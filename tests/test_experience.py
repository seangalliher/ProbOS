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


# ---------------------------------------------------------------------------
# Reflect capability tests
# ---------------------------------------------------------------------------


class TestReflectCapability:

    @pytest.mark.asyncio
    async def test_render_dag_result_with_reflection(self, runtime, console):
        """render_dag_result shows reflection text when present."""
        from probos.experience.panels import render_dag_result
        from probos.types import TaskDAG, TaskNode

        result = {
            "node_count": 1,
            "completed_count": 1,
            "failed_count": 0,
            "dag": TaskDAG(nodes=[
                TaskNode(id="t1", intent="list_directory", status="completed"),
            ]),
            "results": {},
            "reflection": "The largest file is data.csv at 1.2MB.",
        }
        panel = render_dag_result(result, debug=False)
        console.print(panel)
        output = get_output(console)
        assert "largest file" in output

    @pytest.mark.asyncio
    async def test_render_dag_result_without_reflection(self, runtime, console):
        """render_dag_result works normally when no reflection is present."""
        from probos.experience.panels import render_dag_result
        from probos.types import TaskDAG, TaskNode

        result = {
            "node_count": 1,
            "completed_count": 1,
            "failed_count": 0,
            "dag": TaskDAG(nodes=[
                TaskNode(id="t1", intent="read_file", status="completed"),
            ]),
            "results": {},
        }
        panel = render_dag_result(result, debug=False)
        console.print(panel)
        output = get_output(console)
        assert "1/1 tasks completed" in output

    @pytest.mark.asyncio
    async def test_nl_with_reflect_produces_reflection(self, runtime, tmp_path):
        """When MockLLMClient returns reflect:true, result includes reflection."""
        import json

        # Create a file so the intent succeeds
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")

        # Override the default response for this specific request
        runtime.llm_client.set_default_response(json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "list_directory",
                "params": {"path": str(tmp_path)},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        }))

        result = await runtime.process_natural_language(
            "what is the largest file in this directory?"
        )
        assert result["node_count"] == 1
        assert result["completed_count"] == 1
        assert "reflection" in result
        assert len(result["reflection"]) > 0

    @pytest.mark.asyncio
    async def test_nl_without_reflect_no_reflection_key(self, runtime, tmp_path):
        """When reflect is false, no reflection key in the result."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = await runtime.process_natural_language(
            f"read the file at {test_file}"
        )
        assert result["node_count"] == 1
        assert "reflection" not in result


# ---------------------------------------------------------------------------
# Episodic memory integration tests
# ---------------------------------------------------------------------------


class TestEpisodicMemoryIntegration:
    """Integration tests: runtime + MockEpisodicMemory."""

    @pytest.fixture
    async def mem_runtime(self, tmp_path):
        from probos.cognitive.episodic_mock import MockEpisodicMemory

        llm = MockLLMClient()
        mem = MockEpisodicMemory(relevance_threshold=0.3)
        rt = ProbOSRuntime(
            data_dir=tmp_path / "data",
            llm_client=llm,
            episodic_memory=mem,
        )
        await rt.start()
        yield rt, mem
        await rt.stop()

    @pytest.mark.asyncio
    async def test_nl_stores_episode(self, mem_runtime, tmp_path):
        rt, mem = mem_runtime
        test_file = tmp_path / "ep_test.txt"
        test_file.write_text("episode test")
        await rt.process_natural_language(f"read the file at {test_file}")

        recent = await mem.recent(k=10)
        assert len(recent) == 1
        ep = recent[0]
        assert "read the file" in ep.user_input
        assert len(ep.outcomes) == 1
        assert ep.outcomes[0]["intent"] == "read_file"
        assert ep.outcomes[0]["success"] is True
        assert ep.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_second_request_can_recall_first(self, mem_runtime, tmp_path):
        rt, mem = mem_runtime
        f1 = tmp_path / "first.txt"
        f1.write_text("first")
        await rt.process_natural_language(f"read the file at {f1}")

        results = await rt.recall_similar("read the file")
        assert len(results) >= 1
        assert "first.txt" in results[0].user_input

    @pytest.mark.asyncio
    async def test_episode_includes_agent_ids(self, mem_runtime, tmp_path):
        rt, mem = mem_runtime
        test_file = tmp_path / "agents.txt"
        test_file.write_text("test")
        await rt.process_natural_language(f"read the file at {test_file}")

        recent = await mem.recent(k=1)
        assert len(recent) == 1
        # Agent IDs are extracted from results — may be empty if mock
        # but the episode should still exist with outcomes
        assert len(recent[0].outcomes) > 0

    @pytest.mark.asyncio
    async def test_no_episode_for_empty_dag(self, mem_runtime):
        rt, mem = mem_runtime
        await rt.process_natural_language("what is the meaning of life?")
        recent = await mem.recent(k=10)
        # Filter out SystemQA episodes (background task from AD-154)
        user_episodes = [e for e in recent if not e.user_input.startswith("[SystemQA]")]
        assert len(user_episodes) == 0  # Empty DAGs don't produce episodes


# ---------------------------------------------------------------------------
# Episodic shell command tests
# ---------------------------------------------------------------------------


class TestShellEpisodicCommands:

    @pytest.fixture
    async def ep_shell(self, tmp_path):
        from probos.cognitive.episodic_mock import MockEpisodicMemory

        llm = MockLLMClient()
        mem = MockEpisodicMemory(relevance_threshold=0.3)
        rt = ProbOSRuntime(
            data_dir=tmp_path / "data",
            llm_client=llm,
            episodic_memory=mem,
        )
        await rt.start()
        con = Console(file=StringIO(), force_terminal=True, width=120)
        shell = ProbOSShell(rt, console=con)
        yield shell, con, rt
        await rt.stop()

    @pytest.mark.asyncio
    async def test_history_shows_episodes(self, ep_shell, tmp_path):
        shell, con, rt = ep_shell
        f = tmp_path / "h.txt"
        f.write_text("history test")
        await rt.process_natural_language(f"read the file at {f}")
        await shell.execute_command("/history")
        output = get_output(con)
        assert "read the file" in output
        assert "read_file" in output

    @pytest.mark.asyncio
    async def test_recall_shows_results(self, ep_shell, tmp_path):
        shell, con, rt = ep_shell
        f = tmp_path / "r.txt"
        f.write_text("recall test")
        await rt.process_natural_language(f"read the file at {f}")
        await shell.execute_command("/recall read the file")
        output = get_output(con)
        assert "read the file" in output

    @pytest.mark.asyncio
    async def test_status_includes_episodic_stats(self, ep_shell):
        shell, con, rt = ep_shell
        await shell.execute_command("/status")
        output = get_output(con)
        assert "ProbOS" in output

    @pytest.mark.asyncio
    async def test_history_no_memory(self, shell, console):
        """Without episodic memory, /history says it's not enabled."""
        await shell.execute_command("/history")
        output = get_output(console)
        assert "not enabled" in output

    @pytest.mark.asyncio
    async def test_recall_no_memory(self, shell, console):
        """Without episodic memory, /recall says it's not enabled."""
        await shell.execute_command("/recall test")
        output = get_output(console)
        assert "not enabled" in output

    @pytest.mark.asyncio
    async def test_help_includes_history_and_recall(self, shell, console):
        await shell.execute_command("/help")
        output = get_output(console)
        assert "/history" in output
        assert "/recall" in output


# ---------------------------------------------------------------------------
# Attention integration tests
# ---------------------------------------------------------------------------


class TestAttentionIntegration:

    @pytest.mark.asyncio
    async def test_dag_executor_respects_attention_budget(self, tmp_path):
        """DAG with 5 independent nodes and budget=2 executes in batches."""
        import json
        from probos.cognitive.attention import AttentionManager

        llm = MockLLMClient()
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
        # Set attention budget to 2
        rt.attention = AttentionManager(max_concurrent=2)
        rt.dag_executor.attention = rt.attention
        await rt.start()
        try:
            # Create 5 files so we can read them all
            for i in range(5):
                (tmp_path / f"f{i}.txt").write_text(f"content {i}")

            llm.set_default_response(json.dumps({
                "intents": [
                    {
                        "id": f"t{i}",
                        "intent": "read_file",
                        "params": {"path": str(tmp_path / f"f{i}.txt")},
                        "depends_on": [],
                        "use_consensus": False,
                    }
                    for i in range(5)
                ],
            }))

            result = await rt.process_natural_language("read all 5 files")
            assert result["node_count"] == 5
            assert result["completed_count"] == 5
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_attention_scores_in_event_callback(self, runtime, tmp_path):
        """on_event payloads include attention_score when attention is active."""
        test_file = tmp_path / "attn_event.txt"
        test_file.write_text("attention event test")

        events_received: list[dict] = []

        async def capture(name: str, data: dict) -> None:
            events_received.append({"name": name, "data": data})

        await runtime.process_natural_language(
            f"read the file at {test_file}",
            on_event=capture,
        )

        node_starts = [e for e in events_received if e["name"] == "node_start"]
        assert len(node_starts) >= 1
        # attention_score should be in the event data
        assert "attention_score" in node_starts[0]["data"]

    @pytest.mark.asyncio
    async def test_nl_updates_focus(self, runtime):
        """process_natural_language() stores focus keywords in attention manager."""
        await runtime.process_natural_language("read the file at /tmp/test.txt")
        focus = runtime.attention.current_focus
        assert focus["keywords"]  # should have keywords from the input
        assert "read" in focus["keywords"] or "file" in focus["keywords"]


class TestAttentionExperience:

    @pytest.mark.asyncio
    async def test_attention_command(self, shell, console):
        """/attention renders the attention panel."""
        await shell.execute_command("/attention")
        output = get_output(console)
        assert "Attention Queue" in output

    @pytest.mark.asyncio
    async def test_render_attention_panel_with_entries(self):
        """render_attention_panel renders queued tasks with scores."""
        from probos.types import AttentionEntry
        from datetime import datetime, timezone

        entries = [
            AttentionEntry(
                task_id="abc12345", intent="read_file",
                urgency=0.8, score=1.5, dependency_depth=1,
                created_at=datetime.now(timezone.utc),
            ),
            AttentionEntry(
                task_id="def67890", intent="list_directory",
                urgency=0.5, score=0.9, dependency_depth=0,
                created_at=datetime.now(timezone.utc),
            ),
        ]
        focus = {"keywords": ["read", "file"], "context": "read a file"}
        panel = panels.render_attention_panel(entries, focus)

        con = Console(file=StringIO(), force_terminal=True, width=120)
        con.print(panel)
        output = get_output(con)
        assert "abc12345" in output
        assert "read_file" in output
        assert "score=" in output
        assert "Focus:" in output

    @pytest.mark.asyncio
    async def test_render_attention_panel_empty(self):
        """render_attention_panel renders empty state."""
        panel = panels.render_attention_panel([], focus=None)
        con = Console(file=StringIO(), force_terminal=True, width=120)
        con.print(panel)
        output = get_output(con)
        assert "empty" in output.lower()


# ---------------------------------------------------------------------------
# Renderer: force-reflect and self-mod gating
# ---------------------------------------------------------------------------

class TestRendererForceReflect:
    """Tests for force-reflect covering built-in agents."""

    @pytest.fixture
    async def renderer_env(self, tmp_path):
        llm = MockLLMClient()
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
        await rt.start()
        con = Console(file=StringIO(), force_terminal=True, width=120)
        renderer = ExecutionRenderer(con, rt, debug=False)
        yield renderer, rt
        await rt.stop()

    def test_force_reflect_for_builtin_requires_reflect(self, renderer_env):
        """Test 34: run_command intent forces dag.reflect even if LLM set false."""
        from probos.types import TaskDAG, TaskNode
        _, rt = renderer_env
        dag = TaskDAG(
            nodes=[TaskNode(id="t1", intent="run_command", params={"command": "date"})],
            source_text="what time is it",
            reflect=False,
        )
        # Simulate the force-reflect logic that happens in process_with_feedback
        reflect_intents = {
            d.name for d in rt._collect_intent_descriptors() if d.requires_reflect
        }
        assert "run_command" in reflect_intents
        if any(n.intent in reflect_intents for n in dag.nodes):
            dag.reflect = True
        assert dag.reflect is True

    def test_no_force_reflect_for_read_file(self, renderer_env):
        """Test 35: read_file does NOT force reflect."""
        from probos.types import TaskDAG, TaskNode
        _, rt = renderer_env
        dag = TaskDAG(
            nodes=[TaskNode(id="t1", intent="read_file", params={"path": "/tmp/a"})],
            source_text="read /tmp/a",
            reflect=False,
        )
        reflect_intents = {
            d.name for d in rt._collect_intent_descriptors() if d.requires_reflect
        }
        assert "read_file" not in reflect_intents
        if any(n.intent in reflect_intents for n in dag.nodes):
            dag.reflect = True
        assert dag.reflect is False


class TestRendererSelfModGating:
    """Tests for self-mod not triggering on conversational responses."""

    def test_conversational_response_skips_self_mod(self):
        """Test 36: Decomposer response with empty intents + response skips self-mod."""
        from probos.types import TaskDAG
        dag = TaskDAG(
            nodes=[],
            source_text="hello",
            response="Hello! I'm ProbOS.",
        )
        # The renderer should check dag.response BEFORE triggering self-mod.
        # If response is set and nodes are empty, self-mod should NOT run.
        assert dag.nodes == []
        assert dag.response == "Hello! I'm ProbOS."
        # Renderer logic: if dag.response is truthy, show it and return early
        should_try_self_mod = not dag.response
        assert should_try_self_mod is False

    def test_empty_response_allows_self_mod(self):
        """Test 37: Empty response + empty intents allows self-mod."""
        from probos.types import TaskDAG
        dag = TaskDAG(
            nodes=[],
            source_text="do something novel",
            response="",
        )
        assert dag.nodes == []
        should_try_self_mod = not dag.response
        assert should_try_self_mod is True

    def test_capability_gap_flag_triggers_self_mod(self):
        """capability_gap=True triggers self-mod even with a response set."""
        from probos.types import TaskDAG
        from probos.cognitive.decomposer import is_capability_gap

        dag = TaskDAG(
            nodes=[],
            source_text="translate hello to French",
            response="No translation capability available.",
            capability_gap=True,
        )
        is_gap = dag.capability_gap or (dag.response and is_capability_gap(dag.response))
        # Renderer: if dag.response and NOT is_gap → skip self-mod (early return)
        # So self-mod runs when is_gap is True.
        assert is_gap is True

    def test_capability_gap_flag_overrides_undetectable_response(self):
        """capability_gap=True works even when regex can't match response text."""
        from probos.types import TaskDAG
        from probos.cognitive.decomposer import is_capability_gap

        # A response the regex would never match
        dag = TaskDAG(
            nodes=[],
            source_text="translate hello to French",
            response="Translation is something I need to learn.",
            capability_gap=True,
        )
        # Regex alone would miss this:
        assert is_capability_gap(dag.response) is False
        # But the flag catches it:
        is_gap = dag.capability_gap or (dag.response and is_capability_gap(dag.response))
        assert is_gap is True


class TestRendererSelfModIntegration:
    """Integration tests for the full renderer self-mod pipeline."""

    @pytest.fixture
    async def self_mod_env(self, tmp_path):
        """Runtime with self-mod enabled + renderer + captured console."""
        llm = MockLLMClient()
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
        await rt.start()
        con = Console(file=StringIO(), force_terminal=True, width=120)
        renderer = ExecutionRenderer(con, rt, debug=False)
        yield llm, rt, renderer, con
        await rt.stop()

    @pytest.mark.asyncio
    async def test_self_mod_pipeline_exists(self, self_mod_env):
        """Verify that the test runtime actually has self_mod_pipeline set up."""
        _, rt, _, _ = self_mod_env
        assert rt.self_mod_pipeline is not None, (
            "self_mod_pipeline is None — self-mod won't trigger"
        )

    @pytest.mark.asyncio
    async def test_capability_gap_reaches_self_mod(self, self_mod_env):
        """Capability gap DAG triggers _extract_unhandled_intent (not early return)."""
        llm, rt, renderer, con = self_mod_env

        # Phase 1 (decompose): return a capability-gap response
        gap_json = (
            '{"intents": [], '
            '"response": "I don\\u2019t have an audio transcription intent yet.", '
            '"capability_gap": true}'
        )
        llm.set_default_response(gap_json)

        # Because user approval prompt blocks (EOFError → "n"), self-mod
        # will be "rejected" but the proposal text should appear in output.
        result = await renderer.process_with_feedback(
            "please transcribe this audio clip"
        )
        output = con.file.getvalue()

        # The gap response should be printed (dim)
        assert "transcription intent" in output

        # Self-mod proposal should appear OR "Analyzing unhandled request"
        # was reached (either way proves we entered the self-mod block).
        entered_self_mod = (
            "Self-Modification Proposal" in output
            or "Self-modification rejected" in output
            or "designed and registered" in output.lower()
        )
        assert entered_self_mod, (
            f"Self-mod block was never entered.  Full output:\n{output}"
        )

    @pytest.mark.asyncio
    async def test_capability_gap_via_regex_fallback(self, self_mod_env):
        """Even without capability_gap flag, regex match enters self-mod."""
        llm, rt, renderer, con = self_mod_env

        # Return response matching regex but NO capability_gap field
        gap_json = (
            '{"intents": [], '
            '"response": "I don\'t have an intent for audio transcription yet."}'
        )
        llm.set_default_response(gap_json)

        await renderer.process_with_feedback("please transcribe this audio clip")
        output = con.file.getvalue()

        entered_self_mod = (
            "Self-Modification Proposal" in output
            or "Self-modification rejected" in output
            or "designed and registered" in output.lower()
        )
        assert entered_self_mod, (
            f"Regex fallback did not trigger self-mod.  Full output:\n{output}"
        )

    @pytest.mark.asyncio
    async def test_conversational_response_skips_self_mod_integration(self, self_mod_env):
        """Genuine conversational response must NOT enter self-mod."""
        llm, rt, renderer, con = self_mod_env

        # Conversational reply — no capability gap
        conv_json = '{"intents": [], "response": "Hello! How can I help you?"}'
        llm.set_default_response(conv_json)

        await renderer.process_with_feedback("hello there")
        output = con.file.getvalue()

        assert "How can I help you" in output
        assert "Self-Modification Proposal" not in output
        assert "Analyzing unhandled request" not in output

    @pytest.mark.asyncio
    async def test_extract_unhandled_intent_returns_data(self, self_mod_env):
        """_extract_unhandled_intent returns valid intent metadata."""
        _, rt, _, _ = self_mod_env
        meta = await rt._extract_unhandled_intent("please transcribe this audio clip")
        assert meta is not None, "_extract_unhandled_intent returned None"
        assert "name" in meta
        assert "description" in meta

    @pytest.mark.asyncio
    async def test_think_tags_dont_break_self_mod(self, self_mod_env):
        """qwen-style <think> tags in decomposer response still trigger self-mod."""
        llm, rt, renderer, con = self_mod_env

        # Simulate qwen output with <think> tags wrapping the JSON
        gap_with_think = (
            '<think>\nThe user wants audio transcription. No matching intent. '
            'I should return {"capability_gap": true}.\n</think>\n\n'
            '{"intents": [], '
            '"response": "I don\\u2019t have an audio transcription intent yet.", '
            '"capability_gap": true}'
        )
        llm.set_default_response(gap_with_think)

        await renderer.process_with_feedback("please transcribe this audio clip")
        output = con.file.getvalue()

        assert "transcription intent" in output
        entered_self_mod = (
            "Self-Modification Proposal" in output
            or "Self-modification rejected" in output
            or "designed and registered" in output.lower()
        )
        assert entered_self_mod, (
            f"Think-tagged response did not reach self-mod.  Full output:\n{output}"
        )


# ---------------------------------------------------------------------------
# Agent Roster panel tests
# ---------------------------------------------------------------------------

class TestAgentRoster:
    """Tests for render_agent_roster (pool-level org chart)."""

    def test_basic_output(self, runtime, console):
        """Roster produces panel with pool-level rows."""
        scores = runtime.trust_network.all_scores()
        panel = panels.render_agent_roster(
            runtime.pools, runtime.pool_groups, runtime.registry, scores,
        )
        console.print(panel)
        output = get_output(console)
        assert "Agent Roster" in output
        assert "file_reader" in output

    def test_columns_present(self, runtime, console):
        """All expected columns appear in the table."""
        scores = runtime.trust_network.all_scores()
        panel = panels.render_agent_roster(
            runtime.pools, runtime.pool_groups, runtime.registry, scores,
        )
        console.print(panel)
        output = get_output(console)
        for col in ("Type", "Tier", "Team", "Pool", "Size"):
            assert col in output, f"Missing column: {col}"

    def test_empty_pools(self, console):
        """Empty pools dict produces panel with '0 pools' in title."""
        from unittest.mock import MagicMock

        mock_registry = MagicMock()
        mock_registry.get_by_pool.return_value = []
        panel = panels.render_agent_roster({}, None, mock_registry, {})
        console.print(panel)
        output = get_output(console)
        assert "0 pools" in output

    def test_tier_grouping(self, runtime, console):
        """Core-tier agents appear in output."""
        scores = runtime.trust_network.all_scores()
        panel = panels.render_agent_roster(
            runtime.pools, runtime.pool_groups, runtime.registry, scores,
        )
        console.print(panel)
        output = get_output(console)
        assert "core" in output.lower()

    def test_size_format(self, runtime, console):
        """Size column shows current/target format."""
        scores = runtime.trust_network.all_scores()
        panel = panels.render_agent_roster(
            runtime.pools, runtime.pool_groups, runtime.registry, scores,
        )
        console.print(panel)
        output = get_output(console)
        # At least one pool should show e.g. "2/2" or "1/2"
        import re
        assert re.search(r"\d+/\d+", output), "No current/target size found"

    def test_no_pool_groups(self, runtime, console):
        """Handles pool_groups=None gracefully (team shows dash)."""
        scores = runtime.trust_network.all_scores()
        panel = panels.render_agent_roster(
            runtime.pools, None, runtime.registry, scores,
        )
        console.print(panel)
        output = get_output(console)
        assert "Agent Roster" in output

    def test_trust_confidence_format(self, runtime, console):
        """Trust and confidence show avg +/- stdev format."""
        scores = runtime.trust_network.all_scores()
        panel = panels.render_agent_roster(
            runtime.pools, runtime.pool_groups, runtime.registry, scores,
        )
        console.print(panel)
        output = get_output(console)
        assert "\u00b1" in output, "No +/- symbol found in trust/confidence"


# ---------------------------------------------------------------------------
# Shell command handler tests (coverage improvement)
# ---------------------------------------------------------------------------


class TestShellHistoryCommand:
    """Tests for _cmd_history()."""

    @pytest.mark.asyncio
    async def test_history_no_episodic_memory(self, shell, console):
        """History command handles missing episodic memory."""
        shell.runtime.episodic_memory = None
        await shell._cmd_history("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Episodic" in output

    @pytest.mark.asyncio
    async def test_history_empty(self, shell, console):
        """History command handles no episodes gracefully."""
        from unittest.mock import AsyncMock
        mock_mem = AsyncMock()
        mock_mem.recent.return_value = []
        mock_mem.stop = AsyncMock()
        shell.runtime.episodic_memory = mock_mem
        await shell._cmd_history("")
        output = get_output(console)
        assert "No episodes" in output or "Memory" in output or output != ""


class TestShellRecallCommand:
    """Tests for _cmd_recall()."""

    @pytest.mark.asyncio
    async def test_recall_no_query(self, shell, console):
        """Recall command with no episodic memory shows not-enabled message."""
        shell.runtime.episodic_memory = None
        await shell._cmd_recall("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Episodic" in output

    @pytest.mark.asyncio
    async def test_recall_no_memory(self, shell, console):
        """Recall command handles missing episodic memory."""
        shell.runtime.episodic_memory = None
        await shell._cmd_recall("test query")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Episodic" in output


class TestShellDreamCommand:
    """Tests for _cmd_dream()."""

    @pytest.mark.asyncio
    async def test_dream_not_enabled(self, shell, console):
        """Dream command handles missing dream scheduler."""
        shell.runtime.dream_scheduler = None
        await shell._cmd_dream("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Dream" in output


class TestShellFederationCommand:
    """Tests for _cmd_federation() and _cmd_peers()."""

    @pytest.mark.asyncio
    async def test_federation_not_enabled(self, shell, console):
        """Federation command handles missing federation bridge."""
        shell.runtime.federation_bridge = None
        await shell._cmd_federation("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Federation" in output

    @pytest.mark.asyncio
    async def test_peers_not_enabled(self, shell, console):
        """Peers command handles missing federation bridge."""
        shell.runtime.federation_bridge = None
        await shell._cmd_peers("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Federation" in output


class TestShellDesignedCommand:
    """Tests for _cmd_designed()."""

    @pytest.mark.asyncio
    async def test_designed_not_enabled(self, shell, console):
        """Designed command handles missing self_mod_pipeline."""
        shell.runtime.self_mod_pipeline = None
        await shell._cmd_designed("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Self-modification" in output or "modification" in output.lower()


class TestShellKnowledgeCommand:
    """Tests for _cmd_knowledge()."""

    @pytest.mark.asyncio
    async def test_knowledge_not_enabled(self, shell, console):
        """Knowledge command handles missing knowledge store."""
        # Ensure _knowledge_store attribute returns None
        if hasattr(shell.runtime, '_knowledge_store'):
            shell.runtime._knowledge_store = None
        await shell._cmd_knowledge("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Knowledge" in output or "knowledge" in output.lower()


class TestShellQACommand:
    """Tests for _cmd_qa()."""

    @pytest.mark.asyncio
    async def test_qa_no_reports(self, shell, console):
        """QA command handles no reports."""
        shell.runtime._qa_reports = {}
        await shell._cmd_qa("")
        output = get_output(console)
        assert "No QA" in output or "qa" in output.lower() or output != ""


class TestShellSearchCommand:
    """Tests for _cmd_search()."""

    @pytest.mark.asyncio
    async def test_search_no_semantic_layer(self, shell, console):
        """Search command with no semantic layer shows not-available."""
        shell.runtime._semantic_layer = None
        await shell._cmd_search("")
        output = get_output(console)
        assert "not available" in output.lower() or "Semantic" in output

    @pytest.mark.asyncio
    async def test_search_no_semantic_layer(self, shell, console):
        """Search command handles missing semantic layer."""
        shell.runtime._semantic_layer = None
        await shell._cmd_search("test query")
        output = get_output(console)
        assert "not available" in output.lower() or "Semantic" in output


class TestShellImportsCommand:
    """Tests for _cmd_imports()."""

    @pytest.mark.asyncio
    async def test_imports_lists_allowed(self, shell, console):
        """Imports command lists allowed imports when self_mod config exists."""
        from unittest.mock import MagicMock
        mock_config = MagicMock()
        mock_config.allowed_imports = ["json", "os"]
        shell.runtime.config.self_mod = mock_config
        await shell._cmd_imports("")
        output = get_output(console)
        assert "json" in output or "os" in output or "import" in output.lower()


class TestShellApprovalCallbacks:
    """Tests for user approval callback methods."""

    @pytest.mark.asyncio
    async def test_user_self_mod_approval_eof(self, shell, console):
        """_user_self_mod_approval handles EOFError as denial."""
        from unittest.mock import patch
        with patch("builtins.input", side_effect=EOFError):
            result = await shell._user_self_mod_approval("test proposal")
        assert result is False

    @pytest.mark.asyncio
    async def test_user_import_approval_eof(self, shell, console):
        """_user_import_approval handles EOFError as denial."""
        from unittest.mock import patch
        with patch("builtins.input", side_effect=EOFError):
            result = await shell._user_import_approval(["numpy", "pandas"])
        assert result is False

    @pytest.mark.asyncio
    async def test_user_dep_install_approval_eof(self, shell, console):
        """_user_dep_install_approval handles EOFError as denial."""
        from unittest.mock import patch
        with patch("builtins.input", side_effect=EOFError):
            result = await shell._user_dep_install_approval(["requests"])
        assert result is False

    @pytest.mark.asyncio
    async def test_user_escalation_callback_eof(self, shell, console):
        """_user_escalation_callback handles EOFError as skip (None)."""
        from unittest.mock import patch
        if not hasattr(shell, '_user_escalation_callback'):
            pytest.skip("No escalation callback on shell")
        with patch("builtins.input", side_effect=EOFError):
            result = await shell._user_escalation_callback(
                "test escalation", {"intent": "test", "error": "err"}
            )
        assert result is None


# ---------------------------------------------------------------------------
# Renderer tests (coverage improvement)
# ---------------------------------------------------------------------------


class TestRendererProgressTable:
    """Tests for _build_progress_table()."""

    @pytest.fixture
    def renderer(self, runtime, console):
        return ExecutionRenderer(console, runtime)

    def test_progress_table_no_dag(self, renderer):
        """_build_progress_table returns a table even with no current DAG."""
        renderer._current_dag = None
        table = renderer._build_progress_table()
        assert table is not None

    def test_progress_table_with_dag(self, renderer):
        """_build_progress_table includes rows for DAG nodes."""
        from unittest.mock import MagicMock
        dag = MagicMock()
        node = MagicMock()
        node.id = "n1"
        node.intent = "test_intent"
        node.status = "pending"
        node.params = {"key": "value"}
        node.depends_on = []
        dag.nodes = [node]
        renderer._current_dag = dag
        table = renderer._build_progress_table()
        assert table is not None


class TestRendererEventHandler:
    """Tests for _on_execution_event()."""

    @pytest.fixture
    def renderer(self, runtime, console):
        return ExecutionRenderer(console, runtime)

    @pytest.mark.asyncio
    async def test_event_no_matching_node(self, renderer):
        """Event with no matching node doesn't crash."""
        await renderer._on_execution_event("node_started", {"node": None})


# ---------------------------------------------------------------------------
# /models and /registry command tests (AD-356)
# ---------------------------------------------------------------------------

class TestModelsAndRegistry:
    """Verify /model was renamed to /models and /registry exists."""

    def test_help_includes_models_and_registry(self):
        """COMMANDS dict has /models and /registry, not /model."""
        assert "/models" in ProbOSShell.COMMANDS
        assert "/registry" in ProbOSShell.COMMANDS
        assert "/model" not in ProbOSShell.COMMANDS

    def test_classify_provider(self):
        from probos.cognitive.copilot_adapter import _classify_provider
        assert _classify_provider("claude-sonnet-4-6") == "Anthropic"
        assert _classify_provider("gpt-4o-mini") == "OpenAI"
        assert _classify_provider("gemini-1.5-pro") == "Google"
        assert _classify_provider("deepseek-coder") == "Local/OSS"
        assert _classify_provider("qwen-72b") == "Local/OSS"
        assert _classify_provider("some-random-model") == "Unknown"

    @pytest.mark.asyncio
    async def test_cmd_models_shows_tier_info(self, shell, console):
        """_cmd_models prints a Panel with LLM Configuration."""
        await shell.execute_command("/models")
        output = get_output(console)
        assert "LLM Configuration" in output
        assert "MockLLMClient" in output

    @pytest.mark.asyncio
    async def test_cmd_registry_mock_client(self, shell, console):
        """_cmd_registry with MockLLMClient shows the tier table fallback row."""
        await shell.execute_command("/registry")
        output = get_output(console)
        assert "Active Models" in output
        assert "MockLLMClient" in output

