"""AD-859: Crew fan-out executor.

Given a parent work item already decomposed into child sub-tasks by the
:class:`ParallelDispatcher`, :class:`CrewTaskExecutor` drives those children to
completion. It owns its **own** ``depends_on``-gated topological scheduling (the
``WorkItemRouter`` is fire-and-forget and exposes no readiness helper — verified
at HEAD), launches each runnable child through the reusable AD-859a
:class:`WorkItemAgenticExecutor` (awaited directly), and collects a
:class:`SubtaskResult` per child carrying durable provenance (the persistent
agent identity and a content-addressable tool-trace ref — never inline bytes).

Boundaries (Safety Budget / Minimal Authority):
  * Concurrency is bounded by ``AgenticDispatchConfig.max_parallel_subtasks`` so
    a wide fan-out cannot exhaust the LLM tier.
  * A failed child surfaces its status in its ``SubtaskResult`` but does NOT
    abort siblings and does NOT unblock its dependents (it never reaches
    ``done`` in the store, so the dependency gate keeps the dependents waiting).
  * A failed child is never silently transitioned to ``done``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Callable

from probos.crew_utils import CREW_EXECUTION_KEYS, is_crew_agent
from probos.events import EventType

if TYPE_CHECKING:
    from probos.attachments.store import AttachmentStore
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.cognitive.crew_session import CrewSessionService
    from probos.substrate.registry import AgentRegistry
    from probos.threads import ChatThread
    from probos.workforce import WorkItem, WorkItemStore

logger = logging.getLogger(__name__)

# A child whose agentic run stops with this reason is treated as a success and
# transitioned to ``done``; every other reason (max_iterations / token_budget /
# error) surfaces as a non-``done`` status that does not unblock dependents.
_SUCCESS_STOPPED_REASON = "complete"
_STOPPED_REASONS = frozenset(
    {
        "complete",
        "error",
        "max_iterations",
        "token_budget",
        "execution_exception",
        "unassigned",
        "agent_unresolvable",
        "dependency_blocked",
        "start_transition_failed",
    }
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_REF_KEYS = frozenset(
    {
        "artifact_id",
        "content_hash",
        "thread_id",
        "name",
        "mime",
        "size_bytes",
        "version",
    }
)
_MAX_ACTUAL_TOKENS = 9_223_372_036_854_775_807
_MAX_EVIDENCE_BYTES = 32_768
_MAX_OUTPUT_SUMMARY_CHARS = 4_096
_MAX_DEPENDENCY_IDS = 64
_MAX_OUTPUT_BYTES = 1_048_576
_SUMMARY_TRUNCATION_MARKER = "...[truncated]"

# ── AD-1141: Σ (commons) context injected into a crew child's task text ──────
#
# DD-1: the injection point is ``task_text``, not ``extra_context``.
# ``extra_context`` is the *tool-invocation* context — ``AgenticLoop`` builds
# ``messages`` from ``system_prompt`` + ``user_message`` only, so a payload
# placed in ``extra_context`` reaches tools and never reaches the model.
# ``task_text`` becomes ``user_message`` and is **never persisted**: the durable
# value is ``WorkItem.description``, which is inside the plan-identity hash and
# which this module does not touch.
#
# DD-10 bounds. Deliberately smaller than ``oracle_query``'s 6000-char budget:
# that budget is for a lookup the agent *asked for*, while this injection is
# unrequested and is paid on every child whether or not it helps.
_MIN_CONSULT_QUERY_CHARS = 24
_MAX_CONSULT_QUERY_CHARS = 512
_MAX_ENTRY_CHARS = 400
_MAX_EXPECTED_OUTPUT_CHARS = 1000
_CONSULT_K_PER_TIER = 3
_ENTRY_ELISION = " ...[entry shortened]"

# DD-4: framing travels inline. ``AgenticLoop`` renders a bare user message and
# has no consumer-side wrapper, so anything unframed "just appears" to the
# agent. Every string below is asserted against the real imported
# ``decomposer._CAPABILITY_GAP_RE`` in tests — ``lack`` is a bare substring in
# that pattern, so "black hole" and "slack" trip it.
_COMMONS_HEADER = "## What the ship already knows about this"

_COMMONS_DISPOSITION: str = (
    "(These entries come from the ship's shared knowledge stores — work other "
    "crew recorded in earlier sessions. Treat them as reference material "
    "rather than as something you lived through. Each entry carries its source "
    "tier, a confidence score and an age, so weigh a low-confidence or STALE "
    "entry lightly. Build on an entry and cite it; otherwise do not narrate "
    "this consultation.)"
)

_EXPECTED_OUTPUT_HEADER = "## What this subtask will be judged against"

_EXPECTED_OUTPUT_DISPOSITION: str = (
    "(This is the acceptance criterion the verifier applies to your output. "
    "Meet it directly.)"
)

_PUBLISH_NUDGE: str = (
    "(If this subtask produces a durable finding that a different crew member "
    "would want in a later session, record it with the publish_finding tool "
    "before you finish. Publish a conclusion with its basis, not a status "
    "update.)"
)

_BUDGET_NOTE: str = (
    "(Some commons entries were held back to stay inside this subtask's "
    "context budget.)"
)

# DD-3: defined so a later AD does not re-derive the wording, and asserted
# clean — but **never emitted by this AD**. AD-1139's empty body exists because
# an agent that *asked* deserves an answer; a crew child never asked, so
# telling it the commons was silent is pure overhead on the majority path.
_EMPTY_CONSULT_NOTE: str = (
    "(The ship's shared knowledge stores returned nothing above the relevance "
    "bar for this subtask. Work from the task itself.)"
)

# ── AD-1142: crew-child working-context compaction + spend ceiling ──────────
#
# WHY THIS EXISTS — context-window economics, and nothing else.
#
# A crew child's working context is unbounded. ``max_iterations`` (25) bounds
# TURNS, not bytes; ``agentic_loop.tool_result_max_chars`` ships at 0, so each
# tool result is unbounded; and AD-1147 lets ONE turn carry up to
# ``max_parallel_tool_calls`` results (default 3, ceiling 16). Twenty-four
# turns of unbounded ``read_page`` / ``http_fetch`` output exhaust any provider
# window, at which point ``llm_client.complete()`` raises and the loop returns
# ``stopped_reason="error"`` — the child fails, its dependents stay blocked,
# and the failure reads as an LLM error rather than as a design gap.
# Compaction bounds the working context. That is the whole claim.
#
# IT IS NOT A TRANSPARENCY MECHANISM AND DOES NOT CLAIM TO BE ONE. What
# compaction can drop from ``messages``, and what actually retains it:
#
#   role:"tool" content (tool outputs)   PARTIALLY — AD-1151 ``_persist_tool_trace``,
#                                        bounded by tool_trace_output_max_chars
#                                        (8192/output) and tool_trace_max_bytes
#                                        (256 KiB/blob)
#   assistant reasoning text             NOWHERE
#   assistant.tool_calls as the model    id / name / arguments only
#     saw it
#   the flattened prompt actually sent   NOWHERE
#   the compaction summary itself        NOWHERE
#   the original user task after a       NOWHERE (the AD-1142 Defect A fix keeps
#     second compaction pass             it IN the working context instead)
#
# The durable trace is not a superset of the transcript either:
# ``tool_result_max_chars`` ships at 0 (unbounded transcript) and
# ``resolve_tool_trace_bounds`` only clamps the durable cap UP to a NON-ZERO
# context cap, so on shipped defaults the trace records LESS than the model
# saw. Any wording that credits the durable trace with what compaction drops is
# wrong; this AD stands on context-window economics alone.
#
# Two knobs, two different mechanisms:
#   crew_compaction_threshold_tokens — working-context ceiling. Cross it =>
#       shrink and continue. Compaction does NOT grant extra iterations, so it
#       cannot turn a ``max_iterations`` stop into a completion; it addresses
#       window exhaustion (``stopped_reason="error"``) only.
#   crew_token_budget — cumulative-spend ceiling. Cross it => stop, with
#       ``stopped_reason="token_budget"`` mapping to ``status="failed"``, so
#       dependents stay blocked. That is why it defaults to None.
_CREW_COMPACTION_THRESHOLD_TOKENS = 60_000
_MIN_CREW_TOKEN_BUDGET = 1024

# ── AD-1155: loop-until-done — an outer completion evaluator ────────────────
#
# READ THIS BEFORE ADDING A THIRD OUTER LOOP. **One already exists.**
# ``SubtaskVerifier.converge_for_session`` (``crew_verifier.py:1301``) is a
# complete, governed, bounded outer loop over ``WorkItemAgenticExecutor.run``,
# called from ``crew_finalizer.py`` on the LIVE crew-session path. It re-invokes
# with an LLM-judge critique for up to ``min(max_convergence_rounds, 8)`` rounds.
# This AD does NOT replace it and does NOT touch it.
#
# The gap it leaves is narrow and deterministic: its only predicate is that
# judge, and ``_classify_correction_terminal`` routes ``max_iterations`` into
# ``correction_execution_defect`` — so a child cut off mid-work BY A COUNTER is
# recorded as a defect rather than as unfinished work. This AD adds a cheap
# deterministic predicate and a ``max_iterations`` continuation at the fan-out
# seam, and nothing else.
#
# It wraps ``CrewTaskExecutor._run_child``, NOT ``WorkItemAgenticExecutor.run``.
# ``.run`` has six call sites, including the AD-839 conversational path and the
# AD-1072 delegation path — both of which have a HUMAN present who can say
# "keep going" — and ``converge_for_session`` itself. Wrapping ``.run`` would
# nest this loop inside those correction rounds, multiplying convergence x outer
# x inner x parallel. Wrapping here makes every other caller byte-identical **by
# construction rather than by flag**.
#
# Fail-safe direction, following AD-1147/DD-1 (``PARALLEL_SAFE_TOOL_IDS``) and
# AD-1153/DD-1 (``_BROWSER_LOOP_ACTIONS``): membership sets ADMIT, they do not
# EXCLUDE. A stop reason that nobody has classified is not re-invoked.
_REINVOKABLE_STOPPED_REASONS = frozenset({"max_iterations"})

# Predicate ids. A config ENUM STRING, never an operator-supplied callable — a
# callable knob here would be an arbitrary-code seam on the crew hot path.
_LOOP_PREDICATE_STOP_REASON = "stopped_reason"
_LOOP_PREDICATE_COMPLETION_MARKER = "completion_marker"
_LOOP_PREDICATE_OPEN_TODOS = "open_todos"
_LOOP_PREDICATES = frozenset(
    {
        _LOOP_PREDICATE_STOP_REASON,
        _LOOP_PREDICATE_COMPLETION_MARKER,
        _LOOP_PREDICATE_OPEN_TODOS,
    }
)

_LOOP_UNTIL_DONE_MAX_ITERATIONS = 2
_MAX_LOOP_UNTIL_DONE_ITERATIONS = 5
_DEFAULT_COMPLETION_MARKER = "TASK COMPLETE"
_MAX_COMPLETION_MARKER_CHARS = 120
_COMPLETION_MARKER_TAIL_CHARS = 200

# ``open_todos`` step statuses that a re-invoked child can actually MOVE.
# ``submitted`` is deliberately absent: ``_apply_room_todos`` gates
# ``submitted -> done`` on rank >= ``communications.room_todos_min_rank``
# (default ``commander`` => trust >= 0.7), and built-in agents seed at
# Beta(2,2) = 0.50 => ``lieutenant``. The modal crew agent is structurally
# incapable of closing its own submitted step, so counting it as open would
# guarantee futile re-invocation. ``done`` is excluded for the obvious reason.
_ACTIONABLE_STEP_STATUSES = frozenset({"pending", "in_progress", "rejected"})

_MAX_CONTINUATION_CHARS = 3_000
_MAX_CONTINUATION_OUTPUT_CHARS = 2_000
_MAX_CONTINUATION_TODOS = 20
_MAX_CONTINUATION_TODO_CHARS = 120

# DD-4: every string below is asserted clean against the REAL imported
# ``decomposer._CAPABILITY_GAP_RE``. The natural English for "you didn't
# finish" is a minefield there — "you were unable to complete" trips it twice,
# and ``lack`` is a bare substring, so "slack" and "black hole" trip it too.
_CONTINUATION_HEADER = "## Continue this task"

_CONTINUATION_STOP_REASON_NOTE: str = (
    "You reached this task's turn limit before finishing. Continue from where "
    "you stopped. Your previous output is below — build on it, do not start "
    "over."
)

_CONTINUATION_OUTPUT_HEADER = "## What you produced on the previous pass"

_CONTINUATION_OUTPUT_ELISION = (
    "\n... [truncated: {omitted} characters elided from your previous output.] ...\n"
)

_CONTINUATION_TODO_HEADER = "## Checklist items still open"

_CONTINUATION_MARKER_INSTRUCTION: str = (
    "When the task is genuinely finished, end your final message with the "
    "exact line: {marker}"
)


def _normalize_loop_until_done_enabled(value: Any) -> bool:
    """Clamp the AD-1155 gate, never raise (the DD-8 / DD-10 convention).

    ``is True`` rather than ``bool(...)``: a truthy non-bool that reached this
    executor by a route that skipped Pydantic (``model_copy(update=...)``, a
    synthetic runtime, a stub config) must NOT silently arm re-invocation.
    """
    return value is True


def _normalize_loop_until_done_max_iterations(value: Any) -> int:
    """Clamp the outer cap to ``[1, 5]``, never raise.

    ``type(...) is not int`` also rejects ``bool`` (``True`` is not an outer
    cap of 1). Mirrors the ``ge``/``le`` bounds on
    ``AgenticDispatchConfig.crew_loop_until_done_max_iterations`` so a value
    that skipped validation degrades to the module default rather than failing
    every child.
    """
    if type(value) is not int or not (
        1 <= value <= _MAX_LOOP_UNTIL_DONE_ITERATIONS
    ):
        return _LOOP_UNTIL_DONE_MAX_ITERATIONS
    return value


def _normalize_loop_until_done_predicate(value: Any) -> str:
    """Clamp the predicate id to a known member, never raise.

    An unknown id degrades to ``stopped_reason`` — the only predicate whose
    signal is unambiguous — rather than to the opt-in ``open_todos``, whose
    inapplicability guard exists precisely because it is wrong for most
    children (C-2).
    """
    if type(value) is not str or value not in _LOOP_PREDICATES:
        return _LOOP_PREDICATE_STOP_REASON
    return value


def _normalize_completion_marker(value: Any) -> str:
    """Clamp the completion marker, never raise.

    Empty/malformed degrades to the module default rather than to ``""``: an
    empty marker is contained in every string, so it would make the
    ``completion_marker`` predicate stop unconditionally and silently disable
    the feature the operator just armed.
    """
    if type(value) is not str:
        return _DEFAULT_COMPLETION_MARKER
    marker = value.strip()
    if not marker:
        return _DEFAULT_COMPLETION_MARKER
    return marker[:_MAX_COMPLETION_MARKER_CHARS]


def _normalize_compaction_threshold(value: Any) -> int:
    """Clamp the working-context ceiling, never raise (DD-8 / DD-10).

    ``type(...) is int`` also rejects ``bool``, matching
    ``resolve_tool_result_bounds``. Mirrors the ``ge``/``le`` bounds on
    ``AgenticDispatchConfig.crew_compaction_threshold_tokens`` so a value that
    reached this executor by a route that skipped Pydantic validation
    (``model_copy(update=...)``, a synthetic runtime, a stub config) degrades to
    the module default rather than failing every child.
    """
    if type(value) is not int or not (1_000 <= value <= 1_000_000):
        return _CREW_COMPACTION_THRESHOLD_TOKENS
    return value


def _normalize_token_budget(value: Any) -> int | None:
    """Clamp the cumulative-spend ceiling to ``None`` or a valid int.

    ``None`` means *no budget*, which is today's behaviour, so a malformed
    value degrades to ``None`` rather than to a number: silently inventing a
    spend ceiling would fail children that succeed today.
    """
    if value is None or type(value) is not int or value < _MIN_CREW_TOKEN_BUDGET:
        return None
    return value


def resolve_crew_compaction_settings(cfg: Any) -> dict[str, Any]:
    """AD-1142 / DD-8: the compaction kwargs for ONE crew child.

    Returns exactly the ``{compactor, compaction_threshold, token_budget}``
    keyword subset :class:`WorkItemAgenticExecutor` forwards to
    :class:`AgenticLoop`, in that order, omitting every key that is not
    configured — so with the gate off and no budget it returns ``{}`` and the
    child's ``_loop_kwargs`` is byte-identical to pre-AD-1142.

    A clamp, never a validator (the AD-1151 ``resolve_tool_trace_bounds``
    precedent). ``routers/config.py`` writes config by ``model_dump()`` ->
    ``_deep_merge`` -> ``SystemConfig(**merged)``, which marks every field
    explicitly set, so a raise here would turn an unrelated ``POST /config``
    into a 422 and could then persist a combination that refuses to boot;
    ``model_copy(update=...)`` skips validators outright. **This function must
    not raise** — a crew child must never fail because a compaction knob was
    mistyped.

    DD-2 — a **fresh** :class:`SessionCompactor` per call, so callers get one
    per child. ``SessionCompactor`` is stateless at HEAD, but that is an
    accident of the current implementation rather than a declared contract, and
    crew children run concurrently under ``asyncio.Semaphore(max_parallel)``.
    Any future instance state on it would become a silent cross-child race with
    no test to catch it, so the instance is never shared.

    DD-7 — ``crew_token_budget`` is deliberately NOT gated on
    ``crew_compaction_enabled``. They are independent mechanisms, and gating the
    budget on the compaction flag would mean enabling compaction silently
    introduced a new failure mode.
    """
    from probos.cognitive.swe_harness.session_compactor import SessionCompactor

    settings: dict[str, Any] = {}
    if getattr(cfg, "crew_compaction_enabled", False) is True:
        settings["compactor"] = SessionCompactor()
        settings["compaction_threshold"] = _normalize_compaction_threshold(
            getattr(cfg, "crew_compaction_threshold_tokens", None)
        )
    budget = _normalize_token_budget(getattr(cfg, "crew_token_budget", None))
    if budget is not None:
        settings["token_budget"] = budget
    return settings


# ── AD-1155: predicates, progress detection and the continuation block ──────

def _actionable_step_labels(steps: Any, *, child_id: str = "") -> list[str] | None:
    """AD-1155 / DD-2: the labels of the steps a re-invoked child could MOVE.

    Returns ``None`` — meaning **inapplicable, therefore stop** — for every
    shape this predicate cannot reason about: a non-list, an EMPTY list, a
    non-dict member, or a member whose ``status`` is outside
    :data:`workforce.STEP_STATUSES`. Returns a possibly-empty list otherwise.

    **The empty-list case is the load-bearing one.** ``workforce._all_steps_done``
    is ``bool(steps) and all(...)``, so the literal ``not _all_steps_done(steps)``
    is ``True`` for an empty checklist — and the crew fan-out NEVER writes
    ``WorkItem.steps`` (steps move through the ``[TODO_*]`` tags of the DM reply
    pipeline, which a crew child never enters). Treating "no checklist" as
    "unfinished" would re-invoke every crew child to the cap, always. Hence
    ``None``, and hence this function rather than a call to ``_all_steps_done``,
    whose empty-list semantics are correct for its own single caller and wrong
    here.

    Pure apart from a WARNING on the malformed paths; never raises (DD-8).
    """
    from probos.workforce import STEP_STATUSES

    if type(steps) is not list:
        if steps is not None:
            logger.warning(
                "AD-1155: crew child %s has a non-list steps value (%s); the "
                "open_todos predicate is inapplicable, so the outer loop stops "
                "rather than re-invoking on an unreadable checklist",
                child_id,
                type(steps).__name__,
            )
        return None
    if not steps:
        return None
    labels: list[str] = []
    for step in steps:
        if type(step) is not dict:
            logger.warning(
                "AD-1155: crew child %s has a non-dict checklist step (%s); the "
                "open_todos predicate is inapplicable, so the outer loop stops",
                child_id,
                type(step).__name__,
            )
            return None
        status = str(step.get("status", "pending"))
        if status not in STEP_STATUSES:
            logger.warning(
                "AD-1155: crew child %s has a checklist step with an unknown "
                "status %r; the open_todos predicate is inapplicable, so the "
                "outer loop stops rather than guessing at the state machine",
                child_id,
                status,
            )
            return None
        if status in _ACTIONABLE_STEP_STATUSES:
            label = step.get("label")
            labels.append(label if type(label) is str else "")
    return labels


def _iteration_made_progress(
    outcome: Any,
    *,
    previous_text_hash: str | None,
    previous_actionable_count: int | None,
    actionable_count: int | None,
) -> bool:
    """AD-1155 / DD-5: did this iteration achieve anything measurable?

    An iteration made NO progress iff it produced no artifacts, its
    ``final_text`` hashes identically to the previous iteration's, and — when
    ``open_todos`` is armed and applicable — its actionable-step count did not
    fall.

    **This is a backstop against the pathological case, not a general
    early-exit, and it is weak on purpose.** Byte-identical ``final_text``
    across two LLM calls at non-zero temperature is rare, so the artifact clause
    carries almost all the weight, and a task whose output is prose rather than
    a file will rarely trip it at all. The DD-3 cap is the real bound. A
    semantic-similarity check would be stronger and is deliberately rejected: it
    is an LLM call per iteration, which is DD-2's rejected AI-judge cost wearing
    a different hat.
    """
    if getattr(outcome, "artifact_refs", None):
        return True
    if previous_text_hash is None:
        return True
    if _text_hash(getattr(outcome, "final_text", "") or "") != previous_text_hash:
        return True
    if (
        actionable_count is not None
        and previous_actionable_count is not None
        and actionable_count < previous_actionable_count
    ):
        return True
    return False


def _text_hash(text: Any) -> str:
    """SHA-256 of ``text``, used only to compare two iterations' final output."""
    if type(text) is not str:
        text = ""
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _bounded_spend(value: Any) -> int:
    """AD-1155 / DD-3: one iteration's token spend, clamped and NEVER raising.

    Deliberately not :func:`_normalize_tokens`, which raises: this runs inside
    the ``_run_child`` try that persists ``stopped_reason="execution_exception"``,
    so a malformed ``total_tokens`` must degrade the budget arithmetic (to 0,
    the conservative direction — it can only cause MORE re-invocation to be
    permitted, which the DD-3 cap still bounds) rather than fail the child.
    """
    if type(value) is not int or not 0 <= value <= _MAX_ACTUAL_TOKENS:
        return 0
    return value


def _should_continue(
    outcome: Any,
    *,
    iteration: int,
    max_iterations: int,
    predicate: str,
    completion_marker: str,
    no_progress_streak: int,
    actionable_labels: list[str] | None,
) -> tuple[bool, str]:
    """AD-1155 / DD-2 + DD-5 + DD-6: continue the outer loop, or stop and why.

    Pure dispatch over the module predicate ids; returns ``(continue, reason)``
    where ``reason`` is a short log token, never surfaced to the agent.

    ``iteration`` is 1-based and counts the run that just finished.
    ``actionable_labels`` is :func:`_actionable_step_labels`' output, which the
    caller loads only when ``open_todos`` is armed (the other predicates must
    not pay a parent round-trip). ``no_progress_streak`` counts consecutive
    no-progress iterations including this one — see
    :func:`_iteration_made_progress`, which consumes the previous ``final_text``
    hash on the caller's behalf.

    **Order matters.** The cap binds first, then DD-6's re-invokability
    precondition, then no-progress, and only then the predicate. The
    precondition binds for EVERY predicate, including ``completion_marker`` and
    ``open_todos``: a ``complete`` stop with no marker still stops, because the
    model choosing to stop is not the failure this AD addresses.
    """
    if iteration >= max_iterations:
        return False, "max_outer_iterations"

    stopped_reason = getattr(outcome, "stopped_reason", "") or ""
    if stopped_reason not in _REINVOKABLE_STOPPED_REASONS:
        # DD-6, decided explicitly per value:
        #   token_budget — a hard spend ceiling the operator set; re-invoking
        #     after it defeats its purpose and would silently reverse AD-1142's
        #     deliberate ``-> status="failed"`` mapping.
        #   error — most often provider-window exhaustion, and the continuation
        #     block makes ``task_text`` LONGER. Compaction, not looping, is the
        #     mechanism for that reason.
        #   complete — the model chose to stop.
        # An unknown reason lands here too, which is the fail-safe direction.
        return False, f"stopped_reason_terminal:{stopped_reason}"

    if no_progress_streak >= 2:
        return False, "no_progress"

    if predicate == _LOOP_PREDICATE_COMPLETION_MARKER:
        tail = (getattr(outcome, "final_text", "") or "")[
            -_COMPLETION_MARKER_TAIL_CHARS:
        ]
        if completion_marker in tail:
            return False, "completion_marker_present"
        return True, "completion_marker_absent"

    if predicate == _LOOP_PREDICATE_OPEN_TODOS:
        if actionable_labels is None:
            return False, "todos_inapplicable"
        if not actionable_labels:
            return False, "todos_none_actionable"
        return True, f"todos_open:{len(actionable_labels)}"

    return True, "stopped_reason_reinvokable"


def _render_continuation(
    *,
    previous_output: Any,
    todo_labels: list[str] | None,
    completion_marker: str | None,
) -> str:
    """AD-1155 / DD-4: the continuation block appended to ``task_text``.

    Returns ``""`` when it cannot compose anything useful; the caller treats
    that as "stop the loop", never as a failed child. **Never persisted** — the
    durable value is ``WorkItem.description``, which is inside the plan-identity
    hash and which this AD does not touch (the AD-1141 rule).

    Bounded at :data:`_MAX_CONTINUATION_CHARS` overall. The prior output is the
    load-bearing part — without it the agent restarts from zero and repeats the
    work, which is the failure this AD exists to fix — so it is sized last,
    against whatever the fixed sections leave.
    """
    parts: list[str] = [_CONTINUATION_HEADER, "", _CONTINUATION_STOP_REASON_NOTE]

    if todo_labels:
        rendered = [
            f"- {label[:_MAX_CONTINUATION_TODO_CHARS]}"
            for label in todo_labels[:_MAX_CONTINUATION_TODOS]
            if type(label) is str and label.strip()
        ]
        if rendered:
            parts.extend(["", _CONTINUATION_TODO_HEADER, *rendered])

    if completion_marker:
        parts.extend(
            ["", _CONTINUATION_MARKER_INSTRUCTION.format(marker=completion_marker)]
        )

    fixed = "\n".join(parts)
    text = previous_output if type(previous_output) is str else ""
    text = text.strip()
    if text:
        overhead = len(fixed) + len(_CONTINUATION_OUTPUT_HEADER) + 4
        budget = min(
            _MAX_CONTINUATION_OUTPUT_CHARS,
            _MAX_CONTINUATION_CHARS - overhead - len(_CONTINUATION_OUTPUT_ELISION),
        )
        if budget > 0:
            if len(text) > budget:
                omitted = len(text) - budget
                text = text[:budget] + _CONTINUATION_OUTPUT_ELISION.format(
                    omitted=omitted
                )
            fixed = "\n".join([fixed, "", _CONTINUATION_OUTPUT_HEADER, "", text])

    block = "\n\n" + fixed.strip()
    if len(block) > _MAX_CONTINUATION_CHARS:
        block = block[:_MAX_CONTINUATION_CHARS]
    return block


def _format_consult_age(timestamp: Any) -> str:
    """Render an entry age, mirroring ``oracle_service._format_age``'s shape.

    Local rather than imported: that helper is private to its module, and a
    provenance marker that degrades to no age is preferable to a consult that
    raises on a malformed timestamp (DD-8).
    """
    if type(timestamp) not in (int, float):
        return ""
    delta = time.time() - float(timestamp)
    if not math.isfinite(delta) or delta < 0:
        return ""
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


def _render_commons_entry(result: Any) -> str:
    """Render one ``OracleResult`` with its AD-1139-shaped provenance marker.

    Marker carries source tier, confidence and age, so a low-confidence or
    aged entry is visibly weightable. Bounded at ``_MAX_ENTRY_CHARS`` with the
    marker preserved — the marker is what makes the entry weightable, so it is
    never the part that gets cut.
    """
    provenance = getattr(result, "provenance", "") or ""
    if type(provenance) is not str or not provenance:
        provenance = f"[{getattr(result, 'source_tier', '') or 'commons'}]"
    try:
        score = float(getattr(result, "score", 0.0) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    metadata = getattr(result, "metadata", None)
    age = ""
    if type(metadata) is dict:
        age = _format_consult_age(metadata.get("timestamp"))
    marker = f"{provenance} (confidence {score:.2f}"
    if age:
        marker += f", {age}"
    marker += ")"

    content = getattr(result, "content", "") or ""
    if type(content) is not str:
        content = ""
    content = " ".join(content.split())
    entry = f"- {marker} {content}".rstrip()
    if len(entry) <= _MAX_ENTRY_CHARS:
        return entry
    keep = max(0, _MAX_ENTRY_CHARS - len(_ENTRY_ELISION))
    return entry[:keep] + _ENTRY_ELISION


def _render_commons_block(
    results: Any,
    *,
    max_chars: int,
    max_entries: int,
    min_score: float,
) -> str:
    """DD-3: render the commons block, or ``""`` when nothing clears the floor.

    **The zero-character empty path is the load-bearing property.** When no
    result scores at or above ``min_score`` this returns the empty string — no
    header, no note, no whitespace — so a pointless consult costs one local
    Oracle call and *zero* prompt characters. The injection only ever adds
    tokens when it found something that cleared a floor.

    ``min_score`` is applied to ``OracleResult.score``, which is **not
    normalised across tiers** (see ``AgenticToolsConfig``): it is a volume
    control, not a principled relevance threshold.
    """
    if not isinstance(results, list) or max_entries < 1 or max_chars < 1:
        return ""
    admitted: list[tuple[float, Any]] = []
    for result in results:
        try:
            score = float(getattr(result, "score", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score) or score < min_score:
            continue
        admitted.append((score, result))
    if not admitted:
        return ""

    admitted.sort(key=lambda pair: pair[0], reverse=True)
    selected = admitted[:max_entries]
    dropped = len(admitted) - len(selected)

    lines = [_COMMONS_HEADER, "", _COMMONS_DISPOSITION, ""]
    used = sum(len(line) + 1 for line in lines)
    rendered: list[str] = []
    for _score, result in selected:
        entry = _render_commons_entry(result)
        if not entry:
            dropped += 1
            continue
        # Hold room for the budget note so the elision stays visible.
        if used + len(entry) + 1 + len(_BUDGET_NOTE) + 2 > max_chars:
            dropped += 1
            continue
        rendered.append(entry)
        used += len(entry) + 1
    if not rendered:
        return ""
    lines.extend(rendered)
    if dropped:
        lines.extend(["", _BUDGET_NOTE])
    return "\n".join(lines)


def _render_expected_output_block(raw: Any) -> str:
    """DD-9: surface the acceptance criterion the verifier will apply.

    Already persisted into child metadata by ``crew_session`` and already read
    by the verifier — the producer simply never saw it. Reading it here is
    free, additive, and touches no schema.
    """
    if type(raw) is not str:
        return ""
    text = raw.strip()
    if not text:
        return ""
    if len(text) > _MAX_EXPECTED_OUTPUT_CHARS:
        text = text[:_MAX_EXPECTED_OUTPUT_CHARS].rstrip() + _SUMMARY_TRUNCATION_MARKER
    return "\n".join(
        [_EXPECTED_OUTPUT_HEADER, "", _EXPECTED_OUTPUT_DISPOSITION, "", text]
    )


def _compose_child_task_text(
    base_task_text: str,
    *,
    commons_block: str = "",
    expected_output_block: str = "",
    publish_nudge: str = "",
) -> str:
    """DD-1: compose a crew child's user message. Pure; no I/O.

    **Every optional argument empty returns ``base_task_text`` by identity.**
    That is criterion #1 of AD-1141: with ``crew_sigma_context_enabled`` off
    the OFF path is provably a no-op rather than a re-render that happens to
    match, which is what preserves the Nooplex §8.3 ablation control arm.

    Order — task, then acceptance criterion, then commons, then nudge. The task
    comes first so a long commons block cannot push the actual instruction out
    of the model's attention; the nudge comes last because it is about what to
    do *after* the work.
    """
    if not commons_block and not expected_output_block and not publish_nudge:
        return base_task_text
    sections = [
        section
        for section in (
            base_task_text,
            expected_output_block,
            commons_block,
            publish_nudge,
        )
        if section
    ]
    return "\n\n".join(sections)



def _compact_json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_dicts_exactly_equal(
    current: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    try:
        return _compact_json_bytes(current) == _compact_json_bytes(expected)
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        return False


def _bounded_id(value: Any) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ValueError("crew_execution_id_invalid")
    return value


def _bounded_id_or_empty(value: Any) -> str:
    if value == "":
        return ""
    return _bounded_id(value)


def _normalize_tokens(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_ACTUAL_TOKENS:
        raise ValueError("crew_execution_tokens_invalid")
    return value


def _normalize_trace_ref(value: Any, child_id: str) -> str | None:
    if value is None:
        return None
    if type(value) is str and _SHA_RE.fullmatch(value) is not None:
        return value
    logger.warning(
        "Crew child %s returned a malformed tool-trace ref; evidence will "
        "store None while terminal status persistence continues",
        child_id,
    )
    return None


def _output_summary(value: Any) -> str:
    if type(value) is not str:
        return ""
    summary = value.strip()
    if len(summary) <= _MAX_OUTPUT_SUMMARY_CHARS:
        return summary
    keep = _MAX_OUTPUT_SUMMARY_CHARS - len(_SUMMARY_TRUNCATION_MARKER)
    return summary[:keep] + _SUMMARY_TRUNCATION_MARKER


def _exact_dependency_ids(values: Any) -> list[str]:
    if type(values) is not list or len(values) > _MAX_DEPENDENCY_IDS:
        raise ValueError("crew_execution_dependencies_invalid")
    return [_bounded_id(value) for value in values]


def _bounded_dependency_ids(values: list[str]) -> list[str]:
    exact_values = _exact_dependency_ids(values)
    result: list[str] = []
    for value in exact_values:
        if value not in result:
            result.append(value)
    return result


def _normalize_artifact_refs(
    value: Any,
    *,
    thread_id: str,
    child_id: str,
) -> list[dict[str, Any]]:
    if type(value) is not list:
        return []
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    dropped = max(0, len(value) - 64)
    for candidate in value[:64]:
        if type(candidate) is not dict:
            dropped += 1
            continue
        if (
            len(candidate) != 7
            or any(type(key) is not str for key in candidate)
            or set(candidate) != _ARTIFACT_REF_KEYS
        ):
            dropped += 1
            continue
        artifact_id = candidate["artifact_id"]
        content_hash = candidate["content_hash"]
        candidate_thread = candidate["thread_id"]
        name = candidate["name"]
        mime = candidate["mime"]
        size_bytes = candidate["size_bytes"]
        version = candidate["version"]
        valid = (
            type(artifact_id) is str
            and _ID_RE.fullmatch(artifact_id) is not None
            and artifact_id not in seen
            and type(content_hash) is str
            and _SHA_RE.fullmatch(content_hash) is not None
            and type(candidate_thread) is str
            and bool(candidate_thread)
            and candidate_thread == thread_id
            and type(name) is str
            and 1 <= len(name) <= 255
            and "/" not in name
            and "\\" not in name
            and "\x00" not in name
            and type(mime) is str
            and 1 <= len(mime) <= 255
            and type(size_bytes) is int
            and 1 <= size_bytes <= 26_214_400
            and type(version) is int
            and 1 <= version <= 2_147_483_647
            and len(refs) < 32
        )
        if not valid:
            dropped += 1
            continue
        seen.add(artifact_id)
        refs.append(
            {
                "artifact_id": artifact_id,
                "content_hash": content_hash,
                "thread_id": candidate_thread,
                "name": name,
                "mime": mime,
                "size_bytes": size_bytes,
                "version": version,
            }
        )
    if dropped:
        logger.warning(
            "Crew child %s artifact evidence dropped %d malformed, duplicate, "
            "cross-thread, or over-limit refs; terminal persistence continues "
            "with %d validated refs",
            child_id,
            dropped,
            len(refs),
        )
    return refs


def _build_execution_evidence(
    *,
    parent_id: str,
    child: WorkItem,
    thread_id: str,
    status: str,
    stopped_reason: str,
    output: Any,
    tool_trace_ref: str | None,
    artifact_refs: list[dict[str, Any]],
    actual_tokens: int,
    started_at: float,
    finished_at: float,
    blocked_dependency_ids: list[str],
) -> dict[str, Any]:
    if status not in {"done", "failed", "blocked"}:
        raise ValueError("crew_execution_status_invalid")
    reason = stopped_reason if stopped_reason in _STOPPED_REASONS else "error"
    required_status = {
        "complete": "done",
        "error": "failed",
        "max_iterations": "failed",
        "token_budget": "failed",
        "execution_exception": "failed",
        "unassigned": "blocked",
        "agent_unresolvable": "blocked",
        "dependency_blocked": "blocked",
        "start_transition_failed": "blocked",
    }[reason]
    if status != required_status:
        raise ValueError("crew_execution_status_invalid")
    dependencies = _bounded_dependency_ids(blocked_dependency_ids)
    if reason == "dependency_blocked":
        if not dependencies:
            raise ValueError("crew_execution_dependencies_invalid")
    elif dependencies:
        raise ValueError("crew_execution_dependencies_invalid")
    if not (
        type(started_at) in (int, float)
        and type(finished_at) in (int, float)
        and math.isfinite(float(started_at))
        and math.isfinite(float(finished_at))
        and 0 <= float(started_at) <= float(finished_at)
    ):
        raise ValueError("crew_execution_timestamp_invalid")
    record = {
        "version": 1,
        "parent_id": _bounded_id(parent_id),
        "work_item_id": _bounded_id(child.id),
        "thread_id": _bounded_id_or_empty(thread_id),
        "assigned_to": _bounded_id(child.assigned_to) if child.assigned_to else None,
        "status": status,
        "stopped_reason": reason,
        "output_summary": _output_summary(output),
        "tool_trace_ref": tool_trace_ref,
        "artifact_refs": [dict(ref) for ref in artifact_refs],
        "tokens_used": actual_tokens,
        "started_at": float(started_at),
        "finished_at": float(finished_at),
        "blocked_dependency_ids": dependencies,
    }
    initial_ref_count = len(record["artifact_refs"])
    while (
        len(_compact_json_bytes(record)) > _MAX_EVIDENCE_BYTES
        and record["artifact_refs"]
    ):
        record["artifact_refs"].pop()
    if len(record["artifact_refs"]) != initial_ref_count:
        logger.warning(
            "Crew child %s evidence exceeded the 32 KiB record cap; %d "
            "artifact refs were removed and bounded terminal persistence continues",
            child.id,
            initial_ref_count - len(record["artifact_refs"]),
        )
    if len(_compact_json_bytes(record)) > _MAX_EVIDENCE_BYTES:
        raise ValueError("crew_execution_evidence_too_large")
    return record


@dataclass
class SubtaskResult:
    """The collected outcome of one child sub-task with durable provenance."""

    work_item_id: str
    spec_id: str
    agent_id: str
    output: str
    status: str  # done | failed | blocked
    tool_trace_ref: str | None = None
    started_at: float = 0.0
    finished_at: float = 0.0
    stopped_reason: str = ""
    actual_tokens: int = 0
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    blocked_dependency_ids: list[str] = field(default_factory=list)


class CrewTaskExecutor:
    """Drive a parent's child sub-tasks with dependency-gated bounded fan-out."""

    def __init__(
        self,
        *,
        work_item_store: WorkItemStore,
        agent_registry: AgentRegistry,
        agentic_executor: WorkItemAgenticExecutor,
        runtime: Any,
        max_parallel_subtasks: int = 3,
        emit_fn: Callable[[EventType, dict[str, Any]], None] | None = None,
        crew_session_service: CrewSessionService | None = None,
        attachment_store: AttachmentStore | None = None,
        oracle: Any = None,
        crew_sigma_context_enabled: bool = False,
        crew_sigma_max_chars: int = 2000,
        crew_sigma_max_entries: int = 4,
        crew_sigma_min_score: float = 0.35,
        crew_compaction_enabled: bool = False,
        crew_compaction_threshold_tokens: int = _CREW_COMPACTION_THRESHOLD_TOKENS,
        crew_token_budget: int | None = None,
        crew_loop_until_done_enabled: bool = False,
        crew_loop_until_done_max_iterations: int = _LOOP_UNTIL_DONE_MAX_ITERATIONS,
        crew_loop_until_done_predicate: str = _LOOP_PREDICATE_STOP_REASON,
        crew_loop_until_done_completion_marker: str = _DEFAULT_COMPLETION_MARKER,
    ) -> None:
        self._store = work_item_store
        self._registry = agent_registry
        self._executor = agentic_executor
        self._runtime = runtime
        self._max_parallel = max(1, int(max_parallel_subtasks))
        # Honest-degrade: if no emit fn is wired, the executor still runs; it
        # just cannot publish lifecycle events.
        self._emit_fn = emit_fn
        self._crew_session_service = crew_session_service
        self._attachment_store = (
            attachment_store
            if attachment_store is not None
            else getattr(runtime, "attachment_store", None)
        )
        # AD-1141: constructor-injected (DIP) rather than reached for through
        # ``runtime`` in the hot path. Defaults match ``AgenticToolsConfig`` so
        # every existing construction site keeps its pre-AD-1141 behaviour.
        self._oracle = oracle
        self._sigma_enabled = bool(crew_sigma_context_enabled)
        self._sigma_max_chars = int(crew_sigma_max_chars)
        self._sigma_max_entries = int(crew_sigma_max_entries)
        self._sigma_min_score = float(crew_sigma_min_score)
        # AD-1142 / DD-10: the compaction knobs are NORMALISED HERE, in
        # ``__init__`` and OUTSIDE the try in ``_run_child`` that persists
        # ``stopped_reason="execution_exception"``. A mistyped knob must not be
        # able to fail every child of every session (AD-1141 DD-8 precedent).
        # Only the SCALARS are settled now: DD-2 requires a fresh
        # ``SessionCompactor`` per child, so the instance is built at the call
        # site by ``resolve_crew_compaction_settings`` reading this view.
        self._compaction_config = SimpleNamespace(
            crew_compaction_enabled=crew_compaction_enabled is True,
            crew_compaction_threshold_tokens=_normalize_compaction_threshold(
                crew_compaction_threshold_tokens
            ),
            crew_token_budget=_normalize_token_budget(crew_token_budget),
        )
        # AD-1155 / DD-7: same rule, same reason — normalised HERE, outside the
        # ``_run_child`` try that persists ``stopped_reason="execution_exception"``.
        # A mistyped predicate id or a malformed cap must degrade to the shipped
        # default, never fail a child. A sibling namespace rather than more keys
        # on ``_compaction_config``: the two features are independent knobs, and
        # ``resolve_crew_compaction_settings`` reads that view by attribute name.
        self._loop_until_done = SimpleNamespace(
            enabled=_normalize_loop_until_done_enabled(crew_loop_until_done_enabled),
            max_iterations=_normalize_loop_until_done_max_iterations(
                crew_loop_until_done_max_iterations
            ),
            predicate=_normalize_loop_until_done_predicate(
                crew_loop_until_done_predicate
            ),
            completion_marker=_normalize_completion_marker(
                crew_loop_until_done_completion_marker
            ),
        )

    async def run(self, parent_id: str) -> list[SubtaskResult]:
        """Run all child sub-tasks of ``parent_id`` and return their results.

        Children are scheduled in topological order: a child becomes runnable
        only once every id in its ``depends_on`` has reached ``done`` in the
        store. At most ``max_parallel_subtasks`` children run concurrently.
        """
        parent = await self._store.get_work_item(parent_id)
        if parent is None:
            logger.warning(
                "Crew parent %s was not found; no child execution can be bound "
                "to an authoritative parent, so fan-out is skipped",
                parent_id,
            )
            return []
        children = await self._store.list_work_items(
            parent_id=parent_id, limit=1000
        )
        self._emit(
            EventType.CREW_TASK_STARTED,
            {"parent_id": parent_id, "child_count": len(children)},
        )
        if not children and parent.work_type != "crew_session":
            return []

        parent_key = _bounded_id(parent.id)
        resolved_thread = await self._resolve_task_room(parent, children)
        thread_id = (
            _bounded_id(resolved_thread.id)
            if resolved_thread is not None
            else ""
        )
        await self._start_crew_session(parent, resolved_thread)
        if not children:
            return []

        return await self._run_children(
            parent_key,
            children,
            thread_id,
            seed_results={},
            seed_done_ids=set(),
        )

    async def resume(self, parent_id: str) -> list[SubtaskResult]:
        """Resume one authoritative executing CrewSession without rerunning terminals."""
        parent_key = _bounded_id(parent_id)
        parent = await self._store.get_work_item(parent_key)
        if parent is None or parent.work_type != "crew_session":
            raise ValueError("crew_session_parent_not_found")
        service = self._crew_session_service
        if service is None:
            raise ValueError("crew_session_service_unavailable")
        session = await service.get_session(parent_key)
        recovery = await service.get_recovery(parent_key)
        if (
            session is None
            or session.state != "executing"
            or recovery is None
            or recovery.phase != "executing"
            or recovery.plan is None
        ):
            raise ValueError("crew_session_recovery_not_executable")
        children = await self._store.list_work_items(
            parent_id=parent_key,
            limit=1001,
        )
        if len(children) != len(recovery.plan.children) or len(children) > 1000:
            raise ValueError("crew_session_recovery_plan_conflict")
        by_id = {child.id: child for child in children}
        if len(by_id) != len(children):
            raise ValueError("crew_session_recovery_plan_conflict")
        try:
            ordered = [by_id[item.child_id] for item in recovery.plan.children]
        except KeyError as exc:
            raise ValueError("crew_session_recovery_plan_conflict") from exc
        room = await self._resolve_task_room(parent, ordered)
        if room is None or room.id != session.thread_id:
            raise ValueError("crew_session_thread_mismatch")

        reconstructed: dict[str, SubtaskResult] = {}
        done_ids: set[str] = set()
        for child in ordered:
            result = await self._resume_child(
                parent_key,
                child,
                session.thread_id,
            )
            if result is None:
                continue
            reconstructed[child.id] = result
            if result.status == "done":
                done_ids.add(child.id)
        return await self._run_children(
            parent_key,
            ordered,
            session.thread_id,
            seed_results=reconstructed,
            seed_done_ids=done_ids,
        )

    async def _run_children(
        self,
        parent_id: str,
        children: list[WorkItem],
        thread_id: str,
        *,
        seed_results: dict[str, SubtaskResult],
        seed_done_ids: set[str],
    ) -> list[SubtaskResult]:
        """Run one parent's remaining children with an invocation-local task set."""

        by_id: dict[str, WorkItem] = {c.id: c for c in children}
        results = dict(seed_results)
        done_ids = set(seed_done_ids)
        started: set[str] = set(results)
        pending: set[str] = set(by_id).difference(results)
        sem = asyncio.Semaphore(self._max_parallel)
        tasks: set[asyncio.Task[SubtaskResult]] = set()

        for child in children:
            try:
                _exact_dependency_ids(child.depends_on)
            except ValueError:
                logger.error(
                    "Crew child %s has an invalid or over-limit dependency "
                    "vector; no agent will run and the child will be durably "
                    "blocked without dependency evidence",
                    child.id,
                    exc_info=True,
                )
                started_at = time.time()
                result = await self._persist_terminal_result(
                    parent_id=parent_id,
                    child=child,
                    thread_id=thread_id,
                    status="blocked",
                    stopped_reason="start_transition_failed",
                    output="",
                    tool_trace_ref=None,
                    actual_tokens=0,
                    artifact_refs=[],
                    started_at=started_at,
                    finished_at=max(started_at, time.time()),
                    blocked_dependency_ids=[],
                    expected_status=child.status,
                    dependency_input_invalid=True,
                )
                results[child.id] = result
                pending.discard(child.id)
                self._emit_subtask_completed(parent_id, result)

        async def _guarded(child: WorkItem) -> SubtaskResult:
            async with sem:
                return await self._run_child(parent_id, child, thread_id)

        try:
            while pending or tasks:
                runnable = [
                    cid
                    for cid in pending
                    if cid not in started and self._deps_met(by_id[cid], done_ids)
                ]
                for cid in runnable:
                    started.add(cid)
                    task: asyncio.Task[SubtaskResult] = asyncio.create_task(
                        _guarded(by_id[cid])
                    )
                    tasks.add(task)

                if not tasks:
                    blocked_children = [
                        child for child in children if child.id in pending
                    ]
                    for child in blocked_children:
                        unresolved = self._unresolved_dependency_ids(child, done_ids)
                        started_at = time.time()
                        result = await self._persist_terminal_result(
                            parent_id=parent_id,
                            child=child,
                            thread_id=thread_id,
                            status="blocked",
                            stopped_reason="dependency_blocked",
                            output="",
                            tool_trace_ref=None,
                            actual_tokens=0,
                            artifact_refs=[],
                            started_at=started_at,
                            finished_at=max(started_at, time.time()),
                            blocked_dependency_ids=unresolved,
                            expected_status=child.status,
                        )
                        results[child.id] = result
                        pending.discard(child.id)
                        self._emit_subtask_completed(parent_id, result)
                    break

                completed, _ = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )
                for task in completed:
                    tasks.discard(task)
                    result = task.result()
                    results[result.work_item_id] = result
                    pending.discard(result.work_item_id)
                    if result.status == "done":
                        done_ids.add(result.work_item_id)
                    self._emit_subtask_completed(parent_id, result)
        finally:
            held = tuple(tasks)
            for task in held:
                task.cancel()
            if held:
                await asyncio.gather(*held, return_exceptions=True)
            tasks.clear()

        return list(results.values())

    async def _resume_child(
        self,
        parent_id: str,
        child: WorkItem,
        thread_id: str,
    ) -> SubtaskResult | None:
        metadata = child.metadata if type(child.metadata) is dict else {}
        execution = metadata.get("crew_execution")
        output_ref = metadata.get("crew_execution_output")
        initial_status = self._store.work_type_registry.get_initial_status(
            child.work_type,
        )
        if (
            child.status == initial_status
            and execution is None
            and output_ref is None
            and child.verification == {}
        ):
            return None
        if child.status == "in_progress":
            return self._interrupted_result(child, "child_execution_interrupted")
        if child.status not in {"done", "failed", "blocked"}:
            return self._interrupted_result(child, "child_execution_integrity")
        try:
            return await self._reconstruct_terminal_result(
                parent_id,
                child,
                thread_id,
            )
        except (UnicodeError, ValueError, FileNotFoundError):
            return self._interrupted_result(child, "child_execution_integrity")

    async def _reconstruct_terminal_result(
        self,
        parent_id: str,
        child: WorkItem,
        thread_id: str,
    ) -> SubtaskResult:
        metadata = child.metadata
        execution = metadata.get("crew_execution")
        if type(execution) is not dict or set(execution) != CREW_EXECUTION_KEYS:
            raise ValueError("crew_execution_evidence_invalid")
        if (
            type(execution["version"]) is not int
            or execution["version"] != 1
            or execution["parent_id"] != parent_id
            or execution["work_item_id"] != child.id
            or execution["thread_id"] != thread_id
            or execution["assigned_to"] != child.assigned_to
            or execution["status"] != child.status
            or type(execution["stopped_reason"]) is not str
            or type(execution["output_summary"]) is not str
            or type(execution["tokens_used"]) is not int
            or execution["tokens_used"] != child.actual_tokens
            or type(execution["started_at"]) is not float
            or type(execution["finished_at"]) is not float
            or not math.isfinite(execution["started_at"])
            or not math.isfinite(execution["finished_at"])
            or execution["started_at"] > execution["finished_at"]
            or type(execution["blocked_dependency_ids"]) is not list
        ):
            raise ValueError("crew_execution_evidence_invalid")
        trace_ref = _normalize_trace_ref(execution["tool_trace_ref"], child.id)
        if trace_ref != execution["tool_trace_ref"]:
            raise ValueError("crew_execution_evidence_invalid")
        artifacts = _normalize_artifact_refs(
            execution["artifact_refs"],
            thread_id=thread_id,
            child_id=child.id,
        )
        if artifacts != execution["artifact_refs"]:
            raise ValueError("crew_execution_evidence_invalid")
        blocked_dependencies = _exact_dependency_ids(
            execution["blocked_dependency_ids"],
        )
        output = ""
        output_record = metadata.get("crew_execution_output")
        if child.status == "done":
            if (
                type(output_record) is not dict
                or set(output_record)
                != {"version", "content_hash", "mime", "size_bytes"}
                or type(output_record["version"]) is not int
                or output_record["version"] != 1
                or output_record["mime"] != "text/plain"
                or type(output_record["size_bytes"]) is not int
                or not 1 <= output_record["size_bytes"] <= _MAX_OUTPUT_BYTES
                or self._attachment_store is None
            ):
                raise ValueError("crew_execution_output_invalid")
            content_hash = output_record["content_hash"]
            if type(content_hash) is not str or _SHA_RE.fullmatch(content_hash) is None:
                raise ValueError("crew_execution_output_invalid")
            blob = await self._attachment_store.read(content_hash)
            if (
                len(blob) != output_record["size_bytes"]
                or hashlib.sha256(blob).hexdigest() != content_hash
            ):
                raise ValueError("crew_execution_output_invalid")
            output = blob.decode("utf-8", errors="strict")
            if (
                execution["stopped_reason"] != "complete"
                or execution["output_summary"] != _output_summary(output)
                or blocked_dependencies
            ):
                raise ValueError("crew_execution_output_invalid")
        elif output_record is not None:
            raise ValueError("crew_execution_output_invalid")
        spec_id = metadata.get("spec_id")
        if type(spec_id) is not str or not spec_id:
            raise ValueError("crew_execution_evidence_invalid")
        if child.status == "done":
            self._append_crew_session_child_result(
                parent_id=parent_id,
                child=child,
                thread_id=thread_id,
                output=output,
                content_hash=output_record["content_hash"],
                finished_at=execution["finished_at"],
            )
        return SubtaskResult(
            work_item_id=child.id,
            spec_id=spec_id,
            agent_id=child.assigned_to or "",
            output=output,
            status=child.status,
            tool_trace_ref=trace_ref,
            started_at=execution["started_at"],
            finished_at=execution["finished_at"],
            stopped_reason=execution["stopped_reason"],
            actual_tokens=execution["tokens_used"],
            artifact_refs=artifacts,
            blocked_dependency_ids=blocked_dependencies,
        )

    @staticmethod
    def _interrupted_result(child: WorkItem, reason: str) -> SubtaskResult:
        spec_id = (
            child.metadata.get("spec_id", child.id)
            if type(child.metadata) is dict
            else child.id
        )
        return SubtaskResult(
            work_item_id=child.id,
            spec_id=str(spec_id),
            agent_id=child.assigned_to or "",
            output="",
            status="blocked",
            stopped_reason=reason,
        )

    def _deps_met(self, child: WorkItem, done_ids: set[str]) -> bool:
        """True when every ``depends_on`` id of ``child`` has reached ``done``."""
        return all(
            dependency_id in done_ids
            for dependency_id in _exact_dependency_ids(child.depends_on)
        )

    # ── AD-1141: Σ context injection ──────────────────────────────────
    async def _augment_task_text(
        self,
        base_task_text: str,
        *,
        child: WorkItem,
        agent_id: str,
    ) -> str:
        """Compose the child's user message, injecting Σ context when enabled.

        Returns ``base_task_text`` **by identity** when the gate is off, which
        is AD-1141's criterion #1: flags off must be byte-identical to
        pre-AD-1141 crew behaviour, because today's isolated-children
        behaviour is the ablation's control arm.

        DD-8 — the whole body degrades rather than propagates. Nothing here may
        raise into the caller's ``try``, which persists
        ``stopped_reason="execution_exception"``.
        """
        if not self._sigma_enabled:
            return base_task_text
        commons_block = ""
        expected_output_block = ""
        publish_nudge = ""
        try:
            commons_block = await self._consult_commons(child, agent_id=agent_id)
            expected_output_block = _render_expected_output_block(
                (child.metadata or {}).get("expected_output")
            )
            publish_nudge = _PUBLISH_NUDGE if self._publish_tool_available() else ""
            composed = _compose_child_task_text(
                base_task_text,
                commons_block=commons_block,
                expected_output_block=expected_output_block,
                publish_nudge=publish_nudge,
            )
        except Exception:
            logger.warning(
                "AD-1141: Σ task-text composition failed for crew child %s; "
                "continuing with the unaugmented task text so the child still "
                "runs",
                child.id,
                exc_info=True,
            )
            return base_task_text
        if composed is not base_task_text:
            # DD-10: recorded as a metric so the ablation can attribute context
            # growth. Deliberately NOT written into ``crew_execution`` evidence
            # — that set is an exact 14 keys and one extra breaks recovery.
            logger.info(
                "AD-1141: injected %d Σ characters into crew child %s "
                "(commons=%d, expected_output=%d, nudge=%d)",
                len(composed) - len(base_task_text),
                child.id,
                len(commons_block),
                len(expected_output_block),
                len(publish_nudge),
            )
        return composed

    def _publish_tool_available(self) -> bool:
        """True when ``publish_finding`` is registered on the runtime registry.

        DD-5: do not nudge an agent toward a verb it does not hold. Registration
        is dynamic runtime state rather than a construction-time dependency, so
        it is read at consult time; every access is guarded because an absent or
        unusual registry must degrade, never raise (DD-8).
        """
        try:
            registry = getattr(self._runtime, "tool_registry", None)
            if registry is None:
                return False
            return registry.get("publish_finding") is not None
        except Exception:
            logger.warning(
                "AD-1141: tool-registry lookup for publish_finding raised; "
                "omitting the publish nudge so no agent is pointed at a verb "
                "whose availability could not be confirmed",
                exc_info=True,
            )
            return False

    async def _consult_commons(self, child: WorkItem, *, agent_id: str) -> str:
        """DD-2/DD-3: one bounded commons lookup per child, before execution.

        Three gates, cheapest first: a query floor (under
        ``_MIN_CONSULT_QUERY_CHARS`` after strip ⇒ **no Oracle call at all**), a
        score floor, then an entry cap. When nothing clears the score floor the
        renderer returns ``""`` and **zero characters** are injected — a
        pointless consult therefore costs one local Oracle call and no context.

        Tiers come from the imported :data:`SIGMA_TIERS`; ``episodic`` is the
        sovereign per-agent shard and is never queried here.
        """
        if self._oracle is None:
            return ""
        title = child.title if type(child.title) is str else ""
        description = child.description if type(child.description) is str else ""
        query_text = f"{title}\n{description}".strip()
        if len(query_text) < _MIN_CONSULT_QUERY_CHARS:
            return ""
        query_text = query_text[:_MAX_CONSULT_QUERY_CHARS]

        from probos.tools.oracle_query_tool import SIGMA_TIERS

        try:
            results = await self._oracle.query(
                query_text,
                agent_id=agent_id,
                k_per_tier=_CONSULT_K_PER_TIER,
                tiers=list(SIGMA_TIERS),
            )
        except Exception:
            logger.warning(
                "AD-1141: commons consult failed for crew child %s; continuing "
                "with the unaugmented task text",
                child.id,
                exc_info=True,
            )
            return ""
        return _render_commons_block(
            results,
            max_chars=self._sigma_max_chars,
            max_entries=self._sigma_max_entries,
            min_score=self._sigma_min_score,
        )

    # ── AD-1155: loop-until-done ──────────────────────────────────────
    async def _load_actionable_steps(
        self, parent_id: str, child_id: str
    ) -> list[str] | None:
        """DD-2: the parent's actionable checklist labels, or ``None``.

        A store round-trip, so it is paid ONLY when the ``open_todos`` predicate
        is armed and only when another iteration is still possible. Steps live
        on the PARENT (``_run_child`` receives ``parent_id``, not the row), and
        the DM reply pipeline can rewrite the same list concurrently — which is
        why the read happens once per outer iteration rather than once per child.
        Degrades to ``None`` (⇒ stop) on any failure.
        """
        try:
            parent = await self._store.get_work_item(parent_id)
        except Exception:
            logger.warning(
                "AD-1155: loading parent %s for the open_todos predicate failed; "
                "the outer loop stops rather than re-invoking crew child %s on "
                "an unreadable checklist",
                parent_id,
                child_id,
                exc_info=True,
            )
            return None
        if parent is None:
            return None
        return _actionable_step_labels(
            getattr(parent, "steps", None), child_id=child_id
        )

    async def _run_agentic_with_outer_loop(
        self,
        *,
        agent: Any,
        task_text: str,
        thread_id: str,
        parent_id: str,
        child_id: str,
    ) -> Any:
        """AD-1155 / DD-1: run the child, and re-invoke it while it is unfinished.

        Iteration 1 is EXACTLY today's call — the same kwargs, in the same
        order, with ``task_text`` passed by identity — so with the gate off this
        method is one ``self._executor.run(...)`` and a return. The five other
        callers of :meth:`WorkItemAgenticExecutor.run` are untouched **by
        construction**: the wrap is here, not in the executor.

        Every iteration is an INDEPENDENTLY GOVERNED run. That is free at this
        seam and worth stating: each ``run`` builds a fresh
        ``DispatchToolExecutor``, re-resolves department/rank through live
        ``trust_network.get_score``, re-runs every ``check_permission`` offer
        gate, re-arms the AD-1153 browser guard and persists its own AD-1151
        trace. An agent whose trust falls between iterations therefore LOSES
        tools on the next one — Minimal Authority working correctly.

        **Only the final iteration's ``tool_trace_ref`` reaches the 14-key
        ``crew_execution`` record.** That set is frozen and cannot carry a list,
        and inventing a companion key is the "one extra breaks recovery" hazard.
        Intermediate traces are therefore NOT durably linked from the evidence
        record; they are logged at INFO with their iteration index and are
        recoverable from the log alone.
        """
        base_kwargs: dict[str, Any] = {
            "agent_id": agent.id,
            "instructions": str(getattr(agent, "instructions", "") or ""),
            "task_text": task_text,
            "runtime": self._runtime,
            "thread_id": thread_id,
            "extra_context": {
                "_crew_session_id": parent_id,
                "_crew_work_item_id": child_id,
            },
        }
        gate = self._loop_until_done
        max_outer = gate.max_iterations if gate.enabled else 1
        # DD-3: the budget is SHARED across iterations and carried forward as a
        # remainder, never reset. ``AgenticLoop`` measures its budget against a
        # counter local to one ``AgenticResult`` and the executor builds a new
        # loop per call, so passing the full figure each time would multiply the
        # operator's spend ceiling by the outer cap — nobody setting
        # ``crew_token_budget=50000`` expects 250 000.
        #
        # BF-683: ``SubtaskVerifier.converge_for_session``'s correction re-runs
        # pass NO budget and NO compactor at all, so they run entirely outside
        # this ceiling. Pre-existing and deliberately not fixed here; the
        # arithmetic below does not depend on those rounds being budgeted.
        configured_budget = self._compaction_config.crew_token_budget

        outcome: Any = None
        spent = 0
        previous_text_hash: str | None = None
        previous_actionable: int | None = None
        no_progress_streak = 0
        current_task_text = task_text

        for iteration in range(1, max_outer + 1):
            # AD-1142 / DD-2: a FRESH compactor for THIS iteration. Children run
            # concurrently under the fan-out semaphore, so the instance is never
            # shared. Spreads to nothing when the gate is off and no budget is
            # set, leaving iteration 1 byte-identical to AD-1141/AD-1142.
            settings = resolve_crew_compaction_settings(self._compaction_config)
            if configured_budget is not None:
                settings["token_budget"] = configured_budget - spent
            kwargs = dict(base_kwargs)
            kwargs["task_text"] = current_task_text
            outcome = await self._executor.run(**kwargs, **settings)
            spent += _bounded_spend(getattr(outcome, "total_tokens", 0))

            if iteration >= max_outer:
                break

            actionable: list[str] | None = None
            if gate.predicate == _LOOP_PREDICATE_OPEN_TODOS:
                actionable = await self._load_actionable_steps(parent_id, child_id)
            actionable_count = None if actionable is None else len(actionable)

            no_progress_streak = (
                0
                if _iteration_made_progress(
                    outcome,
                    previous_text_hash=previous_text_hash,
                    previous_actionable_count=previous_actionable,
                    actionable_count=actionable_count,
                )
                else no_progress_streak + 1
            )
            previous_text_hash = _text_hash(getattr(outcome, "final_text", "") or "")
            previous_actionable = actionable_count

            proceed, reason = _should_continue(
                outcome,
                iteration=iteration,
                max_iterations=max_outer,
                predicate=gate.predicate,
                completion_marker=gate.completion_marker,
                no_progress_streak=no_progress_streak,
                actionable_labels=actionable,
            )
            if not proceed:
                logger.info(
                    "AD-1155: crew child %s stops after iteration %d/%d (%s)",
                    child_id,
                    iteration,
                    max_outer,
                    reason,
                )
                break

            if configured_budget is not None:
                remaining = configured_budget - spent
                if remaining < _MIN_CREW_TOKEN_BUDGET:
                    logger.info(
                        "AD-1155: crew child %s stops after iteration %d/%d "
                        "(budget_exhausted: %d of %d tokens remain, below the "
                        "%d floor, so a re-invocation would only buy one call "
                        "before hitting the ceiling)",
                        child_id,
                        iteration,
                        max_outer,
                        remaining,
                        configured_budget,
                        _MIN_CREW_TOKEN_BUDGET,
                    )
                    break

            # DD-4 — composed at runtime into ``task_text`` and NEVER persisted;
            # the durable value is ``WorkItem.description``, which is inside the
            # plan-identity hash. Always rebuilt from the BASE text so the block
            # cannot stack across iterations. A composition failure degrades to
            # "stop the loop", never to a failed child: this whole method runs
            # inside the ``_run_child`` try that persists
            # ``stopped_reason="execution_exception"``, and an unfinished child
            # must not be recorded as an exception.
            try:
                block = _render_continuation(
                    previous_output=getattr(outcome, "final_text", "") or "",
                    todo_labels=(
                        actionable
                        if gate.predicate == _LOOP_PREDICATE_OPEN_TODOS
                        else None
                    ),
                    completion_marker=(
                        gate.completion_marker
                        if gate.predicate == _LOOP_PREDICATE_COMPLETION_MARKER
                        else None
                    ),
                )
            except Exception:
                logger.warning(
                    "AD-1155: continuation composition raised for crew child "
                    "%s after iteration %d; the outer loop stops and the last "
                    "real outcome is persisted",
                    child_id,
                    iteration,
                    exc_info=True,
                )
                block = ""
            if not block:
                logger.info(
                    "AD-1155: crew child %s stops after iteration %d/%d "
                    "(continuation_failed)",
                    child_id,
                    iteration,
                    max_outer,
                )
                break

            superseded_ref = getattr(outcome, "tool_trace_ref", None)
            if superseded_ref:
                logger.info(
                    "AD-1155: crew child %s iteration %d produced tool trace "
                    "%s; it is superseded by the next iteration and is NOT "
                    "durably linked from the 14-key crew_execution record, so "
                    "this log line is the only route back to it",
                    child_id,
                    iteration,
                    superseded_ref,
                )
            current_task_text = task_text + block
            logger.info(
                "AD-1155: re-invoking crew child %s (iteration %d/%d, %s, "
                "+%d continuation characters)",
                child_id,
                iteration + 1,
                max_outer,
                reason,
                len(block),
            )

        return outcome

    async def _run_child(
        self,
        parent_id: str,
        child: WorkItem,
        thread_id: str,
    ) -> SubtaskResult:
        """Run a single child through the AD-859a executor and collect its result."""
        started_at = time.time()
        spec_id = str(child.metadata.get("spec_id", child.id))
        child_id = _bounded_id(child.id)
        expected_assigned_to = (
            _bounded_id(child.assigned_to)
            if child.assigned_to is not None
            else None
        )
        admission_status = child.status
        try:
            active_child = await self._store.merge_work_item_metadata(
                child_id,
                {},
                expected_work_type=child.work_type,
                expected_status=admission_status,
                expected_assigned_to_exact=expected_assigned_to,
                expected_parent_id=parent_id,
                expected_depends_on=list(child.depends_on),
                expected_unresolved_dependency_ids=[],
                new_status=(
                    "in_progress"
                    if expected_assigned_to is not None
                    else None
                ),
                source="crew_executor_admission",
            )
        except Exception as exc:
            state_conflict = (
                isinstance(exc, ValueError)
                and str(exc) in {
                    "work_item_state_conflict",
                    "work_item_dependency_state_conflict",
                }
            )
            logger.warning(
                "Crew child %s could not be admitted from status %s because its "
                "atomic state/dependency validation raised; no agent will run "
                "and blocked evidence will fail closed on ownership drift",
                child.id,
                admission_status,
                exc_info=True,
            )
            active_child = None
            if not state_conflict:
                try:
                    reloaded_child = await self._store.get_work_item(child_id)
                except Exception:
                    logger.error(
                        "Crew child %s could not be reloaded after admission "
                        "raised; blocked evidence will use the prior row and "
                        "fail closed on any state conflict",
                        child.id,
                        exc_info=True,
                    )
                else:
                    if reloaded_child is not None:
                        child = reloaded_child
        if active_child is None:
            failure_reason = (
                "unassigned"
                if expected_assigned_to is None
                else "start_transition_failed"
            )
            return await self._persist_terminal_result(
                parent_id=parent_id,
                child=child,
                thread_id=thread_id,
                status="blocked",
                stopped_reason=failure_reason,
                output="",
                tool_trace_ref=None,
                actual_tokens=0,
                artifact_refs=[],
                started_at=started_at,
                finished_at=max(started_at, time.time()),
                blocked_dependency_ids=[],
                expected_status=child.status,
            )

        if active_child.assigned_to is None:
            logger.warning(
                "Crew child %s is authoritatively unassigned at admission; "
                "persisting blocked evidence so dependents remain closed",
                child.id,
            )
            return await self._persist_terminal_result(
                parent_id=parent_id,
                child=active_child,
                thread_id=thread_id,
                status="blocked",
                stopped_reason="unassigned",
                output="",
                tool_trace_ref=None,
                actual_tokens=0,
                artifact_refs=[],
                started_at=started_at,
                finished_at=max(started_at, time.time()),
                blocked_dependency_ids=[],
                expected_status=active_child.status,
            )

        assigned_to = _bounded_id(active_child.assigned_to)
        agent = self._registry.get(assigned_to)
        if agent is None:
            logger.warning(
                "Crew child %s has no resolvable authoritatively assigned agent "
                "%s after admission; persisting blocked evidence so dependents "
                "remain closed",
                child.id,
                assigned_to,
            )
            return await self._persist_terminal_result(
                parent_id=parent_id,
                child=active_child,
                thread_id=thread_id,
                status="blocked",
                stopped_reason="agent_unresolvable",
                output="",
                tool_trace_ref=None,
                actual_tokens=0,
                artifact_refs=[],
                started_at=started_at,
                finished_at=max(started_at, time.time()),
                blocked_dependency_ids=[],
                expected_status=active_child.status,
            )

        task_text = active_child.description or active_child.title or ""
        # AD-1141 DD-1/DD-8: Σ composition happens HERE, outside the try below.
        # That try persists ``stopped_reason="execution_exception"``; a consult
        # raising into it would fail every child of every session on a commons
        # outage. ``_augment_task_text`` absorbs its own failures and returns
        # the base string by identity when the gate is off.
        task_text = await self._augment_task_text(
            task_text, child=active_child, agent_id=agent.id,
        )
        try:
            outcome = await self._run_agentic_with_outer_loop(
                agent=agent,
                task_text=task_text,
                thread_id=thread_id,
                parent_id=parent_id,
                child_id=child_id,
            )
        except Exception:
            logger.warning(
                "Crew child %s raised during agentic execution; persisting failed "
                "evidence so it cannot remain in_progress or unblock dependents",
                child.id,
                exc_info=True,
            )
            return await self._persist_terminal_result(
                parent_id=parent_id,
                child=active_child,
                thread_id=thread_id,
                status="failed",
                stopped_reason="execution_exception",
                output="",
                tool_trace_ref=None,
                actual_tokens=0,
                artifact_refs=[],
                started_at=started_at,
                finished_at=max(started_at, time.time()),
                blocked_dependency_ids=[],
                expected_status="in_progress",
            )

        if outcome.stopped_reason == _SUCCESS_STOPPED_REASON:
            status = "done"
            stopped_reason = "complete"
        else:
            status = "failed"
            stopped_reason = (
                outcome.stopped_reason
                if outcome.stopped_reason in {"error", "max_iterations", "token_budget"}
                else "error"
            )

        checkpoint = asyncio.create_task(self._persist_terminal_result(
            parent_id=parent_id,
            child=active_child,
            thread_id=thread_id,
            status=status,
            stopped_reason=stopped_reason,
            output=outcome.final_text,
            tool_trace_ref=outcome.tool_trace_ref,
            actual_tokens=outcome.total_tokens,
            artifact_refs=outcome.artifact_refs,
            started_at=started_at,
            finished_at=max(started_at, time.time()),
            blocked_dependency_ids=[],
            expected_status="in_progress",
        ))
        try:
            return await asyncio.shield(checkpoint)
        except asyncio.CancelledError:
            while not checkpoint.done():
                try:
                    await asyncio.shield(checkpoint)
                except asyncio.CancelledError:
                    continue
            checkpoint.result()
            raise

    def _is_crew_assignee(self, agent_id: str) -> bool:
        """True iff ``agent_id`` resolves to a live crew agent.

        Mirrors ``AgentGroupChatService._is_crew`` via the shared public
        ``is_crew_agent`` predicate (ontology=None — the legacy crew-type path,
        AD-918 test precedent), None-guarding an unresolvable id.
        """
        agent = self._registry.get(agent_id)
        return bool(agent) and is_crew_agent(agent, None)

    async def _resolve_task_room(
        self,
        parent: WorkItem,
        children: list[WorkItem],
    ) -> ChatThread | None:
        """Resolve one authoritative existing room, or create one for legacy work."""
        runtime = self._runtime
        store = getattr(runtime, "chat_thread_store", None)
        if store is not None:
            rooms = await asyncio.to_thread(
                store.list_threads,
                task_id=parent.id,
                include_archived=True,
                limit=2,
            )
            if len(rooms) == 1:
                return rooms[0]
            if len(rooms) > 1:
                raise ValueError("crew_task_room_cardinality_invalid")
        if parent.work_type == "crew_session":
            raise ValueError("crew_session_thread_not_found")

        group_chat_cfg = getattr(getattr(runtime, "config", None), "group_chat", None)
        if not getattr(group_chat_cfg, "auto_task_room_enabled", False):
            return None
        service = getattr(runtime, "agent_group_chat", None)
        if service is None or store is None:
            logger.debug(
                "AD-925: group-chat substrate not wired on runtime; skipping "
                "task room for parent %s.",
                parent.id,
            )
            return None

        # >=2 DISTINCT crew assignees (a single-agent task needs no room).
        crew_assignees = sorted(
            {
                c.assigned_to
                for c in children
                if c.assigned_to and self._is_crew_assignee(c.assigned_to)
            }
        )
        if len(crew_assignees) < 2:
            return None

        title = (
            f"Task: {parent.title}"
            if parent.title
            else f"Task {parent.id}"
        )
        # The first crew assignee is the creator: it passes the service's
        # _is_crew gate and is auto-added as a participant, so the final
        # participants are exactly the crew child-assignees.
        creator_id = crew_assignees[0]
        result = service.create_group_chat(
            creator_id=creator_id,
            title=title,
            participants=crew_assignees[1:],
            task_id=parent.id,
        )
        if result.ok and result.thread is not None:
            logger.info(
                "AD-925: opened task room %s for parent %s (%d crew, creator=%s).",
                result.thread.id,
                parent.id,
                len(crew_assignees),
                creator_id,
            )
            return result.thread
        else:
            logger.info(
                "AD-925: task room not opened for parent %s (%s); fan-out continues.",
                parent.id,
                result.error or "unknown",
            )
        return None

    async def _start_crew_session(
        self,
        parent: WorkItem,
        resolved_thread: ChatThread | None,
    ) -> None:
        if parent.work_type != "crew_session":
            return
        service = self._crew_session_service
        if service is None:
            raise ValueError("crew_session_service_unavailable")
        contract = await service.get_session(parent.id)
        if contract is None:
            raise ValueError("crew_session_not_initialized")
        if resolved_thread is None or resolved_thread.id != contract.thread_id:
            raise ValueError("crew_session_thread_mismatch")
        if contract.state not in {"discussing", "executing"}:
            raise ValueError("crew_session_state_not_executable")
        if contract.state == "executing":
            return
        recovery = await service.get_recovery(parent.id)
        if recovery is not None:
            values = recovery.model_dump(mode="json")
            values["phase"] = "executing"
            next_recovery = type(recovery).model_validate(values)
            await service.transition_session(
                parent.id,
                "executing",
                expected_revision=contract.revision,
                expected_recovery=recovery,
                recovery=next_recovery,
            )
            return
        await service.transition_session(
            parent.id,
            "executing",
            expected_revision=contract.revision,
        )

    async def _persist_terminal_result(
        self,
        *,
        parent_id: str,
        child: WorkItem,
        thread_id: str,
        status: str,
        stopped_reason: str,
        output: Any,
        tool_trace_ref: Any,
        actual_tokens: Any,
        artifact_refs: Any,
        started_at: float,
        finished_at: float,
        blocked_dependency_ids: list[str],
        expected_status: str,
        dependency_input_invalid: bool = False,
    ) -> SubtaskResult:
        spec_id = str(child.metadata.get("spec_id", child.id))
        normalized_reason = (
            stopped_reason if stopped_reason in _STOPPED_REASONS else "error"
        )
        assigned_to: str | None = None
        tokens = 0
        trace_ref: str | None = None
        refs: list[dict[str, Any]] = []
        result_blocked_dependency_ids: list[str] = []
        result_reason = normalized_reason
        persisted = False
        state_preconditions: dict[str, Any] | None = None
        evidence_normalized = False
        deferred_cancellation: asyncio.CancelledError | None = None
        try:
            child_id = _bounded_id(child.id)
            parent_key = _bounded_id(parent_id)
            assigned_to = (
                _bounded_id(child.assigned_to)
                if child.assigned_to
                else None
            )
            exact_unresolved_dependency_ids = (
                _exact_dependency_ids(blocked_dependency_ids)
                if normalized_reason == "dependency_blocked"
                else []
            )
            state_preconditions = {
                "expected_assigned_to_exact": assigned_to,
                "expected_parent_id": parent_key,
                "expected_depends_on": (
                    child.depends_on
                    if dependency_input_invalid
                    else _exact_dependency_ids(child.depends_on)
                ),
            }
            if not dependency_input_invalid:
                state_preconditions["expected_unresolved_dependency_ids"] = (
                    exact_unresolved_dependency_ids
                )
            tokens = _normalize_tokens(actual_tokens)
            trace_ref = _normalize_trace_ref(tool_trace_ref, child_id)
            refs = _normalize_artifact_refs(
                artifact_refs,
                thread_id=_bounded_id_or_empty(thread_id),
                child_id=child_id,
            )
            evidence = _build_execution_evidence(
                parent_id=parent_key,
                child=child,
                thread_id=thread_id,
                status=status,
                stopped_reason=normalized_reason,
                output=output,
                tool_trace_ref=trace_ref,
                artifact_refs=refs,
                actual_tokens=tokens,
                started_at=started_at,
                finished_at=finished_at,
                blocked_dependency_ids=blocked_dependency_ids,
            )
            metadata_patch: dict[str, Any] = {"crew_execution": evidence}
            if status == "done":
                parent = await self._store.get_work_item(parent_key)
                if parent is not None and parent.work_type == "crew_session":
                    if self._attachment_store is None or type(output) is not str:
                        raise ValueError("crew_execution_output_invalid")
                    output_bytes = output.encode("utf-8", errors="strict")
                    if not 1 <= len(output_bytes) <= _MAX_OUTPUT_BYTES:
                        raise ValueError("crew_execution_output_invalid")
                    content_hash = hashlib.sha256(output_bytes).hexdigest()
                    await self._attachment_store.write(
                        content_hash,
                        output_bytes,
                        "text/plain",
                        origin="agent_artifact",
                    )
                    readback = await self._attachment_store.read(content_hash)
                    if (
                        readback != output_bytes
                        or hashlib.sha256(readback).hexdigest() != content_hash
                    ):
                        raise ValueError("crew_execution_output_invalid")
                    metadata_patch["crew_execution_output"] = {
                        "version": 1,
                        "content_hash": content_hash,
                        "mime": "text/plain",
                        "size_bytes": len(output_bytes),
                    }
            refs = [dict(ref) for ref in evidence["artifact_refs"]]
            result_blocked_dependency_ids = list(
                evidence["blocked_dependency_ids"]
            )
            evidence_normalized = True
            commit_error: BaseException | None = None
            try:
                updated = await self._store.merge_work_item_metadata(
                    child_id,
                    metadata_patch,
                    expected_work_type=child.work_type,
                    expected_status=expected_status,
                    new_status=status,
                    actual_tokens_delta=tokens,
                    source="crew_executor",
                    **state_preconditions,
                )
            except asyncio.CancelledError as exc:
                commit_error = exc
            except Exception as exc:
                commit_error = exc
            if commit_error is not None:
                updated, reconciliation_cancellation = (
                    await self._reconcile_terminal_commit(
                        child=child,
                        expected_status=status,
                        metadata_patch=metadata_patch,
                        actual_tokens_delta=tokens,
                        initial_cancellation=(
                            commit_error
                            if isinstance(commit_error, asyncio.CancelledError)
                            else None
                        ),
                    )
                )
                if reconciliation_cancellation is not None:
                    deferred_cancellation = reconciliation_cancellation
                if updated is None:
                    if deferred_cancellation is None:
                        raise commit_error
                    raise ValueError("crew_execution_persistence_cancelled")
            if updated is None:
                raise ValueError("crew_execution_persistence_failed")
            persisted = True
            output_record = metadata_patch.get("crew_execution_output")
            if status == "done" and type(output_record) is dict:
                self._append_crew_session_child_result(
                    parent_id=parent_key,
                    child=child,
                    thread_id=thread_id,
                    output=output,
                    content_hash=output_record["content_hash"],
                    finished_at=evidence["finished_at"],
                )
        except Exception as exc:
            state_conflict = (
                isinstance(exc, ValueError)
                and str(exc) in {
                    "work_item_state_conflict",
                    "work_item_dependency_state_conflict",
                }
            )
            if state_conflict:
                logger.error(
                    "Crew child %s terminal evidence for reason %s conflicted "
                    "with live ownership, parent, or dependency state; the "
                    "stale writer will attach no evidence and will not mutate "
                    "the authoritative row",
                    child.id,
                    normalized_reason,
                    exc_info=True,
                )
            else:
                logger.error(
                    "Crew child %s terminal evidence for reason %s could not be "
                    "committed atomically; it will not unblock dependents and a "
                    "validated in_progress-to-failed fallback will be attempted",
                    child.id,
                    normalized_reason,
                    exc_info=True,
                )
                result_reason = "error"
                if not evidence_normalized:
                    tokens = 0
                    trace_ref = None
                    refs = []
                    result_blocked_dependency_ids = []
            if (
                expected_status == "in_progress"
                and not state_conflict
                and state_preconditions is not None
            ):
                try:
                    fallback = await self._store.merge_work_item_metadata(
                        child.id,
                        {},
                        expected_work_type=child.work_type,
                        expected_status=expected_status,
                        new_status="failed",
                        actual_tokens_delta=0,
                        source="crew_executor_persistence_fallback",
                        **state_preconditions,
                    )
                    if fallback is None:
                        raise ValueError("crew_execution_fallback_failed")
                except Exception as fallback_exc:
                    fallback_conflict = (
                        isinstance(fallback_exc, ValueError)
                        and str(fallback_exc) in {
                            "work_item_state_conflict",
                            "work_item_dependency_state_conflict",
                        }
                    )
                    if fallback_conflict:
                        logger.error(
                            "Crew child %s persistence fallback conflicted with "
                            "live ownership, parent, or dependency state; the "
                            "authoritative row remains untouched and the caller "
                            "receives failed",
                            child.id,
                            exc_info=True,
                        )
                    else:
                        logger.error(
                            "Crew child %s evidence and fallback status "
                            "persistence both failed; the caller receives failed "
                            "and must not treat the child as complete",
                            child.id,
                            exc_info=True,
                        )
        if deferred_cancellation is not None:
            raise deferred_cancellation
        result_status = status if persisted else "failed"
        return SubtaskResult(
            work_item_id=child.id,
            spec_id=spec_id,
            agent_id=assigned_to or "",
            output=output if type(output) is str else "",
            status=result_status,
            tool_trace_ref=trace_ref,
            started_at=started_at,
            finished_at=finished_at,
            stopped_reason=result_reason,
            actual_tokens=tokens,
            artifact_refs=refs,
            blocked_dependency_ids=result_blocked_dependency_ids,
        )

    def _append_crew_session_child_result(
        self,
        *,
        parent_id: str,
        child: WorkItem,
        thread_id: str,
        output: object,
        content_hash: object,
        finished_at: object,
    ) -> None:
        thread_store = getattr(self._runtime, "chat_thread_store", None)
        if thread_store is None:
            logger.warning(
                "Crew child %s committed successfully but no chat-thread store "
                "is available; resume will retry transcript repair",
                child.id,
            )
            return
        try:
            parent_key = _bounded_id(parent_id)
            child_key = _bounded_id(child.id)
            room_key = _bounded_id(thread_id)
            author_id = _bounded_id(child.assigned_to)
            if (
                type(output) is not str
                or type(content_hash) is not str
                or _SHA_RE.fullmatch(content_hash) is None
                or type(finished_at) is not float
                or not math.isfinite(finished_at)
                or finished_at < 0
            ):
                raise ValueError("crew_execution_message_invalid")
            message_id = hashlib.sha256(
                b"probos:crew-session-child-result:v1\x00"
                + parent_key.encode("utf-8")
                + b"\x00"
                + child_key.encode("utf-8")
                + b"\x00"
                + content_hash.encode("ascii")
            ).hexdigest()
            message = thread_store.append_message_once(
                room_key,
                message_id=message_id,
                author_id=author_id,
                role="agent",
                body=output,
                created_at=finished_at,
                metadata={
                    "source": "crew_session_child_result",
                    "parent_id": parent_key,
                    "work_item_id": child_key,
                    "content_hash": content_hash,
                },
            )
            if message is None:
                raise ValueError("crew_execution_message_thread_missing")
        except Exception:
            logger.warning(
                "Crew child %s committed successfully but its room message "
                "could not be repaired; a later resume can retry idempotently",
                child.id,
                exc_info=True,
            )

    async def _reconcile_terminal_commit(
        self,
        *,
        child: WorkItem,
        expected_status: str,
        metadata_patch: dict[str, Any],
        actual_tokens_delta: int,
        initial_cancellation: asyncio.CancelledError | None,
    ) -> tuple[WorkItem | None, asyncio.CancelledError | None]:
        current_task = asyncio.current_task()
        if initial_cancellation is not None and current_task is not None:
            current_task.uncancel()
        expected_metadata = dict(child.metadata)
        expected_metadata.update(metadata_patch)
        expected_actual_tokens = child.actual_tokens + actual_tokens_delta

        async def _load_and_prove() -> WorkItem | None:
            authoritative = await self._store.get_work_item(child.id)
            if (
                authoritative is None
                or authoritative.id != child.id
                or authoritative.work_type != child.work_type
                or authoritative.status != expected_status
                or authoritative.assigned_to != child.assigned_to
                or authoritative.parent_id != child.parent_id
                or authoritative.depends_on != child.depends_on
                or authoritative.actual_tokens != expected_actual_tokens
                or type(authoritative.metadata) is not dict
                or not _json_dicts_exactly_equal(
                    authoritative.metadata,
                    expected_metadata,
                )
            ):
                return None
            return authoritative

        reconciliation = asyncio.create_task(
            _load_and_prove(),
            name=f"crew-terminal-reconcile:{child.id}",
        )
        first_cancellation = initial_cancellation
        while not reconciliation.done():
            try:
                await asyncio.shield(reconciliation)
            except asyncio.CancelledError as exc:
                if first_cancellation is None:
                    first_cancellation = exc
                current_task = asyncio.current_task()
                if current_task is not None:
                    current_task.uncancel()
        try:
            authoritative = reconciliation.result()
        except Exception:
            logger.exception(
                "Crew child %s terminal reconciliation could not inspect exact "
                "post-commit authority; the original persistence disposition "
                "continues to its cancellation or fallback path",
                child.id,
            )
            authoritative = None
        return authoritative, first_cancellation

    def _unresolved_dependency_ids(
        self,
        child: WorkItem,
        done_ids: set[str],
    ) -> list[str]:
        return [
            dependency_id
            for dependency_id in _exact_dependency_ids(child.depends_on)
            if dependency_id not in done_ids
        ]

    def _emit_subtask_completed(
        self,
        parent_id: str,
        result: SubtaskResult,
    ) -> None:
        self._emit(
            EventType.SUBTASK_COMPLETED,
            {
                "parent_id": parent_id,
                "work_item_id": result.work_item_id,
                "spec_id": result.spec_id,
                "agent_id": result.agent_id,
                "status": result.status,
            },
        )

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Publish a lifecycle event, honest-degrading when no emit fn is wired."""
        if self._emit_fn is None:
            return
        try:
            self._emit_fn(event_type, data)
        except Exception:
            logger.warning(
                "Crew executor failed to emit %s; continuing without the event.",
                getattr(event_type, "value", event_type),
                exc_info=True,
            )
