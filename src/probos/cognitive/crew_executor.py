"""AD-859: Crew fan-out executor.

Given a parent work item already decomposed into child sub-tasks by the
:class:`ParallelDispatcher`, :class:`CrewTaskExecutor` drives those children to
completion. It owns its **own** ``depends_on``-gated topological scheduling (the
``WorkItemRouter`` is fire-and-forget and exposes no readiness helper — verified
at HEAD), launches each runnable child through the reusable AD-859a
:class:`WorkItemAgenticExecutor` (awaited directly), and collects a
:class:`SubtaskResult` per child carrying durable provenance (the persistent
agent identity and a content-addressable tool-trace ref — never inline bytes).

Boundaries (Safety Budget / Minimal Authority):
  * Concurrency is bounded by ``AgenticDispatchConfig.max_parallel_subtasks`` so
    a wide fan-out cannot exhaust the LLM tier.
  * A failed child surfaces its status in its ``SubtaskResult`` but does NOT
    abort siblings and does NOT unblock its dependents (it never reaches
    ``done`` in the store, so the dependency gate keeps the dependents waiting).
  * A failed child is never silently transitioned to ``done``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from probos.events import EventType

if TYPE_CHECKING:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.substrate.registry import AgentRegistry
    from probos.workforce import WorkItem, WorkItemStore

logger = logging.getLogger(__name__)

# A child whose agentic run stops with this reason is treated as a success and
# transitioned to ``done``; every other reason (max_iterations / token_budget /
# error) surfaces as a non-``done`` status that does not unblock dependents.
_SUCCESS_STOPPED_REASON = "complete"


@dataclass
class SubtaskResult:
    """The collected outcome of one child sub-task with durable provenance."""

    work_item_id: str
    spec_id: str
    agent_id: str
    output: str
    status: str  # "done" on success, else "failed" / the degraded stopped_reason
    tool_trace_ref: str | None = None
    started_at: float = 0.0
    finished_at: float = 0.0


class CrewTaskExecutor:
    """Drive a parent's child sub-tasks with dependency-gated bounded fan-out."""

    def __init__(
        self,
        *,
        work_item_store: WorkItemStore,
        agent_registry: AgentRegistry,
        agentic_executor: WorkItemAgenticExecutor,
        runtime: Any,
        max_parallel_subtasks: int = 3,
        emit_fn: Callable[[EventType, dict[str, Any]], None] | None = None,
    ) -> None:
        self._store = work_item_store
        self._registry = agent_registry
        self._executor = agentic_executor
        self._runtime = runtime
        self._max_parallel = max(1, int(max_parallel_subtasks))
        # Honest-degrade: if no emit fn is wired, the executor still runs; it
        # just cannot publish lifecycle events.
        self._emit_fn = emit_fn
        # Async-hygiene: hold strong references to every spawned child task so a
        # fire-and-forget GC cannot drop one mid-flight.
        self._tasks: set[asyncio.Task[SubtaskResult]] = set()

    async def run(self, parent_id: str) -> list[SubtaskResult]:
        """Run all child sub-tasks of ``parent_id`` and return their results.

        Children are scheduled in topological order: a child becomes runnable
        only once every id in its ``depends_on`` has reached ``done`` in the
        store. At most ``max_parallel_subtasks`` children run concurrently.
        """
        children = await self._store.list_work_items(
            parent_id=parent_id, limit=1000
        )
        self._emit(
            EventType.CREW_TASK_STARTED,
            {"parent_id": parent_id, "child_count": len(children)},
        )
        if not children:
            return []

        by_id: dict[str, WorkItem] = {c.id: c for c in children}
        results: dict[str, SubtaskResult] = {}
        done_ids: set[str] = set()
        started: set[str] = set()
        pending: set[str] = set(by_id)
        sem = asyncio.Semaphore(self._max_parallel)

        async def _guarded(child: WorkItem) -> SubtaskResult:
            async with sem:
                return await self._run_child(child)

        while pending or self._tasks:
            runnable = [
                cid
                for cid in pending
                if cid not in started and self._deps_met(by_id[cid], done_ids)
            ]
            for cid in runnable:
                started.add(cid)
                task: asyncio.Task[SubtaskResult] = asyncio.create_task(
                    _guarded(by_id[cid])
                )
                self._tasks.add(task)

            if not self._tasks:
                # Nothing running and nothing runnable: remaining pending
                # children are permanently blocked by a failed dependency.
                if pending:
                    logger.warning(
                        "Crew parent %s: %d child sub-task(s) left unrun — "
                        "blocked by a failed/incomplete dependency; surfacing "
                        "collected results without them.",
                        parent_id,
                        len(pending),
                    )
                break

            completed, _ = await asyncio.wait(
                self._tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in completed:
                self._tasks.discard(task)
                result = task.result()
                results[result.work_item_id] = result
                pending.discard(result.work_item_id)
                if result.status == "done":
                    done_ids.add(result.work_item_id)
                self._emit(
                    EventType.SUBTASK_COMPLETED,
                    {
                        "parent_id": parent_id,
                        "work_item_id": result.work_item_id,
                        "spec_id": result.spec_id,
                        "agent_id": result.agent_id,
                        "status": result.status,
                    },
                )

        return list(results.values())

    def _deps_met(self, child: WorkItem, done_ids: set[str]) -> bool:
        """True when every ``depends_on`` id of ``child`` has reached ``done``."""
        return all(dep in done_ids for dep in (child.depends_on or []))

    async def _run_child(self, child: WorkItem) -> SubtaskResult:
        """Run a single child through the AD-859a executor and collect its result."""
        started_at = time.time()
        spec_id = str(child.metadata.get("spec_id", child.id))
        agent = (
            self._registry.get(child.assigned_to)
            if child.assigned_to
            else None
        )
        if agent is None:
            logger.warning(
                "Crew child %s has no resolvable assigned agent (%r); marking "
                "the sub-task failed without unblocking dependents.",
                child.id,
                child.assigned_to,
            )
            return SubtaskResult(
                work_item_id=child.id,
                spec_id=spec_id,
                agent_id=str(child.assigned_to or ""),
                output="",
                status="failed",
                tool_trace_ref=None,
                started_at=started_at,
                finished_at=time.time(),
            )

        # Move the child into ``in_progress`` so the dependency gate sees it as
        # neither runnable-again nor ``done`` while its agent works. The task
        # state machine requires assignment for this transition, which the
        # child already satisfies.
        await self._store.transition_work_item(
            child.id, "in_progress", source="crew_executor"
        )

        task_text = child.description or child.title or ""
        try:
            outcome = await self._executor.run(
                agent_id=agent.id,
                instructions=str(getattr(agent, "instructions", "") or ""),
                task_text=task_text,
                runtime=self._runtime,
                department=str(getattr(agent, "department", "") or ""),
                rank=str(getattr(agent, "rank", "ensign") or "ensign"),
            )
        except Exception:
            logger.warning(
                "Crew child %s raised during agentic execution; marking failed "
                "without unblocking dependents.",
                child.id,
                exc_info=True,
            )
            return SubtaskResult(
                work_item_id=child.id,
                spec_id=spec_id,
                agent_id=agent.id,
                output="",
                status="failed",
                tool_trace_ref=None,
                started_at=started_at,
                finished_at=time.time(),
            )

        if outcome.stopped_reason == _SUCCESS_STOPPED_REASON:
            await self._store.transition_work_item(
                child.id, "done", source="crew_executor"
            )
            status = "done"
        else:
            # Degraded stop (max_iterations / token_budget / error): surface the
            # reason, do NOT mark done, do NOT unblock dependents.
            status = outcome.stopped_reason or "failed"

        return SubtaskResult(
            work_item_id=child.id,
            spec_id=spec_id,
            agent_id=agent.id,
            output=outcome.final_text,
            status=status,
            tool_trace_ref=outcome.tool_trace_ref,
            started_at=started_at,
            finished_at=time.time(),
        )

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Publish a lifecycle event, honest-degrading when no emit fn is wired."""
        if self._emit_fn is None:
            return
        try:
            self._emit_fn(event_type, data)
        except Exception:
            logger.warning(
                "Crew executor failed to emit %s; continuing without the event.",
                getattr(event_type, "value", event_type),
                exc_info=True,
            )
