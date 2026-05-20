"""AD-752 proactive heartbeat scheduler integration tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from probos.agents.operations.scheduler import ProactiveHeartbeatScheduler
from probos.config import DutyPolicyConfig
from probos.duty_schedule import DutySchedule
from probos.persistent_tasks import PersistentTaskStore


@pytest.mark.asyncio
async def test_ensure_jobs_registered_persists_across_restarts(tmp_path) -> None:
    db_path = tmp_path / 'scheduled_tasks.db'
    cfg = DutyPolicyConfig(
        work_hours={"start_time": "08:00", "end_time": "18:00", "days": [0, 1, 2, 3, 4]},
        quiet_hours={"start_time": "19:00", "end_time": "08:00", "days": []},
    )
    duty = DutySchedule(cfg)

    store_one = PersistentTaskStore(db_path=str(db_path), tick_interval=9999.0)
    await store_one.start()
    try:
        scheduler = ProactiveHeartbeatScheduler(store_one, duty)
        created = await scheduler.ensure_jobs_registered()
        assert len(created) == 3
    finally:
        await store_one.stop()

    store_two = PersistentTaskStore(db_path=str(db_path), tick_interval=9999.0)
    await store_two.start()
    try:
        tasks = await store_two.list_tasks(limit=50)
        hooks = {task.webhook_name for task in tasks}
        assert {'proactive_scan_inbox', 'proactive_scan_calendar', 'proactive_scan_teams'} <= hooks
    finally:
        await store_two.stop()


@pytest.mark.asyncio
async def test_should_dispatch_scan_blocks_outside_work_hours_with_reason() -> None:
    cfg = DutyPolicyConfig(
        work_hours={"start_time": "08:00", "end_time": "18:00", "days": [0, 1, 2, 3, 4]},
        quiet_hours={"start_time": "19:00", "end_time": "08:00", "days": []},
    )
    duty = DutySchedule(cfg)

    store = PersistentTaskStore(db_path=None)
    scheduler = ProactiveHeartbeatScheduler(store, duty)

    saturday = datetime(2026, 5, 23, 10, 0)
    assert scheduler.should_dispatch_scan('inbox', saturday) is False
    assert scheduler.suppression_reason('inbox', saturday) == 'outside_work_hours'
