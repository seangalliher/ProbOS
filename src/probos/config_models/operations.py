"""Operations, quality and engineering configuration models (AD-1270e2).

Batch 5 of the ``config.py`` extraction. Every model here is self-contained:
it references no other config model and no module-level helper in
``config.py``. Import these from ``probos.config``, which re-exports them.
"""

from __future__ import annotations

import ntpath
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# BF-890 (#1529): literal twins of probos.execution.command_env's
# CREDENTIAL_NAME_WORDS, CREDENTIAL_NAME_SEGMENTS, RUNTIME_NAME_PREFIX and
# ENV_NAME_SHAPE_PATTERN. This module may not import probos, so
# tests/test_bf890_command_env.py asserts each twin equals its owner.
_CREDENTIAL_ENV_NAME_WORDS = (
    "KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "PASSPHRASE",
    "CREDENTIAL", "AUTH", "COOKIE", "SESSION", "PRIVATE",
)
_CREDENTIAL_ENV_NAME_SEGMENTS = ("PAT", "PASS", "PWD", "DSN", "CREDS")
_RUNTIME_ENV_NAME_PREFIX = "PROBOS_"
_ENV_NAME_SHAPE_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*"

# AD-1328 S1 (#1530): the command execution policy's models. They sit beside
# ExecutionConfig because S2 attaches them as ExecutionConfig.command_policy and
# this module may not import probos. S1 neither attaches nor re-exports them: their
# only reader is probos.execution.command_policy, which no file under src/ imports
# yet (tests/test_ad1328_s1_policy_evaluation.py pins that).
CommandDecisionName = Literal["allow", "escalate", "forbid"]
#: Strictness: forbid > escalate > allow. The strictest decision wins.
COMMAND_DECISION_RANK: dict[str, int] = {"allow": 0, "escalate": 1, "forbid": 2}
_COMMAND_RULE_NAME_PATTERN = r"[a-z0-9][a-z0-9_.-]{0,63}"
_WINDOWS_PROGRAM_SUFFIXES = (".exe", ".com", ".bat", ".cmd")
_MAX_COMMAND_RULES = 256
_MAX_PATTERN_POSITIONS = 32
_MAX_TOKEN_ALTERNATIVES = 32
_MAX_TOKEN_CHARS = 256
_MAX_RULE_PROSE_CHARS = 500
_MAX_RULE_EXAMPLES = 32
_MAX_EXAMPLE_CHARS = 1024
_MAX_PINNED_PATHS = 16
_MAX_PINNED_PATH_CHARS = 1024


def windows_program_stem(program: str) -> str:
    """A program's name as Windows finds it: the basename, lower-cased, without
    ``.exe``, ``.com``, ``.bat`` or ``.cmd``. ``ntpath`` splits on both separators,
    so a POSIX path gives its basename too."""
    base = ntpath.basename(program).lower()
    for suffix in _WINDOWS_PROGRAM_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            return base[: -len(suffix)]
    return base


def _has_control_character(value: str, allowed: str = "") -> bool:
    return any((ord(char) < 32 and char not in allowed) or ord(char) == 127 for char in value)


def _has_surrogate(value: str) -> bool:
    """True when ``value`` holds a lone surrogate: text that is not valid Unicode, which the RFC 8785
    policy digest cannot encode (AD-1328 S1 repair, finding 12)."""
    return any("\ud800" <= char <= "\udfff" for char in value)


def _check_policy_text(value: str, what: str, limit: int, *, newlines: bool = False) -> None:
    if not value.strip():
        raise ValueError(f"{what} must not be blank")
    if len(value) > limit:
        raise ValueError(f"{what} is longer than {limit} characters")
    if _has_control_character(value, "\t\n" if newlines else ""):
        raise ValueError(f"{what} contains a control character")
    if _has_surrogate(value):
        raise ValueError(f"{what} is not valid Unicode text (a lone surrogate)")


def _check_pattern(pattern: tuple[str | tuple[str, ...], ...], where: str) -> None:
    if not 1 <= len(pattern) <= _MAX_PATTERN_POSITIONS:
        raise ValueError(f"{where}: pattern must have 1 to {_MAX_PATTERN_POSITIONS} positions")
    for position, entry in enumerate(pattern):
        options = (entry,) if isinstance(entry, str) else entry
        if not 1 <= len(options) <= _MAX_TOKEN_ALTERNATIVES or len(set(options)) != len(options):
            raise ValueError(
                f"{where}: pattern position {position} must list 1 to "
                f"{_MAX_TOKEN_ALTERNATIVES} distinct words"
            )
        for token in options:
            if not token or len(token) > _MAX_TOKEN_CHARS or _has_control_character(token):
                raise ValueError(
                    f"{where}: pattern position {position} has an empty, over-long or "
                    "control-character word"
                )
            if _has_surrogate(token):
                raise ValueError(f"{where}: pattern position {position} is not valid Unicode text (a lone surrogate)")
            if position == 0 and any(char in token for char in "/\\ \t"):
                raise ValueError(
                    f"{where}: the program {token!r} must be a bare name; pin paths "
                    "with host_executable"
                )


def _check_pins(rule: CommandPolicyRule, where: str) -> None:
    pins = rule.host_executable
    if not pins:
        return
    if rule.decision != "allow":
        raise ValueError(
            f"{where}: host_executable pins an allow rule only; a {rule.decision} rule "
            "matches its program at every path"
        )
    program = rule.pattern[0]
    if not isinstance(program, str):
        raise ValueError(f"{where}: a pinned rule names one program, not alternatives")
    if len(pins) > _MAX_PINNED_PATHS or len(set(pins)) != len(pins):
        raise ValueError(f"{where}: host_executable must list at most {_MAX_PINNED_PATHS} distinct paths")
    for pin in pins:
        absolute = pin.startswith(("/", "\\\\")) or re.match(r"[A-Za-z]:[\\/]", pin) is not None
        if _has_surrogate(pin):
            raise ValueError(f"{where}: a host_executable path is not valid Unicode text (a lone surrogate)")
        if not absolute or len(pin) > _MAX_PINNED_PATH_CHARS or _has_control_character(pin):
            raise ValueError(f"{where}: host_executable path {pin!r} is not an absolute path")
        if any(part in (".", "..") for part in re.split(r"[\\/]", pin)):
            # AD-1328 S1 r3 (review r3, F3): such a pin is not canonical, and a POSIX '..' is resolved after symbolic
            # links, so it might never prove its program. Write the path without '.' and '..' components.
            raise ValueError(f"{where}: host_executable path {pin!r} has a '.' or '..' component; write the path without them")
        if windows_program_stem(pin) != windows_program_stem(program):
            raise ValueError(f"{where}: host_executable path {pin!r} does not name the program {program!r}")


def _check_examples(rule: CommandPolicyRule, where: str) -> None:
    for kind, examples in (("match", rule.match), ("not_match", rule.not_match)):
        if len(examples) > _MAX_RULE_EXAMPLES:
            raise ValueError(f"{where}: at most {_MAX_RULE_EXAMPLES} {kind} examples")
        for example in examples:
            _check_policy_text(example, f"{where}: {kind} example", _MAX_EXAMPLE_CHARS, newlines=True)
    both = sorted(set(rule.match) & set(rule.not_match))
    if both:
        raise ValueError(f"{where}: {both[0]!r} is both a match and a not_match example")


class CommandPolicyRule(BaseModel):
    """One ordered token-prefix rule of the command execution policy (AD-1328, #1530).

    ``pattern`` is matched against a simple command's words from the first.
    Position 0 is the program: a bare name, compared by basename (in the Windows
    dialects case-insensitively and without its extension). Every later position is
    an exact word. A tuple at any position lists alternatives. A rule matches a
    command that starts with its pattern; later words are unconstrained.

    ``decision`` is ``allow``, ``escalate`` or ``forbid``; the strictest decision of
    every matching rule wins. ``justification`` says why; a ``forbid`` rule names the
    ``alternative`` to use instead (often the governed path), an ``escalate`` rule may.

    ``host_executable`` pins an ``allow`` rule to absolute program paths: the rule
    allows its program only at one of them, and the same name anywhere else is
    refused. ``match`` and ``not_match`` are commands the rule must and must not
    match; ``probos.execution.command_policy.self_test`` judges them with the
    evaluator itself, and a failure is a startup error naming the rule.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    pattern: tuple[str | tuple[str, ...], ...]
    decision: CommandDecisionName
    justification: str
    alternative: str | None = None
    host_executable: tuple[str, ...] = ()
    match: tuple[str, ...] = ()
    not_match: tuple[str, ...] = ()

    @field_validator("name")
    @classmethod
    def _name_is_a_slug(cls, v: str) -> str:
        if re.fullmatch(_COMMAND_RULE_NAME_PATTERN, v) is None:
            raise ValueError(
                f"command policy rule name {v!r} must be 1 to 64 lower-case letters, "
                "digits, '_', '.' or '-', starting with a letter or digit"
            )
        return v

    @model_validator(mode="after")
    def _rule_is_well_formed(self) -> CommandPolicyRule:
        where = f"command policy rule {self.name!r}"
        _check_pattern(self.pattern, where)
        _check_policy_text(self.justification, f"{where}: justification", _MAX_RULE_PROSE_CHARS)
        if self.decision == "forbid" and self.alternative is None:
            raise ValueError(f"{where}: a forbid rule must name its alternative")
        if self.decision == "allow" and self.alternative is not None:
            raise ValueError(f"{where}: an allow rule has no alternative")
        if self.alternative is not None:
            _check_policy_text(self.alternative, f"{where}: alternative", _MAX_RULE_PROSE_CHARS)
        _check_pins(self, where)
        _check_examples(self, where)
        return self


class CommandPolicyConfig(BaseModel):
    """The command execution policy for ``run_command`` (AD-1328, #1530).

    With no ``rules`` there is no policy: every command runs exactly as it does
    without one. With rules, a command is split into simple commands (segments);
    each segment takes the strictest decision of the rules that match it, or
    ``unmatched_decision`` when none does, or ``unparseable_decision`` when the
    policy cannot read it, and the command takes the strictest decision of its
    segments. The policy only adds gates: it never bypasses consensus or the
    permission ladder. The ``max_*`` fields bound the work of one evaluation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rules: tuple[CommandPolicyRule, ...] = ()
    unmatched_decision: CommandDecisionName | None = None
    unparseable_decision: CommandDecisionName = "escalate"
    max_command_chars: int = Field(default=8192, ge=64, le=65536)
    max_segments: int = Field(default=32, ge=1, le=256)
    max_nesting: int = Field(default=3, ge=0, le=8)

    @model_validator(mode="after")
    def _decisions_open_no_bypass(self) -> CommandPolicyConfig:
        if len(self.rules) > _MAX_COMMAND_RULES:
            raise ValueError(f"command policy: at most {_MAX_COMMAND_RULES} rules")
        seen: set[str] = set()
        for rule in self.rules:
            if rule.name in seen:
                raise ValueError(f"command policy: rule name {rule.name!r} is declared twice")
            seen.add(rule.name)
        if not self.rules:
            return self
        if self.unmatched_decision is None:
            raise ValueError(
                "command policy: rules are configured, so declare unmatched_decision "
                "(allow for a deny-list, escalate for an allow-list)"
            )
        if self.unparseable_decision == "allow":
            raise ValueError(
                "command policy: unparseable_decision may not be allow; a command the "
                "policy cannot read could hide any forbidden one"
            )
        if COMMAND_DECISION_RANK[self.unparseable_decision] < COMMAND_DECISION_RANK[self.unmatched_decision]:
            raise ValueError("command policy: unparseable_decision must be at least as strict as unmatched_decision")
        return self


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
    # AD-1246: the wall clock for a call that names no `timeout`. Kept at the
    # shipped 30 s: it keeps an unasked-for runaway short on every surface,
    # including those that cannot promote. A longer job asks through `timeout`.
    timeout_seconds: float = 30.0
    # AD-1246: the longest a single run_python execution may run inside a direct
    # conversation turn that AD-1165 can promote (dm_agentic.promote_to_task_after_seconds
    # > 0). 0 = no long reach: every run keeps the 300 s inline ceiling.
    # Defends against a script that never finishes holding a long-run slot, a
    # thread and the turn's BF-732 slot; costs any single job longer than this.
    # The turn's BF-733 deadline (dm_agentic.promoted_run_deadline_seconds), less
    # a 300 s answer margin, also lowers it, but never below the 300 s inline
    # clock; a turn with less time left than that can be stopped by the watchdog
    # first. Recommended 1800; default 0 because a capability increase is the
    # operator's choice (see fetch_broker_enabled).
    max_runtime_seconds: float = Field(default=0.0, ge=0.0, le=86400.0)
    # AD-1246: ship-wide long runs at once. Each holds a dedicated thread, a
    # child process and its turn's BF-732 promoted-run slot, which comes from
    # that agent's AD-672 limit (default 4; smallest shipped role override 3).
    # 2 leaves at least one of those slots free even when both runs are one
    # agent's. It costs a further long run its reach: that run gets the 300 s
    # inline clock and says so (long_runs_busy). Upper bound = the long-run pool size.
    max_concurrent_long_runs: int = Field(default=2, ge=1, le=16)
    max_output_bytes: int = 65536           # 64 KB per stream
    # AD-1246: kept as shipped. It bounds a runaway allocation on POSIX (best effort)
    # and costs any job that needs more. Windows does not enforce it (BF-781), so
    # run_python's description leaves it out there.
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
    # AD-1246: kept as shipped. It covers a cold venv plus a handful of wheels and
    # cuts off an install stuck on the network, at the cost of a slow source build.
    install_timeout_seconds: float = 180.0  # venv create + pip install is slower
    # BF-890 (#1529): extra environment variable NAMES that a command started by
    # `run_command`, ShellCommandAgent or the red team's re-run may inherit, on
    # top of the built-in allowlist in probos.execution.command_env. The operator
    # sets this; no tool parameter can. A name that is not a plain identifier,
    # starts with PROBOS_, or contains a word in _CREDENTIAL_ENV_NAME_WORDS (or a
    # segment in _CREDENTIAL_ENV_NAME_SEGMENTS) is refused when the config loads.
    # A declared name that is not set is absent from the child. The run_python
    # sandbox does not read this field.
    command_env_passthrough: list[str] = Field(default_factory=list)

    @field_validator("command_env_passthrough")
    @classmethod
    def _declared_env_names_are_plain_and_not_credentials(cls, v: list[str]) -> list[str]:
        names: list[str] = []
        for raw in v:
            name = raw.strip()
            if re.fullmatch(_ENV_NAME_SHAPE_PATTERN, name) is None:
                raise ValueError(
                    f"execution.command_env_passthrough: {raw!r} is not a plain "
                    "environment variable name (letters, digits, underscore)"
                )
            upper = name.upper()
            if (
                upper.startswith(_RUNTIME_ENV_NAME_PREFIX)
                or any(word in upper for word in _CREDENTIAL_ENV_NAME_WORDS)
                or any(part in _CREDENTIAL_ENV_NAME_SEGMENTS for part in upper.split("_"))
            ):
                raise ValueError(
                    f"execution.command_env_passthrough: {name!r} is shaped like a "
                    "credential or is a ProbOS runtime variable, and is never passed "
                    "to a command; declare a non-secret variable instead"
                )
            if name not in names:
                names.append(name)
        return names

    @field_validator("max_runtime_seconds")
    @classmethod
    def _long_reach_must_lengthen(cls, v: float) -> float:
        # 300.0 twins probos.execution.long_runs.INLINE_WALL_CLOCK_SECONDS. This
        # module may not import probos, so test_ad1246_long_run_units asserts they agree.
        if 0.0 < v <= 300.0:
            raise ValueError(
                "execution.max_runtime_seconds must be 0 (off) or above 300 "
                "(the inline wall clock)"
            )
        return v


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
