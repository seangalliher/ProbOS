"""BF-783 (#1247): accepting still paid a verifier, one layer over.

BF-778 removed the trust write that paid a verifier for accepting. The same
incentive survived through AD-861 Shapley attribution: `_build_votes` includes
accepted verifiers in the vote set, and `_record_trust` records EVERY
attributed agent with a hardcoded `success=True`.

So a verifier that accepts still gained trust, and a verifier that refuses still
gained nothing -- a refused result never reaches synthesis at all. The gradient
BF-778 was filed to remove was unchanged; only its source moved.

Resolution (a) from the issue: verifiers are excluded from `_record_trust`,
their attribution owned solely by the resolution path. One outcome authority per
role. A judge whose contribution is a JUDGEMENT is not shown correct by the work
shipping -- a judge that waves everything through appears in every successful
synthesis.

An agent that is BOTH producer and verifier in the same set keeps its producer
credit: the exclusion is verifier-only agents, not every agent that ever judged.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.crew_executor import SubtaskResult
from probos.cognitive.crew_synth import CrewSynthesizer
from probos.cognitive.crew_verifier import ConvergenceOutcome, VerificationVerdict
from probos.consensus.trust import TrustNetwork
from probos.workforce import WorkItemStore


class _FakeLLM:
    async def complete(self, *a: Any, **kw: Any):
        # Production reads `.content`; returning a bare str forces the
        # degrade path and would leave the nominal one untested.
        return SimpleNamespace(content="synthesised parent answer")

    async def generate(self, *a: Any, **kw: Any):
        return SimpleNamespace(content="synthesised parent answer")


def _accepted(*, producer: str, verifier: str, spec: str) -> ConvergenceOutcome:
    return ConvergenceOutcome(
        result=SubtaskResult(
            work_item_id=f"child-{spec}",
            spec_id=spec,
            agent_id=producer,
            output="produced output",
            status="done",
        ),
        verdict=VerificationVerdict(
            accepted=True,
            confidence=0.9,
            critique="ok",
            verifier_agent_id=verifier,
        ),
        status="converged",
    )


@pytest.fixture
async def store(tmp_path):
    s = WorkItemStore(
        db_path=str(tmp_path / "bf783.db"),
        emit_event=MagicMock(),
        tick_interval=1000,
    )
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


async def _synthesise(store, outcomes, *, trust: TrustNetwork | None = None) -> TrustNetwork:
    parent = await store.create_work_item(
        title="parent", work_type="task", assigned_to="lead",
    )
    await store.transition_work_item(parent.id, "in_progress", source="test")

    trust = trust if trust is not None else TrustNetwork()
    synth = CrewSynthesizer(
        llm_client=_FakeLLM(),
        work_item_store=store,
        trust_network=trust,
        episodic_memory=None,
        attachment_store=None,
        runtime=SimpleNamespace(),
        emit_fn=None,
    )
    await synth.synthesize(parent.id, outcomes)
    return trust


def _params(trust: TrustNetwork, agent_id: str) -> tuple[float, float]:
    """Raw Beta parameters. Never a derived mean -- the repo stores (alpha,
    beta) precisely so a comparison like this can see WHICH moved."""
    record = trust.get_record(agent_id)
    if record is None:
        return (trust.prior_alpha, trust.prior_beta)
    return (record.alpha, record.beta)


async def test_an_accepting_verifier_is_not_paid_for_accepting(store) -> None:
    """The defect. Both agents appear in a successful synthesis; only the
    producer did work the synthesis shows was good.

    Asserts NO RECORD, not merely "equal to prior". Review measured that those
    two states compare equal through the params helper, so a row written at the
    prior would have passed while still being a ledger entry nobody earned.
    """
    trust = await _synthesise(
        store, [_accepted(producer="producer-1", verifier="verifier-1", spec="s1")],
    )

    assert trust.get_record("verifier-1") is None, _params(trust, "verifier-1")


async def test_a_verifier_with_history_is_left_exactly_where_it_was(store) -> None:
    """The no-record assertion above cannot see a verifier that already had a
    row. This one seeds history and pins the exact parameters."""
    trust = TrustNetwork()
    trust.create_with_prior("veteran-verifier", alpha=7.0, beta=3.0)

    await _synthesise(
        store,
        [_accepted(producer="producer-1", verifier="veteran-verifier", spec="s1")],
        trust=trust,
    )

    assert _params(trust, "veteran-verifier") == (7.0, 3.0)


async def test_the_producer_is_still_credited(store) -> None:
    """The positive premise. Excluding everyone would satisfy the test above
    and silently remove the attribution AD-861 exists to record."""
    trust = await _synthesise(
        store, [_accepted(producer="producer-1", verifier="verifier-1", spec="s1")],
    )

    baseline = _params(TrustNetwork(), "producer-1")
    assert _params(trust, "producer-1") != baseline, (
        "the producer was not credited for work that shipped"
    )


async def test_an_agent_that_produced_and_verified_keeps_producer_credit(
    store,
) -> None:
    """The exclusion is verifier-ONLY agents.

    Shapley keys by `agent_id`, so an agent appearing in both roles yields two
    votes that merge. Dropping it entirely would punish a producer for also
    having judged something.
    """
    trust = await _synthesise(store, [
        _accepted(producer="both", verifier="verifier-1", spec="s1"),
        _accepted(producer="producer-2", verifier="both", spec="s2"),
    ])

    # Exactly the same credit a producer-only agent gets, not double.
    # "differs from baseline" alone would pass if it were paid twice.
    assert _params(trust, "both") == _params(trust, "producer-2"), (
        _params(trust, "both"), _params(trust, "producer-2"),
    )
    assert trust.get_record("verifier-1") is None
