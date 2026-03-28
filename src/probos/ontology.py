"""AD-429a: Vessel Ontology Foundation — unified formal model of the vessel.

Ship's Computer infrastructure service (no sovereign identity).
Loads ontology schema from config/ontology/*.yaml, builds in-memory
graph at startup, provides query methods for runtime use.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Department:
    id: str
    name: str
    description: str


@dataclass
class Post:
    id: str
    title: str
    department_id: str
    reports_to: str | None  # post_id
    authority_over: list[str] = field(default_factory=list)  # post_ids
    tier: str = "crew"  # "crew", "utility", "infrastructure", "external"


@dataclass
class Assignment:
    agent_type: str
    post_id: str
    callsign: str
    agent_id: str | None = None  # Filled at runtime when agent wires


@dataclass
class VesselIdentity:
    name: str
    version: str
    description: str
    instance_id: str  # UUID, generated once, persisted
    started_at: float = 0.0  # time.time() at boot


@dataclass
class VesselState:
    alert_condition: str  # GREEN, YELLOW, RED
    uptime_seconds: float
    active_crew_count: int


# --- Skills domain (AD-429b) ---

@dataclass
class SkillRequirement:
    """A single skill requirement within a role template."""
    skill_id: str
    min_proficiency: int  # ProficiencyLevel value (1-7)


@dataclass
class RoleTemplate:
    """Required and optional skills for a post. Loaded from skills.yaml."""
    post_id: str
    required_skills: list[SkillRequirement] = field(default_factory=list)
    optional_skills: list[SkillRequirement] = field(default_factory=list)


@dataclass
class QualificationRequirement:
    """A single requirement within a qualification path."""
    type: str  # "pcc_minimum", "role_minimum", "role_depth"
    description: str
    min_proficiency: int
    scope: str  # "all_pccs", "role_skills", "required_role_skills"
    min_count: int | None = None  # For "role_depth" type


@dataclass
class QualificationPath:
    """Requirements for a rank transition."""
    from_rank: str  # e.g., "ensign"
    to_rank: str    # e.g., "lieutenant"
    description: str
    requirements: list[QualificationRequirement] = field(default_factory=list)



# --- Operations domain (AD-429c) ---

@dataclass
class StandingOrderTier:
    """One tier of the standing orders hierarchy."""
    tier: float  # 1, 1.5, 2, 3, 4, 5, 6
    name: str
    source: str
    scope: str  # "universal", "ship", "department", "individual"
    mutable: bool
    description: str


@dataclass
class WatchTypeSchema:
    """Watch type definition from ontology."""
    id: str  # "alpha", "beta", "gamma"
    name: str
    description: str
    staffing: str  # "full", "reduced", "minimal"


@dataclass
class AlertProcedure:
    """Operational procedures for an alert condition level."""
    condition: str  # "GREEN", "YELLOW", "RED"
    description: str
    watch_default: str
    proactive_interval: str
    escalation_threshold: str
    actions: list[str] = field(default_factory=list)


@dataclass
class DutyCategory:
    """Category grouping for duty types."""
    id: str
    name: str
    description: str
    examples: list[str] = field(default_factory=list)


# --- Communication domain (AD-429c) ---

@dataclass
class ChannelTypeSchema:
    """Channel type definition from ontology."""
    id: str  # "ship", "department", "dm", "custom"
    name: str
    description: str
    default_mode: str


@dataclass
class ThreadModeSchema:
    """Thread mode definition from ontology."""
    id: str  # "inform", "discuss", "action", "announce"
    name: str
    description: str
    reply_expected: bool
    routing: str  # "none", "department_preference", "competency_based"
    use_cases: list[str] = field(default_factory=list)


@dataclass
class MessagePattern:
    """Structured message pattern used in Ward Room communication."""
    id: str
    tag: str
    description: str
    expected_from: str
    min_rank: str | None = None


# --- Resources domain (AD-429c) ---

@dataclass
class ModelTier:
    """LLM model tier definition."""
    id: str  # "fast", "standard", "deep"
    name: str
    description: str
    default_model: str
    use_cases: list[str] = field(default_factory=list)


@dataclass
class ToolCapability:
    """A capability an agent can invoke."""
    id: str
    name: str
    description: str
    provider: str
    available_to: str  # "all_crew", "lieutenant_plus", etc.
    gated_by: str | None = None


@dataclass
class KnowledgeSourceSchema:
    """Knowledge source type in the three-tier knowledge model."""
    id: str
    name: str
    description: str
    tier: int
    tier_name: str
    storage: str
    access: str


# --- Records domain (AD-429d) ---

@dataclass
class KnowledgeTier:
    """One tier of the three-tier knowledge model."""
    tier: int
    name: str
    store: str
    description: str
    access: str
    persistence: str
    promotion_path: str | None


@dataclass
class DocumentClassification:
    """Document access control classification."""
    id: str  # "private", "department", "ship", "fleet"
    name: str
    description: str
    access_scope: str


@dataclass
class DocumentClass:
    """Category of ship's record."""
    id: str  # "captains_log", "notebook", "report", etc.
    name: str
    description: str
    classification_default: str
    retention: str  # retention policy id
    format: str
    special_rules: list[str] = field(default_factory=list)


@dataclass
class RetentionPolicy:
    """Retention and archival policy for a document class."""
    id: str
    name: str
    description: str
    archive_after_days: int | None
    delete_after_days: int | None
    applies_to: list[str] = field(default_factory=list)


@dataclass
class DocumentField:
    """A field in the document frontmatter schema."""
    name: str
    type: str
    description: str
    values: list[str] | None = None
    default: str | None = None


@dataclass
class RepositoryDirectory:
    """A directory in the records repository structure."""
    path: str
    description: str


# ---------------------------------------------------------------------------
# VesselOntologyService
# ---------------------------------------------------------------------------

class VesselOntologyService:
    """Ship's Computer service — unified formal model of the vessel.

    Loads ontology schema from config/ontology/*.yaml, builds in-memory
    graph at startup, provides query methods for runtime use.

    Infrastructure service (no sovereign identity).
    """

    def __init__(self, config_dir: Path, data_dir: Path | None = None) -> None:
        self._config_dir = config_dir
        self._data_dir = data_dir
        self._departments: dict[str, Department] = {}
        self._posts: dict[str, Post] = {}
        self._assignments: dict[str, Assignment] = {}  # keyed by agent_type
        self._vessel_identity: VesselIdentity | None = None
        self._alert_condition: str = "GREEN"
        self._valid_alert_conditions: list[str] = ["GREEN", "YELLOW", "RED"]
        self._started_at: float = time.time()
        # Skills domain (AD-429b)
        self._role_templates: dict[str, RoleTemplate] = {}  # keyed by post_id
        self._qualification_paths: dict[str, QualificationPath] = {}  # keyed by "from_to"
        self._skill_service: Any = None
        # Operations domain (AD-429c)
        self._standing_order_tiers: list[StandingOrderTier] = []
        self._watch_types: list[WatchTypeSchema] = []
        self._alert_procedures: dict[str, AlertProcedure] = {}
        self._duty_categories: list[DutyCategory] = []
        # Communication domain (AD-429c)
        self._channel_types: list[ChannelTypeSchema] = []
        self._thread_modes: list[ThreadModeSchema] = []
        self._message_patterns: list[MessagePattern] = []
        # Resources domain (AD-429c)
        self._model_tiers: list[ModelTier] = []
        self._tool_capabilities: list[ToolCapability] = []
        self._knowledge_sources: list[KnowledgeSourceSchema] = []
        # Records domain (AD-429d)
        self._knowledge_tiers: list[KnowledgeTier] = []
        self._classifications: list[DocumentClassification] = []
        self._document_classes: list[DocumentClass] = []
        self._retention_policies: list[RetentionPolicy] = []
        self._document_fields_required: list[DocumentField] = []
        self._document_fields_optional: list[DocumentField] = []
        self._repository_directories: list[RepositoryDirectory] = []

    async def initialize(self) -> None:
        """Load YAML schemas and build in-memory graph."""
        self._load_vessel()
        self._load_organization()
        self._load_skills_schema()
        # AD-429c domains
        for name, loader in [
            ("operations.yaml", self._load_operations_schema),
            ("communication.yaml", self._load_communication_schema),
            ("resources.yaml", self._load_resources_schema),
            ("records.yaml", self._load_records_schema),
        ]:
            path = self._config_dir / name
            if path.exists():
                loader(path)
        # crew.yaml is structural schema only — actual data comes from runtime
        logger.info("ontology initialized: %d departments, %d posts, %d assignments, %d role templates, "
                     "%d standing order tiers, %d channel types, %d model tiers",
                     len(self._departments), len(self._posts), len(self._assignments),
                     len(self._role_templates), len(self._standing_order_tiers),
                     len(self._channel_types), len(self._model_tiers))

    def _load_vessel(self) -> None:
        """Load vessel.yaml → VesselIdentity."""
        vessel_path = self._config_dir / "vessel.yaml"
        if not vessel_path.exists():
            logger.warning("vessel.yaml not found at %s", vessel_path)
            return

        with open(vessel_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        vessel = data.get("vessel", {})
        identity = vessel.get("identity", {})

        # Alert conditions
        self._valid_alert_conditions = vessel.get("alert_conditions", ["GREEN", "YELLOW", "RED"])
        self._alert_condition = vessel.get("default_alert_condition", "GREEN")

        # Instance ID: load from persistence or generate
        instance_id = self._load_or_generate_instance_id()

        self._vessel_identity = VesselIdentity(
            name=identity.get("name", "ProbOS"),
            version=identity.get("version", "0.0.0"),
            description=identity.get("description", ""),
            instance_id=instance_id,
            started_at=self._started_at,
        )

    def _load_or_generate_instance_id(self) -> str:
        """Generate UUID on first boot, persist, reuse on subsequent boots."""
        if self._data_dir:
            id_dir = self._data_dir / "ontology"
            id_file = id_dir / "instance_id"
            if id_file.exists():
                return id_file.read_text(encoding="utf-8").strip()
            # Generate and persist
            new_id = str(uuid.uuid4())
            id_dir.mkdir(parents=True, exist_ok=True)
            id_file.write_text(new_id, encoding="utf-8")
            return new_id
        return str(uuid.uuid4())

    def _load_organization(self) -> None:
        """Load organization.yaml → departments, posts, assignments."""
        org_path = self._config_dir / "organization.yaml"
        if not org_path.exists():
            logger.warning("organization.yaml not found at %s", org_path)
            return

        with open(org_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Departments
        for dept_data in data.get("departments", []):
            dept = Department(
                id=dept_data["id"],
                name=dept_data["name"],
                description=dept_data.get("description", ""),
            )
            self._departments[dept.id] = dept

        # Posts
        for post_data in data.get("posts", []):
            post = Post(
                id=post_data["id"],
                title=post_data["title"],
                department_id=post_data["department"],
                reports_to=post_data.get("reports_to"),
                authority_over=post_data.get("authority_over", []),
                tier=post_data.get("tier", "crew"),
            )
            self._posts[post.id] = post

        # Assignments
        for assign_data in data.get("assignments", []):
            assignment = Assignment(
                agent_type=assign_data["agent_type"],
                post_id=assign_data["post_id"],
                callsign=assign_data["callsign"],
            )
            self._assignments[assignment.agent_type] = assignment

    def _load_skills_schema(self) -> None:
        """Load skills.yaml — role templates and qualification paths (AD-429b)."""
        skills_path = self._config_dir / "skills.yaml"
        if not skills_path.exists():
            return

        with open(skills_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Parse role templates
        for post_id, template_data in data.get("role_templates", {}).items():
            required = [
                SkillRequirement(s["skill_id"], s["min_proficiency"])
                for s in template_data.get("required", [])
            ]
            optional = [
                SkillRequirement(s["skill_id"], s["min_proficiency"])
                for s in template_data.get("optional", [])
            ]
            self._role_templates[post_id] = RoleTemplate(post_id, required, optional)

        # Parse qualification paths
        for path_key, path_data in data.get("qualification_paths", {}).items():
            parts = path_key.split("_to_")
            if len(parts) != 2:
                continue
            from_rank, to_rank = parts
            reqs = []
            for r in path_data.get("requirements", []):
                reqs.append(QualificationRequirement(
                    type=r["type"],
                    description=r["description"],
                    min_proficiency=r["min_proficiency"],
                    scope=r["scope"],
                    min_count=r.get("min_count"),
                ))
            self._qualification_paths[path_key] = QualificationPath(
                from_rank=from_rank,
                to_rank=to_rank,
                description=path_data.get("description", ""),
                requirements=reqs,
            )

    def _load_operations_schema(self, path: Path) -> None:
        """Load operations.yaml — standing order tiers, watch types, alert procedures, duties."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for t in data.get("standing_order_tiers", []):
            self._standing_order_tiers.append(StandingOrderTier(
                tier=float(t["tier"]),
                name=t["name"],
                source=t["source"],
                scope=t["scope"],
                mutable=t["mutable"],
                description=t.get("description", ""),
            ))

        for w in data.get("watch_types", []):
            self._watch_types.append(WatchTypeSchema(
                id=w["id"],
                name=w["name"],
                description=w.get("description", ""),
                staffing=w["staffing"],
            ))

        for condition, proc_data in data.get("alert_procedures", {}).items():
            self._alert_procedures[condition] = AlertProcedure(
                condition=condition,
                description=proc_data.get("description", ""),
                watch_default=proc_data.get("watch_default", "alpha"),
                proactive_interval=proc_data.get("proactive_interval", "normal"),
                escalation_threshold=proc_data.get("escalation_threshold", "standard"),
                actions=proc_data.get("actions", []),
            )

        for d in data.get("duty_categories", []):
            self._duty_categories.append(DutyCategory(
                id=d["id"],
                name=d["name"],
                description=d.get("description", ""),
                examples=d.get("examples", []),
            ))

    def _load_communication_schema(self, path: Path) -> None:
        """Load communication.yaml — channel types, thread modes, message patterns."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for c in data.get("channel_types", []):
            self._channel_types.append(ChannelTypeSchema(
                id=c["id"],
                name=c["name"],
                description=c.get("description", ""),
                default_mode=c.get("default_mode", "discuss"),
            ))

        for t in data.get("thread_modes", []):
            self._thread_modes.append(ThreadModeSchema(
                id=t["id"],
                name=t["name"],
                description=t.get("description", ""),
                reply_expected=t.get("reply_expected", False),
                routing=t.get("routing", "none"),
                use_cases=t.get("use_cases", []),
            ))

        for m in data.get("message_patterns", []):
            self._message_patterns.append(MessagePattern(
                id=m["id"],
                tag=m["tag"],
                description=m.get("description", ""),
                expected_from=m.get("expected_from", "all_crew"),
                min_rank=m.get("min_rank"),
            ))

    def _load_resources_schema(self, path: Path) -> None:
        """Load resources.yaml — model tiers, tool capabilities, knowledge sources."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for m in data.get("model_tiers", []):
            self._model_tiers.append(ModelTier(
                id=m["id"],
                name=m["name"],
                description=m.get("description", ""),
                default_model=m.get("default_model", ""),
                use_cases=m.get("use_cases", []),
            ))

        for t in data.get("tool_capabilities", []):
            self._tool_capabilities.append(ToolCapability(
                id=t["id"],
                name=t["name"],
                description=t.get("description", ""),
                provider=t.get("provider", ""),
                available_to=t.get("available_to", "all_crew"),
                gated_by=t.get("gated_by"),
            ))

        for k in data.get("knowledge_sources", []):
            self._knowledge_sources.append(KnowledgeSourceSchema(
                id=k["id"],
                name=k["name"],
                description=k.get("description", ""),
                tier=k["tier"],
                tier_name=k.get("tier_name", ""),
                storage=k.get("storage", ""),
                access=k.get("access", ""),
            ))

    def _load_records_schema(self, path: Path) -> None:
        """Load records.yaml — knowledge tiers, classifications, document classes, retention."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for t in data.get("knowledge_tiers", []):
            self._knowledge_tiers.append(KnowledgeTier(
                tier=t["tier"], name=t["name"], store=t["store"],
                description=t["description"], access=t["access"],
                persistence=t["persistence"],
                promotion_path=t.get("promotion_path"),
            ))

        for c in data.get("classifications", []):
            self._classifications.append(DocumentClassification(
                id=c["id"], name=c["name"],
                description=c["description"], access_scope=c["access_scope"],
            ))

        for dc in data.get("document_classes", []):
            self._document_classes.append(DocumentClass(
                id=dc["id"], name=dc["name"], description=dc["description"],
                classification_default=dc["classification_default"],
                retention=dc["retention"], format=dc["format"],
                special_rules=dc.get("special_rules", []),
            ))

        for rp in data.get("retention_policies", []):
            self._retention_policies.append(RetentionPolicy(
                id=rp["id"], name=rp["name"], description=rp["description"],
                archive_after_days=rp.get("archive_after_days"),
                delete_after_days=rp.get("delete_after_days"),
                applies_to=rp.get("applies_to", []),
            ))

        schema = data.get("document_schema", {})
        for f in schema.get("required_fields", []):
            self._document_fields_required.append(DocumentField(
                name=f["name"], type=f["type"], description=f["description"],
                values=f.get("values"),
            ))
        for f in schema.get("optional_fields", []):
            self._document_fields_optional.append(DocumentField(
                name=f["name"], type=f["type"], description=f["description"],
                values=f.get("values"), default=f.get("default"),
            ))

        repo = data.get("repository_structure", {})
        for d in repo.get("directories", []):
            self._repository_directories.append(RepositoryDirectory(
                path=d["path"], description=d["description"],
            ))

    def set_skill_service(self, skill_service: Any) -> None:
        """Set reference to AgentSkillService for skill context queries."""
        self._skill_service = skill_service

    # -------------------------------------------------------------------
    # Vessel queries
    # -------------------------------------------------------------------

    def get_vessel_identity(self) -> VesselIdentity:
        """Return vessel identity (name, version, instance_id)."""
        if self._vessel_identity is None:
            return VesselIdentity(
                name="ProbOS", version="0.0.0", description="",
                instance_id="unknown", started_at=self._started_at,
            )
        return self._vessel_identity

    def get_vessel_state(self) -> VesselState:
        """Return current vessel state."""
        crew_count = sum(1 for a in self._assignments.values() if a.agent_id is not None)
        return VesselState(
            alert_condition=self._alert_condition,
            uptime_seconds=time.time() - self._started_at,
            active_crew_count=crew_count,
        )

    def get_alert_condition(self) -> str:
        """Return current alert condition."""
        return self._alert_condition

    def set_alert_condition(self, condition: str) -> None:
        """Set alert condition. Must be one of valid conditions."""
        if condition not in self._valid_alert_conditions:
            raise ValueError(f"Invalid alert condition: {condition}. Valid: {self._valid_alert_conditions}")
        self._alert_condition = condition

    # -------------------------------------------------------------------
    # Organization queries
    # -------------------------------------------------------------------

    def get_departments(self) -> list[Department]:
        """Return all departments."""
        return list(self._departments.values())

    def get_department(self, dept_id: str) -> Department | None:
        """Return a department by ID."""
        return self._departments.get(dept_id)

    def get_posts(self, department_id: str | None = None) -> list[Post]:
        """Return posts, optionally filtered by department."""
        if department_id:
            return [p for p in self._posts.values() if p.department_id == department_id]
        return list(self._posts.values())

    def get_post(self, post_id: str) -> Post | None:
        """Return a post by ID."""
        return self._posts.get(post_id)

    def get_chain_of_command(self, post_id: str) -> list[Post]:
        """Walk reports_to chain from post up to captain. Returns [self, ..., captain]."""
        chain: list[Post] = []
        visited: set[str] = set()
        current_id: str | None = post_id
        while current_id and current_id not in visited:
            visited.add(current_id)
            post = self._posts.get(current_id)
            if post is None:
                break
            chain.append(post)
            current_id = post.reports_to
        return chain

    def get_direct_reports(self, post_id: str) -> list[Post]:
        """Posts that report to this post."""
        return [p for p in self._posts.values() if p.reports_to == post_id]

    # -------------------------------------------------------------------
    # Assignment queries
    # -------------------------------------------------------------------

    def get_assignment_for_agent(self, agent_type: str) -> Assignment | None:
        """Return assignment for an agent_type."""
        return self._assignments.get(agent_type)

    def get_agent_department(self, agent_type: str) -> str | None:
        """Return department_id for an agent_type. Replaces _AGENT_DEPARTMENTS dict."""
        assignment = self._assignments.get(agent_type)
        if not assignment:
            return None
        post = self._posts.get(assignment.post_id)
        if not post:
            return None
        return post.department_id

    def get_crew_agent_types(self) -> set[str]:
        """Return set of agent_types assigned to crew-tier posts. Replaces _WARD_ROOM_CREW."""
        result: set[str] = set()
        for agent_type, assignment in self._assignments.items():
            post = self._posts.get(assignment.post_id)
            if post and post.tier == "crew":
                result.add(agent_type)
        return result

    def get_post_for_agent(self, agent_type: str) -> Post | None:
        """Return the Post that an agent_type is assigned to."""
        assignment = self._assignments.get(agent_type)
        if not assignment:
            return None
        return self._posts.get(assignment.post_id)

    def wire_agent(self, agent_type: str, agent_id: str) -> None:
        """Associate a runtime agent_id with its post assignment."""
        assignment = self._assignments.get(agent_type)
        if assignment:
            assignment.agent_id = agent_id

    def update_assignment_callsign(self, agent_type: str, new_callsign: str) -> bool:
        """Update the callsign on an agent's Assignment after naming ceremony (BF-049)."""
        assignment = self._assignments.get(agent_type)
        if not assignment:
            return False
        self._assignments[agent_type] = Assignment(
            agent_type=assignment.agent_type,
            post_id=assignment.post_id,
            callsign=new_callsign,
            agent_id=assignment.agent_id,
        )
        return True

    def get_assignment_for_agent_by_id(self, agent_id: str) -> Assignment | None:
        """Find assignment by runtime agent_id (set via wire_agent)."""
        for a in self._assignments.values():
            if a.agent_id == agent_id:
                return a
        return None

    # -------------------------------------------------------------------
    # Skills / Role Template queries (AD-429b)
    # -------------------------------------------------------------------

    def get_role_template(self, post_id: str) -> RoleTemplate | None:
        """Get the skill requirements for a post."""
        return self._role_templates.get(post_id)

    def get_role_template_for_agent(self, agent_type: str) -> RoleTemplate | None:
        """Get the role template for an agent's assigned post."""
        assignment = self._assignments.get(agent_type)
        if not assignment:
            return None
        return self._role_templates.get(assignment.post_id)

    def get_qualification_path(self, from_rank: str, to_rank: str) -> QualificationPath | None:
        """Get the qualification requirements for a rank transition."""
        key = f"{from_rank}_to_{to_rank}"
        return self._qualification_paths.get(key)

    def get_all_qualification_paths(self) -> list[QualificationPath]:
        """Get all defined qualification paths."""
        return list(self._qualification_paths.values())

    # -------------------------------------------------------------------
    # Operations queries (AD-429c)
    # -------------------------------------------------------------------

    def get_standing_order_tiers(self) -> list[StandingOrderTier]:
        """Get the standing orders tier hierarchy."""
        return list(self._standing_order_tiers)

    def get_watch_types(self) -> list[WatchTypeSchema]:
        """Get all watch type definitions."""
        return list(self._watch_types)

    def get_alert_procedure(self, condition: str) -> AlertProcedure | None:
        """Get operational procedures for an alert condition level."""
        return self._alert_procedures.get(condition)

    def get_duty_categories(self) -> list[DutyCategory]:
        """Get duty category taxonomy."""
        return list(self._duty_categories)

    # -------------------------------------------------------------------
    # Communication queries (AD-429c)
    # -------------------------------------------------------------------

    def get_channel_types(self) -> list[ChannelTypeSchema]:
        """Get all channel type definitions."""
        return list(self._channel_types)

    def get_thread_modes(self) -> list[ThreadModeSchema]:
        """Get all thread mode definitions."""
        return list(self._thread_modes)

    def get_thread_mode(self, mode_id: str) -> ThreadModeSchema | None:
        """Get a specific thread mode definition."""
        for tm in self._thread_modes:
            if tm.id == mode_id:
                return tm
        return None

    def get_message_patterns(self) -> list[MessagePattern]:
        """Get all message pattern definitions."""
        return list(self._message_patterns)

    # -------------------------------------------------------------------
    # Resources queries (AD-429c)
    # -------------------------------------------------------------------

    def get_model_tiers(self) -> list[ModelTier]:
        """Get all LLM model tier definitions."""
        return list(self._model_tiers)

    def get_model_tier(self, tier_id: str) -> ModelTier | None:
        """Get a specific model tier (fast/standard/deep)."""
        for mt in self._model_tiers:
            if mt.id == tier_id:
                return mt
        return None

    def get_tool_capabilities(self, available_to: str | None = None) -> list[ToolCapability]:
        """Get tool capabilities, optionally filtered by access level."""
        if available_to is None:
            return list(self._tool_capabilities)
        return [t for t in self._tool_capabilities if t.available_to == available_to]

    def get_knowledge_sources(self) -> list[KnowledgeSourceSchema]:
        """Get the three-tier knowledge source model."""
        return list(self._knowledge_sources)

    # -------------------------------------------------------------------
    # Records queries (AD-429d)
    # -------------------------------------------------------------------

    def get_knowledge_tiers(self) -> list[KnowledgeTier]:
        """Get the three-tier knowledge model."""
        return list(self._knowledge_tiers)

    def get_knowledge_tier(self, tier: int) -> KnowledgeTier | None:
        """Get a specific knowledge tier (1, 2, or 3)."""
        for kt in self._knowledge_tiers:
            if kt.tier == tier:
                return kt
        return None

    def get_classifications(self) -> list[DocumentClassification]:
        """Get all document classification levels."""
        return list(self._classifications)

    def get_document_classes(self) -> list[DocumentClass]:
        """Get all document class definitions."""
        return list(self._document_classes)

    def get_document_class(self, class_id: str) -> DocumentClass | None:
        """Get a specific document class by id."""
        for dc in self._document_classes:
            if dc.id == class_id:
                return dc
        return None

    def get_retention_policies(self) -> list[RetentionPolicy]:
        """Get all retention policies."""
        return list(self._retention_policies)

    def get_retention_policy(self, policy_id: str) -> RetentionPolicy | None:
        """Get a specific retention policy."""
        for rp in self._retention_policies:
            if rp.id == policy_id:
                return rp
        return None

    def get_repository_structure(self) -> list[RepositoryDirectory]:
        """Get the records repository directory layout."""
        return list(self._repository_directories)

    # -------------------------------------------------------------------
    # Crew context assembly (for context injection)
    # -------------------------------------------------------------------

    def get_crew_context(self, agent_type: str) -> dict[str, Any] | None:
        """Assemble full crew context for an agent — post, department, chain of command,
        peers, reports. Used by _gather_context() in proactive loop."""
        assignment = self._assignments.get(agent_type)
        if not assignment:
            return None

        post = self._posts.get(assignment.post_id)
        if not post:
            return None

        dept = self._departments.get(post.department_id)

        # Chain of command
        chain = self.get_chain_of_command(post.id)
        chain_titles: list[str] = [p.title for p in chain]

        # Reports to
        reports_to_str = ""
        if post.reports_to:
            superior = self._posts.get(post.reports_to)
            if superior:
                # Find callsign for the superior's occupant
                sup_callsign = ""
                for a in self._assignments.values():
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
            # Find callsign
            peer_callsign = ""
            for a in self._assignments.values():
                if a.post_id == dp.id:
                    peer_callsign = a.callsign
                    break
            label = dp.title
            if peer_callsign:
                label += f" ({peer_callsign})"
            peers.append(label)

        # Adjacent departments (departments of posts this post's superior also commands)
        adjacent_departments: list[str] = []
        if post.reports_to:
            superior = self._posts.get(post.reports_to)
            if superior:
                for sub_post_id in superior.authority_over:
                    sub_post = self._posts.get(sub_post_id)
                    if sub_post and sub_post.department_id != post.department_id:
                        sub_dept = self._departments.get(sub_post.department_id)
                        if sub_dept and sub_dept.name not in adjacent_departments:
                            adjacent_departments.append(sub_dept.name)

        vessel = self.get_vessel_identity()

        context: dict[str, Any] = {
            "vessel": {
                "name": vessel.name,
                "version": vessel.version,
                "alert_condition": self._alert_condition,
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
        if self._skill_service:
            context["skills_note"] = (
                "Your full skill profile is tracked by the Skill Framework. "
                "Role requirements above show what your post demands."
            )

        # Operations context (AD-429c)
        if self._alert_procedures:
            context["alert_condition"] = self._alert_condition
            proc = self.get_alert_procedure(self._alert_condition)
            if proc:
                context["alert_procedure"] = proc.description

        # Communication context (AD-429c)
        if self._message_patterns:
            context["available_actions"] = [
                {"tag": p.tag, "description": p.description}
                for p in self._message_patterns
                if p.min_rank is None  # Agent-specific filtering would need rank
            ]

        # Records context (AD-429d)
        if self._knowledge_tiers:
            context["knowledge_model"] = {
                "tiers": [
                    {"tier": kt.tier, "name": kt.name, "access": kt.access}
                    for kt in self._knowledge_tiers
                ],
                "note": "Tier 1 (Experience) is your episodic memory. Tier 2 (Records) is the ship's shared knowledge. Tier 3 (Operational State) is infrastructure.",
            }

        return context
