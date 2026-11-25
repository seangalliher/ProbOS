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
from probos.workforce import WorkItemStore
from probos.ws_event_stream import MAX_FRAME_BYTES, WSEventStreamHub
from tests.test_ad1133_live_crew_session_refresh import _FakeWebSocket, _Runtime, _wait_until

OVERSIZED = "x" * (MAX_FRAME_BYTES + 1)


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
