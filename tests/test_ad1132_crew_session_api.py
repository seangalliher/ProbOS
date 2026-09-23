"""AD-1132: bounded CrewSession projections on existing HXI APIs."""

from __future__ import annotations

import asyncio
import inspect
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastapi import FastAPI

from probos.api import create_app
from probos.cognitive.crew_session import (
    CrewSessionContract,
    CrewSynthesisMetadata,
    _build_derived_recovery_plan,
)
from probos.config import SystemConfig
from probos.crew_session_delivery import (
    CrewSessionDeliveryOutboxEntry,
    build_crew_session_delivery_record,
)
from probos.crew_session_live import (
    load_crew_session_projection,
    load_fenced_crew_children,
    observe_crew_children,
)
from probos.crew_session_projection import (
    CREW_SESSION_PROJECTION_ERROR,
    CrewSessionProjectionError,
    build_crew_session_detail,
    build_crew_session_summary,
)
from probos.routers import crew_tasks as crew_tasks_router
from probos.notification_context import NotificationContextError, NotificationContextResolver
from probos.routers import threads as threads_router
from probos.routers.deps import get_runtime
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.threads import ChatThreadStore
from probos.work_item_steps import (
    OwnedCrewChildren,
    OwnedStepsError,
    OwnedStepsSeedPlan,
)
from probos.workforce import CrewSessionParentCreate, WorkItem, WorkItemStore

if TYPE_CHECKING:
    from ui.e2e.fixtures.ad1192_backend import FixtureState


_SHA_A = "a" * 64
_SHA_B = "b" * 64
_DETAIL_KEYS = {
    "task_id", "thread_id", "goal", "origin", "originator_id",
    "facilitator_id", "owner_ids", "state", "revision",
    "success_criteria", "expected_deliverable", "timestamps", "progress",
    "last_result_summary", "blocker", "result", "verification",
    "duplicate_resume_count",
}
_SUMMARY_KEYS = {
    "task_id", "thread_id", "goal", "state", "facilitator_id",
    "owner_ids", "progress", "last_result_summary", "blocker",
    "needs_attention", "result_artifact_id", "verified_at",
}
_STATE_STATUS = {
    "discussing": "open",
    "executing": "in_progress",
    "verifying": "review",
    "blocked_needs_captain": "blocked",
    "done": "done",
    "failed": "failed",
}


class _ProjectionService:
    def __init__(self) -> None:
        self.sessions: dict[str, CrewSessionContract | ValueError | None] = {}
        self.open_result: Any = None
        self.open_calls = 0
        self.get_calls: list[str] = []

    def captain_principal(self) -> str:
        return "captain-principal"

    async def open_or_resume(self, **_kwargs: Any) -> Any:
        self.open_calls += 1
        if self.open_result is None:
            raise AssertionError("open_or_resume result was not configured")
        return self.open_result

    async def get_session(self, parent_id: str) -> CrewSessionContract | None:
        self.get_calls.append(parent_id)
        value = self.sessions.get(parent_id)
        if isinstance(value, ValueError):
            raise value
        return value


class _Harness:
    def __init__(
        self,
        *,
        work: WorkItemStore,
        threads: ChatThreadStore,
        service: _ProjectionService,
        runtime: Any,
        app: FastAPI,
    ) -> None:
        self.work = work
        self.threads = threads
        self.service = service
        self.runtime = runtime
        self.app = app
        self.admission = work.claim_crew_session_admission_port()

    @asynccontextmanager
    async def client(self) -> Any:
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield client


@pytest.fixture
async def api_harness(tmp_path: Path) -> Any:
    work = WorkItemStore(
        db_path=str(tmp_path / "ad1132-work.db"),
        connection_factory=SQLiteConnectionFactory(),
        tick_interval=1_000,
    )
    await work.start()
    threads = ChatThreadStore(tmp_path / "ad1132-threads.db")
    service = _ProjectionService()
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    runtime = SimpleNamespace(
        work_item_store=work,
        chat_thread_store=threads,
        crew_session_service=service,
        artifact_store=None,
        attachment_store=None,
        config=config,
    )
    app = FastAPI()
    app.include_router(crew_tasks_router.router)
    app.include_router(threads_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    harness = _Harness(
        work=work,
        threads=threads,
        service=service,
        runtime=runtime,
        app=app,
    )
    try:
        yield harness
    finally:
        await work.stop()


def _session(
    *,
    task_id: str,
    thread_id: str,
    state: str = "discussing",
    goal: str = "Prepare the verified navigation report",
) -> CrewSessionContract:
    created = 100.0
    transitioned = 140.0 if state != "discussing" else created
    started = 110.0 if state in {"executing", "verifying", "done"} else None
    first_result = 120.0 if state in {"verifying", "done"} else None
    done = state == "done"
    failed = state == "failed"
    blocked = state == "blocked_needs_captain"
    return CrewSessionContract.model_validate({
        "version": 1,
        "state": state,
        "previous_state": None,
        "revision": 3,
        "goal": goal,
        "origin": "captain",
        "originator_id": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1", "owner-2"],
        "success_criteria": ["Report is complete", "Evidence is linked"],
        "expected_deliverable": "A verified report artifact",
        "thread_id": thread_id,
        "task_id": task_id,
        "created_at": created,
        "transitioned_at": transitioned,
        "started_at": started,
        "first_result_at": first_result,
        "verified_at": transitioned if done else None,
        "completed_at": transitioned if done or failed else None,
        "last_result_summary": "Draft result ready" if first_result else "",
        "blocked_reason": "Captain must approve the source" if blocked else None,
        "blocked_since": transitioned if blocked else None,
        "blocked_duration_seconds": 95.0 if blocked else 0.0,
        "evidence_refs": [_SHA_A] if done else [],
        "result_artifact_id": "artifact-final" if done else None,
        "result_ref": _SHA_A if done else None,
        "duplicate_resume_count": 2,
    })


def _synthesis(
    *,
    artifact_id: str = "artifact-final",
    provenance_ref: str = _SHA_A,
) -> CrewSynthesisMetadata:
    return CrewSynthesisMetadata.model_validate({
        "version": 1,
        "completed": True,
        "producer_agent_id": "producer-1",
        "final_verifier_agent_id": "verifier-1",
        "final_confidence": 0.93,
        "final_critique": "All criteria are satisfied.",
        "accepted_count": 2,
        "total_count": 2,
        "convergence_rounds": 2,
        "correction_tokens": 10,
        "verification_tokens": 20,
        "synthesis_tokens": 30,
        "result_artifact_id": artifact_id,
        "result_content_hash": _SHA_B,
        "provenance_ref": provenance_ref,
    })


async def _crew_parent(
    harness: _Harness,
    *,
    parent_id: str,
    state: str = "discussing",
    thread_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    goal: str = "Prepare the verified navigation report",
) -> tuple[WorkItem, CrewSessionContract]:
    async with harness.admission.reserve() as reservation:
        parent = await reservation.create_parent(CrewSessionParentCreate(
            id=parent_id,
            title="Crew session",
            description="Crew session",
            assigned_to="facilitator-1",
            created_by="captain",
            metadata=dict(metadata or {}),
            created_at=100.0,
        ))
    room_id = thread_id or f"room-{parent_id}"
    contract = _session(
        task_id=parent.id,
        thread_id=room_id,
        state=state,
        goal=goal,
    )
    harness.service.sessions[parent.id] = contract
    return parent, contract


@pytest.mark.parametrize(
    ("change", "expected_status"),
    [
        ("unchanged", 200), ("completed", 200), ("blocked", 200),
        ("newer", 200), ("older", 409), ("outcome", 409),
        ("origin", 409), ("originator", 409), ("session_thread", 409),
        ("thread_task", 409), ("archived", 410), ("deleted", 404),
        ("archive_during_load", 410), ("delete_during_load", 404),
        ("rebind_during_load", 409), ("missing_projection", 404),
    ],
)
async def test_notification_context_current_correlation(
    api_harness: _Harness, change: str, expected_status: int,
) -> None:
    thread = api_harness.threads.create_thread(
        title="Current room", participants=["facilitator-1"], task_id="context-parent",
    )
    state = {"completed": "done", "blocked": "blocked_needs_captain"}.get(change, "failed")
    parent, session = await _crew_parent(
        api_harness, parent_id="context-parent", state=state, thread_id=thread.id,
        metadata={"crew_synth": _synthesis().model_dump(mode="json")} if state == "done" else None,
    )
    record = build_crew_session_delivery_record(session)
    assert record.outcome == state
    assert record.session_revision == session.revision == 3

    class _DeliveryReader:
        async def get_crew_session_delivery(
            self, delivery_id: str,
        ) -> CrewSessionDeliveryOutboxEntry | None:
            assert delivery_id == record.delivery_id
            return CrewSessionDeliveryOutboxEntry(
                record=record, delivered=True, created_at=140.0, delivered_at=141.0,
            )

    updates: dict[str, Any] = {
        "newer": {"revision": 4}, "older": {"revision": 2},
        "outcome": {"state": "discussing", "completed_at": None},
        "origin": {"origin": "agent", "originator_id": "facilitator-1"},
        "originator": {"originator_id": "other-agent"},
        "session_thread": {"thread_id": "other-room"},
    }.get(change, {})
    api_harness.service.sessions[parent.id] = session.model_copy(update=updates)
    if change == "thread_task":
        api_harness.threads.update_thread(thread.id, task_id="other-parent")
    elif change == "archived":
        api_harness.threads.update_thread(thread.id, archived=True)
    elif change == "deleted":
        api_harness.threads.delete_thread(thread.id)

    async def load_current(parent_id: str) -> Any:
        if change == "missing_projection":
            return None
        loaded = await load_crew_session_projection(
            parent_id, crew_session_service=api_harness.service,
            work_item_store=api_harness.work,
        )
        if change == "archive_during_load":
            api_harness.threads.update_thread(thread.id, archived=True)
        elif change == "delete_during_load":
            api_harness.threads.delete_thread(thread.id)
        elif change == "rebind_during_load":
            api_harness.threads.update_thread(thread.id, task_id="other-parent")
        return loaded

    resolver = NotificationContextResolver(
        delivery_store=_DeliveryReader(), thread_store=api_harness.threads,
        load_projection=load_current,
    )
    if expected_status != 200:
        with pytest.raises(NotificationContextError) as caught:
            await resolver.resolve(record.delivery_id)
        assert caught.value.status_code == expected_status
    else:
        result = await resolver.resolve(record.delivery_id)
        assert set(result) == {"kind", "notification_id", "delivery_revision", "thread", "session"}
        assert result["thread"] == thread.to_dict()
        assert set(result["session"]) == _DETAIL_KEYS
        assert result["session"]["revision"] == (4 if change == "newer" else 3)
        assert result["session"]["state"] == state
        assert result["delivery_revision"] == 3
        if state == "done":
            assert result["session"]["result"] == {
                "artifact_id": "artifact-final", "content_hash": _SHA_B,
                "result_ref": _SHA_A, "evidence_refs": [_SHA_A],
            }
            assert result["session"]["verification"] == {
                "verifier_agent_id": "verifier-1", "confidence": 0.93,
                "critique": "All criteria are satisfied.", "accepted_count": 2,
                "total_count": 2, "convergence_rounds": 2,
            }
    assert api_harness.service.open_calls == 0


class _NotificationIdSubclass(str):
    pass


@pytest.mark.parametrize(
    "notification_id", [None, 1, "", "A" * 64, "a" * 65, _NotificationIdSubclass(_SHA_A)],
)
async def test_notification_context_invalid_id_precedes_dependency_reads(
    notification_id: Any,
) -> None:
    resolver = NotificationContextResolver(
        delivery_store=None, thread_store=None, load_projection=None,
    )
    with pytest.raises(NotificationContextError) as caught:
        await resolver.resolve(notification_id)
    assert caught.value.status_code == 422


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        ("unknown", 404), ("invalid_entry", 409), ("invalid_record", 409),
        ("entry_subclass", 409), ("record_subclass", 409),
        ("wrong_identity", 409), ("corrupt", 409), ("storage", 503),
        ("thread", 503), ("projection", 503),
        ("missing_store", 503), ("missing_threads", 503), ("missing_loader", 503),
    ],
)
async def test_notification_context_dependency_failures_are_closed(
    failure: str, expected_status: int,
) -> None:
    session = _session(task_id="context-parent", thread_id="context-room", state="failed")
    record = build_crew_session_delivery_record(session)
    calls: list[str] = []

    class _EntrySubclass(CrewSessionDeliveryOutboxEntry):
        pass

    class _RecordSubclass(type(record)):
        pass

    class _DeliveryReader:
        async def get_crew_session_delivery(
            self, delivery_id: str,
        ) -> CrewSessionDeliveryOutboxEntry | None:
            calls.append("delivery")
            assert delivery_id == record.delivery_id
            if failure == "unknown":
                return None
            if failure == "invalid_entry":
                return SimpleNamespace(record=record)
            if failure == "corrupt":
                raise ValueError("crew_delivery_outbox_corrupt")
            if failure == "storage":
                raise OSError("storage unavailable")
            candidate = record
            if failure == "invalid_record":
                candidate = SimpleNamespace(**record.to_payload())
            elif failure == "record_subclass":
                candidate = _RecordSubclass(**record.to_payload())
            elif failure == "wrong_identity":
                candidate = build_crew_session_delivery_record(
                    session.model_copy(update={"revision": 4}),
                )
            entry_type = _EntrySubclass if failure == "entry_subclass" else CrewSessionDeliveryOutboxEntry
            return entry_type(
                record=candidate, delivered=True, created_at=140.0, delivered_at=141.0,
            )

    class _ThreadReader:
        def get_thread(self, thread_id: str) -> Any:
            from probos.threads import ChatThread

            calls.append("thread")
            assert thread_id == "context-room"
            if failure == "thread":
                raise OSError("threads unavailable")
            return ChatThread(
                id=thread_id, title="Current room", participants=["facilitator-1"],
                task_id="context-parent", created_at=100.0, last_active_at=140.0,
            )

    async def load_current(parent_id: str) -> Any:
        calls.append("projection")
        assert parent_id == "context-parent"
        raise OSError("projection unavailable")

    resolver = NotificationContextResolver(
        delivery_store=None if failure == "missing_store" else _DeliveryReader(),
        thread_store=None if failure == "missing_threads" else _ThreadReader(),
        load_projection=None if failure == "missing_loader" else load_current,
    )
    with pytest.raises(NotificationContextError) as caught:
        await resolver.resolve(record.delivery_id)
    assert caught.value.status_code == expected_status
    if failure.startswith("missing_"):
        assert calls == []
    elif failure == "projection":
        assert calls == ["delivery", "thread", "projection"]
    elif failure == "thread":
        assert calls == ["delivery", "thread"]
    else:
        assert calls == ["delivery"]


@pytest.mark.parametrize(
    "state",
    [
        "discussing",
        "executing",
        "verifying",
        "blocked_needs_captain",
        "done",
        "failed",
    ],
)
async def test_get_crew_task_each_session_state_returns_exact_projection(
    api_harness: _Harness,
    state: str,
) -> None:
    metadata = {
        "crew_synth": _synthesis().model_dump(mode="json"),
    } if state == "done" else {}
    parent, _ = await _crew_parent(
        api_harness,
        parent_id=f"parent-{state}",
        state=state,
        metadata=metadata,
    )

    async with api_harness.client() as client:
        response = await client.get(f"/api/crew-tasks/{parent.id}")

    assert response.status_code == 200
    assert set(response.json()) == {"session"}
    detail = response.json()["session"]
    assert set(detail) == _DETAIL_KEYS
    assert detail["state"] == state
    assert detail["task_id"] == parent.id
    assert (detail["result"] is not None) is (state == "done")
    assert (detail["verification"] is not None) is (state == "done")
    assert (detail["blocker"] is not None) is (state == "blocked_needs_captain")


async def test_get_crew_task_direct_children_counts_and_selects_active_deterministically(
    api_harness: _Harness,
) -> None:
    parent, _ = await _crew_parent(api_harness, parent_id="parent-progress")
    done = await api_harness.work.create_work_item(
        id="child-done", title="Done", parent_id=parent.id, status="done",
    )
    await api_harness.work.create_work_item(
        id="grandchild", title="Nested", parent_id=done.id, status="in_progress",
    )
    await api_harness.work.create_work_item(
        id="child-failed", title="Failed", parent_id=parent.id, status="failed",
    )
    await api_harness.work.create_work_item(
        id="child-cancelled", title="Cancelled", parent_id=parent.id, status="cancelled",
    )
    await api_harness.work.create_work_item(
        id="child-review", title="Review", parent_id=parent.id, status="review",
        priority=1, created_at=90.0,
    )
    await api_harness.work.create_work_item(
        id="child-active-z", title="Later", parent_id=parent.id, status="in_progress",
        priority=2, created_at=80.0,
    )
    await api_harness.work.create_work_item(
        id="child-active-a", title="Selected", parent_id=parent.id, status="in_progress",
        priority=2, created_at=70.0,
    )

    async with api_harness.client() as client:
        detail = (await client.get(f"/api/crew-tasks/{parent.id}")).json()["session"]

    assert detail["progress"] == {
        "total": 6,
        "done": 1,
        "failed": 2,
        "active": 3,
        "active_child": {
            "id": "child-active-a",
            "title": "Selected",
            "status": "in_progress",
            "owner_id": None,
        },
    }


async def test_get_crew_task_blocked_returns_persisted_blocker_and_fixed_action(
    api_harness: _Harness,
) -> None:
    parent, contract = await _crew_parent(
        api_harness,
        parent_id="parent-blocked",
        state="blocked_needs_captain",
    )

    async with api_harness.client() as client:
        detail = (await client.get(f"/api/crew-tasks/{parent.id}")).json()["session"]

    assert detail["blocker"] == {
        "reason": contract.blocked_reason,
        "since": contract.blocked_since,
        "duration_seconds": contract.blocked_duration_seconds,
        "action": "retry_start_work",
    }


async def test_get_crew_task_done_returns_cross_checked_result_and_verification(
    api_harness: _Harness,
) -> None:
    synthesis = _synthesis()
    parent, _ = await _crew_parent(
        api_harness,
        parent_id="parent-done",
        state="done",
        metadata={"crew_synth": synthesis.model_dump(mode="json")},
    )

    async with api_harness.client() as client:
        detail = (await client.get(f"/api/crew-tasks/{parent.id}")).json()["session"]

    assert detail["result"] == {
        "artifact_id": "artifact-final",
        "content_hash": _SHA_B,
        "result_ref": _SHA_A,
        "evidence_refs": [_SHA_A],
    }
    assert detail["verification"] == {
        "verifier_agent_id": "verifier-1",
        "confidence": 0.93,
        "critique": "All criteria are satisfied.",
        "accepted_count": 2,
        "total_count": 2,
        "convergence_rounds": 2,
    }


@pytest.mark.parametrize("case", ["missing", "malformed", "mismatched"])
async def test_get_crew_task_terminal_invalid_synthesis_returns_stable_409(
    api_harness: _Harness,
    case: str,
) -> None:
    if case == "missing":
        metadata: dict[str, Any] = {}
    elif case == "malformed":
        metadata = {"crew_synth": {"secret": "raw-value"}}
    else:
        metadata = {
            "crew_synth": _synthesis(artifact_id="artifact-other").model_dump(mode="json"),
        }
    parent, _ = await _crew_parent(
        api_harness,
        parent_id=f"parent-terminal-{case}",
        state="done",
        metadata=metadata,
    )

    async with api_harness.client() as client:
        response = await client.get(f"/api/crew-tasks/{parent.id}")

    assert response.status_code == 409
    assert response.json() == {"detail": CREW_SESSION_PROJECTION_ERROR}
    assert "raw-value" not in response.text


async def test_get_crew_task_synthesis_provenance_mismatch_returns_stable_409(
    api_harness: _Harness,
) -> None:
    synthesis = _synthesis(provenance_ref=_SHA_B)
    parent, contract = await _crew_parent(
        api_harness,
        parent_id="parent-provenance-mismatch",
        state="done",
        metadata={"crew_synth": synthesis.model_dump(mode="json")},
    )
    contract = contract.model_copy(
        update={"evidence_refs": (_SHA_A, _SHA_B)},
    )
    api_harness.service.sessions[parent.id] = contract

    assert contract.result_ref == _SHA_A
    assert synthesis.provenance_ref == _SHA_B
    assert contract.evidence_refs == (_SHA_A, _SHA_B)

    async with api_harness.client() as client:
        response = await client.get(f"/api/crew-tasks/{parent.id}")

    assert response.status_code == 409
    assert response.json() == {"detail": CREW_SESSION_PROJECTION_ERROR}


async def test_get_crew_task_result_ref_missing_from_evidence_returns_stable_409(
    api_harness: _Harness,
) -> None:
    parent, contract = await _crew_parent(
        api_harness,
        parent_id="parent-evidence-membership",
        state="done",
        metadata={"crew_synth": _synthesis().model_dump(mode="json")},
    )
    api_harness.service.sessions[parent.id] = contract.model_copy(
        update={"evidence_refs": (_SHA_B,)},
    )

    async with api_harness.client() as client:
        response = await client.get(f"/api/crew-tasks/{parent.id}")

    assert response.status_code == 409
    assert response.json() == {"detail": CREW_SESSION_PROJECTION_ERROR}


@pytest.mark.parametrize(
    "error_code",
    [
        "crew_session_contract_invalid",
        "crew_session_status_projection_conflict",
        "crew_session_thread_binding_conflict",
    ],
)
async def test_get_crew_task_service_authority_conflict_returns_stable_409(
    api_harness: _Harness,
    error_code: str,
) -> None:
    parent, _ = await _crew_parent(
        api_harness,
        parent_id=f"parent-conflict-{error_code[-8:]}",
    )
    api_harness.service.sessions[parent.id] = ValueError(error_code)

    async with api_harness.client() as client:
        response = await client.get(f"/api/crew-tasks/{parent.id}")

    assert response.status_code == 409
    assert response.json() == {"detail": CREW_SESSION_PROJECTION_ERROR}
    assert error_code not in response.text


async def test_get_crew_task_malformed_child_status_returns_stable_409(
    api_harness: _Harness,
) -> None:
    parent, _ = await _crew_parent(api_harness, parent_id="parent-bad-child")
    child = await api_harness.work.create_work_item(
        id="child-bad", title="Child", parent_id=parent.id,
    )
    assert api_harness.work._db is not None
    await api_harness.work._db.execute(
        "UPDATE work_items SET status = ? WHERE id = ?",
        ("unknown_status", child.id),
    )
    await api_harness.work._db.commit()

    async with api_harness.client() as client:
        response = await client.get(f"/api/crew-tasks/{parent.id}")

    assert response.status_code == 409
    assert response.json() == {"detail": CREW_SESSION_PROJECTION_ERROR}


async def test_get_crew_task_child_overflow_returns_stable_409(
    api_harness: _Harness,
) -> None:
    parent, contract = await _crew_parent(api_harness, parent_id="parent-overflow")

    class _OverflowStore:
        async def get_owned_crew_children(
            self,
            parent_id: str,
            expected_plan: OwnedStepsSeedPlan | str | None = None,
        ) -> OwnedCrewChildren:
            assert parent_id == parent.id
            assert expected_plan is None
            raise OwnedStepsError("owned_steps_not_managed", parent_id=parent_id)

        async def get_work_item(self, work_item_id: str) -> WorkItem | None:
            return parent if work_item_id == parent.id else None

        async def list_work_items(self, **kwargs: Any) -> list[WorkItem]:
            assert kwargs == {"parent_id": parent.id, "limit": 1001}
            return [
                WorkItem(
                    id=f"overflow-{index}",
                    title="Overflow",
                    parent_id=parent.id,
                )
                for index in range(1001)
            ]

    api_harness.runtime.work_item_store = _OverflowStore()
    api_harness.service.sessions[parent.id] = contract
    try:
        async with api_harness.client() as client:
            response = await client.get(f"/api/crew-tasks/{parent.id}")
    finally:
        api_harness.runtime.work_item_store = api_harness.work

    assert response.status_code == 409
    assert response.json() == {"detail": CREW_SESSION_PROJECTION_ERROR}


async def test_get_crew_task_preserves_missing_and_unavailable_statuses(
    api_harness: _Harness,
) -> None:
    async with api_harness.client() as client:
        missing = await client.get("/api/crew-tasks/missing")
        api_harness.runtime.work_item_store = None
        unavailable = await client.get("/api/crew-tasks/missing")
    api_harness.runtime.work_item_store = api_harness.work
    parent, _ = await _crew_parent(api_harness, parent_id="parent-no-service")
    api_harness.runtime.crew_session_service = None
    try:
        async with api_harness.client() as client:
            no_service = await client.get(f"/api/crew-tasks/{parent.id}")
    finally:
        api_harness.runtime.crew_session_service = api_harness.service

    assert missing.status_code == 404
    assert unavailable.status_code == 503
    assert no_service.status_code == 503


async def test_get_crew_task_non_session_preserves_exact_ad862_shape_and_values(
    api_harness: _Harness,
) -> None:
    parent = await api_harness.work.create_work_item(
        id="legacy-parent", title="Legacy parent", work_type="task",
    )
    child = await api_harness.work.create_work_item(
        id="legacy-child", title="Legacy child", parent_id=parent.id,
        status="in_progress",
    )

    async with api_harness.client() as client:
        response = await client.get(f"/api/crew-tasks/{parent.id}")

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"parent", "children", "count"}
    assert body["parent"] == parent.to_dict()
    assert body["count"] == 1
    assert body["children"][0] == {
        **child.to_dict(),
        "verdict": None,
        "rounds": None,
    }


async def test_thread_summary_generic_member_has_exact_four_keys(
    api_harness: _Harness,
) -> None:
    parent = await api_harness.work.create_work_item(
        id="summary-generic", title="Generic topic", work_type="task",
    )
    thread = api_harness.threads.create_thread(
        title="Generic room", participants=["agent-1", "agent-2"], task_id=parent.id,
    )

    async with api_harness.client() as client:
        response = await client.get("/api/threads/summaries")

    summary = response.json()["summaries"][thread.id]
    assert summary == {
        "outputs": 0,
        "steps_total": 0,
        "steps_done": 0,
        "topic": "Generic topic",
    }
    assert set(summary) == {"outputs", "steps_total", "steps_done", "topic"}


async def test_thread_summary_valid_session_uses_goal_and_exact_compact_keys(
    api_harness: _Harness,
) -> None:
    thread = api_harness.threads.create_thread(
        title="Session room", participants=["facilitator-1", "owner-2"],
    )
    parent, _ = await _crew_parent(
        api_harness,
        parent_id="summary-session",
        thread_id=thread.id,
        state="blocked_needs_captain",
        goal="Actual validated session goal",
    )
    api_harness.threads.update_thread(thread.id, task_id=parent.id)

    async with api_harness.client() as client:
        response = await client.get("/api/threads/summaries")

    summary = response.json()["summaries"][thread.id]
    assert set(summary) == {
        "outputs", "steps_total", "steps_done", "topic", "session",
    }
    assert summary["topic"] == "Actual validated session goal"
    assert set(summary["session"]) == _SUMMARY_KEYS
    assert summary["session"]["needs_attention"] is True
    assert set(summary["session"]["progress"]) == {"total", "done", "failed", "active"}


async def test_thread_summary_invalid_session_isolated_from_valid_and_generic_siblings(
    api_harness: _Harness,
) -> None:
    generic = await api_harness.work.create_work_item(
        id="mixed-generic", title="Generic sibling",
    )
    generic_thread = api_harness.threads.create_thread(
        title="Generic", participants=["agent-1", "agent-2"], task_id=generic.id,
    )
    valid_thread = api_harness.threads.create_thread(
        title="Valid", participants=["facilitator-1", "owner-2"],
    )
    valid_parent, _ = await _crew_parent(
        api_harness,
        parent_id="mixed-valid",
        thread_id=valid_thread.id,
        goal="Valid session goal",
    )
    api_harness.threads.update_thread(valid_thread.id, task_id=valid_parent.id)
    invalid_thread = api_harness.threads.create_thread(
        title="Invalid", participants=["facilitator-1", "owner-2"],
    )
    invalid_parent, _ = await _crew_parent(
        api_harness,
        parent_id="mixed-invalid",
        thread_id=invalid_thread.id,
    )
    api_harness.threads.update_thread(invalid_thread.id, task_id=invalid_parent.id)
    api_harness.service.sessions[invalid_parent.id] = ValueError("raw-secret-conflict")

    async with api_harness.client() as client:
        response = await client.get("/api/threads/summaries")

    summaries = response.json()["summaries"]
    assert set(summaries[generic_thread.id]) == {
        "outputs", "steps_total", "steps_done", "topic",
    }
    assert set(summaries[invalid_thread.id]) == {
        "outputs", "steps_total", "steps_done", "topic",
    }
    assert set(summaries[valid_thread.id]) == {
        "outputs", "steps_total", "steps_done", "topic", "session",
    }
    assert summaries[valid_thread.id]["session"]["goal"] == "Valid session goal"
    assert "raw-secret-conflict" not in response.text


async def test_start_work_returns_matching_projection_without_second_mutation(
    api_harness: _Harness,
) -> None:
    thread = api_harness.threads.create_thread(
        title="Start Work room", participants=["facilitator-1", "owner-2"],
    )
    parent, contract = await _crew_parent(
        api_harness,
        parent_id="start-work-parent",
        thread_id=thread.id,
    )
    api_harness.threads.update_thread(thread.id, task_id=parent.id)
    api_harness.service.open_result = SimpleNamespace(
        disposition="created",
        parent_id=parent.id,
        thread_id=thread.id,
        state=contract.state,
        facilitator_id=contract.facilitator_id,
        owner_ids=contract.owner_ids,
        duplicate_resume_count=contract.duplicate_resume_count,
        scheduled=True,
    )

    async with api_harness.client() as client:
        response = await client.post(
            f"/api/threads/{thread.id}/start-work",
            json={
                "goal": contract.goal,
                "success_criteria": list(contract.success_criteria),
                "expected_deliverable": contract.expected_deliverable,
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert api_harness.service.open_calls == 1
    assert api_harness.service.get_calls.count(parent.id) == 1
    assert body["parent_id"] == body["session"]["task_id"] == parent.id
    assert body["thread_id"] == body["session"]["thread_id"] == thread.id
    assert body["state"] == body["session"]["state"]


async def test_start_work_post_admission_projection_conflict_returns_stable_409_once(
    api_harness: _Harness,
) -> None:
    thread = api_harness.threads.create_thread(
        title="Conflicting Start Work room",
        participants=["facilitator-1", "owner-2"],
    )
    parent, contract = await _crew_parent(
        api_harness,
        parent_id="start-work-conflict-parent",
        thread_id=thread.id,
        state="executing",
    )
    api_harness.threads.update_thread(thread.id, task_id=parent.id)
    api_harness.service.open_result = SimpleNamespace(
        disposition="resumed",
        parent_id=parent.id,
        thread_id=thread.id,
        state="discussing",
        facilitator_id=contract.facilitator_id,
        owner_ids=contract.owner_ids,
        duplicate_resume_count=contract.duplicate_resume_count,
        scheduled=True,
    )

    async with api_harness.client() as client:
        response = await client.post(
            f"/api/threads/{thread.id}/start-work",
            json={
                "goal": contract.goal,
                "success_criteria": list(contract.success_criteria),
                "expected_deliverable": contract.expected_deliverable,
            },
        )

    assert response.status_code == 409
    assert response.json() == {"detail": CREW_SESSION_PROJECTION_ERROR}
    assert api_harness.service.open_calls == 1
    assert api_harness.service.get_calls.count(parent.id) == 1


def _walk(value: object) -> Any:
    yield value
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_projection_recursive_forbidden_field_scan() -> None:
    session = _session(task_id="privacy-parent", thread_id="privacy-room", state="done")
    detail = build_crew_session_detail(
        session=session,
        synthesis=_synthesis(),
        children=[
            WorkItem(
                id="privacy-child",
                title="Bounded child",
                parent_id=session.task_id,
                metadata={"password": "must-not-cross"},
                actual_tokens=999,
            ),
        ],
    )
    wires = [detail.to_wire(), build_crew_session_summary(detail).to_wire()]
    forbidden = {
        "metadata", "description", "dependencies", "depends_on", "tags",
        "capabilities", "required_capabilities", "steps", "schedule",
        "password", "secret", "token", "correction_tokens",
        "verification_tokens", "synthesis_tokens", "producer_agent_id",
        "delivery_id", "outbox", "notification", "metrics", "event_payload",
        "trust_receipt", "attachment_bytes",
    }

    for wire in wires:
        assert not forbidden.intersection(
            item for item in _walk(wire) if isinstance(item, str)
        )


@dataclass
class _OwnedProjectionCase:
    state: FixtureState
    client: httpx.AsyncClient

    async def apply(
        self, parent_id: str, kind: str, identity: str,
    ) -> dict[str, Any]:
        base = f"/api/work-items/{parent_id}/owned-steps"
        observed = await self.client.get(base)
        assert observed.status_code == 200, observed.text
        preview = await self.client.post(
            f"{base}/preview",
            json={
                "version": 1,
                "kind": kind,
                "preparation_id": f"{identity}-prepare",
                "reference": observed.json()["reference"],
            },
        )
        assert preview.status_code == 200, preview.text
        proposal = preview.json()["proposal"]
        response = await self.client.post(
            f"{base}/{'adopt' if kind == 'adopt_existing' else 'commands'}",
            json={
                "version": 1,
                "operation_id": f"{identity}-apply",
                "reference": proposal["reference"],
            },
        )
        assert response.status_code == 200, response.text
        return proposal

    async def managed_parent(self, *, canonical: bool) -> str:
        if canonical:
            setup = await self.state.create_canonical()
            await self.apply(setup["parent_id"], "adopt_existing", "projection-adopt")
        else:
            setup = await self.state.create_replan()
        return setup["parent_id"]

    async def unmanaged_parent(
        self, *, canonical: bool, child_count: int = 0,
    ) -> str:
        parent_id = self.state.identity("preinstall")
        if canonical:
            async with self.state.admission_port.reserve() as reservation:
                parent = await reservation.create_parent(CrewSessionParentCreate(
                    id=parent_id,
                    title="Pre-install session projection",
                    description="Current children before owner-plan installation",
                    assigned_to="facilitator-a",
                    created_by="captain",
                    metadata={},
                ))
            thread = self.state.threads.create_thread(
                title="Pre-install room",
                participants=["facilitator-a", "worker-a"],
                task_id=parent.id,
            )
            await self.state.service.initialize_session(
                parent.id,
                thread.id,
                goal="Pre-install current work",
                origin="captain",
                originator_id="captain",
                facilitator_id="facilitator-a",
                owner_ids=["facilitator-a", "worker-a"],
                success_criteria=["Current children are displayed"],
                expected_deliverable="A current projection",
            )
        else:
            parent = await self.state.store.create_work_item(
                id=parent_id,
                title="Unmanaged legacy projection",
                assigned_to="worker-a",
            )
        for index in range(child_count):
            await self.state.store.create_work_item(
                id=f"{parent.id}-child-{index}",
                title=f"Pre-install child {index}",
                parent_id=parent.id,
                assigned_to="worker-a",
                priority=3 - index,
            )
        with pytest.raises(OwnedStepsError) as error:
            await self.state.store.get_owned_crew_children(parent.id)
        assert error.value.code == "owned_steps_not_managed"
        return parent.id

    async def install(self, parent_id: str, *, canonical: bool) -> None:
        if canonical:
            session = await self.state.service.get_session(parent_id)
            assert session is not None
            specs = self.state.replan_decomposer.decompose(session.goal)
            plan, inserts = _build_derived_recovery_plan(
                parent_id, specs, created_by=session.facilitator_id,
            )
            await self.state.service.install_recovery_plan(
                parent_id,
                expected_session=session,
                expected_recovery=None,
                plan=plan,
                children=inserts,
            )
        else:
            children = tuple(await self.state.store.list_work_items(
                parent_id=parent_id, limit=1000,
            ))
            await self.state.store.get_owned_steps_execution_port().admit(
                parent_id, children=children, thread_id="",
            )
        membership = await self.state.store.get_owned_crew_children(parent_id)
        assert len(membership.active) == 2
        assert membership.retired == ()

    def sources(self, parent_id: str) -> list[tuple[Any, ...]]:
        with sqlite3.connect(self.state.storage_root / "workforce.db") as db:
            return db.execute(
                "SELECT * FROM work_items WHERE id=? OR parent_id=? ORDER BY id",
                (parent_id, parent_id),
            ).fetchall()

    async def corrupt(
        self, parent_id: str, membership: OwnedCrewChildren, corruption: str,
    ) -> None:
        extra = None
        if corruption == "extra_child":
            extra = await self.state.store.create_work_item(
                title="Unproven direct child", assigned_to="worker-a",
            )
        with sqlite3.connect(self.state.storage_root / "workforce.db") as db:
            if corruption == "malformed_control":
                db.execute(
                    "UPDATE work_items SET steps_control=? WHERE id=?",
                    ('{"version":1}', parent_id),
                )
            elif corruption == "extra_child":
                assert extra is not None
                db.execute(
                    "UPDATE work_items SET parent_id=? WHERE id=?",
                    (parent_id, extra.id),
                )
            elif corruption == "tampered_receipt":
                db.execute(
                    "UPDATE owned_steps_proposals SET acknowledgement="
                    "json_set(acknowledgement,'$.operation_id','tampered-operation') "
                    "WHERE proposal_id=?",
                    (membership.retired[0].proposal_id,),
                )
            else:
                assert corruption == "retired_source"
                db.execute(
                    "UPDATE work_items SET actual_tokens=actual_tokens+1 WHERE id=?",
                    (membership.retired[0].child.id,),
                )
        with pytest.raises((OwnedStepsError, ValueError)) as error:
            await self.state.store.get_owned_crew_children(parent_id)
        if isinstance(error.value, OwnedStepsError):
            assert error.value.code != "owned_steps_not_managed"


@pytest.fixture
async def owned_projection_case(tmp_path: Path) -> Any:
    from ui.e2e.fixtures.ad1192_backend import _build_state

    root = Path(__file__).resolve().parents[1]
    assert Path(inspect.getfile(WorkItemStore)).resolve() == root / "src/probos/workforce.py"
    assert Path(inspect.getfile(_build_state)).resolve() == root / "ui/e2e/fixtures/ad1192_backend.py"
    state = await _build_state(tmp_path)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(state.runtime)),
            base_url="http://test",
        ) as client:
            yield _OwnedProjectionCase(state=state, client=client)
    finally:
        tasks = tuple(state.running_executions.values()) + tuple(state.scheduled.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await state.orchestrator.stop()
        await state.route_agent.stop()
        await state.trust.stop()
        await state.secondary_store.stop()
        await state.store.stop()


async def test_owned_legacy_replan_current_children(
    owned_projection_case: _OwnedProjectionCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = owned_projection_case
    parent_id = await case.managed_parent(canonical=False)
    original = await case.state.store.get_owned_crew_children(parent_id)
    assert len(original.active) == 2 and original.retired == ()
    assert original.active[0].priority == original.active[1].priority
    assert original.active[0].created_at < original.active[1].created_at
    response = await case.client.get(f"/api/crew-tasks/{parent_id}")
    assert response.status_code == 200, response.text
    assert [child["id"] for child in response.json()["children"]] == [
        child.id for child in reversed(original.active)
    ]

    decompose = case.state.replan_decomposer.decompose

    def priority_plan(goal: str) -> list[Any]:
        return [
            replace(spec, priority=4 if index == 0 else 1)
            for index, spec in enumerate(decompose(goal))
        ]

    monkeypatch.setattr(case.state.replan_decomposer, "decompose", priority_plan)
    await case.apply(parent_id, "replan_unstarted", "legacy-projection-replan")
    membership = await case.state.store.get_owned_crew_children(parent_id)
    assert len(membership.active) == len(membership.retired) == 2
    assert [child.priority for child in membership.active] == [4, 1]
    assert {entry.child.id for entry in membership.retired} == {
        child.id for child in original.active
    }
    assert [entry.child.to_dict() for entry in membership.retired] == [
        child.to_dict()
        for child in sorted(original.active, key=lambda child: child.id)
    ]
    before = case.sources(parent_id)
    parent = await case.state.store.get_work_item(parent_id)
    assert parent is not None

    response = await case.client.get(f"/api/crew-tasks/{parent_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"parent", "children", "count"}
    assert body["parent"] == parent.to_dict()
    assert body["count"] == 2
    assert body["children"] == [
        {**child.to_dict(), "verdict": None, "rounds": None}
        for child in sorted(
            membership.active, key=lambda child: (child.priority, -child.created_at),
        )
    ]
    assert case.sources(parent_id) == before


@pytest.mark.parametrize("canonical", [True, False], ids=["canonical", "legacy"])
@pytest.mark.parametrize("child_count", [0, 2], ids=["empty", "nonempty"])
async def test_unmanaged_preinstall_projection_compatibility(
    owned_projection_case: _OwnedProjectionCase,
    canonical: bool,
    child_count: int,
) -> None:
    case = owned_projection_case
    parent_id = await case.unmanaged_parent(canonical=canonical, child_count=child_count)
    parent = await case.state.store.get_work_item(parent_id)
    children = await case.state.store.list_work_items(parent_id=parent_id, limit=1000)
    assert parent is not None and len(children) == child_count
    before = case.sources(parent_id)

    response = await case.client.get(f"/api/crew-tasks/{parent_id}")

    assert response.status_code == 200, response.text
    if canonical:
        session = await case.state.service.get_session(parent_id)
        assert session is not None
        assert response.json() == {"session": build_crew_session_detail(
            session=session, synthesis=None, children=children,
        ).to_wire()}
    else:
        assert response.json() == {
            "parent": parent.to_dict(),
            "children": [
                {**child.to_dict(), "verdict": None, "rounds": None}
                for child in children
            ],
            "count": child_count,
        }
    assert case.sources(parent_id) == before


@pytest.mark.parametrize("canonical", [True, False], ids=["canonical", "legacy"])
@pytest.mark.parametrize("corruption", [
    "malformed_control", "extra_child", "tampered_receipt", "retired_source",
])
async def test_owned_projection_membership_conflicts_fail_closed(
    owned_projection_case: _OwnedProjectionCase,
    canonical: bool,
    corruption: str,
) -> None:
    case = owned_projection_case
    parent_id = await case.managed_parent(canonical=canonical)
    await case.apply(parent_id, "replan_unstarted", "corruption-replan")
    membership = await case.state.store.get_owned_crew_children(parent_id)
    assert len(membership.active) == 2
    assert len(membership.retired) == (1 if canonical else 2)
    await case.corrupt(parent_id, membership, corruption)
    before = case.sources(parent_id)

    response = await case.client.get(f"/api/crew-tasks/{parent_id}")

    assert response.status_code == 409
    assert response.json() == {"detail": CREW_SESSION_PROJECTION_ERROR}
    if canonical:
        summaries = await case.client.get("/api/threads/summaries")
        assert summaries.status_code == 200
        thread_id = case.state.threads_by_scenario["canonical"]
        summary = summaries.json()["summaries"][thread_id]
        assert set(summary) == {"outputs", "steps_total", "steps_done", "topic"}
        assert summary["steps_total"] == 3
        assert summary["steps_done"] == 0
    assert case.sources(parent_id) == before


class _ProjectionReadBarrier:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.used = False

    async def pause(self) -> None:
        if self.used:
            return
        self.used = True
        self.entered.set()
        await self.release.wait()


@pytest.mark.parametrize("canonical", [True, False], ids=["canonical", "legacy"])
@pytest.mark.parametrize("transition", ["replan", "install"])
async def test_replan_read_interleaving_fails_closed(
    owned_projection_case: _OwnedProjectionCase,
    monkeypatch: pytest.MonkeyPatch,
    canonical: bool,
    transition: str,
) -> None:
    case = owned_projection_case
    if transition == "replan":
        parent_id = await case.managed_parent(canonical=canonical)
        before_membership = await case.state.store.get_owned_crew_children(parent_id)
    else:
        parent_id = await case.unmanaged_parent(
            canonical=canonical, child_count=0 if canonical else 2,
        )
        before_membership = None
    session_before = await case.state.service.get_session(parent_id) if canonical else None
    parent_before = await case.state.store.get_work_item(parent_id)
    assert parent_before is not None
    barrier = _ProjectionReadBarrier()
    reader = case.state.secondary_store
    case.state.runtime.work_item_store = reader
    get_membership = reader.get_owned_crew_children
    list_children = reader.list_work_items
    observations: list[OwnedStepsSeedPlan | str | None] = []

    async def fenced_membership(
        key: str, expected_plan: OwnedStepsSeedPlan | str | None = None,
    ) -> OwnedCrewChildren:
        if asyncio.current_task() is request:
            observations.append(expected_plan)
            if expected_plan is not None:
                await barrier.pause()
        return await get_membership(key, expected_plan=expected_plan)

    async def paused_listing(**kwargs: Any) -> list[WorkItem]:
        children = await list_children(**kwargs)
        if asyncio.current_task() is request:
            await barrier.pause()
        return children

    monkeypatch.setattr(reader, "get_owned_crew_children", fenced_membership)
    monkeypatch.setattr(reader, "list_work_items", paused_listing)
    request = asyncio.create_task(case.client.get(f"/api/crew-tasks/{parent_id}"))
    try:
        await barrier.entered.wait()
        assert not request.done()
        if transition == "replan":
            await case.apply(parent_id, "replan_unstarted", "overlapping-replan")
        else:
            await case.install(parent_id, canonical=canonical)
        after_membership = await case.state.store.get_owned_crew_children(parent_id)
        assert len(after_membership.active) == 2
        if before_membership is not None:
            assert after_membership.incarnation != before_membership.incarnation
            assert after_membership.plan_digest != before_membership.plan_digest
            assert len(after_membership.retired) == len(before_membership.active)
        if canonical:
            session_after = await case.state.service.get_session(parent_id)
            parent_after = await case.state.store.get_work_item(parent_id)
            assert session_before is not None and session_after is not None
            assert session_after.revision == session_before.revision
            assert parent_after is not None
            assert parent_after.metadata["crew_session"] == parent_before.metadata["crew_session"]
            assert parent_after.metadata["crew_recovery"] != parent_before.metadata.get("crew_recovery")
        committed_sources = case.sources(parent_id)
        barrier.release.set()
        response = await request

        assert response.status_code == 409
        assert response.json() == {"detail": CREW_SESSION_PROJECTION_ERROR}
        assert observations == [
            None, before_membership.plan_digest if before_membership is not None else None,
        ]
        fresh = await case.client.get(f"/api/crew-tasks/{parent_id}")
        assert fresh.status_code == 200, fresh.text
        if canonical:
            progress = fresh.json()["session"]["progress"]
            assert progress["total"] == 2
            assert progress["active_child"]["id"] in {
                child.id for child in after_membership.active
            }
        else:
            assert fresh.json()["count"] == 2
            assert {child["id"] for child in fresh.json()["children"]} == {
                child.id for child in after_membership.active
            }
        assert case.sources(parent_id) == committed_sources
    finally:
        barrier.release.set()
        if not request.done():
            request.cancel()
        await asyncio.gather(request, return_exceptions=True)


@pytest.mark.parametrize(
    ("canonical", "limit"), [(True, 1001), (False, 1000)],
    ids=["canonical", "legacy"],
)
async def test_unmanaged_listing_oserror_returns_stable_409(
    api_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    canonical: bool,
    limit: int,
) -> None:
    if canonical:
        parent, _ = await _crew_parent(
            api_harness, parent_id="parent-unmanaged-listing",
        )
    else:
        parent = await api_harness.work.create_work_item(
            id="parent-unmanaged-listing", title="Legacy crew", work_type="crew_task",
        )
    read = api_harness.work.get_owned_crew_children
    calls: list[str] = []

    async def observed_not_managed(
        key: str, expected_plan: OwnedStepsSeedPlan | str | None = None,
    ) -> OwnedCrewChildren:
        assert key == parent.id
        assert expected_plan is None
        with pytest.raises(OwnedStepsError) as raised:
            await read(key, expected_plan=expected_plan)
        assert raised.value.code == "owned_steps_not_managed"
        calls.append("not_managed")
        raise raised.value

    async def failing_listing(**kwargs: Any) -> list[WorkItem]:
        assert calls == ["not_managed"]
        assert kwargs == {"parent_id": parent.id, "limit": limit}
        calls.append("listing")
        raise OSError("unmanaged listing unavailable")

    monkeypatch.setattr(api_harness.work, "get_owned_crew_children", observed_not_managed)
    monkeypatch.setattr(api_harness.work, "list_work_items", failing_listing)
    transport = httpx.ASGITransport(app=api_harness.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/crew-tasks/{parent.id}")

    assert calls == ["not_managed", "listing"]
    assert response.status_code == 409
    assert response.json() == {"detail": CREW_SESSION_PROJECTION_ERROR}


@pytest.mark.parametrize("error_type", [
    ValueError, OSError, RuntimeError, TypeError, asyncio.CancelledError,
])
@pytest.mark.parametrize("current_after", [True, False], ids=["current", "cancelled"])
async def test_unmanaged_listing_failure_boundary_preserves_cause_and_cancellation(
    api_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
    current_after: bool,
) -> None:
    error = error_type("unmanaged listing failed")
    current = True
    checks: list[bool] = []
    listings: list[dict[str, Any]] = []

    def still_current() -> bool:
        checks.append(current)
        return current

    async def failing_listing(**kwargs: Any) -> list[WorkItem]:
        nonlocal current
        listings.append(kwargs)
        await asyncio.sleep(0)
        current = current_after
        raise error

    monkeypatch.setattr(api_harness.work, "list_work_items", failing_listing)
    expected_type = (
        asyncio.CancelledError if not current_after
        else CrewSessionProjectionError if error_type in (ValueError, OSError)
        else error_type
    )

    with pytest.raises(expected_type) as raised:
        await load_fenced_crew_children(
            "parent-failing-listing",
            observation=None,
            work_item_store=api_harness.work,
            unmanaged_limit=1001,
            still_current=still_current,
        )

    assert listings == [{"parent_id": "parent-failing-listing", "limit": 1001}]
    assert checks == [True, current_after]
    if current_after:
        if error_type in (ValueError, OSError):
            assert raised.value.__cause__ is error
            assert str(raised.value) == CREW_SESSION_PROJECTION_ERROR
        else:
            assert raised.value is error
            assert raised.value.__cause__ is None


@pytest.mark.parametrize("error_type", [RuntimeError, TypeError, asyncio.CancelledError])
async def test_observe_crew_children_unexpected_errors_propagate_unconverted(
    api_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
) -> None:
    error = error_type("membership reader failed")

    async def failing_read(
        parent_id: str, expected_plan: OwnedStepsSeedPlan | str | None = None,
    ) -> OwnedCrewChildren:
        assert parent_id == "parent-failing-observation"
        assert expected_plan == _SHA_A
        raise error

    monkeypatch.setattr(api_harness.work, "get_owned_crew_children", failing_read)

    with pytest.raises(error_type) as raised:
        await observe_crew_children(
            "parent-failing-observation",
            work_item_store=api_harness.work,
            expected_plan=_SHA_A,
        )

    assert raised.value is error


@pytest.mark.parametrize("canonical", [True, False], ids=["canonical", "legacy"])
@pytest.mark.parametrize("failure", [
    "repair_required", "unavailable", "plan_conflict", "not_managed_suffix",
    "untyped_not_managed", "io_error", "missing_result",
])
async def test_projection_membership_failure_never_uses_unmanaged_fallback(
    owned_projection_case: _OwnedProjectionCase,
    monkeypatch: pytest.MonkeyPatch,
    canonical: bool,
    failure: str,
) -> None:
    case = owned_projection_case
    parent_id = await case.managed_parent(canonical=canonical)
    membership = await case.state.store.get_owned_crew_children(parent_id)
    reader = case.state.secondary_store
    case.state.runtime.work_item_store = reader
    read = reader.get_owned_crew_children
    list_children = reader.list_work_items
    observations: list[OwnedStepsSeedPlan | str | None] = []
    listings: list[dict[str, Any]] = []

    async def failing_close(
        key: str, expected_plan: OwnedStepsSeedPlan | str | None = None,
    ) -> OwnedCrewChildren | None:
        observations.append(expected_plan)
        if len(observations) == 1:
            return await read(key, expected_plan=expected_plan)
        if failure == "missing_result":
            return None
        if failure == "untyped_not_managed":
            raise ValueError("owned_steps_not_managed")
        if failure == "io_error":
            raise OSError("membership source unavailable")
        raise OwnedStepsError(f"owned_steps_{failure}", parent_id=key)

    async def recorded_listing(**kwargs: Any) -> list[WorkItem]:
        listings.append(kwargs)
        return await list_children(**kwargs)

    monkeypatch.setattr(reader, "get_owned_crew_children", failing_close)
    monkeypatch.setattr(reader, "list_work_items", recorded_listing)
    before = case.sources(parent_id)

    response = await case.client.get(f"/api/crew-tasks/{parent_id}")

    assert response.status_code == 409
    assert response.json() == {"detail": CREW_SESSION_PROJECTION_ERROR}
    assert observations == [None, membership.plan_digest]
    assert listings == []
    assert case.sources(parent_id) == before


@pytest.mark.parametrize("canonical", [True, False], ids=["canonical", "legacy"])
@pytest.mark.parametrize("identity", [
    "parent_id", "incarnation", "plan_digest", "ordered_ids", "unmanaged",
])
async def test_projection_membership_identity_fence_rejects_changed_observation(
    owned_projection_case: _OwnedProjectionCase,
    monkeypatch: pytest.MonkeyPatch,
    canonical: bool,
    identity: str,
) -> None:
    case = owned_projection_case
    case.state.ingress_decomposer.count = 2
    parent_id = await case.managed_parent(canonical=canonical)
    membership = await case.state.store.get_owned_crew_children(parent_id)
    assert len(membership.active) == 2
    reader = case.state.secondary_store
    case.state.runtime.work_item_store = reader
    read = reader.get_owned_crew_children
    observations: list[OwnedStepsSeedPlan | str | None] = []

    async def changed_identity(
        key: str, expected_plan: OwnedStepsSeedPlan | str | None = None,
    ) -> OwnedCrewChildren:
        observations.append(expected_plan)
        proven = await read(key, expected_plan=expected_plan)
        if len(observations) == 1:
            return proven
        # Fault only the closing public result, after the real store proves it.
        if identity == "unmanaged":
            raise OwnedStepsError("owned_steps_not_managed", parent_id=key)
        if identity == "ordered_ids":
            return replace(proven, active=tuple(reversed(proven.active)))
        return replace(proven, **{identity: f"changed-{identity}"})

    monkeypatch.setattr(reader, "get_owned_crew_children", changed_identity)

    response = await case.client.get(f"/api/crew-tasks/{parent_id}")

    assert response.status_code == 409
    assert response.json() == {"detail": CREW_SESSION_PROJECTION_ERROR}
    assert observations == [None, membership.plan_digest]


@pytest.mark.parametrize("canonical", [True, False], ids=["canonical", "legacy"])
async def test_projection_closing_observation_supplies_current_child_content(
    owned_projection_case: _OwnedProjectionCase,
    monkeypatch: pytest.MonkeyPatch,
    canonical: bool,
) -> None:
    case = owned_projection_case
    parent_id = await case.managed_parent(canonical=canonical)
    membership = await case.state.store.get_owned_crew_children(parent_id)
    reader = case.state.secondary_store
    case.state.runtime.work_item_store = reader
    read = reader.get_owned_crew_children
    observations: list[OwnedStepsSeedPlan | str | None] = []

    async def stale_first_content(
        key: str, expected_plan: OwnedStepsSeedPlan | str | None = None,
    ) -> OwnedCrewChildren:
        observations.append(expected_plan)
        proven = await read(key, expected_plan=expected_plan)
        if len(observations) == 1:
            # Identity is stable, but the first observation's row content is stale.
            return replace(proven, active=tuple(
                replace(child, title="Earlier observation")
                for child in proven.active
            ))
        return proven

    monkeypatch.setattr(reader, "get_owned_crew_children", stale_first_content)
    before = case.sources(parent_id)

    response = await case.client.get(f"/api/crew-tasks/{parent_id}")

    assert response.status_code == 200, response.text
    if canonical:
        selected = response.json()["session"]["progress"]["active_child"]
        current = {child.id: child for child in membership.active}[selected["id"]]
        assert selected["title"] == current.title
    else:
        assert response.json()["children"] == [
            {**child.to_dict(), "verdict": None, "rounds": None}
            for child in sorted(
                membership.active, key=lambda child: (child.priority, -child.created_at),
            )
        ]
    assert observations == [None, membership.plan_digest]
    assert case.sources(parent_id) == before


async def test_legacy_parent_is_reloaded_inside_membership_fence(
    owned_projection_case: _OwnedProjectionCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = owned_projection_case
    parent_id = await case.managed_parent(canonical=False)
    old_parent = await case.state.store.get_work_item(parent_id)
    assert old_parent is not None
    reader = case.state.secondary_store
    case.state.runtime.work_item_store = reader
    read = reader.get_owned_crew_children
    replanned = False

    async def replan_before_observation(
        key: str, expected_plan: OwnedStepsSeedPlan | str | None = None,
    ) -> OwnedCrewChildren:
        nonlocal replanned
        if not replanned:
            replanned = True
            await case.apply(parent_id, "replan_unstarted", "before-first-observation")
        return await read(key, expected_plan=expected_plan)

    monkeypatch.setattr(reader, "get_owned_crew_children", replan_before_observation)

    response = await case.client.get(f"/api/crew-tasks/{parent_id}")

    current_parent = await case.state.store.get_work_item(parent_id)
    assert replanned and current_parent is not None
    assert old_parent.steps != current_parent.steps
    assert response.status_code == 200, response.text
    assert response.json()["parent"] == current_parent.to_dict()
    assert response.json()["count"] == 2