"""AD-1324: agent-chosen model tier per step, under a deterministic stakes floor.

The model STATES the tier of its next step (a one-line directive on its own reply);
this module validates and enforces limits, and never chooses among valid tiers. The
only tier code ever picks is the stakes floor, and only on a floor-bound step (a
decision or verification step), by raising -- never by lowering. There is no
automatic cascade, no extra model call and no classifier.

Pure: no I/O, no runtime, no client. The loop owns the wiring.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from probos.cognitive.llm_client import TEXT_TIERS

logger = logging.getLogger(__name__)

TIER_RANK: dict[str, int] = {tier: rank for rank, tier in enumerate(TEXT_TIERS)}
REASON_TOKENS: frozenset[str] = frozenset(
    {"hard_step", "verification_needed", "prior_error", "easy_step", "wrap_up"}
)
# Tiers the router never governs; a directive naming one is rejected, never routed.
SPECIAL_TIERS: frozenset[str] = frozenset({"vision", "vision_fast", "compute_use", "image_gen"})
DIRECTIVE_PREFIX = "@@next_tier"
MAX_DIRECTIVE_CHARS = 160
# Organ signals that count as deterministic evidence of difficulty. Overspend and
# verification_unavailable are cost/availability facts, not difficulty.
EVIDENCE_SIGNALS: frozenset[str] = frozenset({"underspend", "finished_unverified"})
LONG_CONTEXT_THRESHOLD = 100_000
_ALLOWED_KEYS = frozenset({"tier", "reason"})


@dataclass(frozen=True)
class TierDirective:
    tier: str
    reason: str


@dataclass(frozen=True)
class DirectiveParse:
    status: str  # "absent" | "valid" | "invalid"
    directive: TierDirective | None = None
    detail: str = ""


_ABSENT = DirectiveParse("absent")


def _directive_lines(text: str) -> tuple[str, list[str]]:
    """``text`` with every directive line removed, and the removed lines (in order)."""
    kept: list[str] = []
    found: list[str] = []
    for line in text.split("\n"):
        if line.strip().startswith(DIRECTIVE_PREFIX):
            found.append(line.strip())
        else:
            kept.append(line)
    return "\n".join(kept).rstrip(), found


def _parse_line(line: str) -> DirectiveParse:
    if len(line) > MAX_DIRECTIVE_CHARS:
        return DirectiveParse("invalid", detail="too_long")
    body = line[len(DIRECTIVE_PREFIX):]
    if body and not body[0].isspace():
        return DirectiveParse("invalid", detail="malformed")
    try:
        data = json.loads(body)
    except ValueError:
        return DirectiveParse("invalid", detail="malformed")
    if type(data) is not dict or set(data) != _ALLOWED_KEYS:
        return DirectiveParse("invalid", detail="bad_keys")
    tier, reason = data["tier"], data["reason"]
    if type(tier) is not str or type(reason) is not str:
        return DirectiveParse("invalid", detail="bad_types")
    if tier in SPECIAL_TIERS:
        return DirectiveParse("invalid", detail="special_tier")
    if tier not in TIER_RANK:
        return DirectiveParse("invalid", detail="unknown_tier")
    if reason not in REASON_TOKENS:
        return DirectiveParse("invalid", detail="bad_reason")
    return DirectiveParse("valid", TierDirective(tier, reason))


def split_directive(response: Any) -> tuple[Any, DirectiveParse]:
    """Strip every directive line from ``response`` and parse the one that counts.

    Returns ``(cleaned, parse)``. ``cleaned`` is a copy; the original is untouched.
    A directive counts only as the single last non-empty line of the model's text;
    a duplicate, a misplaced or a malformed one is stripped and reported invalid,
    so no directive ever reaches a user, history, budget-stop text or a block.
    """
    content = getattr(response, "content", None)
    blocks = list(getattr(response, "content_blocks", None) or [])
    texts: list[str] = [content] if type(content) is str else []
    texts += [b.text for b in blocks if getattr(b, "kind", "") == "text" and type(getattr(b, "text", None)) is str]
    if not any(DIRECTIVE_PREFIX in t for t in texts):
        return response, _ABSENT

    found: list[str] = []
    last_is_directive = False
    cleaned_content = content
    if type(content) is str:
        cleaned_content, lines = _directive_lines(content)
        found += lines
        non_empty = [ln for ln in content.split("\n") if ln.strip()]
        last_is_directive = bool(lines) and bool(non_empty) and non_empty[-1].strip() == lines[-1]
    new_blocks: list[Any] = []
    for block in blocks:
        text = getattr(block, "text", None)
        if getattr(block, "kind", "") == "text" and type(text) is str and DIRECTIVE_PREFIX in text:
            cleaned_text, lines = _directive_lines(text)
            if type(content) is not str or not content.strip():
                found += lines
                non_empty = [ln for ln in text.split("\n") if ln.strip()]
                last_is_directive = bool(lines) and bool(non_empty) and non_empty[-1].strip() == lines[-1]
            new_blocks.append(dataclasses.replace(block, text=cleaned_text))
        else:
            new_blocks.append(block)
    if not found:
        return response, _ABSENT
    changes: dict[str, Any] = {}
    if type(content) is str:
        changes["content"] = cleaned_content
    if blocks:
        changes["content_blocks"] = new_blocks
    if dataclasses.is_dataclass(response):
        cleaned = dataclasses.replace(response, **changes)
    else:
        cleaned = copy.copy(response)
        for name, value in changes.items():
            setattr(cleaned, name, value)
    if len(found) > 1:
        return cleaned, DirectiveParse("invalid", detail="duplicate")
    if not last_is_directive:
        return cleaned, DirectiveParse("invalid", detail="not_last_line")
    return cleaned, _parse_line(found[0])


def stakes_floor_tier(stakes: object, floor_map: Mapping[str, str]) -> str | None:
    """The configured floor for ``stakes``, or None (no floor / unknown level)."""
    if type(stakes) is not str:
        return None
    tier = floor_map.get(stakes)
    return tier if type(tier) is str and tier in TIER_RANK else None


def is_floor_bound_step(
    *,
    first_step: bool,
    prev_non_tier1: bool,
    prev_verification: bool,
    prev_error: bool,
) -> bool:
    """A step that decides, verifies or recovers is held at the floor; pure observation is not."""
    return first_step or prev_non_tier1 or prev_verification or prev_error


def _max_tier(a: str, b: str) -> str:
    return a if TIER_RANK[a] >= TIER_RANK[b] else b


@dataclass(frozen=True)
class TierDecision:
    tier: str
    reason: str | None
    floor: str | None
    floor_bound: bool
    outcome: str  # call_site | agent_choice | floor_raise | floor_redo
    requested: str
    evidence: str | None = None


@dataclass(frozen=True)
class EligibilityVerdict:
    """Whether the exact tier can take the request; ``cause`` is a closed token: "ceiling", "ineligible" or None."""

    eligible: bool
    cause: str | None = None


class TierEligibility(Protocol):
    def assess(self, tier: str, *, prompt_tokens: int, reserved_output: int) -> EligibilityVerdict: ...


class RouterEligibility:
    """Whether the EXACT tier has an available model that fits the ceiling and the context.

    ``prompt_tokens + reserved_output`` must fit the model's window (unknown window: no bound), and a
    prompt over ``LONG_CONTEXT_THRESHOLD`` needs the long-context capability when capabilities are known.
    """

    def __init__(self, router: Any) -> None:
        self._router = router

    def assess(self, tier: str, *, prompt_tokens: int, reserved_output: int) -> EligibilityVerdict:
        refused = EligibilityVerdict(False, "ineligible")
        try:
            decision = self._router.preview(tier=tier, exact_tier=True)
            # A ceiling exclusion returns no chosen model, so it must be read before that check.
            if decision.excluded_by_cost_ceiling is True:
                return EligibilityVerdict(False, "ceiling")
            if not decision.chosen_model:
                return refused
            if getattr(decision, "excluded_exact", False) is True:
                return refused
            if decision.chosen_tier and decision.chosen_tier != tier:
                return refused
            descriptor = self._router.registry.get(decision.chosen_model)
        except Exception:
            logger.warning("AD-1324: eligibility check for tier %s failed; treating it as ineligible", tier, exc_info=True)
            return refused
        if descriptor is None:
            return EligibilityVerdict(True)
        window = descriptor.context_window_tokens
        if window and prompt_tokens + reserved_output > window:
            return refused
        if prompt_tokens > LONG_CONTEXT_THRESHOLD and descriptor.capabilities:
            if any(getattr(c, "value", c) == "long_context" for c in descriptor.capabilities):
                return EligibilityVerdict(True)
            return refused
        return EligibilityVerdict(True)

class StepLedger:
    """What the previous step's tools did: the facts that make the next step floor-bound."""

    def __init__(self, verification_ids: Collection[str]) -> None:
        self._verification = frozenset(verification_ids)
        self.non_tier1 = False
        self.verification = False
        self.error = False
        self.verification_failed = False

    def record(self, tool_names: Sequence[str], all_tier1: bool, results_is_error: Sequence[bool]) -> None:
        self.non_tier1 = not all_tier1
        verified = [n in self._verification for n in tool_names]
        self.verification = any(verified)
        self.error = any(results_is_error)
        self.verification_failed = any(v and bool(e) for v, e in zip(verified, results_is_error))

    def is_verification(self, tool_name: str) -> bool:
        return tool_name in self._verification

    def floor_bound(self, *, first_step: bool) -> bool:
        return is_floor_bound_step(
            first_step=first_step, prev_non_tier1=self.non_tier1,
            prev_verification=self.verification, prev_error=self.error,
        )


class TierChoiceController:
    """Per-run state machine: sticky agent tier, floor enforcement, bounded upward moves."""

    def __init__(
        self,
        *,
        call_site_tier: str,
        stakes_floor: Mapping[str, str],
        max_upward_moves: int,
        eligibility: TierEligibility,
        case_provider: Callable[[], Any],
        verification_ids: Collection[str] = (),
        audit: Callable[[dict[str, Any]], None] | None = None,
        agent_id: str = "",
        work_item_id: Callable[[], str | None] | None = None,
        audit_drain: Callable[[], Awaitable[None]] | None = None,
        audit_sink: Any = None,
    ) -> None:
        # The run's audit sink (None = decisions are logged only); the loop reads it to record terminals.
        self.audit_sink = audit_sink
        self._call_site = call_site_tier if call_site_tier in TIER_RANK else "deep"
        self._floor_map = dict(stakes_floor)
        self._max_up = max_upward_moves
        self._eligibility = eligibility
        self._case_provider = case_provider
        self._verification = frozenset(verification_ids)
        self._audit = audit
        self._audit_drain = audit_drain
        self._agent_id = agent_id
        self._work_item_id = work_item_id
        self._agent_tier = self._call_site
        self._up_moves = 0
        self._step = 0
        self._ledger = StepLedger(verification_ids)
        self._last_stakes: str | None = None
        self._last_floor: str | None = None
        self._counts: dict[str, int] = {}
        self._accepted_reason: str | None = None
        self._accepted_evidence: str | None = None

    # -- reading -------------------------------------------------------------
    def _read_case(self) -> tuple[str | None, frozenset[str]]:
        case = self._case_provider()
        stakes = getattr(case, "stakes", None)
        signals = getattr(case, "signals", ()) or ()
        self._last_stakes = stakes if type(stakes) is str else None
        return self._last_stakes, frozenset(s for s in signals if type(s) is str)

    @property
    def work_item_id(self) -> str | None:
        if self._work_item_id is None:
            return None
        try:
            value = self._work_item_id()
        except Exception:
            return None
        return value if type(value) is str and value else None

    @property
    def last_floor(self) -> str | None:
        """The floor read at the most recent step (None: no floor applied)."""
        return self._last_floor

    @property
    def steps(self) -> int:
        """Model steps this controller has decided."""
        return self._step

    @property
    def eligibility(self) -> TierEligibility:
        """The admission check the loop applies to every dispatch."""
        return self._eligibility

    # -- the step ------------------------------------------------------------
    def next_request_tier(self) -> TierDecision:
        stakes, _signals = self._read_case()
        floor = stakes_floor_tier(stakes, self._floor_map)
        self._last_floor = floor
        floor_bound = self._ledger.floor_bound(first_step=self._step == 0)
        base = self._agent_tier
        if floor is not None and floor_bound and TIER_RANK[floor] > TIER_RANK[base]:
            decision = TierDecision(floor, None, floor, floor_bound, "floor_raise", base, None)
        else:
            outcome = (
                "call_site"
                if base == self._call_site and self._up_moves == 0
                else "agent_choice"
            )
            decision = TierDecision(
                base,
                self._accepted_reason,
                floor,
                floor_bound,
                outcome,
                base,
                self._accepted_evidence,
            )
            if self._accepted_reason is not None:
                self._accepted_reason = None
                self._accepted_evidence = None
        self._step += 1
        self._record(decision.outcome, requested=decision.requested, effective=decision.tier, floor=decision.floor)
        return decision

    def guard_response(self, decision: TierDecision, *, tool_names: Sequence[str], all_tier1: bool) -> TierDecision | None:
        """A re-issue decision at the floor when a sub-floor observation step decided or answered.

        Returns None when the response stands. ``tool_names`` empty means a final answer.
        """
        if decision.floor is None or decision.floor_bound or decision.outcome == "floor_redo":
            return None
        if TIER_RANK[decision.tier] >= TIER_RANK[decision.floor]:
            return None
        decided = (not tool_names) or (not all_tier1) or any(self._ledger.is_verification(n) for n in tool_names)
        if not decided:
            return None
        redo = TierDecision(
            decision.floor, None, decision.floor, True, "floor_redo",
            decision.tier, "sub_floor_response",
        )
        self._record(redo.outcome, requested=redo.requested, effective=redo.tier, floor=redo.floor, evidence="sub_floor_response")
        return redo

    def after_tools(self, *, tool_names: Sequence[str], all_tier1: bool, results_is_error: Sequence[bool]) -> None:
        self._ledger.record(tool_names, all_tier1, results_is_error)

    def observe(self, decision: TierDecision, parse: DirectiveParse, *, prompt_tokens_estimate: int) -> str:
        """Apply ``parse`` for the NEXT step. Returns the outcome label (never raises on bad input)."""
        if parse.status == "absent":
            return "no_directive"
        directive = parse.directive
        if parse.status == "invalid" or directive is None:
            return self._rejected(f"rejected:{parse.detail or 'invalid'}", decision, directive)
        tier = directive.tier
        up = TIER_RANK[tier] > TIER_RANK[self._agent_tier]
        evidence = ""
        if up:
            if self._up_moves >= self._max_up:
                return self._rejected("rejected:upward_cap", decision, directive)
            _stakes, signals = self._read_case()
            if self._ledger.error:
                evidence = "prior_error"
            elif self._ledger.verification_failed:
                evidence = "failed_verification"
            elif signals & EVIDENCE_SIGNALS:
                evidence = "organ_signal"
            else:
                return self._rejected("rejected:uncorroborated_upward", decision, directive)
        if not self._eligibility.assess(tier, prompt_tokens=prompt_tokens_estimate, reserved_output=0).eligible:
            return self._rejected("rejected:ineligible", decision, directive)
        self._agent_tier = tier
        if up:
            self._up_moves += 1
        self._accepted_reason = directive.reason
        self._accepted_evidence = evidence or None
        self._record(
            "agent_choice", requested=tier, effective=self._agent_tier, floor=decision.floor,
            evidence=evidence, model_reason=directive.reason,
        )
        return "agent_choice"

    def _rejected(self, outcome: str, decision: TierDecision, directive: TierDirective | None) -> str:
        self._record(
            outcome, requested=directive.tier if directive else "", effective=self._agent_tier,
            floor=decision.floor, model_reason=directive.reason if directive else "",
        )
        return outcome

    # -- prompt / audit --------------------------------------------------------
    def prompt_block(self, *, prompt_tokens_estimate: int) -> str:
        tiers = [
            t for t in TEXT_TIERS
            if self._eligibility.assess(t, prompt_tokens=prompt_tokens_estimate, reserved_output=0).eligible
        ]
        if not tiers:
            return ""
        floor = stakes_floor_tier(self._last_stakes, self._floor_map)
        floor_note = (
            f" Steps that decide, verify or follow an error run at no lower than '{floor}' regardless."
            if floor else ""
        )
        return (
            "Model tier: you may name the tier for your next step by ending a reply that calls tools "
            "with one final line, "
            f'{DIRECTIVE_PREFIX} {{"tier":"<tier>","reason":"<reason>"}}. '
            f"Eligible tiers: {', '.join(tiers)}. Reasons: {', '.join(sorted(REASON_TOKENS))}. "
            "Moving up needs evidence such as an error. Omit the line to keep the current tier."
            f"{floor_note}"
        )

    def stats(self) -> dict[str, int]:
        return dict(self._counts)

    async def drain_audit(self) -> None:
        """Wait for audit records still being written; never raises."""
        if self._audit_drain is not None:
            try:
                await self._audit_drain()
            except Exception:
                logger.warning("AD-1324: draining the tier audit failed; some records may be missing", exc_info=True)

    def _record(
        self, outcome: str, *, requested: str, effective: str, floor: str | None,
        evidence: str = "", model_reason: str = "",
    ) -> None:
        self._counts[outcome] = self._counts.get(outcome, 0) + 1
        payload = {
            "event": "tier_decision", "agent_id": self._agent_id, "work_item_id": self.work_item_id,
            "step": self._step, "requested": requested, "effective": effective, "floor": floor,
            "outcome": outcome, "evidence": evidence, "model_reason": model_reason,
        }
        logger.info(
            "AD-1324: tier decision agent=%s work_item=%s step=%s outcome=%s requested=%s effective=%s "
            "floor=%s evidence=%s model_reason=%s",
            self._agent_id[:12], payload["work_item_id"], self._step, outcome, requested, effective,
            floor, evidence or "-", model_reason or "-",
        )
        if self._audit is None:
            return
        try:
            self._audit(payload)
        except Exception:
            logger.warning("AD-1324: tier audit callback failed; the decision stands", exc_info=True)


class TierControllerUnavailable(Exception):
    """AD-1324 amendment 2: an armed run's tier controller could not be built."""


class FailedTierController:
    """Stands in for a controller that failed to build while the run was armed.

    Every decision call raises ``TierControllerUnavailable``, so the loop's fault latch ends the run
    with a stated error and zero model calls: an armed run is never silently unarmed. Its own class so
    ``TierChoiceController`` stays within its method limit.
    """

    steps = 0
    last_floor: str | None = None
    work_item_id: str | None = None

    def __init__(self, cause: str, audit_sink: Any = None) -> None:
        self.cause = cause
        self.audit_sink = audit_sink

    def _unavailable(self) -> TierControllerUnavailable:
        return TierControllerUnavailable(self.cause)

    def next_request_tier(self) -> Any:
        raise self._unavailable()

    def prompt_block(self, **_kwargs: Any) -> str:
        raise self._unavailable()

    def guard_response(self, *_args: Any, **_kwargs: Any) -> Any:
        raise self._unavailable()

    def after_tools(self, **_kwargs: Any) -> None:
        raise self._unavailable()

    def observe(self, *_args: Any, **_kwargs: Any) -> str:
        raise self._unavailable()

    @property
    def eligibility(self) -> Any:
        raise self._unavailable()

    async def drain_audit(self) -> None:
        """Wait (bounded) for the sink's records; never raises."""
        if self.audit_sink is not None:
            try:
                await self.audit_sink.drain()
            except Exception:
                logger.warning("AD-1324: draining the tier audit failed; some records may be missing", exc_info=True)


def tier_choice_armed(runtime: Any) -> bool:
    """All four flags strictly ``is True``; anything else (mocks, None) is unarmed."""
    config = getattr(runtime, "config", None)
    dm = getattr(config, "dm_agentic", None)
    econ = getattr(dm, "economic_judgment", None)
    choice = getattr(econ, "tier_choice", None)
    routing = getattr(config, "model_routing", None)
    return (
        getattr(dm, "enabled", False) is True
        and getattr(econ, "enabled", False) is True
        and getattr(choice, "enabled", False) is True
        and getattr(routing, "enabled", False) is True
    )
