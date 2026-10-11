"""AD-1286: Elastic Team Contract -- immutable team specs, durable slots, ephemeral attempts.

The business process stays durable while its workforce is elastic (epic #1332).
This module holds only frozen identity contracts; it provisions nothing, ranks
nothing and stores nothing (``elastic_team_store`` persists, AD-1288 provisions).

Identity is content addressed: ``sha256(domain + RFC 8785 bytes)`` over the
``model_dump(mode="json")`` projection. The canonicaliser is AD-1144's
``probos.federation.ard.jcs.canonicalize``, imported lazily so importing this
module never imports the federation package. Identity material holds no floats,
so the ECMAScript number formatting rule never applies. Set-valued fields are
sorted at validation and duplicates are refused, so declaration order never
changes an identity. Optional fields are always emitted (as ``null``): the key
set is fixed per ``schema_version`` and a new field means a new schema version,
never a silent re-hash of v1.

Runtime-only attempt state (``WorkerAttemptOutcome``) is a separate type and is
never part of any digest.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from typing import Annotated, Any, Final, Literal, Protocol, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator

ELASTIC_TEAM_SCHEMA_VERSION: Final = 1
#: The parent-metadata key ``CrewSessionService.bind_team_spec`` writes (see ``CrewElasticTeamBinding``).
CREW_ELASTIC_TEAM_METADATA_KEY: Final = "crew_elastic_team"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_SCOPE_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,127}$")
_MAX_SAFE_INT: Final = 2**53 - 1
_MAX_REVISION: Final = 2_147_483_647
_MAX_SLOTS: Final = 64
_MAX_CAPACITY: Final = 64
_MAX_SET_ITEMS: Final = 32
_MAX_ATTEMPTS_PER_SLOT: Final = 1_024
_MAX_SPEC_BYTES: Final = 262_144
_MAX_TIMESTAMP: Final = 253_402_300_799.0

_DOMAINS: Final[dict[str, bytes]] = {
    "team_spec": b"probos.elastic_team/team_spec/v1\x00",
    "worker_slot": b"probos.elastic_team/worker_slot/v1\x00",
    "worker_attempt": b"probos.elastic_team/worker_attempt/v1\x00",
    "worker_attempt_id": b"probos.elastic_team/worker_attempt_id/v1\x00",
}


def canonicalize_projection(value: object) -> bytes:
    """RFC 8785 bytes of a JSON-shaped value (AD-1144's canonicaliser).

    Imported lazily: importing ``probos.federation.ard.jcs`` runs the federation
    package ``__init__``, which must stay off this module's import path
    (precedent: ``probos.identity_keys.canonical_bytes``).
    """
    from probos.federation.ard.jcs import canonicalize

    return canonicalize(value)


def content_digest(kind: str, value: object) -> str:
    """Domain-separated sha256 hex digest of ``value``'s RFC 8785 bytes."""
    domain = _DOMAINS.get(kind) if type(kind) is str else None
    if domain is None:
        raise ValueError("elastic_team_identity_kind_invalid")
    return hashlib.sha256(domain + canonicalize_projection(value)).hexdigest()


def is_sha256_ref(value: object) -> bool:
    """True when ``value`` is a lowercase 64-hex sha256 reference."""
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _id(value: Any) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ValueError("elastic_team_id_invalid")
    return value


def _sha(value: Any) -> str:
    if not is_sha256_ref(value):
        raise ValueError("elastic_team_ref_invalid")
    return value


def _scope(value: Any) -> str:
    if type(value) is not str or _SCOPE_RE.fullmatch(value) is None:
        raise ValueError("elastic_team_scope_invalid")
    return value


def _code(value: Any) -> str:
    if type(value) is not str or _CODE_RE.fullmatch(value) is None:
        raise ValueError("elastic_attempt_outcome_invalid")
    return value


def _timestamp(value: Any) -> float:
    if type(value) is not float or not math.isfinite(value) or not 0.0 <= value <= _MAX_TIMESTAMP:
        raise ValueError("elastic_attempt_outcome_invalid")
    return value


def _int_range(low: int, high: int, code: str) -> Callable[[Any], int]:
    def check(value: Any) -> int:
        if type(value) is not int or not low <= value <= high:
            raise ValueError(code)
        return value

    return check


def _unique_sorted(item: Callable[[Any], str], code: str) -> Callable[[Any], tuple[str, ...]]:
    def check(value: Any) -> tuple[str, ...]:
        if type(value) not in (list, tuple) or len(value) > _MAX_SET_ITEMS:
            raise ValueError(code)
        items = [item(entry) for entry in value]
        if len(set(items)) != len(items):
            raise ValueError(code)
        return tuple(sorted(items))

    return check


ElasticId = Annotated[str, BeforeValidator(_id)]
Sha256Ref = Annotated[str, BeforeValidator(_sha)]
IdSet = Annotated[tuple[str, ...], BeforeValidator(_unique_sorted(_id, "elastic_team_id_set_invalid"))]
RefSet = Annotated[tuple[str, ...], BeforeValidator(_unique_sorted(_sha, "elastic_team_ref_set_invalid"))]
ScopeSet = Annotated[tuple[str, ...], BeforeValidator(_unique_sorted(_scope, "elastic_team_scope_set_invalid"))]
SchemaVersion = Annotated[Literal[1], BeforeValidator(_int_range(1, 1, "elastic_team_schema_version_invalid"))]
Revision = Annotated[int, BeforeValidator(_int_range(1, _MAX_REVISION, "elastic_team_revision_invalid"))]
CapacityCount = Annotated[int, BeforeValidator(_int_range(1, _MAX_CAPACITY, "elastic_team_capacity_invalid"))]
CapacityFloor = Annotated[int, BeforeValidator(_int_range(0, _MAX_CAPACITY, "elastic_team_capacity_invalid"))]
DistinctCount = Annotated[int, BeforeValidator(_int_range(1, _MAX_CAPACITY, "elastic_team_independence_invalid"))]
Quorum = Annotated[int, BeforeValidator(_int_range(1, _MAX_CAPACITY, "elastic_team_merge_invalid"))]
BudgetAmount = Annotated[int, BeforeValidator(_int_range(1, _MAX_SAFE_INT, "elastic_team_budget_invalid"))]
AttemptBudget = Annotated[int, BeforeValidator(_int_range(1, _MAX_ATTEMPTS_PER_SLOT, "elastic_team_budget_invalid"))]
Ordinal = Annotated[int, BeforeValidator(_int_range(1, _MAX_ATTEMPTS_PER_SLOT, "elastic_attempt_ordinal_invalid"))]
OutcomeCode = Annotated[str, BeforeValidator(_code)]
OutcomeTimestamp = Annotated[float, BeforeValidator(_timestamp)]

IndependenceMode = Literal["none", "distinct_attempts", "distinct_profiles", "distinct_models"]
MergeKind = Literal["single", "all_required", "first_accepted", "reducer", "adjudicator"]
TerminalStatus = Literal["succeeded", "failed", "cancelled"]

_MERGE_REQUIRED_FIELD: Final[dict[str, str]] = {
    "first_accepted": "quorum",
    "reducer": "reducer_id",
    "adjudicator": "adjudicator_slot_id",
}


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class BillRef(_Frozen):
    """An existing AD-618 Bill named by slug and version. The Bill is not changed or resolved here."""

    bill_id: ElasticId
    bill_version: Revision


class ProcessBinding(_Frozen):
    """The durable process a team recipe serves: a Bill, an installed CrewSession plan, or both."""

    bill: BillRef | None
    plan_hash: Sha256Ref | None

    @model_validator(mode="after")
    def _require_process(self) -> Self:
        if self.bill is None and self.plan_hash is None:
            raise ValueError("elastic_team_process_binding_empty")
        return self


class CapacityRange(_Frozen):
    minimum: CapacityFloor
    maximum: CapacityCount

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.minimum > self.maximum:
            raise ValueError("elastic_team_capacity_invalid")
        return self


class QualificationRequirement(_Frozen):
    """Declared constraints only. Evaluation is AD-1287; qualification never grants authority."""

    qualification_ids: IdSet
    pinned_profile_refs: RefSet


class IndependencePolicy(_Frozen):
    mode: IndependenceMode
    min_distinct: DistinctCount

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.mode == "none" and self.min_distinct != 1:
            raise ValueError("elastic_team_independence_invalid")
        return self


class MergeRule(_Frozen):
    """How a slot's attempt outputs combine. Behaviour is AD-1290; this is the typed declaration."""

    kind: MergeKind
    quorum: Quorum | None
    reducer_id: ElasticId | None
    adjudicator_slot_id: ElasticId | None

    @model_validator(mode="after")
    def _fields_match_kind(self) -> Self:
        required = _MERGE_REQUIRED_FIELD.get(self.kind)
        present = {
            name
            for name in ("quorum", "reducer_id", "adjudicator_slot_id")
            if getattr(self, name) is not None
        }
        if present != ({required} if required else set()):
            raise ValueError("elastic_team_merge_invalid")
        return self


class SlotBudget(_Frozen):
    max_tokens: BudgetAmount
    max_wall_ms: BudgetAmount
    max_attempts: AttemptBudget


class AuthorityCeiling(_Frozen):
    """The most authority any attempt in this slot may ever be leased (AD-1288). Grants nothing."""

    tool_scopes: ScopeSet
    data_scopes: ScopeSet


class WorkerSlot(_Frozen):
    """One durable role/task-class/capacity requirement. Never an agent instance."""

    slot_id: ElasticId
    role_id: ElasticId
    task_class: ElasticId
    capacity: CapacityRange
    qualification: QualificationRequirement
    independence: IndependencePolicy
    merge: MergeRule
    budget: SlotBudget
    authority: AuthorityCeiling

    @model_validator(mode="after")
    def _within_capacity(self) -> Self:
        if self.independence.min_distinct > self.capacity.maximum:
            raise ValueError("elastic_team_independence_invalid")
        if self.merge.quorum is not None and self.merge.quorum > self.capacity.maximum:
            raise ValueError("elastic_team_merge_invalid")
        if self.merge.adjudicator_slot_id == self.slot_id:
            raise ValueError("elastic_team_merge_invalid")
        if self.budget.max_attempts < self.capacity.maximum:
            raise ValueError("elastic_team_budget_invalid")
        return self

    def content_ref(self) -> str:
        """Domain-separated digest of this slot's full projection."""
        return content_digest("worker_slot", self.model_dump(mode="json"))


def _slot_sequence(value: Any) -> tuple[Any, ...]:
    if type(value) not in (list, tuple) or not 1 <= len(value) <= _MAX_SLOTS:
        raise ValueError("elastic_team_slots_invalid")
    keyed: list[tuple[str, Any]] = []
    for entry in value:
        if type(entry) is WorkerSlot:
            key: Any = entry.slot_id
        elif type(entry) is dict:
            key = entry.get("slot_id")
        else:
            key = None
        if type(key) is not str:
            raise ValueError("elastic_team_slots_invalid")
        keyed.append((key, entry))
    keys = [key for key, _ in keyed]
    if len(set(keys)) != len(keys):
        raise ValueError("elastic_team_slot_duplicate")
    return tuple(entry for _, entry in sorted(keyed, key=lambda pair: pair[0]))


class ElasticTeamSpec(_Frozen):
    """One frozen, versioned team recipe bound to an existing Bill and/or CrewSession plan.

    Any behaviourally material change -- role, task class, capacity, pinned
    execution profiles (which carry skill/model/prompt/tool/policy, AD-1287),
    independence, merge, budget, authority, process binding -- changes
    ``content_ref()``. ``ElasticTeamStore`` refuses a second digest for one
    ``(team_id, revision)``, so a change requires a new revision.
    """

    schema_version: SchemaVersion
    team_id: ElasticId
    revision: Revision
    process: ProcessBinding
    slots: Annotated[tuple[WorkerSlot, ...], BeforeValidator(_slot_sequence)]

    @model_validator(mode="after")
    def _closed_references(self) -> Self:
        slot_ids = {slot.slot_id for slot in self.slots}
        for slot in self.slots:
            target = slot.merge.adjudicator_slot_id
            if target is not None and target not in slot_ids:
                raise ValueError("elastic_team_merge_invalid")
        if len(self.canonical_bytes()) > _MAX_SPEC_BYTES:
            raise ValueError("elastic_team_spec_too_large")
        return self

    def canonical_bytes(self) -> bytes:
        """RFC 8785 bytes of the full projection (no domain prefix); what the store persists."""
        return canonicalize_projection(self.model_dump(mode="json"))

    def content_ref(self) -> str:
        """The spec's content identity: ``sha256(team_spec domain + canonical_bytes())``."""
        return hashlib.sha256(_DOMAINS["team_spec"] + self.canonical_bytes()).hexdigest()

    def slot(self, slot_id: str) -> WorkerSlot | None:
        """The slot named ``slot_id``, or None."""
        return next((slot for slot in self.slots if slot.slot_id == slot_id), None)


def derive_worker_attempt_id(
    *, team_spec_ref: str, session_id: str, slot_id: str, ordinal: int,
) -> str:
    """The one deterministic id for attempt ``ordinal`` of a slot in a session."""
    projection = [
        _sha(team_spec_ref),
        _id(session_id),
        _id(slot_id),
        _int_range(1, _MAX_ATTEMPTS_PER_SLOT, "elastic_attempt_ordinal_invalid")(ordinal),
    ]
    return "wa-" + content_digest("worker_attempt_id", projection)


class WorkerAttempt(_Frozen):
    """One uniquely identified ephemeral incarnation of a slot, bound to an exact execution profile.

    ``execution_profile_ref`` is a reference only; AD-1287 defines how it is computed.
    """

    schema_version: SchemaVersion
    worker_attempt_id: ElasticId
    team_spec_ref: Sha256Ref
    session_id: ElasticId
    slot_id: ElasticId
    ordinal: Ordinal
    execution_profile_ref: Sha256Ref
    supersedes_attempt_id: ElasticId | None

    @model_validator(mode="after")
    def _derived_identity(self) -> Self:
        expected = derive_worker_attempt_id(
            team_spec_ref=self.team_spec_ref,
            session_id=self.session_id,
            slot_id=self.slot_id,
            ordinal=self.ordinal,
        )
        if self.worker_attempt_id != expected:
            raise ValueError("elastic_attempt_id_mismatch")
        if self.supersedes_attempt_id == self.worker_attempt_id:
            raise ValueError("elastic_attempt_supersedes_invalid")
        return self

    def content_ref(self) -> str:
        """Digest of the identity projection. Runtime outcome is a separate type and never included."""
        return content_digest("worker_attempt", self.model_dump(mode="json"))


class WorkerAttemptOutcome(_Frozen):
    """Runtime-only terminal state of one attempt. Write-once in the store; never hashed."""

    worker_attempt_id: ElasticId
    terminal_status: TerminalStatus
    error_code: OutcomeCode | None
    recorded_at: OutcomeTimestamp

    @model_validator(mode="after")
    def _error_matches_status(self) -> Self:
        if (self.error_code is None) != (self.terminal_status == "succeeded"):
            raise ValueError("elastic_attempt_outcome_invalid")
        return self


class CrewElasticTeamBinding(_Frozen):
    """The one durable CrewSession -> team-spec association (stored under ``crew_elastic_team``).

    Written by ``CrewSessionService.bind_team_spec``, its only production writer, which verifies the spec and
    the session state first. The key is protected by owned steps only once a plan is installed; before that,
    the platform's generic metadata merge can write it like any other ``crew_*`` key (#1419 F-1), which is why
    ``get_team_binding`` verifies what it returns.
    """

    version: SchemaVersion
    team_spec_ref: Sha256Ref
    team_id: ElasticId
    revision: Revision

    @classmethod
    def for_spec(cls, spec: ElasticTeamSpec) -> CrewElasticTeamBinding:
        """The binding that names exactly ``spec``."""
        return cls(
            version=1,
            team_spec_ref=spec.content_ref(),
            team_id=spec.team_id,
            revision=spec.revision,
        )


class TeamSpecLookup(Protocol):
    """Narrow read port ``CrewSessionService`` depends on (ISP); ``ElasticTeamStore`` satisfies it."""

    async def get_team_spec(self, team_spec_ref: str) -> ElasticTeamSpec | None: ...
