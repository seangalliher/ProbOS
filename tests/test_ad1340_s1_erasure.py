"""AD-1340 S1 (M3): erasure removes every copy of an episode -- the live row, the sidecar rows and the archive rows.

A real ``EpisodicMemory`` (real ChromaDB, FTS5 sidecar, ``ActivationTracker``, ``ParticipantIndex``,
``EvictionAuditLog`` and episode archive) on ``tmp_path``, driven through the real ``ErasureManager``. The helpers of
``test_ad1340_s1_eviction.py`` are the independent witnesses: raw ``sqlite3`` for the archive, the audit and the
sidecars, and a direct ChromaDB read for the live store. Every test states its premise first, so "gone" can never mean
"was never there". ``delete`` is the default until M4, so archive-mode tests pass ``"archive"`` explicitly.
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import hashlib
import logging
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.activation_tracker import ActivationTracker
from probos.cognitive.episode_archive import (
    ARCHIVE_FILENAME,
    ARCHIVE_REASONS,
    EpisodeArchive,
    EpisodeArchiveIntegrityError,
    EpisodeArchiveUnavailable,
    EpisodeErasureIncomplete,
    decode_payload,
)
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.memory_probes import _cleanup_test_episodes
from probos.cognitive.participant_index import ParticipantIndex
from probos.config import SystemConfig
from probos.knowledge.erasure import ErasureCascadeIncomplete, ErasureManager
from probos.startup.cognitive_services import (
    ACTIVATION_TRACKER_DB,
    PARTICIPANT_INDEX_DB,
    init_cognitive_services,
    wire_erasure_sidecar_paths,
)
from probos.types import Episode, EpisodeStoreOutcome, EvictionDisposition
from tests.test_ad1340_s1_eviction import (
    _archive_rows,
    _audit_rows,
    _episode,
    _ids,
    _memory,
    _query,
    _raw,
    _record_collection,
    _Rig,
    _sidecar_counts,
    _warnings,
)

_SRC = Path(__file__).resolve().parent.parent / "src" / "probos"
# R10: the only files that may name EvictionDisposition.ERASE: the policy owner, the AD-754 manager, probe cleanup.
_ERASE_CALLERS = frozenset({"cognitive/episode_archive.py", "knowledge/erasure.py", "cognitive/memory_probes.py"})

_RESOURCE = "/srv/reactor.log"
_ATTACHMENT = hashlib.sha256(b"ad1340-s1-r3-attachment").hexdigest()
# The scene: L and B1 stay live; A, B2, P and T are archived. B1, B2 belong to agent-b, P names a path, T an attachment.
_L, _A, _B1, _B2, _P, _T = _ids(6)
_ARCHIVED = [_A, _B2, _P, _T]

# What one episode leaves in each of the six stores. "Gone" means every count is 0.
_LIVE_TRACES = {
    "chromadb": 1, "episode_fts": 1, "activation": 1, "participants": 2, "participant_lookup": 1,
    "episode_archive": 0, "archive_access": 0,
}
_ARCHIVED_TRACES = {
    "chromadb": 0, "episode_fts": 0, "activation": 0, "participants": 0, "participant_lookup": 0,
    "episode_archive": 1, "archive_access": 1,
}
_GONE = dict.fromkeys(_LIVE_TRACES, 0)
# Every table, in the sidecar databases, that can name an episode (R4 discovers them and expects exactly these).
_NAMING_TABLES = {
    "episode_fts.db:episode_fts", "activation.db:episode_access_log", "participant_index.db:episode_participants",
    f"{ARCHIVE_FILENAME}:episode_archive", f"{ARCHIVE_FILENAME}:archive_access",
}


# --- helpers -------------------------------------------------------------------------------------------------


class _Attachments:
    """The attachment store's ``unlink``: records every id it is given and reports each as removed."""

    def __init__(self) -> None:
        self.unlinked: list[str] = []

    async def unlink(self, attachment_id: str) -> bool:
        self.unlinked.append(attachment_id)
        return True


class _WatchedAttachments(_Attachments):
    """``_Attachments`` that also notes, at each ``unlink``, which live row (if any) still names the episode."""

    def __init__(self, em: EpisodicMemory, episode_id: str) -> None:
        super().__init__()
        self._em = em
        self._episode_id = episode_id
        self.live_when_unlinked: list[list[str]] = []

    async def unlink(self, attachment_id: str) -> bool:
        self.live_when_unlinked.append(_raw(self._em, [self._episode_id])["ids"])
        return await super().unlink(attachment_id)


def _manager(em: EpisodicMemory) -> tuple[ErasureManager, _Attachments]:
    attachments = _Attachments()
    return ErasureManager(episodic_memory=em, attachment_store=attachments, audit_log=None), attachments


def _scene() -> dict[str, Episode]:
    """Fresh episodes for every test: ``store`` may touch what it is given."""
    episodes = [
        _episode(0),
        _episode(1),
        dataclasses.replace(_episode(2), agent_ids=["agent-b"]),
        dataclasses.replace(_episode(3), agent_ids=["agent-b"]),
        dataclasses.replace(_episode(4), user_input=f"echo section filed the coolant readings under {_RESOURCE}"),
        dataclasses.replace(
            _episode(5), outcomes=[{"intent": "report", "success": True, "attachment_ids": [_ATTACHMENT]}],
        ),
    ]
    return {episode.id: episode for episode in episodes}


async def _participants_named(root: Path, agent_id: str) -> list[str]:
    """Ask the participant index itself, through a second handle on the same file."""
    index = ParticipantIndex(db_path=str(root / "participant_index.db"))
    await index.start()
    try:
        return await index.get_episode_ids_for_agent(agent_id)
    finally:
        await index.stop()


async def _traces(em: EpisodicMemory, root: Path, episode_id: str, *, agent: str = "agent-a") -> dict[str, int]:
    """How many rows hold this episode in each of the six stores."""
    sidecars = _sidecar_counts(root, episode_id)
    return {
        "chromadb": len(_raw(em, [episode_id])["ids"]),
        "episode_fts": sidecars["fts"],
        "activation": sidecars["activation"],
        "participants": sidecars["participants"],
        "participant_lookup": int(episode_id in await _participants_named(root, agent)),
        "episode_archive": sum(row["episode_id"] == episode_id for row in _archive_rows(root)),
        "archive_access": _query(
            root / "chroma" / ARCHIVE_FILENAME,
            "SELECT count(*) FROM archive_access WHERE episode_id = ?",
            (episode_id,),
        )[0][0],
    }


async def _record_archive_access(root: Path, episode_id: str) -> None:
    """Write an ``archive_access`` row through the archive's own API, so there is one for erasure to clear."""
    archive = EpisodeArchive(str(root / "chroma" / ARCHIVE_FILENAME))
    await archive.start()
    try:
        await archive.record_access(episode_id, accessor="r-tests", purpose="seed an archive_access row")
    finally:
        await archive.stop()


async def _seed(rig: _Rig, episodes: Sequence[Episode], *, archive: Sequence[str] = ()) -> dict[str, str]:
    """Store the episodes (each read once, so the activation log holds a row), archive the ids in ``archive``, and prove
    that every episode stands where the test expects it. Returns the content hash each one was stored with."""
    em = rig.em
    for episode in episodes:
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
        await rig.activations.record_access(episode.id)
    hashes = {episode.id: _raw(em, [episode.id])["metadatas"][0]["content_hash"] for episode in episodes}
    assert all(hashes.values())
    assert await em.evict_by_ids(list(archive), reason="activation_decay") == len(archive)
    for episode_id in archive:
        await _record_archive_access(rig.root, episode_id)
    for episode in episodes:
        expected = _ARCHIVED_TRACES if episode.id in archive else _LIVE_TRACES
        assert await _traces(em, rig.root, episode.id, agent=episode.agent_ids[0]) == expected, episode.id
    return hashes


def _audit_for(root: Path, episode_id: str, disposition: str) -> list[dict[str, Any]]:
    return [row for row in _audit_rows(root) if row["episode_id"] == episode_id and row["disposition"] == disposition]


def _rows_naming(root: Path, episode_ids: Sequence[str]) -> dict[str, int]:
    """Rows naming any of these ids, in every table of every sidecar database that has an ``episode_id`` column.

    The tables are discovered, not listed, so a table added to a sidecar later is swept too.
    """
    marks = ",".join("?" * len(episode_ids))
    counts: dict[str, int] = {}
    for path in (
        root / "chroma" / "episode_fts.db", root / "activation.db", root / "participant_index.db",
        root / "chroma" / ARCHIVE_FILENAME,
    ):
        for (table,) in _query(path, "SELECT name FROM sqlite_master WHERE type = 'table'"):
            if "episode_id" in [column[1] for column in _query(path, f'PRAGMA table_info("{table}")')]:
                counts[f"{path.name}:{table}"] = _query(
                    path, f'SELECT count(*) FROM "{table}" WHERE episode_id IN ({marks})', tuple(episode_ids),
                )[0][0]
    return counts


def _erase_references(source: str) -> list[int]:
    """Line numbers of every ``EvictionDisposition.ERASE`` attribute reference in ``source`` (aliases included)."""
    tree = ast.parse(source)
    names = {"EvictionDisposition"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname for alias in node.names if alias.name == "EvictionDisposition" and alias.asname)
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "ERASE"
        and (
            (isinstance(node.value, ast.Name) and node.value.id in names)
            or (isinstance(node.value, ast.Attribute) and node.value.attr == "EvictionDisposition")
        )
    )


# --- R1 ------------------------------------------------------------------------------------------------------


async def test_erase_live_and_archived(tmp_path: Path) -> None:
    scene = _scene()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        hashes = await _seed(rig, [scene[_L], scene[_A]], archive=[_A])  # premise: L is live, A only archived

        result = await manager.forget_episode(_L)

        assert result.deleted_episode_ids == [_L]
        assert await _traces(em, rig.root, _L) == _GONE
        # Targeted: erasing the live episode left the archived one where it was.
        assert await _traces(em, rig.root, _A) == _ARCHIVED_TRACES
        erased = _audit_for(rig.root, _L, "erased")
        assert [row["content_hash"] for row in erased] == [hashes[_L]]

        result = await manager.forget_episode(_A)

        assert result.deleted_episode_ids == [_A]
        assert await _traces(em, rig.root, _A) == _GONE
        erased = _audit_for(rig.root, _A, "erased")
        assert [row["content_hash"] for row in erased] == [hashes[_A]]
        assert len(_audit_for(rig.root, _A, "archived")) == 1  # the eviction's row stays: the audit is append-only


# --- R2 ------------------------------------------------------------------------------------------------------


async def test_cascades_reach_the_archive(tmp_path: Path) -> None:
    scene = _scene()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        await _seed(rig, list(scene.values()), archive=_ARCHIVED)  # premise: B1 live and B2 archived, both agent-b
        live = await em.list_episodes()
        assert [episode.id for episode in live if "agent-b" in episode.agent_ids] == [_B1]
        assert [episode.id for episode in live if _RESOURCE in episode.user_input] == []  # no live episode names it
        named = [
            row["episode_id"] for row in _archive_rows(rig.root)
            if _RESOURCE in decode_payload(
                row["episode_id"], row["content_hash"], row["payload_format"], row["payload"],
            ).metadata["user_input"]
        ]
        assert named == [_P]  # only an archived episode does

        by_agent = await manager.forget_agent_memory("agent-b")

        assert sorted(by_agent.deleted_episode_ids) == [_B1, _B2]
        for episode_id in (_B1, _B2):
            assert await _traces(em, rig.root, episode_id, agent="agent-b") == _GONE
        # The agent-a control episodes, live and archived, and the path's episode were not touched.
        for episode_id, expected in ((_L, _LIVE_TRACES), (_A, _ARCHIVED_TRACES), (_P, _ARCHIVED_TRACES)):
            assert await _traces(em, rig.root, episode_id) == expected, episode_id

        by_resource = await manager.forget_resource(_RESOURCE)

        assert by_resource.deleted_episode_ids == [_P]
        assert await _traces(em, rig.root, _P) == _GONE
        for episode_id, expected in ((_L, _LIVE_TRACES), (_A, _ARCHIVED_TRACES), (_T, _ARCHIVED_TRACES)):
            assert await _traces(em, rig.root, episode_id) == expected, episode_id


# --- R3 ------------------------------------------------------------------------------------------------------


async def test_attachment_of_an_archived_episode_is_unlinked(tmp_path: Path) -> None:
    scene = _scene()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, attachments = _manager(em)
        await _seed(rig, [scene[_T]], archive=[_T])
        # premise: not live by any read, so the archive is the only place its attachment id survives
        assert _raw(em, [_T])["ids"] == []
        assert await em.get_by_ids([_T]) == []
        assert await em.get_episode_metadata(_T) is None
        (row,) = _archive_rows(rig.root)
        archived = decode_payload(row["episode_id"], row["content_hash"], row["payload_format"], row["payload"])
        assert _ATTACHMENT in archived.metadata["outcomes_json"]
        assert attachments.unlinked == []

        result = await manager.forget_episode(_T)

        assert attachments.unlinked == [_ATTACHMENT]
        assert result.deleted_attachment_ids == [_ATTACHMENT]
        assert result.deleted_episode_ids == [_T]


# --- R4 ------------------------------------------------------------------------------------------------------


async def test_erasure_leaves_only_the_audit_row(tmp_path: Path) -> None:
    scene = _scene()
    everyone = list(scene)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        await _seed(rig, list(scene.values()), archive=_ARCHIVED)
        # premise: every table that can name an episode names some of these, so a zero afterwards is an erasure
        named_before = _rows_naming(rig.root, everyone)
        assert set(named_before) == _NAMING_TABLES
        assert all(count > 0 for count in named_before.values()), named_before

        # What R1, R2 and R3 each erase, one after the other.
        assert (await manager.forget_episode(_L)).deleted_episode_ids == [_L]
        assert (await manager.forget_episode(_A)).deleted_episode_ids == [_A]
        assert sorted((await manager.forget_agent_memory("agent-b")).deleted_episode_ids) == [_B1, _B2]
        assert (await manager.forget_resource(_RESOURCE)).deleted_episode_ids == [_P]
        assert (await manager.forget_episode(_T)).deleted_episode_ids == [_T]

        for episode_id, episode in scene.items():
            assert await _traces(em, rig.root, episode_id, agent=episode.agent_ids[0]) == _GONE, episode_id
        assert _rows_naming(rig.root, everyone) == dict.fromkeys(named_before, 0)
        assert await em.list_episodes() == []  # nothing is live

        # The audit is the one place that still names them, and it holds a hash, not what the episode said.
        audit = _audit_rows(rig.root)
        assert {row["episode_id"] for row in audit if row["disposition"] == "erased"} == set(everyone)
        content = [episode.user_input for episode in scene.values()] + [_RESOURCE, _ATTACHMENT]
        assert not [
            row for row in audit if any(text in str(value) for value in row.values() for text in content)
        ]


# --- R5 ------------------------------------------------------------------------------------------------------


async def test_custom_reason_from_the_erasure_api_still_erases(tmp_path: Path) -> None:
    reason = "Captain: forget the reactor incident"
    scene = _scene()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        await _seed(rig, [scene[_L], scene[_A]], archive=[_A])
        assert reason not in ARCHIVE_REASONS  # premise: a reason that policy has never heard of

        for episode_id in (_L, _A):
            result = await manager.forget_episode(episode_id, reason=reason)

            assert result.deleted_episode_ids == [episode_id]
            assert await _traces(em, rig.root, episode_id) == _GONE
            assert [row["reason"] for row in _audit_for(rig.root, episode_id, "erased")] == [reason]


# --- R6 ------------------------------------------------------------------------------------------------------


async def test_probe_cleanup_erases(tmp_path: Path) -> None:
    ids = _ids(2)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        for i in range(2):
            assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        # premise: two live episodes, an archive that is open and empty, and an audit with nothing in it
        assert sorted(_raw(em, ids)["ids"]) == ids
        assert em.archive_available and _archive_rows(rig.root) == [] and _audit_rows(rig.root) == []

        await _cleanup_test_episodes(em, ids)

        assert _raw(em, ids)["ids"] == []
        assert _archive_rows(rig.root) == []
        audit = _audit_rows(rig.root)
        assert sorted(row["episode_id"] for row in audit) == ids
        assert {(row["disposition"], row["reason"]) for row in audit} == {("erased", "qualification_test_cleanup")}


# --- R7 ------------------------------------------------------------------------------------------------------


async def test_erase_with_a_failed_archive_deletes_live_then_raises(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    blocker = tmp_path / "chroma" / ARCHIVE_FILENAME
    blocker.mkdir(parents=True)
    assert blocker.is_dir()  # premise: a directory stands where the archive file would be created
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        assert em.archive_available is False
        assert _warnings(caplog, "failed to open")  # the archive failed to open: "failed", not merely absent
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        assert _raw(em, ["ep-000"])["ids"] == ["ep-000"]
        assert _sidecar_counts(rig.root, "ep-000")["fts"] == 1  # premise: live, and in the FTS sidecar

        with pytest.raises(EpisodeArchiveUnavailable, match="episode_archive_unavailable_for_erase"):
            await em.evict_by_ids(["ep-000"], disposition=EvictionDisposition.ERASE)

        # The live copy went first; only the archive, which may hold another copy, could not be checked.
        assert _raw(em, ["ep-000"])["ids"] == []
        assert _sidecar_counts(rig.root, "ep-000")["fts"] == 0
        assert [(row["episode_id"], row["disposition"]) for row in _audit_rows(rig.root)] == [("ep-000", "erased")]

        with pytest.raises(ErasureCascadeIncomplete) as info:
            await manager.forget_resource("x")  # the cascade cannot read the archive either
        # M3r: this used to pin the bare EpisodeArchiveUnavailable out of the cascade, which was raised before any
        # match was erased. The cascade now erases what it found, then raises one error naming the scan failure.
        assert isinstance(info.value.enumeration_error, EpisodeArchiveUnavailable)
        assert info.value.failures == {}
        assert isinstance(info.value.__cause__, EpisodeArchiveUnavailable)


# --- R8 ------------------------------------------------------------------------------------------------------


async def test_delete_mode_erase_clears_a_leftover_archive(tmp_path: Path) -> None:
    leftover, fresh = tmp_path / "leftover", tmp_path / "fresh"
    async with _memory(leftover, "archive") as rig:
        for i in range(2):
            assert await rig.em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        assert await rig.em.evict_by_ids(["ep-000"], reason="activation_decay") == 1
        assert [row["episode_id"] for row in _archive_rows(leftover)] == ["ep-000"]  # premise: X is archived

    async with _memory(leftover, "delete") as rig:
        em = rig.em
        manager, _ = _manager(em)
        assert em.eviction_disposition_mode == "delete"
        assert em.archive_available is True  # premise: the file archive mode left behind was opened

        result = await manager.forget_episode("ep-000")

        assert result.deleted_episode_ids == ["ep-000"]
        assert _archive_rows(leftover) == []

    async with _memory(fresh, "delete") as rig:
        em = rig.em
        manager, _ = _manager(em)
        archive_path = fresh / "chroma" / ARCHIVE_FILENAME
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        await rig.activations.record_access("ep-000")
        # premise: delete mode with no archive file has no archive, and the episode is live and in every sidecar
        assert em.archive_available is False and not archive_path.exists()
        assert _raw(em, ["ep-000"])["ids"] == ["ep-000"]
        assert _sidecar_counts(fresh, "ep-000") == {"fts": 1, "activation": 1, "participants": 2}

        result = await manager.forget_episode("ep-000")

        assert result.deleted_episode_ids == ["ep-000"]
        assert _raw(em, ["ep-000"])["ids"] == []
        assert _sidecar_counts(fresh, "ep-000") == {"fts": 0, "activation": 0, "participants": 0}
        assert not archive_path.exists()  # erasing did not create an archive to look in


# --- R9 ------------------------------------------------------------------------------------------------------


async def test_sidecar_failure_on_erase_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = _ids(2)

    async def _fail(self: ParticipantIndex, episode_ids: list[str]) -> None:
        raise RuntimeError("injected: the participant index cannot delete")

    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        await _seed(rig, [_episode(0), _episode(1)])  # premise: both live, in every sidecar
        monkeypatch.setattr(ParticipantIndex, "delete_episodes", _fail)

        with pytest.raises(EpisodeErasureIncomplete, match="participant_index"):
            await em.evict_by_ids([ids[0]], reason="activation_decay", disposition=EvictionDisposition.ERASE)

        assert _raw(em, [ids[0]])["ids"] == []  # the live row went first
        # Every other cleanup was still attempted; the participant rows are what survived, which is what the error says.
        assert _sidecar_counts(rig.root, ids[0]) == {"fts": 0, "activation": 0, "participants": 2}

        # The same fault under archive eviction is best-effort, as it was before AD-1340: no error.
        assert await em.evict_by_ids([ids[1]], reason="activation_decay") == 1
        assert _raw(em, [ids[1]])["ids"] == []
        assert [row["episode_id"] for row in _archive_rows(rig.root)] == [ids[1]]
        assert _sidecar_counts(rig.root, ids[1]) == {"fts": 0, "activation": 0, "participants": 2}  # the fault did fire


# --- R10 -----------------------------------------------------------------------------------------------------


def test_only_declared_callers_name_erase() -> None:
    """No agent-facing path reaches ERASE (AD-1339).

    ERASE destroys the archive's copy as well, so the code allowed to ask for it is a closed list: the policy owner
    (``resolve_disposition``), the AD-754 ``ErasureManager`` and the qualification-test cleanup. Adding a caller is a
    reviewed decision with its own argument, not a test edit to get past.
    """
    # premise: the scanner finds each spelling it claims to find, and nothing else
    assert _erase_references("from probos.types import EvictionDisposition\nx = EvictionDisposition.ERASE") == [2]
    assert _erase_references("from probos.types import EvictionDisposition as D\nx = D.ERASE") == [2]
    assert _erase_references("import probos.types as t\nx = t.EvictionDisposition.ERASE") == [2]
    assert _erase_references("x = Other.ERASE\ny = EvictionDisposition.ARCHIVE") == []

    found = {
        path.relative_to(_SRC).as_posix(): lines
        for path in sorted(_SRC.rglob("*.py"))
        if (lines := _erase_references(path.read_text(encoding="utf-8")))
    }
    # premise: the scan reaches the three declared callers, so "nothing else" is not the product of an empty scan
    missing = sorted(_ERASE_CALLERS - found.keys())
    assert not missing, f"the scan found no EvictionDisposition.ERASE reference in the declared callers {missing}"

    outside = {name: lines for name, lines in found.items() if name not in _ERASE_CALLERS}
    assert not outside, f"EvictionDisposition.ERASE is named outside the declared callers: {outside}"


# --- R11 -----------------------------------------------------------------------------------------------------


async def test_failed_erase_still_unlinks_the_attachments(tmp_path: Path) -> None:
    blocker = tmp_path / "chroma" / ARCHIVE_FILENAME
    blocker.mkdir(parents=True)
    assert blocker.is_dir()  # premise: a directory stands where the archive file would be created
    audit_log = AsyncMock()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        attachments = _WatchedAttachments(em, _T)
        manager = ErasureManager(episodic_memory=em, attachment_store=attachments, audit_log=audit_log)
        assert em.archive_available is False  # premise: the archive failed to open, so the erase will raise
        assert await em.store(_scene()[_T]) is EpisodeStoreOutcome.STORED
        live = _raw(em, [_T])
        assert live["ids"] == [_T]
        assert _ATTACHMENT in live["metadatas"][0]["outcomes_json"]  # premise: the live row is where the id is written
        assert attachments.unlinked == []

        with pytest.raises(EpisodeArchiveUnavailable, match="episode_archive_unavailable_for_erase"):
            await manager.forget_episode(_T)

        assert attachments.unlinked == [_ATTACHMENT]  # the erase raised, and the attachment was unlinked all the same
        assert attachments.live_when_unlinked == [[_T]]  # unlinked BEFORE the erase: the row naming it still stood
        assert _raw(em, [_T])["ids"] == []  # and the erase did delete the live row, as in R7
        audit_log.mark_deleted.assert_not_awaited()  # the audit marker is written only after a successful erase


# --- R12 -----------------------------------------------------------------------------------------------------


async def test_cascade_continues_past_a_failing_episode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _scene()
    delete_episodes = ParticipantIndex.delete_episodes
    seen: list[list[str]] = []

    async def _fail_for_b1(self: ParticipantIndex, episode_ids: list[str]) -> None:
        seen.append(list(episode_ids))
        if _B1 in episode_ids:
            raise RuntimeError("injected: the participant index cannot delete B1")
        await delete_episodes(self, episode_ids)

    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        await _seed(rig, list(scene.values()), archive=_ARCHIVED)  # premise: B1 live and B2 archived, both agent-b
        live = await em.list_episodes()
        assert [episode.id for episode in live if "agent-b" in episode.agent_ids] == [_B1]
        assert _B2 in [row["episode_id"] for row in _archive_rows(rig.root)]
        monkeypatch.setattr(ParticipantIndex, "delete_episodes", _fail_for_b1)

        with pytest.raises(ErasureCascadeIncomplete) as info:
            await manager.forget_agent_memory("agent-b")

        error = info.value
        assert seen == [[_B1], [_B2]]  # B1 failed first, and the cascade still went on to B2
        assert set(error.failures) == {_B1}
        assert isinstance(error.failures[_B1], EpisodeErasureIncomplete)
        assert error.enumeration_error is None
        assert error.result.deleted_episode_ids == [_B2]  # what was erased is reported, and it is not B1
        assert await _traces(em, rig.root, _B2, agent="agent-b") == _GONE
        assert _raw(em, [_B1])["ids"] == []  # B1's live row went before its sidecar sweep failed ...
        # ... and the participant rows are what the failed sweep left; every other cleanup was still done
        assert _sidecar_counts(rig.root, _B1) == {"fts": 0, "activation": 0, "participants": 2}
        # The agent-a control episodes, live and archived, were not touched.
        for episode_id, expected in ((_L, _LIVE_TRACES), (_A, _ARCHIVED_TRACES)):
            assert await _traces(em, rig.root, episode_id) == expected, episode_id


# --- R13 -----------------------------------------------------------------------------------------------------


async def test_cascade_erases_the_live_matches_when_the_archive_scan_fails(tmp_path: Path) -> None:
    blocker = tmp_path / "chroma" / ARCHIVE_FILENAME
    blocker.mkdir(parents=True)
    assert blocker.is_dir()  # premise: a directory stands where the archive file would be created
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, attachments = _manager(em)
        assert em.archive_available is False  # premise: the archive failed to open
        for episode in (_episode(0), _scene()[_T]):
            assert await em.store(episode) is EpisodeStoreOutcome.STORED
            await rig.activations.record_access(episode.id)
        live = await em.list_episodes()
        assert sorted(episode.id for episode in live if "agent-a" in episode.agent_ids) == [_L, _T]  # premise
        assert _ATTACHMENT in _raw(em, [_T])["metadatas"][0]["outcomes_json"]
        for episode_id in (_L, _T):
            assert _sidecar_counts(rig.root, episode_id) == {"fts": 1, "activation": 1, "participants": 2}

        with pytest.raises(ErasureCascadeIncomplete) as info:
            await manager.forget_agent_memory("agent-a")

        error = info.value
        assert isinstance(error.enumeration_error, EpisodeArchiveUnavailable)  # the scan met the failed archive ...
        assert set(error.failures) == {_L, _T}  # ... and so did each per-episode erase, after it deleted the live row
        assert all(isinstance(failure, EpisodeArchiveUnavailable) for failure in error.failures.values())
        assert _raw(em, [_L, _T])["ids"] == []  # both matches were erased all the same
        for episode_id in (_L, _T):
            assert _sidecar_counts(rig.root, episode_id) == {"fts": 0, "activation": 0, "participants": 0}
        assert attachments.unlinked == [_ATTACHMENT]


# --- R14 -----------------------------------------------------------------------------------------------------


async def test_a_failed_live_delete_still_erases_the_archive_copy(tmp_path: Path) -> None:
    scene = _scene()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        await _seed(rig, [scene[_L], scene[_A]], archive=[_A])  # premise: L is live, A only archived
        assert [row["episode_id"] for row in _archive_rows(rig.root)] == [_A]
        proxy = _record_collection(em)
        proxy.fail_next_delete = True

        with pytest.raises(RuntimeError, match="^injected: delete failed$"):
            await em.evict_by_ids([_L, _A], disposition=EvictionDisposition.ERASE)

        assert ("delete", None) in proxy.calls and proxy.fail_next_delete is False  # the live delete ran, and failed
        assert [row for row in _archive_rows(rig.root) if row["episode_id"] == _A] == []  # A's copy went regardless
        assert _raw(em, [_L])["ids"] == [_L]  # L's live row survived the failed delete


# --- R15 -----------------------------------------------------------------------------------------------------


async def test_retry_after_a_partial_erase_sweeps_what_was_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _ids(2)

    async def _fail(self: ParticipantIndex, episode_ids: list[str]) -> None:
        raise RuntimeError("injected: the participant index cannot delete")

    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        await _seed(rig, [_episode(0), _episode(1)])  # premise: both live, in every sidecar
        monkeypatch.setattr(ParticipantIndex, "delete_episodes", _fail)
        with pytest.raises(EpisodeErasureIncomplete, match="participant_index"):
            await em.evict_by_ids([ids[0]], reason="activation_decay", disposition=EvictionDisposition.ERASE)
        # premise: the live row is gone, so a retry finds nothing to erase; the participant rows are what survived
        assert _raw(em, [ids[0]])["ids"] == []
        assert _sidecar_counts(rig.root, ids[0])["participants"] == 2
        monkeypatch.undo()  # the fault is removed

        assert await em.evict_by_ids([ids[0]], reason="activation_decay", disposition=EvictionDisposition.ERASE) == 0

        assert _sidecar_counts(rig.root, ids[0]) == {"fts": 0, "activation": 0, "participants": 0}
        assert ids[0] not in await _participants_named(rig.root, "agent-a")
        # Targeted: the sweep is keyed on the requested id, so the other episode stands untouched.
        assert _sidecar_counts(rig.root, ids[1]) == {"fts": 1, "activation": 1, "participants": 2}


# --- R16 - R23: the sidecar sweep reaches a store that has no open handle (AD-1340 R1, F1) ---------------------

_CLEARED = {"fts": 0, "activation": 0, "participants": 0}


async def test_erase_clears_activation_rows_when_the_tracker_is_not_wired(tmp_path: Path) -> None:
    episode = _episode(0)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        await _seed(rig, [episode])
        await rig.activations.stop()  # the standalone tracker wrote its row and is done
        em.set_activation_tracker(None)  # activation tracking is off: no tracker is wired, the file is declared
        assert _sidecar_counts(rig.root, episode.id) == {"fts": 1, "activation": 1, "participants": 2}  # premise

        erased = await em.evict_by_ids([episode.id], reason="user_request", disposition=EvictionDisposition.ERASE)

        assert erased == 1
        assert _sidecar_counts(rig.root, episode.id) == _CLEARED


async def test_erase_clears_participant_rows_after_a_failed_index_start(tmp_path: Path) -> None:
    episode = _episode(0)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        await _seed(rig, [episode])
        await rig.participants.stop()
        em.set_participant_index(None)  # the index failed to start: nothing is wired, the file still holds rows
        assert _sidecar_counts(rig.root, episode.id)["participants"] == 2  # premise

        erased = await em.evict_by_ids([episode.id], reason="user_request", disposition=EvictionDisposition.ERASE)

        assert erased == 1
        assert _sidecar_counts(rig.root, episode.id) == _CLEARED


async def test_erase_raises_when_an_unwired_store_cannot_be_opened(tmp_path: Path) -> None:
    episode = _episode(0)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
        await rig.activations.record_access(episode.id)
        assert await em.evict_by_ids([episode.id], reason="activation_decay") == 1
        await em.restore_from_archive(episode.id)  # live again, with its archive row kept
        assert _raw(em, [episode.id])["ids"] == [episode.id]
        assert len(_archive_rows(rig.root)) == 1
        assert _sidecar_counts(rig.root, episode.id)["fts"] == 1
        await rig.participants.stop()
        em.set_participant_index(None)
        (rig.root / "participant_index.db").write_bytes(b"this is not an sqlite database " * 64)

        with pytest.raises(EpisodeErasureIncomplete, match="participant_index"):
            await em.evict_by_ids([episode.id], reason="user_request", disposition=EvictionDisposition.ERASE)

        # Every other copy was still cleared: the failure is reported, not allowed to spare anything else.
        assert _raw(em, [episode.id])["ids"] == []
        assert _archive_rows(rig.root) == []
        counts = _sidecar_counts_without_participants(rig.root, episode.id)
        assert counts == {"fts": 0, "activation": 0}


def _sidecar_counts_without_participants(root: Path, episode_id: str) -> dict[str, int]:
    return {
        "fts": _query(root / "chroma" / "episode_fts.db", "SELECT count(*) FROM episode_fts WHERE episode_id = ?", (episode_id,))[0][0],
        "activation": _query(root / "activation.db", "SELECT count(*) FROM episode_access_log WHERE episode_id = ?", (episode_id,))[0][0],
    }


async def test_erase_with_no_sidecar_file_is_complete_and_creates_none(tmp_path: Path) -> None:
    episode = _episode(0)
    activation_path = tmp_path / "activation.db"
    participants_path = tmp_path / "participant_index.db"
    em = EpisodicMemory(
        db_path=str(tmp_path / "chroma" / "episodes.db"), relevance_threshold=0.0, eviction_disposition="archive",
    )
    em.set_erasure_sidecar_paths(
        activation_db_path=str(activation_path), participant_index_db_path=str(participants_path),
    )
    await em.start()
    try:
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
        assert not activation_path.exists() and not participants_path.exists()  # premise: no sidecar file was ever made

        erased = await em.evict_by_ids([episode.id], reason="user_request", disposition=EvictionDisposition.ERASE)

        assert erased == 1
        assert _raw(em, [episode.id])["ids"] == []
        assert not activation_path.exists() and not participants_path.exists()  # erasing created neither
    finally:
        await em.stop()


async def test_erase_clears_fts_text_when_the_fts_handle_is_closed(tmp_path: Path) -> None:
    episode = _episode(0)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        await _seed(rig, [episode])
        await em._fts_db.close()  # test-only private access: the FTS handle is closed ...
        em._fts_db = None  # ... and no longer wired, as after a failed FTS open
        assert _sidecar_counts(rig.root, episode.id)["fts"] == 1  # premise: the file still holds the text

        erased = await em.evict_by_ids([episode.id], reason="user_request", disposition=EvictionDisposition.ERASE)

        assert erased == 1
        assert _sidecar_counts(rig.root, episode.id)["fts"] == 0


async def test_erase_clears_stores_whose_handles_were_stopped(tmp_path: Path) -> None:
    episode = _episode(0)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        await _seed(rig, [episode])
        await rig.activations.stop()  # still wired, but stopped: its delete would silently do nothing
        await rig.participants.stop()
        assert not rig.activations.is_open and not rig.participants.is_open  # premise
        assert _sidecar_counts(rig.root, episode.id) == {"fts": 1, "activation": 1, "participants": 2}

        erased = await em.evict_by_ids([episode.id], reason="user_request", disposition=EvictionDisposition.ERASE)

        assert erased == 1
        assert _sidecar_counts(rig.root, episode.id) == _CLEARED


class _FtsProxy:
    """Forwards to the real FTS connection, but its DELETE raises for one episode id."""

    def __init__(self, inner: Any, failing_id: str) -> None:
        self.inner = inner
        self.failing_id = failing_id

    async def execute(self, sql: str, params: Any = ()) -> Any:
        if sql.startswith("DELETE") and params and params[0] == self.failing_id:
            raise RuntimeError("injected: the FTS delete failed")
        return await self.inner.execute(sql, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


async def test_one_failing_fts_delete_does_not_spare_the_other_ids(tmp_path: Path) -> None:
    ids = _ids(2)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        await _seed(rig, [_episode(0), _episode(1)])
        real = em._fts_db  # test-only private access
        em._fts_db = _FtsProxy(real, ids[0])
        try:
            with pytest.raises(EpisodeErasureIncomplete, match="episode_fts"):
                await em.evict_by_ids(ids, reason="user_request", disposition=EvictionDisposition.ERASE)
        finally:
            em._fts_db = real

        assert _sidecar_counts(rig.root, ids[0])["fts"] == 1  # premise: the injected failure is what was left
        assert _sidecar_counts(rig.root, ids[1])["fts"] == 0  # the sweep went on to the second id


async def test_erase_on_a_stopped_memory_raises(tmp_path: Path) -> None:
    episode = _episode(0)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        await _seed(rig, [episode])
        await em.stop()

        with pytest.raises(EpisodeErasureIncomplete, match="live_store"):
            await em.evict_by_ids([episode.id], reason="user_request", disposition=EvictionDisposition.ERASE)


# --- R24 - R28: cascades see every archived version (AD-1340 R1, F2, F3, S2) ----------------------------------

_ATT1 = hashlib.sha256(b"ad1340-r1-attachment-1").hexdigest()
_ATT2 = hashlib.sha256(b"ad1340-r1-attachment-2").hexdigest()


def _versions() -> tuple[Episode, Episode]:
    """Two versions of one episode id: v1 (agent-a, declares ATT1) and v2 (agent-b, declares ATT2)."""
    v1 = dataclasses.replace(
        _episode(1), agent_ids=["agent-a"], user_input="alpha reactor section coolant reading one",
        outcomes=[{"intent": "report", "success": True, "attachment_ids": [_ATT1]}],
    )
    v2 = dataclasses.replace(
        v1, agent_ids=["agent-b"], user_input="bravo hangar section cargo manifest two",
        outcomes=[{"intent": "report", "success": True, "attachment_ids": [_ATT2]}],
    )
    return v1, v2


async def test_cascade_matches_an_archived_version_shadowed_by_a_live_one(tmp_path: Path) -> None:
    v1, v2 = _versions()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        assert await em.store(v1) is EpisodeStoreOutcome.STORED
        assert await em.evict_by_ids([v1.id], reason="activation_decay") == 1
        assert await em.store(v2) is EpisodeStoreOutcome.STORED
        # premise: v1 (agent-a) archived, v2 (agent-b) live, under the one id
        assert [(row["episode_id"], row["agent_id"]) for row in _archive_rows(rig.root)] == [(v1.id, "agent-a")]
        assert [(e.id, e.agent_ids) for e in await em.list_episodes()] == [(v1.id, ["agent-b"])]

        result = await manager.forget_agent_memory("agent-a")

        assert result.deleted_episode_ids == [v1.id]
        assert _archive_rows(rig.root) == []
        assert _raw(em, [v1.id])["ids"] == []  # erased by id, as D6 states: the unit of erasure is the episode id


async def test_forget_episode_unlinks_attachments_of_every_archived_version(tmp_path: Path) -> None:
    v1, v2 = _versions()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, attachments = _manager(em)
        assert await em.store(v1) is EpisodeStoreOutcome.STORED
        assert await em.evict_by_ids([v1.id], reason="activation_decay") == 1
        assert await em.store(v2) is EpisodeStoreOutcome.STORED
        assert await em.evict_by_ids([v2.id], reason="activation_decay") == 1
        assert len(_archive_rows(rig.root)) == 2  # premise: two archived versions, none live
        assert _raw(em, [v1.id])["ids"] == []
        assert attachments.unlinked == []

        result = await manager.forget_episode(v1.id)

        assert sorted(attachments.unlinked) == sorted([_ATT1, _ATT2])
        assert result.deleted_attachment_ids == sorted([_ATT1, _ATT2])
        assert _archive_rows(rig.root) == []


async def test_forget_episode_unions_live_and_archived_attachments(tmp_path: Path) -> None:
    v1, v2 = _versions()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, attachments = _manager(em)
        assert await em.store(v1) is EpisodeStoreOutcome.STORED
        assert await em.evict_by_ids([v1.id], reason="activation_decay") == 1
        assert await em.store(v2) is EpisodeStoreOutcome.STORED
        assert len(_archive_rows(rig.root)) == 1  # premise: v1 archived, v2 live
        assert _ATT2 in _raw(em, [v2.id])["metadatas"][0]["outcomes_json"]
        assert attachments.unlinked == []

        await manager.forget_episode(v1.id)

        assert sorted(attachments.unlinked) == sorted([_ATT1, _ATT2])


async def test_cascade_reports_an_archived_record_that_cannot_rehydrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad, good = _episode(0), _episode(1)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        await _seed(rig, [bad, good], archive=[bad.id, good.id])
        original = em._metadata_to_episode

        def _fail_for_bad(episode_id: str, document: str, metadata: dict[str, Any]) -> Any:
            if episode_id == bad.id:
                raise ValueError("injected: this record cannot be rehydrated")
            return original(episode_id, document, metadata)

        monkeypatch.setattr(em, "_metadata_to_episode", _fail_for_bad)

        with pytest.raises(ErasureCascadeIncomplete) as info:
            await manager.forget_agent_memory("agent-a")

        error = info.value
        assert isinstance(error.enumeration_error, EpisodeArchiveIntegrityError)
        assert str(error.enumeration_error) == "episode_archive_rows_unrehydratable:1"
        assert error.failures == {}
        assert error.result.deleted_episode_ids == [good.id]  # the other match was erased
        assert await _traces(em, rig.root, good.id) == _GONE
        # premise of the report: the record it names is still archived
        assert await _traces(em, rig.root, bad.id) == _ARCHIVED_TRACES


async def test_cascade_scans_past_an_undecodable_archived_row(tmp_path: Path) -> None:
    first, second = _episode(0), _episode(1)  # ep-000 sorts before ep-001: the corrupt row is met first
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        await _seed(rig, [first, second], archive=[first.id, second.id])
        with contextlib.closing(sqlite3.connect(rig.root / "chroma" / ARCHIVE_FILENAME, timeout=5)) as connection:
            connection.execute("UPDATE episode_archive SET payload = ? WHERE episode_id = ?", (b"not zlib", first.id))
            connection.commit()

        with pytest.raises(ErasureCascadeIncomplete) as info:
            await manager.forget_agent_memory("agent-a")

        error = info.value
        assert isinstance(error.enumeration_error, EpisodeArchiveIntegrityError)
        assert str(error.enumeration_error) == "episode_archive_rows_undecodable:1"
        assert error.result.deleted_episode_ids == [second.id]  # the higher-key match, found past the bad row
        assert await _traces(em, rig.root, second.id) == _GONE
        assert [row["episode_id"] for row in _archive_rows(rig.root)] == [first.id]  # the bad row is what is left


# --- R29 -----------------------------------------------------------------------------------------------------


async def test_startup_sidecar_paths_reach_erase(tmp_path: Path) -> None:
    """The production layout: startup declares the files, ERASE clears them. This crosses that seam."""
    episode = _episode(0)
    activation_path = tmp_path / ACTIVATION_TRACKER_DB
    participants_path = tmp_path / PARTICIPANT_INDEX_DB
    fts_path = tmp_path / "episode_fts.db"  # beside EpisodicMemory(db_path=data_dir/"episodic.db")
    activations = ActivationTracker(db_path=str(activation_path))
    participants = ParticipantIndex(db_path=str(participants_path))
    await activations.start()
    await participants.start()
    try:
        await activations.record_access(episode.id)
        await participants.record_episode(episode.id, ["agent-a"], ["worf"])
    finally:
        await activations.stop()
        await participants.stop()
    em = EpisodicMemory(db_path=str(tmp_path / "episodic.db"), relevance_threshold=0.0, eviction_disposition="archive")
    await em.start()
    try:
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
        assert _query(fts_path, "SELECT count(*) FROM episode_fts WHERE episode_id = ?", (episode.id,))[0][0] == 1
        assert _query(
            activation_path, "SELECT count(*) FROM episode_access_log WHERE episode_id = ?", (episode.id,),
        )[0][0] == 1
        assert _query(
            participants_path, "SELECT count(*) FROM episode_participants WHERE episode_id = ?", (episode.id,),
        )[0][0] == 2  # premise: every sidecar holds the episode, and nothing is wired to the memory

        wire_erasure_sidecar_paths(em, tmp_path)
        erased = await em.evict_by_ids([episode.id], reason="user_request", disposition=EvictionDisposition.ERASE)

        assert erased == 1
        assert _query(fts_path, "SELECT count(*) FROM episode_fts WHERE episode_id = ?", (episode.id,))[0][0] == 0
        assert _query(
            activation_path, "SELECT count(*) FROM episode_access_log WHERE episode_id = ?", (episode.id,),
        )[0][0] == 0
        assert _query(
            participants_path, "SELECT count(*) FROM episode_participants WHERE episode_id = ?", (episode.id,),
        )[0][0] == 0
    finally:
        await em.stop()


# --- R30 (AD-1340 R3: the production call, not the helper) ---------------------------------------------------


async def test_init_cognitive_services_declares_the_sidecar_files_to_erase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real init_cognitive_services() declares the sidecar files; deleting that call leaves them undeclared."""
    episode = _episode(0)
    activation_path = tmp_path / ACTIVATION_TRACKER_DB
    participants_path = tmp_path / PARTICIPANT_INDEX_DB
    fts_path = tmp_path / "episode_fts.db"
    activations = ActivationTracker(db_path=str(activation_path))
    participants = ParticipantIndex(db_path=str(participants_path))
    await activations.start()
    await participants.start()
    try:
        await activations.record_access(episode.id)
        await participants.record_episode(episode.id, ["agent-a"], ["worf"])
    finally:
        await activations.stop()
        await participants.stop()
    em = EpisodicMemory(db_path=str(tmp_path / "episodic.db"), relevance_threshold=0.0, eviction_disposition="archive")
    monkeypatch.setenv("PROBOS_SKIP_EPISODIC_MIGRATIONS", "1")
    config = SystemConfig()
    config.self_mod.enabled = False
    config.knowledge.enabled = False
    config.records.enabled = False
    config.orientation.enabled = False
    config.social_verification.enabled = False
    config.consultation.enabled = False
    config.expertise.enabled = False
    config.dreaming.activation_enabled = False  # neither sidecar is then wired by startup
    try:
        await init_cognitive_services(
            config=config,
            data_dir=tmp_path,
            registry=object(),
            pools={},
            llm_client=object(),
            trust_network=object(),
            hebbian_router=object(),
            episodic_memory=em,
            intent_bus=object(),
            working_memory=object(),
            event_log=object(),
            workflow_cache=object(),
            qa_reports={},
            submit_intent_with_consensus_fn=lambda *args, **kwargs: None,
            register_designed_agent_fn=lambda *args, **kwargs: None,
            unregister_designed_agent_fn=lambda *args, **kwargs: None,
            create_designed_pool_fn=lambda *args, **kwargs: None,
            set_probationary_trust_fn=lambda *args, **kwargs: None,
            add_skill_to_agents_fn=lambda *args, **kwargs: None,
            create_pool_fn=lambda *args, **kwargs: None,
        )
        assert em._activation_tracker is None and em._participant_index is None  # premise: nothing is wired
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
        assert _query(fts_path, "SELECT count(*) FROM episode_fts WHERE episode_id = ?", (episode.id,))[0][0] == 1
        assert _query(
            activation_path, "SELECT count(*) FROM episode_access_log WHERE episode_id = ?", (episode.id,),
        )[0][0] == 1
        assert _query(
            participants_path, "SELECT count(*) FROM episode_participants WHERE episode_id = ?", (episode.id,),
        )[0][0] == 2  # premise: the seeded rows are there

        erased = await em.evict_by_ids([episode.id], reason="user_request", disposition=EvictionDisposition.ERASE)

        assert erased == 1
        assert _query(fts_path, "SELECT count(*) FROM episode_fts WHERE episode_id = ?", (episode.id,))[0][0] == 0
        assert _query(
            activation_path, "SELECT count(*) FROM episode_access_log WHERE episode_id = ?", (episode.id,),
        )[0][0] == 0
        assert _query(
            participants_path, "SELECT count(*) FROM episode_participants WHERE episode_id = ?", (episode.id,),
        )[0][0] == 0
    finally:
        await em.stop()
