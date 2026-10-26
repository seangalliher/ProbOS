"""BF-939 (#1683) M2: the forget route reports each attachment it kept and the episodes that still name it.

The real app's ``POST /api/security/forget`` (S2a's client), a real ``EpisodicMemory`` and a real
``FilesystemAttachmentStore`` on the runtime.
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.types import EpisodeStoreOutcome
from tests.test_ad1340_s1_eviction import _episode, _memory, _raw
from tests.test_ad1340_s2a_lookup_route import _client, _post, _runtime

_FORGET = "/api/security/forget"
_BODY = b"bf939: one photograph, two episodes, through the route"
_SHA = hashlib.sha256(_BODY).hexdigest()


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
