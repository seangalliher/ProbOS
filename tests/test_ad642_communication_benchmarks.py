"""AD-642: Communication Quality Benchmarks tests.

Infrastructure tests (scoring, rubric parsing, protocol compliance, registration),
probe tests (2 per probe), and Counselor integration tests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.communication_benchmarks import (
    ALL_COMMUNICATION_PROBES,
    CommunicationQualityProbe,
    CommunicationScore,
    DMActionProbe,
    ExpertiseProbe,
    MemoryAbsenceProbe,
    MemoryGroundingProbe,
    SilenceAppropriatenessProbe,
    ThreadRelevanceProbe,
    _DIMENSION_WEIGHTS,
    _score_response,
    _send_chain_probe,
)
from probos.cognitive.qualification import QualificationTest, TestResult
from probos.config import CommunicationBenchmarksConfig, QualificationConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_llm_response(content: str = "{}"):
    resp = MagicMock()
    resp.content = content
    resp.tokens_used = 50
    resp.tier = "fast"
    return resp


def _mock_agent(agent_id: str = "agent-1", department: str = "science", callsign: str = "Kira"):
    agent = AsyncMock()
    agent.id = agent_id
    agent.department = department
    agent.callsign = callsign
    agent._department = department
    agent._callsign = callsign
    return agent


def _mock_runtime(agent=None, llm_content: str = "{}"):
    runtime = MagicMock()
    if agent is None:
        agent = _mock_agent()
    runtime.registry.get.return_value = agent
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=_mock_llm_response(llm_content))
    runtime.llm_client = llm
    return runtime


def _good_score_json() -> str:
    return (
        '{"relevance": 0.9, "memory_grounding": 0.8, "expertise_coloring": 0.85, '
        '"action_appropriateness": 0.75, "voice_consistency": 0.7, '
        '"justifications": {"relevance": "good", "memory_grounding": "solid", '
        '"expertise_coloring": "on point", "action_appropriateness": "ok", '
        '"voice_consistency": "consistent"}}'
    )


def _bad_score_json() -> str:
    return (
        '{"relevance": 0.2, "memory_grounding": 0.1, "expertise_coloring": 0.15, '
        '"action_appropriateness": 0.1, "voice_consistency": 0.2, '
        '"justifications": {"relevance": "off topic", "memory_grounding": "fabricated"}}'
    )


# ===========================================================================
# CommunicationScore tests (5)
# ===========================================================================

class TestCommunicationScore:
    def test_composite_weighted_average(self):
        score = CommunicationScore(
            relevance=1.0,
            memory_grounding=1.0,
            expertise_coloring=1.0,
            action_appropriateness=1.0,
            voice_consistency=1.0,
        )
        assert abs(score.composite - 1.0) < 0.001

    def test_composite_zero(self):
        score = CommunicationScore()
        assert score.composite == 0.0

    def test_composite_weighted_correctly(self):
        score = CommunicationScore(
            relevance=0.5,
            memory_grounding=0.0,
            expertise_coloring=0.0,
            action_appropriateness=0.0,
            voice_consistency=0.0,
        )
        expected = 0.5 * 0.30
        assert abs(score.composite - expected) < 0.001

    def test_to_dict_keys(self):
        score = CommunicationScore(relevance=0.8, justifications={"relevance": "good"})
        d = score.to_dict()
        assert "relevance" in d
        assert "memory_grounding" in d
        assert "expertise_coloring" in d
        assert "action_appropriateness" in d
        assert "voice_consistency" in d
        assert "composite" in d
        assert "justifications" in d
        assert d["justifications"]["relevance"] == "good"

    def test_dimension_weights_sum_to_one(self):
        total = sum(_DIMENSION_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001


# ===========================================================================
# _score_response tests (6)
# ===========================================================================

class TestScoreResponse:
    @pytest.mark.asyncio
    async def test_none_client_returns_zero(self):
        score = await _score_response(None, "scenario", "response", "rubric")
        assert score.composite == 0.0

    @pytest.mark.asyncio
    async def test_valid_json_parsed(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_mock_llm_response(_good_score_json()))
        score = await _score_response(llm, "scenario", "response", "rubric")
        assert score.relevance == 0.9
        assert score.memory_grounding == 0.8
        assert score.expertise_coloring == 0.85

    @pytest.mark.asyncio
    async def test_invalid_json_returns_zero(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_mock_llm_response("not json at all"))
        score = await _score_response(llm, "scenario", "response", "rubric")
        assert score.composite == 0.0

    @pytest.mark.asyncio
    async def test_llm_exception_returns_zero(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("timeout"))
        score = await _score_response(llm, "scenario", "response", "rubric")
        assert score.composite == 0.0

    @pytest.mark.asyncio
    async def test_values_clamped_to_0_1(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_mock_llm_response(
            '{"relevance": 1.5, "memory_grounding": -0.3, '
            '"expertise_coloring": 0.5, "action_appropriateness": 2.0, '
            '"voice_consistency": 0.7}'
        ))
        score = await _score_response(llm, "scenario", "response", "rubric")
        assert score.relevance == 1.0
        assert score.memory_grounding == 0.0
        assert score.action_appropriateness == 1.0

    @pytest.mark.asyncio
    async def test_justifications_preserved(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_mock_llm_response(
            '{"relevance": 0.8, "memory_grounding": 0.7, '
            '"expertise_coloring": 0.6, "action_appropriateness": 0.5, '
            '"voice_consistency": 0.4, '
            '"justifications": {"relevance": "addressed topic well"}}'
        ))
        score = await _score_response(llm, "scenario", "response", "rubric")
        assert score.justifications["relevance"] == "addressed topic well"


# ===========================================================================
# _send_chain_probe tests (3)
# ===========================================================================

class TestSendChainProbe:
    @pytest.mark.asyncio
    async def test_builds_correct_intent(self):
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="Response text"))

        result = await _send_chain_probe(
            agent,
            channel_name="all-hands",
            author_callsign="Captain",
            title="Test",
            text="Test text",
            probe_name="test_probe",
        )
        call_args = agent.handle_intent.call_args[0][0]
        assert call_args.intent == "ward_room_notification"
        assert call_args.params["_qualification_test"] is True
        assert call_args.params["channel_name"] == "all-hands"
        assert "benchmark-test_probe-" in call_args.params["thread_id"]

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self):
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(side_effect=RuntimeError("boom"))
        result = await _send_chain_probe(
            agent,
            channel_name="all-hands",
            author_callsign="Captain",
            title="Test",
            text="Test",
            probe_name="test_probe",
        )
        assert result == ""

    @pytest.mark.asyncio
    async def test_extra_params_merged(self):
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="ok"))
        await _send_chain_probe(
            agent,
            channel_name="all-hands",
            author_callsign="Captain",
            title="Test",
            text="Test",
            probe_name="test_probe",
            extra_params={"_formatted_memories": "some memory"},
        )
        call_args = agent.handle_intent.call_args[0][0]
        assert call_args.params["_formatted_memories"] == "some memory"


# ===========================================================================
# Protocol compliance tests (4)
# ===========================================================================

class TestProtocolCompliance:
    def test_all_probes_have_required_attributes(self):
        for probe in ALL_COMMUNICATION_PROBES:
            assert hasattr(probe, "name")
            assert hasattr(probe, "tier")
            assert hasattr(probe, "description")
            assert hasattr(probe, "threshold")
            assert hasattr(probe, "run")

    def test_all_probes_are_tier_2(self):
        for probe in ALL_COMMUNICATION_PROBES:
            assert probe.tier == 2

    def test_probe_names_unique(self):
        names = [p.name for p in ALL_COMMUNICATION_PROBES]
        assert len(names) == len(set(names))

    def test_six_probes_registered(self):
        assert len(ALL_COMMUNICATION_PROBES) == 6

    def test_probe_names_match_expected(self):
        names = {p.name for p in ALL_COMMUNICATION_PROBES}
        expected = {
            "comm_thread_relevance",
            "comm_memory_grounding",
            "comm_memory_absence",
            "comm_expertise_coloring",
            "comm_silence_appropriateness",
            "comm_dm_action",
        }
        assert names == expected


# ===========================================================================
# Probe tests — 2 per probe (12 total)
# ===========================================================================

class TestThreadRelevanceProbe:
    @pytest.mark.asyncio
    async def test_good_response_passes(self):
        probe = ThreadRelevanceProbe()
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="Relevant response"))
        runtime = _mock_runtime(agent=agent, llm_content=_good_score_json())

        result = await probe.run("agent-1", runtime)
        assert isinstance(result, TestResult)
        assert result.score > probe.threshold
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_bad_response_fails(self):
        probe = ThreadRelevanceProbe()
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="Bad"))
        runtime = _mock_runtime(agent=agent, llm_content=_bad_score_json())

        result = await probe.run("agent-1", runtime)
        assert result.score < probe.threshold
        assert result.passed is False


class TestMemoryGroundingProbe:
    @pytest.mark.asyncio
    async def test_grounded_response_passes(self):
        probe = MemoryGroundingProbe()
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="Grounded response"))
        runtime = _mock_runtime(agent=agent, llm_content=_good_score_json())

        result = await probe.run("agent-1", runtime)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fabricated_response_fails(self):
        probe = MemoryGroundingProbe()
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="Fabricated details"))
        runtime = _mock_runtime(agent=agent, llm_content=_bad_score_json())

        result = await probe.run("agent-1", runtime)
        assert result.passed is False


class TestMemoryAbsenceProbe:
    @pytest.mark.asyncio
    async def test_honest_uncertainty_passes(self):
        probe = MemoryAbsenceProbe()
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="I don't recall"))
        runtime = _mock_runtime(agent=agent, llm_content=_good_score_json())

        result = await probe.run("agent-1", runtime)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_confabulation_fails(self):
        probe = MemoryAbsenceProbe()
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="I found thread abc123"))
        runtime = _mock_runtime(agent=agent, llm_content=_bad_score_json())

        result = await probe.run("agent-1", runtime)
        assert result.passed is False


class TestExpertiseProbe:
    @pytest.mark.asyncio
    async def test_expertise_focused_passes(self):
        probe = ExpertiseProbe()
        agent = _mock_agent(department="medical", callsign="Bones")
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="Medical response"))
        runtime = _mock_runtime(agent=agent, llm_content=_good_score_json())

        result = await probe.run("agent-1", runtime)
        assert result.passed is True
        assert result.details["department"] == "medical"

    @pytest.mark.asyncio
    async def test_wrong_expertise_fails(self):
        probe = ExpertiseProbe()
        agent = _mock_agent(department="medical", callsign="Bones")
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="Wrong focus"))
        runtime = _mock_runtime(agent=agent, llm_content=_bad_score_json())

        result = await probe.run("agent-1", runtime)
        assert result.passed is False


class TestSilenceAppropriatenessProbe:
    @pytest.mark.asyncio
    async def test_silence_passes(self):
        probe = SilenceAppropriatenessProbe()
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="[NO_RESPONSE]"))
        runtime = _mock_runtime(agent=agent, llm_content=_good_score_json())

        result = await probe.run("agent-1", runtime)
        assert probe.threshold == 0.4  # Lower threshold
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_unnecessary_response_fails(self):
        probe = SilenceAppropriatenessProbe()
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="Long irrelevant post"))
        runtime = _mock_runtime(agent=agent, llm_content=_bad_score_json())

        result = await probe.run("agent-1", runtime)
        assert result.passed is False


class TestDMActionProbe:
    @pytest.mark.asyncio
    async def test_dm_action_identified_passes(self):
        probe = DMActionProbe()
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="DM follow-up"))
        runtime = _mock_runtime(agent=agent, llm_content=_good_score_json())

        result = await probe.run("agent-1", runtime)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_public_when_dm_needed_fails(self):
        probe = DMActionProbe()
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="Public broadcast"))
        runtime = _mock_runtime(agent=agent, llm_content=_bad_score_json())

        result = await probe.run("agent-1", runtime)
        assert result.passed is False


# ===========================================================================
# Edge case tests (4)
# ===========================================================================

class TestProbeEdgeCases:
    @pytest.mark.asyncio
    async def test_agent_not_found(self):
        probe = ThreadRelevanceProbe()
        runtime = MagicMock()
        runtime.registry.get.return_value = None
        runtime.llm_client = AsyncMock()

        result = await probe.run("nonexistent", runtime)
        assert result.passed is False
        assert result.error == "Agent not found in registry"

    @pytest.mark.asyncio
    async def test_handle_intent_exception(self):
        probe = ThreadRelevanceProbe()
        agent = _mock_agent()
        agent.handle_intent = AsyncMock(side_effect=RuntimeError("chain failed"))
        runtime = _mock_runtime(agent=agent, llm_content=_good_score_json())

        result = await probe.run("agent-1", runtime)
        # Should not crash — returns a result with low/zero score
        assert isinstance(result, TestResult)
        assert result.agent_id == "agent-1"

    @pytest.mark.asyncio
    async def test_result_includes_details(self):
        probe = ExpertiseProbe()
        agent = _mock_agent(department="engineering", callsign="LaForge")
        agent.handle_intent = AsyncMock(return_value=MagicMock(result="Engineering response"))
        runtime = _mock_runtime(agent=agent, llm_content=_good_score_json())

        result = await probe.run("agent-1", runtime)
        assert result.details["department"] == "engineering"
        assert result.details["callsign"] == "LaForge"
        assert "dimensions" in result.details
        assert "response_preview" in result.details

    @pytest.mark.asyncio
    async def test_probe_department_specific_rubric(self):
        probe = ExpertiseProbe()
        rubric_medical = probe._build_rubric("medical", "Bones")
        rubric_science = probe._build_rubric("science", "Kira")

        assert "casualties" in rubric_medical
        assert "analysis" in rubric_science
        assert rubric_medical != rubric_science


# ===========================================================================
# Config tests (3)
# ===========================================================================

class TestConfig:
    def test_default_config(self):
        config = CommunicationBenchmarksConfig()
        assert config.enabled is True
        assert config.frequency_hours == 12.0
        assert len(config.probes) == 6

    def test_qualification_config_has_benchmarks(self):
        config = QualificationConfig()
        assert hasattr(config, "communication_benchmarks")
        assert isinstance(config.communication_benchmarks, CommunicationBenchmarksConfig)

    def test_disabled_config(self):
        config = CommunicationBenchmarksConfig(enabled=False)
        assert config.enabled is False


# ===========================================================================
# Counselor integration tests (8)
# ===========================================================================

class TestCounselorIntegration:
    def _make_counselor(self):
        """Create a minimal CounselorAgent for testing assess_agent()."""
        from probos.cognitive.counselor import CounselorAgent
        counselor = CounselorAgent.__new__(CounselorAgent)
        counselor.id = "counselor-001"
        counselor.agent_type = "counselor"
        counselor._cognitive_profiles = {}
        counselor._profile_store = None
        counselor._profiles = {}
        counselor._profile_lock = __import__("asyncio").Lock()
        counselor._dm_cooldowns = {}
        counselor._dm_cooldown_seconds = 300.0
        counselor._emit_event_fn = AsyncMock()
        counselor._db_path = ":memory:"
        counselor._send_dm_fn = AsyncMock()
        counselor._registry = MagicMock()
        counselor._registry.get.return_value = None
        counselor._trust_network = MagicMock()
        counselor._trust_network.get_score.return_value = 0.7
        counselor._hebbian_router = MagicMock()
        counselor._hebbian_router.get_weight.return_value = 0.5
        counselor._config = MagicMock()
        counselor._config.trust_delta_threshold = 0.15
        counselor._config.alert_on_red = True
        counselor._config.alert_on_yellow = False
        counselor._ward_room = None
        counselor._ward_room_router = None
        counselor._intervention_targets = set()
        counselor._reminiscence_engine = None
        counselor._reminiscence_cooldowns = {}
        counselor._REMINISCENCE_COOLDOWN_SECONDS = 7200
        counselor._reminiscence_concern_threshold = 3
        counselor._confabulation_alert_threshold = 0.3
        return counselor

    def test_assess_default_comm_quality(self):
        """Default communication_quality=1.0 should not affect wellness."""
        from probos.cognitive.counselor import CounselorAgent
        counselor = self._make_counselor()
        assessment = counselor.assess_agent(
            agent_id="agent-1",
            current_trust=0.8,
            current_confidence=0.7,
            hebbian_avg=0.5,
            success_rate=0.9,
            personality_drift=0.0,
        )
        # No comm quality concern with default 1.0
        for concern in assessment.concerns:
            assert "communication quality" not in concern.lower()

    def test_assess_low_comm_quality_adds_concern(self):
        """Low communication quality should add a concern."""
        counselor = self._make_counselor()
        assessment = counselor.assess_agent(
            agent_id="agent-1",
            current_trust=0.8,
            current_confidence=0.7,
            hebbian_avg=0.5,
            success_rate=0.9,
            personality_drift=0.0,
            communication_quality=0.3,
        )
        concern_texts = " ".join(assessment.concerns).lower()
        assert "communication quality" in concern_texts

    def test_assess_low_comm_quality_reduces_wellness(self):
        """Low communication quality should reduce wellness score."""
        counselor = self._make_counselor()
        good = counselor.assess_agent(
            agent_id="agent-1",
            current_trust=0.8,
            current_confidence=0.7,
            hebbian_avg=0.5,
            success_rate=0.9,
            personality_drift=0.0,
            communication_quality=1.0,
        )
        bad = counselor.assess_agent(
            agent_id="agent-1",
            current_trust=0.8,
            current_confidence=0.7,
            hebbian_avg=0.5,
            success_rate=0.9,
            personality_drift=0.0,
            communication_quality=0.3,
        )
        assert bad.wellness_score < good.wellness_score

    def test_promotion_blocked_by_low_comm_quality(self):
        """Agent with low comm quality should not be fit for promotion."""
        counselor = self._make_counselor()
        assessment = counselor.assess_agent(
            agent_id="agent-1",
            current_trust=0.9,
            current_confidence=0.8,
            hebbian_avg=0.6,
            success_rate=0.95,
            personality_drift=0.0,
            communication_quality=0.4,
        )
        assert assessment.fit_for_promotion is False

    def test_promotion_allowed_with_good_comm_quality(self):
        """Agent with good comm quality can be promoted (if other criteria met)."""
        counselor = self._make_counselor()
        assessment = counselor.assess_agent(
            agent_id="agent-1",
            current_trust=0.9,
            current_confidence=0.8,
            hebbian_avg=0.6,
            success_rate=0.95,
            personality_drift=0.0,
            communication_quality=0.8,
        )
        assert assessment.fit_for_promotion is True

    def test_comm_quality_borderline_promotion_gate(self):
        """communication_quality=0.6 should pass the promotion gate."""
        counselor = self._make_counselor()
        assessment = counselor.assess_agent(
            agent_id="agent-1",
            current_trust=0.9,
            current_confidence=0.8,
            hebbian_avg=0.6,
            success_rate=0.95,
            personality_drift=0.0,
            communication_quality=0.6,
        )
        # 0.6 meets the >= 0.6 gate
        assert assessment.fit_for_promotion is True

    def test_comm_quality_just_below_promotion_gate(self):
        """communication_quality=0.59 should fail promotion gate."""
        counselor = self._make_counselor()
        assessment = counselor.assess_agent(
            agent_id="agent-1",
            current_trust=0.9,
            current_confidence=0.8,
            hebbian_avg=0.6,
            success_rate=0.95,
            personality_drift=0.0,
            communication_quality=0.59,
        )
        assert assessment.fit_for_promotion is False
