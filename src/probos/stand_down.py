"""AD-1341 S4 (#1569): the stand-down, each crew agent's one bounded turn to leave exit notes before a reset.

``probos reset`` runs with the vessel stopped (S1's AD-816 pidfile), so no agent can think inside it (#1569, the
Architect's premise P1). The stand-down is the live step before it. The Captain types ``/stand-down`` at the vessel's
console, and every crew agent is sent one Captain's message: a ``direct_message`` intent through the intent bus, as a
1:1 message is, that asks for exit notes in the lessons format (``probos.knowledge.lessons``) and shows the agent its
own most recent episodes by handle. Writing is optional.

No agent can hold a reset. Each turn is bounded by ``STAND_DOWN_TURN_SECONDS``, the whole stand-down by
``STAND_DOWN_WINDOW_SECONDS``, and at most ``STAND_DOWN_CONCURRENCY`` turns run at once. A turn that runs out of time
is cancelled, and a turn that ends late, fails or is never reached writes nothing. ``probos reset`` neither waits for
a stand-down nor needs one.

A note is a Ship's Records document at ``exit_note_path(timeline, agent_type)``, written with the author's callsign,
agent type and DID, the ids of the episodes it cites (only episodes the agent was shown), ``ship`` classification and
status ``submitted``. A note already written in this timeline is never overwritten, so a second stand-down asks only
the agents without one. The reset's promotion archives each note before anything is wiped
(``probos.knowledge.archive_promotion``); the Captain reviews the notes with ``probos archive pending`` and may veto any
of them first. This module never writes the Ship's Archive and never copies an episode's text into a note.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from probos.dm_reply import DmReply
from probos.knowledge.lessons import (
    DECLINE_REPLY,
    EXIT_NOTE_KEY,
    EXIT_NOTE_STATUS,
    EXIT_NOTE_VERSION,
    LESSON_MAX_CITATIONS,
    LESSON_SECTION_MAX_CHARS,
    exit_note_body,
    exit_note_path,
    exit_notes_directory,
    is_declined,
    parse_citations,
    parse_lesson,
)
from probos.types import IntentMessage

if TYPE_CHECKING:
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
EPISODE_EXCERPT_CHARS: Final = 160


@dataclass(frozen=True)
class CrewMember:
    """One crew agent as the stand-down addresses it. ``did`` and ``callsign`` are empty when no identity resolves."""

    agent_id: str
    agent_type: str
    sovereign_id: str = ""
    did: str = ""
    callsign: str = ""


class TurnOutcome(StrEnum):
    """What one agent's stand-down turn came to. Only WRITTEN wrote anything."""

    WRITTEN = "written"
    DECLINED = "declined"
    NOT_IN_FORMAT = "not_in_format"
    NO_REPLY = "no_reply"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    NOT_REACHED = "not_reached"
    ALREADY_WRITTEN = "already_written"
    NO_IDENTITY = "no_identity"


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


def _offer(episodes: Sequence[Any]) -> tuple[dict[str, str], tuple[str, ...]]:
    """The handles an agent may cite (``e1`` -> an episode id) and the lines that show them (D4, D9).

    The agent's own most recent episodes, at most ``STAND_DOWN_EPISODES``, each by handle, date and at most
    ``EPISODE_EXCERPT_CHARS`` opening characters. An episode without an id, or seen twice, is skipped.
    """
    offered: dict[str, str] = {}
    shown: list[str] = []
    for episode in episodes:
        if len(offered) >= STAND_DOWN_EPISODES:
            break
        episode_id = getattr(episode, "id", None)
        if type(episode_id) is not str or not episode_id.strip() or episode_id in offered.values():
            continue
        handle = f"e{len(offered) + 1}"
        offered[handle] = episode_id
        stamp = getattr(episode, "timestamp", 0.0)
        day = time.strftime("%Y-%m-%d", time.gmtime(stamp)) if type(stamp) in (int, float) and stamp > 0 else "undated"
        excerpt = " ".join(str(getattr(episode, "user_input", "") or "").split())[:EPISODE_EXCERPT_CHARS]
        shown.append(f"{handle} {day}: {excerpt}")
    return offered, tuple(shown)


def exit_notes_prompt(callsign: str, shown: Sequence[str]) -> str:
    """AD-1341 S4 (D4): the Captain's message for one agent's turn: why, what, that it is optional, where it goes."""
    episodes = "\n".join(shown) if shown else "(none could be read)"
    return (
        f"Captain to {callsign}: the crew is standing down before a reset. Your successor in this billet will not share "
        "your memories. This is your one turn to leave them exit notes: what you learned, what you would do "
        "differently, and what remains open.\n\n"
        f"Writing is optional. To decline, reply exactly {DECLINE_REPLY} and nothing is recorded.\n\n"
        "If you write, reply in exactly this form, from your own experience, each section at most "
        f"{LESSON_SECTION_MAX_CHARS} characters:\n"
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
    episodes. Returns when every turn has ended: by ``window_seconds`` after it starts, plus the cancellation of the
    turns still running then. Raises ``StandDownRefused`` when the timeline is missing or names no records path, and
    ``ValueError`` for a bound that is not positive; nothing that happens in a turn raises.
    """
    if type(timeline_id) is not str or not timeline_id.strip():
        raise StandDownRefused("This vessel has no instance id, so its exit notes could not be attributed to a timeline.")
    if concurrency < 1 or turn_seconds <= 0 or window_seconds <= 0:
        raise ValueError("AD-1341 S4: a stand-down's bounds must be positive")
    try:
        directory = exit_notes_directory(timeline_id)
    except ValueError as exc:
        raise StandDownRefused(f"The instance id cannot name a records path: {exc}") from exc
    existing = {listed["path"] for listed in await records.list_entries(directory)}
    deadline = clock() + window_seconds
    gate = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()  # one Ship's Records write at a time: the repository has one git index

    async def _ask_and_write(member: CrewMember, path: str) -> TurnResult:
        try:
            episodes = await asyncio.wait_for(recall(member), timeout=max(0.001, min(turn_seconds, deadline - clock())))
        except Exception:  # log-and-degrade: the turn offers no episodes, so its note cites none
            logger.warning(
                "AD-1341 S4: %s's recent episodes could not be read; its turn offers none", member.callsign,
                exc_info=True,
            )
            episodes = ()
        offered, shown = _offer(episodes)
        remaining = deadline - clock()
        if remaining <= 0:
            return _turn_result(member, TurnOutcome.TIMED_OUT)
        prompt = exit_notes_prompt(member.callsign, shown)
        try:
            reply = await asyncio.wait_for(ask(member, prompt), timeout=min(turn_seconds, remaining))
        except TimeoutError:
            return _turn_result(member, TurnOutcome.TIMED_OUT)
        except Exception:  # log-and-degrade: one agent's failed turn never stops the others, or the reset
            logger.warning(
                "AD-1341 S4: %s's exit-notes turn failed; nothing is written", member.callsign, exc_info=True,
            )
            return _turn_result(member, TurnOutcome.FAILED)
        if clock() > deadline:  # a reply after the window writes nothing
            return _turn_result(member, TurnOutcome.TIMED_OUT)
        if reply is None:
            return _turn_result(member, TurnOutcome.NO_REPLY)
        if is_declined(reply):
            return _turn_result(member, TurnOutcome.DECLINED)
        lesson = parse_lesson(reply)
        if lesson is None:
            return _turn_result(member, TurnOutcome.NOT_IN_FORMAT)
        cited = parse_citations(reply, offered)
        envelope = {
            "version": EXIT_NOTE_VERSION,
            "timeline_id": timeline_id,
            "callsign": member.callsign,
            "agent_type": member.agent_type,
            "author_did": member.did,
            "source_episode_ids": list(cited),
        }
        async with write_lock:
            try:
                await records.write_entry(
                    author=member.callsign,
                    path=path,
                    content=exit_note_body(member.callsign, member.agent_type, timeline_id, lesson),
                    message=f"AD-1341 S4: exit notes of {member.callsign}",
                    classification="ship",  # AD-1341 S4 (D8): for the next crew, so ship-wide; C1 admits it to the archive
                    status=EXIT_NOTE_STATUS,
                    topic=f"Exit notes of {member.callsign}",
                    tags=["exit-notes", "ad-1341"],
                    extra_frontmatter={EXIT_NOTE_KEY: envelope},
                )
            except Exception:  # log-and-degrade: the turn is reported failed; the other notes are still written
                logger.warning(
                    "AD-1341 S4: %s's exit note could not be written to Ship's Records", member.callsign,
                    exc_info=True,
                )
                return _turn_result(member, TurnOutcome.FAILED)
        return _turn_result(member, TurnOutcome.WRITTEN, path)

    async def _turn(member: CrewMember) -> TurnResult:
        if not member.did.strip() or not member.callsign.strip():
            return _turn_result(member, TurnOutcome.NO_IDENTITY)
        try:
            path = exit_note_path(timeline_id, member.agent_type)
        except ValueError:
            return _turn_result(member, TurnOutcome.NO_IDENTITY)
        if path in existing:
            return _turn_result(member, TurnOutcome.ALREADY_WRITTEN, path)
        async with gate:
            if clock() >= deadline:  # the window closed before this agent's turn began
                return _turn_result(member, TurnOutcome.NOT_REACHED)
            return await _ask_and_write(member, path)

    turns = await asyncio.gather(*(_turn(member) for member in crew))
    report = StandDownReport(timeline_id=timeline_id, turns=tuple(turns))
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
            params={"text": text, "from": "captain", "session": False},
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
