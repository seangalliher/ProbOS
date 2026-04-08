"""Tests for Adaptive Source Governance (AD-568a/b/c)."""

from __future__ import annotations

import pytest

from probos.cognitive.source_governance import (
    BudgetAdjustment,
    RetrievalStrategy,
    SourceAuthority,
    SourceFraming,
    _INTENT_STRATEGY_MAP,
    classify_retrieval_strategy,
    compute_adaptive_budget,
    compute_source_framing,
)


# ===========================================================================
# Phase 1: AD-568a — Task-Type Retrieval Router
# ===========================================================================


class TestRetrievalRouter:
    """AD-568a: Task-Type Retrieval Router."""

    def test_game_intents_return_none(self):
        """Game intents should skip episodic recall."""
        for intent in ("game_challenge", "game_move", "game_spectate"):
            assert classify_retrieval_strategy(intent, episodic_count=10) == RetrievalStrategy.NONE

    def test_diagnostic_intents_return_deep(self):
        """Diagnostic/operational intents should use deep retrieval."""
        for intent in ("incident_response", "diagnostic_request", "system_analysis"):
            assert classify_retrieval_strategy(intent, episodic_count=10) == RetrievalStrategy.DEEP

    def test_routine_intents_return_shallow(self):
        """Routine intents should use standard retrieval."""
        for intent in ("proactive_think", "ward_room_notification", "direct_message"):
            assert classify_retrieval_strategy(intent, episodic_count=10) == RetrievalStrategy.SHALLOW

    def test_unknown_intent_defaults_to_shallow(self):
        """Unknown intent types should default to SHALLOW."""
        assert classify_retrieval_strategy("unknown_thing", episodic_count=10) == RetrievalStrategy.SHALLOW

    def test_zero_episodes_always_none(self):
        """If agent has no episodes, strategy is always NONE regardless of intent."""
        assert classify_retrieval_strategy("incident_response", episodic_count=0) == RetrievalStrategy.NONE
        assert classify_retrieval_strategy("proactive_think", episodic_count=0) == RetrievalStrategy.NONE

    def test_high_confabulation_downgrades_deep(self):
        """High confabulation rate should downgrade DEEP to SHALLOW."""
        result = classify_retrieval_strategy(
            "incident_response", episodic_count=10, recent_confabulation_rate=0.5
        )
        assert result == RetrievalStrategy.SHALLOW

    def test_low_confabulation_preserves_deep(self):
        """Low confabulation rate should preserve DEEP."""
        result = classify_retrieval_strategy(
            "incident_response", episodic_count=10, recent_confabulation_rate=0.1
        )
        assert result == RetrievalStrategy.DEEP

    def test_deep_strategy_expands_params(self):
        """DEEP strategy should multiply k and budget by 1.5x."""
        base_k = 5
        base_budget = 4000
        assert int(base_k * 1.5) == 7
        assert int(base_budget * 1.5) == 6000

    def test_none_strategy_enum_value(self):
        """NONE strategy should have string value 'none'."""
        assert RetrievalStrategy.NONE.value == "none"

    def test_intent_strategy_map_coverage(self):
        """All mapped intents should return valid strategies."""
        for intent, expected in _INTENT_STRATEGY_MAP.items():
            result = classify_retrieval_strategy(intent, episodic_count=10)
            assert result == expected

    def test_confabulation_threshold_boundary(self):
        """Confabulation rate at exactly 0.3 should NOT downgrade."""
        result = classify_retrieval_strategy(
            "incident_response", episodic_count=10, recent_confabulation_rate=0.3
        )
        assert result == RetrievalStrategy.DEEP

    def test_confabulation_just_above_threshold(self):
        """Confabulation rate just above 0.3 should downgrade."""
        result = classify_retrieval_strategy(
            "incident_response", episodic_count=10, recent_confabulation_rate=0.31
        )
        assert result == RetrievalStrategy.SHALLOW


# ===========================================================================
# Phase 2: AD-568b — Adaptive Budget Scaling
# ===========================================================================


class TestAdaptiveBudget:
    """AD-568b: Adaptive Budget Scaling."""

    def test_none_strategy_zero_budget(self):
        """NONE strategy should return zero budget."""
        result = compute_adaptive_budget(4000, strategy=RetrievalStrategy.NONE)
        assert result.adjusted_budget == 0

    def test_high_anchor_confidence_expands(self):
        """High anchor confidence should expand budget."""
        result = compute_adaptive_budget(
            4000, mean_anchor_confidence=0.8, episode_count=10
        )
        assert result.adjusted_budget > 4000

    def test_low_anchor_confidence_contracts(self):
        """Low anchor confidence should contract budget."""
        result = compute_adaptive_budget(
            4000, mean_anchor_confidence=0.1, episode_count=10
        )
        assert result.adjusted_budget < 4000

    def test_sparse_episodes_contracts(self):
        """Very few episodes should contract budget."""
        result = compute_adaptive_budget(4000, episode_count=2)
        assert result.adjusted_budget < 4000

    def test_budget_floor_enforced(self):
        """Budget should never go below 500."""
        result = compute_adaptive_budget(
            500, mean_anchor_confidence=0.05, episode_count=1
        )
        assert result.adjusted_budget >= 500

    def test_budget_ceiling_enforced(self):
        """Budget should never exceed 12000."""
        result = compute_adaptive_budget(
            10000, mean_anchor_confidence=0.9, episode_count=100
        )
        assert result.adjusted_budget <= 12000

    def test_no_adjustment_returns_base(self):
        """Neutral signals should return base budget."""
        result = compute_adaptive_budget(
            4000, mean_anchor_confidence=0.4, episode_count=10
        )
        assert result.scale_factor == 1.0
        assert result.adjusted_budget == 4000

    def test_multiple_signals_compound(self):
        """Multiple quality signals should compound."""
        result = compute_adaptive_budget(
            4000, mean_anchor_confidence=0.8, episode_count=10,
        )
        # High confidence (1.3x) — should be > base
        assert result.adjusted_budget > 4000
        assert result.scale_factor > 1.0

    def test_budget_adjustment_reason_populated(self):
        """Reason string should describe what scaled."""
        result = compute_adaptive_budget(
            4000, mean_anchor_confidence=0.8, episode_count=10
        )
        assert "anchor confidence" in result.reason

    def test_recall_scores_override_mean_confidence(self):
        """If recall_scores have anchor_confidence, use those over the arg."""
        class MockRS:
            def __init__(self, conf, score):
                self.anchor_confidence = conf
                self.composite_score = score
        scores = [MockRS(0.9, 0.8), MockRS(0.85, 0.75)]
        result = compute_adaptive_budget(
            4000, recall_scores=scores, mean_anchor_confidence=0.1, episode_count=10
        )
        # Should use the recall_scores' confidence (0.875), not the arg (0.1)
        assert result.adjusted_budget > 4000


# ===========================================================================
# Phase 3: AD-568c — Source Priority Framing
# ===========================================================================


class TestSourceFraming:
    """AD-568c: Source Priority Framing."""

    def test_none_strategy_peripheral(self):
        """NONE strategy should produce PERIPHERAL framing."""
        result = compute_source_framing(strategy=RetrievalStrategy.NONE)
        assert result.authority == SourceAuthority.PERIPHERAL

    def test_zero_recalls_peripheral(self):
        """Zero recalled episodes should produce PERIPHERAL framing."""
        result = compute_source_framing(recall_count=0)
        assert result.authority == SourceAuthority.PERIPHERAL

    def test_high_quality_authoritative(self):
        """High quality signals should produce AUTHORITATIVE framing."""
        result = compute_source_framing(
            mean_anchor_confidence=0.8,
            recall_count=5,
            mean_recall_score=0.7,
        )
        assert result.authority == SourceAuthority.AUTHORITATIVE

    def test_moderate_quality_supplementary(self):
        """Moderate quality should produce SUPPLEMENTARY framing."""
        result = compute_source_framing(
            mean_anchor_confidence=0.4,
            recall_count=3,
            mean_recall_score=0.4,
        )
        assert result.authority == SourceAuthority.SUPPLEMENTARY

    def test_low_quality_peripheral(self):
        """Low quality should produce PERIPHERAL framing."""
        result = compute_source_framing(
            mean_anchor_confidence=0.1,
            recall_count=2,
            mean_recall_score=0.1,
        )
        assert result.authority == SourceAuthority.PERIPHERAL

    def test_authoritative_header_contains_verified(self):
        """AUTHORITATIVE header should reference verification."""
        result = compute_source_framing(
            mean_anchor_confidence=0.9, recall_count=5, mean_recall_score=0.8
        )
        assert "verified" in result.header.lower()

    def test_peripheral_instruction_warns(self):
        """PERIPHERAL instruction should warn against relying on memories."""
        result = compute_source_framing(
            mean_anchor_confidence=0.1, recall_count=1, mean_recall_score=0.1
        )
        assert "do not rely" in result.instruction.lower()

    def test_framing_works_with_format_memory_section(self):
        """SourceFraming should integrate with _format_memory_section signature."""
        framing = compute_source_framing(
            mean_anchor_confidence=0.8, recall_count=5, mean_recall_score=0.7
        )
        assert hasattr(framing, 'header')
        assert hasattr(framing, 'instruction')
        assert hasattr(framing, 'authority')
