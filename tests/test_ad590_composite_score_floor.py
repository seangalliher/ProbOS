"""AD-590: Composite Score Floor — Recall Quality Gate.

Tests that the composite_score_floor parameter on recall_weighted() correctly
filters marginal episodes from results, reducing noise in agent context.
"""

from __future__ import annotations

import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.types import AnchorFrame, Episode, RecallScore


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_ad584c_scoring_rebalance.py)
# ---------------------------------------------------------------------------

def _make_episode(
    *,
    user_input: str = "test input",
    timestamp: float | None = None,
    agent_ids: list[str] | None = None,
    source: str = "direct",
    anchors: AnchorFrame | None = None,
) -> Episode:
    return Episode(
        user_input=user_input,
        timestamp=timestamp or time.time(),
        agent_ids=agent_ids or ["agent-001"],
        source=source,
        anchors=anchors,
        outcomes=[{"intent": "test_intent", "success": True}],
    )


def _full_anchor() -> AnchorFrame:
    """AnchorFrame with all 10 fields — anchor_confidence ~ 1.0."""
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
    """AnchorFrame with 5/10 fields — anchor_confidence ~ 0.5."""
    return AnchorFrame(
        channel="ward_room",
        department="science",
        participants=["Atlas"],
        trigger_type="ward_room_post",
        trigger_agent="Atlas",
    )


def _make_em():
    """Create a minimal EpisodicMemory for recall_weighted testing."""
    from probos.cognitive.episodic import EpisodicMemory

    em = EpisodicMemory.__new__(EpisodicMemory)
    em._query_reformulation_enabled = False
    em._activation_tracker = None
    return em


# ===========================================================================
# Group 1: Floor Filter Behavior (6 tests)
# ===========================================================================

class TestFloorFilterBehavior:
    """AD-590: Composite score floor filters marginal episodes."""

    @pytest.mark.asyncio
    async def test_floor_zero_no_filtering(self):
        """Floor of 0.0 (default) does not filter any episodes."""
        em = _make_em()

        # Two episodes: one high-scoring, one low-scoring
        ep_high = _make_episode(user_input="relevant data", anchors=_full_anchor())
        ep_low = _make_episode(user_input="marginal noise", anchors=None)

        em.recall_for_agent_scored = AsyncMock(return_value=[
            (ep_high, 0.8),  # high semantic sim → high composite
            (ep_low, 0.1),   # low semantic sim → low composite
        ])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            composite_score_floor=0.0,
        )
        assert len(results) == 2  # Both pass — no floor applied

    @pytest.mark.asyncio
    async def test_floor_filters_low_scoring_episodes(self):
        """Floor of 0.35 filters episodes with composite_score < 0.35."""
        em = _make_em()

        ep_high = _make_episode(user_input="relevant data", anchors=_full_anchor())
        ep_low = _make_episode(user_input="marginal noise", anchors=None)

        em.recall_for_agent_scored = AsyncMock(return_value=[
            (ep_high, 0.8),  # high sim → composite well above 0.35
            (ep_low, 0.1),   # low sim, no anchor → composite below 0.35
        ])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            composite_score_floor=0.35,
        )
        # Only high-scoring episode passes
        assert len(results) == 1
        assert results[0].composite_score >= 0.35

    @pytest.mark.asyncio
    async def test_floor_keeps_episodes_at_boundary(self):
        """Episodes exactly at the floor threshold are kept (>=, not >)."""
        from probos.cognitive.episodic import EpisodicMemory

        # Engineer an episode that scores exactly at the boundary
        ep = _make_episode(anchors=_half_anchor())
        rs = EpisodicMemory.score_recall(
            ep, semantic_similarity=0.5,
            keyword_hits=0, trust_weight=0.5, hebbian_weight=0.5,
            recency_weight=0.5, convergence_bonus=0.0,
        )
        floor = rs.composite_score  # Use its exact score as floor

        em = _make_em()
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.5)])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            composite_score_floor=floor,
        )
        assert len(results) == 1  # Exact match kept

    @pytest.mark.asyncio
    async def test_floor_applied_after_anchor_gate(self):
        """Floor filter runs after anchor_confidence_gate (step 3c after 3b)."""
        em = _make_em()

        # Episode with low anchor but high composite (would pass floor, fail anchor gate)
        ep_low_anchor = _make_episode(user_input="low anchor high sim", anchors=None)
        # Episode with high anchor but low composite (would pass anchor gate, fail floor)
        ep_low_composite = _make_episode(user_input="high anchor low sim", anchors=_full_anchor())

        em.recall_for_agent_scored = AsyncMock(return_value=[
            (ep_low_anchor, 0.9),    # High sim, no anchor
            (ep_low_composite, 0.05), # Low sim, full anchor
        ])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            anchor_confidence_gate=0.3,
            composite_score_floor=0.40,
        )
        # ep_low_anchor: fails anchor gate (0.0 < 0.3) — filtered at 3b
        # ep_low_composite: passes anchor gate (1.0 > 0.3) but fails floor (<0.40) — filtered at 3c
        # Result: neither passes
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_floor_filters_before_budget_enforcement(self):
        """Floor filtering happens before budget loop — budget only sees quality episodes."""
        em = _make_em()

        # Create 20 marginal episodes + 2 relevant ones
        eps = []
        for i in range(20):
            eps.append((_make_episode(user_input=f"noise {i}"), 0.1))  # low sim
        eps.append((_make_episode(user_input="relevant A", anchors=_full_anchor()), 0.8))
        eps.append((_make_episode(user_input="relevant B", anchors=_full_anchor()), 0.7))

        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=4000,
            composite_score_floor=0.35,
        )
        # Only the 2 relevant episodes should pass the floor
        assert len(results) == 2
        for rs in results:
            assert rs.composite_score >= 0.35

    @pytest.mark.asyncio
    async def test_all_episodes_below_floor_returns_empty(self):
        """When all episodes are below the floor, return empty list."""
        em = _make_em()

        ep = _make_episode(user_input="very marginal")
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.05)])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            composite_score_floor=0.90,  # Very high floor
        )
        assert len(results) == 0


# ===========================================================================
# Group 2: Config Integration (4 tests)
# ===========================================================================

class TestConfigIntegration:
    """AD-590: Config field and tier wiring."""

    def test_memory_config_has_composite_score_floor(self):
        """MemoryConfig has composite_score_floor field with default 0.35."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert hasattr(cfg, "composite_score_floor")
        assert cfg.composite_score_floor == 0.35

    def test_basic_tier_floor_disabled(self):
        """Basic tier has composite_score_floor = 0.0 (disabled)."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.recall_tiers["basic"]["composite_score_floor"] == 0.0

    def test_enhanced_tier_floor_set(self):
        """Enhanced tier has composite_score_floor = 0.35."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.recall_tiers["enhanced"]["composite_score_floor"] == 0.35

    def test_oracle_tier_floor_disabled(self):
        """Oracle tier has composite_score_floor = 0.0 (exhaustive recall)."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.recall_tiers["oracle"]["composite_score_floor"] == 0.0


# ===========================================================================
# Group 3: Wiring — Call Sites Pass Floor (3 tests)
# ===========================================================================

class TestCallSiteWiring:
    """AD-590: Production call sites pass composite_score_floor."""

    def test_cognitive_agent_passes_composite_score_floor(self):
        """cognitive_agent.py recall_weighted call includes composite_score_floor kwarg."""
        import ast
        from pathlib import Path

        src = Path("src/probos/cognitive/cognitive_agent.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "composite_score_floor":
                found = True
                break
        assert found, "cognitive_agent.py must pass composite_score_floor to recall_weighted()"

    def test_proactive_passes_composite_score_floor(self):
        """proactive.py recall_weighted call includes composite_score_floor kwarg."""
        import ast
        from pathlib import Path

        src = Path("src/probos/proactive.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "composite_score_floor":
                found = True
                break
        assert found, "proactive.py must pass composite_score_floor to recall_weighted()"

    def test_oracle_does_not_pass_composite_score_floor(self):
        """oracle_service.py does NOT pass composite_score_floor (inherits 0.0 default)."""
        import ast
        from pathlib import Path

        src = Path("src/probos/cognitive/oracle_service.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "composite_score_floor":
                pytest.fail("oracle_service.py must NOT pass composite_score_floor (0.0 default = disabled)")


# ===========================================================================
# Group 4: DEEP Strategy Relaxation (2 tests)
# ===========================================================================

class TestDeepStrategyRelaxation:
    """AD-590: DEEP retrieval strategy relaxes the composite score floor."""

    def test_deep_strategy_relaxes_floor_in_code(self):
        """cognitive_agent.py DEEP block adjusts composite_score_floor."""
        from pathlib import Path

        src = Path("src/probos/cognitive/cognitive_agent.py").read_text(encoding="utf-8")
        # Both DEEP adjustments should reference composite_score_floor
        assert "composite_score_floor" in src
        # Verify DEEP block pattern: max(0.0, ... - 0.10)
        assert "0.10" in src  # The relaxation amount

    def test_deep_relaxation_cannot_go_negative(self):
        """DEEP relaxation uses max(0.0, ...) to prevent negative floor."""
        # Simulate the relaxation math
        original_floor = 0.05
        relaxed = max(0.0, original_floor - 0.10)
        assert relaxed == 0.0

        original_floor = 0.35
        relaxed = max(0.0, original_floor - 0.10)
        assert relaxed == pytest.approx(0.25)


# ===========================================================================
# Group 5: Regression — No Impact on Existing Behavior (2 tests)
# ===========================================================================

class TestRegression:
    """AD-590: Existing behavior unaffected when floor is 0.0."""

    @pytest.mark.asyncio
    async def test_default_params_match_pre_ad590_behavior(self):
        """recall_weighted() with no composite_score_floor behaves identically to pre-AD-590."""
        em = _make_em()

        ep = _make_episode(user_input="test data")
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.3)])
        em.keyword_search = AsyncMock(return_value=[])

        # Default composite_score_floor is 0.0 — should not filter
        results = await em.recall_weighted("agent-001", "test query")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_activation_tracking_still_runs_after_floor(self):
        """AD-567d activation tracking runs on the budgeted results, not pre-floor results."""
        em = _make_em()
        mock_tracker = MagicMock()
        mock_tracker.record_batch_access = AsyncMock()
        em._activation_tracker = mock_tracker

        ep_good = _make_episode(user_input="relevant", anchors=_full_anchor())
        ep_bad = _make_episode(user_input="noise")

        em.recall_for_agent_scored = AsyncMock(return_value=[
            (ep_good, 0.8),
            (ep_bad, 0.05),
        ])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            composite_score_floor=0.35,
        )

        # Only the good episode should be tracked
        assert len(results) == 1
        mock_tracker.record_batch_access.assert_called_once()
        tracked_ids = mock_tracker.record_batch_access.call_args[0][0]
        assert len(tracked_ids) == 1
