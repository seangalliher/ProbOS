"""AD-1286: ElasticTeamStore -- insert-only persistence for team specs, slots, attempts and outcomes.

Immutability is enforced by the database, not only by this class: twelve triggers
abort, on all four tables, every UPDATE, every DELETE and every INSERT that would
replace an existing row (REPLACE / INSERT OR REPLACE), including a replace through
a secondary unique key. REPLACE deletes the conflicting row without firing DELETE
triggers unless ``recursive_triggers`` is ON (default OFF), so the BEFORE INSERT
guards are what close it; nothing relies on that pragma. The four tables are
``WITHOUT ROWID``, so no implicit rowid exists to replace a row through (SQLite itself
refuses an INSERT OR REPLACE that names ``rowid``). This class itself only
issues plain INSERTs after explicit read-then-insert checks under its lock, never
INSERT OR REPLACE, INSERT OR IGNORE or ON CONFLICT. A spec is stored as its RFC 8785
canonical bytes and re-verified against its content identity on every read.
An attempt is admitted only for a declared slot of a stored spec -- the canonical spec is
loaded and verified inside the transaction and the slot row's cached columns must match
it -- in contiguous ordinal order (the recorded ordinals must be exactly 1..n), within the
slot's ``budget.max_attempts``, against a pinned execution profile when the slot pins any,
and -- when it replaces another attempt -- only for a digest-verified predecessor with a
recorded failed/cancelled outcome that no other attempt has already replaced. Every
operation uses its own connection, serialised in-process by one lock, so a failed, cancelled
or un-closable write's uncommitted rows are never visible to any other operation (SQLite never
shows one connection another's uncommitted rows). A connection whose close fails or stalls is
tracked and reported, never reused, and ``stop()`` waits a bounded time for outstanding closes.
The store never admits, acknowledges or returns from a stored row it cannot verify: the catalog
columns must match the canonical spec, every attempt row of a slot's history, an existing attempt
and a predecessor are digest-verified, and every outcome row is shape-verified (an unverifiable row
is an integrity error; refusing on one is fine, relying on one is not).
The store does not validate session
membership: it cannot know that ``session_id`` names a CrewSession that bound
``team_spec_ref`` (that fact lives in the work-item store, with no cross-store
transaction). AD-1288's commission admission must check
``CrewSessionService.get_team_binding(session_id)`` against the spec before it
records an attempt. Nothing here provisions, ranks or schedules (AD-1288/AD-1290).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from probos.cognitive.elastic_team import (
    ElasticTeamSpec,
    WorkerAttempt,
    WorkerAttemptOutcome,
    canonicalize_projection,
    is_sha256_ref,
)
from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS elastic_team_specs (
    spec_ref TEXT PRIMARY KEY CHECK (length(spec_ref) = 64),
    team_id TEXT NOT NULL CHECK (length(team_id) BETWEEN 1 AND 128),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    canonical_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (team_id, revision)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS elastic_worker_slots (
    spec_ref TEXT NOT NULL REFERENCES elastic_team_specs (spec_ref),
    slot_id TEXT NOT NULL CHECK (length(slot_id) BETWEEN 1 AND 128),
    slot_digest TEXT NOT NULL CHECK (length(slot_digest) = 64),
    max_attempts INTEGER NOT NULL CHECK (max_attempts BETWEEN 1 AND 1024),
    pinned_profile_refs TEXT NOT NULL,
    PRIMARY KEY (spec_ref, slot_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS elastic_worker_attempts (
    worker_attempt_id TEXT PRIMARY KEY CHECK (length(worker_attempt_id) = 67),
    spec_ref TEXT NOT NULL,
    session_id TEXT NOT NULL CHECK (length(session_id) BETWEEN 1 AND 128),
    slot_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 1 AND 1024),
    execution_profile_ref TEXT NOT NULL CHECK (length(execution_profile_ref) = 64),
    supersedes_attempt_id TEXT REFERENCES elastic_worker_attempts (worker_attempt_id),
    attempt_digest TEXT NOT NULL CHECK (length(attempt_digest) = 64),
    created_at REAL NOT NULL,
    FOREIGN KEY (spec_ref, slot_id) REFERENCES elastic_worker_slots (spec_ref, slot_id),
    UNIQUE (session_id, spec_ref, slot_id, ordinal)
) WITHOUT ROWID;
CREATE UNIQUE INDEX IF NOT EXISTS elastic_worker_attempts_one_successor
    ON elastic_worker_attempts (supersedes_attempt_id) WHERE supersedes_attempt_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS elastic_attempt_outcomes (
    worker_attempt_id TEXT PRIMARY KEY REFERENCES elastic_worker_attempts (worker_attempt_id),
    terminal_status TEXT NOT NULL CHECK (terminal_status IN ('succeeded', 'failed', 'cancelled')),
    error_code TEXT,
    recorded_at REAL NOT NULL
) WITHOUT ROWID;
CREATE TRIGGER IF NOT EXISTS elastic_team_specs_no_update BEFORE UPDATE ON elastic_team_specs
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_team_specs_no_delete BEFORE DELETE ON elastic_team_specs
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_worker_slots_no_update BEFORE UPDATE ON elastic_worker_slots
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_worker_slots_no_delete BEFORE DELETE ON elastic_worker_slots
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_worker_attempts_no_update BEFORE UPDATE ON elastic_worker_attempts
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_worker_attempts_no_delete BEFORE DELETE ON elastic_worker_attempts
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_attempt_outcomes_no_update BEFORE UPDATE ON elastic_attempt_outcomes
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_attempt_outcomes_no_delete BEFORE DELETE ON elastic_attempt_outcomes
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_team_specs_no_replace BEFORE INSERT ON elastic_team_specs
WHEN EXISTS (SELECT 1 FROM elastic_team_specs WHERE spec_ref = NEW.spec_ref
             OR (team_id = NEW.team_id AND revision = NEW.revision))
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_worker_slots_no_replace BEFORE INSERT ON elastic_worker_slots
WHEN EXISTS (SELECT 1 FROM elastic_worker_slots WHERE spec_ref = NEW.spec_ref AND slot_id = NEW.slot_id)
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_worker_attempts_no_replace BEFORE INSERT ON elastic_worker_attempts
WHEN EXISTS (SELECT 1 FROM elastic_worker_attempts WHERE worker_attempt_id = NEW.worker_attempt_id
             OR (session_id = NEW.session_id AND spec_ref = NEW.spec_ref AND slot_id = NEW.slot_id
                 AND ordinal = NEW.ordinal)
             OR (NEW.supersedes_attempt_id IS NOT NULL AND supersedes_attempt_id = NEW.supersedes_attempt_id))
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_attempt_outcomes_no_replace BEFORE INSERT ON elastic_attempt_outcomes
WHEN EXISTS (SELECT 1 FROM elastic_attempt_outcomes WHERE worker_attempt_id = NEW.worker_attempt_id)
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
"""

_ATTEMPT_COLUMNS = (
    "worker_attempt_id, spec_ref, session_id, slot_id, ordinal, execution_profile_ref, "
    "supersedes_attempt_id, attempt_digest"
)
_OUTCOME_COLUMNS = "worker_attempt_id, terminal_status, error_code, recorded_at"
_SPEC_COLUMNS = "spec_ref, team_id, revision, schema_version, canonical_json"
_MAX_LISTED_ATTEMPTS = 1_024
_MAX_ID_LENGTH = 128
_CLOSE_WAIT_SECONDS = 5.0  # how long an operation waits for its own connection to close before moving on
_STOP_CLOSE_WAIT_SECONDS = 5.0  # how long stop() waits for the connection closes still outstanding


class ElasticTeamStoreUnavailable(RuntimeError):
    """The store has not been started, or has stopped."""


class ElasticTeamConflict(ValueError):
    """A write that would contradict an immutable record. ``str(exc)`` is the stable code."""


class ElasticTeamIntegrityError(ValueError):
    """A stored row no longer matches its content identity (data integrity: propagate)."""


def _checked_now(clock: Callable[[], float]) -> float:
    """The store's "now" as a finite float, or ``ElasticTeamStoreUnavailable`` when the clock is not one.

    A NaN or infinite ``created_at`` would be written into an insert-only table and could never
    be corrected, so a bad clock refuses the write instead.
    """
    now = clock()
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ElasticTeamStoreUnavailable("elastic_team_clock_invalid")
    return float(now)


def _is_no_transaction(exc: BaseException) -> bool:
    """True only for SQLite's benign "ROLLBACK with no transaction open" error, and nothing else.

    Any other failed ROLLBACK is reported at WARNING; the connection is discarded either way.
    """
    return isinstance(exc, sqlite3.OperationalError) and str(exc) == "cannot rollback - no transaction is active"


def _is_private_memory_path(db_path: str) -> bool:
    """True for SQLite's per-connection in-memory database, which vanishes when its one connection closes.

    The store opens and closes one connection per operation, so such a database would be created empty
    again by every operation: ``start()`` would succeed and every real operation would then fail. Only the
    exact name ``:memory:`` is special: the default factory hands the string to SQLite without ``uri=True``,
    so ``file:...?mode=memory`` forms and names that merely contain ``memory`` are ordinary file names, and
    refusing them would reject a legitimate data directory.
    """
    return db_path == ":memory:"


async def _apply_connection_pragmas(db: Any) -> None:
    """The settings SQLite keeps per connection, so every connection the store opens must set them itself."""
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA foreign_keys=ON")


async def _rollback(db: Any) -> None:
    """Undo an uncommitted write on ``db``; the caller then re-raises its ORIGINAL error.

    This never decides availability: ``_connection`` discards the connection in every case, which
    discards the uncommitted work too, and no other connection ever saw it. SQLite's "no transaction
    is active" is benign (debug); any other failure is a WARNING. A ``CancelledError`` always propagates.
    """
    try:
        await db.execute("ROLLBACK")
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 -- classified just below; the connection is discarded either way
        if _is_no_transaction(exc):
            logger.debug(
                "AD-1286: rollback after a failed elastic team write found no open "
                "transaction; the original error is re-raised unchanged"
            )
            return
        logger.warning(
            "AD-1286: rollback after a failed elastic team write also failed (%s); the connection is being "
            "closed, which discards the uncommitted work, and no other connection ever saw it",
            exc,
            exc_info=True,
        )


def _report_close_outcome(task: asyncio.Task[None]) -> None:
    """Done-callback of a connection-close task: say so when the close failed or was cancelled.

    Reading the outcome here also retrieves the exception, so a failed close is never an unretrieved
    task exception. A close that finished cleanly logs nothing, and nothing ever claims one that did not.
    """
    if task.cancelled():
        logger.error(
            "AD-1286: closing an elastic team connection was cancelled before it finished; any uncommitted "
            "work on it was never visible to other connections, but it may hold the write lock until the "
            "connection is released, so later writes can fail as 'database is locked'"
        )
        return
    failure = task.exception()
    if failure is not None:
        logger.error(
            "AD-1286: closing an elastic team connection failed (%s); any uncommitted work on it was never "
            "visible to other connections and is discarded when the connection is released, but it may hold "
            "the write lock until then, so later writes can fail as 'database is locked'",
            failure,
            exc_info=failure,
        )


async def _query(db: Any, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    """Run one read and return every row. Rows are indexed positionally by every caller."""
    cursor = await db.execute(sql, params)
    return list(await cursor.fetchall())


def _is_query_id(value: object) -> bool:
    return type(value) is str and 1 <= len(value) <= _MAX_ID_LENGTH


def _pinned_refs(stored: Any) -> tuple[str, ...]:
    """The slot's pinned execution-profile refs from their stored JSON text (data integrity: propagate)."""
    try:
        refs = json.loads(stored)
    except (TypeError, ValueError):
        refs = None
    if type(refs) is not list or not all(is_sha256_ref(ref) for ref in refs):
        logger.error(
            "AD-1286: a stored slot's pinned profile list is not a list of sha256 references; "
            "refusing to admit an attempt against it, because admission cannot tell which profiles are pinned"
        )
        raise ElasticTeamIntegrityError("elastic_team_spec_integrity")
    return tuple(refs)


def _attempt_from_row(row: Any) -> WorkerAttempt:
    """Rebuild an attempt from ``_ATTEMPT_COLUMNS`` and verify it against its stored digest."""
    try:
        attempt = WorkerAttempt(
            schema_version=1,
            worker_attempt_id=row[0],
            team_spec_ref=row[1],
            session_id=row[2],
            slot_id=row[3],
            ordinal=row[4],
            execution_profile_ref=row[5],
            supersedes_attempt_id=row[6],
        )
        verified = attempt.content_ref() == row[7]
    except ValueError:
        verified = False
    if not verified:
        logger.error(
            "AD-1286: stored worker attempt %s no longer matches its content identity; refusing to "
            "return it, so no caller acts on a tampered attempt record",
            str(row[0])[:70],
        )
        raise ElasticTeamIntegrityError("elastic_attempt_integrity")
    return attempt


def _outcome_from_row(row: Any) -> WorkerAttemptOutcome:
    """Rebuild an outcome from ``_OUTCOME_COLUMNS``."""
    return WorkerAttemptOutcome(
        worker_attempt_id=row[0],
        terminal_status=row[1],
        error_code=row[2],
        recorded_at=row[3],
    )


def _verified_outcome(row: Any) -> WorkerAttemptOutcome:
    """Rebuild an outcome from ``_OUTCOME_COLUMNS`` and refuse a row that no longer validates (data integrity).

    An outcome carries no digest, so what can be verified is its shape: a status/code combination or a
    timestamp no ``WorkerAttemptOutcome`` could have been built with means the row was written around the store.
    """
    try:
        return _outcome_from_row(row)
    except ValueError:  # includes pydantic.ValidationError
        logger.error(
            "AD-1286: the stored outcome of worker attempt %s no longer validates as an outcome; refusing to "
            "acknowledge or act on it, because it can only have been written around the store",
            str(row[0])[:70],
        )
        raise ElasticTeamIntegrityError("elastic_attempt_outcome_integrity") from None


def _verified_spec(stored: str, team_spec_ref: str) -> ElasticTeamSpec:
    """Parse a stored canonical spec and verify it against the reference it is stored under.

    Raises ``ElasticTeamIntegrityError("elastic_team_spec_integrity")`` after an ERROR log when the text
    does not parse, no longer validates, hashes to another reference, or is not byte-for-byte canonical
    (data integrity: propagate).
    """
    try:
        spec = ElasticTeamSpec.model_validate(json.loads(stored))
        verified = spec.content_ref() == team_spec_ref and spec.canonical_bytes().decode("utf-8") == stored
    except (TypeError, ValueError):
        verified = False
    if not verified:
        logger.error(
            "AD-1286: stored team spec %s no longer matches its content identity; refusing to "
            "return it, so no session binds or runs against a tampered recipe",
            team_spec_ref,
        )
        raise ElasticTeamIntegrityError("elastic_team_spec_integrity")
    return spec


def _verified_spec_row(row: Any) -> ElasticTeamSpec:
    """Verify one ``_SPEC_COLUMNS`` row: its canonical text AND the catalog columns cached beside it.

    The text must verify against the reference it is stored under (``_verified_spec``), and the cached
    ``team_id``, ``revision`` and ``schema_version`` must equal what that spec says: ``put_team_spec`` decides
    revision conflicts from them, so a row whose catalog drifted from its content is refused, not trusted.
    """
    spec = _verified_spec(row[4], row[0])
    if (row[1], row[2], row[3]) != (spec.team_id, spec.revision, spec.schema_version):
        logger.error(
            "AD-1286: the catalog columns of stored team spec %s (team=%s revision=%s schema=%s) disagree with its "
            "canonical content (team=%s revision=%d schema=%d); refusing to use the row, because a revision "
            "decision would rest on a cached value that does not match the spec",
            row[0],
            row[1],
            row[2],
            row[3],
            spec.team_id,
            spec.revision,
            spec.schema_version,
        )
        raise ElasticTeamIntegrityError("elastic_team_spec_integrity")
    return spec


async def _load_verified_spec(db: Any, team_spec_ref: str) -> ElasticTeamSpec | None:
    """The spec stored under ``team_spec_ref``, verified, or None. Uses the open ``db``; never takes the lock."""
    rows = await _query(db, f"SELECT {_SPEC_COLUMNS} FROM elastic_team_specs WHERE spec_ref = ?", (team_spec_ref,))
    return _verified_spec_row(rows[0]) if rows else None


async def _require_contiguous_ordinals(db: Any, attempt: WorkerAttempt) -> int:
    """How many attempts the session holds for the slot, after verifying each one and proving the ordinals are 1..n."""
    rows = await _query(
        db,
        f"SELECT {_ATTEMPT_COLUMNS} FROM elastic_worker_attempts WHERE session_id = ? AND spec_ref = ? AND slot_id = ? "
        "ORDER BY ordinal",
        (attempt.session_id, attempt.team_spec_ref, attempt.slot_id),
    )
    ordinals = [_attempt_from_row(row).ordinal for row in rows]  # each row is digest-verified before it is counted
    if ordinals != list(range(1, len(ordinals) + 1)):
        logger.error(
            "AD-1286: the %d recorded attempts of slot %s in session %s are not numbered 1..n; refusing to "
            "admit another, because the next ordinal cannot be derived from a gapped or duplicated history",
            len(ordinals),
            attempt.slot_id,
            attempt.session_id,
        )
        raise ElasticTeamIntegrityError("elastic_attempt_integrity")
    return len(ordinals)


class ElasticTeamStore:
    """Insert-only team specs, slots, worker attempts and attempt outcomes.

    Public API:
        start() / stop() -- lifecycle (one connection per operation, serialised in-process by one lock;
            uncommitted work is never visible to another operation)
        put_team_spec(spec) -> spec_ref -- idempotent; one content digest per (team_id, revision)
        get_team_spec(ref) -> ElasticTeamSpec | None -- integrity-verified; satisfies ``TeamSpecLookup``
        record_attempt(attempt) -> WorkerAttempt -- admission-checked and idempotent
        get_attempt(id) / list_slot_attempts(...) -- integrity-verified reads
        record_attempt_outcome(outcome) -> WorkerAttemptOutcome -- write-once
        get_attempt_outcome(id) -> WorkerAttemptOutcome | None -- shape-verified

    Raises:
        ElasticTeamStoreUnavailable: not started, stopped, or a clock that is not a finite real.
        ElasticTeamConflict: a write that contradicts an immutable record; ``str(exc)`` is the code.
        ElasticTeamIntegrityError: a stored row no longer matches its content identity
            (``elastic_team_spec_integrity``, ``elastic_attempt_integrity``) or no longer validates as an
            outcome (``elastic_attempt_outcome_integrity``).
    """

    def __init__(
        self,
        db_path: str,
        connection_factory: ConnectionFactory | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Construct the store; nothing is opened until :meth:`start`.

        Args:
            db_path: SQLite path to a file (``elastic_teams.db`` under the data directory in production). A
                private in-memory database (``:memory:``) is refused: every operation opens its own connection,
                so it would be a different, empty database each time.
            connection_factory: injected per the Cloud-Ready Storage rule; the default SQLite
                factory is imported lazily.
            clock: the single source of ``created_at``.
        """
        if type(db_path) is not str or not db_path or _is_private_memory_path(db_path):
            raise ValueError("elastic_team_store_path_invalid")
        self._db_path = db_path
        self._started = False
        self._closing: set[asyncio.Task[None]] = set()
        self._clock = clock
        self._lock = asyncio.Lock()
        if connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            connection_factory = default_factory
        self._connection_factory: ConnectionFactory = connection_factory

    async def start(self) -> None:
        """Probe the database, apply the schema, then admit operations. Idempotent.

        The probe connection's close is requested, tracked and waited for a bounded time before this
        returns; a close that stalls stays tracked and ``stop()`` waits for it. A failure to open the
        database, probe it or apply the schema leaves the store stopped and propagates unchanged -- a
        file that is not a database raises ``sqlite3.DatabaseError``. A failed close is not such a
        failure: the close callback reports it and the store still starts, because the probe's work was
        committed before the close was requested.
        """
        async with self._lock:
            if self._started:
                return
            db = await self._connection_factory.connect(self._db_path)
            try:
                await db.execute("PRAGMA journal_mode=WAL")  # persistent for the file, so set once, here
                await _apply_connection_pragmas(db)
                await db.executescript(_SCHEMA)
                await db.commit()
            finally:
                await self._close(db)
            self._started = True
        logger.info(
            "AD-1286: ElasticTeamStore started (db=%s); specs, slots and attempts are insert-only",
            self._db_path,
        )

    async def stop(self) -> None:
        """Stop admitting operations, wait for any in-flight one (it holds the lock), then wait a
        bounded time for outstanding connection closes. Idempotent.

        The wait for closes happens outside the lock and is bounded by ``_STOP_CLOSE_WAIT_SECONDS``. That is
        the additional wait: taking the lock first waits for any in-flight operation, including that
        operation's own bounded close wait, so ``stop()`` can take up to the two bounds together. A stalled
        close never blocks another operation from being refused.
        """
        async with self._lock:
            was_started, self._started = self._started, False
        if self._closing:
            _, unfinished = await asyncio.wait(set(self._closing), timeout=_STOP_CLOSE_WAIT_SECONDS)
            if unfinished:
                logger.error(
                    "AD-1286: %d elastic team connection(s) did not finish closing within %.1fs; they may "
                    "hold the database write lock until they are released",
                    len(unfinished),
                    _STOP_CLOSE_WAIT_SECONDS,
                )
        if not was_started:
            return
        logger.info(
            "AD-1286: ElasticTeamStore stopped (db=%s); operations raise unavailable until it is started again",
            self._db_path,
        )

    @contextlib.asynccontextmanager
    async def _connection(self) -> AsyncIterator[Any]:
        """One connection for one operation: opened with its own pragmas, always closed through ``_close``.

        Another connection never sees this one's uncommitted rows, so a failed, cancelled or un-closable
        write cannot expose partial rows to any later operation: every later operation opens its own.
        """
        if not self._started:
            raise ElasticTeamStoreUnavailable("elastic_team_store_unavailable")
        db = await self._connection_factory.connect(self._db_path)
        try:
            await _apply_connection_pragmas(db)
            yield db
        finally:
            await self._close(db)

    async def _close(self, db: Any) -> None:
        """Close ``db`` in a tracked task and wait a bounded time for it, without ever claiming a close it did not see.

        ``asyncio.wait`` cancels the task neither on timeout nor when this caller is cancelled, so a
        cancelled or stalled operation still finishes closing in the background; the task stays in
        ``_closing`` until it does, and ``stop()`` waits for it. A failed close is logged by the
        done-callback, so this method never raises because of one.
        """
        task = asyncio.create_task(db.close())
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)
        task.add_done_callback(_report_close_outcome)
        done, _ = await asyncio.wait({task}, timeout=_CLOSE_WAIT_SECONDS)
        if not done:
            logger.error(
                "AD-1286: closing an elastic team connection did not finish within %.1fs; it stays tracked "
                "and stop() waits for it",
                _CLOSE_WAIT_SECONDS,
            )

    async def put_team_spec(self, spec: ElasticTeamSpec) -> str:
        """Persist ``spec`` and its slots, returning its content reference.

        Idempotent: the same spec again writes nothing. A different spec for an existing
        ``(team_id, revision)`` is refused -- a change needs a new revision.

        Raises:
            TypeError: ``spec`` is not an ``ElasticTeamSpec``.
            ValueError: (``pydantic.ValidationError``) ``spec`` no longer validates -- it was built
                without validation, e.g. by ``model_copy(update=...)``. Nothing is written.
            ElasticTeamConflict: ``elastic_team_revision_conflict``.
            ElasticTeamIntegrityError: ``elastic_team_spec_integrity`` when a stored row that decides the
                write (the same reference, or the same ``(team_id, revision)``) cannot be verified.
        """
        if type(spec) is not ElasticTeamSpec:
            raise TypeError("elastic_team_spec_type_invalid")
        spec = ElasticTeamSpec.model_validate(spec)  # a model_copy(update=...) skips validation; hash only what validates
        spec_ref = spec.content_ref()
        canonical_json = spec.canonical_bytes().decode("utf-8")
        inserted = False
        async with self._lock:
            now = _checked_now(self._clock)
            async with self._connection() as db:
                try:
                    await db.execute("BEGIN IMMEDIATE")
                    rows = await _query(
                        db,
                        f"SELECT {_SPEC_COLUMNS} FROM elastic_team_specs "
                        "WHERE spec_ref = ? OR (team_id = ? AND revision = ?)",
                        (spec_ref, spec.team_id, spec.revision),
                    )
                    for row in rows:
                        _verified_spec_row(row)  # a row the store cannot read back decides nothing
                    if any(row[0] != spec_ref for row in rows):
                        raise ElasticTeamConflict("elastic_team_revision_conflict")
                    if not rows:
                        await db.execute(
                            "INSERT INTO elastic_team_specs "
                            "(spec_ref, team_id, revision, schema_version, canonical_json, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (spec_ref, spec.team_id, spec.revision, spec.schema_version, canonical_json, now),
                        )
                        for slot in spec.slots:
                            await db.execute(
                                "INSERT INTO elastic_worker_slots "
                                "(spec_ref, slot_id, slot_digest, max_attempts, pinned_profile_refs) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (
                                    spec_ref,
                                    slot.slot_id,
                                    slot.content_ref(),
                                    slot.budget.max_attempts,
                                    canonicalize_projection(
                                        list(slot.qualification.pinned_profile_refs)
                                    ).decode("utf-8"),
                                ),
                            )
                        inserted = True
                    await db.commit()
                except BaseException:
                    await _rollback(db)
                    raise
        if inserted:
            logger.info(
                "AD-1286: stored team spec %s (team=%s revision=%d, %d slots); it is immutable, "
                "so any change needs a new revision",
                spec_ref,
                spec.team_id,
                spec.revision,
                len(spec.slots),
            )
        return spec_ref

    async def get_team_spec(self, team_spec_ref: str) -> ElasticTeamSpec | None:
        """The spec stored under ``team_spec_ref``, re-verified against its content identity, or None.

        Raises:
            ValueError: ``elastic_team_spec_ref_invalid`` for a malformed reference.
            ElasticTeamIntegrityError: ``elastic_team_spec_integrity`` when the stored row no longer
                matches the reference it is stored under, or its cached catalog columns (``team_id``,
                ``revision``, ``schema_version``) no longer match its canonical content.
        """
        if not is_sha256_ref(team_spec_ref):
            raise ValueError("elastic_team_spec_ref_invalid")
        async with self._lock:
            async with self._connection() as db:
                return await _load_verified_spec(db, team_spec_ref)

    async def record_attempt(self, attempt: WorkerAttempt) -> WorkerAttempt:
        """Admit and persist ``attempt``. Idempotent for an identical attempt.

        Raises:
            TypeError: ``attempt`` is not a ``WorkerAttempt``.
            ValueError: (``pydantic.ValidationError``) ``attempt`` no longer validates -- it was built
                without validation, e.g. by ``model_copy(update=...)``. Nothing is written.
            ElasticTeamConflict: ``elastic_attempt_conflict`` (same id, different content), or any
                refusal of :meth:`_admit_attempt`.
            ElasticTeamIntegrityError: ``elastic_attempt_integrity``, ``elastic_team_spec_integrity`` or
                ``elastic_attempt_outcome_integrity`` when a row that decides the admission -- the stored spec
                and its slot, an existing attempt, the slot's history, a predecessor and its outcome -- cannot
                be verified. An identical repeat is acknowledged only from a verified row.
        """
        if type(attempt) is not WorkerAttempt:
            raise TypeError("elastic_attempt_type_invalid")
        attempt = WorkerAttempt.model_validate(attempt)  # a model_copy(update=...) skips validation
        digest = attempt.content_ref()
        inserted = False
        async with self._lock:
            now = _checked_now(self._clock)
            async with self._connection() as db:
                try:
                    await db.execute("BEGIN IMMEDIATE")
                    existing = await _query(
                        db,
                        f"SELECT {_ATTEMPT_COLUMNS} FROM elastic_worker_attempts WHERE worker_attempt_id = ?",
                        (attempt.worker_attempt_id,),
                    )
                    if existing:
                        stored = _attempt_from_row(existing[0])  # a corrupt row is refused, never acknowledged
                        if stored.content_ref() != digest:
                            raise ElasticTeamConflict("elastic_attempt_conflict")
                    else:
                        await self._admit_attempt(db, attempt)
                        await db.execute(
                            "INSERT INTO elastic_worker_attempts "
                            "(worker_attempt_id, spec_ref, session_id, slot_id, ordinal, execution_profile_ref, "
                            "supersedes_attempt_id, attempt_digest, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                attempt.worker_attempt_id,
                                attempt.team_spec_ref,
                                attempt.session_id,
                                attempt.slot_id,
                                attempt.ordinal,
                                attempt.execution_profile_ref,
                                attempt.supersedes_attempt_id,
                                digest,
                                now,
                            ),
                        )
                        inserted = True
                    await db.commit()
                except BaseException:
                    await _rollback(db)
                    raise
        if inserted:
            logger.info(
                "AD-1286: recorded worker attempt %s (slot=%s ordinal=%d session=%s); the attempt is "
                "insert-only and its outcome is recorded once when it ends",
                attempt.worker_attempt_id,
                attempt.slot_id,
                attempt.ordinal,
                attempt.session_id,
            )
        return attempt

    async def _admit_attempt(self, db: Any, attempt: WorkerAttempt) -> None:
        """Refuse, with a stable code, an attempt the stored slot does not admit. Writes nothing.

        Everything is decided from rows read inside the caller's open transaction, and the stored spec is
        the authority: the slot row's cached columns are only a projection that must equal it. Checked in
        order: declared slot; verified spec and slot cache; attempt budget; contiguous ordinal history;
        pinned profile; then -- for a replacement -- a digest-verified predecessor of this slot and session
        with a failed/cancelled outcome that no other attempt has already replaced.
        """
        slot_rows = await _query(
            db,
            "SELECT max_attempts, pinned_profile_refs, slot_digest FROM elastic_worker_slots "
            "WHERE spec_ref = ? AND slot_id = ?",
            (attempt.team_spec_ref, attempt.slot_id),
        )
        if not slot_rows:
            raise ElasticTeamConflict("elastic_attempt_slot_unknown")
        max_attempts, pinned_text, slot_digest = slot_rows[0]
        spec = await _load_verified_spec(db, attempt.team_spec_ref)
        slot = spec.slot(attempt.slot_id) if spec is not None else None
        if (
            slot is None
            or slot.content_ref() != slot_digest
            or slot.budget.max_attempts != max_attempts
            or _pinned_refs(pinned_text) != slot.qualification.pinned_profile_refs
        ):
            logger.error(
                "AD-1286: the stored slot %s of team spec %s is not backed by, or no longer matches, its "
                "verified spec; refusing to admit an attempt, because admission would rely on an unverified "
                "budget or profile pin",
                attempt.slot_id,
                attempt.team_spec_ref,
            )
            raise ElasticTeamIntegrityError("elastic_team_spec_integrity")
        if attempt.ordinal > slot.budget.max_attempts:
            raise ElasticTeamConflict("elastic_attempt_budget_exhausted")
        recorded = await _require_contiguous_ordinals(db, attempt)
        if attempt.ordinal != recorded + 1:
            raise ElasticTeamConflict("elastic_attempt_ordinal_invalid")
        pinned = slot.qualification.pinned_profile_refs
        if pinned and attempt.execution_profile_ref not in pinned:
            raise ElasticTeamConflict("elastic_attempt_profile_not_pinned")
        predecessor_id = attempt.supersedes_attempt_id
        if predecessor_id is None:
            return
        predecessor_rows = await _query(
            db,
            f"SELECT {_ATTEMPT_COLUMNS} FROM elastic_worker_attempts WHERE worker_attempt_id = ?",
            (predecessor_id,),
        )
        predecessor = _attempt_from_row(predecessor_rows[0]) if predecessor_rows else None
        if (
            predecessor is None
            or predecessor.session_id != attempt.session_id
            or predecessor.team_spec_ref != attempt.team_spec_ref
            or predecessor.slot_id != attempt.slot_id
            or not predecessor.ordinal < attempt.ordinal
        ):
            raise ElasticTeamConflict("elastic_attempt_supersedes_invalid")
        ended = await _query(
            db,
            f"SELECT {_OUTCOME_COLUMNS} FROM elastic_attempt_outcomes WHERE worker_attempt_id = ?",
            (predecessor_id,),
        )
        predecessor_outcome = _verified_outcome(ended[0]) if ended else None
        if predecessor_outcome is None or predecessor_outcome.terminal_status not in ("failed", "cancelled"):
            raise ElasticTeamConflict("elastic_attempt_supersedes_invalid")
        replaced = await _query(
            db,
            "SELECT 1 FROM elastic_worker_attempts WHERE supersedes_attempt_id = ?",
            (predecessor_id,),
        )
        if replaced:
            raise ElasticTeamConflict("elastic_attempt_already_replaced")

    async def get_attempt(self, worker_attempt_id: str) -> WorkerAttempt | None:
        """The attempt stored under ``worker_attempt_id``, verified against its digest, or None.

        Raises:
            ValueError: ``elastic_attempt_query_invalid`` for a malformed id.
            ElasticTeamIntegrityError: ``elastic_attempt_integrity`` when the row was altered.
        """
        if not _is_query_id(worker_attempt_id):
            raise ValueError("elastic_attempt_query_invalid")
        async with self._lock:
            async with self._connection() as db:
                rows = await _query(
                    db,
                    f"SELECT {_ATTEMPT_COLUMNS} FROM elastic_worker_attempts WHERE worker_attempt_id = ?",
                    (worker_attempt_id,),
                )
        return _attempt_from_row(rows[0]) if rows else None

    async def list_slot_attempts(
        self, *, session_id: str, team_spec_ref: str, slot_id: str,
    ) -> tuple[WorkerAttempt, ...]:
        """Every attempt of one slot in one session, in ordinal order, each verified against its digest.

        Raises:
            ValueError: ``elastic_attempt_query_invalid`` for a malformed argument.
            ElasticTeamIntegrityError: ``elastic_attempt_integrity`` when a row was altered.
        """
        if not (_is_query_id(session_id) and is_sha256_ref(team_spec_ref) and _is_query_id(slot_id)):
            raise ValueError("elastic_attempt_query_invalid")
        async with self._lock:
            async with self._connection() as db:
                rows = await _query(
                    db,
                    f"SELECT {_ATTEMPT_COLUMNS} FROM elastic_worker_attempts "
                    "WHERE session_id = ? AND spec_ref = ? AND slot_id = ? ORDER BY ordinal LIMIT ?",
                    (session_id, team_spec_ref, slot_id, _MAX_LISTED_ATTEMPTS),
                )
        return tuple(_attempt_from_row(row) for row in rows)

    async def record_attempt_outcome(self, outcome: WorkerAttemptOutcome) -> WorkerAttemptOutcome:
        """Record the terminal state of an attempt, once. The first write wins.

        An identical repeat (same status and error code) returns the stored outcome, with the
        first write's ``recorded_at``; a different one is refused.

        Raises:
            TypeError: ``outcome`` is not a ``WorkerAttemptOutcome``.
            ValueError: (``pydantic.ValidationError``) ``outcome`` no longer validates -- it was built
                without validation, e.g. by ``model_copy(update=...)``. Nothing is written.
            ElasticTeamConflict: ``elastic_attempt_unknown`` or ``elastic_attempt_outcome_conflict``.
            ElasticTeamIntegrityError: ``elastic_attempt_integrity`` when the attempt row cannot be
                verified, or ``elastic_attempt_outcome_integrity`` when an existing outcome row no longer
                validates; neither is acknowledged.
        """
        if type(outcome) is not WorkerAttemptOutcome:
            raise TypeError("elastic_attempt_outcome_type_invalid")
        outcome = WorkerAttemptOutcome.model_validate(outcome)  # a model_copy(update=...) skips validation
        result = outcome
        inserted = False
        async with self._lock:
            async with self._connection() as db:
                try:
                    await db.execute("BEGIN IMMEDIATE")
                    known = await _query(
                        db,
                        f"SELECT {_ATTEMPT_COLUMNS} FROM elastic_worker_attempts WHERE worker_attempt_id = ?",
                        (outcome.worker_attempt_id,),
                    )
                    if not known:
                        raise ElasticTeamConflict("elastic_attempt_unknown")
                    _attempt_from_row(known[0])  # no outcome is recorded against an attempt row that cannot be verified
                    rows = await _query(
                        db,
                        f"SELECT {_OUTCOME_COLUMNS} FROM elastic_attempt_outcomes WHERE worker_attempt_id = ?",
                        (outcome.worker_attempt_id,),
                    )
                    if rows:
                        result = _verified_outcome(rows[0])
                        if (result.terminal_status, result.error_code) != (
                            outcome.terminal_status,
                            outcome.error_code,
                        ):
                            raise ElasticTeamConflict("elastic_attempt_outcome_conflict")
                    else:
                        await db.execute(
                            f"INSERT INTO elastic_attempt_outcomes ({_OUTCOME_COLUMNS}) VALUES (?, ?, ?, ?)",
                            (
                                outcome.worker_attempt_id,
                                outcome.terminal_status,
                                outcome.error_code,
                                outcome.recorded_at,
                            ),
                        )
                        inserted = True
                    await db.commit()
                except BaseException:
                    await _rollback(db)
                    raise
        if inserted:
            logger.info(
                "AD-1286: recorded outcome %s for worker attempt %s; the outcome is write-once, "
                "so a later different outcome is refused",
                outcome.terminal_status,
                outcome.worker_attempt_id,
            )
        return result

    async def get_attempt_outcome(self, worker_attempt_id: str) -> WorkerAttemptOutcome | None:
        """The recorded outcome of ``worker_attempt_id``, or None while the attempt has not ended.

        Raises:
            ValueError: ``elastic_attempt_query_invalid`` for a malformed id.
            ElasticTeamIntegrityError: ``elastic_attempt_outcome_integrity`` when the stored row no longer
                validates as an outcome.
        """
        if not _is_query_id(worker_attempt_id):
            raise ValueError("elastic_attempt_query_invalid")
        async with self._lock:
            async with self._connection() as db:
                rows = await _query(
                    db,
                    f"SELECT {_OUTCOME_COLUMNS} FROM elastic_attempt_outcomes WHERE worker_attempt_id = ?",
                    (worker_attempt_id,),
                )
        return _verified_outcome(rows[0]) if rows else None
