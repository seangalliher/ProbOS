"""AD-1286 (#1333): the one durable CrewSession -> team-spec association (Sections 3 and 5).

``CrewSessionService.bind_team_spec`` writes exactly one new key, ``crew_elastic_team``, on the
PARENT work-item row through the service's owned-metadata path: write-once, ``discussing`` only,
never on a child row and never inside ``crew_session`` / ``crew_recovery``. These tests drive the
real ``WorkItemStore`` and the real ``ElasticTeamStore`` (SQLite under ``tmp_path`` only) and reuse
the AD-1125 / AD-1127 / AD-1128 / AD-1152 harnesses, so a bound session is carried through reload,
restart, the recovery CAS, plan adoption, the retry barrier, finalization and publication.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from probos import work_item_steps as owned_steps
from probos.cognitive import crew_session as crew_session_module
from probos.cognitive.crew_session import (
    CrewRecoveryPlan,
    CrewSessionProvisioningContract,
    CrewSessionService,
    _build_adopted_recovery_plan,
    _build_derived_recovery_plan,
)
from probos.cognitive.elastic_team import CREW_ELASTIC_TEAM_METADATA_KEY, CrewElasticTeamBinding
from probos.cognitive.elastic_team_store import ElasticTeamStore
from probos.consultation.dispatch import WorkItemSpec
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.threads import ChatThreadStore
from probos.workforce import WorkItem, WorkItemRetryBarrier, WorkItemStore
from tests import test_ad1125_room_bound_execution as room
from tests.test_ad1125_room_bound_execution import stores  # noqa: F401  (fixture, used by name)
from tests.test_ad1127_crew_session_lifecycle_recovery import (
    _VECTOR_CHILD_ID,
    _VECTOR_PLAN_HASH,
    _VECTOR_ROW_HASH,
    _admission_port,
    _checkpoint_fault_finalizer,
    _Clock,
    _create_crew_parent,
    _durable_finalization_harness,
    _new_session,
    _vector_insert,
    _vector_plan_payload,
)
from tests.test_ad1128_crew_session_ingress_dedup import _create_reserved_parent
from tests.test_ad1132_crew_session_api import owned_projection_case  # noqa: F401  (fixture, used by name)
from tests.test_ad1152_crew_token_usage import _owned_merge
from tests.test_ad1286_elastic_team_contract import _spec
from tests.test_ad1286_elastic_team_store import _FaultyFactory

_KEY = CREW_ELASTIC_TEAM_METADATA_KEY
_SESSION_LOGGER = "probos.cognitive.crew_session"


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


@asynccontextmanager
async def _open_work_store(root: Path) -> AsyncIterator[WorkItemStore]:
    store = WorkItemStore(
        db_path=str(root / "workforce.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


@asynccontextmanager
async def _open_team_store(root: Path) -> AsyncIterator[ElasticTeamStore]:
    store = ElasticTeamStore(
        db_path=str(root / "elastic_teams.db"),
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


async def _row(work: WorkItemStore, work_item_id: str) -> WorkItem:
    row = await work.get_work_item(work_item_id)
    assert row is not None
    return row


async def _install_vector_plan(service: CrewSessionService, parent_id: str, session: Any) -> None:
    """Install the fixed-vector plan exactly as ``test_ad1127`` does (one child, known hashes)."""
    await service.install_recovery_plan(
        parent_id,
        expected_session=session,
        expected_recovery=None,
        plan=CrewRecoveryPlan.model_validate(_vector_plan_payload()),
        children=(_vector_insert(),),
    )


def _plan_bound_spec(plan_hash: str = _VECTOR_PLAN_HASH, *, revision: int = 2) -> Any:
    """A spec that names an installed CrewSession plan; revision 2 so it can sit beside ``_spec()``."""
    return _spec(process={"bill": None, "plan_hash": plan_hash}, revision=revision)


def _provisioning_marker() -> dict[str, Any]:
    """A valid AD-1128 ``crew_provisioning`` marker for the session ``_new_session`` builds (as JSON)."""
    request = crew_session_module._normalize_ingress_values(
        goal="Produce a durable result",
        success_criteria=["Result is complete"],
        expected_deliverable="A report",
    )
    marker = CrewSessionProvisioningContract.model_validate({
        "version": 1,
        "provision_id": "e" * 64,
        "phase": "parent_created",
        "room_policy": "create",
        "thread_id": "crew-room-provisioning",
        "goal": request.display_goal,
        "goal_fingerprint": request.goal_fingerprint,
        "origin": "captain",
        "originator_id": "captain",
        "created_by": "captain",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1", "agent-1"],
        "success_criteria": ["Result is complete"],
        "expected_deliverable": "A report",
        "plan_specs": crew_session_module._project_decomposition([WorkItemSpec(spec_id="spec-a", title="Child")]),
        "last_error_code": None,
    })
    return marker.model_dump(mode="json")


async def _new_session_during_provisioning(work: WorkItemStore, root: Path) -> tuple[WorkItem, CrewSessionService, Any]:
    """A discussing session whose parent still carries its AD-1128 ``crew_provisioning`` marker.

    The marker is supplied the way provisioning supplies it (``test_ad1128``): at parent creation,
    through the claimed admission port. The session is then initialised on top of it, exactly as
    ``_new_session`` does, so the only difference is the marker.
    """
    parent = await _create_reserved_parent(
        work,
        _admission_port(work),
        parent_id="session-parent",
        title="Session",
        assigned_to="facilitator-1",
        created_by="captain",
        metadata={"crew_provisioning": _provisioning_marker()},
        created_at=100.0,
    )
    threads = ChatThreadStore(root / "threads.db")
    thread = threads.create_thread(
        title="Session room", participants=["facilitator-1", "agent-1"], task_id=parent.id,
    )
    service = CrewSessionService(work_item_store=work, chat_thread_store=threads, clock=_Clock(200.0))
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


# --------------------------------------------------------------------------------------
# 1-5. The bound session crosses reload, restart, CAS, adoption, retry, finalization, publication
# --------------------------------------------------------------------------------------


async def test_bound_reference_survives_restart_and_changes_no_accepted_work(tmp_path: Path) -> None:
    """The seam-crossing test: bind, close BOTH stores, reopen them, and read it all back."""
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        parent, service, session = await _new_session(work, tmp_path)
        await _install_vector_plan(service, parent.id, session)
        before_parent = dict((await _row(work, parent.id)).metadata)
        before_child = _canonical((await _row(work, _VECTOR_CHILD_ID)).metadata)
        before_recovery = (await service.get_recovery(parent.id)).model_dump(mode="json")
        ref = await store.put_team_spec(_plan_bound_spec())
        service.bind_team_spec_lookup(store)
        session = await service.get_session(parent.id)

        bound = await service.bind_team_spec(parent.id, ref, expected_session=session)

    async with _open_work_store(tmp_path) as reopened_work, _open_team_store(tmp_path) as reopened_store:
        reopened_service = CrewSessionService(
            work_item_store=reopened_work, chat_thread_store=ChatThreadStore(tmp_path / "threads.db"),
        )
        reopened_service.bind_team_spec_lookup(reopened_store)

        parent_row = await _row(reopened_work, parent.id)
        child_row = await _row(reopened_work, _VECTOR_CHILD_ID)
        recovery = await reopened_service.get_recovery(parent.id)
        assert bound.team_spec_ref == ref
        assert await reopened_service.get_team_binding(parent.id) == bound
        assert (await reopened_store.get_team_spec(ref)).content_ref() == ref
        assert recovery is not None and recovery.plan is not None
        assert recovery.plan.plan_hash == _VECTOR_PLAN_HASH
        assert [child.row_hash for child in recovery.plan.children] == [_VECTOR_ROW_HASH]
        assert recovery.model_dump(mode="json") == before_recovery
        assert _canonical(child_row.metadata) == before_child
        assert set(parent_row.metadata) - set(before_parent) == {_KEY}
        assert parent_row.metadata == {**before_parent, _KEY: bound.model_dump(mode="json")}
        assert len(_canonical(parent_row.metadata[_KEY]).encode("utf-8")) < 1024


async def test_unbound_session_metadata_is_untouched_by_wiring_and_reads(tmp_path: Path) -> None:
    root = tmp_path / "unbound"
    root.mkdir()
    async with _open_work_store(root) as work, _open_team_store(root) as store:
        parent, service, _ = await _new_session(work, root)
        before = _canonical((await _row(work, parent.id)).metadata)

        service.bind_team_spec_lookup(store)
        binding = await service.get_team_binding(parent.id)
        session = await service.get_session(parent.id)

        after = await _row(work, parent.id)
        assert binding is None and session is not None
        assert _canonical(after.metadata) == before
        assert _KEY not in after.metadata


async def test_finalization_publishes_a_bound_session_and_keeps_the_binding(tmp_path: Path) -> None:
    """Load, recovery CAS, adoption, finalize, crash, resume and publish -- with a binding on the parent."""
    opened: list[ElasticTeamStore] = []
    bindings: list[CrewElasticTeamBinding] = []

    async def bind(parent: Any, service: Any) -> None:
        store = ElasticTeamStore(
            db_path=str(tmp_path / "elastic_teams.db"), connection_factory=SQLiteConnectionFactory(),
        )
        await store.start()
        opened.append(store)
        ref = await store.put_team_spec(_spec())  # bill-only: it names no plan_hash
        service.bind_team_spec_lookup(store)
        session = await service.get_session(parent.id)
        bindings.append(await service.bind_team_spec(parent.id, ref, expected_session=session))

    harness: Any = None
    try:
        harness = await _durable_finalization_harness(
            tmp_path, child_count=2, output_size=128, after_session=bind,
        )
        fault = RuntimeError("synthesis-crash")
        failing = _checkpoint_fault_finalizer(harness, stage="synthesis", fault=fault)

        with pytest.raises(RuntimeError, match=r"^synthesis-crash$") as raised:
            await failing.resume(harness.parent.id)
        assert raised.value is fault
        crashed = await harness.service.get_recovery(harness.parent.id)
        assert crashed is not None and crashed.phase == "synthesized"
        completed = await _checkpoint_fault_finalizer(harness, stage=None, fault=None).resume(harness.parent.id)

        assert completed.state == "done" and completed.completed is True
        session = await harness.service.get_session(harness.parent.id)
        published = await harness.service.get_recovery(harness.parent.id)
        assert session is not None and session.state == "done"
        assert published is not None and published.phase == "published"
        assert len(harness.outcome.calls) == 2 and len(harness.synth.requests) == 1
        binding = bindings[0]
        assert await harness.service.get_team_binding(harness.parent.id) == binding
        row = await _row(harness.stores.work, harness.parent.id)
        assert _canonical(row.metadata[_KEY]) == _canonical(binding.model_dump(mode="json"))
    finally:
        for store in opened:
            await store.stop()
        if harness is not None:
            await harness.stores_generator.aclose()


async def test_retry_barrier_tolerates_a_bound_session(stores: room._Stores, tmp_path: Path) -> None:  # noqa: F811
    parent, _thread, service = await room._session_parent(stores)
    async with _open_team_store(tmp_path) as store:
        ref = await store.put_team_spec(_spec())
        service.bind_team_spec_lookup(store)
        session = await service.get_session(parent.id)
        bound = await service.bind_team_spec(parent.id, ref, expected_session=session)
    child = await room._child(stores, parent_id=parent.id, child_id="bound-child")
    session = await service.get_session(parent.id)
    executing = await service.transition_session(parent.id, "executing", expected_revision=session.revision)
    plan = _build_adopted_recovery_plan(parent.id, (child,))
    await service.adopt_recovery_plan(
        parent.id, expected_session=executing, expected_recovery=None, plan=plan, expected_children=(child,),
    )
    session = await service.get_session(parent.id)
    recovery = await service.get_recovery(parent.id)
    assert session is not None and recovery is not None and recovery.phase == "executing"
    parent_row = await _row(stores.work, parent.id)
    assert parent_row.metadata[_KEY] == bound.model_dump(mode="json")
    target = session.model_dump(mode="json")
    target.update(
        revision=session.revision + 1, state="blocked_needs_captain", previous_state="executing",
        blocked_reason="crew_worker_unavailable", blocked_since=400.0, transitioned_at=400.0,
    )
    checkpoint = recovery.model_dump(mode="json")
    checkpoint["last_error_code"] = "crew_worker_unavailable"

    updated = await _owned_merge(
        stores.work, service, parent.id, {"crew_session": target, "crew_recovery": checkpoint},
        expected_work_type="crew_session", expected_status="in_progress", new_status="blocked",
        source="crew_session_retry_failure", retry_barrier=WorkItemRetryBarrier(parent_row, (child,)),
    )

    assert updated is not None and updated.status == "blocked"
    assert updated.metadata[_KEY] == bound.model_dump(mode="json")
    assert (await _row(stores.work, parent.id)).metadata[_KEY] == bound.model_dump(mode="json")


async def test_initialize_session_is_idempotent_on_a_bound_session(tmp_path: Path) -> None:
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        parent, service, session = await _new_session(work, tmp_path)
        ref = await store.put_team_spec(_spec())
        service.bind_team_spec_lookup(store)
        bound = await service.bind_team_spec(parent.id, ref, expected_session=session)
        before = (await _row(work, parent.id)).to_dict()

        again = await service.initialize_session(
            parent.id,
            session.thread_id,
            goal="Produce a durable result",
            origin="captain",
            originator_id="captain",
            facilitator_id="facilitator-1",
            owner_ids=["facilitator-1", "agent-1"],
            success_criteria=["Result is complete"],
            expected_deliverable="A report",
        )

        assert again == session
        assert await service.get_team_binding(parent.id) == bound
        assert (await _row(work, parent.id)).to_dict() == before


# --------------------------------------------------------------------------------------
# 6. Every precondition refuses before any write
# --------------------------------------------------------------------------------------

_PRECONDITION_CASES = [
    ("lookup_unbound", "crew_session_team_lookup_unavailable"),
    ("malformed_ref", "crew_session_team_spec_ref_invalid"),
    ("unknown_ref", "crew_session_team_spec_not_found"),
    ("stale_session", "crew_session_revision_conflict"),
    ("executing_session", "crew_session_team_binding_state_invalid"),
    ("provisioning_marker", "crew_session_team_binding_state_invalid"),
    ("plan_hash_without_recovery", "crew_session_team_plan_mismatch"),
    ("plan_hash_differs_from_installed", "crew_session_team_plan_mismatch"),
]


async def _arrange_refusal(
    case: str, work: WorkItemStore, store: ElasticTeamStore, root: Path,
) -> tuple[WorkItem, CrewSessionService, str, Any]:
    """The parent, service, reference and expected session whose ``bind_team_spec`` call must refuse."""
    if case == "provisioning_marker":
        parent, service, session = await _new_session_during_provisioning(work, root)
    else:
        parent, service, session = await _new_session(work, root)
    ref = await store.put_team_spec(_spec())
    if case != "lookup_unbound":
        service.bind_team_spec_lookup(store)
    if case == "malformed_ref":
        return parent, service, "NOT-A-SHA256-REFERENCE", session
    if case == "unknown_ref":
        return parent, service, "d" * 64, session
    if case in ("stale_session", "executing_session"):
        executing = await service.transition_session(parent.id, "executing", expected_revision=session.revision)
        return parent, service, ref, (session if case == "stale_session" else executing)
    if case == "plan_hash_without_recovery":
        return parent, service, await store.put_team_spec(_plan_bound_spec()), session
    if case == "plan_hash_differs_from_installed":
        await _install_vector_plan(service, parent.id, session)
        other = await store.put_team_spec(_plan_bound_spec("c" * 64))
        return parent, service, other, await service.get_session(parent.id)
    return parent, service, ref, session


@pytest.mark.parametrize(("case", "code"), _PRECONDITION_CASES, ids=[case for case, _ in _PRECONDITION_CASES])
async def test_bind_preconditions_refuse_without_mutation(case: str, code: str, tmp_path: Path) -> None:
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        parent, service, ref, expected_session = await _arrange_refusal(case, work, store, tmp_path)
        before = (await _row(work, parent.id)).to_dict()

        with pytest.raises(ValueError, match=f"^{code}$"):
            await service.bind_team_spec(parent.id, ref, expected_session=expected_session)

        assert (await _row(work, parent.id)).to_dict() == before
        assert _KEY not in (await _row(work, parent.id)).metadata


# --------------------------------------------------------------------------------------
# 7-8. Write-once, including under a race
# --------------------------------------------------------------------------------------


async def test_rebinding_is_idempotent_and_a_different_spec_conflicts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        parent, service, session = await _new_session(work, tmp_path)
        first_ref = await store.put_team_spec(_spec())
        second_ref = await store.put_team_spec(_spec(revision=2))
        service.bind_team_spec_lookup(store)

        with caplog.at_level(logging.INFO, logger=_SESSION_LOGGER):
            first = await service.bind_team_spec(parent.id, first_ref, expected_session=session)
            after_first = (await _row(work, parent.id)).to_dict()
            again = await service.bind_team_spec(parent.id, first_ref, expected_session=session)
            with pytest.raises(ValueError, match="^crew_session_team_binding_conflict$"):
                await service.bind_team_spec(parent.id, second_ref, expected_session=session)

        assert first_ref != second_ref
        assert again == first
        assert (await _row(work, parent.id)).to_dict() == after_first  # neither later call wrote anything
        assert await service.get_team_binding(parent.id) == first
        bound_lines = [r for r in caplog.records if "AD-1286: crew session parent=" in r.getMessage()]
        assert len(bound_lines) == 1  # logged once, for the write that happened


async def test_concurrent_binds_leave_exactly_one_binding(tmp_path: Path) -> None:
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        parent, service, session = await _new_session(work, tmp_path)
        refs = [await store.put_team_spec(_spec()), await store.put_team_spec(_spec(revision=2))]
        service.bind_team_spec_lookup(store)

        results = await asyncio.gather(
            *(service.bind_team_spec(parent.id, ref, expected_session=session) for ref in refs),
            return_exceptions=True,
        )

        winners = [r for r in results if isinstance(r, CrewElasticTeamBinding)]
        losers = [r for r in results if isinstance(r, BaseException)]
        assert len(winners) == 1 and len(losers) == 1
        assert type(losers[0]) is ValueError and str(losers[0]) == "crew_session_team_binding_conflict"
        assert await service.get_team_binding(parent.id) == winners[0]
        assert winners[0].team_spec_ref in refs


async def test_concurrent_identical_binds_on_a_planned_session_both_succeed(tmp_path: Path) -> None:
    """F7: on a planned (owned-steps) session a racing writer makes the loser's owned binding stale.

    The loser's merge then fails with ``owned_steps_plan_conflict`` rather than ``work_item_metadata_conflict``;
    both are retried (each pass re-reads), so an identical bind sees the winner's binding and returns it.
    """
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        parent, service, session = await _new_session(work, tmp_path)
        await _install_vector_plan(service, parent.id, session)  # planned => the owned-binding CAS path
        ref = await store.put_team_spec(_spec())
        service.bind_team_spec_lookup(store)
        session = await service.get_session(parent.id)

        results = await asyncio.gather(
            service.bind_team_spec(parent.id, ref, expected_session=session),
            service.bind_team_spec(parent.id, ref, expected_session=session),
        )

        assert results[0] == results[1] and results[0].team_spec_ref == ref
        assert (await _row(work, parent.id)).metadata[_KEY] == results[0].model_dump(mode="json")


async def test_concurrent_different_binds_on_a_planned_session_leave_one_binding(tmp_path: Path) -> None:
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        parent, service, session = await _new_session(work, tmp_path)
        await _install_vector_plan(service, parent.id, session)
        refs = [await store.put_team_spec(_spec()), await store.put_team_spec(_spec(revision=2))]
        service.bind_team_spec_lookup(store)
        session = await service.get_session(parent.id)

        results = await asyncio.gather(
            *(service.bind_team_spec(parent.id, ref, expected_session=session) for ref in refs),
            return_exceptions=True,
        )

        winners = [r for r in results if isinstance(r, CrewElasticTeamBinding)]
        losers = [r for r in results if isinstance(r, BaseException)]
        assert len(winners) == 1 and len(losers) == 1
        assert type(losers[0]) is ValueError and str(losers[0]) == "crew_session_team_binding_conflict"
        assert await service.get_team_binding(parent.id) == winners[0]
        assert (await _row(work, parent.id)).metadata[_KEY] == winners[0].model_dump(mode="json")


# --------------------------------------------------------------------------------------
# 9. install_recovery_plan alone cannot replace the plan; a governed replan can (see the replan test)
# --------------------------------------------------------------------------------------


async def test_governed_replan_leaves_the_binding_and_rebind_reports_plan_mismatch(
    owned_projection_case: Any, tmp_path: Path
) -> None:
    """F2: the plan check is a bind-time admission check, not a guarantee that the plan stays.

    A governed ``replan_unstarted`` (the real owned-steps HTTP harness) installs a different plan on a
    ``discussing`` session. The binding is left exactly as it was, so a repeat bind of the same reference now
    reports ``crew_session_team_plan_mismatch`` -- and AD-1288's commission admission is what must compare
    ``spec.process.plan_hash`` with the current plan.
    """
    case = owned_projection_case
    service = case.state.service
    parent_id = await case.managed_parent(canonical=True)  # created and adopted: discussing, plan installed
    async with _open_team_store(tmp_path) as store:
        service.bind_team_spec_lookup(store)  # the harness builds CrewSessionService directly, with no lookup
        planned = await service.get_recovery(parent_id)
        assert planned is not None and planned.plan is not None
        original_plan_hash = planned.plan.plan_hash
        ref = await store.put_team_spec(_plan_bound_spec(original_plan_hash))
        bound = await service.bind_team_spec(parent_id, ref, expected_session=await service.get_session(parent_id))
        bound_value = _canonical((await _row(case.state.store, parent_id)).metadata[_KEY])

        await case.apply(parent_id, "replan_unstarted", "ad1286-replan")

        replanned = await service.get_recovery(parent_id)
        assert replanned is not None and replanned.plan is not None
        assert replanned.plan.plan_hash != original_plan_hash  # the governed replan really replaced the plan
        assert await service.get_team_binding(parent_id) == bound  # ... and left the binding alone
        assert _canonical((await _row(case.state.store, parent_id)).metadata[_KEY]) == bound_value
        with pytest.raises(ValueError, match="^crew_session_team_plan_mismatch$"):
            await service.bind_team_spec(parent_id, ref, expected_session=await service.get_session(parent_id))
        assert _canonical((await _row(case.state.store, parent_id)).metadata[_KEY]) == bound_value


async def test_install_recovery_plan_refuses_a_second_plan_after_binding(tmp_path: Path) -> None:
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        parent, service, session = await _new_session(work, tmp_path)
        await _install_vector_plan(service, parent.id, session)
        ref = await store.put_team_spec(_plan_bound_spec())
        service.bind_team_spec_lookup(store)
        session = await service.get_session(parent.id)
        bound = await service.bind_team_spec(parent.id, ref, expected_session=session)
        recovery = await service.get_recovery(parent.id)
        other_plan, other_children = _build_derived_recovery_plan(
            parent.id, [WorkItemSpec(spec_id="spec-other", title="Other")], created_by="facilitator-1",
        )
        before = (await _row(work, parent.id)).to_dict()

        with pytest.raises(ValueError, match="^crew_recovery_plan_conflict$"):
            await service.install_recovery_plan(
                parent.id,
                expected_session=session,
                expected_recovery=recovery,
                plan=other_plan,
                children=other_children,
            )

        assert other_plan.plan_hash != _VECTOR_PLAN_HASH
        assert (await _row(work, parent.id)).to_dict() == before
        assert await work.get_work_item(other_children[0].id) is None
        assert await service.get_team_binding(parent.id) == bound
        current = await service.get_recovery(parent.id)
        assert current is not None and current.plan is not None and current.plan.plan_hash == _VECTOR_PLAN_HASH


# --------------------------------------------------------------------------------------
# 10. A malformed stored binding is refused, never repaired
# --------------------------------------------------------------------------------------

_GOOD_BINDING = {"version": 1, "team_spec_ref": "a" * 64, "team_id": "review-team", "revision": 1}
_MALFORMED_BINDINGS = {
    "not_a_mapping": "bound",
    "empty_mapping": {},
    "uppercase_ref": {**_GOOD_BINDING, "team_spec_ref": "A" * 64},
    "version_two": {**_GOOD_BINDING, "version": 2},
    "extra_key": {**_GOOD_BINDING, "blob": "x"},
}


@pytest.mark.parametrize("malformed", list(_MALFORMED_BINDINGS.values()), ids=list(_MALFORMED_BINDINGS))
async def test_get_team_binding_rejects_a_malformed_stored_binding(malformed: Any, tmp_path: Path) -> None:
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        parent, service, session = await _new_session(work, tmp_path)
        await _install_vector_plan(service, parent.id, session)  # planned => the owned-steps write path
        session = await service.get_session(parent.id)
        live = await _row(work, parent.id)
        await _owned_merge(
            work, service, parent.id, {_KEY: malformed},
            expected={"crew_session": live.metadata["crew_session"], "crew_recovery": live.metadata["crew_recovery"]},
            expected_absent_keys=frozenset({_KEY}),
            expected_work_type="crew_session", expected_status="open", expected_assigned_to="facilitator-1",
            source="test_malformed_team_binding",
        )
        service.bind_team_spec_lookup(store)
        ref = await store.put_team_spec(_plan_bound_spec())
        stored = (await _row(work, parent.id)).to_dict()

        with pytest.raises(ValueError, match="^crew_session_team_binding_invalid$"):
            await service.get_team_binding(parent.id)
        with pytest.raises(ValueError, match="^crew_session_team_binding_invalid$"):
            await service.bind_team_spec(parent.id, ref, expected_session=session)

        assert (await _row(work, parent.id)).to_dict() == stored  # refused, and never overwritten


# --------------------------------------------------------------------------------------
# 10b. An unverifiable binding is refused on read (review round 1, F3)
# --------------------------------------------------------------------------------------


async def _write_binding_without_the_service(work: WorkItemStore, parent_id: str, value: Any) -> None:
    """Land a ``crew_elastic_team`` value on an UNPLANNED session the way the platform permits (F3 / #1419)."""
    live = await _row(work, parent_id)
    await work.merge_work_item_metadata(
        parent_id,
        {_KEY: value},
        expected={"crew_session": live.metadata["crew_session"]},
        expected_absent_keys=frozenset({_KEY, "crew_recovery"}),
        expected_work_type="crew_session",
        expected_status="open",
        expected_assigned_to="facilitator-1",
        source="test_unverifiable_team_binding",
    )


async def test_get_team_binding_refuses_a_binding_to_an_unknown_spec(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        parent, service, _session = await _new_session(work, tmp_path)
        service.bind_team_spec_lookup(store)
        await _write_binding_without_the_service(work, parent.id, {**_GOOD_BINDING, "team_spec_ref": "d" * 64})

        with caplog.at_level(logging.ERROR, logger=_SESSION_LOGGER):
            with pytest.raises(ValueError, match="^crew_session_team_binding_invalid$"):
                await service.get_team_binding(parent.id)

        refusals = [r for r in caplog.records if "cannot confirm" in r.getMessage() and parent.id in r.getMessage()]
        assert len(refusals) == 1 and "d" * 64 in refusals[0].getMessage()


@pytest.mark.parametrize(
    ("field", "value"),
    [pytest.param("revision", 2, id="revision"), pytest.param("team_id", "other-team", id="team-id")],
)
async def test_get_team_binding_refuses_a_binding_with_mismatched_revision(
    tmp_path: Path, field: str, value: Any
) -> None:
    """A binding whose ``revision`` (or ``team_id``) differs from the spec its reference names is not the spec's."""
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        parent, service, _session = await _new_session(work, tmp_path)
        ref = await store.put_team_spec(_spec())
        service.bind_team_spec_lookup(store)
        stored_binding = CrewElasticTeamBinding.for_spec(_spec()).model_dump(mode="json")
        assert stored_binding["team_spec_ref"] == ref
        await _write_binding_without_the_service(work, parent.id, {**stored_binding, field: value})

        with pytest.raises(ValueError, match="^crew_session_team_binding_invalid$"):
            await service.get_team_binding(parent.id)


async def test_get_team_binding_without_a_lookup_returns_the_strictly_parsed_binding(tmp_path: Path) -> None:
    """With no lookup bound there is nothing to verify against: the strictly parsed value is returned."""
    async with _open_work_store(tmp_path) as work:
        parent, service, _session = await _new_session(work, tmp_path)  # no lookup is bound
        await _write_binding_without_the_service(work, parent.id, _GOOD_BINDING)

        binding = await service.get_team_binding(parent.id)

        assert binding == CrewElasticTeamBinding.model_validate(_GOOD_BINDING)


async def test_unplanned_crew_keys_accept_a_generic_merge_platform_property(tmp_path: Path) -> None:
    """Pins today's platform property recorded in #1419; when that item is fixed, this test changes on purpose.

    Before a plan is installed the in-process ``merge_work_item_metadata`` primitive accepts any ``crew_*``
    key on a crew-session parent -- ``crew_elastic_team`` and ``crew_session``'s own key name (with an unchanged
    value) alike -- so the key is exactly as protected as the CrewSession contract key itself. Once a plan is
    installed, owned steps refuse the same merges. AD-1286 does not change either half of this.
    """
    guard: dict[str, Any] = {
        "expected_work_type": "crew_session",
        "expected_status": "open",
        "expected_assigned_to": "facilitator-1",
        "source": "test_platform_property",
    }
    async with _open_work_store(tmp_path) as work:
        parent, service, session = await _new_session(work, tmp_path)
        session_raw = (await _row(work, parent.id)).metadata["crew_session"]

        accepted_binding = await work.merge_work_item_metadata(parent.id, {_KEY: _GOOD_BINDING}, **guard)
        accepted_session = await work.merge_work_item_metadata(parent.id, {"crew_session": session_raw}, **guard)

        assert accepted_binding is not None and accepted_binding.metadata[_KEY] == _GOOD_BINDING
        assert accepted_session is not None and accepted_session.metadata["crew_session"] == session_raw
        await _install_vector_plan(service, parent.id, session)
        with pytest.raises(owned_steps.OwnedStepsError, match="^owned_steps_write_reserved$"):
            await work.merge_work_item_metadata(parent.id, {_KEY: {**_GOOD_BINDING, "revision": 2}}, **guard)
        with pytest.raises(owned_steps.OwnedStepsError, match="^owned_steps_write_reserved$"):
            await work.merge_work_item_metadata(parent.id, {"crew_session": session_raw}, **guard)
        assert (await _row(work, parent.id)).metadata[_KEY] == _GOOD_BINDING  # the refused write changed nothing


# --------------------------------------------------------------------------------------
# Additional boundary tests for the new branches (beyond the ten specified tests)
# --------------------------------------------------------------------------------------


class _SkippedValidationLookup:
    """A ``TeamSpecLookup`` whose spec was built without validation (a ``model_copy(update=...)``).

    The ``review`` slot is dropped while ``analyse`` still names it as its adjudicator, so the copy no longer
    validates (``elastic_team_merge_invalid``) yet carries a valid team id and revision, canonicalises, and has a
    content reference of its own. ``CrewElasticTeamBinding.for_spec`` and the reference check would both accept
    it: only revalidating the instance can refuse it. (An earlier version built the copy with ``revision=0``,
    which ``for_spec`` rejects by itself, so it kept passing with the revalidation removed -- the mutation
    check found that.)
    """

    def __init__(self) -> None:
        valid = _spec()
        self.spec = valid.model_copy(update={"slots": tuple(slot for slot in valid.slots if slot.slot_id != "review")})

    async def get_team_spec(self, team_spec_ref: str) -> Any:
        return self.spec


async def test_bind_team_spec_revalidates_what_the_lookup_returns(tmp_path: Path) -> None:
    """F4: a lookup that hands back an instance which no longer validates is refused before anything is written."""
    async with _open_work_store(tmp_path) as work:
        parent, service, session = await _new_session(work, tmp_path)
        lookup = _SkippedValidationLookup()
        service.bind_team_spec_lookup(lookup)
        before = (await _row(work, parent.id)).to_dict()

        with pytest.raises(ValidationError, match="elastic_team_merge_invalid"):
            await service.bind_team_spec(parent.id, lookup.spec.content_ref(), expected_session=session)

        assert (await _row(work, parent.id)).to_dict() == before


async def test_cancelled_spec_write_cannot_be_bound(tmp_path: Path) -> None:
    """R2-1 consumer: a spec write cancelled mid-rollback must not let a session bind to the uncommitted spec.

    The put dies on its second slot insert and is cancelled while its ROLLBACK is awaited, so its transaction is
    still open when the write is abandoned. ``bind_team_spec`` asks the SAME store for the spec and must be told it
    does not exist: before R4 the one shared connection still showed the uncommitted spec, and the binding -- a
    durable write on the parent row -- persisted to a spec that was never stored. Reopening the store changes nothing.
    """
    async with _open_work_store(tmp_path) as work:
        parent, service, session = await _new_session(work, tmp_path)
        factory = _FaultyFactory()
        team_store = ElasticTeamStore(db_path=str(tmp_path / "elastic_teams.db"), connection_factory=factory)
        await team_store.start()
        entered, release = asyncio.Event(), asyncio.Event()
        try:
            service.bind_team_spec_lookup(team_store)
            ref = _spec().content_ref()
            factory.arm(fail_slot_insert=True, rollback="gated", entered=entered, release=release)
            write = asyncio.create_task(team_store.put_team_spec(_spec()))
            await asyncio.wait_for(entered.wait(), timeout=10)  # the put failed and is inside its ROLLBACK
            write.cancel()
            with pytest.raises(asyncio.CancelledError):
                await write

            with pytest.raises(ValueError, match="^crew_session_team_spec_not_found$"):
                await service.bind_team_spec(parent.id, ref, expected_session=session)
            assert _KEY not in (await _row(work, parent.id)).metadata

            await team_store.stop()
            await team_store.start()  # reopened: the cancelled write left nothing behind
            with pytest.raises(ValueError, match="^crew_session_team_spec_not_found$"):
                await service.bind_team_spec(parent.id, ref, expected_session=session)
            assert _KEY not in (await _row(work, parent.id)).metadata
        finally:
            release.set()
            await team_store.stop()


class _MarkerRaceStore:
    """Delegates to the real store; the binding's first merge is preceded by a provisioning marker landing."""

    def __init__(self, inner: WorkItemStore, marker: dict[str, Any]) -> None:
        self._inner = inner
        self._marker = marker
        self.raced = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def merge_work_item_metadata(self, work_item_id: str, patch: dict[str, Any], **kwargs: Any) -> WorkItem | None:
        if _KEY in patch and not self.raced:
            self.raced = True  # land the marker AFTER the binding read the parent and BEFORE its CAS
            live = await _row(self._inner, work_item_id)
            await self._inner.merge_work_item_metadata(
                work_item_id,
                {"crew_provisioning": self._marker},
                expected={"crew_session": live.metadata["crew_session"]},
                expected_work_type="crew_session",
                expected_status="open",
                expected_assigned_to="facilitator-1",
                source="test_provisioning_marker_race",
            )
        return await self._inner.merge_work_item_metadata(work_item_id, patch, **kwargs)


async def test_provisioning_marker_written_between_read_and_cas_refuses_the_bind(tmp_path: Path) -> None:
    """S1: ``crew_provisioning`` is part of the CAS, so a marker that lands after the read cannot be bound over.

    The first attempt read a parent with no marker; the marker lands before its merge. Without the key in
    ``expected_absent_keys`` that merge would succeed and bind a session that has just entered provisioning.
    """
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        parent, _service, session = await _new_session(work, tmp_path)
        racing = _MarkerRaceStore(work, _provisioning_marker())
        service = CrewSessionService(
            work_item_store=racing,  # type: ignore[arg-type]
            chat_thread_store=ChatThreadStore(tmp_path / "threads.db"),
            clock=_Clock(300.0),
        )
        service.bind_team_spec_lookup(store)
        ref = await store.put_team_spec(_spec())

        with pytest.raises(ValueError, match="^crew_session_team_binding_state_invalid$"):
            await service.bind_team_spec(parent.id, ref, expected_session=session)

        stored = await _row(work, parent.id)
        assert racing.raced and "crew_provisioning" in stored.metadata
        assert _KEY not in stored.metadata


async def test_bind_team_spec_lookup_refuses_none_and_a_second_binding(tmp_path: Path) -> None:
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        _parent, service, _session = await _new_session(work, tmp_path)

        with pytest.raises(ValueError, match="^crew_session_team_lookup_binding_invalid$"):
            service.bind_team_spec_lookup(None)  # type: ignore[arg-type]
        service.bind_team_spec_lookup(store)
        with pytest.raises(ValueError, match="^crew_session_team_lookup_binding_invalid$"):
            service.bind_team_spec_lookup(store)


async def test_unknown_or_uninitialized_parents_have_no_binding_and_refuse_to_bind(tmp_path: Path) -> None:
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        _parent, service, session = await _new_session(work, tmp_path)
        bare = await _create_crew_parent(work, parent_id="bare-parent", title="No session yet")
        ref = await store.put_team_spec(_spec())
        service.bind_team_spec_lookup(store)

        assert await service.get_team_binding("missing-parent") is None
        assert await service.get_team_binding(bare.id) is None
        with pytest.raises(ValueError, match="^crew_session_parent_not_found$"):
            await service.bind_team_spec("missing-parent", ref, expected_session=session)
        with pytest.raises(ValueError, match="^crew_session_not_initialized$"):
            await service.bind_team_spec(bare.id, ref, expected_session=session)
        assert _KEY not in (await _row(work, bare.id)).metadata


class _MisbehavingMergeStore:
    """Delegates to the real store; only the binding's metadata merge misbehaves (a ``_Fake`` seam)."""

    def __init__(self, inner: WorkItemStore, mode: str) -> None:
        self._inner = inner
        self._mode = mode
        self.merge_calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def merge_work_item_metadata(self, work_item_id: str, patch: dict[str, Any], **kwargs: Any) -> WorkItem | None:
        if _KEY not in patch:
            return await self._inner.merge_work_item_metadata(work_item_id, patch, **kwargs)
        self.merge_calls += 1
        if self._mode == "always_conflicts":
            raise ValueError("work_item_metadata_conflict")
        if self._mode == "always_plan_conflicts":
            raise owned_steps.OwnedStepsError("owned_steps_plan_conflict")
        if self._mode == "other_error":
            raise ValueError("work_item_state_conflict")
        if self._mode == "row_vanishes":
            return None
        written = await self._inner.merge_work_item_metadata(work_item_id, patch, **kwargs)
        assert written is not None
        return dataclasses.replace(
            written, metadata={**written.metadata, _KEY: {**patch[_KEY], "revision": patch[_KEY]["revision"] + 1}},
        )


@pytest.mark.parametrize(
    ("mode", "code", "merge_calls"),
    [
        # F7: three attempts, each re-reading and re-deciding, then the LAST conflict is re-raised as it was
        # (this used to pin ``crew_session_team_binding_conflict`` after two attempts)
        ("always_conflicts", "work_item_metadata_conflict", 3),
        ("always_plan_conflicts", "owned_steps_plan_conflict", 3),
        ("other_error", "work_item_state_conflict", 1),
        ("row_vanishes", "crew_session_team_binding_failed", 1),
        ("store_disagrees", "crew_session_team_binding_failed", 1),
    ],
)
async def test_bind_failure_modes_fail_closed(mode: str, code: str, merge_calls: int, tmp_path: Path) -> None:
    async with _open_work_store(tmp_path) as work, _open_team_store(tmp_path) as store:
        parent, _service, session = await _new_session(work, tmp_path)
        faulty = _MisbehavingMergeStore(work, mode)
        service = CrewSessionService(
            work_item_store=faulty,  # type: ignore[arg-type]
            chat_thread_store=ChatThreadStore(tmp_path / "threads.db"),
            clock=_Clock(300.0),
        )
        service.bind_team_spec_lookup(store)
        ref = await store.put_team_spec(_spec())

        with pytest.raises(ValueError, match=f"^{code}$"):
            await service.bind_team_spec(parent.id, ref, expected_session=session)

        assert faulty.merge_calls == merge_calls  # a conflict is re-read and retried, three attempts at most
