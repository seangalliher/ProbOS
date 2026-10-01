"""Experience layer: panels and the execution renderer.

Split out of the original single test_experience.py so no one file is the
canonical gate's critical path (see docs/development/test-suite-optimization-plan.md, P0.1).
"""

from io import StringIO

import pytest
from rich.console import Console

from probos.cognitive.llm_client import MockLLMClient
from probos.experience import panels
from probos.experience.renderer import ExecutionRenderer

from tests.fixtures.experience_shell import (  # noqa: F401 -- pytest fixtures and helper
    console,
    get_output,
    runtime,
)
from tests.fixtures.runtime_factory import started_runtime


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
# Renderer: force-reflect and self-mod gating
# ---------------------------------------------------------------------------

class TestRendererForceReflect:
    """Tests for force-reflect covering built-in agents."""

    @pytest.fixture
    async def renderer_env(self, tmp_path):
        async with started_runtime(tmp_path, fast_teardown=True) as rt:
            con = Console(file=StringIO(), force_terminal=True, width=120)
            renderer = ExecutionRenderer(con, rt, debug=False)
            yield renderer, rt

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
        async with started_runtime(tmp_path, llm=llm, fast_teardown=True) as rt:
            con = Console(file=StringIO(), force_terminal=True, width=120)
            renderer = ExecutionRenderer(con, rt, debug=False)
            yield llm, rt, renderer, con

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
