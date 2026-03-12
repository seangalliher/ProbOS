"""Tests for Phase 19 — Trust-Weighted Capability Matching (AD-225, AD-226)."""

from __future__ import annotations

import pytest

from probos.mesh.capability import CapabilityMatch, CapabilityRegistry
from probos.types import CapabilityDescriptor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cap(can: str, detail: str = "") -> CapabilityDescriptor:
    return CapabilityDescriptor(can=can, detail=detail)


def _registry_with_agents() -> CapabilityRegistry:
    """Registry with two agents both claiming read_file."""
    reg = CapabilityRegistry(semantic_matching=False)
    reg.register("agent-x", [_cap("read_file", "reads files from disk")])
    reg.register("agent-y", [_cap("read_file", "reads files from disk")])
    return reg


# ---------------------------------------------------------------------------
# Trust weighting
# ---------------------------------------------------------------------------


class TestTrustWeightedMatching:
    """CapabilityRegistry.query() with trust_scores (AD-225)."""

    def test_no_trust_scores_unchanged(self):
        """Without trust_scores, behavior is identical to before."""
        reg = _registry_with_agents()

        matches_without = reg.query("read_file")
        matches_with_none = reg.query("read_file", trust_scores=None)

        assert len(matches_without) == len(matches_with_none)
        for a, b in zip(matches_without, matches_with_none):
            assert a.score == b.score

    def test_trust_1_0_no_change(self):
        """Trust 1.0 → score * (0.5 + 0.5*1.0) = score * 1.0, no change."""
        reg = CapabilityRegistry(semantic_matching=False)
        reg.register("a1", [_cap("read_file")])

        [m_base] = reg.query("read_file")
        base_score = m_base.score

        [m_trust] = reg.query("read_file", trust_scores={"a1": 1.0})

        assert abs(m_trust.score - base_score) < 1e-9

    def test_trust_0_0_halved(self):
        """Trust 0.0 → score * (0.5 + 0.5*0.0) = score * 0.5, halved."""
        reg = CapabilityRegistry(semantic_matching=False)
        reg.register("a1", [_cap("read_file")])

        [m_base] = reg.query("read_file")
        base_score = m_base.score

        [m_trust] = reg.query("read_file", trust_scores={"a1": 0.0})

        assert abs(m_trust.score - base_score * 0.5) < 1e-9

    def test_trust_0_5_multiplied(self):
        """Trust 0.5 → score * 0.75."""
        reg = CapabilityRegistry(semantic_matching=False)
        reg.register("a1", [_cap("read_file")])

        [m_base] = reg.query("read_file")
        base_score = m_base.score

        [m_trust] = reg.query("read_file", trust_scores={"a1": 0.5})

        assert abs(m_trust.score - base_score * 0.75) < 1e-9

    def test_higher_trust_ranks_above(self):
        """Agent with trust 0.9 ranks above agent with trust 0.3."""
        reg = _registry_with_agents()

        matches = reg.query(
            "read_file",
            trust_scores={"agent-x": 0.9, "agent-y": 0.3},
        )

        # Both match, but agent-x should rank first due to higher trust
        assert matches[0].agent_id == "agent-x"
        assert matches[1].agent_id == "agent-y"
        assert matches[0].score > matches[1].score

    def test_trust_never_eliminates(self):
        """Trust weighting never zeroes out a match (floor at 50%)."""
        reg = CapabilityRegistry(semantic_matching=False)
        reg.register("a1", [_cap("read_file")])

        [m] = reg.query("read_file", trust_scores={"a1": 0.0})

        assert m.score > 0.0  # Not eliminated

    def test_multiple_agents_correct_ordering(self):
        """Multiple agents with different trust → correct score ordering."""
        reg = CapabilityRegistry(semantic_matching=False)
        reg.register("low", [_cap("read_file")])
        reg.register("mid", [_cap("read_file")])
        reg.register("high", [_cap("read_file")])

        matches = reg.query(
            "read_file",
            trust_scores={"low": 0.1, "mid": 0.5, "high": 0.9},
        )

        # Sort order should be high, mid, low
        ids = [m.agent_id for m in matches]
        assert ids.index("high") < ids.index("mid") < ids.index("low")

    def test_missing_agent_uses_default_trust(self):
        """Agent not in trust_scores dict gets default trust 0.5."""
        reg = CapabilityRegistry(semantic_matching=False)
        reg.register("a1", [_cap("read_file")])

        [m] = reg.query("read_file", trust_scores={})  # a1 not in dict

        # Default trust = 0.5 → factor = 0.75
        base_score = 1.0  # exact match
        assert abs(m.score - base_score * 0.75) < 1e-9


# ---------------------------------------------------------------------------
# Shapley-weighted trust updates
# ---------------------------------------------------------------------------


class TestShapleyTrustUpdates:
    """Shapley values as trust update weights (AD-224)."""

    def test_decisive_gets_stronger_trust_update(self):
        """Decisive agent (high Shapley) gets weight > redundant agent."""
        from probos.consensus.trust import TrustNetwork

        trust = TrustNetwork()

        # Decisive agent gets weight 0.8, redundant gets weight 0.1
        trust.record_outcome("decisive", success=True, weight=0.8)
        trust.record_outcome("redundant", success=True, weight=0.1)

        score_d = trust.get_score("decisive")
        score_r = trust.get_score("redundant")

        assert score_d > score_r

    def test_redundant_gets_weaker_trust_update(self):
        """Redundant agent (low Shapley) gets minimal trust boost."""
        from probos.consensus.trust import TrustNetwork

        trust = TrustNetwork()

        # Both start at default prior
        baseline = trust.get_score("baseline-agent")

        trust.record_outcome("redundant", success=True, weight=0.1)
        score = trust.get_score("redundant")

        # Should be only slightly above baseline
        assert score > baseline
        assert score < baseline + 0.05

    def test_equal_votes_equal_updates(self):
        """Equal Shapley values → identical trust updates (same as before)."""
        from probos.consensus.trust import TrustNetwork

        trust = TrustNetwork()

        trust.record_outcome("a1", success=True, weight=0.5)
        trust.record_outcome("a2", success=True, weight=0.5)

        assert abs(trust.get_score("a1") - trust.get_score("a2")) < 1e-9

    def test_weight_parameter_backward_compat(self):
        """Default weight=1.0 preserves existing behavior."""
        from probos.consensus.trust import TrustNetwork

        trust = TrustNetwork()

        trust.record_outcome("a1", success=True)  # default weight=1.0
        trust.record_outcome("a2", success=True, weight=1.0)  # explicit

        assert abs(trust.get_score("a1") - trust.get_score("a2")) < 1e-9
