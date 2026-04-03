"""Tests for BF-101: Agent uses seed callsign instead of chosen callsign.

Validates:
- _resolve_callsign() helper with live attribute, birth cert fallback, no identity
- _build_personality_block cache correctness across callsign overrides
- _decide_via_llm passes resolved callsign (not None)
- Warm boot restores callsign correctly
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.standing_orders import _build_personality_block


@pytest.fixture(autouse=True)
def _clear_decision_cache():
    """Clear CognitiveAgent decision cache between tests to prevent pollution."""
    from probos.cognitive.cognitive_agent import _DECISION_CACHES

    _DECISION_CACHES.clear()
    yield
    _DECISION_CACHES.clear()


@pytest.fixture(autouse=True)
def _clear_personality_cache():
    """Clear personality block lru_cache between tests."""
    _build_personality_block.cache_clear()
    yield
    _build_personality_block.cache_clear()


def _make_agent(**overrides) -> CognitiveAgent:
    """Create a bare CognitiveAgent for unit testing."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.callsign = ""
    agent.agent_type = "data_analyst"
    agent.id = "sci_data_analyst_0_abc12345"
    agent._runtime = None
    for k, v in overrides.items():
        setattr(agent, k, v)
    return agent


# -----------------------------------------------------------------------
# _resolve_callsign() tests
# -----------------------------------------------------------------------


class TestResolveCallsign:
    """BF-101: _resolve_callsign() helper method."""

    def test_uses_live_attribute(self):
        """Agent with callsign='Kira' returns 'Kira'."""
        agent = _make_agent(callsign="Kira")
        assert agent._resolve_callsign() == "Kira"

    def test_falls_back_to_birth_cert(self):
        """Agent with callsign='' but birth cert with 'Kira' restores and returns 'Kira'."""
        cert = SimpleNamespace(callsign="Kira")
        registry = MagicMock()
        registry.get_by_slot.return_value = cert

        rt = SimpleNamespace(_identity_registry=registry)
        agent = _make_agent(callsign="", _runtime=rt)

        result = agent._resolve_callsign()
        assert result == "Kira"
        # Should also restore to live attribute
        assert agent.callsign == "Kira"

    def test_returns_none_when_no_identity(self):
        """Agent with callsign='' and no birth cert returns None."""
        registry = MagicMock()
        registry.get_by_slot.return_value = None

        rt = SimpleNamespace(_identity_registry=registry)
        agent = _make_agent(callsign="", _runtime=rt)

        assert agent._resolve_callsign() is None

    def test_returns_none_when_no_runtime(self):
        """Agent with callsign='' and no runtime returns None."""
        agent = _make_agent(callsign="", _runtime=None)
        assert agent._resolve_callsign() is None

    def test_returns_none_when_no_registry(self):
        """Agent with runtime but no identity_registry returns None."""
        rt = SimpleNamespace(_identity_registry=None)
        agent = _make_agent(callsign="", _runtime=rt)
        assert agent._resolve_callsign() is None

    def test_empty_cert_callsign_returns_none(self):
        """Birth cert with empty callsign returns None."""
        cert = SimpleNamespace(callsign="")
        registry = MagicMock()
        registry.get_by_slot.return_value = cert

        rt = SimpleNamespace(_identity_registry=registry)
        agent = _make_agent(callsign="", _runtime=rt)

        assert agent._resolve_callsign() is None


# -----------------------------------------------------------------------
# _build_personality_block cache tests
# -----------------------------------------------------------------------


class TestPersonalityBlockCallsign:
    """BF-101: personality block uses correct callsign."""

    def test_uses_runtime_callsign(self):
        """_build_personality_block with override='Kira' produces 'Kira' not 'Rahda'."""
        block = _build_personality_block("data_analyst", "science", "Kira")
        assert "Kira" in block
        # Should NOT contain the seed callsign as the identity
        lines = block.split("\n")
        identity_lines = [l for l in lines if "You are " in l]
        for line in identity_lines:
            assert "Rahda" not in line

    def test_none_override_uses_seed(self):
        """_build_personality_block with None falls back to YAML seed 'Rahda'."""
        block = _build_personality_block("data_analyst", "science", None)
        assert "Rahda" in block

    def test_cache_key_includes_callsign(self):
        """Two calls with different callsign_override return different results."""
        block_kira = _build_personality_block("data_analyst", "science", "Kira")
        block_rahda = _build_personality_block("data_analyst", "science", None)
        assert block_kira != block_rahda
        assert "Kira" in block_kira
        assert "Rahda" in block_rahda
