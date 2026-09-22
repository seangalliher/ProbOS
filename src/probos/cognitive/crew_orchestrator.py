"""AD-867: :class:`CrewOrchestrator` — wire the full crew pipeline behind one
runtime entry point.

**AD-1231 — why a service owns this, and where its authority stops.** Design
Principle 1 is hybrid: agents choose *what to work on*; a deterministic service
owns *durable workflow time*. This module is that service's reference case. It
decides when a durable step runs, in what order, and whether it may run twice —
admission bounds, CAS transitions, crash recovery, exactly-once delivery,
cancellation and drain. Those are guarantees an emergent negotiation cannot
make.

What it must never decide is *which agent is best suited* or *how good the work
is*. Agent selection stays with capability matching and Hebbian routing; quality
stays with the verifier. The bottleneck the no-central-scheduler principle
exists to prevent is one planner becoming the single point of thought — N agents
reasoning concurrently behind a sequencer is not that. A change here that starts
ranking agents or work belongs back in the mesh.

The dormant crew classes (AD-859 executor, AD-860 verifier, AD-861 synthesizer,
AD-864 assignment resolver, AD-865 delegator) each do one stage of a multi-agent
collaboration. This module threads them into a single end-to-end flow:

    resolve -> delegate -> fan-out -> verify -> synthesize

behind ``runtime.crew_orchestrator.run_crew_task(parent_id)``.

**Trigger.** ``maybe_dispatch_crew(parent_id)`` is the gate: it schedules
``run_crew_task`` as a *held* task only when the orchestrator is enabled
(``AgenticDispatchConfig.orchestrator_enabled``, default OFF) and the parent
decomposed into **>1** child. A single-spec parent returns ``None`` so the
caller keeps the existing AD-856 single-agent path (no crew overhead). The live
originating path that *creates* the parent + its ``parent_id``-linked children
is AD-868 (``originate_crew_task``); this AD ships the orchestrator + trigger
gate it will call.

**Honest-degrade.** Legacy task stages are wrapped log-and-degrade (Tier 2): a
failed stage logs *what* failed, *why* it matters, and *what happens next*, then
the pipeline continues with a partial result. Once a parent is authoritatively
classified as a durable crew session, room/service integrity failures propagate
instead of being converted into a valid-looking partial result.

**Parent state glue (AD-867 deviation).** :meth:`CrewSynthesizer._complete_parent`
transitions the parent ``in_progress -> done``; an ``open`` task cannot go
straight to ``done`` under the AD-498 state machine, and neither the executor
nor the dispatcher moves the parent. So the orchestrator transitions the parent
``open -> in_progress`` at the start of ``run_crew_task`` (honest-degrade, only
when ``status == "open"``) so the pipeline can actually complete end-to-end.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import logging
import math
import re
import sqlite3
import time
import uuid
import weakref
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from probos import work_item_steps as owned_steps
from probos.cognitive.crew_executor import (
    CrewWorkerUnavailable,
    SubtaskResult,
    is_untouched_crew_child,
)
from probos.cognitive.crew_synth import SynthesisResult
from probos.cognitive.crew_verdict import criteria_to_json, parse_criteria
from probos.cognitive.crew_verifier import (
    ConvergenceOutcome,
    VerificationVerdict,
)
from probos.consultation.dispatch import WorkItemSpec
from probos.events import EventType

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from probos.cognitive.crew_assignment import CrewAssignmentResolver, CrewWorkerEligibilityResolver
    from probos.cognitive.crew_delegation import CrewDelegator
    from probos.cognitive.crew_executor import CrewTaskExecutor, SubtaskResult
    from probos.cognitive.crew_finalizer import CrewSessionFinalizer
    from probos.cognitive.crew_session import CrewSessionService
    from probos.cognitive.crew_synth import CrewSynthesizer
    from probos.cognitive.crew_verifier import SubtaskVerifier
    from probos.workforce import WorkItem, WorkItemStore

logger = logging.getLogger(__name__)

# ConvergenceOutcome.status — kept in sync with crew_verifier's status vocabulary
# (the synthesizer keys off ``verdict.accepted``, not this string, so it is a
# human-readable marker only).
_STATUS_CONVERGED = "converged"
_STATUS_UNVERIFIED = "unverified"
_PARENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_RECOVERY_BOUNDARY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class _OwnedViewRegistration:
    reference: owned_steps.OwnedStepsViewReference
    view: owned_steps.OwnedStepsView
    presented: bool = False


class _LegacyCorrectionPort:
    def __init__(
        self,
        *,
        store: "WorkItemStore",
        execution: owned_steps.OwnedStepsExecutionPort,
        authority: Callable[..., owned_steps.OwnedStepsAuthority],
        component_allowed: Callable[[object], bool],
    ) -> None:
        self._store = store
        self._execution = execution
        self._authority = authority
        self._component_allowed = component_allowed

    def owns_store(self, store: object) -> bool:
        return store is self._store

    async def admit(
        self,
        parent_id: str,
        *,
        children: tuple["WorkItem", ...],
        thread_id: str,
    ) -> owned_steps.OwnedExecutionLease:
        return await self._execution.admit(
            parent_id,
            children=children,
            thread_id=thread_id,
        )

    async def start(
        self,
        lease: owned_steps.OwnedExecutionLease,
        child_id: str,
        *,
        execution_nonce: str,
    ) -> owned_steps.OwnedStepMutationResult:
        return await self._execution.start(
            lease,
            child_id,
            execution_nonce=execution_nonce,
        )

    async def submit(
        self,
        lease: owned_steps.OwnedExecutionLease,
        submission: owned_steps.OwnedExecutionSubmission,
    ) -> owned_steps.OwnedStepMutationResult:
        return await self._execution.submit(lease, submission)

    async def record_unstarted(
        self,
        lease: owned_steps.OwnedExecutionLease,
        submission: owned_steps.OwnedUnstartedSubmission,
    ) -> owned_steps.OwnedStepMutationResult:
        return await self._execution.record_unstarted(lease, submission)

    async def validate(
        self,
        lease: owned_steps.OwnedExecutionLease,
        permit: owned_steps.OwnedStepExecutionPermit,
    ) -> None:
        if permit.review_attempt_id is None:
            await self._execution.validate(lease, permit)
            return
        if (
            lease.snapshot.control.parent_id != permit.parent_id
            or lease.snapshot.control.incarnation != permit.incarnation
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_execution_scope_denied",
                parent_id=permit.parent_id,
            )
        await self._store.validate_owned_execution_permit(
            permit,
            self._authority(
                self,
                parent_id=permit.parent_id,
                actor_id="crew_orchestrator",
                thread_id=lease.snapshot.control.thread_id,
                role="verifier",
                operation="execution_active",
                token=permit,
            ),
        )

    async def admit_correction(
        self,
        component: object,
        snapshot: owned_steps.OwnedStepsSnapshot,
        child_id: str,
        *,
        reviewer_id: str,
        review_attempt_id: str,
        execution_nonce: str,
    ) -> owned_steps.OwnedStepMutationResult:
        if not self._component_allowed(component):
            raise owned_steps.OwnedStepsError(
                "owned_steps_authority_denied",
                parent_id=snapshot.control.parent_id,
            )
        row = next(
            (
                row
                for row in snapshot.control.rows
                if row.child is not None and row.child.child_id == child_id
            ),
            None,
        )
        if row is None or row.permit is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_correction_conflict",
                parent_id=snapshot.control.parent_id,
            )
        original = await self._store.get_owned_step_evidence(
            snapshot.control.parent_id,
            snapshot.control.incarnation,
            "permit",
            row.permit,
        )
        return await self._store.admit_owned_correction(
            snapshot,
            child_id,
            reviewer_id=reviewer_id,
            review_attempt_id=review_attempt_id,
            execution_nonce=execution_nonce,
            authority=self._authority(
                component,
                parent_id=snapshot.control.parent_id,
                actor_id=reviewer_id,
                thread_id=snapshot.control.thread_id,
                role="verifier",
                operation="admit_correction",
                token=original,
            ),
        )

    async def record_correction(
        self,
        component: object,
        snapshot: owned_steps.OwnedStepsSnapshot,
        correction: owned_steps.OwnedCorrectionResult,
    ) -> owned_steps.OwnedStepMutationResult:
        if not self._component_allowed(component):
            raise owned_steps.OwnedStepsError(
                "owned_steps_authority_denied",
                parent_id=snapshot.control.parent_id,
            )
        return await self._store.record_owned_correction(
            snapshot,
            correction,
            self._authority(
                component,
                parent_id=snapshot.control.parent_id,
                actor_id=correction.reviewer_id,
                thread_id=snapshot.control.thread_id,
                role="verifier",
                operation="record_correction",
                token=correction.permit,
            ),
        )

    async def read_correction(
        self,
        snapshot: owned_steps.OwnedStepsSnapshot,
        permit: owned_steps.OwnedStepExecutionPermit,
    ) -> owned_steps.OwnedCorrectionResult | None:
        return await self._store.read_owned_correction(snapshot, permit)

    def correction_execution_lease(
        self,
        snapshot: owned_steps.OwnedStepsSnapshot,
    ) -> owned_steps.OwnedExecutionLease:
        return owned_steps.OwnedExecutionLease(
            snapshot,
            owned_steps.OwnedStepsAuthority(self),
        )


class CrewOrchestrator:
    """Threads the crew pipeline behind a single ``run_crew_task`` entry point."""

    def __init__(
        self,
        *,
        assignment_resolver: "CrewAssignmentResolver",
        delegator: "CrewDelegator",
        crew_executor: "CrewTaskExecutor",
        verifier: "SubtaskVerifier",
        synthesizer: "CrewSynthesizer",
        work_item_store: "WorkItemStore",
        runtime: Any,
        emit_fn: Any = None,
        config: Any = None,
        decomposer: Any = None,
        crew_session_finalizer: "CrewSessionFinalizer | None" = None,
        crew_session_service: "CrewSessionService | None" = None,
        eligibility_resolver: CrewWorkerEligibilityResolver | None = None,
        owned_human_authorizer: owned_steps.OwnedStepsAuthorizer | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        owner_service = getattr(
            crew_executor,
            "owned_steps_authority_service",
            None,
        )
        if crew_session_service is None and callable(owner_service):
            crew_session_service = owner_service()
        self._assignment_resolver = assignment_resolver
        self._delegator = delegator
        self._crew_executor = crew_executor
        self._verifier = verifier
        self._synthesizer = synthesizer
        self._work_item_store = work_item_store
        self._runtime = runtime
        self._emit_fn = emit_fn
        self._config = config
        # AD-868: plan decomposer for self-originated goals. An injected instance
        # (tests) takes precedence; otherwise one is built lazily from
        # ``runtime.llm_client`` on first use (see :meth:`_get_decomposer`).
        self._decomposer = decomposer
        self._crew_session_finalizer = crew_session_finalizer
        self._crew_session_service = crew_session_service
        self._eligibility_resolver = (
            eligibility_resolver
            if eligibility_resolver is not None
            else getattr(crew_session_service, "worker_eligibility", None)
        )
        self._owned_human_authorizer = owned_human_authorizer
        self._clock = clock
        self._sleep = sleep
        dispatch_config = getattr(config, "agentic_dispatch", None)
        max_active = getattr(dispatch_config, "max_active_crew_sessions", 2)
        self._active_parent_semaphore = asyncio.Semaphore(max(1, int(max_active)))
        self._tasks_by_parent: dict[str, asyncio.Task[SynthesisResult]] = {}
        self._pending_continuations: set[str] = set()
        self._scheduling_open = False
        self._started = False
        self._stopped = False
        self._start_lock = asyncio.Lock()
        self._stop_cleanup_task: asyncio.Task[None] | None = None
        self._lifecycle_generation = 0
        self._admission_generation: int | None = None
        self._task_generations: weakref.WeakKeyDictionary[
            asyncio.Task[SynthesisResult],
            int,
        ] = weakref.WeakKeyDictionary()
        self._owned_principal = object()
        self._owned_components: dict[object, frozenset[str]] = {
            self: frozenset({"owner", "ttl", "verifier"}),
            verifier: frozenset({"verifier"}),
        }
        self._legacy_owned_port: owned_steps.OwnedStepsExecutionPort | None = None
        self._legacy_correction_port: _LegacyCorrectionPort | None = None
        self._owned_view_store = getattr(runtime, "attachment_store", None)
        if self._owned_view_store is None:
            self._owned_view_store = getattr(runtime, "attachments", None)
        if self._owned_view_store is None and getattr(runtime, "config", None) is not None:
            from probos.routers.chat import _get_attachment_store

            self._owned_view_store = _get_attachment_store(runtime)
        self._owned_views: dict[
            tuple[str, str, str],
            OrderedDict[str, _OwnedViewRegistration],
        ] = {}
        execution_port = getattr(crew_executor, "owned_steps_execution_port", None)
        if callable(execution_port):
            port = execution_port()
            owns_store = getattr(port, "owns_store", None)
            if not callable(owns_store) or not owns_store(work_item_store):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_execution_scope_denied"
                )
            self._legacy_owned_port = port
            content_reader = getattr(
                synthesizer,
                "owned_steps_content_reader",
                None,
            )
            if callable(content_reader):
                reader = content_reader()
                if reader is not None:
                    work_item_store.bind_owned_steps_content(reader)
            can_bind_legacy_corrections = False
            if crew_session_service is not None:
                crew_session_service.bind_owned_legacy_authorizer(self)
                crew_session_service.bind_owned_steps_view_authorizer(self)
                crew_session_service.register_owned_steps_component(
                    self,
                    frozenset({"owner", "ttl", "verifier"}),
                )
                can_bind_legacy_corrections = True
            elif (
                not work_item_store.owned_steps_owner_matches(self)
                and not work_item_store.has_owned_steps_owner()
            ):
                work_item_store.bind_owned_steps_owner(self, self)
                can_bind_legacy_corrections = True
            bind_corrections = getattr(
                verifier,
                "bind_owned_steps_correction_port",
                None,
            )
            if callable(bind_corrections) and can_bind_legacy_corrections:
                correction_port = _LegacyCorrectionPort(
                    store=work_item_store,
                    execution=port,
                    authority=self.owned_steps_authority,
                    component_allowed=lambda component: (
                        "verifier"
                        in self._owned_components.get(
                            component,
                            frozenset(),
                        )
                    ),
                )
                self._owned_components[correction_port] = frozenset(
                    {"verifier"}
                )
                self._legacy_correction_port = correction_port
                bind_corrections(correction_port)

    async def start(self) -> None:
        """Open scheduling and perform one bounded recovery scan when enabled."""
        if self._stopped:
            raise RuntimeError("crew_session_lifecycle_stopped")
        if not self._orchestrator_enabled():
            return
        if self._started:
            return
        if self._start_lock.locked():
            async with self._start_lock:
                pass
            if self._stopped:
                raise RuntimeError("crew_session_lifecycle_stopped")
            if self._started:
                return
            return await self.start()
        prior_tasks = {
            parent_id: (task, self._task_generations.get(task))
            for parent_id, task in self._tasks_by_parent.items()
        }
        self._lifecycle_generation += 1
        generation = self._lifecycle_generation
        self._admission_generation = generation
        self._scheduling_open = True
        async with self._start_lock:
            if self._stopped:
                self._scheduling_open = False
                raise RuntimeError("crew_session_lifecycle_stopped")
            if self._started:
                return
            try:
                dispatch_config = getattr(self._config, "agentic_dispatch", None)
                repair_limit = getattr(
                    dispatch_config,
                    "crew_provisioning_repair_limit",
                    100,
                )
                scan_limit = getattr(dispatch_config, "crew_resume_scan_limit", 100)
                repaired_ids: tuple[str, ...] | list[str] = ()
                candidates: list[Any] = []
                if self._crew_session_service is not None:
                    repaired_ids = await self._crew_session_service.repair_provisioning(
                        limit=int(repair_limit),
                    )
                    candidates.extend(
                        await self._work_item_store.list_crew_session_recovery_candidates(
                            limit=int(scan_limit),
                        )
                    )
                if self._legacy_owned_port is not None:
                    candidates.extend(
                        await self._work_item_store.list_owned_legacy_recovery_candidates(
                            limit=int(scan_limit),
                        )
                    )
                selected_ids: list[str] = []
                seen_ids: set[str] = set()
                for parent_id in (
                    *repaired_ids,
                    *(item.id for item in candidates),
                ):
                    if parent_id in seen_ids:
                        continue
                    seen_ids.add(parent_id)
                    selected_ids.append(parent_id)
                    if len(selected_ids) == int(scan_limit):
                        break
                validated: list[tuple[str, str]] = []
                for parent_id in selected_ids:
                    parent = await self._work_item_store.get_work_item(parent_id)
                    if parent is None:
                        raise ValueError("crew_session_candidate_integrity_invalid")
                    if parent.work_type == "crew_session":
                        if self._crew_session_service is None:
                            raise ValueError("crew_session_service_unavailable")
                        session = await self._crew_session_service.get_session(
                            parent_id
                        )
                        if session is None:
                            raise ValueError(
                                "crew_session_candidate_integrity_invalid"
                            )
                        await self._crew_session_service.get_recovery(parent_id)
                        validated.append((parent_id, session.state))
                    else:
                        snapshot = await self._work_item_store.get_owned_steps(
                            parent_id
                        )
                        if (
                            snapshot is None
                            or snapshot.control.owner_kind != "legacy"
                        ):
                            raise ValueError(
                                "owned_steps_recovery_candidate_invalid"
                            )
                        validated.append((parent_id, "legacy"))
                if self._stopped:
                    self._scheduling_open = False
                    raise RuntimeError("crew_session_lifecycle_stopped")
                for parent_id, state in validated:
                    if state in {
                        "discussing",
                        "executing",
                        "verifying",
                        "legacy",
                    }:
                        self.schedule(parent_id)
                self._started = True
            except BaseException as start_error:
                self._scheduling_open = False
                self._admission_generation = None
                first_cancellation = (
                    start_error
                    if isinstance(start_error, asyncio.CancelledError)
                    else None
                )
                current_task = asyncio.current_task()
                if first_cancellation is not None and current_task is not None:
                    current_task.uncancel()
                cleanup = asyncio.create_task(
                    self._drain_start_generation(generation, prior_tasks),
                    name=f"crew-start-cleanup:{generation}",
                )
                while not cleanup.done():
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError as exc:
                        if first_cancellation is None:
                            first_cancellation = exc
                        current_task = asyncio.current_task()
                        if current_task is not None:
                            current_task.uncancel()
                cleanup.result()
                self._started = False
                if first_cancellation is not None:
                    raise first_cancellation
                raise start_error

    def schedule(
        self,
        parent_id: str,
        *,
        continuation: bool = False,
    ) -> asyncio.Task[SynthesisResult]:
        """Synchronously register or return the one live owner task for a parent."""
        if type(parent_id) is not str or _PARENT_ID_RE.fullmatch(parent_id) is None:
            raise ValueError("crew_session_parent_id_invalid")
        if not self._scheduling_open:
            raise RuntimeError("crew_session_scheduling_closed")
        existing = self._tasks_by_parent.get(parent_id)
        if existing is not None and not existing.done():
            if continuation:
                self._pending_continuations.add(parent_id)
            return existing
        task = asyncio.create_task(
            self._run_owned_parent(parent_id),
            name=f"crew-session:{parent_id}",
        )
        generation = self._admission_generation
        if generation is None:
            task.cancel()
            raise RuntimeError("crew_session_scheduling_closed")
        self._task_generations[task] = generation
        self._tasks_by_parent[parent_id] = task
        task.add_done_callback(
            lambda completed, key=parent_id: self._observe_parent_task(
                key,
                completed,
            )
        )
        return task

    def close_scheduling(self) -> None:
        """Synchronously and idempotently close admission to new parent work."""
        self._scheduling_open = False
        self._pending_continuations.clear()

    async def stop(self) -> None:
        """Close admission and cancellation-defer one shared owner-task drain."""
        self.close_scheduling()
        self._stopped = True
        cleanup = self._stop_cleanup_task
        if cleanup is None:
            cleanup = asyncio.create_task(
                self._drain_parent_tasks(),
                name="crew-session-stop",
            )
            self._stop_cleanup_task = cleanup
        first_cancellation: asyncio.CancelledError | None = None
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError as exc:
                if first_cancellation is None:
                    first_cancellation = exc
                current = asyncio.current_task()
                if current is not None:
                    current.uncancel()
                continue
        cleanup.result()
        if first_cancellation is not None:
            raise first_cancellation

    async def _run_owned_parent(self, parent_id: str) -> SynthesisResult:
        async with self._active_parent_semaphore:
            parent = await self._work_item_store.get_work_item(parent_id)
            if (
                parent is None
                or parent.work_type != "crew_session"
                or self._crew_session_service is None
            ):
                return await self.run_crew_task(parent_id)
            return await self._run_recovery_loop(parent_id)

    def _observe_parent_task(
        self,
        parent_id: str,
        task: asyncio.Task[SynthesisResult],
    ) -> None:
        cancelled = task.cancelled()
        if cancelled:
            logger.info(
                "Crew session parent=%s owner task was cancelled; durable recovery will resume it on a later authorized start",
                parent_id,
            )
        else:
            try:
                task.result()
            except Exception:
                logger.exception(
                    "Crew session parent=%s owner task failed; durable state remains authoritative and startup recovery will inspect it",
                    parent_id,
                )
        if self._tasks_by_parent.get(parent_id) is task:
            self._tasks_by_parent.pop(parent_id, None)
        if cancelled:
            self._pending_continuations.discard(parent_id)
            return
        if (
            parent_id in self._pending_continuations
            and self._scheduling_open
        ):
            self._pending_continuations.remove(parent_id)
            self.schedule(parent_id)

    async def _drain_parent_tasks(self) -> None:
        snapshot = tuple(self._tasks_by_parent.values())
        for task in snapshot:
            task.cancel()
        if snapshot:
            await asyncio.gather(*snapshot, return_exceptions=True)

    async def _drain_start_generation(
        self,
        generation: int,
        prior_tasks: dict[
            str,
            tuple[asyncio.Task[SynthesisResult], int | None],
        ],
    ) -> None:
        while True:
            snapshot = tuple(
                task
                for parent_id, task in self._tasks_by_parent.items()
                if self._task_generations.get(task) == generation
                and (
                    parent_id not in prior_tasks
                    or prior_tasks[parent_id][0] is not task
                    or prior_tasks[parent_id][1] != generation
                )
            )
            if not snapshot:
                return
            for task in snapshot:
                task.cancel()
            await asyncio.gather(*snapshot, return_exceptions=True)
            await asyncio.sleep(0)

    async def _run_recovery_attempt(self, parent_id: str) -> SynthesisResult:
        service = self._crew_session_service
        if service is None:
            raise ValueError("crew_session_service_unavailable")
        session = await self._await_recovery_boundary(
            service.get_session(parent_id),
            boundary="session_load",
        )
        if session is None:
            raise ValueError("crew_session_not_initialized")
        try:
            owned_snapshot = await service.get_owned_steps_snapshot(parent_id)
        except Exception as exc:
            if getattr(exc, "code", None) != "owned_steps_execution_scope_denied":
                raise
            owned_snapshot = None
        if (
            owned_snapshot is not None
            and owned_snapshot.control.finalization is not None
        ):
            if self._crew_session_finalizer is None:
                raise ValueError("crew_session_finalizer_unavailable")
            return self._finalization_result(
                await self._crew_session_finalizer.finalize_from_receipt(
                    owned_snapshot.control.finalization
                )
            )
        if session.state in {"done", "failed", "blocked_needs_captain"}:
            return self._session_observation(session)
        recovery = await self._await_recovery_boundary(
            service.get_recovery(parent_id),
            boundary="recovery_load",
        )
        if (
            owned_snapshot is not None
            and await self._work_item_store.get_owned_synthesis_claim(parent_id)
            is not None
            and (recovery is None or recovery.synthesis_ref is None)
        ):
            return SynthesisResult(
                parent_id=parent_id,
                final_output="",
                completed=False,
                disposition="pending",
            )
        if recovery is None and session.state == "verifying":
            children = await self._await_recovery_boundary(
                self._recovery_children(parent_id),
                boundary="child_scan",
            )
            if len(children) > 1000:
                raise ValueError("crew_recovery_plan_children_invalid")
            if any(
                child.verification
                and (
                    type(child.metadata) is not dict
                    or type(
                        child.metadata.get("crew_verification_recovery")
                    ) is not dict
                )
                for child in children
            ):
                blocked = await self._await_recovery_boundary(
                    service.transition_session(
                        parent_id,
                        "blocked_needs_captain",
                        expected_revision=session.revision,
                        last_result_summary=(
                            "legacy_verification_nonreconstructable"
                        ),
                        blocked_reason="legacy_verification_nonreconstructable",
                    ),
                    boundary="session_transition",
                )
                return self._session_observation(blocked)
        if recovery is None or recovery.plan is None:
            recovery = await self._establish_recovery_plan(session, recovery)
            session = await self._await_recovery_boundary(
                service.get_session(parent_id),
                boundary="session_load",
            )
            if session is None:
                raise ValueError("crew_session_not_initialized")
        recovery = await self._checkpoint_attempt(session, recovery)

        if session.state == "discussing":
            if recovery.phase != "planned":
                raise ValueError("crew_recovery_phase_state_conflict")
            values = recovery.model_dump(mode="json")
            values.update({
                "phase": "executing",
                "retry_count": 0,
                "next_attempt_at": None,
                "last_error_code": None,
                "interrupted_child_ids": [],
            })
            executing_recovery = type(recovery).model_validate(values)
            session = await self._await_recovery_boundary(
                service.transition_session(
                    parent_id,
                    "executing",
                    expected_revision=session.revision,
                    expected_recovery=recovery,
                    recovery=executing_recovery,
                ),
                boundary="session_transition",
            )
            recovery = executing_recovery

        if session.state == "executing":
            if recovery.phase != "executing":
                raise ValueError("crew_recovery_phase_state_conflict")
            try:
                await service.validate_worker_admission(parent_id, allow_reassignment=True)
                await self._assign_untouched_session_children(parent_id, recovery.plan.plan_hash)
                await service.validate_worker_admission(parent_id)
                results = await self._crew_executor.resume(parent_id)
            except CrewWorkerUnavailable:
                children = await self._recovery_children(parent_id, recovery.plan.plan_hash)
                untouched = bool(children) and len(children) <= 1000 and all(
                    is_untouched_crew_child(
                        child,
                        initial_status=self._work_item_store.work_type_registry.get_initial_status(
                            child.work_type,
                        ),
                    )
                    for child in children
                )
                logger.warning(
                    "Crew parent %s lost worker eligibility; child tasks are drained "
                    "and the parent is parked for %s",
                    parent_id,
                    "Captain retry" if untouched else "execution evidence review",
                )
                return await self._transition_recovery_terminal(
                    session,
                    recovery,
                    state="blocked_needs_captain",
                    code="crew_worker_unavailable" if untouched else "crew_worker_identity_lost",
                )
            if any(result.stopped_reason == "crew_worker_identity_lost" for result in results):
                return await self._transition_recovery_terminal(
                    session,
                    recovery,
                    state="blocked_needs_captain",
                    code="crew_worker_identity_lost",
                )
            failed = next(
                (result for result in results if result.status == "failed"),
                None,
            )
            blocked = next(
                (result for result in results if result.status == "blocked"),
                None,
            )
            if failed is not None:
                return await self._transition_recovery_terminal(
                    session,
                    recovery,
                    state="failed",
                    code="child_execution_failed",
                )
            if blocked is not None:
                return await self._transition_recovery_terminal(
                    session,
                    recovery,
                    state="blocked_needs_captain",
                    code=(
                        "child_execution_interrupted"
                        if blocked.stopped_reason.startswith("child_execution_")
                        else "child_execution_blocked"
                    ),
                )
            if self._crew_session_finalizer is None:
                raise ValueError("crew_session_finalizer_unavailable")
            return self._finalization_result(
                await self._crew_session_finalizer.resume(parent_id),
            )

        if session.state == "verifying":
            if self._crew_session_finalizer is None:
                raise ValueError("crew_session_finalizer_unavailable")
            try:
                finalized = await self._crew_session_finalizer.resume(parent_id)
            except ValueError as exc:
                if str(exc) != (
                    "crew_finalization_legacy_verification_nonreconstructable"
                ):
                    raise
                return await self._transition_recovery_terminal(
                    session,
                    recovery,
                    state="blocked_needs_captain",
                    code="legacy_verification_nonreconstructable",
                )
            return self._finalization_result(finalized)
        raise ValueError("crew_recovery_state_invalid")

    async def _establish_recovery_plan(
        self,
        session: Any,
        recovery: Any | None,
    ) -> Any:
        from probos.cognitive.crew_session import (
            _build_adopted_recovery_plan,
            _build_derived_recovery_plan,
        )

        service = self._crew_session_service
        if service is None:
            raise ValueError("crew_session_service_unavailable")
        if recovery is not None and recovery.phase != "unplanned":
            raise ValueError("crew_recovery_plan_missing")
        children = await self._await_recovery_boundary(
            self._recovery_children(session.task_id),
            boundary="child_scan",
        )
        if len(children) > 1000:
            raise ValueError("crew_recovery_plan_children_invalid")
        if children:
            if recovery is not None:
                raise ValueError("crew_recovery_plan_missing")
            ordered = tuple(sorted(children, key=lambda child: child.id))
            plan = _build_adopted_recovery_plan(session.task_id, ordered)
            return await self._await_recovery_boundary(
                service.adopt_recovery_plan(
                    session.task_id,
                    expected_session=session,
                    expected_recovery=None,
                    plan=plan,
                    expected_children=ordered,
                ),
                boundary="plan_adoption_store",
            )
        if session.state != "discussing":
            raise ValueError("crew_recovery_plan_missing")
        decomposer = self._get_decomposer()
        if decomposer is None:
            raise ValueError("crew_recovery_decomposer_unavailable")
        decomposition = asyncio.create_task(
            asyncio.to_thread(decomposer.decompose, session.goal),
            name=f"crew-session-decompose:{session.task_id}",
        )
        cancellation: asyncio.CancelledError | None = None
        while not decomposition.done():
            try:
                await asyncio.shield(decomposition)
            except asyncio.CancelledError as exc:
                if cancellation is None:
                    cancellation = exc
                current = asyncio.current_task()
                if current is not None:
                    current.uncancel()
                continue
        try:
            specs = list(decomposition.result())
        except Exception as exc:
            translated = self._translate_recovery_boundary_error(
                exc,
                boundary="decomposition_llm",
            )
            if translated is None:
                raise
            raise translated from exc
        plan, inserts = _build_derived_recovery_plan(
            session.task_id,
            specs,
            created_by=session.facilitator_id,
        )
        installed, _ = await self._await_recovery_boundary(
            service.install_recovery_plan(
                session.task_id,
                expected_session=session,
                expected_recovery=recovery,
                plan=plan,
                children=inserts,
            ),
            boundary="plan_install_store",
        )
        if cancellation is not None:
            values = installed.model_dump(mode="json")
            values.update({
                "last_error_code": "decomposition_cancelled_after_plan_install",
                "next_attempt_at": None,
            })
            checkpoint = type(installed).model_validate(values)
            await self._await_recovery_boundary(
                service.compare_and_set_recovery(
                    session.task_id,
                    checkpoint,
                    expected_session=session,
                    expected_recovery=installed,
                ),
                boundary="recovery_store",
            )
            raise cancellation
        return installed

    async def _checkpoint_attempt(self, session: Any, recovery: Any) -> Any:
        service = self._crew_session_service
        if service is None:
            raise ValueError("crew_session_service_unavailable")
        if recovery.attempt_count >= 1_000_000:
            raise ValueError("crew_recovery_attempt_count_invalid")
        values = recovery.model_dump(mode="json")
        values.update({
            "attempt_count": recovery.attempt_count + 1,
            "last_attempt_at": self._recovery_now(),
            "next_attempt_at": None,
        })
        candidate = type(recovery).model_validate(values)
        return await self._await_recovery_boundary(
            service.compare_and_set_recovery(
                session.task_id,
                candidate,
                expected_session=session,
                expected_recovery=recovery,
            ),
            boundary="recovery_store",
        )

    async def _recovery_children(
        self, parent_id: str, expected_plan: str | None = None,
    ) -> list["WorkItem"]:
        try:
            membership = await self._work_item_store.get_owned_crew_children(parent_id, expected_plan)
            return list(membership.active)
        except owned_steps.OwnedStepsError as exc:
            if exc.code != "owned_steps_not_managed":
                raise
            return await self._work_item_store.list_work_items(parent_id=parent_id, limit=1001)

    async def _assign_untouched_session_children(
        self, parent_id: str, expected_plan: str | None = None,
    ) -> None:
        children = await self._await_recovery_boundary(
            self._recovery_children(parent_id, expected_plan),
            boundary="child_scan",
        )
        if len(children) > 1000:
            raise ValueError("crew_recovery_plan_children_invalid")
        for child in children:
            metadata = child.metadata if type(child.metadata) is dict else {}
            if not is_untouched_crew_child(
                child,
                initial_status=self._work_item_store.work_type_registry.get_initial_status(
                    child.work_type,
                ),
            ):
                continue
            if child.assigned_to is not None and (
                self._eligibility_resolver is None
                or self._eligibility_resolver.check_eligibility(child.assigned_to).identity is not None
            ):
                continue
            if self._crew_session_service is None:
                raise ValueError("crew_session_service_unavailable")
            owned_snapshot = await self._await_recovery_boundary(
                self._crew_session_service.get_owned_steps_snapshot(parent_id),
                boundary="assignment_capture",
            )
            decision = self._assignment_resolver.resolve(self._spec_view(child))
            delegation = self._delegator.delegate(decision)
            if not delegation.worker_agent_id:
                continue
            assigned_metadata = {
                "chief_agent_id": delegation.chief_agent_id,
                "order_id": delegation.order_id,
                "delegated": delegation.delegated,
                "delegation_reason": delegation.reason,
                "assigned_capability": decision.capability,
                "assigned_department": decision.department,
            }
            try:
                result = await self._await_recovery_boundary(
                    self._crew_session_service.reassign_unstarted(
                        owned_snapshot,
                        child.id,
                        delegation.worker_agent_id,
                        assigned_metadata,
                    ),
                    boundary="assignment_store",
                )
            except Exception as exc:
                if getattr(exc, "code", None) not in {
                    "owned_steps_row_conflict",
                    "owned_steps_reassignment_conflict",
                    "owned_steps_assignment_ineligible",
                }:
                    raise
                raise CrewWorkerUnavailable("crew_worker_unavailable") from exc
            if result.snapshot is None and result.disposition != "duplicate":
                raise CrewWorkerUnavailable("crew_worker_unavailable")

    async def _run_recovery_loop(self, parent_id: str) -> SynthesisResult:
        while True:
            try:
                await self._honor_recovery_backoff(parent_id)
                return await self._run_recovery_attempt(parent_id)
            except asyncio.CancelledError as cancellation:
                current_task = asyncio.current_task()
                if current_task is not None:
                    current_task.uncancel()

                async def _checkpoint() -> None:
                    current = None
                    if self._crew_session_service is not None:
                        try:
                            current = await self._crew_session_service.get_recovery(
                                parent_id,
                            )
                        except Exception:
                            current = None
                    if (
                        current is None
                        or current.last_error_code
                        != "decomposition_cancelled_after_plan_install"
                    ):
                        await self._checkpoint_recovery_cancellation(parent_id)

                checkpoint = asyncio.create_task(
                    _checkpoint(),
                    name=f"crew-cancellation-checkpoint:{parent_id}",
                )
                while not checkpoint.done():
                    try:
                        await asyncio.shield(checkpoint)
                    except asyncio.CancelledError:
                        current_task = asyncio.current_task()
                        if current_task is not None:
                            current_task.uncancel()
                try:
                    checkpoint.result()
                except BaseException:
                    logger.exception(
                        "Crew session parent=%s cancellation checkpoint could "
                        "not complete; the first cancellation remains "
                        "authoritative and will propagate",
                        parent_id,
                    )
                raise cancellation
            except Exception as exc:
                transient = self._as_recovery_transient(exc)
                if transient is not None:
                    terminal = await self._checkpoint_transient_failure(
                        parent_id,
                        transient,
                    )
                    if terminal is not None:
                        return terminal
                    continue
                if not isinstance(exc, Exception):
                    raise
                return await self._contain_recovery_failure(parent_id, exc)

    async def _checkpoint_recovery_cancellation(self, parent_id: str) -> None:
        service = self._crew_session_service
        if service is None:
            return
        try:
            session = await service.get_session(parent_id)
            recovery = await service.get_recovery(parent_id)
            if (
                session is None
                or recovery is None
                or session.state in {"done", "failed", "blocked_needs_captain"}
            ):
                return
            snapshot = await self._work_item_store.get_owned_steps(parent_id)
            membership = (
                await self._work_item_store.get_owned_crew_children(
                    parent_id,
                    snapshot.control.plan_digest,
                )
                if snapshot is not None
                else None
            )
            children = (
                list(membership.active)
                if membership is not None
                else await self._work_item_store.list_work_items(
                    parent_id=parent_id,
                    limit=1001,
                )
            )
            interrupted = sorted(
                child.id for child in children if child.status == "in_progress"
            )
            dispatch_config = getattr(self._config, "agentic_dispatch", None)
            maximum = int(getattr(dispatch_config, "max_parallel_subtasks", 3))
            interrupted = interrupted[:maximum]
            safely_terminal = any(
                child.status in {"done", "failed", "blocked"}
                and type(child.metadata) is dict
                and type(child.metadata.get("crew_execution")) is dict
                for child in children
            )
            values = recovery.model_dump(mode="json")
            values.update({
                "last_error_code": (
                    "child_execution_cancelled"
                    if interrupted
                    else (
                        "child_execution_cancelled_at_safe_boundary"
                        if safely_terminal
                        else "child_execution_cancelled_before_admission"
                    )
                ),
                "next_attempt_at": None,
                "interrupted_child_ids": interrupted,
            })
            checkpoint = type(recovery).model_validate(values)
            if interrupted and session.state == "executing":
                await service.transition_session(
                    parent_id,
                    "blocked_needs_captain",
                    expected_revision=session.revision,
                    last_result_summary="child_execution_interrupted",
                    blocked_reason="child_execution_interrupted",
                    expected_recovery=recovery,
                    recovery=checkpoint,
                )
            else:
                await service.compare_and_set_recovery(
                    parent_id,
                    checkpoint,
                    expected_session=session,
                    expected_recovery=recovery,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Crew session parent=%s cancellation checkpoint failed; the original cancellation will propagate and durable state remains authoritative",
                parent_id,
            )

    async def _honor_recovery_backoff(self, parent_id: str) -> None:
        service = self._crew_session_service
        if service is None:
            return
        recovery = await self._await_recovery_boundary(
            service.get_recovery(parent_id),
            boundary="recovery_load",
        )
        if recovery is None or recovery.next_attempt_at is None:
            return
        remaining = max(0.0, recovery.next_attempt_at - self._recovery_now())
        if remaining > 0.0:
            await self._sleep(remaining)

    def _as_recovery_transient(self, exc: BaseException) -> Any | None:
        from probos.cognitive.crew_session import CrewRecoveryTransientError

        return exc if isinstance(exc, CrewRecoveryTransientError) else None

    @staticmethod
    def _translate_recovery_boundary_error(
        exc: Exception,
        *,
        boundary: str,
    ) -> Any | None:
        from probos.cognitive.crew_session import CrewRecoveryTransientError

        if isinstance(exc, CrewRecoveryTransientError):
            return exc
        if type(boundary) is not str or _RECOVERY_BOUNDARY_RE.fullmatch(boundary) is None:
            raise ValueError("crew_recovery_boundary_invalid")
        code: str | None = None
        if isinstance(exc, TimeoutError):
            code = f"transient_{boundary}_timeout"
        elif isinstance(exc, ConnectionError):
            code = f"transient_{boundary}_connection"
        elif isinstance(exc, sqlite3.OperationalError) and getattr(
            exc,
            "sqlite_errorcode",
            None,
        ) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            code = f"transient_{boundary}_sqlite_busy"
        elif isinstance(exc, OSError) and exc.errno in {
            errno.EAGAIN,
            errno.EBUSY,
            errno.ETIMEDOUT,
            errno.ECONNRESET,
            errno.ECONNREFUSED,
            errno.ENETDOWN,
            errno.ENETUNREACH,
            errno.EHOSTUNREACH,
        }:
            code = f"transient_{boundary}_os_{exc.errno}"
        if code is None:
            return None
        wrapped = CrewRecoveryTransientError(code)
        wrapped.__cause__ = exc
        return wrapped

    async def _await_recovery_boundary(
        self,
        awaitable: Awaitable[Any],
        *,
        boundary: str,
    ) -> Any:
        try:
            return await awaitable
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            translated = self._translate_recovery_boundary_error(
                exc,
                boundary=boundary,
            )
            if translated is None:
                raise
            raise translated from exc

    async def _checkpoint_transient_failure(
        self,
        parent_id: str,
        transient: Any,
    ) -> SynthesisResult | None:
        service = self._crew_session_service
        if service is None:
            raise transient
        session = await service.get_session(parent_id)
        recovery = await service.get_recovery(parent_id)
        if session is None or recovery is None:
            raise transient
        dispatch_config = getattr(self._config, "agentic_dispatch", None)
        maximum_retries = int(
            getattr(dispatch_config, "crew_recovery_max_retries", 3),
        )
        if recovery.retry_count >= maximum_retries:
            return await self._transition_recovery_terminal(
                session,
                recovery,
                state="blocked_needs_captain",
                code="recovery_retry_exhausted",
            )
        retry_count = recovery.retry_count + 1
        initial = float(
            getattr(
                dispatch_config,
                "crew_recovery_initial_backoff_seconds",
                5.0,
            ),
        )
        maximum = float(
            getattr(
                dispatch_config,
                "crew_recovery_max_backoff_seconds",
                300.0,
            ),
        )
        try:
            delay = min(initial * (2.0 ** (retry_count - 1)), maximum)
        except OverflowError:
            delay = maximum
        if not math.isfinite(delay):
            delay = maximum
        delay = max(0.0, delay)
        now = self._recovery_now()
        values = recovery.model_dump(mode="json")
        values.update({
            "retry_count": retry_count,
            "last_attempt_at": now,
            "next_attempt_at": now + delay,
            "last_error_code": transient.code,
            "interrupted_child_ids": [],
        })
        candidate = type(recovery).model_validate(values)
        await service.compare_and_set_recovery(
            parent_id,
            candidate,
            expected_session=session,
            expected_recovery=recovery,
        )
        if delay > 0.0:
            await self._sleep(delay)
        return None

    async def _contain_recovery_failure(
        self,
        parent_id: str,
        exc: Exception,
    ) -> SynthesisResult:
        service = self._crew_session_service
        if service is None:
            return self._empty_result(parent_id)
        try:
            session = await service.get_session(parent_id)
            recovery = await service.get_recovery(parent_id)
        except Exception:
            logger.exception(
                "Crew session parent=%s recovery authority could not be inspected after failure; stores remain untouched",
                parent_id,
            )
            return self._empty_result(parent_id)
        if session is None or recovery is None:
            logger.error(
                "Crew session parent=%s recovery failed before complete authority existed; stores remain untouched",
                parent_id,
            )
            return self._empty_result(parent_id)
        if session.state in {"done", "failed", "blocked_needs_captain"}:
            return self._session_observation(session)
        state = "blocked_needs_captain" if isinstance(exc, ValueError) else "failed"
        code = (
            "recovery_integrity_conflict"
            if isinstance(exc, ValueError)
            else "recovery_unexpected_failure"
        )
        logger.warning(
            "Crew session parent=%s recovery failed code=%s; authoritative session will transition to %s and no implicit retry will be scheduled",
            parent_id,
            code,
            state,
            exc_info=True,
        )
        try:
            return await self._transition_recovery_terminal(
                session,
                recovery,
                state=state,
                code=code,
            )
        except Exception:
            logger.exception(
                "Crew session parent=%s terminal recovery checkpoint failed; stores remain at their prior authoritative state",
                parent_id,
            )
            return self._empty_result(parent_id)

    async def _transition_recovery_terminal(
        self,
        session: Any,
        recovery: Any,
        *,
        state: str,
        code: str,
    ) -> SynthesisResult:
        service = self._crew_session_service
        if service is None:
            raise ValueError("crew_session_service_unavailable")
        values = recovery.model_dump(mode="json")
        values.update({
            "last_error_code": code,
            "next_attempt_at": None,
            "interrupted_child_ids": [],
        })
        checkpoint = type(recovery).model_validate(values)
        transitioned = await service.transition_session(
            session.task_id,
            state,
            expected_revision=session.revision,
            last_result_summary=code,
            blocked_reason=code if state == "blocked_needs_captain" else None,
            expected_recovery=recovery,
            recovery=checkpoint,
        )
        return self._session_observation(transitioned)

    def _recovery_now(self) -> float:
        value = self._clock()
        if type(value) not in (int, float):
            raise ValueError("crew_recovery_clock_invalid")
        normalized = float(value)
        if not math.isfinite(normalized) or normalized < 0.0:
            raise ValueError("crew_recovery_clock_invalid")
        return normalized

    @staticmethod
    def _finalization_result(finalized: Any) -> SynthesisResult:
        return SynthesisResult(
            parent_id=finalized.parent_id,
            final_output=finalized.final_output if finalized.completed else "",
            completed=finalized.completed,
            shapley_values={},
            provenance_ref=(
                finalized.provenance_ref if finalized.completed else None
            ),
            accepted_count=finalized.accepted_count,
            total_count=finalized.total_count,
        )

    @staticmethod
    def _session_observation(session: Any) -> SynthesisResult:
        return SynthesisResult(
            parent_id=session.task_id,
            final_output=(
                session.last_result_summary if session.state == "done" else ""
            ),
            completed=session.state == "done",
            provenance_ref=session.result_ref,
        )

    @staticmethod
    def _empty_result(parent_id: str) -> SynthesisResult:
        return SynthesisResult(
            parent_id=parent_id,
            final_output="",
            completed=False,
        )

    # ------------------------------------------------------------------ trigger

    async def maybe_dispatch_crew(self, parent_id: str) -> asyncio.Task[SynthesisResult] | None:
        """Trigger gate: schedule ``run_crew_task`` as a held task iff the
        orchestrator is enabled and the parent decomposed into **>1** child.

        Returns the scheduled task, or ``None`` when the orchestrator is disabled
        or the parent is single-spec (caller keeps the AD-856 single-agent path).
        """
        if not self._orchestrator_enabled():
            return None
        children = await self._load_children(parent_id)
        if len(children) <= 1:
            logger.debug(
                "AD-867: parent %s has %d child(ren); single-spec keeps the "
                "AD-856 single-agent path",
                parent_id, len(children),
            )
            return None
        task = self.schedule(parent_id)
        logger.info(
            "AD-867: scheduled crew_orchestrator.run_crew_task for parent %s "
            "(%d children)",
            parent_id, len(children),
        )
        return task

    # --------------------------------------------------------------- originate

    async def originate_crew_task(
        self,
        *,
        origin_agent_id: str,
        goal: str,
        work_type: str = "task",
    ) -> str | None:
        """Compatibility delegate to the unified AD-1128 ingress authority."""
        if work_type != "task" or self._crew_session_service is None:
            logger.warning(
                "AD-1128: self-originated CrewSession from agent=%s was not "
                "admitted because the compatibility contract or service is "
                "unavailable; no work was created",
                origin_agent_id,
            )
            return None
        try:
            result = await self._crew_session_service.open_or_resume(
                principal=self._crew_session_service.agent_principal(
                    origin_agent_id,
                ),
                goal=goal,
                success_criteria=[
                    "Complete the stated goal with verifiable evidence.",
                ],
                expected_deliverable=(
                    "A verified result for the stated goal."
                ),
            )
        except Exception:
            logger.warning(
                "AD-1128: self-originated CrewSession from agent=%s failed "
                "unified admission; no alternate parent or runner was used",
                origin_agent_id,
                exc_info=True,
            )
            return None
        return result.parent_id

    def _get_decomposer(self) -> Any | None:
        """Return the plan decomposer, building one lazily from the runtime.

        An instance injected at construction (tests) takes precedence; otherwise
        a real :class:`LLMPlanDecomposer` is built from ``runtime.llm_client``
        and cached. Returns ``None`` when no LLM client is available
        (honest-degrade).
        """
        if self._decomposer is not None:
            return self._decomposer
        llm_client = getattr(self._runtime, "llm_client", None)
        if llm_client is None:
            return None
        from probos.consultation.llm_decomposer import LLMPlanDecomposer

        self._decomposer = LLMPlanDecomposer(llm_client)
        return self._decomposer

    async def owned_steps_actual_context(
        self,
        principal: object,
        *,
        work_item_id: str,
        turn_id: str,
    ) -> owned_steps.OwnedStepsActualContext:
        """Validate a server principal and freeze its actual managed scope."""
        if (
            type(turn_id) is not str
            or _PARENT_ID_RE.fullmatch(turn_id) is None
            or self._crew_session_service is None
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_actual_context_invalid",
                parent_id=work_item_id,
            )
        parent_id = await self._work_item_store.resolve_owned_steps_parent_id(
            work_item_id
        )
        if parent_id is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_not_managed",
                parent_id=work_item_id,
                actions=("inspect_source",),
            )
        if getattr(principal, "origin", None) == "agent":
            try:
                authority = (
                    await self._crew_session_service.owned_human_steps_authority(
                        principal,
                        parent_id=parent_id,
                        operation="read_owned_steps",
                        token=None,
                    )
                )
            except owned_steps.OwnedStepsError:
                authority = (
                    await self._crew_session_service.owned_read_steps_authority(
                        principal,
                        parent_id=parent_id,
                    )
                )
        else:
            authority = await self._crew_session_service.owned_human_steps_authority(
                principal,
                parent_id=parent_id,
                operation="read_owned_steps",
                token=None,
            )
        invocation = authority.context
        if (
            type(invocation) is not owned_steps.OwnedOwnerInvocation
            or invocation.parent_id != parent_id
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_actual_context_invalid",
                parent_id=parent_id,
            )
        return owned_steps.OwnedStepsActualContext(
            authority=authority,
            owner=self._owned_principal,
            parent_id=parent_id,
            actor_id=invocation.actor_id,
            thread_id=invocation.thread_id,
            turn_id=turn_id,
        )

    async def owned_steps_repair_context(
        self,
        principal: object,
        *,
        work_item_id: str,
        turn_id: str,
    ) -> owned_steps.OwnedStepsActualContext:
        """Authenticate a human owner before any malformed raw bytes are read."""
        if (
            type(turn_id) is not str
            or _PARENT_ID_RE.fullmatch(turn_id) is None
            or self._crew_session_service is None
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_actual_context_invalid",
                parent_id=work_item_id,
            )
        parent_id = (
            await self._work_item_store.resolve_owned_steps_parent_id(work_item_id)
            or work_item_id
        )
        identity = await self._work_item_store.read_owned_steps_raw_identity(parent_id)
        if identity is None or identity.parent_id_value is not None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_parent_missing",
                parent_id=parent_id,
            )
        authority = await self._crew_session_service.owned_human_steps_authority(
            principal,
            parent_id=parent_id,
            operation="capture_repair_observation",
            token=None,
        )
        invocation = authority.context
        if (
            type(invocation) is not owned_steps.OwnedOwnerInvocation
            or invocation.parent_id != parent_id
            or invocation.role not in ("captain", "facilitator")
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_actual_context_invalid",
                parent_id=parent_id,
            )
        return owned_steps.OwnedStepsActualContext(
            authority=authority,
            owner=self._owned_principal,
            parent_id=parent_id,
            actor_id=invocation.actor_id,
            thread_id=invocation.thread_id,
            turn_id=turn_id,
        )

    async def capture_owned_steps_repair_observation(
        self,
        actual_context: owned_steps.OwnedStepsActualContext,
    ) -> tuple[owned_steps.RepairObservation, owned_steps.RepairReference]:
        """Capture immutable raw evidence without requiring a valid projection."""
        self._require_owned_steps_actual_context(actual_context)
        authority = actual_context.authority_for_operation(
            self._owned_principal,
            operation="capture_repair_observation",
        )
        observation = (
            await self._work_item_store.capture_owned_steps_repair_observation(
                actual_context.parent_id,
                authority,
            )
        )
        reference = owned_steps.RepairReference(
            parent_id=actual_context.parent_id,
            actor_id=actual_context.actor_id,
            thread_id=actual_context.thread_id,
            turn_id=actual_context.turn_id,
            view_id=uuid.uuid4().hex,
            content_hash=observation.source_digest,
            observation_id=observation.observation_id,
        )
        return observation, reference

    def _require_owned_steps_actual_context(
        self,
        actual_context: owned_steps.OwnedStepsActualContext,
        *,
        parent_id: str | None = None,
    ) -> None:
        issued = (
            type(actual_context) is owned_steps.OwnedStepsActualContext
            and actual_context.is_issued_by(self._owned_principal)
        )
        if not issued or (parent_id is not None and actual_context.parent_id != parent_id):
            raise owned_steps.OwnedStepsError(
                "owned_steps_actual_context_invalid",
                parent_id=actual_context.parent_id if issued else parent_id or "",
            )

    @staticmethod
    def _owned_view_cursor(
        control: owned_steps.OwnedStepsControl,
        offset: int,
    ) -> str:
        return (
            f"{control.incarnation}.{control.layout_revision}.{offset}"
        )

    @staticmethod
    def _owned_view_offset(
        control: owned_steps.OwnedStepsControl,
        cursor: str | None,
    ) -> int:
        if cursor is None:
            return 0
        visible = (
            control.rows[:control.manual_prefix_length]
            if control.mode == "awaiting_adoption"
            else control.rows
        )
        for index, row in enumerate(visible):
            if row.step_id == cursor:
                return index
        try:
            incarnation, layout, offset_text = cursor.split(".", 2)
            offset = int(offset_text)
        except (AttributeError, TypeError, ValueError) as exc:
            raise owned_steps.OwnedStepsError(
                "owned_steps_cursor_invalid",
                parent_id=control.parent_id,
                actions=("refresh", "page"),
            ) from exc
        if (
            incarnation != control.incarnation
            or layout != str(control.layout_revision)
            or offset < 0
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_cursor_stale",
                parent_id=control.parent_id,
                actions=("refresh", "page"),
            )
        return offset

    @staticmethod
    def _owned_view_actions(
        control: owned_steps.OwnedStepsControl,
        row: owned_steps.OwnedStepRecord,
        *,
        can_manage: bool,
    ) -> tuple[str, ...]:
        if not can_manage:
            return ()
        todo = owned_steps.OwnedTodo.model_validate_json(row.todo_json)
        if row.kind == "manual":
            actions: list[str] = ["edit_note"]
            if todo.status in ("pending", "rejected"):
                actions.append("manual_submit")
            elif todo.status == "submitted":
                actions.extend(("manual_confirm", "manual_reject"))
            return tuple(actions)
        if row.permit_state == "unstarted":
            return ("reassign_unstarted", "cancel_execution")
        if row.permit_state == "started":
            actions = ["cancel_execution"]
            if row.booking_id is not None:
                actions.extend(("pause_accounting", "resume_accounting"))
            return tuple(actions)
        if row.permit_state == "interrupted":
            return ("abandon",)
        return ()

    async def capture_owned_steps_view(
        self,
        actual_context: owned_steps.OwnedStepsActualContext,
        *,
        requested_item_id: str,
        cursor: str | None = None,
        presentation_budget: int = owned_steps.MAX_OWNED_VIEW_BYTES,
    ) -> owned_steps.OwnedStepsViewReference:
        """Capture one immutable, attachment-backed, model-bounded owner page."""
        self._require_owned_steps_actual_context(actual_context)
        if (
            type(presentation_budget) is not int
            or not 1 <= presentation_budget <= owned_steps.MAX_OWNED_VIEW_BYTES
            or self._owned_view_store is None
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_view_unavailable",
                parent_id=actual_context.parent_id,
                actions=("view_budget", "inspect_source"),
            )
        resolved = await self._work_item_store.resolve_owned_steps_parent_id(
            requested_item_id
        )
        if resolved != actual_context.parent_id:
            raise owned_steps.OwnedStepsError(
                "owned_steps_scope_conflict",
                parent_id=actual_context.parent_id,
            )
        snapshot = await self._work_item_store.get_owned_steps(resolved)
        if snapshot is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_not_managed",
                parent_id=resolved,
            )
        control = snapshot.control
        source = actual_context.authority_for(self._owned_principal).context
        can_manage = (
            type(source) is owned_steps.OwnedOwnerInvocation
            and source.role in ("captain", "facilitator")
        )
        offset = self._owned_view_offset(control, cursor)
        visible = (
            control.rows[:control.manual_prefix_length]
            if control.mode == "awaiting_adoption"
            else control.rows
        )
        if offset > len(visible):
            raise owned_steps.OwnedStepsError(
                "owned_steps_cursor_invalid",
                parent_id=control.parent_id,
                actions=("refresh", "page"),
            )
        page = visible[offset:offset + owned_steps.MAX_OWNED_VIEW_ROWS]
        view_id = uuid.uuid4().hex
        plan_token = (
            owned_steps.OwnedStepsPlanToken(
                parent_id=control.parent_id,
                incarnation=control.incarnation,
                layout_revision=control.layout_revision,
                plan_revision=control.plan_revision,
                plan_digest=control.plan_digest,
                steps_digest=control.steps_digest,
                source_digest=snapshot.source_digest,
                actor_id=actual_context.actor_id,
                thread_id=actual_context.thread_id,
                view_id=view_id,
                turn_id=actual_context.turn_id,
            )
            if can_manage
            else None
        )
        rendered_rows: list[owned_steps.OwnedStepViewRow] = []
        omitted: list[str] = []
        omitted_offsets: dict[str, int] = {}
        for relative, row in enumerate(page):
            ordinal = offset + relative + 1
            token = (
                owned_steps.StepViewToken(
                    parent_id=control.parent_id,
                    incarnation=control.incarnation,
                    layout_revision=control.layout_revision,
                    plan_revision=control.plan_revision,
                    plan_digest=control.plan_digest,
                    step_id=row.step_id,
                    row_revision=row.revision,
                    row_digest=row.digest,
                    source_digest=row.source_digest,
                    assignment_epoch=row.assignment_epoch,
                    actor_id=actual_context.actor_id,
                    thread_id=actual_context.thread_id,
                    view_id=view_id,
                    turn_id=actual_context.turn_id,
                )
                if can_manage
                else None
            )
            candidate = owned_steps.OwnedStepViewRow(
                step_id=row.step_id,
                ordinal=ordinal,
                kind=row.kind,
                child_id=row.child.child_id if row.child else None,
                revision=row.revision,
                digest=row.digest,
                todo=owned_steps.OwnedTodo.model_validate_json(row.todo_json),
                actions=self._owned_view_actions(
                    control,
                    row,
                    can_manage=can_manage,
                ),
                evidence=owned_steps.OwnedStepViewEvidence(
                    permit_state=row.permit_state,
                    assignment_epoch=row.assignment_epoch,
                    booking_id=row.booking_id,
                    has_submission=row.submission is not None,
                    review_accepted=row.review_accepted,
                ),
                token=token,
                detail_url=(
                    f"/api/work-items/{control.parent_id}/owned-steps"
                    f"?detail={row.step_id}"
                ),
            )
            if len(owned_steps.owned_json_bytes(
                candidate.model_dump(mode="json")
            )) > presentation_budget:
                omitted.append(row.step_id)
                omitted_offsets[row.step_id] = relative
                continue
            rendered_rows.append(candidate)
        recovery: list[str] = []
        if can_manage and not snapshot.projection_matches:
            recovery.extend(("repair_projection", "inspect_source"))
        if can_manage and control.mode not in ("completed", "cancelled"):
            recovery.append("replace_manual_prefix")
        if can_manage and control.mode == "awaiting_adoption":
            recovery.append("preview_adoption")
        if can_manage and control.mode == "interrupted":
            recovery.extend(("interrupted_work", "abandon"))
        if can_manage and control.mode == "waiting_manual_gate":
            recovery.append("manual_gate")
        if can_manage and control.finalization_disposition == "pending":
            recovery.append("finalize")
        if can_manage and control.mode == "active":
            try:
                await self._work_item_store.assert_owned_steps_replan_eligible(
                    control.parent_id
                )
            except owned_steps.OwnedStepsError as exc:
                logger.debug(
                    "Owned replan affordance omitted because eligibility "
                    "failed (%s); no planner action is advertised until the "
                    "managed state changes or is repaired",
                    exc.code,
                )
            else:
                recovery.append("replan_unstarted")
        if omitted:
            recovery.extend(("detail", "view_budget"))
        finalization = control.finalization_disposition or "none"

        consumed = len(page)

        def build(
            rows: tuple[owned_steps.OwnedStepViewRow, ...],
            consumed_rows: int,
        ) -> owned_steps.OwnedStepsView:
            next_offset = offset + consumed_rows
            included = {entry.step_id for entry in rows}
            consumed_page = page[:consumed_rows]
            return owned_steps.OwnedStepsView(
                parent_id=control.parent_id,
                requested_item_id=requested_item_id,
                actor_id=actual_context.actor_id,
                thread_id=actual_context.thread_id,
                turn_id=actual_context.turn_id,
                view_id=view_id,
                mode=control.mode,
                layout_revision=control.layout_revision,
                plan_revision=control.plan_revision,
                plan_digest=control.plan_digest,
                steps_digest=control.steps_digest,
                source_digest=snapshot.source_digest,
                plan_token=plan_token,
                rows=rows,
                previous_cursor=(
                    self._owned_view_cursor(
                        control,
                        max(0, offset - owned_steps.MAX_OWNED_VIEW_ROWS),
                    )
                    if offset
                    else None
                ),
                next_cursor=(
                    self._owned_view_cursor(control, next_offset)
                    if next_offset < len(visible)
                    else None
                ),
                omitted_step_ids=tuple(
                    dict.fromkeys(
                        (
                            *omitted,
                            *(
                                row.step_id
                                for row in consumed_page
                                if row.step_id not in included
                            ),
                        )
                    )
                ),
                recovery=tuple(dict.fromkeys(recovery)),
                finalization=finalization,
            )

        view = build(tuple(rendered_rows), consumed)
        raw = owned_steps.owned_json_bytes(view.model_dump(mode="json"))
        while len(raw) > presentation_budget and rendered_rows:
            deferred = rendered_rows.pop()
            consumed = deferred.ordinal - offset - 1
            omitted = [
                step_id
                for step_id, relative in omitted_offsets.items()
                if relative < consumed
            ]
            view = build(tuple(rendered_rows), consumed)
            raw = owned_steps.owned_json_bytes(view.model_dump(mode="json"))
        if len(raw) > presentation_budget:
            raise owned_steps.OwnedStepsError(
                "owned_steps_view_budget",
                parent_id=control.parent_id,
                view_id=view_id,
                actions=("page", "detail", "view_budget"),
            )
        content_hash = hashlib.sha256(raw).hexdigest()
        await self._owned_view_store.write(
            content_hash,
            raw,
            "application/json",
            origin="agent_artifact",
        )
        stored_size = await self._owned_view_store.size(content_hash)
        stored = await self._owned_view_store.read(content_hash)
        if (
            stored_size != len(raw)
            or stored != raw
            or hashlib.sha256(stored).hexdigest() != content_hash
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_view_content_conflict",
                parent_id=control.parent_id,
                view_id=view_id,
            )
        reference = owned_steps.OwnedStepsViewReference(
            parent_id=control.parent_id,
            actor_id=actual_context.actor_id,
            thread_id=actual_context.thread_id,
            turn_id=actual_context.turn_id,
            view_id=view_id,
            content_hash=content_hash,
        )
        key = (
            actual_context.actor_id,
            actual_context.thread_id,
            actual_context.turn_id,
        )
        registry = self._owned_views.setdefault(key, OrderedDict())
        registry[view_id] = _OwnedViewRegistration(reference, view)
        while len(registry) > 8:
            registry.popitem(last=False)
        return reference

    async def resolve_owned_steps_view(
        self,
        reference: owned_steps.OwnedStepsViewReference,
        actual_context: owned_steps.OwnedStepsActualContext,
    ) -> owned_steps.OwnedStepsView:
        """Resolve only the exact live captured bytes for the actual scope."""
        self._require_owned_steps_actual_context(
            actual_context,
            parent_id=reference.parent_id,
        )
        if (
            reference.actor_id != actual_context.actor_id
            or reference.thread_id != actual_context.thread_id
            or reference.turn_id != actual_context.turn_id
            or self._owned_view_store is None
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_view_scope_conflict",
                parent_id=reference.parent_id,
                view_id=reference.view_id,
            )
        registry = self._owned_views.get(
            (
                actual_context.actor_id,
                actual_context.thread_id,
                actual_context.turn_id,
            )
        )
        registration = registry.get(reference.view_id) if registry else None
        if registration is None or registration.reference != reference:
            raise owned_steps.OwnedStepsError(
                "owned_steps_view_expired",
                parent_id=reference.parent_id,
                view_id=reference.view_id,
                actions=("refresh",),
            )
        try:
            size = await self._owned_view_store.size(reference.content_hash)
            raw = await self._owned_view_store.read(reference.content_hash)
        except FileNotFoundError as exc:
            raise owned_steps.OwnedStepsError(
                "owned_steps_view_missing",
                parent_id=reference.parent_id,
                view_id=reference.view_id,
                actions=("refresh",),
            ) from exc
        if (
            size != len(raw)
            or size > owned_steps.MAX_OWNED_VIEW_BYTES
            or hashlib.sha256(raw).hexdigest() != reference.content_hash
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_view_content_conflict",
                parent_id=reference.parent_id,
                view_id=reference.view_id,
            )
        try:
            resolved = owned_steps.OwnedStepsView.model_validate_json(raw)
        except Exception as exc:
            raise owned_steps.OwnedStepsError(
                "owned_steps_view_schema_invalid",
                parent_id=reference.parent_id,
                view_id=reference.view_id,
            ) from exc
        if resolved != registration.view:
            raise owned_steps.OwnedStepsError(
                "owned_steps_view_content_conflict",
                parent_id=reference.parent_id,
                view_id=reference.view_id,
            )
        return resolved

    async def admit_owned_steps_presentation(
        self,
        reference: owned_steps.OwnedStepsViewReference,
        actual_context: owned_steps.OwnedStepsActualContext,
    ) -> owned_steps.OwnedStepsView:
        """Mark a view authoritative only after complete actual presentation."""
        view = await self.resolve_owned_steps_view(reference, actual_context)
        key = (view.actor_id, view.thread_id, view.turn_id)
        registry = self._owned_views[key]
        registration = registry[view.view_id]
        registry[view.view_id] = replace(registration, presented=True)
        return view

    async def expire_owned_steps_views(
        self,
        actual_context: owned_steps.OwnedStepsActualContext,
        *,
        view_id: str | None = None,
    ) -> int:
        """Remove live viewed authority for one actual turn or one exact view."""
        self._require_owned_steps_actual_context(actual_context)
        key = (
            actual_context.actor_id,
            actual_context.thread_id,
            actual_context.turn_id,
        )
        registry = self._owned_views.get(key)
        if registry is None:
            return 0
        if view_id is None:
            count = len(registry)
            del self._owned_views[key]
            return count
        removed = registry.pop(view_id, None) is not None
        if not registry:
            self._owned_views.pop(key, None)
        return int(removed)

    async def read_owned_steps_detail(
        self,
        actual_context: owned_steps.OwnedStepsActualContext,
        *,
        step_id: str,
    ) -> dict[str, Any]:
        """Return one authenticated full row without granting write authority."""
        self._require_owned_steps_actual_context(actual_context)
        snapshot = await self._work_item_store.get_owned_steps(
            actual_context.parent_id
        )
        if snapshot is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_not_managed",
                parent_id=actual_context.parent_id,
            )
        row = next(
            (entry for entry in snapshot.control.rows if entry.step_id == step_id),
            None,
        )
        if row is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_row_missing",
                parent_id=actual_context.parent_id,
                actions=("refresh", "page"),
            )
        detail = {
            "version": 1,
            "parent_id": actual_context.parent_id,
            "step_id": row.step_id,
            "ordinal": snapshot.control.rows.index(row) + 1,
            "kind": row.kind,
            "child_id": row.child.child_id if row.child else None,
            "revision": row.revision,
            "digest": row.digest,
            "todo": owned_steps.OwnedTodo.model_validate_json(
                row.todo_json
            ).model_dump(mode="json"),
            "evidence": {
                "permit_state": row.permit_state,
                "assignment_epoch": row.assignment_epoch,
                "booking_id": row.booking_id,
                "has_submission": row.submission is not None,
                "review_accepted": row.review_accepted,
            },
            "read_only": True,
        }
        if (
            len(owned_steps.owned_json_bytes(detail))
            > owned_steps.MAX_OWNED_PUBLIC_RESPONSE_BYTES
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_public_response_too_large",
                parent_id=actual_context.parent_id,
                actions=("inspect_source",),
            )
        return detail

    def _presented_registration(
        self,
        reference: owned_steps.OwnedStepsViewReference,
        actual_context: owned_steps.OwnedStepsActualContext,
    ) -> _OwnedViewRegistration:
        self._require_owned_steps_actual_context(
            actual_context,
            parent_id=reference.parent_id,
        )
        registry = self._owned_views.get(
            (
                actual_context.actor_id,
                actual_context.thread_id,
                actual_context.turn_id,
            )
        )
        registration = registry.get(reference.view_id) if registry else None
        if (
            registration is None
            or registration.reference != reference
            or not registration.presented
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_view_unpresented",
                parent_id=reference.parent_id,
                view_id=reference.view_id,
                actions=("refresh",),
            )
        return registration

    def _presented_authority(
        self,
        registration: _OwnedViewRegistration,
        actual_context: owned_steps.OwnedStepsActualContext,
        *,
        operation: str,
        token: object,
    ) -> owned_steps.OwnedStepsAuthority:
        source = actual_context.authority_for(self._owned_principal).context
        if (
            type(source) is not owned_steps.OwnedOwnerInvocation
            or source.role not in ("captain", "facilitator")
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_authority_denied",
                parent_id=registration.reference.parent_id,
            )
        return owned_steps.OwnedStepsAuthority(
            owned_steps.OwnedOwnerInvocation(
                owner=self._owned_principal,
                component=self,
                parent_id=registration.reference.parent_id,
                actor_id=actual_context.actor_id,
                thread_id=actual_context.thread_id,
                role=source.role,
                operation=operation,
                token=token,
                request_digest=registration.reference.content_hash,
            )
        )

    async def _proposal_observation(
        self,
        reference: owned_steps.ViewReference | owned_steps.RepairReference,
        actual_context: owned_steps.OwnedStepsActualContext,
    ) -> owned_steps.RepairObservation:
        self._require_owned_steps_actual_context(
            actual_context,
            parent_id=reference.parent_id,
        )
        if (
            reference.actor_id != actual_context.actor_id
            or reference.thread_id != actual_context.thread_id
            or reference.turn_id != actual_context.turn_id
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_view_scope_conflict",
                parent_id=reference.parent_id,
            )
        if isinstance(reference, owned_steps.OwnedStepsViewReference):
            await self.resolve_owned_steps_view(reference, actual_context)
            self._presented_registration(reference, actual_context)
        observation = (
            await self._work_item_store.capture_owned_steps_repair_observation(
                reference.parent_id,
                actual_context.authority_for_operation(
                    self._owned_principal,
                    operation="capture_repair_observation",
                ),
            )
        )
        if isinstance(reference, owned_steps.RepairReference) and (
            reference.observation_id != observation.observation_id
            or reference.content_hash != observation.source_digest
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_observation_stale",
                parent_id=reference.parent_id,
                view_id=reference.view_id,
                actions=("refresh", "inspect_source"),
            )
        return observation

    async def _build_owned_steps_proposal_manifest(
        self,
        request: (
            owned_steps.AdoptExistingProposalRequest
            | owned_steps.ReplaceManualPrefixProposalRequest
            | owned_steps.ReplanUnstartedProposalRequest
        ),
        observation: owned_steps.RepairObservation,
    ) -> owned_steps.ProposalManifest:
        try:
            parent = await self._work_item_store.get_work_item(
                observation.parent_id
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            parent = None
        if parent is None:
            identity = (
                await self._work_item_store.read_owned_steps_raw_identity(
                    observation.parent_id
                )
            )
            if identity is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_parent_missing",
                    parent_id=observation.parent_id,
                )
            try:
                metadata = json.loads(identity.raw_metadata or "{}")
            except (TypeError, ValueError) as exc:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_source_conflict",
                    parent_id=observation.parent_id,
                ) from exc
            parent = SimpleNamespace(
                id=identity.parent_id,
                title=identity.title,
                description=identity.description,
                created_by=identity.created_by,
                metadata=metadata,
            )
        try:
            snapshot = await self._work_item_store.get_owned_steps(parent.id)
        except owned_steps.OwnedStepsError:
            snapshot = None
        raw_steps = observation.raw_steps
        before_digest = observation.steps_digest
        gate_completion = False
        try:
            raw_metadata = json.loads(observation.source_manifest)
            identity = raw_metadata.get("parent", {})
            metadata_digest = identity.get("metadata_digest")
            gate_completion = bool(
                metadata_digest
                and (parent.metadata or {}).get("steps_gate_completion")
            )
        except (TypeError, ValueError):
            gate_completion = False
        if isinstance(request, owned_steps.AdoptExistingProposalRequest):
            if snapshot is None or snapshot.control.mode != "awaiting_adoption":
                raise owned_steps.OwnedStepsError(
                    "owned_steps_adoption_not_pending",
                    parent_id=parent.id,
                )
            control = snapshot.control
            prefix = control.current_manual_prefix_json()
            suffix = tuple(
                row.todo_json
                for row in control.rows[control.manual_prefix_length:]
            )
            projection = owned_steps.append_owned_rows(prefix, suffix)
            return owned_steps.ProposalManifest(
                kind=request.kind,
                observation_id=observation.observation_id,
                before_digest=before_digest,
                after_digest=owned_steps.owned_digest(projection),
                gate_completion=bool(
                    owned_steps.owned_json_loads(control.gate_json).get(
                        "steps_gate_completion"
                    )
                ),
                manual_count=control.manual_prefix_length,
                child_count=len(suffix),
                retired_count=0,
                before_prefix_json=prefix,
                after_prefix_json=prefix,
                suffix_json=suffix,
                proposed_control_json=None,
                current_child_ids=tuple(
                    row.child.child_id
                    for row in control.rows
                    if row.child is not None
                ),
            )
        if isinstance(request, owned_steps.ReplaceManualPrefixProposalRequest):
            prefix = request.prefix_json
            source_oversized = (
                raw_steps is not None
                and len(raw_steps.encode("utf-8"))
                > owned_steps.MAX_OWNED_MANIFEST_BYTES
            )
            source_malformed = False
            before_prefix = "[]"
            if raw_steps is not None and not source_oversized:
                try:
                    owned_steps.owned_row_spans(raw_steps)
                    before_prefix = raw_steps
                except owned_steps.OwnedStepsError:
                    source_malformed = True
            if snapshot is not None:
                control = snapshot.control
                before_prefix = control.current_manual_prefix_json()
                suffix = tuple(
                    row.todo_json
                    for row in control.rows[control.manual_prefix_length:]
                )
                projection = (
                    prefix
                    if control.mode == "awaiting_adoption"
                    else owned_steps.append_owned_rows(prefix, suffix)
                )
                current_child_ids = tuple(
                    row.child.child_id
                    for row in control.rows
                    if row.child is not None
                )
            else:
                suffix = ()
                projection = prefix
                children = await self._work_item_store.list_work_items(
                    parent_id=parent.id,
                    limit=owned_steps.MAX_OWNED_ROWS + 1,
                )
                if not children or len(children) > owned_steps.MAX_OWNED_ROWS:
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_commitment_conflict",
                        parent_id=parent.id,
                    )
                current_child_ids = tuple(
                    child.id for child in sorted(children, key=lambda item: item.id)
                )
            return owned_steps.ProposalManifest(
                kind=request.kind,
                observation_id=observation.observation_id,
                before_digest=before_digest,
                after_digest=owned_steps.owned_digest(projection),
                gate_completion=gate_completion,
                manual_count=len(owned_steps.owned_row_spans(prefix)),
                child_count=len(current_child_ids),
                retired_count=0,
                before_prefix_json=before_prefix,
                after_prefix_json=prefix,
                suffix_json=suffix,
                proposed_control_json=None,
                current_child_ids=current_child_ids,
                source_malformed=source_malformed,
                source_oversized=source_oversized,
            )

        if snapshot is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_replan_requires_managed_plan",
                parent_id=parent.id,
            )
        control = snapshot.control
        await self._work_item_store.assert_owned_steps_replan_eligible(parent.id)
        decomposer = self._get_decomposer()
        if decomposer is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_planner_unavailable",
                parent_id=parent.id,
            )
        if control.owner_kind == "canonical":
            if self._crew_session_service is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_planner_unavailable",
                    parent_id=parent.id,
                )
            session = await self._crew_session_service.get_session(parent.id)
            recovery = await self._crew_session_service.get_recovery(parent.id)
            if session is None or recovery is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_session_conflict",
                    parent_id=parent.id,
                )
            goal = session.goal
            created_by = session.facilitator_id
        else:
            session = None
            recovery = None
            goal = parent.description or parent.title
            created_by = parent.created_by
        specs = list(await asyncio.to_thread(decomposer.decompose, goal))
        successor = uuid.uuid4().hex
        mapping = {
            spec.spec_id: (
                "rp-"
                + owned_steps.owned_digest(
                    owned_steps.owned_json_bytes(
                        [successor, spec.spec_id]
                    )
                )[:24]
            )
            for spec in specs
        }
        scoped_specs = [
            replace(
                spec,
                spec_id=mapping[spec.spec_id],
                depends_on=tuple(mapping[item] for item in spec.depends_on),
            )
            for spec in specs
        ]
        from probos.cognitive.crew_session import _build_derived_recovery_plan

        plan, inserts = _build_derived_recovery_plan(
            parent.id,
            scoped_specs,
            created_by=created_by,
        )
        proposed_children: list[dict[str, Any]] = []
        for insert, commitment in zip(inserts, plan.children, strict=True):
            todo_json = owned_steps.owned_json_bytes({
                "label": insert.title,
                "status": "pending",
                "assigned_to": insert.assigned_to,
            }).decode("utf-8")
            proposed_children.append({
                "id": insert.id,
                "title": insert.title,
                "description": insert.description,
                "work_type": insert.work_type,
                "priority": insert.priority,
                "depends_on": list(insert.depends_on),
                "assigned_to": insert.assigned_to,
                "created_by": insert.created_by,
                "trust_requirement": insert.trust_requirement,
                "required_capabilities": list(insert.required_capabilities),
                "metadata": insert.metadata,
                "step_id": uuid.uuid4().hex,
                "todo_json": todo_json,
                "commitment": {
                    "child_id": commitment.child_id,
                    "spec_id": commitment.spec_id,
                    "commitment_digest": commitment.row_hash,
                },
            })
        metadata_patch = None
        if session is not None and recovery is not None:
            values = recovery.model_dump(mode="json")
            values.update({
                "phase": (
                    "executing"
                    if session.state == "executing"
                    else "planned"
                ),
                "plan": plan.model_dump(mode="json"),
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
            })
            recovery_type = type(recovery)
            metadata_patch = {
                "crew_recovery": recovery_type.model_validate_json(
                    owned_steps.owned_json_bytes(values)
                ).model_dump(mode="json")
            }
        suffix = tuple(entry["todo_json"] for entry in proposed_children)
        prefix = control.current_manual_prefix_json()
        projection = (
            prefix
            if control.mode == "awaiting_adoption"
            else owned_steps.append_owned_rows(
                prefix,
                suffix,
            )
        )
        current_ids = tuple(
            row.child.child_id
            for row in control.rows
            if row.child is not None
        )
        return owned_steps.ProposalManifest(
            kind=request.kind,
            observation_id=observation.observation_id,
            before_digest=before_digest,
            after_digest=owned_steps.owned_digest(projection),
            gate_completion=bool(
                owned_steps.owned_json_loads(control.gate_json).get(
                    "steps_gate_completion"
                )
            ),
            manual_count=control.manual_prefix_length,
            child_count=len(proposed_children),
            retired_count=len(current_ids),
            successor_incarnation=successor,
            successor_plan_digest=plan.plan_hash,
            successor_seed_digest=plan.plan_seed_hash,
            before_prefix_json=prefix,
            after_prefix_json=prefix,
            suffix_json=suffix,
            proposed_control_json=None,
            current_child_ids=current_ids,
            proposed_children=tuple(proposed_children),
            retired_child_ids=current_ids,
            cancelled_booking_ids=tuple(
                row.booking_id
                for row in control.rows[control.manual_prefix_length:]
                if row.booking_id is not None
            ),
            canonical_metadata_patch=metadata_patch,
            original_spec_mapping=tuple(
                (original, scoped)
                for original, scoped in mapping.items()
            ),
        )

    def _owned_steps_proposal_page(
        self,
        record: owned_steps.ProposalRecord,
        actual_context: owned_steps.OwnedStepsActualContext,
        *,
        cursor: str | None = None,
    ) -> owned_steps.ProposalPage:
        try:
            offset = 0 if cursor is None else int(cursor)
        except (TypeError, ValueError) as exc:
            raise owned_steps.OwnedStepsError(
                "owned_steps_cursor_invalid",
                parent_id=record.claim.parent_id,
            ) from exc
        if offset < 0:
            raise owned_steps.OwnedStepsError(
                "owned_steps_cursor_invalid",
                parent_id=record.claim.parent_id,
            )
        manifest = record.manifest
        digest = record.manifest_digest or owned_steps.owned_digest(b"")
        locator = owned_steps.ProposalLocator(
            parent_id=record.claim.parent_id,
            proposal_id=record.claim.proposal_id,
            manifest_digest=digest,
        )
        reference = None
        rows: list[dict[str, Any]] = []
        omissions: list[str] = []
        total = 0
        if manifest is not None:
            reference = owned_steps.ProposalReference(
                parent_id=record.claim.parent_id,
                actor_id=actual_context.actor_id,
                thread_id=actual_context.thread_id,
                turn_id=actual_context.turn_id,
                view_id=uuid.uuid4().hex,
                content_hash=digest,
                proposal_id=record.claim.proposal_id,
                manifest_digest=digest,
            )
            raw = (
                owned_steps.append_owned_rows(
                    manifest.after_prefix_json,
                    manifest.suffix_json,
                )
                if manifest.kind != "replace_manual_prefix"
                or manifest.suffix_json
                else manifest.after_prefix_json
            )
            try:
                spans = owned_steps.owned_row_spans(raw)
                total = len(spans)
                for ordinal, (start, end) in enumerate(
                    spans[offset:offset + owned_steps.MAX_OWNED_VIEW_ROWS],
                    start=offset + 1,
                ):
                    row_raw = raw[start:end]
                    if len(row_raw.encode("utf-8")) > 4096:
                        omissions.append(f"row:{ordinal}:detail")
                        rows.append({
                            "ordinal": ordinal,
                            "kind": "oversized_row",
                            "digest": owned_steps.owned_digest(row_raw),
                            "read_only": True,
                        })
                        continue
                    rows.append({
                        "ordinal": ordinal,
                        "todo": owned_steps.OwnedTodo.model_validate_json(
                            row_raw
                        ).model_dump(mode="json"),
                    })
            except owned_steps.OwnedStepsError:
                omissions.append("malformed_source_evidence")
            if manifest.source_malformed:
                omissions.append("malformed_source_evidence")
            if manifest.source_oversized:
                omissions.append("oversized_source_evidence")
        next_cursor = (
            str(offset + owned_steps.MAX_OWNED_VIEW_ROWS)
            if offset + owned_steps.MAX_OWNED_VIEW_ROWS < total
            else None
        )
        acknowledgement = (
            owned_steps.owned_json_loads(record.acknowledgement)
            if record.acknowledgement is not None
            else None
        )
        page = owned_steps.ProposalPage(
            proposal=locator,
            reference=reference,
            kind=record.claim.kind,
            state=record.claim.state,
            before_digest=manifest.before_digest if manifest else None,
            after_digest=manifest.after_digest if manifest else None,
            gate_completion=manifest.gate_completion if manifest else None,
            manual_count=manifest.manual_count if manifest else 0,
            child_count=manifest.child_count if manifest else 0,
            retired_count=manifest.retired_count if manifest else 0,
            rows=tuple(rows),
            previous_cursor=(
                str(max(0, offset - owned_steps.MAX_OWNED_VIEW_ROWS))
                if offset
                else None
            ),
            next_cursor=next_cursor,
            coverage={
                "total_rows": total,
                "start_ordinal": rows[0]["ordinal"] if rows else None,
                "end_ordinal": rows[-1]["ordinal"] if rows else None,
                "complete": not omissions and offset == 0 and next_cursor is None,
            },
            omissions=tuple(omissions),
            actions=(
                ("apply", "inspect")
                if record.claim.state == "ready"
                else ("inspect",)
            ),
            error_code=record.error_code,
            acknowledgement=acknowledgement,
        )
        while (
            len(owned_steps.owned_json_bytes(page.model_dump(mode="json")))
            > owned_steps.MAX_OWNED_VIEW_BYTES
            and rows
        ):
            rows.pop()
            next_cursor = str(offset + len(rows))
            page = page.model_copy(update={
                "rows": tuple(rows),
                "next_cursor": next_cursor,
                "omissions": tuple((*omissions, "view_budget")),
                "coverage": {
                    "total_rows": total,
                    "start_ordinal": rows[0]["ordinal"] if rows else None,
                    "end_ordinal": rows[-1]["ordinal"] if rows else None,
                    "complete": False,
                },
            })
        if len(owned_steps.owned_json_bytes(page.model_dump(mode="json"))) > owned_steps.MAX_OWNED_VIEW_BYTES:
            raise owned_steps.OwnedStepsError(
                "owned_steps_view_budget",
                parent_id=record.claim.parent_id,
                actions=("inspect_source", "view_budget"),
            )
        return page

    async def prepare_owned_steps_proposal(
        self,
        request: (
            owned_steps.AdoptExistingProposalRequest
            | owned_steps.ReplaceManualPrefixProposalRequest
            | owned_steps.ReplanUnstartedProposalRequest
            | owned_steps.InspectProposalRequest
        ),
        actual_context: owned_steps.OwnedStepsActualContext,
    ) -> owned_steps.ProposalPage:
        if isinstance(request, owned_steps.InspectProposalRequest):
            return await self.inspect_owned_steps_proposal(
                request.proposal,
                actual_context,
                cursor=request.cursor,
            )
        self._require_owned_steps_actual_context(
            actual_context,
            parent_id=request.reference.parent_id,
        )
        observation = await self._proposal_observation(
            request.reference,
            actual_context,
        )
        request_digest = owned_steps.owned_digest(
            owned_steps.owned_json_bytes(request.model_dump(mode="json"))
        )
        preparation = owned_steps.ProposalPreparation(
            parent_id=request.reference.parent_id,
            preparation_id=request.preparation_id,
            request_digest=request_digest,
            observation_id=observation.observation_id,
            kind=request.kind,
        )
        authority = actual_context.authority_for_operation(
            self._owned_principal,
            operation="claim_proposal",
        )
        claim = await self._work_item_store.claim_owned_steps_proposal(
            preparation,
            authority,
        )
        if claim.is_new:
            try:
                manifest = await self._build_owned_steps_proposal_manifest(
                    request,
                    observation,
                )
                locator = (
                    await self._work_item_store.publish_owned_steps_proposal(
                        claim,
                        manifest,
                        actual_context.authority_for_operation(
                            self._owned_principal,
                            operation="publish_proposal",
                        ),
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                code = (
                    exc.code
                    if isinstance(exc, owned_steps.OwnedStepsError)
                    else "owned_steps_proposal_preparation_failed"
                )
                await self._work_item_store.fail_owned_steps_proposal(
                    claim,
                    code,
                    actual_context.authority_for_operation(
                        self._owned_principal,
                        operation="publish_proposal",
                    ),
                )
                raise
        else:
            locator = owned_steps.ProposalLocator(
                parent_id=claim.parent_id,
                proposal_id=claim.proposal_id,
                manifest_digest=(
                    claim.manifest_digest or owned_steps.owned_digest(b"")
                ),
            )
        return await self.inspect_owned_steps_proposal(
            locator,
            actual_context,
        )

    async def inspect_owned_steps_proposal(
        self,
        locator: owned_steps.ProposalLocator,
        actual_context: owned_steps.OwnedStepsActualContext,
        cursor: str | None = None,
    ) -> owned_steps.ProposalPage:
        self._require_owned_steps_actual_context(
            actual_context,
            parent_id=locator.parent_id,
        )
        record = await self._work_item_store.get_owned_steps_proposal(
            locator,
            actual_context.authority_for_operation(
                self._owned_principal,
                operation="inspect_proposal",
            ),
        )
        return self._owned_steps_proposal_page(
            record,
            actual_context,
            cursor=cursor,
        )

    async def apply_owned_steps_proposal(
        self,
        request: owned_steps.OwnedStepsProposalApplyRequest,
        actual_context: owned_steps.OwnedStepsActualContext,
        *,
        allowed_kinds: frozenset[str] | None = None,
    ) -> owned_steps.OwnedStepMutationResult:
        self._require_owned_steps_actual_context(
            actual_context,
            parent_id=request.reference.parent_id,
        )
        if (
            request.reference.actor_id != actual_context.actor_id
            or request.reference.thread_id != actual_context.thread_id
            or request.reference.turn_id != actual_context.turn_id
            or request.reference.content_hash
            != request.reference.manifest_digest
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_proposal_scope_conflict",
                parent_id=request.reference.parent_id,
            )
        if allowed_kinds is not None:
            record = await self._work_item_store.get_owned_steps_proposal(
                owned_steps.ProposalLocator(
                    parent_id=request.reference.parent_id,
                    proposal_id=request.reference.proposal_id,
                    manifest_digest=request.reference.manifest_digest,
                ),
                actual_context.authority_for_operation(
                    self._owned_principal, operation="inspect_proposal",
                ),
            )
            if record.claim.kind not in allowed_kinds:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_proposal_route_conflict",
                    parent_id=request.reference.parent_id,
                    actions=("inspect_source",),
                )
        return await self._work_item_store.apply_owned_steps_proposal(
            request,
            actual_context.authority_for_operation(
                self._owned_principal,
                operation="apply_proposal",
            ),
        )

    async def preview_owned_steps_adoption(
        self,
        reference: owned_steps.OwnedStepsViewReference,
        actual_context: owned_steps.OwnedStepsActualContext,
    ) -> owned_steps.OwnedStepsAdoptionPreview:
        await self.resolve_owned_steps_view(reference, actual_context)
        registration = self._presented_registration(reference, actual_context)
        token = registration.view.plan_token
        return await self._work_item_store.preview_owned_steps_adoption(
            reference.parent_id,
            authority=self._presented_authority(
                registration,
                actual_context,
                operation="preview_adoption",
                token=None,
            ),
            view_id=reference.view_id,
            turn_id=reference.turn_id,
        )

    async def adopt_owned_steps(
        self,
        request: owned_steps.OwnedStepsAdoptRequest,
        actual_context: owned_steps.OwnedStepsActualContext,
    ) -> owned_steps.OwnedStepMutationResult:
        await self.resolve_owned_steps_view(request.reference, actual_context)
        registration = self._presented_registration(
            request.reference,
            actual_context,
        )
        if request.preview.token != registration.view.plan_token:
            raise owned_steps.OwnedStepsError(
                "owned_steps_adoption_conflict",
                parent_id=request.reference.parent_id,
                view_id=request.reference.view_id,
                actions=("preview_adoption", "refresh"),
            )
        change = owned_steps.OwnedStepChange(
            operation_id=request.operation_id,
            token=request.preview.token,
            command=owned_steps.AdoptOwnedStepsCommand(
                preview=request.preview,
            ),
        )
        return await self._work_item_store.compare_and_set_owned_step(
            owned_steps.OwnedStepMutation(
                change,
                self._presented_authority(
                    registration,
                    actual_context,
                    operation="adopt",
                    token=request.preview.token,
                ),
            )
        )

    async def apply_owned_steps_commands(
        self,
        batch: owned_steps.OwnedStepsCommandBatch,
        actual_context: owned_steps.OwnedStepsActualContext,
    ) -> tuple[owned_steps.OwnedStepMutationResult, ...]:
        await self.resolve_owned_steps_view(batch.reference, actual_context)
        registration = self._presented_registration(
            batch.reference,
            actual_context,
        )
        view = registration.view
        rows = {row.step_id: row for row in view.rows}
        mutations: list[owned_steps.OwnedStepMutation] = []
        for requested in batch.commands:
            if isinstance(requested, owned_steps.OwnedStepsHttpPlanCommand):
                if requested.kind not in view.recovery:
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_hidden_or_unpresented",
                        parent_id=view.parent_id,
                        view_id=view.view_id,
                        actions=("refresh", "inspect_source"),
                    )
                command: owned_steps.OwnedStepsCommand = (
                    owned_steps.RepairOwnedStepsCommand(
                        observed_steps_digest=requested.observed_steps_digest,
                    )
                )
                token: (
                    owned_steps.StepViewToken
                    | owned_steps.OwnedStepsPlanToken
                ) = view.plan_token
                if token is None:
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_hidden_or_unpresented",
                        parent_id=view.parent_id,
                        view_id=view.view_id,
                        actions=("refresh",),
                    )
            else:
                presented = rows.get(requested.step_id)
                if (
                    presented is None
                    or presented.token is None
                    or requested.kind not in presented.actions
                ):
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_hidden_or_unpresented",
                        parent_id=view.parent_id,
                        view_id=view.view_id,
                        actions=("page", "detail", "refresh"),
                    )
                token = presented.token
                if requested.kind in {
                    "manual_submit",
                    "manual_confirm",
                    "manual_reject",
                    "edit_note",
                }:
                    command = owned_steps.ManualStepCommand(
                        kind=requested.kind,
                        note=requested.note,
                    )
                elif requested.kind == "reassign_unstarted":
                    command = owned_steps.ReassignOwnedStepCommand(
                        assignee_id=requested.assignee_id,
                    )
                elif requested.kind == "cancel_execution":
                    command = owned_steps.CancelOwnedStepCommand()
                elif requested.kind == "abandon":
                    command = owned_steps.AbandonOwnedStepCommand()
                else:
                    command = owned_steps.AccountingOwnedStepCommand(
                        kind=requested.kind,
                        booking_id=requested.booking_id,
                        resource_id=requested.resource_id,
                    )
            change = owned_steps.OwnedStepChange(
                operation_id=requested.operation_id,
                token=token,
                command=command,
            )
            mutations.append(
                owned_steps.OwnedStepMutation(
                    change,
                    self._presented_authority(
                        registration,
                        actual_context,
                        operation=command.kind,
                        token=token,
                    ),
                )
            )
        return await self._work_item_store.compare_and_set_owned_steps_batch(
            tuple(mutations)
        )

    async def finalize_owned_steps(
        self,
        reference: owned_steps.OwnedStepsViewReference,
        actual_context: owned_steps.OwnedStepsActualContext,
    ) -> object:
        await self.resolve_owned_steps_view(reference, actual_context)
        self._presented_registration(reference, actual_context)
        snapshot = await self._work_item_store.get_owned_steps(
            reference.parent_id
        )
        if snapshot is None or snapshot.control.finalization is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_finalization_unavailable",
                parent_id=reference.parent_id,
                view_id=reference.view_id,
                actions=("inspect_source",),
            )
        if snapshot.control.owner_kind == "canonical":
            if self._crew_session_finalizer is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_finalization_unavailable",
                    parent_id=reference.parent_id,
                )
            return await self._crew_session_finalizer.finalize_from_receipt(
                snapshot.control.finalization
            )
        return await self._recover_owned_legacy(snapshot)

    def _owned_authority(
        self,
        *,
        parent_id: str,
        thread_id: str,
        operation: str,
        token: object,
        actor_id: str = "crew_orchestrator",
        role: str = "owner",
        component: object | None = None,
    ) -> owned_steps.OwnedStepsAuthority:
        selected = self if component is None else component
        if role not in self._owned_components.get(selected, frozenset()):
            raise owned_steps.OwnedStepsError(
                "owned_steps_authority_denied",
                parent_id=parent_id,
            )
        return owned_steps.OwnedStepsAuthority(
            owned_steps.OwnedOwnerInvocation(
                owner=self._owned_principal,
                component=selected,
                parent_id=parent_id,
                actor_id=actor_id,
                thread_id=thread_id,
                role=role,
                operation=operation,
                token=token,
            )
        )

    def owned_steps_authority(
        self,
        component: object,
        *,
        parent_id: str,
        actor_id: str,
        thread_id: str,
        role: str,
        operation: str,
        token: object,
    ) -> owned_steps.OwnedStepsAuthority:
        """Issue one server-component capability for an exact legacy action."""
        return self._owned_authority(
            parent_id=parent_id,
            thread_id=thread_id,
            operation=operation,
            token=token,
            actor_id=actor_id,
            role=role,
            component=component,
        )

    async def authorize_owned_steps(
        self,
        authority: owned_steps.OwnedStepsAuthority,
        *,
        parent_id: str,
        operation: str,
        token: (
            owned_steps.StepViewToken
            | owned_steps.OwnedStepsPlanToken
            | owned_steps.OwnedStepExecutionPermit
            | None
        ),
    ) -> owned_steps.OwnedStepsGrant:
        human_operations = {
            "read_owned_steps",
            "preview_adoption",
            "adopt",
            "manual_submit",
            "manual_confirm",
            "manual_reject",
            "edit_note",
            "repair_projection",
            "reassign_unstarted",
            "cancel_execution",
            "pause_accounting",
            "resume_accounting",
            "replace_manual_prefix",
            "replan_unstarted",
            "abandon",
            "finalize",
        }
        context = authority.context
        if operation in human_operations and (
            type(context) is not owned_steps.OwnedOwnerInvocation
            or context.owner is not self._owned_principal
            or context.role in ("captain", "facilitator")
        ):
            if (
                type(context) is owned_steps.OwnedOwnerInvocation
                and context.owner is self._owned_principal
                and context.component is self
                and context.role in ("captain", "facilitator")
                and context.parent_id == parent_id
                and context.operation == operation
                and context.token == token
            ):
                registry = self._owned_views.get(
                    (context.actor_id, context.thread_id, token.turn_id)
                    if isinstance(
                        token,
                        (
                            owned_steps.StepViewToken,
                            owned_steps.OwnedStepsPlanToken,
                        ),
                    )
                    else None
                )
                registration = None
                if registry is not None and isinstance(
                    token,
                    (
                        owned_steps.StepViewToken,
                        owned_steps.OwnedStepsPlanToken,
                    ),
                ):
                    registration = registry.get(token.view_id)
                elif token is None:
                    matches = [
                        entry
                        for entries in self._owned_views.values()
                        for entry in entries.values()
                        if (
                            entry.reference.parent_id == parent_id
                            and entry.reference.actor_id == context.actor_id
                            and entry.reference.thread_id == context.thread_id
                            and entry.reference.content_hash
                            == context.request_digest
                        )
                    ]
                    registration = matches[0] if len(matches) == 1 else None
                valid_token = (
                    token is None
                    or (
                        registration is not None
                        and (
                            token == registration.view.plan_token
                            or token
                            in tuple(
                                row.token
                                for row in registration.view.rows
                                if row.token is not None
                            )
                        )
                    )
                )
                if (
                    registration is not None
                    and registration.presented
                    and registration.reference.content_hash
                    == context.request_digest
                    and valid_token
                ):
                    return owned_steps.OwnedStepsGrant(
                        parent_id,
                        context.actor_id,
                        context.thread_id,
                        context.role,
                    )
                raise owned_steps.OwnedStepsError(
                    "owned_steps_view_unpresented",
                    parent_id=parent_id,
                    actions=("refresh",),
                )
            if self._owned_human_authorizer is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_authority_denied",
                    parent_id=parent_id,
                )
            return await self._owned_human_authorizer.authorize_owned_steps(
                authority,
                parent_id=parent_id,
                operation=operation,
                token=token,
            )
        context = authority.context
        if (
            type(context) is not owned_steps.OwnedOwnerInvocation
            or context.owner is not self._owned_principal
            or context.role
            not in self._owned_components.get(context.component, frozenset())
            or context.parent_id != parent_id
            or context.operation != operation
            or context.token != token
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_authority_denied",
                parent_id=parent_id,
            )
        allowed = {
            "owner": {
                "start_parent",
                "begin_synthesis",
                "reassign_unstarted",
                "finalize",
                "claim_effect",
            },
            "verifier": {
                "record_review",
                "admit_correction",
                "record_correction",
                "execution_active",
            },
            "ttl": {"cancel_execution"},
        }
        if operation not in allowed.get(context.role, set()):
            raise owned_steps.OwnedStepsError(
                "owned_steps_authority_denied",
                parent_id=parent_id,
            )
        return owned_steps.OwnedStepsGrant(
            parent_id,
            context.actor_id,
            context.thread_id,
            context.role,
        )

    async def owned_manual_gate_released(self, parent_id: str) -> None:
        snapshot = await self._work_item_store.get_owned_steps(parent_id)
        if (
            snapshot is None
            or snapshot.control.owner_kind != "legacy"
            or snapshot.control.finalization is None
            or snapshot.control.finalization_disposition != "pending"
            or any(
                owned_steps.owned_json_loads(row.todo_json)["status"] != "done"
                for row in snapshot.control.rows[
                    :snapshot.control.manual_prefix_length
                ]
            )
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_continuation_invalid",
                parent_id=parent_id,
            )
        self.schedule(parent_id, continuation=True)

    async def authorize_owned_store_write(
        self,
        binding: owned_steps.OwnedStoreBinding,
    ) -> owned_steps.OwnedStepsGrant:
        context = binding.authority.context
        if (
            type(context) is not owned_steps.OwnedOwnerInvocation
            or context.request_digest != binding.request_digest
        ):
            raise owned_steps.OwnedStepsError("owned_steps_authority_denied")
        return await self.authorize_owned_steps(
            binding.authority,
            parent_id=binding.snapshot.control.parent_id,
            operation=binding.operation,
            token=binding.snapshot,
        )

    async def expire_owned_steps(
        self,
        work_item_id: str,
        observed_at: float,
    ) -> bool:
        snapshot = await self._work_item_store.get_owned_steps(work_item_id)
        if snapshot is None or snapshot.control.owner_kind != "legacy":
            return False
        rows = tuple(
            row
            for row in snapshot.control.rows
            if row.child is not None
            and (
                work_item_id == snapshot.control.parent_id
                or row.child.child_id == work_item_id
            )
        )
        changed = False
        for row in rows:
            token = owned_steps.execution_step_token(
                owned_steps.OwnedExecutionLease(
                    snapshot,
                    self._owned_authority(
                        parent_id=snapshot.control.parent_id,
                        thread_id=snapshot.control.thread_id,
                        operation="cancel_execution",
                        token=snapshot,
                        actor_id="crew_orchestrator",
                        role="ttl",
                    ),
                ),
                row,
            ).model_copy(update={"actor_id": "crew_orchestrator"})
            result = await self._work_item_store.compare_and_set_owned_step(
                owned_steps.OwnedStepMutation(
                    owned_steps.OwnedStepChange(
                        operation_id=owned_steps.owned_digest(
                            owned_steps.owned_json_bytes(
                                [
                                    "ttl",
                                    snapshot.control.incarnation,
                                    row.step_id,
                                    work_item_id,
                                    observed_at,
                                ]
                            )
                        ),
                        token=token,
                        command=owned_steps.CancelOwnedStepCommand(
                            expired_item_id=work_item_id,
                            observed_at=observed_at,
                        ),
                    ),
                    self._owned_authority(
                        parent_id=snapshot.control.parent_id,
                        thread_id=snapshot.control.thread_id,
                        operation="cancel_execution",
                        token=token,
                        actor_id="crew_orchestrator",
                        role="ttl",
                    ),
                )
            )
            changed = changed or result.disposition == "applied"
        return changed

    # ------------------------------------------------------------------ pipeline

    async def run_crew_task(self, parent_id: str) -> SynthesisResult:
        """Thread resolve -> delegate -> fan-out -> verify -> synthesize for one
        parent task, propagating durable-session integrity failures."""
        try:
            parent = await self._work_item_store.get_work_item(parent_id)
        except Exception:
            logger.warning(
                "AD-1125: parent classification failed for %s; no generic "
                "promotion or crew work will run because session-state ownership "
                "cannot be determined safely",
                parent_id,
                exc_info=True,
            )
            return SynthesisResult(
                parent_id=parent_id,
                final_output="",
                completed=False,
                accepted_count=0,
                total_count=0,
            )
        is_crew_session = bool(
            parent is not None and parent.work_type == "crew_session"
        )
        if (
            parent is not None
            and not is_crew_session
            and self._legacy_owned_port is not None
        ):
            return await self._run_owned_legacy_parent(parent)
        if not is_crew_session:
            # Legacy AD-867 glue: move open -> in_progress so the synthesizer's
            # in_progress -> done completion remains valid.
            await self._promote_parent(parent_id)

        children = await self._load_children(parent_id)
        self._emit(EventType.CREW_ORCHESTRATION_STARTED, {
            "parent_id": parent_id,
            "child_count": len(children),
        })

        # Stage 1: resolve + delegate + persist assignment per child.
        if not is_crew_session:
            for child in children:
                await self._assign_child(child)

        # Stage 2: fan-out execution (existing AD-859 executor). A confirmed
        # durable session must preserve room/service integrity errors; legacy
        # parents retain the AD-867 honest-degrade boundary.
        if is_crew_session:
            results = await self._crew_executor.run(parent_id)
        else:
            results = await self._execute(parent_id)

        if is_crew_session:
            if self._crew_session_finalizer is not None:
                finalized = await self._crew_session_finalizer.finalize(
                    parent_id,
                    results,
                )
                return SynthesisResult(
                    parent_id=parent_id,
                    final_output=(
                        finalized.final_output if finalized.completed else ""
                    ),
                    completed=finalized.completed,
                    shapley_values={},
                    provenance_ref=(
                        finalized.provenance_ref if finalized.completed else None
                    ),
                    accepted_count=finalized.accepted_count,
                    total_count=finalized.total_count,
                )
            return SynthesisResult(
                parent_id=parent_id,
                final_output="",
                completed=False,
                accepted_count=0,
                total_count=len(results),
            )

        # Stage 3: independent verification of each successful subtask.
        outcomes = await self._verify(results)

        # Stage 4: synthesis (existing AD-861 synthesizer — parent completion,
        # Shapley, episode, provenance).
        return await self._synthesize(parent_id, outcomes)

    # --------------------------------------------------------------- stage impl

    async def _run_owned_legacy_parent(
        self,
        parent: "WorkItem",
    ) -> SynthesisResult:
        parent_id = parent.id
        existing = await self._work_item_store.get_owned_steps(parent_id)
        if existing is not None:
            if existing.control.finalization is not None:
                return await self._recover_owned_legacy(existing)
            if (
                await self._work_item_store.get_owned_synthesis_claim(parent_id)
                is not None
            ):
                return SynthesisResult(
                    parent_id=parent_id,
                    final_output="",
                    completed=False,
                    total_count=sum(
                        row.child is not None
                        for row in existing.control.rows
                    ),
                    disposition="pending",
                )
        if existing is not None:
            membership = await self._work_item_store.get_owned_crew_children(
                parent_id,
                existing.control.plan_digest,
            )
            children = list(membership.active)
        else:
            children = await self._work_item_store.list_work_items(
                parent_id=parent_id,
                limit=1001,
            )
        if len(children) > 1000:
            raise owned_steps.OwnedStepsError(
                "owned_steps_rows_invalid",
                parent_id=parent_id,
            )
        execution_port = getattr(
            self._crew_executor,
            "owned_steps_execution_port",
            None,
        )
        port = execution_port() if callable(execution_port) else None
        if port is not None and port is not self._legacy_owned_port:
            self._legacy_owned_port = port
            bind_corrections = getattr(
                self._verifier,
                "bind_owned_steps_correction_port",
                None,
            )
            if callable(bind_corrections):
                correction_port = _LegacyCorrectionPort(
                    store=self._work_item_store,
                    execution=port,
                    authority=self.owned_steps_authority,
                    component_allowed=lambda component: (
                        "verifier"
                        in self._owned_components.get(
                            component,
                            frozenset(),
                        )
                    ),
                )
                self._owned_components[correction_port] = frozenset(
                    {"verifier"}
                )
                self._legacy_correction_port = correction_port
                bind_corrections(correction_port)
        assert port is not None
        assignment_decisions: dict[str, Any] = {}
        prospective_children: list["WorkItem"] = []
        for child in children:
            if child.assigned_to is not None:
                prospective_children.append(child)
                continue
            decision = self._assignment_resolver.resolve(
                self._spec_view(child)
            )
            assignment_decisions[child.id] = decision
            prospective_children.append(
                replace(child, assigned_to=decision.agent_id)
                if decision.agent_id is not None
                else child
            )
        resolved_thread = await self._crew_executor.resolve_task_room(
            parent,
            prospective_children,
        )
        thread_id = resolved_thread.id if resolved_thread is not None else ""
        lease = await port.admit(
            parent_id,
            children=tuple(children),
            thread_id=thread_id,
        )
        snapshot = lease.snapshot
        control = snapshot.control
        if control.finalization is not None:
            return await self._recover_owned_legacy(snapshot)
        if (
            await self._work_item_store.get_owned_synthesis_claim(parent_id)
            is not None
        ):
            return SynthesisResult(
                parent_id=parent_id,
                final_output="",
                completed=False,
                total_count=len(children),
                disposition="pending",
            )
        if control.mode == "awaiting_adoption":
            return SynthesisResult(
                parent_id=parent_id,
                final_output="",
                completed=False,
                total_count=len(children),
                disposition="pending",
            )
        if control.mode != "active" or any(
            row.child is not None
            and row.permit_state in {"started", "interrupted"}
            and row.submission is None
            for row in control.rows
        ):
            return SynthesisResult(
                parent_id=parent_id,
                final_output="",
                completed=False,
                total_count=len(children),
                disposition="pending",
            )
        for child in children:
            if child.assigned_to is None:
                await self._assign_owned_legacy_child(
                    parent_id,
                    child,
                    snapshot,
                    assignment_decisions[child.id],
                )
        snapshot = await self._work_item_store.get_owned_steps(parent_id)
        if snapshot is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_execution_scope_denied",
                parent_id=parent_id,
            )
        snapshot = await self._work_item_store.start_owned_legacy_parent(
            snapshot,
            self._owned_authority(
                parent_id=parent_id,
                thread_id=control.thread_id,
                operation="start_parent",
                token=snapshot,
            ),
        )
        self._emit(
            EventType.CREW_ORCHESTRATION_STARTED,
            {
                "parent_id": parent_id,
                "child_count": len(children),
            },
        )
        results = await self._crew_executor.run(parent_id)
        outcomes = await self._review_owned_legacy_results(
            parent_id,
            results,
        )
        current = await self._work_item_store.get_owned_steps(parent_id)
        if current is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_execution_scope_denied",
                parent_id=parent_id,
            )
        return await self._synthesizer.synthesize_owned_legacy(
            parent_id,
            outcomes,
            token=self._owned_plan_token(current),
            authority_factory=lambda operation, token: self._owned_authority(
                parent_id=parent_id,
                thread_id=current.control.thread_id,
                operation=operation,
                token=token,
            ),
        )

    async def _recover_owned_legacy(
        self,
        snapshot: owned_steps.OwnedStepsSnapshot,
    ) -> SynthesisResult:
        receipt = snapshot.control.finalization
        if receipt is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_finalization_state",
                parent_id=snapshot.control.parent_id,
            )
        token = self._owned_plan_token(snapshot)
        return await self._synthesizer.finalize_from_receipt(
            receipt,
            token=token,
            authority=self._owned_authority(
                parent_id=snapshot.control.parent_id,
                thread_id=snapshot.control.thread_id,
                operation="finalize",
                token=token,
            ),
            source_review_digest=receipt.source_review_digest,
        )

    async def _assign_owned_legacy_child(
        self,
        parent_id: str,
        child: "WorkItem",
        captured: owned_steps.OwnedStepsSnapshot,
        decision: Any,
    ) -> None:
        row = next(
            (
                row
                for row in captured.control.rows
                if row.child is not None and row.child.child_id == child.id
            ),
            None,
        )
        if row is None or row.permit_state != "unstarted":
            raise owned_steps.OwnedStepsError(
                "owned_steps_reassignment_conflict",
                parent_id=parent_id,
            )
        delegation = self._delegator.delegate(decision)
        if not delegation.worker_agent_id:
            return
        metadata_patch = {
            "chief_agent_id": delegation.chief_agent_id,
            "order_id": delegation.order_id,
            "delegated": delegation.delegated,
            "delegation_reason": delegation.reason,
            "assigned_capability": decision.capability,
            "assigned_department": decision.department,
        }
        token = owned_steps.execution_step_token(
            owned_steps.OwnedExecutionLease(
                captured,
                self._owned_authority(
                    parent_id=parent_id,
                    thread_id=captured.control.thread_id,
                    operation="reassign_unstarted",
                    token=captured,
                ),
            ),
            row,
        ).model_copy(update={"actor_id": "crew_orchestrator"})
        await self._work_item_store.compare_and_set_owned_step(
            owned_steps.OwnedStepMutation(
                owned_steps.OwnedStepChange(
                    operation_id=owned_steps.owned_digest(
                        owned_steps.owned_json_bytes(
                            [
                                "legacy_assignment",
                                captured.control.incarnation,
                                row.step_id,
                                row.assignment_epoch,
                                delegation.worker_agent_id,
                                metadata_patch,
                            ]
                        )
                    ),
                    token=token,
                    command=owned_steps.ReassignOwnedStepCommand(
                        assignee_id=delegation.worker_agent_id,
                        metadata_patch=metadata_patch,
                    ),
                ),
                self._owned_authority(
                    parent_id=parent_id,
                    thread_id=captured.control.thread_id,
                    operation="reassign_unstarted",
                    token=token,
                ),
            )
        )

    async def _review_owned_legacy_results(
        self,
        parent_id: str,
        results: list[SubtaskResult],
    ) -> list[ConvergenceOutcome]:
        by_child = {result.work_item_id: result for result in results}
        snapshot = await self._work_item_store.get_owned_steps(parent_id)
        if snapshot is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_execution_scope_denied",
                parent_id=parent_id,
            )
        outcomes: list[ConvergenceOutcome] = []
        for row in snapshot.control.rows:
            if row.child is None or row.submission is None:
                continue
            if row.reviewed_result is not None:
                outcomes.append(
                    await self._read_owned_legacy_outcome(snapshot, row)
                )
                continue
            result = by_child.get(row.child.child_id)
            if result is None or result.status != "done":
                continue
            outcome = await self._verifier.converge(
                result,
                owned_steps_snapshot=snapshot,
            )
            if not outcome.verdict.verifier_agent_id:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_review_conflict",
                    parent_id=parent_id,
                )
            await self._persist_owned_legacy_review(
                snapshot,
                row,
                outcome,
            )
            outcomes.append(outcome)
            refreshed = await self._work_item_store.get_owned_steps(parent_id)
            if refreshed is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_execution_scope_denied",
                    parent_id=parent_id,
                )
            snapshot = refreshed
        return outcomes

    async def _persist_owned_legacy_review(
        self,
        snapshot: owned_steps.OwnedStepsSnapshot,
        row: owned_steps.OwnedStepRecord,
        outcome: ConvergenceOutcome,
    ) -> None:
        result, verdict = outcome.result, outcome.verdict
        submission = await self._work_item_store.get_owned_step_evidence(
            snapshot.control.parent_id,
            snapshot.control.incarnation,
            "submission",
            row.submission,
        )
        writer = getattr(self._synthesizer, "write_owned_steps_content", None)
        if not callable(writer):
            raise owned_steps.OwnedStepsError(
                "owned_steps_content_unavailable",
                parent_id=snapshot.control.parent_id,
            )
        reviewed = self._owned_execution_result(result)
        reviewed_ref = await writer(
            reviewed.model_dump_json().encode("utf-8"),
            mime="application/json",
            origin="crew_verifier_owned_result",
        )
        verification_payload = {
            "accepted": verdict.accepted,
            "confidence": verdict.confidence,
            "critique": verdict.critique,
            "verifier_agent_id": verdict.verifier_agent_id,
            "verification_defect": verdict.verification_defect,
            "criteria": (
                criteria_to_json(verdict.criteria)
                if verdict.criteria is not None
                else None
            ),
            "rounds": outcome.rounds,
            "parent_id": snapshot.control.parent_id,
            "work_item_id": result.work_item_id,
            "thread_id": snapshot.control.thread_id,
            "producer_agent_id": result.agent_id,
        }
        verification_ref = await writer(
            owned_steps.owned_json_bytes(verification_payload),
            mime="application/json",
            origin="crew_verifier_owned_verdict",
        )
        review_attempt_id = owned_steps.owned_digest(
            owned_steps.owned_json_bytes(
                [
                    "legacy_review",
                    snapshot.control.incarnation,
                    row.step_id,
                    row.submission,
                    verdict.verifier_agent_id,
                ]
            )
        )
        review = owned_steps.ReviewedStepResult(
            submission_digest=row.submission,
            permit=submission.permit,
            reviewed_result=reviewed_ref,
            verification=verification_ref,
            reviewer_id=verdict.verifier_agent_id,
            review_attempt_id=review_attempt_id,
            accepted=verdict.accepted,
        )
        await self._work_item_store.compare_and_set_owned_step(
            owned_steps.OwnedStepMutation(
                owned_steps.OwnedStepChange(
                    operation_id=review_attempt_id,
                    token=submission.permit,
                    command=owned_steps.ReviewOwnedStepCommand(result=review),
                ),
                self._owned_authority(
                    parent_id=snapshot.control.parent_id,
                    thread_id=snapshot.control.thread_id,
                    operation="record_review",
                    token=submission.permit,
                    actor_id=verdict.verifier_agent_id,
                    role="verifier",
                    component=self._verifier,
                ),
            )
        )

    async def record_legacy_convergence(
        self,
        parent_id: str,
        outcome: ConvergenceOutcome,
    ) -> None:
        """Persist one public legacy convergence outcome before synthesis."""
        snapshot = await self._work_item_store.get_owned_steps(parent_id)
        if snapshot is None or snapshot.control.owner_kind != "legacy":
            raise owned_steps.OwnedStepsError(
                "owned_steps_execution_scope_denied",
                parent_id=parent_id,
            )
        row = next(
            (
                row
                for row in snapshot.control.rows
                if row.child is not None
                and row.child.child_id == outcome.result.work_item_id
            ),
            None,
        )
        if row is None or row.submission is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_review_conflict",
                parent_id=parent_id,
            )
        await self._persist_owned_legacy_review(
            snapshot,
            row,
            outcome,
        )

    async def _read_owned_legacy_outcome(
        self,
        snapshot: owned_steps.OwnedStepsSnapshot,
        row: owned_steps.OwnedStepRecord,
    ) -> ConvergenceOutcome:
        review = await self._work_item_store.get_owned_step_evidence(
            snapshot.control.parent_id,
            snapshot.control.incarnation,
            "review",
            row.reviewed_result,
        )
        result_bytes = await self._work_item_store.read_owned_steps_content(
            review.reviewed_result
        )
        verification_bytes = await self._work_item_store.read_owned_steps_content(
            review.verification
        )
        private_result = owned_steps.OwnedExecutionResult.model_validate_json(
            result_bytes
        )
        verification = owned_steps.owned_json_loads(
            verification_bytes.decode("utf-8", errors="strict")
        )
        criteria = (
            parse_criteria(verification["criteria"])
            if verification.get("criteria") is not None
            else None
        )
        result = SubtaskResult(
            work_item_id=private_result.work_item_id,
            spec_id=private_result.spec_id,
            agent_id=private_result.agent_id,
            output=private_result.output,
            status=private_result.status,
            tool_trace_ref=private_result.tool_trace_ref,
            started_at=private_result.started_at,
            finished_at=private_result.finished_at,
            stopped_reason=private_result.stopped_reason,
            actual_tokens=private_result.actual_tokens,
            artifact_refs=[
                reference.model_dump(mode="json")
                for reference in private_result.artifact_refs
            ],
            blocked_dependency_ids=list(
                private_result.blocked_dependency_ids
            ),
        )
        verdict = VerificationVerdict(
            accepted=verification["accepted"],
            confidence=verification["confidence"],
            critique=verification["critique"],
            verifier_agent_id=verification["verifier_agent_id"],
            verification_defect=verification["verification_defect"],
            criteria=criteria,
        )
        return ConvergenceOutcome(
            result=result,
            verdict=verdict,
            status=(
                _STATUS_CONVERGED
                if verdict.accepted
                else _STATUS_UNVERIFIED
            ),
            rounds=verification["rounds"],
        )

    @staticmethod
    def _owned_execution_result(
        result: SubtaskResult,
    ) -> owned_steps.OwnedExecutionResult:
        return owned_steps.OwnedExecutionResult(
            work_item_id=result.work_item_id,
            spec_id=result.spec_id,
            agent_id=result.agent_id,
            output=result.output,
            status=result.status,
            tool_trace_ref=result.tool_trace_ref,
            started_at=result.started_at,
            finished_at=result.finished_at,
            stopped_reason=result.stopped_reason,
            actual_tokens=result.actual_tokens,
            artifact_refs=tuple(
                owned_steps.OwnedArtifactReference.model_validate(reference)
                for reference in result.artifact_refs
            ),
            blocked_dependency_ids=tuple(result.blocked_dependency_ids),
        )

    @staticmethod
    def _owned_plan_token(
        snapshot: owned_steps.OwnedStepsSnapshot,
    ) -> owned_steps.OwnedStepsPlanToken:
        control = snapshot.control
        return owned_steps.OwnedStepsPlanToken(
            parent_id=control.parent_id,
            incarnation=control.incarnation,
            layout_revision=control.layout_revision,
            plan_revision=control.plan_revision,
            plan_digest=control.plan_digest,
            steps_digest=control.steps_digest,
            source_digest=snapshot.source_digest,
            actor_id="crew_orchestrator",
            thread_id=control.thread_id,
            view_id="legacy-owner",
            turn_id=control.incarnation,
        )

    async def _promote_parent(self, parent_id: str) -> None:
        """Transition the parent ``open -> in_progress`` (honest-degrade)."""
        try:
            parent = await self._work_item_store.get_work_item(parent_id)
            if parent is None:
                logger.warning(
                    "AD-867: parent %s not found; crew pipeline will degrade to "
                    "an empty synthesis",
                    parent_id,
                )
                return
            if parent.status != "open":
                return
            # BF-608: ``task`` ``open -> in_progress`` requires an owner. The
            # crew parent is a coordination container — its children carry the
            # real per-agent assignments, so it has no single worker. Claim it
            # for the orchestrating subsystem before promoting; otherwise the
            # BF-608 store guard refuses the unassigned transition and the
            # parent can never reach in_progress (and thus never ``done``).
            if parent.assigned_to is None:
                await self._work_item_store.update_work_item(
                    parent_id, assigned_to="crew_orchestrator",
                )
            moved = await self._work_item_store.transition_work_item(
                parent_id, "in_progress", source="crew_orchestrator",
            )
            if moved is None:
                logger.warning(
                    "AD-867: could not promote parent %s open->in_progress "
                    "(likely missing assignment); synthesis completion may degrade",
                    parent_id,
                )
        except Exception:
            logger.warning(
                "AD-867: parent promotion failed for %s; continuing with the "
                "crew pipeline (synthesis completion may degrade)",
                parent_id, exc_info=True,
            )

    async def _load_children(self, parent_id: str) -> list["WorkItem"]:
        """List the parent's children (honest-degrade to ``[]``)."""
        try:
            snapshot = await self._work_item_store.get_owned_steps(parent_id)
            if snapshot is not None:
                membership = await self._work_item_store.get_owned_crew_children(
                    parent_id,
                    snapshot.control.plan_digest,
                )
                return list(membership.active)
            return await self._work_item_store.list_work_items(
                parent_id=parent_id, limit=1000,
            )
        except Exception:
            logger.warning(
                "AD-867: failed to list children for parent %s; crew pipeline "
                "will degrade to an empty run",
                parent_id, exc_info=True,
            )
            return []

    async def _assign_child(self, child: "WorkItem") -> None:
        """Resolve + delegate + persist the assignment for one child.

        Honest-degrade: an unresolved child stays unassigned (the AD-859 executor
        fails it without aborting its siblings).
        """
        try:
            spec_view = self._spec_view(child)
            decision = self._assignment_resolver.resolve(spec_view)
            delegation = self._delegator.delegate(decision)
            if not delegation.worker_agent_id:
                logger.debug(
                    "AD-867: child %s unresolved (%s); leaving unassigned",
                    child.id, delegation.reason,
                )
                return
            existing = dict(child.metadata or {})
            existing.update({
                "chief_agent_id": delegation.chief_agent_id,
                "order_id": delegation.order_id,
                "delegated": delegation.delegated,
                "delegation_reason": delegation.reason,
                "assigned_capability": decision.capability,
                "assigned_department": decision.department,
            })
            await self._work_item_store.update_work_item(
                child.id,
                assigned_to=delegation.worker_agent_id,
                metadata=existing,
            )
        except Exception:
            logger.warning(
                "AD-867: assignment failed for child %s; leaving it unassigned "
                "(executor will fail it without aborting siblings)",
                getattr(child, "id", "?"), exc_info=True,
            )

    async def _execute(self, parent_id: str) -> list["SubtaskResult"]:
        """Run the fan-out executor (honest-degrade to ``[]``)."""
        try:
            return await self._crew_executor.run(parent_id)
        except Exception:
            logger.warning(
                "AD-867: crew executor failed for parent %s; degrading to an "
                "empty result set (synthesis will report no accepted work)",
                parent_id, exc_info=True,
            )
            return []

    async def _verify(self, results: list["SubtaskResult"]) -> list[ConvergenceOutcome]:
        """Verify each successful subtask into a :class:`ConvergenceOutcome`.

        Failed subtasks are skipped (no producer output to verify). A verifier
        failure degrades that single subtask without aborting the others.
        """
        outcomes: list[ConvergenceOutcome] = []
        for result in results:
            if result.status != "done":
                continue
            try:
                verdict = await self._verifier.verify(result)
            except Exception:
                logger.warning(
                    "AD-867: verification failed for subtask %s; skipping it in "
                    "synthesis (its sibling outcomes still proceed)",
                    getattr(result, "work_item_id", "?"), exc_info=True,
                )
                continue
            status = _STATUS_CONVERGED if verdict.accepted else _STATUS_UNVERIFIED
            outcomes.append(ConvergenceOutcome(
                result=result, verdict=verdict, status=status, rounds=0,
            ))
        return outcomes

    async def _synthesize(
        self, parent_id: str, outcomes: list[ConvergenceOutcome],
    ) -> SynthesisResult:
        """Run synthesis (honest-degrade to a partial, never raises)."""
        try:
            return await self._synthesizer.synthesize(parent_id, outcomes)
        except Exception:
            logger.warning(
                "AD-867: synthesis failed for parent %s; surfacing a partial "
                "result (completed=False) instead of raising",
                parent_id, exc_info=True,
            )
            return SynthesisResult(
                parent_id=parent_id,
                final_output="",
                completed=False,
                total_count=len(outcomes),
            )

    # ----------------------------------------------------------------- helpers

    def _spec_view(self, child: "WorkItem") -> WorkItemSpec:
        """Build a :class:`WorkItemSpec`-shaped view from a child WorkItem,
        recovering the AD-863 ``capability``/``department`` hints persisted in
        its metadata."""
        md = dict(child.metadata or {})
        return WorkItemSpec(
            spec_id=str(md.get("spec_id") or child.id),
            title=child.title,
            description=child.description,
            work_type=child.work_type,
            priority=int(child.priority),
            metadata=md,
            expected_output=md.get("expected_output"),
            capability=md.get("capability"),
            department=md.get("department"),
        )

    def _orchestrator_enabled(self) -> bool:
        """Read the ``orchestrator_enabled`` gate off the config (default OFF)."""
        dispatch_cfg = getattr(self._config, "agentic_dispatch", None)
        return bool(getattr(dispatch_cfg, "orchestrator_enabled", False))

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Emit a lifecycle event through ``emit_fn`` (honest-degrade)."""
        if not self._emit_fn:
            return
        try:
            self._emit_fn(event_type, data)
        except Exception:
            logger.warning(
                "AD-867: emit_fn raised for %s; the crew pipeline continues",
                getattr(event_type, "value", event_type), exc_info=True,
            )
