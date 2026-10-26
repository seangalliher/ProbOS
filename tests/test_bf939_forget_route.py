"""BF-939 (#1683) M2: the forget route reports each attachment it kept and the episodes that still name it.

The real app's ``POST /api/security/forget`` (S2a's client), a real ``EpisodicMemory`` and a real
``FilesystemAttachmentStore`` on the runtime.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
from pathlib import Path

import pytest

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.routers import chat as chat_router
from probos.types import EpisodeStoreOutcome
from tests.test_ad1340_s1_eviction import _episode, _memory, _raw
from tests.test_ad1340_s2a_lookup_route import _client, _post, _runtime
from tests.test_bf939_shared_attachment_ownership import (
    _BODY as _SHARED_BODY,
    _FIRST,
    _SECOND,
    _SHA as _SHARED_SHA,
    _rendezvous_after_the_archive_scan,
    _two_owners,
)

_FORGET = "/api/security/forget"
_BODY = b"bf939: one photograph, two episodes, through the route"
_SHA = hashlib.sha256(_BODY).hexdigest()
_PHOTO, _CHART = b"bf939 route: the photograph", b"bf939 route: the chart"
_PHOTO_SHA, _CHART_SHA = (hashlib.sha256(body).hexdigest() for body in (_PHOTO, _CHART))


async def test_the_forget_route_reports_the_attachment_it_kept_and_removes_it_with_the_last_episode(
    tmp_path: Path,
) -> None:
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        attachments = FilesystemAttachmentStore(tmp_path / "attachments")
        try:
            await attachments.write(_SHA, _BODY, "text/plain")
            first, second = (
                dataclasses.replace(
                    _episode(i), outcomes=[{"intent": "report", "success": True, "attachment_refs": [_SHA]}],
                )
                for i in (0, 1)
            )
            for episode in (first, second):
                assert await rig.em.store(episode) is EpisodeStoreOutcome.STORED
            assert await attachments.exists(_SHA)  # premise: one file, named by both episodes
            runtime = _runtime(root, rig.em)
            runtime.attachment_store = attachments

            async with _client(runtime) as client:
                kept = await _post(client, _FORGET, {"episode_id": first.id})

                assert kept.status_code == 200, kept.text
                assert kept.json()["deleted_episode_ids"] == [first.id]
                assert kept.json()["deleted_attachment_ids"] == []
                assert kept.json()["retained_attachment_ids"] == {_SHA: [second.id]}
                assert kept.json()["deleted_count"] == 1
                assert await attachments.exists(_SHA)

                removed = await _post(client, _FORGET, {"episode_id": second.id})

                assert removed.status_code == 200, removed.text
                assert removed.json()["deleted_attachment_ids"] == [_SHA]
                assert removed.json()["retained_attachment_ids"] == {}
                assert removed.json()["deleted_count"] == 2
            assert not await attachments.exists(_SHA)
            assert _raw(rig.em, [first.id, second.id])["ids"] == []
        finally:
            attachments.close()


async def test_the_forget_route_maps_each_kept_attachment_to_its_own_sorted_holders(tmp_path: Path) -> None:
    """B4 (A-4): two kept attachments with different holders, one held by two episodes. Reversing a holder list,
    or swapping two entries' holders, fails it."""
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        attachments = FilesystemAttachmentStore(tmp_path / "attachments")
        try:
            for body, sha in ((_PHOTO, _PHOTO_SHA), (_CHART, _CHART_SHA)):
                await attachments.write(sha, body, "text/plain")
            named = {0: [_PHOTO_SHA, _CHART_SHA], 1: [_PHOTO_SHA], 2: [_PHOTO_SHA, _CHART_SHA]}
            episodes = [
                dataclasses.replace(
                    _episode(i), outcomes=[{"intent": "report", "success": True, "attachment_refs": refs}],
                )
                for i, refs in named.items()
            ]
            for episode in episodes:
                assert await rig.em.store(episode) is EpisodeStoreOutcome.STORED
            erased, photo_only, both = (episode.id for episode in episodes)
            runtime = _runtime(root, rig.em)
            runtime.attachment_store = attachments

            async with _client(runtime) as client:
                answer = await _post(client, _FORGET, {"episode_id": erased})

            assert answer.status_code == 200, answer.text
            retained = answer.json()["retained_attachment_ids"]
            assert retained == {_PHOTO_SHA: sorted([photo_only, both]), _CHART_SHA: [both]}
            assert list(retained) == sorted(retained)  # the map's keys arrive in sorted order
            assert answer.json()["deleted_attachment_ids"] == []
            assert answer.json()["deleted_count"] == 1
            assert await attachments.exists(_PHOTO_SHA)
            assert await attachments.exists(_CHART_SHA)
        finally:
            attachments.close()


_OVERLAPPING_REQUESTS = {
    "episode": ({"episode_id": "ep-000"}, {"episode_id": "ep-001"}),
    "agent": ({"agent_id": "agent-a"}, {"agent_id": "agent-b"}),
    "resource": ({"resource_path": _FIRST}, {"resource_path": _SECOND}),
    "agent-and-episode": ({"agent_id": "agent-a"}, {"episode_id": "ep-001"}),
}


@pytest.mark.parametrize("form", list(_OVERLAPPING_REQUESTS))
async def test_overlapping_forget_requests_leave_nothing_downloadable_once_every_owner_is_erased(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str,
) -> None:
    """B1 (A-4) through the real app: two requests, each erasing one of two episodes that name one file."""
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        attachments = FilesystemAttachmentStore(tmp_path / "attachments")
        runtime = _runtime(root, rig.em)
        runtime.attachment_store = attachments
        # The download route reads the router's cached store: seed it with this one (test_ad1124's pattern)
        chat_router._ATTACHMENT_STORE_CACHE[id(runtime)] = attachments
        try:
            await attachments.write(_SHARED_SHA, _SHARED_BODY, "text/plain")
            for episode in _two_owners():
                assert await rig.em.store(episode) is EpisodeStoreOutcome.STORED
            arrivals = _rendezvous_after_the_archive_scan(monkeypatch, rig.em)

            async with _client(runtime) as client:
                before = await client.get(f"/api/chat/attachments/{_SHARED_SHA}")
                assert before.status_code == 200, before.text  # premise: the file is served ...
                assert before.content == _SHARED_BODY  # ... and both episodes name it
                answers = await asyncio.gather(
                    *(_post(client, _FORGET, body) for body in _OVERLAPPING_REQUESTS[form]),
                )
                after = await client.get(f"/api/chat/attachments/{_SHARED_SHA}")

            assert [answer.status_code for answer in answers] == [200, 200], [answer.text for answer in answers]
            assert after.status_code == 404  # B1: every owner is erased, so nothing may still serve the bytes
            assert sorted(sha for answer in answers for sha in answer.json()["deleted_attachment_ids"]) == [_SHARED_SHA]
            assert _raw(rig.em, ["ep-000", "ep-001"])["ids"] == []
            assert arrivals == [0, 0]  # the two erasures' scans never overlapped
        finally:
            chat_router._ATTACHMENT_STORE_CACHE.pop(id(runtime), None)
            attachments.close()
