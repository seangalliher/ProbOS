"""AD-601: TCM Temporal Context Vectors — 20 tests.

Tests for the Temporal Context Model engine, serialization, EpisodicMemory
integration, RecallScore field, and config defaults.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from probos.cognitive.temporal_context import (
    TCMConfig,
    TemporalContextModel,
    deserialize_tcm_vector,
    serialize_tcm_vector,
)
from probos.config import MemoryConfig
from probos.types import Episode, RecallScore


# ---- TemporalContextModel engine (8 tests) --------------------------------


class TestTCMInitZeros:
    def test_new_tcm_has_zero_context(self):
        tcm = TemporalContextModel()
        vec = tcm.get_context_vector()
        assert len(vec) == 16
        assert all(v == 0.0 for v in vec)
        assert not tcm._initialized


class TestTCMFirstUpdate:
    def test_first_update_sets_context_directly(self):
        tcm = TemporalContextModel()
        result = tcm.update("hello world", timestamp=1000.0)
        assert len(result) == 16
        # Should be normalized to unit length
        mag = math.sqrt(sum(x * x for x in result))
        assert mag == pytest.approx(1.0, abs=1e-6)
        assert tcm._initialized


class TestTCMDriftRate:
    def test_drift_rate_controls_decay(self):
        tcm = TemporalContextModel(TCMConfig(drift_rate=0.95))
        ctx1 = tcm.update("episode-1", timestamp=100.0)
        ctx2 = tcm.update("episode-2", timestamp=200.0)
        # Second context should differ from first (drift occurred)
        assert ctx1 != ctx2
        # Both should be unit vectors
        mag1 = math.sqrt(sum(x * x for x in ctx1))
        mag2 = math.sqrt(sum(x * x for x in ctx2))
        assert mag1 == pytest.approx(1.0, abs=1e-6)
        assert mag2 == pytest.approx(1.0, abs=1e-6)


class TestTCMSimilarityNearby:
    def test_similarity_nearby_is_high(self):
        tcm = TemporalContextModel()
        tcm.update("episode-A", timestamp=100.0)
        stored_a = tcm.get_context_vector()
        tcm.update("episode-B", timestamp=101.0)
        sim = tcm.compute_similarity(stored_a)
        assert sim > 0.8


class TestTCMSimilarityDecays:
    def test_similarity_decays_over_many_episodes(self):
        # Use lower drift rate (0.80) to make decay observable in 16-dim hash space
        tcm = TemporalContextModel(TCMConfig(drift_rate=0.80))
        tcm.update("episode-anchor", timestamp=100.0)
        stored = tcm.get_context_vector()
        for i in range(30):
            tcm.update(f"episode-drift-{i}", timestamp=200.0 + i * 10)
        sim = tcm.compute_similarity(stored)
        assert sim < 0.95  # Should decay noticeably with rho=0.80


class TestTCMSimilarityGradient:
    def test_endpoint_gradient(self):
        tcm = TemporalContextModel()
        snapshots: dict[int, list[float]] = {}
        for i in range(21):
            tcm.update(f"episode-{i}", timestamp=1000.0 + i * 10)
            if i in (0, 5, 10, 15, 20):
                snapshots[i] = tcm.get_context_vector()
        # Similarity to context at episode 20
        sim_0 = tcm.compute_similarity(snapshots[0])
        sim_15 = tcm.compute_similarity(snapshots[15])
        sim_20 = tcm.compute_similarity(snapshots[20])
        # Endpoint ordering
        assert sim_20 > sim_0
        assert sim_15 > sim_0


class TestTCMSetContextVector:
    def test_set_context_restores_state(self):
        tcm = TemporalContextModel()
        tcm.update("episode-1", timestamp=100.0)
        saved = tcm.get_context_vector()

        tcm2 = TemporalContextModel()
        tcm2.set_context_vector(saved)
        assert tcm2.get_context_vector() == saved
        assert tcm2._initialized

        # Similarity should work with restored vector
        sim = tcm2.compute_similarity(saved)
        assert sim == pytest.approx(1.0, abs=1e-6)


class TestTCMDimensionMismatch:
    def test_set_context_wrong_dimension_raises(self):
        tcm = TemporalContextModel(TCMConfig(dimension=16))
        with pytest.raises(ValueError, match="dimension mismatch"):
            tcm.set_context_vector([0.1] * 8)

    def test_compute_similarity_wrong_dimension_returns_zero(self):
        tcm = TemporalContextModel(TCMConfig(dimension=16))
        tcm.update("init", timestamp=1.0)
        assert tcm.compute_similarity([0.1] * 8) == 0.0


# ---- Serialization (3 tests) ----------------------------------------------


class TestSerializeDeserializeRoundtrip:
    def test_roundtrip(self):
        vec = [0.123456, -0.654321, 0.0, 1.0, -1.0]
        result = deserialize_tcm_vector(serialize_tcm_vector(vec))
        assert result is not None
        assert len(result) == len(vec)
        for a, b in zip(result, vec):
            assert a == pytest.approx(b, abs=1e-5)


class TestDeserializeEmpty:
    def test_empty_string_returns_none(self):
        assert deserialize_tcm_vector("") is None
        assert deserialize_tcm_vector(None) is None  # type: ignore[arg-type]


class TestDeserializeMalformed:
    @pytest.mark.parametrize("bad_input", ["not json", "[1, 'foo']", "42"])
    def test_malformed_returns_none(self, bad_input: str):
        assert deserialize_tcm_vector(bad_input) is None


# ---- EpisodicMemory integration (5 tests) ----------------------------------


class TestStoreCapturesTCMVector:
    @pytest.mark.asyncio
    async def test_store_with_tcm_captures_vector(self, tmp_path: Path):
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(db_path=str(tmp_path / "test.db"))
        await em.start()

        tcm = TemporalContextModel(TCMConfig(dimension=16))
        em.set_tcm(tcm)

        ep = Episode(id="test-ep-1", user_input="hello world", timestamp=1000.0, agent_ids=["agent-1"])
        await em.store(ep)

        # Check metadata has TCM vector
        result = em._collection.get(ids=["test-ep-1"], include=["metadatas"])
        meta = result["metadatas"][0]
        assert "tcm_vector_json" in meta
        assert meta["tcm_vector_json"] != ""
        vec = deserialize_tcm_vector(meta["tcm_vector_json"])
        assert vec is not None
        assert len(vec) == 16


class TestStoreWithoutTCM:
    @pytest.mark.asyncio
    async def test_store_without_tcm_empty_vector(self, tmp_path: Path):
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(db_path=str(tmp_path / "test.db"))
        await em.start()
        # No set_tcm() call

        ep = Episode(id="test-ep-2", user_input="hello world", timestamp=1000.0, agent_ids=["agent-1"])
        await em.store(ep)

        result = em._collection.get(ids=["test-ep-2"], include=["metadatas"])
        meta = result["metadatas"][0]
        assert meta.get("tcm_vector_json", "") == ""


class TestScoreRecallTCMGradient:
    def test_higher_tcm_similarity_higher_score(self):
        from probos.cognitive.episodic import EpisodicMemory

        ep = Episode(id="test-ep", user_input="test", timestamp=1000.0)
        rs_high = EpisodicMemory.score_recall(
            episode=ep, semantic_similarity=0.5, keyword_hits=0,
            trust_weight=0.5, hebbian_weight=0.5, recency_weight=0.3,
            tcm_similarity=0.9, tcm_weight=0.15, tcm_fallback_watch_weight=0.05,
        )
        rs_low = EpisodicMemory.score_recall(
            episode=ep, semantic_similarity=0.5, keyword_hits=0,
            trust_weight=0.5, hebbian_weight=0.5, recency_weight=0.3,
            tcm_similarity=0.3, tcm_weight=0.15, tcm_fallback_watch_weight=0.05,
        )
        assert rs_high.composite_score > rs_low.composite_score
        diff = rs_high.composite_score - rs_low.composite_score
        assert diff == pytest.approx(0.15 * (0.9 - 0.3), abs=1e-6)


class TestScoreRecallTCMFallback:
    def test_no_tcm_falls_back_to_bf147(self):
        from probos.cognitive.episodic import EpisodicMemory

        ep = Episode(id="test-ep", user_input="test", timestamp=1000.0)
        # No TCM (tcm_similarity=0.0) — should use legacy temporal_match logic
        rs = EpisodicMemory.score_recall(
            episode=ep, semantic_similarity=0.5, keyword_hits=0,
            trust_weight=0.5, hebbian_weight=0.5, recency_weight=0.3,
            temporal_match=True, temporal_match_weight=0.25,
            tcm_similarity=0.0, tcm_weight=0.15,
        )
        rs_no_match = EpisodicMemory.score_recall(
            episode=ep, semantic_similarity=0.5, keyword_hits=0,
            trust_weight=0.5, hebbian_weight=0.5, recency_weight=0.3,
            temporal_match=False, temporal_match_weight=0.25,
            tcm_similarity=0.0, tcm_weight=0.15,
        )
        # Legacy temporal_match=True should add the full temporal_match_weight
        assert rs.composite_score > rs_no_match.composite_score
        diff = rs.composite_score - rs_no_match.composite_score
        assert diff == pytest.approx(0.25, abs=1e-6)


class TestScoreRecallTCMNoMismatchPenalty:
    def test_tcm_active_no_mismatch_penalty(self):
        from probos.cognitive.episodic import EpisodicMemory

        ep = Episode(id="test-ep", user_input="test", timestamp=1000.0)
        # TCM active — should NOT apply mismatch penalty
        rs_tcm = EpisodicMemory.score_recall(
            episode=ep, semantic_similarity=0.5, keyword_hits=0,
            trust_weight=0.5, hebbian_weight=0.5, recency_weight=0.3,
            temporal_match=False, query_has_temporal_intent=True,
            temporal_mismatch_penalty=0.15,
            tcm_similarity=0.7, tcm_weight=0.15,
        )
        # Baseline without any temporal contribution
        rs_base = EpisodicMemory.score_recall(
            episode=ep, semantic_similarity=0.5, keyword_hits=0,
            trust_weight=0.5, hebbian_weight=0.5, recency_weight=0.3,
            temporal_match=False, query_has_temporal_intent=False,
            tcm_similarity=0.0, tcm_weight=0.0,
        )
        # TCM branch should ADD, not subtract
        assert rs_tcm.composite_score >= rs_base.composite_score + 0.15 * 0.7 - 1e-6


# ---- RecallScore (1 test) --------------------------------------------------


class TestRecallScoreTCMField:
    def test_tcm_similarity_default(self):
        ep = Episode(id="x", user_input="t")
        rs = RecallScore(episode=ep)
        assert rs.tcm_similarity == 0.0
        rs2 = RecallScore(episode=ep, tcm_similarity=0.85)
        assert rs2.tcm_similarity == 0.85


# ---- Config (3 tests) ------------------------------------------------------


class TestMemoryConfigTCMDefaults:
    def test_defaults(self):
        mc = MemoryConfig()
        assert mc.tcm_enabled is True
        assert mc.tcm_dimension == 16
        assert mc.tcm_drift_rate == 0.95
        assert mc.tcm_weight == 0.15
        assert mc.tcm_fallback_watch_weight == 0.05


class TestTCMConfigDataclass:
    def test_defaults_match_memory_config(self):
        tc = TCMConfig()
        mc = MemoryConfig()
        assert tc.dimension == mc.tcm_dimension
        assert tc.drift_rate == mc.tcm_drift_rate
        assert tc.weight == mc.tcm_weight
        assert tc.fallback_watch_weight == mc.tcm_fallback_watch_weight


class TestTCMDisabledSkipsWiring:
    @pytest.mark.asyncio
    async def test_no_tcm_no_vector(self, tmp_path: Path):
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(db_path=str(tmp_path / "test.db"))
        await em.start()
        # Simulate tcm_enabled=False — don't call set_tcm()
        assert em._tcm is None

        ep = Episode(id="test-disabled", user_input="no tcm", timestamp=1000.0, agent_ids=["agent-1"])
        await em.store(ep)

        result = em._collection.get(ids=["test-disabled"], include=["metadatas"])
        meta = result["metadatas"][0]
        assert meta.get("tcm_vector_json", "") == ""
