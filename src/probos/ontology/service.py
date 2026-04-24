"""VesselOntologyService facade — thin delegation layer over sub-services.

Ship's Computer infrastructure service (no sovereign identity).
Loads ontology schema from config/ontology/*.yaml, builds in-memory
graph at startup, provides query methods for runtime use.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from probos.ontology.billet_registry import BilletRegistry
from probos.ontology.departments import DepartmentService
from probos.ontology.loader import OntologyLoader
from probos.ontology.models import (
    AlertProcedure,
    Assignment,
    ChannelTypeSchema,
    Department,
    DocumentClass,
    DocumentClassification,
    DocumentField,
    DutyCategory,
    KnowledgeSourceSchema,
    KnowledgeTier,
    MessagePattern,
    ModelTier,
    Post,
    PostCapability,
    QualificationPath,
    RepositoryDirectory,
    RetentionPolicy,
    RoleTemplate,
    StandingOrderTier,
    ToolCapability,
    VesselIdentity,
    VesselState,
    WatchTypeSchema,
)
from probos.ontology.ranks import RankService


class VesselOntologyService:
    """Ship's Computer service — unified formal model of the vessel.

    Thin facade that delegates to OntologyLoader, DepartmentService,
    and RankService.
    """

    def __init__(self, config_dir: Path, data_dir: Path | None = None) -> None:
        self._loader = OntologyLoader(config_dir, data_dir)
        self._dept: DepartmentService | None = None
        self._billet_registry: BilletRegistry | None = None  # AD-595a
        self._ranks: RankService | None = None

    async def initialize(self) -> None:
        """Load YAML schemas and wire sub-services."""
        await self._loader.initialize()
        self._dept = DepartmentService(
            self._loader.departments,
            self._loader.posts,
            self._loader.assignments,
        )
        # AD-595a: Build BilletRegistry eagerly (no lazy init — avoids race)
        self._billet_registry = BilletRegistry(self._dept)
        self._ranks = RankService(
            self._loader.role_templates,
            self._loader.qualification_paths,
            self._loader.assignments,
        )

    @property
    def billet_registry(self) -> "BilletRegistry | None":
        """AD-595a: Billet resolution facade."""
        return self._billet_registry

    # -------------------------------------------------------------------
    # Vessel queries (kept on facade — trivial getters)
    # -------------------------------------------------------------------

    def get_vessel_identity(self) -> VesselIdentity:
        if self._loader.vessel_identity is None:
            return VesselIdentity(
                name="ProbOS", version="0.0.0", description="",
                instance_id="unknown", started_at=self._loader.started_at,
            )
        return self._loader.vessel_identity

    def get_vessel_state(self) -> VesselState:
        crew_count = sum(1 for a in self._loader.assignments.values() if a.agent_id is not None)
        return VesselState(
            alert_condition=self._loader.alert_condition,
            uptime_seconds=time.time() - self._loader.started_at,
            active_crew_count=crew_count,
        )

    def get_alert_condition(self) -> str:
        return self._loader.alert_condition

    def set_alert_condition(self, condition: str) -> None:
        if condition not in self._loader.valid_alert_conditions:
            raise ValueError(f"Invalid alert condition: {condition}. Valid: {self._loader.valid_alert_conditions}")
        self._loader.alert_condition = condition

    # -------------------------------------------------------------------
    # Department queries (delegated)
    # -------------------------------------------------------------------

    def get_departments(self) -> list[Department]:
        return self._dept.get_departments()  # type: ignore[union-attr]

    def get_department(self, dept_id: str) -> Department | None:
        return self._dept.get_department(dept_id)  # type: ignore[union-attr]

    def get_posts(self, department_id: str | None = None) -> list[Post]:
        return self._dept.get_posts(department_id)  # type: ignore[union-attr]

    def get_post(self, post_id: str) -> Post | None:
        return self._dept.get_post(post_id)  # type: ignore[union-attr]

    def get_chain_of_command(self, post_id: str) -> list[Post]:
        return self._dept.get_chain_of_command(post_id)  # type: ignore[union-attr]

    def get_direct_reports(self, post_id: str) -> list[Post]:
        return self._dept.get_direct_reports(post_id)  # type: ignore[union-attr]

    def get_post_capabilities(self, post_id: str) -> list[PostCapability]:
        """AD-648: Return structured capabilities for a post."""
        post = self._loader.posts.get(post_id)
        if not post:
            return []
        return list(post.capabilities)

    def get_agent_capabilities(self, agent_type: str) -> list[PostCapability]:
        """AD-648: Return capabilities for the post an agent fills."""
        assignment = self._loader.assignments.get(agent_type)
        if not assignment:
            return []
        return self.get_post_capabilities(assignment.post_id)

    def get_post_negative_grounding(self, post_id: str) -> list[str]:
        """AD-648: Return 'does not have' list for a post."""
        post = self._loader.posts.get(post_id)
        if not post:
            return []
        return list(post.does_not_have)

    def get_all_assignments(self) -> list[Assignment]:
        return self._dept.get_all_assignments()  # type: ignore[union-attr]

    def get_assignment_for_agent(self, agent_type: str) -> Assignment | None:
        return self._dept.get_assignment_for_agent(agent_type)  # type: ignore[union-attr]

    def get_agent_department(self, agent_type: str) -> str | None:
        return self._dept.get_agent_department(agent_type)  # type: ignore[union-attr]

    def get_crew_agent_types(self) -> set[str]:
        return self._dept.get_crew_agent_types()  # type: ignore[union-attr]

    def get_post_for_agent(self, agent_type: str) -> Post | None:
        return self._dept.get_post_for_agent(agent_type)  # type: ignore[union-attr]

    def wire_agent(self, agent_type: str, agent_id: str) -> None:
        self._dept.wire_agent(agent_type, agent_id)  # type: ignore[union-attr]

    def update_assignment_callsign(self, agent_type: str, new_callsign: str) -> bool:
        return self._dept.update_assignment_callsign(agent_type, new_callsign)  # type: ignore[union-attr]

    def get_assignment_for_agent_by_id(self, agent_id: str) -> Assignment | None:
        return self._dept.get_assignment_for_agent_by_id(agent_id)  # type: ignore[union-attr]

    def get_subordinate_agent_types(self, agent_type: str) -> list[str]:
        """AD-630: Return agent_types of all direct reports for the given agent.

        Uses authority_over from ontology to find subordinate posts,
        then reverse-maps to agent assignments.

        Args:
            agent_type: The agent type (e.g., 'engineering_officer').

        Returns:
            List of agent_type strings for subordinates. Empty if not a chief.
        """
        post = self.get_post_for_agent(agent_type)
        if not post or not post.authority_over:
            return []
        result: list[str] = []
        for sub_post_id in post.authority_over:
            assignments = self._dept.get_agents_for_post(sub_post_id)  # type: ignore[union-attr]
            for a in assignments:
                result.append(a.agent_type)
        return result

    # -------------------------------------------------------------------
    # Rank queries (delegated)
    # -------------------------------------------------------------------

    def get_role_template(self, post_id: str) -> RoleTemplate | None:
        return self._ranks.get_role_template(post_id)  # type: ignore[union-attr]

    def get_role_template_for_agent(self, agent_type: str) -> RoleTemplate | None:
        return self._ranks.get_role_template_for_agent(agent_type)  # type: ignore[union-attr]

    def get_qualification_path(self, from_rank: str, to_rank: str) -> QualificationPath | None:
        return self._ranks.get_qualification_path(from_rank, to_rank)  # type: ignore[union-attr]

    def get_all_qualification_paths(self) -> list[QualificationPath]:
        return self._ranks.get_all_qualification_paths()  # type: ignore[union-attr]

    def set_skill_service(self, skill_service: Any) -> None:
        if self._ranks:
            self._ranks.set_skill_service(skill_service)
        self._loader_skill_service = skill_service

    # -------------------------------------------------------------------
    # Operations queries (kept on facade — trivial getters)
    # -------------------------------------------------------------------

    def get_standing_order_tiers(self) -> list[StandingOrderTier]:
        return list(self._loader.standing_order_tiers)

    def get_watch_types(self) -> list[WatchTypeSchema]:
        return list(self._loader.watch_types)

    def get_alert_procedure(self, condition: str) -> AlertProcedure | None:
        return self._loader.alert_procedures.get(condition)

    def get_duty_categories(self) -> list[DutyCategory]:
        return list(self._loader.duty_categories)

    # -------------------------------------------------------------------
    # Communication queries (kept on facade — trivial getters)
    # -------------------------------------------------------------------

    def get_channel_types(self) -> list[ChannelTypeSchema]:
        return list(self._loader.channel_types)

    def get_thread_modes(self) -> list:
        return list(self._loader.thread_modes)

    def get_thread_mode(self, mode_id: str) -> Any:
        for tm in self._loader.thread_modes:
            if tm.id == mode_id:
                return tm
        return None

    def get_message_patterns(self) -> list[MessagePattern]:
        return list(self._loader.message_patterns)

    # -------------------------------------------------------------------
    # Resources queries (kept on facade — trivial getters)
    # -------------------------------------------------------------------

    def get_model_tiers(self) -> list[ModelTier]:
        return list(self._loader.model_tiers)

    def get_model_tier(self, tier_id: str) -> ModelTier | None:
        for mt in self._loader.model_tiers:
            if mt.id == tier_id:
                return mt
        return None

    def get_tool_capabilities(self, available_to: str | None = None) -> list[ToolCapability]:
        if available_to is None:
            return list(self._loader.tool_capabilities)
        return [t for t in self._loader.tool_capabilities if t.available_to == available_to]

    def get_knowledge_sources(self) -> list[KnowledgeSourceSchema]:
        return list(self._loader.knowledge_sources)

    # -------------------------------------------------------------------
    # Records queries (kept on facade — trivial getters)
    # -------------------------------------------------------------------

    def get_knowledge_tiers(self) -> list[KnowledgeTier]:
        return list(self._loader.knowledge_tiers)

    def get_knowledge_tier(self, tier: int) -> KnowledgeTier | None:
        for kt in self._loader.knowledge_tiers:
            if kt.tier == tier:
                return kt
        return None

    def get_classifications(self) -> list[DocumentClassification]:
        return list(self._loader.classifications)

    def get_document_classes(self) -> list[DocumentClass]:
        return list(self._loader.document_classes)

    def get_document_class(self, class_id: str) -> DocumentClass | None:
        for dc in self._loader.document_classes:
            if dc.id == class_id:
                return dc
        return None

    def get_retention_policies(self) -> list[RetentionPolicy]:
        return list(self._loader.retention_policies)

    def get_retention_policy(self, policy_id: str) -> RetentionPolicy | None:
        for rp in self._loader.retention_policies:
            if rp.id == policy_id:
                return rp
        return None

    def get_repository_structure(self) -> list[RepositoryDirectory]:
        return list(self._loader.repository_directories)

    # -------------------------------------------------------------------
    # Crew context assembly (cross-cutting, kept on facade)
    # -------------------------------------------------------------------

    def get_crew_context(self, agent_type: str) -> dict[str, Any] | None:
        """Assemble full crew context for an agent — post, department, chain of command,
        peers, reports. Used by _gather_context() in proactive loop."""
        assignment = self._loader.assignments.get(agent_type)
        if not assignment:
            return None

        post = self._loader.posts.get(assignment.post_id)
        if not post:
            return None

        dept = self._loader.departments.get(post.department_id)

        # Chain of command
        chain = self.get_chain_of_command(post.id)
        chain_titles: list[str] = [p.title for p in chain]

        # Reports to
        reports_to_str = ""
        if post.reports_to:
            superior = self._loader.posts.get(post.reports_to)
            if superior:
                sup_callsign = ""
                for a in self._loader.assignments.values():
                    if a.post_id == superior.id:
                        sup_callsign = a.callsign
                        break
                reports_to_str = f"{superior.title}"
                if sup_callsign:
                    reports_to_str += f" ({sup_callsign})"

        # Direct reports
        direct_reports = self.get_direct_reports(post.id)
        direct_report_titles: list[str] = [dr.title for dr in direct_reports]

        # Peers (other crew in same department, excluding self)
        dept_posts = self.get_posts(department_id=post.department_id)
        peers: list[str] = []
        for dp in dept_posts:
            if dp.id == post.id:
                continue
            peer_callsign = ""
            for a in self._loader.assignments.values():
                if a.post_id == dp.id:
                    peer_callsign = a.callsign
                    break
            label = dp.title
            if peer_callsign:
                label += f" ({peer_callsign})"
            peers.append(label)

        # Adjacent departments
        adjacent_departments: list[str] = []
        if post.reports_to:
            superior = self._loader.posts.get(post.reports_to)
            if superior:
                for sub_post_id in superior.authority_over:
                    sub_post = self._loader.posts.get(sub_post_id)
                    if sub_post and sub_post.department_id != post.department_id:
                        sub_dept = self._loader.departments.get(sub_post.department_id)
                        if sub_dept and sub_dept.name not in adjacent_departments:
                            adjacent_departments.append(sub_dept.name)

        vessel = self.get_vessel_identity()

        context: dict[str, Any] = {
            "vessel": {
                "name": vessel.name,
                "version": vessel.version,
                "alert_condition": self._loader.alert_condition,
            },
            "identity": {
                "agent_type": agent_type,
                "callsign": assignment.callsign,
                "post": post.title,
            },
            "department": {
                "id": post.department_id,
                "name": dept.name if dept else post.department_id,
            },
            "chain_of_command": chain_titles,
            "reports_to": reports_to_str,
            "direct_reports": direct_report_titles,
            "peers": peers,
            "adjacent_departments": adjacent_departments,
        }

        # Skills context (AD-429b)
        role_template = self.get_role_template(assignment.post_id)
        if role_template:
            context["role_requirements"] = {
                "required": [
                    {"skill": r.skill_id, "min_level": r.min_proficiency}
                    for r in role_template.required_skills
                ],
                "optional": [
                    {"skill": o.skill_id, "min_level": o.min_proficiency}
                    for o in role_template.optional_skills
                ],
            }
        if self._ranks and self._ranks._skill_service:
            context["skills_note"] = (
                "Your full skill profile is tracked by the Skill Framework. "
                "Role requirements above show what your post demands."
            )

        # Operations context (AD-429c)
        if self._loader.alert_procedures:
            context["alert_condition"] = self._loader.alert_condition
            proc = self.get_alert_procedure(self._loader.alert_condition)
            if proc:
                context["alert_procedure"] = proc.description

        # Communication context (AD-429c)
        if self._loader.message_patterns:
            context["available_actions"] = [
                {"tag": p.tag, "description": p.description}
                for p in self._loader.message_patterns
                if p.min_rank is None
            ]

        # Records context (AD-429d)
        if self._loader.knowledge_tiers:
            context["knowledge_model"] = {
                "tiers": [
                    {"tier": kt.tier, "name": kt.name, "access": kt.access}
                    for kt in self._loader.knowledge_tiers
                ],
                "note": "Tier 1 (Experience) is your episodic memory. Tier 2 (Records) is the ship's shared knowledge. Tier 3 (Operational State) is infrastructure.",
            }

        # AD-648: Post capability profiles — confabulation prevention
        if post.capabilities:
            context["capabilities"] = [
                {
                    "id": cap.id,
                    "summary": cap.summary,
                    "tools": cap.tools,
                    "outputs": cap.outputs,
                }
                for cap in post.capabilities
            ]
        if post.does_not_have:
            context["does_not_have"] = list(post.does_not_have)

        return context

    # -------------------------------------------------------------------
    # Crew manifest (AD-513)
    # -------------------------------------------------------------------

    def get_crew_manifest(
        self,
        *,
        department: str | None = None,
        trust_network: Any | None = None,
        callsign_registry: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Assemble live crew roster from ship subsystems.

        Returns one entry per crew agent with fields:
          agent_type, callsign, department, post, rank, trust_score, agent_id.

        Enrichment sources are optional — omit for a minimal roster.
        """
        from probos.crew_profile import Rank

        crew_types = self.get_crew_agent_types()
        manifest: list[dict[str, Any]] = []

        for agent_type in sorted(crew_types):
            assignment = self.get_assignment_for_agent(agent_type)
            if not assignment:
                continue

            post = self.get_post(assignment.post_id) if assignment.post_id else None
            dept_id = self.get_agent_department(agent_type) or ""

            entry: dict[str, Any] = {
                "agent_type": agent_type,
                "callsign": assignment.callsign,
                "department": dept_id,
                "post": post.title if post else "",
                "agent_id": assignment.agent_id or "",
            }

            # Enrich with callsign registry (live callsign may differ)
            if callsign_registry:
                live_cs = callsign_registry.get_callsign(agent_type)
                if live_cs:
                    entry["callsign"] = live_cs

            # Enrich with trust score + rank
            if trust_network and assignment.agent_id:
                try:
                    trust_score = trust_network.get_score(assignment.agent_id)
                    entry["trust_score"] = round(trust_score, 3)
                    entry["rank"] = Rank.from_trust(trust_score).value
                except Exception:
                    entry["trust_score"] = 0.5
                    entry["rank"] = Rank.ENSIGN.value
            else:
                entry["trust_score"] = 0.5
                entry["rank"] = Rank.ENSIGN.value

            manifest.append(entry)

        if department:
            manifest = [e for e in manifest if e["department"] == department]

        return manifest
