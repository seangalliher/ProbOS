"""AD-1324 amendment 1: the agentic loop's fail-closed adapter to the tier controller.

The loop asks this adapter what tier each model request takes, whether that exact tier is
eligible for the request, and whether a response stands. Every controller call is guarded: a
controller failure latches and ends the run with a stated error rather than guessing a tier,
and an ineligible tier is refused rather than substituted. Cancellation always propagates.
"""

from __future__ import annotations

import enum
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from probos.cognitive.swe_harness.tool_call import ToolUseBlock

logger = logging.getLogger(__name__)

FLOOR_UNMET_TEXT = (
    "I stopped because no model is available at the tier this work requires. "
    "I did not answer from a lower tier."
)
UNAVAILABLE_TEXT = (
    "I stopped because the model tier chosen for this step is not available. "
    "No other tier was substituted."
)
FAULT_TEXT = "I stopped because tier selection failed; no tier was guessed and no answer was given."
UNVERIFIABLE_TEXT = (
    "I stopped because the model route for this step could not be verified. "
    "Nothing was sent and no other model was substituted."
)
# Refusal errors that are infrastructure faults rather than a floor or eligibility decision.
FAULT_ERRORS = frozenset(
    {"tier_controller_failed", "tier_route_unverifiable", "tier_guard_fault", "tier_guard_failed"}
)


@dataclass(frozen=True)
class Refusal:
    """Why an armed run ends instead of dispatching or applying a step."""

    stopped_reason: str
    error: str
    text: str
    cause: str | None = None
    evidence: str | None = None


@dataclass(frozen=True)
class TierStop:
    """The closed context of an armed run's terminal stop, shared by its audit record and the ask."""

    error_kind: str
    cause: str | None
    request_id: str | None
    step: int | None
    floor: str | None
    requested_tier: str
    effective_tier: str
    work_item_id: str | None


@dataclass
class StepPlan:
    """The controller's decision for the next request."""

    decision: Any = None
    tier: str = ""
    extra: dict[str, Any] | None = None
    block: str | None = None
    refusal: Refusal | None = None


class GuardVerdict(enum.Enum):
    STAND = "stand"
    REDO = "redo"
    REFUSE = "refuse"


def response_refusal(response: Any, decision: Any = None) -> Refusal | None:
    """The refusal an armed response's error_kind maps to, if any.

    An unverifiable route under a stakes floor is an ASK to the chain of command (the floor stop),
    never a bare terminal error; without a floor it is a terminal fault.
    """
    kind = getattr(response, "error_kind", None)
    cause = getattr(response, "refusal_cause", None)
    cause = cause if type(cause) is str else None
    if kind == "tier_floor_unmet":
        return Refusal("tier_floor_unavailable", "tier_floor_unmet", FLOOR_UNMET_TEXT, cause or "floor_unmet")
    if kind == "tier_unavailable":
        return Refusal("error", "tier_unavailable", UNAVAILABLE_TEXT, cause or "exact_unavailable")
    if kind == "tier_route_unverifiable":
        if getattr(decision, "floor", None) is not None:
            return Refusal(
                "tier_floor_unavailable", "tier_route_unverifiable", UNVERIFIABLE_TEXT, "route_unverifiable",
            )
        return Refusal("error", "tier_route_unverifiable", UNVERIFIABLE_TEXT, "route_unverifiable")
    return None


class LoopTierSteps:
    """Guarded access to a TierChoiceController for one loop run."""

    def __init__(
        self,
        controller: Any,
        *,
        estimate_context: Callable[[list[Any]], int],
        is_tier1: Callable[[Any, Any], bool],
    ) -> None:
        self._ctl = controller
        self._estimate = estimate_context
        self._is_tier1 = is_tier1
        self._faulted = False
        self._audit_sink = getattr(controller, "audit_sink", None)

    def _stop(
        self, error_kind: str | None, cause: str | None, decision: Any, request_id: str | None,
    ) -> TierStop:
        requested = getattr(decision, "requested", None)
        effective = getattr(decision, "tier", None)
        return TierStop(
            error_kind=error_kind or "",
            cause=cause,
            request_id=request_id if type(request_id) is str else None,
            step=getattr(self._ctl, "steps", None),
            floor=getattr(decision, "floor", None) or getattr(self._ctl, "last_floor", None),
            requested_tier=requested if type(requested) is str else "",
            effective_tier=effective if type(effective) is str else "",
            work_item_id=getattr(self._ctl, "work_item_id", None),
        )

    def _emit_stop(self, outcome: str, stop: TierStop, evidence: str | None = None) -> None:
        if self._audit_sink is None:
            return
        self._audit_sink.emit_terminal(
            outcome=outcome, step=stop.step, floor=stop.floor, request_id=stop.request_id,
            error_kind=stop.error_kind or None, cause=stop.cause, evidence=evidence,
            work_item_id=stop.work_item_id, requested_tier=stop.requested_tier,
            effective_tier=stop.effective_tier,
        )

    def finish(self, result: Any, refusal: Refusal, decision: Any, request_id: str | None) -> Any:
        """Record a refusal on an AgenticResult, emit its one terminal audit record, return it."""
        result.stopped_reason = refusal.stopped_reason
        if refusal.error:
            result.error = refusal.error
        result.final_text = refusal.text
        try:
            stop = self._stop(refusal.error, refusal.cause, decision, request_id)
            result.tier_stop = stop
            self._emit_stop("faulted" if refusal.error in FAULT_ERRORS else "refused", stop, refusal.evidence)
        except Exception:
            logger.warning(
                "AD-1324: the terminal tier stop could not be recorded; the run's outcome is unchanged",
                exc_info=True,
            )
        return result

    def call_failed(
        self, result: Any, exc: BaseException, decision: Any, request_id: str | None, *, redo: bool,
    ) -> Any:
        """A model call raised: the run ends in error exactly as unarmed, with one faulted terminal record."""
        result.stopped_reason = "error"
        result.error = str(exc)
        try:
            self._emit_stop(
                "faulted",
                self._stop("llm_call_failed", "redo_call_failed" if redo else "call_failed", decision, request_id),
            )
        except Exception:
            logger.warning(
                "AD-1324: the terminal tier stop for a failed model call could not be recorded; "
                "the run's error stands", exc_info=True,
            )
        return result

    def _fault(self, where: str, error: str) -> Refusal:
        self._faulted = True
        logger.error(
            "AD-1324: the tier controller failed %s; the run stops (%s) instead of guessing a tier",
            where, error, exc_info=True,
        )
        return Refusal("error", error, FAULT_TEXT)

    def plan(self, messages: list[Any], context: dict[str, Any], agent_id: str) -> StepPlan:
        """The next request's decision, tier, request fields and prompt block."""
        if self._faulted:
            return StepPlan(refusal=Refusal("error", "tier_controller_failed", FAULT_TEXT))
        try:
            decision = self._ctl.next_request_tier()
            block = self._ctl.prompt_block(prompt_tokens_estimate=self._estimate(messages)) or None
        except Exception:
            return StepPlan(refusal=self._fault("before a model call", "tier_controller_failed"))
        work_item_id = context.get("_crew_work_item_id")
        if type(work_item_id) is not str or not work_item_id:
            work_item_id = getattr(self._ctl, "work_item_id", None)
        extra = {
            "agent_id": agent_id if agent_id != "<unknown>" else None,
            "work_item_id": work_item_id,
            "min_tier": decision.floor if decision.floor_bound else None,
            "tier_choice_reason": decision.outcome,
            "exact_tier": True,
        }
        return StepPlan(decision=decision, tier=decision.tier, extra=extra, block=block)

    def admit(self, request: Any, decision: Any) -> Refusal | None:
        """Refuse a dispatch whose EXACT tier cannot take this request; never substitute a tier."""
        if self._faulted:
            return Refusal("error", "tier_controller_failed", FAULT_TEXT)
        try:
            tokens = self._request_tokens(request)
            verdict = self._ctl.eligibility.assess(
                request.tier, prompt_tokens=tokens, reserved_output=int(request.max_tokens or 0),
            )
        except Exception:
            return self._fault("while checking tier eligibility", "tier_controller_failed")
        if verdict.eligible:
            return None
        cause = verdict.cause or "ineligible"
        if getattr(decision, "floor", None) is not None:
            return Refusal("tier_floor_unavailable", "tier_floor_unmet", FLOOR_UNMET_TEXT, cause)
        return Refusal("error", "tier_ineligible", UNAVAILABLE_TEXT, cause)

    def _request_tokens(self, request: Any) -> int:
        messages = request.messages
        if messages:
            body = self._estimate(list(messages))
        else:
            body = len(request.prompt or "") // 4
        tools = json.dumps(request.tools, default=str) if request.tools else ""
        return body + len(request.system_prompt or "") // 4 + len(tools) // 4

    def guard(
        self, decision: Any, response: Any, *, redo_pass: bool = False,
    ) -> tuple[GuardVerdict, Any, Refusal | None]:
        """Whether the response stands, is re-issued at the floor, or ends the run."""
        if decision is None or getattr(response, "error_kind", None) is not None:
            return GuardVerdict.STAND, None, None
        uses = [b for b in (getattr(response, "content_blocks", None) or []) if isinstance(b, ToolUseBlock)]
        try:
            redo = self._ctl.guard_response(
                decision,
                tool_names=[u.tool_call.name for u in uses],
                all_tier1=all(self._is_tier1(u.tool_call.name, u.tool_call.arguments) for u in uses),
            )
        except Exception:
            return GuardVerdict.REFUSE, None, self._fault("while guarding a response", "tier_guard_failed")
        if redo is None:
            return GuardVerdict.STAND, None, None
        if redo_pass:
            return GuardVerdict.REFUSE, None, Refusal(
                "tier_floor_unavailable", "tier_floor_unmet", FLOOR_UNMET_TEXT, "redo_floor_unmet",
            )
        return GuardVerdict.REDO, redo, None

    def observe(self, decision: Any, parse: Any, tool_uses: list[Any], results: list[Any], messages: list[Any]) -> None:
        """Record the step's tools, then apply the directive; a failure latches the next step."""
        try:
            self._ctl.after_tools(
                tool_names=[u.tool_call.name for u in tool_uses],
                all_tier1=all(self._is_tier1(u.tool_call.name, u.tool_call.arguments) for u in tool_uses),
                results_is_error=[bool(getattr(r, "is_error", False)) for r in results],
            )
            if decision is not None:
                self._ctl.observe(decision, parse, prompt_tokens_estimate=self._estimate(messages))
        except Exception:
            self._fault("after tool results", "tier_controller_failed")
