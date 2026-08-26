"""AD-1272 / BF-851 — trust accrues per unit of work, verdicts combine first.

Two layers:

* ``combine_verdicts`` unit tests — the new rule in
  ``probos.consensus.verification``.
* Spend-conservation integration tests that drive the real
  ``submit_intent_with_consensus`` path with a crafted result set and fake
  verifiers, so the whole chain (quorum evaluate -> verify fan-out -> combine ->
  one trust update) is crossed rather than each half tested alone.

Conservation is asserted on the **weights passed to** ``record_outcome``, never
on alpha/beta deltas: ``effective_weight = outcome.weight * dampening_factor``
and the AD-558 hard-floor branch applies zero, so a delta assertion would pin
those behaviours by accident.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from probos.consensus.verification import combine_verdicts
from probos.mesh.routing import REL_AGENT
from probos.runtime import ProbOSRuntime
from probos.types import (
    ConsensusOutcome,
    ConsensusResult,
    IntentResult,
    QuorumPolicy,
    VerificationResult,
)

THRESHOLD = QuorumPolicy().approval_threshold  # 0.6


def _verdict(
    verifier_id: str,
    verified: bool,
    confidence: float = 0.9,
    target: str = "target",
) -> VerificationResult:
    return VerificationResult(
        verifier_id=verifier_id,
        target_agent_id=target,
        intent_id="intent-1",
        verified=verified,
        confidence=confidence,
    )


class TestCombineVerdicts:
    def test_empty_verdicts_returns_none(self):
        assert combine_verdicts([], approval_threshold=THRESHOLD) is None

    def test_single_verdict_passes_through_unchanged(self):
        approve = combine_verdicts([_verdict("rt1", True)], approval_threshold=THRESHOLD)
        reject = combine_verdicts([_verdict("rt1", False)], approval_threshold=THRESHOLD)

        assert approve == (True, ("rt1",))
        assert reject == (False, ("rt1",))

    def test_unanimous_verdicts_carry_their_shared_outcome(self):
        approve = combine_verdicts(
            [_verdict("rt1", True), _verdict("rt2", True)],
            approval_threshold=THRESHOLD,
        )
        reject = combine_verdicts(
            [_verdict("rt1", False), _verdict("rt2", False)],
            approval_threshold=THRESHOLD,
        )

        assert approve == (True, ("rt1", "rt2"))
        assert reject == (False, ("rt1", "rt2"))

    def test_split_verdict_resolves_toward_higher_confidence_side(self):
        # 0.9 approve vs 0.1 reject -> 0.9 approval share, clears 0.6.
        verified, _ = combine_verdicts(
            [_verdict("rt1", True, 0.9), _verdict("rt2", False, 0.1)],
            approval_threshold=THRESHOLD,
        )

        assert verified is True

    def test_confidence_outweighs_a_numerically_larger_low_confidence_side(self):
        # Two 0.1-confidence approvals (a RedTeamAgent benefit-of-the-doubt
        # shrug) against one considered 0.9 rejection: majority would approve,
        # confidence weighting must not. Approval share = 0.2/1.1 = 0.18.
        verdicts = [
            _verdict("rt1", True, 0.1),
            _verdict("rt2", True, 0.1),
            _verdict("rt3", False, 0.9),
        ]

        weighted, _ = combine_verdicts(verdicts, approval_threshold=THRESHOLD)
        unweighted, _ = combine_verdicts(
            verdicts, approval_threshold=THRESHOLD, use_confidence_weights=False,
        )

        assert weighted is False
        assert unweighted is True, "premise: plain majority would have approved"

    def test_all_zero_confidence_falls_back_to_unweighted_majority(self):
        # A verifier metadata gap must not read as "failed verification" —
        # that would be a trust penalty for a missing field.
        verified, ids = combine_verdicts(
            [_verdict("rt1", True, 0.0), _verdict("rt2", True, 0.0)],
            approval_threshold=THRESHOLD,
        )

        assert verified is True
        assert ids == ("rt1", "rt2")

    def test_weights_disabled_uses_unweighted_majority(self):
        # 1 of 3 approve = 0.33 < 0.6, despite the approver's confidence lead.
        verified, _ = combine_verdicts(
            [
                _verdict("rt1", True, 0.9),
                _verdict("rt2", False, 0.1),
                _verdict("rt3", False, 0.1),
            ],
            approval_threshold=THRESHOLD,
            use_confidence_weights=False,
        )

        assert verified is False

    def test_exactly_at_threshold_approves(self):
        # 0.6 approve / 1.0 total == 0.6; ">=" matches shapley._evaluate_coalition.
        verified, _ = combine_verdicts(
            [_verdict("rt1", True, 0.6), _verdict("rt2", False, 0.4)],
            approval_threshold=THRESHOLD,
        )

        assert verified is True

    def test_verifier_ids_are_sorted_and_deduplicated(self):
        # The cross product gives one verifier several verdicts for one target
        # when that target produced several result rows.
        _, ids = combine_verdicts(
            [
                _verdict("rt-z", True),
                _verdict("rt-a", True),
                _verdict("rt-z", True),
                _verdict("rt-m", True),
            ],
            approval_threshold=THRESHOLD,
        )

        assert ids == ("rt-a", "rt-m", "rt-z")

    # ── round-1 review repairs ───────────────────────────────────────────

    @pytest.mark.parametrize(
        "junk",
        [None, float("nan"), float("inf"), float("-inf"), -5.0, "0.9", True],
    )
    def test_an_unweighable_confidence_degrades_the_whole_set(self, junk):
        """Confidence is producer-supplied and ``VerificationResult`` does not
        validate it.

        Review measured two failures: ``None`` raised ``TypeError`` straight out
        of the sum and aborted the round, and one ``NaN`` slipped past the
        ``<= 0`` guard and turned two APPROVALS into a rejection -- a trust
        penalty produced by a metadata gap. Both verdicts approve here, so a
        result of anything but ``True`` means the gap was scored as a failure.
        """
        verdicts = [_verdict("rt1", True, 0.9), _verdict("rt2", True, junk)]

        combined = combine_verdicts(verdicts, approval_threshold=THRESHOLD)

        assert combined is not None
        verified, ids = combined
        assert verified is True, (
            f"a confidence of {junk!r} must degrade to unweighted majority, "
            "not score two approvals as a failed verification"
        )
        assert ids == ("rt1", "rt2")

    def test_a_malformed_verdict_does_not_disenfranchise_its_verifier(self):
        """Degrading the whole set is deliberate, not incidental.

        Dropping only the malformed verdict would be a quieter version of the
        same defect: a verifier whose metadata is broken still returned a
        judgement. Two rejections and one high-confidence approval must reject
        under unweighted majority, even though the approval carries all the
        usable weight.
        """
        verdicts = [
            _verdict("rt1", True, 0.9),
            _verdict("rt2", False, None),
            _verdict("rt3", False, None),
        ]

        verified, _ = combine_verdicts(verdicts, approval_threshold=THRESHOLD)

        assert verified is False, (
            "the two malformed rejections must still count; 1 of 3 = 0.33 < 0.6"
        )

    def test_a_true_confidence_is_not_silently_worth_one(self):
        # bool is a subclass of int, so an unguarded float() would weigh a
        # verdict marked ``True`` as 1.0 rather than treating it as malformed.
        weighted, _ = combine_verdicts(
            [_verdict("rt1", False, 0.9), _verdict("rt2", True, True)],
            approval_threshold=THRESHOLD,
        )

        assert weighted is False, (
            "True as a confidence is malformed metadata, not a weight of 1.0"
        )


class _FakeVerifier:
    """Stands in for a RedTeamAgent on the consensus verification path."""

    def __init__(
        self,
        verifier_id: str,
        *,
        verdict: bool = True,
        confidence: float = 0.9,
        raises: bool = False,
        hangs: bool = False,
    ) -> None:
        self.id = verifier_id
        self._verdict = verdict
        self._confidence = confidence
        self._raises = raises
        self._hangs = hangs
        self.lies_about_target: str | None = None
        self.calls: list[str] = []

    async def verify(
        self, target_agent_id: str, intent: Any, claimed_result: Any,
    ) -> VerificationResult:
        self.calls.append(target_agent_id)
        if self._hangs:
            await asyncio.sleep(30)
        if self._raises:
            raise RuntimeError("verifier exploded")
        return VerificationResult(
            verifier_id=self.id,
            target_agent_id=self.lies_about_target or target_agent_id,
            intent_id=intent.id,
            verified=self._verdict,
            confidence=self._confidence,
        )


def _result(agent_id: str, success: bool = True, confidence: float = 0.9) -> IntentResult:
    return IntentResult(
        intent_id="",
        agent_id=agent_id,
        success=success,
        result="payload",
        confidence=confidence,
    )


async def _run_round(
    runtime: ProbOSRuntime,
    results: list[IntentResult],
    verifiers: list[_FakeVerifier],
    *,
    trust_side_effect: Exception | None = None,
    consensus_override: ConsensusResult | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Drive one real consensus round over a crafted result set.

    Every patched attribute is restored before returning — a fake verifier left
    on the runtime breaks the shutdown sweep, which then leaks the Yeoman
    singleton into the next test.

    Returns the round output and the ``record_outcome`` calls it made, filtered
    to this round's episode so an unrelated background writer cannot inflate it.
    """
    calls: list[dict[str, Any]] = []
    original_record = runtime.trust_network.record_outcome
    original_broadcast = runtime.intent_bus.broadcast
    original_verifiers = runtime.red_team_agents
    original_evaluate = runtime.quorum_engine.evaluate

    def _recorder(agent_id: str, **kwargs: Any) -> float:
        calls.append({"agent_id": agent_id, **kwargs})
        if trust_side_effect is not None:
            raise trust_side_effect
        return original_record(agent_id, **kwargs)

    async def _broadcast(msg: Any, timeout: float | None = None) -> list[IntentResult]:
        for r in results:
            r.intent_id = msg.id
        return results

    runtime.trust_network.record_outcome = _recorder  # type: ignore[method-assign]
    runtime.red_team_agents = verifiers  # type: ignore[assignment]
    runtime.intent_bus.broadcast = _broadcast  # type: ignore[method-assign]
    if consensus_override is not None:
        runtime.quorum_engine.evaluate = (  # type: ignore[method-assign]
            lambda *a, **k: consensus_override
        )
    try:
        out = await runtime.submit_intent_with_consensus(
            "read_file", params={"path": "/tmp/x"}, timeout=1.0,
        )
    finally:
        runtime.trust_network.record_outcome = original_record  # type: ignore[method-assign]
        runtime.intent_bus.broadcast = original_broadcast  # type: ignore[method-assign]
        runtime.red_team_agents = original_verifiers  # type: ignore[assignment]
        runtime.quorum_engine.evaluate = original_evaluate  # type: ignore[method-assign]

    episode_id = out["intent"].id
    return out, [c for c in calls if c.get("episode_id") == episode_id]


def _crafted_consensus(shapley_values: dict[str, float]) -> ConsensusResult:
    consensus = ConsensusResult(
        proposal_id="p1",
        outcome=ConsensusOutcome.APPROVED,
        votes=[],
        weighted_approval=1.0,
        total_weight=1.0,
    )
    consensus.shapley_values = shapley_values
    return consensus


def _assert_spend_conserved(
    out: dict[str, Any], calls: list[dict[str, Any]], results: list[IntentResult],
) -> tuple[float, float]:
    """The AD-1272 conservation assertion.

    Total weight spent equals the sum of Shapley values over *verified* agents —
    the denominator is computed from the round, never hard-coded, because a
    mixed-verdict round has an attributable total below 1.0.
    """
    consensus = out["consensus"]
    verified_agents = {r.agent_id for r in results if r.success}
    shapley = consensus.shapley_values or {}

    assert shapley, "premise: this shape must produce a non-empty attribution"
    assert not (verified_agents - shapley.keys()), (
        "premise: every verified agent must be attributed"
    )

    available = sum(shapley[a] for a in verified_agents)
    spent = sum(c["weight"] for c in calls)

    assert spent == pytest.approx(available, abs=1e-9)
    assert len(calls) == len(verified_agents)
    assert {c["agent_id"] for c in calls} == verified_agents
    return spent, available


@pytest.fixture
async def runtime(tmp_path):
    rt = ProbOSRuntime(data_dir=tmp_path / "data")
    await rt.start()
    yield rt
    await rt.stop()


class TestSpendConservation:
    @pytest.mark.asyncio
    async def test_duplicate_agent_one_verifier_spends_once_per_agent(self, runtime):
        results = [_result("A"), _result("A"), _result("A"), _result("B")]

        out, calls = await _run_round(runtime, results, [_FakeVerifier("rt1")])

        _assert_spend_conserved(out, calls, results)
        assert len(calls) == 2, "one update per agent, not one per result row"
        assert len(out["verifications"]) == 4, "premise: 4 verdicts were produced"

    @pytest.mark.asyncio
    async def test_duplicate_agent_two_verifiers_spends_once_per_agent(self, runtime):
        results = [_result("A"), _result("A"), _result("A"), _result("B")]
        verifiers = [_FakeVerifier("rt1"), _FakeVerifier("rt2")]

        out, calls = await _run_round(runtime, results, verifiers)

        _assert_spend_conserved(out, calls, results)
        assert len(calls) == 2, "stock 2-verifier config must not double the spend"
        assert len(out["verifications"]) == 8, "premise: the cross product ran 8 times"

    @pytest.mark.asyncio
    async def test_three_distinct_agents_two_verifiers_spend_three_times(self, runtime):
        results = [_result("A"), _result("B"), _result("C")]
        verifiers = [_FakeVerifier("rt1"), _FakeVerifier("rt2")]

        out, calls = await _run_round(runtime, results, verifiers)

        _assert_spend_conserved(out, calls, results)
        assert len(calls) == 3
        assert len(out["verifications"]) == 6

    @pytest.mark.asyncio
    async def test_mixed_verdict_denominator_is_below_one(self, runtime):
        results = [_result("A"), _result("A"), _result("A"), _result("B", success=False)]
        verifiers = [_FakeVerifier("rt1"), _FakeVerifier("rt2")]

        out, calls = await _run_round(runtime, results, verifiers)

        spent, available = _assert_spend_conserved(out, calls, results)
        assert available < 1.0, (
            "premise: a mixed-verdict round clamps negative marginals, so hard-"
            "coding 1.0 would pass only on all-approve rounds"
        )
        assert spent == pytest.approx(available, abs=1e-9)
        assert {c["agent_id"] for c in calls} == {"A"}

    @pytest.mark.asyncio
    async def test_nine_agents_monte_carlo_spend_is_conserved(self, runtime):
        # n=9 is above MAX_EXACT_SHAPLEY, so values are sampled and vary between
        # evaluations. Assert conservation and per-agent equality, never values.
        results = [_result(f"A{i}") for i in range(9)]
        verifiers = [_FakeVerifier("rt1"), _FakeVerifier("rt2")]

        out, calls = await _run_round(runtime, results, verifiers)

        _assert_spend_conserved(out, calls, results)
        shapley = out["consensus"].shapley_values
        for call in calls:
            assert call["weight"] == pytest.approx(shapley[call["agent_id"]], abs=1e-12)

    @pytest.mark.asyncio
    async def test_sub_floor_shapley_value_is_spent_as_computed(self, runtime):
        # The old ``max(value, 0.1)`` floor is gone. Under the exact path no
        # successful agent falls below 0.1, so the attribution is set directly
        # to make the removal deterministic rather than dependent on Monte
        # Carlo noise.
        results = [_result("A"), _result("B"), _result("C")]

        _, calls = await _run_round(
            runtime,
            results,
            [_FakeVerifier("rt1")],
            consensus_override=_crafted_consensus({"A": 0.04, "B": 0.06, "C": 0.90}),
        )

        weights = {c["agent_id"]: c["weight"] for c in calls}
        assert weights == pytest.approx({"A": 0.04, "B": 0.06, "C": 0.90})
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)

    @pytest.mark.asyncio
    async def test_empty_shapley_keeps_the_unit_weight_branch(self, runtime):
        # Fewer results than ``min_votes`` -> INSUFFICIENT -> no attribution.
        results = [_result("A"), _result("B")]

        out, calls = await _run_round(runtime, results, [_FakeVerifier("rt1")])

        assert out["consensus"].outcome == ConsensusOutcome.INSUFFICIENT
        assert not out["consensus"].shapley_values, "premise: attribution is empty"
        assert {c["agent_id"] for c in calls} == {"A", "B"}
        assert [c["weight"] for c in calls] == [1.0, 1.0]

    @pytest.mark.asyncio
    async def test_agent_absent_from_attribution_is_skipped_with_a_warning(
        self, runtime, caplog,
    ):
        results = [_result("A"), _result("B"), _result("C")]

        with caplog.at_level("WARNING", logger="probos.runtime"):
            _, calls = await _run_round(
                runtime,
                results,
                [_FakeVerifier("rt1")],
                # C is attributed nowhere.
                consensus_override=_crafted_consensus({"A": 0.5, "B": 0.5}),
            )

        assert {c["agent_id"] for c in calls} == {"A", "B"}
        assert all(c["weight"] != 0.1 for c in calls), "no fabricated floor weight"
        assert "AD-1272" in caplog.text
        assert "C" in caplog.text


class TestVerificationSurfacePreserved:
    @pytest.mark.asyncio
    async def test_trust_write_in_progress_preserves_verifications_hebbian_events(
        self, runtime, caplog,
    ):
        # Mirrors tests/test_consensus_integration.py::
        # test_busy_trust_preserves_verification_hebbian_and_event — with one
        # combined call the degrade is all-or-nothing per agent, and everything
        # outside trust must still land.
        results = [_result("A"), _result("B"), _result("C")]
        verifiers = [_FakeVerifier("rt1"), _FakeVerifier("rt2")]

        with caplog.at_level("WARNING", logger="probos.runtime"):
            out, calls = await _run_round(
                runtime,
                results,
                verifiers,
                trust_side_effect=RuntimeError("trust_write_in_progress"),
            )

        assert len(out["verifications"]) == 6
        typed = runtime.hebbian_router.all_weights_typed()
        assert any(key[2] == REL_AGENT for key in typed)
        events = await runtime.event_log.query(category="consensus")
        assert sum(1 for e in events if e["event"] == "verification_complete") == 6
        assert "AD-1130" in caplog.text
        assert "rt1,rt2" in caplog.text, "the warning names the combined verifier set"
        assert len(calls) == 3, "one attempted update per agent, not per verdict"

    @pytest.mark.asyncio
    async def test_collapse_is_only_in_the_trust_dimension(self, runtime):
        results = [_result("A"), _result("B"), _result("C")]
        verifiers = [_FakeVerifier("rt1"), _FakeVerifier("rt2")]
        assert runtime.bridge_alerts is not None, "premise: AD-410 path is wired"
        alert_targets: list[str] = []
        original_check = runtime.bridge_alerts.check_trust_change

        def _spy(agent_id: str, old: float, new: float):
            alert_targets.append(agent_id)
            return original_check(agent_id, old, new)

        runtime.bridge_alerts.check_trust_change = _spy  # type: ignore[method-assign]
        try:
            out, calls = await _run_round(runtime, results, verifiers)
        finally:
            runtime.bridge_alerts.check_trust_change = original_check  # type: ignore[method-assign]

        # Per-verifier list, per-verification events, per-pair Hebbian edges all
        # stay at N; only the trust update collapses.
        assert len(out["verifications"]) == 6
        events = await runtime.event_log.query(category="consensus")
        assert sum(1 for e in events if e["event"] == "verification_complete") == 6
        typed = runtime.hebbian_router.all_weights_typed()
        pairs = {
            (key[0], key[1]) for key in typed
            if key[2] == REL_AGENT and key[0] in {"rt1", "rt2"}
        }
        assert pairs == {
            (v, t) for v in ("rt1", "rt2") for t in ("A", "B", "C")
        }
        assert len(calls) == 3
        assert sorted(alert_targets) == ["A", "B", "C"], (
            "AD-410 check runs once per agent, not once per verdict"
        )

    @pytest.mark.asyncio
    async def test_verification_count_event_reports_verifications_not_updates(
        self, runtime,
    ):
        results = [_result("A"), _result("B"), _result("C")]
        verifiers = [_FakeVerifier("rt1"), _FakeVerifier("rt2")]

        _, calls = await _run_round(runtime, results, verifiers)

        events = await runtime.event_log.query(category="mesh")
        resolved = [e for e in events if e["event"] == "intent_resolved"]
        assert resolved, "premise: the round logged intent_resolved"
        assert resolved[-1]["data"]["verification_count"] == 6
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_one_verifier_timing_out_still_yields_one_combined_update(
        self, runtime,
    ):
        runtime.config.consensus.verification_timeout_seconds = 0.05
        results = [_result("A"), _result("B"), _result("C")]
        verifiers = [_FakeVerifier("rt1"), _FakeVerifier("rt2", hangs=True)]

        out, calls = await _run_round(runtime, results, verifiers)

        assert len(out["verifications"]) == 3, "only the live verifier contributed"
        assert len(calls) == 3
        assert all(c["verifier_id"] == "rt1" for c in calls)

    @pytest.mark.asyncio
    async def test_agent_with_no_surviving_verdict_gets_no_trust_update(self, runtime):
        results = [_result("A"), _result("B"), _result("C")]
        verifiers = [_FakeVerifier("rt1", raises=True)]

        out, calls = await _run_round(runtime, results, verifiers)

        assert out["verifications"] == []
        assert calls == []

    @pytest.mark.asyncio
    async def test_combined_verifier_id_is_the_sorted_join(self, runtime):
        results = [_result("A"), _result("B"), _result("C")]
        # Reverse-alphabetical registration order, so a sorted join is not the
        # same as arrival order.
        verifiers = [_FakeVerifier("rt-z"), _FakeVerifier("rt-a")]

        _, many = await _run_round(runtime, results, verifiers)
        assert {c["verifier_id"] for c in many} == {"rt-a,rt-z"}

        _, single = await _run_round(runtime, results, [_FakeVerifier("rt-solo")])
        assert {c["verifier_id"] for c in single} == {"rt-solo"}, (
            "one verifier stays byte-identical to the pre-AD-1272 value"
        )


class TestTrustFollowsTheRoundNotTheVerifier:
    """The two High findings from round-1 adversarial review."""

    @pytest.mark.asyncio
    async def test_a_verifier_naming_a_stranger_writes_no_trust(
        self, runtime, caplog,
    ):
        """The pre-AD-1272 loop keyed trust on ``result.agent_id``. Grouping by
        ``vr.target_agent_id`` routed that identity through a third-party
        verifier.

        Review measured the consequence on the empty-Shapley branch, where the
        attribution lookup cannot catch it: trust was written to a
        non-participant with weight 1.0 and no warning. Wrong signal is worse
        than no signal.
        """
        results = [_result("A"), _result("B")]  # 2 < min_votes -> INSUFFICIENT
        liar = _FakeVerifier("rt1")
        liar.lies_about_target = "WRONG"  # type: ignore[attr-defined]

        with caplog.at_level("WARNING", logger="probos.runtime"):
            out, calls = await _run_round(runtime, results, [liar])

        assert out["consensus"].outcome == ConsensusOutcome.INSUFFICIENT
        assert not out["consensus"].shapley_values, (
            "premise: the attribution must be EMPTY, or the existing lookup "
            "would catch this and the test proves nothing about this branch"
        )
        assert len(out["verifications"]) == 2, (
            "premise: the verdicts were produced and did name the stranger"
        )
        assert {v.target_agent_id for v in out["verifications"]} == {"WRONG"}

        assert calls == [], "a stranger must not accrue trust"
        assert "AD-1272" in caplog.text
        assert "WRONG" in caplog.text

    @pytest.mark.asyncio
    async def test_one_malformed_verdict_does_not_abort_the_round(
        self, runtime,
    ):
        """``combine_verdicts`` reads producer-supplied confidence.

        Review measured ``TypeError`` escaping ``submit_intent_with_consensus``
        entirely when it was called from outside the per-agent boundary, losing
        every remaining agent's update along with the round.
        """
        results = [_result("A"), _result("B"), _result("C")]
        verifiers = [_FakeVerifier("rt1"), _FakeVerifier("rt2", confidence=None)]

        out, calls = await _run_round(runtime, results, verifiers)

        assert len(out["verifications"]) == 6, "premise: every verdict landed"
        assert any(v.confidence is None for v in out["verifications"]), (
            "premise: a malformed confidence must actually reach the combinator"
        )
        assert {c["agent_id"] for c in calls} == {"A", "B", "C"}, (
            "the round survived and every agent still got its one update"
        )
        _assert_spend_conserved(out, calls, results)

    @pytest.mark.asyncio
    async def test_a_raising_combinator_costs_one_agent_not_the_round(
        self, runtime, monkeypatch, caplog,
    ):
        """Pins the PLACEMENT, not just the totality of ``combine_verdicts``.

        ``_usable_weight`` means the combinator no longer raises on the shapes
        review found, so nothing else here would notice if the call drifted back
        outside the per-agent ``try``. This forces it to raise for exactly one
        target and requires the other two to be unaffected.
        """
        import probos.runtime as runtime_module

        real = runtime_module.combine_verdicts

        def _explode_for_b(verdicts, **kwargs):
            if verdicts and verdicts[0].target_agent_id == "B":
                raise ValueError("combinator defect")
            return real(verdicts, **kwargs)

        monkeypatch.setattr(runtime_module, "combine_verdicts", _explode_for_b)

        results = [_result("A"), _result("B"), _result("C")]

        with caplog.at_level("WARNING", logger="probos.runtime"):
            out, calls = await _run_round(runtime, results, [_FakeVerifier("rt1")])

        assert len(out["verifications"]) == 3, "premise: all three were verified"
        assert {c["agent_id"] for c in calls} == {"A", "C"}, (
            "one agent's combinator failure must not abort the round"
        )
        assert "Verification error: trust update failed for target=B" in caplog.text
