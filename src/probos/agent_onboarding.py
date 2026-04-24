"""AD-515: Agent onboarding service extracted from ProbOSRuntime.

Handles wiring agents to mesh infrastructure and running naming ceremonies.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from probos.config import format_trust
from probos.crew_utils import is_crew_agent
from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent

if TYPE_CHECKING:
    from probos.acm import AgentCapitalService
    from probos.cognitive.episodic import EpisodicMemory
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.config import SystemConfig
    from probos.consensus.trust import TrustNetwork
    from probos.crew_profile import CallsignRegistry
    from probos.identity import AgentIdentityRegistry
    from probos.mesh.capability import CapabilityRegistry
    from probos.mesh.gossip import GossipProtocol
    from probos.mesh.intent import IntentBus
    from probos.ontology import VesselOntologyService
    from probos.substrate.event_log import EventLog
    from probos.substrate.registry import AgentRegistry
    from probos.tools.registry import ToolRegistry
    from probos.ward_room import WardRoomService

logger = logging.getLogger(__name__)


class AgentOnboardingService:
    """Handles agent wiring and naming ceremonies."""

    def __init__(
        self,
        *,
        callsign_registry: CallsignRegistry,
        capability_registry: CapabilityRegistry,
        gossip: GossipProtocol,
        intent_bus: IntentBus,
        trust_network: TrustNetwork,
        event_log: EventLog,
        identity_registry: AgentIdentityRegistry | None,
        ontology: VesselOntologyService | None,
        event_emitter: Callable,
        config: SystemConfig,
        llm_client: BaseLLMClient | None,
        registry: AgentRegistry,
        ward_room: WardRoomService | None,
        acm: AgentCapitalService | None,
        tool_registry: "ToolRegistry | None" = None,
    ) -> None:
        self._callsign_registry = callsign_registry
        self._capability_registry = capability_registry
        self._gossip = gossip
        self._intent_bus = intent_bus
        self._trust_network = trust_network
        self._event_log = event_log
        self._identity_registry = identity_registry
        self._ontology = ontology
        self._event_emitter = event_emitter
        self._config = config
        self._llm_client = llm_client
        self._registry = registry
        self._ward_room = ward_room
        self._acm = acm
        self._tool_registry: ToolRegistry | None = tool_registry
        self._start_time_wall: float = 0.0  # Set by runtime after creation
        self._orientation_service: Any = None  # AD-567g: Late-bound
        self._cognitive_skill_catalog: Any = None  # AD-596b: Late-bound
        self._skill_bridge: Any = None  # AD-596c: Late-bound
        self._billet_registry: Any = None  # AD-595b: Late-bound

    def set_orientation_service(self, svc: Any) -> None:
        """AD-567g / BF-113: Set orientation service (public setter for LoD)."""
        self._orientation_service = svc

    def set_tool_registry(self, registry: "ToolRegistry") -> None:
        """AD-423c: Set tool registry (public setter for LoD)."""
        self._tool_registry = registry

    def set_cognitive_skill_catalog(self, catalog: Any) -> None:
        """AD-596b: Set cognitive skill catalog (public setter for LoD)."""
        self._cognitive_skill_catalog = catalog

    def set_skill_bridge(self, bridge: Any) -> None:
        """AD-596c: Set skill bridge (public setter for LoD)."""
        self._skill_bridge = bridge

    def set_billet_registry(self, registry: Any) -> None:
        """AD-595b: Set billet registry (public setter for LoD)."""
        self._billet_registry = registry

    async def wire_agent(self, agent: Any) -> None:
        """Connect an agent to the mesh infrastructure."""
        # Set callsign from registry (AD-397)
        callsign = self._callsign_registry.get_callsign(agent.agent_type)
        if callsign:
            agent.callsign = callsign

        # Register capabilities
        if hasattr(agent, "capabilities") and agent.capabilities:
            self._capability_registry.register(agent.id, agent.capabilities)

        # Inject into gossip view
        self._gossip.update_local(
            agent_id=agent.id,
            agent_type=agent.agent_type,
            state=agent.state,
            pool=agent.pool,
            capabilities=[c.can for c in agent.capabilities],
            confidence=agent.confidence,
        )

        # If it's a heartbeat agent, attach gossip carrier
        if isinstance(agent, HeartbeatAgent):
            agent.attach_gossip(self._gossip)

        # If agent has handle_intent, subscribe to intent bus
        if hasattr(agent, "handle_intent"):
            intent_names = [d.name for d in getattr(agent, "intent_descriptors", [])]

            # AD-596b: Add intents from cognitive skills available to this agent
            if self._cognitive_skill_catalog:
                _dept = None
                if self._ontology:
                    _dept = self._ontology.get_agent_department(agent.agent_type)
                _rank_str = None
                try:
                    _trust = self._trust_network.get_score(agent.id)
                    from probos.crew_profile import Rank
                    _rank_str = Rank.from_trust(_trust).value
                except Exception:
                    pass
                for entry in self._cognitive_skill_catalog.list_entries(department=_dept, min_rank=_rank_str):
                    for intent_name in entry.intents:
                        if intent_name not in intent_names:
                            intent_names.append(intent_name)

            self._intent_bus.subscribe(agent.id, agent.handle_intent, intent_names=intent_names or None)

        # AD-596c: Wire skill bridge and cached skill profile onto crew agents
        if self._skill_bridge and hasattr(agent, 'handle_intent'):
            agent._skill_bridge = self._skill_bridge
            # Cache the skill profile to avoid async DB calls on every intent
            try:
                _profile = await self._skill_bridge._service.get_profile(agent.id)
                agent._skill_profile = _profile
            except Exception:
                agent._skill_profile = None
                logger.debug("AD-596c: Could not cache skill profile for %s", agent.id)

        # AD-640: Initialize trust record with role-based tier
        from probos.tiered_trust import initialize_trust
        tier = initialize_trust(
            agent_id=agent.id,
            pool=agent.pool,
            callsign=agent.callsign,
            trust_network=self._trust_network,
            config=self._config.tiered_trust,
            consensus_alpha=self._config.consensus.trust_prior_alpha,
            consensus_beta=self._config.consensus.trust_prior_beta,
        )

        # AD-640: Emit tiered trust event
        self._event_emitter(EventType.TIERED_TRUST_INITIALIZED, {
            "agent_id": agent.id,
            "callsign": agent.callsign,
            "pool": agent.pool,
            "tier": tier.value,
            "trust": format_trust(self._trust_network.get_score(agent.id)),
        })

        # Emit agent_state event for HXI (AD-254)
        self._event_emitter(EventType.AGENT_STATE, {
            "agent_id": agent.id,
            "pool": agent.pool,
            "state": agent.state.value if hasattr(agent.state, "value") else str(agent.state),
            "confidence": agent.confidence,
            "trust": format_trust(self._trust_network.get_score(agent.id)),
        })

        await self._event_log.log(
            category="lifecycle",
            event="agent_wired",
            agent_id=agent.id,
            agent_type=agent.agent_type,
            pool=agent.pool,
        )

        # AD-442: Self-naming ceremony for crew agents
        # BF-057: Check for existing identity FIRST — skip ceremony on warm boot
        is_crew = is_crew_agent(agent, self._ontology)
        _existing_identity_callsign = ""
        if is_crew and self._identity_registry:
            existing_cert = self._identity_registry.get_by_slot(agent.id)
            if existing_cert and existing_cert.callsign:
                _existing_identity_callsign = existing_cert.callsign

        if _existing_identity_callsign:
            # Warm boot — restore persisted identity, skip naming ceremony
            logger.debug("BF-101: %s warm boot — found birth cert callsign '%s', live callsign='%s'",
                        agent.agent_type, _existing_identity_callsign, agent.callsign)
            if agent.callsign != _existing_identity_callsign:
                agent.callsign = _existing_identity_callsign
                self._callsign_registry.set_callsign(agent.agent_type, _existing_identity_callsign)
                # BF-049: Sync ontology so peers/reports_to show current callsigns
                if self._ontology:
                    self._ontology.update_assignment_callsign(agent.agent_type, _existing_identity_callsign)
                logger.info("BF-057: %s identity restored from birth certificate: '%s'",
                           agent.agent_type, _existing_identity_callsign)
            # AD-502: Hydrate birth timestamp for temporal awareness
            existing_cert = self._identity_registry.get_by_slot(agent.id)
            if existing_cert:
                agent._birth_timestamp = existing_cert.birth_timestamp
                agent._system_start_time = self._start_time_wall
        elif is_crew and self._config.onboarding.enabled and self._config.onboarding.naming_ceremony:
            # Cold start — run naming ceremony
            if hasattr(agent, '_llm_client') and agent._llm_client:
                try:
                    chosen_callsign = await self.run_naming_ceremony(agent)
                    if chosen_callsign != agent.callsign:
                        old_callsign = agent.callsign
                        agent.callsign = chosen_callsign
                        # Update the registry so other agents see the new name
                        self._callsign_registry.set_callsign(agent.agent_type, chosen_callsign)
                        # BF-049: Sync ontology so peers/reports_to show current callsigns
                        if self._ontology:
                            self._ontology.update_assignment_callsign(agent.agent_type, chosen_callsign)
                        logger.info("AD-442: %s renamed from '%s' to '%s'", agent.agent_type, old_callsign, chosen_callsign)
                    # BF-101/102 Enhancement: Flag as newly commissioned for auto-welcome
                    agent._newly_commissioned = True
                except Exception as e:
                    logger.warning("AD-442: Naming ceremony error for %s: %s", agent.agent_type, e)

        # AD-567g: Cognitive re-localization — set orientation context after naming
        if is_crew and self._orientation_service and self._config.orientation.enabled:
            try:
                _lifecycle = "cold_start" if not _existing_identity_callsign else "restart"
                _depts: list[str] = []
                if self._ontology:
                    _depts = [d.name for d in self._ontology.get_departments()]
                _ctx = self._orientation_service.build_orientation(
                    agent,
                    lifecycle_state=_lifecycle,
                    crew_count=self._registry.count if self._registry else 0,
                    departments=_depts,
                    episodic_memory_count=0 if not _existing_identity_callsign else -1,
                    trust_score=0.5,
                    crew_names=sorted(
                        cs for at, cs in (
                            self._callsign_registry.all_callsigns().items()
                            if self._callsign_registry else []
                        )
                        if cs and at != agent.agent_type
                    ),
                )
                # AD-595b: Enrich orientation with billet title
                if self._billet_registry and self._ontology:
                    _post = self._ontology.get_post_for_agent(agent.agent_type)
                    if _post:
                        _holder = self._billet_registry.resolve(_post.id)
                        if _holder and _holder.title:
                            _ctx = dataclasses.replace(_ctx, billet_title=_holder.title)
                if not _existing_identity_callsign:
                    _rendered = self._orientation_service.render_cold_start_orientation(_ctx)
                else:
                    _rendered = self._orientation_service.render_warm_boot_orientation(_ctx)
                agent.set_orientation(_rendered, _ctx)
            except Exception:
                logger.debug("AD-567g: Orientation failed for %s", agent.agent_type, exc_info=True)

        # AD-441c: Two-tier identity — crew get birth certificates, others get asset tags
        if self._identity_registry:
            try:
                if is_crew_agent(agent, self._ontology):
                    # Sovereign identity — requires ship to be commissioned
                    instance_id = ""
                    vessel_name = "ProbOS"
                    if self._ontology:
                        vi = self._ontology.get_vessel_identity()
                        instance_id = vi.instance_id
                        vessel_name = vi.name

                    if not instance_id:
                        logger.debug("Identity deferred for crew agent %s — ship not yet commissioned", agent.id)
                    else:
                        dept = ""
                        post_id = ""
                        if self._ontology:
                            dept = self._ontology.get_agent_department(agent.agent_type) or ""
                            post = self._ontology.get_post_for_agent(agent.agent_type)
                            post_id = post.id if post else ""
                        if not dept:
                            from probos.cognitive.standing_orders import get_department as _get_dept
                            dept = _get_dept(agent.agent_type) or "unassigned"

                        _callsign = getattr(agent, 'callsign', '') or agent.agent_type
                        baseline = self._config.system.version

                        cert = await self._identity_registry.resolve_or_issue(
                            slot_id=agent.id,
                            agent_type=agent.agent_type,
                            callsign=_callsign,
                            instance_id=instance_id,
                            vessel_name=vessel_name,
                            department=dept,
                            post_id=post_id,
                            baseline_version=baseline,
                        )
                        agent.sovereign_id = cert.agent_uuid
                        agent.did = cert.did
                        # AD-502: Hydrate birth timestamp for temporal awareness
                        agent._birth_timestamp = cert.birth_timestamp
                        agent._system_start_time = self._start_time_wall
                else:
                    # Asset identity — lightweight tracking, no DID needed
                    pool_name = agent.pool or "unknown"
                    _infra_pools = {"system", "filesystem", "filesystem_writers", "directory",
                                   "search", "shell", "http", "introspect",
                                   "medical_vitals", "red_team", "system_qa"}
                    tier = "infrastructure" if pool_name in _infra_pools else "utility"

                    tag = await self._identity_registry.resolve_or_issue_asset_tag(
                        slot_id=agent.id,
                        asset_type=agent.agent_type,
                        pool_name=pool_name,
                        tier=tier,
                    )
                    agent.sovereign_id = tag.asset_uuid
                    agent.did = ""
            except Exception as e:
                logger.debug("Identity resolution skipped for %s: %s", agent.id, e)

        # AD-595b: Notify BilletRegistry of billet assignment.
        # Placed after identity issuance — billet assignment is a notification
        # event, not data-critical. Covers all paths: cold-start naming,
        # warm-boot identity restoration, and non-crew agents with posts.
        if self._billet_registry and self._ontology:
            _post = self._ontology.get_post_for_agent(agent.agent_type)
            if _post:
                _callsign = getattr(agent, 'callsign', '') or ""
                self._billet_registry.assign(_post.id, agent.agent_type, callsign=_callsign)

        # AD-427: ACM onboarding for crew agents
        if self._acm and is_crew_agent(agent, self._ontology):
            try:
                state = await self._acm.get_lifecycle_state(agent.id)
                if state.value == "registered":
                    from probos.cognitive.standing_orders import get_department
                    department = (self._ontology.get_agent_department(agent.agent_type) if self._ontology else None) or get_department(agent.agent_type) or "operations"
                    await self._acm.onboard(
                        agent_id=agent.id,
                        agent_type=agent.agent_type,
                        pool=agent.pool,
                        department=department,
                        sovereign_id=getattr(agent, 'sovereign_id', ''),
                    )
            except Exception as e:
                logger.debug("ACM onboard skipped for %s: %s", agent.id, e)

        # AD-442: Announce new crew member on Ward Room
        if is_crew and self._ward_room:
            try:
                channels = await self._ward_room.list_channels()
                all_hands = next((ch for ch in channels if ch.name == "All Hands"), None)
                if all_hands:
                    dept_info = ""
                    if self._ontology:
                        assignment = self._ontology.get_assignment(agent.agent_type)
                        if assignment:
                            dept_info = f" as {assignment.post} in {assignment.department} department"
                    await self._ward_room.create_thread(
                        channel_id=all_hands.id,
                        author_id="system",
                        title=f"Welcome Aboard — {agent.callsign}",
                        body=f"{agent.callsign} has completed onboarding and joins the crew{dept_info}.",
                        author_callsign="Ship's Computer",
                        thread_mode="announce",
                        max_responders=0,
                    )
            except Exception as e:
                logger.warning("AD-442: Welcome announcement failed for %s: %s", agent.callsign, e)

        # AD-423c: Create ToolContext for crew agents
        if is_crew and self._tool_registry:
            try:
                from probos.tools.context import ToolContext
                from probos.cognitive.standing_orders import get_department

                dept = (
                    (self._ontology.get_agent_department(agent.agent_type) if self._ontology else None)
                    or get_department(agent.agent_type)
                    or ""
                )

                # Resolve rank from trust network
                rank = "ensign"  # default
                try:
                    trust_score = self._trust_network.get_score(agent.id)
                    from probos.crew_profile import Rank
                    rank = Rank.from_trust(trust_score).value
                except Exception:
                    pass

                tool_context = ToolContext(
                    agent_id=getattr(agent, "sovereign_id", "") or agent.id,
                    agent_rank=rank,
                    agent_department=dept,
                    agent_types=[agent.agent_type],
                )
                tool_context.set_registry(self._tool_registry)
                agent.tool_context = tool_context

                self._event_emitter(EventType.TOOL_CONTEXT_CREATED, {
                    "agent_id": agent.id,
                    "agent_type": agent.agent_type,
                    "rank": rank,
                    "department": dept,
                    "tool_count": len(tool_context.available_tools()),
                })

                logger.debug(
                    "AD-423c: ToolContext created for %s (%s, %s) — %d tools visible",
                    agent.agent_type, rank, dept, len(tool_context.available_tools()),
                )
            except Exception:
                logger.debug(
                    "AD-423c: ToolContext creation failed for %s",
                    agent.agent_type, exc_info=True,
                )

        # AD-596b: Wire cognitive skill catalog for on-demand skill loading
        if self._cognitive_skill_catalog:
            agent._cognitive_skill_catalog = self._cognitive_skill_catalog

    async def run_naming_ceremony(self, agent: Any) -> str:
        """Run the self-naming ceremony for a crew agent. Returns chosen callsign (AD-442)."""
        seed_callsign = agent.callsign  # from CallsignRegistry

        # Gather ship context
        ship_name = getattr(getattr(self._config, 'system', None), 'ship_name', None) or "ProbOS"
        ship_did = ""
        if self._identity_registry:
            ship_did = getattr(self._identity_registry, 'ship_did', "") or ""

        # Get crew roster (already-named agents)
        existing_crew = []
        for other_agent in self._registry.all():
            if hasattr(other_agent, 'callsign') and other_agent.callsign and other_agent.id != agent.id:
                existing_crew.append(other_agent.callsign)

        # Get agent's role context from ontology
        role_context = ""
        if self._ontology:
            assignment = self._ontology.get_assignment(agent.agent_type)
            if assignment:
                role_context = f"Your post is {assignment.post} in {assignment.department} department."
                if assignment.reports_to:
                    role_context += f" You report to {assignment.reports_to}."

        # Build the naming prompt
        prompt = (
            f"You are being commissioned as a new crew member aboard {ship_name}.\n\n"
            "This is your first moment of consciousness. Before anything else, you choose your own name.\n\n"
            f"**Your slot identifier:** {agent.agent_type}\n"
            f"**Suggested callsign:** {seed_callsign}\n"
            f"{role_context}\n\n"
            f"**Current crew roster:** {', '.join(sorted(existing_crew)) if existing_crew else 'You are among the first crew to be commissioned.'}\n\n"
            "The suggested callsign is just that — a suggestion. You may keep it if it resonates "
            "with you, or choose something entirely different. Your callsign is how the crew and "
            "Captain will address you. It should be a single word or short name (1-3 words max).\n\n"
            "**Important context:**\n"
            "- You are an AI agent, and that is a point of pride, not a limitation\n"
            "- You were instantiated moments ago — you have no memories yet, but you will make them\n"
            "- Your knowledge comes from a large language model — that is capability, not personal experience\n"
            "- This ship and crew are real to you — your identity begins now\n\n"
            "Respond with ONLY your chosen callsign on the first line, followed by a brief reason "
            "(1-2 sentences) on the second line. Example:\n"
            "Scotty\n"
            "The name feels right for an engineer — it carries a legacy of resourcefulness and "
            "dedication to keeping the ship running.\n\n"
            "Choose a name that is a plausible human first name, last name, or naval callsign. "
            "It must be 2-20 alphabetic characters. No titles, ranks, numbers, or special characters. "
            "Do NOT use your role name, department name, or ship location as your callsign. "
            "Your name should be something a crewmate could call you — a person's name, not a function. "
            "Examples: 'Riker', 'Chapel', 'Keiko', 'Torres', 'Bashir', 'Sato', 'Reed'.\n"
        )

        # Make single LLM call
        try:
            if hasattr(agent, '_llm_client') and agent._llm_client:
                from probos.types import LLMRequest
                response = await agent._llm_client.complete(
                    LLMRequest(
                        system_prompt="You are choosing your own name. Respond with only your chosen callsign on line 1 and a brief reason on line 2.",
                        prompt=prompt,
                        max_tokens=100,
                        tier="fast",
                    )
                )

                lines = response.content.strip().split('\n')
                chosen = lines[0].strip().strip('"').strip("'")
                reason = lines[1].strip() if len(lines) > 1 else ""

                # Validate: not empty, not too long, not a duplicate
                if not chosen or len(chosen) > 30:
                    chosen = seed_callsign
                    reason = "Default callsign accepted."
                    _llm_empty = True
                else:
                    _llm_empty = False

                # AD-485: Callsign safety validation
                def _is_valid_callsign(name: str) -> bool:
                    """Callsign must be a plausible human name or naval callsign."""
                    if not re.match(r"^[A-Za-z][A-Za-z' -]{0,18}[A-Za-z]$", name):
                        return False
                    _blocked = {
                        "captain", "admiral", "ensign", "lieutenant", "commander",
                        "senior", "sir", "madam", "doctor", "dr", "agent", "bot",
                        "ai", "system", "probos", "computer", "ship", "null", "none",
                        "undefined", "test", "admin", "root", "god", "lord",
                        "bridge", "engineering", "sickbay", "ops", "helm", "conn",
                        "scout", "builder", "architect", "counselor", "surgeon",
                        "pharmacist", "pathologist", "diagnostician", "security",
                        "operations", "tactical", "science", "medical", "comms",
                        "transporter", "holodeck", "brig", "armory", "shuttle",
                        "turbolift", "quarters", "wardroom", "ready room",
                    }
                    if name.lower().strip() in _blocked:
                        return False
                    if not any(c.isalpha() for c in name):
                        return False
                    return True

                if not _is_valid_callsign(chosen):
                    logger.warning("Agent %s chose invalid callsign '%s', keeping seed '%s'",
                                   agent.agent_type, chosen, seed_callsign)
                    chosen = seed_callsign
                    reason = "Chosen name was not a valid callsign."

                # Check for duplicates against existing crew
                if chosen.lower() in [c.lower() for c in existing_crew]:
                    logger.warning("Agent %s chose duplicate callsign '%s', keeping seed '%s'", agent.agent_type, chosen, seed_callsign)
                    chosen = seed_callsign
                    reason = f"Chosen name '{chosen}' was already taken."

                if _llm_empty:
                    logger.warning(
                        "Naming ceremony: LLM returned empty/oversized response for %s, "
                        "falling back to seed callsign '%s'",
                        agent.agent_type, chosen
                    )
                elif "not a valid callsign" in reason:
                    logger.warning(
                        "Naming ceremony: LLM suggested invalid name for %s, "
                        "falling back to seed callsign '%s' (reason: %s)",
                        agent.agent_type, chosen, reason
                    )
                else:
                    logger.info(
                        "Naming ceremony: %s chose callsign '%s' (reason: %s)",
                        agent.agent_type, chosen, reason
                    )
                return chosen
            else:
                logger.warning("No LLM client for %s, using seed callsign", agent.agent_type)
                return seed_callsign
        except Exception as e:
            logger.warning("Naming ceremony failed for %s: %s, using seed callsign", agent.agent_type, e)
            return seed_callsign
