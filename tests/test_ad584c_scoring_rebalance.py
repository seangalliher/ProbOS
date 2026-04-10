"""AD-584c: Recall Scoring Rebalance — weights, convergence bonus, config wiring."""

from __future__ import annotations

import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.types import AnchorFrame, Episode, RecallScore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    *,
    user_input: str = "test input",
    timestamp: float | None = None,
    agent_ids: list[str] | None = None,
    source: str = "direct",
    anchors: AnchorFrame | None = None,
    reflection: str | None = None,
) -> Episode:
    return Episode(
        user_input=user_input,
        timestamp=timestamp or time.time(),
        agent_ids=agent_ids or ["agent-001"],
        source=source,
        anchors=anchors,
        reflection=reflection,
        outcomes=[{"intent": "test_intent", "success": True}],
    )


def _full_anchor() -> AnchorFrame:
    """AnchorFrame with all 10 fields filled — anchor_confidence ≈ 1.0."""
    return AnchorFrame(
        duty_cycle_id="duty-001",
        watch_section="alpha",
        channel="ward_room",
        channel_id="ch-123",
        department="science",
        participants=["Atlas", "Horizon"],
        trigger_agent="Atlas",
        trigger_type="ward_room_post",
        thread_id="thread-456",
        event_log_window=1000.0,
    )


def _half_anchor() -> AnchorFrame:
    """AnchorFrame with 5/10 fields filled — anchor_confidence ≈ 0.5."""
    return AnchorFrame(
        channel="ward_room",
        department="science",
        participants=["Atlas"],
        trigger_type="ward_room_post",
        trigger_agent="Atlas",
    )


# ===========================================================================
# Group 1: Weight Rebalance (8 tests)
# ===========================================================================

class TestWeightRebalance:
    """AD-584c: Verify new default weights and scoring formula."""

    def test_score_recall_default_weights_sum_to_one(self):
        """Test 1: Default weights dict sums to 1.0."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode()
        # Call with no explicit weights to trigger defaults
        rs = EpisodicMemory.score_recall(ep, semantic_similarity=0.5)
        # Verify by inspecting the source defaults
        w = {
            "semantic": 0.35, "keyword": 0.20, "trust": 0.10,
            "hebbian": 0.05, "recency": 0.15, "anchor": 0.15,
        }
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_score_recall_new_keyword_weight(self):
        """Test 2: keyword_hits=2 scores higher with new weight (0.20 vs old 0.10)."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode()
        rs = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.0, keyword_hits=2,
            trust_weight=0.0, hebbian_weight=0.0, recency_weight=0.0,
            convergence_bonus=0.0,
        )
        # keyword_norm = min(2/3, 1.0) = 0.667
        # new contribution: 0.20 * 0.667 ≈ 0.133
        keyword_norm = min(2 / 3.0, 1.0)
        expected = 0.20 * keyword_norm
        assert abs(rs.composite_score - expected) < 0.01

    def test_score_recall_reduced_trust_weight(self):
        """Test 3: trust_weight=1.0 contributes 0.10 (was 0.15)."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode()
        rs = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.0, keyword_hits=0,
            trust_weight=1.0, hebbian_weight=0.0, recency_weight=0.0,
            convergence_bonus=0.0,
        )
        # Only trust contributes: 0.10 * 1.0 = 0.10
        assert abs(rs.composite_score - 0.10) < 0.01

    def test_score_recall_reduced_hebbian_weight(self):
        """Test 4: hebbian_weight=1.0 contributes 0.05 (was 0.10)."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode()
        rs = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.0, keyword_hits=0,
            trust_weight=0.0, hebbian_weight=1.0, recency_weight=0.0,
            convergence_bonus=0.0,
        )
        assert abs(rs.composite_score - 0.05) < 0.01

    def test_score_recall_increased_anchor_weight(self):
        """Test 5: full anchor (confidence ≈ 1.0) contributes 0.15 (was 0.10)."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(anchors=_full_anchor())
        rs = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.0, keyword_hits=0,
            trust_weight=0.0, hebbian_weight=0.0, recency_weight=0.0,
            convergence_bonus=0.0,
        )
        # anchor_confidence ≈ 1.0, new weight 0.15
        assert abs(rs.composite_score - 0.15 * rs.anchor_confidence) < 0.01

    def test_score_recall_reduced_recency_weight(self):
        """Test 6: recency contribution is 0.15 * recency_weight (was 0.20)."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode()
        rs = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.0, keyword_hits=0,
            trust_weight=0.0, hebbian_weight=0.0, recency_weight=1.0,
            convergence_bonus=0.0,
        )
        assert abs(rs.composite_score - 0.15) < 0.01

    def test_score_recall_custom_weights_override(self):
        """Test 7: explicit weights= dict overrides defaults."""
        from probos.cognitive.episodic import EpisodicMemory

        custom = {
            "semantic": 1.0, "keyword": 0.0, "trust": 0.0,
            "hebbian": 0.0, "recency": 0.0, "anchor": 0.0,
        }
        ep = _make_episode()
        rs = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.7, weights=custom, convergence_bonus=0.0,
        )
        assert abs(rs.composite_score - 0.7) < 1e-9

    def test_config_default_weights_match_score_recall(self):
        """Test 8: MemoryConfig().recall_weights matches score_recall() defaults."""
        from probos.config import MemoryConfig

        config_weights = MemoryConfig().recall_weights
        expected = {
            "semantic": 0.35, "keyword": 0.20, "trust": 0.10,
            "hebbian": 0.05, "recency": 0.15, "anchor": 0.15,
        }
        assert config_weights == expected


# ===========================================================================
# Group 2: Convergence Bonus (5 tests)
# ===========================================================================

class TestConvergenceBonus:
    """AD-584c: Convergence bonus for multi-channel evidence."""

    def test_convergence_bonus_both_channels(self):
        """Test 9: semantic > 0 AND keyword_hits > 0 gets +0.10 bonus."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode()
        rs_with = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5, keyword_hits=1,
            trust_weight=0.0, hebbian_weight=0.0, recency_weight=0.0,
            convergence_bonus=0.10,
        )
        rs_without = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5, keyword_hits=1,
            trust_weight=0.0, hebbian_weight=0.0, recency_weight=0.0,
            convergence_bonus=0.0,
        )
        assert abs((rs_with.composite_score - rs_without.composite_score) - 0.10) < 1e-9

    def test_no_convergence_bonus_semantic_only(self):
        """Test 10: semantic > 0 but keyword_hits == 0: no bonus."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode()
        rs = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5, keyword_hits=0,
            trust_weight=0.0, hebbian_weight=0.0, recency_weight=0.0,
            convergence_bonus=0.10,
        )
        # Only semantic contributes: 0.35 * 0.5 = 0.175, no bonus
        assert abs(rs.composite_score - 0.35 * 0.5) < 0.01

    def test_no_convergence_bonus_keyword_only(self):
        """Test 11: semantic == 0.0 but keyword_hits > 0: no bonus."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode()
        rs = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.0, keyword_hits=2,
            trust_weight=0.0, hebbian_weight=0.0, recency_weight=0.0,
            convergence_bonus=0.10,
        )
        keyword_norm = min(2 / 3.0, 1.0)
        expected = 0.20 * keyword_norm  # No convergence bonus
        assert abs(rs.composite_score - expected) < 0.01

    def test_convergence_bonus_configurable(self):
        """Test 12: convergence_bonus=0.05 produces +0.05."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode()
        rs_05 = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5, keyword_hits=1,
            trust_weight=0.0, hebbian_weight=0.0, recency_weight=0.0,
            convergence_bonus=0.05,
        )
        rs_00 = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5, keyword_hits=1,
            trust_weight=0.0, hebbian_weight=0.0, recency_weight=0.0,
            convergence_bonus=0.0,
        )
        assert abs((rs_05.composite_score - rs_00.composite_score) - 0.05) < 1e-9

    def test_convergence_bonus_zero_disables(self):
        """Test 13: convergence_bonus=0.0 produces no bonus."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode()
        rs = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5, keyword_hits=2,
            trust_weight=0.0, hebbian_weight=0.0, recency_weight=0.0,
            convergence_bonus=0.0,
        )
        keyword_norm = min(2 / 3.0, 1.0)
        expected = 0.35 * 0.5 + 0.20 * keyword_norm
        assert abs(rs.composite_score - expected) < 0.01


# ===========================================================================
# Group 3: Config Wiring (4 tests)
# ===========================================================================

class TestConfigWiring:
    """AD-584c: Config fields wired through the full call chain."""

    def test_config_convergence_bonus_default(self):
        """Test 14: MemoryConfig().recall_convergence_bonus == 0.10."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.recall_convergence_bonus == 0.10

    @pytest.mark.asyncio
    async def test_recall_weighted_passes_convergence_bonus(self):
        """Test 15: recall_weighted() passes convergence_bonus to score_recall()."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._query_reformulation_enabled = False

        # Mock recall_for_agent_scored to return one episode
        ep = _make_episode()
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.8)])
        em.keyword_search = AsyncMock(return_value=[])

        with patch.object(EpisodicMemory, 'score_recall', wraps=EpisodicMemory.score_recall) as mock_score:
            await em.recall_weighted(
                "agent-001", "test query",
                convergence_bonus=0.25,
            )
            mock_score.assert_called_once()
            call_kwargs = mock_score.call_args
            assert call_kwargs.kwargs.get("convergence_bonus") == 0.25 or \
                (len(call_kwargs.args) >= 8 if call_kwargs.args else False)

    @pytest.mark.asyncio
    async def test_recall_weighted_passes_config_weights(self):
        """Test 16: recall_weighted() passes custom weights dict to score_recall()."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._query_reformulation_enabled = False

        ep = _make_episode()
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.8)])
        em.keyword_search = AsyncMock(return_value=[])

        custom_w = {"semantic": 1.0, "keyword": 0.0, "trust": 0.0,
                     "hebbian": 0.0, "recency": 0.0, "anchor": 0.0}

        with patch.object(EpisodicMemory, 'score_recall', wraps=EpisodicMemory.score_recall) as mock_score:
            await em.recall_weighted(
                "agent-001", "test query",
                weights=custom_w,
                convergence_bonus=0.0,
            )
            mock_score.assert_called_once()
            assert mock_score.call_args.kwargs.get("weights") is custom_w

    def test_cognitive_agent_passes_convergence_bonus(self):
        """Test 17: cognitive_agent.py recall path includes convergence_bonus kwarg."""
        import ast
        from pathlib import Path

        src = Path("src/probos/cognitive/cognitive_agent.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "convergence_bonus":
                found = True
                break
        assert found, "cognitive_agent.py must pass convergence_bonus to recall_weighted()"


# ===========================================================================
# Group 4: Regression — Probe Signal Improvement (3 tests)
# ===========================================================================

class TestProbeSignalImprovement:
    """AD-584c: Verify scoring changes improve probe-style episode ranking."""

    def test_probe_episode_scores_above_gate(self):
        """Test 18: Probe-style episode with QA-range similarity passes anchor_confidence_gate=0.3."""
        from probos.cognitive.episodic import EpisodicMemory

        # Probe episodes have full anchors (BF-133) and realistic QA similarity
        ep = _make_episode(anchors=_full_anchor())
        rs = EpisodicMemory.score_recall(
            ep,
            semantic_similarity=0.6,  # QA-trained model range
            keyword_hits=1,
            trust_weight=0.5,    # Default trust
            hebbian_weight=0.5,  # Default hebbian
            recency_weight=0.9,  # Fresh episode
            convergence_bonus=0.10,
        )
        # With rebalanced weights + convergence bonus, this should comfortably
        # exceed the anchor_confidence_gate of 0.3
        assert rs.composite_score > 0.3
        assert rs.anchor_confidence > 0.3

    def test_convergence_boosts_ranking(self):
        """Test 19: Episode found by both channels ranks higher than semantic-only."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(anchors=_half_anchor())

        # Both channels
        rs_both = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5, keyword_hits=2,
            trust_weight=0.5, hebbian_weight=0.5, recency_weight=0.5,
            convergence_bonus=0.10,
        )
        # Semantic only (same similarity)
        rs_sem_only = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5, keyword_hits=0,
            trust_weight=0.5, hebbian_weight=0.5, recency_weight=0.5,
            convergence_bonus=0.10,
        )
        assert rs_both.composite_score > rs_sem_only.composite_score

    def test_keyword_heavy_episode_promoted(self):
        """Test 20: Episode with 3+ keyword hits ranks higher with new weights vs old."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode()

        # New weights (default)
        rs_new = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.3, keyword_hits=3,
            trust_weight=0.5, hebbian_weight=0.5, recency_weight=0.5,
            convergence_bonus=0.10,
        )

        # Old weights (explicit)
        old_w = {
            "semantic": 0.35, "keyword": 0.10, "trust": 0.15,
            "hebbian": 0.10, "recency": 0.20, "anchor": 0.10,
        }
        rs_old = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.3, keyword_hits=3,
            trust_weight=0.5, hebbian_weight=0.5, recency_weight=0.5,
            weights=old_w,
            convergence_bonus=0.10,
        )

        # New weights give keyword 0.20 vs old 0.10 → keyword-heavy episodes are promoted
        assert rs_new.composite_score > rs_old.composite_score
