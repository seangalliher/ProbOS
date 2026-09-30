"""AD-1156: plan/execute mode for a one-to-one conversation -- the turn side.

The shape is Microsoft Agent Framework's ``AgentModeProvider``: the mode is
session state (in ProbOS, the chat thread), it is injected into the agent's
instructions on every run, and moving from plan to execute belongs to the human.
MAF leaves that confirmation at instruction level. ProbOS keeps the instruction
and also narrows the tool offer in plan mode, so the agentic loop cannot change
state even when the model ignores its instructions: the executor offers only
:data:`PLAN_MODE_TOOL_IDS` and refuses every other call without running it
(``agentic_dispatch.DispatchToolExecutor``). In plan mode the DM reply is held
to its conversation too, through :class:`PlanModeReplyGate`: the reply pipeline
runs only the steps that shape the reply, read, or record the conversation, and
holds back every step that would start work, send, post, save, generate or
schedule anything, and every update the reply would drive in state the ship or
other agents act on -- trust, Hebbian weights, the divergence record
(``reply_pipeline._run_steps``). Its episode carries the plan-mode marker, so
dreaming learns nothing from it later either (A-4,
``types.episode_ran_in_plan_mode``). A reply that reaches the Captain without the
pipeline -- the replay of a held turn, a promoted run's report -- is shown as plan
mode leaves it (A-4, ``reply_pipeline.project_plan_mode_reply``). A record governs
only a turn of the agent it was set for, and only while that agent is its thread's
one participant (A-8, A-9, :func:`agent_mode_record_governs`): every read that decides
a turn's mode names the turn's agent, so an approval never passes to another agent,
and a stored record that governs no turn of this agent there -- another agent's, or on
a thread that is not one-to-one with it -- holds the turn in plan mode (A-9). A
group's own replies read no mode (A-5). A CLI ``/session`` turn runs under its
agent's default thread, so the session reads that thread's mode as the route reads
its thread's, and marks its own episode of a turn plan mode governed (A-5,
:func:`open_plan_mode_session_gate`); it sends the turn on the thread it read, with
the route's plan floor when it read plan mode or could not confirm the mode (A-6).

Nothing here suspends a run. The mode is read once when a turn starts and the
turn runs to completion under it; the Captain's approval is the next message. A
turn the route dispatched in plan mode stays in plan mode for every agent pass it
causes -- a sanity-gate retry, a replay of a held turn -- through
:data:`AGENT_MODE_FLOOR_PARAM`. No LLM client, semaphore permit or loop is held
across the human's latency.

Default-OFF: with ``config.dm_agentic.agent_modes_enabled`` false, nothing here
reads a thread or changes a turn or a reply.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from probos.threads.agent_mode import (
    AGENT_MODE_METADATA_KEY,
    AGENT_MODE_PLAN,
    AgentModeRecord,
    AgentModeRecordError,
    parse_agent_mode_record,
)

logger = logging.getLogger(__name__)

# The tools a plan-mode turn is offered, and the only ones it may call. A
# fail-safe allowlist in the same shape as ``PARALLEL_SAFE_TOOL_IDS`` and
# ``_BROWSER_LOOP_ACTIONS``: membership is the only way in, so a tool that is new
# or renamed is withheld until someone decides it only reads. Every member reads
# and none changes state; that is asserted tool by tool in
# tests/test_ad1156_plan_execute_mode.py. Withheld by omission: run_python,
# browser, delegate_task, publish_finding, claim_work_item, standing_interest
# (it can register and revoke), every MCP tool including find_mcp_tool, and any
# Captain grant whose id is not listed here.
PLAN_MODE_TOOL_IDS: frozenset[str] = frozenset({
    "web_search",
    "read_page",
    "http_fetch",
    "search_capabilities",
    "event_log_query",
    "use_skill",
    "work_item_status",
    "read_owned_steps",
    "recall_artifact",
    "oracle_query",
    "self_query",
    "message_receipts",
    "discover_work_items",
    "load_tools",
})

_PLAN_INSTRUCTIONS = (
    "\n\n## Conversation mode: plan\n\n"
    "The Captain has set this conversation to plan mode: they are asking for the "
    "plan itself, so draft it and leave carrying it out for execute mode. This "
    "takes precedence over any guidance above to act directly this turn.\n"
    "- Research what the plan needs with the tools in this turn's list. While the "
    "conversation is in plan mode that list holds read-only tools only; tools "
    "that change state -- running code, writing files, delegating, acting in a "
    "browser -- return in execute mode, and a call to one now is refused without "
    "running. Opening a task, handing work to a crewmate, saving a note or "
    "scheduling a follow-up is execution too, so leave it for execute mode.\n"
    "- Present a concise, numbered plan: each step, the tool it would use, and "
    "any decision that belongs to the Captain. Ask clarifying questions where the "
    "request is ambiguous.\n"
    "- Execution begins only when the Captain sends /mode execute. The mode is the "
    "Captain's to change, so if you are asked to go ahead, ask the Captain to "
    "send /mode execute."
)
_HELD_INSTRUCTIONS = (
    "\n\n## Conversation mode: plan (held)\n\n"
    "This conversation's mode record could not be read, so it is held in plan "
    "mode until the Captain sets the mode again. Draft the plan with the "
    "read-only tools in this turn's list and leave carrying it out for execute "
    "mode. The Captain sets the mode by sending /mode plan or /mode execute."
)
_UNAPPLIED_INSTRUCTIONS = (
    "\n\n## Conversation mode: plan (held)\n\n"
    "This conversation's stored mode was not set for you here: it was set for another "
    "agent, or this conversation is not one-to-one with you. So you are held in plan "
    "mode until the Captain sets your mode. Draft the plan with the read-only tools in "
    "this turn's list and leave carrying it out for execute mode."
)
_EXECUTE_INSTRUCTIONS = (
    "\n\n## Conversation mode: execute\n\n"
    "The Captain has set this conversation to execute mode{approval}. Work "
    "autonomously: carry the request through with your tools, make reasonable "
    "choices without asking again, and report what you did and anything still "
    "open."
)
_EXECUTE_APPROVAL = ", approving the plan drafted in plan mode"


class AgentModeThreadReader(Protocol):
    """The one store method a turn needs to resolve its mode."""

    def get_thread(self, thread_id: str) -> Any: ...


class DefaultThreadResolver(AgentModeThreadReader, Protocol):
    """What a CLI session turn's gate needs: its agent's default thread, and its mode."""

    def get_or_create_default_for_agent(self, agent_id: str, agent_callsign: str) -> Any: ...


@dataclass(frozen=True)
class TurnAgentMode:
    """The mode one turn runs under.

    ``record`` is ``None`` only when the turn is held in plan mode (:attr:`held`): the
    thread's record could not be read, or (A-9) a record that could be read does not
    govern this turn's agent there, which ``unapplied`` then names.
    """

    mode: str
    record: AgentModeRecord | None
    unapplied: AgentModeRecord | None = None

    @property
    def held(self) -> bool:
        return self.record is None


def agent_modes_enabled(runtime: Any) -> bool:
    """True only for an exact ``True`` flag, so a mock config never arms it."""
    cfg = getattr(getattr(runtime, "config", None), "dm_agentic", None)
    return getattr(cfg, "agent_modes_enabled", False) is True


def dm_agentic_loop_enabled(runtime: Any) -> bool:
    """Whether the conversational loop that modes govern is running at all."""
    cfg = getattr(getattr(runtime, "config", None), "dm_agentic", None)
    return getattr(cfg, "enabled", False) is True


def agent_mode_is_dormant(thread: Any) -> bool:
    """AD-1156 A-5: True when ``thread`` is not a one-to-one conversation.

    A mode is a one-to-one conversation's, and ``/mode`` sets one only there. A thread
    that gains or loses participants keeps its record. Its group replies read no mode,
    and ``/mode`` status says so; a one-to-one turn that meets the record there -- sent
    from an agent's panel with the thread's id, or in flight when the thread changed --
    is held in plan mode (A-9, :func:`turn_agent_mode_of_thread`, which does not consult
    this). The record governs again once the thread is one-to-one with the agent it was
    set for (A-8). A thread whose participants are unknown is not dormant.
    """
    participants = getattr(thread, "participants", None)
    return isinstance(participants, (list, tuple)) and len(participants) != 1


def agent_mode_record_governs(thread: Any, record: AgentModeRecord, *, agent_id: str | None) -> bool:
    """AD-1156 A-8, A-9: True when ``record`` governs a turn of ``agent_id`` on ``thread``.

    Only a turn of the agent the record was set for, and only while that agent is the
    thread's one participant at this read: so an approval given to one agent never passes
    to another -- one that took its place, or whose turn was admitted before the thread
    changed hands (A-9) -- and a read that cannot name its agent (``None``) is governed
    by no record. Participants that are unknown cannot show that the agent is the one
    participant, so they govern nothing either (A-9; A-5 and A-8 let them keep it).
    """
    members = getattr(thread, "participants", None)
    if record.agent_id != agent_id:
        return False
    return isinstance(members, (list, tuple)) and list(members) == [agent_id]


def read_turn_agent_mode(
    store: AgentModeThreadReader | None, thread_id: str, *, agent_id: str | None,
) -> TurnAgentMode | None:
    """The mode for a turn of ``agent_id`` on ``thread_id``; ``None`` when none applies.

    ``None`` -- no store, no thread id, or a thread that stores no record -- means the
    turn runs exactly as it would without this feature. A record governs only a turn of
    the agent it names, while that agent is the thread's one participant (A-8, A-9).
    Any other record, a thread the store no longer has (A-9), a record that does not
    parse, a metadata column that does not decode to an object, or a store that raises
    holds the turn in plan mode: the choice the Captain made for this agent cannot be
    confirmed, and plan mode only withholds. A caller with a store and no thread holds
    its turn itself (A-6). Never raises.
    """
    if store is None or not thread_id:
        return None
    try:
        thread = store.get_thread(thread_id)
    except Exception:
        logger.warning(
            "AD-1156: reading thread %s to resolve its mode failed; this turn is "
            "held in plan mode, so the agent drafts a plan and runs no tool that "
            "changes state until the thread can be read again",
            thread_id, exc_info=True,
        )
        return TurnAgentMode(mode=AGENT_MODE_PLAN, record=None)
    return turn_agent_mode_of_thread(thread_id, thread, agent_id=agent_id)


def turn_agent_mode_of_thread(
    thread_id: str, thread: Any, *, agent_id: str | None,
) -> TurnAgentMode | None:
    """A-6, A-9: the mode a turn of ``agent_id`` on ``thread``, already read, runs under.

    The one decision: :func:`read_turn_agent_mode` after its read, and ``/mode`` status on
    its own read for the agent it addressed, so status says what that agent's turn reads.
    A turn runs outside plan mode only when the thread stores no record, or its record
    governs this agent (:func:`agent_mode_record_governs`); every other outcome of the
    read holds it (A-9). ``thread_id`` names the thread in the log. Never raises.
    """
    if thread is None:
        logger.warning(
            "AD-1156: thread %s is no longer in the store, so agent %s's mode on it cannot "
            "be confirmed; this turn is held in plan mode and runs no tool that changes state",
            thread_id, agent_id,
        )
        return TurnAgentMode(mode=AGENT_MODE_PLAN, record=None)  # A-9: gone, so unconfirmed
    if thread is not None and getattr(thread, "metadata_readable", True) is False:
        logger.warning(
            "AD-1156: thread %s's metadata does not decode to an object, so its "
            "mode record cannot be read; this turn is held in plan mode until the "
            "Captain sets the mode again",
            thread_id,
        )
        return TurnAgentMode(mode=AGENT_MODE_PLAN, record=None)
    metadata = getattr(thread, "metadata", None) if thread is not None else None
    if type(metadata) is not dict or AGENT_MODE_METADATA_KEY not in metadata:
        return None
    try:
        record = parse_agent_mode_record(metadata[AGENT_MODE_METADATA_KEY])
    except AgentModeRecordError as exc:
        logger.warning(
            "AD-1156: thread %s carries a mode record that does not parse (%s); "
            "this turn is held in plan mode until the Captain sets the mode again",
            thread_id, exc,
        )
        return TurnAgentMode(mode=AGENT_MODE_PLAN, record=None)
    if not agent_mode_record_governs(thread, record, agent_id=agent_id):
        logger.warning(
            "AD-1156: thread %s's %s mode record, set for %s, does not govern a turn of %s "
            "there (it names another agent, or the thread is not one-to-one with this one); "
            "the turn is held in plan mode until the Captain sets this agent's mode",
            thread_id, record.mode, record.agent_id, agent_id,
        )
        return TurnAgentMode(mode=AGENT_MODE_PLAN, record=None, unapplied=record)
    return TurnAgentMode(mode=record.mode, record=record)


def render_agent_mode_instructions(turn: TurnAgentMode) -> str:
    """The instruction block appended to the turn's composed system prompt."""
    if turn.unapplied is not None:
        return _UNAPPLIED_INSTRUCTIONS
    if turn.held:
        return _HELD_INSTRUCTIONS
    if turn.mode == AGENT_MODE_PLAN:
        return _PLAN_INSTRUCTIONS
    approved = turn.record is not None and turn.record.previous == AGENT_MODE_PLAN
    return _EXECUTE_INSTRUCTIONS.format(
        approval=_EXECUTE_APPROVAL if approved else "",
    )


#: The ``IntentMessage.params`` key the one-to-one route sets when the thread was
#: in plan mode, or held, as it dispatched the turn. Every agent pass that turn
#: causes -- the first, a sanity-gate retry, a replay of the held turn -- runs in
#: plan mode at least, whatever the thread says by then (A-3): plan mode only
#: withholds, so the stricter of the two modes wins.
AGENT_MODE_FLOOR_PARAM = "agent_mode_floor"


def floor_turn_agent_mode(turn: TurnAgentMode | None, floor: object) -> TurnAgentMode | None:
    """``turn``, raised to plan mode when ``floor`` is plan mode.

    The thread's record is kept, so a thread whose record now says execute gets
    the plan instructions; a thread with no readable record is held, as a turn
    the route dispatched in plan mode and cannot confirm now should be.
    """
    if floor != AGENT_MODE_PLAN or (turn is not None and turn.mode == AGENT_MODE_PLAN):
        return turn
    return TurnAgentMode(mode=AGENT_MODE_PLAN, record=turn.record if turn is not None else None)


# ── the reply in plan mode (A-1, A-2) ─────────────────────────────────────

#: What plan mode holds back from a reply, by kind, each with the phrases its
#: notice uses (one, and several), in the order the notice names them. One kind
#: per reply-pipeline step that would act outside the conversation
#: (``reply_pipeline._PLAN_MODE_WITHHELD_STEPS``): opening a task, a DM to a
#: crewmate, a game challenge, a browser action, a game move, generating an
#: image, scheduling a follow-up, a notebook entry in Ship's Records, and a
#: change to the room task's checklist.
PLAN_MODE_WITHHELD_REPLY_TAGS: dict[str, tuple[str, str]] = {
    "create_task": ("a new task", "new tasks"),
    "dm": ("a message to a crewmate", "messages to crewmates"),
    "challenge": ("a game challenge", "game challenges"),
    "action": ("a browser action", "browser actions"),
    "move": ("a game move", "game moves"),
    "image": ("an image to generate", "images to generate"),
    "follow_up": ("a scheduled follow-up", "scheduled follow-ups"),
    "notebook": ("a notebook entry", "notebook entries"),
    "todos": ("a change to the task checklist", "changes to the task checklist"),
}
_WITHHELD_NOTICE = (
    "(Plan mode held back {held}; none of it was sent, saved or started. Once "
    "this conversation is in execute mode, ask again.)"
)


def plan_mode_governed_turn(
    at_dispatch: TurnAgentMode | None, at_reply: TurnAgentMode | None,
) -> bool:
    """Whether plan mode may have governed any part of a turn.

    ``at_dispatch`` is the thread's mode read before the agent ran and
    ``at_reply`` the mode read after it answered, so every read the agent made
    lies between them. Only ``/mode`` changes the record, each change raises its
    revision by one, and consecutive records alternate modes. The turn therefore
    ran wholly outside plan mode only when there was no record at either read,
    the same execute record at both, or no record and then a first execute
    record. Anything else counts: plan or held at either read, an execute record
    that changed (plan mode came between), or a record that vanished.
    """
    for turn in (at_dispatch, at_reply):
        if turn is not None and (turn.held or turn.mode == AGENT_MODE_PLAN):
            return True
    if at_reply is None:
        return at_dispatch is not None
    if at_dispatch is None:
        return at_reply.record is None or at_reply.record.revision != 1
    return at_dispatch.record != at_reply.record


class PlanModeReplyGate:
    """Whether plan mode holds a reply to its conversation.

    The one-to-one route opens it before the agent runs, with the thread's mode
    at that point. The first :meth:`withholds` call reads the thread again -- the
    reply pipeline asks at its first step that could act outside the
    conversation, after the agent's last pass, a sanity-gate retry included --
    and keeps the verdict, so every step of one reply gets the same answer. Both reads
    name the turn's agent, ``agent_id`` (A-9).
    """

    def __init__(
        self,
        store: AgentModeThreadReader | None,
        thread_id: str,
        at_dispatch: TurnAgentMode | None,
        *,
        agent_id: str | None,
    ) -> None:
        self._store = store
        self._thread_id = thread_id
        self._at_dispatch = at_dispatch
        self._agent_id = agent_id
        self._verdict: bool | None = None
        self._held: dict[str, int] = {}

    @property
    def planned_at_dispatch(self) -> bool:
        """True when the thread was in plan mode, or held, as the route dispatched
        the turn: every agent pass the turn causes runs in plan mode at least."""
        return self._at_dispatch is not None and self._at_dispatch.mode == AGENT_MODE_PLAN

    @property
    def thread_id(self) -> str:
        """The thread this gate reads; empty when it could not be resolved (A-6: the CLI
        session sends its turn on it)."""
        return self._thread_id

    def withholds(self) -> bool:
        """True when plan mode may have governed this turn. Never raises."""
        if self._verdict is None:
            at_reply = read_turn_agent_mode(self._store, self._thread_id, agent_id=self._agent_id)
            self._verdict = plan_mode_governed_turn(self._at_dispatch, at_reply)
        return self._verdict

    def record(self, kind: str, count: int = 1) -> None:
        """Note ``count`` held-back requests of ``kind``, a key of the table above."""
        self._held[kind] = self._held.get(kind, 0) + count

    def summary(self) -> str:
        """``kind=count`` pairs for the log: kinds and counts, never reply text."""
        return " ".join(f"{kind}={count}" for kind, count in sorted(self._held.items()))

    def notice(self, max_chars: int | None = None) -> str:
        """The sentence the reply gains; empty when nothing was withheld.

        With ``max_chars`` -- which must leave room for the rest of the sentence -- a
        sentence longer than that has its list of what was held cut to fit, so it keeps
        its closing clause: none of it was sent, and ask again in execute mode (A-6: an
        episode's bound).
        """
        held = [
            one if self._held[kind] == 1 else f"{self._held[kind]} {several}"
            for kind, (one, several) in PLAN_MODE_WITHHELD_REPLY_TAGS.items()
            if self._held.get(kind)
        ]
        if not held:
            return ""
        named = held[0] if len(held) == 1 else ", ".join(held[:-1]) + " and " + held[-1]
        if max_chars is not None and len(_WITHHELD_NOTICE.format(held=named)) > max_chars:
            named = named[: max(0, max_chars - len(_WITHHELD_NOTICE.format(held="...")))] + "..."
        return _WITHHELD_NOTICE.format(held=named)


def open_plan_mode_reply_gate(
    runtime: Any, store: AgentModeThreadReader | None, thread: Any, *, agent_id: str | None,
) -> PlanModeReplyGate | None:
    """Open the reply gate for a one-to-one turn of ``agent_id``, reading its mode now.

    ``None`` -- nothing is read, and the reply pipeline runs exactly as before --
    unless agent modes and the ``dm_agentic`` loop are both on and there is a
    thread store. ``thread`` is what the route resolved; with a store present,
    ``None`` means resolving it raised, so the mode cannot be confirmed and the
    reply is held in plan mode, as for a store that raises while reading. Both of the
    gate's reads name ``agent_id``, the agent the turn was admitted for, so a thread that
    changes hands after the route admitted it cannot give that turn another agent's mode
    (A-9). Call it before the agent runs. Never raises.
    """
    if store is None or not (agent_modes_enabled(runtime) and dm_agentic_loop_enabled(runtime)):
        return None
    thread_id = getattr(thread, "id", None)
    if type(thread_id) is not str or not thread_id:
        logger.warning(
            "AD-1156: this conversation's thread could not be resolved, so the "
            "reply is held in plan mode and acts on nothing outside the "
            "conversation until the thread store answers",
        )
        return PlanModeReplyGate(
            store, "", TurnAgentMode(mode=AGENT_MODE_PLAN, record=None), agent_id=agent_id,
        )
    return PlanModeReplyGate(
        store, thread_id, read_turn_agent_mode(store, thread_id, agent_id=agent_id), agent_id=agent_id,
    )


def open_plan_mode_replay_gate(
    runtime: Any, store: AgentModeThreadReader | None, thread_id: str, floor: object,
    *, agent_id: str | None,
) -> PlanModeReplyGate | None:
    """AD-1156 A-4: the reply gate for a held turn that AD-1230 replays.

    The replay sends the turn to the agent again and posts the answer itself, so
    no pipeline step sees it. Its gate is the route's: opened before the replay
    runs, it reads the thread's mode now, raised to plan mode by ``floor`` -- the
    route's :data:`AGENT_MODE_FLOOR_PARAM`, set when it dispatched the held turn in
    plan mode -- and reads it again when first asked, once the answer is back.
    ``None``, with nothing read, unless agent modes and the ``dm_agentic`` loop
    are both on and there is a thread store. Both reads name ``agent_id``, the held
    turn's agent (A-9). Never raises.
    """
    if store is None or not (agent_modes_enabled(runtime) and dm_agentic_loop_enabled(runtime)):
        return None
    return PlanModeReplyGate(
        store, thread_id,
        floor_turn_agent_mode(read_turn_agent_mode(store, thread_id, agent_id=agent_id), floor),
        agent_id=agent_id,
    )


def open_plan_mode_session_gate(
    runtime: Any, store: DefaultThreadResolver | None, agent_id: str, title: str,
) -> PlanModeReplyGate | None:
    """AD-1156 A-5: the reply gate for a CLI ``/session`` turn.

    The session sends the Captain's message with no thread, so the agent's turn runs
    under the mode of its default thread (BF-698's third source), and the session
    stores its own episode of the exchange. This is the route's gate on that thread:
    opened before the session sends, it reads the mode now, and again when first
    asked, once the answer is back; the session marks its episode when it withholds.
    ``None``, with nothing read, unless agent modes and the ``dm_agentic`` loop are
    both on and there is a thread store. A default thread that cannot be resolved
    holds, as the route's unresolved thread does. The session sends its turn with this
    gate's :attr:`~PlanModeReplyGate.thread_id` and, when the gate read plan mode or
    held, the plan floor, so the agent's turn runs on the thread this gate reads, and in
    plan mode at least when the gate read plan mode or could not confirm the mode (A-6).
    Never raises.
    """
    if not (agent_modes_enabled(runtime) and dm_agentic_loop_enabled(runtime)) or store is None:
        return None
    try:
        thread = store.get_or_create_default_for_agent(agent_id, title)
    except Exception:
        logger.warning(
            "AD-1156: agent %s's default thread could not be resolved for a session "
            "turn, so its mode cannot be confirmed and the session's episode of the "
            "turn is marked as plan mode's",
            agent_id, exc_info=True,
        )
        unconfirmed = TurnAgentMode(mode=AGENT_MODE_PLAN, record=None)
        return PlanModeReplyGate(store, "", unconfirmed, agent_id=agent_id)
    return open_plan_mode_reply_gate(runtime, store, thread, agent_id=agent_id)
