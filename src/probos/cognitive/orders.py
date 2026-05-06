"""AD-440: Chain of Command Delegation.

Typed agent-to-agent orders validated against ontology authority_over.
Orthogonal to Captain directives (commands_directives.py): Captain orders
are broadcast Standing-Order-style entries with priority 1.0; AD-440
orders are point-to-point delegations from a superior to a direct report.
"""

from __future__ import annotations

import dataclasses
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
    """v1 default -- never reports a violation."""
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
        if from_assignment is None:
            self._emit_rejection(from_agent_id, to_post_id, "issuer_resolution_failed")
            return None
        from_post = self._ontology.get_post(from_assignment.post_id)
        if from_post is None:
            self._emit_rejection(from_agent_id, to_post_id, "issuer_resolution_failed")
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
            "AD-440: order %s issued by %s -> %s (%s)",
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

        Fired on ``decline()`` only (not on refuse -- refuse means the order
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
        or computed via the injected ``StandingOrderPredicate`` -- when both
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
        if assignment is None:
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
                self._orders[oid] = dataclasses.replace(o, state=OrderState.EXPIRED)

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
        logger.info("AD-440: order rejected (%s) %s -> %s", reason, from_agent_id, to_post_id)
