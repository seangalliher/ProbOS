"""Shapley value computation for consensus attribution (AD-223)."""

from __future__ import annotations

import itertools
import logging
import math
import random
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from probos.types import Vote

logger = logging.getLogger(__name__)

# BF-850: the exact path enumerates n! permutations, and quorum.py calls it
# synchronously and unguarded on the destructive-op path. Measured cost of the
# exact path: n=8 0.28s, n=9 3.4s, n=10 40.8s. Ten was a factorial cliff wearing
# a round number; eight is the largest coalition that stays inside a 0.5s
# synchronous budget. Above it the Monte Carlo path is used instead.
MAX_EXACT_SHAPLEY = 8


class _PlayerWeight(NamedTuple):
    """One participant's whole ballot set, reduced to the two sums the rule needs.

    BF-837: a participant that voted more than once is one player holding all of
    its ballots, and the coalition rule is linear in them, so the ballots reduce
    to a pair once instead of being re-summed inside every coalition. Measured at
    the ``MAX_EXACT_SHAPLEY`` bound with 25 ballots per player: 0.061 s here
    against 3.23 s for the equivalent form that carries the ballot lists, which
    would have re-broken BF-850's 0.5 s synchronous budget.
    """

    approval: float
    total: float


def usable_confidence(value: object) -> float | None:
    """A confidence that can actually be weighed, or ``None``.

    ``confidence`` is producer-supplied and neither ``Vote`` nor
    ``VerificationResult`` validates it, so both consensus paths reach this
    boundary with whatever a producer put there.

    Measured on each path, and the failures are not symmetric:

    * verdicts (AD-1272) -- ``None`` raised ``TypeError`` out of the sum and
      aborted the round; one ``NaN`` made the total NaN, slipped past a ``<= 0``
      guard, and turned two APPROVALS into a rejection.
    * ballots (AD-1263) -- before this change a duplicate ballot was discarded
      by last-write-wins, so a malformed one was usually swallowed. Now that
      every ballot counts, ``None`` aborted the round and ``NaN``/``inf`` lost
      half the attributable mass (measured: sum 0.500000 against 1.0).

    Negative is unusable for the same reason: it is not a confidence, and it
    would subtract from a total that the rule divides by. ``bool`` is excluded
    explicitly because it subclasses ``int``, so a ballot weighted ``True``
    would otherwise silently mean ``1.0``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    weight = float(value)
    if not math.isfinite(weight) or weight < 0.0:
        return None
    return weight


def _clears_threshold(
    weighted_approval: float, total_weight: float, approval_threshold: float,
) -> bool:
    """The consensus rule, in the one place it is allowed to live.

    ``verification.combine_verdicts`` (AD-1272) documents itself as mirroring
    this arithmetic; it is the same rule at a different scale, so it stays one
    expression.
    """
    if total_weight == 0:
        return False
    return (weighted_approval / total_weight) >= approval_threshold


def _summarise_players(
    votes: list[Vote], use_confidence_weights: bool,
) -> dict[str, _PlayerWeight]:
    """Collapse ballots to one entry per ``agent_id``, first-appearance ordered.

    A player whose ballots carry ANY unweighable confidence is summarised
    unweighted -- one per ballot -- rather than having that ballot dropped.
    Review measured why this cannot be left to raw arithmetic: making every
    ballot count is exactly what stopped last-write-wins from swallowing a
    malformed one, so the fix for BF-837 is what exposed the boundary. ``None``
    aborted the whole consensus round and ``NaN``/``inf`` silently halved the
    attributable mass.

    The degrade is scoped to the PLAYER, not the round: one agent's broken
    metadata must not discard the confidence signal of every other agent. It
    mirrors ``verification.combine_verdicts``, which degrades its own set for
    the same reason at the verdict scale.
    """
    ballots: dict[str, list[Vote]] = {}
    for v in votes:
        ballots.setdefault(v.agent_id, []).append(v)

    players: dict[str, _PlayerWeight] = {}
    for agent_id, cast in ballots.items():
        if use_confidence_weights:
            weights = [usable_confidence(v.confidence) for v in cast]
        else:
            weights = [1.0 for _ in cast]
        if any(w is None for w in weights):
            logger.debug(
                "AD-1263: %d of %d ballot(s) from %s carry no usable confidence; "
                "summarising that player unweighted so a metadata gap neither "
                "aborts the round nor silently drops attributable mass",
                sum(1 for w in weights if w is None), len(cast), agent_id,
            )
            weights = [1.0 for _ in cast]
        players[agent_id] = _PlayerWeight(
            sum(w for w, v in zip(weights, cast) if v.approved),
            sum(weights),
        )
    return players


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

    return _clears_threshold(weighted_approval, total_weight, approval_threshold)


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

    For coalitions larger than MAX_EXACT_SHAPLEY *players*, switches to Monte
    Carlo approximation to avoid factorial explosion.

    The players are agents, not ballots: an agent that voted more than once is
    one player carrying all of its ballots, which enter every coalition together
    and combine by confidence-weighted approval (BF-837).

    Returns {agent_id: shapley_value} normalized to [0, 1].
    """
    if not votes:
        return {}

    # BF-837: one player per agent_id, carrying every ballot it cast. A
    # participant that voted twice used to have its earlier ballot replaced
    # outright, which left the grand coalition failing votes the quorum engine
    # had passed.
    players = _summarise_players(votes, use_confidence_weights)
    agent_ids = list(players.keys())

    # The game is played over players. ``n`` measures the set that actually gets
    # enumerated -- the short circuit, the tier selection and the equal split
    # below all read it, and all three were previously counting ballots.
    n = len(agent_ids)
    if n == 1:
        return {agent_ids[0]: 1.0}

    if n <= MAX_EXACT_SHAPLEY:
        raw_values = _exact_shapley(agent_ids, players, approval_threshold)
    else:
        raw_values = _approximate_shapley(agent_ids, players, approval_threshold)

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
    players: dict[str, _PlayerWeight],
    approval_threshold: float,
) -> dict[str, float]:
    """Exact Shapley over agents via full permutation enumeration."""
    marginal_sums: dict[str, float] = {aid: 0.0 for aid in agent_ids}
    num_perms = 0

    for perm in itertools.permutations(agent_ids):
        num_perms += 1
        approval = 0.0
        total = 0.0
        for aid in perm:
            v_without = _clears_threshold(approval, total, approval_threshold)
            player = players[aid]
            approval += player.approval
            total += player.total
            v_with = _clears_threshold(approval, total, approval_threshold)
            marginal_sums[aid] += float(v_with) - float(v_without)

    return {aid: marginal_sums[aid] / num_perms for aid in agent_ids}


def _approximate_shapley(
    agent_ids: list[str],
    players: dict[str, _PlayerWeight],
    approval_threshold: float,
    samples: int = 1000,
) -> dict[str, float]:
    """Monte Carlo approximation of per-agent Shapley values via random permutations."""
    marginal_sums: dict[str, float] = {aid: 0.0 for aid in agent_ids}

    for _ in range(samples):
        perm = list(agent_ids)
        random.shuffle(perm)
        approval = 0.0
        total = 0.0
        for aid in perm:
            v_without = _clears_threshold(approval, total, approval_threshold)
            player = players[aid]
            approval += player.approval
            total += player.total
            v_with = _clears_threshold(approval, total, approval_threshold)
            marginal_sums[aid] += float(v_with) - float(v_without)

    return {aid: marginal_sums[aid] / samples for aid in agent_ids}
