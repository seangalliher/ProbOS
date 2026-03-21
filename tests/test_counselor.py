"""Tests for CounselorAgent + Cognitive Profiles (AD-378)."""

from __future__ import annotations

import time
import pytest


class TestCognitiveBaseline:
    def test_roundtrip_dict(self) -> None:
        from probos.cognitive.counselor import CognitiveBaseline
        b = CognitiveBaseline(trust_score=0.8, confidence=0.9)
        restored = CognitiveBaseline.from_dict(b.to_dict())
        assert restored.trust_score == 0.8

    def test_defaults(self) -> None:
        from probos.cognitive.counselor import CognitiveBaseline
        b = CognitiveBaseline()
        assert b.trust_score == 0.5
        assert b.confidence == 0.8


class TestCounselorAssessment:
    def test_roundtrip_dict(self) -> None:
        from probos.cognitive.counselor import CounselorAssessment
        a = CounselorAssessment(
            agent_id="test",
            wellness_score=0.8,
            concerns=["low trust"],
        )
        restored = CounselorAssessment.from_dict(a.to_dict())
        assert restored.agent_id == "test"
        assert len(restored.concerns) == 1


class TestCognitiveProfile:
    def test_add_assessment_updates_alert(self) -> None:
        from probos.cognitive.counselor import CognitiveProfile, CounselorAssessment
        profile = CognitiveProfile(agent_id="test")
        # Good assessment
        profile.add_assessment(CounselorAssessment(
            timestamp=time.time(), wellness_score=0.9, fit_for_duty=True,
        ))
        assert profile.alert_level == "green"

    def test_low_wellness_triggers_yellow(self) -> None:
        from probos.cognitive.counselor import CognitiveProfile, CounselorAssessment
        profile = CognitiveProfile(agent_id="test")
        profile.add_assessment(CounselorAssessment(
            timestamp=time.time(), wellness_score=0.4, fit_for_duty=True,
            concerns=["a", "b", "c"],
        ))
        assert profile.alert_level == "yellow"

    def test_unfit_for_duty_triggers_red(self) -> None:
        from probos.cognitive.counselor import CognitiveProfile, CounselorAssessment
        profile = CognitiveProfile(agent_id="test")
        profile.add_assessment(CounselorAssessment(
            timestamp=time.time(), wellness_score=0.1, fit_for_duty=False,
        ))
        assert profile.alert_level == "red"

    def test_drift_trend(self) -> None:
        from probos.cognitive.counselor import CognitiveProfile, CounselorAssessment
        profile = CognitiveProfile(agent_id="test")
        for i in range(5):
            profile.add_assessment(CounselorAssessment(
                timestamp=time.time(), trust_drift=-0.1 * (i + 1),
            ))
        trend = profile.drift_trend("trust_drift")
        assert trend < 0  # downward trend

    def test_latest_assessment(self) -> None:
        from probos.cognitive.counselor import CognitiveProfile, CounselorAssessment
        profile = CognitiveProfile(agent_id="test")
        assert profile.latest_assessment() is None
        a = CounselorAssessment(timestamp=time.time(), agent_id="test")
        profile.add_assessment(a)
        assert profile.latest_assessment() is a

    def test_roundtrip_dict(self) -> None:
        from probos.cognitive.counselor import CognitiveProfile
        p = CognitiveProfile(agent_id="test", alert_level="yellow")
        restored = CognitiveProfile.from_dict(p.to_dict())
        assert restored.alert_level == "yellow"


class TestCounselorAgent:
    def test_init(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        from unittest.mock import MagicMock
        agent = CounselorAgent(llm_client=MagicMock())
        assert agent.agent_type == "counselor"
        assert agent.pool == "bridge"

    def test_get_or_create_profile(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        from unittest.mock import MagicMock
        agent = CounselorAgent(llm_client=MagicMock())
        p = agent.get_or_create_profile("agent-1", "builder")
        assert p.agent_id == "agent-1"
        # Get again returns same
        p2 = agent.get_or_create_profile("agent-1")
        assert p2 is p

    def test_set_baseline(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CognitiveBaseline
        from unittest.mock import MagicMock
        agent = CounselorAgent(llm_client=MagicMock())
        baseline = CognitiveBaseline(trust_score=0.7, confidence=0.85)
        agent.set_baseline("agent-1", baseline)
        profile = agent.get_profile("agent-1")
        assert profile is not None
        assert profile.baseline.trust_score == 0.7

    def test_assess_healthy_agent(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CognitiveBaseline
        from unittest.mock import MagicMock
        agent = CounselorAgent(llm_client=MagicMock())
        agent.set_baseline("agent-1", CognitiveBaseline(
            trust_score=0.7, confidence=0.8,
        ))
        result = agent.assess_agent(
            "agent-1", current_trust=0.75, current_confidence=0.85,
            success_rate=0.9,
        )
        assert result.wellness_score >= 0.8
        assert result.fit_for_duty
        assert len(result.concerns) == 0

    def test_assess_degraded_agent(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CognitiveBaseline
        from unittest.mock import MagicMock
        agent = CounselorAgent(llm_client=MagicMock())
        agent.set_baseline("agent-1", CognitiveBaseline(
            trust_score=0.8, confidence=0.9,
        ))
        result = agent.assess_agent(
            "agent-1", current_trust=0.4, current_confidence=0.2,
            success_rate=0.3, personality_drift=0.6,
        )
        assert result.wellness_score < 0.5
        assert len(result.concerns) >= 2
        assert not result.fit_for_promotion

    def test_assess_promotion_candidate(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CognitiveBaseline
        from unittest.mock import MagicMock
        agent = CounselorAgent(llm_client=MagicMock())
        agent.set_baseline("agent-1", CognitiveBaseline(
            trust_score=0.7, confidence=0.8,
        ))
        result = agent.assess_agent(
            "agent-1", current_trust=0.9, current_confidence=0.9,
            hebbian_avg=0.5, success_rate=0.95,
        )
        assert result.fit_for_promotion
        assert result.fit_for_duty

    def test_agents_at_alert(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CognitiveBaseline
        from unittest.mock import MagicMock
        agent = CounselorAgent(llm_client=MagicMock())
        # Create a healthy and unhealthy agent
        agent.set_baseline("healthy", CognitiveBaseline(trust_score=0.7))
        agent.assess_agent("healthy", current_trust=0.75, success_rate=0.9)
        agent.set_baseline("degraded", CognitiveBaseline(trust_score=0.8))
        agent.assess_agent("degraded", current_trust=0.4, success_rate=0.3)
        yellow_plus = agent.agents_at_alert("yellow")
        assert any(p.agent_id == "degraded" for p in yellow_plus)

    @pytest.mark.asyncio
    async def test_act_assess(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CognitiveBaseline, CounselorAssessment
        from unittest.mock import MagicMock
        agent = CounselorAgent(llm_client=MagicMock())
        agent.set_baseline("agent-1", CognitiveBaseline(trust_score=0.7))
        result = await agent.act({
            "action": "assess",
            "agent_id": "agent-1",
            "trust_score": 0.75,
            "confidence": 0.8,
            "success_rate": 0.9,
        })
        assert isinstance(result, CounselorAssessment)

    @pytest.mark.asyncio
    async def test_report_assessment(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        from unittest.mock import MagicMock
        agent = CounselorAgent(llm_client=MagicMock())
        assessment = CounselorAssessment(agent_id="test", wellness_score=0.9)
        result = await agent.report(assessment)
        assert result["type"] == "counselor_assessment"
        assert "data" in result
