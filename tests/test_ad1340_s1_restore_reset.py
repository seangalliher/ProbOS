"""AD-1340 S1 (M4): restore, the Tier 2 reset, the store declaration and the flipped default.

A real ``EpisodicMemory`` (real ChromaDB, FTS5 sidecar, ``ActivationTracker``, ``ParticipantIndex``,
``EvictionAuditLog`` and episode archive) on ``tmp_path``. The helpers of ``test_ad1340_s1_eviction.py`` build it and
read it back through independent connections; the real ``ErasureManager`` of ``test_ad1340_s1_erasure.py`` erases from
it; the reset runs through the harness of ``test_reset_integration.py``. Every test states its premise first, so a
pass cannot be vacuous. The default is ``archive`` from M4 on, but the memories built here still name their mode.
"""

from __future__ import annotations

import ast
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
)
from probos.cognitive.episodic import EpisodicMemory
from probos.config import MemoryConfig
from probos.infrastructure.backup_inventory import BackupTier, classify, is_excluded
from probos.storage.registry import load_default_store_registry
from probos.types import EpisodeStoreOutcome
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

    The last assertions pin what the reset does NOT list: ``episode_fts.db`` and the other sidecars survive every tier
    today, and BF-902 (#1579) owns changing that (D8). **BF-902 inverts the ``episode_fts.db`` assertion
    deliberately**, in the change that adds the sidecar to the table; it is that reviewed decision, not an edit to
    get past a failure here.
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
    # D8: BF-902 owns the FTS5 sidecar and the others. The loop sees the real table: it lists the archive above.
    assert [tier for tier, tier_def in RESET_TIERS.items() if "episode_fts.db" in tier_def.get("files", [])] == []
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
