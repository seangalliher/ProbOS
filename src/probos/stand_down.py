"""AD-1341 S4 (#1569): the stand-down, each crew agent's one bounded turn to leave exit notes before a reset.

``probos reset`` runs with the vessel stopped (S1's AD-816 pidfile), so no agent can think inside it (#1569, the
Architect's premise P1). The stand-down is the live step before it. The Captain types ``/stand-down`` at the vessel's
console, and every crew agent is sent one Captain's message: a ``direct_message`` intent through the intent bus, as a
1:1 message is, that asks for exit notes in the lessons format (``probos.knowledge.lessons``) and shows the agent its
own most recent episodes by handle. Writing is optional. The message is a bounded turn (``BOUNDED_TURN_PARAM``, A2): the
agent answers it on its single-pass path, without its tool-calling loop, so nothing the turn starts outlives it.

No agent can hold a reset. Each turn is bounded by ``STAND_DOWN_TURN_SECONDS``, the whole stand-down by
``STAND_DOWN_WINDOW_SECONDS``, and at most ``STAND_DOWN_CONCURRENCY`` turns run at once. A turn that runs out of time
is cancelled; a turn whose reply comes late, fails or is never reached writes nothing, and no write begins once the
window has closed. Nothing the stand-down published is ever removed (A4): a write that fails or is cut off after
publishing is reported with its path. ``probos reset`` neither waits for a stand-down nor needs one.

A note is a Ship's Records document at ``exit_note_path(timeline, agent_type)``, written with the author's callsign,
agent type and DID, the ids of the episodes it cites (only episodes the agent was shown), ``ship`` classification and
status ``submitted``. A note already written in this timeline is never overwritten, so a second stand-down asks only
the agents without one. The reset's promotion archives each note before anything is wiped
(``probos.knowledge.archive_promotion``); the Captain reviews the notes with ``probos archive pending`` and may veto any
of them first. This module never writes the Ship's Archive and never copies an episode's text into a note.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from probos.dm_reply import DmReply
from probos.knowledge.lessons import (
    DECLINE_REPLY,
    EXIT_NOTE_EPISODE_ID_MAX_CHARS,
    EXIT_NOTE_KEY,
    EXIT_NOTE_STATUS,
    EXIT_NOTE_TIMELINE_MAX_CHARS,
    EXIT_NOTE_VERSION,
    LESSON_MAX_CHARS,
    LESSON_MAX_CITATIONS,
    exit_note_body,
    exit_note_lesson,
    exit_note_path,
    exit_note_provenance_ok,
    exit_notes_directory,
    is_declined,
    is_exit_note_text,
    parse_citations,
    parse_lesson,
)
from probos.types import IntentMessage

if TYPE_CHECKING:
    from pathlib import Path

    from probos.knowledge.records_store import RecordsStore

logger = logging.getLogger(__name__)

#: AD-1341 S4 (D5): the longest one agent's turn may take.
STAND_DOWN_TURN_SECONDS: Final = 180.0
#: AD-1341 S4 (D5): the longest the whole stand-down may take.
STAND_DOWN_WINDOW_SECONDS: Final = 900.0
#: AD-1341 S4 (D5): the most turns that run at once, inside AD-636's six concurrent model calls.
STAND_DOWN_CONCURRENCY: Final = 2
#: AD-1341 S4 (D4): the most recent episodes an agent is shown, each by handle, date and opening characters.
STAND_DOWN_EPISODES: Final = LESSON_MAX_CITATIONS
#: A2 (M2-8): an excerpt's bound in bytes once JSON-escaped (the transport escapes every character outside ASCII), so
#: in characters too; the Captain's message stays inside the 4 KiB standard for inline ``IntentMessage.params`` (S7c).
EPISODE_EXCERPT_CHARS: Final = 160
#: A2 (M2-1): the ``direct_message`` param that makes the turn a bounded one. ``CognitiveAgent`` answers it on the
#: single-pass path, so no tool-calling loop runs and nothing is promoted into a background work item past the turn.
BOUNDED_TURN_PARAM: Final = "bounded_turn"


@dataclass(frozen=True)
class CrewMember:
    """One crew agent as the stand-down addresses it. ``did`` and ``callsign`` are empty when no identity resolves."""

    agent_id: str
    agent_type: str
    sovereign_id: str = ""
    did: str = ""
    callsign: str = ""


class TurnOutcome(StrEnum):
    """What one agent's stand-down turn came to.

    WRITTEN wrote its note. The stand-down never removes a document (A4). A FAILED or TIMED_OUT turn that carries a
    path is a write that did not complete and may have left a document there: it published before it failed or was
    cut off, or whether it did could not be checked (A5, round 3 M2-2). The report names the path, the console counts
    such turns apart from WRITTEN, and the Captain's review lists any note the next promotion would archive there. A
    FAILED turn without a path wrote nothing, a billet that could not be checked included (A5). Every other outcome
    left nothing at its path, or found a note there already (ALREADY_WRITTEN, DUPLICATE).
    """

    WRITTEN = "written"
    DECLINED = "declined"
    NOT_IN_FORMAT = "not_in_format"
    NO_REPLY = "no_reply"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    NOT_REACHED = "not_reached"
    ALREADY_WRITTEN = "already_written"
    NO_IDENTITY = "no_identity"
    DUPLICATE = "duplicate"  # A2 (M2-3): this billet's path is another crew agent's turn in this stand-down


@dataclass(frozen=True)
class TurnResult:
    """One agent's turn: who, what it came to, and the note's records path when there is one."""

    agent_type: str
    callsign: str
    outcome: TurnOutcome
    path: str = ""


@dataclass(frozen=True)
class StandDownReport:
    """One stand-down: the timeline its notes belong to, and each crew agent's turn in crew order."""

    timeline_id: str
    turns: tuple[TurnResult, ...]

    def count(self, outcome: TurnOutcome) -> int:
        """How many turns came to ``outcome``."""
        return sum(1 for turn in self.turns if turn.outcome is outcome)


class StandDownRefused(Exception):
    """No stand-down can run on this vessel now. Nobody was asked and nothing was written."""


Ask = Callable[[CrewMember, str], Awaitable[str | None]]
Recall = Callable[[CrewMember], Awaitable[Sequence[Any]]]


def _turn_result(member: CrewMember, outcome: TurnOutcome, path: str = "") -> TurnResult:
    return TurnResult(member.agent_type, member.callsign, outcome, path)


def _present(path: Path) -> bool | None:
    """A5 (7.3a's table, O7): True when something is at ``path``, False when nothing is, None when that cannot be told.

    ``Path.exists`` answers False for errors ``pathlib`` reads as "not there" (EBADF and ELOOP, and on Windows "the
    device is not ready" among others), so a note there could be taken for none and written over, or left out of the
    report. Only "not found", or a parent that is no directory, is absent. ``lstat``: whatever is at the billet's path
    is there, and a link is never followed.
    """
    try:
        path.lstat()
    except (FileNotFoundError, NotADirectoryError):  # A5: nothing is there
        return False
    except OSError:
        return None
    return True


def _offer(episodes: Sequence[Any]) -> tuple[dict[str, str], tuple[str, ...]]:
    """The handles an agent may cite (``e1`` -> an episode id) and the lines that show them (D4, D9).

    The agent's own most recent episodes, at most ``STAND_DOWN_EPISODES``, each by handle, date and opening words of
    at most ``EPISODE_EXCERPT_CHARS`` bytes once JSON-escaped. An episode seen twice, or whose id the promotion's rule
    refuses (``is_exit_note_text``: blank, over 128 characters, not one line, or holding ``---``; A4), is skipped.
    """
    offered: dict[str, str] = {}
    shown: list[str] = []
    for episode in episodes:
        if len(offered) >= STAND_DOWN_EPISODES:
            break
        episode_id = getattr(episode, "id", None)
        if not is_exit_note_text(episode_id, EXIT_NOTE_EPISODE_ID_MAX_CHARS) or episode_id in offered.values():
            continue  # A4 (R2-F4): an id the promotion's rule refuses is never offered
        handle = f"e{len(offered) + 1}"
        offered[handle] = episode_id
        day, excerpt = _day(getattr(episode, "timestamp", 0.0)), _excerpt(getattr(episode, "user_input", ""))
        shown.append(f"{handle} {day}: {excerpt}")
    return offered, tuple(shown)


def _day(stamp: object) -> str:
    """An episode's date, or ``undated`` for a timestamp that names none (missing, not positive, NaN, out of range)."""
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not stamp > 0:
        return "undated"
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(stamp))
    except (OverflowError, OSError, ValueError):  # A2 (M2-6): inf, or out of range; the turn still runs
        return "undated"


def _excerpt(text: object) -> str:
    """An episode's opening words: at most ``EPISODE_EXCERPT_CHARS`` bytes once JSON-escaped (A2, M2-8)."""
    kept: list[str] = []
    cost = 0
    for char in " ".join(str(text or "").split()):
        if "\ud800" <= char <= "\udfff":
            continue  # a lone surrogate is no UTF-8: dropped, never sent
        cost += len(json.dumps(char)) - 2
        if cost > EPISODE_EXCERPT_CHARS:
            break
        kept.append(char)
    return "".join(kept)


def exit_notes_prompt(callsign: str, shown: Sequence[str]) -> str:
    """AD-1341 S4 (D4): the Captain's message for one agent's turn: why, what, that it is optional, where it goes."""
    episodes = "\n".join(shown) if shown else "(none could be read)"
    return (
        f"Captain to {callsign}: the crew is standing down before a reset. Your successor in this billet will not share "
        "your memories. This is your one turn to leave them exit notes: what you learned, what you would do "
        "differently, and what remains open.\n\n"
        f"Writing is optional. To decline, reply exactly {DECLINE_REPLY} and nothing is recorded.\n\n"
        "If you write, reply in exactly this form, from your own experience, the four sections together at most "
        f"{LESSON_MAX_CHARS} characters:\n"
        "## Observation\n(what happened)\n"
        "## Discussion\n(why it happened and why it mattered)\n"
        "## Lesson\n(the general learning)\n"
        "## Recommendation\n(what your successor should do differently, and what remains open)\n"
        "Cites: (optional) the handles of the episodes below that your observation rests on, for example e1, e3\n\n"
        "Your notes are kept in Ship's Records under your callsign and DID. The Captain may review them and veto them; "
        "otherwise they are archived in the Ship's Archive at the reset, where every later crew can read them, "
        "labelled as inherited from this crew. Write nothing you would not share with the whole ship. Summarise in "
        "your own words; do not quote your memories. Reply with the notes alone, without using tools.\n\n"
        f"Your most recent episodes (handle, date, opening words):\n{episodes}"
    )


async def run_stand_down(
    crew: Sequence[CrewMember],
    *,
    ask: Ask,
    recall: Recall,
    records: RecordsStore,
    timeline_id: str,
    turn_seconds: float = STAND_DOWN_TURN_SECONDS,
    window_seconds: float = STAND_DOWN_WINDOW_SECONDS,
    concurrency: int = STAND_DOWN_CONCURRENCY,
    clock: Callable[[], float] = time.monotonic,
) -> StandDownReport:
    """Give each crew member one bounded turn to leave exit notes, and write each note it leaves (D3 to D11).

    ``ask`` delivers the prompt and returns the reply (None for no reply); ``recall`` returns the member's most recent
    episodes. Returns by ``window_seconds`` after it starts, plus the cancellation of what is still running then: the
    window includes the first read of Ship's Records and every write (A2, M2-2). Each member's turn has one deadline,
    ``turn_seconds`` after it begins and never past the window, that its recall and its ask both spend and that its
    reply must meet (A2, M2-5). One turn per billet: a second crew agent of an agent type, or a member listed twice, is
    ``DUPLICATE`` and is not asked (A2, M2-3). No write begins once the window has closed, and nothing the stand-down
    published is removed: a write that fails or is cut off after publishing is reported with its path (A4).

    Raises ``StandDownRefused`` when the timeline is missing, cannot stand in a note or name a records path, or when
    Ship's Records cannot be read in time, a first read that returns after the window has closed included (A5; nobody
    is asked), and ``ValueError`` for a bound that is not positive.
    Nothing that happens in a member's turn raises, and no turn outlives the call.
    """
    if type(timeline_id) is not str or not timeline_id.strip():
        raise StandDownRefused("This vessel has no instance id, so its exit notes could not be attributed to a timeline.")
    if concurrency < 1 or turn_seconds <= 0 or window_seconds <= 0:
        raise ValueError("AD-1341 S4: a stand-down's bounds must be positive")
    if not is_exit_note_text(timeline_id, EXIT_NOTE_TIMELINE_MAX_CHARS):
        raise StandDownRefused(
            f"The instance id cannot stand in an exit note (one line, at most {EXIT_NOTE_TIMELINE_MAX_CHARS} characters)."
        )
    try:
        directory = exit_notes_directory(timeline_id)
    except ValueError as exc:
        raise StandDownRefused(f"The instance id cannot name a records path: {exc}") from exc
    deadline = clock() + window_seconds  # A2 (M2-2): the window starts before Ship's Records is first read
    try:
        listed = await asyncio.wait_for(records.list_entries(directory, strict=True), timeout=window_seconds)
    except Exception as exc:  # the window closed, or a note file could not be read: which notes exist is unknown
        logger.warning(
            "AD-1341 S4: Ship's Records could not be read for the stand-down; nobody is asked", exc_info=True,
        )
        raise StandDownRefused(
            "Ship's Records could not be read in time, so nobody was asked: a note already written could be replaced."
        ) from exc
    if clock() >= deadline:  # A5 (round 3 M2-3): the first read returned after the window closed
        # wait_for cannot cut off a read that never yields (synchronous Ship's Records I/O, register R22), so the
        # window is checked again before any turn task exists, and none begins after it.
        logger.warning("AD-1341 S4: reading Ship's Records took the whole stand-down window; nobody is asked")
        raise StandDownRefused("Reading Ship's Records took the whole stand-down window, so nobody was asked.")
    existing = {entry["path"] for entry in listed}
    claimed_paths: set[str] = set()  # A2 (M2-3): the billets a turn has taken in this stand-down
    seen_agents: set[str] = set()
    gate = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()  # one Ship's Records write at a time: the repository has one git index

    def _left_at(path: str) -> str:
        """A4: ``path`` when a document is there now, so the report names it. Unknown counts as there (A5: through
        ``_present``, which reads what ``Path.exists`` calls "not there" as unknown)."""
        return "" if _present(records.repo_path / path) is False else path

    async def _write(member: CrewMember, path: str, body: str, envelope: dict[str, Any]) -> TurnResult:
        """Write one note: begun inside the window, never over a document its check found or could not rule out, and
        reported as it is left (A2, A4, A5; a writer outside ProbOS saving at the path in the same instant: R28).

        The check for a note written since the stand-down began has no await, and its time is charged to the window
        before a write may begin (A4, round 2 M2-2). The stand-down never removes a document (A4): a write that fails,
        or that the window cuts off, may already have published its note (``write_entry`` writes the file before it
        awaits git), so the report names the path and the Captain's review lists it. A write that returns after the
        window (synchronous Ship's Records I/O, register R22) left its note: WRITTEN.
        """
        async with write_lock:
            present = _present(records.repo_path / path)  # A5: what Path.exists reads as "not there" is unknown here
            if present:  # A2 (M2-3), A4: a note written since the stand-down began; no await
                return _turn_result(member, TurnOutcome.ALREADY_WRITTEN, path)
            if present is None:  # A5: whether a note is there cannot be told now, so nothing is written over it
                logger.warning(
                    "AD-1341 S4: whether %s's exit note is already written cannot be checked; nothing is written",
                    member.callsign,
                )
                return _turn_result(member, TurnOutcome.FAILED)
            remaining = deadline - clock()  # A4: after the check, so its time is charged to the window
            if remaining <= 0:  # A2 (M2-2): the window closed while this turn waited for the write lock
                return _turn_result(member, TurnOutcome.TIMED_OUT)
            written = records.write_entry(
                author=member.callsign,
                path=path,
                content=body,
                message=f"AD-1341 S4: exit notes of {member.callsign}",
                classification="ship",  # AD-1341 S4 (D8): for the next crew, so ship-wide; C1 admits it to the archive
                status=EXIT_NOTE_STATUS,
                topic=f"Exit notes of {member.callsign}",
                tags=["exit-notes", "ad-1341"],
                extra_frontmatter={EXIT_NOTE_KEY: envelope},
            )
            try:
                await asyncio.wait_for(written, timeout=remaining)  # A2 (M2-2): the window cuts off an awaiting write
            except Exception as exc:  # log-and-degrade: TimeoutError included; the other notes are still written
                outcome = TurnOutcome.TIMED_OUT if isinstance(exc, TimeoutError) else TurnOutcome.FAILED
                logger.warning(
                    "AD-1341 S4: %s's exit note write did not complete; what it published stays and is reported",
                    member.callsign, exc_info=True,
                )
                return _turn_result(member, outcome, _left_at(path))  # A4: never removed; the report names it
        return _turn_result(member, TurnOutcome.WRITTEN, path)

    async def _ask_and_write(member: CrewMember, path: str) -> TurnResult:
        turn_deadline = min(clock() + turn_seconds, deadline)  # A2 (M2-5): one deadline for the whole turn
        try:
            episodes = await asyncio.wait_for(recall(member), timeout=max(0.001, turn_deadline - clock()))
        except Exception:  # log-and-degrade: the turn offers no episodes, so its note cites none
            logger.warning(
                "AD-1341 S4: %s's recent episodes could not be read; its turn offers none", member.callsign,
                exc_info=True,
            )
            episodes = ()
        offered, shown = _offer(episodes)
        remaining = turn_deadline - clock()  # A2 (M2-5): what the recall spent is spent
        if remaining <= 0:
            return _turn_result(member, TurnOutcome.TIMED_OUT)
        prompt = exit_notes_prompt(member.callsign, shown)
        try:
            reply = await asyncio.wait_for(ask(member, prompt), timeout=remaining)
        except TimeoutError:
            return _turn_result(member, TurnOutcome.TIMED_OUT)
        except Exception:  # log-and-degrade: one agent's failed turn never stops the others, or the reset
            logger.warning(
                "AD-1341 S4: %s's exit-notes turn failed; nothing is written", member.callsign, exc_info=True,
            )
            return _turn_result(member, TurnOutcome.FAILED)
        if clock() > turn_deadline:  # a reply after the turn's deadline (never past the window) writes nothing
            return _turn_result(member, TurnOutcome.TIMED_OUT)
        if reply is None:
            return _turn_result(member, TurnOutcome.NO_REPLY)
        if is_declined(reply):
            return _turn_result(member, TurnOutcome.DECLINED)
        lesson = parse_lesson(reply)
        if lesson is None:
            return _turn_result(member, TurnOutcome.NOT_IN_FORMAT)
        body = exit_note_body(member.callsign, member.agent_type, timeline_id, lesson)
        if exit_note_lesson(member.callsign, member.agent_type, timeline_id, body) != lesson:
            logger.error(
                "AD-1341 S4: %s's exit note would not pass the promotion's rule; nothing is written", member.callsign,
            )
            return _turn_result(member, TurnOutcome.FAILED)  # A2 (M2-7): the promotion's own rule, before the write
        cited = parse_citations(reply, offered)
        envelope = {
            "version": EXIT_NOTE_VERSION,
            "timeline_id": timeline_id,
            "callsign": member.callsign,
            "agent_type": member.agent_type,
            "author_did": member.did,
            "source_episode_ids": list(cited),
        }
        return await _write(member, path, body, envelope)

    async def _claimed_turn(member: CrewMember) -> TurnResult:
        if not exit_note_provenance_ok(timeline_id, member.callsign, member.agent_type, member.did):
            return _turn_result(member, TurnOutcome.NO_IDENTITY)  # A2 (M2-7): no identity the note could carry
        try:
            path = exit_note_path(timeline_id, member.agent_type)
        except ValueError:
            return _turn_result(member, TurnOutcome.NO_IDENTITY)
        if path in existing:
            return _turn_result(member, TurnOutcome.ALREADY_WRITTEN, path)
        if path in claimed_paths or member.agent_id in seen_agents:  # A2 (M2-3): one turn per billet, and per agent
            return _turn_result(member, TurnOutcome.DUPLICATE, path)
        claimed_paths.add(path)  # no await since the check above: the claim cannot race
        seen_agents.add(member.agent_id)
        async with gate:
            if clock() >= deadline:  # the window closed before this agent's turn began
                return _turn_result(member, TurnOutcome.NOT_REACHED)
            return await _ask_and_write(member, path)

    async def _turn(member: CrewMember) -> TurnResult:
        try:
            return await _claimed_turn(member)
        except Exception:  # A2 (M2-6): one member's fault never ends the others' turns or the report
            logger.warning(
                "AD-1341 S4: %s's stand-down turn failed; nothing is written", member.callsign or member.agent_id,
                exc_info=True,
            )
            return _turn_result(member, TurnOutcome.FAILED)

    turns = [asyncio.create_task(_turn(member)) for member in crew]  # A4: held here and drained below
    try:
        await asyncio.gather(*turns)
    except BaseException:  # A2 (M2-6): the caller's cancellation, or a turn's own; no turn outlives the stand-down
        for turn in turns:
            turn.cancel()
        await asyncio.gather(*turns, return_exceptions=True)
        raise
    report = StandDownReport(timeline_id=timeline_id, turns=tuple(turn.result() for turn in turns))
    logger.info(
        "AD-1341 S4: stand-down for timeline %s: %d of %d crew agents left exit notes",
        timeline_id, report.count(TurnOutcome.WRITTEN), len(report.turns),
    )
    return report


def crew_for_stand_down(runtime: Any) -> tuple[CrewMember, ...]:
    """Every crew agent in the registry (AD-429e's crew types) with the identity ``IdentityService`` resolves (D9)."""
    from probos.crew_utils import is_crew_agent

    identities = runtime.identity_service
    members: list[CrewMember] = []
    for agent in runtime.registry.all():
        if not is_crew_agent(agent, runtime.ontology):
            continue
        ref = identities.resolve(agent.id) if identities is not None else None
        members.append(CrewMember(
            agent_id=agent.id,
            agent_type=agent.agent_type,
            sovereign_id=ref.sovereign_id if ref is not None else "",
            did=ref.did if ref is not None else "",
            callsign=ref.callsign if ref is not None else "",
        ))
    return tuple(sorted(members, key=lambda member: (member.agent_type, member.agent_id)))


async def stand_down_vessel(runtime: Any) -> StandDownReport:
    """The Captain's ``/stand-down`` on this vessel: refuse, or give each crew agent its one turn (D2, D3)."""
    if not runtime.config.archive.enabled:
        raise StandDownRefused("The Ship's Archive is disabled (archive.enabled), so no exit note would be archived.")
    records = runtime.records_store
    if records is None:
        raise StandDownRefused("Ship's Records is not running, so no exit note could be kept.")
    ontology = runtime.ontology
    timeline_id = ontology.get_vessel_identity().instance_id if ontology is not None else ""
    if not timeline_id or timeline_id == "unknown":  # the ontology's placeholder when no identity is loaded
        raise StandDownRefused("This vessel has no instance id, so its exit notes could not be attributed to a timeline.")
    bus, memory = runtime.intent_bus, runtime.episodic_memory

    async def _ask(member: CrewMember, text: str) -> str | None:
        intent = IntentMessage(
            intent="direct_message",
            params={"text": text, "from": "captain", "session": False, BOUNDED_TURN_PARAM: True},  # A2 (M2-1)
            target_agent_id=member.agent_id,
            ttl_seconds=STAND_DOWN_TURN_SECONDS,
        )
        result = await bus.send(intent)
        if result is None or not result.success:  # refused, stopped or failed: no turn
            return None
        return DmReply.from_intent_result(result).body

    async def _recall(member: CrewMember) -> Sequence[Any]:
        if memory is None or not member.sovereign_id:
            return ()
        return await memory.recent_for_agent(member.sovereign_id, k=STAND_DOWN_EPISODES)

    return await run_stand_down(
        crew_for_stand_down(runtime), ask=_ask, recall=_recall, records=records, timeline_id=timeline_id,
    )
