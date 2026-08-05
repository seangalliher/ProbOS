"""AD-1164: a budget ceiling is a checkpoint that asks, not a cliff that truncates.

When the conversational agentic loop (AD-1065) exhausts ``dm_agentic.
max_iterations`` it stops dead. BF-697 fixed it *discarding* the work — the
partial text now survives — but the agent still has no way to say "I was cut
off", so exhausting the budget is indistinguishable from finishing. Measured on
the Captain's vessel: asked to type into a document, the agent spent its five
iterations on ``state, screenshot, click, click, click`` and never reached
``key_type``, then reported as though the turn were over.

This module is the structural fix, and it is almost entirely **reuse**:

* :data:`~probos.cognitive.crew_executor._REINVOKABLE_STOPPED_REASONS` and
  :func:`~probos.cognitive.crew_executor._render_continuation` are imported from
  ``crew_executor`` rather than reimplemented. AD-1155 built the re-invocation
  machinery for the crew fan-out; this is the same machinery pointed at the
  conversational seam. ``crew_executor`` itself is **not modified** — the
  membership set keeps exactly one member and the deliberate exclusions
  (``token_budget`` is an operator ceiling, ``error`` is usually window
  exhaustion that a longer prompt makes worse, ``complete`` means the model
  chose to stop) hold here unchanged.
* :class:`~probos.tools.action_approvals.ActionApprovalStore` (AD-1154) is the
  standing-rule mechanism. No second store, no second TTL, no wildcard.
* :class:`~probos.capability_request.CapabilityRequestStore` (AD-853) is the
  durable approval queue, reached through a FIFTH ``kind``, ``"continue"``. The
  AD-857 REST surface, the Captain-DM notifier and the kind-agnostic HXI panel
  all render it with no change — AD-1154 proved that for the fourth kind and it
  was re-verified here (``CapabilityRequestPanel.departmentColor`` falls through
  to the neutral colour for any unrecognised key).

**Fail-safe in one direction only.** Every failure — an absent store, a raising
cache read, a continuation that will not compose, a re-invocation that throws —
degrades to *today's* behaviour: stop, and report the partial work. An approval
mechanism must never be able to fail a run that would otherwise return
something. The consequence of a bug here is that the Captain is asked when they
did not need to be, never that a turn is lost.

**Known limit, stated rather than implied.** The only production caller of
``ActionApprovalStore.issue_approval`` is ``_maybe_issue_standing_rule`` in
``routers/capability_requests.py``, which is gated on ``kind == "action"``. So
at HEAD nothing *issues* a ``kind="continue"`` standing rule, and the
re-invocation branch below is reachable only when one is issued directly through
the store's public API. That is the AD-1159 precedent — ship the consult, wire
the issuance next — and it is recorded here so the next reader does not have to
discover it from a silent branch.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

# Single source of truth. AD-1155 owns the re-invokability decision and the
# continuation block; importing them is the point. Cross-module import of a
# module-private name is the established convention here (``captain_card.card``
# imports ``decomposer._CAPABILITY_GAP_RE``; ``skill_forge`` imports
# ``skill_catalog._validate_spec``), and re-typing either one would create
# exactly the drift this AD is supposed to avoid.
from probos.cognitive.crew_executor import (
    _REINVOKABLE_STOPPED_REASONS,
    _render_continuation,
)

logger = logging.getLogger(__name__)

# The fifth ``RequestKind``. A new kind rather than a new store because
# everything an approval inbox needs already exists on ``CapabilityRequestStore``
# and is already wired; a parallel store would put the ask on a surface nobody
# polls (AD-1154's reasoning, unchanged).
CONTINUE_REQUEST_KIND = "continue"

# The ``(tool_id, action, scope_key)`` triple a standing continue-rule is keyed
# on. It doubles as the AD-1154 six-key payload's machine shape, so a rule issued
# from a filed request would be keyed identically to the one consulted here.
#
# ``tool_id`` satisfies ``capability_request._TOOL_ID_RE`` and ``action``
# satisfies ``_ACTION_RE``, which is what lets the payload survive
# ``_decode_payload``'s re-validation on store reload.
#
# ``scope_key`` is empty ON PURPOSE, and it is not a wildcard: AD-1154's store
# matches all four fields exactly, so a rule with ``scope_key=""`` matches only
# an ask whose scope is ``""``. Continuation is scoped by ``agent_id``, which is
# the scope the Captain reasons about ("let Ezri keep going"), and there is no
# per-domain or per-page dimension to a turn's step budget.
CONTINUE_TOOL_ID = "dm_agentic"
CONTINUE_ACTION = "continue"
CONTINUE_SCOPE_KEY = ""

# Mirrors ``AgenticDispatchConfig.crew_loop_until_done_max_iterations``: a count
# of TOTAL passes including the first, so ``1`` means no re-invocation and is
# identical to today. The gate flag is what turns the feature on; this is a
# bound, never an enable.
_CONTINUE_MAX_PASSES = 2
_MAX_CONTINUE_PASSES = 5

# ``capability_request._THREAD_ID_MAX``. Duplicated rather than imported because
# importing a bound to satisfy it is the same coupling with extra indirection;
# a drift guard in tests/test_ad1164_continue_or_ask.py keeps the two in step.
_THREAD_ID_MAX = 64
_MAX_EXCERPT_CHARS = 120

# Every string below is asserted clean against the REAL imported
# ``decomposer._CAPABILITY_GAP_RE`` by the test suite. That regex is a minefield
# for this exact sentiment — the natural phrasing for "I did not finish" reaches
# for "could not", "unable to" and "ran out of", and ``lack`` is a BARE
# substring so "black", "slack" and "blacklist" trip it too. Any reword must be
# re-run there. The text also must not read as a completion: the whole point is
# that the agent can now say it stopped mid-task instead of implying it is done.
#
# The separator is kept OUT of the lead so a turn that produced no text at all
# yields the bare statement rather than a leading rule with nothing above it,
# and the lead itself varies for the same reason: "the work above is partial"
# is a false sentence when there is no work above. A feature whose entire point
# is that the agent describes its own state accurately does not get to be
# approximately right about that.
_CUT_OFF_SEPARATOR: str = "\n\n---\n"
_CUT_OFF_LEAD_WITH_WORK: str = (
    "I stopped here because this turn reached its step limit. The work above is "
    "partial and the task is still open."
)
_CUT_OFF_LEAD_NO_WORK: str = (
    "I stopped because this turn reached its step limit before I had anything "
    "to report back. The task is still open."
)
_CUT_OFF_TAIL: str = (
    " Say the word and I will pick up from exactly where this stopped."
)
_CUT_OFF_TAIL_WITH_REQUEST: str = (
    " I filed request {request_id} asking the Captain whether to keep going; "
    "say the word and I will pick up from exactly where this stopped."
)

_CONTINUE_RATIONALE: str = (
    "The conversational turn reached its step limit after {passes} pass(es) "
    "with the task still open. Approving records that this turn should carry on."
)

# AD-1204: the ``blocked_reason`` recorded on a work item parked on a continue
# ask. Written into item metadata by ``CapabilityGapDriver.block_on_request``
# beside ``capability_request_id``, and read back by the board and by anyone
# asking why a row stopped moving.
#
# Asserted clean against the REAL ``decomposer._CAPABILITY_GAP_RE`` by the test
# suite, for the same reason every other string in this module is: this text
# describes a turn that stopped, and the natural phrasing for that is exactly
# what the gap regex reads as "I need a capability I do not have".
_BLOCKED_REASON: str = "continue: the turn reached its step limit"

# AD-1170: a stalled turn has more than one possible cause, and until now the
# system only modelled one of them.
#
# AD-1164 asks "do you want me to keep going?", which is the right question when
# the turn simply needed more room. It is the wrong question when a tool is
# broken -- more room buys more attempts at something that will keep failing.
#
# BF-701 is the case. The agent asked the browser tool for ``key_type`` at step
# 2, was told ``unknown browser action: 'key_type'``, asked again at step 15,
# got the same answer, and burned the steps between on workarounds. It then
# filed a continue request, because that was the only verdict available. The
# diagnosis was sitting in its own results the whole time.
#
# Two occurrences is the threshold. Once is a transient -- a timeout, a race, a
# page that had not settled -- and retrying is the correct response. Twice is a
# pattern: the same tool answered the same way, and the agent already tried the
# obvious thing in between.
#
# The detection reads the outcome's OWN ``tool_calls``/``tool_results``, joined
# on request id. No classifier, no extra model call, no re-reading the persisted
# trace -- the same discipline as AD-1165 promoting on elapsed time. Evidence
# the turn already produced cannot be wrong about what it measures.
_DEFECT_MIN_OCCURRENCES: int = 2

_DEFECT_LEAD_WITH_WORK: str = (
    "I stopped here because the same call kept coming back the same way. The "
    "work above is partial and the task is still open."
)
_DEFECT_LEAD_NO_WORK: str = (
    "I stopped because the same call kept coming back the same way before I had "
    "anything to report. The task is still open."
)
_DEFECT_DETAIL: str = (
    " The {tool_id} tool answered {count} times with: {error}"
)
_DEFECT_TAIL_WITH_FAULT: str = (
    " I filed fault report {fault_id} so it gets looked at rather than retried."
)
_DEFECT_TAIL: str = (
    " Retrying looks like it would land in the same place."
)
# Bound on the error text quoted back to the Captain. The full text is on the
# fault report; the reply needs enough to recognise it, not all of it.
_DEFECT_ERROR_QUOTE_MAX: int = 200


def detect_tool_defect(outcome: Any) -> tuple[str, str, int] | None:
    """AD-1170: find a tool that failed the same way more than once.

    Returns ``(tool_id, error_text, count)`` for the most-repeated failing
    (tool, error) pair when it reaches the threshold, else ``None``.

    ``ToolCallResult`` carries the request id and the error text but not the
    tool name, and ``ToolCallRequest`` carries the id and the name -- so the two
    are joined on id. Both lists live on the outcome the caller already holds.

    Never raises: a malformed outcome yields ``None`` and the caller takes the
    ordinary step-limit path, which is exactly today's behaviour.
    """
    try:
        from probos.fault_report import normalise_error

        calls = getattr(outcome, "tool_calls", None) or []
        results = getattr(outcome, "tool_results", None) or []
        if not calls or not results:
            return None

        name_by_id: dict[str, str] = {}
        for call in calls:
            call_id = getattr(call, "id", None)
            name = getattr(call, "name", None)
            if type(call_id) is str and type(name) is str and name:
                name_by_id[call_id] = name

        # (tool, normalised error) -> [count, first raw error text]
        tally: dict[tuple[str, str], list[Any]] = {}
        for result in results:
            if getattr(result, "is_error", False) is not True:
                continue
            tool_id = name_by_id.get(getattr(result, "id", ""), "")
            if not tool_id:
                continue
            raw = getattr(result, "output", "")
            raw_text = raw if type(raw) is str else str(raw)
            key = (tool_id, normalise_error(raw_text))
            entry = tally.get(key)
            if entry is None:
                tally[key] = [1, raw_text]
            else:
                entry[0] += 1

        if not tally:
            return None
        (tool_id, _sig), (count, raw_text) = max(
            tally.items(), key=lambda kv: kv[1][0],
        )
        if count < _DEFECT_MIN_OCCURRENCES:
            return None
        return tool_id, raw_text, count
    except Exception:
        logger.debug(
            "AD-1170: defect detection raised; the turn takes the ordinary "
            "step-limit path", exc_info=True,
        )
        return None


async def file_fault_from_turn(
    runtime: Any,
    *,
    agent_id: str,
    thread_id: str,
    tool_id: str,
    error_text: str,
    attempted: str,
) -> str:
    """File an AD-1169 fault report for a defect this turn ran into.

    Returns the fault id, or ``""`` when there is nowhere to file. Never
    raises: a turn must finish even when the reporting channel is missing.
    """
    store = getattr(runtime, "fault_report_store", None)
    if store is None:
        return ""
    try:
        report = await store.file_fault(
            tool_id=tool_id,
            error_text=error_text,
            attempted=attempted,
            agent_id=agent_id,
            thread_id=thread_id,
        )
    except Exception:
        logger.warning(
            "AD-1170: could not file a fault report against %r for agent %s",
            tool_id, agent_id[:12], exc_info=True,
        )
        return ""
    fault_id = getattr(report, "id", "") if report is not None else ""
    return fault_id if type(fault_id) is str else ""


def _final_text(outcome: Any) -> str:
    """The outcome's reply text, defensively. Never raises, never strips.

    Stripping is left to the caller so that with the gate off this module hands
    back exactly the value ``_maybe_run_conversational_agentic`` read before
    AD-1164.
    """
    text = getattr(outcome, "final_text", "")
    return text if type(text) is str else ""


def _final_error_quote(error_text: Any) -> str:
    """One bounded line of the error, for quoting back to the Captain.

    The full text lives on the fault report; the reply needs only enough to be
    recognisable. Collapsed to a single line so a multi-line Playwright call log
    does not turn the chat reply into a stack trace.
    """
    flat = " ".join(str(error_text or "").split())
    if len(flat) <= _DEFECT_ERROR_QUOTE_MAX:
        return flat
    return flat[: _DEFECT_ERROR_QUOTE_MAX - 1].rstrip() + "\u2026"


def _is_cut_off(outcome: Any) -> bool:
    """True iff this outcome stopped for a reason AD-1155 classifies re-invokable.

    Today that set has exactly one member, ``max_iterations``. The membership
    test ADMITS rather than excludes (AD-1147/DD-1, AD-1153/DD-1), so a stop
    reason nobody has classified is treated as terminal and takes today's path.
    """
    reason = getattr(outcome, "stopped_reason", "")
    return type(reason) is str and reason in _REINVOKABLE_STOPPED_REASONS


def is_continue_or_ask_armed(config: Any) -> bool:
    """Whether ``dm_agentic.continue_or_ask_enabled`` is genuinely on.

    ``is True`` rather than ``bool(...)``, following AD-1155's
    ``_normalize_loop_until_done_enabled``: a truthy non-bool that reached this
    path by a route that skipped Pydantic (``model_copy(update=...)``, a
    synthetic runtime, a stub config) must not silently arm re-invocation.
    """
    return getattr(config, "continue_or_ask_enabled", False) is True


def resolve_continue_max_passes(value: Any) -> int:
    """Clamp the pass cap to ``[1, 5]``, never raise.

    ``type(...) is not int`` also rejects ``bool`` (``True`` is not a cap of 1).
    Mirrors the ``ge`` / ``le`` bounds on
    ``DmAgenticConfig.continue_or_ask_max_passes`` so a value that skipped
    validation degrades to the module default rather than failing the turn — the
    AD-1151 clamp-don't-validate rule, which exists because ``POST /config``
    round-trips the whole model through ``SystemConfig(**merged)``.
    """
    if type(value) is not int or not 1 <= value <= _MAX_CONTINUE_PASSES:
        return _CONTINUE_MAX_PASSES
    return value


def _task_excerpt(text: Any, limit: int = _MAX_EXCERPT_CHARS) -> str:
    """A single-line, bounded excerpt of the task, for the Captain's card."""
    if type(text) is not str:
        return ""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 1)].rstrip() + "\u2026"


def _display_task_text(display: Any, base: str) -> str:
    """BF-709: the Captain-facing text for a turn — the raw ask when there is one.

    ``base_task_text`` has two jobs that want opposite values. Re-invocation
    needs the FULLY ASSEMBLED prompt (working memory, episodic recall, session
    history, the AD-1055 visual-context block, the BF-294 confabulation guard),
    or a continued pass loses everything the first pass knew. A card title needs
    the RAW message, or the Captain reads scaffolding instead of the ask — which
    is what the seven live pending requests show.

    So the two are separated rather than reconciled: ``base`` keeps its job and
    ``display`` carries the ask, resolved at the arming site by
    ``cognitive_agent._promotion_request_text`` (imported nowhere here — that
    would invert the lazy import that reaches this module).

    Falls back to ``base`` for anything absent, non-``str`` or blank, so a
    caller that passes no display text gets byte-identical behaviour to before
    this parameter existed. ``strip()`` rather than truthiness because a
    whitespace-only message is not an ask.
    """
    if type(display) is str and display.strip():
        return display
    return base


def continue_payload(thread_id: Any) -> dict[str, Any]:
    """The AD-1154 six-key payload for a ``kind="continue"`` request.

    Exactly the six keys ``capability_request.validate_action_payload`` accepts,
    so the row survives a store restart with its payload intact instead of
    degrading to ``None`` on reload. ``params`` is empty: a turn's step budget
    has no arguments, and keeping it empty means the machine shape carries only
    what a future standing rule would be keyed on.
    """
    thread = thread_id if type(thread_id) is str else ""
    return {
        "tool_id": CONTINUE_TOOL_ID,
        "action": CONTINUE_ACTION,
        "params": {},
        "scope_key": CONTINUE_SCOPE_KEY,
        "session_id": None,
        "thread_id": thread[:_THREAD_ID_MAX],
    }


def _standing_rule_permits(runtime: Any, agent_id: str) -> bool:
    """Whether a live standing rule lets this agent continue. Fails CLOSED.

    An absent store, an older build without the method, or a raising cache read
    all return ``False``, which means "ask the Captain" — the direction that
    cannot manufacture authority out of a failure.
    """
    store = getattr(runtime, "action_approval_store", None)
    if store is None:
        return False
    try:
        return bool(
            store.is_approved_sync(
                agent_id, CONTINUE_TOOL_ID, CONTINUE_ACTION, CONTINUE_SCOPE_KEY
            )
        )
    except Exception:
        logger.warning(
            "AD-1164: reading the standing continue-rule for agent %s raised; "
            "treating it as absent, so the turn stops and the Captain is asked "
            "rather than the loop continuing on an unverified rule",
            agent_id[:12],
            exc_info=True,
        )
        return False


def _continuation_block(previous_output: str) -> str:
    """AD-1155's continuation block, composed for a conversational turn.

    ``todo_labels`` and ``completion_marker`` are ``None``: those two predicates
    are crew-specific (a checklist on a ``WorkItem``, an operator-chosen marker
    string) and have no counterpart in a 1:1 chat turn, where the only signal is
    the stop reason itself.

    Returns ``""`` when nothing useful composes, which the caller reads as "stop
    the loop" — never as a failure.
    """
    try:
        return _render_continuation(
            previous_output=previous_output,
            todo_labels=None,
            completion_marker=None,
        )
    except Exception:
        logger.warning(
            "AD-1164: composing the continuation block raised; the turn stops "
            "and the partial work is reported as-is",
            exc_info=True,
        )
        return ""


async def file_continue_request(
    runtime: Any,
    *,
    agent_id: str,
    thread_id: str,
    base_task_text: str,
    passes: int,
    display_task_text: str = "",
    work_item_id: str | None = None,
) -> str:
    """File the ``kind="continue"`` ask. Returns its id, or ``""`` on any failure.

    The Captain's card renders ``kind``, ``target`` and ``rationale`` and does
    NOT render ``payload``, so the human-readable context lives in ``target``
    (what was being worked on) and ``rationale`` (why it stopped). The payload
    carries the machine shape a standing rule would be keyed on.

    BF-709: ``target`` is excerpted from ``display_task_text`` when the caller
    supplies one, because ``base_task_text`` is the assembled prompt and reads
    as scaffolding on a card. Omitted or blank falls back to ``base_task_text``
    — today's title exactly. See :func:`_display_task_text`.

    AD-1204: ``work_item_id`` is the AD-1165 item this turn was promoted to,
    and it is what makes an approval able to DO something. Without it
    ``CapabilityGapDriver.on_capability_event`` recovers ``req.work_item_id``,
    finds ``None``, and logs "nothing to resume" — which is what four live
    approvals bought on 2026-08-04. With it, the ask is linked AND the item is
    parked ``blocked``, so the same driver that has always handled
    BLOCKED -> approve -> resume handles this too.

    ``None`` (a turn that finished under the promotion budget, so there is no
    item) files exactly the request this function filed before this AD, and
    parks nothing.

    Never raises. A missing store or a failed write logs at WARNING and yields
    ``""``; the caller then reports the partial work with the no-id note. Losing
    the ask is strictly better than losing the turn.
    """
    store = getattr(runtime, "capability_request_store", None)
    if store is None:
        logger.warning(
            "AD-1164: no capability-request store is wired, so the cut-off turn "
            "for agent %s could not be filed; the partial work is still "
            "returned and the Captain is told it stopped mid-task",
            agent_id[:12],
        )
        return ""
    excerpt = _task_excerpt(_display_task_text(display_task_text, base_task_text))
    target = f"continue: {excerpt}" if excerpt else "continue"
    try:
        request = await store.file_request(
            agent_id=agent_id,
            kind=CONTINUE_REQUEST_KIND,
            target=target,
            rationale=_CONTINUE_RATIONALE.format(passes=passes),
            work_item_id=work_item_id,
            payload=continue_payload(thread_id),
        )
    except Exception:
        logger.warning(
            "AD-1164: filing the continue request for agent %s failed; the "
            "partial work is still returned and the Captain is told it stopped "
            "mid-task",
            agent_id[:12],
            exc_info=True,
        )
        return ""
    request_id = getattr(request, "id", "") if request is not None else ""
    if type(request_id) is not str or not request_id:
        return ""
    if work_item_id:
        await _park_work_item(
            runtime, work_item_id=work_item_id, request_id=request_id
        )
    logger.info(
        "AD-1164: conversational turn for agent %s stopped at its step limit "
        "after %d pass(es); filed continue request %s and returned the partial "
        "work with an explicit cut-off statement",
        agent_id[:12],
        passes,
        request_id[:12],
    )
    return request_id


async def _park_work_item(
    runtime: Any, *, work_item_id: str, request_id: str
) -> bool:
    """AD-1204: mark the promoted item ``blocked`` on the ask that stopped it.

    Delegates to ``CapabilityGapDriver.block_on_request`` rather than touching
    the work-item store here, so ``blocked_reason`` / ``capability_request_id``
    keep exactly one writer — the driver that reads them back when the request
    resolves. Without the transition the item stays ``in_progress`` and the
    driver's idempotency guard (``if item.status != "blocked": return``) makes
    even a correctly linked approval a no-op.

    Returns whether the board was updated. Never raises: an absent driver, an
    illegal transition or a store failure all leave the ask filed and the
    partial work returned, which is this module's one permitted direction of
    failure.
    """
    driver = getattr(runtime, "capability_gap_driver", None)
    if driver is None:
        logger.warning(
            "AD-1204: no capability-gap driver is wired, so work item %s stays "
            "in_progress while continue request %s waits; approving it will "
            "record the decision but will not resume the turn",
            work_item_id, request_id[:12],
        )
        return False
    try:
        parked = bool(
            await driver.block_on_request(
                work_item_id=work_item_id,
                request_id=request_id,
                reason=_BLOCKED_REASON,
            )
        )
    except Exception:
        logger.warning(
            "AD-1204: parking work item %s on continue request %s raised; the "
            "ask stands and the partial work is still returned, but approving "
            "it will not resume the turn",
            work_item_id, request_id[:12], exc_info=True,
        )
        return False
    if parked:
        logger.info(
            "AD-1204: work item %s parked blocked on continue request %s; an "
            "approval now resumes and re-dispatches it",
            work_item_id, request_id[:12],
        )
    return parked


async def resolve_exhausted_turn(
    outcome: Any,
    *,
    reinvoke: Callable[[str], Awaitable[Any]],
    runtime: Any,
    agent_id: str,
    base_task_text: str,
    thread_id: str = "",
    display_task_text: str = "",
    work_item_id: str | None = None,
    config: Any,
) -> str:
    """Turn a step-limit stop into a continuation or an honest, durable ask.

    Returns the reply text for the turn. ``reinvoke`` is a caller-supplied
    coroutine that runs the agentic loop again with a new ``task_text`` and
    returns a fresh outcome — dependency inversion, so this module never
    constructs an executor and the five other callers of
    ``WorkItemAgenticExecutor.run`` are untouched by construction rather than by
    flag (the AD-1155 seam argument, applied one layer up).

    BF-709: ``base_task_text`` is the ASSEMBLED prompt and stays that way —
    every re-invocation below is built from it, and a pass that continued from
    the raw message alone would lose working memory, episodic recall and session
    history. ``display_task_text`` is the Captain's raw ask, used at the two
    Captain-facing sites (the fault report's ``attempted``, the filed request's
    ``target``) and nowhere else. Omitted or blank falls back to
    ``base_task_text``, so an older caller's behaviour is unchanged.
    AD-1204: ``work_item_id`` is the AD-1165 work item this turn was promoted
    to, if it was. Supplied, the filed ask is LINKED to it and the item is
    parked ``blocked``, so approving the ask resumes and re-dispatches the item
    through the driver that has always done that. Omitted or ``None`` — a turn
    that finished inside the promotion budget, so there is no item — the ask is
    filed exactly as before and nothing is parked.
    The order of the gates is load-bearing:

    1. Gate off  ⇒ return the outcome's text unchanged.
    2. Stop reason is not re-invokable ⇒ return unchanged. ``token_budget`` is
       an operator's spend ceiling, ``error`` is usually window exhaustion that
       a longer prompt makes worse, and ``complete`` means the model chose to
       stop. None of those is the failure this AD addresses, and none of them
       files an ask.
    3. While under the cap AND a standing rule permits it, re-invoke with the
       continuation block appended to the ORIGINAL task text — rebuilt from the
       base every pass, so the block cannot stack.
    4. Still cut off ⇒ file exactly ONE ask and return the partial work with an
       explicit statement that it stopped mid-task.

    Every pass is an independently governed run: ``reinvoke`` calls back into the
    executor, which rebuilds its tool executor, re-resolves department and rank
    through live trust, and re-runs every permission gate. An agent whose trust
    falls between passes therefore loses tools on the next one, which is Minimal
    Authority working correctly.
    """
    text = _final_text(outcome)
    if not is_continue_or_ask_armed(config):
        return text
    if not _is_cut_off(outcome):
        return text

    max_passes = resolve_continue_max_passes(
        getattr(config, "continue_or_ask_max_passes", None)
    )
    current = outcome
    passes = 1

    while passes < max_passes:
        if not _standing_rule_permits(runtime, agent_id):
            logger.info(
                "AD-1164: agent %s reached its step limit on pass %d/%d and no "
                "standing rule covers continuation, so the turn stops and the "
                "Captain is asked",
                agent_id[:12],
                passes,
                max_passes,
            )
            break
        block = _continuation_block(_final_text(current))
        if not block:
            break
        try:
            nxt = await reinvoke(base_task_text + block)
        except Exception:
            logger.warning(
                "AD-1164: re-invoking the conversational loop for agent %s "
                "after pass %d raised; the turn stops and the last real "
                "outcome is reported",
                agent_id[:12],
                passes,
                exc_info=True,
            )
            break
        if nxt is None:
            break
        current = nxt
        passes += 1
        logger.info(
            "AD-1164: re-invoked the conversational loop for agent %s under a "
            "standing rule (pass %d/%d, +%d continuation characters)",
            agent_id[:12],
            passes,
            max_passes,
            len(block),
        )
        if not _is_cut_off(current):
            return _final_text(current)

    # Every exit from the loop above leaves ``current`` cut off: the only
    # assignment to it is followed immediately by the completion check, and both
    # early breaks happen before the assignment. So there is no "finished after
    # all" case to re-test here.
    if passes >= max_passes:
        logger.info(
            "AD-1164: agent %s is still at its step limit after %d/%d pass(es); "
            "the cap binds, so the turn stops and the Captain is asked",
            agent_id[:12],
            passes,
            max_passes,
        )

    partial = _final_text(current).rstrip()

    # AD-1170: before asking whether to keep going, ask whether going on would
    # help. A tool that answered the same way twice will answer that way again.
    defect = detect_tool_defect(current)
    if defect is not None:
        tool_id, error_text, count = defect
        fault_id = await file_fault_from_turn(
            runtime,
            agent_id=agent_id,
            thread_id=thread_id,
            tool_id=tool_id,
            error_text=error_text,
            attempted=_display_task_text(display_task_text, base_task_text),
        )
        logger.info(
            "AD-1170: agent %s stopped against a repeated failure of tool %r "
            "(%d occurrences); filed fault %s instead of a continue request",
            agent_id[:12], tool_id, count, fault_id[:12] or "<none>",
        )
        lead = _DEFECT_LEAD_WITH_WORK if partial else _DEFECT_LEAD_NO_WORK
        detail = _DEFECT_DETAIL.format(
            tool_id=tool_id,
            count=count,
            error=_final_error_quote(error_text),
        )
        tail = (
            _DEFECT_TAIL_WITH_FAULT.format(fault_id=fault_id)
            if fault_id else _DEFECT_TAIL
        )
        note = lead + detail + tail
        return partial + _CUT_OFF_SEPARATOR + note if partial else note

    request_id = await file_continue_request(
        runtime,
        agent_id=agent_id,
        thread_id=thread_id,
        base_task_text=base_task_text,
        passes=passes,
        display_task_text=display_task_text,
        work_item_id=work_item_id,
    )
    lead = _CUT_OFF_LEAD_WITH_WORK if partial else _CUT_OFF_LEAD_NO_WORK
    tail = (
        _CUT_OFF_TAIL_WITH_REQUEST.format(request_id=request_id)
        if request_id
        else _CUT_OFF_TAIL
    )
    note = lead + tail
    return partial + _CUT_OFF_SEPARATOR + note if partial else note
