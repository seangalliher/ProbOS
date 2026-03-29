"""Tests for Workforce Scheduling Engine (AD-496)."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from probos.workforce import (
    AgentCalendar,
    AssignmentMode,
    BookableResource,
    Booking,
    BookingJournal,
    BookingStatus,
    BookingTimestamp,
    CalendarEntry,
    JournalType,
    ResourceRequirement,
    ResourceType,
    WorkItem,
    WorkItemStatus,
    WorkItemStore,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """Return path for a temporary SQLite database."""
    return str(tmp_path / "test_workforce.db")


@pytest.fixture
def mock_emit():
    return MagicMock()


@pytest.fixture
async def store(tmp_db, mock_emit):
    """Create, start, yield, and stop a WorkItemStore."""
    s = WorkItemStore(
        db_path=tmp_db,
        emit_event=mock_emit,
        tick_interval=1000,  # High interval to prevent auto-ticking
    )
    await s.start()
    yield s
    await s.stop()


@pytest.fixture
def sample_resource():
    """A sample BookableResource for testing."""
    return BookableResource(
        resource_id="agent-001",
        resource_type="crew",
        agent_type="scout",
        callsign="Hawkeye",
        capacity=2,
        department="science",
        characteristics=[
            {"skill": "scout", "proficiency": 1.0},
            {"skill": "science", "proficiency": 1.0},
            {"skill": "trust", "proficiency": 0.75},
        ],
        active=True,
    )


@pytest.fixture
async def store_with_resource(store, sample_resource):
    """Store with a registered resource."""
    store.register_resource(sample_resource)
    store.register_calendar(AgentCalendar(
        resource_id="agent-001",
        entries=[CalendarEntry()],
    ))
    return store


# ---------------------------------------------------------------------------
# TestWorkItemCRUD
# ---------------------------------------------------------------------------

class TestWorkItemCRUD:
    @pytest.mark.asyncio
    async def test_create_work_item_basic(self, store):
        item = await store.create_work_item(title="Test task")
        assert item.id
        assert item.title == "Test task"
        assert item.status == "open"
        assert item.work_type == "task"
        assert item.priority == 3

    @pytest.mark.asyncio
    async def test_create_work_item_all_fields(self, store):
        item = await store.create_work_item(
            title="Full task",
            description="A detailed work item",
            work_type="work_order",
            priority=1,
            parent_id="parent-123",
            depends_on=["dep-1", "dep-2"],
            trust_requirement=0.7,
            required_capabilities=["security"],
            tags=["urgent", "security"],
            metadata={"custom": "value"},
            due_at=time.time() + 3600,
            estimated_tokens=1000,
            ttl_seconds=7200,
            template_id="tmpl-1",
        )
        assert item.work_type == "work_order"
        assert item.priority == 1
        assert item.parent_id == "parent-123"
        assert item.depends_on == ["dep-1", "dep-2"]
        assert item.trust_requirement == 0.7
        assert item.required_capabilities == ["security"]
        assert item.tags == ["urgent", "security"]
        assert item.metadata == {"custom": "value"}
        assert item.ttl_seconds == 7200
        assert item.template_id == "tmpl-1"

    @pytest.mark.asyncio
    async def test_get_work_item(self, store):
        item = await store.create_work_item(title="Fetchable")
        fetched = await store.get_work_item(item.id)
        assert fetched is not None
        assert fetched.title == "Fetchable"

    @pytest.mark.asyncio
    async def test_get_work_item_not_found(self, store):
        result = await store.get_work_item("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_work_items_empty(self, store):
        items = await store.list_work_items()
        assert items == []

    @pytest.mark.asyncio
    async def test_list_work_items_filter_status(self, store):
        await store.create_work_item(title="Open 1")
        item2 = await store.create_work_item(title="Done 1")
        # task: open -> in_progress -> done (AD-498 state machine)
        await store.transition_work_item(item2.id, "in_progress")
        await store.transition_work_item(item2.id, "done")
        open_items = await store.list_work_items(status="open")
        assert len(open_items) == 1
        assert open_items[0].title == "Open 1"

    @pytest.mark.asyncio
    async def test_list_work_items_filter_assigned_to(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Assigned")
        await store.assign_work_item(item.id, "agent-001")
        assigned = await store.list_work_items(assigned_to="agent-001")
        assert len(assigned) == 1

    @pytest.mark.asyncio
    async def test_list_work_items_filter_work_type(self, store):
        await store.create_work_item(title="Task", work_type="task")
        await store.create_work_item(title="Card", work_type="card")
        tasks = await store.list_work_items(work_type="task")
        assert len(tasks) == 1
        assert tasks[0].title == "Task"

    @pytest.mark.asyncio
    async def test_list_work_items_filter_parent_id(self, store):
        parent = await store.create_work_item(title="Parent")
        await store.create_work_item(title="Child", parent_id=parent.id)
        await store.create_work_item(title="Orphan")
        children = await store.list_work_items(parent_id=parent.id)
        assert len(children) == 1
        assert children[0].title == "Child"

    @pytest.mark.asyncio
    async def test_list_work_items_pagination(self, store):
        for i in range(5):
            await store.create_work_item(title=f"Item {i}")
        page1 = await store.list_work_items(limit=2, offset=0)
        page2 = await store.list_work_items(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2

    @pytest.mark.asyncio
    async def test_update_work_item(self, store):
        item = await store.create_work_item(title="Original")
        updated = await store.update_work_item(item.id, title="Updated", priority=1)
        assert updated is not None
        assert updated.title == "Updated"
        assert updated.priority == 1

    @pytest.mark.asyncio
    async def test_update_work_item_not_found(self, store):
        result = await store.update_work_item("nonexistent", title="X")
        assert result is None

    @pytest.mark.asyncio
    async def test_transition_work_item(self, store):
        item = await store.create_work_item(title="Transition me")
        updated = await store.transition_work_item(item.id, "in_progress")
        assert updated is not None
        assert updated.status == "in_progress"

    @pytest.mark.asyncio
    async def test_transition_from_terminal_status_rejected(self, store):
        item = await store.create_work_item(title="Terminal")
        await store.transition_work_item(item.id, "done")
        result = await store.transition_work_item(item.id, "open")
        assert result is None  # Can't transition from done

    @pytest.mark.asyncio
    async def test_delete_work_item_cascades(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Delete me")
        await store.assign_work_item(item.id, "agent-001")
        deleted = await store.delete_work_item(item.id)
        assert deleted is True
        assert await store.get_work_item(item.id) is None
        bookings = await store.list_bookings(work_item_id=item.id)
        assert len(bookings) == 0


# ---------------------------------------------------------------------------
# TestAssignmentEngine
# ---------------------------------------------------------------------------

class TestAssignmentEngine:
    @pytest.mark.asyncio
    async def test_push_assign_basic(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Assign me")
        booking = await store.assign_work_item(item.id, "agent-001")
        assert booking is not None
        assert booking.resource_id == "agent-001"
        assert booking.work_item_id == item.id

    @pytest.mark.asyncio
    async def test_push_assign_creates_booking(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Book it")
        booking = await store.assign_work_item(item.id, "agent-001")
        assert booking is not None
        fetched = await store.get_booking(booking.id)
        assert fetched is not None
        assert fetched.status == "scheduled"

    @pytest.mark.asyncio
    async def test_push_assign_ineligible_trust(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(
            title="High trust",
            trust_requirement=0.9,  # agent-001 has trust 0.75
        )
        booking = await store.assign_work_item(item.id, "agent-001")
        assert booking is None

    @pytest.mark.asyncio
    async def test_push_assign_ineligible_capacity(self, store_with_resource):
        store = store_with_resource
        # Fill both capacity slots
        item1 = await store.create_work_item(title="Job 1")
        item2 = await store.create_work_item(title="Job 2")
        await store.assign_work_item(item1.id, "agent-001")
        await store.assign_work_item(item2.id, "agent-001")
        # Third should fail (capacity=2)
        item3 = await store.create_work_item(title="Job 3")
        booking = await store.assign_work_item(item3.id, "agent-001")
        assert booking is None

    @pytest.mark.asyncio
    async def test_push_assign_ineligible_capabilities(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(
            title="Need engineering",
            required_capabilities=["engineering"],  # agent-001 doesn't have this
        )
        booking = await store.assign_work_item(item.id, "agent-001")
        assert booking is None

    @pytest.mark.asyncio
    async def test_pull_claim_highest_priority(self, store_with_resource):
        store = store_with_resource
        await store.create_work_item(title="Low priority", priority=5)
        await store.create_work_item(title="High priority", priority=1)
        result = await store.claim_work_item("agent-001")
        assert result is not None
        work_item, booking = result
        assert work_item.title == "High priority"

    @pytest.mark.asyncio
    async def test_pull_claim_respects_trust_requirement(self, store_with_resource):
        store = store_with_resource
        await store.create_work_item(title="Only high trust", trust_requirement=0.9)
        result = await store.claim_work_item("agent-001")
        assert result is None  # 0.75 < 0.9

    @pytest.mark.asyncio
    async def test_pull_claim_no_eligible_returns_none(self, store):
        result = await store.claim_work_item("nonexistent-agent")
        assert result is None

    @pytest.mark.asyncio
    async def test_pull_claim_filter_work_type(self, store_with_resource):
        store = store_with_resource
        await store.create_work_item(title="Task", work_type="task")
        await store.create_work_item(title="Incident", work_type="incident")
        result = await store.claim_work_item("agent-001", work_type="incident")
        assert result is not None
        assert result[0].work_type == "incident"

    @pytest.mark.asyncio
    async def test_unassign_work_item(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Unassign me")
        await store.assign_work_item(item.id, "agent-001")
        result = await store.unassign_work_item(item.id)
        assert result is True
        updated = await store.get_work_item(item.id)
        assert updated is not None
        assert updated.assigned_to is None
        assert updated.status == "open"


# ---------------------------------------------------------------------------
# TestBookingLifecycle
# ---------------------------------------------------------------------------

class TestBookingLifecycle:
    @pytest.mark.asyncio
    async def test_booking_start(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Start me")
        booking = await store.assign_work_item(item.id, "agent-001")
        assert booking is not None
        started = await store.start_booking(booking.id)
        assert started is not None
        assert started.status == "active"
        assert started.actual_start is not None

    @pytest.mark.asyncio
    async def test_booking_pause_resume(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Pause me")
        booking = await store.assign_work_item(item.id, "agent-001")
        await store.start_booking(booking.id)
        paused = await store.pause_booking(booking.id)
        assert paused is not None
        assert paused.status == "on_break"
        resumed = await store.resume_booking(booking.id)
        assert resumed is not None
        assert resumed.status == "active"

    @pytest.mark.asyncio
    async def test_booking_complete(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Complete me")
        booking = await store.assign_work_item(item.id, "agent-001")
        await store.start_booking(booking.id)
        completed = await store.complete_booking(booking.id, tokens_consumed=500)
        assert completed is not None
        assert completed.status == "completed"
        assert completed.total_tokens_consumed == 500

    @pytest.mark.asyncio
    async def test_booking_cancel(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Cancel me")
        booking = await store.assign_work_item(item.id, "agent-001")
        cancelled = await store.cancel_booking(booking.id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"

    @pytest.mark.asyncio
    async def test_booking_timestamps_appended(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Timestamps")
        booking = await store.assign_work_item(item.id, "agent-001")
        await store.start_booking(booking.id)
        await store.complete_booking(booking.id)
        # Check timestamps were recorded
        cursor = await store._db.execute(
            "SELECT * FROM booking_timestamps WHERE booking_id = ? ORDER BY timestamp",
            (booking.id,),
        )
        rows = await cursor.fetchall()
        assert len(rows) >= 3  # scheduled, active, completed

    @pytest.mark.asyncio
    async def test_generate_journal_working_segment(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Journal")
        booking = await store.assign_work_item(item.id, "agent-001")
        await store.start_booking(booking.id)
        await store.complete_booking(booking.id)
        entries = await store.get_booking_journal(booking.id)
        assert len(entries) >= 1
        # Should have at least an active→completed segment
        working = [e for e in entries if e.journal_type == "working"]
        assert len(working) >= 1

    @pytest.mark.asyncio
    async def test_generate_journal_with_break(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Break journal")
        booking = await store.assign_work_item(item.id, "agent-001")
        await store.start_booking(booking.id)
        await store.pause_booking(booking.id)
        await store.resume_booking(booking.id)
        await store.complete_booking(booking.id)
        entries = await store.get_booking_journal(booking.id)
        types = [e.journal_type for e in entries]
        assert "working" in types
        assert "break" in types

    @pytest.mark.asyncio
    async def test_complete_booking_generates_journal(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Auto journal")
        booking = await store.assign_work_item(item.id, "agent-001")
        await store.start_booking(booking.id)
        await store.complete_booking(booking.id, tokens_consumed=100)
        entries = await store.get_booking_journal(booking.id)
        assert len(entries) >= 1

    @pytest.mark.asyncio
    async def test_list_bookings_filter_resource(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Filter resource")
        await store.assign_work_item(item.id, "agent-001")
        bookings = await store.list_bookings(resource_id="agent-001")
        assert len(bookings) == 1
        empty = await store.list_bookings(resource_id="nonexistent")
        assert len(empty) == 0

    @pytest.mark.asyncio
    async def test_list_bookings_filter_status(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Filter status")
        booking = await store.assign_work_item(item.id, "agent-001")
        scheduled = await store.list_bookings(status="scheduled")
        assert len(scheduled) == 1
        active = await store.list_bookings(status="active")
        assert len(active) == 0


# ---------------------------------------------------------------------------
# TestResourceRegistry
# ---------------------------------------------------------------------------

class TestResourceRegistry:
    def test_register_resource(self, store, sample_resource):
        store.register_resource(sample_resource)
        assert store.get_resource("agent-001") is not None

    def test_unregister_resource(self, store, sample_resource):
        store.register_resource(sample_resource)
        store.unregister_resource("agent-001")
        assert store.get_resource("agent-001") is None

    def test_list_resources_filter_department(self, store, sample_resource):
        store.register_resource(sample_resource)
        science = store.list_resources(department="science")
        assert len(science) == 1
        engineering = store.list_resources(department="engineering")
        assert len(engineering) == 0

    def test_list_resources_filter_type(self, store, sample_resource):
        store.register_resource(sample_resource)
        crew = store.list_resources(resource_type="crew")
        assert len(crew) == 1
        infra = store.list_resources(resource_type="infrastructure")
        assert len(infra) == 0

    def test_list_resources_active_only(self, store):
        active = BookableResource(resource_id="a1", active=True)
        inactive = BookableResource(resource_id="a2", active=False)
        store.register_resource(active)
        store.register_resource(inactive)
        result = store.list_resources(active_only=True)
        assert len(result) == 1
        assert result[0].resource_id == "a1"
        all_result = store.list_resources(active_only=False)
        assert len(all_result) == 2

    @pytest.mark.asyncio
    async def test_get_resource_availability_basic(self, store_with_resource):
        store = store_with_resource
        avail = store.get_resource_availability("agent-001")
        assert avail is not None
        assert avail["capacity"] == 2
        assert avail["active_bookings"] == 0
        assert avail["available_capacity"] == 2

    @pytest.mark.asyncio
    async def test_get_resource_availability_with_active_bookings(self, store_with_resource):
        store = store_with_resource
        item = await store.create_work_item(title="Active booking")
        await store.assign_work_item(item.id, "agent-001")
        avail = store.get_resource_availability("agent-001")
        assert avail is not None
        assert avail["active_bookings"] == 1
        assert avail["available_capacity"] == 1

    @pytest.mark.asyncio
    async def test_eligibility_check(self, store_with_resource):
        store = store_with_resource
        resource = store.get_resource("agent-001")
        # Eligible
        item = WorkItem(title="Eligible", trust_requirement=0.5)
        assert store._check_eligibility(resource, item) is True
        # Not eligible (trust too high)
        item2 = WorkItem(title="Too high trust", trust_requirement=0.9)
        assert store._check_eligibility(resource, item2) is False
        # Not eligible (missing capability)
        item3 = WorkItem(title="Missing cap", required_capabilities=["engineering"])
        assert store._check_eligibility(resource, item3) is False


# ---------------------------------------------------------------------------
# TestWorkItemStoreTick
# ---------------------------------------------------------------------------

class TestWorkItemStoreTick:
    @pytest.mark.asyncio
    async def test_ttl_expiry(self, store):
        item = await store.create_work_item(
            title="Expiring", ttl_seconds=1,
            created_at=time.time() - 10,  # 10s ago with 1s TTL = expired
        )
        await store._expire_ttl_items()
        updated = await store.get_work_item(item.id)
        assert updated is not None
        assert updated.status == "cancelled"

    @pytest.mark.asyncio
    async def test_ttl_not_expired_ignored(self, store):
        item = await store.create_work_item(title="Not expiring", ttl_seconds=3600)
        await store._expire_ttl_items()
        updated = await store.get_work_item(item.id)
        assert updated is not None
        assert updated.status == "open"

    @pytest.mark.asyncio
    async def test_overdue_item_logged(self, store, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            await store.create_work_item(
                title="Overdue task",
                due_at=time.time() - 100,  # 100s ago
            )
            await store._check_overdue_items()
        assert "Overdue work item" in caplog.text

    @pytest.mark.asyncio
    async def test_tick_loop_starts_and_stops(self, tmp_db, mock_emit):
        s = WorkItemStore(db_path=tmp_db, emit_event=mock_emit, tick_interval=1000)
        await s.start()
        assert s._running is True
        assert s._tick_task is not None
        await s.stop()
        assert s._running is False

    @pytest.mark.asyncio
    async def test_snapshot_cache_refreshed(self, store):
        await store.create_work_item(title="Cached")
        snap = store.snapshot()
        assert len(snap["work_items"]) == 1
        assert snap["work_items"][0]["title"] == "Cached"


# ---------------------------------------------------------------------------
# TestWorkforceSnapshot
# ---------------------------------------------------------------------------

class TestWorkforceSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_includes_active_items(self, store):
        await store.create_work_item(title="Active item")
        snap = store.snapshot()
        assert len(snap["work_items"]) == 1

    @pytest.mark.asyncio
    async def test_snapshot_excludes_terminal_items(self, store):
        item = await store.create_work_item(title="Terminal item")
        # task: open -> in_progress -> done (AD-498 state machine)
        await store.transition_work_item(item.id, "in_progress")
        await store.transition_work_item(item.id, "done")
        snap = store.snapshot()
        assert len(snap["work_items"]) == 0

    @pytest.mark.asyncio
    async def test_snapshot_included_in_state_snapshot(self):
        """Verify runtime.build_state_snapshot includes workforce key."""
        import inspect
        from probos.runtime import ProbOSRuntime
        src = inspect.getsource(ProbOSRuntime.build_state_snapshot)
        assert "workforce" in src


# ---------------------------------------------------------------------------
# TestEventEmission
# ---------------------------------------------------------------------------

class TestEventEmission:
    @pytest.mark.asyncio
    async def test_create_emits_event(self, store, mock_emit):
        await store.create_work_item(title="Emit test")
        calls = [c for c in mock_emit.call_args_list if c[0][0] == "work_item_created"]
        assert len(calls) == 1
        data = calls[0][0][1]
        assert "work_item" in data
        assert data["work_item"]["title"] == "Emit test"

    @pytest.mark.asyncio
    async def test_transition_emits_status_changed(self, store, mock_emit):
        item = await store.create_work_item(title="Transition emit")
        mock_emit.reset_mock()
        await store.transition_work_item(item.id, "in_progress")
        calls = [c for c in mock_emit.call_args_list if c[0][0] == "work_item_status_changed"]
        assert len(calls) == 1
        data = calls[0][0][1]
        assert data["old_status"] == "open"
        assert data["new_status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_assign_emits_event(self, store_with_resource, mock_emit):
        store = store_with_resource
        item = await store.create_work_item(title="Assign emit")
        mock_emit.reset_mock()
        await store.assign_work_item(item.id, "agent-001")
        calls = [c for c in mock_emit.call_args_list if c[0][0] == "work_item_assigned"]
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_booking_complete_emits_event(self, store_with_resource, mock_emit):
        store = store_with_resource
        item = await store.create_work_item(title="Complete emit")
        booking = await store.assign_work_item(item.id, "agent-001")
        await store.start_booking(booking.id)
        mock_emit.reset_mock()
        await store.complete_booking(booking.id)
        calls = [c for c in mock_emit.call_args_list if c[0][0] == "booking_completed"]
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# TestDataModel
# ---------------------------------------------------------------------------

class TestDataModel:
    def test_work_item_to_dict(self):
        item = WorkItem(id="test", title="Test")
        d = item.to_dict()
        assert d["id"] == "test"
        assert d["title"] == "Test"
        assert "depends_on" in d
        assert "metadata" in d

    def test_booking_to_dict(self):
        b = Booking(id="b1", resource_id="r1", work_item_id="w1")
        d = b.to_dict()
        assert d["resource_id"] == "r1"
        assert d["work_item_id"] == "w1"

    def test_resource_to_dict(self):
        r = BookableResource(resource_id="r1", callsign="Test")
        d = r.to_dict()
        assert d["callsign"] == "Test"

    def test_calendar_entry_to_dict(self):
        e = CalendarEntry(day_pattern="mon-fri", start_hour=9, end_hour=17)
        d = e.to_dict()
        assert d["day_pattern"] == "mon-fri"
        assert d["start_hour"] == 9
        assert d["end_hour"] == 17

    def test_calendar_to_dict(self):
        c = AgentCalendar(resource_id="r1", entries=[CalendarEntry()])
        d = c.to_dict()
        assert d["resource_id"] == "r1"
        assert len(d["entries"]) == 1

    def test_requirement_to_dict(self):
        r = ResourceRequirement(work_item_id="w1", min_trust=0.5)
        d = r.to_dict()
        assert d["min_trust"] == 0.5

    def test_timestamp_to_dict(self):
        t = BookingTimestamp(booking_id="b1", status="active")
        d = t.to_dict()
        assert d["status"] == "active"

    def test_journal_to_dict(self):
        j = BookingJournal(booking_id="b1", journal_type="working", duration_seconds=60)
        d = j.to_dict()
        assert d["duration_seconds"] == 60

    def test_enums_are_strings(self):
        assert WorkItemStatus.OPEN.value == "open"
        assert BookingStatus.ACTIVE.value == "active"
        assert JournalType.WORKING.value == "working"
        assert ResourceType.CREW.value == "crew"
        assert AssignmentMode.PUSH.value == "push"


# ---------------------------------------------------------------------------
# TestWorkforceConfig
# ---------------------------------------------------------------------------

class TestWorkforceConfig:
    def test_config_defaults(self):
        from probos.config import WorkforceConfig
        config = WorkforceConfig()
        assert config.enabled is False
        assert config.tick_interval_seconds == 10.0
        assert config.default_capacity == 1

    def test_config_in_system_config(self):
        from probos.config import SystemConfig
        config = SystemConfig()
        assert hasattr(config, 'workforce')
        assert config.workforce.enabled is False


# ── AD-497 Tests ─────────────────────────────────────────────────────

class TestSnapshotIncludesResources:
    """AD-497: Snapshot should contain bookable resources."""

    @pytest.mark.asyncio
    async def test_workforce_snapshot_includes_resources(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            # Register a resource
            res = BookableResource(
                resource_id="agent-uuid-1",
                resource_type=ResourceType.CREW,
                agent_type="SecurityAgent",
                callsign="Worf",
                capacity=1,
                department="Security",
                characteristics=[{"name": "security", "value": "expert"}],
                display_on_board=True,
                active=True,
            )
            store.register_resource(res)

            snapshot = store.snapshot()
            assert "resources" in snapshot
            assert len(snapshot["resources"]) == 1
            assert snapshot["resources"][0]["resource_id"] == "agent-uuid-1"
            assert snapshot["resources"][0]["callsign"] == "Worf"
            assert snapshot["resources"][0]["department"] == "Security"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_snapshot_resources_empty_when_none_registered(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            snapshot = store.snapshot()
            assert "resources" in snapshot
            assert snapshot["resources"] == []
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_snapshot_preserves_work_items_and_bookings(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            # Create a work item so snapshot has data
            await store.create_work_item(title="Test", work_type="task")
            await store._refresh_snapshot_cache()
            snapshot = store.snapshot()
            assert "work_items" in snapshot
            assert "bookings" in snapshot
            assert "resources" in snapshot
        finally:
            await store.stop()


# ── AD-498  Work Type Registry & Templates ──────────────────────────────


class TestWorkTypeRegistry:
    """Unit tests for WorkTypeRegistry."""

    def test_builtin_types_registered(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        types = reg.list_types()
        assert len(types) >= 5
        type_ids = [t.type_id for t in types]
        for expected in ("card", "task", "work_order", "duty", "incident"):
            assert expected in type_ids

    def test_card_state_machine(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        assert reg.validate_transition("card", "draft", "open") == (True, "")
        assert reg.validate_transition("card", "open", "done") == (True, "")
        valid, reason = reg.validate_transition("card", "draft", "in_progress")
        assert not valid

    def test_task_state_machine(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        assert reg.validate_transition("task", "open", "in_progress") == (True, "")
        assert reg.validate_transition("task", "in_progress", "done") == (True, "")
        valid, _ = reg.validate_transition("task", "open", "done")
        assert not valid

    def test_work_order_state_machine(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        assert reg.validate_transition("work_order", "draft", "open") == (True, "")
        assert reg.validate_transition("work_order", "in_progress", "review") == (True, "")
        assert reg.validate_transition("work_order", "review", "done") == (True, "")
        valid, _ = reg.validate_transition("work_order", "open", "done")
        assert not valid

    def test_duty_state_machine(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        assert reg.validate_transition("duty", "scheduled", "in_progress") == (True, "")
        assert reg.validate_transition("duty", "in_progress", "done") == (True, "")
        valid, _ = reg.validate_transition("duty", "scheduled", "done")
        assert not valid

    def test_incident_state_machine(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        assert reg.validate_transition("incident", "open", "in_progress") == (True, "")
        assert reg.validate_transition("incident", "in_progress", "review") == (True, "")
        assert reg.validate_transition("incident", "review", "done") == (True, "")

    def test_terminal_status_rejected(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        valid, reason = reg.validate_transition("task", "done", "open")
        assert not valid
        assert "terminal" in reason.lower()

    def test_custom_type_registration(self):
        from probos.workforce import WorkTypeRegistry, WorkTypeDefinition, WorkTypeTransition
        reg = WorkTypeRegistry()
        custom = WorkTypeDefinition(
            type_id="custom_test",
            display_name="Custom",
            description="Test type",
            initial_status="new",
            terminal_statuses=frozenset({"closed"}),
            valid_transitions=[WorkTypeTransition("new", "closed")],
        )
        reg.register(custom)
        assert reg.get("custom_test") is not None
        assert reg.validate_transition("custom_test", "new", "closed") == (True, "")

    def test_unknown_type_permissive(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        valid, _ = reg.validate_transition("unknown_type", "foo", "bar")
        assert valid

    def test_initial_statuses(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        assert reg.get_initial_status("card") == "draft"
        assert reg.get_initial_status("task") == "open"
        assert reg.get_initial_status("work_order") == "draft"
        assert reg.get_initial_status("duty") == "scheduled"
        assert reg.get_initial_status("incident") == "open"
        assert reg.get_initial_status("unknown") == "open"

    def test_required_fields(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        wt = reg.get("incident")
        assert wt is not None

    def test_valid_targets(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        targets = reg.get_valid_targets("task", "open")
        assert "in_progress" in targets
        assert "cancelled" in targets

    def test_blocked_transitions(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        assert reg.validate_transition("task", "open", "blocked") == (True, "")
        assert reg.validate_transition("task", "blocked", "in_progress") == (True, "")
        assert reg.validate_transition("task", "blocked", "cancelled") == (True, "")

    def test_to_dict(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        wt = reg.get("task")
        d = wt.to_dict()
        assert d["type_id"] == "task"
        assert "valid_transitions" in d
        assert isinstance(d["valid_transitions"], list)

    def test_cancelled_from_non_terminal(self):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        assert reg.validate_transition("task", "in_progress", "cancelled") == (True, "")
        assert reg.validate_transition("work_order", "open", "cancelled") == (True, "")


class TestTemplateStore:
    """Unit tests for TemplateStore."""

    def test_builtin_count(self):
        from probos.workforce import TemplateStore
        store = TemplateStore()
        templates = store.list_templates()
        assert len(templates) >= 8

    def test_instantiate_with_variables(self):
        from probos.workforce import TemplateStore
        store = TemplateStore()
        data = store.instantiate("security_scan", {"target": "api.py"})
        assert "api.py" in data["title"]
        assert data["work_type"] == "work_order"

    def test_instantiate_without_variables(self):
        from probos.workforce import TemplateStore
        store = TemplateStore()
        data = store.instantiate("crew_health_check", {})
        assert "title" in data
        assert data["work_type"] == "duty"

    def test_instantiate_with_overrides(self):
        from probos.workforce import TemplateStore
        store = TemplateStore()
        data = store.instantiate("code_review", {"target": "main.py"}, overrides={"priority": 1, "assigned_to": "agent-1"})
        assert data["priority"] == 1
        assert data["assigned_to"] == "agent-1"

    def test_category_filter(self):
        from probos.workforce import TemplateStore
        store = TemplateStore()
        security = store.list_templates(category="security")
        assert all(t.category == "security" for t in security)

    def test_night_orders_metadata(self):
        from probos.workforce import TemplateStore
        store = TemplateStore()
        data = store.instantiate("night_maintenance", {})
        assert "metadata" in data
        meta = data.get("metadata", {})
        assert "can_approve_builds" in meta

    def test_ttl_propagation(self):
        from probos.workforce import TemplateStore
        store = TemplateStore()
        data = store.instantiate("night_maintenance", {})
        assert data.get("ttl_seconds") is not None

    def test_not_found_error(self):
        from probos.workforce import TemplateStore
        store = TemplateStore()
        with pytest.raises(ValueError):
            store.instantiate("nonexistent_template", {})

    def test_custom_registration(self):
        from probos.workforce import TemplateStore, WorkItemTemplate
        store = TemplateStore()
        custom = WorkItemTemplate(
            template_id="test_custom",
            name="Custom Test",
            description="A test template",
            work_type="task",
            title_pattern="Custom: {thing}",
            category="test",
        )
        store.register(custom)
        assert store.get("test_custom") is not None
        data = store.instantiate("test_custom", {"thing": "widget"})
        assert data["title"] == "Custom: widget"

    def test_to_dict_variables(self):
        from probos.workforce import TemplateStore
        store = TemplateStore()
        t = store.get("security_scan")
        d = t.to_dict()
        assert "target" in d["variables"]

    def test_metadata_merge(self):
        from probos.workforce import TemplateStore
        store = TemplateStore()
        data = store.instantiate("night_maintenance", {}, overrides={"metadata": {"extra": "val"}})
        # Overrides replace metadata entirely when passed as dict
        assert data["metadata"].get("extra") == "val"

    def test_reload_templates(self):
        from probos.workforce import TemplateStore
        store = TemplateStore()
        initial = len(store.list_templates())
        store.reload_templates([])
        assert len(store.list_templates()) == initial


class TestWorkTypeValidationIntegration:
    """Integration tests: WorkItemStore + WorkTypeRegistry."""

    @pytest.mark.asyncio
    async def test_initial_status_card(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            item = await store.create_work_item(title="Card", work_type="card")
            assert item.status == "draft"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_initial_status_task(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            item = await store.create_work_item(title="Task", work_type="task")
            assert item.status == "open"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_initial_status_duty(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            item = await store.create_work_item(title="Duty", work_type="duty")
            assert item.status == "scheduled"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_valid_transition(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            item = await store.create_work_item(title="T", work_type="task")
            result = await store.transition_work_item(item.id, "in_progress")
            assert result is not None
            assert result.status == "in_progress"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_invalid_transition_rejected(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            item = await store.create_work_item(title="T", work_type="task")
            result = await store.transition_work_item(item.id, "done")
            assert result is None  # open -> done not valid for task
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_card_direct_done(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            item = await store.create_work_item(title="C", work_type="card")
            # draft -> open
            item = await store.transition_work_item(item.id, "open")
            assert item is not None
            # open -> done
            item = await store.transition_work_item(item.id, "done")
            assert item is not None
            assert item.status == "done"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_work_order_requires_review(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            item = await store.create_work_item(title="WO", work_type="work_order")
            assert item.status == "draft"
            item = await store.transition_work_item(item.id, "open")
            item = await store.transition_work_item(item.id, "scheduled")
            item = await store.transition_work_item(item.id, "in_progress")
            # Can't skip review
            result = await store.transition_work_item(item.id, "done")
            assert result is None
            item = await store.transition_work_item(item.id, "review")
            item = await store.transition_work_item(item.id, "done")
            assert item.status == "done"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_create_from_template(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            item = await store.create_from_template(
                "security_scan", {"target": "api.py"}, overrides={"assigned_to": "agent-1"}
            )
            assert "api.py" in item.title
            assert item.assigned_to == "agent-1"
            assert item.work_type == "work_order"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_template_ttl(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            item = await store.create_from_template("night_maintenance", {})
            assert item.ttl_seconds is not None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_snapshot_includes_types_and_templates(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            await store._refresh_snapshot_cache()
            snapshot = store.snapshot()
            assert "work_types" in snapshot
            assert "templates" in snapshot
            assert len(snapshot["work_types"]) >= 5
            assert len(snapshot["templates"]) >= 8
        finally:
            await store.stop()


class TestWorkTypeAPI:
    """API endpoint tests for work types and templates."""

    @pytest.mark.asyncio
    async def test_work_types_list(self, tmp_path):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        types = reg.list_types()
        assert len(types) >= 5

    @pytest.mark.asyncio
    async def test_templates_list_all(self, tmp_path):
        from probos.workforce import TemplateStore
        store = TemplateStore()
        templates = store.list_templates()
        assert len(templates) >= 8

    @pytest.mark.asyncio
    async def test_templates_list_filtered(self, tmp_path):
        from probos.workforce import TemplateStore
        store = TemplateStore()
        security = store.list_templates(category="security")
        ops = store.list_templates(category="operations")
        assert len(security) >= 1
        assert len(ops) >= 1

    @pytest.mark.asyncio
    async def test_transitions_api(self, tmp_path):
        from probos.workforce import WorkTypeRegistry
        reg = WorkTypeRegistry()
        targets = reg.get_valid_targets("task", "open")
        assert isinstance(targets, list)
        assert "in_progress" in targets

    @pytest.mark.asyncio
    async def test_create_from_template_variables(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            item = await store.create_from_template(
                "engineering_diagnostic", {"system": "EPS Grid"}
            )
            assert "EPS Grid" in item.title
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_invalid_template_raises(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            with pytest.raises(ValueError):
                await store.create_from_template("nonexistent", {})
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_custom_config_types(self, tmp_path):
        config = {
            "custom_work_types": [{
                "type_id": "epic",
                "display_name": "Epic",
                "description": "Large feature",
                "initial_status": "draft",
                "terminal_statuses": ["done", "cancelled"],
                "valid_transitions": [
                    {"from_status": "draft", "to_status": "open"},
                    {"from_status": "open", "to_status": "done"},
                ],
            }],
            "custom_templates": [],
        }
        store = WorkItemStore(db_path=str(tmp_path / "test.db"), config=config)
        await store.start()
        try:
            assert store.work_type_registry.get("epic") is not None
            item = await store.create_work_item(title="E", work_type="epic")
            assert item.status == "draft"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_backward_compat_unknown_type(self, tmp_path):
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            item = await store.create_work_item(title="X", work_type="mystery_type")
            assert item.status == "open"  # default initial status
            result = await store.transition_work_item(item.id, "in_progress")
            assert result is not None  # permissive for unknown types
        finally:
            await store.stop()
