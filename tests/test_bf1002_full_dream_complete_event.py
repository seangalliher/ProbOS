"""BF-1002 (#1820 bf-989 R6, part a): a full dream's dream_complete event reaches its listeners.

DreamReport.episodes_replayed is an int (types.py). Both full-dream emit sites of DreamScheduler
called len() on it while building the payload inside the emit's try, so at the base no full-dream
completion reached runtime._emit_event; the TypeError was logged at DEBUG. One module helper,
_full_dream_complete_payload, now builds the payload for both sites, and a payload failure logs at
WARNING. The last test crosses the seam: the Counselor's AD-505 forced dream, the scheduler that
startup wired, runtime._emit_event and the Counselor's own subscription (AD-506a).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.counselor import CounselorAssessment
from probos.cognitive.dreaming import DreamScheduler
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime
from probos.types import DreamReport

_DREAMING_LOGGER = "probos.cognitive.dreaming"
_FULL_KEYS = frozenset({
    "dream_type",
    "duration_ms",
    "episodes_replayed",
    "clusters_found",
    "notebook_consolidations",
    "convergence_reports_generated",
})
_EXPECTED = {
    "dream_type": "full",
    "duration_ms": 12.5,
    "episodes_replayed": 7,
    "clusters_found": 2,
    "notebook_consolidations": 3,
    "convergence_reports_generated": 1,
}


def _report() -> DreamReport:
    """A real report; each count differs, so a swapped or dropped field changes the payload."""
    return DreamReport(
        duration_ms=12.5,
        episodes_replayed=7,
        clusters_found=2,
        notebook_consolidations=3,
        convergence_reports_generated=1,
        reflections_created=4,
    )


async def _settle(predicate: Any, *, timeout: float = 5.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return bool(predicate())


class _Engine:
    """Stands in for DreamingEngine: the three methods the scheduler calls."""

    def __init__(self, report: Any) -> None:
        self.report = report
        self.cycles = 0

    async def micro_dream(self) -> dict[str, int]:
        return {"episodes_replayed": 0}  # replays nothing, so the loop emits no micro completion

    async def proactive_procedure_scan(self) -> dict[str, int]:
        return {"evolved": 0}

    async def dream_cycle(self) -> Any:
        self.cycles += 1
        return self.report


def _scheduler(engine: _Engine, events: list[tuple[str, dict[str, Any]]]) -> DreamScheduler:
    scheduler = DreamScheduler(engine, idle_threshold_seconds=0.0, dream_interval_seconds=3600.0)
    scheduler._emit_event_fn = lambda event_type, data: events.append((event_type, data))
    return scheduler


async def _one_monitor_dream(scheduler: DreamScheduler, engine: _Engine) -> None:
    """Run the monitor loop until it has run one full dream (its first tick sleeps 1 s)."""
    scheduler._last_dream_time = time.monotonic() - 7200.0  # the 3600 s interval has passed
    scheduler.start()
    try:
        assert await _settle(lambda: engine.cycles >= 1)
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_force_dream_emits_the_full_payload_of_a_real_report() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    report = _report()
    scheduler = _scheduler(_Engine(report), events)

    assert await scheduler.force_dream() is report

    assert events == [("dream_complete", _EXPECTED)]
    assert type(events[0][1]["episodes_replayed"]) is int  # 7.0 == 7, so the equality alone admits a float


@pytest.mark.asyncio
async def test_the_monitor_loop_emits_the_full_payload_of_a_real_report() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    engine = _Engine(_report())
    scheduler = _scheduler(engine, events)

    await _one_monitor_dream(scheduler, engine)

    assert engine.cycles == 1
    assert events == [("dream_complete", _EXPECTED)]
    assert type(events[0][1]["episodes_replayed"]) is int


@pytest.mark.asyncio
async def test_a_payload_failure_in_force_dream_logs_a_warning_and_returns_the_report(caplog) -> None:
    unreadable = object()  # carries no DreamReport field, so building the payload raises
    events: list[tuple[str, dict[str, Any]]] = []
    scheduler = _scheduler(_Engine(unreadable), events)

    with caplog.at_level(logging.WARNING, logger=_DREAMING_LOGGER):
        assert await scheduler.force_dream() is unreadable

    assert events == []
    assert "BF-1002: full dream_complete emission failed (force_dream)" in caplog.text


@pytest.mark.asyncio
async def test_a_payload_failure_in_the_monitor_loop_logs_a_warning(caplog) -> None:
    unreadable = object()
    events: list[tuple[str, dict[str, Any]]] = []
    engine = _Engine(unreadable)
    scheduler = _scheduler(engine, events)

    with caplog.at_level(logging.WARNING, logger=_DREAMING_LOGGER):
        await _one_monitor_dream(scheduler, engine)

    assert scheduler.last_dream_report is unreadable
    assert events == []
    assert "BF-1002: full dream_complete emission failed (monitor loop)" in caplog.text


@pytest.mark.asyncio
async def test_a_forced_dream_reaches_the_booted_counselor_as_a_full_completion(tmp_path, monkeypatch, caplog) -> None:
    """AD-505 forces the dream and records the agent; AD-506a re-assesses it on the completion."""
    rt = ProbOSRuntime(
        config=SystemConfig(),
        data_dir=tmp_path,
        episodic_memory=MockEpisodicMemory(relevance_threshold=0.3),
    )
    await rt.start()
    try:
        scheduler = rt.dream_scheduler
        assert scheduler is not None
        await scheduler.stop()  # quiesce the monitor so only the forced dream completes
        counselor = rt.registry.get_by_pool("counselor")[0]
        assert counselor._dream_scheduler is scheduler  # wired by finalize, not by this test

        seen: list[dict[str, Any]] = []
        handler = counselor._on_dream_complete

        async def spy(data: dict[str, Any]) -> None:
            seen.append(data)
            await handler(data)

        monkeypatch.setattr(counselor, "_on_dream_complete", spy)
        monkeypatch.setattr(counselor, "_gather_agent_metrics", MagicMock(return_value={
            "trust_score": 0.8, "confidence": 0.7, "hebbian_avg": 0.6,
            "success_rate": 0.9, "personality_drift": 0.05,
        }))
        assess = MagicMock(return_value=MagicMock(wellness_score=0.8))
        monkeypatch.setattr(counselor, "assess_agent", assess)
        monkeypatch.setattr(counselor, "_save_profile_and_assessment", AsyncMock())
        monkeypatch.setattr(counselor, "_post_recommendation_to_ward_room", AsyncMock())
        agent_id = "agent-bf1002"

        def _reassessed() -> bool:
            return any(
                call.kwargs.get("agent_id") == agent_id and call.kwargs.get("trigger") == "post_dream"
                for call in assess.call_args_list
            )

        with caplog.at_level(logging.INFO):
            await counselor._apply_intervention(
                agent_id, "BF1002", CounselorAssessment(agent_id=agent_id, wellness_score=0.2), "intervention",
            )
            assert await _settle(lambda: _reassessed() and agent_id not in counselor._intervention_targets)

        full = [data for data in seen if data.get("dream_type") == "full"]
        assert len(full) == 1
        assert set(full[0]) == _FULL_KEYS
        report = scheduler.last_dream_report
        assert report is not None
        assert type(full[0]["episodes_replayed"]) is int
        assert full[0]["episodes_replayed"] == report.episodes_replayed
        assert "AD-505: Failed to trigger dream cycle" not in caplog.text
        assert "Counselor event handler failed" not in caplog.text
        assert "BF-1002: full dream_complete emission failed" not in caplog.text
    finally:
        await rt.stop()
