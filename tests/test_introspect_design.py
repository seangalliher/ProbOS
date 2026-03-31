"""Tests for AD-295d / AD-297: Self-Introspection via CodebaseIndex."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.agents.introspect import IntrospectionAgent
from probos.runtime import ProbOSRuntime
from probos.types import IntentMessage


def _make_rt_with_codebase():
    """Create a mock runtime with a codebase_index."""
    rt = MagicMock(spec=ProbOSRuntime)
    rt.codebase_index = MagicMock()
    rt.codebase_index.query.return_value = {
        "matching_files": [
            {"path": "consensus/trust.py", "docstring": "Trust network", "relevance": 5},
            {"path": "runtime.py", "docstring": "Runtime core", "relevance": 3},
        ],
        "matching_agents": [{"type": "introspect"}],
        "matching_methods": [],
        "layer": "consensus",
    }
    rt.codebase_index.read_source.return_value = "class TrustNetwork:\n    \"\"\"Trust scoring.\"\"\"\n    pass\n"
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
        assert "source_snippets" in data

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

    @pytest.mark.asyncio
    async def test_introspect_design_includes_source_snippets(self):
        """introspect_design returns source snippets from matching files (AD-297)."""
        rt = _make_rt_with_codebase()
        agent = IntrospectionAgent(agent_id="intro-0")
        agent._runtime = rt

        msg = IntentMessage(
            intent="introspect_design",
            params={"question": "trust"},
        )
        result = await agent.handle_intent(msg)

        assert result.success is True
        data = result.result
        snippets = data["source_snippets"]
        assert len(snippets) == 2  # 2 matching files in mock
        assert snippets[0]["path"] == "consensus/trust.py"
        assert "TrustNetwork" in snippets[0]["source"]

    @pytest.mark.asyncio
    async def test_introspect_design_limits_snippets_to_three(self):
        """Source snippets are limited to the top 3 matching files (AD-297)."""
        rt = _make_rt_with_codebase()
        # Override query to return 5 matching files
        rt.codebase_index.query.return_value = {
            "matching_files": [
                {"path": f"file_{i}.py", "docstring": f"File {i}", "relevance": 5 - i}
                for i in range(5)
            ],
            "matching_agents": [],
            "matching_methods": [],
            "layer": None,
        }
        agent = IntrospectionAgent(agent_id="intro-0")
        agent._runtime = rt

        msg = IntentMessage(
            intent="introspect_design",
            params={"question": "something"},
        )
        result = await agent.handle_intent(msg)

        data = result.result
        assert len(data["source_snippets"]) == 3

    @pytest.mark.asyncio
    async def test_introspect_design_skips_empty_source(self):
        """Files where read_source returns empty string are excluded (AD-297)."""
        rt = _make_rt_with_codebase()
        # First file returns source, second returns empty
        rt.codebase_index.read_source.side_effect = [
            "class Foo: pass\n",
            "",
        ]
        agent = IntrospectionAgent(agent_id="intro-0")
        agent._runtime = rt

        msg = IntentMessage(
            intent="introspect_design",
            params={"question": "trust"},
        )
        result = await agent.handle_intent(msg)

        data = result.result
        assert len(data["source_snippets"]) == 1
        assert data["source_snippets"][0]["path"] == "consensus/trust.py"

    @pytest.mark.asyncio
    async def test_codebase_index_always_available(self):
        """CodebaseIndex is available even when medical config is disabled (AD-297)."""
        rt = MagicMock(spec=ProbOSRuntime)
        # Simulate medical disabled but codebase_index still present
        rt.config = MagicMock()
        rt.config.medical.enabled = False
        rt.codebase_index = MagicMock()
        rt.codebase_index.query.return_value = {
            "matching_files": [],
            "matching_agents": [],
            "matching_methods": [],
            "layer": None,
        }
        rt.codebase_index.get_agent_map.return_value = []
        rt.codebase_index.get_layer_map.return_value = {}

        agent = IntrospectionAgent(agent_id="intro-0")
        agent._runtime = rt

        msg = IntentMessage(
            intent="introspect_design",
            params={"question": "anything"},
        )
        result = await agent.handle_intent(msg)

        # Should succeed — codebase_index is not None
        assert result.success is True
        assert "message" not in result.result  # No "not available" fallback
        assert "architecture_context" in result.result

    @pytest.mark.asyncio
    async def test_introspect_design_uses_section_reading_for_docs(self):
        """Doc files use read_doc_sections instead of read_source (AD-300)."""
        rt = MagicMock(spec=ProbOSRuntime)
        rt.codebase_index = MagicMock()
        rt.codebase_index.query.return_value = {
            "matching_files": [
                {"path": "docs:docs/development/roadmap.md", "docstring": "Roadmap", "relevance": 5},
                {"path": "consensus/trust.py", "docstring": "Trust", "relevance": 3},
            ],
            "matching_agents": [],
            "matching_methods": [],
            "layer": None,
        }
        rt.codebase_index.read_doc_sections.return_value = "## Security Team\n\nSecurity content.\n"
        rt.codebase_index.read_source.return_value = "class TrustNetwork: pass\n"
        rt.codebase_index.get_agent_map.return_value = []
        rt.codebase_index.get_layer_map.return_value = {}

        agent = IntrospectionAgent(agent_id="intro-0")
        agent._runtime = rt

        msg = IntentMessage(
            intent="introspect_design",
            params={"question": "security team"},
        )
        result = await agent.handle_intent(msg)

        assert result.success is True
        # read_doc_sections should be called for the docs: file
        rt.codebase_index.read_doc_sections.assert_called_once()
        call_args = rt.codebase_index.read_doc_sections.call_args
        assert call_args[0][0] == "docs:docs/development/roadmap.md"
        # read_source should be called for the source file
        rt.codebase_index.read_source.assert_called_once_with("consensus/trust.py", end_line=80)
