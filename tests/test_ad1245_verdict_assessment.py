"""AD-1245: an unassessed result is neither a negative ballot nor trust evidence."""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import httpx
import pytest
from fastapi import FastAPI

from probos.cognitive.crew_executor import SubtaskResult
from probos.cognitive.crew_synth import CrewSynthesizer
from probos.cognitive.crew_trust import CrewSessionTrustRecorder
from probos.cognitive.crew_verifier import (
    ConvergenceOutcome,
    SessionVerificationPass,
    SubtaskVerifier,
    VerificationVerdict,
)
from probos.consensus.quorum import QuorumEngine
from probos.consensus.shapley import _evaluate_coalition, compute_shapley_values
from probos.consensus.trust import TrustNetwork
from probos.routers.crew_tasks import router
from probos.routers.deps import get_runtime
from probos.types import ConsensusOutcome, IntentResult, QuorumPolicy, Vote
from tests.test_ad860_crew_verifier import _FakeStore, _result
from tests.test_ad1126_verified_finalization import (
    _Agent,
    _LLMResponse,
    _Registry,
    _ScriptedLLM,
    _StaticAgenticExecutor,
    _make_finalizer,
    _make_synthesizer,
    _make_verifier,
    _registry_for,
    _runtime,
    _text,
)
from tests.test_ad1244_verdict_criteria import (
    _FAIL,
    _PASS,
    _criteria_reply,
    _db_rows,
    _executed_session,
    stores,
    trust_network,
)


_Flow = Literal["legacy", "session"]


def _reply(
    accepted: bool, *, confidence: float = 0.8, critique: str = "Checked.",
) -> _LLMResponse:
    return _LLMResponse(json.dumps({
        "accepted": accepted, "confidence": confidence, "critique": critique,
    }), tokens=3)


async def _judge(
    flow: _Flow,
    response: Any,
    *,
    judge_id: str = "judge",
    independent: bool = True,
) -> VerificationVerdict | SessionVerificationPass:
    registry = _Registry([_Agent("producer"), *([_Agent(judge_id)] if independent else [])])
    provider = _ScriptedLLM([response])
    executor = _StaticAgenticExecutor()
    trust = TrustNetwork()
    before = trust.raw_scores()
    verifier = SubtaskVerifier(
        llm_client=provider,
        work_item_store=_FakeStore({"expected_output": "Supply repository evidence."}),
        agent_registry=registry,
        trust_network=trust,
        agentic_executor=executor,
        runtime=SimpleNamespace(),
    )
    if flow == "legacy":
        verdict = await verifier.verify(_result())
    else:
        verdict = await verifier.verify_for_session(
            _result(), expected_output="Supply repository evidence.",
            excluded_agent_ids=frozenset({"producer"}),
        )
    assert len(provider.requests) == int(independent), "the selected judge branch did not execute"
    assert executor.calls == []
    assert trust.raw_scores() == before
    assert trust.get_recent_events() == []
    return verdict


@pytest.mark.parametrize("flow", ["legacy", "session"])
@pytest.mark.parametrize("failure", ["malformed", "empty", "exception", "missing", "schema"])
async def test_real_verifier_structural_failure_becomes_nonapproving_abstention(
    flow: _Flow, failure: str,
) -> None:
    responses = {
        "malformed": _LLMResponse("not-json"),
        "empty": _LLMResponse(""),
        "exception": RuntimeError("scripted provider outage"),
        "missing": _reply(True),
        "schema": _LLMResponse(json.dumps({
            "accepted": False, "confidence": 0.8, "critique": "Supply proof.",
            "criteria": [{"name": "proof", "passed": False}],
        })),
    }
    verdict = await _judge(flow, responses[failure], independent=failure != "missing")
    if isinstance(verdict, VerificationVerdict):
        assert verdict.verification_defect is True
    else:
        assert verdict.status in {"unavailable", "malformed", "error"}
        assert verdict.failure_code is not None
    vote = SubtaskVerifier.verdict_to_vote(verdict)
    assert vote.abstained is True
    assert vote.approved is False
    assert vote.agent_id == verdict.verifier_agent_id
    assert vote.reason == verdict.critique
    assert compute_shapley_values([vote], 0.75, False) == {}


@pytest.mark.parametrize("flow", ["legacy", "session"])
@pytest.mark.parametrize("weighted", [False, True])
async def test_real_verifier_abstention_preserves_carry_but_not_required_participation(
    flow: _Flow, weighted: bool,
) -> None:
    votes = [
        SubtaskVerifier.verdict_to_vote(await _judge(flow, _reply(True), judge_id=agent_id))
        for agent_id in ("first", "second")
    ]
    abstention = SubtaskVerifier.verdict_to_vote(await _judge(flow, _LLMResponse("bad-json")))
    engine = QuorumEngine(QuorumPolicy(2, 0.75, weighted))
    baseline = engine.evaluate_votes(votes, proposal_id="proposal")
    assert baseline.outcome is ConsensusOutcome.APPROVED
    assessed = engine.evaluate_votes([*votes, abstention], proposal_id="proposal")
    assert assessed.outcome is ConsensusOutcome.APPROVED
    assert assessed.total_weight == baseline.total_weight
    assert assessed.weighted_rejection == baseline.weighted_rejection == 0.0
    assert assessed.shapley_values == baseline.shapley_values
    assert assessed.votes == [*votes, abstention]
    assert assessed.proposal_id == "proposal"
    required = engine.evaluate_votes([*votes, abstention], QuorumPolicy(3, 0.75, weighted))
    assert required.outcome is ConsensusOutcome.INSUFFICIENT
    assert required.policy.min_votes == 3
    assert required.votes[-1] is abstention
    assert required.shapley_values is None


@pytest.mark.parametrize("flow", ["legacy", "session"])
@pytest.mark.parametrize("confidence", [0.0, 0.8])
async def test_genuine_refusal_keeps_negative_ballot(flow: _Flow, confidence: float) -> None:
    verdict = await _judge(
        flow, _reply(False, confidence=confidence, critique="Verifier execution failed."),
    )
    if isinstance(verdict, VerificationVerdict):
        assert verdict.verification_defect is False
    else:
        assert verdict.status == "refuted" and verdict.failure_code is None
    vote = SubtaskVerifier.verdict_to_vote(verdict)
    assert vote.abstained is False
    assert vote.approved is False
    other_votes = [Vote("first", True, 0.8), Vote("second", True, 0.8)]
    result = QuorumEngine(QuorumPolicy(3, 0.75, False)).evaluate_votes([*other_votes, vote])
    assert result.outcome is ConsensusOutcome.REJECTED
    assert result.weighted_rejection == 1.0
    assert "judge" in result.shapley_values
    weighted = QuorumEngine(QuorumPolicy(3, 0.75, True)).evaluate_votes([*other_votes, vote])
    assert weighted.outcome is (
        ConsensusOutcome.APPROVED if confidence == 0.0 else ConsensusOutcome.REJECTED
    )


@pytest.mark.parametrize("flow", ["legacy", "session"])
async def test_genuine_acceptance_is_not_abstention(flow: _Flow) -> None:
    verdict = await _judge(flow, _reply(True, confidence=0.0))
    vote = SubtaskVerifier.verdict_to_vote(verdict)
    assert vote.approved is True
    assert vote.abstained is False
    result = QuorumEngine(QuorumPolicy(1, 0.75, False)).evaluate_votes([vote])
    assert result.outcome is ConsensusOutcome.APPROVED
    assert result.shapley_values == {"judge": 1.0}


@pytest.mark.parametrize(
    "verdict",
    [
        VerificationVerdict(True, 1.0, "inconsistent caller", "judge", True),
        SessionVerificationPass("malformed", True, 1.0, "inconsistent caller", "judge", 0, "verification_defect"),
    ],
)
def test_structural_defect_cannot_approve_even_with_inconsistent_accepted_bit(
    verdict: VerificationVerdict | SessionVerificationPass,
) -> None:
    vote = SubtaskVerifier.verdict_to_vote(verdict)
    assert vote.approved is False and vote.abstained is True


def test_vote_abstention_field_preserves_positional_timestamp() -> None:
    timestamp = datetime(2026, 9, 18, tzinfo=timezone.utc)
    vote = Vote("judge", False, 0.0, "gap", timestamp)
    assert vote.timestamp is timestamp and vote.abstained is False
    assert [field.name for field in fields(Vote)] == [
        "agent_id", "approved", "confidence", "reason", "timestamp", "abstained",
    ]


@pytest.mark.parametrize("weighted", [False, True])
@pytest.mark.parametrize("count", [0, 1, 3, 9])
def test_empty_and_all_abstaining_ballots_have_no_quorum_or_attribution(
    weighted: bool, count: int,
) -> None:
    votes = [Vote(str(index), True, 1.0, abstained=True) for index in range(count)]
    result = QuorumEngine(QuorumPolicy(1, 0.6, weighted)).evaluate_votes(votes)
    assert result.outcome is ConsensusOutcome.INSUFFICIENT
    assert result.total_weight == result.weighted_approval == result.weighted_rejection == 0.0
    assert result.votes == votes
    assert compute_shapley_values(votes, 0.6, weighted) == {}
    assert _evaluate_coalition(votes, 0.6, weighted) is False


@pytest.mark.parametrize("weighted", [False, True])
@pytest.mark.parametrize("count,approved", [(1, True), (3, True), (3, False), (9, False), (9, True)])
def test_shapley_excludes_abstainers_from_singleton_exact_approximate_and_equal_share(
    weighted: bool, count: int, approved: bool,
) -> None:
    genuine = [Vote(str(index), approved, 0.5) for index in range(count)]
    abstentions = [Vote(f"abs-{index}", False, 1.0, abstained=True) for index in range(10)]
    attribution = compute_shapley_values([*genuine, *abstentions], 0.6, weighted)
    assert set(attribution) == {vote.agent_id for vote in genuine}
    assert sum(attribution.values()) == pytest.approx(1.0)
    if count <= 3 or not approved:
        assert attribution == compute_shapley_values(genuine, 0.6, weighted)


@pytest.mark.parametrize("weighted", [False, True])
def test_same_agent_genuine_ballot_survives_abstention_without_weight_degradation(weighted: bool) -> None:
    genuine = [Vote("first", True, 0.1), Vote("second", False, 0.9)]
    baseline = compute_shapley_values(genuine, 0.6, weighted)
    abstention = Vote("first", False, float("nan"), abstained=True)
    assert compute_shapley_values([abstention, *genuine], 0.6, weighted) == baseline
    assert compute_shapley_values([*genuine, abstention], 0.6, weighted) == baseline
    assert "first" in baseline


@pytest.mark.parametrize("weighted", [False, True])
@pytest.mark.parametrize("successes", [[], [True], [True, True], [True, False], [False, False]])
def test_result_api_keeps_existing_tally_and_insufficient_empty_votes(
    weighted: bool, successes: list[bool],
) -> None:
    results = [
        IntentResult(intent_id="proposal", agent_id=str(index), success=success, confidence=0.8)
        for index, success in enumerate(successes)
    ]
    engine = QuorumEngine(QuorumPolicy(2, 0.6, weighted))
    old_api = engine.evaluate(results)
    ballots = [Vote(result.agent_id, result.success, result.confidence) for result in results]
    ballot_api = engine.evaluate_votes(ballots, proposal_id="proposal" if results else "")
    assert old_api.outcome is ballot_api.outcome
    assert old_api.total_weight == ballot_api.total_weight
    assert old_api.weighted_approval == ballot_api.weighted_approval
    assert old_api.weighted_rejection == ballot_api.weighted_rejection
    assert old_api.shapley_values == ballot_api.shapley_values
    assert old_api.proposal_id == ballot_api.proposal_id
    if len(results) < 2:
        assert old_api.votes == []
        assert ballot_api.votes == ballots
    else:
        assert [vote.approved for vote in old_api.votes] == successes
        assert all(not vote.abstained for vote in old_api.votes)


@pytest.mark.parametrize("stage", ["child", "final"])
@pytest.mark.parametrize("failure", ["missing", "malformed", "empty", "exception", "schema"])
async def test_session_unassessed_child_or_final_checkpoint_writes_no_trust(
    tmp_path: Path, trust_network: TrustNetwork, stage: str, failure: str,
) -> None:
    async with _executed_session(tmp_path) as case:
        stores = case.stores
        registry = _registry_for([case.child])
        if failure == "missing":
            registry = _Registry([
                _Agent("agent-1"),
                *([_Agent("facilitator-1", rank="commander")] if stage == "final" else []),
            ])
        runtime = _runtime(stores, tmp_path, case.service)
        invalid = {
            "missing": _reply(True),
            "malformed": _LLMResponse("not-json"),
            "empty": _LLMResponse(""),
            "exception": RuntimeError("scripted judge unavailable"),
            "schema": _LLMResponse(json.dumps({
                "accepted": True, "confidence": 0.8, "critique": "Checked.",
                "criteria": [_FAIL],
            })),
        }[failure]
        replies = [] if failure == "missing" else [invalid]
        if stage == "final":
            replies.insert(0, _criteria_reply([_PASS]))
        judge = _ScriptedLLM(replies)
        synth = _ScriptedLLM([_text("Final evidence")] if stage == "final" else [])
        correction = _StaticAgenticExecutor()
        finalizer = _make_finalizer(
            stores=stores, service=case.service, registry=registry,
            verifier=_make_verifier(
                llm=judge, stores=stores, registry=registry, executor=correction,
                runtime=runtime, trust=trust_network,
            ),
            synthesizer=_make_synthesizer(llm=synth, stores=stores, runtime=runtime, trust=trust_network),
            trust_recorder=CrewSessionTrustRecorder(outbox=stores.work, trust_network=trust_network),
        )
        before = trust_network.raw_scores()
        assert _db_rows(tmp_path / "trust.db", "SELECT outcome_id FROM trust_outcome_receipts") == []
        observed = await finalizer.finalize(case.parent.id, case.results)
        expected_reason = "independent_verifier_unavailable" if failure == "missing" else "verification_defect"
        assert observed.completed is False and observed.reason == expected_reason
        assert observed.state == ("blocked_needs_captain" if failure == "missing" else "failed")
        assert len(judge.requests) == int(stage == "final") + int(failure != "missing")
        assert len(synth.requests) == int(stage == "final")
        assert correction.calls == []
        child = await stores.work.get_work_item(case.child.id)
        assert child is not None and child.verification["rounds"]
        if stage == "child":
            persisted_verdict = child.verification["rounds"][0]["verdict"]
        else:
            recovery = await case.service.get_recovery(case.parent.id)
            assert recovery is not None and recovery.final_verification_ref is not None
            document = json.loads(await stores.attachments.read(recovery.final_verification_ref))
            persisted_verdict = document["verdict"]
        assert persisted_verdict["accepted"] is False
        assert persisted_verdict["status"] == (
            "unavailable" if failure == "missing" else ("error" if failure == "exception" else "malformed")
        )
        assert persisted_verdict["failure_code"] == expected_reason
        assert trust_network.raw_scores() == before
        assert trust_network.get_recent_events() == []
        assert _db_rows(tmp_path / "trust.db", "SELECT outcome_id FROM trust_outcome_receipts") == []
        assert _db_rows(tmp_path / "trust.db", "SELECT agent_id, alpha, beta FROM trust_scores") == []
        assert _db_rows(tmp_path / "workforce.db", "SELECT outcome_id FROM crew_trust_outbox") == []
        assert await stores.work.list_pending_crew_trust_outcomes(limit=20) == ()
        # Neutral trust does not suppress the existing terminal notification.
        deliveries = _db_rows(
            tmp_path / "workforce.db", "SELECT delivery_id, outcome, delivered FROM crew_delivery_outbox",
        )
        assert len(deliveries) == 1 and deliveries[0][1] == observed.state
        assert await finalizer.drain_pending_trust() == 0
        await finalizer.resume(case.parent.id)
        assert trust_network.raw_scores() == before
        assert _db_rows(
            tmp_path / "workforce.db", "SELECT delivery_id, outcome, delivered FROM crew_delivery_outbox",
        ) == deliveries


async def test_real_verifier_provenance_api_and_restarted_episode_preserve_assessment(
    stores: Any, tmp_path: Path, trust_network: TrustNetwork, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.cognitive.episodic import EpisodicMemory
    from probos.knowledge import embeddings

    monkeypatch.setattr(embeddings, "get_embedding_function", lambda: None)
    monkeypatch.setenv("ANONYMIZED_TELEMETRY", "False")
    parent = await stores.work.create_work_item(title="Repository evidence", work_type="task", assigned_to="lead")
    await stores.work.transition_work_item(parent.id, "in_progress", source="test")
    children = [
        await stores.work.create_work_item(
            title=label, work_type="task", parent_id=parent.id, assigned_to=label, status="done",
        )
        for label in ("refused-producer", "unassessed-producer", "accepted-producer")
    ]
    judge = _ScriptedLLM([
        _criteria_reply([_FAIL], accepted=False, critique=""),
        _LLMResponse("not-json"),
        _criteria_reply([_PASS]),
    ])
    registry = _Registry([_Agent("judge"), *[_Agent(child.assigned_to) for child in children]])
    runtime = SimpleNamespace(work_item_store=stores.work, attachment_store=stores.attachments)
    verifier = SubtaskVerifier(
        llm_client=judge, work_item_store=stores.work, agent_registry=registry,
        trust_network=trust_network, agentic_executor=_StaticAgenticExecutor(), runtime=runtime,
    )
    outcomes: list[ConvergenceOutcome] = []
    for child in children:
        result = SubtaskResult(
            work_item_id=child.id, spec_id=child.id, agent_id=child.assigned_to,
            output="Produced repository report", status="done",
        )
        verdict = await verifier.verify(result)
        outcomes.append(ConvergenceOutcome(
            result=result, verdict=verdict, status="converged" if verdict.accepted else "unverified",
        ))
    assert len(judge.requests) == 3 and trust_network.raw_scores() == {}
    memory_path = tmp_path / "episodes" / "episodes.db"
    memory = EpisodicMemory(db_path=memory_path)
    await memory.start()
    try:
        assert memory.is_available
        synth = CrewSynthesizer(
            llm_client=_ScriptedLLM([_text("Evidence-backed repository report")]),
            work_item_store=stores.work, trust_network=trust_network,
            episodic_memory=memory, attachment_store=stores.attachments, runtime=runtime,
        )
        completed = await synth.synthesize(parent.id, outcomes)
        assert completed.completed and completed.provenance_ref
        provenance = json.loads(await stores.attachments.read(completed.provenance_ref))
        by_id = {item["work_item_id"]: item for item in provenance["subtasks"]}
        assert by_id[children[0].id]["criteria"] == [_FAIL]
        assert by_id[children[0].id]["verification_defect"] is False
        assert by_id[children[1].id]["verification_defect"] is True
        assert "criteria" not in by_id[children[1].id]
        assert by_id[children[2].id]["criteria"] == [_PASS]
        episodes = await memory.recent(k=10)
        assert len(episodes) == 1, "the real episodic store did not persist the collaboration"
        original_episode = episodes[0]
    finally:
        await memory.stop()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/crew-tasks/{parent.id}")
    assert response.status_code == 200, response.text
    projected = {child["id"]: child["verdict"] for child in response.json()["children"]}
    assert set(projected) == {child.id for child in children}
    for verdict in projected.values():
        assert set(verdict) == {"accepted", "confidence", "critique", "verifier_agent_id", "verification_defect"}
    assert projected[children[0].id]["verification_defect"] is False
    assert "Repository evidence: Supply the target/A query result." in projected[children[0].id]["critique"]
    assert projected[children[1].id]["verification_defect"] is True
    assert projected[children[0].id]["accepted"] is projected[children[1].id]["accepted"] is False
    assert projected[children[2].id]["accepted"] is True
    assert trust_network.raw_scores()["accepted-producer"]["alpha"] > 2.0
    assert "unassessed-producer" not in trust_network.raw_scores()
    assert "refused-producer" not in trust_network.raw_scores()
    assert trust_network.get_events_for_agent("judge") == []

    restarted = EpisodicMemory(db_path=memory_path)
    await restarted.start()
    try:
        episodes = await restarted.recent(k=10)
        assert len(episodes) == 1 and episodes[0].id == original_episode.id
        assert episodes[0].outcomes == original_episode.outcomes
        recorded = {item["work_item_id"]: item for item in episodes[0].outcomes}
        assert recorded[children[0].id]["criteria"] == [_FAIL]
        assert recorded[children[0].id]["verification_defect"] is False
        assert recorded[children[1].id]["verification_defect"] is True
        assert "criteria" not in recorded[children[1].id]
        assert recorded[children[2].id]["criteria"] == [_PASS]
    finally:
        await restarted.stop()
