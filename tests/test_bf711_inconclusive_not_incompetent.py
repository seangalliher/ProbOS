"""BF-711 (#1122): an LLM outage read as an agent that had got worse.

`_score_response` had three failure paths -- no judge configured, the judge's
transport raised, the judge returned unparseable output -- and all three
returned a bare `CommunicationScore()`. Its five dimensions default to `0.0`, so
`composite` is `0.0`, so the `TestResult` carries `score=0.0, passed=False` with
`error=None`. Indistinguishable from a real measurement of a terrible response.

The harm is not the row. It is `drift_detector._analyze_single`, which averages
`[r.score for r in history]` and reports `declined`. During a proxy outage the
window fills with zeros and the ship reports that its crew is deteriorating --
at exactly the moment the Captain is least able to check, and most likely to
believe it.

So the fix has two halves and neither is sufficient alone: a marker that says
*this measured nothing*, and a consumer that excludes it.

**Timeouts are deliberately NOT inconclusive.** A test that times out may be a
hung agent, and calling that "unmeasured" would hide a real fault. The boundary
is whether the failure is known to be non-agent.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from probos.cognitive.communication_benchmarks import (
    CommunicationScore,
    _score_response,
)
from probos.cognitive.qualification import (
    TestResult as QualTestResult,  # aliased: pytest tries to collect Test* classes
    _result_to_row,
    _row_to_result,
)


def _result(**kw: Any) -> QualTestResult:
    base = dict(
        agent_id="a", test_name="t", tier=1, score=0.0, passed=False,
        timestamp=time.time(), duration_ms=1.0,
    )
    base.update(kw)
    return QualTestResult(**base)  # type: ignore[arg-type]


# ── the judge's failures are the judge's, not the agent's ─────────


def test_no_judge_configured_is_inconclusive() -> None:
    score = asyncio.run(_score_response(None, "s", "r", "rub"))
    assert score.inconclusive == "no judge configured"


def test_a_judge_whose_transport_fails_is_inconclusive() -> None:
    class _Boom:
        async def complete(self, req: Any) -> Any:
            raise ConnectionError("proxy down")

    score = asyncio.run(_score_response(_Boom(), "s", "r", "rub"))
    assert score.inconclusive
    assert "ConnectionError" in score.inconclusive


def test_a_judge_returning_garbage_is_inconclusive() -> None:
    class _Garbage:
        async def complete(self, req: Any) -> Any:
            return type("R", (), {"content": "I'm sorry, I can't do that."})()

    score = asyncio.run(_score_response(_Garbage(), "s", "r", "rub"))
    assert score.inconclusive == "judge returned unparseable output"


def test_a_real_verdict_is_not_inconclusive_even_when_it_is_zero() -> None:
    """The distinction that matters. A judge that looked at the response and
    scored it zero is a MEASUREMENT, and must keep counting.
    """
    class _Judge:
        async def complete(self, req: Any) -> Any:
            return type("R", (), {"content": (
                '{"relevance": 0.0, "memory_grounding": 0.0, '
                '"expertise_coloring": 0.0, "action_appropriateness": 0.0, '
                '"voice_consistency": 0.0}'
            )})()

    score = asyncio.run(_score_response(_Judge(), "s", "r", "rub"))
    assert score.inconclusive == ""
    assert score.composite == 0.0


def test_the_flag_travels_in_the_dict_form() -> None:
    assert CommunicationScore(inconclusive="x").to_dict()["inconclusive"] == "x"
    assert CommunicationScore().to_dict()["inconclusive"] == ""


# ── an unmeasured run never reads as a pass ───────────────────────


def test_inconclusive_defaults_off_so_existing_results_are_unchanged() -> None:
    assert _result().inconclusive is False


# ── drift statistics exclude what was never measured ──────────────


class _Store:
    def __init__(self, history: list[QualTestResult]) -> None:
        self._history = history

    async def get_history(self, agent_id: str, test_name: str, limit: int = 0):
        return self._history

    async def get_baseline(self, agent_id: str, test_name: str):
        return _result(score=0.9, passed=True, is_baseline=True)


def _detector(history: list[QualTestResult]) -> Any:
    """Real config, not a stub -- a hand-rolled config double omits whatever
    field the code reads next, which is how this test first failed.
    """
    from probos.cognitive.drift_detector import DriftDetector
    from probos.config import QualificationConfig

    return DriftDetector(store=_Store(history), config=QualificationConfig())


def test_an_outage_does_not_read_as_a_decline() -> None:
    """The headline. A healthy agent at 0.9, then a proxy outage producing four
    unmeasured runs. Before BF-711 the mean collapsed and drift said "declined".
    """
    history = [_result(score=0.0, inconclusive=True, error="judge call failed")
               for _ in range(4)]
    history.append(_result(score=0.9, passed=True))

    signal = asyncio.run(_detector(history)._analyze_single("a", "t"))

    assert signal.direction != "declined"
    assert signal.sample_count == 1  # only the real measurement counted


def test_a_genuine_decline_is_still_reported() -> None:
    """The negative guard. Filtering must not make drift blind -- real zero
    scores from a working judge still count.
    """
    history = [_result(score=0.1, passed=False) for _ in range(4)]

    signal = asyncio.run(_detector(history)._analyze_single("a", "t"))

    assert signal.direction == "declined"
    assert signal.sample_count == 4


def test_a_window_of_nothing_but_outage_reports_no_samples() -> None:
    """Not "declined to zero" -- no data. The honest answer during a total
    outage is that the ship does not know.
    """
    history = [_result(score=0.0, inconclusive=True) for _ in range(5)]

    signal = asyncio.run(_detector(history)._analyze_single("a", "t"))

    assert signal.sample_count == 0
    assert signal.direction == "stable"


# ── the flag survives the store, which is where BF-742 went wrong ──


def test_the_flag_crosses_the_sqlite_boundary() -> None:
    """BF-742's lesson applied before shipping rather than after: a field the
    writer omits is not defaulted visibly, it is simply gone. The INSERT lists
    its columns explicitly, so adding a dataclass field is not enough.
    """
    row = _result_to_row(_result(inconclusive=True, error="judge call failed"))
    assert row[11] == 1

    back = _row_to_result(("id", *row[1:]))
    assert back.inconclusive is True


def test_a_measured_result_round_trips_as_measured() -> None:
    row = _result_to_row(_result(score=0.42, passed=True))
    assert row[11] == 0
    assert _row_to_result(("id", *row[1:])).inconclusive is False


def test_a_row_written_before_the_column_existed_still_loads() -> None:
    """The live vessel's qualification_results.db is 5.7 MB of pre-BF-711 rows.
    A short row means "written before we could record this", not a crash.
    """
    row = _result_to_row(_result(score=0.5))
    legacy = ("id", *row[1:11])  # 11 columns, no inconclusive
    assert _row_to_result(legacy).inconclusive is False


def test_the_insert_names_every_persisted_field() -> None:
    """Drift guard, same shape as BF-742's. A new TestResult field that the
    INSERT does not name is silently dropped on write.
    """
    import dataclasses
    import inspect

    from probos.cognitive import qualification

    src = inspect.getsource(qualification.QualificationStore.save_result)
    declared = {f.name for f in dataclasses.fields(QualTestResult)}
    missing = [
        name for name in declared
        if name not in src and name not in ("details",)  # stored as details_json
    ]
    assert missing == [], (
        f"TestResult fields not named in the INSERT: {missing}. "
        f"A column the writer omits is not defaulted -- it is gone."
    )
