"""Tests for ProbOS shell functionality."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import pytest
from rich.console import Console

from probos.experience.shell import ProbOSShell
from probos.types import AgentState


class TestProbOSShell:
    """Test suite for ProbOSShell."""

    @pytest.fixture
    def mock_runtime(self):
        """Mock ProbOSRuntime for testing."""
        runtime = Mock()
        runtime.status = Mock(return_value={
            "system": {"name": "ProbOS", "version": "1.0.0"},
            "started": True,
            "total_agents": 5,
            "mesh": {
                "self_model": {
                    "uptime_seconds": 7323.5  # 2 hours, 2 minutes, 3 seconds
                }
            }
        })

        # Mock registry with active agents
        agent1 = Mock()
        agent1.state = AgentState.ACTIVE
        agent1.confidence = 0.9
        agent2 = Mock()
        agent2.state = AgentState.ACTIVE
        agent2.confidence = 0.8
        runtime.registry.all.return_value = [agent1, agent2]
        type(runtime.registry).count = PropertyMock(return_value=2)

        # No escalation_manager or self_mod_pipeline
        runtime.escalation_manager = None
        runtime.self_mod_pipeline = None

        return runtime

    @pytest.fixture
    def mock_console(self):
        """Mock Rich Console for testing."""
        return Mock(spec=Console)

    @pytest.fixture
    def shell(self, mock_runtime, mock_console):
        """Create a test shell instance."""
        return ProbOSShell(
            runtime=mock_runtime,
            console=mock_console,
        )

    def test_format_uptime_seconds_only(self, shell):
        """Test uptime formatting for less than a minute."""
        result = shell._format_uptime(45.7)
        assert result == "45 seconds"

    def test_format_uptime_minutes_and_seconds(self, shell):
        """Test uptime formatting for minutes and seconds."""
        result = shell._format_uptime(135.3)  # 2 minutes, 15 seconds
        assert result == "2 minutes, 15 seconds"

    def test_format_uptime_hours_minutes_seconds(self, shell):
        """Test uptime formatting for hours, minutes, and seconds."""
        result = shell._format_uptime(7323.0)  # 2 hours, 2 minutes, 3 seconds
        assert result == "2 hours, 2 minutes, 3 seconds"

    def test_format_uptime_days_hours_minutes(self, shell):
        """Test uptime formatting for days, hours, and minutes."""
        result = shell._format_uptime(180123.0)  # 2 days, 2 hours, 2 minutes, 3 seconds
        assert result == "2 days, 2 hours, 2 minutes"

    def test_format_uptime_exactly_one_hour(self, shell):
        """Test uptime formatting for exactly one hour."""
        result = shell._format_uptime(3600.0)
        assert result == "1 hours, 0 minutes, 0 seconds"

    def test_format_uptime_exactly_one_day(self, shell):
        """Test uptime formatting for exactly one day."""
        result = shell._format_uptime(86400.0)
        assert result == "1 days, 0 hours, 0 minutes"

    @pytest.mark.asyncio
    async def test_cmd_ping_success(self, shell, mock_runtime, mock_console):
        """Test successful ping command execution."""
        await shell._cmd_ping("")

        mock_runtime.status.assert_called_once()
        # Builder changed /ping to print multiple lines: status, uptime, agents
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("System Status: ACTIVE" in c for c in calls)
        assert any("Uptime: 2 hours, 2 minutes, 3 seconds" in c for c in calls)
        assert any("Agents:" in c for c in calls)

    @pytest.mark.asyncio
    async def test_cmd_ping_no_uptime_data(self, shell, mock_runtime, mock_console):
        """Test ping command when uptime data is unavailable."""
        mock_runtime.status.return_value = {
            "system": {"name": "ProbOS", "version": "1.0.0"},
            "started": True,
            "total_agents": 0,
            "mesh": {}  # No self_model data
        }

        await shell._cmd_ping("")

        mock_runtime.status.assert_called_once()
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("UNKNOWN" in c for c in calls)
        assert any("unavailable" in c for c in calls)

    @pytest.mark.asyncio
    async def test_cmd_ping_no_mesh_data(self, shell, mock_runtime, mock_console):
        """Test ping command when mesh data is completely missing."""
        mock_runtime.status.return_value = {
            "system": {"name": "ProbOS", "version": "1.0.0"},
            "started": True,
            "total_agents": 0,
            # No mesh key at all
        }

        await shell._cmd_ping("")

        mock_runtime.status.assert_called_once()
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("UNKNOWN" in c for c in calls)
        assert any("unavailable" in c for c in calls)

    @pytest.mark.asyncio
    async def test_ping_command_in_dispatch(self, shell):
        """Test that ping command is properly registered in command dispatch."""
        assert "/ping" in shell.COMMANDS
        assert shell.COMMANDS["/ping"] == "Show system uptime"
        assert hasattr(shell, "_cmd_ping")
        assert callable(getattr(shell, "_cmd_ping"))

    def test_ping_command_help_text(self, shell):
        """Test that ping command has correct help text."""
        assert "/ping" in shell.COMMANDS
        assert shell.COMMANDS["/ping"] == "Show system uptime"

    def test_orders_command_registered(self, shell):
        """Test that /orders command is registered in COMMANDS."""
        assert "/orders" in shell.COMMANDS
        assert shell.COMMANDS["/orders"] == "Show Standing Orders hierarchy and summaries"
        assert hasattr(shell, "_cmd_orders")
        assert callable(getattr(shell, "_cmd_orders"))

    @pytest.mark.asyncio
    async def test_cmd_orders_no_directory(self, shell, mock_console):
        """Test /orders when standing orders directory does not exist."""
        with patch("probos.cognitive.standing_orders._DEFAULT_ORDERS_DIR", "/nonexistent/path"):
            await shell._cmd_orders("")

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("No standing orders directory found" in c for c in calls)

    @pytest.mark.asyncio
    async def test_cmd_orders_empty_directory(self, shell, mock_console):
        """Test /orders when directory exists but has no .md files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("probos.cognitive.standing_orders._DEFAULT_ORDERS_DIR", tmpdir):
                await shell._cmd_orders("")

        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("No standing orders configured" in c for c in calls)

    @pytest.mark.asyncio
    async def test_cmd_orders_shows_files(self, shell, mock_console):
        """Test /orders displays standing orders files in a table."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "federation.md").write_text("# Federation\nUniversal principles.", encoding="utf-8")
            (tmppath / "ship.md").write_text("# Ship\nInstance config.", encoding="utf-8")
            (tmppath / "engineering.md").write_text("# Engineering\nBuild standards.", encoding="utf-8")

            with patch("probos.cognitive.standing_orders._DEFAULT_ORDERS_DIR", tmpdir):
                await shell._cmd_orders("")

        # Should have printed a Table object
        assert mock_console.print.called
