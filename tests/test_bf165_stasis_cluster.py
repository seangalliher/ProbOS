"""BF-165: Cooperation cluster false positives during stasis.

Tests the cognitive activity gate that suppresses cluster detection
when no Hebbian interactions have occurred within the activity window.
"""

import time
from unittest.mock import MagicMock

import pytest

from probos.cognitive.emergent_detector import EmergentDetector
from probos.config import EmergentDetectorConfig


REL_INTENT = "intent"


def _make_detector(**kwargs) -> EmergentDetector:
    """Create EmergentDetector with strong Hebbian weights that form a cluster."""
    weights = {
        ("intent_a", "agent_pool_0_abc", REL_INTENT): 0.5,
        ("intent_a", "agent_pool_1_def", REL_INTENT): 0.4,
    }
    router = MagicMock()
    router.all_weights_typed.return_value = weights
    trust = MagicMock()
    kwargs.setdefault("cluster_min_size", 1)
    kwargs.setdefault("cluster_edge_threshold", 0.1)
    detector = EmergentDetector(
        hebbian_router=router,
        trust_network=trust,
        episodic_memory=None,  # No episode guard
        **kwargs,
    )
    return detector


# ---------------------------------------------------------------------------
# Activity gate
# ---------------------------------------------------------------------------

class TestActivityGate:
    def test_no_activity_suppresses_clusters(self) -> None:
        """Cluster detection returns empty when no activity has been recorded."""
        detector = _make_detector()
        # _last_activity_time is 0.0 — monotonic() is always >> 900s from 0
        clusters = detector.detect_cooperation_clusters()
        assert clusters == []

    def test_recent_activity_allows_clusters(self) -> None:
        """Cluster detection works normally after record_activity()."""
        detector = _make_detector()
        detector.record_activity()
        clusters = detector.detect_cooperation_clusters()
        assert len(clusters) > 0

    def test_activity_expires_after_window(self) -> None:
        """Clusters suppressed when activity is older than the window."""
        detector = _make_detector(cluster_activity_window=900.0)
        detector.record_activity()
        # Simulate activity 1000s ago (past the 900s window)
        detector._last_activity_time = time.monotonic() - 1000
        clusters = detector.detect_cooperation_clusters()
        assert clusters == []

    def test_activity_window_zero_disables_gate(self) -> None:
        """cluster_activity_window=0 disables the gate entirely."""
        detector = _make_detector(cluster_activity_window=0)
        # No record_activity() call — gate should be disabled
        clusters = detector.detect_cooperation_clusters()
        assert len(clusters) > 0


# ---------------------------------------------------------------------------
# Config field
# ---------------------------------------------------------------------------

class TestConfigField:
    def test_cluster_activity_window_config_exists(self) -> None:
        """EmergentDetectorConfig has cluster_activity_window with default 900."""
        config = EmergentDetectorConfig()
        assert config.cluster_activity_window == 900.0

    def test_activity_window_passed_to_constructor(self) -> None:
        """dreaming.py passes cluster_activity_window to EmergentDetector."""
        import inspect
        from probos.startup import dreaming
        source = inspect.getsource(dreaming)
        assert "cluster_activity_window" in source


# ---------------------------------------------------------------------------
# Runtime wiring
# ---------------------------------------------------------------------------

class TestRuntimeWiring:
    def test_record_activity_called_from_runtime(self) -> None:
        """runtime.py calls record_activity() near record_interaction()."""
        import inspect
        from probos import runtime
        source = inspect.getsource(runtime)
        assert "record_activity()" in source
        # Verify it's near record_interaction
        idx_interaction = source.index("record_interaction(")
        idx_activity = source.index("record_activity()")
        # Activity call should be within ~500 chars of interaction call
        assert abs(idx_activity - idx_interaction) < 1000


# ---------------------------------------------------------------------------
# record_activity method
# ---------------------------------------------------------------------------

class TestRecordActivityMethod:
    def test_record_activity_updates_timestamp(self) -> None:
        """record_activity() sets _last_activity_time to a non-zero value."""
        detector = _make_detector()
        assert detector._last_activity_time == 0.0
        detector.record_activity()
        assert detector._last_activity_time > 0
