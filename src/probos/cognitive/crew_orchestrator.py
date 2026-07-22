"""AD-867: :class:`CrewOrchestrator` — wire the full crew pipeline behind one
runtime entry point.

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
import logging
import math
import re
import sqlite3
import time
import weakref
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from probos.cognitive.crew_synth import SynthesisResult
from probos.cognitive.crew_verifier import ConvergenceOutcome
from probos.consultation.dispatch import WorkItemSpec
from probos.events import EventType

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from probos.cognitive.crew_assignment import CrewAssignmentResolver
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
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
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
        self._clock = clock
        self._sleep = sleep
        dispatch_config = getattr(config, "agentic_dispatch", None)
        max_active = getattr(dispatch_config, "max_active_crew_sessions", 2)
        self._active_parent_semaphore = asyncio.Semaphore(max(1, int(max_active)))
        self._tasks_by_parent: dict[str, asyncio.Task[SynthesisResult]] = {}
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
                if self._crew_session_service is None:
                    raise RuntimeError("crew_session_service_unavailable")
                repair_limit = getattr(
                    dispatch_config,
                    "crew_provisioning_repair_limit",
                    100,
                )
                repaired_ids = await self._crew_session_service.repair_provisioning(
                    limit=int(repair_limit),
                )
                scan_limit = getattr(dispatch_config, "crew_resume_scan_limit", 100)
                candidates = (
                    await self._work_item_store.list_crew_session_recovery_candidates(
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
                    session = await self._crew_session_service.get_session(parent_id)
                    if session is None:
                        raise ValueError("crew_session_candidate_integrity_invalid")
                    await self._crew_session_service.get_recovery(parent_id)
                    validated.append((parent_id, session.state))
                if self._stopped:
                    self._scheduling_open = False
                    raise RuntimeError("crew_session_lifecycle_stopped")
                for parent_id, state in validated:
                    if state in {"discussing", "executing", "verifying"}:
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

    def schedule(self, parent_id: str) -> asyncio.Task[SynthesisResult]:
        """Synchronously register or return the one live owner task for a parent."""
        if type(parent_id) is not str or _PARENT_ID_RE.fullmatch(parent_id) is None:
            raise ValueError("crew_session_parent_id_invalid")
        if not self._scheduling_open:
            raise RuntimeError("crew_session_scheduling_closed")
        existing = self._tasks_by_parent.get(parent_id)
        if existing is not None and not existing.done():
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
        if task.cancelled():
            logger.info(
                "Crew session parent=%s owner task was cancelled; durable recovery will resume it on a later authorized start",
                parent_id,
            )
            if self._tasks_by_parent.get(parent_id) is task:
                self._tasks_by_parent.pop(parent_id, None)
            return
        try:
            task.result()
        except Exception:
            logger.exception(
                "Crew session parent=%s owner task failed; durable state remains authoritative and startup recovery will inspect it",
                parent_id,
            )
        finally:
            if self._tasks_by_parent.get(parent_id) is task:
                self._tasks_by_parent.pop(parent_id, None)

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
        if session.state in {"done", "failed", "blocked_needs_captain"}:
            return self._session_observation(session)
        recovery = await self._await_recovery_boundary(
            service.get_recovery(parent_id),
            boundary="recovery_load",
        )
        if recovery is None and session.state == "verifying":
            children = await self._await_recovery_boundary(
                self._work_item_store.list_work_items(
                    parent_id=parent_id,
                    limit=1001,
                ),
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
            await self._assign_untouched_session_children(parent_id)
            results = await self._crew_executor.resume(parent_id)
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
            self._work_item_store.list_work_items(
                parent_id=session.task_id,
                limit=1001,
            ),
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

    async def _assign_untouched_session_children(self, parent_id: str) -> None:
        children = await self._await_recovery_boundary(
            self._work_item_store.list_work_items(
                parent_id=parent_id,
                limit=1001,
            ),
            boundary="child_scan",
        )
        if len(children) > 1000:
            raise ValueError("crew_recovery_plan_children_invalid")
        for child in children:
            metadata = child.metadata if type(child.metadata) is dict else {}
            if (
                child.assigned_to is not None
                or child.status
                != self._work_item_store.work_type_registry.get_initial_status(
                    child.work_type,
                )
                or child.verification
                or any(
                    key in metadata
                    for key in (
                        "crew_execution",
                        "crew_execution_output",
                        "crew_verification_recovery",
                    )
                )
            ):
                continue
            decision = self._assignment_resolver.resolve(self._spec_view(child))
            delegation = self._delegator.delegate(decision)
            if not delegation.worker_agent_id:
                continue
            assigned_metadata = dict(metadata)
            assigned_metadata.update({
                "chief_agent_id": delegation.chief_agent_id,
                "order_id": delegation.order_id,
                "delegated": delegation.delegated,
                "delegation_reason": delegation.reason,
                "assigned_capability": decision.capability,
                "assigned_department": decision.department,
            })
            await self._await_recovery_boundary(
                self._work_item_store.compare_and_set_work_item_assignment(
                    child.id,
                    expected_parent_id=parent_id,
                    expected_status=child.status,
                    expected_assigned_to=None,
                    expected_depends_on=list(child.depends_on),
                    expected_metadata=metadata,
                    new_assigned_to=delegation.worker_agent_id,
                    metadata=assigned_metadata,
                ),
                boundary="assignment_store",
            )

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
            except BaseException as exc:
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
            children = await self._work_item_store.list_work_items(
                parent_id=parent_id,
                limit=1001,
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
