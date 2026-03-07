"""Tests for the Experience layer — panels, shell, renderer."""

from io import StringIO

import pytest
from rich.console import Console

from probos.cognitive.llm_client import MockLLMClient, OpenAICompatibleClient
from probos.experience import panels
from probos.experience.renderer import ExecutionRenderer
from probos.experience.shell import ProbOSShell
from probos.runtime import ProbOSRuntime
from probos.types import AgentState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def runtime(tmp_path):
    """Create a runtime with MockLLMClient, start it, yield, stop."""
    llm = MockLLMClient()
    rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
    await rt.start()
    yield rt
    await rt.stop()


@pytest.fixture
def console():
    """Console that captures output to a StringIO buffer."""
    return Console(file=StringIO(), force_terminal=True, width=120)


@pytest.fixture
async def shell(runtime, console):
    """Shell with captured console output."""
    return ProbOSShell(runtime, console=console)


def get_output(con: Console) -> str:
    """Extract the captured console output."""
    return con.file.getvalue()


# ---------------------------------------------------------------------------
# Panel tests
# ---------------------------------------------------------------------------

class TestPanels:
    """Test that each panel rendering function produces output without errors."""

    def test_render_status_panel(self, runtime, console):
        status = runtime.status()
        panel = panels.render_status_panel(status)
        console.print(panel)
        output = get_output(console)
        assert "ProbOS" in output

    def test_render_agent_table(self, runtime, console):
        agents = runtime.registry.all()
        scores = runtime.trust_network.all_scores()
        table = panels.render_agent_table(agents, scores)
        console.print(table)
        output = get_output(console)
        assert "file_reader" in output
        assert "system_heartbeat" in output

    def test_render_agent_table_colors_states(self, runtime, console):
        agents = runtime.registry.all()
        scores = runtime.trust_network.all_scores()
        table = panels.render_agent_table(agents, scores)
        console.print(table)
        output = get_output(console)
        assert "active" in output.lower()

    def test_render_weight_table_empty(self, console):
        table = panels.render_weight_table({})
        console.print(table)
        output = get_output(console)
        assert "Weight" in output or "weight" in output.lower()

    def test_render_weight_table_with_data(self, console):
        weights = {("aaa", "bbb", "agent"): 0.05}
        table = panels.render_weight_table(weights)
        console.print(table)
        output = get_output(console)
        assert "0.05" in output

    def test_render_trust_panel(self, runtime, console):
        summary = runtime.trust_network.summary()
        panel = panels.render_trust_panel(summary)
        console.print(panel)
        output = get_output(console)
        assert "Trust" in output

    def test_render_gossip_panel(self, runtime, console):
        view = runtime.gossip.get_view()
        panel = panels.render_gossip_panel(view)
        console.print(panel)
        output = get_output(console)
        assert "Gossip" in output

    @pytest.mark.asyncio
    async def test_render_event_log_table(self, runtime, console):
        events = await runtime.event_log.query(limit=10)
        table = panels.render_event_log_table(events)
        console.print(table)
        output = get_output(console)
        assert "Event" in output

    def test_render_working_memory_panel(self, runtime, console):
        snapshot = runtime.working_memory.assemble(
            registry=runtime.registry,
            trust_network=runtime.trust_network,
            hebbian_router=runtime.hebbian_router,
        )
        panel = panels.render_working_memory_panel(snapshot)
        console.print(panel)
        assert len(get_output(console)) > 0

    def test_render_dag_result_empty(self, console):
        result = {
            "node_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "dag": None,
            "results": {},
        }
        panel = panels.render_dag_result(result)
        console.print(panel)
        output = get_output(console)
        assert "No intents" in output

    def test_render_dag_result_with_response(self, console):
        result = {
            "node_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "dag": None,
            "results": {},
            "response": "I can only do file operations.",
        }
        panel = panels.render_dag_result(result)
        console.print(panel)
        output = get_output(console)
        assert "I can only do file operations." in output
        assert "No intents" not in output

    def test_format_health_green(self):
        text = panels.format_health(0.85)
        assert "0.85" in str(text)

    def test_format_health_red(self):
        text = panels.format_health(0.2)
        assert "0.20" in str(text)


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
        assert "/model" in output
        assert "/tier" in output

    @pytest.mark.asyncio
    async def test_model_with_mock(self, shell, console):
        await shell.execute_command("/model")
        output = get_output(console)
        assert "MockLLMClient" in output

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
# Shell /model and /tier with OpenAICompatibleClient
# ---------------------------------------------------------------------------

class TestShellModelAndTier:
    """Test /model and /tier when runtime uses OpenAICompatibleClient."""

    @pytest.fixture
    async def oai_runtime(self, tmp_path):
        """Runtime with an OpenAICompatibleClient (endpoint is unreachable, but
        that's fine — we only test shell commands, not actual LLM calls)."""
        client = OpenAICompatibleClient(
            base_url="http://127.0.0.1:19999/v1",  # unlikely to be running
            models={"fast": "gpt-4o-mini", "standard": "claude-sonnet-4-6", "deep": "claude-opus-4-0-20250115"},
            default_tier="standard",
        )
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=client)
        await rt.start()
        yield rt
        await rt.stop()

    @pytest.fixture
    async def oai_shell(self, oai_runtime, console):
        return ProbOSShell(oai_runtime, console=console)

    @pytest.mark.asyncio
    async def test_model_shows_endpoint(self, oai_shell, console):
        await oai_shell.execute_command("/model")
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
# Shell NL input
# ---------------------------------------------------------------------------

class TestShellNLInput:

    @pytest.mark.asyncio
    async def test_nl_read_file(self, shell, console, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello from shell test")
        await shell.execute_command(f"read the file at {test_file}")
        output = get_output(console)
        assert len(output) > 0
        assert "Traceback" not in output

    @pytest.mark.asyncio
    async def test_nl_unrecognized(self, shell, console):
        await shell.execute_command("what is the meaning of life?")
        output = get_output(console)
        assert "No actionable intents" in output
        assert "Traceback" not in output

    @pytest.mark.asyncio
    async def test_nl_conversational_response(self, shell, console):
        """When the LLM returns a 'response' field, display it instead of
        the generic 'No actionable intents' message."""
        import json
        shell.runtime.llm_client.set_default_response(json.dumps({
            "intents": [],
            "response": "Hello! I can read and write files.",
        }))
        await shell.execute_command("hello there")
        output = get_output(console)
        assert "Hello! I can read and write files." in output
        assert "No actionable intents" not in output
        assert "Traceback" not in output

    @pytest.mark.asyncio
    async def test_nl_error_handling(self, shell, console):
        """Errors during NL processing should be caught gracefully."""
        await shell.execute_command("read the file at /nonexistent/path/test.txt")
        output = get_output(console)
        assert "Traceback" not in output


# ---------------------------------------------------------------------------
# Shell prompt
# ---------------------------------------------------------------------------

class TestShellPrompt:

    def test_prompt_format(self, shell):
        prompt = shell._build_prompt()
        assert "agents" in prompt
        assert "health" in prompt
        assert "probos>" in prompt

    def test_health_computation(self, shell):
        health = shell._compute_health()
        assert 0.0 <= health <= 1.0
        # All agents are ACTIVE after boot, so health should be positive
        assert health > 0.5


# ---------------------------------------------------------------------------
# Renderer tests
# ---------------------------------------------------------------------------

class TestRenderer:

    @pytest.mark.asyncio
    async def test_process_with_feedback(self, runtime, console, tmp_path):
        renderer = ExecutionRenderer(console, runtime)
        test_file = tmp_path / "render_test.txt"
        test_file.write_text("renderer content")
        result = await renderer.process_with_feedback(
            f"read the file at {test_file}"
        )
        assert result["complete"]
        assert result["node_count"] == 1
        assert result["completed_count"] == 1

    @pytest.mark.asyncio
    async def test_process_empty_dag(self, runtime, console):
        renderer = ExecutionRenderer(console, runtime)
        result = await renderer.process_with_feedback(
            "what is the meaning of life?"
        )
        assert result["node_count"] == 0
        output = get_output(console)
        assert "No actionable intents" in output

    @pytest.mark.asyncio
    async def test_process_conversational_response(self, runtime, console):
        """Renderer shows LLM response text instead of generic message."""
        import json
        runtime.llm_client.set_default_response(json.dumps({
            "intents": [],
            "response": "I can only do file operations.",
        }))
        renderer = ExecutionRenderer(console, runtime)
        result = await renderer.process_with_feedback("what can you do?")
        assert result["node_count"] == 0
        assert result["response"] == "I can only do file operations."
        output = get_output(console)
        assert "I can only do file operations." in output
        assert "No actionable intents" not in output

    @pytest.mark.asyncio
    async def test_debug_mode_shows_extra(self, runtime, console, tmp_path):
        renderer = ExecutionRenderer(console, runtime, debug=True)
        test_file = tmp_path / "debug_test.txt"
        test_file.write_text("debug content")
        await renderer.process_with_feedback(
            f"read the file at {test_file}"
        )
        output = get_output(console)
        # Debug mode should show DAG details
        assert "DEBUG" in output

    @pytest.mark.asyncio
    async def test_process_parallel_reads(self, runtime, console, tmp_path):
        renderer = ExecutionRenderer(console, runtime)
        f1 = tmp_path / "p1.txt"
        f2 = tmp_path / "p2.txt"
        f1.write_text("one")
        f2.write_text("two")
        result = await renderer.process_with_feedback(
            f"read {f1} and {f2}"
        )
        assert result["node_count"] == 2
        assert result["completed_count"] == 2


# ---------------------------------------------------------------------------
# Event callback tests
# ---------------------------------------------------------------------------

class TestEventCallback:
    """Test the on_event callback mechanism added to decomposer and runtime."""

    @pytest.mark.asyncio
    async def test_runtime_on_event_called(self, runtime, tmp_path):
        """The on_event callback should be invoked during NL processing."""
        test_file = tmp_path / "event_test.txt"
        test_file.write_text("event test content")

        events_received: list[str] = []

        async def capture_event(name: str, data: dict) -> None:
            events_received.append(name)

        await runtime.process_natural_language(
            f"read the file at {test_file}",
            on_event=capture_event,
        )

        assert "decompose_start" in events_received
        assert "decompose_complete" in events_received
        assert "node_start" in events_received
        assert "node_complete" in events_received

    @pytest.mark.asyncio
    async def test_runtime_without_on_event(self, runtime, tmp_path):
        """Without on_event, process_natural_language works as before."""
        test_file = tmp_path / "no_event.txt"
        test_file.write_text("no event content")

        result = await runtime.process_natural_language(
            f"read the file at {test_file}"
        )
        assert result["complete"]
        assert result["node_count"] == 1
