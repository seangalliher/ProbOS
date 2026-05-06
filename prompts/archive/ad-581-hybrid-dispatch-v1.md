# AD-581 v1 — Hybrid Dispatch (DepartmentDispatcher + Order Protocol + Confidence Threshold)

**Closes:** GH issue #113
**HEAD:** `7dee646`
**Baseline:** 11565 → target ≥ 11595 (Δ ≥ +30)
**OSS only.** No HXI surface. No router. No new Intent. No LLM call. No commercial content.
**Sub-ADs in scope:** AD-581a (DepartmentDispatcher), AD-581b (Agent Order Protocol), AD-581d (Routing Confidence Threshold).
**Sub-ADs out of scope (commercial):** AD-581c (ASA Bridge), AD-581e (Project Team Dispatch).

## Problem

ProbOS orchestrates work via three primitives that each ship in isolation but do not yet talk to each other:

- AD-654c `Dispatcher` resolves `AgentTarget` to agent_ids (agent_id / capability / department_id / broadcast). Pure activation surface — no policy.
- AD-440 `OrderManager` issues typed orders along the chain of command with `PENDING`/`ACKNOWLEDGED`/`EXPIRED` states. No decline/refuse semantics — agents either ack or wait for TTL.
- AD-594c `ParallelDispatcher` (Wave 80) writes `WorkItem` rows with `assigned_to=spec.agent or None`. `WorkItemStore.create_work_item()` emits `WORK_ITEM_CREATED` only — no `WORK_ITEM_ASSIGNED`, no `TaskEvent`, no agent notification.

The **routing decision** ("for this WorkItem/intent, should we direct-assign or broadcast — and to whom?") has no implementation. The **order pushback** ("agent receives an order that conflicts with Standing Orders or current capacity") has no implementation. The **WorkItem activation gap** ("a 594c-produced WorkItem reaches no agent") has no implementation.

GH #113 lists five sub-ADs. Two are commercial (581c, 581e) and live in the private commercial repo. Three are OSS (581a, 581b, 581d) and ship in this wave.

## Solution

Three new modules + two existing-module extensions + finalize wirer + Pydantic config.

1. **`src/probos/mesh/department_dispatcher.py`** — pure decision layer. `DepartmentDispatcher.route(*, intent, candidates, work_item=None) -> RoutingDecision`. `RoutingDecision(mode: RoutingMode, agent_id: str | None, confidence: float, reason: str)`. Uses `HebbianRouter` + `VesselOntologyService` + `BilletRegistry` to pick `DIRECT(agent_id, conf)` or `BROADCAST`. Stateless except for a `(intent_type, agent_id) → SuccessRateRing` map for AD-581d. No I/O, no event emission.

2. **`src/probos/mesh/work_item_router.py`** — bridge between `WORK_ITEM_CREATED` and AD-654c `Dispatcher`. Subscribes via `runtime.add_event_listener(fn, event_types=["work_item_created"])` (`runtime.py:694`); the listener fan-out at `runtime.py:816-822` invokes async callables via `asyncio.create_task(fn(event))`. The callback receives the full event envelope `{"type", "data", "timestamp"}` and extracts `event["data"]["work_item"]`. For dispatchable items, calls `DepartmentDispatcher.route(...)`, builds a `TaskEvent` via `task_event_for_agent()` or `task_event_broadcast()`, and forwards to `runtime.dispatcher.dispatch(event)`. Honors non-None `WorkItem.assigned_to` as a forced-direct hint (skip routing decision; direct-dispatch). Tier-2 log-and-degrade everywhere.

3. **`src/probos/cognitive/orders.py`** extension — adds `OrderState.DECLINED`, `OrderState.REFUSED`, `OrderManager.decline()`, `OrderManager.refuse()`, `StandingOrderPredicate` Protocol, `reassignment_callback` hook. Two new `EventType` values (`ORDER_DECLINED`, `ORDER_REFUSED`).

4. **`src/probos/events.py`** — +2 order events, +2 routing events.

5. **`src/probos/config.py`** — `HybridDispatchConfig` Pydantic model + field on `SystemConfig`.

6. **`src/probos/startup/finalize.py`** — `_wire_hybrid_dispatch(*, runtime, config) -> bool`. Wires `runtime.department_dispatcher` and `runtime.work_item_router` after `_wire_consultation_dispatch`.

7. **`tests/test_ad581_hybrid_dispatch.py`** — 30 tests.

---

## Section 0 — EventTypes

### File: `src/probos/events.py`

Add 2 order-state events near the existing AD-440 entries (line 173). Add 2 routing events near the AD-594c parallel dispatch block (line 310).

```text
===MODIFY: src/probos/events.py===
===SEARCH===
    ORDER_ISSUED = "order_issued"  # AD-440
    ORDER_REJECTED = "order_rejected"  # AD-440
    ORDER_ACKNOWLEDGED = "order_acknowledged"  # AD-440
===REPLACE===
    ORDER_ISSUED = "order_issued"  # AD-440
    ORDER_REJECTED = "order_rejected"  # AD-440
    ORDER_ACKNOWLEDGED = "order_acknowledged"  # AD-440
    ORDER_DECLINED = "order_declined"  # AD-581b
    ORDER_REFUSED = "order_refused"  # AD-581b
===END REPLACE===
```

```text
===MODIFY: src/probos/events.py===
===SEARCH===
    # Parallel execution dispatch (AD-594c)
    PARALLEL_DISPATCH_STARTED = "parallel_dispatch_started"
    PARALLEL_DISPATCH_PROGRESS = "parallel_dispatch_progress"
    PARALLEL_DISPATCH_BLOCKED = "parallel_dispatch_blocked"
===REPLACE===
    # Parallel execution dispatch (AD-594c)
    PARALLEL_DISPATCH_STARTED = "parallel_dispatch_started"
    PARALLEL_DISPATCH_PROGRESS = "parallel_dispatch_progress"
    PARALLEL_DISPATCH_BLOCKED = "parallel_dispatch_blocked"

    # Hybrid dispatch routing decisions (AD-581a)
    HYBRID_DISPATCH_DIRECT = "hybrid_dispatch_direct"
    HYBRID_DISPATCH_BROADCAST = "hybrid_dispatch_broadcast"
===END REPLACE===
```

Verification: `grep -n "ORDER_DECLINED\|ORDER_REFUSED\|HYBRID_DISPATCH_" src/probos/events.py` returns exactly 4 hits, all on enum lines.

---

## Section 1 — Pydantic config

### File: `src/probos/config.py`

Add `HybridDispatchConfig` immediately after `ConsultationDispatchConfig` (line ~2130). Add the field on `SystemConfig` adjacent to `consultation_dispatch`.

```text
===MODIFY: src/probos/config.py===
===SEARCH===
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
===REPLACE===
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


class HybridDispatchConfig(BaseModel):
    """AD-581 v1: Hybrid dispatch routing policy (581a + 581d).

    Default-True is intentional — DepartmentDispatcher construction is
    read-only on boot (no IO; only resolves runtime.hebbian_router +
    runtime.ontology references). The WorkItemRouter side-effect path
    activates only when a WORK_ITEM_CREATED event fires. Same precedent
    as ConsultationDispatchConfig / ConsultationDeliveryConfig.

    AD-581b order protocol additions are unconditional — declining or
    refusing an order is always available on OrderManager regardless of
    this config; the gate here governs the auto-routing layer only.
    """

    enabled: bool = True

    # AD-581d: Routing confidence thresholds.
    #
    # confidence_threshold — the minimum max-Hebbian-weight on a candidate
    # for the routing decision to be DIRECT. Below this → BROADCAST.
    confidence_threshold: float = 0.4
    # confidence_margin — the max candidate must beat the runner-up by at
    # least this much. Prevents flip-flop when two agents are tied.
    confidence_margin: float = 0.05
    # min_hebbian_weight — cold-start floor. If the max weight across
    # candidates is below this, the dispatcher returns BROADCAST regardless
    # of confidence_threshold. Mirrors "always broadcast until minimum
    # Hebbian weight established" from the AD-581d roadmap entry.
    min_hebbian_weight: float = 0.05

    # AD-581d: Per-(intent_type, agent_id) success-rate ring buffer.
    success_rate_window: int = 50
    min_samples_for_routing: int = 3

    # AD-581a: WorkItemRouter activation criteria. WORK_ITEM_CREATED events
    # are routed when the work item carries one of these tags OR has
    # metadata["dispatchable"] == True. Conservative default avoids
    # auto-routing every work item in the system.
    dispatchable_tags: list[str] = Field(default_factory=lambda: ["consultation"])

    @field_validator("confidence_threshold", "confidence_margin", "min_hebbian_weight")
    @classmethod
    def _weight_in_unit(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("weight must be in [0.0, 1.0]")
        return v

    @field_validator("success_rate_window")
    @classmethod
    def _window_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("success_rate_window must be >= 1")
        return v

    @field_validator("min_samples_for_routing")
    @classmethod
    def _min_samples_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("min_samples_for_routing must be >= 1")
        return v
===END REPLACE===
```

```text
===MODIFY: src/probos/config.py===
===SEARCH===
    consultation_dispatch: ConsultationDispatchConfig = Field(
        default_factory=ConsultationDispatchConfig
    )  # AD-594c
===REPLACE===
    consultation_dispatch: ConsultationDispatchConfig = Field(
        default_factory=ConsultationDispatchConfig
    )  # AD-594c
    hybrid_dispatch: HybridDispatchConfig = Field(
        default_factory=HybridDispatchConfig
    )  # AD-581 v1 (sub-ADs 581a/b/d)
===END REPLACE===
```

Verification: `grep -n "HybridDispatchConfig\|hybrid_dispatch" src/probos/config.py` returns exactly 4 hits (class def + 2 field def + 1 SystemConfig field).

---

## Section 2 — DepartmentDispatcher (AD-581a + AD-581d core)

### File: `src/probos/mesh/department_dispatcher.py` (NEW)

```python
"""AD-581a + AD-581d: Hybrid dispatch routing decision layer.

Pure decision module. Given a candidate pool and an intent (or an unassigned
WorkItem), decide whether to direct-assign to a single agent or to broadcast.
The decision is a function of:

* HebbianRouter weight from intent_type → agent_id
* Department membership (resolved via VesselOntologyService)
* Configurable confidence_threshold + margin (AD-581d)
* Cold-start floor min_hebbian_weight (AD-581d)
* Per-(intent, agent_id) success-rate ring buffer (AD-581d, accessor-only)

This module DOES NOT dispatch. WorkItemRouter is the side-effect surface;
DepartmentDispatcher returns a RoutingDecision and never emits events,
talks to the bus, or constructs TaskEvents.

Out of scope:
- ASA / BookableResource routing (AD-581c, commercial)
- Project-team cross-department CoC (AD-581e, commercial)
- LLM-driven semantic routing (no LLM call here; pure structural)
- Dream-cycle auto-tuning of confidence_threshold (consumer hook only)
"""
from __future__ import annotations

import collections
import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from probos.mesh.routing import REL_INTENT

if TYPE_CHECKING:
    from probos.config import HybridDispatchConfig
    from probos.mesh.routing import HebbianRouter
    from probos.ontology.service import VesselOntologyService

logger = logging.getLogger(__name__)


class RoutingMode(str, Enum):
    DIRECT = "direct"
    BROADCAST = "broadcast"


@dataclass(frozen=True)
class RoutingDecision:
    """Pure-data result. WorkItemRouter (or any caller) acts on it."""

    mode: RoutingMode
    agent_id: str | None       # set only when mode == DIRECT
    confidence: float          # max Hebbian weight observed across candidates
    runner_up_weight: float    # second-highest weight; 0.0 if <2 candidates
    reason: str                # human-readable; one of: "direct_high_confidence",
                               # "broadcast_below_threshold", "broadcast_below_floor",
                               # "broadcast_no_margin", "broadcast_no_candidates",
                               # "direct_assigned_hint", "broadcast_no_router"
    department_id: str | None  # resolved department, or None when unresolvable

    def is_direct(self) -> bool:
        return self.mode == RoutingMode.DIRECT

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "agent_id": self.agent_id,
            "confidence": float(self.confidence),
            "runner_up_weight": float(self.runner_up_weight),
            "reason": self.reason,
            "department_id": self.department_id,
        }


class DepartmentDispatcher:
    """Hebbian + ontology routing decision layer.

    Construct via the ``_wire_hybrid_dispatch`` finalize wirer; tests
    construct directly with stub dependencies.
    """

    def __init__(
        self,
        *,
        hebbian_router: "HebbianRouter | None",
        ontology: "VesselOntologyService | None",
        config: "HybridDispatchConfig",
    ) -> None:
        self._hebbian = hebbian_router
        self._ontology = ontology
        self._config = config
        # Per-(intent_type, agent_id) success-rate ring; bounded buffer.
        self._success_rings: dict[
            tuple[str, str], collections.deque[bool]
        ] = collections.defaultdict(
            lambda: collections.deque(maxlen=int(config.success_rate_window))
        )

    # ------------------------------------------------------------------
    # AD-581a: routing decision
    # ------------------------------------------------------------------
    def route(
        self,
        *,
        intent: str,
        candidates: list[str],
        work_item: Any | None = None,
    ) -> RoutingDecision:
        """Decide DIRECT vs BROADCAST.

        ``work_item`` is the optional WorkItem whose ``assigned_to`` may force
        a direct-assign hint. ``candidates`` is the pool of agent_ids the
        caller has already filtered (e.g. by capability or department).

        Returns ``RoutingDecision``. Pure — no side effects.
        """
        # Forced direct-assign hint: WorkItem.assigned_to honored as-is.
        if work_item is not None:
            assigned_hint = getattr(work_item, "assigned_to", None)
            if assigned_hint:
                department_id = self._department_for_agent(assigned_hint)
                return RoutingDecision(
                    mode=RoutingMode.DIRECT,
                    agent_id=assigned_hint,
                    confidence=1.0,
                    runner_up_weight=0.0,
                    reason="direct_assigned_hint",
                    department_id=department_id,
                )

        if not candidates:
            return RoutingDecision(
                mode=RoutingMode.BROADCAST,
                agent_id=None,
                confidence=0.0,
                runner_up_weight=0.0,
                reason="broadcast_no_candidates",
                department_id=None,
            )

        if self._hebbian is None:
            return RoutingDecision(
                mode=RoutingMode.BROADCAST,
                agent_id=None,
                confidence=0.0,
                runner_up_weight=0.0,
                reason="broadcast_no_router",
                department_id=None,
            )

        # Score every candidate by Hebbian weight from intent_type.
        scored: list[tuple[str, float]] = []
        for agent_id in candidates:
            try:
                w = self._hebbian.get_weight(intent, agent_id, REL_INTENT)
            except Exception:
                logger.debug(
                    "AD-581a: get_weight failed for (%s, %s); treating as 0.0",
                    intent, agent_id, exc_info=True,
                )
                w = 0.0
            scored.append((agent_id, float(w)))

        scored.sort(key=lambda x: x[1], reverse=True)
        top_id, top_w = scored[0]
        runner_up_w = scored[1][1] if len(scored) > 1 else 0.0
        department_id = self._department_for_agent(top_id)

        # Cold-start floor: below this, always broadcast.
        if top_w < self._config.min_hebbian_weight:
            return RoutingDecision(
                mode=RoutingMode.BROADCAST,
                agent_id=None,
                confidence=top_w,
                runner_up_weight=runner_up_w,
                reason="broadcast_below_floor",
                department_id=department_id,
            )

        # Confidence threshold.
        if top_w < self._config.confidence_threshold:
            return RoutingDecision(
                mode=RoutingMode.BROADCAST,
                agent_id=None,
                confidence=top_w,
                runner_up_weight=runner_up_w,
                reason="broadcast_below_threshold",
                department_id=department_id,
            )

        # Margin over runner-up (anti-flip-flop).
        if (top_w - runner_up_w) < self._config.confidence_margin:
            return RoutingDecision(
                mode=RoutingMode.BROADCAST,
                agent_id=None,
                confidence=top_w,
                runner_up_weight=runner_up_w,
                reason="broadcast_no_margin",
                department_id=department_id,
            )

        return RoutingDecision(
            mode=RoutingMode.DIRECT,
            agent_id=top_id,
            confidence=top_w,
            runner_up_weight=runner_up_w,
            reason="direct_high_confidence",
            department_id=department_id,
        )

    # ------------------------------------------------------------------
    # AD-581d: per-(intent, agent_id) success-rate accessor surface
    # ------------------------------------------------------------------
    def record_outcome(
        self, *, intent: str, agent_id: str, success: bool,
    ) -> None:
        """Append an outcome to the rolling window for (intent, agent_id).

        Bounded by config.success_rate_window. No event emission, no side
        effects beyond the in-memory ring. Dream-cycle hook reads via
        ``get_success_rate``.
        """
        self._success_rings[(intent, agent_id)].append(bool(success))

    def get_success_rate(
        self, *, intent: str, agent_id: str,
    ) -> tuple[float, int]:
        """Return ``(success_rate, sample_count)``.

        ``success_rate`` is 0.0 when sample_count < min_samples_for_routing
        (configured floor). This lets the dream-cycle subscriber distinguish
        "low confidence" from "no data" without a separate flag.
        """
        ring = self._success_rings.get((intent, agent_id))
        if ring is None:
            return 0.0, 0
        n = len(ring)
        if n < self._config.min_samples_for_routing:
            return 0.0, n
        successes = sum(1 for s in ring if s)
        return successes / n, n

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _department_for_agent(self, agent_id: str) -> str | None:
        """Resolve agent_id → department_id via ontology.

        agent_id often equals agent_type in this codebase (registry IDs are
        usually the agent_type string). When ontology is unavailable, returns
        None gracefully — the resolution is informational, not gating.
        """
        if self._ontology is None:
            return None
        try:
            return self._ontology.get_agent_department(agent_id)
        except Exception:
            logger.debug(
                "AD-581a: get_agent_department failed for %s",
                agent_id, exc_info=True,
            )
            return None
```

`REL_INTENT` is imported from `probos.mesh.routing`. **Verification step Builder must run:** `grep -n "^REL_INTENT = \|REL_INTENT =" src/probos/mesh/routing.py`. If the constant is not exported under that exact name, fall back to passing `rel_type=None` (the public `get_weight` signature accepts `None` and returns the compat-aggregated weight, per `routing.py:251-260`). Builder choice: import `REL_INTENT` if present; else replace `REL_INTENT` with `None` at the single call site. Both produce equivalent behavior at HEAD because Hebbian writes use `record_interaction(..., rel_type=REL_INTENT)` AND maintain the compat dict — `get_weight(..., rel_type=None)` reads the compat dict directly.

---

## Section 3 — WorkItemRouter (AD-581a wiring side-effect)

### File: `src/probos/mesh/work_item_router.py` (NEW)

```python
"""AD-581a v1: Bridge WORK_ITEM_CREATED → AD-654c Dispatcher.

Subscribes to WORK_ITEM_CREATED events. For dispatchable work items, asks
DepartmentDispatcher whether to DIRECT-assign or BROADCAST, then constructs
the appropriate AD-654c TaskEvent and forwards to runtime.dispatcher.

Tier-2 log-and-degrade everywhere — routing is best-effort. A failure here
must NEVER raise into the WorkItemStore emitter or the agent bringing up
the WorkItem.

Out of scope:
- Auto-routing every WorkItem regardless of tags (gated on
  dispatchable_tags + metadata["dispatchable"])
- TaskEvent on WORK_ITEM_UPDATED (only WORK_ITEM_CREATED)
- Cross-process / federation routing
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.activation.dispatcher import Dispatcher
    from probos.config import HybridDispatchConfig
    from probos.mesh.department_dispatcher import DepartmentDispatcher

logger = logging.getLogger(__name__)


class WorkItemRouter:
    """Routes WORK_ITEM_CREATED events to agents via AD-654c Dispatcher."""

    def __init__(
        self,
        *,
        dispatcher: "Dispatcher",
        department_dispatcher: "DepartmentDispatcher",
        registry: Any,
        config: "HybridDispatchConfig",
        emit_event: Any | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._dept_dispatcher = department_dispatcher
        self._registry = registry
        self._config = config
        self._emit = emit_event

    def is_dispatchable(self, work_item_dict: dict[str, Any]) -> bool:
        """True iff the work item carries a configured dispatchable tag OR
        has metadata["dispatchable"] == True. Conservative default."""
        tags = work_item_dict.get("tags") or []
        if any(t in self._config.dispatchable_tags for t in tags):
            return True
        meta = work_item_dict.get("metadata") or {}
        return bool(meta.get("dispatchable"))

    async def on_work_item_created(self, event: dict[str, Any]) -> None:
        """Handle the WORK_ITEM_CREATED event envelope.

        Envelope shape per ``runtime._emit_event``:
          ``{"type": "work_item_created", "data": {"work_item": item.to_dict()}, "timestamp": ...}``

        Best-effort: any exception is logged at warning and swallowed.
        """
        try:
            data = event.get("data") or {}
            wi = data.get("work_item") or {}
            if not self.is_dispatchable(wi):
                return

            # Build a synthetic intent string from work_type for Hebbian lookup.
            intent = f"work_item:{wi.get('work_type', '')}".strip(":")
            assigned = wi.get("assigned_to") or None
            tags = wi.get("tags") or []

            # Candidate pool: all crew agents from the registry. The
            # DepartmentDispatcher will weigh them; non-crew agents will
            # have weight 0.0 and lose the routing decision naturally.
            candidates = [
                getattr(a, "id", "")
                for a in self._registry.all()
                if getattr(a, "id", "")
            ]

            # Synthesize a minimal work-item shim DepartmentDispatcher can read.
            class _WIView:
                __slots__ = ("assigned_to",)

                def __init__(self, assigned_to: str | None) -> None:
                    self.assigned_to = assigned_to

            decision = self._dept_dispatcher.route(
                intent=intent,
                candidates=candidates,
                work_item=_WIView(assigned),
            )

            from probos.activation.task_event import (
                task_event_broadcast,
                task_event_for_agent,
            )
            from probos.types import Priority

            priority = self._priority_from_int(int(wi.get("priority", 3)))
            payload_out: dict[str, Any] = {
                "work_item_id": wi.get("id", ""),
                "title": wi.get("title", ""),
                "description": wi.get("description", ""),
                "work_type": wi.get("work_type", ""),
                "tags": tags,
                "metadata": wi.get("metadata") or {},
                "routing_reason": decision.reason,
                "routing_confidence": decision.confidence,
            }

            if decision.is_direct() and decision.agent_id:
                event = task_event_for_agent(
                    agent_id=decision.agent_id,
                    source_type="work_item_router",
                    source_id=wi.get("id", ""),
                    event_type="work_item_dispatched",
                    priority=priority,
                    payload=payload_out,
                )
                if self._emit is not None:
                    try:
                        self._emit(EventType.HYBRID_DISPATCH_DIRECT, {
                            "work_item_id": wi.get("id", ""),
                            "agent_id": decision.agent_id,
                            "confidence": decision.confidence,
                            "reason": decision.reason,
                            "department_id": decision.department_id,
                        })
                    except Exception:
                        logger.warning(
                            "AD-581a: HYBRID_DISPATCH_DIRECT emit failed",
                            exc_info=True,
                        )
            else:
                event = task_event_broadcast(
                    source_type="work_item_router",
                    source_id=wi.get("id", ""),
                    event_type="work_item_dispatched",
                    priority=priority,
                    payload=payload_out,
                )
                if self._emit is not None:
                    try:
                        self._emit(EventType.HYBRID_DISPATCH_BROADCAST, {
                            "work_item_id": wi.get("id", ""),
                            "confidence": decision.confidence,
                            "reason": decision.reason,
                            "department_id": decision.department_id,
                        })
                    except Exception:
                        logger.warning(
                            "AD-581a: HYBRID_DISPATCH_BROADCAST emit failed",
                            exc_info=True,
                        )

            await self._dispatcher.dispatch(event)
        except Exception:
            logger.warning(
                "AD-581a: WorkItemRouter.on_work_item_created failed; "
                "work_item dispatch skipped",
                exc_info=True,
            )

    @staticmethod
    def _priority_from_int(p: int) -> Any:
        """Map int priority (1=highest, 5=lowest) → Priority enum.

        WorkItem.priority is a 1..5 int (workforce.py:559). Priority enum
        is symbolic with three tiers (CRITICAL/NORMAL/LOW per types.py:76).
        Map conservatively; unknown values fall back to NORMAL.
        """
        from probos.types import Priority
        if p <= 1:
            return Priority.CRITICAL
        if p >= 5:
            return Priority.LOW
        return Priority.NORMAL
```

---

## Section 4 — Order Protocol decline / refuse (AD-581b)

### File: `src/probos/cognitive/orders.py`

Three changes:

1. Add `DECLINED` and `REFUSED` to `OrderState`.
2. Extend the `Order` dataclass with optional decline/refuse fields.
3. Add `OrderManager.decline()` and `OrderManager.refuse()` methods.
4. Add `StandingOrderPredicate` Protocol.
5. Wire `reassignment_callback` into `decline()` (tier-2 log-and-degrade).

```text
===MODIFY: src/probos/cognitive/orders.py===
===SEARCH===
class OrderState(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    EXPIRED = "expired"


@dataclass(frozen=True)
class Order:
    """A typed delegation along the chain of command."""

    id: str
    from_agent_id: str
    from_post_id: str
    to_post_id: str
    directive: str
    issued_at: float
    expires_at: float
    state: OrderState = OrderState.PENDING
    acknowledged_by: str = ""
    acknowledged_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
===REPLACE===
class OrderState(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    EXPIRED = "expired"
    DECLINED = "declined"   # AD-581b: agent pushback (capacity, scheduling, etc.)
    REFUSED = "refused"     # AD-581b: Standing-Order violation


class StandingOrderPredicate:
    """AD-581b: protocol for evaluating an order against Standing Orders.

    Returns ``(violates: bool, reason: str)``. v1 default predicate (wired
    by ``OrderManager`` constructor) returns ``(False, "")``. Wiring to
    ``cognitive/standing_orders.py`` Federation-tier directives is a
    follow-on AD; the seam ships here.
    """

    def __call__(
        self, *, order: "Order", by_agent_id: str,
    ) -> tuple[bool, str]:  # pragma: no cover - protocol surface
        ...


def _default_standing_order_predicate(
    *, order: "Order", by_agent_id: str,
) -> tuple[bool, str]:
    """v1 default — never reports a violation."""
    return False, ""


@dataclass(frozen=True)
class Order:
    """A typed delegation along the chain of command."""

    id: str
    from_agent_id: str
    from_post_id: str
    to_post_id: str
    directive: str
    issued_at: float
    expires_at: float
    state: OrderState = OrderState.PENDING
    acknowledged_by: str = ""
    acknowledged_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    declined_by: str = ""           # AD-581b
    declined_at: float = 0.0        # AD-581b
    decline_reason: str = ""        # AD-581b
    refused_by: str = ""            # AD-581b
    refused_at: float = 0.0         # AD-581b
    refuse_violation: str = ""      # AD-581b
===END REPLACE===
```

```text
===MODIFY: src/probos/cognitive/orders.py===
===SEARCH===
    DEFAULT_TTL_SECONDS = 3600.0

    def __init__(
        self,
        *,
        ontology: "VesselOntologyService",
        registry: "AgentRegistry",
        emit_event: Any | None = None,
        max_active_per_post: int = 8,
        default_ttl: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._ontology = ontology
        self._registry = registry
        self._emit_event = emit_event
        self._orders: dict[str, Order] = {}
        self._max_active_per_post = max_active_per_post
        self._default_ttl = default_ttl
===REPLACE===
    DEFAULT_TTL_SECONDS = 3600.0

    def __init__(
        self,
        *,
        ontology: "VesselOntologyService",
        registry: "AgentRegistry",
        emit_event: Any | None = None,
        max_active_per_post: int = 8,
        default_ttl: float = DEFAULT_TTL_SECONDS,
        standing_order_predicate: Any = None,  # AD-581b: optional callable
    ) -> None:
        self._ontology = ontology
        self._registry = registry
        self._emit_event = emit_event
        self._orders: dict[str, Order] = {}
        self._max_active_per_post = max_active_per_post
        self._default_ttl = default_ttl
        # AD-581b: Standing-Order predicate. Default = no-violation. Replace
        # with a directive-store-aware callable in a follow-on AD.
        self._so_predicate = standing_order_predicate or _default_standing_order_predicate
        # AD-581b: per-order reassignment callback registry. Keys by order_id.
        # Best-effort hook fired on decline; never raises.
        self._reassignment_callbacks: dict[str, Any] = {}
===END REPLACE===
```

```text
===MODIFY: src/probos/cognitive/orders.py===
===SEARCH===
    def acknowledge(self, order_id: str, by_agent_id: str) -> bool:
        """Subordinate acknowledges an order. Returns True if state changed."""
        order = self._orders.get(order_id)
        if order is None or order.state != OrderState.PENDING:
            return False
        agent_type = self._agent_type_for_id(by_agent_id)
        assignment = (
            self._ontology.get_assignment_for_agent(agent_type) if agent_type else None
        )
        if assignment is None or assignment.post_id != order.to_post_id:
            return False
        updated = dataclasses.replace(
            order,
            state=OrderState.ACKNOWLEDGED,
            acknowledged_by=by_agent_id,
            acknowledged_at=time.time(),
        )
        self._orders[order_id] = updated
        if self._emit_event:
            try:
                self._emit_event(
                    EventType.ORDER_ACKNOWLEDGED,
                    {"order_id": order_id, "by_agent_id": by_agent_id},
                )
            except Exception:
                logger.warning("AD-440: ORDER_ACKNOWLEDGED emit failed", exc_info=True)
        return True
===REPLACE===
    def acknowledge(self, order_id: str, by_agent_id: str) -> bool:
        """Subordinate acknowledges an order. Returns True if state changed."""
        order = self._orders.get(order_id)
        if order is None or order.state != OrderState.PENDING:
            return False
        agent_type = self._agent_type_for_id(by_agent_id)
        assignment = (
            self._ontology.get_assignment_for_agent(agent_type) if agent_type else None
        )
        if assignment is None or assignment.post_id != order.to_post_id:
            return False
        updated = dataclasses.replace(
            order,
            state=OrderState.ACKNOWLEDGED,
            acknowledged_by=by_agent_id,
            acknowledged_at=time.time(),
        )
        self._orders[order_id] = updated
        if self._emit_event:
            try:
                self._emit_event(
                    EventType.ORDER_ACKNOWLEDGED,
                    {"order_id": order_id, "by_agent_id": by_agent_id},
                )
            except Exception:
                logger.warning("AD-440: ORDER_ACKNOWLEDGED emit failed", exc_info=True)
        return True

    # ------------------------------------------------------------------
    # AD-581b: decline / refuse semantics
    # ------------------------------------------------------------------
    def register_reassignment_callback(
        self, order_id: str, callback: Any,
    ) -> None:
        """Register a best-effort reassignment hook for one order.

        Fired on ``decline()`` only (not on refuse — refuse means the order
        is wrong, not the agent). Receives ``(order, declined_by, reason)``
        as keyword arguments. Tier-2 log-and-degrade.
        """
        self._reassignment_callbacks[order_id] = callback

    def decline(
        self, order_id: str, by_agent_id: str, *, reason: str,
    ) -> bool:
        """Subordinate declines a pending order with a reason.

        Returns True iff the order existed, was pending, and the caller is
        the post holder. Triggers an optional reassignment callback (best
        effort). Emits ORDER_DECLINED.
        """
        order = self._orders.get(order_id)
        if order is None or order.state != OrderState.PENDING:
            return False
        if not self._caller_holds_target_post(order, by_agent_id):
            return False
        if not reason or not reason.strip():
            return False
        updated = dataclasses.replace(
            order,
            state=OrderState.DECLINED,
            declined_by=by_agent_id,
            declined_at=time.time(),
            decline_reason=reason.strip(),
        )
        self._orders[order_id] = updated
        if self._emit_event:
            try:
                self._emit_event(
                    EventType.ORDER_DECLINED,
                    {
                        "order_id": order_id,
                        "by_agent_id": by_agent_id,
                        "reason": reason.strip(),
                    },
                )
            except Exception:
                logger.warning("AD-581b: ORDER_DECLINED emit failed", exc_info=True)
        cb = self._reassignment_callbacks.pop(order_id, None)
        if cb is not None:
            try:
                cb(order=updated, declined_by=by_agent_id, reason=reason.strip())
            except Exception:
                logger.warning(
                    "AD-581b: reassignment_callback for order %s raised; ignored",
                    order_id, exc_info=True,
                )
        return True

    def refuse(
        self, order_id: str, by_agent_id: str, *, violation: str = "",
    ) -> bool:
        """Subordinate refuses a pending order on Standing-Order violation.

        Returns True iff the order existed, was pending, and the caller is
        the post holder. ``violation`` may be supplied directly by the caller
        or computed via the injected ``StandingOrderPredicate`` — when both
        are present the caller-supplied text wins; when neither, the order
        does NOT transition (False return).

        Emits ORDER_REFUSED.
        """
        order = self._orders.get(order_id)
        if order is None or order.state != OrderState.PENDING:
            return False
        if not self._caller_holds_target_post(order, by_agent_id):
            return False

        v = (violation or "").strip()
        if not v:
            try:
                violates, predicate_reason = self._so_predicate(
                    order=order, by_agent_id=by_agent_id,
                )
            except Exception:
                logger.warning(
                    "AD-581b: standing_order_predicate raised; treating as no-violation",
                    exc_info=True,
                )
                violates, predicate_reason = False, ""
            if not violates:
                return False
            v = (predicate_reason or "").strip() or "standing_orders_violation"

        updated = dataclasses.replace(
            order,
            state=OrderState.REFUSED,
            refused_by=by_agent_id,
            refused_at=time.time(),
            refuse_violation=v,
        )
        self._orders[order_id] = updated
        if self._emit_event:
            try:
                self._emit_event(
                    EventType.ORDER_REFUSED,
                    {
                        "order_id": order_id,
                        "by_agent_id": by_agent_id,
                        "violation": v,
                    },
                )
            except Exception:
                logger.warning("AD-581b: ORDER_REFUSED emit failed", exc_info=True)
        # No reassignment hook on refuse: the order itself is wrong.
        self._reassignment_callbacks.pop(order_id, None)
        return True

    def _caller_holds_target_post(
        self, order: Order, by_agent_id: str,
    ) -> bool:
        agent_type = self._agent_type_for_id(by_agent_id)
        if not agent_type:
            return False
        assignment = self._ontology.get_assignment_for_agent(agent_type)
        if assignment is None:
            return False
        return assignment.post_id == order.to_post_id
===END REPLACE===
```

---

## Section 5 — Finalize wirer + runtime attribute

### File: `src/probos/startup/finalize.py`

Insert `_wire_hybrid_dispatch` immediately after `_wire_consultation_dispatch` (line ~759). Invoke it from the **late phase** of `finalize()`, immediately after the AD-654d dispatcher-attach block (around line 2230, after `runtime.ward_room.attach_dispatcher(...)`). This ordering is critical — `runtime.dispatcher` (AD-654c) is created at line 2218; the early `_wire_consultation_dispatch` invocation at line ~1085 fires before AD-654c exists, so AD-581 cannot live there.

```text
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
def _wire_workspace_ontology(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-478 v1: Wire WorkspaceOntologyRegistry term frequency helper."""
===REPLACE===
def _wire_hybrid_dispatch(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-581 v1: Wire DepartmentDispatcher + WorkItemRouter.

    Requires ``runtime.hebbian_router``, ``runtime.ontology``,
    ``runtime.work_item_store``, AND ``runtime.dispatcher`` (AD-654c).
    Tier-2 log-and-degrade: missing any dependency -> no-op + INFO log.
    """
    cfg = getattr(config, "hybrid_dispatch", None)
    if not cfg or not cfg.enabled:
        return False
    hebbian = getattr(runtime, "hebbian_router", None)
    if hebbian is None:
        logger.info(
            "AD-581: hebbian_router unavailable; hybrid_dispatch skipped"
        )
        return False
    ontology = getattr(runtime, "ontology", None)
    if ontology is None:
        logger.info(
            "AD-581: ontology unavailable; hybrid_dispatch skipped"
        )
        return False
    dispatcher = getattr(runtime, "dispatcher", None)
    if dispatcher is None:
        logger.info(
            "AD-581: dispatcher (AD-654c) unavailable; hybrid_dispatch skipped"
        )
        return False
    registry = getattr(runtime, "registry", None)
    if registry is None:
        logger.info(
            "AD-581: registry unavailable; hybrid_dispatch skipped"
        )
        return False

    from probos.mesh.department_dispatcher import DepartmentDispatcher
    from probos.mesh.work_item_router import WorkItemRouter

    runtime.department_dispatcher = DepartmentDispatcher(  # public attr (Wave 5 conv #1)
        hebbian_router=hebbian,
        ontology=ontology,
        config=cfg,
    )
    emit_fn = getattr(runtime, "emit_event", None)
    runtime.work_item_router = WorkItemRouter(  # public attr (Wave 5 conv #1)
        dispatcher=dispatcher,
        department_dispatcher=runtime.department_dispatcher,
        registry=registry,
        config=cfg,
        emit_event=emit_fn,
    )
    logger.info(
        "AD-581 v1: HybridDispatch wired "
        "(threshold=%.2f, margin=%.2f, floor=%.2f)",
        cfg.confidence_threshold, cfg.confidence_margin, cfg.min_hebbian_weight,
    )
    return True


def _wire_workspace_ontology(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-478 v1: Wire WorkspaceOntologyRegistry term frequency helper."""
===END REPLACE===
```

```text
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
            # AD-654d: Wire dispatcher into internal emitters
            if runtime.work_item_store:
                runtime.work_item_store.attach_dispatcher(runtime.dispatcher)
            if runtime.ward_room:
                runtime.ward_room.attach_dispatcher(runtime.dispatcher, runtime.callsign_registry)
===REPLACE===
            # AD-654d: Wire dispatcher into internal emitters
            if runtime.work_item_store:
                runtime.work_item_store.attach_dispatcher(runtime.dispatcher)
            if runtime.ward_room:
                runtime.ward_room.attach_dispatcher(runtime.dispatcher, runtime.callsign_registry)

            # AD-581 v1: HybridDispatch — must follow AD-654c so runtime.dispatcher
            # is available. _wire_hybrid_dispatch is tier-2 log-and-degrade.
            if _wire_hybrid_dispatch(runtime=runtime, config=config):
                logger.info("AD-581 v1: HybridDispatch wired during finalization")
===END REPLACE===
```

`runtime.department_dispatcher` and `runtime.work_item_router` are set by the wirer; they don't require typed declarations on `ProbOSRuntime` (precedent: `runtime.consultation_dispatcher` is also wirer-set without a typed attribute declaration — see `consultation/dispatch.py:289` and `startup/finalize.py:748`).

**Subscription wiring** (inside `_wire_hybrid_dispatch`, immediately after the two assignments and before the final `logger.info`):

```python
    # AD-581a: register WorkItemRouter as listener for WORK_ITEM_CREATED.
    # runtime.add_event_listener (runtime.py:694) handles async callables
    # via asyncio.create_task at runtime.py:819-820.
    runtime.add_event_listener(
        runtime.work_item_router.on_work_item_created,
        event_types=["work_item_created"],
    )
```

---

## Section 6 — Tests

### File: `tests/test_ad581_hybrid_dispatch.py` (NEW)

Single test file, ~30 tests across DepartmentDispatcher (12), WorkItemRouter (8), Order Protocol decline/refuse (8), config + wiring (2). All synchronous except WorkItemRouter tests (which use async fakes).

**Required test cases (Builder constructs each):**

DepartmentDispatcher (12):

1. `route` returns BROADCAST when `candidates` is empty (`reason == "broadcast_no_candidates"`).
2. `route` returns BROADCAST when `hebbian_router is None` (`reason == "broadcast_no_router"`).
3. `route` returns DIRECT when WorkItem.assigned_to is set (forced-direct, `confidence == 1.0`, `reason == "direct_assigned_hint"`).
4. `route` returns BROADCAST when max weight < `min_hebbian_weight` (cold start, `reason == "broadcast_below_floor"`).
5. `route` returns BROADCAST when max weight ≥ floor but < `confidence_threshold` (`reason == "broadcast_below_threshold"`).
6. `route` returns BROADCAST when threshold met but margin over runner-up < `confidence_margin` (`reason == "broadcast_no_margin"`).
7. `route` returns DIRECT when threshold + margin both satisfied (`reason == "direct_high_confidence"`, `agent_id == top_id`, `runner_up_weight == ...`).
8. `route` is pure — calling twice with same inputs returns equal `RoutingDecision`.
9. `route` populates `department_id` from ontology when resolvable.
10. `route` returns `department_id == None` when ontology is None (graceful).
11. `record_outcome` + `get_success_rate` round-trip: 8 successes + 2 failures over `success_rate_window=10` returns `(0.8, 10)`.
12. `get_success_rate` returns `(0.0, n)` when `n < min_samples_for_routing` (no data signal).

WorkItemRouter (8):

13. `is_dispatchable` returns True for items with a configured dispatchable tag.
14. `is_dispatchable` returns True for items with `metadata["dispatchable"] == True`.
15. `is_dispatchable` returns False for items with neither.
16. `on_work_item_created` skips non-dispatchable items (no dispatcher.dispatch call).
17. `on_work_item_created` with assigned_to set → DIRECT TaskEvent dispatched (assert `event.target.agent_id == assigned`, `HYBRID_DISPATCH_DIRECT` emitted).
18. `on_work_item_created` with low Hebbian → BROADCAST TaskEvent (assert `event.target.broadcast is True`, `HYBRID_DISPATCH_BROADCAST` emitted).
19. `on_work_item_created` swallows exceptions from dispatcher.dispatch (logs warning; never raises).
20. `_priority_from_int` maps 1→CRITICAL, 3→NORMAL, 5→LOW (per Priority enum at `types.py:76-89`).

Order Protocol decline/refuse (8):

21. `OrderState.DECLINED.value == "declined"` and `OrderState.REFUSED.value == "refused"`.
22. `EventType.ORDER_DECLINED.value == "order_declined"` and `ORDER_REFUSED.value == "order_refused"`.
23. `OrderManager.decline()` transitions PENDING→DECLINED, sets fields, emits ORDER_DECLINED with reason.
24. `OrderManager.decline()` returns False when reason is empty/whitespace (no state change).
25. `OrderManager.decline()` returns False when caller is not the target-post holder (no state change).
26. `OrderManager.decline()` invokes registered `reassignment_callback`; callback exception is logged and swallowed.
27. `OrderManager.refuse()` with caller-supplied violation transitions PENDING→REFUSED, emits ORDER_REFUSED.
28. `OrderManager.refuse()` with default predicate (no violation) returns False; with custom predicate returning `(True, "fed_violation")` transitions and uses predicate reason.

Config + wiring (2):

29. `HybridDispatchConfig()` defaults: `enabled=True`, `confidence_threshold=0.4`, `confidence_margin=0.05`, `min_hebbian_weight=0.05`, `success_rate_window=50`, `min_samples_for_routing=3`, `dispatchable_tags == ["consultation"]`. Validators reject `confidence_threshold=2.0` and `success_rate_window=0`.
30. `_wire_hybrid_dispatch` skips with INFO + returns False when `runtime.hebbian_router` is None; sets `runtime.department_dispatcher` and `runtime.work_item_router` when all four dependencies present.

**Test fixtures Builder MUST use:**

- `_FakeRegistry` with `.all()` returning a list of objects exposing `.id` (precedent: `tests/test_ad440_chain_of_command_delegation.py:38-43`).
- `_FakeOntology` exposing `.get_assignment_for_agent(agent_type)`, `.get_post(post_id)`, `.get_agent_department(agent_type)` (precedent: `tests/test_ad440_chain_of_command_delegation.py:45-58`).
- A `_FakeHebbian` with `.get_weight(source, target, rel_type=None) -> float` driven by a dict the test populates.
- A `_FakeDispatcher` (AD-654c) with `async def dispatch(event)` that records the event; tests assert event shape.

**Forbidden:** any test that boots a real `ProbOSRuntime`, opens the real `WorkItemStore`, or talks to a real `OrderManager` constructed by `_wire_chain_of_command`. Unit tests stand up the components directly.

---

## Section 7 — Tracking

After build, Builder updates:

- `PROGRESS.md` — Wave 81 paragraph at top of "Recent Builder Closures". Copy AD-594c paragraph shape; report exact pytest count delta and confirm 0 NEW phantoms.
- `docs/development/roadmap.md` — locate `### Hybrid Dispatch — Chain-of-Command Direct Tasking (AD-581)` (line 4656) and adjacent sub-AD entries (4662–4666). Flip 581a, 581b, 581d from `*(planned, OSS)*` to `*(complete — Wave 81, OSS)*`. Leave 581c and 581e unchanged (still `*(planned, Commercial)*`). Update the AD-581 umbrella entry status note to: "OSS sub-ADs 581a/b/d shipped Wave 81; commercial sub-ADs 581c/e tracked in private commercial repo."
- `DECISIONS.md` — append `### AD-581 v1: Hybrid Dispatch — DepartmentDispatcher + Order Protocol + Routing Confidence (2026-05-06)` entry above the AD-594c entry (Wave 80). Body summarizes: 5 modules touched, 30 tests, 4 EventTypes added (2 order + 2 routing), Standing-Order predicate is a Protocol seam, dream-cycle auto-tuning is a hook stub, commercial sub-ADs explicitly out of scope.
- `prompts/wave-plan.yaml` — id `"81"` flipped to `status: done`.

GH issue closure note (paste verbatim into `gh issue close 113 -c "..."`):

> "Closed by Wave 81 (OSS sub-ADs 581a/b/d). DepartmentDispatcher routes by Hebbian + ontology with cold-start floor + confidence threshold + runner-up margin. WorkItemRouter bridges WORK_ITEM_CREATED → AD-654c TaskEvent dispatch (consumes AD-594c WorkItems). OrderManager extended with decline/refuse semantics + reassignment callback hook + Standing-Order-violation predicate Protocol seam. Commercial sub-ADs 581c (ASA Bridge) and 581e (Project Team Dispatch) tracked in private commercial repo as extension points on top of these OSS primitives. Standing-Order directive integration and dream-cycle auto-tuning ship as Protocol seams; concrete implementations follow when consumer signal arrives."

---

## What This Does NOT Change

- AD-440 `OrderManager.issue_order()` / `.acknowledge()` / `.list_active_*` / `_prune_expired` — backward compatible. Existing 8 AD-440 tests pass unchanged.
- AD-594c `ParallelDispatcher` — no signature or behavior change. WorkItems it produces are now consumed by WorkItemRouter, but ParallelDispatcher does not call into AD-581.
- AD-654c `Dispatcher` — used as-is. No new methods. WorkItemRouter calls `dispatcher.dispatch(event)` exactly like AD-654d emitters do.
- HebbianRouter — read-only consumer; no schema change.
- VesselOntologyService — read-only consumer; no method addition.
- WorkItemStore — no schema migration. WorkItem.assigned_to is read as-is from existing column.
- IntentBus — not used by AD-581 v1 routing path. WorkItemRouter forwards via AD-654c only.
- Federation — orders are local-process. No cross-node order replication.
- HXI — no UI surface. Routing decisions observable via EventType only.
- Pricing / commercial / enterprise — none. Public OSS only.

## Acceptance Criteria

1. `pytest tests/ -q -n 4 --dist=loadfile` reports ≥ 11595 passed (Δ ≥ +30 over baseline 11565).
2. `pytest tests/test_ad581_hybrid_dispatch.py -v -n 0` reports 30 passed, 0 failed.
3. `pytest tests/test_ad440_chain_of_command_delegation.py -v -n 0` reports the existing AD-440 count passing unchanged (no regression from OrderState extension).
4. `pytest tests/test_ad594c_parallel_dispatch.py -v -n 0` reports the existing AD-594c count passing unchanged (Wave 80 baseline preserved).
5. Phantom-API pre-check on this prompt body: 0 NEW phantoms (intra-prompt-introduction FPs allowed: `DepartmentDispatcher`, `WorkItemRouter`, `RoutingDecision`, `RoutingMode`, `HybridDispatchConfig`, `OrderState.DECLINED`, `OrderState.REFUSED`, `OrderManager.decline`, `OrderManager.refuse`, `OrderManager.register_reassignment_callback`, `EventType.ORDER_DECLINED`, `EventType.ORDER_REFUSED`, `EventType.HYBRID_DISPATCH_DIRECT`, `EventType.HYBRID_DISPATCH_BROADCAST`, `_wire_hybrid_dispatch`, `runtime.department_dispatcher`, `runtime.work_item_router`).
6. No commercial language anywhere — no pricing, no premium-feature specs, no third-party-product positioning, no `*(Commercial)*` body content for 581c or 581e (their roadmap entries stay tagged but body text unchanged).
7. All changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
8. `gh issue close 113` with the closure note above.

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  7dee646

# AD-654c surface (consumer):
src/probos/activation/task_event.py:18-43    # AgentTarget exactly-one validation
src/probos/activation/task_event.py:75-94    # task_event_for_agent kwargs
src/probos/activation/task_event.py:117+     # task_event_broadcast (Builder verifies signature)
src/probos/activation/dispatcher.py:67       # async def dispatch(event) -> DispatchResult

# AD-440 surface (extending):
src/probos/cognitive/orders.py:28-32         # OrderState (extending with DECLINED/REFUSED)
src/probos/cognitive/orders.py:35-49         # @dataclass(frozen=True) Order (extending fields)
src/probos/cognitive/orders.py:51-75         # OrderManager ctor (extending kwargs)
src/probos/cognitive/orders.py:157-184       # acknowledge() — unchanged precedent for decline/refuse shape

# AD-594c surface (consumer):
src/probos/consultation/dispatch.py:457      # create_work_item(..., assigned_to=spec.agent or None, ...)
src/probos/workforce.py:1052                 # emits WORK_ITEM_CREATED only — confirms activation gap

# HebbianRouter:
src/probos/mesh/routing.py:251-260           # get_weight(source, target, rel_type=None)
# REL_INTENT — Builder verifies via grep before importing; falls back to None

# Ontology:
src/probos/ontology/departments.py:65-72     # get_agent_department(agent_type) -> str | None
src/probos/ontology/departments.py:62-66     # get_assignment_for_agent
src/probos/ontology/departments.py:36-40     # get_post

# Config insertion anchor:
src/probos/config.py:2110                    # ConsultationDispatchConfig (anchor for HybridDispatchConfig)
src/probos/config.py:2496-2498               # consultation_dispatch field on SystemConfig (anchor for hybrid_dispatch field)

# Finalize wirer anchor:
src/probos/startup/finalize.py:715           # _wire_consultation_dispatch (precedent shape)
src/probos/startup/finalize.py:1085          # finalize() invocation order (insert _wire_hybrid_dispatch after)

# Event surface (collision-free):
src/probos/events.py:171-173                 # ORDER_ISSUED/REJECTED/ACKNOWLEDGED (extending)
src/probos/events.py:307-310                 # PARALLEL_DISPATCH_* (insertion anchor for HYBRID_DISPATCH_*)
# ORDER_DECLINED, ORDER_REFUSED, HYBRID_DISPATCH_DIRECT, HYBRID_DISPATCH_BROADCAST — 0 hits at HEAD; safe to add.

# Test precedents:
tests/test_ad440_chain_of_command_delegation.py:38-58  # _FakeRegistry / _FakeOntology / _FakeAssignment / _FakePost shapes
tests/test_ad594c_parallel_dispatch.py                 # async test patterns (real WorkItemStore not required for AD-581)
```
