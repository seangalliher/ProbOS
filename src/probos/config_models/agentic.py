"""Agentic dispatch, DM pipeline and discovery config models (AD-1270e2).

Batch 9 of the ``config.py`` extraction, and the last of the TRUE leaves.
Every model here is self-contained: it references no other config model and no
module-level helper in ``config.py``. Import these from ``probos.config``,
which re-exports them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TemporalConfig(BaseModel):
    """AD-502: Temporal awareness configuration."""
    enabled: bool = True
    include_birth_time: bool = True
    include_system_uptime: bool = True
    include_last_action: bool = True
    include_post_count: bool = True
    # AD-984d: the Captain's local IANA timezone (e.g. "America/Denver"). When
    # set, the crew's temporal context includes the Captain's CURRENT local time
    # + zone alongside UTC, so a reply about time-of-day is accurate instead of
    # inferred from UTC (the crew confabulated "3am" when it was 9pm Mountain).
    # Empty (default) = unchanged behavior; the crew see only UTC and must not
    # assert a specific local time. A bad/unknown name honest-degrades to no
    # extra line.
    captain_timezone: str = ""
    include_episode_timestamps: bool = True


class CreativeExpressionConfig(BaseModel):
    """Configuration for AD-525 v1 (Skills Inventory + Records Output)."""

    enabled: bool = True
    default_classification: Literal["ship", "department", "private"] = "ship"


class ClassificationGateConfig(BaseModel):
    """Configuration for AD-530 v1 disclosure gate."""

    enabled: bool = True


class AutonomyBoundariesConfig(BaseModel):
    """AD-511 v1: Agent Autonomy Boundaries (registry + observational detector)."""

    enabled: bool = True


class CrewDevelopmentConfig(BaseModel):
    """AD-507 v1: Crew Development Framework (Core Knowledge Curriculum Registry)."""

    enabled: bool = True


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


class ExtensionsConfig(BaseModel):
    """AD-481: Extension subsystem master config.

    AD-1215 (#1172) deleted the duplicate copy in
    src/probos/extensions/protocol.py along with ExtensionRegistry; this is now
    the only definition. ``enforce_sealed_core`` is the live field
    (cognitive/builder.py reads it on the sealed-path pre-write check).
    """

    enabled: bool = False
    enforce_sealed_core: bool = False
    default_profile: str = "minimal"
    extensions_dir: str = "src/probos/extensions"


class DmSanityGateConfig(BaseModel):  # AD-724
    """Configuration for the DM one-shot sanity gate.

    Default-ON: this config gates three previously-unconditional regex
    cleanups (BF-120, BF-119, AD-572) plus three new log-only checks.
    Disabling it preserves only the BF-120 markdown strip.

    Must stay structurally identical to the ``DmSanityGateConfig`` copy in
    ``cognitive/dm_sanity_gate.py`` (cluster invariant from the AD-724
    archive prompt — do not split DmSanityGate / DmSanityGateConfig /
    DmSanityResult across multiple files).
    """

    enabled: bool = True
    length_floor: int = 5
    repetition_prefix_chars: int = 100

    # AD-724-2: similarity-based repetition.
    repetition_similarity_threshold: float = 0.85

    # AD-724-1: controlled one-shot retry on rejection.
    retry_on_rejection: bool = True
    retry_warnings: list[str] = Field(
        default_factory=lambda: ["length_floor", "orphaned_tag"]
    )


class DmTargetedLookupConfig(BaseModel):  # AD-725 (Wave 159)
    """AD-725: pre-LLM targeted sub-intent dispatch on the DM one-shot path.

    Default OFF — opt-in because the lookup adds latency (max(classifier,
    lookup) ~ 100-300ms) and the v1 regex classifier is intentionally
    conservative. Per-store enables let the operator narrow the surface
    further.
    """

    enabled: bool = False
    classifier_tier: str = "regex"             # v1 ladder; "embedding" reserved for AD-725-2
    timeout_ms: int = 500                      # hard cap; lookup ABORTS on timeout
    enable_oracle: bool = True
    enable_episodic: bool = True
    enable_codebase: bool = False              # default OFF — codebase queries can be slow
    enable_knowledge: bool = True
    identity_enabled: bool = True              # AD-735: cheap in-memory self-identity lookup
    max_lookup_chars: int = 1500               # truncate lookup result before injection

    @field_validator("classifier_tier")
    @classmethod
    def _bound_classifier_tier(cls, v: str) -> str:
        allowed = {"regex", "embedding"}
        if v not in allowed:
            raise ValueError(
                f"classifier_tier must be one of {sorted(allowed)}, got {v!r}"
            )
        return v

    @field_validator("timeout_ms", "max_lookup_chars")
    @classmethod
    def _bound_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"must be >= 1, got {v}")
        return v


class DmDeliberateConfig(BaseModel):  # AD-934
    """AD-934 (Option C): flag-gated [THINK]/[DELIBERATE] deep-tier re-roll.
    Default OFF — opt-in because the re-roll adds a full deep-tier LLM pass
    (latency + cost) per marker-bearing reply."""
    enabled: bool = False
    tier: str = "deep"
    max_tokens: int = 800


class DmAgenticConfig(BaseModel):  # AD-1065
    """AD-1065: flag-gated conversational agentic turn. When enabled, a 1:1
    ``direct_message`` reply runs the AgenticLoop (tool-calling) instead of a
    single LLM pass, so an agent can read / write / execute on the Captain's
    behalf mid-conversation (Claude Cowork / Codex / Copilot parity). A no-tool
    turn is a single pass (the model just answers), so the flag only adds latency
    when the agent actually calls a tool. Default OFF (opt-in: adds tool-calling
    + per-call latency); 1:1 only (group / ward-room / proactive / vision turns
    keep the single-pass path)."""
    enabled: bool = False
    max_iterations: int = Field(default=5, ge=1, le=25)
    tier: str = "standard"
    continue_or_ask_enabled: bool = Field(
        default=False,
        description=(
            "AD-1164: when a conversational turn exhausts max_iterations, "
            "continue it or ask the Captain, instead of stopping silently. "
            "BF-697 stopped the partial work being DISCARDED; this stops it "
            "being reported as though the turn had finished. With the gate on, "
            "a turn that hits the step limit either (a) re-invokes with a fresh "
            "max_iterations allowance when a standing rule from AD-1154's "
            "ActionApprovalStore covers this agent, bounded by "
            "continue_or_ask_max_passes, or (b) files a kind='continue' request "
            "into the AD-853 approval queue and returns the partial work with an "
            "explicit statement that it stopped mid-task. Default-OFF per "
            "convention #14 \u2014 with the gate off the turn behaves exactly as it "
            "does today. Only max_iterations is ever continued: token_budget is "
            "a spend ceiling the operator set, error is usually provider-window "
            "exhaustion that a longer prompt makes worse, and complete means the "
            "model chose to stop. Every failure path (absent store, raising "
            "cache read, failed re-invocation) degrades to today's behaviour, so "
            "arming this can cost you an unnecessary question but never a turn."
        ),
    )
    continue_or_ask_max_passes: int = Field(
        default=2,
        ge=1,
        le=5,
        description=(
            "AD-1164: the hard cap on how many times ONE conversational turn's "
            "agentic loop is run, COUNTING THE FIRST. 1 means no re-invocation, "
            "identical to today; the cap is a bound, never an enable \u2014 "
            "continue_or_ask_enabled is what turns the feature on. Mirrors "
            "agentic_dispatch.crew_loop_until_done_max_iterations, which is the "
            "same bound on the crew fan-out. WORST CASE: each pass gets a fresh "
            "max_iterations (default 5, ceiling 25) turns and one turn can carry "
            "up to agentic_loop.max_parallel_tool_calls (ceiling 16) concurrent "
            "tool calls, so at this ceiling of 5 that is 5 x 25 x 16 = 2000 tool "
            "invocations for a single chat turn. A pass only happens while a "
            "live standing rule permits it, so reaching that ceiling requires "
            "the Captain to have issued one."
        ),
    )
    promote_to_task_after_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=600.0,
        description=(
            "AD-1165: seconds a conversational agentic turn may run before it "
            "stops being a reply and becomes a background task. A Captain DM is "
            "dispatched with a 60s intent TTL, so a turn that does real work "
            "(driving a browser, producing a document) is cancelled mid-flight "
            "and the Captain is told the agent did not respond \u2014 for a turn "
            "in which it was working correctly. Past this budget the run is NOT "
            "cancelled or restarted: the same in-flight loop keeps going, a "
            "work item is opened for it, the turn returns an acknowledgement "
            "inside the TTL, and the result is posted into the same thread when "
            "it lands. Set it BELOW the 60s chat TTL with room for one more "
            "loop iteration \u2014 35 is a reasonable starting value. 0 disables "
            "promotion, which is the default and is byte-identical to AD-1164: "
            "the turn is awaited inline and a long one still trips the TTL. "
            "Promotion needs a chat thread and a work-item store; without "
            "either it degrades to that same inline wait rather than promising "
            "a report nothing would deliver."
        ),
    )
    promoted_run_deadline_seconds: float = Field(
        default=1800.0,
        ge=0.0,
        le=86400.0,
        description=(
            "BF-733: seconds a PROMOTED background run may keep going before it "
            "is stopped and reported as stopped. Only applies after promotion; "
            "an unpromoted turn is still bounded by the chat TTL. Before this "
            "bound existed the reporter awaited the run unconditionally, so a "
            "run that suspended \u2014 measured on the reference vessel through a "
            "four-minute LLM endpoint outage \u2014 never reported and never "
            "reached a terminal state: the Captain held an acknowledgement "
            "promising a report nothing would ever deliver, and the concurrency "
            "slot the reporter holds was never released. The cost is stated "
            "rather than hidden: a run genuinely still working at this deadline "
            "is stopped, and reported as stopped rather than as finished. This "
            "is a CUTOFF the operator chooses, not a computed ceiling \u2014 "
            "dm_agentic max_iterations (up to 25) multiplied by a tier timeout "
            "(300s on the shipped standard tier) can exceed it before tool time "
            "is counted, so raise it if your promoted runs legitimately take "
            "longer. If the run does not answer the stop within a short grace "
            "it is reported as unconfirmed and its work item is left OPEN, "
            "because a terminal status would be a claim about a run that may "
            "still be executing. 0 restores the unbounded wait."
        ),
    )
    promoted_run_unconfirmed_grace_seconds: float = Field(
        default=1800.0,
        ge=0.0,
        le=86400.0,
        description=(
            "BF-825: seconds the reporter keeps waiting for a promoted run "
            "that REFUSED its cancellation, measured from the unconfirmed "
            "notice. Only that path reaches this bound \u2014 a run which "
            "answers the stop is already terminal. Before it existed the wait "
            "was unbounded, so the work item's updated_at stayed frozen at "
            "promotion while the reporter waited, and the work_board_reconciler "
            "read that frozen value as a stall and stranded the row 'failed' "
            "(BF-730). If the run then landed, the reporter posted a SUCCESS "
            "report into the thread and stored a successful episode, while "
            "transition_work_item refused the terminal-to-terminal move and "
            "returned None without raising \u2014 so the transcript, the recall "
            "layer and the board disagreed and nothing said so. "
            "Past this bound the reporter ends the row itself, 'failed', with "
            "the reason recorded in metadata, and the LATE RESULT IS "
            "DISCARDED. That is deliberate: the Captain already holds the "
            "interim notice, the run has had two full budgets, and the "
            "alternative is the pre-BF-730 condition that measured work items "
            "idle between 23.5h and 182h. No second report is posted, because "
            "the interim notice already said the run had not answered. "
            "The default is one more promoted_run_deadline_seconds budget "
            "rather than an independent number \u2014 a run that refused its "
            "cancellation gets exactly one more budget's worth to land, then "
            "it is over \u2014 so the maximum life of a promoted row on shipped "
            "config is about an hour, comfortably inside the reconciler's 4h "
            "strand_timeout_seconds. 0 restores the unbounded wait."
        ),
    )
    hold_degraded_turns: bool = Field(
        default=False,
        description=(
            "AD-1230: hold a Captain DM that the LLM was too degraded to "
            "answer, and reply in the same thread once the model recovers. OFF "
            "reproduces BF-714 exactly \u2014 the Captain is told the tier is "
            "cooling, how long it has left, and to send the message again. ON, "
            "the turn is held and the Captain is told an answer is coming, "
            "which is a promise the runtime then has to keep: a thread holding "
            "a turn accepts no further turns until that one is answered, held "
            "turns are replayed oldest-first one at a time, and every "
            "abandonment path (TTL, retries exhausted, shutdown) posts into the "
            "thread rather than dropping silently. Only turns whose degrade the "
            "runtime could actually diagnose are held \u2014 an unreadable health "
            "status is not evidence a retry would help. The queue is in memory "
            "by design: the outage it covers is measured in seconds (BF-674 "
            "clocked 48.8s), so a durable store would outlive its own TTL."
        ),
    )
    hold_degraded_turn_ttl_seconds: float = Field(
        default=900.0,
        ge=30.0,
        le=7200.0,
        description=(
            "AD-1230: how long a held turn waits for the model before it is "
            "abandoned with a note in the thread. Past this the answer is stale "
            "enough that resending is better than delivering it \u2014 an answer to "
            "a question the Captain asked an hour ago, arriving under "
            "everything said since, costs more attention than it returns."
        ),
    )
    hold_degraded_turn_max_threads: int = Field(
        default=16,
        ge=1,
        le=256,
        description=(
            "AD-1230: how many distinct threads may hold a turn at once. One "
            "turn is held per thread and that thread accepts no further turns "
            "until it is answered, so this bounds the ship, not the "
            "conversation. At the ceiling a further thread is told to resend "
            "rather than being promised an answer that would queue behind "
            "fifteen others."
        ),
    )
    compaction_enabled: bool = Field(
        default=False,
        description=(
            "AD-1167: compact the working context of a long conversational "
            "turn. The agentic loop re-flattens its entire message history "
            "into one prompt every iteration, so without compaction each added "
            "step re-pays for every step before it. Measured on a live "
            "instance: raising max_iterations from 10 to 20 took one turn from "
            "218,957 to 474,736 tokens \u2014 more than double for twice the steps "
            "\u2014 and produced a WORSE answer, because the early tool result that "
            "had located the target was buried under twenty rounds of "
            "re-flattened history. Compaction summarises older messages "
            "through the fast tier and preserves the most recent ones. The "
            "durable tool trace is unaffected: it is persisted after the loop "
            "finishes, so transparency is retained. Off by default; when off "
            "the loop is constructed exactly as before. Turn this on before "
            "raising max_iterations, not after."
        ),
    )
    compaction_threshold_tokens: int = Field(
        default=60_000,
        ge=0,
        description=(
            "AD-1167: estimated working-context size, in tokens, at which "
            "compaction runs. Only consulted when compaction_enabled is true; "
            "0 disables compaction even then. The default leaves generous room "
            "below a 200k context window while still engaging well before the "
            "runaway growth measured above."
        ),
    )


class WriteClaimGuardConfig(BaseModel):  # AD-1285 (#1087 / BF-687)
    """Whether a reply is checked against the turn's write ledger.

    Default ON, and that is a decision rather than an inheritance (#13(a)).
    Repo convention defaults a new CAPABILITY off; this is a safety control,
    and a default-OFF control defends nothing -- which is the AD-1157 failure
    mode #1087 names. It is safe on because ``assess_write_claim`` abstains on
    an unpopulated ledger, so a ship with no durable-write channel wired is
    byte-identical. The flag exists so the behaviour can be turned off without
    a revert.
    """

    enabled: bool = Field(
        default=True,
        description=(
            "AD-1285 (#1087): check a 1:1 reply against the turn's write "
            "ledger and append one honest sentence when a durable-write "
            "channel ran and wrote nothing. Reads no reply text. Default ON "
            "because this is a safety control rather than a capability, and a "
            "default-OFF control defends nothing (#13(a)) -- which is the "
            "AD-1157 failure mode #1087 names. Safe on: the verdict abstains "
            "unless a channel actually ran, so a turn with no write marker is "
            "byte-identical."
        ),
    )


class RepairConfig(BaseModel):  # AD-1172
    """Dispatching a reported fault to a harness of the Captain's choosing.

    A fault report (AD-1169) plus its trace summary (AD-1171) becomes a
    harness-neutral repair brief. The Captain approves the dispatch AND picks
    the target; nothing is spent and nothing is written without that.

    Targets are declared here rather than registered in code because dispatching
    to an external harness means rendering the brief and saying so — adding
    ``copilot`` to this list is the whole integration.
    """

    enabled: bool = Field(
        default=False,
        description=(
            "AD-1172: propose a repair when a fault is reported. Off by "
            "default. When on, a fault that reaches propose_after_occurrences "
            "raises an approval asking the Captain whether to dispatch it and "
            "to which harness. Approval is required before anything is spent: "
            "an Architect run costs deep-tier tokens, and a tool failing in a "
            "loop must not be able to spend them on its own."
        ),
    )
    targets: list[str] = Field(
        default_factory=lambda: ["architect"],
        description=(
            "AD-1172: harnesses this instance can dispatch a repair brief to, "
            "in the order they are offered. 'architect' is the internal crew "
            "(ArchitectAgent then BuilderAgent). Any other name is an external "
            "harness — GitHub Copilot, Claude Code, a person — reached by "
            "rendering the brief for the Captain to carry across. External "
            "targets need no code: the brief IS the interface, which is what "
            "keeps them first-class rather than a degraded path."
        ),
    )
    propose_after_occurrences: int = Field(
        default=2,
        ge=1,
        description=(
            "AD-1172: how many times a fault must recur before a repair is "
            "proposed. Matches the AD-1168/1170/1171 threshold: once is a "
            "transient, twice is the tool."
        ),
    )


class AgenticToolsConfig(BaseModel):  # AD-1072
    """AD-1072: conversational-loop discovery + delegation tools (default-OFF).

    Two keystone tools for the AD-1065 conversational ``AgenticLoop``:
    ``search_capabilities`` (read-only discovery across tools / skills /
    mesh-intents) and ``delegate_task`` (hand a bounded subtask to another crew
    agent by callsign, routed through the same governed
    ``WorkItemAgenticExecutor`` so its tool permissions / consensus gates /
    tool-trace logging all apply). Both default OFF and additive: with the flags
    off, ``WorkItemAgenticExecutor.run`` is byte-identical to today.

    AD-1139 adds ``oracle_query_enabled`` alongside them: the read-only Oracle
    consult tool that lets an agent reach the ship's shared knowledge commons
    (Σ tiers only, never the sovereign episodic shard) *during* a task. Also
    default-OFF, and gated in the same place, so the three flags share one
    byte-identity guarantee.

    AD-1140 adds ``publish_finding_enabled`` and its two bounds: the write half
    of Σ, letting a crew agent record a finding into Ship's Records so a
    different agent in a different session reaches it through ``oracle_query``.
    There is no consensus gate on the native-tool path, so ``max_per_hour`` and
    ``max_content_chars`` are the governance instrument rather than decoration —
    every publish is a git commit and an embedding upsert.
    ``max_content_chars`` defaults to 4000 to match ``semantic._RECORD_DOC_CHARS``,
    the amount of a record that is actually embedded, so what an agent publishes
    is what stays discoverable.

    AD-1141 wires both halves into the crew loop and adds five fields.
    ``crew_sigma_context_enabled`` is the single ablation gate: OFF (default)
    means a crew child's ``task_text`` is byte-identical to pre-AD-1141, which
    is what preserves the Nooplex §8.3 control arm. The other four are bounds,
    not gates, and each carries a caveat worth stating plainly:

    * ``crew_sigma_min_score`` (0.35) is a **starting value, not a derived
      one** — it is the first knob to tune if the ablation's ON arm shows a
      null effect.
    * That floor is applied to ``OracleResult.score``, which is **not
      normalised across tiers**. ``OracleService.query`` merges six tiers whose
      scores are computed six different ways — keyword-hits/10 (records),
      embedding similarity (records-semantic, semantic), word-overlap/5
      (operational), ``weight x confidence x hop_proximity`` (graph),
      token-overlap fraction (health) — and ``archive`` is scored by **recency
      alone** (``1/(1 + age_days*0.01)``), carrying no relevance term at all,
      so a recent archive entry clears any sane floor regardless of relevance.
      A single floor is therefore biased toward whichever tier happens to score
      highest, and it is a blunt volume control rather than a principled
      relevance threshold. Normalising the tiers is the real fix and is not in
      this AD's scope.
    * ``publish_finding_max_per_hour_ship`` (40) bounds the ship-wide write
      **rate**; per-author ``max_per_hour`` does not bound ship-wide volume at
      all. It does **not** make the AD-550 near-duplicate scan sound: 40/hr
      against a 72-hour staleness window admits far more entries than that
      scan's 20-entry cap examines, so duplicates can still slip past. This
      bound limits how fast the commons grows, not what the dedup window
      sees.

    AD-1153 adds ``browser_enabled``: offer the already-registered
    ``BrowserTool`` to the agentic loop so a task that needs a real
    application's rendered state reads the live page instead of degrading to
    ``http_fetch``. Also default-OFF, and gated on ``browser_tool.enabled``
    as well, so the availability logic is not duplicated.

    v1 is **read-only**, and that is a property of the tier ladder rather than
    a preference. ``classify_action`` puts ``state`` / ``extract_text`` /
    ``back`` / ``forward`` / ``wait`` at tier 1 and ``goto`` unconditionally at
    tier 2; only ``click`` / ``type`` / ``drag`` / ``mouse_button`` and the
    always-tier-3 verbs can escalate. So the offered set provably never reaches
    the tier-3 confirmation gate — which matters, because that gate returns a
    SUCCESS-shaped ``intervention_required`` payload (``error=None``) that an
    unattended caller reads as completion. ``click`` / ``type`` / ``scroll``
    wait on AD-1154 and its approval inbox.

    Two consequences worth stating plainly:

    * ``browser_tool.domain_allowlist`` defaults to ``None`` = allow-all, so on
      shipped defaults an agent granted the browser may navigate to any host
      absent from ``domain_denylist``. Requiring an allowlist would make the
      feature useless for the research tasks that motivate it, so the executor
      WARNs once at first offer instead. Set an allowlist to bound egress.
    * ``browser_tool.destructive_url_patterns`` is **not** a ``BrowserTool``
      guardrail — its only reader is the AD-745 DM dispatch stage, which this
      path does not use. An agentic-loop caller gets the domain allow/denylist,
      ``classify_action`` tiering, per-domain rate limiting and the session
      duration cap.

    AD-1180 adds ``disposition_enabled``: compose the shared agentic
    disposition into the system prompt inside ``WorkItemAgenticExecutor.run``.
    It belongs here rather than on ``dm_agentic`` precisely because the paths it
    fixes are the NON-conversational ones — crew children, the AD-860
    convergence re-run and AD-1072 delegation all reach the same executor with
    the same eleven-group tool array and, before this flag, no disposition about
    using any of it. Default-OFF like every other flag on this model, so an
    operator who does not opt in gets a byte-identical system prompt; unlike the
    others, turning it ON changes what the model READS rather than what it
    HOLDS."""

    tool_search_enabled: bool = False
    delegation_enabled: bool = False
    delegation_max_depth: int = Field(default=1, ge=0, le=3)
    delegation_max_iterations: int = Field(default=5, ge=1, le=25)
    delegation_tier: str = "standard"
    oracle_query_enabled: bool = False  # AD-1139
    publish_finding_enabled: bool = False  # AD-1140
    publish_finding_max_per_hour: int = Field(default=12, ge=1, le=100)
    publish_finding_max_content_chars: int = Field(default=4000, ge=200, le=20000)
    # AD-1141 DD-6: ship-wide publication budget, checked before the per-author
    # limiter so a single author cannot be told it hit its personal limit when
    # the ship budget is what actually refused it.
    publish_finding_max_per_hour_ship: int = Field(default=40, ge=1, le=500)
    # AD-1153: offer the registered BrowserTool to the agentic loop, read-only.
    browser_enabled: bool = Field(
        default=False,
        description=(
            "AD-1153: offer the registered BrowserTool to the agentic loop. "
            "v1 is READ-ONLY — the loop admits only goto, state, extract_text, "
            "back, forward and wait, which are exactly the actions that stay "
            "below the tier-3 confirmation gate; click/type/scroll wait on "
            "AD-1154. Also requires browser_tool.enabled plus an importable "
            "Playwright. Egress consequence: browser_tool.domain_allowlist "
            "defaults to None, which permits every host absent from "
            "domain_denylist — set an allowlist to bound where an agent may "
            "navigate."
        ),
    )
    # AD-1180: compose the shared agentic disposition on EVERY path that hands
    # out tools, not just the Captain's 1:1 DM turn.
    disposition_enabled: bool = Field(
        default=False,
        description=(
            "AD-1180: compose the shared agentic disposition "
            "(probos.cognitive.agentic_disposition.AGENTIC_DISPOSITION) into "
            "the system prompt inside WorkItemAgenticExecutor.run, so it "
            "reaches every path that hands an agent a tool array. AD-1177 "
            "authored that text and it reached exactly ONE of the five callers "
            "-- the Captain's 1:1 DM turn -- because the other four (the "
            "AD-856 task path, crew children, the AD-860 convergence re-run and "
            "AD-1072 delegation) pass the agent's STATIC instructions attribute "
            "straight through while receiving the same eleven-group tool array. "
            "Default-OFF: with this False the system prompt reaching the loop "
            "is byte-identical to AD-1177 on every path. Turning it ON is a "
            "REAL behaviour change for crew children, verifier convergence and "
            "delegated sub-agents by design -- it adds roughly 1,500 characters "
            "of disposition to each of those runs and tells them to be "
            "resourceful, to treat run_python as the general-purpose "
            "instrument, and to act inside their orders. Interaction to know: "
            "crew_token_budget (AD-1142) is a HARD STOP that fails a child and "
            "blocks its dependents; it defaults to None, so on shipped defaults "
            "there is no ceiling for these characters to push a child over."
        ),
    )
    # AD-1141: Σ into the crew loop. The bool is the ablation gate; the three
    # bounds below only ever narrow what an already-enabled consult injects.
    crew_sigma_context_enabled: bool = False  # AD-1141
    crew_sigma_max_chars: int = Field(default=2000, ge=200, le=8000)
    crew_sigma_max_entries: int = Field(default=4, ge=1, le=12)
    crew_sigma_min_score: float = Field(default=0.35, ge=0.0, le=1.0)
    self_query_enabled: bool = Field(
        default=False,
        description=(
            "AD-1258: offer first-person telemetry queries through the governed "
            "agentic loop."
        ),
    )


class DiscoveryConfig(BaseModel):
    """AD-708e: LAN mDNS service advertisement for PADD discovery (#484).

    Default-OFF (opt-in). Requires the optional `zeroconf` extra
    (`pip install probos[discovery]`). Advertises a stable `.local`
    hostname + LAN A record + the live server port so a phone on the
    LAN can reach the HXI without a DHCP IP. Advertises NOTHING when
    off, when the lib is absent, or when the server is bound to loopback.

    SECURITY: advertises only non-sensitive fields (service type, instance
    name, LAN IP, port). Never a token, identity, or path. NOTE: auth is
    OFF by default (auth.crew_scope_token=""), so advertising a default
    install makes it LAN-discoverable AND LAN-accessible — set a token and
    bind --host 0.0.0.0 deliberately before enabling this.
    """

    enabled: bool = Field(default=False, description="Master switch for LAN mDNS advertisement. Default OFF.")
    service_type: str = Field(default="_probos._tcp.local.", description="DNS-SD service type (must end in '.local.').")
    hostname: str = Field(default="probos", description="mDNS host label; advertises '<hostname>.local'. Bare label, no dots.")
    instance_name: str = Field(default="ProbOS", description="Human-readable DNS-SD instance name. NON-sensitive — never a secret.")
    txt_path: str = Field(default="/", description="TXT 'path' hint for the HXI entry point.")

    @field_validator("service_type")
    @classmethod
    def _validate_service_type(cls, v: str) -> str:
        if not v.endswith(".local."):
            raise ValueError("service_type must end with '.local.'")
        return v

    @field_validator("hostname")
    @classmethod
    def _validate_hostname(cls, v: str) -> str:
        if "." in v or "/" in v or not v:
            raise ValueError("hostname must be a non-empty bare DNS label (no dots/slashes)")
        return v


class CapabilityTriageConfig(BaseModel):
    """AD-854: Acquire-vs-build triage grant fast-path gating.

    Conservative defaults — the zero-prompt grant fast path is OFF and the trust
    floor is high, so a grant is auto-approved only after the operator opts in.
    ``install`` and ``build`` never use the fast path (Captain / self-mod gate).
    """

    grant_fast_path_enabled: bool = False
    grant_trust_floor: float = 0.8

    @field_validator("grant_trust_floor")
    @classmethod
    def _trust_floor_in_unit(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("grant_trust_floor must be in [0.0, 1.0]")
        return v


class AgenticDispatchConfig(BaseModel):
    """AD-856: Gate the AgenticLoop execution path for dispatched work items.

    Conservative default per convention #14 — the multi-turn loop is OFF, so
    dispatched work items keep using the existing single-shot ``handle_intent``
    path until the operator opts in.
    """

    enabled: bool = False

    # AD-859: bound the crew fan-out so a wide parent (many child subtasks)
    # cannot exhaust the LLM tier. Conservative default per Safety Budget —
    # keeps concurrent subtask runs small until the operator widens it.
    max_parallel_subtasks: int = Field(default=3, ge=1, le=64)

    # AD-860: cap the adversarial verify -> re-run -> re-verify convergence
    # loop. Conservative default per Safety Budget — at most two correction
    # rounds before a still-refuted subtask is escalated as "unverified"
    # rather than looped indefinitely.
    max_convergence_rounds: int = 2

    # AD-867: gate the full crew pipeline (resolve -> delegate -> fan-out ->
    # verify -> synthesize) behind one runtime entry point. Conservative default
    # per convention #14 — the orchestrator trigger stays OFF so a multi-spec
    # dispatch keeps the existing single-agent path until the operator opts in.
    orchestrator_enabled: bool = False

    max_active_crew_sessions: int = Field(default=2, ge=1, le=32)
    crew_resume_scan_limit: int = Field(default=100, ge=1, le=1_000)
    crew_ingress_scan_limit: int = Field(default=100, ge=1, le=1_000)
    crew_ingress_semantic_call_limit: int = Field(default=32, ge=1, le=128)
    crew_ingress_semantic_threshold: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    crew_provisioning_repair_limit: int = Field(default=100, ge=1, le=1_000)
    crew_recovery_max_retries: int = Field(default=3, ge=0, le=10)
    crew_recovery_initial_backoff_seconds: float = Field(
        default=5.0,
        ge=0.0,
        le=3_600.0,
    )
    crew_recovery_max_backoff_seconds: float = Field(
        default=300.0,
        ge=0.0,
        le=86_400.0,
    )

    # ── AD-1142: crew-child working-context compaction + token budget ───────
    #
    # JUSTIFICATION IS CONTEXT-WINDOW ECONOMICS, NOT TRANSPARENCY. A crew
    # child's working context is unbounded today: ``max_iterations`` bounds
    # TURNS, ``agentic_loop.tool_result_max_chars`` ships at 0 (each tool
    # result unbounded), and one AD-1147 turn can append up to
    # ``agentic_loop.max_parallel_tool_calls`` results. Enough turns of
    # unbounded output exhaust the provider window, ``llm_client.complete()``
    # raises, and the child returns ``stopped_reason="error"`` — its dependents
    # stay blocked and the failure reads as an LLM fault rather than a design
    # gap. Compaction bounds the working context. That is its entire claim.
    #
    # It is NOT an observability mechanism and does not claim to be one. What
    # compaction drops is retained as follows:
    #
    #   tool outputs (role:"tool")  -> PARTIALLY, via AD-1151
    #                                  tool_trace_output_max_chars (8192/output)
    #                                  and tool_trace_max_bytes (256 KiB/blob)
    #   assistant reasoning text    -> NOWHERE
    #   assistant/tool correlation  -> id, name and arguments only
    #   the flattened prompt sent   -> NOWHERE
    #   the compaction summary      -> NOWHERE
    #
    # and the durable trace is not a superset of the transcript either:
    # ``tool_result_max_chars`` ships at 0, and no finite durable cap beats an
    # unbounded transcript, so on shipped defaults the trace records LESS than
    # the model saw.
    crew_compaction_enabled: bool = Field(
        default=False,
        description=(
            "AD-1142: compact a crew child's working context when it crosses "
            "crew_compaction_threshold_tokens, instead of letting it grow "
            "until the provider rejects the request. Default-OFF per "
            "convention #14 — with the gate off no compactor is threaded to "
            "the child's AgenticLoop at all and the run is byte-identical to "
            "pre-AD-1142. Compaction is BEST-EFFORT: a single AD-1147 "
            "tool-call group is preserved whole, so one turn's fan-out can "
            "exceed any threshold, in which case the loop warns and continues "
            "rather than retrying. Compaction is a context-window mechanism, "
            "NOT a transparency one: it drops assistant reasoning text, the "
            "flattened prompt and the summary itself, and NONE of those are "
            "recorded in any durable store. Only tool OUTPUTS survive, "
            "bounded, via the AD-1151 tool trace."
        ),
    )
    crew_compaction_threshold_tokens: int = Field(
        default=60_000,
        ge=1_000,
        le=1_000_000,
        description=(
            "AD-1142: the crew child's working-context ceiling, in estimated "
            "tokens. Measures OCCUPANCY of the message list (content plus the "
            "serialised tool_calls array), not cumulative spend — see "
            "crew_token_budget for the spend ceiling. Crossing it shrinks the "
            "history and continues. 60000 is a STARTING VALUE, NOT A DERIVED "
            "ONE: the SWE harness compacts at 0.8 x 100000, and crew children "
            "run up to max_parallel_subtasks concurrently (default 3), so 60000 "
            "is 180000 of simultaneous provider load at the default fan-out. It "
            "is the first knob to tune if children still fail with "
            "stopped_reason='error'. AD-1147 interaction: one turn appends up "
            "to agentic_loop.max_parallel_tool_calls results, so with "
            "agentic_loop.tool_result_max_chars at 0 (unbounded, the shipped "
            "default) a SINGLE turn can cross any threshold and compaction "
            "cannot converge. With a non-zero tool_result_max_chars the "
            "per-turn ceiling is max_parallel_tool_calls x "
            "tool_result_max_chars characters, which must stay comfortably "
            "under crew_compaction_threshold_tokens x 4 for compaction to "
            "converge; at the AD-1147 ceiling of 16 that is 16 x the cap. "
            "There is deliberately no validator relating them — the relation "
            "is stated here and asserted in tests. Only consulted when "
            "crew_compaction_enabled is True."
        ),
    )
    crew_token_budget: int | None = Field(
        default=None,
        ge=1024,
        description=(
            "AD-1142: cumulative-spend ceiling for one crew child, in tokens. "
            "None (the default) means no budget, which is today's behaviour. "
            "This is a HARD STOP, not a shrink: crossing it returns "
            "stopped_reason='token_budget', which crew_executor maps to "
            "status='failed', so the child's DEPENDENTS STAY BLOCKED and no "
            "partial output is persisted as done. That consequence is why it "
            "defaults to None. It is INDEPENDENT of crew_compaction_enabled — "
            "a Safety Budget ceiling is useful with or without compaction, and "
            "gating it on the compaction flag would mean enabling compaction "
            "silently introduced a new failure mode. The two knobs are "
            "different mechanisms: crew_compaction_threshold_tokens is a "
            "working-context ceiling (cross it, shrink and continue); this is "
            "a spend ceiling (cross it, stop and fail). AD-1155 interaction: "
            "when crew_loop_until_done_enabled is True this budget is SHARED "
            "across the outer iterations and carried forward as a remainder, "
            "never reset per iteration, so iterations 2+ run with LESS room "
            "than the first one. It is a ceiling, not an allowance."
        ),
    )
    crew_loop_until_done_enabled: bool = Field(
        default=False,
        description=(
            "AD-1155: re-invoke a crew child that stopped without finishing, "
            "with a fresh independently governed run each time, bounded by "
            "crew_loop_until_done_max_iterations. Default-OFF per convention "
            "#14 \u2014 with the gate off the child runs exactly once and the call "
            "is byte-identical to pre-AD-1155. This does NOT replace "
            "SubtaskVerifier.converge_for_session, which is a separate LIVE "
            "outer loop driven by an LLM judge on the finalizer path; the two "
            "compose, and the four-way worst case in "
            "crew_loop_until_done_max_iterations assumes they do. Only a "
            "stopped_reason the executor classifies as re-invokable is ever "
            "re-run, which today is max_iterations ALONE: token_budget is a "
            "spend ceiling the operator set, error is usually provider-window "
            "exhaustion that a longer prompt makes worse, and complete means "
            "the model chose to stop."
        ),
    )
    crew_loop_until_done_max_iterations: int = Field(
        default=2,
        ge=1,
        le=5,
        description=(
            "AD-1155: the hard outer cap on how many times ONE crew child is "
            "run. 1 means no re-invocation, identical to today; the cap is a "
            "bound, never an enable \u2014 crew_loop_until_done_enabled is what "
            "turns the feature on. WORST CASE, STATED PLAINLY: per outer "
            "iteration a child gets AGENTIC_MAX_ITERATIONS (25) turns, and one "
            "turn can carry up to agentic_loop.max_parallel_tool_calls "
            "(ceiling 16) concurrent tool calls, so at this ceiling of 5 that "
            "is 5 x 25 x 16 = 2000 tool invocations FOR ONE CHILD \u2014 before "
            "max_parallel_subtasks (default 3, ceiling 64) multiplies it "
            "across siblings and before converge_for_session adds up to 8 "
            "correction rounds on the finalizer path. That is the four-way "
            "product: convergence x outer x inner x parallel. There is "
            "deliberately no validator relating these fields \u2014 the relation is "
            "stated here and asserted in tests, because a cross-field "
            "validator would turn an unrelated POST /config into a 422."
        ),
    )
    crew_loop_until_done_predicate: str = Field(
        default="stopped_reason",
        description=(
            "AD-1155: which completion predicate decides whether to re-invoke. "
            "An enum string, never an operator-supplied callable, which would "
            "be an arbitrary-code seam on the crew hot path. 'stopped_reason' "
            "(the default) continues only when the run was cut off by the turn "
            "counter \u2014 the one unambiguous signal. 'completion_marker' "
            "continues while crew_loop_until_done_completion_marker is absent "
            "from the trailing output; its weakness is that nothing teaches "
            "the agent to emit the marker on the FIRST pass, so a "
            "single-iteration run can never satisfy it. 'open_todos' continues "
            "while the PARENT work item has a checklist step in pending / "
            "in_progress / rejected; it is OPT-IN and INAPPLICABLE to the crew "
            "path as shipped \u2014 the crew fan-out never writes WorkItem.steps "
            "(steps move through the DM reply pipeline's [TODO_*] tags, which a "
            "crew child never enters), so a child with no checklist STOPS "
            "rather than being re-invoked forever. 'submitted' steps are "
            "excluded from 'actionable' because closing one needs rank >= "
            "communications.room_todos_min_rank, which the modal crew agent "
            "does not hold. An unknown value degrades to 'stopped_reason'."
        ),
    )
    crew_loop_until_done_completion_marker: str = Field(
        default="TASK COMPLETE",
        description=(
            "AD-1155: the exact line the 'completion_marker' predicate looks "
            "for in the trailing 200 characters of a child's output. Only "
            "consulted when crew_loop_until_done_predicate is "
            "'completion_marker', in which case the continuation block tells "
            "the agent to emit it. An empty or malformed value degrades to the "
            "default rather than to '', because an empty marker is contained "
            "in every string and would silently disable the predicate the "
            "operator just armed."
        ),
    )

    @model_validator(mode="after")
    def _validate_crew_recovery_backoff(self) -> "AgenticDispatchConfig":
        if self.crew_ingress_semantic_call_limit > self.crew_ingress_scan_limit:
            raise ValueError(
                "crew_ingress_semantic_call_limit must be less than or equal "
                "to crew_ingress_scan_limit"
            )
        if (
            self.crew_recovery_max_backoff_seconds
            < self.crew_recovery_initial_backoff_seconds
        ):
            raise ValueError(
                "crew_recovery_max_backoff_seconds must be greater than or equal "
                "to crew_recovery_initial_backoff_seconds"
            )
        return self


class OSActivityConfig(BaseModel):
    """AD-1054: consent gate for the desktop OS-activity sensor.

    A default-OFF, local-only foreground-window watcher in the desktop app
    (AD-759) reports active-window METADATA ONLY (app name + window title +
    optional app path/url) -- NEVER keystrokes, screen content, or clipboard.
    The event is emitted in-process; this AD does not persist or export it.

    Privacy-by-design: ``enabled`` defaults False (no capture without consent);
    the desktop watcher self-gates on this flag AND the runtime ingestion
    endpoint refuses when off (defense in depth).
    """

    enabled: bool = Field(
        default=False,
        description="Consent gate for the OS-activity sensor. Default OFF (no capture without consent).",
    )
    poll_interval_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Heartbeat cadence (seconds) the desktop watcher reads to poll the active window.",
    )


class GroundingConfig(BaseModel):
    """AD-1119: consent/enable gate for the referent-grounding gate (guard G1).

    A default-OFF, observe-only gate wired at the group-chat fan-out choke point
    (``group_chat_fanout``) that resolves each candidate referent in the room
    seed (git object / agent / ward-room channel) BEFORE the crew reasons on it,
    and logs a gap-regex-safe honest-absence cue for the unresolved ones. When
    OFF (default) the fan-out is byte-identical — no gate is built, no git
    subprocess runs. Enabling it changes NO behavior on its own (AD-1119 is
    observe-only; the cue is computed and logged, never injected). AD-1120 adds
    ``ground_before_collaborate_enabled`` — when that AND ``referent_gate_enabled``
    are both ON, the honest-absence cue for an unresolved CENTRAL referent IS
    injected into each dispatched crew agent's context (still default OFF). AD-1121
    adds ``confab_probe_enabled`` — when that AND ``referent_gate_enabled`` are both
    ON, a context-free self-consistency divergence probe runs on an UNRESOLVED
    central referent and, on a divergence verdict, records a CASCADE_CONFAB
    observation and notifies the Captain (best-effort, non-blocking; still default
    OFF).
    """

    referent_gate_enabled: bool = Field(
        default=False,
        description="AD-1119: consent/enable gate for the referent-grounding gate. Default OFF (byte-identical when off).",
    )
    ground_before_collaborate_enabled: bool = Field(
        default=False,
        description=(
            "AD-1120: when True (and referent_gate_enabled is also True), inject the "
            "AD-1119 honest-absence cue for an unresolved CENTRAL room referent into "
            "each dispatched crew agent's context. Default OFF (injection path "
            "byte-identical when off; has no effect unless referent_gate_enabled is on)."
        ),
    )
    confab_probe_enabled: bool = Field(
        default=False,
        description=(
            "AD-1121: when True (and referent_gate_enabled is also True), run a "
            "context-free self-consistency divergence probe on an UNRESOLVED central "
            "room referent; on a divergence verdict, record a CASCADE_CONFAB "
            "observation and notify the Captain. Best-effort + non-blocking. Default "
            "OFF (byte-identical when off; no effect unless referent_gate_enabled is on)."
        ),
    )
