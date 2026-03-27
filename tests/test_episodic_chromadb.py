"""Tests for EpisodicMemory ChromaDB backend (Phase 14b)."""

from __future__ import annotations

import time

import pytest

from probos.types import Episode


def _make_episode(
    id_: str = "test1",
    user_input: str = "read config file",
    intent: str = "read_file",
    ts: float = 0.0,
    success: bool = True,
) -> Episode:
    return Episode(
        id=id_,
        user_input=user_input,
        timestamp=ts or time.time(),
        dag_summary={"intents": 1},
        outcomes=[{"intent": intent, "success": success}],
        agent_ids=["a1"],
        duration_ms=50.0,
    )


class TestEpisodicMemoryChromaDB:
    """Tests for ChromaDB-backed EpisodicMemory."""

    @pytest.fixture
    async def mem(self, tmp_path):
        from probos.cognitive.episodic import EpisodicMemory
        db = tmp_path / "episodic.db"
        m = EpisodicMemory(db_path=str(db), max_episodes=100, relevance_threshold=0.3)
        await m.start()
        yield m
        await m.stop()

    @pytest.mark.asyncio
    async def test_store_and_recall_single(self, mem):
        """Store and recall a single episode via semantic similarity."""
        ep = _make_episode("s1", "read the configuration file")
        await mem.store(ep)

        results = await mem.recall("configuration", k=5)
        assert len(results) >= 1
        assert results[0].id == "s1"

    @pytest.mark.asyncio
    async def test_recall_returns_ranked_results(self, mem):
        """Multiple episodes are ranked by semantic similarity."""
        await mem.store(_make_episode("r1", "read the project configuration file"))
        await mem.store(_make_episode("r2", "deploy to production server"))
        await mem.store(_make_episode("r3", "update the YAML config settings"))

        results = await mem.recall("configuration settings", k=5)
        assert len(results) >= 1
        # Config-related episodes should rank higher than deploy
        result_ids = [r.id for r in results]
        assert "r1" in result_ids or "r3" in result_ids

    @pytest.mark.asyncio
    async def test_semantic_recall_deployment_matches_production(self, mem):
        """Semantic recall: 'deployment' query matches 'push to production' episode."""
        await mem.store(_make_episode("sem1", "push the application to production"))
        await mem.store(_make_episode("sem2", "bake a chocolate cake recipe"))

        results = await mem.recall("deployment", k=5)
        # Production should match deployment semantically
        result_ids = [r.id for r in results]
        if len(results) > 0:
            # The production episode should rank higher than cake
            prod_idx = result_ids.index("sem1") if "sem1" in result_ids else 999
            cake_idx = result_ids.index("sem2") if "sem2" in result_ids else 999
            assert prod_idx < cake_idx or "sem2" not in result_ids

    @pytest.mark.asyncio
    async def test_recall_by_intent_filters(self, mem):
        """recall_by_intent filters correctly by metadata."""
        await mem.store(_make_episode("i1", "read file test.txt", intent="read_file"))
        await mem.store(_make_episode("i2", "write file output.txt", intent="write_file"))

        results = await mem.recall_by_intent("read_file", k=5)
        assert len(results) == 1
        assert results[0].id == "i1"

    @pytest.mark.asyncio
    async def test_recent_returns_most_recent_first(self, mem):
        """recent() returns most recent first by timestamp."""
        await mem.store(_make_episode("t1", "first task", ts=100.0))
        await mem.store(_make_episode("t2", "second task", ts=200.0))
        await mem.store(_make_episode("t3", "third task", ts=300.0))

        results = await mem.recent(k=3)
        assert len(results) == 3
        assert results[0].id == "t3"
        assert results[1].id == "t2"
        assert results[2].id == "t1"

    @pytest.mark.asyncio
    async def test_get_stats_returns_counts(self, mem):
        """get_stats returns correct counts."""
        await mem.store(_make_episode("st1", "read file"))
        await mem.store(_make_episode("st2", "write file", intent="write_file"))

        stats = await mem.get_stats()
        assert stats["total"] == 2
        assert "intent_distribution" in stats
        assert "avg_success_rate" in stats

    @pytest.mark.asyncio
    async def test_max_episodes_eviction(self, tmp_path):
        """max_episodes eviction removes oldest."""
        from probos.cognitive.episodic import EpisodicMemory
        db = tmp_path / "evict.db"
        m = EpisodicMemory(db_path=str(db), max_episodes=3, relevance_threshold=0.1)
        await m.start()
        try:
            for i in range(5):
                await m.store(_make_episode(f"ev{i}", f"task number {i}", ts=float(i + 1)))

            # Should have at most 3 episodes
            recent = await m.recent(k=10)
            assert len(recent) <= 3
            # Oldest should have been evicted
            ids = [r.id for r in recent]
            assert "ev0" not in ids
            assert "ev1" not in ids
        finally:
            await m.stop()

    @pytest.mark.asyncio
    async def test_seed_bulk_loads(self, mem):
        """seed() bulk loads episodes for warm boot."""
        episodes = [
            _make_episode("seed1", "first seeded task", ts=100.0),
            _make_episode("seed2", "second seeded task", ts=200.0),
        ]
        count = await mem.seed(episodes)
        assert count == 2

        recent = await mem.recent(k=10)
        assert len(recent) == 2
        ids = {r.id for r in recent}
        assert "seed1" in ids
        assert "seed2" in ids

    @pytest.mark.asyncio
    async def test_seed_skips_duplicate_ids(self, mem):
        """seed() skips episodes with IDs that already exist."""
        await mem.store(_make_episode("dup1", "existing episode"))

        episodes = [
            _make_episode("dup1", "should be skipped"),
            _make_episode("dup2", "new episode"),
        ]
        count = await mem.seed(episodes)
        assert count == 1  # Only dup2 was new

        recent = await mem.recent(k=10)
        assert len(recent) == 2

    @pytest.mark.asyncio
    async def test_episode_roundtrip(self, mem):
        """All Episode fields survive store → recent round-trip."""
        ep = Episode(
            id="rt1",
            user_input="roundtrip test input",
            timestamp=12345.678,
            dag_summary={"node_count": 3, "intents": ["read_file"]},
            outcomes=[{"intent": "read_file", "success": True, "status": "completed"}],
            reflection="test reflection text",
            agent_ids=["agent_a", "agent_b"],
            duration_ms=42.5,
        )
        await mem.store(ep)

        results = await mem.recent(k=1)
        assert len(results) == 1
        r = results[0]
        assert r.id == "rt1"
        assert r.user_input == "roundtrip test input"
        assert abs(r.timestamp - 12345.678) < 0.001
        assert r.dag_summary == {"node_count": 3, "intents": ["read_file"]}
        assert r.outcomes == [{"intent": "read_file", "success": True, "status": "completed"}]
        assert r.reflection == "test reflection text"
        assert r.agent_ids == ["agent_a", "agent_b"]
        assert r.duration_ms == 42.5

    @pytest.mark.asyncio
    async def test_empty_collection_returns_empty(self, mem):
        """Empty collection returns empty results for all query types."""
        assert await mem.recall("anything", k=5) == []
        assert await mem.recall_by_intent("read_file", k=5) == []
        assert await mem.recent(k=10) == []
        stats = await mem.get_stats()
        assert stats["total"] == 0


# ---------------------------------------------------------------------------
# BF-039: Rate Limiting & Content Deduplication
# ---------------------------------------------------------------------------


class TestEpisodicRateLimiting:
    """BF-039: Per-agent episode rate limiting."""

    @pytest.fixture
    async def mem(self, tmp_path):
        from probos.cognitive.episodic import EpisodicMemory
        db = tmp_path / "rl.db"
        m = EpisodicMemory(db_path=str(db), max_episodes=1000, relevance_threshold=0.3)
        await m.start()
        yield m
        await m.stop()

    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_excess_episodes(self, mem):
        """Store MAX+1 episodes for the same agent — last one rejected."""
        for i in range(mem.MAX_EPISODES_PER_HOUR):
            ep = _make_episode(f"rl-{i}", f"task number {i} unique content", ts=time.time())
            await mem.store(ep)

        # One more should be rate-limited
        excess = _make_episode("rl-excess", "one too many tasks", ts=time.time())
        await mem.store(excess)

        recent = await mem.recent(k=100)
        ids = {r.id for r in recent}
        assert "rl-excess" not in ids
        assert len(recent) == mem.MAX_EPISODES_PER_HOUR

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_different_agents(self, mem):
        """Store MAX episodes for agent A, then one for agent B — B accepted."""
        for i in range(mem.MAX_EPISODES_PER_HOUR):
            ep = Episode(
                id=f"a-{i}", user_input=f"agent A task {i}", timestamp=time.time(),
                agent_ids=["agent_a"], outcomes=[{"intent": "test", "success": True}],
            )
            await mem.store(ep)

        ep_b = Episode(
            id="b-0", user_input="agent B task", timestamp=time.time(),
            agent_ids=["agent_b"], outcomes=[{"intent": "test", "success": True}],
        )
        await mem.store(ep_b)

        recent = await mem.recent(k=100)
        ids = {r.id for r in recent}
        assert "b-0" in ids

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_after_window(self, tmp_path):
        """Episodes with old timestamps don't count against the rate limit."""
        from probos.cognitive.episodic import EpisodicMemory
        db = tmp_path / "rl_window.db"
        m = EpisodicMemory(db_path=str(db), max_episodes=1000, relevance_threshold=0.3)
        await m.start()
        try:
            old_ts = time.time() - 7200  # 2 hours ago
            for i in range(m.MAX_EPISODES_PER_HOUR):
                ep = _make_episode(f"old-{i}", f"old task {i}", ts=old_ts)
                await m.store(ep)

            new_ep = _make_episode("new-0", "new task just now", ts=time.time())
            await m.store(new_ep)

            recent = await m.recent(k=100)
            ids = {r.id for r in recent}
            assert "new-0" in ids
        finally:
            await m.stop()


class TestEpisodicContentDedup:
    """BF-039: Content similarity deduplication."""

    @pytest.fixture
    async def mem(self, tmp_path):
        from probos.cognitive.episodic import EpisodicMemory
        db = tmp_path / "dedup.db"
        m = EpisodicMemory(db_path=str(db), max_episodes=1000, relevance_threshold=0.3)
        await m.start()
        yield m
        await m.stop()

    @pytest.mark.asyncio
    async def test_content_similarity_dedup(self, mem):
        """Near-identical episode for same agent within window is rejected."""
        ep1 = Episode(
            id="dup-1",
            user_input="the quick brown fox jumps over the lazy dog in the park near home",
            timestamp=time.time(), agent_ids=["agent_a"],
            outcomes=[{"intent": "test", "success": True}],
        )
        await mem.store(ep1)

        # Nearly identical text — only 1 word different out of many (>0.9 Jaccard)
        ep2 = Episode(
            id="dup-2",
            user_input="the quick brown fox jumps over the lazy cat in the park near home",
            timestamp=time.time(), agent_ids=["agent_a"],
            outcomes=[{"intent": "test", "success": True}],
        )
        await mem.store(ep2)

        recent = await mem.recent(k=10)
        ids = {r.id for r in recent}
        assert "dup-1" in ids
        assert "dup-2" not in ids

    @pytest.mark.asyncio
    async def test_content_similarity_allows_different_content(self, mem):
        """Substantially different episode is accepted."""
        ep1 = Episode(
            id="diff-1", user_input="the quick brown fox jumps over the lazy dog",
            timestamp=time.time(), agent_ids=["agent_a"],
            outcomes=[{"intent": "test", "success": True}],
        )
        await mem.store(ep1)

        ep2 = Episode(
            id="diff-2", user_input="deploy kubernetes cluster to production environment",
            timestamp=time.time(), agent_ids=["agent_a"],
            outcomes=[{"intent": "deploy", "success": True}],
        )
        await mem.store(ep2)

        recent = await mem.recent(k=10)
        ids = {r.id for r in recent}
        assert "diff-1" in ids
        assert "diff-2" in ids

    @pytest.mark.asyncio
    async def test_content_similarity_allows_different_agent(self, mem):
        """Identical text for different agent is accepted."""
        text = "the quick brown fox jumps over the lazy dog"
        ep1 = Episode(
            id="agent-a", user_input=text,
            timestamp=time.time(), agent_ids=["agent_a"],
            outcomes=[{"intent": "test", "success": True}],
        )
        await mem.store(ep1)

        ep2 = Episode(
            id="agent-b", user_input=text,
            timestamp=time.time(), agent_ids=["agent_b"],
            outcomes=[{"intent": "test", "success": True}],
        )
        await mem.store(ep2)

        recent = await mem.recent(k=10)
        ids = {r.id for r in recent}
        assert "agent-a" in ids
        assert "agent-b" in ids


class TestCountForAgentDedup:
    """BF-039: Verify count_for_agent works after duplicate removal."""

    @pytest.fixture
    async def mem(self, tmp_path):
        from probos.cognitive.episodic import EpisodicMemory
        db = tmp_path / "count.db"
        m = EpisodicMemory(db_path=str(db), max_episodes=1000, relevance_threshold=0.3)
        await m.start()
        yield m
        await m.stop()

    @pytest.mark.asyncio
    async def test_count_for_agent_single_definition(self, mem):
        """count_for_agent works correctly after dedup removal."""
        for i in range(3):
            ep = Episode(
                id=f"cnt-{i}", user_input=f"task {i} for counting", timestamp=time.time(),
                agent_ids=["counter_agent"], outcomes=[{"intent": "test", "success": True}],
            )
            await mem.store(ep)

        count = await mem.count_for_agent("counter_agent")
        assert count == 3

        # Different agent has 0
        assert await mem.count_for_agent("other_agent") == 0
