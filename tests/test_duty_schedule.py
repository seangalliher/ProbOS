"""Tests for Agent Duty Schedule (AD-419)."""

import time
from unittest.mock import MagicMock

import pytest

from probos.duty_schedule import DutyScheduleTracker, DutyStatus


def _make_duty(duty_id: str, interval: float = 3600, cron: str = "", priority: int = 2):
    """Create a mock DutyDefinition."""
    d = MagicMock()
    d.duty_id = duty_id
    d.description = f"Test duty: {duty_id}"
    d.cron = cron
    d.interval_seconds = interval
    d.priority = priority
    return d


class TestDutyScheduleTracker:

    def test_interval_duty_due_on_first_cycle(self):
        """Duties are always due on first cycle (last_executed=0)."""
        duty = _make_duty("test", interval=3600)
        tracker = DutyScheduleTracker({"scout": [duty]})
        due = tracker.get_due_duties("scout")
        assert len(due) == 1
        assert due[0].duty_id == "test"

    def test_interval_duty_not_due_after_execution(self):
        """Duty is not due if executed within interval."""
        duty = _make_duty("test", interval=3600)
        tracker = DutyScheduleTracker({"scout": [duty]})
        tracker.record_execution("scout", "test")
        due = tracker.get_due_duties("scout")
        assert len(due) == 0

    def test_interval_duty_due_after_interval(self):
        """Duty becomes due again after interval elapses."""
        duty = _make_duty("test", interval=1)  # 1 second interval
        tracker = DutyScheduleTracker({"scout": [duty]})
        tracker.record_execution("scout", "test")
        # Manually backdate last_executed
        key = tracker._status_key("scout", "test")
        tracker._status[key].last_executed = time.time() - 2
        due = tracker.get_due_duties("scout")
        assert len(due) == 1

    def test_cron_duty_due_on_first_cycle(self):
        """Cron duties are due on first cycle (never executed)."""
        duty = _make_duty("test", interval=0, cron="* * * * *")  # Every minute
        tracker = DutyScheduleTracker({"scout": [duty]})
        due = tracker.get_due_duties("scout")
        assert len(due) == 1

    def test_cron_duty_not_due_after_recent_execution(self):
        """Cron duty with hourly schedule not due just after execution."""
        duty = _make_duty("test", interval=0, cron="0 * * * *")  # Hourly
        tracker = DutyScheduleTracker({"scout": [duty]})
        tracker.record_execution("scout", "test")
        # Just executed — next hourly cron tick is in the future
        due = tracker.get_due_duties("scout")
        assert len(due) == 0

    def test_priority_sorting(self):
        """Duties returned in priority order (highest first)."""
        low = _make_duty("low", interval=0, cron="* * * * *", priority=1)
        high = _make_duty("high", interval=0, cron="* * * * *", priority=5)
        mid = _make_duty("mid", interval=0, cron="* * * * *", priority=3)
        tracker = DutyScheduleTracker({"scout": [low, high, mid]})
        due = tracker.get_due_duties("scout")
        assert [d.duty_id for d in due] == ["high", "mid", "low"]

    def test_no_duties_for_unknown_agent_type(self):
        """Unknown agent types return empty list."""
        tracker = DutyScheduleTracker({"scout": [_make_duty("test")]})
        due = tracker.get_due_duties("unknown_type")
        assert due == []

    def test_record_execution_increments_count(self):
        """Execution count tracks correctly."""
        duty = _make_duty("test", interval=3600)
        tracker = DutyScheduleTracker({"scout": [duty]})
        tracker.record_execution("scout", "test")
        tracker.record_execution("scout", "test")
        key = tracker._status_key("scout", "test")
        assert tracker._status[key].execution_count == 2

    def test_get_status_returns_all_duties(self):
        """get_status returns info for all configured duties."""
        d1 = _make_duty("report", interval=3600)
        d2 = _make_duty("scan", interval=7200)
        tracker = DutyScheduleTracker({"scout": [d1, d2]})
        tracker.record_execution("scout", "report")
        status = tracker.get_status("scout")
        assert len(status) == 2
        ids = {s["duty_id"] for s in status}
        assert ids == {"report", "scan"}
        report = next(s for s in status if s["duty_id"] == "report")
        assert report["execution_count"] == 1

    def test_mixed_cron_and_interval(self):
        """Can mix cron and interval-based duties for same agent type."""
        cron_duty = _make_duty("cron_task", interval=0, cron="* * * * *")
        interval_duty = _make_duty("interval_task", interval=1)
        tracker = DutyScheduleTracker({"scout": [cron_duty, interval_duty]})
        due = tracker.get_due_duties("scout")
        assert len(due) == 2


class TestProactiveLoopDutyIntegration:
    """Test that proactive loop correctly uses duty schedule."""

    @pytest.mark.asyncio
    async def test_duty_passed_to_intent(self):
        """When a duty is due, the intent includes duty info."""
        from unittest.mock import AsyncMock, patch

        from probos.proactive import ProactiveCognitiveLoop
        from probos.crew_profile import Rank

        loop = ProactiveCognitiveLoop(interval=120, cooldown=300)

        # Set up duty tracker
        duty = _make_duty("scout_report", interval=86400)
        from probos.duty_schedule import DutyScheduleTracker
        loop._duty_tracker = DutyScheduleTracker({"scout": [duty]})

        # Mock runtime
        rt = MagicMock()
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[])
        loop._runtime = rt

        # Mock agent
        agent = MagicMock()
        agent.id = "scout-1"
        agent.agent_type = "scout"
        agent.handle_intent = AsyncMock(return_value=MagicMock(
            success=True, result="[NO_RESPONSE]"
        ))

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        # Verify intent included duty info
        call_args = agent.handle_intent.call_args[0][0]
        assert call_args.params["duty"] is not None
        assert call_args.params["duty"]["duty_id"] == "scout_report"

    @pytest.mark.asyncio
    async def test_no_duty_passes_none(self):
        """When no duty is due, duty param is None."""
        from unittest.mock import AsyncMock, patch

        from probos.proactive import ProactiveCognitiveLoop
        from probos.crew_profile import Rank

        loop = ProactiveCognitiveLoop(interval=120, cooldown=300)

        # Empty duty schedule
        from probos.duty_schedule import DutyScheduleTracker
        loop._duty_tracker = DutyScheduleTracker({})

        rt = MagicMock()
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[])
        loop._runtime = rt

        agent = MagicMock()
        agent.id = "scout-1"
        agent.agent_type = "scout"
        agent.handle_intent = AsyncMock(return_value=MagicMock(
            success=True, result="[NO_RESPONSE]"
        ))

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        call_args = agent.handle_intent.call_args[0][0]
        assert call_args.params["duty"] is None

    @pytest.mark.asyncio
    async def test_duty_recorded_after_execution(self):
        """Duty execution is recorded even with NO_RESPONSE."""
        from unittest.mock import AsyncMock

        from probos.proactive import ProactiveCognitiveLoop
        from probos.crew_profile import Rank

        loop = ProactiveCognitiveLoop(interval=120, cooldown=300)

        duty = _make_duty("scout_report", interval=86400)
        from probos.duty_schedule import DutyScheduleTracker
        loop._duty_tracker = DutyScheduleTracker({"scout": [duty]})

        rt = MagicMock()
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[])
        loop._runtime = rt

        agent = MagicMock()
        agent.id = "scout-1"
        agent.agent_type = "scout"
        agent.handle_intent = AsyncMock(return_value=MagicMock(
            success=True, result="[NO_RESPONSE]"
        ))

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        # Duty should be recorded as executed
        status = loop._duty_tracker.get_status("scout")
        assert status[0]["execution_count"] == 1
