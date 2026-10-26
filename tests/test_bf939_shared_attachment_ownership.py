"""BF-939 (#1683): an AD-754 erasure keeps a content-addressed attachment another episode still names.

A real ``EpisodicMemory`` (``test_ad1340_s1_eviction``'s rig, archive mode), a real ``FilesystemAttachmentStore``, the
real ``ErasureManager``, the real ``ArchiveStore`` and the Captain's real ``probos archive erase``. Modelled on the
AD-1341 S3 M3 reviewer's probes. ``asyncio_mode = "auto"``, so no asyncio marks. Every test states its premise first.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.episode_archive import EpisodeErasureIncomplete
from probos.cognitive.participant_index import ParticipantIndex
from probos.knowledge.archive_store import ArchiveStore, PromotionOutcome
from probos.knowledge.erasure import ArchiveCitationsBlockErasure, ErasureCascadeIncomplete, ErasureManager
from probos.storage.sqlite_factory import default_factory
from probos.types import Episode, EpisodeStoreOutcome
from tests.test_ad1340_s1_eviction import _episode, _memory, _raw
from tests.test_ad1341_s1_archive_store import _record
from tests.test_ad1341_s1_reset_and_erase import _config, _erase
from tests.test_ad1341_s3_erasure_cascade import _midway

_BODY = b"bf939: one photograph, two episodes"
_SHA = hashlib.sha256(_BODY).hexdigest()
_RESOURCE = "/srv/bf939/coolant.log"
_A, _B, _C = "ep-000", "ep-001", "ep-002"  # _midway lands a citation of ep-000


def _naming(i: int, *, agent: str = "agent-a", resource: bool = False, attachment: bool = True) -> Episode:
    """``_episode(i)`` for ``agent``; it names the shared attachment unless ``attachment`` is False."""
    episode = _episode(i)
    outcome: dict[str, Any] = {"intent": "report", "success": True}
    if attachment:
        outcome["attachment_refs"] = [_SHA]
    text = f"{episode.user_input} under {_RESOURCE}" if resource else episode.user_input
    return dataclasses.replace(episode, agent_ids=[agent], user_input=text, outcomes=[outcome])


async def _stored(em: Any, episodes: list[Episode], *, archived: tuple[str, ...] | list[str] = ()) -> None:
    for episode in episodes:
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
    for episode_id in archived:
        assert await em.evict_by_ids([episode_id], reason="activation_decay") == 1
    live = sorted({episode.id for episode in episodes} - set(archived))
    assert sorted(_raw(em, [episode.id for episode in episodes])["ids"]) == live  # premise: live and archived as asked


def _cannot_rebuild(em: Any, episode_id: str) -> None:
    """BF-905's schema drift: the row stays live, and rebuilding it raises (test-only private access)."""
    meta = _raw(em, [episode_id])["metadatas"][0]
    em._collection.update(ids=[episode_id], metadatas=[{**meta, "anchors_json": json.dumps({"retired_field": "drift"})}])


@contextlib.asynccontextmanager
async def _vessel(tmp_path: Path) -> AsyncIterator[tuple[Any, FilesystemAttachmentStore]]:
    async with _memory(tmp_path / "vessel", "archive") as rig:
        attachments = FilesystemAttachmentStore(tmp_path / "attachments")
        try:
            await attachments.write(_SHA, _BODY, "text/plain")
            assert await attachments.exists(_SHA)  # premise: the one shared file
            yield rig, attachments
        finally:
            attachments.close()


def _manager(rig: Any, attachments: FilesystemAttachmentStore, archive: ArchiveStore | None = None) -> ErasureManager:
    return ErasureManager(rig.em, attachments, None, archive_store=archive)


async def _forget(manager: ErasureManager, target: str) -> Any:
    if target == "episode":
        return await manager.forget_episode(_A)
    if target == "agent":
        return await manager.forget_agent_memory("agent-a")
    return await manager.forget_resource(_RESOURCE)


class _CountedArchive(ArchiveStore):
    """The real store, counting its citation reads (S3's D10 check)."""

    def __init__(self, path: Path) -> None:
        super().__init__(str(path), connection_factory=default_factory)
        self.citation_reads = 0

    async def entry_ids_citing(self, episode_ids: list[str] | tuple[str, ...]) -> tuple[int, ...]:
        self.citation_reads += 1
        return await super().entry_ids_citing(episode_ids)


def _count_scans(monkeypatch: pytest.MonkeyPatch, em: Any) -> dict[str, int]:
    calls = {"live": 0, "archive": 0}
    for name, key in (("iter_live_episodes", "live"), ("iter_archived_episodes", "archive")):
        inner = getattr(em, name)

        def counted(*args: Any, _inner: Any = inner, _key: str = key, **kwargs: Any) -> Any:
            calls[_key] += 1
            return _inner(*args, **kwargs)

        monkeypatch.setattr(em, name, counted)
    return calls


# --- T1 to T5: who keeps a shared attachment ---------------------------------------------------------------------


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_erasing_one_of_two_episodes_that_share_an_attachment_keeps_it(tmp_path: Path, target: str) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0, resource=True), _naming(1, agent="agent-b")])

        result = await _forget(_manager(rig, attachments), target)

        assert result.deleted_episode_ids == [_A]
        assert result.deleted_attachment_ids == []
        assert result.retained_attachments == {_SHA: [_B]}
        assert result.count == 1
        assert sorted(_raw(rig.em, [_A, _B])["ids"]) == [_B]
        assert await attachments.exists(_SHA)


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_an_archived_episode_that_names_the_attachment_keeps_it(tmp_path: Path, target: str) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0, resource=True), _naming(1, agent="agent-b")], archived=[_B])

        result = await _forget(_manager(rig, attachments), target)

        assert result.deleted_episode_ids == [_A]
        assert result.deleted_attachment_ids == []
        assert result.retained_attachments == {_SHA: [_B]}
        assert await attachments.exists(_SHA)


async def test_an_episodes_own_archived_version_does_not_keep_its_attachment(tmp_path: Path) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        first = _naming(0)
        await _stored(rig.em, [first], archived=[_A])
        assert await rig.em.store(dataclasses.replace(first, user_input=f"{first.user_input}, rewritten")) is (
            EpisodeStoreOutcome.STORED
        )
        assert _raw(rig.em, [_A])["ids"] == [_A]  # premise: one live and one archived version under one id

        result = await _manager(rig, attachments).forget_episode(_A)

        assert result.deleted_attachment_ids == [_SHA]
        assert result.retained_attachments == {}
        assert not await attachments.exists(_SHA)


@pytest.mark.parametrize("target", ["agent", "resource"])
async def test_erasing_every_episode_that_names_the_attachment_removes_it(tmp_path: Path, target: str) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0, resource=True), _naming(1, resource=True)], archived=[_B])

        result = await _forget(_manager(rig, attachments), target)

        assert sorted(result.deleted_episode_ids) == [_A, _B]
        assert result.deleted_attachment_ids == [_SHA]
        assert result.retained_attachments == {}
        assert result.count == 3  # two episodes and one attachment, unlinked once
        assert not await attachments.exists(_SHA)


async def test_two_owners_erased_one_after_the_other_remove_it_with_the_second(tmp_path: Path) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0), _naming(1, agent="agent-b")])
        manager = _manager(rig, attachments)

        first = await manager.forget_episode(_A)

        assert first.retained_attachments == {_SHA: [_B]}
        assert await attachments.exists(_SHA)

        second = await manager.forget_episode(_B)

        assert second.deleted_attachment_ids == [_SHA]
        assert second.retained_attachments == {}
        assert not await attachments.exists(_SHA)


# --- T6, T7: a match left whole, and a match whose erase began -----------------------------------------------------


@pytest.mark.parametrize("refused", ["first", "last"])
async def test_a_match_the_archive_refuses_keeps_the_attachment_it_shares(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: str,
) -> None:
    store = _midway(tmp_path)  # a promotion citing ep-000 lands just after the cascade's first citation read (S3 E8)
    await store.initialize()
    try:
        async with _vessel(tmp_path) as (rig, attachments):
            # The cascade erases live matches first, then archived ones: this sets the refused match's turn.
            await _stored(rig.em, [_naming(0), _naming(1)], archived=[_B] if refused == "first" else [_A])
            manager = _manager(rig, attachments, store)

            with pytest.raises(ErasureCascadeIncomplete) as incomplete:
                await manager.forget_agent_memory("agent-a")

            assert set(incomplete.value.failures) == {_A}
            assert type(incomplete.value.failures[_A]) is ArchiveCitationsBlockErasure
            assert incomplete.value.result.deleted_episode_ids == [_B]
            assert await attachments.exists(_SHA)  # the refused match still names it
            # first: decided at ep-001's turn and kept for ep-000; last: ep-000 decides it, and was refused first
            assert incomplete.value.result.retained_attachments == ({_SHA: [_A]} if refused == "first" else {})

            (citing,) = await store.entry_ids_citing([_A])
            assert await asyncio.to_thread(_erase, monkeypatch, _config(tmp_path), citing, "the Captain forgets it") == 0
            retried = await manager.forget_agent_memory("agent-a")

            assert retried.deleted_episode_ids == [_A]
            assert retried.deleted_attachment_ids == [_SHA]
            assert not await attachments.exists(_SHA)
    finally:
        await store.close()


async def test_a_match_whose_erase_fails_partway_still_lets_the_shared_attachment_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete_episodes = ParticipantIndex.delete_episodes

    async def _fail_for_the_first(self: ParticipantIndex, episode_ids: list[str]) -> None:
        if _A in episode_ids:
            raise RuntimeError("injected: the participant index cannot delete ep-000")
        await delete_episodes(self, episode_ids)

    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0), _naming(1)], archived=[_B])  # erased in turn: ep-000 (live), then ep-001
        monkeypatch.setattr(ParticipantIndex, "delete_episodes", _fail_for_the_first)

        with pytest.raises(ErasureCascadeIncomplete) as incomplete:
            await _manager(rig, attachments).forget_agent_memory("agent-a")

        assert set(incomplete.value.failures) == {_A}
        assert isinstance(incomplete.value.failures[_A], EpisodeErasureIncomplete)
        assert incomplete.value.result.deleted_episode_ids == [_B]
        assert _raw(rig.em, [_A])["ids"] == []  # ep-000's record went before its sweep failed ...
        assert await rig.em.get_archived_metadata_versions(_A) == []  # ... and no archived copy of it names the file
        assert incomplete.value.result.deleted_attachment_ids == [_SHA]  # so the file went too: none is stranded
        assert not await attachments.exists(_SHA)


# --- T8 to T10: an owner scan that fails (A-2, D5) ------------------------------------------------------------------


async def test_an_episode_whose_own_row_cannot_be_rebuilt_is_still_erased_with_its_attachment(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0)])
        _cannot_rebuild(rig.em, _A)
        assert await rig.em.get_by_ids([_A]) == []  # premise: no read rebuilds it ...
        assert _SHA in (await rig.em.get_episode_metadata(_A))["outcomes_json"]  # ... and its raw row names the file
        caplog.set_level(logging.WARNING, logger="probos.knowledge.erasure")
        manager = _manager(rig, attachments)

        with pytest.raises(ErasureCascadeIncomplete) as incomplete:
            await manager.forget_episode(_A)

        error = incomplete.value
        assert error.failures == {}
        assert str(error.enumeration_error) == "erasure_live_rows_unrehydratable:1"
        assert error.result.deleted_episode_ids == [_A]
        assert error.result.deleted_attachment_ids == [_SHA]
        assert _raw(rig.em, [_A])["ids"] == []
        assert not await attachments.exists(_SHA)
        assert any("BF-939" in record.getMessage() for record in caplog.records)

        retried = await manager.forget_episode(_A)  # nothing is left to find, so the retry is clean

        assert retried.deleted_episode_ids == []
        assert retried.deleted_attachment_ids == []


@pytest.mark.parametrize("target", ["episode", "agent"])
async def test_an_owner_the_failed_scan_reached_still_keeps_the_attachment(tmp_path: Path, target: str) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0), _naming(1, agent="agent-b"), _naming(2, agent="agent-c", attachment=False)])
        _cannot_rebuild(rig.em, _C)  # an unrelated row: the live scan raises after yielding the other two

        with pytest.raises(ErasureCascadeIncomplete) as incomplete:
            await _forget(_manager(rig, attachments), target)

        assert str(incomplete.value.enumeration_error) == "erasure_live_rows_unrehydratable:1"
        assert incomplete.value.result.deleted_episode_ids == [_A]
        assert incomplete.value.result.retained_attachments == {_SHA: [_B]}
        assert await attachments.exists(_SHA)


@pytest.mark.parametrize("target", ["episode", "agent"])
async def test_an_owner_the_failed_scan_could_not_read_does_not_keep_the_attachment(tmp_path: Path, target: str) -> None:
    """D5's disclosed bound: under-erasing is the worse failure (BF-868), so a row no scan can read is no owner."""
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0), _naming(1, agent="agent-b")])
        _cannot_rebuild(rig.em, _B)

        with pytest.raises(ErasureCascadeIncomplete) as incomplete:
            await _forget(_manager(rig, attachments), target)

        assert incomplete.value.result.deleted_episode_ids == [_A]
        assert incomplete.value.result.deleted_attachment_ids == [_SHA]
        assert not await attachments.exists(_SHA)
        assert _raw(rig.em, [_B])["ids"] == [_B]  # the unreadable row is reported by the scan, not erased


# --- T11: one owner scan per entry point; S3's per-episode check unchanged (A-3) ------------------------------------


@pytest.mark.parametrize(
    ("case", "expected"),
    [  # A-4 (A4): explicit ids, so the node ids are the labels §6 and §10 use
        pytest.param("agent", {"live": 1, "archive": 1, "citation_reads": 4}, id="agent"),  # the scan's read, then one per match (S3 D10)
        pytest.param("episode-with-attachment", {"live": 1, "archive": 1, "citation_reads": 1}, id="episode-with-attachment"),
        pytest.param("episode-without-attachment", {"live": 0, "archive": 0, "citation_reads": 1}, id="episode-without-attachment"),
        pytest.param("refused", {"live": 0, "archive": 0, "citation_reads": 1}, id="refused"),
    ],
)
async def test_each_entry_point_scans_for_owners_at_most_once_and_keeps_the_per_episode_citation_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, expected: dict[str, int],
) -> None:
    store = _CountedArchive(tmp_path / "archive.db")
    await store.initialize()
    try:
        cited = (_A,) if case == "refused" else ("ep-elsewhere",)
        assert await store.promote_entry(_record(source_episode_ids=cited)) is PromotionOutcome.CREATED
        store.citation_reads = 0
        async with _vessel(tmp_path) as (rig, attachments):
            await _stored(rig.em, [_naming(0), _naming(1), _naming(2, attachment=False)])
            calls = _count_scans(monkeypatch, rig.em)
            manager = _manager(rig, attachments, store)

            if case == "agent":
                result = await manager.forget_agent_memory("agent-a")
                assert sorted(result.deleted_episode_ids) == [_A, _B, _C]
            elif case == "refused":
                with pytest.raises(ArchiveCitationsBlockErasure):
                    await manager.forget_episode(_A)
                assert await attachments.exists(_SHA)
            else:
                target = _A if case == "episode-with-attachment" else _C
                result = await manager.forget_episode(target)
                assert result.deleted_episode_ids == [target]

            assert {**calls, "citation_reads": store.citation_reads} == expected
    finally:
        await store.close()


# --- T12, T13: overlapping erasures run one at a time (A-4, B1) -----------------------------------------------------

_FIRST, _SECOND = "/srv/bf939/first.log", "/srv/bf939/second.log"
_OVERLAP_WAIT_S = 1.0


def _two_owners() -> tuple[Episode, Episode]:
    """ep-000 (agent-a, under ``_FIRST``) and ep-001 (agent-b, under ``_SECOND``), both naming the shared attachment."""
    first, second = _naming(0), _naming(1, agent="agent-b")
    return (
        dataclasses.replace(first, user_input=f"{first.user_input} under {_FIRST}"),
        dataclasses.replace(second, user_input=f"{second.user_input} under {_SECOND}"),
    )


def _rendezvous_after_the_archive_scan(monkeypatch: pytest.MonkeyPatch, em: Any) -> list[int]:
    """B1's interleaving, made deterministic, for two erasures on ``em``.

    Each archive scan, after its last row, waits up to ``_OVERLAP_WAIT_S`` for the other erasure's scan to finish
    too. Unserialized, both scans finish before either erasure decides (the race reviewer B reproduced); serialized,
    the first waits alone, then decides, unlinks and evicts before the second scans. Returns, per finished scan, how
    many other finished scans were still waiting then: ``[0, 0]`` means the two never overlapped.
    """
    inner = em.iter_archived_episodes
    waiting = [0]
    arrivals: list[int] = []
    both = asyncio.Event()

    async def rendezvous(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        async for episode in inner(*args, **kwargs):
            yield episode
        arrivals.append(waiting[0])
        if len(arrivals) == 2:
            both.set()
        waiting[0] += 1
        try:
            with contextlib.suppress(TimeoutError):  # serialized: nothing else can reach its scan meanwhile
                await asyncio.wait_for(both.wait(), _OVERLAP_WAIT_S)
        finally:
            waiting[0] -= 1

    monkeypatch.setattr(em, "iter_archived_episodes", rendezvous)
    return arrivals


_OVERLAPS: dict[str, tuple[Any, Any]] = {
    "two-episodes": (lambda manager: manager.forget_episode(_A), lambda manager: manager.forget_episode(_B)),
    "two-resources": (
        lambda manager: manager.forget_resource(_FIRST), lambda manager: manager.forget_resource(_SECOND),
    ),
    "agent-and-episode": (
        lambda manager: manager.forget_agent_memory("agent-a"), lambda manager: manager.forget_episode(_B),
    ),
}


@pytest.mark.parametrize("overlap", list(_OVERLAPS))
async def test_overlapping_erasures_on_one_memory_leave_no_attachment_once_every_owner_is_erased(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overlap: str,
) -> None:
    """B1: two managers on one memory, as the route builds one per request, each erasing one of two owners."""
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, list(_two_owners()))
        arrivals = _rendezvous_after_the_archive_scan(monkeypatch, rig.em)
        erase_first, erase_second = _OVERLAPS[overlap]

        results = await asyncio.gather(
            erase_first(_manager(rig, attachments)), erase_second(_manager(rig, attachments)),
        )

        assert not await attachments.exists(_SHA)  # B1: no owner remains, so neither erasure may keep it
        assert sorted(sha for result in results for sha in result.deleted_attachment_ids) == [_SHA]
        assert sorted(sha for result in results for sha in result.retained_attachments) == [_SHA]  # kept once, then removed
        assert _raw(rig.em, [_A, _B])["ids"] == []
        assert arrivals == [0, 0]  # the two scans never overlapped


class _AnyMemory:
    """A stand-in key: the erasure lock needs only an object it can weakly reference."""


def test_the_erasure_lock_is_one_per_memory_and_follows_the_running_loop() -> None:
    # Imported here, so that on a tree without A-4 only this test fails, not the module's collection
    from probos.knowledge.erasure import _one_erasure_at_a_time

    memory, other = _AnyMemory(), _AnyMemory()

    async def hold() -> None:
        async with _one_erasure_at_a_time(memory):
            pass

    async def contend() -> Any:
        lock = _one_erasure_at_a_time(memory)
        assert _one_erasure_at_a_time(memory) is lock  # one lock per memory in a loop ...
        assert _one_erasure_at_a_time(other) is not lock  # ... and each memory its own
        async with lock:
            waiter = asyncio.create_task(hold())
            await asyncio.sleep(0)
            assert not waiter.done()  # the waiter queues on the lock, which binds it to this loop
        await waiter
        return lock

    first = asyncio.run(contend())
    second = asyncio.run(contend())  # the first loop's lock would raise "bound to a different event loop" here

    assert second is not first
    assert isinstance(_one_erasure_at_a_time(None), contextlib.nullcontext)  # no memory, no lock


# --- T14, T15: an owner recording that raises never shrinks an erasure (A-4, A1) -----------------------------------


def _fail_recording_for(
    monkeypatch: pytest.MonkeyPatch, manager: ErasureManager, fault: str, episode_id: str,
) -> list[Any]:
    """Make recording ``episode_id``'s owners raise: its ``_episode_to_dict`` (``serialization``) or its
    ``_extract_attachment_ids`` (``extraction``). Test-only private access. Returns the id each call saw."""
    name = "_episode_to_dict" if fault == "serialization" else "_extract_attachment_ids"
    inner = getattr(manager, name)
    seen: list[Any] = []

    def failing(value: Any) -> Any:
        if fault == "serialization":
            seen_id = getattr(value, "id", None)
        else:
            seen_id = value.get("id") if isinstance(value, dict) else None
        seen.append(seen_id)
        if seen_id == episode_id:
            raise ValueError(f"injected: recording the owners of {episode_id} failed")
        return inner(value)

    monkeypatch.setattr(manager, name, failing)
    return seen


# The resource cascade's own predicate serializes every episode, so its serialization fault ends the scan on the
# base too (reviewer A): that case is not a regression and is not listed here.
_RECORDING_FAULTS = [
    pytest.param(target, fault, where, wired, id=f"{target}-{fault}-{where}-{'wired' if wired else 'unwired'}")
    for target, fault in (("agent", "serialization"), ("agent", "extraction"), ("resource", "extraction"))
    for where in ("live", "archived")
    for wired in (True, False)
]


@pytest.mark.parametrize(("target", "fault", "where", "wired"), _RECORDING_FAULTS)
async def test_an_owner_recording_failure_never_ends_a_cascades_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    target: str, fault: str, where: str, wired: bool,
) -> None:
    """A1: an unrelated episode whose owners cannot be recorded never hides a later match; unwired, nothing is
    recorded, so the cascade is the base's."""
    async with _vessel(tmp_path) as (rig, attachments):
        episodes = [
            _naming(0, resource=True),
            _naming(1, agent="agent-b", attachment=False),
            _naming(2, resource=True, attachment=False),
        ]
        await _stored(rig.em, episodes, archived=[_B, _C] if where == "archived" else [])
        order = [episode.id async for episode in rig.em.iter_live_episodes()]
        order += [episode.id async for episode in rig.em.iter_archived_episodes()]
        assert order.index(_B) < order.index(_C)  # premise: the failing ep-001 is scanned before the match ep-002
        manager = ErasureManager(rig.em, attachments if wired else None, None)
        seen = _fail_recording_for(monkeypatch, manager, fault, _B)
        caplog.set_level(logging.WARNING, logger="probos.knowledge.erasure")

        if wired:
            with pytest.raises(ErasureCascadeIncomplete) as incomplete:
                await _forget(manager, target)
            result = incomplete.value.result
            assert result.deleted_episode_ids == [_A, _C]
            assert incomplete.value.failures == {}
            assert str(incomplete.value.enumeration_error) == f"injected: recording the owners of {_B} failed"
            assert result.deleted_attachment_ids == [_SHA]  # only ep-000 names it
            assert any("recording the attachment owners" in record.getMessage() for record in caplog.records)
        else:
            result = await _forget(manager, target)
            assert result.deleted_episode_ids == [_A, _C]
            assert _B not in seen  # no attachment store, so no owner was recorded

        if where == "live":
            assert _raw(rig.em, [_A, _B, _C])["ids"] == [_B]
        else:
            assert [episode.id async for episode in rig.em.iter_archived_episodes()] == [_B]


async def test_an_owner_recording_failure_on_the_single_path_still_reaches_the_owners_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 on the single path: the scan goes on past the failure, so a later owner still keeps the attachment."""
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0), _naming(1, agent="agent-b", attachment=False), _naming(2, agent="agent-c")])
        order = [episode.id async for episode in rig.em.iter_live_episodes()]
        assert order.index(_B) < order.index(_C)  # premise: the failing ep-001 is scanned before the owner ep-002
        manager = _manager(rig, attachments)
        _fail_recording_for(monkeypatch, manager, "extraction", _B)

        with pytest.raises(ErasureCascadeIncomplete) as incomplete:
            await manager.forget_episode(_A)

        assert incomplete.value.result.retained_attachments == {_SHA: [_C]}
        assert await attachments.exists(_SHA)
        assert incomplete.value.failures == {}
        assert str(incomplete.value.enumeration_error) == f"injected: recording the owners of {_B} failed"
        assert incomplete.value.result.deleted_episode_ids == [_A]
        assert sorted(_raw(rig.em, [_A, _B, _C])["ids"]) == [_B, _C]
