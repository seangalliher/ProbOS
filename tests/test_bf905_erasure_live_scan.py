"""BF-905 (#1587): the erasure cascades' live scan fails closed.

``forget_agent_memory`` and ``forget_resource`` read the live store through ``EpisodicMemory.iter_live_episodes``, in a
scan of their own, separate from the archive scan. An unreadable live store, a failed ChromaDB read or a live row that
does not rebuild ends in ``ErasureCascadeIncomplete`` after every match found has been erased.

These tests use a real ``EpisodicMemory`` (real ChromaDB, FTS5, ``ActivationTracker``, ``ParticipantIndex``,
``EvictionAuditLog``) on ``tmp_path``, built by S1's rig. A failed ChromaDB read is injected by a forwarding proxy on
the real collection (S1's ``_CollectionProxy`` pattern). An unrehydratable row is a real row whose stored metadata no
longer rebuilds. Nothing mocks the erasure manager, the memory or the route. Every test asserts its premise first.
``asyncio_mode = "auto"`` (``pyproject.toml:181``), so no asyncio marks are needed.

R1 to R4 test the reader; T1 to T8 test the cascades and the route (T5 is the seam: the route, the manager, the real
store). "L" and "A" are the controls (agent-a, live and archived); "B1" and "B2" are the target (agent-b, live and
archived): ``ctl_live``, ``ctl_archived``, ``tgt_live`` and ``tgt_archived`` below.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from probos.api import create_app
from probos.cognitive.episode_archive import ARCHIVE_FILENAME, EpisodeErasureIncomplete
from probos.cognitive.episodic import EpisodicMemory
from probos.knowledge.erasure import ErasureCascadeIncomplete, ErasureManager, ErasureResult
from probos.types import Episode, EpisodeStoreOutcome
from tests.test_ad1340_s1_erasure import _ARCHIVED_TRACES, _GONE, _LIVE_TRACES, _manager, _seed, _traces
from tests.test_ad1340_s1_eviction import _episode, _ids, _memory, _raw, _record_collection
from tests.test_ad1340_s2a_lookup_route import _runtime

# --- helpers -------------------------------------------------------------------------------------------------


class _ScanReadFault:
    """Forwards to the real collection; the first ``get`` called without ``ids`` (the live scan's id read) raises once."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.fired = False

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self.inner, name)
        if name != "get":
            return attribute

        def _get(*args: Any, **kwargs: Any) -> Any:
            if not self.fired and "ids" not in kwargs:
                self.fired = True
                raise RuntimeError("injected: the live scan read failed")
            return attribute(*args, **kwargs)

        return _get


def _fail_the_next_scan_read(em: EpisodicMemory) -> _ScanReadFault:
    """Interpose the fault on the live collection (test-only private access, as S1's ``_record_collection``)."""
    fault = _ScanReadFault(em._collection)
    em._collection = fault
    return fault


def _scene() -> tuple[Episode, Episode, Episode, Episode]:
    """L live and A archived (agent-a, the controls); B1 live and B2 archived (agent-b, the target)."""
    return (
        _episode(0),
        _episode(1),
        dataclasses.replace(_episode(2), agent_ids=["agent-b"]),
        dataclasses.replace(_episode(3), agent_ids=["agent-b"]),
    )


def _errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "probos.knowledge.erasure" and r.levelno == logging.ERROR]


@contextlib.asynccontextmanager
async def _route_client(em: EpisodicMemory, root: Path) -> AsyncIterator[httpx.AsyncClient]:
    """S2a's ``_client`` plus ``raise_app_exceptions=False``: an unhandled app error is the 500 a real client receives."""
    app = create_app(_runtime(root, em))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class _ListOnlyMemory:
    """A wired memory that has only the retired best-effort read: ``list_episodes``, no ``iter_live_episodes``, no archive."""

    def __init__(self) -> None:
        self.evicted: list[str] = []

    async def list_episodes(self, *, limit: int | None = None) -> list[Episode]:
        return [dataclasses.replace(_episode(5), id="ep-listed", agent_ids=["agent-b"])]

    async def get_by_ids(self, episode_ids: Sequence[str]) -> list[Episode]:
        return []

    async def evict_by_ids(self, episode_ids: Sequence[str], **kwargs: Any) -> int:
        self.evicted.extend(episode_ids)
        return len(episode_ids)


# --- R1 - R4: the reader ---------------------------------------------------------------------------------------


async def test_the_live_read_refuses_a_memory_that_was_never_started(tmp_path: Path) -> None:
    em = EpisodicMemory(db_path=tmp_path / "chroma" / "episodes.db", max_episodes=100, relevance_threshold=0.0)
    assert await em.list_episodes() == []  # premise: the old read reports an empty store

    with pytest.raises(EpisodeErasureIncomplete, match=r"^erasure_live_store_unavailable$"):
        async for _ in em.iter_live_episodes():
            pass


async def test_the_live_read_pages_by_id_and_yields_every_row_once(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        for i in range(5):
            assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        assert len(_raw(em, _ids(5))["ids"]) == 5  # premise: five live rows

        proxy = _record_collection(em)
        seen = [episode.id async for episode in em.iter_live_episodes(page_size=2)]

        assert sorted(seen) == _ids(5)
        assert len(seen) == 5
        assert proxy.calls.count(("get", [])) == 1  # the ids are read once ...
        assert proxy.calls.count(("get", ["metadatas", "documents"])) == 3  # ... then the rows by id: 2 + 2 + 1


async def test_the_live_read_refuses_a_page_size_below_one(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        assert _raw(em, _ids(1))["ids"] == _ids(1)  # premise: a live row exists, so only the page size can refuse

        with pytest.raises(ValueError, match=r"^erasure_live_page_size_invalid$"):
            async for _ in em.iter_live_episodes(page_size=0):
                pass


async def test_a_failed_live_read_propagates_unwrapped(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        assert _raw(em, _ids(1))["ids"] == _ids(1)  # premise: a live row exists, so an empty result would be a lie
        fault = _fail_the_next_scan_read(em)

        with pytest.raises(RuntimeError, match=r"^injected: the live scan read failed$"):
            async for _ in em.iter_live_episodes():
                pass

        assert fault.fired


# --- T1 - T8: the cascades and the route -----------------------------------------------------------------------


async def test_a_failed_live_read_still_erases_the_archived_matches_then_raises(tmp_path: Path) -> None:
    ctl_live, ctl_archived, tgt_live, tgt_archived = _scene()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        await _seed(rig, [ctl_live, ctl_archived, tgt_live, tgt_archived], archive=[ctl_archived.id, tgt_archived.id])
        live_ids = [episode.id async for episode in em.iter_live_episodes()]
        assert sorted(live_ids) == sorted([ctl_live.id, tgt_live.id])  # premise: the live read sees both live rows
        fault = _fail_the_next_scan_read(em)

        with pytest.raises(ErasureCascadeIncomplete) as info:
            await manager.forget_agent_memory("agent-b")

        assert fault.fired
        assert str(info.value.enumeration_error) == "injected: the live scan read failed"
        assert info.value.failures == {}
        assert info.value.result.deleted_episode_ids == [tgt_archived.id]  # the archive scan still ran, and was erased
        assert await _traces(em, rig.root, tgt_archived.id, agent="agent-b") == _GONE
        assert await _traces(em, rig.root, tgt_live.id, agent="agent-b") == _LIVE_TRACES  # the report is true
        assert await _traces(em, rig.root, ctl_live.id) == _LIVE_TRACES
        assert await _traces(em, rig.root, ctl_archived.id) == _ARCHIVED_TRACES

        retried = await manager.forget_agent_memory("agent-b")  # the fault is spent: the retry reaches the live match

        assert retried.deleted_episode_ids == [tgt_live.id]
        assert await _traces(em, rig.root, tgt_live.id, agent="agent-b") == _GONE


async def test_a_live_row_that_cannot_rehydrate_is_reported_and_the_rest_erased(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    ctl_live, _ctl_archived, tgt_live, tgt_archived = _scene()
    unreadable = dataclasses.replace(_episode(4), agent_ids=["agent-b"])
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        await _seed(rig, [ctl_live, tgt_live, unreadable, tgt_archived], archive=[tgt_archived.id])
        meta = _raw(em, [unreadable.id])["metadatas"][0]
        # Schema drift: an anchors_json whose key the frozen AnchorFrame no longer has, so rebuilding the row raises.
        em._collection.update(
            ids=[unreadable.id], metadatas=[{**meta, "anchors_json": json.dumps({"retired_field": "drift"})}],
        )
        assert _raw(em, [unreadable.id])["ids"] == [unreadable.id]  # premise: the row is still live ...
        assert unreadable.id not in {e.id for e in await em.list_episodes()}  # ... and the old read dropped it silently
        caplog.set_level(logging.WARNING)

        with pytest.raises(ErasureCascadeIncomplete) as info:
            await manager.forget_agent_memory("agent-b")

        error = info.value.enumeration_error
        assert isinstance(error, EpisodeErasureIncomplete)
        assert str(error) == "erasure_live_rows_unrehydratable:1"
        assert info.value.failures == {}
        assert sorted(info.value.result.deleted_episode_ids) == sorted([tgt_live.id, tgt_archived.id])
        assert await _traces(em, rig.root, tgt_live.id, agent="agent-b") == _GONE
        assert await _traces(em, rig.root, tgt_archived.id, agent="agent-b") == _GONE
        assert await _traces(em, rig.root, unreadable.id, agent="agent-b") == _LIVE_TRACES  # reported, not erased
        warnings = [
            r for r in caplog.records
            if r.name == "probos.cognitive.episodic" and r.levelno == logging.WARNING and unreadable.id in r.getMessage()
        ]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "TypeError" in message  # the exception type name, nothing else of the failure
        assert warnings[0].exc_info is None  # no traceback: it can echo a metadata value
        assert unreadable.user_input not in message


async def test_a_cascade_on_a_stopped_memory_raises(tmp_path: Path) -> None:
    ctl_live, ctl_archived, _tgt_live, _tgt_archived = _scene()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        await _seed(rig, [ctl_live, ctl_archived], archive=[ctl_archived.id])
        await em.stop()
        assert await em.list_episodes() == []  # premise: the old read reports an empty store ...
        assert em.archive_available is False  # ... on a memory that holds a live and an archived episode of agent-a

        with pytest.raises(ErasureCascadeIncomplete) as info:
            await manager.forget_agent_memory("agent-a")

        error = info.value.enumeration_error
        assert isinstance(error, EpisodeErasureIncomplete)
        assert str(error) == "erasure_live_store_unavailable"
        assert info.value.failures == {}
        assert info.value.result.deleted_episode_ids == []
        with pytest.raises(EpisodeErasureIncomplete, match="erasure_live_store_unavailable"):
            await manager.forget_episode(ctl_live.id)  # by id, as the cascade: the two entry points now agree


async def test_a_healthy_cascade_is_unchanged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    ctl_live, ctl_archived, tgt_live, tgt_archived = _scene()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        await _seed(rig, [ctl_live, ctl_archived, tgt_live, tgt_archived], archive=[ctl_archived.id, tgt_archived.id])
        caplog.set_level(logging.WARNING)

        result = await manager.forget_agent_memory("agent-b")

        assert sorted(result.deleted_episode_ids) == sorted([tgt_live.id, tgt_archived.id])
        assert await _traces(em, rig.root, tgt_live.id, agent="agent-b") == _GONE
        assert await _traces(em, rig.root, tgt_archived.id, agent="agent-b") == _GONE
        assert await _traces(em, rig.root, ctl_live.id) == _LIVE_TRACES
        assert await _traces(em, rig.root, ctl_archived.id) == _ARCHIVED_TRACES
        assert [r.getMessage() for r in caplog.records if "BF-905" in r.getMessage()] == []


async def test_the_forget_route_answers_500_when_the_live_scan_fails(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    ctl_live, ctl_archived, tgt_live, tgt_archived = _scene()
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        await _seed(rig, [ctl_live, ctl_archived, tgt_live, tgt_archived], archive=[ctl_archived.id, tgt_archived.id])
        caplog.set_level(logging.ERROR)

        async with _route_client(em, tmp_path) as client:
            fault = _fail_the_next_scan_read(em)

            failed = await client.post("/api/security/forget", json={"agent_id": "agent-b"})

            assert fault.fired
            assert failed.status_code == 500
            assert "deleted_episode_ids" not in failed.text
            assert await _traces(em, rig.root, tgt_archived.id, agent="agent-b") == _GONE
            assert await _traces(em, rig.root, tgt_live.id, agent="agent-b") == _LIVE_TRACES
            assert await _traces(em, rig.root, ctl_live.id) == _LIVE_TRACES
            assert await _traces(em, rig.root, ctl_archived.id) == _ARCHIVED_TRACES
            assert len([m for m in _errors(caplog) if "the live erasure scan failed" in m]) == 1

            retried = await client.post("/api/security/forget", json={"agent_id": "agent-b"})

            assert retried.status_code == 200
            assert retried.json()["deleted_episode_ids"] == [tgt_live.id]
            assert await _traces(em, rig.root, tgt_live.id, agent="agent-b") == _GONE


async def test_a_memory_without_the_live_read_fails_closed() -> None:
    memory = _ListOnlyMemory()
    assert [e.id for e in await memory.list_episodes()] == ["ep-listed"]  # premise: the retired read WOULD find it

    with pytest.raises(ErasureCascadeIncomplete) as info:
        await ErasureManager(memory, None, None).forget_agent_memory("agent-b")

    error = info.value.enumeration_error
    assert isinstance(error, AttributeError)
    assert "iter_live_episodes" in str(error)
    assert info.value.result.deleted_episode_ids == []
    assert memory.evicted == []  # there is no fallback to list_episodes


async def test_no_memory_wired_keeps_the_empty_result() -> None:
    manager = ErasureManager(episodic_memory=None, attachment_store=None, audit_log=None)

    by_agent = await manager.forget_agent_memory("agent-b")
    by_resource = await manager.forget_resource("/x")

    for result in (by_agent, by_resource):
        assert isinstance(result, ErasureResult)
        assert result.count == 0
        assert result.deleted_episode_ids == []


async def test_when_both_scans_fail_the_live_error_is_raised_and_both_are_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    _ctl_live, _ctl_archived, tgt_live, _tgt_archived = _scene()
    blocker = tmp_path / "chroma" / ARCHIVE_FILENAME
    blocker.mkdir(parents=True)
    assert blocker.is_dir()  # premise: a directory stands where the archive file would be created (S1 R13)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        manager, _ = _manager(em)
        assert em.archive_available is False
        assert await em.store(tgt_live) is EpisodeStoreOutcome.STORED
        assert _raw(em, [tgt_live.id])["ids"] == [tgt_live.id]  # premise: a live match exists
        caplog.set_level(logging.ERROR)
        fault = _fail_the_next_scan_read(em)

        with pytest.raises(ErasureCascadeIncomplete) as info:
            await manager.forget_agent_memory("agent-b")

        assert fault.fired
        assert str(info.value.enumeration_error) == "injected: the live scan read failed"
        assert info.value.failures == {}
        assert info.value.result.deleted_episode_ids == []
        messages = _errors(caplog)
        live_at = [i for i, m in enumerate(messages) if "the live erasure scan failed" in m]
        archive_at = [i for i, m in enumerate(messages) if "the archive erasure scan failed" in m]
        assert live_at and archive_at
        assert live_at[0] < archive_at[0]  # both are logged, the live scan's first
        assert _raw(em, [tgt_live.id])["ids"] == [tgt_live.id]  # nothing was erased: the report is true
