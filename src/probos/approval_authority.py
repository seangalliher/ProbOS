"""AD-1213: ApprovalAuthorityStore -- the Captain's expiring approval-authority records.

Two kinds of record widen who may decide a capability or skill request, and both
are issued by the Captain alone:

* ``first_officer_delegation`` -- with no live delegation the First Officer
  decides nothing; with one, the First Officer may decide what the Captain has
  delegated once the grace period has passed.
* ``captain_unavailable`` -- while live, that grace period is zero.

Neither can exist without an expiry. ``expires_at`` is ``NOT NULL`` in the
schema, not merely in a method signature (the AD-1154 / AD-1159 precedent), a TTL
must be a finite, strictly positive real, and a record whose ``expires_at`` has
passed reads as absent. Issuing a record supersedes the live one of its kind in
one transaction, so at most one of each kind is ever live. Rows are never
deleted: revoking or superseding flips ``revoked`` so every delegation and every
unavailability mark stays on the record.

This is the sixth instance of one store pattern (``ConnectionFactory``
injection, WAL, ``busy_timeout=5000``, ``synchronous=NORMAL``, an in-memory
cache for zero-I/O synchronous reads, lazy expiry against an injected clock),
not a new pattern. Data only: it imports nothing from the runtime.

**Fail closed.** ``live()`` answers from the cache, and raises
:class:`ApprovalAuthorityUnavailable` instead of guessing whenever the store is
not running or its clock does not read as a finite real. Every caller treats
that as "the Captain decides". The cache changes only after a commit (BF-722), so
a failed write leaves the authority that was live exactly as it was.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

FIRST_OFFICER_DELEGATION = "first_officer_delegation"
CAPTAIN_UNAVAILABLE = "captain_unavailable"
RECORD_KINDS: frozenset[str] = frozenset({FIRST_OFFICER_DELEGATION, CAPTAIN_UNAVAILABLE})
# The tool that confers decision authority. Defined in this, the lowest AD-1213
# module, so the AD-854 grant fast path can refuse to auto-grant it without an
# import cycle; ``delegated_approvals`` re-exports it.
REVIEW_TOOL_ID = "review_requests"
MAX_REASON_CHARS = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_authority (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    issued_by TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    issued_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at REAL,
    revoked_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_aa_live ON approval_authority(kind, revoked, expires_at);
"""

_SELECT_COLUMNS = (
    "id, kind, issued_by, reason, issued_at, expires_at, revoked, revoked_at, revoked_by"
)


@dataclass(frozen=True)
class AuthorityRecord:
    """One Captain-issued authority record."""

    id: str
    kind: str
    issued_by: str
    reason: str
    issued_at: float
    expires_at: float
    revoked: bool = False
    revoked_at: float | None = None
    revoked_by: str = ""


class ApprovalAuthorityUnavailable(Exception):
    """The store cannot answer an authority question. Callers fail closed."""


def _require_kind(kind: Any) -> None:
    if type(kind) is not str or kind not in RECORD_KINDS:
        raise ValueError(f"unknown approval-authority record kind {kind!r}")


def _checked_now(clock: Callable[[], float]) -> float:
    """The store's "now", or ``ApprovalAuthorityUnavailable`` when it is not a finite real.

    A NaN clock would make every ``expires_at <= now`` test false and so keep a
    lapsed record live -- the one inversion this store cannot allow.
    """
    now = clock()
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ApprovalAuthorityUnavailable("the approval-authority clock is not a finite real")
    return float(now)


async def _rollback_quietly(db: Any) -> None:
    """Undo an uncommitted write so a later commit cannot land it by accident."""
    try:
        await db.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- no open transaction is the common case
        logger.debug(
            "AD-1213: rollback after a failed approval-authority write found no open "
            "transaction; the original error is re-raised unchanged"
        )


class ApprovalAuthorityStore:
    """Durable, expiring First Officer delegations and Captain-unavailable marks.

    Public API:
        start() / stop() -- lifecycle
        issue(kind, *, ttl_seconds, issued_by, reason="") -> AuthorityRecord
        revoke(kind, *, revoked_by) -> int
        live(kind) -> AuthorityRecord | None   (synchronous, cache-only)
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: ConnectionFactory | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Construct the store.

        Args:
            db_path: SQLite path. Empty means cache-only (no persistence); the
                store still becomes ready only in :meth:`start`.
            connection_factory: injected per the Cloud-Ready Storage rule; the
                default SQLite factory is imported lazily.
            clock: the single source of "now" -- issue, revoke and lazy expiry.
        """
        self._db_path = db_path
        self._db: Any = None
        self._cache: dict[str, AuthorityRecord] = {}
        self._clock = clock
        self._ready = False
        self._lock = asyncio.Lock()
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory

    async def start(self) -> None:
        """Open the database, apply the schema, load live records, then become ready."""
        if self._db_path:
            self._db = await self._connection_factory.connect(self._db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            await self._load_cache()
        self._ready = True
        logger.info(
            "AD-1213: ApprovalAuthorityStore started (db=%s, live records=%d)",
            self._db_path or "<cache-only>",
            len(self._cache),
        )

    async def stop(self) -> None:
        """Stop answering authority questions, then close the database."""
        self._ready = False
        self._cache.clear()
        if self._db:
            await self._db.close()
            self._db = None

    async def issue(
        self, kind: str, *, ttl_seconds: float, issued_by: str, reason: str = "",
    ) -> AuthorityRecord:
        """Issue a record of ``kind`` that expires ``ttl_seconds`` from now.

        Supersedes the live record of the same kind in the same transaction, so
        at most one of each kind is live. The cache is updated only after the
        commit; a failed commit leaves ``live()`` unchanged and propagates.

        Raises:
            ApprovalAuthorityUnavailable: the store is not running.
            ValueError: an unknown kind; a ``ttl_seconds`` that is not a finite,
                strictly positive ``int`` or ``float`` (``bool`` is refused); a
                blank ``issued_by``; a ``reason`` over 500 characters.
        """
        if not self._ready:
            raise ApprovalAuthorityUnavailable("the approval-authority store is not running")
        _require_kind(kind)
        if (
            type(ttl_seconds) not in (int, float)
            or not math.isfinite(ttl_seconds)
            or ttl_seconds <= 0
        ):
            raise ValueError(
                "ttl_seconds must be a finite positive real (int or float, not bool); "
                f"got {ttl_seconds!r}"
            )
        if type(issued_by) is not str or not issued_by.strip():
            raise ValueError("issued_by must be a non-blank string")
        if type(reason) is not str or len(reason) > MAX_REASON_CHARS:
            raise ValueError(f"reason must be a string of at most {MAX_REASON_CHARS} characters")
        async with self._lock:
            now = _checked_now(self._clock)
            record = AuthorityRecord(
                id=str(uuid.uuid4()),
                kind=kind,
                issued_by=issued_by,
                reason=reason,
                issued_at=now,
                expires_at=now + float(ttl_seconds),
            )
            if self._db:
                try:
                    await self._db.execute(
                        "UPDATE approval_authority SET revoked = 1, revoked_at = ?, "
                        "revoked_by = ? WHERE kind = ? AND revoked = 0 AND expires_at > ?",
                        (now, issued_by, kind, now),
                    )
                    await self._db.execute(
                        f"INSERT INTO approval_authority ({_SELECT_COLUMNS}) "
                        "VALUES (?, ?, ?, ?, ?, ?, 0, NULL, '')",
                        (
                            record.id, record.kind, record.issued_by, record.reason,
                            record.issued_at, record.expires_at,
                        ),
                    )
                    await self._db.commit()
                except BaseException:
                    await _rollback_quietly(self._db)
                    raise
            self._cache[kind] = record
        logger.info(
            "AD-1213: approval authority %s issued by %s until %.0f (id=%s)",
            kind, issued_by[:24], record.expires_at, record.id[:12],
        )
        return record

    async def revoke(self, kind: str, *, revoked_by: str) -> int:
        """Soft-revoke every live record of ``kind``; return how many were live.

        Rows are never deleted. The cache is dropped only after the commit.
        """
        if not self._ready:
            raise ApprovalAuthorityUnavailable("the approval-authority store is not running")
        _require_kind(kind)
        if type(revoked_by) is not str or not revoked_by.strip():
            raise ValueError("revoked_by must be a non-blank string")
        async with self._lock:
            now = _checked_now(self._clock)
            if self._db:
                try:
                    cursor = await self._db.execute(
                        "UPDATE approval_authority SET revoked = 1, revoked_at = ?, "
                        "revoked_by = ? WHERE kind = ? AND revoked = 0 AND expires_at > ?",
                        (now, revoked_by, kind, now),
                    )
                    count = cursor.rowcount
                    await self._db.commit()
                except BaseException:
                    await _rollback_quietly(self._db)
                    raise
            else:
                cached = self._cache.get(kind)
                count = 1 if cached is not None and cached.expires_at > now else 0
            self._cache.pop(kind, None)
        logger.info(
            "AD-1213: approval authority %s revoked by %s (%d live record(s))",
            kind, revoked_by[:24], count,
        )
        return count

    def live(self, kind: str) -> AuthorityRecord | None:
        """The live record of ``kind``, or ``None``. Synchronous and cache-only.

        Lazy expiry: a record with ``expires_at <= now`` is dropped and reads as
        absent. Raises :class:`ApprovalAuthorityUnavailable` when the store is
        not running, and ``ValueError`` for an unknown kind.
        """
        if not self._ready:
            raise ApprovalAuthorityUnavailable("the approval-authority store is not running")
        _require_kind(kind)
        record = self._cache.get(kind)
        if record is None:
            return None
        if record.expires_at <= _checked_now(self._clock):
            self._cache.pop(kind, None)
            return None
        return record

    async def _load_cache(self) -> None:
        self._cache.clear()
        if not self._db:
            return
        now = _checked_now(self._clock)
        async with self._db.execute(
            f"SELECT {_SELECT_COLUMNS} FROM approval_authority "
            "WHERE revoked = 0 AND expires_at > ? ORDER BY issued_at",
            (now,),
        ) as cur:
            async for row in cur:
                record = self._row_to_record(row)
                if record.kind in RECORD_KINDS:
                    self._cache[record.kind] = record

    def _row_to_record(self, row: Any) -> AuthorityRecord:
        return AuthorityRecord(
            id=row[0],
            kind=row[1],
            issued_by=row[2],
            reason=row[3],
            issued_at=row[4],
            expires_at=row[5],
            revoked=bool(row[6]),
            revoked_at=row[7],
            revoked_by=row[8],
        )
