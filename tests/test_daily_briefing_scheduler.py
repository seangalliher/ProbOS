"""AD-752 daily briefing trigger tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from probos.config import DutyPolicyConfig
from probos.duty_schedule import DutySchedule
from probos.proactive import DailyBriefingScheduler


@pytest.mark.asyncio
async def test_trigger_briefing_if_time_runs_once_per_day(tmp_path) -> None:
    now = datetime(2026, 5, 20, 8, 30)
    cfg = DutyPolicyConfig(
        work_hours={"start_time": "08:00", "end_time": "18:00", "days": [0, 1, 2, 3, 4]},
        quiet_hours={"start_time": "19:00", "end_time": "08:00", "days": []},
        daily_briefing_time="08:00",
        briefing_reminder_throttle_sec=0,
    )
    schedule = DutySchedule(cfg, now_fn=lambda: now)
    scheduler = DailyBriefingScheduler(
        duty_schedule=schedule,
        state_path=tmp_path / "briefing_state.json",
        now_fn=lambda: now,
    )

    first = await scheduler.trigger_briefing_if_time()
    second = await scheduler.trigger_briefing_if_time()

    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_trigger_briefing_if_time_suppressed_when_dismissed(tmp_path) -> None:
    now = datetime(2026, 5, 21, 9, 0)
    cfg = DutyPolicyConfig(
        work_hours={"start_time": "08:00", "end_time": "18:00", "days": [0, 1, 2, 3, 4]},
        quiet_hours={"start_time": "19:00", "end_time": "08:00", "days": []},
        daily_briefing_time="08:00",
        briefing_reminder_throttle_sec=0,
    )
    schedule = DutySchedule(cfg, now_fn=lambda: now)
    scheduler = DailyBriefingScheduler(
        duty_schedule=schedule,
        state_path=tmp_path / "briefing_state.json",
        now_fn=lambda: now,
    )

    scheduler.dismiss_for_today()
    triggered = await scheduler.trigger_briefing_if_time()

    assert triggered is False
