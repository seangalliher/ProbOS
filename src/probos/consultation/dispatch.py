"""AD-594c v1: Parallel execution dispatch for consultation workspaces.

Reads an approved ``plan/plan_v{N}.md`` from a ``ConsultationWorkspace``,
decomposes it into ``WorkItemSpec`` rows, detects resource conflicts,
registers ``WorkItem`` rows on ``runtime.work_item_store``, mirrors each
spec into the workspace ``workitems/`` directory for audit, and exposes
progress + completion + blocker surfaces.

LLM-driven plan-to-spec semantic decomposition is deferred behind the
``PlanDecomposer`` Protocol seam (mirrors AD-594a's ``InputProcessor`` and
AD-594d's ``FormatTransformer`` precedent). v1 ships
``MarkdownPlanDecomposer`` covering structured ATX-2-heading plans.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, TYPE_CHECKING

from probos.events import EventType

if TYPE_CHECKING:
    from probos.consultation.workspace import (
        ConsultationWorkspace,
        WorkspaceRegistry,
    )

logger = logging.getLogger(__name__)

_DISPATCH_SCHEMA_VERSION = 1

# WorkItem statuses that signal the item has reached a terminal state for
# dispatch purposes. WorkItemStore + AD-498 WorkTypeRegistry can extend this
# via custom work types; v1 uses the canonical built-in set.
_TERMINAL_STATUSES = frozenset({"completed", "cancelled", "failed", "closed"})


# ---------------------------------------------------------------------------
# Specs and reports
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkItemSpec:
    """Structured plan-derived spec; producer side of dispatch."""
    spec_id: str
    title: str
    description: str = ""
    work_type: str = ""
    agent: str = ""                              # assigned_to hint
    priority: int = 3
    depends_on: tuple[str, ...] = ()             # spec_ids this spec waits on
    resources: tuple[str, ...] = ()              # files/paths/locks the spec touches
    metadata: dict[str, Any] = field(default_factory=dict)
    # AD-858: optional declared acceptance criterion for this sub-task. When an
    # LLM decomposer supplies it, the AD-860 verifier judges the result against
    # this contract; ``None`` (the backward-compatible default for
    # ``MarkdownPlanDecomposer`` and all existing call sites) means the verifier
    # falls back to free-text critique. Placed after ``metadata`` so the
    # defaulted-field-ordering rule holds.
    expected_output: str | None = None
    capability: str | None = None   # AD-863: one-phrase "kind of work" for agent resolution
    department: str | None = None   # AD-863: optional department hint (engineering/science/medical/security/bridge/operations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "title": self.title,
            "description": self.description,
            "work_type": self.work_type,
            "agent": self.agent,
            "priority": int(self.priority),
            "depends_on": list(self.depends_on),
            "resources": list(self.resources),
            "metadata": dict(self.metadata),
            "expected_output": self.expected_output,
            "capability": self.capability,
            "department": self.department,
        }


@dataclass(frozen=True)
class ConflictPair:
    """Two specs that share a resource."""
    a_spec_id: str
    b_spec_id: str
    shared_resources: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "a_spec_id": self.a_spec_id,
            "b_spec_id": self.b_spec_id,
            "shared_resources": list(self.shared_resources),
        }


@dataclass(frozen=True)
class DispatchReceipt:
    """Result of a single ``ParallelDispatcher.dispatch`` call."""
    workspace_id: str
    plan_version: int
    dispatched_spec_ids: tuple[str, ...]
    work_item_ids: tuple[str, ...]                       # 1:1 with dispatched_spec_ids
    spec_id_to_work_item_id: dict[str, str]
    serialization_edges_added: tuple[ConflictPair, ...]  # synthetic depends_on injected
    conflicts: tuple[ConflictPair, ...]                  # original detected pairs
    started_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "plan_version": self.plan_version,
            "dispatched_spec_ids": list(self.dispatched_spec_ids),
            "work_item_ids": list(self.work_item_ids),
            "spec_id_to_work_item_id": dict(self.spec_id_to_work_item_id),
            "serialization_edges_added": [c.to_dict() for c in self.serialization_edges_added],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "started_at": self.started_at,
        }


@dataclass(frozen=True)
class ProgressSnapshot:
    """Aggregate WorkItem-status view over a single workspace."""
    workspace_id: str
    total: int
    by_status: dict[str, int]
    completed: int
    open: int
    in_progress: int
    blocked_spec_ids: tuple[str, ...]
    captured_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "total": int(self.total),
            "by_status": dict(self.by_status),
            "completed": int(self.completed),
            "open": int(self.open),
            "in_progress": int(self.in_progress),
            "blocked_spec_ids": list(self.blocked_spec_ids),
            "captured_at": self.captured_at,
        }


@dataclass(frozen=True)
class BlockerReport:
    """A single spec whose depends_on set is unmet past threshold."""
    workspace_id: str
    spec_id: str
    work_item_id: str
    unmet_dependencies: tuple[str, ...]
    seconds_blocked: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "spec_id": self.spec_id,
            "work_item_id": self.work_item_id,
            "unmet_dependencies": list(self.unmet_dependencies),
            "seconds_blocked": self.seconds_blocked,
        }


# ---------------------------------------------------------------------------
# Plan decomposer (Protocol + v1 markdown impl)
# ---------------------------------------------------------------------------


class PlanDecomposer(Protocol):
    """Convert plan markdown into a list of work-item specs.

    LLM-driven semantic decomposers plug in here under a separate AD.
    """

    def decompose(self, markdown_text: str) -> list[WorkItemSpec]: ...


_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
_BULLET_KV_RE = re.compile(r"^-\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$")


def _slugify(value: str) -> str:
    out = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return out or uuid.uuid4().hex[:8]


def _parse_inline_list(value: str) -> tuple[str, ...]:
    """Parse ``[a, b, c]`` or ``a, b, c`` or ``a`` into a tuple."""
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return tuple(parts)


class MarkdownPlanDecomposer:
    """Default v1 decomposer.

    Recognises ATX-2 headings (``## Task title``) as task boundaries and
    bullet ``- key: value`` lines under each heading as spec attributes.
    Recognised keys: ``id``, ``description``, ``work_type``, ``agent``,
    ``priority``, ``depends_on``, ``resources``. Unknown keys are stored
    under ``metadata``. Missing ``id`` falls back to a slug of the title;
    missing ``priority`` defaults to 3.
    """

    def decompose(self, markdown_text: str) -> list[WorkItemSpec]:
        specs: list[WorkItemSpec] = []
        current_title: str | None = None
        current: dict[str, Any] = {}

        def flush() -> None:
            if current_title is None:
                return
            spec_id = str(current.pop("id", _slugify(current_title)))
            try:
                priority = int(current.pop("priority", 3))
            except (TypeError, ValueError):
                priority = 3
            description = str(current.pop("description", ""))
            work_type = str(current.pop("work_type", ""))
            agent = str(current.pop("agent", ""))
            depends_on = _parse_inline_list(str(current.pop("depends_on", "")))
            resources = _parse_inline_list(str(current.pop("resources", "")))
            specs.append(WorkItemSpec(
                spec_id=spec_id,
                title=current_title,
                description=description,
                work_type=work_type,
                agent=agent,
                priority=priority,
                depends_on=depends_on,
                resources=resources,
                metadata=dict(current),
            ))

        for raw in markdown_text.splitlines():
            line = raw.rstrip()
            if not line.strip():
                continue
            heading = _HEADING_RE.match(line)
            if heading:
                flush()
                current_title = heading.group(1).strip()
                current = {}
                continue
            if current_title is None:
                continue  # preamble lines ignored
            kv = _BULLET_KV_RE.match(line.lstrip())
            if kv:
                key = kv.group(1).lower()
                value = kv.group(2)
                current[key] = value
        flush()
        return specs


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


class ConflictDetector:
    """Pure resource-overlap detector. Stateless."""

    def detect(self, specs: list[WorkItemSpec]) -> list[ConflictPair]:
        out: list[ConflictPair] = []
        for i, a in enumerate(specs):
            if not a.resources:
                continue
            a_set = frozenset(a.resources)
            for b in specs[i + 1:]:
                if not b.resources:
                    continue
                shared = a_set.intersection(b.resources)
                if shared:
                    out.append(ConflictPair(
                        a_spec_id=a.spec_id,
                        b_spec_id=b.spec_id,
                        shared_resources=tuple(sorted(shared)),
                    ))
        return out


# ---------------------------------------------------------------------------
# Parallel dispatcher
# ---------------------------------------------------------------------------


class ParallelDispatcher:
    """Orchestrator. Reads plan, decomposes, dispatches, tracks progress.

    Construct via the ``_wire_consultation_dispatch`` finalize wirer; tests
    construct directly with ``SimpleNamespace``-shaped dependencies.
    """

    def __init__(
        self,
        *,
        workspace_registry: "WorkspaceRegistry",
        work_item_store: Any,
        records_store: Any,
        config: Any,
        decomposer: PlanDecomposer | None = None,
        conflict_detector: ConflictDetector | None = None,
        emit_event: Any | None = None,
        clock: Any = time.time,
    ) -> None:
        self._registry = workspace_registry
        self._store = work_item_store
        self._records = records_store
        self._config = config
        self._decomposer: PlanDecomposer = decomposer or MarkdownPlanDecomposer()
        self._conflicts = conflict_detector or ConflictDetector()
        self._emit = emit_event
        self._clock = clock
        # Dispatch state: workspace_id -> {"started_at", "spec_id_to_work_item_id",
        # "specs", "blocker_dedup": set[str]}
        self._state: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _safe_emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        if self._emit is None:
            return
        try:
            self._emit(event_type, payload)
        except Exception:  # tier-2: telemetry must never break dispatch
            logger.warning(
                "AD-594c: emit_event failed for %s", event_type.value, exc_info=True,
            )

    async def _read_latest_plan(
        self, workspace: "ConsultationWorkspace", *, plan_version: int | None,
    ) -> tuple[int, str]:
        """Resolve plan version + content. Raises ValueError if no plan exists."""
        repo_root = self._records.repo_path  # Path (public property on RecordsStore)
        plan_dir = repo_root / "consultations" / workspace.id / "plan"
        candidates: list[int] = []
        if plan_dir.exists():
            for p in plan_dir.iterdir():
                if p.is_file() and p.name.startswith("plan_v") and p.name.endswith(".md"):
                    try:
                        candidates.append(int(p.name[len("plan_v"):-len(".md")]))
                    except ValueError:
                        continue
        if not candidates:
            raise ValueError(f"AD-594c: no plan files in workspace {workspace.id}")
        if plan_version is None:
            plan_version = max(candidates)
        elif plan_version not in candidates:
            raise ValueError(
                f"AD-594c: plan_v{plan_version}.md not found in workspace {workspace.id}",
            )
        path = f"{workspace.root_path}/plan/plan_v{plan_version}.md"
        text = await self._records.read_workspace_file(path)
        if text is None:
            raise ValueError(
                f"AD-594c: plan_v{plan_version}.md unreadable in workspace {workspace.id}",
            )
        return plan_version, text

    @staticmethod
    def _serialize_conflicts(
        specs: list[WorkItemSpec], conflicts: list[ConflictPair],
    ) -> tuple[list[WorkItemSpec], list[ConflictPair]]:
        """Inject synthetic depends_on edges so colliding specs run sequentially.

        Original spec list order is preserved; for each conflict pair (a, b) where
        a appears before b, b gains a depends_on edge to a. Returns the rewritten
        spec list and the list of edges added.
        """
        if not conflicts:
            return specs, []
        order = {s.spec_id: i for i, s in enumerate(specs)}
        added: list[ConflictPair] = []
        # Map spec_id -> set of new dependency spec_ids
        new_deps: dict[str, set[str]] = {s.spec_id: set() for s in specs}
        for c in conflicts:
            ai = order.get(c.a_spec_id, -1)
            bi = order.get(c.b_spec_id, -1)
            if ai < 0 or bi < 0:
                continue
            if ai < bi:
                first, second = c.a_spec_id, c.b_spec_id
            else:
                first, second = c.b_spec_id, c.a_spec_id
            if first not in new_deps[second] and first not in specs[order[second]].depends_on:
                new_deps[second].add(first)
                added.append(ConflictPair(
                    a_spec_id=first, b_spec_id=second,
                    shared_resources=c.shared_resources,
                ))
        rewritten: list[WorkItemSpec] = []
        for s in specs:
            extra = new_deps.get(s.spec_id, set())
            if not extra:
                rewritten.append(s)
                continue
            merged = tuple(list(s.depends_on) + sorted(extra))
            rewritten.append(WorkItemSpec(
                spec_id=s.spec_id, title=s.title, description=s.description,
                work_type=s.work_type, agent=s.agent, priority=s.priority,
                depends_on=merged, resources=s.resources, metadata=dict(s.metadata),
            ))
        return rewritten, added

    # ------------------------------------------------------------------
    # Public API — dispatch
    # ------------------------------------------------------------------
    async def dispatch(
        self,
        workspace_id: str,
        *,
        plan_version: int | None = None,
        actor_id: str = "captain",
    ) -> DispatchReceipt:
        """Decompose, conflict-resolve, register WorkItems, transition state.

        Raises ``ValueError`` for missing workspace or missing plan files.
        Per-WorkItem creation failures are tier-2 logged but do not abort
        dispatch — partial dispatch is preferable to silent total loss.
        """
        workspace = await self._registry.get(workspace_id)
        if workspace is None:
            raise ValueError(f"AD-594c: unknown workspace {workspace_id!r}")

        version, plan_text = await self._read_latest_plan(workspace, plan_version=plan_version)
        raw_specs = self._decomposer.decompose(plan_text)
        if not raw_specs:
            raise ValueError(
                f"AD-594c: plan_v{version}.md decomposed to zero specs in workspace {workspace_id}",
            )
        conflicts = self._conflicts.detect(raw_specs)
        specs, edges_added = self._serialize_conflicts(raw_specs, conflicts)

        spec_to_wid: dict[str, str] = {}
        work_item_ids: list[str] = []
        cfg = self._config
        default_tags = list(getattr(cfg, "default_tags", ["consultation"]))
        default_work_type = getattr(cfg, "default_work_type", "duty")

        for spec in specs:
            # Translate spec.depends_on (spec_ids) into WorkItem ids if known.
            translated_deps = [
                spec_to_wid[d] for d in spec.depends_on if d in spec_to_wid
            ]
            tags = sorted(set(default_tags + [f"workspace:{workspace_id}"]))
            metadata = dict(spec.metadata)
            metadata.update({
                "workspace_id": workspace_id,
                "spec_id": spec.spec_id,
                "resources": list(spec.resources),
                "plan_version": version,
                "expected_output": spec.expected_output,
                "capability": spec.capability,
                "department": spec.department,
            })
            try:
                item = await self._store.create_work_item(
                    title=spec.title or spec.spec_id,
                    description=spec.description,
                    work_type=spec.work_type or default_work_type,
                    priority=int(spec.priority),
                    depends_on=translated_deps,
                    assigned_to=spec.agent or None,
                    tags=tags,
                    metadata=metadata,
                    created_by=actor_id,
                )
            except Exception:
                logger.warning(
                    "AD-594c: create_work_item failed for spec=%s on workspace=%s",
                    spec.spec_id, workspace_id, exc_info=True,
                )
                continue
            wid = getattr(item, "id", "") or ""
            if not wid:
                logger.warning(
                    "AD-594c: created WorkItem missing id for spec=%s on workspace=%s",
                    spec.spec_id, workspace_id,
                )
                continue
            spec_to_wid[spec.spec_id] = wid
            work_item_ids.append(wid)
            mirror = spec.to_dict()
            mirror["work_item_id"] = wid
            try:
                await workspace.add_work_item(mirror, agent_id=actor_id)
            except Exception:
                logger.warning(
                    "AD-594c: workspace.add_work_item mirror failed for spec=%s",
                    spec.spec_id, exc_info=True,
                )

        # Best-effort transition APPROVED -> EXECUTING. False return is logged
        # by transition_to itself; if the workspace is in a different state
        # (e.g. already EXECUTING from a previous dispatch), proceed.
        from probos.consultation.workspace import WorkspaceLifecycleState
        await workspace.transition_to(WorkspaceLifecycleState.EXECUTING, agent_id=actor_id)

        started_at = float(self._clock())
        receipt = DispatchReceipt(
            workspace_id=workspace_id,
            plan_version=version,
            dispatched_spec_ids=tuple(s.spec_id for s in specs if s.spec_id in spec_to_wid),
            work_item_ids=tuple(work_item_ids),
            spec_id_to_work_item_id=dict(spec_to_wid),
            serialization_edges_added=tuple(edges_added),
            conflicts=tuple(conflicts),
            started_at=started_at,
        )
        self._state[workspace_id] = {
            "started_at": started_at,
            "specs": list(specs),
            "spec_id_to_work_item_id": dict(spec_to_wid),
            "blocker_dedup": set(),
            "plan_version": version,
        }
        try:
            await workspace.append_journal(
                f"dispatch started: {len(work_item_ids)} work items "
                f"(conflicts={len(conflicts)}, serialization_edges={len(edges_added)})",
                agent_id=actor_id,
            )
        except Exception:
            logger.warning(
                "AD-594c: journal append failed on dispatch for workspace=%s",
                workspace_id, exc_info=True,
            )
        self._safe_emit(EventType.PARALLEL_DISPATCH_STARTED, {
            "workspace_id": workspace_id,
            "plan_version": version,
            "work_item_count": len(work_item_ids),
            "conflict_count": len(conflicts),
            "serialization_edge_count": len(edges_added),
        })
        return receipt

    # ------------------------------------------------------------------
    # Public API — progress
    # ------------------------------------------------------------------
    async def get_progress(self, workspace_id: str) -> ProgressSnapshot:
        items: list[Any] = []
        try:
            items = await self._store.list_work_items(
                tags=[f"workspace:{workspace_id}"], limit=10000,
            )
        except Exception:
            logger.warning(
                "AD-594c: list_work_items failed for workspace=%s",
                workspace_id, exc_info=True,
            )
        by_status: dict[str, int] = {}
        completed = 0
        open_count = 0
        in_progress = 0
        for it in items:
            status = getattr(it, "status", "open") or "open"
            by_status[status] = by_status.get(status, 0) + 1
            if status in _TERMINAL_STATUSES:
                completed += 1
            elif status in {"in_progress", "running", "active"}:
                in_progress += 1
            else:
                open_count += 1
        snapshot = ProgressSnapshot(
            workspace_id=workspace_id,
            total=len(items),
            by_status=by_status,
            completed=completed,
            open=open_count,
            in_progress=in_progress,
            blocked_spec_ids=tuple(),  # populated by detect_blockers
            captured_at=float(self._clock()),
        )
        if getattr(self._config, "progress_subscription_enabled", True):
            self._safe_emit(EventType.PARALLEL_DISPATCH_PROGRESS, {
                "workspace_id": workspace_id,
                "total": snapshot.total,
                "completed": snapshot.completed,
                "in_progress": snapshot.in_progress,
                "open": snapshot.open,
            })
        return snapshot

    # ------------------------------------------------------------------
    # Public API — completion
    # ------------------------------------------------------------------
    async def check_completion(
        self, workspace_id: str, *, actor_id: str = "captain",
    ) -> bool:
        """Returns True iff all dispatched WorkItems are terminal AND the
        workspace successfully transitioned EXECUTING -> COMPLETED on this
        call (False if the workspace was already past EXECUTING or if any
        item is non-terminal). Idempotent: a second call after COMPLETED
        returns False without re-transitioning.
        """
        snapshot = await self.get_progress(workspace_id)
        if snapshot.total == 0:
            return False
        if snapshot.completed != snapshot.total:
            return False
        workspace = await self._registry.get(workspace_id)
        if workspace is None:
            return False
        from probos.consultation.workspace import WorkspaceLifecycleState
        if workspace.lifecycle_state != WorkspaceLifecycleState.EXECUTING:
            return False
        ok = await workspace.transition_to(
            WorkspaceLifecycleState.COMPLETED, agent_id=actor_id,
        )
        if ok:
            try:
                await workspace.append_journal(
                    f"dispatch completed: {snapshot.completed}/{snapshot.total} work items terminal",
                    agent_id=actor_id,
                )
            except Exception:
                logger.warning(
                    "AD-594c: journal append failed on completion for workspace=%s",
                    workspace_id, exc_info=True,
                )
        return bool(ok)

    # ------------------------------------------------------------------
    # Public API — blockers
    # ------------------------------------------------------------------
    async def detect_blockers(
        self, workspace_id: str, *, now: float | None = None,
    ) -> list[BlockerReport]:
        state = self._state.get(workspace_id)
        if state is None:
            return []
        threshold = float(getattr(self._config, "blocker_threshold_seconds", 600.0))
        clock_now = float(now if now is not None else self._clock())
        elapsed = clock_now - float(state["started_at"])
        if elapsed < threshold:
            return []

        items: list[Any] = []
        try:
            items = await self._store.list_work_items(
                tags=[f"workspace:{workspace_id}"], limit=10000,
            )
        except Exception:
            logger.warning(
                "AD-594c: list_work_items failed during detect_blockers for workspace=%s",
                workspace_id, exc_info=True,
            )
            return []
        wid_to_item = {getattr(it, "id", ""): it for it in items if getattr(it, "id", "")}
        spec_to_wid: dict[str, str] = state["spec_id_to_work_item_id"]
        terminal_wids = {
            wid for wid, it in wid_to_item.items()
            if (getattr(it, "status", "") or "") in _TERMINAL_STATUSES
        }

        reports: list[BlockerReport] = []
        dedup: set[str] = state["blocker_dedup"]
        for spec in state["specs"]:
            wid = spec_to_wid.get(spec.spec_id)
            if wid is None:
                continue
            item = wid_to_item.get(wid)
            if item is None:
                continue
            status = getattr(item, "status", "open") or "open"
            if status in _TERMINAL_STATUSES:
                continue
            unmet: list[str] = []
            for dep_spec_id in spec.depends_on:
                dep_wid = spec_to_wid.get(dep_spec_id)
                if dep_wid is None or dep_wid not in terminal_wids:
                    unmet.append(dep_spec_id)
            if not unmet:
                continue
            report = BlockerReport(
                workspace_id=workspace_id,
                spec_id=spec.spec_id,
                work_item_id=wid,
                unmet_dependencies=tuple(unmet),
                seconds_blocked=elapsed,
            )
            reports.append(report)
            dedup_key = f"{workspace_id}:{spec.spec_id}"
            if dedup_key not in dedup:
                dedup.add(dedup_key)
                self._safe_emit(EventType.PARALLEL_DISPATCH_BLOCKED, {
                    "workspace_id": workspace_id,
                    "spec_id": spec.spec_id,
                    "work_item_id": wid,
                    "unmet_dependencies": list(unmet),
                    "seconds_blocked": elapsed,
                })
                workspace = await self._registry.get(workspace_id)
                if workspace is not None:
                    try:
                        await workspace.append_journal(
                            f"blocker: {spec.spec_id} unmet={','.join(unmet)} "
                            f"seconds={elapsed:.1f}",
                            agent_id="dispatcher",
                        )
                    except Exception:
                        logger.warning(
                            "AD-594c: journal append failed on blocker for workspace=%s",
                            workspace_id, exc_info=True,
                        )
        return reports

    # ------------------------------------------------------------------
    # Public API — revoke (best-effort cancel for tests / teardown)
    # ------------------------------------------------------------------
    async def revoke(self, workspace_id: str, *, actor_id: str = "captain") -> int:
        state = self._state.get(workspace_id)
        if state is None:
            return 0
        spec_to_wid: dict[str, str] = state["spec_id_to_work_item_id"]
        cancelled = 0
        items: list[Any] = []
        try:
            items = await self._store.list_work_items(
                tags=[f"workspace:{workspace_id}"], limit=10000,
            )
        except Exception:
            return 0
        live_wids = {
            getattr(it, "id", ""): (getattr(it, "status", "") or "")
            for it in items
        }
        for wid in spec_to_wid.values():
            status = live_wids.get(wid, "")
            if not wid or status in _TERMINAL_STATUSES:
                continue
            try:
                await self._store.update_work_item(wid, status="cancelled")
                cancelled += 1
            except Exception:
                logger.warning(
                    "AD-594c: update_work_item(status=cancelled) failed for wid=%s",
                    wid, exc_info=True,
                )
        return cancelled
