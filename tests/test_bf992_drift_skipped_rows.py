"""BF-992 amendment A1 (#1324, register row 992-R1): the drift window leaves out results a probe skipped.

The skip helpers return a passing result at a fixed score with no error and, apart from
``behavioral_probes``, without BF-711's ``inconclusive`` flag. Once BF-992 counted crew episodes, a crew
agent's window held only skipped 1.0 rows, and for one measured score among k equal rows |z| = sqrt(k)
whatever its size: a warning at k 8, critical at a full window. A skip measured nothing, so
``DriftDetector._analyze_single`` drops it beside the ``inconclusive`` filter, reading ``details["skipped"]``
from the row so rows already stored are covered without a migration.

Real ``QualificationConfig`` and ``DriftDetector`` throughout; the last case uses a real
``QualificationStore`` and the real recall probe. Nothing stands in for the detector.
"""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from probos.cognitive import behavioral_probes, collective_tests, domain_tests, memory_probes
from probos.cognitive.drift_detector import DriftDetector
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.qualification import QualificationStore
from probos.cognitive.qualification import TestResult as QualTestResult  # aliased: pytest collects Test* names
from probos.cognitive.qualification_tests import EpisodicRecallProbe
from probos.config import QualificationConfig
from probos.types import Episode, LLMResponse
from tests.test_ad566b_baseline_tests import MockAgent, MockRegistry

_SLOT = "security_officer-0"
_SOVEREIGN = "3f9c2a1e-sovereign"
_SKIPPED = {"skipped": True, "reason": "insufficient_episodes", "episode_count": 0}


def _result(score: float, details: dict[str, Any] | None = None) -> QualTestResult:
    return QualTestResult(
        agent_id="a", test_name="t", tier=1, score=score, passed=True,
        timestamp=time.time(), duration_ms=1.0, details=dict(details or {}),
    )


def _skipped() -> QualTestResult:
    """What the recall probe stored for every crew agent before BF-992: a pass at 1.0, no error."""
    return _result(1.0, _SKIPPED)


def _unmarked(rows: list[QualTestResult]) -> list[QualTestResult]:
    """The same rows without the skip flag: the window as the detector read it before A1."""
    return [dataclasses.replace(r, details={}) for r in rows]


class _Store:
    def __init__(self, history: list[QualTestResult]) -> None:
        self._history = history

    async def get_history(self, agent_id: str, test_name: str, limit: int = 0):
        return self._history

    async def get_baseline(self, agent_id: str, test_name: str):
        # The harness auto-baselines the first result with no error, which was a skip (qualification.py:444).
        return dataclasses.replace(_skipped(), is_baseline=True)


async def _signal(history: list[QualTestResult]) -> Any:
    return await DriftDetector(store=_Store(history), config=QualificationConfig())._analyze_single("a", "t")


async def test_a_full_window_of_skips_does_not_make_the_first_score_critical() -> None:
    history = [_result(0.9)] + [_skipped() for _ in range(19)]  # newest first

    assert (await _signal(_unmarked(history))).severity == "critical"  # the premise: z = -4.36
    signal = await _signal(history)

    assert signal.sample_count == 1
    assert signal.severity == "normal"


async def test_eight_skips_do_not_make_the_first_score_a_warning() -> None:
    history = [_result(0.9)] + [_skipped() for _ in range(8)]

    assert (await _signal(_unmarked(history))).severity == "warning"  # the premise: z = -sqrt(8)
    signal = await _signal(history)

    assert signal.sample_count == 1
    assert signal.severity == "normal"


async def test_a_genuine_decline_among_skips_is_still_reported() -> None:
    history = [_result(0.1)]
    for _ in range(9):
        history += [_skipped(), _result(0.9)]
    history.append(_skipped())

    signal = await _signal(history)

    assert signal.sample_count == 10
    assert signal.current_score == pytest.approx(0.1)
    assert signal.direction == "declined"
    assert signal.severity in ("warning", "critical")  # z = -3.0 over the ten measured scores


async def test_rows_marked_not_skipped_still_count() -> None:
    signal = await _signal([_result(0.1, {"skipped": False}) for _ in range(4)])

    assert signal.sample_count == 4
    assert signal.direction == "declined"


async def test_a_window_of_only_skips_reports_no_samples() -> None:
    signal = await _signal([_skipped() for _ in range(5)])

    assert signal.sample_count == 0
    assert signal.direction == "stable"
    assert signal.severity == "normal"


_SKIP_HELPERS: dict[str, Callable[[], QualTestResult]] = {
    "memory_probes": lambda: memory_probes._make_skip_result("a", "t", 1, time.time(), "no_episodic_memory"),
    "domain_tests": lambda: domain_tests._skip_result("a", "t", 2, "not_in_department"),
    "collective_tests": lambda: collective_tests._skip_result("t", "no_engine"),
    "behavioral_probes": lambda: behavioral_probes._skip_result("t", "no_engine"),
}


@pytest.mark.parametrize("producer", sorted(_SKIP_HELPERS))
async def test_each_skip_helper_is_left_out(producer: str) -> None:
    skip = _SKIP_HELPERS[producer]()
    assert skip.details["skipped"] is True and skip.error is None  # a pass that measured nothing

    signal = await _signal([_result(0.9)] + [dataclasses.replace(skip) for _ in range(8)])

    assert signal.sample_count == 1
    assert signal.severity == "normal"


class _Judge:
    """Answers every judge prompt with a score, as ``BaseLLMClient.complete`` does."""

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        return LLMResponse(content="0.9")


async def _recall_runtime(episodes: int) -> SimpleNamespace:
    agent = MockAgent(agent_id=_SLOT, response="I filed the watch report.")
    agent.sovereign_id = _SOVEREIGN
    memory = MockEpisodicMemory()
    await memory.seed([
        Episode(user_input=f"watch report {i}", timestamp=float(i + 1), agent_ids=[_SOVEREIGN])
        for i in range(episodes)
    ])
    return SimpleNamespace(registry=MockRegistry(agent), episodic_memory=memory, llm_client=_Judge())


async def test_a_recall_probe_skip_keeps_its_flag_through_the_store_and_stays_out(tmp_path: Path) -> None:
    probe = EpisodicRecallProbe()
    skipped = await probe.run(_SLOT, await _recall_runtime(2))
    measured = await probe.run(_SLOT, await _recall_runtime(3))
    assert skipped.details["skipped"] is True and skipped.error is None and skipped.score == 1.0
    assert measured.details["skipped"] is False

    store = QualificationStore(data_dir=tmp_path)
    await store.start()
    try:
        now = time.time()
        for i in range(19):
            await store.save_result(dataclasses.replace(skipped, timestamp=now - 3600.0 * (i + 3)))
        for i in range(2):
            await store.save_result(dataclasses.replace(measured, timestamp=now - 3600.0 * (i + 1)))
        history = await store.get_history(_SLOT, probe.name)
        signal = await DriftDetector(store, QualificationConfig())._analyze_single(_SLOT, probe.name)
    finally:
        await store.stop()

    assert len(history) == 20
    assert sum(1 for r in history if r.details.get("skipped") is True) == 18  # the flag survives SQLite
    assert signal.sample_count == 2
    assert signal.severity == "normal"
