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
