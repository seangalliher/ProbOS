"""Private owned-step formats and storage/authority ports (AD-1192).

These records are not WorkItem fields or Todo wire extensions.  In particular,
a viewed token identifies an observation; it is not an authentication credential.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError, ValidationInfo, field_validator, model_validator

from probos.crew_utils import CREW_EXECUTION_KEYS

if TYPE_CHECKING:
    from probos.workforce import WorkItem

MAX_OWNED_ROWS = 1_000
MAX_OWNED_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_INLINE_OWNED_OPERATIONS = 2_000  # Read-only v1 migration limit, not a live quota.
MAX_OWNED_VIEW_ROWS = 20
MAX_OWNED_VIEW_BYTES = 16 * 1024
MAX_OWNED_PUBLIC_RESPONSE_BYTES = 1024 * 1024
MAX_OWNED_VIEW_REFERENCE_BYTES = 4096
OwnedId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
OwnedThreadId = OwnedId | Literal[""]
OwnedDigest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
OwnedRevision = Annotated[int, Field(ge=1, le=2**63 - 1)]
OwnedCount = Annotated[int, Field(ge=0, le=2**63 - 1)]
OwnedStepsMode = Literal["awaiting_adoption", "active", "interrupted", "cancelled", "waiting_manual_gate", "completed"]


class OwnedStepsError(ValueError):
    def __init__(
        self, code: str, *, parent_id: str = "", view_id: str | None = None,
        message: str | None = None, actions: tuple[str, ...] = ("refresh", "inspect_source"),
        repair_evidence: OwnedStepsRepairEvidence | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.message = message or code.replace("_", " ")
        self.parent_id = parent_id
        self.view_id = view_id
        self.actions = actions
        self.repair_evidence = repair_evidence


@dataclass(frozen=True)
class OwnedStepsRepairEvidence:
    parent_id: str
    raw_steps_json: str
    digest: str
    read_only: Literal[True] = True


def owned_json_bytes(value: Any) -> bytes:
    """Encode only finite JSON, without coercion, with a bounded manifest size."""
    def validate(item: Any, depth: int = 0) -> None:
        if depth > 64:
            raise OwnedStepsError("owned_steps_format_invalid")
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                validate(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                validate(child, depth + 1)
            return
        raise OwnedStepsError("owned_steps_format_invalid")

    validate(value)
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise OwnedStepsError("owned_steps_format_invalid") from exc
    if len(encoded) > MAX_OWNED_MANIFEST_BYTES:
        raise OwnedStepsError("owned_steps_manifest_too_large")
    return encoded


def owned_json_loads(raw: str) -> Any:
    """Reject duplicate keys/nonfinite numbers rather than laundering old bytes."""
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise OwnedStepsError("owned_steps_format_invalid")
            result[key] = value
        return result

    if type(raw) is not str:
        raise OwnedStepsError("owned_steps_format_invalid")
    try:
        if len(raw.encode("utf-8")) > MAX_OWNED_MANIFEST_BYTES:
            raise OwnedStepsError("owned_steps_manifest_too_large")
        result = json.loads(raw, object_pairs_hook=pairs)
        owned_json_bytes(result)
        return result
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, OwnedStepsError):
            raise
        raise OwnedStepsError("owned_steps_format_invalid") from exc


def owned_digest(raw: str | bytes) -> str:
    return hashlib.sha256(raw.encode("utf-8") if isinstance(raw, str) else raw).hexdigest()


class _OwnedFormat(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always",
        allow_inf_nan=False,
    )

    @field_validator("version", mode="before", check_fields=False)
    @classmethod
    def _version_type(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("owned_steps_version_invalid")
        return value

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        owned_json_bytes(self.model_dump(mode="json"))
        return self


class OwnedTodo(_OwnedFormat):
    label: str
    status: Literal["pending", "in_progress", "submitted", "done", "rejected"]
    assigned_to: str | None = None
    submitted_by: str | None = None
    confirmed_by: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _label(self) -> Self:
        if not self.label.strip() or "\x00" in self.label:
            raise ValueError("owned_steps_row_invalid")
        return self


class _InlineTodo(OwnedTodo):
    """Decode the original v1 format only, never a valid owned Todo response."""
    status: Literal["pending", "in_progress", "submitted", "done", "rejected", "completed"]


@lru_cache(maxsize=MAX_OWNED_ROWS * 4)
def _validated_todo(raw: str) -> None:
    OwnedTodo.model_validate_json(raw)


def _row_spans(raw: str, row_type: type[OwnedTodo]) -> tuple[tuple[int, int], ...]:
    """Locate complete public rows without normalizing their original spelling."""
    value = owned_json_loads(raw)
    if type(value) is not list or len(value) > MAX_OWNED_ROWS:
        raise OwnedStepsError("owned_steps_rows_invalid")
    try:
        for row in value:
            if row_type is OwnedTodo:
                encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                if len(encoded.encode("utf-8")) <= 4096:
                    _validated_todo(encoded)
                else:
                    row_type.model_validate(row)
            else:
                row_type.model_validate(row)
    except ValidationError as exc:
        raise OwnedStepsError("owned_steps_rows_invalid") from exc
    decoder = json.JSONDecoder()
    position = raw.index("[") + 1
    spans: list[tuple[int, int]] = []
    for _ in value:
        while raw[position].isspace() or raw[position] == ",":
            position += 1
        _, end = decoder.raw_decode(raw, position)
        spans.append((position, end))
        position = end
    return tuple(spans)


_SPAN_FORMATS: OrderedDict[str, tuple[tuple[int, int], ...]] = OrderedDict()
_SPAN_FORMAT_LOCK = Lock()


def _remember_validated_spans(raw: str, spans: tuple[tuple[int, int], ...]) -> None:
    with _SPAN_FORMAT_LOCK:
        _SPAN_FORMATS[raw] = spans
        _SPAN_FORMATS.move_to_end(raw)
        while len(_SPAN_FORMATS) > 8:
            _SPAN_FORMATS.popitem(last=False)


def _validated_spans(raw: str) -> tuple[tuple[int, int], ...]:
    with _SPAN_FORMAT_LOCK:
        cached = _SPAN_FORMATS.get(raw)
        if cached is not None:
            _SPAN_FORMATS.move_to_end(raw)
            return cached
    spans = _row_spans(raw, OwnedTodo)
    _remember_validated_spans(raw, spans)
    return spans


def owned_row_spans(raw: str) -> tuple[tuple[int, int], ...]:
    if type(raw) is not str:
        raise OwnedStepsError("owned_steps_format_invalid")
    return _validated_spans(raw)


def append_owned_rows(raw: str, suffix: tuple[str, ...]) -> str:
    spans = owned_row_spans(raw)
    for row in suffix:
        owned_row_spans("[" + row + "]")
    if len(spans) + len(suffix) > MAX_OWNED_ROWS:
        raise OwnedStepsError("owned_steps_rows_invalid")
    if not suffix:
        return raw
    end = raw.rfind("]")
    result = raw[:end] + ("," if spans else "") + ",".join(suffix) + raw[end:]
    owned_row_spans(result)
    return result


def replace_owned_row(raw: str, ordinal: int, row_json: str) -> str:
    spans = owned_row_spans(raw)
    if type(ordinal) is not int or not 0 <= ordinal < len(spans):
        raise OwnedStepsError("owned_steps_row_missing")
    replacement_spans = owned_row_spans("[" + row_json + "]")
    start, end = spans[ordinal]
    result = raw[:start] + row_json + raw[end:]
    if len(replacement_spans) == 1:
        try:
            owned_json_loads(result)
        except OwnedStepsError:
            # This helper previously left combined-envelope failures to its
            # consumer. Keep that boundary, without memoizing an invalid result.
            return result
        # Every sibling retains its validated bytes; the one replacement was
        # validated above. Recheck the entire envelope's JSON/byte limits, then
        # retain only context-free spans under the exact resulting bytes.
        replacement_start, replacement_end = replacement_spans[0]
        delta = len(row_json) - (end - start)
        derived = (
            spans[:ordinal]
            + ((start + replacement_start - 1, start + replacement_end - 1),)
            + tuple((left + delta, right + delta) for left, right in spans[ordinal + 1:])
        )
        _remember_validated_spans(result, derived)
    return result


def owned_metadata_key(key: str) -> bool:
    return key.startswith(("crew_", "steps_")) or key in {
        "facilitator", "thread_id", "room_id", "session_id", "spec_id",
        "expected_output", "capability", "department", "agent", "resources",
        "agent_pull", "blocked_dependency_ids", "stopped_reason",
        "chief_agent_id", "order_id", "delegated", "delegation_reason",
        "assigned_capability", "assigned_department",
    }


def owned_source_projection(
    item: dict[str, Any], *, protected_metadata_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Ignore incidental metadata siblings, not assignment/evidence/lifecycle."""
    result = {key: value for key, value in item.items() if key != "updated_at"}
    result["metadata"] = {
        key: value for key, value in item["metadata"].items()
        if owned_metadata_key(key) or key in protected_metadata_keys
    }
    return result


def owned_child_commitment(item: dict[str, Any]) -> str:
    projection = owned_source_projection(item, protected_metadata_keys=tuple(item["metadata"]))
    for key in ("status", "assigned_to", "actual_tokens", "verification"):
        projection.pop(key, None)
    projection["metadata"] = {
        key: value for key, value in projection["metadata"].items()
        if not key.startswith(("crew_execution", "crew_verification"))
    }
    return owned_digest(owned_json_bytes(projection))


class OwnedContentReference(_OwnedFormat):
    version: Literal[1] = 1
    content_hash: OwnedDigest
    mime: Annotated[str, Field(min_length=1, max_length=255)]
    size_bytes: Annotated[int, Field(ge=0, le=2**63 - 1)]


class OwnedArtifactReference(_OwnedFormat):
    artifact_id: OwnedId
    content_hash: OwnedDigest
    thread_id: OwnedId
    name: Annotated[str, Field(min_length=1, max_length=255)]
    mime: Annotated[str, Field(min_length=1, max_length=255)]
    size_bytes: Annotated[int, Field(ge=1, le=26_214_400)]
    version: Annotated[int, Field(ge=1, le=2_147_483_647)]

    @model_validator(mode="after")
    def _name(self) -> Self:
        if any(character in self.name for character in ("/", "\\", "\x00")):
            raise ValueError("owned_steps_artifact_invalid")
        return self


class OwnedStepExecutionPermit(_OwnedFormat):
    version: Literal[1] = 1
    parent_id: OwnedId
    incarnation: OwnedId
    plan_digest: OwnedDigest
    plan_revision: OwnedRevision
    step_id: OwnedId
    child_id: OwnedId
    assignee_id: OwnedId
    assignment_epoch: OwnedRevision
    execution_nonce: OwnedId
    source_digest: OwnedDigest
    booking_id: OwnedId | None
    review_attempt_id: OwnedId | None = None


class OwnedStepSubmission(_OwnedFormat):
    permit: OwnedStepExecutionPermit
    execution_json: str
    output: OwnedContentReference | None = None
    token_usage_json: str | None = None

    @model_validator(mode="after")
    def _execution(self) -> Self:
        record = owned_json_loads(self.execution_json)
        if (
            type(record) is not dict or set(record) != CREW_EXECUTION_KEYS
            or type(record["version"]) is not int or record["version"] != 1
            or record["parent_id"] != self.permit.parent_id
            or record["work_item_id"] != self.permit.child_id
            or record["assigned_to"] != self.permit.assignee_id
            or type(record["thread_id"]) is not str
            or record["status"] not in ("done", "failed", "blocked")
            or type(record["tokens_used"]) is not int
            or not 0 <= record["tokens_used"] <= 2**63 - 1
            or type(record["output_summary"]) is not str
            or type(record["stopped_reason"]) is not str
            or (record["tool_trace_ref"] is not None and type(record["tool_trace_ref"]) is not str)
            or type(record["artifact_refs"]) is not list
            or any(type(ref) is not dict for ref in record["artifact_refs"])
            or type(record["blocked_dependency_ids"]) is not list
            or any(type(value) is not str for value in record["blocked_dependency_ids"])
            or any(type(record[key]) not in (int, float) for key in ("started_at", "finished_at"))
            or not 0 <= record["started_at"] <= record["finished_at"]
        ):
            raise ValueError("owned_steps_submission_invalid")
        reason_status = {
            "complete": "done", "error": "failed", "max_iterations": "failed",
            "token_budget": "failed", "execution_exception": "failed",
            "crew_worker_identity_lost": "failed", "unassigned": "blocked",
            "agent_unresolvable": "blocked", "dependency_blocked": "blocked",
            "start_transition_failed": "blocked",
        }
        references = [OwnedArtifactReference.model_validate(ref) for ref in record["artifact_refs"]]
        if (
            reason_status.get(record["stopped_reason"]) != record["status"]
            or len(references) > 32
            or len({ref.artifact_id for ref in references}) != len(references)
            or any(ref.thread_id != record["thread_id"] for ref in references)
            or len(record["blocked_dependency_ids"]) > 64
            or len(set(record["blocked_dependency_ids"])) != len(record["blocked_dependency_ids"])
            or (bool(record["blocked_dependency_ids"]) != (record["stopped_reason"] == "dependency_blocked"))
        ):
            raise ValueError("owned_steps_submission_invalid")
        if self.token_usage_json is not None:
            from probos.crew_execution_usage import read_crew_execution_token_usage
            read_crew_execution_token_usage({
                "crew_execution": record,
                "crew_execution_token_usage": owned_json_loads(self.token_usage_json),
            })
        return self


class OwnedExecutionResult(_OwnedFormat):
    """Exact private serialization of the unchanged SubtaskResult fields."""
    work_item_id: OwnedId
    spec_id: OwnedId
    agent_id: OwnedId | Literal[""]
    output: str | OwnedContentReference
    status: Literal["done", "failed", "blocked"]
    tool_trace_ref: OwnedDigest | None
    started_at: Annotated[float, Field(ge=0)]
    finished_at: Annotated[float, Field(ge=0)]
    stopped_reason: str
    actual_tokens: OwnedCount
    artifact_refs: tuple[OwnedArtifactReference, ...]
    blocked_dependency_ids: tuple[OwnedId, ...]


class OwnedExecutionSubmission(OwnedStepSubmission):
    version: Literal[2] = 2
    result: OwnedExecutionResult | OwnedContentReference

    @model_validator(mode="after")
    def _result_binding(self) -> Self:
        if isinstance(self.result, OwnedExecutionResult):
            execution = owned_json_loads(self.execution_json)
            if (
                self.result.work_item_id != self.permit.child_id
                or self.result.agent_id != self.permit.assignee_id
                or self.result.status != execution["status"]
                or self.result.actual_tokens != execution["tokens_used"]
                or self.result.stopped_reason != execution["stopped_reason"]
                or self.result.started_at != execution["started_at"]
                or self.result.finished_at != execution["finished_at"]
                or self.result.tool_trace_ref != execution["tool_trace_ref"]
                or [ref.model_dump(mode="json") for ref in self.result.artifact_refs] != execution["artifact_refs"]
                or list(self.result.blocked_dependency_ids) != execution["blocked_dependency_ids"]
            ):
                raise ValueError("owned_steps_result_conflict")
        return self


class OwnedCorrectionResult(_OwnedFormat):
    version: Literal[1] = 1
    permit: OwnedStepExecutionPermit
    reviewer_id: OwnedId
    result: OwnedExecutionResult

    @model_validator(mode="after")
    def _correction_binding(self) -> Self:
        if (
            self.permit.review_attempt_id is None
            or self.reviewer_id == self.permit.assignee_id
            or self.result.work_item_id != self.permit.child_id
            or self.result.agent_id != self.permit.assignee_id
            or self.result.status != "done"
            or self.result.stopped_reason != "complete"
        ):
            raise ValueError("owned_steps_correction_result_invalid")
        return self


class OwnedUnstartedSubmission(_OwnedFormat):
    version: Literal[2] = 2
    admission: Literal["not_started"] = "not_started"
    parent_id: OwnedId
    incarnation: OwnedId
    plan_digest: OwnedDigest
    step_id: OwnedId
    child_id: OwnedId
    assignment_epoch: OwnedRevision
    assignee_id: OwnedId | None
    thread_id: OwnedThreadId
    source_digest: OwnedDigest
    execution_json: str
    result: OwnedExecutionResult

    @model_validator(mode="after")
    def _unstarted(self) -> Self:
        record = owned_json_loads(self.execution_json)
        if (
            type(record) is not dict or set(record) != CREW_EXECUTION_KEYS
            or type(record["version"]) is not int or record["version"] != 1
            or record["parent_id"] != self.parent_id or record["work_item_id"] != self.child_id
            or record["assigned_to"] != self.assignee_id or record["thread_id"] != self.thread_id
            or record["status"] != "blocked" or record["tokens_used"] != 0
            or record["stopped_reason"] not in ("unassigned", "agent_unresolvable", "dependency_blocked", "start_transition_failed")
            or record["output_summary"] != "" or record["tool_trace_ref"] is not None or record["artifact_refs"] != []
            or self.result.status != "blocked" or self.result.actual_tokens != 0 or self.result.output != ""
            or self.result.work_item_id != self.child_id or self.result.agent_id != (self.assignee_id or "")
            or self.result.stopped_reason != record["stopped_reason"]
            or self.result.started_at != record["started_at"] or self.result.finished_at != record["finished_at"]
            or list(self.result.blocked_dependency_ids) != record["blocked_dependency_ids"]
        ):
            raise ValueError("owned_steps_unstarted_evidence_invalid")
        return self


class ReviewedStepResult(_OwnedFormat):
    """Original submission and corrected independent result are distinct hashes."""
    submission_digest: OwnedDigest
    permit: OwnedStepExecutionPermit
    reviewed_result: OwnedContentReference
    verification: OwnedContentReference
    reviewer_id: OwnedId
    review_attempt_id: OwnedId
    accepted: bool


class UnassessedStepCheckpoint(_OwnedFormat):
    version: Literal[1] = 1
    assessment: Literal["unassessed"] = "unassessed"
    submission_digest: OwnedDigest
    permit: OwnedStepExecutionPermit
    verification: OwnedContentReference
    convergence: OwnedContentReference


class FinalizeReceipt(_OwnedFormat):
    parent_id: OwnedId
    owner_kind: Literal["canonical", "legacy"]
    thread_id: OwnedThreadId
    incarnation: OwnedId
    plan_digest: OwnedDigest
    source_review_digest: OwnedDigest
    manifest: OwnedContentReference
    output: OwnedContentReference
    publication_owner_id: OwnedId

    @model_validator(mode="after")
    def _scope(self) -> Self:
        if self.owner_kind == "canonical" and not self.thread_id:
            raise ValueError("owned_steps_canonical_scope_invalid")
        return self


class OwnedStepChild(_OwnedFormat):
    child_id: OwnedId
    spec_id: OwnedId
    commitment_digest: OwnedDigest


class _StepRecordFields(_OwnedFormat):
    step_id: OwnedId
    kind: Literal["manual", "child"]
    revision: OwnedRevision = 1
    todo_json: str
    digest: OwnedDigest
    child: OwnedStepChild | None = None
    source_digest: OwnedDigest | None = None
    plan_metadata_keys: tuple[str, ...] = ()
    assignee_id: OwnedId | None = None
    assignment_epoch: OwnedRevision = 1
    booking_id: OwnedId | None = None
    permit_state: Literal["unstarted", "started", "submitted", "terminal", "revoked", "interrupted"] = "unstarted"


class InlineOwnedStepRecord(_StepRecordFields):
    permit: OwnedStepExecutionPermit | None = None
    submission: OwnedStepSubmission | None = None
    reviewed_result: ReviewedStepResult | None = None

    @model_validator(mode="after")
    def _row(self) -> Self:
        _row_spans("[" + self.todo_json + "]", _InlineTodo)
        if self.digest != owned_digest(self.todo_json) or (
            (self.kind == "child") != (self.child is not None)
        ) or ((self.kind == "child") != (self.source_digest is not None)):
            raise ValueError("owned_steps_row_invalid")
        if self.kind == "manual" and (
            self.permit is not None or self.submission is not None
            or self.reviewed_result is not None or self.booking_id is not None
            or self.plan_metadata_keys
        ):
            raise ValueError("owned_steps_row_invalid")
        if self.permit is not None and (
            self.child is None or self.permit.child_id != self.child.child_id
            or self.permit.step_id != self.step_id
            or (
                self.permit_state != "revoked"
                and self.permit.assignment_epoch != self.assignment_epoch
            )
            or self.permit.assignee_id != self.assignee_id
            or self.permit.booking_id != self.booking_id
        ):
            raise ValueError("owned_steps_permit_invalid")
        if self.submission is not None and self.submission.permit != self.permit:
            raise ValueError("owned_steps_submission_invalid")
        if self.kind == "child":
            todo = owned_json_loads(self.todo_json)
            if (
                (self.permit_state == "unstarted" and (self.permit is not None or self.submission is not None))
                or (self.permit_state == "started" and (self.permit is None or self.submission is not None))
                or (self.permit_state in ("submitted", "terminal") and (self.permit is None or self.submission is None))
                or (todo["status"] in ("done", "completed") and (
                    self.reviewed_result is None or not self.reviewed_result.accepted
                ))
            ):
                raise ValueError("owned_steps_evidence_invalid")
        if self.reviewed_result is not None and (
            self.submission is None or self.reviewed_result.permit != self.permit
            or self.reviewed_result.reviewer_id == self.assignee_id
            or self.reviewed_result.submission_digest != owned_digest(
                owned_json_bytes(self.submission.model_dump(mode="json")),
            )
        ):
            raise ValueError("owned_steps_review_invalid")
        return self


class InlineOwnedOperationReceipt(_OwnedFormat):
    operation_id: OwnedId
    request_digest: OwnedDigest
    step_id: OwnedId | None
    disposition: Literal["applied", "started", "submitted", "cancelled", "adopted", "repaired"]
    permit: OwnedStepExecutionPermit | None = None


class OwnedStepRecord(_StepRecordFields):
    """Current evidence hashes, not an ever-growing or hydrated history."""
    permit: OwnedDigest | None = None
    submission: OwnedDigest | None = None
    reviewed_result: OwnedDigest | None = None
    review_accepted: bool | None = None

    @model_validator(mode="after")
    def _row(self) -> Self:
        owned_row_spans("[" + self.todo_json + "]")
        if (
            self.digest != owned_digest(self.todo_json)
            or ((self.kind == "child") != (self.child is not None))
            or ((self.kind == "child") != (self.source_digest is not None))
        ):
            raise ValueError("owned_steps_row_invalid")
        if self.kind == "manual":
            if any(value is not None for value in (
                self.permit, self.submission, self.reviewed_result, self.review_accepted, self.booking_id,
            )) or self.plan_metadata_keys:
                raise ValueError("owned_steps_row_invalid")
        elif (
            (self.permit_state == "unstarted" and (self.permit is not None or self.submission is not None))
            or (self.permit_state == "started" and (self.permit is None or self.submission is not None))
            or (self.permit_state == "submitted" and (self.permit is None or self.submission is None))
            or (self.permit_state == "terminal" and self.submission is None)
            or (self.submission is not None and self.permit is None and self.permit_state not in ("terminal", "revoked"))
            or ((self.reviewed_result is None) != (self.review_accepted is None))
            or (self.reviewed_result is not None and self.submission is None)
            or (owned_json_loads(self.todo_json)["status"] == "done" and self.review_accepted is not True)
        ):
            raise ValueError("owned_steps_evidence_invalid")
        return self


@lru_cache(maxsize=MAX_OWNED_ROWS * 4)
def _validated_owned_row(raw: str) -> OwnedStepRecord:
    return OwnedStepRecord.model_validate_json(raw)


class OwnedStepObservation(_OwnedFormat):
    parent_id: OwnedId
    incarnation: OwnedId
    plan_digest: OwnedDigest
    plan_revision: OwnedRevision
    layout_revision: OwnedRevision
    observation_revision: OwnedRevision
    steps_digest: OwnedDigest
    step_id: OwnedId | None
    row_revision: OwnedRevision | None
    row_digest: OwnedDigest | None
    todo_json: str | None
    source_digest: OwnedDigest | None
    permit_state: Literal["unstarted", "started", "submitted", "terminal", "revoked", "interrupted"] | None


class OwnedOperationReceipt(_OwnedFormat):
    version: Literal[2] = 2
    operation_id: OwnedId
    request_digest: OwnedDigest
    step_id: OwnedId | None
    disposition: Literal[
        "applied", "started", "submitted", "reviewed", "cancelled", "adopted", "repaired",
        "noop", "observed_started", "observed_terminal",
        "synthesis_started",
        "correction_started", "correction_submitted",
    ]
    permit: OwnedStepExecutionPermit | None = None
    # V1 recorded no observation. Migration must not invent one from today's row.
    observation: OwnedStepObservation | None = None


class OwnedEffectAttempt(_OwnedFormat):
    effect_id: OwnedId
    kind: Literal["producer_trust", "collaboration_episode", "crew_task_completed"]
    intent: OwnedContentReference
    claimed_at: Annotated[float, Field(ge=0)]
    disposition: Literal["attempted_unknown"] = "attempted_unknown"


class _ControlFields(_OwnedFormat):
    owner_kind: Literal["canonical", "legacy"]
    parent_id: OwnedId
    thread_id: OwnedThreadId
    facilitator_id: OwnedId | None
    incarnation: OwnedId
    layout_revision: OwnedRevision = 1
    plan_revision: OwnedRevision = 1
    observation_revision: OwnedRevision = 1
    plan_digest: OwnedDigest
    seed_digest: OwnedDigest
    seed_request_digest: OwnedDigest
    steps_digest: OwnedDigest
    parent_source_digest: OwnedDigest
    manual_prefix_length: Annotated[int, Field(ge=0, le=MAX_OWNED_ROWS)]
    original_steps_json: str
    authorized_steps_json: str
    gate_json: str
    mode: OwnedStepsMode
    finalization: FinalizeReceipt | None = None
    finalization_disposition: Literal["pending", "completed", "conflict"] | None = None

    @model_validator(mode="after")
    def _scope(self) -> Self:
        if self.owner_kind == "canonical" and (not self.thread_id or self.facilitator_id is None):
            raise ValueError("owned_steps_canonical_scope_invalid")
        return self


class InlineOwnedStepsControl(_ControlFields):
    """Strict v1 reader used only by the transactional migration."""
    version: Literal[1] = 1
    rows: Annotated[tuple[InlineOwnedStepRecord, ...], Field(max_length=MAX_OWNED_ROWS)]
    operations: Annotated[tuple[InlineOwnedOperationReceipt, ...], Field(max_length=MAX_INLINE_OWNED_OPERATIONS)] = ()
    effect_attempts: Annotated[tuple[OwnedEffectAttempt, ...], Field(max_length=MAX_INLINE_OWNED_OPERATIONS)] = ()

    @model_validator(mode="after")
    def _control(self) -> Self:
        original = _row_spans(self.original_steps_json, _InlineTodo)
        current = _row_spans(self.authorized_steps_json, _InlineTodo)
        owned_json_loads(self.gate_json)
        visible = self.rows[:self.manual_prefix_length] if self.mode == "awaiting_adoption" else self.rows
        children = [row.child.child_id for row in self.rows if row.child is not None]
        if (
            len(original) != self.manual_prefix_length or len(visible) != len(current)
            or self.steps_digest != owned_digest(self.authorized_steps_json)
            or len({row.step_id for row in self.rows}) != len(self.rows)
            or not children or len(set(children)) != len(children)
            or any(row.kind != "manual" for row in self.rows[:self.manual_prefix_length])
            or any(row.kind != "child" for row in self.rows[self.manual_prefix_length:])
            or len({op.operation_id for op in self.operations}) != len(self.operations)
            or len({attempt.effect_id for attempt in self.effect_attempts}) != len(self.effect_attempts)
            or (self.finalization is None) != (self.finalization_disposition is None)
        ):
            raise ValueError("owned_steps_control_invalid")
        for row, (start, end) in zip(visible, current):
            if row.todo_json != self.authorized_steps_json[start:end]:
                raise ValueError("owned_steps_projection_conflict")
        for row in self.rows:
            if row.permit is not None and (
                row.permit.parent_id != self.parent_id
                or row.permit.incarnation != self.incarnation
                or row.permit.plan_digest != self.plan_digest
                or row.permit.plan_revision != self.plan_revision
            ):
                raise ValueError("owned_steps_permit_invalid")
        if self.finalization is not None and (
            self.finalization.parent_id != self.parent_id or self.finalization.owner_kind != self.owner_kind
            or self.finalization.thread_id != self.thread_id or self.finalization.incarnation != self.incarnation
            or self.finalization.plan_digest != self.plan_digest
        ):
            raise ValueError("owned_steps_finalization_invalid")
        return self


class _ProjectionRevisions(_OwnedFormat):
    mode: OwnedStepsMode
    layout_revision: OwnedRevision
    observation_revision: OwnedRevision


class OwnedStepsControl(_ControlFields):
    version: Literal[2] = 2
    rows: Annotated[tuple[OwnedStepRecord, ...], Field(max_length=MAX_OWNED_ROWS)]

    @field_validator("rows", mode="wrap")
    @classmethod
    def _json_rows(cls, value: Any, handler: Any, info: ValidationInfo) -> tuple[OwnedStepRecord, ...]:
        if info.mode != "json" or type(value) is not list:
            return handler(value)
        if len(value) > MAX_OWNED_ROWS:
            raise ValueError("owned_steps_rows_invalid")
        # Only pure, context-free format validation is memoized, by exact JSON
        # content. Authorities, sources and journal claims are always rechecked
        # in the database transaction. Large rows do not occupy the bounded cache.
        rows = []
        for row in value:
            raw = json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            rows.append(
                _validated_owned_row(raw) if len(raw.encode("utf-8")) <= 4096
                else OwnedStepRecord.model_validate_json(raw)
            )
        return tuple(rows)

    @model_validator(mode="after")
    def _control(self) -> Self:
        original = owned_row_spans(self.original_steps_json)
        current = owned_row_spans(self.authorized_steps_json)
        owned_json_loads(self.gate_json)
        visible = self.rows[:self.manual_prefix_length] if self.mode == "awaiting_adoption" else self.rows
        children = [row.child.child_id for row in self.rows if row.child is not None]
        if (
            len(original) != self.manual_prefix_length or len(visible) != len(current)
            or self.steps_digest != owned_digest(self.authorized_steps_json)
            or len({row.step_id for row in self.rows}) != len(self.rows)
            or not children or len(set(children)) != len(children)
            or any(row.kind != "manual" for row in self.rows[:self.manual_prefix_length])
            or any(row.kind != "child" for row in self.rows[self.manual_prefix_length:])
            or (self.finalization is None) != (self.finalization_disposition is None)
        ):
            raise ValueError("owned_steps_control_invalid")
        for row, (start, end) in zip(visible, current):
            if row.todo_json != self.authorized_steps_json[start:end]:
                raise ValueError("owned_steps_projection_conflict")
        if self.finalization is not None and (
            self.finalization.parent_id != self.parent_id or self.finalization.owner_kind != self.owner_kind
            or self.finalization.thread_id != self.thread_id or self.finalization.incarnation != self.incarnation
            or self.finalization.plan_digest != self.plan_digest
        ):
            raise ValueError("owned_steps_finalization_invalid")
        return self

    def current_manual_prefix_json(self) -> str:
        """Return current manual bytes without the appended child suffix."""
        raw = self.authorized_steps_json
        if self.mode == "awaiting_adoption":
            return raw
        spans = owned_row_spans(raw)
        first_child = spans[self.manual_prefix_length][0]
        boundary = (
            raw.index(",", spans[self.manual_prefix_length - 1][1], first_child)
            if self.manual_prefix_length
            else first_child
        )
        return raw[:boundary] + raw[raw.rfind("]"):]

    def with_projection(
        self, *, rows: tuple[OwnedStepRecord, ...], projection: str,
        mode: OwnedStepsMode, layout_revision: int,
    ) -> OwnedStepsControl:
        """Validate a projection delta over immutable, already validated rows."""
        return self.prepare_projection(
            rows=rows, projection=projection, mode=mode, layout_revision=layout_revision,
        )[0]

    def prepare_projection(
        self, *, rows: tuple[OwnedStepRecord, ...], projection: str,
        mode: OwnedStepsMode, layout_revision: int,
    ) -> tuple[OwnedStepsControl, str]:
        """Validate a projection delta and retain its exact persistence encoding."""
        if type(rows) is not tuple or len(rows) != len(self.rows):
            raise OwnedStepsError("owned_steps_rows_invalid", parent_id=self.parent_id)
        revisions = _ProjectionRevisions(
            mode=mode, layout_revision=layout_revision, observation_revision=self.observation_revision + 1,
        )
        validated = []
        for previous, row in zip(self.rows, rows):
            if row is previous:
                validated.append(previous)
            elif type(row) is OwnedStepRecord:
                validated.append(OwnedStepRecord.model_validate_json(row.model_dump_json()))
            else:
                raise OwnedStepsError("owned_steps_rows_invalid", parent_id=self.parent_id)
        candidate = self.model_copy(update={
            **revisions.model_dump(), "rows": tuple(validated), "authorized_steps_json": projection,
            "steps_digest": owned_digest(projection),
        })
        candidate._control()
        # All leaves are validated above or retained immutable from self. Check
        # the actual encoded envelope once, rather than rewalking every sibling.
        encoded = candidate.model_dump_json()
        if len(encoded.encode("utf-8")) > MAX_OWNED_MANIFEST_BYTES:
            raise OwnedStepsError("owned_steps_manifest_too_large", parent_id=self.parent_id)
        _remember_validated_control(encoded, candidate)
        return candidate, encoded

    def with_finalization(
        self, *, receipt: FinalizeReceipt,
        disposition: Literal["pending", "completed"], mode: OwnedStepsMode,
        parent_source_digest: str | None = None,
    ) -> OwnedStepsControl:
        """Bind an immutable finalization receipt without touching plan rows.

        Only the finalization vector, disposition, mode and the monotonic
        observation revision move; every immutable row/plan field is retained
        so ``_control()`` re-checks the receipt binds this exact plan.
        """
        candidate = self.model_copy(update={
            "finalization": receipt, "finalization_disposition": disposition,
            "mode": mode, "observation_revision": self.observation_revision + 1,
            "parent_source_digest": parent_source_digest or self.parent_source_digest,
        })
        candidate._control()
        encoded = candidate.model_dump_json()
        if len(encoded.encode("utf-8")) > MAX_OWNED_MANIFEST_BYTES:
            raise OwnedStepsError("owned_steps_manifest_too_large", parent_id=self.parent_id)
        _remember_validated_control(encoded, candidate)
        return candidate


def owned_source_review_digest(control: OwnedStepsControl) -> str:
    """Digest the exact per-child execution + review vector a receipt freezes.

    A finalize receipt binds this value; recomputing it at finalize/recovery
    detects any late submission, review or projection change as a conflict
    rather than laundering a stale receipt over advanced state.
    """
    vector = [
        [row.step_id, row.source_digest, row.submission, row.reviewed_result,
         row.review_accepted, row.permit_state]
        for row in control.rows if row.child is not None
    ]
    return owned_digest(owned_json_bytes({
        "parent_id": control.parent_id,
        "incarnation": control.incarnation,
        "thread_id": control.thread_id,
        "plan_digest": control.plan_digest,
        "vector": vector,
    }))


class OwnedStepsRepairControl(_OwnedFormat):
    version: Literal[2] = 2
    mode: Literal["repair_required"] = "repair_required"
    parent_id: OwnedId
    incarnation: OwnedId
    owner_kind: Literal["canonical", "legacy"]
    thread_id: OwnedThreadId
    facilitator_id: OwnedId | None
    plan_digest: OwnedDigest
    child_ids: tuple[OwnedId, ...]
    archived_control: OwnedDigest
    original_steps_digest: OwnedDigest
    steps_digest: OwnedDigest

    @model_validator(mode="after")
    def _scope(self) -> Self:
        if self.owner_kind == "canonical" and (not self.thread_id or self.facilitator_id is None):
            raise ValueError("owned_steps_canonical_scope_invalid")
        return self


def parse_inline_owned_control(raw: str) -> InlineOwnedStepsControl:
    original = owned_json_loads(raw)
    try:
        control = InlineOwnedStepsControl.model_validate_json(raw)
        if original != control.model_dump(mode="json"):
            raise ValueError("owned_steps_control_incomplete")
        return control
    except ValueError as exc:
        raise OwnedStepsError("owned_steps_control_invalid") from exc


def _validated_control(raw: str) -> OwnedStepsControl | OwnedStepsRepairControl:
    original = owned_json_loads(raw)
    try:
        if type(original) is not dict:
            raise ValueError("owned_steps_control_invalid")
        # JSON strict validation accepts arrays for immutable tuple fields, but
        # does not coerce strings/bools into numeric revisions.
        model = OwnedStepsRepairControl if original.get("mode") == "repair_required" else OwnedStepsControl
        control = model.model_validate_json(raw)
        if original != control.model_dump(mode="json"):
            raise ValueError("owned_steps_control_incomplete")
        return control
    except (ValueError, ValidationError) as exc:
        raise OwnedStepsError("owned_steps_control_invalid") from exc


_CONTROL_FORMATS: OrderedDict[str, OwnedStepsControl | OwnedStepsRepairControl] = OrderedDict()
_CONTROL_FORMAT_LOCK = Lock()


def _remember_validated_control(raw: str, control: OwnedStepsControl | OwnedStepsRepairControl) -> None:
    with _CONTROL_FORMAT_LOCK:
        _CONTROL_FORMATS[raw] = control
        _CONTROL_FORMATS.move_to_end(raw)
        while len(_CONTROL_FORMATS) > 4:
            _CONTROL_FORMATS.popitem(last=False)


def parse_owned_control(raw: str) -> OwnedStepsControl | OwnedStepsRepairControl:
    """Reuse only byte-identical immutable formats, never a database observation."""
    if type(raw) is not str:
        raise OwnedStepsError("owned_steps_control_invalid")
    with _CONTROL_FORMAT_LOCK:
        cached = _CONTROL_FORMATS.get(raw)
        if cached is not None:
            _CONTROL_FORMATS.move_to_end(raw)
            return cached
    control = _validated_control(raw)
    _remember_validated_control(raw, control)
    return control


_SNAPSHOT_SOURCE_DIGESTS: OrderedDict[str, str] = OrderedDict()
_SNAPSHOT_SOURCE_LOCK = Lock()


def owned_snapshot_source_digest(control: OwnedStepsControl | str) -> str:
    """Digest a source projection; memoize only exact, strictly validated bytes."""
    raw = control if type(control) is str else None
    if raw is not None:
        control = parse_owned_control(raw)
    if isinstance(control, OwnedStepsRepairControl):
        raise OwnedStepsError("owned_steps_repair_required", parent_id=control.parent_id)
    if not isinstance(control, OwnedStepsControl):
        raise OwnedStepsError("owned_steps_control_invalid")
    if raw is not None:
        with _SNAPSHOT_SOURCE_LOCK:
            cached = _SNAPSHOT_SOURCE_DIGESTS.get(raw)
            if cached is not None:
                _SNAPSHOT_SOURCE_DIGESTS.move_to_end(raw)
                return cached
    sources = [[row.step_id, row.revision, row.digest, row.source_digest] for row in control.rows]
    digest = owned_digest(owned_json_bytes({
        "parent": control.parent_source_digest, "rows": sources, "gate": control.gate_json,
    }))
    if raw is not None:
        with _SNAPSHOT_SOURCE_LOCK:
            _SNAPSHOT_SOURCE_DIGESTS[raw] = digest
            _SNAPSHOT_SOURCE_DIGESTS.move_to_end(raw)
            while len(_SNAPSHOT_SOURCE_DIGESTS) > 4:
                _SNAPSHOT_SOURCE_DIGESTS.popitem(last=False)
    return digest


class OwnedStepsPlanToken(_OwnedFormat):
    parent_id: OwnedId
    incarnation: OwnedId
    layout_revision: OwnedRevision
    plan_revision: OwnedRevision
    plan_digest: OwnedDigest
    steps_digest: OwnedDigest
    source_digest: OwnedDigest
    actor_id: OwnedId
    thread_id: OwnedThreadId
    view_id: OwnedId
    turn_id: OwnedId


class StepViewToken(_OwnedFormat):
    parent_id: OwnedId
    incarnation: OwnedId
    layout_revision: OwnedRevision
    plan_revision: OwnedRevision
    plan_digest: OwnedDigest
    step_id: OwnedId
    row_revision: OwnedRevision
    row_digest: OwnedDigest
    source_digest: OwnedDigest | None
    assignment_epoch: OwnedRevision
    actor_id: OwnedId
    thread_id: OwnedThreadId
    view_id: OwnedId
    turn_id: OwnedId


@dataclass(frozen=True)
class OwnedStepsSnapshot:
    control: OwnedStepsControl
    source_digest: str
    projection_matches: bool = True


class OwnedStepViewEvidence(_OwnedFormat):
    permit_state: Literal[
        "unstarted", "started", "submitted", "terminal", "revoked", "interrupted"
    ]
    assignment_epoch: OwnedRevision
    booking_id: OwnedId | None
    has_submission: bool
    review_accepted: bool | None


class OwnedStepViewRow(_OwnedFormat):
    step_id: OwnedId
    ordinal: Annotated[int, Field(ge=1, le=MAX_OWNED_ROWS)]
    kind: Literal["manual", "child"]
    child_id: OwnedId | None
    revision: OwnedRevision
    digest: OwnedDigest
    todo: OwnedTodo
    actions: tuple[str, ...]
    evidence: OwnedStepViewEvidence
    token: StepViewToken | None
    detail_url: str | None = None


class OwnedStepsView(_OwnedFormat):
    version: Literal[1] = 1
    parent_id: OwnedId
    requested_item_id: OwnedId
    actor_id: OwnedId
    thread_id: OwnedThreadId
    turn_id: OwnedId
    view_id: OwnedId
    mode: OwnedStepsMode
    layout_revision: OwnedRevision
    plan_revision: OwnedRevision
    plan_digest: OwnedDigest
    steps_digest: OwnedDigest
    source_digest: OwnedDigest
    plan_token: OwnedStepsPlanToken | None
    rows: Annotated[tuple[OwnedStepViewRow, ...], Field(max_length=MAX_OWNED_VIEW_ROWS)]
    previous_cursor: str | None = None
    next_cursor: str | None = None
    omitted_step_ids: tuple[OwnedId, ...] = ()
    recovery: tuple[str, ...] = ()
    finalization: Literal["none", "pending", "completed", "conflict"]


class OwnedStepsViewReference(_OwnedFormat):
    version: Literal[1] = 1
    parent_id: OwnedId
    actor_id: OwnedId
    thread_id: OwnedThreadId
    turn_id: OwnedId
    view_id: OwnedId
    content_hash: OwnedDigest

    @model_validator(mode="after")
    def _reference_size(self) -> Self:
        if len(owned_json_bytes(self.model_dump(mode="json"))) > MAX_OWNED_VIEW_REFERENCE_BYTES:
            raise ValueError("owned_steps_view_reference_too_large")
        return self


ViewReference = OwnedStepsViewReference


class RepairReference(_OwnedFormat):
    version: Literal[1] = 1
    parent_id: OwnedId
    actor_id: OwnedId
    thread_id: OwnedThreadId
    turn_id: OwnedId
    view_id: OwnedId
    content_hash: OwnedDigest
    observation_id: OwnedId

    @model_validator(mode="after")
    def _reference_size(self) -> Self:
        if len(owned_json_bytes(self.model_dump(mode="json"))) > MAX_OWNED_VIEW_REFERENCE_BYTES:
            raise ValueError("owned_steps_repair_reference_too_large")
        return self


class ProposalReference(_OwnedFormat):
    version: Literal[1] = 1
    parent_id: OwnedId
    actor_id: OwnedId
    thread_id: OwnedThreadId
    turn_id: OwnedId
    view_id: OwnedId
    content_hash: OwnedDigest
    proposal_id: OwnedId
    manifest_digest: OwnedDigest

    @model_validator(mode="after")
    def _reference_size(self) -> Self:
        if len(owned_json_bytes(self.model_dump(mode="json"))) > MAX_OWNED_VIEW_REFERENCE_BYTES:
            raise ValueError("owned_steps_proposal_reference_too_large")
        return self


class ProposalLocator(_OwnedFormat):
    version: Literal[1] = 1
    parent_id: OwnedId
    proposal_id: OwnedId
    manifest_digest: OwnedDigest

    @model_validator(mode="after")
    def _reference_size(self) -> Self:
        if len(owned_json_bytes(self.model_dump(mode="json"))) > MAX_OWNED_VIEW_REFERENCE_BYTES:
            raise ValueError("owned_steps_proposal_locator_too_large")
        return self


class ProposalPreparation(_OwnedFormat):
    version: Literal[1] = 1
    parent_id: OwnedId
    preparation_id: OwnedId
    request_digest: OwnedDigest
    observation_id: OwnedId
    kind: Literal["adopt_existing", "replace_manual_prefix", "replan_unstarted"]


@dataclass(frozen=True)
class RepairObservation:
    observation_id: str
    parent_id: str
    actor_id: str
    thread_id: str
    raw_steps: str | None
    raw_control: str | None
    steps_digest: str
    control_digest: str | None
    source_manifest: str
    source_digest: str
    created_at: float


@dataclass(frozen=True)
class OwnedStepsRawIdentity:
    parent_id: str
    work_type: str
    status: str
    parent_id_value: str | None
    assigned_to: str | None
    created_by: str
    title: str
    description: str
    raw_metadata: str | None
    raw_steps: str | None
    raw_control: str | None


class ProposalManifest(_OwnedFormat):
    version: Literal[1] = 1
    kind: Literal["adopt_existing", "replace_manual_prefix", "replan_unstarted"]
    observation_id: OwnedId
    before_digest: OwnedDigest
    after_digest: OwnedDigest
    gate_completion: bool
    manual_count: OwnedCount
    child_count: OwnedCount
    retired_count: OwnedCount
    successor_incarnation: OwnedId | None = None
    successor_plan_digest: OwnedDigest | None = None
    successor_seed_digest: OwnedDigest | None = None
    before_prefix_json: str
    after_prefix_json: str
    suffix_json: tuple[str, ...] = ()
    proposed_control_json: str | None
    current_child_ids: tuple[OwnedId, ...] = ()
    proposed_children: tuple[dict[str, Any], ...] = ()
    retired_child_ids: tuple[OwnedId, ...] = ()
    cancelled_booking_ids: tuple[OwnedId, ...] = ()
    canonical_metadata_patch: dict[str, Any] | None = None
    original_spec_mapping: tuple[tuple[OwnedId, OwnedId], ...] = ()
    source_malformed: bool = False
    source_oversized: bool = False

    @model_validator(mode="after")
    def _manifest_shape(self) -> Self:
        if (
            len(set(self.current_child_ids)) != len(self.current_child_ids)
            or len(set(self.retired_child_ids)) != len(self.retired_child_ids)
            or len(self.proposed_children) > MAX_OWNED_ROWS
        ):
            raise ValueError("owned_steps_proposal_manifest_invalid")
        return self


class ProposalAcknowledgement(_OwnedFormat):
    version: Literal[1] = 1
    parent_id: OwnedId
    proposal_id: OwnedId
    operation_id: OwnedId
    kind: Literal["adopt_existing", "replace_manual_prefix", "replan_unstarted"]
    committed_at: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    incarnation: OwnedId
    plan_digest: OwnedDigest
    steps_digest: OwnedDigest


@dataclass(frozen=True)
class ProposalClaim:
    parent_id: str
    preparation_id: str
    proposal_id: str
    actor_id: str
    thread_id: str
    request_digest: str
    observation_id: str
    kind: Literal["adopt_existing", "replace_manual_prefix", "replan_unstarted"]
    state: Literal["preparing", "ready", "failed", "committed"]
    claim_nonce: str
    is_new: bool
    manifest_digest: str | None = None


@dataclass(frozen=True)
class ProposalRecord:
    claim: ProposalClaim
    manifest: ProposalManifest | None
    manifest_digest: str | None
    error_code: str | None
    apply_operation_id: str | None
    acknowledgement: str | None


class ProposalPage(_OwnedFormat):
    version: Literal[1] = 1
    proposal: ProposalLocator
    reference: ProposalReference | None
    kind: Literal["adopt_existing", "replace_manual_prefix", "replan_unstarted"]
    state: Literal["preparing", "ready", "failed", "committed"]
    before_digest: OwnedDigest | None
    after_digest: OwnedDigest | None
    gate_completion: bool | None
    manual_count: OwnedCount
    child_count: OwnedCount
    retired_count: OwnedCount
    rows: tuple[dict[str, Any], ...] = ()
    previous_cursor: str | None = None
    next_cursor: str | None = None
    coverage: dict[str, Any]
    omissions: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    error_code: str | None = None
    acknowledgement: dict[str, Any] | None = None


class AdoptExistingProposalRequest(_OwnedFormat):
    version: Literal[1] = 1
    kind: Literal["adopt_existing"] = "adopt_existing"
    preparation_id: OwnedId
    reference: ViewReference


class ReplaceManualPrefixProposalRequest(_OwnedFormat):
    version: Literal[1] = 1
    kind: Literal["replace_manual_prefix"] = "replace_manual_prefix"
    preparation_id: OwnedId
    reference: ViewReference | RepairReference
    prefix_json: str

    @model_validator(mode="after")
    def _prefix(self) -> Self:
        owned_row_spans(self.prefix_json)
        return self


class ReplanUnstartedProposalRequest(_OwnedFormat):
    version: Literal[1] = 1
    kind: Literal["replan_unstarted"] = "replan_unstarted"
    preparation_id: OwnedId
    reference: ViewReference | RepairReference


class InspectProposalRequest(_OwnedFormat):
    version: Literal[1] = 1
    kind: Literal["inspect_proposal"] = "inspect_proposal"
    proposal: ProposalLocator
    cursor: str | None = None


OwnedStepsProposalRequest = Annotated[
    AdoptExistingProposalRequest
    | ReplaceManualPrefixProposalRequest
    | ReplanUnstartedProposalRequest
    | InspectProposalRequest,
    Field(discriminator="kind"),
]


class OwnedStepsProposalApplyRequest(_OwnedFormat):
    version: Literal[1] = 1
    operation_id: OwnedId
    reference: ProposalReference


@dataclass(frozen=True)
class RetiredOwnedChild:
    child: WorkItem
    old_incarnation: str | None
    successor_incarnation: str
    proposal_id: str
    apply_operation_id: str
    child_snapshot_digest: str
    post_cancellation_source_digest: str


@dataclass(frozen=True)
class OwnedCrewChildren:
    parent_id: str
    incarnation: str
    plan_digest: str
    active: tuple[WorkItem, ...]
    retired: tuple[RetiredOwnedChild, ...]


class OwnedStepsActualContext:
    """Opaque, server-issued actor/thread/task/turn context."""

    __slots__ = ("_authority", "_owner", "parent_id", "actor_id", "thread_id", "turn_id")

    def __init__(
        self,
        *,
        authority: OwnedStepsAuthority,
        owner: object,
        parent_id: str,
        actor_id: str,
        thread_id: str,
        turn_id: str,
    ) -> None:
        self._authority = authority
        self._owner = owner
        self.parent_id = parent_id
        self.actor_id = actor_id
        self.thread_id = thread_id
        self.turn_id = turn_id

    def is_issued_by(self, owner: object) -> bool:
        return self._owner is owner

    def authority_for(self, owner: object) -> OwnedStepsAuthority:
        if self._owner is not owner:
            raise OwnedStepsError(
                "owned_steps_actual_context_invalid",
                parent_id=self.parent_id,
            )
        return self._authority

    def authority_for_operation(
        self,
        owner: object,
        *,
        operation: str,
        token: object = None,
        request_digest: str = "",
    ) -> OwnedStepsAuthority:
        authority = self.authority_for(owner)
        source = authority.context
        if type(source) is not OwnedOwnerInvocation:
            raise OwnedStepsError(
                "owned_steps_actual_context_invalid",
                parent_id=self.parent_id,
            )
        return OwnedStepsAuthority(
            OwnedOwnerInvocation(
                owner=source.owner,
                component=source.component,
                parent_id=self.parent_id,
                actor_id=self.actor_id,
                thread_id=self.thread_id,
                role=source.role,
                operation=operation,
                token=token,
                request_digest=request_digest,
            )
        )


class OwnedStepsHttpRowCommand(_OwnedFormat):
    operation_id: OwnedId
    step_id: OwnedId
    kind: Literal[
        "manual_submit",
        "manual_confirm",
        "manual_reject",
        "edit_note",
        "reassign_unstarted",
        "cancel_execution",
        "pause_accounting",
        "resume_accounting",
        "abandon",
    ]
    note: str | None = None
    assignee_id: OwnedId | None = None
    booking_id: OwnedId | None = None
    resource_id: OwnedId | None = None

    @model_validator(mode="after")
    def _command_shape(self) -> Self:
        supplied = self.model_fields_set
        expected = {
            "manual_submit": set(),
            "manual_confirm": set(),
            "manual_reject": {"note"},
            "edit_note": {"note"},
            "reassign_unstarted": {"assignee_id"},
            "cancel_execution": set(),
            "pause_accounting": {"booking_id", "resource_id"},
            "resume_accounting": {"booking_id", "resource_id"},
            "abandon": set(),
        }[self.kind]
        optional = {"operation_id", "step_id", "kind"}
        if not expected <= supplied or supplied - optional - expected:
            raise ValueError("owned_steps_command_invalid")
        if any(
            getattr(self, field) is None
            for field in expected & {"assignee_id", "booking_id", "resource_id"}
        ):
            raise ValueError("owned_steps_command_invalid")
        if self.kind == "manual_reject" and (self.note is None or not self.note.strip()):
            raise ValueError("owned_steps_rejection_note_required")
        return self


class OwnedStepsHttpPlanCommand(_OwnedFormat):
    operation_id: OwnedId
    kind: Literal["repair_projection"]
    observed_steps_digest: OwnedDigest


OwnedStepsHttpCommand = Annotated[
    OwnedStepsHttpRowCommand | OwnedStepsHttpPlanCommand,
    Field(discriminator="kind"),
]


class OwnedStepsCommandBatch(_OwnedFormat):
    version: Literal[1] = 1
    reference: OwnedStepsViewReference
    commands: Annotated[tuple[OwnedStepsHttpCommand, ...], Field(min_length=1, max_length=MAX_OWNED_VIEW_ROWS)]

    @model_validator(mode="after")
    def _non_contradictory(self) -> Self:
        row_ids = [
            command.step_id
            for command in self.commands
            if isinstance(command, OwnedStepsHttpRowCommand)
        ]
        plan_commands = [
            command
            for command in self.commands
            if isinstance(command, OwnedStepsHttpPlanCommand)
        ]
        if len(row_ids) != len(set(row_ids)) or len(plan_commands) > 1 or (
            plan_commands and len(self.commands) != 1
        ):
            raise ValueError("owned_steps_command_contradiction")
        return self


class OwnedStepsCommandsRequest(RootModel[OwnedStepsCommandBatch | OwnedStepsProposalApplyRequest]):
    pass


class OwnedStepsPreviewRequest(_OwnedFormat):
    version: Literal[1] = 1
    reference: OwnedStepsViewReference


class OwnedStepsAdoptRequest(_OwnedFormat):
    version: Literal[1] = 1
    reference: OwnedStepsViewReference
    operation_id: OwnedId
    preview: OwnedStepsAdoptionPreview


class OwnedStepsFinalizeRequest(_OwnedFormat):
    version: Literal[1] = 1
    reference: OwnedStepsViewReference


def render_owned_steps_feedback(error: OwnedStepsError) -> str:
    action_text = {
        "refresh": "Refresh the owned steps view.",
        "page": "Open the requested owned-steps page.",
        "detail": "Open the authenticated row detail.",
        "preview_adoption": "Preview adoption before applying it.",
        "owned_controls": "Use the owned-steps controls.",
        "inspect_source": "Inspect the preserved source and evidence.",
        "replace_manual_prefix": "Preview an exact manual-prefix correction.",
        "repair_projection": "Repair the projection from the authorized snapshot.",
        "interrupted_work": "Inspect interrupted work before abandoning it.",
        "manual_gate": "Complete the remaining manual gate.",
        "replan_unstarted": "Use the persisted planner proposal for unstarted work.",
        "view_budget": "Request a smaller page or authenticated row detail.",
        "finalize": "Retry exact-receipt finalization.",
    }
    guidance = " ".join(
        action_text[action]
        for action in error.actions
        if action in action_text
    )
    prefix = f"Owned steps refused ({error.code}): {error.message}."
    return f"{prefix} {guidance}".strip()


@dataclass(frozen=True)
class OwnedStepsAuthority:
    """Opaque dispatch/HTTP/owner context, resolved by the injected authorizer."""
    context: object


@dataclass(frozen=True)
class OwnedStepsGrant:
    parent_id: str
    actor_id: str
    thread_id: str
    role: Literal["captain", "facilitator", "reader", "executor", "verifier", "ttl", "owner"]


@dataclass(frozen=True)
class OwnedStoreBinding:
    snapshot: OwnedStepsSnapshot
    operation: Literal[
        "metadata",
        "assignment",
        "verification",
        "publication",
        "steps_finalize",
        "terminal",
    ]
    request_digest: str
    authority: OwnedStepsAuthority
    step_id: str | None = None
    reviewed_result: ReviewedStepResult | None = None
    finalize_receipt: FinalizeReceipt | None = None
    unassessed_checkpoint: UnassessedStepCheckpoint | None = None


@dataclass(frozen=True, eq=False)
class OwnedOwnerInvocation:
    """Server-held invocation identity. Never a request/body or actor-string grant."""
    owner: object
    component: object
    parent_id: str
    actor_id: str
    thread_id: str
    role: Literal[
        "captain",
        "facilitator",
        "reader",
        "owner",
        "executor",
        "verifier",
        "ttl",
    ]
    operation: str
    token: object
    request_digest: str = ""


class OwnedStepsSeedPlan(_OwnedFormat):
    parent_id: OwnedId
    owner_kind: Literal["canonical", "legacy"]
    thread_id: OwnedThreadId
    facilitator_id: OwnedId | None
    incarnation: OwnedId
    plan_digest: OwnedDigest
    expected_steps_digest: OwnedDigest
    children: Annotated[tuple[OwnedStepChild, ...], Field(min_length=1, max_length=MAX_OWNED_ROWS)]

    @model_validator(mode="after")
    def _unique_children(self) -> Self:
        if self.owner_kind == "canonical" and (not self.thread_id or self.facilitator_id is None):
            raise ValueError("owned_steps_canonical_scope_invalid")
        if len({child.child_id for child in self.children}) != len(self.children) or (
            len({child.spec_id for child in self.children}) != len(self.children)
        ):
            raise ValueError("owned_steps_seed_invalid")
        return self


@dataclass(frozen=True)
class OwnedStepsSeed:
    plan: OwnedStepsSeedPlan
    authority: OwnedStepsAuthority


class OwnedStepsAdoptionPreview(_OwnedFormat):
    token: OwnedStepsPlanToken
    prefix_json: str
    suffix_json: tuple[str, ...]
    children: tuple[OwnedStepChild, ...]
    gate_json: str
    preview_digest: OwnedDigest


class ManualStepCommand(_OwnedFormat):
    kind: Literal["manual_submit", "manual_confirm", "manual_reject", "edit_note"]
    note: str | None = None

    @model_validator(mode="after")
    def _edit_note(self) -> Self:
        if self.kind == "edit_note" and "note" not in self.model_fields_set:
            raise ValueError("owned_steps_note_required")
        return self


class StartOwnedStepCommand(_OwnedFormat):
    kind: Literal["admit_execution"] = "admit_execution"
    execution_nonce: OwnedId


class SubmitOwnedStepCommand(_OwnedFormat):
    kind: Literal["submit_execution"] = "submit_execution"
    submission: OwnedStepSubmission | OwnedExecutionSubmission


class UnstartedOwnedStepCommand(_OwnedFormat):
    kind: Literal["record_unstarted_execution"] = "record_unstarted_execution"
    submission: OwnedUnstartedSubmission


class ReviewOwnedStepCommand(_OwnedFormat):
    kind: Literal["record_review"] = "record_review"
    result: ReviewedStepResult


class ReassignOwnedStepCommand(_OwnedFormat):
    kind: Literal["reassign_unstarted"] = "reassign_unstarted"
    assignee_id: OwnedId
    metadata_patch: dict[str, Any] = Field(default_factory=dict)


class CancelOwnedStepCommand(_OwnedFormat):
    kind: Literal["cancel_execution"] = "cancel_execution"
    expired_item_id: OwnedId | None = None
    observed_at: Annotated[float, Field(ge=0)] | None = None


class AbandonOwnedStepCommand(_OwnedFormat):
    kind: Literal["abandon"] = "abandon"


class AccountingOwnedStepCommand(_OwnedFormat):
    kind: Literal["pause_accounting", "resume_accounting"]
    booking_id: OwnedId
    resource_id: OwnedId


class AdoptOwnedStepsCommand(_OwnedFormat):
    kind: Literal["adopt"] = "adopt"
    preview: OwnedStepsAdoptionPreview


class RepairOwnedStepsCommand(_OwnedFormat):
    kind: Literal["repair_projection"] = "repair_projection"
    observed_steps_digest: OwnedDigest


OwnedStepsCommand = Annotated[
    ManualStepCommand | StartOwnedStepCommand | SubmitOwnedStepCommand | ReviewOwnedStepCommand | UnstartedOwnedStepCommand
    | ReassignOwnedStepCommand | CancelOwnedStepCommand | AbandonOwnedStepCommand | AccountingOwnedStepCommand
    | AdoptOwnedStepsCommand | RepairOwnedStepsCommand,
    # Review here is only a storage receipt; M2 still owns verifier execution.
    Field(discriminator="kind"),
]


class OwnedStepChange(_OwnedFormat):
    operation_id: OwnedId
    token: StepViewToken | OwnedStepsPlanToken | OwnedStepExecutionPermit
    command: OwnedStepsCommand


@dataclass(frozen=True)
class OwnedStepMutation:
    change: OwnedStepChange
    authority: OwnedStepsAuthority


@dataclass(frozen=True)
class OwnedStepMutationResult:
    snapshot: OwnedStepsSnapshot | None
    disposition: Literal["applied", "new", "already_started", "terminal", "duplicate"]
    permit: OwnedStepExecutionPermit | None = None
    receipt: OwnedOperationReceipt | None = None
    proposal_acknowledgement: ProposalAcknowledgement | None = None


@dataclass(frozen=True)
class OwnedExecutionLease:
    snapshot: OwnedStepsSnapshot
    authority: OwnedStepsAuthority


def execution_step_token(lease: OwnedExecutionLease, row: OwnedStepRecord) -> StepViewToken:
    control = lease.snapshot.control
    return StepViewToken(
        parent_id=control.parent_id, incarnation=control.incarnation,
        layout_revision=control.layout_revision, plan_revision=control.plan_revision,
        plan_digest=control.plan_digest, step_id=row.step_id, row_revision=row.revision,
        row_digest=row.digest, source_digest=row.source_digest, assignment_epoch=row.assignment_epoch,
        actor_id=row.assignee_id or control.parent_id, thread_id=control.thread_id,
        view_id="execution", turn_id=control.incarnation,
    )


@dataclass(frozen=True)
class OwnedFinalization:
    """One manager-authorized finalize step against an exact frozen receipt.

    ``phase`` separates the durable ``bind`` (receipt pending, before any legacy
    effect claim) from the ``complete`` close.  ``complete`` also binds when no
    prior pending receipt exists, so finalize-only recovery is a single call.
    """
    token: OwnedStepsPlanToken
    receipt: FinalizeReceipt
    source_review_digest: OwnedDigest
    phase: Literal["bind", "complete"]
    authority: OwnedStepsAuthority
    manual_gate: bool = False


@dataclass(frozen=True)
class OwnedFinalizationResult:
    snapshot: OwnedStepsSnapshot
    disposition: Literal["pending", "completed"]
    committed: bool


class OwnedStepsExecutionPort(Protocol):
    def owns_store(self, store: object) -> bool: ...

    async def admit(
        self, parent_id: str, *, children: tuple[WorkItem, ...], thread_id: str,
    ) -> OwnedExecutionLease: ...

    async def start(
        self, lease: OwnedExecutionLease, child_id: str, *, execution_nonce: str,
    ) -> OwnedStepMutationResult: ...

    async def submit(
        self, lease: OwnedExecutionLease, submission: OwnedExecutionSubmission,
    ) -> OwnedStepMutationResult: ...

    async def validate(self, lease: OwnedExecutionLease, permit: OwnedStepExecutionPermit) -> None: ...

    async def record_unstarted(
        self, lease: OwnedExecutionLease, submission: OwnedUnstartedSubmission,
    ) -> OwnedStepMutationResult: ...

    async def admit_correction(
        self,
        component: object,
        snapshot: OwnedStepsSnapshot,
        child_id: str,
        *,
        reviewer_id: str,
        review_attempt_id: str,
        execution_nonce: str,
    ) -> OwnedStepMutationResult: ...

    async def record_correction(
        self,
        component: object,
        snapshot: OwnedStepsSnapshot,
        correction: OwnedCorrectionResult,
    ) -> OwnedStepMutationResult: ...

    async def read_correction(
        self,
        snapshot: OwnedStepsSnapshot,
        permit: OwnedStepExecutionPermit,
    ) -> OwnedCorrectionResult | None: ...


@dataclass(frozen=True)
class OwnedEffectClaim:
    token: OwnedStepsPlanToken
    attempt: OwnedEffectAttempt
    authority: OwnedStepsAuthority


@dataclass(frozen=True)
class OwnedEffectClaimResult:
    attempt: OwnedEffectAttempt
    created: bool


class OwnedStepsAuthorizer(Protocol):
    async def authorize_owned_steps(
        self, authority: OwnedStepsAuthority, *, parent_id: str, operation: str,
        token: StepViewToken | OwnedStepsPlanToken | OwnedStepExecutionPermit | None,
    ) -> OwnedStepsGrant: ...


class OwnedStoreAuthorizer(Protocol):
    async def authorize_owned_store_write(self, binding: OwnedStoreBinding) -> OwnedStepsGrant: ...


class OwnedStepsTTLOwner(Protocol):
    async def expire_owned_steps(self, work_item_id: str, observed_at: float) -> bool: ...


class OwnedStepsContinuationOwner(Protocol):
    async def owned_manual_gate_released(self, parent_id: str) -> None: ...


class OwnedStepsContentReader(Protocol):
    async def read(self, content_hash: str) -> bytes | None: ...


class OwnedStepsStore(Protocol):
    async def get_owned_steps(self, parent_id: str) -> OwnedStepsSnapshot | None: ...

    async def compare_and_set_owned_step(
        self, mutation: OwnedStepMutation,
    ) -> OwnedStepMutationResult: ...

    async def compare_and_set_owned_steps_batch(
        self, mutations: tuple[OwnedStepMutation, ...],
    ) -> tuple[OwnedStepMutationResult, ...]: ...

    async def get_owned_crew_children(
        self,
        parent_id: str,
        expected_plan: OwnedStepsSeedPlan | str | None = None,
    ) -> OwnedCrewChildren: ...

    async def capture_owned_steps_repair_observation(
        self,
        parent_id: str,
        authority: OwnedStepsAuthority,
    ) -> RepairObservation: ...

    async def claim_owned_steps_proposal(
        self,
        preparation: ProposalPreparation,
        authority: OwnedStepsAuthority,
    ) -> ProposalClaim: ...

    async def publish_owned_steps_proposal(
        self,
        claim: ProposalClaim,
        manifest: ProposalManifest,
        authority: OwnedStepsAuthority,
    ) -> ProposalLocator: ...

    async def get_owned_steps_proposal(
        self,
        locator: ProposalLocator,
        authority: OwnedStepsAuthority,
    ) -> ProposalRecord: ...

    async def apply_owned_steps_proposal(
        self,
        approval: OwnedStepsProposalApplyRequest,
        authority: OwnedStepsAuthority,
    ) -> OwnedStepMutationResult: ...


class OwnedStepsViewResolver(Protocol):
    async def resolve_owned_steps_view(
        self,
        reference: OwnedStepsViewReference,
        actual_context: OwnedStepsActualContext,
    ) -> OwnedStepsView: ...

    async def admit_owned_steps_presentation(
        self,
        reference: OwnedStepsViewReference,
        actual_context: OwnedStepsActualContext,
    ) -> OwnedStepsView: ...

    async def expire_owned_steps_views(
        self,
        actual_context: OwnedStepsActualContext,
        *,
        view_id: str | None = None,
    ) -> int: ...
