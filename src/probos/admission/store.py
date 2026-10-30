"""AD-1346 M3b (#1604): ``admission_shadow.db``, the durable record of the shadow admission decision.

The store #1601's evidence 2, 4, 7 and 8 read (memo D9: a dedicated store, not AD-1195 durable
events). It holds one ``schema_version`` row and five tables, each bounded by a module constant
(memo D10); AD-1346 M3c added the last two:

- ``shadow_aggregates``: decisions per (UTC day, work kind, seam, outcome, reason code, latency
  bucket). ``prune`` deletes the days before the last ``AGGREGATE_RETENTION_DAYS`` of its ``now``,
  then, while more than ``AGGREGATE_ROW_LIMIT`` rows remain, the oldest whole day before the
  current one.
- ``shadow_samples``: would-refuse verdicts as ``AdmissionVerdict.to_dict()`` JSON, whose keys are
  in ``VERDICT_KEYS`` order. Each ``write_batch`` that adds samples then keeps the newest
  ``SAMPLE_RING_SIZE`` rows.
- ``shadow_markers``: per (boot, UTC hour), the verdicts offered, the verdicts written to the
  aggregates, the verdicts dropped and the samples dropped. ``prune`` deletes the days before the
  last ``MARKER_RETENTION_DAYS``, then the oldest hours while more than ``MARKER_ROW_LIMIT`` rows
  remain.
- ``shadow_parity`` (M3c): decisions per (UTC day, work kind, seam, today's outcome, outcome,
  reason code), for verdicts aggregated with the site's own outcome. ``prune`` deletes the days before
  the last ``AGGREGATE_RETENTION_DAYS``. It has no row limit of its own: for the verdicts ``decide``
  builds one day holds at most len(WORK_KINDS) * len(SEAMS) * len(TODAY_OUTCOMES) *
  len(REASON_CODES) rows, a test pins that 35 such days stay below ``AGGREGATE_ROW_LIMIT``, and a
  wall clock that steps back can leave more days than 35.
- ``shadow_disagreements`` (M3c): verdicts whose outcome differs from the site's own, as
  ``AdmissionVerdict.to_dict()`` JSON with today's outcome beside it. Each ``write_batch`` that adds
  one then keeps the newest ``DISAGREEMENT_RING_SIZE`` rows.

The store is opened through the ``ConnectionFactory``. ``start`` opens a file whose
``schema_version`` holds exactly one row of ``SCHEMA_VERSION``, writes that row to a file with no
row, and refuses a file with any other rows without writing to it; this module has no migration.
M3c's two tables are additive and keep version 1 (D58): ``start`` creates them on any version-1
file, so a file the M3b build wrote opens here with its rows unchanged, and the M3b build's
``start`` accepts a file this build wrote, because it checks only the version row and creates only
its own three tables.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Final

from probos.storage.sqlite_factory import default_factory

if TYPE_CHECKING:
    from probos.admission.record import AdmissionVerdict
    from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)

STORE_FILENAME: Final = "admission_shadow.db"
#: The layout below; AD-1346 M3c's two tables are additive and keep it (D58). ``start`` refuses any other version.
SCHEMA_VERSION: Final = 1
DAY_SECONDS: Final = 86_400

#: D10: the current UTC day and the 34 days before it.
AGGREGATE_RETENTION_DAYS: Final = 35
#: D10: after ``prune``, at most this many rows remain, unless every remaining row is of the current
#: day or a later one, which ``prune`` never deletes (a later day's rows exist after the wall clock
#: steps back). Keyed by a verdict's closed fields, one day holds at
#: most len(WORK_KINDS) * len(SEAMS) * len(REASON_CODES) * LATENCY_BUCKETS rows: 23,040 with the
#: vocabularies of AD-1346 M3c3 (12 work kinds, 12 seams), and a test pins that the product stays below this bound.
AGGREGATE_ROW_LIMIT: Final = 100_000
#: D10: the would-refuse samples kept, the newest.
SAMPLE_RING_SIZE: Final = 5_000
#: AD-1346 M3c (D58): the disagreement samples kept, the newest.
DISAGREEMENT_RING_SIZE: Final = 1_000
#: D10: the current UTC day and the 34 days before it.
MARKER_RETENTION_DAYS: Final = 35
#: D10: after ``prune``, at most this many marker rows; the oldest hours go first.
MARKER_ROW_LIMIT: Final = 50_000

_VERSION_TABLE: Final = "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);"
_SELECT_VERSION: Final = "SELECT version FROM schema_version"
_INSERT_VERSION: Final = "INSERT INTO schema_version (version) VALUES (?)"
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS shadow_aggregates (
    day            TEXT NOT NULL,
    work_kind      TEXT NOT NULL,
    seam           TEXT NOT NULL,
    outcome        TEXT NOT NULL,
    reason_code    TEXT NOT NULL,
    latency_bucket INTEGER NOT NULL,
    decisions      INTEGER NOT NULL,
    PRIMARY KEY (day, work_kind, seam, outcome, reason_code, latency_bucket)
);
CREATE TABLE IF NOT EXISTS shadow_samples (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    boot_id      TEXT NOT NULL,
    hour         TEXT NOT NULL,
    recorded_at  REAL NOT NULL,
    work_kind    TEXT NOT NULL,
    seam         TEXT NOT NULL,
    outcome      TEXT NOT NULL,
    reason_code  TEXT NOT NULL,
    latency_ns   INTEGER NOT NULL,
    verdict_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shadow_markers (
    boot_id         TEXT NOT NULL,
    hour            TEXT NOT NULL,
    offered         INTEGER NOT NULL,
    written         INTEGER NOT NULL,
    dropped         INTEGER NOT NULL,
    samples_dropped INTEGER NOT NULL,
    PRIMARY KEY (boot_id, hour)
);
CREATE TABLE IF NOT EXISTS shadow_parity (
    day           TEXT NOT NULL,
    work_kind     TEXT NOT NULL,
    seam          TEXT NOT NULL,
    today_outcome TEXT NOT NULL,
    outcome       TEXT NOT NULL,
    reason_code   TEXT NOT NULL,
    decisions     INTEGER NOT NULL,
    PRIMARY KEY (day, work_kind, seam, today_outcome, outcome, reason_code)
);
CREATE TABLE IF NOT EXISTS shadow_disagreements (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    boot_id       TEXT NOT NULL,
    hour          TEXT NOT NULL,
    recorded_at   REAL NOT NULL,
    work_kind     TEXT NOT NULL,
    seam          TEXT NOT NULL,
    today_outcome TEXT NOT NULL,
    outcome       TEXT NOT NULL,
    reason_code   TEXT NOT NULL,
    latency_ns    INTEGER NOT NULL,
    verdict_json  TEXT NOT NULL
);
"""
_UPSERT_AGGREGATE: Final = (
    "INSERT INTO shadow_aggregates (day, work_kind, seam, outcome, reason_code, latency_bucket, decisions) "
    "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (day, work_kind, seam, outcome, reason_code, latency_bucket) "
    "DO UPDATE SET decisions = decisions + excluded.decisions"
)
_INSERT_SAMPLE: Final = (
    "INSERT INTO shadow_samples (boot_id, hour, recorded_at, work_kind, seam, outcome, reason_code, latency_ns, "
    "verdict_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_TRIM_SAMPLES: Final = "DELETE FROM shadow_samples WHERE seq <= (SELECT MAX(seq) FROM shadow_samples) - ?"
_UPSERT_PARITY: Final = (
    "INSERT INTO shadow_parity (day, work_kind, seam, today_outcome, outcome, reason_code, decisions) "
    "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (day, work_kind, seam, today_outcome, outcome, reason_code) "
    "DO UPDATE SET decisions = decisions + excluded.decisions"
)
_INSERT_DISAGREEMENT: Final = (
    "INSERT INTO shadow_disagreements (boot_id, hour, recorded_at, work_kind, seam, today_outcome, outcome, "
    "reason_code, latency_ns, verdict_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_TRIM_DISAGREEMENTS: Final = (
    "DELETE FROM shadow_disagreements WHERE seq <= (SELECT MAX(seq) FROM shadow_disagreements) - ?"
)
_PRUNE_PARITY: Final = "DELETE FROM shadow_parity WHERE day < ?"
_UPSERT_MARKER: Final = (
    "INSERT INTO shadow_markers (boot_id, hour, offered, written, dropped, samples_dropped) "
    "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (boot_id, hour) DO UPDATE SET "
    "offered = offered + excluded.offered, written = written + excluded.written, "
    "dropped = dropped + excluded.dropped, samples_dropped = samples_dropped + excluded.samples_dropped"
)
_PRUNE_AGGREGATES: Final = "DELETE FROM shadow_aggregates WHERE day < ?"
_COUNT_AGGREGATES: Final = "SELECT COUNT(*), MIN(day) FROM shadow_aggregates"
_DELETE_AGGREGATE_DAY: Final = "DELETE FROM shadow_aggregates WHERE day = ?"
#: An hour (``YYYY-MM-DDTHH``) sorts after its own day's date, so this keeps the cutoff day's hours.
_PRUNE_MARKERS: Final = "DELETE FROM shadow_markers WHERE hour < ?"
_COUNT_MARKERS: Final = "SELECT COUNT(*) FROM shadow_markers"
_DELETE_OLDEST_MARKERS: Final = (
    "DELETE FROM shadow_markers WHERE rowid IN (SELECT rowid FROM shadow_markers ORDER BY hour, boot_id LIMIT ?)"
)


def utc_day(timestamp: float) -> str:
    """The UTC date of a POSIX timestamp, ``YYYY-MM-DD``."""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")


def utc_hour(timestamp: float) -> str:
    """The UTC hour of a POSIX timestamp, ``YYYY-MM-DDTHH``; its first ten characters are ``utc_day``'s."""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H")


async def _rollback_quietly(db: DatabaseConnection) -> None:
    """Undo an uncommitted write so that a later commit cannot land it (AD-1213's pattern)."""
    try:
        await db.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- no open transaction is the common case
        logger.debug("AD-1346 M3b: a rollback after a failed shadow store write found no open transaction", exc_info=True)


@dataclass(frozen=True, slots=True)
class ShadowSample:
    """One would-refuse verdict kept for the ring: the UTC hour and wall time it was offered, the verdict and its time."""

    hour: str
    recorded_at: float
    verdict: AdmissionVerdict
    latency_ns: int


@dataclass(frozen=True, slots=True)
class ShadowDisagreement:
    """AD-1346 M3c (D58): a verdict whose outcome differs from the site's own: the hour and wall time it was offered, the verdict, its time and today's outcome."""

    hour: str
    recorded_at: float
    verdict: AdmissionVerdict
    latency_ns: int
    today_outcome: str


@dataclass(frozen=True, slots=True)
class ShadowBatch:
    """What one ``write_batch`` writes. Aggregate keys are (hour, work kind, seam, outcome, reason code, bucket).

    AD-1346 M3c: parity keys are (hour, work kind, seam, today's outcome, outcome, reason code). Both
    fields it added default to empty, so a batch built from the first five fields writes what M3b wrote.
    """

    aggregates: dict[tuple[str, str, str, str, str, int], int]
    samples: list[ShadowSample]
    offered: dict[str, int]
    dropped: dict[str, int]
    samples_dropped: dict[str, int]
    parity: dict[tuple[str, str, str, str, str, str], int] = field(default_factory=dict)
    disagreements: list[ShadowDisagreement] = field(default_factory=list)


class AdmissionShadowStore:
    """Ship's Computer store: the shadow admission decision's durable record (AD-1346 M3b)."""

    def __init__(self, *, data_dir: str | Path, connection_factory: ConnectionFactory | None = None) -> None:
        self._data_dir = Path(data_dir)
        self._connection_factory: ConnectionFactory = (
            connection_factory if connection_factory is not None else default_factory
        )
        self._db: DatabaseConnection | None = None

    @property
    def path(self) -> Path:
        """The store's file: ``STORE_FILENAME`` in the data directory."""
        return self._data_dir / STORE_FILENAME

    @property
    def is_open(self) -> bool:
        """True from a ``start`` that returned until a ``stop`` whose close returned."""
        return self._db is not None

    async def start(self) -> None:
        """Open the file and check its schema version, then create what is missing; a new file records ``SCHEMA_VERSION``.

        Raises ``RuntimeError`` when the store is already open or the file holds other
        ``schema_version`` rows, and propagates what the factory or SQLite raises. When it raises
        after the connection opened, it closes that connection first (a close that raises an
        ``Exception`` is logged at DEBUG; any other ``BaseException`` from the close propagates in
        place of the start's), and ``is_open`` stays False.
        """
        if self._db is not None:
            raise RuntimeError("AD-1346 M3b: the shadow admission store is already open")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        db = await self._connection_factory.connect(str(self.path))
        try:
            await db.executescript(_VERSION_TABLE)
            async with db.execute(_SELECT_VERSION) as cursor:
                rows = [tuple(row) for row in await cursor.fetchall()]
            if rows not in ([], [(SCHEMA_VERSION,)]):
                raise RuntimeError(
                    f"AD-1346 M3b: {STORE_FILENAME} holds schema_version rows {rows!r}; this build reads only "
                    f"version {SCHEMA_VERSION} and has no migration"
                )
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.executescript(_SCHEMA)
            if not rows:
                await db.execute(_INSERT_VERSION, (SCHEMA_VERSION,))
            await db.commit()
        except BaseException:
            try:
                await db.close()
            except Exception:  # noqa: BLE001 -- the start's own exception is the one the caller needs
                logger.debug("AD-1346 M3b: closing the shadow store after a failed start raised", exc_info=True)
            raise
        self._db = db

    async def stop(self) -> None:
        """Close the file; a call after a stop whose close returned does nothing.

        ``_db`` is cleared only after the close returns, so a startup rollback's last-resort close
        (BF-882) still finds a connection whose close raised.
        """
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _connection(self) -> DatabaseConnection:
        if self._db is None:
            raise RuntimeError("AD-1346 M3b: the shadow admission store is not open")
        return self._db

    async def write_batch(self, boot_id: str, batch: ShadowBatch) -> int:
        """Write ``batch`` for ``boot_id`` in one transaction; the number of verdicts added to the aggregates.

        Each aggregate key's count is added to its row for that UTC day (the hour's first ten
        characters). Each sample becomes a row, and then the newest ``SAMPLE_RING_SIZE`` are kept.
        The marker row of each hour in the batch gains that hour's offered, dropped and
        samples-dropped counts, and the verdicts this call added to the aggregates for that hour.
        AD-1346 M3c: each parity key's count is added to its row for that UTC day, and each
        disagreement becomes a row, after which the newest ``DISAGREEMENT_RING_SIZE`` are kept. An
        exception from the statements or the commit rolls the transaction back and propagates.
        Raises ``RuntimeError`` when the store is not open.
        """
        db = self._connection()
        written: dict[str, int] = {}
        aggregates: list[tuple[str, str, str, str, str, int, int]] = []
        for (hour, work_kind, seam, outcome, reason_code, bucket), decisions in batch.aggregates.items():
            aggregates.append((hour[:10], work_kind, seam, outcome, reason_code, bucket, decisions))
            written[hour] = written.get(hour, 0) + decisions
        samples = [
            (
                boot_id, sample.hour, sample.recorded_at, sample.verdict.work_kind, sample.verdict.seam,
                sample.verdict.outcome, sample.verdict.reason_code, sample.latency_ns,
                json.dumps(sample.verdict.to_dict(), separators=(",", ":")),
            )
            for sample in batch.samples
        ]
        parity = [
            (hour[:10], work_kind, seam, today_outcome, outcome, reason_code, decisions)
            for (hour, work_kind, seam, today_outcome, outcome, reason_code), decisions in batch.parity.items()
        ]
        disagreements = [
            (
                boot_id, item.hour, item.recorded_at, item.verdict.work_kind, item.verdict.seam, item.today_outcome,
                item.verdict.outcome, item.verdict.reason_code, item.latency_ns,
                json.dumps(item.verdict.to_dict(), separators=(",", ":")),
            )
            for item in batch.disagreements
        ]
        hours = sorted(set(batch.offered) | set(written) | set(batch.dropped) | set(batch.samples_dropped))
        markers = [
            (
                boot_id, hour, batch.offered.get(hour, 0), written.get(hour, 0), batch.dropped.get(hour, 0),
                batch.samples_dropped.get(hour, 0),
            )
            for hour in hours
        ]
        try:
            if aggregates:
                await db.executemany(_UPSERT_AGGREGATE, aggregates)
            if samples:
                await db.executemany(_INSERT_SAMPLE, samples)
                await db.execute(_TRIM_SAMPLES, (SAMPLE_RING_SIZE,))
            if parity:
                await db.executemany(_UPSERT_PARITY, parity)
            if disagreements:
                await db.executemany(_INSERT_DISAGREEMENT, disagreements)
                await db.execute(_TRIM_DISAGREEMENTS, (DISAGREEMENT_RING_SIZE,))
            if markers:
                await db.executemany(_UPSERT_MARKER, markers)
            await db.commit()
        except BaseException:
            await _rollback_quietly(db)  # a later commit must not land part of this batch
            raise
        return sum(written.values())

    async def prune(self, now: float) -> tuple[int, int]:
        """Apply D10's bounds at wall-clock time ``now``, in one transaction; the aggregate and marker rows deleted.

        AD-1346 M3c: the same transaction deletes the parity rows of days before the last
        ``AGGREGATE_RETENTION_DAYS``; the counts returned leave them out. Raises ``RuntimeError`` when
        the store is not open; an exception from SQLite rolls the transaction back and propagates.
        """
        db = self._connection()
        today = utc_day(now)
        try:
            cursor = await db.execute(
                _PRUNE_AGGREGATES, (utc_day(now - (AGGREGATE_RETENTION_DAYS - 1) * DAY_SECONDS),),
            )
            aggregates = cursor.rowcount
            await db.execute(_PRUNE_PARITY, (utc_day(now - (AGGREGATE_RETENTION_DAYS - 1) * DAY_SECONDS),))
            while True:
                async with db.execute(_COUNT_AGGREGATES) as cursor:
                    count, oldest = await cursor.fetchone()
                if count <= AGGREGATE_ROW_LIMIT or oldest >= today:
                    break
                cursor = await db.execute(_DELETE_AGGREGATE_DAY, (oldest,))
                aggregates += cursor.rowcount
            cursor = await db.execute(
                _PRUNE_MARKERS, (utc_day(now - (MARKER_RETENTION_DAYS - 1) * DAY_SECONDS),),
            )
            markers = cursor.rowcount
            async with db.execute(_COUNT_MARKERS) as cursor:
                (count,) = await cursor.fetchone()
            if count > MARKER_ROW_LIMIT:
                cursor = await db.execute(_DELETE_OLDEST_MARKERS, (count - MARKER_ROW_LIMIT,))
                markers += cursor.rowcount
            await db.commit()
        except BaseException:
            await _rollback_quietly(db)  # a later commit must not land part of this prune
            raise
        return aggregates, markers
