"""Configuration loader for ProbOS."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


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
    llm_model_fast: str = "gpt-4o-mini"
    llm_model_standard: str = "claude-sonnet-4"
    llm_model_deep: str = "claude-sonnet-4"

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


class MemoryConfig(BaseModel):
    """Episodic memory configuration."""

    collection_name: str = "probos_episodes"
    max_episodes: int = 100000
    relevance_threshold: float = 0.7
    similarity_threshold: float = 0.6  # Semantic similarity threshold for recall/fuzzy lookup
    verify_content_hash: bool = True    # AD-541e: Verify episode hashes on recall
    eviction_audit_enabled: bool = True  # AD-541f: Append-only eviction audit trail


class DreamingConfig(BaseModel):
    """Dreaming / offline consolidation configuration."""

    idle_threshold_seconds: float = 120.0  # Tier 2: full dream after idle (AD-288)
    dream_interval_seconds: float = 600.0
    proactive_extends_idle: bool = True     # AD-417: Proactive activity extends idle timer
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


class FederationConfig(BaseModel):
    """Multi-node federation configuration."""

    enabled: bool = False  # Disabled by default — single-node is still the default
    node_id: str = "node-1"
    bind_address: str = "tcp://127.0.0.1:5555"  # This node's ZeroMQ ROUTER address
    peers: list[PeerConfig] = []  # Static peer list
    forward_timeout_ms: int = 5000  # Timeout waiting for peer responses
    gossip_interval_seconds: float = 10.0  # How often to broadcast self-model to peers
    validate_remote_results: bool = True  # Pass remote results through local consensus


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
    # AD-555: Notebook quality metrics
    notebook_quality_enabled: bool = True
    notebook_quality_low_threshold: float = 0.3
    notebook_quality_warn_threshold: float = 0.5
    notebook_staleness_alert_rate: float = 0.7


class OnboardingConfig(BaseModel):
    """AD-442: Onboarding ceremony configuration."""

    enabled: bool = True
    activation_trust_threshold: float = 0.65
    naming_ceremony: bool = True  # If False, agents keep seed callsigns


class UtilityAgentsConfig(BaseModel):
    """Utility agent suite configuration (AD-252)."""

    enabled: bool = True  # Create utility CognitiveAgent pools at boot


class WardRoomConfig(BaseModel):
    """Ward Room communication fabric configuration (AD-407)."""

    enabled: bool = False  # Disabled by default — enable after HXI surface is ready
    max_agent_rounds: int = 3           # AD-407d: max consecutive agent-only rounds per thread
    agent_cooldown_seconds: float = 45  # AD-407d: cooldown for agent-triggered responses
    max_agent_responses_per_thread: int = 3  # BF-016b: per-agent cap per thread (prevents explosion)
    default_discuss_responder_cap: int = 3  # AD-424: Default max_responders for DISCUSS threads
    # AD-416: Retention & archival
    retention_days: int = 7                    # Regular posts older than this are pruned
    retention_days_endorsed: int = 30          # Posts with net_score > 0 retained longer
    retention_days_captain: int = 0            # 0 = indefinite retention for Captain posts
    archive_enabled: bool = True               # Write pruned posts to JSONL archive before deletion
    prune_interval_seconds: float = 86400.0    # How often to run pruning (default: daily)


class AssignmentConfig(BaseModel):
    """Dynamic assignment groups configuration (AD-408)."""

    enabled: bool = False  # Disabled by default — enable after HXI surface is ready


class BridgeAlertConfig(BaseModel):
    """Bridge Alerts — proactive Captain & crew notifications (AD-410)."""
    enabled: bool = False
    cooldown_seconds: float = 300        # Dedup window per alert type+subject
    trust_drop_threshold: float = 0.15   # Trust drop triggering advisory
    trust_drop_alert_threshold: float = 0.25  # Trust drop triggering alert


class EarnedAgencyConfig(BaseModel):
    """Earned Agency — trust-tiered behavioral gating (AD-357)."""
    enabled: bool = False


class DutyDefinition(BaseModel):
    """A single recurring duty for a crew agent type."""
    duty_id: str                # e.g., "scout_report"
    description: str            # Human-readable task description
    cron: str = ""              # Cron expression (croniter format). Empty = interval-based.
    interval_seconds: float = 0 # Alternative to cron: simple interval. 0 = use cron.
    priority: int = 2           # 1-5, higher = more important when multiple due


class DutyScheduleConfig(BaseModel):
    """Duty schedule definitions per agent type (AD-419)."""
    enabled: bool = True
    schedules: dict[str, list[DutyDefinition]] = {}


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


class ChannelsConfig(BaseModel):
    """Channel adapter configurations."""

    discord: DiscordConfig = DiscordConfig()


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


class CommunicationsConfig(BaseModel):
    """Communications settings (AD-485)."""
    dm_min_rank: str = "ensign"  # Minimum rank to send DMs: ensign|lieutenant|commander|senior


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


class QualificationConfig(BaseModel):
    """Configuration for the Crew Qualification Battery (AD-566)."""

    enabled: bool = True
    baseline_auto_capture: bool = True
    significance_threshold: float = 0.15
    test_timeout_seconds: float = 60.0

    # AD-566c: Drift Detection Pipeline
    drift_check_enabled: bool = True
    drift_check_interval_seconds: float = 604800.0  # 1 week
    drift_warning_sigma: float = 2.0    # Counselor alert threshold
    drift_critical_sigma: float = 3.0   # Bridge/Captain alert threshold
    drift_min_samples: int = 3          # Minimum data points before drift analysis
    drift_history_window: int = 20      # Max historical results for stats
    drift_cooldown_seconds: float = 3600.0  # Min time between alerts per agent+test
    drift_check_tiers: list[int] = [1, 2, 3]  # AD-566d/e: Which tiers the drift scheduler runs


class SystemConfig(BaseModel):
    """Root configuration model."""

    system: SystemInfo = SystemInfo()
    pools: PoolConfig = PoolConfig()
    mesh: MeshConfig = MeshConfig()
    consensus: ConsensusConfig = ConsensusConfig()
    cognitive: CognitiveConfig = CognitiveConfig()
    memory: MemoryConfig = MemoryConfig()
    dreaming: DreamingConfig = DreamingConfig()
    scaling: ScalingConfig = ScalingConfig()
    federation: FederationConfig = FederationConfig()
    self_mod: SelfModConfig = SelfModConfig()
    qa: QAConfig = QAConfig()
    knowledge: KnowledgeConfig = KnowledgeConfig()
    records: RecordsConfig = RecordsConfig()
    onboarding: OnboardingConfig = OnboardingConfig()
    utility_agents: UtilityAgentsConfig = UtilityAgentsConfig()
    ward_room: WardRoomConfig = WardRoomConfig()
    assignments: AssignmentConfig = AssignmentConfig()
    bridge_alerts: BridgeAlertConfig = BridgeAlertConfig()
    earned_agency: EarnedAgencyConfig = EarnedAgencyConfig()
    proactive_cognitive: ProactiveCognitiveConfig = ProactiveCognitiveConfig()
    persistent_tasks: PersistentTasksConfig = PersistentTasksConfig()
    channels: ChannelsConfig = ChannelsConfig()
    medical: MedicalConfig = MedicalConfig()
    counselor: CounselorConfig = CounselorConfig()
    circuit_breaker: CircuitBreakerConfig = CircuitBreakerConfig()
    trust_dampening: TrustDampeningConfig = TrustDampeningConfig()
    emergence_metrics: EmergenceMetricsConfig = EmergenceMetricsConfig()
    event_log: EventLogConfig = EventLogConfig()
    cognitive_journal: CognitiveJournalConfig = CognitiveJournalConfig()
    communications: CommunicationsConfig = CommunicationsConfig()
    workforce: WorkforceConfig = WorkforceConfig()
    temporal: TemporalConfig = TemporalConfig()
    qualification: QualificationConfig = QualificationConfig()


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
