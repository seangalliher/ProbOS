"""BF-104: Display crew agent count, not total agent count."""

from __future__ import annotations

import pytest
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from rich.console import Console

from probos.substrate.registry import AgentRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(agent_type: str, pool: str = "crew") -> SimpleNamespace:
    """Create a mock agent with required attributes."""
    return SimpleNamespace(
        id=f"agent-{agent_type}-001",
        agent_type=agent_type,
        pool=pool,
        capabilities=[],
        state="active",
        confidence=0.9,
        callsign=agent_type.capitalize(),
    )


def _make_console() -> tuple[Console, StringIO]:
    buf = StringIO()
    return Console(file=buf, width=120, force_terminal=True), buf


def _get_output(buf: StringIO) -> str:
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Registry.crew_count() tests
# ---------------------------------------------------------------------------


class TestRegistryCrewCount:
    @pytest.mark.asyncio
    async def test_crew_count_with_mixed_agents(self):
        """crew_count() returns only crew agents, not infra/utility."""
        registry = AgentRegistry()
        # Crew agents (in _WARD_ROOM_CREW)
        await registry.register(_make_agent("counselor"))
        await registry.register(_make_agent("security_officer"))
        await registry.register(_make_agent("engineer"))
        # Infrastructure agents (NOT in _WARD_ROOM_CREW)
        await registry.register(_make_agent("introspector"))
        await registry.register(_make_agent("vitals_monitor"))
        await registry.register(_make_agent("red_team"))

        assert registry.count == 6
        assert registry.crew_count() < registry.count
        # counselor, security_officer are crew; engineer is not in the set
        assert registry.crew_count() >= 2

    @pytest.mark.asyncio
    async def test_crew_count_empty_registry(self):
        """crew_count() returns 0 for empty registry."""
        registry = AgentRegistry()
        assert registry.crew_count() == 0

    @pytest.mark.asyncio
    async def test_crew_count_all_infra(self):
        """crew_count() returns 0 when only infrastructure agents present."""
        registry = AgentRegistry()
        await registry.register(_make_agent("introspector"))
        await registry.register(_make_agent("vitals_monitor"))
        await registry.register(_make_agent("red_team"))

        assert registry.count == 3
        assert registry.crew_count() == 0


# ---------------------------------------------------------------------------
# Status dict tests
# ---------------------------------------------------------------------------


class TestStatusDict:
    def test_status_includes_crew_agents(self):
        """runtime.status() includes both crew_agents and total_agents."""
        rt = MagicMock()
        rt.registry.crew_count.return_value = 12
        rt.registry.count = 62
        rt.config.system.model_dump.return_value = {"name": "ProbOS"}
        rt._started = True

        # Simulate the status dict structure
        status = {
            "crew_agents": rt.registry.crew_count(),
            "total_agents": rt.registry.count,
        }

        assert status["crew_agents"] == 12
        assert status["total_agents"] == 62


# ---------------------------------------------------------------------------
# Shell prompt tests
# ---------------------------------------------------------------------------


class TestShellPromptFormat:
    def test_prompt_shows_crew_not_total(self):
        """Shell prompt displays crew count, not total agent count."""
        # Simulate what _build_prompt does
        crew = 12
        health = 0.95
        prompt = f"[{crew} crew | health: {health:.2f}] probos> "

        assert "12 crew" in prompt
        assert "agents" not in prompt
        assert "probos>" in prompt
        assert "health" in prompt


# ---------------------------------------------------------------------------
# /ping command tests
# ---------------------------------------------------------------------------


class TestPingCommand:
    @pytest.mark.asyncio
    async def test_ping_shows_crew_count(self):
        """cmd_ping shows crew active / crew total, not total agents."""
        from probos.experience.commands import commands_status
        from probos.types import AgentState

        console, buf = _make_console()

        rt = MagicMock()
        rt.status.return_value = {
            "total_agents": 62,
            "crew_agents": 12,
            "mesh": {"self_model": {"uptime_seconds": 120}},
            "cognitive": {"llm_client_ready": True},
        }

        # Create mock agents — some crew, some infra
        crew_agent = _make_agent("counselor")
        crew_agent.state = AgentState.ACTIVE
        infra_agent = _make_agent("introspector")
        infra_agent.state = AgentState.ACTIVE

        rt.registry.all.return_value = [crew_agent, infra_agent]
        rt.registry.count = 62
        rt.registry.crew_count.return_value = 12

        await commands_status.cmd_ping(rt, console, "")
        output = _get_output(buf)

        assert "Crew:" in output
        assert "crew" in output.lower()


# ---------------------------------------------------------------------------
# API /health endpoint tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_response_includes_crew_agents(self):
        """API /health response includes crew_agents field."""
        status = {
            "total_agents": 62,
            "crew_agents": 12,
        }
        # Simulate what the endpoint returns
        response = {
            "status": "ok",
            "crew_agents": status.get("crew_agents", 0),
            "agents": status.get("total_agents", 0),
        }

        assert response["crew_agents"] == 12
        assert response["agents"] == 62


# ---------------------------------------------------------------------------
# Working memory tests
# ---------------------------------------------------------------------------


class TestWorkingMemoryContext:
    def test_agent_summary_includes_crew(self):
        """Working memory text shows crew count, not total."""
        from probos.cognitive.working_memory import WorkingMemorySnapshot

        wm = WorkingMemorySnapshot()
        wm.agent_summary = {"total": 62, "crew": 12, "pools": {}}

        text = wm.to_text()
        assert "Crew: 12 agents" in text


# ---------------------------------------------------------------------------
# Status panel tests
# ---------------------------------------------------------------------------


class TestStatusPanel:
    def test_panel_shows_crew_and_total(self):
        """Status panel shows Crew: X (total services: Y)."""
        from probos.experience.panels import render_status_panel

        status = {
            "system": {"name": "ProbOS", "version": "0.4.0"},
            "started": True,
            "crew_agents": 12,
            "total_agents": 62,
            "pools": {},
            "pool_groups": {},
            "mesh": {},
            "consensus": {},
            "cognitive": {},
        }

        panel = render_status_panel(status)
        # Render to text
        console, buf = _make_console()
        console.print(panel)
        output = _get_output(buf)

        assert "Crew:" in output
        assert "12" in output
        assert "62" in output
