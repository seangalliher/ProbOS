"""Tests for commands_status module (AD-519)."""
from __future__ import annotations

import pytest
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

from rich.console import Console

from probos.experience.commands import commands_status


@pytest.fixture
def console():
    return Console(file=StringIO(), force_terminal=True, width=120)


def get_output(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


@pytest.fixture
def mock_runtime():
    rt = MagicMock()
    rt.status.return_value = {
        "total_agents": 3,
        "mesh": {"self_model": {"uptime_seconds": 120}},
        "cognitive": {"llm_client_ready": True},
    }
    rt.episodic_memory = None
    rt.registry.all.return_value = []
    rt.registry.count = 3
    rt.trust_network.all_scores.return_value = {}
    rt.pools = {}
    rt.pool_groups = {}
    rt.callsign_registry = MagicMock()
    rt.pool_scaler = None
    rt.federation_bridge = None
    rt.credential_store = None
    return rt


class TestCommandsStatus:
    @pytest.mark.asyncio
    async def test_cmd_status(self, console, mock_runtime):
        with patch("probos.experience.panels.render_status_panel", return_value="STATUS"):
            await commands_status.cmd_status(mock_runtime, console, "")
        output = get_output(console)
        assert "STATUS" in output

    @pytest.mark.asyncio
    async def test_cmd_agents(self, console, mock_runtime):
        with patch("probos.experience.panels.render_agent_roster", return_value="AGENTS"):
            await commands_status.cmd_agents(mock_runtime, console, "")
        output = get_output(console)
        assert "AGENTS" in output

    @pytest.mark.asyncio
    async def test_cmd_ping(self, console, mock_runtime):
        await commands_status.cmd_ping(mock_runtime, console, "")
        output = get_output(console)
        assert "ACTIVE" in output or "Uptime" in output

    @pytest.mark.asyncio
    async def test_cmd_scaling_disabled(self, console, mock_runtime):
        await commands_status.cmd_scaling(mock_runtime, console, "")
        output = get_output(console)
        assert "disabled" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_federation_disabled(self, console, mock_runtime):
        await commands_status.cmd_federation(mock_runtime, console, "")
        output = get_output(console)
        assert "not enabled" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_peers_disabled(self, console, mock_runtime):
        await commands_status.cmd_peers(mock_runtime, console, "")
        output = get_output(console)
        assert "not enabled" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_credentials_unavailable(self, console, mock_runtime):
        await commands_status.cmd_credentials(mock_runtime, console, "")
        output = get_output(console)
        assert "not available" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_debug_toggle(self, console, mock_runtime):
        shell = MagicMock()
        shell.debug = False
        shell.renderer = MagicMock()
        await commands_status.cmd_debug(mock_runtime, console, "on", shell=shell)
        assert shell.debug is True

    @pytest.mark.asyncio
    async def test_cmd_help(self, console):
        commands_dict = {"/test": "A test command"}
        await commands_status.cmd_help(console, commands_dict)
        output = get_output(console)
        assert "test" in output.lower()


class TestFormatUptime:
    def test_seconds(self):
        assert commands_status.format_uptime(30) == "30 seconds"

    def test_minutes(self):
        result = commands_status.format_uptime(90)
        assert "1 minutes" in result

    def test_hours(self):
        result = commands_status.format_uptime(3700)
        assert "1 hours" in result

    def test_days(self):
        result = commands_status.format_uptime(90000)
        assert "1 days" in result
