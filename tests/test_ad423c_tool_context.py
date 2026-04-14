"""AD-423c: ToolContext tests."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from probos.tools.context import ToolContext
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry, ToolPermissionDenied


# ── Helpers ──────────────────────────────────────────────────────────

class _StubTool:
    """Minimal Tool protocol implementation for testing."""

    def __init__(self, tool_id: str = "test_tool", name: str = "Test Tool",
                 tool_type: ToolType = ToolType.DETERMINISTIC_FUNCTION):
        self._tool_id = tool_id
        self._name = name
        self._tool_type = tool_type

    @property
    def tool_id(self) -> str: return self._tool_id
    @property
    def name(self) -> str: return self._name
    @property
    def tool_type(self) -> ToolType: return self._tool_type
    @property
    def description(self) -> str: return "A test tool"
    @property
    def input_schema(self) -> dict: return {}
    @property
    def output_schema(self) -> dict: return {}

    async def invoke(self, params, context=None):
        return ToolResult(output={"echo": params})


def _make_registry_with_tools(*tool_ids: str) -> ToolRegistry:
    """Create a ToolRegistry and register stub tools."""
    registry = ToolRegistry()
    for tid in tool_ids:
        tool = _StubTool(tool_id=tid, name=f"Tool {tid}")
        registry.register(tool)
    return registry


def _make_context(
    registry: ToolRegistry,
    agent_id: str = "agent-001",
    rank: str = "ensign",
    department: str | None = None,
    agent_types: list[str] | None = None,
) -> ToolContext:
    """Create a ToolContext bound to a registry."""
    ctx = ToolContext(
        agent_id=agent_id,
        agent_rank=rank,
        agent_department=department,
        agent_types=agent_types or [],
    )
    ctx.set_registry(registry)
    return ctx


# ── Tests: Construction ─────────────────────────────────────────────

class TestToolContextConstruction:
    """ToolContext creation and binding."""

    def test_create_unbound(self):
        ctx = ToolContext(agent_id="agent-001")
        assert ctx.agent_id == "agent-001"
        assert ctx.agent_rank == "ensign"
        assert ctx._registry is None

    def test_unbound_raises_on_use(self):
        ctx = ToolContext(agent_id="agent-001")
        with pytest.raises(RuntimeError, match="not bound"):
            ctx.available_tools()

    def test_bind_registry(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry)
        assert ctx._registry is registry

    def test_to_dict(self):
        registry = _make_registry_with_tools("t1", "t2")
        ctx = _make_context(registry, rank="lieutenant", department="science")
        d = ctx.to_dict()
        assert d["agent_id"] == "agent-001"
        assert d["agent_rank"] == "lieutenant"
        assert d["agent_department"] == "science"
        assert d["tool_count"] == 2


# ── Tests: Tool Visibility ──────────────────────────────────────────

class TestToolContextVisibility:
    """available_tools() and has_tool() permission filtering."""

    def test_all_tools_visible_default_permissions(self):
        """With no permission matrix, all enabled tools return READ → visible."""
        registry = _make_registry_with_tools("t1", "t2", "t3")
        ctx = _make_context(registry)
        tools = ctx.available_tools()
        assert len(tools) == 3

    def test_has_tool_true(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry)
        assert ctx.has_tool("t1") is True

    def test_has_tool_false_nonexistent(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry)
        assert ctx.has_tool("nonexistent") is False

    def test_department_scoping_hides_tools(self):
        """Tools scoped to a department are invisible to other departments."""
        registry = ToolRegistry()
        tool = _StubTool(tool_id="eng_only")
        registry.register(tool, department="engineering")

        ctx = _make_context(registry, department="science")
        assert ctx.has_tool("eng_only") is False
        assert len(ctx.available_tools()) == 0

    def test_department_scoping_shows_matching(self):
        """Tools scoped to a department are visible to that department."""
        registry = ToolRegistry()
        tool = _StubTool(tool_id="eng_only")
        registry.register(tool, department="engineering")

        ctx = _make_context(registry, department="engineering")
        assert ctx.has_tool("eng_only") is True

    def test_restricted_to_hides_from_others(self):
        """restricted_to limits visibility to specific agents."""
        registry = ToolRegistry()
        tool = _StubTool(tool_id="special")
        registry.register(tool, restricted_to=["agent-vip"])

        ctx = _make_context(registry, agent_id="agent-001")
        assert ctx.has_tool("special") is False

    def test_restricted_to_shows_for_listed(self):
        registry = ToolRegistry()
        tool = _StubTool(tool_id="special")
        registry.register(tool, restricted_to=["agent-001"])

        ctx = _make_context(registry, agent_id="agent-001")
        assert ctx.has_tool("special") is True

    def test_get_permission(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry)
        perm = ctx.get_permission("t1")
        assert perm == ToolPermission.READ  # default: READ for all ranks

    def test_filter_by_tool_type(self):
        registry = ToolRegistry()
        registry.register(_StubTool("fn1", tool_type=ToolType.DETERMINISTIC_FUNCTION))
        registry.register(_StubTool("svc1", tool_type=ToolType.INFRA_SERVICE))
        ctx = _make_context(registry)
        fns = ctx.available_tools(tool_type=ToolType.DETERMINISTIC_FUNCTION)
        assert len(fns) == 1
        assert fns[0].tool_id == "fn1"


# ── Tests: Invocation ────────────────────────────────────────────────

class TestToolContextInvocation:
    """invoke() delegates to registry with permission checks."""

    @pytest.mark.asyncio
    async def test_invoke_success(self):
        registry = _make_registry_with_tools("echo")
        ctx = _make_context(registry)
        result = await ctx.invoke("echo", {"msg": "hello"})
        assert result.success
        assert result.output == {"echo": {"msg": "hello"}}

    @pytest.mark.asyncio
    async def test_invoke_not_found(self):
        """Nonexistent tool resolves to NONE permission → ToolPermissionDenied."""
        registry = _make_registry_with_tools("echo")
        ctx = _make_context(registry)
        with pytest.raises(ToolPermissionDenied):
            await ctx.invoke("nonexistent", {})

    @pytest.mark.asyncio
    async def test_invoke_permission_denied(self):
        """Agent with NONE permission cannot invoke."""
        registry = ToolRegistry()
        tool = _StubTool("restricted")
        registry.register(tool, department="security")

        ctx = _make_context(registry, department="medical")
        # Permission is NONE (department mismatch) → ToolPermissionDenied
        with pytest.raises(ToolPermissionDenied):
            await ctx.invoke("restricted", {})

    @pytest.mark.asyncio
    async def test_invoke_passes_context(self):
        """Invocation context includes agent identity."""
        captured = {}

        class _CaptureTool:
            @property
            def tool_id(self): return "cap"
            @property
            def name(self): return "Capture"
            @property
            def tool_type(self): return ToolType.DETERMINISTIC_FUNCTION
            @property
            def description(self): return ""
            @property
            def input_schema(self): return {}
            @property
            def output_schema(self): return {}
            async def invoke(self, params, context=None):
                captured.update(context or {})
                return ToolResult(output="ok")

        registry = ToolRegistry()
        registry.register(_CaptureTool())
        ctx = _make_context(registry, department="science", rank="lieutenant")
        await ctx.invoke("cap", {})
        assert captured["agent_id"] == "agent-001"
        assert captured["agent_department"] == "science"
        assert captured["agent_rank"] == "lieutenant"
        assert captured["permission"] == "read"

    @pytest.mark.asyncio
    async def test_invoke_empty_params_default(self):
        """Calling invoke with no params passes empty dict."""
        registry = _make_registry_with_tools("echo")
        ctx = _make_context(registry)
        result = await ctx.invoke("echo")
        assert result.success


# ── Tests: Refresh ───────────────────────────────────────────────────

class TestToolContextRefresh:
    """Identity snapshot refresh on rank change."""

    def test_refresh_rank(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry, rank="ensign")
        assert ctx.agent_rank == "ensign"
        ctx.refresh(agent_rank="commander")
        assert ctx.agent_rank == "commander"

    def test_refresh_department(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry, department="science")
        ctx.refresh(agent_department="engineering")
        assert ctx.agent_department == "engineering"

    def test_refresh_preserves_registry_binding(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry)
        ctx.refresh(agent_rank="commander")
        assert ctx._registry is registry
        assert ctx.has_tool("t1") is True
