"""Holodeck: gap-driven scenarios (AD-539b) and team simulations (AD-510).

AD-1355 S1 (#1700) deleted the AD-486 onboarding construct and the
department scheduler this package also held. Newcomer acclimation is
AD-1355's, from S2 on.
"""

from probos.holodeck.scenarios import (
    GapScenarioGenerator,
    HolodeckGapBridge,
    HolodeckGapDrill,
    HolodeckScenarioStore,
    ScenarioGapLink,
    ScenarioOutcome,
)
from probos.holodeck.team_simulations import (
    DebriefRecord,
    TeamScenario,
    TeamScenarioRegistry,
    TeamSimulationDrill,
    TeamSimulationOrchestrator,
    TeamSimulationParticipant,
    TeamSimulationRecord,
    TeamSimulationStore,
)

__all__ = [
    "DebriefRecord",
    "GapScenarioGenerator",
    "HolodeckGapBridge",
    "HolodeckGapDrill",
    "HolodeckScenarioStore",
    "ScenarioGapLink",
    "ScenarioOutcome",
    "TeamScenario",
    "TeamScenarioRegistry",
    "TeamSimulationDrill",
    "TeamSimulationOrchestrator",
    "TeamSimulationParticipant",
    "TeamSimulationRecord",
    "TeamSimulationStore",
]
