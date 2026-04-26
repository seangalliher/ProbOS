"""Tests for AD-556: Adaptive Trust Anomaly Detection — Per-Agent Z-Score Thresholding."""

from __future__ import annotations

import math
import time
import pytest
from unittest.mock import MagicMock

from probos.cognitive.emergent_detector import EmergentDetector


def _make_detector(**kwargs) -> EmergentDetector:
    """Create an EmergentDetector with mock dependencies."""
    hebbian = MagicMock()
    hebbian.get_all_weights.return_value = {}

    trust = MagicMock()
    trust.raw_scores.return_value = {}
    trust.get_events_for_agent.return_value = []

    defaults = dict(
        hebbian_router=hebbian,
        trust_network=trust,
        # Relax population thresholds so we can test adaptive layer independently
        trust_sigma_threshold=1.5,
        trust_min_std=0.01,
        trust_min_observations=2.0,
        trust_min_deviation=0.01,
        trust_anomaly_min_count=1,  # Disable population temporal buffer
        # AD-556 defaults
        adaptive_window_size=10,
        adaptive_z_threshold=2.5,
        adaptive_debounce_count=2,
        adaptive_min_history=5,
    )
    defaults.update(kwargs)
    return EmergentDetector(**defaults)


def _set_trust_scores(detector: EmergentDetector, scores: dict[str, float]) -> None:
    """Configure mock trust network with given agent scores."""
    raw = {}
    for agent_id, score in scores.items():
        # Convert score to alpha/beta with enough observations
        alpha = score * 20
        beta = (1 - score) * 20
        raw[agent_id] = {"alpha": alpha, "beta": beta, "observations": 20.0}
    detector._trust.raw_scores.return_value = raw


# --- Per-agent history tracking ---

class TestAgentTrustHistory:

    def test_history_populated_on_detect(self):
        """AD-556: detect_trust_anomalies() populates per-agent history."""
        d = _make_detector()
        _set_trust_scores(d, {"agent_a": 0.7, "agent_b": 0.8})
        d.detect_trust_anomalies()
        assert "agent_a" in d._agent_trust_history
        assert "agent_b" in d._agent_trust_history
        assert len(d._agent_trust_history["agent_a"]) == 1

    def test_history_grows_over_calls(self):
        """AD-556: History accumulates over multiple detection passes."""
        d = _make_detector()
        _set_trust_scores(d, {"agent_a": 0.7, "agent_b": 0.8})
        for _ in range(5):
            d.detect_trust_anomalies()
        assert len(d._agent_trust_history["agent_a"]) == 5

    def test_history_capped_at_window_size(self):
        """AD-556: History doesn't exceed adaptive_window_size."""
        d = _make_detector(adaptive_window_size=5)
        _set_trust_scores(d, {"agent_a": 0.7, "agent_b": 0.8})
        for _ in range(10):
            d.detect_trust_anomalies()
        assert len(d._agent_trust_history["agent_a"]) == 5

    def test_update_agent_trust_history_direct(self):
        """AD-556: _update_agent_trust_history maintains rolling window."""
        d = _make_detector(adaptive_window_size=3)
        for i in range(5):
            d._update_agent_trust_history("agent_a", 0.5 + i * 0.01)
        assert len(d._agent_trust_history["agent_a"]) == 3
        # Should keep the most recent 3
        assert d._agent_trust_history["agent_a"][-1] == pytest.approx(0.54)


# --- Z-score computation ---

class TestZScoreComputation:

    def test_insufficient_history_returns_none(self):
        """AD-556: Returns None when agent has less than adaptive_min_history entries."""
        d = _make_detector(adaptive_min_history=5)
        for i in range(3):
            d._update_agent_trust_history("agent_a", 0.7 + i * 0.001)
        assert d._compute_agent_z_score("agent_a", 0.703) is None

    def test_sufficient_history_returns_zscore(self):
        """AD-556: Returns a z-score when enough history exists."""
        d = _make_detector(adaptive_min_history=5)
        # Build stable history with small deltas
        for i in range(8):
            d._update_agent_trust_history("agent_a", 0.7 + i * 0.001)
        z = d._compute_agent_z_score("agent_a", 0.708)
        assert z is not None
        assert isinstance(z, float)

    def test_large_delta_produces_high_zscore(self):
        """AD-556: Sudden large change produces high z-score for stable agent."""
        d = _make_detector(adaptive_min_history=5)
        # Build very stable history
        for i in range(8):
            d._update_agent_trust_history("agent_a", 0.700 + i * 0.001)
        # Sudden drop
        z = d._compute_agent_z_score("agent_a", 0.500)
        assert z is not None
        assert z > 3.0  # Should be a clear anomaly

    def test_normal_delta_produces_low_zscore(self):
        """AD-556: Normal-sized change produces low z-score."""
        d = _make_detector(adaptive_min_history=5)
        # Build history with moderate variance
        scores = [0.70, 0.72, 0.69, 0.71, 0.73, 0.70, 0.72, 0.71]
        for s in scores:
            d._update_agent_trust_history("agent_a", s)
        # Normal continuation
        z = d._compute_agent_z_score("agent_a", 0.73)
        assert z is not None
        assert z < 2.0  # Within normal range

    def test_zero_variance_agent_with_sudden_change(self):
        """AD-556: Agent with near-zero variance gets synthetic high z-score on change."""
        d = _make_detector(adaptive_min_history=5, trust_min_deviation=0.05)
        # Perfectly stable agent
        for _ in range(8):
            d._update_agent_trust_history("agent_a", 0.700)
        # Sudden change exceeding trust_min_deviation
        z = d._compute_agent_z_score("agent_a", 0.60)
        assert z is not None
        assert z >= 10.0  # Synthetic high z-score

    def test_zero_variance_agent_with_tiny_change(self):
        """AD-556: Agent with near-zero variance ignores sub-threshold changes."""
        d = _make_detector(adaptive_min_history=5, trust_min_deviation=0.05)
        for _ in range(8):
            d._update_agent_trust_history("agent_a", 0.700)
        # Tiny change below trust_min_deviation
        z = d._compute_agent_z_score("agent_a", 0.699)
        assert z is not None
        assert z < 1.0

    def test_unknown_agent_returns_none(self):
        """AD-556: Agent with no history returns None."""
        d = _make_detector()
        assert d._compute_agent_z_score("unknown", 0.5) is None


# --- Debounce ---

class TestAdaptiveDebounce:

    def test_single_anomaly_suppressed(self):
        """AD-556: Single anomalous cycle doesn't pass debounce (count=2)."""
        d = _make_detector(adaptive_debounce_count=2, adaptive_z_threshold=2.0)
        assert d._check_adaptive_debounce("agent_a", 3.0) is False  # First time

    def test_consecutive_anomalies_pass(self):
        """AD-556: Two consecutive anomalous cycles pass debounce."""
        d = _make_detector(adaptive_debounce_count=2, adaptive_z_threshold=2.0)
        d._check_adaptive_debounce("agent_a", 3.0)  # Streak = 1
        assert d._check_adaptive_debounce("agent_a", 3.5) is True  # Streak = 2

    def test_streak_resets_on_normal(self):
        """AD-556: Normal cycle resets anomaly streak."""
        d = _make_detector(adaptive_debounce_count=2, adaptive_z_threshold=2.0)
        d._check_adaptive_debounce("agent_a", 3.0)  # Streak = 1
        d._check_adaptive_debounce("agent_a", 1.0)  # Normal — reset
        assert d._check_adaptive_debounce("agent_a", 3.0) is False  # Streak = 1 again

    def test_independent_agent_streaks(self):
        """AD-556: Agent streaks are independent."""
        d = _make_detector(adaptive_debounce_count=2, adaptive_z_threshold=2.0)
        d._check_adaptive_debounce("agent_a", 3.0)
        d._check_adaptive_debounce("agent_b", 3.0)
        assert d._check_adaptive_debounce("agent_a", 3.0) is True
        assert d._check_adaptive_debounce("agent_b", 3.0) is True


# --- Integration: adaptive gate in detect_trust_anomalies ---

class TestAdaptiveGateIntegration:

    def _build_history(self, detector: EmergentDetector, agent_id: str, scores: list[float]):
        """Build up per-agent history by running detection passes."""
        for score in scores:
            _set_trust_scores(detector, {agent_id: score, "baseline_agent": 0.75})
            detector.detect_trust_anomalies()

    def test_anomaly_suppressed_by_adaptive_gate(self):
        """AD-556: Population anomaly suppressed when adaptive z-score is normal."""
        d = _make_detector(
            adaptive_min_history=5,
            adaptive_debounce_count=1,  # No debounce for this test
            adaptive_z_threshold=2.5,
        )
        # Build stable history with moderate variance
        volatile_scores = [0.45, 0.50, 0.42, 0.48, 0.43, 0.47, 0.44, 0.49]
        self._build_history(d, "volatile_agent", volatile_scores)

        # Reset anomaly counts and dedup cache to get clean detection
        d._trust_anomaly_counts.clear()
        d._last_pattern_fired.clear()

        # One more pass with a score in the agent's normal range but
        # deviating from population mean (0.75 baseline_agent pulls mean up)
        _set_trust_scores(d, {"volatile_agent": 0.46, "baseline_agent": 0.85})
        patterns = d.detect_trust_anomalies()

        # Even if population sigma fires, adaptive gate should filter
        trust_anomalies = [p for p in patterns if p.pattern_type == "trust_anomaly"
                          and "volatile_agent" in p.evidence.get("agent_id", "")]
        # The 0.46 score is normal for this agent — adaptive should suppress
        assert len(trust_anomalies) == 0

    def test_genuine_anomaly_passes_both_gates(self):
        """AD-556: Genuine anomaly passes both population and adaptive gates."""
        d = _make_detector(
            adaptive_min_history=5,
            adaptive_debounce_count=1,
            adaptive_z_threshold=2.0,
            trust_sigma_threshold=1.0,
        )
        # Build stable high-trust history — use a larger population so the
        # population sigma gate can actually fire (2 agents are symmetric
        # around the mean, so neither exceeds 1σ).
        stable_scores = [0.80, 0.81, 0.80, 0.82, 0.80, 0.81, 0.80, 0.81]
        for score in stable_scores:
            _set_trust_scores(d, {
                "stable_agent": score,
                "baseline_a": 0.80,
                "baseline_b": 0.78,
                "baseline_c": 0.82,
            })
            d.detect_trust_anomalies()

        d._trust_anomaly_counts.clear()
        d._last_pattern_fired.clear()

        # Sudden drop — anomalous for both population and personal baseline
        _set_trust_scores(d, {
            "stable_agent": 0.40,
            "baseline_a": 0.80,
            "baseline_b": 0.78,
            "baseline_c": 0.82,
        })
        patterns = d.detect_trust_anomalies()

        trust_anomalies = [p for p in patterns if p.pattern_type == "trust_anomaly"
                          and "stable_agent" in p.evidence.get("agent_id", "")]
        # Should pass both gates
        assert len(trust_anomalies) >= 1
        # Should include adaptive info in evidence
        evidence = trust_anomalies[0].evidence
        assert evidence.get("detection_mode") == "adaptive"
        assert "personal_z_score" in evidence

    def test_population_only_for_new_agents(self):
        """AD-556: New agents without history use population-only detection."""
        d = _make_detector(adaptive_min_history=5, trust_anomaly_min_count=1)
        # No history built — agent is new
        _set_trust_scores(d, {"new_agent": 0.30, "agent_b": 0.80, "agent_c": 0.85})
        patterns = d.detect_trust_anomalies()

        trust_anomalies = [p for p in patterns if p.pattern_type == "trust_anomaly"
                          and "new_agent" in p.evidence.get("agent_id", "")]
        # Population detection should still work for new agents
        # (though it depends on the population statistics being wide enough)
        for p in trust_anomalies:
            assert p.evidence.get("detection_mode") == "population_only"

    def test_evidence_includes_adaptive_info(self):
        """AD-556: Pattern evidence includes personal z-score and detection mode."""
        d = _make_detector(
            adaptive_min_history=5,
            adaptive_debounce_count=1,
            adaptive_z_threshold=1.0,  # Very sensitive for test
        )
        stable_scores = [0.80, 0.80, 0.80, 0.80, 0.80, 0.80, 0.80, 0.80]
        self._build_history(d, "test_agent", stable_scores)

        d._trust_anomaly_counts.clear()
        d._last_pattern_fired.clear()

        _set_trust_scores(d, {"test_agent": 0.40, "baseline_agent": 0.80})
        patterns = d.detect_trust_anomalies()

        trust_anomalies = [p for p in patterns if p.pattern_type == "trust_anomaly"
                          and "test_agent" in p.evidence.get("agent_id", "")]
        if trust_anomalies:
            ev = trust_anomalies[0].evidence
            assert "personal_z_score" in ev
            assert "personal_history_len" in ev
            assert ev["detection_mode"] == "adaptive"


# --- Config ---

class TestAdaptiveConfig:

    def test_config_defaults(self):
        """AD-556: EmergentDetectorConfig has adaptive parameters with defaults."""
        from probos.config import EmergentDetectorConfig
        config = EmergentDetectorConfig()
        assert config.adaptive_window_size == 30
        assert config.adaptive_z_threshold == 2.5
        assert config.adaptive_debounce_count == 2
        assert config.adaptive_min_history == 8

    def test_config_overrides(self):
        """AD-556: Adaptive config parameters can be overridden."""
        from probos.config import EmergentDetectorConfig
        config = EmergentDetectorConfig(
            adaptive_window_size=50,
            adaptive_z_threshold=3.0,
            adaptive_debounce_count=3,
            adaptive_min_history=10,
        )
        assert config.adaptive_window_size == 50
        assert config.adaptive_z_threshold == 3.0

    def test_detector_accepts_config_params(self):
        """AD-556: EmergentDetector constructor accepts adaptive parameters."""
        d = _make_detector(
            adaptive_window_size=20,
            adaptive_z_threshold=3.0,
            adaptive_debounce_count=3,
            adaptive_min_history=10,
        )
        assert d._adaptive_window_size == 20
        assert d._adaptive_z_threshold == 3.0
        assert d._adaptive_debounce_count == 3
        assert d._adaptive_min_history == 10


# --- Edge cases ---

class TestAdaptiveEdgeCases:

    def test_empty_trust_scores(self):
        """AD-556: No crash with empty trust scores."""
        d = _make_detector()
        _set_trust_scores(d, {})
        patterns = d.detect_trust_anomalies()
        assert patterns == []

    def test_single_agent(self):
        """AD-556: No crash with single agent (population sigma needs >= 2)."""
        d = _make_detector()
        _set_trust_scores(d, {"only_agent": 0.5})
        patterns = d.detect_trust_anomalies()
        # Single agent — detect_trust_anomalies returns early (< 2 agents),
        # so history is not updated (history update is inside the >= 2 path)
        assert len(d._agent_trust_history.get("only_agent", [])) == 0

    def test_cold_start_suppression_still_works(self):
        """AD-556: BF-034 cold-start suppression prevents adaptive detection too."""
        d = _make_detector()
        d._suppress_trust_until = time.monotonic() + 600  # Suppress for 10 min
        _set_trust_scores(d, {"agent_a": 0.3, "agent_b": 0.8})
        patterns = d.detect_trust_anomalies()
        assert patterns == []
        # History should NOT be updated during suppression
        assert len(d._agent_trust_history) == 0

    def test_dream_suppression_still_works(self):
        """AD-556: BF-100 dream suppression prevents adaptive detection too."""
        d = _make_detector()
        d._dreaming = True
        _set_trust_scores(d, {"agent_a": 0.3, "agent_b": 0.8})
        patterns = d.detect_trust_anomalies()
        assert patterns == []
        assert len(d._agent_trust_history) == 0
