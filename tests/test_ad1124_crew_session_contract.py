"""AD-1124: durable CrewSession contract on WorkItem and task-linked room."""

from __future__ import annotations

import ast
import asyncio
import builtins
import hashlib
import inspect
import io
import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import UploadFile
from pydantic import ValidationError
from starlette.datastructures import Headers

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive import crew_session as crew_session_module
from probos.cognitive.crew_session import (
    CrewSessionContract,
    CrewSessionService,
    is_valid_crew_session_transition,
)
from probos.cognitive.crew_synth import CrewSynthesizer
from probos.config import SystemConfig
from probos.events import EventType
from probos.routers import chat as chat_router
from probos.routers.workforce import attach_work_item_inputs
from probos.startup.finalize import _wire_crew_session_service
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.threads import ChatThread, ChatThreadStore
from probos.workforce import (
    BUILTIN_WORK_TYPES,
    CrewSessionAdmissionPort,
    CrewSessionParentCreate,
    CrewSessionParentReservation,
    WorkItem,
    WorkItemStatus,
    WorkItemStore,
    WorkTypeRegistry,
)


_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_FINE_STATES = (
    "discussing",
    "executing",
    "verifying",
    "blocked_needs_captain",
    "done",
    "failed",
)
_PROJECTION = {
    "discussing": "open",
    "executing": "in_progress",
    "verifying": "review",
    "blocked_needs_captain": "blocked",
    "done": "done",
    "failed": "failed",
}
_FINE_EDGES = {
    ("discussing", "executing"),
    ("discussing", "blocked_needs_captain"),
    ("discussing", "failed"),
    ("executing", "verifying"),
    ("executing", "blocked_needs_captain"),
    ("executing", "failed"),
    ("verifying", "done"),
    ("verifying", "blocked_needs_captain"),
    ("verifying", "failed"),
    ("blocked_needs_captain", "discussing"),
    ("blocked_needs_captain", "executing"),
    ("blocked_needs_captain", "verifying"),
    ("blocked_needs_captain", "failed"),
}
_WORK_ITEM_COLUMNS = [
    "id",
    "title",
    "description",
    "work_type",
    "status",
    "priority",
    "parent_id",
    "depends_on",
    "assigned_to",
    "created_by",
    "created_at",
    "updated_at",
    "due_at",
    "estimated_tokens",
    "actual_tokens",
    "trust_requirement",
    "required_capabilities",
    "tags",
    "metadata",
    "steps",
    "verification",
    "schedule",
    "ttl_seconds",
    "template_id",
]
_CREW_PARENT_IDS = itertools.count(1)


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _EventRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))

    def clear(self) -> None:
        self.events.clear()


class _ImportRecorder:
    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.names: list[str] = []

    def __call__(
        self,
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        self.names.append(name)
        return self._delegate(name, globals, locals, fromlist, level)


class _RuntimeAccessRecorder:
    def __init__(self) -> None:
        self.accesses: list[str] = []

    def __getattr__(self, name: str) -> Any:
        self.accesses.append(name)
        return None


class _MergeAdmissionBarrierStore:
    def __init__(self, delegate: WorkItemStore) -> None:
        self._delegate = delegate
        self.merge_entered = asyncio.Event()
        self.release_merge = asyncio.Event()
        self.last_merge_options: dict[str, Any] = {}

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
        self.last_merge_options = {
            "expected_work_type": expected_work_type,
            "expected_status": expected_status,
            "expected_assigned_to": expected_assigned_to,
        }
        self.merge_entered.set()
        await self.release_merge.wait()
        return await self._delegate.merge_work_item_metadata(
            work_item_id,
            patch,
            expected=expected,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            new_status=new_status,
            source=source,
        )


class _ObservedLock:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.attempts = 0
        self.second_attempted = asyncio.Event()

    async def __aenter__(self) -> _ObservedLock:
        self.attempts += 1
        if self.attempts == 2:
            self.second_attempted.set()
        await self._lock.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()


class _ControlledConnection:
    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.operations: list[str] = []
        self.rollback_attempts = 0
        self._update_error: BaseException | None = None
        self._commit_error: BaseException | None = None
        self._block_commit = False
        self.commit_entered = asyncio.Event()
        self.release_commit = asyncio.Event()

    @property
    def row_factory(self) -> Any:
        return self._delegate.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._delegate.row_factory = value

    def inject_update_error(self, error: BaseException) -> None:
        self._update_error = error

    def inject_commit_error(self, error: BaseException) -> None:
        self._commit_error = error

    def block_next_commit(self) -> None:
        self._block_commit = True
        self.commit_entered.clear()
        self.release_commit.clear()

    async def execute(self, sql: str, parameters: Any = None) -> Any:
        normalized = " ".join(sql.split())
        self.operations.append(normalized)
        if normalized == "ROLLBACK":
            self.rollback_attempts += 1
        if (
            self._update_error is not None
            and normalized.startswith("UPDATE work_items SET metadata")
        ):
            error = self._update_error
            self._update_error = None
            raise error
        if parameters is None:
            return await self._delegate.execute(sql)
        return await self._delegate.execute(sql, parameters)

    async def executemany(self, sql: str, parameters: Any) -> Any:
        return await self._delegate.executemany(sql, parameters)

    async def executescript(self, sql_script: str) -> None:
        await self._delegate.executescript(sql_script)

    async def commit(self) -> None:
        self.operations.append("COMMIT")
        if self._block_commit:
            self._block_commit = False
            self.commit_entered.set()
            await self.release_commit.wait()
        if self._commit_error is not None:
            error = self._commit_error
            self._commit_error = None
            raise error
        await self._delegate.commit()

    async def close(self) -> None:
        await self._delegate.close()


class _ControlledConnectionFactory:
    def __init__(self) -> None:
        self.connection: _ControlledConnection | None = None

    async def connect(self, db_path: str) -> _ControlledConnection:
        delegate = await SQLiteConnectionFactory().connect(db_path)
        self.connection = _ControlledConnection(delegate)
        return self.connection


@dataclass
class _Stores:
    work: WorkItemStore
    chat: ChatThreadStore
    events: _EventRecorder
    admission_port: CrewSessionAdmissionPort | None = None


@pytest.fixture
async def stores(tmp_path: Path) -> Any:
    events = _EventRecorder()
    work = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"),
        emit_event=events,
        tick_interval=1000,
    )
    await work.start()
    try:
        yield _Stores(
            work=work,
            chat=ChatThreadStore(tmp_path / "threads.db"),
            events=events,
        )
    finally:
        await work.stop()


def _service(stores: _Stores, clock: _Clock) -> CrewSessionService:
    return CrewSessionService(
        work_item_store=stores.work,
        chat_thread_store=stores.chat,
        clock=clock,
    )


async def _create_crew_parent(
    stores: _Stores,
    *,
    assigned_to: str = "facilitator-1",
    metadata: dict[str, Any] | None = None,
) -> WorkItem:
    if stores.admission_port is None:
        stores.admission_port = stores.work.claim_crew_session_admission_port()
    async with stores.admission_port.reserve() as reservation:
        parent = await reservation.create_parent(CrewSessionParentCreate(
            id=f"crew-session-fixture-{next(_CREW_PARENT_IDS)}",
            title="Durable session",
            description="Durable session",
            assigned_to=assigned_to,
            created_by="captain",
            metadata={},
            created_at=100.0,
        ))
    if metadata:
        parent = await stores.work.merge_work_item_metadata(
            parent.id,
            dict(metadata),
            expected_work_type="crew_session",
            expected_status="draft",
            expected_assigned_to=assigned_to,
        )
        assert parent is not None
    return parent


async def _parent_and_room(
    stores: _Stores,
    *,
    work_type: str = "crew_session",
    assigned_to: str | None = "facilitator-1",
    status: str | None = None,
    metadata: dict[str, Any] | None = None,
    room_task_id: str | None = None,
) -> tuple[WorkItem, ChatThread]:
    if work_type == "crew_session":
        if assigned_to is None:
            raise ValueError("crew_session_parent_create_invalid")
        parent = await _create_crew_parent(
            stores,
            assigned_to=assigned_to,
            metadata=metadata,
        )
        if status is not None and status != "draft":
            parent = await stores.work.merge_work_item_metadata(
                parent.id,
                {},
                expected_work_type="crew_session",
                expected_status="draft",
                expected_assigned_to=assigned_to,
                new_status=status,
            )
            assert parent is not None
    else:
        kwargs: dict[str, Any] = {
            "title": "Durable session",
            "work_type": work_type,
            "assigned_to": assigned_to,
            "created_at": 100.0,
            "updated_at": 100.0,
            "metadata": dict(metadata or {}),
        }
        if status is not None:
            kwargs["status"] = status
        parent = await stores.work.create_work_item(**kwargs)
    thread = stores.chat.create_thread(
        title="Crew room",
        participants=["facilitator-1", "owner-2"],
        task_id=room_task_id if room_task_id is not None else parent.id,
    )
    return parent, thread


async def _initialize(
    service: CrewSessionService,
    parent: WorkItem,
    thread: ChatThread,
    **overrides: Any,
) -> CrewSessionContract:
    values: dict[str, Any] = {
        "goal": "Deliver a verified result",
        "origin": "captain",
        "originator_id": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1", "owner-2"],
        "success_criteria": ["Result is complete", "Evidence is linked"],
        "expected_deliverable": "A verified report",
    }
    values.update(overrides)
    return await service.initialize_session(parent.id, thread.id, **values)


async def _bound(
    stores: _Stores,
    *,
    clock: _Clock | None = None,
) -> tuple[CrewSessionService, _Clock, WorkItem, ChatThread, CrewSessionContract]:
    active_clock = clock or _Clock(200.0)
    parent, thread = await _parent_and_room(stores)
    service = _service(stores, active_clock)
    contract = await _initialize(service, parent, thread)
    return service, active_clock, parent, thread, contract


def _contract_payload(**updates: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": 1,
        "state": "discussing",
        "previous_state": None,
        "revision": 1,
        "goal": "goal",
        "origin": "captain",
        "originator_id": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1"],
        "success_criteria": ["criterion"],
        "expected_deliverable": "deliverable",
        "thread_id": "thread-1",
        "task_id": "task-1",
        "created_at": 100.0,
        "transitioned_at": 100.0,
        "started_at": None,
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
    }
    payload.update(updates)
    return payload


def _upload(name: str, blob: bytes, mime: str = "text/plain") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(blob),
        filename=name,
        headers=Headers({"content-type": mime}),
    )


def _broadcast(*_args: Any, **_kwargs: Any) -> None:
    return None


def test_builtin_descriptor_matches_exact_contract() -> None:
    descriptor = BUILTIN_WORK_TYPES["crew_session"]
    assert descriptor.initial_status == "draft"
    assert descriptor.terminal_statuses == frozenset({"done", "failed"})
    assert descriptor.supports_children is True
    assert descriptor.auto_assign_eligible is False
    assert descriptor.verification_required is True
    assert descriptor.required_fields == ["title"]
    assert descriptor.default_priority == 2


def test_builtin_coarse_transition_matrix_all_pairs() -> None:
    registry = WorkTypeRegistry()
    statuses = ("draft", "open", "in_progress", "review", "blocked", "done", "failed")
    expected = {
        ("draft", "open"),
        ("open", "in_progress"),
        ("open", "blocked"),
        ("open", "failed"),
        ("in_progress", "review"),
        ("in_progress", "blocked"),
        ("in_progress", "failed"),
        ("review", "done"),
        ("review", "blocked"),
        ("review", "failed"),
        ("blocked", "open"),
        ("blocked", "in_progress"),
        ("blocked", "review"),
        ("blocked", "failed"),
    }
    actual = {
        (old, new)
        for old in statuses
        for new in statuses
        if old != new and registry.validate_transition("crew_session", old, new)[0]
    }
    assert actual == expected
    assert registry.transition_requires_assignment("crew_session", "draft", "open")
    assert registry.transition_requires_assignment("crew_session", "open", "in_progress")
    assert not registry.transition_requires_assignment("crew_session", "blocked", "open")
    assert registry.transition_requires_assignment("crew_session", "blocked", "in_progress")


def test_global_status_vocabulary_has_no_session_only_states() -> None:
    values = {status.value for status in WorkItemStatus}
    assert values == {
        "draft", "open", "scheduled", "in_progress", "review", "done",
        "failed", "cancelled", "blocked",
    }
    assert {"discussing", "executing", "verifying", "blocked_needs_captain"}.isdisjoint(values)


def test_fine_transition_matrix_all_36_pairs() -> None:
    for old in _FINE_STATES:
        for new in _FINE_STATES:
            expected = old == new or (old, new) in _FINE_EDGES
            assert is_valid_crew_session_transition(old, new) is expected
    assert not is_valid_crew_session_transition(None, "done")  # type: ignore[arg-type]
    assert not is_valid_crew_session_transition("unknown", "done")


async def test_initialize_session_persists_strict_contract_and_generic_projection(
    stores: _Stores,
) -> None:
    parent, thread = await _parent_and_room(stores)
    service = _service(stores, _Clock(200.0))

    contract = await _initialize(service, parent, thread)

    assert contract.state == "discussing"
    assert contract.revision == 1
    assert contract.task_id == parent.id
    assert contract.thread_id == thread.id
    reloaded = await stores.work.get_work_item(parent.id)
    assert reloaded is not None
    assert reloaded.status == "open"
    assert reloaded.metadata["crew_session"] == contract.model_dump(mode="json")


async def test_initialize_contract_has_exact_27_keys_and_server_times(stores: _Stores) -> None:
    parent, thread = await _parent_and_room(stores)
    service = _service(stores, _Clock(225.0))

    contract = await _initialize(service, parent, thread)
    persisted = contract.model_dump(mode="json")

    assert len(persisted) == 27
    assert set(persisted) == set(_contract_payload())
    assert contract.created_at == parent.created_at == 100.0
    assert contract.transitioned_at == 225.0
    assert contract.duplicate_resume_count == 0
    assert contract.previous_state is None


async def test_initialize_exact_replay_is_idempotent(stores: _Stores) -> None:
    service, clock, parent, thread, first = await _bound(stores)
    before = await stores.work.get_work_item(parent.id)
    stores.events.clear()
    clock.now = 999.0

    replay = await _initialize(service, parent, thread)

    after = await stores.work.get_work_item(parent.id)
    assert replay == first
    assert after is not None and before is not None
    assert after.updated_at == before.updated_at
    assert stores.events.events == []


async def test_initialize_conflicting_replay_fails_closed(stores: _Stores) -> None:
    service, _clock, parent, thread, first = await _bound(stores)

    with pytest.raises(ValueError):
        await _initialize(service, parent, thread, goal="A different goal")

    assert await service.get_session(parent.id) == first


async def test_get_session_missing_parent_or_contract_returns_none(stores: _Stores) -> None:
    service = _service(stores, _Clock(200.0))
    ordinary = await stores.work.create_work_item(title="ordinary", work_type="task")

    assert await service.get_session("missing-parent") is None
    assert await service.get_session(ordinary.id) is None
    with pytest.raises(ValueError, match="crew_session_parent_not_found"):
        await service.transition_session(
            "missing-parent", "executing", expected_revision=1,
        )
    with pytest.raises(ValueError, match="crew_session_not_initialized"):
        await service.transition_session(
            ordinary.id, "executing", expected_revision=1,
        )


async def test_strict_contract_round_trips_full_lifecycle(stores: _Stores) -> None:
    service, clock, parent, _thread, contract = await _bound(stores)
    clock.now = 220.0
    contract = await service.transition_session(
        parent.id,
        "executing",
        expected_revision=contract.revision,
        last_result_summary="First concrete result",
        evidence_refs=[_SHA_A],
    )
    clock.now = 230.0
    contract = await service.transition_session(
        parent.id,
        "blocked_needs_captain",
        expected_revision=contract.revision,
        blocked_reason="Captain decision required",
    )
    clock.now = 250.0
    contract = await service.transition_session(
        parent.id, "executing", expected_revision=contract.revision,
    )
    clock.now = 260.0
    contract = await service.transition_session(
        parent.id,
        "verifying",
        expected_revision=contract.revision,
        last_result_summary="Verification candidate",
        evidence_refs=[_SHA_B],
    )
    clock.now = 280.0
    contract = await service.transition_session(
        parent.id,
        "done",
        expected_revision=contract.revision,
        evidence_refs=[_SHA_C],
        result_artifact_id="artifact-1",
        result_ref=_SHA_C,
    )

    assert contract.state == "done"
    assert contract.previous_state == "verifying"
    assert contract.started_at == 220.0
    assert contract.first_result_at == 220.0
    assert contract.verified_at == contract.completed_at == 280.0
    assert contract.blocked_duration_seconds == 20.0
    assert contract.blocked_reason is None and contract.blocked_since is None
    assert contract.evidence_refs == (_SHA_A, _SHA_B, _SHA_C)
    assert contract.result_artifact_id == "artifact-1"
    assert contract.result_ref == _SHA_C
    assert (await stores.work.get_work_item(parent.id)).status == "done"
    assert await service.get_session(parent.id) == contract

    failed_parent, failed_thread = await _parent_and_room(stores)
    failed = await _initialize(service, failed_parent, failed_thread)
    clock.now = 300.0
    failed = await service.transition_session(
        failed_parent.id,
        "failed",
        expected_revision=failed.revision,
        last_result_summary="Failure details recorded",
        evidence_refs=[_SHA_A],
    )
    assert failed.state == "failed"
    assert failed.completed_at == failed.transitioned_at == 300.0
    assert failed.started_at is None
    assert failed.first_result_at == 300.0
    assert failed.last_result_summary == "Failure details recorded"
    assert failed.evidence_refs == (_SHA_A,)
    assert (await stores.work.get_work_item(failed_parent.id)).status == "failed"


async def test_server_timestamp_first_write_and_no_timestamp_parameters(stores: _Stores) -> None:
    service, clock, parent, _thread, contract = await _bound(stores)
    initialize_names = set(inspect.signature(service.initialize_session).parameters)
    transition_names = set(inspect.signature(service.transition_session).parameters)
    assert not any(name.endswith("_at") for name in initialize_names | transition_names)

    clock.now = 240.0
    first = await service.transition_session(
        parent.id,
        "executing",
        expected_revision=contract.revision,
        last_result_summary="result one",
    )
    clock.now = 260.0
    second = await service.transition_session(
        parent.id,
        "executing",
        expected_revision=first.revision,
        last_result_summary="result two",
    )
    assert first.started_at == second.started_at == 240.0
    assert first.first_result_at == second.first_result_at == 240.0


async def test_blocked_duration_accumulates_across_cycles(stores: _Stores) -> None:
    service, clock, parent, _thread, contract = await _bound(stores)
    clock.now = 210.0
    contract = await service.transition_session(parent.id, "executing", expected_revision=1)
    clock.now = 220.0
    contract = await service.transition_session(
        parent.id, "blocked_needs_captain", expected_revision=2, blocked_reason="first block",
    )
    clock.now = 240.0
    contract = await service.transition_session(parent.id, "executing", expected_revision=3)
    clock.now = 250.0
    contract = await service.transition_session(
        parent.id, "blocked_needs_captain", expected_revision=4, blocked_reason="second block",
    )
    clock.now = 285.0
    contract = await service.transition_session(parent.id, "executing", expected_revision=5)

    assert contract.blocked_duration_seconds == 55.0
    assert contract.blocked_reason is None
    assert contract.blocked_since is None

    early_parent, early_thread = await _parent_and_room(stores)
    clock.now = 300.0
    early = await _initialize(service, early_parent, early_thread)
    clock.now = 310.0
    early = await service.transition_session(
        early_parent.id,
        "blocked_needs_captain",
        expected_revision=early.revision,
        blocked_reason="Decision before execution",
        last_result_summary="Discussion produced an initial result",
    )
    clock.now = 320.0
    early = await service.transition_session(
        early_parent.id, "executing", expected_revision=early.revision,
    )
    assert early.first_result_at == 310.0
    assert early.started_at == 320.0


async def test_initialize_clock_regression_rejects_without_mutation(stores: _Stores) -> None:
    parent, thread = await _parent_and_room(stores)
    service = _service(stores, _Clock(99.0))
    stores.events.clear()

    with pytest.raises(ValueError):
        await _initialize(service, parent, thread)

    reloaded = await stores.work.get_work_item(parent.id)
    assert reloaded is not None and reloaded.status == "draft"
    assert "crew_session" not in reloaded.metadata
    assert stores.events.events == []


async def test_transition_clock_regression_rejects_without_mutation(stores: _Stores) -> None:
    service, clock, parent, _thread, contract = await _bound(stores)
    clock.now = 199.0
    before = await stores.work.get_work_item(parent.id)

    with pytest.raises(ValueError):
        await service.transition_session(parent.id, "executing", expected_revision=1)

    after = await stores.work.get_work_item(parent.id)
    assert after is not None and before is not None
    assert after.metadata == before.metadata
    assert after.status == before.status

    clock.now = 210.0
    executing = await service.transition_session(
        parent.id, "executing", expected_revision=contract.revision,
    )
    clock.now = 220.0
    progress = await service.transition_session(
        parent.id,
        "executing",
        expected_revision=executing.revision,
        last_result_summary="milestone at 220",
    )
    clock.now = 215.0
    with pytest.raises(ValueError, match="crew_session_clock_regression"):
        await service.transition_session(
            parent.id, "verifying", expected_revision=progress.revision,
        )
    unchanged = await service.get_session(parent.id)
    assert unchanged == progress


async def test_same_state_noop_preserves_every_observable(stores: _Stores) -> None:
    service, clock, parent, _thread, contract = await _bound(stores)
    before = await stores.work.get_work_item(parent.id)
    stores.events.clear()
    clock.now = 900.0

    result = await service.transition_session(
        parent.id, "discussing", expected_revision=contract.revision,
    )

    after = await stores.work.get_work_item(parent.id)
    assert result == contract
    assert after is not None and before is not None
    assert after.updated_at == before.updated_at
    assert after.metadata == before.metadata
    assert stores.events.events == []


async def test_same_state_progress_updates_once_and_first_result_once(stores: _Stores) -> None:
    service, clock, parent, _thread, contract = await _bound(stores)
    clock.now = 210.0
    executing = await service.transition_session(parent.id, "executing", expected_revision=1)
    transitioned_at = executing.transitioned_at
    clock.now = 220.0
    progress = await service.transition_session(
        parent.id,
        "executing",
        expected_revision=2,
        last_result_summary="progress",
        evidence_refs=[_SHA_A],
    )
    clock.now = 240.0
    repeated = await service.transition_session(
        parent.id,
        "executing",
        expected_revision=3,
        last_result_summary="progress",
        evidence_refs=[_SHA_A],
    )

    assert progress.revision == 3
    assert progress.previous_state == "discussing"
    assert progress.transitioned_at == transitioned_at
    assert progress.first_result_at == 220.0
    assert repeated == progress


async def test_evidence_refs_append_first_seen_deduped_and_bounded(stores: _Stores) -> None:
    service, clock, parent, _thread, contract = await _bound(stores)
    clock.now = 210.0
    executing = await service.transition_session(parent.id, "executing", expected_revision=1)
    clock.now = 220.0
    progress = await service.transition_session(
        parent.id,
        "executing",
        expected_revision=executing.revision,
        evidence_refs=[_SHA_A, _SHA_A, _SHA_B],
    )
    assert progress.evidence_refs == (_SHA_A, _SHA_B)

    with pytest.raises(ValueError, match="crew_session_evidence_refs_invalid"):
        await service.transition_session(
            parent.id,
            "executing",
            expected_revision=progress.revision,
            evidence_refs=(_SHA_C,),  # type: ignore[arg-type]
        )

    too_many = [f"{index:064x}" for index in range(33)]
    with pytest.raises(ValueError):
        await service.transition_session(
            parent.id,
            "executing",
            expected_revision=progress.revision,
            evidence_refs=too_many,
        )
    assert (await service.get_session(parent.id)).revision == progress.revision


async def test_stale_revision_conflict_has_no_mutation(stores: _Stores) -> None:
    service, clock, parent, _thread, _contract = await _bound(stores)
    with pytest.raises(ValueError, match="crew_session_revision_invalid"):
        await service.transition_session(
            parent.id, "executing", expected_revision=True,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="crew_session_state_invalid"):
        await service.transition_session(
            parent.id, "unknown", expected_revision=1,  # type: ignore[arg-type]
        )
    clock.now = 210.0
    current = await service.transition_session(parent.id, "executing", expected_revision=1)
    before = await stores.work.get_work_item(parent.id)

    with pytest.raises(ValueError):
        await service.transition_session(parent.id, "verifying", expected_revision=1)

    after = await stores.work.get_work_item(parent.id)
    assert after is not None and before is not None
    assert after.metadata == before.metadata
    assert (await service.get_session(parent.id)).revision == current.revision


async def test_concurrent_same_revision_exactly_one_commits(stores: _Stores) -> None:
    service, clock, parent, _thread, _contract = await _bound(stores)
    await stores.work.merge_work_item_metadata(parent.id, {"origin": "preserve-me"})
    clock.now = 210.0

    results = await asyncio.gather(
        service.transition_session(parent.id, "executing", expected_revision=1),
        service.transition_session(
            parent.id,
            "blocked_needs_captain",
            expected_revision=1,
            blocked_reason="needs decision",
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(result, CrewSessionContract) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    reloaded = await stores.work.get_work_item(parent.id)
    assert reloaded is not None
    assert reloaded.metadata["origin"] == "preserve-me"
    assert reloaded.metadata["crew_session"]["revision"] == 2


@pytest.mark.parametrize("mutation", ["assigned_to", "work_type", "status"])
async def test_initialize_session_generic_writer_interleaving_conflicts_without_mutation(
    stores: _Stores,
    mutation: str,
) -> None:
    parent, thread = await _parent_and_room(stores)
    barrier = _MergeAdmissionBarrierStore(stores.work)
    service = CrewSessionService(
        work_item_store=barrier,
        chat_thread_store=stores.chat,
        clock=_Clock(200.0),
    )
    initialize_task = asyncio.create_task(_initialize(service, parent, thread))
    await barrier.merge_entered.wait()

    with pytest.raises(ValueError, match="^crew_session_write_reserved$"):
        if mutation == "assigned_to":
            await stores.work.update_work_item(
                parent.id,
                assigned_to="other-owner",
            )
        elif mutation == "work_type":
            await stores.work.update_work_item(parent.id, work_type="task")
        else:
            await stores.work.transition_work_item(parent.id, "open")

    barrier.release_merge.set()
    initialized = await initialize_task

    reloaded = await stores.work.get_work_item(parent.id)
    assert reloaded is not None
    assert initialized.state == "discussing"
    assert reloaded.status == "open"
    assert reloaded.metadata["crew_session"] == initialized.model_dump(mode="json")
    assert barrier.last_merge_options == {
        "expected_work_type": "crew_session",
        "expected_status": "draft",
        "expected_assigned_to": "facilitator-1",
    }


async def test_transition_session_generic_status_interleaving_conflicts_without_mutation(
    stores: _Stores,
) -> None:
    _service_before, _clock, parent, _thread, contract = await _bound(stores)
    barrier = _MergeAdmissionBarrierStore(stores.work)
    service = CrewSessionService(
        work_item_store=barrier,
        chat_thread_store=stores.chat,
        clock=_Clock(210.0),
    )
    transition_task = asyncio.create_task(
        service.transition_session(parent.id, "executing", expected_revision=1),
    )
    await barrier.merge_entered.wait()
    with pytest.raises(ValueError, match="^crew_session_write_reserved$"):
        await stores.work.transition_work_item(parent.id, "blocked")

    barrier.release_merge.set()
    transitioned = await transition_task

    reloaded = await stores.work.get_work_item(parent.id)
    assert reloaded is not None and reloaded.status == "in_progress"
    assert transitioned.state == "executing"
    assert reloaded.metadata["crew_session"] == transitioned.model_dump(mode="json")
    assert barrier.last_merge_options == {
        "expected_work_type": "crew_session",
        "expected_status": "open",
        "expected_assigned_to": "facilitator-1",
    }


async def test_transition_session_generic_metadata_alias_interleaving_conflicts_without_mutation(
    stores: _Stores,
) -> None:
    _service_before, _clock, parent, _thread, contract = await _bound(stores)
    barrier = _MergeAdmissionBarrierStore(stores.work)
    service = CrewSessionService(
        work_item_store=barrier,
        chat_thread_store=stores.chat,
        clock=_Clock(210.0),
    )
    transition_task = asyncio.create_task(
        service.transition_session(parent.id, "executing", expected_revision=1),
    )
    await barrier.merge_entered.wait()

    malformed = contract.model_dump(mode="json")
    malformed["revision"] = True
    with pytest.raises(ValueError, match="^crew_session_write_reserved$"):
        await stores.work.update_work_item(
            parent.id,
            metadata={"crew_session": malformed},
        )

    barrier.release_merge.set()
    transitioned = await transition_task
    with pytest.raises(ValueError, match="work_item_metadata_conflict"):
        await stores.work.merge_work_item_metadata(
            parent.id,
            {"alias_probe": True},
            expected={"crew_session": malformed},
            expected_work_type="crew_session",
            expected_status="in_progress",
            expected_assigned_to="facilitator-1",
        )

    reloaded = await stores.work.get_work_item(parent.id)
    assert reloaded is not None
    assert reloaded.status == "in_progress"
    assert "alias_probe" not in reloaded.metadata
    assert reloaded.metadata["crew_session"] == transitioned.model_dump(mode="json")


def test_contract_rejects_unknown_version_state_and_key() -> None:
    invalid_payloads = [
        _contract_payload(version=2),
        _contract_payload(state="unknown"),
        _contract_payload(previous_state="unknown"),
        _contract_payload(origin="system"),
        _contract_payload(revision=0),
        _contract_payload(revision=2_147_483_648),
        _contract_payload(duplicate_resume_count=-1),
        _contract_payload(duplicate_resume_count=1_000_001),
        {**_contract_payload(), "extra": "forbidden"},
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            CrewSessionContract.model_validate(payload)


def test_contract_rejects_malformed_ids_and_refs() -> None:
    invalid_payloads = [
        _contract_payload(originator_id="bad/id"),
        _contract_payload(thread_id=""),
        _contract_payload(task_id="x" * 129),
        _contract_payload(evidence_refs=["A" * 64]),
        _contract_payload(result_ref="0" * 63),
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            CrewSessionContract.model_validate(payload)


def test_contract_rejects_duplicate_or_excessive_lists() -> None:
    invalid_payloads = [
        _contract_payload(owner_ids=None),
        _contract_payload(success_criteria=None),
        _contract_payload(evidence_refs=None),
        _contract_payload(owner_ids=[]),
        _contract_payload(owner_ids=("facilitator-1",)),
        _contract_payload(success_criteria=("criterion",)),
        _contract_payload(evidence_refs=(_SHA_A,)),
        _contract_payload(owner_ids=["facilitator-1", "facilitator-1"]),
        _contract_payload(success_criteria=["same", "same"]),
        _contract_payload(evidence_refs=[_SHA_A, _SHA_A]),
        _contract_payload(owner_ids=[f"owner-{index}" for index in range(17)]),
        _contract_payload(success_criteria=[f"criterion-{index}" for index in range(17)]),
        _contract_payload(evidence_refs=[f"{index:064x}" for index in range(33)]),
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            CrewSessionContract.model_validate(payload)


def test_contract_rejects_empty_nul_and_oversized_text() -> None:
    invalid_payloads = [
        _contract_payload(goal=1),
        _contract_payload(goal="   "),
        _contract_payload(success_criteria=[]),
        _contract_payload(success_criteria=[" "]),
        _contract_payload(expected_deliverable="x\x00y"),
        _contract_payload(goal="x" * 4097),
        _contract_payload(success_criteria=["x" * 513]),
        _contract_payload(expected_deliverable="x" * 2049),
        _contract_payload(last_result_summary="x" * 4097),
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            CrewSessionContract.model_validate(payload)


def test_contract_rejects_bool_nonfinite_negative_and_bad_chronology() -> None:
    invalid_payloads = [
        _contract_payload(revision=True),
        _contract_payload(duplicate_resume_count=True),
        _contract_payload(created_at=True),
        _contract_payload(created_at=-1.0),
        _contract_payload(transitioned_at=253_402_300_800.0),
        _contract_payload(transitioned_at=float("inf")),
        _contract_payload(blocked_duration_seconds=-1.0),
        _contract_payload(blocked_duration_seconds=0),
        _contract_payload(blocked_duration_seconds=float("nan")),
        _contract_payload(blocked_duration_seconds=315_576_001.0),
        _contract_payload(
            state="blocked_needs_captain", blocked_reason=None,
            blocked_since=100.0,
        ),
        _contract_payload(blocked_reason="unexpected"),
        _contract_payload(
            state="executing", started_at=100.0, result_ref=_SHA_A,
        ),
        _contract_payload(
            state="failed", completed_at=100.0, verified_at=100.0,
        ),
        _contract_payload(last_result_summary="result without timestamp"),
        _contract_payload(first_result_at=100.0),
        _contract_payload(
            state="done", started_at=100.0, verified_at=None, completed_at=None,
        ),
        _contract_payload(state="failed", completed_at=None),
        _contract_payload(created_at=101.0, transitioned_at=100.0),
        _contract_payload(started_at=110.0, first_result_at=109.0),
        _contract_payload(state="executing", started_at=None),
        _contract_payload(
            state="blocked_needs_captain", blocked_reason="blocked",
            blocked_since=101.0,
        ),
        _contract_payload(
            state="done", transitioned_at=110.0, started_at=100.0,
            verified_at=109.0, completed_at=110.0,
        ),
        _contract_payload(
            state="failed", transitioned_at=110.0, completed_at=109.0,
        ),
        _contract_payload(completed_at=105.0, started_at=110.0),
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            CrewSessionContract.model_validate(payload)


def test_contract_rejects_excessive_compact_utf8_total_bytes() -> None:
    payload = _contract_payload(
        goal="\U0001f600" * 4096,
        success_criteria=[f"{index:02d}" + "\U0001f600" * 510 for index in range(16)],
    )
    compact = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert len(compact.encode("utf-8")) > 32_768
    with pytest.raises(ValidationError):
        CrewSessionContract.model_validate(payload)


def test_contract_defensively_owns_and_serializes_lists() -> None:
    owners = ["facilitator-1"]
    criteria = ["criterion"]
    refs = [_SHA_A]
    contract = CrewSessionContract.model_validate(
        _contract_payload(owner_ids=owners, success_criteria=criteria, evidence_refs=refs)
    )
    owners.append("owner-2")
    criteria.append("other")
    refs.append(_SHA_B)
    assert contract.owner_ids == ("facilitator-1",)
    assert contract.success_criteria == ("criterion",)
    assert contract.evidence_refs == (_SHA_A,)

    serialized = contract.model_dump(mode="json")
    assert isinstance(serialized["owner_ids"], list)
    serialized["owner_ids"].append("mutated")
    assert contract.owner_ids == ("facilitator-1",)
    with pytest.raises(ValidationError):
        contract.revision = 2  # type: ignore[misc]

    maximal = CrewSessionContract.model_validate(_contract_payload(
        state="blocked_needs_captain",
        previous_state="executing",
        revision=2_147_483_647,
        goal="g" * 4_096,
        owner_ids=["facilitator-1", *[f"owner-{index}" for index in range(15)]],
        success_criteria=[f"{index:02d}" + "c" * 510 for index in range(16)],
        expected_deliverable="d" * 2_048,
        transitioned_at=200.0,
        started_at=150.0,
        first_result_at=175.0,
        last_result_summary="r" * 4_096,
        blocked_reason="b" * 2_048,
        blocked_since=200.0,
        blocked_duration_seconds=315_576_000.0,
        evidence_refs=[f"{index:064x}" for index in range(32)],
        duplicate_resume_count=1_000_000,
    ))
    assert maximal.revision == 2_147_483_647
    assert len(maximal.owner_ids) == 16
    assert len(maximal.success_criteria) == 16
    assert len(maximal.evidence_refs) == 32
    assert maximal.blocked_duration_seconds == 315_576_000.0


async def test_initialize_rejects_missing_wrong_type_and_wrong_status_parent(stores: _Stores) -> None:
    service = _service(stores, _Clock(200.0))
    with pytest.raises(ValueError):
        await service.initialize_session(
            "missing", "thread-1", goal="g", origin="captain",
            originator_id="captain", facilitator_id="facilitator-1",
            owner_ids=["facilitator-1"], success_criteria=["c"],
            expected_deliverable="d",
        )

    wrong_type, wrong_type_thread = await _parent_and_room(stores, work_type="task")
    with pytest.raises(ValueError):
        await _initialize(service, wrong_type, wrong_type_thread)

    wrong_status, wrong_status_thread = await _parent_and_room(stores, status="open")
    with pytest.raises(ValueError):
        await _initialize(service, wrong_status, wrong_status_thread)


async def test_initialize_rejects_assignment_and_owner_invariants(stores: _Stores) -> None:
    service = _service(stores, _Clock(200.0))
    with pytest.raises(ValueError, match="crew_session_parent_create_invalid"):
        if stores.admission_port is None:
            stores.admission_port = stores.work.claim_crew_session_admission_port()
        async with stores.admission_port.reserve() as reservation:
            await reservation.create_parent(CrewSessionParentCreate(
                id=f"crew-session-fixture-{next(_CREW_PARENT_IDS)}",
                title="Durable session",
                description="Durable session",
                assigned_to="",
                created_by="captain",
                metadata={},
                created_at=100.0,
            ))

    mismatch, mismatch_thread = await _parent_and_room(stores, assigned_to="other-owner")
    with pytest.raises(ValueError):
        await _initialize(service, mismatch, mismatch_thread)

    not_owner, not_owner_thread = await _parent_and_room(stores)
    with pytest.raises(ValueError):
        await _initialize(
            service, not_owner, not_owner_thread, owner_ids=["owner-2"],
        )


async def test_initialize_rejects_missing_room_without_mutation(stores: _Stores) -> None:
    parent = await _create_crew_parent(stores)
    service = _service(stores, _Clock(200.0))
    with pytest.raises(ValueError):
        await service.initialize_session(
            parent.id, "missing-thread", goal="g", origin="captain",
            originator_id="captain", facilitator_id="facilitator-1",
            owner_ids=["facilitator-1"], success_criteria=["c"],
            expected_deliverable="d",
        )
    reloaded = await stores.work.get_work_item(parent.id)
    assert reloaded is not None and reloaded.status == "draft"
    assert "crew_session" not in reloaded.metadata


async def test_initialize_rejects_wrong_task_and_wrong_requested_thread(stores: _Stores) -> None:
    parent, linked = await _parent_and_room(stores)
    other = stores.chat.create_thread(title="other", participants=[], task_id="other-task")
    service = _service(stores, _Clock(200.0))

    with pytest.raises(ValueError):
        await _initialize(service, parent, other)

    assert linked.task_id == parent.id
    assert (await stores.work.get_work_item(parent.id)).status == "draft"


async def test_duplicate_room_including_archived_fails_initialize_get_and_transition(
    stores: _Stores,
) -> None:
    parent, thread = await _parent_and_room(stores)
    duplicate = stores.chat.create_thread(title="duplicate", participants=[], task_id=parent.id)
    stores.chat.update_thread(duplicate.id, archived=True)
    service = _service(stores, _Clock(200.0))
    with pytest.raises(ValueError):
        await _initialize(service, parent, thread)

    stores.chat.delete_thread(duplicate.id)
    contract = await _initialize(service, parent, thread)
    duplicate = stores.chat.create_thread(title="duplicate", participants=[], task_id=parent.id)
    stores.chat.update_thread(duplicate.id, archived=True)
    with pytest.raises(ValueError):
        await service.get_session(parent.id)
    with pytest.raises(ValueError):
        await service.transition_session(parent.id, "executing", expected_revision=contract.revision)


async def test_projection_mismatch_fails_get_and_transition_without_repair(stores: _Stores) -> None:
    service, _clock, parent, _thread, contract = await _bound(stores)
    changed = await stores.work.merge_work_item_metadata(
        parent.id,
        {},
        expected_work_type="crew_session",
        expected_status="open",
        expected_assigned_to="facilitator-1",
        new_status="blocked",
    )
    assert changed is not None and changed.status == "blocked"

    with pytest.raises(ValueError):
        await service.get_session(parent.id)
    with pytest.raises(ValueError):
        await service.transition_session(parent.id, "executing", expected_revision=contract.revision)

    after = await stores.work.get_work_item(parent.id)
    assert after is not None and after.status == "blocked"
    assert after.metadata["crew_session"]["state"] == "discussing"


async def test_server_owned_created_at_mismatch_fails_load_without_repair(
    stores: _Stores,
) -> None:
    service, _clock, parent, _thread, contract = await _bound(stores)
    tampered = contract.model_dump(mode="json")
    tampered["created_at"] = contract.created_at + 1.0
    updated = await stores.work.merge_work_item_metadata(
        parent.id, {"crew_session": tampered},
    )
    assert updated is not None

    with pytest.raises(ValueError, match="crew_session_created_at_mismatch"):
        await service.get_session(parent.id)

    after = await stores.work.get_work_item(parent.id)
    assert after is not None
    assert after.metadata["crew_session"]["created_at"] == contract.created_at + 1.0

    type_service, _clock, type_parent, _thread, _contract = await _bound(stores)
    with pytest.raises(ValueError, match="^crew_session_write_reserved$"):
        await stores.work.update_work_item(type_parent.id, work_type="task")
    assert await type_service.get_session(type_parent.id) is not None

    task_service, _clock, task_parent, _thread, task_contract = await _bound(stores)
    wrong_task = task_contract.model_dump(mode="json")
    wrong_task["task_id"] = "other-task"
    await stores.work.merge_work_item_metadata(
        task_parent.id, {"crew_session": wrong_task},
    )
    with pytest.raises(ValueError, match="crew_session_task_mismatch"):
        await task_service.get_session(task_parent.id)


async def test_malformed_existing_contract_fails_replay_without_repair(stores: _Stores) -> None:
    parent, thread = await _parent_and_room(
        stores, metadata={"crew_session": {"version": 1}},
    )
    service = _service(stores, _Clock(200.0))
    with pytest.raises(ValueError):
        await _initialize(service, parent, thread)
    after = await stores.work.get_work_item(parent.id)
    assert after is not None and after.status == "draft"
    assert after.metadata["crew_session"] == {"version": 1}

    malformed_parent, _thread = await _parent_and_room(
        stores, status="open", metadata={"crew_session": "not-an-object"},
    )
    with pytest.raises(ValueError, match="crew_session_contract_invalid"):
        await service.get_session(malformed_parent.id)


async def test_result_refs_only_on_done_and_terminal_updates_reject(stores: _Stores) -> None:
    service, clock, parent, _thread, contract = await _bound(stores)
    clock.now = 210.0
    with pytest.raises(ValueError, match="crew_session_blocked_reason_required"):
        await service.transition_session(
            parent.id, "blocked_needs_captain", expected_revision=1,
        )
    with pytest.raises(ValueError, match="crew_session_blocked_reason_unexpected"):
        await service.transition_session(
            parent.id, "executing", expected_revision=1,
            blocked_reason="not blocked",
        )
    with pytest.raises(ValueError):
        await service.transition_session(
            parent.id, "executing", expected_revision=1, result_ref=_SHA_A,
        )

    contract = await service.transition_session(parent.id, "executing", expected_revision=1)
    clock.now = 220.0
    contract = await service.transition_session(parent.id, "verifying", expected_revision=2)
    clock.now = 230.0
    contract = await service.transition_session(
        parent.id,
        "done",
        expected_revision=3,
        result_artifact_id="artifact-1",
        result_ref=_SHA_A,
    )
    with pytest.raises(ValueError):
        await service.transition_session(
            parent.id, "done", expected_revision=contract.revision,
            last_result_summary="late update",
        )
    with pytest.raises(ValueError):
        await service.transition_session(
            parent.id, "executing", expected_revision=contract.revision,
        )


async def test_merge_preserves_unrelated_keys_and_expected_values(stores: _Stores) -> None:
    item = await stores.work.create_work_item(
        title="merge", metadata={"origin": "captain", "input_attachments": [1]},
    )
    merged = await stores.work.merge_work_item_metadata(
        item.id,
        {"crew_synth": {"completed": False}},
        expected={"origin": "captain"},
    )
    assert merged is not None
    assert merged.metadata == {
        "origin": "captain",
        "input_attachments": [1],
        "crew_synth": {"completed": False},
    }


async def test_merge_expected_nested_bool_numeric_aliases_conflict(stores: _Stores) -> None:
    current_contract = {
        "nested": {
            "bool_as_number": True,
            "number_as_bool": 0,
            "list_values": [False, 1],
        },
    }
    expected_contract = {
        "nested": {
            "bool_as_number": 1,
            "number_as_bool": False,
            "list_values": [0, True],
        },
    }
    item = await stores.work.create_work_item(
        title="merge",
        metadata={"crew_session": current_contract},
    )

    with pytest.raises(ValueError, match="work_item_metadata_conflict"):
        await stores.work.merge_work_item_metadata(
            item.id,
            {"crew_synth": {"completed": True}},
            expected={"crew_session": expected_contract},
        )

    reloaded = await stores.work.get_work_item(item.id)
    assert reloaded is not None
    assert reloaded.metadata == {"crew_session": current_contract}


async def test_merge_expected_conflict_and_unserializable_patch_do_not_mutate(stores: _Stores) -> None:
    item = await stores.work.create_work_item(title="merge", metadata={"key": "value"})
    before = await stores.work.get_work_item(item.id)
    assert await stores.work.merge_work_item_metadata("missing", {}) is None
    with pytest.raises(ValueError, match="work_item_metadata_patch_invalid"):
        await stores.work.merge_work_item_metadata(item.id, [])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="work_item_metadata_expected_invalid"):
        await stores.work.merge_work_item_metadata(
            item.id, {}, expected=[]  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="work_item_metadata_conflict"):
        await stores.work.merge_work_item_metadata(
            item.id, {"other": 1}, expected={"key": "stale"},
        )
    with pytest.raises((TypeError, ValueError)):
        await stores.work.merge_work_item_metadata(item.id, {"bad": object()})
    with pytest.raises(ValueError, match="work_item_metadata_too_large"):
        await stores.work.merge_work_item_metadata(
            item.id, {"too_large": "x" * 1_048_576},
        )
    after = await stores.work.get_work_item(item.id)
    assert after is not None and before is not None
    assert after.metadata == before.metadata


async def test_merge_status_validation_events_and_true_noop(stores: _Stores) -> None:
    item = await _create_crew_parent(stores)
    stores.events.clear()
    merged = await stores.work.merge_work_item_metadata(
        item.id, {"crew_session": {"revision": 1}}, new_status="open", source="test",
    )
    assert merged is not None and merged.status == "open"
    assert [event for event, _data in stores.events.events] == [
        EventType.WORK_ITEM_UPDATED,
        EventType.WORK_ITEM_STATUS_CHANGED,
    ]
    stores.events.clear()
    before_updated_at = merged.updated_at
    same = await stores.work.merge_work_item_metadata(item.id, {}, new_status="open")
    assert same is not None and same.updated_at == before_updated_at
    assert stores.events.events == []

    gated = await stores.work.create_work_item(
        title="gated",
        work_type="card",
        steps=[{"label": "pending", "status": "pending"}],
    )
    refused = await stores.work.merge_work_item_metadata(
        gated.id,
        {"steps_gate_completion": True},
        new_status="done",
    )
    assert refused is None
    gated_after = await stores.work.get_work_item(gated.id)
    assert gated_after is not None
    assert gated_after.status == "draft"
    assert "steps_gate_completion" not in gated_after.metadata


async def test_concurrent_top_level_merges_preserve_all_four_contract_keys(stores: _Stores) -> None:
    item = await stores.work.create_work_item(title="merge", metadata={})
    await asyncio.gather(
        stores.work.merge_work_item_metadata(item.id, {"origin": "captain"}),
        stores.work.merge_work_item_metadata(item.id, {"input_attachments": [{"id": 1}]}),
        stores.work.merge_work_item_metadata(item.id, {"crew_synth": {"done": False}}),
        stores.work.merge_work_item_metadata(item.id, {"crew_session": {"revision": 1}}),
    )
    reloaded = await stores.work.get_work_item(item.id)
    assert reloaded is not None
    assert set(reloaded.metadata) == {
        "origin", "input_attachments", "crew_synth", "crew_session",
    }


async def test_generic_status_writer_cannot_interleave_after_merge_admission(
    tmp_path: Path,
) -> None:
    factory = _ControlledConnectionFactory()
    store = WorkItemStore(
        db_path=str(tmp_path / "contended.db"),
        tick_interval=1000,
        connection_factory=factory,
    )
    await store.start()
    transition_task: asyncio.Task[CrewSessionContract] | None = None
    writer_task: asyncio.Task[WorkItem | None] | None = None
    try:
        chat = ChatThreadStore(tmp_path / "contended-threads.db")
        local_stores = _Stores(
            work=store,
            chat=chat,
            events=_EventRecorder(),
            admission_port=store.claim_crew_session_admission_port(),
        )
        service, _clock, parent, _thread, _contract = await _bound(local_stores)
        connection = factory.connection
        assert connection is not None
        observed_lock = _ObservedLock()
        store._work_item_row_write_lock = observed_lock
        connection.operations.clear()
        connection.block_next_commit()

        transition_task = asyncio.create_task(
            service.transition_session(parent.id, "executing", expected_revision=1),
        )
        await connection.commit_entered.wait()
        writer_task = asyncio.create_task(
            store.transition_work_item(parent.id, "blocked", source="generic_writer"),
        )
        try:
            await asyncio.wait_for(observed_lock.second_attempted.wait(), timeout=1.0)
            assert not writer_task.done()
            protected_updates = [
                operation for operation in connection.operations
                if operation.startswith("UPDATE work_items")
            ]
            assert len(protected_updates) == 1
        finally:
            connection.release_commit.set()

        transitioned = await transition_task
        with pytest.raises(ValueError, match="^crew_session_write_reserved$"):
            await writer_task
        assert transitioned.state == "executing"
        authoritative = await store.get_work_item(parent.id)
        assert authoritative is not None
        assert authoritative.status == "in_progress"
        first_update = next(
            index for index, operation in enumerate(connection.operations)
            if operation.startswith("UPDATE work_items")
        )
        first_commit = connection.operations.index("COMMIT", first_update)
        assert first_update < first_commit
        assert sum(
            operation.startswith("UPDATE work_items")
            for operation in connection.operations
        ) == 1
    finally:
        if factory.connection is not None:
            factory.connection.release_commit.set()
        pending = [
            task for task in (transition_task, writer_task)
            if task is not None and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await store.stop()


@pytest.mark.parametrize(
    ("failure_point", "error_type", "message"),
    [
        ("update", RuntimeError, "injected update failure"),
        ("commit", RuntimeError, "injected commit failure"),
        ("cancellation", asyncio.CancelledError, "injected cancellation"),
    ],
)
async def test_merge_failure_rolls_back_propagates_and_releases_shared_lock(
    tmp_path: Path,
    failure_point: str,
    error_type: type[BaseException],
    message: str,
) -> None:
    factory = _ControlledConnectionFactory()
    store = WorkItemStore(
        db_path=str(tmp_path / f"failure-{failure_point}.db"),
        tick_interval=1000,
        connection_factory=factory,
    )
    await store.start()
    try:
        item = await store.create_work_item(title="failure", metadata={"origin": "captain"})
        connection = factory.connection
        assert connection is not None
        if failure_point == "update":
            connection.inject_update_error(RuntimeError(message))
        elif failure_point == "commit":
            connection.inject_commit_error(RuntimeError(message))
        else:
            connection.inject_commit_error(asyncio.CancelledError(message))

        with pytest.raises(error_type, match=message):
            await store.merge_work_item_metadata(item.id, {"crew_session": {"revision": 1}})

        assert connection.rollback_attempts == 1
        assert not store._work_item_row_write_lock.locked()
        recovered = await store.merge_work_item_metadata(
            item.id,
            {"crew_session": {"revision": 2}},
        )
        assert recovered is not None
        assert recovered.metadata == {
            "origin": "captain",
            "crew_session": {"revision": 2},
        }
    finally:
        await store.stop()


async def test_input_upload_preserves_origin_session_and_synth(
    stores: _Stores, tmp_path: Path,
) -> None:
    attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")
    sentinels = {
        "origin": "captain",
        "crew_session": {"revision": 7},
        "crew_synth": {"completed": False},
    }
    item = await stores.work.create_work_item(title="upload", metadata=sentinels)
    runtime = SimpleNamespace(
        work_item_store=stores.work,
        attachment_store=attachment_store,
        chat_thread_store=stores.chat,
        config=SystemConfig(),
    )
    chat_router._ATTACHMENT_STORE_CACHE[id(runtime)] = attachment_store
    try:
        blob = b"session context\n"
        await attach_work_item_inputs(
            item.id,
            files=[_upload("context.txt", blob), _upload("copy.txt", blob)],
            runtime=runtime,
        )
    finally:
        chat_router._ATTACHMENT_STORE_CACHE.pop(id(runtime), None)
    reloaded = await stores.work.get_work_item(item.id)
    assert reloaded is not None
    assert reloaded.metadata["origin"] == "captain"
    assert reloaded.metadata["crew_session"] == {"revision": 7}
    assert reloaded.metadata["crew_synth"] == {"completed": False}
    refs = reloaded.metadata["input_attachments"]
    assert len(refs) == 1
    assert refs[0]["content_hash"] == hashlib.sha256(blob).hexdigest()


async def test_crew_synth_writer_preserves_origin_session_and_inputs(stores: _Stores) -> None:
    item = await stores.work.create_work_item(
        title="synth",
        work_type="task",
        assigned_to="lead",
        metadata={
            "origin": "captain",
            "crew_session": {"revision": 4},
            "input_attachments": [{"content_hash": _SHA_A}],
        },
    )
    moved = await stores.work.transition_work_item(item.id, "in_progress")
    assert moved is not None
    synth = CrewSynthesizer(
        llm_client=object(),
        work_item_store=stores.work,
        trust_network=object(),
        episodic_memory=None,
        attachment_store=None,
        runtime=SimpleNamespace(),
    )
    completed = await synth._complete_parent(item.id, _SHA_B, [], [])
    assert completed is True
    reloaded = await stores.work.get_work_item(item.id)
    assert reloaded is not None
    assert reloaded.metadata["origin"] == "captain"
    assert reloaded.metadata["crew_session"] == {"revision": 4}
    assert reloaded.metadata["input_attachments"] == [{"content_hash": _SHA_A}]
    assert reloaded.metadata["crew_synth"]["provenance_ref"] == _SHA_B


async def test_legacy_reopen_keeps_columns_and_values_then_session_reopens(tmp_path: Path) -> None:
    db_path = str(tmp_path / "legacy-workforce.db")
    thread_path = tmp_path / "legacy-threads.db"
    first = WorkItemStore(db_path=db_path, tick_interval=1000)
    await first.start()
    ordinary = await first.create_work_item(
        title="ordinary", work_type="task", metadata={"legacy": [1, "two"]},
    )
    cursor = await first._db.execute("PRAGMA table_info(work_items)")
    before_columns = [row["name"] for row in await cursor.fetchall()]
    await first.stop()

    second = WorkItemStore(db_path=db_path, tick_interval=1000)
    await second.start()
    try:
        cursor = await second._db.execute("PRAGMA table_info(work_items)")
        after_columns = [row["name"] for row in await cursor.fetchall()]
        assert before_columns == after_columns == _WORK_ITEM_COLUMNS
        reloaded = await second.get_work_item(ordinary.id)
        assert reloaded is not None
        assert reloaded.metadata == {"legacy": [1, "two"]}

        chat = ChatThreadStore(thread_path)
        admission_port = second.claim_crew_session_admission_port()
        async with admission_port.reserve() as reservation:
            parent = await reservation.create_parent(CrewSessionParentCreate(
                id="crew-session-legacy",
                title="session",
                description="session",
                assigned_to="facilitator-1",
                created_by="captain",
                metadata={},
            ))
        thread = chat.create_thread(title="room", participants=[], task_id=parent.id)
        clock = _Clock(parent.created_at + 1.0)
        service = CrewSessionService(
            work_item_store=second, chat_thread_store=chat, clock=clock,
        )
        contract = await _initialize(service, parent, thread)
        assert contract.revision == 1
    finally:
        await second.stop()

    third = WorkItemStore(db_path=db_path, tick_interval=1000)
    await third.start()
    try:
        chat = ChatThreadStore(thread_path)
        service = CrewSessionService(
            work_item_store=third,
            chat_thread_store=chat,
            clock=_Clock(parent.created_at + 2.0),
        )
        reopened = await service.get_session(parent.id)
        assert reopened is not None and reopened.revision == 1
        cursor = await third._db.execute("PRAGMA table_info(work_items)")
        assert [row["name"] for row in await cursor.fetchall()] == _WORK_ITEM_COLUMNS
    finally:
        await third.stop()


def test_default_off_wirer_reads_no_store_imports_nothing_and_attaches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SystemConfig()
    assert config.agentic_dispatch.orchestrator_enabled is False
    runtime = _RuntimeAccessRecorder()
    imports = _ImportRecorder(builtins.__import__)
    monkeypatch.setattr(builtins, "__import__", imports)

    assert _wire_crew_session_service(runtime=runtime, config=config) is False
    assert runtime.accesses == []
    assert "probos.cognitive.crew_session" not in imports.names


@pytest.mark.parametrize("missing_dependency", ["work_item_store", "chat_thread_store"])
def test_enabled_wirer_missing_dependencies_fail_and_do_not_attach(
    missing_dependency: str,
) -> None:
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    dependencies = {
        "work_item_store": object(),
        "chat_thread_store": object(),
    }
    dependencies[missing_dependency] = None
    runtime = SimpleNamespace(**dependencies)
    with pytest.raises(
        RuntimeError,
        match=(
            "^crew_session_service_dependency_missing:"
            f"{missing_dependency}$"
        ),
    ):
        _wire_crew_session_service(runtime=runtime, config=config)
    assert not hasattr(runtime, "crew_session_service")


def test_enabled_wirer_real_stores_attaches_once_preserving_identity(
    stores: _Stores,
) -> None:
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    runtime = SimpleNamespace(
        work_item_store=stores.work,
        chat_thread_store=stores.chat,
        registry=object(),
        ontology=object(),
        trust_network=object(),
        llm_client=object(),
        crew_session_service=None,
    )
    assert _wire_crew_session_service(runtime=runtime, config=config) is True
    first = runtime.crew_session_service
    assert isinstance(first, CrewSessionService)
    assert _wire_crew_session_service(runtime=runtime, config=config) is True
    assert runtime.crew_session_service is first


def test_public_service_api_and_annotations_are_exact() -> None:
    public = {
        name for name, value in inspect.getmembers(CrewSessionService, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public == {
        "adopt_recovery_plan",
        "agent_principal",
        "bind_scheduler",
        "captain_principal",
        "compare_and_set_recovery",
        "fail_verified_outcome",
        "get_recovery",
        "initialize_session",
        "get_session",
        "install_recovery_plan",
        "metrics",
        "open_or_resume",
        "publish_verified_result",
        "repair_provisioning",
        "transition_session",
    }
    expected_parameters = {
        "adopt_recovery_plan": {
            "self", "parent_id", "expected_session", "expected_recovery",
            "plan", "expected_children",
        },
        "agent_principal": {"self", "agent_id"},
        "bind_scheduler": {"self", "schedule"},
        "captain_principal": {"self"},
        "compare_and_set_recovery": {
            "self", "parent_id", "recovery", "expected_session",
            "expected_recovery",
        },
        "fail_verified_outcome": {
            "self", "parent_id", "expected_revision", "reason",
            "expected_recovery", "crew_trust_effects", "evidence_refs",
        },
        "get_recovery": {"self", "parent_id"},
        "initialize_session": {
            "self", "parent_id", "thread_id", "goal", "origin", "originator_id",
            "facilitator_id", "owner_ids", "success_criteria", "expected_deliverable",
        },
        "get_session": {"self", "parent_id"},
        "install_recovery_plan": {
            "self", "parent_id", "expected_session", "expected_recovery",
            "plan", "children",
        },
        "metrics": {"self", "days", "limit"},
        "open_or_resume": {
            "self", "principal", "goal", "success_criteria",
            "expected_deliverable", "facilitator_id", "owner_ids",
            "requested_thread_id", "retry_blocked",
        },
        "publish_verified_result": {
            "self", "parent_id", "expected_revision", "expected_recovery",
            "expected_direct_children", "crew_synth", "last_result_summary",
            "provenance_ref", "result_artifact_id", "crew_trust_effects",
        },
        "repair_provisioning": {"self", "limit"},
        "transition_session": {
            "self", "parent_id", "new_state", "expected_revision",
            "last_result_summary", "blocked_reason", "evidence_refs",
            "result_artifact_id", "result_ref", "expected_recovery", "recovery",
        },
    }
    for method_name, parameter_names in expected_parameters.items():
        signature = inspect.signature(getattr(CrewSessionService, method_name))
        assert set(signature.parameters) == parameter_names
        assert signature.return_annotation is not inspect.Signature.empty
        assert all(
            parameter.annotation is not inspect.Signature.empty
            for name, parameter in signature.parameters.items()
            if name != "self"
        )
    constructor = inspect.signature(CrewSessionService.__init__)
    assert set(constructor.parameters) == {
        "self",
        "work_item_store",
        "chat_thread_store",
        "registry",
        "ontology",
        "trust_network",
        "config",
        "compute_similarity",
        "decomposer",
        "admission_port",
        "clock",
    }
    request_fields = tuple(CrewSessionParentCreate.__dataclass_fields__)
    assert request_fields == (
        "id",
        "title",
        "description",
        "assigned_to",
        "created_by",
        "metadata",
        "created_at",
    )
    admission_signatures = {
        CrewSessionParentReservation.create_parent: {
            "self",
            "request",
        },
        CrewSessionAdmissionPort.reserve: {"self"},
        WorkItemStore.claim_crew_session_admission_port: {"self"},
    }
    for method, parameters in admission_signatures.items():
        signature = inspect.signature(method)
        assert set(signature.parameters) == parameters
        assert signature.return_annotation is not inspect.Signature.empty
        assert all(
            parameter.annotation is not inspect.Signature.empty
            for name, parameter in signature.parameters.items()
            if name != "self"
        )


def test_source_has_to_thread_and_no_raw_sqlite_schema_or_lifecycle_path() -> None:
    service_source = inspect.getsource(crew_session_module)
    merge_source = inspect.getsource(WorkItemStore.merge_work_item_metadata)
    assert "asyncio.to_thread" in service_source
    for forbidden in (
        "aiosqlite.connect",
        "sqlite3.connect",
        "CREATE TABLE",
        "ALTER TABLE",
        "CREATE INDEX",
        "ensure_future",
        "async def start",
        "async def stop",
    ):
        assert forbidden not in service_source
        assert forbidden not in merge_source

    service_tree = ast.parse(service_source)
    create_task_calls = [
        node
        for node in ast.walk(service_tree)
        if isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == "create_task"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_task"
        )
    ]
    parents = {
        child: parent
        for parent in ast.walk(service_tree)
        for child in ast.iter_child_nodes(parent)
    }
    calls_by_owner: dict[str, list[ast.Call]] = {}
    owner_nodes: dict[str, ast.AsyncFunctionDef] = {}
    for call in create_task_calls:
        owner = parents.get(call)
        while owner is not None and not isinstance(owner, ast.AsyncFunctionDef):
            owner = parents.get(owner)
        assert isinstance(owner, ast.AsyncFunctionDef)
        calls_by_owner.setdefault(owner.name, []).append(call)
        owner_nodes[owner.name] = owner

    expected_task_owners = {
        "_run_held_to_thread",
        "_reconcile_cancelled_parent_create",
        "_checkpoint_cancelled_provisioning",
        "_reconcile_cancelled_plan_commit",
    }
    assert set(calls_by_owner) == expected_task_owners
    for owner_name in expected_task_owners:
        owner = owner_nodes[owner_name]
        owner_calls = calls_by_owner[owner_name]
        assert len(owner_calls) == 1
        owner_call = owner_calls[0]
        assignments = [
            node
            for node in ast.walk(owner)
            if isinstance(node, ast.Assign) and node.value is owner_call
        ]
        assert len(assignments) == 1
        assert len(assignments[0].targets) == 1
        assert isinstance(assignments[0].targets[0], ast.Name)
        task_variable = assignments[0].targets[0].id
        shield_calls = [
            node
            for node in ast.walk(owner)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "asyncio"
            and node.func.attr == "shield"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == task_variable
        ]
        assert len(shield_calls) == 1
        result_calls = [
            node
            for node in ast.walk(owner)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == task_variable
            and node.func.attr == "result"
        ]
        assert result_calls

    reconciliation_helpers = [
        node
        for node in ast.walk(service_tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_reconcile_cancelled_plan_commit"
    ]
    assert len(reconciliation_helpers) == 1
    reconciliation_helper = reconciliation_helpers[0]
    reconciliation_call = calls_by_owner["_reconcile_cancelled_plan_commit"][0]
    assert reconciliation_call in ast.walk(reconciliation_helper)
    assert len(reconciliation_call.args) == 1
    reconciled_call = reconciliation_call.args[0]
    assert isinstance(reconciled_call, ast.Call)
    assert isinstance(reconciled_call.func, ast.Attribute)
    assert isinstance(reconciled_call.func.value, ast.Name)
    assert reconciled_call.func.value.id == "self"
    assert reconciled_call.func.attr == "_reconcile_plan_commit"

    assert [keyword.arg for keyword in reconciliation_call.keywords] == ["name"]
    task_name = reconciliation_call.keywords[0].value
    assert isinstance(task_name, ast.JoinedStr)
    assert len(task_name.values) == 4
    prefix, policy_value, separator, parent_value = task_name.values
    assert isinstance(prefix, ast.Constant)
    assert prefix.value == "crew-plan-reconcile:"
    assert isinstance(policy_value, ast.FormattedValue)
    assert isinstance(policy_value.value, ast.Name)
    assert policy_value.value.id == "expected_policy"
    assert isinstance(separator, ast.Constant)
    assert separator.value == ":"
    assert isinstance(parent_value, ast.FormattedValue)
    assert isinstance(parent_value.value, ast.Name)
    assert parent_value.value.id == "parent_id"

    assignments = [
        node
        for node in ast.walk(reconciliation_helper)
        if isinstance(node, ast.Assign) and node.value is reconciliation_call
    ]
    assert len(assignments) == 1
    assert len(assignments[0].targets) == 1
    assert isinstance(assignments[0].targets[0], ast.Name)
    assert assignments[0].targets[0].id == "reconciliation"

    shield_calls = [
        node
        for node in ast.walk(reconciliation_helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "asyncio"
        and node.func.attr == "shield"
    ]
    assert len(shield_calls) == 1
    assert len(shield_calls[0].args) == 1
    assert isinstance(shield_calls[0].args[0], ast.Name)
    assert shield_calls[0].args[0].id == "reconciliation"
    assert "create_task" not in merge_source