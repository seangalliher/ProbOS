"""Shapley value computation for consensus attribution (AD-223)."""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.types import Vote


def _evaluate_coalition(
    coalition_votes: list[Vote],
    approval_threshold: float,
    use_confidence_weights: bool,
) -> bool:
    """Check if a coalition of votes achieves quorum approval."""
    if not coalition_votes:
        return False

    weighted_approval = 0.0
    total_weight = 0.0
    for v in coalition_votes:
        weight = v.confidence if use_confidence_weights else 1.0
        total_weight += weight
        if v.approved:
            weighted_approval += weight

    if total_weight == 0:
        return False
    return (weighted_approval / total_weight) >= approval_threshold


def compute_shapley_values(
    votes: list[Vote],
    approval_threshold: float,
    use_confidence_weights: bool = True,
) -> dict[str, float]:
    """Compute per-agent Shapley values for a consensus outcome.

    Uses the permutation formulation:
      phi_i = (1/|N|!) * sum over all permutations pi of
              [v(S_pi^i union {i}) - v(S_pi^i)]

    where v(S) = 1 if coalition S achieves quorum, 0 otherwise.

    Returns {agent_id: shapley_value} normalized to [0, 1].
    """
    if not votes:
        return {}

    n = len(votes)
    if n == 1:
        return {votes[0].agent_id: 1.0}

    # Map agent_id -> Vote for quick lookup
    vote_by_id: dict[str, Vote] = {v.agent_id: v for v in votes}
    agent_ids = list(vote_by_id.keys())

    # Accumulate marginal contributions
    marginal_sums: dict[str, float] = {aid: 0.0 for aid in agent_ids}
    num_perms = 0

    for perm in itertools.permutations(agent_ids):
        num_perms += 1
        coalition: list[Vote] = []
        for aid in perm:
            # Value without agent i
            v_without = _evaluate_coalition(
                coalition, approval_threshold, use_confidence_weights,
            )
            # Value with agent i
            coalition.append(vote_by_id[aid])
            v_with = _evaluate_coalition(
                coalition, approval_threshold, use_confidence_weights,
            )
            # Marginal contribution: v(S ∪ {i}) - v(S)
            marginal_sums[aid] += float(v_with) - float(v_without)

    # Average over all permutations
    raw_values = {aid: marginal_sums[aid] / num_perms for aid in agent_ids}

    # Normalize: raw values sum to v(N). Normalize to [0, 1].
    total = sum(abs(v) for v in raw_values.values())
    if total > 0:
        normalized = {aid: max(0.0, v) / total for aid, v in raw_values.items()}
    else:
        # All zero — equal split
        normalized = {aid: 1.0 / n for aid in agent_ids}

    return normalized
