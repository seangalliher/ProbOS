"""BF-922 (#1639) M2: the single-call fallback runs the chain's deterministic output checks; the BF-206 line names the agent.

The contract is ``prompts/bf-922-output-gate-grounding-and-fallback.md``. Real code from ``decide()`` through AD-643a's
routing, the triage or chain failure, the fallback flag, ``_decide_via_llm`` and the gate. Stand-ins, named: the model
client (``_OneShotClient``: one scripted reply), the chain executor (raises on triage, or returns a triage and then
raises), ``_check_procedural_memory`` (no procedure), and ``_build_user_message`` (returns ``THREAD``, so the request's
text is known). The runtime is ``MagicMock(spec=ProbOSRuntime)`` with a real ``SystemConfig`` and a trust network that
answers 0.5; any further attribute the routing path reads that a spec'd mock cannot answer is set on the mock here and
named in this docstring. The transport tests (BF-922 A1) swap in the real ``OpenAICompatibleClient``, whose HTTP clients
answer through ``httpx.MockTransport`` per host as in tests/test_ad835_tier_adaptation.py, and set
``runtime.config.cognitive`` to that client's config; only the HTTP endpoints are stand-ins there.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from probos.cognitive.cognitive_agent import (
    CHAIN_FALLBACK_KEY,
    CognitiveAgent,
    _CACHE_HITS,
    _CACHE_MISSES,
    _DECISION_CACHES,
)
from probos.cognitive.llm_client import MockLLMClient, OpenAICompatibleClient
from probos.cognitive.sub_task import (
    SubTaskChain,
    SubTaskError,
    SubTaskExecutor,
    SubTaskResult,
    SubTaskSpec,
    SubTaskType,
)
from probos.config import CognitiveConfig, SystemConfig
from probos.events import EventType
from probos.runtime import ProbOSRuntime
from probos.types import LLMRequest, LLMResponse

THREAD_ID = "1ce6b514-9b54-4c2e-8f0a-2b7c9d3e4f51"
POST_ID = "c71f7ab2-e9d5-4a10-b2c3-d4e5f6a7b8c9"
THREAD = (
    "[Ward Room — #medical]\nThread: Post-stasis readiness\n"
    f"[{POST_ID[:8]}] Meridian: Surgeon GREEN post-stasis; all medical systems nominal."
)
INVENTED = "Per post 7f3a9c2e and thread b81d04aa, the backlog cleared."
GROUNDED = f"Agreed with {POST_ID[:8]}; nothing to add on thread {THREAD_ID[:8]}."
RAW_JSON = '{"intents": [{"intent": "ward_room_post"}]}'
GIVEN_BY_TIER = "Reference records available to this tier: post 7f3a9c2e and thread b81d04aa."


class _CrewAgent(CognitiveAgent):
    agent_type = "science_officer"
    _handled_intents = {"ward_room_notification", "test"}
    instructions = "You are a test crew agent."


class _OneShotClient(MockLLMClient):
    """Answers every request with one scripted reply and records the requests."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self._response = LLMResponse(content=content, model="test-model")
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return self._response


@pytest.fixture(autouse=True)
def _clear_decision_caches() -> None:
    _DECISION_CACHES.clear()
    _CACHE_HITS.clear()
    _CACHE_MISSES.clear()


def _agent(reply: str, *, execute: Any) -> tuple[_CrewAgent, MagicMock]:
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.config = SystemConfig()
    runtime.trust_network = MagicMock()
    runtime.trust_network.get_score.return_value = 0.5
    agent = _CrewAgent(llm_client=_OneShotClient(reply), runtime=runtime)
    agent.callsign = "Kira"
    agent._check_procedural_memory = AsyncMock(return_value=None)
    agent._build_user_message = AsyncMock(return_value=THREAD)
    executor = MagicMock(spec=SubTaskExecutor)
    executor.enabled = True
    executor.can_execute.return_value = True
    executor.execute = execute
    agent._sub_task_executor = executor
    return agent, runtime


def _observation() -> dict[str, Any]:
    return {
        "intent": "ward_room_notification",
        "intent_id": "intent-1",
        "context": THREAD,
        "params": {
            "thread_id": THREAD_ID,
            "channel_id": "",
            "channel_name": "medical",
            "title": "Post-stasis readiness",
            "author_id": "meridian",
            "author_callsign": "Meridian",
        },
    }


def _suppression_events(runtime: MagicMock) -> list[dict[str, Any]]:
    return [
        call.args[1] for call in runtime.emit_event.call_args_list
        if call.args and call.args[0] == EventType.CONFABULATION_SUPPRESSED
    ]


@pytest.mark.asyncio
async def test_a_triage_failure_fallback_citing_invented_ids_is_suppressed(caplog) -> None:
    agent, runtime = _agent(INVENTED, execute=AsyncMock(side_effect=SubTaskError("triage timed out")))
    observation = _observation()

    with caplog.at_level(logging.INFO):
        decision = await agent.decide(observation)

    assert agent._sub_task_executor.execute.await_args.args[0].source.endswith(":triage")  # the real triage ran
    assert agent._llm_client.requests, "the fallback single call was made"
    assert decision["llm_output"] == "[NO_RESPONSE]"
    assert decision["_suppressed"] is True
    assert decision["_suppression_reason"] == "confabulation_detected"
    (event,) = _suppression_events(runtime)
    assert event["path"] == "single_call_fallback"
    assert "BF-922: Single-call fallback output suppressed for science_officer Kira" in caplog.text
    assert "path=single_call_fallback) — 2 ungrounded hex IDs: ['7f3a9c2e', 'b81d04aa']" in caplog.text
    assert CHAIN_FALLBACK_KEY not in observation


@pytest.mark.asyncio
async def test_a_fallback_reply_citing_given_ids_is_posted() -> None:
    """The post id is in the request's user prompt; the thread id is the intent's own (BF-233)."""
    agent, runtime = _agent(GROUNDED, execute=AsyncMock(side_effect=SubTaskError("triage timed out")))

    decision = await agent.decide(_observation())

    assert decision["llm_output"] == GROUNDED
    assert not decision.get("_suppressed")
    assert _suppression_events(runtime) == []


@pytest.mark.asyncio
async def test_a_chain_failure_after_triage_is_gated_too() -> None:
    triage = [
        SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE, name="analyze-reply", result={"intended_actions": ["ward_room_reply"]},
        ),
    ]
    agent, _ = _agent(INVENTED, execute=AsyncMock(side_effect=[triage, SubTaskError("compose timed out")]))

    decision = await agent.decide(_observation())

    assert agent._sub_task_executor.execute.await_count == 2
    assert decision["_suppression_reason"] == "confabulation_detected"


@pytest.mark.asyncio
async def test_raw_intent_json_on_the_fallback_is_suppressed() -> None:
    agent, _ = _agent(RAW_JSON, execute=AsyncMock(side_effect=SubTaskError("triage timed out")))

    decision = await agent.decide(_observation())

    assert decision["_suppression_reason"] == "raw_json_output"


@pytest.mark.asyncio
async def test_an_external_chain_fallback_is_gated_for_a_chain_intent() -> None:
    agent, _ = _agent(INVENTED, execute=AsyncMock(side_effect=SubTaskError("external chain failed")))
    agent._pending_sub_task_chain = SubTaskChain(
        steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="external-compose")], source="external",
    )
    agent._load_augmentation_skills = MagicMock(return_value="")

    decision = await agent.decide(_observation())

    assert decision["_suppression_reason"] == "confabulation_detected"


@pytest.mark.asyncio
async def test_a_single_call_that_answers_no_chain_is_not_gated() -> None:
    agent, runtime = _agent(INVENTED, execute=AsyncMock(side_effect=AssertionError("no chain runs for this intent")))

    decision = await agent.decide({"intent": "test", "params": {"q": "hello"}, "context": ""})

    assert decision["llm_output"] == INVENTED
    assert _suppression_events(runtime) == []


@pytest.mark.asyncio
async def test_the_chain_suppression_log_line_names_the_agent(caplog) -> None:
    agent = CognitiveAgent.__new__(CognitiveAgent)  # as tests/test_bf206_confab_feedback.py builds it
    agent.id = "agent-1"
    agent.agent_type = "science_officer"
    agent.callsign = "Kira"
    agent._runtime = MagicMock()
    executor = MagicMock()
    executor.can_execute.return_value = True
    executor.execute = AsyncMock(return_value=[
        SubTaskResult(sub_task_type=SubTaskType.COMPOSE, name="compose-reply", result={"output": "x"}),
        SubTaskResult(sub_task_type=SubTaskType.EVALUATE, name="evaluate-reply", result={"recommendation": "suppress"}),
    ])
    agent._sub_task_executor = executor
    chain = MagicMock()
    chain.source = "test"
    chain.steps = [MagicMock()]

    with caplog.at_level(logging.INFO, logger="probos.cognitive.cognitive_agent"):
        await agent._execute_sub_task_chain(chain, {"intent": "ward_room_notification"})

    assert (
        "BF-206: Chain output suppressed for science_officer Kira (agent-1)"
        " — Evaluate recommended suppress (quality_gate)"
    ) in caplog.text


# --- the answering attempt's system message (BF-922 A1, round 1 M2 finding 1) ------------------------


def _tiered_config(**suffixes: str) -> CognitiveConfig:
    """Three endpoints, and the AD-835 per-tier system-prompt suffixes named (unnamed tiers keep None)."""
    return CognitiveConfig(
        llm_base_url_fast="http://fast.local/v1", llm_model_fast="fast-model",
        llm_base_url_standard="http://standard.local/v1", llm_model_standard="standard-model",
        llm_base_url_deep="http://deep.local/v1", llm_model_deep="deep-model",
        **{f"llm_system_prompt_suffix_{tier}": text for tier, text in suffixes.items()},
    )


async def _over_transport(
    config: CognitiveConfig, answer: str, sent: list[tuple[str, dict[str, Any]]],
    *, answering_host: str = "standard.local",
) -> OpenAICompatibleClient:
    """The real client; ``answering_host`` answers ``answer`` and every other host returns 503 ("": none answers)."""
    client = OpenAICompatibleClient(config=config)

    def dispatch(http_request: httpx.Request) -> httpx.Response:
        sent.append((http_request.url.host, json.loads(http_request.content)))
        if http_request.url.host != answering_host:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(200, json={
            "model": "standard-model",
            "choices": [{"message": {"content": answer}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        })

    for key, existing in list(client._clients.items()):
        await existing.aclose()
        client._clients[key] = httpx.AsyncClient(
            base_url=existing.base_url, transport=httpx.MockTransport(dispatch), timeout=5.0,
        )
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("suffixes", "requested_tier", "suppressed"),
    [
        ({"standard": GIVEN_BY_TIER}, None, False),
        ({"standard": GIVEN_BY_TIER, "deep": "A different tier addendum."}, "deep", False),
        ({"deep": GIVEN_BY_TIER}, "deep", True),
    ],
    ids=["serving_tier_suffix", "retry_serving_tier_suffix", "ids_only_in_failed_attempt"],
)
async def test_the_fallback_grounds_on_the_answering_attempts_system_message(
    suffixes: dict[str, str], requested_tier: str | None, suppressed: bool,
) -> None:
    """The real client appends the answering attempt's AD-835 suffix after the request is built. Ids given only there
    ground the reply, directly or after deep and fast fail; ids given only to a failed attempt do not."""
    sent: list[tuple[str, dict[str, Any]]] = []
    config = _tiered_config(**suffixes)
    client = await _over_transport(config, INVENTED, sent)
    try:
        agent, runtime = _agent(INVENTED, execute=AsyncMock(side_effect=SubTaskError("triage timed out")))
        runtime.config.cognitive = config
        agent._llm_client = client  # the real client, as the round-1 review's probe drove it
        observation = _observation()
        if requested_tier is not None:
            observation["level_llm_tier"] = requested_tier
        decision = await agent.decide(observation)
    finally:
        await client.close()

    host, payload = sent[-1]
    answered_system = payload["messages"][0]["content"]
    assert host == "standard.local"
    if requested_tier is not None:
        assert sent[0][0] == "deep.local"  # the requested tier failed first
    if suppressed:
        assert "7f3a9c2e" in sent[0][1]["messages"][0]["content"]  # the failed attempt was given the ids
    assert ("7f3a9c2e" in answered_system and "b81d04aa" in answered_system) is not suppressed
    assert bool(decision.get("_suppressed")) is suppressed
    assert decision["llm_output"] == ("[NO_RESPONSE]" if suppressed else INVENTED)


@pytest.mark.asyncio
async def test_a_cache_replay_keeps_the_answering_attempts_suffix() -> None:
    """A replay was produced under its first attempt's suffix; without it the fallback gate would suppress a grounded
    reply the client served from its cache."""
    sent: list[tuple[str, dict[str, Any]]] = []
    client = await _over_transport(_tiered_config(), GROUNDED, sent, answering_host="")
    request = LLMRequest(prompt="hi", system_prompt="BASE", tier="standard")
    client._cache[client._cache_key("standard", request.prompt, request.system_prompt)] = LLMResponse(
        content=GROUNDED, model="standard-model", applied_system_suffix=GIVEN_BY_TIER,
    )
    try:
        replay = await client.complete(request)
    finally:
        await client.close()

    assert sent, "premise: the tiers were tried and failed"
    assert replay.cached is True and replay.content == GROUNDED
    assert replay.applied_system_suffix == GIVEN_BY_TIER
