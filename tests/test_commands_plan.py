"""Tests for commands_plan module (AD-519)."""
from __future__ import annotations

import pytest
from io import StringIO
from unittest.mock import AsyncMock, MagicMock

from rich.console import Console

from probos.experience.commands import commands_plan


@pytest.fixture
def console():
    return Console(file=StringIO(), force_terminal=True, width=120)


def get_output(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


@pytest.fixture
def mock_runtime():
    rt = MagicMock()
    rt._pending_proposal = None
    rt._last_execution = None
    rt._last_feedback_applied = False
    rt._correction_detector = None
    rt.self_mod_pipeline = None
    rt.self_mod_manager = None
    rt._agent_patcher = None
    rt.reject_proposal = AsyncMock(return_value=True)
    return rt


@pytest.fixture
def mock_renderer():
    rnd = MagicMock()
    rnd.debug = False
    rnd._current_dag = None
    rnd._node_statuses = {}
    rnd._status = None
    return rnd


class TestCommandsPlan:
    @pytest.mark.asyncio
    async def test_plan_no_args_no_pending(self, console, mock_runtime, mock_renderer):
        await commands_plan.cmd_plan(mock_runtime, console, mock_renderer, "")
        output = get_output(console)
        assert "Usage" in output or "plan" in output.lower()

    @pytest.mark.asyncio
    async def test_approve_no_pending(self, console, mock_runtime, mock_renderer):
        await commands_plan.cmd_approve(mock_runtime, console, mock_renderer, "")
        output = get_output(console)
        assert "No pending proposal" in output

    @pytest.mark.asyncio
    async def test_reject_no_pending(self, console, mock_runtime, mock_renderer):
        mock_runtime.reject_proposal = AsyncMock(return_value=False)
        await commands_plan.cmd_reject(mock_runtime, console, "")
        output = get_output(console)
        assert "No pending proposal" in output

    @pytest.mark.asyncio
    async def test_reject_success(self, console, mock_runtime, mock_renderer):
        await commands_plan.cmd_reject(mock_runtime, console, "")
        output = get_output(console)
        assert "discarded" in output.lower()

    @pytest.mark.asyncio
    async def test_feedback_invalid(self, console, mock_runtime):
        await commands_plan.cmd_feedback(mock_runtime, console, "maybe")
        output = get_output(console)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_feedback_no_execution(self, console, mock_runtime):
        await commands_plan.cmd_feedback(mock_runtime, console, "good")
        output = get_output(console)
        assert "No recent execution" in output

    @pytest.mark.asyncio
    async def test_correct_no_args(self, console, mock_runtime):
        await commands_plan.cmd_correct(mock_runtime, console, "")
        output = get_output(console)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_correct_no_execution(self, console, mock_runtime):
        await commands_plan.cmd_correct(mock_runtime, console, "fix it")
        output = get_output(console)
        assert "No recent execution" in output
