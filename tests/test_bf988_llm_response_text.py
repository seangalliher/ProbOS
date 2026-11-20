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
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.guided_reminiscence import (
    GuidedReminiscenceEngine,
    RecallClassification,
    RecallResult,
)
from probos.cognitive.qualification import QualificationHarness, QualificationStore
from probos.cognitive.qualification_tests import EpisodicRecallProbe
from probos.types import LLMResponse, llm_response_text
from tests.test_ad541d_guided_reminiscence import _make_counselor, _make_episode
from tests.test_ad566b_baseline_tests import (
    MockAgent,
    MockEpisode,
    MockEpisodicMemory,
    MockRegistry,
)

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


def _engine(client: Any, episodes: list | None = None) -> GuidedReminiscenceEngine:
    memory = MagicMock()
    # Synchronous on purpose: select_episodes_for_session calls recent_for_agent without await
    # (filed with BF-988), so only a synchronous double reaches run_session's reads.
    memory.recent_for_agent = MagicMock(return_value=list(episodes or []))
    return GuidedReminiscenceEngine(
        episodic_memory=memory, llm_client=client, max_episodes_per_session=3,
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
    result = await _engine(_Client(recall=""), _episodes()).run_session("a1")
    assert [r.recalled_text for r in result.recall_results] == ["", "", ""]


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
