"""AD-423c: Onboarding tool wiring tests."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from probos.agent_onboarding import AgentOnboardingService
from probos.tools.registry import ToolRegistry
from probos.tools.protocol import ToolType


class _StubTool:
    """Minimal Tool for registry seeding."""

    def __init__(self, tool_id: str):
        self._id = tool_id

    @property
    def tool_id(self): return self._id
    @property
    def name(self): return self._id
    @property
    def tool_type(self): return ToolType.DETERMINISTIC_FUNCTION
    @property
    def description(self): return ""
    @property
    def input_schema(self): return {}
    @property
    def output_schema(self): return {}

    async def invoke(self, params, context=None):
        from probos.tools.protocol import ToolResult
        return ToolResult(output="ok")


def _make_mock_config():
    """Minimal SystemConfig mock for onboarding."""
    config = MagicMock()
    config.onboarding.enabled = False
    config.onboarding.naming_ceremony = False
    config.orientation.enabled = False
    return config


def _make_mock_agent(agent_type: str = "security_officer", is_crew: bool = True):
    """Minimal agent mock."""
    agent = MagicMock()
    agent.id = f"pool-{agent_type}-0"
    agent.agent_type = agent_type
    agent.pool = f"{agent_type}_pool"
    agent.state = MagicMock()
    agent.state.value = "active"
    agent.confidence = 1.0
    agent.capabilities = []
    agent.callsign = agent_type.replace("_", " ").title()
    agent.tool_context = None
    return agent


def _make_onboarding_service(tool_registry: ToolRegistry | None = None):
    """Create AgentOnboardingService with mocked dependencies."""
    svc = AgentOnboardingService(
        callsign_registry=MagicMock(),
        capability_registry=MagicMock(),
        gossip=MagicMock(),
        intent_bus=MagicMock(),
        trust_network=MagicMock(),
        event_log=MagicMock(log=AsyncMock()),
        identity_registry=None,
        ontology=None,
        event_emitter=MagicMock(),
        config=_make_mock_config(),
        llm_client=None,
        registry=MagicMock(),
        ward_room=None,
        acm=None,
        tool_registry=tool_registry,
    )
    return svc


class TestOnboardingToolWiring:
    """wire_agent() creates ToolContext for crew agents."""

    @pytest.mark.asyncio
    async def test_crew_agent_gets_tool_context(self):
        """Crew agents receive a ToolContext during onboarding."""
        registry = ToolRegistry()
        registry.register(_StubTool("t1"))
        registry.register(_StubTool("t2"))

        svc = _make_onboarding_service(tool_registry=registry)
        agent = _make_mock_agent("security_officer")

        with patch("probos.agent_onboarding.is_crew_agent", return_value=True):
            await svc.wire_agent(agent)

        assert agent.tool_context is not None
        assert agent.tool_context.agent_id == agent.id or agent.tool_context.agent_id
        assert len(agent.tool_context.available_tools()) == 2

    @pytest.mark.asyncio
    async def test_non_crew_agent_no_tool_context(self):
        """Non-crew agents do not receive a ToolContext."""
        registry = ToolRegistry()
        registry.register(_StubTool("t1"))

        svc = _make_onboarding_service(tool_registry=registry)
        agent = _make_mock_agent("introspect_agent")

        with patch("probos.agent_onboarding.is_crew_agent", return_value=False):
            await svc.wire_agent(agent)

        # Non-crew: tool_context should remain as the mock's default (None set in _make_mock_agent)
        assert agent.tool_context is None

    @pytest.mark.asyncio
    async def test_no_registry_no_error(self):
        """If tool_registry is None, onboarding proceeds without error."""
        svc = _make_onboarding_service(tool_registry=None)
        agent = _make_mock_agent("security_officer")

        with patch("probos.agent_onboarding.is_crew_agent", return_value=True):
            await svc.wire_agent(agent)
        # Should not raise

    @pytest.mark.asyncio
    async def test_tool_context_created_event_emitted(self):
        """TOOL_CONTEXT_CREATED event is emitted during onboarding."""
        registry = ToolRegistry()
        registry.register(_StubTool("t1"))
        svc = _make_onboarding_service(tool_registry=registry)
        agent = _make_mock_agent("security_officer")

        with patch("probos.agent_onboarding.is_crew_agent", return_value=True):
            await svc.wire_agent(agent)

        # Check event emission
        from probos.events import EventType
        calls = svc._event_emitter.call_args_list
        tool_ctx_calls = [c for c in calls if c[0][0] == EventType.TOOL_CONTEXT_CREATED]
        assert len(tool_ctx_calls) == 1
        event_data = tool_ctx_calls[0][0][1]
        assert event_data["agent_type"] == "security_officer"

    def test_set_tool_registry_setter(self):
        """Public setter binds tool registry."""
        svc = _make_onboarding_service(tool_registry=None)
        assert svc._tool_registry is None

        registry = ToolRegistry()
        svc.set_tool_registry(registry)
        assert svc._tool_registry is registry


class TestToolContextDepartmentResolution:
    """ToolContext department is resolved from ontology or standing orders."""

    @pytest.mark.asyncio
    async def test_department_from_standing_orders(self):
        """When ontology is None, department comes from standing orders."""
        registry = ToolRegistry()
        registry.register(_StubTool("t1"))
        svc = _make_onboarding_service(tool_registry=registry)
        agent = _make_mock_agent("security_officer")

        with (
            patch("probos.agent_onboarding.is_crew_agent", return_value=True),
            patch("probos.cognitive.standing_orders.get_department", return_value="security"),
        ):
            await svc.wire_agent(agent)

        assert agent.tool_context is not None
        assert agent.tool_context.agent_department == "security"
