"""Tests for commands_llm module (AD-519)."""
from __future__ import annotations

import pytest
from io import StringIO
from unittest.mock import MagicMock

from rich.console import Console

from probos.experience.commands import commands_llm
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
    rt.llm_client = MagicMock()
    # Make it NOT an OpenAICompatibleClient by default
    type(rt.llm_client).__name__ = "MockLLMClient"
    return rt


class TestCommandsLLM:
    @pytest.mark.asyncio
    async def test_cmd_models_mock_client(self, console, mock_runtime):
        await commands_llm.cmd_models(mock_runtime, console, "")
        output = get_output(console)
        assert "MockLLMClient" in output or "mock" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_tier_mock_client(self, console, mock_runtime):
        await commands_llm.cmd_tier(mock_runtime, console, "")
        output = get_output(console)
        assert "MockLLMClient" in output or "mock" in output.lower() or "only available" in output.lower()

    @pytest.mark.asyncio
    async def test_cmd_registry_mock_client(self, console, mock_runtime):
        await commands_llm.cmd_registry(mock_runtime, console, "")
        output = get_output(console)
        assert "mock" in output.lower() or "Active Models" in output
