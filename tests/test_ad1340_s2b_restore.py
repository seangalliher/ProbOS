"""AD-1340 S2b (M3): restore is all or nothing, refuses a store at capacity, names its accessor and types a stop().

The real ``EpisodicMemory`` on ``tmp_path`` with every sidecar and the archive wired (the S1 rig). Raw ``sqlite3``
connections of the tests' own are the independent witness for the archive and the sidecars, and the live store is
read back straight from ChromaDB. Every test archives its subject through Step 12's call and states its premise
first (archived, not live, in no sidecar, no access row), so a pass cannot be vacuous. Every interleaving is a gate
the test creates and resolves: no test sleeps and every wait is bounded. No assertion orders rows by time
(back-to-back ``time.time()`` calls can return one value on Windows): R-6 forces ``archived_at`` and R-7 freezes
the activation clock.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.episode_archive import (
    ARCHIVE_FILENAME,
    ArchiveRecord,
    EpisodeArchiveConflict,
    EpisodeArchiveError,
    EpisodeArchiveNotFound,
    EpisodeArchiveUnavailable,
    decode_payload,
)
from probos.config_models.cognition import DreamingConfig
from probos.security.pii_redaction import LogRedactionFormatter
from probos.types import EpisodeStoreOutcome, EvictionDisposition
from tests.test_ad1340_s1_erasure import _GONE, _traces
from tests.test_ad1340_s1_eviction import (
    _archive_rows,
    _CollectionProxy,
    _episode,
    _ids,
    _memory,
    _query,
    _raw,
    _Rig,
    _sidecar_counts,
)
from tests.test_ad1340_s1_restore_reset import (
    _SUBJECT,
    _activation_types,
    _archive_accesses,
    _cancel_all,
    _canonical,
    _FtsTailProxy,
)
from tests.test_ad1340_s2a_archive_lookup import _GatedRead, _write
from tests.test_ad1340_s2a_lookup_route import _memory_without_archive

_NO_SIDECARS = {"fts": 0, "activation": 0, "participants": 0}
# One FTS row, one activation access (the restore's own) and two participant rows (agent-a as author, worf).
_LIVE_SIDECARS = {"fts": 1, "activation": 1, "participants": 2}
_CAPTAIN = "captain:/api/security/archive/restore"
_RESTORE_ACCESS = ("episodic_memory", "restore")  # the default accessor, and the purpose every restore records
_OVER_CAPACITY = "^episode_archive_restore_over_capacity$"
_INTERRUPTED = "^episode_restore_interrupted_by_stop$"
_NOT_OPEN = "^episode_archive_not_open$"


# --- helpers -------------------------------------------------------------------------------------------------


def _assert_archived_only(rig: _Rig, episode_id: str) -> None:
    """The premise of every test: archived, not live, in no sidecar, and no restore or lookup has touched it."""
    assert episode_id in [row["episode_id"] for row in _archive_rows(rig.root)]
    assert _raw(rig.em, [episode_id])["ids"] == []
    assert _sidecar_counts(rig.root, episode_id) == _NO_SIDECARS
    assert _archive_accesses(rig.root, episode_id) == []


def _assert_live_with_every_row(rig: _Rig, episode_id: str) -> None:
    assert _raw(rig.em, [episode_id])["ids"] == [episode_id]
    assert _sidecar_counts(rig.root, episode_id) == _LIVE_SIDECARS


def _assert_stored_live(rig: _Rig, episode_id: str) -> None:
    """A live episode stored through store(): its FTS row and both participant rows (store() writes no activation row)."""
    assert _raw(rig.em, [episode_id])["ids"] == [episode_id]
    counts = _sidecar_counts(rig.root, episode_id)
    assert (counts["fts"], counts["participants"]) == (1, 2)


async def _archive_one(rig: _Rig, index: int) -> str:
    """Store ``_episode(index)``, archive it through Step 12's call, and prove it is archived and nowhere else."""
    episode = _episode(index)
    assert await rig.em.store(episode) is EpisodeStoreOutcome.STORED
    assert await rig.em.evict_by_ids([episode.id], reason="activation_decay") == 1  # the call dreaming.py makes
    _assert_archived_only(rig, episode.id)
    return episode.id


class _Pause:
    """A gate inside one await of the restore: ``entered`` is set when the restore arrives, ``release`` lets it go on."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def hold(self) -> None:
        self.entered.set()
        await self.release.wait()


def _pause_in(rig: _Rig, monkeypatch: pytest.MonkeyPatch, point: str) -> tuple[asyncio.Event, asyncio.Event]:
    """Pause the next restore inside the await named by ``point``; returns its ``(entered, release)`` events."""
    em = rig.em
    if point in ("archive_read", "replaced"):
        archive = em._episode_archive  # test-only private access
        gate = _GatedRead(archive._db, "before_fetchall" if point == "archive_read" else "after_fetchall")
        archive._db = gate
        return gate.entered, gate.release
    pause = _Pause()
    if point == "fts_insert":
        em._fts_db = _FtsTailProxy(em._fts_db, pause.hold)  # test-only private access
    elif point == "participant_insert":
        original_record_episode = rig.participants.record_episode

        async def _paused_participants(*args: Any, **kwargs: Any) -> Any:
            await pause.hold()
            return await original_record_episode(*args, **kwargs)

        monkeypatch.setattr(rig.participants, "record_episode", _paused_participants)
    elif point == "activation_insert":
        original_record_access = rig.activations.record_access

        async def _paused_activation(*args: Any, **kwargs: Any) -> Any:
            await pause.hold()
            return await original_record_access(*args, **kwargs)

        monkeypatch.setattr(rig.activations, "record_access", _paused_activation)
    else:
        raise AssertionError(f"unknown pause point {point!r}")
    return pause.entered, pause.release


def _fail_insert(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch, store: str,
) -> tuple[list[str], Callable[[], None]]:
    """Make the restore's insert into ``store`` raise ``RuntimeError``; returns the log of hits and the fault's remover."""
    em = rig.em
    hits: list[str] = []
    if store == "episode_fts":
        real = em._fts_db  # test-only private access

        async def _fail_the_fts_insert() -> None:
            hits.append(store)
            raise RuntimeError("injected: episode_fts insert failed")

        em._fts_db = _FtsTailProxy(real, _fail_the_fts_insert)

        def _remove_the_fts_fault() -> None:
            em._fts_db = real

        return hits, _remove_the_fts_fault
    owner, name = (
        (rig.participants, "record_episode") if store == "participant_index" else (rig.activations, "record_access")
    )

    async def _fail(*args: Any, **kwargs: Any) -> None:
        hits.append(store)
        raise RuntimeError(f"injected: {store} insert failed")

    monkeypatch.setattr(owner, name, _fail)
    return hits, monkeypatch.undo


class _FailingAddProxy(_CollectionProxy):
    """The live collection whose next ``add`` raises. With ``land`` it first really adds: a store that failed after its write."""

    def __init__(self, inner: Any, *, land: bool) -> None:
        super().__init__(inner)
        self.armed = True
        self.land = land

    def add(self, **kwargs: Any) -> Any:
        if self.armed:
            self.armed = False
            if self.land:
                self.inner.add(**kwargs)
            raise RuntimeError("injected: live add failed")
        return self.inner.add(**kwargs)


# --- R-1 -----------------------------------------------------------------------------------------------------


async def test_restore_refuses_at_capacity_and_writes_nothing(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive", max_episodes=2) as rig:
        em = rig.em
        for index in (0, 1):
            assert await em.store(_episode(index)) is EpisodeStoreOutcome.STORED
        assert await em.evict_by_ids([_SUBJECT], reason="activation_decay") == 1  # Step 12's call
        assert await em.store(_episode(2)) is EpisodeStoreOutcome.STORED
        assert em._collection.count() == em.max_episodes == 2  # premise: the live store is exactly at its budget
        _assert_archived_only(rig, _SUBJECT)

        with pytest.raises(EpisodeArchiveConflict, match=_OVER_CAPACITY):
            await em.restore_from_archive(_SUBJECT)

        _assert_archived_only(rig, _SUBJECT)  # the refusal wrote nothing: not live, no sidecar row, no access row
        assert em._collection.count() == 2
        assert [row["episode_id"] for row in _archive_rows(rig.root)] == [_SUBJECT]  # and the archive row is kept
        assert await em.evict_by_ids([_episode(1).id], reason="activation_decay") == 1
        assert em._collection.count() == em.max_episodes - 1  # premise: one below the budget

        restored = await em.restore_from_archive(_SUBJECT)

        assert restored.id == _SUBJECT
        assert em._collection.count() == 2
        _assert_live_with_every_row(rig, _SUBJECT)
        assert _archive_accesses(rig.root, _SUBJECT) == [_RESTORE_ACCESS]


# --- R-2 -----------------------------------------------------------------------------------------------------


async def test_restore_writes_every_index_row_before_the_live_add_and_clears_stale_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        subject = await _archive_one(rig, 0)
        fts_path = rig.root / "chroma" / "episode_fts.db"
        _write(fts_path, "INSERT INTO episode_fts(episode_id, content) VALUES (?, 'stale')", (subject,))
        _write(
            rig.root / "participant_index.db",
            "INSERT INTO episode_participants(episode_id, agent_id, callsign, role) VALUES (?, 'stale-agent', '', 'author')",
            (subject,),
        )
        # premise: one stale FTS row and one stale participant row exist for the (not live) id
        assert _sidecar_counts(rig.root, subject) == {"fts": 1, "activation": 0, "participants": 1}
        assert _query(fts_path, "SELECT content FROM episode_fts WHERE episode_id = ?", (subject,)) == [("stale",)]
        assert subject not in [hit for hit, _ in await em.keyword_search("alpha")]
        seen: dict[str, list[str]] = {}  # what the live store held for the id at each insert

        async def _before_the_fts_insert() -> None:
            seen["episode_fts"] = _raw(em, [subject])["ids"]

        def _watch(owner: Any, name: str, key: str) -> None:
            original = getattr(owner, name)

            async def _spy(*args: Any, **kwargs: Any) -> Any:
                seen[key] = _raw(em, [subject])["ids"]
                return await original(*args, **kwargs)

            monkeypatch.setattr(owner, name, _spy)

        real_fts = em._fts_db  # test-only private access
        em._fts_db = _FtsTailProxy(real_fts, _before_the_fts_insert)
        _watch(rig.participants, "record_episode", "participant_index")
        _watch(rig.activations, "record_access", "activation")
        try:
            restored = await em.restore_from_archive(subject)
        finally:
            em._fts_db = real_fts

        # every insert ran, each while the id was NOT yet live: the live add is the commit point
        assert seen == {"episode_fts": [], "participant_index": [], "activation": []}
        assert restored.id == subject
        _assert_live_with_every_row(rig, subject)  # the stale rows are gone: exactly one FTS row, two participant rows
        contents = [row[0] for row in _query(fts_path, "SELECT content FROM episode_fts WHERE episode_id = ?", (subject,))]
        assert len(contents) == 1 and contents[0] != "stale" and _episode(0).user_input in contents[0]
        assert subject in [hit for hit, _ in await em.keyword_search("alpha")]


# --- R-3 -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("store", ["episode_fts", "participant_index", "activation"])
async def test_a_failed_sidecar_insert_undoes_the_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: str,
) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        subject = await _archive_one(rig, 0)
        hits, remove_fault = _fail_insert(rig, monkeypatch, store)

        with pytest.raises(EpisodeArchiveError, match=f"^episode_archive_restore_incomplete:{store}$") as caught:
            await em.restore_from_archive(subject)

        assert hits == [store]  # premise: the injected insert was reached
        assert type(caught.value) is EpisodeArchiveError  # the incomplete-restore error itself, not a subclass
        assert isinstance(caught.value.__cause__, RuntimeError)
        assert _raw(em, [subject])["ids"] == []  # nothing is live
        assert _sidecar_counts(rig.root, subject) == _NO_SIDECARS  # and every row the attempt wrote is undone
        assert [row["episode_id"] for row in _archive_rows(rig.root)] == [subject]  # one archive row, kept
        assert _archive_accesses(rig.root, subject) == [_RESTORE_ACCESS]  # the attempt's audit row stays
        remove_fault()

        restored = await em.restore_from_archive(subject)  # the retry is not met by a conflict

        assert restored.id == subject
        _assert_live_with_every_row(rig, subject)
        assert _archive_accesses(rig.root, subject) == [_RESTORE_ACCESS, _RESTORE_ACCESS]


# --- R-3b ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("landed", [False, True])
async def test_a_failed_live_add_undoes_the_restore_unless_the_id_landed(tmp_path: Path, landed: bool) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        subject = await _archive_one(rig, 0)
        proxy = _FailingAddProxy(em._collection, land=landed)
        em._collection = proxy  # test-only private access: the restore binds this collection at entry

        if landed:
            with pytest.raises(EpisodeArchiveError, match="^episode_archive_restore_unconfirmed$") as caught:
                await em.restore_from_archive(subject)
        else:
            with pytest.raises(EpisodeArchiveError, match="^episode_archive_restore_incomplete:live_add$") as caught:
                await em.restore_from_archive(subject)

        assert proxy.armed is False  # premise: the injected add was reached
        assert type(caught.value) is EpisodeArchiveError
        assert isinstance(caught.value.__cause__, RuntimeError)
        assert [row["episode_id"] for row in _archive_rows(rig.root)] == [subject]  # one archive row, kept
        assert _archive_accesses(rig.root, subject) == [_RESTORE_ACCESS]
        if landed:
            # The add raised after the live store took the id: its rows are kept, never cleared under a live id.
            assert _raw(em, [subject])["ids"] == [subject]
            assert _sidecar_counts(rig.root, subject) == _LIVE_SIDECARS
            with pytest.raises(EpisodeArchiveConflict, match="^episode_archive_restore_live_id$"):
                await em.restore_from_archive(subject)
            assert _sidecar_counts(rig.root, subject) == _LIVE_SIDECARS  # unchanged
            assert _archive_accesses(rig.root, subject) == [_RESTORE_ACCESS]  # a refused retry writes no access row
        else:
            assert _raw(em, [subject])["ids"] == []  # nothing is live ...
            assert _sidecar_counts(rig.root, subject) == _NO_SIDECARS  # ... and no row is left for an id that is not
            restored = await em.restore_from_archive(subject)  # the retry (the proxy is disarmed) succeeds
            assert restored.id == subject
            _assert_live_with_every_row(rig, subject)
            assert _archive_accesses(rig.root, subject) == [_RESTORE_ACCESS, _RESTORE_ACCESS]


# --- R-3c, R-3d ----------------------------------------------------------------------------------------------

_STORED_VALUE_MARKER = "STORED-VALUE-MARKER-7"


class _MarkedFailingAddProxy(_FailingAddProxy):
    """``_FailingAddProxy`` whose injected failure carries stored content in its text, as a Chroma rejection can."""

    def add(self, **kwargs: Any) -> Any:
        if self.armed:
            self.armed = False
            if self.land:
                self.inner.add(**kwargs)
            raise RuntimeError(f"injected: live add failed on {_STORED_VALUE_MARKER}")
        return self.inner.add(**kwargs)


def _episodic_warnings(caplog: pytest.LogCaptureFixture, needle: str) -> list[tuple[logging.LogRecord, str]]:
    """The episodic WARNING records containing ``needle``, each with its text as the PRODUCTION formatter renders it.

    ``Formatter.format`` appends the traceback text whenever ``record.exc_info`` is set, whatever the format string.
    """
    formatter = LogRedactionFormatter("%(message)s")
    records = [
        record for record in caplog.records
        if record.name == "probos.cognitive.episodic" and record.levelno == logging.WARNING
        and needle in record.getMessage()
    ]
    return [(record, formatter.format(record)) for record in records]


@pytest.mark.parametrize("path", ["insert", "add_absent", "add_landed"])
async def test_restore_warnings_carry_no_exception_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, path: str,
) -> None:
    """AD-1340 S2b R-3c (review F1): a restore warning names the stage and the exception type, never its text.

    The archive exists so that ERASE can remove every copy of an episode; an exception text that carries a stored
    value must not be copied into a log, where the production formatter does not mask arbitrary stored content.
    """
    caplog.set_level(logging.WARNING)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        subject = await _archive_one(rig, 0)
        if path == "insert":
            async def _fail_marked(*args: Any, **kwargs: Any) -> None:
                raise RuntimeError(f"injected: participant_index insert failed on {_STORED_VALUE_MARKER}")

            monkeypatch.setattr(rig.participants, "record_episode", _fail_marked)
            expected_error = "^episode_archive_restore_incomplete:participant_index$"
            expected_warning = "could not write its participant_index row"
        else:
            em._collection = _MarkedFailingAddProxy(em._collection, land=path == "add_landed")  # test-only private access
            if path == "add_landed":
                expected_error = "^episode_archive_restore_unconfirmed$"
                expected_warning = "raised but the id may be live"
            else:
                expected_error = "^episode_archive_restore_incomplete:live_add$"
                expected_warning = "could not write its live_add row"

        with pytest.raises(EpisodeArchiveError, match=expected_error) as caught:
            await em.restore_from_archive(subject)

        assert _STORED_VALUE_MARKER in str(caught.value.__cause__)  # premise: the failure's own text carries the marker
        [(record, text)] = _episodic_warnings(caplog, expected_warning)  # premise: the warning exists, once
        assert "RuntimeError" in record.getMessage()  # it names the exception type
        assert record.exc_info is None
        assert _STORED_VALUE_MARKER not in text  # formatting appends a traceback if exc_info is set


async def test_a_real_chroma_rejection_does_not_copy_stored_metadata_into_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """AD-1340 S2b R-3d (review F1): the real ``collection.add`` rejects a dict-valued metadata entry; its text names the value.

    The reviewer's case, with no injection: the archived row's metadata carries a dict-valued entry containing the
    marker, Chroma's own error text quotes it, and the restore warning must not.
    """
    caplog.set_level(logging.WARNING)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        subject = await _archive_one(rig, 0)
        path = rig.root / "chroma" / ARCHIVE_FILENAME
        [row] = [candidate for candidate in _archive_rows(rig.root) if candidate["episode_id"] == subject]
        archived = decode_payload(row["episode_id"], row["content_hash"], row["payload_format"], row["payload"])
        crafted = {**archived.metadata, "content_hash": "f" * 64, _STORED_VALUE_MARKER: {_STORED_VALUE_MARKER: "x"}}
        await em._episode_archive.archive(  # test-only private access
            [ArchiveRecord(episode_id=subject, document=archived.document, metadata=crafted)], reason="activation_decay",
        )
        _write(path, "DELETE FROM episode_archive WHERE episode_id = ? AND content_hash = ?", (subject, row["content_hash"]))
        [only] = [candidate for candidate in _archive_rows(rig.root) if candidate["episode_id"] == subject]
        assert only["content_hash"] != row["content_hash"]  # premise: only the crafted version remains

        with pytest.raises(EpisodeArchiveError, match="^episode_archive_restore_incomplete:live_add$") as caught:
            await em.restore_from_archive(subject)

        assert _STORED_VALUE_MARKER in str(caught.value.__cause__)  # premise: the REAL rejection quotes the stored value
        [(record, text)] = _episodic_warnings(caplog, "could not write its live_add row")
        assert "(" + type(caught.value.__cause__).__name__ + ")" in record.getMessage()
        assert record.exc_info is None
        assert _STORED_VALUE_MARKER not in text


# --- R-4, R-4b -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "point", ["archive_read", "replaced", "fts_insert", "participant_insert", "activation_insert"],
)
async def test_a_stop_at_each_await_of_restore_is_typed_and_leaves_nothing_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str,
) -> None:
    tasks: list[asyncio.Task[Any]] = []
    before_the_access = point in ("archive_read", "replaced")  # these stops come before the audit row is written
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        subject = await _archive_one(rig, 0)
        original = em._collection
        entered, release = _pause_in(rig, monkeypatch, point)
        task = asyncio.create_task(em.restore_from_archive(subject))
        tasks.append(task)
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)  # premise: the restore is paused inside this await
            assert not task.done()
            if point == "replaced":
                em._collection = object()  # test-only private access: a restart's new collection
            else:
                await asyncio.wait_for(em.stop(), timeout=5)
                assert em._collection is None  # premise: the stop completed ...
                assert not task.done()  # ... while the restore was still pending
            release.set()
            with pytest.raises(EpisodeArchiveUnavailable, match=_NOT_OPEN if point == "archive_read" else _INTERRUPTED):
                await asyncio.wait_for(task, timeout=5)
        finally:
            release.set()
            if point == "replaced":
                em._collection = original  # put the real collection back, even when an assertion failed
            await _cancel_all(tasks)

        if point == "replaced":
            assert original.get(ids=[subject])["ids"] == []  # the collection the restore bound never took the add
        assert _sidecar_counts(rig.root, subject) == _NO_SIDECARS  # read from the files: no row survived the stop
        assert [row["episode_id"] for row in _archive_rows(rig.root)] == [subject]  # one archive row
        assert _archive_accesses(rig.root, subject) == ([] if before_the_access else [_RESTORE_ACCESS])

    # The failed read's exception chain keeps the paused SQLite cursor alive, and an unfinished cursor holds the
    # file's read lock. These references belong to the test, not to the product (in production they are dropped
    # once the error is handled): release them so the reopen below sees the files as a restart would.
    tasks.clear()
    task = None
    gc.collect()

    async with _memory(tmp_path, "archive") as again:  # leave the rig, reopen the same files
        assert _raw(again.em, [subject])["ids"] == []  # not live
        restored = await again.em.restore_from_archive(subject)  # and a retry restore succeeds
        assert restored.id == subject
        _assert_live_with_every_row(again, subject)


async def test_a_cancelled_restore_is_undone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tasks: list[asyncio.Task[Any]] = []
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        subject = await _archive_one(rig, 0)
        entered, release = _pause_in(rig, monkeypatch, "participant_insert")
        task = asyncio.create_task(em.restore_from_archive(subject))
        tasks.append(task)
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)  # premise: the restore is inside the participant insert
            assert not task.done()
            assert _sidecar_counts(rig.root, subject) == {"fts": 1, "activation": 0, "participants": 0}  # premise: half done

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
        finally:
            release.set()
            await _cancel_all(tasks)

        assert task.cancelled()
        assert em._collection is not None  # the memory still runs
        assert _raw(em, [subject])["ids"] == []
        assert _sidecar_counts(rig.root, subject) == _NO_SIDECARS  # the FTS row the attempt wrote is undone
        assert _archive_accesses(rig.root, subject) == [_RESTORE_ACCESS]


# --- R-5 -----------------------------------------------------------------------------------------------------


async def test_restore_names_its_accessor_and_types_its_refusals(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        first = await _archive_one(rig, 0)
        second = await _archive_one(rig, 1)

        await em.restore_from_archive(first, accessor=_CAPTAIN)

        assert _archive_accesses(rig.root, first) == [(_CAPTAIN, "restore")]  # the named accessor, not the default
        for blank in (" ", "", None):
            with pytest.raises(ValueError, match="^episode_archive_restore_accessor_invalid$"):
                await em.restore_from_archive(second, accessor=blank)  # type: ignore[arg-type]
        _assert_archived_only(rig, second)  # refused before anything: no access row, nothing live
        with pytest.raises(EpisodeArchiveNotFound, match="^episode_archive_not_found$") as caught:
            await em.restore_from_archive("ep-unknown")
        assert isinstance(caught.value, LookupError)  # S1's callers that catch LookupError still do
        assert _archive_accesses(rig.root, "ep-unknown") == []
    async with _memory_without_archive(tmp_path / "failed", "failed") as without_archive:
        with pytest.raises(EpisodeArchiveUnavailable, match="^episode_archive_unavailable$"):
            await without_archive.restore_from_archive(_SUBJECT)


# --- R-6 -----------------------------------------------------------------------------------------------------


async def _two_crafted_versions(rig: _Rig, episode_id: str, archived_at: dict[str, float]) -> dict[str, dict[str, Any]]:
    """Replace the one archived row of ``episode_id`` by two crafted versions and force their ``archived_at``.

    The versions differ in ``content_hash`` ("0" * 64 and "f" * 64) and in ``valid_until`` (1.0 and 2.0); returns
    each version's metadata by content hash. ``archived_at`` maps a content hash to the time the test forces.
    """
    path = rig.root / "chroma" / ARCHIVE_FILENAME
    [row] = [candidate for candidate in _archive_rows(rig.root) if candidate["episode_id"] == episode_id]
    archived = decode_payload(row["episode_id"], row["content_hash"], row["payload_format"], row["payload"])
    versions = {
        "0" * 64: {**archived.metadata, "content_hash": "0" * 64, "valid_until": 1.0},
        "f" * 64: {**archived.metadata, "content_hash": "f" * 64, "valid_until": 2.0},
    }
    await rig.em._episode_archive.archive(  # test-only private access
        [ArchiveRecord(episode_id=episode_id, document=archived.document, metadata=meta) for meta in versions.values()],
        reason="activation_decay",
    )
    _write(path, "DELETE FROM episode_archive WHERE episode_id = ? AND content_hash = ?", (episode_id, row["content_hash"]))
    for content_hash, forced in archived_at.items():
        _write(
            path,
            "UPDATE episode_archive SET archived_at = ? WHERE episode_id = ? AND content_hash = ?",
            (forced, episode_id, content_hash),
        )
    # premise: exactly the two crafted versions exist, with the forced times (no assertion depends on the clock)
    assert {
        candidate["content_hash"]: candidate["archived_at"]
        for candidate in _archive_rows(rig.root)
        if candidate["episode_id"] == episode_id
    } == archived_at
    return versions


async def test_restore_puts_back_the_version_a_lookup_shows(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        tie = await _archive_one(rig, 0)
        newer = await _archive_one(rig, 1)
        tie_versions = await _two_crafted_versions(rig, tie, {"0" * 64: 7000.0, "f" * 64: 7000.0})
        newer_versions = await _two_crafted_versions(rig, newer, {"0" * 64: 7000.0, "f" * 64: 7001.0})

        for episode_id, versions, shown in ((tie, tie_versions, "0" * 64), (newer, newer_versions, "f" * 64)):
            lookup = await em.lookup_archived_by_id(episode_id, accessor="test")
            assert [item.record.metadata["content_hash"] for item in lookup.episodes] == [shown]  # the version shown

            await em.restore_from_archive(episode_id)

            live = _raw(em, [episode_id])
            assert live["ids"] == [episode_id]
            assert live["metadatas"][0]["content_hash"] == shown  # the version the lookup showed ...
            assert _canonical(live["metadatas"][0]) == _canonical(versions[shown])  # ... and exactly its metadata


# --- R-7 -----------------------------------------------------------------------------------------------------


async def test_the_next_aggressive_step12_prunes_a_restored_episode_again_without_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        before = _raw(em, [_SUBJECT])
        assert await em.evict_by_ids([_SUBJECT], reason="activation_decay") == 1
        _assert_archived_only(rig, _SUBJECT)
        archived = _archive_rows(rig.root)
        assert len(archived) == 1

        await em.restore_from_archive(_SUBJECT)

        accesses = _query(
            rig.root / "activation.db", "SELECT access_time FROM episode_access_log WHERE episode_id = ?", (_SUBJECT,),
        )
        assert len(accesses) == 1 and _activation_types(rig.root, _SUBJECT) == ["archive_restore"]  # one access
        restore_time = accesses[0][0]
        cfg = DreamingConfig()
        cutoff = time.time() - cfg.aggressive_prune_min_age_hours * 3600
        assert cfg.aggressive_prune_enabled and cfg.aggressive_prune_threshold == 0.0  # premise: the shipped defaults
        assert _raw(em, [_SUBJECT])["metadatas"][0]["timestamp"] < cutoff  # the original timestamp: past the age cutoff
        candidates = await em.get_episode_ids_older_than(cutoff)  # Step 12's own read
        assert candidates == [_SUBJECT]
        clock = {"now": restore_time}
        # A stand-in module, so the activation formula sees the frozen time while ChromaDB and SQLite keep the real one.
        monkeypatch.setattr("probos.cognitive.activation_tracker.time", SimpleNamespace(time=lambda: clock["now"]))

        # At the restore instant its activation is high: Step 12 keeps it.
        assert await rig.activations.find_low_activation_episodes(
            all_episode_ids=candidates,
            threshold=cfg.aggressive_prune_threshold,
            max_prune_fraction=cfg.aggressive_prune_max_fraction,
        ) == []
        # An hour later, with no recall in between, both Step 12 selections prune it again.
        clock["now"] = restore_time + 3600
        assert await rig.activations.find_low_activation_episodes(
            all_episode_ids=candidates,
            threshold=cfg.aggressive_prune_threshold,
            max_prune_fraction=cfg.aggressive_prune_max_fraction,
        ) == [_SUBJECT]
        assert await rig.activations.find_low_activation_episodes_with_importance(
            all_episode_ids=candidates,
            importance_map={_SUBJECT: 5},
            threshold=cfg.aggressive_prune_threshold,
            max_prune_fraction=cfg.aggressive_prune_max_fraction,
        ) == [_SUBJECT]

        assert await em.evict_by_ids([_SUBJECT], reason="activation_decay_aggressive") == 1

        assert _raw(em, [_SUBJECT])["ids"] == []
        assert _archive_rows(rig.root) == archived  # re-archived under the same key, byte-equal, not rewritten
        await em.restore_from_archive(_SUBJECT)  # never lost: it can be restored again
        assert _raw(em, [_SUBJECT]) == before
        assert _canonical(_raw(em, [_SUBJECT])["metadatas"][0]) == _canonical(before["metadatas"][0])


# --- R-8 -----------------------------------------------------------------------------------------------------


async def test_restore_eviction_erase_and_lookup_together_finish_and_stay_consistent(tmp_path: Path) -> None:
    all_ids = _ids(6)
    async with _memory(tmp_path, "archive", max_episodes=4) as rig:
        em = rig.em
        for index in range(6):
            assert await em.store(_episode(index)) is EpisodeStoreOutcome.STORED  # the 5th and 6th stores evict by capacity
        await em.evict_by_ids(all_ids[:3], reason="activation_decay")  # ep-000 and ep-001 are archived already: ep-002 goes
        # premise: ep-000, ep-001 and ep-002 are archived and nowhere else; ep-003 to ep-005 are live with every row
        assert [row["episode_id"] for row in _archive_rows(rig.root)] == all_ids[:3]
        for episode_id in all_ids[:3]:
            _assert_archived_only(rig, episode_id)
        for episode_id in all_ids[3:]:
            _assert_stored_live(rig, episode_id)
        assert em._collection.count() == 3

        tasks = [
            asyncio.create_task(coroutine)
            for coroutine in (
                em.restore_from_archive("ep-000"),
                em.evict_by_ids(["ep-001"], reason="erasure", disposition=EvictionDisposition.ERASE),
                em.evict_by_ids(["ep-003"], reason="activation_decay"),
                em.lookup_archived_by_id("ep-002", accessor="test"),
                em._evict(),  # test-only private access: the capacity eviction a store() would start
            )
        ]
        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=10)
        finally:
            await _cancel_all(tasks)

        for result in results:  # each result is a success, or the capacity refusal (the order decides): nothing else
            if isinstance(result, BaseException):
                assert isinstance(result, EpisodeArchiveConflict), repr(result)
                assert str(result) == "episode_archive_restore_over_capacity", repr(result)
        lookup = results[3]
        assert not isinstance(lookup, BaseException)
        assert [item.record.episode_id for item in lookup.episodes] == ["ep-002"]
        assert await _traces(em, rig.root, "ep-001") == _GONE
        for episode_id in all_ids:
            live = _raw(em, [episode_id])["ids"] == [episode_id]
            counts = _sidecar_counts(rig.root, episode_id)
            assert (counts["fts"], counts["participants"]) == ((1, 2) if live else (0, 0)), episode_id