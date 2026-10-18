"""AD-1340 S2b (M2): eviction holds the store write lock per chunk, re-reads before it deletes, and types a stop().

The real ``EpisodicMemory`` on ``tmp_path`` with every sidecar and the archive wired (the S1 rig). The store write
lock is swapped for an ``_ObservedLock`` (test-only private access, as the S1 tests do), so a test can hold it, see
that an eviction waits on it, and count how often the eviction takes it. Every interleaving is a gate the test
creates and resolves; no test sleeps and every wait is bounded. Every test states its premise first, so a pass cannot
be vacuous. No assertion orders rows by time (back-to-back ``time.time()`` calls can return one value on Windows):
archive rows are ordered by episode id and audit rows by rowid.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.episode_archive import EpisodeErasureIncomplete, decode_payload
from probos.cognitive.eviction_audit import DISPOSITION_ERASED
from probos.security.pii_redaction import LogRedactionFormatter
from probos.types import EpisodeStoreOutcome, EvictionDisposition
from tests.test_ad1340_s1_erasure import _GONE, _traces
from tests.test_ad1340_s1_eviction import (
    _archive_rows,
    _audit_rows,
    _CollectionProxy,
    _episode,
    _ids,
    _memory,
    _raw,
    _record_collection,
    _Rig,
    _sidecar_counts,
    _warnings,
)
from tests.test_ad1340_s1_restore_reset import _SUBJECT, _cancel_all, _canonical, _FtsTailProxy, _ObservedLock

_CHUNK = "probos.cognitive.episodic._EVICTION_LOCK_CHUNK"
_VALID_UNTIL = 1234567890.0
_NO_SIDECARS = {"fts": 0, "activation": 0, "participants": 0}


# --- helpers -------------------------------------------------------------------------------------------------


def _witness(monkeypatch: pytest.MonkeyPatch, owner: Any, name: str, lock: asyncio.Lock, seen: list[bool]) -> None:
    """Wrap the coroutine function ``owner.<name>`` so that each call first records whether ``lock`` is held."""
    original = getattr(owner, name)

    async def _wrapped(*args: Any, **kwargs: Any) -> Any:
        seen.append(lock.locked())
        return await original(*args, **kwargs)

    monkeypatch.setattr(owner, name, _wrapped)


@dataclasses.dataclass
class _Behind:
    """An eviction run while the test held the store lock: what it returned, the lock, and the lock's state per write."""

    result: Any
    observed: _ObservedLock
    archive_locked: list[bool]
    participants_locked: list[bool]

    @property
    def eviction_acquisitions(self) -> int:
        return self.observed.acquisitions - 1  # the test's own hold is the first acquisition


async def _evict_behind_a_held_lock(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch, operation: Callable[[], Awaitable[Any]],
) -> _Behind:
    """Hold the store lock, start ``operation`` (an eviction), prove it waits for the lock, release, let it finish."""
    em = rig.em
    observed = _ObservedLock()
    em._store_write_lock = observed  # test-only private access: the store write lock, observed
    archive_locked: list[bool] = []
    participants_locked: list[bool] = []
    _witness(monkeypatch, em._episode_archive, "archive", observed, archive_locked)  # test-only private access
    _witness(monkeypatch, rig.participants, "delete_episodes", observed, participants_locked)
    tasks: list[asyncio.Task[Any]] = []
    holding = True
    await observed.acquire()  # the test is a store() in the middle of its locked write
    try:
        task = asyncio.create_task(operation())
        tasks.append(task)
        await asyncio.wait_for(asyncio.shield(observed.contended), timeout=5)  # the eviction reached the store lock
        assert not task.done()  # premise: it waits there ...
        assert _archive_rows(rig.root) == []  # premise: ... having archived nothing
        observed.release()
        holding = False
        result = await asyncio.wait_for(task, timeout=10)
    finally:
        if holding:
            observed.release()
        await _cancel_all(tasks)
    return _Behind(result, observed, archive_locked, participants_locked)


def _change_after_the_snapshot(
    monkeypatch: pytest.MonkeyPatch, rig: _Rig, hook: str, changed: dict[str, Any],
) -> list[str]:
    """Plant one metadata update of ``_SUBJECT``, once, between an eviction's archive snapshot and its delete.

    The gated stand-in for a metadata updater that takes no store lock. ``hook`` is where it lands: right after
    ``archive()`` returns ("archive"), or just before the eviction audit is written ("audit"). Returns the log of
    runs, so a test can state "the update ran exactly once" as its premise.
    """
    em = rig.em
    ran: list[str] = []

    def _update_once() -> None:
        if not ran:
            ran.append(hook)
            em._collection.update(ids=[_SUBJECT], metadatas=[changed])  # test-only private access

    original_archive = em._episode_archive.archive
    original_audit = em._eviction_audit.record_batch_eviction

    async def _archive_then_update(*args: Any, **kwargs: Any) -> Any:
        result = await original_archive(*args, **kwargs)
        _update_once()
        return result

    async def _update_then_audit(*args: Any, **kwargs: Any) -> Any:
        _update_once()
        return await original_audit(*args, **kwargs)

    if hook == "archive":
        monkeypatch.setattr(em._episode_archive, "archive", _archive_then_update)
    else:
        monkeypatch.setattr(em._eviction_audit, "record_batch_eviction", _update_then_audit)
    return ran


def _archived(rig: _Rig, episode_id: str) -> list[Any]:
    """Every archived record of one episode, decoded from its row (the archive's own decoder proves the key)."""
    return [
        decode_payload(row["episode_id"], row["content_hash"], row["payload_format"], row["payload"])
        for row in _archive_rows(rig.root)
        if row["episode_id"] == episode_id
    ]


# --- L-1, L-2: eviction takes the store lock per chunk (D2) ----------------------------------------------------


async def test_capacity_eviction_holds_the_store_lock_per_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-1340 S2b L-1: a capacity eviction waits for the store lock, then takes it once per chunk, writes inside it."""
    monkeypatch.setattr(_CHUNK, 2)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        for i in range(6):
            assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        em.max_episodes = 1  # test-only: five of the six are now over the budget
        assert sorted(_raw(em, _ids(6))["ids"]) == _ids(6)  # premise: all six are live ...
        assert _archive_rows(rig.root) == [] and _audit_rows(rig.root) == []  # ... and nothing was evicted yet

        behind = await _evict_behind_a_held_lock(rig, monkeypatch, em._evict)  # test-only private access

        assert [row["episode_id"] for row in _archive_rows(rig.root)] == _ids(5)  # the five oldest were archived ...
        assert _raw(em, _ids(6))["ids"] == ["ep-005"]  # ... and only the newest is still live
        assert behind.eviction_acquisitions == 3  # one hold per chunk: two, two, one
        # The audit holds one row per episode, each carrying its chunk's batch text, in the order the chunks ran.
        assert [row["details"] for row in _audit_rows(rig.root)] == (
            ["batch of 2, budget=1"] * 4 + ["batch of 1, budget=1"]
        )
        assert behind.archive_locked == [True, True, True]  # every archive write was made inside the lock
        assert behind.participants_locked == [True, True, True]  # and so was every sidecar cleanup


async def test_dream_eviction_holds_the_store_lock_per_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-1340 S2b L-2: a dream eviction (``evict_by_ids``, not ERASE) holds the store lock per chunk the same way."""
    monkeypatch.setattr(_CHUNK, 2)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        for i in range(6):
            assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        assert sorted(_raw(em, _ids(6))["ids"]) == _ids(6)  # premise: all six are live ...
        assert _archive_rows(rig.root) == [] and _audit_rows(rig.root) == []  # ... and nothing was evicted yet

        behind = await _evict_behind_a_held_lock(
            rig, monkeypatch, lambda: em.evict_by_ids(_ids(5), reason="activation_decay"),
        )

        assert behind.result == 5
        assert [row["episode_id"] for row in _archive_rows(rig.root)] == _ids(5)
        assert _raw(em, _ids(6))["ids"] == ["ep-005"]
        assert behind.eviction_acquisitions == 3  # one hold per chunk: two, two, one
        assert [row["details"] for row in _audit_rows(rig.root)] == (
            ["batch of 2, reason=activation_decay"] * 4 + ["batch of 1, reason=activation_decay"]
        )
        assert behind.archive_locked == [True, True, True]
        assert behind.participants_locked == [True, True, True]


# --- L-4, L-4b: the pre-delete re-read (D4, prerequisite (c)) --------------------------------------------------


@pytest.mark.parametrize("hook", ["archive", "audit"])
async def test_eviction_keeps_an_episode_whose_metadata_changed_after_its_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, hook: str,
) -> None:
    """AD-1340 S2b L-4: an id updated after its archive snapshot is not deleted; its next eviction archives the change.

    ``hook`` places the update right after ``archive()`` returns or just before the audit is written: either way
    it lands between the snapshot and the delete, and only the re-read just before the delete can see it.
    """
    caplog.set_level(logging.WARNING)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        for i in range(2):
            assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        before = dict(_raw(em, [_SUBJECT])["metadatas"][0])
        changed = {**before, "valid_until": _VALID_UNTIL}
        assert before.get("valid_until") != _VALID_UNTIL  # premise: the update really changes the record
        indexed = {eid: _sidecar_counts(rig.root, eid) for eid in (_SUBJECT, "ep-001")}
        assert all(rows["fts"] == 1 and rows["participants"] == 2 for rows in indexed.values())  # premise: both indexed
        ran = _change_after_the_snapshot(monkeypatch, rig, hook, changed)

        removed = await em.evict_by_ids([_SUBJECT, "ep-001"], reason="activation_decay")

        assert ran == [hook]  # premise: the update ran once, between the snapshot and the delete
        assert removed == 1  # only the unchanged episode was deleted
        assert _raw(em, ["ep-001"])["ids"] == [] and len(_archived(rig, "ep-001")) == 1  # ep-001: gone, archived
        live = _raw(em, [_SUBJECT])
        assert live["ids"] == [_SUBJECT]  # ep-000 stays live ...
        assert live["metadatas"][0]["valid_until"] == _VALID_UNTIL  # ... with the change
        assert _sidecar_counts(rig.root, _SUBJECT) == indexed[_SUBJECT]  # ... and keeps its index rows
        assert _sidecar_counts(rig.root, "ep-001") == _NO_SIDECARS  # while ep-001's were cleaned
        (snapshot,) = _archived(rig, _SUBJECT)
        assert _canonical(snapshot.metadata) == _canonical(before)  # the archive row is the snapshot, not the change
        assert _warnings(caplog, "changed after their archive snapshot")

        assert await em.evict_by_ids([_SUBJECT], reason="activation_decay") == 1  # the next eviction takes it
        assert _raw(em, [_SUBJECT])["ids"] == []
        (replaced,) = _archived(rig, _SUBJECT)  # still one archive row for it ...
        assert _canonical(replaced.metadata) == _canonical(changed)  # ... now holding the change

        await em.restore_from_archive(_SUBJECT)
        assert _canonical(_raw(em, [_SUBJECT])["metadatas"][0]) == _canonical(changed)  # a restore brings it back


async def test_an_eviction_whose_every_id_changed_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-1340 S2b L-4b: when every archived id changed, nothing is deleted and ``delete`` is never called empty."""
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        before = dict(_raw(em, [_SUBJECT])["metadatas"][0])
        changed = {**before, "valid_until": _VALID_UNTIL}
        ran = _change_after_the_snapshot(monkeypatch, rig, "archive", changed)
        proxy = _record_collection(em)

        removed = await em.evict_by_ids([_SUBJECT], reason="activation_decay")

        assert ran == ["archive"]  # premise: the one id changed between its snapshot and its delete
        assert removed == 0
        assert "delete" not in [name for name, _ in proxy.calls]  # no delete at all, not even an empty one
        live = _raw(em, [_SUBJECT])
        assert live["ids"] == [_SUBJECT]
        assert live["metadatas"][0]["valid_until"] == _VALID_UNTIL


class _FailNextGet(_CollectionProxy):
    """A recording collection proxy whose next ``get`` raises once, when armed."""

    armed = False
    fired = 0

    def get(self, **kwargs: Any) -> Any:
        self.calls.append(("get", kwargs.get("include")))
        if self.armed:
            self.armed = False
            self.fired += 1
            raise RuntimeError("injected: re-read failed")
        return self.inner.get(**kwargs)


async def test_a_failed_re_read_keeps_every_archived_id_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """AD-1340 S2b L-4c (D4): a re-read that fails deletes nothing; the next eviction completes the job."""
    caplog.set_level(logging.WARNING)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        ids = [_SUBJECT, "ep-001"]
        for i in range(2):
            assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        assert sorted(_raw(em, ids)["ids"]) == sorted(ids)  # premise: both live
        indexed = {eid: _sidecar_counts(rig.root, eid) for eid in ids}
        assert all(rows["fts"] == 1 and rows["participants"] == 2 for rows in indexed.values())  # premise: indexed
        proxy = _FailNextGet(em._collection)  # test-only private access
        em._collection = proxy  # installed before the call
        original_archive = em._episode_archive.archive

        async def _archive_then_arm(*args: Any, **kwargs: Any) -> Any:
            result = await original_archive(*args, **kwargs)
            # Nothing reads the collection between archive() and the re-read, so the next get() is the re-read.
            proxy.armed = True
            return result

        monkeypatch.setattr(em._episode_archive, "archive", _archive_then_arm)

        removed = await em.evict_by_ids(ids, reason="activation_decay")

        assert proxy.fired == 1  # premise: the re-read was reached and failed
        assert removed == 0
        assert "delete" not in [name for name, _ in proxy.calls]  # growth, never loss: no delete at all
        assert sorted(_raw(em, ids)["ids"]) == sorted(ids)  # both still live ...
        assert {eid: _sidecar_counts(rig.root, eid) for eid in ids} == indexed  # ... with their index rows
        assert all(len(_archived(rig, eid)) == 1 for eid in ids)  # both were archived: the archive committed first
        assert _warnings(caplog, "the re-read before an eviction delete failed")

        monkeypatch.setattr(em._episode_archive, "archive", original_archive)  # the hook is removed
        assert proxy.armed is False
        assert await em.evict_by_ids(ids, reason="activation_decay") == 2  # the next eviction completes the job
        assert _raw(em, ids)["ids"] == []
        assert all(len(_archived(rig, eid)) == 1 for eid in ids)
        assert all(_sidecar_counts(rig.root, eid) == _NO_SIDECARS for eid in ids)


_STORED_VALUE_MARKER = "STORED-VALUE-MARKER-7"


class _MarkedFailNextGet(_FailNextGet):
    """``_FailNextGet`` whose injected failure carries stored content in its text, as a Chroma rejection can."""

    def get(self, **kwargs: Any) -> Any:
        self.calls.append(("get", kwargs.get("include")))
        if self.armed:
            self.armed = False
            self.fired += 1
            raise RuntimeError(f"injected: re-read failed on {_STORED_VALUE_MARKER}")
        return self.inner.get(**kwargs)


async def test_a_failed_re_read_warning_carries_no_exception_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """AD-1340 S2b L-4e (review F1): the re-read warning names the exception type, never its text or traceback.

    The archive exists so that ERASE can remove every copy of an episode; an exception text that carries a stored
    value must not be copied into a log, where the production formatter does not mask arbitrary stored content.
    """
    caplog.set_level(logging.WARNING)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        ids = [_SUBJECT, "ep-001"]
        for i in range(2):
            assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        proxy = _MarkedFailNextGet(em._collection)  # test-only private access
        em._collection = proxy  # installed before the call
        original_archive = em._episode_archive.archive

        async def _archive_then_arm(*args: Any, **kwargs: Any) -> Any:
            result = await original_archive(*args, **kwargs)
            proxy.armed = True  # nothing reads the collection between archive() and the re-read
            return result

        monkeypatch.setattr(em._episode_archive, "archive", _archive_then_arm)

        assert await em.evict_by_ids(ids, reason="activation_decay") == 0

        assert proxy.fired == 1  # premise: the re-read was reached and failed with the marked text
        formatter = LogRedactionFormatter("%(message)s")  # the production formatter
        records = [
            record for record in caplog.records
            if record.name == "probos.cognitive.episodic" and record.levelno == logging.WARNING
            and "the re-read before an eviction delete failed" in record.getMessage()
        ]
        assert len(records) == 1  # premise: the warning exists ...
        assert "RuntimeError" in records[0].getMessage()  # ... and names the exception type
        assert records[0].exc_info is None
        assert _STORED_VALUE_MARKER not in formatter.format(records[0])  # formatting appends a traceback if exc_info is set


@pytest.mark.parametrize("error", [TypeError, ValueError])
async def test_an_id_whose_live_record_cannot_be_encoded_stays_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, error: type[Exception],
) -> None:
    """AD-1340 S2b L-4d (D4): a live record that no longer encodes is not the one archived, so it is not deleted."""
    caplog.set_level(logging.WARNING)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        assert _raw(em, [_SUBJECT])["ids"] == [_SUBJECT]  # premise: live
        indexed = _sidecar_counts(rig.root, _SUBJECT)
        assert indexed["fts"] == 1 and indexed["participants"] == 2  # premise: indexed
        reached: list[Any] = []

        def _raises(record: Any) -> bytes:
            reached.append(record)
            raise error("injected: the live record cannot be encoded")

        # In episodic.py only the pre-delete comparison uses this name; the archive writes use episode_archive's.
        monkeypatch.setattr("probos.cognitive.episodic.encode_payload", _raises)

        removed = await em.evict_by_ids([_SUBJECT], reason="activation_decay")

        assert len(reached) == 1  # premise: the comparison reached the patched encoder
        assert removed == 0
        assert _raw(em, [_SUBJECT])["ids"] == [_SUBJECT]
        assert _sidecar_counts(rig.root, _SUBJECT) == indexed
        assert len(_archived(rig, _SUBJECT)) == 1  # the snapshot
        assert _warnings(caplog, "changed after their archive snapshot")

        monkeypatch.undo()
        assert await em.evict_by_ids([_SUBJECT], reason="activation_decay") == 1
        assert _raw(em, [_SUBJECT])["ids"] == []


# --- L-6: a store() tail that is still indexing keeps its id live (D2) -----------------------------------------


@pytest.mark.parametrize("mode", ["archive", "delete"])
async def test_eviction_keeps_an_id_whose_store_tail_is_pending(tmp_path: Path, mode: str) -> None:
    """AD-1340 S2b L-6: an eviction skips an id whose store() is still writing its FTS and participant rows."""
    tasks: list[asyncio.Task[Any]] = []
    async with _memory(tmp_path, mode) as rig:
        em = rig.em
        loop = asyncio.get_running_loop()
        entered: asyncio.Future[None] = loop.create_future()
        release: asyncio.Future[None] = loop.create_future()

        async def _hold_the_tail() -> None:
            entered.set_result(None)
            await release

        real = em._fts_db  # test-only private access
        em._fts_db = _FtsTailProxy(real, _hold_the_tail)
        try:
            store_task = asyncio.create_task(em.store(_episode(0)))
            tasks.append(store_task)
            await asyncio.wait_for(asyncio.shield(entered), timeout=5)  # the store reached its FTS insert
            assert not store_task.done()  # premise: it is paused there, in its tail ...
            assert _raw(em, [_SUBJECT])["ids"] == [_SUBJECT]  # premise: the episode is already live ...
            assert _SUBJECT in em._get_store_tails()  # premise: ... and its tail is pending (test-only private access)

            assert await asyncio.wait_for(em.evict_by_ids([_SUBJECT], reason="activation_decay"), timeout=10) == 0

            assert _raw(em, [_SUBJECT])["ids"] == [_SUBJECT]  # still live
            assert _audit_rows(rig.root) == []  # nothing was audited
            if mode == "archive":
                assert _archive_rows(rig.root) == []  # and nothing was archived
            release.set_result(None)
            assert await asyncio.wait_for(store_task, timeout=10) is EpisodeStoreOutcome.STORED

            assert await asyncio.wait_for(em.evict_by_ids([_SUBJECT], reason="activation_decay"), timeout=10) == 1
            assert _raw(em, [_SUBJECT])["ids"] == []
            assert _sidecar_counts(rig.root, _SUBJECT) == _NO_SIDECARS  # the tail's rows were cleaned this time
            if mode == "archive":
                assert len(_archived(rig, _SUBJECT)) == 1
        finally:
            if not release.done():
                release.set_result(None)
            em._fts_db = real
            await _cancel_all(tasks)


# --- L-7, L-8: a stop() inside eviction or inside an erase is typed (D9) ---------------------------------------


async def test_a_stop_during_capacity_eviction_keeps_the_rest_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """AD-1340 S2b L-7: a stop() inside a capacity eviction keeps every id live; a stopped memory evicts nothing."""
    monkeypatch.setattr(_CHUNK, 1)
    caplog.set_level(logging.WARNING)
    stopped: list[str] = []
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        for i in range(4):
            assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        em.max_episodes = 1  # test-only: three of the four are over the budget, one id per chunk
        original = em._eviction_audit.record_batch_eviction  # test-only private access

        async def _stop_inside_the_first_chunk(*args: Any, **kwargs: Any) -> Any:
            if not stopped:
                stopped.append("stop")
                await em.stop()
            return await original(*args, **kwargs)

        monkeypatch.setattr(em._eviction_audit, "record_batch_eviction", _stop_inside_the_first_chunk)

        await em._evict()  # returns without raising ...

        assert stopped == ["stop"]  # premise: the stop happened inside the first chunk's audit
        assert len(_warnings(caplog, "the live store stopped during eviction")) == 1  # ... through the typed branch
        assert await em._evict() is None  # a stopped memory evicts nothing: no AttributeError on a cleared store

    async with _memory(tmp_path, "archive") as reopened:
        assert sorted(_raw(reopened.em, _ids(4))["ids"]) == _ids(4)  # nothing was lost
        assert [row["episode_id"] for row in _archive_rows(reopened.root)] == ["ep-000"]  # a duplicate, never a loss


async def test_a_stop_during_an_erase_live_phase_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-1340 S2b L-8: a stop() inside an ERASE's live phase raises ``erasure_live_store_unavailable``, not AttributeError."""
    stopped: list[str] = []
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        original = em._eviction_audit.record_batch_eviction  # test-only private access

        async def _stop_inside_the_erase(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("disposition") == DISPOSITION_ERASED and not stopped:
                stopped.append("stop")
                await em.stop()
            return await original(*args, **kwargs)

        monkeypatch.setattr(em._eviction_audit, "record_batch_eviction", _stop_inside_the_erase)

        with pytest.raises(EpisodeErasureIncomplete, match="^erasure_live_store_unavailable$"):
            await em.evict_by_ids([_SUBJECT], reason="erasure", disposition=EvictionDisposition.ERASE)

        assert stopped == ["stop"]  # premise: the stop happened inside the live phase, after the audit began

    async with _memory(tmp_path, "archive") as reopened:
        assert _raw(reopened.em, [_SUBJECT])["ids"] == [_SUBJECT]  # premise: the failed erase left the live row
        retried = await reopened.em.evict_by_ids([_SUBJECT], reason="erasure", disposition=EvictionDisposition.ERASE)
        assert retried == 1  # the retry erases it
        assert await _traces(reopened.em, reopened.root, _SUBJECT) == _GONE
