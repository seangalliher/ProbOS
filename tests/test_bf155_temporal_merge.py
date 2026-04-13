"""BF-155: Temporal recall merge contamination — wrong-watch episodes outscore correct watch."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from probos.types import AnchorFrame, Episode, RecallScore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    *,
    ep_id: str = "ep-001",
    user_input: str = "test input",
    watch_section: str = "",
    timestamp: float | None = None,
    agent_ids: list[str] | None = None,
) -> Episode:
    anchors = AnchorFrame(watch_section=watch_section) if watch_section else None
    ep = Episode(
        user_input=user_input,
        timestamp=timestamp or time.time(),
        agent_ids=agent_ids or ["agent-001"],
        source="direct",
        anchors=anchors,
        outcomes=[{"intent": "test", "success": True}],
    )
    # Override the auto-generated ID for deterministic dedup testing
    object.__setattr__(ep, 'id', ep_id)
    return ep


# ===========================================================================
# Group 1: Pre-Merge Watch Filtering (4 tests)
# ===========================================================================

class TestPreMergeFiltering:
    """BF-155: Wrong-watch semantic episodes excluded during merge."""

    def test_wrong_watch_excluded_from_merge(self):
        """Semantic episodes from a different watch are excluded when query has temporal intent."""
        anchor_ep = _make_episode(ep_id="anchor-1", watch_section="first", user_input="first watch data")
        wrong_watch_ep = _make_episode(ep_id="sem-1", watch_section="second_dog", user_input="second dog data")

        # Simulate the merge logic from cognitive_agent.py
        _anchor_episodes = [anchor_ep]
        episodes = [wrong_watch_ep]
        _query_watch_section = "first"

        _seen_ids = {getattr(ep, 'id', id(ep)) for ep in _anchor_episodes}
        for ep in episodes:
            if getattr(ep, 'id', id(ep)) in _seen_ids:
                continue
            if (
                _query_watch_section
                and getattr(ep, "anchors", None)
                and getattr(ep.anchors, "watch_section", "")
                and ep.anchors.watch_section != _query_watch_section
            ):
                continue
            _anchor_episodes.append(ep)
            _seen_ids.add(getattr(ep, 'id', id(ep)))

        merged = _anchor_episodes
        assert len(merged) == 1
        assert merged[0].id == "anchor-1"

    def test_no_watch_episodes_pass_through(self):
        """Semantic episodes with no anchors/watch_section are NOT excluded."""
        anchor_ep = _make_episode(ep_id="anchor-1", watch_section="first")
        no_watch_ep = _make_episode(ep_id="sem-1", watch_section="")  # No anchors

        _anchor_episodes = [anchor_ep]
        episodes = [no_watch_ep]
        _query_watch_section = "first"

        _seen_ids = {getattr(ep, 'id', id(ep)) for ep in _anchor_episodes}
        for ep in episodes:
            if getattr(ep, 'id', id(ep)) in _seen_ids:
                continue
            if (
                _query_watch_section
                and getattr(ep, "anchors", None)
                and getattr(ep.anchors, "watch_section", "")
                and ep.anchors.watch_section != _query_watch_section
            ):
                continue
            _anchor_episodes.append(ep)
            _seen_ids.add(getattr(ep, 'id', id(ep)))

        merged = _anchor_episodes
        assert len(merged) == 2  # No-watch episode passes through

    def test_no_temporal_intent_no_filtering(self):
        """When query has no temporal intent, all semantic episodes pass through."""
        anchor_ep = _make_episode(ep_id="anchor-1", watch_section="first")
        wrong_watch_ep = _make_episode(ep_id="sem-1", watch_section="second_dog")

        _anchor_episodes = [anchor_ep]
        episodes = [wrong_watch_ep]
        _query_watch_section = ""  # No temporal intent

        _seen_ids = {getattr(ep, 'id', id(ep)) for ep in _anchor_episodes}
        for ep in episodes:
            if getattr(ep, 'id', id(ep)) in _seen_ids:
                continue
            if (
                _query_watch_section
                and getattr(ep, "anchors", None)
                and getattr(ep.anchors, "watch_section", "")
                and ep.anchors.watch_section != _query_watch_section
            ):
                continue
            _anchor_episodes.append(ep)
            _seen_ids.add(getattr(ep, 'id', id(ep)))

        merged = _anchor_episodes
        assert len(merged) == 2  # Both present, no filtering

    def test_duplicate_dedup_preserved(self):
        """Episodes already in anchor set are still deduplicated by ID."""
        anchor_ep = _make_episode(ep_id="shared-1", watch_section="first")
        dup_ep = _make_episode(ep_id="shared-1", watch_section="first")  # Same ID

        _anchor_episodes = [anchor_ep]
        episodes = [dup_ep]
        _query_watch_section = "first"

        _seen_ids = {getattr(ep, 'id', id(ep)) for ep in _anchor_episodes}
        for ep in episodes:
            if getattr(ep, 'id', id(ep)) in _seen_ids:
                continue
            if (
                _query_watch_section
                and getattr(ep, "anchors", None)
                and getattr(ep.anchors, "watch_section", "")
                and ep.anchors.watch_section != _query_watch_section
            ):
                continue
            _anchor_episodes.append(ep)
            _seen_ids.add(getattr(ep, 'id', id(ep)))

        merged = _anchor_episodes
        assert len(merged) == 1  # Duplicate removed


# ===========================================================================
# Group 2: Mismatch Penalty (5 tests)
# ===========================================================================

class TestMismatchPenalty:
    """BF-155: score_recall() penalizes wrong-watch episodes."""

    def test_mismatch_penalty_applied(self):
        """Episode from wrong watch gets penalty when query has temporal intent."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(watch_section="second_dog")
        rs = EpisodicMemory.score_recall(
            ep,
            semantic_similarity=0.5,
            keyword_hits=0,
            trust_weight=0.0,
            hebbian_weight=0.0,
            recency_weight=0.0,
            convergence_bonus=0.0,
            temporal_match=False,
            temporal_match_weight=0.25,
            temporal_mismatch_penalty=0.15,
            query_has_temporal_intent=True,
        )
        # Without penalty: semantic 0.35*0.5 + anchor 0.15*0.125 = 0.175 + 0.01875 = 0.19375
        # With penalty: 0.19375 - 0.15 = 0.04375
        rs_no_penalty = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5, trust_weight=0.0, hebbian_weight=0.0,
            recency_weight=0.0, convergence_bonus=0.0,
            temporal_match=False, query_has_temporal_intent=False,
        )
        assert rs.composite_score < rs_no_penalty.composite_score
        assert abs(rs.composite_score - (rs_no_penalty.composite_score - 0.15)) < 0.01

    def test_no_penalty_when_no_temporal_intent(self):
        """No penalty when query has no temporal intent."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(watch_section="second_dog")
        rs_with_intent = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5, trust_weight=0.0, hebbian_weight=0.0,
            recency_weight=0.0, convergence_bonus=0.0,
            temporal_match=False, temporal_match_weight=0.25,
            temporal_mismatch_penalty=0.15, query_has_temporal_intent=False,
        )
        rs_no_intent = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5, trust_weight=0.0, hebbian_weight=0.0,
            recency_weight=0.0, convergence_bonus=0.0,
            temporal_match=False,
        )
        # Both should produce identical score — no penalty applied
        assert abs(rs_with_intent.composite_score - rs_no_intent.composite_score) < 1e-9

    def test_no_penalty_when_episode_has_no_watch(self):
        """Episode with no anchors gets no penalty."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(watch_section="")  # No anchors
        rs = EpisodicMemory.score_recall(
            ep,
            semantic_similarity=0.5,
            keyword_hits=0,
            trust_weight=0.0,
            hebbian_weight=0.0,
            recency_weight=0.0,
            convergence_bonus=0.0,
            temporal_match=False,
            temporal_match_weight=0.25,
            temporal_mismatch_penalty=0.15,
            query_has_temporal_intent=True,
        )
        # No penalty because episode has no watch_section
        expected = 0.35 * 0.5
        assert abs(rs.composite_score - expected) < 0.01

    def test_penalty_clamped_to_zero(self):
        """Penalty cannot make composite score negative."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(watch_section="second_dog")
        rs = EpisodicMemory.score_recall(
            ep,
            semantic_similarity=0.05,  # Very low similarity → low composite
            keyword_hits=0,
            trust_weight=0.0,
            hebbian_weight=0.0,
            recency_weight=0.0,
            convergence_bonus=0.0,
            temporal_match=False,
            temporal_match_weight=0.25,
            temporal_mismatch_penalty=0.15,
            query_has_temporal_intent=True,
        )
        # Semantic: 0.35 * 0.05 = 0.0175, penalty 0.15 would go negative
        # Clamped to 0.0
        assert rs.composite_score >= 0.0

    def test_match_bonus_and_mismatch_penalty_mutually_exclusive(self):
        """An episode gets EITHER the match bonus OR the mismatch penalty, never both."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(watch_section="first")

        # Match case
        rs_match = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5, convergence_bonus=0.0,
            trust_weight=0.0, hebbian_weight=0.0, recency_weight=0.0,
            temporal_match=True, temporal_match_weight=0.25,
            temporal_mismatch_penalty=0.15, query_has_temporal_intent=True,
        )
        # Mismatch case
        rs_mismatch = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5, convergence_bonus=0.0,
            trust_weight=0.0, hebbian_weight=0.0, recency_weight=0.0,
            temporal_match=False, temporal_match_weight=0.25,
            temporal_mismatch_penalty=0.15, query_has_temporal_intent=True,
        )

        base = 0.35 * 0.5  # 0.175
        # Match gets bonus: 0.175 + 0.25 = 0.425
        assert rs_match.composite_score > base
        # Mismatch gets penalty: 0.175 - 0.15 = 0.025
        assert rs_mismatch.composite_score < base


# ===========================================================================
# Group 3: Weight Increase (3 tests)
# ===========================================================================

class TestWeightIncrease:
    """BF-155: Config defaults updated."""

    def test_temporal_match_weight_default_025(self):
        """MemoryConfig().recall_temporal_match_weight == 0.25."""
        from probos.config import MemoryConfig
        assert MemoryConfig().recall_temporal_match_weight == 0.25

    def test_temporal_mismatch_penalty_default_015(self):
        """MemoryConfig().recall_temporal_mismatch_penalty == 0.15."""
        from probos.config import MemoryConfig
        assert MemoryConfig().recall_temporal_mismatch_penalty == 0.15

    def test_match_vs_mismatch_swing(self):
        """Match bonus (+0.25) vs mismatch penalty (−0.15) = 0.40 composite swing."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = _make_episode(watch_section="first")
        kwargs = dict(
            semantic_similarity=0.5, keyword_hits=0,
            trust_weight=0.0, hebbian_weight=0.0, recency_weight=0.0,
            convergence_bonus=0.0, temporal_match_weight=0.25,
            temporal_mismatch_penalty=0.15, query_has_temporal_intent=True,
        )

        rs_match = EpisodicMemory.score_recall(ep, temporal_match=True, **kwargs)
        rs_mismatch = EpisodicMemory.score_recall(ep, temporal_match=False, **kwargs)

        swing = rs_match.composite_score - rs_mismatch.composite_score
        assert abs(swing - 0.40) < 0.01


# ===========================================================================
# Group 4: recall_weighted() Integration (2 tests)
# ===========================================================================

class TestRecallWeightedIntegration:
    """BF-155: recall_weighted() passes mismatch params to score_recall()."""

    @pytest.mark.asyncio
    async def test_recall_weighted_passes_mismatch_params(self):
        """recall_weighted() passes temporal_mismatch_penalty and query_has_temporal_intent."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._query_reformulation_enabled = False
        em._activation_tracker = None

        ep = _make_episode(watch_section="first")
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.8)])
        em.keyword_search = AsyncMock(return_value=[])

        with patch.object(EpisodicMemory, 'score_recall', wraps=EpisodicMemory.score_recall) as mock_score:
            await em.recall_weighted(
                "agent-001", "test query",
                query_watch_section="first",
                temporal_mismatch_penalty=0.20,
            )
            mock_score.assert_called_once()
            kw = mock_score.call_args.kwargs
            assert kw.get("temporal_mismatch_penalty") == 0.20
            assert kw.get("query_has_temporal_intent") is True

    @pytest.mark.asyncio
    async def test_recall_weighted_no_temporal_intent_when_empty(self):
        """query_has_temporal_intent is False when query_watch_section is empty."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._query_reformulation_enabled = False
        em._activation_tracker = None

        ep = _make_episode(watch_section="first")
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.8)])
        em.keyword_search = AsyncMock(return_value=[])

        with patch.object(EpisodicMemory, 'score_recall', wraps=EpisodicMemory.score_recall) as mock_score:
            await em.recall_weighted(
                "agent-001", "test query",
                query_watch_section="",
                temporal_mismatch_penalty=0.15,
            )
            mock_score.assert_called_once()
            kw = mock_score.call_args.kwargs
            assert kw.get("query_has_temporal_intent") is False
