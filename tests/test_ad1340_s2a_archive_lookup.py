"""AD-1340 S2a (M1): the archive's recorded lookups, ``archive.lookups.lookup_by_id`` and ``.lookup_by_agent``.

Real SQLite on ``tmp_path``. A second, raw ``sqlite3`` connection is the independent witness for what is
committed. To pause a lookup between its unlocked read and its access transaction, a test holds
``archive._write_lock`` (test-only private access, as the S1 tests use ``archive._db``), shows that the lookup
task is NOT done after 0.3 s (so its read is complete and it waits on the lock), changes the file through the raw
connection, then releases the lock. Every wait is bounded. Every test states its premise first, so a pass
cannot be vacuous.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

import probos.cognitive.episode_archive as episode_archive
from probos.cognitive.episode_archive import (
    ArchiveLookupResult,
    ArchiveRecord,
    EpisodeArchive,
    EpisodeArchiveError,
    EpisodeArchiveIntegrityError,
    EpisodeArchiveUnavailable,
    decode_payload,
    encode_payload,
)

ARCHIVE_LOGGER = "probos.cognitive.episode_archive"
NOT_OPEN = r"^episode_archive_not_open$"
NOT_RECORDED = r"^episode_archive_access_not_recorded$"
LIMIT_INVALID = r"^episode_archive_lookup_limit_invalid$"
INDEX = "idx_episode_archive_agent_time"
ALL_ARCHIVE_ROWS = "SELECT * FROM episode_archive ORDER BY episode_id, content_hash"

# S1's schema, typed here on purpose: the two tables and ``idx_archive_access_episode``, no agent index.
_S1_DDL = """\
CREATE TABLE IF NOT EXISTS episode_archive (
    episode_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    episode_timestamp REAL NOT NULL,
    reason TEXT NOT NULL,
    archived_at REAL NOT NULL,
    payload_format INTEGER NOT NULL,
    payload BLOB NOT NULL,
    PRIMARY KEY (episode_id, content_hash)
);

CREATE TABLE IF NOT EXISTS archive_access (
    id INTEGER PRIMARY KEY,
    episode_id TEXT NOT NULL,
    accessed_at REAL NOT NULL,
    accessor TEXT NOT NULL,
    purpose TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_archive_access_episode
    ON archive_access(episode_id);
"""
# S1's INSERT column list: a writer that has never heard of the agent index.
_S1_INSERT = (
    "INSERT INTO episode_archive (episode_id, content_hash, agent_id, episode_timestamp, reason, archived_at, "
    "payload_format, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)


# --- helpers (copied from tests/test_ad1340_s1_archive_store.py, test-local) ----------------------------------------


def _record(i: int, **meta: Any) -> ArchiveRecord:
    metadata: dict[str, Any] = {
        "content_hash": f"{i:064x}",
        "agent_ids_json": '["agent-a"]',
        "timestamp": 1_700_000_000.0 + i,
    }
    metadata.update(meta)
    return ArchiveRecord(episode_id=f"ep-{i:03d}", document=f"document {i}", metadata=metadata)


def _rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """Read through a connection of our own: what another process would see on disk."""
    with contextlib.closing(sqlite3.connect(path, timeout=5)) as connection:
        return connection.execute(sql, params).fetchall()


def _write(path: Path, sql: str, params: tuple[Any, ...] = ()) -> None:
    with contextlib.closing(sqlite3.connect(path, timeout=5)) as connection:
        connection.execute(sql, params)
        connection.commit()


def _count(path: Path, table: str, episode_id: str | None = None) -> int:
    if episode_id is None:
        return _rows(path, f"SELECT count(*) FROM {table}")[0][0]
    return _rows(path, f"SELECT count(*) FROM {table} WHERE episode_id = ?", (episode_id,))[0][0]


@contextlib.asynccontextmanager
async def _started(archive: EpisodeArchive) -> AsyncIterator[EpisodeArchive]:
    await archive.start()
    try:
        yield archive
    finally:
        await archive.stop()


# --- helpers (S2a) -------------------------------------------------------------------------------------------------


def _ids(result: ArchiveLookupResult) -> list[str]:
    return [item.record.episode_id for item in result.episodes]


def _index_names(path: Path) -> list[str]:
    return [row[1] for row in _rows(path, "PRAGMA index_list(episode_archive)")]


def _create_s1_file(path: Path) -> None:
    """S1's DDL and ``user_version`` 1, as S1's ``start()`` leaves them. Idempotent, like S1's ``start()``."""
    with contextlib.closing(sqlite3.connect(path, timeout=5)) as connection:
        connection.executescript(_S1_DDL)
        connection.execute("PRAGMA user_version = 1")
        connection.commit()


def _insert_as_s1(path: Path, record: ArchiveRecord, *, agent_id: str = "agent-a") -> None:
    _write(
        path,
        _S1_INSERT,
        (
            record.episode_id, record.content_hash, agent_id, float(record.metadata["timestamp"]),
            "capacity", 1000.0, 1, encode_payload(record),
        ),
    )


@contextlib.asynccontextmanager
async def _write_lock_held(archive: EpisodeArchive) -> AsyncIterator[None]:
    """Hold the archive's write lock (test-only private access); always release it, even after a failed assertion."""
    await asyncio.wait_for(archive._write_lock.acquire(), timeout=5)
    try:
        yield
    finally:
        archive._write_lock.release()


async def _show_blocked(task: asyncio.Task[Any], what: str) -> None:
    done, _ = await asyncio.wait({task}, timeout=0.3)
    assert not done, f"{what} finished while the test held the write lock"


async def _settle(tasks: list[asyncio.Task[Any]]) -> None:
    finished, _ = await asyncio.wait(set(tasks), timeout=5)
    assert finished == set(tasks), "a task never finished after the write lock was released"


async def _cancel_pending(tasks: list[asyncio.Task[Any]]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def _lookup_changed_under(
    archive: EpisodeArchive,
    lookup: Callable[[], Awaitable[ArchiveLookupResult]],
    change_the_file: Callable[[], None],
) -> ArchiveLookupResult:
    """Run ``lookup`` with its access transaction held at the write lock, change the file raw, then let it finish."""
    tasks: list[asyncio.Task[Any]] = []
    try:
        async with _write_lock_held(archive):
            task = asyncio.create_task(lookup())
            tasks.append(task)
            await _show_blocked(task, "the lookup")  # premise: its read is complete and it waits for the lock
            change_the_file()
        await _settle(tasks)
        return task.result()
    finally:
        await _cancel_pending(tasks)


async def _arm_failing_access(archive: EpisodeArchive, episode_id: str) -> None:
    """A real SQLite failure for one id's access INSERT, on the archive's own connection (nothing else is affected)."""
    await archive._db.execute(  # test-only private access
        "CREATE TEMP TRIGGER fail_access BEFORE INSERT ON main.archive_access "
        f"WHEN NEW.episode_id = '{episode_id}' BEGIN SELECT RAISE(ABORT, 'injected access failure'); END"
    )
    await archive._db.commit()


class _GatedCommit:
    """Forwards everything to the real connection; its first ``commit()`` pauses until ``release`` is set."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self._gated = False

    async def commit(self) -> Any:
        if not self._gated:
            self._gated = True
            self.entered.set()
            await self.release.wait()
        return await self.inner.commit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


class _GatedRead(_GatedCommit):
    """First ``execute()`` pauses at ``point``: ``before_execute``, ``before_fetchall`` or ``after_fetchall``."""

    def __init__(self, inner: Any, point: str) -> None:
        super().__init__(inner)
        self.point = point
        self.raised: BaseException | None = None
        self.rows: list[Any] | None = None
        self._read_gated = False

    async def commit(self) -> Any:
        return await self.inner.commit()

    async def pause(self) -> None:
        self.entered.set()
        await self.release.wait()

    async def execute(self, sql: str, params: Any = ()) -> Any:
        if self._read_gated:
            return await self.inner.execute(sql, params)
        self._read_gated = True
        if self.point == "before_execute":
            await self.pause()
        try:
            return _GatedCursor(self, await self.inner.execute(sql, params))
        except Exception as exc:
            self.raised = exc
            raise


class _GatedCursor:
    def __init__(self, gate: _GatedRead, inner: Any) -> None:
        self._gate, self._inner = gate, inner

    async def fetchall(self) -> list[Any]:
        if self._gate.point == "before_fetchall":
            await self._gate.pause()
        try:
            rows = await self._inner.fetchall()
        except Exception as exc:
            self._gate.raised = exc
            raise
        self._gate.rows = rows
        if self._gate.point == "after_fetchall":
            await self._gate.pause()
        return rows

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def _stop_at(archive: EpisodeArchive, gate: _GatedRead, task: asyncio.Task[Any]) -> None:
    await asyncio.wait_for(gate.entered.wait(), timeout=5)  # premise: the lookup is paused inside its read
    await asyncio.wait_for(archive.stop(), timeout=5)
    assert not archive.is_open and not task.done()  # premise: the stop completed while the read was pending
    gate.release.set()


_MARKED =  ArchiveRecord(episode_id="ep-mark", document="marked", metadata={"content_hash": "h-mark", "timestamp": 1.0})


async def _arm_failing_write(archive: EpisodeArchive) -> None:
    """A real SQLite failure for the marked id, on the archive's own connection (nothing else is affected)."""
    await archive._db.execute(  # test-only private access
        "CREATE TEMP TRIGGER fail_marked BEFORE INSERT ON main.episode_archive WHEN NEW.episode_id = 'ep-mark' "
        "BEGIN SELECT RAISE(ABORT, 'injected write failure'); END"
    )
    await archive._db.commit()


# --- A-1, A-2: the schema ------------------------------------------------------------------------------------------


async def test_schema_adds_only_the_agent_time_index_and_keeps_version_1(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    assert not path.exists()  # premise: this start() builds the schema from nothing

    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert path.exists()
        # Premise: the witness reads the real tables (the primary-key index of episode_archive is there), and
        # the schema holds exactly S1's objects plus the one new index.
        assert sorted(_rows(path, "SELECT type, name FROM sqlite_master")) == [
            ("index", "idx_archive_access_episode"),
            ("index", INDEX),
            ("index", "sqlite_autoindex_episode_archive_1"),
            ("table", "archive_access"),
            ("table", "episode_archive"),
        ]

        index_list = {row[1]: row for row in _rows(path, "PRAGMA index_list(episode_archive)")}
        assert INDEX in index_list
        assert index_list[INDEX][2] == 0  # not unique: one agent can have two episodes at the same instant
        assert [row[2] for row in _rows(path, f"PRAGMA index_info({INDEX})")] == ["agent_id", "episode_timestamp"]
        assert [(row[1], row[2]) for row in _rows(path, "PRAGMA table_info(episode_archive)")] == [
            ("episode_id", "TEXT"),
            ("content_hash", "TEXT"),
            ("agent_id", "TEXT"),
            ("episode_timestamp", "REAL"),
            ("reason", "TEXT"),
            ("archived_at", "REAL"),
            ("payload_format", "INTEGER"),
            ("payload", "BLOB"),
        ]
        assert [row[1] for row in _rows(path, "PRAGMA table_info(archive_access)")] == [
            "id", "episode_id", "accessed_at", "accessor", "purpose",
        ]
        assert _rows(path, "PRAGMA user_version") == [(1,)]


async def test_an_s1_file_gains_the_index_and_stays_openable_by_s1(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    first, second = _record(1), _record(2)
    _create_s1_file(path)
    _insert_as_s1(path, first)
    # Premise: a real S1-shaped file: version 1, one row, and no agent index.
    assert _rows(path, "PRAGMA user_version") == [(1,)]
    assert _count(path, "episode_archive") == 1
    assert INDEX not in _index_names(path)

    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert INDEX in _index_names(path)
        assert _rows(path, "PRAGMA user_version") == [(1,)]
        found = await archive.lookups.lookup_by_agent("agent-a", accessor="test")
        assert [item.record for item in found.episodes] == [first]

    # S1 opening the S2a file: its DDL (all IF NOT EXISTS) changes nothing and the version it checks is still 1 ...
    _create_s1_file(path)
    assert INDEX in _index_names(path)
    assert _rows(path, "PRAGMA user_version") == [(1,)]
    # ... and an S1-shaped writer's row lands in the index anyway: SQLite maintains every index.
    _insert_as_s1(path, second)
    assert _rows(
        path, f"SELECT count(*) FROM episode_archive INDEXED BY {INDEX} WHERE agent_id = ?", ("agent-a",)
    ) == [(2,)]
    async with _started(archive):
        found = await archive.lookups.lookup_by_agent("agent-a", accessor="test")
        assert [item.record for item in found.episodes] == [second, first]  # newest first


# --- A-3, A-4: lookup by id ----------------------------------------------------------------------------------------


async def test_lookup_by_id_returns_the_record_and_one_committed_access_row(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    subject, bystander = _record(1), _record(2)
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([subject, bystander], reason="capacity") == frozenset(
            {subject.episode_id, bystander.episode_id}
        )
        assert _count(path, "episode_archive", subject.episode_id) == 1  # premise: the row is archived ...
        assert _count(path, "archive_access") == 0  # ... and nothing has been accessed yet
        stored_archived_at = _rows(
            path, "SELECT archived_at FROM episode_archive WHERE episode_id = ?", (subject.episode_id,)
        )[0][0]

        started = time.time()
        result = await archive.lookups.lookup_by_id(subject.episode_id, accessor="captain:test")
        finished = time.time()

        # The raw witness, read right after the call returned: exactly one COMMITTED access row for the id.
        access = _rows(path, "SELECT episode_id, accessor, purpose, accessed_at FROM archive_access")
        assert [row[:3] for row in access] == [(subject.episode_id, "captain:test", "lookup")]
        assert started <= access[0][3] <= finished

        assert isinstance(result, ArchiveLookupResult)
        assert len(result.episodes) == 1
        item = result.episodes[0]
        assert item.record == subject  # the document and the metadata, equal
        assert (item.agent_id, item.episode_timestamp, item.reason) == ("agent-a", 1_700_000_001.0, "capacity")
        assert item.archived_at == stored_archived_at
        assert (result.undecodable, result.withdrawn, result.truncated) == (0, 0, False)


async def test_lookup_of_an_unknown_id_is_empty_and_records_nothing(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    other = _record(1)
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([other], reason="capacity") == frozenset({other.episode_id})
        assert _count(path, "episode_archive") == 1  # premise: the archive is not empty, so an empty answer is real
        assert _count(path, "archive_access") == 0

        by_id = await archive.lookups.lookup_by_id("ep-unknown", accessor="test")
        by_agent = await archive.lookups.lookup_by_agent("agent-nobody", accessor="test")

        for result in (by_id, by_agent):
            assert result.episodes == ()
            assert (result.undecodable, result.withdrawn, result.truncated) == (0, 0, False)
        assert _count(path, "archive_access") == 0


# --- A-5: one row per episode id ----------------------------------------------------------------------------------


async def test_lookup_returns_only_the_latest_version_of_an_id(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    older = _record(1)
    newer = _record(1, content_hash=f"{99:064x}", variant="second")  # a second version of the same episode id
    assert older.content_hash < newer.content_hash  # premise: the tie rule below must pick `older`

    def set_archived_at(record: ArchiveRecord, value: float) -> None:
        _write(
            path,
            "UPDATE episode_archive SET archived_at = ? WHERE episode_id = ? AND content_hash = ?",
            (value, record.episode_id, record.content_hash),
        )

    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([older, newer], reason="capacity") == frozenset({older.episode_id})
        assert _count(path, "episode_archive", older.episode_id) == 2  # premise: two archived versions of one id
        assert _count(path, "archive_access") == 0
        lookups: tuple[Callable[[], Awaitable[ArchiveLookupResult]], ...] = (
            lambda: archive.lookups.lookup_by_id(older.episode_id, accessor="test"),
            lambda: archive.lookups.lookup_by_agent("agent-a", accessor="test"),
        )

        # The greater archived_at wins: `newer` (the larger hash, archived later).
        set_archived_at(older, 1000)
        set_archived_at(newer, 2000)
        recorded = 0
        for lookup in lookups:
            result = await lookup()
            assert [item.record for item in result.episodes] == [newer]
            assert [item.archived_at for item in result.episodes] == [2000.0]
            assert result.truncated is False
            recorded += 1
            assert _count(path, "archive_access", older.episode_id) == recorded  # one access row per lookup

        # An exact tie on archived_at keeps the smaller content_hash: `older`.
        set_archived_at(newer, 1000)
        for lookup in lookups:
            result = await lookup()
            assert [item.record for item in result.episodes] == [older]
            assert [item.archived_at for item in result.episodes] == [1000.0]
            assert result.truncated is False
            recorded += 1
            assert _count(path, "archive_access", older.episode_id) == recorded


# --- A-6, A-7, A-8: lookup by agent -------------------------------------------------------------------------------


async def test_lookup_by_agent_range_is_half_open_and_newest_first(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    records = [_record(1, timestamp=10.0), _record(2, timestamp=20.0), _record(3, timestamp=30.0)]
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive(records, reason="capacity") == frozenset(r.episode_id for r in records)
        assert [
            row[0] for row in _rows(path, "SELECT episode_timestamp FROM episode_archive ORDER BY episode_timestamp")
        ] == [10.0, 20.0, 30.0]  # premise: the stored episode times
        assert _count(path, "archive_access") == 0

        cases: list[tuple[dict[str, Any], list[float]]] = [
            ({"since": 10, "until": 30}, [20.0, 10.0]),  # half-open: t = 10 is in, t = 30 is out
            ({"since": None, "until": None}, [30.0, 20.0, 10.0]),  # both bounds open, newest first
            ({"since": 20}, [30.0, 20.0]),  # only the lower bound: inclusive
            ({"until": 20}, [10.0]),  # only the upper bound: exclusive
        ]
        recorded = 0
        for bounds, expected in cases:
            result = await archive.lookups.lookup_by_agent("agent-a", accessor="test", **bounds)
            assert [item.episode_timestamp for item in result.episodes] == expected, bounds
            assert result.truncated is False, bounds
            recorded += len(expected)
            assert _count(path, "archive_access") == recorded, bounds  # one access row per episode returned


async def test_lookup_by_agent_limit_and_truncation(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    records = [_record(i) for i in range(1, 52)]  # ep-001 .. ep-051, newer with each i
    newest_first = [record.episode_id for record in reversed(records)]
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive(records, reason="capacity") == frozenset(r.episode_id for r in records)
        assert _count(path, "episode_archive") == 51  # premise: one more row than the default limit
        assert _count(path, "archive_access") == 0

        default = await archive.lookups.lookup_by_agent("agent-a", accessor="test")
        assert _ids(default) == newest_first[:50]  # the 50 newest; ep-001 is the one left out
        assert default.truncated is True
        assert _count(path, "archive_access") == 50
        assert _count(path, "archive_access", "ep-001") == 0

        exact = await archive.lookups.lookup_by_agent("agent-a", limit=51, accessor="test")
        assert _ids(exact) == newest_first
        assert exact.truncated is False

        widest = await archive.lookups.lookup_by_agent("agent-a", limit=200, accessor="test")  # the maximum is accepted
        assert _ids(widest) == newest_first
        assert widest.truncated is False

        one = await archive.lookups.lookup_by_agent("agent-a", limit=1, accessor="test")
        assert _ids(one) == newest_first[:1]
        assert one.truncated is True
        assert _count(path, "archive_access") == 50 + 51 + 51 + 1

        recorded = _count(path, "archive_access")
        for bad in (0, 201, True, False, -1, 50.0):
            with pytest.raises(ValueError, match=LIMIT_INVALID):
                await archive.lookups.lookup_by_agent("agent-a", limit=bad, accessor="test")  # never clamped
        assert _count(path, "archive_access") == recorded  # a refused lookup records nothing


async def test_lookup_by_agent_matches_the_primary_agent_only(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    shared = _record(1, agent_ids_json='["agent-b", "agent-a"]')
    no_agents = ArchiveRecord("ep-002", "document 2", {"content_hash": f"{2:064x}", "timestamp": 1_700_000_002.0})
    empty_agents = _record(3, agent_ids_json="[]")
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([shared, no_agents, empty_agents], reason="capacity") == frozenset(
            {"ep-001", "ep-002", "ep-003"}
        )
        # Premise: what was stored as each episode's primary agent (the AD-541f rule).
        assert _rows(path, "SELECT episode_id, agent_id FROM episode_archive ORDER BY episode_id") == [
            ("ep-001", "agent-b"), ("ep-002", "unknown"), ("ep-003", "unknown"),
        ]

        assert _ids(await archive.lookups.lookup_by_agent("agent-b", accessor="test")) == ["ep-001"]
        assert _ids(await archive.lookups.lookup_by_agent("agent-a", accessor="test")) == []  # second participant: not found
        assert _ids(await archive.lookups.lookup_by_agent("unknown", accessor="test")) == ["ep-003", "ep-002"]


# --- A-9: one bad row ---------------------------------------------------------------------------------------------


async def test_one_undecodable_row_never_hides_the_others(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "episode_archive.db"
    records = [_record(1), _record(2), _record(3)]
    corrupt = records[1]
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive(records, reason="capacity") == frozenset(r.episode_id for r in records)
        _write(path, "UPDATE episode_archive SET payload = ? WHERE episode_id = ?", (b"not zlib", corrupt.episode_id))
        # Premise: three rows, and the corrupt one really does not decode.
        assert _count(path, "episode_archive") == 3
        stored = _rows(
            path,
            "SELECT episode_id, content_hash, payload_format, payload FROM episode_archive WHERE episode_id = ?",
            (corrupt.episode_id,),
        )[0]
        with pytest.raises(EpisodeArchiveIntegrityError):
            decode_payload(*stored)
        assert _count(path, "archive_access") == 0

        with caplog.at_level(logging.WARNING, logger=ARCHIVE_LOGGER):
            result = await archive.lookups.lookup_by_agent("agent-a", accessor="test")

        assert _ids(result) == ["ep-003", "ep-001"]  # the other two, newest first
        assert (result.undecodable, result.withdrawn, result.truncated) == (1, 0, False)
        assert _count(path, "archive_access", corrupt.episode_id) == 0  # not returned, so not accessed
        assert _count(path, "archive_access") == 2
        warnings = [r for r in caplog.records if r.name == ARCHIVE_LOGGER and r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert corrupt.episode_id in warnings[0].getMessage()

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=ARCHIVE_LOGGER):
            alone = await archive.lookups.lookup_by_id(corrupt.episode_id, accessor="test")
        assert alone.episodes == ()
        assert (alone.undecodable, alone.withdrawn, alone.truncated) == (1, 0, False)
        assert _count(path, "archive_access") == 2  # the corrupt row is still not accessed


# --- A-10, A-11, A-12: the access transaction ----------------------------------------------------------------------


async def test_a_row_erased_after_the_read_is_withdrawn_and_leaves_no_access_row(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    subject = _record(1)
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([subject], reason="capacity") == frozenset({subject.episode_id})
        assert _count(path, "episode_archive", subject.episode_id) == 1  # premise: the row is there to be read
        assert _count(path, "archive_access") == 0

        result = await _lookup_changed_under(
            archive,
            lambda: archive.lookups.lookup_by_id(subject.episode_id, accessor="test"),
            lambda: _write(path, "DELETE FROM episode_archive WHERE episode_id = ?", (subject.episode_id,)),
        )

        assert _count(path, "episode_archive", subject.episode_id) == 0  # the raw delete did happen
        assert result.episodes == ()
        assert (result.undecodable, result.withdrawn, result.truncated) == (0, 1, False)
        assert _count(path, "archive_access") == 0


async def test_a_row_replaced_after_the_read_is_withdrawn(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    subject = _record(1)
    replacement = ArchiveRecord(subject.episode_id, "a different document under the same key", dict(subject.metadata))
    replacement_bytes = encode_payload(replacement)
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([subject], reason="capacity") == frozenset({subject.episode_id})
        stored = _rows(path, "SELECT payload FROM episode_archive WHERE episode_id = ?", (subject.episode_id,))[0][0]
        # Premise: the replacement is a valid payload for the same key, and its bytes differ from the stored ones.
        assert bytes(stored) == encode_payload(subject)
        assert replacement_bytes != bytes(stored)
        assert decode_payload(subject.episode_id, subject.content_hash, 1, replacement_bytes) == replacement
        assert _count(path, "archive_access") == 0

        result = await _lookup_changed_under(
            archive,
            lambda: archive.lookups.lookup_by_id(subject.episode_id, accessor="test"),
            lambda: _write(
                path,
                "UPDATE episode_archive SET payload = ? WHERE episode_id = ? AND content_hash = ?",
                (replacement_bytes, subject.episode_id, subject.content_hash),
            ),
        )

        assert _rows(path, "SELECT payload FROM episode_archive WHERE episode_id = ?", (subject.episode_id,)) == [
            (replacement_bytes,)
        ]  # the raw replace did happen
        assert result.episodes == ()
        assert (result.undecodable, result.withdrawn, result.truncated) == (0, 1, False)
        assert _count(path, "archive_access") == 0


async def test_a_failed_access_write_returns_nothing_and_leaves_no_access_row(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    records = [_record(1), _record(2), _record(3)]
    ids = tuple(record.episode_id for record in records)
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive(records, reason="capacity") == frozenset(ids)
        assert _count(path, "archive_access") == 0  # premise: nothing accessed yet
        # By-agent order is newest first (ep-003, ep-002, ep-001), so ep-002 is the SECOND access INSERT: the
        # first is already pending on the shared connection when the second fails.
        await _arm_failing_access(archive, "ep-002")

        with pytest.raises(EpisodeArchiveError, match=NOT_RECORDED) as raised:
                    await archive.lookups.lookup_by_agent("agent-a", accessor="test")
        assert isinstance(raised.value.__cause__, sqlite3.IntegrityError)  # the real SQLite failure, chained
        assert "injected access failure" in str(raised.value.__cause__)

        # A later commit on the same connection would make any access row left pending durable.
        await archive.record_access("ep-other", accessor="test", purpose="after")
        assert _count(path, "archive_access", "ep-other") == 1  # the later commit happened
        assert _rows(path, "SELECT count(*) FROM archive_access WHERE episode_id IN (?, ?, ?)", ids) == [(0,)]

        # The connection is not wedged: a lookup that does not touch the armed id still works.
        after = await archive.lookups.lookup_by_id("ep-001", accessor="test")
        assert _ids(after) == ["ep-001"]
        assert _count(path, "archive_access", "ep-001") == 1


# --- A-13: erasure ------------------------------------------------------------------------------------------------


async def test_erase_removes_the_access_rows_a_lookup_wrote(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    first, second = _record(1), _record(2)
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([first, second], reason="capacity") == frozenset(
            {first.episode_id, second.episode_id}
        )

        # (a) A lookup, then an erase.
        looked_up = await archive.lookups.lookup_by_id(first.episode_id, accessor="test")
        assert _ids(looked_up) == [first.episode_id]
        assert _count(path, "archive_access", first.episode_id) == 1  # premise: the lookup left an access row
        assert await archive.erase([first.episode_id]) == frozenset({first.episode_id})
        assert _count(path, "episode_archive", first.episode_id) == 0
        assert _count(path, "archive_access", first.episode_id) == 0

        # (b) The erase arrives while the lookup's access transaction waits for the lock: first in, first out.
        assert _count(path, "episode_archive", second.episode_id) == 1  # premise: a row to look up and erase
        assert _count(path, "archive_access", second.episode_id) == 0
        tasks: list[asyncio.Task[Any]] = []
        try:
            async with _write_lock_held(archive):
                lookup_task = asyncio.create_task(archive.lookups.lookup_by_id(second.episode_id, accessor="test"))
                tasks.append(lookup_task)
                await _show_blocked(lookup_task, "the lookup")  # premise: its read is done and it waits for the lock
                erase_task = asyncio.create_task(archive.erase([second.episode_id]))
                tasks.append(erase_task)
                await _show_blocked(erase_task, "the erase")  # premise: it queues behind the lookup
            await _settle(tasks)

            assert _ids(lookup_task.result()) == [second.episode_id]  # the lookup committed first and returned
            assert erase_task.result() == frozenset({second.episode_id})
        finally:
            await _cancel_pending(tasks)
        assert _count(path, "episode_archive", second.episode_id) == 0
        assert _count(path, "archive_access", second.episode_id) == 0


# --- A-14, A-15: unavailable and invalid ---------------------------------------------------------------------------


async def test_lookup_on_a_closed_archive_raises_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    subject = _record(1)

    async def refused(archive: EpisodeArchive) -> None:
        with pytest.raises(EpisodeArchiveUnavailable, match=NOT_OPEN):
            await archive.lookups.lookup_by_id(subject.episode_id, accessor="test")
        with pytest.raises(EpisodeArchiveUnavailable, match=NOT_OPEN):
            await archive.lookups.lookup_by_agent("agent-a", accessor="test")

    archive = EpisodeArchive(str(path))
    assert archive.is_open is False  # premise: never started
    await refused(archive)
    assert not path.exists()  # a refused lookup creates nothing

    async with _started(archive):
        assert archive.is_open is True  # premise: the same calls are answered while it is open
        assert await archive.archive([subject], reason="capacity") == frozenset({subject.episode_id})
        assert _ids(await archive.lookups.lookup_by_id(subject.episode_id, accessor="test")) == [subject.episode_id]
        assert _ids(await archive.lookups.lookup_by_agent("agent-a", accessor="test")) == [subject.episode_id]
    assert archive.is_open is False  # premise: stopped
    await refused(archive)
    assert _count(path, "archive_access") == 2  # only the two lookups made while it was open


async def test_lookup_validates_its_arguments(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    subject = _record(1)
    not_text: Any = None
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([subject], reason="capacity") == frozenset({subject.episode_id})
        assert _ids(await archive.lookups.lookup_by_agent("agent-a", since=1.0, until=2e12, accessor="test")) == ["ep-001"]
        recorded = _count(path, "archive_access")  # premise: valid arguments are answered (and recorded)
        assert recorded == 1

        cases: list[tuple[Callable[[], Awaitable[ArchiveLookupResult]], str]] = [
            (lambda: archive.lookups.lookup_by_id("", accessor="test"), "episode_archive_lookup_id_invalid"),
            (lambda: archive.lookups.lookup_by_id(not_text, accessor="test"), "episode_archive_lookup_id_invalid"),
            (lambda: archive.lookups.lookup_by_agent("", accessor="test"), "episode_archive_lookup_agent_invalid"),
            (lambda: archive.lookups.lookup_by_agent(not_text, accessor="test"), "episode_archive_lookup_agent_invalid"),
            (lambda: archive.lookups.lookup_by_id("ep-001", accessor=""), "episode_archive_lookup_accessor_invalid"),
            (lambda: archive.lookups.lookup_by_id("ep-001", accessor="  \t "), "episode_archive_lookup_accessor_invalid"),
            (lambda: archive.lookups.lookup_by_id("ep-001", accessor=not_text), "episode_archive_lookup_accessor_invalid"),
            (lambda: archive.lookups.lookup_by_agent("agent-a", accessor=""), "episode_archive_lookup_accessor_invalid"),
            (lambda: archive.lookups.lookup_by_agent("agent-a", accessor=" "), "episode_archive_lookup_accessor_invalid"),
            (
                lambda: archive.lookups.lookup_by_agent("agent-a", since=float("nan"), accessor="test"),
                "episode_archive_lookup_range_invalid",
            ),
            (
                lambda: archive.lookups.lookup_by_agent("agent-a", until=float("nan"), accessor="test"),
                "episode_archive_lookup_range_invalid",
            ),
            (
                lambda: archive.lookups.lookup_by_agent("agent-a", since=5.0, until=5.0, accessor="test"),
                "episode_archive_lookup_range_invalid",
            ),
            (
                lambda: archive.lookups.lookup_by_agent("agent-a", since=6.0, until=5.0, accessor="test"),
                "episode_archive_lookup_range_invalid",
            ),
            (  # AD-1340 S2a A3.2: an explicit infinite bound is refused like NaN (D5)
                lambda: archive.lookups.lookup_by_agent("agent-a", since=-float("inf"), accessor="test"),
                "episode_archive_lookup_range_invalid",
            ),
            (
                lambda: archive.lookups.lookup_by_agent("agent-a", since=float("inf"), accessor="test"),
                "episode_archive_lookup_range_invalid",
            ),
            (
                lambda: archive.lookups.lookup_by_agent("agent-a", until=float("inf"), accessor="test"),
                "episode_archive_lookup_range_invalid",
            ),
            (
                lambda: archive.lookups.lookup_by_agent("agent-a", until=-float("inf"), accessor="test"),
                "episode_archive_lookup_range_invalid",
            ),
        ]
        for call, code in cases:
            with pytest.raises(ValueError, match=rf"^{code}$"):
                await call()
        assert _count(path, "archive_access") == recorded  # a refused lookup records nothing


# --- A-16: lookups never change the archive ------------------------------------------------------------------------


async def test_lookups_change_no_archive_row(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    records = [_record(1), _record(2), _record(3), _record(4), _record(9, agent_ids_json='["agent-z"]')]
    replaced = ArchiveRecord("ep-002", "a different document under the same key", dict(records[1].metadata))
    original_payload = encode_payload(records[1])
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive(records, reason="capacity") == frozenset(r.episode_id for r in records)
        before = _rows(path, ALL_ARCHIVE_ROWS)
        assert len(before) == 5  # premise: five archived rows ...
        assert _count(path, "archive_access") == 0  # ... and no access row yet
        returned = 0

        by_id = await archive.lookups.lookup_by_id("ep-001", accessor="test")
        by_agent = await archive.lookups.lookup_by_agent("agent-a", accessor="test")
        unknown = await archive.lookups.lookup_by_id("ep-unknown", accessor="test")
        assert (len(by_id.episodes), len(by_agent.episodes), len(unknown.episodes)) == (1, 4, 0)
        returned += 1 + 4

        # A withdrawn lookup: the row is replaced under it (and put back afterwards), so the table is only ever
        # compared when no raw writer has touched it.
        tampered: list[list[tuple[Any, ...]]] = []

        def replace_the_row() -> None:
            _write(
                path,
                "UPDATE episode_archive SET payload = ? WHERE episode_id = ?",
                (encode_payload(replaced), "ep-002"),
            )
            tampered.append(_rows(path, ALL_ARCHIVE_ROWS))

        withdrawn = await _lookup_changed_under(
            archive, lambda: archive.lookups.lookup_by_id("ep-002", accessor="test"), replace_the_row
        )
        assert (withdrawn.episodes, withdrawn.withdrawn) == ((), 1)
        assert tampered[0] != before  # premise: the raw writer did change the table
        assert _rows(path, ALL_ARCHIVE_ROWS) == tampered[0]  # and the lookup changed nothing on top of it
        _write(path, "UPDATE episode_archive SET payload = ? WHERE episode_id = ?", (original_payload, "ep-002"))

        # A failed lookup (A-12's trigger).
        await _arm_failing_access(archive, "ep-004")
        with pytest.raises(EpisodeArchiveError, match=NOT_RECORDED):
            await archive.lookups.lookup_by_id("ep-004", accessor="test")

        assert _rows(path, ALL_ARCHIVE_ROWS) == before
        assert _count(path, "archive_access") == returned  # grew by exactly the episodes returned


# --- A-17, A-18: nothing left behind, and the index is used ---------------------------------------------------------


async def test_erase_leaves_no_agent_trace_in_the_file(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    marker = b"agent-s2a-marker-7f3a9c"
    subject = _record(1, agent_ids_json='["agent-s2a-marker-7f3a9c"]')
    bystander = _record(2)
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([subject, bystander], reason="capacity") == frozenset(
            {subject.episode_id, bystander.episode_id}
        )
        found = await archive.lookups.lookup_by_agent(marker.decode(), accessor="test")
        assert _ids(found) == [subject.episode_id]
        assert _count(path, "archive_access", subject.episode_id) == 1
    # Premise: before the erase the agent id's bytes are in the file, in the table row and in the agent index.
    assert path.read_bytes().count(marker) >= 2

    async with _started(archive):
        assert await archive.erase([subject.episode_id]) == frozenset({subject.episode_id})
        assert (await archive.lookups.lookup_by_agent(marker.decode(), accessor="test")).episodes == ()
    assert [entry.name for entry in tmp_path.iterdir()] == ["episode_archive.db"]
    assert marker not in path.read_bytes()  # secure_delete overwrote the row and its index entry
    assert _count(path, "episode_archive", subject.episode_id) == 0
    assert _count(path, "archive_access", subject.episode_id) == 0
    assert _count(path, "episode_archive", bystander.episode_id) == 1  # only the erased episode went
    assert b"agent-a" in path.read_bytes()


async def test_the_agent_lookup_uses_the_index(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    records = [_record(1), _record(2), _record(3)]
    plan_sql = "EXPLAIN QUERY PLAN " + episode_archive._LOOKUP_BY_AGENT_SQL  # test-only private access
    params = ("agent-a", 0.0, 4_000_000_000.0, 51)

    def plan() -> str:
        return " | ".join(str(row[3]) for row in _rows(path, plan_sql, params))

    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive(records, reason="capacity") == frozenset(r.episode_id for r in records)
    # Premise: with the index dropped the plan does not name it, so the assertion below can fail.
    _write(path, f"DROP INDEX {INDEX}")
    assert INDEX not in _index_names(path)
    assert INDEX not in plan()

    async with _started(archive):  # start() creates the missing index again
        assert INDEX in _index_names(path)
        assert INDEX in plan()


# --- A-19: a failing archive() never rolls back a lookup's access row ---------------------------------------------


async def test_a_failing_archive_write_never_rolls_back_a_lookups_access_row(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    subject = _record(1)
    tasks: list[asyncio.Task[Any]] = []
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([subject], reason="capacity") == frozenset({subject.episode_id})
        assert _count(path, "archive_access", subject.episode_id) == 0  # premise: no access row yet
        await _arm_failing_write(archive)
        real = archive._db  # test-only private access
        archive._db = gate = _GatedCommit(real)
        try:
            lookup_task = asyncio.create_task(archive.lookups.lookup_by_id(subject.episode_id, accessor="test"))
            tasks.append(lookup_task)
            await asyncio.wait_for(gate.entered.wait(), timeout=5)  # the access row is inserted, not committed
            archive_task = asyncio.create_task(archive.archive([_MARKED], reason="capacity"))
            tasks.append(archive_task)
            done, _ = await asyncio.wait({archive_task}, timeout=0.3)
            assert not done  # the archive waits for the lookup's transaction
            gate.release.set()
            finished, _ = await asyncio.wait({lookup_task, archive_task}, timeout=5)
            assert finished == {lookup_task, archive_task}, "a task never finished after the release"

            result = lookup_task.result()
            assert _ids(result) == [subject.episode_id]
            assert (result.undecodable, result.withdrawn, result.truncated) == (0, 0, False)
            with pytest.raises(sqlite3.IntegrityError, match="injected write failure"):
                archive_task.result()
            assert _rows(
                path, "SELECT purpose FROM archive_access WHERE episode_id = ?", (subject.episode_id,),
            ) == [("lookup",)]  # exactly one committed row: the returned record was audited
            assert _count(path, "episode_archive", _MARKED.episode_id) == 0
        finally:
            gate.release.set()
            archive._db = real
            await _cancel_pending(tasks)


# --- A-20, A-21, A-22: a stop() at any await of a lookup is unavailability (Amendment A3) ---------------------------


@pytest.mark.parametrize("point", ["before_execute", "before_fetchall"])
async def test_a_stop_during_the_read_raises_unavailable(tmp_path: Path, point: str) -> None:
    path = tmp_path / "episode_archive.db"
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        await archive.archive([_record(0)], reason="capacity")
        assert _count(path, "episode_archive", "ep-000") == 1  # premise: there is a row to read
        archive._db = gate = _GatedRead(archive._db, point)  # test-only private access
        task = asyncio.create_task(archive.lookups.lookup_by_id("ep-000", accessor="test"))
        try:
            await _stop_at(archive, gate, task)
            with pytest.raises(EpisodeArchiveUnavailable, match=NOT_OPEN) as caught:
                await asyncio.wait_for(task, timeout=5)
        finally:
            await _cancel_pending([task])
    assert isinstance(gate.raised, Exception) and not isinstance(gate.raised, EpisodeArchiveError)  # premise
    assert caught.value.__cause__ is gate.raised
    assert _count(path, "archive_access") == 0


@pytest.mark.parametrize(("episode_id", "n_rows"), [("ep-unknown", 0), ("ep-000", 1)])
async def test_a_stop_after_the_read_never_answers(tmp_path: Path, episode_id: str, n_rows: int) -> None:
    path = tmp_path / "episode_archive.db"
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        await archive.archive([_record(0)], reason="capacity")
        assert _count(path, "episode_archive", "ep-000") == 1  # premise: there is a row to read
        archive._db = gate = _GatedRead(archive._db, "after_fetchall")  # test-only private access
        task = asyncio.create_task(archive.lookups.lookup_by_id(episode_id, accessor="test"))
        try:
            await _stop_at(archive, gate, task)
            assert gate.raised is None and gate.rows is not None and len(gate.rows) == n_rows  # premise: the read succeeded
            with pytest.raises(EpisodeArchiveUnavailable, match=NOT_OPEN):
                await asyncio.wait_for(task, timeout=5)
        finally:
            await _cancel_pending([task])
    assert _count(path, "archive_access") == 0


async def test_a_read_failure_on_an_open_archive_keeps_its_type(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        await archive.archive([_record(0)], reason="capacity")
        _write(path, "DROP TABLE episode_archive")
        assert archive.is_open  # premise: the archive is open while its table is gone
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            await archive.lookups.lookup_by_id("ep-000", accessor="test")
        assert archive.is_open
