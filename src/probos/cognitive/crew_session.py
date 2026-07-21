"""AD-1124: durable CrewSession contract and storage service."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

if TYPE_CHECKING:
    from probos.threads import ChatThread
    from probos.workforce import WorkItem, WorkItemPlanInsert

logger = logging.getLogger(__name__)

CrewSessionState = Literal[
    "discussing",
    "executing",
    "verifying",
    "blocked_needs_captain",
    "done",
    "failed",
]
CrewSessionOrigin = Literal["captain", "agent"]
CrewRecoveryPhase = Literal[
    "unplanned",
    "planned",
    "executing",
    "verifying_children",
    "children_verified",
    "synthesized",
    "final_verified",
    "artifact_bound",
    "provenance_bound",
    "published",
]

_STATES = frozenset(
    {
        "discussing",
        "executing",
        "verifying",
        "blocked_needs_captain",
        "done",
        "failed",
    }
)
_TERMINAL_STATES = frozenset({"done", "failed"})
_TRANSITIONS = {
    "discussing": frozenset({"executing", "blocked_needs_captain", "failed"}),
    "executing": frozenset({"verifying", "blocked_needs_captain", "failed"}),
    "verifying": frozenset({"done", "blocked_needs_captain", "failed"}),
    "blocked_needs_captain": frozenset({"discussing", "executing", "failed"}),
    "done": frozenset(),
    "failed": frozenset(),
}
_STATUS_PROJECTION: dict[str, str] = {
    "discussing": "open",
    "executing": "in_progress",
    "verifying": "review",
    "blocked_needs_captain": "blocked",
    "done": "done",
    "failed": "failed",
}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_TIMESTAMP = 253_402_300_799.0
_MAX_BLOCKED_SECONDS = 315_576_000.0
_MAX_CONTRACT_BYTES = 32_768
_MAX_SYNTHESIS_METADATA_BYTES = 32_768
_MAX_SESSION_TOKEN_TOTAL = 9_223_372_036_854_775_807
_MAX_RECOVERY_BYTES = 524_288
_MAX_RECOVERY_CHILDREN = 1_000
_MAX_RECOVERY_INTERRUPTED_CHILDREN = 64
_MAX_PLAN_PROJECTION_BYTES = 131_072
_MAX_PLAN_ARRAY_BYTES = 524_288
_MAX_PLAN_METADATA_BYTES = 65_536
_MAX_PLAN_METADATA_DEPTH = 8
_MAX_PLAN_METADATA_NODES = 4_096
_MAX_PLAN_METADATA_STRING = 32_768
_MAX_PLAN_SPECS = 200
_JSON_INT_MIN = -(2**63)
_JSON_INT_MAX = 2**63 - 1
_PLAN_POLICIES = ("derived_v1", "adopted_v1")
_PLAN_RESERVED_METADATA_KEYS = frozenset({
    "spec_id",
    "resources",
    "expected_output",
    "capability",
    "department",
    "chief_agent_id",
    "order_id",
    "delegated",
    "delegation_reason",
    "assigned_capability",
    "assigned_department",
    "crew_execution",
    "crew_execution_output",
    "crew_verification_recovery",
})
_PLAN_ASSIGNMENT_KEYS = frozenset({
    "chief_agent_id",
    "order_id",
    "delegated",
    "delegation_reason",
    "assigned_capability",
    "assigned_department",
})
_PLAN_EXECUTION_KEYS = frozenset({
    "version",
    "parent_id",
    "work_item_id",
    "thread_id",
    "assigned_to",
    "status",
    "stopped_reason",
    "output_summary",
    "tool_trace_ref",
    "artifact_refs",
    "tokens_used",
    "started_at",
    "finished_at",
    "blocked_dependency_ids",
})
_RECOVERY_PHASE_INDEX = {
    phase: index
    for index, phase in enumerate(
        (
            "unplanned",
            "planned",
            "executing",
            "verifying_children",
            "children_verified",
            "synthesized",
            "final_verified",
            "artifact_bound",
            "provenance_bound",
            "published",
        )
    )
}
_RECOVERY_ERROR_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,127}$")
_MISSING = object()
_DISCUSSING_RECOVERY_PHASES = frozenset({"unplanned", "planned"})
_VERIFYING_RECOVERY_PHASES = frozenset({
    "verifying_children",
    "children_verified",
    "synthesized",
    "final_verified",
    "artifact_bound",
    "provenance_bound",
})


class CrewRecoveryTransientError(RuntimeError):
    """A narrowly classified retryable CrewSession recovery boundary error."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or _RECOVERY_ERROR_RE.fullmatch(code) is None:
            raise ValueError("crew_recovery_error_code_invalid")
        super().__init__(code)
        self.code = code


class CrewRecoveryPlanChild(BaseModel):
    """One compact immutable child commitment in a durable recovery plan."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    child_id: str
    spec_id: str
    row_hash: str

    @field_validator("child_id", "spec_id", mode="before")
    @classmethod
    def _validate_plan_id(cls, value: Any) -> str:
        return _normalize_id(value)

    @field_validator("row_hash", mode="before")
    @classmethod
    def _validate_row_hash(cls, value: Any) -> str:
        return _normalize_sha(value)


class CrewRecoveryPlan(BaseModel):
    """Strict ordered child plan committed with the CrewSession parent."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: Literal[1]
    plan_seed_hash: str
    plan_hash: str
    children: tuple[CrewRecoveryPlanChild, ...]

    @field_validator("version", mode="before")
    @classmethod
    def _validate_plan_version(cls, value: Any) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("crew_recovery_plan_version_invalid")
        return value

    @field_validator("plan_seed_hash", "plan_hash", mode="before")
    @classmethod
    def _validate_plan_hash(cls, value: Any) -> str:
        return _normalize_sha(value)

    @field_validator("children", mode="before")
    @classmethod
    def _validate_plan_children(cls, value: Any) -> tuple[Any, ...]:
        if type(value) is not list or not 1 <= len(value) <= _MAX_RECOVERY_CHILDREN:
            raise ValueError("crew_recovery_plan_children_invalid")
        return tuple(value)

    @model_validator(mode="after")
    def _validate_plan_consistency(self) -> Self:
        child_ids = tuple(child.child_id for child in self.children)
        spec_ids = tuple(child.spec_id for child in self.children)
        if len(set(child_ids)) != len(child_ids) or len(set(spec_ids)) != len(spec_ids):
            raise ValueError("crew_recovery_plan_children_invalid")
        return self


class CrewRecoveryContract(BaseModel):
    """Strict bounded fine-grained restart checkpoint for one CrewSession."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: Literal[1]
    phase: CrewRecoveryPhase
    plan: CrewRecoveryPlan | None
    attempt_count: int
    retry_count: int
    last_attempt_at: float | None
    next_attempt_at: float | None
    last_error_code: str | None
    interrupted_child_ids: tuple[str, ...]
    synthesis_ref: str | None
    final_verification_ref: str | None
    result_artifact_id: str | None
    provenance_ref: str | None

    @field_validator("version", mode="before")
    @classmethod
    def _validate_recovery_version(cls, value: Any) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("crew_recovery_version_invalid")
        return value

    @field_validator("attempt_count", mode="before")
    @classmethod
    def _validate_attempt_count(cls, value: Any) -> int:
        if type(value) is not int or not 0 <= value <= 1_000_000:
            raise ValueError("crew_recovery_attempt_count_invalid")
        return value

    @field_validator("retry_count", mode="before")
    @classmethod
    def _validate_retry_count(cls, value: Any) -> int:
        if type(value) is not int or not 0 <= value <= 10:
            raise ValueError("crew_recovery_retry_count_invalid")
        return value

    @field_validator("last_attempt_at", "next_attempt_at", mode="before")
    @classmethod
    def _validate_recovery_timestamp(cls, value: Any) -> float | None:
        if value is None:
            return None
        return _normalize_timestamp(value)

    @field_validator("last_error_code", mode="before")
    @classmethod
    def _validate_error_code(cls, value: Any) -> str | None:
        if value is None:
            return None
        if type(value) is not str or _RECOVERY_ERROR_RE.fullmatch(value) is None:
            raise ValueError("crew_recovery_error_code_invalid")
        return value

    @field_validator("interrupted_child_ids", mode="before")
    @classmethod
    def _validate_interrupted_children(cls, value: Any) -> tuple[str, ...]:
        if type(value) is not list or len(value) > _MAX_RECOVERY_INTERRUPTED_CHILDREN:
            raise ValueError("crew_recovery_interrupted_children_invalid")
        normalized = tuple(_normalize_id(item) for item in value)
        if normalized != tuple(sorted(set(normalized))):
            raise ValueError("crew_recovery_interrupted_children_invalid")
        return normalized

    @field_validator(
        "synthesis_ref",
        "final_verification_ref",
        "provenance_ref",
        mode="before",
    )
    @classmethod
    def _validate_recovery_ref(cls, value: Any) -> str | None:
        return None if value is None else _normalize_sha(value)

    @field_validator("result_artifact_id", mode="before")
    @classmethod
    def _validate_recovery_artifact_id(cls, value: Any) -> str | None:
        return None if value is None else _normalize_id(value)

    @model_validator(mode="after")
    def _validate_recovery_consistency(self) -> Self:
        phase_index = _RECOVERY_PHASE_INDEX[self.phase]
        if (self.plan is not None) != (phase_index >= _RECOVERY_PHASE_INDEX["planned"]):
            raise ValueError("crew_recovery_plan_phase_invalid")
        requirements = (
            ("synthesized", self.synthesis_ref),
            ("final_verified", self.final_verification_ref),
            ("artifact_bound", self.result_artifact_id),
            ("provenance_bound", self.provenance_ref),
        )
        for required_phase, value in requirements:
            should_exist = phase_index >= _RECOVERY_PHASE_INDEX[required_phase]
            if (value is not None) != should_exist:
                raise ValueError("crew_recovery_phase_ref_invalid")
        if self.next_attempt_at is not None and (
            self.last_error_code is None
            or self.retry_count == 0
            or self.last_attempt_at is None
            or self.next_attempt_at < self.last_attempt_at
        ):
            raise ValueError("crew_recovery_backoff_invalid")
        if self.interrupted_child_ids and self.last_error_code not in {
            "child_execution_cancelled",
            "child_execution_interrupted",
            "child_execution_integrity",
        }:
            raise ValueError("crew_recovery_interrupted_children_invalid")
        compact = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(compact) > _MAX_RECOVERY_BYTES:
            raise ValueError("crew_recovery_too_large")
        return self


def _json_values_exactly_equal(current: Any, expected: Any) -> bool:
    try:
        current_bytes = json.dumps(
            current,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        expected_bytes = json.dumps(
            expected,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        return False
    return current_bytes == expected_bytes


def is_valid_crew_session_transition(old: str, new: str) -> bool:
    """Return whether ``old -> new`` is an exact legal fine-state edge."""
    if type(old) is not str or type(new) is not str:
        return False
    if old not in _STATES or new not in _STATES:
        return False
    return old == new or new in _TRANSITIONS[old]


def _normalize_text(
    value: Any,
    *,
    maximum: int,
    allow_empty: bool,
) -> str:
    if type(value) is not str:
        raise ValueError("crew_session_text_invalid")
    normalized = value.strip()
    if "\x00" in normalized:
        raise ValueError("crew_session_text_invalid")
    if not allow_empty and not normalized:
        raise ValueError("crew_session_text_empty")
    if len(normalized) > maximum:
        raise ValueError("crew_session_text_too_long")
    return normalized


def _normalize_id(value: Any) -> str:
    normalized = _normalize_text(value, maximum=128, allow_empty=False)
    if _ID_RE.fullmatch(normalized) is None:
        raise ValueError("crew_session_id_invalid")
    return normalized


def _normalize_sha(value: Any) -> str:
    normalized = _normalize_text(value, maximum=64, allow_empty=False)
    if _SHA_RE.fullmatch(normalized) is None:
        raise ValueError("crew_session_ref_invalid")
    return normalized


def _normalize_timestamp(value: Any) -> float:
    if type(value) not in (int, float):
        raise ValueError("crew_session_timestamp_invalid")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= _MAX_TIMESTAMP:
        raise ValueError("crew_session_timestamp_invalid")
    return normalized


def _canonical_plan_json_bytes(
    value: Any,
    *,
    maximum_bytes: int,
    maximum_depth: int = 16,
    maximum_nodes: int = 65_536,
    maximum_string: int = 32_768,
    maximum_key: int = 128,
    error: str = "crew_recovery_plan_integrity_invalid",
) -> bytes:
    nodes = 0
    active: set[int] = set()

    def _validate(current: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > maximum_nodes or depth > maximum_depth:
            raise ValueError(error)
        if current is None or type(current) is bool:
            return
        if type(current) is int:
            if not _JSON_INT_MIN <= current <= _JSON_INT_MAX:
                raise ValueError(error)
            return
        if type(current) is float:
            if not math.isfinite(current):
                raise ValueError(error)
            return
        if type(current) is str:
            if "\x00" in current or len(current) > maximum_string:
                raise ValueError(error)
            current.encode("utf-8", errors="strict")
            return
        if type(current) not in (dict, list):
            raise ValueError(error)
        identity = id(current)
        if identity in active:
            raise ValueError(error)
        active.add(identity)
        try:
            if type(current) is list:
                for item in current:
                    _validate(item, depth + 1)
                return
            for key, item in current.items():
                if (
                    type(key) is not str
                    or not 1 <= len(key) <= maximum_key
                    or "\x00" in key
                ):
                    raise ValueError(error)
                key.encode("utf-8", errors="strict")
                _validate(item, depth + 1)
        finally:
            active.remove(identity)

    try:
        _validate(value, 1)
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
        UnicodeError,
    ) as exc:
        raise ValueError(error) from exc
    if len(encoded) > maximum_bytes:
        raise ValueError(error)
    return encoded


def _plan_sha(value: Any, *, maximum_bytes: int) -> str:
    return hashlib.sha256(
        _canonical_plan_json_bytes(value, maximum_bytes=maximum_bytes),
    ).hexdigest()


def _plan_text(
    value: Any,
    *,
    maximum: int,
    trim: bool,
    allow_empty: bool,
    error: str = "crew_recovery_plan_semantic_invalid",
) -> str:
    if type(value) is not str:
        raise ValueError(error)
    normalized = value.strip() if trim else value
    if (
        "\x00" in normalized
        or len(normalized) > maximum
        or (not allow_empty and not normalized)
    ):
        raise ValueError(error)
    try:
        normalized.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError(error) from exc
    return normalized


def _plan_optional_text(value: Any, *, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = _plan_text(
        value,
        maximum=maximum,
        trim=True,
        allow_empty=True,
    )
    return normalized or None


def _plan_metadata(value: Any, *, reject_reserved: bool) -> dict[str, Any]:
    if type(value) is not dict or (
        reject_reserved and not _PLAN_RESERVED_METADATA_KEYS.isdisjoint(value)
    ):
        raise ValueError("crew_recovery_plan_semantic_invalid")
    encoded = _canonical_plan_json_bytes(
        value,
        maximum_bytes=_MAX_PLAN_METADATA_BYTES,
        maximum_depth=_MAX_PLAN_METADATA_DEPTH,
        maximum_nodes=_MAX_PLAN_METADATA_NODES,
        maximum_string=_MAX_PLAN_METADATA_STRING,
        maximum_key=128,
        error="crew_recovery_plan_semantic_invalid",
    )
    return json.loads(encoded.decode("utf-8"))


def _plan_sequence(
    value: Any,
    *,
    maximum_items: int,
    maximum_text: int,
    identifiers: bool,
) -> list[str]:
    if type(value) not in (list, tuple) or len(value) > maximum_items:
        raise ValueError("crew_recovery_plan_semantic_invalid")
    normalized: list[str] = []
    for item in value:
        candidate = (
            _normalize_id(item)
            if identifiers
            else _plan_text(
                item,
                maximum=maximum_text,
                trim=True,
                allow_empty=False,
            )
        )
        if candidate in normalized:
            raise ValueError("crew_recovery_plan_semantic_invalid")
        normalized.append(candidate)
    return normalized


def _validate_plan_graph(projections: list[dict[str, Any]]) -> None:
    spec_ids = [projection["spec_id"] for projection in projections]
    if len(set(spec_ids)) != len(spec_ids):
        raise ValueError("crew_recovery_plan_semantic_invalid")
    spec_set = set(spec_ids)
    dependencies = {
        projection["spec_id"]: set(projection["depends_on"])
        for projection in projections
    }
    if any(
        spec_id in refs or not refs.issubset(spec_set)
        for spec_id, refs in dependencies.items()
    ):
        raise ValueError("crew_recovery_plan_semantic_invalid")
    completed: set[str] = set()
    while len(completed) < len(spec_ids):
        ready = {
            spec_id
            for spec_id, refs in dependencies.items()
            if spec_id not in completed and refs.issubset(completed)
        }
        if not ready:
            raise ValueError("crew_recovery_plan_semantic_invalid")
        completed.update(ready)


def _normalize_new_spec(spec: Any) -> tuple[dict[str, Any], str | None]:
    try:
        spec_id = _normalize_id(spec.spec_id)
        title_raw = spec.title
        description_raw = spec.description
        work_type_raw = spec.work_type
        priority = spec.priority
        depends_on_raw = spec.depends_on
        resources_raw = spec.resources
        metadata_raw = spec.metadata
        expected_output_raw = spec.expected_output
        capability_raw = spec.capability
        department_raw = spec.department
        agent_raw = spec.agent
    except Exception as exc:
        raise ValueError("crew_recovery_plan_semantic_invalid") from exc
    title = _plan_text(
        title_raw,
        maximum=4_096,
        trim=True,
        allow_empty=True,
    ) or spec_id
    description = _plan_text(
        description_raw,
        maximum=32_768,
        trim=False,
        allow_empty=True,
    )
    work_type = _plan_text(
        work_type_raw,
        maximum=128,
        trim=True,
        allow_empty=True,
    ) or "task"
    if type(priority) is not int or not 1 <= priority <= 5:
        raise ValueError("crew_recovery_plan_semantic_invalid")
    depends_on = _plan_sequence(
        depends_on_raw,
        maximum_items=64,
        maximum_text=128,
        identifiers=True,
    )
    resources = _plan_sequence(
        resources_raw,
        maximum_items=64,
        maximum_text=4_096,
        identifiers=False,
    )
    projection = {
        "spec_id": spec_id,
        "title": title,
        "description": description,
        "work_type": work_type,
        "priority": priority,
        "depends_on": depends_on,
        "resources": resources,
        "spec_metadata": _plan_metadata(metadata_raw, reject_reserved=True),
        "expected_output": _plan_optional_text(
            expected_output_raw,
            maximum=4_096,
        ),
        "capability": _plan_optional_text(capability_raw, maximum=256),
        "department": _plan_optional_text(department_raw, maximum=128),
    }
    _canonical_plan_json_bytes(
        projection,
        maximum_bytes=_MAX_PLAN_PROJECTION_BYTES,
        error="crew_recovery_plan_semantic_invalid",
    )
    if agent_raw is None:
        assigned_to = None
    elif type(agent_raw) is str:
        normalized_agent = agent_raw.strip()
        assigned_to = _normalize_id(normalized_agent) if normalized_agent else None
    else:
        raise ValueError("crew_recovery_plan_semantic_invalid")
    return projection, assigned_to


def _derived_child_id(parent_id: str, plan_seed_hash: str, spec_id: str) -> str:
    digest = _plan_sha(
        {
            "parent_id": parent_id,
            "plan_seed_hash": plan_seed_hash,
            "spec_id": spec_id,
        },
        maximum_bytes=_MAX_PLAN_PROJECTION_BYTES,
    )
    return f"crew-{digest}"


def _final_plan_hash(
    parent_id: str,
    plan_seed_hash: str,
    commitments: list[dict[str, str]],
    *,
    policy: str,
) -> str:
    if policy not in _PLAN_POLICIES:
        raise ValueError("crew_recovery_plan_integrity_invalid")
    return _plan_sha(
        {
            "version": 1,
            "child_id_policy": policy,
            "parent_id": parent_id,
            "plan_seed_hash": plan_seed_hash,
            "children": commitments,
        },
        maximum_bytes=_MAX_PLAN_ARRAY_BYTES,
    )


def _build_derived_recovery_plan(
    parent_id: str,
    specs: list[Any],
    *,
    created_by: str,
) -> tuple[CrewRecoveryPlan, tuple[WorkItemPlanInsert, ...]]:
    from probos.workforce import WorkItemPlanInsert

    parent_key = _normalize_id(parent_id)
    creator = _normalize_id(created_by)
    if type(specs) is not list or not 1 <= len(specs) <= _MAX_PLAN_SPECS:
        raise ValueError("crew_recovery_plan_semantic_invalid")
    normalized = [_normalize_new_spec(spec) for spec in specs]
    projections = [item[0] for item in normalized]
    _validate_plan_graph(projections)
    projection_bytes = _canonical_plan_json_bytes(
        projections,
        maximum_bytes=_MAX_PLAN_ARRAY_BYTES,
        error="crew_recovery_plan_semantic_invalid",
    )
    plan_seed_hash = hashlib.sha256(projection_bytes).hexdigest()
    child_ids = {
        projection["spec_id"]: _derived_child_id(
            parent_key,
            plan_seed_hash,
            projection["spec_id"],
        )
        for projection in projections
    }
    if len(set(child_ids.values())) != len(child_ids):
        raise ValueError("crew_recovery_plan_child_id_conflict")
    inserts: list[WorkItemPlanInsert] = []
    commitments: list[dict[str, str]] = []
    for projection, assigned_to in normalized:
        child_id = child_ids[projection["spec_id"]]
        child_dependencies = [
            child_ids[spec_id] for spec_id in projection["depends_on"]
        ]
        metadata = dict(projection["spec_metadata"])
        metadata.update({
            "spec_id": projection["spec_id"],
            "resources": list(projection["resources"]),
            "expected_output": projection["expected_output"],
            "capability": projection["capability"],
            "department": projection["department"],
        })
        row_projection = {
            **projection,
            "child_id": child_id,
            "depends_on": child_dependencies,
        }
        row_hash = _plan_sha(
            row_projection,
            maximum_bytes=_MAX_PLAN_PROJECTION_BYTES,
        )
        commitments.append({
            "child_id": child_id,
            "spec_id": projection["spec_id"],
            "row_hash": row_hash,
        })
        inserts.append(WorkItemPlanInsert(
            id=child_id,
            title=projection["title"],
            description=projection["description"],
            work_type=projection["work_type"],
            priority=projection["priority"],
            depends_on=tuple(child_dependencies),
            assigned_to=assigned_to,
            created_by=creator,
            trust_requirement=0.0,
            required_capabilities=(),
            metadata=metadata,
        ))
    plan = CrewRecoveryPlan.model_validate({
        "version": 1,
        "plan_seed_hash": plan_seed_hash,
        "plan_hash": _final_plan_hash(
            parent_key,
            plan_seed_hash,
            commitments,
            policy="derived_v1",
        ),
        "children": commitments,
    })
    _validate_contextual_recovery_plan(
        parent_key,
        plan,
        tuple(inserts),
        expected_policy="derived_v1",
    )
    return plan, tuple(inserts)


def _detach_plan_inserts(
    children: tuple[WorkItemPlanInsert, ...],
) -> tuple[WorkItemPlanInsert, ...]:
    from probos.workforce import WorkItemPlanInsert

    if type(children) is not tuple:
        raise ValueError("crew_recovery_plan_integrity_invalid")
    try:
        return tuple(
            WorkItemPlanInsert(
                id=child.id,
                title=child.title,
                description=child.description,
                work_type=child.work_type,
                priority=child.priority,
                depends_on=child.depends_on,
                assigned_to=child.assigned_to,
                created_by=child.created_by,
                trust_requirement=child.trust_requirement,
                required_capabilities=child.required_capabilities,
                metadata=child.metadata,
            )
            for child in children
            if type(child) is WorkItemPlanInsert
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("crew_recovery_plan_integrity_invalid") from exc


def _validate_assignment_metadata(row: Any, metadata: dict[str, Any]) -> None:
    present = _PLAN_ASSIGNMENT_KEYS.intersection(metadata)
    if present and present != _PLAN_ASSIGNMENT_KEYS:
        raise ValueError("crew_recovery_plan_runtime_invalid")
    if not present:
        return
    chief = metadata["chief_agent_id"]
    order = metadata["order_id"]
    delegated = metadata["delegated"]
    reason = metadata["delegation_reason"]
    capability = metadata["assigned_capability"]
    department = metadata["assigned_department"]
    if chief is not None:
        _normalize_id(chief)
    if order is not None:
        _normalize_id(order)
    if type(delegated) is not bool:
        raise ValueError("crew_recovery_plan_runtime_invalid")
    _plan_text(reason, maximum=128, trim=False, allow_empty=False)
    normalized_capability = _plan_optional_text(capability, maximum=256)
    normalized_department = _plan_optional_text(department, maximum=128)
    if capability != normalized_capability or department != normalized_department:
        raise ValueError("crew_recovery_plan_runtime_invalid")
    assigned_to = getattr(row, "assigned_to", None)
    if assigned_to is None:
        raise ValueError("crew_recovery_plan_runtime_invalid")
    _normalize_id(assigned_to)
    if reason == "delegated_via_chief":
        valid_reason = delegated and chief is not None and order is not None
    elif reason == "out_of_chain":
        valid_reason = not delegated and chief is not None and order is None
    elif reason == "self_assigned":
        valid_reason = not delegated and chief is None and order is None
    elif reason == "direct_no_chief":
        valid_reason = not delegated and order is None
    else:
        valid_reason = False
    if not valid_reason:
        raise ValueError("crew_recovery_plan_runtime_invalid")


def _validate_execution_metadata(row: Any, metadata: dict[str, Any]) -> None:
    execution = metadata.get("crew_execution", _MISSING)
    output = metadata.get("crew_execution_output", _MISSING)
    if execution is _MISSING:
        if output is not _MISSING:
            raise ValueError("crew_recovery_plan_runtime_invalid")
    else:
        if type(execution) is not dict or set(execution) != _PLAN_EXECUTION_KEYS:
            raise ValueError("crew_recovery_plan_runtime_invalid")
        try:
            from probos.cognitive.crew_executor import (
                _build_execution_evidence,
                _normalize_artifact_refs,
                _normalize_trace_ref,
            )

            trace_ref = _normalize_trace_ref(
                execution["tool_trace_ref"],
                getattr(row, "id", ""),
            )
            artifact_refs = _normalize_artifact_refs(
                execution["artifact_refs"],
                thread_id=execution["thread_id"],
                child_id=getattr(row, "id", ""),
            )
            rebuilt = _build_execution_evidence(
                parent_id=getattr(row, "parent_id", None),
                child=row,
                thread_id=execution["thread_id"],
                status=execution["status"],
                stopped_reason=execution["stopped_reason"],
                output=execution["output_summary"],
                tool_trace_ref=trace_ref,
                artifact_refs=artifact_refs,
                actual_tokens=execution["tokens_used"],
                started_at=execution["started_at"],
                finished_at=execution["finished_at"],
                blocked_dependency_ids=execution["blocked_dependency_ids"],
            )
        except (ImportError, ValueError) as exc:
            raise ValueError("crew_recovery_plan_runtime_invalid") from exc
        if not _json_values_exactly_equal(rebuilt, execution):
            raise ValueError("crew_recovery_plan_runtime_invalid")
        if output is not _MISSING:
            if (
                type(output) is not dict
                or set(output) != {"version", "content_hash", "mime", "size_bytes"}
                or type(output["version"]) is not int
                or output["version"] != 1
                or output["mime"] != "text/plain"
                or type(output["size_bytes"]) is not int
                or not 1 <= output["size_bytes"] <= 1_048_576
                or execution["status"] != "done"
                or execution["stopped_reason"] != "complete"
            ):
                raise ValueError("crew_recovery_plan_runtime_invalid")
            _normalize_sha(output["content_hash"])
    verification = getattr(row, "verification", {})
    verification_recovery = metadata.get("crew_verification_recovery", _MISSING)
    if verification:
        if (
            type(verification) is not dict
            or verification_recovery is _MISSING
            or type(verification_recovery) is not dict
            or set(verification_recovery) != {"version", "convergence_ref"}
            or type(verification_recovery["version"]) is not int
            or verification_recovery["version"] != 1
        ):
            raise ValueError("crew_recovery_plan_runtime_invalid")
        _normalize_sha(verification_recovery["convergence_ref"])
        try:
            from probos.cognitive.crew_finalizer import ChildVerificationRecord

            validated_verification = ChildVerificationRecord.model_validate(
                verification,
            ).model_dump(mode="json")
        except (ImportError, ValidationError, ValueError) as exc:
            raise ValueError("crew_recovery_plan_runtime_invalid") from exc
        if not _json_values_exactly_equal(
            validated_verification,
            verification,
        ):
            raise ValueError("crew_recovery_plan_runtime_invalid")
    elif verification_recovery is not _MISSING:
        raise ValueError("crew_recovery_plan_runtime_invalid")


def _row_semantic_projection(
    row: Any,
    *,
    child_to_spec: dict[str, str],
    require_new_metadata: bool,
) -> dict[str, Any]:
    try:
        child_id = _normalize_id(row.id)
        title_raw = row.title
        description_raw = row.description
        work_type_raw = row.work_type
        priority = row.priority
        dependencies_raw = row.depends_on
        metadata_raw = row.metadata
    except Exception as exc:
        raise ValueError("crew_recovery_plan_integrity_invalid") from exc
    if type(metadata_raw) is not dict:
        raise ValueError("crew_recovery_plan_integrity_invalid")
    metadata = _plan_metadata(metadata_raw, reject_reserved=False)
    required_semantic_keys = {
        "spec_id",
        "resources",
        "expected_output",
        "capability",
        "department",
    }
    if require_new_metadata and not required_semantic_keys.issubset(metadata):
        raise ValueError("crew_recovery_plan_integrity_invalid")
    _validate_assignment_metadata(row, metadata)
    if not require_new_metadata:
        _validate_execution_metadata(row, metadata)
    spec_id = _normalize_id(metadata.get("spec_id"))
    if child_to_spec.get(child_id) != spec_id:
        raise ValueError("crew_recovery_plan_integrity_invalid")
    if type(dependencies_raw) not in (list, tuple) or len(dependencies_raw) > 64:
        raise ValueError("crew_recovery_plan_integrity_invalid")
    dependency_specs: list[str] = []
    dependency_child_ids: list[str] = []
    for dependency in dependencies_raw:
        dependency_id = _normalize_id(dependency)
        dependency_spec = child_to_spec.get(dependency_id)
        if dependency_spec is None or dependency_id == child_id:
            raise ValueError("crew_recovery_plan_integrity_invalid")
        if dependency_id in dependency_child_ids:
            raise ValueError("crew_recovery_plan_integrity_invalid")
        dependency_child_ids.append(dependency_id)
        dependency_specs.append(dependency_spec)
    resources_raw = metadata.get("resources", [])
    expected_output_raw = metadata.get("expected_output")
    capability_raw = metadata.get("capability")
    department_raw = metadata.get("department")
    spec_metadata_raw = {
        key: value
        for key, value in metadata.items()
        if key not in _PLAN_RESERVED_METADATA_KEYS
    }
    projection = {
        "spec_id": spec_id,
        "title": _plan_text(
            title_raw,
            maximum=4_096,
            trim=True,
            allow_empty=True,
        ) or spec_id,
        "description": _plan_text(
            description_raw,
            maximum=32_768,
            trim=False,
            allow_empty=True,
        ),
        "work_type": _plan_text(
            work_type_raw,
            maximum=128,
            trim=True,
            allow_empty=True,
        ) or "task",
        "priority": priority,
        "depends_on": dependency_specs,
        "resources": _plan_sequence(
            resources_raw,
            maximum_items=64,
            maximum_text=4_096,
            identifiers=False,
        ),
        "spec_metadata": _plan_metadata(
            spec_metadata_raw,
            reject_reserved=True,
        ),
        "expected_output": _plan_optional_text(
            expected_output_raw,
            maximum=4_096,
        ),
        "capability": _plan_optional_text(capability_raw, maximum=256),
        "department": _plan_optional_text(department_raw, maximum=128),
    }
    if type(priority) is not int or not 1 <= priority <= 5:
        raise ValueError("crew_recovery_plan_integrity_invalid")
    _canonical_plan_json_bytes(
        projection,
        maximum_bytes=_MAX_PLAN_PROJECTION_BYTES,
        error="crew_recovery_plan_integrity_invalid",
    )
    return projection


def _validate_contextual_recovery_plan(
    parent_id: str,
    plan: CrewRecoveryPlan,
    rows: tuple[Any, ...],
    *,
    expected_policy: str | None = None,
) -> str:
    parent_key = _normalize_id(parent_id)
    candidate = CrewRecoveryPlan.model_validate(plan)
    if (
        type(rows) is not tuple
        or len(rows) != len(candidate.children)
        or not 1 <= len(rows) <= _MAX_RECOVERY_CHILDREN
    ):
        raise ValueError("crew_recovery_plan_integrity_invalid")
    row_by_id: dict[str, Any] = {}
    require_new_metadata = False
    try:
        from probos.workforce import WorkItemPlanInsert

        require_new_metadata = all(type(row) is WorkItemPlanInsert for row in rows)
    except ImportError as exc:  # pragma: no cover - package invariant
        raise ValueError("crew_recovery_plan_integrity_invalid") from exc
    if not require_new_metadata and any(
        type(row).__name__ != "WorkItem" for row in rows
    ):
        raise ValueError("crew_recovery_plan_integrity_invalid")
    for row in rows:
        child_id = _normalize_id(getattr(row, "id", None))
        if child_id in row_by_id:
            raise ValueError("crew_recovery_plan_integrity_invalid")
        if not require_new_metadata and getattr(row, "parent_id", None) != parent_key:
            raise ValueError("crew_recovery_plan_integrity_invalid")
        row_by_id[child_id] = row
    commitments = [child.model_dump(mode="json") for child in candidate.children]
    commitment_ids = [item["child_id"] for item in commitments]
    commitment_specs = [item["spec_id"] for item in commitments]
    if (
        len(set(commitment_ids)) != len(commitment_ids)
        or len(set(commitment_specs)) != len(commitment_specs)
        or set(commitment_ids) != set(row_by_id)
    ):
        raise ValueError("crew_recovery_plan_integrity_invalid")
    child_to_spec = dict(zip(commitment_ids, commitment_specs))
    projections: list[dict[str, Any]] = []
    row_projections: list[dict[str, Any]] = []
    for commitment in commitments:
        row = row_by_id[commitment["child_id"]]
        projection = _row_semantic_projection(
            row,
            child_to_spec=child_to_spec,
            require_new_metadata=require_new_metadata,
        )
        projections.append(projection)
        row_projections.append({
            **projection,
            "child_id": commitment["child_id"],
            "depends_on": list(getattr(row, "depends_on")),
        })
    _validate_plan_graph(projections)
    projection_bytes = _canonical_plan_json_bytes(
        projections,
        maximum_bytes=_MAX_PLAN_ARRAY_BYTES,
        error="crew_recovery_plan_integrity_invalid",
    )
    if hashlib.sha256(projection_bytes).hexdigest() != candidate.plan_seed_hash:
        raise ValueError("crew_recovery_plan_integrity_invalid")
    _canonical_plan_json_bytes(
        row_projections,
        maximum_bytes=_MAX_PLAN_ARRAY_BYTES,
        error="crew_recovery_plan_integrity_invalid",
    )
    for commitment, row_projection in zip(commitments, row_projections):
        if _plan_sha(
            row_projection,
            maximum_bytes=_MAX_PLAN_PROJECTION_BYTES,
        ) != commitment["row_hash"]:
            raise ValueError("crew_recovery_plan_integrity_invalid")
    matches = [
        policy
        for policy in _PLAN_POLICIES
        if _final_plan_hash(
            parent_key,
            candidate.plan_seed_hash,
            commitments,
            policy=policy,
        ) == candidate.plan_hash
    ]
    if len(matches) != 1 or (
        expected_policy is not None and matches[0] != expected_policy
    ):
        raise ValueError("crew_recovery_plan_integrity_invalid")
    policy = matches[0]
    if policy == "derived_v1":
        for commitment in commitments:
            if commitment["child_id"] != _derived_child_id(
                parent_key,
                candidate.plan_seed_hash,
                commitment["spec_id"],
            ):
                raise ValueError("crew_recovery_plan_integrity_invalid")
    return policy


def _build_adopted_recovery_plan(
    parent_id: str,
    children: tuple[WorkItem, ...],
) -> CrewRecoveryPlan:
    parent_key = _normalize_id(parent_id)
    if (
        type(children) is not tuple
        or not 1 <= len(children) <= _MAX_RECOVERY_CHILDREN
        or tuple(child.id for child in children)
        != tuple(sorted(child.id for child in children))
    ):
        raise ValueError("crew_recovery_plan_integrity_invalid")
    commitments: list[dict[str, str]] = []
    child_to_spec: dict[str, str] = {}
    for child in children:
        if child.parent_id != parent_key or type(child.metadata) is not dict:
            raise ValueError("crew_recovery_plan_integrity_invalid")
        spec_id = _normalize_id(child.metadata.get("spec_id"))
        if spec_id in child_to_spec.values():
            raise ValueError("crew_recovery_plan_integrity_invalid")
        child_to_spec[_normalize_id(child.id)] = spec_id
    projections: list[dict[str, Any]] = []
    row_projections: list[dict[str, Any]] = []
    for child in children:
        projection = _row_semantic_projection(
            child,
            child_to_spec=child_to_spec,
            require_new_metadata=False,
        )
        projections.append(projection)
        row_projection = {
            **projection,
            "child_id": child.id,
            "depends_on": list(child.depends_on),
        }
        row_projections.append(row_projection)
        commitments.append({
            "child_id": child.id,
            "spec_id": projection["spec_id"],
            "row_hash": _plan_sha(
                row_projection,
                maximum_bytes=_MAX_PLAN_PROJECTION_BYTES,
            ),
        })
    _validate_plan_graph(projections)
    plan_seed_hash = hashlib.sha256(_canonical_plan_json_bytes(
        projections,
        maximum_bytes=_MAX_PLAN_ARRAY_BYTES,
        error="crew_recovery_plan_integrity_invalid",
    )).hexdigest()
    plan = CrewRecoveryPlan.model_validate({
        "version": 1,
        "plan_seed_hash": plan_seed_hash,
        "plan_hash": _final_plan_hash(
            parent_key,
            plan_seed_hash,
            commitments,
            policy="adopted_v1",
        ),
        "children": commitments,
    })
    _validate_contextual_recovery_plan(
        parent_key,
        plan,
        children,
        expected_policy="adopted_v1",
    )
    return plan


class CrewSynthesisMetadata(BaseModel):
    """Strict bounded summary committed with a verified session result."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: Literal[1]
    completed: Literal[True]
    producer_agent_id: str
    final_verifier_agent_id: str
    final_confidence: float
    final_critique: str
    accepted_count: int
    total_count: int
    convergence_rounds: int
    correction_tokens: int
    verification_tokens: int
    synthesis_tokens: int
    result_artifact_id: str
    result_content_hash: str
    provenance_ref: str

    @field_validator("version", mode="before")
    @classmethod
    def _validate_synthesis_version(cls, value: Any) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("crew_synthesis_version_invalid")
        return value

    @field_validator("completed", mode="before")
    @classmethod
    def _validate_synthesis_completed(cls, value: Any) -> bool:
        if value is not True:
            raise ValueError("crew_synthesis_completed_invalid")
        return value

    @field_validator(
        "producer_agent_id",
        "final_verifier_agent_id",
        "result_artifact_id",
        mode="before",
    )
    @classmethod
    def _validate_synthesis_id(cls, value: Any) -> str:
        return _normalize_id(value)

    @field_validator("result_content_hash", "provenance_ref", mode="before")
    @classmethod
    def _validate_synthesis_ref(cls, value: Any) -> str:
        return _normalize_sha(value)

    @field_validator("final_confidence", mode="before")
    @classmethod
    def _validate_synthesis_confidence(cls, value: Any) -> float:
        if type(value) not in (int, float):
            raise ValueError("crew_synthesis_confidence_invalid")
        normalized = float(value)
        if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
            raise ValueError("crew_synthesis_confidence_invalid")
        return normalized

    @field_validator("final_critique", mode="before")
    @classmethod
    def _validate_synthesis_critique(cls, value: Any) -> str:
        normalized = _normalize_text(value, maximum=2_048, allow_empty=False)
        if len(normalized.encode("utf-8")) > 8_192:
            raise ValueError("crew_synthesis_critique_invalid")
        return normalized

    @field_validator(
        "accepted_count",
        "total_count",
        "convergence_rounds",
        "correction_tokens",
        "verification_tokens",
        "synthesis_tokens",
        mode="before",
    )
    @classmethod
    def _validate_synthesis_integer(cls, value: Any) -> int:
        if type(value) is not int or not 0 <= value <= _MAX_SESSION_TOKEN_TOTAL:
            raise ValueError("crew_synthesis_integer_invalid")
        return value

    @model_validator(mode="after")
    def _validate_synthesis_consistency(self) -> Self:
        if (
            self.accepted_count == 0
            or self.accepted_count != self.total_count
            or self.total_count > 1_000
            or self.convergence_rounds > self.total_count * 8
        ):
            raise ValueError("crew_synthesis_counts_invalid")
        compact = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(compact) > _MAX_SYNTHESIS_METADATA_BYTES:
            raise ValueError("crew_synthesis_metadata_too_large")
        return self


class CrewSessionContract(BaseModel):
    """Strict immutable v1 metadata contract for a durable crew session."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: Literal[1]
    state: CrewSessionState
    previous_state: CrewSessionState | None
    revision: int
    goal: str
    origin: CrewSessionOrigin
    originator_id: str
    facilitator_id: str
    owner_ids: tuple[str, ...]
    success_criteria: tuple[str, ...]
    expected_deliverable: str
    thread_id: str
    task_id: str
    created_at: float
    transitioned_at: float
    started_at: float | None
    first_result_at: float | None
    verified_at: float | None
    completed_at: float | None
    last_result_summary: str
    blocked_reason: str | None
    blocked_since: float | None
    blocked_duration_seconds: float
    evidence_refs: tuple[str, ...]
    result_artifact_id: str | None
    result_ref: str | None
    duplicate_resume_count: int

    @field_validator("version", mode="before")
    @classmethod
    def _validate_version(cls, value: Any) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("crew_session_version_invalid")
        return value

    @field_validator("revision", mode="before")
    @classmethod
    def _validate_revision(cls, value: Any) -> int:
        if type(value) is not int or not 1 <= value <= 2_147_483_647:
            raise ValueError("crew_session_revision_invalid")
        return value

    @field_validator("duplicate_resume_count", mode="before")
    @classmethod
    def _validate_duplicate_resume_count(cls, value: Any) -> int:
        if type(value) is not int or not 0 <= value <= 1_000_000:
            raise ValueError("crew_session_duplicate_resume_count_invalid")
        return value

    @field_validator("goal", mode="before")
    @classmethod
    def _validate_goal(cls, value: Any) -> str:
        return _normalize_text(value, maximum=4_096, allow_empty=False)

    @field_validator("expected_deliverable", mode="before")
    @classmethod
    def _validate_expected_deliverable(cls, value: Any) -> str:
        return _normalize_text(value, maximum=2_048, allow_empty=False)

    @field_validator("last_result_summary", mode="before")
    @classmethod
    def _validate_last_result_summary(cls, value: Any) -> str:
        return _normalize_text(value, maximum=4_096, allow_empty=True)

    @field_validator("blocked_reason", mode="before")
    @classmethod
    def _validate_blocked_reason(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _normalize_text(value, maximum=2_048, allow_empty=False)

    @field_validator(
        "originator_id", "facilitator_id", "thread_id", "task_id", mode="before",
    )
    @classmethod
    def _validate_required_id(cls, value: Any) -> str:
        return _normalize_id(value)

    @field_validator("result_artifact_id", mode="before")
    @classmethod
    def _validate_optional_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _normalize_id(value)

    @field_validator("result_ref", mode="before")
    @classmethod
    def _validate_optional_ref(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _normalize_sha(value)

    @field_validator("owner_ids", mode="before")
    @classmethod
    def _validate_owner_ids(cls, value: Any) -> tuple[str, ...]:
        if type(value) is not list:
            raise ValueError("crew_session_owner_ids_invalid")
        normalized = tuple(_normalize_id(item) for item in value)
        if not 1 <= len(normalized) <= 16 or len(set(normalized)) != len(normalized):
            raise ValueError("crew_session_owner_ids_invalid")
        return normalized

    @field_validator("success_criteria", mode="before")
    @classmethod
    def _validate_success_criteria(cls, value: Any) -> tuple[str, ...]:
        if type(value) is not list:
            raise ValueError("crew_session_success_criteria_invalid")
        normalized = tuple(
            _normalize_text(item, maximum=512, allow_empty=False) for item in value
        )
        if not 1 <= len(normalized) <= 16 or len(set(normalized)) != len(normalized):
            raise ValueError("crew_session_success_criteria_invalid")
        return normalized

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _validate_evidence_refs(cls, value: Any) -> tuple[str, ...]:
        if type(value) is not list:
            raise ValueError("crew_session_evidence_refs_invalid")
        normalized = tuple(_normalize_sha(item) for item in value)
        if len(normalized) > 32 or len(set(normalized)) != len(normalized):
            raise ValueError("crew_session_evidence_refs_invalid")
        return normalized

    @field_validator(
        "created_at",
        "transitioned_at",
        "started_at",
        "first_result_at",
        "verified_at",
        "completed_at",
        "blocked_since",
        mode="before",
    )
    @classmethod
    def _validate_timestamp(cls, value: Any) -> float | None:
        if value is None:
            return None
        return _normalize_timestamp(value)

    @field_validator("blocked_duration_seconds", mode="before")
    @classmethod
    def _validate_blocked_duration(cls, value: Any) -> float:
        if type(value) is not float or not math.isfinite(value):
            raise ValueError("crew_session_blocked_duration_invalid")
        if not 0.0 <= value <= _MAX_BLOCKED_SECONDS:
            raise ValueError("crew_session_blocked_duration_invalid")
        return value

    @model_validator(mode="after")
    def _validate_consistency(self) -> Self:
        if self.facilitator_id not in self.owner_ids:
            raise ValueError("crew_session_facilitator_not_owner")
        if self.state == "blocked_needs_captain":
            if self.blocked_reason is None or self.blocked_since is None:
                raise ValueError("crew_session_blocked_fields_required")
        elif self.blocked_reason is not None or self.blocked_since is not None:
            raise ValueError("crew_session_blocked_fields_unexpected")
        if self.state != "done" and (
            self.result_artifact_id is not None or self.result_ref is not None
        ):
            raise ValueError("crew_session_result_requires_done")
        if self.state != "done" and self.verified_at is not None:
            raise ValueError("crew_session_verified_timestamp_unexpected")
        if self.state not in _TERMINAL_STATES and self.completed_at is not None:
            raise ValueError("crew_session_completed_timestamp_unexpected")
        if self.state == "done" and (
            self.verified_at is None or self.completed_at is None
        ):
            raise ValueError("crew_session_done_timestamps_required")
        if self.state == "done" and (
            self.result_artifact_id is None or self.result_ref is None
        ):
            raise ValueError("crew_session_done_result_refs_required")
        if self.state == "failed" and self.completed_at is None:
            raise ValueError("crew_session_failed_timestamp_required")
        if bool(self.last_result_summary) != (self.first_result_at is not None):
            raise ValueError("crew_session_first_result_invalid")
        if self.transitioned_at < self.created_at:
            raise ValueError("crew_session_timestamp_order_invalid")
        if self.started_at is not None and self.started_at > self.transitioned_at:
            raise ValueError("crew_session_timestamp_order_invalid")
        if self.state in {"executing", "verifying", "done"} and self.started_at is None:
            raise ValueError("crew_session_timestamp_order_invalid")
        if self.state == "blocked_needs_captain" and self.blocked_since != self.transitioned_at:
            raise ValueError("crew_session_timestamp_order_invalid")
        if self.state == "done" and (
            self.verified_at != self.transitioned_at
            or self.completed_at != self.transitioned_at
        ):
            raise ValueError("crew_session_timestamp_order_invalid")
        if self.state == "failed" and self.completed_at != self.transitioned_at:
            raise ValueError("crew_session_timestamp_order_invalid")
        optional_milestones = (
            self.started_at,
            self.first_result_at,
            self.verified_at,
            self.completed_at,
        )
        if any(
            milestone is not None and milestone < self.created_at
            for milestone in optional_milestones
        ):
            raise ValueError("crew_session_timestamp_order_invalid")
        if self.verified_at is not None and any(
            milestone is not None and milestone > self.verified_at
            for milestone in (self.started_at, self.first_result_at)
        ):
            raise ValueError("crew_session_timestamp_order_invalid")
        if self.completed_at is not None and any(
            milestone is not None and milestone > self.completed_at
            for milestone in (self.started_at, self.first_result_at, self.verified_at)
        ):
            raise ValueError("crew_session_timestamp_order_invalid")
        if self.blocked_since is not None and self.blocked_since < self.created_at:
            raise ValueError("crew_session_timestamp_order_invalid")
        compact = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(compact) > _MAX_CONTRACT_BYTES:
            raise ValueError("crew_session_contract_too_large")
        return self


def _validate_session_recovery_invariant(
    session: CrewSessionContract,
    recovery: CrewRecoveryContract | None,
) -> None:
    if recovery is None:
        return
    phase = recovery.phase
    if session.state == "discussing":
        valid = phase in _DISCUSSING_RECOVERY_PHASES
    elif session.state == "executing":
        valid = phase == "executing"
    elif session.state == "verifying":
        valid = phase in _VERIFYING_RECOVERY_PHASES
    elif session.state == "done":
        valid = (
            phase == "published"
            and session.result_artifact_id == recovery.result_artifact_id
            and session.result_ref == recovery.provenance_ref
            and recovery.provenance_ref in session.evidence_refs
        )
    else:
        valid = phase != "published"
    if not valid:
        raise ValueError("crew_session_recovery_state_conflict")


class _WorkItemStoreProtocol(Protocol):
    async def get_work_item(self, work_item_id: str) -> WorkItem | None: ...

    async def list_work_items(
        self,
        status: str | None = None,
        assigned_to: str | None = None,
        work_type: str | None = None,
        parent_id: str | None = None,
        priority: int | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkItem]: ...

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any] | None = None,
        expected_absent_keys: frozenset[str] = frozenset(),
        expected_present_keys: frozenset[str] = frozenset(),
        expected_work_type: str | None = None,
        expected_status: str | None = None,
        expected_assigned_to: str | None = None,
        new_status: str | None = None,
        source: str = "system",
    ) -> WorkItem | None: ...

    async def publish_work_item_metadata_with_child_barrier(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any],
        expected_absent_keys: frozenset[str],
        expected_present_keys: frozenset[str],
        expected_work_type: str,
        expected_status: str,
        expected_assigned_to: str,
        expected_direct_children: tuple[dict[str, Any], ...],
        new_status: str,
        source: str = "crew_session_verified_result",
    ) -> WorkItem | None: ...

    async def install_child_plan_with_parent_metadata(
        self,
        parent_id: str,
        *,
        expected_parent_metadata: dict[str, Any],
        expected_status: str,
        expected_assigned_to: str,
        parent_patch: dict[str, Any],
        children: tuple[WorkItemPlanInsert, ...],
        source: str = "crew_session_plan_install",
    ) -> tuple[WorkItem, tuple[WorkItem, ...]]: ...

    async def adopt_child_plan_with_parent_metadata(
        self,
        parent_id: str,
        *,
        expected_parent_metadata: dict[str, Any],
        expected_status: str,
        expected_assigned_to: str,
        parent_patch: dict[str, Any],
        expected_children: tuple[WorkItem, ...],
        source: str = "crew_session_plan_adoption",
    ) -> WorkItem: ...


class _ChatThreadStoreProtocol(Protocol):
    def get_thread(self, thread_id: str) -> ChatThread | None: ...

    def list_threads(
        self,
        *,
        include_archived: bool = False,
        project_id: str | None = None,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[ChatThread]: ...


class CrewSessionService:
    """Validate and persist one durable CrewSession contract per parent."""

    def __init__(
        self,
        *,
        work_item_store: _WorkItemStoreProtocol,
        chat_thread_store: _ChatThreadStoreProtocol,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._work_items = work_item_store
        self._threads = chat_thread_store
        self._clock = clock

    async def initialize_session(
        self,
        parent_id: str,
        thread_id: str,
        *,
        goal: str,
        origin: CrewSessionOrigin,
        originator_id: str,
        facilitator_id: str,
        owner_ids: list[str],
        success_criteria: list[str],
        expected_deliverable: str,
    ) -> CrewSessionContract:
        parent_key = _normalize_id(parent_id)
        thread_key = _normalize_id(thread_id)
        parent = await self._work_items.get_work_item(parent_key)
        if parent is None:
            raise ValueError("crew_session_parent_not_found")

        raw = (parent.metadata or {}).get("crew_session", _MISSING)
        if raw is not _MISSING:
            existing = self._parse_contract(raw)
            await self._validate_loaded(parent, existing)
            candidate = self._build_initial_contract(
                parent=parent,
                thread_id=thread_key,
                goal=goal,
                origin=origin,
                originator_id=originator_id,
                facilitator_id=facilitator_id,
                owner_ids=owner_ids,
                success_criteria=success_criteria,
                expected_deliverable=expected_deliverable,
                transitioned_at=existing.transitioned_at,
            )
            if self._initial_fields(existing) != self._initial_fields(candidate):
                raise ValueError("crew_session_contract_conflict")
            return existing

        if parent.work_type != "crew_session":
            raise ValueError("crew_session_parent_type_invalid")
        if parent.status != "draft":
            raise ValueError("crew_session_parent_status_invalid")
        if not parent.assigned_to:
            raise ValueError("crew_session_parent_unassigned")
        if parent.assigned_to != _normalize_id(facilitator_id):
            raise ValueError("crew_session_facilitator_assignment_mismatch")
        await self._validate_room(parent.id, thread_key)
        now = self._server_time(parent.created_at)
        contract = self._build_initial_contract(
            parent=parent,
            thread_id=thread_key,
            goal=goal,
            origin=origin,
            originator_id=originator_id,
            facilitator_id=facilitator_id,
            owner_ids=owner_ids,
            success_criteria=success_criteria,
            expected_deliverable=expected_deliverable,
            transitioned_at=now,
        )
        updated = await self._work_items.merge_work_item_metadata(
            parent.id,
            {"crew_session": contract.model_dump(mode="json")},
            expected={"crew_session": None},
            expected_work_type="crew_session",
            expected_status="draft",
            expected_assigned_to=_normalize_id(facilitator_id),
            new_status="open",
            source="crew_session_initialize",
        )
        if updated is None:
            raise ValueError("crew_session_initialize_failed")
        logger.info(
            "Crew session parent=%s initialized state=%s revision=%d; session is ready for discussion",
            parent.id,
            contract.state,
            contract.revision,
        )
        return self._parse_contract(updated.metadata.get("crew_session"))

    async def get_session(self, parent_id: str) -> CrewSessionContract | None:
        parent_key = _normalize_id(parent_id)
        parent = await self._work_items.get_work_item(parent_key)
        if parent is None:
            return None
        raw = (parent.metadata or {}).get("crew_session", _MISSING)
        if raw is _MISSING:
            return None
        contract = self._parse_contract(raw)
        await self._validate_loaded(parent, contract)
        return contract

    async def get_recovery(self, parent_id: str) -> CrewRecoveryContract | None:
        """Return the exact recovery sibling after validating session authority."""
        parent_key = _normalize_id(parent_id)
        parent = await self._work_items.get_work_item(parent_key)
        if parent is None:
            return None
        session_raw = (parent.metadata or {}).get("crew_session", _MISSING)
        if session_raw is _MISSING:
            return None
        session = self._parse_contract(session_raw)
        await self._validate_loaded(parent, session)
        recovery_raw = (parent.metadata or {}).get("crew_recovery", _MISSING)
        if recovery_raw is _MISSING:
            return None
        recovery = self._parse_recovery(recovery_raw)
        await self._validate_recovery_context(parent.id, recovery)
        return recovery

    async def compare_and_set_recovery(
        self,
        parent_id: str,
        recovery: CrewRecoveryContract,
        *,
        expected_session: CrewSessionContract,
        expected_recovery: CrewRecoveryContract | None,
    ) -> CrewRecoveryContract:
        """Commit one exact recovery sibling without changing coarse state."""
        parent_key = _normalize_id(parent_id)
        candidate = self._validate_recovery(recovery)
        expected_contract = self._validate_contract(expected_session)
        expected_checkpoint = (
            self._validate_recovery(expected_recovery)
            if expected_recovery is not None
            else None
        )
        self._require_preserved_plan(expected_checkpoint, candidate)
        if (
            expected_checkpoint is not None
            and _RECOVERY_PHASE_INDEX[candidate.phase]
            < _RECOVERY_PHASE_INDEX[expected_checkpoint.phase]
        ):
            raise ValueError("crew_recovery_phase_regression")
        parent = await self._work_items.get_work_item(parent_key)
        if parent is None:
            raise ValueError("crew_session_parent_not_found")
        metadata = parent.metadata or {}
        session_raw = metadata.get("crew_session", _MISSING)
        if session_raw is _MISSING:
            raise ValueError("crew_session_not_initialized")
        current_session = self._parse_contract(session_raw)
        await self._validate_loaded(parent, current_session)
        if not _json_values_exactly_equal(
            current_session.model_dump(mode="json"),
            expected_contract.model_dump(mode="json"),
        ):
            raise ValueError("crew_session_revision_conflict")
        _validate_session_recovery_invariant(current_session, candidate)
        current_recovery_raw = metadata.get("crew_recovery", _MISSING)
        if expected_checkpoint is None:
            if current_recovery_raw is not _MISSING:
                raise ValueError("crew_recovery_conflict")
            expected: dict[str, Any] = {"crew_session": session_raw}
            absent = frozenset({"crew_recovery"})
        else:
            if current_recovery_raw is _MISSING:
                raise ValueError("crew_recovery_conflict")
            current_recovery = self._parse_recovery(current_recovery_raw)
            await self._validate_recovery_context(parent.id, current_recovery)
            if not _json_values_exactly_equal(
                current_recovery.model_dump(mode="json"),
                expected_checkpoint.model_dump(mode="json"),
            ):
                raise ValueError("crew_recovery_conflict")
            expected = {
                "crew_session": session_raw,
                "crew_recovery": current_recovery_raw,
            }
            absent = frozenset()
        updated = await self._work_items.merge_work_item_metadata(
            parent.id,
            {"crew_recovery": candidate.model_dump(mode="json")},
            expected=expected,
            expected_absent_keys=absent,
            expected_work_type="crew_session",
            expected_status=_STATUS_PROJECTION[current_session.state],
            expected_assigned_to=current_session.facilitator_id,
            source="crew_session_recovery",
        )
        if updated is None:
            raise ValueError("crew_recovery_update_failed")
        authoritative = self._parse_recovery(
            updated.metadata.get("crew_recovery"),
        )
        if not _json_values_exactly_equal(
            authoritative.model_dump(mode="json"),
            candidate.model_dump(mode="json"),
        ):
            raise ValueError("crew_recovery_update_failed")
        return authoritative

    async def install_recovery_plan(
        self,
        parent_id: str,
        *,
        expected_session: CrewSessionContract,
        expected_recovery: CrewRecoveryContract | None,
        plan: CrewRecoveryPlan,
        children: tuple[WorkItemPlanInsert, ...],
    ) -> tuple[CrewRecoveryContract, tuple[WorkItem, ...]]:
        """Install one exact plan and all children through the store transaction."""
        parent_key = _normalize_id(parent_id)
        expected_contract = self._validate_contract(expected_session)
        expected_checkpoint = (
            self._validate_recovery(expected_recovery)
            if expected_recovery is not None
            else None
        )
        candidate_plan = self._validate_plan(plan)
        detached_children = _detach_plan_inserts(children)
        if len(detached_children) != len(children) or tuple(
            child.id for child in detached_children
        ) != tuple(commitment.child_id for commitment in candidate_plan.children):
            raise ValueError("crew_recovery_plan_children_invalid")
        _validate_contextual_recovery_plan(
            parent_key,
            candidate_plan,
            detached_children,
            expected_policy="derived_v1",
        )
        parent = await self._work_items.get_work_item(parent_key)
        if parent is None:
            raise ValueError("crew_session_parent_not_found")
        metadata = parent.metadata or {}
        session_raw = metadata.get("crew_session", _MISSING)
        if session_raw is _MISSING:
            raise ValueError("crew_session_not_initialized")
        current_session = self._parse_contract(session_raw)
        await self._validate_loaded(parent, current_session)
        if not _json_values_exactly_equal(
            current_session.model_dump(mode="json"),
            expected_contract.model_dump(mode="json"),
        ):
            raise ValueError("crew_session_revision_conflict")
        recovery_raw = metadata.get("crew_recovery", _MISSING)
        if expected_checkpoint is None:
            if recovery_raw is not _MISSING:
                raise ValueError("crew_recovery_conflict")
            base = self._initial_recovery()
        else:
            if recovery_raw is _MISSING:
                raise ValueError("crew_recovery_conflict")
            current_recovery = self._parse_recovery(recovery_raw)
            await self._validate_recovery_context(parent.id, current_recovery)
            if not _json_values_exactly_equal(
                current_recovery.model_dump(mode="json"),
                expected_checkpoint.model_dump(mode="json"),
            ):
                raise ValueError("crew_recovery_conflict")
            base = current_recovery
        if _RECOVERY_PHASE_INDEX[base.phase] >= _RECOVERY_PHASE_INDEX["planned"]:
            raise ValueError("crew_recovery_plan_conflict")
        values = base.model_dump(mode="json")
        values.update({
            "phase": "planned",
            "plan": candidate_plan.model_dump(mode="json"),
            "retry_count": 0,
            "next_attempt_at": None,
            "last_error_code": None,
            "interrupted_child_ids": [],
        })
        planned = self._validate_recovery(values)
        _validate_session_recovery_invariant(current_session, planned)
        commit_error: BaseException | None = None
        try:
            updated, created = (
                await self._work_items.install_child_plan_with_parent_metadata(
                    parent.id,
                    expected_parent_metadata=dict(metadata),
                    expected_status=_STATUS_PROJECTION[current_session.state],
                    expected_assigned_to=current_session.facilitator_id,
                    parent_patch={
                        "crew_recovery": planned.model_dump(mode="json"),
                    },
                    children=detached_children,
                )
            )
        except asyncio.CancelledError as exc:
            commit_error = exc
        except Exception as exc:
            commit_error = exc
        if commit_error is not None:
            if isinstance(commit_error, asyncio.CancelledError):
                reconciled, commit_cancellation = (
                    await self._reconcile_cancelled_plan_commit(
                        parent.id,
                        expected_session=current_session,
                        expected_recovery=planned,
                        expected_children=detached_children,
                        expected_policy="derived_v1",
                        first_cancellation=commit_error,
                    )
                )
            else:
                reconciled = await self._reconcile_plan_commit(
                    parent.id,
                    expected_session=current_session,
                    expected_recovery=planned,
                    expected_children=detached_children,
                    expected_policy="derived_v1",
                )
            if reconciled is None:
                raise commit_error
            authoritative, created = reconciled
            if isinstance(commit_error, asyncio.CancelledError):
                raise commit_cancellation
            return authoritative, created
        authoritative = self._parse_recovery(
            updated.metadata.get("crew_recovery"),
        )
        if not _json_values_exactly_equal(
            authoritative.model_dump(mode="json"),
            planned.model_dump(mode="json"),
        ):
            raise ValueError("crew_recovery_plan_install_failed")
        return authoritative, created

    async def adopt_recovery_plan(
        self,
        parent_id: str,
        *,
        expected_session: CrewSessionContract,
        expected_recovery: None,
        plan: CrewRecoveryPlan,
        expected_children: tuple[WorkItem, ...],
    ) -> CrewRecoveryContract:
        """Adopt one exact existing-child plan through the store snapshot barrier."""
        parent_key = _normalize_id(parent_id)
        if expected_recovery is not None:
            raise ValueError("crew_recovery_conflict")
        expected_contract = self._validate_contract(expected_session)
        candidate_plan = self._validate_plan(plan)
        if (
            type(expected_children) is not tuple
            or not expected_children
            or tuple(child.id for child in expected_children)
            != tuple(sorted(child.id for child in expected_children))
        ):
            raise ValueError("crew_recovery_plan_children_invalid")
        _validate_contextual_recovery_plan(
            parent_key,
            candidate_plan,
            expected_children,
            expected_policy="adopted_v1",
        )
        parent = await self._work_items.get_work_item(parent_key)
        if parent is None:
            raise ValueError("crew_session_parent_not_found")
        metadata = parent.metadata or {}
        session_raw = metadata.get("crew_session", _MISSING)
        if session_raw is _MISSING:
            raise ValueError("crew_session_not_initialized")
        current_session = self._parse_contract(session_raw)
        await self._validate_loaded(parent, current_session)
        if not _json_values_exactly_equal(
            current_session.model_dump(mode="json"),
            expected_contract.model_dump(mode="json"),
        ):
            raise ValueError("crew_session_revision_conflict")
        if "crew_recovery" in metadata:
            raise ValueError("crew_recovery_conflict")
        if current_session.state == "discussing":
            phase = "planned"
        elif current_session.state == "executing":
            phase = "executing"
        elif current_session.state == "verifying":
            populated = [bool(child.verification) for child in expected_children]
            phase = "children_verified" if all(populated) else "verifying_children"
        else:
            raise ValueError("crew_recovery_plan_adoption_state_invalid")
        values = self._initial_recovery().model_dump(mode="json")
        values.update({
            "phase": phase,
            "plan": candidate_plan.model_dump(mode="json"),
        })
        recovery = self._validate_recovery(values)
        _validate_session_recovery_invariant(current_session, recovery)
        commit_error: BaseException | None = None
        try:
            updated = await self._work_items.adopt_child_plan_with_parent_metadata(
                parent.id,
                expected_parent_metadata=dict(metadata),
                expected_status=_STATUS_PROJECTION[current_session.state],
                expected_assigned_to=current_session.facilitator_id,
                parent_patch={"crew_recovery": recovery.model_dump(mode="json")},
                expected_children=expected_children,
            )
        except asyncio.CancelledError as exc:
            commit_error = exc
        except Exception as exc:
            commit_error = exc
        if commit_error is not None:
            if isinstance(commit_error, asyncio.CancelledError):
                reconciled, commit_cancellation = (
                    await self._reconcile_cancelled_plan_commit(
                        parent.id,
                        expected_session=current_session,
                        expected_recovery=recovery,
                        expected_children=expected_children,
                        expected_policy="adopted_v1",
                        first_cancellation=commit_error,
                    )
                )
            else:
                reconciled = await self._reconcile_plan_commit(
                    parent.id,
                    expected_session=current_session,
                    expected_recovery=recovery,
                    expected_children=expected_children,
                    expected_policy="adopted_v1",
                )
            if reconciled is None:
                raise commit_error
            authoritative, _ = reconciled
            if isinstance(commit_error, asyncio.CancelledError):
                raise commit_cancellation
            return authoritative
        authoritative = self._parse_recovery(
            updated.metadata.get("crew_recovery"),
        )
        if not _json_values_exactly_equal(
            authoritative.model_dump(mode="json"),
            recovery.model_dump(mode="json"),
        ):
            raise ValueError("crew_recovery_plan_adoption_failed")
        return authoritative

    async def transition_session(
        self,
        parent_id: str,
        new_state: CrewSessionState,
        *,
        expected_revision: int,
        last_result_summary: str | None = None,
        blocked_reason: str | None = None,
        evidence_refs: list[str] | None = None,
        result_artifact_id: str | None = None,
        result_ref: str | None = None,
        expected_recovery: CrewRecoveryContract | None = None,
        recovery: CrewRecoveryContract | None = None,
    ) -> CrewSessionContract:
        parent_key = _normalize_id(parent_id)
        target = self._state(new_state)
        if type(expected_revision) is not int:
            raise ValueError("crew_session_revision_invalid")
        if (expected_recovery is None) != (recovery is None):
            raise ValueError("crew_recovery_pair_invalid")
        expected_checkpoint = (
            self._validate_recovery(expected_recovery)
            if expected_recovery is not None
            else None
        )
        next_checkpoint = (
            self._validate_recovery(recovery)
            if recovery is not None
            else None
        )
        if expected_checkpoint is not None and next_checkpoint is not None:
            self._require_preserved_plan(expected_checkpoint, next_checkpoint)
        if (
            expected_checkpoint is not None
            and next_checkpoint is not None
            and _RECOVERY_PHASE_INDEX[next_checkpoint.phase]
            < _RECOVERY_PHASE_INDEX[expected_checkpoint.phase]
        ):
            raise ValueError("crew_recovery_phase_regression")
        parent = await self._work_items.get_work_item(parent_key)
        if parent is None:
            raise ValueError("crew_session_parent_not_found")
        raw = (parent.metadata or {}).get("crew_session", _MISSING)
        if raw is _MISSING:
            raise ValueError("crew_session_not_initialized")
        current = self._parse_contract(raw)
        await self._validate_loaded(parent, current)
        current_recovery_raw = (parent.metadata or {}).get(
            "crew_recovery",
            _MISSING,
        )
        if expected_checkpoint is None:
            if current_recovery_raw is not _MISSING:
                raise ValueError("crew_recovery_pair_required")
        else:
            if current_recovery_raw is _MISSING:
                raise ValueError("crew_recovery_conflict")
            current_recovery = self._parse_recovery(current_recovery_raw)
            await self._validate_recovery_context(parent.id, current_recovery)
            if not _json_values_exactly_equal(
                current_recovery.model_dump(mode="json"),
                expected_checkpoint.model_dump(mode="json"),
            ):
                raise ValueError("crew_recovery_conflict")
        if expected_revision != current.revision:
            raise ValueError("crew_session_revision_conflict")
        if not is_valid_crew_session_transition(current.state, target):
            raise ValueError("crew_session_transition_invalid")

        summary = None
        if last_result_summary is not None:
            summary = _normalize_text(
                last_result_summary, maximum=4_096, allow_empty=True,
            )
        blocker = None
        if blocked_reason is not None:
            blocker = _normalize_text(
                blocked_reason, maximum=2_048, allow_empty=False,
            )
        supplied_refs = self._evidence_input(evidence_refs)
        artifact_id = (
            _normalize_id(result_artifact_id)
            if result_artifact_id is not None
            else None
        )
        result_sha = _normalize_sha(result_ref) if result_ref is not None else None

        state_changed = target != current.state
        if artifact_id is not None or result_sha is not None:
            if not state_changed or target != "done":
                raise ValueError("crew_session_result_requires_done_transition")
        if target == "blocked_needs_captain" and state_changed:
            if blocker is None:
                raise ValueError("crew_session_blocked_reason_required")
        elif blocker is not None:
            raise ValueError("crew_session_blocked_reason_unexpected")

        next_summary = current.last_result_summary
        if summary:
            next_summary = summary
        next_refs = list(current.evidence_refs)
        for ref in supplied_refs:
            if ref not in next_refs:
                next_refs.append(ref)
        if len(next_refs) > 32:
            raise ValueError("crew_session_evidence_refs_invalid")
        progress_changed = (
            next_summary != current.last_result_summary
            or tuple(next_refs) != current.evidence_refs
        )
        if not state_changed and progress_changed and current.state not in {
            "executing", "verifying",
        }:
            reason = (
                "crew_session_terminal_update_invalid"
                if current.state in _TERMINAL_STATES
                else "crew_session_progress_state_invalid"
            )
            raise ValueError(reason)
        if not state_changed and not progress_changed:
            return current

        now = self._server_time(
            current.created_at,
            current.transitioned_at,
            current.started_at,
            current.first_result_at,
            current.verified_at,
            current.completed_at,
            current.blocked_since,
        )
        values = current.model_dump(mode="json")
        values["revision"] = current.revision + 1
        values["last_result_summary"] = next_summary
        values["evidence_refs"] = next_refs
        if current.first_result_at is None and next_summary:
            values["first_result_at"] = now
        if state_changed:
            values["previous_state"] = current.state
            values["state"] = target
            values["transitioned_at"] = now
            if target == "executing" and current.started_at is None:
                values["started_at"] = now
            if target == "blocked_needs_captain":
                values["blocked_reason"] = blocker
                values["blocked_since"] = now
            elif current.state == "blocked_needs_captain":
                if current.blocked_since is None:
                    raise ValueError("crew_session_blocked_fields_invalid")
                values["blocked_duration_seconds"] = (
                    current.blocked_duration_seconds + now - current.blocked_since
                )
                values["blocked_reason"] = None
                values["blocked_since"] = None
            if target == "done":
                values["verified_at"] = now
                values["completed_at"] = now
                values["result_artifact_id"] = artifact_id
                values["result_ref"] = result_sha
            elif target == "failed":
                values["completed_at"] = now

        contract = self._validate_contract(values)
        _validate_session_recovery_invariant(contract, next_checkpoint)
        patch: dict[str, Any] = {
            "crew_session": contract.model_dump(mode="json"),
        }
        expected_metadata: dict[str, Any] = {"crew_session": raw}
        if expected_checkpoint is not None and next_checkpoint is not None:
            expected_metadata["crew_recovery"] = current_recovery_raw
            patch["crew_recovery"] = next_checkpoint.model_dump(mode="json")
        updated = await self._work_items.merge_work_item_metadata(
            parent.id,
            patch,
            expected=expected_metadata,
            expected_work_type="crew_session",
            expected_status=_STATUS_PROJECTION[current.state],
            expected_assigned_to=current.facilitator_id,
            new_status=_STATUS_PROJECTION[target],
            source="crew_session_transition",
        )
        if updated is None:
            raise ValueError("crew_session_transition_failed")
        logger.info(
            "Crew session parent=%s transitioned state=%s revision=%d; projected status=%s",
            parent.id,
            contract.state,
            contract.revision,
            _STATUS_PROJECTION[target],
        )
        return self._parse_contract(updated.metadata.get("crew_session"))

    async def publish_verified_result(
        self,
        parent_id: str,
        *,
        expected_revision: int,
        expected_recovery: CrewRecoveryContract | None,
        expected_direct_children: tuple[dict[str, Any], ...],
        crew_synth: CrewSynthesisMetadata,
        last_result_summary: str,
        provenance_ref: str,
        result_artifact_id: str,
    ) -> CrewSessionContract:
        """Atomically publish both verified refs and transition to ``done``."""
        parent_key = _normalize_id(parent_id)
        if type(expected_revision) is not int:
            raise ValueError("crew_session_revision_invalid")
        try:
            synthesis = CrewSynthesisMetadata.model_validate(crew_synth)
        except ValidationError as exc:
            raise ValueError("crew_synthesis_metadata_invalid") from exc
        summary = _normalize_text(
            last_result_summary,
            maximum=4_096,
            allow_empty=False,
        )
        provenance_sha = _normalize_sha(provenance_ref)
        artifact_id = _normalize_id(result_artifact_id)
        if (
            synthesis.provenance_ref != provenance_sha
            or synthesis.result_artifact_id != artifact_id
        ):
            raise ValueError("crew_session_publication_ref_mismatch")

        parent = await self._work_items.get_work_item(parent_key)
        if parent is None:
            raise ValueError("crew_session_parent_not_found")
        raw = (parent.metadata or {}).get("crew_session", _MISSING)
        if raw is _MISSING:
            raise ValueError("crew_session_not_initialized")
        if "crew_synth" in (parent.metadata or {}):
            raise ValueError("crew_session_publication_conflict")
        current = self._parse_contract(raw)
        await self._validate_loaded(parent, current)
        if current.state != "verifying":
            raise ValueError("crew_session_publication_state_invalid")
        if current.revision != expected_revision:
            raise ValueError("crew_session_revision_conflict")
        if synthesis.producer_agent_id != current.facilitator_id:
            raise ValueError("crew_session_publication_producer_mismatch")
        recovery_raw = (parent.metadata or {}).get("crew_recovery", _MISSING)
        published_recovery: CrewRecoveryContract | None = None
        if expected_recovery is None:
            if recovery_raw is not _MISSING:
                raise ValueError("crew_recovery_pair_required")
        else:
            checkpoint = self._validate_recovery(expected_recovery)
            if recovery_raw is _MISSING:
                raise ValueError("crew_recovery_conflict")
            current_recovery = self._parse_recovery(recovery_raw)
            await self._validate_recovery_context(parent.id, current_recovery)
            if not _json_values_exactly_equal(
                current_recovery.model_dump(mode="json"),
                checkpoint.model_dump(mode="json"),
            ) or (
                checkpoint.phase != "provenance_bound"
                or checkpoint.result_artifact_id != artifact_id
                or checkpoint.provenance_ref != provenance_sha
            ):
                raise ValueError("crew_recovery_conflict")
            recovery_values = checkpoint.model_dump(mode="json")
            recovery_values.update({
                "phase": "published",
                "retry_count": 0,
                "next_attempt_at": None,
                "last_error_code": None,
                "interrupted_child_ids": [],
            })
            published_recovery = self._validate_recovery(recovery_values)

        now = self._server_time(
            current.created_at,
            current.transitioned_at,
            current.started_at,
            current.first_result_at,
        )
        evidence_refs = list(current.evidence_refs)
        if provenance_sha not in evidence_refs:
            evidence_refs.append(provenance_sha)
        if len(evidence_refs) > 32:
            raise ValueError("crew_session_evidence_refs_invalid")
        values = current.model_dump(mode="json")
        values.update({
            "state": "done",
            "previous_state": current.state,
            "revision": current.revision + 1,
            "transitioned_at": now,
            "verified_at": now,
            "completed_at": now,
            "last_result_summary": summary,
            "evidence_refs": evidence_refs,
            "result_artifact_id": artifact_id,
            "result_ref": provenance_sha,
        })
        if current.first_result_at is None:
            values["first_result_at"] = now
        contract = self._validate_contract(values)
        _validate_session_recovery_invariant(contract, published_recovery)
        contract_json = contract.model_dump(mode="json")
        synthesis_json = synthesis.model_dump(mode="json")
        publication_patch: dict[str, Any] = {
            "crew_session": contract_json,
            "crew_synth": synthesis_json,
        }
        expected_metadata: dict[str, Any] = {"crew_session": raw}
        if published_recovery is not None:
            publication_patch["crew_recovery"] = published_recovery.model_dump(
                mode="json",
            )
            expected_metadata["crew_recovery"] = recovery_raw
        sibling_keys = frozenset(
            key
            for key in (parent.metadata or {})
            if key not in {"crew_session", "crew_synth"}
        )
        publish_error: BaseException | None = None
        try:
            await self._work_items.publish_work_item_metadata_with_child_barrier(
                parent.id,
                publication_patch,
                expected=expected_metadata,
                expected_absent_keys=frozenset({"crew_synth"}),
                expected_present_keys=sibling_keys,
                expected_work_type="crew_session",
                expected_status=_STATUS_PROJECTION[current.state],
                expected_assigned_to=current.facilitator_id,
                expected_direct_children=expected_direct_children,
                new_status="done",
                source="crew_session_verified_result",
            )
        except asyncio.CancelledError as exc:
            publish_error = exc
        except Exception as exc:
            publish_error = exc
        try:
            authoritative_contract = await self._authoritative_publication(
                parent_id=parent.id,
                facilitator_id=current.facilitator_id,
                contract_json=contract_json,
                synthesis_json=synthesis_json,
                recovery_json=(
                    published_recovery.model_dump(mode="json")
                    if published_recovery is not None
                    else None
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            if publish_error is not None:
                raise publish_error
            raise
        if authoritative_contract is not None:
            if publish_error is not None:
                logger.warning(
                    "Crew session parent=%s publication raised after the exact "
                    "done contract committed; returning the authoritative result "
                    "without rewriting unrelated metadata siblings",
                    parent.id,
                )
            else:
                logger.info(
                    "Crew session parent=%s published verified result revision=%d; "
                    "artifact and provenance refs committed atomically",
                    parent.id,
                    contract.revision,
                )
            return authoritative_contract
        if publish_error is not None:
            raise publish_error
        raise ValueError("crew_session_publication_failed")

    async def _authoritative_publication(
        self,
        *,
        parent_id: str,
        facilitator_id: str,
        contract_json: dict[str, Any],
        synthesis_json: dict[str, Any],
        recovery_json: dict[str, Any] | None,
    ) -> CrewSessionContract | None:
        authoritative = await self._work_items.get_work_item(parent_id)
        if (
            authoritative is None
            or authoritative.id != parent_id
            or authoritative.work_type != "crew_session"
            or authoritative.status != "done"
            or authoritative.assigned_to != facilitator_id
            or type(authoritative.metadata) is not dict
        ):
            return None
        metadata = authoritative.metadata
        if not _json_values_exactly_equal(
            metadata.get("crew_session", _MISSING),
            contract_json,
        ) or not _json_values_exactly_equal(
            metadata.get("crew_synth", _MISSING),
            synthesis_json,
        ) or (
            recovery_json is not None
            and not _json_values_exactly_equal(
                metadata.get("crew_recovery", _MISSING),
                recovery_json,
            )
        ):
            return None
        try:
            authoritative_contract = self._parse_contract(metadata["crew_session"])
            authoritative_synthesis = CrewSynthesisMetadata.model_validate(
                metadata["crew_synth"],
            )
            if recovery_json is not None:
                authoritative_recovery = self._parse_recovery(
                    metadata["crew_recovery"],
                )
                await self._validate_recovery_context(
                    parent_id,
                    authoritative_recovery,
                )
        except (KeyError, ValidationError, ValueError):
            return None
        if (
            authoritative_contract.result_artifact_id
            != authoritative_synthesis.result_artifact_id
            or authoritative_contract.result_ref
            != authoritative_synthesis.provenance_ref
        ):
            return None
        return authoritative_contract

    @staticmethod
    def _state(value: Any) -> CrewSessionState:
        if type(value) is not str or value not in _STATES:
            raise ValueError("crew_session_state_invalid")
        return value  # type: ignore[return-value]

    @staticmethod
    def _evidence_input(value: Any) -> list[str]:
        if value is None:
            return []
        if type(value) is not list:
            raise ValueError("crew_session_evidence_refs_invalid")
        normalized: list[str] = []
        for item in value:
            ref = _normalize_sha(item)
            if ref not in normalized:
                normalized.append(ref)
        return normalized

    def _server_time(self, *minimums: float | None) -> float:
        now = _normalize_timestamp(self._clock())
        if any(minimum is not None and now < minimum for minimum in minimums):
            raise ValueError("crew_session_clock_regression")
        return now

    @staticmethod
    def _validate_contract(value: Any) -> CrewSessionContract:
        try:
            return CrewSessionContract.model_validate(value)
        except ValidationError as exc:
            raise ValueError("crew_session_contract_invalid") from exc

    @staticmethod
    def _validate_recovery(value: Any) -> CrewRecoveryContract:
        try:
            return CrewRecoveryContract.model_validate(value)
        except ValidationError as exc:
            raise ValueError("crew_recovery_invalid") from exc

    @staticmethod
    def _validate_plan(value: Any) -> CrewRecoveryPlan:
        try:
            return CrewRecoveryPlan.model_validate(value)
        except ValidationError as exc:
            raise ValueError("crew_recovery_plan_invalid") from exc

    @staticmethod
    def _require_preserved_plan(
        expected: CrewRecoveryContract | None,
        candidate: CrewRecoveryContract,
    ) -> None:
        expected_plan = expected.plan if expected is not None else None
        if not _json_values_exactly_equal(
            (
                expected_plan.model_dump(mode="json")
                if expected_plan is not None
                else None
            ),
            (
                candidate.plan.model_dump(mode="json")
                if candidate.plan is not None
                else None
            ),
        ):
            raise ValueError("crew_recovery_plan_conflict")

    def _parse_contract(self, value: Any) -> CrewSessionContract:
        if type(value) is not dict:
            raise ValueError("crew_session_contract_invalid")
        return self._validate_contract(value)

    def _parse_recovery(self, value: Any) -> CrewRecoveryContract:
        if type(value) is not dict:
            raise ValueError("crew_recovery_invalid")
        return self._validate_recovery(value)

    async def _validate_recovery_context(
        self,
        parent_id: str,
        recovery: CrewRecoveryContract,
    ) -> tuple[WorkItem, ...]:
        if recovery.plan is None:
            return ()
        children = await self._work_items.list_work_items(
            parent_id=parent_id,
            limit=_MAX_RECOVERY_CHILDREN + 1,
        )
        if len(children) > _MAX_RECOVERY_CHILDREN:
            raise ValueError("crew_recovery_plan_integrity_invalid")
        child_tuple = tuple(children)
        _validate_contextual_recovery_plan(
            parent_id,
            recovery.plan,
            child_tuple,
        )
        return child_tuple

    async def _reconcile_cancelled_plan_commit(
        self,
        parent_id: str,
        *,
        expected_session: CrewSessionContract,
        expected_recovery: CrewRecoveryContract,
        expected_children: tuple[Any, ...],
        expected_policy: str,
        first_cancellation: asyncio.CancelledError,
    ) -> tuple[
        tuple[CrewRecoveryContract, tuple[WorkItem, ...]] | None,
        asyncio.CancelledError,
    ]:
        current_task = asyncio.current_task()
        if current_task is not None:
            current_task.uncancel()
        reconciliation = asyncio.create_task(
            self._reconcile_plan_commit(
                parent_id,
                expected_session=expected_session,
                expected_recovery=expected_recovery,
                expected_children=expected_children,
                expected_policy=expected_policy,
            ),
            name=f"crew-plan-reconcile:{expected_policy}:{parent_id}",
        )
        while not reconciliation.done():
            try:
                await asyncio.shield(reconciliation)
            except asyncio.CancelledError:
                current_task = asyncio.current_task()
                if current_task is not None:
                    current_task.uncancel()
        try:
            reconciled = reconciliation.result()
        except asyncio.CancelledError:
            logger.warning(
                "Crew session parent=%s plan reconciliation was cancelled "
                "before exact post-commit authority could be proved; the "
                "first cancellation remains authoritative and will be re-raised",
                parent_id,
            )
            reconciled = None
        except Exception:
            logger.exception(
                "Crew session parent=%s plan reconciliation could not inspect "
                "exact post-commit authority; the first cancellation remains "
                "authoritative and will be re-raised",
                parent_id,
            )
            reconciled = None
        return reconciled, first_cancellation

    async def _reconcile_plan_commit(
        self,
        parent_id: str,
        *,
        expected_session: CrewSessionContract,
        expected_recovery: CrewRecoveryContract,
        expected_children: tuple[Any, ...],
        expected_policy: str,
    ) -> tuple[CrewRecoveryContract, tuple[WorkItem, ...]] | None:
        authoritative_parent = await self._work_items.get_work_item(parent_id)
        if (
            authoritative_parent is None
            or authoritative_parent.work_type != "crew_session"
            or authoritative_parent.status
            != _STATUS_PROJECTION[expected_session.state]
            or authoritative_parent.assigned_to != expected_session.facilitator_id
            or type(authoritative_parent.metadata) is not dict
            or not _json_values_exactly_equal(
                authoritative_parent.metadata.get("crew_session", _MISSING),
                expected_session.model_dump(mode="json"),
            )
            or not _json_values_exactly_equal(
                authoritative_parent.metadata.get("crew_recovery", _MISSING),
                expected_recovery.model_dump(mode="json"),
            )
            or expected_recovery.plan is None
        ):
            return None
        try:
            await self._validate_loaded(authoritative_parent, expected_session)
            live_children = await self._work_items.list_work_items(
                parent_id=parent_id,
                limit=_MAX_RECOVERY_CHILDREN + 1,
            )
            if len(live_children) > _MAX_RECOVERY_CHILDREN:
                return None
            live_by_id = {child.id: child for child in live_children}
            if (
                len(live_by_id) != len(live_children)
                or set(live_by_id)
                != {getattr(child, "id", None) for child in expected_children}
            ):
                return None
            live_tuple = tuple(live_by_id[commitment.child_id] for commitment in expected_recovery.plan.children)
            _validate_contextual_recovery_plan(
                parent_id,
                expected_recovery.plan,
                live_tuple,
                expected_policy=expected_policy,
            )
            if expected_policy == "adopted_v1":
                expected_by_id = {
                    child.id: child for child in expected_children
                }
                if any(
                    not _json_values_exactly_equal(
                        child.to_dict(),
                        expected_by_id[child.id].to_dict(),
                    )
                    for child in live_tuple
                ):
                    return None
            else:
                expected_by_id = {
                    child.id: child for child in expected_children
                }
                for child in live_tuple:
                    expected = expected_by_id[child.id]
                    if (
                        child.title != expected.title
                        or child.description != expected.description
                        or child.work_type != expected.work_type
                        or child.priority != expected.priority
                        or child.parent_id != parent_id
                        or child.depends_on != list(expected.depends_on)
                        or child.assigned_to != expected.assigned_to
                        or child.created_by != expected.created_by
                        or child.trust_requirement != expected.trust_requirement
                        or child.required_capabilities
                        != list(expected.required_capabilities)
                        or not _json_values_exactly_equal(
                            child.metadata,
                            expected.metadata,
                        )
                    ):
                        return None
        except (ValidationError, ValueError):
            return None
        return expected_recovery, live_tuple

    @staticmethod
    def _initial_recovery() -> CrewRecoveryContract:
        return CrewRecoveryContract.model_validate({
            "version": 1,
            "phase": "unplanned",
            "plan": None,
            "attempt_count": 0,
            "retry_count": 0,
            "last_attempt_at": None,
            "next_attempt_at": None,
            "last_error_code": None,
            "interrupted_child_ids": [],
            "synthesis_ref": None,
            "final_verification_ref": None,
            "result_artifact_id": None,
            "provenance_ref": None,
        })

    def _build_initial_contract(
        self,
        *,
        parent: WorkItem,
        thread_id: str,
        goal: str,
        origin: CrewSessionOrigin,
        originator_id: str,
        facilitator_id: str,
        owner_ids: list[str],
        success_criteria: list[str],
        expected_deliverable: str,
        transitioned_at: float,
    ) -> CrewSessionContract:
        return self._validate_contract({
            "version": 1,
            "state": "discussing",
            "previous_state": None,
            "revision": 1,
            "goal": goal,
            "origin": origin,
            "originator_id": originator_id,
            "facilitator_id": facilitator_id,
            "owner_ids": owner_ids,
            "success_criteria": success_criteria,
            "expected_deliverable": expected_deliverable,
            "thread_id": thread_id,
            "task_id": parent.id,
            "created_at": parent.created_at,
            "transitioned_at": transitioned_at,
            "started_at": None,
            "first_result_at": None,
            "verified_at": None,
            "completed_at": None,
            "last_result_summary": "",
            "blocked_reason": None,
            "blocked_since": None,
            "blocked_duration_seconds": 0.0,
            "evidence_refs": [],
            "result_artifact_id": None,
            "result_ref": None,
            "duplicate_resume_count": 0,
        })

    @staticmethod
    def _initial_fields(contract: CrewSessionContract) -> tuple[Any, ...]:
        return (
            contract.goal,
            contract.origin,
            contract.originator_id,
            contract.facilitator_id,
            contract.owner_ids,
            contract.success_criteria,
            contract.expected_deliverable,
            contract.thread_id,
            contract.task_id,
            contract.created_at,
        )

    async def _validate_loaded(
        self, parent: WorkItem, contract: CrewSessionContract,
    ) -> None:
        if parent.work_type != "crew_session":
            raise ValueError("crew_session_parent_type_invalid")
        if contract.task_id != parent.id:
            raise ValueError("crew_session_task_mismatch")
        if contract.created_at != parent.created_at:
            raise ValueError("crew_session_created_at_mismatch")
        if parent.assigned_to != contract.facilitator_id:
            raise ValueError("crew_session_facilitator_assignment_mismatch")
        projected = _STATUS_PROJECTION[contract.state]
        if parent.status != projected:
            raise ValueError("crew_session_projection_mismatch")
        metadata = parent.metadata
        if type(metadata) is not dict:
            raise ValueError("crew_session_contract_invalid")
        recovery_raw = metadata.get("crew_recovery", _MISSING)
        recovery = (
            None
            if recovery_raw is _MISSING
            else self._parse_recovery(recovery_raw)
        )
        _validate_session_recovery_invariant(contract, recovery)
        await self._validate_room(parent.id, contract.thread_id)

    async def _validate_room(self, parent_id: str, thread_id: str) -> None:
        thread = await asyncio.to_thread(self._threads.get_thread, thread_id)
        if thread is None:
            raise ValueError("crew_session_thread_not_found")
        if thread.task_id != parent_id:
            raise ValueError("crew_session_thread_task_mismatch")
        rooms = await asyncio.to_thread(
            self._threads.list_threads,
            task_id=parent_id,
            include_archived=True,
            limit=2,
        )
        if len(rooms) != 1:
            raise ValueError("crew_session_thread_cardinality_invalid")
        if rooms[0].id != thread_id:
            raise ValueError("crew_session_thread_mismatch")