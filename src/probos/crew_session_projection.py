"""Pure, bounded HXI projections for validated CrewSession state."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from probos.cognitive.crew_session import (
    CrewSessionContract,
    CrewSessionOrigin,
    CrewSessionState,
    CrewSynthesisMetadata,
)
from probos.workforce import WorkItem, WorkItemStatus


CREW_SESSION_PROJECTION_ERROR = "crew_session_projection_invalid"
_MAX_CHILDREN = 1_000
_MAX_ID_CHARS = 128
_MAX_ID_BYTES = 512
_MAX_TITLE_CHARS = 4_096
_MAX_TITLE_BYTES = 16_384
_ACTIVE_STATUS_RANK = {
    WorkItemStatus.IN_PROGRESS.value: 0,
    WorkItemStatus.REVIEW.value: 1,
    WorkItemStatus.BLOCKED.value: 2,
    WorkItemStatus.SCHEDULED.value: 3,
    WorkItemStatus.OPEN.value: 4,
    WorkItemStatus.DRAFT.value: 5,
}
_KNOWN_STATUSES = frozenset(status.value for status in WorkItemStatus)
_FAILED_STATUSES = frozenset({
    WorkItemStatus.FAILED.value,
    WorkItemStatus.CANCELLED.value,
})


class CrewSessionProjectionError(ValueError):
    """Stable conflict raised for every invalid projection input."""

    def __init__(self) -> None:
        super().__init__(CREW_SESSION_PROJECTION_ERROR)


@dataclass(frozen=True, slots=True)
class CrewSessionTimestampsProjection:
    created_at: float
    transitioned_at: float
    started_at: float | None
    first_result_at: float | None
    verified_at: float | None
    completed_at: float | None


@dataclass(frozen=True, slots=True)
class CrewSessionActiveChildProjection:
    id: str
    title: str
    status: str
    owner_id: str | None


@dataclass(frozen=True, slots=True)
class CrewSessionProgressProjection:
    total: int
    done: int
    failed: int
    active: int
    active_child: CrewSessionActiveChildProjection | None


@dataclass(frozen=True, slots=True)
class CrewSessionBlockerProjection:
    reason: str
    since: float
    duration_seconds: float
    action: Literal["retry_start_work"] = "retry_start_work"


@dataclass(frozen=True, slots=True)
class CrewSessionResultProjection:
    artifact_id: str
    content_hash: str
    result_ref: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CrewSessionVerificationProjection:
    verifier_agent_id: str
    confidence: float
    critique: str
    accepted_count: int
    total_count: int
    convergence_rounds: int


@dataclass(frozen=True, slots=True)
class CrewSessionDetailProjection:
    task_id: str
    thread_id: str
    goal: str
    origin: CrewSessionOrigin
    originator_id: str
    facilitator_id: str
    owner_ids: tuple[str, ...]
    state: CrewSessionState
    revision: int
    success_criteria: tuple[str, ...]
    expected_deliverable: str
    timestamps: CrewSessionTimestampsProjection
    progress: CrewSessionProgressProjection
    last_result_summary: str
    blocker: CrewSessionBlockerProjection | None
    result: CrewSessionResultProjection | None
    verification: CrewSessionVerificationProjection | None
    duplicate_resume_count: int

    def to_wire(self) -> dict[str, object]:
        active_child = self.progress.active_child
        blocker = self.blocker
        result = self.result
        verification = self.verification
        return {
            "task_id": self.task_id,
            "thread_id": self.thread_id,
            "goal": self.goal,
            "origin": self.origin,
            "originator_id": self.originator_id,
            "facilitator_id": self.facilitator_id,
            "owner_ids": list(self.owner_ids),
            "state": self.state,
            "revision": self.revision,
            "success_criteria": list(self.success_criteria),
            "expected_deliverable": self.expected_deliverable,
            "timestamps": {
                "created_at": self.timestamps.created_at,
                "transitioned_at": self.timestamps.transitioned_at,
                "started_at": self.timestamps.started_at,
                "first_result_at": self.timestamps.first_result_at,
                "verified_at": self.timestamps.verified_at,
                "completed_at": self.timestamps.completed_at,
            },
            "progress": {
                "total": self.progress.total,
                "done": self.progress.done,
                "failed": self.progress.failed,
                "active": self.progress.active,
                "active_child": None if active_child is None else {
                    "id": active_child.id,
                    "title": active_child.title,
                    "status": active_child.status,
                    "owner_id": active_child.owner_id,
                },
            },
            "last_result_summary": self.last_result_summary,
            "blocker": None if blocker is None else {
                "reason": blocker.reason,
                "since": blocker.since,
                "duration_seconds": blocker.duration_seconds,
                "action": blocker.action,
            },
            "result": None if result is None else {
                "artifact_id": result.artifact_id,
                "content_hash": result.content_hash,
                "result_ref": result.result_ref,
                "evidence_refs": list(result.evidence_refs),
            },
            "verification": None if verification is None else {
                "verifier_agent_id": verification.verifier_agent_id,
                "confidence": verification.confidence,
                "critique": verification.critique,
                "accepted_count": verification.accepted_count,
                "total_count": verification.total_count,
                "convergence_rounds": verification.convergence_rounds,
            },
            "duplicate_resume_count": self.duplicate_resume_count,
        }


@dataclass(frozen=True, slots=True)
class CrewSessionSummaryBlockerProjection:
    reason: str
    since: float
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class CrewSessionSummaryProjection:
    task_id: str
    thread_id: str
    goal: str
    state: CrewSessionState
    facilitator_id: str
    owner_ids: tuple[str, ...]
    progress: CrewSessionProgressProjection
    last_result_summary: str
    blocker: CrewSessionSummaryBlockerProjection | None
    needs_attention: bool
    result_artifact_id: str | None
    verified_at: float | None

    def to_wire(self) -> dict[str, object]:
        blocker = self.blocker
        return {
            "task_id": self.task_id,
            "thread_id": self.thread_id,
            "goal": self.goal,
            "state": self.state,
            "facilitator_id": self.facilitator_id,
            "owner_ids": list(self.owner_ids),
            "progress": {
                "total": self.progress.total,
                "done": self.progress.done,
                "failed": self.progress.failed,
                "active": self.progress.active,
            },
            "last_result_summary": self.last_result_summary,
            "blocker": None if blocker is None else {
                "reason": blocker.reason,
                "since": blocker.since,
                "duration_seconds": blocker.duration_seconds,
            },
            "needs_attention": self.needs_attention,
            "result_artifact_id": self.result_artifact_id,
            "verified_at": self.verified_at,
        }


def _invalid() -> CrewSessionProjectionError:
    return CrewSessionProjectionError()


def _bounded_id(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise _invalid()
    if len(value) > _MAX_ID_CHARS or any(ord(char) < 32 for char in value):
        raise _invalid()
    try:
        if len(value.encode("utf-8")) > _MAX_ID_BYTES:
            raise _invalid()
    except UnicodeEncodeError as exc:
        raise _invalid() from exc
    return value


def _bounded_title(value: object) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise _invalid()
    if len(value) > _MAX_TITLE_CHARS:
        raise _invalid()
    try:
        if len(value.encode("utf-8")) > _MAX_TITLE_BYTES:
            raise _invalid()
    except UnicodeEncodeError as exc:
        raise _invalid() from exc
    return value


def _child_sort_key(child: WorkItem) -> tuple[int, int, float, str]:
    if type(child.priority) is not int or not 1 <= child.priority <= 5:
        raise _invalid()
    if (
        type(child.created_at) not in (int, float)
        or not math.isfinite(float(child.created_at))
        or float(child.created_at) < 0.0
    ):
        raise _invalid()
    return (
        _ACTIVE_STATUS_RANK[child.status],
        child.priority,
        float(child.created_at),
        child.id,
    )


def _validate_children(
    session: CrewSessionContract,
    children: Sequence[WorkItem],
) -> tuple[WorkItem, ...]:
    try:
        if len(children) > _MAX_CHILDREN:
            raise _invalid()
        validated = tuple(children)
    except CrewSessionProjectionError:
        raise
    except Exception as exc:
        raise _invalid() from exc
    if len(validated) > _MAX_CHILDREN:
        raise _invalid()
    seen_ids: set[str] = set()
    for child in validated:
        if type(child) is not WorkItem or child.parent_id != session.task_id:
            raise _invalid()
        child_id = _bounded_id(child.id)
        if child_id in seen_ids:
            raise _invalid()
        seen_ids.add(child_id)
        if type(child.status) is not str or child.status not in _KNOWN_STATUSES:
            raise _invalid()
        _bounded_title(child.title)
        if child.assigned_to is not None:
            _bounded_id(child.assigned_to)
        if child.status in _ACTIVE_STATUS_RANK:
            _child_sort_key(child)
    return validated


def validate_synthesis_metadata(value: object) -> CrewSynthesisMetadata:
    try:
        if type(value) is CrewSynthesisMetadata:
            return value
        return CrewSynthesisMetadata.model_validate(value)
    except Exception as exc:
        raise _invalid() from exc


def build_crew_session_detail(
    *,
    session: CrewSessionContract,
    synthesis: CrewSynthesisMetadata | None,
    children: Sequence[WorkItem],
) -> CrewSessionDetailProjection:
    try:
        if type(session) is not CrewSessionContract:
            raise _invalid()
        if synthesis is not None and type(synthesis) is not CrewSynthesisMetadata:
            raise _invalid()
        validated_children = _validate_children(session, children)
        if session.state == "done":
            if synthesis is None:
                raise _invalid()
            if (
                synthesis.result_artifact_id != session.result_artifact_id
                or synthesis.provenance_ref != session.result_ref
                or synthesis.provenance_ref not in session.evidence_refs
            ):
                raise _invalid()
        elif synthesis is not None:
            raise _invalid()

        done_count = sum(
            child.status == WorkItemStatus.DONE.value
            for child in validated_children
        )
        failed_count = sum(
            child.status in _FAILED_STATUSES
            for child in validated_children
        )
        active_children = tuple(
            child for child in validated_children
            if child.status != WorkItemStatus.DONE.value
            and child.status not in _FAILED_STATUSES
        )
        selected_child = min(active_children, key=_child_sort_key, default=None)
        active_child = None if selected_child is None else (
            CrewSessionActiveChildProjection(
                id=selected_child.id,
                title=selected_child.title,
                status=selected_child.status,
                owner_id=selected_child.assigned_to,
            )
        )
        progress = CrewSessionProgressProjection(
            total=len(validated_children),
            done=done_count,
            failed=failed_count,
            active=len(active_children),
            active_child=active_child,
        )
        blocker = None
        if session.state == "blocked_needs_captain":
            if session.blocked_reason is None or session.blocked_since is None:
                raise _invalid()
            blocker = CrewSessionBlockerProjection(
                reason=session.blocked_reason,
                since=session.blocked_since,
                duration_seconds=session.blocked_duration_seconds,
            )

        result = None
        verification = None
        if session.state == "done":
            if (
                synthesis is None
                or session.result_artifact_id is None
                or session.result_ref is None
            ):
                raise _invalid()
            result = CrewSessionResultProjection(
                artifact_id=session.result_artifact_id,
                content_hash=synthesis.result_content_hash,
                result_ref=session.result_ref,
                evidence_refs=session.evidence_refs,
            )
            verification = CrewSessionVerificationProjection(
                verifier_agent_id=synthesis.final_verifier_agent_id,
                confidence=synthesis.final_confidence,
                critique=synthesis.final_critique,
                accepted_count=synthesis.accepted_count,
                total_count=synthesis.total_count,
                convergence_rounds=synthesis.convergence_rounds,
            )

        return CrewSessionDetailProjection(
            task_id=session.task_id,
            thread_id=session.thread_id,
            goal=session.goal,
            origin=session.origin,
            originator_id=session.originator_id,
            facilitator_id=session.facilitator_id,
            owner_ids=session.owner_ids,
            state=session.state,
            revision=session.revision,
            success_criteria=session.success_criteria,
            expected_deliverable=session.expected_deliverable,
            timestamps=CrewSessionTimestampsProjection(
                created_at=session.created_at,
                transitioned_at=session.transitioned_at,
                started_at=session.started_at,
                first_result_at=session.first_result_at,
                verified_at=session.verified_at,
                completed_at=session.completed_at,
            ),
            progress=progress,
            last_result_summary=session.last_result_summary,
            blocker=blocker,
            result=result,
            verification=verification,
            duplicate_resume_count=session.duplicate_resume_count,
        )
    except CrewSessionProjectionError:
        raise
    except Exception as exc:
        raise _invalid() from exc


def build_crew_session_summary(
    detail: CrewSessionDetailProjection,
) -> CrewSessionSummaryProjection:
    try:
        if type(detail) is not CrewSessionDetailProjection:
            raise _invalid()
        blocker = None if detail.blocker is None else (
            CrewSessionSummaryBlockerProjection(
                reason=detail.blocker.reason,
                since=detail.blocker.since,
                duration_seconds=detail.blocker.duration_seconds,
            )
        )
        result_artifact_id = (
            None if detail.result is None else detail.result.artifact_id
        )
        return CrewSessionSummaryProjection(
            task_id=detail.task_id,
            thread_id=detail.thread_id,
            goal=detail.goal,
            state=detail.state,
            facilitator_id=detail.facilitator_id,
            owner_ids=detail.owner_ids,
            progress=detail.progress,
            last_result_summary=detail.last_result_summary,
            blocker=blocker,
            needs_attention=detail.state == "blocked_needs_captain",
            result_artifact_id=result_artifact_id,
            verified_at=detail.timestamps.verified_at,
        )
    except CrewSessionProjectionError:
        raise
    except Exception as exc:
        raise _invalid() from exc