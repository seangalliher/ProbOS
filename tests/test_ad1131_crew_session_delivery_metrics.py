"""AD-1131: durable CrewSession outcome delivery and bounded metrics."""

from __future__ import annotations

import asyncio
import copy
import inspect
import itertools
import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Sequence

import pytest

from probos.cognitive.crew_session import (
    CrewSessionContract,
    CrewSessionMetrics,
    CrewSessionService,
)
from probos.config import AgenticDispatchConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.crew_session_delivery import (
    CrewSessionDeliveryOutboxEntry,
    CrewSessionDeliveryOutcome,
    CrewSessionDeliveryRecord,
    CrewSessionDeliveryService,
)
from probos.events import EventType
from probos.notifications import NotificationQueue
from probos.protocols import ConnectionFactory, DatabaseConnection
from probos.runtime import ProbOSRuntime
from probos.startup.finalize import (
    _drain_crew_session_outboxes,
    _wire_crew_session_delivery,
)
from probos.startup.shutdown import _close_crew_session_delivery
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.substrate.registry import AgentRegistry
from probos.threads import ChatThread, ChatThreadStore
from probos.workforce import (
    CrewSessionAdmissionPort,
    CrewSessionParentCreate,
    WorkItem,
    WorkItemStore,
)

_SHA_A = "a" * 64
_CASE_IDS = itertools.count(1)


class _ManualClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.now


class _RuntimeEnvelopeRecorder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.nats_bus = None

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        ProbOSRuntime._emit_event(self, event_type, data)  # type: ignore[arg-type]

    def _check_night_order_escalation(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        return None

    def _emit_event_local(self, event: dict[str, Any], type_str: str) -> None:
        self.events.append(copy.deepcopy(event))


class _Ontology:
    def get_crew_agent_types(self) -> set[str]:
        return {"operations_officer"}


class _NoopDecomposer:
    def decompose(self, goal: str) -> list[Any]:
        raise AssertionError("existing-thread resume must not decompose")


class _RecordingConnection:
    def __init__(self, delegate: DatabaseConnection) -> None:
        self._delegate = delegate
        self.queries: list[tuple[str, Sequence[Any]]] = []
        self._execute_fault: tuple[str, BaseException] | None = None
        self._postcommit_fault: BaseException | None = None

    @property
    def row_factory(self) -> Any:
        return self._delegate.row_factory  # type: ignore[attr-defined]

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._delegate.row_factory = value  # type: ignore[attr-defined]

    def fail_next_execute_containing(
        self,
        fragment: str,
        error: BaseException,
    ) -> None:
        self._execute_fault = (fragment, error)

    def fail_after_next_commit(self, error: BaseException) -> None:
        self._postcommit_fault = error

    async def execute(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
    ) -> Any:
        self.queries.append((sql, parameters))
        fault = self._execute_fault
        if fault is not None and fault[0] in sql:
            self._execute_fault = None
            raise fault[1]
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
        fault = self._postcommit_fault
        if fault is not None:
            self._postcommit_fault = None
            raise fault

    async def close(self) -> None:
        await self._delegate.close()


class _RecordingConnectionFactory:
    def __init__(self) -> None:
        self._delegate: ConnectionFactory = SQLiteConnectionFactory()
        self.connection: _RecordingConnection | None = None

    async def connect(self, db_path: str) -> DatabaseConnection:
        connection = _RecordingConnection(
            await self._delegate.connect(db_path),
        )
        self.connection = connection
        return connection


class _ThreadLookupAdapter:
    def __init__(self, delegate: ChatThreadStore, missing_id: str) -> None:
        self._delegate = delegate
        self._missing_id = missing_id
        self.missing = True

    def get_thread(self, thread_id: str) -> ChatThread | None:
        if self.missing and thread_id == self._missing_id:
            return None
        return self._delegate.get_thread(thread_id)


class _MarkFaultAdapter:
    def __init__(self, delegate: WorkItemStore, mode: str) -> None:
        self._delegate = delegate
        self._mode = mode
        self.mark_calls = 0
        self.read_calls = 0
        self.read_completed = asyncio.Event()

    async def list_pending_crew_session_deliveries(
        self,
        *,
        limit: int,
        session_id: str | None = None,
        session_revision: int | None = None,
    ) -> tuple[CrewSessionDeliveryOutboxEntry, ...]:
        return await self._delegate.list_pending_crew_session_deliveries(
            limit=limit,
            session_id=session_id,
            session_revision=session_revision,
        )

    async def mark_crew_session_delivery_delivered(
        self,
        delivery_id: str,
        *,
        session_id: str,
        session_revision: int,
        outcome: CrewSessionDeliveryOutcome,
    ) -> bool | None:
        self.mark_calls += 1
        if self._mode == "pre_error":
            raise OSError("mark unavailable")
        result = await self._delegate.mark_crew_session_delivery_delivered(
            delivery_id,
            session_id=session_id,
            session_revision=session_revision,
            outcome=outcome,
        )
        if self._mode == "post_error":
            raise OSError("postcommit mark error")
        if self._mode == "post_cancel":
            raise asyncio.CancelledError("postcommit mark cancellation")
        if self._mode == "false":
            return False
        if self._mode == "none":
            return None
        return result

    async def get_exact_crew_session_delivery(
        self,
        record: CrewSessionDeliveryRecord,
        *,
        session_id: str,
        session_revision: int,
        outcome: CrewSessionDeliveryOutcome,
    ) -> CrewSessionDeliveryOutboxEntry | None:
        self.read_calls += 1
        entry = await self._delegate.get_exact_crew_session_delivery(
            record,
            session_id=session_id,
            session_revision=session_revision,
            outcome=outcome,
        )
        self.read_completed.set()
        return entry


class _MetricQueryAdapter:
    def __init__(
        self,
        delegate: WorkItemStore,
        transform: Callable[[tuple[WorkItem, ...], int], tuple[WorkItem, ...]],
    ) -> None:
        self._delegate = delegate
        self._transform = transform
        self.requested_limits: list[int] = []

    async def list_crew_session_metric_work_items(
        self,
        *,
        window_start: float,
        window_end: float,
        limit: int,
    ) -> tuple[WorkItem, ...]:
        self.requested_limits.append(limit)
        rows = await self._delegate.list_crew_session_metric_work_items(
            window_start=window_start,
            window_end=window_end,
            limit=limit,
        )
        return self._transform(rows, limit)


class _StrictLegacyPostCommitTransitionAdapter:
    def __init__(self, delegate: WorkItemStore) -> None:
        self._delegate = delegate
        self.merge_calls = 0

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        return await self._delegate.get_work_item(work_item_id)

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any] | None = None,
        expected_work_type: str | None = None,
        expected_status: str | None = None,
        expected_assigned_to: str | None = None,
        new_status: str | None = None,
        source: str = "system",
    ) -> WorkItem | None:
        self.merge_calls += 1
        committed = await self._delegate.merge_work_item_metadata(
            work_item_id,
            patch,
            expected=expected,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            new_status=new_status,
            source=source,
        )
        assert committed is not None
        raise OSError("strict legacy postcommit ambiguity")


class _BlockingMarkAdapter(_MarkFaultAdapter):
    def __init__(self, delegate: WorkItemStore) -> None:
        super().__init__(delegate, "normal")
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()

    async def mark_crew_session_delivery_delivered(
        self,
        delivery_id: str,
        *,
        session_id: str,
        session_revision: int,
        outcome: CrewSessionDeliveryOutcome,
    ) -> bool | None:
        self.entered.set()
        await self.release.wait()
        try:
            return await super().mark_crew_session_delivery_delivered(
                delivery_id,
                session_id=session_id,
                session_revision=session_revision,
                outcome=outcome,
            )
        finally:
            self.finished.set()


@dataclass
class _Harness:
    work_path: str
    work: WorkItemStore
    admission: CrewSessionAdmissionPort
    threads: ChatThreadStore
    clock: _ManualClock
    work_events: _RuntimeEnvelopeRecorder
    notification_events: list[tuple[str, dict[str, Any]]]
    queue: NotificationQueue
    delivery: CrewSessionDeliveryService
    service: CrewSessionService
    scheduled_tasks: set[asyncio.Task[Any]]
    connection: _RecordingConnection


@dataclass(frozen=True)
class _OutcomeCase:
    service: CrewSessionService
    contract: CrewSessionContract
    thread: ChatThread
    event: dict[str, Any]


@pytest.fixture
async def harness(tmp_path: Path) -> Any:
    work_path = str(tmp_path / "workforce.db")
    events = _RuntimeEnvelopeRecorder()
    connection_factory = _RecordingConnectionFactory()
    work = WorkItemStore(
        db_path=work_path,
        emit_event=events,
        tick_interval=1_000,
        connection_factory=connection_factory,
    )
    await work.start()
    assert connection_factory.connection is not None
    notification_events: list[tuple[str, dict[str, Any]]] = []
    queue = NotificationQueue(
        on_event=lambda event_type, data: notification_events.append(
            (event_type, copy.deepcopy(data)),
        ),
    )
    threads = ChatThreadStore(tmp_path / "threads.db")
    admission = work.claim_crew_session_admission_port()
    registry = AgentRegistry()
    for agent_id in ("facilitator-metrics", "producer-metrics"):
        await registry.register(SimpleNamespace(
            id=agent_id,
            agent_type="operations_officer",
            pool="operations",
        ))
    scheduled_tasks: set[asyncio.Task[Any]] = set()

    def _schedule(_parent_id: str) -> asyncio.Task[Any]:
        task = asyncio.create_task(asyncio.sleep(0))
        scheduled_tasks.add(task)
        task.add_done_callback(scheduled_tasks.discard)
        return task

    service_clock = _ManualClock()
    service = CrewSessionService(
        work_item_store=work,
        chat_thread_store=threads,
        registry=registry,
        ontology=_Ontology(),
        trust_network=TrustNetwork(),
        config=AgenticDispatchConfig(orchestrator_enabled=True),
        compute_similarity=lambda _left, _right: 0.0,
        decomposer=_NoopDecomposer(),
        admission_port=admission,
        clock=service_clock,
    )
    service.bind_scheduler(_schedule)
    value = _Harness(
        work_path=work_path,
        work=work,
        admission=admission,
        threads=threads,
        clock=service_clock,
        work_events=events,
        notification_events=notification_events,
        queue=queue,
        delivery=CrewSessionDeliveryService(
            outbox=work,
            thread_store=threads,
            notification_queue=queue,
        ),
        service=service,
        scheduled_tasks=scheduled_tasks,
        connection=connection_factory.connection,
    )
    try:
        yield value
    finally:
        if value.scheduled_tasks:
            await asyncio.gather(*tuple(value.scheduled_tasks))
        await value.work.stop()


def _status_event(
    events: list[dict[str, Any]],
    session_id: str,
) -> dict[str, Any]:
    for event in reversed(events):
        data = event.get("data")
        work_item = data.get("work_item") if type(data) is dict else None
        if (
            event.get("type") == "work_item_status_changed"
            and type(work_item) is dict
            and work_item.get("id") == session_id
        ):
            return copy.deepcopy(event)
    raise AssertionError(f"status event missing for {session_id}")


async def _new_session(
    value: _Harness,
    *,
    origin: str = "captain",
    originator_id: str = "captain",
    facilitator_id: str | None = None,
    created_at: float = 100.0,
    goal: str = "Deliver the requested result",
    expected_deliverable: str = "A verified report",
    owner_ids: list[str] | None = None,
) -> tuple[CrewSessionService, CrewSessionContract, ChatThread]:
    index = next(_CASE_IDS)
    session_id = f"session-{index}"
    facilitator = facilitator_id or f"facilitator-{index}"
    created_by = "captain" if origin == "captain" else originator_id
    owners = owner_ids or [facilitator, f"producer-{index}"]
    async with value.admission.reserve() as reservation:
        await reservation.create_parent(CrewSessionParentCreate(
            id=session_id,
            title=f"Crew session {index}",
            description="Produce one durable outcome",
            assigned_to=facilitator,
            created_by=created_by,
            metadata={},
            created_at=created_at,
        ))
    thread = value.threads.create_thread(
        title=f"Crew room {index}",
        participants=owners,
        task_id=session_id,
    )
    value.clock.now = created_at
    service = value.service
    contract = await service.initialize_session(
        session_id,
        thread.id,
        goal=goal,
        origin=origin,  # type: ignore[arg-type]
        originator_id=originator_id,
        facilitator_id=facilitator,
        owner_ids=owners,
        success_criteria=["The result is verified"],
        expected_deliverable=expected_deliverable,
    )
    return service, contract, thread


async def _make_outcome(
    value: _Harness,
    outcome: str,
    *,
    origin: str = "captain",
    originator_id: str = "captain",
    facilitator_id: str | None = None,
    created_at: float = 100.0,
    elapsed_seconds: float = 20.0,
    goal: str = "Deliver the requested result",
    expected_deliverable: str = "A verified report",
    owner_ids: list[str] | None = None,
    summary: str = "Verified result summary",
    blocked_reason: str = "Captain decision required",
    artifact_id: str = "artifact-final",
) -> _OutcomeCase:
    service, contract, thread = await _new_session(
        value,
        origin=origin,
        originator_id=originator_id,
        facilitator_id=facilitator_id,
        created_at=created_at,
        goal=goal,
        expected_deliverable=expected_deliverable,
        owner_ids=owner_ids,
    )
    if outcome == "blocked_needs_captain":
        value.clock.now = created_at + elapsed_seconds
        contract = await service.transition_session(
            contract.task_id,
            "blocked_needs_captain",
            expected_revision=contract.revision,
            blocked_reason=blocked_reason,
        )
    elif outcome == "failed":
        value.clock.now = created_at + elapsed_seconds
        contract = await service.transition_session(
            contract.task_id,
            "failed",
            expected_revision=contract.revision,
            last_result_summary=summary,
        )
    elif outcome == "done":
        value.clock.now = created_at + 2.0
        contract = await service.transition_session(
            contract.task_id,
            "executing",
            expected_revision=contract.revision,
        )
        value.clock.now = created_at + 3.0
        contract = await service.transition_session(
            contract.task_id,
            "verifying",
            expected_revision=contract.revision,
        )
        value.clock.now = created_at + elapsed_seconds
        contract = await service.transition_session(
            contract.task_id,
            "done",
            expected_revision=contract.revision,
            last_result_summary=summary,
            evidence_refs=[_SHA_A],
            result_artifact_id=artifact_id,
            result_ref=_SHA_A,
        )
    else:
        raise AssertionError(f"unsupported outcome {outcome}")
    return _OutcomeCase(
        service=service,
        contract=contract,
        thread=thread,
        event=_status_event(value.work_events.events, contract.task_id),
    )


async def _exact_delivery(
    work: WorkItemStore,
    record: CrewSessionDeliveryRecord,
) -> CrewSessionDeliveryOutboxEntry:
    entry = await work.get_exact_crew_session_delivery(
        record,
        session_id=record.session_id,
        session_revision=record.session_revision,
        outcome=record.outcome,
    )
    assert entry is not None
    return entry


async def _raw_delivery_payloads(
    connection: _RecordingConnection,
) -> list[str]:
    cursor = await connection.execute(
        "SELECT payload_json FROM crew_delivery_outbox ORDER BY delivery_id",
    )
    return [str(row[0]) for row in await cursor.fetchall()]


@pytest.mark.parametrize(
    ("outcome", "notification_type", "title"),
    [
        ("done", "info", "Crew session completed"),
        ("failed", "error", "Crew session failed"),
        (
            "blocked_needs_captain",
            "action_required",
            "Crew session needs Captain input",
        ),
    ],
)
async def test_captain_outcome_commits_one_fixed_room_notification(
    harness: _Harness,
    outcome: str,
    notification_type: str,
    title: str,
) -> None:
    case = await _make_outcome(harness, outcome)
    pending = await harness.work.list_pending_crew_session_deliveries(
        limit=10,
        session_id=case.contract.task_id,
    )
    assert len(pending) == 1
    assert pending[0].record.ownership == "captain"
    assert pending[0].record.author_id == case.contract.facilitator_id

    assert await harness.delivery.on_status_changed(case.event) == 1

    notification = harness.queue.snapshot()[0]
    assert notification["id"] == pending[0].record.delivery_id
    assert notification["agent_id"] == case.contract.facilitator_id
    assert notification["agent_type"] == "crew_session"
    assert notification["department"] == "operations"
    assert notification["notification_type"] == notification_type
    assert notification["title"] == title
    assert notification["detail"] == "Open the existing crew room for details."
    assert notification["action_url"] == f"thread:{case.thread.id}"
    assert notification["suggested_action"] is None
    authoritative = await _exact_delivery(harness.work, pending[0].record)
    assert authoritative.delivered is True


async def test_agent_outcome_uses_exact_originator_not_owner_order(
    harness: _Harness,
) -> None:
    case = await _make_outcome(
        harness,
        "failed",
        origin="agent",
        originator_id="agent-originator",
        facilitator_id="facilitator-agent-case",
        owner_ids=["roster-first", "facilitator-agent-case", "agent-originator"],
    )
    pending = await harness.work.list_pending_crew_session_deliveries(
        limit=10,
        session_id=case.contract.task_id,
    )
    assert len(pending) == 1

    assert await harness.delivery.on_status_changed(case.event) == 1

    row = (await _exact_delivery(harness.work, pending[0].record)).record
    notification = harness.queue.snapshot()[0]
    assert row.ownership == "self"
    assert row.originator_id == row.author_id == "agent-originator"
    assert notification["agent_id"] == "agent-originator"


async def test_block_resume_done_and_concurrent_events_keep_two_identities(
    harness: _Harness,
) -> None:
    blocked = await _make_outcome(
        harness,
        "blocked_needs_captain",
        elapsed_seconds=10.0,
    )
    blocked_pending = await harness.work.list_pending_crew_session_deliveries(
        limit=10,
        session_id=blocked.contract.task_id,
    )
    assert len(blocked_pending) == 1
    assert await harness.delivery.on_status_changed(blocked.event) == 1
    contract = blocked.contract
    harness.clock.now = contract.created_at + 11.0
    contract = await blocked.service.transition_session(
        contract.task_id,
        "discussing",
        expected_revision=contract.revision,
    )
    harness.clock.now = contract.created_at + 12.0
    contract = await blocked.service.transition_session(
        contract.task_id,
        "executing",
        expected_revision=contract.revision,
    )
    harness.clock.now = contract.created_at + 13.0
    contract = await blocked.service.transition_session(
        contract.task_id,
        "verifying",
        expected_revision=contract.revision,
    )
    harness.clock.now = contract.created_at + 20.0
    contract = await blocked.service.transition_session(
        contract.task_id,
        "done",
        expected_revision=contract.revision,
        last_result_summary="resumed result",
        evidence_refs=[_SHA_A],
        result_artifact_id="artifact-resumed",
        result_ref=_SHA_A,
    )
    done_event = _status_event(harness.work_events.events, contract.task_id)
    done_pending = await harness.work.list_pending_crew_session_deliveries(
        limit=10,
        session_id=contract.task_id,
    )
    assert len(done_pending) == 1

    results = await asyncio.gather(
        harness.delivery.on_status_changed(done_event),
        harness.delivery.on_status_changed(done_event),
        harness.delivery.on_status_changed(blocked.event),
    )

    rows = [
        await _exact_delivery(harness.work, blocked_pending[0].record),
        await _exact_delivery(harness.work, done_pending[0].record),
    ]
    assert len(rows) == 2
    assert {row.record.outcome for row in rows} == {
        "blocked_needs_captain",
        "done",
    }
    assert len({row.record.delivery_id for row in rows}) == 2
    assert len({row.record.session_revision for row in rows}) == 2
    assert len(harness.queue.snapshot()) == 2
    assert sum(results) >= 1
    notification_events = [
        item for item in harness.notification_events if item[0] == "notification"
    ]
    assert len(notification_events) == 2


async def test_crew_session_events_are_minimal_and_sentinel_free(
    harness: _Harness,
) -> None:
    case = await _make_outcome(harness, "failed")
    relevant_types = {
        "work_item_created",
        "work_item_updated",
        "work_item_status_changed",
    }
    projected = []
    for event in harness.work_events.events:
        data = event.get("data")
        item = data.get("work_item") if type(data) is dict else None
        if (
            event.get("type") in relevant_types
            and type(item) is dict
            and item.get("id") == case.contract.task_id
        ):
            projected.append(item)
            assert item == {
                "id": case.contract.task_id,
                "work_type": "crew_session",
                "status": item["status"],
            }
            assert "sentinel" not in json.dumps(item)
    assert projected
    assert {event["type"] for event in harness.work_events.events if (
        type(event.get("data")) is dict
        and type(event["data"].get("work_item")) is dict
        and event["data"]["work_item"].get("id") == case.contract.task_id
    )} >= relevant_types
    assert case.event["type"] == "work_item_status_changed"
    assert type(case.event["data"]["work_item"]) is dict
    tampered = copy.deepcopy(case.event)
    tampered["data"]["new_status"] = "done"
    tampered["data"]["work_item"]["status"] = "done"
    tampered["data"]["work_item"]["metadata"] = {
        "crew_session": {
            "revision": True,
            "state": "done",
            "last_result_summary": "tampered-result-sentinel",
        },
    }

    assert await harness.delivery.on_status_changed(tampered) == 1

    notification = harness.queue.snapshot()[0]
    assert notification["title"] == "Crew session failed"
    assert "tampered" not in json.dumps(notification)
    assert await harness.delivery.on_status_changed({"data": {}}) == 0


@pytest.mark.parametrize("room_state", ["missing", "archived", "mismatched"])
async def test_invalid_room_stays_pending_until_existing_room_is_repaired(
    harness: _Harness,
    room_state: str,
) -> None:
    case = await _make_outcome(harness, "blocked_needs_captain")
    before_count = len(harness.threads.list_threads(include_archived=True))
    delivery = harness.delivery
    missing_adapter: _ThreadLookupAdapter | None = None
    if room_state == "missing":
        missing_adapter = _ThreadLookupAdapter(harness.threads, case.thread.id)
        delivery = CrewSessionDeliveryService(
            outbox=harness.work,
            thread_store=missing_adapter,
            notification_queue=harness.queue,
        )
    elif room_state == "archived":
        assert harness.threads.update_thread(case.thread.id, archived=True) is not None
    else:
        assert harness.threads.update_thread(
            case.thread.id,
            task_id="different-session",
        ) is not None

    assert await delivery.drain_pending(
        session_id=case.contract.task_id,
    ) == 0
    assert harness.queue.snapshot() == []
    assert len(await harness.work.list_pending_crew_session_deliveries(
        limit=10,
        session_id=case.contract.task_id,
    )) == 1

    if missing_adapter is not None:
        missing_adapter.missing = False
    elif room_state == "archived":
        assert harness.threads.update_thread(case.thread.id, archived=False) is not None
    else:
        assert harness.threads.update_thread(
            case.thread.id,
            task_id=case.contract.task_id,
        ) is not None

    assert await delivery.drain_pending(
        session_id=case.contract.task_id,
    ) == 1
    assert await delivery.drain_pending(
        session_id=case.contract.task_id,
    ) == 0
    assert len(harness.queue.snapshot()) == 1
    assert len(harness.threads.list_threads(include_archived=True)) == before_count


async def test_queue_failure_leaves_pending_and_retry_delivers_once(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await _make_outcome(harness, "blocked_needs_captain")
    original = harness.queue.notify_once

    def fail_queue(record: CrewSessionDeliveryRecord) -> Any:
        raise OSError("queue unavailable")

    monkeypatch.setattr(harness.queue, "notify_once", fail_queue)
    assert await harness.delivery.drain_pending(
        session_id=case.contract.task_id,
    ) == 0
    assert harness.queue.snapshot() == []
    monkeypatch.setattr(harness.queue, "notify_once", original)
    assert await harness.delivery.drain_pending(
        session_id=case.contract.task_id,
    ) == 1
    assert len(harness.queue.snapshot()) == 1


async def test_notify_once_callback_failure_retains_one_logical_queue_entry(
    harness: _Harness,
) -> None:
    case = await _make_outcome(harness, "failed")
    events: list[tuple[str, dict[str, Any]]] = []
    armed = True

    def _callback(event_type: str, data: dict[str, Any]) -> None:
        nonlocal armed
        events.append((event_type, copy.deepcopy(data)))
        if armed:
            armed = False
            raise OSError("callback failed after insertion")

    queue = NotificationQueue(on_event=_callback)
    service = CrewSessionDeliveryService(
        outbox=harness.work,
        thread_store=harness.threads,
        notification_queue=queue,
    )
    pending = await harness.work.list_pending_crew_session_deliveries(
        limit=2,
        session_id=case.contract.task_id,
    )
    assert len(pending) == 1

    assert await service.drain_pending(session_id=case.contract.task_id) == 0
    assert len(queue.snapshot()) == 1
    assert len(events) == 1
    assert await service.drain_pending(session_id=case.contract.task_id) == 1
    assert len(queue.snapshot()) == 1
    assert len(events) == 1
    authoritative = await _exact_delivery(harness.work, pending[0].record)
    assert authoritative.delivered is True


async def test_mark_precommit_error_stays_pending_and_retry_is_replay_safe(
    harness: _Harness,
) -> None:
    failed = await _make_outcome(harness, "failed")
    adapter = _MarkFaultAdapter(harness.work, "pre_error")
    service = CrewSessionDeliveryService(
        outbox=adapter,
        thread_store=harness.threads,
        notification_queue=harness.queue,
    )
    assert await service.drain_pending(
        session_id=failed.contract.task_id,
    ) == 0
    assert adapter.mark_calls == adapter.read_calls == 1
    assert len(harness.queue.snapshot()) == 1
    first_event_count = len(harness.notification_events)
    assert await harness.delivery.drain_pending(
        session_id=failed.contract.task_id,
    ) == 1
    assert len(harness.notification_events) == first_event_count


async def test_delivery_mark_postcommit_error_reconciles_authoritative_ack(
    harness: _Harness,
) -> None:
    case = await _make_outcome(harness, "failed")
    adapter = _MarkFaultAdapter(harness.work, "post_error")
    service = CrewSessionDeliveryService(
        outbox=adapter,
        thread_store=harness.threads,
        notification_queue=harness.queue,
    )
    pending = await harness.work.list_pending_crew_session_deliveries(
        limit=2,
        session_id=case.contract.task_id,
    )
    assert len(pending) == 1

    assert await service.drain_pending(
        session_id=case.contract.task_id,
    ) == 1
    assert adapter.mark_calls == adapter.read_calls == 1
    assert adapter.read_completed.is_set()
    assert (await _exact_delivery(harness.work, pending[0].record)).delivered is True
    assert len(harness.queue.snapshot()) == 1
    assert len(harness.notification_events) == 1


async def test_delivery_mark_postcommit_cancellation_propagates_without_duplicate(
    harness: _Harness,
) -> None:
    case = await _make_outcome(harness, "blocked_needs_captain")
    adapter = _MarkFaultAdapter(harness.work, "post_cancel")
    service = CrewSessionDeliveryService(
        outbox=adapter,
        thread_store=harness.threads,
        notification_queue=harness.queue,
    )
    pending = await harness.work.list_pending_crew_session_deliveries(
        limit=2,
        session_id=case.contract.task_id,
    )
    assert len(pending) == 1

    with pytest.raises(
        asyncio.CancelledError,
        match="postcommit mark cancellation",
    ):
        await service.drain_pending(session_id=case.contract.task_id)

    assert adapter.mark_calls == adapter.read_calls == 1
    assert adapter.read_completed.is_set()
    assert (await _exact_delivery(harness.work, pending[0].record)).delivered is True
    event_count = len(harness.notification_events)
    assert len(harness.queue.snapshot()) == 1
    assert await service.drain_pending(session_id=case.contract.task_id) == 0
    assert len(harness.queue.snapshot()) == 1
    assert len(harness.notification_events) == event_count


@pytest.mark.parametrize("mode", ["normal", "false", "none"])
async def test_delivery_mark_return_reconciles_exact_authority(
    harness: _Harness,
    mode: str,
) -> None:
    case = await _make_outcome(harness, "failed")
    adapter = _MarkFaultAdapter(harness.work, mode)
    service = CrewSessionDeliveryService(
        outbox=adapter,
        thread_store=harness.threads,
        notification_queue=harness.queue,
    )

    assert await service.drain_pending(session_id=case.contract.task_id) == 1
    assert adapter.mark_calls == adapter.read_calls == 1
    assert len(harness.queue.snapshot()) == 1


async def test_nonterminal_postcommit_ambiguity_reconciles_with_strict_legacy_adapter(
    harness: _Harness,
) -> None:
    service, contract, _thread = await _new_session(harness)
    adapter = _StrictLegacyPostCommitTransitionAdapter(harness.work)
    service._work_items = adapter  # type: ignore[assignment]

    harness.clock.now = contract.created_at + 10.0
    authoritative = await service.transition_session(
        contract.task_id,
        "executing",
        expected_revision=contract.revision,
    )

    assert adapter.merge_calls == 1
    assert authoritative.state == "executing"
    assert authoritative.revision == contract.revision + 1
    persisted = await harness.work.get_work_item(contract.task_id)
    assert persisted is not None
    assert persisted.status == "in_progress"
    assert persisted.assigned_to == contract.facilitator_id
    assert persisted.metadata["crew_session"] == authoritative.model_dump(mode="json")
    assert await harness.work.list_pending_crew_session_deliveries(limit=10) == ()


async def test_precommit_cancellation_and_delivery_insert_failure_roll_back(
    harness: _Harness,
) -> None:
    service, contract, _thread = await _new_session(harness)
    harness.connection.fail_next_execute_containing(
        "UPDATE work_items SET metadata = ?, status = ?",
        asyncio.CancelledError("cancel before outcome"),
    )
    harness.clock.now = contract.created_at + 10.0
    with pytest.raises(asyncio.CancelledError, match="cancel before outcome"):
        await service.transition_session(
            contract.task_id,
            "blocked_needs_captain",
            expected_revision=contract.revision,
            blocked_reason="need input",
        )
    authoritative = await service.get_session(contract.task_id)
    assert authoritative is not None and authoritative.state == "discussing"
    assert await harness.work.list_pending_crew_session_deliveries(limit=10) == ()

    service, contract, _thread = await _new_session(harness)

    harness.connection.fail_next_execute_containing(
        "INSERT INTO crew_delivery_outbox",
        OSError("delivery insert failed"),
    )
    harness.clock.now = contract.created_at + 20.0
    with pytest.raises(OSError, match="delivery insert failed"):
        await service.transition_session(
            contract.task_id,
            "failed",
            expected_revision=contract.revision,
            last_result_summary="failed candidate",
        )
    authoritative = await service.get_session(contract.task_id)
    assert authoritative is not None and authoritative.state == "discussing"
    assert await harness.work.list_pending_crew_session_deliveries(limit=10) == ()


async def test_postcommit_cancellation_requires_exact_row_and_stays_pending(
    harness: _Harness,
) -> None:
    service, contract, thread = await _new_session(harness)
    harness.connection.fail_after_next_commit(
        asyncio.CancelledError("cancel after outcome commit"),
    )
    harness.clock.now = contract.created_at + 10.0
    with pytest.raises(asyncio.CancelledError, match="cancel after outcome commit"):
        await service.transition_session(
            contract.task_id,
            "blocked_needs_captain",
            expected_revision=contract.revision,
            blocked_reason="need input",
        )
    authoritative = await service.get_session(contract.task_id)
    assert authoritative is not None and authoritative.state == "blocked_needs_captain"
    pending = await harness.work.list_pending_crew_session_deliveries(
        limit=10,
        session_id=contract.task_id,
    )
    assert len(pending) == 1
    assert pending[0].record.thread_id == thread.id
    assert harness.queue.snapshot() == []
    assert await harness.delivery.drain_pending(
        session_id=contract.task_id,
    ) == 1


async def test_pending_restart_replays_same_id_once_and_delivered_stays_silent(
    harness: _Harness,
) -> None:
    case = await _make_outcome(harness, "failed")
    pending = await harness.work.list_pending_crew_session_deliveries(
        limit=10,
        session_id=case.contract.task_id,
    )
    delivery_id = pending[0].record.delivery_id
    await harness.work.stop()

    restarted = WorkItemStore(
        db_path=harness.work_path,
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await restarted.start()
    harness.work = restarted
    first_queue = NotificationQueue()
    first_service = CrewSessionDeliveryService(
        outbox=restarted,
        thread_store=harness.threads,
        notification_queue=first_queue,
    )
    assert await first_service.drain_pending() == 1
    assert first_queue.snapshot()[0]["id"] == delivery_id
    await restarted.stop()

    second = WorkItemStore(
        db_path=harness.work_path,
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await second.start()
    harness.work = second
    second_queue = NotificationQueue()
    second_service = CrewSessionDeliveryService(
        outbox=second,
        thread_store=harness.threads,
        notification_queue=second_queue,
    )
    assert await second_service.drain_pending() == 0
    assert second_queue.snapshot() == []


async def test_metrics_real_19_session_fixture_reports_zero_completion_and_six_resumes(
    harness: _Harness,
) -> None:
    await _make_outcome(
        harness,
        "failed",
        created_at=1.0,
        elapsed_seconds=1.0,
        facilitator_id="facilitator-metrics",
        owner_ids=["facilitator-metrics", "producer-metrics"],
    )
    sessions: list[tuple[CrewSessionContract, ChatThread]] = []
    for index in range(19):
        _service, contract, thread = await _new_session(
            harness,
            created_at=150_000.0 + index,
            facilitator_id="facilitator-metrics",
            owner_ids=["facilitator-metrics", "producer-metrics"],
            goal=f"Produce metric report {index}",
            expected_deliverable=f"Metric report {index}",
        )
        sessions.append((contract, thread))
    principal = harness.service.captain_principal()
    for contract, thread in sessions[:6]:
        result = await harness.service.open_or_resume(
            principal=principal,
            goal=contract.goal,
            success_criteria=list(contract.success_criteria),
            expected_deliverable=contract.expected_deliverable,
            facilitator_id="facilitator-metrics",
            owner_ids=["facilitator-metrics", "producer-metrics"],
            requested_thread_id=thread.id,
        )
        assert result.disposition == "resumed"

    harness.clock.now = 200_000.0
    clock_calls = harness.clock.calls
    query_start = len(harness.connection.queries)
    metrics = await harness.service.metrics(days=1, limit=1000)

    assert metrics == CrewSessionMetrics(
        days=1,
        limit=1000,
        window_start=113_600.0,
        window_end=200_000.0,
        sessions_started=19,
        truncated=False,
        done_count=0,
        failed_count=0,
        artifact_count=0,
        verified_count=0,
        done_rate=0.0,
        failed_rate=0.0,
        artifact_rate=0.0,
        verified_rate=0.0,
        duplicate_resume_count=6,
        time_to_first_result_p50_seconds=0.0,
        time_to_first_result_p95_seconds=0.0,
        blocked_duration_seconds=0.0,
    )
    assert harness.clock.calls == clock_calls + 1
    metric_sql = "\n".join(
        sql for sql, _parameters in harness.connection.queries[query_start:]
    )
    assert "FROM work_items WHERE work_type = 'crew_session'" in metric_sql
    assert "crew_delivery_outbox" not in metric_sql
    assert "crew_trust_outbox" not in metric_sql


async def test_metrics_session_window_boundaries_and_nearest_rank_percentiles(
    harness: _Harness,
) -> None:
    window_end = 200_000.0
    window_start = 113_600.0
    _outside_service, outside, _outside_thread = await _new_session(
        harness,
        created_at=window_start - 0.001,
        goal="Outside metric window",
    )
    _boundary_service, boundary, _boundary_thread = await _new_session(
        harness,
        created_at=window_start,
        goal="Start boundary",
    )
    _end_service, end, _end_thread = await _new_session(
        harness,
        created_at=window_end,
        goal="End boundary",
    )
    terminal_cases = [
        await _make_outcome(harness, "done", created_at=190_000.0, elapsed_seconds=10.0),
        await _make_outcome(harness, "failed", created_at=190_000.0, elapsed_seconds=20.0),
        await _make_outcome(harness, "done", created_at=170_000.0, elapsed_seconds=30.0),
        await _make_outcome(harness, "failed", created_at=160_000.0, elapsed_seconds=40.0),
        await _make_outcome(harness, "done", created_at=150_000.0, elapsed_seconds=50.0),
    ]
    service, accumulated, _thread = await _new_session(
        harness,
        created_at=180_000.0,
        goal="Accumulated blocked duration",
    )
    harness.clock.now = 180_010.0
    accumulated = await service.transition_session(
        accumulated.task_id,
        "blocked_needs_captain",
        expected_revision=accumulated.revision,
        blocked_reason="Captain decision required",
    )
    harness.clock.now = 180_020.0
    accumulated = await service.transition_session(
        accumulated.task_id,
        "discussing",
        expected_revision=accumulated.revision,
    )
    service, current_blocked, _thread = await _new_session(
        harness,
        created_at=199_900.0,
        goal="Current blocked duration",
    )
    harness.clock.now = 199_930.0
    current_blocked = await service.transition_session(
        current_blocked.task_id,
        "blocked_needs_captain",
        expected_revision=current_blocked.revision,
        blocked_reason="Captain decision required",
    )

    harness.clock.now = window_end
    clock_calls = harness.clock.calls
    metrics = await harness.service.metrics(days=1, limit=100)
    assert harness.clock.calls == clock_calls + 1
    assert metrics.sessions_started == 9
    assert metrics.done_count == 3
    assert metrics.failed_count == 2
    assert metrics.artifact_count == metrics.verified_count == 3
    assert metrics.done_rate == 0.333333
    assert metrics.failed_rate == 0.222222
    assert metrics.artifact_rate == metrics.verified_rate == 0.333333
    assert metrics.time_to_first_result_p50_seconds == 30.0
    assert metrics.time_to_first_result_p95_seconds == 50.0
    assert metrics.blocked_duration_seconds == 80.0
    assert metrics.duplicate_resume_count == 0

    rows = await harness.work.list_crew_session_metric_work_items(
        window_start=window_start,
        window_end=window_end,
        limit=100,
    )
    row_ids = {row.id for row in rows}
    assert outside.task_id not in row_ids
    assert boundary.task_id in row_ids
    assert end.task_id in row_ids
    assert [(row.created_at, row.id) for row in rows] == sorted(
        ((row.created_at, row.id) for row in rows),
        reverse=True,
    )
    tie_ids = [
        row.id for row in rows if row.created_at == 190_000.0
    ]
    assert tie_ids == sorted(
        (terminal_cases[0].contract.task_id, terminal_cases[1].contract.task_id),
        reverse=True,
    )

    query_start = len(harness.connection.queries)
    truncated = await harness.service.metrics(days=1, limit=1)
    assert truncated.sessions_started == 1
    assert truncated.truncated is True
    metric_queries = [
        (sql, parameters)
        for sql, parameters in harness.connection.queries[query_start:]
        if "FROM work_items WHERE work_type = 'crew_session'" in sql
    ]
    assert len(metric_queries) == 1
    assert tuple(metric_queries[0][1]) == (window_start, window_end, 2)


async def test_metrics_empty_and_one_row_windows_are_zero_safe(
    harness: _Harness,
) -> None:
    harness.clock.now = 100_000.0
    empty = await harness.service.metrics(days=1, limit=10)
    assert empty.sessions_started == 0
    assert empty.truncated is False
    assert empty.done_count == empty.failed_count == 0
    assert empty.artifact_count == empty.verified_count == 0
    assert empty.duplicate_resume_count == 0
    assert empty.done_rate == empty.failed_rate == 0.0
    assert empty.artifact_rate == empty.verified_rate == 0.0
    assert empty.time_to_first_result_p50_seconds == 0.0
    assert empty.time_to_first_result_p95_seconds == 0.0
    assert empty.blocked_duration_seconds == 0.0

    await _new_session(harness, created_at=99_999.0)
    one = await harness.service.metrics(days=1, limit=10)
    assert one.sessions_started == 1
    assert one.done_rate == one.failed_rate == 0.0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"days": True}, "crew_session_metrics_days_invalid"),
        ({"days": None}, "crew_session_metrics_days_invalid"),
        ({"days": 0}, "crew_session_metrics_days_invalid"),
        ({"days": 366}, "crew_session_metrics_days_invalid"),
        ({"limit": False}, "crew_session_metrics_limit_invalid"),
        ({"limit": None}, "crew_session_metrics_limit_invalid"),
        ({"limit": 0}, "crew_session_metrics_limit_invalid"),
        ({"limit": 10_001}, "crew_session_metrics_limit_invalid"),
    ],
)
async def test_metrics_rejects_invalid_bounds(
    harness: _Harness,
    kwargs: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        await harness.service.metrics(**kwargs)


@pytest.mark.parametrize("clock", [True, None, float("nan"), float("inf"), -1.0])
async def test_metrics_rejects_invalid_captured_clock(
    harness: _Harness,
    clock: Any,
) -> None:
    harness.clock.now = clock
    with pytest.raises(ValueError, match="crew_session_metrics_clock_invalid"):
        await harness.service.metrics()


async def test_metrics_malformed_bool_alias_rejects_without_skipping(
    harness: _Harness,
) -> None:
    _service, malformed, _thread = await _new_session(
        harness,
        created_at=100.0,
        goal="Malformed metric row",
    )
    await _new_session(harness, created_at=99.0, goal="Valid metric row")
    parent = await harness.work.get_work_item(malformed.task_id)
    assert parent is not None
    metadata = copy.deepcopy(parent.metadata)
    metadata["crew_session"]["revision"] = True
    await harness.connection.execute(
        "UPDATE work_items SET metadata = ? WHERE id = ?",
        (
            json.dumps(metadata, sort_keys=True, separators=(",", ":")),
            malformed.task_id,
        ),
    )
    await harness.connection.commit()
    harness.clock.now = 200.0

    with pytest.raises(ValueError, match="crew_session_metrics_contract_invalid"):
        await harness.service.metrics(days=1, limit=10)


@pytest.mark.parametrize("fault", ["projection", "order", "over_return"])
async def test_metrics_rejects_query_contract_faults(
    harness: _Harness,
    fault: str,
) -> None:
    await _new_session(harness, created_at=100.0, goal="Metric row A")
    await _new_session(harness, created_at=99.0, goal="Metric row B")
    harness.clock.now = 200.0

    def _transform(
        rows: tuple[WorkItem, ...],
        requested_limit: int,
    ) -> tuple[WorkItem, ...]:
        assert rows
        if fault == "projection":
            return (replace(rows[0], status="failed"), *rows[1:])
        if fault == "order":
            return tuple(reversed(rows))
        return (*rows, *(rows[0] for _ in range(requested_limit + 1)))

    adapter = _MetricQueryAdapter(harness.work, _transform)
    service = CrewSessionService(
        work_item_store=adapter,  # type: ignore[arg-type]
        chat_thread_store=harness.threads,
        clock=harness.clock,
    )
    expected = {
        "projection": "crew_session_metrics_projection_invalid",
        "order": "crew_session_metrics_order_invalid",
        "over_return": "crew_session_metrics_query_invalid",
    }[fault]
    with pytest.raises(ValueError, match=expected):
        await service.metrics(days=1, limit=1)
    assert adapter.requested_limits == [2]


async def test_metrics_live_block_clock_regression_is_rejected(
    harness: _Harness,
) -> None:
    service, contract, _thread = await _new_session(harness, created_at=100.0)
    harness.clock.now = 200.0
    await service.transition_session(
        contract.task_id,
        "blocked_needs_captain",
        expected_revision=contract.revision,
        blocked_reason="Captain decision required",
    )
    harness.clock.now = 150.0

    with pytest.raises(ValueError, match="crew_session_metrics_clock_regression"):
        await harness.service.metrics(days=1, limit=10)


async def test_exact_delivery_reread_rejects_bool_alias_corruption(
    harness: _Harness,
) -> None:
    case = await _make_outcome(harness, "failed")
    pending = await harness.work.list_pending_crew_session_deliveries(
        limit=2,
        session_id=case.contract.task_id,
    )
    assert len(pending) == 1
    payload = pending[0].record.to_payload()
    payload["session_revision"] = True
    await harness.connection.execute(
        "UPDATE crew_delivery_outbox SET payload_json = ? WHERE delivery_id = ?",
        (
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            pending[0].record.delivery_id,
        ),
    )
    await harness.connection.commit()

    with pytest.raises(ValueError, match="crew_delivery_outbox_corrupt"):
        await _exact_delivery(harness.work, pending[0].record)


async def test_sensitive_contract_content_never_reaches_delivery_surfaces(
    harness: _Harness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinels = (
        "secret-goal-sentinel",
        "secret-result-sentinel",
        "secret-file-sentinel.docx",
        "secret-artifact-sentinel",
        "secret-blocked-reason-sentinel",
        "secret-roster-sentinel",
    )
    with caplog.at_level(logging.DEBUG, logger="probos.crew_session_delivery"):
        case = await _make_outcome(
            harness,
            "done",
            goal=sentinels[0],
            expected_deliverable=sentinels[2],
            summary=sentinels[1],
            artifact_id=sentinels[3],
            facilitator_id="facilitator-privacy",
            owner_ids=["facilitator-privacy", sentinels[5]],
        )
        assert await harness.delivery.on_status_changed(case.event) == 1
        blocked = await _make_outcome(
            harness,
            "blocked_needs_captain",
            blocked_reason=sentinels[4],
        )
        assert await harness.delivery.on_status_changed(blocked.event) == 1
        harness.clock.now = 1_000.0
        metrics = await harness.service.metrics(days=30, limit=10)
    surfaces = "\n".join([
        *await _raw_delivery_payloads(harness.connection),
        json.dumps(harness.queue.snapshot(), sort_keys=True),
        json.dumps(harness.notification_events, sort_keys=True),
        repr(metrics),
        caplog.text,
    ])
    for sentinel in sentinels:
        assert sentinel not in surfaces


class _WireRuntime:
    def __init__(self, value: _Harness) -> None:
        self.work_item_store = value.work
        self.chat_thread_store = value.threads
        self.notification_queue = NotificationQueue()
        self.crew_session_delivery_service: CrewSessionDeliveryService | None = None
        self.crew_session_delivery_listener: Callable[..., Any] | None = None
        self.listeners: list[tuple[Callable[..., Any], tuple[str, ...]]] = []

    def add_event_listener(
        self,
        callback: Callable[..., Any],
        event_types: list[str],
    ) -> None:
        self.listeners.append((callback, tuple(event_types)))

    def remove_event_listener(self, callback: Callable[..., Any]) -> None:
        self.listeners = [item for item in self.listeners if item[0] is not callback]


async def test_wiring_is_idempotent_and_listener_uses_real_service(
    harness: _Harness,
) -> None:
    case = await _make_outcome(harness, "blocked_needs_captain")
    runtime = _WireRuntime(harness)
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True

    assert _wire_crew_session_delivery(runtime=runtime, config=config) is True
    assert _wire_crew_session_delivery(runtime=runtime, config=config) is True
    assert len(runtime.listeners) == 1
    assert runtime.listeners[0][1] == ("work_item_status_changed",)
    runtime.listeners[0][0](case.event)
    assert runtime.crew_session_delivery_service is not None
    await runtime.crew_session_delivery_service.close()
    assert len(runtime.notification_queue.snapshot()) == 1


class _DrainProbe:
    def __init__(
        self,
        name: str,
        order: list[str],
        error: BaseException | None = None,
    ) -> None:
        self.name = name
        self.order = order
        self.error = error
        self.calls = 0

    async def drain_pending(self) -> int:
        self.calls += 1
        self.order.append(self.name)
        if self.error is not None:
            raise self.error
        return 1


@pytest.mark.parametrize(
    ("trust_error", "delivery_error", "expected"),
    [
        (
            OSError("trust ordinary"),
            asyncio.CancelledError("delivery cancelled"),
            "delivery cancelled",
        ),
        (
            asyncio.CancelledError("trust cancelled"),
            OSError("delivery ordinary"),
            "trust cancelled",
        ),
        (
            OSError("trust first"),
            OSError("delivery second"),
            "trust first",
        ),
        (
            asyncio.CancelledError("trust first cancellation"),
            asyncio.CancelledError("delivery second cancellation"),
            "trust first cancellation",
        ),
    ],
)
async def test_startup_dual_drain_never_masks_cancellation(
    trust_error: BaseException,
    delivery_error: BaseException,
    expected: str,
) -> None:
    order: list[str] = []
    trust = _DrainProbe("trust", order, trust_error)
    delivery = _DrainProbe("delivery", order, delivery_error)
    runtime = SimpleNamespace(
        crew_session_trust_recorder=trust,
        crew_session_delivery_service=delivery,
    )

    expected_type = (
        asyncio.CancelledError
        if isinstance(trust_error, asyncio.CancelledError)
        or isinstance(delivery_error, asyncio.CancelledError)
        else OSError
    )
    with pytest.raises(expected_type, match=expected):
        await _drain_crew_session_outboxes(runtime)

    assert trust.calls == delivery.calls == 1
    assert order == ["trust", "delivery"]


async def test_delivery_shutdown_waits_for_inflight_drain_before_store_close(
    harness: _Harness,
) -> None:
    case = await _make_outcome(harness, "failed")
    adapter = _BlockingMarkAdapter(harness.work)
    queue = NotificationQueue()
    service = CrewSessionDeliveryService(
        outbox=adapter,
        thread_store=harness.threads,
        notification_queue=queue,
    )
    listener = service.admit_status_changed
    listeners = [listener]
    order: list[str] = []

    class _StopStore:
        async def stop(self) -> None:
            assert adapter.finished.is_set()
            assert runtime.crew_session_delivery_service is None
            order.append("store_stop")
            await harness.work.stop()

    def _remove_listener(callback: Callable[..., Any]) -> None:
        listeners.remove(callback)

    runtime = SimpleNamespace(
        crew_session_delivery_service=service,
        crew_session_delivery_listener=listener,
        remove_event_listener=_remove_listener,
        work_item_store=_StopStore(),
    )
    assert listener(case.event) is True
    await adapter.entered.wait()

    async def _production_shutdown_slice() -> None:
        await _close_crew_session_delivery(runtime)
        order.append("service_close")
        await runtime.work_item_store.stop()

    stopping = asyncio.create_task(_production_shutdown_slice())
    await asyncio.sleep(0)
    assert listeners == []
    assert listener(case.event) is False
    assert adapter.mark_calls == 0
    assert stopping.done() is False

    adapter.release.set()
    await stopping
    assert adapter.mark_calls == adapter.read_calls == 1
    assert order == ["service_close", "store_stop"]
    assert len(queue.snapshot()) == 1


async def test_delivery_close_preserves_first_cancellation_after_inflight_drain(
    harness: _Harness,
) -> None:
    case = await _make_outcome(harness, "failed")
    adapter = _BlockingMarkAdapter(harness.work)
    service = CrewSessionDeliveryService(
        outbox=adapter,
        thread_store=harness.threads,
        notification_queue=NotificationQueue(),
    )
    assert service.admit_status_changed(case.event) is True
    await adapter.entered.wait()

    closing = asyncio.create_task(service.close())
    await asyncio.sleep(0)
    assert service.admit_status_changed(case.event) is False
    closing.cancel("first close cancellation")
    await asyncio.sleep(0)
    closing.cancel("second close cancellation")
    await asyncio.sleep(0)
    adapter.release.set()

    with pytest.raises(asyncio.CancelledError) as raised:
        await closing
    assert raised.value.args == ("first close cancellation",)
    assert adapter.finished.is_set()
    assert adapter.mark_calls == adapter.read_calls == 1
    await service.close()


def test_static_scope_guards_no_new_transport_or_background_loop() -> None:
    delivery_source = inspect.getsource(CrewSessionDeliveryService)
    wiring_source = inspect.getsource(_wire_crew_session_delivery)
    event_values = {event.value for event in EventType}
    assert "crew_session_delivery" not in event_values
    assert "create_task(" in delivery_source
    assert "create_task(" not in wiring_source
    for forbidden_loop in ("call_later(", "call_at(", "sleep(", "poll"):
        assert forbidden_loop not in delivery_source
    for forbidden in (
        "discord",
        "slack",
        "teams",
        "email",
        "websocket",
        "billing",
        "pricing",
        "ad-1132",
        "ad-1133",
    ):
        assert forbidden not in delivery_source.lower()