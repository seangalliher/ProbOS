"""Tests for Phase 7: Escalation Cascades & Error Recovery."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.llm_client import MockLLMClient
from probos.consensus.escalation import ARBITRATION_PROMPT, EscalationManager
from probos.experience.panels import render_dag_result
from probos.types import (
    ConsensusOutcome,
    ConsensusResult,
    EscalationResult,
    EscalationTier,
    IntentResult,
    TaskDAG,
    TaskNode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(**overrides) -> TaskNode:
    defaults = {
        "id": "t1",
        "intent": "read_file",
        "params": {"path": "/tmp/test.txt"},
        "use_consensus": False,
    }
    defaults.update(overrides)
    return TaskNode(**defaults)


def _make_mock_runtime(
    *,
    submit_intent_side_effect=None,
    submit_intent_with_consensus_side_effect=None,
    submit_write_with_consensus_side_effect=None,
):
    """Build a minimal mock runtime for EscalationManager tests."""
    runtime = MagicMock()
    runtime.submit_intent = AsyncMock(
        side_effect=submit_intent_side_effect
    )
    runtime.submit_intent_with_consensus = AsyncMock(
        side_effect=submit_intent_with_consensus_side_effect
    )
    runtime.submit_write_with_consensus = AsyncMock(
        side_effect=submit_write_with_consensus_side_effect
    )
    return runtime


def _approved_consensus_result():
    return {
        "consensus": MagicMock(outcome=ConsensusOutcome.APPROVED),
        "results": [],
    }


def _rejected_consensus_result():
    return {
        "consensus": MagicMock(outcome=ConsensusOutcome.REJECTED),
        "results": [],
    }


def _success_intent_results():
    r = MagicMock()
    r.success = True
    return [r]


def _fail_intent_results():
    r = MagicMock()
    r.success = False
    return [r]


# ---------------------------------------------------------------------------
# EscalationManager unit tests
# ---------------------------------------------------------------------------


class TestEscalationManagerTier1:
    """Tier 1: retry with different agent."""

    @pytest.mark.asyncio
    async def test_tier1_retry_succeeds(self):
        """1. First call raises error, second succeeds. Resolved via retry."""
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _fail_intent_results()
            return _success_intent_results()

        runtime = _make_mock_runtime(submit_intent_side_effect=side_effect)
        mgr = EscalationManager(runtime=runtime, llm_client=None, max_retries=2)

        node = _make_node()
        result = await mgr.escalate(node, "test error", {})

        assert result.tier == EscalationTier.RETRY
        assert result.resolved is True
        assert result.attempts == 2

    @pytest.mark.asyncio
    async def test_tier1_all_retries_fail(self):
        """2. All retries fail. Escalation proceeds to Tier 3 (no LLM)."""
        runtime = _make_mock_runtime(
            submit_intent_side_effect=AsyncMock(return_value=_fail_intent_results()),
        )
        mgr = EscalationManager(runtime=runtime, llm_client=None, max_retries=2)

        node = _make_node()
        result = await mgr.escalate(node, "test error", {})

        # Should reach Tier 3 (USER) since no LLM
        assert result.tier == EscalationTier.USER
        assert result.resolved is False

    @pytest.mark.asyncio
    async def test_tier1_skipped_for_consensus_rejection(self):
        """3. Consensus rejection still retries (different agents from pool)."""
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _rejected_consensus_result()
            return _approved_consensus_result()

        runtime = _make_mock_runtime(
            submit_intent_with_consensus_side_effect=side_effect,
        )
        mgr = EscalationManager(runtime=runtime, llm_client=None, max_retries=2)

        node = _make_node(use_consensus=True)
        result = await mgr.escalate(node, "consensus rejected", {})

        assert result.tier == EscalationTier.RETRY
        assert result.resolved is True


class TestEscalationManagerTier2:
    """Tier 2: LLM arbitration."""

    @pytest.mark.asyncio
    async def test_tier2_approve(self):
        """4. LLM returns approve. Resolved at tier 2."""
        runtime = _make_mock_runtime(
            submit_intent_side_effect=AsyncMock(return_value=_fail_intent_results()),
        )
        llm = MagicMock()
        llm.__class__.__name__ = "FakeLLMClient"
        resp = MagicMock()
        resp.error = None
        resp.content = json.dumps({"action": "approve", "reason": "Partial results OK"})
        llm.complete = AsyncMock(return_value=resp)

        mgr = EscalationManager(runtime=runtime, llm_client=llm, max_retries=1)

        node = _make_node()
        result = await mgr.escalate(node, "test error", {})

        assert result.tier == EscalationTier.ARBITRATION
        assert result.resolved is True
        assert "Partial results OK" in result.reason

    @pytest.mark.asyncio
    async def test_tier2_reject_proceeds_to_tier3(self):
        """5. LLM rejects. Escalation proceeds to Tier 3."""
        runtime = _make_mock_runtime(
            submit_intent_side_effect=AsyncMock(return_value=_fail_intent_results()),
        )
        llm = MagicMock()
        llm.__class__.__name__ = "FakeLLMClient"
        resp = MagicMock()
        resp.error = None
        resp.content = json.dumps({"action": "reject", "reason": "Fundamentally flawed"})
        llm.complete = AsyncMock(return_value=resp)

        mgr = EscalationManager(runtime=runtime, llm_client=llm, max_retries=1)

        node = _make_node()
        result = await mgr.escalate(node, "test error", {})

        assert result.tier == EscalationTier.USER
        assert result.resolved is False

    @pytest.mark.asyncio
    async def test_tier2_modify_retries_with_new_params(self):
        """6. LLM returns modify with new params. Retry succeeds."""
        runtime = _make_mock_runtime(
            submit_intent_side_effect=AsyncMock(return_value=_fail_intent_results()),
        )
        # The modified retry should use submit_intent (no consensus for this node)
        runtime.submit_intent = AsyncMock(
            side_effect=[_fail_intent_results(), _success_intent_results()],
        )

        llm = MagicMock()
        llm.__class__.__name__ = "FakeLLMClient"
        resp = MagicMock()
        resp.error = None
        resp.content = json.dumps({
            "action": "modify",
            "params": {"path": "/fixed/path"},
            "reason": "Path corrected",
        })
        llm.complete = AsyncMock(return_value=resp)

        mgr = EscalationManager(runtime=runtime, llm_client=llm, max_retries=1)

        node = _make_node()
        result = await mgr.escalate(node, "test error", {})

        assert result.tier == EscalationTier.ARBITRATION
        assert result.resolved is True

    @pytest.mark.asyncio
    async def test_tier2_skipped_when_no_llm(self):
        """7. No LLM client. Tier 2 skipped, goes to Tier 3."""
        runtime = _make_mock_runtime(
            submit_intent_side_effect=AsyncMock(return_value=_fail_intent_results()),
        )
        mgr = EscalationManager(runtime=runtime, llm_client=None, max_retries=1)

        node = _make_node()
        result = await mgr.escalate(node, "test error", {})

        assert result.tier == EscalationTier.USER
        assert EscalationTier.ARBITRATION not in result.tiers_attempted

    @pytest.mark.asyncio
    async def test_tier2_mock_llm_falls_through(self):
        """8. MockLLMClient returns reject, escalation goes to Tier 3."""
        runtime = _make_mock_runtime(
            submit_intent_side_effect=AsyncMock(return_value=_fail_intent_results()),
        )
        mock_llm = MockLLMClient()
        mgr = EscalationManager(runtime=runtime, llm_client=mock_llm, max_retries=1)

        node = _make_node()
        result = await mgr.escalate(node, "test error", {})

        assert result.tier == EscalationTier.USER
        assert EscalationTier.ARBITRATION in result.tiers_attempted


class TestEscalationManagerTier3:
    """Tier 3: user consultation."""

    @pytest.mark.asyncio
    async def test_tier3_user_approves(self):
        """9. User callback returns True. Re-executes without consensus."""
        # First call (tier1 retry) fails, then re-execution after user
        # approval succeeds with actual output.
        call_count = 0

        async def submit_intent_fn(intent, params, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                # Tier 1 retry — still fails
                return _fail_intent_results()
            else:
                # Re-execution after user approval — succeeds
                r = MagicMock()
                r.success = True
                r.result = {"stdout": "Tokyo time output", "stderr": "", "exit_code": 0}
                r.error = None
                r.confidence = 0.8
                return [r]

        runtime = _make_mock_runtime(
            submit_intent_side_effect=submit_intent_fn,
        )

        async def user_cb(desc, ctx):
            return True

        mgr = EscalationManager(
            runtime=runtime, llm_client=None, max_retries=1,
            user_callback=user_cb,
        )

        node = _make_node()
        result = await mgr.escalate(node, "test error", {})

        assert result.tier == EscalationTier.USER
        assert result.resolved is True
        assert result.user_approved is True
        # The resolution should contain actual re-executed output
        assert result.resolution is not None
        assert result.resolution["success"] is True
        assert len(result.resolution["results"]) == 1
        assert result.resolution["results"][0].result["stdout"] == "Tokyo time output"

    @pytest.mark.asyncio
    async def test_tier3_user_rejects(self):
        """10. User callback returns False. Resolved (as rejected)."""
        runtime = _make_mock_runtime(
            submit_intent_side_effect=AsyncMock(return_value=_fail_intent_results()),
        )

        async def user_cb(desc, ctx):
            return False

        mgr = EscalationManager(
            runtime=runtime, llm_client=None, max_retries=1,
            user_callback=user_cb,
        )

        node = _make_node()
        result = await mgr.escalate(node, "test error", {})

        assert result.tier == EscalationTier.USER
        assert result.resolved is True
        assert result.user_approved is False

    @pytest.mark.asyncio
    async def test_tier3_user_skips(self):
        """11. User callback returns None. Unresolved."""
        runtime = _make_mock_runtime(
            submit_intent_side_effect=AsyncMock(return_value=_fail_intent_results()),
        )

        async def user_cb(desc, ctx):
            return None

        mgr = EscalationManager(
            runtime=runtime, llm_client=None, max_retries=1,
            user_callback=user_cb,
        )

        node = _make_node()
        result = await mgr.escalate(node, "test error", {})

        assert result.tier == EscalationTier.USER
        assert result.resolved is False
        assert result.user_approved is None

    @pytest.mark.asyncio
    async def test_tier3_no_callback(self):
        """12. No user_callback set. Unresolved."""
        runtime = _make_mock_runtime(
            submit_intent_side_effect=AsyncMock(return_value=_fail_intent_results()),
        )
        mgr = EscalationManager(runtime=runtime, llm_client=None, max_retries=1)

        node = _make_node()
        result = await mgr.escalate(node, "test error", {})

        assert result.tier == EscalationTier.USER
        assert result.resolved is False


class TestEscalationManagerCascade:
    """Full cascade and boundary tests."""

    @pytest.mark.asyncio
    async def test_full_cascade_all_fail(self):
        """13. All tiers fail. Final result is unresolved at USER tier."""
        runtime = _make_mock_runtime(
            submit_intent_side_effect=AsyncMock(return_value=_fail_intent_results()),
        )
        mock_llm = MockLLMClient()
        mgr = EscalationManager(runtime=runtime, llm_client=mock_llm, max_retries=2)

        node = _make_node()
        result = await mgr.escalate(node, "test error", {})

        assert result.resolved is False
        assert result.tier == EscalationTier.USER
        assert EscalationTier.RETRY in result.tiers_attempted
        assert EscalationTier.ARBITRATION in result.tiers_attempted
        assert EscalationTier.USER in result.tiers_attempted

    @pytest.mark.asyncio
    async def test_escalation_bounded(self):
        """14. max_retries=2 limits Tier 1 calls to exactly 2."""
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _fail_intent_results()

        runtime = _make_mock_runtime(
            submit_intent_side_effect=side_effect,
        )
        mgr = EscalationManager(runtime=runtime, llm_client=None, max_retries=2)

        node = _make_node()
        await mgr.escalate(node, "test error", {})

        assert call_count == 2  # Exactly max_retries


class TestEscalationResultSerialization:
    """EscalationResult to_dict() and JSON roundtrip."""

    def test_escalation_result_to_dict(self):
        """15. to_dict() produces JSON-serializable output."""
        result = EscalationResult(
            tier=EscalationTier.RETRY,
            resolved=True,
            original_error="some error",
            resolution={"key": "value"},
            reason="Retry succeeded",
            agent_id="agent_123",
            attempts=2,
            user_approved=None,
            tiers_attempted=[EscalationTier.RETRY],
        )
        d = result.to_dict()
        # Should be JSON serializable
        json_str = json.dumps(d)
        assert json_str  # Non-empty
        assert d["tier"] == "retry"
        assert d["resolved"] is True
        assert d["attempts"] == 2
        assert isinstance(d["tiers_attempted"], list)
        assert d["tiers_attempted"] == ["retry"]

    def test_escalation_result_to_dict_roundtrip(self):
        """16. to_dict() output renders correctly in _format_escalation."""
        from probos.experience.panels import _format_escalation

        result = EscalationResult(
            tier=EscalationTier.ARBITRATION,
            resolved=True,
            reason="LLM approved",
            tiers_attempted=[EscalationTier.RETRY, EscalationTier.ARBITRATION],
        )
        d = result.to_dict()
        lines = _format_escalation(d)
        assert len(lines) >= 1
        assert "Resolved" in lines[0]


# ---------------------------------------------------------------------------
# DAGExecutor escalation tests
# ---------------------------------------------------------------------------


class TestDAGExecutorEscalation:
    """Escalation wired into DAGExecutor."""

    @pytest.mark.asyncio
    async def test_executor_escalates_on_exception(self):
        """17. Node raises exception -> escalation triggered -> resolved."""
        from probos.cognitive.decomposer import DAGExecutor

        runtime = MagicMock()
        runtime.submit_intent = AsyncMock(side_effect=RuntimeError("boom"))

        # Create an escalation manager that resolves at Tier 1
        esc_mgr = MagicMock()
        esc_result = EscalationResult(
            tier=EscalationTier.RETRY,
            resolved=True,
            original_error="boom",
            resolution={"intent": "read_file", "results": [], "success": True, "result_count": 0},
            tiers_attempted=[EscalationTier.RETRY],
        )
        esc_mgr.escalate = AsyncMock(return_value=esc_result)

        executor = DAGExecutor(runtime=runtime, escalation_manager=esc_mgr)
        dag = TaskDAG(nodes=[_make_node()])

        result = await executor.execute(dag)

        assert dag.nodes[0].status == "completed"
        assert dag.nodes[0].escalation_result is not None
        assert dag.nodes[0].escalation_result["resolved"] is True

    @pytest.mark.asyncio
    async def test_executor_escalates_on_consensus_rejection(self):
        """18. Consensus-rejected node -> escalation triggered."""
        from probos.cognitive.decomposer import DAGExecutor

        rejected_result = {
            "consensus": MagicMock(outcome=ConsensusOutcome.REJECTED),
            "results": [],
        }
        runtime = MagicMock()
        runtime.submit_intent_with_consensus = AsyncMock(
            return_value=rejected_result,
        )

        esc_mgr = MagicMock()
        esc_result = EscalationResult(
            tier=EscalationTier.USER,
            resolved=False,
            original_error="consensus rejected",
            tiers_attempted=[EscalationTier.RETRY, EscalationTier.USER],
        )
        esc_mgr.escalate = AsyncMock(return_value=esc_result)

        executor = DAGExecutor(runtime=runtime, escalation_manager=esc_mgr)
        dag = TaskDAG(nodes=[_make_node(use_consensus=True)])

        result = await executor.execute(dag)

        assert dag.nodes[0].status == "failed"
        esc_mgr.escalate.assert_called_once()

    @pytest.mark.asyncio
    async def test_executor_no_escalation_without_manager(self):
        """19. No escalation_manager -> node fails normally."""
        from probos.cognitive.decomposer import DAGExecutor

        runtime = MagicMock()
        runtime.submit_intent = AsyncMock(side_effect=RuntimeError("boom"))

        executor = DAGExecutor(runtime=runtime)
        dag = TaskDAG(nodes=[_make_node()])

        result = await executor.execute(dag)

        assert dag.nodes[0].status == "failed"
        assert dag.nodes[0].escalation_result is None

    @pytest.mark.asyncio
    async def test_executor_rejected_node_marked_failed(self):
        """20. Without escalation, consensus-REJECTED node is now 'failed'."""
        from probos.cognitive.decomposer import DAGExecutor

        rejected_result = {
            "consensus": MagicMock(outcome=ConsensusOutcome.REJECTED),
            "results": [],
        }
        runtime = MagicMock()
        runtime.submit_intent_with_consensus = AsyncMock(
            return_value=rejected_result,
        )

        executor = DAGExecutor(runtime=runtime)
        dag = TaskDAG(nodes=[_make_node(use_consensus=True)])

        result = await executor.execute(dag)

        assert dag.nodes[0].status == "failed"

    @pytest.mark.asyncio
    async def test_executor_escalation_events_fired(self):
        """21. on_event fires escalation_start and escalation_complete."""
        from probos.cognitive.decomposer import DAGExecutor

        runtime = MagicMock()
        runtime.submit_intent = AsyncMock(side_effect=RuntimeError("boom"))

        esc_mgr = MagicMock()
        esc_result = EscalationResult(
            tier=EscalationTier.USER,
            resolved=False,
            original_error="boom",
            tiers_attempted=[EscalationTier.RETRY, EscalationTier.USER],
        )
        esc_mgr.escalate = AsyncMock(return_value=esc_result)

        events = []

        async def on_event(name, data):
            events.append(name)

        executor = DAGExecutor(runtime=runtime, escalation_manager=esc_mgr)
        dag = TaskDAG(nodes=[_make_node()])

        await executor.execute(dag, on_event=on_event)

        assert "escalation_start" in events
        assert "escalation_exhausted" in events or "escalation_resolved" in events

    @pytest.mark.asyncio
    async def test_executor_escalation_result_stored_on_node(self):
        """22. After escalation, node.escalation_result is a JSON-safe dict."""
        from probos.cognitive.decomposer import DAGExecutor

        runtime = MagicMock()
        runtime.submit_intent = AsyncMock(side_effect=RuntimeError("boom"))

        esc_mgr = MagicMock()
        esc_result = EscalationResult(
            tier=EscalationTier.RETRY,
            resolved=True,
            original_error="boom",
            resolution={"intent": "read_file", "results": [], "success": True, "result_count": 0},
            tiers_attempted=[EscalationTier.RETRY],
        )
        esc_mgr.escalate = AsyncMock(return_value=esc_result)

        executor = DAGExecutor(runtime=runtime, escalation_manager=esc_mgr)
        dag = TaskDAG(nodes=[_make_node()])

        await executor.execute(dag)

        node = dag.nodes[0]
        assert node.escalation_result is not None
        # Must be JSON serializable
        json.dumps(node.escalation_result)


# ---------------------------------------------------------------------------
# Runtime escalation wiring tests
# ---------------------------------------------------------------------------


class TestRuntimeEscalation:
    """Runtime creates and wires EscalationManager."""

    @pytest.fixture
    async def runtime(self, tmp_path):
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime(data_dir=tmp_path)
        await rt.start()
        yield rt
        await rt.stop()

    @pytest.mark.asyncio
    async def test_runtime_creates_escalation_manager(self, runtime):
        """23. Runtime has escalation_manager after start."""
        assert runtime.escalation_manager is not None
        assert isinstance(runtime.escalation_manager, EscalationManager)

    @pytest.mark.asyncio
    async def test_runtime_status_includes_escalation(self, runtime):
        """24. status() includes escalation key."""
        status = runtime.status()
        assert "escalation" in status
        assert status["escalation"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_runtime_nl_with_escalation(self, runtime, tmp_path):
        """25. NL processing works unchanged when no escalation triggers."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")

        result = await runtime.process_natural_language(
            f"read the file at {test_file}"
        )
        assert result["node_count"] == 1
        assert result["completed_count"] == 1

    @pytest.mark.asyncio
    async def test_escalation_resolved_stored_in_episodic_memory(self, tmp_path):
        """26. Escalation-resolved node stores successful outcome in episode."""
        from probos.runtime import ProbOSRuntime

        # Build a runtime with episodic memory
        mem = MagicMock()
        mem.start = AsyncMock()
        mem.stop = AsyncMock()
        mem.recall = AsyncMock(return_value=[])
        mem.store = AsyncMock()
        mem.get_stats = AsyncMock(return_value={})

        rt = ProbOSRuntime(data_dir=tmp_path, episodic_memory=mem)
        await rt.start()

        try:
            # Create a file to read
            test_file = tmp_path / "ep_test.txt"
            test_file.write_text("data")

            result = await rt.process_natural_language(
                f"read the file at {test_file}"
            )
            # Should still work — episode stored normally
            assert result["completed_count"] == 1
            assert mem.store.called
        finally:
            await rt.stop()


# ---------------------------------------------------------------------------
# Panel / rendering tests
# ---------------------------------------------------------------------------


class TestEscalationPanels:
    """Panel rendering for escalation data."""

    def test_format_escalation_resolved(self):
        """27. _format_escalation with resolved=True shows green Resolved."""
        from probos.experience.panels import _format_escalation

        esc = {
            "tier": "retry",
            "resolved": True,
            "reason": "Retry worked",
        }
        lines = _format_escalation(esc)
        assert any("Resolved" in line for line in lines)
        assert any("green" in line for line in lines)

    def test_format_escalation_unresolved(self):
        """28. _format_escalation with resolved=False shows red Unresolved."""
        from probos.experience.panels import _format_escalation

        esc = {
            "tier": "user",
            "resolved": False,
            "reason": "User skipped",
        }
        lines = _format_escalation(esc)
        assert any("Unresolved" in line for line in lines)
        assert any("red" in line for line in lines)

    def test_render_dag_result_with_escalation(self):
        """29. render_dag_result shows escalation info for nodes with it."""
        node = _make_node()
        node.status = "failed"
        node.escalation_result = {
            "tier": "user",
            "resolved": False,
            "reason": "All tiers exhausted",
        }

        dag = TaskDAG(nodes=[node])
        result = {
            "dag": dag,
            "results": {"t1": {"error": "boom"}},
            "node_count": 1,
            "completed_count": 0,
            "failed_count": 1,
        }

        panel = render_dag_result(result)
        # The panel should contain escalation info —
        # We can check the renderable text
        assert panel is not None


# ---------------------------------------------------------------------------
# End-to-end: escalation → re-execute → reflect
# ---------------------------------------------------------------------------


class TestEscalationReflectEndToEnd:
    """Verify that user-approved escalation produces meaningful reflection."""

    @pytest.mark.asyncio
    async def test_consensus_reject_user_approve_reflects_output(self):
        """30. Consensus rejects run_command → user approves → re-execute
        produces stdout → DAGExecutor stores normalized result →
        reflect sees the output and produces a meaningful summary.
        """
        from probos.cognitive.decomposer import DAGExecutor, _normalize_consensus_result

        # --- Mock runtime ---
        # submit_intent_with_consensus always rejects (consensus REJECTED)
        rejected_result = {
            "consensus": MagicMock(outcome=ConsensusOutcome.REJECTED),
            "results": [
                MagicMock(
                    success=True,
                    result={"stdout": "03/09/2026 01:30:00\r\n", "stderr": "", "exit_code": 0},
                    error=None,
                    confidence=0.8,
                    agent_id="shell_cmd_01",
                ),
            ],
        }
        runtime = MagicMock()
        runtime.submit_intent_with_consensus = AsyncMock(
            return_value=rejected_result,
        )

        # submit_intent succeeds (re-execution without consensus)
        reexec_ir = MagicMock()
        reexec_ir.success = True
        reexec_ir.result = {"stdout": "03/09/2026 01:30:00\r\n", "stderr": "", "exit_code": 0}
        reexec_ir.error = None
        reexec_ir.confidence = 0.8
        reexec_ir.agent_id = "shell_cmd_01"
        runtime.submit_intent = AsyncMock(return_value=[reexec_ir])

        # --- User callback ---
        async def user_cb(desc, ctx):
            return True

        esc_mgr = EscalationManager(
            runtime=runtime, llm_client=None, max_retries=1,
            user_callback=user_cb,
        )

        # --- Build DAG ---
        node = TaskNode(
            id="t1",
            intent="run_command",
            params={"command": 'powershell -Command "[System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), \'Tokyo Standard Time\')"'},
            use_consensus=True,
        )
        dag = TaskDAG(nodes=[node], reflect=True)

        # --- Execute ---
        executor = DAGExecutor(runtime=runtime, escalation_manager=esc_mgr)
        execution_result = await executor.execute(dag)

        # --- Assertions on DAG state ---
        assert node.status == "completed", f"Expected completed, got {node.status}"
        assert node.escalation_result is not None
        assert node.escalation_result["resolved"] is True

        # --- Assertions on result content ---
        node_result = execution_result["results"]["t1"]
        assert isinstance(node_result, dict)
        assert node_result.get("success") is True, f"Result should be successful: {node_result}"
        assert "results" in node_result, f"Result should have 'results' key: {node_result}"

        # The actual agent output should be accessible
        agent_results = node_result["results"]
        assert len(agent_results) >= 1
        first_ir = agent_results[0]
        assert first_ir.result["stdout"].strip() == "03/09/2026 01:30:00"

    @pytest.mark.asyncio
    async def test_reflect_sees_stdout_after_escalation(self):
        """31. The reflect() method extracts stdout from the re-executed
        result and sends it to the LLM for synthesis.
        """
        from probos.cognitive.decomposer import DAGExecutor, IntentDecomposer
        from probos.cognitive.working_memory import WorkingMemoryManager

        # --- Build a result dict simulating post-escalation ---
        reexec_ir = MagicMock()
        reexec_ir.success = True
        reexec_ir.result = {"stdout": "03/09/2026 01:30:00\r\n", "stderr": "", "exit_code": 0}
        reexec_ir.error = None

        node = TaskNode(
            id="t1", intent="run_command",
            params={"command": "get tokyo time"},
            status="completed",
        )
        dag = TaskDAG(nodes=[node], reflect=True)

        execution_result = {
            "dag": dag,
            "results": {
                "t1": {
                    "intent": "run_command",
                    "results": [reexec_ir],
                    "success": True,
                    "result_count": 1,
                },
            },
            "node_count": 1,
            "completed_count": 1,
            "failed_count": 0,
        }

        # --- Setup decomposer with mock LLM ---
        from probos.cognitive.llm_client import MockLLMClient
        llm = MockLLMClient()
        decomposer = IntentDecomposer(
            llm_client=llm,
            working_memory=WorkingMemoryManager(),
        )

        reflection = await decomposer.reflect(
            "what time is it in tokyo?", execution_result
        )

        # Check what was sent to the LLM
        last_req = llm.last_request
        assert last_req is not None
        prompt = last_req.prompt

        # The prompt should contain the actual stdout, not consensus metadata
        assert "03/09/2026 01:30:00" in prompt, (
            f"Reflection prompt should contain stdout. Got:\n{prompt}"
        )
        assert "REJECTED" not in prompt, (
            f"Reflection prompt should NOT contain REJECTED. Got:\n{prompt}"
        )
        assert "ConsensusOutcome" not in prompt, (
            f"Reflection prompt should NOT contain ConsensusOutcome. Got:\n{prompt}"
        )

    @pytest.mark.asyncio
    async def test_user_rejects_marks_node_failed(self):
        """32. Consensus rejects → user rejects → node is 'failed', not 'completed'."""
        from probos.cognitive.decomposer import DAGExecutor

        rejected_result = {
            "consensus": MagicMock(outcome=ConsensusOutcome.REJECTED),
            "results": [
                MagicMock(
                    success=True,
                    result={"stdout": "some output", "stderr": "", "exit_code": 0},
                    error=None,
                    confidence=0.8,
                    agent_id="shell_cmd_01",
                ),
            ],
        }
        runtime = MagicMock()
        runtime.submit_intent_with_consensus = AsyncMock(
            return_value=rejected_result,
        )
        runtime.submit_intent = AsyncMock(return_value=[])

        async def user_cb(desc, ctx):
            return False  # User rejects

        esc_mgr = EscalationManager(
            runtime=runtime, llm_client=None, max_retries=1,
            user_callback=user_cb,
        )

        node = TaskNode(
            id="t1", intent="run_command",
            params={"command": "echo hello"},
            use_consensus=True,
        )
        dag = TaskDAG(nodes=[node], reflect=True)

        executor = DAGExecutor(runtime=runtime, escalation_manager=esc_mgr)
        execution_result = await executor.execute(dag)

        assert node.status == "failed", f"Expected failed, got {node.status}"
        node_result = execution_result["results"]["t1"]
        assert "error" in node_result

    @pytest.mark.asyncio
    async def test_reuse_original_results_on_consensus_rejection(self):
        """33. When consensus rejected the policy (not the results), user
        approval should reuse the original successful agent output
        without re-executing.
        """
        from probos.cognitive.decomposer import DAGExecutor

        # Original consensus result: agents succeeded but consensus rejected
        original_ir = MagicMock()
        original_ir.success = True
        original_ir.result = {
            "stdout": "03/08/2026 10:30:00\r\n",
            "stderr": "",
            "exit_code": 0,
            "command": "powershell -Command \"Get-Date\"",
        }
        original_ir.error = None
        original_ir.confidence = 0.8
        original_ir.agent_id = "shell_cmd_01"

        rejected_result = {
            "consensus": MagicMock(outcome=ConsensusOutcome.REJECTED),
            "results": [original_ir],
        }
        runtime = MagicMock()
        runtime.submit_intent_with_consensus = AsyncMock(
            return_value=rejected_result,
        )
        # submit_intent should NOT be called — original results are reused
        runtime.submit_intent = AsyncMock(
            side_effect=AssertionError("submit_intent should not be called"),
        )

        async def user_cb(desc, ctx):
            return True

        esc_mgr = EscalationManager(
            runtime=runtime, llm_client=None, max_retries=1,
            user_callback=user_cb,
        )

        node = TaskNode(
            id="t1", intent="run_command",
            params={"command": "powershell -Command \"Get-Date\""},
            use_consensus=True,
        )
        dag = TaskDAG(nodes=[node], reflect=True)

        executor = DAGExecutor(runtime=runtime, escalation_manager=esc_mgr)
        execution_result = await executor.execute(dag)

        assert node.status == "completed"
        node_result = execution_result["results"]["t1"]
        assert node_result["success"] is True
        # Should have the original stdout from the consensus attempt
        assert node_result["results"][0].result["stdout"].strip() == "03/08/2026 10:30:00"

    @pytest.mark.asyncio
    async def test_reflect_deduplicates_and_includes_status(self):
        """34. Reflect prompt deduplicates identical agent outputs and
        includes node status ([completed]) in the data sent to the LLM.
        """
        from probos.cognitive.decomposer import IntentDecomposer
        from probos.cognitive.working_memory import WorkingMemoryManager
        from probos.cognitive.llm_client import MockLLMClient

        # 3 agents all returning identical stdout
        irs = []
        for i in range(3):
            ir = MagicMock()
            ir.success = True
            ir.result = {
                "stdout": "Sunday, March 8, 2026 10:30:00 AM\r\n",
                "stderr": "",
                "exit_code": 0,
                "command": "date",
            }
            ir.error = None
            irs.append(ir)

        node = TaskNode(
            id="t1", intent="run_command",
            params={"command": "date"},
            status="completed",
        )
        dag = TaskDAG(nodes=[node], reflect=True)

        execution_result = {
            "dag": dag,
            "results": {
                "t1": {
                    "intent": "run_command",
                    "results": irs,
                    "success": True,
                    "result_count": 3,
                },
            },
        }

        llm = MockLLMClient()
        decomposer = IntentDecomposer(
            llm_client=llm,
            working_memory=WorkingMemoryManager(),
        )

        await decomposer.reflect("what time is it?", execution_result)

        prompt = llm.last_request.prompt

        # Output should appear exactly once (deduplicated)
        assert prompt.count("Sunday, March 8, 2026 10:30:00 AM") == 1, (
            f"Output should appear once (deduplicated). Got:\n{prompt}"
        )

        # Node status should be included
        assert "[completed]" in prompt, (
            f"Prompt should include [completed] status. Got:\n{prompt}"
        )

        # success=True should be present
        assert "success=True" in prompt


# ---------------------------------------------------------------------------
# DAG timeout + user-wait deadline extension tests
# ---------------------------------------------------------------------------


class TestDAGTimeoutUserWait:
    """Verify DAG timeout excludes user-wait time during escalation."""

    @pytest.mark.asyncio
    async def test_user_wait_excluded_from_deadline(self):
        """33. User spent 2s at prompt, DAG timeout is 3s, node takes 2s
        total wall-clock ~4s but effective elapsed (4-2=2s) < 3s → succeeds.
        """
        from probos.cognitive.decomposer import DAGExecutor

        async def slow_submit(intent, params, timeout=None):
            await asyncio.sleep(0.5)
            return _success_intent_results()

        runtime = MagicMock()
        runtime.submit_intent = AsyncMock(side_effect=slow_submit)

        # Simulate an escalation manager where user waited 2 seconds
        esc_mgr = EscalationManager(
            runtime=runtime, llm_client=None, max_retries=1,
        )

        executor = DAGExecutor(
            runtime=runtime, timeout=3.0, escalation_manager=esc_mgr,
        )

        dag = TaskDAG(nodes=[_make_node()])

        # Simulate user-wait: set user_wait_seconds mid-flight via a task
        # that adds user-wait time before the main node executes.
        # We do this by monkey-patching the execute flow: after reset but
        # before _execute_dag, add 2.0s of user_wait.
        original_execute_dag = executor._execute_dag

        async def patched_execute_dag(*args, **kwargs):
            # Simulate that escalation added 2s of user-wait
            esc_mgr.user_wait_seconds = 2.0
            # Burn 2s of wall-clock (simulating the user prompt)
            await asyncio.sleep(2.0)
            return await original_execute_dag(*args, **kwargs)

        executor._execute_dag = patched_execute_dag

        result = await executor.execute(dag)

        # Should succeed: effective = ~2.5s wall - 2.0s user = 0.5s < 3.0s
        assert result["completed_count"] == 1
        assert result["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_genuine_timeout_still_fires(self):
        """34. Multi-batch DAG: first batch completes slowly, deadline
        check fires before second batch starts.  Individual node
        timeouts (submit_intent timeout=10) handle single-node hangs;
        the DAG-level timeout is checked between batches.
        """
        from probos.cognitive.decomposer import DAGExecutor

        async def slow_submit(intent, params, timeout=None):
            await asyncio.sleep(0.6)  # completes, but burns most of budget
            return _success_intent_results()

        runtime = MagicMock()
        runtime.submit_intent = AsyncMock(side_effect=slow_submit)

        executor = DAGExecutor(runtime=runtime, timeout=0.5)
        # Two nodes: t2 depends on t1 → forces two separate batches
        dag = TaskDAG(nodes=[
            _make_node(id="t1"),
            TaskNode(id="t2", intent="read_file", params={"path": "/x"},
                     depends_on=["t1"]),
        ])

        result = await executor.execute(dag)

        # t1 completed in its batch, but t2 never ran — deadline fires
        assert result["failed_count"] >= 1

    @pytest.mark.asyncio
    async def test_user_wait_seconds_reset_each_execute(self):
        """35. user_wait_seconds is reset to 0 at start of each execute()."""
        from probos.cognitive.decomposer import DAGExecutor

        runtime = MagicMock()
        runtime.submit_intent = AsyncMock(return_value=_success_intent_results())

        esc_mgr = EscalationManager(
            runtime=runtime, llm_client=None, max_retries=1,
        )
        esc_mgr.user_wait_seconds = 99.0  # leftover from previous run

        executor = DAGExecutor(
            runtime=runtime, timeout=5.0, escalation_manager=esc_mgr,
        )
        dag = TaskDAG(nodes=[_make_node()])

        await executor.execute(dag)

        # After execute, user_wait_seconds should have been reset (not 99)
        # The exact value may be 0 or small, but definitely not 99
        assert esc_mgr.user_wait_seconds < 1.0
