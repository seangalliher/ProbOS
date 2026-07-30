"""AD-1165: a conversational turn that outgrows a reply becomes a task.

A Captain DM is dispatched with ``ttl_seconds=60.0`` (``routers/agents.py``),
enforced by ``IntentBus`` as ``wait_for(handler(intent), timeout=...)``. That
deadline is **correct for a reply** — a conversational answer should be fast,
and a hung agent should not hold the chat open. It is wrong for *work*. When
AD-1065's conversational agentic loop is asked to do something real (drive a
browser, produce a document) the turn routinely runs past 60s, the handler is
cancelled mid-flight, and the Captain gets ``(error: Agent did not respond in
time.)`` — for a turn in which the agent was working correctly.

Raising the TTL is the wrong fix. It trades one arbitrary ceiling for a larger
one, and it makes every genuinely hung turn hold the chat hostage for longer.
The Captain's framing is the design:

    "we came up with a structure where we could have a TTL for chat based
    requests and then the concept of the agent creating tasks that could run in
    the background async and allow me to keep chatting."

So the chat TTL is untouched. Work that does not fit inside a reply stops being
a reply and becomes a **task**: durable on the work board, executing in the
background, reporting into the same thread when it lands. The Captain keeps
chatting.

Three properties of this implementation are load-bearing:

**1. Promotion is decided by elapsed evidence, never by classification.**
There is no "is this task-shaped?" model call and no keyword heuristic. A turn
is promoted precisely because it *has already* run past the configured budget,
which is the only signal that is never wrong about the thing it measures. A
fast turn is therefore untouched: it completes and returns before the timer is
ever consulted.

**2. The in-flight run is never restarted.** Promotion stops *waiting* for the
loop; it does not cancel it. The same ``asyncio.Task`` continues with its full
message history, its tool trace and whatever side effects it has already
produced. A design that cancelled and re-dispatched would redo every click and
every write the agent had already performed — the browser work this AD exists
to unblock is exactly the kind that must not be replayed.

**3. Every failure degrades to today's behaviour, never past it.** No thread to
report into, no work-item store, a store that raises — each falls back to
awaiting the run inline, which is precisely what happens with the feature off.
The worst outcome of a bug here is the 60s TTL the Captain already has; it can
never be a lost turn or a task with nowhere to report.

The promoted work item is deliberately **not dispatchable**: it carries neither
``metadata["dispatchable"]`` nor a tag in ``hybrid_dispatch.dispatchable_tags``
(``["consultation"]`` at HEAD), so ``WorkItemRouter`` leaves it alone. The run
already has an owner — the agent whose turn it was — and routing it a second
time would execute it twice. The item is the durable *record* of work in
flight, not a request for someone to start it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# Bounds on what is copied out of the Captain's message into the work item.
# The description carries the request so the board row is readable on its own;
# the title is a one-line handle for a card.
_TITLE_MAX_CHARS = 120
_DESCRIPTION_MAX_CHARS = 4000

# ``metadata["source"]`` on the promoted item. Distinguishes an item this module
# created from one the Captain or the crew orchestrator raised, so a later
# reader (board filter, reconciler, audit) can tell who owns the execution.
PROMOTION_SOURCE = "dm_agentic_promotion"

# Tag applied to promoted items. Chosen so it is NOT in the shipped
# ``HybridDispatchConfig.dispatchable_tags`` (``["consultation"]``) — see the
# module docstring on why double dispatch must be impossible here. A drift guard
# in tests/test_ad1165_turn_promotion.py asserts the two never overlap.
PROMOTION_TAG = "conversational-turn"

# Every string below is asserted clean against the REAL
# ``decomposer._CAPABILITY_GAP_RE`` by the test suite. That regex reads a reply
# as "the agent is reporting a capability gap" and routes it into
# self-modification, so an acknowledgement that trips it would make the runtime
# try to *design a new agent* every time a turn ran long. The phrasing is
# constrained accordingly: no "can't" / "cannot" / "unable to" / "not
# available", and no word containing the bare substring "lack".
#
# The acknowledgement also has to be true at the moment it is spoken. It says
# the work is running, because it is — the task is already executing when this
# text is returned.
_ACK_TEMPLATE: str = (
    "I've started on that. It runs longer than a single reply fits, so I opened "
    "task {work_item_id} and I'm working it in the background. Keep chatting — "
    "I'll report back here as soon as it lands."
)

# Posted when a promoted run finishes having produced no text of its own. Rare
# (BF-697 made the iteration-cap exit report its work) but it must not be
# silence: the Captain was told a report would arrive.
_REPORT_EMPTY: str = "That background task is finished."

# Posted when a promoted run raised. Deliberately does not speculate about the
# cause — the traceback goes to the log, and the work item moves to ``failed``
# so the board shows it rather than leaving a row stuck ``in_progress``.
_REPORT_FAILED: str = (
    "I stopped partway through that background task. The details are in the "
    "ship's log and the task is marked so it shows on the board."
)


def _shorten(text: str, limit: int) -> str:
    """Collapse ``text`` to a single bounded line."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: max(0, limit - 1)].rstrip() + "\u2026"


async def _create_promoted_work_item(
    *,
    runtime: Any,
    agent_id: str,
    thread_id: str,
    request_text: str,
) -> Any | None:
    """Create the durable record for a turn that is being promoted.

    Returns the created ``WorkItem``, or ``None`` when no durable record could
    be made — in which case the caller must NOT acknowledge, because there
    would be nothing for the acknowledgement to point at.
    """
    store = getattr(runtime, "work_item_store", None)
    if store is None:
        return None
    title = _shorten(request_text, _TITLE_MAX_CHARS) or "Background task"
    description = str(request_text or "")[:_DESCRIPTION_MAX_CHARS]
    try:
        item = await store.create_work_item(
            title=title,
            description=description or title,
            work_type="task",
            assigned_to=agent_id,
            created_by="captain",
            tags=[PROMOTION_TAG],
            metadata={
                "source": PROMOTION_SOURCE,
                "thread_id": thread_id,
                "agent_id": agent_id,
            },
        )
    except Exception:
        logger.warning(
            "AD-1165: could not create the work item for a promoted turn on "
            "agent=%s thread=%s; the run stays inline and keeps the chat TTL",
            agent_id, thread_id, exc_info=True,
        )
        return None
    if item is None:
        return None
    # ``task`` starts ``open``; the run is already executing, so the board must
    # say so. ``open -> in_progress`` requires an assignee, which is set above.
    try:
        await store.transition_work_item(item.id, "in_progress", source=agent_id)
    except Exception:
        logger.warning(
            "AD-1165: work item %s stays 'open' — the transition to in_progress "
            "failed; the run itself is unaffected and still reports back",
            item.id, exc_info=True,
        )
    return item


def _post_report(
    *,
    runtime: Any,
    agent_id: str,
    thread_id: str,
    work_item_id: str,
    body: str,
) -> None:
    """Append a promoted run's report into the thread it came from.

    Synchronous on purpose — ``ChatThreadStore`` is a synchronous SQLite store,
    and its commit callback is what emits ``CHAT_THREAD_MESSAGE_APPENDED``, the
    event the HXI already consumes to live-refresh an open transcript (AD-1133).
    So the Captain sees the report arrive without any new UI wiring.
    """
    store = getattr(runtime, "chat_thread_store", None)
    if store is None:
        logger.warning(
            "AD-1165: no chat_thread_store — the report for work item %s has "
            "nowhere to land; it is recorded here instead: %s",
            work_item_id, _shorten(body, 400),
        )
        return
    try:
        store.append_message(
            thread_id,
            author_id=agent_id,
            role="agent",
            body=body,
            metadata={"work_item_id": work_item_id, "source": PROMOTION_SOURCE},
        )
    except Exception:
        logger.warning(
            "AD-1165: failed to post the report for work item %s into thread "
            "%s; it is recorded here instead: %s",
            work_item_id, thread_id, _shorten(body, 400), exc_info=True,
        )


async def _finish_promoted_turn(
    task: "asyncio.Task[str]",
    *,
    runtime: Any,
    agent_id: str,
    thread_id: str,
    work_item_id: str,
) -> None:
    """Await a promoted run, report it into the thread, close the work item.

    Never raises apart from cancellation: this runs detached from any caller,
    so an exception here would surface only as an unretrieved-task warning.
    """
    text = ""
    failed = False
    try:
        text = await task
    except asyncio.CancelledError:
        # The run was cancelled (agent recycled, loop shutting down). Leave the
        # work item ``in_progress`` — it is genuinely unfinished, and inventing
        # a terminal status would tell the board a completed story about work
        # that simply stopped.
        logger.info(
            "AD-1165: promoted turn for work item %s was cancelled; it stays "
            "in_progress on the board",
            work_item_id,
        )
        raise
    except Exception:
        failed = True
        logger.warning(
            "AD-1165: promoted turn for work item %s failed",
            work_item_id, exc_info=True,
        )

    body = (str(text or "").strip() or _REPORT_EMPTY) if not failed else _REPORT_FAILED
    _post_report(
        runtime=runtime,
        agent_id=agent_id,
        thread_id=thread_id,
        work_item_id=work_item_id,
        body=body,
    )

    store = getattr(runtime, "work_item_store", None)
    if store is None:
        return
    try:
        await store.transition_work_item(
            work_item_id, "failed" if failed else "done", source=agent_id,
        )
    except Exception:
        logger.warning(
            "AD-1165: could not close work item %s; the report was posted and "
            "the row stays in_progress",
            work_item_id, exc_info=True,
        )


async def run_with_promotion(
    work: Callable[[], Awaitable[str]],
    *,
    promote_after_seconds: float,
    runtime: Any,
    agent_id: str,
    thread_id: str,
    request_text: str,
    hold: set["asyncio.Task[Any]"],
) -> str:
    """Run ``work``; promote it to a background task if it outlives the budget.

    Returns the run's own text when it completes within ``promote_after_seconds``
    (identical to awaiting ``work()`` directly), or an acknowledgement naming the
    work item when it does not.

    ``hold`` is the caller's task registry. Both the run and its reporter are
    added to it so neither is garbage-collected mid-flight, and both discard
    themselves on completion.

    Exceptions raised by ``work`` propagate unchanged on the inline path, so the
    caller's existing honest-degrade is untouched. Once promoted they are caught
    by the reporter instead, because there is no longer a caller to raise into.

    If the CALLER is cancelled while waiting (the chat TTL firing before the
    budget elapses, which means the budget was misconfigured above the TTL) the
    run is deliberately not cancelled with it — it stays in ``hold`` and
    finishes, unreported. Losing a report is a smaller harm than killing work
    the Captain asked for, which is the same judgement rule 6 of the control
    lease was written under.
    """
    if promote_after_seconds <= 0.0:
        return await work()

    task: "asyncio.Task[str]" = asyncio.create_task(
        work(), name=f"ad1165-turn-{agent_id[:8]}",
    )
    hold.add(task)
    task.add_done_callback(hold.discard)

    done, _pending = await asyncio.wait({task}, timeout=promote_after_seconds)
    if task in done:
        # Fast path: the turn was a reply after all. ``result()`` re-raises the
        # run's exception into the caller exactly as a direct await would.
        return task.result()

    # The run has outlived a reply. Give it a durable home before saying so.
    work_item = None
    if thread_id:
        work_item = await _create_promoted_work_item(
            runtime=runtime,
            agent_id=agent_id,
            thread_id=thread_id,
            request_text=request_text,
        )
    if work_item is None:
        # No thread to report into, or no durable record could be made. Wait it
        # out inline — that is today's behaviour, including today's TTL risk.
        # Acknowledging here would promise a report that nothing would deliver.
        logger.info(
            "AD-1165: agent=%s has no promotable destination (thread=%r); the "
            "turn stays inline under the chat TTL",
            agent_id, thread_id,
        )
        return await task

    reporter = asyncio.create_task(
        _finish_promoted_turn(
            task,
            runtime=runtime,
            agent_id=agent_id,
            thread_id=thread_id,
            work_item_id=work_item.id,
        ),
        name=f"ad1165-report-{work_item.id[:8]}",
    )
    hold.add(reporter)
    reporter.add_done_callback(hold.discard)

    logger.info(
        "AD-1165: promoted agent=%s turn to work item %s after %.1fs; the run "
        "continues in the background and reports into thread %s",
        agent_id, work_item.id, promote_after_seconds, thread_id,
    )
    return _ACK_TEMPLATE.format(work_item_id=work_item.id)
