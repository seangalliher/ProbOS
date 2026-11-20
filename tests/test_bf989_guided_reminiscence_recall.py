"""BF-989 (#1838): the Counselor's guided-reminiscence session reads its episodes with ``await`` and scores the
agent's own recall; a session writes no confabulation rate and no alert level.

Every engine here runs over a real ``MockEpisodicMemory`` (async ``recent_for_agent``, as on ``EpisodicMemory``)
and a recording client that answers with real ``LLMResponse``s. No memory is a ``MagicMock``: a synchronous
double is what hid that the read was never awaited.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.counselor import CognitiveProfile
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.guided_reminiscence import GuidedReminiscenceEngine, RecallClassification, RecallResult
from probos.types import LLMResponse
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
    from probos.cognitive.qualification_tests import agent_recall_fn  # imported here: only this case needs the new name

    class _Agent:
        id = "a1"
        agent_type = "crew"

        def __init__(self) -> None:
            self.intents: list[Any] = []

        async def handle_intent(self, intent: Any) -> Any:
            self.intents.append(intent)
            return SimpleNamespace(result="I checked the warp core.")

    agent = _Agent()
    recall = agent_recall_fn(SimpleNamespace(get=lambda agent_id: agent if agent_id == "a1" else None))
    assert await recall("a1", "What happened?") == "I checked the warp core."
    (intent,) = agent.intents
    assert (intent.intent, intent.target_agent_id, intent.params["text"]) == ("direct_message", "a1", "What happened?")
    assert intent.params["_qualification_test"] is True  # suppresses episode storage (CognitiveAgent.handle_intent)
    assert await recall("zz", "What happened?") == ""
    assert len(agent.intents) == 1


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
