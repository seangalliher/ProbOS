"""Tests for Watch Rotation + Duty Shifts (AD-377)."""

from __future__ import annotations


class TestWatchType:
    def test_alpha_value(self) -> None:
        from probos.watch_rotation import WatchType
        assert WatchType.ALPHA.value == "alpha"


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
