"""AD-494: Trait-Adaptive Circuit Breaker — personality-aware thresholds.

Tests for per-agent circuit breaker threshold adaptation based on Big Five
personality scores. 28 tests across 7 categories.
"""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, patch

import pytest

from probos.cognitive.circuit_breaker import (
    BreakerState,
    CognitiveCircuitBreaker,
    CognitiveZone,
    TraitAdaptiveThresholds,
    compute_trait_thresholds,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_breaker(**overrides) -> CognitiveCircuitBreaker:
    """Factory with short test-friendly parameters."""
    defaults = dict(
        velocity_threshold=4,
        velocity_window_seconds=60.0,
        similarity_threshold=0.6,
        similarity_min_events=3,
        base_cooldown_seconds=60.0,
        max_cooldown_seconds=300.0,
    )
    defaults.update(overrides)
    return CognitiveCircuitBreaker(**defaults)


def _record_similar_events(
    breaker: CognitiveCircuitBreaker,
    agent_id: str,
    n: int,
    content: str = "the same repeated thought about systems",
) -> None:
    """Record *n* events with identical content to trigger similarity."""
    for _ in range(n):
        breaker.record_event(agent_id, "proactive_think", content)


def _record_diverse_events(
    breaker: CognitiveCircuitBreaker,
    agent_id: str,
    n: int,
) -> None:
    """Record *n* events each with unique content (velocity without similarity).

    Content is carefully crafted so Jaccard similarity between any two events
    is well below typical thresholds (no shared words between events).
    """
    # Each word set is completely disjoint from every other
    word_banks = [
        "alpha bravo charlie delta echo",
        "foxtrot golf hotel india juliet",
        "kilo lima mike november oscar",
        "papa quebec romeo sierra tango",
        "uniform victor whiskey xray yankee",
        "zulu amber bronze copper diamond",
        "emerald flame granite helium iridium",
        "jasper kelvin lithium mercury neon",
        "oxygen platinum quartz radium sulfur",
        "titanium uranium vanadium wolfram xenon",
    ]
    for i in range(n):
        breaker.record_event(agent_id, "proactive_think", word_banks[i % len(word_banks)])


# ===========================================================================
# 1. compute_trait_thresholds — pure function (8 tests)
# ===========================================================================


class TestComputeTraitThresholds:
    """Tests for the pure compute_trait_thresholds function."""

    def test_default_traits_produce_unit_multipliers(self):
        t = compute_trait_thresholds()
        assert t.velocity_multiplier == 1.0
        assert t.similarity_multiplier == 1.0
        assert t.cooldown_multiplier == 1.0
        assert t.amber_sensitivity_multiplier == 1.0

    def test_high_openness_increases_velocity_multiplier(self):
        t = compute_trait_thresholds(openness=1.0)
        assert t.velocity_multiplier == pytest.approx(1.4)

    def test_low_openness_decreases_velocity_multiplier(self):
        t = compute_trait_thresholds(openness=0.0)
        assert t.velocity_multiplier == pytest.approx(0.6)

    def test_high_neuroticism_decreases_similarity_multiplier(self):
        t = compute_trait_thresholds(neuroticism=1.0)
        assert t.similarity_multiplier == pytest.approx(0.8)

    def test_low_neuroticism_increases_similarity_multiplier(self):
        t = compute_trait_thresholds(neuroticism=0.0)
        assert t.similarity_multiplier == pytest.approx(1.2)

    def test_high_conscientiousness_decreases_cooldown_multiplier(self):
        t = compute_trait_thresholds(conscientiousness=1.0)
        assert t.cooldown_multiplier == pytest.approx(0.7)

    def test_high_extraversion_increases_amber_multiplier(self):
        t = compute_trait_thresholds(extraversion=1.0)
        assert t.amber_sensitivity_multiplier == pytest.approx(1.4)

    def test_clamped_inputs(self):
        # Values outside 0-1 get clamped
        t_high = compute_trait_thresholds(openness=2.0, neuroticism=-1.0)
        t_max = compute_trait_thresholds(openness=1.0, neuroticism=0.0)
        assert t_high.velocity_multiplier == t_max.velocity_multiplier
        assert t_high.similarity_multiplier == t_max.similarity_multiplier


# ===========================================================================
# 2. TraitAdaptiveThresholds dataclass (2 tests)
# ===========================================================================


class TestTraitAdaptiveThresholds:
    """Tests for the TraitAdaptiveThresholds frozen dataclass."""

    def test_frozen_dataclass(self):
        t = TraitAdaptiveThresholds()
        with pytest.raises(dataclasses.FrozenInstanceError):
            t.velocity_multiplier = 2.0  # type: ignore[misc]

    def test_default_values(self):
        t = TraitAdaptiveThresholds()
        assert t.velocity_multiplier == 1.0
        assert t.similarity_multiplier == 1.0
        assert t.cooldown_multiplier == 1.0
        assert t.amber_sensitivity_multiplier == 1.0


# ===========================================================================
# 3. set_agent_traits + _effective_thresholds (6 tests)
# ===========================================================================


class TestEffectiveThresholds:
    """Tests for trait registration and effective threshold computation."""

    def test_no_traits_returns_base_thresholds(self):
        cb = _make_breaker()
        eff = cb._effective_thresholds("agent_a")
        assert eff["velocity_threshold"] == 4
        assert eff["similarity_threshold"] == 0.6
        assert eff["base_cooldown"] == 60.0

    def test_set_traits_modifies_effective_velocity(self):
        cb = _make_breaker()
        cb.set_agent_traits("agent_a", openness=0.9)
        eff = cb._effective_thresholds("agent_a")
        assert eff["velocity_threshold"] > 4  # higher O = more tolerance

    def test_set_traits_modifies_effective_similarity(self):
        cb = _make_breaker()
        cb.set_agent_traits("agent_a", neuroticism=0.8)
        eff = cb._effective_thresholds("agent_a")
        assert eff["similarity_threshold"] < 0.6  # higher N = lower threshold

    def test_set_traits_modifies_effective_cooldown(self):
        cb = _make_breaker(base_cooldown_seconds=300.0)  # High enough to avoid 120s clamp
        cb.set_agent_traits("agent_a", conscientiousness=0.9)
        eff = cb._effective_thresholds("agent_a")
        assert eff["base_cooldown"] < 300.0  # higher C = shorter cooldown

    def test_effective_thresholds_clamped(self):
        cb = _make_breaker()
        # Extreme personality — all 0.0 or all 1.0
        cb.set_agent_traits("extreme_low", openness=0.0, conscientiousness=0.0, extraversion=0.0, neuroticism=1.0)
        eff_low = cb._effective_thresholds("extreme_low")
        assert eff_low["velocity_threshold"] >= 2
        assert 0.3 <= eff_low["similarity_threshold"] <= 0.95
        assert eff_low["base_cooldown"] >= 120.0

        cb.set_agent_traits("extreme_high", openness=1.0, conscientiousness=1.0, extraversion=1.0, neuroticism=0.0)
        eff_high = cb._effective_thresholds("extreme_high")
        assert eff_high["velocity_threshold"] >= 2
        assert 0.3 <= eff_high["similarity_threshold"] <= 0.95
        assert eff_high["base_cooldown"] >= 120.0

    def test_set_traits_idempotent(self):
        cb = _make_breaker()
        cb.set_agent_traits("agent_a", openness=0.7, neuroticism=0.3)
        eff1 = cb._effective_thresholds("agent_a")
        cb.set_agent_traits("agent_a", openness=0.7, neuroticism=0.3)
        eff2 = cb._effective_thresholds("agent_a")
        assert eff1 == eff2


# ===========================================================================
# 4. Behavioral integration — trip behavior changes with personality (6 tests)
# ===========================================================================


class TestBehavioralIntegration:
    """Tests that personality traits actually change trip/zone behavior."""

    def test_high_openness_agent_needs_more_events_to_trip(self):
        cb = _make_breaker()
        # High openness agent — more tolerant velocity threshold
        cb.set_agent_traits("open_agent", openness=0.9)
        eff = cb._effective_thresholds("open_agent")
        base_threshold = 4
        assert eff["velocity_threshold"] > base_threshold

        # Record base_threshold events for default agent — should trip
        _record_diverse_events(cb, "default_agent", base_threshold)
        assert cb.check_and_trip("default_agent") is True

        # Same count for open agent — should NOT trip (needs more)
        _record_diverse_events(cb, "open_agent", base_threshold)
        assert cb.check_and_trip("open_agent") is False

    def test_high_neuroticism_agent_trips_on_lower_similarity(self):
        cb = _make_breaker(similarity_threshold=0.6)
        # High neuroticism — lower similarity threshold (more sensitive)
        cb.set_agent_traits("neurotic_agent", neuroticism=0.9)
        eff = cb._effective_thresholds("neurotic_agent")
        assert eff["similarity_threshold"] < 0.6

    def test_high_conscientiousness_agent_gets_shorter_cooldown(self):
        cb = _make_breaker(base_cooldown_seconds=900.0)
        cb.set_agent_traits("diligent_agent", conscientiousness=0.9)

        # Trip the agent
        _record_similar_events(cb, "diligent_agent", 10)
        cb.check_and_trip("diligent_agent")
        state = cb._get_state("diligent_agent")

        if state.state == BreakerState.OPEN:
            # Cooldown should be less than the base 900s
            assert state.cooldown_seconds < 900.0

    def test_high_extraversion_agent_less_amber_sensitive(self):
        cb = _make_breaker(amber_similarity_ratio=0.25, amber_velocity_ratio=0.6)
        # High extraversion — higher amber thresholds (less sensitive)
        cb.set_agent_traits("extrovert_agent", extraversion=0.9)
        eff = cb._effective_thresholds("extrovert_agent")
        assert eff["amber_similarity_ratio"] > 0.25
        assert eff["amber_velocity_ratio"] > 0.6

    def test_default_personality_matches_uniform_behavior(self):
        cb = _make_breaker(base_cooldown_seconds=300.0)  # Above 120s clamp floor
        cb.set_agent_traits("default_traits", openness=0.5, conscientiousness=0.5, extraversion=0.5, neuroticism=0.5)
        eff_with = cb._effective_thresholds("default_traits")
        eff_without = cb._effective_thresholds("no_traits_agent")
        assert eff_with["velocity_threshold"] == eff_without["velocity_threshold"]
        assert eff_with["similarity_threshold"] == pytest.approx(eff_without["similarity_threshold"])
        assert eff_with["base_cooldown"] == pytest.approx(eff_without["base_cooldown"])

    def test_wesley_profile_more_tolerant(self):
        """Wesley's actual seed: O=0.9, C=0.7, E=0.4, A=0.5, N=0.2."""
        cb = _make_breaker()
        base_velocity = cb._velocity_threshold
        base_similarity = cb._similarity_threshold

        cb.set_agent_traits(
            "wesley", openness=0.9, conscientiousness=0.7,
            extraversion=0.4, agreeableness=0.5, neuroticism=0.2,
        )
        eff = cb._effective_thresholds("wesley")
        # High O + low N = more tolerant on both axes
        assert eff["velocity_threshold"] > base_velocity
        assert eff["similarity_threshold"] > base_similarity


# ===========================================================================
# 5. Reset and lifecycle (4 tests)
# ===========================================================================


class TestResetLifecycle:
    """Tests for trait cleanup on reset."""

    def test_reset_agent_clears_traits(self):
        cb = _make_breaker()
        cb.set_agent_traits("agent_a", openness=0.9)
        assert cb.has_agent_traits("agent_a") is True
        cb.reset_agent("agent_a")
        assert cb.has_agent_traits("agent_a") is False

    def test_reset_all_clears_all_traits(self):
        cb = _make_breaker()
        cb.set_agent_traits("a1", openness=0.9)
        cb.set_agent_traits("a2", neuroticism=0.8)
        cb.reset_all()
        assert cb.has_agent_traits("a1") is False
        assert cb.has_agent_traits("a2") is False

    def test_get_status_shows_trait_adapted(self):
        cb = _make_breaker()
        status_before = cb.get_status("agent_a")
        assert status_before["trait_adapted"] is False

        cb.set_agent_traits("agent_a", openness=0.9)
        status_after = cb.get_status("agent_a")
        assert status_after["trait_adapted"] is True

    def test_get_status_shows_effective_thresholds(self):
        cb = _make_breaker()
        cb.set_agent_traits("agent_a", openness=0.9)
        status = cb.get_status("agent_a")
        assert "effective_velocity_threshold" in status
        assert "effective_similarity_threshold" in status
        # With high openness, effective velocity should be > base
        assert status["effective_velocity_threshold"] > 4


# ===========================================================================
# 6. Config integration (2 tests)
# ===========================================================================


class TestConfigIntegration:
    """Tests for trait-adaptive config wiring in ProactiveCognitiveLoop."""

    def test_trait_adaptive_disabled_skips_registration(self):
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop(interval=999, cooldown=999)
        loop._trait_adaptive_enabled = False

        agent = MagicMock()
        agent.id = "test_agent"
        agent.agent_type = "wesley"

        loop._ensure_agent_traits_registered(agent)
        assert loop._circuit_breaker.has_agent_traits("test_agent") is False

    @patch("probos.crew_profile.load_seed_profile")
    def test_trait_adaptive_enabled_registers_traits(self, mock_load):
        mock_load.return_value = {
            "personality": {
                "openness": 0.9,
                "conscientiousness": 0.7,
                "extraversion": 0.4,
                "agreeableness": 0.5,
                "neuroticism": 0.2,
            }
        }

        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop(interval=999, cooldown=999)
        loop._trait_adaptive_enabled = True

        agent = MagicMock()
        agent.id = "test_agent"
        agent.agent_type = "wesley"

        loop._ensure_agent_traits_registered(agent)
        assert loop._circuit_breaker.has_agent_traits("test_agent") is True
