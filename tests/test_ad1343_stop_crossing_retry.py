"""AD-1343 N1 (#1595): a crew session stopped by the Captain's order can be finished after the lift.

S1 ended such a session ``blocked_needs_captain`` / ``recovery_integrity_conflict``, which the Captain could not retry.
N1 raises a transient error at the stop checks of the owner's resume, so the owner's recovery loop retries it with
backoff. These tests cross the whole chain on real parts: a real ``AgentStopService`` over ``agent_stops.db`` -> the
real ``CrewOrchestrator._run_owned_parent`` and its recovery loop -> the real verifier, synthesizer and finalizer over
real stores -> the real authorizer, through ``CrewSessionService.open_or_resume(retry_blocked=True)``:

- X12  a stopped facilitator or producer: blocked ``recovery_retry_exhausted`` after the bounded retries -> lift -> the
       Captain's retry is authorized -> the owner finishes the session;
- X13  the order is lifted during the backoff: the session finishes by itself, with no Captain action;
- X14  F-177: a correction admitted just before the order keeps its permit, and the session still ends blocked
       ``recovery_integrity_conflict``, which the Captain cannot retry (a retry would replay the permit as a defect).

One ``CrewSessionService`` owns the session, the finalizer's checkpoints and the authorizer: the store binds a single
owned-steps owner (``CrewSessionService.register_owned_steps_component``). Nothing sleeps: the owner's clock and sleep
are injected, and every owner run is bounded with ``asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.crew_orchestrator import CrewOrchestrator
from probos.cognitive.crew_session import CrewRecoveryTransientError, CrewSessionService, _build_adopted_recovery_plan
from probos.config import AgenticDispatchConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.workforce import CrewSessionParentCreate
from tests.test_ad1125_room_bound_execution import (
    _Agent as _ExecutionAgent,
    _Clock,
    _Registry as _ExecutionRegistry,
    _StaticOutcomeExecutor,
    _child,
    _crew_executor,
    _runtime as _execution_runtime,
    stores as _execution_stores,
)
from tests.test_ad1126_verified_finalization import _registry_for, _text, _verdict
from tests.test_ad1244_verdict_criteria import _ExecutedSession
from tests.test_ad1343_agent_stop import LIFT_REASON, REASON, _service
from tests.test_ad1343_agent_stop_crew import _BOUND, _CountingLLM
from tests.test_ad1343_stop_crossing_resume import FACILITATOR, FINAL_TEXT, _Rig

MAX_RETRIES = 1
INITIAL_BACKOFF = 2.0


class _CrewTypes:
    """The ontology's crew types: every agent the rig registers is crew, so the Captain's retry can validate the room."""

    def get_crew_agent_types(self) -> set[str]:
        return {"facilitator", "builder", "reviewer"}


@asynccontextmanager
async def _retryable_session(tmp_path: Path) -> AsyncIterator[_ExecutedSession]:
    """``_executed_session`` (``tests/test_ad1244_verdict_criteria.py``), with its session owned by a service wired for
    the Captain's retry: the config (the retry bound), the registry, the ontology and the admission port."""
    generator = _execution_stores.__wrapped__(tmp_path)
    stores = await generator.__anext__()
    try:
        async with stores.admission_port.reserve() as reservation:
            parent = await reservation.create_parent(CrewSessionParentCreate(
                id="crew-session-n1-retry",
                title="Room-bound session",
                description="Room-bound session",
                assigned_to="facilitator-1",
                created_by="captain",
                metadata={},
                created_at=100.0,
                steps=[],
            ))
        thread = stores.chat.create_thread(
            title="Room-bound session", participants=["facilitator-1", "agent-1"], task_id=parent.id,
        )
        service = CrewSessionService(
            work_item_store=stores.work,
            chat_thread_store=stores.chat,
            registry=_registry_for([SimpleNamespace(id="checkpoint-child", assigned_to="agent-1")]),
            ontology=_CrewTypes(),
            config=AgenticDispatchConfig(orchestrator_enabled=True, crew_recovery_max_retries=MAX_RETRIES),
            admission_port=stores.admission_port,
            clock=_Clock(200.0),
        )
        await service.initialize_session(
            parent.id,
            thread.id,
            goal="Produce a room-bound result",
            origin="captain",
            originator_id="captain",
            facilitator_id="facilitator-1",
            owner_ids=["facilitator-1", "agent-1"],
            success_criteria=["Artifact is persisted", "Evidence is durable"],
            expected_deliverable="A persisted report",
        )
        child = await _child(stores, parent_id=parent.id, child_id="checkpoint-child")
        session = await service.get_session(parent.id)
        assert session is not None
        executing = await service.transition_session(parent.id, "executing", expected_revision=session.revision)
        await service.adopt_recovery_plan(
            parent.id, expected_session=executing, expected_recovery=None,
            plan=_build_adopted_recovery_plan(parent.id, (child,)), expected_children=(child,),
        )
        runtime = _execution_runtime(stores, tmp_path)
        runtime.crew_session_service = service
        executor = _crew_executor(
            stores=stores, registry=_ExecutionRegistry({"agent-1": _ExecutionAgent("agent-1")}),
            executor=_StaticOutcomeExecutor(output="Durable child evidence", total_tokens=7),
            runtime=runtime, service=service,
        )
        results = await executor.resume(parent.id)
        assert len(results) == 1 and results[0].status == "done"
        child = await stores.work.get_work_item(child.id)
        assert child is not None
        yield _ExecutedSession(stores, parent, thread, service, child, results)
    finally:
        await generator.aclose()


def _owner(
    rig: _Rig, sleeps: list[float], on_sleep: Callable[[], Awaitable[None]] | None = None,
) -> CrewOrchestrator:
    """The real owner over the rig's one service and its finalizer, with an injected clock and sleep."""
    now = {"value": 1_000.0}
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    config.agentic_dispatch.crew_recovery_max_retries = MAX_RETRIES
    config.agentic_dispatch.crew_recovery_initial_backoff_seconds = INITIAL_BACKOFF
    config.agentic_dispatch.crew_recovery_max_backoff_seconds = 3.0

    async def sleep(delay: float) -> None:
        sleeps.append(delay)
        now["value"] += delay
        if on_sleep is not None:
            await on_sleep()

    return CrewOrchestrator(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=rig.case.stores.work,
        runtime=SimpleNamespace(),
        config=config,
        crew_session_finalizer=rig.finalizer,
        crew_session_service=rig.case.service,
        clock=lambda: now["value"],
        sleep=sleep,
    )


async def _captain_retry(case: _ExecutedSession) -> Any:
    session = await case.service.get_session(case.parent.id)
    assert session is not None
    return await case.service.open_or_resume(
        principal=case.service.captain_principal(),
        goal=session.goal,
        success_criteria=list(session.success_criteria),
        expected_deliverable=session.expected_deliverable,
        requested_thread_id=case.thread.id,
        retry_blocked=True,
    )


# X12
@pytest.mark.parametrize("role", ["facilitator", "producer"])
async def test_a_stopped_session_is_retried_by_the_captain_after_the_lift_and_finishes(tmp_path: Path, role: str) -> None:
    if role == "facilitator":
        judge = [_verdict(True), _verdict(True)]
        code = "synthesis_producer_stopped"
    else:
        judge = [*(_verdict(False, critique="incomplete") for _ in range(4)), _verdict(True), _verdict(True)]
        code = "child_producer_stopped"
    async with _retryable_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(case, tmp_path, stops, TrustNetwork(), judge=judge, synth=[_text(FINAL_TEXT)])
        agent_id = FACILITATOR if role == "facilitator" else rig.producer_id
        record = (await stops.issue_stop(agent_id, reason=REASON)).record

        # Premise: the first resume, made directly, refuses with the transient code and leaves the session verifying.
        with pytest.raises(CrewRecoveryTransientError) as refused:
            await rig.finalizer.resume(rig.parent_id)
        assert refused.value.code == code
        verifying = await case.service.get_session(rig.parent_id)
        assert verifying is not None and verifying.state == "verifying"

        sleeps: list[float] = []
        owner = _owner(rig, sleeps)
        owned = await asyncio.wait_for(owner._run_owned_parent(rig.parent_id), timeout=_BOUND)

        blocked = await case.service.get_session(rig.parent_id)
        recovery = await case.service.get_recovery(rig.parent_id)
        assert owned.completed is False and blocked is not None and recovery is not None
        assert (blocked.state, blocked.blocked_reason) == ("blocked_needs_captain", "recovery_retry_exhausted")
        assert (recovery.last_error_code, recovery.retry_count) == ("recovery_retry_exhausted", MAX_RETRIES)
        assert sleeps == [INITIAL_BACKOFF]  # one bounded backoff, then exhaustion
        assert rig.synth.requests == [] and await rig.synthesis_claim() is None  # nothing synthesized or claimed
        assert len(rig.correction.calls) == 0  # the stopped producer ran nothing
        assert stops.refused_counts(record.stop_id) == {"agentic_run": 3}  # the direct resume and both owner attempts

        lifted = await stops.lift_stop(agent_id, reason=LIFT_REASON)
        assert lifted.refused == {"agentic_run": 3}
        scheduled: list[asyncio.Task[Any]] = []

        def schedule(parent_id: str) -> asyncio.Task[Any]:
            task = asyncio.create_task(owner._run_owned_parent(parent_id))
            scheduled.append(task)
            return task

        case.service.bind_scheduler(schedule)
        retried = await _captain_retry(case)
        assert (retried.state, retried.scheduled) == ("verifying", True)  # the Captain's retry is authorized
        assert len(scheduled) == 1
        finished = await asyncio.wait_for(scheduled[0], timeout=_BOUND)

        done = await case.service.get_session(rig.parent_id)
        assert finished.completed is True and done is not None and done.state == "done"
        assert len(rig.synth.requests) == 1  # the one synthesis, after the lift
        if role == "facilitator":
            assert len(rig.judge.requests) == 2  # the child once (checkpointed before the stop), the final verification once
        else:
            # D12 (F-178, measured): round 0 is judged again at each attempt (three while stopped, one after the retry),
            # then the correction and the final verification once each.
            assert len(rig.judge.requests) == 6 and len(rig.correction.calls) == 1


# X13
async def test_a_stop_lifted_during_the_backoff_lets_the_session_finish_by_itself(tmp_path: Path) -> None:
    async with _retryable_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(case, tmp_path, stops, TrustNetwork(), judge=[_verdict(True), _verdict(True)], synth=[_text(FINAL_TEXT)])
        await stops.issue_stop(FACILITATOR, reason=REASON)
        with pytest.raises(CrewRecoveryTransientError):
            await rig.finalizer.resume(rig.parent_id)  # premise: the session is verifying and its synthesis was refused
        lifts: list[Any] = []

        async def lift_during_backoff() -> None:
            lifts.append(await stops.lift_stop(FACILITATOR, reason=LIFT_REASON))

        sleeps: list[float] = []
        owner = _owner(rig, sleeps, on_sleep=lift_during_backoff)
        finished = await asyncio.wait_for(owner._run_owned_parent(rig.parent_id), timeout=_BOUND)

        done = await case.service.get_session(rig.parent_id)
        assert finished.completed is True and done is not None and done.state == "done"  # no Captain action
        assert sleeps == [INITIAL_BACKOFF] and len(lifts) == 1
        assert lifts[0].refused == {"agentic_run": 2}  # the direct resume and the first owner attempt
        assert (len(rig.judge.requests), len(rig.synth.requests)) == (2, 1)
        assert stops.stop_for(FACILITATOR) is None


# X14 (F-177)
async def test_a_correction_admitted_just_before_the_stop_still_blocks_and_is_not_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    llm = _CountingLLM()
    refute = [_verdict(False, critique="incomplete") for _ in range(2)]
    async with _retryable_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(
            case, tmp_path, stops, TrustNetwork(), judge=refute, synth=[],
            correction=WorkItemAgenticExecutor(llm_client=llm),
        )
        await stops.issue_stop(rig.producer_id, reason=REASON)
        with pytest.raises(CrewRecoveryTransientError):
            await rig.finalizer.resume(rig.parent_id)  # premise: refused before admission; the session is verifying
        await stops.lift_stop(rig.producer_id, reason=LIFT_REASON)

        admit = case.service.admit_correction
        admitted: list[str] = []

        async def admit_then_stop(*args: Any, **kwargs: Any) -> Any:
            # The F-177 window: the real admission records the permit, then the Captain's order lands before the run entry.
            admission = await admit(*args, **kwargs)
            admitted.append(admission.disposition)
            await stops.issue_stop(rig.producer_id, reason=REASON)
            return admission

        monkeypatch.setattr(case.service, "admit_correction", admit_then_stop)
        with caplog.at_level(logging.WARNING):
            owned = await asyncio.wait_for(_owner(rig, [])._run_owned_parent(rig.parent_id), timeout=_BOUND)

        blocked = await case.service.get_session(rig.parent_id)
        assert owned.completed is False and admitted == ["new"]
        assert blocked is not None
        assert (blocked.state, blocked.blocked_reason) == ("blocked_needs_captain", "recovery_integrity_conflict")
        assert llm.calls == []  # the correction never ran
        assert sum("admitted but not executed" in r.getMessage() for r in caplog.records) == 1
        assert len(rig.judge.requests) == 2

        await stops.lift_stop(rig.producer_id, reason=LIFT_REASON)
        with pytest.raises(ValueError, match="crew_session_retry_not_authorized"):
            await _captain_retry(case)
