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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
    EXIT_NOTE_KEY,
    EXIT_NOTE_VERSION,
    EXIT_NOTES_DIR,
    LESSON_MAX_CITATIONS,
    exit_note_header,
    exit_note_path,
    parse_lesson,
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


def _title_for(path: str, frontmatter: dict[str, Any]) -> str:
    """The archive entry's title: the document's topic, else its file name, else its records path (A3, F1).

    The producers accept a blank topic (``write_entry(topic="   ")``, ``write_notebook(topic_slug=" ")``) and the
    promotion record refuses a blank title. A title is a label, so it never withholds a document or stops a run.
    The records path is never blank: only a path under a source's directory is a source.
    """
    topic = frontmatter.get("topic")
    for candidate in (str(topic) if topic else "", path.rsplit("/", 1)[-1].removesuffix(".md")):
        if candidate.strip():
            return candidate
    return path


def _exit_note_record(path: str, document: Any) -> PromotionRecord | None:
    """AD-1341 S4: an exit note as the Ship's Archive receives it, or None when it breaks the exit-note rule (D7, D9).

    The rule: the ``exit_note`` envelope (version 1) names a timeline, a callsign, an agent type and the author's DID,
    and lists at most ``LESSON_MAX_CITATIONS`` distinct episode ids; the path is the one ``exit_note_path`` gives for
    that timeline and agent type; the author is the callsign; the body is the note's origin line followed by a lesson
    in the format; the classification is ``ship`` or ``fleet`` (C1). The entry is attributed to the timeline that wrote
    the note, not to the reset that promotes it, so a note a skipped promotion left behind keeps its own generation.

    Never raises for a document: every value ``PromotionRecord`` would refuse is checked here first, so one bad note is
    withheld and never stops a reset (S1 A3's rule). The one rule for the promotion and for ``exit_note_citations``.
    """
    if type(document) is not dict or type(document.get("frontmatter")) is not dict:
        return None
    frontmatter, content = document["frontmatter"], document.get("content")
    envelope = frontmatter.get(EXIT_NOTE_KEY)
    if type(envelope) is not dict or envelope.get("version") != EXIT_NOTE_VERSION:
        return None
    named = [envelope.get(field) for field in ("timeline_id", "callsign", "agent_type", "author_did")]
    if any(type(value) is not str or not value.strip() for value in named):
        return None
    note_timeline, callsign, agent_type, author_did = named
    cited = envelope.get("source_episode_ids")
    if type(cited) is not list or any(type(item) is not str or not item.strip() for item in cited):
        return None
    if len(cited) > LESSON_MAX_CITATIONS or len(set(cited)) != len(cited):
        return None
    try:
        expected_path = exit_note_path(note_timeline, agent_type)
    except ValueError:
        return None
    if path != expected_path or frontmatter.get("author") != callsign:
        return None
    header = exit_note_header(callsign, agent_type, note_timeline)
    if type(content) is not str or not content.startswith(f"{header}\n\n") or parse_lesson(content) is None:
        return None
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
        metadata={
            "status": str(frontmatter.get("status") or ""),
            "record_created": str(frontmatter.get("created") or ""),
            "record_updated": str(frontmatter.get("updated") or ""),
        },
    )


async def exit_note_citations(records: RecordsStore, archive: ArchiveStore | None) -> dict[str, tuple[str, ...]]:
    """AD-1341 S4 (D14): each episode id cited by an exit note the next promotion would archive, with those notes.

    The notes are read as the promotion reads them (``_exit_note_record``, the one rule). With an open archive a note
    counts while ``source_state`` says CREATED; a vetoed, erased or already archived note does not (an archived one
    is S3's own check). With no open archive every valid note counts (fail closed: the next reset opens the archive
    and would promote it). Reads Ship's Records and the archive; writes nothing; any failure propagates.
    """
    citing: dict[str, list[str]] = {}
    for listed in await records.list_entries(EXIT_NOTES_DIR):
        path = listed["path"]
        if source_kind_for(path, listed["frontmatter"]) is not SourceKind.EXIT_NOTE:
            continue  # plan_promotion skips it unread (frontmatter not a mapping), so it can never be archived
        record = _exit_note_record(path, await records.read_entry(path, ARCHIVE_READER))
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


async def plan_promotion(records: RecordsStore, *, timeline_id: str) -> PromotionPlan:
    """The records a run would promote, attributed to ``timeline_id``. Reads Ship's Records; writes nothing.

    ``probos reset --dry-run`` lists this plan. A document is withheld when the anonymous read refuses it, when
    its body is empty, or when it is narrower than ``ship`` (C1: a later crew reads every archived entry). An
    empty ``timeline_id`` raises as soon as there is anything to promote. A blank topic withholds nothing: the title
    falls back to the file name, then the records path (A3, F1).
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
                author_callsign=str(frontmatter.get("author") or ""),
                metadata={
                    "status": str(frontmatter.get("status") or ""),
                    "department": str(frontmatter.get("department") or ""),
                    "record_created": str(frontmatter.get("created") or ""),
                    "record_updated": str(frontmatter.get("updated") or ""),
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
