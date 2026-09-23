"""Real M2 execution crossings; no provider calls or private owner patching."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest

from probos import work_item_steps as steps
from probos.cognitive.agentic_dispatch import AgenticIdentityUnresolved, WorkItemAgenticOutcome
from probos.cognitive.crew_executor import CrewTaskExecutor
from probos.crew_execution_usage import read_crew_execution_token_usage
from probos.crew_utils import CREW_EXECUTION_KEYS, is_crew_agent
from probos.workforce import CrewSessionParentCreate, WorkItemStore


class _Registry:
    def __init__(self) -> None:
        self.agents = {
            identity: SimpleNamespace(id=identity, instructions="deterministic", agent_type="builder",
                                      department="engineering", rank="ensign")
            for identity in ("worker-a", "worker-b")
        }

    def get(self, identity: str | None) -> Any:
        return self.agents.get(identity)


class _Worker:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
        self.calls.append(kwargs)
        await kwargs["owned_steps_execution_port"].validate(
            kwargs["owned_steps_execution_lease"], kwargs["owned_steps_execution_permit"],
        )
        return WorkItemAgenticOutcome(final_text=f"exact-{kwargs['agent_id']}", stopped_reason="complete")


class _Captain:
    def __init__(self) -> None:
        self.credential = object()

    async def authorize_owned_steps(self, authority: steps.OwnedStepsAuthority, **context: Any) -> steps.OwnedStepsGrant:
        if authority.context is not self.credential:
            raise steps.OwnedStepsError("owned_steps_authority_denied")
        return steps.OwnedStepsGrant(context["parent_id"], "captain", "", "captain")

    async def expire_owned_steps(self, work_item_id: str, observed_at: float) -> bool:
        raise AssertionError("No expiry in this fixture")


@pytest.fixture
async def store(tmp_path):
    value = WorkItemStore(str(tmp_path / "execution.db"), tick_interval=1000)
    await value.start()
    try:
        yield value
    finally:
        await value.stop()


@pytest.fixture
async def owned_closeout_case(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from probos.api import create_app
    from ui.e2e.fixtures.ad1192_backend import _build_state

    root = Path(__file__).resolve().parents[1]
    assert Path(inspect.getfile(WorkItemStore)).resolve() == root / "src" / "probos" / "workforce.py"
    assert Path(inspect.getfile(_build_state)).resolve() == root / "ui" / "e2e" / "fixtures" / "ad1192_backend.py"
    state = await _build_state(tmp_path)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=create_app(state.runtime), raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            yield SimpleNamespace(state=state, client=client)
    finally:
        for task in state.running_executions.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*state.running_executions.values(), return_exceptions=True)
        await state.orchestrator.stop()
        await state.route_agent.stop()
        await state.trust.stop()
        await state.secondary_store.stop()
        await state.store.stop()


async def _owned_http_view(case: Any, item_id: str) -> dict[str, Any]:
    response = await case.client.get(f"/api/work-items/{item_id}/owned-steps")
    assert response.status_code == 200, response.text
    return response.json()


async def _owned_http_proposal(
    case: Any, item_id: str, kind: str, operation_id: str, **fields: Any,
) -> dict[str, Any]:
    view = await _owned_http_view(case, item_id)
    response = await case.client.post(
        f"/api/work-items/{item_id}/owned-steps/preview",
        json={
            "version": 1, "kind": kind, "preparation_id": operation_id,
            "reference": view["reference"], **fields,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["proposal"]


async def _owned_http_apply(case: Any, item_id: str, proposal: dict[str, Any], operation_id: str) -> None:
    endpoint = "adopt" if proposal["kind"] == "adopt_existing" else "commands"
    response = await case.client.post(
        f"/api/work-items/{item_id}/owned-steps/{endpoint}",
        json={"version": 1, "operation_id": operation_id, "reference": proposal["reference"]},
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_canonical_two_replans_restart_recovery_resume_and_publication(owned_closeout_case) -> None:
    case = owned_closeout_case
    state = case.state
    setup = await state.create_canonical()
    parent_id = setup["parent_id"]
    original = await state.store.read_owned_steps_raw_identity(parent_id)
    await _owned_http_apply(
        case, parent_id,
        await _owned_http_proposal(case, parent_id, "adopt_existing", "canonical-adopt"),
        "canonical-adopt",
    )
    retired_ids = {setup["child_id"]}
    for index in range(2):
        proposal = await _owned_http_proposal(case, parent_id, "replan_unstarted", f"canonical-replan-{index}")
        await _owned_http_apply(case, parent_id, proposal, f"canonical-replan-{index}")
        membership = await state.store.get_owned_crew_children(parent_id)
        assert len(membership.active) == 2
        assert {entry.child.id for entry in membership.retired} == retired_ids
        recovery = await state.service.get_recovery(parent_id)
        assert recovery is not None and recovery.plan is not None
        assert {entry.child_id for entry in recovery.plan.children} == {child.id for child in membership.active}
        retired_ids.update(child.id for child in membership.active)
        await state.store.stop()
        await state.store.start()
        assert await state.service.get_recovery(parent_id) == recovery

    initial_task = state.schedule(parent_id)
    result = await initial_task
    assert not result.completed
    assert (result.accepted_count, result.total_count) == (2, 2)
    assert (await state.service.get_session(parent_id)).state == "verifying"
    assert len(state.worker.calls) == 2
    snapshot = await state.store.get_owned_steps(parent_id)
    assert snapshot.control.original_steps_json == original.raw_steps
    assert all(row.review_accepted is True for row in snapshot.control.rows if row.child is not None)
    assert snapshot.control.finalization is not None
    assert snapshot.control.mode == "waiting_manual_gate"
    assert snapshot.control.finalization_disposition == "pending"
    frozen_output = await state.store.read_owned_steps_content(snapshot.control.finalization.output)
    calls = state.counters()
    for kind in ("manual_submit", "manual_confirm"):
        view = await _owned_http_view(case, parent_id)
        response = await case.client.post(
            f"/api/work-items/{parent_id}/owned-steps/commands",
            json={
                "version": 1, "reference": view["reference"],
                "commands": [{"operation_id": kind, "step_id": view["rows"][0]["step_id"], "kind": kind}],
            },
        )
        assert response.status_code == 200, response.text
    assert state.scheduled[parent_id] is not initial_task
    finished = await state.scheduled[parent_id]
    assert finished.completed
    assert finished.final_output == frozen_output.decode("utf-8")
    assert (await state.service.get_session(parent_id)).state == "done"
    assert len((await state.store.get_owned_crew_children(parent_id)).retired) == 3
    assert state.counters() == calls


@pytest.mark.asyncio
@pytest.mark.parametrize("lose_after_commit", [False, True], ids=["retry", "retry-failure"])
async def test_canonical_replan_native_retry_barrier_uses_only_proven_active_children(
    owned_closeout_case, monkeypatch: pytest.MonkeyPatch, lose_after_commit: bool,
) -> None:
    case, state = owned_closeout_case, owned_closeout_case.state
    setup = await state.create_canonical()
    parent_id = setup["parent_id"]
    for kind in ("adopt_existing", "replan_unstarted"):
        await _owned_http_apply(
            case, parent_id, await _owned_http_proposal(case, parent_id, kind, kind), kind,
        )

    class _Eligibility:
        def check_eligibility(self, agent_id: str) -> Any:
            agent = state.registry.get(agent_id)
            return SimpleNamespace(identity=agent if agent is not None and agent.is_alive else None)

        def resolve(self, spec: Any) -> Any:
            return SimpleNamespace(agent_id="worker-a")

    state.registry.get("verifier-a").agent_type = "security_officer"
    session = await state.service.get_session(parent_id)
    assert all(is_crew_agent(state.registry.get(agent_id)) for agent_id in session.owner_ids)
    state.service.bind_worker_resolver(_Eligibility())
    worker = state.registry.get("worker-a")
    worker.is_alive = False
    stopped = await state.schedule(parent_id)
    assert not stopped.completed
    blocked = await state.service.get_session(parent_id)
    assert blocked.blocked_reason == "crew_worker_unavailable"
    assert len(state.worker.calls) == 0
    worker.is_alive = True
    merge = state.store.merge_work_item_metadata
    committed: list[str] = []

    async def observe_retry(item_id: str, patch: dict[str, Any], **kwargs: Any) -> Any:
        result = await merge(item_id, patch, **kwargs)
        if kwargs.get("source") == "crew_session_ingress_resume":
            assert result is not None
            committed.append(item_id)
            if lose_after_commit:
                worker.is_alive = False
        return result

    monkeypatch.setattr(state.store, "merge_work_item_metadata", observe_retry)
    request = {
        "principal": state.service.captain_principal(), "goal": blocked.goal,
        "success_criteria": list(blocked.success_criteria),
        "expected_deliverable": blocked.expected_deliverable,
        "requested_thread_id": setup["thread_id"], "retry_blocked": True,
    }
    try:
        if lose_after_commit:
            with pytest.raises(ValueError, match="crew_worker_unavailable"):
                await state.service.open_or_resume(**request)
            current = await state.service.get_session(parent_id)
            assert current.state == "blocked_needs_captain"
            assert current.blocked_reason == "crew_worker_unavailable"
            assert len(state.worker.calls) == 0
        else:
            reopened = await state.service.open_or_resume(**request)
            assert reopened.disposition == "resumed"
            await state.scheduled[parent_id]
            assert len(state.worker.calls) == 2
        assert committed == [parent_id]
        membership = await state.store.get_owned_crew_children(parent_id)
        assert len(membership.active) == 2 and len(membership.retired) == 1
    finally:
        worker.is_alive = True


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["retired-source", "unexpected-child"])
async def test_canonical_recovery_and_resume_reject_tampered_retired_or_extra_children(
    owned_closeout_case, corruption: str,
) -> None:
    case, state = owned_closeout_case, owned_closeout_case.state
    setup = await state.create_canonical()
    parent_id = setup["parent_id"]
    for kind in ("adopt_existing", "replan_unstarted"):
        await _owned_http_apply(
            case, parent_id, await _owned_http_proposal(case, parent_id, kind, kind), kind,
        )
    membership = await state.store.get_owned_crew_children(parent_id)
    assert len(membership.active) == 2 and len(membership.retired) == 1
    with sqlite3.connect(state.storage_root / "workforce.db") as db:
        if corruption == "retired-source":
            db.execute("UPDATE work_items SET description=? WHERE id=?", ("tampered retired source", setup["child_id"]))
        else:
            inserted = db.execute(
                "INSERT INTO work_items (id,title,parent_id,metadata,created_at,updated_at) "
                "SELECT ?,title,parent_id,metadata,created_at,updated_at FROM work_items WHERE id=?",
                ("unexpected-child", setup["child_id"]),
            )
            assert inserted.rowcount == 1
    with pytest.raises(steps.OwnedStepsError, match="retirement_conflict|membership_conflict"):
        await state.service.get_recovery(parent_id)
    with pytest.raises(steps.OwnedStepsError, match="retirement_conflict|membership_conflict"):
        await state.executor.resume(parent_id)
    assert not state.worker.calls


async def _plan(store: WorkItemStore, *, prefix: bool = False):
    parent = await store.create_work_item(
        id="legacy-parent", title="Parent", metadata={"manual_data": "keep"},
        steps=[{"label": "manual", "status": "pending", "note": None}] if prefix else [],
    )
    children = tuple([await store.create_work_item(
        id=f"child-{index}", title=f"Child {index}", parent_id=parent.id,
        assigned_to=actor, metadata={"spec_id": f"spec-{index}"},
    ) for index, actor in enumerate(("worker-a", "worker-b"))])
    return parent, children


def _executor(store: WorkItemStore, worker: _Worker, **kwargs: Any) -> CrewTaskExecutor:
    return CrewTaskExecutor(
        work_item_store=store, agent_registry=_Registry(), agentic_executor=worker,
        runtime=SimpleNamespace(config=SimpleNamespace(group_chat=SimpleNamespace(auto_task_room_enabled=False))),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_direct_no_room_run_submits_exact_results_and_restarts_without_replay(store: WorkItemStore) -> None:
    parent, children = await _plan(store)
    worker = _Worker()
    executor = _executor(store, worker)
    original_port = store.get_owned_steps_execution_port()
    assert original_port is store.get_owned_steps_execution_port()
    results = await executor.run(parent.id)
    assert len(worker.calls) == 2 and all(result.status == "done" for result in results)
    assert all(call["thread_id"] == "" for call in worker.calls)
    assert (await store.get_work_item(parent.id)).assigned_to is None
    snapshot = await store.get_owned_steps(parent.id)
    assert snapshot.control.thread_id == "" and snapshot.control.facilitator_id is None
    for child in children:
        item = await store.get_work_item(child.id)
        assert set(item.metadata["crew_execution"]) == CREW_EXECUTION_KEYS
        assert item.metadata["crew_execution"]["thread_id"] == ""
    old_lease = worker.calls[0]["owned_steps_execution_lease"]
    old_permit = worker.calls[0]["owned_steps_execution_permit"]
    await store.stop()
    await store.start()
    assert store.get_owned_steps_execution_port() is not original_port
    with pytest.raises(steps.OwnedStepsError, match="port_expired"):
        await original_port.validate(old_lease, old_permit)
    replay = await executor.run(parent.id)
    assert {result.work_item_id: result for result in replay} == {result.work_item_id: result for result in results}
    assert len(worker.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("arrival", ["measured_zero", "exception", "identity_loss"])
async def test_owned_submission_distinguishes_real_zero_from_synthetic_outcomes(
    store: WorkItemStore, enabled: bool, arrival: str,
) -> None:
    parent, children = await _plan(store)

    class _ZeroWorker(_Worker):
        async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
            outcome = await super().run(**kwargs)
            if arrival == "exception":
                raise RuntimeError("execution failed before supplying usage")
            if arrival == "identity_loss":
                raise AgenticIdentityUnresolved()
            assert outcome.total_tokens == 0 and outcome.token_source == "measured"
            return outcome

    class _Eligibility:
        def check_eligibility(self, agent_id: str) -> Any:
            return SimpleNamespace(identity=agent_id)

    worker = _ZeroWorker()
    results = await _executor(
        store, worker, eligibility_resolver=_Eligibility(),
        event_correlation_enabled=enabled,
    ).run(parent.id)

    assert len(results) == len(worker.calls) == len(children) == 2
    snapshot = await store.get_owned_steps(parent.id)
    for child, result in zip(children, results):
        item = await store.get_work_item(child.id)
        assert item.actual_tokens == result.actual_tokens == 0
        assert result.stopped_reason == {
            "measured_zero": "complete", "exception": "execution_exception",
            "identity_loss": "crew_worker_identity_lost",
        }[arrival]
        assert item.status == result.status == ("done" if arrival == "measured_zero" else "failed")
        usage = read_crew_execution_token_usage(item.metadata)
        row = next(row for row in snapshot.control.rows if row.child.child_id == child.id)
        submission = await store.get_owned_step_evidence(
            parent.id, snapshot.control.incarnation, "submission", row.submission,
        )
        if enabled and arrival == "measured_zero":
            assert usage.tokens_used == 0 and usage.token_source == "measured"
            assert json.loads(submission.token_usage_json) == {
                "version": 1, "tokens_used": 0, "token_source": "measured",
            }
        else:
            assert usage is None
            assert "crew_execution_token_usage" not in item.metadata
            assert submission.token_usage_json is None


@pytest.mark.asyncio
async def test_shared_execution_port_keeps_owner_binding_and_rejects_foreign_store(store: WorkItemStore, tmp_path) -> None:
    owner = _Captain()
    store.bind_owned_steps_owner(owner, owner)
    port = store.get_owned_steps_execution_port()
    first = _executor(store, _Worker(), owned_steps_execution_port=port)
    second = _executor(store, _Worker(), owned_steps_execution_port=port)
    assert first is not second and store.get_owned_steps_execution_port() is port
    with pytest.raises(steps.OwnedStepsError, match="already_bound"):
        store.bind_owned_steps_owner(_Captain(), _Captain())
    other = WorkItemStore(str(tmp_path / "other.db"), tick_interval=1000)
    with pytest.raises(steps.OwnedStepsError, match="owner_conflict"):
        _executor(other, _Worker(), owned_steps_execution_port=port)


@pytest.mark.asyncio
async def test_nonempty_no_owner_plan_remains_preserved_and_captain_adoptable(store: WorkItemStore) -> None:
    parent, _ = await _plan(store, prefix=True)
    worker = _Worker()
    with pytest.raises(steps.OwnedStepsError, match="adoption_required"):
        await _executor(store, worker).run(parent.id)
    assert worker.calls == []
    assert (await store.get_work_item(parent.id)).steps == parent.steps
    assert (await store.get_work_item(parent.id)).metadata == parent.metadata
    snapshot = await store.get_owned_steps(parent.id)
    assert snapshot.control.mode == "awaiting_adoption" and snapshot.control.facilitator_id is None
    owner = _Captain()
    store.bind_owned_steps_owner(owner, owner)
    authority = steps.OwnedStepsAuthority(owner.credential)
    preview = await store.preview_owned_steps_adoption(parent.id, authority=authority, view_id="captain-view", turn_id="turn")
    await store.compare_and_set_owned_step(steps.OwnedStepMutation(
        steps.OwnedStepChange(operation_id="captain-adoption", token=preview.token, command=steps.AdoptOwnedStepsCommand(preview=preview)),
        authority,
    ))
    results = await _executor(store, worker).run(parent.id)
    assert len(results) == len(worker.calls) == 2
    assert (await store.get_work_item(parent.id)).steps[0] == parent.steps[0]


@pytest.mark.asyncio
async def test_execution_port_cannot_adopt_or_supply_captain_or_verdict_authority(store: WorkItemStore) -> None:
    parent, children = await _plan(store, prefix=True)
    port = store.get_owned_steps_execution_port()
    lease = await port.admit(parent.id, children=children, thread_id="")
    for authority in (lease.authority, steps.OwnedStepsAuthority("captain"), steps.OwnedStepsAuthority("verifier")):
        with pytest.raises(steps.OwnedStepsError, match="scope_denied|authority_required"):
            await store.preview_owned_steps_adoption(parent.id, authority=authority, view_id="forged", turn_id="turn")
    assert (await store.get_work_item(parent.id)).steps == parent.steps
    assert lease.snapshot.control.mode == "awaiting_adoption"


@pytest.mark.asyncio
async def test_canonical_scope_remains_nonempty_and_cannot_use_legacy_port(store: WorkItemStore) -> None:
    parent, _ = await _plan(store)
    legacy = await store.get_owned_steps_execution_port().admit(
        parent.id, children=tuple(await store.list_work_items(parent_id=parent.id)), thread_id="",
    )
    values = legacy.snapshot.control.model_dump(mode="json")
    values["owner_kind"] = "canonical"
    with pytest.raises(steps.OwnedStepsError, match="control_invalid"):
        steps.parse_owned_control(json.dumps(values))
    async with store.claim_crew_session_admission_port().reserve() as reservation:
        canonical = await reservation.create_parent(CrewSessionParentCreate(
            id="canonical", title="Canonical", description="Canonical", assigned_to="facilitator",
            created_by="captain", metadata={},
        ))
    child = await store.create_work_item(title="Canonical child", parent_id=canonical.id, assigned_to="worker-a")
    with pytest.raises(steps.OwnedStepsError, match="scope_denied"):
        await store.get_owned_steps_execution_port().admit(canonical.id, children=(child,), thread_id="")
