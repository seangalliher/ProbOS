"""Outcome-only trust effects for durable CrewSession finalization."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from probos.consensus.shapley import MAX_EXACT_SHAPLEY, compute_shapley_values
from probos.types import Vote

logger = logging.getLogger(__name__)

CrewTrustRole = Literal[
    "child_producer",
    "child_verifier",
    "facilitator",
    "final_verifier",
]

_SOURCE = "crew_session_outcome"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ROLES = frozenset({
    "child_producer",
    "child_verifier",
    "facilitator",
    "final_verifier",
})
_EFFECT_KEYS = frozenset({
    "outcome_id",
    "session_id",
    "session_revision",
    "evidence_sha256",
    "agent_id",
    "role",
    "work_item_id",
    "result_revision",
    "success",
    "weight",
    "intent_type",
    "verifier_id",
    "source",
})
_MAX_EFFECT_BYTES = 8_192
_MAX_EVIDENCE_BYTES = 262_144
_MAX_CHILDREN = 1_000
MAX_CREW_TRUST_EFFECTS = (_MAX_CHILDREN * 10) + 2


def _exact_json_bytes(
    value: Any,
    *,
    error: str,
    maximum: int = _MAX_EFFECT_BYTES,
) -> bytes:
    def _validate(current: Any) -> None:
        if current is None or type(current) in (bool, int, str):
            return
        if type(current) is float:
            if not math.isfinite(current):
                raise ValueError(error)
            return
        if type(current) is list:
            for item in current:
                _validate(item)
            return
        if type(current) is dict:
            if any(type(key) is not str for key in current):
                raise ValueError(error)
            for item in current.values():
                _validate(item)
            return
        raise ValueError(error)

    try:
        _validate(value)
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise ValueError(error) from exc
    if len(encoded) > maximum:
        raise ValueError(error)
    return encoded


def _required_id(value: Any, *, error: str = "crew_trust_effect_invalid") -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ValueError(error)
    return value


def _required_sha(value: Any, *, error: str = "crew_trust_effect_invalid") -> str:
    if type(value) is not str or _SHA_RE.fullmatch(value) is None:
        raise ValueError(error)
    return value


def _all_approved_shapley(
    votes: list[Vote],
    *,
    use_confidence_weights: bool,
) -> dict[str, float]:
    if not votes:
        raise ValueError("crew_trust_evidence_invalid")
    if use_confidence_weights:
        positive_count = sum(vote.confidence > 0.0 for vote in votes)
        if positive_count > 0:
            exact_share = 1.0 / positive_count
            return {
                vote.agent_id: exact_share if vote.confidence > 0.0 else 0.0
                for vote in votes
            }
    exact_share = 1.0 / len(votes)
    return {vote.agent_id: exact_share for vote in votes}


@dataclass(frozen=True, slots=True)
class CrewTrustEffect:
    outcome_id: str
    session_id: str
    session_revision: int
    evidence_sha256: str
    agent_id: str
    role: CrewTrustRole
    work_item_id: str
    result_revision: int
    success: bool
    weight: float
    intent_type: str
    verifier_id: str
    source: Literal["crew_session_outcome"] = _SOURCE

    def __post_init__(self) -> None:
        _required_sha(self.outcome_id, error="trust_outcome_identity_conflict")
        _required_id(self.session_id)
        _required_sha(self.evidence_sha256)
        _required_id(self.agent_id)
        _required_id(self.work_item_id)
        _required_id(self.intent_type)
        _required_id(self.verifier_id)
        if (
            type(self.role) is not str
            or self.role not in _ROLES
            or type(self.source) is not str
            or self.source != _SOURCE
        ):
            raise ValueError("crew_trust_effect_invalid")
        if (
            type(self.session_revision) is not int
            or not 1 <= self.session_revision <= 2_147_483_647
            or type(self.result_revision) is not int
            or not 1 <= self.result_revision <= 2_147_483_647
            or type(self.success) is not bool
            or type(self.weight) is not float
            or not math.isfinite(self.weight)
            or not 0.0 < self.weight <= 1.0
        ):
            raise ValueError("crew_trust_effect_invalid")
        expected = hashlib.sha256(self.semantic_bytes()).hexdigest()
        if self.outcome_id != expected:
            raise ValueError("trust_outcome_identity_conflict")

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        session_revision: int,
        evidence_sha256: str,
        agent_id: str,
        role: CrewTrustRole,
        work_item_id: str,
        result_revision: int,
        success: bool,
        weight: float,
        intent_type: str,
        verifier_id: str,
    ) -> CrewTrustEffect:
        semantic = {
            "agent_id": agent_id,
            "evidence_sha256": evidence_sha256,
            "intent_type": intent_type,
            "result_revision": result_revision,
            "role": role,
            "session_id": session_id,
            "session_revision": session_revision,
            "source": _SOURCE,
            "success": success,
            "verifier_id": verifier_id,
            "weight": weight,
            "work_item_id": work_item_id,
        }
        outcome_id = hashlib.sha256(
            _exact_json_bytes(semantic, error="crew_trust_effect_invalid"),
        ).hexdigest()
        return cls(outcome_id=outcome_id, **semantic)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CrewTrustEffect:
        if type(payload) is not dict or set(payload) != _EFFECT_KEYS:
            raise ValueError("crew_trust_effect_invalid")
        detached = json.loads(
            _exact_json_bytes(payload, error="crew_trust_effect_invalid"),
        )
        return cls(**detached)

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "evidence_sha256": self.evidence_sha256,
            "intent_type": self.intent_type,
            "result_revision": self.result_revision,
            "role": self.role,
            "session_id": self.session_id,
            "session_revision": self.session_revision,
            "source": self.source,
            "success": self.success,
            "verifier_id": self.verifier_id,
            "weight": self.weight,
            "work_item_id": self.work_item_id,
        }

    def semantic_bytes(self) -> bytes:
        return _exact_json_bytes(
            self.semantic_payload(),
            error="crew_trust_effect_invalid",
        )

    def to_payload(self) -> dict[str, Any]:
        return {"outcome_id": self.outcome_id, **self.semantic_payload()}

    def canonical_bytes(self) -> bytes:
        return _exact_json_bytes(
            self.to_payload(),
            error="crew_trust_effect_invalid",
        )


@dataclass(frozen=True, slots=True)
class _ChildEvidence:
    parent_id: str
    work_item_id: str
    producer_agent_id: str
    status: str
    accepted: bool
    failure_code: str | None
    rounds: tuple[dict[str, Any], ...]
    evidence_sha256: str


def _child_evidence(payload: dict[str, Any]) -> _ChildEvidence:
    expected_keys = {
        "version",
        "parent_id",
        "work_item_id",
        "thread_id",
        "producer_agent_id",
        "status",
        "accepted",
        "rounds_used",
        "result_revision_count",
        "rounds",
        "failure_code",
        "terminal_attempt",
    }
    if type(payload) is not dict or set(payload) != expected_keys:
        raise ValueError("crew_trust_evidence_invalid")
    detached = json.loads(
        _exact_json_bytes(
            payload,
            error="crew_trust_evidence_invalid",
            maximum=_MAX_EVIDENCE_BYTES,
        ),
    )
    rounds = detached["rounds"]
    if (
        detached["version"] != 1
        or type(detached["accepted"]) is not bool
        or type(rounds) is not list
        or not 1 <= len(rounds) <= 9
        or type(detached["result_revision_count"]) is not int
        or detached["result_revision_count"] != len(rounds)
    ):
        raise ValueError("crew_trust_evidence_invalid")
    parent_id = _required_id(
        detached["parent_id"],
        error="crew_trust_evidence_invalid",
    )
    work_item_id = _required_id(
        detached["work_item_id"],
        error="crew_trust_evidence_invalid",
    )
    _required_id(detached["thread_id"], error="crew_trust_evidence_invalid")
    producer_id = _required_id(
        detached["producer_agent_id"],
        error="crew_trust_evidence_invalid",
    )
    for index, round_record in enumerate(rounds):
        if type(round_record) is not dict:
            raise ValueError("crew_trust_evidence_invalid")
        verdict = round_record.get("verdict")
        if (
            type(round_record.get("round_index")) is not int
            or round_record["round_index"] != index
            or type(round_record.get("result_revision")) is not int
            or round_record["result_revision"] != index + 1
            or type(verdict) is not dict
            or verdict.get("status") not in {
                "accepted",
                "refuted",
                "unavailable",
                "malformed",
                "error",
            }
            or type(verdict.get("accepted")) is not bool
            or verdict["accepted"] != (verdict["status"] == "accepted")
            or type(verdict.get("confidence")) not in (int, float)
            or not math.isfinite(float(verdict["confidence"]))
            or not 0.0 <= float(verdict["confidence"]) <= 1.0
        ):
            raise ValueError("crew_trust_evidence_invalid")
        verifier_id = verdict.get("verifier_agent_id")
        if verdict["status"] in {"accepted", "refuted"}:
            _required_id(verifier_id, error="crew_trust_evidence_invalid")
        elif verifier_id != "":
            _required_id(verifier_id, error="crew_trust_evidence_invalid")
    return _ChildEvidence(
        parent_id=parent_id,
        work_item_id=work_item_id,
        producer_agent_id=producer_id,
        status=str(detached["status"]),
        accepted=detached["accepted"],
        failure_code=detached["failure_code"],
        rounds=tuple(rounds),
        evidence_sha256=hashlib.sha256(
            _exact_json_bytes(
                detached,
                error="crew_trust_evidence_invalid",
                maximum=_MAX_EVIDENCE_BYTES,
            ),
        ).hexdigest(),
    )


def derive_completed_crew_trust_effects(
    *,
    session_id: str,
    session_revision: int,
    child_verifications: tuple[dict[str, Any], ...],
    facilitator_id: str,
    final_verifier_id: str,
    final_confidence: float,
    final_evidence_sha256: str,
    approval_threshold: float,
    use_confidence_weights: bool,
) -> tuple[CrewTrustEffect, ...]:
    if (
        type(child_verifications) is not tuple
        or not 1 <= len(child_verifications) <= _MAX_CHILDREN
        or type(final_confidence) not in (int, float)
        or not math.isfinite(float(final_confidence))
        or not 0.0 <= float(final_confidence) <= 1.0
        or type(approval_threshold) not in (int, float)
        or not math.isfinite(float(approval_threshold))
        or not 0.0 <= float(approval_threshold) <= 1.0
        or type(use_confidence_weights) is not bool
    ):
        raise ValueError("crew_trust_evidence_invalid")
    _required_id(session_id, error="crew_trust_evidence_invalid")
    _required_id(facilitator_id, error="crew_trust_evidence_invalid")
    _required_id(final_verifier_id, error="crew_trust_evidence_invalid")
    _required_sha(final_evidence_sha256, error="crew_trust_evidence_invalid")
    children = tuple(sorted(
        (_child_evidence(value) for value in child_verifications),
        key=lambda child: child.work_item_id,
    ))
    if (
        any(child.parent_id != session_id for child in children)
        or len({child.work_item_id for child in children}) != len(children)
    ):
        raise ValueError("crew_trust_evidence_invalid")
    if any(
        not child.accepted
        or child.status != "converged"
        or child.failure_code is not None
        or child.rounds[-1]["verdict"]["status"] != "accepted"
        for child in children
    ):
        raise ValueError("crew_trust_evidence_invalid")

    vote_keys = [f"child:{child.work_item_id}" for child in children]
    facilitator_vote_key = f"facilitator:{session_id}"
    votes = [
        Vote(
            agent_id=vote_key,
            approved=True,
            confidence=float(child.rounds[-1]["verdict"]["confidence"]),
        )
        for vote_key, child in zip(vote_keys, children)
    ]
    votes.append(Vote(
        agent_id=facilitator_vote_key,
        approved=True,
        confidence=float(final_confidence),
    ))
    if len(votes) <= MAX_EXACT_SHAPLEY:
        shapley = compute_shapley_values(
            votes,
            approval_threshold=float(approval_threshold),
            use_confidence_weights=use_confidence_weights,
        )
    else:
        shapley = _all_approved_shapley(
            votes,
            use_confidence_weights=use_confidence_weights,
        )

    effects: list[CrewTrustEffect] = []
    for vote_key, child in zip(vote_keys, children):
        final_round = child.rounds[-1]
        final_verifier = final_round["verdict"]["verifier_agent_id"]
        effects.append(CrewTrustEffect.create(
            session_id=session_id,
            session_revision=session_revision,
            evidence_sha256=child.evidence_sha256,
            agent_id=child.producer_agent_id,
            role="child_producer",
            work_item_id=child.work_item_id,
            result_revision=final_round["result_revision"],
            success=True,
            weight=max(float(shapley.get(vote_key, 0.0)), 0.1),
            intent_type="crew_session_child",
            verifier_id=final_verifier,
        ))
        for index, round_record in enumerate(child.rounds):
            verdict = round_record["verdict"]
            correct_judgment = verdict["status"] == "accepted" or (
                verdict["status"] == "refuted" and index + 1 < len(child.rounds)
            )
            if not correct_judgment:
                continue
            effects.append(CrewTrustEffect.create(
                session_id=session_id,
                session_revision=session_revision,
                evidence_sha256=child.evidence_sha256,
                agent_id=verdict["verifier_agent_id"],
                role="child_verifier",
                work_item_id=child.work_item_id,
                result_revision=round_record["result_revision"],
                success=True,
                weight=1.0,
                intent_type="crew_session_child_verification",
                verifier_id=verdict["verifier_agent_id"],
            ))

    effects.extend((
        CrewTrustEffect.create(
            session_id=session_id,
            session_revision=session_revision,
            evidence_sha256=final_evidence_sha256,
            agent_id=facilitator_id,
            role="facilitator",
            work_item_id=session_id,
            result_revision=1,
            success=True,
            weight=max(float(shapley.get(facilitator_vote_key, 0.0)), 0.1),
            intent_type="crew_session_final",
            verifier_id=final_verifier_id,
        ),
        CrewTrustEffect.create(
            session_id=session_id,
            session_revision=session_revision,
            evidence_sha256=final_evidence_sha256,
            agent_id=final_verifier_id,
            role="final_verifier",
            work_item_id=session_id,
            result_revision=1,
            success=True,
            weight=1.0,
            intent_type="crew_session_final_verification",
            verifier_id=final_verifier_id,
        ),
    ))
    if len(effects) > MAX_CREW_TRUST_EFFECTS:
        raise ValueError("crew_trust_effects_overflow")
    return tuple(effects)


def derive_convergence_exhausted_effects(
    *,
    session_id: str,
    session_revision: int,
    child_verifications: tuple[dict[str, Any], ...],
) -> tuple[CrewTrustEffect, ...]:
    if type(child_verifications) is not tuple or len(child_verifications) > _MAX_CHILDREN:
        raise ValueError("crew_trust_evidence_invalid")
    effects: list[CrewTrustEffect] = []
    failed_producers = 0
    seen_work_items: set[str] = set()
    for payload in child_verifications:
        child = _child_evidence(payload)
        if child.parent_id != session_id or child.work_item_id in seen_work_items:
            raise ValueError("crew_trust_evidence_invalid")
        seen_work_items.add(child.work_item_id)
        if child.failure_code not in {None, "convergence_exhausted"}:
            raise ValueError("crew_trust_evidence_invalid")
        if child.failure_code == "convergence_exhausted":
            if child.status != "unverified" or child.accepted:
                raise ValueError("crew_trust_evidence_invalid")
            final_round = child.rounds[-1]
            final_verifier = final_round["verdict"]["verifier_agent_id"]
            effects.append(CrewTrustEffect.create(
                session_id=session_id,
                session_revision=session_revision,
                evidence_sha256=child.evidence_sha256,
                agent_id=child.producer_agent_id,
                role="child_producer",
                work_item_id=child.work_item_id,
                result_revision=final_round["result_revision"],
                success=False,
                weight=1.0,
                intent_type="crew_session_child",
                verifier_id=final_verifier,
            ))
            failed_producers += 1
        for index, round_record in enumerate(child.rounds):
            verdict = round_record["verdict"]
            if verdict["status"] != "refuted" or not (
                index + 1 < len(child.rounds)
                or child.failure_code == "convergence_exhausted"
            ):
                continue
            effects.append(CrewTrustEffect.create(
                session_id=session_id,
                session_revision=session_revision,
                evidence_sha256=child.evidence_sha256,
                agent_id=verdict["verifier_agent_id"],
                role="child_verifier",
                work_item_id=child.work_item_id,
                result_revision=round_record["result_revision"],
                success=True,
                weight=1.0,
                intent_type="crew_session_child_verification",
                verifier_id=verdict["verifier_agent_id"],
            ))
    if failed_producers == 0 or len(effects) > MAX_CREW_TRUST_EFFECTS:
        raise ValueError("crew_trust_evidence_invalid")
    return tuple(effects)


def derive_final_refutation_effects(
    *,
    session_id: str,
    session_revision: int,
    facilitator_id: str,
    final_verifier_id: str,
    final_evidence_sha256: str,
    child_verifications: tuple[dict[str, Any], ...] = (),
) -> tuple[CrewTrustEffect, ...]:
    effects: list[CrewTrustEffect] = []
    seen_work_items: set[str] = set()
    for payload in child_verifications:
        child = _child_evidence(payload)
        if child.parent_id != session_id or child.work_item_id in seen_work_items:
            raise ValueError("crew_trust_evidence_invalid")
        seen_work_items.add(child.work_item_id)
        if not child.accepted or child.status != "converged":
            raise ValueError("crew_trust_evidence_invalid")
        for index, round_record in enumerate(child.rounds):
            verdict = round_record["verdict"]
            if verdict["status"] != "refuted" or index + 1 >= len(child.rounds):
                continue
            effects.append(CrewTrustEffect.create(
                session_id=session_id,
                session_revision=session_revision,
                evidence_sha256=child.evidence_sha256,
                agent_id=verdict["verifier_agent_id"],
                role="child_verifier",
                work_item_id=child.work_item_id,
                result_revision=round_record["result_revision"],
                success=True,
                weight=1.0,
                intent_type="crew_session_child_verification",
                verifier_id=verdict["verifier_agent_id"],
            ))
    effects.extend((
        CrewTrustEffect.create(
            session_id=session_id,
            session_revision=session_revision,
            evidence_sha256=final_evidence_sha256,
            agent_id=facilitator_id,
            role="facilitator",
            work_item_id=session_id,
            result_revision=1,
            success=False,
            weight=1.0,
            intent_type="crew_session_final",
            verifier_id=final_verifier_id,
        ),
        CrewTrustEffect.create(
            session_id=session_id,
            session_revision=session_revision,
            evidence_sha256=final_evidence_sha256,
            agent_id=final_verifier_id,
            role="final_verifier",
            work_item_id=session_id,
            result_revision=1,
            success=True,
            weight=1.0,
            intent_type="crew_session_final_verification",
            verifier_id=final_verifier_id,
        ),
    ))
    if len(effects) > MAX_CREW_TRUST_EFFECTS:
        raise ValueError("crew_trust_effects_overflow")
    return tuple(effects)


class _CrewTrustOutboxPort(Protocol):
    async def list_pending_crew_trust_outcomes(
        self,
        *,
        limit: int,
    ) -> tuple[dict[str, Any], ...]: ...

    async def mark_crew_trust_outcome_delivered(
        self,
        outcome_id: str,
        *,
        session_id: str,
        session_revision: int,
        evidence_sha256: str,
    ) -> bool: ...


class _TrustOutcomePort(Protocol):
    async def record_outcome_once(self, effect: CrewTrustEffect) -> Any: ...


class CrewSessionTrustRecorder:
    def __init__(
        self,
        *,
        outbox: _CrewTrustOutboxPort,
        trust_network: _TrustOutcomePort,
    ) -> None:
        self._outbox = outbox
        self._trust = trust_network

    async def drain_pending(self, *, limit: int = 100) -> int:
        if type(limit) is not int or not 1 <= limit <= MAX_CREW_TRUST_EFFECTS:
            raise ValueError("crew_trust_drain_limit_invalid")
        try:
            rows = await self._outbox.list_pending_crew_trust_outcomes(limit=limit)
        except asyncio.CancelledError:
            raise
        except ValueError:
            raise
        except Exception:
            logger.warning(
                "Crew trust pending-outbox read failed; no terminal state is "
                "rolled back and startup or the next finalization will retry "
                "the bounded drain",
                exc_info=True,
            )
            return 0
        if type(rows) is not tuple or len(rows) > limit:
            raise ValueError("crew_trust_outbox_batch_invalid")
        delivered = 0
        for payload in rows:
            effect = CrewTrustEffect.from_payload(payload)
            try:
                await self._trust.record_outcome_once(effect)
                acknowledged = await self._outbox.mark_crew_trust_outcome_delivered(
                    effect.outcome_id,
                    session_id=effect.session_id,
                    session_revision=effect.session_revision,
                    evidence_sha256=effect.evidence_sha256,
                )
            except asyncio.CancelledError:
                raise
            except ValueError as exc:
                if str(exc) in {
                    "trust_outcome_identity_conflict",
                    "crew_trust_effect_invalid",
                    "crew_trust_outbox_corrupt",
                }:
                    raise
                logger.warning(
                    "Crew trust delivery validation failed outcome=%s session=%s; "
                    "the durable outbox row remains pending and startup or the "
                    "next finalization will retry it",
                    effect.outcome_id,
                    effect.session_id,
                    exc_info=True,
                )
                continue
            except Exception:
                logger.warning(
                    "Crew trust delivery failed outcome=%s session=%s; the durable "
                    "outbox row remains pending and startup or the next finalization "
                    "will retry it",
                    effect.outcome_id,
                    effect.session_id,
                    exc_info=True,
                )
                continue
            if not acknowledged:
                logger.warning(
                    "Crew trust acknowledgement did not match outcome=%s session=%s; "
                    "the row remains pending and a later bounded drain will reconcile it",
                    effect.outcome_id,
                    effect.session_id,
                )
                continue
            delivered += 1
        return delivered