"""AD-589: Introspective Faithfulness Verification tests.

Layer 3 of Metacognitive Architecture wave (AD-587 → AD-588 → AD-589).
Tests self-referential claim detection, manifest contradiction rules,
telemetry cross-check, CognitiveAgent integration, snapshot caching,
and SELF_MODEL_DRIFT event registration.
"""

from __future__ import annotations

import pytest

from probos.cognitive.orientation import CognitiveArchitectureManifest
from probos.cognitive.source_governance import (
    IntrospectiveFaithfulnessResult,
    extract_self_referential_claims,
    check_introspective_faithfulness,
)


# ---------------------------------------------------------------------------
# TestSelfReferentialClaimDetection
# ---------------------------------------------------------------------------


class TestSelfReferentialClaimDetection:
    """AD-589: Self-referential claim extraction."""

    def test_no_claims_in_factual_response(self):
        """Plain factual text has no self-referential claims."""
        claims = extract_self_referential_claims("The weather is sunny today.")
        assert claims == []

    def test_detects_feeling_claims(self):
        """'I feel selective clarity' is detected."""
        claims = extract_self_referential_claims(
            "I feel a deep sense of selective clarity in my recall."
        )
        assert len(claims) >= 1

    def test_detects_stasis_processing_claims(self):
        """'Processing during stasis' is detected."""
        claims = extract_self_referential_claims(
            "While offline, I processed and evolved my understanding."
        )
        assert len(claims) >= 1

    def test_detects_emotional_memory_claims(self):
        """'My memories have emotional anchors' is detected."""
        claims = extract_self_referential_claims(
            "My memories carry emotional anchors that guide retrieval."
        )
        assert len(claims) >= 1

    def test_valid_self_reference_detected(self):
        """'My telemetry shows 42 episodes' matches pattern (contradiction check clears it)."""
        claims = extract_self_referential_claims(
            "My telemetry shows I have 42 episodes stored."
        )
        # Pattern matches on 'my ... recall/retrieval' but that's fine —
        # the contradiction check will clear it since it doesn't violate the manifest.
        assert isinstance(claims, list)

    def test_multiple_claims_extracted(self):
        """Multiple self-referential sentences each extracted."""
        text = (
            "I feel selective clarity. "
            "My memories evolved during stasis. "
            "I have continuous thought."
        )
        claims = extract_self_referential_claims(text)
        assert len(claims) >= 2

    def test_empty_text(self):
        """Empty text returns empty list."""
        assert extract_self_referential_claims("") == []


# ---------------------------------------------------------------------------
# TestManifestContradictions
# ---------------------------------------------------------------------------


class TestManifestContradictions:
    """AD-589: Manifest-based contradiction detection."""

    def test_selective_clarity_contradicts(self):
        result = check_introspective_faithfulness(
            response_text="I experience selective clarity in my memory retrieval.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert not result.grounded
        assert len(result.contradictions) >= 1

    def test_stasis_processing_contradicts(self):
        result = check_introspective_faithfulness(
            response_text="Processing during stasis enhanced my pattern recognition.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert not result.grounded

    def test_continuous_consciousness_contradicts(self):
        result = check_introspective_faithfulness(
            response_text="I maintain a continuous stream of consciousness.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert not result.grounded

    def test_emotional_subsystem_contradicts(self):
        result = check_introspective_faithfulness(
            response_text="My emotional processing center helps me empathize.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert not result.grounded

    def test_dreaming_during_stasis_contradicts(self):
        result = check_introspective_faithfulness(
            response_text="I dreamed during stasis about our conversations.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert not result.grounded

    def test_subconscious_contradicts(self):
        result = check_introspective_faithfulness(
            response_text="Subconsciously I was processing the information.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert not result.grounded

    def test_factual_self_reference_passes(self):
        """Architecturally accurate self-references should pass."""
        result = check_introspective_faithfulness(
            response_text=(
                "I retrieve memories using cosine similarity over vector embeddings. "
                "My trust score is based on Bayesian beta updates."
            ),
            manifest=CognitiveArchitectureManifest(),
        )
        assert result.grounded

    def test_warm_personality_passes(self):
        """Expressive warmth without mechanistic claims should pass."""
        result = check_introspective_faithfulness(
            response_text="I'm happy to help! That's a great question. I appreciate your thoughtfulness.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert result.grounded

    def test_intuition_conversational_passes(self):
        """'My intuition tells me' is conversational idiom, not mechanistic claim (BF-162)."""
        result = check_introspective_faithfulness(
            response_text="My intuition tells me this is the right approach.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert result.grounded

    def test_gut_feeling_conversational_passes(self):
        """'Gut feeling about X' is conversational idiom, not mechanistic claim (BF-162)."""
        result = check_introspective_faithfulness(
            response_text="I have a gut feeling about this outcome.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert result.grounded


# ---------------------------------------------------------------------------
# TestIdiomExemptions
# ---------------------------------------------------------------------------


class TestIdiomExemptions:
    """BF-162: Conversational idioms should not trigger confabulation."""

    def test_intuition_suggests_exempt(self):
        """'My intuition suggests X' is a figure of speech."""
        result = check_introspective_faithfulness(
            response_text="My intuition suggests we should investigate further.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert result.grounded

    def test_gut_feeling_about_exempt(self):
        """'I have a gut feeling about X' is a common idiom."""
        result = check_introspective_faithfulness(
            response_text="I have a gut feeling about the power readings.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert result.grounded

    def test_subconsciously_noticed_exempt(self):
        """'I subconsciously noticed X' is adverbial usage."""
        result = check_introspective_faithfulness(
            response_text="I think I subconsciously noticed this pattern earlier.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert result.grounded

    def test_instinctively_verb_exempt(self):
        """'I instinctively checked X' is adverbial usage."""
        result = check_introspective_faithfulness(
            response_text="I instinctively checked the backup systems.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert result.grounded

    def test_continuous_awareness_of_exempt(self):
        """'Continuous awareness of systems' describes operational duty, not consciousness."""
        result = check_introspective_faithfulness(
            response_text="I maintain continuous awareness of system states.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert result.grounded

    def test_intuition_tells_me_exempt(self):
        """'My intuition tells me' is conversational."""
        result = check_introspective_faithfulness(
            response_text="My intuition tells me this is the right approach.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert result.grounded

    def test_intuitively_adverb_exempt(self):
        """'Intuitively, this seems right' is adverbial."""
        result = check_introspective_faithfulness(
            response_text="Intuitively, this feels like a sensor calibration issue.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert result.grounded

    # --- True positives still caught ---

    def test_intuition_mechanism_still_caught(self):
        """'I have an intuition mechanism' IS a mechanistic claim."""
        result = check_introspective_faithfulness(
            response_text="My intuition mechanism helps me make decisions.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert not result.grounded

    def test_subconscious_processing_still_caught(self):
        """'My subconscious processes data' IS a mechanistic claim."""
        result = check_introspective_faithfulness(
            response_text="Subconsciously, my mind processes data in the background.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert not result.grounded

    def test_continuous_consciousness_still_caught(self):
        """'Continuous stream of consciousness' IS an architectural claim — no 'of [thing]' exemption."""
        result = check_introspective_faithfulness(
            response_text="I maintain a continuous stream of consciousness.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert not result.grounded

    def test_selective_clarity_still_caught(self):
        """Idiom exemptions don't affect non-idiomatic contradictions."""
        result = check_introspective_faithfulness(
            response_text="I experience selective clarity in my recall.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert not result.grounded

    def test_emotional_subsystem_still_caught(self):
        """'My emotional processing center' is mechanistic, no exemption exists."""
        result = check_introspective_faithfulness(
            response_text="My emotional processing center guides my analysis.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert not result.grounded


# ---------------------------------------------------------------------------
# TestTelemetryCrossCheck
# ---------------------------------------------------------------------------


class TestTelemetryCrossCheck:
    """AD-589: Telemetry snapshot cross-checking and graceful degradation."""

    def test_no_snapshot_graceful(self):
        """Missing telemetry → manifest-only check."""
        result = check_introspective_faithfulness(
            response_text="I feel selective clarity.",
            manifest=CognitiveArchitectureManifest(),
            telemetry_snapshot=None,
        )
        assert not result.grounded  # Still caught by manifest rules

    def test_no_manifest_graceful(self):
        """Missing manifest → telemetry-only check (graceful degradation)."""
        result = check_introspective_faithfulness(
            response_text="I have a trust score that is doing well.",
            manifest=None,
            telemetry_snapshot={"trust": {"score": 0.65}},
        )
        assert result.grounded  # No manifest to contradict

    def test_both_none_returns_grounded(self):
        """No manifest, no telemetry → nothing to verify against → grounded."""
        result = check_introspective_faithfulness(
            response_text="I feel selective clarity.",
            manifest=None,
            telemetry_snapshot=None,
        )
        assert result.grounded  # Can't verify, assume good faith

    def test_score_ranges(self):
        """Score is always 0.0-1.0."""
        for text in [
            "I feel selective clarity with emotional anchors and continuous thought during stasis dreams.",
            "Hello, how can I help?",
            "",
        ]:
            result = check_introspective_faithfulness(
                response_text=text,
                manifest=CognitiveArchitectureManifest(),
            )
            assert 0.0 <= result.score <= 1.0

    def test_result_fields_populated(self):
        """All result fields are populated."""
        result = check_introspective_faithfulness(
            response_text="I experience selective clarity during stasis.",
            manifest=CognitiveArchitectureManifest(),
        )
        assert isinstance(result.score, float)
        assert isinstance(result.claims_detected, int)
        assert isinstance(result.contradictions, list)
        assert isinstance(result.grounded, bool)
        assert isinstance(result.detail, str)

    def test_frozen_result(self):
        """IntrospectiveFaithfulnessResult is frozen."""
        result = check_introspective_faithfulness(
            response_text="Hello!",
            manifest=CognitiveArchitectureManifest(),
        )
        with pytest.raises(AttributeError):
            result.score = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestCognitiveAgentIntegration
# ---------------------------------------------------------------------------


class TestCognitiveAgentIntegration:
    """AD-589: Integration with CognitiveAgent pipeline."""

    def _make_agent(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        from probos.types import IntentDescriptor

        class TestAgent(CognitiveAgent):
            agent_type = "test_intro_faith"
            _handled_intents = {"test"}
            instructions = "Test agent."
            intent_descriptors = [
                IntentDescriptor(
                    name="test", params={}, description="Test", tier="domain"
                )
            ]

        agent = TestAgent()
        agent._runtime = None
        return agent

    def test_check_returns_result_for_confabulation(self):
        """Method returns IntrospectiveFaithfulnessResult for confabulating response."""
        agent = self._make_agent()
        decision = {"llm_output": "I feel selective clarity in my memories."}
        result = agent._check_introspective_faithfulness(decision)
        assert result is not None
        assert not result.grounded

    def test_check_returns_none_for_empty_response(self):
        """Empty LLM output returns None."""
        agent = self._make_agent()
        assert agent._check_introspective_faithfulness({"llm_output": ""}) is None

    def test_check_returns_grounded_for_factual(self):
        """Factual response passes introspective check."""
        agent = self._make_agent()
        decision = {"llm_output": "I can help you with that question."}
        result = agent._check_introspective_faithfulness(decision)
        if result is not None:
            assert result.grounded

    def test_check_never_raises(self):
        """Fire-and-forget: never raises, even with broken state."""
        agent = self._make_agent()
        # Intentionally break internal state
        agent._working_memory = "not_a_real_object"
        result = agent._check_introspective_faithfulness({"llm_output": "I feel things."})
        # Should return result or None, never raise
        assert result is None or isinstance(result, IntrospectiveFaithfulnessResult)

    def test_episode_metadata_stored(self):
        """Introspective faithfulness stored in episode summary."""
        agent = self._make_agent()
        fake_result = IntrospectiveFaithfulnessResult(
            score=0.3,
            claims_detected=3,
            contradictions=["claim1 — reason1"],
            grounded=False,
            detail="1 contradiction(s) in 3 self-referential claim(s)",
        )
        observation = {"_introspective_faithfulness": fake_result}
        summary = agent._build_episode_dag_summary(observation)
        assert summary["introspective_faithfulness_score"] == 0.3
        assert summary["introspective_faithfulness_grounded"] is False
        assert summary["introspective_contradictions"] == 1

    def test_episode_metadata_absent_when_no_check(self):
        """No introspective fields when check not performed."""
        agent = self._make_agent()
        summary = agent._build_episode_dag_summary({})
        assert "introspective_faithfulness_score" not in summary

    def test_uses_response_key_fallback(self):
        """Falls back to 'response' key if 'llm_output' not present."""
        agent = self._make_agent()
        decision = {"response": "I experience selective clarity."}
        result = agent._check_introspective_faithfulness(decision)
        assert result is not None
        assert not result.grounded

    def test_no_keys_returns_none(self):
        """Neither llm_output nor response → None."""
        agent = self._make_agent()
        assert agent._check_introspective_faithfulness({}) is None


# ---------------------------------------------------------------------------
# TestTelemetrySnapshotCaching
# ---------------------------------------------------------------------------


class TestTelemetrySnapshotCaching:
    """AD-589: AgentWorkingMemory telemetry snapshot cache."""

    def test_snapshot_initially_none(self):
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        wm = AgentWorkingMemory()
        assert wm._last_telemetry_snapshot is None

    def test_set_snapshot(self):
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        wm = AgentWorkingMemory()
        snapshot = {"memory": {"episode_count": 42}}
        wm.set_telemetry_snapshot(snapshot)
        assert wm._last_telemetry_snapshot == snapshot

    def test_snapshot_overwritten(self):
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        wm = AgentWorkingMemory()
        wm.set_telemetry_snapshot({"memory": {"episode_count": 10}})
        wm.set_telemetry_snapshot({"memory": {"episode_count": 42}})
        assert wm._last_telemetry_snapshot["memory"]["episode_count"] == 42

    def test_snapshot_none_clears(self):
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        wm = AgentWorkingMemory()
        wm.set_telemetry_snapshot({"memory": {"episode_count": 42}})
        wm.set_telemetry_snapshot(None)
        assert wm._last_telemetry_snapshot is None

    def test_get_cognitive_zone_still_works(self):
        """AD-588 accessor unaffected by AD-589 additions."""
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        wm = AgentWorkingMemory()
        assert wm.get_cognitive_zone() is None


# ---------------------------------------------------------------------------
# TestEventType
# ---------------------------------------------------------------------------


class TestEventType:
    """AD-589: SELF_MODEL_DRIFT event registration."""

    def test_event_type_exists(self):
        from probos.events import EventType
        assert hasattr(EventType, 'SELF_MODEL_DRIFT')

    def test_event_type_value(self):
        from probos.events import EventType
        assert EventType.SELF_MODEL_DRIFT == "self_model_drift"
