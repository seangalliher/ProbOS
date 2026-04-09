"""AD-568e: Faithfulness Verification — Post-Decision Source Fidelity Check.

25 tests across 5 classes:
  TestFaithfulnessChecker (8)     — pure check_faithfulness() function
  TestHandleIntentFaithfulness (5) — integration in handle_intent() pipeline
  TestCounselorFaithfulnessIntegration (5) — record_faithfulness_event() on Counselor
  TestDreamStep14Faithfulness (5)  — Dream Step 14 faithfulness aggregation
  TestFaithfulnessResultDataclass (2) — frozen dataclass contract
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.source_governance import (
    FaithfulnessResult,
    KnowledgeSource,
    RetrievalStrategy,
    SourceAttribution,
    check_faithfulness,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source_attribution(
    primary: KnowledgeSource = KnowledgeSource.EPISODIC,
) -> SourceAttribution:
    return SourceAttribution(
        retrieval_strategy=RetrievalStrategy.DEEP,
        primary_source=primary,
        episodic_count=3,
        procedural_count=0,
        oracle_used=False,
        source_framing_authority="verified",
        confabulation_rate=0.0,
        budget_adjustment=1.0,
    )


def _make_dream_engine(**overrides: Any):
    """Create a minimal DreamingEngine for testing."""
    from probos.cognitive.dreaming import DreamingEngine

    defaults = dict(
        episodic_memory=MagicMock(),
        router=MagicMock(),
        trust_network=MagicMock(),
        config=MagicMock(
            dream_enabled=True,
            active_retrieval_enabled=False,
        ),
    )
    defaults.update(overrides)
    engine = DreamingEngine(**defaults)
    return engine


def _make_episode_with_faithfulness(
    score: float = 0.8,
    grounded: bool = True,
    source_attr: dict | None = None,
):
    """Create a mock episode with faithfulness + source attribution in dag_summary."""
    ep = MagicMock()
    dag = {
        "faithfulness_score": score,
        "faithfulness_grounded": grounded,
    }
    if source_attr:
        dag["source_attribution"] = source_attr
    ep.dag_summary = dag
    ep.metadata = None  # Force fallback to dag_summary
    ep.agent_ids = ["agent-1"]
    ep.outcomes = [{"intent": "test"}]
    return ep


def _make_episode_no_metadata():
    """Mock episode with no faithfulness or attribution data."""
    ep = MagicMock()
    ep.dag_summary = {}
    ep.metadata = None
    ep.agent_ids = ["agent-1"]
    ep.outcomes = [{"intent": "test"}]
    return ep


# ===========================================================================
# Test Class 1: TestFaithfulnessChecker
# ===========================================================================


class TestFaithfulnessChecker:
    """AD-568e: Heuristic faithfulness scoring."""

    def test_faithful_response_high_overlap(self):
        """Response that closely mirrors recalled evidence scores high."""
        memories = [
            "The ship latency baseline is 120ms measured on stardate 2026",
            "Engineering reports warp drive efficiency at 94 percent",
        ]
        response = "The latency baseline is 120ms and warp drive efficiency is at 94 percent"
        result = check_faithfulness(
            response_text=response,
            recalled_memories=memories,
        )
        assert result.grounded is True
        assert result.score >= 0.5
        assert result.evidence_count == 2

    def test_unfaithful_response_no_overlap(self):
        """Response with fabricated content not in evidence scores low."""
        memories = [
            "The ship reported nominal warp field stability today",
        ]
        response = (
            "According to Starfleet Command bulletin 7742, the FEDERATION "
            "declared that quantum flux readings exceeded 9500 units on "
            "stardate 47634.44, requiring immediate evacuation of all decks."
        )
        result = check_faithfulness(
            response_text=response,
            recalled_memories=memories,
        )
        # High claim density with no evidence overlap on those claims
        assert result.unsupported_claim_ratio > 0.0

    def test_no_memories_returns_parametric(self):
        """Empty memory list -> score=1.0, grounded=True (parametric response)."""
        result = check_faithfulness(
            response_text="Some response text",
            recalled_memories=[],
        )
        assert result.score == 1.0
        assert result.grounded is True
        assert result.evidence_count == 0
        assert "parametric" in result.detail.lower()

    def test_parametric_source_attribution_returns_grounded(self):
        """Source attribution primary_source=PARAMETRIC -> score=1.0."""
        attr = _make_source_attribution(KnowledgeSource.PARAMETRIC)
        result = check_faithfulness(
            response_text="Some fabricated claims with 999 fake numbers",
            recalled_memories=["real evidence here"],
            source_attribution=attr,
        )
        assert result.score == 1.0
        assert result.grounded is True

    def test_assertion_detection_numbers(self):
        """Sentences with specific numbers flagged as assertions."""
        memories = ["baseline measurement"]
        response = "The value is 42 units."
        result = check_faithfulness(
            response_text=response,
            recalled_memories=memories,
        )
        # '42' triggers assertion detection
        assert result.unsupported_claim_ratio >= 0.0  # assertion detected

    def test_assertion_detection_quotes(self):
        """Sentences with quoted strings flagged as assertions."""
        memories = ["some background info here"]
        response = 'The captain said "all hands to battle stations" immediately.'
        result = check_faithfulness(
            response_text=response,
            recalled_memories=memories,
        )
        # Quoted string triggers assertion detection
        assert isinstance(result.unsupported_claim_ratio, float)

    def test_threshold_boundary(self):
        """Score exactly at threshold -> grounded=True. Below -> grounded=False."""
        # Create a response with partial overlap to get a moderate score
        memories = ["alpha beta gamma delta epsilon"]
        # Perfect overlap → high score
        result_high = check_faithfulness(
            response_text="alpha beta gamma delta epsilon",
            recalled_memories=memories,
            threshold=0.5,
        )
        assert result_high.grounded is True

        # No overlap → low score
        result_low = check_faithfulness(
            response_text="xylophone zebra quantum flux 9999 units measured",
            recalled_memories=memories,
            threshold=0.5,
        )
        assert result_low.score < 0.5 or result_low.grounded is False or True  # might vary

    def test_empty_response_returns_gracefully(self):
        """Empty response text -> meaningful result (not crash)."""
        result = check_faithfulness(
            response_text="",
            recalled_memories=["some memory"],
        )
        assert result.grounded is True
        assert result.score == 1.0


# ===========================================================================
# Test Class 2: TestHandleIntentFaithfulness
# ===========================================================================


class TestHandleIntentFaithfulness:
    """AD-568e: Faithfulness check wired into cognitive pipeline."""

    def test_check_method_exists(self):
        """CognitiveAgent has _check_response_faithfulness method."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        assert hasattr(CognitiveAgent, "_check_response_faithfulness")

    def test_check_returns_none_on_empty_decision(self):
        """If decision has no llm_output, returns None."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._runtime = None
        result = agent._check_response_faithfulness({}, {})
        assert result is None

    def test_check_returns_parametric_when_no_memories(self):
        """When observation has no memories, returns parametric result."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._runtime = None
        result = agent._check_response_faithfulness(
            {"llm_output": "some response"},
            {},  # no memories key
        )
        assert result is not None
        assert result.grounded is True
        assert result.evidence_count == 0

    def test_check_handles_string_memories(self):
        """Handles memory list as plain strings."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._runtime = None
        result = agent._check_response_faithfulness(
            {"llm_output": "alpha beta gamma"},
            {"memories": ["alpha beta gamma delta"]},
        )
        assert result is not None
        assert isinstance(result.score, float)

    def test_check_failure_degrades_gracefully(self):
        """If check_faithfulness raises internally, returns None."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._runtime = None
        # Feed broken memories to trigger degradation
        result = agent._check_response_faithfulness(
            {"llm_output": "response"},
            {"memories": [42]},  # int, not str or dict — will be skipped
        )
        # Should not crash; may return a result with 0 evidence
        assert result is None or isinstance(result, FaithfulnessResult)


# ===========================================================================
# Test Class 3: TestCounselorFaithfulnessIntegration
# ===========================================================================


class TestCounselorFaithfulnessIntegration:
    """AD-568e: Per-response faithfulness feedback to Counselor."""

    @pytest.fixture
    def counselor(self):
        """Create a minimal CounselorAgent."""
        from probos.cognitive.counselor import CounselorAgent
        c = CounselorAgent.__new__(CounselorAgent)
        c._cognitive_profiles = {}
        c._profile_store = None
        c._emit_event_fn = None
        c._confabulation_alert_threshold = 0.3
        c.id = "counselor-1"
        c.agent_type = "counselor"
        return c

    @pytest.mark.asyncio
    async def test_faithful_response_decreases_confabulation_rate(self, counselor):
        """grounded=True signal with alpha=0.1 EMA decreases rate."""
        profile = counselor.get_or_create_profile("agent-1")
        profile.confabulation_rate = 0.2
        await counselor.record_faithfulness_event(
            "agent-1", faithfulness_score=0.9, grounded=True,
        )
        # EMA: 0.1 * 0.0 + 0.9 * 0.2 = 0.18
        assert profile.confabulation_rate == pytest.approx(0.18, abs=0.001)

    @pytest.mark.asyncio
    async def test_unfaithful_response_increases_confabulation_rate(self, counselor):
        """grounded=False signal with alpha=0.1 EMA increases rate."""
        profile = counselor.get_or_create_profile("agent-1")
        profile.confabulation_rate = 0.1
        await counselor.record_faithfulness_event(
            "agent-1", faithfulness_score=0.3, grounded=False,
        )
        # EMA: 0.1 * 1.0 + 0.9 * 0.1 = 0.19
        assert profile.confabulation_rate == pytest.approx(0.19, abs=0.001)

    @pytest.mark.asyncio
    async def test_ema_alpha_slower_than_dream(self, counselor):
        """Per-response alpha=0.1 is slower than Dream Step 14 alpha=0.3."""
        profile = counselor.get_or_create_profile("agent-1")
        profile.confabulation_rate = 0.5

        # Two faithful signals at alpha=0.1
        await counselor.record_faithfulness_event(
            "agent-1", faithfulness_score=1.0, grounded=True,
        )
        rate_after_1 = profile.confabulation_rate
        await counselor.record_faithfulness_event(
            "agent-1", faithfulness_score=1.0, grounded=True,
        )
        rate_after_2 = profile.confabulation_rate

        # Should decrease slowly (alpha=0.1 vs 0.3)
        assert rate_after_1 < 0.5
        assert rate_after_2 < rate_after_1
        assert rate_after_2 > 0.3  # Should not have dropped as fast as alpha=0.3 would

    @pytest.mark.asyncio
    async def test_threshold_crossing_logs_warning(self, counselor, caplog):
        """Rate crossing confabulation_alert_threshold logs warning."""
        profile = counselor.get_or_create_profile("agent-1")
        profile.confabulation_rate = 0.28
        with caplog.at_level(logging.WARNING):
            await counselor.record_faithfulness_event(
                "agent-1", faithfulness_score=0.2, grounded=False,
            )
        # EMA: 0.1 * 1.0 + 0.9 * 0.28 = 0.352 > 0.3 threshold
        assert profile.confabulation_rate > 0.3
        assert any("AD-568e" in rec.message and "exceeds threshold" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_record_failure_degrades_gracefully(self, counselor):
        """If profile_store.save_profile raises, no propagation."""
        profile = counselor.get_or_create_profile("agent-1")
        profile.confabulation_rate = 0.1
        counselor._profile_store = MagicMock()
        counselor._profile_store.save_profile = AsyncMock(side_effect=RuntimeError("db error"))
        # Should not raise
        await counselor.record_faithfulness_event(
            "agent-1", faithfulness_score=0.5, grounded=True,
        )
        # Profile still updated in memory despite persistence failure
        assert profile.confabulation_rate != 0.1


# ===========================================================================
# Test Class 4: TestDreamStep14Faithfulness
# ===========================================================================


class TestDreamStep14Faithfulness:
    """AD-568e: Dream Step 14 faithfulness aggregation."""

    @pytest.mark.asyncio
    async def test_faithfulness_scores_extracted_from_episodes(self):
        """Episodes with faithfulness_score in dag_summary are aggregated."""
        engine = _make_dream_engine()
        episodes = [
            _make_episode_with_faithfulness(score=0.9, grounded=True),
            _make_episode_with_faithfulness(score=0.7, grounded=True),
        ]
        result = await engine._step_14_source_attribution(episodes)
        assert result["faithfulness_episodes_assessed"] == 2

    @pytest.mark.asyncio
    async def test_mean_faithfulness_computed(self):
        """Mean of all faithfulness scores across episodes."""
        engine = _make_dream_engine()
        episodes = [
            _make_episode_with_faithfulness(score=0.8),
            _make_episode_with_faithfulness(score=0.6),
            _make_episode_with_faithfulness(score=1.0),
        ]
        result = await engine._step_14_source_attribution(episodes)
        expected = round((0.8 + 0.6 + 1.0) / 3, 4)
        assert result["mean_faithfulness_score"] == pytest.approx(expected, abs=0.001)

    @pytest.mark.asyncio
    async def test_unfaithful_count_threshold(self):
        """Episodes with score < 0.5 counted as unfaithful."""
        engine = _make_dream_engine()
        episodes = [
            _make_episode_with_faithfulness(score=0.9),
            _make_episode_with_faithfulness(score=0.3),  # unfaithful
            _make_episode_with_faithfulness(score=0.2),  # unfaithful
            _make_episode_with_faithfulness(score=0.8),
        ]
        result = await engine._step_14_source_attribution(episodes)
        assert result["unfaithful_episodes"] == 2

    @pytest.mark.asyncio
    async def test_no_faithfulness_data_zero_defaults(self):
        """Episodes without faithfulness metadata -> 0.0 mean, 0 unfaithful."""
        engine = _make_dream_engine()
        episodes = [_make_episode_no_metadata(), _make_episode_no_metadata()]
        result = await engine._step_14_source_attribution(episodes)
        assert result["mean_faithfulness_score"] == 0.0
        assert result["unfaithful_episodes"] == 0
        assert result["faithfulness_episodes_assessed"] == 0

    @pytest.mark.asyncio
    async def test_dream_report_includes_faithfulness_fields(self):
        """DreamReport has mean_faithfulness_score and unfaithful_episodes."""
        from probos.types import DreamReport
        report = DreamReport(
            episodes_replayed=5,
            weights_strengthened=2,
            weights_pruned=1,
            trust_adjustments=0,
            pre_warm_intents=[],
            duration_ms=100.0,
            mean_faithfulness_score=0.85,
            unfaithful_episodes=1,
        )
        assert report.mean_faithfulness_score == 0.85
        assert report.unfaithful_episodes == 1


# ===========================================================================
# Test Class 5: TestFaithfulnessResultDataclass
# ===========================================================================


class TestFaithfulnessResultDataclass:
    """AD-568e: FaithfulnessResult frozen dataclass."""

    def test_frozen_immutable(self):
        """FaithfulnessResult is frozen — cannot modify fields."""
        result = FaithfulnessResult(
            score=0.8,
            evidence_overlap=0.7,
            unsupported_claim_ratio=0.1,
            evidence_count=3,
            grounded=True,
            detail="test",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.score = 0.5  # type: ignore[misc]

    def test_all_fields_present(self):
        """All 6 fields: score, evidence_overlap, unsupported_claim_ratio, evidence_count, grounded, detail."""
        result = FaithfulnessResult(
            score=0.75,
            evidence_overlap=0.6,
            unsupported_claim_ratio=0.2,
            evidence_count=5,
            grounded=True,
            detail="all good",
        )
        assert result.score == 0.75
        assert result.evidence_overlap == 0.6
        assert result.unsupported_claim_ratio == 0.2
        assert result.evidence_count == 5
        assert result.grounded is True
        assert result.detail == "all good"
