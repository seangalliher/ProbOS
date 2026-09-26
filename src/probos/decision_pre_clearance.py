"""AD-1214 (#1171): DecisionPreClearanceStore -- the Captain's expiring decision pre-clearances.

A pre-clearance stops the Captain's notification for one exact class of AD-1213
delegated decision. It confers no authority: every AD-1213 rule still decides
whether an agent may decide at all, the pre-clearance is consulted only after
the verdict has allowed the decision, and every decision -- pre-cleared or not
-- is still audited.

A class is eight exact values (:class:`PreClearanceKey`): the queue, the request
kind, its exact target, the request class, the requester's department, the
deciding post, that post's role, and approve-or-deny. A match is equality on
the frozen key. No wildcard, prefix or pattern is representable. The key type is
the complete validator: it refuses any value outside its allowlist or pattern.
The schema's CHECK constraints refuse every wildcard and every out-of-range
value, and the loader skips any row the key type refuses, so neither a route nor
a hand-edited row can widen one.

This is the seventh instance of one store pattern (``ConnectionFactory``
injection, WAL, ``busy_timeout=5000``, ``synchronous=NORMAL``, an in-memory
cache for zero-I/O synchronous reads, lazy expiry against an injected clock,
supersede in one transaction, soft revoke), not a new pattern. ``expires_at`` is
``NOT NULL`` in the schema. Data plus the pure key and text core: it imports
nothing from the runtime.

**Fail closed.** :meth:`DecisionPreClearanceStore.lookup` answers from the cache
and raises :class:`PreClearanceUnavailable` instead of guessing whenever the
store is not running or its clock does not read as a finite real; every caller
treats that as "notify the Captain". The cache changes only after a commit, so a
failed write leaves every pre-clearance exactly as it was, and two live rows for
one class load as no pre-clearance at all. Offers -- the opaque ids a
notification carries so the Captain can accept its exact class -- are held in
memory only and are forgotten on restart.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import secrets
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from probos.capability_request import validate_install_payload, validate_python_install_target
from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

PRE_CLEAR_ACTION_PREFIX = "approval-pre-clear:"
OFFER_ID_RE = re.compile(r"[0-9a-f]{32}")
MAX_OFFERS = 256
MAX_REASON_CHARS = 500
PRE_CLEARANCE_AUDIT_CATEGORY = "decision_pre_clearance"
TARGET_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}")
_ID_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_KINDS: dict[str, tuple[str, ...]] = {"capability": ("grant", "install"), "skill": ("skill",)}
# The RequestClass values an agent can ever be allowed to decide (AD-1213); pinned against the enum.
_CLASSES = ("non_destructive", "destructive")
# The DeciderRole values an agent decides under; pinned against the enum.
_ROLES = ("department_chief", "first_officer")
_DECISIONS = ("approve", "deny")
_NOT_A_KEY = "AD-1214: not an exact pre-clearance key"
_MAX_OFFER_TTL_HOURS = 720
_MAX_RECORD_ID_CHARS = 64
_ROLE_TEXT = {"department_chief": "department chief", "first_officer": "First Officer"}
_KIND_TEXT = {"grant": "grant tool", "install": "install Python package", "skill": "train skill"}
_KEY_COLUMNS = (
    "queue", "kind", "target", "request_class", "requester_department", "decider_post",
    "decider_role", "decision",
)
_KEY_MATCH = " AND ".join(f"{column} = ?" for column in _KEY_COLUMNS)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_pre_clearances (
    id TEXT PRIMARY KEY,
    queue TEXT NOT NULL CHECK (queue IN ('capability', 'skill')),
    kind TEXT NOT NULL CHECK (kind IN ('grant', 'install', 'skill')),
    target TEXT NOT NULL CHECK (length(target) BETWEEN 1 AND 200 AND target NOT GLOB '*[^A-Za-z0-9_.:-]*'),
    request_class TEXT NOT NULL CHECK (request_class IN ('non_destructive', 'destructive')),
    requester_department TEXT NOT NULL CHECK (length(requester_department) BETWEEN 1 AND 64 AND requester_department NOT GLOB '*[^a-z0-9_]*'),
    decider_post TEXT NOT NULL CHECK (length(decider_post) BETWEEN 1 AND 64 AND decider_post NOT GLOB '*[^a-z0-9_]*'),
    decider_role TEXT NOT NULL CHECK (decider_role IN ('department_chief', 'first_officer')),
    decision TEXT NOT NULL CHECK (decision IN ('approve', 'deny')),
    issued_by TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    issued_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at REAL,
    revoked_by TEXT NOT NULL DEFAULT '',
    CHECK ((queue = 'capability' AND kind IN ('grant', 'install')) OR (queue = 'skill' AND kind = 'skill'))
);
CREATE INDEX IF NOT EXISTS idx_dpc_live ON decision_pre_clearances(revoked, expires_at);
"""

_SELECT_COLUMNS = (
    "id, queue, kind, target, request_class, requester_department, decider_post, decider_role, "
    "decision, issued_by, reason, issued_at, expires_at, revoked, revoked_at, revoked_by"
)


@dataclass(frozen=True)
class PreClearanceKey:
    """One exact class of delegated decision. Equality on all eight fields; no wildcard.

    Construction refuses any value outside its allowlist or pattern, so a key
    that exists names exactly one class.
    """

    queue: str
    kind: str
    target: str
    request_class: str
    requester_department: str
    decider_post: str
    decider_role: str
    decision: str

    def __post_init__(self) -> None:
        values = (
            self.queue, self.kind, self.target, self.request_class, self.requester_department,
            self.decider_post, self.decider_role, self.decision,
        )
        if not all(type(value) is str for value in values):
            raise ValueError(_NOT_A_KEY)
        if self.kind not in _KINDS.get(self.queue, ()):
            raise ValueError(_NOT_A_KEY)
        if not TARGET_RE.fullmatch(self.target):
            raise ValueError(_NOT_A_KEY)
        if self.kind == "install" and validate_python_install_target(self.target) != self.target:
            raise ValueError(_NOT_A_KEY)
        if self.request_class not in _CLASSES:
            raise ValueError(_NOT_A_KEY)
        if not _ID_RE.fullmatch(self.requester_department):
            raise ValueError(_NOT_A_KEY)
        if not _ID_RE.fullmatch(self.decider_post):
            raise ValueError(_NOT_A_KEY)
        if self.decider_role not in _ROLES:
            raise ValueError(_NOT_A_KEY)
        if self.decision not in _DECISIONS:
            raise ValueError(_NOT_A_KEY)


@dataclass(frozen=True)
class PreClearance:
    """One Captain-issued pre-clearance of one exact class."""

    id: str
    key: PreClearanceKey
    issued_by: str
    reason: str
    issued_at: float
    expires_at: float
    revoked: bool = False
    revoked_at: float | None = None
    revoked_by: str = ""


class PreClearanceUnavailable(Exception):
    """The store cannot answer. Callers fail closed: the Captain is notified."""


class PreClearanceBook(Protocol):
    """The only two calls the decision path makes. Both are synchronous and never awaited."""

    def lookup(self, key: PreClearanceKey) -> PreClearance | None: ...

    def offer(self, key: PreClearanceKey, *, ttl_hours: int) -> str | None: ...


def pre_clearance_key(
    *,
    queue: Any,
    kind: Any,
    target: Any,
    install_payload: Any,
    request_class: Any,
    requester_department: Any,
    decider_post: Any,
    decider_role: Any,
    approve: Any,
) -> PreClearanceKey | None:
    """The exact class of one decision, or ``None`` when it cannot be pre-cleared. Never raises.

    ``None`` for a non-``bool`` approve; an install without Python provenance
    (an MCP install, or a legacy install with no payload); and anything the key
    refuses -- a kind other than a grant, an install or a skill, a free-text or
    unpatterned target, an unknown class, role, department or post.
    """
    if type(approve) is not bool:
        return None
    if kind == "install" and validate_install_payload(install_payload) != {"install_kind": "python"}:
        return None
    try:
        return PreClearanceKey(
            queue=queue,
            kind=kind,
            target=target,
            request_class=request_class,
            requester_department=requester_department,
            decider_post=decider_post,
            decider_role=decider_role,
            decision="approve" if approve else "deny",
        )
    except ValueError:
        return None


def describe_scope(key: PreClearanceKey) -> str:
    """The exact class in plain words: the text the Captain consents to."""
    verb = "approves" if key.decision == "approve" else "denies"
    return (
        f"when the {key.decider_post} post, acting as {_ROLE_TEXT[key.decider_role]}, {verb} a "
        f"request from the {key.requester_department} department to {_KIND_TEXT[key.kind]} "
        f"'{key.target}' (class {key.request_class})"
    )


def offer_sentence(key: PreClearanceKey, *, hours: int) -> str:
    """The sentence a notification appends to offer pre-clearing ``key`` for ``hours``."""
    unit = "hour" if hours == 1 else "hours"
    return (
        f"Pre-clear offer (AD-1214): for {hours} {unit} after you accept, you will not be "
        f"notified {describe_scope(key)}. Each such decision is still audited, and nothing else "
        "is pre-cleared."
    )


def make_offer(
    book: PreClearanceBook, key: PreClearanceKey, *, hours: int,
) -> tuple[str, str] | None:
    """``(action_url, sentence)`` offering ``key`` for ``hours``, or ``None``. Never raises.

    The sentence and the offer-book entry come from the one ``key`` instance,
    so the text the Captain reads is the class the offer id resolves to.
    """
    try:
        if type(key) is not PreClearanceKey or type(hours) is not int or hours < 1:
            return None
        sentence = offer_sentence(key, hours=hours)
        offer_id = book.offer(key, ttl_hours=hours)
    except Exception:
        logger.warning(
            "AD-1214: a pre-clear offer for %s could not be recorded; the Captain is notified "
            "without one",
            key, exc_info=True,
        )
        return None
    if type(offer_id) is not str or not OFFER_ID_RE.fullmatch(offer_id):
        return None
    return PRE_CLEAR_ACTION_PREFIX + offer_id, sentence


def confirm_pre_clearance(
    book: PreClearanceBook | None, key: PreClearanceKey | None, match: PreClearance | None,
) -> PreClearance | None:
    """``match`` while ``book`` still holds that same record for ``key``, else ``None``. Never raises.

    Synchronous and cache-only. The decision path calls it immediately after its
    commit, so a pre-clearance revoked, expired or superseded before this re-read
    no longer silences the decision it matched.
    """
    if match is None or book is None or key is None:  # nothing matched, so nothing is silenced
        return None
    try:
        current = book.lookup(key)
        return match if current is not None and current.id == match.id else None
    except Exception:
        logger.warning(
            "AD-1214: pre-clearance %s could not be re-read after the decision it matched was "
            "committed; that decision is treated as not pre-cleared and the Captain is notified",
            str(getattr(match, "id", ""))[:12], exc_info=True,
        )
        return None


def _checked_now(clock: Callable[[], float]) -> float:
    """The store's "now", or ``PreClearanceUnavailable`` when it is not a finite real.

    A NaN clock would make every ``expires_at <= now`` test false and so keep a
    lapsed pre-clearance live.
    """
    now = clock()
    if type(now) not in (int, float) or not math.isfinite(now):
        raise PreClearanceUnavailable("the decision pre-clearance clock is not a finite real")
    return float(now)


async def _rollback_quietly(db: Any) -> None:
    """Undo an uncommitted write so a later commit cannot land it by accident."""
    try:
        await db.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- no open transaction is the common case
        logger.debug(
            "AD-1214: rollback after a failed decision pre-clearance write found no open "
            "transaction; the original error is re-raised unchanged"
        )


class DecisionPreClearanceStore:
    """Durable, expiring, revocable decision pre-clearances, and the in-memory offers.

    Public API:
        start() / stop() -- lifecycle
        issue(key, *, ttl_seconds, issued_by, reason="") -> PreClearance
        revoke(record_id, *, revoked_by) -> int
        lookup(key) -> PreClearance | None       (synchronous, cache-only)
        live() -> list[PreClearance]             (synchronous, cache-only)
        offer(key, *, ttl_hours) -> str | None   (synchronous, in memory)
        offered(offer_id) -> tuple[PreClearanceKey, int] | None
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
        self._cache: dict[PreClearanceKey, PreClearance] = {}
        self._offers: OrderedDict[str, tuple[PreClearanceKey, int]] = OrderedDict()
        self._clock = clock
        self._ready = False
        self._lock = asyncio.Lock()
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory

    async def start(self) -> None:
        """Open the database, apply the schema, load live pre-clearances, then become ready."""
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
            "AD-1214: DecisionPreClearanceStore started (db=%s, live pre-clearances=%d)",
            self._db_path or "<cache-only>",
            len(self._cache),
        )

    async def stop(self) -> None:
        """Stop answering, forget every offer, then close the database."""
        self._ready = False
        self._cache.clear()
        self._offers.clear()
        if self._db:
            await self._db.close()
            self._db = None

    async def issue(
        self, key: PreClearanceKey, *, ttl_seconds: float, issued_by: str, reason: str = "",
    ) -> PreClearance:
        """Pre-clear ``key`` until ``ttl_seconds`` from now.

        Supersedes the live pre-clearance of the same key in the same
        transaction, so at most one is live per class. The cache is updated
        only after the commit; a failed commit leaves ``lookup()`` unchanged and
        propagates.

        Raises:
            PreClearanceUnavailable: the store is not running, or its clock is
                not a finite real.
            ValueError: ``key`` is not a :class:`PreClearanceKey`; a
                ``ttl_seconds`` that is not a finite, strictly positive ``int``
                or ``float`` (``bool`` is refused); a blank ``issued_by``; a
                ``reason`` over 500 characters.
        """
        if not self._ready:
            raise PreClearanceUnavailable("the decision pre-clearance store is not running")
        if type(key) is not PreClearanceKey:
            raise ValueError("AD-1214: a pre-clearance needs an exact PreClearanceKey")
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
            record = PreClearance(
                id=str(uuid.uuid4()),
                key=key,
                issued_by=issued_by,
                reason=reason,
                issued_at=now,
                expires_at=now + float(ttl_seconds),
            )
            values = tuple(getattr(key, column) for column in _KEY_COLUMNS)
            if self._db:
                try:
                    await self._db.execute(
                        "UPDATE decision_pre_clearances SET revoked = 1, revoked_at = ?, "
                        f"revoked_by = ? WHERE {_KEY_MATCH} AND revoked = 0 AND expires_at > ?",
                        (now, issued_by, *values, now),
                    )
                    await self._db.execute(
                        f"INSERT INTO decision_pre_clearances ({_SELECT_COLUMNS}) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, '')",
                        (
                            record.id, *values, record.issued_by, record.reason,
                            record.issued_at, record.expires_at,
                        ),
                    )
                    await self._db.commit()
                except BaseException:
                    await _rollback_quietly(self._db)
                    raise
            self._cache[key] = record
        logger.info(
            "AD-1214: decision pre-clearance %s issued by %s until %.0f: %s",
            record.id[:12], issued_by[:24], record.expires_at, describe_scope(key),
        )
        return record

    async def revoke(self, record_id: str, *, revoked_by: str) -> int:
        """Soft-revoke the live pre-clearance ``record_id``; return how many were live (0 or 1).

        Rows are never deleted. The cache is dropped only after the commit.
        """
        if not self._ready:
            raise PreClearanceUnavailable("the decision pre-clearance store is not running")
        if (
            type(record_id) is not str
            or not record_id.strip()
            or len(record_id) > _MAX_RECORD_ID_CHARS
        ):
            raise ValueError(
                f"record_id must be a non-blank string of at most {_MAX_RECORD_ID_CHARS} characters"
            )
        if type(revoked_by) is not str or not revoked_by.strip():
            raise ValueError("revoked_by must be a non-blank string")
        async with self._lock:
            now = _checked_now(self._clock)
            if self._db:
                try:
                    cursor = await self._db.execute(
                        "UPDATE decision_pre_clearances SET revoked = 1, revoked_at = ?, "
                        "revoked_by = ? WHERE id = ? AND revoked = 0 AND expires_at > ?",
                        (now, revoked_by, record_id, now),
                    )
                    count = cursor.rowcount
                    await self._db.commit()
                except BaseException:
                    await _rollback_quietly(self._db)
                    raise
            else:
                count = sum(
                    1 for record in self._cache.values()
                    if record.id == record_id and record.expires_at > now
                )
            self._cache = {key: record for key, record in self._cache.items() if record.id != record_id}
        logger.info(
            "AD-1214: decision pre-clearance %s revoked by %s (%d live record(s)); decisions of "
            "its class notify the Captain again",
            record_id[:12], revoked_by[:24], count,
        )
        return count

    def lookup(self, key: PreClearanceKey) -> PreClearance | None:
        """The live pre-clearance of exactly ``key``, or ``None``. Synchronous and cache-only.

        Lazy expiry: a pre-clearance with ``expires_at <= now`` is dropped and
        reads as absent. Anything that is not a :class:`PreClearanceKey` reads
        as absent. Raises :class:`PreClearanceUnavailable` when the store is
        not running or its clock is not a finite real.
        """
        if not self._ready:
            raise PreClearanceUnavailable("the decision pre-clearance store is not running")
        now = _checked_now(self._clock)
        if type(key) is not PreClearanceKey:
            return None
        record = self._cache.get(key)
        if record is None:
            return None
        if record.expires_at <= now:
            self._cache.pop(key, None)
            return None
        return record

    def live(self) -> list[PreClearance]:
        """Every unexpired, unrevoked pre-clearance, oldest first. Synchronous and cache-only."""
        if not self._ready:
            raise PreClearanceUnavailable("the decision pre-clearance store is not running")
        now = _checked_now(self._clock)
        for key in [key for key, record in self._cache.items() if record.expires_at <= now]:
            del self._cache[key]
        return sorted(self._cache.values(), key=lambda record: record.issued_at)

    def offer(self, key: PreClearanceKey, *, ttl_hours: int) -> str | None:
        """Remember an offer to pre-clear ``key`` for ``ttl_hours``; return its opaque id.

        Synchronous, in memory, no I/O. ``None`` when the store is not running,
        for anything that is not a :class:`PreClearanceKey`, or unless
        ``ttl_hours`` is an ``int`` from 1 to 720. The oldest offers are
        forgotten beyond :data:`MAX_OFFERS`.
        """
        if not self._ready or type(key) is not PreClearanceKey:
            return None
        if type(ttl_hours) is not int or not 1 <= ttl_hours <= _MAX_OFFER_TTL_HOURS:
            return None
        offer_id = secrets.token_hex(16)
        self._offers[offer_id] = (key, ttl_hours)
        while len(self._offers) > MAX_OFFERS:
            self._offers.popitem(last=False)
        return offer_id

    def offered(self, offer_id: str) -> tuple[PreClearanceKey, int] | None:
        """The key and hours an offer id names, or ``None`` for a malformed or unknown id.

        Raises :class:`PreClearanceUnavailable` when the store is not running.
        """
        if not self._ready:
            raise PreClearanceUnavailable("the decision pre-clearance store is not running")
        if type(offer_id) is not str or not OFFER_ID_RE.fullmatch(offer_id):
            return None
        return self._offers.get(offer_id)

    async def _load_cache(self) -> None:
        self._cache.clear()
        if not self._db:
            return
        now = _checked_now(self._clock)
        grouped: dict[PreClearanceKey, list[PreClearance]] = {}
        async with self._db.execute(
            f"SELECT {_SELECT_COLUMNS} FROM decision_pre_clearances "
            "WHERE revoked = 0 AND expires_at > ? ORDER BY issued_at",
            (now,),
        ) as cur:
            async for row in cur:
                try:
                    record = self._row_to_record(row)
                except ValueError:
                    logger.warning(
                        "AD-1214: decision pre-clearance row %s does not name an exact class; it "
                        "is not loaded, so any decision it might have matched notifies the Captain",
                        str(row[0])[:12],
                    )
                    continue
                grouped.setdefault(record.key, []).append(record)
        for key, records in grouped.items():
            if len(records) > 1:
                logger.warning(
                    "AD-1214: %d live decision pre-clearances (%s) name one class; none is loaded, "
                    "so that class notifies the Captain until the Captain pre-clears it again",
                    len(records), ", ".join(record.id[:12] for record in records),
                )
                continue
            self._cache[key] = records[0]

    def _row_to_record(self, row: Any) -> PreClearance:
        return PreClearance(
            id=row[0],
            key=PreClearanceKey(
                queue=row[1],
                kind=row[2],
                target=row[3],
                request_class=row[4],
                requester_department=row[5],
                decider_post=row[6],
                decider_role=row[7],
                decision=row[8],
            ),
            issued_by=row[9],
            reason=row[10],
            issued_at=row[11],
            expires_at=row[12],
            revoked=bool(row[13]),
            revoked_at=row[14],
            revoked_by=row[15],
        )
