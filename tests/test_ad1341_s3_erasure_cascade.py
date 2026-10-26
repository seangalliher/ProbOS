"""AD-1341 S3 M3 (#1569): an AD-754 erasure erases nothing while a Ship's Archive entry cites its episodes.

A real ``EpisodicMemory`` (ChromaDB, FTS5 and every sidecar, from ``test_ad1340_s1_eviction``), the real
``ErasureManager``, the real ``ArchiveStore``, the real app's ``POST /api/security/forget`` (S2a's client) and the
Captain's real ``probos archive erase``. Entries citing episodes are written with ``promote_entry`` directly: no
production source cites an episode until S4, so the test is the producer.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import inspect
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.knowledge.archive_store import ArchiveStore, PromotionOutcome
from probos.knowledge.erasure import ArchiveCitationsBlockErasure, ErasureCascadeIncomplete, ErasureManager
from probos.runtime import ProbOSRuntime
from probos.storage.sqlite_factory import default_factory
from probos.types import EpisodeStoreOutcome
from tests.test_ad1340_s1_eviction import _episode, _memory, _raw
from tests.test_ad1340_s2a_lookup_route import _client, _post, _runtime
from tests.test_ad1341_s1_archive_store import _record, _rows, _store
from tests.test_ad1341_s1_reset_and_erase import _config, _erase
from tests.test_ad1341_s3_veto_store import _SRC, _naming

_FORGET = "/api/security/forget"
_CITED, _OTHER = "ep-000", "ep-001"
_RESOURCE = "/srv/reactor.log"
_TARGETS: dict[str, dict[str, str]] = {
    "episode": {"episode_id": _CITED},
    "agent": {"agent_id": "agent-a"},
    "resource": {"resource_path": _RESOURCE},
}
_MATCHED = {"episode": [_CITED], "agent": [_CITED, _OTHER], "resource": [_CITED]}  # of the two stored episodes


class _CitedMidway(ArchiveStore):
    """The real store; just after its first citation read, a promotion citing ``_CITED`` lands (D10, E8)."""

    landed = False

    async def entry_ids_citing(self, episode_ids: list[str] | tuple[str, ...]) -> tuple[int, ...]:
        found = await super().entry_ids_citing(episode_ids)
        if not self.landed:
            self.landed = True
            late = _record(source_ref="reports/convergence/midway.md", source_episode_ids=(_CITED,))
            assert await self.promote_entry(late) is PromotionOutcome.CREATED
        return found


def _midway(tmp_path: Path) -> _CitedMidway:
    return _CitedMidway(str(tmp_path / "archive.db"), connection_factory=default_factory)


def _episodes() -> list[Any]:
    """Two episodes of agent-a; only the first names the resource."""
    cited = dataclasses.replace(_episode(0), user_input=f"alpha section filed the coolant readings under {_RESOURCE}")
    return [cited, _episode(1)]


def _with_archive(memory: Any, archive: Any) -> ErasureManager:
    options = {"archive_store": archive}  # S3's keyword, passed as a mapping
    return ErasureManager(memory, None, None, **options)


async def _forget(manager: ErasureManager, target: str) -> Any:
    if target == "episode":
        return await manager.forget_episode(_CITED)
    if target == "agent":
        return await manager.forget_agent_memory("agent-a")
    return await manager.forget_resource(_RESOURCE)


async def _stored(em: Any) -> None:
    for episode in _episodes():
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
    assert _live(em) == [_CITED, _OTHER]  # premise: both are live


def _live(em: Any) -> list[str]:
    return sorted(_raw(em, [_CITED, _OTHER])["ids"])


async def _archive_with(tmp_path: Path, cited: tuple[str, ...]) -> tuple[ArchiveStore, int, int]:
    """An open archive: one entry citing ``cited``, and one the agent authored that cites nothing (D9)."""
    store = _store(tmp_path)
    await store.initialize()
    assert await store.promote_entry(_record(source_episode_ids=cited)) is PromotionOutcome.CREATED
    authored = _record(source_ref="reports/convergence/authored.md", author_did="agent-a", author_callsign="agent-a")
    assert await store.promote_entry(authored) is PromotionOutcome.CREATED
    citing, unrelated = (row[0] for row in _rows(tmp_path / "archive.db", "SELECT id FROM archive ORDER BY id"))
    return store, citing, unrelated


def _archive_counts(tmp_path: Path) -> tuple[int, int]:
    archive = tmp_path / "archive.db"
    return (
        _rows(archive, "SELECT COUNT(*) FROM archive")[0][0],
        _rows(archive, "SELECT COUNT(*) FROM archive_erasures")[0][0],
    )


# --- E1, E2: the refusal, and the Captain's way through it --------------------------------------------------------


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_an_erasure_whose_episodes_an_archive_entry_cites_erases_nothing(tmp_path: Path, target: str) -> None:
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        store, citing, _unrelated = await _archive_with(tmp_path, (_CITED,))
        try:
            with pytest.raises(ArchiveCitationsBlockErasure) as refused:
                await _forget(_with_archive(rig.em, store), target)

            assert refused.value.entry_ids == (citing,)
            assert _live(rig.em) == [_CITED, _OTHER]  # nothing was erased
        finally:
            await store.close()
    assert _archive_counts(tmp_path) == (2, 0)


@pytest.mark.parametrize("target", ["episode", "agent"])
async def test_the_captain_erases_the_citing_entry_then_the_forget_route_erases_the_episodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str,
) -> None:
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        store, citing, unrelated = await _archive_with(tmp_path, (_CITED,))
        try:
            runtime = _runtime(root, rig.em)
            runtime.archive_store = store  # the runtime's public accessor (7.10)
            async with _client(runtime) as client:
                refused = await _post(client, _FORGET, _TARGETS[target])

                assert refused.status_code == 409, refused.text
                assert refused.json()["error"] == "archive_entries_cite_erased_episodes"
                assert refused.json()["archive_entry_ids"] == [citing]
                assert _live(rig.em) == [_CITED, _OTHER]

                # The Captain's erasure, as the CLI runs it: its own event loop, so in a thread.
                assert await asyncio.to_thread(_erase, monkeypatch, _config(tmp_path), citing, "the Captain forgets it") == 0

                erased = await _post(client, _FORGET, _TARGETS[target])

                assert erased.status_code == 200, erased.text
                assert sorted(erased.json()["deleted_episode_ids"]) == _MATCHED[target]
                assert _live(rig.em) == sorted({_CITED, _OTHER} - set(_MATCHED[target]))
                assert await store.entry_ids_citing([_CITED]) == ()
        finally:
            await store.close()
    archive = tmp_path / "archive.db"
    assert _rows(archive, "SELECT id FROM archive") == [(unrelated,)]
    assert _rows(archive, "SELECT entry_id, reason FROM archive_erasures") == [(citing, "the Captain forgets it")]


# --- E3 to E5: what does not block, and what fails closed ----------------------------------------------------------


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_an_erasure_no_archive_entry_cites_erases_as_before(tmp_path: Path, target: str) -> None:
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        store, _citing, _unrelated = await _archive_with(tmp_path, ("ep-elsewhere",))
        try:
            result = await _forget(_with_archive(rig.em, store), target)

            assert sorted(result.deleted_episode_ids) == _MATCHED[target]
            assert _live(rig.em) == sorted({_CITED, _OTHER} - set(_MATCHED[target]))
        finally:
            await store.close()
    assert _archive_counts(tmp_path) == (2, 0)


@pytest.mark.parametrize("accessor", ["mock", "none"])
async def test_the_forget_route_consults_only_a_real_archive_store(tmp_path: Path, accessor: str) -> None:
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        await _stored(rig.em)
        runtime = _runtime(root, rig.em)
        if accessor == "none":
            runtime.archive_store = None
        assert accessor == "none" or isinstance(runtime.archive_store, MagicMock)  # premise: the double's attribute
        async with _client(runtime) as client:
            erased = await _post(client, _FORGET, {"episode_id": _CITED})

        assert erased.status_code == 200, erased.text
        assert erased.json()["deleted_episode_ids"] == [_CITED]


@pytest.mark.parametrize("fault", ["closed", "corrupt-row"])
async def test_an_archive_that_cannot_answer_stops_the_erasure_before_anything_is_erased(
    tmp_path: Path, fault: str,
) -> None:
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        store, _citing, _unrelated = await _archive_with(tmp_path, ("ep-elsewhere",))
        if fault == "closed":
            await store.close()
        else:
            connection = sqlite3.connect(str(tmp_path / "archive.db"))
            try:
                connection.execute(
                    "INSERT INTO archive (timeline_id, category, title, content, archived_at, source_kind, "
                    "source_ref, source_episode_ids) VALUES ('t', 'c', 't', 'c', 0, 'convergence_report', 'r', '{x')"
                )
                connection.commit()
            finally:
                connection.close()
        try:
            with pytest.raises((RuntimeError, ValueError)):
                await _with_archive(rig.em, store).forget_episode(_CITED)

            assert _live(rig.em) == [_CITED, _OTHER]
        finally:
            await store.close()


# --- E6 to E8: authority, the accessor, and a citation that lands mid-run -----------------------------------------


def test_only_the_erasure_manager_reads_citations_and_only_the_forget_route_builds_it() -> None:
    builders: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ErasureManager":
                builders.add(path.relative_to(_SRC).as_posix())
    assert builders == {"routers/security.py"}
    assert _naming("entry_ids_citing") == {"knowledge/erasure.py"}
    assert _naming("erase_entry") == {"__main__.py"}  # S1's rule holds: the AD-754 route never erases an entry


def test_the_runtime_exposes_its_archive_store_read_only() -> None:
    accessor = inspect.getattr_static(ProbOSRuntime, "archive_store")
    assert isinstance(accessor, property) and accessor.fset is None
    runtime = object.__new__(ProbOSRuntime)  # no boot: only the accessor is under test
    sentinel = object()
    runtime._archive_store = sentinel
    assert runtime.archive_store is sentinel


async def test_a_citation_that_appears_after_the_scan_still_stops_that_episode(tmp_path: Path) -> None:
    async with _memory(tmp_path / "vessel", "archive") as rig:
        await _stored(rig.em)
        store = _midway(tmp_path)
        await store.initialize()
        try:
            with pytest.raises(ErasureCascadeIncomplete) as incomplete:
                await _with_archive(rig.em, store).forget_agent_memory("agent-a")

            assert set(incomplete.value.failures) == {_CITED}
            assert type(incomplete.value.failures[_CITED]) is ArchiveCitationsBlockErasure
            assert incomplete.value.result.deleted_episode_ids == [_OTHER]
            assert _live(rig.em) == [_CITED]
        finally:
            await store.close()
