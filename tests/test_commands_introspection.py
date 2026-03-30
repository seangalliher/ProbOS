"""Tests for commands_introspection module (AD-519)."""
from __future__ import annotations

import pytest
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

from rich.console import Console

from probos.experience.commands import commands_introspection


@pytest.fixture
def console():
    return Console(file=StringIO(), force_terminal=True, width=120)


def get_output(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


@pytest.fixture
def mock_runtime():
    rt = MagicMock()
    rt.hebbian_router.all_weights_typed.return_value = []
    rt.gossip.get_view.return_value = {}
    rt.self_mod_pipeline = None
    rt.behavioral_monitor = None
    rt.event_log.query = AsyncMock(return_value=[])
    rt.attention.get_queue_snapshot.return_value = []
    rt.attention.current_focus = None
    rt.attention.focus_history = []
    rt.workflow_cache.entries = []
    rt.workflow_cache.size = 0
    rt.trust_network = MagicMock()
    rt.registry.get.return_value = None
    return rt


class TestCommandsIntrospection:
    @pytest.mark.asyncio
    async def test_cmd_weights(self, console, mock_runtime):
        with patch("probos.experience.panels.render_weight_table", return_value="WEIGHTS"):
            await commands_introspection.cmd_weights(mock_runtime, console, "")
        output = get_output(console)
        assert "WEIGHTS" in output

    @pytest.mark.asyncio
    async def test_cmd_gossip(self, console, mock_runtime):
        with patch("probos.experience.panels.render_gossip_panel", return_value="GOSSIP"):
            await commands_introspection.cmd_gossip(mock_runtime, console, "")
        output = get_output(console)
        assert "GOSSIP" in output

    @pytest.mark.asyncio
    async def test_cmd_designed_not_enabled(self, console, mock_runtime):
        await commands_introspection.cmd_designed(mock_runtime, console, "")
        output = get_output(console)
        assert "not enabled" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_qa_empty(self, console, mock_runtime):
        mock_runtime._qa_reports = {}
        await commands_introspection.cmd_qa(mock_runtime, console, "")
        output = get_output(console)
        assert "No QA results" in output

    @pytest.mark.asyncio
    async def test_cmd_prune_no_args(self, console, mock_runtime):
        await commands_introspection.cmd_prune(mock_runtime, console, "")
        output = get_output(console)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_cmd_prune_not_found(self, console, mock_runtime):
        await commands_introspection.cmd_prune(mock_runtime, console, "nonexistent")
        output = get_output(console)
        assert "not found" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_log(self, console, mock_runtime):
        with patch("probos.experience.panels.render_event_log_table", return_value="LOG"):
            await commands_introspection.cmd_log(mock_runtime, console, "")
        output = get_output(console)
        assert "LOG" in output

    @pytest.mark.asyncio
    async def test_cmd_attention(self, console, mock_runtime):
        with patch("probos.experience.panels.render_attention_panel", return_value="ATTENTION"):
            await commands_introspection.cmd_attention(mock_runtime, console, "")
        output = get_output(console)
        assert "ATTENTION" in output

    @pytest.mark.asyncio
    async def test_cmd_cache(self, console, mock_runtime):
        with patch("probos.experience.panels.render_workflow_cache_panel", return_value="CACHE"):
            await commands_introspection.cmd_cache(mock_runtime, console, "")
        output = get_output(console)
        assert "CACHE" in output
