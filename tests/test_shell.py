"""Tests for ProbOS shell functionality."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from rich.console import Console

from probos.experience.shell import ProbOSShell


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
            renderer=Mock()
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
        mock_console.print.assert_called_once_with(
            "[green]●[/green] ProbOS uptime: 2 hours, 2 minutes, 3 seconds"
        )

    @pytest.mark.asyncio
    async def test_cmd_ping_no_uptime_data(self, shell, mock_runtime, mock_console):
        """Test ping command when uptime data is unavailable."""
        mock_runtime.status.return_value = {
            "system": {"name": "ProbOS", "version": "1.0.0"},
            "started": True,
            "mesh": {}  # No self_model data
        }
        
        await shell._cmd_ping("")
        
        mock_runtime.status.assert_called_once()
        mock_console.print.assert_called_once_with(
            "[yellow]⚠[/yellow] Uptime information unavailable"
        )

    @pytest.mark.asyncio
    async def test_cmd_ping_no_mesh_data(self, shell, mock_runtime, mock_console):
        """Test ping command when mesh data is completely missing."""
        mock_runtime.status.return_value = {
            "system": {"name": "ProbOS", "version": "1.0.0"},
            "started": True,
            # No mesh key at all
        }
        
        await shell._cmd_ping("")
        
        mock_runtime.status.assert_called_once()
        mock_console.print.assert_called_once_with(
            "[yellow]⚠[/yellow] Uptime information unavailable"
        )

    @pytest.mark.asyncio
    async def test_ping_command_in_dispatch(self, shell):
        """Test that ping command is properly registered in command dispatch."""
        # Check that ping is in COMMANDS dictionary
        assert "/ping" in shell.COMMANDS
        assert shell.COMMANDS["/ping"] == "Show system uptime"
        
        # Verify the command handler exists
        assert hasattr(shell, "_cmd_ping")
        assert callable(getattr(shell, "_cmd_ping"))

    def test_ping_command_help_text(self, shell):
        """Test that ping command has correct help text."""
        assert "/ping" in shell.COMMANDS
        assert shell.COMMANDS["/ping"] == "Show system uptime"
