"""AD-1128: unified CrewSession ingress, dedup, and provisioning."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from probos.cognitive import crew_session as crew_session_module
from probos.cognitive.crew_session import (
    CrewRecoveryContract,
    CrewSessionContract,
    CrewSessionProvisioningContract,
    CrewSessionService,
    _build_derived_recovery_plan,
)
from probos.consensus.trust import TrustNetwork
from probos.config import AgenticDispatchConfig
from probos.consultation.dispatch import WorkItemSpec
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.substrate.registry import AgentRegistry
from probos.threads import ChatThreadStore
from probos.workforce import (
    Booking,
    BookableResource,
    CrewSessionAdmissionPort,
    CrewSessionParentCreate,
    CrewSessionParentReservation,
    WorkItemTemplate,
    WorkItem,
    WorkItemStore,
)


class _NoCallRegistry:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, agent_id: str) -> Any | None:
        self.calls += 1
        raise AssertionError("registry reached before principal authority rejection")


class _NoCallTrust:
    def get_score(self, agent_id: str) -> float:
        raise AssertionError("trust reached before principal authority rejection")


class _Ontology:
    def get_crew_agent_types(self) -> set[str]:
        return {"operations_officer"}


class _NoCallDecomposer:
    def decompose(self, goal: str) -> list[Any]:
        raise AssertionError("decomposer reached before principal authority rejection")


class _SpecDecomposer:
    def __init__(self, specs: list[WorkItemSpec] | None = None) -> None:
        self.specs = specs or [WorkItemSpec(spec_id="spec-a", title="A")]
        self.calls: list[str] = []

    def decompose(self, goal: str) -> list[WorkItemSpec]:
        self.calls.append(goal)
        return list(self.specs)


class _BlockingDecomposer(_SpecDecomposer):
    def __init__(self) -> None:
        import threading

        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def decompose(self, goal: str) -> list[WorkItemSpec]:
        self.calls.append(goal)
        self.entered.set()
        if not self.release.wait(timeout=5.0):
            raise RuntimeError("decomposition barrier timed out")
        return list(self.specs)


class _FailingDecomposer:
    def decompose(self, goal: str) -> list[WorkItemSpec]:
        raise RuntimeError("decomposition failed")


class _PostCommitParentCancelStore(WorkItemStore):
    def __init__(
        self,
        *args: Any,
        first_cancellation: asyncio.CancelledError,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.first_cancellation = first_cancellation
        self.parent_committed = asyncio.Event()
        self.reconciliation_entered = asyncio.Event()
        self.release_reconciliation = asyncio.Event()
        self._raise_after_commit = True

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        if self.parent_committed.is_set() and not self.release_reconciliation.is_set():
            self.reconciliation_entered.set()
            await self.release_reconciliation.wait()
        return await super().get_work_item(work_item_id)


class _PostCommitParentCancelReservation:
    def __init__(
        self,
        delegate: CrewSessionParentReservation,
        store: _PostCommitParentCancelStore,
    ) -> None:
        self._delegate = delegate
        self._store = store

    async def create_parent(
        self,
        request: CrewSessionParentCreate,
    ) -> WorkItem:
        created = await self._delegate.create_parent(request)
        if self._store._raise_after_commit:
            self._store._raise_after_commit = False
            self._store.parent_committed.set()
            raise self._store.first_cancellation
        return created


class _PostCommitParentCancelPort:
    def __init__(
        self,
        delegate: CrewSessionAdmissionPort,
        store: _PostCommitParentCancelStore,
    ) -> None:
        self._delegate = delegate
        self._store = store

    def reserve(
        self,
    ) -> AbstractAsyncContextManager[CrewSessionParentReservation]:
        return self._reserve()

    @asynccontextmanager
    async def _reserve(self) -> Any:
        async with self._delegate.reserve() as reservation:
            yield _PostCommitParentCancelReservation(
                reservation,
                self._store,
            )


class _CreateParentBarrierReservation:
    def __init__(
        self,
        delegate: CrewSessionParentReservation,
        entered: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        self._delegate = delegate
        self._entered = entered
        self._release = release

    async def create_parent(
        self,
        request: CrewSessionParentCreate,
    ) -> WorkItem:
        self._entered.set()
        await self._release.wait()
        return await self._delegate.create_parent(request)


class _CreateParentBarrierPort:
    def __init__(self, delegate: CrewSessionAdmissionPort) -> None:
        self._delegate = delegate
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    def reserve(
        self,
    ) -> AbstractAsyncContextManager[CrewSessionParentReservation]:
        return self._reserve()

    @asynccontextmanager
    async def _reserve(self) -> Any:
        async with self._delegate.reserve() as reservation:
            yield _CreateParentBarrierReservation(
                reservation,
                self.entered,
                self.release,
            )


class _InsertBarrierStore(WorkItemStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.insert_entered = asyncio.Event()
        self.release_insert = asyncio.Event()

    async def _insert_work_item(self, item: WorkItem) -> WorkItem:
        self.insert_entered.set()
        await self.release_insert.wait()
        return await super()._insert_work_item(item)


class _EventRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


class _LegacyBookingStore(WorkItemStore):
    def __init__(
        self,
        *args: Any,
        booking: Booking,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._legacy_booking = booking

    async def get_booking(self, booking_id: str) -> Booking | None:
        if booking_id == self._legacy_booking.id:
            return self._legacy_booking
        return await super().get_booking(booking_id)


class _StartupService:
    def __init__(
        self,
        delegate: CrewSessionService,
        repaired_ids: tuple[str, ...],
    ) -> None:
        self._delegate = delegate
        self._repaired_ids = repaired_ids
        self.repair_limits: list[int] = []
        self.validation_order: list[tuple[str, str]] = []

    async def repair_provisioning(self, *, limit: int) -> tuple[str, ...]:
        self.repair_limits.append(limit)
        return self._repaired_ids

    async def get_session(self, parent_id: str) -> CrewSessionContract | None:
        self.validation_order.append(("session", parent_id))
        return await self._delegate.get_session(parent_id)

    async def get_recovery(self, parent_id: str) -> CrewRecoveryContract | None:
        self.validation_order.append(("recovery", parent_id))
        return await self._delegate.get_recovery(parent_id)


class _RecoveryCandidatesStore:
    def __init__(self, parent_ids: tuple[str, ...]) -> None:
        self.parent_ids = parent_ids
        self.limits: list[int] = []

    async def list_crew_session_recovery_candidates(
        self,
        *,
        limit: int,
    ) -> list[Any]:
        self.limits.append(limit)
        return [SimpleNamespace(id=parent_id) for parent_id in self.parent_ids]


class _StartupScheduleOwner:
    def __init__(self, *, service: Any, store: Any, config: Any) -> None:
        from probos.cognitive.crew_orchestrator import CrewOrchestrator

        class _Owner(CrewOrchestrator):
            def __init__(self, outer: _StartupScheduleOwner) -> None:
                super().__init__(
                    assignment_resolver=object(),
                    delegator=object(),
                    crew_executor=object(),
                    verifier=object(),
                    synthesizer=object(),
                    work_item_store=store,
                    runtime=SimpleNamespace(),
                    config=config,
                    crew_session_service=service,
                )
                self._outer = outer

            def schedule(self, parent_id: str) -> asyncio.Task[Any]:
                self._outer.scheduled_ids.append(parent_id)
                task = asyncio.create_task(self._complete(parent_id))
                self._outer.tasks.append(task)
                return task

            @staticmethod
            async def _complete(parent_id: str) -> Any:
                from probos.cognitive.crew_synth import SynthesisResult

                return SynthesisResult(parent_id, "", False)

        self.scheduled_ids: list[str] = []
        self.tasks: list[asyncio.Task[Any]] = []
        self.owner = _Owner(self)

    async def drain(self) -> None:
        if self.tasks:
            await asyncio.gather(*self.tasks)


def _no_call_scorer(left: str, right: str) -> float:
    raise AssertionError("scorer reached before principal authority rejection")


class _Clock:
    def __init__(self, now: float = 32_503_680_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        value = self.now
        self.now += 1.0
        return value


class _ScoreRecorder:
    def __init__(self, default: float = 0.0) -> None:
        self.default = default
        self.values: dict[tuple[str, str], float] = {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, left: str, right: str) -> float:
        self.calls.append((left, right))
        return self.values.get((left, right), self.default)


class _ScheduleSpy:
    def __init__(self) -> None:
        self.parent_ids: list[str] = []
        self.tasks: list[asyncio.Task[Any]] = []
        self._tasks_by_parent: dict[str, asyncio.Task[Any]] = {}
        self._release = asyncio.Event()

    def __call__(self, parent_id: str) -> asyncio.Task[Any]:
        existing = self._tasks_by_parent.get(parent_id)
        if existing is not None and not existing.done():
            return existing
        self.parent_ids.append(parent_id)
        task = asyncio.create_task(self._complete())
        self.tasks.append(task)
        self._tasks_by_parent[parent_id] = task
        return task

    async def _complete(self) -> None:
        await self._release.wait()

    async def drain(self) -> None:
        self._release.set()
        if self.tasks:
            await asyncio.gather(*self.tasks)


@dataclass
class _Harness:
    work: WorkItemStore
    threads: ChatThreadStore
    registry: AgentRegistry
    trust: TrustNetwork
    scorer: _ScoreRecorder
    schedule: _ScheduleSpy
    service: CrewSessionService
    clock: _Clock
    decomposer: _SpecDecomposer
    admission_port: CrewSessionAdmissionPort
    events: _EventRecorder


class _ThreadIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"crew-thread-{self.value}"


@pytest.fixture
async def ingress_service(tmp_path: Path) -> Any:
    work_items = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await work_items.start()
    admission_port = work_items.claim_crew_session_admission_port()
    registry = _NoCallRegistry()
    service = CrewSessionService(
        work_item_store=work_items,
        chat_thread_store=ChatThreadStore(tmp_path / "threads.db"),
        registry=registry,
        ontology=_Ontology(),
        trust_network=_NoCallTrust(),
        config=AgenticDispatchConfig(orchestrator_enabled=True),
        compute_similarity=_no_call_scorer,
        decomposer=_NoCallDecomposer(),
        admission_port=admission_port,
    )
    try:
        yield service, registry
    finally:
        await work_items.stop()


@pytest.fixture
async def harness(tmp_path: Path) -> Any:
    events = _EventRecorder()
    work = WorkItemStore(
        db_path=str(tmp_path / "workforce-real.db"),
        emit_event=events,
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await work.start()
    admission_port = work.claim_crew_session_admission_port()
    threads = ChatThreadStore(
        tmp_path / "threads-real.db",
        clock=_Clock(2_000.0),
        id_factory=_ThreadIds(),
    )
    registry = AgentRegistry()
    for agent_id in (
        "facilitator-1",
        "owner-2",
        "owner-3",
        "agent-origin",
        "ensign-origin",
    ):
        await registry.register(SimpleNamespace(
            id=agent_id,
            agent_type="operations_officer",
            pool="operations",
        ))
    trust = TrustNetwork()
    trust.create_with_prior("ensign-origin", 1.0, 3.0)
    scorer = _ScoreRecorder()
    schedule = _ScheduleSpy()
    clock = _Clock()
    decomposer = _SpecDecomposer()
    service = CrewSessionService(
        work_item_store=work,
        chat_thread_store=threads,
        registry=registry,
        ontology=_Ontology(),
        trust_network=trust,
        config=AgenticDispatchConfig(orchestrator_enabled=True),
        compute_similarity=scorer,
        decomposer=decomposer,
        admission_port=admission_port,
        clock=clock,
    )
    service.bind_scheduler(schedule)
    active = _Harness(
        work=work,
        threads=threads,
        registry=registry,
        trust=trust,
        scorer=scorer,
        schedule=schedule,
        service=service,
        clock=clock,
        decomposer=decomposer,
        admission_port=admission_port,
        events=events,
    )
    try:
        yield active
    finally:
        await schedule.drain()
        await work.stop()


async def _create_reserved_parent(
    work: WorkItemStore,
    admission_port: CrewSessionAdmissionPort,
    *,
    parent_id: str,
    title: str,
    assigned_to: str,
    created_by: str,
    metadata: dict[str, Any] | None = None,
    created_at: float | None = None,
) -> WorkItem:
    async with admission_port.reserve() as reservation:
        return await reservation.create_parent(CrewSessionParentCreate(
            id=parent_id,
            title=title,
            description=title,
            assigned_to=assigned_to,
            created_by=created_by,
            metadata=dict(metadata or {}),
            created_at=created_at,
        ))


async def _requirement_parent_ids(work: WorkItemStore) -> list[str]:
    assert work._db is not None
    cursor = await work._db.execute(
        "SELECT work_item_id FROM resource_requirements ORDER BY work_item_id",
    )
    return [row["work_item_id"] for row in await cursor.fetchall()]


async def _create_bound_session(
    harness: _Harness,
    *,
    parent_id: str = "session-parent",
    goal: str = "Produce a verified report",
    origin: str = "captain",
    originator_id: str = "captain",
    facilitator_id: str = "facilitator-1",
    owner_ids: list[str] | None = None,
    success_criteria: list[str] | None = None,
    expected_deliverable: str = "A verified report",
    created_at: float = 100.0,
) -> tuple[WorkItem, Any, CrewSessionContract]:
    owners = list(owner_ids or [facilitator_id, "owner-2"])
    parent = await _create_reserved_parent(
        harness.work,
        harness.admission_port,
        parent_id=parent_id,
        title="Crew session",
        assigned_to=facilitator_id,
        created_by=("captain" if origin == "captain" else originator_id),
        created_at=created_at,
    )
    thread = harness.threads.create_thread(
        title="Crew room",
        participants=owners,
        task_id=parent.id,
    )
    session = await harness.service.initialize_session(
        parent.id,
        thread.id,
        goal=goal,
        origin=origin,
        originator_id=originator_id,
        facilitator_id=facilitator_id,
        owner_ids=owners,
        success_criteria=list(success_criteria or ["Report is complete"]),
        expected_deliverable=expected_deliverable,
    )
    return parent, thread, session


async def _seed_session_authority(
    harness: _Harness,
    *,
    parent_id: str,
    created_by: str,
    origin: str,
    originator_id: str,
    facilitator_id: str,
    owner_ids: list[str],
    created_at: float,
) -> tuple[WorkItem, Any, dict[str, Any]]:
    parent = await _create_reserved_parent(
        harness.work,
        harness.admission_port,
        parent_id=parent_id,
        title=parent_id,
        assigned_to=facilitator_id,
        created_by=created_by,
        created_at=created_at,
    )
    thread = harness.threads.create_thread(
        title=parent_id,
        participants=list(owner_ids),
        task_id=parent.id,
    )
    contract = {
        "version": 1,
        "state": "discussing",
        "previous_state": None,
        "revision": 1,
        "goal": f"Goal for {parent_id}",
        "origin": origin,
        "originator_id": originator_id,
        "facilitator_id": facilitator_id,
        "owner_ids": list(owner_ids),
        "success_criteria": ["Complete"],
        "expected_deliverable": "Result",
        "thread_id": thread.id,
        "task_id": parent.id,
        "created_at": parent.created_at,
        "transitioned_at": parent.created_at,
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
    updated = await harness.work.merge_work_item_metadata(
        parent.id,
        {"crew_session": contract},
        expected_absent_keys=frozenset({"crew_session", "crew_recovery"}),
        expected_work_type="crew_session",
        expected_status="draft",
        expected_assigned_to=facilitator_id,
        new_status="open",
    )
    assert updated is not None
    return updated, thread, contract


def test_ingress_config_defaults_are_bounded() -> None:
    config = AgenticDispatchConfig()

    assert config.crew_ingress_scan_limit == 100
    assert config.crew_ingress_semantic_call_limit == 32
    assert config.crew_ingress_semantic_threshold == 0.90
    assert config.crew_provisioning_repair_limit == 100


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("crew_ingress_scan_limit", 0),
        ("crew_ingress_scan_limit", 1_001),
        ("crew_ingress_semantic_call_limit", 0),
        ("crew_ingress_semantic_call_limit", 129),
        ("crew_ingress_semantic_threshold", float("nan")),
        ("crew_ingress_semantic_threshold", 1.01),
        ("crew_provisioning_repair_limit", 0),
        ("crew_provisioning_repair_limit", 1_001),
    ],
)
def test_ingress_config_rejects_out_of_bounds(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        AgenticDispatchConfig(**{field: value})


def test_ingress_config_semantic_limit_cannot_exceed_scan_limit() -> None:
    with pytest.raises(ValidationError, match="semantic_call_limit"):
        AgenticDispatchConfig(
            crew_ingress_scan_limit=4,
            crew_ingress_semantic_call_limit=5,
        )


async def test_store_crew_session_admission_port_claim_is_one_shot_and_typed(
    tmp_path: Path,
) -> None:
    store = WorkItemStore(
        db_path=str(tmp_path / "claim.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    try:
        port = store.claim_crew_session_admission_port()

        assert callable(port.reserve)
        with pytest.raises(
            RuntimeError,
            match="^crew_session_admission_port_claimed$",
        ):
            store.claim_crew_session_admission_port()
    finally:
        await store.stop()


async def test_store_crew_session_reservation_is_task_scoped_one_use_and_detached(
    tmp_path: Path,
) -> None:
    events = _EventRecorder()
    store = _InsertBarrierStore(
        db_path=str(tmp_path / "reservation.db"),
        emit_event=events,
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    port = store.claim_crew_session_admission_port()
    retained: CrewSessionParentReservation | None = None
    create_task: asyncio.Task[WorkItem] | None = None
    metadata = {"crew_provisioning": {"version": 1, "phase": "parent_created"}}
    request = CrewSessionParentCreate(
        id="crew-session-reservation",
        title="Reservation",
        description="Reservation",
        assigned_to="facilitator-1",
        created_by="captain",
        metadata=metadata,
        created_at=100.0,
    )
    try:
        async with port.reserve() as reservation:
            retained = reservation

            async def child_create() -> WorkItem:
                return await reservation.create_parent(request)

            with pytest.raises(
                RuntimeError,
                match="^crew_session_admission_reservation_invalid$",
            ):
                await asyncio.create_task(child_create())

            create_task = asyncio.create_task(reservation.create_parent(request))
            with pytest.raises(
                RuntimeError,
                match="^crew_session_admission_reservation_invalid$",
            ):
                await create_task
            create_task = None

            async def mutate_after_detach() -> None:
                await store.insert_entered.wait()
                request.metadata["crew_provisioning"]["phase"] = "failed"
                request.metadata["late"] = True
                store.release_insert.set()

            mutator = asyncio.create_task(mutate_after_detach())
            created = await reservation.create_parent(request)
            await mutator

            assert created.metadata == {
                "crew_provisioning": {
                    "version": 1,
                    "phase": "parent_created",
                },
            }
            with pytest.raises(
                RuntimeError,
                match="^crew_session_admission_reservation_invalid$",
            ):
                await reservation.create_parent(request)

        assert retained is not None
        with pytest.raises(
            RuntimeError,
            match="^crew_session_admission_reservation_invalid$",
        ):
            await retained.create_parent(request)
        assert len(events.events) == 1
    finally:
        store.release_insert.set()
        if create_task is not None and not create_task.done():
            create_task.cancel()
            await asyncio.gather(create_task, return_exceptions=True)
        await store.stop()


async def test_generic_crew_session_writers_and_router_reject_before_side_effects(
    tmp_path: Path,
) -> None:
    from probos.routers import workforce as workforce_router
    from probos.routers.deps import get_runtime, get_ws_broadcast

    events = _EventRecorder()
    store = WorkItemStore(
        db_path=str(tmp_path / "generic-reject.db"),
        emit_event=events,
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    port = store.claim_crew_session_admission_port()
    parent = await _create_reserved_parent(
        store,
        port,
        parent_id="crew-session-generic",
        title="Generic boundary",
        assigned_to="facilitator-1",
        created_by="captain",
    )
    baseline_events = list(events.events)
    store.template_store.register(WorkItemTemplate(
        template_id="crew-session-template",
        name="Crew Session",
        description="Reserved parent",
        work_type="crew_session",
        title_pattern="Crew Session",
    ))
    try:
        for operation in (
            lambda: store.create_work_item(
                title="blocked",
                work_type="crew_session",
            ),
            lambda: store.create_from_template("crew-session-template"),
            lambda: store.update_work_item(parent.id, title="blocked"),
            lambda: store.update_work_item(
                parent.id,
                work_type="crew_session",
            ),
            lambda: store.transition_work_item(parent.id, parent.status),
        ):
            with pytest.raises(ValueError, match="^crew_session_write_reserved$"):
                await operation()
        assert await store.get_work_item(parent.id) == parent
        assert events.events == baseline_events
        assert await _requirement_parent_ids(store) == [parent.id]

        app = FastAPI()
        app.include_router(workforce_router.router)
        runtime = SimpleNamespace(work_item_store=store)
        app.dependency_overrides[get_runtime] = lambda: runtime
        app.dependency_overrides[get_ws_broadcast] = lambda: (lambda _event: None)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            responses = [
                await client.post(
                    "/api/work-items",
                    json={"title": "blocked", "work_type": "crew_session"},
                ),
                await client.post(
                    "/api/work-items/from-template/crew-session-template",
                    json={},
                ),
                await client.patch(
                    f"/api/work-items/{parent.id}",
                    json={"title": "blocked"},
                ),
                await client.post(
                    f"/api/work-items/{parent.id}/transition",
                    json={"status": parent.status},
                ),
                await client.post(
                    f"/api/work-items/{parent.id}/assign",
                    json={"resource_id": "facilitator-1"},
                ),
                await client.post(
                    "/api/work-items/claim",
                    json={
                        "resource_id": "facilitator-1",
                        "work_type": "crew_session",
                    },
                ),
            ]
        assert [response.status_code for response in responses] == [409] * 6
        assert all(
            response.json()["detail"] == "crew_session_write_reserved"
            for response in responses
        )
        assert await store.list_bookings(work_item_id=parent.id) == []
        assert await _requirement_parent_ids(store) == [parent.id]
        assert events.events == baseline_events
    finally:
        await store.stop()


async def test_generic_child_work_type_remains_writable(
    tmp_path: Path,
) -> None:
    store = WorkItemStore(
        db_path=str(tmp_path / "child-compatible.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    try:
        child = await store.create_work_item(
            id="child-compatible",
            title="Child",
            work_type="task",
            assigned_to="agent-1",
        )
        moved = await store.transition_work_item(child.id, "in_progress")
        changed = await store.update_work_item(child.id, title="Changed child")

        assert moved is not None and moved.status == "in_progress"
        assert changed is not None and changed.title == "Changed child"
    finally:
        await store.stop()


async def test_crew_session_claim_unassign_and_booking_paths_reject_before_side_effects(
    tmp_path: Path,
) -> None:
    legacy_booking = Booking(
        id="legacy-booking",
        resource_id="facilitator-1",
        work_item_id="crew-session-booking",
        status="scheduled",
        start_time=100.0,
    )
    events = _EventRecorder()
    store = _LegacyBookingStore(
        db_path=str(tmp_path / "booking-reject.db"),
        emit_event=events,
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
        booking=legacy_booking,
    )
    await store.start()
    port = store.claim_crew_session_admission_port()
    parent = await _create_reserved_parent(
        store,
        port,
        parent_id=legacy_booking.work_item_id,
        title="Booking boundary",
        assigned_to="facilitator-1",
        created_by="captain",
    )
    store.register_resource(BookableResource(
        resource_id="facilitator-1",
        resource_type="crew",
        active=True,
    ))
    baseline_events = list(events.events)
    try:
        operations = (
            lambda: store.assign_work_item(parent.id, "facilitator-1"),
            lambda: store.claim_work_item(
                "facilitator-1",
                work_type="crew_session",
            ),
            lambda: store.unassign_work_item(parent.id),
            lambda: store.start_booking(legacy_booking.id),
            lambda: store.complete_booking(
                legacy_booking.id,
                tokens_consumed=1,
            ),
        )
        for operation in operations:
            with pytest.raises(ValueError, match="^crew_session_write_reserved$"):
                await operation()

        authoritative = await store.get_work_item(parent.id)
        assert authoritative == parent
        assert await store.list_bookings(work_item_id=parent.id) == []
        assert events.events == baseline_events
    finally:
        await store.stop()


async def test_captain_principal_is_server_owned(ingress_service: Any) -> None:
    service, _ = ingress_service

    principal = service.captain_principal()

    assert principal.origin == "captain"
    assert principal.originator_id == "captain"
    assert principal.created_by == "captain"


async def test_agent_principal_preserves_validated_id(ingress_service: Any) -> None:
    service, registry = ingress_service

    principal = service.agent_principal("crew-agent-1")

    assert principal.origin == "agent"
    assert principal.originator_id == "crew-agent-1"
    assert principal.created_by == "crew-agent-1"
    assert registry.calls == 0


@pytest.mark.parametrize(
    (
        "created_by",
        "origin",
        "originator_id",
        "facilitator_id",
        "owners",
        "valid",
    ),
    [
        ("captain", "captain", "captain", "facilitator-1", ["facilitator-1"], True),
        ("agent-origin", "agent", "agent-origin", "agent-origin", ["agent-origin"], True),
        ("captain", "captain", "captain-other", "facilitator-1", ["facilitator-1"], False),
        ("captain-other", "captain", "captain", "facilitator-1", ["facilitator-1"], False),
        ("captain", "Captain", "captain", "facilitator-1", ["facilitator-1"], False),
        ("owner-2", "agent", "agent-origin", "agent-origin", ["agent-origin"], False),
    ],
)
async def test_loaded_captain_and_agent_provenance_is_exact_before_scorer_or_write(
    harness: _Harness,
    created_by: str,
    origin: str,
    originator_id: str,
    facilitator_id: str,
    owners: list[str],
    valid: bool,
) -> None:
    parent_id = f"provenance-{len(harness.events.events)}-{created_by}-{originator_id}"
    parent, thread, contract = await _seed_session_authority(
        harness,
        parent_id=parent_id,
        created_by=created_by,
        origin=origin,
        originator_id=originator_id,
        facilitator_id=facilitator_id,
        owner_ids=owners,
        created_at=100.0 + len(harness.events.events),
    )
    events_before = list(harness.events.events)
    scorer_before = list(harness.scorer.calls)
    schedule_before = list(harness.schedule.parent_ids)
    room_before = thread.to_dict()

    if valid:
        loaded = await harness.service.get_session(parent.id)
        assert loaded is not None
        assert loaded.origin == origin
        assert loaded.originator_id == originator_id
    else:
        with pytest.raises(ValueError, match="^crew_session_provenance_invalid$"):
            await harness.service.get_session(parent.id)
        with pytest.raises(ValueError, match="^crew_session_provenance_invalid$"):
            await harness.service.open_or_resume(
                principal=harness.service.captain_principal(),
                goal=contract["goal"],
                success_criteria=list(contract["success_criteria"]),
                expected_deliverable=contract["expected_deliverable"],
                facilitator_id="facilitator-1",
            )
        assert harness.scorer.calls == scorer_before
        assert harness.decomposer.calls == []
        assert harness.events.events == events_before
        assert harness.schedule.parent_ids == schedule_before
        assert harness.threads.get_thread(thread.id).to_dict() == room_before


async def test_provisioning_and_initialize_reject_forged_provenance_without_mutation(
    harness: _Harness,
) -> None:
    request = crew_session_module._normalize_ingress_values(
        goal="Forged provisioning",
        success_criteria=["Complete"],
        expected_deliverable="Result",
    )
    raw_marker = {
        "version": 1,
        "provision_id": "7" * 64,
        "phase": "parent_created",
        "room_policy": "create",
        "thread_id": "crew-room-" + "7" * 64,
        "goal": request.display_goal,
        "goal_fingerprint": request.goal_fingerprint,
        "origin": "captain",
        "originator_id": "Captain",
        "created_by": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1"],
        "success_criteria": ["Complete"],
        "expected_deliverable": "Result",
        "plan_specs": crew_session_module._project_decomposition([
            WorkItemSpec(spec_id="spec-forged", title="Forged"),
        ]),
        "last_error_code": None,
    }
    with pytest.raises(ValueError, match="crew_session_provenance_invalid"):
        CrewSessionProvisioningContract.model_validate(raw_marker)
    with pytest.raises(ValueError, match="^crew_session_provenance_invalid$"):
        harness.service._parse_provisioning(raw_marker)

    parent = await _create_reserved_parent(
        harness.work,
        harness.admission_port,
        parent_id="initialize-forged",
        title="Initialize forged",
        assigned_to="facilitator-1",
        created_by="owner-2",
        created_at=100.0,
    )
    room = harness.threads.create_thread(
        title="Initialize forged",
        participants=["facilitator-1"],
        task_id=parent.id,
    )
    events_before = list(harness.events.events)

    with pytest.raises(ValueError, match="^crew_session_provenance_invalid$"):
        await harness.service.initialize_session(
            parent.id,
            room.id,
            goal="Initialize forged",
            origin="captain",
            originator_id="captain",
            facilitator_id="facilitator-1",
            owner_ids=["facilitator-1"],
            success_criteria=["Complete"],
            expected_deliverable="Result",
        )

    authoritative = await harness.work.get_work_item(parent.id)
    assert authoritative is not None
    assert authoritative.status == "draft"
    assert authoritative.metadata == {}
    assert harness.events.events == events_before
    assert harness.threads.get_thread(room.id).task_id == parent.id

    valid_marker = dict(raw_marker)
    valid_marker["originator_id"] = "captain"
    marker = CrewSessionProvisioningContract.model_validate(valid_marker)
    repair_parent = await _create_reserved_parent(
        harness.work,
        harness.admission_port,
        parent_id="repair-forged",
        title="Repair forged",
        assigned_to="facilitator-1",
        created_by="owner-2",
        metadata={"crew_provisioning": marker.model_dump(mode="json")},
        created_at=101.0,
    )
    repair_before = repair_parent.to_dict()
    repair_events = list(harness.events.events)

    with pytest.raises(ValueError, match="^crew_session_provenance_invalid$"):
        await harness.service.repair_provisioning(limit=10)

    repair_after = await harness.work.get_work_item(repair_parent.id)
    assert repair_after is not None
    assert repair_after.to_dict() == repair_before
    assert harness.events.events == repair_events
    assert harness.threads.get_thread(marker.thread_id) is None


async def test_open_or_resume_rejects_forged_principal_before_dependencies(
    ingress_service: Any,
) -> None:
    service, registry = ingress_service
    forged = crew_session_module.CrewSessionPrincipal(
        origin="captain",
        originator_id="captain",
        created_by="captain",
        _authority=object(),
    )

    with pytest.raises(ValueError, match="crew_session_principal_invalid"):
        await service.open_or_resume(
            principal=forged,
            goal="Produce a verified report",
            success_criteria=["The report is complete"],
            expected_deliverable="A verified report",
            facilitator_id="facilitator-1",
        )

    assert registry.calls == 0


async def test_open_or_resume_canonical_exact_resumes_without_scorer(
    harness: _Harness,
) -> None:
    parent, thread, original = await _create_bound_session(
        harness,
        goal="Ｆｏｏ\t BAR",
        success_criteria=["  Result\nIS complete  "],
        expected_deliverable=" A VERIFIED report ",
    )

    result = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="foo bar",
        success_criteria=["result is COMPLETE"],
        expected_deliverable="a verified REPORT",
        facilitator_id="facilitator-1",
        owner_ids=["owner-3"],
    )

    assert result.disposition == "resumed"
    assert result.parent_id == parent.id
    assert result.thread_id == thread.id
    assert result.owner_ids == ("facilitator-1", "owner-2", "owner-3")
    assert result.duplicate_resume_count == 1
    assert result.scheduled is True
    assert harness.scorer.calls == []
    assert harness.schedule.parent_ids == [parent.id]
    stored = await harness.service.get_session(parent.id)
    assert stored is not None
    assert stored.origin == original.origin
    assert stored.originator_id == original.originator_id
    assert stored.goal == original.goal
    assert harness.threads.get_thread(thread.id).participants == [
        "facilitator-1",
        "owner-2",
        "owner-3",
    ]


async def test_open_or_resume_punctuation_difference_is_not_exact(
    harness: _Harness,
) -> None:
    await _create_bound_session(harness, goal="Report: alpha")

    result = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="Report alpha",
        success_criteria=["Report is complete"],
        expected_deliverable="A verified report",
        facilitator_id="facilitator-1",
    )

    assert result.disposition == "created"
    assert harness.scorer.calls == [
        ("report alpha", "report: alpha"),
        ("report alpha", "report: alpha"),
    ]
    assert harness.schedule.parent_ids == [result.parent_id]


async def test_open_or_resume_ensign_rejects_before_scan(
    harness: _Harness,
) -> None:
    with pytest.raises(ValueError, match="crew_session_agent_rank_insufficient"):
        await harness.service.open_or_resume(
            principal=harness.service.agent_principal("ensign-origin"),
            goal="Produce a report",
            success_criteria=["Report is complete"],
            expected_deliverable="A verified report",
        )

    assert harness.scorer.calls == []
    assert harness.schedule.parent_ids == []


async def test_open_or_resume_blocked_counts_once_without_schedule(
    harness: _Harness,
) -> None:
    parent, _, session = await _create_bound_session(harness)
    blocked = await harness.service.transition_session(
        parent.id,
        "blocked_needs_captain",
        expected_revision=session.revision,
        blocked_reason="child_tool_blocked",
    )

    result = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal=blocked.goal,
        success_criteria=list(blocked.success_criteria),
        expected_deliverable=blocked.expected_deliverable,
        facilitator_id="facilitator-1",
    )

    assert result.disposition == "blocked"
    assert result.state == "blocked_needs_captain"
    assert result.duplicate_resume_count == 1
    assert result.scheduled is False
    assert harness.schedule.parent_ids == []


@pytest.mark.parametrize(
    "goal",
    [
        "",
        " \t\n ",
        "bad\x00goal",
        "bad\ud800goal",
        "x" * 4_097,
    ],
)
async def test_open_or_resume_rejects_invalid_goal_before_scan(
    harness: _Harness,
    goal: str,
) -> None:
    with pytest.raises(ValueError, match="crew_session_ingress_text"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal=goal,
            success_criteria=["Complete"],
            expected_deliverable="Result",
            facilitator_id="facilitator-1",
        )

    assert harness.scorer.calls == []
    assert harness.decomposer.calls == []


async def test_open_or_resume_criteria_order_and_deliverable_are_identity(
    harness: _Harness,
) -> None:
    parent, _, _ = await _create_bound_session(
        harness,
        success_criteria=["One", "Two"],
        expected_deliverable="Report",
    )

    reordered = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="Produce a verified report",
        success_criteria=["Two", "One"],
        expected_deliverable="Report",
        facilitator_id="facilitator-1",
    )
    changed_deliverable = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="Produce a verified report",
        success_criteria=["One", "Two"],
        expected_deliverable="Workbook",
        facilitator_id="facilitator-1",
    )

    assert reordered.parent_id != parent.id
    assert changed_deliverable.parent_id not in {parent.id, reordered.parent_id}


async def test_open_or_resume_semantic_threshold_and_tie_are_deterministic(
    harness: _Harness,
) -> None:
    older, _, _ = await _create_bound_session(
        harness,
        parent_id="older-parent",
        goal="Alpha report",
        created_at=50.0,
    )
    await _create_bound_session(
        harness,
        parent_id="newer-parent",
        goal="Beta report",
        created_at=60.0,
    )
    harness.scorer.values[("semantic report", "alpha report")] = 0.90
    harness.scorer.values[("semantic report", "beta report")] = 0.90

    result = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="Semantic report",
        success_criteria=["Report is complete"],
        expected_deliverable="A verified report",
        facilitator_id="facilitator-1",
    )

    assert result.parent_id == older.id
    assert harness.scorer.calls == [
        ("semantic report", "alpha report"),
        ("semantic report", "beta report"),
    ]
    assert harness.decomposer.calls == []


@pytest.mark.parametrize(
    "score",
    [True, 1, float("nan"), float("inf"), -0.1, 1.1],
)
async def test_open_or_resume_rejects_invalid_scorer_output(
    harness: _Harness,
    score: Any,
) -> None:
    await _create_bound_session(harness, goal="Candidate")
    harness.scorer.default = score

    with pytest.raises(ValueError, match="crew_session_similarity_invalid"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal="Requested",
            success_criteria=["Report is complete"],
            expected_deliverable="A verified report",
            facilitator_id="facilitator-1",
        )


async def test_ingress_scan_overflow_fails_without_decomposition(
    harness: _Harness,
) -> None:
    harness.service._config = AgenticDispatchConfig(
        orchestrator_enabled=True,
        crew_ingress_scan_limit=1,
        crew_ingress_semantic_call_limit=1,
    )
    await _create_bound_session(harness, parent_id="parent-a", goal="A")
    await _create_bound_session(harness, parent_id="parent-b", goal="B")

    with pytest.raises(ValueError, match="crew_session_ingress_scan_overflow"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal="C",
            success_criteria=["Report is complete"],
            expected_deliverable="A verified report",
            facilitator_id="facilitator-1",
        )

    assert harness.decomposer.calls == []


async def test_semantic_call_overflow_fails_without_scorer(
    harness: _Harness,
) -> None:
    harness.service._config = AgenticDispatchConfig(
        orchestrator_enabled=True,
        crew_ingress_scan_limit=10,
        crew_ingress_semantic_call_limit=1,
    )
    await _create_bound_session(harness, parent_id="parent-a", goal="A")
    await _create_bound_session(harness, parent_id="parent-b", goal="B")

    with pytest.raises(ValueError, match="crew_session_semantic_scan_overflow"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal="C",
            success_criteria=["Report is complete"],
            expected_deliverable="A verified report",
            facilitator_id="facilitator-1",
        )

    assert harness.scorer.calls == []


async def test_open_or_resume_provisions_parent_room_plan_and_clears_marker(
    harness: _Harness,
) -> None:
    result = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="Build the report",
        success_criteria=["Report is complete"],
        expected_deliverable="A verified report",
        facilitator_id="facilitator-1",
        owner_ids=["owner-2"],
    )

    parent = await harness.work.get_work_item(result.parent_id)
    assert result.disposition == "created"
    assert result.scheduled is True
    assert parent is not None
    assert parent.created_by == "captain"
    assert "crew_provisioning" not in parent.metadata
    assert parent.metadata["crew_session"]["transitioned_at"] > parent.created_at
    assert parent.metadata["crew_session"]["origin"] == "captain"
    assert parent.metadata["crew_session"]["originator_id"] == "captain"
    assert parent.metadata["crew_recovery"]["phase"] == "planned"
    assert harness.threads.get_thread(result.thread_id).task_id == result.parent_id
    children = await harness.work.list_work_items(
        parent_id=result.parent_id,
        limit=10,
    )
    assert len(children) == 1


@pytest.mark.parametrize(("caller_count", "duplicate_count"), [(2, 1), (3, 2)])
async def test_concurrent_equivalent_calls_create_one_authority_and_count_duplicate(
    harness: _Harness,
    caller_count: int,
    duplicate_count: int,
) -> None:
    async def open_one() -> Any:
        return await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal="Coordinate response",
            success_criteria=["Response is complete"],
            expected_deliverable="Verified response",
            facilitator_id="facilitator-1",
        )

    results = await asyncio.gather(*(open_one() for _ in range(caller_count)))

    assert len({result.parent_id for result in results}) == 1
    assert len({result.thread_id for result in results}) == 1
    stored = await harness.service.get_session(results[0].parent_id)
    assert stored is not None and stored.duplicate_resume_count == duplicate_count
    assert harness.decomposer.calls == ["Coordinate response"]
    assert harness.schedule.parent_ids == [results[0].parent_id]


async def test_scan2_reservation_blocks_generic_parent_and_commits_one_authority(
    harness: _Harness,
) -> None:
    barrier = _CreateParentBarrierPort(harness.admission_port)
    harness.service._admission_port = barrier
    before_events = len(harness.events.events)
    opening = asyncio.create_task(harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="Reserved race",
        success_criteria=["Complete"],
        expected_deliverable="Result",
        facilitator_id="facilitator-1",
    ))
    try:
        await barrier.entered.wait()
        with pytest.raises(ValueError, match="^crew_session_write_reserved$"):
            await harness.work.create_work_item(
                id="generic-racer",
                title="Generic racer",
                work_type="crew_session",
            )
        assert await harness.work.list_work_items(limit=20) == []
        assert len(harness.events.events) == before_events

        barrier.release.set()
        result = await opening

        parents = await harness.work.list_work_items(
            work_type="crew_session",
            limit=10,
        )
        children = await harness.work.list_work_items(
            parent_id=result.parent_id,
            limit=10,
        )
        assert [parent.id for parent in parents] == [result.parent_id]
        assert len(children) == 1
        assert harness.threads.get_thread(result.thread_id).task_id == result.parent_id
        assert harness.schedule.parent_ids == [result.parent_id]
        assert await harness.work.get_work_item("generic-racer") is None
        requirement_ids = await _requirement_parent_ids(harness.work)
        assert requirement_ids.count(result.parent_id) == 1
        assert "generic-racer" not in requirement_ids
        assert len(harness.events.events) > before_events
    finally:
        barrier.release.set()
        if not opening.done():
            opening.cancel()
            await asyncio.gather(opening, return_exceptions=True)


async def test_distinct_goals_create_distinct_authorities(
    harness: _Harness,
) -> None:
    first = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="Alpha",
        success_criteria=["Complete"],
        expected_deliverable="Result",
        facilitator_id="facilitator-1",
    )
    second = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="Beta",
        success_criteria=["Complete"],
        expected_deliverable="Result",
        facilitator_id="facilitator-1",
    )

    assert first.parent_id != second.parent_id


async def test_second_scan_resumes_external_winner_without_writing_before_release(
    harness: _Harness,
) -> None:
    blocker = _BlockingDecomposer()
    harness.service._decomposer = blocker
    pending = asyncio.create_task(harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="External winner",
        success_criteria=["Complete"],
        expected_deliverable="Result",
        facilitator_id="facilitator-1",
    ))
    await asyncio.to_thread(blocker.entered.wait, 2.0)
    assert await harness.work.list_work_items(limit=20) == []
    winner, _, _ = await _create_bound_session(
        harness,
        parent_id="external-parent",
        goal="External winner",
        success_criteria=["Complete"],
        expected_deliverable="Result",
    )
    blocker.release.set()

    result = await pending

    assert result.parent_id == winner.id
    assert result.disposition == "resumed"


async def test_decomposition_failure_and_cancellation_write_nothing(
    harness: _Harness,
) -> None:
    harness.service._decomposer = _FailingDecomposer()
    with pytest.raises(ValueError, match="crew_session_decomposition_failed"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal="Failure",
            success_criteria=["Complete"],
            expected_deliverable="Result",
            facilitator_id="facilitator-1",
        )
    assert await harness.work.list_work_items(limit=20) == []

    blocker = _BlockingDecomposer()
    harness.service._decomposer = blocker
    pending = asyncio.create_task(harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="Cancelled",
        success_criteria=["Complete"],
        expected_deliverable="Result",
        facilitator_id="facilitator-1",
    ))
    await asyncio.to_thread(blocker.entered.wait, 2.0)
    pending.cancel()
    blocker.release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert await harness.work.list_work_items(limit=20) == []


async def test_parent_create_repeated_cancel_preserves_first_and_marker(
    tmp_path: Path,
) -> None:
    first_cancellation = asyncio.CancelledError("parent-create-first")
    work = _PostCommitParentCancelStore(
        db_path=str(tmp_path / "parent-cancel.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
        first_cancellation=first_cancellation,
    )
    await work.start()
    admission_port = _PostCommitParentCancelPort(
        work.claim_crew_session_admission_port(),
        work,
    )
    threads = ChatThreadStore(tmp_path / "parent-cancel-threads.db")
    registry = AgentRegistry()
    await registry.register(SimpleNamespace(
        id="facilitator-1",
        agent_type="operations_officer",
        pool="operations",
    ))
    service = CrewSessionService(
        work_item_store=work,
        chat_thread_store=threads,
        registry=registry,
        ontology=_Ontology(),
        trust_network=TrustNetwork(),
        config=AgenticDispatchConfig(orchestrator_enabled=True),
        compute_similarity=_ScoreRecorder(),
        decomposer=_SpecDecomposer(),
        admission_port=admission_port,
    )
    service.bind_scheduler(_ScheduleSpy())
    opening = asyncio.create_task(service.open_or_resume(
        principal=service.captain_principal(),
        goal="Parent cancellation",
        success_criteria=["Complete"],
        expected_deliverable="Result",
        facilitator_id="facilitator-1",
    ))
    try:
        await work.reconciliation_entered.wait()
        opening.cancel("parent-create-second")
        await asyncio.sleep(0)
        assert opening.done() is False
        work.release_reconciliation.set()

        with pytest.raises(asyncio.CancelledError) as raised:
            await opening
        assert raised.value is first_cancellation
        assert raised.value.args == ("parent-create-first",)
        parents = await work.list_work_items(work_type="crew_session", limit=10)
        assert len(parents) == 1
        assert set(parents[0].metadata) == {"crew_provisioning"}
    finally:
        work.release_reconciliation.set()
        if not opening.done():
            opening.cancel()
            await asyncio.gather(opening, return_exceptions=True)
        await work.stop()


async def test_requested_room_adopts_exact_link_and_preserves_stored_order(
    harness: _Harness,
) -> None:
    room = harness.threads.create_thread(
        title="Room",
        participants=["owner-2", "facilitator-1"],
    )

    result = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="Room work",
        success_criteria=["Complete"],
        expected_deliverable="Result",
        requested_thread_id=room.id,
    )

    assert result.thread_id == room.id
    assert result.facilitator_id == "owner-2"
    assert result.owner_ids == ("owner-2",)
    assert harness.threads.get_thread(room.id).task_id == result.parent_id


async def test_requested_room_bound_incompatible_and_terminal_reject(
    harness: _Harness,
) -> None:
    parent, thread, session = await _create_bound_session(harness)
    with pytest.raises(ValueError, match="thread_task_incompatible"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal="Different",
            success_criteria=list(session.success_criteria),
            expected_deliverable=session.expected_deliverable,
            requested_thread_id=thread.id,
        )
    failed = await harness.service.transition_session(
        parent.id,
        "failed",
        expected_revision=session.revision,
    )
    assert failed.state == "failed"
    with pytest.raises(ValueError, match="terminal_not_reopenable"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal=session.goal,
            success_criteria=list(session.success_criteria),
            expected_deliverable=session.expected_deliverable,
            requested_thread_id=thread.id,
        )


async def test_requested_room_missing_and_archived_reject_before_write(
    harness: _Harness,
) -> None:
    with pytest.raises(ValueError, match="thread_not_found"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal="Missing room",
            success_criteria=["Complete"],
            expected_deliverable="Result",
            requested_thread_id="missing-room",
        )
    archived = harness.threads.create_thread(
        title="Archived",
        participants=["facilitator-1"],
    )
    harness.threads.update_thread(archived.id, archived=True)

    with pytest.raises(ValueError, match="thread_archived"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal="Archived room",
            success_criteria=["Complete"],
            expected_deliverable="Result",
            requested_thread_id=archived.id,
        )

    assert await harness.work.list_work_items(limit=20) == []
    assert harness.decomposer.calls == []


async def test_requested_room_pending_marker_blocks_resume_and_schedule(
    harness: _Harness,
) -> None:
    result = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="Pending authority",
        success_criteria=["Complete"],
        expected_deliverable="Result",
        facilitator_id="facilitator-1",
    )
    parent = await harness.work.get_work_item(result.parent_id)
    session = await harness.service.get_session(result.parent_id)
    recovery = await harness.service.get_recovery(result.parent_id)
    assert parent is not None and session is not None and recovery is not None
    normalized = crew_session_module._normalize_ingress_values(
        goal=session.goal,
        success_criteria=list(session.success_criteria),
        expected_deliverable=session.expected_deliverable,
    )
    marker = CrewSessionProvisioningContract.model_validate({
        "version": 1,
        "provision_id": "d" * 64,
        "phase": "plan_installed",
        "room_policy": "create",
        "thread_id": result.thread_id,
        "goal": session.goal,
        "goal_fingerprint": normalized.goal_fingerprint,
        "origin": session.origin,
        "originator_id": session.originator_id,
        "created_by": parent.created_by,
        "facilitator_id": session.facilitator_id,
        "owner_ids": list(session.owner_ids),
        "success_criteria": list(session.success_criteria),
        "expected_deliverable": session.expected_deliverable,
        "plan_specs": crew_session_module._project_decomposition(
            harness.decomposer.specs,
        ),
        "last_error_code": None,
    })
    updated = await harness.work.merge_work_item_metadata(
        parent.id,
        {"crew_provisioning": marker.model_dump(mode="json")},
        expected={
            "crew_session": session.model_dump(mode="json"),
            "crew_recovery": recovery.model_dump(mode="json"),
        },
        expected_work_type="crew_session",
        expected_status="open",
        expected_assigned_to=session.facilitator_id,
        source="test_pending_provisioning",
    )
    assert updated is not None
    scheduled_before = list(harness.schedule.parent_ids)

    with pytest.raises(ValueError, match="crew_provisioning_pending"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal=session.goal,
            success_criteria=list(session.success_criteria),
            expected_deliverable=session.expected_deliverable,
            requested_thread_id=result.thread_id,
        )

    authoritative = await harness.service.get_session(parent.id)
    assert authoritative is not None
    assert authoritative.duplicate_resume_count == 0
    assert harness.schedule.parent_ids == scheduled_before


async def test_owner_union_preserves_facilitator_and_rejects_cap_overflow(
    harness: _Harness,
) -> None:
    extra_ids = [f"owner-{index}" for index in range(4, 19)]
    for agent_id in extra_ids:
        await harness.registry.register(SimpleNamespace(
            id=agent_id,
            agent_type="operations_officer",
            pool="operations",
        ))
    _, _, session = await _create_bound_session(harness)
    resumed = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal=session.goal,
        success_criteria=list(session.success_criteria),
        expected_deliverable=session.expected_deliverable,
        facilitator_id="owner-3",
        owner_ids=["facilitator-1", "owner-3"],
    )
    assert resumed.facilitator_id == "facilitator-1"
    assert resumed.owner_ids == ("facilitator-1", "owner-2", "owner-3")

    with pytest.raises(ValueError, match="owner_ids_invalid"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal=session.goal,
            success_criteria=list(session.success_criteria),
            expected_deliverable=session.expected_deliverable,
            facilitator_id="facilitator-1",
            owner_ids=extra_ids,
        )


async def test_agent_provenance_and_live_rank_drop_before_second_scan(
    harness: _Harness,
) -> None:
    blocker = _BlockingDecomposer()
    harness.service._decomposer = blocker
    pending = asyncio.create_task(harness.service.open_or_resume(
        principal=harness.service.agent_principal("agent-origin"),
        goal="Agent work",
        success_criteria=["Complete"],
        expected_deliverable="Result",
    ))
    await asyncio.to_thread(blocker.entered.wait, 2.0)
    harness.trust.create_with_prior("agent-origin", 1.0, 3.0)
    blocker.release.set()

    with pytest.raises(ValueError, match="agent_rank_insufficient"):
        await pending
    assert await harness.work.list_work_items(limit=20) == []


async def test_agent_owner_replacement_before_write_rejects_without_mutation(
    harness: _Harness,
) -> None:
    blocker = _BlockingDecomposer()
    harness.service._decomposer = blocker
    pending = asyncio.create_task(harness.service.open_or_resume(
        principal=harness.service.agent_principal("agent-origin"),
        goal="Agent owner race",
        success_criteria=["Complete"],
        expected_deliverable="Result",
        owner_ids=["owner-2"],
    ))
    await asyncio.to_thread(blocker.entered.wait, 2.0)
    await harness.registry.unregister("owner-2")
    await harness.registry.register(SimpleNamespace(
        id="owner-2",
        agent_type="operations_officer",
        pool="operations",
    ))
    blocker.release.set()

    with pytest.raises(ValueError, match="owner_identity_changed"):
        await pending
    assert await harness.work.list_work_items(limit=20) == []
    assert harness.threads.list_threads(include_archived=True) == []


async def test_agent_created_session_has_truthful_provenance(
    harness: _Harness,
) -> None:
    result = await harness.service.open_or_resume(
        principal=harness.service.agent_principal("agent-origin"),
        goal="Agent work",
        success_criteria=["Complete"],
        expected_deliverable="Result",
    )
    session = await harness.service.get_session(result.parent_id)
    parent = await harness.work.get_work_item(result.parent_id)

    assert session is not None and session.origin == "agent"
    assert session.originator_id == "agent-origin"
    assert session.facilitator_id == "agent-origin"
    assert session.owner_ids == ("agent-origin",)
    assert parent is not None and parent.created_by == "agent-origin"


async def test_blocked_explicit_captain_retry_restores_executing(
    harness: _Harness,
) -> None:
    parent, thread, session = await _create_bound_session(harness)
    executing = await harness.service.transition_session(
        parent.id,
        "executing",
        expected_revision=session.revision,
    )
    child = await harness.work.create_work_item(
        id="retry-child",
        title="Retry",
        work_type="task",
        parent_id=parent.id,
        status="in_progress",
        metadata={
            "spec_id": "spec-a",
            "resources": [],
            "expected_output": None,
            "capability": None,
            "department": None,
        },
        created_by="facilitator-1",
    )
    from probos.cognitive.crew_session import _build_adopted_recovery_plan
    plan = _build_adopted_recovery_plan(parent.id, (child,))
    recovery = await harness.service.adopt_recovery_plan(
        parent.id,
        expected_session=executing,
        expected_recovery=None,
        plan=plan,
        expected_children=(child,),
    )
    values = recovery.model_dump(mode="json")
    values.update({
        "last_error_code": "child_execution_cancelled",
        "interrupted_child_ids": [child.id],
    })
    checkpoint = CrewRecoveryContract.model_validate(values)
    blocked = await harness.service.transition_session(
        parent.id,
        "blocked_needs_captain",
        expected_revision=executing.revision,
        blocked_reason="child_execution_interrupted",
        expected_recovery=recovery,
        recovery=checkpoint,
    )

    result = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal=blocked.goal,
        success_criteria=list(blocked.success_criteria),
        expected_deliverable=blocked.expected_deliverable,
        requested_thread_id=thread.id,
        retry_blocked=True,
    )

    assert result.state == "executing"
    assert result.scheduled is True
    assert result.duplicate_resume_count == 1


async def test_blocked_retry_rejects_nonrecoverable_and_unbound_room(
    harness: _Harness,
) -> None:
    parent, thread, session = await _create_bound_session(harness)
    blocked = await harness.service.transition_session(
        parent.id,
        "blocked_needs_captain",
        expected_revision=session.revision,
        blocked_reason="child_tool_blocked",
    )
    with pytest.raises(ValueError, match="retry_not_authorized"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal=blocked.goal,
            success_criteria=list(blocked.success_criteria),
            expected_deliverable=blocked.expected_deliverable,
            requested_thread_id=thread.id,
            retry_blocked=True,
        )
    unbound = harness.threads.create_thread(
        title="Unbound",
        participants=["facilitator-1"],
    )
    with pytest.raises(ValueError, match="retry_state_invalid"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal="Retry",
            success_criteria=["Complete"],
            expected_deliverable="Result",
            requested_thread_id=unbound.id,
            retry_blocked=True,
        )


@pytest.mark.parametrize(
    ("previous_state", "expected_status"),
    [("discussing", "open"), ("verifying", "review")],
)
async def test_blocked_exhausted_retry_restores_proven_previous_state(
    harness: _Harness,
    previous_state: str,
    expected_status: str,
) -> None:
    parent, thread, session = await _create_bound_session(harness)
    child = await harness.work.create_work_item(
        id="exhausted-child",
        title="Retry child",
        work_type="task",
        parent_id=parent.id,
        metadata={
            "spec_id": "spec-a",
            "resources": [],
            "expected_output": None,
            "capability": None,
            "department": None,
        },
        created_by="facilitator-1",
    )
    plan = crew_session_module._build_adopted_recovery_plan(parent.id, (child,))
    recovery = await harness.service.adopt_recovery_plan(
        parent.id,
        expected_session=session,
        expected_recovery=None,
        plan=plan,
        expected_children=(child,),
    )
    current = session
    if previous_state == "verifying":
        executing_values = recovery.model_dump(mode="json")
        executing_values["phase"] = "executing"
        executing_recovery = CrewRecoveryContract.model_validate(executing_values)
        current = await harness.service.transition_session(
            parent.id,
            "executing",
            expected_revision=current.revision,
            expected_recovery=recovery,
            recovery=executing_recovery,
        )
        verifying_values = executing_recovery.model_dump(mode="json")
        verifying_values["phase"] = "verifying_children"
        recovery = CrewRecoveryContract.model_validate(verifying_values)
        current = await harness.service.transition_session(
            parent.id,
            "verifying",
            expected_revision=current.revision,
            expected_recovery=executing_recovery,
            recovery=recovery,
        )
    exhausted_values = recovery.model_dump(mode="json")
    exhausted_values.update({
        "retry_count": 3,
        "last_error_code": "recovery_retry_exhausted",
    })
    exhausted = CrewRecoveryContract.model_validate(exhausted_values)
    blocked = await harness.service.transition_session(
        parent.id,
        "blocked_needs_captain",
        expected_revision=current.revision,
        blocked_reason="recovery_retry_exhausted",
        expected_recovery=recovery,
        recovery=exhausted,
    )

    result = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal=blocked.goal,
        success_criteria=list(blocked.success_criteria),
        expected_deliverable=blocked.expected_deliverable,
        requested_thread_id=thread.id,
        retry_blocked=True,
    )

    assert result.state == previous_state
    assert result.scheduled is True
    stored = await harness.work.get_work_item(parent.id)
    restored_recovery = await harness.service.get_recovery(parent.id)
    assert stored is not None and stored.status == expected_status
    assert restored_recovery is not None
    assert restored_recovery.retry_count == 0
    assert restored_recovery.last_error_code is None


def test_provisioning_marker_is_strict_and_json_type_exact() -> None:
    projection = crew_session_module._project_decomposition([
        WorkItemSpec(spec_id="spec-a", title="A"),
    ])
    payload = {
        "version": 1,
        "provision_id": "a" * 64,
        "phase": "parent_created",
        "room_policy": "create",
        "thread_id": "crew-room-" + "a" * 64,
        "goal": "Goal",
        "goal_fingerprint": crew_session_module.hashlib.sha256(b"goal").hexdigest(),
        "origin": "captain",
        "originator_id": "captain",
        "created_by": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1"],
        "success_criteria": ["Complete"],
        "expected_deliverable": "Result",
        "plan_specs": projection,
        "last_error_code": None,
    }

    marker = CrewSessionProvisioningContract.model_validate(payload)

    assert marker.phase == "parent_created"
    with pytest.raises(ValidationError):
        CrewSessionProvisioningContract.model_validate({**payload, "version": True})
    with pytest.raises(ValidationError):
        CrewSessionProvisioningContract.model_validate({**payload, "extra": 1})


async def test_thread_store_exact_provisioning_primitives(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "thread-primitives.db", clock=lambda: 5.0)
    provision_id = "b" * 64
    thread_id = f"crew-room-{provision_id}"

    created = store.create_crew_session_thread(
        thread_id=thread_id,
        title="Goal",
        participants=("facilitator-1",),
        task_id="parent-1",
        provision_id=provision_id,
        created_by="captain",
    )
    repeated = store.create_crew_session_thread(
        thread_id=thread_id,
        title="Goal",
        participants=("facilitator-1",),
        task_id="parent-1",
        provision_id=provision_id,
        created_by="captain",
    )

    assert repeated.to_dict() == created.to_dict()
    assert store.compare_and_set_task_link(
        thread_id,
        expected_task_id="foreign",
        new_task_id=None,
    ) is None
    assert store.delete_untouched_crew_session_thread(
        thread_id,
        task_id="parent-1",
        provision_id=provision_id,
    ) is True

    existing = tuple(f"participant-{index}" for index in range(17))
    adopted = store.create_thread(
        title="Large existing room",
        participants=existing,
        task_id="parent-large",
    )
    updated = store.add_crew_session_participants(
        adopted.id,
        task_id="parent-large",
        participant_ids=("facilitator-1",),
    )
    assert updated is not None
    assert updated.participants == [*existing, "facilitator-1"]


async def test_repair_provisioning_installs_plan_clears_marker_without_schedule(
    harness: _Harness,
) -> None:
    request = crew_session_module._normalize_ingress_values(
        goal="Repair me",
        success_criteria=["Complete"],
        expected_deliverable="Result",
    )
    provision_id = "c" * 64
    marker = CrewSessionProvisioningContract.model_validate({
        "version": 1,
        "provision_id": provision_id,
        "phase": "parent_created",
        "room_policy": "create",
        "thread_id": f"crew-room-{provision_id}",
        "goal": request.display_goal,
        "goal_fingerprint": request.goal_fingerprint,
        "origin": "captain",
        "originator_id": "captain",
        "created_by": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1"],
        "success_criteria": ["Complete"],
        "expected_deliverable": "Result",
        "plan_specs": crew_session_module._project_decomposition([
            WorkItemSpec(spec_id="spec-a", title="A"),
        ]),
        "last_error_code": None,
    })
    parent = await _create_reserved_parent(
        harness.work,
        harness.admission_port,
        parent_id=f"crew-session-{provision_id}",
        title="Repair me",
        assigned_to="facilitator-1",
        created_by="captain",
        metadata={"crew_provisioning": marker.model_dump(mode="json")},
    )

    repaired = await harness.service.repair_provisioning(limit=10)

    assert repaired == (parent.id,)
    assert harness.schedule.parent_ids == []
    stored = await harness.work.get_work_item(parent.id)
    assert stored is not None and "crew_provisioning" not in stored.metadata
    assert stored.metadata["crew_recovery"]["phase"] == "planned"


async def test_clear_provisioning_preserves_unrelated_metadata_sibling(
    harness: _Harness,
) -> None:
    request = crew_session_module._normalize_ingress_values(
        goal="Preserve sibling",
        success_criteria=["Complete"],
        expected_deliverable="Result",
    )
    provision_id = "d" * 64
    marker = CrewSessionProvisioningContract.model_validate({
        "version": 1,
        "provision_id": provision_id,
        "phase": "parent_created",
        "room_policy": "create",
        "thread_id": f"crew-room-{provision_id}",
        "goal": request.display_goal,
        "goal_fingerprint": request.goal_fingerprint,
        "origin": "captain",
        "originator_id": "captain",
        "created_by": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1"],
        "success_criteria": ["Complete"],
        "expected_deliverable": "Result",
        "plan_specs": crew_session_module._project_decomposition([
            WorkItemSpec(spec_id="spec-sibling", title="Sibling"),
        ]),
        "last_error_code": None,
    })
    parent = await _create_reserved_parent(
        harness.work,
        harness.admission_port,
        parent_id=f"crew-session-{provision_id}",
        title=marker.goal,
        assigned_to=marker.facilitator_id,
        created_by=marker.created_by,
        metadata={"crew_provisioning": marker.model_dump(mode="json")},
    )
    parent = await harness.work.merge_work_item_metadata(
        parent.id,
        {"unrelated": {"preserve": True}},
        expected={
            "crew_provisioning": marker.model_dump(mode="json"),
        },
        expected_work_type="crew_session",
        expected_status="draft",
        expected_assigned_to=marker.facilitator_id,
    )
    assert parent is not None

    repaired = await harness.service.repair_provisioning(limit=10)

    assert repaired == (parent.id,)
    stored = await harness.work.get_work_item(parent.id)
    assert stored is not None
    assert "crew_provisioning" not in stored.metadata
    assert stored.metadata["unrelated"] == {"preserve": True}


async def test_fail_provisioning_preserves_unrelated_metadata_sibling(
    harness: _Harness,
) -> None:
    request = crew_session_module._normalize_ingress_values(
        goal="Fail sibling",
        success_criteria=["Complete"],
        expected_deliverable="Result",
    )
    marker = CrewSessionProvisioningContract.model_validate({
        "version": 1,
        "provision_id": "9" * 64,
        "phase": "parent_created",
        "room_policy": "create",
        "thread_id": "crew-room-" + "9" * 64,
        "goal": request.display_goal,
        "goal_fingerprint": request.goal_fingerprint,
        "origin": "captain",
        "originator_id": "captain",
        "created_by": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1"],
        "success_criteria": ["Complete"],
        "expected_deliverable": "Result",
        "plan_specs": crew_session_module._project_decomposition([
            WorkItemSpec(spec_id="spec-fail", title="Fail"),
        ]),
        "last_error_code": None,
    })
    parent = await _create_reserved_parent(
        harness.work,
        harness.admission_port,
        parent_id="crew-session-" + "9" * 64,
        title=marker.goal,
        assigned_to=marker.facilitator_id,
        created_by=marker.created_by,
        metadata={"crew_provisioning": marker.model_dump(mode="json")},
    )
    parent = await harness.work.merge_work_item_metadata(
        parent.id,
        {"unrelated": {"preserve": True}},
        expected={
            "crew_provisioning": marker.model_dump(mode="json"),
        },
        expected_work_type="crew_session",
        expected_status="draft",
        expected_assigned_to=marker.facilitator_id,
    )
    assert parent is not None

    failed = await harness.work.fail_crew_session_provisioning(
        parent.id,
        expected_marker=marker.model_dump(mode="json"),
        error_code="injected_failure",
    )

    assert failed is not None
    assert failed.metadata["unrelated"] == {"preserve": True}
    assert failed.metadata["crew_provisioning"]["phase"] == "failed"
    assert failed.metadata["crew_provisioning"]["last_error_code"] == (
        "injected_failure"
    )


async def test_repair_provisioning_adopts_exact_existing_children(
    harness: _Harness,
) -> None:
    request = crew_session_module._normalize_ingress_values(
        goal="Adopt repair",
        success_criteria=["Complete"],
        expected_deliverable="Result",
    )
    provision_id = "e" * 64
    projections = crew_session_module._project_decomposition([
        WorkItemSpec(spec_id="spec-adopt", title="Existing child"),
    ])
    marker = CrewSessionProvisioningContract.model_validate({
        "version": 1,
        "provision_id": provision_id,
        "phase": "parent_created",
        "room_policy": "create",
        "thread_id": f"crew-room-{provision_id}",
        "goal": request.display_goal,
        "goal_fingerprint": request.goal_fingerprint,
        "origin": "captain",
        "originator_id": "captain",
        "created_by": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1"],
        "success_criteria": ["Complete"],
        "expected_deliverable": "Result",
        "plan_specs": projections,
        "last_error_code": None,
    })
    parent = await _create_reserved_parent(
        harness.work,
        harness.admission_port,
        parent_id=f"crew-session-{provision_id}",
        title=marker.goal,
        assigned_to=marker.facilitator_id,
        created_by=marker.created_by,
        metadata={"crew_provisioning": marker.model_dump(mode="json")},
    )
    harness.threads.create_crew_session_thread(
        thread_id=marker.thread_id,
        title=marker.goal,
        participants=marker.owner_ids,
        task_id=parent.id,
        provision_id=marker.provision_id,
        created_by=marker.created_by,
    )
    marker = await harness.service._advance_provisioning_marker(
        parent.id,
        marker,
        "room_bound",
        expected_status="draft",
    )
    session = await harness.service.initialize_session(
        parent.id,
        marker.thread_id,
        goal=marker.goal,
        origin=marker.origin,
        originator_id=marker.originator_id,
        facilitator_id=marker.facilitator_id,
        owner_ids=list(marker.owner_ids),
        success_criteria=list(marker.success_criteria),
        expected_deliverable=marker.expected_deliverable,
    )
    marker = await harness.service._advance_provisioning_marker(
        parent.id,
        marker,
        "session_initialized",
        expected_status="open",
    )
    specs = crew_session_module._specs_from_projections(marker.plan_specs)
    _expected_plan, inserts = _build_derived_recovery_plan(
        parent.id,
        specs,
        created_by=marker.facilitator_id,
    )
    insert = inserts[0]
    child = await harness.work.create_work_item(
        id=insert.id,
        title=insert.title,
        description=insert.description,
        work_type=insert.work_type,
        priority=insert.priority,
        parent_id=parent.id,
        depends_on=list(insert.depends_on),
        assigned_to=insert.assigned_to,
        created_by=insert.created_by,
        trust_requirement=insert.trust_requirement,
        required_capabilities=list(insert.required_capabilities),
        metadata=dict(insert.metadata),
    )

    repaired = await harness.service.repair_provisioning(limit=10)

    assert repaired == (parent.id,)
    recovery = await harness.service.get_recovery(parent.id)
    assert recovery is not None and recovery.plan is not None
    assert crew_session_module._validate_contextual_recovery_plan(
        parent.id,
        recovery.plan,
        (child,),
    ) == "adopted_v1"
    assert await harness.service.get_session(parent.id) == session


async def test_cancel_checkpoint_does_not_advance_drifted_created_room(
    harness: _Harness,
) -> None:
    request = crew_session_module._normalize_ingress_values(
        goal="Checkpoint drift",
        success_criteria=["Complete"],
        expected_deliverable="Result",
    )
    provision_id = "f" * 64
    marker = CrewSessionProvisioningContract.model_validate({
        "version": 1,
        "provision_id": provision_id,
        "phase": "parent_created",
        "room_policy": "create",
        "thread_id": f"crew-room-{provision_id}",
        "goal": request.display_goal,
        "goal_fingerprint": request.goal_fingerprint,
        "origin": "captain",
        "originator_id": "captain",
        "created_by": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1"],
        "success_criteria": ["Complete"],
        "expected_deliverable": "Result",
        "plan_specs": crew_session_module._project_decomposition([
            WorkItemSpec(spec_id="spec-a", title="A"),
        ]),
        "last_error_code": None,
    })
    parent = await _create_reserved_parent(
        harness.work,
        harness.admission_port,
        parent_id=f"crew-session-{provision_id}",
        title=marker.goal,
        assigned_to=marker.facilitator_id,
        created_by=marker.created_by,
        metadata={"crew_provisioning": marker.model_dump(mode="json")},
    )
    harness.threads.create_crew_session_thread(
        thread_id=marker.thread_id,
        title=marker.goal,
        participants=marker.owner_ids,
        task_id=parent.id,
        provision_id=marker.provision_id,
        created_by=marker.created_by,
    )
    harness.threads.add_participant(marker.thread_id, "owner-2")

    with pytest.raises(ValueError, match="thread_create_conflict"):
        await harness.service._checkpoint_provisioning_authority(parent.id)

    authoritative = await harness.work.get_work_item(parent.id)
    assert authoritative is not None
    assert authoritative.metadata["crew_provisioning"]["phase"] == "parent_created"


@pytest.mark.parametrize("room_policy", ["create", "adopt"])
async def test_compensation_removes_only_exact_untouched_pre_session_authority(
    harness: _Harness,
    room_policy: str,
) -> None:
    request = crew_session_module._normalize_ingress_values(
        goal=f"Compensate {room_policy}",
        success_criteria=["Complete"],
        expected_deliverable="Result",
    )
    provision_id = ("a" if room_policy == "create" else "b") * 64
    adopted_snapshot: dict[str, Any] | None = None
    if room_policy == "adopt":
        adopted = harness.threads.create_thread(
            title="Adopted room",
            participants=["facilitator-1"],
        )
        thread_id = adopted.id
        adopted_snapshot = adopted.to_dict()
    else:
        thread_id = f"crew-room-{provision_id}"
    marker = CrewSessionProvisioningContract.model_validate({
        "version": 1,
        "provision_id": provision_id,
        "phase": "parent_created",
        "room_policy": room_policy,
        "thread_id": thread_id,
        "goal": request.display_goal,
        "goal_fingerprint": request.goal_fingerprint,
        "origin": "captain",
        "originator_id": "captain",
        "created_by": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1"],
        "success_criteria": ["Complete"],
        "expected_deliverable": "Result",
        "plan_specs": crew_session_module._project_decomposition([
            WorkItemSpec(spec_id="spec-a", title="A"),
        ]),
        "last_error_code": None,
    })
    parent = await _create_reserved_parent(
        harness.work,
        harness.admission_port,
        parent_id=f"crew-session-{provision_id}",
        title=marker.goal,
        assigned_to=marker.facilitator_id,
        created_by=marker.created_by,
        metadata={"crew_provisioning": marker.model_dump(mode="json")},
    )
    assert parent.description == marker.goal
    if room_policy == "adopt":
        linked = harness.threads.compare_and_set_task_link(
            marker.thread_id,
            expected_task_id=None,
            new_task_id=parent.id,
        )
        assert linked is not None
    else:
        harness.threads.create_crew_session_thread(
            thread_id=marker.thread_id,
            title=marker.goal,
            participants=marker.owner_ids,
            task_id=parent.id,
            provision_id=marker.provision_id,
            created_by=marker.created_by,
        )

    await harness.service._compensate_pre_session(
        parent.id,
        marker,
        adopted_room_snapshot=adopted_snapshot,
    )

    assert await harness.work.get_work_item(parent.id) is None
    if room_policy == "create":
        assert harness.threads.get_thread(marker.thread_id) is None
    else:
        restored = harness.threads.get_thread(marker.thread_id)
        assert restored is not None and restored.to_dict() == adopted_snapshot


async def test_compensation_refuses_drifted_adopted_room_after_external_unlink(
    harness: _Harness,
) -> None:
    request = crew_session_module._normalize_ingress_values(
        goal="Refuse drift",
        success_criteria=["Complete"],
        expected_deliverable="Result",
    )
    adopted = harness.threads.create_thread(
        title="Adopted room",
        participants=["facilitator-1"],
    )
    snapshot = adopted.to_dict()
    marker = CrewSessionProvisioningContract.model_validate({
        "version": 1,
        "provision_id": "c" * 64,
        "phase": "parent_created",
        "room_policy": "adopt",
        "thread_id": adopted.id,
        "goal": request.display_goal,
        "goal_fingerprint": request.goal_fingerprint,
        "origin": "captain",
        "originator_id": "captain",
        "created_by": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1"],
        "success_criteria": ["Complete"],
        "expected_deliverable": "Result",
        "plan_specs": crew_session_module._project_decomposition([
            WorkItemSpec(spec_id="spec-a", title="A"),
        ]),
        "last_error_code": None,
    })
    parent = await _create_reserved_parent(
        harness.work,
        harness.admission_port,
        parent_id="crew-session-" + "c" * 64,
        title=marker.goal,
        assigned_to=marker.facilitator_id,
        created_by=marker.created_by,
        metadata={"crew_provisioning": marker.model_dump(mode="json")},
    )
    assert harness.threads.compare_and_set_task_link(
        adopted.id,
        expected_task_id=None,
        new_task_id=parent.id,
    ) is not None
    assert harness.threads.compare_and_set_task_link(
        adopted.id,
        expected_task_id=parent.id,
        new_task_id=None,
    ) is not None
    harness.threads.update_thread(adopted.id, title="Externally changed")

    await harness.service._compensate_pre_session(
        parent.id,
        marker,
        adopted_room_snapshot=snapshot,
    )

    assert await harness.work.get_work_item(parent.id) is not None
    drifted = harness.threads.get_thread(adopted.id)
    assert drifted is not None and drifted.title == "Externally changed"


async def test_post_room_bound_error_compensates_authoritative_marker(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_initialize(
        parent_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> CrewSessionContract:
        parent = await harness.work.get_work_item(parent_id)
        assert parent is not None
        marker = CrewSessionProvisioningContract.model_validate(
            parent.metadata["crew_provisioning"],
        )
        assert parent.description == marker.goal
        raise ValueError("injected_initialize_failure")

    monkeypatch.setattr(harness.service, "initialize_session", fail_initialize)

    with pytest.raises(ValueError, match="injected_initialize_failure"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal="Compensate after room bound",
            success_criteria=["Complete"],
            expected_deliverable="Result",
            facilitator_id="facilitator-1",
        )

    assert await harness.work.list_work_items(work_type="crew_session", limit=10) == []
    assert harness.threads.list_threads(include_archived=True) == []


async def test_closed_scheduler_leaves_durable_authority_and_fails_closed(
    harness: _Harness,
) -> None:
    def closed(_: str) -> asyncio.Task[Any]:
        raise RuntimeError("closed")

    harness.service._schedule = closed
    with pytest.raises(ValueError, match="scheduler_unavailable"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal="Durable before schedule",
            success_criteria=["Complete"],
            expected_deliverable="Result",
            facilitator_id="facilitator-1",
        )

    parents = await harness.work.list_work_items(work_type="crew_session", limit=10)
    assert len(parents) == 1
    assert "crew_session" in parents[0].metadata
    assert "crew_recovery" in parents[0].metadata
    assert "crew_provisioning" not in parents[0].metadata


async def test_coordinator_intent_uses_truthful_captain_provenance(
    harness: _Harness,
) -> None:
    from probos.agents.operations.coordinator import CoordinatorAgent
    from probos.types import IntentMessage

    runtime = SimpleNamespace(
        config=SimpleNamespace(
            operations=SimpleNamespace(enabled=True),
            agentic_dispatch=SimpleNamespace(orchestrator_enabled=True),
        ),
        crew_session_service=harness.service,
    )
    agent = CoordinatorAgent(agent_id="coordinator-1", runtime=runtime)
    result = await agent.handle_intent(IntentMessage(
        intent="start_crew_session",
        params={
            "goal": "Coordinate",
            "success_criteria": ["Complete"],
            "expected_deliverable": "Result",
            "facilitator_id": "facilitator-1",
            "origin": "agent",
            "originator_id": "spoofed",
            "created_by": "spoofed",
            "retry_blocked": True,
        },
    ))

    assert result is not None and result.success is True
    session = await harness.service.get_session(result.result["parent_id"])
    assert session is not None and session.origin == "captain"
    assert session.originator_id == "captain"


async def test_coordinator_intent_reports_contract_error_without_side_effect(
    harness: _Harness,
) -> None:
    from probos.agents.operations.coordinator import CoordinatorAgent
    from probos.types import IntentMessage

    runtime = SimpleNamespace(
        config=SimpleNamespace(
            operations=SimpleNamespace(enabled=True),
            agentic_dispatch=SimpleNamespace(orchestrator_enabled=True),
        ),
        crew_session_service=harness.service,
    )
    agent = CoordinatorAgent(agent_id="coordinator-1", runtime=runtime)

    result = await agent.handle_intent(IntentMessage(
        intent="start_crew_session",
        params={
            "goal": "",
            "success_criteria": ["Complete"],
            "expected_deliverable": "Result",
            "facilitator_id": "facilitator-1",
        },
    ))

    assert result is not None and result.success is False
    assert result.error == "crew_session_ingress_text_empty"
    assert await harness.work.list_work_items(limit=10) == []


def test_default_off_hides_live_and_planner_descriptor() -> None:
    from probos.agents.operations.coordinator import CoordinatorAgent
    from probos.runtime import ProbOSRuntime

    disabled_config = SimpleNamespace(
        operations=SimpleNamespace(enabled=True),
        agentic_dispatch=SimpleNamespace(orchestrator_enabled=False),
    )
    disabled_agent = CoordinatorAgent(
        agent_id="coordinator-disabled",
        runtime=SimpleNamespace(config=disabled_config),
    )
    assert "start_crew_session" not in {
        descriptor.name for descriptor in disabled_agent.intent_descriptors
    }
    assert not hasattr(disabled_agent, "handle_intent")

    runtime = ProbOSRuntime.__new__(ProbOSRuntime)
    runtime.spawner = SimpleNamespace(
        _templates={"operations_coordinator": CoordinatorAgent},
    )
    runtime.config = disabled_config
    runtime.cognitive_skill_catalog = None
    assert "start_crew_session" not in {
        descriptor.name for descriptor in runtime._collect_intent_descriptors()
    }

    runtime.config = SimpleNamespace(
        operations=SimpleNamespace(enabled=True),
        agentic_dispatch=SimpleNamespace(orchestrator_enabled=True),
    )
    assert "start_crew_session" in {
        descriptor.name for descriptor in runtime._collect_intent_descriptors()
    }


async def test_orchestrator_start_repairs_before_recovery_scan() -> None:
    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.config import SystemConfig

    events: list[str] = []

    class _RepairService:
        async def repair_provisioning(self, *, limit: int) -> tuple[str, ...]:
            events.append(f"repair:{limit}")
            return ()

    class _RecoveryStore:
        async def list_crew_session_recovery_candidates(
            self,
            *,
            limit: int,
        ) -> list[Any]:
            events.append(f"recovery:{limit}")
            return []

    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    config.agentic_dispatch.crew_provisioning_repair_limit = 7
    config.agentic_dispatch.crew_resume_scan_limit = 9
    orchestrator = CrewOrchestrator(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=_RecoveryStore(),
        runtime=SimpleNamespace(),
        config=config,
        crew_session_service=_RepairService(),
    )

    await orchestrator.start()
    try:
        assert events == ["repair:7", "recovery:9"]
        assert orchestrator._tasks_by_parent == {}
    finally:
        await orchestrator.stop()


async def test_start_schedules_repaired_id_absent_from_recovery_candidates(
    harness: _Harness,
) -> None:
    from probos.config import SystemConfig

    parent, _thread, _session = await _create_bound_session(
        harness,
        parent_id="repaired-only",
    )
    service = _StartupService(harness.service, (parent.id,))
    store = _RecoveryCandidatesStore(())
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    config.agentic_dispatch.crew_resume_scan_limit = 4
    owner = _StartupScheduleOwner(service=service, store=store, config=config)

    await owner.owner.start()
    await owner.drain()
    try:
        assert owner.scheduled_ids == [parent.id]
        assert service.validation_order == [
            ("session", parent.id),
            ("recovery", parent.id),
        ]
    finally:
        await owner.owner.stop()


async def test_start_unions_repaired_first_once_under_one_global_cap(
    harness: _Harness,
) -> None:
    from probos.config import SystemConfig

    for parent_id in ("startup-a", "startup-b", "startup-c", "startup-d"):
        await _create_bound_session(harness, parent_id=parent_id)
    service = _StartupService(
        harness.service,
        ("startup-b", "startup-a"),
    )
    store = _RecoveryCandidatesStore(
        ("startup-a", "startup-c", "startup-d"),
    )
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    config.agentic_dispatch.crew_resume_scan_limit = 3
    owner = _StartupScheduleOwner(service=service, store=store, config=config)

    await owner.owner.start()
    await owner.drain()
    try:
        assert owner.scheduled_ids == [
            "startup-b",
            "startup-a",
            "startup-c",
        ]
        assert service.validation_order == [
            ("session", "startup-b"),
            ("recovery", "startup-b"),
            ("session", "startup-a"),
            ("recovery", "startup-a"),
            ("session", "startup-c"),
            ("recovery", "startup-c"),
        ]
        assert store.limits == [3]
    finally:
        await owner.owner.stop()


async def test_start_malformed_provenance_schedules_nothing(
    harness: _Harness,
) -> None:
    from probos.config import SystemConfig

    valid_parent, _thread, _session = await _create_bound_session(
        harness,
        parent_id="startup-valid",
    )
    malformed_parent, _thread, malformed_session = await _create_bound_session(
        harness,
        parent_id="startup-malformed",
        origin="agent",
        originator_id="agent-origin",
        facilitator_id="agent-origin",
        owner_ids=["agent-origin"],
    )
    forged = malformed_session.model_dump(mode="json")
    forged.update({"origin": "captain", "originator_id": "captain"})
    changed = await harness.work.merge_work_item_metadata(
        malformed_parent.id,
        {"crew_session": forged},
        expected={
            "crew_session": malformed_session.model_dump(mode="json"),
        },
        expected_work_type="crew_session",
        expected_status="open",
        expected_assigned_to="agent-origin",
    )
    assert changed is not None
    service = _StartupService(
        harness.service,
        (valid_parent.id, malformed_parent.id),
    )
    store = _RecoveryCandidatesStore(())
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    owner = _StartupScheduleOwner(service=service, store=store, config=config)

    with pytest.raises(ValueError, match="^crew_session_provenance_invalid$"):
        await owner.owner.start()
    assert owner.scheduled_ids == []
    assert service.validation_order == [
        ("session", valid_parent.id),
        ("recovery", valid_parent.id),
        ("session", malformed_parent.id),
    ]
    await owner.owner.stop()


def _thread_api_app(
    harness: _Harness,
    *,
    enabled: bool = True,
    token: str = "",
    service: Any | None = None,
) -> FastAPI:
    from probos.routers import threads as threads_router
    from probos.routers.deps import get_runtime
    from probos.config import SystemConfig

    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = enabled
    config.auth.crew_scope_token = token
    runtime = SimpleNamespace(
        config=config,
        crew_session_service=service or harness.service,
        chat_thread_store=harness.threads,
    )
    app = FastAPI()
    app.include_router(threads_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return app


async def test_room_api_happy_returns_open_result(
    harness: _Harness,
) -> None:
    room = harness.threads.create_thread(
        title="API room",
        participants=["facilitator-1"],
    )
    transport = httpx.ASGITransport(app=_thread_api_app(harness))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/threads/{room.id}/start-work",
            json={
                "goal": "API work",
                "success_criteria": ["Complete"],
                "expected_deliverable": "Result",
            },
        )
        assert response.status_code == 200
        assert response.json()["thread_id"] == room.id


async def test_start_work_configured_token_missing_and_wrong_reject_before_service(
    harness: _Harness,
) -> None:
    class _ServiceRecorder:
        def __init__(self) -> None:
            self.principal_calls = 0
            self.open_calls = 0

        def captain_principal(self) -> Any:
            self.principal_calls += 1
            return object()

        async def open_or_resume(self, **_kwargs: Any) -> Any:
            self.open_calls += 1
            raise AssertionError("service work reached before auth")

    room = harness.threads.create_thread(
        title="Protected API room",
        participants=["facilitator-1"],
    )
    recorder = _ServiceRecorder()
    transport = httpx.ASGITransport(
        app=_thread_api_app(
            harness,
            token="secret-token",
            service=recorder,
        ),
    )
    payload = {
        "goal": "Protected work",
        "success_criteria": ["Complete"],
        "expected_deliverable": "Result",
    }
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        missing = await client.post(
            f"/api/threads/{room.id}/start-work",
            json=payload,
        )
        wrong = await client.post(
            f"/api/threads/{room.id}/start-work",
            json=payload,
            headers={"Authorization": "Bearer wrong-token"},
        )

    assert missing.status_code == 401
    assert missing.json()["detail"] == "missing_or_malformed_authorization"
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "invalid_token"
    assert recorder.principal_calls == 0
    assert recorder.open_calls == 0


async def test_start_work_configured_token_valid_reaches_service(
    harness: _Harness,
) -> None:
    class _ServiceRecorder:
        def __init__(self) -> None:
            self.principal_calls = 0
            self.open_calls = 0

        def captain_principal(self) -> str:
            self.principal_calls += 1
            return "captain-principal"

        async def open_or_resume(self, **kwargs: Any) -> Any:
            self.open_calls += 1
            assert kwargs["principal"] == "captain-principal"
            return SimpleNamespace(
                disposition="created",
                parent_id="protected-parent",
                thread_id=kwargs["requested_thread_id"],
                state="discussing",
                facilitator_id="facilitator-1",
                owner_ids=("facilitator-1",),
                duplicate_resume_count=0,
                scheduled=True,
            )

    room = harness.threads.create_thread(
        title="Protected API room",
        participants=["facilitator-1"],
    )
    recorder = _ServiceRecorder()
    transport = httpx.ASGITransport(
        app=_thread_api_app(
            harness,
            token="secret-token",
            service=recorder,
        ),
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/threads/{room.id}/start-work",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "goal": "Protected work",
                "success_criteria": ["Complete"],
                "expected_deliverable": "Result",
            },
        )

    assert response.status_code == 200
    assert response.json()["parent_id"] == "protected-parent"
    assert recorder.principal_calls == 1
    assert recorder.open_calls == 1


async def test_room_api_rejects_caller_principal_fields(
    harness: _Harness,
) -> None:
    room = harness.threads.create_thread(
        title="API validation room",
        participants=["facilitator-1"],
    )
    transport = httpx.ASGITransport(app=_thread_api_app(harness))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        invalid = await client.post(
            f"/api/threads/{room.id}/start-work",
            json={
                "goal": "API work",
                "success_criteria": ["Complete"],
                "expected_deliverable": "Result",
                "origin": "agent",
            },
        )
        overlong = await client.post(
            f"/api/threads/{room.id}/start-work",
            json={
                "goal": "API work",
                "success_criteria": ["x" * 513],
                "expected_deliverable": "Result",
            },
        )
    assert invalid.status_code == 422
    assert overlong.status_code == 422
    assert await harness.work.list_work_items(limit=10) == []


async def test_room_api_terminal_binding_returns_conflict(
    harness: _Harness,
) -> None:
    parent, room, session = await _create_bound_session(harness)
    await harness.service.transition_session(
        parent.id,
        "failed",
        expected_revision=session.revision,
    )
    transport = httpx.ASGITransport(app=_thread_api_app(harness))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        terminal = await client.post(
            f"/api/threads/{room.id}/start-work",
            json={
                "goal": session.goal,
                "success_criteria": list(session.success_criteria),
                "expected_deliverable": session.expected_deliverable,
            },
        )
    assert terminal.status_code == 409


async def test_room_api_disabled_fails_before_service_work(
    harness: _Harness,
) -> None:
    room = harness.threads.create_thread(
        title="API disabled room",
        participants=["facilitator-1"],
    )
    transport = httpx.ASGITransport(
        app=_thread_api_app(harness, enabled=False),
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        disabled = await client.post(
            f"/api/threads/{room.id}/start-work",
            json={
                "goal": "API work",
                "success_criteria": ["Complete"],
                "expected_deliverable": "Result",
            },
        )
    assert disabled.status_code == 503
    assert await harness.work.list_work_items(limit=10) == []