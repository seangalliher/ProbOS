"""Ship's Archive — cross-reset generational knowledge persistence (AD-524, AD-1341).

Stores curated knowledge entries that survive resets. Agents and services never
update or delete an entry. The one write is ``ArchiveStore.promote_entry``
(AD-1341), called only by the promotion service
(``probos.knowledge.archive_promotion``); it is idempotent on the source and its
content. The one removal is the Captain's ``erase_entry``, reached only from the
offline ``probos archive erase``: it deletes the row and leaves a marker in
``archive_erasures`` that holds no title, content or hash.

AD-1341 S3: the Captain reviews what the next promotion would archive
(``source_state``, through ``probos archive pending``) and may veto a source
before it is archived (``veto_source``, through ``probos archive veto``): a row
in ``archive_vetoes`` that holds no title, content or hash, and that
``promote_entry`` honours for the source with any content. The AD-754 erasure
manager reads ``entry_ids_citing`` and erases nothing while an entry cites an
episode it would erase, until the Captain has erased that entry.

Each entry records the timeline (instance) it came from, its source kind and
reference, the content's SHA-256, its classification (``ship`` or ``fleet``: a
later crew reads every entry) and when it was archived. ``generations`` records
each crew generation's close at a reset of tier 2 or above, including a
promotion the Captain skipped and why.

AD-1341 S2: ``generations`` also numbers the crews. A timeline's generation is
its first close's place among the closes attributed to a timeline, and every read
fills an entry's ``generation`` from it. ``inheritance_label`` is what an agent
reads first about an archived entry: inherited from the crew of generation N, or
from an earlier crew, or archived by this crew; never its own memory. The Oracle's
archive tier (``OracleService._query_archive``) is the one place that attaches it.

Schema: ``PRAGMA user_version`` 1. A version-0 archive (AD-524) is migrated in
place by adding columns; any other version is refused. Every connection sets
``PRAGMA secure_delete=ON`` and verifies it, so an erased row's bytes are
overwritten in the file (earlier backup snapshots hold them until they age out).

Storage location: {archive_dir}/archive.db (outside instance data_dir).
Default archive_dir: platform-specific ProbOS home / archive/.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArchiveEntry:
    """A single archived knowledge entry."""

    id: int
    timeline_id: str
    category: str
    title: str
    content: str
    author_agent_type: str
    author_callsign: str
    archived_at: float
    metadata: dict[str, Any] = field(default_factory=dict)
    # AD-1341: provenance. Empty for an AD-524 entry written before schema v1.
    source_kind: str = ""
    source_ref: str = ""
    content_sha256: str = ""
    classification: str = ""
    author_did: str = ""
    source_episode_ids: tuple[str, ...] = ()
    # AD-1341 S2 (D3): the crew generation that archived it: 1 for the first crew whose close ``generations``
    # records. None when its timeline has no recorded close (an AD-524 entry, or a close that failed).
    generation: int | None = None


#: AD-1341: the schema this store writes. 0 is AD-524's, with no provenance.
ARCHIVE_SCHEMA_VERSION = 1

#: AD-1341 C1: the classifications the archive accepts. A later crew reads every entry (the Oracle's archive
#: tier has no reader filter), so nothing narrower than ``ship`` is ever archived.
PROMOTABLE_CLASSIFICATIONS = frozenset({"ship", "fleet"})

#: AD-1341: the longest reason an erasure or a skipped promotion records.
ARCHIVE_REASON_MAX_CHARS = 500


class SourceKind(StrEnum):
    """AD-1341: where a promoted entry came from.

    Closed, and with no episode member: episodes are memory, governed by AD-1340, and are never archived.
    """

    CONVERGENCE_REPORT = "convergence_report"
    PUBLISHED_REPORT = "published_report"
    CAPTAINS_LOG = "captains_log"
    NOTEBOOK_FINDING = "notebook_finding"
    EXIT_NOTE = "exit_note"  # AD-1341 S4: a lesson a crew agent leaves for its successor; it cites episodes, never is one


class PromotionOutcome(StrEnum):
    """AD-1341: what ``promote_entry`` did with one record."""

    CREATED = "created"
    PRESENT = "present"  # this source with this content is already archived
    ERASED = "erased"  # the Captain erased this source; it is not archived again
    VETOED = "vetoed"  # AD-1341 S3: the Captain vetoed this source before it was archived; it never is


class GenerationOutcome(StrEnum):
    """AD-1341: how a crew generation's close was handled at a reset of tier 2 or above."""

    PROMOTED = "promoted"
    SKIPPED = "skipped"


class VetoOutcome(StrEnum):
    """AD-1341 S3: what ``veto_source`` did with the Captain's veto of a source."""

    RECORDED = "recorded"
    ALREADY_VETOED = "already_vetoed"  # a veto of this source is recorded already; the first reason stands
    ARCHIVED = "archived"  # an entry from this source is archived: a veto does not remove it, erase_entry does
    ERASED = "erased"  # the Captain erased this source's entry, so it is already never promoted again


@dataclass(frozen=True)
class SourceState:
    """AD-1341 S3: what ``promote_entry`` would do with a record now, and the ids already archived from its source.

    ``outcome`` is CREATED when the record would be archived (new, or a revision of the entries in ``entry_ids``).
    Read with no lock: a veto, erasure or promotion after the read decides what ``promote_entry`` does. The review is
    not a reservation.
    """

    outcome: PromotionOutcome
    entry_ids: tuple[int, ...] = ()


def _required_text(value: object, name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"AD-1341: {name} must be a non-empty string")


@dataclass(frozen=True)
class PromotionRecord:
    """AD-1341: one entry to promote, with its provenance.

    Validated when built, so a record the archive must not hold (narrower than ``ship``, an unknown source
    kind, nothing to archive) never reaches the store.
    """

    timeline_id: str
    source_kind: SourceKind
    source_ref: str
    title: str
    content: str
    classification: str
    author_callsign: str = ""
    author_agent_type: str = ""
    author_did: str = ""
    source_episode_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.source_kind) is not SourceKind:
            raise ValueError("AD-1341: source_kind must be a SourceKind")
        for name in ("timeline_id", "source_ref", "title", "content"):
            _required_text(getattr(self, name), name)
        if type(self.classification) is not str or self.classification not in PROMOTABLE_CLASSIFICATIONS:
            raise ValueError(f"AD-1341: only {sorted(PROMOTABLE_CLASSIFICATIONS)} may be archived")
        for name in ("author_callsign", "author_agent_type", "author_did"):
            if type(getattr(self, name)) is not str:
                raise ValueError(f"AD-1341: {name} must be a string")
        if type(self.source_episode_ids) is not tuple or any(
            type(item) is not str or not item.strip() for item in self.source_episode_ids
        ):
            raise ValueError("AD-1341: source_episode_ids must be a tuple of episode ids")
        if type(self.metadata) is not dict:
            raise ValueError("AD-1341: metadata must be a dict")
        try:
            json.dumps(self.metadata)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"AD-1341: metadata must serialise to JSON: {exc}") from exc

    @property
    def content_sha256(self) -> str:
        """The SHA-256 of the content: part of the idempotence key."""
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GenerationRecord:
    """AD-1341: one crew generation's close at a reset of tier 2 or above, for ``generations``."""

    timeline_id: str
    reset_tier: int
    outcome: GenerationOutcome
    created: int = 0
    present: int = 0
    erased: int = 0
    withheld: int = 0
    reason: str = ""

    def __post_init__(self) -> None:
        if type(self.outcome) is not GenerationOutcome:
            raise ValueError("AD-1341: outcome must be a GenerationOutcome")
        if type(self.reset_tier) is not int or self.reset_tier not in (2, 3):
            raise ValueError("AD-1341: a generation closes at a reset of tier 2 or 3")
        if type(self.timeline_id) is not str or type(self.reason) is not str:
            raise ValueError("AD-1341: timeline_id and reason must be strings")
        if len(self.reason) > ARCHIVE_REASON_MAX_CHARS:
            raise ValueError(f"AD-1341: a reason is at most {ARCHIVE_REASON_MAX_CHARS} characters")
        for count in (self.created, self.present, self.erased, self.withheld):
            if type(count) is not int or count < 0:
                raise ValueError("AD-1341: counts are non-negative integers")
        if self.outcome is GenerationOutcome.PROMOTED and not self.timeline_id.strip():
            raise ValueError("AD-1341: a promotion is attributed to the timeline it closes")
        if self.outcome is GenerationOutcome.SKIPPED and not self.reason.strip():
            raise ValueError("AD-1341: a skipped promotion needs the Captain's reason")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeline_id TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    author_agent_type TEXT NOT NULL DEFAULT '',
    author_callsign TEXT NOT NULL DEFAULT '',
    archived_at REAL NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_archive_category ON archive(category);
CREATE INDEX IF NOT EXISTS idx_archive_timeline ON archive(timeline_id);

CREATE TABLE IF NOT EXISTS generations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeline_id TEXT NOT NULL,
    reset_tier INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    created_count INTEGER NOT NULL DEFAULT 0,
    present_count INTEGER NOT NULL DEFAULT 0,
    erased_count INTEGER NOT NULL DEFAULT 0,
    withheld_count INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    recorded_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_generations_timeline ON generations(timeline_id);

CREATE TABLE IF NOT EXISTS archive_erasures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    timeline_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    reason TEXT NOT NULL,
    erased_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_archive_erasures_source ON archive_erasures(source_kind, source_ref);

CREATE TABLE IF NOT EXISTS archive_vetoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeline_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    reason TEXT NOT NULL,
    vetoed_at REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_vetoes_source ON archive_vetoes(source_kind, source_ref);
"""

# AD-1341 schema v1: the provenance columns, each added to a v0 table only where absent, so a migration that
# stopped part-way finishes on the next open.
_V1_COLUMNS: tuple[tuple[str, str], ...] = (
    ("source_kind", "TEXT NOT NULL DEFAULT ''"),
    ("source_ref", "TEXT NOT NULL DEFAULT ''"),
    ("content_sha256", "TEXT"),
    ("classification", "TEXT NOT NULL DEFAULT ''"),
    ("author_did", "TEXT NOT NULL DEFAULT ''"),
    ("source_episode_ids", "TEXT NOT NULL DEFAULT '[]'"),
)

# AD-1341: the idempotence key. A source with the same content is archived once, whichever timeline promotes
# it: Ship's Records survive a tier 2 reset, so the next reset reads the same documents again.
_PROMOTION_KEY = "source_kind, source_ref, content_sha256"

# Partial: an AD-524 entry has no hash (NULL) and stays outside the key.
_PROMOTION_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_promotion_key "
    f"ON archive ({_PROMOTION_KEY}) WHERE content_sha256 IS NOT NULL"
)

_ENTRY_COLUMNS = (
    "id, timeline_id, category, title, content, author_agent_type, author_callsign, archived_at, metadata, "
    "source_kind, source_ref, content_sha256, classification, author_did, source_episode_ids"
)

# One statement, so neither an erasure nor (AD-1341 S3) a veto can land between a check and the insert.
_PROMOTE_SQL = (
    "INSERT INTO archive (timeline_id, category, title, content, author_agent_type, author_callsign, "
    "archived_at, metadata, source_kind, source_ref, content_sha256, classification, author_did, "
    "source_episode_ids) "
    "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? "
    "WHERE NOT EXISTS (SELECT 1 FROM archive_erasures WHERE source_kind = ? AND source_ref = ?) "
    "AND NOT EXISTS (SELECT 1 FROM archive_vetoes WHERE source_kind = ? AND source_ref = ?) "
    f"ON CONFLICT ({_PROMOTION_KEY}) WHERE content_sha256 IS NOT NULL DO NOTHING"
)

_ERASED_SOURCE_SQL = "SELECT 1 FROM archive_erasures WHERE source_kind = ? AND source_ref = ? LIMIT 1"

# AD-1341 S3 (D6): the Captain's veto, honoured by promote_entry and shown by source_state.
_VETOED_SOURCE_SQL = "SELECT 1 FROM archive_vetoes WHERE source_kind = ? AND source_ref = ? LIMIT 1"

_PRESENT_SQL = "SELECT 1 FROM archive WHERE source_kind = ? AND source_ref = ? AND content_sha256 = ? LIMIT 1"

_SOURCE_ENTRIES_SQL = "SELECT id FROM archive WHERE source_kind = ? AND source_ref = ? ORDER BY id"

# AD-1341 S3 (D5): one statement. A source already archived or erased is refused, and a second veto writes nothing.
_VETO_SQL = (
    "INSERT INTO archive_vetoes (timeline_id, source_kind, source_ref, reason, vetoed_at) "
    "SELECT ?, ?, ?, ?, ? "
    "WHERE NOT EXISTS (SELECT 1 FROM archive AS a WHERE a.source_kind = ? AND a.source_ref = ?) "
    "AND NOT EXISTS (SELECT 1 FROM archive_erasures AS e WHERE e.source_kind = ? AND e.source_ref = ?) "
    "ON CONFLICT (source_kind, source_ref) DO NOTHING"
)

# AD-1341 S3 (D9, D10): every entry whose citation cell is not the canonical '[]' (AD-524 rows and uncited entries hold
# it). SQL NULL and empty text are fetched, so that entry_ids_citing refuses them instead of skipping them.
_CITING_SQL = "SELECT id, source_episode_ids FROM archive WHERE source_episode_ids IS NOT '[]' ORDER BY id"

# The marker copies only the entry's id, timeline and source from the row it is about to delete.
_ERASURE_MARKER_SQL = (
    "INSERT INTO archive_erasures (entry_id, timeline_id, source_kind, source_ref, reason, erased_at) "
    "SELECT id, timeline_id, source_kind, source_ref, ?, ? FROM archive WHERE id = ?"
)

_GENERATION_SQL = (
    "INSERT INTO generations (timeline_id, reset_tier, outcome, created_count, present_count, erased_count, "
    "withheld_count, reason, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

# AD-1341 A2 (F2): SQLite's largest INTEGER, so its largest rowid. No row can have a larger id, and binding
# one raises OverflowError, so the lookup and the erasure treat it as a missing id.
_SQLITE_MAX_ROWID = 2**63 - 1

# AD-1341 S2 (D3): the generation order. A timeline's generation is its first close's place among the closes
# attributed to a timeline: a skip with no instance id numbers none, and a second close of one timeline does not
# renumber it. AUTOINCREMENT ids only grow, so the first close's id orders the crews. Which timelines are blank is
# decided in Python (``_generation_numbers``, A2): SQLite's one-argument ``trim`` strips spaces only.
_GENERATION_ORDER_SQL = (
    "SELECT timeline_id FROM generations "
    "GROUP BY timeline_id ORDER BY min(id)"
)

#: AD-1341 S2 (D4, D5): what an agent reads first about an entry its own crew archived.
LABEL_THIS_CREW = "[Archived by this crew: a record, not a memory]"

#: AD-1341 S2 (D4): what an agent reads first about an inherited entry whose crew generation is not recorded.
LABEL_EARLIER_CREW = "[Inherited from an earlier crew: not your own memory]"

#: AD-1341 S2 (A2, D12): what an agent reads before text in which a consumer may have cut or summarised away an
#: archive label: after AD-1148's elision marker, and at the head of an AD-547 compaction summary.
ARCHIVE_ORIGIN_NOTICE = (
    "[Ship's Archive: some text here may come from archived entries whose labels were cut or summarised away: "
    "archived knowledge, not your own memory]"
)

# AD-1341 S2 (A2): text that holds any of these holds Ship's Archive knowledge. Every inherited label opens with the
# first; the notice is here so that a second compaction keeps it.
_ARCHIVE_ORIGINS = ("[Inherited from ", LABEL_THIS_CREW, ARCHIVE_ORIGIN_NOTICE)


def holds_archive_label(text: str) -> bool:
    """AD-1341 S2 (A2, D12): whether ``text`` holds an inheritance label or ``ARCHIVE_ORIGIN_NOTICE``.

    A consumer that cuts a tool result's middle or summarises messages asks this of the text it cuts or summarises
    and, when it is true, puts ``ARCHIVE_ORIGIN_NOTICE`` before what it keeps. A false positive (a file that quotes a
    label) only adds the notice: the safe direction.
    """
    return any(origin in text for origin in _ARCHIVE_ORIGINS)


def inheritance_label(entry: ArchiveEntry, *, current_timeline: str) -> str:
    """AD-1341 S2 (#1569): the label an agent reads before an archived entry (D4).

    The Westworld Principle (agents know what they are) and the minority-report principle (inherited knowledge is
    never presented as an agent's own memory): every label says where the entry came from and that it is not the
    reader's memory. An entry of ``current_timeline`` (the reading crew's own instance id) was archived by this
    crew, whatever its generation (D5); any other entry is inherited, from the crew of its generation when one is
    recorded and from an earlier crew otherwise. An empty ``current_timeline`` matches nothing.
    """
    if current_timeline and entry.timeline_id == current_timeline:
        return LABEL_THIS_CREW
    if type(entry.generation) is int and entry.generation >= 1:
        return f"[Inherited from the crew of generation {entry.generation}: not your own memory]"
    return LABEL_EARLIER_CREW


def _valid_reason(reason: object) -> str:
    if type(reason) is not str or not reason.strip() or len(reason) > ARCHIVE_REASON_MAX_CHARS:
        raise ValueError(f"AD-1341: a reason of 1..{ARCHIVE_REASON_MAX_CHARS} characters is required")
    return reason.strip()


async def _rollback_quietly(db: Any) -> None:
    """Undo an uncommitted write so a later commit cannot land it (the AD-1213 pattern)."""
    try:
        await db.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- no open transaction is the common case
        logger.debug("AD-1341: rollback after a failed archive write found no open transaction")


async def _close_quietly(db: Any) -> None:
    """Close a connection whose open failed; the open's own failure is the one reported."""
    try:
        await db.close()
    except Exception:  # noqa: BLE001 -- see the docstring
        logger.debug("AD-1341: closing the archive after a failed open also failed", exc_info=True)


class ArchiveStore:
    """The Ship's Archive (AD-524), with AD-1341's provenance, promotion, and the Captain's veto and erasure.

    Agents and services never update or delete an entry: ``promote_entry`` is the one write of an entry and
    ``erase_entry`` the one removal (Captain-only, through ``probos archive erase``). ``veto_source`` (S3) records
    the Captain's veto of a source (Captain-only, through ``probos archive veto``); it writes no entry. Uses the
    ConnectionFactory protocol for cloud-ready storage.

    AD-1341 A2 (F1): one connection serves every call, and a ROLLBACK or COMMIT ends whatever that connection
    has open. So the four writes and ``close`` hold ``_write_lock`` from their first statement through the
    commit or rollback that ends it, and no call can undo, or land, another call's work (AD-1340 R3's pattern,
    ``episode_archive.py``). Reads and ``initialize`` take no lock: a read issues no commit or rollback, and it
    sees the connection's state, a write in flight included. No method holding the lock calls another store
    method (the lock is not re-entrant).
    """

    def __init__(self, db_path: str, *, connection_factory: ConnectionFactory) -> None:
        self._db_path = db_path
        self._connection_factory = connection_factory
        self._db: Any = None
        self._write_lock = asyncio.Lock()  # AD-1341 A2 (F1): one transaction at a time on the one connection

    async def initialize(self) -> None:
        """Open the database, enable and verify ``secure_delete``, and bring the schema to v1 (AD-1341).

        Additive and idempotent: a v0 archive keeps every row and gains the provenance columns, the partial
        unique index, ``generations`` and ``archive_erasures``. Each column is added only where absent, so a
        migration that stopped part-way finishes here, and ``user_version`` is written last. A file of any
        other schema version is refused, unopened.
        """
        if self._db is not None:
            return
        db = await self._connection_factory.connect(self._db_path)
        try:
            await db.execute("PRAGMA secure_delete=ON")
            cursor = await db.execute("PRAGMA secure_delete")
            row = await cursor.fetchone()
            if not row or int(row[0]) != 1:
                raise RuntimeError("AD-1341: secure_delete is unavailable, so an erasure could not be honoured")
            cursor = await db.execute("PRAGMA user_version")
            row = await cursor.fetchone()
            version = int(row[0]) if row else 0
            if version not in (0, ARCHIVE_SCHEMA_VERSION):
                raise RuntimeError(
                    f"AD-1341: archive schema version {version} is not one this ProbOS reads "
                    f"(0 or {ARCHIVE_SCHEMA_VERSION}); refusing to open it"
                )
            await db.executescript(_SCHEMA)
            cursor = await db.execute("PRAGMA table_info(archive)")
            present = {column[1] for column in await cursor.fetchall()}
            for name, declaration in _V1_COLUMNS:
                if name not in present:
                    await db.execute(f"ALTER TABLE archive ADD COLUMN {name} {declaration}")
            await db.execute(_PROMOTION_INDEX)
            await db.execute(f"PRAGMA user_version = {ARCHIVE_SCHEMA_VERSION}")
            await db.commit()
        except BaseException:  # close on every exit, cancellation included, then re-raise
            await _close_quietly(db)
            raise
        self._db = db
        logger.info("AD-524: ArchiveStore initialized at %s (schema v%d)", self._db_path, ARCHIVE_SCHEMA_VERSION)

    async def close(self) -> None:
        """Close the connection once no write is in flight (AD-1341 A2, F1). A failed close keeps ``_db``."""
        async with self._write_lock:  # AD-1341 F1: never close inside another call's transaction
            if self._db:
                await self._db.close()
                self._db = None

    async def promote_entry(self, record: PromotionRecord) -> PromotionOutcome:
        """AD-1341: the archive's one write, called only by ``probos.knowledge.archive_promotion``.

        Idempotent on ``(source_kind, source_ref, content_sha256)``: the same source with the same content is
        archived once, whichever timeline promotes it (PRESENT). A source the Captain erased is not written
        again, with any content (ERASED); the check and the insert are one statement. Any database failure
        rolls the transaction back and propagates: the caller decides what a failed promotion means.
        """
        if type(record) is not PromotionRecord:
            raise TypeError("AD-1341: promote_entry takes a PromotionRecord")
        kind = record.source_kind.value
        params = (
            record.timeline_id, kind, record.title, record.content, record.author_agent_type,
            record.author_callsign, time.time(), json.dumps(record.metadata), kind, record.source_ref,
            record.content_sha256, record.classification, record.author_did,
            json.dumps(list(record.source_episode_ids)), kind, record.source_ref,
            kind, record.source_ref,  # AD-1341 S3: the veto check
        )
        async with self._write_lock:  # AD-1341 F1: the insert and its erasure check commit or roll back alone
            if not self._db:
                raise RuntimeError("ArchiveStore not initialized")
            try:
                cursor = await self._db.execute(_PROMOTE_SQL, params)
                created = cursor.rowcount == 1
                erased = vetoed = False
                if not created:  # AD-1341 S3 (D6): erased, then vetoed, then present; source_state reads the same
                    cursor = await self._db.execute(_ERASED_SOURCE_SQL, (kind, record.source_ref))
                    erased = await cursor.fetchone() is not None
                    cursor = await self._db.execute(_VETOED_SOURCE_SQL, (kind, record.source_ref))
                    vetoed = await cursor.fetchone() is not None
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        if created:
            return PromotionOutcome.CREATED
        if erased:
            return PromotionOutcome.ERASED
        return PromotionOutcome.VETOED if vetoed else PromotionOutcome.PRESENT

    async def record_generation(self, closure: GenerationRecord) -> int:
        """AD-1341: record a crew generation's close (a promotion run, or a skip and its reason). Returns its id."""
        if type(closure) is not GenerationRecord:
            raise TypeError("AD-1341: record_generation takes a GenerationRecord")
        params = (
            closure.timeline_id, closure.reset_tier, closure.outcome.value, closure.created, closure.present,
            closure.erased, closure.withheld, closure.reason.strip(), time.time(),
        )
        async with self._write_lock:  # AD-1341 F1: the generation row commits or rolls back alone
            if not self._db:
                raise RuntimeError("ArchiveStore not initialized")
            try:
                cursor = await self._db.execute(_GENERATION_SQL, params)
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        return cursor.lastrowid

    async def erase_entry(self, entry_id: int, reason: str) -> bool:
        """AD-1341: the Captain's erasure (AD-754 extended to the archive), reached only from ``probos archive erase``.

        One transaction: a marker in ``archive_erasures`` (the entry's id, timeline, source kind and source ref,
        the reason and the time; never its title, content, metadata or hash), then the row's delete.
        ``secure_delete`` overwrites the freed bytes. The marker also keeps the source from being promoted
        again. Returns False, writing nothing, when no entry has this id, including an id above SQLite's largest
        rowid (A2, F2). The marker, the delete and the commit or rollback hold ``_write_lock`` (A2, F1).
        """
        if type(entry_id) is not int or entry_id <= 0:
            raise ValueError("AD-1341: an archive entry id is a positive integer")
        text = _valid_reason(reason)
        async with self._write_lock:  # AD-1341 F1: the marker and the delete commit or roll back alone
            if not self._db:
                raise RuntimeError("ArchiveStore not initialized")
            if entry_id > _SQLITE_MAX_ROWID:  # AD-1341 F2: no row has it, and SQLite cannot bind it
                return False
            try:
                cursor = await self._db.execute(_ERASURE_MARKER_SQL, (text, time.time(), entry_id))
                if cursor.rowcount != 1:
                    await _rollback_quietly(self._db)
                    return False
                await self._db.execute("DELETE FROM archive WHERE id = ?", (entry_id,))
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        logger.warning("AD-1341: the Captain erased Ship's Archive entry %d", entry_id)
        return True

    async def veto_source(
        self, source_kind: SourceKind, source_ref: str, reason: str, *, timeline_id: str = "",
    ) -> VetoOutcome:
        """AD-1341 S3: the Captain's veto of a source before it is archived, reached only from ``probos archive veto``.

        One statement (``_VETO_SQL``) writes a row in ``archive_vetoes``: the source kind and ref, the Captain's
        reason, the timeline it was vetoed in and the time; never a title, content, metadata or hash.
        ``promote_entry`` then refuses the source with any content (VETOED). Nothing is written for a source an entry
        is archived from (ARCHIVED: a veto does not remove an entry, ``erase_entry`` does), for a source the Captain
        erased (ERASED: it is never promoted again already), or for a second veto (ALREADY_VETOED: the first reason
        stands). Holds ``_write_lock`` through the commit or rollback (S1 D16).
        """
        if type(source_kind) is not SourceKind:
            raise ValueError("AD-1341: source_kind must be a SourceKind")
        _required_text(source_ref, "source_ref")
        text = _valid_reason(reason)
        if type(timeline_id) is not str:
            raise ValueError("AD-1341: timeline_id must be a string")
        kind = source_kind.value
        params = (timeline_id.strip(), kind, source_ref, text, time.time(), kind, source_ref, kind, source_ref)
        async with self._write_lock:  # AD-1341 S3: the veto and its checks commit or roll back alone (D16)
            if not self._db:
                raise RuntimeError("ArchiveStore not initialized")
            try:
                cursor = await self._db.execute(_VETO_SQL, params)
                recorded = cursor.rowcount == 1
                archived = was_erased = False
                if not recorded:
                    cursor = await self._db.execute(_SOURCE_ENTRIES_SQL, (kind, source_ref))
                    archived = await cursor.fetchone() is not None
                    cursor = await self._db.execute(_ERASED_SOURCE_SQL, (kind, source_ref))
                    was_erased = await cursor.fetchone() is not None
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)  # AD-1341 S3: nothing is left open for the next write
                raise
        if recorded:
            logger.warning("AD-1341 S3: the Captain vetoed a %s source's promotion into the Ship's Archive", kind)
            return VetoOutcome.RECORDED
        if archived:
            return VetoOutcome.ARCHIVED
        return VetoOutcome.ERASED if was_erased else VetoOutcome.ALREADY_VETOED

    async def source_state(self, record: PromotionRecord) -> SourceState:
        """AD-1341 S3: what ``promote_entry`` would do with ``record`` now, and the ids archived from its source.

        The same checks in the same order as ``promote_entry`` (an erasure, then a veto, then this content already
        archived), CREATED when none holds (D6). A read: no lock and no commit (S1 D16), so a later write decides.
        """
        if type(record) is not PromotionRecord:
            raise TypeError("AD-1341: source_state takes a PromotionRecord")
        if not self._db:
            raise RuntimeError("ArchiveStore not initialized")
        kind, ref = record.source_kind.value, record.source_ref
        cursor = await self._db.execute(_SOURCE_ENTRIES_SQL, (kind, ref))
        entry_ids = tuple(row[0] for row in await cursor.fetchall())
        cursor = await self._db.execute(_ERASED_SOURCE_SQL, (kind, ref))
        if await cursor.fetchone() is not None:
            return SourceState(PromotionOutcome.ERASED, entry_ids)
        cursor = await self._db.execute(_VETOED_SOURCE_SQL, (kind, ref))
        if await cursor.fetchone() is not None:
            return SourceState(PromotionOutcome.VETOED, entry_ids)
        cursor = await self._db.execute(_PRESENT_SQL, (kind, ref, record.content_sha256))
        present = await cursor.fetchone() is not None
        return SourceState(PromotionOutcome.PRESENT if present else PromotionOutcome.CREATED, entry_ids)

    async def entry_ids_citing(self, episode_ids: list[str] | tuple[str, ...]) -> tuple[int, ...]:
        """AD-1341 S3: the ids of the entries whose ``source_episode_ids`` name any of ``episode_ids``, ascending.

        The AD-754 erasure manager's check (``knowledge/erasure.py``): an episode an entry cites is not erased until
        the Captain has erased the entry (D8). Blank ids match nothing. A read, with no lock (S1 D16). It raises when
        the store is not open, and ``ValueError`` when any citation cell is not a JSON list of strings (malformed
        JSON, an object, a string, a number, ``null``, a list holding a non-string, empty text or SQL NULL): it never
        answers "none" then, because an erasure that cannot check must not go on as if nothing cited the episode (D10).
        One statement per call; ``_CITING_SQL`` skips only the canonical ``'[]'``.
        """
        if type(episode_ids) not in (list, tuple) or any(type(item) is not str for item in episode_ids):
            raise TypeError("AD-1341: entry_ids_citing takes a list or tuple of episode ids")
        if not self._db:
            raise RuntimeError("AD-1341 S3: the Ship's Archive is not open, so its citations cannot be read")
        wanted = {item for item in episode_ids if item}
        if not wanted:
            return ()
        cursor = await self._db.execute(_CITING_SQL)
        citing: list[int] = []
        for entry_id, cell in await cursor.fetchall():
            cited = json.loads(cell) if type(cell) is str else None  # SQL NULL, or a blob, is no citation list (D10)
            if type(cited) is not list or any(type(item) is not str for item in cited):
                raise ValueError(f"AD-1341 S3: Ship's Archive entry {entry_id}'s citation list cannot be read")
            if wanted.intersection(cited):
                citing.append(entry_id)
        return tuple(citing)

    async def entry_by_id(self, entry_id: int) -> ArchiveEntry | None:
        """AD-1341: one entry, so the erasure can show the Captain what it is about to remove.

        None for an id no row can have: below 1, or above SQLite's largest rowid, which cannot be bound (A2, F2).
        """
        if not self._db or not 0 < entry_id <= _SQLITE_MAX_ROWID:  # AD-1341 F2: ids are positive rowids
            return None
        cursor = await self._db.execute(f"SELECT {_ENTRY_COLUMNS} FROM archive WHERE id = ?", (entry_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_entry(row, await self._generation_numbers())

    async def search(
        self,
        query: str,
        *,
        category: str = "",
        limit: int = 10,
    ) -> list[ArchiveEntry]:
        """Search archive entries by keyword match on title and content.

        Simple LIKE-based search. Future: full-text search or vector embeddings.
        """
        if not self._db:
            return []

        _escaped = query.replace("%", "\\%").replace("_", "\\_")
        conditions = ["(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')"]
        params: list[Any] = [f"%{_escaped}%", f"%{_escaped}%"]

        if category:
            conditions.append("category = ?")
            params.append(category)

        sql = f"""SELECT {_ENTRY_COLUMNS}
                  FROM archive
                  WHERE {' AND '.join(conditions)}
                  ORDER BY archived_at DESC
                  LIMIT ?"""
        params.append(limit)

        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        generations = await self._generation_numbers()  # AD-1341 S2

        return [self._row_to_entry(row, generations) for row in rows]

    async def get_recent(self, limit: int = 20) -> list[ArchiveEntry]:
        """Get the most recent archive entries (no filter)."""
        if not self._db:
            return []

        cursor = await self._db.execute(
            f"SELECT {_ENTRY_COLUMNS} FROM archive ORDER BY archived_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        generations = await self._generation_numbers()  # AD-1341 S2
        return [self._row_to_entry(row, generations) for row in rows]

    async def count(self) -> int:
        """Return total number of archive entries."""
        if not self._db:
            return 0
        cursor = await self._db.execute("SELECT COUNT(*) FROM archive")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def _generation_numbers(self) -> dict[str, int]:
        """AD-1341 S2: each timeline's generation, from ``generations`` (D3). A read, so it takes no lock (D16)."""
        cursor = await self._db.execute(_GENERATION_ORDER_SQL)
        rows = await cursor.fetchall()
        # A close whose timeline is blank by ``str.strip`` names no crew, so it numbers none (A2: SQLite's ``trim``
        # strips spaces only, so the filter is here, not in the SQL).
        crews = [row[0] for row in rows if row[0].strip()]
        return {timeline: number for number, timeline in enumerate(crews, start=1)}

    @staticmethod
    def _row_to_entry(row: Any, generations: dict[str, int]) -> ArchiveEntry:
        return ArchiveEntry(
            id=row[0],
            timeline_id=row[1],
            category=row[2],
            title=row[3],
            content=row[4],
            author_agent_type=row[5],
            author_callsign=row[6],
            archived_at=row[7],
            metadata=json.loads(row[8]) if row[8] else {},
            source_kind=row[9],
            source_ref=row[10],
            content_sha256=row[11] or "",
            classification=row[12],
            author_did=row[13],
            source_episode_ids=tuple(json.loads(row[14])) if row[14] else (),
            generation=generations.get(row[1]),
        )
