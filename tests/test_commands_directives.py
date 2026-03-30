"""Tests for commands_directives module (AD-519)."""
from __future__ import annotations

import pytest
from io import StringIO
from unittest.mock import MagicMock

from rich.console import Console

from probos.experience.commands import commands_directives


@pytest.fixture
def console():
    return Console(file=StringIO(), force_terminal=True, width=120)


def get_output(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


@pytest.fixture
def mock_runtime():
    rt = MagicMock()
    rt.directive_store = None
    rt.config.self_mod.allowed_imports = ["os", "json"]
    rt.self_mod_pipeline = None
    return rt


class TestCommandsDirectives:
    @pytest.mark.asyncio
    async def test_cmd_order_no_args(self, console, mock_runtime):
        await commands_directives.cmd_order(mock_runtime, console, "")
        output = get_output(console)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_cmd_order_no_store(self, console, mock_runtime):
        await commands_directives.cmd_order(mock_runtime, console, "analyst do something")
        output = get_output(console)
        assert "not available" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_directives_no_store(self, console, mock_runtime):
        await commands_directives.cmd_directives(mock_runtime, console, "")
        output = get_output(console)
        assert "not available" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_revoke_no_args(self, console, mock_runtime):
        await commands_directives.cmd_revoke(mock_runtime, console, "")
        output = get_output(console)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_cmd_revoke_no_store(self, console, mock_runtime):
        await commands_directives.cmd_revoke(mock_runtime, console, "abc123")
        output = get_output(console)
        assert "not available" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_amend_no_args(self, console, mock_runtime):
        await commands_directives.cmd_amend(mock_runtime, console, "")
        output = get_output(console)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_cmd_amend_no_store(self, console, mock_runtime):
        await commands_directives.cmd_amend(mock_runtime, console, "abc123 new text")
        output = get_output(console)
        assert "not available" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_imports_list(self, console, mock_runtime):
        await commands_directives.cmd_imports(mock_runtime, console, "")
        output = get_output(console)
        assert "Allowed imports" in output

    @pytest.mark.asyncio
    async def test_cmd_imports_add(self, console, mock_runtime):
        await commands_directives.cmd_imports(mock_runtime, console, "add requests")
        output = get_output(console)
        assert "Added" in output
        assert "requests" in mock_runtime.config.self_mod.allowed_imports


class TestGetCallsign:
    def test_fallback(self):
        """get_callsign falls back to formatted name for unknown agents."""
        result = commands_directives.get_callsign("nonexistent_agent")
        assert isinstance(result, str)
        assert len(result) > 0
