"""AD-1191 strict, bounded evidence and legacy result identity controls."""

from __future__ import annotations

import dataclasses
import gc
import hashlib
import json
import weakref
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from probos.artifacts.refs import ArtifactRef, validate_artifact_ref
from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome, _extract_artifact_refs
from probos.cognitive.swe_harness.agentic_loop import (
    build_tool_result_messages,
    build_tool_trace_payload,
    format_tool_result_content,
    truncate_tool_output,
)
from probos.cognitive.swe_harness.tool_call import (
    DelegatedToolCallResult,
    ToolCallRequest,
    ToolCallResult,
    ToolResultBlock,
)
from probos.knowledge.claims import FindingClaim, FindingPublication, compute_claim_id
from probos.tools.delegation_evidence import (
    MAX_CORE_BYTES,
    MAX_FRAME_BYTES,
    MAX_OMISSION_COUNT,
    MAX_TRANSPORT_BYTES,
    MESSAGE_OMISSION_MARKER,
    ClaimVerification,
    DelegatedToolResult,
    DelegationEvidence,
    DelegationEvidenceCollector,
    EvidenceCoverage,
    EvidenceOmission,
    EvidenceProducer,
    FindingSourceRef,
    PublishedFindingClaim,
    delegation_status,
    evidence_frame,
    unobserved_delegation_evidence,
)
from probos.tools.protocol import ToolResult
from probos.tools.publish_finding_tool import (
    FindingToolResult,
    compute_claim_id as publication_claim_id,
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _artifact(index: int = 0, **changes: Any) -> dict[str, Any]:
    return {
        "artifact_id": f"a{index}", "content_hash": hashlib.sha256(str(index).encode()).hexdigest(),
        "thread_id": "t", "name": f"a{index}.txt", "mime": "text/plain",
        "size_bytes": 5, "version": 1, **changes,
    }


def _publication(index: int = 0, **changes: Any) -> FindingPublication:
    core = changes.pop("claim", FindingClaim(title=f"T{index}", claim="C", basis="B"))
    return FindingPublication(
        claim=core, claim_id=compute_claim_id(core.title, core.claim, core.basis),
        path=changes.pop("path", f"notebooks/A/{index}.md"),
        classification=changes.pop("classification", "ship"),
        requested_scope=changes.pop("requested_scope", "ship"), **changes,
    )


def _evidence(**changes: Any) -> DelegationEvidence:
    return DelegationEvidenceCollector(agent_id="a", thread_id="t").finish(
        status="completed", final_text="opaque result", **changes,
    )


def _omissions(evidence: DelegationEvidence) -> dict[tuple[str, str], EvidenceOmission]:
    return {(item.section, item.reason): item for item in evidence.omissions}


def test_imports_resolve_only_to_the_intended_worktree() -> None:
    import probos.artifacts.refs as refs
    import probos.cognitive.agentic_dispatch as dispatch
    import probos.cognitive.swe_harness.agentic_loop as loop
    import probos.cognitive.swe_harness.tool_call as adapter
    import probos.knowledge.claims as claims
    import probos.tools.delegate_task_tool as delegate
    import probos.tools.delegation_evidence as evidence
    import probos.tools.publish_finding_tool as publication

    root = Path(__file__).resolve().parents[1]
    for module in (refs, dispatch, loop, adapter, claims, delegate, evidence, publication):
        assert Path(module.__file__).resolve().is_relative_to(root)


def test_result_field_prefixes_and_default_outcome_are_unchanged() -> None:
    native = ["output", "error", "duration_ms", "metadata"]
    call = ["id", "output", "is_error", "duration_ms", "source_chars"]
    outcome = [
        "final_text", "stopped_reason", "denied_tools", "tool_trace_ref", "total_tokens",
        "artifact_refs", "token_source", "tool_failures", "tool_defect",
        "tool_defect_evaluated", "tool_invocations",
    ]
    for model, expected in (
        (ToolResult, native), (ToolCallResult, call),
        (DelegatedToolResult, native + ["evidence"]),
        (DelegatedToolCallResult, call + ["evidence"]),
        # AD-1190 appends `iterations` after delegation_evidence; the pinned prefix is unchanged.
        (WorkItemAgenticOutcome, outcome + ["delegation_evidence", "iterations"]),
    ):
        assert [item.name for item in dataclasses.fields(model)] == expected
    assert WorkItemAgenticOutcome("text", "complete").delegation_evidence is None


@pytest.mark.parametrize("error", [None, "delegation_failed: exact 1234 \n cause"])
@pytest.mark.parametrize("cap", [0, 36, 1000])
def test_adapter_preserves_native_fields_stored_output_trace_and_error_identity(
    error: str | None, cap: int,
) -> None:
    from probos.fault_report import error_signature

    output = {"delegated": True, "result": "x" * 10000, "stopped_reason": "error"}
    metadata = {"native": "untouched"}
    legacy = ToolResult(output=output, error=error, duration_ms=11, metadata=metadata)
    typed = DelegatedToolResult(
        output=output, error=error, duration_ms=11, metadata=metadata, evidence=_evidence(),
    )
    ordinary = ToolCallResult.from_tool_result("id", legacy, 23, max_chars=cap)
    adapted = ToolCallResult.from_tool_result("id", typed, 23, max_chars=cap)
    assert isinstance(adapted, DelegatedToolCallResult)
    for item in dataclasses.fields(ToolCallResult):
        assert getattr(adapted, item.name) == getattr(ordinary, item.name)
    assert typed.output is output and typed.metadata is metadata
    assert typed.duration_ms == 11 and adapted.duration_ms == 23
    assert adapted.evidence is typed.evidence
    call = ToolCallRequest(name="delegate_task", arguments={}, id="id", timestamp=1)
    kwargs = {"output_max_chars": 8192, "blob_max_bytes": 262144}
    assert build_tool_trace_payload([call], [adapted], **kwargs) == build_tool_trace_payload(
        [call], [ordinary], **kwargs,
    )
    assert error_signature(tool_id="delegate_task", error_text=adapted.output) == error_signature(
        tool_id="delegate_task", error_text=ordinary.output,
    )


@pytest.mark.parametrize("output", [None, "", "ordinary\ntext", {"evidence": {"status": "completed"}}])
@pytest.mark.parametrize("cap", [0, 1, 35, 73, 6000])
def test_ordinary_results_and_forged_metadata_remain_byte_identical(output: Any, cap: int) -> None:
    ordinary = ToolCallResult.from_tool_result(
        "id", ToolResult(output=output, metadata={"evidence": _evidence()}), 1, max_chars=cap,
    )
    assert type(ordinary) is ToolCallResult
    expected = truncate_tool_output(ordinary.output, max_chars=cap, head_chars=7, tail_chars=3)
    assert format_tool_result_content(ordinary, max_chars=cap, head_chars=7, tail_chars=3) == expected
    assert build_tool_result_messages(
        [ToolResultBlock(result=ordinary)], max_chars=cap, head_chars=7, tail_chars=3,
    ) == [{"role": "tool", "tool_call_id": "id", "content": expected}]


@pytest.mark.parametrize("model,kwargs", [
    (DelegatedToolResult, {}),
    (DelegatedToolCallResult, {"id": "id"}),
])
def test_native_extension_rejects_dictionary_evidence(model: type, kwargs: dict[str, Any]) -> None:
    with pytest.raises(TypeError, match="typed evidence"):
        model(**kwargs, evidence=_evidence().model_dump())


def test_frozen_models_and_collections_reject_mutation() -> None:
    evidence = _evidence(artifact_refs=[_artifact()])
    native = DelegatedToolResult(output="original", evidence=evidence)
    with pytest.raises(dataclasses.FrozenInstanceError):
        native.evidence = evidence
    with pytest.raises(ValidationError):
        evidence.status = "failed"
    with pytest.raises(ValidationError):
        evidence.producer.agent_id = "other"
    with pytest.raises(ValidationError):
        evidence.artifacts[0].name = "other"
    assert type(evidence.claims) is tuple and type(evidence.artifacts) is tuple
    with pytest.raises(TypeError):
        evidence.artifacts[0] = evidence.artifacts[0]


def test_typed_publication_rejects_untyped_extension_and_preserves_native_fields() -> None:
    with pytest.raises(TypeError, match="typed publication"):
        FindingToolResult(publication={"claim": "not authoritative"})
    publication = _publication()
    metadata = {"published": True}
    result = FindingToolResult(output="original", metadata=metadata, publication=publication)
    assert result.metadata is metadata and result.output == "original"
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.publication = publication


@pytest.mark.parametrize("reason,status", [
    ("complete", "completed"), ("max_iterations", "exhausted"),
    ("token_budget", "exhausted"), ("error", "failed"),
    ("other", "unknown"), ("", "unknown"), (None, "unknown"), ({}, "unknown"),
])
def test_stopped_reason_is_not_verification(reason: Any, status: str) -> None:
    assert delegation_status(reason) == status
    result = unobserved_delegation_evidence(status=status)
    assert result.verification.state == "unknown"
    assert result.coverage == EvidenceCoverage()


@pytest.mark.parametrize("text", ["", " \n\t", "single opaque [citation](https://example.invalid)", "\u00e9\U0001f680\r\n"])
def test_final_assertion_hashes_exact_original_utf8_without_prose_parsing(text: str) -> None:
    evidence = DelegationEvidenceCollector(agent_id="a", thread_id="t").finish(
        status="completed", final_text=text,
    )
    assert evidence.status == "completed"
    assert evidence.verification == ClaimVerification(state="not_performed")
    assert evidence.coverage.claims == "observed"
    if not text.strip():
        assert evidence.claims == ()
    else:
        assert len(evidence.claims) == 1
        claim = evidence.claims[0]
        assert claim.kind == "delegate_assertion"
        assert claim.result_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert claim.result_utf8_bytes == len(text.encode("utf-8"))
        assert claim.verification == "unverified"
        assert "title" not in claim.model_dump() and "basis" not in claim.model_dump()


@pytest.mark.parametrize("text", ["\ud800", 17, 0, False, None, {}])
def test_invalid_final_text_is_disclosed_instead_of_hashing_replacement_bytes(text: Any) -> None:
    evidence = DelegationEvidenceCollector(agent_id="a", thread_id="t").finish(
        status="completed", final_text=text,
    )
    assert not evidence.claims
    assert _omissions(evidence)["claims", "invalid"].count == 1


@pytest.mark.parametrize("version", [True, False, "1", 1.0, 2, None])
def test_exact_schema_version_rejects_coercion(version: Any) -> None:
    with pytest.raises(ValidationError):
        DelegationEvidence(status="completed", schema_version=version)


@pytest.mark.parametrize("change", [
    {"extra": "forbidden"}, {"status": "success"},
    {"producer": {"scope": "descendants"}},
    {"producer": {"agent_id": 12}},
    {"verification": {"state": "verified"}},
    {"coverage": {"claims": "complete"}},
    {"claims": [{"kind": "invented", "verification": "unverified"}]},
    {"claims": [{"kind": "delegate_assertion", "result_sha256": "a" * 64,
                 "result_utf8_bytes": True, "verification": "unverified"}]},
    {"source_refs": [{"kind": "tool_trace", "content_hash": "A" * 64}]},
    {"source_refs": [{"kind": "tool_trace", "content_hash": "a" * 64 + "\n"}]},
    {"omissions": [{"section": "claims", "reason": "invalid", "count": True}]},
    {"omissions": [{"section": "claims", "reason": "invalid", "count": 1, "saturated": 1}]},
    {"omissions": [{"section": "claims", "reason": "invalid", "count": 1, "saturated": True}]},
    {"omissions": [{"section": "other", "reason": "invalid", "count": 1}]},
    {"omissions": [{"section": "claims", "reason": "other", "count": 1}]},
])
def test_strict_envelope_rejects_malformed_json(change: dict[str, Any]) -> None:
    data = {**_evidence().model_dump(mode="json"), **change}
    with pytest.raises(ValidationError):
        DelegationEvidence.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("confidence", [True, False, "0.5", None, -0.1, 1.1, float("nan"), float("inf")])
def test_claim_core_preserves_confidence_rejections(confidence: Any) -> None:
    with pytest.raises(ValidationError):
        FindingClaim(title="T", claim="C", basis="B", confidence=confidence)


@pytest.mark.parametrize("confidence,expected", [(0, 0.0), (1, 1.0), (0.5, 0.5)])
def test_claim_core_preserves_accepted_confidence_and_hash_bytes(confidence: Any, expected: float) -> None:
    core = FindingClaim(title="  T\u00e9  ", claim=" C\u00e9 ", basis=" B ", confidence=confidence)
    canonical_bytes = '{"basis":"B","claim":"C\u00e9","title":"T\u00e9"}'.encode("utf-8")
    assert core.model_dump() == {"title": "T\u00e9", "claim": "C\u00e9", "basis": "B", "confidence": expected}
    assert publication_claim_id is compute_claim_id
    assert compute_claim_id(core.title, core.claim, core.basis) == hashlib.sha256(canonical_bytes).hexdigest()


@pytest.mark.parametrize("field,limit", [("title", 200), ("basis", 1000), ("claim", 37)])
def test_claim_publication_field_limit_and_plus_one(field: str, limit: int) -> None:
    data = {"title": "T", "claim": "C", "basis": "B", field: "x" * limit}
    assert FindingClaim.model_validate(data, context={"max_content_chars": 37})
    data[field] += "x"
    with pytest.raises(ValidationError):
        FindingClaim.model_validate(data, context={"max_content_chars": 37})


@pytest.mark.parametrize("field", ["title", "claim", "basis"])
@pytest.mark.parametrize("value", ["", "  ", None, True, 1, []])
def test_claim_core_rejects_invalid_text(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        FindingClaim(**{"title": "T", "claim": "C", "basis": "B", field: value})


def test_claim_defaults_and_punctuation_title() -> None:
    assert FindingClaim(title="T", claim="C", basis="B").confidence == 0.5
    with pytest.raises(ValidationError):
        FindingClaim(title="!!!", claim="C", basis="B")
    with pytest.raises(ValidationError):
        FindingClaim(title="T", claim="C", basis="B", invented=True)


def test_claim_normalization_keeps_the_legacy_python_string_domain() -> None:
    core = FindingClaim(title="T", claim=" \ud800 ", basis="B")
    assert core.claim == "\ud800"
    with pytest.raises(UnicodeEncodeError):
        compute_claim_id(core.title, core.claim, core.basis)


@pytest.mark.parametrize("change", [
    {"claim_id": "a" * 64}, {"classification": "private"},
    {"requested_scope": "department"}, {"requested_scope": "invalid"},
    {"path": False}, {"extra": "not part of the observation"},
])
def test_publication_model_rejects_invalid_hash_scope_and_shape(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        FindingPublication.model_validate({**_publication().model_dump(), **change})


@pytest.mark.parametrize("core_bytes", [1024, 1025])
def test_finding_core_byte_limit_keeps_original_reference_and_hash(core_bytes: int) -> None:
    overhead = len(_canonical(FindingClaim(title="T", claim="x", basis="B").model_dump())) - 1
    core = FindingClaim(title="T", claim="x" * (core_bytes - overhead), basis="B")
    assert len(_canonical(core.model_dump()).encode("utf-8")) == core_bytes
    publication = _publication(claim=core)
    collector = DelegationEvidenceCollector(agent_id="a", thread_id="t")
    collector.observe_publication(publication)
    evidence = collector.finish(status="completed")
    assert len(evidence.claims) == len(evidence.source_refs) == 1
    claim = evidence.claims[0]
    assert claim.claim_id == publication.claim_id == evidence.source_refs[0].claim_id
    assert evidence.source_refs[0].path == publication.path
    if core_bytes > MAX_CORE_BYTES:
        assert claim.core is None and claim.content_omitted == "field_limit"
        assert _omissions(evidence)["claims", "field_limit"].count == 1
    else:
        assert claim.core == core and claim.content_omitted is None
        assert not evidence.omissions


@pytest.mark.parametrize("kind", ["producer", "path"])
@pytest.mark.parametrize("text", ["x" * 512, "x" * 513, "\u00e9" * 256, "\u00e9" * 257])
def test_identifier_utf8_boundary_omits_whole_fields(kind: str, text: str) -> None:
    collector = DelegationEvidenceCollector(agent_id=text if kind == "producer" else "a", thread_id="t")
    if kind == "path":
        collector.observe_publication(_publication(path=text))
    evidence = collector.finish(status="completed")
    over = len(text.encode("utf-8")) > 512
    if kind == "producer":
        assert evidence.producer.agent_id == (None if over else text)
        section = "producer"
    else:
        assert [ref.path for ref in evidence.source_refs] == ([] if over else [text])
        assert bool(evidence.claims) is not over
        section = "source_refs"
    assert ((section, "field_limit") in _omissions(evidence)) is over


@pytest.mark.parametrize("count", [8, 9, 100])
def test_finding_count_limit_is_bounded_before_frame_packing(count: int) -> None:
    collector = DelegationEvidenceCollector(agent_id="a", thread_id="t")
    for index in range(count):
        collector.observe_publication(_publication(index))
    evidence = collector.finish(status="completed")
    assert len(evidence.claims) <= 8 and len(evidence.source_refs) <= 8
    if count > 8:
        assert _omissions(evidence)["claims", "count_limit"].count == count - 8
        assert _omissions(evidence)["source_refs", "count_limit"].count == count - 8
    assert [c.claim_id for c in evidence.claims] == [r.claim_id for r in evidence.source_refs]


@pytest.mark.parametrize("count", [8, 9, 100])
def test_artifact_count_and_upstream_omissions_are_visible(count: int) -> None:
    evidence = _evidence(artifact_refs=[_artifact(i) for i in range(count)], artifact_omissions=7)
    assert len(evidence.artifacts) == 8
    assert _omissions(evidence)["artifacts", "upstream_omission"].count == 7
    if count > 8:
        assert _omissions(evidence)["artifacts", "count_limit"].count == count - 8
    assert evidence.coverage.artifacts == "partial"


def test_omission_counts_saturate_explicitly_and_stay_aggregated() -> None:
    evidence = _evidence(artifact_omissions=MAX_OMISSION_COUNT + 1)
    omitted = _omissions(evidence)["artifacts", "upstream_omission"]
    assert omitted.count == MAX_OMISSION_COUNT and omitted.saturated is True
    bounded = _evidence(artifact_omissions=MAX_OMISSION_COUNT)
    assert _omissions(bounded)["artifacts", "upstream_omission"].saturated is False
    assert len(evidence.omissions) == 1


@pytest.mark.parametrize("count", [True, False, -1, 1.0, "1", None])
def test_collector_rejects_invalid_upstream_counts(count: Any) -> None:
    with pytest.raises(ValueError):
        _evidence(artifact_omissions=count)


def test_observed_empty_and_legacy_unknown_are_distinct() -> None:
    actual = DelegationEvidenceCollector(agent_id="a", thread_id="t").finish(status="completed")
    unknown = unobserved_delegation_evidence(status="completed", agent_id="a", thread_id="t")
    assert actual.claims == unknown.claims == actual.artifacts == unknown.artifacts == ()
    assert set(actual.coverage.model_dump().values()) == {"observed"}
    assert set(unknown.coverage.model_dump().values()) == {"unknown"}
    assert actual.verification.state == "not_performed" and unknown.verification.state == "unknown"


@pytest.mark.parametrize("field", ["name", "mime", "thread_id"])
def test_artifact_invalid_utf8_is_omitted_without_changing_legacy_validation(field: str) -> None:
    raw = _artifact(**{field: "\ud800"})
    # The seven-field legacy contract is deliberately unchanged. The new
    # JSON evidence boundary, not that persisted consumer, owns this omission.
    assert validate_artifact_ref(raw, thread_id=raw["thread_id"])
    evidence = _evidence(artifact_refs=[raw])
    assert not evidence.artifacts
    assert _omissions(evidence)["artifacts", "invalid"].count == 1


@pytest.mark.parametrize("length", [512, 513])
def test_artifact_thread_field_limit_and_plus_one(length: int) -> None:
    thread = "t" * length
    evidence = DelegationEvidenceCollector(agent_id="a", thread_id=thread).finish(
        status="completed", artifact_refs=[_artifact(thread_id=thread)],
    )
    if length == 512:
        assert len(evidence.artifacts) == 1 and evidence.artifacts[0].thread_id == thread
    else:
        assert not evidence.artifacts
        assert _omissions(evidence)["producer", "field_limit"].count == 1
        assert _omissions(evidence)["artifacts", "field_limit"].count == 1


@pytest.mark.parametrize("path", ["", "/absolute", "../parent", "n/../p", "n//p", "n\\p", "C:p", "\x00"])
def test_invalid_record_paths_are_whole_pair_omissions(path: str) -> None:
    collector = DelegationEvidenceCollector(agent_id="a", thread_id="t")
    collector.observe_publication(_publication(path=path))
    evidence = collector.finish(status="completed")
    assert not evidence.claims and not evidence.source_refs
    assert _omissions(evidence)["claims", "invalid"].count == 1
    assert _omissions(evidence)["source_refs", "invalid"].count == 1


def test_collector_does_not_retain_oversized_restricted_or_over_count_claim_objects() -> None:
    collector = DelegationEvidenceCollector(agent_id="a", thread_id="t")
    oversized = FindingClaim(title="T", claim="x" * 100000, basis="B")
    core_ref = weakref.ref(oversized)
    collector.observe_publication(_publication(claim=oversized))
    del oversized
    restricted = _publication(1, classification="private", requested_scope="private")
    restricted_ref = weakref.ref(restricted.claim)
    collector.observe_publication(restricted)
    del restricted
    for index in range(1, 8):
        collector.observe_publication(_publication(index))
    overflow = _publication(9)
    overflow_ref = weakref.ref(overflow.claim)
    collector.observe_publication(overflow)
    del overflow
    gc.collect()
    assert core_ref() is restricted_ref() is overflow_ref() is None
    evidence = collector.finish(status="completed")
    assert len(evidence.claims) <= 8
    assert _omissions(evidence)["claims", "count_limit"].count == 1
    with pytest.raises(TypeError, match="typed producer"):
        collector.observe_publication({"published": True})


def test_strict_evidence_rejects_dangling_pairs_duplicate_artifacts_and_unknown_fields() -> None:
    publication = _publication()
    claim = PublishedFindingClaim(claim_id=publication.claim_id, core=publication.claim)
    source = FindingSourceRef(claim_id=publication.claim_id, path=publication.path)
    for fields in ({"claims": (claim,)}, {"source_refs": (source,)}):
        with pytest.raises(ValidationError, match="paired"):
            DelegationEvidence(status="completed", **fields)
    ref = validate_artifact_ref(_artifact(), thread_id="t")
    with pytest.raises(ValidationError, match="repeat"):
        DelegationEvidence(status="completed", artifacts=(ref, ref))
    with pytest.raises(ValidationError, match="producer's thread"):
        DelegationEvidence(status="completed", producer=EvidenceProducer(thread_id="other"), artifacts=(ref,))
    with pytest.raises(ValidationError):
        ArtifactRef(**{**_artifact(), "extra": True})
    with pytest.raises(ValidationError):
        ClaimVerification(state="not_performed", scope="claims", extra=True)
    with pytest.raises(ValidationError):
        EvidenceCoverage(claims="observed", extra=True)
    omitted = EvidenceOmission(section="claims", reason="invalid", count=1)
    with pytest.raises(ValidationError, match="aggregated"):
        DelegationEvidence(status="completed", omissions=(omitted, omitted))
    with pytest.raises(ValidationError, match="observed coverage"):
        DelegationEvidence(status="completed", omissions=(omitted,),
                           coverage=EvidenceCoverage(claims="observed"))


@pytest.mark.parametrize("scope", ["private", "department", "ship", "fleet"])
def test_publication_scope_is_truthful_and_restricted_content_never_exported(scope: str) -> None:
    collector = DelegationEvidenceCollector(agent_id="a", thread_id="t")
    publication = _publication(
        claim=FindingClaim(title="Restricted marker", claim="secret body", basis="secret basis"),
        path="notebooks/Secret/secret-path.md",
        classification="ship" if scope == "fleet" else scope, requested_scope=scope,
    )
    collector.observe_publication(publication)
    evidence = collector.finish(status="completed")
    if scope in {"private", "department"}:
        assert evidence.claims == evidence.source_refs == ()
        assert _omissions(evidence)["claims", "restricted_scope"].count == 1
        assert _omissions(evidence)["source_refs", "restricted_scope"].count == 1
        encoded = evidence_frame(evidence)
        assert all(secret not in encoded for secret in ("secret", "Secret", "Restricted marker"))
    else:
        assert evidence.source_refs[0].classification == "ship"
        assert evidence.source_refs[0].requested_scope == scope
        assert evidence.claims[0].verification == "unverified"


@pytest.mark.parametrize("change", [
    {"artifact_id": ""}, {"artifact_id": "a" * 129}, {"artifact_id": "a\n"},
    {"content_hash": "a" * 63}, {"content_hash": "A" * 64},
    {"thread_id": ""}, {"thread_id": "other"}, {"name": "../a"},
    {"name": "a\\b"}, {"name": "\x00"}, {"name": "x" * 256},
    {"mime": ""}, {"mime": "x" * 256}, {"size_bytes": True},
    {"size_bytes": 0}, {"size_bytes": 26_214_401}, {"version": True},
    {"version": 0}, {"version": 2_147_483_648}, {"extra": "field"},
])
def test_shared_artifact_validation_preserves_all_legacy_rejections(change: dict[str, Any]) -> None:
    raw = _artifact(**change)
    with pytest.raises(ValueError):
        validate_artifact_ref(raw, thread_id="t")
    refs, omitted = _extract_artifact_refs(
        [("run_python", ToolResult(output={"artifact_details": [raw]}))], thread_id="t",
    )
    assert refs == [] and omitted == 1


def test_shared_artifact_validation_keeps_exact_seven_field_shape_and_native_limits() -> None:
    raw = _artifact(artifact_id="a" * 128, name="n" * 255, mime="m" * 255,
                    size_bytes=26_214_400, version=2_147_483_647)
    assert validate_artifact_ref(raw, thread_id="t").model_dump() == raw
    refs, omitted = _extract_artifact_refs(
        [("run_python", ToolResult(output={"artifact_details": [raw, raw, *_artifacts(40)]}))],
        thread_id="t",
    )
    assert refs[0] == raw
    assert len(refs) == 32 and omitted == 10


def _artifacts(count: int) -> list[dict[str, Any]]:
    return [_artifact(i) for i in range(count)]


@pytest.mark.parametrize("structured", [False, True])
def test_envelope_exact_frame_byte_boundary_and_plus_one(structured: bool) -> None:
    data = _evidence(artifact_refs=_artifacts(8)).model_dump()
    needed = MAX_FRAME_BYTES - len(evidence_frame(DelegationEvidence.model_validate(data)).encode())
    assert needed > 0
    for artifact in data["artifacts"]:
        for key in ("name", "mime"):
            extra = min(needed, 255 - len(artifact[key]))
            artifact[key] += "x" * extra
            needed -= extra
    assert needed == 0, "fixture did not reach the actual 4096-byte boundary"
    exact = DelegationEvidence.model_validate(data)
    frame = evidence_frame(exact)
    assert len(frame.encode("utf-8")) == 4096
    prefix = "" if structured else "[user] [tool_result:id error=False]\n"
    role = "tool" if structured else "user"
    legacy = {"messages": [{"role": role, "content": prefix + "legacy"}]}
    extended = {"messages": [{"role": role, "content": prefix + frame + "legacy"}]}
    added = len(httpx.Request("POST", "https://codec.invalid/", json=extended).content) - len(
        httpx.Request("POST", "https://codec.invalid/", json=legacy).content
    )
    assert 4096 < added <= 8192
    print(f"AD1191 boundary mode={structured} frame=4096 added_httpx_bytes={added}")
    data["producer"]["agent_id"] += "x"
    with pytest.raises(ValidationError, match="serialized frame"):
        DelegationEvidence.model_validate(data)


def test_canonical_frame_and_message_repacking_keep_atomic_pairs_and_visible_omissions() -> None:
    collector = DelegationEvidenceCollector(agent_id="a", thread_id="t")
    for index in range(8):
        collector.observe_publication(_publication(index))
    evidence = collector.finish(
        status="completed", final_text="answer", trace_ref="a" * 64,
        artifact_refs=_artifacts(8),
    )
    frame = evidence_frame(evidence)
    assert frame == _canonical(json.loads(frame)) + "\n"
    assert len(frame.splitlines()) == 1
    assert evidence.source_refs[0].kind == "tool_trace"
    for cap in (1000, 1400, 2000, 2500):
        reduced = evidence_frame(evidence, max_chars=cap)
        assert reduced is not None and len(reduced) <= cap
        parsed = DelegationEvidence.model_validate_json(json.dumps(json.loads(reduced)["evidence"]))
        assert parsed.claims[0] == evidence.claims[0]
        findings = [c.claim_id for c in parsed.claims if c.kind == "published_finding"]
        refs = [r.claim_id for r in parsed.source_refs if r.kind == "published_finding"]
        assert findings == refs
        assert any(item.reason == "message_limit" for item in parsed.omissions)
    assert evidence_frame(evidence, max_chars=1) is None
    with pytest.raises(TypeError, match="typed envelope"):
        evidence_frame({"evidence": {}})


def test_omission_bookkeeping_itself_is_bounded_even_with_all_saturated_reasons() -> None:
    reasons = (
        "count_limit", "field_limit", "byte_limit", "message_limit",
        "invalid", "restricted_scope", "upstream_omission",
    )
    omissions = tuple(
        EvidenceOmission(section=section, reason=reason, count=MAX_OMISSION_COUNT, saturated=True)
        for section in ("producer", "claims", "source_refs", "artifacts")
        for reason in reasons
    )
    evidence = DelegationEvidence(
        status="unknown", omissions=omissions,
        coverage=EvidenceCoverage(claims="partial", source_refs="partial", artifacts="partial"),
    )
    assert len(evidence.omissions) == 28
    assert len(evidence_frame(evidence).encode()) <= 4096
    assert evidence_frame(evidence, max_chars=1000) is None


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("leaf", ["x" * 300, '"\\\n\t' * 80, "\u00e9\U0001f680" * 100])
def test_packing_bounds_actual_httpx_escaped_contribution_in_both_modes(
    structured: bool, leaf: str,
) -> None:
    collector = DelegationEvidenceCollector(agent_id="a", thread_id="t")
    for index in range(8):
        collector.observe_publication(_publication(
            index, claim=FindingClaim(title=f"T{index}", claim=leaf, basis="B"),
        ))
    evidence = collector.finish(
        status="completed", final_text="original final", trace_ref="a" * 64,
        artifact_refs=[_artifact(i, name="\u00e9" * 100) for i in range(8)],
    )
    native = DelegatedToolCallResult(id="id", output=leaf * 100, evidence=evidence)
    content = format_tool_result_content(native)
    frame, suffix = content.split("\n", 1)
    assert suffix == native.output
    assert len((frame + "\n").encode()) <= MAX_FRAME_BYTES
    parsed = json.loads(frame)["evidence"]
    assert parsed["omissions"], "fixture must discriminate byte overflow from count bounds"
    prefix = "" if structured else "[tool_result:id error=False]\n"
    message = {"role": "tool" if structured else "user", "content": prefix + content}
    before = {**message, "content": prefix + native.output}
    actual = httpx.Request("POST", "https://codec.invalid/", json={"messages": [message]}).content
    legacy = httpx.Request("POST", "https://codec.invalid/", json={"messages": [before]}).content
    contribution = len(actual) - len(legacy)
    assert len(frame) < contribution <= MAX_TRANSPORT_BYTES
    findings = [c["claim_id"] for c in parsed["claims"] if c["kind"] == "published_finding"]
    refs = [r["claim_id"] for r in parsed["source_refs"] if r["kind"] == "published_finding"]
    assert findings == refs
    assert json.loads(actual)["messages"][0]["content"] == prefix + content
    print(f"AD1191 codec mode={structured} frame={len(frame) + 1} added_httpx_bytes={contribution}")


@pytest.mark.parametrize("cap", [0, 1, 2, 35, 36, 37, 72, 73, 74, 75, 500, 999, 1200, 2048, 8192])
@pytest.mark.parametrize("error", [False, True])
def test_finite_caps_never_split_json_or_turn_zero_into_unbounded(cap: int, error: bool) -> None:
    result = DelegatedToolCallResult(id="id", output="BEGIN" + "x" * 20000 + "END",
                                     is_error=error, evidence=_evidence())
    content = format_tool_result_content(result, max_chars=cap, head_chars=40, tail_chars=20)
    assert result.output.endswith("END") and len(result.output) > 20000
    assert cap == 0 or len(content) <= cap
    if 0 < cap < 36:
        assert content == "!"
    elif 36 <= cap <= 73:
        assert content == MESSAGE_OMISSION_MARKER
    else:
        line, suffix = content.split("\n", 1)
        parsed = json.loads(line)
        assert "evidence" in parsed or parsed == {"evidence_omitted": "message_limit"}
        if cap:
            assert len(line) + 1 <= cap // 2
            assert suffix == truncate_tool_output(
                result.output, max_chars=cap - len(line) - 1, head_chars=40, tail_chars=20,
            )
        else:
            assert suffix == result.output
    assert build_tool_result_messages(
        [ToolResultBlock(result=result)], max_chars=cap, head_chars=40, tail_chars=20,
    )[0]["content"] == content
