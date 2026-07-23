"""AD-1132: bounded CrewSession projections on existing HXI APIs."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from probos.cognitive.crew_session import (
    CrewSessionContract,
    CrewSynthesisMetadata,
)
from probos.config import SystemConfig
from probos.crew_session_projection import (
    CREW_SESSION_PROJECTION_ERROR,
    build_crew_session_detail,
    build_crew_session_summary,
)
from probos.routers import crew_tasks as crew_tasks_router
from probos.routers import threads as threads_router
from probos.routers.deps import get_runtime
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.threads import ChatThreadStore
from probos.workforce import CrewSessionParentCreate, WorkItem, WorkItemStore


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