"""Shared crew-identification utility used by multiple extracted modules."""

from __future__ import annotations

from typing import Any

# Legacy fallback — remove when ontology is mandatory.
# Core crew eligible for Ward Room participation.
# Ontology equivalent: VesselOntologyService.get_crew_agent_types()
_WARD_ROOM_CREW = {
    "architect", "scout", "counselor",
    "security_officer", "operations_officer", "engineering_officer",
    "diagnostician",  # Bones — CMO / Medical Chief
    "surgeon", "pathologist", "pharmacist",  # Medical crew
    "builder",  # Scotty — SWE officer, uses build pipeline as tool
    "data_analyst", "systems_analyst", "research_specialist",  # Science crew (AD-560)
}


# AD-619: Agent types with ship-wide cross-department authority.
# Bridge officers who report directly to the Captain and need visibility
# into all department channels + cross-shard Oracle recall.
# Ontology equivalent: posts with reports_to == "captain" and tier == "crew".
_SHIP_WIDE_AUTHORITY_TYPES = {"counselor"}


def has_ship_wide_authority(agent: Any) -> bool:
    """Check if an agent has ship-wide cross-department authority (AD-619)."""
    return getattr(agent, 'agent_type', '') in _SHIP_WIDE_AUTHORITY_TYPES


def is_crew_agent(agent: Any, ontology: Any | None = None) -> bool:
    """Check if an agent is core crew eligible for Ward Room participation."""
    if not hasattr(agent, 'agent_type'):
        return False
    # AD-429e: Prefer ontology, fall back to legacy set
    if ontology:
        return agent.agent_type in ontology.get_crew_agent_types()
    return agent.agent_type in _WARD_ROOM_CREW
