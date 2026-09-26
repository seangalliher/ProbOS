"""AD-1213 (#1170): ``review_requests`` -- how a chief or the First Officer decides a request.

Registered only while delegated approvals are wired, with every rank at
``none``: the tool reaches an agent only through a Captain grant (the HXI
capability toggle or the AD-894 crew grant). The decider is always the trusted
``context["agent_id"]`` that ``ToolRegistry.check_and_invoke`` sets; the
parameters may not name an agent, and a crew room is not a decision seat.

The service answers only whether this agent may decide this request now (DP-1:
it never picks a decider or judges merit). Every refusal carries its code and a
fixed text, and a refusal about the request says it stays with the Captain
(DP-13(c)). Success outputs are complete, pre-rendered Python-literal objects
admitted by the invocation's ``ToolResultPresentation``.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from probos.delegated_approvals import (
    REFUSAL_TEXT,
    REVIEW_TOOL_ID,
    DelegatedApprovalRefused,
    DelegatedApprovalService,
    Refusal,
    ReviewableRequest,
)
from probos.tools.protocol import (
    ToolResult,
    ToolResultPresentation,
    ToolType,
    refuse_undeclared_params,
)

logger = logging.getLogger(__name__)

# Every rank at none, so only the Captain's grant (Layer 4) reaches the tool.
# The single source for the wiring and the tests.
REVIEW_TOOL_DEFAULT_PERMISSIONS: dict[str, str] = {
    "ensign": "none",
    "lieutenant": "none",
    "commander": "none",
    "senior_officer": "none",
}

_ROOM_CONTEXT_KEYS = frozenset({"_crew_session_id", "_crew_work_item_id"})
_DECIDE_KEYS = ("queue", "request_id", "approve", "reason")
_STAYS_WITH_CAPTAIN = " The request stays with the Captain."
# Refusals about the call itself rather than the request: there is nothing to route.
_UNROUTED = frozenset({
    Refusal.UNKNOWN_QUEUE,
    Refusal.UNKNOWN_REQUEST,
    Refusal.NOT_PENDING,
    Refusal.INVALID_DECISION,
})
_TARGET_CHARS = 200
_RATIONALE_CHARS = 300
_CONTEXT_ERROR = (
    "review_requests: context_invalid: The invocation context must name the deciding "
    "agent and carry its result presentation."
)
_ROOM_ERROR = (
    "review_requests: crew_room: A crew room is not a decision seat. Decide from your own turn."
)
_ACTION_ERROR = "review_requests: invalid_action: Give action as 'list' or 'decide'."
_BUDGET_ERROR = "review_requests: result_budget"
_RECEIPT_ERROR = (
    "review_requests: receipt_withheld: The decision was recorded; its receipt did not fit "
    "this turn's result presentation."
)


def _refusal_text(refusal: Refusal, decidable_after: Any = None) -> str:
    """The fixed, model-facing refusal: its code, its text, and where the request goes now."""
    text = f"review_requests: {refusal.value}: {REFUSAL_TEXT[refusal]}"
    if refusal not in _UNROUTED:
        text += _STAYS_WITH_CAPTAIN
    if (
        refusal is Refusal.GRACE_PERIOD
        and type(decidable_after) in (int, float)
        and math.isfinite(decidable_after)
    ):
        when = datetime.fromtimestamp(math.ceil(decidable_after), tz=timezone.utc)
        text += f" Decidable after {when.isoformat()}."
    return text


def _entry(item: ReviewableRequest) -> dict[str, Any]:
    return {
        "queue": item.queue,
        "request_id": item.request_id,
        "kind": item.kind,
        "target": item.target[:_TARGET_CHARS],
        "rationale": item.rationale[:_RATIONALE_CHARS],
        "requester_id": item.requester_id,
        "created_at": item.created_at,
        "request_class": item.request_class.value,
        "role": item.role.value if item.role is not None else None,
        "decidable_after": item.decidable_after,
    }


def _render(presentation: ToolResultPresentation, value: dict[str, Any]) -> str | None:
    """The complete rendering, or None when it exceeds the invocation's budget."""
    rendered = presentation.render_complete(value)
    if rendered is not None and (type(rendered) is not str or not rendered):
        raise ValueError("review_requests: the result presentation returned an invalid rendering")
    return rendered


class ReviewRequestsTool:
    """List the requests an agent may decide, and decide one, through the delegated-approval service."""

    def __init__(self, *, service: DelegatedApprovalService) -> None:
        if service is None:
            raise ValueError("AD-1213: ReviewRequestsTool needs the delegated-approval service")
        self._service = service

    @property
    def tool_id(self) -> str:
        return REVIEW_TOOL_ID

    @property
    def name(self) -> str:
        return "Review Requests"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.INFRA_SERVICE

    @property
    def description(self) -> str:
        return (
            "List the capability and skill requests you currently hold authority to decide, "
            "and approve or deny one. Only requests from crew under your command appear. "
            "Every decision is recorded under your identity and reported to the Captain. "
            "A request outside your authority stays with the Captain."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "decide"]},
                "queue": {"type": "string", "enum": ["capability", "skill"]},
                "request_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "approve": {"type": "boolean"},
                "reason": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "string",
            "description": (
                "A complete pre-rendered Python-literal object (not JSON). list: requests "
                "and more; decide: decided, queue, request_id, status, fulfilled, "
                "captain_notified, audited, role and request_class."
            ),
        }

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        if type(context) is not dict:
            return ToolResult(error=_CONTEXT_ERROR)
        if any(key in context for key in _ROOM_CONTEXT_KEYS):
            return ToolResult(error=_ROOM_ERROR)
        presentation = context.get("_tool_result_presentation")
        agent_id = context.get("agent_id")
        if (
            type(presentation) is not ToolResultPresentation
            or not callable(presentation.render_complete)
            or type(agent_id) is not str
            or not agent_id
        ):
            return ToolResult(error=_CONTEXT_ERROR)
        if type(params) is not dict:
            return ToolResult(error=_ACTION_ERROR)
        undeclared = refuse_undeclared_params(self, params)
        if undeclared is not None:
            return undeclared
        action = params.get("action")
        try:
            if action == "list":
                return await self._list(agent_id, presentation)
            if action == "decide":
                return await self._decide(agent_id, params, presentation)
        except DelegatedApprovalRefused as refused:
            return ToolResult(error=_refusal_text(refused.refusal))
        except Exception:
            logger.warning(
                "AD-1213: review_requests %s failed for %s; the call is refused as "
                "state_unreadable and the requests stay with the Captain",
                str(action)[:16], agent_id[:64], exc_info=True,
            )
            return ToolResult(error=_refusal_text(Refusal.STATE_UNREADABLE))
        return ToolResult(error=_ACTION_ERROR)

    async def _list(self, agent_id: str, presentation: ToolResultPresentation) -> ToolResult:
        """The advisory snapshot, halved until it fits the presentation budget."""
        items, more = await self._service.list_reviewable(agent_id)
        entries = [_entry(item) for item in items]
        rendered = _render(presentation, {"requests": entries, "more": more})
        while rendered is None and len(entries) > 1:
            entries = entries[: len(entries) // 2]
            rendered = _render(presentation, {"requests": entries, "more": True})
        if rendered is None:
            return ToolResult(error=_BUDGET_ERROR)
        return ToolResult(output=rendered)

    async def _decide(
        self, agent_id: str, params: dict[str, Any], presentation: ToolResultPresentation,
    ) -> ToolResult:
        """One decision through the service; a refusal leaves the request with the Captain."""
        if any(key not in params for key in _DECIDE_KEYS):
            return ToolResult(error=_refusal_text(Refusal.INVALID_DECISION))
        outcome = await self._service.decide(
            agent_id,
            queue=params["queue"],
            request_id=params["request_id"],
            approve=params["approve"],
            reason=params["reason"],
        )
        if outcome.refusal is not None:
            return ToolResult(error=_refusal_text(outcome.refusal, outcome.decidable_after))
        receipt = {
            "decided": True,
            "queue": outcome.queue,
            "request_id": outcome.request_id,
            "status": outcome.status,
            "fulfilled": outcome.fulfilled,
            "captain_notified": outcome.notified,
            "audited": outcome.audited,
            "role": outcome.role.value if outcome.role is not None else None,
            "request_class": (
                outcome.request_class.value if outcome.request_class is not None else None
            ),
        }
        try:
            rendered = _render(presentation, receipt)
        except Exception:
            logger.warning(
                "AD-1213: %s decided %s request %s, but rendering its receipt failed; the "
                "decision stands and the agent is told it was recorded",
                agent_id[:64], outcome.queue, str(outcome.request_id)[:12], exc_info=True,
            )
            rendered = None
        if rendered is None:  # the decision is committed: never report it as a refusal
            return ToolResult(error=_RECEIPT_ERROR)
        return ToolResult(output=rendered)
