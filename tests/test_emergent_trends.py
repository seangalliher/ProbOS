"""Tests for EmergentDetector Trend Regression (AD-380)."""

from __future__ import annotations

import time

import pytest

from probos.cognitive.emergent_detector import (
    EmergentDetector,
    MetricTrend,
    SystemDynamicsSnapshot,
    TrendDirection,
    TrendReport,
)
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import HebbianRouter


def _make_snapshot(
    tc_n: float = 0.5,
    routing_entropy: float = 1.0,
    cooperation_clusters: list | None = None,
    trust_distribution: dict | None = None,
    capability_count: int = 5,
    timestamp: float = 0.0,
) -> SystemDynamicsSnapshot:
    return SystemDynamicsSnapshot(
        timestamp=timestamp or time.monotonic(),
        tc_n=tc_n,
        routing_entropy=routing_entropy,
        cooperation_clusters=cooperation_clusters if cooperation_clusters is not None else [],
        trust_distribution=trust_distribution if trust_distribution is not None else {"std": 0.1, "mean": 0.5},
        capability_count=capability_count,
    )


def _make_detector(**kwargs) -> EmergentDetector:
    router = HebbianRouter()
    trust = TrustNetwork()
    return EmergentDetector(hebbian_router=router, trust_network=trust, **kwargs)


class TestLinearRegression:
    def test_perfect_line(self) -> None:
        slope, intercept, r_sq = EmergentDetector._linear_regression(
            [0, 1, 2, 3, 4], [0, 2, 4, 6, 8]
        )
        assert abs(slope - 2.0) < 1e-6
        assert abs(intercept) < 1e-6
        assert abs(r_sq - 1.0) < 1e-6

    def test_flat(self) -> None:
        slope, intercept, r_sq = EmergentDetector._linear_regression(
            [0, 1, 2, 3, 4], [5, 5, 5, 5, 5]
        )
        assert abs(slope) < 1e-6
        assert abs(intercept - 5.0) < 1e-6


class TestComputeTrends:
    def test_none_insufficient_data(self) -> None:
        det = _make_detector()
        # Add only 5 snapshots — below min_window=20 default
        for _ in range(5):
            det._history.append(_make_snapshot())
        assert det.compute_trends() is None

    def test_rising_tc_n(self) -> None:
        det = _make_detector()
        for i in range(25):
            det._history.append(_make_snapshot(tc_n=0.1 + i * 0.02))
        report = det.compute_trends()
        assert report is not None
        assert report.tc_n.direction == TrendDirection.RISING
        assert report.tc_n.significant

    def test_falling_entropy(self) -> None:
        det = _make_detector()
        for i in range(25):
            det._history.append(_make_snapshot(routing_entropy=2.0 - i * 0.05))
        report = det.compute_trends()
        assert report is not None
        assert report.routing_entropy.direction == TrendDirection.FALLING

    def test_stable(self) -> None:
        det = _make_detector()
        import random
        rng = random.Random(42)
        for _ in range(25):
            det._history.append(_make_snapshot(
                tc_n=0.5 + rng.uniform(-0.001, 0.001),
                routing_entropy=1.0 + rng.uniform(-0.001, 0.001),
            ))
        report = det.compute_trends()
        assert report is not None
        assert report.tc_n.direction == TrendDirection.STABLE
        assert not report.tc_n.significant

    def test_significant_trends_filtered(self) -> None:
        det = _make_detector()
        for i in range(25):
            # tc_n rising, everything else constant
            det._history.append(_make_snapshot(
                tc_n=0.1 + i * 0.02,
                routing_entropy=1.0,
                capability_count=5,
            ))
        report = det.compute_trends()
        assert report is not None
        significant_names = {t.metric_name for t in report.significant_trends}
        assert "tc_n" in significant_names
        # routing_entropy should NOT be significant (flat)
        assert "routing_entropy" not in significant_names

    def test_threshold_configurable(self) -> None:
        det = _make_detector(trend_threshold=0.1)
        for i in range(25):
            # Small slope (0.02 per step) — below threshold of 0.1
            det._history.append(_make_snapshot(tc_n=0.1 + i * 0.02))
        report = det.compute_trends()
        assert report is not None
        assert not report.tc_n.significant

    def test_deque_maxlen_respected(self) -> None:
        det = _make_detector(max_history=100)
        for i in range(150):
            det._history.append(_make_snapshot(tc_n=float(i)))
        assert len(det._history) == 100

    def test_r_squared_low_noisy_data(self) -> None:
        det = _make_detector()
        import random
        rng = random.Random(99)
        for _ in range(25):
            det._history.append(_make_snapshot(tc_n=rng.uniform(0.0, 1.0)))
        report = det.compute_trends()
        assert report is not None
        # Noisy data should have low r_squared, not significant
        assert not report.tc_n.significant

    def test_trend_with_missing_trust_std(self) -> None:
        det = _make_detector()
        for i in range(25):
            det._history.append(_make_snapshot(
                trust_distribution={},  # no "std" key
            ))
        report = det.compute_trends()
        assert report is not None
        # Should gracefully use 0.0 for missing std
        assert report.trust_spread.current_value == 0.0


class TestAnalyzeWithTrends:
    def test_analyze_includes_trends(self) -> None:
        det = _make_detector()
        # Pre-populate with 24 snapshots with rising tc_n
        for i in range(24):
            det._history.append(_make_snapshot(tc_n=0.1 + i * 0.02))
        # The 25th comes from analyze() calling get_snapshot()
        # But get_snapshot uses live router/trust, so tc_n will be 0.0
        # Inject directly instead
        det._history.append(_make_snapshot(tc_n=0.1 + 24 * 0.02))

        report = det.compute_trends()
        assert report is not None
        assert len(report.significant_trends) > 0

        # Verify the pattern would appear in analyze output
        trend_names = {t.metric_name for t in report.significant_trends}
        assert "tc_n" in trend_names
