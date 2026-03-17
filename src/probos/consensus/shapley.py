"""Shapley value computation for consensus attribution (AD-223)."""

from __future__ import annotations

import itertools
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.types import Vote

MAX_EXACT_SHAPLEY = 10


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

    For coalitions larger than MAX_EXACT_SHAPLEY, switches to Monte Carlo
    approximation to avoid factorial explosion.

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

    if n <= MAX_EXACT_SHAPLEY:
        raw_values = _exact_shapley(agent_ids, vote_by_id, approval_threshold, use_confidence_weights)
    else:
        raw_values = _approximate_shapley(agent_ids, vote_by_id, approval_threshold, use_confidence_weights)

    # Normalize: raw values sum to v(N). Normalize to [0, 1].
    total = sum(abs(v) for v in raw_values.values())
    if total > 0:
        normalized = {aid: max(0.0, v) / total for aid, v in raw_values.items()}
    else:
        # All zero — equal split
        normalized = {aid: 1.0 / n for aid in agent_ids}

    return normalized


def _exact_shapley(
    agent_ids: list[str],
    vote_by_id: dict[str, Vote],
    approval_threshold: float,
    use_confidence_weights: bool,
) -> dict[str, float]:
    """Exact Shapley via full permutation enumeration."""
    marginal_sums: dict[str, float] = {aid: 0.0 for aid in agent_ids}
    num_perms = 0

    for perm in itertools.permutations(agent_ids):
        num_perms += 1
        coalition: list[Vote] = []
        for aid in perm:
            v_without = _evaluate_coalition(
                coalition, approval_threshold, use_confidence_weights,
            )
            coalition.append(vote_by_id[aid])
            v_with = _evaluate_coalition(
                coalition, approval_threshold, use_confidence_weights,
            )
            marginal_sums[aid] += float(v_with) - float(v_without)

    return {aid: marginal_sums[aid] / num_perms for aid in agent_ids}


def _approximate_shapley(
    agent_ids: list[str],
    vote_by_id: dict[str, Vote],
    approval_threshold: float,
    use_confidence_weights: bool,
    samples: int = 1000,
) -> dict[str, float]:
    """Monte Carlo approximation of Shapley values via random permutation sampling."""
    marginal_sums: dict[str, float] = {aid: 0.0 for aid in agent_ids}

    for _ in range(samples):
        perm = list(agent_ids)
        random.shuffle(perm)
        coalition: list[Vote] = []
        for aid in perm:
            v_without = _evaluate_coalition(
                coalition, approval_threshold, use_confidence_weights,
            )
            coalition.append(vote_by_id[aid])
            v_with = _evaluate_coalition(
                coalition, approval_threshold, use_confidence_weights,
            )
            marginal_sums[aid] += float(v_with) - float(v_without)

    return {aid: marginal_sums[aid] / samples for aid in agent_ids}
