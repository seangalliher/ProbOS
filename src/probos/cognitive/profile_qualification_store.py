"""AD-1287 S1: ProfileQualificationStore -- insert-only execution profiles, evaluation evidence and invalidations.

Three ``WITHOUT ROWID`` tables; nine triggers abort every UPDATE, every DELETE and every INSERT that
would replace a row (including through a secondary unique key). The store issues plain INSERTs after
read-then-insert checks inside ``BEGIN IMMEDIATE``. Profiles and evaluation records are stored as
RFC 8785 canonical text under their content reference. The columns the store selects and enforces
uniqueness by (a profile's role and task class; an evaluation's profile and evaluation id) are
``VIRTUAL`` columns generated from that text, so they hold no value of their own to edit.

``start()`` accepts a database holding no schema objects (it creates them) or exactly this module's:
the same tables, indexes and triggers, each stored with the definition this module writes, which
SQLite re-reads every time it opens the file. Anything else is refused, and the store issues no schema
or data write to a file it refuses. SQLite itself can still change a refused file: opening it replays
a hot rollback journal a crashed writer left, or recovers its ``-wal`` file, and closing the last
connection to a WAL-mode file can checkpoint it and remove its ``-wal`` and ``-shm`` files. A refused file that needs no such
recovery, in rollback-journal mode, is left byte-identical. SQLite's own ``sqlite_*`` objects and
page-level integrity are not checked, and a layout changed while the store is started is seen only
when a stopped store is next started. WAL is requested after the check and tried again while another
connection holds the lock; a file that does not end in WAL is logged as a WARNING and served as it is.

Verification is per row, on read. Every stored row the store uses -- to decide a result or to return
it, including each profile ``find_slot_candidates`` examines -- is re-verified first (schema version;
canonical text against its content reference; each store stamp's type and range); one that does not
verify raises ``ProfileQualificationIntegrityError`` and is never relied on. A row a query fetches but
does not examine (``find_slot_candidates`` stops at ``limit``) is not verified. That is all the store
detects. A row that is missing -- deleted, or edited so that no selection
reaches it any more (for example an invalidation moved to another key) -- is indistinguishable from
one never written (R-2). Store stamps (sequence, issue, record and invalidation times) are bound to no
content identity, so a stamp rewritten within its type and range is not detected (R-3). A row forged
with valid content is indistinguishable from a real one: the store does not authenticate evaluators
(no signing; AD-1047). The engine's own checks are ``schema_version = 1`` per table, the triggers, the
unique keys, the generated columns and, on the store's own connections, foreign keys; every other
rule is enforced in Python before a write and on read, so a raw writer can insert a row the store
then refuses to read.

Evaluations and invalidations draw one store-wide sequence number, at most ``2**53 - 1``; a write that
would need a higher one is refused and writes nothing. The latest evaluation of a
profile (highest sequence) decides its status; an invalidation applies to every evaluation of that
profile with a lower sequence, so requalification is a new evaluation recorded after it. Expiry is
wall clock: issue time plus the suite's validity, both stamped by this store's clock.

Not wired: nothing constructs or starts this store in production; AD-1288 commission admission is
the intended caller of ``admit_qualified_attempt``. Qualification never grants a tool, data scope,
rank or authority lease.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

from pydantic import TypeAdapter

from probos.cognitive.elastic_team import ElasticId, ElasticTeamSpec, WorkerAttempt, WorkerSlot, is_sha256_ref
from probos.cognitive.execution_profile import (
    EvaluationRecord,
    ExecutionProfile,
    QualificationStatus,
    assess_evaluation,
    expires_at_ms,
    slot_refusal,
)
from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

PROFILE_QUALIFICATION_SCHEMA_VERSION: Final = 1
MAX_CANDIDATES: Final = 64
_MAX_SCAN = 128  # profiles examined per find_slot_candidates call; not Final so a test can lower it
_MAX_REASONS: Final = 16
_MAX_TIMESTAMP: Final = 253_402_300_799.0  # 9999-12-31T23:59:59Z in seconds: the largest clock accepted
_MAX_TIMESTAMP_MS: Final = 253_402_300_799_000  # the same instant in the store's integer milliseconds
_MAX_SEQ: Final = 2**53 - 1
_WAL_ATTEMPTS = 50  # tries of PRAGMA journal_mode=WAL in start(); not Final so a test can lower it
_WAL_RETRY_DELAY_S = 0.1  # seconds between those tries, about 5 s in all with no busy handler; not Final either
_REASON_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_ELASTIC_ID: Final = TypeAdapter(ElasticId)

# One statement per schema object, run in this order on a database holding none. SQLite stores each
# statement's text as written after normalising its leading keywords and spaces and removing any TEMP
# keyword or database-name qualifier (https://www.sqlite.org/schematab.html, section 3); these statements
# are already in that normalised form, so a file holding this layout holds exactly these texts in
# ``sqlite_master``, and ``start()`` compares them. Each CREATE TABLE is bound to its own name so
# ``scripts/check_store_registry.py`` detects the tables (AD-1256 rule (a)).
_PROFILES_TABLE: Final = """CREATE TABLE execution_profiles (
    profile_ref TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1), -- execution_profiles
    canonical_json TEXT NOT NULL,
    recorded_at_ms INTEGER NOT NULL,
    role_id TEXT GENERATED ALWAYS AS (json_extract(canonical_json, '$.role_id')) VIRTUAL,
    task_class TEXT GENERATED ALWAYS AS (json_extract(canonical_json, '$.task_class')) VIRTUAL
) WITHOUT ROWID"""  # end execution_profiles
_EVALUATIONS_TABLE: Final = """CREATE TABLE profile_evaluations (
    evidence_ref TEXT PRIMARY KEY,
    seq INTEGER NOT NULL UNIQUE,
    issued_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1), -- profile_evaluations
    canonical_json TEXT NOT NULL,
    profile_ref TEXT GENERATED ALWAYS AS (json_extract(canonical_json, '$.profile_ref')) VIRTUAL
        REFERENCES execution_profiles (profile_ref),
    evaluation_id TEXT GENERATED ALWAYS AS (json_extract(canonical_json, '$.evaluation_id')) VIRTUAL,
    UNIQUE (profile_ref, evaluation_id)
) WITHOUT ROWID"""  # end profile_evaluations
_INVALIDATIONS_TABLE: Final = """CREATE TABLE profile_invalidations (
    profile_ref TEXT NOT NULL REFERENCES execution_profiles (profile_ref),
    invalidation_id TEXT NOT NULL,
    seq INTEGER NOT NULL UNIQUE,
    reason_code TEXT NOT NULL,
    invalidated_at_ms INTEGER NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1), -- profile_invalidations
    PRIMARY KEY (profile_ref, invalidation_id)
) WITHOUT ROWID"""  # end profile_invalidations
_SCHEMA_STATEMENTS: Final = (
    _PROFILES_TABLE,
    "CREATE INDEX execution_profiles_by_slot ON execution_profiles (role_id, task_class, profile_ref)",
    _EVALUATIONS_TABLE,
    "CREATE INDEX profile_evaluations_latest ON profile_evaluations (profile_ref, seq)",
    _INVALIDATIONS_TABLE,
    "CREATE INDEX profile_invalidations_latest ON profile_invalidations (profile_ref, seq)",
    """CREATE TRIGGER execution_profiles_no_update BEFORE UPDATE ON execution_profiles
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER execution_profiles_no_delete BEFORE DELETE ON execution_profiles
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER execution_profiles_no_replace BEFORE INSERT ON execution_profiles
WHEN EXISTS (SELECT 1 FROM execution_profiles WHERE profile_ref = NEW.profile_ref)
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER profile_evaluations_no_update BEFORE UPDATE ON profile_evaluations
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER profile_evaluations_no_delete BEFORE DELETE ON profile_evaluations
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER profile_evaluations_no_replace BEFORE INSERT ON profile_evaluations
WHEN EXISTS (SELECT 1 FROM profile_evaluations WHERE evidence_ref = NEW.evidence_ref OR seq = NEW.seq
             OR (profile_ref = json_extract(NEW.canonical_json, '$.profile_ref')
                 AND evaluation_id = json_extract(NEW.canonical_json, '$.evaluation_id')))
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER profile_invalidations_no_update BEFORE UPDATE ON profile_invalidations
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER profile_invalidations_no_delete BEFORE DELETE ON profile_invalidations
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER profile_invalidations_no_replace BEFORE INSERT ON profile_invalidations
WHEN EXISTS (SELECT 1 FROM profile_invalidations WHERE seq = NEW.seq
             OR (profile_ref = NEW.profile_ref AND invalidation_id = NEW.invalidation_id))
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
)


def _object_key(statement: str) -> tuple[str, str]:
    """``(type, name)`` of one schema statement, as ``sqlite_master`` names the object it creates."""
    _create, kind, name = statement.split(" ", 3)[:3]
    return kind.lower(), name


_LAYOUT: Final = {_object_key(statement): statement for statement in _SCHEMA_STATEMENTS}
_CATALOG_SQL: Final = "SELECT type, name, sql FROM sqlite_master"

_PROFILE_COLUMNS: Final = "profile_ref, schema_version, canonical_json, recorded_at_ms"
_EVALUATION_COLUMNS: Final = "evidence_ref, seq, issued_at_ms, expires_at_ms, schema_version, canonical_json"
_INVALIDATION_COLUMNS: Final = "profile_ref, invalidation_id, seq, reason_code, invalidated_at_ms, schema_version"
# Each table's MAX(seq) is read from its ``seq`` unique index, so the work does not grow with the rows.
_NEXT_SEQ_SQL: Final = (
    "SELECT MAX(m) FROM (SELECT MAX(seq) AS m FROM profile_evaluations "
    "UNION ALL SELECT MAX(seq) AS m FROM profile_invalidations)"
)


class ProfileQualificationStoreUnavailable(RuntimeError):
    """The store has not been started, has stopped, refused its file's layout, or its clock is not a finite real
    in range. ``str(exc)`` is the code."""


class ProfileQualificationConflict(ValueError):
    """A write that contradicts the record, names a profile the store does not hold, or would need a sequence
    number above ``_MAX_SEQ``. ``str(exc)`` is the code."""


class ProfileQualificationIntegrityError(ValueError):
    """A stored row no longer verifies (data integrity: propagate)."""


class SlotAdmissionRefused(ValueError):
    """The slot boundary refused a profile; ``str(exc)`` is the stable code. Nothing was recorded."""


@dataclass(frozen=True)
class RecordedEvaluation:
    """One stored evaluation: the evaluator's raw record plus what this store stamped on it."""

    evidence_ref: str
    seq: int
    issued_at_ms: int
    expires_at_ms: int
    record: EvaluationRecord


@dataclass(frozen=True)
class RecordedInvalidation:
    """One stored invalidation of a profile's evaluations recorded before it."""

    profile_ref: str
    invalidation_id: str
    reason_code: str
    seq: int
    invalidated_at_ms: int


@dataclass(frozen=True)
class ProfileQualification:
    """A profile's status at ``assessed_at_ms`` with the evidence that decided it. Evidence, never a grant."""

    profile_ref: str
    profile: ExecutionProfile
    status: QualificationStatus
    deciding: RecordedEvaluation | None  # the latest evaluation; None when unevaluated
    invalidation_reasons: tuple[str, ...]  # reasons that apply to ``deciding``, oldest first, at most 16
    assessed_at_ms: int


@dataclass(frozen=True)
class CandidateQueryResult:
    """Qualified profiles meeting one slot's constraints, ascending by reference. Nothing is ranked or chosen.

    ``complete`` is True when every stored profile with the slot's role and task class after the cursor
    was examined; otherwise ``next_after`` resumes after the last one examined.
    """

    candidates: tuple[ProfileQualification, ...]
    examined: int
    complete: bool
    next_after: str | None


class ProfileQualificationReader(Protocol):
    """The narrow read port the slot boundary depends on (ISP); ``ProfileQualificationStore`` satisfies it."""

    async def get_qualification(self, profile_ref: str) -> ProfileQualification | None: ...


class TeamAttemptRecorder(Protocol):
    """The two ``ElasticTeamStore`` operations the slot boundary uses; ``ElasticTeamStore`` satisfies it."""

    async def get_team_spec(self, team_spec_ref: str) -> ElasticTeamSpec | None: ...

    async def record_attempt(self, attempt: WorkerAttempt) -> WorkerAttempt: ...


def _checked_now_ms(clock: Callable[[], float]) -> int:
    """The store's "now" in integer milliseconds, or ``ProfileQualificationStoreUnavailable`` for a bad clock.

    Only exact comparisons: NaN and both infinities fail the range test, and Python compares an int of any
    size with a float without converting it, so no int or float clock value raises anything else."""
    now = clock()
    if type(now) not in (int, float) or not 0 <= now <= _MAX_TIMESTAMP:
        raise ProfileQualificationStoreUnavailable("profile_qualification_clock_invalid")
    return int(now * 1_000)


def _integrity(what: str, key: object) -> ProfileQualificationIntegrityError:
    logger.error(
        "AD-1287: stored %s %s no longer verifies; refusing to rely on it, so no status is reported and no "
        "slot is admitted from it -- inspect or restore profile_qualifications.db",
        what,
        str(key)[:80],
    )
    return ProfileQualificationIntegrityError("profile_qualification_integrity")


def _is_elastic_id(value: object) -> bool:
    try:
        _ELASTIC_ID.validate_python(value)
    except ValueError:
        return False
    return True


def _is_stamp(value: object) -> bool:
    """A time this store stamped: integer milliseconds in ``[0, _MAX_TIMESTAMP_MS]``."""
    return type(value) is int and 0 <= value <= _MAX_TIMESTAMP_MS


def _is_seq(value: object) -> bool:
    """A sequence number this store drew: an integer in ``[1, _MAX_SEQ]``."""
    return type(value) is int and 1 <= value <= _MAX_SEQ


def _schema_objects(catalog: list[Any]) -> dict[tuple[str, str], Any]:
    """``(type, name) -> stored definition`` of the file's schema objects, without SQLite's own ``sqlite_*`` ones."""
    return {(kind, name): sql for kind, name, sql in catalog if not str(name).lower().startswith("sqlite_")}


def _layout_differences(found: dict[tuple[str, str], Any]) -> list[str]:
    """Names of the objects missing from ``found``, extra in it, or stored with another definition than this
    module writes; empty when ``found`` is exactly this module's layout."""
    differences = sorted(name for _kind, name in set(found) ^ set(_LAYOUT))
    differences += sorted(key[1] for key, sql in found.items() if key in _LAYOUT and sql != _LAYOUT[key])
    return differences


async def _query(db: Any, sql: str, params: tuple[Any, ...]) -> list[Any]:
    """Run one read and return every row. Rows are indexed positionally by every caller."""
    cursor = await db.execute(sql, params)
    return list(await cursor.fetchall())


async def _set_wal(db: Any) -> str | None:
    """Ask SQLite for WAL mode; return the journal mode it reports, or None when every try found the file busy.

    Another connection's lock makes the switch answer SQLITE_BUSY. Under a RESERVED lock (an open write
    transaction) SQLite answers at once; under an EXCLUSIVE lock (a commit in progress, or BEGIN EXCLUSIVE)
    it first runs the busy handler, which held one try for 7.45 s under ``busy_timeout=5000`` (measured,
    review round 4, E1). The handler is therefore turned off on this connection before the first try, so
    every try answers at once and this loop alone bounds the wait: ``_WAL_ATTEMPTS`` tries
    ``_WAL_RETRY_DELAY_S`` apart, about 5 s. ``start()`` closes the connection straight after, so no other
    statement runs without the handler. A busy answer is tried again; any other error propagates, including
    an ``OperationalError`` that carries no SQLite error code (one a connection wrapper built itself)."""
    await db.execute("PRAGMA busy_timeout=0")  # the loop owns the budget (review round 4, E1)
    for attempt in range(_WAL_ATTEMPTS):
        if attempt:
            await asyncio.sleep(_WAL_RETRY_DELAY_S)
        try:
            rows = await _query(db, "PRAGMA journal_mode=WAL", ())
        except sqlite3.OperationalError as exc:
            code = getattr(exc, "sqlite_errorcode", None)  # set only on errors the sqlite3 library raised (E3)
            if not isinstance(code, int) or code & 0xFF != sqlite3.SQLITE_BUSY:
                raise
            continue
        return str(rows[0][0]).lower()
    return None  # every try found the file busy


def _verified_profile(row: Any) -> ExecutionProfile:
    """Verify one ``_PROFILE_COLUMNS`` row: schema version, canonical text, content identity, record time."""
    ref, version, stored, recorded_at = row
    try:
        profile = ExecutionProfile.model_validate(json.loads(stored))
        verified = (
            type(version) is int
            and version == PROFILE_QUALIFICATION_SCHEMA_VERSION
            and profile.content_ref() == ref
            and profile.canonical_bytes().decode("utf-8") == stored
            and _is_stamp(recorded_at)
        )
    except (TypeError, ValueError):
        verified = False
    if not verified:
        raise _integrity("execution profile", ref)
    return profile


def _verified_evaluation(row: Any, profile_ref: str, profile: ExecutionProfile) -> RecordedEvaluation:
    """Verify one ``_EVALUATION_COLUMNS`` row of ``profile``: canonical text, identity, stamps and expiry."""
    evidence_ref, seq, issued, expires, version, stored = row
    try:
        record = EvaluationRecord.model_validate(json.loads(stored))
        verified = (
            type(version) is int
            and version == PROFILE_QUALIFICATION_SCHEMA_VERSION
            and record.content_ref() == evidence_ref
            and record.canonical_bytes().decode("utf-8") == stored
            and record.profile_ref == profile_ref
            and _is_seq(seq)
            and _is_stamp(issued)
            and type(expires) is int and expires == expires_at_ms(profile, issued)
        )
    except (TypeError, ValueError):
        verified = False
    if not verified:
        raise _integrity("profile evaluation", evidence_ref)
    return RecordedEvaluation(evidence_ref, seq, issued, expires, record)


def _verified_invalidation(row: Any, profile_ref: str) -> RecordedInvalidation:
    """Verify one ``_INVALIDATION_COLUMNS`` row of ``profile_ref``."""
    row_profile_ref, invalidation_id, seq, reason_code, invalidated_at, version = row
    verified = (
        row_profile_ref == profile_ref
        and _is_elastic_id(invalidation_id)
        and type(reason_code) is str
        and _REASON_RE.fullmatch(reason_code) is not None
        and _is_seq(seq)
        and _is_stamp(invalidated_at)
        and type(version) is int
        and version == PROFILE_QUALIFICATION_SCHEMA_VERSION
    )
    if not verified:
        raise _integrity("profile invalidation", (row_profile_ref, invalidation_id))
    return RecordedInvalidation(profile_ref, invalidation_id, reason_code, seq, invalidated_at)


async def _next_seq(db: Any) -> int:
    """One more than the highest sequence in either table (1 for an empty store). Called inside BEGIN IMMEDIATE,
    before the caller's INSERT, so a refusal here writes nothing.

    Raises ``ProfileQualificationConflict("profile_sequence_exhausted")`` when the highest is ``_MAX_SEQ``: a
    higher number would be a row this store refuses to read."""
    rows = await _query(db, _NEXT_SEQ_SQL, ())
    latest = rows[0][0]
    if latest is None:
        return 1
    if not _is_seq(latest):
        raise _integrity("sequence", latest)
    if latest == _MAX_SEQ:
        raise ProfileQualificationConflict("profile_sequence_exhausted")
    return latest + 1


async def _load_profile(db: Any, profile_ref: str) -> ExecutionProfile | None:
    rows = await _query(db, f"SELECT {_PROFILE_COLUMNS} FROM execution_profiles WHERE profile_ref = ?", (profile_ref,))
    return _verified_profile(rows[0]) if rows else None


async def _assess(db: Any, profile_ref: str, profile: ExecutionProfile, now_ms: int) -> ProfileQualification:
    """The profile's status from its latest evaluation and the invalidations recorded after it."""
    latest = await _query(
        db,
        f"SELECT {_EVALUATION_COLUMNS} FROM profile_evaluations WHERE profile_ref = ? ORDER BY seq DESC LIMIT 1",
        (profile_ref,),
    )
    if not latest:
        return ProfileQualification(profile_ref, profile, "unevaluated", None, (), now_ms)
    deciding = _verified_evaluation(latest[0], profile_ref, profile)
    later = await _query(
        db,
        f"SELECT {_INVALIDATION_COLUMNS} FROM profile_invalidations WHERE profile_ref = ? AND seq > ? "
        "ORDER BY seq LIMIT ?",
        (profile_ref, deciding.seq, _MAX_REASONS),
    )
    reasons = tuple(_verified_invalidation(row, profile_ref).reason_code for row in later)
    status = assess_evaluation(
        profile, deciding.record, issued_at_ms=deciding.issued_at_ms, invalidated=bool(reasons), now_ms=now_ms,
    )
    return ProfileQualification(profile_ref, profile, status, deciding, reasons, now_ms)


class ProfileQualificationStore:
    """Insert-only execution profiles, evaluation evidence and invalidations (AD-1287 S1).

    Public API:
        start() / stop() -- lifecycle; idempotent
        register_profile(profile) -> profile_ref -- idempotent
        get_profile(profile_ref) -> ExecutionProfile | None -- verified
        record_evaluation(record) -> RecordedEvaluation -- idempotent for an identical record
        invalidate_profile(profile_ref, invalidation_id, reason_code) -> RecordedInvalidation -- idempotent
        get_qualification(profile_ref) -> ProfileQualification | None -- satisfies ProfileQualificationReader
        find_slot_candidates(slot, *, limit, after) -> CandidateQueryResult -- bounded, deterministic

    Cancellation contract (every method): ``CancelledError`` propagates and is not swallowed; for a write
    it means the outcome is unknown. Every write is idempotent for identical input, so retrying the
    identical call is safe whether or not the cancelled one recorded. No promise is made about when
    ``CancelledError`` arrives relative to the connection's cleanup, the lock's release or a queued COMMIT.

    Raises:
        ProfileQualificationStoreUnavailable: not started, stopped, a refused file layout (``start``), or a clock
            that is not a finite real in range.
        ProfileQualificationConflict: a write that contradicts the record or exceeds the sequence bound;
            ``str(exc)`` is the code.
        ProfileQualificationIntegrityError: a stored row that decides or is returned does not verify.
    """

    def __init__(
        self,
        db_path: str,
        connection_factory: ConnectionFactory | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Nothing is opened until :meth:`start`. ``""`` and ``":memory:"`` are refused: evidence that forgets
        on restart defeats its purpose, and per-operation connections would each see an empty database."""
        if type(db_path) is not str or not db_path or db_path == ":memory:":
            raise ValueError("profile_qualification_store_path_invalid")
        self._db_path = db_path
        self._clock = clock
        self._started = False
        self._lock = asyncio.Lock()
        if connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            connection_factory = default_factory
        self._connection_factory: ConnectionFactory = connection_factory

    async def start(self) -> None:
        """Check the file's layout (creating it in a file that holds none), then admit operations. Idempotent.

        Accepts a database holding no schema objects, which it gives this module's layout, or exactly this
        module's layout. Any other file is refused inside one ``BEGIN IMMEDIATE``; the store issues no schema
        or data write to it (SQLite's own journal recovery and checkpoint can still change it). WAL is
        requested only after the check, and tried again while another connection holds the lock; a file that
        does not end in WAL is served as it is, with a WARNING. A start that finds the store stopped and fails
        leaves it stopped and propagates, except that a ``close()`` failure is logged and does not fail it
        (D9). A start that finds the store started returns at once without checking, and one cancelled while
        waiting for the lock leaves a started store started.

        Raises:
            ProfileQualificationStoreUnavailable: ``profile_qualification_layout_mismatch``.
        """
        async with self._lock:
            if self._started:
                return
            async with self._open() as db:
                await db.execute("BEGIN IMMEDIATE")
                found = _schema_objects(await _query(db, _CATALOG_SQL, ()))
                if not found:
                    for statement in _SCHEMA_STATEMENTS:
                        await db.execute(statement)
                else:
                    differences = _layout_differences(found)
                    if differences:
                        logger.error(
                            "AD-1287: %s does not hold the profile qualification layout (missing, extra or "
                            "differently defined: %s); refusing to start, and the store wrote no schema or data "
                            "to it -- move the file aside or restore it",
                            self._db_path,
                            ", ".join(differences[:16]),
                        )
                        raise ProfileQualificationStoreUnavailable("profile_qualification_layout_mismatch")
                await db.commit()
                mode = await _set_wal(db)
            self._started = True
        if mode != "wal":
            logger.warning(
                "AD-1287: %s is not in WAL mode (SQLite answered %s within %d tries); the store works without "
                "WAL, but its readers and its writer now wait on each other",
                self._db_path,
                mode or "busy on every try",
                _WAL_ATTEMPTS,
            )
        logger.info(
            "AD-1287: ProfileQualificationStore started (db=%s); profiles, evaluations and invalidations "
            "are insert-only",
            self._db_path,
        )

    async def stop(self) -> None:
        """Stop admitting operations. Waits for the lock, so a call holding it returns or raises first. Idempotent."""
        async with self._lock:
            was_started, self._started = self._started, False
        if was_started:
            logger.info(
                "AD-1287: ProfileQualificationStore stopped (db=%s); calls raise unavailable until start()",
                self._db_path,
            )

    @contextlib.asynccontextmanager
    async def _open(self) -> AsyncIterator[Any]:
        """One connection for one operation, with its own pragmas. Once ``connect`` has returned, ``close()``
        is awaited in ``finally`` on every exit path (a repeated cancellation can interrupt that wait); a
        ``close()`` that raises is logged, not raised, and that connection may then stay open until released."""
        db = await self._connection_factory.connect(self._db_path)
        try:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.execute("PRAGMA foreign_keys=ON")
            yield db
        finally:
            try:
                await db.close()
            except Exception:  # noqa: BLE001 -- log-and-degrade: the operation's own result or error stands
                logger.warning(
                    "AD-1287: closing a profile qualification connection failed; its uncommitted work was never "
                    "visible to other connections, and later writes may wait on its lock until it is released",
                    exc_info=True,
                )

    @contextlib.asynccontextmanager
    async def _operation(self) -> AsyncIterator[tuple[Any, int]]:
        """The frame of each of the six data methods: hold the lock, refuse when stopped, take "now", open one
        connection. ``start`` and ``stop`` take the lock but read no clock."""
        async with self._lock:
            if not self._started:
                raise ProfileQualificationStoreUnavailable("profile_qualification_store_unavailable")
            now_ms = _checked_now_ms(self._clock)
            async with self._open() as db:
                yield db, now_ms

    async def register_profile(self, profile: ExecutionProfile) -> str:
        """Store ``profile`` and return its reference. Idempotent: the same profile again writes nothing.

        Raises:
            TypeError: ``execution_profile_type_invalid``.
            ValueError: (``pydantic.ValidationError``) the profile no longer validates (built without validation).
            ProfileQualificationIntegrityError: the row stored under its reference does not verify.
        """
        if type(profile) is not ExecutionProfile:
            raise TypeError("execution_profile_type_invalid")
        profile = ExecutionProfile.model_validate(profile)  # a model_copy(update=...) skips validation
        profile_ref = profile.content_ref()
        canonical = profile.canonical_bytes().decode("utf-8")
        async with self._operation() as (db, now_ms):
            await db.execute("BEGIN IMMEDIATE")
            if await _load_profile(db, profile_ref) is None:
                await db.execute(
                    "INSERT INTO execution_profiles (profile_ref, schema_version, canonical_json, recorded_at_ms) "
                    "VALUES (?, ?, ?, ?)",
                    (profile_ref, PROFILE_QUALIFICATION_SCHEMA_VERSION, canonical, now_ms),
                )
            await db.commit()  # not shielded: a COMMIT queued before a cancel may still run (N2)
        return profile_ref

    async def get_profile(self, profile_ref: str) -> ExecutionProfile | None:
        """The profile stored under ``profile_ref``, verified, or None.

        Raises:
            ValueError: ``execution_profile_ref_invalid`` for a malformed reference.
            ProfileQualificationIntegrityError: the stored row does not verify.
        """
        if not is_sha256_ref(profile_ref):
            raise ValueError("execution_profile_ref_invalid")
        async with self._operation() as (db, _now_ms):
            return await _load_profile(db, profile_ref)

    async def record_evaluation(self, record: EvaluationRecord) -> RecordedEvaluation:
        """Store one evaluation run of a registered profile; this store stamps its issue time and sequence.

        Idempotent: an identical record returns what was stored the first time (same sequence and issue
        time) and writes nothing, so renewing a pass needs a new run (a new ``evaluation_id``).

        Raises:
            TypeError: ``profile_evaluation_type_invalid``.
            ValueError: (``pydantic.ValidationError``) the record no longer validates.
            ProfileQualificationConflict: ``profile_unknown``, ``profile_evaluation_conflict`` (this profile
                already holds a different record under this ``evaluation_id``) or ``profile_sequence_exhausted``.
                Nothing is written.
            ProfileQualificationIntegrityError: a row that decides the write does not verify.
        """
        if type(record) is not EvaluationRecord:
            raise TypeError("profile_evaluation_type_invalid")
        record = EvaluationRecord.model_validate(record)
        evidence_ref = record.content_ref()
        canonical = record.canonical_bytes().decode("utf-8")
        async with self._operation() as (db, now_ms):
            await db.execute("BEGIN IMMEDIATE")
            profile = await _load_profile(db, record.profile_ref)
            if profile is None:
                raise ProfileQualificationConflict("profile_unknown")
            rows = await _query(
                db,
                f"SELECT {_EVALUATION_COLUMNS} FROM profile_evaluations "
                "WHERE evidence_ref = ? OR (profile_ref = ? AND evaluation_id = ?)",
                (evidence_ref, record.profile_ref, record.evaluation_id),
            )
            stored = [_verified_evaluation(row, record.profile_ref, profile) for row in rows]
            if any(item.evidence_ref != evidence_ref for item in stored):
                raise ProfileQualificationConflict("profile_evaluation_conflict")
            if stored:
                await db.commit()
                return stored[0]
            seq = await _next_seq(db)
            recorded = RecordedEvaluation(evidence_ref, seq, now_ms, expires_at_ms(profile, now_ms), record)
            await db.execute(
                "INSERT INTO profile_evaluations (evidence_ref, seq, issued_at_ms, expires_at_ms, schema_version, "
                "canonical_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    evidence_ref,
                    seq,
                    recorded.issued_at_ms,
                    recorded.expires_at_ms,
                    PROFILE_QUALIFICATION_SCHEMA_VERSION,
                    canonical,
                ),
            )
            await db.commit()  # not shielded: a COMMIT queued before a cancel may still run (N2)
        return recorded

    async def invalidate_profile(
        self, profile_ref: str, invalidation_id: str, reason_code: str,
    ) -> RecordedInvalidation:
        """Record that ``profile_ref``'s evaluations recorded so far no longer qualify it.

        Applies to every evaluation of the profile with a lower sequence; an evaluation recorded later can
        qualify it again. Idempotent for the same ``invalidation_id`` and ``reason_code``.

        Raises:
            ValueError: ``profile_invalidation_invalid`` for a malformed reference, id or reason code.
            ProfileQualificationConflict: ``profile_unknown``, ``profile_invalidation_conflict`` (the id is
                already recorded with another reason) or ``profile_sequence_exhausted``. Nothing is written.
            ProfileQualificationIntegrityError: a row that decides the write does not verify.
        """
        if (
            not is_sha256_ref(profile_ref)
            or not _is_elastic_id(invalidation_id)
            or type(reason_code) is not str
            or _REASON_RE.fullmatch(reason_code) is None
        ):
            raise ValueError("profile_invalidation_invalid")
        async with self._operation() as (db, now_ms):
            await db.execute("BEGIN IMMEDIATE")
            if await _load_profile(db, profile_ref) is None:
                raise ProfileQualificationConflict("profile_unknown")
            rows = await _query(
                db,
                f"SELECT {_INVALIDATION_COLUMNS} FROM profile_invalidations "
                "WHERE profile_ref = ? AND invalidation_id = ?",
                (profile_ref, invalidation_id),
            )
            if rows:
                existing = _verified_invalidation(rows[0], profile_ref)
                if existing.reason_code != reason_code:
                    raise ProfileQualificationConflict("profile_invalidation_conflict")
                await db.commit()
                return existing
            seq = await _next_seq(db)
            await db.execute(
                "INSERT INTO profile_invalidations (profile_ref, invalidation_id, seq, reason_code, "
                "invalidated_at_ms, schema_version) VALUES (?, ?, ?, ?, ?, ?)",
                (profile_ref, invalidation_id, seq, reason_code, now_ms, PROFILE_QUALIFICATION_SCHEMA_VERSION),
            )
            await db.commit()  # not shielded: a COMMIT queued before a cancel may still run (N2)
        logger.info(
            "AD-1287: invalidated execution profile %s (%s); evaluations recorded before this no longer "
            "qualify it, and a new evaluation is needed",
            profile_ref,
            reason_code,
        )
        return RecordedInvalidation(profile_ref, invalidation_id, reason_code, seq, now_ms)

    async def get_qualification(self, profile_ref: str) -> ProfileQualification | None:
        """``profile_ref``'s status now, with the evidence that decided it, or None when it is not registered.

        Raises:
            ValueError: ``execution_profile_ref_invalid`` for a malformed reference.
            ProfileQualificationIntegrityError: a row that decides the status does not verify.
        """
        if not is_sha256_ref(profile_ref):
            raise ValueError("execution_profile_ref_invalid")
        async with self._operation() as (db, now_ms):
            profile = await _load_profile(db, profile_ref)
            return None if profile is None else await _assess(db, profile_ref, profile, now_ms)

    async def find_slot_candidates(
        self, slot: WorkerSlot, *, limit: int = 16, after: str | None = None,
    ) -> CandidateQueryResult:
        """Qualified profiles meeting ``slot``'s declared constraints, ascending by reference, with evidence.

        Examines at most ``_MAX_SCAN`` stored profiles with the slot's role and task class, in ascending
        reference order after ``after``, all assessed at one "now", and returns at most ``limit``
        (1..``MAX_CANDIDATES``) whose status is ``qualified`` and that ``slot_refusal`` accepts. It ranks and
        chooses nothing; the process owner decides. ``complete`` is False when it stopped at ``limit`` or at
        the scan bound with profiles left to examine; ``next_after`` then resumes after the last one examined.

        Raises:
            TypeError: ``profile_slot_type_invalid``.
            ValueError: ``profile_query_invalid`` for a bad ``limit`` or ``after``.
            ProfileQualificationIntegrityError: an examined row does not verify.
        """
        if type(slot) is not WorkerSlot:
            raise TypeError("profile_slot_type_invalid")
        slot = WorkerSlot.model_validate(slot)
        if (
            type(limit) is not int
            or not 1 <= limit <= MAX_CANDIDATES
            or (after is not None and not is_sha256_ref(after))
        ):
            raise ValueError("profile_query_invalid")
        async with self._operation() as (db, now_ms):
            rows = await _query(
                db,
                f"SELECT {_PROFILE_COLUMNS} FROM execution_profiles WHERE role_id = ? AND task_class = ? "
                "AND profile_ref > ? ORDER BY profile_ref LIMIT ?",
                (slot.role_id, slot.task_class, after or "", _MAX_SCAN + 1),
            )
            candidates: list[ProfileQualification] = []
            examined = 0
            for row in rows[:_MAX_SCAN]:
                examined += 1
                profile = _verified_profile(row)
                if slot_refusal(slot, profile) is None:
                    assessed = await _assess(db, row[0], profile, now_ms)
                    if assessed.status == "qualified":
                        candidates.append(assessed)
                        if len(candidates) == limit:
                            break
            complete = examined == len(rows)
            next_after = None if complete else rows[examined - 1][0]
        return CandidateQueryResult(tuple(candidates), examined, complete, next_after)


async def check_slot_qualification(
    qualifications: ProfileQualificationReader, spec: ElasticTeamSpec, slot_id: str, profile_ref: str,
) -> ProfileQualification:
    """The slot boundary's qualification check: the qualifying evidence, or ``SlotAdmissionRefused``.

    Refuses, in this order: ``slot_unknown``; ``profile_unknown``; ``profile_evidence_mismatch`` (the reader
    answered for another profile); the first ``slot_refusal`` code; ``profile_status_<status>`` for any status
    other than ``qualified``. Every slot requires a qualified profile; ``qualification_ids`` and
    ``pinned_profile_refs`` only narrow which. Reads only; grants nothing.

    Raises:
        TypeError: ``profile_slot_type_invalid`` when ``spec`` is not an ``ElasticTeamSpec``.
    """
    if type(spec) is not ElasticTeamSpec:
        raise TypeError("profile_slot_type_invalid")
    slot = spec.slot(slot_id)
    if slot is None:
        raise SlotAdmissionRefused("slot_unknown")
    qualification = await qualifications.get_qualification(profile_ref)
    if qualification is None:
        raise SlotAdmissionRefused("profile_unknown")
    if qualification.profile_ref != profile_ref or qualification.profile.content_ref() != profile_ref:
        raise SlotAdmissionRefused("profile_evidence_mismatch")
    refusal = slot_refusal(slot, qualification.profile)
    if refusal is not None:
        raise SlotAdmissionRefused(refusal)
    if qualification.status != "qualified":
        raise SlotAdmissionRefused(f"profile_status_{qualification.status}")
    return qualification


async def admit_qualified_attempt(
    qualifications: ProfileQualificationReader, teams: TeamAttemptRecorder, attempt: WorkerAttempt,
) -> WorkerAttempt:
    """Record ``attempt`` only when its exact execution profile is qualified for its slot (the slot boundary).

    Loads the stored spec through ``teams``, runs ``check_slot_qualification``, then calls
    ``teams.record_attempt``, which applies AD-1286's own admission rules. A refusal records nothing. The
    check runs on every call, including an identical replay of an attempt already recorded, so a replay
    after the profile stopped qualifying is refused (recovery reads ``get_attempt`` instead). Admission is
    decided as of the qualification read: the two stores share no transaction, so an invalidation recorded
    after that read does not undo an attempt already recorded (AD-1288 owns stopping running attempts).

    Raises:
        TypeError: ``elastic_attempt_type_invalid``.
        SlotAdmissionRefused: ``slot_spec_unknown`` or any ``check_slot_qualification`` code.
        Whatever ``teams.record_attempt`` raises, unchanged.
    """
    if type(attempt) is not WorkerAttempt:
        raise TypeError("elastic_attempt_type_invalid")
    attempt = WorkerAttempt.model_validate(attempt)
    spec = await teams.get_team_spec(attempt.team_spec_ref)
    if spec is None:
        raise SlotAdmissionRefused("slot_spec_unknown")
    try:
        await check_slot_qualification(qualifications, spec, attempt.slot_id, attempt.execution_profile_ref)
    except SlotAdmissionRefused as refused:
        logger.info(
            "AD-1287: slot %s refused execution profile %s (%s); no worker attempt was recorded",
            attempt.slot_id,
            attempt.execution_profile_ref,
            refused,
        )
        raise
    return await teams.record_attempt(attempt)
