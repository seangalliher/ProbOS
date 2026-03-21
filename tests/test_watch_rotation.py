"""Tests for Watch Rotation + Duty Shifts (AD-377)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest


class TestWatchType:
    def test_alpha_value(self) -> None:
        from probos.watch_rotation import WatchType
        assert WatchType.ALPHA.value == "alpha"


class TestStandingTask:
    def test_is_due_initially(self) -> None:
        from probos.watch_rotation import StandingTask
        task = StandingTask(interval_seconds=60, last_executed=0.0)
        assert task.is_due()

    def test_not_due_if_recent(self) -> None:
        import time
        from probos.watch_rotation import StandingTask
        task = StandingTask(interval_seconds=3600, last_executed=time.time())
        assert not task.is_due()


class TestWatchManager:
    def test_default_watch_is_alpha(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType
        mgr = WatchManager()
        assert mgr.current_watch == WatchType.ALPHA

    def test_set_current_watch(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType
        mgr = WatchManager()
        mgr.set_current_watch(WatchType.BETA)
        assert mgr.current_watch == WatchType.BETA

    def test_assign_and_get_on_duty(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType
        mgr = WatchManager()
        mgr.assign_to_watch("agent-1", WatchType.ALPHA)
        mgr.assign_to_watch("agent-2", WatchType.ALPHA)
        assert len(mgr.get_on_duty()) == 2

    def test_on_duty_changes_with_watch(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType
        mgr = WatchManager()
        mgr.assign_to_watch("agent-1", WatchType.ALPHA)
        mgr.assign_to_watch("agent-2", WatchType.BETA)
        assert "agent-1" in mgr.get_on_duty()
        assert "agent-2" not in mgr.get_on_duty()
        mgr.set_current_watch(WatchType.BETA)
        assert "agent-2" in mgr.get_on_duty()
        assert "agent-1" not in mgr.get_on_duty()

    def test_remove_from_watch(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType
        mgr = WatchManager()
        mgr.assign_to_watch("agent-1", WatchType.ALPHA)
        mgr.remove_from_watch("agent-1", WatchType.ALPHA)
        assert mgr.get_on_duty() == []

    def test_get_roster(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType
        mgr = WatchManager()
        mgr.assign_to_watch("a1", WatchType.ALPHA)
        mgr.assign_to_watch("a2", WatchType.GAMMA)
        roster = mgr.get_roster()
        assert "a1" in roster["alpha"]
        assert "a2" in roster["gamma"]

    def test_add_standing_task(self) -> None:
        from probos.watch_rotation import WatchManager, StandingTask
        mgr = WatchManager()
        mgr.add_standing_task(StandingTask(id="t1", department="medical"))
        assert len(mgr.get_standing_tasks()) == 1

    def test_remove_standing_task(self) -> None:
        from probos.watch_rotation import WatchManager, StandingTask
        mgr = WatchManager()
        mgr.add_standing_task(StandingTask(id="t1"))
        assert mgr.remove_standing_task("t1")
        assert len(mgr.get_standing_tasks()) == 0

    def test_filter_tasks_by_department(self) -> None:
        from probos.watch_rotation import WatchManager, StandingTask
        mgr = WatchManager()
        mgr.add_standing_task(StandingTask(id="t1", department="medical"))
        mgr.add_standing_task(StandingTask(id="t2", department="engineering"))
        assert len(mgr.get_standing_tasks("medical")) == 1

    def test_issue_captain_order(self) -> None:
        from probos.watch_rotation import WatchManager, CaptainOrder
        mgr = WatchManager()
        mgr.issue_order(CaptainOrder(id="o1", target="builder", description="Build module"))
        assert len(mgr.get_active_orders()) == 1

    def test_rescind_captain_order(self) -> None:
        from probos.watch_rotation import WatchManager, CaptainOrder
        mgr = WatchManager()
        mgr.issue_order(CaptainOrder(id="o1", target="builder", description="Build"))
        assert mgr.rescind_order("o1")
        assert len(mgr.get_active_orders()) == 0

    def test_filter_orders_by_target(self) -> None:
        from probos.watch_rotation import WatchManager, CaptainOrder
        mgr = WatchManager()
        mgr.issue_order(CaptainOrder(id="o1", target="builder"))
        mgr.issue_order(CaptainOrder(id="o2", target="architect"))
        assert len(mgr.get_active_orders("builder")) == 1

    @pytest.mark.asyncio
    async def test_dispatch_standing_task(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType, StandingTask
        mock_dispatch = AsyncMock()
        mgr = WatchManager(dispatch_fn=mock_dispatch)
        mgr.assign_to_watch("agent-1", WatchType.ALPHA)
        mgr.add_standing_task(StandingTask(
            id="t1", intent_type="run_diagnostics",
            interval_seconds=0,  # always due
        ))
        await mgr._dispatch_due_tasks()
        mock_dispatch.assert_awaited_once_with("run_diagnostics", {})

    @pytest.mark.asyncio
    async def test_one_shot_order_deactivates(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType, CaptainOrder
        mock_dispatch = AsyncMock()
        mgr = WatchManager(dispatch_fn=mock_dispatch)
        mgr.assign_to_watch("agent-1", WatchType.ALPHA)
        mgr.issue_order(CaptainOrder(
            id="o1", target="agent-1", target_type="agent",
            intent_type="special_task", one_shot=True,
        ))
        await mgr._dispatch_due_orders()
        mock_dispatch.assert_awaited_once()
        # one_shot order should now be inactive
        assert len(mgr.get_active_orders()) == 0
        assert mgr._captain_orders[0].executed_count == 1

    @pytest.mark.asyncio
    async def test_dispatch_skips_off_duty(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType, CaptainOrder
        mock_dispatch = AsyncMock()
        mgr = WatchManager(dispatch_fn=mock_dispatch)
        # agent-1 on Beta, but we're on Alpha
        mgr.assign_to_watch("agent-1", WatchType.BETA)
        mgr.issue_order(CaptainOrder(
            id="o1", target="agent-1", target_type="agent",
            intent_type="task",
        ))
        await mgr._dispatch_due_orders()
        mock_dispatch.assert_not_awaited()
