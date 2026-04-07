"""AD-570b: Participant Index Tests — SQLite sidecar junction table.

20 tests across 4 test classes covering:
- ParticipantIndex unit tests (9)
- EpisodicMemory integration tests (6)
- Migration tests (3)
- String-contains bug fix tests (2)
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.episodic import EpisodicMemory, migrate_participant_index
from probos.cognitive.participant_index import ParticipantIndex
from probos.types import AnchorFrame, Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    *,
    ep_id: str = "",
    user_input: str = "test input",
    timestamp: float | None = None,
    agent_ids: list[str] | None = None,
    anchors: AnchorFrame | None = None,
) -> Episode:
    ep = Episode(
        user_input=user_input,
        timestamp=timestamp or time.time(),
        agent_ids=agent_ids or ["agent-001"],
        source="direct",
        anchors=anchors,
        outcomes=[{"intent": "test_intent", "success": True}],
    )
    if ep_id:
        object.__setattr__(ep, "id", ep_id)
    return ep


def _anchor(
    *,
    department: str = "",
    channel: str = "",
    trigger_type: str = "",
    trigger_agent: str = "",
    participants: list[str] | None = None,
) -> AnchorFrame:
    return AnchorFrame(
        department=department,
        channel=channel,
        trigger_type=trigger_type,
        trigger_agent=trigger_agent,
        participants=participants or [],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def participant_index(tmp_path):
    idx = ParticipantIndex(db_path=str(tmp_path / "participant_index.db"))
    await idx.start()
    yield idx
    await idx.stop()


@pytest.fixture
def tmp_episodic(tmp_path):
    em = EpisodicMemory(db_path=str(tmp_path / "chroma" / "episodes.db"), max_episodes=100)
    return em


# ---------------------------------------------------------------------------
# TestParticipantIndex — Unit tests for the sidecar (9)
# ---------------------------------------------------------------------------

class TestParticipantIndex:
    """Unit tests for ParticipantIndex CRUD operations."""

    @pytest.mark.asyncio
    async def test_record_and_query_by_agent_id(self, participant_index):
        """Store episode with agent_ids, query by sovereign ID."""
        await participant_index.record_episode("ep-1", ["sovereign-abc"], ["worf"])
        result = await participant_index.get_episode_ids_for_agent("sovereign-abc")
        assert "ep-1" in result

    @pytest.mark.asyncio
    async def test_record_and_query_by_callsign(self, participant_index):
        """Store episode with participants, query by callsign."""
        await participant_index.record_episode("ep-1", ["sovereign-abc"], ["worf", "data"])
        result = await participant_index.get_episode_ids_for_callsign("worf")
        assert "ep-1" in result
        result2 = await participant_index.get_episode_ids_for_callsign("data")
        assert "ep-1" in result2

    @pytest.mark.asyncio
    async def test_query_participants_any(self, participant_index):
        """OR semantics: any of [A, B] present."""
        await participant_index.record_episode("ep-1", ["a1"], ["worf"])
        await participant_index.record_episode("ep-2", ["a2"], ["data"])
        await participant_index.record_episode("ep-3", ["a3"], ["troi"])

        result = await participant_index.get_episode_ids_for_participants(
            ["worf", "data"], require_all=False,
        )
        assert set(result) == {"ep-1", "ep-2"}

    @pytest.mark.asyncio
    async def test_query_participants_all(self, participant_index):
        """AND semantics: both A and B must be present."""
        await participant_index.record_episode("ep-1", ["a1"], ["worf", "data"])
        await participant_index.record_episode("ep-2", ["a2"], ["worf"])
        await participant_index.record_episode("ep-3", ["a3"], ["data"])

        result = await participant_index.get_episode_ids_for_participants(
            ["worf", "data"], require_all=True,
        )
        assert result == ["ep-1"]

    @pytest.mark.asyncio
    async def test_count_for_agent(self, participant_index):
        """Verify count matches expected."""
        await participant_index.record_episode("ep-1", ["agent-x"], [])
        await participant_index.record_episode("ep-2", ["agent-x"], [])
        await participant_index.record_episode("ep-3", ["agent-y"], [])

        assert await participant_index.count_for_agent("agent-x") == 2
        assert await participant_index.count_for_agent("agent-y") == 1
        assert await participant_index.count_for_agent("agent-z") == 0

    @pytest.mark.asyncio
    async def test_delete_episodes(self, participant_index):
        """Verify cleanup removes all rows for deleted episode IDs."""
        await participant_index.record_episode("ep-1", ["a1"], ["worf"])
        await participant_index.record_episode("ep-2", ["a2"], ["data"])

        await participant_index.delete_episodes(["ep-1"])

        result = await participant_index.get_episode_ids_for_agent("a1")
        assert result == []
        result2 = await participant_index.get_episode_ids_for_agent("a2")
        assert "ep-2" in result2

    @pytest.mark.asyncio
    async def test_record_episode_batch(self, participant_index):
        """Bulk insert, verify all queryable."""
        batch = [
            ("ep-1", ["a1"], ["worf"]),
            ("ep-2", ["a2"], ["data", "troi"]),
            ("ep-3", ["a3"], []),
        ]
        await participant_index.record_episode_batch(batch)

        assert "ep-1" in await participant_index.get_episode_ids_for_callsign("worf")
        assert "ep-2" in await participant_index.get_episode_ids_for_callsign("data")
        assert "ep-2" in await participant_index.get_episode_ids_for_callsign("troi")
        assert "ep-3" in await participant_index.get_episode_ids_for_agent("a3")

    @pytest.mark.asyncio
    async def test_duplicate_insert_ignored(self, participant_index):
        """INSERT OR IGNORE doesn't error on re-insert."""
        await participant_index.record_episode("ep-1", ["a1"], ["worf"])
        # Re-insert same data — should not raise
        await participant_index.record_episode("ep-1", ["a1"], ["worf"])

        result = await participant_index.get_episode_ids_for_agent("a1")
        assert result == ["ep-1"]

    @pytest.mark.asyncio
    async def test_empty_participants(self, participant_index):
        """Episode with no participants, only agent_ids."""
        await participant_index.record_episode("ep-1", ["a1", "a2"], [])

        result = await participant_index.get_episode_ids_for_agent("a1")
        assert "ep-1" in result
        result2 = await participant_index.get_episode_ids_for_agent("a2")
        assert "ep-1" in result2
        result3 = await participant_index.get_episode_ids_for_callsign("a1")
        # a1 was recorded as author with empty callsign, so callsign search won't find it
        assert "ep-1" not in result3


# ---------------------------------------------------------------------------
# TestParticipantIndexIntegration — Wired to EpisodicMemory (6)
# ---------------------------------------------------------------------------

class TestParticipantIndexIntegration:
    """Integration tests: EpisodicMemory dual-writes to ParticipantIndex."""

    @pytest.mark.asyncio
    async def test_store_populates_index(self, tmp_episodic, tmp_path):
        """store() dual-writes to participant index."""
        await tmp_episodic.start()
        idx = ParticipantIndex(db_path=str(tmp_path / "pi.db"))
        await idx.start()
        tmp_episodic.set_participant_index(idx)

        ep = _make_episode(
            agent_ids=["sovereign-001"],
            anchors=_anchor(participants=["worf", "data"]),
        )
        await tmp_episodic.store(ep)

        result = await idx.get_episode_ids_for_agent("sovereign-001")
        assert ep.id in result
        result2 = await idx.get_episode_ids_for_callsign("worf")
        assert ep.id in result2
        result3 = await idx.get_episode_ids_for_callsign("data")
        assert ep.id in result3

        await idx.stop()
        await tmp_episodic.stop()

    @pytest.mark.asyncio
    async def test_seed_populates_index(self, tmp_episodic, tmp_path):
        """seed() batch-writes to participant index."""
        await tmp_episodic.start()
        idx = ParticipantIndex(db_path=str(tmp_path / "pi.db"))
        await idx.start()
        tmp_episodic.set_participant_index(idx)

        episodes = [
            _make_episode(
                ep_id=f"seed-{i}",
                user_input=f"seed input {i}",
                agent_ids=[f"agent-{i}"],
                anchors=_anchor(participants=[f"crew-{i}"]),
            )
            for i in range(3)
        ]
        seeded = await tmp_episodic.seed(episodes)
        assert seeded == 3

        for i in range(3):
            result = await idx.get_episode_ids_for_callsign(f"crew-{i}")
            assert f"seed-{i}" in result

        await idx.stop()
        await tmp_episodic.stop()

    @pytest.mark.asyncio
    async def test_evict_cleans_index(self, tmp_path):
        """Eviction removes participant records."""
        em = EpisodicMemory(db_path=str(tmp_path / "chroma" / "episodes.db"), max_episodes=2)
        await em.start()
        idx = ParticipantIndex(db_path=str(tmp_path / "pi.db"))
        await idx.start()
        em.set_participant_index(idx)

        # Store 3 episodes — max is 2, so oldest gets evicted
        for i in range(3):
            ep = _make_episode(
                user_input=f"eviction test {i}",
                timestamp=time.time() - (300 - i * 100),  # oldest first
                agent_ids=[f"agent-{i}"],
                anchors=_anchor(participants=[f"crew-{i}"]),
            )
            await em.store(ep)

        # agent-0 should have been evicted
        count_0 = await idx.count_for_agent("agent-0")
        # agent-2 should still exist
        count_2 = await idx.count_for_agent("agent-2")
        assert count_0 == 0
        assert count_2 == 1

        await idx.stop()
        await em.stop()

    @pytest.mark.asyncio
    async def test_evict_by_ids_cleans_index(self, tmp_episodic, tmp_path):
        """Explicit eviction removes participant records."""
        await tmp_episodic.start()
        idx = ParticipantIndex(db_path=str(tmp_path / "pi.db"))
        await idx.start()
        tmp_episodic.set_participant_index(idx)

        ep = _make_episode(
            agent_ids=["agent-x"],
            anchors=_anchor(participants=["worf"]),
        )
        await tmp_episodic.store(ep)
        assert await idx.count_for_agent("agent-x") == 1

        evicted = await tmp_episodic.evict_by_ids([ep.id])
        assert evicted == 1
        assert await idx.count_for_agent("agent-x") == 0

        await idx.stop()
        await tmp_episodic.stop()

    @pytest.mark.asyncio
    async def test_recall_by_anchor_with_participants(self, tmp_episodic, tmp_path):
        """recall_by_anchor(participants=["worf"]) returns correct episodes."""
        await tmp_episodic.start()
        idx = ParticipantIndex(db_path=str(tmp_path / "pi.db"))
        await idx.start()
        tmp_episodic.set_participant_index(idx)

        # Episode with worf participating
        ep1 = _make_episode(
            user_input="worf episode",
            agent_ids=["agent-1"],
            anchors=_anchor(department="security", participants=["worf"]),
        )
        await tmp_episodic.store(ep1)

        # Episode without worf
        ep2 = _make_episode(
            user_input="data episode",
            agent_ids=["agent-2"],
            anchors=_anchor(department="science", participants=["data"]),
        )
        await tmp_episodic.store(ep2)

        result = await tmp_episodic.recall_by_anchor(participants=["worf"])
        assert len(result) == 1
        assert result[0].id == ep1.id

        await idx.stop()
        await tmp_episodic.stop()

    @pytest.mark.asyncio
    async def test_recall_by_anchor_participants_and_department(self, tmp_episodic, tmp_path):
        """Combined filter: participants AND department."""
        await tmp_episodic.start()
        idx = ParticipantIndex(db_path=str(tmp_path / "pi.db"))
        await idx.start()
        tmp_episodic.set_participant_index(idx)

        # Episode with worf in security
        ep1 = _make_episode(
            user_input="worf security episode",
            agent_ids=["agent-1"],
            anchors=_anchor(department="security", participants=["worf"]),
        )
        await tmp_episodic.store(ep1)

        # Episode with worf in engineering
        ep2 = _make_episode(
            user_input="worf engineering episode",
            agent_ids=["agent-2"],
            anchors=_anchor(department="engineering", participants=["worf"]),
        )
        await tmp_episodic.store(ep2)

        result = await tmp_episodic.recall_by_anchor(
            participants=["worf"], department="security",
        )
        assert len(result) == 1
        assert result[0].id == ep1.id

        await idx.stop()
        await tmp_episodic.stop()


# ---------------------------------------------------------------------------
# TestMigration (3)
# ---------------------------------------------------------------------------

class TestMigration:
    """Tests for migrate_participant_index()."""

    @pytest.mark.asyncio
    async def test_migrate_participant_index(self, tmp_episodic, tmp_path):
        """Migration backfills from existing episodes."""
        await tmp_episodic.start()

        # Store episodes without participant index first
        ep1 = _make_episode(
            user_input="pre-migration 1",
            agent_ids=["agent-1"],
            anchors=_anchor(participants=["worf", "data"]),
        )
        await tmp_episodic.store(ep1)
        ep2 = _make_episode(
            user_input="pre-migration 2",
            agent_ids=["agent-2"],
            anchors=_anchor(participants=["troi"]),
        )
        await tmp_episodic.store(ep2)

        # Now wire participant index and run migration
        idx = ParticipantIndex(db_path=str(tmp_path / "pi.db"))
        await idx.start()
        tmp_episodic.set_participant_index(idx)

        migrated = await migrate_participant_index(tmp_episodic)
        assert migrated == 2

        # Verify data was backfilled
        result = await idx.get_episode_ids_for_callsign("worf")
        assert ep1.id in result
        result2 = await idx.get_episode_ids_for_callsign("troi")
        assert ep2.id in result2

        await idx.stop()
        await tmp_episodic.stop()

    @pytest.mark.asyncio
    async def test_migrate_empty_collection(self, tmp_episodic, tmp_path):
        """Migration with no episodes returns 0."""
        await tmp_episodic.start()
        idx = ParticipantIndex(db_path=str(tmp_path / "pi.db"))
        await idx.start()
        tmp_episodic.set_participant_index(idx)

        migrated = await migrate_participant_index(tmp_episodic)
        assert migrated == 0

        await idx.stop()
        await tmp_episodic.stop()

    @pytest.mark.asyncio
    async def test_migrate_no_index(self, tmp_episodic):
        """Migration without participant_index wired returns 0."""
        await tmp_episodic.start()
        migrated = await migrate_participant_index(tmp_episodic)
        assert migrated == 0
        await tmp_episodic.stop()


# ---------------------------------------------------------------------------
# TestStringContainsBugFix (2)
# ---------------------------------------------------------------------------

class TestStringContainsBugFix:
    """Verify lines 719/739 use proper JSON parsing, not string `in`."""

    @pytest.mark.asyncio
    async def test_is_rate_limited_uses_json_parse(self, tmp_episodic):
        """Line 719 fix: proper JSON parsing prevents substring false positives."""
        await tmp_episodic.start()

        # Store an episode for agent "agent-001"
        ep = _make_episode(
            user_input="rate limit test",
            agent_ids=["agent-001"],
        )
        await tmp_episodic.store(ep)

        # "01" is a substring of "agent-001" — the old string `in` check
        # would have matched. The JSON parse fix should NOT match.
        ep2 = _make_episode(
            user_input="different episode",
            agent_ids=["01"],
        )
        # Should NOT be rate-limited (agent "01" has 0 episodes, not 20)
        assert not tmp_episodic._is_rate_limited(ep2)

        await tmp_episodic.stop()

    @pytest.mark.asyncio
    async def test_is_duplicate_content_uses_json_parse(self, tmp_episodic):
        """Line 739 fix: proper JSON parsing prevents substring false positives."""
        await tmp_episodic.start()

        # Store an episode for agent "agent-001"
        ep = _make_episode(
            user_input="duplicate test content here for matching",
            agent_ids=["agent-001"],
        )
        await tmp_episodic.store(ep)

        # Agent "01" should NOT see agent-001's episodes as duplicates
        ep2 = _make_episode(
            user_input="duplicate test content here for matching",
            agent_ids=["01"],
        )
        assert not tmp_episodic._is_duplicate_content(ep2)

        await tmp_episodic.stop()
