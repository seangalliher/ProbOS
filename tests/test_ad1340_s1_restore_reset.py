"""AD-1340 S1 (M4): restore, the Tier 2 reset, the store declaration and the flipped default.

A real ``EpisodicMemory`` (real ChromaDB, FTS5 sidecar, ``ActivationTracker``, ``ParticipantIndex``,
``EvictionAuditLog`` and episode archive) on ``tmp_path``. The helpers of ``test_ad1340_s1_eviction.py`` build it and
read it back through independent connections; the real ``ErasureManager`` of ``test_ad1340_s1_erasure.py`` erases from
it; the reset runs through the harness of ``test_reset_integration.py``. Every test states its premise first, so a
pass cannot be vacuous. The default is ``archive`` from M4 on, but the memories built here still name their mode.
"""

from __future__ import annotations

import ast
import asyncio
import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from pydantic import ValidationError

from probos.cognitive.episode_archive import (
    ARCHIVE_FILENAME,
    EpisodeArchiveConflict,
    EpisodeArchiveUnavailable,
    EpisodeErasureIncomplete,
)
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.eviction_audit import DISPOSITION_ERASED
from probos.config import MemoryConfig
from probos.infrastructure.backup_inventory import BackupTier, classify, is_excluded
from probos.storage.registry import load_default_store_registry
from probos.types import EpisodeStoreOutcome, EvictionDisposition
from tests.test_ad1340_s1_erasure import _GONE, _LIVE_TRACES, _audit_for, _manager, _participants_named, _traces
from tests.test_ad1340_s1_eviction import (
    _archive_rows,
    _episode,
    _memory,
    _query,
    _raw,
    _record_collection,
    _sidecar_counts,
)
from tests.test_reset_integration import _create_sqlite_db, _db_has_data, _run_reset

_MAIN = Path(__file__).resolve().parent.parent / "src" / "probos" / "__main__.py"
# The "alpha" episode of agent-a (participant "worf"): the one every test here evicts and restores.
_SUBJECT = _episode(0).id


# --- helpers -------------------------------------------------------------------------------------------------


def _canonical(metadata: Mapping[str, Any]) -> bytes:
    """The archive's own canonical JSON of a metadata dict. ``==`` cannot tell ``1`` from ``1.0`` from ``True``."""
    return json.dumps(dict(metadata), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _activation_types(root: Path, episode_id: str) -> list[str]:
    """The ``access_type`` of every activation-log row of one episode, read through a connection of our own."""
    rows = _query(
        root / "activation.db", "SELECT access_type FROM episode_access_log WHERE episode_id = ?", (episode_id,),
    )
    return [row[0] for row in rows]


def _archive_accesses(root: Path, episode_id: str) -> list[tuple[Any, ...]]:
    """``(accessor, purpose)`` of every ``archive_access`` row of one episode."""
    return _query(
        root / "chroma" / ARCHIVE_FILENAME,
        "SELECT accessor, purpose FROM archive_access WHERE episode_id = ?",
        (episode_id,),
    )


async def _found_by(em: EpisodicMemory, root: Path, episode_id: str) -> dict[str, bool]:
    """Whether the FTS5 keyword channel (the word "alpha") and the participant index (agent-a) return the episode."""
    return {
        "keyword": episode_id in [hit for hit, _ in await em.keyword_search("alpha")],
        "participants": episode_id in await _participants_named(root, "agent-a"),
    }


async def _prove_round_trip(root: Path, route: str) -> None:
    """Evict the "alpha" episode by ``route`` ("step12" or "capacity"), restore it, and prove it is back byte-equal."""
    capacity = route == "capacity"
    async with _memory(root, "archive", max_episodes=2 if capacity else 100) as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        await rig.activations.record_access(_SUBJECT)  # a recall-type access: eviction has a row to delete
        before_raw = _raw(em, [_SUBJECT])
        before_ep = (await em.get_by_ids([_SUBJECT]))[0]
        # premise: live, with a real content hash, in every sidecar and findable through each; nothing archived yet
        assert before_raw["ids"] == [_SUBJECT] and before_ep.id == _SUBJECT, route
        assert before_raw["metadatas"][0]["content_hash"], route
        assert _sidecar_counts(root, _SUBJECT) == {"fts": 1, "activation": 1, "participants": 2}, route
        assert await _found_by(em, root, _SUBJECT) == {"keyword": True, "participants": True}, route
        assert _archive_rows(root) == [], route

        if capacity:
            assert await em.store(_episode(1)) is EpisodeStoreOutcome.STORED
            assert _raw(em, [_SUBJECT])["ids"] == [_SUBJECT]  # premise: two episodes fit the budget of two
            assert await em.store(_episode(2)) is EpisodeStoreOutcome.STORED  # the third store evicts the oldest
            reason = "capacity"
        else:
            reason = "activation_decay"
            assert await em.evict_by_ids([_SUBJECT], reason=reason) == 1  # the exact call Step 12 makes (dreaming.py)
        # premise: archived, and gone from the live store, from every sidecar and from both read channels
        assert [(row["episode_id"], row["reason"]) for row in _archive_rows(root)] == [(_SUBJECT, reason)], route
        assert _raw(em, [_SUBJECT])["ids"] == [], route
        assert _sidecar_counts(root, _SUBJECT) == {"fts": 0, "activation": 0, "participants": 0}, route
        assert await _found_by(em, root, _SUBJECT) == {"keyword": False, "participants": False}, route
        assert _archive_accesses(root, _SUBJECT) == [], route

        if capacity:
            assert em._collection.count() == em.max_episodes  # premise: the store is at its budget (test-only)
            em.max_episodes = 3  # AD-1340 S2b (b): a restore refuses at capacity, so the round trip makes room first
        proxy = _record_collection(em)
        restored = await em.restore_from_archive(_SUBJECT)

        calls = [name for name, _ in proxy.calls]
        assert calls.count("add") == 1 and "upsert" not in calls, route  # not through store(), and never a replace
        after_raw = _raw(em, [_SUBJECT])
        assert after_raw == before_raw, route
        assert _canonical(after_raw["metadatas"][0]) == _canonical(before_raw["metadatas"][0]), route
        assert restored == before_ep, route
        assert (await em.get_by_ids([_SUBJECT]))[0] == before_ep, route
        assert await _found_by(em, root, _SUBJECT) == {"keyword": True, "participants": True}, route
        assert _activation_types(root, _SUBJECT) == ["archive_restore"], route  # activation restarts from this access
        assert _archive_accesses(root, _SUBJECT) == [("episodic_memory", "restore")], route
        assert [row["episode_id"] for row in _archive_rows(root)] == [_SUBJECT], route  # the archive row is kept


def _callee_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    return call.func.attr if isinstance(call.func, ast.Attribute) else None


def _attribute_chain(node: ast.expr) -> list[str]:
    """``config.memory.eviction_disposition`` as ``["config", "memory", "eviction_disposition"]``."""
    names: list[str] = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
    return names[::-1]


# --- T1 ------------------------------------------------------------------------------------------------------


async def test_byte_equal_round_trip_through_step12(tmp_path: Path) -> None:
    await _prove_round_trip(tmp_path / "step12", "step12")
    await _prove_round_trip(tmp_path / "capacity", "capacity")


# --- T2 ------------------------------------------------------------------------------------------------------


async def test_restore_refuses_a_live_id(tmp_path: Path) -> None:
    first, second = _episode(0), _episode(1)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        for episode in (first, second):
            assert await em.store(episode) is EpisodeStoreOutcome.STORED
        assert await em.evict_by_ids([first.id, second.id], reason="activation_decay") == 2
        assert em.archive_available and _raw(em, [first.id, second.id])["ids"] == []  # premise: both archived only

        assert (await em.restore_from_archive(first.id)).id == first.id  # premise: the first restore succeeds
        live = _raw(em, [first.id])
        assert live["ids"] == [first.id]
        written = (_sidecar_counts(rig.root, first.id), _archive_accesses(rig.root, first.id))

        with pytest.raises(EpisodeArchiveConflict, match="^episode_archive_restore_live_id$"):
            await em.restore_from_archive(first.id)

        assert _raw(em, [first.id]) == live  # the refusal left the live document and metadata alone ...
        # ... and wrote nothing: no sidecar row and no archive_access row
        assert (_sidecar_counts(rig.root, first.id), _archive_accesses(rig.root, first.id)) == written

        assert _raw(em, ["ep-never"])["ids"] == []  # premise: neither live ...
        assert "ep-never" not in [row["episode_id"] for row in _archive_rows(rig.root)]  # ... nor archived
        with pytest.raises(LookupError, match="^episode_archive_not_found$"):
            await em.restore_from_archive("ep-never")

        await em.stop()

        # premise: the second episode is still in the archive file, so only the closed archive can explain the refusal
        assert not em.archive_available
        assert [row["episode_id"] for row in _archive_rows(rig.root)] == [first.id, second.id]
        with pytest.raises(EpisodeArchiveUnavailable, match="^episode_archive_unavailable$"):
            await em.restore_from_archive(second.id)

    # The other way to have no archive: the live store is up, but delete mode never opened one.
    async with _memory(tmp_path / "delete", "delete") as plain:
        assert await plain.em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        assert not plain.em.archive_available
        assert not (plain.root / "chroma" / ARCHIVE_FILENAME).exists()  # premise: there is no archive file either
        with pytest.raises(EpisodeArchiveUnavailable, match="^episode_archive_unavailable$"):
            await plain.em.restore_from_archive(_SUBJECT)
        assert not (plain.root / "chroma" / ARCHIVE_FILENAME).exists()  # and the refused restore did not create one


# --- T3 ------------------------------------------------------------------------------------------------------


async def test_restore_then_erase_clears_every_copy(tmp_path: Path) -> None:
    episode = _episode(0)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
        await rig.activations.record_access(episode.id)
        content_hash = _raw(em, [episode.id])["metadatas"][0]["content_hash"]
        assert content_hash
        assert await _traces(em, rig.root, episode.id) == _LIVE_TRACES  # premise: live only
        assert await em.evict_by_ids([episode.id], reason="activation_decay") == 1
        assert await _traces(em, rig.root, episode.id) == {**_GONE, "episode_archive": 1}  # premise: archived only

        await em.restore_from_archive(episode.id)

        # premise: live in every store AND archived; restore wrote its one archive_access row
        assert await _traces(em, rig.root, episode.id) == {**_LIVE_TRACES, "episode_archive": 1, "archive_access": 1}

        result = await manager.forget_episode(episode.id)

        assert result.deleted_episode_ids == [episode.id]
        assert await _traces(em, rig.root, episode.id) == _GONE  # includes episode_archive and archive_access: 0 rows
        assert [row["content_hash"] for row in _audit_for(rig.root, episode.id, "erased")] == [content_hash]


# --- T4 ------------------------------------------------------------------------------------------------------


async def test_restore_then_re_evict_is_idempotent(tmp_path: Path) -> None:
    episode = _episode(0)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
        # A different reason from the re-eviction's, so a rewritten row could not look like the original.
        assert await em.evict_by_ids([episode.id], reason="activation_decay_aggressive") == 1
        archived = _archive_rows(rig.root)
        assert [(row["episode_id"], row["reason"]) for row in archived] == [(episode.id, "activation_decay_aggressive")]

        await em.restore_from_archive(episode.id)

        # premise: live again, in its sidecars, and the archive row is kept untouched
        assert _raw(em, [episode.id])["ids"] == [episode.id]
        assert _sidecar_counts(rig.root, episode.id) == {"fts": 1, "activation": 1, "participants": 2}
        assert _archive_rows(rig.root) == archived

        assert await em.evict_by_ids([episode.id], reason="activation_decay") == 1

        assert _raw(em, [episode.id])["ids"] == []
        assert _archive_rows(rig.root) == archived  # one row, the same key: neither duplicated nor rewritten
        assert _sidecar_counts(rig.root, episode.id) == {"fts": 0, "activation": 0, "participants": 0}


# --- T5 ------------------------------------------------------------------------------------------------------


def test_tier2_reset_removes_the_archive(tmp_path: Path) -> None:
    """A Tier 2 reset deletes ``episode_archive.db``; a Tier 1 reset keeps it (D7: episodes are nurture, and reset).

    The last assertions pin where the FTS5 sidecar sits. Until BF-902 it survived every tier (D8); **BF-902 (#1579)
    inverted that assertion deliberately**: ``episode_fts.db`` now goes with ``chroma.sqlite3`` in Tier 2 and no other
    tier. That is the reviewed decision recorded on #1579, not an edit to get past a failure here.
    """
    from probos.__main__ import RESET_TIERS, _file_purpose

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    archive = data_dir / "episode_archive.db"
    assert ARCHIVE_FILENAME == "episode_archive.db"  # premise: the reset's name is the name the archive writes
    _create_sqlite_db(archive, "episode_archive")
    assert _db_has_data(archive, "episode_archive")  # premise: a planted archive, with rows

    _run_reset(data_dir, tmp_path)  # the default tier is Tier 2

    assert not archive.exists()

    _create_sqlite_db(archive, "episode_archive")
    _create_sqlite_db(data_dir / "events.db", "events")  # a Tier 1 target: when it is gone, the soft reset ran
    assert _db_has_data(archive, "episode_archive") and (data_dir / "events.db").exists()  # premise

    _run_reset(data_dir, tmp_path, soft=True)

    assert not (data_dir / "events.db").exists()
    assert _db_has_data(archive, "episode_archive")

    assert "episode_archive.db" in RESET_TIERS[2]["files"]
    assert "episode_archive.db" not in RESET_TIERS[1]["files"]
    # D8, inverted by BF-902 (#1579): the FTS5 sidecar goes with the episodes it indexes, in Tier 2 only.
    assert [tier for tier, tier_def in RESET_TIERS.items() if "episode_fts.db" in tier_def.get("files", [])] == [2]
    assert _file_purpose("episode_archive.db") == "Episode archive"


# --- T6 ------------------------------------------------------------------------------------------------------


def test_archive_is_declared_and_backed_up() -> None:
    declaration = load_default_store_registry().get("cognitive.episode-archive")
    assert declaration is not None  # premise: the declaration module imported and registered it
    assert declaration.owner_symbol == "EpisodeArchive"
    assert declaration.canonical_path == "episode_archive.db"
    assert declaration.backup == "included"
    assert declaration.lifecycle_owner == "probos.cognitive.episodic.EpisodicMemory"
    relative = PurePosixPath("episode_archive.db")
    assert is_excluded(relative) is None
    assert classify(relative) is BackupTier.INCLUDED


# --- T7 ------------------------------------------------------------------------------------------------------


def test_default_is_archive_and_the_flag_reaches_both_constructions(tmp_path: Path) -> None:
    assert MemoryConfig(eviction_disposition="delete").eviction_disposition == "delete"  # premise: "delete" is valid
    assert MemoryConfig().eviction_disposition == "archive"
    with pytest.raises(ValidationError):
        MemoryConfig(eviction_disposition="purge")
    assert EpisodicMemory(db_path=str(tmp_path / "e.db")).eviction_disposition_mode == "archive"

    tree = ast.parse(_MAIN.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and _callee_name(node) == "EpisodicMemory"]
    assert len(calls) == 2  # premise: the runtime construction and the rebuild CLI's, so the loop is not vacuous
    for call in calls:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        assert "eviction_disposition" in keywords, f"EpisodicMemory(...) at line {call.lineno} does not pass the flag"
        chain = _attribute_chain(keywords["eviction_disposition"])
        assert chain[-2:] == ["memory", "eviction_disposition"], f"line {call.lineno}: {chain}"


# --- T8 ------------------------------------------------------------------------------------------------------


async def test_restore_fails_closed_when_the_access_cannot_be_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _refuse(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected: the access cannot be recorded")

    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        await rig.activations.record_access(_SUBJECT)
        assert await em.evict_by_ids([_SUBJECT], reason="activation_decay") == 1
        # premise: archived and not live, in no sidecar, and no access of the archive was ever recorded for it
        assert [row["episode_id"] for row in _archive_rows(rig.root)] == [_SUBJECT]
        assert _raw(em, [_SUBJECT])["ids"] == []
        assert _sidecar_counts(rig.root, _SUBJECT) == {"fts": 0, "activation": 0, "participants": 0}
        assert _archive_accesses(rig.root, _SUBJECT) == []
        monkeypatch.setattr(em._episode_archive, "record_access", _refuse)

        with pytest.raises(RuntimeError, match="^injected: the access cannot be recorded$"):
            await em.restore_from_archive(_SUBJECT)

        # Failed closed: the audit comes first, so nothing was restored and nothing has to be undone.
        assert _raw(em, [_SUBJECT])["ids"] == []
        assert _sidecar_counts(rig.root, _SUBJECT) == {"fts": 0, "activation": 0, "participants": 0}
        assert [row["episode_id"] for row in _archive_rows(rig.root)] == [_SUBJECT]
        assert _archive_accesses(rig.root, _SUBJECT) == []
        monkeypatch.undo()  # the fault is removed

        restored = await em.restore_from_archive(_SUBJECT)  # the retry is not met by EpisodeArchiveConflict

        assert restored.id == _SUBJECT
        assert _raw(em, [_SUBJECT])["ids"] == [_SUBJECT]
        assert _sidecar_counts(rig.root, _SUBJECT) == {"fts": 1, "activation": 1, "participants": 2}
        assert await _found_by(em, rig.root, _SUBJECT) == {"keyword": True, "participants": True}
        assert _activation_types(rig.root, _SUBJECT) == ["archive_restore"]  # one activation access
        assert _archive_accesses(rig.root, _SUBJECT) == [("episodic_memory", "restore")]  # and one archive_access row


# --- T9 ------------------------------------------------------------------------------------------------------


async def test_reevicting_a_restored_episode_archives_its_current_metadata(tmp_path: Path) -> None:
    """AD-1340 R1 (F4): a metadata change after a restore must reach the archive on the next eviction.

    Before R1 the second archive kept the first payload, the read-back checked only the key, and the live row
    (carrying the change) was deleted: the restore below brought back the OLD ``valid_until``.
    """
    episode = _episode(2)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
        first = dict(_raw(em, [episode.id])["metadatas"][0])
        assert await em.evict_by_ids([episode.id], reason="activation_decay") == 1
        await em.restore_from_archive(episode.id)
        restored = dict(_raw(em, [episode.id])["metadatas"][0])
        assert restored == first  # premise: the first cycle is byte-equal

        changed = dict(restored)
        changed["valid_until"] = 1234567890.0  # a normal metadata update after the restore
        em._collection.update(ids=[episode.id], metadatas=[changed])  # test-only private access
        assert _raw(em, [episode.id])["metadatas"][0]["valid_until"] == 1234567890.0  # premise: the update landed
        assert first.get("valid_until") != 1234567890.0  # premise: the archived copy holds a different value

        assert await em.evict_by_ids([episode.id], reason="activation_decay") == 1
        assert _raw(em, [episode.id])["ids"] == []
        await em.restore_from_archive(episode.id)

        again = dict(_raw(em, [episode.id])["metadatas"][0])
        assert again["valid_until"] == 1234567890.0
        assert len(_archive_rows(rig.root)) == 1  # the same (id, content_hash) slot, now holding the newest payload


# --- T10-T12 (AD-1340 R2: the restore and erase race) ----------------------------------------------------------


async def _cancel_all(tasks: list[asyncio.Task[Any]]) -> None:
    """Bound a failing test: cancel what is still pending so no task outlives the test."""
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_erase_during_restore_waits_then_erases_every_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-1340 R2: an ERASE started inside the restore's awaits waits for the lock, then erases the restored copy."""
    tasks: list[asyncio.Task[Any]] = []
    held: dict[str, Any] = {}
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        await rig.activations.record_access(_SUBJECT)
        assert await em.evict_by_ids([_SUBJECT], reason="activation_decay") == 1
        assert await _traces(em, rig.root, _SUBJECT) == {**_GONE, "episode_archive": 1}  # premise: archived only
        original = em._episode_archive.record_access  # test-only private access

        async def _erase_inside_restore(*args: Any, **kwargs: Any) -> Any:
            result = await original(*args, **kwargs)
            erase_task = asyncio.create_task(
                em.evict_by_ids([_SUBJECT], reason="erasure", disposition=EvictionDisposition.ERASE)
            )
            tasks.append(erase_task)
            held["erase_task"] = erase_task
            done, _ = await asyncio.wait({erase_task}, timeout=0.5)
            held["erase_finished_inside_restore"] = bool(done)
            held["archive_rows_inside_restore"] = len(_archive_rows(rig.root))
            return result

        monkeypatch.setattr(em._episode_archive, "record_access", _erase_inside_restore)
        try:
            restored = await em.restore_from_archive(_SUBJECT)

            assert held["erase_finished_inside_restore"] is False  # the erase waited on the store write lock
            assert held["archive_rows_inside_restore"] == 1  # the archive row was still there while restore held it
            assert restored.id == _SUBJECT
            erased, _ = await asyncio.wait({held["erase_task"]}, timeout=5)
            assert erased, "the erase never finished after the restore released the lock"
            assert await held["erase_task"] == 1
            assert await _traces(em, rig.root, _SUBJECT) == _GONE  # chroma, FTS, activation, participants, archive, access
        finally:
            await _cancel_all(tasks)


async def test_restore_during_erase_finds_no_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AD-1340 R2: a restore started inside the erase's archive phase waits, then finds no archived record."""
    tasks: list[asyncio.Task[Any]] = []
    held: dict[str, Any] = {}
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        await rig.activations.record_access(_SUBJECT)
        assert await em.evict_by_ids([_SUBJECT], reason="activation_decay") == 1
        assert await _traces(em, rig.root, _SUBJECT) == {**_GONE, "episode_archive": 1}  # premise: archived only
        original = em._episode_archive.erase  # test-only private access

        async def _restore_inside_erase(*args: Any, **kwargs: Any) -> Any:
            restore_task = asyncio.create_task(em.restore_from_archive(_SUBJECT))
            tasks.append(restore_task)
            held["restore_task"] = restore_task
            done, _ = await asyncio.wait({restore_task}, timeout=0.5)
            held["restore_finished_inside_erase"] = bool(done)
            return await original(*args, **kwargs)

        monkeypatch.setattr(em._episode_archive, "erase", _restore_inside_erase)
        try:
            erased = await em.evict_by_ids([_SUBJECT], reason="erasure", disposition=EvictionDisposition.ERASE)

            assert held["restore_finished_inside_erase"] is False  # the restore waited on the store write lock
            assert erased == 1
            finished, _ = await asyncio.wait({held["restore_task"]}, timeout=5)
            assert finished, "the restore never finished after the erase released the lock"
            with pytest.raises(LookupError, match="^episode_archive_not_found$"):
                await held["restore_task"]
            assert await _traces(em, rig.root, _SUBJECT) == _GONE  # no archive_access row either
        finally:
            await _cancel_all(tasks)


async def test_erase_during_the_restore_sidecar_tail_leaves_no_index_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-1340 R2: an ERASE started between the restore's sidecar inserts cannot leave an index row behind."""
    tasks: list[asyncio.Task[Any]] = []
    held: dict[str, Any] = {}
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        await rig.activations.record_access(_SUBJECT)
        assert await em.evict_by_ids([_SUBJECT], reason="activation_decay") == 1
        assert await _traces(em, rig.root, _SUBJECT) == {**_GONE, "episode_archive": 1}  # premise: archived only
        original = rig.participants.record_episode

        async def _erase_in_the_tail(*args: Any, **kwargs: Any) -> Any:
            result = await original(*args, **kwargs)
            erase_task = asyncio.create_task(
                em.evict_by_ids([_SUBJECT], reason="erasure", disposition=EvictionDisposition.ERASE)
            )
            tasks.append(erase_task)
            held["erase_task"] = erase_task
            done, _ = await asyncio.wait({erase_task}, timeout=0.5)
            held["erase_finished_inside_restore"] = bool(done)
            return result

        monkeypatch.setattr(rig.participants, "record_episode", _erase_in_the_tail)
        try:
            await em.restore_from_archive(_SUBJECT)

            assert held["erase_finished_inside_restore"] is False  # the erase waited for the activation insert too
            erased, _ = await asyncio.wait({held["erase_task"]}, timeout=5)
            assert erased, "the erase never finished after the restore released the lock"
            assert await held["erase_task"] == 1
            assert await _traces(em, rig.root, _SUBJECT) == _GONE
            assert _sidecar_counts(rig.root, _SUBJECT) == {"fts": 0, "activation": 0, "participants": 0}
        finally:
            await _cancel_all(tasks)


# --- T13-T17 (AD-1340 R3: the store tail and the archive eviction inside an erase) -------------------------------

_TAIL_WAIT = "probos.cognitive.episodic._ERASE_STORE_TAIL_WAIT_S"


def _start_erase(em: EpisodicMemory, tasks: list[asyncio.Task[Any]]) -> asyncio.Task[Any]:
    task = asyncio.create_task(em.evict_by_ids([_SUBJECT], reason="erasure", disposition=EvictionDisposition.ERASE))
    tasks.append(task)
    return task


class _FtsTailProxy:
    """Forwards to the real FTS connection; the first episode_fts INSERT first calls ``before_insert``."""

    def __init__(self, inner: Any, before_insert: Any) -> None:
        self.inner = inner
        self.before_insert = before_insert
        self.armed = True

    async def execute(self, sql: str, params: Any = ()) -> Any:
        if self.armed and sql.lstrip().startswith("INSERT INTO episode_fts"):
            self.armed = False
            await self.before_insert()
        return await self.inner.execute(sql, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


async def test_erase_during_the_store_participant_tail_waits_then_leaves_no_index_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-1340 R3: an ERASE that starts inside store()'s participant insert waits for it, then sweeps the new row."""
    monkeypatch.setattr(_TAIL_WAIT, 2.0)  # a mutant fails in 2 s and never hangs
    tasks: list[asyncio.Task[Any]] = []
    held: dict[str, Any] = {}
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        original = rig.participants.record_episode

        async def _erase_before_the_participant_insert(*args: Any, **kwargs: Any) -> Any:
            held["live_in_tail"] = _raw(em, [_SUBJECT])["ids"]
            held["participants_in_tail"] = _sidecar_counts(rig.root, _SUBJECT)["participants"]
            held["erase_task"] = _start_erase(em, tasks)
            done, _ = await asyncio.wait({held["erase_task"]}, timeout=0.5)
            held["erase_finished_in_tail"] = bool(done)
            return await original(*args, **kwargs)

        monkeypatch.setattr(rig.participants, "record_episode", _erase_before_the_participant_insert)
        try:
            outcome = await asyncio.wait_for(em.store(_episode(0)), timeout=10)

            assert held["live_in_tail"] == [_SUBJECT]  # premise: the add finished, the episode is live
            assert held["participants_in_tail"] == 0  # premise: the participant insert had not run
            assert outcome is EpisodeStoreOutcome.STORED
            assert held["erase_finished_in_tail"] is False  # the erase waited for the tail
            finished, _ = await asyncio.wait({held["erase_task"]}, timeout=5)
            assert finished, "the erase never finished after the store tail did"
            assert await held["erase_task"] == 1
            assert await _traces(em, rig.root, _SUBJECT) == _GONE
            assert _sidecar_counts(rig.root, _SUBJECT) == {"fts": 0, "activation": 0, "participants": 0}
        finally:
            await _cancel_all(tasks)


async def test_erase_during_the_store_fts_tail_waits_then_leaves_no_fts_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-1340 R3: an ERASE that starts inside store()'s FTS insert waits for it, then sweeps the new FTS text."""
    monkeypatch.setattr(_TAIL_WAIT, 2.0)
    tasks: list[asyncio.Task[Any]] = []
    held: dict[str, Any] = {}
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em

        async def _erase_before_the_fts_insert() -> None:
            held["live_in_tail"] = _raw(em, [_SUBJECT])["ids"]
            held["fts_in_tail"] = _sidecar_counts(rig.root, _SUBJECT)["fts"]
            held["erase_task"] = _start_erase(em, tasks)
            done, _ = await asyncio.wait({held["erase_task"]}, timeout=0.5)
            held["erase_finished_in_tail"] = bool(done)

        real = em._fts_db  # test-only private access
        em._fts_db = _FtsTailProxy(real, _erase_before_the_fts_insert)
        try:
            outcome = await asyncio.wait_for(em.store(_episode(0)), timeout=10)

            assert held["live_in_tail"] == [_SUBJECT]  # premise: the add finished, the episode is live
            assert held["fts_in_tail"] == 0  # premise: the FTS insert had not run
            assert outcome is EpisodeStoreOutcome.STORED
            assert held["erase_finished_in_tail"] is False  # the erase waited for the tail
            finished, _ = await asyncio.wait({held["erase_task"]}, timeout=5)
            assert finished, "the erase never finished after the store tail did"
            assert await held["erase_task"] == 1
            assert await _traces(em, rig.root, _SUBJECT) == _GONE
            assert _sidecar_counts(rig.root, _SUBJECT) == {"fts": 0, "activation": 0, "participants": 0}
        finally:
            em._fts_db = real
            await _cancel_all(tasks)


async def test_erase_reports_a_store_tail_that_does_not_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-1340 R3: a tail that outlives the bound makes the ERASE raise; a retry then completes it."""
    monkeypatch.setattr(_TAIL_WAIT, 0.2)
    tasks: list[asyncio.Task[Any]] = []
    held: dict[str, Any] = {}
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        original = rig.participants.record_episode

        async def _erase_then_finish_late(*args: Any, **kwargs: Any) -> Any:
            erase_task = _start_erase(em, tasks)
            done, _ = await asyncio.wait({erase_task}, timeout=5)
            held["erase_finished"] = bool(done)
            held["erase_error"] = erase_task.exception() if done and not erase_task.cancelled() else None
            return await original(*args, **kwargs)

        monkeypatch.setattr(rig.participants, "record_episode", _erase_then_finish_late)
        try:
            outcome = await asyncio.wait_for(em.store(_episode(0)), timeout=10)

            assert held["erase_finished"] is True  # premise: the erase gave up on the tail inside it
            assert outcome is EpisodeStoreOutcome.STORED
            with pytest.raises(EpisodeErasureIncomplete, match="^erasure_store_tail_pending$"):
                raise held["erase_error"]
            assert _raw(em, [_SUBJECT])["ids"] == []  # the live row was erased all the same
            counts = _sidecar_counts(rig.root, _SUBJECT)
            assert counts["fts"] == 0
            assert counts["participants"] == 2  # premise: the late tail wrote after the sweep

            retried = await asyncio.wait_for(
                em.evict_by_ids([_SUBJECT], reason="erasure", disposition=EvictionDisposition.ERASE), timeout=10,
            )

            assert retried == 0
            assert await _traces(em, rig.root, _SUBJECT) == _GONE
        finally:
            await _cancel_all(tasks)


async def test_a_cancelled_store_tail_never_blocks_erasure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AD-1340 R3: a store() cancelled inside its tail leaves no registry entry, so ERASE does not wait for it."""
    tasks: list[asyncio.Task[Any]] = []
    entered = asyncio.Event()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em

        async def _stall_in_the_tail(*args: Any, **kwargs: Any) -> Any:
            entered.set()
            await asyncio.Event().wait()  # never fires: only cancellation leaves this

        monkeypatch.setattr(rig.participants, "record_episode", _stall_in_the_tail)
        store_task = asyncio.create_task(em.store(_episode(0)))
        tasks.append(store_task)
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            assert list(em._get_store_tails()) == [_SUBJECT]  # premise: the tail is registered while it stalls
            store_task.cancel()
            results = await asyncio.gather(store_task, return_exceptions=True)

            assert isinstance(results[0], asyncio.CancelledError)
            assert em._get_store_tails() == {}
            monkeypatch.setattr(_TAIL_WAIT, 0.5)
            erased = await asyncio.wait_for(
                em.evict_by_ids([_SUBJECT], reason="erasure", disposition=EvictionDisposition.ERASE), timeout=10,
            )

            assert erased == 1
            assert await _traces(em, rig.root, _SUBJECT) == _GONE
        finally:
            await _cancel_all(tasks)


class _ObservedLock(asyncio.Lock):
    """AD-1340 S2b: the store write lock, observed. Counts acquisitions; ``contended`` resolves when an acquire finds it held."""

    def __init__(self) -> None:
        super().__init__()
        self.acquisitions = 0
        self.contended = asyncio.get_running_loop().create_future()

    async def acquire(self) -> bool:
        if self.locked() and not self.contended.done():
            self.contended.set_result(None)
        acquired = await super().acquire()
        self.acquisitions += 1
        return acquired


async def test_an_eviction_started_inside_an_erase_waits_then_finds_nothing(tmp_path: Path) -> None:
    """AD-1340 S2b (a): an eviction started inside an erase waits for the store lock, then finds the id gone.

    Replaces S1 R3's archive-eviction-inside-an-erase test. Eviction now holds the store write lock, so it can no
    longer run inside an erase's locked phases (awaiting it there would deadlock): S1's condition (d) holds by
    construction instead of by the archive lock's FIFO order.
    """
    tasks: list[asyncio.Task[Any]] = []
    held: dict[str, Any] = {}
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        observed = _ObservedLock()
        em._store_write_lock = observed  # test-only private access: the store write lock, observed
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        original = em._eviction_audit.record_batch_eviction  # test-only private access

        async def _evict_inside_the_erase(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("disposition") == DISPOSITION_ERASED and "evict_task" not in held:
                evict_task = asyncio.create_task(em.evict_by_ids([_SUBJECT], reason="activation_decay"))
                tasks.append(evict_task)
                held["evict_task"] = evict_task
                await asyncio.wait_for(asyncio.shield(observed.contended), timeout=5)  # it reached the store lock
                held["blocked_inside_erase"] = not evict_task.done()
                held["archive_rows_inside_erase"] = len(_archive_rows(rig.root))
            return await original(*args, **kwargs)

        em._eviction_audit.record_batch_eviction = _evict_inside_the_erase
        erase_task = _start_erase(em, tasks)
        try:
            finished, _ = await asyncio.wait({erase_task}, timeout=10)
            assert finished, "the erase never finished"
            assert held["blocked_inside_erase"] is True  # premise: the eviction waited on the store lock inside the erase
            assert held["archive_rows_inside_erase"] == 0  # and archived nothing there
            assert await erase_task == 1
            assert await asyncio.wait_for(held["evict_task"], timeout=5) == 0  # then it found nothing live to evict
            assert await _traces(em, rig.root, _SUBJECT) == _GONE
            assert _archive_rows(rig.root) == []
        finally:
            del em._eviction_audit.record_batch_eviction  # back to the class method
            await _cancel_all(tasks)
