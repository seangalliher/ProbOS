"""AD-536: Tests for CognitiveAgent._route_promotion_approval() and _DEPARTMENT_CHIEFS."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent


def _make_agent(agent_type: str = "test_agent", department: str | None = None) -> CognitiveAgent:
    """Create a minimal CognitiveAgent for routing tests."""
    config = MagicMock()
    config.llm = MagicMock()
    config.llm.model_name = "test"
    config.llm.temperature = 0.7
    model_registry = MagicMock()
    model_registry.get_best_model = MagicMock(return_value=MagicMock())

    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.agent_type = agent_type
    agent._runtime = MagicMock()
    if department:
        agent._runtime.ontology.get_agent_department.return_value = department
    else:
        agent._runtime.ontology = None
    return agent


class TestDepartmentChiefs:
    """Verify the _DEPARTMENT_CHIEFS mapping is correct."""

    def test_chiefs_contains_all_departments(self) -> None:
        expected = {"engineering", "medical", "science", "security", "operations", "bridge"}
        assert set(CognitiveAgent._DEPARTMENT_CHIEFS.keys()) == expected

    def test_chiefs_values(self) -> None:
        chiefs = CognitiveAgent._DEPARTMENT_CHIEFS
        assert chiefs["engineering"] == "laforge"
        assert chiefs["medical"] == "bones"
        assert chiefs["science"] == "number_one"
        assert chiefs["security"] == "worf"
        assert chiefs["operations"] == "obrien"
        assert chiefs["bridge"] == "captain"


class TestRoutePromotionApproval:
    """Verify routing logic for promotion approval."""

    @patch("probos.config.PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD", "high")
    def test_low_criticality_engineering_routes_to_laforge(self) -> None:
        agent = _make_agent(department="engineering")
        assert agent._route_promotion_approval("low") == "laforge"

    @patch("probos.config.PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD", "high")
    def test_medium_criticality_medical_routes_to_bones(self) -> None:
        agent = _make_agent(department="medical")
        assert agent._route_promotion_approval("medium") == "bones"

    @patch("probos.config.PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD", "high")
    def test_high_criticality_routes_to_captain(self) -> None:
        agent = _make_agent(department="engineering")
        assert agent._route_promotion_approval("high") == "captain"

    @patch("probos.config.PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD", "high")
    def test_critical_routes_to_captain(self) -> None:
        agent = _make_agent(department="medical")
        assert agent._route_promotion_approval("critical") == "captain"

    @patch("probos.config.PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD", "high")
    def test_unknown_department_falls_back_to_captain(self) -> None:
        agent = _make_agent(department="nonexistent_dept")
        assert agent._route_promotion_approval("low") == "captain"

    @patch("probos.config.PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD", "high")
    def test_bridge_department_routes_to_captain(self) -> None:
        agent = _make_agent(department="bridge")
        assert agent._route_promotion_approval("medium") == "captain"

    @patch("probos.config.PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD", "high")
    def test_no_ontology_falls_back_to_captain(self) -> None:
        agent = _make_agent(department=None)  # ontology set to None
        assert agent._route_promotion_approval("low") == "captain"

    @patch("probos.config.PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD", "high")
    def test_science_department_routes_to_number_one(self) -> None:
        agent = _make_agent(department="science")
        assert agent._route_promotion_approval("medium") == "number_one"
