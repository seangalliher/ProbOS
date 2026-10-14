"""AD-1326 (#1510): deterministic ranking of procedure candidates from pairwise outcomes.

A Bradley-Terry model gives each candidate a strength ``p``; ``i`` is expected to
beat ``j`` with probability ``p_i / (p_i + p_j)``. :func:`bradley_terry` fits it
with Hunter's MM iteration (Ann. Statist. 32(1), 2004). Two choices make the fit
total and deterministic:

- **Pseudo-counts.** Every pair that met at least once gets ``prior`` extra wins on
  each side, so a candidate that never won still has a finite, positive strength.
- **A reference.** The reference (the champion) is pinned to strength 1.0. On a
  star -- every candidate compared only with the reference, which is what dream
  consolidation produces -- the fit is closed-form:
  ``p_i = (w_i + t_i / 2 + prior) / (l_i + t_i / 2 + prior)``, and it is returned
  directly. With the default prior every count is a multiple of 0.5, so two equal
  records give ``==`` strengths and the caller's tie-break decides, not solver
  roundoff (``test_bradley_terry_star_equal_records_are_exactly_equal``).

A tie counts half a win to each side. Outcomes are folded into per-pair counts in
sorted order and players are updated in sorted order, so one set of outcomes gives
bit-identical strengths in whatever order it arrives
(``test_bradley_terry_is_order_independent_bit_for_bit``).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

PairResult = Literal["first", "second", "tie"]

DEFAULT_PRIOR = 0.5
MAX_ITERATIONS = 1000
TOLERANCE = 1e-12


@dataclass(frozen=True)
class PairOutcome:
    """One pairwise judgement between ``first`` and ``second``."""

    first: str
    second: str
    result: PairResult

    def __post_init__(self) -> None:
        if type(self.first) is not str or type(self.second) is not str:
            raise ValueError("pair_outcome_invalid")
        if not self.first or not self.second or self.first == self.second:
            raise ValueError("pair_outcome_invalid")
        if self.result not in ("first", "second", "tie"):
            raise ValueError("pair_outcome_invalid")


def _pair_wins(outcomes: Iterable[PairOutcome], prior: float) -> dict[tuple[str, str], list[float]]:
    """``(a, b)`` with ``a < b`` -> ``[wins of a, wins of b]``: ties halved, pseudo-counts added."""
    counts: dict[tuple[str, str], list[float]] = {}
    for outcome in sorted(outcomes, key=lambda o: (o.first, o.second, o.result)):
        a, b = sorted((outcome.first, outcome.second))
        wins = counts.setdefault((a, b), [prior, prior])
        if outcome.result == "tie":
            wins[0] += 0.5
            wins[1] += 0.5
        else:
            winner = outcome.first if outcome.result == "first" else outcome.second
            wins[0 if winner == a else 1] += 1.0
    return counts


def _require_connected(links: dict[str, list[tuple[str, float, float]]], reference: str) -> None:
    reached = {reference}
    frontier = [reference]
    while frontier:
        name = frontier.pop()
        for other, _, _ in links[name]:
            if other not in reached:
                reached.add(other)
                frontier.append(other)
    if len(reached) != len(links):
        raise ValueError("bradley_terry_disconnected")


def bradley_terry(
    outcomes: Iterable[PairOutcome],
    *,
    reference: str,
    prior: float = DEFAULT_PRIOR,
    max_iterations: int = MAX_ITERATIONS,
    tolerance: float = TOLERANCE,
) -> dict[str, float]:
    """Strength per player, ``reference`` pinned to 1.0.

    Raises ``ValueError`` for an empty or non-string reference, a prior that is not
    a positive finite number, ``max_iterations < 1``, a negative tolerance, or a
    player with no chain of comparisons to the reference (its scale would be
    arbitrary). No outcomes gives ``{reference: 1.0}``.
    """
    if type(reference) is not str or not reference:
        raise ValueError("bradley_terry_reference_invalid")
    if not (math.isfinite(prior) and prior > 0.0):
        raise ValueError("bradley_terry_prior_invalid")
    if max_iterations < 1 or not tolerance >= 0.0:
        raise ValueError("bradley_terry_iteration_invalid")
    counts = _pair_wins(outcomes, prior)
    players = sorted({reference, *(name for pair in counts for name in pair)})
    links: dict[str, list[tuple[str, float, float]]] = {name: [] for name in players}
    for (first, second), (first_wins, second_wins) in sorted(counts.items()):
        games = first_wins + second_wins
        links[first].append((second, first_wins, games))
        links[second].append((first, second_wins, games))
    _require_connected(links, reference)
    if all(reference in pair for pair in counts):
        # A star: each candidate met only the reference, so its strength is its wins over the
        # reference's wins in their pair, computed directly (exact; no iteration roundoff).
        star = {reference: 1.0}
        for (first, second), (first_wins, second_wins) in counts.items():
            if first == reference:
                star[second] = second_wins / first_wins
            else:
                star[first] = first_wins / second_wins
        return {name: star[name] for name in players}
    strength = dict.fromkeys(players, 1.0)
    for _ in range(max_iterations):
        previous = dict(strength)
        for name in players:
            if not links[name]:
                continue
            wins = sum(won for _, won, _ in links[name])
            spread = sum(games / (strength[name] + strength[other]) for other, _, games in links[name])
            strength[name] = wins / spread
        scale = strength[reference]
        for name in players:
            strength[name] /= scale
        if max(abs(strength[name] - previous[name]) / previous[name] for name in players) <= tolerance:
            break
    return strength


def beats_champion(*, wins: int, decisions: int, min_decisions: int, margin: float) -> bool:
    """AD-1326: whether ``wins`` of ``decisions`` counted judgements promote a challenger.

    True only with at least ``min_decisions`` (and at least one) judgements and a
    win share strictly above ``0.5 + margin``. Ties and losses count against it.
    """
    if decisions < max(min_decisions, 1) or wins < 0 or wins > decisions:
        return False
    return wins / decisions > 0.5 + margin
