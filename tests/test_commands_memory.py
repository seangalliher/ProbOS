"""Tests for commands_memory module (AD-519)."""
from __future__ import annotations

import pytest
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

from rich.console import Console

from probos.experience.commands import commands_memory
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
    rt.episodic_memory = None
    rt.dream_scheduler = None
    rt.registry = MagicMock()
    rt.trust_network = MagicMock()
    rt.hebbian_router = MagicMock()
    rt.working_memory = MagicMock()
    rt.working_memory.assemble.return_value = {}
    return rt


class TestCommandsMemory:
    @pytest.mark.asyncio
    async def test_cmd_memory(self, console, mock_runtime):
        with patch("probos.experience.panels.render_working_memory_panel", return_value="MEMORY"):
            await commands_memory.cmd_memory(mock_runtime, console, "")
        output = get_output(console)
        assert "MEMORY" in output

    @pytest.mark.asyncio
    async def test_cmd_history_no_episodic(self, console, mock_runtime):
        await commands_memory.cmd_history(mock_runtime, console, "")
        output = get_output(console)
        assert "not enabled" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_history_empty(self, console, mock_runtime):
        mem = MagicMock()
        mem.recent = AsyncMock(return_value=[])
        mock_runtime.episodic_memory = mem
        await commands_memory.cmd_history(mock_runtime, console, "")
        output = get_output(console)
        assert "No episodes" in output

    @pytest.mark.asyncio
    async def test_cmd_recall_no_episodic(self, console, mock_runtime):
        await commands_memory.cmd_recall(mock_runtime, console, "test query")
        output = get_output(console)
        assert "not enabled" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_recall_no_args(self, console, mock_runtime):
        mem = MagicMock()
        mock_runtime.episodic_memory = mem
        await commands_memory.cmd_recall(mock_runtime, console, "")
        output = get_output(console)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_cmd_dream_no_scheduler(self, console, mock_runtime):
        await commands_memory.cmd_dream(mock_runtime, console, "")
        output = get_output(console)
        assert "not enabled" in output.lower()
