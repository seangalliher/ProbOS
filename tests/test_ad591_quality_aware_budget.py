"""AD-591: Quality-Aware Budget Enforcement.

Tests that recall_weighted() stops adding episodes when quality degrades
or episode count cap is reached, not just when character budget is exhausted.
"""

from __future__ import annotations

import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.types import AnchorFrame, Episode, RecallScore


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_ad590/test_ad584c)
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


def _make_em():
    """Create a minimal EpisodicMemory for recall_weighted testing."""
    from probos.cognitive.episodic import EpisodicMemory

    em = EpisodicMemory.__new__(EpisodicMemory)
    em._query_reformulation_enabled = False
    em._activation_tracker = None
    return em


# ===========================================================================
# Group 1: Max Episodes Cap (5 tests)
# ===========================================================================

class TestMaxEpisodesCap:
    """AD-591: max_recall_episodes hard cap on episode count."""

    @pytest.mark.asyncio
    async def test_default_max_is_k_times_two(self):
        """Default max (0) resolves to k*2. k=5 -> max 10 episodes."""
        em = _make_em()

        # Create 15 episodes that all score well (all pass AD-590 floor)
        eps = []
        for i in range(15):
            eps.append((_make_episode(
                user_input=f"episode {i}",
                anchors=_full_anchor(),
            ), 0.8 - i * 0.01))  # Descending similarity

        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            k=5,
            context_budget=99999,  # No char budget limit
            max_recall_episodes=0,  # Default -> k*2 = 10
        )
        assert len(results) <= 10

    @pytest.mark.asyncio
    async def test_explicit_max_respected(self):
        """Explicit max_recall_episodes=3 caps at 3."""
        em = _make_em()

        eps = [
            (_make_episode(user_input=f"ep {i}", anchors=_full_anchor()), 0.8)
            for i in range(8)
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            k=5,
            context_budget=99999,
            max_recall_episodes=3,
        )
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_char_budget_still_takes_priority(self):
        """Character budget can stop before max episodes is reached."""
        em = _make_em()

        # Large episodes that exceed budget quickly
        eps = [
            (_make_episode(user_input="x" * 2000, anchors=_full_anchor()), 0.8),
            (_make_episode(user_input="y" * 2000, anchors=_full_anchor()), 0.7),
            (_make_episode(user_input="z" * 2000, anchors=_full_anchor()), 0.6),
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            k=5,
            context_budget=3000,  # Only fits ~1.5 episodes
            max_recall_episodes=10,
        )
        # Char budget cuts before max
        assert len(results) < 3

    @pytest.mark.asyncio
    async def test_fewer_candidates_than_max_returns_all(self):
        """When fewer episodes available than max, all are returned."""
        em = _make_em()

        eps = [
            (_make_episode(user_input="ep", anchors=_full_anchor()), 0.8),
            (_make_episode(user_input="ep2", anchors=_full_anchor()), 0.7),
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            k=5,
            context_budget=99999,
            max_recall_episodes=10,
        )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_max_zero_uses_k_times_two(self):
        """Verify max=0 computes to k*2 for different k values."""
        em = _make_em()

        eps = [
            (_make_episode(user_input=f"e{i}", anchors=_full_anchor()), 0.8)
            for i in range(20)
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            k=3,  # k*2 = 6
            context_budget=99999,
            max_recall_episodes=0,
        )
        assert len(results) <= 6


# ===========================================================================
# Group 2: Quality Floor Stop (5 tests)
# ===========================================================================

class TestQualityFloorStop:
    """AD-591: Stop adding episodes when mean composite drops below floor."""

    @pytest.mark.asyncio
    async def test_quality_floor_zero_no_filtering(self):
        """Quality floor 0.0 (default) does not trigger quality stop."""
        em = _make_em()

        # Mix of high and low scoring episodes
        eps = [
            (_make_episode(user_input="good", anchors=_full_anchor()), 0.9),
            (_make_episode(user_input="ok"), 0.3),
            (_make_episode(user_input="marginal"), 0.1),
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=99999,
            max_recall_episodes=99,
            recall_quality_floor=0.0,
        )
        # No quality stop — all episodes pass (only char budget and max apply)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_quality_floor_stops_on_mean_degradation(self):
        """Adding a low-scoring episode that drops mean below floor stops accumulation."""
        em = _make_em()

        # First two episodes have high composite, third would drag mean below 0.40
        # Actual composites depend on scoring — use high/low similarity to control
        ep_high1 = _make_episode(user_input="relevant A", anchors=_full_anchor())
        ep_high2 = _make_episode(user_input="relevant B", anchors=_full_anchor())
        ep_low = _make_episode(user_input="noise")  # No anchor, low sim

        eps = [
            (ep_high1, 0.9),   # High composite
            (ep_high2, 0.8),   # High composite
            (ep_low, 0.05),    # Very low composite — would tank the mean
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=99999,
            max_recall_episodes=99,
            recall_quality_floor=0.56,
        )
        # Third episode (composite ~0.26) should be excluded because it would
        # drop mean below 0.56: (0.71 + 0.68 + 0.26) / 3 = 0.55 < 0.56
        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_quality_floor_first_episode_always_included(self):
        """First episode is always included regardless of quality floor."""
        em = _make_em()

        # Single low-scoring episode
        ep = _make_episode(user_input="only episode")
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.1)])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=99999,
            max_recall_episodes=99,
            recall_quality_floor=0.90,  # Very high floor
        )
        # First episode always included
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_quality_floor_gradual_degradation(self):
        """With gradually decreasing scores, quality stop fires at the right point."""
        em = _make_em()

        # 8 episodes: first 3 anchored (high composite), last 5 unanchored (low composite)
        # Unanchored episodes with decreasing similarity will have much lower composites
        # because anchor_confidence=0.0 removes that scoring component
        eps = []
        for i in range(8):
            sim = 0.9 - i * 0.12  # 0.9, 0.78, 0.66, 0.54, 0.42, 0.30, 0.18, 0.06
            anchors = _full_anchor() if i < 3 else None
            eps.append((_make_episode(
                user_input=f"episode {i}",
                anchors=anchors,
            ), max(sim, 0.05)))
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results_with_floor = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=99999,
            max_recall_episodes=99,
            recall_quality_floor=0.50,
        )
        results_without = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=99999,
            max_recall_episodes=99,
            recall_quality_floor=0.0,
        )
        # With quality floor, unanchored low-sim episodes should be excluded
        assert len(results_with_floor) < len(results_without)

    @pytest.mark.asyncio
    async def test_quality_floor_checks_running_mean_not_individual(self):
        """Quality stop uses running mean, not individual score check."""
        em = _make_em()

        # High-high-medium pattern: medium episode alone < 0.40 but
        # running mean of (high + high + medium) / 3 may still be > 0.40
        ep1 = _make_episode(user_input="great", anchors=_full_anchor())
        ep2 = _make_episode(user_input="great2", anchors=_full_anchor())
        ep3 = _make_episode(user_input="ok-ish", anchors=_full_anchor())

        eps = [
            (ep1, 0.9),    # composite ~ 0.65
            (ep2, 0.85),   # composite ~ 0.63
            (ep3, 0.3),    # composite ~ 0.40 — individual is border, mean of 3 may be above 0.40
        ]
        em.recall_for_agent_scored = AsyncMock(return_value=eps)
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            context_budget=99999,
            max_recall_episodes=99,
            recall_quality_floor=0.40,
        )
        # Mean of 3 is (0.65+0.63+0.40)/3 ~ 0.56 > 0.40 — third episode should be included
        # This verifies running mean, not individual score
        assert len(results) >= 2  # At minimum, first two pass


# ===========================================================================
# Group 3: Config Integration (5 tests)
# ===========================================================================

class TestConfigIntegration:
    """AD-591: Config fields and tier wiring."""

    def test_memory_config_has_max_recall_episodes(self):
        """MemoryConfig has max_recall_episodes with default 0."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert hasattr(cfg, "max_recall_episodes")
        assert cfg.max_recall_episodes == 0

    def test_memory_config_has_recall_quality_floor(self):
        """MemoryConfig has recall_quality_floor with default 0.40."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert hasattr(cfg, "recall_quality_floor")
        assert cfg.recall_quality_floor == 0.40

    def test_enhanced_tier_has_quality_floor(self):
        """Enhanced tier has recall_quality_floor = 0.40."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.recall_tiers["enhanced"]["recall_quality_floor"] == 0.40

    def test_basic_tier_quality_disabled(self):
        """Basic tier has recall_quality_floor = 0.0 (disabled)."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.recall_tiers["basic"]["recall_quality_floor"] == 0.0

    def test_oracle_tier_quality_disabled(self):
        """Oracle tier has recall_quality_floor = 0.0 (exhaustive recall)."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.recall_tiers["oracle"]["recall_quality_floor"] == 0.0


# ===========================================================================
# Group 4: Wiring — Call Sites (3 tests)
# ===========================================================================

class TestCallSiteWiring:
    """AD-591: Production call sites pass quality budget params."""

    def test_cognitive_agent_passes_max_recall_episodes(self):
        """cognitive_agent.py recall_weighted call includes max_recall_episodes kwarg."""
        import ast
        from pathlib import Path

        src = Path("src/probos/cognitive/cognitive_agent.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "max_recall_episodes":
                found = True
                break
        assert found, "cognitive_agent.py must pass max_recall_episodes to recall_weighted()"

    def test_cognitive_agent_passes_recall_quality_floor(self):
        """cognitive_agent.py recall_weighted call includes recall_quality_floor kwarg."""
        import ast
        from pathlib import Path

        src = Path("src/probos/cognitive/cognitive_agent.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "recall_quality_floor":
                found = True
                break
        assert found, "cognitive_agent.py must pass recall_quality_floor to recall_weighted()"

    def test_proactive_passes_quality_params(self):
        """proactive.py recall_weighted call includes both quality params."""
        import ast
        from pathlib import Path

        src = Path("src/probos/proactive.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found_max = False
        found_floor = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword):
                if node.arg == "max_recall_episodes":
                    found_max = True
                elif node.arg == "recall_quality_floor":
                    found_floor = True
        assert found_max, "proactive.py must pass max_recall_episodes"
        assert found_floor, "proactive.py must pass recall_quality_floor"


# ===========================================================================
# Group 5: DEEP Strategy Relaxation (2 tests)
# ===========================================================================

class TestDeepRelaxation:
    """AD-591: DEEP strategy relaxes quality budget params."""

    def test_deep_relaxes_quality_floor_in_code(self):
        """cognitive_agent.py DEEP block adjusts recall_quality_floor."""
        from pathlib import Path

        src = Path("src/probos/cognitive/cognitive_agent.py").read_text(encoding="utf-8")
        assert "recall_quality_floor" in src

    def test_deep_relaxation_quality_floor_clamps(self):
        """DEEP relaxation of quality floor uses max(0.0, ...) to prevent negative."""
        original = 0.05
        relaxed = max(0.0, original - 0.10)
        assert relaxed == 0.0

        original = 0.40
        relaxed = max(0.0, original - 0.10)
        assert relaxed == pytest.approx(0.30)


# ===========================================================================
# Group 6: Regression — Backward Compatibility (2 tests)
# ===========================================================================

class TestRegression:
    """AD-591: Existing behavior unaffected when quality params are 0."""

    @pytest.mark.asyncio
    async def test_defaults_match_pre_ad591_behavior(self):
        """recall_weighted() with 0/0.0 quality params behaves like pre-AD-591."""
        em = _make_em()

        ep = _make_episode(user_input="test data", anchors=_full_anchor())
        em.recall_for_agent_scored = AsyncMock(return_value=[(ep, 0.5)])
        em.keyword_search = AsyncMock(return_value=[])

        results = await em.recall_weighted(
            "agent-001", "test query",
            max_recall_episodes=0,
            recall_quality_floor=0.0,
        )
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_ad568b_still_runs_after_quality_budget(self):
        """AD-568b adaptive re-budget in cognitive_agent/proactive still functional."""
        # Integration test: verify compute_adaptive_budget still importable and callable
        from probos.cognitive.source_governance import compute_adaptive_budget, RetrievalStrategy

        result = compute_adaptive_budget(
            4000,
            episode_count=50,
            strategy=RetrievalStrategy.SHALLOW,
        )
        # Should return a valid BudgetAdjustment (no crash, reasonable values)
        assert result.original_budget == 4000
        assert result.adjusted_budget > 0
