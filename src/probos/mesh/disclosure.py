"""Selective Disclosure Routing (AD-679).

Classifies content sensitivity and filters intent recipients
based on department-level clearance. Does NOT replace IntentBus
routing — provides a filter layer that callers use to narrow
broadcast targets.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class DisclosureLevel(IntEnum):
    """Content sensitivity classification (AD-679)."""

    PUBLIC = 0
    INTERNAL = 1
    RESTRICTED = 2
    CONFIDENTIAL = 3
    CLASSIFIED = 4


DEFAULT_CLEARANCES: dict[str, DisclosureLevel] = {
    "bridge": DisclosureLevel.CONFIDENTIAL,
    "security": DisclosureLevel.RESTRICTED,
    "engineering": DisclosureLevel.INTERNAL,
    "medical": DisclosureLevel.RESTRICTED,
    "science": DisclosureLevel.INTERNAL,
    "operations": DisclosureLevel.INTERNAL,
    "core": DisclosureLevel.INTERNAL,
    "utility": DisclosureLevel.PUBLIC,
}


@dataclass(frozen=True)
class DisclosureDecision:
    """Result of a disclosure routing check (AD-679)."""

    agent_id: str
    permitted: bool
    agent_clearance: DisclosureLevel
    content_level: DisclosureLevel
    reason: str = ""


class DisclosureRouter:
    """Filters intent/context recipients by disclosure level (AD-679)."""

    def __init__(
        self,
        *,
        clearance_overrides: dict[str, DisclosureLevel] | None = None,
    ) -> None:
        self._department_clearances = dict(DEFAULT_CLEARANCES)
        self._agent_overrides: dict[str, DisclosureLevel] = clearance_overrides or {}

    def set_agent_clearance(
        self, agent_id: str, level: DisclosureLevel,
    ) -> None:
        """Override clearance for a specific agent."""
        self._agent_overrides[agent_id] = level

    def set_department_clearance(
        self, department: str, level: DisclosureLevel,
    ) -> None:
        """Override clearance for a department."""
        self._department_clearances[department] = level

    def get_clearance(
        self, agent_id: str, department: str = "",
    ) -> DisclosureLevel:
        """Resolve effective clearance for an agent."""
        if agent_id in self._agent_overrides:
            return self._agent_overrides[agent_id]
        if department:
            return self._department_clearances.get(
                department, DisclosureLevel.PUBLIC,
            )
        return DisclosureLevel.PUBLIC

    def check_recipients(
        self,
        *,
        content_level: DisclosureLevel,
        candidates: list[str],
        agent_departments: dict[str, str],
    ) -> list[DisclosureDecision]:
        """Check which candidates may receive content at the given level."""
        results: list[DisclosureDecision] = []
        for agent_id in candidates:
            department = agent_departments.get(agent_id, "")
            clearance = self.get_clearance(agent_id, department)
            permitted = clearance >= content_level

            results.append(DisclosureDecision(
                agent_id=agent_id,
                permitted=permitted,
                agent_clearance=clearance,
                content_level=content_level,
                reason=(
                    f"Clearance {clearance.name} >= {content_level.name}"
                    if permitted else
                    f"Clearance {clearance.name} < {content_level.name}"
                ),
            ))

        return results

    def filter_permitted(
        self,
        *,
        content_level: DisclosureLevel,
        candidates: list[str],
        agent_departments: dict[str, str],
    ) -> list[str]:
        """Return only permitted agent IDs."""
        decisions = self.check_recipients(
            content_level=content_level,
            candidates=candidates,
            agent_departments=agent_departments,
        )
        return [d.agent_id for d in decisions if d.permitted]

    def get_clearance_map(self) -> dict[str, str]:
        """Return department to clearance level name mapping."""
        return {
            dept: level.name
            for dept, level in self._department_clearances.items()
        }
