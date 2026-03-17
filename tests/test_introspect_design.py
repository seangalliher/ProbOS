"""Tests for AD-295d: Self-Introspection via CodebaseIndex."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.agents.introspect import IntrospectionAgent
from probos.types import IntentMessage


def _make_rt_with_codebase():
    """Create a mock runtime with a codebase_index."""
    rt = MagicMock()
    rt.codebase_index = MagicMock()
    rt.codebase_index.query.return_value = {
        "files": [{"path": "src/probos/runtime.py", "layer": "cognitive"}],
        "agents": [{"type": "introspect", "file": "agents/introspect.py"}],
        "methods": [],
    }
    rt.codebase_index.get_agent_map.return_value = [
        {"type": "introspect"},
        {"type": "shell_command"},
    ]
    rt.codebase_index.get_layer_map.return_value = {
        "substrate": ["agent.py"],
        "mesh": ["routing.py"],
        "consensus": ["trust.py", "quorum.py"],
        "cognitive": ["episodic.py"],
    }
    return rt


def _make_rt_without_codebase():
    """Create a mock runtime without codebase_index."""
    rt = MagicMock(spec=[])
    return rt


class TestIntrospectDesign:
    @pytest.mark.asyncio
    async def test_introspect_design_returns_architecture(self):
        """introspect_design returns architecture context from CodebaseIndex."""
        rt = _make_rt_with_codebase()
        agent = IntrospectionAgent(agent_id="intro-0")
        agent._runtime = rt

        msg = IntentMessage(
            intent="introspect_design",
            params={"question": "How does trust scoring work?"},
        )
        result = await agent.handle_intent(msg)

        assert result is not None
        assert result.success is True
        data = result.result
        assert "architecture_context" in data
        assert data["agent_count"] == 2
        assert "consensus" in data["layers"]

    @pytest.mark.asyncio
    async def test_introspect_design_no_codebase(self):
        """introspect_design gracefully handles missing CodebaseIndex."""
        rt = _make_rt_without_codebase()
        agent = IntrospectionAgent(agent_id="intro-0")
        agent._runtime = rt

        msg = IntentMessage(
            intent="introspect_design",
            params={"question": "What is the architecture?"},
        )
        result = await agent.handle_intent(msg)

        assert result is not None
        assert result.success is True
        data = result.result
        assert "not available" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_introspect_design_in_handled_intents(self):
        """introspect_design is registered in the handled intents set."""
        assert "introspect_design" in IntrospectionAgent._handled_intents
        # Also in intent_descriptors
        names = [d.name for d in IntrospectionAgent.intent_descriptors]
        assert "introspect_design" in names
