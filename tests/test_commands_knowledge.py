"""Tests for commands_knowledge module (AD-519)."""
from __future__ import annotations

import pytest
from io import StringIO
from unittest.mock import MagicMock

from rich.console import Console

from probos.experience.commands import commands_knowledge
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
    rt._knowledge_store = None
    rt._semantic_layer = None
    rt._emergent_detector = None
    rt.pools = {}
    return rt


class TestCommandsKnowledge:
    @pytest.mark.asyncio
    async def test_cmd_knowledge_not_enabled(self, console, mock_runtime):
        await commands_knowledge.cmd_knowledge(mock_runtime, console, "")
        output = get_output(console)
        assert "not enabled" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_rollback_not_enabled(self, console, mock_runtime):
        await commands_knowledge.cmd_rollback(mock_runtime, console, "trust snapshot")
        output = get_output(console)
        assert "not enabled" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_rollback_no_args(self, console, mock_runtime):
        mock_runtime._knowledge_store = MagicMock()
        await commands_knowledge.cmd_rollback(mock_runtime, console, "")
        output = get_output(console)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_cmd_search_no_layer(self, console, mock_runtime):
        await commands_knowledge.cmd_search(mock_runtime, console, "test")
        output = get_output(console)
        assert "not available" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_search_no_query(self, console, mock_runtime):
        mock_runtime._semantic_layer = MagicMock()
        await commands_knowledge.cmd_search(mock_runtime, console, "")
        output = get_output(console)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_cmd_anomalies_not_available(self, console, mock_runtime):
        await commands_knowledge.cmd_anomalies(mock_runtime, console, "")
        output = get_output(console)
        assert "not available" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_scout_no_pool(self, console, mock_runtime):
        await commands_knowledge.cmd_scout(mock_runtime, console, "")
        output = get_output(console)
        assert "not available" in output.lower()
