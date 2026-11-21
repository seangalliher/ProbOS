"""BF-989 (#1838): the Counselor's guided-reminiscence session reads its episodes with ``await`` and scores the
agent's own recall; a session writes no confabulation rate and no alert level.

Every engine here runs over a real ``MockEpisodicMemory`` (async ``recent_for_agent``, as on ``EpisodicMemory``)
and a recording client that answers with real ``LLMResponse``s. No memory is a ``MagicMock``: a synchronous
double is what hid that the read was never awaited.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.agent_stop import STOP_METADATA_KEY, AgentStopService
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.concurrency_manager import ConcurrencyManager
from probos.cognitive.counselor import CognitiveProfile
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.guided_reminiscence import (
    GuidedReminiscenceEngine,
    RecallClassification,
    RecallResult,
    RecallUnavailable,
)
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.qualification_tests import agent_recall_fn
from probos.config import SystemConfig
from probos.identity import AgentIdentityRegistry
from probos.substrate.registry import AgentRegistry
from probos.types import IntentDescriptor, IntentMessage, IntentResult, LLMResponse
from tests.test_ad541d_guided_reminiscence import _make_counselor, _make_episode

_MESSAGE = "Thank you for reviewing these with me. Let's look at your Ship Memory records together."
_RECALL = "the ship status was checked and it was nominal"
_FABRICATED = "then after the explosion it resulted in cascading failures because specifically the core overloaded"
_RECALL_PROMPT = "I'd like to review"  # how build_recall_prompt starts
_EXPECTED = "ship status check ok"
_ABSTENTIONS = [  # the orchestrator's probe: on the base each is CONFABULATED or CONTAMINATED below 0.3
    "I don't remember exactly what happened.",
    "I'm not sure what happened then.",
    "I do not remember the details of that exchange.",
    "I can't recall that episode.",
    "I don't recall.",
    "I have no memory of this.",
    "Unable to recall.",
]


class _Client:
    """The engine's LLM client: records every prompt; answers the judge and the message with real LLMResponses.

    ``scores`` are the judge's replies in order (an exception is raised); past them it answers "0.9".
    """

    def __init__(self, scores: list[Any] | None = None) -> None:
        self.prompts: list[str] = []
        self._scores = list(scores or [])

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        self.prompts.append(request.prompt)
        if request.prompt.startswith("Score the factual accuracy"):
            reply = self._scores.pop(0) if self._scores else "0.9"
            if isinstance(reply, Exception):
                raise reply
            return LLMResponse(content=reply)
        if request.prompt.startswith("You are a Ship's Counselor"):
            return LLMResponse(content=_MESSAGE)
        return LLMResponse(content="a model's recall")


class _Recall:
    """A recall source: records each (agent_id, prompt) and answers ``reply``, or raises it."""

    def __init__(self, reply: Any = _RECALL) -> None:
        self.calls: list[tuple[str, str]] = []
        self._reply = reply

    async def __call__(self, agent_id: str, prompt: str) -> str:
        self.calls.append((agent_id, prompt))
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


async def _store(memory: MockEpisodicMemory, n: int = 4) -> MockEpisodicMemory:
    for i in range(n):
        await memory.store(_make_episode(ep_id=f"ep-{i}", timestamp=1000.0 + i * 100, agent_ids=["a1"]))
    return memory


async def _engine(client: _Client, recall_fn: Any, **kwargs: Any) -> GuidedReminiscenceEngine:
    """Four stored episodes of a1; the session selects ep-0, ep-1, ep-2 (the most recent is skipped)."""
    return GuidedReminiscenceEngine(
        episodic_memory=await _store(MockEpisodicMemory()), llm_client=client, max_episodes_per_session=3,
        recall_fn=recall_fn, **kwargs,
    )


def _ward_room() -> SimpleNamespace:
    return SimpleNamespace(
        get_or_create_dm_channel=AsyncMock(return_value=SimpleNamespace(id="dm-1")),
        create_thread=AsyncMock(),
    )


# -- N1 to N7: the read, the recall source, what is measured ----------------------------------------


async def test_the_selection_awaits_the_memory_read() -> None:
    awaited: list[str] = []

    class _Counting(MockEpisodicMemory):
        async def recent_for_agent(self, agent_id: str, k: int = 5) -> list:
            awaited.append(agent_id)
            return await super().recent_for_agent(agent_id, k=k)

    memory = await _store(_Counting())
    selected = await GuidedReminiscenceEngine(episodic_memory=memory).select_episodes_for_session("a1", k=3)
    assert awaited == ["a1"]
    assert [ep.id for ep in selected] == ["ep-0", "ep-1", "ep-2"]


async def test_a_session_scores_the_agents_own_recall() -> None:
    client, recall = _Client(), _Recall()
    result = await (await _engine(client, recall)).run_session("a1")
    assert (result.episodes_tested, result.accurate_count, result.unmeasured) == (3, 3, [])
    assert [r.recalled_text for r in result.recall_results] == [_RECALL] * 3
    assert [agent_id for agent_id, _ in recall.calls] == ["a1"] * 3
    assert all(prompt.startswith(_RECALL_PROMPT) for _, prompt in recall.calls)
    assert not any(p.startswith(_RECALL_PROMPT) for p in client.prompts)  # the client only judges and writes
    assert result.therapeutic_message == _MESSAGE


async def test_with_no_recall_source_a_session_measures_nothing_and_asks_no_model() -> None:
    client = _Client()
    result = await (await _engine(client, None)).run_session("a1")
    assert (result.episodes_tested, result.unmeasured, result.recall_results) == (0, ["no agent recall source"], [])
    assert client.prompts == []


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        pytest.param("   ", "empty recall", id="empty"),
        pytest.param(ValueError("agent gone"), "recall failed: ValueError", id="raises"),
    ],
)
async def test_an_unmeasured_recall_is_not_counted(reply: Any, reason: str) -> None:
    client = _Client()
    result = await (await _engine(client, _Recall(reply))).run_session("a1")
    assert result.episodes_tested == 0
    assert result.unmeasured == [f"ep-{i}: {reason}" for i in range(3)]
    assert client.prompts == []  # no judge and no message


async def test_an_inconclusive_judge_leaves_its_episode_unmeasured() -> None:
    client = _Client(["0.9", RuntimeError("judge down"), "0.9"])
    result = await (await _engine(client, _Recall())).run_session("a1")
    assert result.episodes_tested == 2
    assert [r.episode_id for r in result.recall_results] == ["ep-0", "ep-2"]
    assert result.unmeasured == ["ep-1: judge call failed: RuntimeError"]


async def test_a_recall_that_never_returns_times_out() -> None:
    async def _never(_agent_id: str, _prompt: str) -> str:
        await asyncio.Event().wait()
        return ""

    engine = await _engine(_Client(), _never, recall_timeout_seconds=0.01)
    result = await asyncio.wait_for(engine.run_session("a1"), 5)  # bounded here so a missing timeout fails, not hangs
    assert result.episodes_tested == 0
    assert result.unmeasured == [f"ep-{i}: recall timed out" for i in range(3)]


async def test_agent_recall_fn_asks_the_agent_on_the_probe_path() -> None:
    class _Agent:
        """As the runtime holds a crew agent: registered by its slot id; its episodes carry its sovereign id."""

        id = "slot-a1"
        sovereign_id = "a1"
        agent_type = "crew"

        def __init__(self) -> None:
            self.intents: list[Any] = []

        async def handle_intent(self, intent: Any) -> IntentResult:
            self.intents.append(intent)
            return IntentResult(intent_id=intent.id, agent_id=self.id, success=True, result="I checked the warp core.")

    agent = _Agent()
    registry = SimpleNamespace(get=lambda key: agent if key == agent.id else None)
    recall = agent_recall_fn(registry, resolve_slot={"a1": "slot-a1"}.get)
    assert await recall("a1", "What happened?") == "I checked the warp core."
    (intent,) = agent.intents
    assert (intent.intent, intent.target_agent_id, intent.params["text"]) == ("direct_message", "slot-a1", "What happened?")
    assert intent.params["_qualification_test"] is True  # suppresses episode storage (CognitiveAgent.handle_intent)
    assert await agent_recall_fn(registry)("slot-a1", "Again?") == "I checked the warp core."  # a slot key as given
    with pytest.raises(RecallUnavailable, match="^no live agent$"):
        await recall("zz", "What happened?")
    with pytest.raises(RecallUnavailable, match="^no live agent$"):
        await agent_recall_fn(registry)("a1", "What happened?")  # no resolver: the sovereign key reaches no agent
    assert len(agent.intents) == 2


# -- N8 to N10: an abstention is an omission, not a commission ----------------------------------------


@pytest.mark.parametrize("recall", _ABSTENTIONS)
def test_an_abstention_is_partial(recall: str) -> None:
    engine = GuidedReminiscenceEngine(episodic_memory=None)
    assert engine.classify_recall(recall, _EXPECTED, None, 0.1) is RecallClassification.PARTIAL


def test_a_hedge_followed_by_a_claim_stays_confabulated() -> None:
    engine = GuidedReminiscenceEngine(episodic_memory=None)
    recall = f"I'm not sure, but {_FABRICATED}."
    assert engine.classify_recall(recall, _EXPECTED, None, 0.1) is RecallClassification.CONFABULATED


def test_the_rule_does_not_override_a_measured_score() -> None:
    engine = GuidedReminiscenceEngine(episodic_memory=None)
    assert engine.classify_recall("I don't recall.", _EXPECTED, None, 0.75) is RecallClassification.ACCURATE
    assert engine.classify_recall("I don't recall.", _EXPECTED, None, 0.45) is RecallClassification.PARTIAL


# -- N11, N12: the message states no fact it was not given ------------------------------------------------


async def test_the_message_prompt_asks_for_no_fact() -> None:
    client = _Client()
    engine = GuidedReminiscenceEngine(episodic_memory=None, llm_client=client)
    results = [RecallResult(classification=RecallClassification.CONFABULATED, accuracy=0.1) for _ in range(3)]
    assert await engine.build_therapeutic_response("a1", results) == _MESSAGE
    (prompt,) = client.prompts
    assert "Do not state any fact about the episodes." in prompt
    assert "redirect to verified facts" not in prompt


@pytest.mark.parametrize(
    "classifications",
    [
        pytest.param([RecallClassification.CONFABULATED] * 3, id="mostly-confabulated"),
        pytest.param(
            [RecallClassification.CONFABULATED, RecallClassification.PARTIAL, RecallClassification.PARTIAL],
            id="some-gaps",
        ),
    ],
)
async def test_no_template_promises_records_it_does_not_give(classifications: list) -> None:
    engine = GuidedReminiscenceEngine(episodic_memory=None)
    message = await engine.build_therapeutic_response("a1", [RecallResult(classification=c) for c in classifications])
    assert "share" not in message.lower()
    assert "Ship Memory records together" in message


# -- N13 to N15: what a session writes, through the real Counselor --------------------------------------


async def test_a_counselor_session_writes_no_rate_and_no_alert_level() -> None:
    ward_room, events = _ward_room(), []
    counselor = _make_counselor(
        _reminiscence_engine=await _engine(_Client(["0.1"] * 3), _Recall(_FABRICATED)),
        _cognitive_profiles={"a1": CognitiveProfile(agent_id="a1", confabulation_rate=0.12, alert_level="green")},
        _ward_room=ward_room,
        _emit_event_fn=lambda name, payload: events.append((name, payload)),
        callsign="Counselor",
        _record_intervention=MagicMock(),
    )
    await counselor._initiate_reminiscence_session("a1", trigger="bf989")
    profile = counselor._cognitive_profiles["a1"]
    assert profile.confabulation_rate == pytest.approx(0.12)  # the AD-568d/e value, not the session's 1.0
    assert profile.alert_level == "green"
    assert profile.memory_integrity_score == pytest.approx(0.1)
    assert profile.reminiscence_sessions == 1
    ward_room.create_thread.assert_awaited_once()
    assert ward_room.create_thread.await_args.kwargs["body"] == _MESSAGE
    ((name, payload),) = events
    assert name == "reminiscence_session_complete"
    assert payload["confabulation_rate"] == pytest.approx(1.0)
    assert payload["unmeasured"] == 0


async def test_a_failed_session_takes_the_cooldown_and_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    class _FailingEngine:
        def __init__(self) -> None:
            self.calls = 0

        async def run_session(self, agent_id: str) -> Any:
            self.calls += 1
            raise RuntimeError("session broke")

    engine = _FailingEngine()
    counselor = _make_counselor(_reminiscence_engine=engine)
    caplog.set_level(logging.DEBUG, logger="probos.cognitive.counselor")
    await counselor._initiate_reminiscence_session("a1", trigger="bf989")
    await counselor._initiate_reminiscence_session("a1", trigger="bf989")
    assert engine.calls == 1
    failures = [r for r in caplog.records if "Reminiscence session failed" in r.getMessage()]
    assert [r.levelno for r in failures] == [logging.WARNING]


async def test_a_session_that_measured_nothing_writes_sends_and_emits_nothing(caplog: pytest.LogCaptureFixture) -> None:
    store = SimpleNamespace(save_profile=AsyncMock())
    ward_room, events = _ward_room(), []
    counselor = _make_counselor(
        _reminiscence_engine=await _engine(_Client(), _Recall("")),
        _profile_store=store,
        _ward_room=ward_room,
        _emit_event_fn=lambda name, payload: events.append((name, payload)),
    )
    caplog.set_level(logging.INFO, logger="probos.cognitive.counselor")
    await counselor._initiate_reminiscence_session("a1", trigger="bf989")
    assert "a1" not in counselor._cognitive_profiles
    store.save_profile.assert_not_awaited()
    ward_room.create_thread.assert_not_awaited()
    assert events == []
    (line,) = [r.getMessage() for r in caplog.records if "measured no episode" in r.getMessage()]
    assert "ep-0: empty recall" in line


# -- R1 to R4: review round 1 (a crew agent's slot and sovereign ids; a reply that is not a recall) ----------------

_SLOT = "surgeon_medical_surgeon_0_b2321292"
_INSTANCE = "bf989-ship"


class _CrewAgent:
    """A crew agent as the runtime holds one: registered by its slot id; its episodes carry its sovereign id."""

    agent_type = "surgeon"
    pool = "surgeon"
    callsign = "Meridian"

    def __init__(self, sovereign_id: str) -> None:
        self.id = _SLOT
        self.sovereign_id = sovereign_id
        self.intents: list[Any] = []

    async def handle_intent(self, intent: Any) -> IntentResult:
        self.intents.append(intent)
        return IntentResult(intent_id=intent.id, agent_id=self.id, success=True, result=_RECALL)


async def test_a_session_on_the_sovereign_id_measures_and_writes_through_the_slot(tmp_path: Path) -> None:
    identities = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await identities.start()
        await identities.start(instance_id=_INSTANCE, vessel_name="Bf989", version="1")
        cert = await identities.resolve_or_issue(
            slot_id=_SLOT, agent_type="surgeon", callsign="Meridian", instance_id=_INSTANCE,
            vessel_name="Bf989", department="medical", post_id="surgeon", baseline_version="v1",
        )
        sovereign = cert.agent_uuid
        assert sovereign != _SLOT and identities.resolve_slot_id(sovereign) == _SLOT  # premise: BF-907's split
        agent, registry, memory = _CrewAgent(sovereign), AgentRegistry(), MockEpisodicMemory()
        await registry.register(agent)
        for i in range(4):
            await memory.store(_make_episode(ep_id=f"ep-{i}", timestamp=1000.0 + i * 100, agent_ids=[sovereign]))
        engine = GuidedReminiscenceEngine(
            episodic_memory=memory, llm_client=_Client(), max_episodes_per_session=3,
            recall_fn=agent_recall_fn(registry, resolve_slot=identities.resolve_slot_id),
        )
        ward_room, events = _ward_room(), []
        counselor = _make_counselor(
            _registry=registry, _ward_room=ward_room, callsign="Counselor", _record_intervention=MagicMock(),
            _emit_event_fn=lambda name, payload: events.append((name, payload)),
        )
        counselor.set_reminiscence_engine(engine, resolve_slot=identities.resolve_slot_id)
        await counselor._initiate_reminiscence_session(sovereign, trigger="retrieval_concern")
    finally:
        await identities.stop()
    assert [intent.target_agent_id for intent in agent.intents] == [_SLOT] * 3
    profile = counselor._cognitive_profiles[_SLOT]
    assert profile.memory_integrity_score == pytest.approx(0.9)
    assert profile.reminiscence_sessions == 1
    assert sovereign not in counselor._cognitive_profiles
    assert list(counselor._reminiscence_cooldowns) == [_SLOT]
    dm = ward_room.get_or_create_dm_channel.await_args.kwargs
    assert (dm["agent_b_id"], dm["callsign_b"]) == (_SLOT, "Meridian")
    assert list(counselor._dm_cooldowns) == [_SLOT]
    ((name, payload),) = events
    assert (name, payload["agent_id"], payload["episodes_tested"], payload["unmeasured"]) == (
        "reminiscence_session_complete", _SLOT, 3, 0,
    )


async def test_a_key_with_no_live_agent_runs_no_session_and_takes_no_cooldown(caplog: pytest.LogCaptureFixture) -> None:
    engine = SimpleNamespace(run_session=AsyncMock())
    counselor = _make_counselor(_reminiscence_engine=engine, _registry=AgentRegistry())
    caplog.set_level(logging.INFO, logger="probos.cognitive.counselor")
    await counselor._initiate_reminiscence_session("a1", trigger="bf989")
    engine.run_session.assert_not_awaited()
    assert counselor._reminiscence_cooldowns == {}
    assert [r.levelno for r in caplog.records if "no live agent" in r.getMessage()] == [logging.INFO]


def _crew_class() -> type[CognitiveAgent]:
    return type("_BF989Crew", (CognitiveAgent,), {
        "agent_type": "surgeon",
        "_handled_intents": {"bf989_probe"},
        "instructions": "You are a crew member. Respond concisely.",
        "intent_descriptors": [IntentDescriptor(name="bf989_probe", params={}, description="probe", tier="domain")],
    })


class _CountingLLM(MockLLMClient):
    """The agent's model: counts calls; a stopped or saturated agent makes none."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:  # type: ignore[override]
        self.calls += 1
        return LLMResponse(content=_RECALL)


async def _session_of(agent: CognitiveAgent, client: _Client) -> Any:
    registry, memory = AgentRegistry(), MockEpisodicMemory()
    await registry.register(agent)
    for i in range(4):
        await memory.store(_make_episode(ep_id=f"ep-{i}", timestamp=1000.0 + i * 100, agent_ids=[agent.id]))
    engine = GuidedReminiscenceEngine(
        episodic_memory=memory, llm_client=client, max_episodes_per_session=3, recall_fn=agent_recall_fn(registry),
    )
    return await engine.run_session(agent.id)


async def test_a_stopped_or_saturated_agent_gives_no_recall(tmp_path: Path) -> None:
    stopped_llm, saturated_llm, client = _CountingLLM(), _CountingLLM(), _Client()
    stopped = _crew_class()(llm_client=stopped_llm)
    stops = AgentStopService(data_dir=tmp_path / "stops")
    await stops.start()
    try:
        await stops.issue_stop(stopped.id, reason="BF-989 test: this agent is stopped")
        stopped._runtime = SimpleNamespace(agent_stops=stops)
        result = await _session_of(stopped, client)
    finally:
        await stops.stop()
    assert (result.episodes_tested, result.unmeasured) == (0, [f"ep-{i}: agent stopped" for i in range(3)])

    saturated = _crew_class()(llm_client=saturated_llm)
    manager = ConcurrencyManager(saturated.id, max_concurrent=1, queue_max_size=0)
    saturated.set_concurrency_manager(manager)
    held = await manager.acquire("held")
    try:
        result = await _session_of(saturated, client)
    finally:
        await manager.release(held)
    assert (result.episodes_tested, result.unmeasured) == (0, [f"ep-{i}: no response" for i in range(3)])
    assert (stopped_llm.calls, saturated_llm.calls, client.prompts) == (0, 0, [])  # no turn, no judge, no message


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        pytest.param(None, "no reply", id="none"),
        pytest.param(
            IntentResult(intent_id="i", agent_id=_SLOT, success=False, result="Not delivered", error="Not delivered",
                         metadata={STOP_METADATA_KEY: {}}),
            "agent stopped", id="stop",
        ),
        pytest.param(IntentResult(intent_id="i", agent_id=_SLOT, success=False, result="partial"),
                     "agent reply failed", id="failed"),
        pytest.param(IntentResult(intent_id="i", agent_id=_SLOT, success=True, result="text", error="cognitive_failed"),
                     "agent reply failed", id="error"),
        pytest.param(IntentResult(intent_id="i", agent_id=_SLOT, success=True, result="Noted. [NO_RESPONSE]"),
                     "no response", id="silence"),
    ],
)
async def test_a_reply_that_is_not_a_recall_names_its_reason(reply: Any, reason: str) -> None:
    class _Agent:
        id = _SLOT
        agent_type = "surgeon"

        async def handle_intent(self, intent: Any) -> Any:
            return reply

    recall = agent_recall_fn(SimpleNamespace(get=lambda key: _Agent() if key == _SLOT else None))
    with pytest.raises(RecallUnavailable, match=f"^{reason}$"):
        await recall(_SLOT, "What happened?")


# -- R5 to R7: review round 2 (a session leaves nothing behind, and selects no reflection) ----------------------------


async def test_the_selection_leaves_out_the_agents_own_reflections() -> None:
    memory = MockEpisodicMemory()
    for i, source in enumerate(["direct", "reflection", "direct", "reflection", "direct"]):
        await memory.store(_make_episode(ep_id=f"ep-{i}", timestamp=1000.0 + i * 100, agent_ids=["a1"], source=source))
    selected = await GuidedReminiscenceEngine(episodic_memory=memory).select_episodes_for_session("a1", k=3)
    assert [(ep.id, ep.source) for ep in selected] == [("ep-0", "direct"), ("ep-2", "direct"), ("ep-4", "direct")]


async def test_a_memory_of_reflections_alone_leaves_a_session_nothing_to_test() -> None:
    memory, recall = MockEpisodicMemory(), _Recall()
    for i in range(3):
        await memory.store(
            _make_episode(ep_id=f"ep-{i}", timestamp=1000.0 + i * 100, agent_ids=["a1"], source="reflection"),
        )
    engine = GuidedReminiscenceEngine(
        episodic_memory=memory, llm_client=_Client(), max_episodes_per_session=3, recall_fn=recall,
    )
    result = await engine.run_session("a1")
    assert (result.episodes_tested, recall.calls) == (0, [])


def _real_agent(memory: MockEpisodicMemory) -> CognitiveAgent:
    return _crew_class()(
        llm_client=_CountingLLM(), runtime=SimpleNamespace(episodic_memory=memory, config=SystemConfig()),
    )


async def test_a_qualification_turn_leaves_no_episode_and_no_conclusion() -> None:
    seen = []
    for marked in (True, False):
        memory = MockEpisodicMemory()
        agent = _real_agent(memory)
        params = {"text": "What do you recall?", **({"_qualification_test": True} if marked else {})}
        await agent.handle_intent(IntentMessage(intent="bf989_probe", params=params, target_agent_id=agent.id))
        stored = [ep.source for ep in await memory.recent_for_agent(agent.id, k=10)]
        seen.append((stored, len(agent._working_memory.get_active_conclusions())))
    # The unmarked control concludes and stores a reflection, so the pair can tell the two turns apart.
    assert seen == [([], 0), (["reflection"], 1)]


async def test_a_session_over_a_real_agent_stores_nothing_and_never_selects_its_own_replies() -> None:
    memory, registry = MockEpisodicMemory(), AgentRegistry()
    agent = _real_agent(memory)
    await registry.register(agent)
    for i in range(4):
        await memory.store(_make_episode(ep_id=f"ep-{i}", timestamp=1000.0 + i * 100, agent_ids=[agent.id]))
    engine = GuidedReminiscenceEngine(
        episodic_memory=memory, llm_client=_Client(), max_episodes_per_session=3, recall_fn=agent_recall_fn(registry),
    )
    sessions = [await engine.run_session(agent.id) for _ in range(2)]
    assert [[r.episode_id for r in s.recall_results] for s in sessions] == [["ep-0", "ep-1", "ep-2"]] * 2
    assert sorted(ep.id for ep in await memory.recent_for_agent(agent.id, k=10)) == ["ep-0", "ep-1", "ep-2", "ep-3"]


# -- R8, R9: review round 3 (a marked turn leaves no action or reasoning entry; a session's probes never see each other)


def _chain_class() -> type[CognitiveAgent]:
    async def decide(self: CognitiveAgent, observation: dict[str, Any]) -> dict[str, Any]:
        decision = await CognitiveAgent.decide(self, observation)
        # What an enabled sub-task chain returns: AD-645 records the composition brief from these two keys.
        decision.update(
            sub_task_chain=True,
            _composition_brief={"situation": "a recall probe", "response_should_cover": ["the status"]},
        )
        return decision

    return type("_BF989Chain", (_crew_class(),), {"decide": decide})


@pytest.mark.parametrize("chain", [False, True], ids=["plain", "chain"])
async def test_a_qualification_turn_leaves_no_action_and_no_reasoning_in_working_memory(chain: bool) -> None:
    seen = []
    for marked in (True, False):
        agent = (_chain_class() if chain else _crew_class())(
            llm_client=_CountingLLM(),
            runtime=SimpleNamespace(episodic_memory=MockEpisodicMemory(), config=SystemConfig()),
        )
        params = {"text": "What do you recall?", **({"_qualification_test": True} if marked else {})}
        await agent.handle_intent(IntentMessage(intent="bf989_probe", params=params, target_agent_id=agent.id))
        state = agent._working_memory.to_dict()
        seen.append((len(state["recent_actions"]), len(state["recent_reasoning"])))
    # The unmarked control records the action (and, on a chain, the brief), so the pair can tell the two turns apart.
    assert seen == [(0, 0), (1, 1 if chain else 0)]


class _EchoLLM(MockLLMClient):
    """The agent's model: every reply carries its own number, and every request is kept."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[str] = []

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:  # type: ignore[override]
        self.requests.append(f"{getattr(request, 'system_prompt', '')}\n{getattr(request, 'prompt', '')}")
        return LLMResponse(content=f"RECALL-NUMBER-{len(self.requests)}: the ship status was checked and it was nominal")


async def test_a_session_never_shows_the_agent_its_own_earlier_recall_replies() -> None:
    memory, registry, llm = MockEpisodicMemory(), AgentRegistry(), _EchoLLM()
    agent = _crew_class()(llm_client=llm, runtime=SimpleNamespace(episodic_memory=memory, config=SystemConfig()))
    await registry.register(agent)
    for i in range(4):
        await memory.store(_make_episode(ep_id=f"ep-{i}", timestamp=1000.0 + i * 100, agent_ids=[agent.id]))
    engine = GuidedReminiscenceEngine(
        episodic_memory=memory, llm_client=_Client(), max_episodes_per_session=3, recall_fn=agent_recall_fn(registry),
    )
    await engine.run_session(agent.id)
    assert len(llm.requests) == 3  # one turn per episode, and nothing else asks the agent's model
    assert [[f"RECALL-NUMBER-{n}" in request for n in (1, 2, 3)] for request in llm.requests] == [[False] * 3] * 3
