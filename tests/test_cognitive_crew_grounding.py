"""Tests for AD-513: Crew complement cognitive grounding."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


class TestCrewComplement:
    """AD-513: Crew complement cognitive grounding."""

    def _make_agent(self, agent_type: str = "test_agent"):
        """Create a minimal CognitiveAgent for testing."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent.agent_type = agent_type
        agent._runtime = None
        return agent

    def test_complement_graceful_without_ontology(self):
        """Returns empty string if ontology not available."""
        agent = self._make_agent()
        assert agent._build_crew_complement() == ""

    def test_complement_graceful_without_runtime(self):
        """Returns empty string if runtime not set."""
        agent = self._make_agent()
        agent._runtime = None
        assert agent._build_crew_complement() == ""

    def test_complement_excludes_self(self):
        """Agent's own callsign is excluded from the complement."""
        agent = self._make_agent("security_agent")
        rt = MagicMock()
        rt.ontology.get_crew_manifest.return_value = [
            {"agent_type": "security_agent", "callsign": "Worf", "department": "security"},
            {"agent_type": "engineer", "callsign": "LaForge", "department": "engineering"},
            {"agent_type": "medic", "callsign": "Bones", "department": "medical"},
        ]
        rt.callsign_registry = None
        agent._runtime = rt
        result = agent._build_crew_complement()
        assert "Worf" not in result
        assert "LaForge" in result
        assert "Bones" in result

    def test_complement_department_grouped(self):
        """Crew are grouped by department in the complement block."""
        agent = self._make_agent("test_agent")
        rt = MagicMock()
        rt.ontology.get_crew_manifest.return_value = [
            {"agent_type": "engineer", "callsign": "LaForge", "department": "engineering"},
            {"agent_type": "medic", "callsign": "Bones", "department": "medical"},
        ]
        rt.callsign_registry = None
        agent._runtime = rt
        result = agent._build_crew_complement()
        assert "Engineering:" in result
        assert "Medical:" in result
        assert "LaForge" in result
        assert "Bones" in result

    def test_complement_includes_anti_confab_instruction(self):
        """Block ends with anti-confabulation instruction."""
        agent = self._make_agent("test_agent")
        rt = MagicMock()
        rt.ontology.get_crew_manifest.return_value = [
            {"agent_type": "engineer", "callsign": "LaForge", "department": "engineering"},
        ]
        rt.callsign_registry = None
        agent._runtime = rt
        result = agent._build_crew_complement()
        assert "Do NOT reference crew members who are not listed above" in result

    def test_complement_header(self):
        """Block starts with SHIP'S COMPLEMENT header."""
        agent = self._make_agent("test_agent")
        rt = MagicMock()
        rt.ontology.get_crew_manifest.return_value = [
            {"agent_type": "engineer", "callsign": "LaForge", "department": "engineering"},
        ]
        rt.callsign_registry = None
        agent._runtime = rt
        result = agent._build_crew_complement()
        assert "SHIP'S COMPLEMENT" in result

    def test_complement_empty_manifest_returns_empty(self):
        """Returns empty string when manifest is empty."""
        agent = self._make_agent("test_agent")
        rt = MagicMock()
        rt.ontology.get_crew_manifest.return_value = []
        rt.callsign_registry = None
        agent._runtime = rt
        assert agent._build_crew_complement() == ""
