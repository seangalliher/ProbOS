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

**Honest-degrade.** Every stage is wrapped log-and-degrade (Tier 2): a failed
stage logs *what* failed, *why* it matters, and *what happens next*, then the
pipeline continues with a partial result. ``run_crew_task`` never raises — a
total failure surfaces a partial :class:`SynthesisResult` (``completed=False``).

**Parent state glue (AD-867 deviation).** :meth:`CrewSynthesizer._complete_parent`
transitions the parent ``in_progress -> done``; an ``open`` task cannot go
straight to ``done`` under the AD-498 state machine, and neither the executor
nor the dispatcher moves the parent. So the orchestrator transitions the parent
``open -> in_progress`` at the start of ``run_crew_task`` (honest-degrade, only
when ``status == "open"``) so the pipeline can actually complete end-to-end.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from probos.cognitive.crew_synth import SynthesisResult
from probos.cognitive.crew_verifier import ConvergenceOutcome
from probos.consultation.dispatch import WorkItemSpec
from probos.events import EventType

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from probos.cognitive.crew_assignment import CrewAssignmentResolver
    from probos.cognitive.crew_delegation import CrewDelegator
    from probos.cognitive.crew_executor import CrewTaskExecutor, SubtaskResult
    from probos.cognitive.crew_synth import CrewSynthesizer
    from probos.cognitive.crew_verifier import SubtaskVerifier
    from probos.workforce import WorkItem, WorkItemStore

logger = logging.getLogger(__name__)

# ConvergenceOutcome.status — kept in sync with crew_verifier's status vocabulary
# (the synthesizer keys off ``verdict.accepted``, not this string, so it is a
# human-readable marker only).
_STATUS_CONVERGED = "converged"
_STATUS_UNVERIFIED = "unverified"


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
        # Held references for fire-and-forget protection (async-hygiene rule).
        self._tasks: set[asyncio.Task[SynthesisResult]] = set()

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
        task: asyncio.Task[SynthesisResult] = asyncio.create_task(
            self.run_crew_task(parent_id)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        logger.info(
            "AD-867: scheduled crew_orchestrator.run_crew_task for parent %s "
            "(%d children)",
            parent_id, len(children),
        )
        return task

    # ------------------------------------------------------------------ pipeline

    async def run_crew_task(self, parent_id: str) -> SynthesisResult:
        """Thread resolve -> delegate -> fan-out -> verify -> synthesize for one
        parent task. Honest-degrades every stage and never raises."""
        # Stage 0: move the parent open -> in_progress so the synthesizer's
        # in_progress -> done completion is valid (AD-867 glue, honest-degrade).
        await self._promote_parent(parent_id)

        children = await self._load_children(parent_id)
        self._emit(EventType.CREW_ORCHESTRATION_STARTED, {
            "parent_id": parent_id,
            "child_count": len(children),
        })

        # Stage 1: resolve + delegate + persist assignment per child.
        for child in children:
            await self._assign_child(child)

        # Stage 2: fan-out execution (existing AD-859 executor).
        results = await self._execute(parent_id)

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
