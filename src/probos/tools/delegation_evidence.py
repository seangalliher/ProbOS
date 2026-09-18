"""Bounded, invocation-local delegation observations, not verification receipts."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from probos.artifacts.refs import ArtifactRef, validate_artifact_ref
from probos.knowledge.claims import FindingClaim, FindingPublication, compute_claim_id
from probos.tools.protocol import ToolResult

logger = logging.getLogger(__name__)

MAX_FINDINGS = 8
MAX_ARTIFACTS = 8
MAX_CORE_BYTES = 1024
MAX_IDENTIFIER_BYTES = 512
MAX_FRAME_BYTES = 4096
MAX_TRANSPORT_BYTES = 8192
MAX_OMISSION_COUNT = 2_147_483_647
MESSAGE_OMISSION_MARKER = '{"evidence_omitted":"message_limit"}'

EvidenceStatus = Literal["completed", "exhausted", "failed", "not_started", "unknown"]
CoverageState = Literal["observed", "partial", "unknown"]
Section = Literal["producer", "claims", "source_refs", "artifacts"]
OmissionReason = Literal[
    "count_limit", "field_limit", "byte_limit", "message_limit",
    "invalid", "restricted_scope", "upstream_omission",
]


def _canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
    )


def _identifier_reason(value: Any) -> OmissionReason | None:
    if type(value) is not str or not value:
        return "invalid"
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return "invalid"
    return "field_limit" if size > MAX_IDENTIFIER_BYTES else None


def _sha(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("evidence hash must be an unchanged SHA-256")
    return value


def _core_fits(core: FindingClaim) -> bool:
    if len(core.title) + len(core.claim) + len(core.basis) > MAX_CORE_BYTES:
        return False
    return len(_canonical(core.model_dump()).encode("utf-8")) <= MAX_CORE_BYTES


class _Frozen(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class EvidenceProducer(_Frozen):
    agent_id: str | None = None
    thread_id: str | None = None
    scope: Literal["this_delegate_invocation"] = "this_delegate_invocation"

    @field_validator("agent_id", "thread_id")
    @classmethod
    def bounded_identity(cls, value: str | None) -> str | None:
        if value is not None and _identifier_reason(value) is not None:
            raise ValueError("producer identity is invalid or exceeds its UTF-8 bound")
        return value


class ClaimVerification(_Frozen):
    state: Literal["not_performed", "unknown"] = "not_performed"
    scope: Literal["claims"] = "claims"


class DelegateAssertion(_Frozen):
    kind: Literal["delegate_assertion"] = "delegate_assertion"
    verification: Literal["unverified"] = "unverified"
    result_sha256: str
    result_utf8_bytes: int = Field(ge=0)

    _validate_hash = field_validator("result_sha256")(_sha)


class PublishedFindingClaim(_Frozen):
    kind: Literal["published_finding"] = "published_finding"
    verification: Literal["unverified"] = "unverified"
    claim_id: str
    core: FindingClaim | None = None
    content_omitted: Literal["field_limit"] | None = None

    _validate_hash = field_validator("claim_id")(_sha)

    @model_validator(mode="after")
    def validate_core(self) -> PublishedFindingClaim:
        if self.core is None:
            if self.content_omitted != "field_limit":
                raise ValueError("reference-only finding must disclose its content omission")
        elif (
            self.content_omitted is not None
            or not _core_fits(self.core)
            or compute_claim_id(self.core.title, self.core.claim, self.core.basis) != self.claim_id
        ):
            raise ValueError("finding core exceeds its bound or differs from its original hash")
        return self


class TraceSourceRef(_Frozen):
    kind: Literal["tool_trace"] = "tool_trace"
    content_hash: str

    _validate_hash = field_validator("content_hash")(_sha)


class FindingSourceRef(_Frozen):
    kind: Literal["published_finding"] = "published_finding"
    claim_id: str
    path: str
    classification: Literal["ship"] = "ship"
    requested_scope: Literal["ship", "fleet"] = "ship"

    _validate_hash = field_validator("claim_id")(_sha)

    @field_validator("path")
    @classmethod
    def bounded_path(cls, value: str) -> str:
        if (
            _identifier_reason(value) is not None
            or "\\" in value or "\x00" in value or ":" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("finding reference must be a bounded relative records path")
        return value


EvidenceClaim = Annotated[
    DelegateAssertion | PublishedFindingClaim, Field(discriminator="kind"),
]
SourceRef = Annotated[TraceSourceRef | FindingSourceRef, Field(discriminator="kind")]


class EvidenceCoverage(_Frozen):
    claims: CoverageState = "unknown"
    source_refs: CoverageState = "unknown"
    artifacts: CoverageState = "unknown"


class EvidenceOmission(_Frozen):
    section: Section
    reason: OmissionReason
    count: int = Field(ge=1, le=MAX_OMISSION_COUNT)
    saturated: bool = False

    @model_validator(mode="after")
    def validate_saturation(self) -> EvidenceOmission:
        if self.saturated and self.count != MAX_OMISSION_COUNT:
            raise ValueError("saturated omission count must be at the counter limit")
        return self


class DelegationEvidence(_Frozen):
    schema_version: Literal[1] = 1
    status: EvidenceStatus
    producer: EvidenceProducer = Field(default_factory=EvidenceProducer)
    verification: ClaimVerification = Field(default_factory=ClaimVerification)
    claims: tuple[EvidenceClaim, ...] = Field(default=(), max_length=MAX_FINDINGS + 1)
    source_refs: tuple[SourceRef, ...] = Field(default=(), max_length=MAX_FINDINGS + 1)
    artifacts: tuple[ArtifactRef, ...] = Field(default=(), max_length=MAX_ARTIFACTS)
    coverage: EvidenceCoverage = Field(default_factory=EvidenceCoverage)
    omissions: tuple[EvidenceOmission, ...] = Field(default=(), max_length=28)

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value: Any) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("evidence schema version must be the exact integer one")
        return value

    @model_validator(mode="after")
    def validate_envelope(self) -> DelegationEvidence:
        assertions = [claim for claim in self.claims if isinstance(claim, DelegateAssertion)]
        findings = [claim for claim in self.claims if isinstance(claim, PublishedFindingClaim)]
        traces = [ref for ref in self.source_refs if isinstance(ref, TraceSourceRef)]
        refs = [ref for ref in self.source_refs if isinstance(ref, FindingSourceRef)]
        if len(assertions) > 1 or len(traces) > 1 or len(findings) > MAX_FINDINGS:
            raise ValueError("evidence exceeds its per-producer count limits")
        if [claim.claim_id for claim in findings] != [ref.claim_id for ref in refs]:
            raise ValueError("finding claims and references must be paired in observation order")
        for ref in self.artifacts:
            if _identifier_reason(ref.thread_id) is not None:
                raise ValueError("artifact thread identity exceeds its evidence field bound")
            if self.producer.thread_id is not None and ref.thread_id != self.producer.thread_id:
                raise ValueError("artifact reference differs from its producer's thread")
            ref.name.encode("utf-8")
            ref.mime.encode("utf-8")
        if len({ref.artifact_id for ref in self.artifacts}) != len(self.artifacts):
            raise ValueError("artifact references must not repeat an identity")
        keys = [(item.section, item.reason) for item in self.omissions]
        if len(keys) != len(set(keys)):
            raise ValueError("omissions must be aggregated by section and reason")
        for section in ("claims", "source_refs", "artifacts"):
            if any(item.section == section for item in self.omissions):
                if getattr(self.coverage, section) == "observed":
                    raise ValueError("omitted evidence cannot have complete observed coverage")
        frame = _frame(self.model_dump(mode="json"))
        if not _fits(frame, MAX_FRAME_BYTES):
            raise ValueError("evidence exceeds its serialized frame or transport bound")
        return self


@dataclass(frozen=True)
class DelegatedToolResult(ToolResult):
    evidence: DelegationEvidence = field(kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, DelegationEvidence):
            raise TypeError("delegated result requires typed evidence")


def delegation_status(stopped_reason: Any) -> EvidenceStatus:
    """Map loop termination without treating completion as claim verification."""
    if type(stopped_reason) is not str:
        return "unknown"
    statuses: dict[str, EvidenceStatus] = {
        "complete": "completed",
        "max_iterations": "exhausted",
        "token_budget": "exhausted",
        "error": "failed",
    }
    return statuses.get(stopped_reason, "unknown")


def _frame(data: dict[str, Any]) -> str:
    return _canonical({"evidence": data}) + "\n"


def _fits(frame: str, cap: int) -> bool:
    # HTTPX's JSON codec uses ensure_ascii=False and compact separators. Since
    # the frame is ASCII, this is its exact additive string contribution.
    escaped_bytes = len(json.dumps(frame, ensure_ascii=False).encode("utf-8")) - 2
    return len(frame.encode("utf-8")) <= cap and escaped_bytes <= MAX_TRANSPORT_BYTES


class _Omissions:
    def __init__(self, values: tuple[EvidenceOmission, ...] = ()) -> None:
        self.values = {(item.section, item.reason): item for item in values}

    def add(self, section: Section, reason: OmissionReason, count: int = 1) -> None:
        if type(count) is not int or count < 0:
            raise ValueError("omission increment must be a nonnegative exact integer")
        if count == 0:
            return
        prior = self.values.get((section, reason))
        total = count + (prior.count if prior else 0)
        self.values[section, reason] = EvidenceOmission(
            section=section, reason=reason, count=min(total, MAX_OMISSION_COUNT),
            saturated=total > MAX_OMISSION_COUNT or bool(prior and prior.saturated),
        )

    def frozen(self) -> tuple[EvidenceOmission, ...]:
        return tuple(self.values[key] for key in sorted(self.values))


@dataclass(frozen=True)
class _Entry:
    claim: PublishedFindingClaim | None = None
    source: TraceSourceRef | FindingSourceRef | None = None
    artifact: ArtifactRef | None = None

    def omit(self, omissions: _Omissions, reason: OmissionReason) -> None:
        for section, value in (
            ("claims", self.claim), ("source_refs", self.source), ("artifacts", self.artifact),
        ):
            if value is not None:
                omissions.add(section, reason)


def _pack(
    *, status: EvidenceStatus, producer: EvidenceProducer, verification: ClaimVerification,
    assertion: DelegateAssertion | None, entries: list[_Entry], coverage: EvidenceCoverage,
    omissions: tuple[EvidenceOmission, ...], cap: int,
) -> DelegationEvidence | None:
    reason: OmissionReason = "message_limit" if cap < MAX_FRAME_BYTES else "byte_limit"
    base = _Omissions(omissions)

    def candidate(accepted: list[_Entry], omitted: list[_Entry]) -> dict[str, Any]:
        counts = _Omissions(base.frozen())
        for entry in omitted:
            entry.omit(counts, reason)
        states = coverage.model_dump()
        for item in counts.frozen():
            if item.section in states and states[item.section] != "unknown":
                states[item.section] = "partial"
        return {
            "schema_version": 1, "status": status, "producer": producer.model_dump(),
            "verification": verification.model_dump(),
            "claims": tuple(
                item.model_dump() for item in
                ([assertion] if assertion else []) +
                [entry.claim for entry in accepted if entry.claim is not None]
            ),
            "source_refs": tuple(
                entry.source.model_dump() for entry in accepted if entry.source is not None
            ),
            "artifacts": tuple(
                entry.artifact.model_dump() for entry in accepted if entry.artifact is not None
            ),
            "coverage": states,
            "omissions": tuple(item.model_dump() for item in counts.frozen()),
        }

    # Future rejected entries already have room for their omission records.
    # Whole identity fields are the only optional parts of the mandatory summary.
    for name in ("thread_id", "agent_id"):
        if _fits(_frame(candidate([], entries)), cap):
            break
        if getattr(producer, name) is not None:
            producer = EvidenceProducer(**{**producer.model_dump(), name: None})
            base.add("producer", reason)
    if not _fits(_frame(candidate([], entries)), cap):
        return None
    accepted: list[_Entry] = []
    rejected: list[_Entry] = []
    for index, entry in enumerate(entries):
        remaining = rejected + entries[index + 1:]
        trial = candidate([*accepted, entry], remaining)
        if _fits(_frame(trial), cap):
            accepted.append(entry)
        else:
            rejected.append(entry)
    return DelegationEvidence.model_validate(candidate(accepted, rejected))


def _ordered_entries(
    trace: TraceSourceRef | None,
    artifacts: list[ArtifactRef],
    findings: list[tuple[PublishedFindingClaim, FindingSourceRef]],
) -> list[_Entry]:
    entries = [_Entry(source=trace)] if trace else []
    for index in range(max(len(artifacts), len(findings))):
        if index < len(artifacts):
            entries.append(_Entry(artifact=artifacts[index]))
        if index < len(findings):
            claim, ref = findings[index]
            entries.append(_Entry(claim=claim, source=ref))
    return entries


def evidence_frame(evidence: DelegationEvidence, *, max_chars: int = 0) -> str | None:
    """Return a complete frame, or None when a finite cap cannot hold its summary."""
    if not isinstance(evidence, DelegationEvidence):
        raise TypeError("evidence formatter requires the typed envelope")
    if max_chars <= 0 or len(_frame(evidence.model_dump(mode="json"))) <= max_chars:
        return _frame(evidence.model_dump(mode="json"))
    assertion = next((c for c in evidence.claims if isinstance(c, DelegateAssertion)), None)
    trace = next((r for r in evidence.source_refs if isinstance(r, TraceSourceRef)), None)
    findings = [c for c in evidence.claims if isinstance(c, PublishedFindingClaim)]
    refs = [r for r in evidence.source_refs if isinstance(r, FindingSourceRef)]
    packed = _pack(
        status=evidence.status, producer=evidence.producer, verification=evidence.verification,
        assertion=assertion,
        entries=_ordered_entries(trace, list(evidence.artifacts), list(zip(findings, refs))),
        coverage=evidence.coverage, omissions=evidence.omissions,
        cap=min(max_chars, MAX_FRAME_BYTES),
    )
    return _frame(packed.model_dump(mode="json")) if packed is not None else None


class DelegationEvidenceCollector:
    """Retain only bounded current-invocation observations; never read a store."""

    def __init__(
        self, *, agent_id: str | None, thread_id: str | None, observed: bool = True,
    ) -> None:
        self._observed = observed
        self._omissions = _Omissions()
        identities: dict[str, str | None] = {}
        for name, value in (("agent_id", agent_id), ("thread_id", thread_id)):
            reason = _identifier_reason(value) if value not in (None, "") else None
            identities[name] = value if reason is None and value else None
            if reason is not None:
                self._omissions.add("producer", reason)
        self._producer = EvidenceProducer(**identities)
        self._findings: list[tuple[PublishedFindingClaim, FindingSourceRef]] = []

    def observe_publication(self, publication: FindingPublication) -> None:
        if not isinstance(publication, FindingPublication):
            raise TypeError("publication observation must come from the typed producer")
        if publication.classification != "ship":
            self._omit_finding("restricted_scope")
            return
        if len(self._findings) >= MAX_FINDINGS:
            self._omit_finding("count_limit")
            return
        reason = _identifier_reason(publication.path)
        if reason is not None:
            self._omit_finding(reason)
            return
        try:
            ref = FindingSourceRef(
                claim_id=publication.claim_id, path=publication.path,
                classification=publication.classification,
                requested_scope=publication.requested_scope,
            )
        except ValueError:
            self._omit_finding("invalid")
            return
        core = publication.claim
        oversized = not _core_fits(core)
        claim = PublishedFindingClaim(
            claim_id=publication.claim_id, core=None if oversized else core,
            content_omitted="field_limit" if oversized else None,
        )
        if oversized:
            self._omissions.add("claims", "field_limit")
        self._findings.append((claim, ref))

    def _omit_finding(self, reason: OmissionReason) -> None:
        self._omissions.add("claims", reason)
        self._omissions.add("source_refs", reason)

    def finish(
        self, *, status: EvidenceStatus, final_text: str = "",
        trace_ref: str | None = None, trace_expected: bool = False,
        artifact_refs: list[dict[str, Any]] | None = None, artifact_omissions: int = 0,
    ) -> DelegationEvidence:
        omissions = _Omissions(self._omissions.frozen())
        assertion = None
        if type(final_text) is not str:
            omissions.add("claims", "invalid")
        elif final_text.strip():
            try:
                original = final_text.encode("utf-8")
            except UnicodeEncodeError:
                omissions.add("claims", "invalid")
                logger.warning(
                    "AD-1191: delegate text is not UTF-8 encodable; preserving the "
                    "native result and reporting an omitted assertion instead of a hash",
                )
            else:
                assertion = DelegateAssertion(
                    result_sha256=hashlib.sha256(original).hexdigest(),
                    result_utf8_bytes=len(original),
                )
        trace = None
        if trace_ref is not None:
            try:
                trace = TraceSourceRef(content_hash=trace_ref)
            except ValueError:
                omissions.add("source_refs", "invalid")
        elif trace_expected:
            omissions.add("source_refs", "upstream_omission")
        artifacts: list[ArtifactRef] = []
        candidates = artifact_refs or []
        # The executor already returns at most 32 validated refs. Do not retain
        # an unbounded caller-supplied sequence even on this defensive boundary.
        omissions.add("artifacts", "count_limit", max(0, len(candidates) - 32))
        for raw in candidates[:32]:
            if len(artifacts) >= MAX_ARTIFACTS:
                omissions.add("artifacts", "count_limit")
                continue
            if type(raw) is dict:
                reason = _identifier_reason(raw.get("thread_id"))
                if reason is not None:
                    omissions.add("artifacts", reason)
                    continue
            try:
                ref = validate_artifact_ref(raw, thread_id=self._producer.thread_id or "")
                ref.name.encode("utf-8")
                ref.mime.encode("utf-8")
            except ValueError:
                omissions.add("artifacts", "invalid")
                continue
            if any(prior.artifact_id == ref.artifact_id for prior in artifacts):
                omissions.add("artifacts", "invalid")
                continue
            artifacts.append(ref)
        omissions.add("artifacts", "upstream_omission", artifact_omissions)
        state: CoverageState = "observed" if self._observed else "unknown"
        packed = _pack(
            status=status, producer=self._producer,
            verification=ClaimVerification(state="not_performed" if self._observed else "unknown"),
            assertion=assertion,
            entries=_ordered_entries(trace, artifacts, self._findings),
            coverage=EvidenceCoverage(claims=state, source_refs=state, artifacts=state),
            omissions=omissions.frozen(), cap=MAX_FRAME_BYTES,
        )
        if packed is None:
            raise ValueError("bounded mandatory delegation summary exceeded the frame limit")
        return packed


def unobserved_delegation_evidence(
    *, status: EvidenceStatus, agent_id: str | None = None,
    thread_id: str | None = None, final_text: str = "",
) -> DelegationEvidence:
    """Keep legacy/refused/exception paths explicitly distinct from observed-empty."""
    return DelegationEvidenceCollector(
        agent_id=agent_id, thread_id=thread_id, observed=False,
    ).finish(status=status, final_text=final_text)
