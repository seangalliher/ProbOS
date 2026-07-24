"""Bounded owner for the existing HXI ``/ws/events`` stream."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import math
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from probos.crew_session_live import CrewSessionLiveProjector
from probos.events import EventType
from probos.routers.workforce import build_ws_workforce_snapshot

logger = logging.getLogger(__name__)

MAX_CLIENTS = 16
MAX_CLIENT_FRAMES = 32
MAX_CLIENT_BYTES = 2 * 1024 * 1024
MAX_INGRESS_ITEMS = 256
MAX_INGRESS_BYTES = 8 * 1024 * 1024
SEND_TIMEOUT_SECONDS = 5.0
MAX_FRAME_BYTES = 256 * 1024
MAX_SNAPSHOT_BYTES = 1024 * 1024
MAX_FRAME_NODES = 20_000
MAX_SNAPSHOT_NODES = 80_000
MAX_DEPTH = 24
MAX_CONTAINER_ITEMS = 4_096
MAX_STRING_CHARS = 65_536
MAX_STRING_BYTES = 256 * 1024
MAX_KEY_CHARS = 256
MAX_WORKFORCE_ITEMS = 100

_IDS_ONLY_EVENT_KEYS = {
    "chat_thread_message_appended": {
        "thread_id",
        "message_id",
        "author_id",
        "role",
        "created_at",
    },
    "artifact_version_added": {
        "thread_id",
        "artifact_id",
        "version",
        "created_at",
    },
}
_WORK_ITEM_EVENTS = {
    "work_item_created",
    "work_item_updated",
    "work_item_status_changed",
}


class WireValueError(ValueError):
    pass


@dataclass(slots=True)
class _DetachBudget:
    remaining_nodes: int


def _bounded_string(value: object, *, key: bool = False) -> str:
    if type(value) is not str:
        raise WireValueError("wire_string_invalid")
    char_limit = MAX_KEY_CHARS if key else MAX_STRING_CHARS
    if len(value) > char_limit:
        raise WireValueError("wire_string_too_long")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise WireValueError("wire_string_invalid") from exc
    byte_limit = MAX_KEY_CHARS * 4 if key else MAX_STRING_BYTES
    if len(encoded) > byte_limit:
        raise WireValueError("wire_string_too_long")
    return value


def detach_json_value(
    value: object,
    *,
    snapshot: bool = False,
) -> object:
    """Detach only exact JSON built-ins and trusted ProbOS enums/dataclasses."""
    budget = _DetachBudget(
        remaining_nodes=MAX_SNAPSHOT_NODES if snapshot else MAX_FRAME_NODES,
    )

    def _detach(candidate: object, depth: int) -> object:
        if depth > MAX_DEPTH or budget.remaining_nodes <= 0:
            raise WireValueError("wire_budget_exceeded")
        budget.remaining_nodes -= 1
        candidate_type = type(candidate)
        if candidate is None or candidate_type is bool:
            return candidate
        if candidate_type is int:
            if not -(2**63) <= candidate <= 2**63 - 1:
                raise WireValueError("wire_integer_invalid")
            return candidate
        if candidate_type is float:
            if not math.isfinite(candidate):
                raise WireValueError("wire_float_invalid")
            return candidate
        if candidate_type is str:
            return _bounded_string(candidate)
        if candidate_type is list:
            if len(candidate) > MAX_CONTAINER_ITEMS:
                raise WireValueError("wire_container_too_large")
            return [_detach(item, depth + 1) for item in candidate]
        if candidate_type is dict:
            if len(candidate) > MAX_CONTAINER_ITEMS:
                raise WireValueError("wire_container_too_large")
            detached: dict[str, object] = {}
            for raw_key, item in candidate.items():
                key_value = _bounded_string(raw_key, key=True)
                detached[key_value] = _detach(item, depth + 1)
            return detached
        if Enum in candidate_type.__mro__ and candidate_type.__module__.startswith("probos."):
            return _detach(candidate.value, depth + 1)
        if (
            dataclasses.is_dataclass(candidate_type)
            and type not in candidate_type.__mro__
            and candidate_type.__module__.startswith("probos.")
        ):
            declared = dataclasses.fields(candidate_type)
            if len(declared) > MAX_CONTAINER_ITEMS:
                raise WireValueError("wire_container_too_large")
            return {
                _bounded_string(field.name, key=True): _detach(
                    getattr(candidate, field.name),
                    depth + 1,
                )
                for field in declared
            }
        raise WireValueError("wire_value_unsupported")

    return _detach(value, 0)


def _json_text(value: object, *, max_bytes: int) -> tuple[str, int]:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        encoded = payload.encode("utf-8", errors="strict")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise WireValueError("wire_json_invalid") from exc
    if len(encoded) > max_bytes:
        raise WireValueError("wire_json_too_large")
    return payload, len(encoded)


@dataclass(frozen=True, slots=True)
class _QueuedFrame:
    payload: str
    size_bytes: int
    control: str | None = None


def _finalize_frame(
    *,
    event_type: str,
    data: object,
    timestamp: float,
    generation: str,
    sequence: int,
    snapshot: bool = False,
    control: str | None = None,
) -> _QueuedFrame:
    if (
        not event_type
        or len(event_type) > 128
        or type(timestamp) not in {int, float}
        or not math.isfinite(float(timestamp))
        or float(timestamp) < 0
        or type(generation) is not str
        or len(generation) != 32
        or any(char not in "0123456789abcdef" for char in generation)
        or type(sequence) is not int
        or sequence < 0
    ):
        raise WireValueError("wire_frame_invalid")
    detached = detach_json_value(data, snapshot=snapshot)
    if type(detached) is not dict:
        raise WireValueError("wire_frame_data_invalid")
    frame = {
        "type": event_type,
        "data": detached,
        "timestamp": float(timestamp),
        "stream": {
            "generation": generation,
            "sequence": sequence,
        },
    }
    payload, size = _json_text(
        frame,
        max_bytes=MAX_SNAPSHOT_BYTES if snapshot else MAX_FRAME_BYTES,
    )
    return _QueuedFrame(payload=payload, size_bytes=size, control=control)


def _finalize_ping() -> _QueuedFrame:
    payload, size = _json_text(
        {"type": "ping", "timestamp": time.time()},
        max_bytes=MAX_FRAME_BYTES,
    )
    return _QueuedFrame(payload=payload, size_bytes=size, control="ping")


async def build_ws_state_snapshot(runtime: Any) -> dict[str, object]:
    """Build the source-bounded, Crew-safe initial WebSocket snapshot."""
    snapshot = dict(runtime.build_bounded_hxi_snapshot_base())
    workforce = await build_ws_workforce_snapshot(
        runtime,
        limit=MAX_WORKFORCE_ITEMS,
    )
    snapshot["workforce"] = workforce
    return snapshot


@dataclass(frozen=True, slots=True)
class _IngressItem:
    event_type: str
    data: dict[str, object]
    timestamp: float
    trigger: dict[str, object] | None
    size_bytes: int


@dataclass(slots=True)
class _ClientState:
    websocket: WebSocket
    queue: deque[_QueuedFrame]
    queued_bytes: int
    wake: asyncio.Event
    sender_task: asyncio.Task[None] | None = None
    resync_pending: bool = False
    close_code: int | None = None


class WSEventStreamHub:
    """Sole ordered runtime-listener and bounded client fanout owner."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self.generation = uuid.uuid4().hex
        self._sequence = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ingress_lock = threading.Lock()
        self._ingress: deque[_IngressItem] = deque()
        self._ingress_bytes = 0
        self._global_resync_requested = False
        self._wake = asyncio.Event()
        self._dispatcher_task: asyncio.Task[None] | None = None
        self._clients: dict[int, _ClientState] = {}
        self._admission_open = False
        self._projector = CrewSessionLiveProjector(
            crew_session_service=getattr(runtime, "crew_session_service", None),
            work_item_store=getattr(runtime, "work_item_store", None),
            chat_thread_store=getattr(runtime, "chat_thread_store", None),
            artifact_store=getattr(runtime, "artifact_store", None),
            publish=self._publish_projector,
            request_resync=self.request_resync,
        )

    @property
    def sequence(self) -> int:
        return self._sequence

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def start(self) -> None:
        if self._dispatcher_task is not None:
            raise RuntimeError("ws_event_hub_already_started")
        self._loop = asyncio.get_running_loop()
        self._admission_open = True
        self._dispatcher_task = asyncio.create_task(
            self._dispatch(),
            name="ws-event-dispatcher",
        )
        try:
            self._projector.start(self.generation)
        except BaseException:
            self.close_admission()
            self._dispatcher_task.cancel()
            await asyncio.gather(self._dispatcher_task, return_exceptions=True)
            self._dispatcher_task = None
            raise

    def close_admission(self) -> None:
        with self._ingress_lock:
            self._admission_open = False

    def _signal(self) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            if asyncio.get_running_loop() is loop:
                self._wake.set()
                return
        except RuntimeError:
            pass
        loop.call_soon_threadsafe(self._wake.set)

    def request_resync(self) -> None:
        should_signal = False
        with self._ingress_lock:
            if self._admission_open and not self._global_resync_requested:
                self._global_resync_requested = True
                should_signal = True
        if should_signal:
            self._signal()

    def ingress(self, event: dict[str, Any]) -> None:
        if not self._admission_open:
            return
        try:
            item = self._prepare_ingress(event)
        except WireValueError:
            raw_event_type = event.get("type") if type(event) is dict else None
            if type(raw_event_type) is EventType:
                event_name = raw_event_type.value
            elif type(raw_event_type) is str and len(raw_event_type) <= 128:
                event_name = raw_event_type
            else:
                event_name = "invalid"
            logger.warning(
                "Dropped runtime event type %s because bounded wire "
                "finalization failed; clients retain their prior state",
                event_name,
            )
            return
        should_signal = False
        with self._ingress_lock:
            if not self._admission_open:
                return
            if (
                len(self._ingress) >= MAX_INGRESS_ITEMS
                or self._ingress_bytes + item.size_bytes > MAX_INGRESS_BYTES
            ):
                if not self._global_resync_requested:
                    self._global_resync_requested = True
                    should_signal = True
            else:
                self._ingress.append(item)
                self._ingress_bytes += item.size_bytes
                should_signal = True
        if should_signal:
            self._signal()

    def _prepare_ingress(self, event: dict[str, Any]) -> _IngressItem:
        if type(event) is not dict:
            raise WireValueError("runtime_event_invalid")
        raw_event_type = event.get("type")
        if type(raw_event_type) is EventType:
            raw_event_type = raw_event_type.value
        event_type = _bounded_string(raw_event_type)
        if not event_type or len(event_type) > 128:
            raise WireValueError("runtime_event_invalid")
        timestamp = event.get("timestamp", time.time())
        if (
            type(timestamp) not in {int, float}
            or not math.isfinite(float(timestamp))
            or float(timestamp) < 0
        ):
            raise WireValueError("runtime_event_invalid")
        detached = detach_json_value(event.get("data"))
        if type(detached) is not dict:
            raise WireValueError("runtime_event_invalid")
        data = detached
        expected_keys = _IDS_ONLY_EVENT_KEYS.get(event_type)
        if expected_keys is not None:
            if set(data) != expected_keys:
                raise WireValueError("runtime_event_private_fields")
            if event_type == "chat_thread_message_appended":
                if data["role"] not in {"captain", "agent", "system"}:
                    raise WireValueError("runtime_event_invalid")
                for key in ("thread_id", "message_id", "author_id"):
                    value = data[key]
                    if type(value) is not str or not value or len(value) > 128:
                        raise WireValueError("runtime_event_invalid")
            else:
                for key in ("thread_id", "artifact_id"):
                    value = data[key]
                    if type(value) is not str or not value or len(value) > 128:
                        raise WireValueError("runtime_event_invalid")
                if type(data["version"]) is not int or data["version"] <= 0:
                    raise WireValueError("runtime_event_invalid")
            created_at = data["created_at"]
            if (
                type(created_at) not in {int, float}
                or not math.isfinite(float(created_at))
                or float(created_at) < 0
            ):
                raise WireValueError("runtime_event_invalid")

        trigger = None
        if event_type in _WORK_ITEM_EVENTS:
            raw_work_item = data.get("work_item")
            if type(raw_work_item) is not dict:
                raise WireValueError("runtime_event_invalid")
            trigger = {}
            for key in ("id", "work_type", "status"):
                value = raw_work_item.get(key)
                if type(value) is not str or not value or len(value) > 128:
                    raise WireValueError("runtime_event_invalid")
                trigger[key] = value
            parent_id = raw_work_item.get("parent_id")
            if parent_id is not None and (
                type(parent_id) is not str
                or not parent_id
                or len(parent_id) > 128
            ):
                raise WireValueError("runtime_event_invalid")
            trigger["parent_id"] = parent_id

        canonical = {
            "type": event_type,
            "data": data,
            "timestamp": float(timestamp),
        }
        _payload, size = _json_text(canonical, max_bytes=MAX_FRAME_BYTES)
        return _IngressItem(
            event_type=event_type,
            data=data,
            timestamp=float(timestamp),
            trigger=trigger,
            size_bytes=size,
        )

    async def _dispatch(self) -> None:
        try:
            while True:
                await self._wake.wait()
                while True:
                    item: _IngressItem | None = None
                    resync = False
                    with self._ingress_lock:
                        if not self._admission_open and not self._ingress:
                            return
                        if self._global_resync_requested:
                            self._global_resync_requested = False
                            resync = True
                        elif self._ingress:
                            item = self._ingress.popleft()
                            self._ingress_bytes -= item.size_bytes
                        else:
                            self._wake.clear()
                    if resync:
                        self._publish_resync_all()
                        continue
                    if item is None:
                        break
                    try:
                        disposition = await self._projector.route_event(
                            item.event_type,
                            item.data,
                            item.trigger,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning(
                            "WebSocket route for event type %s failed with %s; "
                            "one authoritative resync is queued and dispatch continues",
                            item.event_type,
                            type(exc).__name__[:128],
                        )
                        self.request_resync()
                        continue
                    if not self._admission_open:
                        return
                    if disposition == "publish":
                        self._publish_delta(
                            item.event_type,
                            item.data,
                            item.timestamp,
                        )
        except asyncio.CancelledError:
            raise

    def _publish_projector(
        self,
        event_type: str,
        data: dict[str, object],
        generation: str,
    ) -> None:
        if generation != self.generation or not self._admission_open:
            return
        self._publish_delta(event_type, data, time.time())

    def _publish_delta(
        self,
        event_type: str,
        data: dict[str, object],
        timestamp: float,
    ) -> None:
        next_sequence = self._sequence + 1
        try:
            frame = _finalize_frame(
                event_type=event_type,
                data=data,
                timestamp=timestamp,
                generation=self.generation,
                sequence=next_sequence,
            )
        except WireValueError:
            logger.warning(
                "Dropped runtime event type %s because its final bounded "
                "envelope was invalid; clients retain their prior state",
                event_type if len(event_type) <= 128 else "invalid",
            )
            return
        self._sequence = next_sequence
        for client in tuple(self._clients.values()):
            self._enqueue_delta(client, frame)

    def _resync_frame(self, *, sequence: int | None = None) -> _QueuedFrame:
        return _finalize_frame(
            event_type="resync_required",
            data={},
            timestamp=time.time(),
            generation=self.generation,
            sequence=self._sequence if sequence is None else sequence,
            control="resync_required",
        )

    def _publish_resync_all(self) -> None:
        next_sequence = self._sequence + 1
        try:
            marker = self._resync_frame(sequence=next_sequence)
        except WireValueError:
            for client in tuple(self._clients.values()):
                self._request_client_close(client, 1013)
            return
        self._sequence = next_sequence
        for client in tuple(self._clients.values()):
            if client.resync_pending:
                continue
            self._discard_pending_deltas(client)
            if not self._frame_fits(client, marker):
                self._request_client_close(client, 1013)
                continue
            client.queue.append(marker)
            client.queued_bytes += marker.size_bytes
            client.resync_pending = True
            client.wake.set()

    @staticmethod
    def _frame_fits(client: _ClientState, frame: _QueuedFrame) -> bool:
        return (
            len(client.queue) < MAX_CLIENT_FRAMES
            and client.queued_bytes + frame.size_bytes <= MAX_CLIENT_BYTES
        )

    @staticmethod
    def _discard_pending_deltas(client: _ClientState) -> None:
        retained = deque(frame for frame in client.queue if frame.control is not None)
        client.queue = retained
        client.queued_bytes = sum(frame.size_bytes for frame in retained)

    def _enqueue_delta(self, client: _ClientState, frame: _QueuedFrame) -> None:
        if client.close_code is not None:
            return
        if self._frame_fits(client, frame):
            client.queue.append(frame)
            client.queued_bytes += frame.size_bytes
            client.wake.set()
            return
        if client.resync_pending:
            self._request_client_close(client, 1013)
            return
        self._discard_pending_deltas(client)
        marker = self._resync_frame()
        if not self._frame_fits(client, marker):
            self._request_client_close(client, 1013)
            return
        client.queue.append(marker)
        client.queued_bytes += marker.size_bytes
        client.resync_pending = True
        client.wake.set()

    @staticmethod
    def _request_client_close(client: _ClientState, code: int) -> None:
        if client.close_code is None:
            client.close_code = code
            client.wake.set()

    async def serve(self, websocket: WebSocket) -> None:
        if not self._admission_open or len(self._clients) >= MAX_CLIENTS:
            await websocket.accept()
            await websocket.close(code=1013, reason="event stream capacity")
            return
        try:
            snapshot = await build_ws_state_snapshot(self._runtime)
            snapshot_frame = _finalize_frame(
                event_type="state_snapshot",
                data=snapshot,
                timestamp=time.time(),
                generation=self.generation,
                sequence=self._sequence,
                snapshot=True,
                control="state_snapshot",
            )
        except Exception:
            logger.warning(
                "WebSocket state snapshot failed bounded finalization; the "
                "client is closed for retry without a partial snapshot",
                exc_info=True,
            )
            await websocket.accept()
            await websocket.close(code=1013, reason="snapshot unavailable")
            return

        if not self._admission_open or len(self._clients) >= MAX_CLIENTS:
            await websocket.accept()
            await websocket.close(code=1013, reason="event stream capacity")
            return

        client = _ClientState(
            websocket=websocket,
            queue=deque([snapshot_frame]),
            queued_bytes=snapshot_frame.size_bytes,
            wake=asyncio.Event(),
        )
        client.wake.set()
        key = id(websocket)
        self._clients[key] = client
        try:
            await websocket.accept()
            if not self._admission_open:
                self._request_client_close(client, 1001)
            client.sender_task = asyncio.create_task(
                self._send_client(key, client),
                name=f"ws-event-sender:{key}",
            )
            while self._admission_open and client.close_code is None:
                try:
                    await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    if not client.queue:
                        ping = _finalize_ping()
                        if self._frame_fits(client, ping):
                            client.queue.append(ping)
                            client.queued_bytes += ping.size_bytes
                            client.wake.set()
                except WebSocketDisconnect:
                    break
        finally:
            await self._disconnect_client(key, client)

    async def _send_client(self, key: int, client: _ClientState) -> None:
        try:
            while True:
                await client.wake.wait()
                if client.close_code is not None:
                    try:
                        await client.websocket.close(code=client.close_code)
                    except Exception:
                        pass
                    return
                while client.queue:
                    frame = client.queue.popleft()
                    client.queued_bytes -= frame.size_bytes
                    try:
                        await asyncio.wait_for(
                            client.websocket.send_text(frame.payload),
                            timeout=SEND_TIMEOUT_SECONDS,
                        )
                    except Exception:
                        self._request_client_close(client, 1013)
                        break
                    if frame.control == "resync_required":
                        client.resync_pending = False
                if client.close_code is None:
                    client.wake.clear()
        except asyncio.CancelledError:
            raise
        finally:
            self._clients.pop(key, None)

    async def _disconnect_client(
        self,
        key: int,
        client: _ClientState,
    ) -> None:
        self._clients.pop(key, None)
        task = client.sender_task
        client.sender_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def stop(self) -> None:
        self.close_admission()
        self._projector.invalidate()
        dispatcher = self._dispatcher_task
        self._dispatcher_task = None
        if dispatcher is not None:
            dispatcher.cancel()
            await asyncio.gather(dispatcher, return_exceptions=True)
        await self._projector.stop()
        clients = tuple(self._clients.values())
        if clients:
            await asyncio.gather(
                *(
                    client.websocket.close(code=1001, reason="application shutdown")
                    for client in clients
                ),
                return_exceptions=True,
            )
        sender_tasks = tuple(
            client.sender_task
            for client in clients
            if client.sender_task is not None
        )
        for task in sender_tasks:
            task.cancel()
        if sender_tasks:
            await asyncio.gather(*sender_tasks, return_exceptions=True)
        self._clients.clear()
        with self._ingress_lock:
            self._ingress.clear()
            self._ingress_bytes = 0
            self._global_resync_requested = False