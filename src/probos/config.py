"""Configuration loader for ProbOS."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Trust Threshold Constants ─────────────────────────────────────
# Canonical trust boundaries used across the system.
# Rank thresholds define promotion gates in crew_profile.py.
# Other thresholds reference these for consistency.

TRUST_SENIOR = 0.85        # Senior rank promotion threshold
TRUST_COMMANDER = 0.7      # Commander rank promotion threshold
TRUST_LIEUTENANT = 0.5     # Lieutenant rank promotion threshold
TRUST_DEFAULT = 0.5        # Default trust for new/unknown agents
TRUST_FLOOR_CONN = 0.6     # Minimum trust for Conn eligibility
TRUST_FLOOR_CREDIBILITY = 0.3  # Minimum credibility for channel creation
TRUST_DEGRADED = 0.2       # Agent degraded state threshold
TRUST_HARD_FLOOR = 0.05    # AD-558: Protective minimum — below this, negative updates silently absorbed
TRUST_OUTLIER_LOW = 0.3    # Trust outlier detection — low flag
TRUST_OUTLIER_HIGH = 0.9   # Trust outlier detection — high flag

# Display
TRUST_DISPLAY_PRECISION = 4  # Decimal places for trust/score display
TRUST_COLOR_GREEN = 0.6      # HXI trust color: green above this
TRUST_COLOR_YELLOW = 0.4     # HXI trust color: yellow above this

# Counselor assessment
COUNSELOR_TRUST_PROMOTION = 0.7    # Min trust for promotion fitness
COUNSELOR_WELLNESS_PROMOTION = 0.8  # Min wellness for promotion fitness
COUNSELOR_WELLNESS_YELLOW = 0.5    # Yellow alert wellness threshold
COUNSELOR_WELLNESS_FIT = 0.3       # Minimum wellness for fit-for-duty
COUNSELOR_CONFIDENCE_LOW = 0.3     # Low confidence concern threshold
COUNSELOR_TRUST_DRIFT_CONCERN = -0.2  # Significant trust drop

# ─── Cognitive JIT (AD-534) ───────────────────────────────────────
# Replay-first dispatch thresholds for procedural memory.

PROCEDURE_MATCH_THRESHOLD = 0.6     # Minimum semantic similarity for replay
PROCEDURE_MIN_COMPILATION_LEVEL = 2  # AD-535: Minimum Level 2 (Guided) for replay dispatch
PROCEDURE_MIN_SELECTIONS = 5        # Minimum selections before health diagnosis
PROCEDURE_HEALTH_FALLBACK_RATE = 0.4    # FIX diagnosis threshold
PROCEDURE_HEALTH_COMPLETION_RATE = 0.35  # FIX diagnosis (with applied > 0.4)
PROCEDURE_HEALTH_APPLIED_RATE = 0.4      # FIX diagnosis trigger
PROCEDURE_HEALTH_EFFECTIVE_RATE = 0.55   # DERIVED diagnosis threshold
PROCEDURE_HEALTH_DERIVED_APPLIED = 0.25  # DERIVED minimum applied_rate
EVOLUTION_COOLDOWN_SECONDS = 259200  # 72 hours — don't re-evolve same procedure within this window

# AD-532e: Reactive & proactive triggers
REACTIVE_COOLDOWN_SECONDS: int = 60       # Per-agent cooldown for reactive checks
PROACTIVE_SCAN_INTERVAL_SECONDS: int = 300  # 5 minutes between proactive scans
EVOLUTION_MAX_RETRIES: int = 3              # Max retry attempts for evolution

# AD-534b: Fallback learning
MAX_FALLBACK_RESPONSE_CHARS: int = 4000   # Truncation limit for LLM response in fallback events
MAX_FALLBACK_QUEUE_SIZE: int = 50         # Cap on in-memory fallback queue per dream cycle

# AD-534c: Multi-agent replay dispatch
COMPOUND_STEP_TIMEOUT_SECONDS: float = 10.0  # Per-step dispatch timeout

# AD-535: Graduated compilation
COMPILATION_PROMOTION_THRESHOLD: int = 3        # Consecutive successes to promote
COMPILATION_DEMOTION_LEVEL: int = 2              # Level to demote to on failure (Guided)
COMPILATION_MAX_LEVEL: int = 5                   # Maximum level (AD-537: Level 5 Expert unlocked)
COMPILATION_VALIDATION_TIMEOUT_SECONDS: float = 15.0  # LLM validation call timeout at Level 3
COMPILATION_TRUST_LEVEL_2_MIN: float = 0.0       # Ensign+ (any trust)
COMPILATION_TRUST_LEVEL_3_MIN: float = 0.5       # Lieutenant+ (TRUST_LIEUTENANT)
COMPILATION_TRUST_LEVEL_4_MIN: float = 0.5       # Lieutenant+ (TRUST_LIEUTENANT)

# AD-536: Procedure Promotion
PROMOTION_MIN_COMPILATION_LEVEL: int = 4          # Must be Level 4+ to request promotion
PROMOTION_MIN_TOTAL_COMPLETIONS: int = 10          # Minimum successful completions
PROMOTION_MIN_EFFECTIVE_RATE: float = 0.7           # Minimum effective_rate
PROMOTION_REJECTION_COOLDOWN_HOURS: int = 72        # Anti-loop: no re-submit within 72h
PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD: str = "high"  # "high"/"critical" -> Captain
PROMOTION_DESTRUCTIVE_KEYWORDS: frozenset[str] = frozenset({
    "delete", "remove", "destroy", "reset", "drop", "purge", "force", "override",
})

# AD-537: Observational Learning
OBSERVATION_MIN_TRUST: float = 0.5               # Only observe agents with trust >= this
OBSERVATION_MAX_THREADS_PER_DREAM: int = 20       # Cap threads scanned per dream cycle
OBSERVATION_MIN_DETAIL_SCORE: float = 0.6         # LLM-assessed actionability threshold
OBSERVATION_WARD_ROOM_LOOKBACK_HOURS: float = 24  # Scan threads from last N hours
TEACHING_MIN_COMPILATION_LEVEL: int = 5           # Must be Level 5 to teach
TEACHING_MIN_TRUST: float = 0.85                  # Must be Commander+ trust to teach

# AD-538: Procedure Lifecycle
LIFECYCLE_DECAY_DAYS: int = 30                  # Unused for this many days → lose 1 compilation level
LIFECYCLE_ARCHIVE_DAYS: int = 90                # Unused at Level 1 for this many days → archived
LIFECYCLE_DEDUP_SIMILARITY_THRESHOLD: float = 0.85  # ChromaDB cosine similarity → flag as duplicate
LIFECYCLE_DEDUP_MAX_CANDIDATES: int = 50        # Max procedures to scan for dedup per dream
LIFECYCLE_REVALIDATION_LEVEL: int = 2           # Decayed procedures drop to this level (Guided)
LIFECYCLE_MIN_SELECTIONS_FOR_DECAY: int = 3     # Don't decay procedures that haven't had a fair chance

# AD-539: Gap → Qualification Pipeline
GAP_MIN_FAILURE_RATE: float = 0.30         # Cluster failure rate threshold for gap detection
GAP_MIN_EPISODES: int = 5                  # Minimum episodes in cluster to qualify as gap evidence
GAP_MIN_PROCEDURE_FAILURES: int = 3        # Minimum procedure failures to constitute a gap
GAP_PROFICIENCY_TARGET: int = 3            # Target ProficiencyLevel (APPLY) for gap closure
GAP_REPORT_MAX_PER_DREAM: int = 10         # Cap gap reports per dream cycle


def format_trust(value: float, precision: int = TRUST_DISPLAY_PRECISION) -> float:
    """Round a trust/score value for display. Centralizes precision."""
    return round(value, precision)


class PoolConfig(BaseModel):
    """Agent pool configuration."""

    default_pool_size: int = 3
    max_pool_size: int = 7
    min_pool_size: int = 2
    spawn_cooldown_ms: int = 500
    health_check_interval_seconds: float = 5.0


class MeshConfig(BaseModel):
    """Mesh communication configuration."""

    gossip_interval_ms: int = 1000
    hebbian_decay_rate: float = 0.995
    # AD-571c v1: per-rel_type decay. SOCIAL weights persist longer than intent-routing
    # weights. Default falls back to hebbian_decay_rate so v1 is behavior-equivalent;
    # AD-571c-i forcing function flips this to 0.999 once AD-557 benchmarks land.
    hebbian_social_decay_rate: float = 0.995
    # AD-428b v1: Map intent_id -> skill_id for skill-weighted routing.
    # Empty dict (default) means skill weighting is off; the router returns
    # base_weight unchanged. Reread per call so config reload picks up changes.
    intent_skill_map: dict[str, str] = Field(default_factory=dict)
    hebbian_reward: float = 0.05
    signal_ttl_seconds: float = 30.0
    capability_broadcast_interval_seconds: float = 5.0
    semantic_matching: bool = True  # Enable semantic matching in CapabilityRegistry


class ConsensusConfig(BaseModel):
    """Consensus layer configuration."""

    min_votes: int = 3
    approval_threshold: float = 0.6
    use_confidence_weights: bool = True
    verification_timeout_seconds: float = 5.0
    red_team_pool_size: int = 2
    trust_prior_alpha: float = 2.0  # Beta distribution prior successes
    trust_prior_beta: float = 2.0  # Beta distribution prior failures
    trust_decay_rate: float = 0.999  # Slow decay of trust observations


class CognitiveConfig(BaseModel):
    """Cognitive layer configuration."""

    # Shared endpoint (backward compat — used when per-tier not specified)
    llm_base_url: str = "http://127.0.0.1:8080/v1"  # OpenAI-compatible endpoint
    llm_api_key: str = ""
    llm_timeout_seconds: float = 30.0

    # Per-tier model names (existing)
    llm_model_fast: str = "claude-sonnet-4-6"
    llm_model_standard: str = "claude-sonnet-4-6"
    llm_model_deep: str = "claude-opus-4-6"

    # BF-240: Dwell-time criterion for LLM health recovery
    llm_health_min_consecutive_healthy: int = 3  # Consecutive successes before tier transitions to operational

    @field_validator("llm_health_min_consecutive_healthy")
    @classmethod
    def _validate_min_consecutive_healthy(cls, v: int) -> int:
        if v < 1:
            raise ValueError("llm_health_min_consecutive_healthy must be >= 1")
        return v

    @model_validator(mode="after")
    def _apply_env_overrides(self) -> "CognitiveConfig":
        """Docker-friendly: allow PROBOS_LLM_URL to override default LLM endpoint."""
        url = os.environ.get("PROBOS_LLM_URL")
        if url:
            self.llm_base_url = url
        return self

    # Per-tier endpoint overrides (None = fall back to shared)
    llm_base_url_fast: str | None = None
    llm_api_key_fast: str | None = None
    llm_timeout_fast: float | None = None
    llm_api_format_fast: str | None = None  # "openai" or "ollama"

    llm_base_url_standard: str | None = None
    llm_api_key_standard: str | None = None
    llm_timeout_standard: float | None = None
    llm_api_format_standard: str | None = None

    llm_base_url_deep: str | None = None
    llm_api_key_deep: str | None = None
    llm_timeout_deep: float | None = None
    llm_api_format_deep: str | None = None

    # Per-tier sampling overrides (None = use request-level value)
    llm_temperature_fast: float | None = None
    llm_temperature_standard: float | None = None
    llm_temperature_deep: float | None = None

    llm_top_p_fast: float | None = None
    llm_top_p_standard: float | None = None
    llm_top_p_deep: float | None = None

    # Default tier for LLM requests ("fast", "standard", or "deep")
    default_llm_tier: str = "fast"

    # Ollama keep_alive: how long the model stays loaded after the last request.
    # Prevents cold-start delays when Ollama unloads idle models.
    # Examples: "5m", "30m", "1h", "-1" (forever). Default "30m".
    ollama_keep_alive: str = "30m"

    working_memory_token_budget: int = 4000
    decomposition_timeout_seconds: float = 30.0
    dag_execution_timeout_seconds: float = 60.0
    use_consensus_for_writes: bool = True
    max_concurrent_tasks: int = 8
    attention_decay_rate: float = 0.95  # Per-second decay for stale tasks
    focus_history_size: int = 10
    background_demotion_factor: float = 0.25

    def tier_config(self, tier: str) -> dict:
        """Return resolved endpoint config for a tier.

        Returns {"base_url": str, "api_key": str, "model": str, "timeout": float}
        with per-tier overrides applied, falling back to shared values.
        """
        model_map = {
            "fast": self.llm_model_fast,
            "standard": self.llm_model_standard,
            "deep": self.llm_model_deep,
        }
        url_map = {
            "fast": self.llm_base_url_fast,
            "standard": self.llm_base_url_standard,
            "deep": self.llm_base_url_deep,
        }
        key_map = {
            "fast": self.llm_api_key_fast,
            "standard": self.llm_api_key_standard,
            "deep": self.llm_api_key_deep,
        }
        timeout_map = {
            "fast": self.llm_timeout_fast,
            "standard": self.llm_timeout_standard,
            "deep": self.llm_timeout_deep,
        }
        format_map = {
            "fast": self.llm_api_format_fast,
            "standard": self.llm_api_format_standard,
            "deep": self.llm_api_format_deep,
        }
        temp_map = {
            "fast": self.llm_temperature_fast,
            "standard": self.llm_temperature_standard,
            "deep": self.llm_temperature_deep,
        }
        top_p_map = {
            "fast": self.llm_top_p_fast,
            "standard": self.llm_top_p_standard,
            "deep": self.llm_top_p_deep,
        }
        return {
            "base_url": url_map.get(tier) or self.llm_base_url,
            "api_key": key_map.get(tier) if key_map.get(tier) is not None else self.llm_api_key,
            "model": model_map.get(tier, self.llm_model_standard),
            "timeout": timeout_map.get(tier) if timeout_map.get(tier) is not None else self.llm_timeout_seconds,
            "api_format": format_map.get(tier) or "openai",
            "temperature": temp_map.get(tier),   # None = use request default
            "top_p": top_p_map.get(tier),        # None = don't send
        }


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
    bridge_pools: list[str] = ["counselor"]
    bridge_callsigns: list[str] = ["Meridian"]
    chief_callsigns: list[str] = ["Bones", "LaForge", "Number One", "Worf", "O'Brien"]


class ChainTuningConfig(BaseModel):
    """AD-639: Trust-adaptive chain personality tuning."""

    enabled: bool = True

    # Trust band thresholds
    low_trust_ceiling: float = 0.60   # Below this: skip evaluate/reflect
    high_trust_floor: float = 0.75    # At or above: full chain as-is
    # Mid band is implicitly [low_trust_ceiling, high_trust_floor)


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


class NLGraphQueryConfig(BaseModel):
    """AD-691 v1: NL-to-Graph Query Service.

    Default-enabled (deviation from Wave-10 transitional-flag convention)
    because the service is a callable read-only aggregator with no automatic
    invocation; it is invisible at runtime until a caller invokes
    `runtime.nl_graph_query.query()`. Same precedent as
    `DiagnosticContextConfig` and `KnowledgeEdgesConfig`.
    """

    enabled: bool = True
    default_max_hops: int = 2
    default_limit: int = 10
    llm_tier: str = "standard"
    extraction_max_tokens: int = 600
    synthesis_max_tokens: int = 800

    @field_validator("default_max_hops")
    @classmethod
    def _hops_in_range(cls, v: int) -> int:
        if not 1 <= v <= 3:
            raise ValueError("default_max_hops must be in [1, 3]")
        return v

    @field_validator("default_limit")
    @classmethod
    def _limit_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("default_limit must be >= 1")
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


class MemoryConfig(BaseModel):
    """Episodic memory configuration."""

    collection_name: str = "probos_episodes"
    max_episodes: int = 100000
    # AD-607e: Cross-shard recall access policy. PERMISSIVE preserves the
    # AD-462c cross-shard recall behavior verbatim. Opt-in tightening via
    # OWN_SHARD_ONLY or OWN_SHARD_PLUS_PUBLIC.
    access_policy: str = "permissive"
    relevance_threshold: float = 0.7
    # BF-134 / AD-593: Agent-scoped recall threshold.
    # MiniLM QA-trained model cosine similarity for question-vs-statement is typically 0.20-0.45.
    # 0.25 eliminates near-random associations while remaining generous for cross-topic recall.
    # Anchor confidence gate and composite score floor (AD-590) provide additional quality filtering.
    agent_recall_threshold: float = 0.25
    # BF-134: Minimum semantic similarity floor for FTS5 keyword-only hits.
    # Episodes found by keyword search but not semantic search get this
    # floor instead of 0.0, preventing keyword-relevant episodes from
    # being buried by the composite score formula.
    fts_keyword_semantic_floor: float = 0.2
    # AD-584: Embedding model and query reformulation
    embedding_model: str = "multi-qa-MiniLM-L6-cos-v1"
    query_reformulation_enabled: bool = True
    similarity_threshold: float = 0.6  # Semantic similarity threshold for recall/fuzzy lookup
    verify_content_hash: bool = True    # AD-541e: Verify episode hashes on recall
    eviction_audit_enabled: bool = True  # AD-541f: Append-only eviction audit trail
    # AD-567b/AD-584c: Salience-weighted recall (rebalanced for QA-trained embeddings)
    recall_weights: dict[str, float] = {
        "semantic": 0.35,
        "keyword": 0.20,
        "trust": 0.10,
        "hebbian": 0.05,
        "recency": 0.15,
        "anchor": 0.15,
    }
    recall_convergence_bonus: float = 0.10  # AD-584c: bonus for multi-channel hits
    recall_temporal_match_weight: float = 0.25       # BF-147→BF-155: bonus for temporal cue match in score_recall()
    recall_temporal_mismatch_penalty: float = 0.15   # BF-155: penalty when query watch differs from episode watch
    # AD-601: TCM Temporal Context Model
    tcm_enabled: bool = True
    tcm_dimension: int = 16
    tcm_drift_rate: float = 0.95
    tcm_weight: float = 0.15
    tcm_fallback_watch_weight: float = 0.05
    recall_context_budget_chars: int = 4000  # ~4K char memory budget
    # AD-567c: Anchor confidence scoring
    anchor_dimension_weights: dict[str, float] = {
        "temporal": 0.25,
        "spatial": 0.25,
        "social": 0.25,
        "causal": 0.15,
        "evidential": 0.10,
    }
    anchor_confidence_gate: float = 0.3  # RPMS: suppress below this from default recall
    # AD-590: Composite score floor — filter marginal episodes from recall results.
    # Episodes with composite_score below this threshold are excluded regardless
    # of remaining budget. 0.0 = disabled (backward compatible).
    composite_score_floor: float = 0.35
    # AD-591: Quality-aware budget enforcement.
    # max_recall_episodes: hard cap on episodes returned per recall. 0 = use k*2 default.
    max_recall_episodes: int = 0
    # recall_quality_floor: stop adding episodes if mean composite would drop below this.
    # 0.0 = disabled (character budget only).
    recall_quality_floor: float = 0.40
    # AD-462c: Variable Recall Tiers
    recall_tiers: dict[str, dict[str, Any]] = {
        "basic": {
            "k": 3,
            "context_budget": 1500,
            "anchor_confidence_gate": 0.0,
            "composite_score_floor": 0.0,
            "max_recall_episodes": 0,
            "recall_quality_floor": 0.0,
            "use_salience_weights": False,
            "cross_department_anchors": False,
        },
        "enhanced": {
            "k": 5,
            "context_budget": 4000,
            "anchor_confidence_gate": 0.3,
            "composite_score_floor": 0.35,
            "max_recall_episodes": 0,
            "recall_quality_floor": 0.40,
            "use_salience_weights": True,
            "cross_department_anchors": False,
        },
        "full": {
            "k": 8,
            "context_budget": 6000,
            "anchor_confidence_gate": 0.3,
            "composite_score_floor": 0.35,
            "max_recall_episodes": 0,
            "recall_quality_floor": 0.40,
            "use_salience_weights": True,
            "cross_department_anchors": True,
        },
        "oracle": {
            "k": 10,
            "context_budget": 8000,
            "anchor_confidence_gate": 0.2,
            "composite_score_floor": 0.0,
            "max_recall_episodes": 0,
            "recall_quality_floor": 0.0,
            "use_salience_weights": True,
            "cross_department_anchors": True,
        },
    }

    @field_validator("access_policy")
    @classmethod
    def _validate_access_policy(cls, v: str) -> str:
        """AD-607e: Validate cross-shard access policy values."""
        valid = {"permissive", "own_shard_only", "own_shard_plus_public"}
        if v not in valid:
            raise ValueError(
                f"access_policy must be one of {sorted(valid)}; got {v!r}"
            )
        return v


class DreamingConfig(BaseModel):
    """Dreaming / offline consolidation configuration."""

    idle_threshold_seconds: float = 120.0  # Tier 2: full dream after idle (AD-288)
    dream_interval_seconds: float = 600.0
    replay_episode_count: int = 50
    pathway_strengthening_factor: float = 0.03
    pathway_weakening_factor: float = 0.02
    prune_threshold: float = 0.01
    trust_boost: float = 0.1
    trust_penalty: float = 0.1
    pre_warm_top_k: int = 5
    # AD-551: Notebook consolidation
    notebook_consolidation_enabled: bool = True
    notebook_consolidation_threshold: float = 0.6
    notebook_consolidation_min_entries: int = 2
    notebook_convergence_threshold: float = 0.5
    notebook_convergence_min_agents: int = 3
    notebook_convergence_min_departments: int = 2
    # AD-541c: Spaced Retrieval Therapy
    active_retrieval_enabled: bool = False
    retrieval_episodes_per_cycle: int = 3
    retrieval_success_threshold: float = 0.6
    retrieval_partial_threshold: float = 0.3
    retrieval_initial_interval_hours: float = 24.0
    retrieval_max_interval_hours: float = 168.0
    retrieval_counselor_failure_streak: int = 3
    # AD-541d: Guided Reminiscence
    reminiscence_enabled: bool = True
    reminiscence_episodes_per_session: int = 3
    reminiscence_concern_threshold: int = 3
    reminiscence_confabulation_alert: float = 0.3
    reminiscence_cooldown_hours: float = 2.0
    # AD-567d / AD-462b: Activation-based memory lifecycle
    activation_enabled: bool = True
    activation_decay_d: float = 0.5
    activation_prune_threshold: float = -2.0
    activation_access_max_age_days: int = 180
    # AD-593: Pruning acceleration — configurable parameters (previously hardcoded)
    prune_min_age_hours: int = 24  # Standard tier: only prune episodes older than this
    prune_max_fraction: float = 0.10  # Standard tier: max fraction of candidates per cycle
    # AD-599: Reflection episode promotion
    reflection_enabled: bool = True
    reflection_max_per_cycle: int = 3        # Cap reflections per dream cycle to prevent flooding
    reflection_min_importance: int = 8       # Importance score for reflection episodes (1-10 scale)
    # AD-593: Aggressive pruning tier — targets old, low-activation episodes
    aggressive_prune_enabled: bool = True
    aggressive_prune_min_age_hours: int = 168  # 7 days
    aggressive_prune_threshold: float = 0.0  # Higher threshold than standard (-2.0)
    aggressive_prune_max_fraction: float = 0.25  # Up to 25% of old candidates
    # AD-593: Episode pool pressure — accelerate pruning when pool is large
    episode_pressure_threshold: int = 5000  # Above this count, increase pruning aggressiveness
    episode_pressure_multiplier: float = 1.5  # Multiply prune fraction by this when above pressure threshold
    # AD-657: Trace exemplars preserved per consolidated procedure (0 = disabled)
    trace_exemplars_per_procedure: int = 3
    # AD-690: Dream Step 7i — Relationship inference from co-occurring episode agents
    relationship_inference_enabled: bool = True
    relationship_inference_max_pairs_per_run: int = 50
    relationship_inference_max_per_entity: int = 5
    relationship_inference_min_confidence: float = 0.6


class DreamWMConfig(BaseModel):
    """AD-671: Dream-Working Memory bridge configuration."""

    enabled: bool = True
    max_priming_entries: int = 3
    flush_min_entries: int = 5
    priming_category: str = "observation"


class ScalingConfig(BaseModel):
    """Adaptive pool scaling configuration."""

    enabled: bool = True
    scale_up_threshold: float = 0.8
    scale_down_threshold: float = 0.2
    scale_up_step: int = 1
    scale_down_step: int = 1
    cooldown_seconds: float = 30.0
    observation_window_seconds: float = 60.0
    idle_scale_down_seconds: float = 120.0


class PeerConfig(BaseModel):
    """Configuration for a single peer node."""

    node_id: str
    address: str  # e.g. "tcp://127.0.0.1:5556"


class FederationMCPServerConfig(BaseModel):
    """AD-480a: Inbound MCP server — exposes ProbOS capabilities as MCP tools."""

    enabled: bool = False  # Default-False per AD-695 + W82 + W88 precedent
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8765, ge=1, le=65535)
    path_prefix: str = "/mcp"


class KnowledgeBrowserConfig(BaseModel):
    """AD-562: Ship's Records Knowledge Browser (Phases 1-4 OSS)."""
    enabled: bool = False
    max_graph_nodes: int = Field(default=500, ge=0, le=2000)
    max_graph_edges: int = Field(default=1000, ge=0, le=5000)
    jaccard_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    max_suggestions_per_entry: int = Field(default=5, ge=0, le=50)
    index_refresh_seconds: int = Field(default=300, ge=10, le=3600)


class SpatialExplorerConfig(BaseModel):
    """AD-520: Spatial Knowledge Explorer (Phase 1 Knowledge Graph View + Phase 2 Spatial Ship Layout).

    Default-False per AD-695 transitional precedent — wirer reads YAML and
    constructs an in-memory layout, not zero-cost on boot. Operator opt-in.
    """

    enabled: bool = False
    max_graph_edges: int = Field(default=500, ge=0, le=5000)
    max_graph_nodes: int = Field(default=200, ge=0, le=2000)
    spatial_layout_path: str = ""  # empty → resolves to config/ontology/spatial.yaml then to _DEFAULT_LAYOUT


class MCPAppHostConfig(BaseModel):
    """AD-597 — MCP App Host configuration."""

    enabled: bool = False
    serve_internal_games: bool = True
    discover_external_apps: bool = False
    internal_default_csp: str = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'"
    )
    external_default_csp: str = (
        "default-src 'none'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'"
    )
    bundles_dir: str = ""


class A2APeerConfig(BaseModel):
    """AD-480e: Outbound A2A peer registration entry."""

    peer_url: str
    auth_token: str = ""


class FederationA2AConfig(BaseModel):
    """AD-480d / AD-480e: Inbound A2A server + outbound A2A clients."""

    enabled: bool = False  # Default-False per AD-695 + W82 + W88 precedent
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8766, ge=1, le=65535)
    agent_card_path: str = "/.well-known/agent.json"
    outbound_peers: list[A2APeerConfig] = Field(default_factory=list)


class FederationPeerTrustConfig(BaseModel):
    """AD-480g: Probationary trust prior for federated peers."""

    probationary_alpha: float = Field(default=1.0, gt=0.0)
    probationary_beta: float = Field(default=3.0, gt=0.0)


class FederationTLSConfig(BaseModel):
    """AD-479f: Federation TLS surface (NATS pass-through in v1).

    Default-False. v1 wires the NATS path via ``nats_bus.config.tls``.
    ZeroMQ CURVE encryption is parked as AD-479l with explicit forcing
    function — AD-637e moved default federation traffic to NATS, so ZMQ
    TLS is downstream of "ZMQ becomes production transport again".
    """

    enabled: bool = False
    cert_file: str | None = None
    key_file: str | None = None
    ca_file: str | None = None
    verify_peer: bool = True


class FederationDiscoveryConfig(BaseModel):
    """AD-479h: Multicast peer discovery (opt-in, default-False).

    Raw UDP multicast on the local broadcast domain. Cross-LAN mDNS via
    ``zeroconf`` is parked as AD-479j.
    """

    multicast_enabled: bool = False
    multicast_group: str = "239.255.42.99"
    multicast_port: int = 5556
    announce_interval_seconds: float = 5.0


class FederationClusterMonitorConfig(BaseModel):
    """AD-479g: Cluster health monitor.

    Default-True (the gossip-driven liveness flag is purely additive — peers
    that never fall silent never get flagged unreachable). The two trip-wire
    EventTypes (``FEDERATION_PEER_UNREACHABLE`` / ``FEDERATION_PEER_RECOVERED``)
    are always-on observability when federation is enabled.
    """

    enabled: bool = True
    peer_unreachable_seconds: float = 60.0


class FederationConfig(BaseModel):
    """Multi-node federation configuration."""

    enabled: bool = False  # Disabled by default — single-node is still the default
    node_id: str = "node-1"
    bind_address: str = "tcp://127.0.0.1:5555"  # This node's ZeroMQ ROUTER address
    peers: list[PeerConfig] = []  # Static peer list
    forward_timeout_ms: int = 5000  # Timeout waiting for peer responses
    gossip_interval_seconds: float = 10.0  # How often to broadcast self-model to peers
    validate_remote_results: bool = True  # Pass remote results through local consensus
    # AD-443c: Memory portability tier for incoming agent transfers.
    # CLEAN_ROOM (default) means foreign agents arrive with sovereign identity
    # but zero episodic memory — safest default. SELECTIVE filters by tag.
    # FULL accepts all episodes verbatim. Per-agent overrides via Standing Orders.
    memory_policy: str = "clean_room"
    # AD-443c: Tag whitelist for SELECTIVE memory policy. Ignored for the
    # other two policies. Empty list with SELECTIVE means no episodes pass.
    memory_policy_selective_tags: list[str] = []

    # AD-480: Cross-ecosystem federation adapters.
    mcp_server: FederationMCPServerConfig = Field(
        default_factory=FederationMCPServerConfig
    )
    a2a: FederationA2AConfig = Field(default_factory=FederationA2AConfig)
    peer_trust: FederationPeerTrustConfig = Field(
        default_factory=FederationPeerTrustConfig
    )
    # AD-479f / AD-479g / AD-479h: hardening surfaces (all default-False or
    # additive-only).
    tls: FederationTLSConfig = Field(default_factory=FederationTLSConfig)
    discovery: FederationDiscoveryConfig = Field(
        default_factory=FederationDiscoveryConfig
    )
    cluster_monitor: FederationClusterMonitorConfig = Field(
        default_factory=FederationClusterMonitorConfig
    )
    # AD-479b ranking gate (default 0.0 keeps W87/W89 baseline behavior).
    min_peer_trust_score: float = 0.0
    # AD-607g federation outbound privacy filter. Default ``shared_trust``
    # honors the AD-479b peer-trust ranking surface that W91 shipped.
    memory_access_policy: str = "shared_trust"
    shared_trust_min_score: float = Field(default=0.5, ge=0.0, le=1.0)
    dp_min_cohort_size: int = Field(default=3, ge=1)

    @field_validator("memory_access_policy")
    @classmethod
    def _validate_memory_access_policy(cls, v: str) -> str:
        """AD-607g: validate federation outbound privacy policy values."""
        valid = {"public", "shared_trust", "private"}
        if v not in valid:
            raise ValueError(
                f"memory_access_policy must be one of {sorted(valid)}; got {v!r}"
            )
        return v

    @field_validator("memory_policy")
    @classmethod
    def _validate_memory_policy(cls, v: str) -> str:
        from probos.mobility import MemoryPolicy
        valid = {p.value for p in MemoryPolicy}
        if v not in valid:
            raise ValueError(
                f"memory_policy must be one of {sorted(valid)}; got {v!r}"
            )
        return v


class SelfModConfig(BaseModel):
    """Self-modification configuration."""

    enabled: bool = False  # Disabled by default — opt-in capability
    require_user_approval: bool = True  # Human must confirm before agent goes live
    probationary_alpha: float = 1.0  # Beta prior alpha for self-created agents
    probationary_beta: float = 3.0  # Beta prior beta → E[trust] = 0.25
    max_designed_agents: int = 5  # Maximum self-created agent types in system
    sandbox_timeout_seconds: float = 60.0  # Timeout for sandbox test execution (LLM-backed agents need more)
    allowed_imports: list[str] = [
        "asyncio", "pathlib", "json", "os", "re", "datetime",
        "typing", "dataclasses", "collections", "math", "hashlib",
        "urllib.parse", "base64", "csv", "io", "tempfile",
    ]
    forbidden_patterns: list[str] = [
        r"subprocess", r"shutil\.rmtree", r"os\.remove", r"os\.unlink",
        r"eval\s*\(", r"exec\s*\(", r"__import__",
        r"open\s*\(.*['\"][waxWAX]", r"socket\b", r"ctypes\b",
        # BF-086: Close security gaps found by bypass testing
        r"os\.system", r"os\.popen", r"os\.exec", r"os\.kill",
        r"\.write_text\s*\(", r"\.write_bytes\s*\(",
        r"\.unlink\s*\(",
        r"__builtins__",
        r"compile\s*\(",
    ]
    research_enabled: bool = False  # Opt-in web research before design
    research_domain_whitelist: list[str] = [
        "docs.python.org",
        "pypi.org",
        "developer.mozilla.org",
        "learn.microsoft.com",
    ]
    research_max_pages: int = 3
    research_max_content_per_page: int = 2000


class QAConfig(BaseModel):
    """SystemQAAgent configuration."""

    enabled: bool = True                    # QA runs by default when self-mod is enabled
    smoke_test_count: int = 5               # Number of synthetic intents per new agent
    timeout_per_test_seconds: float = 10.0  # Per-intent timeout
    total_timeout_seconds: float = 30.0     # Total QA budget per agent
    pass_threshold: float = 0.6             # Fraction of tests that must pass (3/5)
    trust_reward_weight: float = 1.0        # Weight for trust_network.record_outcome on success
    trust_penalty_weight: float = 2.0       # Weight for trust_network.record_outcome on failure
    flag_on_fail: bool = True               # Emit warning event if agent fails QA
    auto_remove_on_total_fail: bool = False  # Remove agent if 0/N pass


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


class ArchiveConfig(BaseModel):
    """Ship's Archive configuration (AD-524)."""

    enabled: bool = True
    db_path: str = ""


class TelemetryConfig(BaseModel):
    """Ship's Telemetry configuration (AD-461)."""

    enabled: bool = True
    report_interval_seconds: float = 60.0
    max_samples_per_bucket: int = 1000


class PostBudgetTelemetryConfig(BaseModel):
    """BF-238: Post-budget exhaustion telemetry configuration."""

    enabled: bool = True
    exhaustion_alert_threshold: float = 0.5  # Per-agent rate that triggers WARN
    min_samples_for_alert: int = 10          # Suppress alert below this invocation count
    recent_suppressions_max: int = 100       # Ring buffer size for ops review


class ConfidenceConfig(BaseModel):
    """AD-444: Knowledge confidence scoring configuration."""

    enabled: bool = True
    default_confidence: float = 0.5
    confirm_delta: float = 0.15
    contradict_delta: float = 0.25
    auto_supersede_threshold: float = 0.1
    auto_apply_threshold: float = 0.8
    suppress_threshold: float = 0.5


class LintConfig(BaseModel):
    """AD-563: Knowledge linting configuration."""

    enabled: bool = True
    min_coverage_per_department: int = 5
    inconsistency_keywords: dict[str, str] = Field(default_factory=lambda: {
        "increased": "decreased",
        "improved": "degraded",
        "rising": "falling",
        "positive": "negative",
        "success": "failure",
    })


class QualityTriggerConfig(BaseModel):
    """AD-564: Quality-triggered forced consolidation configuration."""

    enabled: bool = True
    min_quality_threshold: float = 0.4
    max_stale_rate: float = 0.3
    max_repetition_rate: float = 0.2
    cooldown_seconds: float = 1800.0
    max_forced_per_day: int = 5


class QualityRouterConfig(BaseModel):
    """AD-565: Quality-informed routing configuration."""

    enabled: bool = True
    min_weight: float = 0.5
    max_weight: float = 1.5
    concern_threshold: float = 0.3


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


class AnomalyWindowConfig(BaseModel):
    """Anomaly window detection configuration (AD-673)."""

    enabled: bool = True
    max_window_duration_seconds: float = 1800.0
    lookback_seconds: float = 60.0


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


class WorkingMemoryConfig(BaseModel):
    """AD-573: Unified agent working memory configuration."""

    token_budget: int = 3000  # Max tokens for working memory context
    max_recent_actions: int = 10  # Ring buffer capacity
    max_recent_observations: int = 5
    max_recent_conversations: int = 5
    max_events: int = 10
    proactive_budget: int = 1500  # Lower budget for proactive (supplemental)
    stale_threshold_hours: float = 24.0  # Entries older than this pruned on restore
    conclusion_ttl_seconds: float = 1800.0
    max_conclusions: int = 20
    duty_budget: int = 600
    social_budget: int = 800
    ship_budget: int = 800
    engagement_budget: int = 800


class MemoryBudgetConfig(BaseModel):
    """AD-573: Memory budget accounting across recall tiers."""

    enabled: bool = True
    total_budget_tokens: int = 4650
    l0_budget: int = 150
    l1_budget: int = 3000
    l2_budget: int = 1000
    l3_budget: int = 500


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


class SpreadingActivationConfig(BaseModel):
    """AD-604: Spreading activation / multi-hop retrieval configuration."""

    enabled: bool = True
    max_hops: int = 2
    k_per_hop: int = 5
    hop_decay_factor: float = 0.6
    min_anchor_fields: int = 2


class ThoughtStoreConfig(BaseModel):
    """AD-606: Think-in-Memory thought storage configuration."""

    enabled: bool = True
    min_importance: int = 5
    max_thoughts_per_cycle: int = 3


class DistillationConfig(BaseModel):
    """AD-609: Multi-faceted distillation configuration."""

    enabled: bool = True
    min_failure_cluster_size: int = 3
    comparative_enabled: bool = True


class MetabolismConfig(BaseModel):
    """AD-670: Working memory metabolism — active lifecycle management."""

    enabled: bool = True
    decay_half_life_seconds: float = 3600.0
    forget_threshold: float = 0.05
    min_entries_per_buffer: int = 2
    audit_enabled: bool = True
    cycle_interval_seconds: float = 300.0
    triage_fullness_threshold: float = 0.8
    triage_base_score: float = 0.3


class ReconsolidationConfig(BaseModel):
    """AD-574: Episodic decay reconsolidation scheduling."""

    enabled: bool = True
    base_intervals_hours: list[float] = Field(default_factory=lambda: [1.0, 6.0, 24.0, 72.0, 168.0, 720.0])
    importance_scale_factor: float = 0.1
    max_scheduled: int = 500


class StorageGateConfig(BaseModel):
    """AD-610: Utility-based storage gating - write-time validation."""

    enabled: bool = True
    duplicate_threshold: float = 0.95
    utility_floor: float = 0.2
    recent_window: int = 50
    contradiction_check_enabled: bool = True


class RetroactiveConfig(BaseModel):
    """AD-608: Retroactive memory evolution - store-time metadata propagation."""

    enabled: bool = True
    neighbor_k: int = 5
    similarity_threshold: float = 0.7
    max_relations_per_episode: int = 10
    propagate_watch_section: bool = True
    propagate_department: bool = True


class PinnedKnowledgeConfig(BaseModel):
    """AD-579a: Pinned knowledge buffer configuration."""

    enabled: bool = True
    max_tokens: int = 150
    max_pins: int = 10
    default_ttl_seconds: float = 86400.0


class TemporalValidityConfig(BaseModel):
    """AD-579b: Temporal validity windows for episodic memory."""

    enabled: bool = True
    default_validity_hours: float = 0.0


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


class SensoriumConfig(BaseModel):
    """AD-666: Agent Sensorium tracking configuration."""

    enabled: bool = True
    token_budget_warning: int = 10000


class RuntimeOverridesConfig(BaseModel):
    """Runtime override layer configuration (AD-468)."""

    enabled: bool = True
    store_filename: str = "runtime_overrides.json"


class OrdersConfig(BaseModel):
    """Chain-of-command order configuration (AD-440)."""

    enabled: bool = True
    max_active_per_post: int = Field(default=8, ge=1, le=64)
    default_ttl_seconds: float = Field(default=3600.0, ge=60.0, le=86400.0)


class ValidationFrameworkConfig(BaseModel):
    """Validation framework configuration (AD-451)."""

    enabled: bool = True
    metadata_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    min_confidence_delta: float = Field(default=0.20, ge=0.0, le=1.0)


class PreFlightConfig(BaseModel):
    """Pre-flight validation configuration (AD-458 / AD-458b)."""

    enabled: bool = True
    # AD-458b: optional LLM-tier reachability and token-budget checks.
    # Default-True on _check_enabled flags so the wiring is live; the
    # token-budget check is harmless under AD-469 v1 (`check_budgets()`
    # returns `[]`) and activates automatically once AD-469b lands.
    # `token_budget_blocking` defaults False — warn rather than abort
    # until operator confidence builds.
    llm_tier_check_enabled: bool = True
    required_llm_tier: str = "deep"
    token_budget_check_enabled: bool = True
    token_budget_blocking: bool = False


class EngineeringConfig(BaseModel):
    """Engineering crew configuration (AD-457)."""

    enabled: bool = True
    performance_interval_seconds: float = Field(default=10.0, ge=1.0)
    maintenance_interval_seconds: float = Field(default=300.0, ge=60.0)
    damage_control_cooldown_seconds: float = Field(default=60.0, ge=1.0)


class InfrastructureConfig(BaseModel):
    """Engineering infrastructure configuration (AD-466)."""

    enabled: bool = True
    backup_enabled: bool = True
    backup_subdir: str = "backups"

class DegradationConfig(BaseModel):
    """Saucer separation / graceful degradation (AD-459 / AD-459b).

    AD-459 v1 shipped the read-only coordinator (always-wired, no
    operator-tunable fields). AD-459b adds active subsystem pause/resume
    hooks gated by ``auto_pause_enabled`` (default False per Wave-10
    convention #14 — transitional flag, default off until validated in
    rehearsal). When True, finalize.py registers ``dream_scheduler`` and
    ``proactive_loop`` adopters via ``LifecycleAdapter``; the manager
    invokes their pause/resume callbacks on tier-mask transitions.

    Future: custom policies, stress-level thresholds, operator override
    for shed-ESSENTIAL emergency mode.
    """

    auto_pause_enabled: bool = False


class InfodynamicConfig(BaseModel):
    """Infodynamic telemetry configuration (AD-491)."""

    enabled: bool = True
    event_window_seconds: float = Field(default=3600.0, ge=60.0)
    trust_buckets: int = Field(default=10, ge=2, le=100)


class GroundTruthConfig(BaseModel):
    """Ground-truth task verification configuration (AD-528, AD-528b, AD-528c)."""

    enabled: bool = True
    threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    event_window_seconds: float = Field(default=600.0, ge=10.0)
    write_episode: bool = True
    # AD-528b: active rejection & metadata quarantine. Default False per
    # Convention #14 (transitional flag) + Convention #3 (default off until
    # caller integration lands at AD-528b-2). When True, finalize.py
    # constructs a GroundTruthRejectionGate that wraps the verifier; the
    # gate emits VERIFICATION_REJECTED + WORK_ITEM_QUARANTINED on the
    # rejection branch and writes a quarantine payload into the work item's
    # metadata under `quarantine_metadata_key`.
    active_rejection_enabled: bool = False
    quarantine_metadata_key: str = "ground_truth_quarantine"
    # AD-528c: trust-network feedback. Default False per Convention #14
    # (transitional flag) + Convention #3 (default off until fleet rehearsal
    # confirms no false-positive trust drops, AD-528c-1). When True,
    # finalize.py registers a GroundTruthTrustFeedback listener that
    # subscribes to VERIFICATION_PASSED + VERIFICATION_FAILED and calls
    # runtime.trust_network.record_outcome(...) — the public API that
    # internally stores raw (alpha, beta) per ProbOS principle 3.
    # VERIFICATION_REJECTED is NOT consumed in v1 (every REJECTED co-fires
    # with FAILED inside verifier.verify(); double-counting prevention).
    # REJECTED-aware weighting is deferred to AD-528c-1.
    trust_feedback_enabled: bool = False
    trust_feedback_success_weight: float = Field(default=1.0, ge=0.0)
    trust_feedback_failure_weight: float = Field(default=0.5, ge=0.0)


class OperationsConfig(BaseModel):
    """Operations crew configuration (AD-467)."""

    enabled: bool = True
    resource_interval_seconds: float = Field(default=30.0, ge=1.0)
    resource_emit_interval_seconds: float = Field(default=60.0, ge=10.0)
    scheduler_interval_seconds: float = Field(default=60.0, ge=10.0)
    coordinator_interval_seconds: float = Field(default=60.0, ge=10.0)


class ModelRoutingConfig(BaseModel):
    """Model routing configuration (AD-463)."""

    enabled: bool = True
    cost_ceiling_per_million_output_tokens: float | None = None  # USD; None disables


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


class DepartmentProfilesConfig(BaseModel):
    """AD-656: dict of department-name -> DepartmentCognitiveProfile."""

    profiles: dict[str, DepartmentCognitiveProfile] = Field(default_factory=dict)


class EPSDepartmentConfig(BaseModel):
    """One department's EPS allocation entry (AD-469)."""

    name: str
    percent: float = Field(default=0.0, ge=0.0, le=1.0)
    priority: int = Field(default=5, ge=1, le=10)


class EPSConfig(BaseModel):
    """EPS - Compute/Token Distribution (AD-469)."""

    enabled: bool = True
    window_seconds: float = Field(default=60.0, ge=10.0)
    over_budget_threshold: float = Field(default=1.25, ge=1.0, le=10.0)
    departments: list[EPSDepartmentConfig] = Field(
        default_factory=lambda: [
            EPSDepartmentConfig(name="engineering", percent=0.30, priority=3),
            EPSDepartmentConfig(name="science", percent=0.20, priority=4),
            EPSDepartmentConfig(name="medical", percent=0.15, priority=2),
            EPSDepartmentConfig(name="security", percent=0.15, priority=2),
            EPSDepartmentConfig(name="operations", percent=0.10, priority=4),
            EPSDepartmentConfig(name="other", percent=0.10, priority=6),
        ]
    )


class MCPServerConfig(BaseModel):
    """One MCP server registration entry (AD-449)."""

    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class MCPConfig(BaseModel):
    """MCP Bridge configuration (AD-449)."""

    enabled: bool = True
    request_timeout_seconds: float = Field(default=30.0, ge=1.0)
    servers: list[MCPServerConfig] = Field(default_factory=list)


class ObservabilityBridgeConfig(BaseModel):
    """AD-641a: Observability Bridge configuration."""

    enabled: bool = True
    publish_interval_seconds: float = 60.0
    system_channel: str = "system_observability"


class ThresholdAlertConfig(BaseModel):
    """AD-695: Threshold-driven bridge alerts.

    Default-False — opt-in until a node operator chooses to surface health
    breaches into the ward room. Replaces the AD-641a continuous-posting
    loop with on-breach-only notifications.
    """

    enabled: bool = False
    pool_saturation_floor: float = Field(default=0.9, ge=0.0, le=1.0)
    degradation_min_severity: str = "degraded"
    attention_queue_depth: int = Field(default=20, ge=0)
    dedup_window_seconds: float = Field(default=300.0, ge=1.0)


class WardRoomHebbianConfig(BaseModel):
    """AD-641b: Ward Room Hebbian Router configuration."""

    enabled: bool = True
    learning_rate: float = 0.10
    decay_factor: float = 0.99


class EngineeringSensorsConfig(BaseModel):
    """AD-641f: Engineering Chief Observability configuration."""

    enabled: bool = True
    report_interval_seconds: float = 60.0
    auto_start_periodic_report: bool = False


class LearnedShortcutsConfig(BaseModel):
    """AD-641e: LearnedShortcut Registry configuration."""

    enabled: bool = True
    register_workflow_cache: bool = True


class ThreadPriorityConfig(BaseModel):
    """AD-641c: Ward Room Thread Priority configuration."""

    enabled: bool = True
    weight_captain: float = 0.30
    weight_unresolved: float = 0.20
    weight_cross_department: float = 0.15
    weight_recency: float = 0.20
    weight_endorsement: float = 0.15
    captain_callsign: str = "Captain"


class DeliberationConfig(BaseModel):
    """AD-641d: Crew Deliberation Protocol configuration."""

    enabled: bool = True
    captain_callsign: str = "Captain"


class SecurityInfraConfig(BaseModel):
    """Security infrastructure configuration (AD-456 + AD-456b).

    Distinct from ``SecurityConfig`` (AD-455) which configures threat detection,
    input validation, trust integrity, and red-team coordination.
    """

    secrets_persistence_enabled: bool = True
    secrets_store_filename: str = "secrets.json"
    egress_enabled: bool = True
    egress_deny_by_default: bool = True  # v1: real-signal default per no-theater
    audit_enabled: bool = True

    # AD-456b: Runtime Sandboxing
    sandbox_enabled: bool = True
    sandbox_default_wall_timeout_seconds: float = 30.0
    sandbox_default_memory_peak_mb: float = 256.0
    # AD-456b: Egress active enforcement (v1 default False — preserves AD-456
    # consultation-only behavior on existing deployments; flip to True at upgrade
    # time after reviewing allowlist coverage. AD-456b-7 will flip default to True
    # once fleet-wide allowlist coverage is verified.).
    egress_active_enforcement: bool = False

    # AD-456c: Per-tier credential lookup gate (v1 default False — preserves
    # AD-456 ungated-lookup behavior on existing deployments; flip to True at
    # upgrade time after reviewing per-spec ``min_tier`` coverage. AD-456c-5
    # will flip default to True once fleet-wide ``min_tier`` coverage is
    # verified AND caller-side ``tier=`` argument propagation (AD-456c-2)
    # has landed in all production credential-using agent paths.).
    credential_tier_enforcement: bool = False

    # AD-456d: AuditLog SQLite persistence (v1 default False — preserves
    # AD-456 in-memory-only audit chain on existing deployments; flip to
    # True at upgrade time after rehearsing rehydrate-on-boot against a
    # production-shaped audit trail. AD-456d-4 will flip default to True
    # once AD-456d-1 (shutdown-flush hook) lands.).
    audit_persistence_enabled: bool = False
    audit_persistence_filename: str = "audit_log.db"


class PermissionsConfig(BaseModel):
    """AD-711: declarative permission lists (enforcement deferred to AD-711-1)."""

    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class SecurityConfig(BaseModel):
    """Security Team configuration (AD-455).

    AD-711 (Wave 130): adds ``profile`` and ``permissions`` fields for
    claude-bootstrap-derived secure-by-default init wizard. ``profile`` is
    a declarative marker; ``permissions.deny`` is consumed at the wizard +
    doctor layer today and at the runtime enforcement layer in AD-711-1.
    """

    enabled: bool = True
    max_payload_bytes: int = Field(default=65536, ge=1024)
    rate_window_seconds: float = Field(default=60.0, ge=1.0)
    rate_max_requests: int = Field(default=60, ge=1)
    max_threat_severity: float = Field(default=0.80, ge=0.0, le=1.0)
    burst_window_seconds: float = Field(default=60.0, ge=1.0)
    burst_threshold: int = Field(default=20, ge=2)
    campaign_interval_seconds: float = Field(default=3600.0, ge=60.0)
    # AD-607: Memory security framework (Wave 92).
    memory: "MemorySecurityConfig" = Field(default_factory=lambda: MemorySecurityConfig())
    # AD-711: claude-bootstrap-derived security profile + permissions deny-list.
    profile: Literal["strict", "relaxed"] = "strict"
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)


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


class OnboardingConfig(BaseModel):
    """AD-442: Onboarding ceremony configuration."""

    enabled: bool = True
    activation_trust_threshold: float = 0.65
    naming_ceremony: bool = True  # If False, agents keep seed callsigns


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


class NativeSWEHarnessConfig(BaseModel):
    """AD-549: Configuration for the native SWE agentic harness.

    Default-False on ``enabled`` per AD-695 transitional-flag precedent —
    pool wiring + tool registration happen unconditionally, but route
    selection in ``SoftwareEngineerAgent.perceive()`` requires opt-in.
    """

    enabled: bool = Field(
        default=False,
        description="Master gate. When False, builds route to existing native/visiting paths.",
    )
    eligibility_modify_only: bool = Field(
        default=True,
        description="Phase α default. Only modify-only builds (all targets exist) eligible.",
    )
    max_iterations: int = Field(default=25, ge=1, le=200)
    max_fix_iterations: int = Field(default=5, ge=1, le=20)
    token_budget: int | None = Field(default=None, ge=1024)
    compaction_threshold_pct: float = Field(default=0.8, ge=0.1, le=0.95)
    blocked_paths: list[str] = Field(
        default_factory=lambda: [
            "src/probos/security/",
            ".env",
            "config/sealed_modules.yaml",
        ],
        description="AD-548: Pre-hook denies tool calls touching these path substrings.",
    )


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


class BridgeAlertConfig(BaseModel):
    """Bridge Alerts — proactive Captain & crew notifications (AD-410)."""
    enabled: bool = False
    cooldown_seconds: float = 300        # Dedup window per alert type+subject
    trust_drop_threshold: float = 0.15   # Trust drop triggering advisory
    trust_drop_alert_threshold: float = 0.25  # Trust drop triggering alert
    resolve_clean_period: float = 3600.0       # AD-580: seconds before resolved alert can re-fire
    default_dismiss_duration: float = 14400.0  # AD-580: default dismiss duration (4 hours)


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


class EmergentDetectorConfig(BaseModel):
    """BF-124: Emergent detector calibration parameters."""
    cluster_edge_threshold: float = 0.3
    cluster_min_size: int = 3
    cluster_min_avg_weight: float = 0.25
    cluster_cooldown_seconds: float = 1800.0
    cluster_activity_window: float = 900.0  # BF-165: seconds without Hebbian interaction before suppressing cluster detection (0 = disabled)
    dream_min_history: int = 5  # BF-166: minimum dream reports before anomaly detection fires
    # BF-175: Minimum absolute floors — prevent false positives when baseline averages are low
    dream_anomaly_min_strengthened: int = 10  # ignore strengthened spikes below this count
    dream_anomaly_min_pruned: int = 5  # ignore pruning spikes below this count
    dream_anomaly_min_trust_adj: int = 10  # ignore trust adjustment spikes below this count
    # AD-556: Per-agent adaptive trust anomaly detection
    adaptive_window_size: int = 30     # Number of trust snapshots per agent for rolling window
    adaptive_z_threshold: float = 2.5  # Z-score threshold for personal baseline anomaly
    adaptive_debounce_count: int = 2   # Consecutive anomalous cycles required before escalation
    adaptive_min_history: int = 8      # Minimum history entries before adaptive detection activates


class NoveltyGateConfig(BaseModel):
    """AD-493: Semantic novelty gate — suppress rehashed observations."""
    enabled: bool = True
    # Cosine similarity threshold — observations above this vs any recent
    # fingerprint are considered "not novel" and suppressed.
    # MiniLM cosine: 0.85+ = near-paraphrase, 0.70-0.85 = same topic/different angle,
    # 0.50-0.70 = related topic, <0.50 = different topic.
    similarity_threshold: float = 0.82
    # How many recent observation fingerprints to retain per agent.
    max_fingerprints_per_agent: int = 50
    # Decay: fingerprints older than this (hours) are evicted, making
    # the topic "novel again." 0 = no decay (fingerprints persist until
    # max_fingerprints_per_agent pushes them out).
    decay_hours: float = 24.0
    # Minimum text length to gate. Very short responses (acknowledgments,
    # social replies) skip the novelty check.
    min_text_length: int = 80


class EarnedAgencyConfig(BaseModel):
    """Earned Agency — trust-tiered behavioral gating (AD-357)."""
    enabled: bool = False
    # AD-674: Graduated initiative thresholds
    initiative_trust_thresholds: dict[str, float] = {
        "responsive": 0.3,    # Ensign threshold
        "contributory": 0.5,  # Lieutenant threshold
        "proactive": 0.7,     # Commander threshold
    }


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


class DutyScheduleConfig(BaseModel):
    """Duty schedule definitions per agent type (AD-419)."""
    enabled: bool = True
    schedules: dict[str, list[DutyDefinition]] = {}
    use_work_items: bool = False  # AD-500: opt-in for duty WorkItem producer; flips to True in AD-500a-1


class ProactiveCognitiveConfig(BaseModel):
    """Proactive Cognitive Loop — periodic idle-think (Phase 28b)."""
    enabled: bool = False
    interval_seconds: float = 120.0
    cooldown_seconds: float = 300.0
    # AD-414: Trust signal weights for proactive thinks
    trust_reward_weight: float = 0.1        # Trust signal for successful proactive think (posted to Ward Room)
    trust_no_response_weight: float = 0.0   # Trust signal for [NO_RESPONSE] (0 = no signal, silence is fine)
    trust_duty_bonus: float = 0.1           # Additional trust weight when completing a scheduled duty
    duty_schedule: DutyScheduleConfig = DutyScheduleConfig()
    # AD-636: Stagger proactive agent dispatch across cycle interval
    stagger_enabled: bool = True
    min_stagger_seconds: float = 5.0


class PersistentTasksConfig(BaseModel):
    """Persistent Task Engine — SQLite-backed scheduled tasks (Phase 25a)."""
    enabled: bool = False
    tick_interval_seconds: float = 5.0
    max_concurrent_executions: int = 1   # Sequential by design
    dag_auto_resume: bool = False        # Future: auto-resume stale DAGs


class DiscordConfig(BaseModel):
    """Discord bot adapter configuration."""

    enabled: bool = False
    token: str = ""                          # Bot token (prefer env var PROBOS_DISCORD_TOKEN)
    allowed_channel_ids: list[int] = []      # Empty = respond in all channels
    allowed_user_ids: list[int] = []         # Empty = respond to all users (SECURITY RISK)
    command_prefix: str = "!"                # "!status" -> "/status"
    mention_required: bool = False           # Only respond when @mentioned
    scout_channel_id: int = 0                # Discord channel ID for scout reports (0 = disabled)


class SlackConfig(BaseModel):
    """Slack adapter configuration (AD-472)."""

    enabled: bool = False
    bot_token: str = ""           # xoxb-... (prefer env var PROBOS_SLACK_BOT_TOKEN)
    signing_secret: str = ""      # for events-api verification
    allowed_channel_ids: list[str] = []
    allowed_user_ids: list[str] = []
    default_thread_ts: bool = True


class WebhookConfig(BaseModel):
    """Webhook adapter configuration (AD-472)."""

    enabled: bool = False
    shared_secret: str = ""       # set via env var PROBOS_WEBHOOK_SECRET
    allowed_channels: list[str] = []


class ChannelsConfig(BaseModel):
    """Channel adapter configurations."""

    discord: DiscordConfig = DiscordConfig()
    slack: SlackConfig = SlackConfig()
    webhook: WebhookConfig = WebhookConfig()


class MedicalConfig(BaseModel):
    """Medical team pool configuration (AD-290)."""

    enabled: bool = True
    vitals_interval_seconds: float = 5.0
    vitals_window_size: int = 12
    pool_health_min: float = 0.5
    trust_floor: float = 0.3
    health_floor: float = 0.6
    max_trust_outliers: int = 3
    scheduled_diagnosis_interval: float = 300.0


class CounselorConfig(BaseModel):
    """Counselor cognitive wellness configuration (AD-503)."""

    enabled: bool = True
    profile_retention_days: int = 90
    trust_delta_threshold: float = 0.15
    sweep_max_agents: int = 50
    alert_on_red: bool = True
    alert_on_yellow: bool = False


class CaptainsLogConfig(BaseModel):
    """Captain's Log daily-narrative configuration (AD-477)."""

    enabled: bool = True
    output_dir: Path = Path("data/captains_log")
    end_of_day_hour: int = 23  # local hour to trigger generation
    top_episodes_count: int = 5
    importance_threshold: int = 5


class PlanOfDayConfig(BaseModel):
    """Plan of the Day morning-summary configuration (AD-477)."""

    enabled: bool = True
    output_dir: Path = Path("data/plan_of_day")
    start_of_day_hour: int = 8
    include_alert_conditions: bool = True


class NavalOrganizationConfig(BaseModel):
    """Naval Organization Protocols (AD-477) — v1 ships Captain's Log + Plan of the Day."""

    captains_log: CaptainsLogConfig = Field(default_factory=CaptainsLogConfig)
    plan_of_day: PlanOfDayConfig = Field(default_factory=PlanOfDayConfig)



class CircuitBreakerConfig(BaseModel):
    """Cognitive circuit breaker thresholds (AD-506a)."""

    velocity_threshold: int = 8
    velocity_window_seconds: float = 300.0
    similarity_threshold: float = 0.6
    similarity_min_events: int = 4
    base_cooldown_seconds: float = 900.0
    max_cooldown_seconds: float = 3600.0
    # Amber zone thresholds
    amber_similarity_ratio: float = 0.25  # Amber when similarity pair ratio exceeds this
    amber_velocity_ratio: float = 0.6     # Amber when velocity > this fraction of threshold
    amber_decay_seconds: float = 900.0    # 15 min quiet -> amber decays to green
    red_decay_seconds: float = 1800.0     # 30 min quiet -> red decays to amber
    critical_decay_seconds: float = 3600.0  # 1h quiet -> critical decays to red
    critical_trip_window_seconds: float = 3600.0  # Window for counting trips toward critical
    critical_trip_count: int = 3           # Trips in window to reach critical


class TraitAdaptiveConfig(BaseModel):
    """Trait-adaptive circuit breaker configuration (AD-494)."""

    enabled: bool = True


class ConcurrencyConfig(BaseModel):
    """AD-672: Per-agent concurrency management."""

    enabled: bool = True
    default_max_concurrent: int = 4
    queue_max_size: int = 10
    capacity_warning_ratio: float = 0.75
    role_overrides: dict[str, int] = Field(default_factory=lambda: {
        "bridge": 3,
        "operations": 6,
        "engineering": 5,
        "science": 4,
        "medical": 3,
        "security": 3,
    })


class TrustDampeningConfig(BaseModel):
    """Trust cascade dampening configuration (AD-558)."""

    # Progressive dampening
    dampening_window_seconds: float = 300.0
    dampening_geometric_factors: tuple[float, ...] = (1.0, 0.75, 0.5, 0.25)
    dampening_floor: float = 0.25

    # Hard trust floor
    hard_trust_floor: float = 0.05

    # Network circuit breaker
    cascade_agent_threshold: int = 3
    cascade_department_threshold: int = 2
    cascade_delta_threshold: float = 0.15
    cascade_window_seconds: float = 300.0
    cascade_global_dampening: float = 0.5
    cascade_cooldown_seconds: float = 600.0

    # Cold-start scaling
    cold_start_observation_threshold: float = 20.0
    cold_start_dampening_floor: float = 0.5


class EmergenceMetricsConfig(BaseModel):
    """Configuration for emergence metrics computation (AD-557)."""

    # PID computation
    pid_bins: int = 2  # K=2 quantile binning (per Riedl 2025)
    pid_permutation_shuffles: int = 50  # Significance testing
    pid_significance_threshold: float = 0.05  # p-value threshold

    # Thread analysis
    min_thread_contributors: int = 2  # Minimum agents in thread to analyze
    min_thread_posts: int = 3  # Minimum posts in thread to analyze
    thread_lookback_hours: float = 24.0  # How far back to look for threads

    # Coordination balance
    groupthink_redundancy_threshold: float = 0.8  # Flag when redundancy dominates
    fragmentation_synergy_threshold: float = 0.1  # Flag when synergy is near zero

    # ToM effectiveness
    tom_baseline_window: int = 20  # Initial threads to establish baseline
    tom_trend_min_samples: int = 10  # Minimum threads before computing trend

    # Hebbian correlation
    hebbian_synergy_min_interactions: int = 5  # Minimum Hebbian interactions to correlate


class EmergentLeadershipConfig(BaseModel):
    """Emergent leadership detection configuration (AD-439)."""

    enabled: bool = True
    min_weight: float = 0.10
    min_ratio: float = 1.5


class BehavioralMetricsConfig(BaseModel):
    """AD-569: Observation-Grounded Crew Intelligence Metrics."""

    # Thread analysis
    thread_lookback_hours: float = 72.0  # How far back to analyze threads
    min_thread_contributors: int = 2  # Minimum unique authors for a qualifying thread
    min_thread_posts: int = 3  # Minimum posts for a qualifying thread

    # Frame Diversity (Metric 1)
    frame_diversity_min_departments: int = 2  # Need 2+ departments represented

    # Synthesis Detection (Metric 2)
    synthesis_novelty_threshold: float = 0.35  # Cosine distance threshold for "novel"
    synthesis_min_thread_posts: int = 4  # Threads need 4+ posts for synthesis analysis

    # Cross-Department Trigger (Metric 3)
    trigger_correlation_window_hours: float = 24.0  # Window for topic trigger correlation
    trigger_topic_similarity_threshold: float = 0.6  # Cosine similarity for "same topic"

    # Convergence Correctness (Metric 4)
    convergence_similarity_threshold: float = 0.75  # When posts are "converging"
    convergence_min_agreeing: int = 2  # Minimum agents agreeing for convergence

    # Anchor-Grounded Emergence (Metric 5)
    anchor_independence_min_episodes: int = 3  # Minimum episodes for anchor analysis

    # Snapshot history
    max_snapshots: int = 100  # Rolling window of historical snapshots


class EventLogConfig(BaseModel):
    """Event log retention configuration."""
    retention_days: int = 7          # Delete events older than N days (0 = keep forever)
    max_rows: int = 100_000          # Hard cap on total rows (0 = no cap)
    prune_interval_seconds: float = 3600.0  # Check for pruning every N seconds


class CognitiveJournalConfig(BaseModel):
    """Cognitive Journal — append-only LLM reasoning trace store (AD-431)."""
    enabled: bool = True
    retention_days: int = 14         # Keep journal entries for N days (0 = keep forever)
    max_rows: int = 500_000          # Hard cap on total rows (0 = no cap)
    prune_interval_seconds: float = 3600.0


class KnowledgeEdgesConfig(BaseModel):
    """Knowledge Edge Store — typed-triple graph (AD-687).

    Default ``enabled=True`` is intentional and DEVIATES from the Wave-10
    transitional-flag convention. Rationale: this v1 ships an empty,
    write-only-when-called-by-consumers SQLite table. Consumers (Oracle
    Tier 6, Hebbian backfill, Dream Step 10) arrive in AD-688/689/690. With
    no consumers the store costs one CREATE TABLE IF NOT EXISTS at boot —
    invisible at runtime. Same precedent: ``CognitiveJournalConfig`` (also
    enabled=True for an infrastructure store).
    """
    enabled: bool = True
    db_path: str = "data/knowledge_edges.sqlite"
    max_traverse_hops: int = 3

    @field_validator("max_traverse_hops")
    @classmethod
    def _cap_hops(cls, v: int) -> int:
        if v < 1 or v > 3:
            raise ValueError(
                "knowledge_edges.max_traverse_hops must be in [1, 3] "
                "(MAX_HOPS_CEILING; research §Phase 1)"
            )
        return v


class KnowledgeEdgeClassificationConfig(BaseModel):
    """AD-692: Classification enforcement on knowledge graph edges.

    OSS extension point. Default ``enabled=True`` follows the same precedent
    as ``KnowledgeEdgesConfig`` — the wrapper is a transparent pass-through
    when ``requester_agent_id`` is ``None`` (system/internal callers,
    backward-compatible with Wave 37/38/39/40). Filtering only applies once
    consumers (Oracle Tier 6 via AD-688 plumbing) supply a requester id.
    """
    enabled: bool = True
    default_classification: str = "private"

    @field_validator("default_classification")
    @classmethod
    def _validate_default(cls, v: str) -> str:
        allowed = {"private", "department", "ship", "fleet"}
        if v.lower() not in allowed:
            raise ValueError(
                f"knowledge_edge_classification.default_classification "
                f"must be one of {sorted(allowed)}, got {v!r}"
            )
        return v.lower()


class EdgeBackfillConfig(BaseModel):
    """AD-689: One-shot backfill of ``knowledge_edges`` from existing data.

    Default ``enabled=True`` follows the same precedent as
    ``KnowledgeEdgesConfig`` — the warm-boot wirer is a no-op once the table
    has any rows (idempotency-by-row-count guard). The first cold boot after
    AD-689 lands populates the graph from ontology/Hebbian/episodes/DECISIONS;
    subsequent boots see ``find_edges(limit=1) != []`` and skip.
    """
    enabled: bool = True
    run_on_warm_boot: bool = True
    hebbian_threshold: float = 0.5
    force: bool = False
    decisions_paths: list[str] = Field(
        default_factory=lambda: [
            "DECISIONS.md",
            "decisions-era-1-genesis.md",
            "decisions-era-2-emergence.md",
            "decisions-era-3-product.md",
            "decisions-era-4-evolution.md",
        ]
    )

    @field_validator("hebbian_threshold")
    @classmethod
    def _check_threshold(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("edge_backfill.hebbian_threshold must be in [0.0, 1.0]")
        return v


class ClinicalTelemetryConfig(BaseModel):
    """AD-635 / AD-635b / AD-635c: Clearance-gated clinical query facade (Medical / Counselor).

    AD-635 v1 shipped the read-only query facade with a bounded in-memory
    audit ring (``audit_max_entries`` deque). AD-635b adds optional
    SQLite persistence of the audit ring for post-incident review,
    gated by ``audit_persistence_enabled``. AD-635c adds optional
    SQLite persistence of cognitive-circuit-breaker state and zone
    transitions, gated by ``circuit_breaker_history_persistence_enabled``,
    plus a clearance-gated ``query_circuit_breaker_history`` method on
    ``ClinicalTelemetryService`` that reads from the durable store.

    Each persistence flag defaults False per Wave-10 convention #14
    (transitional flag, default off until validated). The service is
    invisible at runtime out-of-the-box (``enabled=False``). Captain
    opts in via YAML; each persistence side requires its own opt-in.
    """
    enabled: bool = False
    audit_max_entries: int = 1000
    audit_persistence_enabled: bool = False
    audit_db_path: str = "data/clinical_audit.db"
    circuit_breaker_history_persistence_enabled: bool = False
    circuit_breaker_history_db_path: str = "data/circuit_breaker_history.db"


class ProcessChainRegistryConfig(BaseModel):
    """AD-647b v1: Registry of named process chains (`ProcessChainDefinition`).

    Default-True is intentional — registry construction cost is one empty
    dict + one ``register_chain(SCOUT_REPORT_CHAIN)`` call at boot, and
    Scout's ``act()`` depends on the registry being present (the
    module-level fallback is a defensive belt — disabling the registry
    would still log a WARNING per scout invocation).
    """
    enabled: bool = True


class ConsultationWorkspaceConfig(BaseModel):
    """AD-594a v1: Session-scoped consultation workspace registry.

    Default-True is intentional — the registry is read-only on boot (constructs
    an empty in-memory cache and ensures the ``consultations/`` subdir exists
    in Ship's Records). No automatic side effects until an agent calls
    ``runtime.consultation_workspaces.create(...)``. Same precedent as
    ``KnowledgeEdgesConfig`` / ``EdgeBackfillConfig``.
    """
    enabled: bool = True
    root_path: str = "consultations"
    input_processor: str = "passthrough"


class ConsultationDeliveryConfig(BaseModel):
    """AD-594d v1: Consultation delivery pipeline.

    Default-True is intentional — pipeline construction is read-only on boot
    (registers built-in adapters into an in-memory dict; no IO). Workspaces
    consume the pipeline only when an agent calls ``runtime.consultation_delivery
    .deliver(...)``. Same precedent as ``ConsultationWorkspaceConfig``.
    """
    enabled: bool = True
    # Adapter enablement — operators can disable individual adapters without
    # disabling the pipeline. Disabled adapters are not registered.
    local_file_enabled: bool = True
    github_enabled: bool = True
    # LocalFileAdapter: list of allowed destination root paths (absolute or
    # tilde-expandable). Empty = LocalFileAdapter registered with no roots
    # (rejects every delivery with "no allowed_roots configured").
    local_file_allowed_roots: list[str] = Field(default_factory=list)
    # GitHubAdapter: env var name from which the token is read at delivery time.
    github_token_env: str = "GITHUB_TOKEN"
    # Default approval requirement — used when a request does not specify
    # requires_approval explicitly via the dataclass default of False.
    default_requires_approval: bool = False


class ConsultationDispatchConfig(BaseModel):
    """AD-594c v1: Parallel execution dispatch.

    Default-True is intentional — dispatcher construction is read-only on boot
    (no IO; only resolves runtime.work_item_store + runtime.consultation_workspaces
    references). Side effects only fire when an agent calls
    ``runtime.consultation_dispatcher.dispatch(...)``. Same precedent as
    ``ConsultationWorkspaceConfig`` / ``ConsultationDeliveryConfig``.
    """
    enabled: bool = True
    # Default work_type used for WorkItems created by the dispatcher when a
    # plan spec does not specify one. "duty" is registered in the WorkTypeRegistry.
    default_work_type: str = "duty"
    # Tags applied to every dispatched WorkItem in addition to the workspace_id
    # tag — used by get_progress to scope list_work_items queries.
    default_tags: list[str] = Field(default_factory=lambda: ["consultation"])
    # Blocker escalation: emit PARALLEL_DISPATCH_BLOCKED when a spec's depends_on
    # set has been unmet for at least this many seconds since dispatch.
    blocker_threshold_seconds: float = 600.0
    # Progress event emission cadence (caller-driven; no internal timer in v1).
    # When True, get_progress() emits PARALLEL_DISPATCH_PROGRESS on each call.
    progress_subscription_enabled: bool = True


class HybridDispatchConfig(BaseModel):
    """AD-581 v1: Hybrid dispatch routing policy (581a + 581d).

    Default-True is intentional — DepartmentDispatcher construction is
    read-only on boot (no IO; only resolves runtime.hebbian_router +
    runtime.ontology references). The WorkItemRouter side-effect path
    activates only when a WORK_ITEM_CREATED event fires. Same precedent
    as ConsultationDispatchConfig / ConsultationDeliveryConfig.

    AD-581b order protocol additions are unconditional — declining or
    refusing an order is always available on OrderManager regardless of
    this config; the gate here governs the auto-routing layer only.
    """

    enabled: bool = True

    # AD-581d: Routing confidence thresholds.
    confidence_threshold: float = 0.4
    confidence_margin: float = 0.05
    min_hebbian_weight: float = 0.05

    # AD-581d: Per-(intent_type, agent_id) success-rate ring buffer.
    success_rate_window: int = 50
    min_samples_for_routing: int = 3

    # AD-581a: WorkItemRouter activation criteria.
    dispatchable_tags: list[str] = Field(default_factory=lambda: ["consultation"])

    @field_validator("confidence_threshold", "confidence_margin", "min_hebbian_weight")
    @classmethod
    def _weight_in_unit(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("weight must be in [0.0, 1.0]")
        return v

    @field_validator("success_rate_window")
    @classmethod
    def _window_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("success_rate_window must be >= 1")
        return v

    @field_validator("min_samples_for_routing")
    @classmethod
    def _min_samples_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("min_samples_for_routing must be >= 1")
        return v


class CommunicationsConfig(BaseModel):
    """Communications settings (AD-485)."""
    dm_min_rank: str = "ensign"  # Minimum rank to send DMs: ensign|lieutenant|commander|senior
    recreation_min_rank: str = "ensign"  # Minimum rank for game challenges: ensign|lieutenant|commander|senior


class WorkforceConfig(BaseModel):
    """Workforce Scheduling Engine configuration (AD-496)."""
    enabled: bool = False
    tick_interval_seconds: float = 10.0
    default_capacity: int = 1           # Default concurrent task limit per agent
    custom_work_types: list[dict] = []
    custom_templates: list[dict] = []
    template_config_path: str = "config/work_templates.yaml"


class TemporalConfig(BaseModel):
    """AD-502: Temporal awareness configuration."""
    enabled: bool = True
    include_birth_time: bool = True
    include_system_uptime: bool = True
    include_last_action: bool = True
    include_post_count: bool = True
    include_episode_timestamps: bool = True


class SystemInfo(BaseModel):
    """Top-level system identity."""

    name: str = "ProbOS"
    version: str = "0.1.0"
    log_level: str = "INFO"


class CommunicationBenchmarksConfig(BaseModel):
    """AD-642: Communication Quality Benchmarks configuration."""

    enabled: bool = True
    frequency_hours: float = 12.0
    probes: list[str] = [
        "thread_relevance",
        "memory_grounding",
        "memory_absence",
        "expertise",
        "silence_appropriateness",
        "dm_action",
    ]


class BillConfig(BaseModel):
    """Configuration for the Bill System runtime (AD-618b)."""

    # Maximum concurrent bill instances (0 = unlimited)
    max_concurrent_instances: int = 10

    # Default step timeout in seconds (0 = no timeout)
    default_step_timeout_seconds: float = 300.0

    # Whether to allow bills to activate with unfilled roles
    allow_partial_assignment: bool = False


class QualificationConfig(BaseModel):
    """Configuration for the Crew Qualification Battery (AD-566)."""

    enabled: bool = True
    baseline_auto_capture: bool = True
    significance_threshold: float = 0.15
    test_timeout_seconds: float = 60.0

    # AD-595e: Qualification Gate Enforcement
    enforcement_enabled: bool = False
    enforcement_log_only: bool = True

    # AD-642: Communication Quality Benchmarks
    communication_benchmarks: CommunicationBenchmarksConfig = CommunicationBenchmarksConfig()

    # AD-566c: Drift Detection Pipeline
    drift_check_enabled: bool = True
    drift_check_interval_seconds: float = 604800.0  # 1 week
    drift_warning_sigma: float = 2.0    # Counselor alert threshold
    drift_critical_sigma: float = 3.0   # Bridge/Captain alert threshold
    drift_min_samples: int = 3          # Minimum data points before drift analysis
    drift_history_window: int = 20      # Max historical results for stats
    drift_cooldown_seconds: float = 3600.0  # Min time between alerts per agent+test
    drift_check_tiers: list[int] = [1, 2, 3]  # AD-566d/e: Which tiers the drift scheduler runs


class NatsConfig(BaseModel):
    """NATS event bus configuration (AD-637)."""

    enabled: bool = Field(
        default=False,
        validate_default=True,
        description="Enable NATS event bus. Overridden by PROBOS_NATS_ENABLED env var.",
    )

    @field_validator("enabled", mode="before")
    @classmethod
    def _env_override_enabled(cls, v: Any) -> Any:
        """BF-245: Allow env var to force-disable NATS in test workers."""
        env_val = os.environ.get("PROBOS_NATS_ENABLED")
        if env_val is not None:
            return env_val.lower() in ("true", "1", "yes")
        return v

    url: str = "nats://localhost:4222"
    connect_timeout_seconds: float = 5.0
    max_reconnect_attempts: int = 60
    reconnect_time_wait_seconds: float = 2.0
    drain_timeout_seconds: float = 5.0

    # JetStream
    jetstream_enabled: bool = True
    jetstream_domain: str | None = None  # For leaf node isolation

    # Subject prefix — derived from ship DID at runtime, fallback for local
    subject_prefix: str = "probos.local"

    # BF-230: JetStream publish timeout (seconds) — raised from nats-py default
    # to tolerate CPU load spikes. Applied per-publish, not connection-level.
    js_publish_timeout: float = 5.0


class AgentTierConfig(BaseModel):
    """Agent tier classification for trust separation (AD-571)."""

    crew_types: list[str] = Field(default_factory=lambda: [
        "architect", "builder", "code_reviewer", "counselor",
        "diagnostician", "surgeon", "pharmacist", "pathologist",
        "red_team", "system_qa", "scout",
        "data_analyst", "systems_analyst", "research_specialist",
    ])
    core_types: list[str] = Field(default_factory=lambda: ["event_log", "vitals_monitor", "introspect"])


class OperationalStatusConfig(BaseModel):
    """Operational status tracker configuration (AD-571b)."""

    # Number of recent calls retained per agent for rolling metrics.
    sample_window_size: int = 50
    # Minimum success rate to be considered AVAILABLE. Below this → DEGRADED.
    available_success_rate: float = 0.85
    # p95 latency (ms) above which an otherwise-healthy agent is DEGRADED.
    degraded_p95_latency_ms: float = 5000.0
    # Consecutive error count that flips an agent to OFFLINE.
    offline_consecutive_errors: int = 5


class BridgeConfig(BaseModel):
    """Episodic-procedural bridge configuration (AD-572)."""

    enabled: bool = True
    min_cross_cycle_episodes: int = 5
    novelty_threshold: float = 0.3


class SelfDistillationConfig(BaseModel):
    """Configuration for AD-487 self-distillation v1 (Map step only)."""

    enabled: bool = True
    rate_limit_hours: int = 24
    llm_timeout_seconds: float = 30.0
    max_sub_topics: int = 5
    db_path: Path = Path("data/agent_probes.db")


class CreativeExpressionConfig(BaseModel):
    """Configuration for AD-525 v1 (Skills Inventory + Records Output)."""

    enabled: bool = True
    default_classification: Literal["ship", "department", "private"] = "ship"


class ClassificationGateConfig(BaseModel):
    """Configuration for AD-530 v1 disclosure gate."""

    enabled: bool = True
    # v1: pattern set is hardcoded; register_pattern is runtime-only.


class AutonomyBoundariesConfig(BaseModel):
    """AD-511 v1: Agent Autonomy Boundaries (registry + observational detector)."""

    enabled: bool = True
    # v1: 5 federation-tier boundaries + 6 detection patterns are hardcoded.
    # register_pattern is runtime-only. Active blocking is AD-511b.


class CrewDevelopmentConfig(BaseModel):
    """AD-507 v1: Crew Development Framework (Core Knowledge Curriculum Registry)."""

    enabled: bool = True
    # v1: 9 default modules are hardcoded. register_module is runtime-only.
    # Progression tracking, competency assessment, and Standing Orders
    # integration are deferred to AD-507b/c/d.


class BootCampPhaseConfig(BaseModel):
    """AD-509 v1: Boot Camp Phase Tracker (in-memory observational).

    Disambiguated from AD-638 ``BootCampConfig`` (cold-start boot camp); the
    AD-509 v1 tracker records 5-phase progression per agent.
    """

    enabled: bool = True
    # v1: tracker only. A-School curriculum, graduated stimuli,
    # completion-criteria gating, and trait-adaptive pacing are deferred
    # to AD-509b/c/d/e.


class DiscoveryLearningConfig(BaseModel):
    """AD-512 v1: Discovery-Based Capability Building substrate (observational).

    Default-True follows AD-507/509/511 v1 precedent — substrate is in-memory
    only, emits events, no resource creation, no I/O, no LLM calls. The
    eventual AD-486 Holodeck wave is the consumer that drives outcomes
    through this substrate; v1 ships the registry + per-agent maps + ZPD
    calibrator without that consumer.
    """

    enabled: bool = True
    # v1: 8 default scenarios + Beta(1,1) confidence priors + scaffolding
    # heuristic. Hebbian writes, episode storage, and Holodeck wiring are
    # caller responsibilities and are deferred to AD-486 / AD-510.
    confidence_prior_alpha: float = Field(default=1.0, ge=0.01)
    confidence_prior_beta: float = Field(default=1.0, ge=0.01)
    zpd_lower_bound: float = Field(default=0.40, ge=0.0, le=1.0)
    zpd_upper_bound: float = Field(default=0.75, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_zpd_band(self) -> "DiscoveryLearningConfig":
        if self.zpd_lower_bound >= self.zpd_upper_bound:
            raise ValueError(
                "zpd_lower_bound must be strictly less than zpd_upper_bound"
            )
        return self


class ScopedCognitionConfig(BaseModel):
    """AD-508 v1: Duty Scope helper (read-only observational)."""

    enabled: bool = True


class WorkspaceOntologyConfig(BaseModel):
    """AD-478 v1: Workspace Ontology read-only register (frequency-bounded)."""

    enabled: bool = True
    max_terms: int = 1000


class GapPipelineExtensionsConfig(BaseModel):
    """AD-539c + AD-539d v1 config (observational gap pipeline extensions)."""

    remediation_tracker_enabled: bool = True
    fleet_aggregator_enabled: bool = True
    remediation_max_history: int = 100
    # AD-539c-i: opt-in active remediation. Default-False keeps observational
    # mode the default; flip to True to actually trigger qualifications,
    # request data routing, and escalate capability gaps.
    active_remediation_enabled: bool = False


class SPCConfig(BaseModel):
    """AD-522 v1: Statistical Process Control (calibration profile + WE rules)."""

    enabled: bool = True
    sample_window: int = 100


class ExtensionsConfig(BaseModel):
    """AD-481: Extension subsystem master config.

    Mirrors src/probos/extensions/protocol.py:ExtensionsConfig — duplicated here
    to avoid circular import (config.py is imported very early; the extensions/
    package imports config indirectly via runtime).
    """

    enabled: bool = False
    enforce_sealed_core: bool = False
    default_profile: str = "minimal"
    extensions_dir: str = "src/probos/extensions"


class SystemConfig(BaseModel):
    """Root configuration model."""

    system: SystemInfo = SystemInfo()
    pools: PoolConfig = PoolConfig()
    mesh: MeshConfig = MeshConfig()
    consensus: ConsensusConfig = ConsensusConfig()
    cognitive: CognitiveConfig = CognitiveConfig()
    health_probe_interval_seconds: float = 30.0  # BF-246: Periodic LLM connectivity probe
    memory: MemoryConfig = MemoryConfig()
    dreaming: DreamingConfig = DreamingConfig()
    dream_wm: DreamWMConfig = DreamWMConfig()  # AD-671
    scaling: ScalingConfig = ScalingConfig()
    federation: FederationConfig = FederationConfig()
    self_mod: SelfModConfig = SelfModConfig()
    qa: QAConfig = QAConfig()
    knowledge: KnowledgeConfig = KnowledgeConfig()
    records: RecordsConfig = RecordsConfig()
    archive: ArchiveConfig = ArchiveConfig()
    telemetry: TelemetryConfig = TelemetryConfig()  # AD-461
    post_budget_telemetry: PostBudgetTelemetryConfig = PostBudgetTelemetryConfig()  # BF-238
    confidence: ConfidenceConfig = ConfidenceConfig()  # AD-444
    lint: LintConfig = LintConfig()  # AD-563
    quality_trigger: QualityTriggerConfig = QualityTriggerConfig()  # AD-564
    quality_router: QualityRouterConfig = QualityRouterConfig()  # AD-565
    onboarding: OnboardingConfig = OnboardingConfig()
    holodeck_birth_chamber: HolodeckBirthChamberConfig = HolodeckBirthChamberConfig()
    holodeck_scenarios: HolodeckScenarioConfig = HolodeckScenarioConfig()
    team_simulations: HolodeckTeamSimulationConfig = HolodeckTeamSimulationConfig()
    naming: NamingConfig = NamingConfig()  # AD-499
    runtime_overrides: RuntimeOverridesConfig = RuntimeOverridesConfig()  # AD-468
    utility_agents: UtilityAgentsConfig = UtilityAgentsConfig()
    swe_specialists: SoftwareEngineerSpecialistsConfig = Field(
        default_factory=SoftwareEngineerSpecialistsConfig
    )
    native_swe_harness: NativeSWEHarnessConfig = Field(
        default_factory=NativeSWEHarnessConfig,
        description="AD-549: Native SWE agentic harness configuration.",
    )
    ward_room: WardRoomConfig = WardRoomConfig()
    assignments: AssignmentConfig = AssignmentConfig()
    bridge_alerts: BridgeAlertConfig = BridgeAlertConfig()
    firewall: FirewallConfig = FirewallConfig()
    security: SecurityConfig = SecurityConfig()  # AD-455
    emergent_detector: EmergentDetectorConfig = EmergentDetectorConfig()
    novelty_gate: NoveltyGateConfig = NoveltyGateConfig()
    earned_agency: EarnedAgencyConfig = EarnedAgencyConfig()
    proactive_cognitive: ProactiveCognitiveConfig = ProactiveCognitiveConfig()
    persistent_tasks: PersistentTasksConfig = PersistentTasksConfig()
    channels: ChannelsConfig = ChannelsConfig()
    medical: MedicalConfig = MedicalConfig()
    counselor: CounselorConfig = CounselorConfig()
    circuit_breaker: CircuitBreakerConfig = CircuitBreakerConfig()
    trait_adaptive: TraitAdaptiveConfig = TraitAdaptiveConfig()  # AD-494
    concurrency: ConcurrencyConfig = ConcurrencyConfig()  # AD-672
    trust_dampening: TrustDampeningConfig = TrustDampeningConfig()
    emergence_metrics: EmergenceMetricsConfig = EmergenceMetricsConfig()
    emergent_leadership: EmergentLeadershipConfig = EmergentLeadershipConfig()  # AD-439
    orders: OrdersConfig = OrdersConfig()  # AD-440
    validation_framework: ValidationFrameworkConfig = ValidationFrameworkConfig()  # AD-451
    pre_flight: PreFlightConfig = PreFlightConfig()  # AD-458
    engineering: EngineeringConfig = EngineeringConfig()  # AD-457
    degradation: DegradationConfig = DegradationConfig()  # AD-459
    infodynamic: InfodynamicConfig = InfodynamicConfig()  # AD-491
    infrastructure: InfrastructureConfig = InfrastructureConfig()  # AD-466
    security_infra: SecurityInfraConfig = SecurityInfraConfig()  # AD-456
    ground_truth: GroundTruthConfig = GroundTruthConfig()  # AD-528
    operations: OperationsConfig = OperationsConfig()  # AD-467
    model_routing: ModelRoutingConfig = ModelRoutingConfig()  # AD-463
    ready_room: ReadyRoomConfig = ReadyRoomConfig()  # AD-475
    dept_profiles: DepartmentProfilesConfig = DepartmentProfilesConfig()  # AD-656
    eps: EPSConfig = EPSConfig()  # AD-469
    mcp: MCPConfig = MCPConfig()  # AD-449
    mcp_app_host: MCPAppHostConfig = Field(default_factory=MCPAppHostConfig)  # AD-597
    spatial_explorer: SpatialExplorerConfig = Field(default_factory=SpatialExplorerConfig)  # AD-520
    knowledge_browser: KnowledgeBrowserConfig = Field(default_factory=KnowledgeBrowserConfig)  # AD-562
    extensions: ExtensionsConfig = Field(default_factory=ExtensionsConfig)  # AD-481
    observability_bridge: ObservabilityBridgeConfig = Field(default_factory=ObservabilityBridgeConfig)  # AD-641a
    threshold_alerts: ThresholdAlertConfig = Field(default_factory=ThresholdAlertConfig)  # AD-695
    ward_room_hebbian: WardRoomHebbianConfig = Field(default_factory=WardRoomHebbianConfig)  # AD-641b
    engineering_sensors: EngineeringSensorsConfig = Field(default_factory=EngineeringSensorsConfig)  # AD-641f
    learned_shortcuts: LearnedShortcutsConfig = Field(default_factory=LearnedShortcutsConfig)  # AD-641e
    thread_priority: ThreadPriorityConfig = Field(default_factory=ThreadPriorityConfig)  # AD-641c
    deliberation: DeliberationConfig = Field(default_factory=DeliberationConfig)  # AD-641d
    behavioral_metrics: BehavioralMetricsConfig = BehavioralMetricsConfig()
    event_log: EventLogConfig = EventLogConfig()
    cognitive_journal: CognitiveJournalConfig = CognitiveJournalConfig()
    knowledge_edges: KnowledgeEdgesConfig = Field(default_factory=KnowledgeEdgesConfig)  # AD-687
    knowledge_edge_classification: KnowledgeEdgeClassificationConfig = Field(
        default_factory=KnowledgeEdgeClassificationConfig
    )  # AD-692
    edge_backfill: EdgeBackfillConfig = Field(default_factory=EdgeBackfillConfig)  # AD-689
    communications: CommunicationsConfig = CommunicationsConfig()
    workforce: WorkforceConfig = WorkforceConfig()
    temporal: TemporalConfig = TemporalConfig()
    qualification: QualificationConfig = QualificationConfig()
    orientation: OrientationConfig = OrientationConfig()
    social_verification: SocialVerificationConfig = SocialVerificationConfig()
    anomaly_window: AnomalyWindowConfig = AnomalyWindowConfig()  # AD-673
    working_memory: WorkingMemoryConfig = WorkingMemoryConfig()
    predictive_branching: PredictiveBranchingConfig = PredictiveBranchingConfig()  # AD-633
    self_improvement: SelfImprovementConfig = SelfImprovementConfig()  # AD-482
    memory_budget: MemoryBudgetConfig = MemoryBudgetConfig()  # AD-573
    metabolism: MetabolismConfig = MetabolismConfig()  # AD-670
    pinned_knowledge: PinnedKnowledgeConfig = PinnedKnowledgeConfig()  # AD-579a
    temporal_validity: TemporalValidityConfig = TemporalValidityConfig()  # AD-579b
    task_context: TaskContextConfig = TaskContextConfig()  # AD-586
    question_adaptive: QuestionAdaptiveConfig = QuestionAdaptiveConfig()  # AD-602
    storage_gate: StorageGateConfig = StorageGateConfig()  # AD-610
    salience: SalienceConfig = SalienceConfig()  # AD-668
    sensorium: SensoriumConfig = SensoriumConfig()  # AD-666
    source_tracing: SourceTracingConfig = SourceTracingConfig()
    observable_state: ObservableStateConfig = ObservableStateConfig()
    llm_rate: LLMRateConfig = LLMRateConfig()  # AD-617
    sub_task: SubTaskConfig = SubTaskConfig()  # AD-632a
    boot_camp: BootCampConfig = BootCampConfig()  # AD-638
    ship_state_snapshot: ShipStateSnapshotConfig = Field(
        default_factory=ShipStateSnapshotConfig
    )  # AD-683
    tiered_trust: TieredTrustConfig = TieredTrustConfig()  # AD-640
    chain_tuning: ChainTuningConfig = ChainTuningConfig()  # AD-639
    chain_optimizer: ChainOptimizerConfig = ChainOptimizerConfig()  # AD-659
    chain_optimizer_counselor: ChainOptimizerCounselorConfig = ChainOptimizerCounselorConfig()  # AD-659c
    causal_reasoning: CausalReasoningConfig = CausalReasoningConfig()  # AD-660
    diagnostic_context: DiagnosticContextConfig = Field(
        default_factory=DiagnosticContextConfig
    )  # AD-661
    nl_graph_query: NLGraphQueryConfig = Field(
        default_factory=NLGraphQueryConfig
    )  # AD-691
    clinical_telemetry: ClinicalTelemetryConfig = Field(
        default_factory=ClinicalTelemetryConfig
    )  # AD-635
    consultation_workspaces: ConsultationWorkspaceConfig = Field(
        default_factory=ConsultationWorkspaceConfig
    )  # AD-594a
    consultation_delivery: ConsultationDeliveryConfig = Field(
        default_factory=ConsultationDeliveryConfig
    )  # AD-594d
    consultation_dispatch: ConsultationDispatchConfig = Field(
        default_factory=ConsultationDispatchConfig
    )  # AD-594c
    hybrid_dispatch: HybridDispatchConfig = Field(
        default_factory=HybridDispatchConfig
    )  # AD-581 v1 (sub-ADs 581a/b/d)
    process_chain_registry: ProcessChainRegistryConfig = Field(
        default_factory=ProcessChainRegistryConfig
    )  # AD-647b
    knowledge_loading: KnowledgeLoadingConfig = KnowledgeLoadingConfig()  # AD-585
    step_instruction: StepInstructionConfig = StepInstructionConfig()  # AD-651
    agent_tiers: AgentTierConfig = AgentTierConfig()  # AD-571
    operational_status: OperationalStatusConfig = OperationalStatusConfig()  # AD-571b
    risk_tiers: RiskTierConfig = RiskTierConfig()  # AD-676
    procedural_bridge: BridgeConfig = BridgeConfig()  # AD-572
    nats: NatsConfig = NatsConfig()  # AD-637
    bill: BillConfig = BillConfig()  # AD-618b
    consultation: ConsultationConfig = ConsultationConfig()  # AD-594
    expertise: ExpertiseConfig = ExpertiseConfig()  # AD-600
    creative_expression: CreativeExpressionConfig = Field(default_factory=CreativeExpressionConfig)  # AD-525
    classification_gate: ClassificationGateConfig = Field(default_factory=ClassificationGateConfig)  # AD-530
    autonomy_boundaries: AutonomyBoundariesConfig = Field(default_factory=AutonomyBoundariesConfig)  # AD-511
    crew_development: CrewDevelopmentConfig = Field(default_factory=CrewDevelopmentConfig)  # AD-507
    boot_camp_phase: BootCampPhaseConfig = Field(default_factory=BootCampPhaseConfig)  # AD-509
    discovery_learning: DiscoveryLearningConfig = Field(default_factory=DiscoveryLearningConfig)  # AD-512
    scoped_cognition: ScopedCognitionConfig = Field(default_factory=ScopedCognitionConfig)  # AD-508
    workspace_ontology: WorkspaceOntologyConfig = Field(default_factory=WorkspaceOntologyConfig)  # AD-478
    gap_pipeline_extensions: GapPipelineExtensionsConfig = Field(default_factory=GapPipelineExtensionsConfig)  # AD-539c/d
    spreading_activation: SpreadingActivationConfig = SpreadingActivationConfig()  # AD-604
    thought_store: ThoughtStoreConfig = ThoughtStoreConfig()  # AD-606
    retroactive: RetroactiveConfig = RetroactiveConfig()  # AD-608
    distillation: DistillationConfig = DistillationConfig()  # AD-609
    reconsolidation: ReconsolidationConfig = ReconsolidationConfig()  # AD-574
    naval_organization: NavalOrganizationConfig = Field(default_factory=NavalOrganizationConfig)  # AD-477
    self_distillation: SelfDistillationConfig = SelfDistillationConfig()  # AD-487
    spc: SPCConfig = Field(default_factory=SPCConfig)  # AD-522 v1

    @field_validator("health_probe_interval_seconds")
    @classmethod
    def _validate_probe_interval(cls, v: float) -> float:
        if v < 5.0:
            raise ValueError(
                "health_probe_interval_seconds must be >= 5.0 to avoid hammering a recovering proxy"
            )
        return v


def load_config(path: str | Path) -> SystemConfig:
    """Load and validate system config from a YAML file."""
    path = Path(path)
    if not path.exists():
        return SystemConfig()
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    # YAML sections with all values commented out parse as key: None.
    # Remove these so pydantic uses defaults instead of failing validation.
    raw = {k: v for k, v in raw.items() if v is not None}
    return SystemConfig.model_validate(raw)
