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
import hashlib
import logging
import time
from typing import Any, Awaitable, Callable

from probos.cognitive.dm.bypass_egress import compose_bypass_reply

logger = logging.getLogger(__name__)

# Bounds on what is copied out of the Captain's message into the work item.
# The description carries the request so the board row is readable on its own;
# the title is a one-line handle for a card.
_TITLE_MAX_CHARS = 120
_DESCRIPTION_MAX_CHARS = 4000

# AD-1226: how much of a promoted run's report is copied into the episode's
# ``outcome["response"]``.
#
# This number is a decision, not an inheritance (Design Principle 13a). It used
# to be 500 and it was a *partial copy of the payload* — measured on the
# reference vessel, a 1362-char fifteen-row table was stored as 500 chars and
# seven rows, cut mid-word at "| charset-normalizer | 3.4.9 | The Real Fi". A
# truncated copy is the worst of both worlds: too big to be a summary and too
# small to be the answer.
#
# With the ref in place the stored text no longer has to *be* the payload. It
# has two jobs and both are small: it feeds the semantic embedding that makes
# the episode findable, and it renders as one line of the memory section. The
# full text is retrievable on demand through ``recall_artifact``, so 240 chars
# buys a findable, readable cue without spending prompt budget on a copy.
#
# Only applied when ``memory.recall_outcome_refs_enabled`` is on — shrinking
# the stored text is only defensible *because* the ref exists.
_OUTCOME_DIGEST_CHARS = 240

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

# BF-704: ``AgenticResult.stopped_reason`` values that mean the run STOPPED
# rather than finished. A turn that exhausted its step budget produced partial
# work and said so; closing its work item ``done`` tells the board a completed
# story about work that is still open. Observed on the reference vessel: item
# ``fa516242ed24`` read ``status='done'`` beside its own report, "I stopped here
# because this turn reached its step limit... the task is still open."
#
# There is no ``paused``/``incomplete`` status in the AD-498 state machine
# (``open|in_progress|done|failed``), and inventing one to carry this is a
# larger change than the defect warrants. So an incomplete run performs NO
# terminal transition and the row stays ``in_progress`` — which is exactly the
# judgement the cancellation branch below already makes, for the same reason.
_INCOMPLETE_STOP_REASONS: frozenset[str] = frozenset({
    "max_iterations", "token_budget",
})


def _shorten(text: str, limit: int) -> str:
    """Collapse ``text`` to a single bounded line."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: max(0, limit - 1)].rstrip() + "\u2026"


def _outcome_digest(body: str, limit: int = _OUTCOME_DIGEST_CHARS) -> str:
    """AD-1226: a short, whole cue for ``outcome["response"]``.

    Cuts on the last line boundary inside ``limit`` when there is one, so a
    markdown table never ends mid-cell and the rendered memory line never shows
    the Captain half a row. Falls back to a hard cut only when the first line
    is itself longer than the cap.
    """
    text = str(body or "")
    if len(text) <= limit:
        return text
    window = text[:limit]
    cut = window.rfind("\n")
    if cut > 0:
        return window[:cut].rstrip()
    return window


async def _store_outcome_artifact(
    *,
    runtime: Any,
    agent_id: str,
    thread_id: str,
    work_item_id: str,
    body: str,
) -> dict[str, Any] | None:
    """AD-1226: persist a promoted run's full report and describe where it went.

    Returns the ``artifact_ref`` to embed in the episode's outcome, or ``None``
    when nothing durable could be written — in which case the episode is stored
    exactly as it would have been, carrying its digest and no ref, and recall
    renders no "you produced" cue rather than one pointing at nothing.

    Log-and-degrade throughout. An artifact that fails to store must never turn
    a delivered report into a failed one; by the time this runs the Captain
    already has the text in the thread.
    """
    attachment_store = getattr(runtime, "attachment_store", None)
    if attachment_store is None or not body:
        return None

    blob = str(body).encode("utf-8")
    content_hash = hashlib.sha256(blob).hexdigest()
    try:
        await attachment_store.write(
            content_hash, blob, "text/markdown", origin="agent_artifact",
        )
    except Exception:
        logger.warning(
            "AD-1226: could not store the artifact for work item %s; the report "
            "was delivered and the episode still carries its digest, but the "
            "full text will not be re-readable through recall_artifact",
            work_item_id, exc_info=True,
        )
        return None

    # The name is the handle a human (or the agent) recognises on the board.
    name = f"task-{work_item_id}"
    artifact_id = ""
    artifact_store = getattr(runtime, "artifact_store", None)
    if artifact_store is not None and thread_id:
        try:
            artifact = artifact_store.add_version(
                thread_id=thread_id,
                name=name,
                content_hash=content_hash,
                mime="text/markdown",
                size_bytes=len(blob),
                created_by=agent_id,
            )
            artifact_id = str(getattr(artifact, "id", "") or "")
        except Exception:
            # Non-fatal by design: the attachment ref alone is enough to fetch
            # by, so the agent can still read its own work back. Only the
            # artifact drawer's version chain is missing an entry.
            logger.warning(
                "AD-1226: stored the artifact bytes for work item %s but could "
                "not register a version on thread %s; the text is still "
                "readable by content hash and only the version chain is short "
                "one entry",
                work_item_id, thread_id, exc_info=True,
            )

    return {
        "content_hash": content_hash,
        "mime": "text/markdown",
        "size_bytes": len(blob),
        "chars": len(body),
        "artifact_id": artifact_id,
        "name": name,
    }


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
    tool_failures: Any = None,
) -> str:
    """Append a promoted run's report into the thread it came from.

    Synchronous on purpose — ``ChatThreadStore`` is a synchronous SQLite store,
    and its commit callback is what emits ``CHAT_THREAD_MESSAGE_APPENDED``, the
    event the HXI already consumes to live-refresh an open transcript (AD-1133).
    So the Captain sees the report arrive without any new UI wiring.

    AD-1248: composes the disclosure and RETURNS the composed text, because this
    route has two Captain-visible sinks -- this thread post and the outcome
    artifact -- and composing twice is how one of them ends up with a different
    story. Render once per route, reuse.
    """
    from probos.dm_reply import DmReply, ToolFailures

    if tool_failures is not None and not isinstance(tool_failures, ToolFailures):
        # The probe is caller-supplied and typed ``Any``. A wrong shape here
        # would raise inside a DETACHED reporter whose contract is "never raises
        # apart from cancellation", costing the Captain the whole report.
        logger.warning(
            "AD-1248: failure probe for work item %s returned %s, not "
            "ToolFailures; the report is delivered without a disclosure",
            work_item_id, type(tool_failures).__name__,
        )
        tool_failures = None
    try:
        body = str(DmReply(
            body=body,
            tool_failures=tool_failures if tool_failures is not None else ToolFailures(),
        ).render())
    except Exception:
        logger.warning(
            "AD-1248: could not compose the disclosure for work item %s; the "
            "report is delivered with its body unchanged",
            work_item_id, exc_info=True,
        )
    store = getattr(runtime, "chat_thread_store", None)
    if store is None:
        logger.warning(
            "AD-1165: no chat_thread_store — the report for work item %s has "
            "nowhere to land; it is recorded here instead: %s",
            work_item_id, _shorten(body, 400),
        )
        return body
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
    return body


async def _store_promoted_episode(
    *,
    runtime: Any,
    agent_id: str,
    thread_id: str,
    work_item_id: str,
    request_text: str,
    body: str,
    complete: bool,
    failed: bool,
) -> None:
    """AD-1166: put a promoted run's REAL outcome into episodic memory.

    ``DmReplyPipeline.step_5_episodic_store`` runs when the turn returns, and
    for a promoted turn what it returns is the acknowledgement. So the episode
    recorded for this interaction says "I've started on that, I opened task X"
    — and what the agent actually did, and whether it worked, reached neither
    recall nor dreaming nor trust nor Hebbian routing.

    Promoted turns are by construction the *hard* ones. They were the only ones
    the system learned nothing from.

    A second episode is stored rather than the first amended, because there is
    no amend API: ``EpisodicMemory`` exposes only ``update_episode_validity``,
    which moves a validity window and cannot touch content. Inventing a
    content-mutation path to fix a reporting gap would be the larger change and
    the riskier one. The two are linked by ``correlation_id`` = the work item,
    so a later consolidation can pair them.

    Log-and-degrade throughout: an episode that fails to store must never turn
    a delivered report into a failed one.

    AD-1226: when ``memory.recall_outcome_refs_enabled`` is on, the full report
    is also written to the content-addressable stores and the outcome carries a
    ref to it, so the agent can read its own work back later instead of having
    to carry it. OFF ⇒ this function is byte-identical to AD-1166.
    """
    memory = getattr(runtime, "episodic_memory", None)
    if memory is None:
        return

    # AD-1226: one flag, read once. OFF ⇒ no artifact write, no ref key, and
    # the AD-1166 ``body[:500]`` response verbatim.
    refs_enabled = bool(getattr(
        getattr(getattr(runtime, "config", None), "memory", None),
        "recall_outcome_refs_enabled",
        False,
    ))
    artifact_ref: dict[str, Any] | None = None
    if refs_enabled:
        try:
            artifact_ref = await _store_outcome_artifact(
                runtime=runtime,
                agent_id=agent_id,
                thread_id=thread_id,
                work_item_id=work_item_id,
                body=body,
            )
        except Exception:
            # Defence in depth: the helper already degrades internally, so
            # reaching here means something unforeseen. The report is already
            # delivered and must stay delivered.
            logger.warning(
                "AD-1226: artifact capture for work item %s failed outright; "
                "the report was delivered and the episode is stored without a "
                "re-readable ref",
                work_item_id, exc_info=True,
            )
            artifact_ref = None

    try:
        import time as _time

        from probos.cognitive.episodic import resolve_sovereign_id
        from probos.types import AnchorFrame, Episode

        # Sovereignty: episode ``agent_ids`` must carry the sovereign id, not
        # the pool id. ``resolve_sovereign_id`` already falls back to
        # ``agent.id``, so a registry miss degrades to the same value the
        # caller holds rather than to something wrong.
        sovereign_id = agent_id
        try:
            registry = getattr(runtime, "registry", None)
            agent = registry.get(agent_id) if registry is not None else None
            if agent is not None:
                sovereign_id = resolve_sovereign_id(agent)
        except Exception:
            logger.debug(
                "AD-1166: could not resolve a sovereign id for %s; the episode "
                "is stored under the pool id",
                agent_id, exc_info=True,
            )

        outcome: dict[str, Any] = {
            "intent": "direct_message",
            # A run that stopped at its step limit did partial work. It is
            # neither a success nor a failure, and recording it as either
            # would teach the wrong lesson.
            "success": bool(complete and not failed),
            "complete": bool(complete),
            # AD-1226: a short whole cue once the full text is retrievable;
            # the AD-1166 partial copy verbatim while it is not.
            "response": (
                _outcome_digest(body) if refs_enabled else body[:500]
            ),
            "session_type": "1:1",
            "source": PROMOTION_SOURCE,
            "work_item_id": work_item_id,
        }
        if artifact_ref is not None:
            outcome["artifact_ref"] = artifact_ref

        await memory.store(Episode(
            user_input=f"[1:1 background task] Captain: {request_text}",
            timestamp=_time.time(),
            agent_ids=[sovereign_id],
            correlation_id=work_item_id,
            outcomes=[outcome],
            reflection=(
                f"Captain asked for work that outgrew a reply; it ran as "
                f"background task {work_item_id} and "
                + (
                    "finished." if complete and not failed
                    else "stopped before finishing."
                )
            ),
            source="direct",
            anchors=AnchorFrame(
                channel="dm",
                trigger_type="direct_message",
                trigger_agent="captain",
                participants=["captain", agent_id],
                chat_thread_id=thread_id,
            ),
        ))
    except Exception:
        logger.warning(
            "AD-1166: could not store the episode for work item %s; the report "
            "was delivered and only the learning signal is lost",
            work_item_id, exc_info=True,
        )


async def _finish_promoted_turn(
    task: "asyncio.Task[str]",
    *,
    runtime: Any,
    agent_id: str,
    thread_id: str,
    work_item_id: str,
    request_text: str = "",
    completed_probe: Callable[[], bool] | None = None,
    failures_probe: Callable[[], Any] | None = None,
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

    if failed:
        body = _REPORT_FAILED
    else:
        # BF-702/791: a promoted run returns the agentic loop's text directly, so
        # it never passes through ``DmReplyPipeline`` -- and every marker the
        # pipeline strips reaches the transcript raw. BF-702 fixed the emotion
        # self-tag here and the A2UI block still leaked, so the transformations
        # now live in one place both bypass paths call.
        #
        # A reply that was nothing but markers composes to "" and correctly
        # falls through to the empty-report wording.
        body = compose_bypass_reply(text) or _REPORT_EMPTY
    # AD-1248: the awaited task returns a plain string, so the run's tool
    # failures cannot be recovered here -- exactly the reason BF-704 introduced
    # ``completed_probe``. Same shape, same reason. Omitting it renders
    # byte-identically to before.
    _failures = None
    if not failed and failures_probe is not None:
        try:
            _failures = failures_probe()
        except Exception:
            logger.warning(
                "AD-1248: failure probe for work item %s raised; the promoted "
                "report is delivered without a tool-failure disclosure",
                work_item_id, exc_info=True,
            )
    # AD-1248: the composed text, reused below. This route has TWO
    # Captain-visible sinks -- the thread post and the outcome artifact -- and
    # the artifact previously received the raw body, so a promoted run's stored
    # evidence disagreed with its transcript about whether a tool failed.
    reported = _post_report(
        runtime=runtime,
        agent_id=agent_id,
        thread_id=thread_id,
        work_item_id=work_item_id,
        body=body,
        tool_failures=_failures,
    )

    # BF-704: did the run finish, or did it stop? ``completed_probe`` is the
    # caller's view of the LAST pass's ``stopped_reason`` -- the awaited task
    # returns a plain string, so the reason cannot be recovered here. Absent a
    # probe the answer is "finished", which is exactly today's behaviour.
    complete = True
    if not failed and completed_probe is not None:
        try:
            complete = bool(completed_probe())
        except Exception:
            logger.debug(
                "AD-1165: completion probe for work item %s raised; treating "
                "the run as finished",
                work_item_id, exc_info=True,
            )

    await _store_promoted_episode(
        runtime=runtime,
        agent_id=agent_id,
        thread_id=thread_id,
        work_item_id=work_item_id,
        request_text=request_text,
        body=reported,
        complete=complete,
        failed=failed,
    )

    store = getattr(runtime, "work_item_store", None)
    if store is None:
        return
    if not failed and not complete:
        # Partial work, still open. No terminal transition: the row stays
        # ``in_progress``, which is the honest state and the one the Captain
        # can act on -- AD-1164 has already filed the ask about continuing.
        logger.info(
            "BF-704: promoted turn for work item %s stopped before finishing; "
            "it stays in_progress rather than closing done",
            work_item_id,
        )
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


async def _report_holding_slot(
    task: "asyncio.Task[str]",
    *,
    runtime: Any,
    agent_id: str,
    thread_id: str,
    work_item_id: str,
    request_text: str = "",
    completed_probe: Callable[[], bool] | None = None,
    failures_probe: Callable[[], Any] | None = None,
    background_slot: Callable[[], Any] | None = None,
) -> None:
    """BF-732: hold a concurrency slot for as long as the promoted run lives.

    The slot wraps the whole reporter, so it is released on every terminal path
    ``_finish_promoted_turn`` distinguishes -- completed, failed, and cancelled
    (which re-raises through the ``async with``). That is the property worth
    testing: a run that dies must not leak the capacity it was holding.

    Without a slot factory this is exactly ``_finish_promoted_turn``, so the
    default path is unchanged.

    A slot that cannot be acquired must not cost the Captain the report. If the
    manager raises, the report still runs -- unaccounted, which is today's
    behaviour and strictly better than a silent loss.
    """
    if background_slot is None:
        await _finish_promoted_turn(
            task,
            runtime=runtime,
            agent_id=agent_id,
            thread_id=thread_id,
            work_item_id=work_item_id,
            request_text=request_text,
            completed_probe=completed_probe,
            failures_probe=failures_probe,
        )
        return

    try:
        slot = background_slot()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "BF-732: could not open a concurrency slot for promoted work item "
            "%s; the run reports as before but is not counted against agent=%s "
            "capacity",
            work_item_id, agent_id, exc_info=True,
        )
        slot = None

    if slot is None:
        await _finish_promoted_turn(
            task,
            runtime=runtime,
            agent_id=agent_id,
            thread_id=thread_id,
            work_item_id=work_item_id,
            request_text=request_text,
            completed_probe=completed_probe,
            failures_probe=failures_probe,
        )
        return

    async with slot:
        await _finish_promoted_turn(
            task,
            runtime=runtime,
            agent_id=agent_id,
            thread_id=thread_id,
            work_item_id=work_item_id,
            request_text=request_text,
            completed_probe=completed_probe,
            failures_probe=failures_probe,
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
    completed_probe: Callable[[], bool] | None = None,
    failures_probe: Callable[[], Any] | None = None,
    on_promoted: Callable[[str], None] | None = None,
    background_slot: Callable[[], Any] | None = None,
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

    ``completed_probe`` (BF-704) is consulted only after a PROMOTED run
    finishes, and answers one question: did it finish, or did it stop? The
    awaited task returns a plain string, so a run that exhausted its step
    budget is otherwise indistinguishable from one that completed, and the work
    item closes ``done`` either way. Omitting it preserves that behaviour
    exactly, which is why it is optional.

    ``failures_probe`` (AD-1248) is the same shape for the same reason: the
    awaited task returns a plain string, so the run's tool failures cannot be
    recovered at report time either. It reads the turn's accumulated
    ``ToolFailures`` so the promoted report discloses a failed tool instead of
    silently claiming success. Omitting it renders byte-identically to before.

    ``on_promoted`` (AD-1204) is the reverse direction of ``completed_probe``:
    it publishes the work item's id back to the still-running ``work`` the
    moment the item exists. The item is created LAZILY — the run is already
    in flight when the budget elapses — so the id cannot be a parameter of
    ``work``; it does not exist when ``work`` is constructed. Everything the
    run wants to link to that item (AD-1204's ``continue`` request) therefore
    reads a cell this callback writes. Called exactly once, only on the
    promoted path, before the reporter is spawned, and never on the inline
    path (where there is no item and nothing to link).

    A raising ``on_promoted`` is logged and swallowed: the promotion itself
    has already succeeded, and failing it here would trade a working
    background task for a missing link.

    ``background_slot`` (BF-732) returns an async context manager -- normally
    ``ConcurrencyManager.slot`` -- held by the reporter for as long as the
    promoted run lives. Without it a promoted run escaped the per-agent
    accounting entirely: the foreground slot releases when the acknowledgement
    returns, which is correct because the *turn* is over, but the *run* is not,
    and nothing bounded how many accumulated. Measured 2026-08-08: four live
    promoted runs from one conversation, each competing for LLM capacity with
    the Captain's next turn, with a ceiling of "intent dispatch rate".

    Held by the reporter rather than acquired here on purpose. Acquiring before
    returning would block the acknowledgement behind a slot this turn's own
    foreground slot is still holding -- a deadlock at ``max_concurrent=1``. The
    reporter is a separate task, so its acquire waits harmlessly while the
    acknowledgement returns and the foreground slot releases. The run is
    unaccounted for that window, which is small, bounded, and honest.
    """
    if promote_after_seconds <= 0.0:
        return await work()

    task: "asyncio.Task[str]" = asyncio.create_task(
        work(), name=f"ad1165-turn-{agent_id[:8]}",
    )
    hold.add(task)
    task.add_done_callback(hold.discard)

    # BF-705: measured, not configured. The log line below used to print
    # ``promote_after_seconds`` — so every promotion in the ship's log read back
    # exactly whatever the config said, and none of them were evidence of
    # anything. ``asyncio.wait`` cannot fire its timer while the loop is blocked,
    # so the real wait overshoots the budget under the concurrent cognition this
    # BF exists to survive, and that overshoot is the number worth having.
    _wait_started = time.monotonic()
    done, _pending = await asyncio.wait({task}, timeout=promote_after_seconds)
    waited_seconds = time.monotonic() - _wait_started
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

    # AD-1204: the run is still executing and can now name the item it belongs
    # to. Published before the reporter is spawned so the id is available for
    # as much of the remaining run as possible.
    if on_promoted is not None:
        try:
            on_promoted(work_item.id)
        except Exception:
            logger.warning(
                "AD-1204: publishing work item %s back to the promoted run for "
                "agent=%s raised; the task still runs and reports, but anything "
                "it files this turn will not be linked to the item",
                work_item.id, agent_id, exc_info=True,
            )

    reporter = asyncio.create_task(
        _report_holding_slot(
            task,
            runtime=runtime,
            agent_id=agent_id,
            thread_id=thread_id,
            work_item_id=work_item.id,
            request_text=request_text,
            completed_probe=completed_probe,
            failures_probe=failures_probe,
            background_slot=background_slot,
        ),
        name=f"ad1165-report-{work_item.id[:8]}",
    )
    hold.add(reporter)
    reporter.add_done_callback(hold.discard)

    logger.info(
        "AD-1165: promoted agent=%s turn to work item %s after %.1fs measured "
        "(budget %.1fs); the run continues in the background and reports into "
        "thread %s",
        agent_id, work_item.id, waited_seconds, promote_after_seconds, thread_id,
    )
    return _ACK_TEMPLATE.format(work_item_id=work_item.id)
