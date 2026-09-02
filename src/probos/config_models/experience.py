"""Experience, interface and channel configuration models (AD-1270e2).

Batch 3 of the ``config.py`` extraction. Every model here is self-contained:
it references no other config model and no module-level helper in
``config.py``. Import these from ``probos.config``, which re-exports them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ApprovalInboxConfig(BaseModel):  # AD-1154
    """AD-1154: park an unattended consequential action instead of performing it.

    An unattended agent that reaches a tier-3 browser action currently has two
    outcomes: perform it, or receive the ``intervention_required`` payload the
    tier-3 gate returns with ``error=None`` — a SUCCESS-shaped no-op the model
    reads as completion. This config turns on the third: file a durable,
    reviewable record on the existing AD-853 approval queue (as a fourth
    ``kind="action"``), tell the agent honestly that the step did not happen, and
    carry on with the rest of the task.

    **Approval does not replay the parked action, and this is the design's honest
    limitation.** ``browser_tool.session_max_duration_seconds`` is 1800 s while a
    human decision takes minutes to days, so the session named in a parked ask is
    almost certainly reaped by the time the Captain looks. Creating a fresh
    session and replaying a page-relative selector against whatever that page
    looks like now is a *different act* from the one the Captain approved. What
    approval buys is a durable record, a trust signal, and — when
    ``standing_rules_enabled`` — a scoped, expiring rule that lets the NEXT run
    proceed without asking. It does not rescue the run that raised the ask, and
    the originating work item is not re-dispatched.

    **Two flags, not one.** ``enabled`` turns on parking. ``standing_rules_enabled``
    additionally permits a durable privilege grant. An operator who wants the
    audit trail without the "don't ask again" lever gets exactly that, and the
    riskier half stays off until asked for. Both default OFF; with ``enabled``
    off the dispatch path is byte-identical to AD-1153.

    **The inbox is bounded, and a full inbox degrades to a refusal.** An approval
    queue with no cap is a memory leak wearing a governance costume — and worse,
    400 pending asks is indistinguishable from 0 to a human. At
    ``max_pending_per_agent`` the wrapper refuses WITHOUT filing and logs at
    WARNING with the agent id and the count, so the operator learns the inbox is
    saturated from the log rather than from a panel silently growing. That bounds
    the damage when the human is absent; it does not solve the attention problem.

    ``pending_ask_ttl_hours`` marks an undecided ask stale. Stale means excluded
    from the per-agent cap count and rendered as stale — **not** auto-approved
    (which would make walking away the approval mechanism) and **not**
    auto-denied (which would silently discard a decision still worth making).

    **A standing rule must expire.** ``ActionApprovalStore`` declares
    ``expires_at NOT NULL`` in its schema, not merely in its method signature,
    because a standing rule with no TTL is a permanent privilege escalation
    nobody remembers granting. ``standing_rule_default_ttl_hours`` (24 h) sits
    deliberately far below ``standing_rule_max_ttl_hours`` (168 h) so the
    low-effort path is the short-lived one; a request above the max is clamped,
    not rejected.

    **No HXI affordance ships with this.** The existing capability-request panel
    renders the fourth kind unchanged (it will show ``kind: action`` and the
    target), but there is no Approve-with-standing checkbox. ``grant_standing`` on
    ``POST /api/capability-requests/{id}/decide`` is API-only until a follow-up
    adds the control. Heuristic auto-approval is deliberately deferred.

    Cross-field relation documented rather than validated (AD-1142 precedent):
    ``standing_rule_default_ttl_hours`` should be ``<=
    standing_rule_max_ttl_hours``. It is clamped at issue time; a
    ``@model_validator`` here would turn an unrelated ``POST /config`` into a 422.
    """

    enabled: bool = Field(
        default=False,
        description=(
            "AD-1154: park a tier-3 unattended tool action as a durable "
            "capability request (kind='action') instead of letting the tier-3 "
            "gate return its success-shaped intervention_required no-op. The "
            "agent is told in an ERROR-shaped result that the step did not run, "
            "and the run continues. Approval does NOT replay the parked action "
            "— the browser session TTL (1800s) is far shorter than human "
            "decision latency, so replaying a page-relative selector against a "
            "changed page would be a different act. Off by default; off means "
            "the dispatch path is byte-identical to AD-1153."
        ),
    )
    standing_rules_enabled: bool = Field(
        default=False,
        description=(
            "AD-1154: additionally permit the Captain to convert an approval "
            "into a standing, scoped, mandatorily-expiring rule that answers "
            "the same ask on the next run. Separate from 'enabled' so an "
            "operator can take the audit trail without the durable privilege "
            "grant. Rules match (agent_id, tool_id, action, scope_key) exactly "
            "— there is no wildcard, and scope_key='' matches only an ask whose "
            "scope is also ''. No HXI affordance ships with this: grant_standing "
            "is API-only on POST /api/capability-requests/{id}/decide, and the "
            "capability-request panel has no Approve-with-standing control until "
            "a follow-up adds one."
        ),
    )
    standing_rule_max_ttl_hours: int = Field(
        default=168,
        ge=1,
        le=720,
        description=(
            "AD-1154: hard ceiling on a standing rule's lifetime. A requested "
            "TTL above this is clamped, not rejected. expires_at is NOT NULL in "
            "the action_approvals schema, so no standing rule can be issued "
            "without an expiry."
        ),
    )
    standing_rule_default_ttl_hours: int = Field(
        default=24,
        ge=1,
        le=720,
        description=(
            "AD-1154: TTL applied when the Captain approves with grant_standing "
            "but names no duration. Deliberately far below "
            "standing_rule_max_ttl_hours so the low-effort path is the "
            "short-lived one. Should be <= the max; clamped at issue time "
            "rather than validated, so an out-of-order pair cannot 422 an "
            "unrelated config write."
        ),
    )
    max_pending_per_agent: int = Field(
        default=20,
        ge=1,
        le=200,
        description=(
            "AD-1154: per-agent cap on undecided action asks. At the cap the "
            "wrapper REFUSES without filing and logs at WARNING with the agent "
            "id and count — a neglected inbox becomes an honest refusal within "
            "this many asks per agent rather than an unbounded queue that looks "
            "like progress."
        ),
    )
    pending_ask_ttl_hours: int = Field(
        default=72,
        ge=1,
        le=720,
        description=(
            "AD-1154: age at which an undecided ask is treated as stale. Stale "
            "asks are excluded from the max_pending_per_agent count but are "
            "NEITHER auto-approved NOR auto-denied — they keep status='pending' "
            "and keep appearing in the pending list, because auto-approving on "
            "timeout would make walking away the approval mechanism."
        ),
    )
    # AD-1159: work permits. Sited here rather than on agentic_tools because
    # this model already holds the ship's TTL-bounded tool-governance settings
    # (the AD-1154 standing-rule ceiling/default pair), and a permit is the same
    # class of thing one layer up: an expiring authority over an act. The
    # standing-rule fields' prefix convention is reused verbatim. Nothing reads
    # these three in AD-1159 — WorkPermitStore is constructed by tests only, and
    # AD-1160 is what wires it — so all three are inert on shipped defaults.
    work_permits_enabled: bool = Field(
        default=False,
        description=(
            "AD-1159: issue single-holder, expiring work permits over a "
            "workstation within a crew session, so at most one agent holds "
            "(session_id, workstation_id) at a time and its hazard ceiling is "
            "explicit rather than implied. A permit's issuing authority must "
            "differ from its holder — the officer who authorizes never performs "
            "— and every permit carries a mandatory expiry (expires_at is NOT "
            "NULL in the work_permits schema). Off by default; off means the "
            "dispatch path is byte-identical to AD-1158. Nothing consumes the "
            "store in AD-1159: it lands with tests and no callers so its first "
            "exercise is not in production. AD-1160 wires it."
        ),
    )
    work_permit_default_ttl_seconds: float = Field(
        default=3600.0,
        gt=0.0,
        le=86400.0,
        description=(
            "AD-1159: lifetime applied to a work permit whose issuer names no "
            "duration. One hour, deliberately short: a permit is authority to "
            "act on a live workstation, and the cost of an expiry that is too "
            "short is a reissue, while the cost of one that is too long is an "
            "authority nobody remembers granting. Expiry is lazy — a lapsed "
            "permit answers as absent on the next read rather than being reaped "
            "— so a stale row is inert, not active."
        ),
    )
    work_permit_max_tier_ceiling: int = Field(
        default=2,
        ge=1,
        le=3,
        description=(
            "AD-1159: highest classify_action hazard tier a work permit may "
            "authorize by default. 2 covers observation plus ordinary "
            "click/type/goto; tier 3 (eval_js, upload_file, fill_credential, "
            "checkout and payment paths) is excluded so reaching it needs an "
            "explicit Captain-issued permit rather than an inherited default. "
            "Bounded 1-3 because that is the whole tier ladder classify_action "
            "returns; a ceiling outside it is unrepresentable rather than "
            "merely discouraged."
        ),
    )


class BaselineVRMManifest(BaseModel):
    """AD-721g: per-rank baseline VRM filenames.

    Resolved against ``<avatars_dir>/_baselines/<filename>``. Each entry is a
    bare filename (no path separators, no parent-dir traversal). Empty string
    disables the tier baseline — the resolver then falls back to the seed
    profile, then to the parametric capsule. License-clean by construction:
    no avatar bytes ship in the repo; operators install their own files
    under the AD-721i-1 CC0/MIT/Apache/BSD/CC-BY whitelist.
    """

    ensign: str = ""
    lieutenant: str = ""
    commander: str = ""
    senior: str = ""


class CameraStreamConfig(BaseModel):
    """AD-733: client-side camera streaming controls."""

    enabled: bool = False
    """Default-OFF per privacy posture; operator flips explicitly."""

    default_fps: int = Field(default=1, ge=1, le=4,
        description=(
            "Client-side capture cadence. Vision tier inference budget caps "
            "this; 1 fps is the safe default."
        ),
    )

    frame_jpeg_quality: float = Field(default=0.6, ge=0.2, le=0.95)

    frame_max_dimension: int = Field(default=512, ge=128, le=1024,
        description="Longest-edge downsample target for capture.",
    )


class DesktopConfig(BaseModel):
    """AD-751: Desktop UX Surface — tray, hotkey, notifications, autostart."""

    enabled: bool = Field(
        default=False,
        description="AD-751: master switch for desktop surface. Default OFF (Wave 10 convention #14).",
    )
    tray_autostart: bool = Field(
        default=True,
        description="Auto-start tray icon on boot when desktop enabled.",
    )
    hotkey: str = Field(
        default="ctrl+shift+space",
        description="Global hotkey to activate mini-mode (pynput syntax).",
    )
    notification_timeout_sec: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Toast notification display duration (seconds).",
    )
    quiet_hours_start: str = Field(
        default="19:00",
        description="Start of quiet hours (HH:MM format, local time).",
    )
    quiet_hours_end: str = Field(
        default="08:00",
        description="End of quiet hours (HH:MM format, local time).",
    )
    lock_file: str = Field(
        default="~/.probos/yeo.lock",
        description="Single-instance lock file path.",
    )
    autostart_enabled: bool = Field(
        default=False,
        description="Register for OS autostart on boot.",
    )

    @property
    def quiet_hours_start_tuple(self) -> tuple[int, int]:
        """Parse quiet_hours_start into (hour, minute) tuple."""
        parts = self.quiet_hours_start.split(":")
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)

    @property
    def quiet_hours_end_tuple(self) -> tuple[int, int]:
        """Parse quiet_hours_end into (hour, minute) tuple."""
        parts = self.quiet_hours_end.split(":")
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


class DiscordConfig(BaseModel):
    """Discord bot adapter configuration."""

    enabled: bool = False
    token: str = ""                          # Bot token (prefer env var PROBOS_DISCORD_TOKEN)
    allowed_channel_ids: list[int] = []      # Empty = respond in all channels
    allowed_user_ids: list[int] = []         # Empty = respond to all users (SECURITY RISK)
    command_prefix: str = "!"                # "!status" -> "/status"
    mention_required: bool = False           # Only respond when @mentioned
    scout_channel_id: int = 0                # Discord channel ID for scout reports (0 = disabled)


class GroupChatConfig(BaseModel):
    """AD-915: ad-hoc group-chat turn-taking facilitator.

    Defaults preserve AD-914 (all crew reply, once): the truncation cap is
    OFF (0) and the convergence gate cannot fire until a real exchange has
    accumulated (>= convergence_min_messages from >= convergence_min_agents).
    """

    max_speakers_per_turn: int = 0          # 0 = off (AD-914 all-at-once). >0 caps NON-mentioned speakers.
    convergence_enabled: bool = True
    convergence_similarity_threshold: float = 0.6   # AD-614 Jaccard precedent
    convergence_min_messages: int = 4       # min recent agent msgs before the gate can fire
    convergence_min_agents: int = 2         # min distinct agents in the recent window
    weight_mention: float = 0.40            # also a hard-include (see facilitator)
    weight_recency: float = 0.25            # anti-domination / fairness
    weight_department: float = 0.25
    weight_trust: float = 0.10
    # AD-958a: exploration / anti-rich-get-richer term (Minimal Authority axiom —
    # earned trust, everyone has a path). A trust-weighted facilitator risks
    # rich-get-richer: a high-trust agent keeps being surfaced and a low-trust
    # but domain-relevant agent never gets a chance to EARN trust. The
    # exploration bonus is a deterministic "optimism under uncertainty" (UCB-
    # style) term: ``weight_exploration * department_relevance * (1 - trust)`` —
    # the more relevant AND the LESS proven an agent is, the bigger the boost,
    # so a domain-relevant newcomer is surfaced to earn trust while a high-trust
    # agent (already carried by the trust term) gets ~0 extra. Bounded below the
    # mention weight so a direct address always still wins; NO randomness (the
    # facilitator stays pure + deterministic). Transitional flag (#14) — Pydantic
    # default 0.0 (OFF, ranking byte-identical to pre-AD-958a); system.yaml sets
    # the live value.
    weight_exploration: float = 0.0
    # AD-958 (Natural Conversation epic #882, #894): conversational trust
    # learning loop (convergence-only v1). When a group conversation CONVERGES
    # (the AD-915 facilitator's pure test), credit each corroborated contributor
    # with a small POSITIVE trust observation, each verified by a DISTINCT peer
    # (no self-sourcing). The asymmetric negative weight (peer-corrects-peer) is
    # reserved for AD-958c and validated-but-unused in v1. Master flag ships OFF
    # (#14, default-OFF byte-identical: no extractor, no facilitator build, no
    # record_outcome — the trust network is identical to today); system.yaml
    # flips it on, then the Captain tunes the weights live.
    conversation_trust_enabled: bool = False
    conversation_trust_positive_weight: float = 0.05   # small per-contributor positive on convergence
    conversation_trust_negative_weight: float = 0.15   # asymmetry (>= positive); reserved for AD-958c, unused in v1
    conversation_trust_max_outcomes: int = 4           # bound: max positives recorded per conversation
    # AD-958c: peer-corrects-peer DETECT-AND-OBSERVE. A SEPARATE switch from the
    # positive write (conversation_trust_enabled) so the Captain can run the
    # correction detector in observe-only mode — emitting a structured log per
    # detected correction, writing NOTHING to the trust ledger — to measure its
    # precision on live transcripts BEFORE any negative trust write (AD-958d).
    # Default-OFF byte-identical (the detector never runs); system.yaml flips it.
    conversation_trust_correction_observe_enabled: bool = False
    # AD-918: per-agent rate limit on agent-initiated group-chat creation.
    # Conservative defaults prevent a create-storm without blocking
    # legitimate ad-hoc collaboration. Reuses the BF-163 (60s DM cooldown)
    # + BF-257 (sliding-window budget) shape.
    agent_create_cooldown_seconds: float = 60.0   # min seconds between two creates by one agent
    agent_create_max_per_window: int = 5          # max creates per agent per window
    agent_create_window_seconds: float = 3600.0   # sliding window (1 hour)
    # AD-925: auto-create ONE task-linked workspace room when CrewTaskExecutor
    # fans a parent out to >=2 distinct crew. Transitional flag (wave-10 #14) —
    # ships OFF; the Captain flips it on after reviewing AD-925..927. Note the
    # crew pipeline that drives the executor (agentic_dispatch.orchestrator_enabled)
    # also ships OFF, so a zero-config boot creates no task rooms.
    auto_task_room_enabled: bool = False
    # AD-935: bounded synchronous agent-to-agent reactivity. When enabled, an
    # agent reply in a group chat fans to the OTHER crew for up to
    # ``max_agent_rounds`` extra rounds, gated by the AD-915 convergence gate
    # + [NO_RESPONSE]. Transitional flag (#14) — ships OFF; system.yaml flips it
    # on. Synchronous within the Captain turn (no live-refresh exists yet).
    agent_reactivity_enabled: bool = False
    max_agent_rounds: int = 2   # extra agent-only rounds after the Captain round (0 = AD-914 single round)
    # AD-951: turn-allocation rule 1a ("current speaker selects next"). When
    # enabled (and reactivity is on), an agent that DIRECTLY ADDRESSES a peer by
    # callsign in a group reply ("@yeo ..." or "Yeo, ...") hard-includes that peer
    # as a speaker in the next cascade round (overriding the per-turn cap +
    # convergence, still bounded by max_agent_rounds). Makes AD-950's "hand the
    # floor to a named peer" mechanical. Transitional flag (#14) — ships OFF;
    # system.yaml flips it on. Off => the AD-935 cascade is byte-identical.
    agent_next_speaker_selection_enabled: bool = False
    # AD-961: cascade-extend-on-address. A directed address ("Ezri, ...") in the
    # LAST normal cascade round (round == max_agent_rounds) would otherwise be
    # dropped — the addressed peer never gets a turn. When next-speaker selection
    # is on, allow up to this many EXTRA rounds PAST max_agent_rounds, each
    # consumed only by an unanswered directed address, so a hand-off is always
    # answered. Bounded so a chain of mutual hand-offs (Ezri->Yeo->Ezri...) can't
    # ping-pong forever. Only takes effect when agent_next_speaker_selection_enabled
    # is on (which is itself an operator opt-in), so the default of 1 never
    # changes a zero-config boot. 0 = disable the extension (pre-AD-961 behavior).
    max_address_extensions: int = 1
    # AD-970: agent-initiated kickoff. When an agent OPENS a group chat with a
    # first message (the AD-924 [GROUP_CHAT] tag), fan that opening out to the
    # OTHER participants so they can respond — the agent-initiated analogue of a
    # Captain turn, bounded by the SAME AD-935 backstops (cap / convergence /
    # [NO_RESPONSE] / max_agent_rounds). Fixes the Captain-reported bug where an
    # agent opened a room and addressed a peer who never responded (the opening
    # was role="agent" and AD-914 fan-out gates on role=="captain"). Lifts the
    # deliberate AD-918 "no auto-reply on create" boundary, now that the bounded
    # cascade exists. Transitional flag (#14) — ships OFF (zero-config boot keeps
    # the AD-918 quiet-create behavior); system.yaml flips it on.
    agent_initiated_kickoff_enabled: bool = False
    # AD-1079: hint a Commander+ participant to convene a dedicated group chat
    # when a Ward Room thread becomes a sustained multi-crew working exchange
    # (the "social spark" the original agent-created rooms had). Default OFF — a
    # proactive nudge, opt in after watching cadence. Thresholds are conservative
    # so routine chatter is never nudged.
    escalation_suggestion_enabled: bool = False
    escalation_min_crew: int = 3
    escalation_min_posts: int = 6
    # AD-963a: broadcast turn-mode terminator. The AD-935 cascade stops at
    # ``max_agent_rounds`` or the convergence gate — right for a DISCUSSION
    # ("hash this out"), but wrong for a BROADCAST ("what do you ALL think?")
    # where the Captain wants EACH relevant crew member to answer ONCE, not
    # "until convergence" and not capped at two rounds. When enabled, a Captain
    # turn classified as a broadcast (a plural ask to the whole room) round-robins
    # every crew participant exactly once (relevance-ordered, each seeing prior
    # answers), naturally bounded by the participant count. A non-broadcast turn
    # (the default classification) is byte-identical to AD-935/961. Transitional
    # flag (#14) — ships OFF; system.yaml flips it on.
    broadcast_terminator_enabled: bool = False
    # AD-963b (Natural Conversation epic #882): broadcast department-dominant
    # weight tilt — the deferred-for-live-look third of #897 (AD-963a shipped the
    # terminator + ``classify_broadcast`` cue detector; AD-951 the directed
    # dispatch). ``turn_mode_policy_enabled`` is the MASTER flag for the 3-mode
    # turn-order policy (directed / broadcast / discussion). OFF (default) =>
    # byte-identical AD-963a: the broadcast terminator keys off the shipped
    # ``classify_broadcast`` and the facilitator uses the standard fixed weights.
    # ON => a BROADCAST turn re-weights the facilitator so the DOMAIN EXPERT
    # frames first (department-dominant), while DIRECTED and DISCUSSION turns keep
    # the standard weights. The broadcast weights need not sum to 1 (the
    # facilitator ranks by magnitude, it does not normalize). Transitional flag
    # (#14) — ships OFF; system.yaml flips it on.
    turn_mode_policy_enabled: bool = False
    broadcast_weight_mention: float = 0.20
    broadcast_weight_recency: float = 0.15
    broadcast_weight_department: float = 0.50
    broadcast_weight_trust: float = 0.10
    # AD-956 (Natural Conversation epic #882): scale-aware facilitation. The
    # facilitator already ranks the room every turn (AD-915) and surfaces an
    # advisory room-awareness signal (AD-955). AD-956 makes ENFORCEMENT
    # scale-aware: a small room (2-4 voices, below ``facilitation_gate_threshold``)
    # self-regulates with the cap OFF (advisory) so every relevant crew member may
    # answer (still convergence-gated, [NO_RESPONSE]-thinned, max_agent_rounds-
    # bounded); a large room (>= threshold, ratified at 5 on span-of-control
    # grounds) keeps the cap to GATE the fan-out. ``force_facilitation_min`` is an
    # opt-in floor that gates even small rooms (0 = off). Master flag ships OFF
    # (#14, default-OFF byte-identical: the classifier never runs, every round
    # uses ``max_speakers_per_turn`` EXACTLY as today); ``system.yaml`` flips it on.
    scale_aware_facilitation_enabled: bool = False
    facilitation_gate_threshold: int = Field(default=5, ge=2)
    force_facilitation_min: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_conversation_trust(self) -> "GroupChatConfig":
        """AD-958: enforce the conversational-trust invariants — a non-negative
        positive weight, the asymmetry (negative >= positive so a future
        correction always outweighs a corroboration, AD-958c), and a
        non-negative outcome bound."""
        if self.conversation_trust_positive_weight < 0:
            raise ValueError("conversation_trust_positive_weight must be >= 0")
        if self.conversation_trust_negative_weight < self.conversation_trust_positive_weight:
            raise ValueError(
                "conversation_trust_negative_weight must be >= "
                "conversation_trust_positive_weight (asymmetry: a correction "
                "outweighs a corroboration)"
            )
        if self.conversation_trust_max_outcomes < 0:
            raise ValueError("conversation_trust_max_outcomes must be >= 0")
        return self


class KnowledgeBrowserConfig(BaseModel):
    """AD-562: Ship's Records Knowledge Browser (Phases 1-4 OSS)."""
    enabled: bool = False
    max_graph_nodes: int = Field(default=500, ge=0, le=2000)
    max_graph_edges: int = Field(default=1000, ge=0, le=5000)
    jaccard_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    max_suggestions_per_entry: int = Field(default=5, ge=0, le=50)
    index_refresh_seconds: int = Field(default=300, ge=10, le=3600)


class LipSyncConfig(BaseModel):
    """AD-721b-1 — Server-side lip-sync backend selection.

    Default: ``heuristic`` — the AD-721b v1 text→viseme driver in
    ``ui/src/audio/lipSyncTrack.ts``. Operator opts in to ``rhubarb``
    by setting ``backend: "rhubarb"`` AND providing the binary at
    ``binary_path``. If the binary is missing or a probe fails, the
    system logs WARNING and degrades to the heuristic path — speech
    must NEVER stop animating because of a viseme failure.
    """

    enabled: bool = True
    """Master switch for the lip-sync pipeline. ``False`` disables both
    backends — CrewVRM falls back to the AD-721 D5 amplitude path."""

    backend: Literal["heuristic", "rhubarb"] = "heuristic"
    """``heuristic``: AD-721b v1 text→viseme. ``rhubarb``: subprocess to
    rhubarb-lip-sync for phonetic alignment of real audio."""

    binary_path: str = "tools/rhubarb/rhubarb"
    """Path (relative to repo root or absolute) to the rhubarb binary.
    On Windows the wrapper auto-appends ``.exe`` if the literal path
    does not exist. Operator places the binary themselves; the repo
    never ships it (gitignored under ``/tools/``)."""

    timeout_seconds: float = 30.0
    """Subprocess timeout. rhubarb on a 5-10s utterance typically takes
    1-3s; the default leaves ample headroom for cold disk reads. Tier-2
    log-and-degrade on TimeoutExpired — falls back to heuristic."""

    ffmpeg_binary_path: str = "tools/ffmpeg/ffmpeg"
    """AD-721b-1a: optional ffmpeg binary for converting non-WAV/OGG audio
    (e.g. Chrome MediaRecorder's audio/webm) to rhubarb's required format.
    When the binary is missing, generate_visemes honest-degrades to the
    heuristic lip-sync path (BF-292 contract preserved). Operator places
    the binary; the repo never ships it (gitignored under ``/tools/``).
    License posture: ffmpeg is LGPL-2.1+ / GPL-2+; the operator-provided
    binary keeps ProbOS distribution clean."""


class OnboardingConfig(BaseModel):
    """AD-442: Onboarding ceremony configuration."""

    enabled: bool = True
    activation_trust_threshold: float = 0.65
    naming_ceremony: bool = True  # If False, agents keep seed callsigns


class ScreenStreamConfig(BaseModel):
    """AD-733-2: client-side screen-share streaming controls.

    Mirrors :class:`CameraStreamConfig`. Default-OFF — Captain must opt-in
    explicitly. ``getDisplayMedia`` browser-prompt consent is the floor;
    this toggle is the additional ProbOS-side switch the operator can flip
    to hide the surface entirely (e.g. kiosk mode).
    """

    enabled: bool = False
    """Default-OFF — Captain flips explicitly."""

    default_fps: int = Field(default=1, ge=1, le=4,
        description=(
            "Client-side screen-capture cadence. Vision tier inference budget "
            "caps this; 1 fps is the safe default."
        ),
    )


class SlackConfig(BaseModel):
    """Slack adapter configuration (AD-472 + AD-804).

    AD-472 v1 shipped webhook-only inbound via slack-sdk (opt-in extra).
    AD-804 (Wave 191) adds polling-mode inbound on a thin httpx client
    (no slack-sdk dep required), AD-802a pairing-gate integration, and
    a doctor health check. The polling-mode fields below are additive
    and back-compat with AD-472 webhook deployments.
    """

    enabled: bool = False
    bot_token: str = ""           # xoxb-... (prefer env var PROBOS_SLACK_BOT_TOKEN)
    signing_secret: str = ""      # for events-api verification
    allowed_channel_ids: list[str] = []
    allowed_user_ids: list[str] = []
    default_thread_ts: bool = True
    # AD-804: polling-mode inbound config (no slack-sdk dep required).
    channels: list[str] = []      # explicit channel-id list, empty = auto-discover via conversations.list
    poll_interval_s: float = 8.0  # seconds between conversations.history polls
    poll_inbound: bool = True     # opt-in to polling mode; AD-472 webhook receive() always available
    api_base: str = "https://slack.com/api"  # override only for testing


class SpatialExplorerConfig(BaseModel):
    """AD-520: Spatial Knowledge Explorer (Phase 1 Knowledge Graph View + Phase 2 Spatial Ship Layout).

    Default-False per AD-695 transitional precedent — wirer reads YAML and
    constructs an in-memory layout, not zero-cost on boot. Operator opt-in.
    """

    enabled: bool = False
    max_graph_edges: int = Field(default=500, ge=0, le=5000)
    max_graph_nodes: int = Field(default=200, ge=0, le=2000)
    spatial_layout_path: str = ""  # empty → resolves to config/ontology/spatial.yaml then to _DEFAULT_LAYOUT


class TTSConfig(BaseModel):
    """AD-738 — Server-side TTS backend selection.

    Default: ``browser`` — every ``speakResponse()`` call uses
    ``SpeechSynthesisUtterance`` (today's behaviour, zero regression).
    Operator opts in to ``piper`` by setting ``backend: "piper"`` AND
    placing the binary at ``binary_path`` AND placing the voice model
    files at ``tools/piper/voices/<voice_model>.onnx`` (+ ``.onnx.json``).
    Any failure (binary missing, model missing, subprocess error,
    timeout) returns honest-degrade — the browser falls back to
    SpeechSynthesisUtterance. Speech must NEVER stop because of a TTS
    failure.
    """

    enabled: bool = True
    """Master switch for the server-side TTS pipeline. ``False`` makes
    ``POST /api/avatars/tts`` return ``{"backend": "disabled"}``; the
    browser falls back to SpeechSynthesisUtterance."""

    backend: Literal["browser", "piper"] = "browser"
    """``browser``: server returns ``{"backend": "disabled"}``, browser
    uses SpeechSynthesisUtterance (default — zero behaviour change for
    operators who don't install Piper). ``piper``: subprocess wrapper
    around the piper binary."""

    binary_path: str = "tools/piper/piper"
    """Path (relative to repo root or absolute) to the piper binary.
    On Windows the wrapper auto-appends ``.exe`` if the literal path
    does not exist. Operator places the binary; the repo never ships
    it (gitignored under ``/tools/``)."""

    voice_model: str = "en_US-amy-medium"
    """Voice model name. Operator places ``tools/piper/voices/<name>.onnx``
    AND ``tools/piper/voices/<name>.onnx.json`` (Piper requires both).
    Default ``en_US-amy-medium`` is MIT-licensed (verified on the
    rhasspy/piper-voices model card). Operator who picks a different
    voice is responsible for the license check until AD-738a surfaces
    a license display in the per-agent voice selector."""

    voices_dir: str = "tools/piper/voices"
    """AD-1025: directory holding the Piper voice model files
    (``<voice_model>.onnx`` + ``.onnx.json``). A relative path resolves
    against the ProbOS install root (NOT the process CWD); an absolute path
    is used as-is. Default preserves the historical ``tools/piper/voices``
    location, so existing installs need no change. Operator places the
    files; the repo never ships them (gitignored under ``/tools/``)."""

    timeout_seconds: float = 10.0
    """Subprocess timeout. Piper on a sentence-length input typically
    takes 0.3-1.5s on CPU; default leaves ample headroom for cold
    model load on first call. Tier-2 log-and-degrade on TimeoutExpired —
    endpoint returns honest-degrade, browser falls back."""

    # AD-738e (BF-285 2026-05-13): prosody controls. Piper-VITS exposes
    # three inference knobs plus a sentence-silence gap. Defaults below
    # are tuned for *more* natural variation than Piper's safe-minimum
    # defaults — Captain reported "monotone" + "strange consistent rhythm"
    # on the upstream defaults (noise_scale=0.667, noise_w=0.8,
    # sentence_silence=0.2). Tuning higher trades a touch of clarity for
    # noticeable expressiveness.

    noise_scale: float = 0.85
    """Piper ``--noise_scale``. Generator noise — controls pitch/expression
    variation. Higher = more expressive, less robotic. Piper upstream
    default 0.667. Range 0.0-1.5. At 0 the voice is robotically uniform;
    at 1.5 it starts to wobble unnaturally."""

    length_scale: float = 1.0
    """Piper ``--length_scale``. Phoneme duration multiplier. >1.0 = slower
    speech, <1.0 = faster. Operator-tunable for users who prefer slower
    diction; per-agent AD-735 ``rate`` (browser-side ``playbackRate``)
    still applies on top of this. Piper upstream default 1.0."""

    noise_w: float = 1.0
    """Piper ``--noise_w``. Phoneme-width (duration) variation. Higher =
    more natural rhythm because each phoneme's duration varies. Piper
    upstream default 0.8. Range 0.0-1.5. The Captain's "strange consistent
    rhythm" comment maps directly to this knob — at 0.8 every phoneme is
    the same length; at 1.0+ rhythm breathes."""

    sentence_silence: float = 0.35
    """Piper ``--sentence_silence``. Seconds of silence inserted after
    each sentence boundary. Piper upstream default 0.2. A small bump
    here adds natural pauses for paragraph-style replies. Range 0.0-2.0."""

    sentence_pipelining_enabled: bool = False
    """AD-1071 — Sentence-chunked TTS pipelining (voice edge). Default-OFF.

    When ``True`` AND the backend is ``piper`` AND a reply contains more
    than one sentence, the browser splits the finished reply into
    sentences and synthesizes + plays them SEQUENTIALLY (an ordered
    queue). The first audio then starts after synthesizing only the
    FIRST sentence instead of the whole reply, cutting time-to-first-
    audio. This does NOT stream the LLM reply — the reply is still
    produced in full, then chunked for playback.

    When ``False`` (default) OR the backend is ``browser`` OR the reply
    is a single sentence, the browser issues one TTS call per full reply
    exactly as before (byte-identical). Surfaced by
    ``GET /api/avatars/tts/status`` so the browser can read it via its
    existing one-time status probe."""


class WakeWordConfig(BaseModel):
    """AD-705c (Wave 179) — custom wake-word training pipeline config.

    All fields default-OFF / privacy-preserving per convention #14.
    Operator opts in via system.yaml. The training audio NEVER leaves
    the local runtime; the trainer runs entirely in-process.
    """

    wake_word_trainer_enabled: bool = False
    custom_model_filename: str = "captain.onnx"
    retain_training_samples: bool = False
    training_samples_max_count: int = 200
    training_audio_max_bytes: int = 1_048_576


class WebhookConfig(BaseModel):
    """Webhook adapter configuration (AD-472)."""

    enabled: bool = False
    shared_secret: str = ""       # set via env var PROBOS_WEBHOOK_SECRET
    allowed_channels: list[str] = []


class WorkstationsConfig(BaseModel):
    """AD-1022: HXI workstation-type surface (Experience layer).

    Governs whether the runtime registers the OSS baseline workstation types and
    surfaces ``GET /api/workstations/types`` + the HXI launcher. **Default OFF** —
    when disabled the registry may still be constructed (so an overlay finalize
    hook can register a commercial type into it) but no baseline types are
    registered, the API is dormant (returns an empty list), and the HXI surface
    is hidden ⇒ byte-identical to pre-AD-1022.
    """

    enabled: bool = False
