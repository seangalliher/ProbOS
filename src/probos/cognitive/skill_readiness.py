"""AD-628b: Agent skill readiness profile aggregator.

Pure read-side aggregator over AgentSkillService + qual_skill_bridge
SkillAdvancement history + an internal regression-event ring populated
by AD-628a SKILL_REGRESSION emission consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from probos.skill_framework import ProficiencyLevel

if TYPE_CHECKING:
    from probos.cognitive.qual_skill_bridge import SkillAdvancement
    from probos.skill_framework import AgentSkillService, SkillRegistry


_REGRESSION_RING_CAP = 100
_RECENT_LIMIT = 10


@dataclass(frozen=True)
class SkillRegressionEvent:
    """AD-628b: a captured SKILL_REGRESSION event."""

    agent_id: str
    skill_id: str
    from_level: int
    to_level: int
    timestamp: float
    reason: str = ""


@dataclass(frozen=True)
class AgentSkillReadinessProfile:
    """AD-628b: read-only readiness snapshot for one agent."""

    agent_id: str
    qualifications: list[str] = field(default_factory=list)
    proficiency_distribution: dict[str, int] = field(default_factory=dict)
    recent_advancements: list["SkillAdvancement"] = field(default_factory=list)
    recent_regressions: list[SkillRegressionEvent] = field(default_factory=list)
    last_exercised_per_skill: dict[str, float] = field(default_factory=dict)
    composite_capabilities: list[str] = field(default_factory=list)


class AgentSkillReadinessService:
    """AD-628b: read-side readiness aggregator (no writes to skill state)."""

    def __init__(
        self,
        skill_service: "AgentSkillService",
        *,
        advancement_log: list["SkillAdvancement"] | None = None,
        registry: "SkillRegistry | None" = None,
    ) -> None:
        self._skill_service = skill_service
        self._advancement_log: list["SkillAdvancement"] = (
            advancement_log if advancement_log is not None else []
        )
        self._regression_ring: list[SkillRegressionEvent] = []
        self._registry = registry

    def record_regression(self, event: SkillRegressionEvent) -> None:
        """Append a regression event; cap ring at 100."""
        self._regression_ring.append(event)
        if len(self._regression_ring) > _REGRESSION_RING_CAP:
            # Drop oldest
            del self._regression_ring[: len(self._regression_ring) - _REGRESSION_RING_CAP]

    def record_advancement(self, advancement: "SkillAdvancement") -> None:
        """Append a qual_skill_bridge advancement."""
        self._advancement_log.append(advancement)

    async def get_profile(self, agent_id: str) -> AgentSkillReadinessProfile:
        """Build the read-only readiness profile for one agent."""
        skill_profile = await self._skill_service.get_profile(agent_id)
        all_records = skill_profile.all_skills

        qualifications = [
            r.skill_id for r in all_records
            if r.proficiency.value >= ProficiencyLevel.APPLY.value
        ]

        distribution: dict[str, int] = {}
        for r in all_records:
            distribution[r.proficiency.name] = distribution.get(r.proficiency.name, 0) + 1

        # Recent advancements: filter by agent, last 10 newest-first
        agent_advancements = [
            a for a in self._advancement_log if a.agent_id == agent_id
        ]
        recent_advancements = list(reversed(agent_advancements))[:_RECENT_LIMIT]

        # Recent regressions: filter by agent, last 10 newest-first (sorted by timestamp)
        agent_regressions = [
            r for r in self._regression_ring if r.agent_id == agent_id
        ]
        agent_regressions.sort(key=lambda e: e.timestamp, reverse=True)
        recent_regressions = agent_regressions[:_RECENT_LIMIT]

        last_exercised = {r.skill_id: r.last_exercised for r in all_records}

        composite_capabilities: list[str] = []
        if self._registry is not None:
            try:
                for skill_def in self._registry.list_skills():
                    if getattr(skill_def, "composite_skill_ids", None):
                        if skill_profile.has_composite_capability(skill_def):
                            composite_capabilities.append(skill_def.skill_id)
            except Exception:
                # Tier-2: if registry traversal fails, return empty composite list
                composite_capabilities = []

        return AgentSkillReadinessProfile(
            agent_id=agent_id,
            qualifications=qualifications,
            proficiency_distribution=distribution,
            recent_advancements=recent_advancements,
            recent_regressions=recent_regressions,
            last_exercised_per_skill=last_exercised,
            composite_capabilities=composite_capabilities,
        )
