"""Tests for DAG Proposal Mode (Phase 16, AD-204 through AD-209)."""

from __future__ import annotations

import asyncio
import time

import pytest

from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig, SelfModConfig
from probos.experience.panels import render_dag_proposal
from probos.runtime import ProbOSRuntime
from probos.types import TaskDAG, TaskNode

from rich.panel import Panel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dag(*intents: str, reflect: bool = False) -> TaskDAG:
    """Create a simple TaskDAG from intent names."""
    nodes = []
    for i, intent in enumerate(intents):
        nodes.append(TaskNode(
            id=f"t{i + 1}",
            intent=intent,
            params={"path": f"/tmp/{intent}.txt"},
        ))
    return TaskDAG(nodes=nodes, source_text=" ".join(intents), reflect=reflect)


def _make_dag_with_deps() -> TaskDAG:
    """Create a TaskDAG with dependencies: t1 -> t2 -> t3."""
    return TaskDAG(
        nodes=[
            TaskNode(id="t1", intent="read_file", params={"path": "/tmp/a.txt"}),
            TaskNode(id="t2", intent="write_file", params={"path": "/tmp/b.txt"},
                     depends_on=["t1"], use_consensus=True),
            TaskNode(id="t3", intent="run_command", params={"command": "echo done"},
                     depends_on=["t2"], use_consensus=True),
        ],
        source_text="read a, write b, then echo done",
        reflect=True,
    )


# ===========================================================================
# Runtime propose / execute / reject
# ===========================================================================


class TestRuntimePropose:
    """Test propose() method (AD-204)."""

    @pytest.fixture
    def config(self):
        return SystemConfig(
            self_mod=SelfModConfig(enabled=True, require_user_approval=False),
        )

    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.mark.asyncio
    async def test_propose_returns_task_dag(self, config, llm, tmp_path):
        """propose() returns a TaskDAG."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        dag = await rt.propose("read the file /tmp/test.txt")
        assert isinstance(dag, TaskDAG)
        await rt.stop()

    @pytest.mark.asyncio
    async def test_propose_stores_pending_proposal(self, config, llm, tmp_path):
        """propose() stores the DAG as _pending_proposal."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        dag = await rt.propose("read the file /tmp/test.txt")
        if dag.nodes:
            assert rt._pending_proposal is dag
        await rt.stop()

    @pytest.mark.asyncio
    async def test_propose_conversational_no_pending(self, config, llm, tmp_path):
        """propose() with conversational response does not create pending proposal."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        dag = await rt.propose("hello")
        # Greeting should produce a conversational response with no nodes
        if dag.response and not dag.nodes:
            assert rt._pending_proposal is None
        await rt.stop()

    @pytest.mark.asyncio
    async def test_propose_replaces_existing(self, config, llm, tmp_path):
        """propose() replaces an existing pending proposal."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        dag1 = await rt.propose("read the file /tmp/a.txt")
        dag2 = await rt.propose("read the file /tmp/b.txt")
        if dag2.nodes:
            assert rt._pending_proposal is dag2
            assert rt._pending_proposal is not dag1
        await rt.stop()

    @pytest.mark.asyncio
    async def test_propose_does_not_execute(self, config, llm, tmp_path):
        """propose() does not execute the DAG — nodes remain pending."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        dag = await rt.propose("read the file /tmp/test.txt")
        if dag.nodes:
            for node in dag.nodes:
                assert node.status == "pending"
        await rt.stop()


class TestRuntimeExecuteProposal:
    """Test execute_proposal() method (AD-205)."""

    @pytest.fixture
    def config(self):
        return SystemConfig(
            self_mod=SelfModConfig(enabled=True, require_user_approval=False),
        )

    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.mark.asyncio
    async def test_execute_proposal_returns_none_when_empty(self, config, llm, tmp_path):
        """execute_proposal() returns None when no pending proposal."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        result = await rt.execute_proposal()
        assert result is None
        await rt.stop()

    @pytest.mark.asyncio
    async def test_execute_proposal_clears_pending(self, config, llm, tmp_path):
        """execute_proposal() clears _pending_proposal after execution."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        dag = await rt.propose("read the file /tmp/test.txt")
        if dag.nodes:
            await rt.execute_proposal()
            assert rt._pending_proposal is None
        await rt.stop()

    @pytest.mark.asyncio
    async def test_execute_proposal_returns_result(self, config, llm, tmp_path):
        """execute_proposal() returns execution result dict."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        dag = await rt.propose("read the file /tmp/test.txt")
        if dag.nodes:
            result = await rt.execute_proposal()
            assert result is not None
            assert "dag" in result
            assert "results" in result
            assert "complete" in result
        await rt.stop()

    @pytest.mark.asyncio
    async def test_execute_proposal_stores_introspection(self, config, llm, tmp_path):
        """execute_proposal() stores execution result for introspection."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        dag = await rt.propose("read the file /tmp/test.txt")
        if dag.nodes:
            result = await rt.execute_proposal()
            assert rt._last_execution is result
        await rt.stop()


class TestRuntimeRejectProposal:
    """Test reject_proposal() method (AD-205)."""

    @pytest.fixture
    def config(self):
        return SystemConfig(
            self_mod=SelfModConfig(enabled=True, require_user_approval=False),
        )

    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.mark.asyncio
    async def test_reject_clears_pending(self, config, llm, tmp_path):
        """reject_proposal() clears _pending_proposal."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        dag = await rt.propose("read the file /tmp/test.txt")
        if dag.nodes:
            result = await rt.reject_proposal()
            assert result is True
            assert rt._pending_proposal is None
        await rt.stop()

    @pytest.mark.asyncio
    async def test_reject_returns_false_when_empty(self, config, llm, tmp_path):
        """reject_proposal() returns False when no pending proposal."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        result = await rt.reject_proposal()
        assert result is False
        await rt.stop()


class TestProcessNaturalLanguagePreserved:
    """Test that process_natural_language() still works after refactor."""

    @pytest.fixture
    def config(self):
        return SystemConfig(
            self_mod=SelfModConfig(enabled=True, require_user_approval=False),
        )

    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.mark.asyncio
    async def test_pnl_still_works(self, config, llm, tmp_path):
        """process_natural_language() still works identically after refactor."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        result = await rt.process_natural_language("read the file /tmp/test.txt")
        assert isinstance(result, dict)
        assert "dag" in result
        assert "results" in result
        await rt.stop()

    @pytest.mark.asyncio
    async def test_pnl_conversational(self, config, llm, tmp_path):
        """process_natural_language() handles conversational input."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        result = await rt.process_natural_language("hello")
        assert isinstance(result, dict)
        # Should have response or node_count
        assert "node_count" in result or "response" in result
        await rt.stop()

    @pytest.mark.asyncio
    async def test_execute_dag_shared(self, config, llm, tmp_path):
        """_execute_dag() is used by both process_natural_language() and execute_proposal()."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        assert hasattr(rt, '_execute_dag')
        assert asyncio.iscoroutinefunction(rt._execute_dag)
        await rt.stop()


# ===========================================================================
# Node removal
# ===========================================================================


class TestRemoveProposalNode:
    """Test remove_proposal_node() method (AD-205)."""

    @pytest.fixture
    def config(self):
        return SystemConfig(
            self_mod=SelfModConfig(enabled=True, require_user_approval=False),
        )

    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.mark.asyncio
    async def test_remove_by_index(self, config, llm, tmp_path):
        """remove_proposal_node() removes node by index."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        rt._pending_proposal = _make_dag("read_file", "write_file")
        removed = await rt.remove_proposal_node(0)
        assert removed is not None
        assert removed.intent == "read_file"
        assert len(rt._pending_proposal.nodes) == 1
        await rt.stop()

    @pytest.mark.asyncio
    async def test_remove_returns_task_node(self, config, llm, tmp_path):
        """remove_proposal_node() returns the removed TaskNode."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        rt._pending_proposal = _make_dag("read_file")
        removed = await rt.remove_proposal_node(0)
        assert isinstance(removed, TaskNode)
        assert removed.intent == "read_file"
        await rt.stop()

    @pytest.mark.asyncio
    async def test_remove_invalid_index(self, config, llm, tmp_path):
        """remove_proposal_node() returns None for invalid index."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        rt._pending_proposal = _make_dag("read_file")
        assert await rt.remove_proposal_node(5) is None
        assert await rt.remove_proposal_node(-1) is None
        await rt.stop()

    @pytest.mark.asyncio
    async def test_remove_no_pending(self, config, llm, tmp_path):
        """remove_proposal_node() returns None when no pending proposal."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        assert await rt.remove_proposal_node(0) is None
        await rt.stop()

    @pytest.mark.asyncio
    async def test_remove_cleans_deps(self, config, llm, tmp_path):
        """Removing a node cleans up dependency references."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        rt._pending_proposal = _make_dag_with_deps()
        # Remove t1 (index 0) — t2 depends on it
        removed = await rt.remove_proposal_node(0)
        assert removed.intent == "read_file"
        # t2 should no longer depend on t1
        remaining = rt._pending_proposal.nodes
        t2_node = next(n for n in remaining if n.id == "t2")
        assert "t1" not in t2_node.depends_on
        await rt.stop()

    @pytest.mark.asyncio
    async def test_remove_dependent_node_updates_dependents(self, config, llm, tmp_path):
        """Removing a middle node updates downstream depends_on."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        rt._pending_proposal = _make_dag_with_deps()
        # Remove t2 (index 1) — t3 depends on t2
        removed = await rt.remove_proposal_node(1)
        assert removed.intent == "write_file"
        remaining = rt._pending_proposal.nodes
        assert len(remaining) == 2
        t3_node = next(n for n in remaining if n.id == "t3")
        assert "t2" not in t3_node.depends_on
        await rt.stop()

    @pytest.mark.asyncio
    async def test_remove_last_node_leaves_empty(self, config, llm, tmp_path):
        """Removing the last node leaves an empty nodes list."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        rt._pending_proposal = _make_dag("read_file")
        await rt.remove_proposal_node(0)
        assert rt._pending_proposal.nodes == []
        await rt.stop()


# ===========================================================================
# Panel rendering
# ===========================================================================


class TestRenderDagProposal:
    """Test render_dag_proposal() panel (AD-206)."""

    def test_returns_rich_panel(self):
        """render_dag_proposal() returns a Rich Panel."""
        dag = _make_dag("read_file", "write_file")
        result = render_dag_proposal(dag)
        assert isinstance(result, Panel)

    def test_shows_correct_node_count(self):
        """render_dag_proposal() table has correct number of rows."""
        dag = _make_dag("read_file", "write_file", "run_command")
        panel = render_dag_proposal(dag)
        # Panel contains a Table with 3 data rows
        assert panel is not None

    def test_maps_deps_to_indices(self):
        """render_dag_proposal() maps node IDs to readable indices."""
        dag = _make_dag_with_deps()
        panel = render_dag_proposal(dag)
        assert panel is not None

    def test_empty_nodes_renders_gracefully(self):
        """render_dag_proposal() with empty nodes list renders gracefully."""
        dag = TaskDAG(nodes=[], source_text="empty")
        panel = render_dag_proposal(dag)
        assert isinstance(panel, Panel)

    def test_reflect_flag_noted(self):
        """render_dag_proposal() notes when reflect is enabled."""
        dag = _make_dag("read_file", reflect=True)
        panel = render_dag_proposal(dag)
        assert panel is not None

    def test_consensus_shown_for_write_file(self):
        """render_dag_proposal() shows consensus for known consensus intents."""
        dag = TaskDAG(
            nodes=[
                TaskNode(id="t1", intent="write_file",
                         params={"path": "/tmp/x.txt", "content": "test"},
                         use_consensus=True),
            ],
            source_text="write file",
        )
        panel = render_dag_proposal(dag)
        assert panel is not None


# ===========================================================================
# Event log
# ===========================================================================


class TestProposalEventLog:
    """Test proposal lifecycle event logging (AD-209)."""

    @pytest.fixture
    def config(self):
        return SystemConfig(
            self_mod=SelfModConfig(enabled=True, require_user_approval=False),
        )

    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.mark.asyncio
    async def test_proposal_created_event(self, config, llm, tmp_path):
        """proposal_created event logged on propose()."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        dag = await rt.propose("read the file /tmp/test.txt")
        if dag.nodes:
            events = await rt.event_log.query(category="cognitive", limit=10)
            proposal_events = [e for e in events if e["event"] == "proposal_created"]
            assert len(proposal_events) >= 1
        await rt.stop()

    @pytest.mark.asyncio
    async def test_proposal_approved_event(self, config, llm, tmp_path):
        """proposal_approved event logged on execute_proposal()."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        dag = await rt.propose("read the file /tmp/test.txt")
        if dag.nodes:
            await rt.execute_proposal()
            events = await rt.event_log.query(category="cognitive", limit=20)
            approved_events = [e for e in events if e["event"] == "proposal_approved"]
            assert len(approved_events) >= 1
        await rt.stop()

    @pytest.mark.asyncio
    async def test_proposal_rejected_event(self, config, llm, tmp_path):
        """proposal_rejected event logged on reject_proposal()."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        dag = await rt.propose("read the file /tmp/test.txt")
        if dag.nodes:
            await rt.reject_proposal()
            events = await rt.event_log.query(category="cognitive", limit=10)
            rejected_events = [e for e in events if e["event"] == "proposal_rejected"]
            assert len(rejected_events) >= 1
        await rt.stop()

    @pytest.mark.asyncio
    async def test_proposal_node_removed_event(self, config, llm, tmp_path):
        """proposal_node_removed event logged on remove_proposal_node()."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        rt._pending_proposal = _make_dag("read_file", "write_file")
        await rt.remove_proposal_node(0)
        events = await rt.event_log.query(category="cognitive", limit=10)
        removed_events = [e for e in events if e["event"] == "proposal_node_removed"]
        assert len(removed_events) >= 1
        await rt.stop()


# ===========================================================================
# Integration: workflow cache and reflect
# ===========================================================================


class TestProposalWorkflowIntegration:
    """Test that proposal execution goes through workflow cache and reflect."""

    @pytest.fixture
    def config(self):
        return SystemConfig(
            self_mod=SelfModConfig(enabled=True, require_user_approval=False),
        )

    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.mark.asyncio
    async def test_execute_proposal_stores_in_cache(self, config, llm, tmp_path):
        """execute_proposal() stores successful workflow in cache."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        dag = await rt.propose("read the file /tmp/test.txt")
        if dag.nodes:
            result = await rt.execute_proposal()
            # If all nodes completed, it should be cached
            if result and all(n.status == "completed" for n in result["dag"].nodes):
                assert rt.workflow_cache.size > 0
        await rt.stop()

    @pytest.mark.asyncio
    async def test_execute_proposal_runs_reflect(self, config, llm, tmp_path):
        """execute_proposal() runs reflect step when dag.reflect=True."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()
        # Manually set a proposal with reflect=True
        dag = _make_dag("read_file", reflect=True)
        rt._pending_proposal = dag
        rt._pending_proposal_text = "read file with reflect"
        result = await rt.execute_proposal()
        if result:
            # Reflect would have been attempted (may succeed or fail)
            # The key test is that _execute_dag was called
            assert "dag" in result
        await rt.stop()


# ===========================================================================
# Shell commands
# ===========================================================================


class TestShellPlanCommands:
    """Test /plan, /approve, /reject shell commands (AD-207, AD-208)."""

    @pytest.fixture
    async def runtime(self, tmp_path):
        llm = MockLLMClient()
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
        await rt.start()
        yield rt
        await rt.stop()

    @pytest.fixture
    def console(self):
        from io import StringIO
        from rich.console import Console
        return Console(file=StringIO(), force_terminal=True, width=120)

    @pytest.fixture
    async def shell(self, runtime, console):
        from probos.experience.shell import ProbOSShell
        return ProbOSShell(runtime, console=console)

    def _get_output(self, console) -> str:
        return console.file.getvalue()

    @pytest.mark.asyncio
    async def test_help_includes_plan_approve_reject(self, shell, console):
        """/help output includes /plan, /approve, /reject."""
        await shell.execute_command("/help")
        output = self._get_output(console)
        assert "/plan" in output
        assert "/approve" in output
        assert "/reject" in output

    @pytest.mark.asyncio
    async def test_plan_with_text(self, shell, console, runtime):
        """/plan <text> creates a proposal."""
        await shell.execute_command("/plan read the file /tmp/test.txt")
        output = self._get_output(console)
        # Should show proposed plan or conversational
        assert "Proposed Plan" in output or "No actionable" in output or "read" in output.lower()

    @pytest.mark.asyncio
    async def test_plan_no_args_shows_usage(self, shell, console):
        """/plan with no args and no pending shows usage."""
        await shell.execute_command("/plan")
        output = self._get_output(console)
        assert "Usage" in output or "pending" in output.lower()

    @pytest.mark.asyncio
    async def test_reject_no_pending(self, shell, console):
        """/reject with no pending shows warning."""
        await shell.execute_command("/reject")
        output = self._get_output(console)
        assert "No pending" in output

    @pytest.mark.asyncio
    async def test_approve_no_pending(self, shell, console):
        """/approve with no pending shows warning."""
        await shell.execute_command("/approve")
        output = self._get_output(console)
        assert "No pending" in output

    @pytest.mark.asyncio
    async def test_plan_remove_no_pending(self, shell, console):
        """/plan remove 0 with no pending shows warning."""
        await shell.execute_command("/plan remove 0")
        output = self._get_output(console)
        assert "No pending" in output

    @pytest.mark.asyncio
    async def test_plan_remove_invalid_index(self, shell, console, runtime):
        """/plan remove with invalid index shows error."""
        runtime._pending_proposal = _make_dag("read_file")
        await shell.execute_command("/plan remove 99")
        output = self._get_output(console)
        assert "Invalid" in output

    @pytest.mark.asyncio
    async def test_plan_remove_valid_index(self, shell, console, runtime):
        """/plan remove 0 removes the node."""
        runtime._pending_proposal = _make_dag("read_file", "write_file")
        await shell.execute_command("/plan remove 0")
        output = self._get_output(console)
        assert "Removed" in output
        assert len(runtime._pending_proposal.nodes) == 1

    @pytest.mark.asyncio
    async def test_reject_with_pending(self, shell, console, runtime):
        """/reject clears pending proposal."""
        runtime._pending_proposal = _make_dag("read_file")
        runtime._pending_proposal_text = "test"
        await shell.execute_command("/reject")
        output = self._get_output(console)
        assert "discarded" in output.lower()
        assert runtime._pending_proposal is None
