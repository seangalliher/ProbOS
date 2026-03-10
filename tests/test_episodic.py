"""Tests for episodic memory — store, recall, stats, eviction."""

import time

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.embeddings import _keyword_embedding, _keyword_similarity
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.types import Episode


# ---------------------------------------------------------------------------
# Unit tests — MockEpisodicMemory (fast, in-memory)
# ---------------------------------------------------------------------------


class TestMockEpisodicMemory:
    @pytest.fixture
    def mem(self):
        return MockEpisodicMemory(max_episodes=100, relevance_threshold=0.3)

    @pytest.mark.asyncio
    async def test_store_and_recall_single(self, mem):
        ep = Episode(
            timestamp=time.time(),
            user_input="read the file at /tmp/test.txt",
            outcomes=[{"intent": "read_file", "success": True}],
            agent_ids=["agent1"],
            duration_ms=50.0,
        )
        await mem.store(ep)
        results = await mem.recall("read a file", k=5)
        assert len(results) == 1
        assert results[0].id == ep.id

    @pytest.mark.asyncio
    async def test_store_multiple_recall_ranked(self, mem):
        ep1 = Episode(
            timestamp=1.0,
            user_input="read the file at /tmp/a.txt",
            outcomes=[{"intent": "read_file", "success": True}],
        )
        ep2 = Episode(
            timestamp=2.0,
            user_input="list the directory /tmp",
            outcomes=[{"intent": "list_directory", "success": True}],
        )
        ep3 = Episode(
            timestamp=3.0,
            user_input="read the file at /tmp/b.txt",
            outcomes=[{"intent": "read_file", "success": True}],
        )
        await mem.store(ep1)
        await mem.store(ep2)
        await mem.store(ep3)

        results = await mem.recall("read file", k=5)
        # Both read episodes should match; list_directory might not
        assert len(results) >= 1
        user_inputs = [r.user_input for r in results]
        assert any("read" in inp for inp in user_inputs)

    @pytest.mark.asyncio
    async def test_recall_no_matches(self, mem):
        ep = Episode(
            timestamp=1.0,
            user_input="read the file at /tmp/test.txt",
            outcomes=[{"intent": "read_file", "success": True}],
        )
        await mem.store(ep)
        results = await mem.recall("completely unrelated xyz query", k=5)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_recall_by_intent_filters(self, mem):
        ep1 = Episode(
            timestamp=1.0,
            user_input="read /tmp/a.txt",
            outcomes=[{"intent": "read_file", "success": True}],
        )
        ep2 = Episode(
            timestamp=2.0,
            user_input="list /tmp",
            outcomes=[{"intent": "list_directory", "success": True}],
        )
        await mem.store(ep1)
        await mem.store(ep2)

        results = await mem.recall_by_intent("read_file", k=5)
        assert len(results) == 1
        assert results[0].user_input == "read /tmp/a.txt"

    @pytest.mark.asyncio
    async def test_get_stats(self, mem):
        for i in range(5):
            ep = Episode(
                timestamp=float(i),
                user_input=f"read file {i}",
                outcomes=[{"intent": "read_file", "success": i % 2 == 0}],
                agent_ids=["agent1"],
            )
            await mem.store(ep)

        stats = await mem.get_stats()
        assert stats["total"] == 5
        assert "read_file" in stats["intent_distribution"]
        assert stats["intent_distribution"]["read_file"] == 5
        assert stats["avg_success_rate"] == 3 / 5  # 0, 2, 4 succeed
        assert "agent1" in stats["most_used_agents"]

    @pytest.mark.asyncio
    async def test_max_episodes_eviction(self):
        mem = MockEpisodicMemory(max_episodes=3, relevance_threshold=0.3)
        for i in range(5):
            ep = Episode(
                timestamp=float(i),
                user_input=f"operation {i}",
                outcomes=[{"intent": "read_file", "success": True}],
            )
            await mem.store(ep)

        # Should have evicted oldest, keeping only 3
        recent = await mem.recent(k=10)
        assert len(recent) == 3
        # Oldest surviving should be operation 2
        inputs = [r.user_input for r in recent]
        assert "operation 2" in inputs
        assert "operation 0" not in inputs

    @pytest.mark.asyncio
    async def test_recent_returns_most_recent_first(self, mem):
        for i in range(5):
            ep = Episode(timestamp=float(i), user_input=f"op {i}")
            await mem.store(ep)

        recent = await mem.recent(k=3)
        assert len(recent) == 3
        assert recent[0].user_input == "op 4"
        assert recent[1].user_input == "op 3"
        assert recent[2].user_input == "op 2"


# ---------------------------------------------------------------------------
# Unit tests — EpisodicMemory (SQLite-backed)
# ---------------------------------------------------------------------------


class TestEpisodicMemoryChromaDBLegacy:
    @pytest.fixture
    async def mem(self, tmp_path):
        m = EpisodicMemory(
            db_path=tmp_path / "episodes.db",
            max_episodes=100,
            relevance_threshold=0.3,
        )
        await m.start()
        yield m
        await m.stop()

    @pytest.mark.asyncio
    async def test_store_and_recall(self, mem):
        ep = Episode(
            timestamp=time.time(),
            user_input="read the file at /tmp/test.txt",
            outcomes=[{"intent": "read_file", "success": True}],
            agent_ids=["agent1"],
            duration_ms=42.0,
        )
        await mem.store(ep)
        results = await mem.recall("read file", k=5)
        assert len(results) >= 1
        assert results[0].id == ep.id
        assert results[0].duration_ms == 42.0

    @pytest.mark.asyncio
    async def test_recall_by_intent(self, mem):
        ep1 = Episode(
            timestamp=1.0,
            user_input="read /tmp/a.txt",
            outcomes=[{"intent": "read_file", "success": True}],
        )
        ep2 = Episode(
            timestamp=2.0,
            user_input="list /tmp",
            outcomes=[{"intent": "list_directory", "success": True}],
        )
        await mem.store(ep1)
        await mem.store(ep2)

        results = await mem.recall_by_intent("list_directory")
        assert len(results) == 1
        assert results[0].user_input == "list /tmp"

    @pytest.mark.asyncio
    async def test_get_stats_empty(self, mem):
        stats = await mem.get_stats()
        assert stats["total"] == 0

    @pytest.mark.asyncio
    async def test_eviction(self, tmp_path):
        m = EpisodicMemory(
            db_path=tmp_path / "evict.db",
            max_episodes=3,
            relevance_threshold=0.3,
        )
        await m.start()
        try:
            for i in range(5):
                ep = Episode(timestamp=float(i), user_input=f"op {i}",
                             outcomes=[{"intent": "read_file", "success": True}])
                await m.store(ep)
            recent = await m.recent(k=10)
            assert len(recent) == 3
        finally:
            await m.stop()

    @pytest.mark.asyncio
    async def test_episode_round_trip(self, mem):
        """Episode fields survive store → recall."""
        ep = Episode(
            timestamp=123.456,
            user_input="fetch https://example.com",
            dag_summary={"node_count": 1, "intent_types": ["http_fetch"]},
            outcomes=[{"intent": "http_fetch", "success": True}],
            reflection="The page returned 200 OK.",
            agent_ids=["agent_a", "agent_b"],
            duration_ms=99.5,
        )
        await mem.store(ep)
        results = await mem.recall("fetch", k=1)
        assert len(results) == 1
        r = results[0]
        assert r.user_input == "fetch https://example.com"
        assert r.dag_summary["node_count"] == 1
        assert r.reflection == "The page returned 200 OK."
        assert r.agent_ids == ["agent_a", "agent_b"]
        assert r.duration_ms == 99.5


# ---------------------------------------------------------------------------
# Keyword embedding tests
# ---------------------------------------------------------------------------


class TestKeywordEmbedding:
    def test_embedding_non_empty(self):
        emb = _keyword_embedding("read the file at /tmp/test.txt")
        assert len(emb) > 0

    def test_similarity_identical(self):
        emb = _keyword_embedding("read the file")
        score = _keyword_similarity(emb, emb)
        assert score == pytest.approx(1.0, abs=0.001)

    def test_similarity_different(self):
        a = _keyword_embedding("read the file at /tmp/test.txt")
        b = _keyword_embedding("completely unrelated banana query")
        score = _keyword_similarity(a, b)
        assert score < 0.5

    def test_similarity_empty(self):
        assert _keyword_similarity([], []) == 0.0
