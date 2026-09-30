"""AD-1156: ``/mode [plan|execute]`` -- the Captain's explicit mode transition.

The single writer of a conversation's plan/execute mode. The router calls
:func:`handle_mode_command` before auto-naming and before logging the Captain's
message, exactly where AD-809 handles ``/personality``, and returns its result
without dispatching the message to the agent. The handler records each change
three ways: on the thread (the record the next turn reads), in the thread's
transcript (what the Captain sees), and in the event log.

Only the thread write decides the reply. The transcript and the event log are
best-effort: a failure there is logged and never reported as a failed command,
because the mode did change.

The command decides on the thread as it is when it runs (A-6): status reads the
thread again, and the writer checks inside its transaction that the thread is still
one-to-one, since the route's copy of it can predate a change to its participants.
The record names the agent the command addressed (A-8). Status decides for the agent
it addressed, through the same decision as that agent's turns (A-9): on a thread whose
record governs no turn of this agent -- set for another agent, or on a thread that is
not one-to-one with it -- it says this agent is held in plan mode there, and names the
record.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.cognitive.agent_mode import TurnAgentMode, agent_mode_is_dormant, turn_agent_mode_of_thread
from probos.threads import ChatThread, ChatThreadStore
from probos.threads.agent_mode import (
    AGENT_MODE_EXECUTE,
    AGENT_MODE_PLAN,
    AGENT_MODES,
    AgentModeNotOneToOneError,
    AgentModeRecord,
)

logger = logging.getLogger(__name__)

MODE_COMMAND = "/mode"
MODE_CHANGED_EVENT = "agent_mode_changed"
_ECHO_MAX_CHARS = 32

_USAGE = "Send /mode plan, /mode execute, or /mode to show the current mode."
_FAILED = "Mode command failed; please try again."
_NOT_ONE_TO_ONE = (
    "Plan and execute modes apply to a one-to-one conversation with an agent; this "
    "conversation's mode is unchanged."
)
_LOOP_OFF_NOTE = (
    " Modes take effect when the direct-message agentic loop is enabled "
    "(dm_agentic.enabled)."
)


def is_mode_command(message: str) -> bool:
    """True when the message's first word is exactly ``/mode`` (case-sensitive).

    ``/modes`` and ``/model`` are not the command, and neither is ``/mode`` in
    the middle of a sentence. Like ``/personality``, callers pass a body that
    carries no @-mention.
    """
    parts = message.strip().split(maxsplit=1)
    return bool(parts) and parts[0] == MODE_COMMAND


async def handle_mode_command(
    message: str,
    *,
    thread: ChatThread,
    agent_id: str,
    store: ChatThreadStore,
    loop_enabled: bool,
    event_log: Any = None,
) -> dict[str, Any]:
    """Parse and apply one ``/mode`` command on ``thread``.

    Returns the router's response: a system note (``system: True``, which the
    HXI renders as a note rather than an agent reply) plus ``agent_mode``, the
    thread's record after the command, or ``None`` when there is none.
    ``applied`` names the mode this command switched to, and is ``None`` when
    nothing changed.
    """
    parts = message.strip().split()
    arg = parts[1].lower() if len(parts) > 1 else ""
    applied: str | None = None
    record: AgentModeRecord | None = None
    try:
        if len(parts) > 2 or (arg and arg != "status" and arg not in AGENT_MODES):
            echoed = " ".join(parts[1:]).replace("`", "")[:_ECHO_MAX_CHARS]
            reply = f"Unknown mode `{echoed}`. {_USAGE}"
        elif arg in ("", "status"):
            # A-6: the thread as it is now, not the route's copy, which can predate a
            # change to its participants; whether a mode applies, and which, come from
            # this one read.
            current = store.get_thread(thread.id)
            if current is None:
                # A-9: the thread is gone, so there is no mode to report for it
                reply = _FAILED
            elif agent_mode_is_dormant(current):
                # A-9: what this agent's own turns here read, through their decision
                dormant = turn_agent_mode_of_thread(thread.id, current, agent_id=agent_id)
                reply = _dormant_reply(dormant, loop_enabled)
            else:
                turn = turn_agent_mode_of_thread(thread.id, current, agent_id=agent_id)
                record = None if turn is None else turn.record
                reply = _status_reply(turn is not None and turn.held, record, loop_enabled)
                if turn is not None and turn.unapplied is not None:
                    # A-9: a stored record that governs no turn of this agent here holds it
                    alone = getattr(current, "participants", None) == [agent_id]
                    reply = _unapplied_reply(turn.unapplied, alone, loop_enabled)
        elif list(thread.participants) != [agent_id]:
            reply = _NOT_ONE_TO_ONE
        else:
            transition = store.set_agent_mode(thread.id, arg, changed_by="captain", expected_participant=agent_id)
            if transition is None:
                reply = _FAILED
            else:
                record = transition.record
                if transition.changed:
                    applied = arg
                    reply = _changed_reply(record, loop_enabled)
                else:
                    reply = (
                        f"This conversation is already in {record.mode} mode "
                        f"(revision {record.revision})."
                    )
    except AgentModeNotOneToOneError:
        # A-6: the thread stopped being one-to-one after the route read it, or its one
        # participant is no longer the agent addressed (A-7); the writer checked inside
        # its transaction and wrote nothing.
        reply, applied, record = _NOT_ONE_TO_ONE, None, None
    except Exception:
        logger.warning(
            "AD-1156: /mode failed for thread=%s agent=%s; the conversation's "
            "mode is unchanged and the Captain is asked to retry",
            thread.id, agent_id, exc_info=True,
        )
        reply, applied, record = _FAILED, None, None

    _append_transcript(store, thread.id, message, reply, applied, record)
    if applied is not None and record is not None:
        await _record_transition(event_log, thread_id=thread.id, agent_id=agent_id, record=record)
    return {
        "response": reply,
        "thread_id": thread.id,
        "system": True,
        "applied": applied,
        "agent_mode": None if record is None else record.to_dict(),
        "dag": None,
        "results": None,
    }


def _status_reply(held: bool, record: AgentModeRecord | None, loop_enabled: bool) -> str:
    note = "" if loop_enabled else _LOOP_OFF_NOTE
    if held:
        return (
            "This conversation's mode record could not be read, so the agent is "
            "held in plan mode. Send /mode plan or /mode execute to set it." + note
        )
    if record is None:
        return (
            "No mode is set for this conversation, so the agent works as usual. "
            "Send /mode plan to have it draft a plan before doing anything, or "
            "/mode execute to have it work autonomously." + note
        )
    reply = f"This conversation is in {record.mode} mode (revision {record.revision})."
    if record.mode == AGENT_MODE_PLAN:
        reply += " The agent drafts a plan without carrying it out; send /mode execute to approve it."
    return reply + note


def _dormant_reply(turn: TurnAgentMode | None, loop_enabled: bool) -> str:
    """A-5: the status of a thread that is not one-to-one, whose group replies read no
    mode. A stored record, or one that cannot be read, holds this agent's own turns here
    in plan mode (A-9: ``turn`` is what they read), and governs again only if the thread
    becomes one-to-one with the agent it was set for (A-8)."""
    if turn is None:
        return (
            "Plan and execute modes apply only to a one-to-one conversation with an "
            "agent. This conversation is not one-to-one, so no mode applies to it and "
            "its replies are not held."
        ) + ("" if loop_enabled else _LOOP_OFF_NOTE)
    reply = (
        "Plan and execute modes apply only to a one-to-one conversation with an agent. "
        "This conversation is not one-to-one, so its group replies are not held, but this "
        "agent's own turns here are held in plan mode: it drafts a plan without carrying "
        "it out."
    )
    if turn.unapplied is None:
        reply += " Its stored mode record cannot be read."
    else:
        reply += (
            f" Its stored {turn.unapplied.mode} mode (revision {turn.unapplied.revision}) "
            "applies again only if it becomes one-to-one with the agent it was set for."
        )
    return reply + ("" if loop_enabled else _LOOP_OFF_NOTE)


def _unapplied_reply(record: AgentModeRecord, alone: bool, loop_enabled: bool) -> str:
    """A-9: the status on a thread with one participant whose stored record governs no
    turn of this agent: set for another agent, or this agent is not that participant.
    ``alone`` -- this agent is the one participant -- adds how to set its own mode."""
    reply = (
        f"The stored {record.mode} mode (revision {record.revision}) applies only to the "
        "agent it was set for, while that agent is this conversation's one participant, so "
        "this agent is held in plan mode here: it drafts a plan without carrying it out."
    )
    if alone:
        reply += " Send /mode plan or /mode execute to set this agent's own mode."
    return reply + ("" if loop_enabled else _LOOP_OFF_NOTE)


def _changed_reply(record: AgentModeRecord, loop_enabled: bool) -> str:
    reply = f"Mode set to {record.mode} for this conversation (revision {record.revision})."
    if record.mode == AGENT_MODE_PLAN:
        reply += (
            " The agent will research and present a plan without carrying it "
            "out. Send /mode execute to approve the plan and let it work "
            "autonomously."
        )
    elif record.mode == AGENT_MODE_EXECUTE and record.previous == AGENT_MODE_PLAN:
        reply += " This approves the plan: the agent carries it out autonomously from its next turn."
    else:
        reply += " The agent will work autonomously."
    return reply + ("" if loop_enabled else _LOOP_OFF_NOTE)


def _append_transcript(
    store: ChatThreadStore,
    thread_id: str,
    message: str,
    reply: str,
    applied: str | None,
    record: AgentModeRecord | None,
) -> None:
    """Log both sides of the command on the thread. Best-effort."""
    try:
        store.append_message(
            thread_id,
            author_id="captain",
            role="captain",
            body=message,
            metadata={"slash_command": "mode"},
        )
        store.append_message(
            thread_id,
            author_id="system",
            role="system",
            body=reply,
            metadata={
                "slash_command": "mode",
                "applied": applied,
                "agent_mode": None if record is None else record.to_dict(),
            },
        )
    except Exception:
        logger.warning(
            "AD-1156: logging /mode on thread=%s failed; the mode itself is "
            "stored on the thread, but this exchange is missing from its transcript",
            thread_id, exc_info=True,
        )


async def _record_transition(
    event_log: Any, *, thread_id: str, agent_id: str, record: AgentModeRecord,
) -> None:
    """Write the transition to the event log. Best-effort (BF-873 may raise)."""
    if event_log is None:
        return
    try:
        await event_log.log(
            category="cognitive",
            event=MODE_CHANGED_EVENT,
            agent_id=agent_id,
            detail=f"{record.previous or 'none'} -> {record.mode}",
            data={"thread_id": thread_id, **record.to_dict()},
        )
    except Exception:
        logger.warning(
            "AD-1156: the event log did not record thread=%s moving to %s "
            "(revision %d); the change is stored on the thread and in its "
            "transcript",
            thread_id, record.mode, record.revision, exc_info=True,
        )
