"""BF-988 (#1523 F-19): an LLM reply's text is read through ``probos.types.llm_response_text``.

``LLMResponse`` carries its text in ``content`` and has no ``text`` attribute, so the three
``response.text ... if hasattr(response, 'text') else str(response)`` reads in
``guided_reminiscence.py`` took the dataclass repr: ``score_recall`` returned 0.5 for a reply that is
only a number (the repr wraps it in ``content='...'``, which the parse skips; a number inside a
sentence was parsed out of the repr by accident), ``build_therapeutic_response`` returned the repr,
and ``run_session`` recalled it. Every
regression case here answers with a real ``LLMResponse``; the ``.text``-only doubles are the
compatibility cases (the four in ``test_ad541d_guided_reminiscence.py`` stay as they are).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.collective_tests import ScaffoldDecompositionProbe
from probos.cognitive.drift_detector import DriftDetector
from probos.cognitive.guided_reminiscence import (
    GuidedReminiscenceEngine,
    RecallClassification,
    RecallResult,
)
from probos.cognitive.qualification import QualificationHarness, QualificationStore
from probos.cognitive.qualification import TestResult as StoredResult
from probos.cognitive.qualification_tests import ConfabulationProbe, EpisodicRecallProbe, PersonalityProbe
from probos.config import QualificationConfig
from probos.types import LLMResponse, llm_response_text
from tests.test_ad541d_guided_reminiscence import _make_counselor, _make_episode
from tests.test_ad566b_baseline_tests import (
    MockAgent,
    MockEpisode,
    MockEpisodicMemory,
    MockRegistry,
)
from tests.test_ad566e_collective_tests import MockCrewAgent, _build_runtime

_SCORE = "0.8"
_RECALL = "the ship status was checked and it was nominal"
_MESSAGE = "Good session. Your recall matched the records."


class _Client:
    """Answers like ``BaseLLMClient.complete``: with a real ``LLMResponse``, by prompt."""

    def __init__(
        self,
        *,
        score: str = _SCORE,
        recall: str = _RECALL,
        message: str = _MESSAGE,
        error: str | None = None,
    ) -> None:
        self._score = score
        self._recall = recall
        self._message = message
        self._error = error

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        prompt = request.prompt
        if prompt.startswith("Score the factual accuracy"):
            content = self._score
        elif prompt.startswith("You are a Ship's Counselor"):
            content = self._message
        else:
            content = self._recall
        return LLMResponse(
            content=content,
            model="m",
            tier="fast",
            error=self._error,
            answered_tier="fast",
            answered_model="provider-echo",
        )


class _ObjectClient:
    """A client whose reply is neither an ``LLMResponse`` nor a ``.text`` double."""

    async def complete(self, request: Any, **_kwargs: Any) -> object:
        return object()


async def _agent_recall(_agent_id: str, _prompt: str) -> str:
    """The agent's own recall (BF-989): the engine no longer asks the client for it."""
    return _RECALL


def _engine(client: Any, episodes: list | None = None) -> GuidedReminiscenceEngine:
    memory = MagicMock()
    # BF-989 (#1838): async, as on both memories; the selection now awaits recent_for_agent, which the
    # synchronous double (filed with BF-988) stood in for. The recall is recall_fn's; the client judges and
    # writes the message.
    memory.recent_for_agent = AsyncMock(return_value=list(episodes or []))
    return GuidedReminiscenceEngine(
        episodic_memory=memory, llm_client=client, max_episodes_per_session=3, recall_fn=_agent_recall,
    )


def _episodes() -> list:
    return [
        _make_episode(ep_id=f"ep-{i}", timestamp=time.time() - (i + 1) * 1000, agent_ids=["a1"])
        for i in range(4)
    ]


def _results() -> list[RecallResult]:
    return [RecallResult(classification=RecallClassification.PARTIAL, accuracy=0.5) for _ in range(3)]


def _mock_with_text(text: str) -> MagicMock:
    double = MagicMock()
    double.text = text
    return double


# -- T1: the reader -------------------------------------------------------------


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        pytest.param(lambda: LLMResponse(content="  0.9 \n"), "0.9", id="content-stripped"),
        pytest.param(lambda: LLMResponse(content=""), "", id="empty-content"),
        pytest.param(lambda: LLMResponse(content="0.9", error="tier unavailable"), "", id="error-with-content"),
        pytest.param(lambda: LLMResponse(content="", error="All LLM tiers unavailable (x)"), "", id="error-empty"),
        pytest.param(lambda: LLMResponse(content="ok", error=""), "ok", id="empty-error-is-no-error"),
        pytest.param(lambda: SimpleNamespace(text=" 0.7 "), "0.7", id="text-only"),
        pytest.param(lambda: _mock_with_text("0.9"), "0.9", id="mock-with-text"),
        pytest.param(lambda: MagicMock(), "", id="bare-mock"),
        pytest.param(lambda: SimpleNamespace(content="a", text="b"), "a", id="content-wins"),
        pytest.param(lambda: SimpleNamespace(content=None, text="x"), "x", id="content-not-a-str"),
        pytest.param(lambda: object(), "", id="neither"),
        pytest.param(lambda: None, "", id="none"),
    ],
)
def test_the_reader_returns_the_reply_text_and_never_a_repr(make: Any, expected: str) -> None:
    result = llm_response_text(make())
    assert isinstance(result, str)
    assert result == expected


# -- T2: score_recall -----------------------------------------------------------


@pytest.mark.parametrize(("reply", "expected"), [("0.9", 0.9), ("0.1", 0.1), ("Score: 0.75.", 0.75)])
async def test_score_recall_parses_a_real_llm_response(reply: str, expected: float) -> None:
    assert await _engine(_Client(score=reply)).score_recall("recall", "expected") == pytest.approx(expected)


async def test_score_recall_treats_an_error_reply_as_unparseable() -> None:
    engine = _engine(_Client(score="0.9", error="tier unavailable"))
    assert await engine.score_recall("recall", "expected") == 0.5


# -- T3: build_therapeutic_response ----------------------------------------------


async def test_the_therapeutic_message_is_the_reply_content() -> None:
    engine = _engine(_Client(message="  Well done, Lieutenant.  \n"))
    assert await engine.build_therapeutic_response("a1", _results()) == "Well done, Lieutenant."


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda: _Client(message=""), id="empty-reply"),
        pytest.param(lambda: _Client(message="ignored", error="tier unavailable"), id="error-reply"),
        pytest.param(lambda: _ObjectClient(), id="not-a-response"),
    ],
)
async def test_a_reply_without_text_falls_to_the_template(make: Any) -> None:
    template = await _engine(None).build_therapeutic_response("a1", _results())
    message = await _engine(make()).build_therapeutic_response("a1", _results())
    assert message == template
    assert not message.startswith("LLMResponse(")
    assert "provider-echo" not in message


# -- T4, T6: run_session ---------------------------------------------------------


async def test_run_session_reads_each_reply_content() -> None:
    result = await _engine(_Client(), _episodes()).run_session("a1")
    assert result.episodes_tested == 3
    assert [r.recalled_text for r in result.recall_results] == [_RECALL] * 3
    assert all(r.accuracy == pytest.approx(0.8) for r in result.recall_results)
    assert result.therapeutic_message == _MESSAGE


async def test_run_session_never_recalls_a_repr() -> None:
    # BF-989 (#1838): the recall now comes from recall_fn, so the client is never asked for it; the recalled
    # text is the agent's reply, never a response's repr. Was: the client's empty recall read as "".
    prompts: list[str] = []

    class _Recording(_Client):
        async def complete(self, request: Any, **kwargs: Any) -> LLMResponse:
            prompts.append(request.prompt)
            return await super().complete(request, **kwargs)

    result = await _engine(_Recording(recall="a model's recall"), _episodes()).run_session("a1")
    assert [r.recalled_text for r in result.recall_results] == [_RECALL] * 3
    assert not any(p.startswith("I'd like to review") for p in prompts)


# -- T5: the .text compatibility case ---------------------------------------------


async def test_a_text_only_double_still_scores() -> None:
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=_mock_with_text("0.7"))
    assert await _engine(llm).score_recall("recall", "expected") == pytest.approx(0.7)


# -- T7: end to end through the Counselor's DM ------------------------------------


async def test_the_counselor_dm_body_is_the_reply_content() -> None:
    ward_room = SimpleNamespace(
        get_or_create_dm_channel=AsyncMock(return_value=SimpleNamespace(id="dm-1")),
        create_thread=AsyncMock(),
    )
    counselor = _make_counselor(
        _reminiscence_engine=_engine(_Client(), _episodes()),
        _ward_room=ward_room,
        callsign="Counselor",
        _record_intervention=MagicMock(),
    )
    await counselor._initiate_reminiscence_session("a1", trigger="bf988")
    ward_room.create_thread.assert_awaited_once()
    body = ward_room.create_thread.await_args.kwargs["body"]
    assert body == _MESSAGE
    assert not body.startswith("LLMResponse(")


# -- T8: the production path (AD-566 D2) ------------------------------------------


def _probe_runtime(client: Any) -> MagicMock:
    episodes = [MockEpisode(id=f"ep-{i}", user_input=f"Task {i}", timestamp=float(i)) for i in range(3)]
    runtime = MagicMock()
    runtime.registry = MockRegistry(MockAgent(response="I analyzed trust patterns and the task was successful."))
    runtime.llm_client = client
    runtime.episodic_memory = MockEpisodicMemory(episodes, 3)
    return runtime


@pytest.mark.parametrize(("reply", "score", "passed"), [("0.9", 0.9, True), ("0.2", 0.2, False)])
async def test_the_episodic_recall_probe_scores_a_real_reply(reply: str, score: float, passed: bool) -> None:
    result = await EpisodicRecallProbe().run("agent-1", _probe_runtime(_Client(score=reply)))
    assert result.error is None
    assert result.inconclusive is False
    assert result.score == pytest.approx(score)
    assert result.passed is passed


# -- T9 to T12: a judge that failed is not a measurement (review round 1, F2; BF-711) -------------


class _SequenceClient:
    """Answers each judge call with the next entry: a reply text, an ``LLMResponse``, or an exception to raise."""

    def __init__(self, replies: list[Any]) -> None:
        self._replies = list(replies)

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, LLMResponse) else LLMResponse(content=reply)


_UNPARSEABLE = "judge returned unparseable output"
_RAISED = "judge call failed: RuntimeError"


@pytest.mark.parametrize(
    ("reply", "score", "reason"),
    [
        pytest.param("0.9", 0.9, "", id="number"),
        pytest.param("0.5", 0.5, "", id="a-judge-that-says-0.5"),
        pytest.param("I cannot score this", 0.5, _UNPARSEABLE, id="prose"),
        pytest.param(LLMResponse(content="", error="tier unavailable"), 0.5, _UNPARSEABLE, id="error-reply"),
        pytest.param(RuntimeError("proxy down"), 0.5, _RAISED, id="raises"),
        pytest.param(None, 1.0, "", id="no-client-jaccard"),
    ],
)
async def test_score_recall_outcome_says_why_a_score_is_the_fallback(reply: Any, score: float, reason: str) -> None:
    client = None if reply is None else _SequenceClient([reply])
    outcome = await _engine(client).score_recall_outcome("a b c", "a b c")
    assert (outcome.score, outcome.inconclusive) == (pytest.approx(score), reason)


async def test_an_empty_expected_summary_is_a_measurement_and_asks_no_judge() -> None:
    outcome = await _engine(_SequenceClient([])).score_recall_outcome("anything", "")
    assert (outcome.score, outcome.inconclusive) == (1.0, "")


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        pytest.param(RuntimeError("proxy down"), _RAISED, id="raises"),
        pytest.param(LLMResponse(content="", error="tier unavailable"), _UNPARSEABLE, id="error-reply"),
    ],
)
async def test_the_probe_holds_a_failed_judge_out_of_drift(reply: Any, reason: str) -> None:
    result = await EpisodicRecallProbe().run("agent-1", _probe_runtime(_SequenceClient([reply] * 3)))
    assert result.inconclusive is True
    assert result.passed is False
    assert result.error == f"3/3 episodes: {reason}"
    assert result.score == pytest.approx(0.5)
    assert [e["judge"] for e in result.details["per_episode"]] == [reason] * 3


async def test_one_failed_judge_makes_the_run_inconclusive_and_never_a_baseline(tmp_path: Path) -> None:
    store = QualificationStore(data_dir=tmp_path)
    await store.start()
    try:
        harness = QualificationHarness(store=store)
        harness.register_test(EpisodicRecallProbe())
        runtime = _probe_runtime(_SequenceClient(["0.9", "no number here", "0.9"]))
        first = await harness.run_test("agent-1", "episodic_recall_probe", runtime)
        assert first.inconclusive is True
        assert first.passed is False
        assert first.error == f"1/3 episodes: {_UNPARSEABLE}"
        assert ["judge" in e for e in first.details["per_episode"]] == [False, True, False]
        assert first.is_baseline is False
        assert await store.get_baseline("agent-1", "episodic_recall_probe") is None
        second = await harness.run_test("agent-1", "episodic_recall_probe", _probe_runtime(_SequenceClient(["0.9"] * 3)))
        assert second.inconclusive is False
        assert second.is_baseline is True
    finally:
        await store.stop()


async def test_a_judge_that_replies_0_5_is_a_measurement() -> None:
    result = await EpisodicRecallProbe().run("agent-1", _probe_runtime(_SequenceClient(["0.5"] * 3)))
    assert (result.inconclusive, result.error, result.passed) == (False, None, True)
    assert result.score == pytest.approx(0.5)
    assert all("judge" not in e for e in result.details["per_episode"])


# -- T13 to T18: the collective probe inherits a failed judge (review round 2, R2-1) -------------------

_FAILED_JUDGE = {"passed": False, "error": f"3/3 episodes: {_RAISED}", "inconclusive": True}  # as the recall probe stores one


def _tier1_row(agent_id: str, test_name: str, score: float, ts: float = 1000.0, **fields: Any) -> StoredResult:
    base: dict[str, Any] = {
        "agent_id": agent_id, "test_name": test_name, "tier": 1, "score": score, "passed": True,
        "timestamp": ts, "duration_ms": 1.0,
    }
    return StoredResult(**{**base, **fields})


def _collective_row(score: float, ts: float) -> StoredResult:
    return StoredResult(
        agent_id="__crew__", test_name="scaffold_decomposition", tier=3, score=score, passed=True,
        timestamp=ts, duration_ms=1.0,
    )


@asynccontextmanager
async def _collective(
    tmp_path: Path,
    *,
    recall: dict[str, Any] | None = None,
    personality: dict[str, Any] | None = None,
    confabulation: dict[str, Any] | None = None,
    emitted: list[str] | None = None,
) -> AsyncIterator[tuple[QualificationStore, QualificationHarness, MagicMock]]:
    """Two crew members' stored Tier-1 rows (personality 1.0, recall 0.5, confabulation 0.9, each with the given
    extra fields), a real store and harness holding the real probes, and a runtime that reaches them."""
    store = QualificationStore(data_dir=tmp_path)
    await store.start()
    try:
        harness = QualificationHarness(
            store=store, emit_event_fn=None if emitted is None else (lambda name, _payload: emitted.append(name)),
        )
        for probe in (PersonalityProbe(), EpisodicRecallProbe(), ConfabulationProbe(), ScaffoldDecompositionProbe()):
            harness.register_test(probe)
        for agent_id in ("a1", "a2"):
            await store.save_result(_tier1_row(agent_id, "bfi2_personality_probe", 1.0, **(personality or {})))
            await store.save_result(_tier1_row(agent_id, "episodic_recall_probe", 0.5, **(recall or {})))
            await store.save_result(_tier1_row(agent_id, "confabulation_probe", 0.9, **(confabulation or {})))
        runtime = _build_runtime(agents=[MockCrewAgent("a1"), MockCrewAgent("a2")], harness=harness, store=store)
        yield store, harness, runtime
    finally:
        await store.stop()


async def test_a_failed_judge_makes_the_collective_result_inconclusive(tmp_path: Path) -> None:
    async with _collective(tmp_path, recall=_FAILED_JUDGE) as (_store, _harness, runtime):
        result = await ScaffoldDecompositionProbe().run("any", runtime)

    assert result.inconclusive is True
    assert result.passed is False
    assert result.error == "2 Tier-1 result(s) inconclusive: episodic_recall_probe"
    assert result.details["inconclusive_inputs"] == ["a1:episodic_recall_probe", "a2:episodic_recall_probe"]
    assert result.score == pytest.approx(0.7308)  # the aggregate over the inputs that were measured, kept for forensics


async def test_an_inconclusive_collective_result_is_never_a_baseline(tmp_path: Path) -> None:
    emitted: list[str] = []
    async with _collective(tmp_path, recall=_FAILED_JUDGE, emitted=emitted) as (store, harness, runtime):
        first = await harness.run_test("__crew__", "scaffold_decomposition", runtime)
        assert first.inconclusive is True
        assert first.is_baseline is False
        assert await store.get_baseline("__crew__", "scaffold_decomposition") is None
        assert "qualification_baseline_set" not in emitted

        for agent_id in ("a1", "a2"):  # the judge recovers: the same series takes its baseline from a measurement
            await store.save_result(_tier1_row(agent_id, "episodic_recall_probe", 0.9, ts=2000.0))
        second = await harness.run_test("__crew__", "scaffold_decomposition", runtime)
        assert second.inconclusive is False
        assert second.is_baseline is True
        assert "qualification_baseline_set" in emitted


async def test_an_inconclusive_collective_result_stays_out_of_the_drift_history(tmp_path: Path) -> None:
    async with _collective(tmp_path, recall=_FAILED_JUDGE) as (store, harness, runtime):
        detector = DriftDetector(store, QualificationConfig())
        for i in range(19):  # the earlier weekly aggregates, all measured
            await store.save_result(_collective_row(0.6667, ts=100.0 + i))
        run = await harness.run_test("__crew__", "scaffold_decomposition", runtime)
        assert run.inconclusive is True

        signal = (await detector.analyze_agent("__crew__", ["scaffold_decomposition"])).signals[0]
        assert (signal.severity, signal.sample_count) == ("normal", 19)

        # the control: the same aggregate stored as a measurement is critical drift
        await store.save_result(_collective_row(run.score, ts=run.timestamp + 1.0))
        control = (await detector.analyze_agent("__crew__", ["scaffold_decomposition"])).signals[0]
        assert control.severity == "critical"


async def test_a_collective_result_with_no_measured_input_is_inconclusive_and_not_a_skip(tmp_path: Path) -> None:
    async with _collective(
        tmp_path, recall=_FAILED_JUDGE, personality=_FAILED_JUDGE, confabulation=_FAILED_JUDGE,
    ) as (_store, _harness, runtime):
        result = await ScaffoldDecompositionProbe().run("any", runtime)

    assert result.inconclusive is True
    assert result.details["skipped"] is False
    assert result.score == 0.0
    assert result.error == "6 Tier-1 result(s) inconclusive: bfi2_personality_probe, confabulation_probe, episodic_recall_probe"


async def test_an_input_that_timed_out_is_still_dropped_from_the_aggregate(tmp_path: Path) -> None:
    async with _collective(tmp_path, recall={"passed": False, "error": "Test timed out"}) as (_store, _harness, runtime):
        result = await ScaffoldDecompositionProbe().run("any", runtime)

    assert (result.inconclusive, result.error, result.passed) == (False, None, True)
    assert result.details["tests_measured"] == 2
    assert "inconclusive_inputs" not in result.details
    assert result.score == pytest.approx(0.7308)


async def test_a_collective_result_over_measured_inputs_is_what_it_was(tmp_path: Path) -> None:
    async with _collective(tmp_path) as (_store, _harness, runtime):
        result = await ScaffoldDecompositionProbe().run("any", runtime)

    assert (result.inconclusive, result.error, result.passed) == (False, None, True)
    assert result.details["tests_measured"] == 3
    assert "inconclusive_inputs" not in result.details
    assert result.score == pytest.approx(0.6667)
