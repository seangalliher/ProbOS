# AD-440: Chain of Command Delegation

**Status:** Ready for builder
**Dependencies:** None hard. AD-477 (Naval Org Protocols) is **NOT** a hard prerequisite — `authority_over` is owned by AD-429 (closed). AD-477 adds qualification programs and SORM, which are orthogonal to typed-order semantics.
**Estimated tests:** ~14
**Risk:** High — adds an authority-respecting agent-to-agent order channel. Trust/authority semantics, must integrate with consensus and proactive context. Different from existing `cmd_order` (Captain directives, verified at `commands_directives.py:99`) which broadcasts a `DirectiveType.CAPTAIN_ORDER` system-wide.

---

## Problem

The ontology defines `authority_over` (verified at `config/ontology/organization.yaml:28,38,80,124` and used by `VesselOntologyService.get_subordinate_agent_types()` at `service.py:174`). It is a YAML field with no runtime mechanism for a Chief to issue a direct order to a direct report. Captains can issue Standing-Order-style directives via `cmd_order` (verified at `experience/commands/commands_directives.py:99` — issuer hardcoded `Rank.SENIOR`, type `CAPTAIN_ORDER`), but a Chief Engineer cannot today issue a typed order to its Engineering Officer through any validated path.

`grep -rn "issue_order" src/probos/` returns no matches.

The "absent Captain" problem: when the Captain is not at the conn, the First Officer should be able to delegate cross-department work without requiring Captain involvement. The chain of command exists in YAML but has no runtime expression.

## Solution Overview

Add `OrderManager` that exposes `issue_order(from_agent_id, to_post_id, directive, ...)` validated against the ontology's `authority_over` graph. Orders that pass validation are persisted in-memory (with TTL), surfaced to subordinates via the proactive cognitive context, and emit `EventType.ORDER_ISSUED`. Out-of-chain attempts emit `EventType.ORDER_REJECTED` and are denied. No mutation of trust or Hebbian weights.

This is **non-destructive** — orders are advisory until the subordinate executes through their normal capabilities. AD-440 does NOT add new destructive intents and does NOT require consensus gating per the standing rule (verified — order issuance itself does not destroy state; the actions a subordinate takes in response retain their existing consensus gates).

---

## Section 0: Event Types

Add to `src/probos/events.py` near the existing chain/agent diagnostics block (around line 167 between `DM_CONVERGENCE_DETECTED` and `SENSORIUM_BUDGET_EXCEEDED`):

```
ORDER_ISSUED = "order_issued"  # AD-440
ORDER_REJECTED = "order_rejected"  # AD-440 — out-of-chain or invalid order
ORDER_ACKNOWLEDGED = "order_acknowledged"  # AD-440 — subordinate ack
```

Three new values. Verified absent via `grep -n "ORDER_" src/probos/events.py` (no `ORDER_*` matches).

---

## Section 1: Create `OrderManager`

**File:** `src/probos/cognitive/orders.py` (new)

```python
"""AD-440: Chain of Command Delegation.

Typed agent-to-agent orders validated against ontology authority_over.
Orthogonal to Captain directives (commands_directives.py): Captain orders
are broadcast Standing-Order-style entries with priority 1.0; AD-440
orders are point-to-point delegations from a superior to a direct report.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.ontology.service import VesselOntologyService
    from probos.substrate.registry import AgentRegistry

logger = logging.getLogger(__name__)


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


class OrderManager:
    """In-memory chain-of-command delegation store.

    Validates issuer authority over target post via ontology.authority_over.
    Orders are advisory: subordinate executes through their normal
    capabilities. No tool registration in this AD.
    """

    DEFAULT_TTL_SECONDS = 3600.0

    def __init__(
        self,
        *,
        ontology: VesselOntologyService,
        registry: AgentRegistry,
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

    def issue_order(
        self,
        *,
        from_agent_id: str,
        to_post_id: str,
        directive: str,
        ttl_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Order | None:
        """Issue an order from from_agent_id to to_post_id.

        Returns the persisted Order on success, None on rejection.
        Rejection reasons emit EventType.ORDER_REJECTED with a `reason` field.
        """
        if not directive or not directive.strip():
            self._emit_rejection(from_agent_id, to_post_id, "empty_directive")
            return None

        from_agent_type = self._agent_type_for_id(from_agent_id)
        if not from_agent_type:
            self._emit_rejection(from_agent_id, to_post_id, "unknown_issuer")
            return None
        from_assignment = self._ontology.get_assignment_for_agent(from_agent_type)
        if not from_assignment:
            self._emit_rejection(from_agent_id, to_post_id, "issuer_no_assignment")
            return None
        from_post = self._ontology.get_post(from_assignment.post_id)
        if not from_post:
            self._emit_rejection(from_agent_id, to_post_id, "issuer_post_missing")
            return None

        if to_post_id not in (from_post.authority_over or []):
            self._emit_rejection(from_agent_id, to_post_id, "out_of_chain")
            return None

        active_to_post = sum(
            1 for o in self._orders.values()
            if o.to_post_id == to_post_id and o.state == OrderState.PENDING
        )
        if active_to_post >= self._max_active_per_post:
            self._emit_rejection(from_agent_id, to_post_id, "queue_full")
            return None

        now = time.time()
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        order = Order(
            id=uuid.uuid4().hex[:12],
            from_agent_id=from_agent_id,
            from_post_id=from_assignment.post_id,
            to_post_id=to_post_id,
            directive=directive.strip(),
            issued_at=now,
            expires_at=now + ttl,
            metadata=dict(metadata or {}),
        )
        self._orders[order.id] = order

        if self._emit_event:
            try:
                self._emit_event(
                    EventType.ORDER_ISSUED,
                    {
                        "order_id": order.id,
                        "from_agent_id": order.from_agent_id,
                        "from_post_id": order.from_post_id,
                        "to_post_id": order.to_post_id,
                        "directive": order.directive,
                        "expires_at": order.expires_at,
                    },
                )
            except Exception:
                logger.warning("AD-440: ORDER_ISSUED emit failed; order persisted", exc_info=True)

        logger.info(
            "AD-440: order %s issued by %s → %s (%s)",
            order.id, from_assignment.post_id, to_post_id,
            order.directive[:60],
        )
        return order

    def acknowledge(self, order_id: str, by_agent_id: str) -> bool:
        """Subordinate acknowledges an order. Returns True if state changed."""
        order = self._orders.get(order_id)
        if order is None or order.state != OrderState.PENDING:
            return False
        agent_type = self._agent_type_for_id(by_agent_id)
        assignment = (
            self._ontology.get_assignment_for_agent(agent_type) if agent_type else None
        )
        if not assignment or assignment.post_id != order.to_post_id:
            return False
        updated = Order(
            **{**order.__dict__, "state": OrderState.ACKNOWLEDGED,
               "acknowledged_by": by_agent_id, "acknowledged_at": time.time()},
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

    def list_active_for_post(self, post_id: str) -> list[Order]:
        """Pending orders targeting a post (after TTL prune)."""
        self._prune_expired()
        return [
            o for o in self._orders.values()
            if o.to_post_id == post_id and o.state == OrderState.PENDING
        ]

    def list_active_for_agent(self, agent_id: str) -> list[Order]:
        """Pending orders for the post an agent currently fills."""
        agent_type = self._agent_type_for_id(agent_id)
        if not agent_type:
            return []
        assignment = self._ontology.get_assignment_for_agent(agent_type)
        if not assignment:
            return []
        return self.list_active_for_post(assignment.post_id)

    def all_orders(self) -> list[Order]:
        self._prune_expired()
        return list(self._orders.values())

    def _agent_type_for_id(self, agent_id: str) -> str | None:
        for agent in self._registry.all():
            if getattr(agent, "id", "") == agent_id:
                return getattr(agent, "agent_type", None)
        return None

    def _prune_expired(self) -> None:
        now = time.time()
        for oid, o in list(self._orders.items()):
            if o.state == OrderState.PENDING and o.expires_at < now:
                self._orders[oid] = Order(
                    **{**o.__dict__, "state": OrderState.EXPIRED},
                )

    def _emit_rejection(self, from_agent_id: str, to_post_id: str, reason: str) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.ORDER_REJECTED,
                {
                    "from_agent_id": from_agent_id,
                    "to_post_id": to_post_id,
                    "reason": reason,
                },
            )
        except Exception:
            logger.warning("AD-440: ORDER_REJECTED emit failed", exc_info=True)
        logger.info("AD-440: order rejected (%s) %s → %s", reason, from_agent_id, to_post_id)
```

---

## Section 2: Add Order EventTypes

**File:** `src/probos/events.py`

SEARCH (around line 167):
```python
    DM_CONVERGENCE_DETECTED = "dm_convergence_detected"  # AD-623: DM thread converged
    SENSORIUM_BUDGET_EXCEEDED = "sensorium_budget_exceeded"  # AD-666: sensorium injection over char threshold
```

REPLACE:
```python
    DM_CONVERGENCE_DETECTED = "dm_convergence_detected"  # AD-623: DM thread converged
    ORDER_ISSUED = "order_issued"  # AD-440
    ORDER_REJECTED = "order_rejected"  # AD-440
    ORDER_ACKNOWLEDGED = "order_acknowledged"  # AD-440
    SENSORIUM_BUDGET_EXCEEDED = "sensorium_budget_exceeded"  # AD-666: sensorium injection over char threshold
```

---

## Section 3: Add `OrdersConfig`

**File:** `src/probos/config.py`

```python
class OrdersConfig(BaseModel):
    """Chain-of-command order configuration (AD-440)."""

    enabled: bool = True
    max_active_per_post: int = 8
    default_ttl_seconds: float = 3600.0
```

Wire into `SystemConfig`:

SEARCH:
```python
    emergence_metrics: EmergenceMetricsConfig = EmergenceMetricsConfig()
```

REPLACE:
```python
    emergence_metrics: EmergenceMetricsConfig = EmergenceMetricsConfig()
    orders: OrdersConfig = OrdersConfig()  # AD-440
```

---

## Section 4: Wire into startup

**File:** `src/probos/startup/finalize.py`

Place near the existing risk-registry block (`finalize.py:297`):

```python
    # AD-440: Chain of Command order manager
    if config.orders.enabled:
        from probos.cognitive.orders import OrderManager
        order_manager = OrderManager(
            ontology=runtime.ontology,
            registry=runtime.registry,
            emit_event=runtime.emit_event,
            max_active_per_post=config.orders.max_active_per_post,
            default_ttl=config.orders.default_ttl_seconds,
        )
        runtime._order_manager = order_manager
        logger.info("AD-440: OrderManager wired (max_active=%d)", config.orders.max_active_per_post)
```

---

## Section 5: Proactive context injection

**File:** `src/probos/proactive.py`

Subordinates with active orders should see them at the top of their proactive context. Find the `_gather_context()` method and add a new context block. The existing pattern (search for `if hasattr(rt, 'bridge_alerts')` for an analogous block) is to read a list and inject formatted strings into `context_parts`.

Add (after the bridge-alerts block):

```python
        # AD-440: Active chain-of-command orders for this agent
        order_mgr = getattr(rt, "_order_manager", None)
        if order_mgr is not None:
            try:
                pending = order_mgr.list_active_for_agent(agent.id)
                if pending:
                    lines = ["ACTIVE ORDERS (act on these in priority order):"]
                    for o in pending:
                        lines.append(f"  - [{o.id}] from {o.from_post_id}: {o.directive}")
                    context["active_orders"] = "\n".join(lines)
            except Exception:
                logger.debug("AD-440: order context injection failed", exc_info=True)
```

> Verify-first: builder MUST grep `_gather_context` to confirm the exact insertion point. Do NOT use stale line numbers; they drift.

---

## Section 6: REST endpoint

**File:** `src/probos/routers/orders.py` (new — 50 lines, follows `routers/task_router.py` style if present, otherwise the AD-679 disclosure router pattern).

Endpoints:
- `GET /api/orders` — list all orders (state filter optional).
- `GET /api/orders/post/{post_id}` — pending orders for a post.
- `POST /api/orders` — Captain-only override path to issue orders bypassing chain validation. Out of scope; **omit** in this AD.

Implement only the two GET endpoints. Surface in `routers/__init__.py`.

---

## Tests

**File:** `tests/test_ad440_chain_of_command_delegation.py`

14 tests:

1. `test_event_type_order_issued_exists` — `EventType.ORDER_ISSUED.value == "order_issued"`.
2. `test_event_type_order_rejected_exists` — value present.
3. `test_event_type_order_acknowledged_exists` — value present.
4. `test_config_defaults` — `OrdersConfig()` defaults to `enabled=True`, `max_active=8`, `ttl=3600`.
5. `test_issue_order_in_chain_succeeds` — chief_engineer issues to engineering_officer post → returns Order, emit_event called once with `ORDER_ISSUED`.
6. `test_issue_order_out_of_chain_rejected` — engineering_officer attempts to order chief_engineer → returns None, emit_event called with `ORDER_REJECTED` reason `"out_of_chain"`.
7. `test_issue_order_empty_directive_rejected` — empty/whitespace directive → reason `"empty_directive"`.
8. `test_issue_order_unknown_issuer_rejected` — agent_id not in registry → reason `"unknown_issuer"`.
9. `test_queue_full_rejection` — 8 active orders to a post, 9th rejected with reason `"queue_full"`.
10. `test_acknowledge_by_correct_subordinate_succeeds` — subordinate filling target post acks → state changes to `ACKNOWLEDGED`, emit fires.
11. `test_acknowledge_by_wrong_agent_fails` — non-subordinate attempts ack → returns False, no emit.
12. `test_list_active_filters_by_post` — two pending orders to two posts → each list returns only its own.
13. `test_ttl_expiration_marks_expired` — `default_ttl=0.1`, sleep 0.2, `all_orders()` shows expired state.
14. `test_proactive_context_injects_active_orders` — `_gather_context` integration test with stubbed `runtime._order_manager` → context contains `"active_orders"` key with order id and directive.

---

## What This Does NOT Change

- No mutation of trust scores. Order compliance is observed by existing trust signals downstream.
- No new destructive intent and no consensus gating on order issuance itself. Subordinate actions retain their existing consensus rules.
- Captain `cmd_order` (`commands_directives.py:99`) is NOT modified. AD-440 introduces an orthogonal chain-of-command channel.
- No persistence to disk in this AD. Orders are in-memory; reset clears them. Future AD may add SQLite persistence if needed.
- No HXI panel in this AD. REST endpoint only.
- No automatic order escalation when a subordinate fails to acknowledge. Manual surface via REST.

---

## Tracking

- `PROGRESS.md`: add `AD-440 CLOSED. Chain of Command Delegation — ...`
- `docs/development/roadmap.md`: flip AD-440 status from `*(planned)*` to `*(complete)*` at line ~4085.
- `DECISIONS.md`: add an entry recording (1) the orthogonality decision against `cmd_order`, (2) the choice of in-memory storage with TTL over disk persistence, (3) the no-consensus-on-issuance decision.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file (`PROGRESS.md`, `roadmap.md`, `DECISIONS.md`) shows >200 deletions, STOP.

Expected delta:
- `src/probos/cognitive/orders.py`: ~250 lines added (new).
- `src/probos/events.py`: 3 lines added.
- `src/probos/config.py`: ~10 lines added.
- `src/probos/startup/finalize.py`: ~13 lines added.
- `src/probos/proactive.py`: ~12 lines added.
- `src/probos/routers/orders.py`: ~50 lines added (new).
- `tests/test_ad440_chain_of_command_delegation.py`: ~340 lines added (new).
- `PROGRESS.md`, `roadmap.md`, `DECISIONS.md`: ~5 lines changed.

---

## Acceptance Criteria

- All 14 tests pass at `pytest tests/test_ad440_chain_of_command_delegation.py -v -n 0`.
- Full parallel gate `pytest tests/ -q -n 8 --dist=loadfile` is non-decreasing vs baseline.
- 3 new EventTypes appear exactly once in `events.py` at the documented insertion point.
- `OrderManager` wired only when `config.orders.enabled` is True.
- Proactive context injection does not crash when `_order_manager` is None (graceful degradation tested).
- DECISIONS.md entry records the three architectural decisions enumerated above.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-04-30)

```
grep -rn "issue_order" src/probos/
  (no matches — AD-440 introduces the symbol)

grep -n "class VesselOntologyService" src/probos/ontology/service.py
  45: class VesselOntologyService:

grep -n "def get_assignment_for_agent" src/probos/ontology/service.py
  153:    def get_assignment_for_agent(self, agent_type: str) -> Assignment | None:

grep -n "def get_post" src/probos/ontology/service.py
  120:    def get_post(self, post_id: str) -> Post | None:

grep -n "authority_over" config/ontology/organization.yaml
  28:    authority_over: [first_officer, counselor]
  38:    authority_over: [chief_engineer, chief_science, chief_medical, chief_security, chief_operations]
  80:    authority_over: [engineering_officer, builder_officer]

grep -n "DM_CONVERGENCE_DETECTED" src/probos/events.py
  167:    DM_CONVERGENCE_DETECTED = "dm_convergence_detected"  # AD-623: DM thread converged

grep -n "ORDER_" src/probos/events.py
  (no matches — names are free)

grep -n "if config.risk_tiers.enabled" src/probos/startup/finalize.py
  297:    if config.risk_tiers.enabled:

grep -n "async def cmd_order" src/probos/experience/commands/commands_directives.py
  99: async def cmd_order(runtime: ProbOSRuntime, console: Console, args: str) -> None:
  (existing CAPTAIN_ORDER directive flow — orthogonal to AD-440)

grep -n "emergence_metrics: EmergenceMetricsConfig" src/probos/config.py
  1544:    emergence_metrics: EmergenceMetricsConfig = EmergenceMetricsConfig()
```
