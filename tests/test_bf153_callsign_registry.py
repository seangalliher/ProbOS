"""BF-153: Shell directive commands use seed callsign instead of runtime callsign.

Root cause: commands_directives.get_callsign() reads from YAML seed profile,
ignoring the runtime callsign registry. After naming ceremony (agent self-names
e.g. "O'Brien" → "Cassian"), shell commands (/order, /revoke, /amend) still
display the seed callsign. Crew-identified by Reyes (Operations).

Fix: get_callsign() checks runtime.callsign_registry first (authoritative
after naming ceremony), falls back to YAML seed profile, then to formatted
agent_type.
"""

import pytest
from unittest.mock import MagicMock

from probos.experience.commands.commands_directives import get_callsign


class _MockCallsignRegistry:
    """Minimal mock of CallsignRegistry for testing."""

    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    def get_callsign(self, agent_type: str) -> str:
        return self._mapping.get(agent_type, "")


class TestGetCallsignRegistryFirst:
    """BF-153: get_callsign() prefers runtime registry over YAML seed."""

    def test_returns_runtime_callsign_when_available(self):
        """Runtime registry callsign takes precedence over seed."""
        runtime = MagicMock()
        runtime.callsign_registry = _MockCallsignRegistry({
            "operations_officer": "Cassian",
        })
        result = get_callsign("operations_officer", runtime)
        assert result == "Cassian"

    def test_falls_back_to_seed_when_registry_empty(self):
        """If registry returns empty string, fall back to seed profile."""
        runtime = MagicMock()
        runtime.callsign_registry = _MockCallsignRegistry({})
        result = get_callsign("operations_officer", runtime)
        # Should return seed callsign from YAML (O'Brien) or formatted name
        assert result  # non-empty
        assert result != ""

    def test_falls_back_to_seed_when_no_registry(self):
        """If runtime has no callsign_registry attr, fall back to seed."""
        runtime = MagicMock(spec=[])  # empty spec — no attributes
        result = get_callsign("operations_officer", runtime)
        assert result  # non-empty fallback

    def test_falls_back_to_seed_when_no_runtime(self):
        """If runtime is None, fall back to seed profile (backward compat)."""
        result = get_callsign("operations_officer", None)
        assert result  # non-empty fallback

    def test_backward_compat_no_runtime_arg(self):
        """Calling without runtime arg still works (default None)."""
        result = get_callsign("operations_officer")
        assert result  # non-empty fallback

    def test_runtime_registry_exception_falls_through(self):
        """If registry.get_callsign() raises, falls back gracefully."""
        runtime = MagicMock()
        runtime.callsign_registry.get_callsign.side_effect = RuntimeError("broken")
        result = get_callsign("operations_officer", runtime)
        assert result  # should still return something from seed/formatted

    def test_formatted_fallback_for_unknown_agent(self):
        """Unknown agent_type with no YAML file returns formatted name."""
        runtime = MagicMock()
        runtime.callsign_registry = _MockCallsignRegistry({})
        result = get_callsign("nonexistent_agent_type", runtime)
        assert result == "Nonexistent Agent Type"

    def test_all_crew_agents_resolve_from_registry(self):
        """Multiple agent types all resolved from registry, not YAML."""
        registry_map = {
            "operations_officer": "Cassian",
            "engineering_officer": "Forge",
            "security_officer": "Worf",
            "systems_analyst": "Lynx",
            "data_analyst": "Kira",
        }
        runtime = MagicMock()
        runtime.callsign_registry = _MockCallsignRegistry(registry_map)
        for agent_type, expected in registry_map.items():
            result = get_callsign(agent_type, runtime)
            assert result == expected, f"{agent_type}: expected '{expected}', got '{result}'"


class TestSeedCallsignStillWorks:
    """Seed profile fallback remains functional for pre-naming-ceremony state."""

    def test_seed_callsign_returned_without_runtime(self):
        """Without runtime, operations_officer should return seed 'O'Brien'."""
        result = get_callsign("operations_officer")
        assert result == "O'Brien"

    def test_seed_callsign_returned_with_empty_registry(self):
        """With empty registry, seed profile provides the default."""
        runtime = MagicMock()
        runtime.callsign_registry = _MockCallsignRegistry({})
        result = get_callsign("operations_officer", runtime)
        assert result == "O'Brien"
