"""Tests for Workforce Scheduling Engine (AD-496)."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Iterable, Sequence
from unittest.mock import MagicMock

import pytest

from probos.protocols import ConnectionFactory, DatabaseConnection
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.workforce import (
    AgentCalendar,
    AssignmentMode,
    BookableResource,
    Booking,
    BookingJournal,
    BookingStatus,
    BookingTimestamp,
    CalendarEntry,
    CrewSessionAdmissionPort,
    CrewSessionParentCreate,
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


class _RecordingConnection:
    def __init__(self, delegate: DatabaseConnection) -> None:
        self._delegate = delegate
        self.queries: list[tuple[str, Sequence[Any]]] = []

    @property
    def row_factory(self) -> Any:
        return self._delegate.row_factory  # type: ignore[attr-defined]

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._delegate.row_factory = value  # type: ignore[attr-defined]

    async def execute(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
    ) -> Any:
        self.queries.append((sql, parameters))
        return await self._delegate.execute(sql, parameters)

    async def executemany(
        self,
        sql: str,
        parameters: Iterable[Sequence[Any]],
    ) -> Any:
        return await self._delegate.executemany(sql, parameters)

    async def executescript(self, sql_script: str) -> None:
        await self._delegate.executescript(sql_script)

    async def fetchone(self) -> Any:
        return await self._delegate.fetchone()

    async def fetchall(self) -> Any:
        return await self._delegate.fetchall()

    async def commit(self) -> None:
        await self._delegate.commit()

    async def close(self) -> None:
        await self._delegate.close()


class _RecordingConnectionFactory:
    def __init__(self) -> None:
        self._delegate: ConnectionFactory = SQLiteConnectionFactory()
        self.connection: _RecordingConnection | None = None

    async def connect(self, db_path: str) -> DatabaseConnection:
        connection = _RecordingConnection(await self._delegate.connect(db_path))
        self.connection = connection
        return connection


async def _create_crew_session_parent(
    admission: CrewSessionAdmissionPort,
    *,
    parent_id: str,
    created_at: float,
) -> WorkItem:
    async with admission.reserve() as reservation:
        return await reservation.create_parent(CrewSessionParentCreate(
            id=parent_id,
            title="Crew session",
            description="Crew session",
            assigned_to="facilitator-1",
            created_by="captain",
            metadata={},
            created_at=created_at,
        ))


# ---------------------------------------------------------------------------
# TestWSVisibleWorkItems
# ---------------------------------------------------------------------------

class TestWSVisibleWorkItems:
    @pytest.mark.asyncio
    async def test_list_ws_visible_work_items_empty_returns_empty(self, store):
        assert await store.list_ws_visible_work_items(limit=100) == []

    @pytest.mark.asyncio
    async def test_list_ws_visible_work_items_unstarted_store_returns_empty(self):
        unstarted = WorkItemStore()
        assert await unstarted.list_ws_visible_work_items(limit=1) == []

    @pytest.mark.asyncio
    async def test_list_ws_visible_work_items_invalid_limit_raises(self):
        unstarted = WorkItemStore()
        for invalid_limit in (True, False, 0, -1, 101, 1.0, "1", None):
            with pytest.raises(
                ValueError,
                match="^ws_visible_work_items_limit_invalid$",
            ):
                await unstarted.list_ws_visible_work_items(limit=invalid_limit)

    @pytest.mark.asyncio
    async def test_list_ws_visible_work_items_crew_rows_do_not_starve_ordinary_rows(
        self,
        store,
    ):
        admission = store.claim_crew_session_admission_port()
        parents: list[WorkItem] = []
        for index in range(51):
            parents.append(await _create_crew_session_parent(
                admission,
                parent_id=f"crew-parent-{index:03d}",
                created_at=300.0 + index,
            ))
        for index, parent in enumerate(parents):
            await store.create_work_item(
                id=f"crew-child-{index:03d}",
                title="Crew child",
                parent_id=parent.id,
                created_at=500.0 + index,
                updated_at=500.0 + index,
            )
        await store.create_work_item(
            id="ordinary-middle",
            title="Ordinary middle",
            created_at=400.0,
            updated_at=400.0,
        )
        await store.create_work_item(
            id="ordinary-tail",
            title="Ordinary tail",
            created_at=100.0,
            updated_at=100.0,
        )

        visible = await store.list_ws_visible_work_items(limit=100)

        assert [item.id for item in visible] == [
            "ordinary-middle",
            "ordinary-tail",
        ]

    @pytest.mark.asyncio
    async def test_list_ws_visible_work_items_parent_classification_is_exact(
        self,
        store,
    ):
        admission = store.claim_crew_session_admission_port()
        crew_parent = await _create_crew_session_parent(
            admission,
            parent_id="crew-parent",
            created_at=10.0,
        )
        ordinary_parent = await store.create_work_item(
            id="ordinary-parent",
            title="Ordinary parent",
            created_at=9.0,
            updated_at=9.0,
        )
        await store.create_work_item(
            id="crew-child",
            title="Crew child",
            parent_id=crew_parent.id,
            created_at=8.0,
            updated_at=8.0,
        )
        await store.create_work_item(
            id="ordinary-child",
            title="Ordinary child",
            parent_id=ordinary_parent.id,
            created_at=7.0,
            updated_at=7.0,
        )
        await store.create_work_item(
            id="missing-parent-child",
            title="Missing parent child",
            parent_id="missing-parent",
            created_at=6.0,
            updated_at=6.0,
        )

        visible = await store.list_ws_visible_work_items(limit=100)
        visible_ids = {item.id for item in visible}

        assert crew_parent.id not in visible_ids
        assert "crew-child" not in visible_ids
        assert visible_ids == {
            ordinary_parent.id,
            "ordinary-child",
            "missing-parent-child",
        }

    @pytest.mark.asyncio
    async def test_list_ws_visible_work_items_returns_cap_plus_one_sentinel(
        self,
        store,
    ):
        for index in range(101):
            await store.create_work_item(
                id=f"ordinary-{index:03d}",
                title="Ordinary",
                created_at=float(index),
                updated_at=float(index),
            )

        visible = await store.list_ws_visible_work_items(limit=100)

        assert len(visible) == 101

    @pytest.mark.asyncio
    async def test_list_ws_visible_work_items_order_is_deterministic(self, store):
        for item_id, priority, created_at in (
            ("priority-two", 2, 20.0),
            ("same-time-b", 1, 10.0),
            ("newest", 1, 30.0),
            ("same-time-a", 1, 10.0),
        ):
            await store.create_work_item(
                id=item_id,
                title=item_id,
                priority=priority,
                created_at=created_at,
                updated_at=created_at,
            )

        visible = await store.list_ws_visible_work_items(limit=100)

        assert [item.id for item in visible] == [
            "newest",
            "same-time-a",
            "same-time-b",
            "priority-two",
        ]

    @pytest.mark.asyncio
    async def test_list_ws_visible_work_items_uses_one_sql_query(
        self,
        tmp_path,
    ):
        factory = _RecordingConnectionFactory()
        recorded_store = WorkItemStore(
            db_path=str(tmp_path / "recorded-workforce.db"),
            connection_factory=factory,
            tick_interval=1_000,
        )
        await recorded_store.start()
        try:
            admission = recorded_store.claim_crew_session_admission_port()
            crew_parent = await _create_crew_session_parent(
                admission,
                parent_id="crew-parent",
                created_at=3.0,
            )
            await recorded_store.create_work_item(
                id="crew-child",
                title="Crew child",
                parent_id=crew_parent.id,
                created_at=2.0,
                updated_at=2.0,
            )
            await recorded_store.create_work_item(
                id="ordinary",
                title="Ordinary",
                created_at=1.0,
                updated_at=1.0,
            )
            assert factory.connection is not None
            factory.connection.queries.clear()

            visible = await recorded_store.list_ws_visible_work_items(limit=100)

            assert [item.id for item in visible] == ["ordinary"]
            assert len(factory.connection.queries) == 1
            sql, parameters = factory.connection.queries[0]
            assert "NOT EXISTS" in sql
            assert "ORDER BY item.priority ASC, item.created_at DESC, item.id ASC" in sql
            assert parameters == ("crew_session", "crew_session", 101)
        finally:
            await recorded_store.stop()

    @pytest.mark.asyncio
    async def test_list_work_items_generic_contract_still_includes_crew_rows(
        self,
        store,
    ):
        admission = store.claim_crew_session_admission_port()
        crew_parent = await _create_crew_session_parent(
            admission,
            parent_id="crew-parent",
            created_at=3.0,
        )
        await store.create_work_item(
            id="crew-child",
            title="Crew child",
            parent_id=crew_parent.id,
            created_at=2.0,
            updated_at=2.0,
        )

        generic = await store.list_work_items(limit=10)

        assert {item.id for item in generic} == {crew_parent.id, "crew-child"}


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
        # BF-608: in_progress requires an assignee (task open->in_progress).
        item2 = await store.create_work_item(title="Done 1", assigned_to="agent-1")
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
        # BF-608: in_progress requires an assignee (task open->in_progress).
        item = await store.create_work_item(title="Transition me", assigned_to="agent-1")
        updated = await store.transition_work_item(item.id, "in_progress")
        assert updated is not None
        assert updated.status == "in_progress"

    @pytest.mark.asyncio
    async def test_transition_from_terminal_status_rejected(self, store):
        # BF-608: in_progress requires an assignee (task open->in_progress).
        item = await store.create_work_item(title="Terminal", assigned_to="agent-1")
        # Reach the terminal 'done' status via the valid task path
        # (open -> in_progress -> done); open -> done is not a legal task
        # transition, so the item must be moved through in_progress first.
        await store.transition_work_item(item.id, "in_progress")
        await store.transition_work_item(item.id, "done")
        result = await store.transition_work_item(item.id, "open")
        assert result is None  # Can't transition from done (terminal)

    @pytest.mark.asyncio
    async def test_transition_same_status_is_idempotent_noop(self, store, mock_emit):
        """BF-606: re-dispatching an already-in_progress item is a no-op success.

        ``work_item_dispatched`` is delivered at-least-once (broadcast fan-out,
        AD-855 resume re-dispatch, bus redelivery). The redundant
        ``in_progress -> in_progress`` must NOT log a warning, must NOT write
        the DB, must NOT emit STATUS_CHANGED, and must return the item (not
        None) so callers don't read it as a failure.
        """
        # BF-608: in_progress requires an assignee (task open->in_progress).
        item = await store.create_work_item(
            title="Dispatched", work_type="task", assigned_to="agent-1",
        )
        moved = await store.transition_work_item(item.id, "in_progress")
        assert moved is not None and moved.status == "in_progress"

        mock_emit.reset_mock()
        again = await store.transition_work_item(item.id, "in_progress")

        # Returns the item unchanged (no-op success), not None.
        assert again is not None
        assert again.status == "in_progress"
        # No event of any kind was emitted for the redundant transition.
        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_transition_same_status_no_invalid_warning(self, store, caplog):
        """BF-606: same-status transition must not emit the 'Invalid transition'
        warning that previously spammed the log dozens of times for a stuck item.
        """
        # BF-608: in_progress requires an assignee (task open->in_progress).
        item = await store.create_work_item(
            title="Stuck", work_type="task", assigned_to="agent-1",
        )
        await store.transition_work_item(item.id, "in_progress")

        with caplog.at_level("WARNING", logger="probos.workforce"):
            result = await store.transition_work_item(item.id, "in_progress")

        assert result is not None
        assert "Invalid transition" not in caplog.text

    @pytest.mark.asyncio
    async def test_requires_assignment_blocks_unassigned_in_progress(self, store, mock_emit):
        """BF-608: a transition flagged ``requires_assignment`` (task
        ``open -> in_progress``) is refused while the item is unassigned, so the
        board can never show the contradictory "in_progress / Unassigned" state
        (work item 1e0ffcdb7b57). The item stays ``open`` and dispatchable.
        """
        item = await store.create_work_item(title="Unowned", work_type="task")
        assert item.assigned_to is None

        mock_emit.reset_mock()
        result = await store.transition_work_item(item.id, "in_progress")

        # Refused: returns None and the item stays in its prior dispatchable status.
        assert result is None
        unchanged = await store.get_work_item(item.id)
        assert unchanged.status == "open"
        # No DB write / STATUS_CHANGED event for the refused transition.
        status_changed = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "work_item_status_changed"
        ]
        assert status_changed == []

    @pytest.mark.asyncio
    async def test_requires_assignment_warns_on_refusal(self, store, caplog):
        """BF-608: the refusal log names the item and its dispatchable status."""
        item = await store.create_work_item(title="Unowned", work_type="task")
        with caplog.at_level("WARNING", logger="probos.workforce"):
            result = await store.transition_work_item(item.id, "in_progress")
        assert result is None
        assert "BF-608" in caplog.text

    @pytest.mark.asyncio
    async def test_requires_assignment_allows_assigned_in_progress(self, store):
        """BF-608: once an owner is set, ``open -> in_progress`` proceeds."""
        item = await store.create_work_item(
            title="Owned", work_type="task", assigned_to="agent-1",
        )
        result = await store.transition_work_item(item.id, "in_progress")
        assert result is not None
        assert result.status == "in_progress"

    @pytest.mark.asyncio
    async def test_blocked_to_in_progress_keeps_existing_assignment(self, store):
        """BF-608: the AD-855 capability-gap resume (``blocked -> in_progress``,
        which is NOT assignment-gated) still works for an item that already has
        an owner — the resume path is not broken for properly-assigned items.
        """
        item = await store.create_work_item(
            title="Resumable", work_type="task", assigned_to="agent-1",
        )
        await store.transition_work_item(item.id, "in_progress")
        await store.transition_work_item(item.id, "blocked")
        resumed = await store.transition_work_item(
            item.id, "in_progress", source="capability_gap_driver",
        )
        assert resumed is not None
        assert resumed.status == "in_progress"
        assert resumed.assigned_to == "agent-1"

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
        # BF-608: in_progress requires an assignee (task open->in_progress).
        item = await store.create_work_item(title="Terminal item", assigned_to="agent-1")
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
        # BF-608: in_progress requires an assignee (task open->in_progress).
        item = await store.create_work_item(title="Transition emit", assigned_to="agent-1")
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
            # BF-608: in_progress requires an assignee (task open->in_progress).
            item = await store.create_work_item(
                title="T", work_type="task", assigned_to="agent-1",
            )
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
            # BF-608: scheduled->in_progress requires an assignee (work_order).
            item = await store.create_work_item(
                title="WO", work_type="work_order", assigned_to="agent-1",
            )
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

    @pytest.mark.asyncio
    async def test_transition_requires_assignment_helper(self, tmp_path):
        """BF-608: the registry exposes AD-498's per-edge ``requires_assignment``
        flag so the store can enforce it where ``assigned_to`` is available.
        """
        store = WorkItemStore(db_path=str(tmp_path / "test.db"))
        await store.start()
        try:
            reg = store.work_type_registry
            # task open->in_progress is assignment-gated; its other edges are not.
            assert reg.transition_requires_assignment("task", "open", "in_progress") is True
            assert reg.transition_requires_assignment("task", "in_progress", "done") is False
            assert reg.transition_requires_assignment("task", "blocked", "in_progress") is False
            # work_order scheduled->in_progress is also gated.
            assert reg.transition_requires_assignment(
                "work_order", "scheduled", "in_progress"
            ) is True
            # Unknown type / unknown edge -> permissive False.
            assert reg.transition_requires_assignment("mystery", "open", "in_progress") is False
            assert reg.transition_requires_assignment("task", "open", "review") is False
        finally:
            await store.stop()

