"""AD-570: Anchor-Indexed Episodic Recall — Structured AnchorFrame Queries.

23 tests covering metadata promotion, migration, recall_by_anchor()
(enumeration + semantic modes), and edge cases.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.episodic import EpisodicMemory, migrate_anchor_metadata
from probos.types import AnchorFrame, Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    *,
    user_input: str = "test input",
    timestamp: float | None = None,
    agent_ids: list[str] | None = None,
    anchors: AnchorFrame | None = None,
) -> Episode:
    return Episode(
        user_input=user_input,
        timestamp=timestamp or time.time(),
        agent_ids=agent_ids or ["agent-001"],
        source="direct",
        anchors=anchors,
        outcomes=[{"intent": "test_intent", "success": True}],
    )


def _anchor(
    *,
    department: str = "",
    channel: str = "",
    trigger_type: str = "",
    trigger_agent: str = "",
) -> AnchorFrame:
    return AnchorFrame(
        department=department,
        channel=channel,
        trigger_type=trigger_type,
        trigger_agent=trigger_agent,
    )


# ---------------------------------------------------------------------------
# Metadata Promotion Tests (5)
# ---------------------------------------------------------------------------

class TestMetadataPromotion:
    """Verify _episode_to_metadata() promotes anchor fields."""

    def test_episode_to_metadata_promotes_anchor_fields(self):
        ep = _make_episode(
            anchors=_anchor(
                department="medical",
                channel="ward_room",
                trigger_type="proactive_think",
                trigger_agent="echo",
            ),
        )
        meta = EpisodicMemory._episode_to_metadata(ep)
        assert meta["anchor_department"] == "medical"
        assert meta["anchor_channel"] == "ward_room"
        assert meta["anchor_trigger_type"] == "proactive_think"
        assert meta["anchor_trigger_agent"] == "echo"

    def test_episode_to_metadata_empty_anchors(self):
        ep = _make_episode(anchors=None)
        meta = EpisodicMemory._episode_to_metadata(ep)
        assert meta["anchor_department"] == ""
        assert meta["anchor_channel"] == ""
        assert meta["anchor_trigger_type"] == ""
        assert meta["anchor_trigger_agent"] == ""

    def test_episode_to_metadata_partial_anchors(self):
        ep = _make_episode(anchors=_anchor(department="engineering"))
        meta = EpisodicMemory._episode_to_metadata(ep)
        assert meta["anchor_department"] == "engineering"
        assert meta["anchor_channel"] == ""
        assert meta["anchor_trigger_type"] == ""
        assert meta["anchor_trigger_agent"] == ""

    def test_episode_to_metadata_preserves_anchors_json(self):
        ep = _make_episode(
            anchors=_anchor(department="science", trigger_agent="atlas"),
        )
        meta = EpisodicMemory._episode_to_metadata(ep)
        # Both the promoted fields AND the anchors_json blob exist
        assert meta["anchor_department"] == "science"
        assert meta["anchor_trigger_agent"] == "atlas"
        assert meta["anchors_json"] != ""
        blob = json.loads(meta["anchors_json"])
        assert blob["department"] == "science"
        assert blob["trigger_agent"] == "atlas"

    @pytest.mark.asyncio
    async def test_store_writes_promoted_fields_to_chromadb(self, tmp_path):
        mem = EpisodicMemory(
            db_path=tmp_path / "promo.db", max_episodes=100, relevance_threshold=0.3
        )
        await mem.start()
        try:
            ep = _make_episode(
                anchors=_anchor(department="engineering", channel="dm"),
            )
            await mem.store(ep)
            # Fetch back from ChromaDB
            result = mem._collection.get(ids=[ep.id], include=["metadatas"])
            meta = result["metadatas"][0]
            assert meta["anchor_department"] == "engineering"
            assert meta["anchor_channel"] == "dm"
            assert meta["anchor_trigger_type"] == ""
            assert meta["anchor_trigger_agent"] == ""
        finally:
            await mem.stop()


# ---------------------------------------------------------------------------
# Migration Tests (5)
# ---------------------------------------------------------------------------

class TestMigration:
    """Verify migrate_anchor_metadata() backfill."""

    @pytest.mark.asyncio
    async def test_migrate_backfills_existing(self, tmp_path):
        mem = EpisodicMemory(
            db_path=tmp_path / "mig1.db", max_episodes=100, relevance_threshold=0.3
        )
        await mem.start()
        try:
            # Manually insert episode WITHOUT promoted fields
            anchors_data = {"department": "medical", "channel": "ward_room",
                            "trigger_type": "dm", "trigger_agent": "bones"}
            mem._collection.add(
                ids=["ep-001"],
                documents=["test doc"],
                metadatas=[{
                    "timestamp": time.time(),
                    "intent_type": "",
                    "dag_summary_json": "{}",
                    "outcomes_json": "[]",
                    "reflection": "",
                    "agent_ids_json": '["agent-001"]',
                    "duration_ms": 10.0,
                    "shapley_values_json": "{}",
                    "trust_deltas_json": "[]",
                    "source": "direct",
                    "anchors_json": json.dumps(anchors_data),
                    "content_hash": "",
                    "_hash_v": 2,
                }],
            )
            migrated = await migrate_anchor_metadata(mem)
            assert migrated == 1
            result = mem._collection.get(ids=["ep-001"], include=["metadatas"])
            meta = result["metadatas"][0]
            assert meta["anchor_department"] == "medical"
            assert meta["anchor_channel"] == "ward_room"
            assert meta["anchor_trigger_type"] == "dm"
            assert meta["anchor_trigger_agent"] == "bones"
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_migrate_skips_already_migrated(self, tmp_path):
        mem = EpisodicMemory(
            db_path=tmp_path / "mig2.db", max_episodes=100, relevance_threshold=0.3
        )
        await mem.start()
        try:
            ep = _make_episode(anchors=_anchor(department="science"))
            await mem.store(ep)  # store() now writes promoted fields
            migrated = await migrate_anchor_metadata(mem)
            assert migrated == 0
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_migrate_handles_empty_anchors(self, tmp_path):
        mem = EpisodicMemory(
            db_path=tmp_path / "mig3.db", max_episodes=100, relevance_threshold=0.3
        )
        await mem.start()
        try:
            mem._collection.add(
                ids=["ep-empty"],
                documents=["no anchors"],
                metadatas=[{
                    "timestamp": time.time(),
                    "intent_type": "",
                    "dag_summary_json": "{}",
                    "outcomes_json": "[]",
                    "reflection": "",
                    "agent_ids_json": '["agent-001"]',
                    "duration_ms": 10.0,
                    "shapley_values_json": "{}",
                    "trust_deltas_json": "[]",
                    "source": "direct",
                    "anchors_json": "",
                    "content_hash": "",
                    "_hash_v": 2,
                }],
            )
            migrated = await migrate_anchor_metadata(mem)
            assert migrated == 1
            result = mem._collection.get(ids=["ep-empty"], include=["metadatas"])
            meta = result["metadatas"][0]
            assert meta["anchor_department"] == ""
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_migrate_count(self, tmp_path):
        mem = EpisodicMemory(
            db_path=tmp_path / "mig4.db", max_episodes=100, relevance_threshold=0.3
        )
        await mem.start()
        try:
            # 1 already migrated (via store)
            ep1 = _make_episode(anchors=_anchor(department="eng"))
            await mem.store(ep1)
            # 2 needing migration (manual inserts without promoted fields)
            base_meta = {
                "timestamp": time.time(),
                "intent_type": "",
                "dag_summary_json": "{}",
                "outcomes_json": "[]",
                "reflection": "",
                "agent_ids_json": '["agent-001"]',
                "duration_ms": 10.0,
                "shapley_values_json": "{}",
                "trust_deltas_json": "[]",
                "source": "direct",
                "anchors_json": json.dumps({"department": "med"}),
                "content_hash": "",
                "_hash_v": 2,
            }
            mem._collection.add(
                ids=["old-1"], documents=["doc1"], metadatas=[dict(base_meta)]
            )
            mem._collection.add(
                ids=["old-2"], documents=["doc2"], metadatas=[dict(base_meta)]
            )
            migrated = await migrate_anchor_metadata(mem)
            assert migrated == 2
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_migrate_empty_collection(self, tmp_path):
        mem = EpisodicMemory(
            db_path=tmp_path / "mig5.db", max_episodes=100, relevance_threshold=0.3
        )
        await mem.start()
        try:
            migrated = await migrate_anchor_metadata(mem)
            assert migrated == 0
        finally:
            await mem.stop()


# ---------------------------------------------------------------------------
# recall_by_anchor() — Enumeration Mode (6)
# ---------------------------------------------------------------------------

class TestRecallByAnchorEnumeration:
    """Verify recall_by_anchor() enumeration mode (no semantic_query)."""

    @pytest.fixture
    async def mem(self, tmp_path):
        m = EpisodicMemory(
            db_path=tmp_path / "recall_enum.db",
            max_episodes=100,
            relevance_threshold=0.0,  # No threshold for testing
        )
        await m.start()
        yield m
        await m.stop()

    @pytest.mark.asyncio
    async def test_department_filter(self, mem):
        await mem.store(_make_episode(
            user_input="warp core analysis", anchors=_anchor(department="engineering")))
        await mem.store(_make_episode(
            user_input="shield harmonics", anchors=_anchor(department="engineering")))
        await mem.store(_make_episode(
            user_input="patient report", anchors=_anchor(department="medical")))
        results = await mem.recall_by_anchor(department="engineering")
        assert len(results) == 2
        assert all(ep.anchors and ep.anchors.department == "engineering" for ep in results)

    @pytest.mark.asyncio
    async def test_channel_filter(self, mem):
        await mem.store(_make_episode(
            user_input="ward room talk", anchors=_anchor(channel="ward_room")))
        await mem.store(_make_episode(
            user_input="private dm", anchors=_anchor(channel="dm")))
        results = await mem.recall_by_anchor(channel="ward_room")
        assert len(results) == 1
        assert results[0].anchors.channel == "ward_room"

    @pytest.mark.asyncio
    async def test_trigger_type_filter(self, mem):
        await mem.store(_make_episode(
            user_input="proactive thought", anchors=_anchor(trigger_type="proactive_think")))
        await mem.store(_make_episode(
            user_input="direct msg", anchors=_anchor(trigger_type="direct_message")))
        results = await mem.recall_by_anchor(trigger_type="proactive_think")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_combined_filters(self, mem):
        await mem.store(_make_episode(
            user_input="med dm", anchors=_anchor(department="medical", channel="dm")))
        await mem.store(_make_episode(
            user_input="med wr", anchors=_anchor(department="medical", channel="ward_room")))
        await mem.store(_make_episode(
            user_input="eng dm", anchors=_anchor(department="engineering", channel="dm")))
        results = await mem.recall_by_anchor(department="medical", channel="dm")
        assert len(results) == 1
        assert results[0].user_input == "med dm"

    @pytest.mark.asyncio
    async def test_time_range(self, mem):
        t_base = time.time() - 1000
        await mem.store(_make_episode(
            user_input="old", timestamp=t_base, anchors=_anchor(department="eng")))
        await mem.store(_make_episode(
            user_input="mid", timestamp=t_base + 500, anchors=_anchor(department="eng")))
        await mem.store(_make_episode(
            user_input="new", timestamp=t_base + 900, anchors=_anchor(department="eng")))
        # Only mid episode in range
        results = await mem.recall_by_anchor(
            time_range=(t_base + 400, t_base + 600))
        assert len(results) == 1
        assert results[0].user_input == "mid"

    @pytest.mark.asyncio
    async def test_no_filters_returns_empty(self, mem):
        await mem.store(_make_episode(
            user_input="something", anchors=_anchor(department="eng")))
        results = await mem.recall_by_anchor()
        assert results == []


# ---------------------------------------------------------------------------
# recall_by_anchor() — Semantic Mode (4)
# ---------------------------------------------------------------------------

class TestRecallByAnchorSemantic:
    """Verify recall_by_anchor() semantic re-ranking mode."""

    @pytest.fixture
    async def mem(self, tmp_path):
        m = EpisodicMemory(
            db_path=tmp_path / "recall_sem.db",
            max_episodes=100,
            relevance_threshold=0.0,
        )
        await m.start()
        yield m
        await m.stop()

    @pytest.mark.asyncio
    async def test_semantic_reranking(self, mem):
        await mem.store(_make_episode(
            user_input="warp core diagnostic report shows plasma leak",
            anchors=_anchor(department="engineering")))
        await mem.store(_make_episode(
            user_input="patient triage for radiation exposure",
            anchors=_anchor(department="engineering")))
        results = await mem.recall_by_anchor(
            department="engineering",
            semantic_query="warp core diagnostics",
        )
        assert len(results) >= 1
        # Semantic re-ranking: warp core episode should be first
        assert "warp core" in results[0].user_input

    @pytest.mark.asyncio
    async def test_semantic_no_filter(self, mem):
        await mem.store(_make_episode(
            user_input="shield analysis results"))
        results = await mem.recall_by_anchor(
            semantic_query="shield analysis")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_agent_id_filter(self, mem):
        await mem.store(_make_episode(
            user_input="report from atlas",
            agent_ids=["atlas-001"],
            anchors=_anchor(department="science")))
        await mem.store(_make_episode(
            user_input="report from horizon",
            agent_ids=["horizon-002"],
            anchors=_anchor(department="science")))
        results = await mem.recall_by_anchor(
            department="science", agent_id="atlas-001")
        assert len(results) == 1
        assert "atlas-001" in results[0].agent_ids

    @pytest.mark.asyncio
    async def test_limit(self, mem):
        for i in range(10):
            await mem.store(_make_episode(
                user_input=f"episode {i}",
                anchors=_anchor(department="ops"),
            ))
        results = await mem.recall_by_anchor(department="ops", limit=3)
        assert len(results) <= 3


# ---------------------------------------------------------------------------
# Edge Cases (3)
# ---------------------------------------------------------------------------

class TestRecallByAnchorEdgeCases:
    """Edge cases for recall_by_anchor()."""

    @pytest.mark.asyncio
    async def test_no_collection(self):
        mem = EpisodicMemory(
            db_path=None, max_episodes=100, relevance_threshold=0.3
        )
        # _collection is None when not started
        results = await mem.recall_by_anchor(department="engineering")
        assert results == []

    @pytest.mark.asyncio
    async def test_trigger_agent_filter(self, tmp_path):
        mem = EpisodicMemory(
            db_path=tmp_path / "edge.db", max_episodes=100, relevance_threshold=0.0
        )
        await mem.start()
        try:
            await mem.store(_make_episode(
                user_input="worf report",
                anchors=_anchor(trigger_agent="worf")))
            await mem.store(_make_episode(
                user_input="echo report",
                anchors=_anchor(trigger_agent="echo")))
            results = await mem.recall_by_anchor(trigger_agent="worf")
            assert len(results) == 1
            assert results[0].anchors.trigger_agent == "worf"
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_activation_tracking(self, tmp_path):
        mem = EpisodicMemory(
            db_path=tmp_path / "track.db", max_episodes=100, relevance_threshold=0.0
        )
        await mem.start()
        try:
            tracker = AsyncMock()
            mem._activation_tracker = tracker
            await mem.store(_make_episode(
                user_input="tracked episode",
                anchors=_anchor(department="engineering")))
            results = await mem.recall_by_anchor(department="engineering")
            assert len(results) == 1
            tracker.record_batch_access.assert_awaited_once()
            call_args = tracker.record_batch_access.call_args
            assert results[0].id in call_args[0][0]
            assert call_args[1]["access_type"] == "recall"
        finally:
            await mem.stop()
