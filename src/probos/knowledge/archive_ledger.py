"""AD-1341 S6 (#1569): the reset's ledger in the Ship's Archive's file: the Ship's Records snapshots a ``--full``
reset kept.

``archive_snapshots`` holds no content: each snapshot's timeline, ship DID, generation dates, file name, the file's
SHA-256, its file count and size (``probos.knowledge.records_snapshot`` writes the file beside the archive).
``nature_clearances`` (M3) holds no content either: each ``--clean-slate``, its timeline and tier, what it cleared and
how many procedures the store held, recorded before anything is deleted (``record_nature_clearance``, reached only
from ``probos reset``).
``ArchiveStore`` owns the schema and its version (``archive_store._SCHEMA``). The ledger opens the same file on a
connection of its own, and only once the store has brought it to that version, so a ledger write never shares a
transaction with an entry's (S1 D16). It is its own class because ``ArchiveStore`` is at the repository's SRP method
trigger (``scripts/check_architecture_principles.py``).

- Only the offline CLI writes here: ``record_snapshot`` from ``probos reset``, ``mark_snapshot_erased`` from the
  Captain's ``probos archive erase-snapshot`` (``tests/test_ad1341_s6_records_snapshot.py`` holds that with a census).
- A snapshot's row is never deleted. The Captain's erasure marks it, with the reason and the time, before the file is
  deleted, so no snapshot is removed unrecorded; a second erasure keeps the first reason.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from probos.knowledge.archive_store import ARCHIVE_REASON_MAX_CHARS, ARCHIVE_SCHEMA_VERSION
from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

#: SQLite's largest rowid: no row has a larger id, and binding one raises (S1 A2, F2).
_SQLITE_MAX_ROWID = 2**63 - 1
_HEX_DIGITS = frozenset("0123456789abcdef")

_SNAPSHOT_COLUMNS = (
    "id, timeline_id, ship_did, generation_started, generation_ended, relative_path, sha256, file_count, "
    "total_bytes, recorded_at, erased_at, erase_reason"
)
_SNAPSHOT_SQL = (
    "INSERT INTO archive_snapshots (timeline_id, ship_did, generation_started, generation_ended, relative_path, "
    "sha256, file_count, total_bytes, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_SNAPSHOTS_SQL = f"SELECT {_SNAPSHOT_COLUMNS} FROM archive_snapshots ORDER BY id"
_SNAPSHOT_BY_ID_SQL = f"SELECT {_SNAPSHOT_COLUMNS} FROM archive_snapshots WHERE id = ?"
# The Captain's erasure marks the row once; a second erasure keeps the first reason and time.
_SNAPSHOT_ERASE_SQL = (
    "UPDATE archive_snapshots SET erased_at = ?, erase_reason = ? WHERE id = ? AND erased_at IS NULL"
)
_NATURE_CLEARANCE_SQL = (
    "INSERT INTO nature_clearances (timeline_id, reset_tier, cleared, procedure_count, cleared_at) "
    "VALUES (?, ?, ?, ?, ?)"
)


def _required_text(value: object, name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"AD-1341 S6: {name} must be a non-empty string")


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _HEX_DIGITS


def _valid_reason(reason: object) -> str:
    """The Captain's reason, at the archive's bound (``ARCHIVE_REASON_MAX_CHARS``), stripped."""
    if type(reason) is not str or not reason.strip() or len(reason) > ARCHIVE_REASON_MAX_CHARS:
        raise ValueError(f"AD-1341 S6: a reason of 1..{ARCHIVE_REASON_MAX_CHARS} characters is required")
    return reason.strip()


@dataclass(frozen=True)
class SnapshotRecord:
    """AD-1341 S6: one Ship's Records snapshot a ``--full`` reset kept, for ``archive_snapshots``. Holds no content."""

    timeline_id: str
    ship_did: str
    generation_started: str
    generation_ended: str
    relative_path: str
    sha256: str
    file_count: int
    total_bytes: int

    def __post_init__(self) -> None:
        for name in ("timeline_id", "ship_did", "generation_started", "generation_ended", "relative_path"):
            _required_text(getattr(self, name), name)
        if not _is_sha256(self.sha256):
            raise ValueError("AD-1341 S6: sha256 is 64 lower-case hexadecimal digits")
        for count in (self.file_count, self.total_bytes):
            if type(count) is not int or count < 0:
                raise ValueError("AD-1341 S6: counts are non-negative integers")


@dataclass(frozen=True)
class SnapshotEntry:
    """AD-1341 S6: a row of ``archive_snapshots``. ``erased_at`` is set once the Captain erased the snapshot."""

    id: int
    timeline_id: str
    ship_did: str
    generation_started: str
    generation_ended: str
    relative_path: str
    sha256: str
    file_count: int
    total_bytes: int
    recorded_at: float
    erased_at: float | None = None
    erase_reason: str = ""


@dataclass(frozen=True)
class NatureClearanceRecord:
    """AD-1341 S6: the Captain's clean slate at a reset, for ``nature_clearances``: what is cleared, never content."""

    timeline_id: str
    reset_tier: int
    cleared: tuple[str, ...]
    procedure_count: int

    def __post_init__(self) -> None:
        if type(self.timeline_id) is not str:
            raise ValueError("AD-1341 S6: timeline_id is a string (empty when the ship has no instance id)")
        if type(self.reset_tier) is not int or self.reset_tier not in (2, 3):  # AD-1341 S6: tier 1 keeps the crew
            raise ValueError("AD-1341 S6: a clean slate is part of a reset of tier 2 or 3")
        if type(self.cleared) is not tuple or any(type(item) is not str or not item.strip() for item in self.cleared):
            raise ValueError("AD-1341 S6: cleared is a tuple of data-directory names")
        if type(self.procedure_count) is not int or self.procedure_count < -1:
            raise ValueError("AD-1341 S6: procedure_count is a count, or -1 when the store could not be counted")


def _row_to_snapshot(row: Any) -> SnapshotEntry:
    return SnapshotEntry(
        id=row[0], timeline_id=row[1], ship_did=row[2], generation_started=row[3], generation_ended=row[4],
        relative_path=row[5], sha256=row[6], file_count=row[7], total_bytes=row[8], recorded_at=row[9],
        erased_at=row[10], erase_reason=row[11] or "",
    )


async def _rollback_quietly(db: Any) -> None:
    """Undo an uncommitted write so a later commit cannot land it (``archive_store``'s rule, on this connection)."""
    try:
        await db.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- no open transaction is the common case
        logger.debug("AD-1341 S6: rollback after a failed ledger write found no open transaction")


class ArchiveLedger:
    """AD-1341 S6: the reset's rows in the Ship's Archive's file, on a connection of their own.

    ``initialize`` refuses a file ``ArchiveStore`` has not brought to ``ARCHIVE_SCHEMA_VERSION``: the store owns the
    schema, and its ``initialize`` creates these tables. Each write holds ``_write_lock`` from its first statement to
    its commit or rollback (S1 D16); reads take no lock. Uses the ConnectionFactory protocol.
    """

    def __init__(self, db_path: str, *, connection_factory: ConnectionFactory) -> None:
        self._db_path = db_path
        self._connection_factory = connection_factory
        self._db: Any = None
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Open the archive's file once ``ArchiveStore.initialize`` has brought it to its schema; refuse otherwise."""
        if self._db is not None:
            return
        db = await self._connection_factory.connect(self._db_path)
        try:
            await db.execute("PRAGMA secure_delete=ON")  # as every connection to the archive's file does (S1)
            cursor = await db.execute("PRAGMA user_version")
            row = await cursor.fetchone()
            version = int(row[0]) if row else 0
            if version != ARCHIVE_SCHEMA_VERSION:
                raise RuntimeError(
                    f"AD-1341 S6: the Ship's Archive is at schema version {version}; ArchiveStore.initialize brings "
                    f"it to {ARCHIVE_SCHEMA_VERSION} before the ledger opens it"
                )
        except BaseException:
            try:
                await db.close()
            except Exception:  # noqa: BLE001 -- the open's own failure is the one reported
                logger.debug("AD-1341 S6: closing the ledger after a failed open also failed", exc_info=True)
            raise
        self._db = db

    async def close(self) -> None:
        """Close the connection once no write is in flight."""
        async with self._write_lock:
            if self._db:
                await self._db.close()
                self._db = None

    async def record_snapshot(self, snapshot: SnapshotRecord) -> int:
        """Record a snapshot a ``--full`` reset kept; reached only from ``probos reset``. Returns the row's id.

        A second row for one file name raises (a unique index).
        """
        if type(snapshot) is not SnapshotRecord:
            raise TypeError("AD-1341 S6: record_snapshot takes a SnapshotRecord")
        params = (
            snapshot.timeline_id, snapshot.ship_did, snapshot.generation_started, snapshot.generation_ended,
            snapshot.relative_path, snapshot.sha256, snapshot.file_count, snapshot.total_bytes, time.time(),
        )
        async with self._write_lock:  # S1 D16: the row commits or rolls back alone
            if not self._db:
                raise RuntimeError("ArchiveLedger not initialized")
            try:
                cursor = await self._db.execute(_SNAPSHOT_SQL, params)
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        return cursor.lastrowid

    async def snapshot_entries(self) -> tuple[SnapshotEntry, ...]:
        """Every recorded snapshot, erased ones included, in the order they were recorded. A read."""
        if not self._db:
            raise RuntimeError("ArchiveLedger not initialized")
        cursor = await self._db.execute(_SNAPSHOTS_SQL)
        return tuple(_row_to_snapshot(row) for row in await cursor.fetchall())

    async def snapshot_by_id(self, snapshot_id: int) -> SnapshotEntry | None:
        """One recorded snapshot, or None (an id that no row can have included). A read."""
        if not self._db:
            raise RuntimeError("ArchiveLedger not initialized")
        if type(snapshot_id) is not int or snapshot_id <= 0 or snapshot_id > _SQLITE_MAX_ROWID:
            return None
        cursor = await self._db.execute(_SNAPSHOT_BY_ID_SQL, (snapshot_id,))
        row = await cursor.fetchone()
        return None if row is None else _row_to_snapshot(row)

    async def mark_snapshot_erased(self, snapshot_id: int, reason: str) -> SnapshotEntry | None:
        """The Captain's erasure of a snapshot, reached only from ``probos archive erase-snapshot``.

        Marks the row with the reason and the time before the caller deletes the file. A row already marked keeps its
        first reason. Returns the row as it now stands, or None, writing nothing, when no snapshot has this id.
        """
        if type(snapshot_id) is not int or snapshot_id <= 0:
            raise ValueError("AD-1341 S6: a snapshot id is a positive integer")
        text = _valid_reason(reason)
        async with self._write_lock:  # S1 D16: the mark and its read commit or roll back alone
            if not self._db:
                raise RuntimeError("ArchiveLedger not initialized")
            if snapshot_id > _SQLITE_MAX_ROWID:
                return None
            try:
                await self._db.execute(_SNAPSHOT_ERASE_SQL, (time.time(), text, snapshot_id))
                cursor = await self._db.execute(_SNAPSHOT_BY_ID_SQL, (snapshot_id,))
                row = await cursor.fetchone()
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        if row is None:
            return None
        logger.warning("AD-1341 S6: the Captain erased Ship's Records snapshot %d", snapshot_id)
        return _row_to_snapshot(row)

    async def record_nature_clearance(self, clearance: NatureClearanceRecord) -> int:
        """Record the Captain's clean slate before it deletes nature; reached only from ``probos reset``."""
        if type(clearance) is not NatureClearanceRecord:
            raise TypeError("AD-1341 S6: record_nature_clearance takes a NatureClearanceRecord")
        params = (
            clearance.timeline_id.strip(), clearance.reset_tier, json.dumps(list(clearance.cleared)),
            clearance.procedure_count, time.time(),
        )
        async with self._write_lock:  # S1 D16: the marker commits or rolls back alone
            if not self._db:
                raise RuntimeError("ArchiveLedger not initialized")
            try:
                cursor = await self._db.execute(_NATURE_CLEARANCE_SQL, params)
                await self._db.commit()
            except BaseException:
                await _rollback_quietly(self._db)
                raise
        logger.warning("AD-1341 S6: the Captain's clean slate is recorded (tier %d)", clearance.reset_tier)
        return cursor.lastrowid
