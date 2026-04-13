"""BF-166: Consolidation anomaly false positives after stasis."""

import collections
import time

from probos.cognitive.emergent_detector import EmergentDetector
from probos.types import DreamReport

# Re-use the existing test helper for creating detectors with mock deps.
# _make_detector() passes **kwargs through to EmergentDetector.
from tests.test_emergent_detector import _make_detector


class TestConsolidationMinHistory:
    """Part A: Minimum history gate raised to 5."""

    def test_no_anomaly_with_fewer_than_5_reports(self):
        """4 reports should never trigger anomalies, even with variance."""
        d = _make_detector()
        # First 3 reports: low values
        for _ in range(3):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=1, weights_pruned=1, trust_adjustments=0)
            )
        # 4th report: 100x spike — should NOT fire because < 5 history
        patterns = d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=100, weights_pruned=100, trust_adjustments=100)
        )
        assert patterns == []

    def test_anomaly_fires_after_5_reports(self):
        """With 5 baseline reports, a spike on the 6th should fire."""
        d = _make_detector()
        for _ in range(5):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=5, weights_pruned=3, trust_adjustments=2)
            )
        # 6th report: big spike
        patterns = d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=50, weights_pruned=30, trust_adjustments=20)
        )
        assert len(patterns) > 0
        assert all(p.pattern_type == "consolidation_anomaly" for p in patterns)

    def test_configurable_min_history(self):
        """dream_min_history parameter controls the gate."""
        d = _make_detector(dream_min_history=3)
        for _ in range(3):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=5, weights_pruned=3, trust_adjustments=2)
            )
        patterns = d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=50, weights_pruned=3, trust_adjustments=2)
        )
        assert len(patterns) > 0


class TestConsolidationColdStartSuppression:
    """Part B: Cold-start suppression for dream anomalies."""

    def test_suppressed_during_cold_start_window(self):
        """No dream anomalies during suppression window."""
        d = _make_detector()
        d.set_cold_start_suppression(300.0)
        # Build enough history
        for _ in range(6):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=5, weights_pruned=3, trust_adjustments=2)
            )
        # Spike during suppression — should be suppressed
        patterns = d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=50, weights_pruned=3, trust_adjustments=2)
        )
        assert patterns == []

    def test_fires_after_suppression_expires(self):
        """Dream anomalies fire after suppression window expires."""
        d = _make_detector()
        d.set_cold_start_suppression(0.01)  # Near-instant expiry
        time.sleep(0.02)
        # Build baseline after suppression expires
        for _ in range(5):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=5, weights_pruned=3, trust_adjustments=2)
            )
        patterns = d.detect_consolidation_anomalies(
            DreamReport(weights_strengthened=50, weights_pruned=3, trust_adjustments=2)
        )
        assert len(patterns) > 0

    def test_cold_start_suppression_includes_dreams(self):
        """set_cold_start_suppression() sets _suppress_dreams_until."""
        d = _make_detector()
        d.set_cold_start_suppression(300.0)
        assert d._suppress_dreams_until > time.monotonic()


class TestDreamHistoryBounded:
    """Part C: _dream_history uses deque with maxlen."""

    def test_dream_history_is_bounded(self):
        """_dream_history should not grow beyond max_history."""
        d = _make_detector()
        assert isinstance(d._dream_history, collections.deque)
        assert d._dream_history.maxlen is not None

    def test_dream_history_evicts_oldest(self):
        """Old entries are evicted when maxlen exceeded."""
        d = _make_detector(max_history=10)
        for i in range(20):
            d.detect_consolidation_anomalies(
                DreamReport(weights_strengthened=i, weights_pruned=0, trust_adjustments=0)
            )
        assert len(d._dream_history) == 10
        # Oldest entries evicted — first entry should NOT be 0
        assert d._dream_history[0]["weights_strengthened"] >= 10
