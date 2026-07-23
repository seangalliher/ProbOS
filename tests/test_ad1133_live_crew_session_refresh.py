"""AD-1133: live CrewSession/thread refresh over the bounded existing stream."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from probos.api import create_app
from probos.artifacts import ArtifactStore
from probos.cognitive.crew_executor import CrewTaskExecutor
from probos.cognitive.crew_session import CrewSessionContract
from probos.config import AuthConfig, SystemConfig, format_trust
from probos.crew_profile import Rank
from probos.earned_agency import agency_from_rank
from probos.events import EventType
from probos.mesh.nats_bus import MockNATSBus, NATSBus
from probos.routers.workforce import build_ws_workforce_snapshot
from probos.runtime import ProbOSRuntime
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.substrate.pool_group import PoolGroup, PoolGroupRegistry
from probos.threads import ChatThreadStore
from probos.workforce import CrewSessionParentCreate, WorkItem, WorkItemStore
from probos.ws_event_stream import (
    MAX_CLIENT_BYTES,
    MAX_CLIENT_FRAMES,
    MAX_INGRESS_ITEMS,
    WireValueError,
    WSEventStreamHub,
    build_ws_state_snapshot,
    detach_json_value,
)


class _Registry:
    def __init__(self, agents: list[Any] | None = None) -> None:
        self._agents = list(agents or [])

    def all(self) -> list[Any]:
        return list(self._agents)

    @property
    def count(self) -> int:
        return len(self._agents)

    def get(self, _agent_id: str) -> None:
        return None


class _Trust:
    def __init__(self, score: float = 0.5) -> None:
        self.score = score

    def get_score(self, _agent_id: str) -> float:
        return self.score


class _Hebbian:
    def __init__(
        self,
        weights: dict[tuple[str, str, str], float] | None = None,
    ) -> None:
        self.weights = dict(weights or {})

    def all_weights_typed(self) -> dict[tuple[str, str, str], float]:
        return dict(self.weights)

    @property
    def weight_count(self) -> int:
        return len(self.weights)


class _Notifications:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self.rows)

    @property
    def count(self) -> int:
        return len(self.rows)

    def unread_count(self) -> int:
        return len(self.rows)


class _PoolGroups:
    def __init__(self) -> None:
        self._pool_to_group: dict[str, str] = {}

    def all_groups(self) -> list[Any]:
        return []

    @property
    def count(self) -> int:
        return 0

    @property
    def membership_count(self) -> int:
        return 0

    @property
    def pool_mapping_count(self) -> int:
        return len(self._pool_to_group)

    def pool_to_group_snapshot(self) -> dict[str, str]:
        return dict(self._pool_to_group)

    def get_group_for_pool(self, _pool_name: str) -> None:
        return None

    def group_health(self, _name: str, _pools: dict[str, Any]) -> dict[str, Any]:
        return {}


class _ProjectionService:
    def __init__(self) -> None:
        self.sessions: dict[str, CrewSessionContract] = {}
        self.started = asyncio.Event()
        self.release: asyncio.Event | None = None
        self.calls = 0

    async def get_session(self, parent_id: str) -> CrewSessionContract | None:
        self.calls += 1
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        return self.sessions.get(parent_id)


class _LocalLiveListenerHandle:
    def __init__(
        self,
        runtime: _Runtime,
        listener: Callable[[dict[str, Any]], None],
    ) -> None:
        self.runtime = runtime
        self.listener = listener
        self.stopped = False

    async def stop(self) -> None:
        if self.stopped:
            return
        self.stopped = True
        self.runtime.remove_event_listener(self.listener)


class _Runtime:
    def __init__(
        self,
        data_dir: Path,
        *,
        token: str = "",
        work_items: WorkItemStore | None = None,
        threads: ChatThreadStore | None = None,
        artifacts: ArtifactStore | None = None,
        service: _ProjectionService | None = None,
        agents: list[Any] | None = None,
    ) -> None:
        self.config = SystemConfig(auth=AuthConfig(crew_scope_token=token))
        self.registry = _Registry(agents)
        self.trust_network = _Trust()
        self.hebbian_router = _Hebbian()
        self.pools: dict[str, Any] = {}
        self.notification_queue = _Notifications()
        self.persistent_task_store = None
        self.pool_groups = _PoolGroups()
        self.work_item_store = work_items
        self.chat_thread_store = threads
        self.artifact_store = artifacts
        self.crew_session_service = service
        self.ontology = None
        self._data_dir = data_dir
        self.listeners: list[Callable[[dict[str, Any]], None]] = []
        self.added: list[Callable[[dict[str, Any]], None]] = []
        self.removed: list[Callable[[dict[str, Any]], None]] = []

    async def register_live_event_listener(
        self,
        listener: Callable[[dict[str, Any]], None],
        _event_types: Any = None,
    ) -> _LocalLiveListenerHandle:
        self.add_event_listener(listener)
        return _LocalLiveListenerHandle(self, listener)

    def add_event_listener(
        self,
        listener: Callable[[dict[str, Any]], None],
        _event_types: Any = None,
    ) -> None:
        self.listeners.append(listener)
        self.added.append(listener)

    def remove_event_listener(
        self,
        listener: Callable[[dict[str, Any]], None],
    ) -> None:
        self.listeners = [candidate for candidate in self.listeners if candidate is not listener]
        self.removed.append(listener)

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        event = {"type": event_type, "data": data, "timestamp": time.time()}
        for listener in tuple(self.listeners):
            listener(event)

    def build_bounded_hxi_snapshot_base(self) -> dict[str, Any]:
        agents = self.registry.all()
        if len(agents) > 1_000:
            raise ValueError("ws_snapshot_agents_overflow")
        return {
            "agents": [],
            "connections": [],
            "pools": [],
            "system_mode": "active",
            "tc_n": 0.0,
            "routing_entropy": 0.0,
            "fresh_boot": False,
            "temporal": {
                "current_time_utc": "2026-07-23T00:00:00+00:00",
                "uptime_seconds": 0.0,
                "lifecycle_state": "running",
                "stasis_duration": None,
                "session_id": "test-session",
            },
            "pool_groups": {},
            "pool_to_group": {},
            "directives": {"active": 0, "pending": 0},
            "notifications": [],
            "unread_count": 0,
            "scheduled_tasks": [],
            "ward_room_stats": None,
            "skill_framework": False,
            "acm": False,
        }


class _DrainableSubscription:
    def __init__(
        self,
        bus: _DrainableMockNATSBus,
        subject: str,
        callback: Callable[[Any], Any],
        *,
        fail_drain: bool,
    ) -> None:
        self.bus = bus
        self.subject = subject
        self.callback = callback
        self.fail_drain = fail_drain
        self.drain_calls = 0
        self.unsubscribe_calls = 0
        self.active = True

    async def drain(self) -> None:
        self.drain_calls += 1
        if self.fail_drain:
            raise RuntimeError("test drain failure")
        self.bus.remove_subscription(self)

    async def unsubscribe(self) -> None:
        self.unsubscribe_calls += 1
        self.bus.remove_subscription(self)


class _DrainableMockNATSBus(MockNATSBus):
    release_raw_subscription = NATSBus.release_raw_subscription
    _release_raw_subscription = NATSBus._release_raw_subscription
    _forget_raw_release_task = NATSBus._forget_raw_release_task

    def __init__(self) -> None:
        super().__init__(subject_prefix="probos.live-test")
        self.subscribe_started = asyncio.Event()
        self.subscribe_release = asyncio.Event()
        self.subscribe_release.set()
        self.fail_subscribe: BaseException | None = None
        self.fail_next_drain = False
        self.subscriptions: list[_DrainableSubscription] = []
        self._subscriptions: list[object] = []
        self._raw_subscription_release_tasks: list[
            tuple[object, asyncio.Task[bool]]
        ] = []

    async def subscribe_raw(
        self,
        subject: str,
        callback: Callable[[Any], Any],
        queue: str = "",
    ) -> _DrainableSubscription | None:
        del queue
        if not self.connected:
            return None
        self.subscribe_started.set()
        await self.subscribe_release.wait()
        if self.fail_subscribe is not None:
            raise self.fail_subscribe
        subscription = _DrainableSubscription(
            self,
            subject,
            callback,
            fail_drain=self.fail_next_drain,
        )
        self.fail_next_drain = False
        self._subs.setdefault(subject, []).append(callback)
        self.subscriptions.append(subscription)
        self._subscriptions.append(subscription)
        return subscription

    def remove_subscription(self, subscription: _DrainableSubscription) -> None:
        if not subscription.active:
            return
        callbacks = self._subs.get(subscription.subject, [])
        retained = [
            callback
            for callback in callbacks
            if callback is not subscription.callback
        ]
        if retained:
            self._subs[subscription.subject] = retained
        else:
            self._subs.pop(subscription.subject, None)
        subscription.active = False


class _Pool:
    def __init__(self, agent_type: str = "architect") -> None:
        self.agent_type = agent_type

    def info(self) -> dict[str, Any]:
        return {
            "agent_type": self.agent_type,
            "current_size": 1,
            "target_size": 2,
        }


class _VisibleWorkItemStore:
    def __init__(self, items: list[WorkItem]) -> None:
        self.items = items
        self.calls: list[int] = []

    async def list_ws_visible_work_items(self, *, limit: int) -> list[WorkItem]:
        self.calls.append(limit)
        return list(self.items)

    async def list_work_items(self, **_kwargs: Any) -> list[WorkItem]:
        raise AssertionError("generic list_work_items must not serve the WebSocket snapshot")

    async def get_work_item(self, _work_item_id: str) -> WorkItem | None:
        raise AssertionError("parent reads must not serve the WebSocket snapshot")


class _MemoryAttachmentStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def write(
        self,
        content_hash: str,
        blob: bytes,
        _mime: str,
        *,
        origin: str = "chat_attachment",
    ) -> Path:
        assert origin in {"agent_artifact", "chat_attachment"}
        self.blobs[content_hash] = bytes(blob)
        return Path(content_hash)

    async def read(self, content_hash: str) -> bytes:
        if content_hash not in self.blobs:
            raise FileNotFoundError(content_hash)
        return self.blobs[content_hash]


class _FakeWebSocket:
    def __init__(self, *, block_after: int | None = None) -> None:
        self.query_params: dict[str, str] = {}
        self.accepted = asyncio.Event()
        self.closed = asyncio.Event()
        self.receive_gate = asyncio.Event()
        self.release_send = asyncio.Event()
        self.sent: list[str] = []
        self.close_code: int | None = None
        self.block_after = block_after

    async def accept(self) -> None:
        self.accepted.set()

    async def send_text(self, payload: str) -> None:
        if self.block_after is not None and len(self.sent) >= self.block_after:
            await self.release_send.wait()
        self.sent.append(payload)

    async def receive_text(self) -> str:
        await self.receive_gate.wait()
        raise WebSocketDisconnect(code=self.close_code or 1000)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        del reason
        self.close_code = code
        self.closed.set()
        self.receive_gate.set()


class _BlockingAcceptWebSocket(_FakeWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.accept_started = asyncio.Event()
        self.accept_release = asyncio.Event()

    async def accept(self) -> None:
        self.accept_started.set()
        await self.accept_release.wait()
        await super().accept()


async def _wait_until(predicate: Callable[[], bool]) -> None:
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.002)
    raise AssertionError("condition did not become true")


def _session(parent_id: str, thread_id: str, *, state: str = "executing") -> CrewSessionContract:
    return CrewSessionContract.model_validate({
        "version": 1,
        "state": state,
        "previous_state": "discussing" if state != "discussing" else None,
        "revision": 3,
        "goal": "Prepare the live navigation report",
        "origin": "captain",
        "originator_id": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1", "agent-1"],
        "success_criteria": ["Complete"],
        "expected_deliverable": "Report",
        "thread_id": thread_id,
        "task_id": parent_id,
        "created_at": 100.0,
        "transitioned_at": 110.0,
        "started_at": 105.0 if state != "discussing" else None,
        "first_result_at": None,
        "verified_at": None,
        "completed_at": None,
        "last_result_summary": "",
        "blocked_reason": None,
        "blocked_since": None,
        "blocked_duration_seconds": 0.0,
        "evidence_refs": [],
        "result_artifact_id": None,
        "result_ref": None,
        "duplicate_resume_count": 0,
    })


@pytest.fixture
async def work_store(tmp_path: Path) -> Any:
    store = WorkItemStore(
        db_path=str(tmp_path / "work.db"),
        connection_factory=SQLiteConnectionFactory(),
        tick_interval=1_000,
    )
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


async def _create_crew_parent(
    store: WorkItemStore,
    parent_id: str,
) -> WorkItem:
    admission = store.claim_crew_session_admission_port()
    async with admission.reserve() as reservation:
        return await reservation.create_parent(CrewSessionParentCreate(
            id=parent_id,
            title="Crew session",
            description="Crew session",
            assigned_to="facilitator-1",
            created_by="captain",
            metadata={},
            created_at=100.0,
        ))


def _ordinary_item(index: int) -> WorkItem:
    return WorkItem(
        id=f"ordinary-{index:03d}",
        title="Ordinary",
        created_at=float(index),
        updated_at=float(index),
    )


async def test_ws_workforce_snapshot_delegates_once_without_parent_reads(
    tmp_path: Path,
) -> None:
    store = _VisibleWorkItemStore([_ordinary_item(1)])
    runtime = _Runtime(tmp_path, work_items=store)  # type: ignore[arg-type]

    snapshot = await build_ws_workforce_snapshot(runtime, limit=100)

    assert store.calls == [100]
    assert [item["id"] for item in snapshot["work_items"]] == ["ordinary-001"]


async def test_ws_workforce_snapshot_ordinary_overflow_is_stable(
    tmp_path: Path,
    work_store: WorkItemStore,
) -> None:
    for index in range(101):
        await work_store.create_work_item(
            id=f"ordinary-{index:03d}",
            title="Ordinary",
            created_at=float(index),
            updated_at=float(index),
        )
    runtime = _Runtime(tmp_path, work_items=work_store)

    with pytest.raises(ValueError, match="^ws_workforce_source_overflow$"):
        await build_ws_workforce_snapshot(runtime, limit=100)


async def test_ws_workforce_snapshot_excluded_crew_rows_do_not_overflow(
    tmp_path: Path,
    work_store: WorkItemStore,
) -> None:
    parent = await _create_crew_parent(work_store, "crew-parent")
    for index in range(101):
        await work_store.create_work_item(
            id=f"crew-child-{index:03d}",
            title="Crew child",
            parent_id=parent.id,
            created_at=200.0 + index,
            updated_at=200.0 + index,
        )
    ordinary = await work_store.create_work_item(
        id="ordinary-visible",
        title="Ordinary",
        created_at=1.0,
        updated_at=1.0,
    )
    runtime = _Runtime(tmp_path, work_items=work_store)

    snapshot = await build_ws_workforce_snapshot(runtime, limit=100)

    assert [item["id"] for item in snapshot["work_items"]] == [ordinary.id]


def test_runtime_store_callbacks_emit_exact_ids_only_after_commit(tmp_path: Path) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    events: list[dict[str, Any]] = []
    runtime.add_event_listener(events.append)
    thread = runtime.chat_thread_store.create_thread(
        title="Room",
        participants=["agent-1"],
    )

    runtime.chat_thread_store.append_message_once(
        thread.id,
        message_id="message-1",
        author_id="agent-1",
        role="agent",
        body="private body",
        created_at=10.0,
        metadata={"private": "metadata"},
    )
    runtime.artifact_store.add_version(
        thread_id=thread.id,
        name="report.md",
        content_hash="a" * 64,
        mime="text/markdown",
        size_bytes=12,
        created_by="agent-1",
    )

    message_event = next(
        event for event in events
        if event["type"] == EventType.CHAT_THREAD_MESSAGE_APPENDED.value
    )
    artifact_event = next(
        event for event in events
        if event["type"] == EventType.ARTIFACT_VERSION_ADDED.value
    )
    assert set(message_event["data"]) == {
        "thread_id", "message_id", "author_id", "role", "created_at",
    }
    assert set(artifact_event["data"]) == {
        "thread_id", "artifact_id", "version", "created_at",
    }
    forbidden = json.dumps([message_event, artifact_event]).lower()
    assert "private body" not in forbidden
    assert "content_hash" not in forbidden
    assert "metadata" not in forbidden


def test_append_message_once_is_idempotent_exact_and_post_commit(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "threads.db", clock=lambda: 10.0)
    thread = store.create_thread(title="Room", participants=["agent-1"])
    committed: list[str] = []
    store.set_message_committed_callback(lambda row: committed.append(row.id))
    expected = dict(
        message_id="message-1",
        author_id="agent-1",
        role="agent",
        body="result",
        created_at=20.0,
        metadata={"nested": {"flag": True}},
    )

    first = store.append_message_once(thread.id, **expected)
    second = store.append_message_once(thread.id, **expected)

    assert first == second
    assert committed == ["message-1"]
    assert store.get_thread(thread.id).last_active_at == 20.0
    with pytest.raises(ValueError, match="chat_thread_message_conflict"):
        store.append_message_once(thread.id, **{**expected, "metadata": {"nested": {"flag": 1}}})
    assert len(store.list_messages(thread.id)) == 1


def test_post_commit_callback_failure_does_not_fail_store_write(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "threads.db")
    thread = store.create_thread(title="Room", participants=["agent-1"])

    def _raise(_row: Any) -> None:
        raise RuntimeError("callback failure")

    store.set_message_committed_callback(_raise)
    written = store.append_message_once(
        thread.id,
        message_id="message-1",
        author_id="agent-1",
        role="agent",
        body="durable",
        created_at=10.0,
    )
    assert written is not None
    assert store.list_messages(thread.id)[0].body == "durable"


def test_artifact_shared_post_commit_helper_emits_only_new_rows(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts.db", clock=lambda: 10.0)
    committed: list[tuple[str, int]] = []
    store.set_version_committed_callback(
        lambda artifact: committed.append((artifact.id, artifact.version)),
    )
    args = dict(
        thread_id="thread-1",
        name="report.md",
        content_hash="a" * 64,
        mime="text/markdown",
        size_bytes=12,
        created_by="agent-1",
    )
    first = store.reconcile_exact_version(**args)
    reused = store.reconcile_exact_version(**args)
    second = store.add_version(**{**args, "content_hash": "b" * 64})

    assert reused.id == first.id
    assert committed == [(first.id, 1), (second.id, 2)]
    assert store.count_thread_latest("thread-1") == 1


def test_ws_auth_envelope_sequence_and_lifespan_listener_identity(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path, token="secret")
    app = create_app(runtime)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/events") as websocket:
                websocket.receive_text()
        assert exc_info.value.code == 1008

        with client.websocket_connect("/ws/events?token=secret") as websocket:
            snapshot = websocket.receive_json()
            assert set(snapshot) == {"type", "data", "timestamp", "stream"}
            assert snapshot["type"] == "state_snapshot"
            generation = snapshot["stream"]["generation"]
            assert len(generation) == 32
            assert snapshot["stream"]["sequence"] == 0
            runtime.emit("system_mode", {"mode": "idle", "previous": "active"})
            delta = websocket.receive_json()
            assert set(delta) == {"type", "data", "timestamp", "stream"}
            assert delta["stream"] == {"generation": generation, "sequence": 1}
        assert runtime.added == [app.state.broadcast_event]
    assert runtime.listeners == []
    assert runtime.removed == runtime.added
    assert app.state.event_stream_hub.client_count == 0


async def test_runtime_live_listener_is_live_only_and_stops_exact_subscription(
    tmp_path: Path,
) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    bus = _DrainableMockNATSBus()
    await bus.start()
    runtime.nats_bus = bus
    received: list[str] = []

    await bus.publish(
        "system.events.before",
        {"type": "before", "data": {}, "timestamp": 1.0},
    )
    handle = await runtime.register_live_event_listener(
        lambda event: received.append(event["type"]),
    )
    subscription = bus.subscriptions[-1]
    await bus.publish(
        "system.events.after",
        {"type": "after", "data": {}, "timestamp": 2.0},
    )

    assert received == ["after"]
    assert len(runtime._live_event_listeners) == 1
    await asyncio.gather(handle.stop(), handle.stop())
    assert runtime._live_event_listeners == []
    assert bus._subscriptions == []
    assert subscription.drain_calls == 1
    assert subscription.unsubscribe_calls == 0
    assert subscription.active is False


async def test_runtime_live_listener_setup_failure_and_cancellation_roll_back(
    tmp_path: Path,
) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    failing_bus = _DrainableMockNATSBus()
    await failing_bus.start()
    failing_bus.fail_subscribe = RuntimeError("subscribe failed")
    runtime.nats_bus = failing_bus

    with pytest.raises(RuntimeError, match="subscribe failed"):
        await runtime.register_live_event_listener(lambda _event: None)
    assert runtime._live_event_listeners == []
    assert failing_bus.subscriptions == []
    assert failing_bus._subs == {}

    blocking_bus = _DrainableMockNATSBus()
    await blocking_bus.start()
    blocking_bus.subscribe_release.clear()
    runtime.nats_bus = blocking_bus
    registration = asyncio.create_task(
        runtime.register_live_event_listener(lambda _event: None),
    )
    await blocking_bus.subscribe_started.wait()
    registration.cancel()
    await asyncio.sleep(0)
    assert registration.done() is False
    blocking_bus.subscribe_release.set()
    with pytest.raises(asyncio.CancelledError):
        await registration

    assert runtime._live_event_listeners == []
    assert len(blocking_bus.subscriptions) == 1
    assert blocking_bus._subscriptions == []
    assert blocking_bus.subscriptions[0].drain_calls == 1
    assert blocking_bus.subscriptions[0].active is False
    await asyncio.sleep(0)
    assert not [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and task.get_name().startswith("runtime-live-event-listener-")
    ]


async def test_runtime_live_listener_restart_and_drain_fallback_are_identity_safe(
    tmp_path: Path,
) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    bus = _DrainableMockNATSBus()
    await bus.start()
    runtime.nats_bus = bus
    first_events: list[str] = []
    second_events: list[str] = []

    first = await runtime.register_live_event_listener(
        lambda event: first_events.append(event["type"]),
    )
    second = await runtime.register_live_event_listener(
        lambda event: second_events.append(event["type"]),
    )
    first_subscription, second_subscription = bus.subscriptions
    await first.stop()
    await bus.publish(
        "system.events.live",
        {"type": "live", "data": {}, "timestamp": 3.0},
    )

    assert first_events == []
    assert second_events == ["live"]
    assert first_subscription.drain_calls == 1
    assert second_subscription.drain_calls == 0
    bus.fail_next_drain = True
    third = await runtime.register_live_event_listener(lambda _event: None)
    third_subscription = bus.subscriptions[-1]
    await third.stop()
    assert third_subscription.drain_calls == 1
    assert third_subscription.unsubscribe_calls == 1
    await second.stop()
    assert second_subscription.drain_calls == 1
    assert runtime._live_event_listeners == []
    assert bus._subscriptions == []


async def test_runtime_live_listener_release_uses_captured_bus_identity(
    tmp_path: Path,
) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    owning_bus = _DrainableMockNATSBus()
    replacement_bus = _DrainableMockNATSBus()
    await owning_bus.start()
    await replacement_bus.start()
    runtime.nats_bus = owning_bus
    handle = await runtime.register_live_event_listener(lambda _event: None)
    subscription = owning_bus.subscriptions[-1]

    runtime.nats_bus = replacement_bus
    await handle.stop()

    assert subscription.drain_calls == 1
    assert owning_bus._subscriptions == []
    assert replacement_bus._subscriptions == []


async def test_api_lifespan_awaits_live_listener_readiness_and_drains_on_exit(
    tmp_path: Path,
) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    bus = _DrainableMockNATSBus()
    await bus.start()
    bus.subscribe_release.clear()
    runtime.nats_bus = bus
    app = create_app(runtime)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            entered.set()
            await release.wait()

    lifespan_task = asyncio.create_task(_run_lifespan())
    await bus.subscribe_started.wait()
    assert entered.is_set() is False
    assert app.state.broadcast_event is None
    bus.subscribe_release.set()
    await entered.wait()
    assert app.state.broadcast_event is not None
    release.set()
    await lifespan_task

    assert runtime._live_event_listeners == []
    assert len(bus.subscriptions) == 1
    assert bus._subscriptions == []
    assert bus.subscriptions[0].drain_calls == 1
    assert app.state.event_stream_hub._dispatcher_task is None


async def test_api_lifespan_failure_and_cancellation_leave_no_listener_or_task(
    tmp_path: Path,
) -> None:
    failed_runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "failed")
    failed_bus = _DrainableMockNATSBus()
    await failed_bus.start()
    failed_bus.fail_subscribe = RuntimeError("lifespan subscribe failed")
    failed_runtime.nats_bus = failed_bus
    failed_app = create_app(failed_runtime)

    with pytest.raises(RuntimeError, match="lifespan subscribe failed"):
        async with failed_app.router.lifespan_context(failed_app):
            raise AssertionError("lifespan must not yield after setup failure")
    assert failed_runtime._live_event_listeners == []
    assert failed_app.state.event_stream_hub._dispatcher_task is None

    cancelled_runtime = ProbOSRuntime(
        config=SystemConfig(),
        data_dir=tmp_path / "cancelled",
    )
    cancelled_bus = _DrainableMockNATSBus()
    await cancelled_bus.start()
    cancelled_bus.subscribe_release.clear()
    cancelled_runtime.nats_bus = cancelled_bus
    cancelled_app = create_app(cancelled_runtime)

    async def _run_cancelled_lifespan() -> None:
        async with cancelled_app.router.lifespan_context(cancelled_app):
            raise AssertionError("cancelled setup must not yield")

    lifespan_task = asyncio.create_task(_run_cancelled_lifespan())
    await cancelled_bus.subscribe_started.wait()
    lifespan_task.cancel()
    await asyncio.sleep(0)
    assert lifespan_task.done() is False
    cancelled_bus.subscribe_release.set()
    with pytest.raises(asyncio.CancelledError):
        await lifespan_task

    assert cancelled_runtime._live_event_listeners == []
    assert len(cancelled_bus.subscriptions) == 1
    assert cancelled_bus._subscriptions == []
    assert cancelled_bus.subscriptions[0].drain_calls == 1
    assert cancelled_app.state.event_stream_hub._dispatcher_task is None


async def test_api_lifespan_restarts_restore_tracking_without_duplicate_delivery(
    tmp_path: Path,
) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    bus = _DrainableMockNATSBus()
    await bus.start()
    runtime.nats_bus = bus
    baseline = len(bus._subscriptions)

    for index in range(2):
        app = create_app(runtime)
        async with app.router.lifespan_context(app):
            assert len(bus._subscriptions) == baseline + 1
            await bus.publish(
                f"system.events.restart-{index}",
                {
                    "type": "system_mode",
                    "data": {"mode": "idle", "previous": "active"},
                    "timestamp": float(index + 1),
                },
            )
            for _ in range(20):
                if app.state.event_stream_hub.sequence == 1:
                    break
                await asyncio.sleep(0)
            assert app.state.event_stream_hub.sequence == 1

        assert len(bus._subscriptions) == baseline
        assert runtime._live_event_listeners == []


def test_detacher_rejects_hostile_containers_nonfinite_and_excess_depth() -> None:
    class _HostileDict(dict):
        def items(self) -> Any:
            raise AssertionError("must not iterate a dict subclass")

    with pytest.raises(WireValueError):
        detach_json_value(_HostileDict({"safe": 1}))
    with pytest.raises(WireValueError):
        detach_json_value({"value": math.inf})
    nested: object = "leaf"
    for _ in range(30):
        nested = [nested]
    with pytest.raises(WireValueError):
        detach_json_value(nested)


async def test_router_broadcast_without_timestamp_gets_server_timestamp(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    hub = WSEventStreamHub(runtime)
    await hub.start()
    websocket = _FakeWebSocket()
    serve_task = asyncio.create_task(hub.serve(websocket))
    try:
        await websocket.accepted.wait()
        await _wait_until(lambda: len(websocket.sent) == 1)
        hub.ingress({"type": "game_update", "data": {"status": "in_progress"}})
        await _wait_until(lambda: len(websocket.sent) == 2)
        frame = json.loads(websocket.sent[1])
        assert frame["type"] == "game_update"
        assert math.isfinite(frame["timestamp"])
        assert frame["timestamp"] >= 0
        assert frame["stream"] == {
            "generation": hub.generation,
            "sequence": 1,
        }
    finally:
        await hub.stop()
        await asyncio.gather(serve_task, return_exceptions=True)


async def test_connect_queues_delta_arriving_during_accept_after_snapshot(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    hub = WSEventStreamHub(runtime)
    await hub.start()
    websocket = _BlockingAcceptWebSocket()
    serve_task = asyncio.create_task(hub.serve(websocket))
    try:
        await websocket.accept_started.wait()
        assert hub.client_count == 1
        hub.ingress({"type": "bounded_event", "data": {"value": 1}})
        await _wait_until(lambda: hub.sequence == 1)
        websocket.accept_release.set()
        await websocket.accepted.wait()
        await _wait_until(lambda: len(websocket.sent) == 2)
        snapshot_frame, delta_frame = map(json.loads, websocket.sent)
        assert snapshot_frame["type"] == "state_snapshot"
        assert snapshot_frame["stream"]["sequence"] == 0
        assert delta_frame["type"] == "bounded_event"
        assert delta_frame["stream"]["sequence"] == 1
    finally:
        websocket.accept_release.set()
        await hub.stop()
        await asyncio.gather(serve_task, return_exceptions=True)


async def test_ingress_and_client_queues_are_count_and_byte_bounded(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)
    hub = WSEventStreamHub(runtime)
    await hub.start()
    try:
        for index in range(MAX_INGRESS_ITEMS + 50):
            hub.ingress({
                "type": "bounded_event",
                "data": {"index": index},
                "timestamp": 1.0,
            })
        assert len(hub._ingress) == MAX_INGRESS_ITEMS
        assert hub._global_resync_requested is True

        websocket = _FakeWebSocket(block_after=1)
        serve_task = asyncio.create_task(hub.serve(websocket))
        await websocket.accepted.wait()
        await _wait_until(lambda: len(websocket.sent) == 1)
        baseline_sequence = hub.sequence
        for index in range(50):
            hub.ingress({
                "type": "bounded_event",
                "data": {"next": index},
                "timestamp": 2.0,
            })
        await _wait_until(lambda: hub.sequence >= baseline_sequence + 50)
        client = next(iter(hub._clients.values()))
        assert len(client.queue) <= MAX_CLIENT_FRAMES
        assert client.queued_bytes <= MAX_CLIENT_BYTES
        assert client.resync_pending or client.close_code == 1013
        websocket.release_send.set()
        await hub.stop()
        await asyncio.gather(serve_task, return_exceptions=True)
    finally:
        if hub._dispatcher_task is not None:
            await hub.stop()


async def test_sender_timeout_closes_only_slow_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import probos.ws_event_stream as stream_module

    monkeypatch.setattr(stream_module, "SEND_TIMEOUT_SECONDS", 0.01)
    runtime = _Runtime(tmp_path)
    hub = WSEventStreamHub(runtime)
    await hub.start()
    websocket = _FakeWebSocket(block_after=1)
    serve_task = asyncio.create_task(hub.serve(websocket))
    try:
        await websocket.accepted.wait()
        await _wait_until(lambda: len(websocket.sent) == 1)
        hub.ingress({"type": "bounded_event", "data": {}, "timestamp": 1.0})
        await asyncio.wait_for(websocket.closed.wait(), timeout=1.0)
        assert websocket.close_code == 1013
    finally:
        websocket.release_send.set()
        await hub.stop()
        await asyncio.gather(serve_task, return_exceptions=True)


async def test_authoritative_bounded_snapshot_preserves_runtime_parity(
    tmp_path: Path,
) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    agent = SimpleNamespace(
        id="agent-1",
        agent_type="architect",
        callsign="ARCHITECT",
        pool="present-pool",
        state=SimpleNamespace(value="idle"),
        confidence=0.75,
        tier="domain",
    )
    runtime.registry = _Registry([agent])  # type: ignore[assignment]
    runtime.trust_network = _Trust(0.8)  # type: ignore[assignment]
    runtime.hebbian_router = _Hebbian({
        ("agent-1", "agent-2", "learned"): 0.625,
    })  # type: ignore[assignment]
    runtime.pools = {"present-pool": _Pool()}
    runtime.pool_groups = PoolGroupRegistry()
    runtime.pool_groups.register(PoolGroup(
        name="bridge",
        display_name="Bridge",
        pool_names={"present-pool", "future-pool"},
    ))
    runtime.callsign_registry._type_to_profile["architect"] = {
        "display_name": "Chief Architect",
    }
    runtime.notification_queue = _Notifications([{"id": "notice-1"}])  # type: ignore[assignment]
    runtime.persistent_task_store = SimpleNamespace(
        snapshot=lambda: [{"id": "scheduled-1"}],
    )
    runtime.work_item_store = _VisibleWorkItemStore([])  # type: ignore[assignment]
    runtime._emergent_detector = SimpleNamespace(
        summary=lambda: {"tc_n": 0.42, "routing_entropy": 0.17},
    )
    runtime._fresh_boot = True
    runtime._lifecycle_state = "running"
    runtime._last_request_time = time.monotonic()
    runtime.dream_scheduler = SimpleNamespace(is_dreaming=False)

    snapshot = await build_ws_state_snapshot(runtime)
    expected_keys = {
        "agents",
        "connections",
        "pools",
        "system_mode",
        "tc_n",
        "routing_entropy",
        "fresh_boot",
        "temporal",
        "pool_groups",
        "pool_to_group",
        "directives",
        "notifications",
        "unread_count",
        "scheduled_tasks",
        "workforce",
        "ward_room_stats",
        "skill_framework",
        "acm",
    }

    assert set(snapshot) == expected_keys
    assert snapshot["system_mode"] == "active"
    assert snapshot["fresh_boot"] is True
    assert snapshot["tc_n"] == format_trust(0.42)
    assert snapshot["routing_entropy"] == format_trust(0.17)
    assert snapshot["agents"][0]["display_name"] == "Chief Architect"
    assert snapshot["agents"][0]["agency"] == agency_from_rank(
        Rank.from_trust(0.8),
    ).value
    assert snapshot["pool_to_group"] == {
        "present-pool": "bridge",
        "future-pool": "bridge",
    }
    assert snapshot["workforce"] == {
        "work_items": [],
        "bookings": [],
        "resources": [],
    }

    runtime._fresh_boot = False
    runtime._last_request_time = time.monotonic() - 31
    assert runtime.build_bounded_hxi_snapshot_base()["system_mode"] == "idle"
    runtime.dream_scheduler.is_dreaming = True
    assert runtime.build_bounded_hxi_snapshot_base()["system_mode"] == "dreaming"


@pytest.mark.parametrize(
    ("source", "expected_error"),
    [
        ("agents", "ws_snapshot_agents_overflow"),
        ("connections", "ws_snapshot_connections_overflow"),
        ("pools", "ws_snapshot_pools_overflow"),
        ("pool_groups", "ws_snapshot_pool_groups_overflow"),
        ("group_memberships", "ws_snapshot_group_memberships_overflow"),
        ("pool_mappings", "ws_snapshot_pool_mappings_overflow"),
        ("notifications", "ws_snapshot_notifications_overflow"),
        ("scheduled_tasks", "ws_snapshot_scheduled_tasks_overflow"),
        ("directives", "ws_snapshot_directives_overflow"),
    ],
)
def test_bounded_snapshot_source_caps_fail_closed(
    tmp_path: Path,
    source: str,
    expected_error: str,
) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / source)
    runtime.registry = _Registry()  # type: ignore[assignment]
    runtime.hebbian_router = _Hebbian()  # type: ignore[assignment]
    runtime.pools = {}
    runtime.pool_groups = PoolGroupRegistry()
    runtime.notification_queue = _Notifications()  # type: ignore[assignment]
    runtime.persistent_task_store = None
    runtime.directive_store = None

    if source == "agents":
        runtime.registry = _Registry([object()] * 1_001)  # type: ignore[assignment]
    elif source == "connections":
        runtime.hebbian_router = _Hebbian({
            (f"source-{index}", f"target-{index}", "learned"): 0.5
            for index in range(1_001)
        })  # type: ignore[assignment]
    elif source == "pools":
        runtime.pools = {
            f"pool-{index}": _Pool()
            for index in range(1_001)
        }
    elif source == "pool_groups":
        for index in range(129):
            runtime.pool_groups.register(PoolGroup(
                name=f"group-{index}",
                display_name="Group",
            ))
    elif source == "group_memberships":
        runtime.pool_groups.register(PoolGroup(
            name="large-group",
            display_name="Large",
            pool_names={f"pool-{index}" for index in range(1_001)},
        ))
    elif source == "pool_mappings":
        for index in range(1_001):
            runtime.pool_groups.register(PoolGroup(
                name="replacement-group",
                display_name="Replacement",
                pool_names={f"pool-{index}"},
            ))
    elif source == "notifications":
        runtime.notification_queue = _Notifications([{}] * 1_001)  # type: ignore[assignment]
    elif source == "scheduled_tasks":
        runtime.persistent_task_store = SimpleNamespace(
            snapshot=lambda: [{}] * 1_001,
        )
    elif source == "directives":
        runtime.directive_store = SimpleNamespace(
            list_directives_bounded=lambda **_kwargs: [
                SimpleNamespace(status=SimpleNamespace(value="active"))
                for _ in range(1_001)
            ],
        )

    with pytest.raises(ValueError, match=f"^{expected_error}$"):
        runtime.build_bounded_hxi_snapshot_base()


def _runtime_for_snapshot_admission(
    tmp_path: Path,
    source: str,
    count: object,
    calls: list[str],
) -> ProbOSRuntime:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / source)

    def _record(name: str, value: Any) -> Any:
        calls.append(name)
        return value

    runtime.registry = SimpleNamespace(  # type: ignore[assignment]
        count=count if source == "agents" else 0,
        all=lambda: _record("agents", []),
    )
    runtime.hebbian_router = SimpleNamespace(  # type: ignore[assignment]
        weight_count=count if source == "connections" else 0,
        all_weights_typed=lambda: _record("connections", {}),
    )

    class _CountedPools(dict[str, Any]):
        def __len__(self) -> int:
            if source == "pools":
                return int(count)
            return 0

        def items(self) -> Any:
            return _record("pools", super().items())

    runtime.pools = _CountedPools()
    runtime.pool_groups = SimpleNamespace(  # type: ignore[assignment]
        count=count if source == "pool_groups" else 0,
        membership_count=count if source == "group_memberships" else 0,
        pool_mapping_count=count if source == "pool_mappings" else 0,
        all_groups=lambda: _record("pool_groups", []),
        pool_to_group_snapshot=lambda: _record("pool_mappings", {}),
        group_health=lambda _name, _pools: {},
        get_group_for_pool=lambda _name: None,
    )
    runtime.notification_queue = SimpleNamespace(  # type: ignore[assignment]
        count=count if source == "notifications" else 0,
        snapshot=lambda: _record("notifications", []),
        unread_count=lambda: 0,
    )
    runtime.persistent_task_store = None
    runtime.directive_store = None
    return runtime


@pytest.mark.parametrize(
    ("source", "count", "expected_error"),
    [
        ("agents", 1_001, "ws_snapshot_agents_overflow"),
        ("connections", 1_001, "ws_snapshot_connections_overflow"),
        ("pools", 1_001, "ws_snapshot_pools_overflow"),
        ("pool_groups", 129, "ws_snapshot_pool_groups_overflow"),
        ("group_memberships", 1_001, "ws_snapshot_group_memberships_overflow"),
        ("pool_mappings", 1_001, "ws_snapshot_pool_mappings_overflow"),
        ("notifications", 1_001, "ws_snapshot_notifications_overflow"),
    ],
)
def test_snapshot_count_overflow_precedes_full_accessor(
    tmp_path: Path,
    source: str,
    count: int,
    expected_error: str,
) -> None:
    calls: list[str] = []
    runtime = _runtime_for_snapshot_admission(tmp_path, source, count, calls)

    with pytest.raises(ValueError, match=f"^{expected_error}$"):
        runtime.build_bounded_hxi_snapshot_base()

    assert source not in calls
    if source in {"pool_groups", "group_memberships", "pool_mappings"}:
        assert "pool_groups" not in calls
        assert "pool_mappings" not in calls


@pytest.mark.parametrize(
    ("source", "expected_error"),
    [
        ("agents", "ws_snapshot_agents_overflow"),
        ("connections", "ws_snapshot_connections_overflow"),
        ("pool_groups", "ws_snapshot_pool_groups_overflow"),
        ("group_memberships", "ws_snapshot_group_memberships_overflow"),
        ("pool_mappings", "ws_snapshot_pool_mappings_overflow"),
        ("notifications", "ws_snapshot_notifications_overflow"),
    ],
)
@pytest.mark.parametrize("malformed_count", [True, -1, 1.5])
def test_snapshot_malformed_owner_count_fails_before_full_accessor(
    tmp_path: Path,
    source: str,
    expected_error: str,
    malformed_count: object,
) -> None:
    calls: list[str] = []
    runtime = _runtime_for_snapshot_admission(
        tmp_path,
        source,
        malformed_count,
        calls,
    )

    with pytest.raises(ValueError, match=f"^{expected_error}$"):
        runtime.build_bounded_hxi_snapshot_base()

    assert source not in calls
    if source in {"pool_groups", "group_memberships", "pool_mappings"}:
        assert "pool_groups" not in calls
        assert "pool_mappings" not in calls


@pytest.mark.parametrize(
    ("source", "count", "expected_accessor"),
    [
        ("agents", 1_000, "agents"),
        ("connections", 1_000, "connections"),
        ("pools", 1_000, "pools"),
        ("pool_groups", 128, "pool_groups"),
        ("group_memberships", 1_000, "pool_groups"),
        ("pool_mappings", 1_000, "pool_mappings"),
        ("notifications", 1_000, "notifications"),
    ],
)
def test_snapshot_exact_count_cap_proceeds_to_full_accessor(
    tmp_path: Path,
    source: str,
    count: int,
    expected_accessor: str,
) -> None:
    calls: list[str] = []
    runtime = _runtime_for_snapshot_admission(tmp_path, source, count, calls)

    runtime.build_bounded_hxi_snapshot_base()

    assert expected_accessor in calls


def test_snapshot_directives_use_bounded_seam_and_preserve_exact_cap(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Any]] = []
    runtime = _runtime_for_snapshot_admission(tmp_path, "directives", 0, [])
    active = SimpleNamespace(status=SimpleNamespace(value="active"))

    def _bounded(*, include_inactive: bool, limit: int) -> list[Any]:
        calls.append(("bounded", (include_inactive, limit)))
        return [active] * limit

    runtime.directive_store = SimpleNamespace(
        list_directives_bounded=_bounded,
        all_directives=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("all_directives must not serve bounded snapshots")
        ),
    )

    snapshot = runtime.build_bounded_hxi_snapshot_base()

    assert calls == [("bounded", (False, 1_000))]
    assert snapshot["directives"] == {"active": 1_000, "pending": 0}

    runtime.directive_store.list_directives_bounded = lambda **_kwargs: [  # type: ignore[method-assign]
        active
    ] * 1_001
    with pytest.raises(ValueError, match="^ws_snapshot_directives_overflow$"):
        runtime.build_bounded_hxi_snapshot_base()


def test_bounded_snapshot_under_cap_matches_legacy_source_projection(
    tmp_path: Path,
) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "parity")
    runtime.registry = _Registry()  # type: ignore[assignment]
    runtime.hebbian_router = _Hebbian()  # type: ignore[assignment]
    runtime.pools = {}
    runtime.pool_groups = PoolGroupRegistry()
    runtime.pool_groups.register(PoolGroup(
        name="future",
        display_name="Future",
        pool_names={"not-instantiated"},
    ))
    runtime.notification_queue = _Notifications([{"id": "notice"}])  # type: ignore[assignment]
    runtime.persistent_task_store = SimpleNamespace(
        snapshot=lambda: [{"id": "scheduled"}],
    )
    runtime.directive_store = None
    scalars = {
        "system_mode": "active",
        "tc_n": 0.0,
        "routing_entropy": 0.0,
        "fresh_boot": False,
        "temporal": {"fixed": True},
    }
    runtime._build_hxi_system_scalars = lambda: scalars  # type: ignore[method-assign]

    legacy = runtime.build_state_snapshot()
    legacy.pop("workforce")

    assert runtime.build_bounded_hxi_snapshot_base() == legacy


async def test_dispatcher_contains_route_failure_resyncs_and_delivers_next(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _FailOnceStore(_VisibleWorkItemStore):
        def __init__(self) -> None:
            super().__init__([])
            self.lookup_calls = 0

        async def get_work_item(self, _work_item_id: str) -> WorkItem | None:
            self.lookup_calls += 1
            if self.lookup_calls == 1:
                raise RuntimeError("private lookup detail")
            return None

    store = _FailOnceStore()
    runtime = _Runtime(tmp_path, work_items=store)  # type: ignore[arg-type]
    hub = WSEventStreamHub(runtime)
    await hub.start()
    dispatcher = hub._dispatcher_task
    websocket = _FakeWebSocket()
    serve_task = asyncio.create_task(hub.serve(websocket))
    try:
        await websocket.accepted.wait()
        await _wait_until(lambda: len(websocket.sent) == 1)
        with caplog.at_level("WARNING"):
            hub.ingress({
                "type": "work_item_updated",
                "data": {
                    "work_item": {
                        "id": "child-private",
                        "parent_id": "parent-private",
                        "work_type": "ordinary",
                        "status": "open",
                    },
                },
                "timestamp": 1.0,
            })
            hub.ingress({
                "type": "valid_event",
                "data": {"value": 1},
                "timestamp": 2.0,
            })
            await _wait_until(lambda: len(websocket.sent) == 3)

        repair = json.loads(websocket.sent[1])
        delivered = json.loads(websocket.sent[2])
        assert repair["type"] == "resync_required"
        assert repair["stream"]["sequence"] == 1
        assert delivered["type"] == "valid_event"
        assert delivered["stream"]["sequence"] == 2
        assert dispatcher is hub._dispatcher_task
        assert dispatcher is not None and not dispatcher.done()
        assert "parent-private" not in caplog.text
        assert "private lookup detail" not in caplog.text
        assert "RuntimeError" in caplog.text
    finally:
        await hub.stop()
        await asyncio.gather(serve_task, return_exceptions=True)
    assert dispatcher is not None and dispatcher.done()


async def test_dispatcher_route_cancellation_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _Runtime(tmp_path)
    hub = WSEventStreamHub(runtime)
    await hub.start()

    async def _cancel_route(*_args: Any) -> Any:
        raise asyncio.CancelledError()

    monkeypatch.setattr(hub._projector, "route_event", _cancel_route)
    dispatcher = hub._dispatcher_task
    assert dispatcher is not None
    hub.ingress({"type": "valid_event", "data": {}, "timestamp": 1.0})
    with pytest.raises(asyncio.CancelledError):
        await dispatcher
    assert dispatcher.cancelled()
    hub._dispatcher_task = None
    await hub.stop()


async def test_real_parent_child_projection_suppresses_raw_and_counts_outputs(
    tmp_path: Path,
    work_store: WorkItemStore,
) -> None:
    parent = await _create_crew_parent(work_store, "parent-1")
    child = await work_store.create_work_item(
        id="child-1",
        title="Research",
        description="Research",
        parent_id=parent.id,
        assigned_to="agent-1",
        status="done",
    )
    threads = ChatThreadStore(tmp_path / "threads.db")
    thread = threads.create_thread(
        title="Crew room",
        participants=["facilitator-1", "agent-1"],
        task_id=parent.id,
    )
    artifacts = ArtifactStore(tmp_path / "artifacts.db")
    artifact = artifacts.add_version(
        thread_id=thread.id,
        name="report.md",
        content_hash="a" * 64,
        mime="text/markdown",
        size_bytes=12,
        created_by="agent-1",
    )
    service = _ProjectionService()
    service.sessions[parent.id] = _session(parent.id, thread.id)
    runtime = _Runtime(
        tmp_path,
        work_items=work_store,
        threads=threads,
        artifacts=artifacts,
        service=service,
    )
    hub = WSEventStreamHub(runtime)
    await hub.start()
    websocket = _FakeWebSocket()
    serve_task = asyncio.create_task(hub.serve(websocket))
    try:
        await websocket.accepted.wait()
        await _wait_until(lambda: len(websocket.sent) == 1)
        snapshot = json.loads(websocket.sent[0])
        assert snapshot["data"]["workforce"]["work_items"] == []

        hub.ingress({
            "type": "work_item_updated",
            "data": {"work_item": child.to_dict()},
            "timestamp": 2.0,
        })
        await _wait_until(lambda: len(websocket.sent) >= 2)
        projected = json.loads(websocket.sent[1])
        assert projected["type"] == "crew_session_projection"
        assert projected["data"]["parent_id"] == parent.id
        assert projected["data"]["session"]["progress"]["done"] == 1
        assert projected["data"]["room_summary"]["outputs"] == 1
        assert "metadata" not in json.dumps(projected)

        hub.ingress({
            "type": "artifact_version_added",
            "data": {
                "thread_id": thread.id,
                "artifact_id": artifact.id,
                "version": artifact.version,
                "created_at": artifact.created_at,
            },
            "timestamp": 3.0,
        })
        await _wait_until(lambda: len(websocket.sent) >= 4)
        artifact_frame = json.loads(websocket.sent[2])
        assert artifact_frame["type"] == "artifact_version_added"
        assert set(artifact_frame["data"]) == {
            "thread_id", "artifact_id", "version", "created_at",
        }
        assert json.loads(websocket.sent[3])["type"] == "crew_session_projection"

        hub.ingress({
            "type": "chat_thread_message_appended",
            "data": {
                "thread_id": thread.id,
                "message_id": "message-1",
                "author_id": "agent-1",
                "role": "agent",
                "created_at": 4.0,
            },
            "timestamp": 4.0,
        })
        await _wait_until(lambda: len(websocket.sent) >= 5)
        assert json.loads(websocket.sent[4])["type"] == "chat_thread_message_appended"
    finally:
        await hub.stop()
        await asyncio.gather(serve_task, return_exceptions=True)


async def test_malformed_special_event_is_dropped_without_advancing_sequence(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)
    hub = WSEventStreamHub(runtime)
    await hub.start()
    try:
        hub.ingress({
            "type": "chat_thread_message_appended",
            "data": {"thread_id": "thread-1", "body": "forbidden"},
            "timestamp": 1.0,
        })
        await asyncio.sleep(0)
        assert hub.sequence == 0
        assert len(hub._ingress) == 0
    finally:
        await hub.stop()


async def test_projector_cancellation_rejects_old_generation_completion(
    tmp_path: Path,
    work_store: WorkItemStore,
) -> None:
    parent = await _create_crew_parent(work_store, "parent-1")
    threads = ChatThreadStore(tmp_path / "threads.db")
    thread = threads.create_thread(
        title="Crew room",
        participants=["facilitator-1"],
        task_id=parent.id,
    )
    service = _ProjectionService()
    service.sessions[parent.id] = _session(parent.id, thread.id)
    service.release = asyncio.Event()
    runtime = _Runtime(
        tmp_path,
        work_items=work_store,
        threads=threads,
        artifacts=ArtifactStore(tmp_path / "artifacts.db"),
        service=service,
    )
    hub = WSEventStreamHub(runtime)
    await hub.start()
    old_generation = hub.generation
    hub.ingress({
        "type": "work_item_updated",
        "data": {"work_item": {"id": parent.id, "work_type": "crew_session", "status": "open"}},
        "timestamp": 1.0,
    })
    await service.started.wait()
    await hub.stop()
    service.release.set()
    assert hub.sequence == 0

    restarted = WSEventStreamHub(runtime)
    assert restarted.generation != old_generation
    await restarted.start()
    await restarted.stop()


async def test_duplicate_parent_event_during_projection_gets_one_bounded_rerun(
    tmp_path: Path,
    work_store: WorkItemStore,
) -> None:
    parent = await _create_crew_parent(work_store, "parent-1")
    threads = ChatThreadStore(tmp_path / "threads.db")
    thread = threads.create_thread(
        title="Crew room",
        participants=["facilitator-1"],
        task_id=parent.id,
    )
    service = _ProjectionService()
    service.sessions[parent.id] = _session(parent.id, thread.id)
    service.release = asyncio.Event()
    runtime = _Runtime(
        tmp_path,
        work_items=work_store,
        threads=threads,
        artifacts=ArtifactStore(tmp_path / "artifacts.db"),
        service=service,
    )
    hub = WSEventStreamHub(runtime)
    await hub.start()
    websocket = _FakeWebSocket()
    serve_task = asyncio.create_task(hub.serve(websocket))
    event = {
        "type": "work_item_updated",
        "data": {
            "work_item": {
                "id": parent.id,
                "work_type": "crew_session",
                "status": "open",
            },
        },
        "timestamp": 1.0,
    }
    try:
        await websocket.accepted.wait()
        await _wait_until(lambda: len(websocket.sent) == 1)
        hub.ingress(event)
        await service.started.wait()
        hub.ingress(event)
        await _wait_until(
            lambda: parent.id in hub._projector._dirty_ids,
        )
        service.release.set()
        await _wait_until(lambda: service.calls == 2 and len(websocket.sent) == 3)
        assert [json.loads(payload)["type"] for payload in websocket.sent[1:]] == [
            "crew_session_projection",
            "crew_session_projection",
        ]
    finally:
        service.release.set()
        await hub.stop()
        await asyncio.gather(serve_task, return_exceptions=True)


async def test_terminal_commit_reconciliation_and_resume_append_one_room_message(
    tmp_path: Path,
    work_store: WorkItemStore,
) -> None:
    parent = await _create_crew_parent(work_store, "parent-1")
    child = await work_store.create_work_item(
        id="child-1",
        title="Research",
        description="Research",
        parent_id=parent.id,
        assigned_to="agent-1",
        status="in_progress",
        metadata={"spec_id": "spec-1"},
    )
    threads = ChatThreadStore(tmp_path / "threads.db")
    thread = threads.create_thread(
        title="Crew room",
        participants=["facilitator-1", "agent-1"],
        task_id=parent.id,
    )
    committed: list[str] = []
    threads.set_message_committed_callback(lambda message: committed.append(message.id))
    attachments = _MemoryAttachmentStore()
    runtime = SimpleNamespace(
        chat_thread_store=threads,
        attachment_store=attachments,
    )
    executor = CrewTaskExecutor(
        work_item_store=work_store,
        agent_registry=_Registry(),
        agentic_executor=SimpleNamespace(),
        runtime=runtime,
        attachment_store=attachments,
    )
    output = "Authoritative child result"
    result = await executor._persist_terminal_result(
        parent_id=parent.id,
        child=child,
        thread_id=thread.id,
        status="done",
        stopped_reason="complete",
        output=output,
        tool_trace_ref=None,
        actual_tokens=3,
        artifact_refs=[],
        started_at=200.0,
        finished_at=201.0,
        blocked_dependency_ids=[],
        expected_status="in_progress",
    )
    assert result.status == "done"
    assert len(threads.list_messages(thread.id)) == 1

    reconciled = await executor._persist_terminal_result(
        parent_id=parent.id,
        child=child,
        thread_id=thread.id,
        status="done",
        stopped_reason="complete",
        output=output,
        tool_trace_ref=None,
        actual_tokens=3,
        artifact_refs=[],
        started_at=200.0,
        finished_at=201.0,
        blocked_dependency_ids=[],
        expected_status="in_progress",
    )
    assert reconciled.status == "done"
    assert len(threads.list_messages(thread.id)) == 1

    authoritative = await work_store.get_work_item(child.id)
    assert authoritative is not None
    resumed = await executor._reconstruct_terminal_result(
        parent.id,
        authoritative,
        thread.id,
    )
    assert resumed.output == output
    assert len(threads.list_messages(thread.id)) == 1
    assert len(committed) == 1
    message = threads.list_messages(thread.id)[0]
    output_hash = hashlib.sha256(output.encode()).hexdigest()
    assert message.metadata == {
        "source": "crew_session_child_result",
        "parent_id": parent.id,
        "work_item_id": child.id,
        "content_hash": output_hash,
    }


async def test_snapshot_source_overflow_closes_1013_without_partial_frame(tmp_path: Path) -> None:
    agents = [
        SimpleNamespace(
            id=f"agent-{index}",
            agent_type="crew",
            callsign=f"A{index}",
            pool="crew",
            state="active",
            confidence=1.0,
            tier="domain",
        )
        for index in range(1001)
    ]
    runtime = _Runtime(tmp_path, agents=agents)
    with pytest.raises(ValueError, match="^ws_snapshot_agents_overflow$"):
        await build_ws_state_snapshot(runtime)

    hub = WSEventStreamHub(runtime)
    await hub.start()
    websocket = _FakeWebSocket()
    try:
        await hub.serve(websocket)
        assert websocket.close_code == 1013
        assert websocket.sent == []
    finally:
        await hub.stop()