"""AD-1126: verified CrewSession finalization and result publication."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass, replace
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from probos.cognitive.crew_session import CrewSynthesisMetadata
from probos.cognitive.crew_trust import (
    MAX_CREW_TRUST_EFFECTS,
    CrewSessionTrustRecorder,
    CrewTrustEffect,
    derive_completed_crew_trust_effects,
    derive_convergence_exhausted_effects,
    derive_final_refutation_effects,
)
from probos.cognitive.crew_verifier import (
    SessionConvergenceOutcome,
    SessionCorrectionTerminalAttempt,
    SessionVerificationFailureCode,
    SessionVerificationPass,
    SessionVerificationRound,
    validate_session_denied_tools,
)

if TYPE_CHECKING:
    from probos.artifacts import Artifact, ArtifactStore
    from probos.attachments.store import AttachmentStore
    from probos.cognitive.crew_executor import SubtaskResult
    from probos.cognitive.crew_session import CrewSessionContract, CrewSessionService
    from probos.cognitive.crew_synth import CrewSynthesizer, SessionSynthesisDraft
    from probos.cognitive.crew_verifier import SubtaskVerifier
    from probos.substrate.registry import AgentRegistry
    from probos.threads import ChatThreadStore
    from probos.workforce import WorkItem, WorkItemStore

logger = logging.getLogger(__name__)

_CheckpointValue = TypeVar("_CheckpointValue")

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_CHILDREN = 1_000
_MAX_RESULT_BYTES = 65_536
_MAX_INSTRUCTIONS_BYTES = 32_768
_MAX_FINAL_BYTES = 262_144
_MAX_EXPECTED_PROMPT_BYTES = 262_144
_MAX_VERIFICATION_BYTES = 262_144
_MAX_PROVENANCE_BYTES = 1_048_576
_MAX_CHILD_SNAPSHOT_BYTES = 1_572_864
_MAX_TOKEN_TOTAL = 9_223_372_036_854_775_807
_ARTIFACT_KEYS = {
    "artifact_id",
    "content_hash",
    "thread_id",
    "name",
    "mime",
    "size_bytes",
    "version",
}
_EXECUTION_KEYS = {
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
}


def _id(value: Any) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ValueError("crew_finalization_id_invalid")
    return value


def _sha(value: Any) -> str:
    if type(value) is not str or _SHA_RE.fullmatch(value) is None:
        raise ValueError("crew_finalization_ref_invalid")
    return value


def _text(
    value: Any,
    *,
    maximum_codepoints: int,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> str:
    if type(value) is not str or "\x00" in value:
        raise ValueError("crew_finalization_text_invalid")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise ValueError("crew_finalization_text_invalid")
    if (
        len(normalized) > maximum_codepoints
        or len(normalized.encode("utf-8")) > maximum_bytes
    ):
        raise ValueError("crew_finalization_text_invalid")
    return normalized


def _exact_int(value: Any, *, minimum: int = 0, maximum: int = _MAX_TOKEN_TOTAL) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("crew_finalization_integer_invalid")
    return value


def _compact_bytes(value: Any, *, maximum: int, error: str) -> bytes:
    try:
        blob = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError(error) from exc
    if len(blob) > maximum:
        raise ValueError(error)
    return blob


def _detached(value: Any) -> Any:
    return json.loads(_compact_bytes(value, maximum=_MAX_PROVENANCE_BYTES, error="crew_finalization_json_invalid"))


def _json_exactly_equal(current: Any, expected: Any) -> bool:
    if type(current) is not type(expected):
        return False
    if type(current) is dict:
        if (
            any(type(key) is not str for key in current)
            or any(type(key) is not str for key in expected)
            or current.keys() != expected.keys()
        ):
            return False
        return all(
            _json_exactly_equal(current[key], expected[key])
            for key in current
        )
    if type(current) is list:
        return len(current) == len(expected) and all(
            _json_exactly_equal(current_value, expected_value)
            for current_value, expected_value in zip(current, expected)
        )
    if current is None:
        return True
    if type(current) in (bool, int, float, str):
        return current == expected
    return False


def _execution_summary(value: str) -> str:
    normalized = value.strip()
    marker = "...[truncated]"
    if len(normalized) <= 4_096:
        return normalized
    return normalized[: 4_096 - len(marker)] + marker


class _ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    artifact_id: str
    content_hash: str
    thread_id: str
    name: str
    mime: str
    size_bytes: int
    version: int

    @field_validator("artifact_id", "thread_id", mode="before")
    @classmethod
    def _validate_id(cls, value: Any) -> str:
        return _id(value)

    @field_validator("content_hash", mode="before")
    @classmethod
    def _validate_hash(cls, value: Any) -> str:
        return _sha(value)

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, value: Any) -> str:
        normalized = _text(
            value,
            maximum_codepoints=255,
            maximum_bytes=1_024,
        )
        if "/" in normalized or "\\" in normalized:
            raise ValueError("crew_finalization_artifact_invalid")
        return normalized

    @field_validator("mime", mode="before")
    @classmethod
    def _validate_mime(cls, value: Any) -> str:
        return _text(value, maximum_codepoints=255, maximum_bytes=1_024)

    @field_validator("size_bytes", mode="before")
    @classmethod
    def _validate_size(cls, value: Any) -> int:
        return _exact_int(value, minimum=1, maximum=26_214_400)

    @field_validator("version", mode="before")
    @classmethod
    def _validate_version(cls, value: Any) -> int:
        return _exact_int(value, minimum=1, maximum=2_147_483_647)


class _VerdictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    status: Literal["accepted", "refuted", "unavailable", "malformed", "error"]
    accepted: bool
    confidence: float
    critique: str
    verifier_agent_id: str
    tokens_used: int
    failure_code: SessionVerificationFailureCode | None

    @field_validator("accepted", mode="before")
    @classmethod
    def _validate_bool(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("crew_finalization_verdict_invalid")
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def _validate_confidence(cls, value: Any) -> float:
        if type(value) not in (int, float):
            raise ValueError("crew_finalization_verdict_invalid")
        normalized = float(value)
        if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
            raise ValueError("crew_finalization_verdict_invalid")
        return normalized

    @field_validator("critique", mode="before")
    @classmethod
    def _validate_critique(cls, value: Any) -> str:
        return _text(
            value,
            maximum_codepoints=2_048,
            maximum_bytes=8_192,
            allow_empty=True,
        )

    @field_validator("verifier_agent_id", mode="before")
    @classmethod
    def _validate_verifier(cls, value: Any) -> str:
        if value == "":
            return value
        return _id(value)

    @field_validator("tokens_used", mode="before")
    @classmethod
    def _validate_tokens(cls, value: Any) -> int:
        return _exact_int(value)

    @model_validator(mode="after")
    def _validate_consistency(self) -> _VerdictRecord:
        if self.accepted != (self.status == "accepted"):
            raise ValueError("crew_finalization_verdict_invalid")
        if self.status in {"accepted", "refuted"}:
            if self.failure_code is not None or not self.verifier_agent_id:
                raise ValueError("crew_finalization_verdict_invalid")
        elif self.failure_code is None:
            raise ValueError("crew_finalization_verdict_invalid")
        if self.accepted and not self.critique:
            raise ValueError("crew_finalization_verdict_invalid")
        if (
            self.status == "unavailable"
            and self.failure_code != "independent_verifier_unavailable"
        ):
            raise ValueError("crew_finalization_verdict_invalid")
        if (
            self.status in {"malformed", "error"}
            and self.failure_code != "verification_defect"
        ):
            raise ValueError("crew_finalization_verdict_invalid")
        return self


class _RoundRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    round_index: int
    result_revision: int
    result_sha256: str
    result_summary: str
    stopped_reason: Literal["complete"]
    correction_tokens: int
    verifier_tokens: int
    tool_trace_ref: str | None
    artifact_refs: tuple[_ArtifactRef, ...]
    verdict: _VerdictRecord

    @field_validator("round_index", mode="before")
    @classmethod
    def _validate_round(cls, value: Any) -> int:
        return _exact_int(value, maximum=8)

    @field_validator("result_revision", mode="before")
    @classmethod
    def _validate_revision(cls, value: Any) -> int:
        return _exact_int(value, minimum=1, maximum=9)

    @field_validator("result_sha256", mode="before")
    @classmethod
    def _validate_result_hash(cls, value: Any) -> str:
        return _sha(value)

    @field_validator("result_summary", mode="before")
    @classmethod
    def _validate_summary(cls, value: Any) -> str:
        return _text(
            value,
            maximum_codepoints=4_096,
            maximum_bytes=16_384,
        )

    @field_validator("correction_tokens", "verifier_tokens", mode="before")
    @classmethod
    def _validate_token_count(cls, value: Any) -> int:
        return _exact_int(value)

    @field_validator("tool_trace_ref", mode="before")
    @classmethod
    def _validate_trace(cls, value: Any) -> str | None:
        return None if value is None else _sha(value)

    @field_validator("artifact_refs", mode="before")
    @classmethod
    def _validate_refs(cls, value: Any) -> Any:
        if type(value) not in (list, tuple) or len(value) > 32:
            raise ValueError("crew_finalization_artifact_invalid")
        return tuple(value)

    @model_validator(mode="after")
    def _validate_round_consistency(self) -> _RoundRecord:
        if self.result_revision != self.round_index + 1:
            raise ValueError("crew_finalization_round_invalid")
        if self.verifier_tokens != self.verdict.tokens_used:
            raise ValueError("crew_finalization_round_invalid")
        if self.round_index == 0 and self.correction_tokens != 0:
            raise ValueError("crew_finalization_round_invalid")
        return self


class _TerminalAttemptRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    attempt_index: int
    attempted_revision: int
    stopped_reason: Literal[
        "complete",
        "error",
        "max_iterations",
        "token_budget",
        "execution_exception",
    ]
    result_sha256: str | None
    result_summary: str
    correction_tokens: int
    tool_trace_ref: str | None
    artifact_refs: tuple[_ArtifactRef, ...]
    denied_tools: tuple[str, ...]
    failure_code: Literal[
        "correction_capability_denied",
        "correction_budget_exhausted",
        "correction_execution_defect",
    ]

    @field_validator("attempt_index", mode="before")
    @classmethod
    def _validate_attempt(cls, value: Any) -> int:
        return _exact_int(value, minimum=1, maximum=8)

    @field_validator("attempted_revision", mode="before")
    @classmethod
    def _validate_attempted_revision(cls, value: Any) -> int:
        return _exact_int(value, minimum=1, maximum=10)

    @field_validator("result_sha256", mode="before")
    @classmethod
    def _validate_optional_result_hash(cls, value: Any) -> str | None:
        return None if value is None else _sha(value)

    @field_validator("result_summary", mode="before")
    @classmethod
    def _validate_terminal_summary(cls, value: Any) -> str:
        return _text(
            value,
            maximum_codepoints=4_096,
            maximum_bytes=16_384,
            allow_empty=True,
        )

    @field_validator("correction_tokens", mode="before")
    @classmethod
    def _validate_terminal_tokens(cls, value: Any) -> int:
        return _exact_int(value)

    @field_validator("tool_trace_ref", mode="before")
    @classmethod
    def _validate_terminal_trace(cls, value: Any) -> str | None:
        return None if value is None else _sha(value)

    @field_validator("artifact_refs", mode="before")
    @classmethod
    def _validate_terminal_refs(cls, value: Any) -> Any:
        if type(value) not in (list, tuple) or len(value) > 32:
            raise ValueError("crew_finalization_artifact_invalid")
        return tuple(value)

    @field_validator("denied_tools", mode="before")
    @classmethod
    def _validate_denied_tools(cls, value: Any) -> tuple[str, ...]:
        validated = validate_session_denied_tools(value)
        if validated is None:
            raise ValueError("crew_finalization_denied_tools_invalid")
        return validated

    @model_validator(mode="after")
    def _validate_terminal_consistency(self) -> _TerminalAttemptRecord:
        if (
            self.failure_code == "correction_capability_denied"
            and not self.denied_tools
        ):
            raise ValueError("crew_finalization_terminal_invalid")
        if self.failure_code == "correction_budget_exhausted":
            if self.stopped_reason != "token_budget" or self.denied_tools:
                raise ValueError("crew_finalization_terminal_invalid")
        return self


class ChildVerificationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: Literal[1]
    parent_id: str
    work_item_id: str
    thread_id: str
    producer_agent_id: str
    status: Literal["converged", "unverified", "blocked", "failed"]
    accepted: bool
    rounds_used: int
    result_revision_count: int
    rounds: tuple[_RoundRecord, ...]
    failure_code: SessionVerificationFailureCode | None
    terminal_attempt: _TerminalAttemptRecord | None

    @field_validator("version", mode="before")
    @classmethod
    def _validate_version(cls, value: Any) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("crew_finalization_version_invalid")
        return value

    @field_validator("parent_id", "work_item_id", "thread_id", "producer_agent_id", mode="before")
    @classmethod
    def _validate_ids(cls, value: Any) -> str:
        return _id(value)

    @field_validator("accepted", mode="before")
    @classmethod
    def _validate_accepted(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("crew_finalization_verification_invalid")
        return value

    @field_validator("rounds_used", mode="before")
    @classmethod
    def _validate_rounds_used(cls, value: Any) -> int:
        return _exact_int(value, maximum=8)

    @field_validator("result_revision_count", mode="before")
    @classmethod
    def _validate_revision_count(cls, value: Any) -> int:
        return _exact_int(value, minimum=1, maximum=9)

    @field_validator("rounds", mode="before")
    @classmethod
    def _validate_rounds(cls, value: Any) -> Any:
        if type(value) not in (list, tuple) or not 1 <= len(value) <= 9:
            raise ValueError("crew_finalization_round_invalid")
        return tuple(value)

    @model_validator(mode="after")
    def _validate_consistency(self) -> ChildVerificationRecord:
        if self.result_revision_count != len(self.rounds):
            raise ValueError("crew_finalization_verification_invalid")
        if tuple(item.round_index for item in self.rounds) != tuple(range(len(self.rounds))):
            raise ValueError("crew_finalization_verification_invalid")
        if self.accepted != (self.status == "converged"):
            raise ValueError("crew_finalization_verification_invalid")
        if self.status == "converged" and self.failure_code is not None:
            raise ValueError("crew_finalization_verification_invalid")
        if self.status != "converged" and self.failure_code is None:
            raise ValueError("crew_finalization_verification_invalid")
        if self.terminal_attempt is None:
            if self.rounds_used != len(self.rounds) - 1:
                raise ValueError("crew_finalization_verification_invalid")
        elif (
            self.rounds_used != self.terminal_attempt.attempt_index
            or self.terminal_attempt.attempted_revision != len(self.rounds) + 1
        ):
            raise ValueError("crew_finalization_verification_invalid")
        if any(
            artifact.thread_id != self.thread_id
            for round_record in self.rounds
            for artifact in round_record.artifact_refs
        ):
            raise ValueError("crew_finalization_verification_invalid")
        if self.terminal_attempt is not None and any(
            artifact.thread_id != self.thread_id
            for artifact in self.terminal_attempt.artifact_refs
        ):
            raise ValueError("crew_finalization_verification_invalid")
        final_verdict = self.rounds[-1].verdict
        if self.status == "converged" and (
            final_verdict.status != "accepted"
            or self.terminal_attempt is not None
        ):
            raise ValueError("crew_finalization_verification_invalid")
        if self.status == "unverified" and (
            self.failure_code != "convergence_exhausted"
            or final_verdict.status != "refuted"
            or self.terminal_attempt is not None
        ):
            raise ValueError("crew_finalization_verification_invalid")
        if self.failure_code == "independent_verifier_unavailable" and (
            self.status != "blocked"
            or final_verdict.status != "unavailable"
            or self.terminal_attempt is not None
        ):
            raise ValueError("crew_finalization_verification_invalid")
        if self.failure_code == "verification_defect" and (
            self.status != "failed"
            or final_verdict.status not in {"malformed", "error"}
            or self.terminal_attempt is not None
        ):
            raise ValueError("crew_finalization_verification_invalid")
        if self.terminal_attempt is not None and (
            self.failure_code != self.terminal_attempt.failure_code
            or self.status not in {"blocked", "failed"}
            or final_verdict.status != "refuted"
            or (
                self.status == "blocked"
                and self.failure_code not in {
                    "correction_capability_denied",
                    "correction_budget_exhausted",
                }
            )
            or (
                self.status == "failed"
                and self.failure_code != "correction_execution_defect"
            )
        ):
            raise ValueError("crew_finalization_verification_invalid")
        compact = _compact_bytes(
            self.model_dump(mode="json"),
            maximum=_MAX_VERIFICATION_BYTES,
            error="crew_finalization_verification_too_large",
        )
        if not compact:
            raise ValueError("crew_finalization_verification_invalid")
        return self


@dataclass(frozen=True)
class CrewSessionFinalizationResult:
    parent_id: str
    claimed: bool
    state: str
    completed: bool
    final_output: str
    accepted_count: int
    total_count: int
    result_artifact_id: str | None
    provenance_ref: str | None
    reason: str


@dataclass(frozen=True)
class _ChildPublication:
    child: WorkItem
    outcome: SessionConvergenceOutcome
    verification: dict[str, Any]
    child_snapshot: dict[str, Any]


@dataclass(frozen=True)
class _InitialResultBinding:
    work_item_id: str
    spec_id: str
    agent_id: str
    output: str
    status: str
    tool_trace_ref: str | None
    started_at: float
    finished_at: float
    stopped_reason: str
    actual_tokens: int
    artifact_refs: tuple[dict[str, Any], ...]
    blocked_dependency_ids: tuple[str, ...]


@dataclass
class _ClaimAttempt:
    event: asyncio.Event
    disposition: Literal[
        "pending",
        "claimed",
        "cancelled_precommit",
        "cancelled_postcommit",
        "failed",
    ] = "pending"


class CrewSessionFinalizer:
    """Claim, converge, independently verify, and publish one durable session."""

    def __init__(
        self,
        *,
        work_item_store: WorkItemStore,
        crew_session_service: CrewSessionService,
        chat_thread_store: ChatThreadStore,
        artifact_store: ArtifactStore,
        attachment_store: AttachmentStore,
        agent_registry: AgentRegistry,
        verifier: SubtaskVerifier,
        synthesizer: CrewSynthesizer,
        trust_recorder: CrewSessionTrustRecorder | None = None,
        approval_threshold: float = 0.6,
        use_confidence_weights: bool = True,
    ) -> None:
        if (
            type(approval_threshold) not in (int, float)
            or not math.isfinite(float(approval_threshold))
            or not 0.0 <= float(approval_threshold) <= 1.0
            or type(use_confidence_weights) is not bool
        ):
            raise ValueError("crew_trust_policy_invalid")
        self._work_items = work_item_store
        self._sessions = crew_session_service
        self._threads = chat_thread_store
        self._artifacts = artifact_store
        self._attachments = attachment_store
        self._registry = agent_registry
        self._verifier = verifier
        self._synthesizer = synthesizer
        self._trust_recorder = trust_recorder
        self._approval_threshold = float(approval_threshold)
        self._use_confidence_weights = use_confidence_weights
        self._active_claims: dict[str, _ClaimAttempt] = {}

    async def drain_pending_trust(
        self,
        *,
        limit: int = MAX_CREW_TRUST_EFFECTS,
    ) -> int:
        """Run one bounded awaited CrewSession trust outbox pass."""
        if self._trust_recorder is None:
            return 0
        try:
            return await self._trust_recorder.drain_pending(limit=limit)
        except asyncio.CancelledError:
            raise
        except ValueError:
            raise
        except Exception:
            logger.warning(
                "Crew trust pending-outbox scan failed; terminal session state "
                "remains authoritative and the next startup or finalization "
                "will retry the bounded drain",
                exc_info=True,
            )
            return 0

    def _completed_trust_effects(
        self,
        *,
        session: CrewSessionContract,
        publications: list[_ChildPublication],
        final_verdict: SessionVerificationPass,
        final_evidence_sha256: str,
    ) -> tuple[CrewTrustEffect, ...]:
        if self._trust_recorder is None:
            return ()
        return derive_completed_crew_trust_effects(
            session_id=session.task_id,
            session_revision=session.revision + 1,
            child_verifications=tuple(
                item.verification
                for item in sorted(publications, key=lambda value: value.child.id)
            ),
            facilitator_id=session.facilitator_id,
            final_verifier_id=final_verdict.verifier_agent_id,
            final_confidence=final_verdict.confidence,
            final_evidence_sha256=final_evidence_sha256,
            approval_threshold=self._approval_threshold,
            use_confidence_weights=self._use_confidence_weights,
        )

    def _convergence_failure_trust_effects(
        self,
        *,
        session: CrewSessionContract,
        publications: list[_ChildPublication],
    ) -> tuple[CrewTrustEffect, ...]:
        if self._trust_recorder is None:
            return ()
        eligible = tuple(
            item.verification
            for item in sorted(publications, key=lambda value: value.child.id)
            if item.outcome.failure_code in {None, "convergence_exhausted"}
        )
        if not any(
            item.outcome.failure_code == "convergence_exhausted"
            for item in publications
        ):
            return ()
        return derive_convergence_exhausted_effects(
            session_id=session.task_id,
            session_revision=session.revision + 1,
            child_verifications=eligible,
        )

    def _final_refutation_trust_effects(
        self,
        *,
        session: CrewSessionContract,
        publications: list[_ChildPublication],
        final_verdict: SessionVerificationPass,
        final_evidence_sha256: str,
    ) -> tuple[CrewTrustEffect, ...]:
        if self._trust_recorder is None:
            return ()
        if final_verdict.status != "refuted" or final_verdict.accepted:
            raise ValueError("crew_trust_evidence_invalid")
        return derive_final_refutation_effects(
            session_id=session.task_id,
            session_revision=session.revision + 1,
            facilitator_id=session.facilitator_id,
            final_verifier_id=final_verdict.verifier_agent_id,
            final_evidence_sha256=final_evidence_sha256,
            child_verifications=tuple(
                item.verification
                for item in sorted(publications, key=lambda value: value.child.id)
            ),
        )

    @staticmethod
    def _effect_evidence_refs(
        effects: tuple[CrewTrustEffect, ...],
    ) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            effect.evidence_sha256
            for effect in effects
            if effect.role in {"facilitator", "final_verifier"}
        ))

    async def finalize(
        self,
        parent_id: str,
        results: list[SubtaskResult],
    ) -> CrewSessionFinalizationResult:
        """Finalize one executing CrewSession without background work or retries."""
        parent_key = _id(parent_id)
        current = await self._sessions.get_session(parent_key)
        if current is None:
            raise ValueError("crew_session_not_initialized")
        recovery_getter = getattr(self._sessions, "get_recovery", None)
        recovery = (
            await recovery_getter(parent_key)
            if callable(recovery_getter)
            else None
        )
        if recovery is not None:
            if current.state in {"executing", "verifying"}:
                await self._load_resume_children(
                    parent_key,
                    current,
                    results,
                )
            return await self.resume(parent_key)
        if current.state == "verifying":
            raise ValueError("crew_session_finalization_in_progress")
        if current.state != "executing":
            if current.state in {"done", "failed"}:
                await self.drain_pending_trust()
            return self._observation(current, reason="session_not_executing")
        existing_claim = self._active_claims.get(parent_key)
        if existing_claim is not None:
            await existing_claim.event.wait()
            authoritative = await self._sessions.get_session(parent_key)
            if authoritative is None:
                raise ValueError("crew_session_not_initialized")
            if (
                existing_claim.disposition == "cancelled_precommit"
                and authoritative.state == "executing"
            ):
                claimed = await self._sessions.transition_session(
                    parent_key,
                    "verifying",
                    expected_revision=authoritative.revision,
                )
                return await self._finalize_claimed(
                    parent_key,
                    claimed,
                    results,
                )
            if (
                existing_claim.disposition == "failed"
                and authoritative.state == "executing"
            ):
                return self._observation(
                    authoritative,
                    reason="claim_failed",
                )
            if authoritative.state in {"done", "failed"}:
                await self.drain_pending_trust()
            return self._observation(
                authoritative,
                reason="finalization_in_progress",
            )
        claim_attempt = _ClaimAttempt(event=asyncio.Event())
        self._active_claims[parent_key] = claim_attempt
        try:
            claimed = await self._sessions.transition_session(
                parent_key,
                "verifying",
                expected_revision=current.revision,
            )
        except asyncio.CancelledError:
            claim_attempt.disposition = "failed"
            try:
                authoritative = await asyncio.shield(
                    self._sessions.get_session(parent_key),
                )
            except BaseException:
                pass
            else:
                claim_attempt.disposition = (
                    "cancelled_precommit"
                    if authoritative is not None
                    and authoritative.state == "executing"
                    else "cancelled_postcommit"
                )
            raise
        except Exception as claim_error:
            claim_attempt.disposition = "failed"
            try:
                authoritative = await self._sessions.get_session(parent_key)
            except Exception:
                raise claim_error
            if authoritative is not None and authoritative.state != "executing":
                return self._observation(authoritative, reason="claim_lost")
            raise claim_error
        except BaseException:
            claim_attempt.disposition = "failed"
            raise
        else:
            claim_attempt.disposition = "claimed"
        finally:
            claim_attempt.event.set()
            if self._active_claims.get(parent_key) is claim_attempt:
                self._active_claims.pop(parent_key, None)
        return await self._finalize_claimed(parent_key, claimed, results)

    async def resume(self, parent_id: str) -> CrewSessionFinalizationResult:
        """Resume one durable CrewSession from its exact persisted checkpoint."""
        parent_key = _id(parent_id)
        session = await self._sessions.get_session(parent_key)
        if session is None:
            raise ValueError("crew_session_not_initialized")
        if session.state in {"done", "failed", "blocked_needs_captain"}:
            if session.state in {"done", "failed"}:
                await self.drain_pending_trust()
            return self._observation(session, reason="session_terminal")
        recovery = await self._sessions.get_recovery(parent_key)
        if recovery is None or recovery.plan is None:
            raise ValueError("crew_recovery_not_initialized")
        if session.state == "executing":
            results = await self._reconstruct_execution_results(
                parent_key,
                session.thread_id,
                recovery.plan.children,
            )
            recovery_values = recovery.model_dump(mode="json")
            recovery_values.update({
                "phase": "verifying_children",
                "retry_count": 0,
                "next_attempt_at": None,
                "last_error_code": None,
                "interrupted_child_ids": [],
            })
            next_recovery = type(recovery).model_validate(recovery_values)
            session = await self._sessions.transition_session(
                parent_key,
                "verifying",
                expected_revision=session.revision,
                expected_recovery=recovery,
                recovery=next_recovery,
            )
            recovery = next_recovery
        elif session.state == "verifying":
            results = await self._reconstruct_execution_results(
                parent_key,
                session.thread_id,
                recovery.plan.children,
            )
        else:
            return self._observation(session, reason="session_not_resumable")
        return await self._resume_checkpoints(
            session=session,
            recovery=recovery,
            results=results,
        )

    async def _resume_checkpoints(
        self,
        *,
        session: CrewSessionContract,
        recovery: Any,
        results: list[SubtaskResult],
    ) -> CrewSessionFinalizationResult:
        children, matched_results = await self._load_resume_children(
            session.task_id,
            session,
            results,
        )
        publications: list[_ChildPublication] = []
        convergence_refs: list[dict[str, str]] = []
        for child in children:
            publication, convergence_ref = await self._resume_child_convergence(
                session=session,
                child=child,
                result=matched_results[child.id],
            )
            publications.append(publication)
            convergence_refs.append({
                "work_item_id": child.id,
                "convergence_ref": convergence_ref,
            })
        convergence_refs.sort(key=lambda item: item["work_item_id"])
        if any(not item.outcome.accepted for item in publications):
            reason, blocked = self._outcome_failure(
                next(item.outcome for item in publications if not item.outcome.accepted),
            )
            effects = (
                self._convergence_failure_trust_effects(
                    session=session,
                    publications=publications,
                )
                if not blocked
                else ()
            )
            if effects:
                return await self._fail_verified(
                    session,
                    reason=reason,
                    accepted_count=self._accepted_count(publications),
                    total_count=len(publications),
                    effects=effects,
                    recovery=recovery,
                )
            return await self._fail_recovery(
                session,
                recovery,
                reason=reason,
                accepted_count=self._accepted_count(publications),
                total_count=len(publications),
                blocked=blocked,
            )
        if recovery.phase == "verifying_children":
            recovery = await self._advance_recovery(
                session,
                recovery,
                phase="children_verified",
            )

        draft, recovery = await self._resume_synthesis(
            session=session,
            recovery=recovery,
            publications=publications,
            convergence_refs=convergence_refs,
        )
        result_bytes = draft.final_text.encode("utf-8")
        if not result_bytes or len(result_bytes) > _MAX_FINAL_BYTES:
            raise ValueError("crew_finalization_result_invalid")
        result_hash = hashlib.sha256(result_bytes).hexdigest()
        candidate = {
            "thread_id": session.thread_id,
            "name": "crew-result.md",
            "mime": "text/markdown",
            "size_bytes": len(result_bytes),
            "content_hash": result_hash,
            "created_by": session.facilitator_id,
        }
        final_verdict, recovery = await self._resume_final_verdict(
            session=session,
            recovery=recovery,
            publications=publications,
            draft=draft,
            candidate=candidate,
            result_hash=result_hash,
        )
        if not final_verdict.accepted:
            if final_verdict.status == "unavailable":
                reason = "independent_verifier_unavailable"
                blocked = True
            elif final_verdict.status == "refuted":
                reason = "final_verification_refuted"
                blocked = False
            else:
                reason = "verification_defect"
                blocked = False
            if reason == "final_verification_refuted":
                if self._trust_recorder is None:
                    return await self._fail_recovery(
                        session,
                        recovery,
                        reason=reason,
                        accepted_count=self._accepted_count(publications),
                        total_count=len(publications),
                        blocked=False,
                    )
                verification_ref = recovery.final_verification_ref
                if verification_ref is None:
                    raise ValueError("crew_finalization_verdict_recovery_invalid")
                effects = self._final_refutation_trust_effects(
                    session=session,
                    publications=publications,
                    final_verdict=final_verdict,
                    final_evidence_sha256=verification_ref,
                )
                return await self._fail_verified(
                    session,
                    reason=reason,
                    accepted_count=self._accepted_count(publications),
                    total_count=len(publications),
                    effects=effects,
                    recovery=recovery,
                )
            return await self._fail_recovery(
                session,
                recovery,
                reason=reason,
                accepted_count=self._accepted_count(publications),
                total_count=len(publications),
                blocked=blocked,
            )
        artifact, recovery = await self._defer_checkpoint(self._resume_result_artifact(
            session=session,
            recovery=recovery,
            result_bytes=result_bytes,
            result_hash=result_hash,
        ))
        artifact_ref = self._validate_result_artifact(
            artifact,
            session=session,
            result_hash=result_hash,
            size_bytes=len(result_bytes),
        )
        provenance_ref, recovery = await self._defer_checkpoint(self._resume_provenance(
            session=session,
            recovery=recovery,
            publications=publications,
            draft=draft,
            final_verdict=final_verdict,
            artifact_ref=artifact_ref,
        ))
        synthesis = self._synthesis_metadata(
            publications=publications,
            draft=draft,
            final_verdict=final_verdict,
            artifact_ref=artifact_ref,
            result_hash=result_hash,
            provenance_ref=provenance_ref,
        )
        trust_effects = self._completed_trust_effects(
            session=session,
            publications=publications,
            final_verdict=final_verdict,
            final_evidence_sha256=provenance_ref,
        )
        trust_kwargs = (
            {"crew_trust_effects": trust_effects}
            if trust_effects
            else {}
        )
        completed = await self._sessions.publish_verified_result(
            session.task_id,
            expected_revision=session.revision,
            expected_recovery=recovery,
            expected_direct_children=tuple(
                item.child_snapshot
                for item in sorted(publications, key=lambda value: value.child.id)
            ),
            crew_synth=synthesis,
            last_result_summary=draft.final_text[:4_096],
            provenance_ref=provenance_ref,
            result_artifact_id=artifact.id,
            **trust_kwargs,
        )
        await self.drain_pending_trust()
        return CrewSessionFinalizationResult(
            parent_id=session.task_id,
            claimed=True,
            state=completed.state,
            completed=True,
            final_output=draft.final_text,
            accepted_count=self._accepted_count(publications),
            total_count=len(publications),
            result_artifact_id=artifact.id,
            provenance_ref=provenance_ref,
            reason="completed",
        )

    async def _load_resume_children(
        self,
        parent_id: str,
        session: CrewSessionContract,
        results: list[SubtaskResult],
    ) -> tuple[list[WorkItem], dict[str, SubtaskResult]]:
        children = await self._work_items.list_work_items(
            parent_id=parent_id,
            limit=_MAX_CHILDREN + 1,
        )
        if not 1 <= len(children) <= _MAX_CHILDREN:
            raise ValueError("child_result_invalid")
        children.sort(key=lambda child: child.id)
        matched = {result.work_item_id: result for result in results}
        if len(matched) != len(results) or set(matched) != {child.id for child in children}:
            raise ValueError("child_result_invalid")
        for child in children:
            self._validate_resume_execution_result(
                parent_id,
                session.thread_id,
                child,
                matched[child.id],
            )
        return children, matched

    def _validate_resume_execution_result(
        self,
        parent_id: str,
        thread_id: str,
        child: WorkItem,
        result: SubtaskResult,
    ) -> None:
        execution = (child.metadata or {}).get("crew_execution")
        output_ref = (child.metadata or {}).get("crew_execution_output")
        if (
            result.work_item_id != child.id
            or result.spec_id != (child.metadata or {}).get("spec_id")
            or result.agent_id != child.assigned_to
            or result.status != "done"
            or result.stopped_reason != "complete"
            or child.parent_id != parent_id
            or child.status != "done"
            or type(execution) is not dict
            or set(execution) != _EXECUTION_KEYS
            or execution["parent_id"] != parent_id
            or execution["work_item_id"] != child.id
            or execution["thread_id"] != thread_id
            or execution["assigned_to"] != child.assigned_to
            or execution["status"] != "done"
            or execution["stopped_reason"] != "complete"
            or execution["output_summary"] != _execution_summary(result.output)
            or execution["tool_trace_ref"] != result.tool_trace_ref
            or not _json_exactly_equal(execution["artifact_refs"], result.artifact_refs)
            or execution["tokens_used"] > child.actual_tokens
            or type(output_ref) is not dict
            or set(output_ref) != {"version", "content_hash", "mime", "size_bytes"}
            or output_ref["version"] != 1
            or output_ref["mime"] != "text/plain"
            or output_ref["size_bytes"] != len(result.output.encode("utf-8"))
            or hashlib.sha256(result.output.encode("utf-8")).hexdigest()
            != output_ref["content_hash"]
        ):
            raise ValueError("child_result_invalid")

    async def _reconstruct_execution_results(
        self,
        parent_id: str,
        thread_id: str,
        commitments: Any,
    ) -> list[SubtaskResult]:
        from probos.cognitive.crew_executor import SubtaskResult

        children = await self._work_items.list_work_items(
            parent_id=parent_id,
            limit=_MAX_CHILDREN + 1,
        )
        by_id = {child.id: child for child in children}
        if len(by_id) != len(children) or len(children) != len(commitments):
            raise ValueError("child_result_invalid")
        results: list[SubtaskResult] = []
        for commitment in commitments:
            child = by_id.get(commitment.child_id)
            if child is None:
                raise ValueError("child_result_invalid")
            execution = (child.metadata or {}).get("crew_execution")
            output_ref = (child.metadata or {}).get("crew_execution_output")
            if (
                child.status != "done"
                or type(execution) is not dict
                or set(execution) != _EXECUTION_KEYS
                or type(output_ref) is not dict
                or set(output_ref) != {"version", "content_hash", "mime", "size_bytes"}
                or output_ref["mime"] != "text/plain"
            ):
                raise ValueError("child_result_invalid")
            blob = await self._attachments.read(_sha(output_ref["content_hash"]))
            if (
                type(output_ref["size_bytes"]) is not int
                or len(blob) != output_ref["size_bytes"]
                or hashlib.sha256(blob).hexdigest() != output_ref["content_hash"]
            ):
                raise ValueError("child_result_invalid")
            output = blob.decode("utf-8", errors="strict")
            result = SubtaskResult(
                work_item_id=child.id,
                spec_id=str((child.metadata or {}).get("spec_id", "")),
                agent_id=child.assigned_to or "",
                output=output,
                status="done",
                tool_trace_ref=execution["tool_trace_ref"],
                started_at=execution["started_at"],
                finished_at=execution["finished_at"],
                stopped_reason="complete",
                actual_tokens=execution["tokens_used"],
                artifact_refs=[dict(ref) for ref in execution["artifact_refs"]],
                blocked_dependency_ids=[],
            )
            self._validate_resume_execution_result(
                parent_id,
                thread_id,
                child,
                result,
            )
            results.append(result)
        return results

    async def _resume_child_convergence(
        self,
        *,
        session: CrewSessionContract,
        child: WorkItem,
        result: SubtaskResult,
    ) -> tuple[_ChildPublication, str]:
        recovery_record = (child.metadata or {}).get("crew_verification_recovery")
        if child.verification:
            if (
                type(recovery_record) is not dict
                or set(recovery_record) != {"version", "convergence_ref"}
                or recovery_record["version"] != 1
            ):
                raise ValueError(
                    "crew_finalization_legacy_verification_nonreconstructable"
                )
            convergence_ref = _sha(recovery_record["convergence_ref"])
            document = await self._read_json_checkpoint(
                convergence_ref,
                maximum=1_048_576,
            )
            outcome = self._convergence_from_checkpoint(
                document,
                session=session,
                child=child,
                initial=result,
            )
            verification = self._verification_document(
                parent_id=session.task_id,
                thread_id=session.thread_id,
                producer_agent_id=result.agent_id,
                outcome=outcome,
            )
            if not _json_exactly_equal(verification, child.verification):
                raise ValueError("crew_finalization_recovery_invalid")
            return _ChildPublication(
                child=child,
                outcome=outcome,
                verification=_detached(child.verification),
                child_snapshot=self._publication_child_snapshot(child),
            ), convergence_ref

        producer = self._live_agent(result.agent_id)
        if producer is None:
            raise ValueError("child_producer_unavailable")
        instructions = _text(
            getattr(producer, "instructions", None),
            maximum_codepoints=32_768,
            maximum_bytes=_MAX_INSTRUCTIONS_BYTES,
        )
        task_text = _text(
            child.description or child.title,
            maximum_codepoints=32_768,
            maximum_bytes=_MAX_INSTRUCTIONS_BYTES,
        )
        snapshot = self._snapshot_child(child)
        initial_binding = self._initial_result_binding(
            result,
            thread_id=session.thread_id,
        )
        outcome = await self._verifier.converge_for_session(
            result,
            instructions=instructions,
            task_text=task_text,
            expected_output=self._expected_output(child),
            parent_id=session.task_id,
            thread_id=session.thread_id,
            department=str(getattr(producer, "department", "") or ""),
            rank=str(getattr(producer, "rank", "ensign") or "ensign"),
        )
        return await self._defer_checkpoint(self._checkpoint_child_convergence(
            session=session,
            child=child,
            result=result,
            snapshot=snapshot,
            initial_binding=initial_binding,
            outcome=outcome,
        ))

    async def _checkpoint_child_convergence(
        self,
        *,
        session: CrewSessionContract,
        child: WorkItem,
        result: SubtaskResult,
        snapshot: dict[str, Any],
        initial_binding: _InitialResultBinding,
        outcome: SessionConvergenceOutcome,
    ) -> tuple[_ChildPublication, str]:
        self._validate_convergence_binding(
            child=child,
            initial=initial_binding,
            outcome=outcome,
            thread_id=session.thread_id,
        )
        self._validate_outcome_verifiers(
            outcome,
            excluded_agent_ids=frozenset({result.agent_id}),
        )
        verification = self._verification_document(
            parent_id=session.task_id,
            thread_id=session.thread_id,
            producer_agent_id=result.agent_id,
            outcome=outcome,
        )
        convergence_document = self._convergence_checkpoint(
            session=session,
            child=child,
            outcome=outcome,
        )
        convergence_ref = await self._write_json_checkpoint(
            convergence_document,
            maximum=1_048_576,
        )
        correction_tokens = self._correction_tokens(outcome)
        persisted = await self._work_items.compare_and_set_work_item_verification(
            child.id,
            verification,
            expected_verification=snapshot["verification"],
            expected_work_type=snapshot["work_type"],
            expected_status=snapshot["status"],
            expected_assigned_to=snapshot["assigned_to"],
            expected_parent_id=snapshot["parent_id"],
            expected_title=snapshot["title"],
            expected_description=snapshot["description"],
            expected_depends_on=snapshot["depends_on"],
            expected_metadata=snapshot["metadata"],
            expected_actual_tokens=snapshot["actual_tokens"],
            metadata_patch={
                "crew_verification_recovery": {
                    "version": 1,
                    "convergence_ref": convergence_ref,
                }
            },
            actual_tokens_delta=correction_tokens,
        )
        if persisted is None:
            raise ValueError("work_item_verification_conflict")
        return _ChildPublication(
            child=persisted,
            outcome=outcome,
            verification=_detached(persisted.verification),
            child_snapshot=self._publication_child_snapshot(persisted),
        ), convergence_ref

    async def _resume_synthesis(
        self,
        *,
        session: CrewSessionContract,
        recovery: Any,
        publications: list[_ChildPublication],
        convergence_refs: list[dict[str, str]],
    ) -> tuple[SessionSynthesisDraft, Any]:
        from probos.cognitive.crew_synth import SessionSynthesisDraft

        if recovery.synthesis_ref is not None:
            document = await self._read_json_checkpoint(
                recovery.synthesis_ref,
                maximum=_MAX_FINAL_BYTES,
            )
            expected_keys = {
                "version", "parent_id", "thread_id", "producer_agent_id",
                "final_text", "tokens_used", "child_convergence_refs",
            }
            if (
                type(document) is not dict
                or set(document) != expected_keys
                or document["version"] != 1
                or document["parent_id"] != session.task_id
                or document["thread_id"] != session.thread_id
                or document["producer_agent_id"] != session.facilitator_id
                or not _json_exactly_equal(
                    document["child_convergence_refs"],
                    convergence_refs,
                )
                or type(document["tokens_used"]) is not int
                or not 0 <= document["tokens_used"] <= _MAX_TOKEN_TOTAL
            ):
                raise ValueError("crew_finalization_synthesis_recovery_invalid")
            final_text = _text(
                document["final_text"],
                maximum_codepoints=_MAX_FINAL_BYTES,
                maximum_bytes=_MAX_FINAL_BYTES,
            )
            return SessionSynthesisDraft(
                producer_agent_id=session.facilitator_id,
                final_text=final_text,
                tokens_used=document["tokens_used"],
            ), recovery
        facilitator = self._live_agent(session.facilitator_id)
        if facilitator is None:
            raise ValueError("synthesis_producer_unavailable")
        instructions = _text(
            getattr(facilitator, "instructions", None),
            maximum_codepoints=32_768,
            maximum_bytes=_MAX_INSTRUCTIONS_BYTES,
        )
        draft = await self._synthesizer.synthesize_for_session(
            parent_id=session.task_id,
            producer_agent_id=session.facilitator_id,
            producer_instructions=instructions,
            goal=session.goal,
            success_criteria=session.success_criteria,
            expected_deliverable=session.expected_deliverable,
            outcomes=tuple(item.outcome for item in publications),
        )
        recovery = await self._defer_checkpoint(self._checkpoint_synthesis(
            session=session,
            recovery=recovery,
            draft=draft,
            convergence_refs=convergence_refs,
        ))
        return draft, recovery

    async def _checkpoint_synthesis(
        self,
        *,
        session: CrewSessionContract,
        recovery: Any,
        draft: SessionSynthesisDraft,
        convergence_refs: list[dict[str, str]],
    ) -> Any:
        document = {
            "version": 1,
            "parent_id": session.task_id,
            "thread_id": session.thread_id,
            "producer_agent_id": session.facilitator_id,
            "final_text": draft.final_text,
            "tokens_used": draft.tokens_used,
            "child_convergence_refs": convergence_refs,
        }
        synthesis_ref = await self._write_json_checkpoint(
            document,
            maximum=_MAX_FINAL_BYTES,
        )
        recovery = await self._advance_recovery(
            session,
            recovery,
            phase="synthesized",
            synthesis_ref=synthesis_ref,
        )
        return recovery

    async def _resume_final_verdict(
        self,
        *,
        session: CrewSessionContract,
        recovery: Any,
        publications: list[_ChildPublication],
        draft: SessionSynthesisDraft,
        candidate: dict[str, Any],
        result_hash: str,
    ) -> tuple[SessionVerificationPass, Any]:
        if recovery.final_verification_ref is not None:
            document = await self._read_json_checkpoint(
                recovery.final_verification_ref,
                maximum=_MAX_VERIFICATION_BYTES,
            )
            expected_keys = {
                "version", "parent_id", "thread_id", "synthesis_ref",
                "result_content_hash", "candidate", "verdict",
            }
            if (
                type(document) is not dict
                or set(document) != expected_keys
                or document["version"] != 1
                or document["parent_id"] != session.task_id
                or document["thread_id"] != session.thread_id
                or document["synthesis_ref"] != recovery.synthesis_ref
                or document["result_content_hash"] != result_hash
                or not _json_exactly_equal(document["candidate"], candidate)
            ):
                raise ValueError("crew_finalization_verdict_recovery_invalid")
            verdict_record = _VerdictRecord.model_validate(document["verdict"])
            verdict = SessionVerificationPass(**verdict_record.model_dump(mode="json"))
            self._validate_verifier_identity(
                verdict,
                excluded_agent_ids=frozenset({
                    session.facilitator_id,
                    *(item.outcome.result.agent_id for item in publications),
                }),
            )
            return verdict, recovery
        expected_output = await self._final_expected_output(
            session=session,
            publications=publications,
            candidate=candidate,
        )
        producer_ids = {item.outcome.result.agent_id for item in publications}
        verdict = await self._verifier.verify_for_session(
            self._final_result(session.task_id, session.facilitator_id, draft.final_text),
            expected_output=expected_output,
            excluded_agent_ids=frozenset({session.facilitator_id, *producer_ids}),
        )
        recovery = await self._defer_checkpoint(self._checkpoint_final_verdict(
            session=session,
            recovery=recovery,
            publications=publications,
            verdict=verdict,
            candidate=candidate,
            result_hash=result_hash,
        ))
        return verdict, recovery

    async def _checkpoint_final_verdict(
        self,
        *,
        session: CrewSessionContract,
        recovery: Any,
        publications: list[_ChildPublication],
        verdict: SessionVerificationPass,
        candidate: dict[str, Any],
        result_hash: str,
    ) -> Any:
        producer_ids = {item.outcome.result.agent_id for item in publications}
        self._validate_verifier_identity(
            verdict,
            excluded_agent_ids=frozenset({session.facilitator_id, *producer_ids}),
        )
        verdict_document = self._verdict_document(verdict)
        document = {
            "version": 1,
            "parent_id": session.task_id,
            "thread_id": session.thread_id,
            "synthesis_ref": recovery.synthesis_ref,
            "result_content_hash": result_hash,
            "candidate": _detached(candidate),
            "verdict": verdict_document,
        }
        verification_ref = await self._write_json_checkpoint(
            document,
            maximum=_MAX_VERIFICATION_BYTES,
        )
        recovery = await self._advance_recovery(
            session,
            recovery,
            phase="final_verified",
            final_verification_ref=verification_ref,
        )
        return recovery

    async def _resume_result_artifact(
        self,
        *,
        session: CrewSessionContract,
        recovery: Any,
        result_bytes: bytes,
        result_hash: str,
    ) -> tuple[Artifact, Any]:
        if recovery.result_artifact_id is not None:
            readback = await self._attachments.read(result_hash)
            if (
                readback != result_bytes
                or hashlib.sha256(readback).hexdigest() != result_hash
            ):
                raise ValueError("crew_finalization_artifact_recovery_invalid")
            versions = await asyncio.to_thread(
                self._artifacts.list_versions,
                thread_id=session.thread_id,
                name="crew-result.md",
            )
            if (
                len(versions) != 1
                or versions[0].id != recovery.result_artifact_id
            ):
                raise ValueError("crew_finalization_artifact_recovery_invalid")
            artifact = versions[0]
            self._validate_result_artifact(
                artifact,
                session=session,
                result_hash=result_hash,
                size_bytes=len(result_bytes),
            )
            return artifact, recovery

        await self._attachments.write(
            result_hash,
            result_bytes,
            "text/markdown",
            origin="agent_artifact",
        )
        readback = await self._attachments.read(result_hash)
        if readback != result_bytes or hashlib.sha256(readback).hexdigest() != result_hash:
            raise ValueError("crew_finalization_result_readback_failed")
        artifact = await asyncio.to_thread(
            self._artifacts.reconcile_exact_version,
            thread_id=session.thread_id,
            name="crew-result.md",
            content_hash=result_hash,
            mime="text/markdown",
            size_bytes=len(result_bytes),
            created_by=session.facilitator_id,
        )
        self._validate_result_artifact(
            artifact,
            session=session,
            result_hash=result_hash,
            size_bytes=len(result_bytes),
        )
        recovery = await self._advance_recovery(
            session,
            recovery,
            phase="artifact_bound",
            result_artifact_id=artifact.id,
        )
        return artifact, recovery

    async def _resume_provenance(
        self,
        *,
        session: CrewSessionContract,
        recovery: Any,
        publications: list[_ChildPublication],
        draft: SessionSynthesisDraft,
        final_verdict: SessionVerificationPass,
        artifact_ref: dict[str, Any],
    ) -> tuple[str, Any]:
        provenance = self._provenance_document(
            session=session,
            publications=publications,
            draft=draft,
            final_verdict=final_verdict,
            artifact_ref=artifact_ref,
        )
        provenance_bytes = _compact_bytes(
            provenance,
            maximum=_MAX_PROVENANCE_BYTES,
            error="crew_finalization_provenance_too_large",
        )
        provenance_ref = hashlib.sha256(provenance_bytes).hexdigest()
        if recovery.provenance_ref is not None:
            if recovery.provenance_ref != provenance_ref:
                raise ValueError("crew_finalization_provenance_recovery_invalid")
            readback = await self._attachments.read(provenance_ref)
            if (
                readback != provenance_bytes
                or hashlib.sha256(readback).hexdigest() != provenance_ref
            ):
                raise ValueError("crew_finalization_provenance_recovery_invalid")
            return provenance_ref, recovery

        await self._attachments.write(
            provenance_ref,
            provenance_bytes,
            "application/json",
            origin="chat_attachment",
        )
        readback = await self._attachments.read(provenance_ref)
        if (
            readback != provenance_bytes
            or hashlib.sha256(readback).hexdigest() != provenance_ref
        ):
            raise ValueError("crew_finalization_provenance_readback_failed")
        recovery = await self._advance_recovery(
            session,
            recovery,
            phase="provenance_bound",
            provenance_ref=provenance_ref,
        )
        return provenance_ref, recovery

    async def _advance_recovery(
        self,
        session: CrewSessionContract,
        recovery: Any,
        *,
        phase: str,
        **updates: Any,
    ) -> Any:
        values = recovery.model_dump(mode="json")
        values.update(updates)
        values.update({
            "phase": phase,
            "retry_count": 0,
            "next_attempt_at": None,
            "last_error_code": None,
            "interrupted_child_ids": [],
        })
        candidate = type(recovery).model_validate(values)
        return await self._sessions.compare_and_set_recovery(
            session.task_id,
            candidate,
            expected_session=session,
            expected_recovery=recovery,
        )

    @staticmethod
    async def _defer_checkpoint(
        operation: Awaitable[_CheckpointValue],
    ) -> _CheckpointValue:
        task = asyncio.create_task(operation)
        cancellation: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                if cancellation is None:
                    cancellation = exc
                current = asyncio.current_task()
                if current is not None:
                    current.uncancel()
                continue
        result = task.result()
        if cancellation is not None:
            raise cancellation
        return result

    async def _write_json_checkpoint(
        self,
        document: dict[str, Any],
        *,
        maximum: int,
    ) -> str:
        payload = _compact_bytes(
            document,
            maximum=maximum,
            error="crew_finalization_checkpoint_too_large",
        )
        content_hash = hashlib.sha256(payload).hexdigest()
        await self._attachments.write(
            content_hash,
            payload,
            "application/json",
            origin="chat_attachment",
        )
        readback = await self._attachments.read(content_hash)
        if readback != payload or hashlib.sha256(readback).hexdigest() != content_hash:
            raise ValueError("crew_finalization_checkpoint_readback_failed")
        return content_hash

    async def _read_json_checkpoint(
        self,
        content_hash: str,
        *,
        maximum: int,
    ) -> dict[str, Any]:
        ref = _sha(content_hash)
        payload = await self._attachments.read(ref)
        if len(payload) > maximum or hashlib.sha256(payload).hexdigest() != ref:
            raise ValueError("crew_finalization_checkpoint_invalid")
        try:
            document = json.loads(payload.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("crew_finalization_checkpoint_invalid") from exc
        if type(document) is not dict or _compact_bytes(
            document,
            maximum=maximum,
            error="crew_finalization_checkpoint_invalid",
        ) != payload:
            raise ValueError("crew_finalization_checkpoint_invalid")
        return document

    def _convergence_checkpoint(
        self,
        *,
        session: CrewSessionContract,
        child: WorkItem,
        outcome: SessionConvergenceOutcome,
    ) -> dict[str, Any]:
        output_ref = (child.metadata or {}).get("crew_execution_output")
        if type(output_ref) is not dict:
            raise ValueError("crew_finalization_recovery_invalid")
        return {
            "version": 1,
            "parent_id": session.task_id,
            "work_item_id": child.id,
            "thread_id": session.thread_id,
            "producer_agent_id": outcome.result.agent_id,
            "execution_output_ref": _sha(output_ref.get("content_hash")),
            "outcome": {
                "result": {
                    "work_item_id": outcome.result.work_item_id,
                    "spec_id": outcome.result.spec_id,
                    "agent_id": outcome.result.agent_id,
                    "output": outcome.result.output,
                    "status": outcome.result.status,
                    "tool_trace_ref": outcome.result.tool_trace_ref,
                    "started_at": outcome.result.started_at,
                    "finished_at": outcome.result.finished_at,
                    "stopped_reason": outcome.result.stopped_reason,
                    "actual_tokens": outcome.result.actual_tokens,
                    "artifact_refs": [dict(ref) for ref in outcome.result.artifact_refs],
                    "blocked_dependency_ids": list(outcome.result.blocked_dependency_ids),
                },
                "accepted": outcome.accepted,
                "status": outcome.status,
                "rounds_used": outcome.rounds_used,
                "failure_code": outcome.failure_code,
                "history": [
                    {
                        **self._round_document(item),
                        "result_text": item.result_text,
                    }
                    for item in outcome.history
                ],
                "terminal_attempt": (
                    {
                        **self._terminal_document(outcome.terminal_attempt),
                        "result_text": outcome.terminal_attempt.result_text,
                    }
                    if outcome.terminal_attempt is not None
                    else None
                ),
            },
        }

    def _convergence_from_checkpoint(
        self,
        document: dict[str, Any],
        *,
        session: CrewSessionContract,
        child: WorkItem,
        initial: SubtaskResult,
    ) -> SessionConvergenceOutcome:
        expected_keys = {
            "version", "parent_id", "work_item_id", "thread_id",
            "producer_agent_id", "execution_output_ref", "outcome",
        }
        output_ref = (child.metadata or {}).get("crew_execution_output")
        if (
            set(document) != expected_keys
            or document["version"] != 1
            or document["parent_id"] != session.task_id
            or document["work_item_id"] != child.id
            or document["thread_id"] != session.thread_id
            or document["producer_agent_id"] != initial.agent_id
            or type(output_ref) is not dict
            or document["execution_output_ref"] != output_ref.get("content_hash")
            or type(document["outcome"]) is not dict
        ):
            raise ValueError("crew_finalization_recovery_invalid")
        raw = document["outcome"]
        if set(raw) != {
            "result", "accepted", "status", "rounds_used", "failure_code",
            "history", "terminal_attempt",
        } or type(raw["result"]) is not dict or type(raw["history"]) is not list:
            raise ValueError("crew_finalization_recovery_invalid")
        from probos.cognitive.crew_executor import SubtaskResult

        result_values = raw["result"]
        if set(result_values) != {
            "work_item_id", "spec_id", "agent_id", "output", "status",
            "tool_trace_ref", "started_at", "finished_at", "stopped_reason",
            "actual_tokens", "artifact_refs", "blocked_dependency_ids",
        }:
            raise ValueError("crew_finalization_recovery_invalid")
        result = SubtaskResult(**result_values)
        history: list[SessionVerificationRound] = []
        for item in raw["history"]:
            if type(item) is not dict or "result_text" not in item:
                raise ValueError("crew_finalization_recovery_invalid")
            values = dict(item)
            result_text = values.pop("result_text")
            verdict = _VerdictRecord.model_validate(values.pop("verdict"))
            round_record = _RoundRecord.model_validate({
                **values,
                "verdict": verdict.model_dump(mode="json"),
            })
            history.append(SessionVerificationRound(
                round_index=round_record.round_index,
                result_revision=round_record.result_revision,
                result_text=_text(
                    result_text,
                    maximum_codepoints=_MAX_RESULT_BYTES,
                    maximum_bytes=_MAX_RESULT_BYTES,
                ),
                result_sha256=round_record.result_sha256,
                result_summary=round_record.result_summary,
                stopped_reason=round_record.stopped_reason,
                correction_tokens=round_record.correction_tokens,
                verifier_tokens=round_record.verifier_tokens,
                tool_trace_ref=round_record.tool_trace_ref,
                artifact_refs=tuple(
                    value.model_dump(mode="json")
                    for value in round_record.artifact_refs
                ),
                verdict=SessionVerificationPass(**verdict.model_dump(mode="json")),
            ))
        terminal = None
        if raw["terminal_attempt"] is not None:
            values = dict(raw["terminal_attempt"])
            result_text = values.pop("result_text")
            terminal_record = _TerminalAttemptRecord.model_validate(values)
            terminal = SessionCorrectionTerminalAttempt(
                attempt_index=terminal_record.attempt_index,
                attempted_revision=terminal_record.attempted_revision,
                stopped_reason=terminal_record.stopped_reason,
                result_text=result_text,
                result_sha256=terminal_record.result_sha256,
                result_summary=terminal_record.result_summary,
                correction_tokens=terminal_record.correction_tokens,
                tool_trace_ref=terminal_record.tool_trace_ref,
                artifact_refs=tuple(
                    value.model_dump(mode="json")
                    for value in terminal_record.artifact_refs
                ),
                denied_tools=terminal_record.denied_tools,
                failure_code=terminal_record.failure_code,
            )
        if type(raw["accepted"]) is not bool or type(raw["rounds_used"]) is not int:
            raise ValueError("crew_finalization_recovery_invalid")
        outcome = SessionConvergenceOutcome(
            result=result,
            accepted=raw["accepted"],
            status=raw["status"],
            rounds_used=raw["rounds_used"],
            failure_code=raw["failure_code"],
            history=tuple(history),
            terminal_attempt=terminal,
        )
        self._validate_convergence_binding(
            child=child,
            initial=self._initial_result_binding(
                initial,
                thread_id=session.thread_id,
            ),
            outcome=outcome,
            thread_id=session.thread_id,
        )
        self._validate_outcome_verifiers(
            outcome,
            excluded_agent_ids=frozenset({initial.agent_id}),
        )
        return outcome

    async def _fail_recovery(
        self,
        session: CrewSessionContract,
        recovery: Any,
        *,
        reason: str,
        accepted_count: int,
        total_count: int,
        blocked: bool,
    ) -> CrewSessionFinalizationResult:
        target = "blocked_needs_captain" if blocked else "failed"
        transitioned = await self._sessions.transition_session(
            session.task_id,
            target,
            expected_revision=session.revision,
            blocked_reason=reason if blocked else None,
            last_result_summary=reason,
            expected_recovery=recovery,
            recovery=recovery,
        )
        return CrewSessionFinalizationResult(
            parent_id=session.task_id,
            claimed=True,
            state=transitioned.state,
            completed=False,
            final_output="",
            accepted_count=accepted_count,
            total_count=total_count,
            result_artifact_id=None,
            provenance_ref=None,
            reason=reason,
        )

    async def _finalize_claimed(
        self,
        parent_id: str,
        session: CrewSessionContract,
        results: list[SubtaskResult],
    ) -> CrewSessionFinalizationResult:
        try:
            children, matched_results = await self._load_and_validate_children(
                parent_id,
                session,
                results,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return await self._fail(
                session,
                reason="child_result_invalid",
                accepted_count=0,
                total_count=0,
            )

        publications: list[_ChildPublication] = []
        first_failure: tuple[str, bool] | None = None
        for child in children:
            result = matched_results[child.id]
            producer = self._live_agent(result.agent_id)
            if producer is None:
                return await self._fail(
                    session,
                    reason="child_producer_unavailable",
                    accepted_count=self._accepted_count(publications),
                    total_count=len(children),
                    blocked=True,
                )
            try:
                instructions = _text(
                    getattr(producer, "instructions", None),
                    maximum_codepoints=32_768,
                    maximum_bytes=_MAX_INSTRUCTIONS_BYTES,
                )
                task_text = _text(
                    child.description or child.title,
                    maximum_codepoints=32_768,
                    maximum_bytes=_MAX_INSTRUCTIONS_BYTES,
                )
            except ValueError:
                return await self._fail(
                    session,
                    reason="child_producer_unavailable",
                    accepted_count=self._accepted_count(publications),
                    total_count=len(children),
                    blocked=True,
                )

            try:
                snapshot = self._snapshot_child(child)
                initial_binding = self._initial_result_binding(
                    result,
                    thread_id=session.thread_id,
                )
                convergence_input = replace(
                    result,
                    output=initial_binding.output,
                    artifact_refs=[
                        dict(ref) for ref in initial_binding.artifact_refs
                    ],
                    blocked_dependency_ids=list(
                        initial_binding.blocked_dependency_ids,
                    ),
                )
            except Exception:
                return await self._fail(
                    session,
                    reason="child_result_invalid",
                    accepted_count=self._accepted_count(publications),
                    total_count=len(children),
                )
            try:
                outcome = await self._verifier.converge_for_session(
                    convergence_input,
                    instructions=instructions,
                    task_text=task_text,
                    expected_output=self._expected_output(child),
                    parent_id=parent_id,
                    thread_id=session.thread_id,
                    department=str(getattr(producer, "department", "") or ""),
                    rank=str(getattr(producer, "rank", "ensign") or "ensign"),
                )
                self._validate_convergence_binding(
                    child=child,
                    initial=initial_binding,
                    outcome=outcome,
                    thread_id=session.thread_id,
                )
                self._validate_outcome_verifiers(
                    outcome,
                    excluded_agent_ids=frozenset({result.agent_id}),
                )
                verification = self._verification_document(
                    parent_id=parent_id,
                    thread_id=session.thread_id,
                    producer_agent_id=result.agent_id,
                    outcome=outcome,
                )
                correction_tokens = self._correction_tokens(outcome)
            except asyncio.CancelledError:
                raise
            except Exception:
                return await self._fail(
                    session,
                    reason="verification_defect",
                    accepted_count=self._accepted_count(publications),
                    total_count=len(children),
                )
            try:
                persisted = await self._work_items.compare_and_set_work_item_verification(
                    child.id,
                    verification,
                    expected_verification=snapshot["verification"],
                    expected_work_type=snapshot["work_type"],
                    expected_status=snapshot["status"],
                    expected_assigned_to=snapshot["assigned_to"],
                    expected_parent_id=snapshot["parent_id"],
                    expected_title=snapshot["title"],
                    expected_description=snapshot["description"],
                    expected_depends_on=snapshot["depends_on"],
                    expected_metadata=snapshot["metadata"],
                    expected_actual_tokens=snapshot["actual_tokens"],
                    actual_tokens_delta=correction_tokens,
                )
                if persisted is None:
                    raise ValueError("work_item_verification_conflict")
                child_snapshot = self._publication_child_snapshot(persisted)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Crew child verification persistence failed parent=%s "
                    "child=%s; the session will transition to failed and no "
                    "replacement verification record will be invented",
                    session.task_id,
                    child.id,
                    exc_info=True,
                )
                return await self._fail(
                    session,
                    reason="verification_persistence_failed",
                    accepted_count=self._accepted_count(publications),
                    total_count=len(children),
                )
            publications.append(_ChildPublication(
                child=persisted,
                outcome=outcome,
                verification=_detached(persisted.verification),
                child_snapshot=child_snapshot,
            ))
            if not outcome.accepted and first_failure is None:
                first_failure = self._outcome_failure(outcome)

        if first_failure is not None:
            reason, blocked = first_failure
            effects = (
                self._convergence_failure_trust_effects(
                    session=session,
                    publications=publications,
                )
                if not blocked
                else ()
            )
            if effects:
                return await self._fail_verified(
                    session,
                    reason=reason,
                    accepted_count=self._accepted_count(publications),
                    total_count=len(children),
                    effects=effects,
                    recovery=None,
                )
            return await self._fail(
                session,
                reason=reason,
                accepted_count=self._accepted_count(publications),
                total_count=len(children),
                blocked=blocked,
            )

        facilitator = self._live_agent(session.facilitator_id)
        if facilitator is None:
            return await self._fail(
                session,
                reason="synthesis_producer_unavailable",
                accepted_count=self._accepted_count(publications),
                total_count=len(children),
                blocked=True,
            )
        try:
            facilitator_instructions = _text(
                getattr(facilitator, "instructions", None),
                maximum_codepoints=32_768,
                maximum_bytes=_MAX_INSTRUCTIONS_BYTES,
            )
        except ValueError:
            return await self._fail(
                session,
                reason="synthesis_producer_unavailable",
                accepted_count=self._accepted_count(publications),
                total_count=len(children),
                blocked=True,
            )
        try:
            draft = await self._synthesizer.synthesize_for_session(
                parent_id=parent_id,
                producer_agent_id=session.facilitator_id,
                producer_instructions=facilitator_instructions,
                goal=session.goal,
                success_criteria=session.success_criteria,
                expected_deliverable=session.expected_deliverable,
                outcomes=tuple(item.outcome for item in publications),
            )
            if (
                getattr(draft, "producer_agent_id", None) != session.facilitator_id
                or type(getattr(draft, "tokens_used", None)) is not int
                or not 0 <= draft.tokens_used <= _MAX_TOKEN_TOTAL
            ):
                raise ValueError("crew_finalization_synthesis_invalid")
            validated_final_text = _text(
                getattr(draft, "final_text", None),
                maximum_codepoints=_MAX_FINAL_BYTES,
                maximum_bytes=_MAX_FINAL_BYTES,
            )
            if validated_final_text != draft.final_text:
                raise ValueError("crew_finalization_synthesis_invalid")
        except asyncio.CancelledError:
            raise
        except Exception:
            return await self._fail(
                session,
                reason="synthesis_defect",
                accepted_count=self._accepted_count(publications),
                total_count=len(children),
            )

        try:
            result_bytes = validated_final_text.encode("utf-8")
            if (
                not draft.final_text.strip()
                or len(result_bytes) > _MAX_FINAL_BYTES
            ):
                raise ValueError("crew_finalization_result_invalid")
            result_hash = hashlib.sha256(result_bytes).hexdigest()
            candidate = {
                "thread_id": session.thread_id,
                "name": "crew-result.md",
                "mime": "text/markdown",
                "size_bytes": len(result_bytes),
                "content_hash": result_hash,
                "created_by": session.facilitator_id,
            }
            expected_output = await self._final_expected_output(
                session=session,
                publications=publications,
                candidate=candidate,
            )
            producer_ids = {item.outcome.result.agent_id for item in publications}
            final_verdict = await self._verifier.verify_for_session(
                self._final_result(parent_id, session.facilitator_id, validated_final_text),
                expected_output=expected_output,
                excluded_agent_ids=frozenset({session.facilitator_id, *producer_ids}),
            )
            self._validate_verifier_identity(
                final_verdict,
                excluded_agent_ids=frozenset({session.facilitator_id, *producer_ids}),
            )
            self._verdict_document(final_verdict)
        except asyncio.CancelledError:
            raise
        except Exception:
            return await self._fail(
                session,
                reason="verification_defect",
                accepted_count=self._accepted_count(publications),
                total_count=len(children),
            )
        if final_verdict.status == "unavailable":
            return await self._fail(
                session,
                reason="independent_verifier_unavailable",
                accepted_count=self._accepted_count(publications),
                total_count=len(children),
                blocked=True,
            )
        if final_verdict.status in {"malformed", "error"}:
            return await self._fail(
                session,
                reason="verification_defect",
                accepted_count=self._accepted_count(publications),
                total_count=len(children),
            )
        if not final_verdict.accepted:
            if self._trust_recorder is None:
                return await self._fail(
                    session,
                    reason="final_verification_refuted",
                    accepted_count=self._accepted_count(publications),
                    total_count=len(children),
                )
            try:
                verdict_ref = await self._write_json_checkpoint(
                    {
                        "version": 1,
                        "parent_id": session.task_id,
                        "thread_id": session.thread_id,
                        "verdict": self._verdict_document(final_verdict),
                    },
                    maximum=_MAX_VERIFICATION_BYTES,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                return await self._fail(
                    session,
                    reason="verification_defect",
                    accepted_count=self._accepted_count(publications),
                    total_count=len(children),
                )
            effects = self._final_refutation_trust_effects(
                session=session,
                publications=publications,
                final_verdict=final_verdict,
                final_evidence_sha256=verdict_ref,
            )
            return await self._fail_verified(
                session,
                reason="final_verification_refuted",
                accepted_count=self._accepted_count(publications),
                total_count=len(children),
                effects=effects,
                recovery=None,
            )
        return await self._publish(
            session=session,
            publications=publications,
            draft=draft,
            final_verdict=final_verdict,
            result_bytes=result_bytes,
            result_hash=result_hash,
        )

    async def _load_and_validate_children(
        self,
        parent_id: str,
        session: CrewSessionContract,
        results: list[SubtaskResult],
    ) -> tuple[list[WorkItem], dict[str, SubtaskResult]]:
        if type(results) is not list or len(results) > _MAX_CHILDREN:
            raise ValueError("child_result_invalid")
        children = await self._work_items.list_work_items(
            parent_id=parent_id,
            limit=_MAX_CHILDREN + 1,
        )
        if not 1 <= len(children) <= _MAX_CHILDREN:
            raise ValueError("child_result_invalid")
        children.sort(key=lambda child: child.id)
        child_ids = [_id(child.id) for child in children]
        if len(set(child_ids)) != len(child_ids):
            raise ValueError("child_result_invalid")
        matched: dict[str, SubtaskResult] = {}
        for result in results:
            child_id = _id(getattr(result, "work_item_id", None))
            if child_id in matched:
                raise ValueError("child_result_invalid")
            matched[child_id] = result
        if set(matched) != set(child_ids):
            raise ValueError("child_result_invalid")
        for child in children:
            result = matched[child.id]
            self._validate_child_result(parent_id, session.thread_id, child, result)
        return children, matched

    def _validate_child_result(
        self,
        parent_id: str,
        thread_id: str,
        child: WorkItem,
        result: SubtaskResult,
    ) -> None:
        producer_id = _id(getattr(result, "agent_id", None))
        if getattr(result, "work_item_id", None) != child.id:
            raise ValueError("child_result_invalid")
        output = _text(
            getattr(result, "output", None),
            maximum_codepoints=_MAX_RESULT_BYTES,
            maximum_bytes=_MAX_RESULT_BYTES,
        )
        if (
            getattr(result, "status", None) != "done"
            or getattr(result, "stopped_reason", None) != "complete"
            or child.parent_id != parent_id
            or child.status != "done"
            or child.assigned_to != producer_id
            or child.verification != {}
        ):
            raise ValueError("child_result_invalid")
        execution = (child.metadata or {}).get("crew_execution")
        if type(execution) is not dict or set(execution) != _EXECUTION_KEYS:
            raise ValueError("child_result_invalid")
        result_tokens = getattr(result, "actual_tokens", None)
        result_started = getattr(result, "started_at", None)
        result_finished = getattr(result, "finished_at", None)
        result_trace = getattr(result, "tool_trace_ref", None)
        result_artifacts = getattr(result, "artifact_refs", None)
        result_dependencies = getattr(result, "blocked_dependency_ids", None)
        result_spec = getattr(result, "spec_id", None)
        if (
            type(result_tokens) is not int
            or not 0 <= result_tokens <= _MAX_TOKEN_TOTAL
            or type(result_started) is not float
            or type(result_finished) is not float
            or not math.isfinite(float(result_started))
            or not math.isfinite(float(result_finished))
            or not 0.0 <= float(result_started) <= float(result_finished)
            or type(result_spec) is not str
            or not result_spec
            or (child.metadata or {}).get("spec_id") != result_spec
            or (
                result_trace is not None
                and (type(result_trace) is not str or _SHA_RE.fullmatch(result_trace) is None)
            )
            or not _json_exactly_equal(result_dependencies, [])
        ):
            raise ValueError("child_result_invalid")
        try:
            normalized_artifacts = self._artifact_refs(
                result_artifacts,
                thread_id=thread_id,
            )
        except (ValidationError, ValueError) as exc:
            raise ValueError("child_result_invalid") from exc
        if (
            type(execution["version"]) is not int
            or execution["version"] != 1
            or execution["parent_id"] != parent_id
            or execution["work_item_id"] != child.id
            or execution["thread_id"] != thread_id
            or execution["assigned_to"] != producer_id
            or execution["status"] != "done"
            or execution["stopped_reason"] != "complete"
            or execution["output_summary"] != _execution_summary(output)
            or execution["tool_trace_ref"] != result_trace
            or type(execution["tokens_used"]) is not int
            or execution["tokens_used"] != result_tokens
            or type(child.actual_tokens) is not int
            or child.actual_tokens != result_tokens
            or type(execution["started_at"]) is not float
            or type(execution["finished_at"]) is not float
            or execution["started_at"] != result_started
            or execution["finished_at"] != result_finished
            or not _json_exactly_equal(execution["blocked_dependency_ids"], [])
            or not _json_exactly_equal(
                execution["artifact_refs"],
                normalized_artifacts,
            )
        ):
            raise ValueError("child_result_invalid")
        if not output:
            raise ValueError("child_result_invalid")

    def _live_agent(self, agent_id: str) -> Any | None:
        try:
            candidate = self._registry.get(_id(agent_id))
        except Exception:
            logger.warning(
                "Crew finalization agent lookup failed for agent=%s; authority "
                "cannot be proven and the session will fail closed",
                agent_id,
                exc_info=True,
            )
            return None
        if (
            candidate is None
            or getattr(candidate, "id", None) != agent_id
            or getattr(candidate, "is_alive", None) is not True
        ):
            return None
        return candidate

    def _validate_outcome_verifiers(
        self,
        outcome: SessionConvergenceOutcome,
        *,
        excluded_agent_ids: frozenset[str],
    ) -> None:
        if type(outcome.history) is not tuple or not outcome.history:
            raise ValueError("crew_finalization_verifier_invalid")
        for round_record in outcome.history:
            self._validate_verifier_identity(
                round_record.verdict,
                excluded_agent_ids=excluded_agent_ids,
            )

    @classmethod
    def _validate_convergence_binding(
        cls,
        *,
        child: WorkItem,
        initial: _InitialResultBinding,
        outcome: SessionConvergenceOutcome,
        thread_id: str,
    ) -> None:
        if (
            outcome.result.work_item_id != child.id
            or outcome.result.work_item_id != initial.work_item_id
            or outcome.result.spec_id != initial.spec_id
            or outcome.result.agent_id != initial.agent_id
            or outcome.result.agent_id != child.assigned_to
            or outcome.result.status != initial.status
            or outcome.result.stopped_reason != initial.stopped_reason
            or type(outcome.result.started_at) is not float
            or outcome.result.started_at != initial.started_at
            or type(outcome.result.finished_at) is not float
            or outcome.result.finished_at != initial.finished_at
            or not _json_exactly_equal(
                outcome.result.blocked_dependency_ids,
                list(initial.blocked_dependency_ids),
            )
            or type(outcome.history) is not tuple
            or not outcome.history
        ):
            raise ValueError("crew_finalization_convergence_binding_invalid")
        round_zero = outcome.history[0]
        if (
            type(round_zero.round_index) is not int
            or round_zero.round_index != 0
            or type(round_zero.result_revision) is not int
            or round_zero.result_revision != 1
            or round_zero.result_text != initial.output
            or round_zero.result_sha256
            != hashlib.sha256(initial.output.encode("utf-8")).hexdigest()
            or round_zero.result_summary != initial.output.strip()[:4_096]
            or round_zero.stopped_reason != initial.stopped_reason
            or round_zero.stopped_reason != "complete"
            or type(round_zero.correction_tokens) is not int
            or round_zero.correction_tokens != 0
            or not _json_exactly_equal(
                round_zero.tool_trace_ref,
                initial.tool_trace_ref,
            )
            or not _json_exactly_equal(
                list(round_zero.artifact_refs),
                list(initial.artifact_refs),
            )
        ):
            raise ValueError("crew_finalization_convergence_binding_invalid")
        expected_result_tokens = (
            initial.actual_tokens
            if len(outcome.history) == 1
            else outcome.history[-1].correction_tokens
        )
        if (
            type(outcome.result.actual_tokens) is not int
            or type(expected_result_tokens) is not int
            or outcome.result.actual_tokens != expected_result_tokens
        ):
            raise ValueError("crew_finalization_convergence_binding_invalid")

    @classmethod
    def _initial_result_binding(
        cls,
        result: SubtaskResult,
        *,
        thread_id: str,
    ) -> _InitialResultBinding:
        artifacts = cls._artifact_refs(
            result.artifact_refs,
            thread_id=thread_id,
        )
        if not _json_exactly_equal(result.blocked_dependency_ids, []):
            raise ValueError("child_result_invalid")
        return _InitialResultBinding(
            work_item_id=result.work_item_id,
            spec_id=result.spec_id,
            agent_id=result.agent_id,
            output=_text(
                result.output,
                maximum_codepoints=_MAX_RESULT_BYTES,
                maximum_bytes=_MAX_RESULT_BYTES,
            ),
            status=result.status,
            tool_trace_ref=result.tool_trace_ref,
            started_at=result.started_at,
            finished_at=result.finished_at,
            stopped_reason=result.stopped_reason,
            actual_tokens=result.actual_tokens,
            artifact_refs=tuple(dict(ref) for ref in artifacts),
            blocked_dependency_ids=(),
        )

    def _validate_verifier_identity(
        self,
        verdict: SessionVerificationPass,
        *,
        excluded_agent_ids: frozenset[str],
    ) -> None:
        verifier_id = getattr(verdict, "verifier_agent_id", None)
        status = getattr(verdict, "status", None)
        if verifier_id == "" and status in {"unavailable", "error"}:
            return
        if (
            type(verifier_id) is not str
            or verifier_id in excluded_agent_ids
            or self._live_agent(verifier_id) is None
        ):
            raise ValueError("crew_finalization_verifier_invalid")

    @staticmethod
    def _snapshot_child(child: WorkItem) -> dict[str, Any]:
        if child.verification != {} or child.assigned_to is None or child.parent_id is None:
            raise ValueError("child_result_invalid")
        return {
            "verification": _detached(child.verification),
            "work_type": child.work_type,
            "status": child.status,
            "assigned_to": child.assigned_to,
            "parent_id": child.parent_id,
            "title": child.title,
            "description": child.description,
            "depends_on": _detached(child.depends_on),
            "metadata": _detached(child.metadata),
            "actual_tokens": child.actual_tokens,
        }

    @staticmethod
    def _expected_output(child: WorkItem) -> str | None:
        value = (child.metadata or {}).get("expected_output")
        if value is None:
            return None
        return _text(
            value,
            maximum_codepoints=32_768,
            maximum_bytes=32_768,
        )

    @classmethod
    def _verification_document(
        cls,
        *,
        parent_id: str,
        thread_id: str,
        producer_agent_id: str,
        outcome: SessionConvergenceOutcome,
    ) -> dict[str, Any]:
        if outcome.result.work_item_id != _id(outcome.result.work_item_id):
            raise ValueError("crew_finalization_verification_invalid")
        if outcome.result.agent_id != producer_agent_id:
            raise ValueError("crew_finalization_verification_invalid")
        if (
            not outcome.history
            or outcome.result.status != "done"
            or outcome.result.stopped_reason != "complete"
            or outcome.result.output != outcome.history[-1].result_text
            or outcome.result.tool_trace_ref != outcome.history[-1].tool_trace_ref
            or not _json_exactly_equal(
                outcome.result.artifact_refs,
                list(outcome.history[-1].artifact_refs),
            )
        ):
            raise ValueError("crew_finalization_verification_invalid")
        rounds = [cls._round_document(item) for item in outcome.history]
        terminal = (
            cls._terminal_document(outcome.terminal_attempt)
            if outcome.terminal_attempt is not None
            else None
        )
        try:
            record = ChildVerificationRecord.model_validate({
                "version": 1,
                "parent_id": parent_id,
                "work_item_id": outcome.result.work_item_id,
                "thread_id": thread_id,
                "producer_agent_id": producer_agent_id,
                "status": outcome.status,
                "accepted": outcome.accepted,
                "rounds_used": outcome.rounds_used,
                "result_revision_count": len(rounds),
                "rounds": rounds,
                "failure_code": outcome.failure_code,
                "terminal_attempt": terminal,
            })
        except ValidationError as exc:
            raise ValueError("crew_finalization_verification_invalid") from exc
        return record.model_dump(mode="json")

    @classmethod
    def _round_document(cls, item: SessionVerificationRound) -> dict[str, Any]:
        result_text = _text(
            item.result_text,
            maximum_codepoints=_MAX_RESULT_BYTES,
            maximum_bytes=_MAX_RESULT_BYTES,
        )
        if hashlib.sha256(result_text.encode("utf-8")).hexdigest() != item.result_sha256:
            raise ValueError("crew_finalization_round_invalid")
        if item.result_summary != result_text.strip()[:4_096]:
            raise ValueError("crew_finalization_round_invalid")
        return {
            "round_index": item.round_index,
            "result_revision": item.result_revision,
            "result_sha256": item.result_sha256,
            "result_summary": item.result_summary,
            "stopped_reason": item.stopped_reason,
            "correction_tokens": item.correction_tokens,
            "verifier_tokens": item.verifier_tokens,
            "tool_trace_ref": item.tool_trace_ref,
            "artifact_refs": [dict(ref) for ref in item.artifact_refs],
            "verdict": cls._verdict_document(item.verdict),
        }

    @staticmethod
    def _verdict_document(item: SessionVerificationPass) -> dict[str, Any]:
        try:
            record = _VerdictRecord.model_validate({
                "status": item.status,
                "accepted": item.accepted,
                "confidence": item.confidence,
                "critique": item.critique,
                "verifier_agent_id": item.verifier_agent_id,
                "tokens_used": item.tokens_used,
                "failure_code": item.failure_code,
            })
        except (AttributeError, ValidationError) as exc:
            raise ValueError("crew_finalization_verdict_invalid") from exc
        return record.model_dump(mode="json")

    @classmethod
    def _terminal_document(
        cls,
        item: SessionCorrectionTerminalAttempt,
    ) -> dict[str, Any]:
        if item.result_text:
            result_text = _text(
                item.result_text,
                maximum_codepoints=_MAX_RESULT_BYTES,
                maximum_bytes=_MAX_RESULT_BYTES,
            )
            if hashlib.sha256(result_text.encode("utf-8")).hexdigest() != item.result_sha256:
                raise ValueError("crew_finalization_terminal_invalid")
            if item.result_summary != result_text.strip()[:4_096]:
                raise ValueError("crew_finalization_terminal_invalid")
        elif item.result_sha256 is not None:
            raise ValueError("crew_finalization_terminal_invalid")
        elif item.result_summary:
            raise ValueError("crew_finalization_terminal_invalid")
        return {
            "attempt_index": item.attempt_index,
            "attempted_revision": item.attempted_revision,
            "stopped_reason": item.stopped_reason,
            "result_sha256": item.result_sha256,
            "result_summary": item.result_summary,
            "correction_tokens": item.correction_tokens,
            "tool_trace_ref": item.tool_trace_ref,
            "artifact_refs": [dict(ref) for ref in item.artifact_refs],
            "denied_tools": list(item.denied_tools),
            "failure_code": item.failure_code,
        }

    @staticmethod
    def _correction_tokens(outcome: SessionConvergenceOutcome) -> int:
        total = 0
        for round_record in outcome.history:
            tokens = _exact_int(round_record.correction_tokens)
            if total > _MAX_TOKEN_TOTAL - tokens:
                raise ValueError("crew_finalization_token_overflow")
            total += tokens
        if outcome.terminal_attempt is not None:
            tokens = _exact_int(outcome.terminal_attempt.correction_tokens)
            if total > _MAX_TOKEN_TOTAL - tokens:
                raise ValueError("crew_finalization_token_overflow")
            total += tokens
        return total

    @staticmethod
    def _accepted_count(publications: list[_ChildPublication]) -> int:
        return sum(
            1
            for publication in publications
            if publication.outcome.accepted is True
        )

    @staticmethod
    def _outcome_failure(outcome: SessionConvergenceOutcome) -> tuple[str, bool]:
        mapping: dict[SessionVerificationFailureCode | None, tuple[str, bool]] = {
            "independent_verifier_unavailable": ("independent_verifier_unavailable", True),
            "verification_defect": ("verification_defect", False),
            "correction_capability_denied": ("correction_capability_denied", True),
            "correction_budget_exhausted": ("correction_budget_exhausted", True),
            "correction_execution_defect": ("correction_execution_defect", False),
            "convergence_exhausted": ("convergence_exhausted", False),
            None: ("verification_defect", False),
        }
        return mapping[outcome.failure_code]

    @classmethod
    def _artifact_refs(cls, value: Any, *, thread_id: str) -> list[dict[str, Any]]:
        if type(value) is not list or len(value) > 32:
            raise ValueError("crew_finalization_artifact_invalid")
        refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in value:
            if type(raw) is not dict or set(raw) != _ARTIFACT_KEYS:
                raise ValueError("crew_finalization_artifact_invalid")
            try:
                record = _ArtifactRef.model_validate(raw)
            except ValidationError as exc:
                raise ValueError("crew_finalization_artifact_invalid") from exc
            if record.thread_id != thread_id or record.artifact_id in seen:
                raise ValueError("crew_finalization_artifact_invalid")
            seen.add(record.artifact_id)
            refs.append(record.model_dump(mode="json"))
        return refs

    async def _final_expected_output(
        self,
        *,
        session: CrewSessionContract,
        publications: list[_ChildPublication],
        candidate: dict[str, Any],
    ) -> str:
        chunks = [
            f"PARENT GOAL:\n{session.goal}\n\n",
            "SUCCESS CRITERIA:\n",
        ]
        chunks.extend(
            f"{index}. {criterion}\n"
            for index, criterion in enumerate(session.success_criteria, start=1)
        )
        chunks.extend([
            f"\nEXPECTED DELIVERABLE:\n{session.expected_deliverable}\n\n",
            "CHILD ARTIFACT MANIFEST:\n[",
        ])
        byte_count = sum(len(chunk.encode("utf-8")) for chunk in chunks)
        for index, publication in enumerate(publications):
            refs = await self._child_manifest_refs(
                publication,
                thread_id=session.thread_id,
            )
            entry = json.dumps(
                {
                    "work_item_id": publication.child.id,
                    "artifact_refs": refs,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            if index:
                entry = "," + entry
            byte_count += len(entry.encode("utf-8"))
            if byte_count > _MAX_EXPECTED_PROMPT_BYTES:
                raise ValueError("crew_finalization_expected_prompt_too_large")
            chunks.append(entry)
        candidate_text = json.dumps(
            candidate,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        tail = ["]\n\nCANDIDATE RESULT:\n", candidate_text]
        byte_count += sum(len(chunk.encode("utf-8")) for chunk in tail)
        if byte_count > _MAX_EXPECTED_PROMPT_BYTES:
            raise ValueError("crew_finalization_expected_prompt_too_large")
        chunks.extend(tail)
        prompt = "".join(chunks)
        return prompt

    async def _child_manifest_refs(
        self,
        publication: _ChildPublication,
        *,
        thread_id: str,
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        history = publication.outcome.history
        ordered_rounds = (history[-1], *history[:-1])
        for round_record in ordered_rounds:
            validated = self._artifact_refs(
                list(round_record.artifact_refs),
                thread_id=thread_id,
            )
            for ref in validated:
                if ref["artifact_id"] in seen:
                    continue
                if len(selected) == 32:
                    break
                seen.add(ref["artifact_id"])
                selected.append(ref)
            if len(selected) == 32:
                break
        resolved: list[dict[str, Any]] = []
        for ref in selected:
            artifact = await asyncio.to_thread(
                self._artifacts.get,
                ref["artifact_id"],
            )
            if artifact is None:
                raise ValueError("crew_finalization_artifact_invalid")
            authoritative = {
                "artifact_id": artifact.id,
                "content_hash": artifact.content_hash,
                "thread_id": artifact.thread_id,
                "name": artifact.name,
                "mime": artifact.mime,
                "size_bytes": artifact.size_bytes,
                "version": artifact.version,
            }
            if (
                artifact.thread_id != thread_id
                or not _json_exactly_equal(authoritative, ref)
            ):
                raise ValueError("crew_finalization_artifact_invalid")
            resolved.append(ref)
        return resolved

    @staticmethod
    def _final_result(
        parent_id: str,
        facilitator_id: str,
        final_text: str,
    ) -> SubtaskResult:
        from probos.cognitive.crew_executor import SubtaskResult

        return SubtaskResult(
            work_item_id=parent_id,
            spec_id="crew-session-final",
            agent_id=facilitator_id,
            output=final_text,
            status="done",
            stopped_reason="complete",
        )

    async def _publish(
        self,
        *,
        session: CrewSessionContract,
        publications: list[_ChildPublication],
        draft: SessionSynthesisDraft,
        final_verdict: SessionVerificationPass,
        result_bytes: bytes,
        result_hash: str,
    ) -> CrewSessionFinalizationResult:
        artifact: Artifact | None = None
        provenance_ref: str | None = None
        result_blob_written = False
        try:
            await self._attachments.write(
                result_hash,
                result_bytes,
                "text/markdown",
                origin="agent_artifact",
            )
            result_blob_written = True
            result_readback = await self._attachments.read(result_hash)
            if (
                result_readback != result_bytes
                or hashlib.sha256(result_readback).hexdigest() != result_hash
            ):
                raise ValueError("crew_finalization_result_readback_failed")
            room = await asyncio.to_thread(self._threads.get_thread, session.thread_id)
            if room is None or room.task_id != session.task_id:
                raise ValueError("crew_finalization_room_invalid")
            artifact_task = asyncio.create_task(asyncio.to_thread(
                self._artifacts.add_version,
                thread_id=session.thread_id,
                name="crew-result.md",
                content_hash=result_hash,
                mime="text/markdown",
                size_bytes=len(result_bytes),
                created_by=session.facilitator_id,
            ))
            try:
                artifact = await asyncio.shield(artifact_task)
            except asyncio.CancelledError:
                worker_failed = False
                while not artifact_task.done():
                    try:
                        await asyncio.shield(artifact_task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        worker_failed = True
                        logger.warning(
                            "Crew result Artifact creation failed after cancellation "
                            "parent=%s content_hash=%s; no Artifact identity was "
                            "returned and the original cancellation will propagate",
                            session.task_id,
                            result_hash,
                            exc_info=True,
                        )
                        break
                if not worker_failed:
                    try:
                        artifact = artifact_task.result()
                    except Exception:
                        logger.warning(
                            "Crew result Artifact creation failed after cancellation "
                            "parent=%s content_hash=%s; no Artifact identity was "
                            "returned and the original cancellation will propagate",
                            session.task_id,
                            result_hash,
                            exc_info=True,
                        )
                raise
            artifact_ref = self._validate_result_artifact(
                artifact,
                session=session,
                result_hash=result_hash,
                size_bytes=len(result_bytes),
            )
            provenance = self._provenance_document(
                session=session,
                publications=publications,
                draft=draft,
                final_verdict=final_verdict,
                artifact_ref=artifact_ref,
            )
            provenance_bytes = _compact_bytes(
                provenance,
                maximum=_MAX_PROVENANCE_BYTES,
                error="crew_finalization_provenance_too_large",
            )
            provenance_ref = hashlib.sha256(provenance_bytes).hexdigest()
            await self._attachments.write(
                provenance_ref,
                provenance_bytes,
                "application/json",
                origin="chat_attachment",
            )
            provenance_readback = await self._attachments.read(provenance_ref)
            if (
                provenance_readback != provenance_bytes
                or hashlib.sha256(provenance_readback).hexdigest() != provenance_ref
            ):
                raise ValueError("crew_finalization_provenance_readback_failed")
            synthesis = self._synthesis_metadata(
                publications=publications,
                draft=draft,
                final_verdict=final_verdict,
                artifact_ref=artifact_ref,
                result_hash=result_hash,
                provenance_ref=provenance_ref,
            )
            trust_effects = self._completed_trust_effects(
                session=session,
                publications=publications,
                final_verdict=final_verdict,
                final_evidence_sha256=provenance_ref,
            )
            trust_kwargs = (
                {"crew_trust_effects": trust_effects}
                if trust_effects
                else {}
            )
            completed = await self._sessions.publish_verified_result(
                session.task_id,
                expected_revision=session.revision,
                expected_recovery=None,
                expected_direct_children=tuple(
                    publication.child_snapshot
                    for publication in sorted(
                        publications,
                        key=lambda item: item.child.id,
                    )
                ),
                crew_synth=synthesis,
                last_result_summary=draft.final_text[:4_096],
                provenance_ref=provenance_ref,
                result_artifact_id=artifact.id,
                **trust_kwargs,
            )
        except asyncio.CancelledError:
            logger.warning(
                "Crew result publication was cancelled parent=%s "
                "artifact_id=%s content_hash=%s provenance_ref=%s; a write in "
                "progress may have created an orphan, and any created blob or "
                "Artifact is retained for the existing reaper/manual audit",
                session.task_id,
                artifact.id if artifact is not None else None,
                result_hash,
                provenance_ref,
            )
            raise
        except Exception:
            if result_blob_written:
                logger.warning(
                    "Crew result publication failed after result storage "
                    "parent=%s artifact_id=%s content_hash=%s provenance_ref=%s; "
                    "the orphan is retained for the existing reaper/manual audit",
                    session.task_id,
                    artifact.id if artifact is not None else None,
                    result_hash,
                    provenance_ref,
                    exc_info=True,
                )
            return await self._fail(
                session,
                reason="result_publication_failed",
                accepted_count=self._accepted_count(publications),
                total_count=len(publications),
            )
        await self.drain_pending_trust()
        return CrewSessionFinalizationResult(
            parent_id=session.task_id,
            claimed=True,
            state=completed.state,
            completed=True,
            final_output=draft.final_text,
            accepted_count=self._accepted_count(publications),
            total_count=len(publications),
            result_artifact_id=artifact.id,
            provenance_ref=provenance_ref,
            reason="completed",
        )

    async def _fail_verified(
        self,
        session: CrewSessionContract,
        *,
        reason: str,
        accepted_count: int,
        total_count: int,
        effects: tuple[CrewTrustEffect, ...],
        recovery: Any | None,
    ) -> CrewSessionFinalizationResult:
        if not effects:
            raise ValueError("crew_trust_evidence_invalid")
        transitioned = await self._sessions.fail_verified_outcome(
            session.task_id,
            expected_revision=session.revision,
            reason=reason,
            expected_recovery=recovery,
            crew_trust_effects=effects,
            evidence_refs=self._effect_evidence_refs(effects),
        )
        await self.drain_pending_trust()
        return CrewSessionFinalizationResult(
            parent_id=session.task_id,
            claimed=True,
            state=transitioned.state,
            completed=False,
            final_output="",
            accepted_count=accepted_count,
            total_count=total_count,
            result_artifact_id=None,
            provenance_ref=None,
            reason=reason,
        )

    @staticmethod
    def _publication_child_snapshot(child: WorkItem) -> dict[str, Any]:
        values = child.to_dict()
        values.pop("updated_at")
        return json.loads(_compact_bytes(
            values,
            maximum=_MAX_CHILD_SNAPSHOT_BYTES,
            error="crew_finalization_child_snapshot_invalid",
        ))

    @staticmethod
    def _validate_result_artifact(
        artifact: Artifact,
        *,
        session: CrewSessionContract,
        result_hash: str,
        size_bytes: int,
    ) -> dict[str, Any]:
        if (
            type(getattr(artifact, "id", None)) is not str
            or _ID_RE.fullmatch(artifact.id) is None
            or artifact.thread_id != session.thread_id
            or artifact.name != "crew-result.md"
            or artifact.content_hash != result_hash
            or artifact.mime != "text/markdown"
            or type(artifact.size_bytes) is not int
            or artifact.size_bytes != size_bytes
            or artifact.created_by != session.facilitator_id
            or type(artifact.version) is not int
            or artifact.version <= 0
        ):
            raise ValueError("crew_finalization_artifact_invalid")
        return _ArtifactRef.model_validate({
            "artifact_id": artifact.id,
            "content_hash": artifact.content_hash,
            "thread_id": artifact.thread_id,
            "name": artifact.name,
            "mime": artifact.mime,
            "size_bytes": artifact.size_bytes,
            "version": artifact.version,
        }).model_dump(mode="json")

    @classmethod
    def _provenance_document(
        cls,
        *,
        session: CrewSessionContract,
        publications: list[_ChildPublication],
        draft: SessionSynthesisDraft,
        final_verdict: SessionVerificationPass,
        artifact_ref: dict[str, Any],
    ) -> dict[str, Any]:
        result_hash = hashlib.sha256(draft.final_text.encode("utf-8")).hexdigest()
        document = {
            "version": 1,
            "origin": "crew_session_finalizer",
            "parent_id": session.task_id,
            "thread_id": session.thread_id,
            "goal": session.goal,
            "success_criteria": list(session.success_criteria),
            "expected_deliverable": session.expected_deliverable,
            "children": [],
            "synthesis": {
                "producer_agent_id": draft.producer_agent_id,
                "final_text": draft.final_text,
                "result_sha256": result_hash,
                "tokens_used": draft.tokens_used,
            },
            "final_verification": cls._verdict_document(final_verdict),
            "result_artifact": _detached(artifact_ref),
        }
        base_size = len(_compact_bytes(
            document,
            maximum=_MAX_PROVENANCE_BYTES,
            error="crew_finalization_provenance_too_large",
        ))
        child_bytes = 0
        for publication in publications:
            revisions = [
                {
                    "round_index": item.round_index,
                    "result_revision": item.result_revision,
                    "result_text": item.result_text,
                    "result_sha256": item.result_sha256,
                }
                for item in publication.outcome.history
            ]
            terminal_text = (
                publication.outcome.terminal_attempt.result_text
                if publication.outcome.terminal_attempt is not None
                and publication.outcome.terminal_attempt.result_text
                else None
            )
            child_entry = {
                "work_item_id": publication.child.id,
                "verification": _detached(publication.verification),
                "result_revisions": revisions,
                "terminal_result_text": terminal_text,
            }
            entry_size = len(_compact_bytes(
                child_entry,
                maximum=_MAX_PROVENANCE_BYTES,
                error="crew_finalization_provenance_too_large",
            ))
            projected = base_size + child_bytes + entry_size
            if document["children"]:
                projected += 1
            if projected > _MAX_PROVENANCE_BYTES:
                raise ValueError("crew_finalization_provenance_too_large")
            child_bytes += entry_size + (1 if document["children"] else 0)
            document["children"].append(child_entry)
        return document

    @classmethod
    def _synthesis_metadata(
        cls,
        *,
        publications: list[_ChildPublication],
        draft: SessionSynthesisDraft,
        final_verdict: SessionVerificationPass,
        artifact_ref: dict[str, Any],
        result_hash: str,
        provenance_ref: str,
    ) -> CrewSynthesisMetadata:
        convergence_rounds = sum(item.outcome.rounds_used for item in publications)
        correction_tokens = sum(
            cls._correction_tokens(item.outcome) for item in publications
        )
        verification_tokens = final_verdict.tokens_used + sum(
            round_record.verifier_tokens
            for item in publications
            for round_record in item.outcome.history
        )
        return CrewSynthesisMetadata.model_validate({
            "version": 1,
            "completed": True,
            "producer_agent_id": draft.producer_agent_id,
            "final_verifier_agent_id": final_verdict.verifier_agent_id,
            "final_confidence": final_verdict.confidence,
            "final_critique": final_verdict.critique,
            "accepted_count": cls._accepted_count(publications),
            "total_count": len(publications),
            "convergence_rounds": convergence_rounds,
            "correction_tokens": correction_tokens,
            "verification_tokens": verification_tokens,
            "synthesis_tokens": draft.tokens_used,
            "result_artifact_id": artifact_ref["artifact_id"],
            "result_content_hash": result_hash,
            "provenance_ref": provenance_ref,
        })

    async def _fail(
        self,
        session: CrewSessionContract,
        *,
        reason: str,
        accepted_count: int,
        total_count: int,
        blocked: bool = False,
    ) -> CrewSessionFinalizationResult:
        target = "blocked_needs_captain" if blocked else "failed"
        try:
            transitioned = await self._sessions.transition_session(
                session.task_id,
                target,
                expected_revision=session.revision,
                blocked_reason=reason if blocked else None,
                last_result_summary=reason,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error(
                "Crew finalization terminal transition failed parent=%s "
                "target=%s reason=%s; the session remains non-done and the "
                "canonical transition error propagates",
                session.task_id,
                target,
                reason,
                exc_info=True,
            )
            raise
        return CrewSessionFinalizationResult(
            parent_id=session.task_id,
            claimed=True,
            state=transitioned.state,
            completed=False,
            final_output="",
            accepted_count=accepted_count,
            total_count=total_count,
            result_artifact_id=None,
            provenance_ref=None,
            reason=reason,
        )

    @staticmethod
    def _observation(
        session: CrewSessionContract,
        *,
        reason: str,
    ) -> CrewSessionFinalizationResult:
        return CrewSessionFinalizationResult(
            parent_id=session.task_id,
            claimed=False,
            state=session.state,
            completed=False,
            final_output="",
            accepted_count=0,
            total_count=0,
            result_artifact_id=session.result_artifact_id,
            provenance_ref=session.result_ref,
            reason=reason,
        )