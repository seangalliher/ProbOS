"""AD-1326 (#1510), Milestone 1: ranking procedure candidates from pairwise outcomes.

Every expected strength is hand-computed from D5. A candidate compared only with the
champion (the reference, pinned to 1.0) has the closed form
``p = (w + t / 2 + 0.5) / (l + t / 2 + 0.5)`` for ``w`` wins, ``t`` ties and ``l`` losses.
A challenger is promoted only on a win share strictly above ``0.5 + margin`` over at
least ``min_decisions`` counted judgements.
"""

from __future__ import annotations

import dataclasses
import itertools
import math

import pytest

from probos.cognitive.procedure_ranking import PairOutcome, beats_champion, bradley_terry

REFERENCE = "R"


class _StrSubclass(str):
    """A ``str`` that is not exactly a ``str``: the module checks ``type(x) is str``."""


def _wins(candidate: str, count: int) -> list[PairOutcome]:
    """``count`` wins of ``candidate`` over the reference, alternating which one is listed first."""
    return [
        PairOutcome(candidate, REFERENCE, "first") if index % 2 == 0
        else PairOutcome(REFERENCE, candidate, "second")
        for index in range(count)
    ]


def _losses(candidate: str, count: int) -> list[PairOutcome]:
    """``count`` losses of ``candidate`` to the reference, alternating which one is listed first."""
    return [
        PairOutcome(REFERENCE, candidate, "first") if index % 2 == 0
        else PairOutcome(candidate, REFERENCE, "second")
        for index in range(count)
    ]


def _ties(candidate: str, count: int) -> list[PairOutcome]:
    """``count`` ties between ``candidate`` and the reference, alternating which one is listed first."""
    return [
        PairOutcome(candidate, REFERENCE, "tie") if index % 2 == 0
        else PairOutcome(REFERENCE, candidate, "tie")
        for index in range(count)
    ]


# The ids of the reviewer's probe (logs/architect/probe_ad1326_r1_findings.py, F4): UUID-shaped, with the
# reference sorting BETWEEN the two candidates, so one candidate's pair is (candidate, reference) and the
# other's is (reference, candidate): both orientations of a pair are exercised at once.
PROBE_REFERENCE = "55555555-0000-4000-8000-000000000000"
PROBE_BEFORE = "11111111-0000-4000-8000-000000000000"  # sorts before the reference
PROBE_AFTER = "99999999-0000-4000-8000-000000000000"  # sorts after the reference


def _mm_equations(
    outcomes: list[PairOutcome], strengths: dict[str, float], prior: float = 0.5,
) -> dict[str, tuple[float, float]]:
    """Per player ``(p_i * sum_j n_ij / (p_i + p_j), w_i)``: the two sides are equal at the Bradley-Terry fit.

    Written from the model and not from the module under test. ``w_i`` is the player's wins (a tie is half a
    win to each side) plus ``prior`` for every opponent it met; ``n_ij`` is the same count for the pair
    ``(i, j)``, both sides together.
    """
    wins: dict[str, float] = {}
    games: dict[frozenset[str], float] = {}
    for outcome in outcomes:
        pair = frozenset((outcome.first, outcome.second))
        if pair not in games:
            games[pair] = 2 * prior
            for name in pair:
                wins[name] = wins.get(name, 0.0) + prior
        games[pair] += 1.0
        if outcome.result == "tie":
            wins[outcome.first] += 0.5
            wins[outcome.second] += 0.5
        else:
            wins[outcome.first if outcome.result == "first" else outcome.second] += 1.0
    spread = dict.fromkeys(wins, 0.0)
    for pair, total in games.items():
        first, second = tuple(pair)
        share = total / (strengths[first] + strengths[second])
        spread[first] += share
        spread[second] += share
    return {name: (strengths[name] * spread[name], wins[name]) for name in wins}


# ---------------------------------------------------------------------------
# bradley_terry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("candidate", ["A", "Z"])
def test_bradley_terry_star_matches_closed_form(candidate: str) -> None:
    """3 wins and 1 loss against the reference: (3 + 0.5) / (1 + 0.5), whichever name sorts first."""
    strengths = bradley_terry(_wins(candidate, 3) + _losses(candidate, 1), reference=REFERENCE)

    assert set(strengths) == {REFERENCE, candidate}
    assert strengths[REFERENCE] == 1.0  # exactly: the reference is pinned, not fitted
    assert strengths == pytest.approx({REFERENCE: 1.0, candidate: 3.5 / 1.5}, rel=1e-9)


def test_bradley_terry_star_with_ties_counts_half_each() -> None:
    """1 win, 2 ties, 0 losses: (1 + 2 / 2 + 0.5) / (0 + 2 / 2 + 0.5)."""
    strengths = bradley_terry(_wins("A", 1) + _ties("A", 2), reference=REFERENCE)

    assert strengths[REFERENCE] == 1.0
    assert strengths == pytest.approx({REFERENCE: 1.0, "A": 2.5 / 1.5}, rel=1e-9)


def test_bradley_terry_candidate_that_never_won_is_finite() -> None:
    """0 wins, 4 losses: the prior keeps the strength positive, 0.5 / 4.5."""
    strengths = bradley_terry(_losses("B", 4), reference=REFERENCE)

    assert math.isfinite(strengths["B"])
    assert strengths["B"] > 0.0
    assert strengths == pytest.approx({REFERENCE: 1.0, "B": 0.5 / 4.5}, rel=1e-9)


def test_bradley_terry_cycle_is_uniform() -> None:
    """A beats B, B beats C, C beats A: nobody is ahead, whichever one is the reference."""
    outcomes = [
        PairOutcome("A", "B", "first"),
        PairOutcome("B", "C", "first"),
        PairOutcome("C", "A", "first"),
    ]

    strengths = bradley_terry(outcomes, reference="A")

    assert strengths == pytest.approx({"A": 1.0, "B": 1.0, "C": 1.0}, rel=1e-9)


def test_bradley_terry_two_candidates_decouple_on_a_star() -> None:
    """On a star each candidate depends only on its own record against the reference."""
    outcomes = _wins("A", 3) + _losses("A", 1) + _losses("B", 4)

    strengths = bradley_terry(outcomes, reference=REFERENCE)

    assert strengths[REFERENCE] == 1.0
    assert strengths == pytest.approx(
        {REFERENCE: 1.0, "A": 3.5 / 1.5, "B": 0.5 / 4.5}, rel=1e-9,
    )


def test_bradley_terry_no_outcomes_returns_reference_only() -> None:
    assert bradley_terry([], reference=REFERENCE) == {REFERENCE: 1.0}
    assert bradley_terry(iter(()), reference=REFERENCE) == {REFERENCE: 1.0}  # any iterable


@pytest.mark.parametrize(
    ("two_wins_two_ties", "three_wins_one_loss"),
    [
        pytest.param(PROBE_AFTER, PROBE_BEFORE, id="2W2T-sorts-after-the-reference"),
        pytest.param(PROBE_BEFORE, PROBE_AFTER, id="2W2T-sorts-before-the-reference"),
    ],
)
def test_bradley_terry_star_equal_records_are_exactly_equal(
    two_wins_two_ties: str, three_wins_one_loss: str,
) -> None:
    """R1 (F4): 2W2T and 3W1L are one record, (w + t / 2 + 0.5) / (l + t / 2 + 0.5) = 3.5 / 1.5 either way.

    Equal records must give ``==`` strengths, so the caller's tie-break decides and not solver roundoff.
    The comparisons are exact on purpose, in both layouts of which candidate holds which record. Measured:
    the MM iteration run on this star leaves the two candidates about 8.6e-12 apart in either layout.
    """
    outcomes = (
        [PairOutcome(two_wins_two_ties, PROBE_REFERENCE, "first")] * 2
        + [PairOutcome(two_wins_two_ties, PROBE_REFERENCE, "tie")] * 2
        + [PairOutcome(three_wins_one_loss, PROBE_REFERENCE, "first")] * 3
        + [PairOutcome(three_wins_one_loss, PROBE_REFERENCE, "second")]
    )

    strengths = bradley_terry(outcomes, reference=PROBE_REFERENCE)

    assert set(strengths) == {PROBE_REFERENCE, PROBE_BEFORE, PROBE_AFTER}
    assert strengths[PROBE_REFERENCE] == 1.0
    assert strengths[two_wins_two_ties] == strengths[three_wins_one_loss]  # not approx: equal records are equal
    assert strengths[two_wins_two_ties] == 3.5 / 1.5
    assert strengths[three_wins_one_loss] == 3.5 / 1.5


def test_bradley_terry_non_star_still_iterates() -> None:
    """R1 (F4): A never met the reference, so no closed form applies and the strengths are the MM fixed point.

    A beats B twice, loses once and ties once (A 3.0, B 2.0 with the prior); B beats R once and loses to it
    three times (B 1.5, R 3.5). Hand-solved: p_R = 1, p_B = 3/7, p_A = 9/14.
    """
    outcomes = [
        PairOutcome("A", "B", "first"),
        PairOutcome("B", "A", "second"),
        PairOutcome("A", "B", "second"),
        PairOutcome("A", "B", "tie"),
        PairOutcome("B", REFERENCE, "first"),
        PairOutcome(REFERENCE, "B", "first"),
        PairOutcome("B", REFERENCE, "second"),
        PairOutcome(REFERENCE, "B", "first"),
    ]
    assert not all(REFERENCE in (o.first, o.second) for o in outcomes)  # premise: not a star

    strengths = bradley_terry(outcomes, reference=REFERENCE)

    assert set(strengths) == {"A", "B", REFERENCE}
    # Exactly 1.0: the fixed point below is scale-free (every p multiplied by c still satisfies it),
    # so only the pin on the reference fixes the scale.
    assert strengths[REFERENCE] == 1.0
    equations = _mm_equations(outcomes, strengths)
    assert set(equations) == {"A", "B", REFERENCE}
    for name, (fitted, wins) in equations.items():
        assert fitted == pytest.approx(wins, rel=1e-9), f"{name}: p_i * sum(n_ij / (p_i + p_j)) != w_i"
    assert strengths == pytest.approx({REFERENCE: 1.0, "A": 9 / 14, "B": 3 / 7}, rel=1e-9)


def test_bradley_terry_is_order_independent_bit_for_bit() -> None:
    """A 6-outcome list with wins, ties, both orientations and a cycle through the reference."""
    outcomes = (
        PairOutcome("A", "R", "first"),
        PairOutcome("R", "A", "tie"),
        PairOutcome("B", "A", "first"),
        PairOutcome("A", "B", "second"),
        PairOutcome("C", "B", "tie"),
        PairOutcome("R", "C", "first"),
    )
    baseline = bradley_terry(outcomes, reference=REFERENCE)
    # Premise: the fit is not trivial, so a different summation order could change low bits.
    assert len(set(baseline.values())) == 4

    permutations = list(itertools.permutations(outcomes))
    assert len(permutations) == 720
    different = [
        permutation for permutation in permutations
        if bradley_terry(permutation, reference=REFERENCE) != baseline
    ]
    assert different == []


@pytest.mark.parametrize(
    "outcomes",
    [
        pytest.param([PairOutcome("B", "C", "first")], id="players-never-meet-the-reference"),
        pytest.param(
            [PairOutcome("A", "R", "first"), PairOutcome("B", "C", "tie")],
            id="a-second-component-beside-the-reference",
        ),
        pytest.param(
            [PairOutcome("A", "R", "first"), PairOutcome("B", "C", "first"), PairOutcome("C", "D", "tie")],
            id="a-chain-that-never-reaches-the-reference",
        ),
    ],
)
def test_bradley_terry_rejects_disconnected_players(outcomes: list[PairOutcome]) -> None:
    with pytest.raises(ValueError, match="bradley_terry_disconnected"):
        bradley_terry(outcomes, reference=REFERENCE)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        pytest.param({"reference": ""}, "bradley_terry_reference_invalid", id="empty-reference"),
        pytest.param({"reference": None}, "bradley_terry_reference_invalid", id="none-reference"),
        pytest.param({"reference": 7}, "bradley_terry_reference_invalid", id="int-reference"),
        pytest.param({"reference": b"R"}, "bradley_terry_reference_invalid", id="bytes-reference"),
        pytest.param(
            {"reference": _StrSubclass("R")}, "bradley_terry_reference_invalid", id="str-subclass-reference",
        ),
        pytest.param({"prior": 0.0}, "bradley_terry_prior_invalid", id="zero-prior"),
        pytest.param({"prior": -0.5}, "bradley_terry_prior_invalid", id="negative-prior"),
        pytest.param({"prior": float("nan")}, "bradley_terry_prior_invalid", id="nan-prior"),
        pytest.param({"prior": float("inf")}, "bradley_terry_prior_invalid", id="inf-prior"),
        pytest.param({"max_iterations": 0}, "bradley_terry_iteration_invalid", id="zero-max-iterations"),
        pytest.param({"tolerance": -1e-12}, "bradley_terry_iteration_invalid", id="negative-tolerance"),
        pytest.param({"tolerance": float("nan")}, "bradley_terry_iteration_invalid", id="nan-tolerance"),
    ],
)
def test_bradley_terry_rejects_bad_arguments(overrides: dict[str, object], message: str) -> None:
    """The outcomes are valid and connected: the one bad argument is the only reason to refuse."""
    arguments: dict[str, object] = {"reference": REFERENCE, **overrides}

    with pytest.raises(ValueError, match=message):
        bradley_terry(_wins("A", 2), **arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"max_iterations": 1}, id="one-iteration"),
        pytest.param({"tolerance": 0.0}, id="zero-tolerance"),
        pytest.param({"prior": 1e-9}, id="tiny-positive-prior"),
    ],
)
def test_bradley_terry_accepts_the_boundary_arguments(overrides: dict[str, float]) -> None:
    """The positive controls of the rejection test: the nearest valid values still fit."""
    strengths = bradley_terry(_wins("A", 2) + _losses("A", 1), reference=REFERENCE, **overrides)

    assert set(strengths) == {REFERENCE, "A"}
    assert strengths[REFERENCE] == 1.0
    assert math.isfinite(strengths["A"]) and strengths["A"] > 0.0


# ---------------------------------------------------------------------------
# PairOutcome
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second", "result"),
    [
        pytest.param("A", "A", "first", id="self-pair"),
        pytest.param("A", "A", "tie", id="self-pair-tie"),
        pytest.param("", "B", "first", id="empty-first"),
        pytest.param("A", "", "second", id="empty-second"),
        pytest.param("", "", "tie", id="both-empty"),
        pytest.param("A", "B", "win", id="unknown-result"),
        pytest.param("A", "B", "", id="empty-result"),
        pytest.param("A", "B", "FIRST", id="result-is-case-sensitive"),
        pytest.param("A", "B", None, id="none-result"),
        pytest.param(None, "B", "first", id="none-first"),
        pytest.param("A", 1, "first", id="int-second"),
        pytest.param(_StrSubclass("A"), "B", "first", id="str-subclass-first"),
    ],
)
def test_pair_outcome_rejects_self_pair_empty_and_unknown_result(
    first: object, second: object, result: object,
) -> None:
    with pytest.raises(ValueError, match="pair_outcome_invalid"):
        PairOutcome(first, second, result)  # type: ignore[arg-type]


@pytest.mark.parametrize("result", ["first", "second", "tie"])
def test_pair_outcome_accepts_each_result_and_is_immutable(result: str) -> None:
    """The positive control of the rejection test: each documented result is kept as given."""
    outcome = PairOutcome("A", "B", result)  # type: ignore[arg-type]

    assert (outcome.first, outcome.second, outcome.result) == ("A", "B", result)
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.result = "first"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# beats_champion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("wins", "decisions", "margin", "expected"),
    [
        pytest.param(3, 4, 0.1, True, id="three-of-four-is-0.75-above-0.6"),
        pytest.param(3, 5, 0.1, False, id="three-of-five-is-exactly-0.6-and-not-above-it"),
        pytest.param(2, 4, 0.1, False, id="two-of-four-is-0.5"),
        # The margin is what moves the line: the same 3 of 5 passes at margin 0 ...
        pytest.param(3, 5, 0.0, True, id="three-of-five-passes-at-zero-margin"),
        # ... and "strictly above" holds there too: a tie at 0.5 is not a win.
        pytest.param(2, 4, 0.0, False, id="two-of-four-is-not-above-0.5-at-zero-margin"),
    ],
)
def test_beats_champion_requires_share_strictly_above_threshold(
    wins: int, decisions: int, margin: float, expected: bool,
) -> None:
    assert beats_champion(wins=wins, decisions=decisions, min_decisions=3, margin=margin) is expected


@pytest.mark.parametrize(
    ("wins", "decisions", "min_decisions", "expected"),
    [
        pytest.param(2, 2, 3, False, id="all-wins-but-fewer-than-the-minimum"),
        pytest.param(0, 0, 3, False, id="no-decisions"),
        pytest.param(0, 0, 0, False, id="no-decisions-even-with-a-zero-minimum"),
        pytest.param(3, 3, 3, True, id="exactly-the-minimum-is-enough"),
    ],
)
def test_beats_champion_requires_min_decisions(
    wins: int, decisions: int, min_decisions: int, expected: bool,
) -> None:
    assert beats_champion(wins=wins, decisions=decisions, min_decisions=min_decisions, margin=0.1) is expected


@pytest.mark.parametrize(
    ("wins", "decisions", "margin"),
    [
        # Unguarded, 5 / 4 = 1.25 would clear 0.6: only the consistency check refuses it.
        pytest.param(5, 4, 0.1, id="more-wins-than-decisions"),
        pytest.param(-1, 4, 0.1, id="negative-wins"),
        # Unguarded, -0.25 would clear 0.5 - 0.9 = -0.4: the only margin at which a negative
        # share can pass, so the one case in which the consistency check is what refuses it.
        pytest.param(-1, 4, -0.9, id="negative-wins-that-would-pass-a-negative-margin"),
    ],
)
def test_beats_champion_rejects_inconsistent_counts(wins: int, decisions: int, margin: float) -> None:
    assert beats_champion(wins=wins, decisions=decisions, min_decisions=3, margin=margin) is False
