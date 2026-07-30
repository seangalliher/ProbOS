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


def _final_text(outcome: Any) -> str:
    """The outcome's reply text, defensively. Never raises, never strips.

    Stripping is left to the caller so that with the gate off this module hands
    back exactly the value ``_maybe_run_conversational_agentic`` read before
    AD-1164.
    """
    text = getattr(outcome, "final_text", "")
    return text if type(text) is str else ""


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
) -> str:
    """File the ``kind="continue"`` ask. Returns its id, or ``""`` on any failure.

    The Captain's card renders ``kind``, ``target`` and ``rationale`` and does
    NOT render ``payload``, so the human-readable context lives in ``target``
    (what was being worked on) and ``rationale`` (why it stopped). The payload
    carries the machine shape a standing rule would be keyed on.

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
    excerpt = _task_excerpt(base_task_text)
    target = f"continue: {excerpt}" if excerpt else "continue"
    try:
        request = await store.file_request(
            agent_id=agent_id,
            kind=CONTINUE_REQUEST_KIND,
            target=target,
            rationale=_CONTINUE_RATIONALE.format(passes=passes),
            work_item_id=None,
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
    logger.info(
        "AD-1164: conversational turn for agent %s stopped at its step limit "
        "after %d pass(es); filed continue request %s and returned the partial "
        "work with an explicit cut-off statement",
        agent_id[:12],
        passes,
        request_id[:12],
    )
    return request_id


async def resolve_exhausted_turn(
    outcome: Any,
    *,
    reinvoke: Callable[[str], Awaitable[Any]],
    runtime: Any,
    agent_id: str,
    base_task_text: str,
    thread_id: str = "",
    config: Any,
) -> str:
    """Turn a step-limit stop into a continuation or an honest, durable ask.

    Returns the reply text for the turn. ``reinvoke`` is a caller-supplied
    coroutine that runs the agentic loop again with a new ``task_text`` and
    returns a fresh outcome — dependency inversion, so this module never
    constructs an executor and the five other callers of
    ``WorkItemAgenticExecutor.run`` are untouched by construction rather than by
    flag (the AD-1155 seam argument, applied one layer up).

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

    request_id = await file_continue_request(
        runtime,
        agent_id=agent_id,
        thread_id=thread_id,
        base_task_text=base_task_text,
        passes=passes,
    )
    partial = _final_text(current).rstrip()
    lead = _CUT_OFF_LEAD_WITH_WORK if partial else _CUT_OFF_LEAD_NO_WORK
    tail = (
        _CUT_OFF_TAIL_WITH_REQUEST.format(request_id=request_id)
        if request_id
        else _CUT_OFF_TAIL
    )
    note = lead + tail
    return partial + _CUT_OFF_SEPARATOR + note if partial else note
