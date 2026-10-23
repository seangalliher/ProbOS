"""Ship's Archive — cross-reset generational knowledge persistence (AD-524, AD-1341).

Stores curated knowledge entries that survive resets. Agents and services never
update or delete an entry. The one write is ``ArchiveStore.promote_entry``
(AD-1341), called only by the promotion service
(``probos.knowledge.archive_promotion``); it is idempotent on the source and its
content. The one removal is the Captain's ``erase_entry``, reached only from the
offline ``probos archive erase``: it deletes the row and leaves a marker in
``archive_erasures`` that holds no title, content or hash.

Each entry records the timeline (instance) it came from, its source kind and
reference, the content's SHA-256, its classification (``ship`` or ``fleet``: a
later crew reads every entry) and when it was archived. ``generations`` records
each crew generation's close at a reset of tier 2 or above, including a
promotion the Captain skipped and why.

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


class PromotionOutcome(StrEnum):
    """AD-1341: what ``promote_entry`` did with one record."""

    CREATED = "created"
    PRESENT = "present"  # this source with this content is already archived
    ERASED = "erased"  # the Captain erased this source; it is not archived again


class GenerationOutcome(StrEnum):
    """AD-1341: how a crew generation's close was handled at a reset of tier 2 or above."""

    PROMOTED = "promoted"
    SKIPPED = "skipped"


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

# One statement, so an erasure can never land between a check and the insert.
_PROMOTE_SQL = (
    "INSERT INTO archive (timeline_id, category, title, content, author_agent_type, author_callsign, "
    "archived_at, metadata, source_kind, source_ref, content_sha256, classification, author_did, "
    "source_episode_ids) "
    "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? "
    "WHERE NOT EXISTS (SELECT 1 FROM archive_erasures WHERE source_kind = ? AND source_ref = ?) "
    f"ON CONFLICT ({_PROMOTION_KEY}) WHERE content_sha256 IS NOT NULL DO NOTHING"
)

_ERASED_SOURCE_SQL = "SELECT 1 FROM archive_erasures WHERE source_kind = ? AND source_ref = ? LIMIT 1"

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
    """The Ship's Archive (AD-524), with AD-1341's provenance, promotion and the Captain's erasure.

    Agents and services never update or delete an entry: ``promote_entry`` is the one write and
    ``erase_entry`` the one removal (Captain-only, through ``probos archive erase``). Uses the
    ConnectionFactory protocol for cloud-ready storage.

    AD-1341 A2 (F1): one connection serves every call, and a ROLLBACK or COMMIT ends whatever that connection
    has open. So the three writes and ``close`` hold ``_write_lock`` from their first statement through the
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
        )
        async with self._write_lock:  # AD-1341 F1: the insert and its erasure check commit or roll back alone
            if not self._db:
                raise RuntimeError("ArchiveStore not initialized")
            try:
                cursor = await self._db.execute(_PROMOTE_SQL, params)
                created = cursor.rowcount == 1
                erased = False
                if not created:
                    cursor = await self._db.execute(_ERASED_SOURCE_SQL, (kind, record.source_ref))
                    erased = await cursor.fetchone() is not None
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        if created:
            return PromotionOutcome.CREATED
        return PromotionOutcome.ERASED if erased else PromotionOutcome.PRESENT

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

    async def entry_by_id(self, entry_id: int) -> ArchiveEntry | None:
        """AD-1341: one entry, so the erasure can show the Captain what it is about to remove.

        None for an id no row can have: below 1, or above SQLite's largest rowid, which cannot be bound (A2, F2).
        """
        if not self._db or not 0 < entry_id <= _SQLITE_MAX_ROWID:  # AD-1341 F2: ids are positive rowids
            return None
        cursor = await self._db.execute(f"SELECT {_ENTRY_COLUMNS} FROM archive WHERE id = ?", (entry_id,))
        row = await cursor.fetchone()
        return self._row_to_entry(row) if row else None

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

        return [self._row_to_entry(row) for row in rows]

    async def get_recent(self, limit: int = 20) -> list[ArchiveEntry]:
        """Get the most recent archive entries (no filter)."""
        if not self._db:
            return []

        cursor = await self._db.execute(
            f"SELECT {_ENTRY_COLUMNS} FROM archive ORDER BY archived_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_entry(row) for row in rows]

    async def count(self) -> int:
        """Return total number of archive entries."""
        if not self._db:
            return 0
        cursor = await self._db.execute("SELECT COUNT(*) FROM archive")
        row = await cursor.fetchone()
        return row[0] if row else 0

    @staticmethod
    def _row_to_entry(row: Any) -> ArchiveEntry:
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
        )
