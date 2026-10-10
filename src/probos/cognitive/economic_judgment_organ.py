"""AD-1322: the opt-in economic judgment organ (orbitofrontal analogue).

A deterministic, synchronous, no-LLM :class:`CognitiveOrgan` that weighs what an
agentic turn is spending against what the work is worth. It is distinct from the
valuation/affect faculties: it reads cost and stakes, not mood.

It is driven only through an explicit **inner-loop hook** (:class:`InnerLoopHook`):
``AgenticLoop`` calls it at each step between model calls. The hook is a per-turn
:class:`EconomicTurnHandle` that the organ opens (:meth:`EconomicJudgmentOrgan.open_turn_hook`):
all per-turn mutable state lives on the handle and is dropped with the turn, so two
overlapping turns of one agent cannot reset, deactivate or leak into each other, and
nothing is locked or serialised. The organ keeps only immutable configuration and a
bounded deque of finished-turn summaries. The spine's per-cycle ``drive_cycle`` leaves
it inert (``perceive`` returns ``None`` for any context that is not its own
:class:`InnerStepContext` carrying a turn), so the existing cycle semantics are
unchanged.

It informs only. Its sole outputs are a compact context block appended to the
outbound system prompt and an audit trace. It never blocks, vetoes, reroutes,
charges tokens, makes a model call, or persists a derived score. Cross-turn memory
is a bounded in-memory deque of raw counts, cleared on detach.

Known limits, stated rather than implied: the prompt-token figure is the loop's
``len // 4`` estimate of the message history (it excludes tool definitions and this
organ's own block) and is input-side only; verification matching is by the exact
name the model called, so a tool whose call name differs from its registry id must
be listed by call name.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import deque
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, runtime_checkable

from probos.cognitive.organ import BaseCognitiveOrgan, OrganAuditEmit
from probos.economic_calibration import (
    CompletionCalibrationSummary,
    render_calibration_evidence,
)

logger = logging.getLogger(__name__)

ECONOMIC_JUDGMENT_ORGAN_NAME = "economic_judgment"

# Mirrors workforce.VALUE_BANDS / STAKES_LEVELS; a drift test keeps them equal.
VALUE_BANDS: tuple[str, ...] = ("minor", "moderate", "significant", "critical")
STAKES_LEVELS: tuple[str, ...] = ("low", "moderate", "high", "severe")
_LOW_VALUE_BANDS = frozenset({"minor", "moderate"})
_HIGH_STAKES = frozenset({"high", "severe"})
# The tiers whose input price forms the relative-weight scale. Vision is not
# comparable (it is not on the fallback chain), so it is left out on purpose.
_PRICED_TIERS: tuple[str, ...] = ("fast", "standard", "deep")
_MAX_SPEND_HISTORY = 64

PHASE_BEFORE_MODEL_CALL = "before_model_call"
PHASE_AFTER_TOOLS = "after_tools"
PHASE_FINISHED = "finished"

SIGNAL_OVERSPEND = "overspend"
SIGNAL_UNDERSPEND = "underspend"
SIGNAL_FINISHED_UNVERIFIED = "finished_unverified"
SIGNAL_VERIFICATION_UNAVAILABLE = "verification_unavailable"

# AD-1323 amendment 3: who set a value or stakes figure, as a closed token (never free text).
VALUE_PROVENANCE_TOKENS: tuple[str, ...] = (
    "captain", "agent_captain_confirmed", "agent_chain_confirmed", "agent_unconfirmed", "unrecorded",
)


def classify_value_provenance(provenance: Any) -> str:
    """Map a work item's recorded provenance mapping onto a closed token. Never raises."""
    try:
        source = provenance.get("source_kind")
        confirmation = provenance.get("confirmation_kind")
        if source == "captain":
            return "captain"
        if source == "agent":
            if confirmation == "captain":
                return "agent_captain_confirmed"
            if confirmation == "chain_of_command":
                return "agent_chain_confirmed"
            return "agent_unconfirmed"
    except Exception:
        return "unrecorded"
    return "unrecorded"


@runtime_checkable
class InnerLoopHook(Protocol):
    """The narrow surface ``AgenticLoop`` drives between model calls (AD-1322)."""

    def open_run(
        self,
        *,
        turn_key: str,
        value_band: str | None,
        stakes: str | None,
        tier: str,
        budget: int | None,
        input_price_per_million: float | None = None,
        price_weight: float | None = None,
        verification_tool_ids: Collection[str] = (),
        value_provenance: str | None = None,
        stakes_provenance: str | None = None,
        completion_calibration: CompletionCalibrationSummary | None = None,
        calibrated_tokens: int | None = None,
        calibration_tolerance_percent: int = 20,
    ) -> None: ...

    def before_model_call(
        self,
        *,
        iteration: int,
        prompt_tokens_estimate: int,
        tier: str,
        cumulative_tokens: int,
    ) -> str | None: ...

    def after_tools(
        self,
        *,
        iteration: int,
        tool_names: Sequence[str],
        results_is_error: Sequence[bool],
        cumulative_tokens: int,
        arguments: Sequence[Mapping[str, Any]] = (),
    ) -> None: ...

    def finished(self, stopped_reason: str) -> None: ...

    def close_run(
        self, stopped_reason: str, final_cumulative_tokens: int | None = None,
    ) -> None: ...


@runtime_checkable
class InnerLoopChargeObserver(Protocol):
    """Optional, synchronous notification of the loop's cumulative charge (AD-1322)."""

    def note_charge(self, cumulative_tokens: int) -> None: ...

@runtime_checkable
class InnerLoopHookSource(Protocol):
    """What the spine resolves by name: something that opens a per-turn hook (AD-1322)."""

    def open_turn_hook(self, *, trust_headroom: float | None = None) -> InnerLoopHook: ...


@dataclass(frozen=True)
class InnerStepContext:
    """What the loop reports at one step; the only context the organ acts on."""

    phase: str
    iteration: int
    cumulative_tokens: int = 0
    prompt_tokens_estimate: int = 0
    tier: str = ""
    tool_names: tuple[str, ...] = ()
    results_is_error: tuple[bool, ...] = ()
    arg_digests: tuple[str, ...] = ()
    stopped_reason: str = ""
    # The owning turn's state (amendment 2); excluded from comparison and repr.
    turn: Any = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class InnerStepObservation:
    """The organ's reading of one step (inputs to :meth:`decide`)."""

    phase: str
    iteration: int
    spend_tokens: int
    spend_history: tuple[int, ...]
    value_band: str | None
    stakes: str | None
    trust_headroom: float | None
    total_budget: int | None
    prompt_tokens_estimate: int
    tier: str
    input_price_per_million: float | None
    price_weight: float | None
    repeat_attempts: int
    verification_recorded: bool
    verification_available: bool
    any_error: bool
    stopped_reason: str
    turn_key: str = ""
    open_run_tier: str = ""
    tier_mismatch: bool = False
    carry_tokens: int = 0
    pass_cumulative_tokens: int = 0
    pass_budget: int | None = None
    completion_calibration: CompletionCalibrationSummary | None = None
    calibrated_tokens: int | None = None
    calibration_tolerance_percent: int = 20
    turn: Any = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class InnerStepDecision:
    """The deterministic signals for one step (input to :meth:`act`)."""

    observation: InnerStepObservation
    signals: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TurnSummary:
    """Raw counts about one finished turn; never a derived score."""

    value_band: str | None
    spend_tokens: int
    signals_raised: tuple[str, ...]
    verified: bool


@dataclass(frozen=True)
class RenderTrace:
    """What :func:`render_block` kept, dropped and which wording it used."""

    kept: tuple[str, ...]
    dropped: tuple[str, ...]
    block_chars: int
    forms_used: tuple[str, ...] = ()


def arguments_digest(arguments: Mapping[str, Any] | None) -> str:
    """A short stable digest of tool arguments; the arguments themselves are never kept."""
    try:
        payload = json.dumps(arguments or {}, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        payload = repr(arguments)
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()[:16]


def resolve_tier_pricing(model_registry: Any, tier: str) -> tuple[float | None, float | None]:
    """Return ``(input price per million, relative weight)`` for ``tier``.

    A tier is priced only when every available descriptor for it agrees on one
    price above zero. The weight is that price over the lowest priced tier's.
    Anything unresolved yields ``(None, None)``: tokens only, no invented number.
    """
    by_tier = getattr(model_registry, "by_tier", None)
    if not callable(by_tier):
        return None, None
    prices: dict[str, float] = {}
    for name in _PRICED_TIERS:
        try:
            descriptors = [d for d in by_tier(name) if getattr(d, "available", True)]
        except Exception:
            logger.warning(
                "AD-1322: model registry could not list tier %s; its price is "
                "treated as unknown and costs show tokens only for it",
                name, exc_info=True,
            )
            continue
        values = {getattr(d, "cost_per_million_input_tokens", 0.0) for d in descriptors}
        if len(values) != 1:
            continue
        value = next(iter(values))
        if type(value) in (int, float) and value > 0:
            prices[name] = float(value)
    price = prices.get(tier)
    if price is None:
        return None, None
    return price, price / min(prices.values())


def _as_int(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


# Floor on the block cap: the three compact actionable messages, at their longest, plus
# their separators fit whole (asserted from these constants in tests), so no combination
# of actionable messages is ever cut. Wording must not match the capability-gap regex.
BLOCK_MAX_CHARS_FLOOR = 160
_REPEAT_FULL = (
    "The same call has failed repeatedly with the same arguments; "
    "change the approach instead of repeating it."
)
_REPEAT_COMPACT = "Same call keeps failing; change approach."
_SPEND_FULL = (
    "Spend is high for the value of this work; prefer the cheapest step that settles it."
)
_SPEND_COMPACT = "Spend high for this value; take the cheapest step."
_VERIFY_FULL = (
    "Stakes are {stakes} and no verification step has succeeded yet; "
    "verify the result before you finish."
)
_VERIFY_COMPACT = "Stakes {stakes}; verify before finishing."
_ACTIONABLE_DISPLAY_ORDER = ("repeat", "spend", "verify")
# Stable marker every block starts with; it counts against the cap and the floor.
ECONOMIC_NOTE_PREFIX = "Economic note: "


def compact_actionable_worst_case() -> int:
    """Longest joined length of all three compact actionable messages."""
    longest_stakes = max(STAKES_LEVELS, key=len)
    return (
        len(ECONOMIC_NOTE_PREFIX)
        + len(_REPEAT_COMPACT)
        + len(_SPEND_COMPACT)
        + len(_VERIFY_COMPACT.format(stakes=longest_stakes))
        + 2
    )


def render_block(
    observation: InnerStepObservation,
    signals: Collection[str],
    reasons: Collection[str],
    *,
    block_max_chars: int,
    currency_is_marginal: bool,
) -> tuple[str, RenderTrace]:
    """Render the context block; pure, structural and never sliced (AD-1322).

    Actionable messages come first and are always present (full form when it fits,
    else compact; the cap floor guarantees every compact form fits). Descriptive
    segments follow and are dropped whole, by priority, when they do not fit.
    """
    cap = max(BLOCK_MAX_CHARS_FLOOR, int(block_max_chars)) - len(ECONOMIC_NOTE_PREFIX)
    stakes = str(observation.stakes or "")
    # (id, full, compact) in priority order for choosing the full form.
    actionable: list[tuple[str, str, str]] = []
    if SIGNAL_UNDERSPEND in signals:
        actionable.append(
            ("verify", _VERIFY_FULL.format(stakes=stakes), _VERIFY_COMPACT.format(stakes=stakes))
        )
    if SIGNAL_OVERSPEND in signals:
        if "repeated_failed_attempts" in reasons:
            actionable.append(("repeat", _REPEAT_FULL, _REPEAT_COMPACT))
        if any(r.endswith("_low_value") for r in reasons):
            actionable.append(("spend", _SPEND_FULL, _SPEND_COMPACT))
    separators = max(len(actionable) - 1, 0)
    chosen: dict[str, tuple[str, str]] = {}
    used = 0
    for index, (segment_id, full, compact) in enumerate(actionable):
        reserved = sum(len(c) for _, _, c in actionable[index + 1:])
        if used + len(full) + reserved + separators <= cap:
            chosen[segment_id] = (full, "full")
        else:
            chosen[segment_id] = (compact, "compact")
        used += len(chosen[segment_id][0])
    parts: list[str] = []
    kept: list[str] = []
    forms: list[str] = []
    for segment_id in _ACTIONABLE_DISPLAY_ORDER:
        if segment_id in chosen:
            text, form = chosen[segment_id]
            parts.append(text)
            kept.append(segment_id)
            forms.append(f"{segment_id}:{form}")
    length = len(" ".join(parts))
    dropped: list[str] = []

    def _append(segment_id: str, *candidates: tuple[str, str]) -> None:
        nonlocal length
        for text, form in candidates:
            extra = len(text) + (1 if parts else 0)
            if length + extra <= cap:
                parts.append(text)
                length += extra
                kept.append(segment_id)
                forms.append(f"{segment_id}:{form}")
                return
        dropped.append(segment_id)

    prompt = observation.prompt_tokens_estimate
    _append(
        "spend_tokens",
        (
            f"Request ~{prompt:,} prompt tokens (tool definitions and this note "
            f"excluded); turn spent {observation.spend_tokens:,} tokens.",
            "full",
        ),
        (f"About {prompt:,} prompt tokens; {observation.spend_tokens:,} spent.", "compact"),
    )
    if observation.price_weight is not None and observation.tier:
        _append(
            "weight",
            (
                f"{observation.tier} tier input price is "
                f"{observation.price_weight:.1f}x the cheapest tier.",
                "full",
            ),
        )
    price = observation.input_price_per_million
    if currency_is_marginal and price is not None and price > 0:
        cost = prompt * price / 1_000_000
        _append("currency", (f"Input cost about ${cost:.4f}.", "full"))
    if type(observation.completion_calibration) is CompletionCalibrationSummary:
        try:
            calibration_text = render_calibration_evidence(
                observation.completion_calibration,
                tolerance_percent=observation.calibration_tolerance_percent,
                calibrated_tokens=observation.calibrated_tokens,
            )
        except Exception:
            calibration_text = ""
        if calibration_text:
            _append("completion_calibration", (calibration_text, "full"))
    block = ECONOMIC_NOTE_PREFIX + " ".join(parts)
    return block, RenderTrace(
        kept=tuple(kept), dropped=tuple(dropped), block_chars=len(block),
        forms_used=tuple(forms),
    )


@dataclass
class _TurnState:
    """Every mutable per-turn field; owned by exactly one :class:`EconomicTurnHandle`."""

    effective_verification: frozenset[str]
    trust_headroom: float | None = None
    turn_key: str | None = None
    active: bool = False
    value_band: str | None = None
    stakes: str | None = None
    value_provenance: str = "unrecorded"
    stakes_provenance: str = "unrecorded"
    tier: str = ""
    pass_budget: int | None = None
    input_price: float | None = None
    price_weight: float | None = None
    completion_calibration: CompletionCalibrationSummary | None = None
    calibrated_tokens: int | None = None
    calibration_tolerance_percent: int = 20
    carry: int = 0
    pass_cumulative: int = 0
    spend_history: deque[int] = field(default_factory=lambda: deque(maxlen=_MAX_SPEND_HISTORY))
    last_failed_key: tuple[str, str] | None = None
    repeat_count: int = 0
    verification_recorded: bool = False
    signals: list[str] = field(default_factory=list)
    last_stopped_reason: str = ""
    publish_token: object = field(default_factory=object)

    def fold_pass(self) -> None:
        if self.active:
            self.carry += self.pass_cumulative
            self.pass_cumulative = 0
            self.active = False


class EconomicJudgmentOrgan(BaseCognitiveOrgan):
    """Weighs spend against value and stakes at each inner-loop step (AD-1322)."""

    default_name: ClassVar[str] = ECONOMIC_JUDGMENT_ORGAN_NAME

    def __init__(
        self,
        *,
        summary_turns: int = 3,
        block_max_chars: int = 400,
        overspend_spend_fraction: float = 0.5,
        repeat_attempt_threshold: int = 3,
        rising_spend_steps: int = 2,
        verification_tool_ids: Collection[str] = (),
        currency_is_marginal: bool = False,
        name: str | None = None,
        emit: OrganAuditEmit | None = None,
    ) -> None:
        super().__init__(name=name, emit=emit)
        self._block_max_chars = max(BLOCK_MAX_CHARS_FLOOR, int(block_max_chars))
        self._overspend_fraction = overspend_spend_fraction
        self._repeat_threshold = repeat_attempt_threshold
        self._rising_steps = rising_spend_steps
        self._configured_verification = frozenset(verification_tool_ids)
        self._currency_is_marginal = currency_is_marginal
        # (publish token, summary) pairs; append/replace-only and bounded, so it needs no
        # lock (the hook runs synchronously between awaits). A turn whose entry the bound
        # evicted is re-appended on its next close: an accepted bounded-memory limit.
        self._summaries: deque[tuple[object, TurnSummary]] = deque(
            maxlen=max(1, summary_turns)
        )

    # -- introspection ---------------------------------------------------

    @property
    def turn_summaries(self) -> tuple[TurnSummary, ...]:
        """The bounded cross-turn raw-count summaries, oldest first."""
        return tuple(summary for _, summary in self._summaries)

    @property
    def block_max_chars(self) -> int:
        return self._block_max_chars

    @property
    def currency_is_marginal(self) -> bool:
        return self._currency_is_marginal

    @property
    def configured_verification_ids(self) -> frozenset[str]:
        return self._configured_verification

    def on_detach(self) -> None:
        # Handles check ``attached`` on every call, so this alone makes them inert.
        self._summaries.clear()

    # -- per-turn hook ---------------------------------------------------

    def open_turn_hook(self, *, trust_headroom: float | None = None) -> InnerLoopHook:
        """Open a NEW turn-bound hook handle; never caches or reuses a prior one."""
        headroom = (
            float(trust_headroom)
            if type(trust_headroom) in (int, float) and math.isfinite(trust_headroom)
            else None
        )
        return EconomicTurnHandle(self, trust_headroom=headroom)

    def publish_turn_summary(self, token: object, summary: TurnSummary) -> None:
        """Upsert one turn's summary under its handle's opaque token (no-op once detached)."""
        if not self.attached:
            return
        for index, (existing, _) in enumerate(self._summaries):
            if existing is token:
                self._summaries[index] = (token, summary)
                return
        self._summaries.append((token, summary))

    # -- cognitive cycle (own typed context only) ------------------------

    def perceive(self, context: Any) -> InnerStepObservation | None:
        if type(context) is not InnerStepContext:
            return None
        turn = context.turn
        if type(turn) is not _TurnState:
            return None
        if context.phase in (PHASE_BEFORE_MODEL_CALL, PHASE_AFTER_TOOLS):
            turn.pass_cumulative = _as_int(context.cumulative_tokens)
        any_error = False
        if context.phase == PHASE_AFTER_TOOLS:
            turn.spend_history.append(turn.carry + turn.pass_cumulative)
            any_error = self._fold_tool_results(turn, context)
        if context.phase == PHASE_FINISHED:
            turn.last_stopped_reason = context.stopped_reason
        total_budget = turn.carry + turn.pass_budget if turn.pass_budget is not None else None
        # The request's own tier is authoritative; a differing price tier is unknown.
        mismatch = bool(context.tier) and bool(turn.tier) and context.tier != turn.tier
        return InnerStepObservation(
            phase=context.phase,
            iteration=context.iteration,
            spend_tokens=turn.carry + turn.pass_cumulative,
            spend_history=tuple(turn.spend_history),
            value_band=turn.value_band,
            stakes=turn.stakes,
            trust_headroom=turn.trust_headroom,
            total_budget=total_budget,
            prompt_tokens_estimate=_as_int(context.prompt_tokens_estimate),
            tier=context.tier or turn.tier,
            input_price_per_million=None if mismatch else turn.input_price,
            price_weight=None if mismatch else turn.price_weight,
            repeat_attempts=turn.repeat_count,
            verification_recorded=turn.verification_recorded,
            verification_available=bool(turn.effective_verification),
            any_error=any_error,
            stopped_reason=context.stopped_reason,
            turn_key=turn.turn_key or "",
            open_run_tier=turn.tier,
            tier_mismatch=mismatch,
            carry_tokens=turn.carry,
            pass_cumulative_tokens=turn.pass_cumulative,
            pass_budget=turn.pass_budget,
            completion_calibration=turn.completion_calibration,
            calibrated_tokens=turn.calibrated_tokens,
            calibration_tolerance_percent=turn.calibration_tolerance_percent,
            turn=turn,
        )

    @staticmethod
    def _fold_tool_results(turn: _TurnState, context: InnerStepContext) -> bool:
        any_error = False
        for index, name in enumerate(context.tool_names):
            is_error = (
                context.results_is_error[index]
                if index < len(context.results_is_error)
                else False
            )
            digest = context.arg_digests[index] if index < len(context.arg_digests) else ""
            if is_error:
                any_error = True
                key = (name, digest)
                turn.repeat_count = turn.repeat_count + 1 if key == turn.last_failed_key else 1
                turn.last_failed_key = key
            else:
                turn.last_failed_key = None
                turn.repeat_count = 0
                if name in turn.effective_verification:
                    turn.verification_recorded = True
        return any_error

    def decide(self, observation: Any) -> InnerStepDecision | None:
        if type(observation) is not InnerStepObservation:
            return None
        signals: list[str] = []
        reasons: list[str] = []
        if observation.phase == PHASE_AFTER_TOOLS or observation.phase == PHASE_BEFORE_MODEL_CALL:
            if observation.repeat_attempts >= self._repeat_threshold:
                reasons.append("repeated_failed_attempts")
            if observation.value_band in _LOW_VALUE_BANDS:
                if (
                    observation.total_budget is not None
                    and observation.spend_tokens
                    >= self._overspend_fraction * observation.total_budget
                ):
                    reasons.append("high_spend_low_value")
                elif self._is_rising(observation):
                    reasons.append("rising_spend_low_value")
            if reasons:
                signals.append(SIGNAL_OVERSPEND)
        if observation.stakes in _HIGH_STAKES and not observation.verification_recorded:
            if not observation.verification_available:
                if observation.phase != PHASE_AFTER_TOOLS:
                    signals.append(SIGNAL_VERIFICATION_UNAVAILABLE)
            elif observation.phase == PHASE_BEFORE_MODEL_CALL:
                signals.append(SIGNAL_UNDERSPEND)
            elif observation.phase == PHASE_FINISHED:
                signals.append(SIGNAL_FINISHED_UNVERIFIED)
        return InnerStepDecision(
            observation=observation, signals=tuple(signals), reasons=tuple(reasons)
        )

    def _is_rising(self, observation: InnerStepObservation) -> bool:
        history = (0,) + observation.spend_history
        deltas = [b - a for a, b in zip(history, history[1:])]
        window = deltas[-self._rising_steps :]
        if len(window) < self._rising_steps:
            return False
        return all(d > 0 for d in window) and all(
            later > earlier for earlier, later in zip(window, window[1:])
        )

    def act(self, decision: Any) -> str | None:
        if type(decision) is not InnerStepDecision:
            return None
        obs = decision.observation
        turn = obs.turn
        if type(turn) is not _TurnState:
            return None
        for signal in decision.signals:
            if signal not in turn.signals:
                turn.signals.append(signal)
        block: str | None = None
        rendering: dict[str, Any] | None = None
        if obs.phase == PHASE_BEFORE_MODEL_CALL:
            block, trace = render_block(
                obs,
                decision.signals,
                decision.reasons,
                block_max_chars=self._block_max_chars,
                currency_is_marginal=self._currency_is_marginal,
            )
            rendering = {
                "kept": list(trace.kept),
                "dropped": list(trace.dropped),
                "block_chars": trace.block_chars,
                "forms_used": list(trace.forms_used),
            }
        self._emit_audit_trace(
            obs.phase,
            {
                "inputs": {
                    "phase": obs.phase,
                    "iteration": obs.iteration,
                    "turn_key": obs.turn_key,
                    "tier": obs.tier,
                    "open_run_tier": obs.open_run_tier,
                    "tier_mismatch": obs.tier_mismatch,
                    "input_price_per_million": obs.input_price_per_million,
                    "price_weight": obs.price_weight,
                    "currency_is_marginal": self._currency_is_marginal,
                    "block_max_chars": self._block_max_chars,
                    "prompt_tokens_estimate": obs.prompt_tokens_estimate,
                    "spend_tokens": obs.spend_tokens,
                    "carry_tokens": obs.carry_tokens,
                    "pass_cumulative_tokens": obs.pass_cumulative_tokens,
                    "spend_history": list(obs.spend_history),
                    "total_budget": obs.total_budget,
                    "pass_budget": obs.pass_budget,
                    "trust_headroom": obs.trust_headroom,
                    "value_band": obs.value_band,
                    "stakes": obs.stakes,
                    "repeat_attempts": obs.repeat_attempts,
                    "verification_recorded": obs.verification_recorded,
                    "verification_available": obs.verification_available,
                    "thresholds": {
                        "overspend_spend_fraction": self._overspend_fraction,
                        "repeat_attempt_threshold": self._repeat_threshold,
                        "rising_spend_steps": self._rising_steps,
                    },
                    "rendering": rendering,
                    "stopped_reason": obs.stopped_reason,
                },
                "signals": list(decision.signals),
                "reasons": list(decision.reasons),
            },
        )
        return block


@dataclass(frozen=True)
class CostedCase:
    """AD-1323: what a stopped turn has spent and what it is worth. Counts and enum tokens only."""

    spent: int
    budget: int | None
    value_band: str | None
    stakes: str | None
    verified: bool
    signals: tuple[str, ...]
    recent_step_deltas: tuple[int, ...]
    value_provenance: str = "unrecorded"
    stakes_provenance: str = "unrecorded"


class EconomicTurnHandle:
    """One turn's inner-loop hook: owns ALL per-turn state, dropped with the turn (AD-1322).

    Created only by :meth:`EconomicJudgmentOrgan.open_turn_hook`. It shares nothing
    mutable with other handles; its only writes outside itself are upserts of its own
    :class:`TurnSummary` into the organ's bounded deque. Every call first checks that
    the organ is still attached, so a detach makes the handle inert.
    """

    def __init__(
        self, organ: EconomicJudgmentOrgan, *, trust_headroom: float | None = None,
    ) -> None:
        self._organ = organ
        self._state = _TurnState(
            effective_verification=organ.configured_verification_ids,
            trust_headroom=trust_headroom,
        )

    def open_run(
        self,
        *,
        turn_key: str,
        value_band: str | None,
        stakes: str | None,
        tier: str,
        budget: int | None,
        input_price_per_million: float | None = None,
        price_weight: float | None = None,
        verification_tool_ids: Collection[str] = (),
        value_provenance: str | None = None,
        stakes_provenance: str | None = None,
        completion_calibration: CompletionCalibrationSummary | None = None,
        calibrated_tokens: int | None = None,
        calibration_tolerance_percent: int = 20,
    ) -> None:
        if not self._organ.attached:
            return
        state = self._state
        if state.turn_key is None:
            state.turn_key = turn_key or "<unkeyed>"
        elif turn_key and turn_key != state.turn_key:
            # Reuse of a handle for a different turn: publish this one, reset only here.
            state.fold_pass()
            self._publish()
            self._state = state = _TurnState(
                effective_verification=self._organ.configured_verification_ids,
                trust_headroom=state.trust_headroom,
                turn_key=turn_key,
            )
        else:
            state.fold_pass()
        state.active = True
        state.pass_cumulative = 0
        state.value_band = value_band if value_band in VALUE_BANDS else None
        state.stakes = stakes if stakes in STAKES_LEVELS else None
        state.value_provenance = value_provenance if value_provenance in VALUE_PROVENANCE_TOKENS else "unrecorded"
        state.stakes_provenance = stakes_provenance if stakes_provenance in VALUE_PROVENANCE_TOKENS else "unrecorded"
        state.pass_budget = budget if type(budget) is int and budget > 0 else None
        state.tier = str(tier or "")
        state.input_price = input_price_per_million
        state.price_weight = price_weight
        state.completion_calibration = (
            completion_calibration
            if type(completion_calibration) is CompletionCalibrationSummary
            else None
        )
        state.calibrated_tokens = (
            calibrated_tokens
            if type(calibrated_tokens) is int and calibrated_tokens > 0
            else None
        )
        state.calibration_tolerance_percent = (
            calibration_tolerance_percent
            if type(calibration_tolerance_percent) is int
            and 0 <= calibration_tolerance_percent <= 100
            else 20
        )
        state.effective_verification = self._organ.configured_verification_ids | frozenset(
            verification_tool_ids
        )

    def before_model_call(
        self,
        *,
        iteration: int,
        prompt_tokens_estimate: int,
        tier: str,
        cumulative_tokens: int,
    ) -> str | None:
        return self._drive(
            InnerStepContext(
                phase=PHASE_BEFORE_MODEL_CALL,
                iteration=iteration,
                cumulative_tokens=cumulative_tokens,
                prompt_tokens_estimate=prompt_tokens_estimate,
                tier=tier,
                turn=self._state,
            )
        )

    def after_tools(
        self,
        *,
        iteration: int,
        tool_names: Sequence[str],
        results_is_error: Sequence[bool],
        cumulative_tokens: int,
        arguments: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        digests = tuple(arguments_digest(a) for a in arguments)
        self._drive(
            InnerStepContext(
                phase=PHASE_AFTER_TOOLS,
                iteration=iteration,
                cumulative_tokens=cumulative_tokens,
                tool_names=tuple(str(n) for n in tool_names),
                results_is_error=tuple(bool(e) for e in results_is_error),
                arg_digests=digests,
                turn=self._state,
            )
        )

    def finished(self, stopped_reason: str) -> None:
        self._drive(
            InnerStepContext(
                phase=PHASE_FINISHED,
                iteration=0,
                stopped_reason=str(stopped_reason or ""),
                turn=self._state,
            )
        )

    def close_run(
        self, stopped_reason: str, final_cumulative_tokens: int | None = None,
    ) -> None:
        state = self._state
        if not self._organ.attached or not state.active:
            return
        state.last_stopped_reason = str(stopped_reason or "")
        # The loop's final charge is authoritative: it REPLACES the last live reading.
        if type(final_cumulative_tokens) is int and final_cumulative_tokens >= 0:
            state.pass_cumulative = final_cumulative_tokens
        state.fold_pass()
        self._publish()

    def note_charge(self, cumulative_tokens: int) -> None:
        """Record the loop's last charged cumulative figure; passive, folded only on close."""
        state = self._state
        if not self._organ.attached or not state.active:
            return
        if type(cumulative_tokens) is not int or cumulative_tokens < 0:
            return
        state.pass_cumulative = max(state.pass_cumulative, cumulative_tokens)

    def costed_case(self) -> CostedCase:
        """AD-1323: a read-only snapshot of what this turn has spent against what it is worth.

        Pure counts and enum tokens, taken from state the organ already holds; it
        never raises and changes nothing.
        """
        state = self._state
        history = list(state.spend_history)
        deltas = tuple(
            b - a for a, b in zip([0] + history[:-1], history) if type(a) is int and b >= a
        )
        return CostedCase(
            spent=state.carry + state.pass_cumulative,
            budget=state.pass_budget,
            value_band=state.value_band,
            stakes=state.stakes,
            verified=state.verification_recorded,
            signals=tuple(state.signals),
            recent_step_deltas=deltas[-3:],
            value_provenance=state.value_provenance,
            stakes_provenance=state.stakes_provenance,
        )

    def _publish(self) -> None:
        state = self._state
        if state.turn_key is None:
            return
        self._organ.publish_turn_summary(
            state.publish_token,
            TurnSummary(
                value_band=state.value_band,
                spend_tokens=state.carry,
                signals_raised=tuple(state.signals),
                verified=state.last_stopped_reason == "complete"
                and state.verification_recorded,
            ),
        )

    def _drive(self, context: InnerStepContext) -> str | None:
        organ = self._organ
        if not organ.attached or not self._state.active:
            return None
        return organ.act(organ.decide(organ.perceive(context)))
