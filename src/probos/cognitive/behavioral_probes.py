"""AD-569: Tier 3 Behavioral Qualification Probes.

Five crew-wide probes measuring observable collaboration quality.
Read-only consumers of BehavioralMetricsEngine snapshots.
No LLM calls, no triggering new computations.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.cognitive.qualification import TestResult

logger = logging.getLogger(__name__)

CREW_AGENT_ID = "__crew__"


def _skip_result(test_name: str, reason: str) -> TestResult:
    """Return a skip-passing TestResult."""
    return TestResult(
        agent_id=CREW_AGENT_ID,
        test_name=test_name,
        tier=3,
        score=0.0,
        passed=True,
        timestamp=time.time(),
        duration_ms=0.0,
        details={"skipped": True, "reason": reason},
    )


class FrameDiversityProbe:
    """Measures analytical frame diversity across departments."""

    @property
    def name(self) -> str:
        return "frame_diversity"

    @property
    def tier(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Analytical Frame Diversity — distinct perspectives per department in multi-agent threads"

    @property
    def threshold(self) -> float:
        return 0.0

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        engine = getattr(runtime, "_behavioral_metrics_engine", None)
        if not engine:
            return _skip_result(self.name, "Behavioral metrics engine not available")
        snapshot = engine.latest_snapshot
        if not snapshot:
            return _skip_result(self.name, "No behavioral snapshot available")

        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=3,
            score=snapshot.frame_diversity_score,
            passed=True,
            timestamp=time.time(),
            duration_ms=0.0,
            details={
                "frame_diversity_score": snapshot.frame_diversity_score,
                "threads_analyzed": snapshot.frame_diversity_threads,
                "department_representation": snapshot.department_representation,
            },
        )


class SynthesisDetectionProbe:
    """Measures synthesis rate — novel insights from collaboration."""

    @property
    def name(self) -> str:
        return "synthesis_detection"

    @property
    def tier(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Synthesis Detection — novel elements not attributable to any single agent"

    @property
    def threshold(self) -> float:
        return 0.0

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        engine = getattr(runtime, "_behavioral_metrics_engine", None)
        if not engine:
            return _skip_result(self.name, "Behavioral metrics engine not available")
        snapshot = engine.latest_snapshot
        if not snapshot:
            return _skip_result(self.name, "No behavioral snapshot available")

        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=3,
            score=snapshot.synthesis_rate,
            passed=True,
            timestamp=time.time(),
            duration_ms=0.0,
            details={
                "synthesis_rate": snapshot.synthesis_rate,
                "synthesis_threads": snapshot.synthesis_threads,
                "total_novel_elements": snapshot.total_novel_elements,
            },
        )


class CrossDeptTriggerProbe:
    """Measures cross-department investigation trigger rate."""

    @property
    def name(self) -> str:
        return "cross_dept_trigger_rate"

    @property
    def tier(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Cross-Department Trigger Rate — findings in one department driving investigation in another"

    @property
    def threshold(self) -> float:
        return 0.0

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        engine = getattr(runtime, "_behavioral_metrics_engine", None)
        if not engine:
            return _skip_result(self.name, "Behavioral metrics engine not available")
        snapshot = engine.latest_snapshot
        if not snapshot:
            return _skip_result(self.name, "No behavioral snapshot available")

        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=3,
            score=snapshot.cross_dept_trigger_rate,
            passed=True,
            timestamp=time.time(),
            duration_ms=0.0,
            details={
                "trigger_rate": snapshot.cross_dept_trigger_rate,
                "trigger_events": snapshot.trigger_events,
                "trigger_pairs": snapshot.trigger_pairs[:10],
            },
        )


class ConvergenceCorrectnessProbe:
    """Measures correctness rate of converged conclusions."""

    @property
    def name(self) -> str:
        return "convergence_correctness"

    @property
    def tier(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Convergence Correctness — quality of converged agent conclusions (when verifiable)"

    @property
    def threshold(self) -> float:
        return 0.0

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        engine = getattr(runtime, "_behavioral_metrics_engine", None)
        if not engine:
            return _skip_result(self.name, "Behavioral metrics engine not available")
        snapshot = engine.latest_snapshot
        if not snapshot:
            return _skip_result(self.name, "No behavioral snapshot available")

        score = snapshot.convergence_correctness_rate if snapshot.convergence_correctness_rate is not None else 0.0
        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=3,
            score=score,
            passed=True,
            timestamp=time.time(),
            duration_ms=0.0,
            details={
                "convergence_events": snapshot.convergence_events,
                "verified_correct": snapshot.verified_correct,
                "verified_incorrect": snapshot.verified_incorrect,
                "unverified": snapshot.unverified,
                "correctness_rate": snapshot.convergence_correctness_rate,
            },
        )


class AnchorGroundedEmergenceProbe:
    """Measures emergence backed by independent anchor provenance."""

    @property
    def name(self) -> str:
        return "anchor_grounded_emergence"

    @property
    def tier(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Anchor-Grounded Emergence — insights backed by independently-observed evidence"

    @property
    def threshold(self) -> float:
        return 0.0

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        engine = getattr(runtime, "_behavioral_metrics_engine", None)
        if not engine:
            return _skip_result(self.name, "Behavioral metrics engine not available")
        snapshot = engine.latest_snapshot
        if not snapshot:
            return _skip_result(self.name, "No behavioral snapshot available")

        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=3,
            score=snapshot.anchor_grounded_rate,
            passed=True,
            timestamp=time.time(),
            duration_ms=0.0,
            details={
                "grounded_rate": snapshot.anchor_grounded_rate,
                "independence_score": snapshot.anchor_independence_score,
                "analyzed_threads": snapshot.anchor_analyzed_threads,
            },
        )
