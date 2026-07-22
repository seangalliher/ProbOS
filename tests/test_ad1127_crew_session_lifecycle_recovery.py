"""AD-1127: CrewSession lifecycle ownership and restart recovery."""

from __future__ import annotations

import asyncio
import weakref
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from probos.artifacts import ArtifactStore
from probos.cognitive.crew_session import CrewSessionService
from probos.config import AgenticDispatchConfig
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.threads import ChatThreadStore
from probos.workforce import (
    CrewSessionAdmissionPort,
    CrewSessionParentCreate,
    WorkItem,
    WorkItemStore,
)


_SHA_A = "a" * 64
_SHA_B = "b" * 64
_ADMISSION_PORTS: weakref.WeakKeyDictionary[
    WorkItemStore,
    CrewSessionAdmissionPort,
] = weakref.WeakKeyDictionary()

_VECTOR_PLAN_SEED_HASH = (
    "8e53150cafb2837a2efa70f795703388ba91fe4ccd96563e2afe11b734108980"
)
_VECTOR_CHILD_ID = (
    "crew-2eea0cd19b27d9b8bb894c7a8d4d95eee3e44327a9a06c42826e5d0faa4ef543"
)
_VECTOR_ROW_HASH = (
    "2957fda273133f8170b06197292c3aae06b1644ea572ac769f2202383b82a178"
)
_VECTOR_PLAN_HASH = (
    "10da076213290108ff5bab846b27888cbb50be6c43e16fb61ed9f8a5a4b72d74"
)
_VECTOR_SEMANTIC_BYTES = (
    b'[{"capability":null,"department":null,"depends_on":[],"description":"Do it",'
    b'"expected_output":null,"priority":3,"resources":[],"spec_id":"spec-a",'
    b'"spec_metadata":{},"title":"Child","work_type":"task"}]'
)
_VECTOR_CHILD_INPUT_BYTES = (
    b'{"parent_id":"session-parent","plan_seed_hash":"8e53150cafb2837a2efa70f795703388'
    b'ba91fe4ccd96563e2afe11b734108980","spec_id":"spec-a"}'
)
_VECTOR_ROW_BYTES = (
    b'{"capability":null,"child_id":"crew-2eea0cd19b27d9b8bb894c7a8d4d95eee3e44327a9a'
    b'06c42826e5d0faa4ef543","department":null,"depends_on":[],"description":"Do it",'
    b'"expected_output":null,"priority":3,"resources":[],"spec_id":"spec-a",'
    b'"spec_metadata":{},"title":"Child","work_type":"task"}'
)
_VECTOR_MANIFEST_BYTES = (
    b'{"child_id_policy":"derived_v1","children":[{"child_id":"crew-2eea0cd19b27d9b8'
    b'bb894c7a8d4d95eee3e44327a9a06c42826e5d0faa4ef543","row_hash":"2957fda273133f8170b'
    b'06197292c3aae06b1644ea572ac769f2202383b82a178","spec_id":"spec-a"}],"parent_id":'
    b'"session-parent","plan_seed_hash":"8e53150cafb2837a2efa70f795703388ba91fe4ccd96563e2'
    b'afe11b734108980","version":1}'
)


class _Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        value = self.now
        self.now += 1.0
        return value


class _IdFactory:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"artifact-{self.value}"


class _AdoptionBarrierStore(WorkItemStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.adoption_entered = asyncio.Event()
        self.release_adoption = asyncio.Event()

    async def adopt_child_plan_with_parent_metadata(
        self,
        parent_id: str,
        **kwargs: Any,
    ) -> WorkItem:
        self.adoption_entered.set()
        await self.release_adoption.wait()
        return await super().adopt_child_plan_with_parent_metadata(
            parent_id,
            **kwargs,
        )


class _InstallDetachBarrierStore(WorkItemStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.install_detach_entered = asyncio.Event()
        self.release_install_detach = asyncio.Event()
        self.arm_install_detach = False
        self.fail_on_get = False

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        if self.fail_on_get:
            raise AssertionError("install_recovery_plan awaited the store")
        if self.arm_install_detach and not self.install_detach_entered.is_set():
            self.install_detach_entered.set()
            await self.release_install_detach.wait()
        return await super().get_work_item(work_item_id)


class _PostCommitPlanStore(WorkItemStore):
    def __init__(
        self,
        *args: Any,
        fail_mode: str,
        fail_operation: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fail_mode = fail_mode
        self.fail_operation = fail_operation

    def _raise_after_commit(self) -> None:
        if self.fail_mode == "cancel":
            raise asyncio.CancelledError()
        raise RuntimeError("injected post-commit plan failure")

    async def install_child_plan_with_parent_metadata(
        self,
        parent_id: str,
        **kwargs: Any,
    ) -> tuple[WorkItem, tuple[WorkItem, ...]]:
        result = await super().install_child_plan_with_parent_metadata(
            parent_id,
            **kwargs,
        )
        if self.fail_operation == "install":
            self._raise_after_commit()
        return result

    async def adopt_child_plan_with_parent_metadata(
        self,
        parent_id: str,
        **kwargs: Any,
    ) -> WorkItem:
        result = await super().adopt_child_plan_with_parent_metadata(
            parent_id,
            **kwargs,
        )
        if self.fail_operation == "adopt":
            self._raise_after_commit()
        return result


class _RepeatedCancelPlanStore(WorkItemStore):
    def __init__(
        self,
        *args: Any,
        operation: str,
        first_cancellation: asyncio.CancelledError,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.operation = operation
        self.first_cancellation = first_cancellation
        self.commit_raised = False
        self.reconciliation_entered = asyncio.Event()
        self.release_reconciliation = asyncio.Event()
        self.reconciliation_task: asyncio.Task[Any] | None = None

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        if self.commit_raised and not self.reconciliation_entered.is_set():
            self.reconciliation_task = asyncio.current_task()
            self.reconciliation_entered.set()
            await self.release_reconciliation.wait()
        return await super().get_work_item(work_item_id)

    async def install_child_plan_with_parent_metadata(
        self,
        parent_id: str,
        **kwargs: Any,
    ) -> tuple[WorkItem, tuple[WorkItem, ...]]:
        result = await super().install_child_plan_with_parent_metadata(
            parent_id,
            **kwargs,
        )
        if self.operation == "install":
            self.commit_raised = True
            raise self.first_cancellation
        return result

    async def adopt_child_plan_with_parent_metadata(
        self,
        parent_id: str,
        **kwargs: Any,
    ) -> WorkItem:
        result = await super().adopt_child_plan_with_parent_metadata(
            parent_id,
            **kwargs,
        )
        if self.operation == "adopt":
            self.commit_raised = True
            raise self.first_cancellation
        return result


class _PostCommitTerminalStore(WorkItemStore):
    def __init__(
        self,
        *args: Any,
        terminal_error: BaseException,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.terminal_error = terminal_error
        self.post_commit_raised = False
        self.reconciliation_reads = 0
        self.fallback_calls = 0

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        if self.post_commit_raised:
            self.reconciliation_reads += 1
        return await super().get_work_item(work_item_id)

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        **kwargs: Any,
    ) -> WorkItem | None:
        source = kwargs.get("source")
        if source == "crew_executor_persistence_fallback":
            self.fallback_calls += 1
        updated = await super().merge_work_item_metadata(
            work_item_id,
            patch,
            **kwargs,
        )
        if (
            source == "crew_executor"
            and "crew_execution" in patch
            and not self.post_commit_raised
        ):
            self.post_commit_raised = True
            raise self.terminal_error
        return updated


class _PreCommitTerminalCancelStore(WorkItemStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.cancelled = False
        self.fallback_calls = 0

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        **kwargs: Any,
    ) -> WorkItem | None:
        source = kwargs.get("source")
        if source == "crew_executor" and not self.cancelled:
            self.cancelled = True
            raise asyncio.CancelledError("terminal-precommit-sentinel")
        if source == "crew_executor_persistence_fallback":
            self.fallback_calls += 1
        return await super().merge_work_item_metadata(
            work_item_id,
            patch,
            **kwargs,
        )


class _CheckpointAttachmentStore:
    def __init__(
        self,
        delegate: Any,
        *,
        stage: str,
        fault: BaseException,
        child_count: int,
    ) -> None:
        self._delegate = delegate
        self._stage = stage
        self._fault = fault
        self._child_count = child_count
        self._chat_writes = 0
        self._failed = False

    async def write(
        self,
        content_hash: str,
        blob: bytes,
        mime: str,
        *,
        origin: str = "chat_attachment",
    ) -> Path:
        path = await self._delegate.write(
            content_hash,
            blob,
            mime,
            origin=origin,
        )
        if origin == "chat_attachment":
            self._chat_writes += 1
        should_fail = (
            self._stage == "result_blob"
            and origin == "agent_artifact"
        ) or (
            self._stage == "provenance"
            and origin == "chat_attachment"
            and self._chat_writes == self._child_count + 3
        )
        if should_fail and not self._failed:
            self._failed = True
            raise self._fault
        return path

    async def read(self, content_hash: str) -> bytes:
        return await self._delegate.read(content_hash)


class _CheckpointArtifactStore:
    def __init__(self, delegate: ArtifactStore, fault: BaseException) -> None:
        self._delegate = delegate
        self._fault = fault
        self._failed = False

    def reconcile_exact_version(self, **kwargs: Any) -> Any:
        artifact = self._delegate.reconcile_exact_version(**kwargs)
        if not self._failed:
            self._failed = True
            raise self._fault
        return artifact

    def list_versions(self, **kwargs: Any) -> list[Any]:
        return self._delegate.list_versions(**kwargs)


class _PostPublicationService:
    def __init__(self, delegate: CrewSessionService, fault: BaseException) -> None:
        self._delegate = delegate
        self._fault = fault
        self._failed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    async def publish_verified_result(
        self,
        parent_id: str,
        **kwargs: Any,
    ) -> Any:
        result = await self._delegate.publish_verified_result(
            parent_id,
            **kwargs,
        )
        if not self._failed:
            self._failed = True
            raise self._fault
        return result


@pytest.fixture
async def work_store(tmp_path: Path) -> Any:
    store = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


def _admission_port(store: WorkItemStore) -> CrewSessionAdmissionPort:
    port = _ADMISSION_PORTS.get(store)
    if port is None:
        port = store.claim_crew_session_admission_port()
        _ADMISSION_PORTS[store] = port
    return port


async def _create_crew_parent(
    store: WorkItemStore,
    *,
    parent_id: str,
    title: str,
    assigned_to: str = "facilitator-1",
    created_by: str = "captain",
    created_at: float = 100.0,
    metadata: dict[str, Any] | None = None,
    status: str = "draft",
) -> WorkItem:
    async with _admission_port(store).reserve() as reservation:
        parent = await reservation.create_parent(CrewSessionParentCreate(
            id=parent_id,
            title=title,
            description=title,
            assigned_to=assigned_to,
            created_by=created_by,
            metadata={},
            created_at=created_at,
        ))
    if metadata:
        parent = await store.merge_work_item_metadata(
            parent.id,
            dict(metadata),
            expected_work_type="crew_session",
            expected_status="draft",
            expected_assigned_to=assigned_to,
        )
        assert parent is not None
    paths = {
        "draft": (),
        "open": ("open",),
        "in_progress": ("open", "in_progress"),
        "review": ("open", "in_progress", "review"),
        "blocked": ("open", "blocked"),
        "done": ("open", "in_progress", "review", "done"),
        "failed": ("open", "failed"),
    }
    if status not in paths:
        raise ValueError("crew_session_fixture_status_invalid")
    for next_status in paths[status]:
        parent = await store.merge_work_item_metadata(
            parent.id,
            {},
            expected_work_type="crew_session",
            expected_status=parent.status,
            expected_assigned_to=assigned_to,
            new_status=next_status,
        )
        assert parent is not None
    return parent


async def _new_session(
    work_store: WorkItemStore,
    tmp_path: Path,
) -> tuple[WorkItem, CrewSessionService, Any]:
    parent = await _create_crew_parent(
        work_store,
        parent_id="session-parent",
        title="Session",
    )
    threads = ChatThreadStore(tmp_path / "threads.db")
    thread = threads.create_thread(
        title="Session room",
        participants=["facilitator-1", "agent-1"],
        task_id=parent.id,
    )
    service = CrewSessionService(
        work_item_store=work_store,
        chat_thread_store=threads,
        clock=_Clock(200.0),
    )
    session = await service.initialize_session(
        parent.id,
        thread.id,
        goal="Produce a durable result",
        origin="captain",
        originator_id="captain",
        facilitator_id="facilitator-1",
        owner_ids=["facilitator-1", "agent-1"],
        success_criteria=["Result is complete"],
        expected_deliverable="A report",
    )
    return parent, service, session


def _recovery_payload(**updates: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": 1,
        "phase": "unplanned",
        "plan": None,
        "attempt_count": 0,
        "retry_count": 0,
        "last_attempt_at": None,
        "next_attempt_at": None,
        "last_error_code": None,
        "interrupted_child_ids": [],
        "synthesis_ref": None,
        "final_verification_ref": None,
        "result_artifact_id": None,
        "provenance_ref": None,
    }
    payload.update(updates)
    return payload


def _vector_plan_payload(*, row_hash: str = _VECTOR_ROW_HASH) -> dict[str, Any]:
    return {
        "version": 1,
        "plan_seed_hash": _VECTOR_PLAN_SEED_HASH,
        "plan_hash": _VECTOR_PLAN_HASH,
        "children": [
            {
                "child_id": _VECTOR_CHILD_ID,
                "spec_id": "spec-a",
                "row_hash": row_hash,
            }
        ],
    }


def _vector_insert() -> Any:
    from probos.workforce import WorkItemPlanInsert

    return WorkItemPlanInsert(
        id=_VECTOR_CHILD_ID,
        title="Child",
        description="Do it",
        work_type="task",
        priority=3,
        depends_on=(),
        assigned_to=None,
        created_by="facilitator-1",
        trust_requirement=0.0,
        required_capabilities=(),
        metadata={
            "spec_id": "spec-a",
            "resources": [],
            "expected_output": None,
            "capability": None,
            "department": None,
        },
    )


def test_config_defaults_and_bounds_are_exact() -> None:
    config = AgenticDispatchConfig()
    assert config.max_parallel_subtasks == 3
    assert config.max_active_crew_sessions == 2
    assert config.crew_resume_scan_limit == 100
    assert config.crew_recovery_max_retries == 3
    assert config.crew_recovery_initial_backoff_seconds == 5.0
    assert config.crew_recovery_max_backoff_seconds == 300.0

    for field, value in (
        ("max_parallel_subtasks", 0),
        ("max_active_crew_sessions", 33),
        ("crew_resume_scan_limit", 0),
        ("crew_recovery_max_retries", 11),
        ("crew_recovery_initial_backoff_seconds", -1.0),
        ("crew_recovery_max_backoff_seconds", 86_401.0),
    ):
        with pytest.raises(ValidationError):
            AgenticDispatchConfig(**{field: value})

    with pytest.raises(ValidationError):
        AgenticDispatchConfig(
            crew_recovery_initial_backoff_seconds=10.0,
            crew_recovery_max_backoff_seconds=9.0,
        )


def test_recovery_contract_is_strict_phase_aware_and_json_type_exact() -> None:
    from probos.cognitive.crew_session import CrewRecoveryContract

    recovery = CrewRecoveryContract.model_validate(_recovery_payload())
    assert recovery.phase == "unplanned"
    assert recovery.model_dump(mode="json") == _recovery_payload()

    with pytest.raises(ValidationError):
        CrewRecoveryContract.model_validate(_recovery_payload(attempt_count=True))
    with pytest.raises(ValidationError):
        CrewRecoveryContract.model_validate(
            _recovery_payload(phase="planned", plan=None),
        )
    with pytest.raises(ValidationError):
        CrewRecoveryContract.model_validate(
            _recovery_payload(phase="unplanned", synthesis_ref=_SHA_A),
        )


def test_identity_fixed_vector_accepts_exact_two_stage_plan() -> None:
    from probos.cognitive.crew_session import CrewRecoveryPlan

    plan = CrewRecoveryPlan.model_validate(_vector_plan_payload())

    assert plan.plan_seed_hash == _VECTOR_PLAN_SEED_HASH
    assert plan.plan_hash == _VECTOR_PLAN_HASH
    assert plan.children[0].child_id == _VECTOR_CHILD_ID


def test_identity_fixed_vector_canonical_bytes_and_generated_hashes_are_exact() -> None:
    import hashlib

    from probos.cognitive.crew_session import (
        _build_derived_recovery_plan,
        _canonical_plan_json_bytes,
    )
    from probos.consultation.dispatch import WorkItemSpec

    semantic = [{
        "spec_id": "spec-a",
        "title": "Child",
        "description": "Do it",
        "work_type": "task",
        "priority": 3,
        "depends_on": [],
        "resources": [],
        "spec_metadata": {},
        "expected_output": None,
        "capability": None,
        "department": None,
    }]
    child_input = {
        "parent_id": "session-parent",
        "plan_seed_hash": _VECTOR_PLAN_SEED_HASH,
        "spec_id": "spec-a",
    }
    row = {
        **semantic[0],
        "child_id": _VECTOR_CHILD_ID,
        "depends_on": [],
    }
    manifest = {
        "version": 1,
        "child_id_policy": "derived_v1",
        "parent_id": "session-parent",
        "plan_seed_hash": _VECTOR_PLAN_SEED_HASH,
        "children": [{
            "child_id": _VECTOR_CHILD_ID,
            "spec_id": "spec-a",
            "row_hash": _VECTOR_ROW_HASH,
        }],
    }

    assert _canonical_plan_json_bytes(
        semantic,
        maximum_bytes=524_288,
    ) == _VECTOR_SEMANTIC_BYTES
    assert _canonical_plan_json_bytes(
        child_input,
        maximum_bytes=131_072,
    ) == _VECTOR_CHILD_INPUT_BYTES
    assert _canonical_plan_json_bytes(
        row,
        maximum_bytes=131_072,
    ) == _VECTOR_ROW_BYTES
    assert _canonical_plan_json_bytes(
        manifest,
        maximum_bytes=524_288,
    ) == _VECTOR_MANIFEST_BYTES
    assert len(_VECTOR_SEMANTIC_BYTES) == 201
    assert len(_VECTOR_CHILD_INPUT_BYTES) == 133
    assert len(_VECTOR_ROW_BYTES) == 282
    assert len(_VECTOR_MANIFEST_BYTES) == 352
    assert hashlib.sha256(_VECTOR_SEMANTIC_BYTES).hexdigest() == _VECTOR_PLAN_SEED_HASH
    assert "crew-" + hashlib.sha256(_VECTOR_CHILD_INPUT_BYTES).hexdigest() == _VECTOR_CHILD_ID
    assert hashlib.sha256(_VECTOR_ROW_BYTES).hexdigest() == _VECTOR_ROW_HASH
    assert hashlib.sha256(_VECTOR_MANIFEST_BYTES).hexdigest() == _VECTOR_PLAN_HASH

    plan, inserts = _build_derived_recovery_plan(
        "session-parent",
        [WorkItemSpec(
            spec_id="spec-a",
            title="Child",
            description="Do it",
            work_type="task",
        )],
        created_by="facilitator-1",
    )
    assert plan.model_dump(mode="json") == _vector_plan_payload()
    assert inserts == (_vector_insert(),)


class _HostileDict(dict[str, Any]):
    pass


class _HostileStr(str):
    pass


@pytest.mark.parametrize(
    "specs",
    [
        [
            {"spec_id": " spec-a ", "title": "A"},
            {"spec_id": "spec-a", "title": "B"},
        ],
        [{"spec_id": "spec-a", "title": "A", "priority": True}],
        [{"spec_id": "spec-a", "title": "A", "depends_on": ("spec-a",)}],
        [{"spec_id": "spec-a", "title": "A", "depends_on": ("missing",)}],
        [
            {"spec_id": "spec-a", "title": "A", "depends_on": ("spec-b",)},
            {"spec_id": "spec-b", "title": "B", "depends_on": ("spec-a",)},
        ],
        [{"spec_id": "spec-a", "title": "A", "resources": (" x ", "x")}],
        [{"spec_id": "spec-a", "title": "A", "metadata": {"spec_id": "x"}}],
        [{"spec_id": _HostileStr("spec-a"), "title": "A"}],
        [{"spec_id": "spec-a", "title": "A", "metadata": _HostileDict()}],
        [{"spec_id": "spec-a", "title": "\ud800"}],
        [{"spec_id": "spec-a", "title": "A", "metadata": {"n": float("nan")}}],
        [{"spec_id": "spec-a", "title": "A", "metadata": {"n": 2**63}}],
        [{
            "spec_id": "spec-a",
            "title": "A",
            "metadata": {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {}}}}}}}}},
        }],
        [{
            "spec_id": "spec-a",
            "title": "A",
            "metadata": {"nodes": list(range(4_096))},
        }],
        [{
            "spec_id": "spec-a",
            "title": "A",
            "metadata": {"text": "x" * 32_769},
        }],
    ],
)
def test_identity_invalid_semantics_reject_before_plan_build(
    specs: list[dict[str, Any]],
) -> None:
    from probos.cognitive.crew_session import _build_derived_recovery_plan
    from probos.consultation.dispatch import WorkItemSpec

    raw_specs = [WorkItemSpec(**spec) for spec in specs]
    with pytest.raises(ValueError, match="^crew_recovery_plan_semantic_invalid$"):
        _build_derived_recovery_plan(
            "session-parent",
            raw_specs,
            created_by="facilitator-1",
        )


def test_identity_duplicate_dependency_rejects_before_plan_build() -> None:
    from probos.cognitive.crew_session import _build_derived_recovery_plan
    from probos.consultation.dispatch import WorkItemSpec

    with pytest.raises(ValueError, match="^crew_recovery_plan_semantic_invalid$"):
        _build_derived_recovery_plan(
            "session-parent",
            [
                WorkItemSpec(spec_id="spec-a", title="A"),
                WorkItemSpec(
                    spec_id="spec-b",
                    title="B",
                    depends_on=("spec-a", "spec-a"),
                ),
            ],
            created_by="facilitator-1",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("plan_seed_hash", _SHA_A),
        ("plan_hash", _SHA_A),
    ],
)
def test_identity_seed_and_final_hash_tamper_reject_contextually(
    field: str,
    value: str,
) -> None:
    from probos.cognitive.crew_session import (
        CrewRecoveryPlan,
        _validate_contextual_recovery_plan,
    )

    payload = _vector_plan_payload()
    payload[field] = value
    plan = CrewRecoveryPlan.model_validate(payload)
    with pytest.raises(ValueError, match="^crew_recovery_plan_integrity_invalid$"):
        _validate_contextual_recovery_plan(
            "session-parent",
            plan,
            (_vector_insert(),),
        )


def test_identity_child_id_tamper_rejects_contextually() -> None:
    from dataclasses import replace

    from probos.cognitive.crew_session import (
        CrewRecoveryPlan,
        _validate_contextual_recovery_plan,
    )

    payload = _vector_plan_payload()
    payload["children"][0]["child_id"] = "crew-" + _SHA_A
    plan = CrewRecoveryPlan.model_validate(payload)
    row = replace(_vector_insert(), id="crew-" + _SHA_A)
    with pytest.raises(ValueError, match="^crew_recovery_plan_integrity_invalid$"):
        _validate_contextual_recovery_plan(
            "session-parent",
            plan,
            (row,),
        )


def test_identity_policy_substitution_rejects_install_mode() -> None:
    from probos.cognitive.crew_session import (
        CrewRecoveryPlan,
        _final_plan_hash,
        _validate_contextual_recovery_plan,
    )

    payload = _vector_plan_payload()
    payload["plan_hash"] = _final_plan_hash(
        "session-parent",
        _VECTOR_PLAN_SEED_HASH,
        payload["children"],
        policy="adopted_v1",
    )
    plan = CrewRecoveryPlan.model_validate(payload)
    assert _validate_contextual_recovery_plan(
        "session-parent",
        plan,
        (_vector_insert(),),
    ) == "adopted_v1"
    with pytest.raises(ValueError, match="^crew_recovery_plan_integrity_invalid$"):
        _validate_contextual_recovery_plan(
            "session-parent",
            plan,
            (_vector_insert(),),
            expected_policy="derived_v1",
        )


def test_identity_reordered_commitments_reject_contextually() -> None:
    from probos.cognitive.crew_session import (
        CrewRecoveryPlan,
        _build_derived_recovery_plan,
        _validate_contextual_recovery_plan,
    )
    from probos.consultation.dispatch import WorkItemSpec

    plan, rows = _build_derived_recovery_plan(
        "session-parent",
        [
            WorkItemSpec(spec_id="spec-a", title="A"),
            WorkItemSpec(spec_id="spec-b", title="B", depends_on=("spec-a",)),
        ],
        created_by="facilitator-1",
    )
    payload = plan.model_dump(mode="json")
    payload["children"] = list(reversed(payload["children"]))
    reordered = CrewRecoveryPlan.model_validate(payload)
    with pytest.raises(ValueError, match="^crew_recovery_plan_integrity_invalid$"):
        _validate_contextual_recovery_plan(
            "session-parent",
            reordered,
            rows,
        )


@pytest.mark.asyncio
async def test_identity_assignment_status_and_exact_runtime_evidence_are_volatile(
    work_store: WorkItemStore,
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import (
        CrewRecoveryPlan,
        _validate_contextual_recovery_plan,
    )

    parent, service, session = await _new_session(work_store, tmp_path)
    plan = CrewRecoveryPlan.model_validate(_vector_plan_payload())
    await service.install_recovery_plan(
        parent.id,
        expected_session=session,
        expected_recovery=None,
        plan=plan,
        children=(_vector_insert(),),
    )
    child = await work_store.get_work_item(_VECTOR_CHILD_ID)
    assert child is not None
    metadata = dict(child.metadata)
    metadata["crew_execution"] = {
        "version": 1,
        "parent_id": parent.id,
        "work_item_id": child.id,
        "thread_id": session.thread_id,
        "assigned_to": "agent-1",
        "status": "done",
        "stopped_reason": "complete",
        "output_summary": "done",
        "tool_trace_ref": None,
        "artifact_refs": [],
        "tokens_used": 0,
        "started_at": 300.0,
        "finished_at": 301.0,
        "blocked_dependency_ids": [],
    }
    metadata["crew_execution_output"] = {
        "version": 1,
        "content_hash": _SHA_A,
        "mime": "text/plain",
        "size_bytes": 4,
    }
    await work_store.update_work_item(
        child.id,
        assigned_to="agent-1",
        status="done",
        metadata=metadata,
    )
    live = await work_store.get_work_item(child.id)
    assert live is not None
    assert _validate_contextual_recovery_plan(
        parent.id,
        plan,
        (live,),
    ) == "derived_v1"

    await work_store.update_work_item(live.id, title="tampered")
    tampered = await work_store.get_work_item(live.id)
    assert tampered is not None
    with pytest.raises(ValueError, match="^crew_recovery_plan_integrity_invalid$"):
        _validate_contextual_recovery_plan(
            parent.id,
            plan,
            (tampered,),
        )


@pytest.mark.asyncio
async def test_identity_tampered_row_hash_rejects_before_plan_mutation(
    work_store: WorkItemStore,
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import CrewRecoveryPlan

    parent, service, session = await _new_session(work_store, tmp_path)
    tampered = CrewRecoveryPlan.model_validate(
        _vector_plan_payload(row_hash=_SHA_B),
    )

    with pytest.raises(ValueError, match="^crew_recovery_plan_integrity_invalid$"):
        await service.install_recovery_plan(
            parent.id,
            expected_session=session,
            expected_recovery=None,
            plan=tampered,
            children=(_vector_insert(),),
        )

    authoritative = await work_store.get_work_item(parent.id)
    assert authoritative is not None
    assert "crew_recovery" not in authoritative.metadata
    assert await work_store.get_work_item(_VECTOR_CHILD_ID) is None


@pytest.mark.asyncio
async def test_recovery_service_missing_then_exact_cas_and_stale_conflict(
    work_store: WorkItemStore,
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import CrewRecoveryContract

    parent, service, session = await _new_session(work_store, tmp_path)
    assert await service.get_recovery(parent.id) is None
    recovery = CrewRecoveryContract.model_validate(_recovery_payload())

    installed = await service.compare_and_set_recovery(
        parent.id,
        recovery,
        expected_session=session,
        expected_recovery=None,
    )

    assert installed == recovery
    assert await service.get_recovery(parent.id) == recovery
    with pytest.raises(ValueError, match="^crew_recovery_conflict$"):
        await service.compare_and_set_recovery(
            parent.id,
            recovery,
            expected_session=session,
            expected_recovery=None,
        )


@pytest.mark.asyncio
async def test_compare_and_set_recovery_rejects_phase_regression(
    work_store: WorkItemStore,
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import (
        CrewRecoveryContract,
        CrewRecoveryPlan,
    )

    parent, service, session = await _new_session(work_store, tmp_path)
    initial = await service.compare_and_set_recovery(
        parent.id,
        CrewRecoveryContract.model_validate(_recovery_payload()),
        expected_session=session,
        expected_recovery=None,
    )
    planned, _ = await service.install_recovery_plan(
        parent.id,
        expected_session=session,
        expected_recovery=initial,
        plan=CrewRecoveryPlan.model_validate(_vector_plan_payload()),
        children=(_vector_insert(),),
    )
    executing_recovery = CrewRecoveryContract.model_validate(
        {**planned.model_dump(mode="json"), "phase": "executing"},
    )
    executing_session = await service.transition_session(
        parent.id,
        "executing",
        expected_revision=session.revision,
        expected_recovery=planned,
        recovery=executing_recovery,
    )

    with pytest.raises(ValueError, match="^crew_recovery_phase_regression$"):
        await service.compare_and_set_recovery(
            parent.id,
            planned,
            expected_session=executing_session,
            expected_recovery=executing_recovery,
        )

    assert await service.get_recovery(parent.id) == executing_recovery


@pytest.mark.asyncio
async def test_transition_session_pairs_fine_state_and_recovery_in_one_cas(
    work_store: WorkItemStore,
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import CrewRecoveryContract

    parent, service, session = await _new_session(work_store, tmp_path)
    initial = CrewRecoveryContract.model_validate(_recovery_payload())
    initial = await service.compare_and_set_recovery(
        parent.id,
        initial,
        expected_session=session,
        expected_recovery=None,
    )
    from probos.cognitive.crew_session import CrewRecoveryPlan

    planned, _ = await service.install_recovery_plan(
        parent.id,
        expected_session=session,
        expected_recovery=initial,
        plan=CrewRecoveryPlan.model_validate(_vector_plan_payload()),
        children=(_vector_insert(),),
    )
    executing = CrewRecoveryContract.model_validate(
        {**planned.model_dump(mode="json"), "phase": "executing"}
    )

    transitioned = await service.transition_session(
        parent.id,
        "executing",
        expected_revision=session.revision,
        expected_recovery=planned,
        recovery=executing,
    )

    authoritative = await work_store.get_work_item(parent.id)
    assert authoritative is not None
    assert transitioned.state == "executing"
    assert authoritative.status == "in_progress"
    assert authoritative.metadata["crew_recovery"] == executing.model_dump(
        mode="json",
    )


@pytest.mark.asyncio
async def test_state_recovery_invariant_rejects_verifying_planned_before_work(
    work_store: WorkItemStore,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.cognitive.crew_session import CrewRecoveryContract, CrewRecoveryPlan
    from probos.config import SystemConfig

    parent, service, discussing = await _new_session(work_store, tmp_path)
    planned, _ = await service.install_recovery_plan(
        parent.id,
        expected_session=discussing,
        expected_recovery=None,
        plan=CrewRecoveryPlan.model_validate(_vector_plan_payload()),
        children=(_vector_insert(),),
    )
    executing_recovery = CrewRecoveryContract.model_validate({
        **planned.model_dump(mode="json"),
        "phase": "executing",
    })
    executing = await service.transition_session(
        parent.id,
        "executing",
        expected_revision=discussing.revision,
        expected_recovery=planned,
        recovery=executing_recovery,
    )
    verifying_recovery = CrewRecoveryContract.model_validate({
        **executing_recovery.model_dump(mode="json"),
        "phase": "verifying_children",
    })
    verifying = await service.transition_session(
        parent.id,
        "verifying",
        expected_revision=executing.revision,
        expected_recovery=executing_recovery,
        recovery=verifying_recovery,
    )
    authoritative = await work_store.get_work_item(parent.id)
    assert authoritative is not None
    corrupted_metadata = dict(authoritative.metadata)
    corrupted_metadata["crew_recovery"] = planned.model_dump(mode="json")
    corrupted = await work_store.merge_work_item_metadata(
        parent.id,
        {"crew_recovery": planned.model_dump(mode="json")},
        expected={
            "crew_session": authoritative.metadata["crew_session"],
            "crew_recovery": authoritative.metadata["crew_recovery"],
        },
        expected_work_type="crew_session",
        expected_status=authoritative.status,
        expected_assigned_to=authoritative.assigned_to,
    )
    assert corrupted is not None
    child_before = await work_store.get_work_item(_VECTOR_CHILD_ID)
    assert child_before is not None

    class _NoWork:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def resume(self, parent_id: str) -> Any:
            self.calls.append(parent_id)
            raise AssertionError("illegal authority reached downstream work")

    executor = _NoWork()
    finalizer = _NoWork()
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    owner = CrewOrchestrator(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=executor,
        verifier=object(),
        synthesizer=object(),
        work_item_store=work_store,
        runtime=SimpleNamespace(),
        config=config,
        crew_session_service=service,
        crew_session_finalizer=finalizer,
    )

    with pytest.raises(
        ValueError,
        match="^crew_session_recovery_state_conflict$",
    ):
        await service.get_session(parent.id)
    with pytest.raises(
        ValueError,
        match="^crew_session_recovery_state_conflict$",
    ):
        await owner._run_recovery_attempt(parent.id)

    child_after = await work_store.get_work_item(_VECTOR_CHILD_ID)
    parent_after = await work_store.get_work_item(parent.id)
    assert child_after is not None and parent_after is not None
    assert child_after.actual_tokens == child_before.actual_tokens
    assert child_after.metadata == child_before.metadata
    assert parent_after.metadata == corrupted_metadata
    assert executor.calls == []
    assert finalizer.calls == []
    assert verifying.state == "verifying"


@pytest.mark.asyncio
async def test_install_recovery_plan_uses_service_and_store_transaction(
    work_store: WorkItemStore,
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import CrewRecoveryContract, CrewRecoveryPlan

    parent, service, session = await _new_session(work_store, tmp_path)
    recovery = CrewRecoveryContract.model_validate(_recovery_payload())
    recovery = await service.compare_and_set_recovery(
        parent.id,
        recovery,
        expected_session=session,
        expected_recovery=None,
    )
    plan = CrewRecoveryPlan.model_validate(_vector_plan_payload())
    insert = _vector_insert()

    planned, children = await service.install_recovery_plan(
        parent.id,
        expected_session=session,
        expected_recovery=recovery,
        plan=plan,
        children=(insert,),
    )

    assert planned.phase == "planned"
    assert planned.plan == plan
    assert [child.id for child in children] == [_VECTOR_CHILD_ID]


@pytest.mark.asyncio
async def test_install_recovery_plan_detaches_children_before_first_await(
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import (
        _build_derived_recovery_plan,
        _validate_contextual_recovery_plan,
    )
    from probos.consultation.dispatch import WorkItemSpec

    store = _InstallDetachBarrierStore(
        db_path=str(tmp_path / "install-detach.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    try:
        parent, service, session = await _new_session(store, tmp_path)
        plan, children = _build_derived_recovery_plan(
            parent.id,
            [WorkItemSpec(
                spec_id="spec-detach",
                title="Detached child",
                metadata={"custom": {"values": ["original"]}},
            )],
            created_by="facilitator-1",
        )
        store.arm_install_detach = True
        installation = asyncio.create_task(service.install_recovery_plan(
            parent.id,
            expected_session=session,
            expected_recovery=None,
            plan=plan,
            children=children,
        ))
        await store.install_detach_entered.wait()

        children[0].metadata["custom"]["values"].append("caller-mutation")
        store.release_install_detach.set()
        planned, created = await installation

        assert children[0].metadata["custom"]["values"] == [
            "original",
            "caller-mutation",
        ]
        assert created[0].metadata["custom"]["values"] == ["original"]
        authoritative = await store.get_work_item(created[0].id)
        assert authoritative is not None
        assert authoritative.metadata["custom"]["values"] == ["original"]
        assert planned.plan == plan
        assert _validate_contextual_recovery_plan(
            parent.id,
            plan,
            (authoritative,),
            expected_policy="derived_v1",
        ) == "derived_v1"
    finally:
        store.release_install_detach.set()
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed_kind", ["subclass", "cycle", "scalar"])
async def test_install_recovery_plan_rejects_hostile_metadata_before_await(
    tmp_path: Path,
    malformed_kind: str,
) -> None:
    store = _InstallDetachBarrierStore(
        db_path=str(tmp_path / f"install-hostile-{malformed_kind}.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    try:
        parent, service, session = await _new_session(store, tmp_path)
        insert = _vector_insert()
        if malformed_kind == "subclass":
            malformed: Any = _HostileDict(insert.metadata)
        elif malformed_kind == "cycle":
            malformed = dict(insert.metadata)
            malformed["cycle"] = malformed
        else:
            malformed = dict(insert.metadata)
            malformed["value"] = object()
        object.__setattr__(insert, "metadata", malformed)
        store.fail_on_get = True

        from probos.cognitive.crew_session import CrewRecoveryPlan

        with pytest.raises(
            ValueError,
            match="^crew_recovery_plan_integrity_invalid$",
        ):
            await service.install_recovery_plan(
                parent.id,
                expected_session=session,
                expected_recovery=None,
                plan=CrewRecoveryPlan.model_validate(_vector_plan_payload()),
                children=(insert,),
            )
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_adopt_recovery_plan_commits_adopted_policy_for_exact_children(
    work_store: WorkItemStore,
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import (
        _build_adopted_recovery_plan,
        _validate_contextual_recovery_plan,
    )

    parent, service, session = await _new_session(work_store, tmp_path)
    child = await work_store.create_work_item(
        id="existing-child-a",
        title="Existing child",
        description="Preserve me",
        work_type="task",
        priority=2,
        parent_id=parent.id,
        depends_on=[],
        assigned_to=None,
        created_by="facilitator-1",
        metadata={
            "spec_id": "spec-existing",
            "resources": [],
            "expected_output": None,
            "capability": None,
            "department": None,
        },
    )
    plan = _build_adopted_recovery_plan(parent.id, (child,))

    adopted = await service.adopt_recovery_plan(
        parent.id,
        expected_session=session,
        expected_recovery=None,
        plan=plan,
        expected_children=(child,),
    )

    assert adopted.phase == "planned"
    assert adopted.plan == plan
    assert _validate_contextual_recovery_plan(
        parent.id,
        plan,
        (child,),
    ) == "adopted_v1"


@pytest.mark.asyncio
async def test_adopt_recovery_plan_child_changes_before_store_lock_rejects(
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import _build_adopted_recovery_plan

    store = _AdoptionBarrierStore(
        db_path=str(tmp_path / "adoption-race.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    try:
        parent, service, session = await _new_session(store, tmp_path)
        child = await store.create_work_item(
            id="existing-child-race",
            title="Before",
            description="Stable snapshot",
            work_type="task",
            parent_id=parent.id,
            assigned_to=None,
            metadata={
                "spec_id": "spec-race",
                "resources": [],
                "expected_output": None,
                "capability": None,
                "department": None,
            },
        )
        plan = _build_adopted_recovery_plan(parent.id, (child,))
        adoption = asyncio.create_task(service.adopt_recovery_plan(
            parent.id,
            expected_session=session,
            expected_recovery=None,
            plan=plan,
            expected_children=(child,),
        ))
        await store.adoption_entered.wait()
        await store.update_work_item(child.id, title="After")
        store.release_adoption.set()

        with pytest.raises(ValueError, match="^work_item_plan_children_conflict$"):
            await adoption
        authoritative = await store.get_work_item(parent.id)
        assert authoritative is not None
        assert "crew_recovery" not in authoritative.metadata
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_mode", ["error", "cancel"])
async def test_install_recovery_plan_reconciles_exact_post_commit_authority(
    tmp_path: Path,
    fail_mode: str,
) -> None:
    from probos.cognitive.crew_session import CrewRecoveryPlan

    store = _PostCommitPlanStore(
        db_path=str(tmp_path / f"install-{fail_mode}.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
        fail_mode=fail_mode,
        fail_operation="install",
    )
    await store.start()
    try:
        parent, service, session = await _new_session(store, tmp_path)
        call = service.install_recovery_plan(
            parent.id,
            expected_session=session,
            expected_recovery=None,
            plan=CrewRecoveryPlan.model_validate(_vector_plan_payload()),
            children=(_vector_insert(),),
        )
        if fail_mode == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await call
        else:
            planned, children = await call
            assert planned.plan is not None
            assert [child.id for child in children] == [_VECTOR_CHILD_ID]
        authoritative = await service.get_recovery(parent.id)
        assert authoritative is not None
        assert authoritative.plan is not None
        assert authoritative.plan.plan_hash == _VECTOR_PLAN_HASH
        assert await store.get_work_item(_VECTOR_CHILD_ID) is not None
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_mode", ["error", "cancel"])
async def test_adopt_recovery_plan_reconciles_exact_post_commit_authority(
    tmp_path: Path,
    fail_mode: str,
) -> None:
    from probos.cognitive.crew_session import _build_adopted_recovery_plan

    store = _PostCommitPlanStore(
        db_path=str(tmp_path / f"adopt-{fail_mode}.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
        fail_mode=fail_mode,
        fail_operation="adopt",
    )
    await store.start()
    try:
        parent, service, session = await _new_session(store, tmp_path)
        child = await store.create_work_item(
            id=f"existing-{fail_mode}",
            title="Existing",
            work_type="task",
            parent_id=parent.id,
            metadata={
                "spec_id": f"spec-{fail_mode}",
                "resources": [],
                "expected_output": None,
                "capability": None,
                "department": None,
            },
        )
        plan = _build_adopted_recovery_plan(parent.id, (child,))
        call = service.adopt_recovery_plan(
            parent.id,
            expected_session=session,
            expected_recovery=None,
            plan=plan,
            expected_children=(child,),
        )
        if fail_mode == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await call
        else:
            adopted = await call
            assert adopted.plan == plan
        authoritative = await service.get_recovery(parent.id)
        assert authoritative is not None
        assert authoritative.plan == plan
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_install_recovery_plan_repeated_cancel_preserves_first_and_authority(
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import CrewRecoveryPlan

    first_cancellation = asyncio.CancelledError("install-first-cancellation")
    store = _RepeatedCancelPlanStore(
        db_path=str(tmp_path / "install-repeated-cancel.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
        operation="install",
        first_cancellation=first_cancellation,
    )
    await store.start()
    try:
        parent, service, session = await _new_session(store, tmp_path)
        installing = asyncio.create_task(service.install_recovery_plan(
            parent.id,
            expected_session=session,
            expected_recovery=None,
            plan=CrewRecoveryPlan.model_validate(_vector_plan_payload()),
            children=(_vector_insert(),),
        ))
        await store.reconciliation_entered.wait()
        installing.cancel("install-second-cancellation")
        await asyncio.sleep(0)
        assert installing.done() is False
        store.release_reconciliation.set()

        with pytest.raises(asyncio.CancelledError) as raised:
            await installing
        assert raised.value is first_cancellation
        assert raised.value.args == ("install-first-cancellation",)
        recovery = await service.get_recovery(parent.id)
        children = await store.list_work_items(parent_id=parent.id, limit=1_001)
        assert recovery is not None and recovery.plan is not None
        assert recovery.plan.plan_hash == _VECTOR_PLAN_HASH
        assert [child.id for child in children] == [_VECTOR_CHILD_ID]
        assert store.reconciliation_task is not None
        assert store.reconciliation_task.done() is True
        assert store.reconciliation_task.cancelled() is False
        assert store.reconciliation_task.exception() is None
        assert store._work_item_row_write_lock.locked() is False
        authoritative_parent = await store.get_work_item(parent.id)
        assert authoritative_parent is not None
        updated = await store.merge_work_item_metadata(
            parent.id,
            {"post_reconcile_probe": "install"},
            expected_work_type="crew_session",
            expected_status=authoritative_parent.status,
            expected_assigned_to=authoritative_parent.assigned_to,
        )
        assert updated is not None
        assert updated.metadata["post_reconcile_probe"] == "install"
    finally:
        store.release_reconciliation.set()
        await store.stop()


@pytest.mark.asyncio
async def test_adopt_recovery_plan_repeated_cancel_preserves_first_and_authority(
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import _build_adopted_recovery_plan

    first_cancellation = asyncio.CancelledError("adopt-first-cancellation")
    store = _RepeatedCancelPlanStore(
        db_path=str(tmp_path / "adopt-repeated-cancel.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
        operation="adopt",
        first_cancellation=first_cancellation,
    )
    await store.start()
    try:
        parent, service, session = await _new_session(store, tmp_path)
        child = await store.create_work_item(
            id="existing-repeated-cancel",
            title="Existing",
            work_type="task",
            parent_id=parent.id,
            metadata={
                "spec_id": "spec-repeated-cancel",
                "resources": [],
                "expected_output": None,
                "capability": None,
                "department": None,
            },
        )
        plan = _build_adopted_recovery_plan(parent.id, (child,))
        adopting = asyncio.create_task(service.adopt_recovery_plan(
            parent.id,
            expected_session=session,
            expected_recovery=None,
            plan=plan,
            expected_children=(child,),
        ))
        await store.reconciliation_entered.wait()
        adopting.cancel("adopt-second-cancellation")
        await asyncio.sleep(0)
        assert adopting.done() is False
        store.release_reconciliation.set()

        with pytest.raises(asyncio.CancelledError) as raised:
            await adopting
        assert raised.value is first_cancellation
        assert raised.value.args == ("adopt-first-cancellation",)
        recovery = await service.get_recovery(parent.id)
        children = await store.list_work_items(parent_id=parent.id, limit=1_001)
        assert recovery is not None and recovery.plan == plan
        assert [authoritative.id for authoritative in children] == [child.id]
        assert children[0].to_dict() == child.to_dict()
        assert store.reconciliation_task is not None
        assert store.reconciliation_task.done() is True
        assert store.reconciliation_task.cancelled() is False
        assert store.reconciliation_task.exception() is None
        assert store._work_item_row_write_lock.locked() is False
        authoritative_parent = await store.get_work_item(parent.id)
        assert authoritative_parent is not None
        updated = await store.merge_work_item_metadata(
            parent.id,
            {"post_reconcile_probe": "adopt"},
            expected_work_type="crew_session",
            expected_status=authoritative_parent.status,
            expected_assigned_to=authoritative_parent.assigned_to,
        )
        assert updated is not None
        assert updated.metadata["post_reconcile_probe"] == "adopt"
    finally:
        store.release_reconciliation.set()
        await store.stop()


@pytest.mark.asyncio
async def test_scan_uses_one_global_limit_and_deterministic_order(
    work_store: WorkItemStore,
) -> None:
    rows = (
        ("old-review", "review", 10.0),
        ("old-open", "open", 10.0),
        ("middle-progress", "in_progress", 20.0),
        ("done-row", "done", 1.0),
        ("blocked-row", "blocked", 2.0),
        ("failed-row", "failed", 3.0),
        ("ordinary-task", "open", 4.0),
    )
    for item_id, status, created_at in rows:
        if item_id == "ordinary-task":
            await work_store.create_work_item(
                id=item_id,
                title=item_id,
                work_type="task",
                status=status,
                assigned_to="facilitator-1",
                created_at=created_at,
                updated_at=created_at,
            )
        else:
            await _create_crew_parent(
                work_store,
                parent_id=item_id,
                title=item_id,
                created_at=created_at,
                status=status,
            )

    candidates = await work_store.list_crew_session_recovery_candidates(limit=2)

    assert [item.id for item in candidates] == ["old-open", "old-review"]


@pytest.mark.asyncio
async def test_plan_install_is_atomic_and_creates_one_requirement_per_child(
    work_store: WorkItemStore,
) -> None:
    from probos.workforce import WorkItemPlanInsert

    parent = await _create_crew_parent(
        work_store,
        parent_id="parent-plan",
        title="Session",
        status="open",
        metadata={"crew_session": {"version": 1}},
    )
    children = (
        WorkItemPlanInsert(
            id="crew-child-a",
            title="A",
            description="First",
            work_type="task",
            priority=2,
            depends_on=(),
            assigned_to="agent-1",
            created_by="facilitator-1",
            trust_requirement=0.4,
            required_capabilities=("write",),
            metadata={"spec_id": "a"},
        ),
        WorkItemPlanInsert(
            id="crew-child-b",
            title="B",
            description="Second",
            work_type="task",
            priority=3,
            depends_on=("crew-child-a",),
            assigned_to=None,
            created_by="facilitator-1",
            trust_requirement=0.0,
            required_capabilities=(),
            metadata={"spec_id": "b"},
        ),
    )

    updated, created = await work_store.install_child_plan_with_parent_metadata(
        parent.id,
        expected_parent_metadata=parent.metadata,
        expected_status="open",
        expected_assigned_to="facilitator-1",
        parent_patch={"crew_recovery": _recovery_payload(phase="planned", plan={})},
        children=children,
    )

    assert updated.metadata["crew_recovery"]["phase"] == "planned"
    assert [item.id for item in created] == ["crew-child-a", "crew-child-b"]
    cursor = await work_store._db.execute(
        "SELECT work_item_id FROM resource_requirements "
        "WHERE work_item_id IN (?, ?) ORDER BY work_item_id",
        ("crew-child-a", "crew-child-b"),
    )
    assert [row["work_item_id"] for row in await cursor.fetchall()] == [
        "crew-child-a",
        "crew-child-b",
    ]


@pytest.mark.asyncio
async def test_plan_install_cancellation_rolls_back_every_child_and_parent_patch(
    work_store: WorkItemStore,
) -> None:
    from probos.workforce import WorkItemPlanInsert

    parent = await _create_crew_parent(
        work_store,
        parent_id="parent-cancel",
        title="Session",
        status="open",
        metadata={"crew_session": {"version": 1}},
    )
    child = WorkItemPlanInsert(
        id="crew-child-cancel",
        title="Child",
        description="Child",
        work_type="task",
        priority=3,
        depends_on=(),
        assigned_to=None,
        created_by="facilitator-1",
        trust_requirement=0.0,
        required_capabilities=(),
        metadata={"spec_id": "cancel"},
    )
    original_execute = work_store._db.execute

    async def cancelling_execute(sql: str, parameters: Any = ()) -> Any:
        if "INSERT INTO resource_requirements" in " ".join(sql.split()):
            raise asyncio.CancelledError()
        return await original_execute(sql, parameters)

    work_store._db.execute = cancelling_execute
    with pytest.raises(asyncio.CancelledError):
        await work_store.install_child_plan_with_parent_metadata(
            parent.id,
            expected_parent_metadata=parent.metadata,
            expected_status="open",
            expected_assigned_to="facilitator-1",
            parent_patch={"crew_recovery": _recovery_payload(phase="planned", plan={})},
            children=(child,),
        )

    authoritative_parent = await work_store.get_work_item(parent.id)
    assert authoritative_parent is not None
    assert authoritative_parent.metadata == parent.metadata
    assert await work_store.get_work_item(child.id) is None


@pytest.mark.asyncio
async def test_child_checkpoint_commits_verification_recovery_and_tokens_atomically(
    work_store: WorkItemStore,
) -> None:
    child = await work_store.create_work_item(
        id="child-checkpoint",
        title="Child",
        description="Verify child",
        work_type="task",
        status="done",
        parent_id="parent-checkpoint",
        assigned_to="agent-1",
        actual_tokens=7,
        metadata={"spec_id": "checkpoint"},
    )
    verification = {"version": 1, "status": "converged"}
    recovery = {
        "version": 1,
        "convergence_ref": _SHA_A,
    }

    updated = await work_store.compare_and_set_work_item_verification(
        child.id,
        verification,
        expected_verification={},
        expected_work_type=child.work_type,
        expected_status=child.status,
        expected_assigned_to="agent-1",
        expected_parent_id="parent-checkpoint",
        expected_title=child.title,
        expected_description=child.description,
        expected_depends_on=[],
        expected_metadata=child.metadata,
        expected_actual_tokens=7,
        metadata_patch={"crew_verification_recovery": recovery},
        actual_tokens_delta=3,
    )

    assert updated is not None
    assert updated.verification == verification
    assert updated.metadata == {
        "spec_id": "checkpoint",
        "crew_verification_recovery": recovery,
    }
    assert updated.actual_tokens == 10


def test_artifact_reconcile_exact_version_handles_zero_one_and_many(tmp_path: Path) -> None:
    store = ArtifactStore(
        tmp_path / "artifacts.db",
        clock=_Clock(),
        id_factory=_IdFactory(),
    )
    expected = {
        "thread_id": "thread-1",
        "name": "crew-result.md",
        "content_hash": _SHA_A,
        "mime": "text/markdown",
        "size_bytes": 12,
        "created_by": "facilitator-1",
    }

    created = store.reconcile_exact_version(**expected)
    reused = store.reconcile_exact_version(**expected)
    assert reused.id == created.id
    assert reused.version == 1
    assert len(store.list_versions(thread_id="thread-1", name="crew-result.md")) == 1

    conflicting = ArtifactStore(
        tmp_path / "conflicting.db",
        clock=_Clock(),
        id_factory=_IdFactory(),
    )
    conflicting.add_version(**{**expected, "content_hash": _SHA_B})
    with pytest.raises(ValueError, match="^artifact_exact_match_conflict$"):
        conflicting.reconcile_exact_version(**expected)
    assert len(conflicting.list_versions(thread_id="thread-1", name="crew-result.md")) == 1

    ambiguous = ArtifactStore(
        tmp_path / "ambiguous.db",
        clock=_Clock(),
        id_factory=_IdFactory(),
    )
    ambiguous.add_version(**expected)
    ambiguous.add_version(**expected)
    with pytest.raises(ValueError, match="^artifact_exact_match_ambiguous$"):
        ambiguous.reconcile_exact_version(**expected)
    assert len(ambiguous.list_versions(thread_id="thread-1", name="crew-result.md")) == 2


@pytest.mark.asyncio
async def test_executor_resume_checkpoints_output_and_reconstructs_without_rerun(
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import _build_adopted_recovery_plan
    from tests.test_ad1125_room_bound_execution import (
        _Agent,
        _Registry,
        _StaticOutcomeExecutor,
        _child,
        _crew_executor,
        _runtime,
        _session_parent,
        stores as stores_fixture,
    )

    stores_generator = stores_fixture.__wrapped__(tmp_path)
    stores = await stores_generator.__anext__()
    try:
        parent, _thread, service = await _session_parent(stores)
        child = await _child(
            stores,
            parent_id=parent.id,
            child_id="resume-output-child",
        )
        session = await service.get_session(parent.id)
        assert session is not None
        executing = await service.transition_session(
            parent.id,
            "executing",
            expected_revision=session.revision,
        )
        plan = _build_adopted_recovery_plan(parent.id, (child,))
        await service.adopt_recovery_plan(
            parent.id,
            expected_session=executing,
            expected_recovery=None,
            plan=plan,
            expected_children=(child,),
        )
        outcome = _StaticOutcomeExecutor(
            output="durable child output",
            total_tokens=11,
        )
        runtime = _runtime(stores, tmp_path)
        runtime.crew_session_service = service
        executor = _crew_executor(
            stores=stores,
            registry=_Registry({"agent-1": _Agent("agent-1")}),
            executor=outcome,
            runtime=runtime,
            service=service,
        )

        first = await executor.resume(parent.id)
        second = await executor.resume(parent.id)

        assert [result.output for result in first] == ["durable child output"]
        assert [result.output for result in second] == ["durable child output"]
        assert len(outcome.calls) == 1
        stored = await stores.work.get_work_item(child.id)
        assert stored is not None and stored.actual_tokens == 11
        output_ref = stored.metadata["crew_execution_output"]
        assert output_ref["mime"] == "text/plain"
        assert output_ref["size_bytes"] == len(b"durable child output")
        assert await stores.attachments.read(output_ref["content_hash"]) == (
            b"durable child output"
        )
    finally:
        await stores_generator.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["done", "failed", "blocked"])
@pytest.mark.parametrize("cancel_commit", [False, True])
async def test_executor_terminal_post_commit_reconciles_exact_authority(
    tmp_path: Path,
    terminal_status: str,
    cancel_commit: bool,
) -> None:
    from types import SimpleNamespace

    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    from probos.cognitive.crew_executor import CrewTaskExecutor

    terminal_error: BaseException = (
        asyncio.CancelledError("terminal-sentinel")
        if cancel_commit
        else RuntimeError("terminal-post-commit")
    )
    store = _PostCommitTerminalStore(
        db_path=str(tmp_path / f"terminal-{terminal_status}-{cancel_commit}.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
        terminal_error=terminal_error,
    )
    await store.start()
    try:
        parent, service, discussing = await _new_session(store, tmp_path)
        executing = await service.transition_session(
            parent.id,
            "executing",
            expected_revision=discussing.revision,
        )
        child = await store.create_work_item(
            id=f"terminal-{terminal_status}",
            title=f"Terminal {terminal_status}",
            description="Persist exact terminal evidence",
            work_type="task",
            status="in_progress",
            parent_id=parent.id,
            assigned_to="agent-1",
            metadata={"spec_id": f"spec-{terminal_status}"},
            actual_tokens=3,
        )
        attachments = FilesystemAttachmentStore(tmp_path / "terminal-attachments")
        executor = CrewTaskExecutor(
            work_item_store=store,
            agent_registry=object(),
            agentic_executor=object(),
            runtime=SimpleNamespace(attachment_store=attachments),
            attachment_store=attachments,
        )
        output = "committed child output"
        call = executor._persist_terminal_result(
            parent_id=parent.id,
            child=child,
            thread_id=executing.thread_id,
            status=terminal_status,
            stopped_reason=(
                "complete"
                if terminal_status == "done"
                else ("unassigned" if terminal_status == "blocked" else "error")
            ),
            output=output,
            tool_trace_ref=_SHA_A,
            actual_tokens=7,
            artifact_refs=[],
            started_at=300.0,
            finished_at=301.0,
            blocked_dependency_ids=[],
            expected_status="in_progress",
        )
        if cancel_commit:
            with pytest.raises(asyncio.CancelledError) as raised:
                await call
            assert raised.value is terminal_error
            assert raised.value.args == ("terminal-sentinel",)
        else:
            result = await call
            assert result.status == terminal_status
            assert result.stopped_reason == (
                "complete"
                if terminal_status == "done"
                else ("unassigned" if terminal_status == "blocked" else "error")
            )
            assert result.actual_tokens == 7

        authoritative = await store.get_work_item(child.id)
        parent_after = await service.get_session(parent.id)
        assert authoritative is not None
        assert authoritative.status == terminal_status
        assert authoritative.actual_tokens == 10
        assert authoritative.metadata["crew_execution"]["status"] == terminal_status
        assert authoritative.metadata["crew_execution"]["tokens_used"] == 7
        if terminal_status == "done":
            output_record = authoritative.metadata["crew_execution_output"]
            assert await attachments.read(output_record["content_hash"]) == output.encode()
        else:
            assert "crew_execution_output" not in authoritative.metadata
        assert parent_after is not None and parent_after.state == "executing"
        assert store.reconciliation_reads >= 1
        assert store.fallback_calls == 0
        async with store._work_item_row_write_lock:
            pass
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_executor_terminal_precommit_cancel_falls_back_then_reraises(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.crew_executor import CrewTaskExecutor

    store = _PreCommitTerminalCancelStore(
        db_path=str(tmp_path / "terminal-precommit-cancel.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    try:
        parent = await store.create_work_item(
            id="terminal-precommit-parent",
            title="Parent",
            work_type="task",
        )
        child = await store.create_work_item(
            id="terminal-precommit-child",
            title="Child",
            work_type="task",
            status="in_progress",
            parent_id=parent.id,
            assigned_to="agent-1",
            metadata={"spec_id": "precommit-spec"},
            actual_tokens=3,
        )
        executor = CrewTaskExecutor(
            work_item_store=store,
            agent_registry=object(),
            agentic_executor=object(),
            runtime=SimpleNamespace(attachment_store=None),
        )

        with pytest.raises(asyncio.CancelledError) as raised:
            await executor._persist_terminal_result(
                parent_id=parent.id,
                child=child,
                thread_id="",
                status="failed",
                stopped_reason="error",
                output="",
                tool_trace_ref=None,
                actual_tokens=7,
                artifact_refs=[],
                started_at=300.0,
                finished_at=301.0,
                blocked_dependency_ids=[],
                expected_status="in_progress",
            )

        assert raised.value.args == ("terminal-precommit-sentinel",)
        authoritative = await store.get_work_item(child.id)
        assert authoritative is not None
        assert authoritative.status == "failed"
        assert authoritative.actual_tokens == 3
        assert "crew_execution" not in authoritative.metadata
        assert store.fallback_calls == 1
        async with store._work_item_row_write_lock:
            pass
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_executor_two_parent_tasks_are_invocation_local(
    tmp_path: Path,
) -> None:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
    from probos.cognitive.crew_session import _build_adopted_recovery_plan
    from tests.test_ad1125_room_bound_execution import (
        _Agent,
        _Registry,
        _child,
        _crew_executor,
        _runtime,
        _session_parent,
        stores as stores_fixture,
    )

    stores_generator = stores_fixture.__wrapped__(tmp_path)
    stores = await stores_generator.__anext__()
    try:
        parent_a, _thread_a, service = await _session_parent(stores)
        parent_b, _thread_b, _service_b = await _session_parent(stores)
        child_a = await _child(
            stores,
            parent_id=parent_a.id,
            child_id="isolated-child-a",
        )
        child_b = await _child(
            stores,
            parent_id=parent_b.id,
            child_id="isolated-child-b",
        )
        for parent, child in ((parent_a, child_a), (parent_b, child_b)):
            session = await service.get_session(parent.id)
            assert session is not None
            executing = await service.transition_session(
                parent.id,
                "executing",
                expected_revision=session.revision,
            )
            plan = _build_adopted_recovery_plan(parent.id, (child,))
            await service.adopt_recovery_plan(
                parent.id,
                expected_session=executing,
                expected_recovery=None,
                plan=plan,
                expected_children=(child,),
            )

        entered = {
            parent_a.id: asyncio.Event(),
            parent_b.id: asyncio.Event(),
        }
        release = {
            parent_a.id: asyncio.Event(),
            parent_b.id: asyncio.Event(),
        }

        class _BarrierOutcome:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str]] = []
                self.cancelled: list[str] = []

            async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
                context = kwargs["extra_context"]
                parent_id = context["_crew_session_id"]
                child_id = context["_crew_work_item_id"]
                self.calls.append((parent_id, child_id))
                entered[parent_id].set()
                try:
                    await release[parent_id].wait()
                except asyncio.CancelledError:
                    self.cancelled.append(parent_id)
                    raise
                return WorkItemAgenticOutcome(
                    final_text=f"completed-{parent_id}",
                    stopped_reason="complete",
                    tool_trace_ref=_SHA_B,
                    total_tokens=5,
                    artifact_refs=[],
                )

        outcome = _BarrierOutcome()
        runtime = _runtime(stores, tmp_path)
        runtime.crew_session_service = service
        executor = _crew_executor(
            stores=stores,
            registry=_Registry({"agent-1": _Agent("agent-1")}),
            executor=outcome,
            runtime=runtime,
            service=service,
            max_parallel=2,
        )
        task_a = asyncio.create_task(executor.resume(parent_a.id))
        task_b = asyncio.create_task(executor.resume(parent_b.id))
        await asyncio.gather(
            entered[parent_a.id].wait(),
            entered[parent_b.id].wait(),
        )

        task_a.cancel("parent-a-sentinel")
        with pytest.raises(asyncio.CancelledError) as raised:
            await task_a
        assert raised.value.args == ("parent-a-sentinel",)
        assert task_b.done() is False
        assert outcome.cancelled == [parent_a.id]

        release[parent_b.id].set()
        results_b = await task_b

        assert len(results_b) == 1
        assert results_b[0].work_item_id == child_b.id
        assert results_b[0].status == "done"
        assert outcome.calls.count((parent_a.id, child_a.id)) == 1
        assert outcome.calls.count((parent_b.id, child_b.id)) == 1
        stored_a = await stores.work.get_work_item(child_a.id)
        stored_b = await stores.work.get_work_item(child_b.id)
        assert stored_a is not None and stored_a.status == "in_progress"
        assert "crew_execution" not in stored_a.metadata
        assert stored_b is not None and stored_b.status == "done"
        assert stored_b.actual_tokens == 5
        assert stored_b.metadata["crew_execution"]["tokens_used"] == 5
        output_ref = stored_b.metadata["crew_execution_output"]
        assert await stores.attachments.read(output_ref["content_hash"]) == (
            f"completed-{parent_b.id}".encode()
        )
    finally:
        await stores_generator.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["failed", "blocked"])
async def test_executor_resume_reconstructs_terminal_failure_without_rerun(
    tmp_path: Path,
    terminal_status: str,
) -> None:
    from probos.cognitive.crew_session import _build_adopted_recovery_plan
    from tests.test_ad1125_room_bound_execution import (
        _Agent,
        _Registry,
        _StaticOutcomeExecutor,
        _child,
        _crew_executor,
        _runtime,
        _session_parent,
        stores as stores_fixture,
    )

    stores_generator = stores_fixture.__wrapped__(tmp_path)
    stores = await stores_generator.__anext__()
    try:
        parent, _thread, service = await _session_parent(stores)
        child = await _child(
            stores,
            parent_id=parent.id,
            child_id=f"resume-{terminal_status}-child",
            assigned_to=("agent-1" if terminal_status == "failed" else None),
        )
        session = await service.get_session(parent.id)
        assert session is not None
        executing = await service.transition_session(
            parent.id,
            "executing",
            expected_revision=session.revision,
        )
        plan = _build_adopted_recovery_plan(parent.id, (child,))
        await service.adopt_recovery_plan(
            parent.id,
            expected_session=executing,
            expected_recovery=None,
            plan=plan,
            expected_children=(child,),
        )
        outcome = _StaticOutcomeExecutor(
            stopped_reason="error",
            output="failed child output",
            total_tokens=5,
        )
        runtime = _runtime(stores, tmp_path)
        runtime.crew_session_service = service
        executor = _crew_executor(
            stores=stores,
            registry=_Registry({"agent-1": _Agent("agent-1")}),
            executor=outcome,
            runtime=runtime,
            service=service,
        )

        first = await executor.resume(parent.id)
        calls_after_first = len(outcome.calls)
        second = await executor.resume(parent.id)

        assert first[0].status == terminal_status
        assert second[0].status == terminal_status
        assert len(outcome.calls) == calls_after_first
        assert calls_after_first == (1 if terminal_status == "failed" else 0)
    finally:
        await stores_generator.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("durable_state", "expected_reason"),
    [
        ("in_progress", "child_execution_interrupted"),
        ("done_without_output", "child_execution_integrity"),
    ],
)
async def test_executor_resume_ambiguous_child_blocks_without_rerun(
    tmp_path: Path,
    durable_state: str,
    expected_reason: str,
) -> None:
    from probos.cognitive.crew_executor import _build_execution_evidence
    from probos.cognitive.crew_session import _build_adopted_recovery_plan
    from tests.test_ad1125_room_bound_execution import (
        _Agent,
        _Registry,
        _StaticOutcomeExecutor,
        _child,
        _crew_executor,
        _runtime,
        _session_parent,
        stores as stores_fixture,
    )

    stores_generator = stores_fixture.__wrapped__(tmp_path)
    stores = await stores_generator.__anext__()
    try:
        parent, thread, service = await _session_parent(stores)
        child = await _child(
            stores,
            parent_id=parent.id,
            child_id=f"resume-{durable_state}-child",
            status=("in_progress" if durable_state == "in_progress" else "done"),
        )
        if durable_state == "done_without_output":
            evidence = _build_execution_evidence(
                parent_id=parent.id,
                child=child,
                thread_id=thread.id,
                status="done",
                stopped_reason="complete",
                output="unreplayable output",
                tool_trace_ref=None,
                artifact_refs=[],
                actual_tokens=0,
                started_at=300.0,
                finished_at=301.0,
                blocked_dependency_ids=[],
            )
            updated = await stores.work.merge_work_item_metadata(
                child.id,
                {"crew_execution": evidence},
                expected_work_type=child.work_type,
                expected_status="done",
                expected_assigned_to="agent-1",
                expected_parent_id=parent.id,
                expected_depends_on=[],
                source="ad1127_missing_output_fixture",
            )
            assert updated is not None
            child = updated
        session = await service.get_session(parent.id)
        assert session is not None
        executing = await service.transition_session(
            parent.id,
            "executing",
            expected_revision=session.revision,
        )
        plan = _build_adopted_recovery_plan(parent.id, (child,))
        await service.adopt_recovery_plan(
            parent.id,
            expected_session=executing,
            expected_recovery=None,
            plan=plan,
            expected_children=(child,),
        )
        outcome = _StaticOutcomeExecutor()
        runtime = _runtime(stores, tmp_path)
        runtime.crew_session_service = service
        executor = _crew_executor(
            stores=stores,
            registry=_Registry({"agent-1": _Agent("agent-1")}),
            executor=outcome,
            runtime=runtime,
            service=service,
        )

        results = await executor.resume(parent.id)

        assert results[0].status == "blocked"
        assert results[0].stopped_reason == expected_reason
        assert outcome.calls == []
    finally:
        await stores_generator.aclose()


async def _durable_finalization_harness(
    tmp_path: Path,
    *,
    child_count: int,
    output_size: int,
) -> Any:
    from types import SimpleNamespace

    from probos.cognitive.crew_session import _build_adopted_recovery_plan
    from tests.test_ad1125_room_bound_execution import (
        _Agent,
        _Registry,
        _StaticOutcomeExecutor,
        _child,
        _crew_executor,
        _runtime as executor_runtime,
        _session_parent,
        stores as stores_fixture,
    )
    from tests.test_ad1126_verified_finalization import (
        _ScriptedLLM,
        _StaticAgenticExecutor,
        _make_synthesizer,
        _make_verifier,
        _registry_for,
        _runtime as finalizer_runtime,
        _text,
        _verdict,
    )

    stores_generator = stores_fixture.__wrapped__(tmp_path)
    stores = await stores_generator.__anext__()
    parent, thread, service = await _session_parent(stores)
    children = [
        await _child(
            stores,
            parent_id=parent.id,
            child_id=f"checkpoint-child-{index:02d}",
        )
        for index in range(child_count)
    ]
    session = await service.get_session(parent.id)
    assert session is not None
    executing = await service.transition_session(
        parent.id,
        "executing",
        expected_revision=session.revision,
    )
    ordered_children = tuple(sorted(children, key=lambda child: child.id))
    plan = _build_adopted_recovery_plan(parent.id, ordered_children)
    await service.adopt_recovery_plan(
        parent.id,
        expected_session=executing,
        expected_recovery=None,
        plan=plan,
        expected_children=ordered_children,
    )
    execution_runtime = executor_runtime(stores, tmp_path)
    execution_runtime.crew_session_service = service
    outcome = _StaticOutcomeExecutor(
        output="x" * output_size,
        total_tokens=7,
    )
    executor = _crew_executor(
        stores=stores,
        registry=_Registry({"agent-1": _Agent("agent-1")}),
        executor=outcome,
        runtime=execution_runtime,
        service=service,
        max_parallel=max(1, child_count),
    )
    results = await executor.resume(parent.id)
    stored_children = []
    for child in ordered_children:
        stored = await stores.work.get_work_item(child.id)
        assert stored is not None
        stored_children.append(stored)
    registry = _registry_for(stored_children)
    runtime = finalizer_runtime(stores, tmp_path, service)
    judge = _ScriptedLLM([
        *[
            _verdict(True, critique=f"Child {index} is complete.")
            for index in range(child_count)
        ],
        _verdict(
            True,
            confidence=0.98,
            critique="Final result is complete.",
        ),
    ])
    synth = _ScriptedLLM([
        _text("z" * output_size, tokens=11),
    ])
    verifier = _make_verifier(
        llm=judge,
        stores=stores,
        registry=registry,
        executor=_StaticAgenticExecutor(),
        runtime=runtime,
    )
    synthesizer = _make_synthesizer(
        llm=synth,
        stores=stores,
        runtime=runtime,
    )
    return SimpleNamespace(
        stores_generator=stores_generator,
        stores=stores,
        parent=parent,
        thread=thread,
        service=service,
        outcome=outcome,
        judge=judge,
        synth=synth,
        registry=registry,
        verifier=verifier,
        synthesizer=synthesizer,
        child_count=child_count,
        results=results,
    )


def _checkpoint_fault_finalizer(
    harness: Any,
    *,
    stage: str | None,
    fault: BaseException | None,
    service: Any | None = None,
    attachments: Any | None = None,
    artifacts: Any | None = None,
) -> Any:
    from probos.cognitive.crew_finalizer import CrewSessionFinalizer

    class _FaultFinalizer(CrewSessionFinalizer):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._fault_fired = False

        def _raise_after(self, checkpoint: str) -> None:
            if (
                stage == checkpoint
                and fault is not None
                and not self._fault_fired
            ):
                self._fault_fired = True
                raise fault

        async def _checkpoint_child_convergence(self, **kwargs: Any) -> Any:
            result = await super()._checkpoint_child_convergence(**kwargs)
            self._raise_after("child_verification")
            return result

        async def _checkpoint_synthesis(self, **kwargs: Any) -> Any:
            result = await super()._checkpoint_synthesis(**kwargs)
            self._raise_after("synthesis")
            return result

        async def _checkpoint_final_verdict(self, **kwargs: Any) -> Any:
            result = await super()._checkpoint_final_verdict(**kwargs)
            self._raise_after("verdict")
            return result

        async def _resume_provenance(self, **kwargs: Any) -> Any:
            result = await super()._resume_provenance(**kwargs)
            self._raise_after("prepublication")
            return result

    return _FaultFinalizer(
        work_item_store=harness.stores.work,
        crew_session_service=service or harness.service,
        chat_thread_store=harness.stores.chat,
        artifact_store=artifacts or harness.stores.artifacts,
        attachment_store=attachments or harness.stores.attachments,
        agent_registry=harness.registry,
        verifier=harness.verifier,
        synthesizer=harness.synthesizer,
    )


_DURABLE_CHECKPOINT_CASES = (
    ("child_verification", "verifying_children", 2, 64),
    ("synthesis", "synthesized", 2, 128),
    ("verdict", "final_verified", 1, 256),
    ("result_blob", "final_verified", 2, 512),
    ("artifact", "final_verified", 1, 1_024),
    ("provenance", "artifact_bound", 2, 2_048),
    ("prepublication", "provenance_bound", 1, 4_096),
    ("postpublication", "published", 2, 96),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault_mode", ["crash", "cancel"])
@pytest.mark.parametrize(
    ("stage", "expected_phase", "child_count", "output_size"),
    _DURABLE_CHECKPOINT_CASES,
)
async def test_finalizer_durable_checkpoint_fault_resumes_exactly_once(
    tmp_path: Path,
    stage: str,
    expected_phase: str,
    child_count: int,
    output_size: int,
    fault_mode: str,
) -> None:
    harness = await _durable_finalization_harness(
        tmp_path,
        child_count=child_count,
        output_size=output_size,
    )
    fault: BaseException = (
        asyncio.CancelledError(f"{stage}-sentinel")
        if fault_mode == "cancel"
        else RuntimeError(f"{stage}-crash")
    )
    attachments: Any = harness.stores.attachments
    artifacts: Any = harness.stores.artifacts
    service: Any = harness.service
    finalizer_stage: str | None = stage
    if stage in {"result_blob", "provenance"}:
        attachments = _CheckpointAttachmentStore(
            harness.stores.attachments,
            stage=stage,
            fault=fault,
            child_count=child_count,
        )
        finalizer_stage = None
    elif stage == "artifact":
        artifacts = _CheckpointArtifactStore(harness.stores.artifacts, fault)
        finalizer_stage = None
    elif stage == "postpublication":
        service = _PostPublicationService(harness.service, fault)
        finalizer_stage = None
    failing = _checkpoint_fault_finalizer(
        harness,
        stage=finalizer_stage,
        fault=fault,
        service=service,
        attachments=attachments,
        artifacts=artifacts,
    )
    try:
        if fault_mode == "cancel":
            with pytest.raises(asyncio.CancelledError) as raised:
                await failing.resume(harness.parent.id)
            assert raised.value is fault
            assert raised.value.args == (f"{stage}-sentinel",)
        else:
            with pytest.raises(RuntimeError, match=rf"^{stage}-crash$"):
                await failing.resume(harness.parent.id)

        recovery = await harness.service.get_recovery(harness.parent.id)
        assert recovery is not None and recovery.phase == expected_phase
        versions_before = harness.stores.artifacts.list_versions(
            thread_id=harness.thread.id,
            name="crew-result.md",
        )
        assert len(versions_before) == (1 if stage in {
            "artifact",
            "provenance",
            "prepublication",
            "postpublication",
        } else 0)

        fresh = _checkpoint_fault_finalizer(
            harness,
            stage=None,
            fault=None,
        )
        completed = await fresh.resume(harness.parent.id)

        assert completed.state == "done"
        if stage == "postpublication":
            assert completed.completed is False
            assert completed.reason == "session_terminal"
        else:
            assert completed.completed is True
        assert len(harness.outcome.calls) == child_count
        assert len(harness.judge.requests) == child_count + 1
        assert len(harness.synth.requests) == 1
        versions = harness.stores.artifacts.list_versions(
            thread_id=harness.thread.id,
            name="crew-result.md",
        )
        assert len(versions) == 1
        session = await harness.service.get_session(harness.parent.id)
        published = await harness.service.get_recovery(harness.parent.id)
        assert session is not None and session.state == "done"
        assert published is not None and published.phase == "published"
        assert session.result_artifact_id == versions[0].id
        assert session.result_ref == published.provenance_ref
        assert session.evidence_refs.count(session.result_ref) == 1
    finally:
        await harness.stores_generator.aclose()


@pytest.mark.asyncio
async def test_finalizer_resume_checkpoints_and_reuses_complete_pipeline(
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import _build_adopted_recovery_plan
    from tests.test_ad1125_room_bound_execution import (
        _Agent,
        _Registry,
        _StaticOutcomeExecutor,
        _child,
        _crew_executor,
        _runtime as executor_runtime,
        _session_parent,
        stores as stores_fixture,
    )
    from tests.test_ad1126_verified_finalization import (
        _ScriptedLLM,
        _StaticAgenticExecutor,
        _make_finalizer,
        _make_synthesizer,
        _make_verifier,
        _registry_for,
        _runtime as finalizer_runtime,
        _text,
        _verdict,
    )

    stores_generator = stores_fixture.__wrapped__(tmp_path)
    stores = await stores_generator.__anext__()
    try:
        parent, thread, service = await _session_parent(stores)
        child = await _child(
            stores,
            parent_id=parent.id,
            child_id="resume-final-child",
        )
        session = await service.get_session(parent.id)
        assert session is not None
        executing = await service.transition_session(
            parent.id,
            "executing",
            expected_revision=session.revision,
        )
        plan = _build_adopted_recovery_plan(parent.id, (child,))
        await service.adopt_recovery_plan(
            parent.id,
            expected_session=executing,
            expected_recovery=None,
            plan=plan,
            expected_children=(child,),
        )
        execution_runtime = executor_runtime(stores, tmp_path)
        execution_runtime.crew_session_service = service
        executor = _crew_executor(
            stores=stores,
            registry=_Registry({"agent-1": _Agent("agent-1")}),
            executor=_StaticOutcomeExecutor(
                output="verified durable evidence",
                total_tokens=7,
            ),
            runtime=execution_runtime,
            service=service,
        )
        execution_results = await executor.resume(parent.id)
        assert execution_results[0].status == "done"

        stored_child = await stores.work.get_work_item(child.id)
        assert stored_child is not None
        registry = _registry_for([stored_child])
        runtime = finalizer_runtime(stores, tmp_path, service)
        judge = _ScriptedLLM([
            _verdict(True, critique="Child evidence is complete."),
            _verdict(True, confidence=0.98, critique="Final result is complete."),
        ])
        synth = _ScriptedLLM([_text("Recovered final result", tokens=11)])
        finalizer = _make_finalizer(
            stores=stores,
            service=service,
            registry=registry,
            verifier=_make_verifier(
                llm=judge,
                stores=stores,
                registry=registry,
                executor=_StaticAgenticExecutor(),
                runtime=runtime,
            ),
            synthesizer=_make_synthesizer(
                llm=synth,
                stores=stores,
                runtime=runtime,
            ),
        )
        assert finalizer is not None

        completed = await finalizer.finalize(parent.id, execution_results)
        observed = await finalizer.resume(parent.id)

        assert completed.completed is True
        assert completed.final_output == "Recovered final result"
        assert observed.state == "done"
        assert len(judge.requests) == 2
        assert len(synth.requests) == 1
        versions = stores.artifacts.list_versions(
            thread_id=thread.id,
            name="crew-result.md",
        )
        assert len(versions) == 1
        recovery = await service.get_recovery(parent.id)
        assert recovery is not None and recovery.phase == "published"
    finally:
        await stores_generator.aclose()


@pytest.mark.asyncio
async def test_finalizer_artifact_checkpoint_missing_identity_creates_no_replacement(
    tmp_path: Path,
) -> None:
    import hashlib

    from probos.cognitive.crew_finalizer import CrewSessionFinalizer
    from probos.cognitive.crew_session import CrewRecoveryContract, CrewRecoveryPlan
    from tests.test_ad1126_verified_finalization import (
        _Registry,
        stores as stores_fixture,
    )

    stores_generator = stores_fixture.__wrapped__(tmp_path)
    stores = await stores_generator.__anext__()
    try:
        _parent, thread, service, session = await __import__(
            "tests.test_ad1126_verified_finalization",
            fromlist=["_new_session"],
        )._new_session(stores)
        recovery = CrewRecoveryContract.model_validate(_recovery_payload(
            phase="artifact_bound",
            plan=CrewRecoveryPlan.model_validate(
                _vector_plan_payload(),
            ).model_dump(mode="json"),
            synthesis_ref=_SHA_A,
            final_verification_ref=_SHA_B,
            result_artifact_id="missing-artifact",
        ))
        finalizer = CrewSessionFinalizer(
            work_item_store=stores.work,
            crew_session_service=service,
            chat_thread_store=stores.chat,
            artifact_store=stores.artifacts,
            attachment_store=stores.attachments,
            agent_registry=_Registry([]),
            verifier=object(),
            synthesizer=object(),
        )
        result_bytes = b"durable result"
        result_hash = hashlib.sha256(result_bytes).hexdigest()
        await stores.attachments.write(
            result_hash,
            result_bytes,
            "text/markdown",
            origin="agent_artifact",
        )

        with pytest.raises(
            ValueError,
            match="^crew_finalization_artifact_recovery_invalid$",
        ):
            await finalizer._resume_result_artifact(
                session=session,
                recovery=recovery,
                result_bytes=result_bytes,
                result_hash=result_hash,
            )

        assert stores.artifacts.list_versions(
            thread_id=thread.id,
            name="crew-result.md",
        ) == []
    finally:
        await stores_generator.aclose()


@pytest.mark.asyncio
async def test_finalizer_missing_checkpointed_provenance_fails_without_recreation(
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_session import _build_adopted_recovery_plan
    from tests.test_ad1125_room_bound_execution import (
        _Agent,
        _Registry,
        _StaticOutcomeExecutor,
        _child,
        _crew_executor,
        _runtime as executor_runtime,
        _session_parent,
        stores as stores_fixture,
    )
    from tests.test_ad1126_verified_finalization import (
        _ScriptedLLM,
        _StaticAgenticExecutor,
        _make_finalizer,
        _make_synthesizer,
        _make_verifier,
        _registry_for,
        _runtime as finalizer_runtime,
        _text,
        _verdict,
    )

    class _PublishFailureService:
        def __init__(self, delegate: CrewSessionService) -> None:
            self.delegate = delegate

        async def get_session(self, parent_id: str) -> Any:
            return await self.delegate.get_session(parent_id)

        async def get_recovery(self, parent_id: str) -> Any:
            return await self.delegate.get_recovery(parent_id)

        async def transition_session(
            self,
            parent_id: str,
            new_state: Any,
            **kwargs: Any,
        ) -> Any:
            return await self.delegate.transition_session(
                parent_id,
                new_state,
                **kwargs,
            )

        async def compare_and_set_recovery(
            self,
            parent_id: str,
            recovery: Any,
            **kwargs: Any,
        ) -> Any:
            return await self.delegate.compare_and_set_recovery(
                parent_id,
                recovery,
                **kwargs,
            )

        async def publish_verified_result(
            self,
            _parent_id: str,
            **_kwargs: Any,
        ) -> Any:
            raise RuntimeError("injected publication stop")

    stores_generator = stores_fixture.__wrapped__(tmp_path)
    stores = await stores_generator.__anext__()
    try:
        parent, thread, service = await _session_parent(stores)
        child = await _child(
            stores,
            parent_id=parent.id,
            child_id="missing-provenance-child",
        )
        session = await service.get_session(parent.id)
        assert session is not None
        executing = await service.transition_session(
            parent.id,
            "executing",
            expected_revision=session.revision,
        )
        plan = _build_adopted_recovery_plan(parent.id, (child,))
        await service.adopt_recovery_plan(
            parent.id,
            expected_session=executing,
            expected_recovery=None,
            plan=plan,
            expected_children=(child,),
        )
        execution_runtime = executor_runtime(stores, tmp_path)
        execution_runtime.crew_session_service = service
        executor = _crew_executor(
            stores=stores,
            registry=_Registry({"agent-1": _Agent("agent-1")}),
            executor=_StaticOutcomeExecutor(output="durable evidence"),
            runtime=execution_runtime,
            service=service,
        )
        execution_results = await executor.resume(parent.id)
        stored_child = await stores.work.get_work_item(child.id)
        assert stored_child is not None
        registry = _registry_for([stored_child])
        runtime = finalizer_runtime(stores, tmp_path, service)
        judge = _ScriptedLLM([
            _verdict(True, critique="Child evidence is complete."),
            _verdict(True, confidence=0.98, critique="Final result is complete."),
        ])
        synth = _ScriptedLLM([_text("Durable final result", tokens=11)])
        finalizer = _make_finalizer(
            stores=stores,
            service=_PublishFailureService(service),
            registry=registry,
            verifier=_make_verifier(
                llm=judge,
                stores=stores,
                registry=registry,
                executor=_StaticAgenticExecutor(),
                runtime=runtime,
            ),
            synthesizer=_make_synthesizer(
                llm=synth,
                stores=stores,
                runtime=runtime,
            ),
        )
        assert finalizer is not None
        with pytest.raises(RuntimeError, match="^injected publication stop$"):
            await finalizer.finalize(parent.id, execution_results)
        recovery = await service.get_recovery(parent.id)
        assert recovery is not None and recovery.phase == "provenance_bound"
        assert recovery.provenance_ref is not None
        provenance_ref = recovery.provenance_ref
        assert await stores.attachments.unlink(provenance_ref) is True
        judge_calls = len(judge.requests)
        synth_calls = len(synth.requests)

        with pytest.raises(FileNotFoundError):
            await finalizer.resume(parent.id)

        assert await stores.attachments.exists(provenance_ref) is False
        assert len(judge.requests) == judge_calls
        assert len(synth.requests) == synth_calls
        assert len(stores.artifacts.list_versions(
            thread_id=thread.id,
            name="crew-result.md",
        )) == 1
        current = await service.get_session(parent.id)
        assert current is not None and current.state == "verifying"
    finally:
        await stores_generator.aclose()


class _LifecycleOrchestrator:
    pass


class _StartGenerationScanStore(WorkItemStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.scan_entered = asyncio.Event()
        self.release_scan = asyncio.Event()
        self.scan_calls = 0
        self.fail_first = True

    async def list_crew_session_recovery_candidates(
        self,
        *,
        limit: int,
    ) -> list[WorkItem]:
        self.scan_calls += 1
        if self.fail_first:
            self.scan_entered.set()
            await self.release_scan.wait()
            raise RuntimeError("injected start scan failure")
        return await super().list_crew_session_recovery_candidates(limit=limit)


class _StartupValidationService:
    def __init__(
        self,
        store: WorkItemStore,
        *,
        fail_parent_id: str | None = None,
    ) -> None:
        self._store = store
        self.fail_parent_id = fail_parent_id
        self.repair_limits: list[int] = []

    async def repair_provisioning(self, *, limit: int) -> tuple[str, ...]:
        self.repair_limits.append(limit)
        return ()

    async def get_session(self, parent_id: str) -> Any:
        if parent_id == self.fail_parent_id:
            raise ValueError("injected_start_validation_failure")
        parent = await self._store.get_work_item(parent_id)
        if parent is None:
            return None
        state_by_status = {
            "open": "discussing",
            "in_progress": "executing",
            "review": "verifying",
            "blocked": "blocked_needs_captain",
            "done": "done",
            "failed": "failed",
        }
        return SimpleNamespace(state=state_by_status[parent.status])

    async def get_recovery(self, parent_id: str) -> None:
        return None


@pytest.mark.asyncio
async def test_lifecycle_schedule_is_keyed_synchronous_and_closes_admission(
    work_store: WorkItemStore,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.config import SystemConfig

    entered = asyncio.Event()
    release = asyncio.Event()

    class _Owner(CrewOrchestrator):
        async def run_crew_task(self, parent_id: str) -> Any:
            from probos.cognitive.crew_synth import SynthesisResult

            entered.set()
            await release.wait()
            return SynthesisResult(
                parent_id=parent_id,
                final_output="done",
                completed=True,
            )

    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    owner = _Owner(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=work_store,
        runtime=SimpleNamespace(),
        config=config,
        crew_session_service=_StartupValidationService(work_store),
    )

    with pytest.raises(RuntimeError, match="^crew_session_scheduling_closed$"):
        owner.schedule("parent-1")
    await owner.start()
    first = owner.schedule("parent-1")
    duplicate = owner.schedule("parent-1")

    assert first is duplicate
    assert first.done() is False
    await entered.wait()
    owner.close_scheduling()
    with pytest.raises(RuntimeError, match="^crew_session_scheduling_closed$"):
        owner.schedule("parent-2")
    release.set()
    assert (await first).completed is True
    await asyncio.sleep(0)
    assert owner._tasks_by_parent == {}
    await owner.stop()


@pytest.mark.asyncio
async def test_lifecycle_disabled_start_is_inert_and_enabled_start_scans_once(
    work_store: WorkItemStore,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.cognitive.crew_synth import SynthesisResult
    from probos.config import SystemConfig

    for item_id, status, created_at in (
        ("scan-b", "review", 10.0),
        ("scan-a", "open", 10.0),
        ("scan-c", "in_progress", 20.0),
        ("scan-done", "done", 1.0),
    ):
        await _create_crew_parent(
            work_store,
            parent_id=item_id,
            title=item_id,
            created_at=created_at,
            status=status,
        )

    class _ScanOwner(CrewOrchestrator):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.calls: list[str] = []

        async def _run_owned_parent(self, parent_id: str) -> SynthesisResult:
            self.calls.append(parent_id)
            return SynthesisResult(parent_id, "", False)

    def owner(config: SystemConfig) -> _ScanOwner:
        return _ScanOwner(
            assignment_resolver=object(),
            delegator=object(),
            crew_executor=object(),
            verifier=object(),
            synthesizer=object(),
            work_item_store=work_store,
            runtime=SimpleNamespace(),
            config=config,
            crew_session_service=_StartupValidationService(work_store),
        )

    disabled_config = SystemConfig()
    disabled = owner(disabled_config)
    await disabled.start()
    assert disabled.calls == []
    assert disabled._tasks_by_parent == {}

    enabled_config = SystemConfig()
    enabled_config.agentic_dispatch.orchestrator_enabled = True
    enabled_config.agentic_dispatch.crew_resume_scan_limit = 2
    enabled = owner(enabled_config)
    await enabled.start()
    await asyncio.gather(*tuple(enabled._tasks_by_parent.values()))
    await asyncio.sleep(0)
    assert enabled.calls == ["scan-a", "scan-b"]
    await enabled.start()
    assert enabled.calls == ["scan-a", "scan-b"]
    await enabled.stop()


@pytest.mark.parametrize(
    "missing_dependency",
    [
        "work_item_store",
        "registry",
        "capability_registry",
        "ontology",
        "trust_network",
        "llm_client",
        "crew_session_service",
        "chat_thread_store",
        "artifact_store",
        "attachment_store",
    ],
)
def test_enabled_startup_missing_mandatory_dependency_fails_before_admission(
    monkeypatch: pytest.MonkeyPatch,
    missing_dependency: str,
) -> None:
    from types import SimpleNamespace

    from probos.config import SystemConfig
    from probos.startup.finalize import _wire_crew_orchestrator

    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    dependencies = {
        "work_item_store": object(),
        "registry": object(),
        "capability_registry": object(),
        "ontology": object(),
        "trust_network": object(),
        "llm_client": object(),
        "crew_session_service": object(),
        "chat_thread_store": object(),
        "artifact_store": object(),
        "attachment_store": object(),
    }
    dependencies[missing_dependency] = None
    runtime = SimpleNamespace(**{
        key: value
        for key, value in dependencies.items()
        if key != "attachment_store"
    })

    def attachment_store(_runtime: Any) -> Any:
        return dependencies["attachment_store"]

    monkeypatch.setattr(
        "probos.routers.chat._get_attachment_store",
        attachment_store,
    )

    with pytest.raises(
        RuntimeError,
        match=rf"^crew_orchestrator_dependency_missing:{missing_dependency}$",
    ):
        _wire_crew_orchestrator(runtime=runtime, config=config)

    assert not hasattr(runtime, "crew_orchestrator")


@pytest.mark.asyncio
async def test_lifecycle_parent_concurrency_and_concurrent_stop_are_bounded(
    work_store: WorkItemStore,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.cognitive.crew_synth import SynthesisResult
    from probos.config import SystemConfig

    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    config.agentic_dispatch.max_active_crew_sessions = 2
    entered = asyncio.Event()
    release = asyncio.Event()

    class _BoundedOwner(CrewOrchestrator):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.active = 0
            self.max_active = 0
            self.started_count = 0
            self.cancelled_count = 0

        async def run_crew_task(self, parent_id: str) -> SynthesisResult:
            self.active += 1
            self.started_count += 1
            self.max_active = max(self.max_active, self.active)
            if self.started_count == 2:
                entered.set()
            try:
                await release.wait()
                return SynthesisResult(parent_id, "", False)
            except asyncio.CancelledError:
                self.cancelled_count += 1
                raise
            finally:
                self.active -= 1

    owner = _BoundedOwner(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=work_store,
        runtime=SimpleNamespace(),
        config=config,
        crew_session_service=_StartupValidationService(work_store),
    )
    await owner.start()
    tasks = [owner.schedule(f"parent-{index}") for index in range(4)]
    await entered.wait()
    assert owner.max_active == 2
    first_stop = asyncio.create_task(owner.stop())
    second_stop = asyncio.create_task(owner.stop())
    await asyncio.gather(first_stop, second_stop)
    assert owner.cancelled_count == 2
    assert all(task.done() for task in tasks)
    with pytest.raises(RuntimeError, match="^crew_session_lifecycle_stopped$"):
        await owner.start()


@pytest.mark.asyncio
async def test_lifecycle_stop_preserves_first_repeated_cancellation(
    work_store: WorkItemStore,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.cognitive.crew_synth import SynthesisResult
    from probos.config import SystemConfig

    cleanup_entered = asyncio.Event()
    release_cleanup = asyncio.Event()

    class _StopOwner(CrewOrchestrator):
        async def _drain_parent_tasks(self) -> None:
            cleanup_entered.set()
            await release_cleanup.wait()

        async def run_crew_task(self, parent_id: str) -> SynthesisResult:
            return SynthesisResult(parent_id, "", False)

    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    owner = _StopOwner(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=work_store,
        runtime=SimpleNamespace(),
        config=config,
        crew_session_service=_StartupValidationService(work_store),
    )
    await owner.start()
    stopping = asyncio.create_task(owner.stop())
    await cleanup_entered.wait()
    stopping.cancel("sentinel")
    await asyncio.sleep(0)
    stopping.cancel("second")
    release_cleanup.set()

    with pytest.raises(asyncio.CancelledError) as raised:
        await stopping
    assert raised.value.args == ("sentinel",)
    assert owner._stop_cleanup_task is not None
    assert owner._stop_cleanup_task.done() is True


@pytest.mark.asyncio
async def test_production_shutdown_drains_crew_first_and_preserves_clean_marker(
    tmp_path: Path,
) -> None:
    import time

    from probos.shutdown_integrity import mark_clean_shutdown, read_shutdown_status
    from probos.startup.shutdown import shutdown

    order: list[str] = []
    stop_entered = asyncio.Event()
    release_stop = asyncio.Event()

    class _Registry:
        def all(self) -> list[Any]:
            return []

    class _CrewOwner:
        def close_scheduling(self) -> None:
            order.append("crew_close")

        async def stop(self) -> None:
            assert (tmp_path / "session_last.json").exists()
            order.append("crew_stop")
            stop_entered.set()
            await release_stop.wait()

    class _Runtime:
        def __init__(self) -> None:
            self._data_dir = tmp_path
            self._started = False
            self._shutdown_started = False
            self._session_id = "ad1127-shutdown"
            self._start_time_wall = time.time()
            self._start_time = time.monotonic()
            self.registry = _Registry()
            self.ontology = None
            self.crew_orchestrator = _CrewOwner()
            self.confab_probe_tasks: set[Any] = set()
            self._confab_probe_scheduling_open = True
            self.dream_scheduler = None
            self.episodic_memory = None
            self.config = None

        def close_confab_probe_scheduling(self) -> None:
            order.append("probe_close")
            self._confab_probe_scheduling_open = False

    mark_clean_shutdown(
        tmp_path,
        consolidation_result="full",
        note="phase1_ok",
    )
    before = read_shutdown_status(tmp_path)
    runtime = _Runtime()
    stopping = asyncio.create_task(shutdown(runtime, reason="ad1127 test"))
    await stop_entered.wait()

    assert order == ["crew_close", "probe_close", "crew_stop"]
    assert stopping.done() is False
    assert runtime._shutdown_started is True
    assert read_shutdown_status(tmp_path) == before

    release_stop.set()
    await stopping
    assert read_shutdown_status(tmp_path) == before

    await shutdown(runtime, reason="duplicate")
    assert order == ["crew_close", "probe_close", "crew_stop"]
    assert read_shutdown_status(tmp_path) == before


@pytest.mark.asyncio
async def test_lifecycle_failed_start_closes_drains_and_can_retry(
    work_store: WorkItemStore,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.cognitive.crew_synth import SynthesisResult
    from probos.config import SystemConfig

    await _create_crew_parent(
        work_store,
        parent_id="valid-parent",
        title="valid",
        created_at=1.0,
        status="open",
    )
    await _create_crew_parent(
        work_store,
        parent_id="second-parent",
        title="second",
        created_at=2.0,
        status="open",
    )
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True

    class _RetryOwner(CrewOrchestrator):
        async def _run_owned_parent(self, parent_id: str) -> SynthesisResult:
            await asyncio.Event().wait()

    startup_service = _StartupValidationService(
        work_store,
        fail_parent_id="second-parent",
    )
    owner = _RetryOwner(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=work_store,
        runtime=SimpleNamespace(),
        config=config,
        crew_session_service=startup_service,
    )
    with pytest.raises(ValueError, match="^injected_start_validation_failure$"):
        await owner.start()
    assert owner._scheduling_open is False
    assert owner._started is False
    assert owner._tasks_by_parent == {}

    startup_service.fail_parent_id = None
    await owner.start()
    await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_start", [False, True])
async def test_lifecycle_failed_start_drains_only_its_registration_generation(
    tmp_path: Path,
    cancel_start: bool,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.cognitive.crew_synth import SynthesisResult
    from probos.config import SystemConfig

    store = _StartGenerationScanStore(
        db_path=str(tmp_path / f"start-generation-{cancel_start}.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    release_owners = asyncio.Event()

    class _GenerationOwner(CrewOrchestrator):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.observed: list[tuple[str, bool]] = []

        async def _run_owned_parent(self, parent_id: str) -> SynthesisResult:
            await release_owners.wait()
            return SynthesisResult(parent_id, "done", True)

        def _observe_parent_task(
            self,
            parent_id: str,
            task: asyncio.Task[SynthesisResult],
        ) -> None:
            self.observed.append((parent_id, task.cancelled()))
            super()._observe_parent_task(parent_id, task)

    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    owner = _GenerationOwner(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=store,
        runtime=SimpleNamespace(),
        config=config,
        crew_session_service=_StartupValidationService(store),
    )
    prior = asyncio.create_task(owner._run_owned_parent("prior-parent"))
    owner._tasks_by_parent["prior-parent"] = prior
    prior.add_done_callback(
        lambda completed: owner._observe_parent_task(
            "prior-parent",
            completed,
        ),
    )
    try:
        starting = asyncio.create_task(owner.start())
        await store.scan_entered.wait()
        external = owner.schedule("external-parent")
        if cancel_start:
            starting.cancel("start-sentinel")
        else:
            store.release_scan.set()

        if cancel_start:
            with pytest.raises(asyncio.CancelledError) as raised:
                await starting
            assert raised.value.args == ("start-sentinel",)
        else:
            with pytest.raises(
                RuntimeError,
                match="^injected start scan failure$",
            ):
                await starting

        await asyncio.sleep(0)
        assert external.cancelled() is True
        assert ("external-parent", True) in owner.observed
        assert owner._tasks_by_parent == {"prior-parent": prior}
        assert prior.done() is False
        assert owner._scheduling_open is False
        assert owner._started is False

        store.fail_first = False
        await owner.start()
        assert store.scan_calls == 2
        assert owner._started is True
    finally:
        release_owners.set()
        store.release_scan.set()
        if not prior.done():
            await prior
        await owner.stop()
        await store.stop()


@pytest.mark.asyncio
async def test_lifecycle_start_cleanup_preserves_first_repeated_cancellation(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.cognitive.crew_synth import SynthesisResult
    from probos.config import SystemConfig

    store = _StartGenerationScanStore(
        db_path=str(tmp_path / "start-cleanup-repeat.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    cleanup_entered = asyncio.Event()
    release_cleanup = asyncio.Event()

    class _RepeatedStartOwner(CrewOrchestrator):
        async def _run_owned_parent(self, parent_id: str) -> SynthesisResult:
            await asyncio.Event().wait()

        async def _drain_start_generation(
            self,
            generation: int,
            prior_tasks: dict[
                str,
                tuple[asyncio.Task[SynthesisResult], int | None],
            ],
        ) -> None:
            cleanup_entered.set()
            await release_cleanup.wait()
            await super()._drain_start_generation(generation, prior_tasks)

    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    owner = _RepeatedStartOwner(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=store,
        runtime=SimpleNamespace(),
        config=config,
        crew_session_service=_StartupValidationService(store),
    )
    try:
        starting = asyncio.create_task(owner.start())
        await store.scan_entered.wait()
        external = owner.schedule("start-cleanup-external")
        starting.cancel("sentinel")
        await cleanup_entered.wait()
        starting.cancel("second")
        release_cleanup.set()

        with pytest.raises(asyncio.CancelledError) as raised:
            await starting
        assert raised.value.args == ("sentinel",)
        assert external.cancelled() is True
        assert owner._tasks_by_parent == {}
        assert owner._scheduling_open is False
        assert owner._started is False

        store.fail_first = False
        await owner.start()
        assert owner._started is True
    finally:
        release_cleanup.set()
        store.release_scan.set()
        await owner.stop()
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("checkpoint_terminal", "expected_code"),
    [
        (False, "child_execution_cancelled_before_admission"),
        (True, "child_execution_cancelled_at_safe_boundary"),
    ],
)
async def test_lifecycle_cancellation_records_exact_safe_boundary_code(
    tmp_path: Path,
    checkpoint_terminal: bool,
    expected_code: str,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.cognitive.crew_session import _build_adopted_recovery_plan
    from probos.config import SystemConfig
    from tests.test_ad1125_room_bound_execution import (
        _Agent,
        _Registry,
        _StaticOutcomeExecutor,
        _child,
        _crew_executor,
        _runtime,
        _session_parent,
        stores as stores_fixture,
    )

    stores_generator = stores_fixture.__wrapped__(tmp_path)
    stores = await stores_generator.__anext__()
    try:
        parent, _thread, service = await _session_parent(stores)
        child = await _child(
            stores,
            parent_id=parent.id,
            child_id="cancel-boundary-child",
        )
        session = await service.get_session(parent.id)
        assert session is not None
        executing = await service.transition_session(
            parent.id,
            "executing",
            expected_revision=session.revision,
        )
        plan = _build_adopted_recovery_plan(parent.id, (child,))
        await service.adopt_recovery_plan(
            parent.id,
            expected_session=executing,
            expected_recovery=None,
            plan=plan,
            expected_children=(child,),
        )
        if checkpoint_terminal:
            runtime = _runtime(stores, tmp_path)
            runtime.crew_session_service = service
            executor = _crew_executor(
                stores=stores,
                registry=_Registry({"agent-1": _Agent("agent-1")}),
                executor=_StaticOutcomeExecutor(output="durable", total_tokens=1),
                runtime=runtime,
                service=service,
            )
            assert (await executor.resume(parent.id))[0].status == "done"

        class _CancelledOwner(CrewOrchestrator):
            async def _run_recovery_attempt(self, parent_id: str) -> Any:
                raise asyncio.CancelledError()

        config = SystemConfig()
        config.agentic_dispatch.orchestrator_enabled = True
        owner = _CancelledOwner(
            assignment_resolver=object(),
            delegator=object(),
            crew_executor=object(),
            verifier=object(),
            synthesizer=object(),
            work_item_store=stores.work,
            runtime=SimpleNamespace(),
            config=config,
            crew_session_service=service,
        )

        await owner.start()
        task = owner._tasks_by_parent[parent.id]
        with pytest.raises(asyncio.CancelledError):
            await task

        current_session = await service.get_session(parent.id)
        recovery = await service.get_recovery(parent.id)
        assert current_session is not None and current_session.state == "executing"
        assert recovery is not None
        assert recovery.last_error_code == expected_code
        assert recovery.interrupted_child_ids == ()
        await owner.stop()
    finally:
        await stores_generator.aclose()


@pytest.mark.asyncio
async def test_lifecycle_owner_recovers_session_to_published_once(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from probos.cognitive.crew_assignment import AssignmentDecision
    from probos.cognitive.crew_delegation import DelegationDecision
    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.cognitive.crew_session import _build_adopted_recovery_plan
    from probos.config import SystemConfig
    from tests.test_ad1125_room_bound_execution import (
        _Agent,
        _Registry,
        _StaticOutcomeExecutor,
        _child,
        _crew_executor,
        _runtime as executor_runtime,
        _session_parent,
        stores as stores_fixture,
    )
    from tests.test_ad1126_verified_finalization import (
        _ScriptedLLM,
        _StaticAgenticExecutor,
        _make_finalizer,
        _make_synthesizer,
        _make_verifier,
        _registry_for,
        _runtime as finalizer_runtime,
        _text,
        _verdict,
    )

    stores_generator = stores_fixture.__wrapped__(tmp_path)
    stores = await stores_generator.__anext__()
    try:
        parent, thread, service = await _session_parent(stores)
        child = await _child(
            stores,
            parent_id=parent.id,
            child_id="owner-recovery-child",
            assigned_to=None,
        )
        session = await service.get_session(parent.id)
        assert session is not None
        plan = _build_adopted_recovery_plan(parent.id, (child,))
        await service.adopt_recovery_plan(
            parent.id,
            expected_session=session,
            expected_recovery=None,
            plan=plan,
            expected_children=(child,),
        )

        class _Resolver:
            def resolve(self, spec: Any) -> AssignmentDecision:
                return AssignmentDecision(
                    spec_id=spec.spec_id,
                    agent_id="agent-1",
                    department="engineering",
                    capability="analysis",
                    score=1.0,
                    reason="capability_match",
                )

        class _Delegator:
            def delegate(self, decision: AssignmentDecision) -> DelegationDecision:
                return DelegationDecision(
                    spec_id=decision.spec_id,
                    chief_agent_id=None,
                    worker_agent_id="agent-1",
                    order_id=None,
                    delegated=False,
                    reason="direct_no_chief",
                )

        execution_runtime = executor_runtime(stores, tmp_path)
        execution_runtime.crew_session_service = service
        executor_outcome = _StaticOutcomeExecutor(
            output="owner durable evidence",
            total_tokens=7,
        )
        executor = _crew_executor(
            stores=stores,
            registry=_Registry({"agent-1": _Agent("agent-1")}),
            executor=executor_outcome,
            runtime=execution_runtime,
            service=service,
        )
        registry = _registry_for([replace(child, assigned_to="agent-1")])
        judge = _ScriptedLLM([
            _verdict(True, critique="Child evidence is complete."),
            _verdict(True, confidence=0.98, critique="Final result is complete."),
        ])
        synth = _ScriptedLLM([_text("Owner final result", tokens=11)])
        final_runtime = finalizer_runtime(stores, tmp_path, service)
        finalizer = _make_finalizer(
            stores=stores,
            service=service,
            registry=registry,
            verifier=_make_verifier(
                llm=judge,
                stores=stores,
                registry=registry,
                executor=_StaticAgenticExecutor(),
                runtime=final_runtime,
            ),
            synthesizer=_make_synthesizer(
                llm=synth,
                stores=stores,
                runtime=final_runtime,
            ),
        )
        config = SystemConfig()
        config.agentic_dispatch.orchestrator_enabled = True
        owner = CrewOrchestrator(
            assignment_resolver=_Resolver(),
            delegator=_Delegator(),
            crew_executor=executor,
            verifier=object(),
            synthesizer=object(),
            work_item_store=stores.work,
            runtime=execution_runtime,
            config=config,
            crew_session_service=service,
            crew_session_finalizer=finalizer,
        )

        await owner.start()
        task = owner._tasks_by_parent[parent.id]
        result = await task
        await asyncio.sleep(0)

        assert result.completed is True
        assert result.final_output == "Owner final result"
        assert len(executor_outcome.calls) == 1
        assert len(judge.requests) == 2
        assert len(synth.requests) == 1
        assert len(stores.artifacts.list_versions(
            thread_id=thread.id,
            name="crew-result.md",
        )) == 1
        recovery = await service.get_recovery(parent.id)
        assert recovery is not None and recovery.phase == "published"
        assert recovery.attempt_count == 1
        await owner.stop()
    finally:
        await stores_generator.aclose()


@pytest.mark.asyncio
async def test_lifecycle_transient_retry_backoff_and_exhaustion_are_exact(
    work_store: WorkItemStore,
    tmp_path: Path,
) -> None:
    import errno
    from types import SimpleNamespace

    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.cognitive.crew_session import (
        CrewRecoveryTransientError,
        CrewSessionService,
        _build_adopted_recovery_plan,
    )
    from probos.cognitive.crew_synth import SynthesisResult
    from probos.config import SystemConfig
    from probos.threads import ChatThreadStore

    parent = await _create_crew_parent(
        work_store,
        parent_id="retry-parent",
        title="retry",
    )
    threads = ChatThreadStore(tmp_path / "retry-threads.db")
    thread = threads.create_thread(
        title="retry room",
        participants=["facilitator-1"],
        task_id=parent.id,
    )
    now = {"value": 200.0}

    def clock() -> float:
        return now["value"]

    service = CrewSessionService(
        work_item_store=work_store,
        chat_thread_store=threads,
        clock=clock,
    )
    session = await service.initialize_session(
        parent.id,
        thread.id,
        goal="retry",
        origin="captain",
        originator_id="captain",
        facilitator_id="facilitator-1",
        owner_ids=["facilitator-1"],
        success_criteria=["done"],
        expected_deliverable="result",
    )
    child = await work_store.create_work_item(
        id="retry-child",
        title="retry child",
        work_type="task",
        parent_id=parent.id,
        metadata={
            "spec_id": "retry-spec",
            "resources": [],
            "expected_output": None,
            "capability": None,
            "department": None,
        },
    )
    plan = _build_adopted_recovery_plan(parent.id, (child,))
    await service.adopt_recovery_plan(
        parent.id,
        expected_session=session,
        expected_recovery=None,
        plan=plan,
        expected_children=(child,),
    )
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)
        now["value"] += delay

    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    config.agentic_dispatch.crew_recovery_max_retries = 2
    config.agentic_dispatch.crew_recovery_initial_backoff_seconds = 2.0
    config.agentic_dispatch.crew_recovery_max_backoff_seconds = 3.0

    class _RetryOwner(CrewOrchestrator):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.attempts = 0

        async def _run_recovery_attempt(self, parent_id: str) -> SynthesisResult:
            self.attempts += 1
            if self.attempts <= 2:
                async def _session_load() -> None:
                    raise TimeoutError("retry")

                await self._await_recovery_boundary(
                    _session_load(),
                    boundary="session_load",
                )
            return SynthesisResult(parent_id, "done", True)

    owner = _RetryOwner(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=work_store,
        runtime=SimpleNamespace(),
        config=config,
        crew_session_service=service,
        clock=clock,
        sleep=sleep,
    )
    result = await owner._run_recovery_loop(parent.id)
    assert result.completed is True
    assert owner.attempts == 3
    assert sleeps == [2.0, 3.0]
    recovery = await service.get_recovery(parent.id)
    assert recovery is not None and recovery.retry_count == 2
    assert owner._as_recovery_transient(OSError(errno.ENOSPC, "full")) is None
    assert owner._as_recovery_transient(OSError(errno.EIO, "io")) is None
    assert owner._as_recovery_transient(ConnectionError("down")) is None
    wrapped = owner._translate_recovery_boundary_error(
        ConnectionError("down"),
        boundary="session_load",
    )
    assert isinstance(wrapped, CrewRecoveryTransientError)
    assert isinstance(wrapped.__cause__, ConnectionError)
    assert wrapped.code == "transient_session_load_connection"

    class _RawFailureOwner(CrewOrchestrator):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.attempts = 0
            self.contained: list[BaseException] = []

        async def _run_recovery_attempt(self, parent_id: str) -> SynthesisResult:
            self.attempts += 1
            raise TimeoutError("raw owner failure")

        async def _contain_recovery_failure(
            self,
            parent_id: str,
            exc: Exception,
        ) -> SynthesisResult:
            self.contained.append(exc)
            return SynthesisResult(parent_id, "", False)

    raw_sleeps: list[float] = []

    async def raw_sleep(delay: float) -> None:
        raw_sleeps.append(delay)

    raw_owner = _RawFailureOwner(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=work_store,
        runtime=SimpleNamespace(),
        config=config,
        sleep=raw_sleep,
    )
    raw_result = await raw_owner._run_recovery_loop("raw-parent")
    assert raw_result.completed is False
    assert raw_owner.attempts == 1
    assert len(raw_owner.contained) == 1
    assert isinstance(raw_owner.contained[0], TimeoutError)
    assert raw_sleeps == []

    class _ExhaustedOwner(_RetryOwner):
        async def _run_recovery_attempt(self, parent_id: str) -> SynthesisResult:
            self.attempts += 1
            raise CrewRecoveryTransientError("transient_timeout")

    exhausted = _ExhaustedOwner(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=work_store,
        runtime=SimpleNamespace(),
        config=config,
        crew_session_service=service,
        clock=clock,
        sleep=sleep,
    )
    exhausted_result = await exhausted._run_recovery_loop(parent.id)
    assert exhausted_result.completed is False
    blocked = await service.get_session(parent.id)
    assert blocked is not None and blocked.state == "blocked_needs_captain"
    exhausted_recovery = await service.get_recovery(parent.id)
    assert exhausted_recovery is not None
    assert exhausted_recovery.last_error_code == "recovery_retry_exhausted"


@pytest.mark.asyncio
async def test_lifecycle_decomposition_cancellation_preserves_plan_checkpoint(
    work_store: WorkItemStore,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.config import SystemConfig
    from probos.consultation.dispatch import WorkItemSpec
    from probos.threads import ChatThreadStore

    parent = await _create_crew_parent(
        work_store,
        parent_id="decompose-parent",
        title="decompose",
    )
    threads = ChatThreadStore(tmp_path / "decompose-threads.db")
    thread = threads.create_thread(
        title="decompose room",
        participants=["facilitator-1"],
        task_id=parent.id,
    )
    from probos.cognitive.crew_session import CrewSessionService

    service = CrewSessionService(
        work_item_store=work_store,
        chat_thread_store=threads,
        clock=lambda: 200.0,
    )
    await service.initialize_session(
        parent.id,
        thread.id,
        goal="decompose",
        origin="captain",
        originator_id="captain",
        facilitator_id="facilitator-1",
        owner_ids=["facilitator-1"],
        success_criteria=["done"],
        expected_deliverable="result",
    )
    release = __import__("threading").Event()
    entered = __import__("threading").Event()

    class _Decomposer:
        def decompose(self, _goal: str) -> list[WorkItemSpec]:
            entered.set()
            release.wait(timeout=2.0)
            return [WorkItemSpec(spec_id="spec-a", title="A")]

    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    owner = CrewOrchestrator(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=work_store,
        runtime=SimpleNamespace(),
        config=config,
        crew_session_service=service,
        decomposer=_Decomposer(),
    )
    await owner.start()
    task = owner._tasks_by_parent[parent.id]
    await asyncio.to_thread(entered.wait, 2.0)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    recovery = await service.get_recovery(parent.id)
    assert recovery is not None and recovery.plan is not None
    assert recovery.last_error_code == "decomposition_cancelled_after_plan_install"
    children = await work_store.list_work_items(parent_id=parent.id, limit=1001)
    assert len(children) == 1
    await owner.stop()


@pytest.mark.asyncio
async def test_lifecycle_decomposition_preserves_first_repeated_cancellation(
    work_store: WorkItemStore,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.cognitive.crew_session import CrewSessionService
    from probos.config import SystemConfig
    from probos.consultation.dispatch import WorkItemSpec
    from probos.threads import ChatThreadStore

    parent = await _create_crew_parent(
        work_store,
        parent_id="decompose-cancel-parent",
        title="decompose cancel",
    )
    threads = ChatThreadStore(tmp_path / "decompose-cancel-threads.db")
    thread = threads.create_thread(
        title="decompose cancel room",
        participants=["facilitator-1"],
        task_id=parent.id,
    )
    service = CrewSessionService(
        work_item_store=work_store,
        chat_thread_store=threads,
        clock=lambda: 200.0,
    )
    await service.initialize_session(
        parent.id,
        thread.id,
        goal="decompose with repeated cancellation",
        origin="captain",
        originator_id="captain",
        facilitator_id="facilitator-1",
        owner_ids=["facilitator-1"],
        success_criteria=["done"],
        expected_deliverable="result",
    )
    release = __import__("threading").Event()
    entered = __import__("threading").Event()

    class _Decomposer:
        def decompose(self, _goal: str) -> list[WorkItemSpec]:
            entered.set()
            release.wait(timeout=2.0)
            return [WorkItemSpec(spec_id="spec-repeat", title="Repeat")]

    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    owner = CrewOrchestrator(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=work_store,
        runtime=SimpleNamespace(),
        config=config,
        crew_session_service=service,
        decomposer=_Decomposer(),
    )
    await owner.start()
    task = owner._tasks_by_parent[parent.id]
    await asyncio.to_thread(entered.wait, 2.0)
    task.cancel("sentinel")
    await asyncio.sleep(0)
    task.cancel("second")
    release.set()

    with pytest.raises(asyncio.CancelledError) as raised:
        await task
    assert raised.value.args == ("sentinel",)
    recovery = await service.get_recovery(parent.id)
    assert recovery is not None and recovery.plan is not None
    assert recovery.last_error_code == "decomposition_cancelled_after_plan_install"
    assert len(await work_store.list_work_items(
        parent_id=parent.id,
        limit=1001,
    )) == 1
    await owner.stop()


@pytest.mark.asyncio
async def test_finalizer_checkpoint_preserves_first_repeated_cancellation() -> None:
    from probos.cognitive.crew_finalizer import CrewSessionFinalizer

    entered = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def checkpoint() -> str:
        entered.set()
        await release.wait()
        completed.set()
        return "committed"

    deferred = asyncio.create_task(CrewSessionFinalizer._defer_checkpoint(
        checkpoint(),
    ))
    await entered.wait()
    deferred.cancel("sentinel")
    await asyncio.sleep(0)
    deferred.cancel("second")
    release.set()

    with pytest.raises(asyncio.CancelledError) as raised:
        await deferred
    assert raised.value.args == ("sentinel",)
    assert completed.is_set()


@pytest.mark.asyncio
async def test_lifecycle_legacy_verification_without_sidecar_blocks_no_rerun(
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_orchestrator import CrewOrchestrator
    from probos.cognitive.crew_session import _build_adopted_recovery_plan
    from probos.config import SystemConfig
    from tests.test_ad1125_room_bound_execution import (
        _child,
        _runtime as executor_runtime,
        _session_parent,
        stores as stores_fixture,
    )

    stores_generator = stores_fixture.__wrapped__(tmp_path)
    stores = await stores_generator.__anext__()
    try:
        parent, _thread, service = await _session_parent(stores)
        child = await _child(
            stores,
            parent_id=parent.id,
            child_id="legacy-verification-child",
            status="done",
        )
        metadata = dict(child.metadata)
        metadata["crew_execution"] = {
            "version": 1,
            "parent_id": parent.id,
            "work_item_id": child.id,
            "thread_id": (await service.get_session(parent.id)).thread_id,
            "assigned_to": child.assigned_to,
            "status": "done",
            "stopped_reason": "complete",
            "output_summary": "legacy",
            "tool_trace_ref": None,
            "artifact_refs": [],
            "tokens_used": 0,
            "started_at": 300.0,
            "finished_at": 301.0,
            "blocked_dependency_ids": [],
        }
        blob = b"legacy"
        import hashlib

        content_hash = hashlib.sha256(blob).hexdigest()
        await stores.attachments.write(
            content_hash,
            blob,
            "text/plain",
            origin="agent_artifact",
        )
        metadata["crew_execution_output"] = {
            "version": 1,
            "content_hash": content_hash,
            "mime": "text/plain",
            "size_bytes": len(blob),
        }
        await stores.work.update_work_item(
            child.id,
            metadata=metadata,
            verification={"legacy": True},
        )
        session = await service.get_session(parent.id)
        assert session is not None
        executing = await service.transition_session(
            parent.id,
            "executing",
            expected_revision=session.revision,
        )
        verifying_session = await service.transition_session(
            parent.id,
            "verifying",
            expected_revision=executing.revision,
        )

        config = SystemConfig()
        config.agentic_dispatch.orchestrator_enabled = True
        owner = CrewOrchestrator(
            assignment_resolver=object(),
            delegator=object(),
            crew_executor=object(),
            verifier=object(),
            synthesizer=object(),
            work_item_store=stores.work,
            runtime=executor_runtime(stores, tmp_path),
            config=config,
            crew_session_service=service,
            crew_session_finalizer=object(),
        )
        result = await owner._run_recovery_attempt(parent.id)
        assert result.completed is False
        blocked = await service.get_session(parent.id)
        assert blocked is not None and blocked.state == "blocked_needs_captain"
        assert blocked.blocked_reason == "legacy_verification_nonreconstructable"
        assert await service.get_recovery(parent.id) is None
        assert verifying_session.state == "verifying"
    finally:
        await stores_generator.aclose()
