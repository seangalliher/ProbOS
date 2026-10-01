"""Experience layer: natural-language input, reflection, episodic memory and attention.

Split out of the original single test_experience.py so no one file is the
canonical gate's critical path (see docs/development/test-suite-optimization-plan.md, P0.1).
"""

from io import StringIO

import pytest
from rich.console import Console

from probos.cognitive.llm_client import MockLLMClient
from probos.experience import panels
from probos.experience.shell import ProbOSShell
from probos.runtime import ProbOSRuntime

from tests.fixtures.experience_shell import (  # noqa: F401 -- pytest fixtures and helper
    console,
    get_output,
    runtime,
    shell,
)


# ---------------------------------------------------------------------------
# Shell NL input
# ---------------------------------------------------------------------------

# BF-323: bumped class-level timeout 60s -> 180s. The pre-existing per-class
# override was tighter than the BF-320 global default (180s) and tripped
# test_nl_unrecognized on GHA runners where full shell boot + NL decomposition
# path takes 70-90s under loaded CI vs ~5s locally. 180s aligns with the
# global and gives consistent treatment.
@pytest.mark.timeout(180)
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
    async def test_render_dag_result_with_reflection(self, console):
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
    async def test_render_dag_result_without_reflection(self, console):
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
        mem = MockEpisodicMemory(relevance_threshold=0.2)
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
        assert len(recent) >= 1  # AD-430c act-store hook may add extras
        # Find the DAG-originated episode (has read_file intent)
        ep = next(e for e in recent if any(o.get("intent") == "read_file" for o in e.outcomes))
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

        results = await rt.dream_adapter.recall_similar("read the file")
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
        # Filter out non-user episodes: SystemQA (AD-154), act-store hook (AD-430c),
        # proactive thoughts + Ward Room posts (AD-430a — proactive loop may fire during test)
        user_episodes = [
            e for e in recent
            if not e.user_input.startswith("[SystemQA]")
            and not e.user_input.startswith("[Action:")
            and not e.user_input.startswith("[Proactive thought")
            and not e.user_input.startswith("[Ward Room")
        ]
        assert len(user_episodes) == 0  # Empty DAGs don't produce episodes


# ---------------------------------------------------------------------------
# Episodic shell command tests
# ---------------------------------------------------------------------------


class TestShellEpisodicCommands:

    @pytest.fixture
    async def ep_shell(self, tmp_path):
        from probos.cognitive.episodic_mock import MockEpisodicMemory

        llm = MockLLMClient()
        mem = MockEpisodicMemory(relevance_threshold=0.2)
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
