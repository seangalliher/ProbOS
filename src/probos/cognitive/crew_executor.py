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
import hashlib
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from probos.crew_utils import is_crew_agent
from probos.events import EventType

if TYPE_CHECKING:
    from probos.attachments.store import AttachmentStore
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.cognitive.crew_session import CrewSessionService
    from probos.substrate.registry import AgentRegistry
    from probos.threads import ChatThread
    from probos.workforce import WorkItem, WorkItemStore

logger = logging.getLogger(__name__)

# A child whose agentic run stops with this reason is treated as a success and
# transitioned to ``done``; every other reason (max_iterations / token_budget /
# error) surfaces as a non-``done`` status that does not unblock dependents.
_SUCCESS_STOPPED_REASON = "complete"
_STOPPED_REASONS = frozenset(
    {
        "complete",
        "error",
        "max_iterations",
        "token_budget",
        "execution_exception",
        "unassigned",
        "agent_unresolvable",
        "dependency_blocked",
        "start_transition_failed",
    }
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_REF_KEYS = frozenset(
    {
        "artifact_id",
        "content_hash",
        "thread_id",
        "name",
        "mime",
        "size_bytes",
        "version",
    }
)
_MAX_ACTUAL_TOKENS = 9_223_372_036_854_775_807
_MAX_EVIDENCE_BYTES = 32_768
_MAX_OUTPUT_SUMMARY_CHARS = 4_096
_MAX_DEPENDENCY_IDS = 64
_MAX_OUTPUT_BYTES = 1_048_576
_SUMMARY_TRUNCATION_MARKER = "...[truncated]"


def _compact_json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_dicts_exactly_equal(
    current: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    try:
        return _compact_json_bytes(current) == _compact_json_bytes(expected)
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        return False


def _bounded_id(value: Any) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ValueError("crew_execution_id_invalid")
    return value


def _bounded_id_or_empty(value: Any) -> str:
    if value == "":
        return ""
    return _bounded_id(value)


def _normalize_tokens(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_ACTUAL_TOKENS:
        raise ValueError("crew_execution_tokens_invalid")
    return value


def _normalize_trace_ref(value: Any, child_id: str) -> str | None:
    if value is None:
        return None
    if type(value) is str and _SHA_RE.fullmatch(value) is not None:
        return value
    logger.warning(
        "Crew child %s returned a malformed tool-trace ref; evidence will "
        "store None while terminal status persistence continues",
        child_id,
    )
    return None


def _output_summary(value: Any) -> str:
    if type(value) is not str:
        return ""
    summary = value.strip()
    if len(summary) <= _MAX_OUTPUT_SUMMARY_CHARS:
        return summary
    keep = _MAX_OUTPUT_SUMMARY_CHARS - len(_SUMMARY_TRUNCATION_MARKER)
    return summary[:keep] + _SUMMARY_TRUNCATION_MARKER


def _exact_dependency_ids(values: Any) -> list[str]:
    if type(values) is not list or len(values) > _MAX_DEPENDENCY_IDS:
        raise ValueError("crew_execution_dependencies_invalid")
    return [_bounded_id(value) for value in values]


def _bounded_dependency_ids(values: list[str]) -> list[str]:
    exact_values = _exact_dependency_ids(values)
    result: list[str] = []
    for value in exact_values:
        if value not in result:
            result.append(value)
    return result


def _normalize_artifact_refs(
    value: Any,
    *,
    thread_id: str,
    child_id: str,
) -> list[dict[str, Any]]:
    if type(value) is not list:
        return []
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    dropped = max(0, len(value) - 64)
    for candidate in value[:64]:
        if type(candidate) is not dict:
            dropped += 1
            continue
        if (
            len(candidate) != 7
            or any(type(key) is not str for key in candidate)
            or set(candidate) != _ARTIFACT_REF_KEYS
        ):
            dropped += 1
            continue
        artifact_id = candidate["artifact_id"]
        content_hash = candidate["content_hash"]
        candidate_thread = candidate["thread_id"]
        name = candidate["name"]
        mime = candidate["mime"]
        size_bytes = candidate["size_bytes"]
        version = candidate["version"]
        valid = (
            type(artifact_id) is str
            and _ID_RE.fullmatch(artifact_id) is not None
            and artifact_id not in seen
            and type(content_hash) is str
            and _SHA_RE.fullmatch(content_hash) is not None
            and type(candidate_thread) is str
            and bool(candidate_thread)
            and candidate_thread == thread_id
            and type(name) is str
            and 1 <= len(name) <= 255
            and "/" not in name
            and "\\" not in name
            and "\x00" not in name
            and type(mime) is str
            and 1 <= len(mime) <= 255
            and type(size_bytes) is int
            and 1 <= size_bytes <= 26_214_400
            and type(version) is int
            and 1 <= version <= 2_147_483_647
            and len(refs) < 32
        )
        if not valid:
            dropped += 1
            continue
        seen.add(artifact_id)
        refs.append(
            {
                "artifact_id": artifact_id,
                "content_hash": content_hash,
                "thread_id": candidate_thread,
                "name": name,
                "mime": mime,
                "size_bytes": size_bytes,
                "version": version,
            }
        )
    if dropped:
        logger.warning(
            "Crew child %s artifact evidence dropped %d malformed, duplicate, "
            "cross-thread, or over-limit refs; terminal persistence continues "
            "with %d validated refs",
            child_id,
            dropped,
            len(refs),
        )
    return refs


def _build_execution_evidence(
    *,
    parent_id: str,
    child: WorkItem,
    thread_id: str,
    status: str,
    stopped_reason: str,
    output: Any,
    tool_trace_ref: str | None,
    artifact_refs: list[dict[str, Any]],
    actual_tokens: int,
    started_at: float,
    finished_at: float,
    blocked_dependency_ids: list[str],
) -> dict[str, Any]:
    if status not in {"done", "failed", "blocked"}:
        raise ValueError("crew_execution_status_invalid")
    reason = stopped_reason if stopped_reason in _STOPPED_REASONS else "error"
    required_status = {
        "complete": "done",
        "error": "failed",
        "max_iterations": "failed",
        "token_budget": "failed",
        "execution_exception": "failed",
        "unassigned": "blocked",
        "agent_unresolvable": "blocked",
        "dependency_blocked": "blocked",
        "start_transition_failed": "blocked",
    }[reason]
    if status != required_status:
        raise ValueError("crew_execution_status_invalid")
    dependencies = _bounded_dependency_ids(blocked_dependency_ids)
    if reason == "dependency_blocked":
        if not dependencies:
            raise ValueError("crew_execution_dependencies_invalid")
    elif dependencies:
        raise ValueError("crew_execution_dependencies_invalid")
    if not (
        type(started_at) in (int, float)
        and type(finished_at) in (int, float)
        and math.isfinite(float(started_at))
        and math.isfinite(float(finished_at))
        and 0 <= float(started_at) <= float(finished_at)
    ):
        raise ValueError("crew_execution_timestamp_invalid")
    record = {
        "version": 1,
        "parent_id": _bounded_id(parent_id),
        "work_item_id": _bounded_id(child.id),
        "thread_id": _bounded_id_or_empty(thread_id),
        "assigned_to": _bounded_id(child.assigned_to) if child.assigned_to else None,
        "status": status,
        "stopped_reason": reason,
        "output_summary": _output_summary(output),
        "tool_trace_ref": tool_trace_ref,
        "artifact_refs": [dict(ref) for ref in artifact_refs],
        "tokens_used": actual_tokens,
        "started_at": float(started_at),
        "finished_at": float(finished_at),
        "blocked_dependency_ids": dependencies,
    }
    initial_ref_count = len(record["artifact_refs"])
    while (
        len(_compact_json_bytes(record)) > _MAX_EVIDENCE_BYTES
        and record["artifact_refs"]
    ):
        record["artifact_refs"].pop()
    if len(record["artifact_refs"]) != initial_ref_count:
        logger.warning(
            "Crew child %s evidence exceeded the 32 KiB record cap; %d "
            "artifact refs were removed and bounded terminal persistence continues",
            child.id,
            initial_ref_count - len(record["artifact_refs"]),
        )
    if len(_compact_json_bytes(record)) > _MAX_EVIDENCE_BYTES:
        raise ValueError("crew_execution_evidence_too_large")
    return record


@dataclass
class SubtaskResult:
    """The collected outcome of one child sub-task with durable provenance."""

    work_item_id: str
    spec_id: str
    agent_id: str
    output: str
    status: str  # done | failed | blocked
    tool_trace_ref: str | None = None
    started_at: float = 0.0
    finished_at: float = 0.0
    stopped_reason: str = ""
    actual_tokens: int = 0
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    blocked_dependency_ids: list[str] = field(default_factory=list)


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
        crew_session_service: CrewSessionService | None = None,
        attachment_store: AttachmentStore | None = None,
    ) -> None:
        self._store = work_item_store
        self._registry = agent_registry
        self._executor = agentic_executor
        self._runtime = runtime
        self._max_parallel = max(1, int(max_parallel_subtasks))
        # Honest-degrade: if no emit fn is wired, the executor still runs; it
        # just cannot publish lifecycle events.
        self._emit_fn = emit_fn
        self._crew_session_service = crew_session_service
        self._attachment_store = (
            attachment_store
            if attachment_store is not None
            else getattr(runtime, "attachment_store", None)
        )

    async def run(self, parent_id: str) -> list[SubtaskResult]:
        """Run all child sub-tasks of ``parent_id`` and return their results.

        Children are scheduled in topological order: a child becomes runnable
        only once every id in its ``depends_on`` has reached ``done`` in the
        store. At most ``max_parallel_subtasks`` children run concurrently.
        """
        parent = await self._store.get_work_item(parent_id)
        if parent is None:
            logger.warning(
                "Crew parent %s was not found; no child execution can be bound "
                "to an authoritative parent, so fan-out is skipped",
                parent_id,
            )
            return []
        children = await self._store.list_work_items(
            parent_id=parent_id, limit=1000
        )
        self._emit(
            EventType.CREW_TASK_STARTED,
            {"parent_id": parent_id, "child_count": len(children)},
        )
        if not children and parent.work_type != "crew_session":
            return []

        parent_key = _bounded_id(parent.id)
        resolved_thread = await self._resolve_task_room(parent, children)
        thread_id = (
            _bounded_id(resolved_thread.id)
            if resolved_thread is not None
            else ""
        )
        await self._start_crew_session(parent, resolved_thread)
        if not children:
            return []

        return await self._run_children(
            parent_key,
            children,
            thread_id,
            seed_results={},
            seed_done_ids=set(),
        )

    async def resume(self, parent_id: str) -> list[SubtaskResult]:
        """Resume one authoritative executing CrewSession without rerunning terminals."""
        parent_key = _bounded_id(parent_id)
        parent = await self._store.get_work_item(parent_key)
        if parent is None or parent.work_type != "crew_session":
            raise ValueError("crew_session_parent_not_found")
        service = self._crew_session_service
        if service is None:
            raise ValueError("crew_session_service_unavailable")
        session = await service.get_session(parent_key)
        recovery = await service.get_recovery(parent_key)
        if (
            session is None
            or session.state != "executing"
            or recovery is None
            or recovery.phase != "executing"
            or recovery.plan is None
        ):
            raise ValueError("crew_session_recovery_not_executable")
        children = await self._store.list_work_items(
            parent_id=parent_key,
            limit=1001,
        )
        if len(children) != len(recovery.plan.children) or len(children) > 1000:
            raise ValueError("crew_session_recovery_plan_conflict")
        by_id = {child.id: child for child in children}
        if len(by_id) != len(children):
            raise ValueError("crew_session_recovery_plan_conflict")
        try:
            ordered = [by_id[item.child_id] for item in recovery.plan.children]
        except KeyError as exc:
            raise ValueError("crew_session_recovery_plan_conflict") from exc
        room = await self._resolve_task_room(parent, ordered)
        if room is None or room.id != session.thread_id:
            raise ValueError("crew_session_thread_mismatch")

        reconstructed: dict[str, SubtaskResult] = {}
        done_ids: set[str] = set()
        for child in ordered:
            result = await self._resume_child(
                parent_key,
                child,
                session.thread_id,
            )
            if result is None:
                continue
            reconstructed[child.id] = result
            if result.status == "done":
                done_ids.add(child.id)
        return await self._run_children(
            parent_key,
            ordered,
            session.thread_id,
            seed_results=reconstructed,
            seed_done_ids=done_ids,
        )

    async def _run_children(
        self,
        parent_id: str,
        children: list[WorkItem],
        thread_id: str,
        *,
        seed_results: dict[str, SubtaskResult],
        seed_done_ids: set[str],
    ) -> list[SubtaskResult]:
        """Run one parent's remaining children with an invocation-local task set."""

        by_id: dict[str, WorkItem] = {c.id: c for c in children}
        results = dict(seed_results)
        done_ids = set(seed_done_ids)
        started: set[str] = set(results)
        pending: set[str] = set(by_id).difference(results)
        sem = asyncio.Semaphore(self._max_parallel)
        tasks: set[asyncio.Task[SubtaskResult]] = set()

        for child in children:
            try:
                _exact_dependency_ids(child.depends_on)
            except ValueError:
                logger.error(
                    "Crew child %s has an invalid or over-limit dependency "
                    "vector; no agent will run and the child will be durably "
                    "blocked without dependency evidence",
                    child.id,
                    exc_info=True,
                )
                started_at = time.time()
                result = await self._persist_terminal_result(
                    parent_id=parent_id,
                    child=child,
                    thread_id=thread_id,
                    status="blocked",
                    stopped_reason="start_transition_failed",
                    output="",
                    tool_trace_ref=None,
                    actual_tokens=0,
                    artifact_refs=[],
                    started_at=started_at,
                    finished_at=max(started_at, time.time()),
                    blocked_dependency_ids=[],
                    expected_status=child.status,
                    dependency_input_invalid=True,
                )
                results[child.id] = result
                pending.discard(child.id)
                self._emit_subtask_completed(parent_id, result)

        async def _guarded(child: WorkItem) -> SubtaskResult:
            async with sem:
                return await self._run_child(parent_id, child, thread_id)

        try:
            while pending or tasks:
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
                    tasks.add(task)

                if not tasks:
                    blocked_children = [
                        child for child in children if child.id in pending
                    ]
                    for child in blocked_children:
                        unresolved = self._unresolved_dependency_ids(child, done_ids)
                        started_at = time.time()
                        result = await self._persist_terminal_result(
                            parent_id=parent_id,
                            child=child,
                            thread_id=thread_id,
                            status="blocked",
                            stopped_reason="dependency_blocked",
                            output="",
                            tool_trace_ref=None,
                            actual_tokens=0,
                            artifact_refs=[],
                            started_at=started_at,
                            finished_at=max(started_at, time.time()),
                            blocked_dependency_ids=unresolved,
                            expected_status=child.status,
                        )
                        results[child.id] = result
                        pending.discard(child.id)
                        self._emit_subtask_completed(parent_id, result)
                    break

                completed, _ = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )
                for task in completed:
                    tasks.discard(task)
                    result = task.result()
                    results[result.work_item_id] = result
                    pending.discard(result.work_item_id)
                    if result.status == "done":
                        done_ids.add(result.work_item_id)
                    self._emit_subtask_completed(parent_id, result)
        finally:
            held = tuple(tasks)
            for task in held:
                task.cancel()
            if held:
                await asyncio.gather(*held, return_exceptions=True)
            tasks.clear()

        return list(results.values())

    async def _resume_child(
        self,
        parent_id: str,
        child: WorkItem,
        thread_id: str,
    ) -> SubtaskResult | None:
        metadata = child.metadata if type(child.metadata) is dict else {}
        execution = metadata.get("crew_execution")
        output_ref = metadata.get("crew_execution_output")
        initial_status = self._store.work_type_registry.get_initial_status(
            child.work_type,
        )
        if (
            child.status == initial_status
            and execution is None
            and output_ref is None
            and child.verification == {}
        ):
            return None
        if child.status == "in_progress":
            return self._interrupted_result(child, "child_execution_interrupted")
        if child.status not in {"done", "failed", "blocked"}:
            return self._interrupted_result(child, "child_execution_integrity")
        try:
            return await self._reconstruct_terminal_result(
                parent_id,
                child,
                thread_id,
            )
        except (UnicodeError, ValueError, FileNotFoundError):
            return self._interrupted_result(child, "child_execution_integrity")

    async def _reconstruct_terminal_result(
        self,
        parent_id: str,
        child: WorkItem,
        thread_id: str,
    ) -> SubtaskResult:
        metadata = child.metadata
        execution = metadata.get("crew_execution")
        if type(execution) is not dict or set(execution) != {
            "version",
            "parent_id",
            "work_item_id",
            "thread_id",
            "assigned_to",
            "status",
            "stopped_reason",
            "output_summary",
            "tool_trace_ref",
            "artifact_refs",
            "tokens_used",
            "started_at",
            "finished_at",
            "blocked_dependency_ids",
        }:
            raise ValueError("crew_execution_evidence_invalid")
        if (
            type(execution["version"]) is not int
            or execution["version"] != 1
            or execution["parent_id"] != parent_id
            or execution["work_item_id"] != child.id
            or execution["thread_id"] != thread_id
            or execution["assigned_to"] != child.assigned_to
            or execution["status"] != child.status
            or type(execution["stopped_reason"]) is not str
            or type(execution["output_summary"]) is not str
            or type(execution["tokens_used"]) is not int
            or execution["tokens_used"] != child.actual_tokens
            or type(execution["started_at"]) is not float
            or type(execution["finished_at"]) is not float
            or not math.isfinite(execution["started_at"])
            or not math.isfinite(execution["finished_at"])
            or execution["started_at"] > execution["finished_at"]
            or type(execution["blocked_dependency_ids"]) is not list
        ):
            raise ValueError("crew_execution_evidence_invalid")
        trace_ref = _normalize_trace_ref(execution["tool_trace_ref"], child.id)
        if trace_ref != execution["tool_trace_ref"]:
            raise ValueError("crew_execution_evidence_invalid")
        artifacts = _normalize_artifact_refs(
            execution["artifact_refs"],
            thread_id=thread_id,
            child_id=child.id,
        )
        if artifacts != execution["artifact_refs"]:
            raise ValueError("crew_execution_evidence_invalid")
        blocked_dependencies = _exact_dependency_ids(
            execution["blocked_dependency_ids"],
        )
        output = ""
        output_record = metadata.get("crew_execution_output")
        if child.status == "done":
            if (
                type(output_record) is not dict
                or set(output_record)
                != {"version", "content_hash", "mime", "size_bytes"}
                or type(output_record["version"]) is not int
                or output_record["version"] != 1
                or output_record["mime"] != "text/plain"
                or type(output_record["size_bytes"]) is not int
                or not 1 <= output_record["size_bytes"] <= _MAX_OUTPUT_BYTES
                or self._attachment_store is None
            ):
                raise ValueError("crew_execution_output_invalid")
            content_hash = output_record["content_hash"]
            if type(content_hash) is not str or _SHA_RE.fullmatch(content_hash) is None:
                raise ValueError("crew_execution_output_invalid")
            blob = await self._attachment_store.read(content_hash)
            if (
                len(blob) != output_record["size_bytes"]
                or hashlib.sha256(blob).hexdigest() != content_hash
            ):
                raise ValueError("crew_execution_output_invalid")
            output = blob.decode("utf-8", errors="strict")
            if (
                execution["stopped_reason"] != "complete"
                or execution["output_summary"] != _output_summary(output)
                or blocked_dependencies
            ):
                raise ValueError("crew_execution_output_invalid")
        elif output_record is not None:
            raise ValueError("crew_execution_output_invalid")
        spec_id = metadata.get("spec_id")
        if type(spec_id) is not str or not spec_id:
            raise ValueError("crew_execution_evidence_invalid")
        return SubtaskResult(
            work_item_id=child.id,
            spec_id=spec_id,
            agent_id=child.assigned_to or "",
            output=output,
            status=child.status,
            tool_trace_ref=trace_ref,
            started_at=execution["started_at"],
            finished_at=execution["finished_at"],
            stopped_reason=execution["stopped_reason"],
            actual_tokens=execution["tokens_used"],
            artifact_refs=artifacts,
            blocked_dependency_ids=blocked_dependencies,
        )

    @staticmethod
    def _interrupted_result(child: WorkItem, reason: str) -> SubtaskResult:
        spec_id = (
            child.metadata.get("spec_id", child.id)
            if type(child.metadata) is dict
            else child.id
        )
        return SubtaskResult(
            work_item_id=child.id,
            spec_id=str(spec_id),
            agent_id=child.assigned_to or "",
            output="",
            status="blocked",
            stopped_reason=reason,
        )

    def _deps_met(self, child: WorkItem, done_ids: set[str]) -> bool:
        """True when every ``depends_on`` id of ``child`` has reached ``done``."""
        return all(
            dependency_id in done_ids
            for dependency_id in _exact_dependency_ids(child.depends_on)
        )

    async def _run_child(
        self,
        parent_id: str,
        child: WorkItem,
        thread_id: str,
    ) -> SubtaskResult:
        """Run a single child through the AD-859a executor and collect its result."""
        started_at = time.time()
        spec_id = str(child.metadata.get("spec_id", child.id))
        child_id = _bounded_id(child.id)
        expected_assigned_to = (
            _bounded_id(child.assigned_to)
            if child.assigned_to is not None
            else None
        )
        admission_status = child.status
        try:
            active_child = await self._store.merge_work_item_metadata(
                child_id,
                {},
                expected_work_type=child.work_type,
                expected_status=admission_status,
                expected_assigned_to_exact=expected_assigned_to,
                expected_parent_id=parent_id,
                expected_depends_on=list(child.depends_on),
                expected_unresolved_dependency_ids=[],
                new_status=(
                    "in_progress"
                    if expected_assigned_to is not None
                    else None
                ),
                source="crew_executor_admission",
            )
        except Exception as exc:
            state_conflict = (
                isinstance(exc, ValueError)
                and str(exc) in {
                    "work_item_state_conflict",
                    "work_item_dependency_state_conflict",
                }
            )
            logger.warning(
                "Crew child %s could not be admitted from status %s because its "
                "atomic state/dependency validation raised; no agent will run "
                "and blocked evidence will fail closed on ownership drift",
                child.id,
                admission_status,
                exc_info=True,
            )
            active_child = None
            if not state_conflict:
                try:
                    reloaded_child = await self._store.get_work_item(child_id)
                except Exception:
                    logger.error(
                        "Crew child %s could not be reloaded after admission "
                        "raised; blocked evidence will use the prior row and "
                        "fail closed on any state conflict",
                        child.id,
                        exc_info=True,
                    )
                else:
                    if reloaded_child is not None:
                        child = reloaded_child
        if active_child is None:
            failure_reason = (
                "unassigned"
                if expected_assigned_to is None
                else "start_transition_failed"
            )
            return await self._persist_terminal_result(
                parent_id=parent_id,
                child=child,
                thread_id=thread_id,
                status="blocked",
                stopped_reason=failure_reason,
                output="",
                tool_trace_ref=None,
                actual_tokens=0,
                artifact_refs=[],
                started_at=started_at,
                finished_at=max(started_at, time.time()),
                blocked_dependency_ids=[],
                expected_status=child.status,
            )

        if active_child.assigned_to is None:
            logger.warning(
                "Crew child %s is authoritatively unassigned at admission; "
                "persisting blocked evidence so dependents remain closed",
                child.id,
            )
            return await self._persist_terminal_result(
                parent_id=parent_id,
                child=active_child,
                thread_id=thread_id,
                status="blocked",
                stopped_reason="unassigned",
                output="",
                tool_trace_ref=None,
                actual_tokens=0,
                artifact_refs=[],
                started_at=started_at,
                finished_at=max(started_at, time.time()),
                blocked_dependency_ids=[],
                expected_status=active_child.status,
            )

        assigned_to = _bounded_id(active_child.assigned_to)
        agent = self._registry.get(assigned_to)
        if agent is None:
            logger.warning(
                "Crew child %s has no resolvable authoritatively assigned agent "
                "%s after admission; persisting blocked evidence so dependents "
                "remain closed",
                child.id,
                assigned_to,
            )
            return await self._persist_terminal_result(
                parent_id=parent_id,
                child=active_child,
                thread_id=thread_id,
                status="blocked",
                stopped_reason="agent_unresolvable",
                output="",
                tool_trace_ref=None,
                actual_tokens=0,
                artifact_refs=[],
                started_at=started_at,
                finished_at=max(started_at, time.time()),
                blocked_dependency_ids=[],
                expected_status=active_child.status,
            )

        task_text = active_child.description or active_child.title or ""
        try:
            outcome = await self._executor.run(
                agent_id=agent.id,
                instructions=str(getattr(agent, "instructions", "") or ""),
                task_text=task_text,
                runtime=self._runtime,
                thread_id=thread_id,
                extra_context={
                    "_crew_session_id": parent_id,
                    "_crew_work_item_id": child_id,
                },
            )
        except Exception:
            logger.warning(
                "Crew child %s raised during agentic execution; persisting failed "
                "evidence so it cannot remain in_progress or unblock dependents",
                child.id,
                exc_info=True,
            )
            return await self._persist_terminal_result(
                parent_id=parent_id,
                child=active_child,
                thread_id=thread_id,
                status="failed",
                stopped_reason="execution_exception",
                output="",
                tool_trace_ref=None,
                actual_tokens=0,
                artifact_refs=[],
                started_at=started_at,
                finished_at=max(started_at, time.time()),
                blocked_dependency_ids=[],
                expected_status="in_progress",
            )

        if outcome.stopped_reason == _SUCCESS_STOPPED_REASON:
            status = "done"
            stopped_reason = "complete"
        else:
            status = "failed"
            stopped_reason = (
                outcome.stopped_reason
                if outcome.stopped_reason in {"error", "max_iterations", "token_budget"}
                else "error"
            )

        checkpoint = asyncio.create_task(self._persist_terminal_result(
            parent_id=parent_id,
            child=active_child,
            thread_id=thread_id,
            status=status,
            stopped_reason=stopped_reason,
            output=outcome.final_text,
            tool_trace_ref=outcome.tool_trace_ref,
            actual_tokens=outcome.total_tokens,
            artifact_refs=outcome.artifact_refs,
            started_at=started_at,
            finished_at=max(started_at, time.time()),
            blocked_dependency_ids=[],
            expected_status="in_progress",
        ))
        try:
            return await asyncio.shield(checkpoint)
        except asyncio.CancelledError:
            while not checkpoint.done():
                try:
                    await asyncio.shield(checkpoint)
                except asyncio.CancelledError:
                    continue
            checkpoint.result()
            raise

    def _is_crew_assignee(self, agent_id: str) -> bool:
        """True iff ``agent_id`` resolves to a live crew agent.

        Mirrors ``AgentGroupChatService._is_crew`` via the shared public
        ``is_crew_agent`` predicate (ontology=None — the legacy crew-type path,
        AD-918 test precedent), None-guarding an unresolvable id.
        """
        agent = self._registry.get(agent_id)
        return bool(agent) and is_crew_agent(agent, None)

    async def _resolve_task_room(
        self,
        parent: WorkItem,
        children: list[WorkItem],
    ) -> ChatThread | None:
        """Resolve one authoritative existing room, or create one for legacy work."""
        runtime = self._runtime
        store = getattr(runtime, "chat_thread_store", None)
        if store is not None:
            rooms = await asyncio.to_thread(
                store.list_threads,
                task_id=parent.id,
                include_archived=True,
                limit=2,
            )
            if len(rooms) == 1:
                return rooms[0]
            if len(rooms) > 1:
                raise ValueError("crew_task_room_cardinality_invalid")
        if parent.work_type == "crew_session":
            raise ValueError("crew_session_thread_not_found")

        group_chat_cfg = getattr(getattr(runtime, "config", None), "group_chat", None)
        if not getattr(group_chat_cfg, "auto_task_room_enabled", False):
            return None
        service = getattr(runtime, "agent_group_chat", None)
        if service is None or store is None:
            logger.debug(
                "AD-925: group-chat substrate not wired on runtime; skipping "
                "task room for parent %s.",
                parent.id,
            )
            return None

        # >=2 DISTINCT crew assignees (a single-agent task needs no room).
        crew_assignees = sorted(
            {
                c.assigned_to
                for c in children
                if c.assigned_to and self._is_crew_assignee(c.assigned_to)
            }
        )
        if len(crew_assignees) < 2:
            return None

        title = (
            f"Task: {parent.title}"
            if parent.title
            else f"Task {parent.id}"
        )
        # The first crew assignee is the creator: it passes the service's
        # _is_crew gate and is auto-added as a participant, so the final
        # participants are exactly the crew child-assignees.
        creator_id = crew_assignees[0]
        result = service.create_group_chat(
            creator_id=creator_id,
            title=title,
            participants=crew_assignees[1:],
            task_id=parent.id,
        )
        if result.ok and result.thread is not None:
            logger.info(
                "AD-925: opened task room %s for parent %s (%d crew, creator=%s).",
                result.thread.id,
                parent.id,
                len(crew_assignees),
                creator_id,
            )
            return result.thread
        else:
            logger.info(
                "AD-925: task room not opened for parent %s (%s); fan-out continues.",
                parent.id,
                result.error or "unknown",
            )
        return None

    async def _start_crew_session(
        self,
        parent: WorkItem,
        resolved_thread: ChatThread | None,
    ) -> None:
        if parent.work_type != "crew_session":
            return
        service = self._crew_session_service
        if service is None:
            raise ValueError("crew_session_service_unavailable")
        contract = await service.get_session(parent.id)
        if contract is None:
            raise ValueError("crew_session_not_initialized")
        if resolved_thread is None or resolved_thread.id != contract.thread_id:
            raise ValueError("crew_session_thread_mismatch")
        if contract.state not in {"discussing", "executing"}:
            raise ValueError("crew_session_state_not_executable")
        if contract.state == "executing":
            return
        recovery = await service.get_recovery(parent.id)
        if recovery is not None:
            values = recovery.model_dump(mode="json")
            values["phase"] = "executing"
            next_recovery = type(recovery).model_validate(values)
            await service.transition_session(
                parent.id,
                "executing",
                expected_revision=contract.revision,
                expected_recovery=recovery,
                recovery=next_recovery,
            )
            return
        await service.transition_session(
            parent.id,
            "executing",
            expected_revision=contract.revision,
        )

    async def _persist_terminal_result(
        self,
        *,
        parent_id: str,
        child: WorkItem,
        thread_id: str,
        status: str,
        stopped_reason: str,
        output: Any,
        tool_trace_ref: Any,
        actual_tokens: Any,
        artifact_refs: Any,
        started_at: float,
        finished_at: float,
        blocked_dependency_ids: list[str],
        expected_status: str,
        dependency_input_invalid: bool = False,
    ) -> SubtaskResult:
        spec_id = str(child.metadata.get("spec_id", child.id))
        normalized_reason = (
            stopped_reason if stopped_reason in _STOPPED_REASONS else "error"
        )
        assigned_to: str | None = None
        tokens = 0
        trace_ref: str | None = None
        refs: list[dict[str, Any]] = []
        result_blocked_dependency_ids: list[str] = []
        result_reason = normalized_reason
        persisted = False
        state_preconditions: dict[str, Any] | None = None
        evidence_normalized = False
        deferred_cancellation: asyncio.CancelledError | None = None
        try:
            child_id = _bounded_id(child.id)
            parent_key = _bounded_id(parent_id)
            assigned_to = (
                _bounded_id(child.assigned_to)
                if child.assigned_to
                else None
            )
            exact_unresolved_dependency_ids = (
                _exact_dependency_ids(blocked_dependency_ids)
                if normalized_reason == "dependency_blocked"
                else []
            )
            state_preconditions = {
                "expected_assigned_to_exact": assigned_to,
                "expected_parent_id": parent_key,
                "expected_depends_on": (
                    child.depends_on
                    if dependency_input_invalid
                    else _exact_dependency_ids(child.depends_on)
                ),
            }
            if not dependency_input_invalid:
                state_preconditions["expected_unresolved_dependency_ids"] = (
                    exact_unresolved_dependency_ids
                )
            tokens = _normalize_tokens(actual_tokens)
            trace_ref = _normalize_trace_ref(tool_trace_ref, child_id)
            refs = _normalize_artifact_refs(
                artifact_refs,
                thread_id=_bounded_id_or_empty(thread_id),
                child_id=child_id,
            )
            evidence = _build_execution_evidence(
                parent_id=parent_key,
                child=child,
                thread_id=thread_id,
                status=status,
                stopped_reason=normalized_reason,
                output=output,
                tool_trace_ref=trace_ref,
                artifact_refs=refs,
                actual_tokens=tokens,
                started_at=started_at,
                finished_at=finished_at,
                blocked_dependency_ids=blocked_dependency_ids,
            )
            metadata_patch: dict[str, Any] = {"crew_execution": evidence}
            if status == "done":
                parent = await self._store.get_work_item(parent_key)
                if parent is not None and parent.work_type == "crew_session":
                    if self._attachment_store is None or type(output) is not str:
                        raise ValueError("crew_execution_output_invalid")
                    output_bytes = output.encode("utf-8", errors="strict")
                    if not 1 <= len(output_bytes) <= _MAX_OUTPUT_BYTES:
                        raise ValueError("crew_execution_output_invalid")
                    content_hash = hashlib.sha256(output_bytes).hexdigest()
                    await self._attachment_store.write(
                        content_hash,
                        output_bytes,
                        "text/plain",
                        origin="agent_artifact",
                    )
                    readback = await self._attachment_store.read(content_hash)
                    if (
                        readback != output_bytes
                        or hashlib.sha256(readback).hexdigest() != content_hash
                    ):
                        raise ValueError("crew_execution_output_invalid")
                    metadata_patch["crew_execution_output"] = {
                        "version": 1,
                        "content_hash": content_hash,
                        "mime": "text/plain",
                        "size_bytes": len(output_bytes),
                    }
            refs = [dict(ref) for ref in evidence["artifact_refs"]]
            result_blocked_dependency_ids = list(
                evidence["blocked_dependency_ids"]
            )
            evidence_normalized = True
            commit_error: BaseException | None = None
            try:
                updated = await self._store.merge_work_item_metadata(
                    child_id,
                    metadata_patch,
                    expected_work_type=child.work_type,
                    expected_status=expected_status,
                    new_status=status,
                    actual_tokens_delta=tokens,
                    source="crew_executor",
                    **state_preconditions,
                )
            except asyncio.CancelledError as exc:
                commit_error = exc
            except Exception as exc:
                commit_error = exc
            if commit_error is not None:
                updated, reconciliation_cancellation = (
                    await self._reconcile_terminal_commit(
                        child=child,
                        expected_status=status,
                        metadata_patch=metadata_patch,
                        actual_tokens_delta=tokens,
                        initial_cancellation=(
                            commit_error
                            if isinstance(commit_error, asyncio.CancelledError)
                            else None
                        ),
                    )
                )
                if reconciliation_cancellation is not None:
                    deferred_cancellation = reconciliation_cancellation
                if updated is None:
                    if deferred_cancellation is None:
                        raise commit_error
                    raise ValueError("crew_execution_persistence_cancelled")
            if updated is None:
                raise ValueError("crew_execution_persistence_failed")
            persisted = True
        except Exception as exc:
            state_conflict = (
                isinstance(exc, ValueError)
                and str(exc) in {
                    "work_item_state_conflict",
                    "work_item_dependency_state_conflict",
                }
            )
            if state_conflict:
                logger.error(
                    "Crew child %s terminal evidence for reason %s conflicted "
                    "with live ownership, parent, or dependency state; the "
                    "stale writer will attach no evidence and will not mutate "
                    "the authoritative row",
                    child.id,
                    normalized_reason,
                    exc_info=True,
                )
            else:
                logger.error(
                    "Crew child %s terminal evidence for reason %s could not be "
                    "committed atomically; it will not unblock dependents and a "
                    "validated in_progress-to-failed fallback will be attempted",
                    child.id,
                    normalized_reason,
                    exc_info=True,
                )
                result_reason = "error"
                if not evidence_normalized:
                    tokens = 0
                    trace_ref = None
                    refs = []
                    result_blocked_dependency_ids = []
            if (
                expected_status == "in_progress"
                and not state_conflict
                and state_preconditions is not None
            ):
                try:
                    fallback = await self._store.merge_work_item_metadata(
                        child.id,
                        {},
                        expected_work_type=child.work_type,
                        expected_status=expected_status,
                        new_status="failed",
                        actual_tokens_delta=0,
                        source="crew_executor_persistence_fallback",
                        **state_preconditions,
                    )
                    if fallback is None:
                        raise ValueError("crew_execution_fallback_failed")
                except Exception as fallback_exc:
                    fallback_conflict = (
                        isinstance(fallback_exc, ValueError)
                        and str(fallback_exc) in {
                            "work_item_state_conflict",
                            "work_item_dependency_state_conflict",
                        }
                    )
                    if fallback_conflict:
                        logger.error(
                            "Crew child %s persistence fallback conflicted with "
                            "live ownership, parent, or dependency state; the "
                            "authoritative row remains untouched and the caller "
                            "receives failed",
                            child.id,
                            exc_info=True,
                        )
                    else:
                        logger.error(
                            "Crew child %s evidence and fallback status "
                            "persistence both failed; the caller receives failed "
                            "and must not treat the child as complete",
                            child.id,
                            exc_info=True,
                        )
        if deferred_cancellation is not None:
            raise deferred_cancellation
        result_status = status if persisted else "failed"
        return SubtaskResult(
            work_item_id=child.id,
            spec_id=spec_id,
            agent_id=assigned_to or "",
            output=output if type(output) is str else "",
            status=result_status,
            tool_trace_ref=trace_ref,
            started_at=started_at,
            finished_at=finished_at,
            stopped_reason=result_reason,
            actual_tokens=tokens,
            artifact_refs=refs,
            blocked_dependency_ids=result_blocked_dependency_ids,
        )

    async def _reconcile_terminal_commit(
        self,
        *,
        child: WorkItem,
        expected_status: str,
        metadata_patch: dict[str, Any],
        actual_tokens_delta: int,
        initial_cancellation: asyncio.CancelledError | None,
    ) -> tuple[WorkItem | None, asyncio.CancelledError | None]:
        current_task = asyncio.current_task()
        if initial_cancellation is not None and current_task is not None:
            current_task.uncancel()
        expected_metadata = dict(child.metadata)
        expected_metadata.update(metadata_patch)
        expected_actual_tokens = child.actual_tokens + actual_tokens_delta

        async def _load_and_prove() -> WorkItem | None:
            authoritative = await self._store.get_work_item(child.id)
            if (
                authoritative is None
                or authoritative.id != child.id
                or authoritative.work_type != child.work_type
                or authoritative.status != expected_status
                or authoritative.assigned_to != child.assigned_to
                or authoritative.parent_id != child.parent_id
                or authoritative.depends_on != child.depends_on
                or authoritative.actual_tokens != expected_actual_tokens
                or type(authoritative.metadata) is not dict
                or not _json_dicts_exactly_equal(
                    authoritative.metadata,
                    expected_metadata,
                )
            ):
                return None
            return authoritative

        reconciliation = asyncio.create_task(
            _load_and_prove(),
            name=f"crew-terminal-reconcile:{child.id}",
        )
        first_cancellation = initial_cancellation
        while not reconciliation.done():
            try:
                await asyncio.shield(reconciliation)
            except asyncio.CancelledError as exc:
                if first_cancellation is None:
                    first_cancellation = exc
                current_task = asyncio.current_task()
                if current_task is not None:
                    current_task.uncancel()
        try:
            authoritative = reconciliation.result()
        except Exception:
            logger.exception(
                "Crew child %s terminal reconciliation could not inspect exact "
                "post-commit authority; the original persistence disposition "
                "continues to its cancellation or fallback path",
                child.id,
            )
            authoritative = None
        return authoritative, first_cancellation

    def _unresolved_dependency_ids(
        self,
        child: WorkItem,
        done_ids: set[str],
    ) -> list[str]:
        return [
            dependency_id
            for dependency_id in _exact_dependency_ids(child.depends_on)
            if dependency_id not in done_ids
        ]

    def _emit_subtask_completed(
        self,
        parent_id: str,
        result: SubtaskResult,
    ) -> None:
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
