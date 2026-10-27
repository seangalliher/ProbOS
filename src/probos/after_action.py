"""AD-1341 S5 (#1569): the after-action report, a crew agent's lesson after an event the Captain flags, reviewed by
the chain of command before it may reach the Ship's Archive.

The Captain types ``/after-action CALLSIGN: SUBJECT`` at the vessel's console (console only). The agent with that
callsign gets one bounded turn: S4's ``BOUNDED_TURN_PARAM`` message from the Captain through the intent bus, answered
inline on its single-pass path. The turn names the subject, shows the agent its own recent episodes by handle and asks
for the naval lessons-learned format (``probos.knowledge.lessons``). Writing is optional.

A lesson in the format then goes to the chain of command (#1569 comment 1, item 3): the author's superior, then the
Counselor, or the first officer when the Counselor wrote it or is the superior. Each reviewer gets one bounded turn and
answers ENDORSE or RETURN. A returned or unanswered stage ends the review.

The report is written once, after the review, to Ship's Records at ``after_action_path(timeline, agent_type, flagged)``
at ``ship`` classification, with the review in its envelope. Only a report its chain endorsed is a promotion source
(``after_action_review_ok``); a returned one stays in Ship's Records as a record. The Captain still reviews and vetoes
with ``probos archive pending`` and ``probos archive veto``. This module never writes the Ship's Archive, never copies
an episode's text into a report, and never writes over a report.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from probos.dm_reply import DmReply
from probos.knowledge.lessons import (
    AFTER_ACTION_KEY,
    AFTER_ACTION_STATUS,
    AFTER_ACTION_SUBJECT_MAX_CHARS,
    AFTER_ACTION_VERSION,
    DECLINE_REPLY,
    EXIT_NOTE_AGENT_TYPE_MAX_CHARS,
    EXIT_NOTE_CALLSIGN_MAX_CHARS,
    EXIT_NOTE_DID_MAX_CHARS,
    LESSON_MAX_CHARS,
    REVIEW_ENDORSED,
    REVIEW_NOT_REVIEWED,
    REVIEW_RETURNED,
    REVIEW_STAGES,
    REVIEW_VACANT,
    after_action_body,
    after_action_lesson,
    after_action_path,
    after_action_review_ok,
    exit_note_provenance_ok,
    is_declined,
    is_exit_note_text,
    parse_citations,
    parse_lesson,
)
from probos.stand_down import (
    BOUNDED_TURN_PARAM,
    STAND_DOWN_EPISODES,
    CrewMember,
    crew_for_stand_down,
    offer_episodes,
    path_presence,
)
from probos.types import IntentMessage

if TYPE_CHECKING:
    from probos.knowledge.records_store import RecordsStore

logger = logging.getLogger(__name__)

#: AD-1341 S5 (D7): the longest one turn may take (the author's, or a reviewer's).
AFTER_ACTION_TURN_SECONDS: Final = 180.0
#: AD-1341 S5 (D7): the longest the whole report may take: the author's turn, both reviews and the write.
AFTER_ACTION_WINDOW_SECONDS: Final = 600.0
#: AD-1341 S5 (D5): the posts the second review stage looks for, in order: the Counselor, then the first officer (XO).
SECOND_REVIEW_POSTS: Final = ("counselor", "first_officer")
#: The two answers a reviewer may give. Anything else is no review.
REVIEW_ENDORSE_REPLY: Final = "ENDORSE"
REVIEW_RETURN_REPLY: Final = "RETURN"
_REVIEW_REPLY = re.compile(r"^[\W_]*(endorse|return)(?:[\W_].*)?$", re.IGNORECASE | re.DOTALL)


class AfterActionOutcome(StrEnum):
    """What the author's turn came to. Only WRITTEN wrote a report; ALREADY_WRITTEN found one at the path."""

    WRITTEN = "written"
    DECLINED = "declined"
    NOT_IN_FORMAT = "not_in_format"
    NO_REPLY = "no_reply"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ALREADY_WRITTEN = "already_written"


@dataclass(frozen=True)
class ReviewResult:
    """One review stage: its outcome and, when someone was asked, who."""

    stage: str
    outcome: str
    callsign: str = ""
    agent_type: str = ""
    did: str = ""

    def as_envelope(self) -> dict[str, str]:
        """The stage as the report's envelope records it."""
        return {
            "stage": self.stage, "outcome": self.outcome, "callsign": self.callsign, "agent_type": self.agent_type,
            "did": self.did,
        }


@dataclass(frozen=True)
class AfterActionReport:
    """One flagged event's report: the author's outcome, the path when there is one, and each review stage."""

    callsign: str
    agent_type: str
    outcome: AfterActionOutcome
    path: str = ""
    reviews: tuple[ReviewResult, ...] = ()

    @property
    def endorsed(self) -> bool:
        """Whether the chain admitted the written report to canon, by the promotion's own rule."""
        return self.outcome is AfterActionOutcome.WRITTEN and after_action_review_ok(
            [review.as_envelope() for review in self.reviews], self.agent_type,
        )


class AfterActionRefused(Exception):
    """No report can be asked for now. Nobody was asked and nothing was written."""


Ask = Callable[[CrewMember, str], Awaitable[str | None]]
Recall = Callable[[CrewMember], Awaitable[Sequence[Any]]]


def _can_review(member: CrewMember) -> bool:
    """Whether a member's callsign, agent type and DID can stand in a report's envelope."""
    return (
        is_exit_note_text(member.callsign, EXIT_NOTE_CALLSIGN_MAX_CHARS)
        and is_exit_note_text(member.agent_type, EXIT_NOTE_AGENT_TYPE_MAX_CHARS)
        and is_exit_note_text(member.did, EXIT_NOTE_DID_MAX_CHARS)
    )


def chain_of_command_reviewers(
    author: CrewMember, crew: Sequence[CrewMember], ontology: Any,
) -> tuple[tuple[str, CrewMember | None], ...]:
    """AD-1341 S5 (D5): each review stage and the crew agent who fills it now, or None when the billet is vacant.

    By billet, resolved at the time of the review: the superior is whoever fills the post the author's post reports to;
    the second stage is whoever fills the first of ``SECOND_REVIEW_POSTS`` that is neither the author's billet nor the
    superior's. A billet is filled by the first crew agent of its type, in crew order, whose identity the envelope can
    hold. Nobody reviews their own report. With no ontology every stage is vacant.
    """
    first_of_type: dict[str, CrewMember] = {}
    for member in crew:
        if _can_review(member):
            first_of_type.setdefault(member.agent_type, member)  # one turn per billet, in crew order (S4's rule)

    def filling(post_id: object) -> CrewMember | None:
        if ontology is None or type(post_id) is not str or not post_id:
            return None
        for assignment in sorted(ontology.get_agents_for_post(post_id), key=lambda item: item.agent_type):
            member = first_of_type.get(assignment.agent_type)
            if member is not None and member.agent_type != author.agent_type:
                return member
        return None

    post = ontology.get_post_for_agent(author.agent_type) if ontology is not None else None
    superior = filling(post.reports_to if post is not None else None)
    second: CrewMember | None = None
    for post_id in SECOND_REVIEW_POSTS:
        candidate = filling(post_id)
        if candidate is not None and (superior is None or candidate.agent_type != superior.agent_type):
            second = candidate
            break
    return ((REVIEW_STAGES[0], superior), (REVIEW_STAGES[1], second))


def after_action_prompt(callsign: str, subject: str, shown: Sequence[str]) -> str:
    """AD-1341 S5 (D3): the Captain's message for the author's turn: the event, what to write, where it goes."""
    episodes = "\n".join(shown) if shown else "(none could be read)"
    return (
        f"Captain to {callsign}: after-action report. The Captain has flagged this event for a hot wash: {subject}\n\n"
        "This is your one turn to record, from your own experience, what the ship should learn from it. Writing is "
        f"optional. To decline, reply exactly {DECLINE_REPLY} and nothing is recorded.\n\n"
        "If you write, reply in exactly this form, the four sections together at most "
        f"{LESSON_MAX_CHARS} characters:\n"
        "## Observation\n(what happened)\n"
        "## Discussion\n(why it happened and why it mattered)\n"
        "## Lesson\n(the general learning)\n"
        "## Recommendation\n(what to do differently)\n"
        "Cites: (optional) the handles of the episodes below that your observation rests on, for example e1, e3\n\n"
        "Your report then goes to your chain of command for review: your superior, then the Counselor or the first "
        "officer. If they endorse it, it is kept in Ship's Records under your callsign and DID, the Captain may review "
        "and veto it, and it may be archived in the Ship's Archive, where every later crew can read it, labelled as "
        "inherited from this crew. Write nothing you would not share with the whole ship. Summarise in your own words; "
        "do not quote your memories. Reply with the report alone, without using tools.\n\n"
        f"Your most recent episodes (handle, date, opening words):\n{episodes}"
    )


def review_prompt(callsign: str, author_callsign: str, report: str) -> str:
    """AD-1341 S5 (D5): the Captain's message for one reviewer's turn."""
    return (
        f"Captain to {callsign}: as part of the chain of command, review this after-action report by "
        f"{author_callsign} before it may enter the Ship's Archive, where every later crew can read it. Endorse it only "
        "if it is grounded, fit to share with the whole ship, and a lesson worth keeping.\n\n"
        f"Reply with one word: {REVIEW_ENDORSE_REPLY} to endorse it, or {REVIEW_RETURN_REPLY} to keep it out of the "
        "archive. Reply without using tools.\n\n"
        f"The report:\n{report}"
    )


def parse_review(reply: object) -> str:
    """A reviewer's answer: ``endorsed``, ``returned``, or ``not_reviewed`` for anything else (D5)."""
    if type(reply) is not str:
        return REVIEW_NOT_REVIEWED
    match = _REVIEW_REPLY.match(reply.strip())
    if match is None:
        return REVIEW_NOT_REVIEWED
    return REVIEW_ENDORSED if match.group(1).lower() == "endorse" else REVIEW_RETURNED


async def run_after_action(
    author: CrewMember,
    *,
    subject: str,
    flagged_at: str,
    reviewers: Sequence[tuple[str, CrewMember | None]],
    ask: Ask,
    recall: Recall,
    records: RecordsStore,
    timeline_id: str,
    turn_seconds: float = AFTER_ACTION_TURN_SECONDS,
    window_seconds: float = AFTER_ACTION_WINDOW_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> AfterActionReport:
    """Ask ``author`` for one report on ``subject``, have the chain review it, and write it once (D3 to D7).

    ``reviewers`` is one ``(stage, member or None)`` per ``REVIEW_STAGES`` entry, in order
    (``chain_of_command_reviewers``). ``ask`` delivers a prompt and returns the reply (None for no reply); ``recall``
    returns the author's most recent episodes. Each turn has one deadline, ``turn_seconds`` after it begins and never
    past the window, that its reply must meet. The window bounds every turn and the write, and no write begins once it
    has closed. A report already at its path is never written over, and then nobody is asked.

    Raises ``AfterActionRefused`` (nobody asked, nothing written) for a subject, identity, timeline or flag that cannot
    stand in a report, and ``ValueError`` for a bound that is not positive or reviewers not in stage order. Nothing a
    turn does raises.
    """
    if turn_seconds <= 0 or window_seconds <= 0:
        raise ValueError("AD-1341 S5: an after-action report's bounds must be positive")
    if [stage for stage, _member in reviewers] != list(REVIEW_STAGES):
        raise ValueError("AD-1341 S5: one reviewer entry per review stage, in order")
    if not is_exit_note_text(subject, AFTER_ACTION_SUBJECT_MAX_CHARS):
        raise AfterActionRefused(
            f"The subject must be one line of at most {AFTER_ACTION_SUBJECT_MAX_CHARS} characters."
        )
    if not exit_note_provenance_ok(timeline_id, author.callsign, author.agent_type, author.did):
        raise AfterActionRefused("The agent or this vessel has no identity a report could carry.")
    try:
        path = after_action_path(timeline_id, author.agent_type, flagged_at)
    except ValueError as exc:
        raise AfterActionRefused(f"The report cannot name a records path: {exc}") from exc

    def _done(outcome: AfterActionOutcome, at: str = "", reviews: Sequence[ReviewResult] = ()) -> AfterActionReport:
        return AfterActionReport(author.callsign, author.agent_type, outcome, at, tuple(reviews))

    present = path_presence(records.repo_path / path)
    if present is not False:  # a report is never written over, nor where that cannot be ruled out
        return _done(AfterActionOutcome.ALREADY_WRITTEN, path) if present else _done(AfterActionOutcome.FAILED)
    deadline = clock() + window_seconds

    async def _turn(member: CrewMember, prompt: str, turn_deadline: float) -> tuple[str, str | None]:
        """One bounded turn: ("answered", reply), ("timed_out", None) or ("failed", None). Never raises."""
        remaining = turn_deadline - clock()
        if remaining <= 0:
            return "timed_out", None
        try:
            reply = await asyncio.wait_for(ask(member, prompt), timeout=remaining)
        except TimeoutError:
            return "timed_out", None
        except Exception:  # log-and-degrade: a failed turn never stops the report or the console
            logger.warning("AD-1341 S5: %s's after-action turn failed", member.callsign, exc_info=True)
            return "failed", None
        if clock() > turn_deadline:  # a reply after the turn's deadline counts for nothing
            return "timed_out", None
        return "answered", reply

    turn_deadline = min(clock() + turn_seconds, deadline)
    try:
        episodes = await asyncio.wait_for(recall(author), timeout=max(0.001, turn_deadline - clock()))
    except Exception:  # log-and-degrade: the turn offers no episodes, so the report cites none
        logger.warning(
            "AD-1341 S5: %s's recent episodes could not be read; the turn offers none", author.callsign, exc_info=True,
        )
        episodes = ()
    offered, shown = offer_episodes(episodes)
    status, reply = await _turn(author, after_action_prompt(author.callsign, subject, shown), turn_deadline)
    if status != "answered":
        return _done(AfterActionOutcome.TIMED_OUT if status == "timed_out" else AfterActionOutcome.FAILED)
    if reply is None:
        return _done(AfterActionOutcome.NO_REPLY)
    if is_declined(reply):
        return _done(AfterActionOutcome.DECLINED)
    lesson = parse_lesson(reply)
    if lesson is None:
        return _done(AfterActionOutcome.NOT_IN_FORMAT)
    body = after_action_body(author.callsign, author.agent_type, timeline_id, lesson)
    if after_action_lesson(author.callsign, author.agent_type, timeline_id, body) != lesson:
        logger.error("AD-1341 S5: %s's report would not pass the promotion's rule; nothing is written", author.callsign)
        return _done(AfterActionOutcome.FAILED)
    cited = parse_citations(reply, offered)

    reviews: list[ReviewResult] = []
    for stage, reviewer in reviewers:
        if reviews and reviews[-1].outcome in (REVIEW_RETURNED, REVIEW_NOT_REVIEWED):
            reviews.append(ReviewResult(stage, REVIEW_NOT_REVIEWED))  # D5: the review ended at the stage before
            continue
        if reviewer is None or not _can_review(reviewer) or reviewer.agent_type == author.agent_type:
            reviews.append(ReviewResult(stage, REVIEW_VACANT))  # D5: nobody fills the billet; never the author
            continue
        status, answer = await _turn(
            reviewer, review_prompt(reviewer.callsign, author.callsign, body), min(clock() + turn_seconds, deadline),
        )
        outcome = parse_review(answer) if status == "answered" else REVIEW_NOT_REVIEWED
        reviews.append(ReviewResult(stage, outcome, reviewer.callsign, reviewer.agent_type, reviewer.did))

    envelope = {
        "version": AFTER_ACTION_VERSION,
        "timeline_id": timeline_id,
        "callsign": author.callsign,
        "agent_type": author.agent_type,
        "author_did": author.did,
        "flagged_at": flagged_at,
        "subject": subject,
        "source_episode_ids": list(cited),
        "review": [review.as_envelope() for review in reviews],
    }
    present = path_presence(records.repo_path / path)  # no await since: a report written meanwhile is kept
    if present is not False:
        return _done(AfterActionOutcome.ALREADY_WRITTEN, path, reviews) if present else _done(
            AfterActionOutcome.FAILED, "", reviews,
        )
    remaining = deadline - clock()
    if remaining <= 0:  # no write begins once the window has closed
        return _done(AfterActionOutcome.TIMED_OUT, "", reviews)
    written = records.write_entry(
        author=author.callsign,
        path=path,
        content=body,
        message=f"AD-1341 S5: after-action report of {author.callsign}",
        classification="ship",  # for every later crew, so ship-wide; C1 admits it to the archive
        status=AFTER_ACTION_STATUS,
        topic=f"After-action report of {author.callsign}",
        tags=["after-action", "ad-1341"],
        extra_frontmatter={AFTER_ACTION_KEY: envelope},
    )
    try:
        await asyncio.wait_for(written, timeout=remaining)
    except Exception as exc:  # log-and-degrade: what a cut-off write published stays and is reported (S4 A4)
        logger.warning("AD-1341 S5: %s's report write did not complete", author.callsign, exc_info=True)
        left = "" if path_presence(records.repo_path / path) is False else path
        outcome = AfterActionOutcome.TIMED_OUT if isinstance(exc, TimeoutError) else AfterActionOutcome.FAILED
        return _done(outcome, left, reviews)
    report = _done(AfterActionOutcome.WRITTEN, path, reviews)
    logger.info(
        "AD-1341 S5: after-action report of %s written at %s (%s)", author.callsign, path,
        "endorsed by the chain of command" if report.endorsed else "not endorsed: never archived",
    )
    return report


async def after_action_vessel(
    runtime: Any, callsign: str, subject: str, *, now: Callable[[], float] = time.time,
) -> AfterActionReport:
    """The Captain's ``/after-action`` on this vessel: refuse, or run one report and its review (D2, D3, D5)."""
    if not runtime.config.archive.enabled:
        raise AfterActionRefused("The Ship's Archive is disabled (archive.enabled), so no report would be archived.")
    records = runtime.records_store
    if records is None:
        raise AfterActionRefused("Ship's Records is not running, so no report could be kept.")
    ontology = runtime.ontology
    timeline_id = ontology.get_vessel_identity().instance_id if ontology is not None else ""
    if not timeline_id or timeline_id == "unknown":  # the ontology's placeholder when no identity is loaded
        raise AfterActionRefused("This vessel has no instance id, so a report could not be attributed to a timeline.")
    crew = crew_for_stand_down(runtime)
    wanted = callsign.strip().casefold()
    author = next((member for member in crew if member.callsign and member.callsign.casefold() == wanted), None)
    if author is None:
        raise AfterActionRefused("No crew agent answers to that callsign.")
    bus, memory = runtime.intent_bus, runtime.episodic_memory

    async def _ask(member: CrewMember, text: str) -> str | None:
        intent = IntentMessage(
            intent="direct_message",
            params={"text": text, "from": "captain", "session": False, BOUNDED_TURN_PARAM: True},  # S4 A2 (M2-1)
            target_agent_id=member.agent_id,
            ttl_seconds=AFTER_ACTION_TURN_SECONDS,
        )
        result = await bus.send(intent)
        if result is None or not result.success:  # refused, stopped or failed: no turn
            return None
        return DmReply.from_intent_result(result).body

    async def _recall(member: CrewMember) -> Sequence[Any]:
        if memory is None or not member.sovereign_id:
            return ()
        return await memory.recent_for_agent(member.sovereign_id, k=STAND_DOWN_EPISODES)

    return await run_after_action(
        author,
        subject=subject.strip(),
        flagged_at=time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now())),
        reviewers=chain_of_command_reviewers(author, crew, ontology),
        ask=_ask,
        recall=_recall,
        records=records,
        timeline_id=timeline_id,
    )
