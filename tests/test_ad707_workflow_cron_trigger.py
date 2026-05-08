"""Tests for AD-707 — Workflow Cron Trigger scheduler.

Wave 130. Closes #483 (cron-only; webhook + workflow API deferred to AD-707b/c).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.workflow_cron import (
    WorkflowCronScheduler,
    WorkflowCronTrigger,
    _is_due,
    _validate_cron,
)


class _Clock:
    def __init__(self, t: float = 1_700_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class _ProcessNLRecorder:
    def __init__(self, raises: bool = False) -> None:
        self.calls: list[str] = []
        self.raises = raises

    async def __call__(self, user_input: str) -> dict[str, Any]:
        self.calls.append(user_input)
        if self.raises:
            raise RuntimeError("simulated nl-processing failure")
        return {"replayed": user_input}


@pytest.mark.asyncio
async def test_register_validates_cron_expression(tmp_path: Path) -> None:
    rec = _ProcessNLRecorder()
    sched = WorkflowCronScheduler(rec, db_path=str(tmp_path / "wfc.db"))
    await sched.start()
    try:
        with pytest.raises(ValueError):
            await sched.register("hello", "not-a-cron")
        with pytest.raises(ValueError):
            await sched.register("", "* * * * *")
        trig = await sched.register("daily standup", "0 9 * * *")
        assert trig.cron_expr == "0 9 * * *"
        assert trig.user_input == "daily standup"
        assert trig.enabled is True
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_register_persists_to_sqlite(tmp_path: Path) -> None:
    db_path = str(tmp_path / "wfc.db")
    rec1 = _ProcessNLRecorder()
    sched1 = WorkflowCronScheduler(rec1, db_path=db_path)
    await sched1.start()
    trig = await sched1.register("morning report", "0 8 * * *")
    await sched1.stop()

    # Restart with the same DB — trigger should reload.
    rec2 = _ProcessNLRecorder()
    sched2 = WorkflowCronScheduler(rec2, db_path=db_path)
    await sched2.start()
    try:
        triggers = sched2.list_triggers()
        ids = {t.id for t in triggers}
        assert trig.id in ids
        reloaded = next(t for t in triggers if t.id == trig.id)
        assert reloaded.user_input == "morning report"
        assert reloaded.cron_expr == "0 8 * * *"
        assert reloaded.enabled is True
    finally:
        await sched2.stop()


@pytest.mark.asyncio
async def test_cancel_marks_disabled_in_db_and_removes_from_memory(
    tmp_path: Path,
) -> None:
    db_path = str(tmp_path / "wfc.db")
    rec = _ProcessNLRecorder()
    sched = WorkflowCronScheduler(rec, db_path=db_path)
    await sched.start()
    trig = await sched.register("x", "* * * * *")

    assert await sched.cancel(trig.id) is True
    assert trig.id not in {t.id for t in sched.list_triggers()}
    # Second cancel returns False
    assert await sched.cancel(trig.id) is False
    await sched.stop()

    # Reloaded scheduler should not see the cancelled trigger (enabled=0 filter).
    sched2 = WorkflowCronScheduler(_ProcessNLRecorder(), db_path=db_path)
    await sched2.start()
    try:
        ids = {t.id for t in sched2.list_triggers()}
        assert trig.id not in ids
    finally:
        await sched2.stop()


@pytest.mark.asyncio
async def test_tick_fires_due_trigger_via_process_nl_fn(tmp_path: Path) -> None:
    clock = _Clock(t=1_700_000_000.0)
    rec = _ProcessNLRecorder()
    sched = WorkflowCronScheduler(
        rec, db_path=str(tmp_path / "wfc.db"), clock=clock
    )
    await sched.start()
    try:
        trig = await sched.register("nightly cleanup", "*/1 * * * *")
        # Advance clock past next minute boundary so cron is due.
        clock.t += 120.0
        await sched._tick_once()
        assert "nightly cleanup" in rec.calls
        # Reload trigger state from in-memory dict
        updated = next(t for t in sched.list_triggers() if t.id == trig.id)
        assert updated.fire_count == 1
        assert updated.last_fired_at == clock.t
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_tick_does_not_fire_undue_trigger(tmp_path: Path) -> None:
    clock = _Clock()
    rec = _ProcessNLRecorder()
    sched = WorkflowCronScheduler(rec, db_path=str(tmp_path / "wfc.db"), clock=clock)
    await sched.start()
    try:
        # Daily at 09:00; clock is at the registration moment — not due.
        await sched.register("daily report", "0 9 * * *")
        await sched._tick_once()
        assert rec.calls == []
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_failed_replay_logs_and_continues(tmp_path: Path) -> None:
    clock = _Clock()
    rec = _ProcessNLRecorder(raises=True)
    sched = WorkflowCronScheduler(rec, db_path=str(tmp_path / "wfc.db"), clock=clock)
    await sched.start()
    try:
        trig = await sched.register("flaky", "*/1 * * * *")
        clock.t += 120.0
        await sched._tick_once()
        # Call attempted but fire_count NOT incremented on failure.
        assert rec.calls == ["flaky"]
        updated = next(t for t in sched.list_triggers() if t.id == trig.id)
        assert updated.fire_count == 0
        assert updated.last_fired_at == 0.0
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_cancelled_trigger_does_not_fire(tmp_path: Path) -> None:
    clock = _Clock()
    rec = _ProcessNLRecorder()
    sched = WorkflowCronScheduler(rec, db_path=str(tmp_path / "wfc.db"), clock=clock)
    await sched.start()
    try:
        trig = await sched.register("x", "*/1 * * * *")
        await sched.cancel(trig.id)
        clock.t += 120.0
        await sched._tick_once()
        assert rec.calls == []
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_start_stop_idempotent(tmp_path: Path) -> None:
    rec = _ProcessNLRecorder()
    sched = WorkflowCronScheduler(rec, db_path=str(tmp_path / "wfc.db"))
    await sched.start()
    await sched.start()  # idempotent
    await asyncio.sleep(0.01)
    await sched.stop()
    await sched.stop()  # idempotent


@pytest.mark.asyncio
async def test_in_memory_mode_does_not_persist() -> None:
    rec = _ProcessNLRecorder()
    sched = WorkflowCronScheduler(rec, db_path=None)  # in-memory only
    await sched.start()
    try:
        trig = await sched.register("x", "* * * * *")
        assert trig.id in {t.id for t in sched.list_triggers()}
    finally:
        await sched.stop()


def test_validate_cron_helper() -> None:
    assert _validate_cron("* * * * *") is True
    assert _validate_cron("0 9 * * *") is True
    assert _validate_cron("garbage") is False
    assert _validate_cron("") is False


def test_is_due_uses_created_at_for_first_eval() -> None:
    """Per hard-constraint: a freshly-registered trigger does not fire instantly."""
    trig = WorkflowCronTrigger(
        id="t",
        user_input="x",
        cron_expr="*/5 * * * *",
        created_at=1_700_000_000.0,
        last_fired_at=0.0,
    )
    # 'now' equal to created_at → not yet at next 5-min boundary.
    assert _is_due(trig, 1_700_000_000.0) is False
    # 'now' 6 minutes later → due.
    assert _is_due(trig, 1_700_000_000.0 + 360.0) is True
