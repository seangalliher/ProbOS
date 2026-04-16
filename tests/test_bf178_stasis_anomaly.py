"""BF-178: Consolidation anomaly false positives during micro-stasis recovery.

After short stasis periods, stale dream history causes false consolidation_anomaly
events. Fix: clear dream history on stasis recovery + short suppression window.
"""

from __future__ import annotations

import collections
from unittest.mock import MagicMock

import pytest

from probos.cognitive.emergent_detector import EmergentDetector


class TestClearDreamHistory:
    """Test clear_dream_history() method."""

    def test_clear_empties_deque(self):
        """clear_dream_history() empties _dream_history."""
        detector = EmergentDetector.__new__(EmergentDetector)
        detector._dream_history = collections.deque(maxlen=50)
        detector._dream_history.append({"weights_strengthened": 5})
        detector._dream_history.append({"weights_strengthened": 10})
        assert len(detector._dream_history) == 2
        detector.clear_dream_history()
        assert len(detector._dream_history) == 0

    def test_clear_forces_min_history_gate(self):
        """After clear, detect_consolidation_anomalies returns empty until min history met."""
        detector = EmergentDetector.__new__(EmergentDetector)
        detector._dream_history = collections.deque(maxlen=50)
        detector._dream_min_history = 5
        detector._suppress_dreams_until = 0
        detector._dream_anomaly_min_strengthened = 10
        detector._dream_anomaly_min_pruned = 5
        detector._dream_anomaly_min_trust_adj = 10
        # Pre-populate 6 reports (above min_history)
        for _ in range(6):
            detector._dream_history.append({
                "weights_strengthened": 5, "weights_pruned": 2,
                "trust_adjustments": 3, "pre_warm_intents": [],
            })
        assert len(detector._dream_history) == 6
        detector.clear_dream_history()
        # First report after clear should return empty (below min_history)
        result = detector.detect_consolidation_anomalies({
            "weights_strengthened": 100, "weights_pruned": 50,
            "trust_adjustments": 100, "pre_warm_intents": [],
        })
        assert result == []

    def test_clear_is_idempotent(self):
        """Clearing an already-empty history is safe."""
        detector = EmergentDetector.__new__(EmergentDetector)
        detector._dream_history = collections.deque(maxlen=50)
        detector.clear_dream_history()
        assert len(detector._dream_history) == 0


class TestStasisRecoverySuppressionLogic:
    """Test the suppression logic that should fire on stasis recovery."""

    def test_stasis_recovery_triggers_clear_and_suppress(self):
        """Simulates what init_dreaming does: clear + 60s suppression."""
        detector = EmergentDetector(
            hebbian_router=MagicMock(),
            trust_network=MagicMock(),
        )
        # Accumulate stale history
        for _ in range(6):
            detector._dream_history.append({
                "weights_strengthened": 3, "weights_pruned": 1,
                "trust_adjustments": 2, "pre_warm_intents": [],
            })
        # Simulate stasis recovery actions
        detector.clear_dream_history()
        detector.set_cold_start_suppression(60)

        # Post-stasis dream with inflated counts — suppressed + no history
        result = detector.detect_consolidation_anomalies({
            "weights_strengthened": 50, "weights_pruned": 20,
            "trust_adjustments": 40, "pre_warm_intents": [],
        })
        assert result == []
        # History still accumulates during suppression
        assert len(detector._dream_history) == 0  # suppression returns before append

    def test_without_fix_stale_history_causes_false_positive(self):
        """Without clearing, stale low baseline + spike = false anomaly."""
        detector = EmergentDetector(
            hebbian_router=MagicMock(),
            trust_network=MagicMock(),
        )
        # Accumulate 6 low-activity stale reports
        for _ in range(6):
            detector.detect_consolidation_anomalies({
                "weights_strengthened": 5, "weights_pruned": 2,
                "trust_adjustments": 4, "pre_warm_intents": [],
            })
        # No clear, no suppression — simulates old behavior
        # Post-stasis spike: 50 strengthened vs avg 5 = 10x, above floor of 10
        result = detector.detect_consolidation_anomalies({
            "weights_strengthened": 50, "weights_pruned": 20,
            "trust_adjustments": 40, "pre_warm_intents": [],
        })
        # This WOULD have been a false positive in the old code
        assert len(result) > 0  # confirms the bug scenario

    def test_with_fix_same_scenario_no_anomaly(self):
        """With clearing, same spike scenario produces no anomaly."""
        detector = EmergentDetector(
            hebbian_router=MagicMock(),
            trust_network=MagicMock(),
        )
        # Accumulate 6 low-activity stale reports
        for _ in range(6):
            detector.detect_consolidation_anomalies({
                "weights_strengthened": 5, "weights_pruned": 2,
                "trust_adjustments": 4, "pre_warm_intents": [],
            })
        # Apply fix
        detector.clear_dream_history()
        detector.set_cold_start_suppression(60)

        # Same spike — now suppressed
        result = detector.detect_consolidation_anomalies({
            "weights_strengthened": 50, "weights_pruned": 20,
            "trust_adjustments": 40, "pre_warm_intents": [],
        })
        assert result == []

