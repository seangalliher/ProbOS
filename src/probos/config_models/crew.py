"""Crew, governance and holodeck configuration models (AD-1270e2).

Batch 7 of the ``config.py`` extraction. Every model here is self-contained:
it references no other config model and no module-level helper in
``config.py``. Import these from ``probos.config``, which re-exports them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class BootCampConfig(BaseModel):
    """AD-638: Cold-start boot camp configuration."""

    enabled: bool = True
    min_episodes: int = 5
    min_ward_room_posts: int = 3
    min_dm_conversations: int = 1
    min_trust_score: float = 0.55
    min_time_minutes: int = 60
    timeout_minutes: int = 120
    nudge_cooldown_seconds: int = 600


class ShipStateSnapshotConfig(BaseModel):
    """AD-683: Ship State Snapshot for Cold-Start Onboarding."""

    enabled: bool = True


class TieredTrustConfig(BaseModel):
    """AD-640: Role-based trust initialization tiers."""

    enabled: bool = True

    # Bridge tier (Captain, First Officer, Counselor)
    bridge_alpha: float = 4.5
    bridge_beta: float = 1.0

    # Department Chief tier
    chief_alpha: float = 3.0
    chief_beta: float = 1.0

    # Crew tier uses existing consensus priors — no separate config needed.

    # Callsigns in each tier.
    bridge_pools: list[str] = ["counselor", "yeoman"]
    bridge_callsigns: list[str] = ["Meridian", "Yeo"]
    chief_callsigns: list[str] = ["Bones", "LaForge", "Number One", "Worf", "O'Brien"]


class OrdersConfig(BaseModel):
    """Chain-of-command order configuration (AD-440)."""

    enabled: bool = True
    max_active_per_post: int = Field(default=8, ge=1, le=64)
    default_ttl_seconds: float = Field(default=3600.0, ge=60.0, le=86400.0)


class ReadyRoomConfig(BaseModel):
    """Captain's Ready Room configuration (AD-475)."""

    enabled: bool = True
    idea_store_filename: str = "ready_room/ideas.json"
    wardroom_channel_id: str = "ready_room"


class DepartmentCognitiveProfile(BaseModel):
    """AD-656: per-department cognitive profile overlay.

    Modulates retrieval depth, similarity threshold, and context budget
    for the cognitive chain on a per-department basis.
    """

    recall_depth: int = Field(default=5, ge=1, le=20)
    recall_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    context_token_budget: int = Field(default=4000, ge=500)


class EPSDepartmentConfig(BaseModel):
    """One department's EPS allocation entry (AD-469)."""

    name: str
    percent: float = Field(default=0.0, ge=0.0, le=1.0)
    priority: int = Field(default=5, ge=1, le=10)


class WardRoomHebbianConfig(BaseModel):
    """AD-641b: Ward Room Hebbian Router configuration."""

    enabled: bool = True
    learning_rate: float = 0.10
    decay_factor: float = 0.99


class DeliberationConfig(BaseModel):
    """AD-641d: Crew Deliberation Protocol configuration."""

    enabled: bool = True
    captain_callsign: str = "Captain"


class PermissionsConfig(BaseModel):
    """AD-711: declarative permission lists (enforcement deferred to AD-711-1)."""

    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class MemorySecurityConfig(BaseModel):
    """AD-607: Memory security framework configuration.

    All ``enforce_*`` flags default-False per the AD-695 + W82 + W88 + W91
    default-False precedent — v1 ships observational by default.
    """

    enforce_recall: bool = False        # AD-607a opt-in: drop anomalous episodes from recall
    enforce_provenance: bool = False    # AD-607b opt-in: reject provenance-gap episodes from recall
    enforce_leak_guard: bool = False    # AD-607d opt-in: redact response when leak suspected
    enforce_store: bool = False         # AD-607h opt-in: reject prompt-injection at store time
    anchor_mismatch_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    dp_min_cohort_size: int = Field(default=3, ge=1)


class HolodeckBirthChamberConfig(BaseModel):
    """AD-486: Holodeck Birth Chamber — graduated cognitive onboarding.

    Default-False per AD-695 transitional-flag precedent: enabling the
    chamber gates Ward Room subscription and proactive-loop dispatch
    behind 5-phase graduation, which is a meaningful behavior change.
    Operators flip ``enabled=True`` after Phase α validation (manual
    cohort under observation).
    """

    enabled: bool = False
    bypass_for_existing_agents: bool = True
    department_order: list[str] = Field(
        default_factory=lambda: [
            "security",
            "operations",
            "engineering",
            "science",
            "medical",
        ]
    )
    calibration_min_episodes: int = Field(default=5, ge=1)
    affective_baseline_check_enabled: bool = True
    auto_advance_enabled: bool = True
    auto_advance_poll_interval_seconds: float = Field(
        default=2.0, ge=0.1, le=30.0
    )
    max_self_discovery_probe_attempts: int = Field(default=3, ge=1)

    @field_validator("department_order")
    @classmethod
    def _department_order_lowercase(cls, v: list[str]) -> list[str]:
        return [d.lower() for d in v]


class HolodeckScenarioConfig(BaseModel):
    """AD-539b: Holodeck scenario generation from skill gaps.

    Default-False per AD-695 transitional-flag precedent: enabling the
    bridge causes ``HolodeckGapBridge.bridge_gap_to_holodeck`` to
    register a runnable ``HolodeckGapDrill`` with the AD-477
    ``QualificationHarness`` for every classified knowledge gap that
    has a ``mapped_skill_id``. v1 ships dormant — operators flip
    ``enabled=True`` once an AD-486 cohort produces real ``GapReport``
    instances with non-empty ``mapped_skill_id`` to bridge against.
    """

    enabled: bool = False
    auto_register_with_harness: bool = True
    default_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    default_tier: int = Field(default=2, ge=1, le=3)
    category_fallback: str = "construction"
    persist_to_sqlite: bool = False
    data_subdir: str = "holodeck_scenarios"


class HolodeckTeamSimulationConfig(BaseModel):
    """AD-510: Holodeck team simulations — group discovery & collaboration.

    Default-False per AD-695 transitional-flag precedent: enabling the
    orchestrator causes ``TeamSimulationOrchestrator.start_simulation``
    to register a runnable ``TeamSimulationDrill`` with the AD-477
    ``QualificationHarness`` for every started simulation. v1 ships
    dormant — operators flip ``enabled=True`` once an AD-486 cohort
    reaches Phase α with crew-tier agents available across >=2
    departments to populate team rosters.
    """

    enabled: bool = False
    auto_register_with_harness: bool = True
    default_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    default_tier: int = Field(default=2, ge=1, le=3)
    enforce_required_departments: bool = True
    persist_to_sqlite: bool = False
    data_subdir: str = "team_simulations"


class SkillRequestConfig(BaseModel):
    """AD-906: Crew skill-acquisition request queue.

    Default-False per the AD-695 transitional-flag precedent: enabling this
    constructs a ``SkillRequestStore`` during startup, wires the AD-907
    TEAM_SIMULATION_COMPLETED subscriber, and exposes the
    ``/api/skill-requests`` decision surface. v1 ships dormant — with
    ``enabled=False`` no store is built, no listener is registered, the router
    returns 503, and runtime behavior is byte-identical to pre-AD-906.
    """

    enabled: bool = False
    data_subdir: str = "skill_requests"


class NamingConfig(BaseModel):
    """Ship & crew naming conventions (AD-499)."""

    enabled: bool = True
    captain_ship_override: str = ""  # If non-empty, overrides seed selection
    extra_banned_words: list[str] = Field(default_factory=list)


class UtilityAgentsConfig(BaseModel):
    """Utility agent suite configuration (AD-252)."""

    enabled: bool = True  # Create utility CognitiveAgent pools at boot


class SoftwareEngineerSpecialistsConfig(BaseModel):
    """AD-476 v1 — opt-in pool registration for the five SWE specialists.

    Default ``enabled=False`` per AD-695 transitional-flag precedent: pool
    creation is a real cognitive-budget side-effect (five new agents at
    boot), so v1 ships dormant. Operators flip ``enabled=True`` after
    AD-546 wires the production chunk-routing call site.
    """

    enabled: bool = False
    pool_size_per_specialty: int = 1
    model_tier_overrides: dict[str, str] = Field(
        default_factory=lambda: {
            "backend": "deep",
            "frontend": "standard",
            "test": "fast",
            "infrastructure": "standard",
            "data": "deep",
        }
    )

    @field_validator("pool_size_per_specialty")
    @classmethod
    def _pool_size_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("pool_size_per_specialty must be >= 1")
        return v

    @field_validator("model_tier_overrides")
    @classmethod
    def _tier_values_valid(cls, v: dict[str, str]) -> dict[str, str]:
        valid_tiers = {"fast", "standard", "deep"}
        for specialty, tier in v.items():
            if tier not in valid_tiers:
                raise ValueError(
                    f"AD-476 model_tier_overrides[{specialty!r}]={tier!r} "
                    f"not in {sorted(valid_tiers)}"
                )
        return v


class WardRoomConfig(BaseModel):
    """Ward Room communication fabric configuration (AD-407)."""

    enabled: bool = False  # Disabled by default — enable after HXI surface is ready
    max_agent_rounds: int = 5           # AD-407d / BF-201: max consecutive agent-only rounds per thread
    agent_cooldown_seconds: float = 45  # AD-407d: cooldown for agent-triggered responses
    max_thread_posts: int = 50          # BF-201: total posts per thread (all authors)
    default_discuss_responder_cap: int = 3  # AD-424: Default max_responders for DISCUSS threads
    # AD-416: Retention & archival
    retention_days: int = 7                    # Regular posts older than this are pruned
    retention_days_endorsed: int = 30          # Posts with net_score > 0 retained longer
    retention_days_captain: int = 0            # 0 = indefinite retention for Captain posts
    archive_enabled: bool = True               # Write pruned posts to JSONL archive before deletion
    prune_interval_seconds: float = 86400.0    # How often to run pruning (default: daily)
    dm_exchange_limit: int = 15          # BF-257: lowered from 40 (BF-200's value) — 15 still allows substantive DM conversations
    dm_similarity_threshold: float = 0.6  # AD-614: Jaccard threshold for DM self-similarity suppression
    router_concurrency_limit: int = 10     # AD-616: max concurrent route_event() tasks
    event_coalesce_ms: int = 200           # AD-616: coalesce window for rapid-fire post events (0 = disabled)
    dm_response_budget: int = 6             # BF-257: max DM responses per agent per window
    dm_response_window_seconds: float = 600.0  # BF-257: sliding window (10 minutes)
    dm_pair_exchange_budget: int = 8        # BF-257: max exchanges per A<->B pair per window


class AssignmentConfig(BaseModel):
    """Dynamic assignment groups configuration (AD-408)."""

    enabled: bool = False  # Disabled by default — enable after HXI surface is ready


class VisitingOfficersConfig(BaseModel):
    """AD-701: Visiting officer registry tunables.

    Default-False per Wave 10 standing convention #14: this is a transitional
    feature that must be explicitly enabled by the operator. The registry
    issues sovereign DIDs under ``agent_type='visiting'`` and runs an async
    sweep loop, so silently enabling it would change the substrate's
    process-tree shape on first commit.
    """

    enabled: bool = False
    session_ttl_seconds: float = Field(default=3600.0, gt=0.0)
    sweep_interval_seconds: float = Field(default=60.0, gt=0.0)
    default_capabilities: list[str] = Field(
        default_factory=lambda: ["ward_room.post", "ward_room.read"]
    )


class FirewallConfig(BaseModel):
    """AD-529: Communication Contagion Firewall configuration."""

    enabled: bool = True
    scan_trust_threshold: float = 0.65      # Scan posts from agents below this
    low_trust_threshold: float = 0.45       # Extra checks for very low trust
    hex_id_min_length: int = 6              # Min hex string length to flag
    hex_id_threshold: int = 2               # Flag if N+ ungrounded hex IDs
    fabricated_metrics_threshold: int = 3   # Flag if N+ precise claims with no source
    flag_window_seconds: float = 3600.0     # Window for counting flags
    quarantine_threshold: int = 3           # Flags in window before quarantine escalation


class RiskTierConfig(BaseModel):
    """Action Risk Tier configuration (AD-676)."""

    enabled: bool = True
    elevated_min_trust: float = 0.0
    critical_min_trust: float = 0.70


class DutyDefinition(BaseModel):
    """A single recurring duty for a crew agent type."""
    duty_id: str                # e.g., "scout_report"
    description: str            # Human-readable task description
    cron: str = ""              # Cron expression (croniter format). Empty = interval-based.
    interval_seconds: float = 0 # Alternative to cron: simple interval. 0 = use cron.
    priority: int = 2           # 1-5, higher = more important when multiple due
    required_skills: list[str] = []  # AD-423c: skill_ids needed for this duty (informational)


class PolicyWindowConfig(BaseModel):
    """Time window policy definition used for proactive scheduling."""

    start_time: str = Field(default="08:00")
    end_time: str = Field(default="18:00")
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
