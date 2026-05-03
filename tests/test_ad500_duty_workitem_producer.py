"""AD-500: DutyScheduleTracker → WorkItem producer (Section 2-3).

Tests the producer-only side of duty WorkItem migration. v1 ships:
- `DutyScheduleTracker.emit_due_duties_as_work_items()` producer method.
- `DutyScheduleConfig.use_work_items: bool = False` opt-in flag.

Consumer (proactive loop) migration deferred to AD-500a-1.
"""

from __future__ import annotations

import time
import unittest
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.config import DutyScheduleConfig
from probos.duty_schedule import DutyScheduleTracker
from probos.events import EventType
from probos.workforce import BUILTIN_WORK_TYPES, WorkTypeRegistry


@dataclass
class _FakeDuty:
    """Stand-in for `DutyDefinition` (duty_schedule's `get_due_duties` reads
    cron/interval_seconds/priority/duty_id/description ducktype)."""
    duty_id: str = "scout_report"
    description: str = "Run scout report"
    cron: str = ""
    interval_seconds: float = 1.0
    priority: int = 2


@dataclass
class _FakeWorkItem:
    id: str = "wi-abc"
    work_type: str = "duty"
    assigned_to: str = ""
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class TestAD500DutyWorkType(unittest.TestCase):
    """Section 1 verify-only: AD-498 `duty` work type registration."""

    def test_duty_work_type_registered(self) -> None:
        """The `duty` work type is pre-registered (AD-498 dependency)."""
        # Module-level builtin table
        assert "duty" in BUILTIN_WORK_TYPES
        assert BUILTIN_WORK_TYPES["duty"].type_id == "duty"
        assert BUILTIN_WORK_TYPES["duty"].initial_status == "scheduled"
        # Registry instance also exposes it
        registry = WorkTypeRegistry()
        defn = registry.get("duty")
        assert defn is not None
        assert defn.initial_status == "scheduled"


class TestAD500UseWorkItemsFlag(unittest.TestCase):
    """Section 3: opt-in flag default-False per convention #14."""

    def test_use_work_items_flag_default_false(self) -> None:
        """`DutyScheduleConfig().use_work_items` defaults to False (opt-in)."""
        cfg = DutyScheduleConfig()
        assert cfg.use_work_items is False

    def test_use_work_items_flag_can_be_enabled(self) -> None:
        """Operators can flip the flag to True via config."""
        cfg = DutyScheduleConfig(use_work_items=True)
        assert cfg.use_work_items is True


@pytest.mark.asyncio
async def test_emit_due_duties_creates_work_items_via_create_work_item() -> None:
    """Producer calls `WorkItemStore.create_work_item(work_type='duty', ...)` per due duty."""
    duty = _FakeDuty(duty_id="scout_report", description="Run scout report")
    tracker = DutyScheduleTracker(schedules={"scout": [duty]})

    store = MagicMock()
    store.create_work_item = AsyncMock(return_value=_FakeWorkItem(id="wi-1"))

    ids = await tracker.emit_due_duties_as_work_items("scout", store)

    assert ids == ["wi-1"]
    store.create_work_item.assert_awaited_once()
    kwargs = store.create_work_item.await_args.kwargs
    assert kwargs["work_type"] == "duty"
    assert kwargs["assigned_to"] == "scout"
    assert kwargs["title"] == "Run scout report"
    assert kwargs["metadata"]["duty_id"] == "scout_report"
    assert kwargs["metadata"]["agent_type"] == "scout"


@pytest.mark.asyncio
async def test_emit_due_duties_returns_work_item_ids() -> None:
    """Method returns IDs matching what the store returned, in due-duty order."""
    duties = [
        _FakeDuty(duty_id="d1", description="duty one", priority=5),
        _FakeDuty(duty_id="d2", description="duty two", priority=3),
    ]
    tracker = DutyScheduleTracker(schedules={"scout": duties})

    store = MagicMock()
    store.create_work_item = AsyncMock(side_effect=[
        _FakeWorkItem(id="wi-A"),
        _FakeWorkItem(id="wi-B"),
    ])

    ids = await tracker.emit_due_duties_as_work_items("scout", store)
    assert ids == ["wi-A", "wi-B"]
    assert store.create_work_item.await_count == 2


@pytest.mark.asyncio
async def test_emit_due_duties_emits_work_item_created_event() -> None:
    """Producer relies on store's existing WORK_ITEM_CREATED emission (no new event)."""
    duty = _FakeDuty(duty_id="scout_report")
    tracker = DutyScheduleTracker(schedules={"scout": [duty]})

    events: list[tuple[str, dict[str, Any]]] = []

    async def _create(**kwargs: Any) -> _FakeWorkItem:
        # Mirror what the real WorkItemStore.create_work_item does at workforce.py:1051
        item = _FakeWorkItem(
            id="wi-evt",
            work_type=kwargs["work_type"],
            assigned_to=kwargs.get("assigned_to", ""),
            title=kwargs.get("title", ""),
            metadata=kwargs.get("metadata", {}),
        )
        events.append((EventType.WORK_ITEM_CREATED, {"work_item": {"id": item.id}}))
        return item

    store = MagicMock()
    store.create_work_item = _create

    ids = await tracker.emit_due_duties_as_work_items("scout", store)
    assert ids == ["wi-evt"]
    assert len(events) == 1
    assert events[0][0] == EventType.WORK_ITEM_CREATED


@pytest.mark.asyncio
async def test_emit_due_duties_no_due_duties_returns_empty() -> None:
    """When no duties are due, returns [] and makes zero create_work_item calls."""
    # No schedules registered for this agent type → get_due_duties returns []
    tracker = DutyScheduleTracker(schedules={})

    store = MagicMock()
    store.create_work_item = AsyncMock()

    ids = await tracker.emit_due_duties_as_work_items("scout", store)
    assert ids == []
    store.create_work_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_emit_due_duties_does_not_call_record_execution() -> None:
    """v1 producer-side ONLY: `record_execution` stays on the legacy path.

    AD-500a-1 will integrate the booking lifecycle. v1 must not double-record.
    """
    duty = _FakeDuty(duty_id="scout_report", interval_seconds=1.0)
    tracker = DutyScheduleTracker(schedules={"scout": [duty]})

    store = MagicMock()
    store.create_work_item = AsyncMock(return_value=_FakeWorkItem(id="wi-1"))

    # Snapshot status pre-call: nothing recorded yet
    pre_status = list(tracker._status.items())
    assert pre_status == []

    await tracker.emit_due_duties_as_work_items("scout", store)

    # Post-call: still nothing recorded — record_execution NOT called from producer
    post_status = list(tracker._status.items())
    assert post_status == []


@pytest.mark.asyncio
async def test_emit_due_duties_uses_duty_id_when_description_missing() -> None:
    """If description is empty, title falls back to duty_id."""
    duty = _FakeDuty(duty_id="silent_duty", description="")
    tracker = DutyScheduleTracker(schedules={"scout": [duty]})

    store = MagicMock()
    store.create_work_item = AsyncMock(return_value=_FakeWorkItem(id="wi-1"))

    await tracker.emit_due_duties_as_work_items("scout", store)
    kwargs = store.create_work_item.await_args.kwargs
    assert kwargs["title"] == "silent_duty"
