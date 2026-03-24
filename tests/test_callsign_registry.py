"""Tests for AD-397: CallsignRegistry — callsign-based crew addressing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.crew_profile import CallsignRegistry


class TestLoadFromProfiles:
    """Test loading callsigns from crew profile YAMLs."""

    def test_load_from_profiles(self):
        """Load real YAML profiles, verify all 10 callsigns indexed (AD-398: reclassified infra)."""
        registry = CallsignRegistry()
        registry.load_from_profiles()
        callsigns = registry.all_callsigns()
        # 11 profiles with callsigns (excluding _default.yaml)
        assert len(callsigns) == 11

    def test_resolve_known_callsign(self):
        """Resolve 'wesley' -> agent_type 'scout'."""
        registry = CallsignRegistry()
        registry.load_from_profiles()
        result = registry.resolve("wesley")
        assert result is not None
        assert result["agent_type"] == "scout"
        assert result["callsign"] == "Wesley"

    def test_resolve_case_insensitive(self):
        """'Wesley', 'wesley', 'WESLEY' all resolve identically."""
        registry = CallsignRegistry()
        registry.load_from_profiles()
        r1 = registry.resolve("Wesley")
        r2 = registry.resolve("wesley")
        r3 = registry.resolve("WESLEY")
        assert r1 is not None
        assert r1["agent_type"] == r2["agent_type"] == r3["agent_type"]
        assert r1["callsign"] == r2["callsign"] == r3["callsign"]

    def test_resolve_unknown_callsign(self):
        """Returns None for 'picard'."""
        registry = CallsignRegistry()
        registry.load_from_profiles()
        assert registry.resolve("picard") is None

    def test_get_callsign_by_type(self):
        """get_callsign('builder') returns 'Scotty'."""
        registry = CallsignRegistry()
        registry.load_from_profiles()
        assert registry.get_callsign("builder") == "Scotty"

    def test_all_callsigns(self):
        """Returns dict mapping agent_type to display-case callsign."""
        registry = CallsignRegistry()
        registry.load_from_profiles()
        callsigns = registry.all_callsigns()
        assert isinstance(callsigns, dict)
        assert "Wesley" in callsigns.values()
        assert "Scotty" in callsigns.values()
        assert "Bones" in callsigns.values()

    def test_resolve_with_live_agent(self):
        """Bind a mock AgentRegistry with a live scout, verify agent_id returned."""
        registry = CallsignRegistry()
        registry.load_from_profiles()

        mock_agent = MagicMock()
        mock_agent.id = "scout-agent-123"
        mock_agent.is_alive = True
        mock_agent.pool = "scout"
        mock_agent.agent_type = "scout"

        mock_reg = MagicMock()
        mock_reg.get_by_pool.return_value = [mock_agent]
        registry.bind_registry(mock_reg)

        result = registry.resolve("wesley")
        assert result is not None
        assert result["agent_id"] == "scout-agent-123"

    def test_resolve_no_live_agent(self):
        """Bind a mock AgentRegistry with no scout, verify agent_id is None."""
        registry = CallsignRegistry()
        registry.load_from_profiles()

        mock_reg = MagicMock()
        mock_reg.get_by_pool.return_value = []
        registry.bind_registry(mock_reg)

        result = registry.resolve("wesley")
        assert result is not None
        assert result["agent_id"] is None

    def test_load_from_nonexistent_dir(self):
        """Loading from nonexistent directory doesn't crash."""
        registry = CallsignRegistry()
        registry.load_from_profiles(profiles_dir="/nonexistent/path")
        assert registry.all_callsigns() == {}

    def test_get_callsign_unknown_type(self):
        """get_callsign returns empty string for unknown type."""
        registry = CallsignRegistry()
        assert registry.get_callsign("unknown_type") == ""
