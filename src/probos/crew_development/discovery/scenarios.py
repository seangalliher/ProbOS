"""DiscoveryScenarioRegistry (AD-512a v1).

Read-only catalog of capability discovery scenarios. Future Holodeck
consumers (AD-486, AD-510) read this registry, present scenarios, and
record outcomes via :class:`StrengthMap`.

v1 ships registry only; the registry never writes Hebbian edges or
episodes — those are caller responsibilities reserved for AD-486 / AD-510.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveryScenario:
    """A discovery scenario the Holodeck (AD-486) can present.

    ``capability_category`` is one of: ``analysis``, ``communication``,
    ``coordination``, ``construction``, ``diagnosis``.

    ``difficulty`` is a normalized scalar on [0.0, 1.0] used by the ZPD
    calibrator. ``scaffolding_level`` is one of ``high``, ``medium``,
    ``low``, ``none`` — a hint for the eventual presenter.
    """

    scenario_id: str
    title: str
    capability_category: str
    summary: str
    learning_objectives: tuple[str, ...]
    difficulty: float
    scaffolding_level: str


_DEFAULT_SCENARIOS: tuple[DiscoveryScenario, ...] = (
    DiscoveryScenario(
        scenario_id="diagnose_simple_fault",
        title="Diagnose a single-component fault",
        capability_category="diagnosis",
        summary="One subsystem reports anomaly; isolate cause and propose remediation.",
        learning_objectives=(
            "Identify the failing component",
            "Distinguish symptom from root cause",
            "Propose a reversible remediation",
        ),
        difficulty=0.30,
        scaffolding_level="high",
    ),
    DiscoveryScenario(
        scenario_id="diagnose_cross_subsystem",
        title="Diagnose a fault spanning two subsystems",
        capability_category="diagnosis",
        summary="Symptoms appear in two subsystems; locate the upstream cause.",
        learning_objectives=(
            "Trace causality across subsystem boundaries",
            "Recognize when a peer expert is needed",
        ),
        difficulty=0.65,
        scaffolding_level="medium",
    ),
    DiscoveryScenario(
        scenario_id="analyze_telemetry_window",
        title="Analyze a telemetry window for anomalies",
        capability_category="analysis",
        summary="Given a 5-minute telemetry window, identify outlier signals.",
        learning_objectives=(
            "Apply baseline-vs-window comparison",
            "Distinguish noise from signal",
        ),
        difficulty=0.45,
        scaffolding_level="medium",
    ),
    DiscoveryScenario(
        scenario_id="compose_briefing",
        title="Compose a briefing for the Captain",
        capability_category="communication",
        summary="Summarize a multi-thread Ward Room exchange in 4 sentences.",
        learning_objectives=(
            "Identify the Captain's decision question",
            "Suppress side detail; surface the actionable signal",
        ),
        difficulty=0.40,
        scaffolding_level="medium",
    ),
    DiscoveryScenario(
        scenario_id="coordinate_two_dept_handoff",
        title="Coordinate a two-department handoff",
        capability_category="coordination",
        summary="Engineering and Medical share an artifact; route the handoff cleanly.",
        learning_objectives=(
            "Identify each department's authoritative role",
            "Recognize when to escalate vs proceed",
        ),
        difficulty=0.55,
        scaffolding_level="medium",
    ),
    DiscoveryScenario(
        scenario_id="construct_remediation_plan",
        title="Construct a remediation plan from a diagnosis",
        capability_category="construction",
        summary="Given a confirmed diagnosis, produce a 3-step reversible remediation.",
        learning_objectives=(
            "Order steps so each is reversible at its boundary",
            "Identify the gate for crew approval",
        ),
        difficulty=0.60,
        scaffolding_level="low",
    ),
    DiscoveryScenario(
        scenario_id="construct_research_proposal",
        title="Construct a research proposal",
        capability_category="construction",
        summary="From an open question, produce a researchable proposal.",
        learning_objectives=(
            "Frame the question as falsifiable",
            "Identify scope boundaries",
        ),
        difficulty=0.75,
        scaffolding_level="low",
    ),
    DiscoveryScenario(
        scenario_id="communicate_under_time_pressure",
        title="Communicate a decision under time pressure",
        capability_category="communication",
        summary="60-second window to brief the Captain on a fast-moving incident.",
        learning_objectives=(
            "Surface the single most decision-relevant fact",
            "Suppress reflexive caveat-stacking",
        ),
        difficulty=0.70,
        scaffolding_level="none",
    ),
)


class DiscoveryScenarioRegistry:
    """Read-only registry of discovery scenarios. AD-512a v1.

    Default catalog seeds 8 scenarios across 5 capability categories.
    Extensible at runtime via :meth:`register_scenario` (no persistence
    in v1 — runtime-only).

    Public API:
        list_scenarios() -> tuple[DiscoveryScenario, ...]
        get_scenario(scenario_id) -> DiscoveryScenario | None
        list_by_category(category) -> tuple[DiscoveryScenario, ...]
        list_by_difficulty_band(low, high) -> tuple[DiscoveryScenario, ...]
        register_scenario(scenario) -> None
    """

    def __init__(self) -> None:
        self._scenarios: dict[str, DiscoveryScenario] = {
            s.scenario_id: s for s in _DEFAULT_SCENARIOS
        }
        self.emit_event: Callable[..., None] | None = None

    def list_scenarios(self) -> tuple[DiscoveryScenario, ...]:
        return tuple(self._scenarios.values())

    def get_scenario(self, scenario_id: str) -> DiscoveryScenario | None:
        s = self._scenarios.get(scenario_id)
        if s is not None:
            self._emit(scenario_id, "by_id")
        return s

    def list_by_category(self, category: str) -> tuple[DiscoveryScenario, ...]:
        out = tuple(s for s in self._scenarios.values() if s.capability_category == category)
        if out:
            self._emit("", f"by_category:{category}")
        return out

    def list_by_difficulty_band(
        self, low: float, high: float
    ) -> tuple[DiscoveryScenario, ...]:
        if low > high:
            return ()
        return tuple(
            s for s in self._scenarios.values()
            if low <= s.difficulty <= high
        )

    def register_scenario(self, scenario: DiscoveryScenario) -> None:
        """Add or overwrite a scenario by id (runtime-only; not persisted)."""
        self._scenarios[scenario.scenario_id] = scenario

    def _emit(self, scenario_id: str, query_type: str) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.DISCOVERY_SCENARIO_OFFERED,
                {
                    "scenario_id": scenario_id,
                    "query_type": query_type,
                },
            )
        except Exception:
            logger.warning(
                "AD-512a: emit_event failed for scenario_id=%s; continuing without event",
                scenario_id,
                exc_info=True,
            )
