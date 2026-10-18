"""BF-902 (#1579): the FTS keyword index goes with the episodes it indexes.

A real ``EpisodicMemory`` (real ChromaDB, FTS5 sidecar, ``ActivationTracker``, ``ParticipantIndex``,
``EvictionAuditLog`` and episode archive) on ``tmp_path``. The rig and the readers are AD-1340 S1's
(``test_ad1340_s1_eviction.py``), and the reset runs through the harness of ``test_reset_integration.py``. Stale FTS
rows are injected through a connection of our own, which reproduces the vessel's rows that name no episode. Every test
states its premise first, so a pass cannot be vacuous, and every wait is bounded.

T1 to T3: the Tier 2 reset. T4 to T11: the start-up reconciliation. T12 and T13: the counted eviction warning.
T14: the archive is not consulted. T15: keyword recall for live episodes is unchanged.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import sqlite3
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.activation_tracker import ActivationTracker
from probos.cognitive.episodic import _FTS_FILENAME, EpisodicMemory, _delete_fts_rows
from probos.cognitive.participant_index import ParticipantIndex
from probos.startup.cognitive_services import ACTIVATION_TRACKER_DB, PARTICIPANT_INDEX_DB
from probos.types import EpisodeStoreOutcome
from tests.test_ad1340_s1_eviction import _archive_rows, _episode, _ids, _memory, _query, _raw, _warnings
from tests.test_reset_integration import _create_sqlite_db, _run_reset

_UNSET: Any = object()
_WAIT_S = 10  # every await on production code is bounded; a mutant fails in seconds and never hangs
_LOGGER = "probos.cognitive.episodic"
_GOLDEN_QUERIES = ("coolant reading alpha", "bravo section coolant", "loop reading charlie")


# --- helpers -------------------------------------------------------------------------------------------------


def _fts(root: Path) -> Path:
    """The FTS5 sidecar of the S1 rig (``_memory``): beside the ChromaDB files."""
    return root / "chroma" / _FTS_FILENAME


def _inject(path: Path, rows: list[tuple[str, str]]) -> None:
    """Write FTS rows through a connection of our own, as the vessel's stale rows were written.

    Safe while a memory is open: its aiosqlite handle holds no open transaction between operations.
    """
    with contextlib.closing(sqlite3.connect(str(path), timeout=5)) as connection:
        connection.executemany("INSERT INTO episode_fts(episode_id, content) VALUES (?, ?)", rows)
        connection.commit()


def _rows(path: Path) -> list[tuple[int, str]]:
    return _query(path, "SELECT rowid, episode_id FROM episode_fts ORDER BY rowid")


def _count(path: Path, episode_id: str) -> int:
    return _query(path, "SELECT count(*) FROM episode_fts WHERE episode_id = ?", (episode_id,))[0][0]


def _content(path: Path, episode_id: str) -> list[str]:
    rows = _query(path, "SELECT content FROM episode_fts WHERE episode_id = ? ORDER BY rowid", (episode_id,))
    return [row[0] for row in rows]


def _stale(i: int) -> tuple[str, str]:
    """An FTS row whose id names no episode."""
    return (f"gone-{i:03d}", "gone crew coolant loop reading section archived text")


def _infos(caplog: pytest.LogCaptureFixture, needle: str) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO and needle in record.getMessage()
    ]


async def _store_episodes(em: EpisodicMemory, count: int) -> None:
    """Store ``_episode(0..count-1)``; each must be STORED, so every premise below is real."""
    for i in range(count):
        assert await asyncio.wait_for(em.store(_episode(i)), timeout=_WAIT_S) is EpisodeStoreOutcome.STORED


async def _reconcile(em: EpisodicMemory) -> int:
    return await asyncio.wait_for(em._reconcile_fts_index(), timeout=_WAIT_S)  # test-only private access


@contextlib.contextmanager
def _replaced(em: EpisodicMemory, attribute: str, replacement: Any) -> Iterator[Any]:
    """Interpose on a live attribute (test-only private access); the original goes back on the way out."""
    original = getattr(em, attribute)
    setattr(em, attribute, replacement)
    try:
        yield replacement
    finally:
        setattr(em, attribute, original)


class _GetProxy:
    """Forwards to the real ChromaDB collection and records the ids of each ``get``.

    ``fail_on_call`` is the 1-based number of the ``get`` call that raises; ``answer`` replaces every result.
    """

    def __init__(self, inner: Any, *, fail_on_call: int | None = None, answer: Any = _UNSET) -> None:
        self.inner = inner
        self.fail_on_call = fail_on_call
        self.answer = answer
        self.calls: list[list[str]] = []

    def get(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(list(kwargs.get("ids") or []))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("injected")
        if self.answer is not _UNSET:
            return self.answer
        return self.inner.get(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


class _FtsProxy:
    """Forwards to the real FTS connection (the pattern of S1's ``_FtsTailProxy``); injects one fault at a time.

    ``before_delete`` runs once, before the first reconciliation page delete (``DELETE ... WHERE rowid``).
    ``fail_delete_id`` makes the per-id eviction delete of that id raise. ``fail_commit`` makes one commit raise.
    ``failures`` counts the faults actually raised, so a test can prove its injection fired.
    """

    def __init__(
        self,
        inner: Any,
        *,
        before_delete: Callable[[], Awaitable[None]] | None = None,
        fail_delete_id: str | None = None,
        fail_commit: bool = False,
    ) -> None:
        self.inner = inner
        self.before_delete = before_delete
        self.fail_delete_id = fail_delete_id
        self.fail_commit = fail_commit
        self.failures = 0

    async def execute(self, sql: str, params: Any = ()) -> Any:
        if (
            self.fail_delete_id is not None
            and sql.lstrip().startswith("DELETE FROM episode_fts WHERE episode_id")
            and params[0] == self.fail_delete_id
        ):
            self.failures += 1
            raise sqlite3.OperationalError("injected")
        return await self.inner.execute(sql, params)

    async def executemany(self, sql: str, params: Any) -> Any:
        if self.before_delete is not None and sql.lstrip().startswith("DELETE FROM episode_fts WHERE rowid"):
            callback, self.before_delete = self.before_delete, None
            await callback()
        return await self.inner.executemany(sql, params)

    async def commit(self) -> Any:
        if self.fail_commit:
            self.fail_commit = False
            self.failures += 1
            raise sqlite3.OperationalError("injected")
        return await self.inner.commit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def _sentinel(tmp_path: Path) -> Path:
    """A knowledge file a Tier 2 reset deletes: proof that the reset used the temporary knowledge path."""
    return tmp_path / "knowledge" / "episodes" / "old.json"


async def _populated_data_dir(tmp_path: Path) -> Path:
    """A data directory in the production layout, written by the real stores, with every handle closed.

    The memory sits at ``data_dir / "episodic.db"``, so its ChromaDB files and the FTS sidecar are at the root of
    the data directory, where the reset looks for them.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    participants = ParticipantIndex(db_path=str(data_dir / PARTICIPANT_INDEX_DB))
    activations = ActivationTracker(db_path=str(data_dir / ACTIVATION_TRACKER_DB))
    em = EpisodicMemory(db_path=str(data_dir / "episodic.db"), relevance_threshold=0.0, eviction_disposition="delete")
    try:
        await participants.start()
        await activations.start()
        em.set_participant_index(participants)
        em.set_activation_tracker(activations)
        em.set_erasure_sidecar_paths(
            activation_db_path=str(data_dir / ACTIVATION_TRACKER_DB),
            participant_index_db_path=str(data_dir / PARTICIPANT_INDEX_DB),
        )
        await em.start()
        await _store_episodes(em, 2)
        await activations.record_access("ep-000")
    finally:
        await em.stop()
        await participants.stop()
        await activations.stop()
    sentinel = _sentinel(tmp_path)
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("{}", encoding="utf-8")
    return data_dir


def _assert_populated(data_dir: Path, tmp_path: Path) -> None:
    """The premise of T1 and T2: the four files exist and hold what the real stores wrote."""
    assert (data_dir / "chroma.sqlite3").exists()
    assert len(_rows(data_dir / _FTS_FILENAME)) == 2
    assert _query(data_dir / PARTICIPANT_INDEX_DB, "SELECT count(*) FROM episode_participants")[0][0] > 0
    assert _query(data_dir / ACTIVATION_TRACKER_DB, "SELECT count(*) FROM episode_access_log")[0][0] > 0
    assert _sentinel(tmp_path).exists()


async def _seed_stale_corpus(root: Path) -> Path:
    """T4 and T5: three live episodes, then eight FTS rows of which four name no episode. Returns the FTS file."""
    async with _memory(root, "delete") as rig:
        await _store_episodes(rig.em, 3)
    path = _fts(root)
    assert _rows(path) == [(1, "ep-000"), (2, "ep-001"), (3, "ep-002")]  # premise: the three live rows, no stale one
    _inject(path, [_stale(0), _stale(1), _stale(1), _stale(2), ("ep-000", "alpha duplicate row of a live episode")])
    rows = _rows(path)
    assert {eid for _, eid in rows} == {"ep-000", "ep-001", "ep-002", "gone-000", "gone-001", "gone-002"}
    assert len(rows) == 8
    assert _count(path, "ep-000") == 2
    return path


# --- T1 ------------------------------------------------------------------------------------------------------


async def test_tier2_reset_deletes_every_episode_index(tmp_path: Path) -> None:
    """A Tier 2 reset ("New ship, new crew") deletes the keyword, participant and activation indexes."""
    data_dir = await _populated_data_dir(tmp_path)
    _assert_populated(data_dir, tmp_path)

    _run_reset(data_dir, tmp_path)  # the default tier is Tier 2

    assert not (data_dir / "chroma.sqlite3").exists()
    assert not (data_dir / _FTS_FILENAME).exists()
    assert not (data_dir / PARTICIPANT_INDEX_DB).exists()
    assert not (data_dir / ACTIVATION_TRACKER_DB).exists()
    assert not _sentinel(tmp_path).exists()  # the reset used the temporary knowledge path, so it ran for real


# --- T2 ------------------------------------------------------------------------------------------------------


async def test_tier1_reset_keeps_every_episode_index(tmp_path: Path) -> None:
    """A Tier 1 reset keeps the episodes, so it keeps every index of them (no rebuild path exists for the FTS rows)."""
    data_dir = await _populated_data_dir(tmp_path)
    _create_sqlite_db(data_dir / "events.db", "events")  # a Tier 1 target: when it is gone, the soft reset ran
    _assert_populated(data_dir, tmp_path)
    assert (data_dir / "events.db").exists()

    _run_reset(data_dir, tmp_path, soft=True)

    assert not (data_dir / "events.db").exists()
    assert (data_dir / "chroma.sqlite3").exists()
    assert (data_dir / _FTS_FILENAME).exists()
    assert (data_dir / PARTICIPANT_INDEX_DB).exists()
    assert (data_dir / ACTIVATION_TRACKER_DB).exists()
    assert len(_rows(data_dir / _FTS_FILENAME)) == 2
    assert _sentinel(tmp_path).exists()  # Tier 1 does not touch the knowledge store


# --- T3 ------------------------------------------------------------------------------------------------------


def test_reset_table_lists_the_indexes_in_tier2_only() -> None:
    """The three index files are in Tier 2 (so in Tier 3, which runs cumulatively) and in no other tier's list."""
    from probos.__main__ import RESET_TIERS, _file_purpose

    expected = (
        (_FTS_FILENAME, "episode_fts.db", "Episode keyword index"),
        (PARTICIPANT_INDEX_DB, "participant_index.db", "Episode participant index"),
        (ACTIVATION_TRACKER_DB, "activation_tracker.db", "Episode activation log"),
    )
    for constant, name, purpose in expected:
        assert constant == name  # premise: the reset's name is the name the store writes
        assert name in RESET_TIERS[2]["files"]
        assert [tier for tier, tier_def in RESET_TIERS.items() if name in tier_def.get("files", [])] == [2]
        assert _file_purpose(name) == purpose


# --- T4 ------------------------------------------------------------------------------------------------------


async def test_start_removes_rows_that_name_no_live_episode(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """``start()`` deletes exactly the FTS rows whose id is not live; a duplicate row of a live episode stays."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    path = await _seed_stale_corpus(tmp_path)

    async with _memory(tmp_path, "delete"):  # its start() reconciles
        pass

    rows = _rows(path)
    assert {eid for _, eid in rows} == set(_ids(3))
    assert [_count(path, eid) for eid in _ids(3)] == [2, 1, 1]  # live rows unchanged, the duplicate included
    assert len(rows) == 4
    assert len(_infos(caplog, "BF-902: FTS reconciliation removed 4 of 8")) == 1


# --- T5 ------------------------------------------------------------------------------------------------------


async def test_reconciliation_is_idempotent(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A second reconciliation over a clean index deletes nothing and says so."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    path = await _seed_stale_corpus(tmp_path)

    async with _memory(tmp_path, "delete") as rig:
        reconciled = _rows(path)
        assert len(reconciled) == 4  # premise: the start-up reconciliation already cleaned the stale rows

        assert await _reconcile(rig.em) == 0

        assert _rows(path) == reconciled
        assert len(_infos(caplog, "removed 0 of 4")) == 1


# --- T6 ------------------------------------------------------------------------------------------------------


async def test_unreadable_collection_deletes_nothing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A collection read that raises stops the reconciliation before any delete, with one WARNING."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    async with _memory(tmp_path, "delete") as rig:
        em = rig.em
        path = _fts(rig.root)
        await _store_episodes(em, 1)
        _inject(path, [_stale(0), _stale(1)])
        before = _rows(path)
        assert [eid for _, eid in before] == ["ep-000", "gone-000", "gone-001"]  # premise: two stale rows to delete

        with _replaced(em, "_collection", _GetProxy(em._collection, fail_on_call=1)) as proxy:
            removed = await _reconcile(em)

        assert len(proxy.calls) == 1  # premise: the read was attempted, and it was the injected one that failed
        assert removed == 0
        assert _rows(path) == before
        assert len(_warnings(caplog, "stopped after removing 0")) == 1


# --- T7 ------------------------------------------------------------------------------------------------------


async def test_missing_collection_deletes_nothing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """With no collection the reconciliation deletes nothing and warns once."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    async with _memory(tmp_path, "delete") as rig:
        em = rig.em
        path = _fts(rig.root)
        await _store_episodes(em, 1)
        _inject(path, [_stale(0), _stale(1)])
        before = _rows(path)
        assert len(before) == 3  # premise: two stale rows to delete

        with _replaced(em, "_collection", None):
            removed = await _reconcile(em)

        assert removed == 0
        assert _rows(path) == before
        assert len(_warnings(caplog, "the episode collection is unavailable")) == 1


# --- T8 ------------------------------------------------------------------------------------------------------


async def test_answer_without_an_id_list_deletes_nothing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """An answer that is a mapping without an id list is not "nothing is live": it stops the reconciliation."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    async with _memory(tmp_path, "delete") as rig:
        em = rig.em
        path = _fts(rig.root)
        await _store_episodes(em, 1)
        _inject(path, [_stale(0), _stale(1)])
        before = _rows(path)
        assert len(before) == 3  # premise: two stale rows to delete

        with _replaced(em, "_collection", _GetProxy(em._collection, answer={"ids": None})) as proxy:
            removed = await _reconcile(em)

        assert len(proxy.calls) == 1  # premise: the answer was asked for, and it is the one that was refused
        assert removed == 0
        assert _rows(path) == before
        assert len(_warnings(caplog, "stopped after removing 0")) == 1


# --- T9 ------------------------------------------------------------------------------------------------------


async def test_pages_are_bounded_and_a_failed_page_keeps_what_came_before(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read asks about at most one page of ids; a failed page keeps the pages before it; the next run finishes."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    monkeypatch.setattr("probos.cognitive.episodic._FTS_RECONCILE_PAGE", 2)
    async with _memory(tmp_path, "delete") as rig:
        em = rig.em
        path = _fts(rig.root)
        _inject(path, [_stale(0), _stale(1)])  # rowids 1 and 2
        await _store_episodes(em, 3)  # rowids 3 to 5
        _inject(path, [_stale(2)])  # rowid 6
        assert [eid for _, eid in _rows(path)] == ["gone-000", "gone-001", "ep-000", "ep-001", "ep-002", "gone-002"]

        with _replaced(em, "_collection", _GetProxy(em._collection, fail_on_call=2)) as failing:
            first = await _reconcile(em)

        assert len(failing.calls) == 2  # premise: page 1 was read and deleted, page 2's read is the injected failure
        assert first == 2
        assert [eid for _, eid in _rows(path)] == ["ep-000", "ep-001", "ep-002", "gone-002"]
        assert len(_warnings(caplog, "stopped after removing 2")) == 1

        with _replaced(em, "_collection", _GetProxy(em._collection)) as healthy:
            second = await _reconcile(em)

        assert second == 1
        assert {eid for _, eid in _rows(path)} == set(_ids(3))
        assert failing.calls and healthy.calls
        assert all(len(ids) <= 2 for ids in failing.calls + healthy.calls)  # bounded by the page


# --- T10 -----------------------------------------------------------------------------------------------------


async def test_store_of_a_stale_id_during_a_page_waits_for_the_page_and_keeps_its_new_row(
    tmp_path: Path,
) -> None:
    """A ``store()`` of an id the page is deleting waits for the page's lock, and its new FTS row survives."""
    held: dict[str, Any] = {}
    async with _memory(tmp_path, "delete") as rig:
        em = rig.em
        path = _fts(rig.root)
        await _store_episodes(em, 1)
        _inject(path, [_stale(0)])
        returning = dataclasses.replace(_episode(5), id="gone-000", user_input="zulu fresh report of a returning id")

        async def _store_during_the_page() -> None:
            held["lock_held"] = em._get_store_write_lock().locked()  # test-only private access
            held["task"] = asyncio.create_task(em.store(returning))

        assert _raw(em, ["gone-000"])["ids"] == []  # premise: the id is not live, so its FTS row is stale
        assert _count(path, "gone-000") == 1
        assert em._get_store_write_lock().locked() is False  # premise: nothing but the page can hold the lock

        try:
            with _replaced(em, "_fts_db", _FtsProxy(em._fts_db, before_delete=_store_during_the_page)):
                removed = await _reconcile(em)
            assert "task" in held  # premise: the page reached its delete, and the store was started inside it
            outcome = await asyncio.wait_for(held["task"], timeout=_WAIT_S)
        finally:
            task = held.get("task")
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        assert removed == 1
        assert held["lock_held"] is True  # the page held the store write lock while it deleted
        assert outcome is EpisodeStoreOutcome.STORED
        assert _raw(em, ["gone-000"])["ids"] == ["gone-000"]
        assert _count(path, "gone-000") == 1
        content = _content(path, "gone-000")[0]
        assert "zulu" in content
        assert "archived" not in content  # the stale text is gone; this row is the new one


# --- T11 -----------------------------------------------------------------------------------------------------


async def test_a_row_that_reuses_a_freed_rowid_is_never_deleted(tmp_path: Path) -> None:
    """The page deletes a row by its (rowid, id) pair, so a live row that took a freed rowid is not matched."""
    held: dict[str, Any] = {}
    async with _memory(tmp_path, "delete") as rig:
        em = rig.em
        path = _fts(rig.root)
        await _store_episodes(em, 1)
        _inject(path, [_stale(0)])
        real = em._fts_db  # test-only private access

        async def _reuse_the_freed_rowid() -> None:
            cursor = await real.execute("SELECT rowid FROM episode_fts WHERE episode_id = ?", ("gone-000",))
            held["rowid"] = (await cursor.fetchone())[0]
            await real.execute("DELETE FROM episode_fts WHERE rowid = ?", (held["rowid"],))
            await real.execute(
                "INSERT INTO episode_fts(rowid, episode_id, content) "
                "VALUES (?, 'ep-000', 'alpha reused rowid live row')",
                (held["rowid"],),
            )
            await real.commit()

        assert _count(path, "ep-000") == 1  # premise: the live episode has its stored row only
        assert _count(path, "gone-000") == 1

        with _replaced(em, "_fts_db", _FtsProxy(real, before_delete=_reuse_the_freed_rowid)):
            await _reconcile(em)  # the return value counts the pairs asked for, so it is not asserted

        assert "rowid" in held  # premise: the page reached its delete, and the rowid was freed and reused inside it
        assert _count(path, "ep-000") == 2  # its stored row and the one at the reused rowid
        assert _count(path, "gone-000") == 0
        assert held["rowid"] in [rowid for rowid, eid in _rows(path) if eid == "ep-000"]


# --- T12 -----------------------------------------------------------------------------------------------------


async def test_failed_fts_delete_in_eviction_warns_with_a_count_and_the_next_start_repairs_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Failed cleanup, restart, repaired: eviction warns with the count, and the next start deletes the row."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    path = _fts(tmp_path)
    async with _memory(tmp_path, "delete") as rig:
        em = rig.em
        await _store_episodes(em, 3)
        assert [_count(path, eid) for eid in _ids(3)] == [1, 1, 1]  # premise: every episode has its FTS row

        with _replaced(em, "_fts_db", _FtsProxy(em._fts_db, fail_delete_id="ep-001")) as proxy:
            evicted = await asyncio.wait_for(em.evict_by_ids(_ids(3), reason="activation_pruning"), timeout=_WAIT_S)

        assert evicted == 3
        assert proxy.failures == 1  # premise: the injected delete failure fired, for ep-001 only
        assert _raw(em, _ids(3))["ids"] == []  # premise: none of the three is live
        assert [_count(path, eid) for eid in _ids(3)] == [0, 1, 0]  # the failure spared the other ids' cleanup
        assert len(_warnings(caplog, "could not clear 1 of 3")) == 1

    async with _memory(tmp_path, "delete"):  # its start() reconciles
        pass

    assert _count(path, "ep-001") == 0
    assert len(_infos(caplog, "removed 1 of 1")) == 1


# --- T13 -----------------------------------------------------------------------------------------------------


async def test_failed_fts_commit_in_eviction_warns_with_the_full_count(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed commit leaves nothing of the sweep durable, so the WARNING counts every id."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    async with _memory(tmp_path, "delete") as rig:
        em = rig.em
        await _store_episodes(em, 2)
        assert [_count(_fts(rig.root), eid) for eid in _ids(2)] == [1, 1]  # premise: both have an FTS row

        with _replaced(em, "_fts_db", _FtsProxy(em._fts_db, fail_commit=True)) as proxy:
            evicted = await asyncio.wait_for(em.evict_by_ids(_ids(2), reason="activation_pruning"), timeout=_WAIT_S)

        assert evicted == 2
        assert proxy.failures == 1  # premise: the injected commit failure fired
        assert _raw(em, _ids(2))["ids"] == []  # premise: both are gone from the live collection
        assert len(_warnings(caplog, "could not clear 2 of 2")) == 1


# --- T14 -----------------------------------------------------------------------------------------------------


async def test_an_archive_only_id_is_stale_for_the_fts_index(tmp_path: Path) -> None:
    """An id that is only in the archive is stale for the FTS index; the archive is neither read nor changed."""
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        path = _fts(rig.root)
        await _store_episodes(em, 2)
        assert await asyncio.wait_for(em.evict_by_ids(["ep-000"], reason="activation_decay"), timeout=_WAIT_S) == 1
        assert [row["episode_id"] for row in _archive_rows(rig.root)] == ["ep-000"]  # premise: archived
        assert _raw(em, ["ep-000"])["ids"] == []  # premise: not live
        assert _count(path, "ep-000") == 0  # premise: eviction removed its FTS row
        _inject(path, [("ep-000", "alpha archived leftover text")])
        assert _count(path, "ep-000") == 1  # premise: a leftover row for an archive-only id
        archived = _archive_rows(rig.root)

        assert await _reconcile(em) == 1

        assert _count(path, "ep-000") == 0
        assert _archive_rows(rig.root) == archived
        assert _count(path, "ep-001") == 1


# --- T15 -----------------------------------------------------------------------------------------------------


def _golden_stale(i: int) -> tuple[str, str]:
    """A stale row that repeats the golden queries' words, so it out-ranks live episodes under bm25."""
    return (f"gone-{i:03d}", "coolant reading loop section alpha bravo charlie " * 2)


async def _golden_search(em: EpisodicMemory, query: str) -> list[tuple[str, float]]:
    return await asyncio.wait_for(em.keyword_search(query, k=3), timeout=_WAIT_S)


async def test_keyword_recall_for_live_episodes_is_unchanged(tmp_path: Path) -> None:
    """Golden: stale rows take keyword slots; after a restart the same queries return the same ids and ranks."""
    async with _memory(tmp_path, "delete") as rig:
        em = rig.em
        await _store_episodes(em, 6)
        baseline = [await _golden_search(em, query) for query in _GOLDEN_QUERIES]
        assert all(hits and all(eid.startswith("ep-") for eid, _ in hits) for hits in baseline)  # premise: live hits

        _inject(_fts(rig.root), [_golden_stale(i) for i in range(4)])
        polluted = [await _golden_search(em, query) for query in _GOLDEN_QUERIES]
        displaced = [
            query
            for query, before, during in zip(_GOLDEN_QUERIES, baseline, polluted)
            if any(eid.startswith("gone-") for eid, _ in during)
            and not {eid for eid, _ in before} <= {eid for eid, _ in during}
        ]
        assert displaced  # premise: stale rows took slots and a live hit was displaced

    async with _memory(tmp_path, "delete") as rig:  # its start() reconciles
        restored = [await _golden_search(rig.em, query) for query in _GOLDEN_QUERIES]

    for query, before, after in zip(_GOLDEN_QUERIES, baseline, restored):
        assert [eid for eid, _ in after] == [eid for eid, _ in before], query
        assert [rank for _, rank in after] == pytest.approx([rank for _, rank in before], rel=1e-9, abs=1e-12), query


# --- T16 -----------------------------------------------------------------------------------------------------


async def test_a_failed_commit_with_no_ids_is_not_reported_as_cleared(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed commit is a failure even when there were no ids to delete: False, and one WARNING."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    async with _memory(tmp_path, "delete") as rig:
        proxy = _FtsProxy(rig.em._fts_db, fail_commit=True)  # test-only private access

        cleared = await asyncio.wait_for(_delete_fts_rows(proxy, []), timeout=_WAIT_S)

        assert proxy.failures == 1  # premise: the injected commit failure fired
        assert cleared is False
        assert len(_warnings(caplog, "could not clear 0 of 0")) == 1


# --- T17 -----------------------------------------------------------------------------------------------------


async def test_a_malformed_store_lock_degrades_the_reconciliation_instead_of_raising(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A store write lock that is not an asyncio.Lock stops the reconciliation with one WARNING; it never raises."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    async with _memory(tmp_path, "delete") as rig:
        em = rig.em
        path = _fts(rig.root)
        await _store_episodes(em, 1)
        _inject(path, [_stale(0)])
        before = _rows(path)
        assert [eid for _, eid in before] == ["ep-000", "gone-000"]  # premise: a stale row the run would delete

        with _replaced(em, "_store_write_lock", object()) as malformed:  # the real lock returns on the way out
            assert em._store_write_lock is malformed  # premise: the malformed lock is in place
            with pytest.raises(TypeError):
                em._get_store_write_lock()  # premise: the lock getter itself raises
            removed = await _reconcile(em)

        assert removed == 0
        assert _rows(path) == before
        assert len(_warnings(caplog, "stopped after removing 0")) == 1
