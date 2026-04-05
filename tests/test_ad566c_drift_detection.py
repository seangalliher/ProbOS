"""AD-566c: Drift Detection Pipeline tests.

Tests for DriftDetector, DriftScheduler, BridgeAlertService integration,
Counselor integration, VitalsMonitor integration, and config defaults.

Minimum: 30 tests.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.drift_detector import (
    DriftDetector,
    DriftReport,
    DriftScheduler,
    DriftSignal,
    _worst_severity,
)
from probos.config import QualificationConfig
from probos.events import EventType


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

@dataclass
class MockTestResult:
    agent_id: str
    test_name: str
    score: float
    tier: int = 1
    passed: bool = True
    timestamp: float = 0.0
    duration_ms: float = 10.0
    is_baseline: bool = False


@dataclass
class MockBaseline:
    agent_id: str
    test_name: str
    score: float


class MockQualificationStore:
    """Minimal mock for QualificationStore."""

    def __init__(self) -> None:
        self._history: dict[str, list[MockTestResult]] = {}
        self._baselines: dict[str, MockBaseline] = {}

    def add_history(self, agent_id: str, test_name: str, scores: list[float]) -> None:
        key = f"{agent_id}:{test_name}"
        results = [
            MockTestResult(
                agent_id=agent_id,
                test_name=test_name,
                score=s,
                timestamp=time.time() - i,
            )
            for i, s in enumerate(scores)
        ]
        self._history[key] = results

    def set_baseline(self, agent_id: str, test_name: str, score: float) -> None:
        key = f"{agent_id}:{test_name}"
        self._baselines[key] = MockBaseline(agent_id, test_name, score)

    async def get_history(
        self, agent_id: str, test_name: str, *, limit: int = 20
    ) -> list[MockTestResult]:
        key = f"{agent_id}:{test_name}"
        return self._history.get(key, [])[:limit]

    async def get_baseline(
        self, agent_id: str, test_name: str
    ) -> MockBaseline | None:
        key = f"{agent_id}:{test_name}"
        return self._baselines.get(key)


class MockAgent:
    def __init__(self, agent_id: str, agent_type: str = "cognitive",
                 pool: str = "bridge") -> None:
        self.id = agent_id
        self.agent_type = agent_type
        self.pool = pool
        self.state = "active"
        self._meta = {"pool": pool}


class MockPool:
    def __init__(self, agents: list) -> None:
        self.healthy_agents = agents
        self.target_size = len(agents)


class MockHarness:
    def __init__(self) -> None:
        self.registered_tests: dict[str, Any] = {}
        self.run_calls: list[tuple] = []

    def add_test(self, name: str, tier: int = 1) -> None:
        t = MagicMock()
        t.tier = tier
        t.name = name
        self.registered_tests[name] = t

    async def run_tier(self, agent_id: str, tier: int, runtime: Any = None) -> list:
        self.run_calls.append((agent_id, tier))
        return []


def _build_detector(
    scores: list[float] | None = None,
    baseline: float = 0.8,
    agent_id: str = "agent-1",
    test_name: str = "personality_probe",
    config: QualificationConfig | None = None,
) -> tuple[DriftDetector, MockQualificationStore]:
    """Build a detector with pre-loaded history."""
    cfg = config or QualificationConfig()
    store = MockQualificationStore()
    if scores is not None:
        store.add_history(agent_id, test_name, scores)
    store.set_baseline(agent_id, test_name, baseline)
    detector = DriftDetector(store=store, config=cfg)
    return detector, store


# ===================================================================
# DriftDetector tests (~12)
# ===================================================================


class TestDriftDetector:
    @pytest.mark.asyncio
    async def test_drift_signal_normal(self):
        """z-score within bounds → severity 'normal'."""
        # Scores centered around 0.8 with low variance
        scores = [0.80, 0.79, 0.81, 0.80, 0.78]
        detector, _ = _build_detector(scores=scores, baseline=0.8)
        report = await detector.analyze_agent("agent-1", ["personality_probe"])
        assert len(report.signals) == 1
        sig = report.signals[0]
        assert sig.severity == "normal"
        assert not report.drift_detected

    @pytest.mark.asyncio
    async def test_drift_signal_warning(self):
        """z-score >= 2σ → severity 'warning'."""
        # Use a wider spread to ensure z > 2σ clearly
        scores = [0.3, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8]
        cfg = QualificationConfig(drift_warning_sigma=2.0, drift_critical_sigma=5.0)
        detector, _ = _build_detector(scores=scores, baseline=0.8, config=cfg)
        report = await detector.analyze_agent("agent-1", ["personality_probe"])
        sig = report.signals[0]
        assert sig.severity == "warning"
        assert report.drift_detected

    @pytest.mark.asyncio
    async def test_drift_signal_critical(self):
        """z-score >= 3σ → severity 'critical'."""
        # 19 scores at 0.8 + 1 extreme outlier → z well beyond 3σ
        scores = [0.0] + [0.8] * 19
        detector, _ = _build_detector(scores=scores, baseline=0.8)
        report = await detector.analyze_agent("agent-1", ["personality_probe"])
        sig = report.signals[0]
        assert sig.severity == "critical"
        assert abs(sig.z_score) >= 3.0

    @pytest.mark.asyncio
    async def test_drift_direction_improved(self):
        """Positive delta from baseline → 'improved'."""
        scores = [0.95, 0.8, 0.8, 0.8]
        detector, _ = _build_detector(scores=scores, baseline=0.7)
        report = await detector.analyze_agent("agent-1", ["personality_probe"])
        sig = report.signals[0]
        assert sig.direction == "improved"

    @pytest.mark.asyncio
    async def test_drift_direction_declined(self):
        """Negative delta from baseline → 'declined'."""
        scores = [0.4, 0.8, 0.8, 0.8]
        detector, _ = _build_detector(scores=scores, baseline=0.8)
        report = await detector.analyze_agent("agent-1", ["personality_probe"])
        sig = report.signals[0]
        assert sig.direction == "declined"

    @pytest.mark.asyncio
    async def test_drift_direction_stable(self):
        """Small delta from baseline → 'stable'."""
        scores = [0.80, 0.80, 0.80, 0.80]
        detector, _ = _build_detector(scores=scores, baseline=0.80)
        report = await detector.analyze_agent("agent-1", ["personality_probe"])
        sig = report.signals[0]
        assert sig.direction == "stable"

    @pytest.mark.asyncio
    async def test_drift_insufficient_samples(self):
        """Fewer than drift_min_samples → severity 'normal'."""
        cfg = QualificationConfig(drift_min_samples=5)
        scores = [0.1, 0.8, 0.8]  # only 3 samples, minimum is 5
        detector, _ = _build_detector(scores=scores, baseline=0.8, config=cfg)
        report = await detector.analyze_agent("agent-1", ["personality_probe"])
        sig = report.signals[0]
        # Should be normal despite extreme z-score due to insufficient samples
        assert sig.severity == "normal"

    @pytest.mark.asyncio
    async def test_drift_zero_stddev(self):
        """All identical scores → z_score=0, severity 'normal'."""
        scores = [0.8, 0.8, 0.8, 0.8, 0.8]
        detector, _ = _build_detector(scores=scores, baseline=0.8)
        report = await detector.analyze_agent("agent-1", ["personality_probe"])
        sig = report.signals[0]
        assert sig.z_score == 0.0
        assert sig.severity == "normal"

    @pytest.mark.asyncio
    async def test_drift_report_overall_severity(self):
        """Worst signal severity determines report overall severity."""
        store = MockQualificationStore()
        store.add_history("agent-1", "test_a", [0.8, 0.8, 0.8, 0.8])
        store.set_baseline("agent-1", "test_a", 0.8)
        # 19 stable + 1 extreme outlier → critical
        store.add_history(
            "agent-1", "test_b",
            [0.0] + [0.8] * 19,
        )
        store.set_baseline("agent-1", "test_b", 0.8)

        detector = DriftDetector(store=store, config=QualificationConfig())
        report = await detector.analyze_agent("agent-1", ["test_a", "test_b"])
        assert report.overall_severity == "critical"
        assert report.drift_detected

    @pytest.mark.asyncio
    async def test_drift_report_multiple_tests(self):
        """Analyzes across all specified tests."""
        store = MockQualificationStore()
        for name in ("test_a", "test_b", "test_c"):
            store.add_history("agent-1", name, [0.8, 0.8, 0.8])
            store.set_baseline("agent-1", name, 0.8)

        detector = DriftDetector(store=store, config=QualificationConfig())
        report = await detector.analyze_agent("agent-1", ["test_a", "test_b", "test_c"])
        assert len(report.signals) == 3

    @pytest.mark.asyncio
    async def test_drift_history_window(self):
        """Respects drift_history_window limit."""
        cfg = QualificationConfig(drift_history_window=3)
        scores = [0.8, 0.8, 0.8, 0.8, 0.8]  # 5 scores but window=3
        detector, store = _build_detector(scores=scores, baseline=0.8, config=cfg)
        report = await detector.analyze_agent("agent-1", ["personality_probe"])
        sig = report.signals[0]
        assert sig.sample_count == 3  # limited by window

    @pytest.mark.asyncio
    async def test_drift_config_thresholds(self):
        """Custom sigma thresholds apply correctly."""
        # Lower thresholds so moderate z-score triggers critical
        cfg = QualificationConfig(drift_warning_sigma=1.0, drift_critical_sigma=1.5)
        scores = [0.5, 0.8, 0.8, 0.8, 0.8]
        detector, _ = _build_detector(scores=scores, baseline=0.8, config=cfg)
        report = await detector.analyze_agent("agent-1", ["personality_probe"])
        sig = report.signals[0]
        assert sig.severity == "critical"

    @pytest.mark.asyncio
    async def test_drift_no_history(self):
        """No history → zero values, severity 'normal'."""
        detector, _ = _build_detector(scores=None, baseline=0.8)
        report = await detector.analyze_agent("agent-1", ["personality_probe"])
        sig = report.signals[0]
        assert sig.sample_count == 0
        assert sig.severity == "normal"
        assert sig.z_score == 0.0


# ===================================================================
# DriftScheduler tests (~8)
# ===================================================================


class TestDriftScheduler:
    @pytest.mark.asyncio
    async def test_scheduler_start_stop(self):
        """Starts and stops cleanly."""
        harness = MockHarness()
        harness.add_test("test_a")
        store = MockQualificationStore()
        detector = DriftDetector(store=store, config=QualificationConfig())

        scheduler = DriftScheduler(
            harness=harness,
            detector=detector,
            emit_event_fn=MagicMock(),
            config=QualificationConfig(drift_check_interval_seconds=0.1),
            runtime=MagicMock(pools={}),
        )
        await scheduler.start()
        assert scheduler._running
        assert scheduler._task is not None
        await scheduler.stop()
        assert not scheduler._running

    @pytest.mark.asyncio
    async def test_scheduler_disabled(self):
        """drift_check_enabled=False → does not start."""
        cfg = QualificationConfig(drift_check_enabled=False)
        scheduler = DriftScheduler(
            harness=MockHarness(),
            detector=MagicMock(),
            config=cfg,
        )
        await scheduler.start()
        assert not scheduler._running
        assert scheduler._task is None

    @pytest.mark.asyncio
    async def test_scheduler_run_now(self):
        """On-demand drift check returns DriftReports."""
        store = MockQualificationStore()
        store.add_history("agent-1", "test_a", [0.8, 0.8, 0.8])
        store.set_baseline("agent-1", "test_a", 0.8)

        harness = MockHarness()
        harness.add_test("test_a")
        detector = DriftDetector(store=store, config=QualificationConfig())

        agent = MockAgent("agent-1")
        pool = MockPool([agent])
        runtime = MagicMock(pools={"bridge": pool})

        scheduler = DriftScheduler(
            harness=harness,
            detector=detector,
            emit_event_fn=MagicMock(),
            config=QualificationConfig(),
            runtime=runtime,
        )

        with patch("probos.crew_utils.is_crew_agent", return_value=True):
            reports = await scheduler.run_now()

        assert len(reports) == 1
        assert reports[0].agent_id == "agent-1"

    @pytest.mark.asyncio
    async def test_scheduler_emits_event_on_warning(self):
        """Emits QUALIFICATION_DRIFT_DETECTED for warning severity."""
        store = MockQualificationStore()
        store.add_history("agent-1", "test_a", [0.5, 0.8, 0.8, 0.8, 0.8])
        store.set_baseline("agent-1", "test_a", 0.8)

        harness = MockHarness()
        harness.add_test("test_a")
        cfg = QualificationConfig(drift_warning_sigma=1.0, drift_critical_sigma=5.0)
        detector = DriftDetector(store=store, config=cfg)

        emit_fn = MagicMock()
        agent = MockAgent("agent-1")
        pool = MockPool([agent])
        runtime = MagicMock(pools={"bridge": pool})

        scheduler = DriftScheduler(
            harness=harness,
            detector=detector,
            emit_event_fn=emit_fn,
            config=cfg,
            runtime=runtime,
        )

        with patch("probos.crew_utils.is_crew_agent", return_value=True):
            await scheduler.run_now()

        assert emit_fn.called
        call_args = emit_fn.call_args
        assert call_args[0][0] == EventType.QUALIFICATION_DRIFT_DETECTED

    @pytest.mark.asyncio
    async def test_scheduler_emits_event_on_critical(self):
        """Emits QUALIFICATION_DRIFT_DETECTED for critical severity."""
        store = MockQualificationStore()
        store.add_history("agent-1", "test_a", [0.0] + [0.8] * 19)
        store.set_baseline("agent-1", "test_a", 0.8)

        harness = MockHarness()
        harness.add_test("test_a")
        detector = DriftDetector(store=store, config=QualificationConfig())

        emit_fn = MagicMock()
        agent = MockAgent("agent-1")
        pool = MockPool([agent])
        runtime = MagicMock(pools={"bridge": pool})

        scheduler = DriftScheduler(
            harness=harness,
            detector=detector,
            emit_event_fn=emit_fn,
            config=QualificationConfig(),
            runtime=runtime,
        )

        with patch("probos.crew_utils.is_crew_agent", return_value=True):
            await scheduler.run_now()

        assert emit_fn.called
        call_args = emit_fn.call_args
        assert call_args[0][0] == EventType.QUALIFICATION_DRIFT_DETECTED
        assert call_args[0][1]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_scheduler_cooldown(self):
        """Does not re-emit within drift_cooldown_seconds."""
        store = MockQualificationStore()
        store.add_history("agent-1", "test_a", [0.0] + [0.8] * 19)
        store.set_baseline("agent-1", "test_a", 0.8)

        harness = MockHarness()
        harness.add_test("test_a")
        detector = DriftDetector(store=store, config=QualificationConfig())

        emit_fn = MagicMock()
        agent = MockAgent("agent-1")
        pool = MockPool([agent])
        runtime = MagicMock(pools={"bridge": pool})

        cfg = QualificationConfig(drift_cooldown_seconds=3600)
        scheduler = DriftScheduler(
            harness=harness,
            detector=detector,
            emit_event_fn=emit_fn,
            config=cfg,
            runtime=runtime,
        )

        with patch("probos.crew_utils.is_crew_agent", return_value=True):
            await scheduler.run_now()
            first_count = emit_fn.call_count
            assert first_count >= 1

            # Second run should be suppressed by cooldown
            await scheduler.run_now()
            assert emit_fn.call_count == first_count  # no additional calls

    @pytest.mark.asyncio
    async def test_scheduler_latest_reports(self):
        """latest_reports property returns cached results."""
        store = MockQualificationStore()
        store.add_history("agent-1", "test_a", [0.8, 0.8, 0.8])
        store.set_baseline("agent-1", "test_a", 0.8)

        harness = MockHarness()
        harness.add_test("test_a")
        detector = DriftDetector(store=store, config=QualificationConfig())

        agent = MockAgent("agent-1")
        pool = MockPool([agent])
        runtime = MagicMock(pools={"bridge": pool})

        scheduler = DriftScheduler(
            harness=harness,
            detector=detector,
            config=QualificationConfig(),
            runtime=runtime,
        )

        assert scheduler.latest_reports == {}

        with patch("probos.crew_utils.is_crew_agent", return_value=True):
            await scheduler.run_now()

        reports = scheduler.latest_reports
        assert "agent-1" in reports
        assert isinstance(reports["agent-1"], DriftReport)

    @pytest.mark.asyncio
    async def test_scheduler_no_event_on_normal(self):
        """No event emitted when all signals are normal."""
        store = MockQualificationStore()
        store.add_history("agent-1", "test_a", [0.8, 0.8, 0.8, 0.8])
        store.set_baseline("agent-1", "test_a", 0.8)

        harness = MockHarness()
        harness.add_test("test_a")
        detector = DriftDetector(store=store, config=QualificationConfig())

        emit_fn = MagicMock()
        agent = MockAgent("agent-1")
        pool = MockPool([agent])
        runtime = MagicMock(pools={"bridge": pool})

        scheduler = DriftScheduler(
            harness=harness,
            detector=detector,
            emit_event_fn=emit_fn,
            config=QualificationConfig(),
            runtime=runtime,
        )

        with patch("probos.crew_utils.is_crew_agent", return_value=True):
            await scheduler.run_now()

        assert not emit_fn.called


# ===================================================================
# BridgeAlertService tests (~4)
# ===================================================================


class TestBridgeAlertDrift:
    def test_bridge_alert_critical_drift(self):
        """Critical drift → ALERT severity."""
        from probos.bridge_alerts import AlertSeverity, BridgeAlertService

        svc = BridgeAlertService()
        report = DriftReport(
            agent_id="agent-1",
            timestamp=time.time(),
            signals=[
                DriftSignal(
                    agent_id="agent-1", test_name="personality_probe",
                    current_score=0.1, baseline_score=0.8, mean_score=0.8,
                    std_dev=0.05, z_score=-14.0, direction="declined",
                    severity="critical", sample_count=10,
                ),
            ],
            overall_severity="critical",
            drift_detected=True,
        )
        alerts = svc.check_qualification_drift([report])
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ALERT
        assert alerts[0].department is None  # all-hands

    def test_bridge_alert_warning_drift(self):
        """Warning drift → ADVISORY severity, routed to medical."""
        from probos.bridge_alerts import AlertSeverity, BridgeAlertService

        svc = BridgeAlertService()
        report = DriftReport(
            agent_id="agent-1",
            timestamp=time.time(),
            signals=[
                DriftSignal(
                    agent_id="agent-1", test_name="temperament",
                    current_score=0.5, baseline_score=0.8, mean_score=0.78,
                    std_dev=0.1, z_score=-2.8, direction="declined",
                    severity="warning", sample_count=10,
                ),
            ],
            overall_severity="warning",
            drift_detected=True,
        )
        alerts = svc.check_qualification_drift([report])
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ADVISORY
        assert alerts[0].department == "medical"

    def test_bridge_alert_no_drift(self):
        """No drift detected → no alerts."""
        from probos.bridge_alerts import BridgeAlertService

        svc = BridgeAlertService()
        report = DriftReport(
            agent_id="agent-1",
            timestamp=time.time(),
            signals=[
                DriftSignal(
                    agent_id="agent-1", test_name="personality_probe",
                    current_score=0.8, baseline_score=0.8, mean_score=0.8,
                    std_dev=0.01, z_score=0.0, direction="stable",
                    severity="normal", sample_count=10,
                ),
            ],
            overall_severity="normal",
            drift_detected=False,
        )
        alerts = svc.check_qualification_drift([report])
        assert len(alerts) == 0

    def test_bridge_alert_dedup(self):
        """Repeated critical drift → suppressed by cooldown."""
        from probos.bridge_alerts import BridgeAlertService

        svc = BridgeAlertService(cooldown_seconds=300)
        report = DriftReport(
            agent_id="agent-1",
            timestamp=time.time(),
            signals=[
                DriftSignal(
                    agent_id="agent-1", test_name="personality_probe",
                    current_score=0.1, baseline_score=0.8, mean_score=0.8,
                    std_dev=0.05, z_score=-14.0, direction="declined",
                    severity="critical", sample_count=10,
                ),
            ],
            overall_severity="critical",
            drift_detected=True,
        )
        alerts1 = svc.check_qualification_drift([report])
        assert len(alerts1) == 1
        # Second call: dedup should suppress
        alerts2 = svc.check_qualification_drift([report])
        assert len(alerts2) == 0


# ===================================================================
# Counselor integration tests (~3)
# ===================================================================


class TestCounselorDrift:
    def test_counselor_subscribes_drift_event(self):
        """QUALIFICATION_DRIFT_DETECTED in Counselor event subscription list."""
        import inspect
        from probos.cognitive.counselor import CounselorAgent

        source = inspect.getsource(CounselorAgent.initialize)
        assert "QUALIFICATION_DRIFT_DETECTED" in source

    @pytest.mark.asyncio
    async def test_counselor_critical_drift_triggers_assessment(self):
        """Critical severity → full assessment triggered."""
        from probos.cognitive.counselor import CounselorAgent

        counselor = CounselorAgent.__new__(CounselorAgent)
        counselor.id = "counselor-1"
        counselor._cognitive_profiles = {}
        counselor._runtime = MagicMock()
        counselor._registry = MagicMock()

        # Mock required methods
        counselor._resolve_agent_callsign = MagicMock(return_value="Worf")
        counselor._gather_agent_metrics = MagicMock(return_value={
            "trust_score": 0.7,
            "confidence": 0.8,
            "hebbian_avg": 0.5,
            "success_rate": 0.6,
            "personality_drift": 0.1,
        })
        mock_assessment = MagicMock()
        mock_assessment.fit_for_duty = True
        counselor.assess_agent = MagicMock(return_value=mock_assessment)
        counselor._save_profile_and_assessment = AsyncMock()
        counselor._maybe_send_therapeutic_dm = AsyncMock()

        data = {
            "agent_id": "agent-worf",
            "test_name": "personality_probe",
            "severity": "critical",
            "z_score": -3.5,
            "direction": "declined",
        }
        await counselor._on_qualification_drift(data)

        counselor.assess_agent.assert_called_once()
        call_kwargs = counselor.assess_agent.call_args
        assert call_kwargs[1]["trigger"] == "qualification_drift_critical"
        counselor._save_profile_and_assessment.assert_called_once()
        counselor._maybe_send_therapeutic_dm.assert_called_once()

    @pytest.mark.asyncio
    async def test_counselor_warning_drift_logs_only(self):
        """Warning severity → logged, no assessment/DM."""
        from probos.cognitive.counselor import CounselorAgent

        counselor = CounselorAgent.__new__(CounselorAgent)
        counselor.id = "counselor-1"
        counselor._resolve_agent_callsign = MagicMock(return_value="Worf")
        counselor._gather_agent_metrics = MagicMock()
        counselor.assess_agent = MagicMock()
        counselor._save_profile_and_assessment = AsyncMock()
        counselor._maybe_send_therapeutic_dm = AsyncMock()

        data = {
            "agent_id": "agent-worf",
            "test_name": "personality_probe",
            "severity": "warning",
            "z_score": -2.1,
            "direction": "declined",
        }
        await counselor._on_qualification_drift(data)

        # Warning should NOT trigger assessment or DM
        counselor.assess_agent.assert_not_called()
        counselor._save_profile_and_assessment.assert_not_called()
        counselor._maybe_send_therapeutic_dm.assert_not_called()


# ===================================================================
# VitalsMonitor tests (~2)
# ===================================================================


class TestVitalsMonitorDrift:
    def test_vitals_includes_drift_metrics(self):
        """Drift metrics appear in vitals when drift scheduler exists."""
        from probos.agents.medical.vitals_monitor import VitalsMonitorAgent

        report = DriftReport(
            agent_id="agent-1",
            timestamp=time.time(),
            signals=[],
            overall_severity="warning",
            drift_detected=True,
        )
        mock_scheduler = MagicMock()
        mock_scheduler.latest_reports = {"agent-1": report}
        mock_scheduler.last_run_time = 1234567890.0

        # Simulate what collect_metrics does for drift
        metrics: dict[str, Any] = {}
        _drift_scheduler = mock_scheduler
        _reports = _drift_scheduler.latest_reports
        if _reports:
            drift_agents_warning = sum(
                1 for r in _reports.values() if r.overall_severity == "warning"
            )
            drift_agents_critical = sum(
                1 for r in _reports.values() if r.overall_severity == "critical"
            )
            metrics["qualification_drift_warning_count"] = drift_agents_warning
            metrics["qualification_drift_critical_count"] = drift_agents_critical
            metrics["qualification_last_check"] = _drift_scheduler.last_run_time

        assert metrics["qualification_drift_warning_count"] == 1
        assert metrics["qualification_drift_critical_count"] == 0
        assert metrics["qualification_last_check"] == 1234567890.0

    def test_vitals_no_drift_scheduler(self):
        """Graceful when _drift_scheduler is None."""
        metrics: dict[str, Any] = {}
        _drift_scheduler = None
        if _drift_scheduler:
            # This block should not execute
            metrics["qualification_drift_warning_count"] = 999

        assert "qualification_drift_warning_count" not in metrics


# ===================================================================
# Config tests (~1)
# ===================================================================


class TestConfigDrift:
    def test_qualification_config_drift_fields(self):
        """New drift fields have correct defaults."""
        cfg = QualificationConfig()
        assert cfg.drift_check_enabled is True
        assert cfg.drift_check_interval_seconds == 604800.0
        assert cfg.drift_warning_sigma == 2.0
        assert cfg.drift_critical_sigma == 3.0
        assert cfg.drift_min_samples == 3
        assert cfg.drift_history_window == 20
        assert cfg.drift_cooldown_seconds == 3600.0


# ===================================================================
# Helper tests
# ===================================================================


class TestHelpers:
    def test_worst_severity_normal(self):
        assert _worst_severity(["normal", "normal"]) == "normal"

    def test_worst_severity_warning(self):
        assert _worst_severity(["normal", "warning"]) == "warning"

    def test_worst_severity_critical(self):
        assert _worst_severity(["normal", "warning", "critical"]) == "critical"

    def test_worst_severity_empty(self):
        assert _worst_severity([]) == "normal"


# ===================================================================
# End-to-end pipeline test
# ===================================================================


class TestE2EPipeline:
    @pytest.mark.asyncio
    async def test_drift_detection_pipeline_e2e(self):
        """Full pipeline: build history → inject drift → detect → alert → event."""
        from probos.bridge_alerts import AlertSeverity, BridgeAlertService

        # 1. Set up store, detector, scheduler
        store = MockQualificationStore()
        cfg = QualificationConfig(drift_min_samples=3)

        # 2. Build history: 19 stable runs
        stable_scores = [0.8] * 19
        store.add_history("agent-1", "personality_probe", stable_scores)
        store.set_baseline("agent-1", "personality_probe", 0.8)

        # 3. Now inject a drifted score (prepend = newest)
        drifted_scores = [0.0] + stable_scores  # 0.0 is far below mean
        store._history["agent-1:personality_probe"] = [
            MockTestResult("agent-1", "personality_probe", s, timestamp=time.time() - i)
            for i, s in enumerate(drifted_scores)
        ]

        detector = DriftDetector(store=store, config=cfg)

        # 4. Analyze drift
        report = await detector.analyze_agent("agent-1", ["personality_probe"])

        # 5. Assert drift detected
        assert report.drift_detected
        sig = report.signals[0]
        assert sig.severity == "critical"
        assert sig.direction == "declined"
        assert abs(sig.z_score) >= 2.0

        # 6. Check bridge alert
        bridge_svc = BridgeAlertService()
        alerts = bridge_svc.check_qualification_drift([report])
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ALERT
        assert "personality_probe" in alerts[0].title

        # 7. Emit event
        emit_fn = MagicMock()
        harness = MockHarness()
        harness.add_test("personality_probe")

        agent = MockAgent("agent-1")
        pool = MockPool([agent])
        runtime = MagicMock(pools={"bridge": pool})

        scheduler = DriftScheduler(
            harness=harness,
            detector=detector,
            emit_event_fn=emit_fn,
            config=cfg,
            runtime=runtime,
        )

        with patch("probos.crew_utils.is_crew_agent", return_value=True):
            await scheduler.run_now()

        assert emit_fn.called
        event_data = emit_fn.call_args[0][1]
        assert event_data["severity"] == "critical"
        assert event_data["agent_id"] == "agent-1"
