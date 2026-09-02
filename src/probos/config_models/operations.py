"""Operations, quality and engineering configuration models (AD-1270e2).

Batch 5 of the ``config.py`` extraction. Every model here is self-contained:
it references no other config model and no module-level helper in
``config.py``. Import these from ``probos.config``, which re-exports them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExecutionConfig(BaseModel):
    """AD-993/994: sandboxed code execution (tiered isolation).

    Lets crew agents create + run Python scripts and install libraries to perform
    tasks (the Copilot / Claude Code pattern), bounded by the tier model.
    **Default OFF** — this is the highest-risk capability in the system; the
    operator must opt in deliberately after reviewing the tier model.

    BF-763 / BF-779: **neither** ``run_python`` path is quorum-approved before it
    runs. The agentic tool is permission-resolved but nothing votes on the
    script; the mesh intent declares consensus and executes during the broadcast,
    so quorum votes on a script that has already run.

    What is recorded, precisely. AD-1247 gives the AGENTIC path a
    ``code_execution`` audit record, ATTEMPTED once per run that reached the
    sandbox, when ``security_infra.audit_enabled`` is on. Each record carries a
    ``launch_state``: ``launched`` when a child was confirmed, ``unknown`` when
    the turn was torn down before the sandbox could answer and a script MAY have
    run. With the sink off there is no record and a warning says so; if the
    append raises, whether the entry landed is UNCONFIRMED, because the sink can
    store and then fail. It is a best effort under stated conditions, never an
    unconditional guarantee, because an audit write that could fail an execution
    would be a new way to lose work.
    AD-1280 gave the MESH path the same record, on the same terms and from the
    same shared builder (``execution/audit.py``): attempted once per
    ``run_python`` turn that reached the sandbox, carrying the same
    ``launch_state`` and with the same UNCONFIRMED case when the append raises.
    Only the script run is recorded -- ``install_package`` and venv preparation
    execute argv this codebase wrote, not source an agent authored. What ELSE
    the mesh path writes still varies BY INGRESS -- the decomposed-plan route
    writes generic intent rows (plus a quorum row only when the plan's
    model-chosen ``use_consensus`` was true), the federation MCP route writes
    none, and none of those rows carries the source or its output. Separately,
    the DAG checkpoint and a caller-preserved workdir's ``script.py`` can hold
    source.

    Do not read authorization into any of it.
    """

    enabled: bool = False                   # opt-in; arbitrary code execution
    # Which isolation tier to run at: 1 = subprocess/working-folder (AD-993,
    # the only tier built today), 2 = OS-native sandbox (AD-995, future),
    # 3 = container/VM (AD-996, future).
    #
    # BF-781: this used to add "A request unsafe for the configured tier should
    # escalate, not silently downgrade." Nothing escalates, and no module under
    # `execution/` reads this field -- it is declaration-only, kept so the shape
    # exists when a tier is built. A rule stated for a field nobody reads is the
    # kind of claim that stops the next reader checking. (Scoped to `execution/`
    # on purpose: a first draft claimed every `default_tier` reader in the tree
    # was the LLM client's, and review found holodeck readers too.)
    default_tier: int = 1
    # Root for scratch working folders, and the root under which `workspace_root`
    # sits by default. BF-781: the comment here used to read "ephemeral per-task
    # working folders" flatly. That is true when `persistent_workspaces` is
    # False -- and it defaults True, under which `CodeRunnerAgent` runs in its
    # owner's persistent folder instead. NOT dead either way: `CodeExecutionTool`
    # still roots its runs here regardless of that setting.
    scratch_dir: str = "data/execution"
    # AD-997: per-agent PERSISTENT working folders. Each owner (crew agent) gets
    # its own folder under workspace_root so work products (scripts, generated
    # files, the installed venv) survive across runs and are visible from the
    # agent's profile card. The root is operator-configurable (HXI Settings).
    # When False, every run uses a fresh ephemeral scratch that is reaped after
    # (the original AD-993/994 behavior).
    persistent_workspaces: bool = True
    workspace_root: str = "data/execution/workspaces"
    # AD-1221: let sandboxed code fetch a URL through the ship's governed HTTP
    # path (`import probos; probos.fetch(url)`), so an agent can fetch and
    # extract in ONE process instead of carrying every byte through its context
    # window. This does NOT open general network access: the sandbox gets a
    # loopback socket to a relay that exists only for that run, and every
    # request still passes SSRF validation, per-domain rate limiting and audit.
    # Default OFF because it is a capability increase and the operator should
    # choose it; see Design Principle 13 for why the choice is stated rather
    # than inherited.
    fetch_broker_enabled: bool = False
    # A body returned through the broker goes to the sandbox's own memory, NOT
    # onto the intent bus, so HttpFetchAgent.MAX_BODY_BYTES (1 MB, sized to
    # protect the bus after the #636 OOM) is not the constraint that applies
    # here. 8 MB is chosen to cover the documents this is for — package
    # indexes, API listings, large HTML pages — while still bounding one fetch.
    fetch_broker_max_body_bytes: int = 8 * 1024 * 1024
    # AD-1021b: governed write-through to the per-agent workspace folder (the
    # Monaco workstation Save path). Default OFF — a separate master switch from
    # ``enabled`` so editing a workspace text file (consensus-gated) does not
    # require opting into arbitrary code execution. When False the write endpoint
    # 503s; the read endpoint + all AD-997/998 behavior are unaffected.
    workspace_write_enabled: bool = False
    timeout_seconds: float = 30.0
    max_output_bytes: int = 65536           # 64 KB per stream
    max_memory_mb: int = 512                # RLIMIT_AS on POSIX; advisory on Windows
    # AD-1074d: stage the chat thread's current artifacts (the latest version of
    # each name) into the sandbox working folder BEFORE the script runs, so a
    # crew agent can READ + MODIFY an existing document (the Cowork round-trip:
    # "change the heading to bold"). Only files the script actually changes — or
    # newly creates — are re-captured as a new version; unchanged staged inputs
    # are skipped. Default OFF (behavior-preserving: the workdir is empty as
    # before). ``max_staged_artifacts`` caps how many documents are copied in so
    # a thread with many artifacts can't bloat the sandbox.
    stage_thread_artifacts: bool = False
    max_staged_artifacts: int = 20
    # Library installation (pip into the owner's workspace venv, which is REUSED
    # across runs under the default persistent_workspaces). Separately gated
    # because installing arbitrary PyPI packages is a supply-chain risk, and the
    # install persists. The package names are surfaced in the intent, but that
    # intent is not quorum-approved before it runs (BF-779).
    allow_package_install: bool = False
    pip_index_url: str = "https://pypi.org/simple"
    install_timeout_seconds: float = 180.0  # venv create + pip install is slower


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


class AnomalyWindowConfig(BaseModel):
    """Anomaly window detection configuration (AD-673)."""

    enabled: bool = True
    max_window_duration_seconds: float = 1800.0
    lookback_seconds: float = 60.0


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
    """Engineering infrastructure configuration (AD-466 / AD-1265)."""

    enabled: bool = True
    backup_enabled: bool = True
    backup_subdir: str = "backups"

    # AD-1265: AD-466 shipped the service with no scheduler; these drive it.
    # Defaults are arithmetic, not taste. Measured 2026-08-24: the included
    # tier is ~559 MiB/tick (immutable adds 91 MiB once, then hard-links).
    # 6 h => 4 ticks/day; 3 days => 12 ticks => ~6.8 GiB, under the 8 GiB
    # ceiling. Both bounds agree at this footprint, so retain_days means what
    # it says. Raise max_total_bytes before raising retain_days.
    backup_interval_seconds: float = Field(default=21600.0, ge=300.0)
    backup_warmup_seconds: float = Field(default=120.0, ge=0.0)
    backup_retain_days: int = Field(default=3, ge=1, le=365)
    backup_max_total_bytes: int = Field(default=8 * 1024**3, ge=64 * 1024**2)
    backup_include_archive_root: bool = True

    # AD-1296 D3: working directories whose owner cannot be proven are kept,
    # never deleted, and retention cannot see them -- so they are the one part
    # of the backup root with no bound at all. At or above this many orphaned
    # bytes the per-tick message logs at ERROR instead of WARNING; nothing is
    # deleted either way, the operator is told to run ``probos backup-reclaim``.
    #
    # 4 GiB is half of backup_max_total_bytes, which is ~7 abandoned working
    # directories at the ~559 MiB/tick measured above. Below that, one or two
    # leftovers from a crash-during-snapshot or a peer host are routine and a
    # warning is proportionate. At or above it the unreclaimed set rivals
    # everything retention *does* bound and is still growing, which is a
    # disk-exhaustion trajectory and must not read as background noise after a
    # month of identical warnings. 0 escalates on any orphan at all.
    backup_orphan_alert_bytes: int = Field(default=4 * 1024**3, ge=0)


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


class EngineeringSensorsConfig(BaseModel):
    """AD-641f: Engineering Chief Observability configuration."""

    enabled: bool = True
    report_interval_seconds: float = 60.0
    auto_start_periodic_report: bool = False


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


class SPCConfig(BaseModel):
    """AD-522 v1: Statistical Process Control (calibration profile + WE rules)."""

    enabled: bool = True
    sample_window: int = 100
