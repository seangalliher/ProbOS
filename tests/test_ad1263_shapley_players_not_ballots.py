"""AD-1263 / BF-837 — the Shapley game is played over agents, not over ballots.

``compute_shapley_values`` used to build ``{v.agent_id: v}``, so a participant
that voted twice had its earlier ballot replaced outright while ``n`` kept
counting the ballots that arrived. One field was doing two jobs — "ballots that
arrived" against "players in the game" — and the two were spent
interchangeably. The sharpest consequence was that the characteristic function
reported the grand coalition failing a vote the quorum engine had passed.

Every test here asserts returned values or conservation. **No Monte Carlo figure
is asserted anywhere**: above ``MAX_EXACT_SHAPLEY`` players the values are
sampled and vary between evaluations, so the approximate path is pinned only by
which path ran, its key set, and ``sum <= 1.0``.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from probos.consensus import shapley
from probos.consensus.quorum import QuorumEngine
from probos.consensus.shapley import (
    MAX_EXACT_SHAPLEY,
    _PlayerWeight,
    _clears_threshold,
    _summarise_players,
    compute_shapley_values,
    usable_confidence,
)
from probos.runtime import ProbOSRuntime
from probos.types import (
    ConsensusOutcome,
    IntentResult,
    QuorumPolicy,
    VerificationResult,
    Vote,
)

THRESHOLD = QuorumPolicy().approval_threshold  # 0.6


def _vote(agent_id: str, approved: bool, confidence: float = 0.8) -> Vote:
    return Vote(
        agent_id=agent_id, approved=approved, confidence=confidence, reason="r",
    )


class TestPlayersNotBallots:
    def test_a_duplicate_ballot_no_longer_replaces_its_predecessor(self):
        """F1: A's approving ballot used to be discarded, crediting A as a pure
        dissenter at 0.0 while B and C split the game."""
        votes = [
            _vote("A", True, 0.9),
            _vote("A", False, 0.2),
            _vote("B", True, 0.8),
            _vote("C", True, 0.8),
        ]

        sv = compute_shapley_values(votes, THRESHOLD)

        assert set(sv) == {"A", "B", "C"}, "every participant is a player"
        assert sv["A"] == pytest.approx(1 / 3)
        assert sv["B"] == pytest.approx(1 / 3)
        assert sv["C"] == pytest.approx(1 / 3)
        assert sum(sv.values()) == pytest.approx(1.0)

    def test_ballot_arrival_order_does_not_change_attribution(self):
        """F2: last-write-wins made attribution depend on which concurrent task
        happened to return first — A got 0.0 or 0.5 on identical ballots."""
        approve_first = [
            _vote("A", True, 0.9), _vote("A", False, 0.2), _vote("B", True, 0.8),
        ]
        reject_first = [
            _vote("A", False, 0.2), _vote("A", True, 0.9), _vote("B", True, 0.8),
        ]

        first = compute_shapley_values(approve_first, THRESHOLD)
        second = compute_shapley_values(reject_first, THRESHOLD)

        assert first == second
        assert first == pytest.approx({"A": 0.5, "B": 0.5})

    def test_a_players_ballots_combine_by_confidence_weighted_approval(self):
        """The combination rule is the one ``_evaluate_coalition`` already owned,
        which ``verification.combine_verdicts`` documents itself as mirroring."""
        assert _clears_threshold(0.9, 1.1, THRESHOLD) is True  # 0.818 >= 0.6
        assert _clears_threshold(0.2, 1.1, THRESHOLD) is False  # 0.181 < 0.6

        players = _summarise_players(
            [_vote("A", True, 0.9), _vote("A", False, 0.2)], True,
        )

        assert isinstance(players["A"], _PlayerWeight)
        assert players["A"].approval == pytest.approx(0.9)
        assert players["A"].total == pytest.approx(1.1)

    def test_a_single_player_with_many_ballots_takes_the_whole_game(self):
        """F3b: two ballots skipped the ``n == 1`` short circuit, the surviving
        rejecting ballot clamped to zero, and one player kept half a game."""
        sv = compute_shapley_values([_vote("A", False, 0.5), _vote("A", False, 0.5)], THRESHOLD)

        assert sv == {"A": 1.0}

    def test_keys_are_bare_agent_ids(self):
        """Five consumers index the returned dict by a bare agent id, so
        per-ballot or composite keys are unavailable rather than merely awkward."""
        sv = compute_shapley_values(
            [_vote("A", True, 0.9), _vote("A", False, 0.2), _vote("B", True, 0.8)],
            THRESHOLD,
        )

        assert set(sv) == {"A", "B"}
        assert all(isinstance(key, str) for key in sv)


class TestConservation:
    def test_all_zero_confidence_with_duplicates_splits_the_whole_game(self):
        """F3: the equal-split fallback divided by the ballot count while
        iterating players, so three ballots over two players summed to 0.667."""
        votes = [_vote("A", True, 0.0), _vote("A", True, 0.0), _vote("B", True, 0.0)]

        sv = compute_shapley_values(votes, THRESHOLD)

        assert sv == pytest.approx({"A": 0.5, "B": 0.5})
        assert sum(sv.values()) == pytest.approx(1.0)

    @pytest.mark.parametrize(
        "votes",
        [
            pytest.param(
                [_vote("A", True), _vote("B", True), _vote("C", True)], id="distinct-unanimous",
            ),
            pytest.param(
                [_vote("A", True), _vote("B", True), _vote("C", False)], id="distinct-dissenter",
            ),
            pytest.param(
                [_vote("A", True, 0.9), _vote("A", False, 0.2), _vote("B", True)],
                id="duplicate-mixed",
            ),
            pytest.param(
                [_vote("A", False), _vote("A", False), _vote("B", False)],
                id="duplicate-all-reject",
            ),
            pytest.param(
                [_vote("A", True, 0.0), _vote("A", True, 0.0)], id="duplicate-zero-confidence",
            ),
            pytest.param(
                [_vote(f"a{i}", i % 3 != 0) for i in range(10)], id="ten-distinct-approximate",
            ),
            pytest.param(
                [_vote("A", True), _vote("A", True), _vote("A", True), _vote("B", False)],
                id="the-bf851-shape",
            ),
        ],
    )
    def test_values_never_exceed_one(self, votes):
        sv = compute_shapley_values(votes, THRESHOLD)

        assert sum(sv.values()) <= 1.0 + 1e-9
        assert all(value >= 0.0 for value in sv.values())

    def test_a_clamped_round_legitimately_sums_below_one(self):
        """D3: negative marginals are clamped, which drops mass on purpose.

        Guards against anyone "fixing" conservation to an unconditional 1.0 —
        that would fail on correct dissenter rounds and pin the wrong contract.
        """
        votes = [_vote("A", True, 1.0), _vote("B", True, 1.0), _vote("C", False, 1.0)]

        sv = compute_shapley_values(votes, THRESHOLD, use_confidence_weights=False)

        assert sv["C"] == 0.0
        assert sum(sv.values()) == pytest.approx(0.8)

    def test_equal_split_fallback_sums_to_exactly_one(self):
        with_duplicates = compute_shapley_values(
            [_vote("A", True, 0.0), _vote("A", True, 0.0), _vote("B", True, 0.0)], THRESHOLD,
        )
        without_duplicates = compute_shapley_values(
            [_vote("A", True, 0.0), _vote("B", True, 0.0)], THRESHOLD,
        )

        assert sum(with_duplicates.values()) == pytest.approx(1.0)
        assert sum(without_duplicates.values()) == pytest.approx(1.0)
        assert with_duplicates == pytest.approx(without_duplicates)


class TestGameSizeIsThePlayerCount:
    @staticmethod
    def _spy_paths(monkeypatch) -> list[str]:
        took: list[str] = []
        real_exact = shapley._exact_shapley
        real_approx = shapley._approximate_shapley

        def spy_exact(*a, **kw):
            took.append("exact")
            return real_exact(*a, **kw)

        def spy_approx(*a, **kw):
            took.append("approx")
            return real_approx(*a, **kw)

        monkeypatch.setattr(shapley, "_exact_shapley", spy_exact)
        monkeypatch.setattr(shapley, "_approximate_shapley", spy_approx)
        return took

    def test_ballot_count_above_the_bound_still_takes_the_exact_path(self, monkeypatch):
        """F4: ten ballots over two players selected Monte Carlo for a two-player
        game, paying sampling noise when the exact 0.5/0.5 was free."""
        took = self._spy_paths(monkeypatch)
        votes = [_vote("A", True) for _ in range(5)] + [_vote("B", True) for _ in range(5)]
        assert len(votes) > MAX_EXACT_SHAPLEY, "premise: the ballot count is above the bound"

        sv = shapley.compute_shapley_values(votes, THRESHOLD)

        assert took == ["exact"]
        assert sv == pytest.approx({"A": 0.5, "B": 0.5})

    def test_player_count_above_the_bound_takes_the_approximate_path(self, monkeypatch):
        took = self._spy_paths(monkeypatch)
        votes = [_vote(f"a{i}", True) for i in range(MAX_EXACT_SHAPLEY + 1)]

        sv = shapley.compute_shapley_values(votes, THRESHOLD)

        assert took == ["approx"]
        assert len(sv) == MAX_EXACT_SHAPLEY + 1
        assert sum(sv.values()) <= 1.0 + 1e-9

    def test_the_exact_path_stays_inside_the_bf850_budget_under_ballot_multiplicity(
        self, monkeypatch,
    ):
        """BF-850 is re-breakable by the obvious implementation.

        Flattening a player's ballots back into ``_evaluate_coalition`` is
        arithmetically identical but makes coalition evaluation O(ballots):
        measured at this shape, 3.23 s against 0.06 s for the weight-pair form.
        """
        took = self._spy_paths(monkeypatch)
        votes = [
            _vote(f"p{i}", True)
            for i in range(MAX_EXACT_SHAPLEY)
            for _ in range(25)
        ]

        start = time.monotonic()
        sv = shapley.compute_shapley_values(votes, THRESHOLD)
        elapsed = time.monotonic() - start

        assert took == ["exact"], "premise: the exact path is what is being timed"
        assert len(sv) == MAX_EXACT_SHAPLEY
        assert elapsed < 0.5, f"exact path took {elapsed:.2f}s with 25 ballots per player"


class TestGrandCoalitionAgreesWithTheVote:
    def test_the_grand_coalition_matches_the_quorum_engines_own_verdict(self):
        """The defect at its sharpest: Shapley solved a different game.

        ``QuorumEngine.evaluate`` tallies every ballot, then hands the same votes
        to Shapley. On ``[A ok, A ok, A ok, B fail]`` the engine approved while
        the coalition HEAD enumerated — A's one surviving ballot plus B — failed.
        """
        engine = QuorumEngine(QuorumPolicy())
        results = [
            IntentResult(intent_id="i1", agent_id=a, success=ok, result="x", confidence=0.9)
            for a, ok in (("A", True), ("A", True), ("A", True), ("B", False))
        ]

        consensus = engine.evaluate(results)

        assert consensus.outcome is ConsensusOutcome.APPROVED, (
            "premise: the engine must pass this round for the contradiction to exist"
        )
        players = _summarise_players(consensus.votes, True)
        grand = _PlayerWeight(
            sum(p.approval for p in players.values()),
            sum(p.total for p in players.values()),
        )
        assert _clears_threshold(grand.approval, grand.total, THRESHOLD) is True, (
            "the grand coalition must pass the vote the engine passed"
        )


class TestDistinctIdParity:
    def test_distinct_ids_are_unaffected(self):
        """Re-pins what ``test_shapley.py`` relies on. Verified bit-exact against
        HEAD over 18,000 distinct-id configurations before this test was written.
        """
        unanimous = compute_shapley_values(
            [_vote("a1", True, 0.9), _vote("a2", True, 0.9), _vote("a3", True, 0.9)],
            0.6,
        )
        dissenter = compute_shapley_values(
            [_vote("a1", True, 1.0), _vote("a2", True, 1.0), _vote("a3", False, 1.0)],
            0.6,
            use_confidence_weights=False,
        )

        assert unanimous == pytest.approx({"a1": 1 / 3, "a2": 1 / 3, "a3": 1 / 3})
        assert dissenter["a3"] == 0.0
        assert compute_shapley_values([_vote("a1", True, 0.9)], 0.6) == {"a1": 1.0}
        assert compute_shapley_values([], 0.6) == {}

    def test_composite_participant_keys_are_unaffected(self):
        """The AD-1130 shape: distinct-by-construction composite keys."""
        votes = [
            _vote("child:w1", True, 0.9),
            _vote("child:w2", True, 0.9),
            _vote("facilitator:s1", True, 0.9),
        ]

        sv = compute_shapley_values(votes, THRESHOLD)

        assert set(sv) == {"child:w1", "child:w2", "facilitator:s1"}
        assert sum(sv.values()) == pytest.approx(1.0)


class TestConsumerContracts:
    def test_result_survives_the_episodic_json_round_trip(self):
        """``episodic.py`` persists via ``json.dumps`` and reads back with
        ``json.loads``, which requires str keys and float values."""
        sv = compute_shapley_values(
            [_vote("A", True, 0.9), _vote("A", False, 0.2), _vote("B", True, 0.8)],
            THRESHOLD,
        )

        assert json.loads(json.dumps(sv)) == sv

    def test_a_bare_agent_id_lookup_resolves(self):
        """The ``panels.py`` / ``runtime.py`` access shape: ``sv.get(agent.id)``."""
        sv = compute_shapley_values(
            [_vote("A", True, 0.9), _vote("A", True, 0.9), _vote("B", True, 0.8)],
            THRESHOLD,
        )

        assert sv.get("A") is not None
        assert sv.get("B") is not None


class _FakeVerifier:
    """Minimal stand-in for a RedTeamAgent on the verification path."""

    def __init__(self, verifier_id: str) -> None:
        self.id = verifier_id

    async def verify(
        self, target_agent_id: str, intent: Any, claimed_result: Any,
    ) -> VerificationResult:
        return VerificationResult(
            verifier_id=self.id,
            target_agent_id=target_agent_id,
            intent_id=intent.id,
            verified=True,
            confidence=0.9,
        )


class TestSpendSeam:
    """Crosses quorum -> verify -> combine -> trust in one test.

    Each half of that chain is covered elsewhere; a test for each half passing
    is the signature of a dead chain, so this one traverses the whole of it.
    """

    @pytest.mark.asyncio
    async def test_one_spend_per_distinct_agent_survives_the_merge(self, tmp_path):
        runtime = ProbOSRuntime(data_dir=tmp_path / "data")
        await runtime.start()

        results = [
            IntentResult(intent_id="", agent_id=a, success=True, result="p", confidence=0.9)
            for a in ("A", "A", "A", "B")
        ]
        calls: list[dict[str, Any]] = []
        original_record = runtime.trust_network.record_outcome
        original_broadcast = runtime.intent_bus.broadcast
        original_verifiers = runtime.red_team_agents

        def _recorder(agent_id: str, **kwargs: Any) -> float:
            calls.append({"agent_id": agent_id, **kwargs})
            return original_record(agent_id, **kwargs)

        async def _broadcast(msg: Any, timeout: float | None = None) -> list[IntentResult]:
            for r in results:
                r.intent_id = msg.id
            return results

        runtime.trust_network.record_outcome = _recorder  # type: ignore[method-assign]
        runtime.red_team_agents = [_FakeVerifier("rt1")]  # type: ignore[assignment]
        runtime.intent_bus.broadcast = _broadcast  # type: ignore[method-assign]
        try:
            out = await runtime.submit_intent_with_consensus(
                "read_file", params={"path": "/tmp/x"}, timeout=1.0,
            )
        finally:
            runtime.trust_network.record_outcome = original_record  # type: ignore[method-assign]
            runtime.intent_bus.broadcast = original_broadcast  # type: ignore[method-assign]
            runtime.red_team_agents = original_verifiers  # type: ignore[assignment]
            await runtime.stop()

        episode_id = out["intent"].id
        mine = [c for c in calls if c.get("episode_id") == episode_id]
        sv = out["consensus"].shapley_values or {}
        verified = {r.agent_id for r in results if r.success}

        assert sv, "premise: this shape must produce a non-empty attribution"
        assert len(mine) == 2, "one update per agent, not one per ballot"
        assert {c["agent_id"] for c in mine} == {"A", "B"}
        assert sum(c["weight"] for c in mine) == pytest.approx(
            sum(sv[a] for a in verified), abs=1e-9,
        )


class TestMalformedConfidenceIsTotal:
    """The round-1 adversarial review finding.

    Making every ballot count is exactly what stopped last-write-wins from
    swallowing a malformed one, so the BF-837 fix is what exposed this boundary.
    ``Vote.confidence`` is producer-supplied and unvalidated.
    """

    @pytest.mark.parametrize(
        "junk", [None, float("nan"), float("inf"), float("-inf"), -1.0, "0.9", True],
    )
    def test_an_unweighable_ballot_neither_raises_nor_loses_mass(self, junk):
        # Measured before the repair: None raised TypeError straight out of the
        # sum and aborted the round; NaN and inf normalised to sum 0.500000.
        votes = [
            _vote("A", True, junk),
            _vote("A", True, 0.9),
            _vote("B", True, 0.9),
        ]

        values = compute_shapley_values(votes, 0.6)

        assert set(values) == {"A", "B"}, (
            f"a confidence of {junk!r} must not drop a player from the "
            "attribution -- runtime.py skips the trust update for a missing key"
        )
        assert sum(values.values()) == pytest.approx(1.0, abs=1e-9), (
            f"a confidence of {junk!r} lost attributable mass"
        )
        # Both of A's ballots approve, so a player degraded to UNWEIGHTED still
        # clears the threshold and earns a share. Mutation caught that the two
        # assertions above hold just as well if the player is ZEROED instead --
        # it keeps its key and the normalisation still sums to 1.0. Degrading
        # rather than dropping only means anything if the player still counts.
        assert values["A"] > 0.0, (
            f"a confidence of {junk!r} silently zeroed the player instead of "
            "weighing its ballots unweighted"
        )
        assert values["A"] == pytest.approx(values["B"], abs=1e-9), (
            "two unanimous approvers, one degraded, must split the game evenly"
        )

    def test_the_degrade_is_scoped_to_the_player_not_the_round(self):
        """One agent's broken metadata must not discard everyone's weighting.

        B and C are cleanly weighted and differ from each other only in
        confidence, so if the whole round degraded to unweighted they would come
        out equal. They must not.
        """
        votes = [
            _vote("A", True, None),
            _vote("A", True, 0.9),
            _vote("B", True, 0.9),
            _vote("C", False, 0.1),
        ]

        values = compute_shapley_values(votes, 0.6)

        assert set(values) == {"A", "B", "C"}
        assert values["B"] != pytest.approx(values["C"], abs=1e-9), (
            "B and C differ only in confidence; equal values mean A's bad "
            "metadata degraded the whole round rather than just A"
        )

    def test_a_lone_unweighable_ballot_is_also_survivable(self):
        # Not a duplicate: this shape raised at HEAD too, so it is a repair
        # rather than a regression introduced by BF-837.
        values = compute_shapley_values(
            [_vote("A", True, None), _vote("B", True, 0.9)], 0.6,
        )

        assert set(values) == {"A", "B"}
        assert sum(values.values()) == pytest.approx(1.0, abs=1e-9)
        assert values["A"] > 0.0, (
            "the degraded player must still count, not be zeroed"
        )

    def test_well_formed_confidence_is_untouched(self):
        # Oracle, not a self-comparison: an all-distinct fixture, so the 18,000
        # config parity sweep makes HEAD's own output the expected value. Sums
        # to 0.875 rather than 1.0 because C's negative marginal is clamped --
        # asserting 1.0 here would pin the wrong contract.
        clean = [_vote("A", True, 0.9), _vote("B", True, 0.3), _vote("C", False, 0.5)]

        values = compute_shapley_values(clean, 0.6)

        assert values == pytest.approx({"A": 0.625, "B": 0.25, "C": 0.0}, abs=1e-9)
        assert sum(values.values()) == pytest.approx(0.875, abs=1e-9)

    def test_the_player_wide_degrade_is_deliberate_and_can_change_a_verdict(self):
        """Round 2 asked whether one junk ballot should reweigh an agent's good
        ones. It should, and this pins the drift rather than leaving it implicit.

        Per-BALLOT degrade was rejected: substituting 1.0 for the junk ballot
        alone would make a broken metadata field the LOUDEST vote in a set whose
        real confidences are 0.2-0.9. Confidence is per-agent metadata, so an
        agent that reports one unusable value has its confidence reporting
        treated as unreliable for that round -- the same rule
        ``verification.combine_verdicts`` applies to its own set.

        A is identical in both fixtures apart from one extra junk ballot:
          weighted   0.9 / 1.3 = 0.692 >= 0.6  -> A approves, equal three-way split
          unweighted 2   / 4   = 0.500 <  0.6  -> A rejects, and earns nothing
        """
        base = [
            _vote("A", True, 0.9), _vote("A", False, 0.2), _vote("A", False, 0.2),
            _vote("B", True, 0.9), _vote("C", True, 0.9),
        ]
        with_junk = [*base[:3], _vote("A", True, None), *base[3:]]

        clean_values = compute_shapley_values(base, 0.6)
        junk_values = compute_shapley_values(with_junk, 0.6)

        assert clean_values["A"] == pytest.approx(1 / 3, abs=1e-9), (
            "premise: weighted, A's 0.9 approval outvotes its two 0.2 rejections"
        )
        assert junk_values["A"] == pytest.approx(0.0, abs=1e-9), (
            "unweighted, A is 2 of 4 and does not clear 0.6"
        )
        assert set(junk_values) == {"A", "B", "C"}, "A keeps its key, it just earns 0"
        assert junk_values["B"] == pytest.approx(junk_values["C"], abs=1e-9)
        assert sum(junk_values.values()) == pytest.approx(0.8, abs=1e-9), (
            "A's clamped marginal legitimately leaves mass unattributed"
        )

    def test_one_definition_of_usable_confidence(self):
        """DRY: ``verification`` must not carry a second copy that can drift."""
        from probos.consensus import verification

        assert verification.usable_confidence is usable_confidence
        assert not hasattr(verification, "_usable_weight"), (
            "the duplicate sanitiser must be gone, not merely unused"
        )

