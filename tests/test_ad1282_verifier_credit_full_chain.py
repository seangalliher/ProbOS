"""AD-1282 (BF-782, #1246): the session path is what credits a resolved refusal.

BF-778 removed the trust write from ``verify()`` -- it recorded the verifier with
``success=verdict.accepted``, which paid a judge to agree. The open question was
where the replacement signal comes from, since a judgement's correctness is not
knowable when it is made. It becomes knowable when a correction either closes the
gap the refusal named or does not, and only ONE live path retains the round history
needed to see that: ``SubtaskVerifier.converge_for_session``.

That path already credits it. ``crew_trust.derive_completed_crew_trust_effects``
pays a refuted round that a later round followed, and delivery is durable and
idempotent through the crew trust outbox. This file proves the whole chain, from
the production entry point through to a real :class:`TrustNetwork`.

The existing coverage at ``test_ad1130_outcome_only_room_trust.py`` stops at the
derive function with a hand-built round history, so it never crosses the
``converge_for_session`` seam; and the finalizer-level test there asserts only that
the verifier's alpha exceeds 3.0, which the accepted round alone would satisfy.
Neither discriminates the credit for the REFUSAL, which is the whole decision.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.crew_finalizer import CrewSessionFinalizer, _ChildPublication
from probos.cognitive.crew_trust import CrewSessionTrustRecorder
from probos.cognitive.crew_verifier import (
    SessionConvergenceOutcome,
    SessionVerificationPass,
    SubtaskVerifier,
)
from probos.consensus.crew_trust_effect import CrewTrustEffect
from probos.consensus.trust import TrustNetwork
from probos.workforce import WorkItemStore, _insert_crew_trust_effects
from tests.test_ad1126_verified_finalization import (
    _ScriptedLLM,
    _StaticAgenticExecutor,
    _executing_case,
    _make_finalizer,
    _make_synthesizer,
    _make_verifier,
    _registry_for,
    _runtime,
    _verdict,
    stores as stores_fixture,
)

_FINAL_EVIDENCE_SHA = "b" * 64
_FINAL_VERIFIER_ID = "final-verifier-1"


@pytest.fixture
async def stores(tmp_path: Path) -> Any:
    generator = stores_fixture.__wrapped__(tmp_path)
    value = await generator.__anext__()
    try:
        yield value
    finally:
        await generator.aclose()


@pytest.fixture
async def trust_network(tmp_path: Path) -> Any:
    network = TrustNetwork(db_path=str(tmp_path / "trust.db"))
    await network.start()
    try:
        yield network
    finally:
        await network.stop()


def _final_verdict() -> SessionVerificationPass:
    return SessionVerificationPass(
        status="accepted",
        accepted=True,
        confidence=0.95,
        critique="The session deliverable is complete.",
        verifier_agent_id=_FINAL_VERIFIER_ID,
        tokens_used=3,
        failure_code=None,
    )


async def _enqueue(store: WorkItemStore, effects: tuple[CrewTrustEffect, ...]) -> None:
    """Write the derived effects to the durable outbox the finalizer writes to."""
    assert store._db is not None
    await store._db.execute("BEGIN IMMEDIATE")
    try:
        await _insert_crew_trust_effects(
            store._db,
            tuple(effect.to_payload() for effect in effects),
        )
        await store._db.commit()
    except BaseException:
        await store._db.execute("ROLLBACK")
        raise


async def _delivered_outcome_ids(store: WorkItemStore) -> set[str]:
    assert store._db is not None
    cursor = await store._db.execute(
        "SELECT outcome_id FROM crew_trust_outbox WHERE delivered = 1",
    )
    return {str(row[0]) for row in await cursor.fetchall()}


async def _converge(
    stores: Any,
    tmp_path: Path,
    *,
    service: Any,
    parent: Any,
    thread: Any,
    children: list[Any],
    results: list[Any],
    verdicts: list[Any],
    trust: TrustNetwork,
    max_rounds: int = 2,
) -> tuple[SessionConvergenceOutcome, CrewSessionFinalizer]:
    """Drive the real production entry point and return the real finalizer.

    Nothing here hand-builds a round history: the rounds come from
    ``converge_for_session`` exactly as ``crew_finalizer._converge_child`` obtains
    them.
    """
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    verifier = _make_verifier(
        llm=_ScriptedLLM(verdicts),
        stores=stores,
        registry=registry,
        executor=_StaticAgenticExecutor(final_text="Corrected child evidence"),
        runtime=runtime,
        max_rounds=max_rounds,
    )
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=verifier,
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([]),
            stores=stores,
            runtime=runtime,
        ),
        trust_recorder=CrewSessionTrustRecorder(
            outbox=stores.work,
            trust_network=trust,
        ),
    )
    assert isinstance(finalizer, CrewSessionFinalizer)
    outcome = await verifier.converge_for_session(
        results[0],
        instructions=str(registry.get("producer-1").instructions),
        task_text=str(children[0].description),
        expected_output=str(children[0].metadata["expected_output"]),
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )
    return outcome, finalizer


def _publication(
    finalizer: CrewSessionFinalizer,
    *,
    child: Any,
    thread_id: str,
    parent_id: str,
    producer_agent_id: str,
    outcome: SessionConvergenceOutcome,
) -> _ChildPublication:
    """Build the publication the way ``_checkpoint_child_convergence`` does."""
    return _ChildPublication(
        child=child,
        outcome=outcome,
        verification=CrewSessionFinalizer._verification_document(
            parent_id=parent_id,
            thread_id=thread_id,
            producer_agent_id=producer_agent_id,
            outcome=outcome,
        ),
        child_snapshot=CrewSessionFinalizer._publication_child_snapshot(child),
    )


async def test_a_refusal_resolved_by_a_correction_credits_the_verifier_end_to_end(
    stores: Any,
    tmp_path: Path,
    trust_network: TrustNetwork,
) -> None:
    """The full chain: entry point -> refusal -> correction -> acceptance -> credit.

    Every seam is crossed for real: ``converge_for_session`` produces the rounds,
    ``_verification_document`` turns them into the evidence payload,
    ``_completed_trust_effects`` derives the effects, the durable outbox carries
    them, and ``CrewSessionTrustRecorder`` applies them to a real ledger.

    The final verifier is a DIFFERENT agent so every movement on ``verifier-1``
    is attributable to child verification and nothing else.
    """
    parent, thread, service, contract, children, results = await _executing_case(stores)
    outcome, finalizer = await _converge(
        stores,
        tmp_path,
        service=service,
        parent=parent,
        thread=thread,
        children=children,
        results=results,
        verdicts=[
            _verdict(False, critique="The evidence for the claim is missing."),
            _verdict(True, critique="The correction supplies the evidence."),
        ],
        trust=trust_network,
    )

    assert [item.verdict.status for item in outcome.history] == ["refuted", "accepted"]
    assert outcome.accepted is True and outcome.status == "converged"
    refused_revision = outcome.history[0].result_revision
    accepted_revision = outcome.history[1].result_revision
    assert refused_revision != accepted_revision
    assert outcome.history[0].verdict.verifier_agent_id == "verifier-1"

    effects = finalizer._completed_trust_effects(
        session=contract,
        publications=[_publication(
            finalizer,
            child=children[0],
            thread_id=thread.id,
            parent_id=contract.task_id,
            producer_agent_id=results[0].agent_id,
            outcome=outcome,
        )],
        final_verdict=_final_verdict(),
        final_evidence_sha256=_FINAL_EVIDENCE_SHA,
    )

    # The refused round is credited by revision -- an assertion that merely found
    # *a* child_verifier credit would pass if only the acceptance were paid.
    refusal_credits = [
        effect for effect in effects
        if effect.role == "child_verifier"
        and effect.result_revision == refused_revision
    ]
    assert len(refusal_credits) == 1
    credit = refusal_credits[0]
    assert credit.agent_id == "verifier-1"
    assert credit.success is True
    assert credit.intent_type == "crew_session_child_verification"
    assert credit.work_item_id == children[0].id
    assert [
        effect.result_revision for effect in effects if effect.role == "child_verifier"
    ] == [refused_revision, accepted_revision]

    # The premise, asserted before the conclusion: the ledger has not moved yet.
    assert trust_network.raw_scores() == {}
    await _enqueue(stores.work, effects)
    recorder = CrewSessionTrustRecorder(
        outbox=stores.work,
        trust_network=trust_network,
    )
    assert await recorder.drain_pending() == len(effects)

    # THE refusal credit crossed the seam -- identified by its own outcome_id,
    # so this cannot be satisfied by the acceptance credit landing instead.
    assert await _delivered_outcome_ids(stores.work) >= {credit.outcome_id}
    events = trust_network.get_events_for_agent("verifier-1")
    assert len(events) == 2
    assert {event.intent_type for event in events} == {"crew_session_child_verification"}
    assert all(event.success for event in events)

    raw = trust_network.raw_scores()
    # Strictly above 3.0: one credit alone lands exactly there, so this
    # discriminates the refusal from the acceptance. The exact value is lower
    # than 4.0 because repeat same-direction outcomes are dampened.
    assert raw["verifier-1"]["alpha"] > 3.0
    assert raw["verifier-1"]["beta"] == 2.0
    assert raw[_FINAL_VERIFIER_ID]["alpha"] == 3.0
    assert await stores.work.list_pending_crew_trust_outcomes(limit=20) == ()


async def test_a_refusal_that_was_never_resolved_does_not_credit_the_verifier(
    stores: Any,
    tmp_path: Path,
    trust_network: TrustNetwork,
) -> None:
    """Negative control: a refusal no correction resolved pays nothing here.

    Without this, the full-chain test above passes against code that credits
    every verifier unconditionally.

    Note what actually enforces it. ``derive_completed_crew_trust_effects``
    rejects evidence whose terminal round is not accepted, so NO round is
    credited -- including the first refusal, which does have a later round and
    would otherwise satisfy ``correct_judgment``. Having a later round is not
    what pays; the child must have CONVERGED. The convergence-exhausted terminal
    is a separate derivation with its own rules and is not exercised here.
    """
    parent, thread, service, contract, children, results = await _executing_case(stores)
    outcome, finalizer = await _converge(
        stores,
        tmp_path,
        service=service,
        parent=parent,
        thread=thread,
        children=children,
        results=results,
        verdicts=[
            _verdict(False, critique="The evidence for the claim is missing."),
            _verdict(False, critique="The correction still does not supply it."),
        ],
        trust=trust_network,
        max_rounds=1,
    )

    assert [item.verdict.status for item in outcome.history] == ["refuted", "refuted"]
    assert outcome.accepted is False
    assert outcome.failure_code == "convergence_exhausted"

    with pytest.raises(ValueError, match="^crew_trust_evidence_invalid$"):
        finalizer._completed_trust_effects(
            session=contract,
            publications=[_publication(
                finalizer,
                child=children[0],
                thread_id=thread.id,
                parent_id=contract.task_id,
                producer_agent_id=results[0].agent_id,
                outcome=outcome,
            )],
            final_verdict=_final_verdict(),
            final_evidence_sha256=_FINAL_EVIDENCE_SHA,
        )

    recorder = CrewSessionTrustRecorder(
        outbox=stores.work,
        trust_network=trust_network,
    )
    assert await recorder.drain_pending() == 0
    assert trust_network.raw_scores() == {}


def test_there_is_no_record_verification_outcome_seam() -> None:
    """AD-1282: the dormant seam must not come back.

    ``record_verification_outcome`` was a public method reserved for a signal the
    session path already emits. Reintroducing it gives that signal a second
    writer: the outbox dedupes on an ``outcome_id`` derived from the evidence
    hash and revision, so a direct ``TrustNetwork`` write beside it would not be
    deduplicated and the verifier would be paid twice for one judgement.

    It also rotted. While it existed with no caller, three shipped comments came
    to assert that a caller existed -- one of them naming the convergence path
    outright. A named seam invites the claim before it invites the caller.
    """
    assert not hasattr(SubtaskVerifier, "record_verification_outcome")
