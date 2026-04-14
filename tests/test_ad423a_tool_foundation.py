"""AD-423a: Tool Foundation tests.

22 tests across 7 classes covering Tool protocol, ToolRegistration,
ToolRegistry, InfraServiceAdapter, DirectServiceAdapter,
DeterministicFunctionAdapter, and SkillDefinition.preferred_tools.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.tools.protocol import (
    Tool,
    ToolPreference,
    ToolRegistration,
    ToolResult,
    ToolType,
)
from probos.tools.registry import ToolRegistry
from probos.tools.adapters import (
    DeterministicFunctionAdapter,
    DirectServiceAdapter,
    InfraServiceAdapter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubTool:
    """Minimal Tool protocol implementation for testing."""

    def __init__(
        self,
        tool_id: str = "stub_tool",
        name: str = "Stub Tool",
        tool_type: ToolType = ToolType.INFRA_SERVICE,
        description: str = "A stub tool for testing",
    ) -> None:
        self._tool_id = tool_id
        self._name = name
        self._tool_type = tool_type
        self._description = description

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return self._tool_type

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "string"}

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        return ToolResult(output="stub_result")


# ===========================================================================
# Class 1: TestToolProtocol
# ===========================================================================


class TestToolProtocol:
    def test_tool_result_success(self) -> None:
        r = ToolResult(output={"key": "value"})
        assert r.success is True
        assert r.output == {"key": "value"}
        assert r.error is None

    def test_tool_result_failure(self) -> None:
        r = ToolResult(error="something broke")
        assert r.success is False
        assert r.error == "something broke"
        assert r.output is None

    def test_tool_type_enum_values(self) -> None:
        values = [e.value for e in ToolType]
        assert len(values) == 9
        assert "utility_agent" in values
        assert "infra_service" in values
        assert "mcp_server" in values
        assert "remote_api" in values
        assert "computer_use" in values
        assert "browser" in values
        assert "communication" in values
        assert "federation" in values
        assert "deterministic_function" in values
        # All are str enum
        for e in ToolType:
            assert isinstance(e, str)


# ===========================================================================
# Class 2: TestToolRegistration
# ===========================================================================


class TestToolRegistration:
    def test_registration_to_dict(self) -> None:
        tool = _StubTool(tool_id="test_id", name="Test Tool")
        reg = ToolRegistration(
            tool=tool,
            domain="security",
            department="sec_dept",
            tags=["search", "query"],
            provider="ship_computer",
        )
        d = reg.to_dict()
        assert d["tool_id"] == "test_id"
        assert d["name"] == "Test Tool"
        assert d["tool_type"] == "infra_service"
        assert d["domain"] == "security"
        assert d["department"] == "sec_dept"
        assert d["tags"] == ["search", "query"]
        assert d["provider"] == "ship_computer"
        assert d["enabled"] is True
        assert "input_schema" in d
        assert "output_schema" in d

    def test_registration_properties(self) -> None:
        tool = _StubTool(tool_id="prop_test", tool_type=ToolType.COMMUNICATION)
        reg = ToolRegistration(tool=tool)
        assert reg.tool_id == "prop_test"
        assert reg.tool_type == ToolType.COMMUNICATION

    def test_tool_preference_dataclass(self) -> None:
        pref = ToolPreference(tool_id="codebase_query", priority=1, context="for search")
        assert pref.tool_id == "codebase_query"
        assert pref.priority == 1
        assert pref.context == "for search"
        # Defaults
        pref2 = ToolPreference(tool_id="other")
        assert pref2.priority == 0
        assert pref2.context == ""


# ===========================================================================
# Class 3: TestToolRegistry
# ===========================================================================


class TestToolRegistry:
    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        tool = _StubTool(tool_id="reg_test")
        reg = registry.register(tool, provider="test")
        assert reg.tool_id == "reg_test"
        assert reg.provider == "test"
        got = registry.get("reg_test")
        assert got is not None
        assert got.tool_id == "reg_test"

    def test_register_replace_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        registry = ToolRegistry()
        tool1 = _StubTool(tool_id="dup")
        tool2 = _StubTool(tool_id="dup", name="Replacement")
        registry.register(tool1)
        with caplog.at_level(logging.WARNING):
            registry.register(tool2)
        assert "Replacing existing tool registration: dup" in caplog.text
        assert registry.get("dup").tool.name == "Replacement"  # type: ignore[union-attr]

    def test_unregister(self) -> None:
        registry = ToolRegistry()
        registry.register(_StubTool(tool_id="del_me"))
        assert registry.unregister("del_me") is True
        assert registry.unregister("del_me") is False
        assert registry.get("del_me") is None

    def test_get_tool_convenience(self) -> None:
        registry = ToolRegistry()
        tool = _StubTool(tool_id="conv")
        registry.register(tool)
        got = registry.get_tool("conv")
        assert got is tool
        assert registry.get_tool("nope") is None

    def test_get_missing(self) -> None:
        registry = ToolRegistry()
        assert registry.get("missing") is None

    def test_list_tools_no_filter(self) -> None:
        registry = ToolRegistry()
        registry.register(_StubTool(tool_id="b_tool"))
        registry.register(_StubTool(tool_id="a_tool"))
        registry.register(_StubTool(tool_id="c_tool"))
        tools = registry.list_tools()
        assert [t.tool_id for t in tools] == ["a_tool", "b_tool", "c_tool"]

    def test_list_tools_with_filters(self) -> None:
        registry = ToolRegistry()
        registry.register(
            _StubTool(tool_id="sec_tool", tool_type=ToolType.INFRA_SERVICE),
            domain="security",
            department="sec_dept",
            tags=["search"],
        )
        registry.register(
            _StubTool(tool_id="eng_tool", tool_type=ToolType.COMMUNICATION),
            domain="engineering",
            department="eng_dept",
            tags=["comms"],
        )
        registry.register(
            _StubTool(tool_id="universal", tool_type=ToolType.INFRA_SERVICE),
            domain="*",
            tags=["search"],
        )

        # Filter by tool_type
        infra = registry.list_tools(tool_type=ToolType.INFRA_SERVICE)
        assert len(infra) == 2

        # Filter by domain — "*" domain tools always included
        sec_domain = registry.list_tools(domain="security")
        ids = [t.tool_id for t in sec_domain]
        assert "sec_tool" in ids
        assert "universal" in ids
        assert "eng_tool" not in ids

        # Filter by department — None department tools always included
        sec_dept = registry.list_tools(department="sec_dept")
        ids = [t.tool_id for t in sec_dept]
        assert "sec_tool" in ids
        assert "universal" in ids  # department=None → ship-wide
        assert "eng_tool" not in ids

        # Filter by tag
        search = registry.list_tools(tag="search")
        assert len(search) == 2

    def test_list_tools_enabled_only(self) -> None:
        registry = ToolRegistry()
        registry.register(_StubTool(tool_id="on"), enabled=True)
        registry.register(_StubTool(tool_id="off"), enabled=False)

        enabled = registry.list_tools(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0].tool_id == "on"

        all_tools = registry.list_tools(enabled_only=False)
        assert len(all_tools) == 2


# ===========================================================================
# Class 4: TestInfraServiceAdapter
# ===========================================================================


class TestInfraServiceAdapter:
    @pytest.mark.asyncio
    async def test_invoke_success(self) -> None:
        @dataclass
        class _FakeResult:
            success: bool = True
            result: str = "hello"
            error: str | None = None

        bus = AsyncMock()
        bus.broadcast.return_value = [_FakeResult()]
        adapter = InfraServiceAdapter(
            tool_id="infra_test",
            name="Test",
            description="Test infra adapter",
            intent_name="test_intent",
            intent_bus=bus,
        )
        result = await adapter.invoke({"query": "test"}, {"agent_id": "agent_1"})
        assert result.success is True
        assert result.output == "hello"
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_invoke_no_bus(self) -> None:
        adapter = InfraServiceAdapter(
            tool_id="no_bus",
            name="No Bus",
            description="No bus test",
            intent_name="noop",
        )
        result = await adapter.invoke({})
        assert result.success is False
        assert result.error == "Intent bus not available"

    @pytest.mark.asyncio
    async def test_invoke_bus_error(self) -> None:
        bus = AsyncMock()
        bus.broadcast.side_effect = RuntimeError("bus exploded")
        adapter = InfraServiceAdapter(
            tool_id="err_bus",
            name="Error Bus",
            description="Error test",
            intent_name="boom",
            intent_bus=bus,
        )
        result = await adapter.invoke({})
        assert result.success is False
        assert "bus exploded" in result.error  # type: ignore[operator]


# ===========================================================================
# Class 5: TestDirectServiceAdapter
# ===========================================================================


class TestDirectServiceAdapter:
    @pytest.mark.asyncio
    async def test_invoke_async_handler(self) -> None:
        async def _handler(query: str = "") -> str:
            return f"result:{query}"

        adapter = DirectServiceAdapter(
            tool_id="direct_test",
            name="Direct Test",
            description="Test direct adapter",
            handler=_handler,
        )
        result = await adapter.invoke({"query": "hello"})
        assert result.success is True
        assert result.output == "result:hello"
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_invoke_handler_error(self) -> None:
        async def _bad_handler(**kwargs: Any) -> None:
            raise ValueError("handler broke")

        adapter = DirectServiceAdapter(
            tool_id="bad_direct",
            name="Bad Direct",
            description="Failing handler",
            handler=_bad_handler,
        )
        result = await adapter.invoke({})
        assert result.success is False
        assert "handler broke" in result.error  # type: ignore[operator]

    def test_custom_tool_type(self) -> None:
        async def _handler(**kwargs: Any) -> None:
            return None

        adapter = DirectServiceAdapter(
            tool_id="custom_type",
            name="Custom Type",
            description="Custom tool type test",
            handler=_handler,
            tool_type=ToolType.COMMUNICATION,
        )
        assert adapter.tool_type == ToolType.COMMUNICATION


# ===========================================================================
# Class 6: TestDeterministicFunctionAdapter
# ===========================================================================


class TestDeterministicFunctionAdapter:
    @pytest.mark.asyncio
    async def test_invoke_sync_handler(self) -> None:
        def _add(a: int = 0, b: int = 0) -> int:
            return a + b

        adapter = DeterministicFunctionAdapter(
            tool_id="add_func",
            name="Add Function",
            description="Adds two numbers",
            handler=_add,
        )
        result = await adapter.invoke({"a": 3, "b": 4})
        assert result.success is True
        assert result.output == 7
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_invoke_handler_error(self) -> None:
        def _bad(**kwargs: Any) -> None:
            raise TypeError("type error")

        adapter = DeterministicFunctionAdapter(
            tool_id="bad_func",
            name="Bad Function",
            description="Failing function",
            handler=_bad,
        )
        result = await adapter.invoke({})
        assert result.success is False
        assert "type error" in result.error  # type: ignore[operator]


# ===========================================================================
# Class 7: TestSkillDefinitionToolPreference
# ===========================================================================


class TestSkillDefinitionToolPreference:
    def test_skill_definition_preferred_tools_default(self) -> None:
        from probos.skill_framework import SkillDefinition

        d = SkillDefinition(skill_id="test", name="Test", category="pcc")
        assert d.preferred_tools == []

    def test_skill_definition_with_preferences(self) -> None:
        from probos.skill_framework import SkillDefinition

        prefs = [
            ToolPreference(tool_id="codebase_query", priority=0, context="primary"),
            ToolPreference(tool_id="knowledge_query", priority=1, context="fallback"),
        ]
        d = SkillDefinition(
            skill_id="test2",
            name="Test2",
            category="pcc",
            preferred_tools=prefs,
        )
        assert len(d.preferred_tools) == 2
        assert d.preferred_tools[0].tool_id == "codebase_query"
        assert d.preferred_tools[1].priority == 1
