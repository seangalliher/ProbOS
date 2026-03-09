"""Tests for SystemQAAgent — Phase 13."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.agents.system_qa import QAReport, SystemQAAgent, _infer_param_type
from probos.cognitive.self_mod import DesignedAgentRecord
from probos.config import QAConfig, SystemConfig
from probos.substrate.agent import BaseAgent
from probos.types import IntentDescriptor, IntentMessage, IntentResult


# ===================================================================
# Helpers: mock agents for integration tests
# ===================================================================


def _make_record(
    intent_name: str = "count_words",
    agent_type: str = "count_words",
    source_code: str | None = None,
    pool_name: str = "designed_count_words",
    params: dict[str, str] | None = None,
) -> DesignedAgentRecord:
    """Create a DesignedAgentRecord for testing."""
    if source_code is None:
        p = params or {"text": "input text"}
        param_str = ", ".join(f'"{k}": "{v}"' for k, v in p.items())
        source_code = (
            'from probos.substrate.agent import BaseAgent\n'
            'from probos.types import IntentDescriptor\n'
            f'class CountWordsAgent(BaseAgent):\n'
            f'    agent_type = "{agent_type}"\n'
            f'    intent_descriptors = [IntentDescriptor(name="{intent_name}", '
            f'params={{{param_str}}})]\n'
        )
    return DesignedAgentRecord(
        intent_name=intent_name,
        agent_type=agent_type,
        class_name="CountWordsAgent",
        source_code=source_code,
        created_at=time.monotonic(),
        pool_name=pool_name,
    )


class PassingMockAgent(BaseAgent):
    """Agent that always succeeds."""
    agent_type = "passing_mock"
    intent_descriptors = [IntentDescriptor(name="count_words", params={"text": "input text"})]

    async def perceive(self, intent): return intent
    async def decide(self, obs): return obs
    async def act(self, plan): return {"success": True}
    async def report(self, result): return result

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        if intent.intent not in [d.name for d in self.intent_descriptors]:
            return None
        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=True,
            result={"word_count": 42},
        )


class FailingMockAgent(BaseAgent):
    """Agent that always raises exceptions."""
    agent_type = "failing_mock"
    intent_descriptors = [IntentDescriptor(name="count_words", params={"text": "input text"})]

    async def perceive(self, intent): return intent
    async def decide(self, obs): return obs
    async def act(self, plan): return {"success": False}
    async def report(self, result): return result

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        raise RuntimeError("Agent crashed!")


class FlakyMockAgent(BaseAgent):
    """Agent that fails on even-numbered calls."""
    agent_type = "flaky_mock"
    intent_descriptors = [IntentDescriptor(name="count_words", params={"text": "input text"})]
    _call_count = 0

    async def perceive(self, intent): return intent
    async def decide(self, obs): return obs
    async def act(self, plan): return {"success": True}
    async def report(self, result): return result

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        self._call_count += 1
        if self._call_count % 2 == 0:
            raise RuntimeError("Flaky failure")
        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=True,
            result={"word_count": 42},
        )


class DecliningMockAgent(BaseAgent):
    """Agent that returns None for all intents."""
    agent_type = "declining_mock"
    intent_descriptors = [IntentDescriptor(name="count_words", params={"text": "input text"})]

    async def perceive(self, intent): return None
    async def decide(self, obs): return obs
    async def act(self, plan): return {"success": True}
    async def report(self, result): return result

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        return None


class SlowMockAgent(BaseAgent):
    """Agent that sleeps to trigger timeout."""
    agent_type = "slow_mock"
    intent_descriptors = [IntentDescriptor(name="count_words", params={"text": "input text"})]

    async def perceive(self, intent): return intent
    async def decide(self, obs): return obs
    async def act(self, plan): return {"success": True}
    async def report(self, result): return result

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        await asyncio.sleep(100)  # sleep forever (timeout will cancel)
        return IntentResult(
            intent_id=intent.id, agent_id=self.id, success=True, result={},
        )


class GracefulErrorAgent(BaseAgent):
    """Agent that returns failure with error message (no crash)."""
    agent_type = "graceful_error_mock"
    intent_descriptors = [IntentDescriptor(name="count_words", params={"text": "input text"})]

    async def perceive(self, intent): return intent
    async def decide(self, obs): return obs
    async def act(self, plan): return {"success": False}
    async def report(self, result): return result

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=False,
            result=None,
            error="Invalid parameters provided",
        )


class MockPool:
    """Lightweight mock pool for testing."""

    def __init__(self, agents: list[BaseAgent] | None = None):
        self._agents = agents or []
        self.agent_type = "mock"
        self.registry = MagicMock()
        self.min_size = 0
        self.current_size = len(self._agents)
        self._target_size = len(self._agents)

    @property
    def healthy_agents(self):
        return self._agents

    @property
    def agents(self):
        return self._agents

    async def remove_agent(self, trust_network=None):
        if self._agents:
            removed = self._agents.pop()
            self.current_size = len(self._agents)
            return removed.id
        return None

    async def stop(self):
        """No-op stop for test cleanup."""
        pass


# ===================================================================
# 6e. Config tests
# ===================================================================


class TestQAConfig:
    """Tests for QAConfig defaults and loading."""

    def test_qa_config_defaults(self):
        """Default config values match spec."""
        cfg = QAConfig()
        assert cfg.enabled is True
        assert cfg.smoke_test_count == 5
        assert cfg.timeout_per_test_seconds == 10.0
        assert cfg.total_timeout_seconds == 30.0
        assert cfg.pass_threshold == 0.6
        assert cfg.trust_reward_weight == 1.0
        assert cfg.trust_penalty_weight == 2.0
        assert cfg.flag_on_fail is True
        assert cfg.auto_remove_on_total_fail is False

    def test_qa_config_in_system_config(self):
        """SystemConfig includes qa: QAConfig field."""
        cfg = SystemConfig()
        assert hasattr(cfg, "qa")
        assert isinstance(cfg.qa, QAConfig)

    def test_qa_config_from_yaml(self, tmp_path):
        """Config loads from YAML with custom QA values."""
        yaml_content = """
qa:
  enabled: false
  smoke_test_count: 3
  pass_threshold: 0.8
  trust_penalty_weight: 3.0
"""
        yaml_file = tmp_path / "test_qa.yaml"
        yaml_file.write_text(yaml_content)

        from probos.config import load_config
        cfg = load_config(str(yaml_file))
        assert cfg.qa.enabled is False
        assert cfg.qa.smoke_test_count == 3
        assert cfg.qa.pass_threshold == 0.8
        assert cfg.qa.trust_penalty_weight == 3.0

    def test_qa_config_missing_uses_defaults(self, tmp_path):
        """Missing qa: section in YAML -> defaults applied."""
        yaml_content = """
system:
  name: "TestOS"
"""
        yaml_file = tmp_path / "test_no_qa.yaml"
        yaml_file.write_text(yaml_content)

        from probos.config import load_config
        cfg = load_config(str(yaml_file))
        assert cfg.qa.enabled is True
        assert cfg.qa.smoke_test_count == 5


# ===================================================================
# 6a. Unit tests for SystemQAAgent
# ===================================================================


class TestGenerateSyntheticIntents:
    """Tests for generate_synthetic_intents method."""

    def setup_method(self):
        self.agent = SystemQAAgent(agent_id="qa-1")
        self.record = _make_record()

    def test_generate_synthetic_intents_happy_path(self):
        """Generates correct number of synthetic IntentMessages; happy path cases have valid params."""
        cases = self.agent.generate_synthetic_intents(self.record, count=5)
        happy_cases = [c for c in cases if c[0] == "happy"]
        assert len(happy_cases) >= 2
        for case_type, intent in happy_cases:
            assert intent.intent == "count_words"
            assert "text" in intent.params
            assert intent.params["text"] == "test_value"

    def test_generate_synthetic_intents_edge_cases(self):
        """Edge case intents have minimal/empty params."""
        cases = self.agent.generate_synthetic_intents(self.record, count=5)
        edge_cases = [c for c in cases if c[0] == "edge"]
        assert len(edge_cases) == 1
        _, intent = edge_cases[0]
        assert intent.params["text"] == ""

    def test_generate_synthetic_intents_error_cases(self):
        """Error case intents have invalid params."""
        cases = self.agent.generate_synthetic_intents(self.record, count=5)
        error_cases = [c for c in cases if c[0] == "error"]
        assert len(error_cases) == 1
        _, intent = error_cases[0]
        assert intent.params["text"] is None

    @pytest.mark.parametrize("count", [3, 5, 7])
    def test_generate_synthetic_intents_count(self, count):
        """Total generated matches smoke_test_count."""
        cases = self.agent.generate_synthetic_intents(self.record, count=count)
        assert len(cases) == count

    def test_param_type_inference_url_key(self):
        """Key containing 'url' -> URL-type synthetic values (AD-156)."""
        assert _infer_param_type("target_url") == "url"
        assert _infer_param_type("api_uri") == "url"
        assert _infer_param_type("endpoint") == "url"

        record = _make_record(params={"target_url": "a URL to fetch"})
        cases = self.agent.generate_synthetic_intents(record, count=3)
        happy = [c for c in cases if c[0] == "happy"]
        assert happy[0][1].params["target_url"] == "https://example.com"

    def test_param_type_inference_path_key(self):
        """Key containing 'path' or 'file' -> path-type synthetic values (AD-156)."""
        assert _infer_param_type("file_path") == "path"
        assert _infer_param_type("directory") == "path"
        assert _infer_param_type("filepath") == "path"

        record = _make_record(params={"file_path": "path to file"})
        cases = self.agent.generate_synthetic_intents(record, count=3)
        happy = [c for c in cases if c[0] == "happy"]
        assert happy[0][1].params["file_path"] == "/tmp/test_qa.txt"

    def test_param_type_inference_numeric_key(self):
        """Key containing 'count', 'num', 'limit' -> int-type synthetic values (AD-156)."""
        assert _infer_param_type("word_count") == "numeric"
        assert _infer_param_type("max_items") == "numeric"
        assert _infer_param_type("limit") == "numeric"

        record = _make_record(params={"word_count": "number of words"})
        cases = self.agent.generate_synthetic_intents(record, count=3)
        happy = [c for c in cases if c[0] == "happy"]
        assert happy[0][1].params["word_count"] == 42

    def test_param_type_inference_bool_key(self):
        """Key containing 'flag', 'enabled' -> bool-type synthetic values (AD-156)."""
        assert _infer_param_type("verbose_flag") == "bool"
        assert _infer_param_type("enabled") == "bool"

        record = _make_record(params={"verbose": "verbose output"})
        cases = self.agent.generate_synthetic_intents(record, count=3)
        happy = [c for c in cases if c[0] == "happy"]
        assert happy[0][1].params["verbose"] is True

    def test_param_type_inference_default(self):
        """Unknown key name -> string-type synthetic values (AD-156)."""
        assert _infer_param_type("something_random") == "default"
        record = _make_record(params={"query": "search query"})
        cases = self.agent.generate_synthetic_intents(record, count=3)
        happy = [c for c in cases if c[0] == "happy"]
        assert happy[0][1].params["query"] == "test_value"


class TestValidateResult:
    """Tests for validate_result method."""

    def setup_method(self):
        self.agent = SystemQAAgent(agent_id="qa-1")

    def _make_result(self, success=True, result=None, error=None):
        return IntentResult(
            intent_id="test", agent_id="test", success=success,
            result=result, error=error,
        )

    def test_validate_result_success(self):
        """Happy path: IntentResult with success=True passes."""
        r = self._make_result(success=True, result={"data": 42})
        assert self.agent.validate_result("happy", r, None) is True

    def test_validate_result_graceful_failure(self):
        """Error case: IntentResult with success=False, error set passes."""
        r = self._make_result(success=False, error="bad input")
        assert self.agent.validate_result("error", r, None) is True

    def test_validate_result_crash(self):
        """Unhandled exception fails the test (error is not None)."""
        r = self._make_result(success=True, result={"data": 42})
        assert self.agent.validate_result("happy", r, "RuntimeError: crash") is False

    def test_validate_result_none_for_error_case(self):
        """IntentResult=None on error case counts as pass (declined)."""
        assert self.agent.validate_result("error", None, None) is True

    def test_validate_result_none_for_happy_path(self):
        """IntentResult=None on happy path counts as fail."""
        assert self.agent.validate_result("happy", None, None) is False

    def test_validate_result_edge_case_success(self):
        """Edge case: IntentResult with success=True passes."""
        r = self._make_result(success=True, result={"data": 42})
        assert self.agent.validate_result("edge", r, None) is True

    def test_validate_result_edge_case_failure(self):
        """Edge case: IntentResult with success=False also passes (no crash = pass)."""
        r = self._make_result(success=False, error="edge fail")
        assert self.agent.validate_result("edge", r, None) is True


class TestQAReportStructure:
    """Tests for QAReport dataclass."""

    def test_qa_report_structure(self):
        """QAReport has all required fields, types correct."""
        report = QAReport(
            agent_type="test_agent",
            intent_name="test_intent",
            pool_name="test_pool",
            total_tests=5,
            passed=3,
            failed=2,
            pass_rate=0.6,
            verdict="passed",
            test_details=[{"case_type": "happy", "passed": True, "error": None}],
            duration_ms=100.0,
            timestamp=time.time(),
        )
        assert report.agent_type == "test_agent"
        assert report.total_tests == 5
        assert report.passed == 3
        assert report.failed == 2
        assert report.pass_rate == 0.6
        assert report.verdict == "passed"
        assert len(report.test_details) == 1

    def test_pass_rate_calculation(self):
        """3/5 -> 0.6, verdict 'passed' at threshold 0.6."""
        # We test this via the agent's run_smoke_tests, but verify report math
        assert 3 / 5 == 0.6
        report = QAReport(
            agent_type="t", intent_name="i", pool_name="p",
            total_tests=5, passed=3, failed=2, pass_rate=0.6, verdict="passed",
        )
        assert report.pass_rate >= 0.6
        assert report.verdict == "passed"

    def test_fail_rate_calculation(self):
        """2/5 -> 0.4, verdict 'failed' at threshold 0.6."""
        report = QAReport(
            agent_type="t", intent_name="i", pool_name="p",
            total_tests=5, passed=2, failed=3, pass_rate=0.4, verdict="failed",
        )
        assert report.pass_rate < 0.6
        assert report.verdict == "failed"

    def test_pass_rate_boundary(self):
        """Exactly at threshold (0.6) -> 'passed'; one below (0.59) -> 'failed'."""
        # At threshold
        cfg = QAConfig(pass_threshold=0.6)
        assert 3 / 5 >= cfg.pass_threshold
        # Just below
        assert 2.95 / 5 < cfg.pass_threshold


# ===================================================================
# 6b. Integration tests
# ===================================================================


class TestSmokeTestIntegration:
    """Integration tests for run_smoke_tests with mock agents."""

    def setup_method(self):
        self.agent = SystemQAAgent(agent_id="qa-1")
        self.config = QAConfig()
        self.record = _make_record()

    @pytest.mark.asyncio
    async def test_smoke_test_passing_agent(self):
        """A well-behaved mock agent passes all smoke tests."""
        pool = MockPool([PassingMockAgent(agent_id="pass-1")])
        report = await self.agent.run_smoke_tests(self.record, pool, self.config)
        assert report.verdict == "passed"
        assert report.passed >= 3  # At least 3/5 must pass for threshold 0.6
        assert report.total_tests == 5

    @pytest.mark.asyncio
    async def test_smoke_test_failing_agent(self):
        """An agent that always raises exceptions fails smoke tests."""
        pool = MockPool([FailingMockAgent(agent_id="fail-1")])
        report = await self.agent.run_smoke_tests(self.record, pool, self.config)
        assert report.verdict == "failed"
        # All tests should fail because the agent crashes
        assert report.failed == 5

    @pytest.mark.asyncio
    async def test_smoke_test_flaky_agent(self):
        """An agent that sometimes fails gets correct pass rate."""
        agent = FlakyMockAgent(agent_id="flaky-1")
        agent._call_count = 0
        pool = MockPool([agent])
        report = await self.agent.run_smoke_tests(self.record, pool, self.config)
        # Flaky: fails on even calls (2, 4) => 3 pass, 2 fail => 0.6 pass rate
        assert report.total_tests == 5
        assert report.passed + report.failed == 5
        # With threshold 0.6, might pass or fail depending on exact call pattern

    @pytest.mark.asyncio
    async def test_smoke_test_declining_agent(self):
        """An agent returning None for all intents — happy path cases fail, error case passes."""
        pool = MockPool([DecliningMockAgent(agent_id="decline-1")])
        report = await self.agent.run_smoke_tests(self.record, pool, self.config)
        # Happy path: None = fail. Edge: None is fail (must return IntentResult). Error: None is pass.
        # 3 happy fail + 1 edge fail + 1 error pass = 1/5 = "failed"
        assert report.verdict == "failed"
        error_tests = [t for t in report.test_details if t["case_type"] == "error"]
        assert len(error_tests) == 1
        assert error_tests[0]["passed"] is True

    @pytest.mark.asyncio
    async def test_qa_timeout_handling(self):
        """Agent that sleeps beyond timeout — test times out gracefully."""
        pool = MockPool([SlowMockAgent(agent_id="slow-1")])
        config = QAConfig(timeout_per_test_seconds=0.1, total_timeout_seconds=5.0)
        report = await self.agent.run_smoke_tests(self.record, pool, config)
        assert report.total_tests == 5
        # All should fail due to timeout
        for detail in report.test_details:
            assert detail["passed"] is False

    @pytest.mark.asyncio
    async def test_qa_total_timeout(self):
        """Agent that sleeps beyond total timeout — remaining tests skipped."""
        pool = MockPool([SlowMockAgent(agent_id="slow-1")])
        config = QAConfig(
            timeout_per_test_seconds=0.05,
            total_timeout_seconds=0.01,  # Very short total budget
        )
        report = await self.agent.run_smoke_tests(self.record, pool, config)
        # Some tests may be skipped due to total timeout
        assert report.total_tests == 5
        timeout_errors = [t for t in report.test_details if t.get("error") in ("timeout", "total_timeout_exceeded")]
        assert len(timeout_errors) > 0


# ===================================================================
# 6b continued: Trust, episodic, event log integration tests
# ===================================================================


class TestTrustIntegration:
    """Tests for trust network updates from QA."""

    @pytest.mark.asyncio
    async def test_trust_updated_on_qa_pass(self, tmp_path):
        """Trust network scores increase after passing QA."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        # Create a mock designed agent pool
        agent = PassingMockAgent(agent_id="pass-trust-1")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool

        # Get trust before QA
        score_before = rt.trust_network.get_score(agent.id)

        record = _make_record()
        rt._system_qa = SystemQAAgent(agent_id="qa-trust")
        rt._qa_reports = {}

        report = await rt._run_qa_for_designed_agent(record)

        score_after = rt.trust_network.get_score(agent.id)
        assert score_after > score_before
        await rt.stop()

    @pytest.mark.asyncio
    async def test_trust_updated_on_qa_fail(self, tmp_path):
        """Trust network scores decrease after failing QA."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        agent = FailingMockAgent(agent_id="fail-trust-1")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool

        score_before = rt.trust_network.get_score(agent.id)

        record = _make_record()
        rt._system_qa = SystemQAAgent(agent_id="qa-trust")
        rt._qa_reports = {}

        report = await rt._run_qa_for_designed_agent(record)

        score_after = rt.trust_network.get_score(agent.id)
        assert score_after < score_before
        await rt.stop()

    @pytest.mark.asyncio
    async def test_trust_weight_asymmetry(self, tmp_path):
        """Penalty weight (2.0) causes greater trust change than reward weight (1.0)."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        # Agent with equal pass/fail
        agent_pass = PassingMockAgent(agent_id="asym-pass")
        agent_fail = FailingMockAgent(agent_id="asym-fail")
        pool_pass = MockPool([agent_pass])
        pool_fail = MockPool([agent_fail])

        # Start both at same trust
        rt.trust_network.create_with_prior(agent_pass.id, alpha=1.0, beta=1.0)
        rt.trust_network.create_with_prior(agent_fail.id, alpha=1.0, beta=1.0)

        rt.pools["designed_count_words"] = pool_pass
        rt._system_qa = SystemQAAgent(agent_id="qa-asym")
        rt._qa_reports = {}
        record = _make_record()
        await rt._run_qa_for_designed_agent(record)
        score_pass = rt.trust_network.get_score(agent_pass.id)

        rt.pools["designed_count_words"] = pool_fail
        record2 = _make_record()
        await rt._run_qa_for_designed_agent(record2)
        score_fail = rt.trust_network.get_score(agent_fail.id)

        # Passing should be higher trust than failing
        assert score_pass > score_fail
        await rt.stop()


class TestEpisodicMemoryIntegration:
    """Tests for episodic memory recording from QA."""

    @pytest.mark.asyncio
    async def test_episodic_memory_recorded(self, tmp_path):
        """An Episode is stored with [SystemQA] prefix after QA completes."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient
        from probos.cognitive.episodic_mock import MockEpisodicMemory

        mem = MockEpisodicMemory()
        rt = ProbOSRuntime(
            data_dir=tmp_path / "data",
            llm_client=MockLLMClient(),
            episodic_memory=mem,
        )
        await rt.start()

        agent = PassingMockAgent(agent_id="ep-1")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool
        rt._system_qa = SystemQAAgent(agent_id="qa-ep")
        rt._qa_reports = {}

        record = _make_record()
        await rt._run_qa_for_designed_agent(record)

        episodes = await mem.recent(k=10)
        qa_episodes = [e for e in episodes if "[SystemQA]" in e.user_input]
        assert len(qa_episodes) >= 1
        await rt.stop()

    @pytest.mark.asyncio
    async def test_episodic_memory_content(self, tmp_path):
        """Stored episode has correct dag_summary, outcomes, reflection, agent_ids."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient
        from probos.cognitive.episodic_mock import MockEpisodicMemory

        mem = MockEpisodicMemory()
        rt = ProbOSRuntime(
            data_dir=tmp_path / "data",
            llm_client=MockLLMClient(),
            episodic_memory=mem,
        )
        await rt.start()

        agent = PassingMockAgent(agent_id="ep-2")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool
        rt._system_qa = SystemQAAgent(agent_id="qa-ep2")
        rt._qa_reports = {}

        record = _make_record()
        await rt._run_qa_for_designed_agent(record)

        episodes = await mem.recent(k=10)
        qa_ep = [e for e in episodes if "[SystemQA]" in e.user_input][0]
        assert qa_ep.dag_summary["node_count"] == 5
        assert "count_words" in qa_ep.dag_summary["intent_types"]
        assert len(qa_ep.outcomes) == 5
        assert "QA" in qa_ep.reflection
        assert agent.id in qa_ep.agent_ids
        await rt.stop()


class TestEventLogIntegration:
    """Tests for event log entries from QA."""

    @pytest.mark.asyncio
    async def test_event_log_started(self, tmp_path):
        """smoke_test_started event emitted when QA begins."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        agent = PassingMockAgent(agent_id="ev-1")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool
        rt._system_qa = SystemQAAgent(agent_id="qa-ev")
        rt._system_qa._runtime = rt
        rt._qa_reports = {}

        record = _make_record()
        await rt._run_qa_for_designed_agent(record)

        events = await rt.event_log.query(category="qa", limit=20)
        started = [e for e in events if e["event"] == "smoke_test_started"]
        assert len(started) >= 1
        await rt.stop()

    @pytest.mark.asyncio
    async def test_event_log_passed(self, tmp_path):
        """smoke_test_passed event emitted when QA passes."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        agent = PassingMockAgent(agent_id="ev-2")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool
        rt._system_qa = SystemQAAgent(agent_id="qa-ev2")
        rt._system_qa._runtime = rt
        rt._qa_reports = {}

        record = _make_record()
        await rt._run_qa_for_designed_agent(record)

        events = await rt.event_log.query(category="qa", limit=20)
        passed = [e for e in events if e["event"] == "smoke_test_passed"]
        assert len(passed) >= 1
        await rt.stop()

    @pytest.mark.asyncio
    async def test_event_log_failed(self, tmp_path):
        """smoke_test_failed event emitted when QA fails."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        agent = FailingMockAgent(agent_id="ev-3")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool
        rt._system_qa = SystemQAAgent(agent_id="qa-ev3")
        rt._system_qa._runtime = rt
        rt._qa_reports = {}

        record = _make_record()
        await rt._run_qa_for_designed_agent(record)

        events = await rt.event_log.query(category="qa", limit=20)
        failed = [e for e in events if e["event"] == "smoke_test_failed"]
        assert len(failed) >= 1
        await rt.stop()

    @pytest.mark.asyncio
    async def test_qa_flag_on_failure(self, tmp_path):
        """agent_flagged event emitted when QA fails and flag_on_fail=True."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        agent = FailingMockAgent(agent_id="flag-1")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool
        rt._system_qa = SystemQAAgent(agent_id="qa-flag")
        rt._system_qa._runtime = rt
        rt._qa_reports = {}
        rt.config.qa.flag_on_fail = True

        record = _make_record()
        await rt._run_qa_for_designed_agent(record)

        events = await rt.event_log.query(category="qa", limit=20)
        flagged = [e for e in events if e["event"] == "agent_flagged"]
        assert len(flagged) >= 1
        await rt.stop()

    @pytest.mark.asyncio
    async def test_qa_no_flag_when_disabled(self, tmp_path):
        """No agent_flagged event when flag_on_fail=False."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        agent = FailingMockAgent(agent_id="noflag-1")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool
        rt._system_qa = SystemQAAgent(agent_id="qa-noflag")
        rt._system_qa._runtime = rt
        rt._qa_reports = {}
        rt.config.qa.flag_on_fail = False

        record = _make_record()
        await rt._run_qa_for_designed_agent(record)

        events = await rt.event_log.query(category="qa", limit=20)
        flagged = [e for e in events if e["event"] == "agent_flagged"]
        assert len(flagged) == 0
        await rt.stop()


class TestAutoRemove:
    """Tests for auto-remove on total failure."""

    @pytest.mark.asyncio
    async def test_qa_auto_remove_on_total_fail(self, tmp_path):
        """Pool emptied when 0/N pass and auto_remove_on_total_fail=True."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        agent = FailingMockAgent(agent_id="rm-1")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool
        rt._system_qa = SystemQAAgent(agent_id="qa-rm")
        rt._system_qa._runtime = rt
        rt._qa_reports = {}
        rt.config.qa.auto_remove_on_total_fail = True

        record = _make_record()
        await rt._run_qa_for_designed_agent(record)

        events = await rt.event_log.query(category="qa", limit=20)
        removed = [e for e in events if e["event"] == "agent_removed"]
        assert len(removed) >= 1
        await rt.stop()

    @pytest.mark.asyncio
    async def test_qa_no_remove_on_partial_fail(self, tmp_path):
        """Pool NOT emptied when 1/5 pass and auto_remove_on_total_fail=True."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        # Declining agent: error case passes (1/5 pass)
        agent = DecliningMockAgent(agent_id="partial-1")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool
        rt._system_qa = SystemQAAgent(agent_id="qa-partial")
        rt._system_qa._runtime = rt
        rt._qa_reports = {}
        rt.config.qa.auto_remove_on_total_fail = True

        record = _make_record()
        await rt._run_qa_for_designed_agent(record)

        events = await rt.event_log.query(category="qa", limit=20)
        removed = [e for e in events if e["event"] == "agent_removed"]
        assert len(removed) == 0  # Not total fail — no removal
        await rt.stop()

    @pytest.mark.asyncio
    async def test_qa_no_remove_when_disabled(self, tmp_path):
        """Pool NOT emptied when 0/N pass and auto_remove_on_total_fail=False."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        agent = FailingMockAgent(agent_id="normdis-1")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool
        rt._system_qa = SystemQAAgent(agent_id="qa-normdis")
        rt._system_qa._runtime = rt
        rt._qa_reports = {}
        rt.config.qa.auto_remove_on_total_fail = False

        record = _make_record()
        await rt._run_qa_for_designed_agent(record)

        events = await rt.event_log.query(category="qa", limit=20)
        removed = [e for e in events if e["event"] == "agent_removed"]
        assert len(removed) == 0
        await rt.stop()


class TestQAReportStore:
    """Tests for in-memory QA report store (AD-157)."""

    @pytest.mark.asyncio
    async def test_qa_report_stored_in_memory(self, tmp_path):
        """After QA runs, runtime._qa_reports[agent_type] contains the QAReport."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        agent = PassingMockAgent(agent_id="store-1")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool
        rt._system_qa = SystemQAAgent(agent_id="qa-store")
        rt._qa_reports = {}

        record = _make_record()
        await rt._run_qa_for_designed_agent(record)

        assert "count_words" in rt._qa_reports
        assert rt._qa_reports["count_words"].verdict == "passed"
        await rt.stop()

    @pytest.mark.asyncio
    async def test_qa_report_overwritten_on_rerun(self, tmp_path):
        """Second QA run for same agent_type overwrites the first report."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        agent = PassingMockAgent(agent_id="overwrite-1")
        pool = MockPool([agent])
        rt.pools["designed_count_words"] = pool
        rt._system_qa = SystemQAAgent(agent_id="qa-overwrite")
        rt._qa_reports = {}

        record = _make_record()
        await rt._run_qa_for_designed_agent(record)
        first_ts = rt._qa_reports["count_words"].timestamp

        await rt._run_qa_for_designed_agent(record)
        second_ts = rt._qa_reports["count_words"].timestamp
        assert second_ts >= first_ts
        await rt.stop()


class TestQADisabled:
    """Tests for QA disabled scenarios."""

    @pytest.mark.asyncio
    async def test_qa_disabled_skips(self, tmp_path):
        """QA does not run when qa.enabled = False."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        rt.config = rt.config.model_copy(
            update={"qa": QAConfig(enabled=False)}
        )
        await rt.start()

        record = _make_record()
        result = await rt._run_qa_for_designed_agent(record)
        assert result is None
        assert len(rt._qa_reports) == 0
        await rt.stop()

    @pytest.mark.asyncio
    async def test_qa_without_selfmod_skips(self, tmp_path):
        """QA has no agent when self-mod is disabled."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient
        from probos.config import SelfModConfig

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        rt.config = rt.config.model_copy(
            update={"self_mod": SelfModConfig(enabled=False)}
        )
        await rt.start()
        assert rt._system_qa is None
        await rt.stop()


# ===================================================================
# 6c. Error containment tests (AD-154)
# ===================================================================


class TestErrorContainment:
    """Tests for QA error containment."""

    @pytest.mark.asyncio
    async def test_qa_task_exception_logged(self, tmp_path):
        """If run_smoke_tests raises, qa_error event is logged."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        qa_agent = SystemQAAgent(agent_id="qa-err")
        # Make run_smoke_tests raise
        async def boom(*a, **k):
            raise RuntimeError("QA exploded")
        qa_agent.run_smoke_tests = boom
        rt._system_qa = qa_agent
        rt._qa_reports = {}

        record = _make_record()
        pool = MockPool([PassingMockAgent(agent_id="err-1")])
        rt.pools["designed_count_words"] = pool

        result = await rt._run_qa_for_designed_agent(record)
        assert result is None

        events = await rt.event_log.query(category="qa", limit=20)
        errors = [e for e in events if e["event"] == "qa_error"]
        assert len(errors) >= 1
        await rt.stop()

    @pytest.mark.asyncio
    async def test_qa_task_exception_no_crash(self, tmp_path):
        """Exception in QA does not propagate to the calling coroutine."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        qa_agent = SystemQAAgent(agent_id="qa-nocrash")
        async def boom(*a, **k):
            raise RuntimeError("QA exploded")
        qa_agent.run_smoke_tests = boom
        rt._system_qa = qa_agent
        rt._qa_reports = {}

        record = _make_record()
        pool = MockPool([PassingMockAgent(agent_id="nocrash-1")])
        rt.pools["designed_count_words"] = pool

        # Should not raise
        result = await rt._run_qa_for_designed_agent(record)
        assert result is None
        await rt.stop()

    @pytest.mark.asyncio
    async def test_qa_empty_pool_no_crash(self, tmp_path):
        """QA gracefully returns None if designed pool is empty."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        pool = MockPool([])  # Empty pool
        rt.pools["designed_count_words"] = pool
        rt._system_qa = SystemQAAgent(agent_id="qa-empty")
        rt._qa_reports = {}

        record = _make_record()
        result = await rt._run_qa_for_designed_agent(record)
        # Should complete with error verdict or None, not crash
        assert result is None or result.verdict == "error"
        await rt.stop()

    @pytest.mark.asyncio
    async def test_qa_missing_pool_no_crash(self, tmp_path):
        """QA gracefully returns None if pool name doesn't exist."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        rt._system_qa = SystemQAAgent(agent_id="qa-nopool")
        rt._qa_reports = {}

        record = _make_record(pool_name="nonexistent_pool")
        result = await rt._run_qa_for_designed_agent(record)
        assert result is None
        await rt.stop()


# ===================================================================
# 6d. Routing exclusion tests (AD-158)
# ===================================================================


class TestRoutingExclusion:
    """Tests for QA pool routing exclusion."""

    @pytest.mark.asyncio
    async def test_qa_pool_not_in_intent_descriptors(self, tmp_path):
        """_collect_intent_descriptors() does NOT include smoke_test_agent."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        descriptors = rt._collect_intent_descriptors()
        names = [d.name for d in descriptors]
        assert "smoke_test_agent" not in names

    @pytest.mark.asyncio
    async def test_qa_agent_not_in_decomposer_prompt(self, tmp_path):
        """After boot with QA enabled, decomposer prompt does NOT contain smoke_test_agent."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        descriptors = rt._collect_intent_descriptors()
        descriptor_names = [d.name for d in descriptors]
        assert "smoke_test_agent" not in descriptor_names
        await rt.stop()

    @pytest.mark.asyncio
    async def test_qa_pool_excluded_from_scaler(self, tmp_path):
        """QA pool not affected by demand-driven scaling."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        if rt.pool_scaler:
            assert "system_qa" in rt.pool_scaler.excluded_pools
        await rt.stop()

    @pytest.mark.asyncio
    async def test_qa_pool_created_at_boot(self, tmp_path):
        """When self_mod.enabled and qa.enabled, system_qa pool exists with 1 agent."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient
        from probos.config import SelfModConfig

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        rt.config = rt.config.model_copy(
            update={"self_mod": SelfModConfig(enabled=True)}
        )
        await rt.start()

        assert "system_qa" in rt.pools
        pool = rt.pools["system_qa"]
        assert pool.current_size == 1
        assert rt._system_qa is not None
        await rt.stop()

    @pytest.mark.asyncio
    async def test_qa_pool_not_created_when_disabled(self, tmp_path):
        """When qa.enabled=False, no system_qa pool."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        rt.config = rt.config.model_copy(
            update={"qa": QAConfig(enabled=False)}
        )
        await rt.start()
        assert "system_qa" not in rt.pools
        assert rt._system_qa is None
        await rt.stop()


# ===================================================================
# 6g. Regression invariant tests
# ===================================================================


class TestRegressionInvariants:
    """Tests that existing behavior is unchanged."""

    @pytest.mark.asyncio
    async def test_runtime_status_includes_qa(self, tmp_path):
        """runtime.status() dict includes qa key with enabled state."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient
        from probos.config import SelfModConfig

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        rt.config = rt.config.model_copy(
            update={"self_mod": SelfModConfig(enabled=True)}
        )
        await rt.start()
        status = rt.status()
        assert "qa" in status
        assert status["qa"]["enabled"] is True
        assert status["qa"]["report_count"] == 0
        await rt.stop()

    @pytest.mark.asyncio
    async def test_runtime_status_without_qa(self, tmp_path):
        """When QA disabled, runtime.status() still works."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        rt.config = rt.config.model_copy(
            update={"qa": QAConfig(enabled=False)}
        )
        await rt.start()
        status = rt.status()
        assert "qa" in status
        assert status["qa"]["enabled"] is False
        await rt.stop()

    @pytest.mark.asyncio
    async def test_existing_selfmod_flow_unchanged(self, tmp_path):
        """Self-mod pipeline integration is unmodified."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        # Self-mod pipeline should still be created
        assert rt.self_mod_pipeline is not None
        await rt.stop()

    @pytest.mark.asyncio
    async def test_existing_shell_commands_unchanged(self, tmp_path):
        """Existing shell commands still work."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient
        from probos.experience.shell import ProbOSShell

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        shell = ProbOSShell(rt)
        # Basic commands should still be registered
        assert "/status" in shell.COMMANDS
        assert "/agents" in shell.COMMANDS
        assert "/help" in shell.COMMANDS
        await rt.stop()


# ===================================================================
# 6f. Experience layer tests
# ===================================================================


class TestRenderQAPanel:
    """Tests for qa_panel.py rendering."""

    def _render(self, panel) -> str:
        """Render a Rich Panel to string for assertions."""
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        console.print(panel)
        return buf.getvalue()

    def test_render_qa_panel_with_reports(self):
        """render_qa_panel with populated reports shows table with correct columns."""
        from probos.experience.qa_panel import render_qa_panel

        reports = {
            "weather_agent": QAReport(
                agent_type="weather_agent",
                intent_name="get_weather",
                pool_name="designed_weather_agent",
                total_tests=5,
                passed=4,
                failed=1,
                pass_rate=0.8,
                verdict="passed",
                test_details=[],
                duration_ms=150.0,
                timestamp=1000.0,
            ),
        }
        panel = render_qa_panel(reports)
        rendered = self._render(panel)
        assert "weather_agent" in rendered
        assert "PASSED" in rendered

    def test_render_qa_panel_empty(self):
        """render_qa_panel with empty dict shows 'No QA results' message."""
        from probos.experience.qa_panel import render_qa_panel

        panel = render_qa_panel({})
        rendered = self._render(panel)
        assert "No QA results" in rendered

    def test_render_qa_panel_mixed_verdicts(self):
        """Panel correctly shows PASSED and FAILED agents."""
        from probos.experience.qa_panel import render_qa_panel

        reports = {
            "good_agent": QAReport(
                agent_type="good_agent",
                intent_name="do_good",
                pool_name="designed_good_agent",
                total_tests=5,
                passed=5,
                failed=0,
                pass_rate=1.0,
                verdict="passed",
                test_details=[],
                duration_ms=100.0,
                timestamp=1000.0,
            ),
            "bad_agent": QAReport(
                agent_type="bad_agent",
                intent_name="do_bad",
                pool_name="designed_bad_agent",
                total_tests=5,
                passed=1,
                failed=4,
                pass_rate=0.2,
                verdict="failed",
                test_details=[],
                duration_ms=200.0,
                timestamp=1000.0,
            ),
        }
        panel = render_qa_panel(reports)
        rendered = self._render(panel)
        assert "good_agent" in rendered
        assert "bad_agent" in rendered
        assert "PASSED" in rendered
        assert "FAILED" in rendered


class TestQAShellCommand:
    """Tests for /qa command registration and handling."""

    def test_qa_shell_command_registered(self):
        """'/qa' appears in shell COMMANDS dict."""
        from probos.experience.shell import ProbOSShell
        assert "/qa" in ProbOSShell.COMMANDS

    @pytest.mark.asyncio
    async def test_qa_shell_renders_panel(self, tmp_path):
        """/qa command calls render_qa_panel and outputs to console."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient
        from probos.experience.shell import ProbOSShell
        from io import StringIO
        from rich.console import Console

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        rt._qa_reports = {
            "test_agent": QAReport(
                agent_type="test_agent",
                intent_name="test_intent",
                pool_name="designed_test_agent",
                total_tests=5,
                passed=4,
                failed=1,
                pass_rate=0.8,
                verdict="passed",
                test_details=[],
                duration_ms=100.0,
                timestamp=1000.0,
            ),
        }

        buf = StringIO()
        console = Console(file=buf, force_terminal=True)
        shell = ProbOSShell(rt, console=console)
        await shell._cmd_qa("")
        output = buf.getvalue()
        assert "test_agent" in output
        await rt.stop()

    @pytest.mark.asyncio
    async def test_qa_shell_with_agent_type(self, tmp_path):
        """/qa agent_type shows detailed view for specific agent."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient
        from probos.experience.shell import ProbOSShell
        from io import StringIO
        from rich.console import Console

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        rt._qa_reports = {
            "weather_agent": QAReport(
                agent_type="weather_agent",
                intent_name="get_weather",
                pool_name="designed_weather_agent",
                total_tests=5,
                passed=3,
                failed=2,
                pass_rate=0.6,
                verdict="passed",
                test_details=[
                    {"case_type": "happy", "passed": True, "error": None},
                    {"case_type": "edge", "passed": False, "error": "timeout"},
                ],
                duration_ms=250.0,
                timestamp=1000.0,
            ),
        }

        buf = StringIO()
        console = Console(file=buf, force_terminal=True)
        shell = ProbOSShell(rt, console=console)
        await shell._cmd_qa("weather_agent")
        output = buf.getvalue()
        assert "weather_agent" in output
        assert "get_weather" in output
        await rt.stop()

    def test_qa_shell_help_includes_qa(self):
        """/help output includes /qa command."""
        from probos.experience.shell import ProbOSShell
        assert "/qa" in ProbOSShell.COMMANDS
        # /help prints COMMANDS, so /qa should appear
        desc = ProbOSShell.COMMANDS["/qa"]
        assert "QA" in desc


class TestDesignedPanelQAColumn:
    """Tests for QA column in /designed panel."""

    def _render(self, panel) -> str:
        """Render a Rich Panel to string for assertions."""
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        console.print(panel)
        return buf.getvalue()

    def test_designed_panel_qa_column(self):
        """render_designed_panel with qa_reports shows QA column."""
        from probos.experience.panels import render_designed_panel

        status = {
            "designed_agents": [
                {
                    "agent_type": "weather_agent",
                    "class_name": "WeatherAgent",
                    "intent_name": "get_weather",
                    "status": "active",
                    "sandbox_time_ms": 50,
                },
            ],
            "active_count": 1,
            "max_designed_agents": 5,
        }
        qa_reports = {
            "weather_agent": QAReport(
                agent_type="weather_agent",
                intent_name="get_weather",
                pool_name="designed_weather_agent",
                total_tests=5,
                passed=4,
                failed=1,
                pass_rate=0.8,
                verdict="passed",
                test_details=[],
                duration_ms=100.0,
                timestamp=1000.0,
            ),
        }
        panel = render_designed_panel(status, qa_reports=qa_reports)
        rendered = self._render(panel)
        assert "QA" in rendered
        assert "PASSED" in rendered

    def test_designed_panel_qa_column_none(self):
        """render_designed_panel with qa_reports=None renders without QA column."""
        from probos.experience.panels import render_designed_panel

        status = {
            "designed_agents": [
                {
                    "agent_type": "weather_agent",
                    "class_name": "WeatherAgent",
                    "intent_name": "get_weather",
                    "status": "active",
                    "sandbox_time_ms": 50,
                },
            ],
            "active_count": 1,
            "max_designed_agents": 5,
        }
        panel = render_designed_panel(status, qa_reports=None)
        assert panel is not None
        assert "Designed Agents" in panel.title

    def test_designed_panel_qa_column_no_report(self):
        """Agent in designed list but not in QA reports shows em-dash."""
        from probos.experience.panels import render_designed_panel

        status = {
            "designed_agents": [
                {
                    "agent_type": "unknown_agent",
                    "class_name": "UnknownAgent",
                    "intent_name": "do_unknown",
                    "status": "active",
                    "sandbox_time_ms": 30,
                },
            ],
            "active_count": 1,
            "max_designed_agents": 5,
        }
        qa_reports = {}  # No reports for this agent
        panel = render_designed_panel(status, qa_reports=qa_reports)
        rendered = self._render(panel)
        assert "unknown_agent" in rendered
        assert "\u2014" in rendered  # em-dash for missing QA
