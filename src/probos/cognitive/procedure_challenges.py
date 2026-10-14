"""AD-1326 (#1510): the durable record of procedure challengers and their evidence.

``ProcedureChallenger`` saves a FIX evolution inactive for routing and records it
here as a challenger of its parent, the champion. Each situation judged in both
orders is a ``procedure_comparisons`` row; the decision and its reason stay on the
challenge row; each dream cycle that judged, deferred or decided something leaves a
``procedure_challenge_cycles`` row. This module never removes a row, so a retired
challenger keeps its evidence (``test_retired_challenger_keeps_its_comparisons``,
``test_ledger_module_issues_no_delete``).

The file is ``procedures_challenges.db`` beside ``procedures.db``, on its own
connection. ``ProcedureStore`` opens that connection from its ``ConnectionFactory``,
holds it as a direct attribute (so BF-882's last-resort close reaches it when the
store's ``stop()`` fails in a startup rollback), hands it to this ledger and closes
it; the ledger applies its schema in ``start`` and lets go in ``detach``. Each status
change names the statuses it may move from, so a decided challenger cannot be moved
again (``test_set_status_is_conditional_on_expected``). Every write runs in one
transaction (``_write_transaction``) that is rolled back under the ledger lock on any
failure, cancellation included, so the connection never reads a row no other reader
can see (review round 3, R3-2; ``test_failed_ledger_write_is_rolled_back``). The lock is
held until that rollback has run, also when the cancelled statement is still queued on
the connection's worker thread (review round 4, R4-1;
``test_a_cancelled_begin_is_rolled_back_after_it_takes_effect``). Every public read takes
the same lock, so a read on this connection never sees a write that is not yet committed
or is about to be rolled back (review round 5, R5-1;
``test_every_public_ledger_read_waits_for_an_in_flight_write``). These hold while cleanup
succeeds: a ``ROLLBACK`` that itself fails leaves the transaction open, and every read on
this connection may then return its uncommitted rows until the store restarts (an accepted
residual that needs a broken connection; review round 6, R6-2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from probos.protocols import DatabaseConnection

logger = logging.getLogger(__name__)

ChallengeStatus = Literal["pending", "promoting", "promoted", "retired"]
ContextSplit = Literal["used", "held_out"]
Side = Literal["champion", "challenger"]
Outcome = Literal["champion", "challenger", "tie", "invalid"]

_STATUSES: frozenset[str] = frozenset({"pending", "promoting", "promoted", "retired"})
_SPLITS: frozenset[str] = frozenset({"used", "held_out"})
_SIDES: frozenset[str] = frozenset({"champion", "challenger"})
_OUTCOMES: frozenset[str] = frozenset({"champion", "challenger", "tie", "invalid"})

MAX_ID_CHARS = 128
MAX_MODEL_CHARS = 256
MAX_EPISODE_IDS = 20
MAX_DECISION_CHARS = 1000
MAX_JUDGEMENTS_BYTES = 8192

_SCHEMA = """
CREATE TABLE IF NOT EXISTS procedure_challenges (
    challenger_id TEXT PRIMARY KEY,
    champion_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'promoting', 'promoted', 'retired')),
    created_at REAL NOT NULL,
    cycles_pending INTEGER NOT NULL DEFAULT 0,
    used_episode_ids TEXT NOT NULL DEFAULT '[]',
    held_out_episode_ids TEXT NOT NULL DEFAULT '[]',
    context_episode_ids TEXT NOT NULL DEFAULT '[]',
    optimizer_tier TEXT NOT NULL DEFAULT '',
    optimizer_model TEXT NOT NULL DEFAULT '',
    decision_reason TEXT NOT NULL DEFAULT '',
    decided_at REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_procedure_challenges_status
    ON procedure_challenges(status, champion_id);

CREATE TABLE IF NOT EXISTS procedure_comparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenger_id TEXT NOT NULL,
    champion_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    split TEXT NOT NULL CHECK (split IN ('used', 'held_out')),
    first_shown TEXT NOT NULL CHECK (first_shown IN ('champion', 'challenger')),
    outcome TEXT NOT NULL CHECK (outcome IN ('champion', 'challenger', 'tie', 'invalid')),
    counted INTEGER NOT NULL CHECK (counted IN (0, 1)),
    judgements TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_procedure_comparisons_challenger
    ON procedure_comparisons(challenger_id);

CREATE TABLE IF NOT EXISTS procedure_challenge_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at REAL NOT NULL,
    judge_calls INTEGER NOT NULL,
    comparisons INTEGER NOT NULL,
    deferred INTEGER NOT NULL,
    promoted INTEGER NOT NULL,
    retired INTEGER NOT NULL
);
"""

_CHALLENGE_COLUMNS = (
    "challenger_id, champion_id, status, created_at, cycles_pending, used_episode_ids, "
    "held_out_episode_ids, context_episode_ids, optimizer_tier, optimizer_model, "
    "decision_reason, decided_at"
)

# A champion's open challengers: what ``pending_count`` reports and ``add_challenger`` caps.
_PENDING_COUNT_SQL = (
    "SELECT COUNT(*) FROM procedure_challenges "
    "WHERE champion_id = ? AND status IN ('pending', 'promoting')"
)


def bounded_text(value: object, limit: int) -> str:
    """AD-1326: ``value`` as text SQLite and a strict UTF-8 encoder accept, at most ``limit`` characters.

    NUL characters are removed and a lone surrogate (what a provider's JSON
    ``\\ud800`` escape decodes to, which ``json.loads`` lets through) becomes ``?``,
    so the result can be bound, ``json.dumps``-ed and ``.encode("utf-8")``-ed. A
    value that is not exactly a ``str``, or a ``limit`` below 1, gives ``""``.
    """
    if type(value) is not str or limit < 1:
        return ""
    cleaned = value.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")
    return cleaned[:limit]


def _checked_id(value: object, what: str) -> str:
    if type(value) is not str or not value or bounded_text(value, MAX_ID_CHARS) != value:
        raise ValueError(f"procedure_challenge_{what}_invalid")
    return value


def _checked_ids(values: object, what: str) -> list[str]:
    if type(values) not in (list, tuple):
        raise ValueError(f"procedure_challenge_{what}_invalid")
    ids = [_checked_id(value, what) for value in values]  # type: ignore[union-attr]
    if len(ids) > MAX_EPISODE_IDS or len(set(ids)) != len(ids):
        raise ValueError(f"procedure_challenge_{what}_invalid")
    return ids


async def _roll_back(db: DatabaseConnection) -> None:
    """``ROLLBACK`` on ``db``; a failure other than "nothing to undo" is logged at ERROR.

    SQLite refuses a ``ROLLBACK`` when no transaction is open ("cannot rollback - no
    transaction is active"). For a ledger write that means the goal already holds: a
    cancelled ``BEGIN IMMEDIATE`` that then failed on the busy timeout, or a cancelled
    ``COMMIT`` that the worker thread still completed (review round 4, R4-1). Neither is logged.
    """
    try:
        await db.execute("ROLLBACK")
    except Exception as exc:
        if "no transaction is active" in str(exc):
            return
        # Propagate (the original error): this log is the only trace of the open transaction.
        logger.error(
            "AD-1326: a failed procedure challenger ledger write could not be rolled back; "
            "a transaction left open makes the ledger refuse further writes until the procedure store restarts",
            exc_info=True,
        )


@asynccontextmanager
async def _write_transaction(
    lock: asyncio.Lock, connect: Callable[[], DatabaseConnection],
) -> AsyncIterator[DatabaseConnection]:
    """One ledger write: under ``lock``, ``BEGIN IMMEDIATE``, the caller's statements, ``commit``.

    Any failure after ``BEGIN`` -- a statement, the commit, or a cancellation -- is rolled
    back under the same lock before it propagates. Left open, the transaction would let this
    connection read its own uncommitted row while every other reader sees the old one, and a
    later cycle would skip the durable transition it never made (review round 3, R3-2). A
    rollback that itself fails is logged at ERROR and the original error propagates; the next
    write's ``BEGIN IMMEDIATE`` then fails if that transaction is still open, so nothing is built on it.

    Cancelling a call does not withdraw it: aiosqlite runs one connection's calls in order on
    one worker thread, so a ``BEGIN`` cancelled while it waited for another connection's lock
    can still take effect, and a cancelled ``COMMIT`` can still commit. Only a ``BEGIN`` answered
    with an error opened nothing; on every other failure the ``ROLLBACK`` is queued behind the
    cancelled call, and the lock is held, through further cancellations, until it has run
    (review round 4, R4-1). The wait is governed by SQLite's busy handler (``busy_timeout``, set in
    ``start``): a budget for retrying a locked database, not a wall-clock ceiling, so the measured
    wait can exceed it (review round 5, R5-3). The cleanup is deliberately not time-limited:
    abandoning it would leave the transaction open. A cancellation that arrives during that wait is
    delivered afterwards.
    """
    async with lock:
        db = connect()
        begin_refused = False
        try:
            try:
                await db.execute("BEGIN IMMEDIATE")
            except Exception:
                # SQLite answered the BEGIN with an error, so no transaction was opened.
                begin_refused = True
                raise
            yield db
            await db.commit()
        except BaseException as exc:
            if begin_refused:
                raise
            cleanup = asyncio.create_task(_roll_back(db))
            cancelled_again = False
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    cancelled_again = True
            if cancelled_again and not isinstance(exc, asyncio.CancelledError):
                raise asyncio.CancelledError() from exc
            raise


@dataclass(frozen=True)
class ChallengeRecord:
    """One challenger and the champion it challenges (a ``procedure_challenges`` row)."""

    challenger_id: str
    champion_id: str
    status: ChallengeStatus
    created_at: float
    cycles_pending: int
    used_episode_ids: tuple[str, ...]
    held_out_episode_ids: tuple[str, ...]
    context_episode_ids: tuple[str, ...]
    optimizer_tier: str
    optimizer_model: str
    decision_reason: str
    decided_at: float

    @property
    def bars_routing(self) -> bool:
        """Whether this challenger must not route whatever ``procedures.db`` says: undecided or lost.

        ``ProcedureStore`` admits a match through this (review round 3, R3-5), so, while the ledger
        is open and readable, a restore that pairs a ``pending`` row with an active challenger does
        not route it -- unless ``procedures.db`` already holds that challenger's completed promotion
        (review round 4, R4-2; ``ProcedureStore._get_index_row``).
        """
        return self.status in ("pending", "retired")


@dataclass(frozen=True)
class ComparisonRecord:
    """One situation judged in both orders (a ``procedure_comparisons`` row)."""

    challenger_id: str
    champion_id: str
    episode_id: str
    split: ContextSplit
    first_shown: Side
    outcome: Outcome
    counted: bool
    judgements: tuple[dict[str, Any], ...]
    created_at: float


def _challenge_from_row(row: Sequence[Any]) -> ChallengeRecord:
    return ChallengeRecord(
        challenger_id=row[0],
        champion_id=row[1],
        status=row[2],
        created_at=float(row[3]),
        cycles_pending=int(row[4]),
        used_episode_ids=tuple(json.loads(row[5])),
        held_out_episode_ids=tuple(json.loads(row[6])),
        context_episode_ids=tuple(json.loads(row[7])),
        optimizer_tier=row[8],
        optimizer_model=row[9],
        decision_reason=row[10],
        decided_at=float(row[11]),
    )


class ProcedureChallengeLedger:
    """AD-1326: procedure challengers, their comparisons and per-cycle budget use."""

    def __init__(
        self,
        connection: DatabaseConnection,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """``connection`` is open and owned by the caller (``ProcedureStore``), which closes it."""
        if connection is None:
            raise ValueError("procedure_challenge_connection_missing")
        self._connection = connection
        self._db: DatabaseConnection | None = None
        self._lock = asyncio.Lock()
        self._clock = clock

    async def start(self) -> None:
        """Apply the schema on the owner's connection; a failure propagates and the owner closes it."""
        db = self._connection
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.executescript(_SCHEMA)
        await db.commit()
        self._db = db

    def detach(self) -> None:
        """Stop using the connection (its owner closes it); every later call raises ``RuntimeError``."""
        self._db = None

    def _conn(self) -> DatabaseConnection:
        if self._db is None:
            raise RuntimeError("procedure challenge ledger is not started")
        return self._db

    async def add_challenger(
        self,
        *,
        challenger_id: str,
        champion_id: str,
        used_episode_ids: Sequence[str],
        held_out_episode_ids: Sequence[str],
        context_episode_ids: Sequence[str],
        optimizer_tier: str = "",
        optimizer_model: str = "",
        max_pending: int | None = None,
    ) -> ChallengeRecord:
        """Record a new challenger, ``pending``; a duplicate id raises (the PRIMARY KEY).

        With ``max_pending``, counting the champion's ``pending``/``promoting`` challengers
        and the insert run under one lock, so overlapping submits cannot pass the cap: a
        challenger that would exceed it is recorded ``retired`` with reason
        ``pending_limit`` instead, so the inactive procedure row it names stays accounted
        for (``test_add_challenger_enforces_the_pending_cap_atomically``).
        """
        challenger = _checked_id(challenger_id, "challenger_id")
        champion = _checked_id(champion_id, "champion_id")
        if challenger == champion:
            raise ValueError("procedure_challenge_self_challenge")
        used = _checked_ids(used_episode_ids, "episode_ids")
        held_out = _checked_ids(held_out_episode_ids, "episode_ids")
        contexts = _checked_ids(context_episode_ids, "episode_ids")
        if set(used) & set(held_out) or not set(contexts) <= set(used) | set(held_out):
            raise ValueError("procedure_challenge_episode_ids_invalid")
        if max_pending is not None and (type(max_pending) is not int or max_pending < 1):
            raise ValueError("procedure_challenge_max_pending_invalid")
        tier = bounded_text(optimizer_tier, MAX_ID_CHARS)
        model = bounded_text(optimizer_model, MAX_MODEL_CHARS)
        now = self._clock()
        status: ChallengeStatus = "pending"
        reason = ""
        decided_at = 0.0
        async with _write_transaction(self._lock, self._conn) as db:
            if max_pending is not None:
                cursor = await db.execute(_PENDING_COUNT_SQL, (champion,))
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
                if count >= max_pending:
                    status, reason, decided_at = "retired", f"pending_limit: pending={count} max={max_pending}", now
            await db.execute(
                f"INSERT INTO procedure_challenges ({_CHALLENGE_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    challenger, champion, status, now, 0, json.dumps(used), json.dumps(held_out),
                    json.dumps(contexts), tier, model, reason, decided_at,
                ),
            )
        return ChallengeRecord(
            challenger, champion, status, now, 0, tuple(used), tuple(held_out), tuple(contexts),
            tier, model, reason, decided_at,
        )

    async def get(self, challenger_id: str) -> ChallengeRecord | None:
        """The committed row of ``challenger_id``; routing admission reads it (``ProcedureStore._get_index_row``).

        Committed while every rollback succeeds; after a ``ROLLBACK`` that itself failed, the open
        transaction's row (review round 6, R6-2).
        """
        async with self._lock:  # R5-1 (get): committed rows while cleanup succeeds
            cursor = await self._conn().execute(
                f"SELECT {_CHALLENGE_COLUMNS} FROM procedure_challenges WHERE challenger_id = ?",
                (challenger_id,),
            )
            row = await cursor.fetchone()
        return _challenge_from_row(row) if row else None

    async def list_by_status(self, status: ChallengeStatus) -> list[ChallengeRecord]:
        """Challengers in ``status``, oldest first (ties by id)."""
        if status not in _STATUSES:
            raise ValueError("procedure_challenge_status_invalid")
        async with self._lock:  # R5-1 (list_by_status)
            cursor = await self._conn().execute(
                f"SELECT {_CHALLENGE_COLUMNS} FROM procedure_challenges WHERE status = ? "
                "ORDER BY created_at, challenger_id",
                (status,),
            )
            rows = await cursor.fetchall()
        return [_challenge_from_row(row) for row in rows]

    async def pending_count(self, champion_id: str) -> int:
        """Challengers of ``champion_id`` that are ``pending`` or ``promoting``."""
        async with self._lock:  # R5-1 (pending_count)
            cursor = await self._conn().execute(_PENDING_COUNT_SQL, (champion_id,))
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def record_comparison(
        self,
        *,
        challenger_id: str,
        champion_id: str,
        episode_id: str,
        split: ContextSplit,
        first_shown: Side,
        outcome: Outcome,
        counted: bool,
        judgements: Sequence[dict[str, Any]],
    ) -> None:
        """Record one situation judged in both orders. An ``invalid`` outcome is never counted."""
        if split not in _SPLITS or first_shown not in _SIDES or outcome not in _OUTCOMES:
            raise ValueError("procedure_comparison_invalid")
        if type(counted) is not bool or (counted and outcome == "invalid"):
            raise ValueError("procedure_comparison_invalid")
        payload = json.dumps(list(judgements), ensure_ascii=False, sort_keys=True)
        # Strict encode: a lone surrogate raises UnicodeEncodeError (a ValueError).
        if len(payload.encode("utf-8")) > MAX_JUDGEMENTS_BYTES:
            raise ValueError("procedure_comparison_judgements_too_large")
        values = (
            _checked_id(challenger_id, "challenger_id"),
            _checked_id(champion_id, "champion_id"),
            _checked_id(episode_id, "episode_id"),
            split, first_shown, outcome, int(counted), payload, self._clock(),
        )
        async with _write_transaction(self._lock, self._conn) as db:
            await db.execute(
                "INSERT INTO procedure_comparisons (challenger_id, champion_id, episode_id, split, "
                "first_shown, outcome, counted, judgements, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )

    async def comparisons(self, challenger_id: str) -> list[ComparisonRecord]:
        """Every comparison of ``challenger_id``, in the order recorded."""
        async with self._lock:  # R5-1 (comparisons)
            cursor = await self._conn().execute(
                "SELECT challenger_id, champion_id, episode_id, split, first_shown, outcome, counted, "
                "judgements, created_at FROM procedure_comparisons WHERE challenger_id = ? ORDER BY id",
                (challenger_id,),
            )
            rows = await cursor.fetchall()
        return [
            ComparisonRecord(
                row[0], row[1], row[2], row[3], row[4], row[5], bool(row[6]),
                tuple(json.loads(row[7])), float(row[8]),
            )
            for row in rows
        ]

    async def set_status(
        self,
        challenger_id: str,
        status: ChallengeStatus,
        *,
        reason: str,
        expected: Sequence[ChallengeStatus],
    ) -> bool:
        """Move a challenger from one of ``expected`` to ``status``; False when it was in none of them."""
        if status not in _STATUSES or not expected or any(item not in _STATUSES for item in expected):
            raise ValueError("procedure_challenge_status_invalid")
        marks = ", ".join("?" for _ in expected)
        async with _write_transaction(self._lock, self._conn) as db:
            cursor = await db.execute(
                "UPDATE procedure_challenges SET status = ?, decision_reason = ?, decided_at = ? "
                f"WHERE challenger_id = ? AND status IN ({marks})",
                (status, bounded_text(reason, MAX_DECISION_CHARS), self._clock(), challenger_id, *expected),
            )
            changed = cursor.rowcount == 1
        return changed

    async def increment_cycles(self, challenger_id: str) -> int:
        """Add one to a ``pending`` challenger's ``cycles_pending``; return the stored value."""
        async with _write_transaction(self._lock, self._conn) as db:
            await db.execute(
                "UPDATE procedure_challenges SET cycles_pending = cycles_pending + 1 "
                "WHERE challenger_id = ? AND status = 'pending'",
                (challenger_id,),
            )
            cursor = await db.execute(
                "SELECT cycles_pending FROM procedure_challenges WHERE challenger_id = ?",
                (challenger_id,),
            )
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def record_cycle(
        self, *, judge_calls: int, comparisons: int, deferred: int, promoted: int, retired: int,
    ) -> None:
        values = (judge_calls, comparisons, deferred, promoted, retired)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("procedure_challenge_cycle_invalid")
        async with _write_transaction(self._lock, self._conn) as db:
            await db.execute(
                "INSERT INTO procedure_challenge_cycles (recorded_at, judge_calls, comparisons, deferred, "
                "promoted, retired) VALUES (?, ?, ?, ?, ?, ?)",
                (self._clock(), *values),
            )

    async def recent_cycles(self, limit: int = 20) -> list[dict[str, Any]]:
        """The newest ``limit`` cycle rows, newest first."""
        async with self._lock:  # R5-1 (recent_cycles)
            cursor = await self._conn().execute(
                "SELECT recorded_at, judge_calls, comparisons, deferred, promoted, retired "
                "FROM procedure_challenge_cycles ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            )
            rows = await cursor.fetchall()
        keys = ("recorded_at", "judge_calls", "comparisons", "deferred", "promoted", "retired")
        return [dict(zip(keys, row)) for row in rows]
