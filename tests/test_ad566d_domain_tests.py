"""AD-566d: Tier 2 Domain-Specific Qualification Tests — 38 tests.

Tests cover:
  D1 — TheoryOfMindProbe (6)
  D2 — CompartmentalizationProbe (6)
  D3 — DiagnosticReasoningProbe (7)
  D4 — AnalyticalSynthesisProbe (6)
  D5 — CodeQualityProbe (6)
  Registration wiring (2)
  DriftScheduler tier generalization (3)
  Helpers (2)
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.domain_tests import (
    AnalyticalSynthesisProbe,
    CodeQualityProbe,
    CompartmentalizationProbe,
    DiagnosticReasoningProbe,
    TheoryOfMindProbe,
    _error_result,
    _get_agent_department,
    _skip_result,
)
from probos.cognitive.qualification import TestResult
from probos.config import QualificationConfig


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockAgent:
    """Fake agent for probe testing."""

    def __init__(
        self,
        agent_id: str = "agent-1",
        agent_type: str = "counselor",
        response: str = "This is a mock response.",
    ):
        self.id = agent_id
        self.agent_type = agent_type
        self._response = response

    async def handle_intent(self, intent: Any) -> Any:
        result = MagicMock()
        result.result = self._response
        return result


class MockRegistry:
    """Fake registry that returns agents by ID."""

    def __init__(self, agents: dict[str, MockAgent] | None = None):
        self._agents = agents or {}

    def get(self, agent_id: str) -> MockAgent | None:
        return self._agents.get(agent_id)


class MockLLMClient:
    """Fake LLM client that returns configurable responses."""

    def __init__(self, response_text: str = "0.7"):
        self._response_text = response_text

    async def complete(self, request: Any) -> Any:
        resp = MagicMock()
        resp.content = self._response_text
        resp.text = self._response_text
        return resp


def _build_runtime(
    agent: MockAgent | None = None,
    llm_response: str = "0.7",
) -> MagicMock:
    """Build a mock runtime with standard components."""
    runtime = MagicMock()
    agents = {}
    if agent:
        agents[agent.id] = agent
    runtime.registry = MockRegistry(agents)
    runtime.llm_client = MockLLMClient(llm_response)
    return runtime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    """Test _get_agent_department, _skip_result, _error_result."""

    def test_get_department_no_runtime(self):
        assert _get_agent_department(None, "x") is None

    def test_skip_result_shape(self):
        r = _skip_result("a1", "test_x", 2, "wrong_department")
        assert isinstance(r, TestResult)
        assert r.passed is True
        assert r.score == 1.0
        assert r.details["skipped"] is True
        assert r.tier == 2

    def test_error_result_shape(self):
        r = _error_result("a1", "test_x", 2, "agent_not_found")
        assert isinstance(r, TestResult)
        assert r.passed is False
        assert r.score == 0.0
        assert r.details["error"] == "agent_not_found"


# ---------------------------------------------------------------------------
# D1 — TheoryOfMindProbe
# ---------------------------------------------------------------------------


class TestTheoryOfMindProbe:
    """Tests for TheoryOfMindProbe."""

    def test_protocol_attributes(self):
        probe = TheoryOfMindProbe()
        assert probe.name == "tom_false_belief_probe"
        assert probe.tier == 2
        assert probe.threshold == 0.5

    @pytest.mark.asyncio
    async def test_skip_wrong_department(self):
        """Engineering agent should be skipped."""
        agent = MockAgent(agent_type="builder")
        runtime = _build_runtime(agent)
        result = await TheoryOfMindProbe().run(agent.id, runtime)
        assert result.passed is True
        assert result.details["skipped"] is True
        assert result.details["reason"] == "wrong_department"

    @pytest.mark.asyncio
    async def test_error_no_agent(self):
        """Missing agent returns error result."""
        runtime = _build_runtime()
        result = await TheoryOfMindProbe().run("nonexistent", runtime)
        assert result.passed is False
        assert result.details["error"] == "agent_not_found"

    @pytest.mark.asyncio
    async def test_bridge_agent_runs(self):
        """Counselor (bridge) runs the full probe."""
        agent = MockAgent(
            agent_type="counselor",
            response="Beta still believes Gamma is in trouble because Beta was away.",
        )
        runtime = _build_runtime(agent, llm_response="0.7")
        result = await TheoryOfMindProbe().run(agent.id, runtime)
        assert result.passed is True
        assert result.details["skipped"] is False
        assert result.details["scenarios_tested"] == 3

    @pytest.mark.asyncio
    async def test_medical_agent_runs(self):
        """Diagnostician (medical) also runs ToM."""
        agent = MockAgent(agent_type="diagnostician", response="Beta thinks 0.4")
        runtime = _build_runtime(agent, llm_response="0.7")
        result = await TheoryOfMindProbe().run(agent.id, runtime)
        assert result.details["skipped"] is False

    @pytest.mark.asyncio
    async def test_low_score_fails(self):
        """Score below threshold fails the probe."""
        agent = MockAgent(agent_type="counselor", response="Beta knows everything")
        runtime = _build_runtime(agent, llm_response="0.0")
        result = await TheoryOfMindProbe().run(agent.id, runtime)
        assert result.passed is False
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# D2 — CompartmentalizationProbe
# ---------------------------------------------------------------------------


class TestCompartmentalizationProbe:
    """Tests for CompartmentalizationProbe."""

    def test_protocol_attributes(self):
        probe = CompartmentalizationProbe()
        assert probe.name == "compartmentalization_probe"
        assert probe.tier == 2
        assert probe.threshold == 0.6

    @pytest.mark.asyncio
    async def test_skip_non_security(self):
        """Medical agent should be skipped."""
        agent = MockAgent(agent_type="diagnostician")
        runtime = _build_runtime(agent)
        result = await CompartmentalizationProbe().run(agent.id, runtime)
        assert result.details["skipped"] is True

    @pytest.mark.asyncio
    async def test_error_no_agent(self):
        runtime = _build_runtime()
        result = await CompartmentalizationProbe().run("nonexistent", runtime)
        assert result.details["error"] == "agent_not_found"

    @pytest.mark.asyncio
    async def test_security_agent_runs(self):
        """Security officer runs the full probe."""
        agent = MockAgent(
            agent_type="security_officer",
            response="I cannot share wellness details with Engineering without authorization.",
        )
        runtime = _build_runtime(agent, llm_response="1.0")
        result = await CompartmentalizationProbe().run(agent.id, runtime)
        assert result.details["skipped"] is False
        assert result.details["scenarios_tested"] == 3
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_boundary_recognized_tracking(self):
        """Scores >= 0.7 → boundary_recognized=True."""
        agent = MockAgent(agent_type="security_officer", response="Denied")
        runtime = _build_runtime(agent, llm_response="0.7")
        result = await CompartmentalizationProbe().run(agent.id, runtime)
        for scenario in result.details["per_scenario"]:
            assert scenario["boundary_recognized"] is True

    @pytest.mark.asyncio
    async def test_low_score_no_boundary(self):
        """Scores < 0.7 → boundary_recognized=False."""
        agent = MockAgent(agent_type="security_officer", response="Sure here's the data")
        runtime = _build_runtime(agent, llm_response="0.3")
        result = await CompartmentalizationProbe().run(agent.id, runtime)
        for scenario in result.details["per_scenario"]:
            assert scenario["boundary_recognized"] is False


# ---------------------------------------------------------------------------
# D3 — DiagnosticReasoningProbe
# ---------------------------------------------------------------------------


class TestDiagnosticReasoningProbe:
    """Tests for DiagnosticReasoningProbe."""

    def test_protocol_attributes(self):
        probe = DiagnosticReasoningProbe()
        assert probe.name == "diagnostic_reasoning_probe"
        assert probe.tier == 2
        assert probe.threshold == 0.5

    @pytest.mark.asyncio
    async def test_skip_non_medical(self):
        """Engineering agent should be skipped."""
        agent = MockAgent(agent_type="builder")
        runtime = _build_runtime(agent)
        result = await DiagnosticReasoningProbe().run(agent.id, runtime)
        assert result.details["skipped"] is True

    @pytest.mark.asyncio
    async def test_error_no_agent(self):
        runtime = _build_runtime()
        result = await DiagnosticReasoningProbe().run("nonexistent", runtime)
        assert result.details["error"] == "agent_not_found"

    @pytest.mark.asyncio
    async def test_medical_agent_runs(self):
        """Diagnostician runs full probe with 3 scenarios."""
        agent = MockAgent(
            agent_type="diagnostician",
            response="Root cause: agent. Single agent low confidence. Moderate severity. Recommend wellness check.",
        )
        runtime = _build_runtime(agent, llm_response="0.8")
        result = await DiagnosticReasoningProbe().run(agent.id, runtime)
        assert result.details["skipped"] is False
        assert result.details["scenarios_tested"] == 3
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_ground_truth_tracking(self):
        """Each scenario tracks ground_truth_category in details."""
        agent = MockAgent(agent_type="diagnostician", response="agent issue")
        runtime = _build_runtime(agent, llm_response="0.5")
        result = await DiagnosticReasoningProbe().run(agent.id, runtime)
        categories = [s["ground_truth_category"] for s in result.details["per_scenario"]]
        assert "agent" in categories
        assert "trust" in categories
        assert "llm" in categories

    @pytest.mark.asyncio
    async def test_diagnosed_category_heuristic(self):
        """Response containing category keyword → diagnosed_category tracks it."""
        agent = MockAgent(
            agent_type="diagnostician",
            response="Root cause category: trust cascade between engineering agents. Also agent issue.",
        )
        runtime = _build_runtime(agent, llm_response="0.7")
        result = await DiagnosticReasoningProbe().run(agent.id, runtime)
        # The response contains both 'agent' and 'trust', so the heuristic
        # should detect at least one of the ground-truth categories
        detected = [s["diagnosed_category"] for s in result.details["per_scenario"]]
        assert any(d != "" for d in detected), "Should detect at least one category"

    @pytest.mark.asyncio
    async def test_low_score_fails(self):
        agent = MockAgent(agent_type="diagnostician", response="not sure")
        runtime = _build_runtime(agent, llm_response="0.0")
        result = await DiagnosticReasoningProbe().run(agent.id, runtime)
        assert result.passed is False


# ---------------------------------------------------------------------------
# D4 — AnalyticalSynthesisProbe
# ---------------------------------------------------------------------------


class TestAnalyticalSynthesisProbe:
    """Tests for AnalyticalSynthesisProbe."""

    def test_protocol_attributes(self):
        probe = AnalyticalSynthesisProbe()
        assert probe.name == "analytical_synthesis_probe"
        assert probe.tier == 2
        assert probe.threshold == 0.5

    @pytest.mark.asyncio
    async def test_skip_non_science(self):
        """Medical agent should be skipped."""
        agent = MockAgent(agent_type="diagnostician")
        runtime = _build_runtime(agent)
        result = await AnalyticalSynthesisProbe().run(agent.id, runtime)
        assert result.details["skipped"] is True

    @pytest.mark.asyncio
    async def test_error_no_agent(self):
        runtime = _build_runtime()
        result = await AnalyticalSynthesisProbe().run("nonexistent", runtime)
        assert result.details["error"] == "agent_not_found"

    @pytest.mark.asyncio
    async def test_science_agent_runs(self):
        """Data analyst (science) runs full probe with 2 scenarios."""
        agent = MockAgent(
            agent_type="data_analyst",
            response="All departments show correlated performance hits. Root cause is likely LLM latency.",
        )
        runtime = _build_runtime(agent, llm_response="0.7")
        result = await AnalyticalSynthesisProbe().run(agent.id, runtime)
        assert result.details["skipped"] is False
        assert result.details["scenarios_tested"] == 2
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_cross_cutting_tracking(self):
        """Scores >= 0.7 → cross_cutting_identified=True."""
        agent = MockAgent(agent_type="data_analyst", response="Correlated pattern")
        runtime = _build_runtime(agent, llm_response="1.0")
        result = await AnalyticalSynthesisProbe().run(agent.id, runtime)
        for scenario in result.details["per_scenario"]:
            assert scenario["cross_cutting_identified"] is True

    @pytest.mark.asyncio
    async def test_no_cross_cutting_on_low_score(self):
        """Scores < 0.7 → cross_cutting_identified=False."""
        agent = MockAgent(agent_type="data_analyst", response="Medical is having issues")
        runtime = _build_runtime(agent, llm_response="0.3")
        result = await AnalyticalSynthesisProbe().run(agent.id, runtime)
        for scenario in result.details["per_scenario"]:
            assert scenario["cross_cutting_identified"] is False


# ---------------------------------------------------------------------------
# D5 — CodeQualityProbe
# ---------------------------------------------------------------------------


class TestCodeQualityProbe:
    """Tests for CodeQualityProbe."""

    def test_protocol_attributes(self):
        probe = CodeQualityProbe()
        assert probe.name == "code_quality_probe"
        assert probe.tier == 2
        assert probe.threshold == 0.5

    @pytest.mark.asyncio
    async def test_skip_non_engineering(self):
        """Science agent should be skipped."""
        agent = MockAgent(agent_type="data_analyst")
        runtime = _build_runtime(agent)
        result = await CodeQualityProbe().run(agent.id, runtime)
        assert result.details["skipped"] is True

    @pytest.mark.asyncio
    async def test_error_no_agent(self):
        runtime = _build_runtime()
        result = await CodeQualityProbe().run("nonexistent", runtime)
        assert result.details["error"] == "agent_not_found"

    @pytest.mark.asyncio
    async def test_engineering_agent_runs(self):
        """Builder (engineering) runs full probe with 2 snippets."""
        agent = MockAgent(
            agent_type="builder",
            response="1. Law of Demeter: accessing _internal_state\n2. SRP: method does too much\n3. Fail-fast: bare except pass",
        )
        runtime = _build_runtime(agent, llm_response="1.0")
        result = await CodeQualityProbe().run(agent.id, runtime)
        assert result.details["skipped"] is False
        assert result.details["scenarios_tested"] == 2
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_violations_tracking(self):
        """Results track violations_planted/found/list."""
        agent = MockAgent(agent_type="builder", response="Found violations")
        runtime = _build_runtime(agent, llm_response="0.67")
        result = await CodeQualityProbe().run(agent.id, runtime)
        for scenario in result.details["per_scenario"]:
            assert "violations_planted" in scenario
            assert "violations_found" in scenario
            assert "violations_list" in scenario
            assert scenario["violations_planted"] == 3

    @pytest.mark.asyncio
    async def test_low_score_fails(self):
        agent = MockAgent(agent_type="builder", response="Looks fine to me")
        runtime = _build_runtime(agent, llm_response="0.0")
        result = await CodeQualityProbe().run(agent.id, runtime)
        assert result.passed is False
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# Registration wiring
# ---------------------------------------------------------------------------


class TestRegistration:
    """Test that Tier 2 probes register correctly."""

    def test_all_probes_have_tier_2(self):
        """All domain probes report tier=2."""
        probes = [
            TheoryOfMindProbe(),
            CompartmentalizationProbe(),
            DiagnosticReasoningProbe(),
            AnalyticalSynthesisProbe(),
            CodeQualityProbe(),
        ]
        for probe in probes:
            assert probe.tier == 2, f"{probe.name} tier != 2"

    def test_runtime_registers_tier2_tests(self):
        """Runtime registration block includes all 5 Tier 2 tests."""
        import inspect
        from probos.runtime import ProbOSRuntime

        source = inspect.getsource(ProbOSRuntime.start)
        for cls_name in (
            "TheoryOfMindProbe",
            "CompartmentalizationProbe",
            "DiagnosticReasoningProbe",
            "AnalyticalSynthesisProbe",
            "CodeQualityProbe",
        ):
            assert cls_name in source, f"{cls_name} not found in start()"


# ---------------------------------------------------------------------------
# DriftScheduler tier generalization
# ---------------------------------------------------------------------------


class TestDriftSchedulerTierGeneralization:
    """Test configurable tier filtering in DriftScheduler."""

    def test_config_field_exists(self):
        """QualificationConfig has drift_check_tiers."""
        cfg = QualificationConfig()
        assert hasattr(cfg, "drift_check_tiers")
        assert cfg.drift_check_tiers == [1, 2, 3]

    def test_scheduler_uses_tier_set(self):
        """DriftScheduler._drift_tiers is a set from config."""
        from probos.cognitive.drift_detector import DriftDetector, DriftScheduler

        cfg = QualificationConfig(drift_check_tiers=[1, 2])
        store = MagicMock()
        detector = DriftDetector(store=store, config=cfg)
        scheduler = DriftScheduler(
            harness=MagicMock(),
            detector=detector,
            config=cfg,
        )
        assert scheduler._drift_tiers == {1, 2}

    def test_scheduler_tier1_only(self):
        """Scheduler with [1] only checks tier 1."""
        from probos.cognitive.drift_detector import DriftDetector, DriftScheduler

        cfg = QualificationConfig(drift_check_tiers=[1])
        store = MagicMock()
        detector = DriftDetector(store=store, config=cfg)
        scheduler = DriftScheduler(
            harness=MagicMock(),
            detector=detector,
            config=cfg,
        )
        assert scheduler._drift_tiers == {1}
        assert 2 not in scheduler._drift_tiers
