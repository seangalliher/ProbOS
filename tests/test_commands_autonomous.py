"""Tests for commands_autonomous module (AD-519)."""
from __future__ import annotations

import pytest
from io import StringIO
from unittest.mock import MagicMock

from rich.console import Console

from probos.experience.commands import commands_autonomous
from probos.runtime import ProbOSRuntime


@pytest.fixture
def console():
    return Console(file=StringIO(), force_terminal=True, width=120)


def get_output(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


@pytest.fixture
def mock_runtime():
    rt = MagicMock(spec=ProbOSRuntime)
    rt.conn_manager = None
    rt._night_orders_mgr = None
    rt.watch_manager = None
    return rt


class TestCommandsAutonomous:
    @pytest.mark.asyncio
    async def test_cmd_conn_no_manager(self, console, mock_runtime):
        await commands_autonomous.cmd_conn(mock_runtime, console, "")
        output = get_output(console)
        assert "not initialized" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_conn_status(self, console, mock_runtime):
        mgr = MagicMock()
        mgr.get_status.return_value = {"active": False}
        mock_runtime.conn_manager = mgr
        await commands_autonomous.cmd_conn(mock_runtime, console, "status")
        output = get_output(console)
        assert "Captain" in output or "conn" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_conn_return_no_active(self, console, mock_runtime):
        mgr = MagicMock()
        mgr.is_active = False
        mock_runtime.conn_manager = mgr
        await commands_autonomous.cmd_conn(mock_runtime, console, "return")
        output = get_output(console)
        assert "No active conn" in output

    @pytest.mark.asyncio
    async def test_cmd_night_orders_no_manager(self, console, mock_runtime):
        await commands_autonomous.cmd_night_orders(mock_runtime, console, "")
        output = get_output(console)
        assert "not initialized" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_night_orders_status(self, console, mock_runtime):
        mgr = MagicMock()
        mgr.get_status.return_value = {"active": False}
        mock_runtime._night_orders_mgr = mgr
        await commands_autonomous.cmd_night_orders(mock_runtime, console, "status")
        output = get_output(console)
        assert "No active" in output

    @pytest.mark.asyncio
    async def test_cmd_watch_no_manager(self, console, mock_runtime):
        await commands_autonomous.cmd_watch(mock_runtime, console, "")
        output = get_output(console)
        assert "not initialized" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_watch_shows_status(self, console, mock_runtime):
        mgr = MagicMock()
        mgr.get_watch_status.return_value = {
            "current_watch": "morning",
            "time_appropriate_watch": "morning",
            "on_duty": ["a1"],
            "standing_tasks_count": 0,
            "active_orders_count": 0,
            "roster": {"morning": ["a1"], "afternoon": []},
        }
        mock_runtime.watch_manager = mgr
        await commands_autonomous.cmd_watch(mock_runtime, console, "")
        output = get_output(console)
        assert "MORNING" in output
