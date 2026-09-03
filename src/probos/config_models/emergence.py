"""Emergence, behaviour and clinical configuration models (AD-1270e2).

Batch 8 of the ``config.py`` extraction. Every model here is self-contained:
it references no other config model and no module-level helper in
``config.py``. Import these from ``probos.config``, which re-exports them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RuntimeOverridesConfig(BaseModel):
    """Runtime override layer configuration (AD-468)."""

    enabled: bool = True
    store_filename: str = "runtime_overrides.json"


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


class WorkflowCronTriggerConfig(BaseModel):
    """AD-707: Workflow cron-trigger scheduler configuration.

    Default-False per Wave 10 convention #14. ``db_path`` empty means
    in-memory only (triggers lost on restart); supply a path to enable
    persistence. ``initial_triggers`` items must have keys
    ``user_input`` and ``cron_expr``.
    """

    enabled: bool = False
    db_path: str = ""
    tick_interval_seconds: float = Field(default=1.0, gt=0.0)
    initial_triggers: list[dict[str, str]] = Field(default_factory=list)


class QueryPlannerConfig(BaseModel):
    """Memvid pattern 1: relational query routing for the recall pipeline.

    Default-False per Wave 10 convention #14: opt-in until coverage proves
    out the regex classifier on real production traffic. When enabled, the
    runtime exposes a ``query_planner`` attribute that recall consumers can
    use via ``QueryPlanner.recall_with_fallback(episodic, query, k)``.
    """

    enabled: bool = False
    fall_through_on_empty: bool = True


class BridgeAlertConfig(BaseModel):
    """Bridge Alerts — proactive Captain & crew notifications (AD-410)."""
    enabled: bool = False
    cooldown_seconds: float = 300        # Dedup window per alert type+subject
    trust_drop_threshold: float = 0.15   # Trust drop triggering advisory
    trust_drop_alert_threshold: float = 0.25  # Trust drop triggering alert
    resolve_clean_period: float = 3600.0       # AD-580: seconds before resolved alert can re-fire
    default_dismiss_duration: float = 14400.0  # AD-580: default dismiss duration (4 hours)


class EmergenceCollectorConfig(BaseModel):
    """AD-454: EvidenceCollector — research opt-in, default disabled."""

    enabled: bool = False
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    dedup_window_seconds: float = Field(default=600.0, ge=0.0)
    output_dir: str = "data/research/emergence-evidence"
    llm_tier: str = "fast"
    trial_id: str = "default"
    thread_context_limit: int = Field(default=5, ge=0, le=50)
    max_reasoning_chars: int = Field(default=2000, ge=100, le=20000)


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


class ProactiveScanInboxConfig(BaseModel):
    """AD-763: per-operator scoping of the inbox proactive scan."""

    folders: list[str] = Field(
        default_factory=lambda: ["Inbox"],
        description="Graph mail folder IDs (or 'Inbox' alias) to include in scans.",
    )
    lookback_hours: int = Field(
        default=24,
        ge=1,
        le=24 * 14,
        description="Window (hours) to query backward from now.",
    )
    importance_filter: Literal["any", "high"] = Field(
        default="any",
        description="'any' includes all importance levels; 'high' restricts to high-importance only.",
    )
    unread_only: bool = Field(
        default=False,
        description="If True, only unread messages are surfaced.",
    )
    sender_allowlist: list[str] = Field(
        default_factory=list,
        description="Email addresses or domains (e.g. '@acme.com'). Empty = no allow filter.",
    )
    sender_denylist: list[str] = Field(
        default_factory=list,
        description="Email addresses or domains. Senders matching are dropped post-fetch.",
    )


class ProactiveScanCalendarConfig(BaseModel):
    """AD-763: per-operator scoping of the calendar proactive scan."""

    calendar_ids: list[str] = Field(
        default_factory=lambda: ["primary"],
        description="Graph calendar IDs ('primary' alias resolves to default calendar).",
    )
    lookahead_hours: int = Field(
        default=24,
        ge=1,
        le=24 * 30,
        description="Window (hours) to query forward from now.",
    )
    include_declined: bool = Field(
        default=False,
        description="If True, events the operator has declined are still surfaced.",
    )


class PersistentTasksConfig(BaseModel):
    """Persistent Task Engine — SQLite-backed scheduled tasks (Phase 25a)."""
    enabled: bool = False
    tick_interval_seconds: float = 5.0
    max_concurrent_executions: int = 1   # Sequential by design
    dag_auto_resume: bool = False        # Future: auto-resume stale DAGs


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


class TraitAdaptiveConfig(BaseModel):
    """Trait-adaptive circuit breaker configuration (AD-494)."""

    enabled: bool = True


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


class CognitiveJournalConfig(BaseModel):
    """Cognitive Journal — append-only LLM reasoning trace store (AD-431)."""
    enabled: bool = True
    retention_days: int = 14         # Keep journal entries for N days (0 = keep forever)
    max_rows: int = 500_000          # Hard cap on total rows (0 = no cap)
    prune_interval_seconds: float = 3600.0


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


class AgentTierConfig(BaseModel):
    """Agent tier classification for trust separation (AD-571)."""

    crew_types: list[str] = Field(default_factory=lambda: [
        "architect", "builder", "code_reviewer", "counselor",
        "diagnostician", "surgeon", "pharmacist", "pathologist",
        "red_team", "system_qa", "scout",
        "data_analyst", "systems_analyst", "research_specialist",
    ])
    core_types: list[str] = Field(default_factory=lambda: ["event_log", "vitals_monitor", "introspect"])


class BridgeConfig(BaseModel):
    """Episodic-procedural bridge configuration (AD-572)."""

    enabled: bool = True
    min_cross_cycle_episodes: int = 5
    novelty_threshold: float = 0.3
