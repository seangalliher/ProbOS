"""AD-1228 (#1201): StandingInterestStore -- an agent's durable, expiring, revocable standing interests.

A standing interest is an agent's registration to be told when one declared
condition becomes true (the vocabulary below). This module holds the
registrations only; ``probos.cognitive.standing_interests`` decides when a
notice is due and carries it into the agent's next proactive think.

This is the eighth instance of one store pattern (``ConnectionFactory``
injection, WAL, ``busy_timeout=5000``, ``synchronous=NORMAL``, an in-memory
cache for zero-I/O synchronous reads, lazy expiry against an injected clock),
not a new pattern. Unlike AD-1213/1214 it is BOUNDED and deletes: the rows are
agent-authored, so a registration nobody retires would be a registry that grows
while nothing uses it (BF-735). Revoke, expiry and a delivered one-shot delete
the row; expired rows are deleted at start and inside every register.
``expires_at`` is ``NOT NULL`` and must follow ``created_at``.

Durable: the registration itself, because a work item outlives the process
and an agent cannot tell that its registration died with it. Not durable:
pending notices and edge/debounce state, which the service keeps in memory.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

# The closed vocabulary: the single source every layer reads.
WORK_ITEM_FINISHED = "work_item_finished"
TRUST_FALLING = "trust_falling"
SELF_SIMILARITY_HIGH = "self_similarity_high"
KINDS: frozenset[str] = frozenset({WORK_ITEM_FINISHED, TRUST_FALLING, SELF_SIMILARITY_HIGH})
CROSS_AGENT_KINDS: frozenset[str] = frozenset({TRUST_FALLING, SELF_SIMILARITY_HIGH})
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_REG_ID_RE = re.compile(r"[0-9a-f]{32}")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS standing_interests (
    id TEXT PRIMARY KEY CHECK (length(id) = 32),
    agent_id TEXT NOT NULL CHECK (length(agent_id) BETWEEN 1 AND 128),
    kind TEXT NOT NULL CHECK (kind IN ('self_similarity_high', 'trust_falling', 'work_item_finished')),
    subject_id TEXT NOT NULL CHECK (length(subject_id) BETWEEN 1 AND 128),
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL CHECK (expires_at > created_at)
);
CREATE UNIQUE INDEX IF NOT EXISTS standing_interests_one_per_key ON standing_interests (agent_id, kind, subject_id);
CREATE INDEX IF NOT EXISTS standing_interests_by_subject ON standing_interests (kind, subject_id);
"""

_COLUMNS = "id, agent_id, kind, subject_id, created_at, expires_at"


@dataclass(frozen=True)
class StandingInterest:
    """One live registration: ``agent_id`` wants to hear when ``kind`` becomes true of ``subject_id``."""

    id: str
    agent_id: str
    kind: str
    subject_id: str
    created_at: float
    expires_at: float


class StandingInterestUnavailable(Exception):
    """The store cannot answer: not running, or its clock is not a finite real."""


class StandingInterestLimitReached(Exception):
    """The holder already has ``limit`` live registrations."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"AD-1228: the per-agent limit of {limit} standing interests is reached")
        self.limit = limit


def _checked_now(clock: Callable[[], float]) -> float:
    """The store's "now", or ``StandingInterestUnavailable`` when it is not a finite real.

    A NaN clock would make every ``expires_at <= now`` test false and keep a
    lapsed registration live.
    """
    now = clock()
    if type(now) not in (int, float) or not math.isfinite(now):
        raise StandingInterestUnavailable("AD-1228: the standing interest clock is not a finite real")
    return float(now)


async def _rollback_quietly(db: Any) -> None:
    """Undo an uncommitted write so a later commit cannot land it by accident."""
    try:
        await db.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- no open transaction is the common case
        logger.debug(
            "AD-1228: rollback after a failed standing interest write found no open "
            "transaction; the original error is re-raised unchanged"
        )


def _valid_id(value: object) -> bool:
    return type(value) is str and _ID_RE.fullmatch(value) is not None


class StandingInterestStore:
    """Live standing interests: bounded per holder, expiring, deleted when retired.

    Public API:
        start() / stop() -- lifecycle
        register(*, agent_id, kind, subject_id, ttl_seconds, max_live) -> (StandingInterest, renewed)
        revoke(registration_id, *, agent_id) -> bool
        live(kind=None) / live_for_holder(agent_id) / live_for_subject(kind, subject_id) /
        live_naming(subject_id) -> list[StandingInterest]   (synchronous, cache-only)
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
            clock: the single source of "now" -- register and lazy expiry.
        """
        self._db_path = db_path
        self._db: Any = None
        self._cache: dict[str, StandingInterest] = {}
        self._clock = clock
        self._ready = False
        self._lock = asyncio.Lock()
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory

    async def start(self) -> None:
        """Open the database, apply the schema, delete expired rows, load the rest, then become ready.

        A failure after the connection opens closes it, leaves the store stopped and propagates.
        """
        if self._db_path:
            now = _checked_now(self._clock)
            self._db = await self._connection_factory.connect(self._db_path)
            try:
                await self._db.execute("PRAGMA journal_mode=WAL")
                await self._db.execute("PRAGMA busy_timeout=5000")
                await self._db.execute("PRAGMA synchronous=NORMAL")
                await self._db.executescript(_SCHEMA)
                await self._db.execute("DELETE FROM standing_interests WHERE expires_at <= ?", (now,))
                await self._db.commit()
                await self._load_cache()
            except BaseException:
                db, self._db = self._db, None
                self._cache.clear()
                await db.close()
                raise
        self._ready = True
        logger.info(
            "AD-1228: StandingInterestStore started (db=%s, live registrations=%d)",
            self._db_path or "<cache-only>", len(self._cache),
        )

    async def stop(self) -> None:
        """Stop answering, forget the cache, then close the database."""
        self._ready = False
        self._cache.clear()
        if self._db:
            await self._db.close()
            self._db = None

    async def register(
        self, *, agent_id: str, kind: str, subject_id: str, ttl_seconds: float, max_live: int,
    ) -> tuple[StandingInterest, bool]:
        """Register (or renew) ``agent_id``'s interest in ``kind`` of ``subject_id`` for ``ttl_seconds``.

        Renewing a live key keeps its id, costs no slot and returns ``renewed=True``.
        Expired rows are deleted in the same transaction. The cache changes only
        after the commit; a failed commit leaves every read unchanged and propagates.

        Raises:
            ValueError: an unknown kind, an id outside the pattern, a
                ``ttl_seconds`` that is not a finite positive ``int``/``float``
                (``bool`` is refused), or a ``max_live`` that is not an int >= 1.
            StandingInterestLimitReached: a new key while ``max_live`` are live.
            StandingInterestUnavailable: not running, or a clock that is not a finite real.
        """
        if type(kind) is not str or kind not in KINDS:
            raise ValueError(f"AD-1228: kind must be one of {sorted(KINDS)}")
        if not _valid_id(agent_id) or not _valid_id(subject_id):
            raise ValueError("AD-1228: agent_id and subject_id must be 1-128 characters of [A-Za-z0-9_.:-]")
        if type(ttl_seconds) not in (int, float) or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError(f"AD-1228: ttl_seconds must be a finite positive real; got {ttl_seconds!r}")
        if type(max_live) is not int or max_live < 1:
            raise ValueError(f"AD-1228: max_live must be an int of at least 1; got {max_live!r}")
        async with self._lock:
            now = self._now()
            expired = [rid for rid, rec in self._cache.items() if rec.expires_at <= now]
            live = [rec for rec in self._cache.values() if rec.agent_id == agent_id and rec.id not in expired]
            existing = next((rec for rec in live if rec.kind == kind and rec.subject_id == subject_id), None)
            if existing is None:
                if len(live) >= max_live:
                    raise StandingInterestLimitReached(max_live)
                record = StandingInterest(
                    id=secrets.token_hex(16), agent_id=agent_id, kind=kind, subject_id=subject_id,
                    created_at=now, expires_at=now + float(ttl_seconds),
                )
            else:
                record = replace(existing, expires_at=now + float(ttl_seconds))
            if self._db:
                try:
                    await self._db.execute("DELETE FROM standing_interests WHERE expires_at <= ?", (now,))
                    if existing is None:
                        await self._db.execute(
                            f"INSERT INTO standing_interests ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                            (record.id, agent_id, kind, subject_id, record.created_at, record.expires_at),
                        )
                    else:
                        await self._db.execute(
                            "UPDATE standing_interests SET expires_at = ? WHERE id = ?",
                            (record.expires_at, record.id),
                        )
                    await self._db.commit()
                except BaseException:
                    await _rollback_quietly(self._db)
                    raise
            for rid in expired:
                self._cache.pop(rid, None)
            self._cache[record.id] = record
        logger.info(
            "AD-1228: standing interest %s %s by %s: %s on %s until %.0f",
            record.id[:12], "renewed" if existing is not None else "registered",
            agent_id[:32], kind, subject_id[:32], record.expires_at,
        )
        return record, existing is not None

    async def revoke(self, registration_id: str, *, agent_id: str) -> bool:
        """Delete the holder's registration ``registration_id``. True only when a row went.

        A malformed id or an empty holder names no row, so it returns False
        without asking the database. The cache is dropped only after the commit.
        """
        if type(registration_id) is not str or _REG_ID_RE.fullmatch(registration_id) is None:
            return False
        if type(agent_id) is not str or not agent_id:
            return False
        async with self._lock:
            self._now()
            record = self._cache.get(registration_id)
            if self._db:
                try:
                    cursor = await self._db.execute(
                        "DELETE FROM standing_interests WHERE id = ? AND agent_id = ?",
                        (registration_id, agent_id),
                    )
                    count = cursor.rowcount
                    await self._db.commit()
                except BaseException:
                    await _rollback_quietly(self._db)
                    raise
            else:
                count = 1 if record is not None and record.agent_id == agent_id else 0
            if count:
                self._cache.pop(registration_id, None)
        if count:
            logger.info("AD-1228: standing interest %s retired by %s", registration_id[:12], agent_id[:32])
        return count > 0

    def live(self, kind: str | None = None) -> list[StandingInterest]:
        """Every unexpired registration (of ``kind``), oldest first. Synchronous and cache-only."""
        now = self._now()
        records = []
        for record in self._cache.values():
            if record.expires_at <= now:
                continue
            if kind is None or record.kind == kind:
                records.append(record)
        return sorted(records, key=lambda rec: (rec.created_at, rec.id))

    def live_for_holder(self, agent_id: str) -> list[StandingInterest]:
        """The unexpired registrations ``agent_id`` holds, oldest first."""
        return [record for record in self.live() if record.agent_id == agent_id]

    def live_for_subject(self, kind: str, subject_id: str) -> list[StandingInterest]:
        """The unexpired ``kind`` registrations whose subject is ``subject_id``, oldest first."""
        return [record for record in self.live(kind) if record.subject_id == subject_id]

    def live_naming(self, subject_id: str) -> list[StandingInterest]:
        """Cross-agent registrations about ``subject_id`` held by someone else, oldest first."""
        return [
            record for record in self.live()
            if record.kind in CROSS_AGENT_KINDS and record.subject_id == subject_id and record.agent_id != subject_id
        ]

    def _now(self) -> float:
        if not self._ready:
            raise StandingInterestUnavailable("AD-1228: the standing interest store is not running")
        return _checked_now(self._clock)

    async def _load_cache(self) -> None:
        self._cache.clear()
        if not self._db:
            return
        now = _checked_now(self._clock)
        async with self._db.execute(
            f"SELECT {_COLUMNS} FROM standing_interests WHERE expires_at > ?", (now,),
        ) as cur:
            async for row in cur:
                try:
                    record = self._record_from_row(row)
                except ValueError:
                    logger.warning(
                        "AD-1228: standing interest row %s fails validation; it is not loaded, so it "
                        "never fires and expires with its expiry",
                        str(row[0])[:12],
                    )
                    continue
                self._cache[record.id] = record

    @staticmethod
    def _record_from_row(row: Any) -> StandingInterest:
        rid, agent_id, kind, subject_id, created_at, expires_at = row
        times_ok = all(type(t) in (int, float) and math.isfinite(t) for t in (created_at, expires_at))
        if (
            type(rid) is not str or _REG_ID_RE.fullmatch(rid) is None
            or not _valid_id(agent_id) or not _valid_id(subject_id)
            or kind not in KINDS or not times_ok or expires_at <= created_at
        ):
            raise ValueError("AD-1228: not a valid standing interest row")
        return StandingInterest(
            id=rid, agent_id=agent_id, kind=kind, subject_id=subject_id,
            created_at=float(created_at), expires_at=float(expires_at),
        )
