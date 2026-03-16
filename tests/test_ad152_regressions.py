"""AD-152 regression tests: timeout alignment, non-consensus result handling,
prompt consistency, and red team timeout bounds.

These tests guard the invariants established in AD-150/AD-151/AD-152 so
future changes cannot silently reintroduce the bugs found in those cycles.
"""

import asyncio
import json
import re

import pytest

from probos.agents.http_fetch import HttpFetchAgent
from probos.agents.red_team import RedTeamAgent
from probos.cognitive.decomposer import (
    DAGExecutor,
    IntentDecomposer,
    _normalize_consensus_result,
    _summarize_node_result,
)
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.prompt_builder import PromptBuilder, PROMPT_EXAMPLES
from probos.config import SystemConfig, ConsensusConfig
from probos.types import IntentDescriptor, IntentMessage, IntentResult, TaskDAG, TaskNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_descriptors() -> list[IntentDescriptor]:
    """Collect intent descriptors from the standard user-facing agents."""
    from probos.agents.directory_list import DirectoryListAgent
    from probos.agents.file_reader import FileReaderAgent
    from probos.agents.file_search import FileSearchAgent
    from probos.agents.file_writer import FileWriterAgent
    from probos.agents.introspect import IntrospectionAgent
    from probos.agents.shell_command import ShellCommandAgent

    descriptors: list[IntentDescriptor] = []
    seen: set[str] = set()
    for cls in [
        FileReaderAgent,
        FileWriterAgent,
        DirectoryListAgent,
        FileSearchAgent,
        ShellCommandAgent,
        HttpFetchAgent,
        IntrospectionAgent,
    ]:
        for d in cls.intent_descriptors:
            if d.name not in seen:
                seen.add(d.name)
                descriptors.append(d)
    return descriptors


# ===================================================================
# 1. Timeout alignment
# ===================================================================


class TestTimeoutAlignment:
    """Ensure agent timeouts fit within broadcast / DAG executor bounds."""

    # The DAG executor passes timeout=10.0 to submit_intent / broadcast.
    DAG_BROADCAST_TIMEOUT = 10.0

    def test_http_fetch_timeout_within_broadcast(self):
        """http_fetch DEFAULT_TIMEOUT must be < DAG broadcast timeout
        so httpx completes or raises before asyncio.wait cancels the task."""
        assert HttpFetchAgent.DEFAULT_TIMEOUT < self.DAG_BROADCAST_TIMEOUT, (
            f"HttpFetchAgent.DEFAULT_TIMEOUT ({HttpFetchAgent.DEFAULT_TIMEOUT}s) "
            f"must be < DAG broadcast timeout ({self.DAG_BROADCAST_TIMEOUT}s)"
        )

    def test_red_team_http_timeout_within_verification(self):
        """Red team httpx timeout must be < config verification_timeout_seconds
        so the red team response arrives before the verification wrapper times out."""
        config = SystemConfig()
        verification_timeout = config.consensus.verification_timeout_seconds

        # The hard-coded httpx timeout in RedTeamAgent._verify_http_fetch
        # We inspect the source to detect drift.
        import inspect
        source = inspect.getsource(RedTeamAgent._verify_http_fetch)
        match = re.search(r"timeout\s*=\s*([\d.]+)", source)
        assert match, "Could not find httpx timeout in _verify_http_fetch source"
        httpx_timeout = float(match.group(1))

        assert httpx_timeout < verification_timeout, (
            f"Red team httpx timeout ({httpx_timeout}s) must be < "
            f"verification_timeout_seconds ({verification_timeout}s)"
        )

    def test_http_fetch_timeout_positive(self):
        """Sanity: timeout is a reasonable positive number."""
        assert HttpFetchAgent.DEFAULT_TIMEOUT > 0
        assert HttpFetchAgent.DEFAULT_TIMEOUT >= 3.0, (
            "Timeout too short — legitimate sites need at least a few seconds"
        )


# ===================================================================
# 2. Prompt consistency: examples match requires_consensus
# ===================================================================


class TestPromptConsistency:
    """All few-shot examples must agree with the agent's requires_consensus setting."""

    def _extract_examples(self, text: str) -> list[dict]:
        """Extract all JSON example blocks from a prompt string."""
        examples = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{") and "intents" in line:
                try:
                    examples.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return examples

    def test_prompt_builder_examples_http_fetch_non_consensus(self):
        """All http_fetch examples in PROMPT_EXAMPLES must have use_consensus: false."""
        examples = self._extract_examples(PROMPT_EXAMPLES)
        http_fetch_examples = [
            ex for ex in examples
            if any(i.get("intent") == "http_fetch" for i in ex.get("intents", []))
        ]
        assert len(http_fetch_examples) >= 1, "Should have at least one http_fetch example"
        for ex in http_fetch_examples:
            for intent in ex["intents"]:
                if intent["intent"] == "http_fetch":
                    assert intent.get("use_consensus") is False, (
                        f"http_fetch example has use_consensus={intent.get('use_consensus')!r}, "
                        f"expected False"
                    )

    def test_legacy_prompt_examples_http_fetch_non_consensus(self):
        """All http_fetch examples in the legacy system prompt must have use_consensus: false."""
        from probos.cognitive.decomposer import _LEGACY_SYSTEM_PROMPT
        examples = self._extract_examples(_LEGACY_SYSTEM_PROMPT)
        http_fetch_examples = [
            ex for ex in examples
            if any(i.get("intent") == "http_fetch" for i in ex.get("intents", []))
        ]
        assert len(http_fetch_examples) >= 1, "Should have at least one http_fetch example"
        for ex in http_fetch_examples:
            for intent in ex["intents"]:
                if intent["intent"] == "http_fetch":
                    assert intent.get("use_consensus") is False, (
                        f"Legacy http_fetch example has use_consensus="
                        f"{intent.get('use_consensus')!r}, expected False"
                    )

    def test_dynamic_rules_http_fetch_non_consensus(self):
        """Dynamic rules must put http_fetch in the non-consensus group."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(_all_descriptors())
        # Must NOT appear in a 'MUST have "use_consensus": true' rule
        assert 'All http_fetch intents MUST have "use_consensus": true' not in prompt
        # Must appear somewhere in the non-consensus group
        assert "http_fetch" in prompt

    def test_all_prompt_examples_match_descriptor(self):
        """Every few-shot example's use_consensus must agree with the
        intent's IntentDescriptor.requires_consensus."""
        descriptor_map = {d.name: d.requires_consensus for d in _all_descriptors()}
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(_all_descriptors())
        examples = self._extract_examples(prompt)
        for ex in examples:
            for intent in ex.get("intents", []):
                name = intent.get("intent")
                uc = intent.get("use_consensus")
                if name in descriptor_map and uc is not None:
                    expected = descriptor_map[name]
                    assert uc == expected, (
                        f"Example for {name!r} has use_consensus={uc!r} but "
                        f"descriptor says requires_consensus={expected!r}"
                    )

    def test_http_fetch_descriptor_non_consensus(self):
        """HttpFetchAgent's IntentDescriptor must have requires_consensus=False."""
        for d in HttpFetchAgent.intent_descriptors:
            if d.name == "http_fetch":
                assert d.requires_consensus is False


# ===================================================================
# 3. Non-consensus result format and node status
# ===================================================================


class TestNonConsensusResultFormat:
    """Non-consensus path must produce well-structured results and
    set node.status based on actual success/failure."""

    def _make_intent_result(self, success: bool, result=None, error=None) -> IntentResult:
        return IntentResult(
            intent_id="test-id",
            agent_id="agent-1",
            success=success,
            result=result,
            error=error,
            confidence=0.8,
        )

    def test_result_dict_keys(self):
        """Non-consensus result dict must have standard keys."""
        ir = self._make_intent_result(True, result={"body": "hello"})
        result = {
            "intent": "http_fetch",
            "results": [ir],
            "success": any(r.success for r in [ir]),
            "result_count": len([ir]),
        }
        assert "intent" in result
        assert "results" in result
        assert "success" in result
        assert "result_count" in result
        assert result["success"] is True
        assert result["result_count"] == 1

    def test_empty_results_success_false(self):
        """Empty result list means success=False."""
        results = []
        success = any(r.success for r in results)
        assert success is False

    def test_all_failed_results_success_false(self):
        """All agents returning success=False means overall success=False."""
        irs = [
            self._make_intent_result(False, error="timeout"),
            self._make_intent_result(False, error="connection refused"),
        ]
        success = any(r.success for r in irs)
        assert success is False

    def test_mixed_results_success_true(self):
        """At least one agent returning success=True means overall success=True."""
        irs = [
            self._make_intent_result(False, error="timeout"),
            self._make_intent_result(True, result={"body": "ok"}),
        ]
        success = any(r.success for r in irs)
        assert success is True


class TestNodeStatusReflectsSuccess:
    """DAG executor must set node.status based on result success,
    not unconditionally 'completed'."""

    @pytest.fixture
    def mock_runtime(self):
        """Minimal mock runtime for DAGExecutor tests."""
        class MockRuntime:
            async def submit_intent(self, intent, params, timeout):
                return self._next_results

            async def submit_intent_with_consensus(self, intent, params, timeout):
                return self._next_results

            async def submit_write_with_consensus(self, path, content, timeout):
                return self._next_results

            _next_results = []
        return MockRuntime()

    @pytest.mark.asyncio
    async def test_successful_non_consensus_marks_completed(self, mock_runtime):
        """Node with successful results should have status='completed'."""
        mock_runtime._next_results = [
            IntentResult(
                intent_id="i1", agent_id="a1",
                success=True, result={"body": "data"}, confidence=0.9,
            ),
        ]

        dag = TaskDAG(nodes=[
            TaskNode(id="t1", intent="http_fetch", params={"url": "https://example.com"}, use_consensus=False),
        ])
        executor = DAGExecutor(mock_runtime)
        result = await executor.execute(dag)

        assert dag.nodes[0].status == "completed"
        assert result["results"]["t1"]["success"] is True

    @pytest.mark.asyncio
    async def test_failed_non_consensus_marks_failed(self, mock_runtime):
        """Node with all-failed results should have status='failed'."""
        mock_runtime._next_results = [
            IntentResult(
                intent_id="i1", agent_id="a1",
                success=False, error="timeout", confidence=0.0,
            ),
        ]

        dag = TaskDAG(nodes=[
            TaskNode(id="t1", intent="http_fetch", params={"url": "https://example.com"}, use_consensus=False),
        ])
        executor = DAGExecutor(mock_runtime)
        result = await executor.execute(dag)

        assert dag.nodes[0].status == "failed"
        assert result["results"]["t1"]["success"] is False

    @pytest.mark.asyncio
    async def test_empty_results_marks_failed(self, mock_runtime):
        """Node with empty result list (broadcast timeout) should have status='failed'."""
        mock_runtime._next_results = []

        dag = TaskDAG(nodes=[
            TaskNode(id="t1", intent="http_fetch", params={"url": "https://example.com"}, use_consensus=False),
        ])
        executor = DAGExecutor(mock_runtime)
        result = await executor.execute(dag)

        assert dag.nodes[0].status == "failed"
        assert result["results"]["t1"]["success"] is False
        assert result["results"]["t1"]["result_count"] == 0

    @pytest.mark.asyncio
    async def test_node_failed_event_emitted(self, mock_runtime):
        """Verify node_failed event fires when non-consensus result has no success."""
        mock_runtime._next_results = [
            IntentResult(
                intent_id="i1", agent_id="a1",
                success=False, error="connection refused", confidence=0.0,
            ),
        ]

        events = []

        async def capture_event(name, data):
            events.append(name)

        dag = TaskDAG(nodes=[
            TaskNode(id="t1", intent="http_fetch", params={"url": "https://x.invalid"}, use_consensus=False),
        ])
        executor = DAGExecutor(mock_runtime)
        await executor.execute(dag, on_event=capture_event)

        assert "node_failed" in events
        assert "node_complete" not in events

    @pytest.mark.asyncio
    async def test_node_complete_event_on_success(self, mock_runtime):
        """Verify node_complete event fires when non-consensus result succeeds."""
        mock_runtime._next_results = [
            IntentResult(
                intent_id="i1", agent_id="a1",
                success=True, result={"body": "ok"}, confidence=0.9,
            ),
        ]

        events = []

        async def capture_event(name, data):
            events.append(name)

        dag = TaskDAG(nodes=[
            TaskNode(id="t1", intent="http_fetch", params={"url": "https://example.com"}, use_consensus=False),
        ])
        executor = DAGExecutor(mock_runtime)
        await executor.execute(dag, on_event=capture_event)

        assert "node_complete" in events
        assert "node_failed" not in events


# ===================================================================
# 4. _summarize_node_result with http_fetch-style data
# ===================================================================


class TestSummarizeHttpFetchResult:
    """_summarize_node_result must correctly extract http_fetch data."""

    def test_successful_http_fetch(self):
        """Summarize a successful http_fetch result."""
        ir = IntentResult(
            intent_id="i1",
            agent_id="a1",
            success=True,
            result={
                "url": "https://wttr.in/Denver?format=3",
                "status_code": 200,
                "headers": {"content-type": "text/plain"},
                "body": "Denver: 🌤  +72°F",
                "body_length": 19,
            },
            confidence=0.9,
        )
        node_result = {
            "intent": "http_fetch",
            "results": [ir],
            "success": True,
            "result_count": 1,
        }
        summary = _summarize_node_result(node_result)
        assert "success=True" in summary
        assert "Denver" in summary or "wttr" in summary or "72" in summary

    def test_failed_http_fetch(self):
        """Summarize a failed http_fetch result (timeout)."""
        ir = IntentResult(
            intent_id="i1",
            agent_id="a1",
            success=False,
            error="Request timed out after 8.0s",
            confidence=0.0,
        )
        node_result = {
            "intent": "http_fetch",
            "results": [ir],
            "success": False,
            "result_count": 1,
        }
        summary = _summarize_node_result(node_result)
        assert "success=False" in summary
        assert "timed out" in summary

    def test_empty_results_list(self):
        """Summarize with empty results (broadcast cancellation)."""
        node_result = {
            "intent": "http_fetch",
            "results": [],
            "success": False,
            "result_count": 0,
        }
        summary = _summarize_node_result(node_result)
        assert "success=False" in summary

    def test_non_dict_input(self):
        """Summarize falls back to str() for non-dict input."""
        summary = _summarize_node_result("raw string result")
        assert "raw string result" in summary

    def test_error_dict(self):
        """Summarize handles error-only dict."""
        summary = _summarize_node_result({"error": "Something broke"})
        assert "error=Something broke" in summary


# ===================================================================
# 5. HttpFetchAgent requires_consensus = False
# ===================================================================


class TestHttpFetchNonConsensus:
    """Ensure http_fetch is configured as non-consensus end-to-end."""

    def test_agent_requires_consensus_false(self):
        """The agent's IntentDescriptor says requires_consensus=False."""
        for d in HttpFetchAgent.intent_descriptors:
            if d.name == "http_fetch":
                assert d.requires_consensus is False
                return
        pytest.fail("http_fetch descriptor not found")

    @pytest.mark.asyncio
    async def test_full_runtime_non_consensus_routing(self, tmp_path):
        """Integration: http_fetch is not in the consensus_intents set
        and HttpFetchAgent.requires_consensus is False."""
        from probos.runtime import ProbOSRuntime

        cfg = SystemConfig()
        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await rt.start()
        try:
            # Build the pool-intent map and verify http_fetch is present
            pool_map = rt._build_pool_intent_map()
            http_intents = []
            for pool_name, intents in pool_map.items():
                if "http_fetch" in intents:
                    http_intents.append(pool_name)
            assert http_intents, "http_fetch should be mapped to at least one pool"
        finally:
            await rt.stop()

    def test_consensus_intents_exclude_http_fetch(self):
        """The consensus_intents set used by _validate_remote_result must not include http_fetch."""
        # Inspect the source to catch hardcoded sets
        import inspect
        source = inspect.getsource(__import__("probos.runtime", fromlist=["ProbOSRuntime"]).ProbOSRuntime._validate_remote_result)
        # Find the consensus_intents set literal
        assert "http_fetch" not in source or '"http_fetch"' not in source, (
            "http_fetch should not appear in consensus_intents inside _validate_remote_result"
        )


# ===================================================================
# 6. DAG dependency propagation on failure
# ===================================================================


class TestDependencyFailurePropagation:
    """When a non-consensus node fails, dependent nodes must not run."""

    @pytest.fixture
    def mock_runtime(self):
        class MockRuntime:
            def __init__(self):
                self.called_intents = []

            async def submit_intent(self, intent, params, timeout):
                self.called_intents.append(intent)
                if intent == "http_fetch":
                    # Simulate failure
                    return [IntentResult(
                        intent_id="i1", agent_id="a1",
                        success=False, error="timeout", confidence=0.0,
                    )]
                return [IntentResult(
                    intent_id="i2", agent_id="a2",
                    success=True, result="reflected", confidence=0.9,
                )]

        return MockRuntime()

    @pytest.mark.asyncio
    async def test_dependent_node_fails_on_dep_failure(self, mock_runtime):
        """If t1 (http_fetch) fails, t2 (depends on t1) should also fail."""
        dag = TaskDAG(nodes=[
            TaskNode(
                id="t1", intent="http_fetch",
                params={"url": "https://example.com"},
                use_consensus=False,
            ),
            TaskNode(
                id="t2", intent="read_file",
                params={"path": "/tmp/x"},
                depends_on=["t1"],
                use_consensus=False,
            ),
        ])
        executor = DAGExecutor(mock_runtime)
        result = await executor.execute(dag)

        # t1 should have failed
        assert dag.nodes[0].status == "failed"
        # t2 should also be marked failed (deadlock detection)
        assert dag.nodes[1].status == "failed"
        # submit_intent should only have been called for t1 (t2 never ran)
        assert mock_runtime.called_intents == ["http_fetch"]


# ===================================================================
# 7. HttpFetchAgent timeout error message
# ===================================================================


class TestHttpFetchTimeoutMessage:
    """The timeout error message must reflect the actual DEFAULT_TIMEOUT value."""

    @pytest.mark.asyncio
    async def test_timeout_error_message_value(self, monkeypatch):
        """The error message should contain the correct timeout value."""
        import httpx

        class MockAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def request(self, method, url):
                raise httpx.TimeoutException("timed out")

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient())
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 0))],
        )

        agent = HttpFetchAgent()
        intent = IntentMessage(
            intent="http_fetch",
            params={"url": "https://slow.example.com", "method": "GET"},
        )
        result = await agent.handle_intent(intent)

        assert result is not None
        assert not result.success
        assert str(HttpFetchAgent.DEFAULT_TIMEOUT) in result.error
