"""AD-1340 S1 (M3): erasure removes every copy of an episode -- the live row, the sidecar rows and the archive rows.

A real ``EpisodicMemory`` (real ChromaDB, FTS5 sidecar, ``ActivationTracker``, ``ParticipantIndex``,
``EvictionAuditLog`` and episode archive) on ``tmp_path``, driven through the real ``ErasureManager``. The helpers of
``test_ad1340_s1_eviction.py`` are the independent witnesses: raw ``sqlite3`` for the archive, the audit and the
sidecars, and a direct ChromaDB read for the live store. Every test states its premise first, so "gone" can never mean
"was never there". ``delete`` is the default until M4, so archive-mode tests pass ``"archive"`` explicitly.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.episode_archive import (
    ARCHIVE_FILENAME,
    ARCHIVE_REASONS,
    EpisodeArchive,
    EpisodeArchiveUnavailable,
    EpisodeErasureIncomplete,
    decode_payload,
)
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.memory_probes import _cleanup_test_episodes
from probos.cognitive.participant_index import ParticipantIndex
from probos.knowledge.erasure import ErasureManager
from probos.types import Episode, EpisodeStoreOutcome, EvictionDisposition
from tests.test_ad1340_s1_eviction import (
    _archive_rows,
    _audit_rows,
    _episode,
    _ids,
    _memory,
    _query,
    _raw,
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

        with pytest.raises(EpisodeArchiveUnavailable, match="episode_archive_unavailable_for_erase"):
            await manager.forget_resource("x")  # the cascade cannot read the archive either


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
