"""AD-566c: Drift Detection Pipeline.

Statistical drift detection for the Crew Qualification Battery.
Periodically runs Tier 1 tests, computes z-scores against historical
baselines, and routes alerts to Counselor (2σ) and Bridge (3σ).

Classes:
    DriftSignal  — result of drift analysis for one agent+test pair
    DriftReport  — aggregated drift analysis for one agent across all tests
    DriftDetector — statistical engine (z-scores from QualificationStore)
    DriftScheduler — periodic runner + event emission + cooldown
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DriftSignal:
    """Result of drift analysis for one agent+test pair."""

    agent_id: str
    test_name: str
    current_score: float
    baseline_score: float
    mean_score: float
    std_dev: float
    z_score: float
    direction: str       # "improved" | "stable" | "declined"
    severity: str        # "normal" | "warning" | "critical"
    sample_count: int


@dataclass(frozen=True)
class DriftReport:
    """Aggregated drift analysis for one agent across all tests."""

    agent_id: str
    timestamp: float
    signals: list[DriftSignal]  # type: ignore[type-arg]
    overall_severity: str       # worst severity across all signals
    drift_detected: bool        # any signal at warning or critical


# ---------------------------------------------------------------------------
# Severity ordering helper
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"normal": 0, "warning": 1, "critical": 2}


def _worst_severity(severities: list[str]) -> str:
    """Return the most severe level from a list."""
    worst = "normal"
    for s in severities:
        if _SEVERITY_ORDER.get(s, 0) > _SEVERITY_ORDER.get(worst, 0):
            worst = s
    return worst


# ---------------------------------------------------------------------------
# DriftDetector — statistical engine
# ---------------------------------------------------------------------------


class DriftDetector:
    """Statistical drift detection engine.

    Computes z-scores from QualificationStore history and classifies
    drift severity against configurable sigma thresholds.
    """

    def __init__(
        self,
        store: Any,  # QualificationStore
        config: Any,  # QualificationConfig
    ) -> None:
        self._store = store
        self._config = config

    async def analyze_agent(
        self, agent_id: str, test_names: list[str]
    ) -> DriftReport:
        """Compute drift signals for an agent across specified tests."""
        signals: list[DriftSignal] = []

        for test_name in test_names:
            signal = await self._analyze_single(agent_id, test_name)
            signals.append(signal)

        severities = [s.severity for s in signals]
        overall = _worst_severity(severities)

        return DriftReport(
            agent_id=agent_id,
            timestamp=time.time(),
            signals=signals,
            overall_severity=overall,
            drift_detected=overall in ("warning", "critical"),
        )

    async def analyze_all_agents(
        self, agent_ids: list[str], test_names: list[str]
    ) -> list[DriftReport]:
        """Run drift analysis for multiple agents."""
        reports = []
        for agent_id in agent_ids:
            try:
                report = await self.analyze_agent(agent_id, test_names)
                reports.append(report)
            except Exception:
                logger.debug(
                    "Drift analysis failed for %s", agent_id[:8], exc_info=True
                )
        return reports

    async def _analyze_single(
        self, agent_id: str, test_name: str
    ) -> DriftSignal:
        """Analyze drift for a single agent+test pair."""
        window = self._config.drift_history_window
        history = await self._store.get_history(
            agent_id, test_name, limit=window
        )

        # Get baseline
        baseline = await self._store.get_baseline(agent_id, test_name)
        baseline_score = baseline.score if baseline else 0.0

        sample_count = len(history)

        if sample_count == 0:
            return DriftSignal(
                agent_id=agent_id,
                test_name=test_name,
                current_score=0.0,
                baseline_score=baseline_score,
                mean_score=0.0,
                std_dev=0.0,
                z_score=0.0,
                direction="stable",
                severity="normal",
                sample_count=0,
            )

        current_score = history[0].score  # newest first
        scores = [r.score for r in history]

        # Compute statistics
        mean_score = sum(scores) / len(scores)
        variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
        std_dev = math.sqrt(variance)

        # Guard against zero std_dev
        if std_dev < 1e-9:
            z_score = 0.0
        else:
            z_score = (current_score - mean_score) / std_dev

        # Direction from baseline comparison
        delta = current_score - baseline_score
        if abs(delta) < self._config.significance_threshold:
            direction = "stable"
        elif delta > 0:
            direction = "improved"
        else:
            direction = "declined"

        # Severity classification
        if sample_count < self._config.drift_min_samples:
            severity = "normal"  # insufficient data
        elif abs(z_score) >= self._config.drift_critical_sigma:
            severity = "critical"
        elif abs(z_score) >= self._config.drift_warning_sigma:
            severity = "warning"
        else:
            severity = "normal"

        return DriftSignal(
            agent_id=agent_id,
            test_name=test_name,
            current_score=current_score,
            baseline_score=baseline_score,
            mean_score=round(mean_score, 4),
            std_dev=round(std_dev, 4),
            z_score=round(z_score, 4),
            direction=direction,
            severity=severity,
            sample_count=sample_count,
        )


# ---------------------------------------------------------------------------
# DriftScheduler — periodic runner
# ---------------------------------------------------------------------------


class DriftScheduler:
    """Periodic drift detection scheduler.

    Runs Tier 1 qualification tests on a configurable interval,
    performs drift analysis, and emits events for detected drift.
    """

    def __init__(
        self,
        harness: Any,  # QualificationHarness
        detector: DriftDetector,
        emit_event_fn: Callable | None = None,
        config: Any = None,  # QualificationConfig
        runtime: Any = None,
    ) -> None:
        from probos.config import QualificationConfig

        self._harness = harness
        self._detector = detector
        self._emit_event_fn = emit_event_fn
        self._config = config or QualificationConfig()
        self._runtime = runtime
        self._drift_tiers = set(getattr(self._config, "drift_check_tiers", [1]))
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_check: dict[str, float] = {}  # "agent_id:test_name" → ts
        self._last_run_time: float = 0.0
        self._latest_reports: dict[str, DriftReport] = {}

    async def start(self) -> None:
        """Start the periodic drift check loop."""
        if not self._config.drift_check_enabled:
            logger.info("AD-566c: Drift check disabled by config")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("AD-566c: DriftScheduler started")

    async def stop(self) -> None:
        """Stop the periodic drift check loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("AD-566c: DriftScheduler stopped")

    async def _run_loop(self) -> None:
        """Main loop — follows ProactiveCognitiveLoop pattern."""
        while self._running:
            try:
                await asyncio.sleep(self._config.drift_check_interval_seconds)
                if not self._running:
                    break
                await self._run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("DriftScheduler cycle error")

    async def _run_cycle(self) -> None:
        """Single drift check cycle."""
        if not self._runtime:
            return

        # Get all crew agent IDs
        agent_ids = self._get_crew_agent_ids()
        if not agent_ids:
            return

        # Get registered test names for configured tiers
        test_names = [
            name for name, test in self._harness.registered_tests.items()
            if test.tier in self._drift_tiers
        ]
        if not test_names:
            return

        # Run tests for each configured tier
        for agent_id in agent_ids:
            for tier in sorted(self._drift_tiers):
                try:
                    await self._harness.run_tier(agent_id, tier, self._runtime)
                except Exception:
                    logger.debug(
                        "Drift cycle: tier %d test run failed for %s",
                        tier, agent_id[:8], exc_info=True,
                    )

        # Run Tier 3 collective tests once (not per-agent)
        if 3 in self._drift_tiers:
            try:
                collective_results = await self._harness.run_collective(3, self._runtime)
                collective_test_names = [r.test_name for r in collective_results]
                if collective_test_names:
                    crew_reports = await self._detector.analyze_all_agents(
                        ["__crew__"], collective_test_names
                    )
                    for report in crew_reports:
                        self._latest_reports[report.agent_id] = report
                        if report.drift_detected:
                            self._emit_drift_events(report)
            except Exception:
                logger.debug("Drift cycle: collective test run failed", exc_info=True)

        # Analyze drift
        reports = await self._detector.analyze_all_agents(agent_ids, test_names)

        # Cache reports and emit events
        for report in reports:
            self._latest_reports[report.agent_id] = report
            if report.drift_detected:
                self._emit_drift_events(report)

        self._last_run_time = time.time()

    async def run_now(
        self, agent_ids: list[str] | None = None
    ) -> list[DriftReport]:
        """On-demand drift check. Returns DriftReports."""
        if not self._runtime:
            return []

        if agent_ids is None:
            agent_ids = self._get_crew_agent_ids()
        if not agent_ids:
            return []

        test_names = [
            name for name, test in self._harness.registered_tests.items()
            if test.tier in self._drift_tiers
        ]
        if not test_names:
            return []

        # Run tests for each configured tier
        for agent_id in agent_ids:
            for tier in sorted(self._drift_tiers):
                try:
                    await self._harness.run_tier(agent_id, tier, self._runtime)
                except Exception:
                    logger.debug(
                        "run_now: tier %d test failed for %s",
                        tier, agent_id[:8], exc_info=True,
                    )

        # Run Tier 3 collective tests once (not per-agent)
        if 3 in self._drift_tiers:
            try:
                collective_results = await self._harness.run_collective(3, self._runtime)
                collective_test_names = [r.test_name for r in collective_results]
                if collective_test_names:
                    crew_reports = await self._detector.analyze_all_agents(
                        ["__crew__"], collective_test_names
                    )
                    for report in crew_reports:
                        self._latest_reports[report.agent_id] = report
                        if report.drift_detected:
                            self._emit_drift_events(report)
            except Exception:
                logger.debug("run_now: collective test run failed", exc_info=True)

        # Analyze
        reports = await self._detector.analyze_all_agents(agent_ids, test_names)
        for report in reports:
            self._latest_reports[report.agent_id] = report
            if report.drift_detected:
                self._emit_drift_events(report)

        self._last_run_time = time.time()
        return reports

    @property
    def last_run_time(self) -> float:
        """Timestamp of last completed drift check cycle."""
        return self._last_run_time

    @property
    def latest_reports(self) -> dict[str, DriftReport]:
        """Most recent DriftReport per agent_id. For VitalsMonitor."""
        return dict(self._latest_reports)

    def _get_crew_agent_ids(self) -> list[str]:
        """Enumerate active crew agent IDs from runtime."""
        try:
            from probos.crew_utils import is_crew_agent

            ids = []
            pools = getattr(self._runtime, "pools", {})
            for pool in pools.values():
                for agent in getattr(pool, "healthy_agents", []):
                    if is_crew_agent(agent):
                        ids.append(agent.id)
            return ids
        except Exception:
            logger.debug("Failed to enumerate crew agents", exc_info=True)
            return []

    def _emit_drift_events(self, report: DriftReport) -> None:
        """Emit QUALIFICATION_DRIFT_DETECTED events for warning/critical signals."""
        if not self._emit_event_fn:
            return

        now = time.time()
        for signal in report.signals:
            if signal.severity not in ("warning", "critical"):
                continue

            cooldown_key = f"{signal.agent_id}:{signal.test_name}"
            last = self._last_check.get(cooldown_key, 0.0)
            if now - last < self._config.drift_cooldown_seconds:
                continue  # cooldown active

            self._last_check[cooldown_key] = now

            try:
                from probos.events import EventType

                self._emit_event_fn(
                    EventType.QUALIFICATION_DRIFT_DETECTED,
                    {
                        "agent_id": signal.agent_id,
                        "test_name": signal.test_name,
                        "z_score": signal.z_score,
                        "severity": signal.severity,
                        "current_score": signal.current_score,
                        "mean_score": signal.mean_score,
                        "baseline_score": signal.baseline_score,
                        "direction": signal.direction,
                        "sample_count": signal.sample_count,
                    },
                )
            except Exception:
                logger.debug("Failed to emit drift event", exc_info=True)
