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
        decomposer: Any = None,
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

    # --------------------------------------------------------------- originate

    async def originate_crew_task(
        self,
        *,
        origin_agent_id: str,
        goal: str,
        work_type: str = "task",
    ) -> str | None:
        """AD-868: a Lieutenant+ agent originates its own crew task.

        Decomposes ``goal`` into specs, creates a self-originated parent
        WorkItem with its ``parent_id``-linked children, then runs the full
        AD-867 crew pipeline (resolve -> delegate -> fan-out -> verify ->
        synthesize) and returns the parent id.

        **Provenance.** The parent carries ``created_by=origin_agent_id`` and
        ``metadata={"origin": "self_originated", "originator": origin_agent_id}``
        so the originating chain is auditable end-to-end. Trust attribution is
        owned by the AD-861 synthesizer — this method performs **no second trust
        write**.

        **Honest-degrade (Tier 2).** The orchestrator being disabled, an empty
        goal, no available decomposer, or a decomposition that yields zero specs
        all log *what/why/what-next* and return ``None`` with **no dangling
        parent** (decomposition runs before the parent is created). The method
        never raises.
        """
        goal = (goal or "").strip()
        if not goal:
            logger.warning(
                "AD-868: %s originated an empty crew goal; nothing to dispatch",
                origin_agent_id,
            )
            return None
        if not self._orchestrator_enabled():
            logger.info(
                "AD-868: crew orchestrator disabled; ignoring self-originated "
                "goal from %s (set agentic_dispatch.orchestrator_enabled to "
                "allow)",
                origin_agent_id,
            )
            return None

        # Decompose FIRST so a failure never leaves a dangling parent.
        decomposer = self._get_decomposer()
        if decomposer is None:
            logger.warning(
                "AD-868: no plan decomposer available (runtime.llm_client "
                "missing); cannot decompose self-originated goal from %s; "
                "skipping (no parent created)",
                origin_agent_id,
            )
            return None
        try:
            specs = list(decomposer.decompose(goal))
        except Exception:
            logger.warning(
                "AD-868: decomposition raised for self-originated goal from %s; "
                "skipping (no parent created)",
                origin_agent_id, exc_info=True,
            )
            return None
        if not specs:
            logger.warning(
                "AD-868: decomposition yielded zero specs for self-originated "
                "goal from %s; skipping (no parent created)",
                origin_agent_id,
            )
            return None

        # Create the self-originated parent (provenance metadata; AD-861 owns
        # trust attribution, so no second trust write happens here).
        try:
            parent = await self._work_item_store.create_work_item(
                title=goal,
                work_type=work_type,
                created_by=origin_agent_id,
                metadata={
                    "origin": "self_originated",
                    "originator": origin_agent_id,
                },
            )
        except Exception:
            logger.warning(
                "AD-868: failed to create self-originated parent for %s; "
                "skipping",
                origin_agent_id, exc_info=True,
            )
            return None
        parent_id = getattr(parent, "id", "") or ""
        if not parent_id:
            logger.warning(
                "AD-868: self-originated parent created without an id for %s; "
                "skipping",
                origin_agent_id,
            )
            return None

        # Persist the decomposed children (parent_id-linked; AD-863
        # capability/department hints carried in metadata for _spec_view).
        created = await self._create_children(parent_id, specs, origin_agent_id)
        logger.info(
            "AD-868: %s originated crew task %s with %d child(ren)",
            origin_agent_id, parent_id, created,
        )

        # Run the full AD-867 pipeline (honest-degrades internally, never raises).
        await self.run_crew_task(parent_id)
        return parent_id

    async def _create_children(
        self,
        parent_id: str,
        specs: list[WorkItemSpec],
        origin_agent_id: str,
    ) -> int:
        """Persist decomposed specs as ``parent_id``-linked child WorkItems.

        Mirrors the AD-863 ParallelDispatcher spec->WorkItem translation so the
        ``capability``/``department``/``expected_output``/``spec_id`` hints land
        in metadata where :meth:`_spec_view` reads them back. Per-child failures
        are Tier-2 logged but never abort the remaining children. Returns the
        number of children successfully persisted.
        """
        spec_to_wid: dict[str, str] = {}
        created = 0
        for spec in specs:
            translated_deps = [
                spec_to_wid[d] for d in spec.depends_on if d in spec_to_wid
            ]
            metadata = dict(spec.metadata)
            metadata.update({
                "spec_id": spec.spec_id,
                "capability": spec.capability,
                "department": spec.department,
                "expected_output": spec.expected_output,
                "resources": list(spec.resources),
            })
            try:
                item = await self._work_item_store.create_work_item(
                    title=spec.title or spec.spec_id,
                    description=spec.description,
                    work_type=spec.work_type or "task",
                    priority=int(spec.priority),
                    parent_id=parent_id,
                    depends_on=translated_deps,
                    assigned_to=spec.agent or None,
                    metadata=metadata,
                    created_by=origin_agent_id,
                )
            except Exception:
                logger.warning(
                    "AD-868: failed to persist child %s for self-originated "
                    "parent %s; its siblings still proceed",
                    spec.spec_id, parent_id, exc_info=True,
                )
                continue
            wid = getattr(item, "id", "") or ""
            if not wid:
                continue
            spec_to_wid[spec.spec_id] = wid
            created += 1
        return created

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
