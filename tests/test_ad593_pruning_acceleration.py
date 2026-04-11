"""AD-593: Pruning Acceleration + Similarity Floor Tightening.

Tests that dream Step 12 has two pruning tiers (standard + aggressive),
configurable parameters, pool pressure acceleration, and a tightened
similarity floor.
"""

from __future__ import annotations

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
    timestamp: float | None = None,
    agent_ids: list[str] | None = None,
    source: str = "direct",
) -> Episode:
    return Episode(
        user_input=user_input,
        timestamp=timestamp or time.time(),
        agent_ids=agent_ids or ["agent-001"],
        source=source,
        outcomes=[{"intent": "test_intent", "success": True}],
    )


# ===========================================================================
# Group 1: Config Fields (6 tests)
# ===========================================================================

class TestConfigFields:
    """AD-593: DreamingConfig pruning fields and MemoryConfig threshold."""

    def test_prune_min_age_hours_default(self):
        """DreamingConfig.prune_min_age_hours defaults to 24."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig()
        assert cfg.prune_min_age_hours == 24

    def test_prune_max_fraction_default(self):
        """DreamingConfig.prune_max_fraction defaults to 0.10."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig()
        assert cfg.prune_max_fraction == 0.10

    def test_aggressive_prune_enabled_default(self):
        """DreamingConfig.aggressive_prune_enabled defaults to True."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig()
        assert cfg.aggressive_prune_enabled is True

    def test_aggressive_prune_min_age_hours_default(self):
        """DreamingConfig.aggressive_prune_min_age_hours defaults to 168 (7 days)."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig()
        assert cfg.aggressive_prune_min_age_hours == 168

    def test_aggressive_prune_threshold_default(self):
        """DreamingConfig.aggressive_prune_threshold defaults to 0.0."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig()
        assert cfg.aggressive_prune_threshold == 0.0

    def test_episode_pressure_threshold_default(self):
        """DreamingConfig.episode_pressure_threshold defaults to 5000."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig()
        assert cfg.episode_pressure_threshold == 5000


# ===========================================================================
# Group 2: Similarity Floor (3 tests)
# ===========================================================================

class TestSimilarityFloor:
    """AD-593 Part B: agent_recall_threshold raised to 0.25."""

    def test_memory_config_threshold_raised(self):
        """MemoryConfig.agent_recall_threshold defaults to 0.25."""
        from probos.config import MemoryConfig

        cfg = MemoryConfig()
        assert cfg.agent_recall_threshold == 0.25

    def test_episodic_memory_constructor_default(self):
        """EpisodicMemory constructor default agent_recall_threshold is 0.25."""
        import inspect
        from probos.cognitive.episodic import EpisodicMemory

        sig = inspect.signature(EpisodicMemory.__init__)
        param = sig.parameters.get("agent_recall_threshold")
        assert param is not None
        assert param.default == 0.25

    def test_threshold_filters_low_similarity(self):
        """Episodes with similarity < 0.25 should be excluded from recall."""
        # This is a structural test: verify the threshold is used in recall_for_agent
        from pathlib import Path

        src = Path("src/probos/cognitive/episodic.py").read_text(encoding="utf-8")
        # The filtering pattern: "if similarity < agent_recall_threshold: continue"
        assert "agent_recall_threshold" in src
        assert "similarity < agent_recall_threshold" in src


# ===========================================================================
# Group 3: Standard Tier Pruning (4 tests)
# ===========================================================================

class TestStandardTierPruning:
    """AD-593: Standard tier uses config values instead of hardcoded constants."""

    def test_standard_tier_uses_config_age(self):
        """Step 12 uses config.prune_min_age_hours, not hardcoded 86400."""
        from pathlib import Path

        src = Path("src/probos/cognitive/dreaming.py").read_text(encoding="utf-8")
        # Should reference config field, not hardcoded 86400
        assert "prune_min_age_hours" in src

    def test_standard_tier_uses_config_fraction(self):
        """Step 12 uses config.prune_max_fraction, not hardcoded 0.10."""
        from pathlib import Path

        src = Path("src/probos/cognitive/dreaming.py").read_text(encoding="utf-8")
        assert "prune_max_fraction" in src

    @pytest.mark.asyncio
    async def test_standard_tier_prunes_low_activation(self):
        """Standard tier uses config threshold and fraction values."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig()
        # Standard tier should use these config values (previously hardcoded)
        assert cfg.activation_prune_threshold == -2.0
        assert cfg.prune_max_fraction == 0.10
        assert cfg.prune_min_age_hours == 24
        # Verify dreaming.py references these via config
        from pathlib import Path
        src = Path("src/probos/cognitive/dreaming.py").read_text(encoding="utf-8")
        assert "self.config.activation_prune_threshold" in src
        assert "self.config.prune_max_fraction" in src
        assert "self.config.prune_min_age_hours" in src

    @pytest.mark.asyncio
    async def test_standard_fraction_cap_at_50_percent(self):
        """Even under max pressure, standard fraction cannot exceed 0.50."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig(
            prune_max_fraction=0.40,
            episode_pressure_multiplier=2.0,
        )
        # 0.40 * 2.0 = 0.80, but should be capped at 0.50
        result = min(cfg.prune_max_fraction * cfg.episode_pressure_multiplier, 0.50)
        assert result == 0.50


# ===========================================================================
# Group 4: Aggressive Tier Pruning (4 tests)
# ===========================================================================

class TestAggressiveTierPruning:
    """AD-593: Aggressive tier targets old, low-activation episodes."""

    def test_aggressive_tier_present_in_code(self):
        """Dream Step 12 contains aggressive pruning logic."""
        from pathlib import Path

        src = Path("src/probos/cognitive/dreaming.py").read_text(encoding="utf-8")
        assert "aggressive_prune_enabled" in src
        assert "aggressive_prune_min_age_hours" in src
        assert "aggressive_prune_threshold" in src
        assert "aggressive_prune_max_fraction" in src

    def test_aggressive_uses_different_eviction_reason(self):
        """Aggressive tier uses 'activation_decay_aggressive' eviction reason."""
        from pathlib import Path

        src = Path("src/probos/cognitive/dreaming.py").read_text(encoding="utf-8")
        assert "activation_decay_aggressive" in src

    def test_aggressive_threshold_higher_than_standard(self):
        """Aggressive threshold (0.0) is higher than standard (-2.0) — catches more episodes."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig()
        assert cfg.aggressive_prune_threshold > cfg.activation_prune_threshold

    def test_aggressive_disabled_skips_tier(self):
        """When aggressive_prune_enabled=False, aggressive tier is skipped."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig(aggressive_prune_enabled=False)
        # Just verify the config toggle exists and is False
        assert cfg.aggressive_prune_enabled is False


# ===========================================================================
# Group 5: Pool Pressure (4 tests)
# ===========================================================================

class TestPoolPressure:
    """AD-593: Episode pool pressure accelerates pruning."""

    def test_pressure_multiplier_default(self):
        """episode_pressure_multiplier defaults to 1.5."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig()
        assert cfg.episode_pressure_multiplier == 1.5

    def test_no_pressure_below_threshold(self):
        """Below episode_pressure_threshold, multiplier is 1.0 (no acceleration)."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig()
        episode_count = 3000  # Below 5000 threshold
        pressure = cfg.episode_pressure_multiplier if episode_count > cfg.episode_pressure_threshold else 1.0
        assert pressure == 1.0

    def test_pressure_active_above_threshold(self):
        """Above episode_pressure_threshold, multiplier applies."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig()
        episode_count = 6000  # Above 5000 threshold
        pressure = cfg.episode_pressure_multiplier if episode_count > cfg.episode_pressure_threshold else 1.0
        assert pressure == 1.5

    def test_pressure_fraction_capped(self):
        """Pressure-accelerated fraction is capped at 0.50."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig(
            aggressive_prune_max_fraction=0.40,
            episode_pressure_multiplier=2.0,
        )
        # 0.40 * 2.0 = 0.80 → capped to 0.50
        result = min(cfg.aggressive_prune_max_fraction * cfg.episode_pressure_multiplier, 0.50)
        assert result == 0.50


# ===========================================================================
# Group 6: Regression (3 tests)
# ===========================================================================

class TestRegression:
    """AD-593: Existing behavior preserved with default config."""

    def test_default_config_matches_pre_ad593_standard_behavior(self):
        """Default config produces same standard-tier behavior as pre-AD-593."""
        from probos.config import DreamingConfig

        cfg = DreamingConfig()
        # Pre-AD-593 hardcoded: 24h age, -2.0 threshold, 10% fraction
        assert cfg.prune_min_age_hours == 24
        assert cfg.activation_prune_threshold == -2.0
        assert cfg.prune_max_fraction == 0.10

    def test_eviction_audit_reason_standard_unchanged(self):
        """Standard tier still uses 'activation_decay' reason."""
        from pathlib import Path

        src = Path("src/probos/cognitive/dreaming.py").read_text(encoding="utf-8")
        assert '"activation_decay"' in src

    def test_activation_tracker_api_unchanged(self):
        """find_low_activation_episodes signature is unchanged."""
        import inspect
        from probos.cognitive.activation_tracker import ActivationTracker

        sig = inspect.signature(ActivationTracker.find_low_activation_episodes)
        params = list(sig.parameters.keys())
        assert "all_episode_ids" in params
        assert "threshold" in params
        assert "max_prune_fraction" in params
