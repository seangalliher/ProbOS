"""Knowledge, reasoning and consultation configuration models (AD-1270e2).

Batch 6 of the ``config.py`` extraction. Every model here is self-contained:
it references no other config model and no module-level helper in
``config.py``. Import these from ``probos.config``, which re-exports them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class SubTaskConfig(BaseModel):
    """AD-632a: Sub-task protocol configuration."""

    enabled: bool = True                       # AD-632f: MVP chain complete, enabled by default
    chain_timeout_ms: int = 30000              # Default chain timeout (30s)
    step_timeout_ms: int = 15000               # Default per-step timeout (15s)
    max_chain_steps: int = 6                   # Maximum steps per chain (defense in depth)
    fallback_on_timeout: str = "single_call"   # Degradation strategy
    max_concurrent_chains: int = 4             # AD-636: Cap simultaneous chain executions
    nats_publish_enabled: bool = False         # AD-641g: opt-in chain step publish to NATS
    nats_payload_max_bytes: int = 16384        # AD-641g: cap on result-dict serialized size


class ChainTuningConfig(BaseModel):
    """AD-639: Trust-adaptive chain personality tuning."""

    enabled: bool = True

    # Trust band thresholds
    low_trust_ceiling: float = 0.60   # Below this: skip evaluate/reflect
    high_trust_floor: float = 0.75    # At or above: full chain as-is


class ChainOptimizerConfig(BaseModel):
    """AD-659 v1 + AD-659b: Cognitive Chain Self-Optimization service.

    v1 (AD-659) shipped analysis-only proposal generation + Captain approval
    REST surface. AD-659b adds the apply path (gated by `apply_enabled`),
    SQLite persistence, dedup keyed on (detector_name, target_parameter),
    manual revert, and an opt-in scheduled analyze loop.

    Both new flags default OFF. `apply_enabled=True` grants live-mutation
    authority over `chain_tuning.low_trust_ceiling` / `high_trust_floor`.
    `analysis_interval_seconds > 0` enables periodic background analysis.
    """

    enabled: bool = False  # opt-in until validated
    analysis_window: int = 100
    latency_p95_ms_floor: float = 10000.0
    success_rate_floor: float = 0.7
    error_rate_ceiling: float = 0.3
    min_samples_per_group: int = 20
    apply_enabled: bool = False  # AD-659b: apply path gate (default OFF)
    analysis_interval_seconds: int = 0  # AD-659b: 0 disables scheduled loop

    @field_validator("analysis_interval_seconds")
    @classmethod
    def _validate_interval(cls, v: int) -> int:
        if v < 0:
            raise ValueError("analysis_interval_seconds must be >= 0")
        return v


class ChainOptimizerCounselorConfig(BaseModel):
    """AD-659c v1: OptimizationCounselor watchdog for AD-659b applied proposals.

    Default-OFF (Wave-10 convention #14). Captain opts in once AD-659b apply
    has accumulated production data and detection accuracy is validated.

    `auto_revert_enabled` is a SECOND gate — the watchdog can be enabled to
    only observe + record decisions (no destructive action) without granting
    revert authority. Captain flips auto_revert separately once observed
    decisions look correct.
    """

    enabled: bool = False
    baseline_window_seconds: float = 1800.0       # 30 min
    observation_window_seconds: float = 1800.0    # 30 min
    success_rate_drop_floor: float = 0.10         # 10% absolute drop
    min_samples_per_window: int = 20
    auto_revert_enabled: bool = False             # SECOND gate

    @field_validator(
        "baseline_window_seconds",
        "observation_window_seconds",
    )
    @classmethod
    def _validate_window(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError("window seconds must be > 0")
        return v

    @field_validator("success_rate_drop_floor")
    @classmethod
    def _validate_drop_floor(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("success_rate_drop_floor must be in [0.0, 1.0]")
        return v

    @field_validator("min_samples_per_window")
    @classmethod
    def _validate_min_samples(cls, v: int) -> int:
        if v < 1:
            raise ValueError("min_samples_per_window must be >= 1")
        return v


class DiagnosticContextConfig(BaseModel):
    """AD-661 v1 + AD-661b/c: Diagnostic Context Service — pull-based bundle assembly.

    Default-enabled (deviation from Wave-10 transitional-flag convention)
    because the service is a read-only aggregator with no automatic
    invocation; it is invisible at runtime until a caller invokes
    `assemble()`. See AD-661 prompt for the convention deviation rationale.

    AD-661b adds a 4th allocation tier (`records_ratio`) for Ship's Records
    (AD-434). The synthetic system-context reader naturally surfaces only
    ship/fleet records; per-agent record authorization is deferred (AD-661f).

    AD-661c adds `redistribute_remainder` (default True): unused budget from
    under-filled tiers is redistributed to other tiers in priority order
    (chain_traces > procedures > episodes > records) while candidates remain.
    """

    enabled: bool = True
    default_budget_tokens: int = 8000
    chain_trace_ratio: float = 0.30
    procedure_ratio: float = 0.25
    episode_ratio: float = 0.25
    records_ratio: float = 0.20
    chars_per_token: int = 4
    redistribute_remainder: bool = True

    @field_validator(
        "chain_trace_ratio", "procedure_ratio", "episode_ratio", "records_ratio",
    )
    @classmethod
    def _ratio_in_unit(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("ratio must be in [0.0, 1.0]")
        return v

    @model_validator(mode="after")
    def _ratios_sum_to_one(self) -> "DiagnosticContextConfig":
        total = (
            self.chain_trace_ratio
            + self.procedure_ratio
            + self.episode_ratio
            + self.records_ratio
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"ratios must sum to 1.0 (±0.01); got {total:.4f}"
            )
        return self


class CausalReasoningConfig(BaseModel):
    """AD-660 v1 + AD-660b: Agent Causal Reasoning Framework.

    v1 (AD-660) shipped the four-step template + journal storage + opt-in
    counselor concern hook. AD-660b flips the default ON, adds AD-557
    emergence-warning hooks (groupthink + fragmentation) on the same path,
    introduces hypothesis ranking + recommended-action surfacing, and adds
    a per-bucket sliding-window rate limiter to bound LLM cost.

    Default-on is safe because (a) the rate limiter caps invocations per
    bucket per hour, (b) `analyze()` is fire-and-forget — never raises into
    callers, and (c) downstream consumers (counselor hooks, journal) treat
    every result as best-effort.
    """

    enabled: bool = True  # AD-660b: default-on (rate-limited)
    max_tokens: int = 700
    tier: str = "standard"
    max_invocations_per_hour: int = 5  # AD-660b: per-bucket rate cap

    @field_validator("max_invocations_per_hour")
    @classmethod
    def _validate_rate_cap(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_invocations_per_hour must be >= 1")
        return v


class StepInstructionConfig(BaseModel):
    """AD-651: Step-specific standing order decomposition."""

    enabled: bool = False  # Disabled by default — opt-in after validation

    # Step-to-category mappings. Keys are chain step names (matching SubTaskType values),
    # values are lists of category tags that the step should receive.
    step_categories: dict[str, list[str]] = {
        "query": [],  # Query is deterministic, no LLM — receives no instructions
        "analyze": [
            "observation_guidelines",
            "situation_assessment",
            "when_to_act_vs_observe",
            "memory_anchoring",
            "source_attribution",
            "self_monitoring",
        ],
        "compose": [
            "communication_style",
            "personality_expression",
            "audience_awareness",
            "ward_room_actions",
            "knowledge_capture",
            "duty_reporting",
        ],
        "evaluate": [
            "self_monitoring",
            "scope_discipline",
            "communication_style",
        ],
        "reflect": [
            "self_monitoring",
            "scope_discipline",
            "knowledge_capture",
        ],
    }

    # Categories that every LLM-calling step receives regardless of mapping.
    # These are foundational and should never be excluded.
    universal_categories: list[str] = [
        "identity",
        "chain_of_command",
        "core_directives",
        "encoding_safety",
    ]

    # If True, log token savings per step at DEBUG level.
    log_token_savings: bool = True


class LLMRateConfig(BaseModel):
    """AD-617: LLM call rate governance configuration."""

    # Per-tier requests per minute (0 = disabled)
    rpm_fast: int = 120
    rpm_standard: int = 120
    rpm_deep: int = 30

    # Max seconds to wait for a rate limit slot before returning error
    max_wait_seconds: float = 30.0

    # Max LLM response cache entries (LRU eviction)
    cache_max_entries: int = 500

    # AD-617b: Per-agent hourly token cap (0 = disabled)
    per_agent_hourly_token_cap: int = 0

    # AD-636: Global concurrency cap for LLM calls
    max_concurrent_calls: int = 6
    # AD-636: Reserved slots for interactive (Captain DM) priority
    interactive_reserved_slots: int = 2

    # BF-654: max simultaneous in-flight requests to any SINGLE LLM endpoint
    # (keyed by base_url|api_format, i.e. the httpx pool). Bounds total
    # concurrency to the shared Copilot proxy during a boot burst, composing
    # with — not replacing — the AD-636 priority lanes. Endpoints on distinct
    # base_urls (e.g. the Copilot proxy vs. ollama for vision) get INDEPENDENT
    # caps, so vision is never throttled by the text cap. CRITICAL (interactive)
    # calls BYPASS this cap so the Captain is never throttled. 0/negative =
    # disabled (unbounded past the lane fail-open = pre-BF-654 byte-identical).
    max_inflight_per_endpoint: int = 8

    # BF-674: persistent empty HTTP 200s from one endpoint open a background
    # cooldown shared by every alias tier on that endpoint. Critical Captain
    # calls bypass it; one half-open background probe tests recovery. 0 disables.
    endpoint_failure_cooldown_seconds: float = Field(
        default=15.0,
        ge=0.0,
        le=300.0,
    )


class KnowledgeConfig(BaseModel):
    """Persistent knowledge store configuration."""

    enabled: bool = True
    repo_path: str = ""             # Empty = ~/.probos/knowledge/
    auto_commit: bool = True        # Auto-commit on writes
    commit_debounce_seconds: float = 5.0  # Batch writes within this window
    max_episodes: int = 1000        # Max episodes to persist (oldest evicted)
    max_workflows: int = 200        # Max workflow cache entries to persist
    restore_on_boot: bool = True    # Warm boot from existing repo


class KnowledgeLoadingConfig(BaseModel):
    """AD-585: Tiered knowledge loading configuration."""

    enabled: bool = True

    # Per-tier token budgets (approximate: 1 token is about 4 chars)
    ambient_token_budget: int = 200
    contextual_token_budget: int = 400
    on_demand_token_budget: int = 600

    # Per-tier max age in seconds (0 = always fresh)
    ambient_max_age_seconds: float = 300.0
    contextual_max_age_seconds: float = 60.0
    on_demand_max_age_seconds: float = 0.0  # Always fresh

    # Intent-to-knowledge category mapping.
    # Keys are intent types; values are KnowledgeStore subdirectory names.
    intent_knowledge_map: dict[str, list[str]] = Field(default_factory=lambda: {
        "security_alert": ["trust", "agents"],
        "proactive_think": ["episodes", "proactive"],
        "ward_room_notification": ["episodes", "agents"],
        "direct_message": ["episodes", "agents"],
    })


class RecordsConfig(BaseModel):
    """Ship's Records configuration (AD-434)."""

    enabled: bool = True
    repo_path: str = ""  # Empty = {data_dir}/ship-records/
    auto_commit: bool = True
    commit_debounce_seconds: float = 5.0
    max_episodes_per_hour: int = 20  # Rate limit for notebook writes
    # AD-550: Notebook dedup settings
    notebook_dedup_enabled: bool = True
    notebook_similarity_threshold: float = 0.8
    notebook_staleness_hours: float = 72.0
    notebook_max_scan_entries: int = 20
    # AD-552: Notebook self-repetition detection
    notebook_repetition_enabled: bool = True
    notebook_repetition_window_hours: float = 48.0
    notebook_repetition_threshold_count: int = 3
    notebook_repetition_novelty_threshold: float = 0.2
    notebook_repetition_suppression_count: int = 5
    # AD-553: Notebook metric capture
    notebook_metrics_enabled: bool = True
    # AD-554: Real-time convergence/divergence detection
    realtime_convergence_enabled: bool = True
    realtime_convergence_threshold: float = 0.5
    realtime_divergence_threshold: float = 0.3
    realtime_convergence_staleness_hours: float = 72.0
    realtime_max_scan_per_agent: int = 5
    realtime_min_convergence_agents: int = 2
    realtime_min_convergence_departments: int = 2
    # AD-583: Wrong convergence detection
    convergence_independence_threshold: float = 0.3
    # AD-555: Notebook quality metrics
    notebook_quality_enabled: bool = True
    notebook_quality_low_threshold: float = 0.3
    notebook_quality_warn_threshold: float = 0.5
    notebook_staleness_alert_rate: float = 0.7
    # AD-1138: index records into SemanticKnowledgeLayer and serve Oracle
    # Tier 2 from it. Default-OFF — when False, Tier 2 uses the keyword path.
    semantic_index_enabled: bool = False


class ArchiveConfig(BaseModel):
    """Ship's Archive configuration (AD-524)."""

    enabled: bool = True
    db_path: str = ""


class OrientationConfig(BaseModel):
    """AD-567g: Cognitive re-localization configuration."""

    enabled: bool = True
    orientation_window_seconds: float = 600.0  # 10 minutes
    cold_start_full_orientation: bool = True
    warm_boot_orientation: bool = True
    proactive_supplement: bool = True
    populate_watch_section: bool = True
    populate_ward_room_department: bool = True
    populate_event_log_window: bool = True


class SocialVerificationConfig(BaseModel):
    """AD-567f: Social Verification Protocol configuration."""

    enabled: bool = True
    # Corroboration
    corroboration_threshold: float = 0.4  # Score above this = corroborated
    corroboration_max_agents: int = 5  # Denominator for agent count scoring
    corroboration_min_confidence: float = 0.3  # Anchor confidence gate for matches
    # Cascade detection
    cascade_enabled: bool = True
    cascade_independence_threshold: float = 0.3  # Below this = cascade risk
    cascade_cooldown_seconds: float = 300.0  # Dedup window for cascade alerts
    # Provenance (AD-662)
    anomaly_window_discount: float = 0.5  # 0.0-1.0: weight discount for anomaly window pairs
    # Provenance validation (AD-665)
    provenance_version_independence_weight: float = 0.7  # 0.0=reject, 1.0=full independence
    provenance_validation_enabled: bool = True  # Master toggle for AD-665 graded validation
    # Privacy
    expose_episode_content: bool = False  # MUST stay False — privacy boundary


class SourceTracingConfig(BaseModel):
    """AD-583g: Ward Room echo detection and source tracing."""

    echo_min_chain_length: int = 3
    echo_similarity_threshold: float = 0.4
    echo_analysis_enabled: bool = True


class ObservableStateConfig(BaseModel):
    """AD-583f: Observable state verification."""

    verification_enabled: bool = True
    max_claims_per_thread: int = 10


class PredictiveBranchingConfig(BaseModel):
    """AD-633 v1: Predictive Cognitive Branching.

    Default-False — speculation actually consumes tokens (separate budget pool,
    but still real LLM cost when SpeculationExecutor dispatches). Operator
    opt-in. AD-695 default-False precedent applies.
    """

    enabled: bool = False
    cache_ttl_seconds: float = Field(default=60.0, ge=1.0)
    cache_max_entries: int = Field(default=128, ge=1)
    speculation_tokens_per_window: int = Field(default=2000, ge=0)
    speculation_window_seconds: float = Field(default=300.0, ge=1.0)
    flush_rate_feedback_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    flush_rate_window_seconds: float = Field(default=3600.0, ge=1.0)
    accuracy_ring_size: int = Field(default=100, ge=10)
    cheap_tier_min_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
    standard_tier_min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    anticipatory_tier_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)


class SelfImprovementConfig(BaseModel):
    """AD-482 v1: Self-improvement pipeline (proposal -> approval -> QA -> evolution -> versioning).

    Default-False -- operator opt-in. The pipeline spawns real QA agents, opens a
    new ChromaDB collection, and writes promoted agents to
    ``src/probos/agents/designed/``. AD-633 / AD-695 default-False precedent.
    """

    enabled: bool = False
    qa_pool_size: int = Field(default=3, ge=1, le=8)
    iteration_cap: int = Field(default=5, ge=1, le=20)
    evolution_half_life_seconds: float = Field(default=2592000.0, ge=1.0)  # 30 days
    evolution_collection_name: str = "self_improvement_lessons"
    persistence_root_dir: str = "src/probos/agents/designed"


class ConsultationConfig(BaseModel):
    """AD-594: Crew Consultation Protocol configuration."""

    enabled: bool = True
    timeout_seconds: float = 30.0
    max_consultations_per_agent_per_hour: int = 20
    max_pending_requests: int = 10
    expert_selection_max_candidates: int = 5
    weight_capability_match: float = 0.5
    weight_trust: float = 0.3
    weight_billet_relevance: float = 0.2


class ExpertiseConfig(BaseModel):
    """AD-600: Transactive Memory expertise directory configuration."""

    enabled: bool = True
    max_topics_per_agent: int = 50
    min_confidence: float = 0.1
    decay_rate: float = 0.95
    top_k_experts: int = 3


class QuestionAdaptiveConfig(BaseModel):
    """AD-602: Question-adaptive retrieval strategy configuration."""

    enabled: bool = True
    strategy_overrides: dict[str, dict] = Field(default_factory=dict)


class TaskContextConfig(BaseModel):
    """Task-contextual standing orders configuration (AD-586)."""

    enabled: bool = True
    orders_dir: str = "config/task_orders"
    max_tokens: int = 500


class SalienceConfig(BaseModel):
    """AD-668: Salience filter for working memory promotion."""

    enabled: bool = True
    weights: dict[str, float] = {
        "relevance": 0.30,
        "recency": 0.25,
        "novelty": 0.15,
        "urgency": 0.20,
        "social": 0.10,
    }
    threshold: float = 0.3
    background_max_entries: int = 50
