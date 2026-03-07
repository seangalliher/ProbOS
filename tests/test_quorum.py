"""Tests for QuorumEngine."""

import pytest

from probos.consensus.quorum import QuorumEngine
from probos.types import (
    ConsensusOutcome,
    IntentResult,
    QuorumPolicy,
)


class TestQuorumEngine:
    def _make_result(self, agent_id: str, success: bool, confidence: float = 0.8) -> IntentResult:
        return IntentResult(
            intent_id="test-intent",
            agent_id=agent_id,
            success=success,
            result="data" if success else None,
            error=None if success else "failed",
            confidence=confidence,
        )

    def test_unanimous_approval(self):
        engine = QuorumEngine(QuorumPolicy(min_votes=3, approval_threshold=0.6))
        results = [
            self._make_result("a1", True, 0.9),
            self._make_result("a2", True, 0.8),
            self._make_result("a3", True, 0.7),
        ]
        consensus = engine.evaluate(results)
        assert consensus.outcome == ConsensusOutcome.APPROVED
        assert consensus.approval_ratio == 1.0
        assert len(consensus.votes) == 3

    def test_unanimous_rejection(self):
        engine = QuorumEngine(QuorumPolicy(min_votes=3, approval_threshold=0.6))
        results = [
            self._make_result("a1", False, 0.9),
            self._make_result("a2", False, 0.8),
            self._make_result("a3", False, 0.7),
        ]
        consensus = engine.evaluate(results)
        assert consensus.outcome == ConsensusOutcome.REJECTED
        assert consensus.approval_ratio == 0.0

    def test_insufficient_votes(self):
        engine = QuorumEngine(QuorumPolicy(min_votes=3, approval_threshold=0.6))
        results = [
            self._make_result("a1", True, 0.9),
            self._make_result("a2", True, 0.8),
        ]
        consensus = engine.evaluate(results)
        assert consensus.outcome == ConsensusOutcome.INSUFFICIENT

    def test_empty_results(self):
        engine = QuorumEngine(QuorumPolicy(min_votes=1))
        consensus = engine.evaluate([])
        assert consensus.outcome == ConsensusOutcome.INSUFFICIENT

    def test_mixed_votes_approved(self):
        """2/3 approve with threshold 0.6 → approved."""
        engine = QuorumEngine(QuorumPolicy(min_votes=3, approval_threshold=0.6))
        results = [
            self._make_result("a1", True, 0.8),
            self._make_result("a2", True, 0.8),
            self._make_result("a3", False, 0.8),
        ]
        consensus = engine.evaluate(results)
        assert consensus.outcome == ConsensusOutcome.APPROVED

    def test_mixed_votes_rejected(self):
        """1/3 approve with threshold 0.6 → rejected."""
        engine = QuorumEngine(QuorumPolicy(min_votes=3, approval_threshold=0.6))
        results = [
            self._make_result("a1", True, 0.8),
            self._make_result("a2", False, 0.8),
            self._make_result("a3", False, 0.8),
        ]
        consensus = engine.evaluate(results)
        assert consensus.outcome == ConsensusOutcome.REJECTED

    def test_confidence_weighting(self):
        """High-confidence rejection outweighs low-confidence approvals."""
        engine = QuorumEngine(
            QuorumPolicy(min_votes=3, approval_threshold=0.6, use_confidence_weights=True)
        )
        results = [
            self._make_result("a1", True, 0.1),   # low confidence approve
            self._make_result("a2", True, 0.1),   # low confidence approve
            self._make_result("a3", False, 0.9),  # high confidence reject
        ]
        consensus = engine.evaluate(results)
        # weighted_approval = 0.2, total = 1.1, ratio = 0.18 < 0.6
        assert consensus.outcome == ConsensusOutcome.REJECTED

    def test_unweighted_mode(self):
        """Without confidence weighting, each vote counts equally."""
        engine = QuorumEngine(
            QuorumPolicy(min_votes=3, approval_threshold=0.6, use_confidence_weights=False)
        )
        results = [
            self._make_result("a1", True, 0.1),   # low confidence approve
            self._make_result("a2", True, 0.1),   # low confidence approve
            self._make_result("a3", False, 0.9),  # high confidence reject
        ]
        consensus = engine.evaluate(results)
        # unweighted: 2/3 approve = 0.67 > 0.6
        assert consensus.outcome == ConsensusOutcome.APPROVED

    def test_2_of_3_policy(self):
        engine = QuorumEngine(QuorumPolicy(min_votes=3, approval_threshold=0.5))
        results = [
            self._make_result("a1", True, 0.8),
            self._make_result("a2", True, 0.8),
            self._make_result("a3", False, 0.8),
        ]
        consensus = engine.evaluate(results)
        assert consensus.outcome == ConsensusOutcome.APPROVED

    def test_3_of_5_policy(self):
        engine = QuorumEngine(QuorumPolicy(min_votes=5, approval_threshold=0.5))
        results = [
            self._make_result("a1", True, 0.8),
            self._make_result("a2", True, 0.8),
            self._make_result("a3", True, 0.8),
            self._make_result("a4", False, 0.8),
            self._make_result("a5", False, 0.8),
        ]
        consensus = engine.evaluate(results)
        assert consensus.outcome == ConsensusOutcome.APPROVED

    def test_evaluate_values_returns_majority(self):
        engine = QuorumEngine(QuorumPolicy(min_votes=3, approval_threshold=0.5))
        results = [
            IntentResult(
                intent_id="i1", agent_id="a1", success=True,
                result="hello", confidence=0.9,
            ),
            IntentResult(
                intent_id="i1", agent_id="a2", success=True,
                result="hello", confidence=0.8,
            ),
            IntentResult(
                intent_id="i1", agent_id="a3", success=True,
                result="wrong", confidence=0.3,
            ),
        ]
        consensus, value = engine.evaluate_values(results)
        assert consensus.outcome == ConsensusOutcome.APPROVED
        assert value == "hello"

    def test_evaluate_values_insufficient(self):
        engine = QuorumEngine(QuorumPolicy(min_votes=5))
        results = [
            self._make_result("a1", True, 0.8),
        ]
        consensus, value = engine.evaluate_values(results)
        assert consensus.outcome == ConsensusOutcome.INSUFFICIENT
        assert value is None
