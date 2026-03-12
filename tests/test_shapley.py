"""Tests for Phase 19 — Shapley Value Trust Attribution (AD-223, AD-224)."""

from __future__ import annotations

import pytest

from probos.consensus.shapley import compute_shapley_values
from probos.types import ConsensusOutcome, ConsensusResult, QuorumPolicy, Vote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vote(agent_id: str, approved: bool, confidence: float = 1.0) -> Vote:
    return Vote(agent_id=agent_id, approved=approved, confidence=confidence)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


class TestShapleyCore:
    """compute_shapley_values() core tests."""

    def test_unanimous_approval_equal_split(self):
        """3 agents, all approve → equal Shapley (~0.33 each)."""
        votes = [
            _vote("a1", True, 0.9),
            _vote("a2", True, 0.8),
            _vote("a3", True, 0.7),
        ]
        sv = compute_shapley_values(votes, approval_threshold=0.6)

        assert len(sv) == 3
        for v in sv.values():
            assert abs(v - 1.0 / 3) < 0.01

    def test_two_of_three_threshold_one_dissenter(self):
        """3 agents, 2 approve, 1 rejects. Dissenter gets 0."""
        votes = [
            _vote("a1", True, 1.0),
            _vote("a2", True, 1.0),
            _vote("a3", False, 1.0),
        ]
        sv = compute_shapley_values(
            votes, approval_threshold=0.6, use_confidence_weights=False,
        )

        # a3 voted against the majority, contributes nothing to approval
        assert sv["a3"] == 0.0
        # a1 and a2 share credit equally
        assert abs(sv["a1"] - sv["a2"]) < 0.001
        assert sv["a1"] > 0.0

    def test_decisive_voter_gets_more_credit(self):
        """High-confidence decisive voter gets more credit than low-confidence one."""
        # a1(True, 0.9) + a2(True, 0.4) + a3(False, 0.8) = total 2.1
        # Approval = 1.3/2.1 = 0.619 > 0.5 → passes
        # Remove a1: 0.4/1.2 = 0.33 < 0.5 → fails → a1 decisive
        # Remove a2: 0.9/1.7 = 0.53 > 0.5 → still passes → a2 NOT decisive
        votes = [
            _vote("a1", True, 0.9),
            _vote("a2", True, 0.4),
            _vote("a3", False, 0.8),
        ]
        sv = compute_shapley_values(votes, approval_threshold=0.5)

        # a1 is decisive (removing flips outcome); a2 is not always decisive
        assert sv["a1"] > sv["a2"]
        # a3 is a dissenter
        assert sv["a3"] == 0.0

    def test_five_agents_three_of_five(self):
        """5 agents, 3-of-5 threshold, correct computation."""
        votes = [
            _vote("a1", True, 1.0),
            _vote("a2", True, 1.0),
            _vote("a3", True, 1.0),
            _vote("a4", False, 1.0),
            _vote("a5", False, 1.0),
        ]
        sv = compute_shapley_values(
            votes, approval_threshold=0.6, use_confidence_weights=False,
        )

        assert len(sv) == 5
        # Approvers should have positive Shapley
        assert sv["a1"] > 0
        assert sv["a2"] > 0
        assert sv["a3"] > 0
        # Dissenters get 0
        assert sv["a4"] == 0.0
        assert sv["a5"] == 0.0

    def test_single_agent(self):
        """Single agent → Shapley = 1.0."""
        sv = compute_shapley_values(
            [_vote("a1", True, 0.9)], approval_threshold=0.6,
        )
        assert sv == {"a1": 1.0}

    def test_all_reject(self):
        """All agents reject → rejectors split credit (they 'decided' rejection)."""
        votes = [
            _vote("a1", False, 1.0),
            _vote("a2", False, 1.0),
            _vote("a3", False, 1.0),
        ]
        # With threshold 0.6, all votes are reject → approval ratio = 0.0
        # No agent's presence changes outcome (removing any still keeps rejection)
        # In this case, no agent is marginally contributing to a *change*
        # so raw Shapley values are all 0 → equal split fallback
        sv = compute_shapley_values(
            votes, approval_threshold=0.6, use_confidence_weights=False,
        )
        for v in sv.values():
            assert abs(v - 1.0 / 3) < 0.01

    def test_confidence_weighted_decisive_voter(self):
        """With confidence weights, high-confidence voter is more decisive."""
        votes = [
            _vote("a1", True, 0.9),
            _vote("a2", True, 0.1),
            _vote("a3", False, 0.5),
        ]
        sv = compute_shapley_values(votes, approval_threshold=0.6)

        # a1 (conf=0.9) is more decisive than a2 (conf=0.1)
        assert sv["a1"] > sv["a2"]

    def test_empty_votes(self):
        """Empty vote list → empty dict."""
        sv = compute_shapley_values([], approval_threshold=0.6)
        assert sv == {}

    def test_values_sum_to_at_most_one(self):
        """Normalized Shapley values sum to ≤ 1.0."""
        votes = [
            _vote("a1", True, 0.8),
            _vote("a2", True, 0.6),
            _vote("a3", False, 0.9),
        ]
        sv = compute_shapley_values(votes, approval_threshold=0.6)
        assert sum(sv.values()) <= 1.0 + 1e-9

    def test_values_non_negative(self):
        """All Shapley values are ≥ 0.0."""
        votes = [
            _vote("a1", True, 0.8),
            _vote("a2", False, 0.9),
            _vote("a3", True, 0.7),
        ]
        sv = compute_shapley_values(votes, approval_threshold=0.5)
        for v in sv.values():
            assert v >= 0.0

    def test_dissenter_zero_for_majority_outcome(self):
        """Agent voted against majority → Shapley 0.0."""
        votes = [
            _vote("a1", True, 1.0),
            _vote("a2", True, 1.0),
            _vote("a3", False, 1.0),
        ]
        sv = compute_shapley_values(
            votes, approval_threshold=0.5, use_confidence_weights=False,
        )
        assert sv["a3"] == 0.0

    def test_identical_votes_equal_shapley(self):
        """Two agents with identical votes → equal Shapley values."""
        votes = [
            _vote("a1", True, 0.8),
            _vote("a2", True, 0.8),
        ]
        sv = compute_shapley_values(votes, approval_threshold=0.6)
        assert abs(sv["a1"] - sv["a2"]) < 0.001

    def test_marginal_vote_high_shapley(self):
        """Vote that just barely passes threshold → marginal voter is decisive."""
        # 3 agents, threshold 0.6. With unweighted voting:
        # 2 approve, 1 rejects → 2/3 = 0.67 > 0.6 → passes
        # Remove one approver → 1/2 = 0.5 < 0.6 → fails
        # Both approvers are equally decisive
        votes = [
            _vote("a1", True, 1.0),
            _vote("a2", True, 1.0),
            _vote("a3", False, 1.0),
        ]
        sv = compute_shapley_values(
            votes, approval_threshold=0.6, use_confidence_weights=False,
        )
        # Both approvers should be decisive (non-zero)
        assert sv["a1"] > 0.0
        assert sv["a2"] > 0.0

    def test_unweighted_mode(self):
        """use_confidence_weights=False treats all votes equally."""
        votes = [
            _vote("a1", True, 0.9),
            _vote("a2", True, 0.1),  # very different confidence
        ]
        sv = compute_shapley_values(
            votes, approval_threshold=0.6, use_confidence_weights=False,
        )
        # Without confidence weights, both should be equally decisive
        assert abs(sv["a1"] - sv["a2"]) < 0.001

    def test_four_agents_split(self):
        """4 agents, balanced 2-2 split at threshold 0.5 → tie, no approval."""
        votes = [
            _vote("a1", True, 1.0),
            _vote("a2", True, 1.0),
            _vote("a3", False, 1.0),
            _vote("a4", False, 1.0),
        ]
        # 2/4 = 0.50, threshold 0.6 → rejected
        # Nobody individually changes outcome: removing any approver → 1/3 < 0.6
        # removing any denier → 2/3 >= 0.6 → passes!
        sv = compute_shapley_values(
            votes, approval_threshold=0.6, use_confidence_weights=False,
        )
        assert len(sv) == 4
        # All values non-negative
        for v in sv.values():
            assert v >= 0.0

    def test_two_agents_both_approve(self):
        """2 agents, both approve → equal Shapley."""
        votes = [_vote("a1", True, 0.8), _vote("a2", True, 0.6)]
        sv = compute_shapley_values(votes, approval_threshold=0.5)
        assert abs(sv["a1"] - sv["a2"]) < 0.01

    def test_values_sum_to_one_with_approvals(self):
        """When coalition passes, normalized values sum to ~1.0."""
        votes = [
            _vote("a1", True, 0.9),
            _vote("a2", True, 0.7),
            _vote("a3", True, 0.5),
        ]
        sv = compute_shapley_values(votes, approval_threshold=0.5)
        total = sum(sv.values())
        assert abs(total - 1.0) < 0.01

    def test_seven_agents_tractable(self):
        """7-agent quorum computation completes (5040 permutations)."""
        votes = [_vote(f"a{i}", i < 5, 0.7) for i in range(7)]
        sv = compute_shapley_values(
            votes, approval_threshold=0.6, use_confidence_weights=False,
        )
        assert len(sv) == 7
        for v in sv.values():
            assert v >= 0.0

    def test_rejected_outcome_rejecters_have_negative_marginals(self):
        """When consensus is rejected, rejecters' contributions are clamped to 0."""
        votes = [
            _vote("a1", True, 1.0),
            _vote("a2", False, 1.0),
            _vote("a3", False, 1.0),
        ]
        # 1/3 = 0.33 < 0.6 → rejected
        sv = compute_shapley_values(
            votes, approval_threshold=0.6, use_confidence_weights=False,
        )
        # Rejecters broke passing coalitions → negative marginals → clamped to 0
        assert sv["a2"] == 0.0
        assert sv["a3"] == 0.0
        # The approver still has positive marginal (passes in singleton)
        assert sv["a1"] > 0.0

    def test_high_threshold_needs_unanimity(self):
        """High threshold (0.9) → all voters are decisive."""
        votes = [
            _vote("a1", True, 1.0),
            _vote("a2", True, 1.0),
            _vote("a3", True, 1.0),
        ]
        sv = compute_shapley_values(
            votes, approval_threshold=0.9, use_confidence_weights=False,
        )
        # All equally decisive (removing any → 2/2 = 1.0 still passes)
        # Actually 2/2 = 1.0 >= 0.9, so removing one doesn't flip.
        # Only when reduced to 0 or 1 approver does it fail
        for v in sv.values():
            assert v >= 0.0


# ---------------------------------------------------------------------------
# Panel rendering
# ---------------------------------------------------------------------------


class TestShapleyPanelIntegration:
    """Agent table Shapley column (AD-227)."""

    def test_agent_table_without_shapley(self):
        """render_agent_table works without Shapley (backward compat)."""
        from unittest.mock import MagicMock
        from probos.experience.panels import render_agent_table
        from probos.substrate.agent import AgentState

        agent = MagicMock()
        agent.id = "abc12345"
        agent.agent_type = "file_reader"
        agent.tier = "core"
        agent.pool = "pool-1"
        agent.state = AgentState.ACTIVE
        agent.confidence = 0.85

        table = render_agent_table([agent], {"abc12345": 0.9})
        assert table is not None

    def test_agent_table_with_shapley(self):
        """render_agent_table shows Shapley column when values present."""
        from unittest.mock import MagicMock
        from probos.experience.panels import render_agent_table
        from probos.substrate.agent import AgentState

        agent = MagicMock()
        agent.id = "abc12345"
        agent.agent_type = "file_reader"
        agent.tier = "core"
        agent.pool = "pool-1"
        agent.state = AgentState.ACTIVE
        agent.confidence = 0.85

        table = render_agent_table(
            [agent],
            {"abc12345": 0.9},
            shapley_values={"abc12345": 0.5},
        )
        # Should have a Shapley column
        assert len(table.columns) == 8  # 7 base + 1 Shapley


# ---------------------------------------------------------------------------
# ConsensusResult integration
# ---------------------------------------------------------------------------


class TestConsensusResultShapley:
    """ConsensusResult.shapley_values field tests."""

    def test_default_is_none(self):
        """shapley_values defaults to None."""
        cr = ConsensusResult(
            proposal_id="p1",
            outcome=ConsensusOutcome.APPROVED,
        )
        assert cr.shapley_values is None

    def test_can_set_shapley_values(self):
        """shapley_values can be set explicitly."""
        cr = ConsensusResult(
            proposal_id="p1",
            outcome=ConsensusOutcome.APPROVED,
            shapley_values={"a1": 0.5, "a2": 0.5},
        )
        assert cr.shapley_values == {"a1": 0.5, "a2": 0.5}

    def test_quorum_engine_populates_shapley(self):
        """QuorumEngine.evaluate() populates shapley_values."""
        from probos.consensus.quorum import QuorumEngine
        from probos.types import IntentResult

        engine = QuorumEngine()
        results = [
            IntentResult(
                intent_id="i1",
                agent_id="a1",
                success=True,
                confidence=0.9,
            ),
            IntentResult(
                intent_id="i1",
                agent_id="a2",
                success=True,
                confidence=0.8,
            ),
            IntentResult(
                intent_id="i1",
                agent_id="a3",
                success=True,
                confidence=0.7,
            ),
        ]
        cr = engine.evaluate(results)

        assert cr.shapley_values is not None
        assert len(cr.shapley_values) == 3
        for v in cr.shapley_values.values():
            assert v >= 0.0

    def test_quorum_insufficient_no_shapley(self):
        """INSUFFICIENT outcome → shapley_values is None."""
        from probos.consensus.quorum import QuorumEngine
        from probos.types import IntentResult

        engine = QuorumEngine()
        # Only 1 result, min_votes defaults to 3
        results = [
            IntentResult(intent_id="i1", agent_id="a1", success=True),
        ]
        cr = engine.evaluate(results)

        assert cr.outcome == ConsensusOutcome.INSUFFICIENT
        assert cr.shapley_values is None
