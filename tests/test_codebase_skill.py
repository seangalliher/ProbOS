"""Tests for CodebaseSkill handler actions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.cognitive.codebase_skill import create_codebase_skill
from probos.types import IntentMessage


def _make_intent(action: str, **params) -> IntentMessage:
    """Create a mock IntentMessage for the codebase skill."""
    return IntentMessage(
        intent="codebase_knowledge",
        params={"action": action, **params},
    )


class TestCodebaseSkillHandler:
    """Tests for all handler actions."""

    @pytest.fixture
    def index(self):
        """Create a mock CodebaseIndex."""
        idx = MagicMock()
        idx.query.return_value = [{"file": "foo.py", "score": 1.0}]
        idx.read_source.return_value = "def foo(): pass"
        idx.get_agent_map.return_value = {"builder": "BuilderAgent"}
        idx.get_layer_map.return_value = {"core": ["runtime.py"]}
        idx.get_config_schema.return_value = {"host": "str", "port": "int"}
        idx.get_api_surface.return_value = {"methods": ["start", "stop"]}
        return idx

    @pytest.fixture
    def skill(self, index):
        """Create a codebase skill with the mock index."""
        return create_codebase_skill(index)

    @pytest.mark.asyncio
    async def test_query_action(self, skill, index):
        """'query' action calls index.query() and returns results."""
        intent = _make_intent("query", query="builder")
        result = await skill.handler(intent)
        assert result.success is True
        index.query.assert_called_once_with("builder")

    @pytest.mark.asyncio
    async def test_read_source_action(self, skill, index):
        """'read_source' action returns file content."""
        intent = _make_intent("read_source", file_path="src/foo.py")
        result = await skill.handler(intent)
        assert result.success is True
        index.read_source.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_source_with_line_range(self, skill, index):
        """'read_source' with start_line/end_line passes them as ints."""
        intent = _make_intent("read_source", file_path="foo.py", start_line=10, end_line=20)
        result = await skill.handler(intent)
        assert result.success is True
        _, kwargs = index.read_source.call_args
        assert kwargs.get("start_line") == 10
        assert kwargs.get("end_line") == 20

    @pytest.mark.asyncio
    async def test_get_agent_map_action(self, skill, index):
        """'get_agent_map' action returns the agent type map."""
        intent = _make_intent("get_agent_map")
        result = await skill.handler(intent)
        assert result.success is True
        index.get_agent_map.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_layer_map_action(self, skill, index):
        """'get_layer_map' action returns the architecture layer map."""
        intent = _make_intent("get_layer_map")
        result = await skill.handler(intent)
        assert result.success is True
        index.get_layer_map.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_config_schema_action(self, skill, index):
        """'get_config_schema' action returns config schema info."""
        intent = _make_intent("get_config_schema")
        result = await skill.handler(intent)
        assert result.success is True
        index.get_config_schema.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_api_surface_action(self, skill, index):
        """'get_api_surface' action returns API surface data."""
        intent = _make_intent("get_api_surface", class_name="ProbOSRuntime")
        result = await skill.handler(intent)
        assert result.success is True
        index.get_api_surface.assert_called_once_with("ProbOSRuntime")

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self, skill):
        """Unknown action returns success=False."""
        intent = _make_intent("nonexistent_action")
        result = await skill.handler(intent)
        assert result.success is False
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_exception_handling(self, skill, index):
        """Exception during handling returns success=False with error string."""
        index.query.side_effect = RuntimeError("index broken")
        intent = _make_intent("query", query="test")
        result = await skill.handler(intent)
        assert result.success is False
        assert "index broken" in result.error

    def test_skill_metadata(self, skill):
        """Skill has expected name and origin."""
        assert skill.name == "codebase_knowledge"
        assert skill.origin == "builtin"
