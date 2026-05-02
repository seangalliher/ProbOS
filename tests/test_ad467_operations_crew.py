"""AD-467 Operations Crew tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.agents.operations import (
    CoordinatorAgent,
    ResourceAllocatorAgent,
    SchedulerAgent,
)
from probos.config import OperationsConfig
from probos.events import EventType


# ----- EventTypes -----


def test_event_type_resource_allocated_exists():
    assert EventType.RESOURCE_ALLOCATED.value == "resource_allocated"


def test_event_type_task_scheduled_exists():
    assert EventType.TASK_SCHEDULED.value == "task_scheduled"


def test_event_type_workflow_started_exists():
    assert EventType.WORKFLOW_STARTED.value == "workflow_started"


# ----- Config -----


def test_operations_config_defaults():
    cfg = OperationsConfig()
    assert cfg.enabled is True
    assert cfg.resource_interval_seconds == 30.0
    assert cfg.resource_emit_interval_seconds == 60.0
    assert cfg.scheduler_interval_seconds == 60.0
    assert cfg.coordinator_interval_seconds == 60.0


# ----- ResourceAllocator -----


def test_resource_allocator_default_pool_name():
    agent = ResourceAllocatorAgent()
    assert agent.pool == "operations_resource"


@pytest.mark.asyncio
async def test_resource_allocator_collect_metrics_no_runtime():
    agent = ResourceAllocatorAgent()
    metrics = await agent.collect_metrics()
    assert "timestamp" in metrics
    assert "agent_id" in metrics
    # No "capacity" key when runtime is None
    assert "capacity" not in metrics


@pytest.mark.asyncio
async def test_resource_allocator_collect_metrics_emits_capacity():
    rt = SimpleNamespace()
    rt.emit_event = MagicMock()
    rt.pools = {
        "alpha": SimpleNamespace(current_size=3, target_size=5),
        "beta": SimpleNamespace(current_size=2, target_size=2),
    }
    agent = ResourceAllocatorAgent(
        runtime=rt, emit_interval_seconds=0.0,  # always emit
    )
    metrics = await agent.collect_metrics()
    assert metrics["capacity"] == {
        "alpha": {"active": 3, "target": 5},
        "beta": {"active": 2, "target": 2},
    }
    rt.emit_event.assert_called_once()
    et, payload = rt.emit_event.call_args[0]
    assert et == EventType.RESOURCE_ALLOCATED
    assert payload["capacity"] == metrics["capacity"]


# ----- Scheduler -----


def test_scheduler_default_pool_name():
    agent = SchedulerAgent()
    assert agent.pool == "operations_scheduler"


@pytest.mark.asyncio
async def test_scheduler_emits_due_tasks():
    rt = SimpleNamespace()
    rt.emit_event = MagicMock()
    agent = SchedulerAgent(
        runtime=rt,
        task_cadences={"audit": 60.0, "summary": 120.0},
    )
    await agent.collect_metrics()
    # Two distinct task kinds emitted on first cycle
    assert rt.emit_event.call_count == 2
    seen_kinds = {call.args[1]["task_kind"] for call in rt.emit_event.call_args_list}
    assert seen_kinds == {"audit", "summary"}
    for call in rt.emit_event.call_args_list:
        et, _ = call.args
        assert et == EventType.TASK_SCHEDULED


@pytest.mark.asyncio
async def test_scheduler_skips_recently_scheduled():
    rt = SimpleNamespace()
    rt.emit_event = MagicMock()
    agent = SchedulerAgent(
        runtime=rt,
        task_cadences={"audit": 3600.0},  # hourly
    )
    await agent.collect_metrics()
    rt.emit_event.reset_mock()
    # Second cycle within cadence window - no new emits
    await agent.collect_metrics()
    rt.emit_event.assert_not_called()


# ----- Coordinator -----


def test_coordinator_default_pool_name():
    agent = CoordinatorAgent()
    assert agent.pool == "operations_coordinator"


def test_coordinator_start_workflow_emits_event():
    rt = SimpleNamespace()
    rt.emit_event = MagicMock()
    agent = CoordinatorAgent(runtime=rt)
    accepted = agent.start_workflow("w1", ["a", "b", "c"])
    assert accepted is True
    rt.emit_event.assert_called_once()
    et, payload = rt.emit_event.call_args[0]
    assert et == EventType.WORKFLOW_STARTED
    assert payload["workflow_name"] == "w1"
    assert payload["step_count"] == 3


def test_coordinator_start_workflow_rejects_duplicate():
    rt = SimpleNamespace()
    rt.emit_event = MagicMock()
    agent = CoordinatorAgent(runtime=rt)
    assert agent.start_workflow("w1", ["a"]) is True
    assert agent.start_workflow("w1", ["b"]) is False
    # Only one emit
    assert rt.emit_event.call_count == 1


# ----- Module exports -----


def test_operations_init_module_exports():
    from probos.agents.operations import (
        CoordinatorAgent as C,
        ResourceAllocatorAgent as R,
        SchedulerAgent as S,
    )
    assert C is CoordinatorAgent
    assert R is ResourceAllocatorAgent
    assert S is SchedulerAgent
