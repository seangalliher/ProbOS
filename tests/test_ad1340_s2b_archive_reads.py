"""AD-1340 S2b (M1): every unlocked archive read goes through one stop guard, and ``get_records`` takes the lookup's version.

Real ``EpisodeArchive`` on ``tmp_path``. A second, raw ``sqlite3`` connection (``_rows`` / ``_write``) is the
independent witness for what is on disk and the way a test plants or re-times a row. The helpers are the S2a test
module's. To pause a read inside one of its awaits, a test gates ``archive._db`` with ``_GatedRead`` (test-only
private access, as the S1 and S2a tests do), stops the archive while the read is paused, then releases it. Every
wait is bounded and no test sleeps. Every test states its premise first, so a pass cannot be vacuous. A tie on
``archived_at`` is forced with ``_write``, never left to the clock (back-to-back ``time.time()`` calls can return
one value on Windows).
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.episode_archive import (
    ArchiveRecord,
    EpisodeArchive,
    EpisodeArchiveError,
    EpisodeArchiveIntegrityError,
    EpisodeArchiveUnavailable,
    decode_payload,
)
from tests.test_ad1340_s2a_archive_lookup import (
    NOT_OPEN,
    _cancel_pending,
    _count,
    _GatedRead,
    _record,
    _rows,
    _started,
    _stop_at,
    _write,
)

UNDECODABLE = r"^episode_archive_payload_undecodable$"
FIRST, SECOND = "1" * 64, "2" * 64
VERSIONS_OF_EP_000 = (
    "SELECT content_hash, archived_at FROM episode_archive WHERE episode_id = 'ep-000' ORDER BY content_hash"
)


async def _drain(archive: EpisodeArchive, yielded: list[ArchiveRecord] | None = None) -> list[ArchiveRecord]:
    """Drain ``iter_records``; each record is appended to ``yielded`` (the caller's list, if given) as it arrives."""
    records = [] if yielded is None else yielded
    async for record in archive.iter_records():
        records.append(record)
    return records


#: The four service reads, each asked about ``ep-000`` (``iter_records`` is drained), as a coroutine for ``create_task``.
_READS: dict[str, Callable[[EpisodeArchive], Coroutine[Any, Any, Any]]] = {
    "get_records": lambda archive: archive.get_records(["ep-000"]),
    "archived_keys": lambda archive: archive.archived_keys(["ep-000"]),
    "get_versions": lambda archive: archive.get_versions(["ep-000"]),
    "iter_records": _drain,
}


# --- B-1, B-2: get_records takes the lookup's version (Decision D7) ------------------------------------------------


async def test_get_records_takes_the_lookup_version_on_a_tie_and_on_a_newer_row(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    small = _record(0, content_hash=FIRST, marker="small")
    large = _record(0, content_hash=SECOND, marker="large")
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([small, large], reason="capacity") == frozenset({"ep-000"})
        _write(path, "UPDATE episode_archive SET archived_at = 5000.0 WHERE episode_id = 'ep-000'")
        assert _rows(path, VERSIONS_OF_EP_000) == [(FIRST, 5000.0), (SECOND, 5000.0)]  # premise: an exact tie, forced

        records = await archive.get_records(["ep-000"])
        shown = await archive.lookups.lookup_by_id("ep-000", accessor="test")
        assert records == [small]  # the tie keeps the smallest content_hash
        assert records[0].content_hash == FIRST
        assert [item.record for item in shown.episodes] == records  # a restore puts back what the lookup showed

        _write(
            path,
            "UPDATE episode_archive SET archived_at = 5001.0 WHERE episode_id = 'ep-000' AND content_hash = ?",
            (SECOND,),
        )
        assert _rows(path, VERSIONS_OF_EP_000) == [(FIRST, 5000.0), (SECOND, 5001.0)]  # premise: the larger hash is newer

        records = await archive.get_records(["ep-000"])
        shown = await archive.lookups.lookup_by_id("ep-000", accessor="test")
        assert records == [large]  # the newer row wins over the smaller hash
        assert records[0].content_hash == SECOND
        assert [item.record for item in shown.episodes] == records


async def test_get_records_decodes_only_the_latest_version(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    bad_hash, corrupt = "0" * 64, b"\x00corrupt\xff"
    good = _record(0, content_hash=FIRST)  # not the default hash: _record(0) is keyed by "0" * 64, the planted key
    versions_by_age = (
        "SELECT content_hash, archived_at FROM episode_archive WHERE episode_id = 'ep-000' ORDER BY archived_at"
    )
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([good], reason="capacity") == frozenset({"ep-000"})
        _write(path, "UPDATE episode_archive SET archived_at = 2.0 WHERE episode_id = 'ep-000'")
        _write(  # a corrupt payload, planted raw, as test_ad1340_s1_archive_store.py plants one
            path,
            "INSERT INTO episode_archive (episode_id, content_hash, agent_id, episode_timestamp, reason, "
            "archived_at, payload_format, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ep-000", bad_hash, "agent-a", 123.5, "capacity", 1.0, 1, corrupt),
        )
        with pytest.raises(EpisodeArchiveIntegrityError, match=UNDECODABLE):  # premise: it really is corrupt
            decode_payload("ep-000", bad_hash, 1, corrupt)
        assert _rows(path, versions_by_age) == [(bad_hash, 1.0), (good.content_hash, 2.0)]  # premise: the corrupt row is older

        assert await archive.get_records(["ep-000"]) == [good]  # the older, undecodable version never blocks it

        _write(
            path,
            "UPDATE episode_archive SET archived_at = 3.0 WHERE episode_id = 'ep-000' AND content_hash = ?",
            (bad_hash,),
        )
        assert _rows(path, versions_by_age) == [(good.content_hash, 2.0), (bad_hash, 3.0)]  # premise: now the latest
        with pytest.raises(EpisodeArchiveIntegrityError, match=UNDECODABLE):
            await archive.get_records(["ep-000"])


# --- B-3, B-4, B-5: the guard on the four service reads (F-140; Decision D6) -----------------------------------------


@pytest.mark.parametrize("point", ["before_fetchall", "after_fetchall"])
@pytest.mark.parametrize("read", ["get_records", "archived_keys", "get_versions", "iter_records"])
async def test_a_stop_during_each_service_read_raises_unavailable(tmp_path: Path, read: str, point: str) -> None:
    path = tmp_path / "episode_archive.db"
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        await archive.archive([_record(0)], reason="capacity")
        assert _count(path, "episode_archive", "ep-000") == 1  # premise: there is a row to read
        archive._db = gate = _GatedRead(archive._db, point)  # test-only private access
        yielded: list[ArchiveRecord] = []  # what iter_records yields: a row read across a stop() must never be
        task = asyncio.create_task(_drain(archive, yielded) if read == "iter_records" else _READS[read](archive))
        try:
            await _stop_at(archive, gate, task)
            if point == "after_fetchall":
                assert gate.raised is None and gate.rows is not None and len(gate.rows) == 1  # premise: the read succeeded
            with pytest.raises(EpisodeArchiveUnavailable, match=NOT_OPEN) as caught:
                await asyncio.wait_for(task, timeout=5)
            assert yielded == []  # a row read across a stop() is never yielded (the other three reads never fill it)
        finally:
            await _cancel_pending([task])
    if point == "before_fetchall":
        assert isinstance(gate.raised, Exception) and not isinstance(gate.raised, EpisodeArchiveError)  # premise
        assert caught.value.__cause__ is gate.raised


async def test_a_service_read_failure_on_an_open_archive_keeps_its_type(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        await archive.archive([_record(0)], reason="capacity")
        _write(path, "DROP TABLE episode_archive")
        assert archive.is_open  # premise: the archive is open while its table is gone
        for read in _READS.values():
            with pytest.raises(sqlite3.OperationalError, match="no such table"):
                await read(archive)
        assert archive.is_open


async def test_service_reads_of_nothing_on_a_closed_archive_are_unavailable(tmp_path: Path) -> None:
    archive = EpisodeArchive(str(tmp_path / "episode_archive.db"))
    assert not archive.is_open  # premise: never started
    for read in (archive.get_records, archive.archived_keys, archive.get_versions):
        with pytest.raises(EpisodeArchiveUnavailable, match=NOT_OPEN):
            await read([])
