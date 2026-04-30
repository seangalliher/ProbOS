"""Ontology-Based Task Routing (AD-438).

Maps intent types to departments and agents using the ontology's
department→post→agent assignments. When the ontology knows which
department handles an intent type, routes directly. Falls back to
broadcast for unknown intent types.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouteDecision:
    """Result of a routing lookup (AD-438)."""

    intent_type: str
    strategy: str
    department: str | None = None
    agent_ids: list[str] = field(default_factory=list)
    reason: str = ""


class TaskRouter:
    """Maps intent types to departments via ontology (AD-438).

    Two routing strategies:
    - DIRECTED: ontology maps intent → department → agents. Only
      those agents receive the intent.
    - BROADCAST: no ontology mapping exists. Falls back to
      IntentBus broadcast (all subscribers self-select).

    The router does NOT replace IntentBus or Dispatcher. It provides
    a routing decision that callers use to choose between directed
    send and broadcast.
    """

    def __init__(
        self,
        *,
        ontology: Any | None = None,
    ) -> None:
        self._ontology = ontology
        self._intent_department_map: dict[str, str] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default intent → department mappings."""
        self._intent_department_map.update({
            "threat_analysis": "security",
            "security_assessment": "security",
            "access_review": "security",
            "power_diagnostic": "engineering",
            "system_repair": "engineering",
            "performance_optimization": "engineering",
            "wellness_check": "medical",
            "crew_health_report": "medical",
            "data_analysis": "science",
            "anomaly_investigation": "science",
            "research_query": "science",
            "resource_allocation": "operations",
            "scheduling": "operations",
        })

    def register_mapping(self, intent_type: str, department: str) -> None:
        """Register or override an intent → department mapping."""
        self._intent_department_map[intent_type] = department
        logger.debug(
            "AD-438: Registered task route mapping intent_type=%s department=%s",
            intent_type,
            department,
        )

    def resolve(self, intent_type: str) -> RouteDecision:
        """Resolve routing for an intent type.

        Returns a RouteDecision indicating directed or broadcast strategy.
        """
        department = self._intent_department_map.get(intent_type)

        if department is None:
            return RouteDecision(
                intent_type=intent_type,
                strategy="broadcast",
                reason="No ontology mapping for this intent type",
            )

        agent_ids: list[str] = []
        if self._ontology:
            try:
                posts = self._ontology.get_posts(department_id=department)
                post_ids = {p.id for p in posts}
                assignments = self._ontology.get_all_assignments()
                for assignment in assignments:
                    if assignment.post_id in post_ids and assignment.agent_id:
                        agent_ids.append(assignment.agent_id)
            except Exception:
                logger.debug(
                    "AD-438: Ontology lookup failed for department=%s; falling back to broadcast routing",
                    department,
                    exc_info=True,
                )

        if not agent_ids:
            return RouteDecision(
                intent_type=intent_type,
                strategy="broadcast",
                department=department,
                reason=f"Department '{department}' has no wired agents",
            )

        return RouteDecision(
            intent_type=intent_type,
            strategy="directed",
            department=department,
            agent_ids=agent_ids,
            reason=f"Ontology: {intent_type} → {department}",
        )

    def list_mappings(self) -> dict[str, str]:
        """Return all registered intent → department mappings."""
        return dict(self._intent_department_map)
