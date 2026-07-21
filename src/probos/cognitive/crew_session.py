"""AD-1124: durable CrewSession contract and storage service."""

from __future__ import annotations

import asyncio
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
    from probos.workforce import WorkItem

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
_MISSING = object()


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


class _WorkItemStoreProtocol(Protocol):
    async def get_work_item(self, work_item_id: str) -> WorkItem | None: ...

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
    ) -> CrewSessionContract:
        parent_key = _normalize_id(parent_id)
        target = self._state(new_state)
        if type(expected_revision) is not int:
            raise ValueError("crew_session_revision_invalid")
        parent = await self._work_items.get_work_item(parent_key)
        if parent is None:
            raise ValueError("crew_session_parent_not_found")
        raw = (parent.metadata or {}).get("crew_session", _MISSING)
        if raw is _MISSING:
            raise ValueError("crew_session_not_initialized")
        current = self._parse_contract(raw)
        await self._validate_loaded(parent, current)
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
        updated = await self._work_items.merge_work_item_metadata(
            parent.id,
            {"crew_session": contract.model_dump(mode="json")},
            expected={"crew_session": raw},
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
        contract_json = contract.model_dump(mode="json")
        synthesis_json = synthesis.model_dump(mode="json")
        sibling_keys = frozenset(
            key
            for key in (parent.metadata or {})
            if key not in {"crew_session", "crew_synth"}
        )
        publish_error: BaseException | None = None
        try:
            await self._work_items.publish_work_item_metadata_with_child_barrier(
                parent.id,
                {
                    "crew_session": contract_json,
                    "crew_synth": synthesis_json,
                },
                expected={"crew_session": raw},
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
        ):
            return None
        try:
            authoritative_contract = self._parse_contract(metadata["crew_session"])
            authoritative_synthesis = CrewSynthesisMetadata.model_validate(
                metadata["crew_synth"],
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

    def _parse_contract(self, value: Any) -> CrewSessionContract:
        if type(value) is not dict:
            raise ValueError("crew_session_contract_invalid")
        return self._validate_contract(value)

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