"""Agent tier registry for trust and emergence filtering (AD-571)."""

from __future__ import annotations

from enum import StrEnum


class AgentTier(StrEnum):
    """Agent tiers used to separate crew trust from infrastructure noise."""

    CORE_INFRASTRUCTURE = "core_infrastructure"
    UTILITY = "utility"
    CREW = "crew"


class AgentTierRegistry:
    """In-memory registry mapping agent IDs to trust-separation tiers."""

    def __init__(self) -> None:
        self._tiers: dict[str, AgentTier] = {}

    def register(self, agent_id: str, tier: AgentTier) -> None:
        """Register or replace an agent's tier."""
        self._tiers[agent_id] = tier

    def get_tier(self, agent_id: str) -> AgentTier:
        """Return an agent's tier, defaulting unregistered agents to UTILITY."""
        return self._tiers.get(agent_id, AgentTier.UTILITY)

    def is_crew(self, agent_id: str) -> bool:
        """Return True when an agent is registered as crew."""
        return self.get_tier(agent_id) == AgentTier.CREW

    def crew_agents(self) -> list[str]:
        """Return all registered crew agent IDs in stable order."""
        return sorted(agent_id for agent_id, tier in self._tiers.items() if tier == AgentTier.CREW)

    def all_registered(self) -> dict[str, AgentTier]:
        """Return a copy of all registered agent tiers."""
        return dict(self._tiers)
