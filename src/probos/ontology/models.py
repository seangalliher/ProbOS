"""Vessel ontology data models — dataclasses for all ontology domains."""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Core organization models
# ---------------------------------------------------------------------------

@dataclass
class Department:
    id: str
    name: str
    description: str


@dataclass
class PostCapability:
    """A structured capability that a post (billet) provides.

    AD-648: Grounding mechanism to prevent conceptual confabulation.
    Links to actual tools/processes the post uses.
    """
    id: str
    summary: str
    tools: list[str] = field(default_factory=list)      # tool/function names used
    outputs: list[str] = field(default_factory=list)     # artifact types produced


@dataclass
class Post:
    id: str
    title: str
    department_id: str
    reports_to: str | None  # post_id
    authority_over: list[str] = field(default_factory=list)  # post_ids
    tier: str = "crew"  # "crew", "utility", "infrastructure", "external"
    clearance: str = ""  # AD-620: RecallTier name (BASIC/ENHANCED/FULL/ORACLE). Empty = no billet clearance.
    capabilities: list[PostCapability] = field(default_factory=list)  # AD-648
    does_not_have: list[str] = field(default_factory=list)  # AD-648: negative grounding


@dataclass
class Assignment:
    agent_type: str
    post_id: str
    callsign: str
    watches: list[str] = field(default_factory=lambda: ["alpha"])
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
