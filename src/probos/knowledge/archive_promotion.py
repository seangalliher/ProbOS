"""Ship's Archive promotion (AD-1341 S1): the records-only service that writes the Ship's Archive.

A Ship's Computer service. Agents never call it, and nothing else calls ``ArchiveStore.promote_entry``
(``tests/test_ad1341_s1_promotion.py`` holds that with a census). It lists Ship's Records, keeps each document
that meets its source's criterion (``source_kind_for``), reads it as an anonymous reader, withholds what is
narrower than ``ship`` or has nothing to archive, and promotes the rest with their provenance.

- Episodes are never a source: they are memory, governed by AD-1340.
- No model call: every criterion is a fixed rule on the document's path and frontmatter.
- No failure is swallowed here. What a failure means is the caller's decision: ``probos reset`` refuses to wipe
  anything. One limit sits below this service: Ship's Records' listing (``list_entries``) skips a file it cannot
  decode, so such a file is neither promoted nor reported (AD-1341 S1 register RA3-1).
- Ship's Records carry no source-episode ids, so a records-sourced entry carries none. AD-1341 S4: an exit note
  (``exit-notes/``) is the exception. A stand-down writes it with its author's DID, callsign and agent type and the ids
  of the episodes it cites, and ``_exit_note_record`` turns it into an entry attributed to the timeline that wrote it.
  ``exit_note_citations`` is the AD-754 erasure's read of the citations the next promotion would archive.
- AD-1341 S3: a source the Captain vetoed is reported as vetoed and never archived. ``review_promotion`` is the
  Captain's review of the next run (``probos archive pending``): it reads, and records nothing.
- AD-1341 S5: an after-action report (``after-action/``) is a source with its own rule (``_after_action_record``):
  S4's exit-note rule plus the chain-of-command review, so only a report its chain endorsed is archived.
  ``promote_settled`` is the continuous promotion (a dream step, default off): the same plan, settled sources only, a
  bounded batch, and a citing source only inside the AD-754 erasure lock while its episodes are live.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from probos.knowledge.archive_store import (
    PROMOTABLE_CLASSIFICATIONS,
    ArchiveStore,
    PromotionOutcome,
    PromotionRecord,
    SourceKind,
    SourceState,
)
from probos.knowledge.lessons import (
    AFTER_ACTION_DIR,
    AFTER_ACTION_KEY,
    AFTER_ACTION_SUBJECT_MAX_CHARS,
    AFTER_ACTION_VERSION,
    EXIT_NOTE_EPISODE_ID_MAX_CHARS,
    EXIT_NOTE_KEY,
    EXIT_NOTE_VERSION,
    EXIT_NOTES_DIR,
    LESSON_MAX_CITATIONS,
    REVIEW_ENDORSED,
    after_action_lesson,
    after_action_path,
    after_action_review_ok,
    exit_note_lesson,
    exit_note_path,
    exit_note_provenance_ok,
    is_exit_note_text,
)
from probos.knowledge.records_store import RecordsStore

logger = logging.getLogger(__name__)

#: The identity the service reads Ship's Records as. Anonymous, never "captain": the store's own read rule
#: (BF-679) withholds private records, and department records outside their department, before the
#: classification gate below sees them.
ARCHIVE_READER = ""


def source_kind_for(path: str, frontmatter: Any) -> SourceKind | None:
    """The per-source criterion: the kind a Ship's Records document is promoted as, or None.

    - ``reports/convergence/`` written by ``system`` (AD-551's convergence step): a convergence report.
    - ``captains-log/`` written by ``captain``: the Captain's log.
    - any other ``reports/`` document whose status is ``published``: a published report.
    - ``notebooks/`` with a non-empty ``claim_id`` (a finding published through AD-1140's governed route) or
      whose status is ``published``: a notebook finding.
    - ``exit-notes/`` (AD-1341 S4): an exit note. Its own rule, ``_exit_note_record``, applies when it is read.

    Nothing else is promoted: manuals (seeded by the shipyard), duty logs, bills, consultations, creative work,
    drafts and an agent's working notes. Classification is a separate gate (C1), applied to what is read.
    """
    if type(frontmatter) is not dict:
        return None
    if path.startswith(f"{EXIT_NOTES_DIR}/"):
        return SourceKind.EXIT_NOTE  # AD-1341 S4: every exit note is a source; _exit_note_record withholds a bad one
    if path.startswith(f"{AFTER_ACTION_DIR}/"):
        return SourceKind.AFTER_ACTION_REPORT  # AD-1341 S5: every report is a source; _after_action_record withholds a bad one
    author = frontmatter.get("author")
    status = frontmatter.get("status")
    if path.startswith("reports/convergence/"):
        return SourceKind.CONVERGENCE_REPORT if author == "system" else None
    if path.startswith("captains-log/"):
        return SourceKind.CAPTAINS_LOG if author == "captain" else None
    if path.startswith("reports/"):
        return SourceKind.PUBLISHED_REPORT if status == "published" else None
    if path.startswith("notebooks/"):
        claim_id = frontmatter.get("claim_id")
        if (type(claim_id) is str and claim_id.strip()) or status == "published":
            return SourceKind.NOTEBOOK_FINDING
    return None


#: AD-1341 S5 (D17, register F-661): the frontmatter values ``_stored_text`` converts. ``datetime`` is a ``date``.
_SCALARS = (str, int, float, bool, date)


def _stored_text(value: object) -> str:
    """AD-1341 S4 (A5, round 3 R3-M1-2): a stored frontmatter value as archive text; never raises.

    AD-1341 S5 (F-661): only a scalar converts. A list, a mapping or any other object is archived as no value: a YAML
    alias chain deeper than the recursion limit made ``str()`` raise ``RecursionError``, and a graph whose every level
    names the one below twice made it run for an exponential time, which would stall the dream step and the reset.

    ``str()`` raises ``ValueError`` for an integer longer than Python's integer-string limit (4,300 digits by default,
    ``sys.set_int_max_str_digits``), which YAML builds from ``0x...``; one such value stopped the plan and the whole
    reset. It is archived as no value, as a missing one is. Every other value converts exactly as ``str()`` did.
    """
    if not value or not isinstance(value, _SCALARS):
        return ""  # AD-1341 S5 (F-661): a container, an alias graph included, is never walked by str()
    try:
        return str(value)
    except ValueError:  # A5 (R3-M1-2): an integer longer than Python's integer-string limit
        logger.warning("AD-1341 S4: a stored Ship's Records value cannot be shown as text; it is archived empty")
        return ""


def _title_for(path: str, frontmatter: dict[str, Any]) -> str:
    """The archive entry's title: the document's topic, else its file name, else its records path (A3, F1).

    The producers accept a blank topic (``write_entry(topic="   ")``, ``write_notebook(topic_slug=" ")``) and the
    promotion record refuses a blank title. A title is a label, so it never withholds a document or stops a run.
    The records path is never blank: only a path under a source's directory is a source.
    """
    topic = frontmatter.get("topic")
    for candidate in (_stored_text(topic), path.rsplit("/", 1)[-1].removesuffix(".md")):
        if candidate.strip():
            return candidate
    return path


def _exit_note_record(path: str, document: Any) -> PromotionRecord | None:
    """AD-1341 S4: an exit note as the Ship's Archive receives it, or None when it breaks the exit-note rule (D7, D9).

    The rule: the ``exit_note`` envelope (version 1, an ``int``) names a timeline, a callsign, an agent type and the
    author's DID, each one line within its bound (``exit_note_provenance_ok``), and lists at most
    ``LESSON_MAX_CITATIONS`` distinct episode ids, each one line within its bound; the path is the one
    ``exit_note_path`` gives for that timeline and agent type; the author is the callsign; the body is exactly the
    note's origin line followed by a canonical lesson (``exit_note_lesson``), so what is archived is what the Captain
    reviewed and what the rule parsed (A2); the classification is ``ship`` or ``fleet`` (C1). The entry is attributed
    to the timeline that wrote the note, not to the reset that promotes it, so a note a skipped promotion left behind
    keeps its own generation.

    Never raises for a document: every value ``PromotionRecord`` would refuse is checked here first, and a stored
    value ``str()`` cannot convert is archived as no value (``_stored_text``, A5), so one bad note is withheld or
    archived and never stops a reset (S1 A3's rule). The one rule for the promotion and for ``exit_note_citations``.
    """
    if type(document) is not dict or type(document.get("frontmatter")) is not dict:
        return None
    frontmatter, content = document["frontmatter"], document.get("content")
    envelope = frontmatter.get(EXIT_NOTE_KEY)
    if type(envelope) is not dict:
        return None
    version = envelope.get("version")
    if type(version) is not int or version != EXIT_NOTE_VERSION:  # A2: True and 1.0 equal 1 and are not it
        return None
    named = [envelope.get(field) for field in ("timeline_id", "callsign", "agent_type", "author_did")]
    if not exit_note_provenance_ok(*named):  # A2: one storable line each, within its bound
        return None
    note_timeline, callsign, agent_type, author_did = named
    cited = envelope.get("source_episode_ids")
    if type(cited) is not list or not all(is_exit_note_text(item, EXIT_NOTE_EPISODE_ID_MAX_CHARS) for item in cited):
        return None
    if len(cited) > LESSON_MAX_CITATIONS or len(set(cited)) != len(cited):
        return None
    try:
        expected_path = exit_note_path(note_timeline, agent_type)
    except ValueError:
        return None
    if path != expected_path or frontmatter.get("author") != callsign:
        return None
    if exit_note_lesson(callsign, agent_type, note_timeline, content) is None:
        return None  # A2: the body is exactly the origin line and a canonical lesson, or nothing is archived
    classification = frontmatter.get("classification")
    if type(classification) is not str or classification not in PROMOTABLE_CLASSIFICATIONS:
        return None  # C1: nothing narrower than ship reaches a later crew
    return PromotionRecord(
        timeline_id=note_timeline,  # AD-1341 S4 (D9): the timeline that wrote the note, not the reset's
        source_kind=SourceKind.EXIT_NOTE,
        source_ref=path,
        title=f"Exit notes of {callsign}",
        content=content,
        classification=classification,
        author_callsign=callsign,
        author_agent_type=agent_type,
        author_did=author_did,
        source_episode_ids=tuple(cited),  # AD-1341 S4: the agent's own episodes, by id; never their text
        metadata={  # A5 (R3-M1-2): each stored value through the one never-raising conversion
            "status": _stored_text(frontmatter.get("status")),
            "record_created": _stored_text(frontmatter.get("created")),
            "record_updated": _stored_text(frontmatter.get("updated")),
        },
    )


def _after_action_record(path: str, document: Any) -> PromotionRecord | None:
    """AD-1341 S5: an after-action report as the Ship's Archive receives it, or None when it breaks the rule (D4, D5).

    S4's exit-note rule with the report's own envelope, plus the chain-of-command review. The envelope (version 1, an
    ``int``) names a timeline, a callsign, an agent type and the author's DID (``exit_note_provenance_ok``), the flag's
    time, a one-line subject and at most ``LESSON_MAX_CITATIONS`` distinct episode ids. The path is ``after_action_path``
    of them, and the author is the callsign. The body is exactly the canonical report (``after_action_lesson``), the
    recorded review admits it (``after_action_review_ok``), and the classification is ``ship`` or ``fleet`` (C1). The
    entry is attributed to the timeline that wrote the report. Never raises for a document. The one rule for the reset,
    the continuous step and the erasure's citation read.
    """
    if type(document) is not dict or type(document.get("frontmatter")) is not dict:
        return None
    frontmatter, content = document["frontmatter"], document.get("content")
    envelope = frontmatter.get(AFTER_ACTION_KEY)
    if type(envelope) is not dict:
        return None
    version = envelope.get("version")
    if type(version) is not int or version != AFTER_ACTION_VERSION:  # True and 1.0 equal 1 and are not it (S4 A2)
        return None
    named = [envelope.get(field) for field in ("timeline_id", "callsign", "agent_type", "author_did")]
    if not exit_note_provenance_ok(*named):
        return None
    report_timeline, callsign, agent_type, author_did = named
    flagged_at, subject = envelope.get("flagged_at"), envelope.get("subject")
    if not is_exit_note_text(subject, AFTER_ACTION_SUBJECT_MAX_CHARS):
        return None
    cited = envelope.get("source_episode_ids")
    if type(cited) is not list or not all(is_exit_note_text(item, EXIT_NOTE_EPISODE_ID_MAX_CHARS) for item in cited):
        return None
    if len(cited) > LESSON_MAX_CITATIONS or len(set(cited)) != len(cited):
        return None
    try:
        expected_path = after_action_path(report_timeline, agent_type, flagged_at)
    except ValueError:
        return None
    if path != expected_path or frontmatter.get("author") != callsign:
        return None
    if after_action_lesson(callsign, agent_type, report_timeline, content) is None:
        return None
    if not after_action_review_ok(envelope.get("review"), agent_type):
        return None  # AD-1341 S5 (D5): no endorsement by the chain of command, no canon
    classification = frontmatter.get("classification")
    if type(classification) is not str or classification not in PROMOTABLE_CLASSIFICATIONS:
        return None  # C1: nothing narrower than ship reaches a later crew
    endorsed_by = [entry["callsign"] for entry in envelope["review"] if entry.get("outcome") == REVIEW_ENDORSED]
    return PromotionRecord(
        timeline_id=report_timeline,  # the timeline that wrote the report, not the promoting run's
        source_kind=SourceKind.AFTER_ACTION_REPORT,
        source_ref=path,
        title=f"After-action report of {callsign}",
        content=content,
        classification=classification,
        author_callsign=callsign,
        author_agent_type=agent_type,
        author_did=author_did,
        source_episode_ids=tuple(cited),  # the author's own offered episodes, by id; never their text
        metadata={
            "status": _stored_text(frontmatter.get("status")),
            "record_created": _stored_text(frontmatter.get("created")),
            "record_updated": _stored_text(frontmatter.get("updated")),
            "flagged_at": flagged_at,
            "subject": subject,
            "endorsed_by": endorsed_by,
        },
    )


def _lesson_record(path: str, document: Any) -> PromotionRecord | None:
    """AD-1341 S5: the one rule of a lesson source, by its directory: an after-action report's, or an exit note's."""
    if path.startswith(f"{AFTER_ACTION_DIR}/"):
        return _after_action_record(path, document)
    return _exit_note_record(path, document)


#: AD-1341 S5: the Ship's Records directories whose documents cite episodes: exit notes and after-action reports.
_LESSON_DIRS = (EXIT_NOTES_DIR, AFTER_ACTION_DIR)


async def exit_note_citations(records: RecordsStore, archive: ArchiveStore | None) -> dict[str, tuple[str, ...]]:
    """AD-1341 S4 (D14), S5: each episode id cited by a lesson the next promotion would archive, with those lessons.

    The lessons are read as the promotion reads them (``_lesson_record``, the one rule). With an open archive a lesson
    counts while ``source_state`` says CREATED; a vetoed, erased or already archived one does not (an archived one is
    S3's own check). With no open archive every valid lesson counts (fail closed: the next reset opens the archive
    and would promote it). Reads Ship's Records and the archive; writes nothing; any failure propagates.

    A2 (M1-F1, M3-F1): each listing is strict, so a lesson file that exists but cannot be read now (a sharing violation,
    a permission, an I/O error) raises instead of being skipped as if it were not there. A file whose bytes are not
    UTF-8, or whose frontmatter does not parse, is never counted, because the promotion never archives it either: that
    is a property of the file, not of the moment.

    A5 (7.3a's table, O6): each listed lesson is read again through ``read_entry``, whose ``Path.exists`` answers False
    for errors ``pathlib`` reads as "not there". A ship-wide lesson the strict listing returned and the second read
    cannot find raises: it was there a moment ago, so whether the next promotion would archive it is unknown.

    AD-1341 S5: after-action reports (``after-action/``) are read too, so ``/forget`` refuses while a report its chain
    endorsed, awaiting promotion, cites a matched episode. The name and the route's 409 code
    (``exit_notes_cite_erased_episodes``) are kept, so no caller or wire contract changes; the paths say which
    documents they are (register R10).
    """
    citing: dict[str, list[str]] = {}
    for directory in _LESSON_DIRS:
        for listed in await records.list_entries(directory, strict=True):
            path = listed["path"]
            kind = source_kind_for(path, listed["frontmatter"])
            if kind is not SourceKind.EXIT_NOTE and kind is not SourceKind.AFTER_ACTION_REPORT:
                continue  # plan_promotion skips it unread (frontmatter not a mapping), so it can never be archived
            document = await records.read_entry(path, ARCHIVE_READER)
            classification = listed["frontmatter"].get("classification")
            listed_readable = type(classification) is str and classification in PROMOTABLE_CLASSIFICATIONS
            if document is None and listed_readable:  # A5 (O6): listed a moment ago, not found now
                raise OSError(f"AD-1341 S4: the lesson {path} was listed but cannot be found now")
            record = _lesson_record(path, document)
            if record is None or not record.source_episode_ids:
                continue
            if archive is not None and (await archive.source_state(record)).outcome is not PromotionOutcome.CREATED:
                continue
            for episode_id in record.source_episode_ids:
                citing.setdefault(episode_id, []).append(path)
    return {episode_id: tuple(paths) for episode_id, paths in citing.items()}


@dataclass(frozen=True)
class PromotionPlan:
    """What a run would promote, and what met its criterion but may not be archived. Building it writes nothing."""

    records: tuple[PromotionRecord, ...]
    withheld: tuple[str, ...]


@dataclass(frozen=True)
class PromotionReport:
    """What one run did, as Ship's Records paths, in the order the records were listed."""

    created: tuple[str, ...]
    present: tuple[str, ...]
    erased: tuple[str, ...]
    withheld: tuple[str, ...]
    vetoed: tuple[str, ...] = ()  # AD-1341 S3: sources the Captain vetoed; never archived
    waiting: tuple[str, ...] = ()  # AD-1341 S5: left for a later continuous step or the reset (not settled, or unchecked)


async def plan_promotion(records: RecordsStore, *, timeline_id: str) -> PromotionPlan:
    """The records a run would promote, attributed to ``timeline_id``. Reads Ship's Records; writes nothing.

    ``probos reset --dry-run`` lists this plan. A document is withheld when the anonymous read refuses it, when
    its body is empty, or when it is narrower than ``ship`` (C1: a later crew reads every archived entry). An
    empty ``timeline_id`` raises as soon as there is anything to promote. A blank topic withholds nothing: the title
    falls back to the file name, then the records path (A3, F1).

    AD-1341 S4: an exit note (``exit-notes/``) is the exception to both. ``_exit_note_record`` attributes it to the
    timeline in its own envelope, never to ``timeline_id``, and a valid note never raises for an empty
    ``timeline_id`` (the CLI refuses a run without an instance id before it plans). A note that breaks the rule is
    withheld. The listing is not strict: a file that cannot be read at this moment is skipped, as S1 left it.

    AD-1341 S5: an after-action report (``after-action/``) is the same kind of exception, with its own rule
    (``_after_action_record``): only a report its chain of command endorsed is selected.
    """
    selected: list[PromotionRecord] = []
    withheld: list[str] = []
    for listed in await records.list_entries():
        path = listed["path"]
        if source_kind_for(path, listed["frontmatter"]) is None:
            continue
        document = await records.read_entry(path, ARCHIVE_READER)
        if document is None:
            withheld.append(path)
            continue
        if path.startswith(f"{AFTER_ACTION_DIR}/"):  # AD-1341 S5: a report carries its own provenance and its review
            report = _after_action_record(path, document)
            if report is None:
                withheld.append(path)
            else:
                selected.append(report)
            continue
        if path.startswith(f"{EXIT_NOTES_DIR}/"):  # AD-1341 S4: an exit note carries its own provenance
            note = _exit_note_record(path, document)
            if note is None:
                withheld.append(path)
            else:
                selected.append(note)
            continue
        frontmatter = document["frontmatter"]
        kind = source_kind_for(path, frontmatter)
        content = document["content"]
        if kind is None or not content.strip():
            withheld.append(path)
            continue
        classification = frontmatter.get("classification")
        if type(classification) is not str or classification not in PROMOTABLE_CLASSIFICATIONS:
            withheld.append(path)  # C1: nothing narrower than ship reaches a later crew
            continue
        selected.append(
            PromotionRecord(
                timeline_id=timeline_id,
                source_kind=kind,
                source_ref=path,
                title=_title_for(path, frontmatter),
                content=content,
                classification=classification,
                author_callsign=_stored_text(frontmatter.get("author")),
                metadata={  # AD-1341 S4 (A5): S1's conversions, through the one never-raising rule
                    "status": _stored_text(frontmatter.get("status")),
                    "department": _stored_text(frontmatter.get("department")),
                    "record_created": _stored_text(frontmatter.get("created")),
                    "record_updated": _stored_text(frontmatter.get("updated")),
                },
            )
        )
    return PromotionPlan(records=tuple(selected), withheld=tuple(withheld))


async def promote_ship_records(
    records: RecordsStore, archive: ArchiveStore, *, timeline_id: str,
) -> PromotionReport:
    """Promote every Ship's Records document that meets its criterion into the Ship's Archive.

    Idempotent: a second run, under this timeline or the next, archives nothing new. Any failure propagates
    after the store has rolled its transaction back; entries promoted before it stay, and a re-run finds
    them present.
    """
    plan = await plan_promotion(records, timeline_id=timeline_id)
    created: list[str] = []
    present: list[str] = []
    erased: list[str] = []
    vetoed: list[str] = []
    for record in plan.records:
        outcome = await archive.promote_entry(record)
        if outcome is PromotionOutcome.CREATED:
            created.append(record.source_ref)
        elif outcome is PromotionOutcome.ERASED:
            erased.append(record.source_ref)
        elif outcome is PromotionOutcome.VETOED:  # AD-1341 S3: the Captain's veto, reported, never archived
            vetoed.append(record.source_ref)
        else:
            present.append(record.source_ref)
    logger.info(
        "AD-1341: Ship's Archive promotion for timeline %s: %d created, %d already archived, "
        "%d erased by the Captain, %d vetoed by the Captain, %d withheld",
        timeline_id, len(created), len(present), len(erased), len(vetoed), len(plan.withheld),
    )
    return PromotionReport(
        created=tuple(created), present=tuple(present), erased=tuple(erased), withheld=plan.withheld,
        vetoed=tuple(vetoed),
    )


@dataclass(frozen=True)
class PendingSource:
    """AD-1341 S3: one source the next promotion would consider, and what promoting it now would do."""

    record: PromotionRecord
    state: SourceState


@dataclass(frozen=True)
class PromotionReview:
    """AD-1341 S3: the Captain's review of the next promotion, in the order Ship's Records lists the sources."""

    sources: tuple[PendingSource, ...]
    withheld: tuple[str, ...]


async def review_promotion(records: RecordsStore, archive: ArchiveStore, *, timeline_id: str) -> PromotionReview:
    """AD-1341 S3 (D3): every source that meets its criterion, with what promoting it now would do; and what is withheld.

    The queue is derived: the plan the next run would promote (``plan_promotion``), each source's state read from the
    archive (``ArchiveStore.source_state``). It reads Ship's Records and the archive and records nothing. A veto or
    erasure after the review decides the promotion (D6).
    """
    plan = await plan_promotion(records, timeline_id=timeline_id)
    sources = [PendingSource(record, await archive.source_state(record)) for record in plan.records]
    return PromotionReview(sources=tuple(sources), withheld=plan.withheld)


#: AD-1341 S5 (D9, Amendment A3): one UTC day in seconds. POSIX time counts no leap seconds, so every day is this long.
_DAY_SECONDS = 86_400.0


def _captains_log_day_end(ref: str) -> float | None:
    """The end of a Captain's log file's UTC day (seconds since the epoch), or None for a name its writer never gives.

    ``RecordsStore.append_captains_log`` appends to ``captains-log/YYYY-MM-DD.md``, the day read from the UTC clock in
    the same synchronous step as the write, so a day's file takes no entry once that day has ended. It stamps
    ``created`` and never ``updated``.
    """
    try:
        day = date.fromisoformat(ref.removeprefix("captains-log/").removesuffix(".md"))
    except ValueError:
        return None
    if ref != f"captains-log/{day.isoformat()}.md":
        return None  # the writer's own name only: date.fromisoformat also reads 20261026 and 2026-W44-1
    return datetime.fromisoformat(f"{day.isoformat()}T00:00:00+00:00").timestamp() + _DAY_SECONDS


def is_settled(record: PromotionRecord, settled_before: float) -> bool:
    """AD-1341 S5 (D9): whether a source was last updated at or before ``settled_before`` (seconds since the epoch).

    Read from the record's ``record_updated`` (Ship's Records' ``updated``, an ISO 8601 time with its offset). A time
    with no offset, or one that does not parse, is not settled: such a source waits for the reset's promotion.

    Amendment A3: a Captain's log carries no ``updated`` (its writer stamps none) and takes no entry after its UTC day,
    so it settles once its day has ended at or before ``settled_before`` and, if it carries an ``updated``, once that
    has settled too. A Captain's log under any other name never settles here; the reset still promotes it.
    """
    if record.source_kind is SourceKind.CAPTAINS_LOG:
        ended = _captains_log_day_end(record.source_ref)
        if ended is None or ended > settled_before:
            return False
        if not record.metadata.get("record_updated"):
            return True  # the writer's own form: its day is over, so no entry can follow
    stamp = record.metadata.get("record_updated")
    if type(stamp) is not str:
        return False
    try:
        updated = datetime.fromisoformat(stamp)
    except ValueError:
        return False
    if updated.tzinfo is None:
        return False
    return updated.timestamp() <= settled_before


async def promote_settled(
    records: RecordsStore,
    archive: ArchiveStore,
    *,
    timeline_id: str,
    settled_before: float,
    max_created: int,
    cited_live: Callable[[tuple[str, ...]], Awaitable[bool]],
    exclusive: Callable[[], AbstractAsyncContextManager[Any]],
) -> PromotionReport:
    """AD-1341 S5 (D8 to D13): one continuous promotion. Archive settled sources, at most ``max_created`` new entries.

    The reset's own plan and rules (``plan_promotion``), so nothing reaches the archive here that the reset would not.
    A source is promoted only once it has settled (``is_settled``), so the Captain's review (``probos archive pending``,
    ``probos archive veto``) keeps a window before canon. A source the archive would not take now (present, erased,
    vetoed: ``source_state``) is passed over without a write. A source that cites episodes is promoted inside
    ``exclusive()`` (the AD-754 erasure lock) and only when ``cited_live`` says every cited episode is live, so no
    erasure runs between that check and the insert, nor between an erasure's own citation check and its erase (S3
    register R3). Anything else waits (``waiting``) for a later step or the reset; sources after the batch is full are
    not considered this time. No model call. Each write is ``promote_entry``'s one statement, so a step cut off part-way
    leaves only whole entries and the next step finds them present. Any failure propagates: the dream step logs it.
    """
    if type(max_created) is not int or max_created < 1:
        raise ValueError("AD-1341 S5: max_created is a positive integer")
    plan = await plan_promotion(records, timeline_id=timeline_id)
    created: list[str] = []
    present: list[str] = []
    erased: list[str] = []
    vetoed: list[str] = []
    waiting: list[str] = []
    by_outcome = {
        PromotionOutcome.CREATED: created,
        PromotionOutcome.PRESENT: present,
        PromotionOutcome.ERASED: erased,
        PromotionOutcome.VETOED: vetoed,
    }
    for record in plan.records:
        if len(created) >= max_created:
            break  # D10: the batch is full; the rest are considered by the next step
        if not is_settled(record, settled_before):
            waiting.append(record.source_ref)
            continue
        state = (await archive.source_state(record)).outcome
        if state is not PromotionOutcome.CREATED:
            by_outcome[state].append(record.source_ref)  # D10: no write for what the archive would not take
            continue
        if not record.source_episode_ids:
            by_outcome[await archive.promote_entry(record)].append(record.source_ref)
            continue
        async with exclusive():  # D11 (S3 R3): no erasure between the check below and the insert
            if not await cited_live(record.source_episode_ids):
                waiting.append(record.source_ref)  # a cited episode is not live: erased, demoted, or unreadable
                continue
            outcome = await archive.promote_entry(record)
        by_outcome[outcome].append(record.source_ref)
    logger.info(
        "AD-1341 S5: continuous promotion for timeline %s: %d created, %d already archived, %d erased by the Captain, "
        "%d vetoed by the Captain, %d waiting, %d withheld",
        timeline_id, len(created), len(present), len(erased), len(vetoed), len(waiting), len(plan.withheld),
    )
    return PromotionReport(
        created=tuple(created), present=tuple(present), erased=tuple(erased), withheld=plan.withheld,
        vetoed=tuple(vetoed), waiting=tuple(waiting),
    )
