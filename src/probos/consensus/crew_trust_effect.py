"""Durable CrewSession trust-effect contract owned by the consensus layer."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Literal

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


def _exact_json_bytes(value: Any, *, error: str) -> bytes:
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
    if len(encoded) > _MAX_EFFECT_BYTES:
        raise ValueError(error)
    return encoded


def _required_id(value: Any) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ValueError("crew_trust_effect_invalid")
    return value


def _required_sha(value: Any, *, identity: bool = False) -> str:
    if type(value) is not str or _SHA_RE.fullmatch(value) is None:
        error = "trust_outcome_identity_conflict" if identity else "crew_trust_effect_invalid"
        raise ValueError(error)
    return value


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
        _required_sha(self.outcome_id, identity=True)
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
