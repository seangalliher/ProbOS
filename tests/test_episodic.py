"""Tests for episodic memory — store, recall, stats, eviction."""

import asyncio
import dataclasses
import logging
import re
import time

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.knowledge.embeddings import _keyword_embedding, _keyword_similarity
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.types import (
    AnchorFrame,
    Episode,
    EpisodeDuplicatePolicy,
    EpisodeStoreOutcome,
    MemorySource,
)


def _reflection_episode(*, timestamp: float = 1.0) -> Episode:
    import hashlib

    text = "[Reflection] canonical mock replay"
    return Episode(
        id=f"reflection-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}",
        timestamp=timestamp,
        user_input=text,
        dag_summary={
            "type": "reflection",
            "source": "dream_consolidation",
            "involved_agents": [],
        },
        outcomes=[],
        reflection=text,
        duration_ms=0.0,
        shapley_values={},
        trust_deltas=[],
        source=MemorySource.REFLECTION,
        anchors=AnchorFrame(trigger_type="dream_consolidation"),
    )


def _store_start_barrier(expected: int):
    started = 0
    all_started = asyncio.Event()

    async def _run(store_call):
        nonlocal started
        started += 1
        if started == expected:
            all_started.set()
        return await store_call

    return _run, all_started


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

    @pytest.mark.asyncio
    async def test_store_repeated_id_preserves_first_and_returns_typed_outcomes(
        self, mem
    ):
        """BF-669: canonical mock is write-once and outcome-aware."""
        first = Episode(id="same-id", timestamp=1.0, user_input="authoritative")
        replay = Episode(id="same-id", timestamp=2.0, user_input="replacement")

        first_outcome = await mem.store(first)
        replay_outcome = await mem.store(replay)

        assert [episode.id for episode in mem._episodes] == ["same-id"]
        assert mem._episodes[0].user_input == "authoritative"
        assert getattr(first_outcome, "value", None) == "stored"
        assert getattr(replay_outcome, "value", None) == "duplicate"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_policy", ["unexpected", True, object()])
    async def test_store_raw_policy_rejected_before_mutation(
        self, mem, invalid_policy
    ):
        episode = Episode(id="raw-policy", user_input="never stored")

        with pytest.raises(TypeError, match="EpisodeDuplicatePolicy"):
            await mem.store(
                episode, duplicate_policy=invalid_policy  # type: ignore[arg-type]
            )

        assert mem._episodes == []

    def test_new_constructed_mock_gets_one_stable_lazy_store_lock(self):
        mem = MockEpisodicMemory.__new__(MockEpisodicMemory)

        first = mem._get_store_write_lock()
        second = mem._get_store_write_lock()

        assert isinstance(first, asyncio.Lock)
        assert second is first

    @pytest.mark.asyncio
    async def test_store_expected_reflection_replay_debug_only(self, mem, caplog):
        first = _reflection_episode(timestamp=1.0)
        replay = dataclasses.replace(first, timestamp=2.0)

        assert await mem.store(first) is EpisodeStoreOutcome.STORED
        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.episodic_mock"):
            outcome = await mem.store(
                replay,
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            )

        assert outcome is EpisodeStoreOutcome.DUPLICATE
        assert len(mem._episodes) == 1
        assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
        assert "equivalence=timestamp_neutral" in caplog.text
        assert first.id in caplog.text

    @pytest.mark.asyncio
    async def test_store_expected_conflict_warns_and_preserves_first(self, mem, caplog):
        from probos.cognitive.episodic import compute_episode_hash

        first = _reflection_episode(timestamp=1.0)
        conflict = dataclasses.replace(first, agent_ids=["changed-agent"])
        await mem.store(first)

        with caplog.at_level(logging.WARNING, logger="probos.cognitive.episodic_mock"):
            outcome = await mem.store(
                conflict,
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            )

        assert outcome is EpisodeStoreOutcome.DUPLICATE
        assert mem._episodes == [first]
        warnings = [
            record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        warning = warnings[0]
        incoming_prefix = compute_episode_hash(conflict)[:12]
        existing_prefix = compute_episode_hash(first)[:12]
        assert len(incoming_prefix) == len(existing_prefix) == 12
        assert "reason=content_conflict" in warning
        assert first.id in warning
        hash_match = re.search(
            r"incoming_hash=([0-9a-f]{12}) existing_hash=([0-9a-f]{12});",
            warning,
        )
        assert hash_match is not None
        assert hash_match.groups() == (incoming_prefix, existing_prefix)
        assert "existing write remains authoritative" in warning
        assert first.user_input not in warning
        assert first.reflection not in warning

    @pytest.mark.asyncio
    async def test_store_concurrent_replay_one_stored_one_duplicate(self, mem):
        first = _reflection_episode(timestamp=1.0)
        replay = dataclasses.replace(first, timestamp=2.0)
        lock = mem._get_store_write_lock()
        await lock.acquire()
        run_store, all_started = _store_start_barrier(2)
        first_task = asyncio.create_task(
            run_store(mem.store(
                first,
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            ))
        )
        replay_task = asyncio.create_task(
            run_store(mem.store(
                replay,
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            ))
        )
        await all_started.wait()
        assert not first_task.done()
        assert not replay_task.done()
        lock.release()

        outcomes = await asyncio.gather(first_task, replay_task)

        assert sorted(outcome.value for outcome in outcomes) == ["duplicate", "stored"]
        assert len(mem._episodes) == 1

    @pytest.mark.asyncio
    async def test_duplicate_at_capacity_does_not_evict_another_episode(self):
        mem = MockEpisodicMemory(max_episodes=2)
        first = Episode(id="first", user_input="first")
        second = Episode(id="second", user_input="second")
        await mem.store(first)
        await mem.store(second)

        outcome = await mem.store(
            dataclasses.replace(first, user_input="conflict")
        )

        assert outcome is EpisodeStoreOutcome.DUPLICATE
        assert mem._episodes == [first, second]


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
