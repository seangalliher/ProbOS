"""Cognition, memory and self-modification configuration models (AD-1270e2).

Batch 2 of the ``config.py`` extraction. Every model here is self-contained:
it references no other config model and no module-level helper in
``config.py``. Import these from ``probos.config``, which re-exports them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AttentionConfig(BaseModel):
    """AD-1028: ContextAssembler / global token-budget configuration.

    Default-OFF: when ``enabled`` is False the bid-based ``ContextAssembler``
    runs with an effectively-unbounded budget so nothing is dropped and the
    assembled prompt is byte-identical to the prior push-style prepend chain.
    When ``enabled`` is True the assembler enforces ``token_budget`` — the first
    global guard against context-window overflow.
    """

    enabled: bool = False
    # Sized to a large model window; nothing drops at this budget for normal
    # prompts. Operators lower it to enforce a tighter context window.
    token_budget: int = Field(default=120_000, ge=1000)
    # AD-1030: adaptive salience scoring (relevance × recency × importance) for
    # episodic + working-memory bids. Default-OFF ⇒ the AD-1029 fixed insertion
    # priority is byte-identical. INDEPENDENT of ``enabled`` (the budget gate):
    # scoring re-orders/weights bids whether or not a tight budget is enforced.
    salience_scoring: bool = False
    # Linear salience weights (normalized at use, so absolute scale is free).
    w_rel: float = Field(default=1.0, ge=0.0)   # relevance (goal similarity)
    w_rec: float = Field(default=0.5, ge=0.0)   # recency (time decay)
    w_imp: float = Field(default=0.5, ge=0.0)   # importance (AD-598)
    # Recency decay time-constant (seconds): exp(-age / half_life). Default 1 day.
    recency_half_life_seconds: float = Field(default=86400.0, gt=0.0)
    # AD-1031: camera/visual scene as a salience-gated bid. AD-1061 (2026-06-27,
    # Captain-directed after live validation) flipped the default to True: the
    # rendered scene is handed to the agent (via params, NOT prepended onto the
    # Captain turn), bid PROMINENT only when SALIENT — the Captain referenced
    # vision, the frame MATERIALLY CHANGED (novelty ≥ camera_novelty_minimum), or
    # it is a VISUAL TASK (image attachment) — and RECESSIVE (a one-line "live
    # camera" summary, present-but-quiet) otherwise. Stops agents over-narrating
    # an unchanged scene (#973) and removes the visual block's prompt dominance
    # (BF-632). Set False to restore the legacy AD-733a router prepend (the full
    # block on every turn).
    camera_scene_bid_enabled: bool = True
    # Minimum novelty_score (0.0–1.0) for a frame to count as "materially
    # changed" and surface the full scene on CHANGE alone (an explicit visual
    # reference always surfaces it, independent of this gate). Captain-approved
    # default 0.3 (2026-06-19).
    camera_novelty_minimum: float = Field(default=0.3, ge=0.0, le=1.0)
    # AD-1060: adaptive injection FREQUENCY (the cadence the visual scene enters
    # the prompt, vs AD-1031 which sets its prominence). ``camera_novelty_ema_alpha``
    # is the EMA weight on each newer frame's novelty (higher = more reactive to
    # the latest frame). ``camera_recessive_suppress_threshold`` — once the
    # decayed (EMA) novelty falls below it, a non-referenced, non-task,
    # low-raw-novelty frame is SUPPRESSED entirely (the feed fades to background)
    # instead of injecting a recessive one-liner every turn. AD-1061b (2026-06-27,
    # Captain-directed after live validation) flipped the default to 0.15 ⇒
    # suppression ON for perception-enabled operators; set 0.0 to disable (the
    # AD-1031 always-inject bid). A raw-novelty spike, an explicit visual
    # reference, or a visual task always injects regardless.
    camera_novelty_ema_alpha: float = Field(default=0.3, gt=0.0, le=1.0)
    camera_recessive_suppress_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    # AD-1032: faculty-local arousal model (exogenous interrupts → cognitive-zone
    # reconfiguration; the cognitive-layer mirror of HXI Design Principle #9).
    # Default-OFF ⇒ ``AttentionFaculty.arbitrate`` is byte-identical to AD-1029.
    # DOUBLE-gated: the faculty is only composed when ``enabled`` is True, so
    # arousal also requires the AD-1028 budget gate on. The arousal zone is
    # FACULTY-LOCAL and NEVER touches the AD-588 circuit-breaker zone.
    arousal_enabled: bool = False
    # Under RED arousal (attentional narrowing / Yerkes–Dodson) the effective
    # token budget is multiplied by this factor. Captain-approved default 0.5.
    arousal_red_budget_multiplier: float = Field(default=0.5, gt=0.0, le=1.0)
    # A quiet period (no new exogenous event) longer than this fully resets the
    # arousal zone to GREEN (the gradual per-turn step-down handles shorter gaps).
    arousal_full_decay_seconds: float = Field(default=300.0, gt=0.0)
    # A low-severity event (scene_change/gossip) repeating within this window
    # escalates GREEN→AMBER; a single low-severity event only queues (no zone change).
    arousal_repeat_window_seconds: float = Field(default=60.0, gt=0.0)


class DreamingConfig(BaseModel):
    """Dreaming / offline consolidation configuration."""

    # AD-1035: when True, compose a per-agent background DreamingOrgan (personal
    # dreaming faculty, epic #983) onto each CognitiveAgent's spine. Default OFF ⇒ no
    # organ is attached and the shared runtime DreamingEngine + DreamScheduler remain
    # the single source of truth (byte-identical). AD-1035 wires no live engine, so the
    # organ is inert in production even when this is True.
    organ_enabled: bool = False

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
    # AD-980b: per-agent dream attribution. Dream-consolidation reflections are
    # stored ownerless (agent_ids=[]), so no agent can recall "its" dream. When
    # enabled, a reflection whose source cluster/convergence has involved agents
    # is stored with agent_ids=<those agents> — giving a dream a dreamer (the
    # prerequisite for AD-980c dream interpretation). Default OFF -> byte-
    # identical (reflections stay ownerless) until the Captain enables the loop.
    per_agent_dream_attribution_enabled: bool = False
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
