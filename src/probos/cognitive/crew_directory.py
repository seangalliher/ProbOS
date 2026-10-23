"""AD-1347 S1 (#1627): the live crew as the agent-work service sees it.

``CrewDirectory`` (``probos.agent_work``) over the runtime's registry, ontology and trust. Department and
rank come from ``resolve_agentic_identity``, the resolver the workforce pull authority
(``ProbOSRuntime.resolve_workforce_pull_resource``) uses, so the eligibility the service computes at
creation is the one a claim is judged by. The chief is AD-865's in-department superior (``find_chief_post``).
Synchronous and without I/O: the store's claim gate reads it inside a transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from probos.agent_work import CrewMember
from probos.cognitive.agentic_dispatch import (
    AgenticIdentityUnresolved,
    AgentIdentityTrust,
    resolve_agentic_identity,
)
from probos.cognitive.crew_delegation import find_chief_post, resolve_post_agent

if TYPE_CHECKING:
    from probos.ontology import VesselOntologyService
    from probos.substrate.registry import AgentRegistry


class RuntimeCrewDirectory:
    """The live crew: alive, of a crew-tier agent type, with a resolvable department and rank."""

    def __init__(
        self, *, agent_registry: AgentRegistry, ontology: VesselOntologyService,
        trust_network: AgentIdentityTrust,
    ) -> None:
        self._registry = agent_registry
        self._ontology = ontology
        self._trust = trust_network

    def members(self) -> tuple[CrewMember, ...]:
        """Every live crew member, ordered by slot id."""
        crew_types = self._ontology.get_crew_agent_types()
        found = [self._member_of(agent, crew_types) for agent in self._registry.all()]
        return tuple(sorted((member for member in found if member is not None), key=lambda member: member.slot_id))

    def member(self, slot_id: str) -> CrewMember | None:
        """The live crew member in ``slot_id``, or None."""
        if type(slot_id) is not str or not slot_id:
            return None
        agent = self._registry.get(slot_id)
        if agent is None:
            return None
        return self._member_of(agent, self._ontology.get_crew_agent_types())

    def _member_of(self, agent: Any, crew_types: set[str]) -> CrewMember | None:
        agent_type = getattr(agent, "agent_type", None)
        if getattr(agent, "is_alive", None) is not True or agent_type not in crew_types:
            return None
        try:
            identity = resolve_agentic_identity(
                agent_id=agent.id, agent_registry=self._registry,
                ontology=self._ontology, trust_network=self._trust,
            )
        except AgenticIdentityUnresolved:
            return None
        chief = None
        post = self._ontology.get_post_for_agent(identity.agent_type)
        chief_post = find_chief_post(self._ontology, post) if post is not None else None
        if chief_post is not None:
            chief = resolve_post_agent(self._ontology, chief_post.id)
        return CrewMember(identity.agent_id, identity.agent_type, identity.department, identity.rank, chief)
