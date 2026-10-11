# AD-1286: Elastic Team Contract — immutable team specs, durable slots, ephemeral attempts

**One line:** add frozen, content-addressed `ElasticTeamSpec` / `WorkerSlot` / `WorkerAttempt` contracts, an insert-only `ElasticTeamStore`, and one write-once CrewSession binding (`crew_elastic_team`), all inert until AD-1288 calls them.

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-10
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-10 — R1: REPLACE guard triggers (12 total), store/session-membership boundary documented, worktree import-root step 0; R2: census-pin edits (§5c), one documented layer exception (§5d), Builder deviations ruled, frozen-vs-census pin distinction; R3: review round 1 repairs (§8: WITHOUT ROWID, instance revalidation, rollback poisoning, verified admission, bind-time-only plan check, planned-session concurrency, verify-on-read, corruption propagates), false absence/exclusivity claims corrected; R4: review round 2 repairs (§9: one connection per operation, verified reads on a closed path list, binding docstring, rowid test isolation, termination criterion), planned-parent PATCH 500 corrected
**Issue:** #1333 (parent epic #1332). Decisions D1–D5 recorded on #1333 (comment 6103852189).
**Status:** Ready for Builder (one build; slice A/B cut is a hard-stop fallback only, see §"Hard stops").
**Dependencies:** none unbuilt. Builds on AD-618 (Bill schema, read-only reference), AD-1124/1127 (CrewSession), AD-542 (`ConnectionFactory`), AD-1144 (RFC 8785 `canonicalize`), AD-1256 (store registry), AD-1270b (architecture checker).
**Dependents (do not preempt):** AD-1287 #1334 (computes execution-profile digests), AD-1288 #1335 (lifecycle/provisioning/leases), AD-1289 #1336 (blackboard), AD-1290 #1337 (scatter/gather, reducers, trials).
**Estimated tests:** ~95 new (contract ~45, store ~25, binding ~18, wiring ~7) plus focused re-runs of the consumer files listed per section.
**AD number:** AD-1286 is already allocated (#1333). Do **not** allocate a number. Ceiling check run 2026-10-10: `scripts/ad_ceiling.py` → CEILING AD-1325 (git log subjects, GitHub issue titles), exit 0.

---

## Problem

Crew fan-out assigns work directly to standing agent IDs. Nothing durable distinguishes a *role/capacity requirement* from the *ephemeral worker incarnation* that attempts it, so retries, replicas, model diversity and teardown (AD-1288–1290) cannot be represented without overloading agent identity or inventing a parallel workflow engine.

Verified facts this design rests on (evidence in §"Verified Against Codebase"):

- `ElasticTeamSpec`, `WorkerSlot`, `WorkerAttempt` exist nowhere in the repo.
- `BillDefinition` (`src/probos/sop/schema.py:86`) is a mutable dataclass keyed by slug `bill` + `version: int`; it has no hash and no persistence. No crew module references Bills.
- A CrewSession is a `work_items` row with `work_type="crew_session"`; its durable state is top-level parent metadata keys `crew_session` (`CrewSessionContract`, `crew_session.py:1817`), `crew_recovery` (`CrewRecoveryContract`, `:490`), plus existing siblings `crew_provisioning` (`:3797`) and `crew_synth`. Generic writers are refused (`crew_session_write_reserved`, `workforce.py:7626` etc.); `CrewSessionService._merge_owned_metadata` (`crew_session.py:3225`) is the one write path.
- `owned_metadata_key()` (`work_item_steps.py:266`) protects every `crew_*` key under owned steps — **R3: only once a plan is installed** (`steps_control` present). Before that, the in-process `merge_work_item_metadata` primitive accepts any `crew_*` key on an unplanned crew-session parent, `crew_session` itself included (see §8 F3).
- Child metadata keys are hashed into `row_hash` (`workforce.py:5891-5894`), so **child metadata must never be written by this AD**.
- `CrewSessionContract` is pinned at exactly 27 keys (`tests/test_ad1124_crew_session_contract.py:576`); the 14-key `CREW_EXECUTION_KEYS` (`crew_utils.py:38`) and 12-field `SubtaskResult` (`crew_executor.py:1096`) are pinned by many tests and a golden fixture.

## Solution (overview)

| Piece | Where | Owner of |
|---|---|---|
| Frozen contracts + canonical identity | NEW `src/probos/cognitive/elastic_team.py` | `ElasticTeamSpec`, `WorkerSlot` (+ typed policy objects), `WorkerAttempt`, `WorkerAttemptOutcome`, `CrewElasticTeamBinding`, `TeamSpecLookup` protocol, digest helpers |
| Insert-only persistence | NEW `src/probos/cognitive/elastic_team_store.py` | `elastic_teams.db`: specs, slots, attempts, outcomes; twelve SQLite triggers abort every UPDATE, every DELETE and every INSERT that would replace an existing row |
| The one durable association | `CrewSessionService` (`crew_session.py`) | parent-row metadata key `crew_elastic_team`, write-once, `discussing` only |
| Wiring (default-off) | `startup/finalize.py`, `runtime.py`, `startup/shutdown.py` | store opened only inside the existing `orchestrator_enabled` crew-session path |

Identity: `sha256(domain_prefix + rfc8785(model_dump(mode="json")))`, domain prefix `b"probos.elastic_team/<kind>/v1\x00"`. No floats anywhere in identity material. Set-valued fields are sorted at validation and duplicates rejected. Runtime-only attempt state lives in a separate type and is never hashed.

Layering: `elastic_team.py` imports only stdlib + pydantic (+ a lazy `probos.federation.ard.jcs` import inside one helper). `elastic_team_store.py` imports `elastic_team` and `probos.protocols`. `crew_session.py` imports `elastic_team` lazily (inside methods) and under `TYPE_CHECKING` only. `elastic_team*.py` must never import `crew_session`, `crew_executor`, `crew_orchestrator` or `workforce`.

---

## Section 0: Event types

**None.** This AD adds no `EventType` member and emits no event. Do not touch `src/probos/events.py`.

---

## Section 1: Contracts and canonical identity — NEW `src/probos/cognitive/elastic_team.py`

Create the file with exactly this content. You may fix pure pydantic *mechanics* if a test proves one of them fails (e.g. a validator ordering detail), but you may **not** change any field name, field type, error code, domain prefix, the set of fields in any model, the sort/dedupe rules, or what bytes are hashed — any such change is a hard stop (send it back to the Architect).

```python3
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
#: The single parent-metadata key owned by ``CrewSessionService.bind_team_spec``.
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
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


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

    Owned and written only by ``CrewSessionService.bind_team_spec``.
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
```

**Done when:** `tests/test_ad1286_elastic_team_contract.py` (below) passes.

### Tests — `tests/test_ad1286_elastic_team_contract.py` (NEW)

Build a module-level `_KAT_SPEC` dict and helpers `_spec(**overrides)` / `_slot(**overrides)` that deep-copy and patch it. Use **neutral** names (no domain/commercial wording). The KAT fixture, exactly:

```python
_PROFILE_A = "a" * 64
_KAT_SPEC: dict[str, Any] = {
    "schema_version": 1,
    "team_id": "review-team",
    "revision": 1,
    "process": {"bill": {"bill_id": "incident-review", "bill_version": 3}, "plan_hash": None},
    "slots": [
        {
            "slot_id": "analyse",
            "role_id": "analyst",
            "task_class": "evidence_analysis",
            "capacity": {"minimum": 1, "maximum": 3},
            "qualification": {"qualification_ids": ["evidence_analysis"], "pinned_profile_refs": [_PROFILE_A]},
            "independence": {"mode": "distinct_profiles", "min_distinct": 2},
            "merge": {"kind": "adjudicator", "quorum": None, "reducer_id": None, "adjudicator_slot_id": "review"},
            "budget": {"max_tokens": 200000, "max_wall_ms": 900000, "max_attempts": 6},
            "authority": {"tool_scopes": ["records.read"], "data_scopes": ["incident.records"]},
        },
        {
            "slot_id": "review",
            "role_id": "reviewer",
            "task_class": "finding_review",
            "capacity": {"minimum": 1, "maximum": 1},
            "qualification": {"qualification_ids": ["finding_review"], "pinned_profile_refs": []},
            "independence": {"mode": "none", "min_distinct": 1},
            "merge": {"kind": "single", "quorum": None, "reducer_id": None, "adjudicator_slot_id": None},
            "budget": {"max_tokens": 100000, "max_wall_ms": 600000, "max_attempts": 2},
            "authority": {"tool_scopes": [], "data_scopes": ["incident.records"]},
        },
    ],
}
```

Named tests (each one behaviour, Arrange-Act-Assert):

1. `test_spec_happy_path_has_64_hex_content_ref` — valid spec; `content_ref()` matches `^[0-9a-f]{64}$`; every slot `content_ref()` likewise.
2. `test_spec_rejects_malformed_values` — `@pytest.mark.parametrize` over (patch, expected code) and assert `pytest.raises(ValidationError, match=code)`. Cover at least: empty `team_id` (`elastic_team_id_invalid`); `team_id` with a space; `revision` 0, `True`, `1.0` (`elastic_team_revision_invalid`); `schema_version` 2 and `True`; `slots` empty list (`elastic_team_slots_invalid`); duplicate `slot_id` (`elastic_team_slot_duplicate`); capacity minimum 2 > maximum 1, maximum 0, maximum 65, maximum `True` (`elastic_team_capacity_invalid`); pinned profile ref uppercase hex, 63 chars, non-str (**R2: item code** `elastic_team_ref_invalid` — `_unique_sorted` validates each element first, so a malformed element raises the item code; the `*_set_invalid` codes are only for container faults: not a list/tuple, more than 32 items, or duplicates — cover each container fault too); duplicate qualification id (`elastic_team_id_set_invalid`); independence mode `"random"`; `min_distinct` 4 > capacity 3 and mode `"none"` with `min_distinct` 2 (`elastic_team_independence_invalid`); merge kind `"vote"`; `first_accepted` without quorum; `single` with quorum 1; `reducer` without `reducer_id`; adjudicator naming an unknown slot; adjudicator naming itself; quorum 4 > capacity 3 (`elastic_team_merge_invalid`); `max_tokens` 0, `max_wall_ms` 1.5, `max_attempts` 2 < capacity 3 (`elastic_team_budget_invalid`); tool scope `"Tool Read"` (**R2: item code** `elastic_team_scope_invalid`; a duplicated scope or a non-list is `elastic_team_scope_set_invalid`); process with both `bill` and `plan_hash` null (`elastic_team_process_binding_empty`); `plan_hash` `"x"`; an extra top-level key and an extra nested key (pydantic `extra_forbidden`); a missing optional key (e.g. drop `merge.reducer_id`) is refused (`Field required`).
3. `test_set_order_and_slot_order_do_not_change_identity` — reverse `slots`, reverse a two-item `tool_scopes`, reverse a two-item `qualification_ids`: same `content_ref()` and same `canonical_bytes()`; and the normalised `slots[i].slot_id` order is ascending.
4. `test_canonical_round_trip_preserves_every_field` — `again` is `ElasticTeamSpec.model_validate(json.loads(spec.canonical_bytes()))`; `again == spec`; `again.canonical_bytes() == spec.canonical_bytes()`; `set(json.loads(spec.canonical_bytes()))` equals the set of names in `ElasticTeamSpec.model_fields`, and the same key-set check for each nested model's dump.
5. `test_material_change_changes_identity` — parametrize ≥ 13 single-field changes (role_id, task_class, capacity.maximum, add a qualification id, change pinned profile ref, independence.mode, merge kind → `all_required` with adjudicator cleared, budget.max_tokens, add a tool scope, add a data scope, bill_version, set plan_hash, revision); each yields a different spec `content_ref()`; slot-level ones also change that slot's `content_ref()`.
6. `test_attempt_identity_excludes_runtime_state` — build `WorkerAttempt` (derived id) and two `WorkerAttemptOutcome`s (succeeded / failed with code); attempt `content_ref()` is identical before and after constructing outcomes, and `set(attempt.model_dump(mode="json")) == {"schema_version", "worker_attempt_id", "team_spec_ref", "session_id", "slot_id", "ordinal", "execution_profile_ref", "supersedes_attempt_id"}` (no status, timestamp, agent or lease field).
7. `test_attempt_id_is_derived_and_refuses_mismatch` — `derive_worker_attempt_id` deterministic and `"wa-"` + 64 hex; changing any of the four inputs changes it; an attempt whose `worker_attempt_id` is not the derived value → `elastic_attempt_id_mismatch`; `supersedes_attempt_id == worker_attempt_id` → `elastic_attempt_supersedes_invalid`; ordinal 0 / 1025 → `elastic_attempt_ordinal_invalid`.
8. `test_outcome_boundaries` — succeeded with an error code, failed without one, `recorded_at` int / NaN / negative → `elastic_attempt_outcome_invalid`.
9. `test_binding_for_spec_names_exact_spec` — `CrewElasticTeamBinding.for_spec(spec)` carries `spec.content_ref()`, `team_id`, `revision`; malformed binding dicts (bad ref, `version` 2, extra key) refused.
10. `test_known_answer_vectors_match_an_independent_rfc8785_encoding` — **known-answer vectors.** Write a test-local independent encoder `_independent_jcs(value) -> bytes` for the fixture domain (None/bool/int/ASCII str/list/dict; dict members sorted by `key.encode("utf-16-be")`; strings via `json.dumps(s, ensure_ascii=False)`; raise `TypeError` on float or any other type) and `_independent_digest(domain: bytes, value) -> str` using `hashlib.sha256`. Write the domain prefixes as **literals in the test** (do not import `_DOMAINS`). Paste three golden hex literals `_KAT_SPEC_REF`, `_KAT_SLOT_REF` (slot `"analyse"`), `_KAT_ATTEMPT_REF` (attempt: `team_spec_ref=_KAT_SPEC_REF`, `session_id="session-parent"`, `slot_id="analyse"`, `ordinal=1`, `execution_profile_ref=_PROFILE_A`, `supersedes_attempt_id=None`, id derived) **plus** `_KAT_ATTEMPT_ID`. Compute each literal **once, in a scratch Python run that uses only `_independent_jcs`/`hashlib`, never the module under test**, and paste it. The test asserts: independent digest == literal, and module `content_ref()` / `derive_worker_attempt_id` == literal. Also assert `spec.canonical_bytes() == _independent_jcs(_KAT_SPEC)`.
11. `test_identity_is_stable_across_processes` — run `[sys.executable, "-c", script, json.dumps(_KAT_SPEC)]` twice with `env={**os.environ, "PYTHONHASHSEED": seed, "PROBOS_DATA_DIR": str(tmp_path)}` for seeds `"0"` and `"4242"` (`check=True`, `timeout=120`); each stdout equals `_KAT_SPEC_REF`. The script validates the JSON with `ElasticTeamSpec.model_validate` and prints `content_ref()`.
12. `test_module_imports_no_crew_or_workforce_and_no_federation_at_import` — (a) AST-parse `src/probos/cognitive/elastic_team.py` and `elastic_team_store.py` and assert no module-scope import of `probos.cognitive.crew_session`, `crew_executor`, `crew_orchestrator`, `probos.workforce` (and no `probos.federation` import at module scope in either); (b) subprocess: `import probos.cognitive.elastic_team, sys; print("probos.federation" in sys.modules)` prints `False`.

Focused command (Section 1):

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1286_elastic_team_contract.py -q -n 0 -p no:randomly
```

---

## Section 2: Insert-only store — NEW `src/probos/cognitive/elastic_team_store.py` + store declaration

### 2a. Store lifecycle decision (amendment 2)

**Persistent connection with `start()`/`stop()`**, registered in the shutdown sidecar list. Every `ConnectionFactory` sibling does this: `standing_interest_store.py:152-185` (the closest sibling: same package, same ConnectionFactory + lazy `default_factory` pattern), `approval_authority.py:159/176`, `clearance_grants.py:62/73`, `decision_pre_clearance.py:346/363`, `continue_extension_permits.py:467/486`, `capability_request.py:681/693`. Per the Async Discipline standing order a class with `async def start()` must have `async def stop()`; the one connection is serialised by an `asyncio.Lock` exactly as `standing_interest_store.py:145`. `PRAGMA foreign_keys=ON` is per-connection, so a persistent connection sets it once at `start()`.

### 2b. File content

Create with this structure (code is normative where shown; you write the obvious remaining bodies to the stated rules):

```python
"""AD-1286: ElasticTeamStore -- insert-only persistence for team specs, slots, attempts and outcomes.

Immutability is enforced by the database, not only by this class: twelve triggers
abort, on all four tables, every UPDATE, every DELETE and every INSERT that would
replace an existing row (REPLACE / INSERT OR REPLACE), including a replace through
a secondary unique key. REPLACE deletes the conflicting row without firing DELETE
triggers unless ``recursive_triggers`` is ON (default OFF), so the BEFORE INSERT
guards are what close it; nothing relies on that pragma. This class itself only
issues plain INSERTs after explicit read-then-insert checks under its lock, never
INSERT OR REPLACE, INSERT OR IGNORE or ON CONFLICT. A spec is stored as its RFC 8785
canonical bytes and re-verified against its content identity on every read.
An attempt is admitted only for a declared slot of a stored spec, in contiguous
ordinal order, within the slot's ``budget.max_attempts``, against a pinned
execution profile when the slot pins any, and -- when it replaces another
attempt -- only for a predecessor with a recorded failed/cancelled outcome that
no other attempt has already replaced. The store does not validate session
membership: it cannot know that ``session_id`` names a CrewSession that bound
``team_spec_ref`` (that fact lives in the work-item store, with no cross-store
transaction). AD-1288's commission admission must check
``CrewSessionService.get_team_binding(session_id)`` against the spec before it
records an attempt. Nothing here provisions, ranks or schedules (AD-1288/AD-1290).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import Callable
from typing import Any

from probos.cognitive.elastic_team import (
    ElasticTeamSpec,
    WorkerAttempt,
    WorkerAttemptOutcome,
    canonicalize_projection,
    is_sha256_ref,
)
from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS elastic_team_specs (
    spec_ref TEXT PRIMARY KEY CHECK (length(spec_ref) = 64),
    team_id TEXT NOT NULL CHECK (length(team_id) BETWEEN 1 AND 128),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    canonical_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (team_id, revision)
);
CREATE TABLE IF NOT EXISTS elastic_worker_slots (
    spec_ref TEXT NOT NULL REFERENCES elastic_team_specs (spec_ref),
    slot_id TEXT NOT NULL CHECK (length(slot_id) BETWEEN 1 AND 128),
    slot_digest TEXT NOT NULL CHECK (length(slot_digest) = 64),
    max_attempts INTEGER NOT NULL CHECK (max_attempts BETWEEN 1 AND 1024),
    pinned_profile_refs TEXT NOT NULL,
    PRIMARY KEY (spec_ref, slot_id)
);
CREATE TABLE IF NOT EXISTS elastic_worker_attempts (
    worker_attempt_id TEXT PRIMARY KEY CHECK (length(worker_attempt_id) = 67),
    spec_ref TEXT NOT NULL,
    session_id TEXT NOT NULL CHECK (length(session_id) BETWEEN 1 AND 128),
    slot_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 1 AND 1024),
    execution_profile_ref TEXT NOT NULL CHECK (length(execution_profile_ref) = 64),
    supersedes_attempt_id TEXT REFERENCES elastic_worker_attempts (worker_attempt_id),
    attempt_digest TEXT NOT NULL CHECK (length(attempt_digest) = 64),
    created_at REAL NOT NULL,
    FOREIGN KEY (spec_ref, slot_id) REFERENCES elastic_worker_slots (spec_ref, slot_id),
    UNIQUE (session_id, spec_ref, slot_id, ordinal)
);
CREATE UNIQUE INDEX IF NOT EXISTS elastic_worker_attempts_one_successor
    ON elastic_worker_attempts (supersedes_attempt_id) WHERE supersedes_attempt_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS elastic_attempt_outcomes (
    worker_attempt_id TEXT PRIMARY KEY REFERENCES elastic_worker_attempts (worker_attempt_id),
    terminal_status TEXT NOT NULL CHECK (terminal_status IN ('succeeded', 'failed', 'cancelled')),
    error_code TEXT,
    recorded_at REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS elastic_team_specs_no_update BEFORE UPDATE ON elastic_team_specs
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_team_specs_no_delete BEFORE DELETE ON elastic_team_specs
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_worker_slots_no_update BEFORE UPDATE ON elastic_worker_slots
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_worker_slots_no_delete BEFORE DELETE ON elastic_worker_slots
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_worker_attempts_no_update BEFORE UPDATE ON elastic_worker_attempts
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_worker_attempts_no_delete BEFORE DELETE ON elastic_worker_attempts
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_attempt_outcomes_no_update BEFORE UPDATE ON elastic_attempt_outcomes
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_attempt_outcomes_no_delete BEFORE DELETE ON elastic_attempt_outcomes
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_team_specs_no_replace BEFORE INSERT ON elastic_team_specs
WHEN EXISTS (SELECT 1 FROM elastic_team_specs WHERE spec_ref = NEW.spec_ref
             OR (team_id = NEW.team_id AND revision = NEW.revision))
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_worker_slots_no_replace BEFORE INSERT ON elastic_worker_slots
WHEN EXISTS (SELECT 1 FROM elastic_worker_slots WHERE spec_ref = NEW.spec_ref AND slot_id = NEW.slot_id)
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_worker_attempts_no_replace BEFORE INSERT ON elastic_worker_attempts
WHEN EXISTS (SELECT 1 FROM elastic_worker_attempts WHERE worker_attempt_id = NEW.worker_attempt_id
             OR (session_id = NEW.session_id AND spec_ref = NEW.spec_ref AND slot_id = NEW.slot_id
                 AND ordinal = NEW.ordinal)
             OR (NEW.supersedes_attempt_id IS NOT NULL AND supersedes_attempt_id = NEW.supersedes_attempt_id))
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
CREATE TRIGGER IF NOT EXISTS elastic_attempt_outcomes_no_replace BEFORE INSERT ON elastic_attempt_outcomes
WHEN EXISTS (SELECT 1 FROM elastic_attempt_outcomes WHERE worker_attempt_id = NEW.worker_attempt_id)
BEGIN SELECT RAISE(ABORT, 'elastic_team_immutable'); END;
"""


class ElasticTeamStoreUnavailable(RuntimeError):
    """The store has not been started, or has stopped."""


class ElasticTeamConflict(ValueError):
    """A write that would contradict an immutable record. ``str(exc)`` is the stable code."""


class ElasticTeamIntegrityError(ValueError):
    """A stored row no longer matches its content identity (data integrity: propagate)."""
```

Module-level helpers (not methods, to keep the class small): `_checked_now(clock) -> float` (finite float else `ElasticTeamStoreUnavailable("elastic_team_clock_invalid")`), `async _rollback_quietly(db)` (execute `"ROLLBACK"`, swallow at `logger.debug` with a context message — same shape as `standing_interest_store.py:99-107`; a private helper there may not be imported across modules), `_attempt_from_row(row) -> WorkerAttempt` and `_outcome_from_row(row) -> WorkerAttemptOutcome`.

`class ElasticTeamStore` — **at most 12 direct methods** (R3: raised to ≤ 15 methods / < 500 body lines, expected 13 — see §8 "Method budget") (the architecture checker counts every `def`/`async def` in the class body, see §Section 7):

| Method | Rule |
|---|---|
| `__init__(self, db_path: str, connection_factory: ConnectionFactory \| None = None, clock: Callable[[], float] = time.time) -> None` | Empty/non-str path → `ValueError("elastic_team_store_path_invalid")`. Default factory imported lazily: `from probos.storage.sqlite_factory import default_factory` (precedent `standing_interest_store.py:146-150`). Creates `asyncio.Lock()`. Opens nothing. |
| `async start(self) -> None` | Idempotent. Connect via the factory; execute `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, `PRAGMA synchronous=NORMAL`, `PRAGMA foreign_keys=ON`; `executescript(_SCHEMA)`; `commit()`. On any `BaseException` close the connection and re-raise (precedent `standing_interest_store.py:157-172`). Then `logger.info("AD-1286: ElasticTeamStore started (db=%s); specs, slots and attempts are insert-only", ...)`. |
| `async stop(self) -> None` | Idempotent; swap `self._db` to None first, then close. |
| `_require(self) -> Any` | `self._db` or raise `ElasticTeamStoreUnavailable("elastic_team_store_unavailable")`. |
| `async put_team_spec(self, spec: ElasticTeamSpec) -> str` | `type(spec) is not ElasticTeamSpec` → `TypeError("elastic_team_spec_type_invalid")`. Under the lock: `BEGIN IMMEDIATE`; select rows where `spec_ref = ? OR (team_id = ? AND revision = ?)`; any row whose `spec_ref` differs → `ElasticTeamConflict("elastic_team_revision_conflict")`; if absent insert the spec (`canonical_json = spec.canonical_bytes().decode("utf-8")`, `created_at = _checked_now`) and one `elastic_worker_slots` row per slot (`slot.content_ref()`, `slot.budget.max_attempts`, `canonicalize_projection(list(slot.qualification.pinned_profile_refs)).decode("utf-8")`); `commit()`. On error `_rollback_quietly` + re-raise. Idempotent: same spec twice returns the same ref and writes nothing new. Log info only when a new spec was inserted. |
| `async get_team_spec(self, team_spec_ref: str) -> ElasticTeamSpec \| None` | `not is_sha256_ref` → `ValueError("elastic_team_spec_ref_invalid")`. Missing → None. Parse `json.loads` → `ElasticTeamSpec.model_validate`; a `ValueError` (incl. `ValidationError`) there, a `content_ref()` ≠ requested ref, or `canonical_bytes().decode() != stored text` → `logger.error(...)` with the ref and "refusing to return it", then raise `ElasticTeamIntegrityError("elastic_team_spec_integrity")`. Satisfies `TeamSpecLookup`. |
| `async record_attempt(self, attempt: WorkerAttempt) -> WorkerAttempt` | `type` check → `TypeError("elastic_attempt_type_invalid")`. Under the lock, `BEGIN IMMEDIATE`, then `_admit_attempt`, insert, `commit()`; rollback-and-reraise on error. Idempotent: an existing row with the same id and the same `attempt_digest` returns the attempt (commit, no write); same id, different digest → `ElasticTeamConflict("elastic_attempt_conflict")`. |
| `async _admit_attempt(self, db: Any, attempt: WorkerAttempt) -> None` | In order: slot row for `(team_spec_ref, slot_id)` missing → `ElasticTeamConflict("elastic_attempt_slot_unknown")`; `ordinal > max_attempts` → `"elastic_attempt_budget_exhausted"`; `ordinal != COUNT(*)+1` over `(session_id, spec_ref, slot_id)` → `"elastic_attempt_ordinal_invalid"`; pinned list non-empty and profile not in it → `"elastic_attempt_profile_not_pinned"`; if `supersedes_attempt_id` set: predecessor must exist with the same `(session_id, spec_ref, slot_id)`, a smaller ordinal, and an outcome row whose status is `failed` or `cancelled`, else `"elastic_attempt_supersedes_invalid"`; a row already superseding that predecessor → `"elastic_attempt_already_replaced"`. |
| `async get_attempt(self, worker_attempt_id: str) -> WorkerAttempt \| None` | Rebuild with `_attempt_from_row`; rebuilt `content_ref()` ≠ stored `attempt_digest` → log error + `ElasticTeamIntegrityError("elastic_attempt_integrity")`. |
| `async list_slot_attempts(self, *, session_id: str, team_spec_ref: str, slot_id: str) -> tuple[WorkerAttempt, ...]` | Ordered by ordinal, `LIMIT 1024`; same integrity check per row. Invalid args → `ValueError("elastic_attempt_query_invalid")`. |
| `async record_attempt_outcome(self, outcome: WorkerAttemptOutcome) -> WorkerAttemptOutcome` | Attempt must exist → else `ElasticTeamConflict("elastic_attempt_unknown")`. Existing outcome with the same `(terminal_status, error_code)` → return the **stored** outcome (idempotent; `recorded_at` of the first write wins); different → `ElasticTeamConflict("elastic_attempt_outcome_conflict")`. |
| `async get_attempt_outcome(self, worker_attempt_id: str) -> WorkerAttemptOutcome \| None` | Plain read. |

**Write discipline (R1).** `put_team_spec`, `record_attempt` and `record_attempt_outcome` each do their explicit read under the lock inside `BEGIN IMMEDIATE` first, and then issue **plain `INSERT` only**, and only for rows the read proved absent. Never use `INSERT OR REPLACE`, `REPLACE INTO`, `INSERT OR IGNORE` or `ON CONFLICT`: an idempotent duplicate is detected by the read, not by a conflict clause (the `*_no_replace` guard triggers would turn any conflict clause into an `elastic_team_immutable` abort). The idempotent branches (same spec, same attempt, same outcome) **write nothing** — they commit the empty transaction and return. In the normal flow no guard trigger can fire: `put_team_spec` inserts slots only together with their brand-new spec; `record_attempt` has already refused an existing id, an occupied ordinal (`ordinal != COUNT(*)+1`) and an already-replaced predecessor before inserting; `record_attempt_outcome` has already returned or refused an existing outcome.

Rows: index result rows **positionally** (`row[0]`), never by name — `DatabaseConnection` (`protocols.py:325`) does not promise a row factory. Use `await db.execute(...)` then `await cursor.fetchone()/fetchall()` (sibling pattern). Every public method has full type annotations. Logging messages state what, why, what next.

### 2c. Store declaration (AD-1256 registry) — MODIFY `src/probos/cognitive/storage_declarations.py`

`scripts/check_store_registry.py` fails any module holding a detected `CREATE TABLE` that no declaration names (`undeclared-store`, rule 9, `check_store_registry.py:50-51`). Add one declaration. SEARCH:

```python
        notes=(
            "Constructed only when proactive_cognitive.enabled, standing_interests_enabled, a "
            "Ward Room and a tool registry exist. Pending notices and edge/debounce state are in "
            "memory; resume() re-queues work-item notices after a restart."
        ),
    ),
)
```

REPLACE:

```python
        notes=(
            "Constructed only when proactive_cognitive.enabled, standing_interests_enabled, a "
            "Ward Room and a tool registry exist. Pending notices and edge/debounce state are in "
            "memory; resume() re-queues work-item notices after a restart."
        ),
    ),
    StoreDeclaration(
        id="cognitive.elastic-teams",
        title="Elastic team specs, slots and worker attempts (AD-1286)",
        owner_module="probos.cognitive.elastic_team_store",
        owner_symbol="ElasticTeamStore",
        canonical_path="elastic_teams.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.cognitive.elastic_team_store.ElasticTeamStore",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "Insert-only by design: team specs, slots, attempts and outcomes are provenance, and "
            "twelve triggers abort every UPDATE, every DELETE and every INSERT that would replace "
            "an existing row (REPLACE / INSERT OR REPLACE, including through a secondary unique "
            "key), so the module has no delete path. Growth is "
            "bounded per session by each slot's budget.max_attempts (at most 1,024) and by the "
            "number of spec revisions authored. Retention and teardown policy belongs to the "
            "AD-1288/AD-1290 lifecycle, which may add an archival path; this AD adds none."
        ),
        notes=(
            "Constructed only when agentic_dispatch.orchestrator_enabled wires CrewSessionService "
            "(startup/finalize.py). Inert until AD-1288 commissions attempts; a default runtime "
            "never creates the file."
        ),
    ),
)
```

### Tests — `tests/test_ad1286_elastic_team_store.py` (NEW, real SQLite under `tmp_path` only)

Fixture: `ElasticTeamStore(db_path=str(tmp_path / "elastic_teams.db"), connection_factory=SQLiteConnectionFactory(), clock=_Clock(1000.0))`, started, stopped in `finally`. Reuse the KAT spec builder from the contract test by importing it (`from tests.test_ad1286_elastic_team_contract import _spec, _PROFILE_A`).

1. `test_operations_before_start_raise_unavailable` and `test_stop_is_idempotent`.
2. `test_put_team_spec_is_idempotent_and_survives_reopen` — put twice → same ref; stop; new store on the same path; `get_team_spec(ref) == spec`.
3. `test_same_revision_with_different_content_conflicts` → `elastic_team_revision_conflict`; the first spec is unchanged on read.
4. `test_get_team_spec_rejects_bad_ref_and_returns_none_when_absent`.
5. `test_tampered_spec_row_is_refused` — with a raw `sqlite3` connection: `DROP TRIGGER elastic_team_specs_no_update`, `UPDATE ... SET canonical_json = <same JSON with one budget changed>`; `get_team_spec` raises `ElasticTeamIntegrityError("elastic_team_spec_integrity")`.
6. `test_triggers_refuse_every_mutation_and_replacement_on_every_table` (R1) — populate through the store (one spec; attempt 1 with a `failed` outcome; attempt 2 superseding attempt 1; an outcome for attempt 2), then `stop()` the store and open a **raw `sqlite3` connection with default pragmas** (no `recursive_triggers`, no `foreign_keys`). Parametrize over (table, statement):
   - every table × `UPDATE` (one column of an existing row);
   - every table × `DELETE` of an existing row;
   - every table × `INSERT OR REPLACE` reusing an existing primary key (specs `spec_ref`; slots `(spec_ref, slot_id)`; attempts `worker_attempt_id`; outcomes `worker_attempt_id`);
   - `REPLACE INTO elastic_team_specs` with a new `spec_ref` but an existing `(team_id, revision)`;
   - `REPLACE INTO elastic_worker_attempts` with a new id but an existing `(session_id, spec_ref, slot_id, ordinal)`;
   - `REPLACE INTO elastic_worker_attempts` with a new id and ordinal but attempt 2's `supersedes_attempt_id`;
   - every table × `INSERT ... ON CONFLICT DO UPDATE` on its primary key.
   Each statement raises `sqlite3.DatabaseError` matching `elastic_team_immutable`, and a `SELECT * ... ORDER BY` snapshot of the table is identical before and after. **Negative control** on the same raw connection: inserting a genuinely new row succeeds — a new spec (new `spec_ref`, new `(team_id, revision)`) plus its slot, a new attempt at the next free ordinal that supersedes an attempt with a `failed`/`cancelled` outcome nobody has replaced, and a new outcome — proving the guards are not a blanket refusal. (Test 5, which tampers by dropping a trigger, stays as is.)
7. `test_slot_survives_failed_and_replaced_attempts` — **acceptance bullet 5.** Ordinal 1 (profile A) → outcome failed; ordinal 2 supersedes 1 → outcome cancelled; ordinal 3 supersedes 2. `list_slot_attempts` returns three attempts in ordinal order with three distinct ids and digests; each keeps its own outcome; `get_team_spec` still equals the original spec.
8. `test_attempts_cannot_overwrite_one_another` — same derived id with a different profile → `elastic_attempt_conflict`; identical re-record → idempotent; stored row unchanged.
9. `test_attempt_admission_refusals` — parametrize: unknown slot (`elastic_attempt_slot_unknown`), ordinal gap 2 with none recorded (`elastic_attempt_ordinal_invalid`), ordinal beyond `max_attempts` (`elastic_attempt_budget_exhausted`; use a slot with `max_attempts` equal to capacity), unpinned profile (`elastic_attempt_profile_not_pinned`), supersedes a predecessor with no outcome / a succeeded outcome / another slot's attempt (`elastic_attempt_supersedes_invalid`), a second successor of one predecessor (`elastic_attempt_already_replaced`). After each refusal the attempts table is unchanged.
10. `test_outcome_is_write_once` — identical repeat returns the stored outcome (first `recorded_at`); a different status → `elastic_attempt_outcome_conflict`; an outcome for an unknown attempt → `elastic_attempt_unknown`.
11. `test_concurrent_admission_of_one_ordinal_admits_exactly_one` — `asyncio.gather` two `record_attempt` calls for ordinal 1 of one slot with different pinned profiles (add a second pinned ref to the slot), `return_exceptions=True`: exactly one returns, the other is `ElasticTeamConflict`; one row stored.
12. `test_start_failure_closes_and_leaves_store_stopped` — a db path that is a directory: `start()` raises; operations then raise unavailable.

Focused command (Section 2):

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1286_elastic_team_contract.py tests/test_ad1286_elastic_team_store.py tests/test_ad1256_store_registry.py -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check
```

---

## Section 3: CrewSession binding — MODIFY `src/probos/cognitive/crew_session.py`

`bind_team_spec` writes **only** the parent row's `crew_elastic_team` key through `_merge_owned_metadata`, never a child row, never `crew_session`/`crew_recovery`. (R3: this is a statement about what AD-1286's code writes, not exclusivity of the key — see §8 F3.) `CrewSessionContract`, `CrewRecoveryContract`, `CrewRecoveryPlan`, `CrewRecoveryPlanChild` bodies are **not touched**.

### 3a. TYPE_CHECKING import

SEARCH:

```python
if TYPE_CHECKING:
    from probos.cognitive.crew_assignment import AssignmentDecision
    from probos.cognitive.crew_synth import SynthesisResult
```

REPLACE:

```python
if TYPE_CHECKING:
    from probos.cognitive.crew_assignment import AssignmentDecision
    from probos.cognitive.crew_synth import SynthesisResult
    from probos.cognitive.elastic_team import CrewElasticTeamBinding, TeamSpecLookup
```

### 3b. Module-level parser (keeps `CrewSessionService` from gaining a fourth method)

SEARCH:

```python
    if not valid:
        raise ValueError("crew_session_recovery_state_conflict")


class _WorkItemStoreProtocol(Protocol):
```

REPLACE:

```python3
    if not valid:
        raise ValueError("crew_session_recovery_state_conflict")


def _parse_team_binding(value: Any) -> CrewElasticTeamBinding:
    """AD-1286: strict parse of the stored ``crew_elastic_team`` binding (data integrity: propagate)."""
    from probos.cognitive.elastic_team import CrewElasticTeamBinding

    if type(value) is not dict:
        raise ValueError("crew_session_team_binding_invalid")
    try:
        return CrewElasticTeamBinding.model_validate(value)
    except ValidationError as exc:
        raise ValueError("crew_session_team_binding_invalid") from exc


class _WorkItemStoreProtocol(Protocol):
```

### 3c. Lookup slot in `__init__`

SEARCH:

```python
        self._owned_legacy_authorizer: owned_steps.OwnedStepsAuthorizer | None = None
        self._owned_view_authorizer: owned_steps.OwnedStepsAuthorizer | None = None
```

REPLACE:

```python
        self._owned_legacy_authorizer: owned_steps.OwnedStepsAuthorizer | None = None
        self._owned_view_authorizer: owned_steps.OwnedStepsAuthorizer | None = None
        # AD-1286: bound only by the crew-gated finalize wiring; unbound means binding refuses.
        self._team_spec_lookup: TeamSpecLookup | None = None
```

### 3d. Three public methods, inserted after `bind_worker_resolver`

SEARCH:

```python
    def bind_worker_resolver(self, resolver: CrewSessionWorkerResolver) -> None:
        """Bind the same assignment authority before native scheduling opens."""
        if self._worker_resolver is not None or resolver is None:
            raise ValueError("crew_session_worker_binding_invalid")
        self._worker_resolver = resolver
```

REPLACE: the same five lines, followed by:

```python

    def bind_team_spec_lookup(self, lookup: TeamSpecLookup) -> None:
        """AD-1286: bind the read port that resolves an exact team spec before a session binds it."""
        if self._team_spec_lookup is not None or lookup is None:
            raise ValueError("crew_session_team_lookup_binding_invalid")
        self._team_spec_lookup = lookup

    async def get_team_binding(self, parent_id: str) -> CrewElasticTeamBinding | None:
        """AD-1286: the exact team-spec reference this session durably bound, or None."""
        from probos.cognitive.elastic_team import CREW_ELASTIC_TEAM_METADATA_KEY

        parent = await self._work_items.get_work_item(_normalize_id(parent_id))
        if parent is None:
            return None
        metadata = parent.metadata or {}
        session_raw = metadata.get("crew_session", _MISSING)
        if session_raw is _MISSING:
            return None
        await self._validate_loaded(parent, self._parse_contract(session_raw))
        raw = metadata.get(CREW_ELASTIC_TEAM_METADATA_KEY, _MISSING)
        if raw is _MISSING:
            return None
        return _parse_team_binding(raw)

    async def bind_team_spec(
        self,
        parent_id: str,
        team_spec_ref: str,
        *,
        expected_session: CrewSessionContract,
    ) -> CrewElasticTeamBinding:
        """AD-1286: durably bind one exact, already-persisted team spec to a discussing session.

        Write-once, parent row only. Allowed only while the session is ``discussing``
        (recovery absent, ``unplanned`` or ``planned``) and no ``crew_provisioning``
        marker is present, so no accepted work can exist. A spec naming a
        ``plan_hash`` binds only when the installed recovery plan carries that hash;
        an installed plan is never replaced (``install_recovery_plan`` refuses once
        ``planned``; every other ``crew_recovery`` writer preserves the plan), so the
        check made here cannot go stale [R3: FALSE — superseded by §8 F2's docstring]. Re-binding the identical reference returns
        the stored binding; any other reference is a conflict.
        """
        from probos.cognitive.elastic_team import (
            CREW_ELASTIC_TEAM_METADATA_KEY,
            CrewElasticTeamBinding,
            is_sha256_ref,
        )

        parent_key = _normalize_id(parent_id)
        if not is_sha256_ref(team_spec_ref):
            raise ValueError("crew_session_team_spec_ref_invalid")
        lookup = self._team_spec_lookup
        if lookup is None:
            raise ValueError("crew_session_team_lookup_unavailable")
        spec = await lookup.get_team_spec(team_spec_ref)
        if spec is None:
            raise ValueError("crew_session_team_spec_not_found")
        candidate = CrewElasticTeamBinding.for_spec(spec)
        if candidate.team_spec_ref != team_spec_ref:
            raise ValueError("crew_session_team_spec_ref_invalid")
        candidate_json = candidate.model_dump(mode="json")
        expected_contract = self._validate_contract(expected_session)
        for _ in range(2):
            parent = await self._work_items.get_work_item(parent_key)
            if parent is None:
                raise ValueError("crew_session_parent_not_found")
            metadata = parent.metadata or {}
            session_raw = metadata.get("crew_session", _MISSING)
            if session_raw is _MISSING:
                raise ValueError("crew_session_not_initialized")
            current = self._parse_contract(session_raw)
            await self._validate_loaded(parent, current)
            existing_raw = metadata.get(CREW_ELASTIC_TEAM_METADATA_KEY, _MISSING)
            if existing_raw is not _MISSING:
                existing = _parse_team_binding(existing_raw)
                if _json_values_exactly_equal(existing.model_dump(mode="json"), candidate_json):
                    return existing
                raise ValueError("crew_session_team_binding_conflict")
            if not _json_values_exactly_equal(
                current.model_dump(mode="json"),
                expected_contract.model_dump(mode="json"),
            ):
                raise ValueError("crew_session_revision_conflict")
            if current.state != "discussing" or "crew_provisioning" in metadata:
                raise ValueError("crew_session_team_binding_state_invalid")
            recovery_raw = metadata.get("crew_recovery", _MISSING)
            recovery = None if recovery_raw is _MISSING else self._parse_recovery(recovery_raw)
            if recovery is not None and recovery.phase not in _DISCUSSING_RECOVERY_PHASES:
                raise ValueError("crew_session_team_binding_state_invalid")
            plan_hash = spec.process.plan_hash
            if plan_hash is not None and (
                recovery is None or recovery.plan is None or recovery.plan.plan_hash != plan_hash
            ):
                raise ValueError("crew_session_team_plan_mismatch")
            expected: dict[str, Any] = {"crew_session": session_raw}
            absent = {CREW_ELASTIC_TEAM_METADATA_KEY}
            if recovery_raw is _MISSING:
                absent.add("crew_recovery")
            else:
                expected["crew_recovery"] = recovery_raw
            try:
                updated = await self._merge_owned_metadata(
                    parent.id,
                    {CREW_ELASTIC_TEAM_METADATA_KEY: candidate_json},
                    expected=expected,
                    expected_absent_keys=frozenset(absent),
                    expected_work_type="crew_session",
                    expected_status=_STATUS_PROJECTION[current.state],
                    expected_assigned_to=current.facilitator_id,
                    source="crew_session_team_binding",
                )
            except ValueError as exc:
                if str(exc) != "work_item_metadata_conflict":
                    raise
                continue  # a concurrent writer moved the row; re-read once and decide again
            if updated is None:
                raise ValueError("crew_session_team_binding_failed")
            authoritative = _parse_team_binding(
                (updated.metadata or {}).get(CREW_ELASTIC_TEAM_METADATA_KEY),
            )
            if not _json_values_exactly_equal(authoritative.model_dump(mode="json"), candidate_json):
                raise ValueError("crew_session_team_binding_failed")
            logger.info(
                "AD-1286: crew session parent=%s bound team spec=%s (team=%s revision=%d); "
                "the binding is write-once and changes no accepted work",
                parent.id,
                authoritative.team_spec_ref,
                authoritative.team_id,
                authoritative.revision,
            )
            return authoritative
        raise ValueError("crew_session_team_binding_conflict")
```

Note: `CrewSessionService` is already a baseline `srp-size` row with triggers `[lines, methods]` (`architecture-baseline.yaml:469-473`); adding methods keeps the same triggers, so no baseline change is expected. `_WorkItemStoreProtocol` is not touched.

### Plan cross-check semantics (amendment 4) — **SUPERSEDED by §8 F2 (R3)**

> **R3 correction.** The rule and "proof" below are **false**: the enumeration searched `crew_session.py` writers only. A governed `replan_unstarted` writes a **new** plan through a store-applied manifest — `CrewOrchestrator._build_owned_steps_proposal_manifest` builds a `crew_recovery` patch with a new `"plan"` (`crew_orchestrator.py:2638-2663`) and `WorkItemStore._apply_owned_replan` applies `manifest.canonical_metadata_patch` to the parent (`workforce.py:5587-5590`, `:5623-5630`). The plan cross-check is a **bind-time admission check only**; §8 F2 defines the corrected semantics. The struck R0 text is kept below for the audit trail.

~~**Rule: checked once at bind time; the bound plan cannot change afterwards, so no re-check is needed and none is added.**~~ Original (incomplete) enumeration: `install_recovery_plan` refuses when the base phase is already `planned` or later (`crew_session.py:5553-5554`, `crew_recovery_plan_conflict`); `adopt_recovery_plan` refuses when `crew_recovery` exists (`:5664-5665`); `compare_and_set_recovery` and `transition_session` call `_require_preserved_plan` (`:5429`, `:5765`); the retry merge requires the plan unchanged (`workforce.py:9486-9487`); the retry-failure (`:5049-5055`) and ingress-resume (`:4868`) writers derive their checkpoint from the current recovery. AD-1288 re-validates the binding at commission time as part of its own admission; that is its scope, not this AD's. Test it (Section 5, `test_bound_plan_cannot_be_replaced`).

---

## Section 4: Wiring — default-off (amendment 1)

**Site:** a new async `_wire_elastic_team_store` in `src/probos/startup/finalize.py`, called **only inside** the existing `if _wire_crew_session_service(...)` block (`finalize.py:3952-3953`). `_wire_crew_session_service` returns `False` unless `config.agentic_dispatch.orchestrator_enabled` (`finalize.py:1983-1985`), so a default runtime never reaches it: no import of `probos.cognitive.elastic_team*` (both imports are function-local), no file, no log line. `bind_team_spec_lookup` is called from the same new function (not from `_wire_crew_orchestrator`), because the lookup belongs to the service, which exists exactly when this block runs.

**Precedents:** data path = `Path(runtime.data_dir) / "<name>.db"` as `finalize.py:3707` (`standing_interests.db`); ConnectionFactory = the store's lazy `default_factory` as `standing_interest_store.py:146-150` (finalize passes none, exactly like `finalize.py:3708`); `await store.start()` in finalize as `finalize.py:3714`. Failure policy: **log-and-degrade** — binding is optional and crew sessions must keep running; an unbound lookup makes `bind_team_spec` refuse (`crew_session_team_lookup_unavailable`), which is fail-closed.

### 4a. `src/probos/startup/finalize.py` — new function

SEARCH:

```python
    logger.info(
        "AD-1124: CrewSessionService initialized; durable sessions remain inert until explicitly bound"
    )
    return True


def _wire_crew_orchestrator(*, runtime: Any, config: "SystemConfig") -> bool:
```

REPLACE:

```python
    logger.info(
        "AD-1124: CrewSessionService initialized; durable sessions remain inert until explicitly bound"
    )
    return True


async def _wire_elastic_team_store(*, runtime: Any) -> bool:
    """AD-1286: open the elastic team store and bind it as the session's team-spec lookup.

    Called only after ``_wire_crew_session_service`` returned True, so a runtime
    with crew sessions disabled (the default) never imports, opens or logs this.
    """
    service = getattr(runtime, "crew_session_service", None)
    data_dir = getattr(runtime, "data_dir", None)
    if service is None or data_dir is None:
        logger.warning(
            "AD-1286: crew sessions are wired but the runtime has no %s; the elastic team store "
            "is not opened and team-spec binding stays unavailable",
            "crew session service" if service is None else "data directory",
        )
        return False
    if getattr(runtime, "elastic_team_store", None) is not None:
        return True
    from pathlib import Path

    from probos.cognitive.elastic_team_store import ElasticTeamStore

    db_path = Path(data_dir) / "elastic_teams.db"
    store = ElasticTeamStore(db_path=str(db_path))
    try:
        await store.start()
    except Exception:
        logger.warning(
            "AD-1286: ElasticTeamStore failed to start at %s; team-spec binding stays "
            "unavailable and crew sessions run unchanged",
            db_path,
            exc_info=True,
        )
        return False
    runtime.elastic_team_store = store
    service.bind_team_spec_lookup(store)
    return True


def _wire_crew_orchestrator(*, runtime: Any, config: "SystemConfig") -> bool:
```

### 4b. `src/probos/startup/finalize.py` — call site

SEARCH:

```python
    if _wire_crew_session_service(runtime=runtime, config=config):
        logger.info("AD-1124: CrewSessionService wired during finalization")

    if _wire_crew_orchestrator(runtime=runtime, config=config):
```

REPLACE:

```python
    if _wire_crew_session_service(runtime=runtime, config=config):
        logger.info("AD-1124: CrewSessionService wired during finalization")
        if await _wire_elastic_team_store(runtime=runtime):
            logger.info("AD-1286: ElasticTeamStore wired during finalization")

    if _wire_crew_orchestrator(runtime=runtime, config=config):
```

### 4c. `src/probos/runtime.py` — typed attribute (precedent AD-1228, `runtime.py:166`, `:495`, `:1081`)

SEARCH:

```python
    from probos.cognitive.standing_interest_store import StandingInterestStore  # AD-1228
    from probos.cognitive.standing_interests import StandingInterestService  # AD-1228
```

REPLACE:

```python
    from probos.cognitive.standing_interest_store import StandingInterestStore  # AD-1228
    from probos.cognitive.standing_interests import StandingInterestService  # AD-1228
    from probos.cognitive.elastic_team_store import ElasticTeamStore  # AD-1286
```

SEARCH:

```python
    standing_interest_store: StandingInterestStore | None  # AD-1228
    standing_interests: StandingInterestService | None  # AD-1228
```

REPLACE:

```python
    standing_interest_store: StandingInterestStore | None  # AD-1228
    standing_interests: StandingInterestService | None  # AD-1228
    elastic_team_store: ElasticTeamStore | None  # AD-1286
```

SEARCH:

```python
        self.standing_interest_store: StandingInterestStore | None = None
        self.standing_interests: StandingInterestService | None = None
```

REPLACE:

```python
        self.standing_interest_store: StandingInterestStore | None = None
        self.standing_interests: StandingInterestService | None = None
        # --- Elastic team store (AD-1286): set by finalize only while crew sessions are enabled ---
        self.elastic_team_store: ElasticTeamStore | None = None
```

(The first SEARCH is inside the existing `if TYPE_CHECKING:` block at `runtime.py:156`, so it executes nothing at boot.)

### 4d. `src/probos/startup/shutdown.py` — close it with the other SQLite sidecars

SEARCH:

```python
        ("standing_interest_store", "standing interest store"),  # AD-1228
        ("knowledge_edges", "knowledge edge store"),
```

REPLACE:

```python
        ("standing_interest_store", "standing interest store"),  # AD-1228
        ("elastic_team_store", "elastic team store"),  # AD-1286
        ("knowledge_edges", "knowledge edge store"),
```

`_stop_runtime_sqlite_sidecars` (`shutdown.py:297-335`) skips a `None` attribute, logs-and-continues on a failed `stop()`, hands the failure to the BF-882 rollback sink, and sets the attribute to `None`. No new `steps(...)` label is added, so `tests/test_issue1419_failed_start_rollback.py`'s step-label census is unchanged.

### Tests — `tests/test_ad1286_wiring.py` (NEW, `tmp_path` only — never the live vessel data dir, BF-883)

1. `test_disabled_runtime_never_imports_the_elastic_team_modules` — subprocess with `PROBOS_DATA_DIR=str(tmp_path)`: `import probos.runtime, probos.startup.finalize, probos.startup.shutdown, probos.cognitive.crew_session, sys; print(sorted(m for m in sys.modules if "elastic_team" in m))` prints `[]`.
2. `test_default_config_does_not_wire_crew_sessions` — `SystemConfig().agentic_dispatch.orchestrator_enabled is False` and `_wire_crew_session_service(runtime=bare_runtime, config=SystemConfig())` (with `bare_runtime` a `SimpleNamespace()`) returns `False`; `tmp_path` contains no `elastic_teams.db`.
3. `test_store_wiring_sits_inside_the_crew_session_gate` — AST of `probos.startup.finalize`: every call to `_wire_elastic_team_store` is lexically inside the body of an `If` whose test calls `_wire_crew_session_service`. (Structural placement test; state that rationale in its docstring. It pins placement, not a defect.)
4. `test_enabled_wiring_opens_store_and_binds_lookup` — `SimpleNamespace(crew_session_service=CrewSessionService(work_item_store=<started WorkItemStore at tmp_path>, chat_thread_store=ChatThreadStore(tmp_path / "threads.db")), data_dir=tmp_path)`; `await _wire_elastic_team_store(runtime=...)` is True; `tmp_path / "elastic_teams.db"` exists; `runtime.elastic_team_store` is started; a second call returns True and does not replace the store; `bind_team_spec_lookup` on the service now raises `crew_session_team_lookup_binding_invalid` (already bound).
5. `test_start_failure_degrades_and_leaves_binding_unavailable` — `(tmp_path / "elastic_teams.db").mkdir()`; returns False; WARNING record contains `AD-1286`; `getattr(runtime, "elastic_team_store", None) is None`; `bind_team_spec` raises `crew_session_team_lookup_unavailable`.
6. `test_shutdown_closes_the_elastic_team_store` — runtime `SimpleNamespace(elastic_team_store=<started store>)`; `await _stop_runtime_sqlite_sidecars(runtime)`; attribute is `None`; store operations raise unavailable.
7. `test_missing_data_dir_degrades_with_warning` — `data_dir=None` → False, WARNING naming the data directory, no file.

Focused command (Section 4):

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1286_wiring.py tests/test_bf296_shutdown_phase_ordering.py tests/test_issue1419_failed_start_rollback.py tests/test_ad1228_standing_interests.py -q -n 0 -p no:randomly
```

---

## Section 5: Cross-seam and tolerance tests (amendments 3 and 6)

### 5a. The only edit to an existing test file — `tests/test_ad1127_crew_session_lifecycle_recovery.py`

Add one keyword-only hook to the existing durable finalization harness so the full restart/finalize flow is **reused**, not re-invented. Existing callers pass nothing and behave identically.

SEARCH:

```python
async def _durable_finalization_harness(
    tmp_path: Path,
    *,
    child_count: int,
    output_size: int,
    attachment_decorator: Callable[[Any], Any] | None = None,
) -> Any:
```

REPLACE:

```python
async def _durable_finalization_harness(
    tmp_path: Path,
    *,
    child_count: int,
    output_size: int,
    attachment_decorator: Callable[[Any], Any] | None = None,
    after_session: Callable[[Any, Any], Any] | None = None,
) -> Any:
```

SEARCH:

```python
    parent, thread, service = await _session_parent(stores)
    children = [
        await _child(
            stores,
            parent_id=parent.id,
            child_id=f"checkpoint-child-{index:02d}",
        )
```

REPLACE:

```python
    parent, thread, service = await _session_parent(stores)
    if after_session is not None:
        # AD-1286: lets a caller act on the discussing session before any child exists.
        await after_session(parent, service)
    children = [
        await _child(
            stores,
            parent_id=parent.id,
            child_id=f"checkpoint-child-{index:02d}",
        )
```

### 5b. `tests/test_ad1286_crew_session_team_binding.py` (NEW)

Reuse, by import (precedent: `tests/test_ad1130_outcome_only_room_trust.py:35` imports from `test_ad1126`; `test_ad1152_crew_token_usage.py:51` imports the `stores` fixture from `test_ad1125`):
- from `tests.test_ad1127_crew_session_lifecycle_recovery`: `_new_session`, `_vector_plan_payload`, `_vector_insert`, `_VECTOR_PLAN_HASH`, `_VECTOR_ROW_HASH`, `_VECTOR_CHILD_ID`, `_durable_finalization_harness`, `_checkpoint_fault_finalizer`;
- from `tests.test_ad1125_room_bound_execution`: `stores` (fixture, `# noqa: F401`), and the module as `room` (`room._session_parent`, `room._child`);
- from `tests.test_ad1152_crew_token_usage`: `_owned_merge`;
- from `probos.cognitive.crew_session`: `CrewRecoveryPlan`, `_build_adopted_recovery_plan`;
- from `tests.test_ad1286_elastic_team_contract`: `_spec`.

Tests:

1. **`test_bound_reference_survives_restart_and_changes_no_accepted_work`** — the seam-crossing test (amendment 6). `work = WorkItemStore(db_path=str(tmp_path / "workforce.db"), tick_interval=1_000, connection_factory=SQLiteConnectionFactory())`; start; `parent, service, session = await _new_session(work, tmp_path)`; install the vector plan (`CrewRecoveryPlan.model_validate(_vector_plan_payload())`, `children=(_vector_insert(),)`) exactly as `test_ad1127:893-901`; snapshot `before_parent = dict(parent_row.metadata)`, `before_child = canonical json of the child row metadata`, `before_recovery = (await service.get_recovery(parent.id)).model_dump(mode="json")`. Create and start a real `ElasticTeamStore` at `tmp_path / "elastic_teams.db"`; `ref = await store.put_team_spec(_spec(process={"bill": None, "plan_hash": _VECTOR_PLAN_HASH}))`; `service.bind_team_spec_lookup(store)`; `session = await service.get_session(parent.id)`; `bound = await service.bind_team_spec(parent.id, ref, expected_session=session)`. **Close and reopen both stores** (stop; new `WorkItemStore` and new `ElasticTeamStore` on the same paths; a new `CrewSessionService(work_item_store=reopened, chat_thread_store=ChatThreadStore(tmp_path / "threads.db"))` with the reopened store bound as lookup). Assert: `await reopened_service.get_team_binding(parent.id) == bound` and `bound.team_spec_ref == ref`; `(await reopened_store.get_team_spec(ref)).content_ref() == ref`; recovery `plan.plan_hash == _VECTOR_PLAN_HASH` and its single child `row_hash == _VECTOR_ROW_HASH`; recovery dump equals `before_recovery`; the child row's metadata is byte-identical to `before_child`; the parent metadata equals `before_parent` plus exactly one new key `crew_elastic_team` whose value is `bound.model_dump(mode="json")` (no other key added, removed or changed); the binding value is under 1 KB (no blob embedded).
2. **`test_unbound_session_metadata_is_untouched_by_wiring_and_reads`** — on a fresh `_new_session` (separate `tmp_path` subdirectory): snapshot parent metadata canonical bytes; bind a lookup and call `get_team_binding` (→ `None`) and `get_session`; metadata bytes unchanged and contain no `crew_elastic_team`.
3. **`test_finalization_publishes_a_bound_session_and_keeps_the_binding`** (amendment 3: load, recovery, CAS, finalize, publish). Call `_durable_finalization_harness(tmp_path, child_count=2, output_size=128, after_session=bind)` where `bind(parent, service)` puts a **bill-only** spec into a store opened under `tmp_path`, binds the lookup and calls `bind_team_spec` (session is `discussing`, recovery absent). Then exactly as `test_finalizer_durable_checkpoint_fault_resumes_exactly_once` (`test_ad1127:2617-2739`) with `stage="synthesis"`, `fault=RuntimeError("synthesis-crash")`: the failing finalizer raises; `get_recovery` phase is `synthesized`; a fresh `_checkpoint_fault_finalizer(harness, stage=None, fault=None).resume(parent.id)` completes with `state == "done"`; `get_session` state `done`, recovery phase `published`. Assert `get_team_binding` returns the original binding and the parent row's `crew_elastic_team` value is byte-identical to the value bound. (This crosses `compare_and_set_recovery` at every checkpoint, `adopt_recovery_plan`'s whole-metadata `expected_parent_metadata`, and `publish_verified_result`'s `expected_present_keys=sibling_keys`, `crew_session.py:6138-6188`.) Close the store and `harness.stores_generator.aclose()` in `finally`.
4. **`test_retry_barrier_tolerates_a_bound_session`** — using the `stores` fixture: `parent, thread, service = await room._session_parent(stores)`; bind a bill-only spec (store under `tmp_path`); then the remaining steps of `_planned_child` (`test_ad1152:243-256`): `room._child`, transition to `executing`, `_build_adopted_recovery_plan`, `adopt_recovery_plan`; then the clean (`_ABSENT`) branch of `test_untouched_runtime_and_transactional_retry_guards_reject_any_sibling` (`test_ad1152:577-605`): `WorkItemRetryBarrier(parent, (child,))`, the same target/checkpoint patch and kwargs through `_owned_merge`; assert the parent becomes `blocked` and `crew_elastic_team` is unchanged.
5. `test_initialize_session_is_idempotent_on_a_bound_session` — after binding, re-call `initialize_session` with the original arguments: returns the existing contract; binding unchanged.
6. `test_bind_preconditions_refuse_without_mutation` — parametrize, each asserting the parent row metadata is unchanged afterwards: lookup unbound (`crew_session_team_lookup_unavailable`); malformed ref (`crew_session_team_spec_ref_invalid`); unknown ref (`crew_session_team_spec_not_found`); stale `expected_session` (`crew_session_revision_conflict`); session `executing` (`crew_session_team_binding_state_invalid`); a parent carrying `crew_provisioning` (`crew_session_team_binding_state_invalid` — set the marker via the provisioning path used by existing tests, or skip this case with a reason naming the missing fixture rather than writing the key directly); spec naming a `plan_hash` while recovery is absent (`crew_session_team_plan_mismatch`); spec naming a different `plan_hash` than the installed plan (`crew_session_team_plan_mismatch`).
7. `test_rebinding_is_idempotent_and_a_different_spec_conflicts` — same ref twice returns equal bindings, one key; a second spec ref → `crew_session_team_binding_conflict`.
8. `test_concurrent_binds_leave_exactly_one_binding` — `asyncio.gather` two binds of different refs (`return_exceptions=True`): exactly one succeeds, the other raises `ValueError` (`crew_session_team_binding_conflict`), and the stored binding equals the winner.
9. `test_bound_plan_cannot_be_replaced` (amendment 4) — after test 1's bind, a second `install_recovery_plan` raises `crew_recovery_plan_conflict`; binding and plan unchanged.
10. `test_get_team_binding_rejects_a_malformed_stored_binding` — write a malformed `crew_elastic_team` via `_owned_merge`/the store's owned path used in `test_ad1152` (not by bypassing guards); `get_team_binding` raises `crew_session_team_binding_invalid`. If no guard-respecting write path exists for a planned session, use an unplanned session and `merge_work_item_metadata` with the same expectations `bind_team_spec` uses.

Focused command (Section 3 + 5):

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1286_crew_session_team_binding.py tests/test_ad1124_crew_session_contract.py tests/test_ad1126_verified_finalization.py tests/test_ad1127_crew_session_lifecycle_recovery.py tests/test_ad1128_crew_session_ingress_dedup.py tests/test_ad1152_crew_token_usage.py -q -n 0 -p no:randomly
```

Frozen-contract and default-behaviour consumers (must pass **unchanged**):

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1125_room_bound_execution.py tests/test_ad1155_loop_until_done.py tests/test_ad1248_slice_c_one_shape.py tests/test_ad1325_boundaries.py tests/test_ad1132_crew_session_api.py tests/test_ad1072_agentic_tools.py tests/test_ad618a_bill_schema.py tests/test_ad618b_bill_instance_runtime.py -q -n 0 -p no:randomly
```

### 5c. Public-surface census pins (R2-1) — MODIFY two existing test files, census pin only

Two tests pin the **exact public surface** of `CrewSessionService` and were not named in R0: `tests/test_ad1124_crew_session_contract.py::test_public_service_api_and_annotations_are_exact` (`public == original_public | admitted_public`, ≈ line 1913) and `tests/test_ad1126_verified_finalization.py::test_public_session_apis_and_finalizer_signature_are_fully_typed` (`service_public == {…}`, ≈ line 6053). They are **public-surface census pins**, not frozen-contract pins: their purpose is that every public method is deliberately recorded (ad1124's own comment: "The former 17-method-only pin masked the admitted owned execution ports"; ad1126 records one comment per admitted AD, e.g. AD-1321). Section 3d's three methods are an intended, specified API addition, so they are recorded there — by exactly these edits and nothing else.

Decision (ranked): **A (chosen)** — add the three names to the existing admitted sets with an `# AD-1286:` comment; in ad1124 the existing `for method_name in admitted_public:` loop then annotation-checks them for free, and the count assertion moves 25 → 28. B (a separate `elastic_team_public` set) is rejected: it needs its own annotation loop and departs from the file's convention for no gain. C (no public growth) is impossible: AD-1288 must call `bind_team_spec`, `get_team_binding` is the read API, and `bind_team_spec_lookup` mirrors `bind_worker_resolver`'s constructor-free DI binding. Do **not** touch `original_public`, `expected_parameters`, ad1126's typed-method tuple, or any other assertion in either test.

Both files are CRLF (Grep `\r$`: ad1124 2,209 lines, ad1126 8,254 lines). Apply each block as an exact text edit with an editor that preserves the file's existing line endings; a SEARCH that matches nothing is a hard stop, not a reason to retype the block.

`tests/test_ad1124_crew_session_contract.py` — SEARCH:

```python
        "reassign_unstarted", "record_correction", "record_unstarted",
        "register_owned_steps_component", "start", "submit", "validate",
    }
    # The former 17-method-only pin masked the admitted owned execution ports.
    assert len(original_public) == 17 and len(admitted_public) == 25
```

REPLACE:

```python
        "reassign_unstarted", "record_correction", "record_unstarted",
        "register_owned_steps_component", "start", "submit", "validate",
        # AD-1286: write-once team-spec binding, its read API, and the lookup-port
        # binder (mirrors bind_worker_resolver); annotation-checked by the loop below.
        "bind_team_spec", "bind_team_spec_lookup", "get_team_binding",
    }
    # The former 17-method-only pin masked the admitted owned execution ports.
    assert len(original_public) == 17 and len(admitted_public) == 28
```

`tests/test_ad1126_verified_finalization.py` — SEARCH:

```python
        "get_owned_steps_snapshot",
        "get_recovery",
```

REPLACE:

```python
        "get_owned_steps_snapshot",
        "get_recovery",
        # AD-1286: write-once team-spec binding, its read API and lookup-port binder.
        "bind_team_spec",
        "bind_team_spec_lookup",
        "get_team_binding",
```

### 5d. One documented layer exception (R2-2) — MODIFY `tests/test_layer_boundaries.py`

`tests/test_layer_boundaries.py::test_no_undocumented_cross_layer_imports` (AD-400) walks **every** import node, function-level included, against its own `LAYER_MAP` / `ALLOWED_IMPORTS` (`"cognitive": {"knowledge", "substrate", "mesh"}`, line 51). Measured on this worktree (2026-10-10, `pytest tests/test_layer_boundaries.py`): 1 failed, 2 passed, one finding only — `cognitive/elastic_team.py:63 — cognitive imports probos.federation.ard.jcs (federation)`.

Decision (ranked): **A (chosen)** — a documented `ALLOWED_EXCEPTIONS` entry, following the direct precedent `("cognitive/capability_triage.py", "probos.federation.ard.adoption")` (line 121, also a lazy cognitive→federation.ard import). It changes no source the Builder has written and no identity byte. B (a new layer-neutral top-level wrapper module) is rejected: it adds a module and a source edit to `elastic_team.py` (already built and byte-identical to Section 1) purely to launder the same dependency; widening `probos.identity_keys.canonical_bytes` to accept lists would change an existing public helper's contract out of footprint. C (a private canonicaliser asserted byte-equal to jcs) is rejected: it is the D2 rank-2 option, adds an 84th ad-hoc canonical-JSON site, and would rewrite Section 1.

Other new imports, verified by reading `_get_layer` / `_get_imported_layer` (lines 125-153): `startup/finalize.py` and `startup/shutdown.py` — `startup` is not in `LAYER_MAP`, so `_get_layer` returns None and the file is skipped; `runtime.py` is a top-level "core" module, skipped; `elastic_team_store.py` → `probos.protocols` (top-level, `_get_imported_layer` → None) and `probos.storage.sqlite_factory` (`storage` not in `LAYER_MAP` → None); `crew_session.py` / `elastic_team_store.py` → `probos.cognitive.elastic_team` (same layer). None can trip the test; the measured run above confirms exactly one finding.

`tests/test_layer_boundaries.py` (CRLF, 254 lines; same editing rule as 5c) — SEARCH:

```python
    ("cognitive/capability_triage.py", "probos.federation.ard.adoption"),
}
```

REPLACE:

```python
    ("cognitive/capability_triage.py", "probos.federation.ard.adoption"),
    # AD-1286: the elastic team contract hashes its identities with AD-1144's
    # RFC 8785 canonicaliser -- the one standards-grade canonical-JSON owner --
    # rather than adding another ad-hoc ``sort_keys`` site (DRY). The import is
    # lazy and function-level (``canonicalize_projection``) and ``jcs`` is pure
    # stdlib; importing ``elastic_team`` never imports the federation package
    # (pinned by tests/test_ad1286_elastic_team_contract.py, test #12(b)).
    ("cognitive/elastic_team.py", "probos.federation.ard.jcs"),
}
```

`test_no_stale_allowed_exceptions` stays green because `elastic_team.py` really contains that import (line 63).

Focused command (5c + 5d):

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1124_crew_session_contract.py tests/test_ad1126_verified_finalization.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly
```

---

## Section 6: Trackers and ledger (amendment 7) — last

> **R3:** the DECISIONS and PROGRESS wording below is corrected by **§8 "Trackers (Section 6 corrections, R3)"**, which wins wherever they differ (the plan check is bind-time only; the key is not exclusive before a plan exists; `WITHOUT ROWID`; re-measured counts).

1. **`DECISIONS.md`** (append-only; never edit an existing entry). Convention for current entries: a new `### AD-NNNN -- Title` block inserted directly under `## Era V — Civilization (Phases 31-36)` (as AD-1315/AD-1316 at `DECISIONS.md:13/23`). SEARCH `## Era V — Civilization (Phases 31-36)\n\n### AD-1315 -- Protected ProbOS host authority and durable admission witness` and insert between them a block `### AD-1286 -- Elastic Team Contract: immutable team specs, durable slots, ephemeral attempts` with `**Status:** IMPLEMENTED candidate (#1333), inert until AD-1288; store opened only when crew sessions are enabled.` then **Decision.** (D1 module split and import direction; D2 identity = sha256(domain prefix + RFC 8785 bytes), no floats, sets sorted, optionals emitted as null, fixed key set per schema version; runtime outcome excluded), **Durable association.** (D3 `crew_elastic_team` on the parent row, written only by `CrewSessionService.bind_team_spec`, write-once, discussing only, plan cross-check at bind time with the write-once-plan proof; 27-key `CrewSessionContract`, `CrewRecoveryContract`, 14-key `crew_execution` and `SubtaskResult` unchanged), **Storage.** (D4 insert-only `elastic_teams.db`; twelve triggers abort every UPDATE, every DELETE and every INSERT that would replace an existing row — REPLACE / INSERT OR REPLACE, including through a secondary unique key — without relying on `recursive_triggers`; the store issues plain INSERTs only after explicit reads; contiguous ordinals, supersession rules, store declared under AD-1256), **Forward compatibility.** (D5 typed closed policies; `execution_profile_ref` is a reference that AD-1287 computes; pinned profiles carry skill/model/prompt/tool/policy, so unpinned slots bind the exact profile on the attempt instead), **Boundary.** (no provisioning, ranking, blackboard, scatter/gather, UI/API, EventType, config; Bill schema untouched; OSS only. The store does not validate session membership — it cannot know that an attempt's `session_id` names a CrewSession that bound the spec, because that fact lives in the work-item store with no cross-store transaction; AD-1288's commission admission must check `get_team_binding(session_id)` against the spec before it records an attempt), **Existing tests edited (R2).** (name all four, with why: `tests/test_ad1127_crew_session_lifecycle_recovery.py` — one optional `after_session` hook on the durable finalization harness, existing callers unchanged; `tests/test_ad1124_crew_session_contract.py` and `tests/test_ad1126_verified_finalization.py` — public-surface census pins extended by the three new `CrewSessionService` methods, no frozen-contract pin touched; `tests/test_layer_boundaries.py` — one documented `ALLOWED_EXCEPTIONS` entry for the lazy `probos.federation.ard.jcs` import).
2. **`PROGRESS.md`** — insert one bold paragraph directly under `# ProbOS Progress` (line 1), in the existing style (`PROGRESS.md:3`): `**AD-1286 IMPLEMENTED candidate (2026-10-10), #1333 -- ...**` stating what shipped, what is inert, the exact focused test counts you measured per file, the four existing test files edited and why (same list as the DECISIONS "Existing tests edited" bullet), and "#1333 stays open until review, gate and verified closure; AD-1287–1290 remain."
3. **`docs/development/roadmap.md`** — row at line 526 only. SEARCH `| AD-1286 | Elastic Team Contract - immutable team specs, durable slots, ephemeral attempts | [#1333](https://github.com/seangalliher/ProbOS/issues/1333) | 1 |` → REPLACE with the same row whose title cell ends `... ephemeral attempts (implemented candidate 2026-10-10; inert until AD-1288)`. No other roadmap edit.
4. **Ledger guard.** `tests/test_ad1184_ad_ledger.py::test_check_passes_against_the_committed_report` runs `scripts/gen_ad_ledger.py --check`, which re-renders from the pinned snapshot plus a **live** parse of DECISIONS.md and PROGRESS.md (`gen_ad_ledger.py:17-22, 30-32`). Today the committed `docs/development/open-ads-report.md` has no `AD-1286` row (Grep: no match) and its issue snapshot predates #1333 (snapshot `2026-08-29T05:45:15Z`, `open-ads-report.md:41`; #1333 was allocated 05:55Z per #1332). So after steps 1–2:
   - Run `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py --check`.
   - If it exits 0, do nothing more.
   - If it exits nonzero, run `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py` (**no** `--online`), confirm with `git status --short` that it changed only `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`, then rerun `--check` → must exit 0. Precedent: the AD-1321–1325 closure refreshed the report the same way (`PROGRESS.md:7`). Report which branch occurred.

Focused command (Section 6):

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1184_ad_ledger.py -q -n 0 -p no:randomly
```

---

## Section 7: Architecture and registry checkers (amendment 5)

Definitions read from `scripts/check_architecture_principles.py`:

- `srp-size`: a `ClassDef` whose body span > **500** lines or whose **direct** `FunctionDef`/`AsyncFunctionDef` children > **15** (`:187-188`, `:558-569`). **Pydantic `@field_validator`/`@model_validator` methods and `@classmethod`s are `FunctionDef`s and DO count.** That is why Section 1 uses module-level `BeforeValidator` functions: every model above has ≤ 3 methods; `ElasticTeamStore` ≤ 12.
- `layer-import`: only between the five ranked packages (`substrate, mesh, consensus, cognitive, experience`, `architecture-baseline.yaml:12-17`); `TYPE_CHECKING` imports are skipped (`:588`). `probos.protocols`, `probos.storage`, `probos.federation` are unranked, so nothing here can trigger it.
- `db-connect`: a call rendering to `sqlite3.connect` or `aiosqlite.connect` in `src/` (`:191-193`). The store uses only `ConnectionFactory.connect`.
- `unowned-task`: a bare-statement `asyncio.create_task`/`ensure_future` (`:198-200`). Create no task.

Run, after every section that touches `src/`:

```
d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1270b_architecture_fitness.py tests/test_ad1256_store_registry.py -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_layer_boundaries.py -q -n 0 -p no:randomly
```

(R2) `tests/test_layer_boundaries.py` is a **second, independent** layer checker (AD-400): unlike `check_architecture_principles.py` it ranks `federation` and other packages in its own `LAYER_MAP` and walks function-level imports. Its only AD-1286 finding is resolved by the §5d exception; any other finding is a hard stop.

**Never run `--update-baseline` on either script.** Any `NEW VIOLATION`, `STALE BASELINE ROW`, `COUNT DRIFT` or `TRIGGER DRIFT`, or any store-registry error that the Section 2c declaration does not resolve, is a hard stop.

---

## Section 8: Review round 1 repairs (R3)

The independent Diff Reviewer (GPT-6.1 Sol, probes against the real stores) returned **BLOCKED** on the staged candidate. Several findings are false or incomplete claims in **this prompt**, not Builder errors (F2, F3, and the "immutable at the SQLite boundary" claim of F1). This section is the authorised repair. It **explicitly authorises** amendments to these already-built files and nothing else: `src/probos/cognitive/elastic_team.py` (one token, F4), `src/probos/cognitive/elastic_team_store.py`, `src/probos/cognitive/crew_session.py` (`bind_team_spec`, `get_team_binding` bodies and docstrings only — **no new public method**, the census pins list exactly three), `src/probos/startup/finalize.py` (`_wire_elastic_team_store` only), the four `tests/test_ad1286_*.py` files, and the staged AD-1286 entries in `DECISIONS.md` / `PROGRESS.md`. The DECISIONS entry is still uncommitted, so correcting it now does not violate the append-only rule (that rule binds committed history).

Do the repairs in this order: F1 → F4 → F5 → F8 → F6 → F2 → S1 → F7 → F3 → F9 → S2 → trackers. Run Execution brief step 0 first (worktree import root).

### Rulings and decisions

| ID | Ruling | Decision (ranked options) |
|---|---|---|
| F1 | **Confirmed, High.** Implicit `rowid` replacement bypasses all twelve triggers. | **A (chosen):** `WITHOUT ROWID` on all four tables. B: add `rowid` to the guard predicates — rejected (still a hidden mutable key, and every future guard must remember it). |
| F2 | **Confirmed, High.** A governed `replan_unstarted` replaces the plan (`crew_orchestrator.py:2638-2663` → `workforce.py:5587-5590, :5623-5630`). My R0 enumeration was `crew_session.py`-only — an Evidence Standard failure. | **A (chosen):** the plan cross-check is a bind-time admission check only; delete every "cannot go stale" claim; re-run the check on the idempotent re-bind path (currency check → `crew_session_team_plan_mismatch`); AD-1288's commission admission must compare `spec.process.plan_hash` with the session's current plan. B: refuse `replan_unstarted` for a team-bound parent — rejected here (changes `workforce.py`/`crew_orchestrator.py` behaviour; a lifecycle policy that belongs to AD-1288). C: drop the bind-time check — rejected (it still prevents binding to the wrong plan at the one moment AD-1286 owns). |
| F3 | **Reclassified: pre-existing platform property (Medium), not an AD-1286 regression.** Before a plan is installed the in-process `merge_work_item_metadata` primitive accepts any `crew_*` key on a crew-session parent — `crew_session` and `crew_recovery` included — so `crew_elastic_team` is exactly as protected as the contract key itself; once `steps_control` exists, owned steps refuse generic writes (`owned_steps_write_reserved`); over HTTP a generic PATCH returns 409 for an **unplanned** parent only (`crew_session_write_reserved`), and **500** for a planned parent because the router does not map `OwnedStepsError` (R4 correction; #1419 F-2). AD-1286's error was claiming exclusivity. Filed to #1419 (text below). | **A (chosen):** correct every exclusivity claim; keep `get_team_binding` strict-parse fail-closed **and**, when a lookup is bound, verify the referenced spec exists and its `team_id`/`revision` match (cheap verify-on-read, same stance as the store's integrity reads). B: strict parse only — rejected (a dangling or mismatched binding would read as valid). C: harden the key in `workforce.py` — rejected (out of footprint; would not raise the bar while `crew_session` stays forgeable the same way). |
| F4 | **Confirmed, High.** Nested instances skip validation (`revalidate_instances='never'`). | **A (chosen):** `revalidate_instances="always"` on `_Frozen` **and** revalidate incoming instances at every store entry point and in `bind_team_spec`. B: entry revalidation only — rejected (outer `model_validate` would still accept a nested invalid instance). |
| F5 | **Confirmed, High.** Swallowing every ROLLBACK failure leaves uncommitted rows readable on the one connection. | **A (chosen):** suppress only `sqlite3.OperationalError` with message exactly `cannot rollback - no transaction is active`; any other rollback failure closes the connection (SQLite discards the uncommitted work), marks the store unavailable, logs ERROR, and the caller re-raises the **original** error. B: re-raise the rollback failure — rejected (loses the original cause; the store would still hold the poisoned connection). |
| F6 | **Confirmed, High** (requires DB-level tampering). | **A (chosen):** inside the open transaction, load and verify the canonical spec, derive `max_attempts` and pinned refs **from the spec**, and treat the slot row's cached columns and `slot_digest` as a projection that must equal it (integrity error otherwise); require existing ordinals to be exactly `1..n`; verify the predecessor row against its digest. B: drop the cached columns (schema change) — rejected (the slot row is still needed as the FK target; equality-checking the cache gives the same protection without a schema change). C: verify only spec existence — rejected (a tampered cache would still steer admission). |
| F7 | **Confirmed, Medium.** | **A (chosen):** bounded retry (3 attempts) on `work_item_metadata_conflict` **or** `owned_steps_plan_conflict`, each re-reading and re-deciding; after the last attempt re-raise the last error; every other authority failure propagates at once. B: unbounded retry — rejected. |
| F8 | **Confirmed, Medium.** | `stop()` takes `_lock`; it waits for an in-flight operation, then closes. `start()` already holds the lock, so start/stop serialise. |
| F9 | **Confirmed, Medium.** | **A (chosen):** a `sqlite3.DatabaseError` that is **not** a `sqlite3.OperationalError` (e.g. "file is not a database") is data-integrity: log ERROR and re-raise (startup fails and the BF-882 rollback runs); `OperationalError` and other exceptions keep warn-and-degrade. B: log ERROR and degrade — rejected: the repo's three-tier rule puts data integrity in "propagate", and AD-1127 already fails enabled crew startup before admission on a missing mandatory dependency. Operator remedy, stated in the ERROR log: move the corrupt `elastic_teams.db` aside. |
| S1 | **Confirmed.** | Add `"crew_provisioning"` to `expected_absent_keys` in `bind_team_spec`. |
| S2 | **Confirmed.** | Bind the lookup **before** publishing `runtime.elastic_team_store`; if `bind_team_spec_lookup` raises, close the new store, log a warning, return False. No new public unbind API (census pins). |

### Method budget

The architecture checker's triggers are > 500 body lines or > 15 direct methods (`check_architecture_principles.py:187-188`). R0 said "at most 12"; **R3 allows up to 15 methods and < 500 body lines**. Expected after repairs: **13** methods (`_rollback_quietly` becomes the method `_abandon_transaction`, which needs `self`); every other new helper is **module-level** (`_is_no_transaction`, `_verified_spec`, `_load_verified_spec`, `_require_contiguous_ordinals`). If the class body would exceed ~480 lines, move more logic into module-level helpers taking `db`. Never call a public getter (which takes `_lock`) from inside a locked section.

### F1 — `WITHOUT ROWID` (`elastic_team_store.py` `_SCHEMA`)

- Change each of the four `CREATE TABLE … ( … );` to `CREATE TABLE … ( … ) WITHOUT ROWID;`. Primary keys, the FKs, the partial unique index `elastic_worker_attempts_one_successor` and all twelve triggers stay as they are.
- No migration: the store never reached `origin/main` (`git log origin/main --oneline -- src/probos/cognitive/elastic_team_store.py` → no output; control on `crew_session.py` → `0debd77b`), so no released rowid-shaped file exists. Developer databases under `tmp_path` are discarded per test.
- Store docstring and §2c `retention_note`: add "the tables are `WITHOUT ROWID`, so no implicit rowid exists to replace a row through".
- Tests (`tests/test_ad1286_elastic_team_store.py`):
  - **Expected change:** `_read_tables` (≈ :133-134) orders by `rowid`, which no longer exists. Order by each table's primary key instead (specs `spec_ref`; slots `spec_ref, slot_id`; attempts `worker_attempt_id`; outcomes `worker_attempt_id`).
  - Extend `test_triggers_refuse_every_mutation_and_replacement_on_every_table`: per table, `INSERT OR REPLACE INTO <t> (rowid, <all columns>) VALUES (<existing row's rowid-free values with one column changed>, …)` on the raw default-pragma connection raises `sqlite3.DatabaseError` (message contains `rowid`) and the snapshot is unchanged.
  - New `test_every_table_is_without_rowid` — `SELECT sql FROM sqlite_master WHERE type='table'` for the four tables: each ends with `WITHOUT ROWID`.

### F4 — revalidate instances (`elastic_team.py`, `elastic_team_store.py`, `crew_session.py`)

- `elastic_team.py`: `_Frozen.model_config` becomes `ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")`. That is the **only** change to this file. The orchestrator executed this exact change: nested invalid instances are refused and valid instances re-validate to the same identity.
- `elastic_team_store.py`: after each type check, rebind through validation before hashing or inserting — `spec` through `ElasticTeamSpec.model_validate(spec)` in `put_team_spec`, `attempt` through `WorkerAttempt.model_validate(attempt)` in `record_attempt`, `outcome` through `WorkerAttemptOutcome.model_validate(outcome)` in `record_attempt_outcome`. A `ValidationError` propagates (it is a `ValueError`; its text carries the stable code) and nothing is written.
- `crew_session.py` `bind_team_spec`: after `lookup.get_team_spec(...)` returns non-None, rebind `spec` through `ElasticTeamSpec.model_validate(spec)` (lazy import beside the existing ones) before `CrewElasticTeamBinding.for_spec(spec)`.
- Tests:
  - contract: `test_outer_validation_refuses_a_nested_instance_built_without_validation` — a `SlotBudget` built with `model_copy(update={"max_tokens": 1.5})` inside an otherwise valid spec → `ValidationError` matching `elastic_team_budget_invalid`.
  - contract: `test_revalidation_keeps_every_known_answer_identity` — `ElasticTeamSpec.model_validate(spec)` of the KAT spec equals it and `content_ref() == _KAT_SPEC_REF`; same for the slot and attempt KAT literals. **The four KAT literals must not change**; if any moves, hard stop.
  - store: `test_store_revalidates_a_top_level_copy_that_skipped_validation` — parametrize spec / attempt / outcome built with `model_copy(update=…)` to an invalid value: `ValidationError`, snapshot unchanged.

### F5 — rollback failure poisons the connection (`elastic_team_store.py`)

> **R4: SUPERSEDED by §9.** The shared-connection quarantine below was itself defective (R2-1, R2-2) and is replaced by one connection per operation. Kept for the audit trail.

- Module-level `_is_no_transaction(exc: BaseException) -> bool`: `isinstance(exc, sqlite3.OperationalError) and str(exc) == "cannot rollback - no transaction is active"` (the exact aiosqlite message, measured by the orchestrator). Import `sqlite3` at module top (stdlib; the architecture checker flags only `sqlite3.connect` calls, and there are none).
- Replace module `_rollback_quietly(db)` with method `async def _abandon_transaction(self, db: Any) -> None`. It never raises (except `CancelledError` from `close`, which must propagate): `ROLLBACK`; if that raises and `_is_no_transaction(exc)` → `logger.debug` with the existing "found no open transaction" wording (the existing fake-connection test keys on it); any other exception → set `self._db = None`, `await db.close()` (a close failure is logged at WARNING and swallowed — the connection is already being discarded), then `logger.error("AD-1286: rollback failed after a failed elastic team write; the connection was closed so the uncommitted rows cannot be read or committed, and the store is unavailable until it is started again", exc_info=True)`.
- Every write path keeps `except BaseException: await self._abandon_transaction(db); raise`, so the **original** error propagates.
- Tests (store, through a `ConnectionFactory` proxy wrapping a real aiosqlite connection, which delegates everything but fails `ROLLBACK` with `RuntimeError("injected rollback failure")` and fails one chosen statement first — e.g. the second slot INSERT):
  - `test_failed_rollback_closes_the_connection_and_leaves_no_partial_rows` — `put_team_spec` raises the **original** injected failure; any store call then raises `ElasticTeamStoreUnavailable`; an ERROR record containing `AD-1286: rollback failed` exists; a fresh `ElasticTeamStore` on the same path (real factory) returns `None` from `get_team_spec(ref)` and a raw snapshot has no spec and no slot rows.
  - Keep `test_failed_write_propagates_the_original_error_when_rollback_has_nothing_to_undo` as is (benign path).

### F8 — `stop()` under the lock (`elastic_team_store.py`)

- `stop()`: `async with self._lock:` around the swap and close; the info log after the lock.
- Test `test_stop_waits_for_an_in_flight_write` — a proxy connection whose `commit` awaits an `asyncio.Event`; start `put_team_spec`, wait until the commit is entered, call `stop()` concurrently, release the event: the write completes, then `stop()` completes, and a reopened store returns the spec.

### F6 — verified admission (`elastic_team_store.py` `_admit_attempt`)

Module-level helpers (each takes the open `db`; none takes `_lock`):
- `_verified_spec(stored: str, team_spec_ref: str) -> ElasticTeamSpec` — the verification now inside `get_team_spec` (parse, `content_ref` equality, canonical text equality; ERROR log + `ElasticTeamIntegrityError("elastic_team_spec_integrity")`). `get_team_spec` calls it (DRY).
- `async _load_verified_spec(db, team_spec_ref) -> ElasticTeamSpec | None` — reads `canonical_json` and calls `_verified_spec`.
- `async _require_contiguous_ordinals(db, attempt) -> int` — `SELECT ordinal … WHERE session_id=? AND spec_ref=? AND slot_id=? ORDER BY ordinal`; if the list is not exactly `[1, …, n]` → ERROR log + `ElasticTeamIntegrityError("elastic_attempt_integrity")`; returns `n`.

`_admit_attempt` order (each refusal writes nothing):
1. Slot row (`max_attempts, pinned_profile_refs, slot_digest`) missing → `ElasticTeamConflict("elastic_attempt_slot_unknown")` (unchanged).
2. `spec = await _load_verified_spec(db, attempt.team_spec_ref)`; `None` (orphan slot) → `ElasticTeamIntegrityError("elastic_team_spec_integrity")`.
3. `slot = spec.slot(attempt.slot_id)`; `None`, or `slot.content_ref() != slot_digest`, or `slot.budget.max_attempts != max_attempts`, or `_pinned_refs(pinned_text) != slot.qualification.pinned_profile_refs` → `ElasticTeamIntegrityError("elastic_team_spec_integrity")`. From here use **the spec's** values.
4. `attempt.ordinal > slot.budget.max_attempts` → `elastic_attempt_budget_exhausted`.
5. `n = await _require_contiguous_ordinals(db, attempt)`; `attempt.ordinal != n + 1` → `elastic_attempt_ordinal_invalid`.
6. Pinned check against `slot.qualification.pinned_profile_refs`.
7. Supersession: read the predecessor with `_ATTEMPT_COLUMNS` and rebuild it with `_attempt_from_row` (digest-verified; integrity error on tamper); then the existing same-session/spec/slot, older-ordinal (keep it in the same boolean `if`, no separate branch), failed/cancelled outcome and already-replaced checks.

Tests:
- **Expected change:** `test_admission_refuses_a_predecessor_that_is_not_older` (≈ :958-982) pins acceptance of ordinal 2 after a raw ordinal-3 row. Rename to `test_admission_refuses_a_noncontiguous_history_as_an_integrity_failure`; both the replacement and the former "control" now raise `ElasticTeamIntegrityError("elastic_attempt_integrity")`, snapshot unchanged.
- New `test_admission_refuses_an_orphan_slot` (raw insert of a slot row with no spec; raw connection without `foreign_keys`) → `elastic_team_spec_integrity`.
- New `test_admission_refuses_a_slot_cache_that_disagrees_with_the_spec` — parametrize tampering `max_attempts`, `pinned_profile_refs` (a valid but different list) and `slot_digest` (drop the slot UPDATE trigger first, as the existing tamper tests do) → `elastic_team_spec_integrity`.
- New `test_admission_refuses_a_tampered_predecessor` → `elastic_attempt_integrity`.
- Existing `test_tampered_slot_pin_list_refuses_admission_and_writes_nothing` keeps its code (`elastic_team_spec_integrity`).

### F2 — plan cross-check is bind-time only (`crew_session.py` `bind_team_spec`)

- Move the recovery parse (`recovery_raw` / `recovery`) **above** the `existing_raw` check. In the idempotent branch (an identical binding already stored), before returning, re-run the plan check: if `spec.process.plan_hash is not None` and (`recovery is None` or `recovery.plan is None` or `recovery.plan.plan_hash != spec.process.plan_hash`) → `ValueError("crew_session_team_plan_mismatch")`. State checks are **not** added to the idempotent branch (an identical re-bind after the session moved on still returns the stored binding).
- Replace the docstring's plan sentences with: "A spec naming a ``plan_hash`` binds only when the session's **current** recovery plan carries that hash. This is a bind-time admission check: a later governed replan (``replan_unstarted``) can install a different plan and leaves the binding unchanged, so a repeat bind then reports ``crew_session_team_plan_mismatch``, and AD-1288's commission admission must compare ``spec.process.plan_hash`` with the session's current plan before it commissions any attempt." Also replace "so no accepted work can exist" with "so the session has not started executing".
- Tests (`tests/test_ad1286_crew_session_team_binding.py`):
  - New `test_governed_replan_leaves_the_binding_and_rebind_reports_plan_mismatch` — reuse the real owned-steps HTTP harness: import the `owned_projection_case` fixture from `tests.test_ad1132_crew_session_api` (fixture import precedent: `test_ad1152_crew_token_usage.py:51`). `parent_id = await case.managed_parent(canonical=True)` (create + adopt; session `discussing`, plan installed); open an `ElasticTeamStore` under `tmp_path`; `case.state.service.bind_team_spec_lookup(store)` (the fixture builds `CrewSessionService` directly, `ui/e2e/fixtures/ad1192_backend.py:1391`, with no lookup bound); put a spec whose `plan_hash` is the current `(await case.state.service.get_recovery(parent_id)).plan.plan_hash`; bind. Then `await case.apply(parent_id, "replan_unstarted", "ad1286-replan")`. Assert: the plan hash changed; `get_team_binding(parent_id)` equals the binding; the parent's `crew_elastic_team` value is byte-identical; a repeat `bind_team_spec` with the same ref raises `crew_session_team_plan_mismatch`. Close the store in `finally`.
  - **Expected change:** rename `test_bound_plan_cannot_be_replaced` (≈ :456) to `test_install_recovery_plan_refuses_a_second_plan_after_binding` and change its section comment (≈ :452, "The cross-checked plan cannot change after binding") to "install_recovery_plan alone cannot replace the plan; a governed replan can (see the replan test)". Its assertions stay.

### S1 — provisioning marker in the CAS (`crew_session.py`)

- `absent = {CREW_ELASTIC_TEAM_METADATA_KEY, "crew_provisioning"}`.
- Test `test_provisioning_marker_written_between_read_and_cas_refuses_the_bind` — wrap the work-item store so that `merge_work_item_metadata` first writes a `crew_provisioning` marker through the real provisioning path used by binding test 6, then delegates: the bind raises (after the re-read, `crew_session_team_binding_state_invalid`) and no `crew_elastic_team` is stored.

### F7 — planned-session concurrency (`crew_session.py`)

- Loop `for _ in range(3)`; keep `last_error: ValueError | None`. Catch `ValueError` whose `str(exc)` is `work_item_metadata_conflict` **or** `owned_steps_plan_conflict` (an `OwnedStepsError` is a `ValueError` whose `str()` is its code): record it, `continue`. Any other `ValueError` propagates. After the loop `raise last_error` (it is non-None there).
- Tests, on a **planned, owned** session (`_new_session` + `_install_vector_plan`):
  - `test_concurrent_identical_binds_on_a_planned_session_both_succeed` — both results are equal `CrewElasticTeamBinding`s; one stored value.
  - `test_concurrent_different_binds_on_a_planned_session_leave_one_binding` — exactly one winner; the loser is `ValueError("crew_session_team_binding_conflict")`; stored binding equals the winner.

### F3 — verify-on-read and corrected ownership claims (`crew_session.py` `get_team_binding`)

- After `_parse_team_binding(raw)`: if `self._team_spec_lookup is not None`, `spec = await lookup.get_team_spec(binding.team_spec_ref)`; `None`, or `(spec.team_id, spec.revision) != (binding.team_id, binding.revision)` → `logger.error("AD-1286: crew session parent=%s binding names team spec %s, which the lookup cannot confirm; refusing to return an unverifiable binding", …)` and `ValueError("crew_session_team_binding_invalid")`. Lookup errors (`ElasticTeamStoreUnavailable`, integrity) propagate. With no lookup bound, return the strictly parsed binding (document: "verified against the lookup when one is bound").
- Docstrings: `get_team_binding` and `bind_team_spec` must not claim exclusivity. The binding is **written by** `bind_team_spec`; the key is owner-protected only once a plan is installed.
- Tests:
  - `test_get_team_binding_refuses_a_binding_to_an_unknown_spec` and `…_with_mismatched_revision` — write the malformed-but-parseable binding the way `test_get_team_binding_rejects_a_malformed_stored_binding` already does (unplanned session, generic merge with the same expectations) → `crew_session_team_binding_invalid`.
  - `test_unplanned_crew_keys_accept_a_generic_merge_platform_property` — **documents** the pre-existing property (probe as in F3: an unplanned crew-session parent accepts a generic `merge_work_item_metadata` of `crew_elastic_team` **and** of `crew_session`'s own key name with an unchanged value; after a plan is installed the same merge raises `OwnedStepsError("owned_steps_write_reserved")`). Docstring: "pins today's platform property recorded in #1419; when that item is fixed, this test changes on purpose".

### F9 — corruption propagates (`finalize.py` `_wire_elastic_team_store`)

- Around `await store.start()`: `except sqlite3.DatabaseError as exc:` — if `isinstance(exc, sqlite3.OperationalError)`: the existing WARNING and `return False`; else `logger.error("AD-1286: %s is not a usable SQLite database (%s); refusing to start with a corrupt elastic team store -- move the file aside to recover", db_path, exc, exc_info=True)` and `raise`. Then the existing `except Exception:` WARNING-and-degrade for everything else. `import sqlite3` locally beside the other lazy imports.
- Tests (`tests/test_ad1286_wiring.py`): `test_corrupt_store_file_propagates_as_data_integrity` (write `b"not a database" * 100` to `tmp_path / "elastic_teams.db"`) → raises `sqlite3.DatabaseError` (not `OperationalError`), ERROR record contains `AD-1286`, `runtime.elastic_team_store` absent/None, lookup not bound. Keep `test_start_failure_degrades_and_leaves_binding_unavailable` (directory path → WARNING, False).

### S2 — publish only after the lookup is bound (`finalize.py`)

- After `await store.start()` succeeds: `try: service.bind_team_spec_lookup(store) except ValueError: logger.warning("AD-1286: the crew session service already has a team-spec lookup bound; closing the newly opened store so no second store is published", exc_info=True); await store.stop(); return False`. Only then `runtime.elastic_team_store = store; return True`.
- Test `test_rewiring_after_shutdown_closes_the_new_store_and_publishes_nothing` — wire, `_stop_runtime_sqlite_sidecars(runtime)`, wire again: returns False, a WARNING is logged, `runtime.elastic_team_store is None`, and the second store was stopped (its operations raise unavailable).

### Trackers (Section 6 corrections, R3)

Rewrite the staged AD-1286 DECISIONS entry's affected sentences to exactly this meaning (style as written):
- **Durable association (D3):** "It is written by `CrewSessionService.bind_team_spec` (no other production caller writes it) through the service's existing owned-metadata path, only while the session is `discussing` with no `crew_provisioning` marker. Ownership is exactly that of the CrewSession contract key itself: once a plan is installed, owned steps refuse any generic write; before that, the in-process `merge_work_item_metadata` primitive can write any `crew_*` key, `crew_session` included — a pre-existing platform property recorded in #1419. A spec that names a `plan_hash` binds only when the session's current recovery plan carries that hash. That is a bind-time admission check: a governed `replan_unstarted` can install a different plan later and leaves the binding unchanged, a repeat bind then reports `crew_session_team_plan_mismatch`, and AD-1288's commission admission must compare `spec.process.plan_hash` with the current plan. `get_team_binding` parses strictly and, when a lookup is bound, verifies that the referenced spec exists with the same team and revision." Delete "cannot go stale" and the "every other `crew_recovery` writer preserves the plan" clause.
- **Storage (D4):** add "The four tables are `WITHOUT ROWID`, so no implicit rowid can replace a row. Every instance is revalidated (`revalidate_instances="always"`) and the store revalidates what it is given before hashing or inserting. Admission loads and verifies the canonical spec inside the transaction, treats the slot row's cached columns as a projection that must match it, and requires existing ordinals to be exactly 1..n. A failed rollback closes the connection and marks the store unavailable, so no uncommitted row is ever readable. A corrupt database file fails startup (data integrity); ordinary unavailability degrades with a warning."
- **Boundary:** add "AD-1288 owns two checks this AD cannot make: session membership (`get_team_binding(session_id)` against the spec) and plan currency (`spec.process.plan_hash` against the current plan)."
- **Existing tests edited:** unchanged list (four files); add "after review round 1, the AD-1286 test files gained the repairs' regressions and two expected changes: the store's gap test now expects an integrity refusal, and the binding test formerly named `test_bound_plan_cannot_be_replaced` was renamed because a governed replan can replace the plan".
- **PROGRESS:** replace "with the plan hash cross-checked at bind time" by "with the plan hash checked at bind time (a governed replan can change the plan later; AD-1288 re-checks at commission)", replace the "twelve SQLite triggers …" clause by "`WITHOUT ROWID` tables behind twelve SQLite triggers …", add one sentence "Review round 1 (GPT-6.1 Sol) found 6 High and 3 Medium defects, all repaired here; the unplanned-session `crew_*` merge property is recorded in #1419.", and **re-measure every per-file count** after the repairs (the counts above are pre-repair).
- **Ledger:** after editing DECISIONS/PROGRESS, rerun `scripts/gen_ad_ledger.py --check`; regenerate (no `--online`) only if it fails, exactly as Section 6 step 4.

### Focused commands (Section 8)

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1286_elastic_team_contract.py tests/test_ad1286_elastic_team_store.py tests/test_ad1286_crew_session_team_binding.py tests/test_ad1286_wiring.py -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1132_crew_session_api.py tests/test_ad1192_owned_steps_execution.py tests/test_ad1124_crew_session_contract.py tests/test_ad1126_verified_finalization.py tests/test_ad1127_crew_session_lifecycle_recovery.py tests/test_ad1128_crew_session_ingress_dedup.py tests/test_ad1152_crew_token_usage.py tests/test_bf296_shutdown_phase_ordering.py tests/test_issue1419_failed_start_rollback.py -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1256_store_registry.py tests/test_ad1184_ad_ledger.py -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check
```

Expected test changes are exactly: `_read_tables` ordering (F1), the renamed gap test (F6), the renamed plan test (F2), and the tracker counts. Any other existing assertion that must change is a hard stop.

---

## Section 9: Review round 2 repairs (R4)

Round 2 (GPT-6.1 Sol, executed probes) closed F1, F2, F4, F6 (original cases), F7, F8 (original race), F9, S1 and S2, partially closed F3 and F5, and returned **BLOCKED** on 1 High + 3 Medium + 1 Low + one test-isolation Low. This section **explicitly authorises** amendments to: `src/probos/cognitive/elastic_team_store.py` (the connection mechanism and the verified-read paths named below), `src/probos/cognitive/elastic_team.py` (**one docstring only**, R2-5 — no field, validator, model config or identity change), `tests/test_ad1286_elastic_team_store.py`, `tests/test_ad1286_crew_session_team_binding.py` (one new consumer test), and the staged AD-1286 entries in `DECISIONS.md` / `PROGRESS.md`. Nothing else — in particular **no change** to `crew_session.py`, `finalize.py`, `shutdown.py`, `runtime.py`, any non-AD-1286 test, or any public method signature of `ElasticTeamStore`.

Order: R2-1/R2-2 (mechanism) → R2-3/R2-4 (verified reads) → R2-5 → test isolation → trackers. Execution brief step 0 first.

### Rulings

| ID | Ruling |
|---|---|
| R2-1 | **Confirmed, High.** `_abandon_transaction` (`elastic_team_store.py:367-399`) catches `Exception`, so a `CancelledError` delivered while `ROLLBACK` is awaited escapes with the shared connection still published and its transaction open; a consumer then reads the uncommitted spec through that same connection. Dangling write-once binding reproduced by the reviewer. |
| R2-2 | **Confirmed, Medium.** The quarantine clears `_db`, then awaits `db.close()` under `_lock` with no bound, discards the handle when close fails, and logs "the connection was closed" even then; `stop()` never retries. |
| R2-3 | **Confirmed, Medium.** `_load_verified_spec` (:248-251) verifies `canonical_json` only; `put_team_spec` (:424-430) decides revision conflicts from the unverified cached `team_id`/`revision`. |
| R2-4 | **Confirmed, Medium.** Five paths decide or acknowledge from rows the store itself refuses to read (list below). |
| R2-5 | **Confirmed, Low.** `elastic_team.py:402` claims exclusivity the platform does not provide (#1419 F-1). |
| Test isolation | **Confirmed, Low.** The rowid cases reuse an existing primary key, so a guard trigger — not the absence of an implicit rowid — produced the refusal. |
| Schedule | **Confirmed, Medium, pre-existing.** `routers/workforce.py` `update_work_item` (:299-304) maps only `crew_session_write_reserved` (:39-41) and re-raises every other `ValueError`; on a **planned** crew-session parent `_guard_owned_write` raises `OwnedStepsError("owned_steps_write_reserved")` first, so the PATCH returns **500**. Not an AD-1286 regression; filed to #1419 as F-2. The R3 sentence "the PATCH router returns 409" was wrong for planned parents and is corrected in §8. |

### R2-1 / R2-2 decision: per-operation connections (replace the mechanism)

| Rank | Option | Why |
|---|---|---|
| **1 (chosen)** | **B — one connection per operation.** Every public operation opens its own connection, does its work (writes inside `BEGIN IMMEDIATE` … `COMMIT`), and closes it. No connection is shared, published or quarantined. | The safety property becomes SQLite's own: **another connection never sees uncommitted rows**. A failed, cancelled or un-closable write cannot expose partial rows to any later operation, because every later operation uses a fresh connection. This removes the whole class R2-1 and R2-2 belong to, instead of patching the cleanup sequence a third time. The worst residue of a failed close is a leaked connection that still holds SQLite's write lock: later writes then wait `busy_timeout` (5 s) and fail with `sqlite3.OperationalError` ("database is locked") — fail-closed, and self-healing once the close completes. Precedent: `capability_request.py:1133-1141` opens a separate connection for exactly this reason ("A separate reader cannot mistake an uncommitted/failed decision on the writer connection for Captain authority"). |
| 2 | A — unpublish first, catch `BaseException`, shielded bounded close, `_retired` handles retried by `stop()`. | Correct if every step is sequenced right, but the invariant still rests on our cleanup ordering — exactly what failed in R1 (F5) and R2 (R2-1, R2-2). More bookkeeping, more states. |
| 3 | C — document and accept. | Not acceptable for a High. |

Cost of B: one connect/close per operation (low volume: spec writes, attempt records, binding lookups). The admission and trigger logic that two rounds verified is untouched — every helper already takes `db`.

**Specification (normative).**

- Module constants: `_CLOSE_WAIT_SECONDS = 5.0` (how long an operation waits for its own close before moving on), `_STOP_CLOSE_WAIT_SECONDS = 5.0` (how long `stop()` waits for outstanding closes). Tests may monkeypatch both.
- `__init__`: replace `self._db` with `self._started = False` and `self._closing: set[asyncio.Task[None]] = set()`. Keep `self._lock` (it still serialises in-process operations and lets `stop()` wait for in-flight work).
- New method `_connection(self) -> AsyncIterator[Any]`, decorated `@contextlib.asynccontextmanager`:
  1. If not `self._started` → `ElasticTeamStoreUnavailable("elastic_team_store_unavailable")` (no connection opened).
  2. `db = await self._connection_factory.connect(self._db_path)`.
  3. `try:` execute `PRAGMA busy_timeout=5000`, `PRAGMA synchronous=NORMAL`, `PRAGMA foreign_keys=ON` (all per-connection settings); `yield db`. `finally: await self._close(db)`.
- New method `_close(self, db: Any) -> None`: `task = asyncio.create_task(db.close())`; `self._closing.add(task)`; `task.add_done_callback(self._closing.discard)` and a done-callback that, if the task raised, logs ERROR "AD-1286: closing an elastic team connection failed (%s); any uncommitted work on it was never visible to other connections and is discarded when the connection is released, but it may hold the write lock until then, so later writes can fail as 'database is locked'" (retrieve the exception so it is not "never retrieved"). Then `done, _ = await asyncio.wait({task}, timeout=_CLOSE_WAIT_SECONDS)`; if not done, log ERROR "AD-1286: closing an elastic team connection did not finish within %.1fs; it stays tracked and stop() waits for it". `asyncio.wait` neither cancels the task on timeout nor when the awaiting caller is cancelled, so a cancelled operation still completes its close in the background (tracked in `_closing`). Never log that a connection "was closed" unless the task completed without an exception.
- Module helper `async _rollback(db: Any) -> None` (replaces `_abandon_transaction`): `await db.execute("ROLLBACK")`; `except asyncio.CancelledError: raise`; `except Exception as exc:` if `_is_no_transaction(exc)` → `logger.debug` (keep the existing "found no open transaction" wording — the existing fake-connection test keys on it); otherwise `logger.warning("AD-1286: rollback after a failed elastic team write also failed (%s); the connection is being closed, which discards the uncommitted work, and no other connection ever saw it", exc, exc_info=True)`. It never decides availability; the connection is discarded by `_connection`'s `finally` in every case.
- `start()`: under `_lock`: if already started return; set `self._started = True` **after** a probe succeeds: open with `self._connection_factory.connect` directly (not `_connection`, which requires started), execute `PRAGMA journal_mode=WAL` (persistent per file) and the three per-connection pragmas, `executescript(_SCHEMA)`, `commit()`, and close it through `self._close(db)` in `finally`. Any failure leaves `_started = False` and propagates (F9's corrupt-file `DatabaseError` still reaches `finalize.py` unchanged).
- `stop()`: under `_lock`: `was_started, self._started = self._started, False`. Then, **outside the lock**: if `self._closing`, `await asyncio.wait(set(self._closing), timeout=_STOP_CLOSE_WAIT_SECONDS)`; if any remain, log ERROR "AD-1286: %d elastic team connection(s) did not finish closing within %.1fs; they may hold the database write lock until they are released". Log the existing info line only if `was_started`. Docstring: "Stop admitting operations, wait for any in-flight one (it holds the lock), then wait a bounded time for outstanding connection closes. Idempotent."
- Every write (`put_team_spec`, `record_attempt`, `record_attempt_outcome`): `async with self._lock: async with self._connection() as db:` then the existing `try: BEGIN IMMEDIATE … commit` with `except BaseException: await _rollback(db); raise`. Every read (`get_team_spec`, `get_attempt`, `list_slot_attempts`, `get_attempt_outcome`): `async with self._lock: async with self._connection() as db:` — no `BEGIN`. Clock check (`_checked_now`) stays before opening the connection.
- Delete `_require` and `_abandon_transaction`. Class docstring: "one connection per operation, serialised in-process by one lock; uncommitted work is never visible to another operation".
- **Method budget:** removes `_require` and `_abandon_transaction`, adds `_connection` and `_close` → **13** methods (limit 15). Body lines must stay < 500; the verified-read helpers below are module-level.

### R2-3 / R2-4 decision: no decision or acknowledgement from an unverified row

| Rank | Option | Why |
|---|---|---|
| **1 (chosen)** | **A — funnel every read that admits, acknowledges or returns through a verified loader**, on this exact path list. | One principle, closed scope: the store never relies on an unverified stored row to *admit*, *acknowledge* or *return*. Relying on a row to *refuse* (fail closed) is allowed — so the `SELECT 1 … supersedes_attempt_id` already-replaced check stays as is. |
| 2 | B — catalog cross-check only, rest recorded as residual Medium. | Leaves acknowledged writes the store cannot read back. |
| 3 | C — neither. | — |

Module-level helpers (never take the lock; take `db` or a row):
- `_verified_spec_row(row) -> ElasticTeamSpec` for `row = (spec_ref, team_id, revision, schema_version, canonical_json)`: `spec = _verified_spec(row[4], row[0])`, then require `(row[1], row[2], row[3]) == (spec.team_id, spec.revision, spec.schema_version)`, else ERROR log + `ElasticTeamIntegrityError("elastic_team_spec_integrity")`.
- `_load_verified_spec(db, ref)`: select those five columns; `_verified_spec_row(row)` or `None`.
- `_verified_outcome(row) -> WorkerAttemptOutcome`: `_outcome_from_row(row)`; a `ValueError` (incl. `ValidationError`) → ERROR log + `ElasticTeamIntegrityError("elastic_attempt_outcome_integrity")` (**new code**).
- `_require_contiguous_ordinals(db, attempt)`: select `_ATTEMPT_COLUMNS` (not just `ordinal`), rebuild **each** row with `_attempt_from_row` (digest-verified, `elastic_attempt_integrity`), then the existing 1..n check.

The **closed path list** (each path, its read, its error):

| # | Path | Change | Error on an unverifiable row |
|---|---|---|---|
| 1 | `put_team_spec` existing-row and revision-conflict query | select the five catalog columns; verify **every** returned row with `_verified_spec_row` before comparing refs | `elastic_team_spec_integrity` |
| 2 | `get_team_spec` / `_load_verified_spec` (also used by admission) | catalog cross-check added | `elastic_team_spec_integrity` |
| 3 | `record_attempt` existing-row path | select `_ATTEMPT_COLUMNS`, `_attempt_from_row`, then compare digests (`elastic_attempt_conflict` unchanged) | `elastic_attempt_integrity` |
| 4 | `_require_contiguous_ordinals` | verify every history row's digest, then 1..n | `elastic_attempt_integrity` |
| 5 | `_admit_attempt` predecessor outcome read | select `_OUTCOME_COLUMNS`, `_verified_outcome` (predecessor already digest-verified) | `elastic_attempt_outcome_integrity` |
| 6 | `record_attempt_outcome` | the "known attempt" read selects `_ATTEMPT_COLUMNS` and runs `_attempt_from_row`; the existing-outcome read uses `_verified_outcome` | `elastic_attempt_integrity` / `elastic_attempt_outcome_integrity` |
| 7 | `get_attempt_outcome` | `_verified_outcome` instead of `_outcome_from_row` | `elastic_attempt_outcome_integrity` |

Idempotent branches still write nothing. `get_attempt` and `list_slot_attempts` are already verified. No other read in the store is in scope.

### R2-5 — docstring (`elastic_team.py`, `CrewElasticTeamBinding`)

Replace "Owned and written only by ``CrewSessionService.bind_team_spec``." with:

> Written by ``CrewSessionService.bind_team_spec``, its only production writer, which verifies the spec and the session state first. The key is protected by owned steps only once a plan is installed; before that, the platform's generic metadata merge can write it like any other ``crew_*`` key (#1419 F-1), which is why ``get_team_binding`` verifies what it returns.

This is the only change to `elastic_team.py`; the KAT literals cannot move.

### Tests (store unless noted)

New:
- `test_cancellation_during_rollback_never_exposes_uncommitted_rows` — a `ConnectionFactory` proxy over real aiosqlite whose connection fails the second slot `INSERT` and whose `ROLLBACK` awaits an `asyncio.Event`; start `put_team_spec` as a task, wait until the rollback is entered, `task.cancel()`; assert `CancelledError`; then `get_team_spec(ref)` is `None` (fresh connection), a raw snapshot has no spec or slot rows, and after the event is set and closes drain a new valid `put_team_spec` succeeds. Binding-test file: `test_cancelled_spec_write_cannot_be_bound` — the same proxy store bound as the lookup of a real `CrewSessionService`; after the cancelled put, `bind_team_spec` raises `crew_session_team_spec_not_found` and no `crew_elastic_team` is stored; after reopening the store, still not found.
- `test_close_failure_is_reported_and_never_exposes_uncommitted_rows` — a proxy whose `close()` raises **without** closing the real connection first (the test holds the real handle and closes it in `finally`), on a write that fails after `BEGIN IMMEDIATE` and a slot insert, with a rollback that also fails: the original error propagates; an ERROR record contains `closing an elastic team connection failed`; no record claims the connection "was closed"; a read on a fresh connection sees no partial rows.
- `test_stalled_close_bounds_the_operation_and_stop` — monkeypatch `_CLOSE_WAIT_SECONDS` and `_STOP_CLOSE_WAIT_SECONDS` to `0.05`; a proxy `close()` awaits an event: the operation returns within ~0.5 s, an ERROR "did not finish within" is logged, `stop()` returns within ~0.5 s and logs ERROR naming 1 outstanding close; then set the event and assert the tracked task completes and `_closing` empties.
- `test_catalog_columns_must_match_the_canonical_spec` — drop `elastic_team_specs_no_update`, change the cached `team_id` (and separately `revision`, `schema_version`) on a stored spec: `get_team_spec` and an identical `put_team_spec` both raise `elastic_team_spec_integrity`; reproduce R2-3 (a second raw row whose canonical model names the first spec's `(team_id, revision)` but whose catalog says otherwise): `get_team_spec` raises for that row.
- `test_identical_put_on_a_corrupt_spec_row_is_refused` (path 1), `test_identical_record_on_a_corrupt_attempt_row_is_refused` (path 3), `test_admission_refuses_a_history_row_with_a_bad_digest` (path 4: contiguous ordinals, one row's `attempt_digest` altered), `test_admission_refuses_a_malformed_predecessor_outcome` (path 5: predecessor outcome `terminal_status` changed to `'failed'` with a non-null `recorded_at` of type text, or an error code that violates the code pattern), `test_outcome_for_a_corrupt_attempt_is_refused` (path 6), `test_get_attempt_outcome_refuses_a_malformed_row` (path 7). Each asserts the snapshot is unchanged.
- `test_every_connection_gets_the_per_connection_pragmas` — a recording factory: every opened connection executed `busy_timeout`, `synchronous` and `foreign_keys` before any other statement; `journal_mode=WAL` and the schema only at `start()`.

**Expected changes to existing tests** (and only these):
- `test_failed_rollback_closes_the_connection_and_leaves_no_partial_rows` → rename to `test_failed_rollback_leaves_no_partial_rows_and_the_store_usable`: the original error still propagates and no partial rows are readable, but the store is **not** made unavailable — the next operation succeeds on a fresh connection.
- `test_start_applies_the_connection_pragmas_once_and_creates_the_schema` → pragmas are per connection now; assert `journal_mode=WAL` + schema at start and the per-connection pragmas on each connection (or fold into the new pragma test).
- `test_triggers_refuse_every_mutation_and_replacement_on_every_table` rowid cases (**test isolation**): use a primary key **and** every secondary unique key that collide with nothing stored (fresh `spec_ref` and `(team_id, revision)`; fresh attempt id, ordinal and `supersedes_attempt_id`; fresh slot `(spec_ref, slot_id)`; fresh outcome id with an existing attempt) plus an explicit `rowid`, so only the implicit-rowid route could fire. Keep asserting the refusal mentions `rowid` and the snapshot is unchanged; keep `test_every_table_is_without_rowid`.
- Any test that asserted `ElasticTeamStoreUnavailable` **because of a failed rollback** changes in the same way as the rename above. Tests that assert unavailability before `start()` / after `stop()` keep it.

### Focused commands (Section 9)

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1286_elastic_team_store.py tests/test_ad1286_crew_session_team_binding.py tests/test_ad1286_wiring.py tests/test_ad1286_elastic_team_contract.py -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_issue1419_failed_start_rollback.py tests/test_bf296_shutdown_phase_ordering.py tests/test_ad1127_crew_session_lifecycle_recovery.py tests/test_ad1132_crew_session_api.py -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1256_store_registry.py tests/test_ad1184_ad_ledger.py -q -n 0 -p no:randomly
d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check
```

### Termination criterion (record in DECISIONS "Boundary")

The third review round is limited to: (1) closure of R2-1 … R2-5 and the test-isolation Low; (2) regressions introduced by R4; (3) re-confirmation of the existing property list P1–P10. **Explicitly not hardened, and why:**
- **A process that can write the database file** (drop triggers, run DDL, rewrite rows, swap the file). The store's guarantee against it is *detection*, not prevention: every read that admits, acknowledges or returns verifies content identity and the catalog, and refuses with an integrity error. Preventing file-level writes is an OS/deployment control.
- **In-process code that bypasses the store** (monkeypatching, private attribute access, the platform's pre-plan generic merge — #1419 F-1). AD-1286 verifies on read; it does not sandbox the process it runs in.
- **Leaked connections after a failed or stalled close.** They are tracked and reported, never reused; their uncommitted work is invisible to every other connection. The residual effect (a held write lock until release) fails closed.
- **Storage-medium faults** beyond SQLite's own guarantees (power loss, disk corruption mid-write), cross-store atomicity with the work-item store, and **lifecycle checks owned by AD-1288** (session membership, plan currency at commission).
- Any new finding in round 3 outside items (1)–(3) is recorded in #1419 unless it is a security or data-integrity defect reachable **without** file-level write access or in-process bypass.

### Trackers (Section 6 corrections, R4)

Rewrite the staged DECISIONS AD-1286 entry's affected sentences to this meaning:
- **D3:** "a single key, `crew_elastic_team`, written once by `CrewSessionService.bind_team_spec`" (drop the unqualified "write-once key"; the key itself is not write-once against the pre-plan generic merge).
- **D4:** replace "A failed rollback closes the connection and marks the store unavailable, so no uncommitted row is ever readable." with: "Every operation uses its own connection, serialised in-process by one lock, so a failed, cancelled or un-closable write's uncommitted rows are never visible to any other operation; a connection whose close fails or stalls is tracked and reported, never reused, and `stop()` waits a bounded time for outstanding closes. The store never relies on an unverified stored row to admit, acknowledge or return: catalog columns must match the canonical spec, every attempt row in a history, an existing attempt and a predecessor are digest-verified, and outcomes are shape-verified."
- **Boundary:** append the termination criterion above (one paragraph), and replace "closed with the other SQLite sidecars" with "stopped with the other SQLite sidecars".
- **Existing tests edited:** append "after review round 2: the failed-rollback test now expects the store to stay usable (per-operation connections), the pragma test expects per-connection pragmas, and the rowid cases use keys that collide with nothing stored".
- **PROGRESS:** add "Review round 2 found 1 High and 3 Medium defects (cancellation and close failures around a shared connection; reads that trusted unverified rows), repaired by moving to one connection per operation and verified reads; the planned-parent PATCH 500 is recorded in #1419." Re-measure every per-file count after R4.
- Ledger: rerun `scripts/gen_ad_ledger.py --check` after the edits; regenerate (no `--online`) only if it fails.

---

## Tests (summary)

| Acceptance bullet (#1333) | Test |
|---|---|
| Typed contracts validate empty IDs, duplicate slots, bad capacity, bad profile refs, malformed policy/merge | contract #2, #7, #8, #9 |
| Canonical round-trip preserves every field; stable identity across restarts | contract #4, #10, #11; store #2 |
| Material change → new identity; runtime attempt state does not | contract #3, #5, #6 |
| CrewSession durably binds and recovers the exact ref, no blobs, accepted work unchanged | binding #1, #9 |
| Slot survives failed/replaced attempts; no overwrite (Python layer and SQLite boundary, incl. REPLACE) | store #6, #7, #8, #9, #11 |
| Default/no-team behaviour identical; AD-1072 unchanged | binding #2; wiring #1–#3; unchanged consumer files (Section 5 second command) |
| 14-key evidence and `SubtaskResult` not widened; one owner for the association | unchanged `test_ad1248`, `test_ad1155`, `test_ad1325`, `test_ad1152`; binding #1 (exactly one key added) |
| Happy, malformed/empty, round-trip, drift, restart recovery | all of the above |

No mutation campaign is required for this AD (no Critical/High behaviour, acceptance does not demand one). If the Diff Reviewer raises a test-validity concern, the Architect will name targeted mutants.

## What This Does NOT Change

`src/probos/crew_utils.py` (`CREW_EXECUTION_KEYS`); `SubtaskResult` (`crew_executor.py:1096-1110`); the bodies of `CrewSessionContract`, `CrewRecoveryContract`, `CrewRecoveryPlan`, `CrewRecoveryPlanChild`, `CrewSessionProvisioningContract`, `_WorkItemStoreProtocol`; `tests/fixtures/ad1152_agentic_off_golden.json`; `src/probos/workforce.py` (no change at all); any child work-item metadata; `src/probos/tools/delegate_task_tool.py` and the AD-1072 path; `src/probos/sop/*` (Bill schema/runtime); `src/probos/attachments/*` (incl. `ATTACHMENT_ORIGINS`); `src/probos/artifacts/*`; `src/probos/federation/*` (jcs is imported, not edited); `src/probos/events.py`; `src/probos/config.py` / `config_models/*` / `config/system.yaml`; `docs/development/seams/p0-manifest.yaml`; `docs/development/architecture-baseline.yaml`; `docs/development/store-baseline.yaml`; `CrewOrchestrator` / `CrewTaskExecutor` / `CrewSessionFinalizer` (no auto-binding).

## Do Not Build

- Worker provisioning, spawning, onboarding, or any attempt lifecycle phase (reserved/provisioning/active/draining) — AD-1288.
- Execution-profile digest **computation**, qualification evaluation or any qualification store — AD-1287.
- Ranking or choosing profiles/agents; any scheduler deciding which agent works (AD-1231 boundary).
- Mission blackboard storage or entry kinds — AD-1289.
- Scatter/gather, replica scaling, reducers or adjudication behaviour — AD-1290.
- Any UI, router, API endpoint or shell command.
- Any new `EventType`.
- Any new config field, flag or profile.
- Any change to the Bill schema or Bill runtime.
- Auto-binding from `CrewOrchestrator`, `open_or_resume` or provisioning; nothing calls `bind_team_spec` in production yet.
- Cross-store session-membership validation in the store (`ElasticTeamStore` does not check that `session_id` bound the spec; AD-1288's commission admission does, via `get_team_binding`).
- Any use of, reference to, or wording from commercial research material (`research/elastic-cognitive-teams.md` is in the private repo; this AD needs none of it).

## Footprint

| Path | Action |
|---|---|
| `src/probos/cognitive/elastic_team.py` | CREATE |
| `src/probos/cognitive/elastic_team_store.py` | CREATE |
| `src/probos/cognitive/crew_session.py` | MODIFY (3a–3d only) |
| `src/probos/cognitive/storage_declarations.py` | MODIFY (one declaration) |
| `src/probos/startup/finalize.py` | MODIFY (4a, 4b) |
| `src/probos/runtime.py` | MODIFY (4c, three lines) |
| `src/probos/startup/shutdown.py` | MODIFY (4d, one tuple row) |
| `tests/test_ad1286_elastic_team_contract.py` | CREATE |
| `tests/test_ad1286_elastic_team_store.py` | CREATE |
| `tests/test_ad1286_crew_session_team_binding.py` | CREATE |
| `tests/test_ad1286_wiring.py` | CREATE |
| `tests/test_ad1127_crew_session_lifecycle_recovery.py` | MODIFY (5a hook only) |
| `tests/test_ad1124_crew_session_contract.py`, `tests/test_ad1126_verified_finalization.py` | MODIFY (census pin only — §5c blocks verbatim) |
| `tests/test_layer_boundaries.py` | MODIFY (one documented exception only — §5d block verbatim) |
| (R3) `elastic_team.py`, `elastic_team_store.py`, `crew_session.py`, `finalize.py`, the four `tests/test_ad1286_*.py`, staged `DECISIONS.md`/`PROGRESS.md` | MODIFY **only** as §8 specifies. No new file; no other existing test file. |
| (R4) `elastic_team_store.py`, `elastic_team.py` (one docstring), `tests/test_ad1286_elastic_team_store.py`, `tests/test_ad1286_crew_session_team_binding.py`, staged `DECISIONS.md`/`PROGRESS.md` | MODIFY **only** as §9 specifies. No other file. |
| `DECISIONS.md`, `PROGRESS.md`, `docs/development/roadmap.md` | MODIFY (Section 6) |
| `docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json` | MODIFY **only** via `scripts/gen_ad_ledger.py`, **only** if `--check` demands it |

Anything else is out of footprint. Do not stage or commit (the orchestrator does, with explicit paths; never `git add -A`).

## Hard stops (return to the Architect through the orchestrator)

1. A **frozen-contract pin** would need to change: `crew_utils.py`, `SubtaskResult`, the `CrewSessionContract`/`CrewRecoveryContract`/`CrewRecoveryPlan` bodies, `ad1152_agentic_off_golden.json`, `test_ad1124`'s 27-key test, `test_ad1132`'s `_DETAIL_KEYS`, any `CREW_EXECUTION_KEYS` assertion. These are never edited. (R2) This is distinct from a **public-surface census pin** — the exact-`CrewSessionService`-API sets in `test_ad1124` (`test_public_service_api_and_annotations_are_exact`) and `test_ad1126` (`test_public_session_apis_and_finalizer_signature_are_fully_typed`) — which records intended API additions and is extended **only** by the §5c blocks; any other census edit is a hard stop.
2. `check_architecture_principles.py --check` or `check_store_registry.py --check` reports anything the footprint above does not resolve, i.e. a new baseline row would be needed. Never run `--update-baseline`.
3. The binding cannot be written without touching child metadata, `crew_session`, `crew_recovery`, or `workforce.py`.
4. Any existing test in the Section 5 consumer commands, or anywhere else, fails after your change and passes on the unmodified tree — **other than** the two census tests resolved by §5c and the layer test resolved by §5d (R2). Do not edit its assertions.
5. A Section 1 fix would change a field, type, error code, domain prefix, sort rule or the hashed projection.
6. `gen_ad_ledger.py` (non-`--online`) changes any file other than the two named, or `--check` still fails after regeneration.
7. An acceptance bullet cannot be met inside the footprint.
8. Slice fallback (only if one of the above blocks Sections 3–5): stop after Sections 1, 2, 6 (contracts and store only) and report. #1333 would then keep open the "CrewSession can durably bind and recover…" and "default CrewSession unchanged" bullets.
9. The import-root check (Execution brief step 0) prints a `probos.__file__` path that is not under the worktree.
10. (R3) §8 explicitly authorises the amendments it names to Sections 1, 2, 3 and 4 code and to the AD-1286 tests and staged trackers. **Anything outside §8 is still a hard stop**, including: any KAT literal moving (F4), `ElasticTeamStore` exceeding 15 direct methods or 500 body lines, a new public method on `CrewSessionService`, any change to `workforce.py` / `crew_orchestrator.py` / `work_item_steps.py`, or an existing test needing a change other than the three §8 names (`_read_tables` ordering, the renamed gap test, the renamed plan test).
11. (R4) §9 authorises only the amendments it names (the connection mechanism and the seven verified-read paths in `elastic_team_store.py`, one docstring in `elastic_team.py`, the named tests, the staged trackers). Hard stops include: any change to `crew_session.py`, `finalize.py`, `shutdown.py` or `runtime.py`; a public `ElasticTeamStore` signature change; more than 15 methods or ≥ 500 body lines; a KAT literal moving; an existing test needing a change other than those §9 lists; any read path outside the closed list of seven being changed.

## Acceptance Criteria

- Every #1333 acceptance bullet maps to a passing test in the table above.
- `elastic_team.py` and `elastic_team_store.py` import nothing from `crew_session`, `crew_executor`, `crew_orchestrator`, `workforce`; `probos.federation` is imported only lazily inside `canonicalize_projection`.
- A default runtime (crew sessions disabled) imports neither module, creates no `elastic_teams.db`, and logs no `AD-1286` line.
- A bound session loads, recovers, retries, finalizes and publishes; the binding survives unchanged; plan hash and child row hashes are unchanged.
- Specs/slots/attempts/outcomes are immutable at the SQLite boundary, not only in Python: the four tables are `WITHOUT ROWID` (R3) and twelve triggers abort every UPDATE, every DELETE and every INSERT that would replace an existing row (REPLACE / INSERT OR REPLACE, including through a secondary unique key), proven on a raw default-pragma connection (store test #6, including the rowid case), while a genuinely new row still inserts.
- ~~(R3) No uncommitted row is ever readable after a failed write: a failed rollback closes the connection and the store reports unavailable.~~ (R4) Every operation uses its own connection; no failed, cancelled or un-closable write's uncommitted rows are visible to any other operation (including through `CrewSessionService.bind_team_spec`); failed or stalled closes are tracked, reported and bounded, never reused; no log claims a close succeeded when it did not.
- (R4) The store never admits, acknowledges or returns from an unverified stored row on the seven listed paths; catalog columns must match the canonical spec.
- (R4) `CrewElasticTeamBinding`'s docstring names the designated writer, not an exclusive guard.
- (R3) Every incoming contract instance is revalidated (nested and top level); the four KAT literals are unchanged.
- (R3) Admission verifies the canonical spec, the slot cache against it, contiguous ordinals 1..n, and the predecessor's digest inside the transaction.
- (R3) The plan cross-check is a bind-time admission check; a governed replan leaves the binding unchanged and a repeat bind reports `crew_session_team_plan_mismatch`; no document claims the check cannot go stale or that the key is exclusive before a plan exists.
- (R3) Concurrent identical binds on a planned session both succeed; different ones leave exactly one binding.
- (R3) A corrupt `elastic_teams.db` fails startup with an ERROR; ordinary unavailability degrades with a WARNING; the store is published only after its lookup is bound.
- Architecture checker and store-registry checker pass with no baseline change; `tests/test_layer_boundaries.py` passes with exactly the one §5d exception added (R2); ledger check passes.
- All new public methods are fully typed; every log line states what, why and what next.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Report back (Builder)

First line: the `probos.__file__` path printed by Execution brief step 0 (must be under the worktree). Then, per section: files changed, the exact focused command run, and pass/fail/skip counts **per test file**; the two checker outputs; which ledger branch occurred; the three KAT literals and how they were computed; any hard stop hit. No full suite, no commit, no push.

---

## Verified Against Codebase (2026-10-10)

Worktree `ordinary-1333-20261010-c93399b8`, base `origin/main` @ `b7cecaba`. Commands are the searches actually run (Grep/Read tool calls shown as their `rg` equivalents).

```
rg -n "ElasticTeamSpec|WorkerSlot|WorkerAttempt"          (all tracked paths)  -> no hits
  control: rg -c "class CrewRecoveryPlan" src             -> crew_session.py:2
rg -n -i "elastic_team|worker_slot|worker_attempt" src tests -> no hits
rg -n '"crew_(team|elastic)\w*"' src                      -> no hits (control "crew_session" key probe: many hits)
python scripts/ad_ceiling.py                              -> CEILING AD-1325, NEXT AD-1326, exit 0
src/probos/sop/schema.py:86      class BillDefinition: (dataclass; bill: str, version: int = 1)
rg -i "bill" crew_session.py crew_orchestrator.py crew_executor.py -> no hits (control: class CrewSessionService found)
src/probos/cognitive/crew_session.py:3      from __future__ import annotations
  :18   from typing import TYPE_CHECKING, Any, Literal, Protocol, Self
  :20   from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator
  :39   if TYPE_CHECKING:
  :97   _STATUS_PROJECTION: dict[str, str] = {
  :170  _DISCUSSING_RECOVERY_PHASES = frozenset({"unplanned", "planned"})
  :432  class CrewRecoveryPlanChild(BaseModel):   :452 class CrewRecoveryPlan   :490 class CrewRecoveryContract
  :618  def _json_values_exactly_equal(current: Any, expected: Any) -> bool:
  :771  def _normalize_id(value: Any) -> str:
  :1817 class CrewSessionContract(BaseModel):
  :2072 def _validate_session_recovery_invariant(   ... :2095 raise ValueError("crew_session_recovery_state_conflict")
  :2098 class _WorkItemStoreProtocol(Protocol):
  :2342-2343 self._owned_legacy_authorizer / self._owned_view_authorizer = None
  :3225 async def _merge_owned_metadata(self, parent_id: str, patch: dict[str, Any], **kwargs: Any)
  :3261 def bind_worker_resolver(self, resolver: CrewSessionWorkerResolver) -> None:
  :5163/:5179 initialize_session reads only "crew_session"; idempotent via _initial_fields
  :5234 async def get_session   :5394 async def get_recovery   :5412 async def compare_and_set_recovery
  :5429 self._require_preserved_plan(expected_checkpoint, candidate)
  :5553 if _RECOVERY_PHASE_INDEX[base.phase] >= _RECOVERY_PHASE_INDEX["planned"]: raise crew_recovery_plan_conflict
  :5572 expected_parent_metadata=dict(metadata)     (install; adopt :5687 same)
  :5664 if "crew_recovery" in metadata: raise ValueError("crew_recovery_conflict")   (adopt)
  :5765 self._require_preserved_plan(expected_checkpoint, next_checkpoint)          (transition_session)
  :6138-6142 sibling_keys = every parent key except crew_session/crew_synth
  :6187-6188 expected_absent_keys=frozenset({"crew_synth"}), expected_present_keys=sibling_keys
  :6613 def _parse_contract   :6627 def _parse_recovery   :6891 async def _validate_loaded (reads crew_recovery only)
rg '"crew_recovery": [a-z_]+\.model_dump|_require_preserved_plan\(' src
  -> crew_session.py:4868, :5055, :5429, :5474, :5576, :5690, :5765, :6594 (all writers enumerated above)
src/probos/workforce.py:1626  _MAX_WORK_ITEM_METADATA_EXPECTED_KEYS = 1_024
  :1682 def _reject_reserved_metadata (scaffold flag, steps_control only)
  :5891-5894 canonical recovery hashes every non-runtime child metadata key
  :7626 raise ValueError("crew_session_write_reserved")   (create_work_item)
  :8319-8324 install: parent.metadata must equal expected_parent_metadata exactly
  :9090 async def merge_work_item_metadata(... expected_absent_keys, expected_present_keys ...)
  :9298 expected_absent_keys check -> "work_item_metadata_conflict"
  :9435 set(patch) != {"crew_session", "crew_recovery"}   (retry merge patch only)
  :9486-9487 retry merge requires plan unchanged
  :9563 retry barrier compares the whole parent metadata to its snapshot
src/probos/work_item_steps.py:266  def owned_metadata_key(key): key.startswith(("crew_", "steps_")) or ...
src/probos/crew_utils.py:38      CREW_EXECUTION_KEYS = frozenset({ ... 14 keys })
src/probos/cognitive/crew_executor.py:1096  class SubtaskResult:  (12 fields)
tests/test_ad1124_crew_session_contract.py:576  test_initialize_contract_has_exact_27_keys_and_server_times
tests/test_ad1155_loop_until_done.py:1204  len(fields(SubtaskResult)) == 12
tests/test_ad1325_boundaries.py:329      len(CREW_EXECUTION_KEYS) == 14
tests/test_ad1152_crew_token_usage.py:1230  SubtaskResult fields == golden (tests/fixtures/ad1152_agentic_off_golden.json)
src/probos/federation/ard/jcs.py:53      def canonicalize(value: object) -> bytes:   (pure stdlib, RFC 8785)
src/probos/identity_keys.py:215          from probos.federation.ard.jcs import canonicalize   (lazy-import precedent)
src/probos/federation/__init__.py:3-9    eager imports of transports/bridge (why the import must be lazy)
src/probos/__init__.py, src/probos/cognitive/__init__.py  -> docstring/version only
src/probos/protocols.py:325 class DatabaseConnection(Protocol)   :362 class ConnectionFactory(Protocol)
src/probos/storage/sqlite_factory.py:28  default_factory = SQLiteConnectionFactory()
src/probos/cognitive/standing_interest_store.py:99 _rollback_quietly  :125 __init__(db_path, connection_factory, clock)
  :145 self._lock = asyncio.Lock()  :146-150 lazy default_factory  :152 async def start  :179 async def stop
approval_authority.py:159/176, clearance_grants.py:62/73, decision_pre_clearance.py:346/363,
  continue_extension_permits.py:467/486, capability_request.py:681/693 -> persistent connection + start/stop
src/probos/startup/finalize.py:1981 def _wire_crew_session_service  :1983-1985 gated on orchestrator_enabled
  :2023 CrewSessionService(...)  :2041 def _wire_crew_orchestrator  :2120 bind_worker_resolver
  :3707 db_path = Path(runtime.data_dir) / "standing_interests.db"  :3714 await store.start()
  :3952-3953 if _wire_crew_session_service(...): logger.info("AD-1124: ...")   (inside async finalize; :3916 uses await)
src/probos/runtime.py:156 if TYPE_CHECKING:  :166 StandingInterestStore import  :495 annotation  :1081 init None
src/probos/startup/shutdown.py:297 async def _stop_runtime_sqlite_sidecars  :314 ("standing_interest_store", ...)
src/probos/cognitive/storage_declarations.py:117-140  StandingInterestStore declaration (template)
src/probos/storage/declarations.py:66 StoreCriticality  :78 StoreRetention (UNBOUNDED needs retention_note)
scripts/check_store_registry.py:15-20, :50-51  undeclared-store rule; --check / --update-baseline
scripts/check_architecture_principles.py:160-165 GATING_CATEGORIES  :187-188 SRP 500/15
  :558-569 counts direct FunctionDef/AsyncFunctionDef children (validators count)  :588 TYPE_CHECKING imports skipped
  :191-193 DB_CONNECT_CALLEES  :198-200 TASK_CREATE_CALLEES
docs/development/architecture-baseline.yaml:12-17 ranked layers  :469-473 CrewSessionService [lines, methods]
  :871-874 ProbOSRuntime [lines, methods]
tests/test_ad1127_crew_session_lifecycle_recovery.py:37-48 _VECTOR_* constants  :467 _new_session  :521 _vector_plan_payload
  :536 _vector_insert  :893-901 install vector plan  :2417 _durable_finalization_harness  :2452 _session_parent call
  :2542 _checkpoint_fault_finalizer  :2617 test_finalizer_durable_checkpoint_fault_resumes_exactly_once
tests/test_ad1125_room_bound_execution.py:323 stores fixture  :373 _session_parent  :430 _child
tests/test_ad1152_crew_token_usage.py:243 _planned_child  :280 _owned_merge  :577 retry-barrier test
tests/test_ad1130_outcome_only_room_trust.py:35  from tests.test_ad1126_verified_finalization import (   (cross-test import precedent)
tests/test_bf296_shutdown_phase_ordering.py:209  sidecar test uses MagicMock runtime (extra row is tolerated: stop failure is caught)
tests/test_issue1419_failed_start_rollback.py:1390-1451  pins shutdown steps(...) labels and helper calls, not the sidecar tuple
scripts/gen_ad_ledger.py:17-22, :30-32  --check re-renders from pinned snapshot + live DECISIONS/PROGRESS
docs/development/open-ads-report.md:41  issue snapshot 2026-08-29T05:45:15Z;  rg "AD-1286" open-ads-report.md -> no match
DECISIONS.md:11-13  "## Era V — Civilization (Phases 31-36)" then "### AD-1315 -- ..."
PROGRESS.md:1-3     "# ProbOS Progress" then bold status paragraph
docs/development/roadmap.md:526  | AD-1286 | Elastic Team Contract - immutable team specs, durable slots, ephemeral attempts | [#1333](...) | 1 |
```

### Absence Verified (2026-10-10)

```
CLAIM: no existing elastic-team / slot / attempt contract to reuse
RUN:   rg -n "ElasticTeamSpec|WorkerSlot|WorkerAttempt"; rg -i "elastic_team|worker_slot|worker_attempt" src tests;
       rg "class \w*(Slot|Attempt|Replica|Incarnation|TeamSpec|TeamRecipe|ExecutionProfile|Profile)\w*\b" src
FOUND: none for the first two; the third finds only unrelated classes (voice/appearance profiles,
       EffectAttemptView, OwnedEffectAttempt, _TerminalAttemptRecord, IssueAttempt, RecreationTurnAttempt)
HOLDS: yes (control probe for class CrewRecoveryPlan found)

CLAIM: nothing else writes a CrewSession plan after it is installed
RUN:   rg '"crew_recovery": [a-z_]+\.model_dump|_require_preserved_plan\(' src
FOUND: crew_session.py:4868, 5055, 5429, 5474, 5576, 5690, 5765, 6594 (+ publication patch :6134 derived from recovery)
HOLDS: yes -- install refuses >= planned, adopt refuses an existing recovery, CAS/transition preserve the plan,
       retry/ingress derive from current recovery and the store requires the plan unchanged (workforce.py:9486-9487)

CLAIM: nothing hashes or exact-compares the parent's whole metadata in a way the new key would break
RUN:   rg "(sha256|_plan_sha|owned_digest|json\.dumps)\(\s*(dict\()?(parent|item|updated)\.metadata" src;
       read install/adopt (crew_session.py:5572, :5687), publish (:6138-6188), retry barrier (workforce.py:9563)
FOUND: workforce.py:7693 is a persistence write, not a hash; install/adopt/retry compare against a fresh
       re-read of the whole metadata (so they include the binding); publish lists it as expected_present
HOLDS: yes -- and Section 5 tests 3 and 4 prove it empirically rather than by reading
```

### Could not verify (stated, not assumed)

- `gen_ad_ledger.py --check` could not be run in this session (tool call denied). Section 6 step 4 therefore makes the Builder run it and branch on the result.
- The known-answer digest literals are not computed here (no scratch execution available); the Builder computes them with the independent encoder (contract test #10), never with the module under test.
- Exact pydantic-core behaviour of `Annotated[Literal[1], ...]` with a `BeforeValidator(...)` under `strict=True` was not executed; the nested-model-from-dict pattern is proven by the `CrewRecoveryContract.plan` precedent. Contract tests #2/#4 will surface any mechanics issue (fixable per Section 1's rule).

---

## Execution brief (highest-risk constraints, restated)

0. **Import root first (R1).** The shared venv's editable install points at the main checkout (`D:\ProbOS\.venv\Lib\site-packages\__editable__.probos-0.1.0.pth` → `D:\ProbOS\src`), so in a git worktree pytest otherwise imports `D:\ProbOS\src` and tests stale code. Before **any** pytest or script command, in the same shell session:
   ```
   $env:PYTHONPATH = "<absolute worktree path>\src"
   d:/ProbOS/.venv/Scripts/python.exe -c "import probos, sys; print(probos.__file__)"   # must print a path under the worktree
   ```
   Paste the printed path as the first line of your report. If it is not under the worktree, stop (hard stop 9). The subprocess tests in Sections 1 and 4 pass `os.environ` through, so they follow the same root when `PYTHONPATH` is set, and use the editable install in CI where it is not. (`scripts/run_test_gate.py` sets `PYTHONPATH` and asserts the import root itself; focused runs do not.)
1. **Order:** Section 1 → 2 → 3 → 4 → 5 → 6, checkers (Section 7) after every `src/` section. Focused tests only; report per-file counts. No full suite, no commit, no push.
2. **Never write child metadata, `crew_session`, or `crew_recovery`.** The only new durable write AD-1286's code makes is the parent's `crew_elastic_team` key through `_merge_owned_metadata`. (R3: that is what this code writes, not exclusivity — before a plan exists the platform's generic merge can write any `crew_*` key; see §8 F3.)
3. **Frozen contracts are untouched:** `crew_utils.py`, `SubtaskResult`, `CrewSessionContract`/`CrewRecoveryContract`/`CrewRecoveryPlan` bodies, `workforce.py`. If any of their pins fails, stop. (R2) Two kinds of pin: a **frozen-contract pin** (27-key contract, 14-key `CREW_EXECUTION_KEYS`, `SubtaskResult`, the ad1152 golden, `_DETAIL_KEYS`) is never edited; a **public-surface census pin** (the exact `CrewSessionService` API sets in ad1124/ad1126) is extended only by the §5c blocks, applied verbatim. The only other existing-test edits allowed are the §5a harness hook and the §5d layer exception.
4. **Default-off is byte-identical:** the only new boot-path statement is inside `if _wire_crew_session_service(...)`; both new modules are imported only inside functions or under `TYPE_CHECKING`. Wiring test #1 proves it in a subprocess.
5. **Identity bytes are law:** do not change the domain prefixes, field sets, sort/dedupe rules or the projection. KAT literals come from the independent encoder only.
6. **Immutability lives in SQLite:** `WITHOUT ROWID` tables (R3), the twelve triggers (eight UPDATE/DELETE guards plus four `*_no_replace` BEFORE INSERT guards) and the FK/UNIQUE constraints are required; `PRAGMA foreign_keys=ON` at `start()`. Never rely on `recursive_triggers`. The store issues plain `INSERT` only, after its explicit reads — never `INSERT OR REPLACE`, `REPLACE INTO`, `INSERT OR IGNORE` or `ON CONFLICT`.
7. **Never run `--update-baseline`** on `check_architecture_principles.py` or `check_store_registry.py`. Keep every class ≤ 15 direct methods (validators count).
8. **Tests use `tmp_path` only** (BF-883); no live data directory, no `config/system.yaml`.
9. **Ledger:** regenerate `open-ads-report.md`/`ad-ledger-snapshot.json` only if `gen_ad_ledger.py --check` fails after the tracker edits, and only without `--online`.
10. **Diff Reviewer consumers to brief** (properties to verify): `CrewSessionService` reload (`get_session`/`get_recovery`/`get_team_binding`), recovery CAS, plan install/adopt, retry barrier and `publish_verified_result` all accept a parent carrying `crew_elastic_team`; the real `WorkItemStore.merge_work_item_metadata` CAS refuses a second, different binding; the SQLite triggers refuse UPDATE, DELETE and any replacing INSERT (REPLACE / INSERT OR REPLACE, including through a secondary unique key) on all four tables on a raw default-pragma connection, while a new row still inserts; the store never issues a conflict clause; `ElasticTeamStore` admission refuses gaps, overruns, unpinned profiles and double replacement; the architecture and store-registry checkers pass without baseline edits; the AD ledger check passes; a default runtime imports and opens nothing new.
11. **(R3) Review round 1 repairs:** apply §8 in its stated order (F1 → F4 → F5 → F8 → F6 → F2 → S1 → F7 → F3 → F9 → S2 → trackers). The KAT literals must not move. `ElasticTeamStore` ≤ 15 methods / < 500 body lines (expected 13); new helpers module-level and taking `db`, never a public lock-taking getter inside a locked section. No `workforce.py`/`crew_orchestrator.py` change, no new `CrewSessionService` public method. Re-measure every per-file count before writing PROGRESS. For the second Diff Reviewer round, add these properties to brief #10: rowid replacement refused; nested and top-level invalid instances refused with identities unchanged; a failed rollback leaves nothing readable and the store unavailable; admission refuses orphan slots, cache drift, gaps and tampered predecessors; a governed replan leaves the binding and a re-bind reports the mismatch; planned-session concurrent binds are idempotent/single-winner; `get_team_binding` refuses an unverifiable binding when a lookup is bound; corrupt file propagates, unavailable path degrades; re-wiring publishes nothing.
12. **(R4) Review round 2 repairs:** apply §9 in its order. The connection mechanism is **replaced** (one connection per operation), not patched; delete `_require` and `_abandon_transaction`. Verified reads apply to the closed list of seven paths and no others. Expected method count 13, < 500 body lines. For the third Diff Reviewer round, brief **only** the §9 termination scope: closure of R2-1…R2-5 and the rowid test isolation, regressions from R4, and re-confirmation of P1–P10; state the explicitly-not-hardened classes in the brief so out-of-scope observations go to #1419.

---

## Revision log (R1, 2026-10-10)

- **R1-1 (defect).** REPLACE / INSERT OR REPLACE deleted and replaced rows without firing DELETE triggers (`recursive_triggers` is OFF by default), so "immutable at the SQLite boundary" was false. Added four `*_no_replace` BEFORE INSERT guard triggers to `_SCHEMA` (twelve triggers total); the store issues plain INSERTs only after explicit reads and never a conflict clause; idempotent branches write nothing. Updated: Solution table, store docstring, `_SCHEMA`, Section 2b write-discipline paragraph, 2c `retention_note`, store test #6 (every table × UPDATE / DELETE / INSERT OR REPLACE / secondary-key REPLACE / ON CONFLICT DO UPDATE on a raw default-pragma connection, plus a new-row negative control), test-summary row, DECISIONS "Storage" bullet, Acceptance Criteria, Execution brief #6 and #10. Measurement of the bypass and of the guard SQL is the orchestrator's (SQLite 3.50.4), not re-run by the Architect.
- **R1-2 (gap).** Documented that `ElasticTeamStore` does not validate session membership and that AD-1288's commission admission must check `get_team_binding(session_id)`: store docstring, DECISIONS "Boundary" bullet, Do Not Build. No code or test change.
- **R1-3 (gap).** Added Execution brief step 0 (set `PYTHONPATH` to the worktree `src` and print `probos.__file__`), a matching first line in "Report back", and hard stop 9 (import root not under the worktree).

## Revision log (R2, 2026-10-10) — Builder hard stop 4 triage

Trigger: M2 stopped at hard stop 4; the orchestrator's 96-file consumer sweep found 3 failures (6,888 passed, 2 skipped), each passing on the unmodified tree.

- **R2-1 (census pins).** `test_ad1124::test_public_service_api_and_annotations_are_exact` and `test_ad1126::test_public_session_apis_and_finalizer_signature_are_fully_typed` pin the exact public surface of `CrewSessionService`; R0 missed them. Ranked: **A** extend the existing admitted sets under an `# AD-1286:` comment (ad1124 count 25 → 28; its existing loop annotation-checks the new methods) — **chosen**; B separate set + extra loop — rejected (convention break, no gain); C no public growth — impossible (AD-1288 needs `bind_team_spec`; `get_team_binding` is the read API; the lookup binder mirrors `bind_worker_resolver`). New §5c with verbatim SEARCH/REPLACE blocks. Hard stops 1 and 4 and Execution brief #3 now distinguish frozen-contract pins (never edited) from public-surface census pins (extended only by §5c). Footprint adds both files as `MODIFY (census pin only)`.
- **R2-2 (layer boundary).** `tests/test_layer_boundaries.py` (AD-400; own `LAYER_MAP`, function-level imports included) flags `cognitive/elastic_team.py:63 → probos.federation.ard.jcs`; re-measured by the Architect on this worktree: 1 failed / 2 passed, that single finding. Ranked: **A** documented `ALLOWED_EXCEPTIONS` entry following the `capability_triage.py → federation.ard.adoption` precedent — **chosen** (no source or identity-byte change); B layer-neutral wrapper module or widened `identity_keys.canonical_bytes` — rejected (new module/source edit to launder the same dependency, or an out-of-footprint contract change; `canonical_bytes` takes a `Mapping` only); C private canonicaliser — rejected (D2 rank 2, rewrites Section 1, another ad-hoc site). New §5d; Section 7 adds the layer test; Footprint adds the file as `MODIFY (one documented exception only)`. No other new import can trip it (`startup/*` unmapped, `runtime.py` core, `probos.protocols` core, `probos.storage` unmapped, same-layer `cognitive` imports).
- **R2-3 (deviation rulings).**
  1. *Accepted — code is normative.* Contract test #2 prose corrected: a malformed set element raises the **item** code (`elastic_team_ref_invalid` / `elastic_team_scope_invalid` / `elastic_team_id_invalid`); `*_set_invalid` is for container faults only (not a list/tuple, > 32 items, duplicates). `elastic_team.py` unchanged.
  2. *Accepted, all.* `record_attempt_outcome` → `TypeError("elastic_attempt_outcome_type_invalid")`; `get_attempt`/`get_attempt_outcome` → `ValueError("elastic_attempt_query_invalid")` on a malformed id; a corrupt stored pinned-profile list → `ElasticTeamIntegrityError("elastic_team_spec_integrity")`, nothing written (data-integrity tier: propagate); `_checked_now` accepts `int` as well as `float` (must still reject `bool` and non-finite values and return `float`); `get_team_spec` also catches `TypeError` while verifying; `start()` under the lock; `stop()` logs at info (runs only when the store was wired, so no default-runtime log line); module-level `_query`/`_is_query_id`; `_attempt_from_row` owns the digest check (DRY). 12 methods / 409 body lines are inside the 15 / 500 triggers.
  3. *Accepted.* Extra tests stay inside the footprint test files. The negative control as a sibling test satisfies R1's test-#6 requirement. The Builder's reported 100% line/branch coverage and mutant kills (12/12 triggers, 33/33 store, 33/33 contract) are recorded as the Builder's evidence; the Architect did not re-run them. Treat it as the campaign of record for the M1 files only if the Builder's report carries the base tree and each file's sha256; otherwise it is supporting evidence, not a campaign of record.
  4. *Accepted.* The seven extra M2 tests (lookup refuses `None` and a second binding; unknown/uninitialised parents; four fail-closed cases; wired store is the bound lookup; missing service degrades).
  5. *Accepted.* Real provisioning path for binding test 6 (stronger than the permitted skip); `revision=2` for the plan-hash specs (required by the `(team_id, revision)` uniqueness rule); test 9 with a different valid plan via `_build_derived_recovery_plan` (proves replacement is refused, not merely re-install idempotence); wiring test 2 with `SimpleNamespace(data_dir=tmp_path)` (makes the no-file assertion falsifiable); test 4 round trip. The extra private test imports are cross-test reuse within the stated precedent.
  6. Counts noted (binding 27, wiring 9, contract 131, store 110); final per-file counts go in the Builder report and PROGRESS.
- **R2-4 (remaining work).** Builder applies §5c and §5d verbatim, runs the §5c/§5d focused command and the Section 7 commands (now including the layer test), then Section 6. Section 6 changes only by adding the "Existing tests edited" bullet to DECISIONS and the matching sentence in PROGRESS; the ledger procedure is unchanged.

## Revision log (R3, 2026-10-10) — Diff Reviewer round 1 (BLOCKED: 6 High, 3 Medium, 2 small)

- New **Section 8** with per-finding rulings, ranked decisions, files/symbols, tests and focused commands. F1, F2, F4, F5, F6 confirmed High; F7, F8, F9 confirmed Medium; F3 reclassified as a pre-existing platform property (Medium) and filed to #1419; S1, S2 applied.
- Corrected in place: §"Problem" owner-protection bullet; §3 intro sentence; §"Plan cross-check semantics" marked SUPERSEDED with the real writer cited; Section 6 pointer to §8 trackers; Footprint R3 row; Hard stop 10; Acceptance (seven R3 bullets); Execution brief #2, #6, #11. The §3d code block is left as the historical R0 spec; §8 F2/F3/S1/F7 define the current `bind_team_spec`/`get_team_binding` bodies.
- Method budget raised from "at most 12" to the checker's real triggers (≤ 15 methods, < 500 body lines); expected 13.

### Claim re-audit (R3) — wide enumerations, run 2026-10-10 on the staged tree

| Claim (where it appeared) | Command | Result | Holds? / correction |
|---|---|---|---|
| "every other `crew_recovery` writer preserves the plan" / "cannot go stale" (§3d docstring, §plan semantics, DECISIONS D3, PROGRESS) | Grep `"crew_recovery"\s*:\|\["crew_recovery"\]\s*=\|canonical_metadata_patch` over `src/`; Grep `"plan"\s*:` over `src/probos` | Writers: `crew_session.py` (CAS, install, adopt, retry, ingress, transition, publish) **plus** `crew_orchestrator.py:2646/2660` (new plan) applied by `workforce.py:5588-5589/5623-5630` | **FALSE** → §8 F2 |
| "the `crew_` prefix is owner-protected" (§Problem, D3 rationale) | `_guard_owned_write` early return (`workforce.py:5866-5868`); orchestrator's probe of an unplanned parent | Unplanned: generic merge accepts every `crew_*` key; planned: refused | **FALSE before a plan** → §8 F3 |
| "written only by `bind_team_spec`" (DECISIONS D3) | Grep `crew_elastic_team\|CREW_ELASTIC_TEAM_METADATA_KEY` over `src/` | Only `crew_session.py` (bind/get/parse) and `elastic_team.py` (constant, docstring) | Holds for **production callers**; not exclusive (F3) — reworded |
| "nothing calls `bind_team_spec` in production" | Grep `bind_team_spec\(\|bind_team_spec_lookup\(\|get_team_binding\(` over `src/` | Definitions only, plus `finalize.py:2075` (`bind_team_spec_lookup`) and a docstring mention | **Holds** |
| "the store issues plain INSERTs only" | Grep `OR REPLACE\|OR IGNORE\|ON CONFLICT\|REPLACE INTO\|UPDATE \|DELETE ` in `elastic_team_store.py` | Only the module docstring and trigger DDL | **Holds** |
| "no caller depends on `rowid`" (new in R3) | Grep `rowid\|ROWID` over `src/probos/cognitive/elastic_team*.py` and `tests/test_ad1286_*.py` | `tests/test_ad1286_elastic_team_store.py:134` `ORDER BY rowid` | **FALSE** → §8 F1 expected change |
| "no other new import can trip the layer test" (§5d) | `pytest tests/test_layer_boundaries.py` on the staged tree | 3 passed | **Holds** (measured) |
| "store never shipped, so no migration" (new in R3) | `git log origin/main --oneline -- src/probos/cognitive/elastic_team_store.py` (control: same on `crew_session.py` → `0debd77b`) | no output | **Holds** |
| "an attempt is admitted only for a declared slot of a stored spec" (§2b docstring, DECISIONS D4) | Read `_admit_attempt` (`elastic_team_store.py:461-517`) | No spec-row check; cache trusted; `COUNT(*)+1` | **FALSE until §8 F6** |
| "immutable at the SQLite boundary" (Acceptance, D4, PROGRESS) | Orchestrator's execution against `_SCHEMA` | rowid replacement accepted | **FALSE until §8 F1** |
| "so no accepted work can exist" (§3d docstring) | not enumerable from the binding's preconditions (discussing sessions can adopt existing children) | — | **Withdrawn** → "the session has not started executing" |
| "`workforce.py`/`events.py`/`sop/*`/AD-1072 untouched" | `git diff --cached --stat` | none of these paths in the 21 staged files | **Holds** |
| "a default runtime imports/opens/logs nothing new" | reviewer's real default-runtime probe (P6) | held | Holds (reviewer evidence; not re-run by the Architect) |
| "27 / 14 / 12 frozen contracts unchanged" | reviewer P7 | held | Holds (reviewer evidence) |

## Revision log (R4, 2026-10-11) — Diff Reviewer round 2 (BLOCKED: 1 High, 3 Medium, 1 Low + test-isolation Low)

- New **Section 9**. R2-1 (High) and R2-2, R2-3, R2-4 (Medium) confirmed; R2-5 and the rowid test isolation (Low) confirmed; the planned-parent PATCH 500 confirmed as pre-existing and filed to #1419 F-2.
- **Mechanism replaced:** one connection per operation (B), ranked over the shared-connection quarantine (A) because the safety property becomes SQLite's isolation rather than our cleanup sequencing, the part that failed in R1 (F5) and R2 (R2-1, R2-2). §8 F5 marked SUPERSEDED.
- **Verified reads** on a closed list of seven paths; principle: never admit, acknowledge or return from an unverified row (refusing on one is fine).
- **Termination criterion** for round 3 written into §9 and the DECISIONS Boundary bullet.
- Corrected: §8 F3 ruling "the PATCH router returns 409" → 409 for unplanned parents only, 500 for planned; Footprint R4 row; Hard stop 11; Acceptance (R3 rollback bullet struck, three R4 bullets); Execution brief #12.

### Claim re-audit (R4) — cleanup, ownership, closure and "never/always/only" sentences

| Claim (location) | Checked by | Result | Action |
|---|---|---|---|
| "Owned and written only by ``CrewSessionService.bind_team_spec``" (`elastic_team.py:402`) | Grep `only\|never\|always\|exclusive` in `elastic_team.py`; #1419 F-1 evidence | **FALSE** (pre-plan generic merge) | §9 R2-5 rewording |
| "it never raises (only ``CancelledError`` from ``close`` propagates)" (`_abandon_transaction`, `elastic_team_store.py:370-371`) | Read `:367-399` | **FALSE**: `except Exception` lets a `CancelledError` from ROLLBACK escape before any close | method deleted (§9) |
| "the connection was closed so the uncommitted rows cannot be read" (ERROR log, `:395`) | Read `:385-399` | **FALSE** when `close()` failed (logged after a swallowed close failure) | log deleted; new logs claim closure only on success |
| "Taking the lock is what keeps a write that is mid-transaction from having its connection closed underneath it" (`stop()`, `:345-349`) | Read `:344-359` | True for `stop()` itself, but `_abandon_transaction` closed connections under the lock without bound (R2-2) | `stop()` rewritten (§9) |
| "one persistent connection, serialised by one lock" (class docstring, `:279`) | Read `:275-291` | True today; changes with §9 | docstring rewritten |
| "integrity-verified" reads (`get_team_spec` docstring, class docstring) | Read `_load_verified_spec` `:248-251`, `put_team_spec` `:424-430` | **Incomplete**: catalog columns unverified (R2-3); five decision/ack paths unverified (R2-4) | §9 paths 1-7 |
| "re-verified against its content identity on every read" (staged DECISIONS D4) | same | **Incomplete** until §9 | D4 rewritten |
| "A failed rollback closes the connection and marks the store unavailable, so no uncommitted row is ever readable" (staged DECISIONS D4; §8 F5; R3 Acceptance) | reviewer R2-1/R2-2 probes; Read `:367-399` | **FALSE** (cancellation; failed close) | replaced by §9 wording; R3 Acceptance bullet struck |
| "a single write-once key" (staged DECISIONS D3) | #1419 F-1 | Write-once **through `bind_team_spec`** only | D3 rewording (§9 trackers) |
| `bind_team_spec` docstring "Write-once, parent row only" (`crew_session.py`) | Read staged diff | Holds for what the method writes; the docstring already says "This method is the writer of the key, not its guard" | no change (crew_session.py is out of §9 footprint) |
| `get_team_binding` docstring (verify-when-bound; "owner-protected only once a plan is installed") | Read staged diff | Holds | none |
| bind log "the binding is write-once and changes no accepted work" (`crew_session.py`) | Read staged diff | "changes no accepted work" holds (parent key only); "write-once" holds for this method's own writes | none (recorded) |
| finalize docstring "never imports, opens or logs this" / "published only after the service has accepted it" (`finalize.py:2041-2050`) | Read `:2041-2100`; reviewer P6 | Holds | none |
| "the PATCH router returns 409" (§8 F3 ruling) | Read `routers/workforce.py:39-41, :299-304`; `_guard_owned_write` precedes the reserved check in `update_work_item` (`workforce.py:8741-8747`) | **FALSE for planned parents** (500) | corrected in §8 |
| "importing the module never imports the federation package" (`elastic_team.py:10`) | contract test #12(b) (green in the author's run) | Holds | none |
| "the store issues plain INSERTs only" | R3 Grep, unchanged code paths | Holds | none |

## Revision log (orchestrator, 2026-10-11) — wording-only edit for the phantom-API precheck

Not an Architect revision: the provenance line covers R1-R4 only. The staged-candidate preflight (`run_test_gate.py --preflight-only`) runs `scripts/phantom-api-precheck.ps1` on every staged prompt and flagged nine symbols. All nine were third-party or stdlib names (pydantic `BeforeValidator`, `ConfigDict`, `model_validate`, `model_fields`; `types.SimpleNamespace`) or the pseudocode `RFC8785(`; none is a probos symbol, and the script's AST helper (probos classes, kwargs, methods) reported nothing. Markup-only edits to nine lines, no technical content changed:

- The Section 1 module listing and the Section 3b `_parse_team_binding` replacement carry the fence tag `python3` instead of `python`; the script scans only `python` and `py` fences. The shipped `elastic_team.py` and `crew_session.py` and their tests, not this precheck, are what verify that code now.
- The header identity line, Section 1 test 4, Section 4 wiring test 2, the three Section 8 F4 bullets and one "could not verify" bullet re-split their inline spans so each call shape stands alone in its own backticks (`RFC8785(` written in lower case as pseudocode). Same meaning.
