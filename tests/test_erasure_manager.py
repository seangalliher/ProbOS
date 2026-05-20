"""AD-754: erasure manager tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from probos.knowledge.erasure import ErasureManager


@dataclass
class _Episode:
    id: str
    agent_ids: list[str]
    outcomes: list[dict[str, object]]
    user_input: str = ""


class _FakeEpisodicMemory:
    def __init__(self, episodes: list[_Episode]) -> None:
        self._episodes = {e.id: e for e in episodes}

    async def get_by_ids(self, episode_ids: list[str]) -> list[_Episode]:
        return [self._episodes[eid] for eid in episode_ids if eid in self._episodes]

    async def get_episode_metadata(self, episode_id: str) -> dict[str, object] | None:
        episode = self._episodes.get(episode_id)
        if episode is None:
            return None
        return {"outcomes": episode.outcomes}

    async def evict_by_ids(self, episode_ids: list[str], reason: str = "user_request") -> int:
        deleted = 0
        for eid in episode_ids:
            if eid in self._episodes:
                del self._episodes[eid]
                deleted += 1
        return deleted

    async def list_episodes(self, limit: int | None = None) -> list[_Episode]:
        episodes = list(self._episodes.values())
        return episodes if limit is None else episodes[:limit]


class _FakeAttachmentStore:
    def __init__(self) -> None:
        self.deleted: set[str] = set()

    async def unlink(self, content_hash: str) -> bool:
        self.deleted.add(content_hash)
        return True


class _FakeAuditLog:
    def __init__(self) -> None:
        self.markers: list[str] = []

    async def mark_deleted(self, resource_marker: str) -> int:
        self.markers.append(resource_marker)
        return 1


@pytest.mark.asyncio
async def test_forget_episode_removes_episode_and_attachments() -> None:
    attachment_id = "a" * 64
    episodic = _FakeEpisodicMemory([
        _Episode(
            id="ep-1",
            agent_ids=["yeo"],
            outcomes=[{"attachment_id": attachment_id}],
        )
    ])
    store = _FakeAttachmentStore()
    audit = _FakeAuditLog()

    manager = ErasureManager(episodic_memory=episodic, attachment_store=store, audit_log=audit)
    result = await manager.forget_episode("ep-1")

    assert "ep-1" in result.deleted_episode_ids
    assert attachment_id in store.deleted


@pytest.mark.asyncio
async def test_forget_resource_cascades_without_errors() -> None:
    episodic = _FakeEpisodicMemory([
        _Episode(
            id="ep-1",
            agent_ids=["yeo"],
            outcomes=[],
            user_input="open ~/private/secrets.txt",
        ),
        _Episode(
            id="ep-2",
            agent_ids=["yeo"],
            outcomes=[],
            user_input="safe note",
        ),
    ])

    manager = ErasureManager(
        episodic_memory=episodic,
        attachment_store=_FakeAttachmentStore(),
        audit_log=_FakeAuditLog(),
    )
    result = await manager.forget_resource("~/private/secrets.txt")

    assert "ep-1" in result.deleted_episode_ids
    remaining = await episodic.list_episodes()
    assert {episode.id for episode in remaining} == {"ep-2"}


@pytest.mark.asyncio
async def test_forget_episode_marks_audit_log_deleted_marker() -> None:
    episodic = _FakeEpisodicMemory([
        _Episode(id="ep-1", agent_ids=["yeo"], outcomes=[])
    ])
    audit = _FakeAuditLog()

    manager = ErasureManager(
        episodic_memory=episodic,
        attachment_store=_FakeAttachmentStore(),
        audit_log=audit,
    )
    await manager.forget_episode("ep-1")

    assert audit.markers == ["ep-1"]
