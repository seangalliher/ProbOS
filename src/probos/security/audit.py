"""AD-456: AuditLog -- append-only hash-chained record.

v1 in-memory only. Each entry includes the SHA-256 of the prior entry
(hash chain). Tamper detection via ``verify_chain()``. Persistence to SQLite
deferred to AD-456d.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditEntry:
    """One hash-chained audit record."""

    sequence: int
    timestamp: float
    category: str
    detail: str
    prior_hash: str
    entry_hash: str


@dataclass
class AuditLog:
    """In-memory hash-chained log.

    Append-only. Each entry's hash includes the prior entry's hash so any
    tampering breaks the chain. ``verify_chain()`` re-derives every hash and
    confirms continuity.

    AD-456d: Optional ``_persistence`` field accepts an ``AuditLogPersistence``
    instance via ``attach_persistence(...)``. When attached AND a running
    asyncio loop is present at ``append()`` time, each new entry is also
    scheduled for SQLite persistence as a fire-and-forget task tracked in
    ``_pending_writes``. Sync ``append()`` return path is unchanged — the
    in-memory chain remains the source of truth at runtime.
    """

    entries: list[AuditEntry] = field(default_factory=list)
    emit_event: Any | None = None
    # AD-456d: optional persistence seam. Defaults None preserve AD-456
    # in-memory-only contract. Set via ``attach_persistence(...)``.
    _persistence: "AuditLogPersistence | None" = None
    # AD-456d: in-flight persist task references (copilot-instructions Async
    # Discipline rule — fire-and-forget tasks must hold a reference or they
    # may be garbage-collected before completion). Each task adds itself
    # via ``set.add(task)`` and registers ``task.add_done_callback(set.discard)``.
    _pending_writes: set["asyncio.Task[Any]"] = field(default_factory=set)

    GENESIS_HASH: str = "0" * 64

    def append(self, *, category: str, detail: str) -> AuditEntry:
        prior_hash = self.entries[-1].entry_hash if self.entries else self.GENESIS_HASH
        sequence = len(self.entries)
        ts = time.time()
        payload = {
            "sequence": sequence,
            "timestamp": ts,
            "category": category,
            "detail": detail,
            "prior_hash": prior_hash,
        }
        entry_hash = self._hash(payload)
        entry = AuditEntry(
            sequence=sequence,
            timestamp=ts,
            category=category,
            detail=detail,
            prior_hash=prior_hash,
            entry_hash=entry_hash,
        )
        self.entries.append(entry)
        if self.emit_event is not None:
            try:
                self.emit_event(
                    EventType.AUDIT_RECORDED,
                    {
                        "sequence": sequence,
                        "category": category,
                        "entry_hash": entry_hash,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-456: AUDIT_RECORDED emit failed (sequence=%d, category=%s)",
                    sequence, category, exc_info=True,
                )
        # AD-456d: fire-and-forget persist hook. No-op when persistence is
        # not attached OR no asyncio loop is running (sync test paths).
        if self._persistence is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.debug(
                    "AD-456d: AuditLog.append called without running loop "
                    "(sequence=%d); persistence skipped",
                    sequence,
                )
            else:
                task = loop.create_task(self._persistence.persist_entry(entry))
                self._pending_writes.add(task)
                task.add_done_callback(self._pending_writes.discard)
        return entry

    def verify_chain(self) -> bool:
        """Re-derive every entry hash; return True if chain is intact."""
        prior = self.GENESIS_HASH
        for entry in self.entries:
            payload = {
                "sequence": entry.sequence,
                "timestamp": entry.timestamp,
                "category": entry.category,
                "detail": entry.detail,
                "prior_hash": entry.prior_hash,
            }
            recomputed = self._hash(payload)
            if recomputed != entry.entry_hash or entry.prior_hash != prior:
                return False
            prior = entry.entry_hash
        return True

    def attach_persistence(self, persistence: "AuditLogPersistence") -> None:
        """AD-456d: Attach an ``AuditLogPersistence`` instance.

        Pure setter — no other side effects. After attachment, each
        subsequent ``append()`` schedules a fire-and-forget SQLite write
        when a running asyncio loop is present. Mirrors
        ``OracleService.attach_semantic_layer`` shape from AD-686b.
        """
        self._persistence = persistence

    def _hash(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# AD-456d: SQLite persistence layer
# ---------------------------------------------------------------------------

# Schema mirrors ``AuditEntry`` 1-for-1. ``sequence`` is the natural primary
# key (already monotonic per ``len(self.entries)``-based assignment in
# ``AuditLog.append``); ``entry_hash`` is unique per the SHA-256-of-prior-hash
# chain semantics. Index on ``timestamp`` supports AD-456d-7 future range
# queries from the HXI inspection surface.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    sequence INTEGER PRIMARY KEY,
    timestamp REAL NOT NULL,
    category TEXT NOT NULL,
    detail TEXT NOT NULL,
    prior_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
"""


class AuditLogPersistence:
    """AD-456d: SQLite-backed persistence for ``AuditLog``.

    Cloud-ready via injected ``connection_factory: ConnectionFactory``
    (AD-466). Mirrors ``ClearanceGrantStore`` (AD-622) WAL/busy_timeout/
    synchronous PRAGMA shape exactly. Writes are append-only; reads are
    used at boot to rehydrate the in-memory chain.

    v1 ships start + persist_entry + load_entries + count + stop. The
    ``stop()`` method is defined but NOT wired into runtime shutdown in
    v1 (deferred to AD-456d-1 — paired with similar shutdowns for
    ``ClearanceGrantStore``, ``CognitiveJournal``, etc.). Tests call
    ``stop()`` directly.
    """

    def __init__(
        self,
        *,
        db_path: str,
        connection_factory: "ConnectionFactory",
        emit_event: Any | None = None,
    ) -> None:
        self._db_path = db_path
        self._connection_factory = connection_factory
        self._emit_event = emit_event
        self._db: Any = None

    async def start(self) -> None:
        """Open the connection, set PRAGMAs, create schema."""
        self._db = await self._connection_factory.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("AD-456d: AuditLogPersistence started (db=%s)", self._db_path)

    async def stop(self) -> None:
        """Close the connection. NOT wired into runtime shutdown in v1
        (deferred to AD-456d-1). Tests call directly.
        """
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def persist_entry(self, entry: AuditEntry) -> None:
        """Insert one ``AuditEntry`` row + commit + emit ``AUDIT_PERSISTED``.

        Tier-2 log-and-degrade — SQLite write failures NEVER propagate up to
        the sync ``append()`` caller (which scheduled this as a fire-and-
        forget task). The deny decision is already chained in memory and
        emitted as ``AUDIT_RECORDED``; the persist channel is observer-only.
        """
        if self._db is None:
            logger.warning(
                "AD-456d: persist_entry called before start() (sequence=%d)",
                entry.sequence,
            )
            return
        try:
            await self._db.execute(
                """INSERT INTO audit_log
                       (sequence, timestamp, category, detail, prior_hash, entry_hash)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    entry.sequence,
                    entry.timestamp,
                    entry.category,
                    entry.detail,
                    entry.prior_hash,
                    entry.entry_hash,
                ),
            )
            await self._db.commit()
        except Exception:
            logger.warning(
                "AD-456d: AuditLog persist failed (sequence=%d, category=%s)",
                entry.sequence, entry.category, exc_info=True,
            )
            return
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.AUDIT_PERSISTED,
                    {
                        "sequence": entry.sequence,
                        "entry_hash": entry.entry_hash,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-456d: AUDIT_PERSISTED emit failed (sequence=%d)",
                    entry.sequence, exc_info=True,
                )

    async def load_entries(self) -> list[AuditEntry]:
        """Return all rows ordered by sequence ASC for chain rehydration.

        ORDER BY sequence is REQUIRED — without it, SQLite is permitted to
        return rows in any order, which would shuffle the prior_hash chain
        and break ``verify_chain()`` after rehydrate.
        """
        if self._db is None:
            return []
        cursor = await self._db.execute(
            """SELECT sequence, timestamp, category, detail, prior_hash, entry_hash
               FROM audit_log ORDER BY sequence ASC"""
        )
        rows = await cursor.fetchall()
        return [
            AuditEntry(
                sequence=row[0],
                timestamp=row[1],
                category=row[2],
                detail=row[3],
                prior_hash=row[4],
                entry_hash=row[5],
            )
            for row in rows
        ]

    async def count(self) -> int:
        """Return total persisted rows (testability helper)."""
        if self._db is None:
            return 0
        cursor = await self._db.execute("SELECT COUNT(*) FROM audit_log")
        row = await cursor.fetchone()
        return row[0] if row else 0
