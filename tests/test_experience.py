"""Experience layer: shell core -- commands, debug mode, model/tier, quit, prompt.

Split out of the original single test_experience.py so no one file is the
canonical gate's critical path (see docs/development/test-suite-optimization-plan.md, P0.1).
"""

import pytest

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.experience.shell import ProbOSShell
from probos.runtime import ProbOSRuntime

from tests.fixtures.experience_shell import (  # noqa: F401 -- pytest fixtures and helper
    console,
    get_output,
    runtime,
    shell,
)


# ---------------------------------------------------------------------------
# Shell command tests
# ---------------------------------------------------------------------------

class TestShellCommands:
    """Test each slash command produces expected output."""

    @pytest.mark.asyncio
    async def test_status(self, shell, console):
        await shell.execute_command("/status")
        output = get_output(console)
        assert "ProbOS" in output

    @pytest.mark.asyncio
    async def test_agents(self, shell, console):
        await shell.execute_command("/agents")
        output = get_output(console)
        assert "file_reader" in output

    @pytest.mark.asyncio
    async def test_weights(self, shell, console):
        await shell.execute_command("/weights")
        assert len(get_output(console)) > 0

    @pytest.mark.asyncio
    async def test_gossip(self, shell, console):
        await shell.execute_command("/gossip")
        assert len(get_output(console)) > 0

    @pytest.mark.asyncio
    async def test_log(self, shell, console):
        await shell.execute_command("/log")
        output = get_output(console)
        assert len(output) > 0

    @pytest.mark.asyncio
    async def test_log_with_category(self, shell, console):
        await shell.execute_command("/log system")
        output = get_output(console)
        assert len(output) > 0

    @pytest.mark.asyncio
    async def test_memory(self, shell, console):
        await shell.execute_command("/memory")
        assert len(get_output(console)) > 0

    @pytest.mark.asyncio
    async def test_help(self, shell, console):
        await shell.execute_command("/help")
        output = get_output(console)
        assert "/status" in output
        assert "/quit" in output
        assert "/models" in output
        assert "/registry" in output
        assert "/tier" in output

    @pytest.mark.asyncio
    async def test_models_with_mock(self, shell, console):
        await shell.execute_command("/models")
        output = get_output(console)
        assert "MockLLMClient" in output

    @pytest.mark.asyncio
    async def test_cmd_registry_mock_client(self, shell, console):
        await shell.execute_command("/registry")
        output = get_output(console)
        assert "MockLLMClient" in output
        assert "Active Models" in output

    @pytest.mark.asyncio
    async def test_tier_with_mock(self, shell, console):
        """Tier switching should warn when using MockLLMClient."""
        await shell.execute_command("/tier fast")
        output = get_output(console)
        assert "MockLLMClient" in output or "mock" in output.lower()

    @pytest.mark.asyncio
    async def test_unknown_command(self, shell, console):
        await shell.execute_command("/foobar")
        output = get_output(console)
        assert "Unknown command" in output

    @pytest.mark.asyncio
    async def test_empty_input(self, shell, console):
        await shell.execute_command("")
        assert get_output(console) == ""


# ---------------------------------------------------------------------------
# Shell debug mode
# ---------------------------------------------------------------------------

class TestShellDebugMode:

    @pytest.mark.asyncio
    async def test_debug_on(self, shell, console):
        await shell.execute_command("/debug on")
        assert shell.debug is True
        assert shell.renderer.debug is True
        assert "on" in get_output(console).lower()

    @pytest.mark.asyncio
    async def test_debug_off(self, shell, console):
        shell.debug = True
        await shell.execute_command("/debug off")
        assert shell.debug is False
        assert shell.renderer.debug is False

    @pytest.mark.asyncio
    async def test_debug_toggle(self, shell, console):
        assert shell.debug is False
        await shell.execute_command("/debug")
        assert shell.debug is True
        await shell.execute_command("/debug")
        assert shell.debug is False


# ---------------------------------------------------------------------------
# Shell /models and /tier with OpenAICompatibleClient
# ---------------------------------------------------------------------------

class TestShellModelAndTier:
    """Test /models and /tier when runtime uses OpenAICompatibleClient."""

    @pytest.fixture
    async def oai_runtime(self, tmp_path):
        """Runtime with an OpenAICompatibleClient — NOT fully started.
        These tests only exercise /models and /tier shell commands, which
        inspect runtime.llm_client — no agent fleet or startup needed."""
        client = OpenAICompatibleClient(
            base_url="http://127.0.0.1:19999/v1",  # unlikely to be running
            models={"fast": "gpt-4o-mini", "standard": "claude-sonnet-4-6", "deep": "claude-opus-4-0-20250115"},
            default_tier="standard",
            timeout=0.5,
        )
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=client)
        yield rt

    @pytest.fixture
    async def oai_shell(self, oai_runtime, console):
        return ProbOSShell(oai_runtime, console=console)

    @pytest.mark.asyncio
    async def test_models_shows_endpoint(self, oai_shell, console):
        await oai_shell.execute_command("/models")
        output = get_output(console)
        assert "OpenAICompatibleClient" in output
        assert "127.0.0.1" in output
        assert "claude-sonnet" in output

    @pytest.mark.asyncio
    async def test_tier_show_current(self, oai_shell, console):
        await oai_shell.execute_command("/tier")
        output = get_output(console)
        assert "standard" in output

    @pytest.mark.asyncio
    async def test_tier_switch(self, oai_shell, console):
        await oai_shell.execute_command("/tier fast")
        output = get_output(console)
        assert "fast" in output
        assert "gpt-4o-mini" in output
        # Verify it actually changed
        assert oai_shell.runtime.llm_client.default_tier == "fast"

    @pytest.mark.asyncio
    async def test_tier_invalid(self, oai_shell, console):
        await oai_shell.execute_command("/tier turbo")
        output = get_output(console)
        assert "Unknown tier" in output


# ---------------------------------------------------------------------------
# Shell quit
# ---------------------------------------------------------------------------

class TestShellQuit:

    @pytest.mark.asyncio
    async def test_quit_sets_running_false(self, shell):
        shell._running = True
        await shell.execute_command("/quit")
        assert shell._running is False


# ---------------------------------------------------------------------------
# Shell prompt
# ---------------------------------------------------------------------------

class TestShellPrompt:

    def test_prompt_format(self, shell):
        prompt = shell._build_prompt()
        assert "crew" in prompt
        assert "health" in prompt
        assert "probos>" in prompt

    def test_health_computation(self, shell):
        health = shell._compute_health()
        assert 0.0 <= health <= 1.0
        # All agents are ACTIVE after boot, so health should be positive
        assert health > 0.5
