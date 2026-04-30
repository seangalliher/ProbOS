from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.config import EarnedAgencyConfig
from probos.crew_profile import Rank
from probos.earned_agency import InitiativeLevel, resolve_initiative_level


def test_initiative_level_enum_values() -> None:
    assert InitiativeLevel.DIRECTED.value == 0
    assert InitiativeLevel.RESPONSIVE.value == 1
    assert InitiativeLevel.CONTRIBUTORY.value == 2
    assert InitiativeLevel.PROACTIVE.value == 3
    assert InitiativeLevel.STRATEGIC.value == 4


def test_initiative_level_ordering() -> None:
    assert int(InitiativeLevel.DIRECTED) < int(InitiativeLevel.RESPONSIVE)
    assert int(InitiativeLevel.RESPONSIVE) < int(InitiativeLevel.CONTRIBUTORY)
    assert int(InitiativeLevel.CONTRIBUTORY) < int(InitiativeLevel.PROACTIVE)
    assert int(InitiativeLevel.PROACTIVE) < int(InitiativeLevel.STRATEGIC)


def test_ensign_low_trust_directed() -> None:
    assert resolve_initiative_level(Rank.ENSIGN, 0.1) is InitiativeLevel.DIRECTED


def test_ensign_moderate_trust_responsive() -> None:
    assert resolve_initiative_level(Rank.ENSIGN, 0.4) is InitiativeLevel.RESPONSIVE


def test_lieutenant_low_trust_responsive() -> None:
    assert resolve_initiative_level(Rank.LIEUTENANT, 0.3) is InitiativeLevel.RESPONSIVE


def test_lieutenant_high_trust_contributory() -> None:
    assert resolve_initiative_level(Rank.LIEUTENANT, 0.6) is InitiativeLevel.CONTRIBUTORY


def test_commander_high_trust_proactive() -> None:
    assert resolve_initiative_level(Rank.COMMANDER, 0.8) is InitiativeLevel.PROACTIVE


def test_senior_always_strategic() -> None:
    assert resolve_initiative_level(Rank.SENIOR, 0.0) is InitiativeLevel.STRATEGIC
    assert resolve_initiative_level(Rank.SENIOR, 1.0) is InitiativeLevel.STRATEGIC


def test_rank_from_trust_maps_low_trust_to_ensign() -> None:
    assert Rank.from_trust(0.1) is Rank.ENSIGN


def test_resolve_initiative_level_custom_thresholds_override_defaults() -> None:
    thresholds = {"responsive": 0.2, "contributory": 0.4, "proactive": 0.9}

    assert (
        resolve_initiative_level(Rank.COMMANDER, 0.8, thresholds=thresholds)
        is InitiativeLevel.CONTRIBUTORY
    )
    assert (
        resolve_initiative_level(Rank.COMMANDER, 0.95, thresholds=thresholds)
        is InitiativeLevel.PROACTIVE
    )


def test_earned_agency_config_initiative_thresholds_defaults() -> None:
    config = EarnedAgencyConfig()

    assert config.initiative_trust_thresholds == {
        "responsive": 0.3,
        "contributory": 0.5,
        "proactive": 0.7,
    }


def test_agent_metrics_include_initiative_level_from_runtime_trust() -> None:
    runtime = MagicMock()
    runtime.trust_network.get_score.return_value = 0.6
    runtime.config = SimpleNamespace(earned_agency=EarnedAgencyConfig())
    runtime.ontology.get_crew_context.return_value = None
    agent = CognitiveAgent(agent_id="agent-1", instructions="Test instructions.")
    agent._runtime = runtime

    with patch.object(agent, "_build_temporal_context", return_value=""):
        result = agent._build_cognitive_baseline({})

    assert "Initiative: 2" in result["_agent_metrics"]


def test_agent_metrics_use_configured_initiative_thresholds() -> None:
    runtime = MagicMock()
    runtime.trust_network.get_score.return_value = 0.8
    runtime.config = SimpleNamespace(
        earned_agency=SimpleNamespace(
            initiative_trust_thresholds={
                "responsive": 0.3,
                "contributory": 0.5,
                "proactive": 0.9,
            }
        )
    )
    runtime.ontology.get_crew_context.return_value = None
    agent = CognitiveAgent(agent_id="agent-1", instructions="Test instructions.")
    agent._runtime = runtime

    with patch.object(agent, "_build_temporal_context", return_value=""):
        result = agent._build_cognitive_baseline({})

    assert "Initiative: 2" in result["_agent_metrics"]
