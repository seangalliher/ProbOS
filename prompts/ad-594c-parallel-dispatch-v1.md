# AD-594c v1 — Parallel Execution Dispatch (Plan → WorkItems with conflict & progress)

**Closes:** GH issue #162
**HEAD:** `3bcd608`
**Baseline:** 11528 → target ≥ 11553 (Δ ≥ +25)
**OSS only.** No HXI surface. No router. No new Intent. No LLM call.

## Problem

`AD-594a` (Wave 44) shipped the consultation workspace substrate with `plan/plan_v{N}.md` files, a `workitems/` subdirectory, and `ConsultationWorkspace.add_work_item(spec)` that writes a YAML file. `AD-594d` (Wave 79) shipped the delivery pipeline. **The middle of the consultation flow — converting an approved plan into actual `WorkItem` rows on the canonical `WorkItemStore` so executors can pick them up — has no implementation.** GH #162 lists 7 explicit scope bullets covering decomposition, conflict detection, multi-executor dispatch, task boundaries, progress, completion, and blocker escalation.

`AD-594b` (#161 consultation primitive) is also unshipped, but verify-first against HEAD `3bcd608` confirms AD-594c does NOT need it: AD-594c reads `plan/plan_v{N}.md` from the workspace regardless of who authored the plan (manual captain edit, AD-594b primitive output, dream synthesis, or a future LLM advisor). The roadmap "depends: AD-594b" is sequencing prose, not a technical coupling.

## Solution

Single new module `src/probos/consultation/dispatch.py` ships:

1. **`WorkItemSpec`** frozen dataclass — the structured spec a `PlanDecomposer` produces.
2. **`PlanDecomposer`** Protocol + `MarkdownPlanDecomposer` v1 default — parses ATX-2 task headings + body bullet lines into `list[WorkItemSpec]`. LLM-driven decomposers plug in here under a separate AD.
3. **`ConflictDetector`** — pure function `detect(specs) -> list[ConflictPair]`. Two specs conflict if their `resources` sets intersect.
4. **`ParallelDispatcher`** — orchestrator with five public async methods:
   - `dispatch(workspace_id, *, plan_version=None) -> DispatchReceipt` — read latest plan; decompose; conflict-resolve by serializing colliding specs (synthesize `depends_on` edges in original order); register WorkItems via `runtime.work_item_store.create_work_item(...)`; mirror each spec into the workspace via `workspace.add_work_item(...)`; transition `APPROVED → EXECUTING`; emit `PARALLEL_DISPATCH_STARTED`.
   - `get_progress(workspace_id) -> ProgressSnapshot` — read `runtime.work_item_store.list_work_items(tags=[...])` and aggregate.
   - `check_completion(workspace_id) -> bool` — when all dispatched WorkItems reach a terminal status, append journal entry, transition `EXECUTING → COMPLETED`. Idempotent.
   - `detect_blockers(workspace_id, *, now=None) -> list[BlockerReport]` — find specs whose `depends_on` is unmet AND wall-time-since-dispatch exceeds threshold; emit `PARALLEL_DISPATCH_BLOCKED` once per blocker via dedup ring.
   - `revoke(workspace_id) -> int` — best-effort; calls `update_work_item(id, status="cancelled")` on each dispatched item that has not reached a terminal status; returns count cancelled. (Used by tests; no auto-trigger.)
5. **`ConsultationDispatchConfig`** Pydantic model + `_wire_consultation_dispatch` finalize wirer.
6. **3 new EventTypes** (`PARALLEL_DISPATCH_STARTED`, `PARALLEL_DISPATCH_PROGRESS`, `PARALLEL_DISPATCH_BLOCKED`).

PDF/LLM-driven decomposition is deferred behind the `PlanDecomposer` Protocol seam (mirrors AD-594a's `InputProcessor` and AD-594d's `FormatTransformer` precedent).

---

## Section 0 — EventTypes

### File: `src/probos/events.py`

Add 3 new EventType values immediately after the existing `CONSULTATION_FAILED` (line 305) inside the `EventType` enum.

```python
===MODIFY: src/probos/events.py===
===SEARCH===
    # Consultation protocol (AD-594)
    CONSULTATION_REQUESTED = "consultation_requested"
    CONSULTATION_COMPLETED = "consultation_completed"
    CONSULTATION_TIMEOUT = "consultation_timeout"
    CONSULTATION_FAILED = "consultation_failed"

    # Billet management (AD-595a)
===REPLACE===
    # Consultation protocol (AD-594)
    CONSULTATION_REQUESTED = "consultation_requested"
    CONSULTATION_COMPLETED = "consultation_completed"
    CONSULTATION_TIMEOUT = "consultation_timeout"
    CONSULTATION_FAILED = "consultation_failed"

    # Parallel execution dispatch (AD-594c)
    PARALLEL_DISPATCH_STARTED = "parallel_dispatch_started"
    PARALLEL_DISPATCH_PROGRESS = "parallel_dispatch_progress"
    PARALLEL_DISPATCH_BLOCKED = "parallel_dispatch_blocked"

    # Billet management (AD-595a)
===END REPLACE===
```

Verification: `grep -n "PARALLEL_DISPATCH_" src/probos/events.py` returns exactly 3 hits, all on the enum lines.

---

## Section 1 — Pydantic config

### File: `src/probos/config.py`

Add `ConsultationDispatchConfig` immediately after `ConsultationDeliveryConfig` (the model ends at line ~2108 before `class CommunicationsConfig`).

```python
===MODIFY: src/probos/config.py===
===SEARCH===
class ConsultationDeliveryConfig(BaseModel):
    """AD-594d v1: Consultation delivery pipeline.

    Default-True is intentional — pipeline construction is read-only on boot
    (registers built-in adapters into an in-memory dict; no IO). Workspaces
    consume the pipeline only when an agent calls ``runtime.consultation_delivery
    .deliver(...)``. Same precedent as ``ConsultationWorkspaceConfig``.
    """
    enabled: bool = True
    # Adapter enablement — operators can disable individual adapters without
    # disabling the pipeline. Disabled adapters are not registered.
    local_file_enabled: bool = True
    github_enabled: bool = True
    # LocalFileAdapter: list of allowed destination root paths (absolute or
    # tilde-expandable). Empty = LocalFileAdapter registered with no roots
    # (rejects every delivery with "no allowed_roots configured").
    local_file_allowed_roots: list[str] = Field(default_factory=list)
    # GitHubAdapter: env var name from which the token is read at delivery time.
    github_token_env: str = "GITHUB_TOKEN"
    # Default approval requirement — used when a request does not specify
    # requires_approval explicitly via the dataclass default of False.
    default_requires_approval: bool = False


class CommunicationsConfig(BaseModel):
===REPLACE===
class ConsultationDeliveryConfig(BaseModel):
    """AD-594d v1: Consultation delivery pipeline.

    Default-True is intentional — pipeline construction is read-only on boot
    (registers built-in adapters into an in-memory dict; no IO). Workspaces
    consume the pipeline only when an agent calls ``runtime.consultation_delivery
    .deliver(...)``. Same precedent as ``ConsultationWorkspaceConfig``.
    """
    enabled: bool = True
    # Adapter enablement — operators can disable individual adapters without
    # disabling the pipeline. Disabled adapters are not registered.
    local_file_enabled: bool = True
    github_enabled: bool = True
    # LocalFileAdapter: list of allowed destination root paths (absolute or
    # tilde-expandable). Empty = LocalFileAdapter registered with no roots
    # (rejects every delivery with "no allowed_roots configured").
    local_file_allowed_roots: list[str] = Field(default_factory=list)
    # GitHubAdapter: env var name from which the token is read at delivery time.
    github_token_env: str = "GITHUB_TOKEN"
    # Default approval requirement — used when a request does not specify
    # requires_approval explicitly via the dataclass default of False.
    default_requires_approval: bool = False


class ConsultationDispatchConfig(BaseModel):
    """AD-594c v1: Parallel execution dispatch.

    Default-True is intentional — dispatcher construction is read-only on boot
    (no IO; only resolves runtime.work_item_store + runtime.consultation_workspaces
    references). Side effects only fire when an agent calls
    ``runtime.consultation_dispatcher.dispatch(...)``. Same precedent as
    ``ConsultationWorkspaceConfig`` / ``ConsultationDeliveryConfig``.
    """
    enabled: bool = True
    # Default work_type used for WorkItems created by the dispatcher when a
    # plan spec does not specify one. "duty" is registered in the WorkTypeRegistry.
    default_work_type: str = "duty"
    # Tags applied to every dispatched WorkItem in addition to the workspace_id
    # tag — used by get_progress to scope list_work_items queries.
    default_tags: list[str] = Field(default_factory=lambda: ["consultation"])
    # Blocker escalation: emit PARALLEL_DISPATCH_BLOCKED when a spec's depends_on
    # set has been unmet for at least this many seconds since dispatch.
    blocker_threshold_seconds: float = 600.0
    # Progress event emission cadence (caller-driven; no internal timer in v1).
    # When True, get_progress() emits PARALLEL_DISPATCH_PROGRESS on each call.
    progress_subscription_enabled: bool = True


class CommunicationsConfig(BaseModel):
===END REPLACE===
```

Now wire `consultation_dispatch` onto `SystemConfig` immediately after `consultation_delivery` (line ~2469).

```python
===MODIFY: src/probos/config.py===
===SEARCH===
    consultation_workspaces: ConsultationWorkspaceConfig = Field(
        default_factory=ConsultationWorkspaceConfig
    )  # AD-594a
    consultation_delivery: ConsultationDeliveryConfig = Field(
        default_factory=ConsultationDeliveryConfig
    )  # AD-594d
    process_chain_registry: ProcessChainRegistryConfig = Field(
        default_factory=ProcessChainRegistryConfig
    )  # AD-647b
===REPLACE===
    consultation_workspaces: ConsultationWorkspaceConfig = Field(
        default_factory=ConsultationWorkspaceConfig
    )  # AD-594a
    consultation_delivery: ConsultationDeliveryConfig = Field(
        default_factory=ConsultationDeliveryConfig
    )  # AD-594d
    consultation_dispatch: ConsultationDispatchConfig = Field(
        default_factory=ConsultationDispatchConfig
    )  # AD-594c
    process_chain_registry: ProcessChainRegistryConfig = Field(
        default_factory=ProcessChainRegistryConfig
    )  # AD-647b
===END REPLACE===
```

---

## Section 2 — Dispatch module

### File: `src/probos/consultation/dispatch.py` (NEW)

Full file content:

```python
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
from typing import Any, Iterable, Protocol, TYPE_CHECKING

from probos.events import EventType

if TYPE_CHECKING:
    from probos.consultation.workspace import (
        ConsultationWorkspace,
        WorkspaceLifecycleState,
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
            raise ValueError(f"AD-594c: plan_v{plan_version}.md unreadable in workspace {workspace.id}")
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
        wid_to_spec = {v: k for k, v in spec_to_wid.items()}
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
```

---

## Section 3 — Public package surface

### File: `src/probos/consultation/__init__.py`

Append the new dispatch exports next to the existing AD-594d delivery imports.

```python
===MODIFY: src/probos/consultation/__init__.py===
===SEARCH===
from probos.consultation.delivery import (
    AdapterResult,
    DeliveryAdapter,
    DeliveryArtifact,
    DeliveryPipeline,
    DeliveryReceipt,
    DeliveryRequest,
    FormatTransformer,
    GitHubAdapter,
    JSONToMarkdownTransformer,
    LocalFileAdapter,
    MarkdownToHTMLTransformer,
    PassthroughTransformer,
    build_format_transformer,
)

__all__ = [
    "AdapterResult",
    "ArtifactType",
    "ConsultationWorkspace",
    "ConsultationWorkspaceSummary",
    "DeliveryAdapter",
    "DeliveryArtifact",
    "DeliveryPipeline",
    "DeliveryReceipt",
    "DeliveryRequest",
    "FormatTransformer",
    "GitHubAdapter",
    "InputProcessor",
    "JSONToMarkdownTransformer",
    "LocalFileAdapter",
    "MarkdownToHTMLTransformer",
    "PassthroughTextProcessor",
    "PassthroughTransformer",
    "TEMPLATES",
    "WorkspaceLifecycleState",
    "WorkspaceRef",
    "WorkspaceRegistry",
    "build_format_transformer",
    "build_input_processor",
    "parse_workspace_refs",
    "render_advisory_report",
    "render_decision_record",
    "render_plan_document",
    "render_supporting_data",
    "render_work_item_spec",
    "render_workspace_refs_md",
]
===REPLACE===
from probos.consultation.delivery import (
    AdapterResult,
    DeliveryAdapter,
    DeliveryArtifact,
    DeliveryPipeline,
    DeliveryReceipt,
    DeliveryRequest,
    FormatTransformer,
    GitHubAdapter,
    JSONToMarkdownTransformer,
    LocalFileAdapter,
    MarkdownToHTMLTransformer,
    PassthroughTransformer,
    build_format_transformer,
)
from probos.consultation.dispatch import (
    BlockerReport,
    ConflictDetector,
    ConflictPair,
    DispatchReceipt,
    MarkdownPlanDecomposer,
    ParallelDispatcher,
    PlanDecomposer,
    ProgressSnapshot,
    WorkItemSpec,
)

__all__ = [
    "AdapterResult",
    "ArtifactType",
    "BlockerReport",
    "ConflictDetector",
    "ConflictPair",
    "ConsultationWorkspace",
    "ConsultationWorkspaceSummary",
    "DeliveryAdapter",
    "DeliveryArtifact",
    "DeliveryPipeline",
    "DeliveryReceipt",
    "DeliveryRequest",
    "DispatchReceipt",
    "FormatTransformer",
    "GitHubAdapter",
    "InputProcessor",
    "JSONToMarkdownTransformer",
    "LocalFileAdapter",
    "MarkdownPlanDecomposer",
    "MarkdownToHTMLTransformer",
    "ParallelDispatcher",
    "PassthroughTextProcessor",
    "PassthroughTransformer",
    "PlanDecomposer",
    "ProgressSnapshot",
    "TEMPLATES",
    "WorkItemSpec",
    "WorkspaceLifecycleState",
    "WorkspaceRef",
    "WorkspaceRegistry",
    "build_format_transformer",
    "build_input_processor",
    "parse_workspace_refs",
    "render_advisory_report",
    "render_decision_record",
    "render_plan_document",
    "render_supporting_data",
    "render_work_item_spec",
    "render_workspace_refs_md",
]
===END REPLACE===
```

Update the module docstring's old "AD-594c is NOT in v1 scope" line to reflect that AD-594c now ships:

```python
===MODIFY: src/probos/consultation/__init__.py===
===SEARCH===
"""AD-594a v1: Consultation workspace primitives.

Session-scoped shared workspace in Ship's Records for multi-agent advisory
consultations. See ``ConsultationWorkspace`` and ``WorkspaceRegistry``.

This module is the substrate; the consultation primitive (AD-594b) and parallel
execution dispatch (AD-594c) are tracked under separate GH issues (#161, #162)
and are NOT in v1 scope.
"""
===REPLACE===
"""Consultation workspace primitives.

Session-scoped shared workspace in Ship's Records for multi-agent advisory
consultations.

* AD-594a (Wave 44): substrate — ``ConsultationWorkspace`` + ``WorkspaceRegistry``.
* AD-594d (Wave 79): delivery pipeline — ``DeliveryPipeline`` + adapters.
* AD-594c (Wave 80): parallel execution dispatch — ``ParallelDispatcher`` +
  ``MarkdownPlanDecomposer`` + ``ConflictDetector``.

The consultation primitive (AD-594b, GH #161) is tracked under a separate
issue and is NOT shipped here.
"""
===END REPLACE===
```

---

## Section 4 — Finalize wirer

### File: `src/probos/startup/finalize.py`

Add `_wire_consultation_dispatch` immediately after `_wire_consultation_delivery` (ends at line ~712).

```python
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
    runtime.consultation_delivery = pipeline  # public attribute (Wave 5 conv #1)
    logger.info(
        "AD-594d: DeliveryPipeline v1 initialized (adapters=%s, default_requires_approval=%s)",
        pipeline.list_adapters(), cfg.default_requires_approval,
    )
    return True


def _wire_workspace_ontology(*, runtime: Any, config: "SystemConfig") -> bool:
===REPLACE===
    runtime.consultation_delivery = pipeline  # public attribute (Wave 5 conv #1)
    logger.info(
        "AD-594d: DeliveryPipeline v1 initialized (adapters=%s, default_requires_approval=%s)",
        pipeline.list_adapters(), cfg.default_requires_approval,
    )
    return True


def _wire_consultation_dispatch(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-594c v1: Wire ParallelDispatcher.

    Requires ``runtime.consultation_workspaces`` (AD-594a) AND
    ``runtime.work_item_store`` (AD-496). Tier-2 log-and-degrade: missing
    either dependency -> no-op + INFO log.
    """
    cfg = getattr(config, "consultation_dispatch", None)
    if not cfg or not cfg.enabled:
        return False
    registry = getattr(runtime, "consultation_workspaces", None)
    if registry is None:
        logger.info(
            "AD-594c: consultation_workspaces unavailable; consultation_dispatch skipped"
        )
        return False
    work_item_store = getattr(runtime, "work_item_store", None)
    if work_item_store is None:
        logger.info(
            "AD-594c: work_item_store unavailable; consultation_dispatch skipped"
        )
        return False
    records_store = getattr(runtime, "records_store", None)
    if records_store is None:
        logger.info(
            "AD-594c: records_store unavailable; consultation_dispatch skipped"
        )
        return False

    from probos.consultation.dispatch import ParallelDispatcher

    emit_fn = getattr(runtime, "emit_event", None)
    runtime.consultation_dispatcher = ParallelDispatcher(  # public attr (Wave 5 conv #1)
        workspace_registry=registry,
        work_item_store=work_item_store,
        records_store=records_store,
        config=cfg,
        emit_event=emit_fn,
    )
    logger.info(
        "AD-594c: ParallelDispatcher v1 initialized (default_work_type=%s, blocker_threshold=%.1fs)",
        cfg.default_work_type, cfg.blocker_threshold_seconds,
    )
    return True


def _wire_workspace_ontology(*, runtime: Any, config: "SystemConfig") -> bool:
===END REPLACE===
```

Invoke from `finalize_startup` immediately after the `_wire_consultation_delivery` call (line ~1034).

```python
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
    if _wire_consultation_workspaces(runtime=runtime, config=config):
        wired.append("consultation_workspaces")

    if _wire_consultation_delivery(runtime=runtime, config=config):
        wired.append("consultation_delivery")
===REPLACE===
    if _wire_consultation_workspaces(runtime=runtime, config=config):
        wired.append("consultation_workspaces")

    if _wire_consultation_delivery(runtime=runtime, config=config):
        wired.append("consultation_delivery")

    if _wire_consultation_dispatch(runtime=runtime, config=config):
        wired.append("consultation_dispatch")
===END REPLACE===
```

---

## Section 5 — Tests

### File: `tests/test_ad594c_parallel_dispatch.py` (NEW)

Test plan (≥25 tests, every test independent, no shared mutable state):

**Module-level (5):**
1. `test_event_types_present_and_collision_free` — 3 EventType values exist with expected `.value` strings.
2. `test_consultation_dispatch_config_defaults` — Pydantic defaults exact (`enabled=True`, `default_work_type="duty"`, `default_tags=["consultation"]`, `blocker_threshold_seconds=600.0`, `progress_subscription_enabled=True`).
3. `test_workitem_spec_to_dict_roundtrip` — frozen dataclass + tuple-to-list projection.
4. `test_conflict_pair_to_dict` — frozen + projection.
5. `test_dispatch_receipt_to_dict_deep_copies` — receipt projection isolates internal lists.

**MarkdownPlanDecomposer (5):**
6. `test_decomposer_empty_text_returns_empty_list`.
7. `test_decomposer_single_task_with_all_keys` — heading + every recognized key, asserts spec fields exact.
8. `test_decomposer_id_fallback_to_slug_when_missing` — heading "Build Foo Bar" → spec_id `"build-foo-bar"`.
9. `test_decomposer_unknown_keys_routed_to_metadata`.
10. `test_decomposer_multiple_tasks_preserve_order` — 3 ATX-2 tasks; spec list order matches markdown order.

**ConflictDetector (3):**
11. `test_detector_no_resources_returns_empty`.
12. `test_detector_overlap_emits_pair_with_sorted_shared`.
13. `test_detector_three_specs_three_pairwise_overlaps` — A∩B, A∩C, B∩C → 3 pairs.

**Conflict serialization (2):**
14. `test_serialize_conflicts_injects_depends_on_in_original_order` — pair (b, a) with a-before-b → b gains dep on a.
15. `test_serialize_conflicts_no_duplicate_when_dep_already_exists`.

**Dispatcher core (8):** with `tmp_path`-backed `RecordsStore` + real `WorkspaceRegistry`, real `WorkItemStore` (`db_path=str(tmp_path/"wis.db")`):
16. `test_dispatch_unknown_workspace_raises_value_error`.
17. `test_dispatch_no_plan_files_raises_value_error` — workspace exists but `plan/` empty.
18. `test_dispatch_zero_specs_raises_value_error` — plan file exists but is just `# preamble`.
19. `test_dispatch_happy_path_creates_workitems_and_mirrors` — 3-spec plan, no conflicts; assert (a) 3 WorkItems via `list_work_items(tags=["workspace:<id>"])`, (b) 3 yaml files in `workitems/`, (c) workspace state `EXECUTING`, (d) `PARALLEL_DISPATCH_STARTED` emitted once with `work_item_count=3`.
20. `test_dispatch_translates_spec_depends_on_to_work_item_ids` — spec B `depends_on=[a]` → WorkItem B's `depends_on` contains WorkItem-A's id, not the spec_id.
21. `test_dispatch_with_conflict_serializes_via_synthetic_edge` — two specs share a resource; receipt has 1 conflict + 1 serialization edge; second WorkItem `depends_on` includes first WorkItem's id.
22. `test_dispatch_uses_explicit_plan_version_when_passed`.
23. `test_dispatch_explicit_plan_version_unknown_raises_value_error`.

**Progress (3):**
24. `test_get_progress_returns_zero_for_unknown_workspace` — listing returns empty.
25. `test_get_progress_aggregates_by_status` — dispatch 3 items, mark one `update_work_item(status="completed")`, mark one `status="in_progress"`; snapshot shows `completed=1`, `in_progress=1`, `open=1`, `total=3`, `by_status` matches.
26. `test_get_progress_emits_event_when_subscription_enabled` — config `progress_subscription_enabled=True` (default) → emit fires; subscription_disabled config skips emit.

**Completion (3):**
27. `test_check_completion_returns_false_when_some_items_open`.
28. `test_check_completion_transitions_to_completed_and_journals_when_all_terminal` — mark all dispatched WorkItems `completed`; `check_completion()` returns True; `workspace.lifecycle_state == COMPLETED`; journal contains "dispatch completed".
29. `test_check_completion_idempotent` — second call after COMPLETED returns False.

**Blockers (3):**
30. `test_detect_blockers_below_threshold_returns_empty` — `now` < `started_at + threshold` → empty.
31. `test_detect_blockers_emits_blocked_event_with_dedup` — past threshold + B has unmet dep on A; first call emits `PARALLEL_DISPATCH_BLOCKED` once; second call same state does NOT re-emit (dedup ring).
32. `test_detect_blockers_clears_when_dependency_completes` — mark A `completed`; B no longer reported as blocked.

**Wirer (4):**
33. `test_wirer_constructs_dispatcher_when_dependencies_present` — real `SystemConfig` + SimpleNamespace runtime with `consultation_workspaces`, `work_item_store`, AND `records_store` set → `runtime.consultation_dispatcher` populated.
34. `test_wirer_skips_when_disabled_config` — `consultation_dispatch.enabled=False` → no attribute set.
35. `test_wirer_skips_when_work_item_store_missing` — runtime has registry + records_store but no `work_item_store` → no attribute set + INFO logged.
35b. `test_wirer_skips_when_records_store_missing` — runtime has registry + work_item_store but no `records_store` → no attribute set + INFO logged.

**Revoke (1):**
36. `test_revoke_cancels_non_terminal_work_items_only` — dispatch 3 items, mark one `completed`; revoke returns 2; cancelled items have `status="cancelled"` via `update_work_item`.

Total: **37 tests** (over the +25 floor by 12 — boundary coverage on the conflict-serialization, blocker-dedup, and wirer paths).

Test fixtures use:
- `pytest.fixture` async `_records_store(tmp_path)` returning a real `RecordsStore` instance (precedent: `tests/test_ad594d_delivery_pipeline.py`).
- `pytest.fixture` async `_workspace_registry(records_store)` building a real `WorkspaceRegistry`.
- `pytest.fixture` async `_work_item_store(tmp_path)` constructing real `WorkItemStore(db_path=str(tmp_path/"wis.db"))`, calling `start()`, yielding store, then awaiting `stop()` in teardown.
- A `_make_plan(workspace, *, version=1, body)` helper that calls `workspace.add_plan_iteration(body)` and returns the version.

NO `MagicMock` for `WorkItemStore` or `WorkspaceRegistry` — use the real classes (matches AD-594d test suite pattern). `MagicMock` is acceptable only for the runtime SimpleNamespace in wirer tests.

---

## What This Does NOT Change

- **No new Intent.** Dispatcher is a service surface called via `runtime.consultation_dispatcher.<method>()`; no `IntentDescriptor` registration.
- **No HXI surface.** No `routers/*.py` modification, no new endpoint, no `ui/src/` modification. AD-594c-i covers HXI when consumer signal arrives.
- **No AD-594b smuggling.** No `consult(question, context)` method on `CognitiveAgent`. Plan content sourcing is upstream of dispatch.
- **No AD-581 Hybrid Dispatch wiring.** `assigned_to=spec.agent` writes a string; HebbianRouter / ASA dispatcher hand-off is AD-581's surface.
- **No AD-594d delivery auto-trigger.** `check_completion()` does NOT call `runtime.consultation_delivery.deliver(...)`.
- **No LLM call.** v1 decomposer is structured-markdown only; LLM-driven decomposers plug in behind `PlanDecomposer` Protocol seam.
- **No `WorkItemStore` schema migration.** All metadata travels in the existing `metadata` JSON column and `tags` JSON column.
- **No `WorkspaceLifecycleState` enum change.** Existing `APPROVED → EXECUTING → COMPLETED` chain is sufficient (AD-594d already extended `COMPLETED` outflow).
- **No `_ALLOWED_TRANSITIONS` change.**

## Tracking Updates (Builder responsibility post-build)

- `PROGRESS.md`: Wave 80 paragraph at top of "Recent Builder Closures".
- `docs/development/roadmap.md` line 4841: status flip from `*(planned, OSS, depends: AD-594a, AD-594b, AD-496–498 WorkItemStore)*` to `*(complete — Wave 80, OSS; LLM-driven semantic decomposition deferred behind PlanDecomposer Protocol seam pending consumer)*`. Preserve descriptive prose.
- `DECISIONS.md`: append `### AD-594c v1: Parallel Execution Dispatch (2026-05-06)` entry above AD-594d's entry.
- `prompts/wave-plan.yaml` id `"80"` flipped to `status: done`.

## Acceptance Criteria

1. `git status` shows exactly the 10 files listed in WAVE-80-DISPATCH.md step 2.
2. `pytest tests/ -q -n 4 --dist=loadfile` ≥ **11553 collected**, all green.
3. `pytest tests/test_ad594c_parallel_dispatch.py -v -n 0` ≥ 25 tests, all green.
4. `pytest tests/test_ad594a_consultation_workspace.py tests/test_ad594d_delivery_pipeline.py tests/test_workforce.py -v -n 0` all green.
5. PROGRESS.md / roadmap.md / DECISIONS.md updates landed.
6. wave-plan.yaml id `"80"` flipped.
7. GH #162 closed with verify-first evidence + commit hash + scope checklist.
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.** — specifically: SOLID-S (decomposer parses, detector flags, dispatcher orchestrates); SOLID-D (constructor injection for `workspace_registry`, `work_item_store`, `records_store`, `config`, `decomposer`, `conflict_detector`, `emit_event`, `clock` — zero private-attribute reach into the registry); Liskov (`PlanDecomposer` Protocol; future LLM-driven impls honor the same return contract); three-tier exception handling (tier-2 log-and-degrade for `add_work_item`/`update_work_item`/`create_work_item`/journal/`transition_to`/emit failures; tier-3 propagate via `ValueError` for unknown workspace / missing plan / unknown plan_version / zero specs); full type annotations on the public surface; no fire-and-forget `create_task`; structured logging with `"AD-594c: <what> on workspace=<id>"` format; no commercial language; no emoji.

## Verified Against Codebase (2026-05-06, HEAD `3bcd608`)

```
src/probos/events.py:305          # CONSULTATION_FAILED — anchor for SEARCH in Section 0
grep "PARALLEL_DISPATCH_" src/    # 0 hits — collision-free

src/probos/config.py:2086         # class ConsultationDeliveryConfig — anchor for ConsultationDispatchConfig insertion
src/probos/config.py:2466-2470    # consultation_workspaces / consultation_delivery field block — anchor for SystemConfig wiring

src/probos/consultation/__init__.py:1-90      # current docstring + AD-594d delivery imports — SEARCH/REPLACE anchors
src/probos/consultation/workspace.py:43-58    # WorkspaceLifecycleState IntEnum
src/probos/consultation/workspace.py:55-63    # _ALLOWED_TRANSITIONS (APPROVED→EXECUTING→COMPLETED chain confirmed)
src/probos/consultation/workspace.py:205-219  # ConsultationWorkspace.add_work_item(spec, *, agent_id) signature confirmed
src/probos/consultation/workspace.py:243-258  # transition_to(state, *, agent_id) signature confirmed
src/probos/consultation/workspace.py:262-275  # append_journal(message, *, agent_id) signature confirmed

src/probos/workforce.py:559-585   # WorkItem dataclass — depends_on/metadata/parent_id/tags/work_type/status/priority/assigned_to/created_by all present
src/probos/workforce.py:1004      # async create_work_item(**kwargs) -> WorkItem
src/probos/workforce.py:1066      # async list_work_items(status, assigned_to, work_type, parent_id, priority, tags, limit, offset)
src/probos/workforce.py:1108      # async update_work_item(work_item_id, **updates)

src/probos/startup/finalize.py:631   # _wire_consultation_workspaces — sibling pattern
src/probos/startup/finalize.py:663   # _wire_consultation_delivery — directly preceding the new wirer
src/probos/startup/finalize.py:1031  # _wire_consultation_workspaces invocation site
src/probos/startup/finalize.py:1034  # _wire_consultation_delivery invocation site — anchor for new invocation

src/probos/runtime.py:213            # ProbOSRuntime.work_item_store: WorkItemStore | None
src/probos/runtime.py:1595           # adoption: self.work_item_store = comm.work_item_store

# AD-594b decoupling check:
grep -rn "def consult\b" src/probos/cognitive/         # 0 hits → AD-594b unshipped, AD-594c does not import it.

# Sibling test scaffolding:
tests/test_ad594d_delivery_pipeline.py    # real RecordsStore + real WorkspaceRegistry fixture pattern
tests/test_workforce.py:740               # WorkItemStore(db_path=str(tmp_path/"test.db")) construction precedent
```

Every concrete claim in this prompt body maps to a grep hit above.
