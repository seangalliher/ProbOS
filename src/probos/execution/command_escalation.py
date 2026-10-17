"""AD-1328 S2b (#1530): an escalated ``run_command`` goes to the chain of command.

``RunCommandTool`` hands every ``escalate`` verdict to the runtime's one
``CommandEscalations`` (built by ``build_command_escalations`` when the policy has
rules and the approval and request stores run). For one call it answers, in order:

1. **A usable approval** for this agent, scope, canonical command and policy digest
   (``probos.execution.command_approvals``) whose scope is still open: one run is
   admitted and recorded -- the ``approved_run`` the first time, a ``reuse`` after --
   and the tool runs the command. Only a work item's scope reuses.
2. **A denial** in this scope: refused; nothing is filed again. A live denial of the
   same command wins over any approval of it, under any request id: the store admits no
   run and records no approval while it stands (repair r1).
3. Otherwise **filed** as an AD-1154 ``action`` request (tool ``run_command``, action
   ``execute``) carrying the bounded command text, the matched rules and each cause
   (rule and justification, or the reason no rule decided it); a repeat folds into the
   pending request. The agent is told the request id, that nothing ran, and not to
   repeat the call now.

Approval never replays the command (AD-1154, BF-830). The Captain's approval, through
``probos.routers.capability_requests``, calls ``fulfil_approval``: an ``active`` row is
recorded when the policy digest is the running one and the scope is still open, then
the request is marked fulfilled. The command runs when the asking agent issues it
again in that scope. ``forbid`` never reaches this module, and no approval runs a
command whose own decision is ``forbid`` (``CommandGateVerdict.runs``).

Every step fails toward refusal: a store that raises, a payload that will not
validate, an inbox at its cap or a call without an agent identity is refused, never
run. The mesh path (``ShellCommandAgent``) does not come here: it runs a command on
every pool member and re-runs it to verify, so it keeps S2a's refusal.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from probos.capability_request import THREAD_ID_MAX_CHARS, validate_action_payload
from probos.execution.command_approvals import (
    CAPTAIN,
    COMMAND_APPROVAL_ACTION,
    COMMAND_APPROVAL_TOOL_ID,
    ENDED_WORK_ITEM_STATUSES,
    THREAD_SCOPE_PREFIX,
    WORK_ITEM_SCOPE_PREFIX,
    approval_ttl_seconds,
    command_approval_request,
    scope_work_item_id,
)
from probos.execution.command_gate import CommandGateVerdict

logger = logging.getLogger(__name__)

_FILED_IN_TASK_FRAME: Final = (
    "The command policy requires the Captain's approval before this command runs. It was "
    "filed for review as request {request_id} and was not run. {causes} Do not repeat this "
    "call now; a repeat is folded into the same request. Continue with the rest of your task "
    "and report that this command is waiting for approval. Once it is approved, running the "
    "same command again in this task runs it."
)
_FILED_ONCE_FRAME: Final = (
    "The command policy requires the Captain's approval before this command runs. It was "
    "filed for review as request {request_id} and was not run. {causes} Do not repeat this "
    "call now; a repeat is folded into the same request. Continue with the rest of your work "
    "and report that this command is waiting for approval. Once it is approved, running the "
    "same command again {where}within an hour runs it once."
)
_DENIED_FRAME: Final = (
    "The Captain denied this command for this work (request {request_id}), so it was not "
    "run. {causes} Do not repeat it; continue without it and report that it was denied."
)
_INBOX_FULL_FRAME: Final = (
    "The command policy requires the Captain's approval before this command runs. Too many "
    "of your requests are already awaiting review, so it was refused rather than filed, and "
    "it was not run. {causes} Continue with the rest of your work and report what remains open."
)
_UNFILED_FRAME: Final = (
    "The command policy requires the Captain's approval before this command runs. Filing it "
    "for review failed, so it was not run. {causes} Do not repeat this call; continue with "
    "the rest of your work and report that this command needs approval."
)
#: Display bounds for the filed payload: the first pair, then the second if the payload
#: would exceed the AD-1154 limit (4,000 characters, capability_request.py:73).
_COMMAND_DISPLAY_CHARS: Final = (1200, 300)
_CAUSE_DISPLAY_CHARS: Final = (200, 80)
_MAX_CAUSES_FILED: Final = 5
_MAX_AGENT_ID_CHARS: Final = 128
_RATIONALE_CHARS: Final = 280
#: AD-1328 S2c: the tool-context key naming a plain dispatched work item
#: (``CognitiveAgent._run_agentic_dispatch``). Distinct from ``_crew_work_item_id``, which
#: means "crew child" to AD-1324 and to the crew tools.
DISPATCHED_WORK_ITEM_KEY: Final = "_dispatched_work_item_id"


@dataclass(frozen=True)
class EscalationScope:
    """Who asks, and the scope an approval of this call would be bound to."""

    agent_id: str
    scope_key: str  # "work_item:<id>", "thread:<id>" or ""
    work_item_id: str | None
    thread_id: str


@dataclass(frozen=True)
class EscalationOutcome:
    """The verdict as recorded (with its ``approval`` entry) and the refusal, if any."""

    verdict: CommandGateVerdict
    message: str | None  # None: the command runs


def escalation_scope(context: object) -> EscalationScope | None:
    """The asker and scope from the invocation context ``ToolRegistry.check_and_invoke``
    built: it sets ``agent_id`` over the caller's keys; a crew child's loop context
    carries ``_crew_work_item_id``, a plain dispatched work item's
    ``DISPATCHED_WORK_ITEM_KEY`` (S2c), a conversation's ``thread_id``. None without an
    agent identity."""
    if type(context) is not dict:
        return None
    agent_id = context.get("agent_id")
    if type(agent_id) is not str or not agent_id.strip() or len(agent_id) > _MAX_AGENT_ID_CHARS:
        return None
    thread = context.get("thread_id")
    thread_id = thread if type(thread) is str and 0 < len(thread) <= THREAD_ID_MAX_CHARS else ""
    crew_item = context.get("_crew_work_item_id")
    if type(crew_item) is str and scope_work_item_id(WORK_ITEM_SCOPE_PREFIX + crew_item) is not None:
        return EscalationScope(agent_id, WORK_ITEM_SCOPE_PREFIX + crew_item, crew_item, thread_id)
    dispatched = context.get(DISPATCHED_WORK_ITEM_KEY)
    if type(dispatched) is str and scope_work_item_id(WORK_ITEM_SCOPE_PREFIX + dispatched) is not None:
        return EscalationScope(agent_id, WORK_ITEM_SCOPE_PREFIX + dispatched, dispatched, thread_id)
    if thread_id:
        return EscalationScope(agent_id, THREAD_SCOPE_PREFIX + thread_id, None, thread_id)
    return EscalationScope(agent_id, "", None, "")


def with_approval(
    verdict: CommandGateVerdict, state: str, request_id: str | None = None, use_id: str | None = None,
) -> CommandGateVerdict:
    """The verdict carrying what the approval route did (its record's ``approval``)."""
    return dataclasses.replace(
        verdict, approval={"state": state, "request_id": request_id, "use_id": use_id},
    )


def _display(text: str, limit: int) -> str:
    safe = text.encode("utf-8", "backslashreplace").decode("utf-8")
    if len(safe) <= limit:
        return safe
    return f"{safe[:limit]} ...[{len(safe) - limit} more characters]"


def command_approval_payload(
    verdict: CommandGateVerdict, command: str, scope: EscalationScope,
) -> dict[str, Any] | None:
    """The AD-1154 action payload for one escalation, or None if it will not validate."""
    if verdict.evaluation is None or verdict.canonical is None:
        return None
    record = verdict.record or {}
    causes = verdict.causes
    for command_chars, cause_chars in zip(_COMMAND_DISPLAY_CHARS, _CAUSE_DISPLAY_CHARS):
        payload: dict[str, Any] = {
            "tool_id": COMMAND_APPROVAL_TOOL_ID,
            "action": COMMAND_APPROVAL_ACTION,
            "params": {
                "command": _display(command, command_chars),
                "command_chars": len(command),
                "canonical_key": verdict.canonical.key,
                "canonical_kind": verdict.canonical.kind,
                "policy_digest": verdict.evaluation.policy_digest,
                "dialect": verdict.evaluation.dialect,
                "call_site": verdict.call_site,
                "rules": list(record.get("matched_rules", [])),
                "causes": [
                    {
                        "kind": cause.kind,
                        "rule": cause.rule,
                        "text": _display(cause.text, cause_chars),
                        "alternative": None if cause.alternative is None else _display(cause.alternative, cause_chars),
                    }
                    for cause in causes[:_MAX_CAUSES_FILED]
                ],
                "causes_omitted": max(len(causes) - _MAX_CAUSES_FILED, 0),
            },
            "scope_key": scope.scope_key,
            "session_id": None,
            "thread_id": scope.thread_id,
        }
        if validate_action_payload(payload) is not None:
            return payload
    return None


def _rationale(verdict: CommandGateVerdict) -> str:
    names = list((verdict.record or {}).get("matched_rules", []))
    basis = ", ".join(names) if names else ", ".join(sorted({cause.kind for cause in verdict.causes}))
    return f"AD-1328 command policy escalation ({basis or 'escalate'})"[:_RATIONALE_CHARS]


class CommandEscalations:
    """The runtime's one route from an ``escalate`` verdict to the chain of command."""

    def __init__(
        self,
        *,
        gate: Any,
        approvals: Any,
        requests: Any,
        work_items: Any,
        max_pending_per_agent: int = 20,
        pending_ttl_hours: float = 72.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._gate = gate
        self._approvals = approvals
        self._requests = requests
        self._work_items = work_items
        self._max_pending = int(max_pending_per_agent)
        self._pending_ttl_seconds = float(pending_ttl_hours) * 3600.0
        self._clock = clock

    async def resolve(self, verdict: CommandGateVerdict, *, command: str, context: object) -> EscalationOutcome:
        """Run under an approval, refuse as denied, or file; never raises for a store fault."""
        if verdict.decision != "escalate" or verdict.canonical is None or verdict.evaluation is None:
            return EscalationOutcome(verdict, verdict.refusal_message)
        scope = escalation_scope(context)
        if scope is None:
            logger.warning(
                "AD-1328: an escalated run_command call carried no agent identity; it was "
                "neither filed nor run",
            )
            return self._refuse(verdict, "unfiled", _UNFILED_FRAME)
        key = verdict.canonical.key
        digest = verdict.evaluation.policy_digest
        try:
            row = await self._approvals.find(scope.agent_id, scope.scope_key, key, digest, state="active")
            if row is not None and await self._scope_open(scope.scope_key):
                use = await self._approvals.use(row.request_id, agent_id=scope.agent_id, scope_key=scope.scope_key)
                if use is not None:
                    logger.info(
                        "AD-1328: agent %s runs an escalated command as %s of approval %s (scope %s)",
                        scope.agent_id[:12], use.use_kind, row.request_id[:12], scope.scope_key[:40] or "-",
                    )
                    return EscalationOutcome(with_approval(verdict, use.use_kind, row.request_id, use.use_id), None)
            if scope.scope_key:
                denied = await self._approvals.find(scope.agent_id, scope.scope_key, key, digest, state="denied")
                if denied is not None:
                    return self._refuse(verdict, "denied", _DENIED_FRAME, denied.request_id)
        except Exception:
            logger.warning(
                "AD-1328: the command approval lookup failed for agent %s; the command is not "
                "run and is filed for review", scope.agent_id[:12], exc_info=True,
            )
        return await self._file(verdict, command, scope)

    async def fulfil_approval(self, request_store: Any, decided: Any) -> Any | None:
        """The Captain approved a command escalation: record it, then fulfil the request.

        Returns the fulfilled request, or None -- nothing usable recorded and the request
        left approved -- when the request is not an approved, well-formed command
        escalation, was not decided by the Captain, was filed under another policy digest
        than the running one, its work item ended, or a live denial of the same command in
        the same scope stands (any request id). A later fulfil call for the same request
        (the BF-722 retry) records it once the cause has cleared; the actionable list and
        the HXI do not yet offer that retry for command escalations (F-113, #1523).
        """
        ask = command_approval_request(decided)
        if ask is None or getattr(decided, "status", None) != "approved":
            return None
        if getattr(decided, "decided_by", None) != CAPTAIN:
            logger.warning(
                "AD-1328: command approval %s was decided by %r, not the Captain; it grants nothing",
                ask.request_id[:12], getattr(decided, "decided_by", None),
            )
            return None
        if self._gate.digest != ask.policy_digest:
            logger.warning(
                "AD-1328: command approval %s was filed under another command policy "
                "(digest %s, running %s); it grants nothing and the command escalates again",
                ask.request_id[:12], ask.policy_digest[:16], str(self._gate.digest)[:16],
            )
            return None
        if not await self._scope_open(ask.scope_key):
            logger.warning(
                "AD-1328: command approval %s arrived after its work item ended; it grants nothing",
                ask.request_id[:12],
            )
            return None
        row = await self._approvals.record_decision(
            request_id=ask.request_id, agent_id=ask.agent_id, scope_key=ask.scope_key,
            canonical_key=ask.canonical_key, policy_digest=ask.policy_digest,
            state="active", approver=CAPTAIN, ttl_seconds=approval_ttl_seconds(ask.scope_key),
        )
        if row is None:
            logger.warning(
                "AD-1328: command approval %s was not recorded: a denial of the same command "
                "for agent %s in scope %s still stands; it grants nothing",
                ask.request_id[:12], ask.agent_id[:12], ask.scope_key[:40] or "-",
            )
            return None
        if row.state != "active":
            return None
        logger.info(
            "AD-1328: command approval %s recorded for agent %s (scope %s); the command runs "
            "when the agent issues it again there",
            ask.request_id[:12], ask.agent_id[:12], ask.scope_key[:40] or "-",
        )
        return await request_store.mark_fulfilled(ask.request_id)

    async def record_denial(self, decided: Any) -> bool:
        """The Captain denied a command escalation: within its scope it stays denied."""
        ask = command_approval_request(decided)
        if ask is None or not ask.scope_key or getattr(decided, "status", None) != "denied":
            return False
        approver = getattr(decided, "decided_by", None)
        row = await self._approvals.record_decision(
            request_id=ask.request_id, agent_id=ask.agent_id, scope_key=ask.scope_key,
            canonical_key=ask.canonical_key, policy_digest=ask.policy_digest, state="denied",
            approver=approver if type(approver) is str and approver.strip() else CAPTAIN,
            ttl_seconds=approval_ttl_seconds(ask.scope_key),
        )
        return row is not None and row.state == "denied"

    async def _file(self, verdict: CommandGateVerdict, command: str, scope: EscalationScope) -> EscalationOutcome:
        try:
            pending = self._requests.count_pending_sync(
                scope.agent_id, stale_before=self._clock() - self._pending_ttl_seconds,
            )
        except Exception:
            logger.warning(
                "AD-1328: could not count pending asks for agent %s; the command is refused "
                "rather than filed", scope.agent_id[:12], exc_info=True,
            )
            return self._refuse(verdict, "unfiled", _UNFILED_FRAME)
        if pending >= self._max_pending:
            return self._refuse(verdict, "inbox_full", _INBOX_FULL_FRAME)
        payload = command_approval_payload(verdict, command, scope)
        if payload is None:
            logger.warning("AD-1328: an escalated command's approval payload did not validate; not filed")
            return self._refuse(verdict, "unfiled", _UNFILED_FRAME)
        try:
            request = await self._requests.file_action_request(
                scope.agent_id, payload, rationale=_rationale(verdict), work_item_id=scope.work_item_id,
            )
        except Exception:
            logger.warning(
                "AD-1328: filing an escalated command for agent %s failed; it was not run",
                scope.agent_id[:12], exc_info=True,
            )
            return self._refuse(verdict, "unfiled", _UNFILED_FRAME)
        request_id = getattr(request, "id", "") if request is not None else ""
        if type(request_id) is not str or not request_id:
            return self._refuse(verdict, "unfiled", _UNFILED_FRAME)
        logger.info(
            "AD-1328: escalated command for agent %s filed as request %s (scope %s)",
            scope.agent_id[:12], request_id[:12], scope.scope_key[:40] or "-",
        )
        if scope.work_item_id is not None:
            return self._refuse(verdict, "filed", _FILED_IN_TASK_FRAME, request_id)
        where = "in this conversation " if scope.thread_id else ""
        return self._refuse(verdict, "filed", _FILED_ONCE_FRAME, request_id, where=where)

    async def _scope_open(self, scope_key: str) -> bool:
        """A work-item scope is open while its item exists and has not ended; a thread or
        empty scope ends by time alone. A read that fails closes it."""
        work_item_id = scope_work_item_id(scope_key)
        if work_item_id is None:
            return True
        if self._work_items is None:
            return False
        try:
            item = await self._work_items.get_work_item(work_item_id)
        except Exception:
            logger.warning(
                "AD-1328: could not read work item %s; its command approvals are not used",
                work_item_id, exc_info=True,
            )
            return False
        return item is not None and getattr(item, "status", None) not in ENDED_WORK_ITEM_STATUSES

    @staticmethod
    def _refuse(
        verdict: CommandGateVerdict, state: str, frame: str, request_id: str | None = None, *, where: str = "",
    ) -> EscalationOutcome:
        message = frame.format(request_id=request_id or "", causes=verdict.cause_text, where=where)
        return EscalationOutcome(with_approval(verdict, state, request_id), message)


def build_command_escalations(
    *, gate: Any, approvals: Any, requests: Any, work_items: Any, inbox: Any,
) -> CommandEscalations | None:
    """The runtime's one ``CommandEscalations``, or None: no policy rules, or no approval
    or request store (an escalation then keeps S2a's refusal, ``_ESCALATE_FRAME``)."""
    if gate is None or getattr(gate, "configured", False) is not True:
        return None
    if approvals is None or requests is None:
        logger.warning(
            "AD-1328: the command policy has rules but the %s is not running; an escalated "
            "command is refused without being filed",
            "command approval store" if approvals is None else "capability request store",
        )
        return None
    return CommandEscalations(
        gate=gate,
        approvals=approvals,
        requests=requests,
        work_items=work_items,
        max_pending_per_agent=int(getattr(inbox, "max_pending_per_agent", 20)),
        pending_ttl_hours=float(getattr(inbox, "pending_ask_ttl_hours", 72)),
    )
