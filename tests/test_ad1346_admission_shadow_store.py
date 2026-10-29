"""AD-1346 M3b (#1604): ``admission_shadow.db`` over real SQLite in ``tmp_path``.

- S1  a new file gets the four tables and one ``schema_version`` row, and a restart adds no second row.
- S2  a file with other ``schema_version`` rows is refused, its bytes unchanged and the connection closed.
- S3  ``write_batch`` adds counts by UTC day, writes samples as ``to_dict`` JSON, and its markers count what it wrote.
- S4  a batch that fails is rolled back, and the next commit does not land it.
- S5  the sample ring keeps the newest ``SAMPLE_RING_SIZE`` rows.
- S6  ``prune`` keeps the current UTC day and the 34 before it, for aggregates and markers.
- S7  beyond ``AGGREGATE_ROW_LIMIT``, ``prune`` deletes whole older days and never the current day.
- S8  beyond ``MARKER_ROW_LIMIT``, ``prune`` deletes the oldest marker rows.
- S9  the bounds are the D10 constants, and one day of verdict keys fits the row limit.
- S10 writes and prunes need an open store; ``start`` runs once; a second ``stop`` does nothing.
- S11 the AD-1256 declaration, apart from its lifecycle owner.
- S12 the store opens through the injected ``ConnectionFactory`` and closes that connection.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from probos.admission import VERDICT_KEYS
from probos.admission import store as store_module
from probos.admission.store import (
    AGGREGATE_RETENTION_DAYS,
    AGGREGATE_ROW_LIMIT,
    DAY_SECONDS,
    MARKER_RETENTION_DAYS,
    MARKER_ROW_LIMIT,
    SAMPLE_RING_SIZE,
    SCHEMA_VERSION,
    STORE_FILENAME,
    AdmissionShadowStore,
    ShadowBatch,
    ShadowSample,
    utc_day,
    utc_hour,
)
from probos.admission.taxonomy import LATENCY_BUCKETS, REASON_CODES, SEAMS, WORK_KINDS
from probos.storage.declarations import StoreCriticality, StoreRetention
from probos.storage.registry import DECLARATION_MODULES, load_default_store_registry
from probos.storage.sqlite_factory import default_factory
from tests.fixtures.ad1346_shadow import HOUR, T0, refuse, rows

BOOT = "boot-a"
TABLES = "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
MARKERS = "SELECT boot_id, hour, offered, written, dropped, samples_dropped FROM shadow_markers ORDER BY hour"


def _batch(
    aggregates: dict[tuple[str, str, str, str, str, int], int] | None = None,
    samples: list[ShadowSample] | None = None,
    offered: dict[str, int] | None = None,
    dropped: dict[str, int] | None = None,
    samples_dropped: dict[str, int] | None = None,
) -> ShadowBatch:
    return ShadowBatch(aggregates or {}, samples or [], offered or {}, dropped or {}, samples_dropped or {})


def _key(
    hour: str, *, outcome: str = "admit", reason_code: str = "admitted", bucket: int = 0,
    work_kind: str = "intent", seam: str = "intent",
) -> tuple[str, str, str, str, str, int]:
    return (hour, work_kind, seam, outcome, reason_code, bucket)


class _RecordingFactory:
    """A ``ConnectionFactory`` that hands out the default factory's connections and keeps each one."""

    def __init__(self) -> None:
        self.paths: list[str] = []
        self.connections: list[Any] = []

    async def connect(self, db_path: str) -> Any:
        self.paths.append(db_path)
        connection = await default_factory.connect(db_path)
        self.connections.append(connection)
        return connection


async def _is_closed(connection: Any) -> bool:
    try:
        await connection.execute("SELECT 1")
    except ValueError:
        return True
    return False


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[AdmissionShadowStore]:
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    try:
        yield shadow
    finally:
        await shadow.stop()


async def test_a_new_file_gets_four_tables_and_one_schema_version_row(tmp_path: Path) -> None:
    """S1 (kills ST-2)."""
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    assert shadow.path == tmp_path / "data" / STORE_FILENAME and STORE_FILENAME == "admission_shadow.db"
    assert shadow.is_open is False
    await shadow.start()
    assert shadow.is_open is True
    await shadow.stop()
    assert shadow.is_open is False
    assert await rows(shadow.path, TABLES) == [
        ("schema_version",), ("shadow_aggregates",), ("shadow_markers",), ("shadow_samples",),
    ]
    assert await rows(shadow.path, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]
    again = AdmissionShadowStore(data_dir=tmp_path / "data")
    await again.start()
    await again.stop()
    assert await rows(shadow.path, "SELECT version FROM schema_version") == [(1,)], "a restart adds no second row"


@pytest.mark.parametrize("versions", [(2,), (1, 1), (0,)], ids=["version-2", "two-rows", "version-0"])
async def test_a_file_with_other_schema_version_rows_is_refused_unchanged_and_closed(
    tmp_path: Path, versions: tuple[int, ...],
) -> None:
    """S2 (kills ST-1, ST-3)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / STORE_FILENAME
    db = await default_factory.connect(str(path))
    try:
        await db.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        await db.executemany("INSERT INTO schema_version (version) VALUES (?)", [(v,) for v in versions])
        await db.commit()
    finally:
        await db.close()
    before = path.read_bytes()
    factory = _RecordingFactory()
    shadow = AdmissionShadowStore(data_dir=data_dir, connection_factory=factory)
    try:
        with pytest.raises(RuntimeError, match="schema_version"):
            await shadow.start()
        assert shadow.is_open is False
        assert len(factory.connections) == 1 and await _is_closed(factory.connections[0])
    finally:
        for connection in factory.connections:
            await connection.close()
    assert path.read_bytes() == before
    assert await rows(path, TABLES) == [("schema_version",)]


async def test_a_batch_adds_its_counts_and_its_markers_count_what_it_wrote(store: AdmissionShadowStore) -> None:
    """S3 (kills ST-5, ST-6, ST-15, ST-17)."""
    first, second = utc_hour(T0), utc_hour(T0 + HOUR)
    assert (first, second, utc_day(T0)) == ("2026-10-28T12", "2026-10-28T13", "2026-10-28")  # premise
    verdict = refuse()
    batch = _batch(
        aggregates={
            _key(first, outcome="would_refuse", reason_code="identity_unresolved", bucket=10): 3,
            _key(first, bucket=3): 1,
            _key(second, work_kind="tool_call", seam="tool"): 2,
        },
        samples=[ShadowSample(first, T0, verdict, 1000)],
        offered={first: 4, second: 3},
        dropped={second: 1},
        samples_dropped={first: 1},
    )
    assert await store.write_batch(BOOT, batch) == 6
    aggregates = (
        "SELECT day, work_kind, seam, outcome, reason_code, latency_bucket, decisions FROM shadow_aggregates "
        "ORDER BY work_kind, outcome, latency_bucket"
    )
    assert await rows(store.path, aggregates) == [
        ("2026-10-28", "intent", "intent", "admit", "admitted", 3, 1),
        ("2026-10-28", "intent", "intent", "would_refuse", "identity_unresolved", 10, 3),
        ("2026-10-28", "tool_call", "tool", "admit", "admitted", 0, 2),
    ]
    assert await rows(store.path, MARKERS) == [(BOOT, first, 4, 4, 0, 1), (BOOT, second, 3, 2, 1, 0)]
    samples = await rows(
        store.path,
        "SELECT boot_id, hour, recorded_at, work_kind, seam, outcome, reason_code, latency_ns, verdict_json "
        "FROM shadow_samples",
    )
    assert [row[:8] for row in samples] == [
        (BOOT, first, T0, "intent", "intent", "would_refuse", "identity_unresolved", 1000),
    ]
    body = json.loads(samples[0][8])
    assert list(body) == list(VERDICT_KEYS) and body == verdict.to_dict()
    assert await store.write_batch(BOOT, batch) == 6
    assert [row[-1] for row in await rows(store.path, aggregates)] == [2, 6, 4], "a second write adds to each row"
    assert await rows(store.path, MARKERS) == [(BOOT, first, 8, 8, 0, 2), (BOOT, second, 6, 4, 2, 0)]


async def test_a_batch_that_fails_is_rolled_back_and_a_later_commit_does_not_land_it(
    store: AdmissionShadowStore,
) -> None:
    """S4: a NULL boot id fails the sample insert after the aggregate upsert ran (kills ST-8)."""
    hour = utc_hour(T0)
    failing = _batch(aggregates={_key(hour): 5}, samples=[ShadowSample(hour, T0, refuse(), 1)], offered={hour: 5})
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        await store.write_batch(None, failing)  # type: ignore[arg-type]
    assert await store.write_batch(BOOT, _batch(aggregates={_key(hour, bucket=1): 1}, offered={hour: 1})) == 1
    assert await rows(store.path, "SELECT latency_bucket, decisions FROM shadow_aggregates") == [(1, 1)]
    assert await rows(store.path, "SELECT COUNT(*) FROM shadow_samples") == [(0,)]
    assert await rows(store.path, "SELECT boot_id, offered, written FROM shadow_markers") == [(BOOT, 1, 1)]


async def test_the_sample_ring_keeps_the_newest_rows(store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """S5 (kills ST-7, ST-16)."""
    monkeypatch.setattr(store_module, "SAMPLE_RING_SIZE", 4)
    hour = utc_hour(T0)
    for first, last in ((0, 4), (4, 7)):
        samples = [ShadowSample(hour, T0 + n, refuse(), n) for n in range(first, last)]
        await store.write_batch(BOOT, _batch(samples=samples))
    assert await rows(store.path, "SELECT latency_ns FROM shadow_samples ORDER BY seq") == [(3,), (4,), (5,), (6,)]


async def test_prune_keeps_the_current_utc_day_and_the_34_before_it(store: AdmissionShadowStore) -> None:
    """S6 (kills ST-11, ST-12)."""
    old, kept, today = utc_hour(T0 - 35 * DAY_SECONDS), utc_hour(T0 - 34 * DAY_SECONDS), utc_hour(T0)
    await store.write_batch(BOOT, _batch(aggregates={_key(old): 1, _key(kept): 1, _key(today): 1}))
    first_kept_hour = T0 - 34 * DAY_SECONDS - 12 * HOUR
    edge = {utc_hour(first_kept_hour): 1, utc_hour(first_kept_hour - 1): 1}
    assert sorted(edge) == ["2026-09-23T23", "2026-09-24T00"]  # premise
    await store.write_batch(BOOT, _batch(offered=edge))
    assert await store.prune(T0) == (1, 2)
    assert await rows(store.path, "SELECT day FROM shadow_aggregates ORDER BY day") == [("2026-09-24",), ("2026-10-28",)]
    assert await rows(store.path, "SELECT hour FROM shadow_markers ORDER BY hour") == [
        ("2026-09-24T00",), ("2026-09-24T12",), ("2026-10-28T12",),
    ]


async def test_prune_deletes_whole_older_days_beyond_the_row_limit_and_never_the_current_day(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S7 (kills ST-9, ST-10)."""
    monkeypatch.setattr(store_module, "AGGREGATE_ROW_LIMIT", 3)
    aggregates = {_key(utc_hour(T0 - days * DAY_SECONDS), bucket=bucket): 1 for days in (2, 1, 0) for bucket in (0, 1)}
    await store.write_batch(BOOT, _batch(aggregates=aggregates))
    assert await store.prune(T0) == (4, 0)
    assert await rows(store.path, "SELECT DISTINCT day FROM shadow_aggregates") == [("2026-10-28",)]
    monkeypatch.setattr(store_module, "AGGREGATE_ROW_LIMIT", 1)
    assert await store.prune(T0) == (0, 0), "the current day is never deleted"
    assert await rows(store.path, "SELECT COUNT(*) FROM shadow_aggregates") == [(2,)]


async def test_prune_deletes_the_oldest_markers_beyond_the_row_limit(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S8 (kills ST-13, ST-14)."""
    monkeypatch.setattr(store_module, "MARKER_ROW_LIMIT", 2)
    await store.write_batch(BOOT, _batch(offered={utc_hour(T0 - n * HOUR): 0 for n in (11, 10, 9)}))
    assert await store.prune(T0) == (0, 1)
    assert await rows(store.path, "SELECT hour FROM shadow_markers ORDER BY hour") == [
        ("2026-10-28T02",), ("2026-10-28T03",),
    ]


def test_the_bounds_are_named_constants_and_a_day_of_keys_fits_the_row_limit() -> None:
    """S9: D10's values, and the most aggregate rows one day can hold is below the row limit."""
    assert (SCHEMA_VERSION, AGGREGATE_RETENTION_DAYS, AGGREGATE_ROW_LIMIT, SAMPLE_RING_SIZE) == (1, 35, 100_000, 5_000)
    assert (MARKER_RETENTION_DAYS, MARKER_ROW_LIMIT, DAY_SECONDS) == (35, 50_000, 86_400)
    one_day = len(WORK_KINDS) * len(SEAMS) * len(REASON_CODES) * LATENCY_BUCKETS
    assert one_day < AGGREGATE_ROW_LIMIT, one_day


async def test_writes_and_prunes_need_an_open_store_and_start_runs_once(tmp_path: Path) -> None:
    """S10."""
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    with pytest.raises(RuntimeError, match="not open"):
        await shadow.write_batch(BOOT, _batch())
    with pytest.raises(RuntimeError, match="not open"):
        await shadow.prune(T0)
    await shadow.start()
    try:
        with pytest.raises(RuntimeError, match="already open"):
            await shadow.start()
    finally:
        await shadow.stop()
    await shadow.stop()
    with pytest.raises(RuntimeError, match="not open"):
        await shadow.write_batch(BOOT, _batch())


def test_the_store_is_declared_optional_bounded_and_backed_up() -> None:
    """S11: the AD-1256 declaration, apart from its lifecycle owner."""
    assert "probos.admission.storage_declarations" in DECLARATION_MODULES
    declaration = load_default_store_registry().get("admission.shadow-decisions")
    assert declaration is not None
    assert (declaration.owner_module, declaration.owner_symbol, declaration.canonical_path) == (
        "probos.admission.store", "AdmissionShadowStore", STORE_FILENAME,
    )
    assert declaration.criticality is StoreCriticality.OPTIONAL and declaration.retention is StoreRetention.BOUNDED
    assert (declaration.backup, declaration.restore) == ("included", "unknown")


async def test_the_store_opens_through_the_injected_connection_factory(tmp_path: Path) -> None:
    """S12."""
    factory = _RecordingFactory()
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data", connection_factory=factory)
    await shadow.start()
    await shadow.stop()
    assert factory.paths == [str(tmp_path / "data" / STORE_FILENAME)]
    assert await _is_closed(factory.connections[0])
