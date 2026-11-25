"""BF-997 (#1414 items 11 and 12): the HXI event stream past 100 work items, and dropped work-state frames.

Item 11: past the 100-row cap the WebSocket snapshot carries the first 100 rows in the
store's order instead of ending the socket with 1013. Item 12: a dropped work-item frame,
or a dropped crew-session projection, that names its row requests the existing resync
marker; a drop that names no row keeps the silent drop. Real WorkItemStore and the real
WSEventStreamHub on the AD-1133 test websocket.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.workforce import AgentCalendar, BookableResource, CalendarEntry, WorkItemStore
from probos.ws_event_stream import MAX_FRAME_BYTES, WSEventStreamHub
from tests.test_ad1133_live_crew_session_refresh import _FakeWebSocket, _Runtime, _wait_until

OVERSIZED = "x" * (MAX_FRAME_BYTES + 1)
# A work-item record the wire refuses, with the keys the ingress shape check reads.
OVERSIZED_ROW = {"id": "row-1", "work_type": "task", "status": "open", "description": OVERSIZED}


class _CollidingKey:
    """A dict key that hashes like ``name`` and counts, then refuses, every comparison."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.compared = 0

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        self.compared += 1
        raise AssertionError("a foreign key object was compared")


class _CollidingStr(str):
    """A ``str`` subclass key, hashing as its value, that counts, then refuses, every comparison."""

    compared = 0
    __hash__ = str.__hash__

    def __eq__(self, other: object) -> bool:
        self.compared += 1
        raise AssertionError("a foreign key object was compared")


@pytest.fixture
async def wired(tmp_path: Path) -> AsyncIterator[tuple[_Runtime, WorkItemStore]]:
    """A runtime whose real WorkItemStore emits its post-commit events to the runtime's listeners."""
    runtime = _Runtime(tmp_path)
    store = WorkItemStore(
        db_path=str(tmp_path / "work.db"),
        emit_event=runtime.emit,
        connection_factory=SQLiteConnectionFactory(),
        tick_interval=1_000,
    )
    await store.start()
    runtime.work_item_store = store
    try:
        yield runtime, store
    finally:
        await store.stop()


async def _serve(runtime: _Runtime) -> tuple[WSEventStreamHub, _FakeWebSocket, asyncio.Task[None]]:
    hub = WSEventStreamHub(runtime)
    await hub.start()
    runtime.add_event_listener(hub.ingress)
    socket = _FakeWebSocket()
    connection = asyncio.create_task(hub.serve(socket))
    return hub, socket, connection


async def _stop(hub: WSEventStreamHub, connection: asyncio.Task[None]) -> None:
    await hub.stop()
    await asyncio.gather(connection, return_exceptions=True)


async def test_a_snapshot_past_the_cap_carries_the_first_100_rows_and_the_socket_stays_live(
    wired: tuple[_Runtime, WorkItemStore],
) -> None:
    runtime, store = wired
    for index in range(101):
        await store.create_work_item(
            id=f"ordinary-{index:03d}",
            title="Ordinary",
            created_at=float(index),
            updated_at=float(index),
        )
    hub, socket, connection = await _serve(runtime)
    try:
        await _wait_until(lambda: bool(socket.sent) or socket.close_code is not None)
        # A/B: on the base the hub ended the socket with 1013 "snapshot unavailable" and sent nothing.
        assert socket.close_code is None
        snapshot = json.loads(socket.sent[0])
        assert snapshot["type"] == "state_snapshot"
        workforce = snapshot["data"]["workforce"]
        # The store orders by priority, then newest first: the oldest row is the one left out.
        assert [row["id"] for row in workforce["work_items"]] == [
            f"ordinary-{index:03d}" for index in range(100, 0, -1)
        ]
        # No new wire field: the HXI needs none (D1).
        assert set(workforce) == {"work_items", "bookings", "resources"}
        runtime.emit("system_mode", {"mode": "active"})
        await _wait_until(lambda: len(socket.sent) == 2)
        delivered = json.loads(socket.sent[1])
        assert delivered["type"] == "system_mode"
        assert delivered["stream"] == {"generation": hub.generation, "sequence": 1}
        assert socket.close_code is None
    finally:
        await _stop(hub, connection)


async def test_a_dropped_work_item_frame_requests_the_resync_marker(
    wired: tuple[_Runtime, WorkItemStore],
) -> None:
    runtime, store = wired
    hub, socket, connection = await _serve(runtime)
    try:
        await _wait_until(lambda: len(socket.sent) == 1)
        # The real store commits the row, then emits work_item_created past the 256 KiB frame bound.
        await store.create_work_item(id="oversized", title="Oversized", description=OVERSIZED)
        runtime.emit("system_mode", {"mode": "active"})
        await _wait_until(lambda: len(socket.sent) >= 2)
        # A/B: on the base the frame was dropped silently and system_mode arrived here as sequence 1.
        marker = json.loads(socket.sent[1])
        assert marker["type"] == "resync_required" and marker["data"] == {}
        assert marker["stream"] == {"generation": hub.generation, "sequence": 1}
        await _wait_until(lambda: len(socket.sent) == 3)
        following = json.loads(socket.sent[2])
        assert following["type"] == "system_mode"
        assert following["stream"]["sequence"] == 2
        assert await store.get_work_item("oversized") is not None
    finally:
        await _stop(hub, connection)


async def test_a_dropped_crew_session_projection_requests_the_resync_marker(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    hub, socket, connection = await _serve(runtime)
    try:
        await _wait_until(lambda: len(socket.sent) == 1)
        # The projector publishes through the callback the hub gave it; this is that path.
        publish = hub._projector._publish
        assert publish == hub._publish_projector
        publish(
            "crew_session_projection",
            {"parent_id": "parent", "thread_id": "room", "goal": OVERSIZED},
            hub.generation,
        )
        runtime.emit("system_mode", {"mode": "active"})
        await _wait_until(lambda: len(socket.sent) >= 2)
        # A/B: on the base the projection was dropped silently and system_mode arrived here.
        marker = json.loads(socket.sent[1])
        assert marker["type"] == "resync_required" and marker["data"] == {}
        assert marker["stream"]["sequence"] == 1
        await _wait_until(lambda: len(socket.sent) == 3)
        assert json.loads(socket.sent[2])["stream"]["sequence"] == 2
    finally:
        await _stop(hub, connection)


@pytest.mark.parametrize("event", [
    pytest.param(
        {"type": "work_item_updated", "data": {"work_item": {}, "blob": OVERSIZED}},
        id="work-item-frame-naming-no-row",
    ),
    pytest.param(
        {"type": "game_update", "data": {"blob": OVERSIZED}},
        id="other-family-oversized",
    ),
])
async def test_a_drop_that_names_no_work_row_keeps_the_silent_drop(
    tmp_path: Path,
    event: dict[str, Any],
) -> None:
    runtime = _Runtime(tmp_path)
    hub, socket, connection = await _serve(runtime)
    try:
        await _wait_until(lambda: len(socket.sent) == 1)
        hub.ingress({**event, "timestamp": 1.0})
        hub.ingress({"type": "system_mode", "data": {"mode": "active"}, "timestamp": 2.0})
        await _wait_until(lambda: len(socket.sent) == 2)
        assert json.loads(socket.sent[1])["type"] == "system_mode"
        assert hub.sequence == 1
    finally:
        await _stop(hub, connection)


@pytest.mark.parametrize("event", [
    pytest.param(
        {"type": "work_item_created", "data": {"work_item": OVERSIZED_ROW}},
        id="created",
    ),
    pytest.param(
        {"type": "work_item_updated", "data": {"work_item": OVERSIZED_ROW}},
        id="updated",
    ),
    pytest.param(
        {"type": "work_item_status_changed", "data": {
            "work_item": OVERSIZED_ROW,
            "old_status": "draft",
            "new_status": "open",
        }},
        id="status-changed",
    ),
    pytest.param(
        {"type": "work_item_assigned", "data": {
            "work_item": OVERSIZED_ROW,
            "booking": {"id": "booking-1"},
            "resource": {"resource_id": "agent-1"},
        }},
        id="assigned-with-booking",
    ),
    pytest.param(
        {"type": "work_item_assigned", "data": {"work_item": OVERSIZED_ROW, "source": "captain"}},
        id="assigned-from-command",
    ),
    pytest.param(
        {"type": "work_item_claimed", "data": {
            "work_item": OVERSIZED_ROW,
            "booking": {"id": "booking-1"},
            "resource": {"resource_id": "agent-1"},
        }},
        id="claimed",
    ),
])
async def test_a_dropped_work_item_frame_of_each_invalidating_type_requests_the_resync_marker(
    tmp_path: Path,
    event: dict[str, Any],
) -> None:
    # The five work-item events the HXI invalidates on (useStore.ts, invalidateWorkItemFrame),
    # each in its producer's shape: created, updated and status_changed carry the projection;
    # assigned carries the record with a booking and a resource, or with its source; claimed
    # carries the record with a booking and a resource (workforce.py).
    runtime = _Runtime(tmp_path)
    hub, socket, connection = await _serve(runtime)
    try:
        await _wait_until(lambda: len(socket.sent) == 1)
        hub.ingress({**event, "timestamp": 1.0})
        hub.ingress({"type": "system_mode", "data": {"mode": "active"}, "timestamp": 2.0})
        await _wait_until(lambda: len(socket.sent) >= 2)
        # A/B: on 850a1a35 the assigned and claimed frames were dropped silently and
        # system_mode arrived here as sequence 1.
        marker = json.loads(socket.sent[1])
        assert marker["type"] == "resync_required" and marker["data"] == {}
        assert marker["stream"] == {"generation": hub.generation, "sequence": 1}
        await _wait_until(lambda: len(socket.sent) == 3)
        following = json.loads(socket.sent[2])
        assert following["type"] == "system_mode"
        assert following["stream"]["sequence"] == 2
    finally:
        await _stop(hub, connection)


async def test_a_dropped_assignment_requests_the_resync_marker_through_the_real_store(
    wired: tuple[_Runtime, WorkItemStore],
) -> None:
    runtime, store = wired
    store.register_resource(
        BookableResource(
            resource_id="assign-agent",
            resource_type="crew",
            agent_type="builder",
            callsign="Builder",
            capacity=1,
            department="engineering",
            active=True,
        )
    )
    store.register_calendar(AgentCalendar(resource_id="assign-agent", entries=[CalendarEntry()]))
    hub, socket, connection = await _serve(runtime)
    try:
        await _wait_until(lambda: len(socket.sent) == 1)
        # The created frame is refused first; its marker is delivered before the assignment.
        await store.create_work_item(id="oversized", title="Oversized", description=OVERSIZED)
        await _wait_until(lambda: len(socket.sent) == 2)
        assert json.loads(socket.sent[1])["type"] == "resync_required"
        # assign_work_item emits only work_item_assigned, carrying the full record
        # (workforce.py, _publish_assignment), so the next marker can come only from it.
        assert await store.assign_work_item("oversized", "assign-agent") is not None
        runtime.emit("system_mode", {"mode": "active"})
        await _wait_until(lambda: len(socket.sent) >= 3)
        # A/B: on 850a1a35 the assignment was dropped silently and system_mode arrived here.
        marker = json.loads(socket.sent[2])
        assert marker["type"] == "resync_required" and marker["data"] == {}
        assert marker["stream"] == {"generation": hub.generation, "sequence": 2}
        await _wait_until(lambda: len(socket.sent) == 4)
        following = json.loads(socket.sent[3])
        assert following["type"] == "system_mode"
        assert following["stream"]["sequence"] == 3
    finally:
        await _stop(hub, connection)


async def test_an_assignment_frame_naming_no_row_is_still_delivered(
    tmp_path: Path,
) -> None:
    # The resync set is separate from _WORK_ITEM_EVENTS, which also drives the ingress shape
    # check. The store's fallback assigned payload carries an empty record (workforce.py,
    # "updated.to_dict() if updated else {}"); it is delivered as before, not refused.
    runtime = _Runtime(tmp_path)
    hub, socket, connection = await _serve(runtime)
    try:
        await _wait_until(lambda: len(socket.sent) == 1)
        hub.ingress({
            "type": "work_item_assigned",
            "data": {"work_item": {}, "source": "captain"},
            "timestamp": 1.0,
        })
        hub.ingress({"type": "system_mode", "data": {"mode": "active"}, "timestamp": 2.0})
        await _wait_until(lambda: len(socket.sent) >= 2)
        delivered = json.loads(socket.sent[1])
        assert delivered["type"] == "work_item_assigned"
        assert delivered["data"] == {"work_item": {}, "source": "captain"}
        assert delivered["stream"]["sequence"] == 1
        await _wait_until(lambda: len(socket.sent) == 3)
        assert json.loads(socket.sent[2])["type"] == "system_mode"
    finally:
        await _stop(hub, connection)


@pytest.mark.parametrize("case", [
    "work-item-data-key",
    "work-item-record-key",
    "work-item-str-subclass-key",
    "tool-event-data-key",
    "projection-data-key",
])
async def test_a_refused_frame_with_a_foreign_key_object_keeps_the_silent_drop(
    tmp_path: Path,
    case: str,
) -> None:
    # The drop classifier reads the raw data the wire detacher refused. A key object that
    # hashes like a name the classifier looks up must never be compared: the frame takes
    # the silent drop. The tool-event row already raised on fc57a8b2.
    key: _CollidingKey | _CollidingStr
    if case == "work-item-str-subclass-key":
        key = _CollidingStr("work_item")
    else:
        key = _CollidingKey({
            "work-item-data-key": "work_item",
            "work-item-record-key": "id",
            "tool-event-data-key": "run_id",
            "projection-data-key": "parent_id",
        }[case])
    runtime = _Runtime(tmp_path)
    hub, socket, connection = await _serve(runtime)
    try:
        await _wait_until(lambda: len(socket.sent) == 1)
        data: dict[Any, Any]
        # A/B: on 850a1a35 the comparison raised out of the hub in every row.
        if case == "projection-data-key":
            data = {key: "parent"}
            hub._projector._publish("crew_session_projection", data, hub.generation)
        else:
            if case == "work-item-record-key":
                event_type, data = "work_item_updated", {"work_item": {key: "row-1"}}
            elif case == "tool-event-data-key":
                event_type, data = "agentic_tool_call_started", {key: "run"}
            else:
                event_type, data = "work_item_updated", {key: {"id": "row-1"}}
            hub.ingress({"type": event_type, "data": data, "timestamp": 1.0})
        hub.ingress({"type": "system_mode", "data": {"mode": "active"}, "timestamp": 2.0})
        await _wait_until(lambda: len(socket.sent) == 2)
        assert key.compared == 0
        assert json.loads(socket.sent[1])["type"] == "system_mode"
        assert hub.sequence == 1
    finally:
        await _stop(hub, connection)
