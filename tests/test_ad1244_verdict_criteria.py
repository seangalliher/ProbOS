"""AD-1244: strict criterion evidence survives both judge and durable boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from probos.cognitive.crew_executor import SubtaskResult
from probos.cognitive.crew_finalizer import CrewSessionFinalizer, _VerdictRecord
from probos.cognitive.crew_session import CrewSessionService, _build_adopted_recovery_plan
from probos.cognitive.crew_trust import (
    CrewSessionTrustRecorder,
    derive_completed_crew_trust_effects,
)
from probos.cognitive.crew_verdict import (
    CriterionFail,
    CriterionPass,
    criteria_to_json,
    parse_criteria,
    parse_verdict_criteria,
    render_critique,
    validate_criteria,
)
from probos.cognitive.crew_verifier import (
    SessionVerificationPass,
    SubtaskVerifier,
    VerificationVerdict,
)
from probos.cognitive.decomposer import is_capability_gap
from probos.consensus.trust import TrustNetwork
from probos.threads import ChatThread
from probos.workforce import WorkItem
from tests.test_ad860_crew_verifier import _make_verifier
from tests.test_ad1125_room_bound_execution import (
    _Agent as _ExecutionAgent,
    _Registry as _ExecutionRegistry,
    _StaticOutcomeExecutor,
    _child,
    _crew_executor,
    _runtime as _execution_runtime,
    _session_parent,
    stores as _execution_stores,
)
from tests.test_ad1126_verified_finalization import (
    _LLMResponse,
    _ScriptedLLM,
    _StaticAgenticExecutor,
    _executing_case,
    _make_finalizer,
    _make_synthesizer,
    _make_verifier as _session_verifier,
    _registry_for,
    _runtime,
    _text,
    stores as _finalization_stores,
)
from tests.test_ad1130_outcome_only_room_trust import _round, _verification


_ABSENT = object()
_PASS = {"name": "Repository evidence", "passed": True}
_FAIL = {
    "name": "Repository evidence",
    "passed": False,
    "gap": "Supply the target/A query result.",
}
_Parser = Literal["legacy", "session"]


@pytest.fixture(params=("legacy", "session"))
def parser(request: pytest.FixtureRequest) -> _Parser:
    return request.param


def _payload(
    criteria: Any = _ABSENT, *, accepted: bool = True, critique: Any = "Checked."
) -> dict[str, Any]:
    value = {"accepted": accepted, "confidence": 0.8, "critique": critique}
    if criteria is not _ABSENT:
        value["criteria"] = criteria
    return value


def _parse(parser: _Parser, payload: dict[str, Any]) -> VerificationVerdict | SessionVerificationPass:
    content = json.dumps(payload)
    if parser == "session":
        return SubtaskVerifier._parse_session_verdict(content, "judge", 7)
    verifier, *_ = _make_verifier(responses=[])
    return verifier._parse_verdict(content, "judge")


def _assert_malformed(parser: _Parser, payload: dict[str, Any]) -> None:
    if parser == "session":
        with pytest.raises(ValueError, match="session_verdict_invalid"):
            _parse(parser, payload)
    else:
        verdict = _parse(parser, payload)
        assert isinstance(verdict, VerificationVerdict)
        assert verdict.verification_defect is True
        assert verdict.accepted is False
        assert verdict.criteria is None


@pytest.mark.parametrize(
    "criteria",
    [
        pytest.param(None, id="explicit-null"),
        pytest.param({}, id="object-not-array"),
        pytest.param("[]", id="string-not-array"),
        pytest.param([None], id="null-criterion"),
        pytest.param(["requirement"], id="string-criterion"),
        pytest.param([{}], id="empty-criterion"),
        pytest.param([{"passed": True}], id="missing-name"),
        pytest.param([{"name": None, "passed": True}], id="null-name"),
        pytest.param([{"name": 7, "passed": True}], id="numeric-name"),
        pytest.param([{"name": True, "passed": True}], id="boolean-name"),
        pytest.param([{"name": "", "passed": True}], id="empty-name"),
        pytest.param([{"name": " \t ", "passed": True}], id="blank-name"),
        pytest.param([{"name": "bad\x00name", "passed": True}], id="nul-name"),
        pytest.param([{"name": "proof"}], id="missing-passed"),
        pytest.param([{"name": "proof", "passed": 1}], id="integer-true"),
        pytest.param([{"name": "proof", "passed": 0, "gap": "proof"}], id="integer-false"),
        pytest.param([{"name": "proof", "passed": 1.0}], id="float-true"),
        pytest.param([{"name": "proof", "passed": 0.0, "gap": "proof"}], id="float-false"),
        pytest.param([{"name": "proof", "passed": "true"}], id="string-true"),
        pytest.param([{"name": "proof", "passed": "false", "gap": "proof"}], id="string-false"),
        pytest.param([{"name": "proof", "passed": None}], id="null-passed"),
        pytest.param([{"name": "proof", "passed": []}], id="array-passed"),
        pytest.param([{**_PASS, "gap": "extra"}], id="pass-with-gap"),
        pytest.param([{**_PASS, "gap": ""}], id="pass-with-empty-gap"),
        pytest.param([{**_PASS, "gap": None}], id="pass-with-null-gap"),
        pytest.param([{"name": "proof", "passed": False}], id="fail-missing-gap"),
        pytest.param([{**_FAIL, "gap": None}], id="null-gap"),
        pytest.param([{**_FAIL, "gap": 4}], id="numeric-gap"),
        pytest.param([{**_FAIL, "gap": False}], id="boolean-gap"),
        pytest.param([{**_FAIL, "gap": []}], id="array-gap"),
        pytest.param([{**_FAIL, "gap": ""}], id="empty-gap"),
        pytest.param([{**_FAIL, "gap": " \n "}], id="blank-gap"),
        pytest.param([{**_FAIL, "gap": "bad\x00gap"}], id="nul-gap"),
        pytest.param([{**_PASS, "unknown": "extra"}], id="unknown-pass-field"),
        pytest.param([{**_FAIL, "unknown": "extra"}], id="unknown-fail-field"),
    ],
)
def test_both_parsers_reject_malformed_criterion_evidence(parser: _Parser, criteria: Any) -> None:
    passed = (
        criteria[0].get("passed", True)
        if type(criteria) is list and criteria and type(criteria[0]) is dict else True
    )
    accepted = passed not in (False, 0, "false")
    # Keep the summary consistent so a cross-field error cannot mask bad schema validation.
    control = _payload([_PASS if accepted else _FAIL], accepted=accepted, critique="Supply proof.")
    assert _parse(parser, control).accepted is accepted
    _assert_malformed(parser, _payload(criteria, accepted=accepted, critique="Supply proof."))


@pytest.mark.parametrize("accepted,criteria", [(True, [_FAIL]), (False, [_PASS])])
def test_both_parsers_reject_summary_criterion_contradictions(
    parser: _Parser, accepted: bool, criteria: list[dict[str, Any]],
) -> None:
    _assert_malformed(parser, _payload(criteria, accepted=accepted))


@pytest.mark.parametrize("criteria", [_ABSENT, []], ids=["absent", "empty"])
@pytest.mark.parametrize("critique", [None, "", " \n ", 0, False, [], {}])
def test_refusal_without_failed_criteria_requires_real_top_level_gap(
    parser: _Parser, criteria: Any, critique: Any,
) -> None:
    _assert_malformed(parser, _payload(criteria, accepted=False, critique=critique))


@pytest.mark.parametrize(
    "accepted,criteria,critique",
    [
        (True, _ABSENT, "Flat acceptance"),
        (False, _ABSENT, "Supply the query result."),
        (True, [], "Flat acceptance"),
        (False, [], "Supply the query result."),
        (True, [_PASS], "Checked."),
        (False, [_FAIL], ""),
        (False, [_PASS, _FAIL], "The claim needs evidence."),
    ],
)
def test_both_parsers_preserve_valid_flat_or_structured_verdicts(
    parser: _Parser, accepted: bool, criteria: Any, critique: str,
) -> None:
    verdict = _parse(parser, _payload(criteria, accepted=accepted, critique=critique))
    assert verdict.accepted is accepted
    assert verdict.confidence == 0.8
    assert verdict.verifier_agent_id == "judge"
    if criteria is _ABSENT:
        assert verdict.criteria is None
        assert verdict.critique == critique
    else:
        assert criteria_to_json(verdict.criteria) == criteria
        if _FAIL in criteria:
            assert verdict.critique.endswith(
                "Criteria gaps:\n- Repository evidence: Supply the target/A query result."
            )
        else:
            assert verdict.critique == critique
    if isinstance(verdict, SessionVerificationPass):
        assert verdict.tokens_used == 7
        assert verdict.failure_code is None
        assert verdict.status == ("accepted" if accepted else "refuted")
    else:
        assert verdict.verification_defect is False


@pytest.mark.parametrize("model,passed", [(CriterionPass, 1), (CriterionFail, 0)])
def test_literal_models_reject_integer_boolean_even_without_union(model: Any, passed: int) -> None:
    value = {"name": "proof", "passed": passed}
    if model is CriterionFail:
        value["gap"] = "Supply proof."
    with pytest.raises(ValidationError, match="criterion_passed_invalid"):
        model.model_validate(value)


@pytest.mark.parametrize("value", [_PASS, _FAIL])
def test_criterion_models_are_frozen_and_json_roundtrip_is_typed(value: dict[str, Any]) -> None:
    criteria = parse_criteria([value])
    assert isinstance(criteria[0], CriterionPass if value["passed"] else CriterionFail)
    with pytest.raises(ValidationError, match="frozen_instance"):
        criteria[0].name = "changed"
    assert parse_criteria(criteria_to_json(criteria)) == criteria
    assert criteria_to_json(criteria) == [value]


def test_criterion_text_is_trimmed_without_losing_named_gap() -> None:
    criteria = parse_criteria([{"name": " proof ", "passed": False, "gap": " evidence \n"}])
    assert criteria_to_json(criteria) == [{"name": "proof", "passed": False, "gap": "evidence"}]
    assert render_critique("Existing reason.", criteria) == "Existing reason.\n\nCriteria gaps:\n- proof: evidence"
    assert render_critique("Flat text.", None) == "Flat text."
    assert render_critique("Flat text.", ()) == "Flat text."
    assert criteria_to_json(()) == []


@pytest.mark.parametrize("value", [None, (), {}, "[]"])
def test_parse_criteria_rejects_non_json_array(value: Any) -> None:
    with pytest.raises(ValueError, match="verdict_criteria_invalid"):
        parse_criteria(value)


def test_shared_validation_rejects_non_boolean_summary_and_missing_summary() -> None:
    with pytest.raises(ValueError, match="verdict_accepted_invalid"):
        validate_criteria(1, "checked", ())
    with pytest.raises(ValueError, match="verdict_accepted_invalid"):
        parse_verdict_criteria({"critique": "checked"})


def test_legacy_extraction_and_existing_confidence_critique_coercion_remain() -> None:
    verifier, *_ = _make_verifier(responses=[])
    verdict = verifier._parse_verdict(
        'Preface\n```json\n{"accepted":true,"confidence":"2","critique":17}\n```', "judge",
    )
    assert verdict == VerificationVerdict(True, 1.0, "17", "judge")


@pytest.mark.parametrize(
    "content",
    [
        '{"accepted":true,"confidence":0.8,"critique":"ok","criteria":[],"criteria":[]}',
        '{"accepted":true,"confidence":0.8,"critique":"ok","criteria":[{"name":"proof","name":"other","passed":true}]}',
        '{"accepted":true,"confidence":0.8,"critique":"ok","criteria":[],"extra":1}',
        '{"accepted":true,"confidence":NaN,"critique":"ok","criteria":[]}',
        '```json\n{"accepted":true,"confidence":0.8,"critique":"ok","criteria":[]}\n```',
    ],
)
def test_session_parser_retains_strict_json_contract(content: str) -> None:
    with pytest.raises(ValueError, match="session_verdict_invalid"):
        SubtaskVerifier._parse_session_verdict(content, "judge", 7)


@pytest.mark.parametrize("excess", [0, 1])
def test_session_effective_critique_budget_rejects_instead_of_dropping_gap(excess: int) -> None:
    prefix = "Criteria gaps:\n- proof: "
    gap = "x" * (2048 - len(prefix) + excess)
    payload = _payload([{"name": "proof", "passed": False, "gap": gap}], accepted=False, critique="")
    if excess:
        _assert_malformed("session", payload)
    else:
        verdict = _parse("session", payload)
        assert verdict.critique == prefix + gap
        assert len(verdict.critique) == 2048


def test_prompt_conservatism_does_not_signal_a_capability_gap() -> None:
    assert is_capability_gap("I don't have a tool for that.")
    prompt = SubtaskVerifier._JUDGE_SYSTEM_PROMPT
    assert not is_capability_gap(prompt)
    assert "mark every criterion that the supplied evidence does not positively confirm as failed" in prompt
    assert '"passed": true' in prompt and '"passed": false' in prompt
    assert "nonblank critique" in prompt


def test_verdict_fields_append_without_changing_existing_positional_constructors() -> None:
    legacy = VerificationVerdict(False, 0.0, "old", "judge", True)
    session = SessionVerificationPass("refuted", False, 0.0, "old", "judge", 7, None)
    assert legacy.criteria is None and legacy.verification_defect is True
    assert session.criteria is None and session.tokens_used == 7
    assert [field.name for field in fields(VerificationVerdict)] == [
        "accepted", "confidence", "critique", "verifier_agent_id", "verification_defect", "criteria",
    ]
    assert fields(SessionVerificationPass)[-1].name == "criteria"


def _canonical(document: dict[str, Any]) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _historical_verdict(*, accepted: bool = False, critique: str = "") -> dict[str, Any]:
    return {
        "status": "accepted" if accepted else "refuted",
        "accepted": accepted,
        "confidence": 0.8,
        "critique": critique,
        "verifier_agent_id": "judge",
        "tokens_used": 7,
        "failure_code": None,
    }


@pytest.mark.parametrize("accepted,critique", [(False, ""), (False, "Supply proof."), (True, "Checked.")])
def test_historical_verdict_bytes_hash_and_blank_refusal_are_preserved(
    accepted: bool, critique: str,
) -> None:
    original = _historical_verdict(accepted=accepted, critique=critique)
    original_bytes = _canonical(original)
    record = _VerdictRecord.model_validate(json.loads(original_bytes))
    verdict = record.to_verdict()
    assert verdict.criteria is None
    restored_bytes = _canonical(CrewSessionFinalizer._verdict_document(verdict))
    assert restored_bytes == original_bytes
    assert hashlib.sha256(restored_bytes).digest() == hashlib.sha256(original_bytes).digest()


@pytest.mark.parametrize("criteria", [[], [_FAIL]], ids=["explicit-empty", "typed-failure"])
def test_new_verdict_roundtrip_retains_metadata_and_renders_gap_only_once(
    criteria: list[dict[str, Any]],
) -> None:
    parsed = _parse("session", _payload(criteria, accepted=False, critique="Supply proof."))
    assert isinstance(parsed, SessionVerificationPass)
    original = CrewSessionFinalizer._verdict_document(parsed)
    assert original["criteria"] == criteria
    record = _VerdictRecord.model_validate(json.loads(_canonical(original)))
    restored = record.to_verdict()
    assert restored == parsed
    assert restored.criteria == parse_criteria(criteria)
    assert _canonical(CrewSessionFinalizer._verdict_document(restored)) == _canonical(original)
    assert restored.critique.count("Criteria gaps:") == (1 if criteria else 0)


@pytest.mark.parametrize(
    "criteria",
    [None, [_PASS], [{"name": "proof", "passed": False}], [{**_FAIL, "passed": 0}]],
)
def test_persisted_new_metadata_is_validated_not_trusted(criteria: Any) -> None:
    with pytest.raises(ValidationError):
        _VerdictRecord.model_validate({**_historical_verdict(critique="Supply proof."), "criteria": criteria})


class _PreCriteriaRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: str
    accepted: bool
    confidence: float
    critique: str
    verifier_agent_id: str
    tokens_used: int
    failure_code: str | None


def test_rollback_reader_must_retain_new_metadata_support() -> None:
    old = _historical_verdict(critique="Supply proof.")
    new = {**old, "criteria": [_FAIL]}
    assert _PreCriteriaRecord.model_validate(old).model_dump() == old
    with pytest.raises(ValidationError, match="criteria"):
        _PreCriteriaRecord.model_validate(new)
    for persisted in (old, new):
        compatible_reader = _VerdictRecord.model_validate(persisted)
        assert compatible_reader.model_dump(mode="json") == persisted


def _derive(payload: dict[str, Any]) -> tuple[Any, ...]:
    return derive_completed_crew_trust_effects(
        session_id="session-1", session_revision=4, child_verifications=(payload,),
        facilitator_id="facilitator", final_verifier_id="final-judge",
        final_confidence=0.8, final_evidence_sha256="a" * 64,
        approval_threshold=0.6, use_confidence_weights=True,
    )


@pytest.mark.parametrize(
    "criteria", [None, [_FAIL], [{**_PASS, "passed": 1}], [{**_PASS, "gap": ""}]],
)
def test_trust_evidence_boundary_rejects_invalid_supplied_criteria(criteria: Any) -> None:
    round_record = _round(0, status="accepted")
    round_record["verdict"]["criteria"] = criteria
    evidence = _verification(rounds=(round_record,), accepted=True)
    with pytest.raises(ValueError, match="crew_trust_evidence_invalid"):
        _derive(evidence)


@pytest.mark.parametrize("criteria", [_ABSENT, [], [_PASS]], ids=["old", "empty", "structured"])
def test_trust_evidence_hash_uses_exact_original_json(criteria: Any) -> None:
    round_record = _round(0, status="accepted")
    if criteria is not _ABSENT:
        round_record["verdict"]["criteria"] = criteria
    evidence = _verification(rounds=(round_record,), accepted=True)
    before = _canonical(evidence)
    effects = _derive(evidence)
    assert _canonical(evidence) == before
    child_effects = [effect for effect in effects if effect.role.startswith("child_")]
    assert len(child_effects) == 2
    assert {effect.evidence_sha256 for effect in child_effects} == {hashlib.sha256(before).hexdigest()}


def _db_rows(path: Path, query: str) -> list[tuple[Any, ...]]:
    assert path.is_file(), f"the real isolated database was not created: {path}"
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(query).fetchall()


def _criteria_reply(
    criteria: Any, *, accepted: bool = True, critique: str = "Checked.",
) -> _LLMResponse:
    return _LLMResponse(json.dumps(_payload(criteria, accepted=accepted, critique=critique)), tokens=7)


@pytest.fixture
async def stores(tmp_path: Path, request: pytest.FixtureRequest) -> AsyncIterator[Any]:
    generator = _finalization_stores.__wrapped__(tmp_path, request)
    value = await generator.__anext__()
    try:
        yield value
    finally:
        await generator.aclose()


@pytest.fixture
async def trust_network(tmp_path: Path) -> AsyncIterator[TrustNetwork]:
    trust = TrustNetwork(db_path=str(tmp_path / "trust.db"))
    await trust.start()
    try:
        yield trust
    finally:
        await trust.stop()


async def test_criteria_refusal_reaches_correction_and_earns_once_only_resolved_credit(
    stores: Any, tmp_path: Path, trust_network: TrustNetwork,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    judge = _ScriptedLLM([
        _criteria_reply([_FAIL], accepted=False, critique=""),
        _criteria_reply([_PASS]),
        _criteria_reply([_PASS]),
    ])
    correction = _StaticAgenticExecutor(final_text="The target/A query result supplies the evidence.")
    finalizer = _make_finalizer(
        stores=stores, service=service, registry=registry,
        verifier=_session_verifier(
            llm=judge, stores=stores, registry=registry, executor=correction,
            runtime=runtime, trust=trust_network,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([_text("Report grounded in the target/A query.")]),
            stores=stores, runtime=runtime, trust=trust_network,
        ),
        trust_recorder=CrewSessionTrustRecorder(outbox=stores.work, trust_network=trust_network),
    )
    assert trust_network.raw_scores() == {}
    completed = await finalizer.finalize(parent.id, results)
    assert completed.completed is True
    assert len(judge.requests) == 3 and len(correction.calls) == 1
    task_text = correction.calls[0]["task_text"]
    assert "Repository evidence: Supply the target/A query result." in task_text
    assert task_text.count("Supply the target/A query result.") == 1
    child = await stores.work.get_work_item(children[0].id)
    assert child is not None
    rounds = child.verification["rounds"]
    assert [record["verdict"]["status"] for record in rounds] == ["refuted", "accepted"]
    assert rounds[0]["verdict"]["criteria"] == [_FAIL]
    assert rounds[1]["verdict"]["criteria"] == [_PASS]
    assert len(child.metadata["crew_execution"]) == 14
    provenance = json.loads(await stores.attachments.read(completed.provenance_ref))
    assert provenance["final_verification"]["criteria"] == [_PASS]
    assert provenance["children"][0]["verification"] == child.verification
    rows = _db_rows(tmp_path / "workforce.db", "SELECT outcome_id, payload_json, delivered FROM crew_trust_outbox")
    assert len(rows) == 5 and all(row[2] == 1 for row in rows)
    refusal = [
        (outcome_id, json.loads(payload)) for outcome_id, payload, _delivered in rows
        if json.loads(payload)["role"] == "child_verifier"
        and json.loads(payload)["result_revision"] == 1
    ]
    assert len(refusal) == 1
    assert refusal[0][1]["success"] is True
    assert refusal[0][1]["evidence_sha256"] == hashlib.sha256(_canonical(child.verification)).hexdigest()
    receipts = _db_rows(tmp_path / "trust.db", "SELECT outcome_id FROM trust_outcome_receipts")
    assert {row[0] for row in receipts} == {row[0] for row in rows}
    assert refusal[0][0] in {row[0] for row in receipts}
    verifier_events = trust_network.get_events_for_agent("verifier-1")
    assert sum(event.intent_type == "crew_session_child_verification" for event in verifier_events) == 2
    assert trust_network.raw_scores()["verifier-1"]["alpha"] > 3.0
    assert trust_network.raw_scores()["producer-1"]["beta"] == 2.0
    before = trust_network.raw_scores()
    repeated = await finalizer.finalize(parent.id, results)
    assert repeated.state == "done"
    assert await finalizer.drain_pending_trust() == 0
    assert trust_network.raw_scores() == before
    assert _db_rows(tmp_path / "workforce.db", "SELECT outcome_id, payload_json, delivered FROM crew_trust_outbox") == rows
    assert len(stores.artifacts.list_versions(thread_id=thread.id, name="crew-result.md")) == 1


@dataclass
class _ExecutedSession:
    stores: Any
    parent: WorkItem
    thread: ChatThread
    service: CrewSessionService
    child: WorkItem
    results: list[SubtaskResult]


@asynccontextmanager
async def _executed_session(tmp_path: Path) -> AsyncIterator[_ExecutedSession]:
    generator = _execution_stores.__wrapped__(tmp_path)
    stores = await generator.__anext__()
    try:
        parent, thread, service = await _session_parent(stores)
        child = await _child(stores, parent_id=parent.id, child_id="checkpoint-child")
        session = await service.get_session(parent.id)
        assert session is not None
        executing = await service.transition_session(parent.id, "executing", expected_revision=session.revision)
        await service.adopt_recovery_plan(
            parent.id, expected_session=executing, expected_recovery=None,
            plan=_build_adopted_recovery_plan(parent.id, (child,)), expected_children=(child,),
        )
        runtime = _execution_runtime(stores, tmp_path)
        runtime.crew_session_service = service
        executor = _crew_executor(
            stores=stores, registry=_ExecutionRegistry({"agent-1": _ExecutionAgent("agent-1")}),
            executor=_StaticOutcomeExecutor(output="Durable child evidence", total_tokens=7),
            runtime=runtime, service=service,
        )
        results = await executor.resume(parent.id)
        assert len(results) == 1 and results[0].status == "done"
        child = await stores.work.get_work_item(child.id)
        assert child is not None and len(child.metadata["crew_execution"]) == 14
        yield _ExecutedSession(stores, parent, thread, service, child, results)
    finally:
        await generator.aclose()


class _PauseBeforeArtifact:
    def __init__(self) -> None:
        self.calls = 0

    def reconcile_exact_version(self, **_kwargs: Any) -> Any:
        self.calls += 1
        raise asyncio.CancelledError("pause after durable verdict checkpoints")


@pytest.mark.parametrize("metadata", ["absent", "empty", "structured", "corrected"])
async def test_old_and_new_checkpoints_restart_with_exact_bytes_and_typed_criteria(
    tmp_path: Path, metadata: str,
) -> None:
    criteria = _ABSENT if metadata == "absent" else ([] if metadata == "empty" else [_PASS])
    async with _executed_session(tmp_path) as case:
        stores = case.stores
        registry = _registry_for([case.child])
        runtime = _runtime(stores, tmp_path, case.service)
        replies = [_criteria_reply(criteria), _criteria_reply(criteria)]
        if metadata == "corrected":
            replies.insert(0, _criteria_reply([_FAIL], accepted=False, critique=""))
        judge = _ScriptedLLM(replies)
        synth = _ScriptedLLM([_text("Durable final report")])
        pause = _PauseBeforeArtifact()
        finalizer = _make_finalizer(
            stores=stores, service=case.service, registry=registry,
            verifier=_session_verifier(
                llm=judge, stores=stores, registry=registry,
                executor=_StaticAgenticExecutor(final_text="Corrected durable evidence", trace_ref=None),
                runtime=runtime,
            ),
            synthesizer=_make_synthesizer(llm=synth, stores=stores, runtime=runtime),
            artifact_store=pause,
        )
        with pytest.raises(asyncio.CancelledError, match="durable verdict checkpoints"):
            await finalizer.finalize(case.parent.id, case.results)
        assert pause.calls == 1 and len(judge.requests) == (3 if metadata == "corrected" else 2)
        recovery = await case.service.get_recovery(case.parent.id)
        assert recovery is not None and recovery.phase == "final_verified"
        assert recovery.final_verification_ref is not None
        child = await stores.work.get_work_item(case.child.id)
        assert child is not None
        child_ref = child.metadata["crew_verification_recovery"]["convergence_ref"]
        refs = (child_ref, recovery.final_verification_ref)
        checkpoint_bytes = {ref: await stores.attachments.read(ref) for ref in refs}
        for ref, blob in checkpoint_bytes.items():
            assert hashlib.sha256(blob).hexdigest() == ref
            assert _canonical(json.loads(blob)) == blob
        final_document = json.loads(checkpoint_bytes[recovery.final_verification_ref])
        if metadata == "absent":
            assert "criteria" not in final_document["verdict"]
            assert all("criteria" not in item["verdict"] for item in child.verification["rounds"])
        else:
            assert final_document["verdict"]["criteria"] == criteria
            assert child.verification["rounds"][-1]["verdict"]["criteria"] == criteria
        old_verification_bytes = _canonical(child.verification)
        original_execution = child.metadata["crew_execution"]
        original_plan = recovery.plan.model_dump(mode="json")
        parent_id, thread_id, child_id = case.parent.id, case.thread.id, case.child.id

    generator = _execution_stores.__wrapped__(tmp_path)
    restarted = await generator.__anext__()
    trust = TrustNetwork(db_path=str(tmp_path / "restart-trust.db"))
    await trust.start()
    try:
        service = CrewSessionService(work_item_store=restarted.work, chat_thread_store=restarted.chat)
        restored_child = await restarted.work.get_work_item(child_id)
        assert restored_child is not None
        registry = _registry_for([restored_child])
        runtime = _runtime(restarted, tmp_path, service)
        unused_judge, unused_synth = _ScriptedLLM([]), _ScriptedLLM([])
        finalizer = _make_finalizer(
            stores=restarted, service=service, registry=registry,
            verifier=_session_verifier(
                llm=unused_judge, stores=restarted, registry=registry,
                executor=_StaticAgenticExecutor(), runtime=runtime,
            ),
            synthesizer=_make_synthesizer(llm=unused_synth, stores=restarted, runtime=runtime),
            trust_recorder=CrewSessionTrustRecorder(outbox=restarted.work, trust_network=trust),
        )
        completed = await finalizer.resume(parent_id)
        assert completed.completed is True
        assert unused_judge.requests == unused_synth.requests == []
        restored_child = await restarted.work.get_work_item(child_id)
        assert restored_child is not None
        assert _canonical(restored_child.verification) == old_verification_bytes
        assert restored_child.metadata["crew_execution"] == original_execution
        restored_recovery = await service.get_recovery(parent_id)
        assert restored_recovery is not None and restored_recovery.phase == "published"
        assert restored_recovery.plan.model_dump(mode="json") == original_plan
        for ref, blob in checkpoint_bytes.items():
            assert await restarted.attachments.read(ref) == blob
        provenance = json.loads(await restarted.attachments.read(completed.provenance_ref))
        assert provenance["children"][0]["verification"] == restored_child.verification
        assert provenance["final_verification"] == final_document["verdict"]
        if metadata == "corrected":
            critique = restored_child.verification["rounds"][0]["verdict"]["critique"]
            assert critique.count("Criteria gaps:") == 1
            assert critique.count("Supply the target/A query result.") == 1
        raw = trust.raw_scores()
        assert raw, "no durable trust delivery occurred after restart"
        assert await finalizer.drain_pending_trust() == 0
        observed = await finalizer.resume(parent_id)
        assert observed.state == "done" and trust.raw_scores() == raw
        assert len(restarted.artifacts.list_versions(thread_id=thread_id, name="crew-result.md")) == 1
    finally:
        await trust.stop()
        await generator.aclose()
