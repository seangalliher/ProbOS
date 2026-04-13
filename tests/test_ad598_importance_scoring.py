"""AD-598: Importance Scoring at Encoding — rule-based 1-10 scoring."""

from __future__ import annotations

import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.types import AnchorFrame, Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    *,
    user_input: str = "test input",
    anchors: AnchorFrame | None = None,
    importance: int = 5,
    outcomes: list | None = None,
) -> Episode:
    return Episode(
        id="ep-001",
        user_input=user_input,
        timestamp=time.time(),
        agent_ids=["agent-001"],
        source="direct",
        anchors=anchors,
        outcomes=outcomes or [{"intent": "test_intent", "success": True, "response": "done"}],
        importance=importance,
    )


def _anchor(*, trigger_type: str = "", department: str = "", **kw) -> AnchorFrame:
    return AnchorFrame(trigger_type=trigger_type, department=department, **kw)


# ---------------------------------------------------------------------------
# TestComputeImportance — 7 tests
# ---------------------------------------------------------------------------

class TestComputeImportance:
    """Tests for compute_importance() heuristic scoring."""

    def test_default_neutral(self):
        """Test 1: Episode with no signals → importance 5."""
        from probos.cognitive.importance_scorer import compute_importance

        ep = _make_episode()
        assert compute_importance(ep) == 5

    def test_captain_dm_high(self):
        """Test 2: Episode with trigger_type='captain_dm' → importance 8."""
        from probos.cognitive.importance_scorer import compute_importance

        ep = _make_episode(anchors=_anchor(trigger_type="captain_dm"))
        assert compute_importance(ep) == 8

    def test_circuit_breaker_critical(self):
        """Test 3: trigger_type='circuit_breaker_trip' → importance 9."""
        from probos.cognitive.importance_scorer import compute_importance

        ep = _make_episode(anchors=_anchor(trigger_type="circuit_breaker_trip"))
        assert compute_importance(ep) == 9

    def test_failure_boost(self):
        """Test 4: Episode with success=False outcome → importance >= 7."""
        from probos.cognitive.importance_scorer import compute_importance

        ep = _make_episode(
            outcomes=[{"intent": "test", "success": False, "response": "error occurred"}],
        )
        assert compute_importance(ep) >= 7

    def test_proactive_low(self):
        """Test 5: trigger_type='proactive_thought' → importance 3."""
        from probos.cognitive.importance_scorer import compute_importance

        ep = _make_episode(anchors=_anchor(trigger_type="proactive_thought"))
        # proactive_thought maps to 3, but outcomes with real response won't degrade
        assert compute_importance(ep) == 3

    def test_no_response_degrades(self):
        """Test 6: Outcomes with only [NO_RESPONSE] → importance <= 3."""
        from probos.cognitive.importance_scorer import compute_importance

        ep = _make_episode(
            outcomes=[{"intent": "test", "success": True, "response": "[NO_RESPONSE]"}],
        )
        assert compute_importance(ep) <= 3

    def test_captain_content_boost(self):
        """Test 7: '[1:1 with' in user_input → importance >= 8."""
        from probos.cognitive.importance_scorer import compute_importance

        ep = _make_episode(user_input="[1:1 with Captain]: discussed crew rotation")
        assert compute_importance(ep) >= 8


# ---------------------------------------------------------------------------
# TestStoreImportance — 3 tests
# ---------------------------------------------------------------------------

class TestStoreImportance:
    """Tests that store() wires importance into ChromaDB metadata."""

    @pytest.mark.asyncio
    async def test_store_writes_importance_metadata(self):
        """Test 8: After store(), ChromaDB metadata contains importance field."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._activation_tracker = None
        em._query_reformulation_enabled = False
        em.max_episodes = 1000

        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_collection.get.return_value = {"ids": []}
        em._collection = mock_collection
        em._fts_db = None
        em._participant_index = None
        em._eviction_audit = None

        ep = _make_episode(
            anchors=_anchor(trigger_type="captain_dm"),
        )
        await em.store(ep)

        call_args = mock_collection.add.call_args
        meta = call_args.kwargs.get("metadatas") or call_args[1].get("metadatas")
        assert meta is not None
        assert "importance" in meta[0]
        assert meta[0]["importance"] == 8  # captain_dm → 8

    @pytest.mark.asyncio
    async def test_store_default_importance(self):
        """Test 9: Episode without signals stores importance=5."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._activation_tracker = None
        em._query_reformulation_enabled = False
        em.max_episodes = 1000

        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_collection.get.return_value = {"ids": []}
        em._collection = mock_collection
        em._fts_db = None
        em._participant_index = None
        em._eviction_audit = None

        ep = _make_episode()
        await em.store(ep)

        call_args = mock_collection.add.call_args
        meta = call_args.kwargs.get("metadatas") or call_args[1].get("metadatas")
        assert meta[0]["importance"] == 5

    @pytest.mark.asyncio
    async def test_roundtrip_preserves_importance(self):
        """Test 10: store() → _metadata_to_episode() roundtrip preserves importance."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(
            anchors=_anchor(trigger_type="circuit_breaker_trip"),
        )
        # Simulate the scoring that happens in store()
        from probos.cognitive.importance_scorer import compute_importance
        scored_importance = compute_importance(ep)
        ep_scored = Episode(
            id=ep.id, timestamp=ep.timestamp, user_input=ep.user_input,
            dag_summary=ep.dag_summary, outcomes=ep.outcomes, reflection=ep.reflection,
            agent_ids=ep.agent_ids, duration_ms=ep.duration_ms, embedding=ep.embedding,
            shapley_values=ep.shapley_values, trust_deltas=ep.trust_deltas,
            source=ep.source, anchors=ep.anchors, importance=scored_importance,
        )

        metadata = EpisodicMemory._episode_to_metadata(ep_scored)
        doc = EpisodicMemory._prepare_document(ep_scored)
        restored = EpisodicMemory._metadata_to_episode(ep.id, doc, metadata)
        assert restored.importance == scored_importance


# ---------------------------------------------------------------------------
# TestMetadataRoundTrip — 2 tests
# ---------------------------------------------------------------------------

class TestMetadataRoundTrip:
    """Tests for importance in _episode_to_metadata / _metadata_to_episode."""

    def test_episode_to_metadata_includes_importance(self):
        """Test 11: _episode_to_metadata() produces importance key."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(importance=7)
        metadata = EpisodicMemory._episode_to_metadata(ep)
        assert "importance" in metadata
        assert metadata["importance"] == 7

    def test_metadata_to_episode_reads_importance(self):
        """Test 12: _metadata_to_episode() with importance=8 → ep.importance == 8."""
        from probos.cognitive.episodic import EpisodicMemory

        metadata = {
            "timestamp": time.time(),
            "user_input": "test",
            "intent_type": "",
            "dag_summary_json": "{}",
            "outcomes_json": "[]",
            "reflection": "",
            "agent_ids_json": '["agent-001"]',
            "duration_ms": 0.0,
            "shapley_values_json": "{}",
            "trust_deltas_json": "[]",
            "source": "direct",
            "anchors_json": "",
            "importance": 8,
        }
        ep = EpisodicMemory._metadata_to_episode("ep-001", "test", metadata)
        assert ep.importance == 8


# ---------------------------------------------------------------------------
# TestActivationWithImportance — 3 tests
# ---------------------------------------------------------------------------

class TestActivationWithImportance:
    """Tests for compute_activation_with_importance and importance-adjusted pruning."""

    def test_high_importance_slower_decay(self):
        """Test 13: importance=10 activation > importance=5 for same access times."""
        from probos.cognitive.activation_tracker import ActivationTracker

        tracker = ActivationTracker.__new__(ActivationTracker)
        tracker._decay_d = 0.5
        tracker._db = None

        now = time.time()
        access_times = [now - 3600]  # 1 hour ago

        act_5 = tracker.compute_activation_with_importance(access_times, importance=5, now=now)
        act_10 = tracker.compute_activation_with_importance(access_times, importance=10, now=now)

        assert act_10 > act_5, "importance=10 should decay slower (higher activation)"

    def test_low_importance_faster_decay(self):
        """Test 14: importance=1 activation < importance=5 for same access times."""
        from probos.cognitive.activation_tracker import ActivationTracker

        tracker = ActivationTracker.__new__(ActivationTracker)
        tracker._decay_d = 0.5
        tracker._db = None

        now = time.time()
        access_times = [now - 3600]

        act_5 = tracker.compute_activation_with_importance(access_times, importance=5, now=now)
        act_1 = tracker.compute_activation_with_importance(access_times, importance=1, now=now)

        assert act_1 < act_5, "importance=1 should decay faster (lower activation)"

    @pytest.mark.asyncio
    async def test_importance_adjusted_pruning_threshold(self):
        """Test 15: importance=9 episode survives threshold that prunes importance=3."""
        from probos.cognitive.activation_tracker import ActivationTracker

        tracker = ActivationTracker.__new__(ActivationTracker)
        tracker._decay_d = 0.5
        tracker._db = MagicMock()

        now = time.time()
        # Both episodes have same low activation
        async def mock_batch(episode_ids):
            return {
                "ep-high": -2.5,  # below base threshold of -2.0
                "ep-low": -2.5,
            }

        tracker.get_activations_batch = mock_batch

        importance_map = {"ep-high": 9, "ep-low": 3}
        # threshold=-2.0:
        #   ep-high (importance=9): adjusted_threshold = -2.0 - (9-5)*0.2 = -2.8 → -2.5 > -2.8 → survives
        #   ep-low  (importance=3): adjusted_threshold = -2.0 - (3-5)*0.2 = -1.6 → -2.5 < -1.6 → pruned
        pruned = await tracker.find_low_activation_episodes_with_importance(
            all_episode_ids=["ep-high", "ep-low"],
            importance_map=importance_map,
            threshold=-2.0,
            max_prune_fraction=1.0,
        )

        assert "ep-low" in pruned
        assert "ep-high" not in pruned


# ---------------------------------------------------------------------------
# TestScoreRecallImportance — 2 tests
# ---------------------------------------------------------------------------

class TestScoreRecallImportance:
    """Tests for importance channel in score_recall()."""

    def test_importance_weight_zero_no_effect(self):
        """Test 16: Default importance_weight=0.0 → no composite change."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(importance=9)
        rs_no = EpisodicMemory.score_recall(
            episode=ep, semantic_similarity=0.5,
            importance=9, importance_weight=0.0,
        )
        rs_baseline = EpisodicMemory.score_recall(
            episode=ep, semantic_similarity=0.5,
        )
        assert rs_no.composite_score == rs_baseline.composite_score

    def test_importance_weight_boosts_high(self):
        """Test 17: importance=9 with weight=0.05 → higher composite than importance=2."""
        from probos.cognitive.episodic import EpisodicMemory

        ep_high = _make_episode(importance=9)
        ep_low = _make_episode(importance=2)

        rs_high = EpisodicMemory.score_recall(
            episode=ep_high, semantic_similarity=0.5,
            importance=9, importance_weight=0.05,
        )
        rs_low = EpisodicMemory.score_recall(
            episode=ep_low, semantic_similarity=0.5,
            importance=2, importance_weight=0.05,
        )
        assert rs_high.composite_score > rs_low.composite_score


# ---------------------------------------------------------------------------
# TestDreamPruningIntegration — 2 tests
# ---------------------------------------------------------------------------

class TestDreamPruningIntegration:
    """Tests for _get_importance_map() helper in DreamingEngine."""

    @pytest.mark.asyncio
    async def test_get_importance_map_reads_metadata(self):
        """Test 18: Mock ChromaDB returns importance in metadata → map correct."""
        from probos.cognitive.dreaming import DreamingEngine

        engine = DreamingEngine.__new__(DreamingEngine)
        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": ["ep-001", "ep-002"],
            "metadatas": [{"importance": 9}, {"importance": 3}],
        }
        mock_em._collection = mock_collection
        engine.episodic_memory = mock_em

        result = await engine._get_importance_map(["ep-001", "ep-002"])
        assert result == {"ep-001": 9, "ep-002": 3}

    @pytest.mark.asyncio
    async def test_importance_map_empty_fallback(self):
        """Test 19: When collection unavailable → returns empty dict."""
        from probos.cognitive.dreaming import DreamingEngine

        engine = DreamingEngine.__new__(DreamingEngine)
        mock_em = MagicMock()
        mock_em._collection = None
        engine.episodic_memory = mock_em

        result = await engine._get_importance_map(["ep-001"])
        assert result == {}
