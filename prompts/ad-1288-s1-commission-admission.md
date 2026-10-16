# AD-1288 S1 -- Commission admission: owner-named worker attempts admitted against the frozen team spec

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-14
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-15, base 52dcbfa7

**Status:** Ready for build (slice S1 of AD-1288, #1335; epic #1332). No new AD or BF number: AD-1288 is allocated.
**Base:** origin/main `52dcbfa7` (AD-1287 S3, `f66cced7`, PR #1539, is on it; see Absence Verified A5).
**Dependencies:** AD-1286 (shipped), AD-1287 S1, S2a, S2b, S3 (on main). S3's `learn_attempt_outcome` is not called; it learns nothing from a released attempt (`cancelled` is not evidence, `profile_qualification_store.py:1178-1185`).
**Estimated tests:** about 70 new (three files), one existing test changed deliberately (AD-1287 S1 test #16).

One-line summary: a deterministic `ElasticCommissionService` lets a CrewSession's process owner reserve, replace and release exact worker attempts, admitting each against the frozen spec, the session binding, the current plan, slot capacity, budget, qualification, currency and independence before anything is written. It provisions nothing and is not wired.

**Revision 2026-10-15 (base `d936fc24` -> `52dcbfa7`, 68 commits).** Re-verified every claim. What drifted: (1) line numbers only, in `profile_qualification_store.py` (AD-1287 S3, BF-890, BF-892), `DECISIONS.md`, `finalize.py`, `authority.py`, `runtime.py` and one census test; no signature, exception or return type that Section 1 uses changed, so **Section 1, Sections 2-4 and the mutation table are unchanged** and every SEARCH still occurs exactly once. (2) S3 landed: A5 now records it as on the base; S3's outcome learning treats `cancelled` as not evidence, which adds one clause to O-S1-1 (S2 must not end a provisioned attempt as `released_by_owner`, or a failure would escape learning) and one to D6. (3) The test briefs named the wrong source module for `_Clock`, `_started`, `_evaluation` and `_profile`, and forbade importing helpers although the AD-1287 tests import them across modules (`tests/test_ad1287_s2a_profile_currency.py:48-51`); the Tests rules and briefs M2 and M3 now name the real modules, allow those imports, and warn that the KAT `review` slot holds capacity 1. (4) Two new tests scan `src/` and `tests/` (BF-892 launch guard, standing-orders layout); both are added to Hidden Pins and neither meets the new files. (5) Obligations now name the slice that carries each of O-4 and R-1..R-6. (6) Tracker dates move to 2026-10-15; Prior Art links are now the canonical kubernetes.io pages, re-fetched. No decision D1-D9 lost its premise.

**Addition after review round 1 (orchestrator, 2026-10-15; no design or source change).** The GPT-6.1 Sol Diff Reviewer found that no test varied `model.provider` in the `distinct_models` key (F1, P2, ordinary reach): mutant C29 survived all 152 tests. M2 #7 now has a `[provider]` case and the table gained row C29, which that case kills. F2 (P2, reached only by injected faults, not a regression) is recorded as F-87 on #1523 and carried as O-S1-5 to S2 on the Architect's decision.

---

## Problem

#1335 needs one lifecycle owner through which a persistent process-owner agent commissions temporary workers from an immutable team spec. Today the pieces exist and nothing joins them:

- `ElasticTeamStore.record_attempt` (`src/probos/cognitive/elastic_team_store.py:625`) admits an attempt only by slot, budget (`max_attempts`), contiguous ordinal, pinned profile and predecessor rules (`_admit_attempt`, `:692-765`). It does **not** enforce `capacity.maximum` over live attempts, session membership or plan currency; AD-1286 handed the last two to AD-1288 (`DECISIONS.md:319`, `:325`; `crew_session.py:3296-3297`, `:3341-3343`).
- AD-1287's gate `admit_current_qualified_attempt` (`profile_currency.py:199`) is the amended O-1 boundary; nothing calls it (`DECISIONS.md:192`; S1 test #16, `tests/test_ad1287_slot_qualification.py:714`).
- `CrewSessionService` exposes the facts admission needs through public reads: `get_session` (`crew_session.py:5415`), `get_recovery` (`:5575`), `get_team_binding` (`:3288`) and `worker_eligibility` (`:3449`).

Without an owner, any later provisioning code would have to repeat these checks, or skip them.

## Solution

One new module, `src/probos/cognitive/elastic_commission.py`, holding:

- `CommissionRequest` / `SlotReservation` / `ReleaseRequest`: frozen, strict pydantic requests. The owner names every attempt as `(slot_id, ordinal, execution_profile_ref, supersedes_attempt_id)`.
- `ElasticCommissionService.commission`: authorization, binding, plan currency, then per-reservation admission. Everything is checked before the first write, under one in-process lock; then each new attempt is recorded through `admit_current_qualified_attempt` (O-1).
- `ElasticCommissionService.release`: the owner ends an attempt that has no outcome (`cancelled` / `released_by_owner`). The record stays, so a replacement can supersede it.
- `ElasticCommissionService.team_view`: the read model an owner uses to name ordinals, and that a restart reads: reserved (no outcome) versus terminal.

The chain this slice ships, on real stores: owner request -> `CrewSessionService` reads -> `ProfileQualificationStore` + S2a currency -> `ElasticTeamStore` -> restart -> identical replay acknowledged -> release -> replacement -> restart -> view.

### Slicing of AD-1288 (decided; Delegated AD Execution Mode)

| Rank | Cut | Verdict |
|---|---|---|
| 1 (chosen) | **S1** admission (this). **S2** provisioning and symmetric teardown through the real pool/onboarding path, an attempt-lifecycle ledger (reserved/provisioning/active/draining/terminal) and default-off wiring. **S3** mission-scoped leased authority (at most the slot ceiling and the worker's own permissions), binding to a child work item, governed `WorkItemAgenticExecutor` admission, token/wall budgets, plus the drift (`record_component_drift`) and learning (`learn_attempt_outcome`) sweepers. **S4** team cancellation (closes admission synchronously and durably), drain within a bound, revocation, unregistration, honest teardown receipts, restart recovery of every state, and the end-to-end commission -> provisioning -> governed execution -> teardown test with cancellation and restart. **#1335 closes with S4.** | Each slice adds one owner and the consumer that proves it. The refusal rules land before anything is provisioned. |
| 2 | S1 admission; S2 provisioning + leases + governed execution; S3 cancellation/teardown/restart | Same order, but S2 joins four owners (pool, onboarding, leases, executor): the AD-1326 review-surface risk. |
| 3 | S1 admission plus the lifecycle ledger | The ledger would hold provisioning/active/draining states with no writer until S2: dead states. |
| 4 | A thin thread first (one attempt commissioned, provisioned, executed and torn down), then rules, then cancellation | It provisions workers before the refusal rules exist (wrong safety order), and its first slice touches six owners. |

What each slice leaves: S1 leaves provisioning, the ledger, wiring and request persistence (O-S1-1 to O-S1-5 below). S2 leaves authority and execution. S3 leaves cancellation, drain, receipts and full restart recovery.

**Captain decisions:** none for S1. For later slices: S3 stays in the envelope only if a lease is the intersection of the slot's `AuthorityCeiling` and the permissions the provisioned worker already holds. Leasing a scope above the worker's own rank would weaken authorization, so that is the Captain's call; recommended answer: never. Turning the feature on in production (a config flip that lets an agent cause bounded LLM spend) is the Captain's call when S2 lands. Nothing here touches the OSS/commercial boundary.

### Decisions (S1)

- **D1 -- A reservation's identity.** The owner names each attempt explicitly. The attempt id is AD-1286's `derive_worker_attempt_id(team_spec_ref, session_id, slot_id, ordinal)`, so a replay or a concurrent duplicate names the same row. An identical recorded attempt is acknowledged from the store and never re-admitted (S1 O-1: "recovery reads `get_attempt` rather than re-admitting"). Rejected: (a) a count the service turns into ordinals, because a replay after a restart would add attempts; (b) a request-id ledger, which would be a new store with no other writer in S1.
- **D2 -- Who may commission.** The session's `facilitator_id`, and only while the bound `worker_eligibility` resolver reports it eligible (`identity is not None`). An unbound, or required-but-unwired, resolver refuses with `commission_owner_unavailable`. This uses only public `CrewSessionService` reads, so its public surface is unchanged. Rejected: a new `CrewSessionService` method taking a `CrewSessionPrincipal`. The principal's token is checked only inside that class, and `agent_principal(agent_id)` is a public mint (`crew_session.py:3259`), so it would add no strength and would move two surface-census pins.
- **D3 -- Order of checks**, each refusing with a stable code before any write. Request type; session exists; state is `discussing` or `executing`; owner; eligibility; binding present, valid and naming the requested spec; spec stored; current plan (plan-bound specs only). Then per slot, then per reservation in ordinal order: slot declared; existing identical attempt (acknowledged) or conflict; budget; next ordinal; replacement validity; capacity; S1 qualification; S2a currency; independence.
- **D4 -- Independence.** `distinct_profiles` compares profile references. `distinct_models` compares `(model.provider, model.name)`: the version label is declared-only (AD-1287 R-6), so two versions of one model are not independent. `none` and `distinct_attempts` compare nothing, because every attempt has its own id. A new attempt whose key a live attempt of the slot already has is refused while the slot's live distinct keys number fewer than `min_distinct`. "Conflicting duty" is the slot's declared independence policy and nothing else: the spec does not declare adjudicator-versus-adjudicated separation, and profile disjointness between slots is already implied, because a profile has one role and task class (`slot_refusal`). Considered, deferred to AD-1290.
- **D5 -- Not checked in S1.** The capacity minimum (a readiness condition before execution starts, S2/S3), the token and wall budgets (execution, S3) and model availability (O-4, S2). Authority: nothing is leased or granted.
- **D6 -- Release.** Records `WorkerAttemptOutcome(cancelled, released_by_owner)` for an attempt of this session and bound spec that has no outcome. An identical replay returns the stored outcome. It works in any session state and does not compare the plan, because ending a reservation never widens what the team may do. In S1 a released attempt never ran, so `cancelled` is its true outcome, and AD-1287 S3's `learn_attempt_outcome` rightly records nothing for it (`not_evidence`).
- **D7 -- The write phase.** `admit_current_qualified_attempt` re-runs qualification and currency while recording. If it, or a store write, raises after an earlier attempt of the same request was recorded, that attempt stays recorded and the error propagates unchanged (not `CommissionRefused`). An identical retry acknowledges it. Rejected: compensating cancellation, which needs cancellation-safe shielding (the AD-1326 lesson) for a race that needs a component change within one locked call.
- **D8 -- Serialisation.** One `asyncio.Lock` per service covers every read and write of `commission`, `release` and `team_view`. Two service instances over the same files are not serialised (R-S1-1). S2's wiring constructs exactly one (O-S1-2).
- **D9 -- Failure tiers.** Refusals are `CommissionRefused` (a `ValueError`), logged at INFO, and write nothing. `ElasticTeamIntegrityError` from the binding read propagates and is not mapped to a refusal. Store, session and profile read errors propagate unchanged. A write-phase failure logs a WARNING with the count already recorded, then propagates.

**Obligations handed on:** O-S1-1 (S2): `release` must consult provisioning state before ending an attempt; once an attempt is provisioned, ending it goes through drain and records its true terminal status, never `cancelled`/`released_by_owner`, because S3 learning skips `cancelled` and a failure released that way would never count against its profile. O-S1-2 (S2): construct exactly one service per runtime. O-S1-3 (S2): persist each request (rationale, evidence refs, `request_ref`) in the lifecycle ledger; S1 validates them and logs only the reference. O-S1-4 (S2/S3): require every slot's live attempts to reach `capacity.minimum` before execution admission. O-S1-5 (S2, from review round 1 F2, recorded as F-87 on #1523): in `_admissible`, classify an identical replay and a conflict before hydrating the live attempts' independence keys, so a replay is acknowledged from the verified team record alone; S1 fails closed (a replay is refused or raises when a live profile is absent or the qualification store is unavailable, and never re-admits or writes), and no ordinary commission produces those states. **Residual:** R-S1-1, two service instances over the same files are not serialised.

**AD-1287 obligations and residuals (#1335 comment of 2026-10-14; `DECISIONS.md:127`, `:184`, `:192`, `:199`, `:225-233`), by carrier:**

| Item | Carrier | What it requires |
|---|---|---|
| O-1 (amended) | **S1, this slice** | Record only through `admit_current_qualified_attempt`; change test #16 deliberately; recovery reads `get_attempt` (D1, D7, Sections 2-4). |
| #1333 checks | **S1, this slice** | `spec.process.plan_hash` against the current plan (`commission_plan_stale`) and `get_team_binding(session_id)` against the requested spec (`commission_team_mismatch`) (D3). |
| O-4, model half | S2 | Provision only on the profile's declared `model.provider` and `model.name`, or refuse. |
| O-4, policy half; sweepers | S3 | Lease only under the profile's declared policy, or refuse. S3 owns the drift sweeper (`record_component_drift` over the refs it holds; there is no enumerator) and the learning sweeper (`learn_attempt_outcome`). |
| R-1 (shared per-operation `_open`) | S2 decides | S2 adds the lifecycle ledger store, the third copy; it extracts the helper or records why not. |
| R-2, R-3 (missing rows, rewritten stamps) | Captain (AD-1047) | No slice closes them; S4's teardown receipts must not claim tamper evidence. |
| R-4 (`admit_qualified_attempt` has no currency check) | S2 | S1 never calls it (A1). When wiring, S2 retires it or forwards it to the S2a gate. |
| R-5 (prompt revisions, tool implementation digests declared-only) | S3 | Binds them at lease time; until a live owner exists they stay declared-only. |
| R-6 (model version, policy declared-only) | S2 (version), S3 (policy) | Bound at provisioning and leasing; nothing observes them live. |

---

### Section 1 -- NEW `src/probos/cognitive/elastic_commission.py`

```python
"""AD-1288 S1: deterministic commission admission for elastic worker attempts (#1335).

The CrewSession's facilitator (the process owner) names the exact attempts it wants: for each, the slot, the
ordinal, the qualified execution profile and, for a replacement, the attempt it supersedes. This service decides
only whether each reservation is admissible under the frozen team spec. It never chooses or ranks a profile and
never decides what the work is (Design Principle #1): the owner chose them.

``commission`` checks, in order, and refuses with ``CommissionRefused`` (a stable code) before anything is
written: the session exists and is ``discussing`` or ``executing``; the owner is the session's facilitator and the
bound eligibility resolver reports it eligible; the session's ``crew_elastic_team`` binding names the spec the
request names; that spec is stored; a spec naming a ``plan_hash`` matches the session's current plan. Then, per
reservation in slot and ordinal order: the slot is declared; an attempt already recorded under the same id must be
identical, and is acknowledged without being re-admitted (AD-1287 S1 O-1); a new one must fit the slot's attempt
budget, take the next ordinal, replace only a failed or cancelled attempt of the same slot that nothing has
replaced, keep the slot's live attempts (recorded, no outcome) within its capacity maximum, pass S1's
qualification check and S2a's currency check, and satisfy the slot's independence policy. Only then is each new
attempt recorded, in that order, through ``admit_current_qualified_attempt`` (O-1 as amended by S2a).

The checks hold as of their own reads. Every public operation runs under one in-process lock, so two calls on one
service never interleave; two service instances over the same files are not serialised. The recording step re-runs
the qualification and currency checks: if one of them, or a store write, raises after an earlier attempt of the
same request was recorded, that attempt stays recorded and the error propagates unchanged; an identical retry
acknowledges it.

``release`` lets the owner end an attempt that has no outcome, recording ``cancelled`` with ``released_by_owner``.
The released attempt's record stays and a replacement may supersede it. Nothing here provisions a worker, so a
released attempt never ran.

Not checked here: a slot's capacity minimum, the token and wall-clock budgets and model availability. Nothing here
provisions, leases or grants anything, and nothing in ``src/probos`` constructs this service yet.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Final, Protocol

from pydantic import BaseModel, BeforeValidator, ConfigDict

from probos.cognitive.elastic_team import (
    ELASTIC_TEAM_SCHEMA_VERSION,
    CrewElasticTeamBinding,
    ElasticId,
    ElasticTeamSpec,
    Ordinal,
    RefSet,
    SchemaVersion,
    Sha256Ref,
    WorkerAttempt,
    WorkerAttemptOutcome,
    canonicalize_projection,
    derive_worker_attempt_id,
)
from probos.cognitive.elastic_team_store import ElasticTeamIntegrityError
from probos.cognitive.execution_profile import ExecutionProfile
from probos.cognitive.profile_currency import ProfileComponentSource, admit_current_qualified_attempt, profile_drift
from probos.cognitive.profile_qualification_store import (
    ProfileQualification,
    SlotAdmissionRefused,
    check_slot_qualification,
)

if TYPE_CHECKING:
    from probos.cognitive.crew_assignment import CrewWorkerEligibilityResolver
    from probos.cognitive.crew_session import CrewRecoveryContract, CrewSessionContract

logger = logging.getLogger(__name__)

RELEASE_ERROR_CODE: Final = "released_by_owner"

_REQUEST_DOMAIN: Final = b"probos.elastic_team/commission_request/v1\x00"
_MAX_RESERVATIONS: Final = 64
_MAX_RATIONALE_CHARS: Final = 2_000
_OPEN_SESSION_STATES: Final = frozenset({"discussing", "executing"})
_REPLACEABLE_STATUSES: Final = frozenset({"failed", "cancelled"})


class CommissionRefused(ValueError):
    """Admission refused a request before writing anything; ``str(exc)`` is the stable code."""


def _rationale(value: Any) -> str:
    if type(value) is not str or not 1 <= len(value) <= _MAX_RATIONALE_CHARS or not value.strip():
        raise ValueError("commission_rationale_invalid")
    if any((ord(char) < 32 and char not in "\t\n") or ord(char) == 127 for char in value):
        raise ValueError("commission_rationale_invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("commission_rationale_invalid") from None
    return value


def _reservation_sequence(value: Any) -> tuple[Any, ...]:
    if type(value) not in (list, tuple) or not 1 <= len(value) <= _MAX_RESERVATIONS:
        raise ValueError("commission_reservations_invalid")
    keyed: list[tuple[tuple[str, int], Any]] = []
    for entry in value:
        if type(entry) is SlotReservation:
            key: tuple[Any, Any] = (entry.slot_id, entry.ordinal)
        elif type(entry) is dict:
            key = (entry.get("slot_id"), entry.get("ordinal"))
        else:
            raise ValueError("commission_reservations_invalid")
        if type(key[0]) is not str or type(key[1]) is not int:
            raise ValueError("commission_reservations_invalid")
        keyed.append((key, entry))
    keys = [key for key, _ in keyed]
    if len(set(keys)) != len(keys):
        raise ValueError("commission_reservation_duplicate")
    return tuple(entry for _, entry in sorted(keyed, key=lambda pair: pair[0]))


def _checked_now(clock: Callable[[], float]) -> float:
    now = clock()
    if type(now) is not float or not math.isfinite(now) or now < 0.0:
        raise ValueError("commission_clock_invalid")
    return now


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class SlotReservation(_Frozen):
    """One attempt the owner asks for. ``supersedes_attempt_id`` names the failed or cancelled attempt it replaces."""

    slot_id: ElasticId
    ordinal: Ordinal
    execution_profile_ref: Sha256Ref
    supersedes_attempt_id: ElasticId | None


class CommissionRequest(_Frozen):
    """A process owner's request for exact worker attempts under the team spec its session bound. Grants nothing.

    ``reservations`` are sorted by ``(slot_id, ordinal)`` at validation and a repeated pair is refused, so the order
    they were given in never changes the request or its reference.
    """

    schema_version: SchemaVersion
    session_id: ElasticId
    team_spec_ref: Sha256Ref
    owner_id: ElasticId
    reservations: Annotated[tuple[SlotReservation, ...], BeforeValidator(_reservation_sequence)]
    rationale: Annotated[str, BeforeValidator(_rationale)]
    evidence_refs: RefSet

    def content_ref(self) -> str:
        """Domain-separated sha256 of the request's RFC 8785 projection. Logged; S1 stores no request."""
        return hashlib.sha256(_REQUEST_DOMAIN + canonicalize_projection(self.model_dump(mode="json"))).hexdigest()


class ReleaseRequest(_Frozen):
    """A process owner's request to end one attempt that has no outcome."""

    schema_version: SchemaVersion
    session_id: ElasticId
    owner_id: ElasticId
    worker_attempt_id: ElasticId


class _SessionQuery(_Frozen):
    session_id: ElasticId


@dataclass(frozen=True)
class CommissionReceipt:
    """What one ``commission`` call did, each tuple in slot and ordinal order."""

    request_ref: str
    recorded: tuple[WorkerAttempt, ...]  # recorded by this call
    acknowledged: tuple[WorkerAttempt, ...]  # identical attempts that were already recorded


@dataclass(frozen=True)
class SlotView:
    """One slot of a bound team as the stores hold it now. ``outcomes`` is aligned with ``attempts``."""

    slot_id: str
    capacity_maximum: int
    max_attempts: int
    attempts: tuple[WorkerAttempt, ...]
    outcomes: tuple[WorkerAttemptOutcome | None, ...]
    live: int
    next_ordinal: int


@dataclass(frozen=True)
class TeamView:
    """The bound team of one session: every declared slot, in the spec's slot order."""

    session_id: str
    team_spec_ref: str
    slots: tuple[SlotView, ...]


class CommissionSessions(Protocol):
    """The ``CrewSessionService`` reads admission uses (ISP); ``CrewSessionService`` satisfies it."""

    async def get_session(self, parent_id: str) -> CrewSessionContract | None: ...

    async def get_recovery(self, parent_id: str) -> CrewRecoveryContract | None: ...

    async def get_team_binding(self, parent_id: str) -> CrewElasticTeamBinding | None: ...

    @property
    def worker_eligibility(self) -> CrewWorkerEligibilityResolver | None: ...


class CommissionTeams(Protocol):
    """The ``ElasticTeamStore`` operations admission, release and the view use (ISP); ``ElasticTeamStore`` satisfies it."""

    async def get_team_spec(self, team_spec_ref: str) -> ElasticTeamSpec | None: ...

    async def record_attempt(self, attempt: WorkerAttempt) -> WorkerAttempt: ...

    async def get_attempt(self, worker_attempt_id: str) -> WorkerAttempt | None: ...

    async def list_slot_attempts(
        self, *, session_id: str, team_spec_ref: str, slot_id: str,
    ) -> tuple[WorkerAttempt, ...]: ...

    async def record_attempt_outcome(self, outcome: WorkerAttemptOutcome) -> WorkerAttemptOutcome: ...

    async def get_attempt_outcome(self, worker_attempt_id: str) -> WorkerAttemptOutcome | None: ...


class CommissionProfiles(Protocol):
    """The ``ProfileQualificationStore`` reads admission uses (ISP); ``ProfileQualificationStore`` satisfies it."""

    async def get_qualification(self, profile_ref: str) -> ProfileQualification | None: ...

    async def get_profile(self, profile_ref: str) -> ExecutionProfile | None: ...


def _independence_key(mode: str, profile_ref: str, profile: ExecutionProfile | None) -> object:
    """What the slot's independence policy compares: the profile, the model (provider and name), or nothing."""
    if mode == "distinct_profiles":
        return profile_ref
    if mode == "distinct_models" and profile is not None:
        return (profile.model.provider, profile.model.name)
    return None


def _attempt_for(request: CommissionRequest, reservation: SlotReservation) -> WorkerAttempt:
    try:
        return WorkerAttempt(
            schema_version=ELASTIC_TEAM_SCHEMA_VERSION,
            worker_attempt_id=derive_worker_attempt_id(
                team_spec_ref=request.team_spec_ref,
                session_id=request.session_id,
                slot_id=reservation.slot_id,
                ordinal=reservation.ordinal,
            ),
            team_spec_ref=request.team_spec_ref,
            session_id=request.session_id,
            slot_id=reservation.slot_id,
            ordinal=reservation.ordinal,
            execution_profile_ref=reservation.execution_profile_ref,
            supersedes_attempt_id=reservation.supersedes_attempt_id,
        )
    except ValueError as exc:  # the only rule left to fail: an attempt that names itself as its predecessor
        raise CommissionRefused("commission_replacement_invalid") from exc


class ElasticCommissionService:
    """The deterministic admission owner for elastic worker attempts (AD-1288 S1); see the module docstring.

    Public API:
        commission(request) -> CommissionReceipt
        release(request) -> WorkerAttemptOutcome
        team_view(session_id) -> TeamView | None
    """

    def __init__(
        self,
        *,
        sessions: CommissionSessions,
        teams: CommissionTeams,
        profiles: CommissionProfiles,
        components: ProfileComponentSource,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Construct the service; it opens nothing and starts nothing. ``clock`` stamps released outcomes only."""
        self._sessions = sessions
        self._teams = teams
        self._profiles = profiles
        self._components = components
        self._clock = clock
        self._lock = asyncio.Lock()

    async def commission(self, request: CommissionRequest) -> CommissionReceipt:
        """Admit and record the attempts ``request`` names, in the order the module docstring gives.

        Raises:
            TypeError: ``commission_request_type_invalid``; nothing is read.
            ValueError: (``pydantic.ValidationError``) the request no longer validates; nothing is read.
            CommissionRefused: a stable code, raised before anything is written.
            ElasticTeamIntegrityError: a stored spec or attempt no longer verifies.
            Whatever ``admit_current_qualified_attempt`` raises while recording, unchanged; attempts this call
            recorded before it stay recorded.
        """
        if type(request) is not CommissionRequest:
            raise TypeError("commission_request_type_invalid")
        request = CommissionRequest.model_validate(request)  # a model_copy(update=...) skips validation
        request_ref = request.content_ref()
        async with self._lock:  # one admission at a time: reads and writes never interleave
            try:
                spec = await self._authorized_spec(request.session_id, request.owner_id, request.team_spec_ref)
                new, acknowledged = await self._admissible(request, spec)
            except CommissionRefused as refused:
                logger.info(
                    "AD-1288: commission %s for session %s refused (%s); no worker attempt was recorded",
                    request_ref,
                    request.session_id,
                    refused,
                )
                raise
            recorded: list[WorkerAttempt] = []
            for attempt in new:
                try:
                    recorded.append(
                        await admit_current_qualified_attempt(self._profiles, self._teams, self._components, attempt)
                    )
                except BaseException:
                    logger.warning(
                        "AD-1288: commission %s for session %s stopped while recording attempt %s; the %d attempt(s) "
                        "it recorded before stay recorded, and an identical retry acknowledges them",
                        request_ref,
                        request.session_id,
                        attempt.worker_attempt_id,
                        len(recorded),
                    )
                    raise
        logger.info(
            "AD-1288: commission %s for session %s recorded %d worker attempt(s) and acknowledged %d under team "
            "spec %s; nothing was provisioned",
            request_ref,
            request.session_id,
            len(recorded),
            len(acknowledged),
            request.team_spec_ref,
        )
        return CommissionReceipt(request_ref=request_ref, recorded=tuple(recorded), acknowledged=tuple(acknowledged))

    async def release(self, request: ReleaseRequest) -> WorkerAttemptOutcome:
        """End one attempt that has no outcome by recording ``cancelled`` with ``released_by_owner``.

        Checks the session, owner, eligibility and binding as ``commission`` does, but not the session state or the
        plan. An identical replay returns the stored outcome and writes nothing.

        Raises:
            TypeError: ``commission_release_type_invalid``; nothing is read.
            ValueError: (``pydantic.ValidationError``) the request no longer validates; ``commission_clock_invalid``
                when the clock is not a finite non-negative float (nothing is written).
            CommissionRefused: a ``commission`` authorization or binding code, ``release_attempt_unknown`` or
                ``release_attempt_ended``; nothing is written.
            Whatever a read or ``record_attempt_outcome`` raises, unchanged.
        """
        if type(request) is not ReleaseRequest:
            raise TypeError("commission_release_type_invalid")
        request = ReleaseRequest.model_validate(request)
        async with self._lock:
            try:
                spec = await self._authorized_spec(request.session_id, request.owner_id, None)
                attempt = await self._teams.get_attempt(request.worker_attempt_id)
                if (
                    attempt is None
                    or attempt.session_id != request.session_id
                    or attempt.team_spec_ref != spec.content_ref()
                ):
                    raise CommissionRefused("release_attempt_unknown")
                ended = await self._teams.get_attempt_outcome(attempt.worker_attempt_id)
                if ended is not None and (ended.terminal_status, ended.error_code) != ("cancelled", RELEASE_ERROR_CODE):
                    raise CommissionRefused("release_attempt_ended")
            except CommissionRefused as refused:
                logger.info(
                    "AD-1288: release of attempt %s in session %s refused (%s); nothing was recorded",
                    request.worker_attempt_id,
                    request.session_id,
                    refused,
                )
                raise
            if ended is not None:
                return ended  # an identical replay: the first release's outcome, unchanged
            stored = await self._teams.record_attempt_outcome(
                WorkerAttemptOutcome(
                    worker_attempt_id=attempt.worker_attempt_id,
                    terminal_status="cancelled",
                    error_code=RELEASE_ERROR_CODE,
                    recorded_at=_checked_now(self._clock),
                )
            )
        logger.info(
            "AD-1288: the owner of session %s released worker attempt %s; its record stays and a replacement may "
            "supersede it",
            request.session_id,
            request.worker_attempt_id,
        )
        return stored

    async def team_view(self, session_id: str) -> TeamView | None:
        """The bound team's slots as the stores hold them now, or None when the session binds no team. Reads only.

        Raises:
            ValueError: (``pydantic.ValidationError``) a malformed ``session_id``; whatever ``get_team_binding``
                raises, unchanged.
            CommissionRefused: ``commission_team_spec_unknown``.
        """
        query = _SessionQuery.model_validate({"session_id": session_id})
        async with self._lock:
            binding = await self._sessions.get_team_binding(query.session_id)
            if binding is None:
                return None
            spec = await self._teams.get_team_spec(binding.team_spec_ref)
            if spec is None:
                raise CommissionRefused("commission_team_spec_unknown")
            slots: list[SlotView] = []
            for slot in spec.slots:
                attempts = await self._teams.list_slot_attempts(
                    session_id=query.session_id, team_spec_ref=binding.team_spec_ref, slot_id=slot.slot_id,
                )
                outcomes = tuple([await self._teams.get_attempt_outcome(a.worker_attempt_id) for a in attempts])
                slots.append(
                    SlotView(
                        slot_id=slot.slot_id,
                        capacity_maximum=slot.capacity.maximum,
                        max_attempts=slot.budget.max_attempts,
                        attempts=attempts,
                        outcomes=outcomes,
                        live=sum(1 for outcome in outcomes if outcome is None),
                        next_ordinal=len(attempts) + 1,
                    )
                )
        return TeamView(session_id=query.session_id, team_spec_ref=binding.team_spec_ref, slots=tuple(slots))

    async def _authorized_spec(self, session_id: str, owner_id: str, team_spec_ref: str | None) -> ElasticTeamSpec:
        """The bound spec, after the session, owner and binding checks; when commissioning, also state and plan.

        ``team_spec_ref`` is None for a release, which checks neither the session state nor the plan.
        """
        commissioning = team_spec_ref is not None
        session = await self._sessions.get_session(session_id)
        if session is None:
            raise CommissionRefused("commission_session_unknown")
        if commissioning and session.state not in _OPEN_SESSION_STATES:
            raise CommissionRefused("commission_session_state_invalid")
        if owner_id != session.facilitator_id:
            raise CommissionRefused("commission_owner_unauthorized")
        try:
            eligibility = self._sessions.worker_eligibility
        except ValueError:  # required but unwired (crew_session_worker_eligibility_unwired)
            eligibility = None
        if eligibility is None or eligibility.check_eligibility(owner_id).identity is None:
            raise CommissionRefused("commission_owner_unavailable")
        try:
            binding = await self._sessions.get_team_binding(session_id)
        except ElasticTeamIntegrityError:
            raise  # a stored spec that no longer verifies is data integrity, not a refusal
        except ValueError as exc:
            raise CommissionRefused("commission_team_binding_invalid") from exc
        if binding is None:
            raise CommissionRefused("commission_team_unbound")
        if commissioning and binding.team_spec_ref != team_spec_ref:
            raise CommissionRefused("commission_team_mismatch")
        spec = await self._teams.get_team_spec(binding.team_spec_ref)
        if spec is None:
            raise CommissionRefused("commission_team_spec_unknown")
        plan_hash = spec.process.plan_hash
        if commissioning and plan_hash is not None:
            recovery = await self._sessions.get_recovery(session_id)
            if recovery is None or recovery.plan is None or recovery.plan.plan_hash != plan_hash:
                raise CommissionRefused("commission_plan_stale")
        return spec

    async def _live_key(self, mode: str, attempt: WorkerAttempt) -> object:
        if mode != "distinct_models":
            return _independence_key(mode, attempt.execution_profile_ref, None)
        profile = await self._profiles.get_profile(attempt.execution_profile_ref)
        if profile is None:
            raise CommissionRefused("commission_live_profile_unknown")
        return _independence_key(mode, attempt.execution_profile_ref, profile)

    async def _admissible(
        self, request: CommissionRequest, spec: ElasticTeamSpec,
    ) -> tuple[list[WorkerAttempt], list[WorkerAttempt]]:
        """Split the request into new attempts to record and recorded ones to acknowledge; refuse on any rule."""
        new: list[WorkerAttempt] = []
        acknowledged: list[WorkerAttempt] = []
        for slot_id in sorted({reservation.slot_id for reservation in request.reservations}):
            slot = spec.slot(slot_id)
            if slot is None:
                raise CommissionRefused("commission_slot_unknown")
            history = await self._teams.list_slot_attempts(
                session_id=request.session_id, team_spec_ref=request.team_spec_ref, slot_id=slot_id,
            )
            recorded = {attempt.worker_attempt_id: attempt for attempt in history}
            outcomes = {
                attempt.worker_attempt_id: await self._teams.get_attempt_outcome(attempt.worker_attempt_id)
                for attempt in history
            }
            replaced = {attempt.supersedes_attempt_id for attempt in history if attempt.supersedes_attempt_id}
            mode = slot.independence.mode
            live_keys = [
                await self._live_key(mode, attempt) for attempt in history if outcomes[attempt.worker_attempt_id] is None
            ]
            next_ordinal = len(history) + 1
            for reservation in (entry for entry in request.reservations if entry.slot_id == slot_id):
                attempt = _attempt_for(request, reservation)
                existing = recorded.get(attempt.worker_attempt_id)
                if existing is not None:
                    if existing.content_ref() != attempt.content_ref():
                        raise CommissionRefused("commission_reservation_conflict")
                    acknowledged.append(existing)
                    continue  # acknowledged from the store, never re-admitted (S1 O-1)
                if reservation.ordinal > slot.budget.max_attempts:
                    raise CommissionRefused("commission_budget_exhausted")
                if reservation.ordinal != next_ordinal:
                    raise CommissionRefused("commission_ordinal_invalid")
                predecessor = reservation.supersedes_attempt_id
                if predecessor is not None and (
                    predecessor not in recorded
                    or predecessor in replaced
                    or outcomes[predecessor] is None
                    or outcomes[predecessor].terminal_status not in _REPLACEABLE_STATUSES
                ):
                    raise CommissionRefused("commission_replacement_invalid")
                if len(live_keys) >= slot.capacity.maximum:
                    raise CommissionRefused("commission_capacity_exceeded")
                try:
                    qualification = await check_slot_qualification(
                        self._profiles, spec, slot_id, reservation.execution_profile_ref,
                    )
                except SlotAdmissionRefused as refused:
                    raise CommissionRefused(str(refused)) from refused
                drifts = await profile_drift(qualification.profile, self._components)
                if drifts:
                    raise CommissionRefused(drifts[0].code)
                key = _independence_key(mode, reservation.execution_profile_ref, qualification.profile)
                if key is not None and key in live_keys and len(set(live_keys)) < slot.independence.min_distinct:
                    raise CommissionRefused("commission_independence_unmet")
                live_keys.append(key)
                if predecessor is not None:
                    replaced.add(predecessor)
                next_ordinal += 1
                new.append(attempt)
        return new, acknowledged
```

### Section 2 -- `tests/test_ad1287_slot_qualification.py`

The S1 scan (test #16) must spare the one module allowed to import the S1/S2a modules and call the gate (O-1). This is the deliberate change the test's own docstring predicts (`:717-718`). `_S1_MODULES` and `_GATE_NAMES` keep their names and contents, because `tests/test_ad1287_s2b_drift_recorder.py:77-79` imports them and `:801-802` asserts their contents. AD-1287 S3 edited only `:736` of this test (`assert "admit_current_qualified_attempt" in declared`), which no SEARCH below touches.

```
<<<<<<< SEARCH
    "RegistryComponentSource",
    "record_component_drift",
)


def _gate_references(tree: ast.AST) -> list[str]:
=======
    "RegistryComponentSource",
    "record_component_drift",
)
# AD-1288 S1: the one consumer allowed to import the S1/S2a modules and call the gate (O-1). Not a gate module, so it
# is spared as an owner here rather than added to ``_S1_MODULES`` (which the S2b test imports).
_ADMISSION_CONSUMERS = ("elastic_commission",)


def _gate_references(tree: ast.AST) -> list[str]:
>>>>>>> REPLACE
```

### Section 3 -- `tests/test_ad1287_slot_qualification.py`

```
<<<<<<< SEARCH
    owned = [_SRC_PROBOS / "cognitive" / f"{name}.py" for name in _S1_MODULES]
    assert all(path.is_file() for path in owned)  # premise: the modules the scan excludes are where it expects them
=======
    owned = [_SRC_PROBOS / "cognitive" / f"{name}.py" for name in _S1_MODULES]
    assert all(path.is_file() for path in owned)  # premise: the modules the scan excludes are where it expects them
    # AD-1288 S1: commission admission is spared too, and it really references the gate, so sparing it is not vacuous
    consumers = [_SRC_PROBOS / "cognitive" / f"{name}.py" for name in _ADMISSION_CONSUMERS]
    assert all(path.is_file() for path in consumers)
    assert all(_gate_references(ast.parse(path.read_bytes())) for path in consumers)
>>>>>>> REPLACE
```

### Section 4 -- `tests/test_ad1287_slot_qualification.py`

```
<<<<<<< SEARCH
    parsed, offenders = _scan_tree(_SRC_PROBOS, owned)
    # premise: the scan reached the tree, and parsed files that only mention the names (``execution_profile_ref``,
=======
    parsed, offenders = _scan_tree(_SRC_PROBOS, owned + consumers)
    # premise: the scan reached the tree, and parsed files that only mention the names (``execution_profile_ref``,
>>>>>>> REPLACE
```

### Section 5 -- `DECISIONS.md`

```
<<<<<<< SEARCH
## Era V — Civilization (Phases 31-36)
=======
## Era V — Civilization (Phases 31-36)

### AD-1288 S1 -- Commission admission: owner-named worker attempts admitted against the frozen spec (2026-10-15, #1335)

- *Slicing.* AD-1288 is cut into four slices, each a whole chain on real stores: S1 admission (this: reserve, replace and release attempts; no store, nothing provisioned, unwired); S2 provisioning and symmetric teardown through the real pool and onboarding path, with an attempt-lifecycle ledger and default-off wiring; S3 leased authority (at most the slot ceiling and the worker's own permissions), governed execution admission, budgets, and the drift and learning sweepers; S4 cancellation, drain, revocation, teardown receipts and restart recovery. #1335 closes with S4. Rejected: one candidate (AD-1326 took seven review rounds); a thin end-to-end thread first (it provisions before the refusal rules exist); provisioning and leases in one slice (four owners in one review).
- *D1 (reservation identity).* The owner names each attempt `(slot, ordinal, profile, superseded attempt)`; its id is AD-1286's derived id, so a replay or a concurrent duplicate is the same row, acknowledged from the store and never re-admitted (S1 O-1). Rejected: a count turned into ordinals (a replay adds attempts); a request ledger (a store with no other S1 writer).
- *D2 (who).* The session's facilitator, eligible now through the bound `worker_eligibility` resolver, through public `CrewSessionService` reads only; no `CrewSessionService` surface changes.
- *D3 (checks).* State `discussing`/`executing`; the binding names the requested spec and a plan-bound spec matches the current plan (#1333's two checks); per new reservation: budget, next ordinal, replacement of an unreplaced failed or cancelled attempt, live attempts below the capacity maximum, S1 qualification, S2a currency, independence. All before the first write, under one in-process lock.
- *D4 (independence).* `distinct_profiles` compares references, `distinct_models` provider and name (the version label is declared-only, R-6); a duplicate key is refused while the slot's live distinct keys are fewer than `min_distinct`. Conflicting duty is the slot's declared independence only; adjudicator separation is deferred to AD-1290.
- *D5-D9.* Not checked: capacity minimum, token and wall budgets, model availability. `release` records `cancelled`/`released_by_owner` and keeps the record. A write-phase failure keeps earlier writes and propagates; an identical retry acknowledges them. One lock per service; two instances are not serialised (R-S1-1). Refusals are `CommissionRefused` and write nothing; integrity errors propagate.
- *Obligations.* O-S1-1 (S2): release consults provisioning state, and a provisioned attempt ends through drain with its true status, never `released_by_owner` (AD-1287 S3 does not learn `cancelled`). O-S1-2 (S2): exactly one service per runtime. O-S1-3 (S2): persist the request in the lifecycle ledger. O-S1-4 (S2/S3): capacity minimum before execution admission. AD-1287 carriers: O-1 and #1333's two checks land here; O-4's model half and R-4, R-6 (version) in S2, R-1 decided in S2; O-4's policy half, the drift and learning sweepers, R-5 and R-6 (policy) in S3; R-2 and R-3 stay with the Captain (AD-1047).
- *Existing test changed.* AD-1287 S1 test #16 spares `elastic_commission` as the one admission consumer, with a non-vacuity check; `_S1_MODULES` and `_GATE_NAMES` are unchanged.
- Contract `prompts/ad-1288-s1-commission-admission.md`. #1335 stays open.
>>>>>>> REPLACE
```

### Section 6 -- `PROGRESS.md`

The SEARCH is the heading alone so that this applies whether or not AD-1287 S3's paragraph has landed above the S2b one.

```
<<<<<<< SEARCH
# ProbOS Progress
=======
# ProbOS Progress

**AD-1288 slice S1 BUILT (2026-10-15), #1335, built and unwired -- nothing under `src/` constructs `ElasticCommissionService`; no new AD or BF number.** It adds `src/probos/cognitive/elastic_commission.py`: a CrewSession's facilitator names exact worker attempts (slot, ordinal, qualified profile, superseded attempt) and the service admits them against the session state, the owner's eligibility, the `crew_elastic_team` binding, the current plan, the slot's attempt budget, ordinal, replacement rules, capacity maximum, S1 qualification, S2a currency and the slot's independence policy, all before the first write, then records each through `admit_current_qualified_attempt` (O-1). `release` ends an attempt with no outcome (`cancelled`/`released_by_owner`) and keeps its record for a replacement; `team_view` reads reserved versus terminal attempts. Nothing is provisioned, leased or granted. AD-1287 S1 test #16 changed deliberately. S2 (provisioning and teardown), S3 (leased authority and governed execution) and S4 (cancellation, drain and restart recovery) remain; #1335 stays open. Contract `prompts/ad-1288-s1-commission-admission.md`.
>>>>>>> REPLACE
```

### Section 7 -- `docs/development/roadmap.md`

```
<<<<<<< SEARCH
| AD-1288 | Agent-Commissioned Team Lifecycle - governed provision, leases, recovery, teardown | [#1335](https://github.com/seangalliher/ProbOS/issues/1335) | 1 |
=======
| AD-1288 | Agent-Commissioned Team Lifecycle - governed provision, leases, recovery, teardown (S1 commission admission built 2026-10-15, unwired; S2 provisioning, S3 leased authority and governed execution, S4 cancellation and restart recovery remain) | [#1335](https://github.com/seangalliher/ProbOS/issues/1335) | 1 |
>>>>>>> REPLACE
```

**Regenerate the ledger right after installing Sections 5-6** (pinned by `tests/test_ad1184_ad_ledger.py`):

```
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py --check
```

---

## Tests (written by Builders against the installed source; tests only)

Rules for every file: never edit `src/`. Real stores in `tmp_path` only (`ElasticTeamStore(str(path))`, the S1 `_started` helper pattern for `ProfileQualificationStore`, `WorkItemStore` with `SQLiteConnectionFactory()`). Fakes are `_Fake*` classes. Every test asserts its own premise (for example, that the profile really is `qualified` before testing a capacity refusal). Every refusal has a negative control: the accepted neighbour. "Wrote nothing" means a snapshot of every slot's attempts and outcomes (`list_slot_attempts` + `get_attempt_outcome`) is equal before and after. Import test helpers as the AD-1287 tests already do (`tests/test_ad1287_s2a_profile_currency.py:48-51`, `tests/test_ad1287_slot_qualification.py:36-38`): `_World` (`:88`, two real stores on two files; `stop()` then `start()` is a restart), `_variant` (`:124`) and `_in_state` (`:145`) from `tests.test_ad1287_slot_qualification`; `_Clock` (`:91`), `_started` (`:233`) and `_evaluation` (`:244`) from `tests.test_ad1287_profile_qualification_store`; `_FakeSource` (`:108`) and `_current_source` (`:199`) from `tests.test_ad1287_s2a_profile_currency`; `_spec` (`:145`), `_slot` (`:150`) and `_review_slot` (`:157`) from `tests.test_ad1286_elastic_team_contract`; `_profile` (`:101`) from `tests.test_ad1287_execution_profile`. M3 does not import `tests.test_ad1287_slot_qualification` (its #5 reads that file's text), so it builds profiles from `_profile` as `_variant` does. Construct `_World(tmp_path)` in a local fixture rather than importing the `world` fixture. `_variant` profiles meet the KAT `review` slot (role `reviewer`, task class `finding_review`, no pins); the `analyse` slot pins a fixed ref, so commission into `review`. The KAT `review` slot has capacity 1 and `max_attempts` 2: for more, build `_spec(slots=[_slot(), _review_slot(capacity=..., independence=..., budget=...)])`, keeping `max_attempts >= capacity.maximum >= min_distinct`. M3 may import the AD-1127 session harness (`_new_session`, `_vector_plan_payload`, `_vector_insert`, `_VECTOR_PLAN_HASH`), following `tests/test_ad1286_crew_session_team_binding.py:42-58`, and `_plan_bound_spec` (`:118` there).

### M1 `tests/test_ad1288_s1_commission_request.py` (contracts, no stores)

1. `test_reservations_sort_and_order_never_changes_the_reference`: the same reservations given in two orders give equal requests and equal `content_ref()`.
2. `test_request_ref_is_domain_separated_known_answer`: expected = `sha256(b"probos.elastic_team/commission_request/v1\x00" + probos.federation.ard.jcs.canonicalize(request.model_dump(mode="json")))`, computed in the test; the same bytes under a `.../v2\x00` domain differ (negative control).
3. `test_duplicate_slot_ordinal_pair_is_refused`: `commission_reservation_duplicate`; the same slot with two ordinals is accepted.
4. `test_reservation_sequence_bounds[empty, sixty_five, not_a_sequence, bool_ordinal, missing_slot_id, other_type]`: `commission_reservations_invalid`; exactly 64 is accepted.
5. `test_rationale_rules[empty, blank, over_2000, carriage_return, nul, delete, lone_surrogate]`: `commission_rationale_invalid`; tab, newline and exactly 2,000 characters are accepted.
6. `test_requests_are_strict_and_closed`: an extra field, an int session id and a non-sha `team_spec_ref` are refused; `evidence_refs` are sorted and duplicates refused (`elastic_team_ref_set_invalid`).
7. `test_release_request_validates_ids`.
8. `test_types_carry_no_authority_fields`: no field of `CommissionRequest`, `SlotReservation`, `ReleaseRequest`, `CommissionReceipt`, `SlotView` or `TeamView` contains `scope`, `rank`, `lease`, `grant`, `authority` or `permission`; negative control: the same check flags a synthetic `lease_id`.

### M2 `tests/test_ad1288_s1_commission_admission.py` (rules on real team and qualification stores, fake sessions)

`_FakeSessions` holds a settable session (`state`, `facilitator_id`), recovery (`plan.plan_hash`), binding (a real `CrewElasticTeamBinding.for_spec`), a `worker_eligibility` (a `_FakeEligibility` whose `check_eligibility` returns an object with `.identity`, or a property that raises `ValueError`), and records every call. `_FakeSource` reports components as current unless told otherwise.

1. `test_commission_records_exact_attempts_in_slot_and_ordinal_order`: two slots; `recorded` ids equal `derive_worker_attempt_id(...)`; `get_attempt` returns each; `acknowledged == ()`.
2. `test_authorization_refusals_write_nothing[session_unknown, state_verifying, state_done, owner_not_facilitator, resolver_none, resolver_raises, owner_ineligible, unbound, binding_invalid, team_mismatch, spec_unknown, plan_no_recovery, plan_other_hash]`: the exact code; nothing written; `executing` and a matching plan are accepted (controls).
3. `test_reservation_refusals_write_nothing[slot_unknown, conflict, budget_exhausted, ordinal_gap, ordinal_reused_new_profile, replace_unknown, replace_live, replace_succeeded, replace_already_replaced, replace_twice_in_one_request, self_supersede, capacity]`: the exact code; nothing written, including the earlier valid reservations of the same request; each with its control.
4. `test_capacity_boundary`: `maximum` live attempts are accepted, one more is `commission_capacity_exceeded`; after `release` of one, one more is accepted.
5. `test_qualification_and_currency_codes_pass_through[profile_unknown, profile_status_expired, profile_status_unevaluated, role_mismatch, component_drift_skill, component_drift_tool_schema]`: `CommissionRefused` carries the S1 or S2a code unchanged; nothing written.
6. `test_distinct_profiles_allows_a_repeat_only_after_min_distinct`: `min_distinct=2`, capacity 3: A then A refused (`commission_independence_unmet`); A, B, then A accepted.
7. `test_distinct_models_compares_provider_and_name_not_version[provider, name]`: on a fresh rig and live baseline per case, two profiles differing only in `model.version` are one key (refused); a profile differing only in `model.provider`, and one differing only in `model.name`, are each a second key (accepted, tried while the distinct live keys are still below `min_distinct`). The provider case kills C29.
8. `test_identical_replay_is_acknowledged_without_readmission`: record; move the qualification clock until the profile is `expired` (premise asserted); the identical request returns `recorded == ()` and `acknowledged` equal to the stored attempt; a NEW reservation with that profile is refused `profile_status_expired` (control).
9. `test_release_then_replacement_keeps_the_released_record`: release gives `cancelled`/`released_by_owner`; a replay returns the identical outcome with the first `recorded_at`; a replacement superseding it records a new id; the released attempt and outcome are unchanged.
10. `test_release_refusals[unknown_attempt, other_session, other_spec, ended_failed, not_owner]`: the codes, nothing written. Controls: release works with `state="verifying"` and with a stale plan.
11. `test_release_refuses_a_bad_clock_and_writes_nothing`: clocks returning an int, NaN or -1.0 raise `commission_clock_invalid`.
12. `test_binding_integrity_error_propagates`: `get_team_binding` raising `ElasticTeamIntegrityError` propagates as that type, not `CommissionRefused`; a plain `ValueError` maps to `commission_team_binding_invalid` (control).
13. `test_write_phase_failure_keeps_earlier_attempts_and_a_retry_acknowledges_them`: a `_FakeFlipSource` that is current for prevalidation and drifted on the gate's read for the second attempt. The first attempt is recorded and `SlotAdmissionRefused` (not `CommissionRefused`) propagates, with one WARNING naming the count 1. An identical retry with a current source acknowledges the first and records the second.
14. `test_bad_input_reads_nothing`: a non-request raises `TypeError("commission_request_type_invalid")`; `model_copy(update={"owner_id": "bad id!"})` raises `ValidationError`; `_FakeSessions` saw no call.
15. `test_lock_serialises_concurrent_commissions`: a `_FakeBarrierSource` whose `skill_state` waits up to 0.2 s for a second concurrent caller and records whether one arrived. Two `asyncio.gather`ed commissions for different ordinals of one slot: no overlap is observed, and the results are one receipt plus either a receipt or a `CommissionRefused` (never `ElasticTeamConflict`). Premise control: the same barrier sees overlap when two `profile_drift` calls are gathered directly.
16. `test_team_view_reports_reserved_and_terminal`: live and `next_ordinal` per slot, outcomes aligned, and None when unbound.

### M3 `tests/test_ad1288_s1_commission_chain.py` (the seam: real CrewSessionService, real stores, restarts)

1. `test_commission_release_replace_across_restarts`: a real session (`_new_session`), a real `bind_team_spec` of a bill-bound spec, and a second `CrewSessionService` over the same stores with `worker_resolver=_FakeResolver()` (eligible for `facilitator-1` only) as `sessions`. Commission two attempts. Close every store and reopen new instances (new service objects). The identical request is acknowledged with no new row, and `team_view` shows them reserved. Release one, restart, then commission a replacement superseding it; restart; `team_view` shows the released record (`cancelled`/`released_by_owner`) and the live replacement. The parent and child work-item rows are byte-identical (canonical JSON) before and after, and nothing was written outside the two stores.
2. `test_plan_bound_spec_admits_on_the_installed_plan`: the vector plan installed and `_plan_bound_spec()` bound: accepted. Control: the same commission through a `sessions` wrapper whose `get_recovery` reports another plan hash is refused `commission_plan_stale` and writes nothing.
3. `test_concurrent_commissions_never_exceed_capacity_on_real_stores`: five gathered commissions on a capacity-3 slot with distinct profiles. Live attempts never exceed 3; every result is a receipt or `CommissionRefused`.
4. `test_nothing_in_src_constructs_the_service`: an AST scan of `src/probos` (excluding `cognitive/elastic_commission.py`) finds no import of `elastic_commission` and no call of `ElasticCommissionService`. Non-vacuity: a scratch tree with an offender is flagged, and a file that names it only in a string is not.
5. `test_s1_scan_spares_only_the_commission_module`: without importing that test module, read the text of `tests/test_ad1287_slot_qualification.py` and assert it contains `_ADMISSION_CONSUMERS = ("elastic_commission",)` and `_scan_tree(_SRC_PROBOS, owned + consumers)`, and that `_S1_MODULES` still lists exactly the five AD-1287 modules (premise for the S2b import). This pins the deliberate test #16 change.

## What This Does NOT Change

- No `CrewSessionService`, `ElasticTeamStore`, `ProfileQualificationStore` or profile-module source change; no store, config, `EventType`, API, UI, startup or shutdown change; no runtime wiring. A default runtime is byte-for-byte unchanged in behaviour (nothing imports the new module).
- No provisioning, spawn, onboarding, pool, registry, lease, grant, work-item, execution, budget-enforcement, drift-sweeper or learning call. The S2a currency check is called, never recorded (no `record_component_drift`).
- The AD-1286 and AD-1287 campaigns of record stand: no file they pin changes except `tests/test_ad1287_slot_qualification.py` (Sections 2-4, test #16 only; S2a's and S2b's own scans are untouched).

## Do Not Build

The ledger, provisioning, authority leases, execution admission, cancellation or drain (S2-S4). Typed blackboard semantics, replica reducers, automatic scaling heuristics, commercial process discovery, a new agent base class, or a parallel task/workflow store (#1335's "Do Not Build"). A ranking or "best profile" helper: the owner chooses (Design Principle #1). Compensating cancellation in the write phase (D7). Adjudicator-separation rules (AD-1290).

## Acceptance Criteria

1. Sections 1-7 install mechanically on `52dcbfa7`; the ledger regenerates and `--check` passes.
2. One commission creates only attempts declared by the bound spec, with the exact owner-selected profiles (M2 #1, M3 #1).
3. Unauthorized, wrong-state, unbound, stale-plan, unqualified, drifted, over-capacity, over-budget, conflicting, independence-violating and invalid-replacement requests write nothing (M2 #2, #3, #5, #6, #7).
4. Concurrent commissions on one service never exceed a slot maximum or duplicate a reservation (M2 #15, M3 #3).
5. Replacement creates a new attempt id and preserves the superseded attempt's record and outcome (M2 #9, M3 #1).
6. After a restart, reserved and terminal attempts are distinguished from the stores alone, and an identical replay is acknowledged, not re-admitted (M2 #8, M3 #1).
7. The service accepts owner-selected profile ids and ranks nothing (code review: no sort by score, no candidate query).
8. A default runtime is unchanged: nothing in `src/` constructs the service (M3 #4), and AD-1287 S1 test #16 passes with its deliberate change.
9. Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1288_s1_commission_request.py tests/test_ad1288_s1_commission_admission.py tests/test_ad1288_s1_commission_chain.py -q -n 0`, then the whole `tests/test_ad1287_*.py` and `tests/test_ad1286_*.py` groups, then `tests/test_ad1184_ad_ledger.py`.
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Hidden Pins (enumerated)

| Pin | Command | Effect |
|---|---|---|
| AD-1287 S1 test #16 (`tests/test_ad1287_slot_qualification.py:714`) | Grep `_S1_MODULES\|_GATE_NAMES\|_scan_tree\(_SRC_PROBOS` in that file | Fails on the new module's imports; changed by Sections 2-4. |
| S2b imports `_S1_MODULES`, `_GATE_NAMES` (`tests/test_ad1287_s2b_drift_recorder.py:77-79`, asserted `:801-802`) | Grep `_S1_MODULES` in `tests/` | Names and contents kept; unaffected. |
| AD-1287 S3 tests (`tests/test_ad1287_s3_outcome_learning.py`, `tests/test_ad1287_s3_profile_outcomes.py`) | Grep `rglob\|os\.walk\|_SRC_PROBOS\|src/probos` in `tests/test_ad128[678]*.py` | No `src/` scan (their `iterdir` calls list `tmp_path`); the store's public surface is unchanged, so S3's `_data_calls` pin is unaffected. |
| Ledger check (`tests/test_ad1184_ad_ledger.py`) | `scripts/gen_ad_ledger.py --check` | Regenerate after Sections 5-6. |
| `CrewSessionService` surface census (`tests/test_ad1124_crew_session_contract.py:1911`, `tests/test_ad1126_verified_finalization.py:6078`) | Grep `bind_team_spec_lookup` in `tests/` | No method added (D2); unaffected. |
| BF-892 launch guard (`tests/test_bf892_spawn_env_guard.py:479`, `rglob("*.py")` over `src/`) | Read `:61-76` (launchers: `subprocess.*`, `asyncio.create_subprocess_*`, `os.exec*`, `os.spawn*`) | Section 1 launches no process and reads no environment; unaffected. |
| Standing-orders retired-name scan (`tests/test_standing_orders_layout.py:139`, `:146`: `.github`, `scripts`, `src`, `tests`) | Grep `probos-(architect\|builder\|diff-reviewer)\|ProbOS Supervised\|supervised-worker` | Section 1 and the three test files must not contain these strings; none does in this contract. |
| Layer boundaries (`tests/test_layer_boundaries.py:60`) | Grep `ALLOWED_EXCEPTIONS` | Imports are `probos.cognitive.*` only (crew modules under `TYPE_CHECKING`); no exception entry. |
| Store registry and declarations | Section 1 holds no `ConnectionFactory`, `aiosqlite` or SQL | No declaration; `storage_declarations.py` untouched (no prose pin moves). |
| Config, `EventType`, goldens | none added | none. |
| Other `src/` scans: 39 test files glob `*.py` (Grep `r?glob\(["']\*\.py["']\)` in `tests/`; the 39th is BF-892's, above) | read: the AD-1286/1287 ones and BF-892's | The others scan for unrelated patterns (private `_emit_event`, opt-outs, budget arming); the pre-builder full-suite diagnostic is the evidence for them. |
| Prose | Sections 2-4 add comments only, no assertion of existing text | Run the whole `tests/test_ad1287_*.py` group after install. |

## Verified Against Codebase (2026-10-15, `52dcbfa7`)

```
git diff --numstat d936fc24 52dcbfa7 -- elastic_team.py elastic_team_store.py profile_currency.py
  execution_profile.py crew_session.py crew_assignment.py (cognitive/) and tests ad1127 lifecycle, ad1286 binding,
  ad1287 s2a currency, s2b drift, execution_profile
  (empty: every claim below on those files is re-grepped, and the lines are unchanged)
Grep "^(class |def |async def |ElasticId|...)" src/probos/cognitive/elastic_team.py
  31 ELASTIC_TEAM_SCHEMA_VERSION: Final = 1; 35 _ID_RE; 56 canonicalize_projection (lazy jcs.canonicalize, :63);
  132 ElasticId; 133 Sha256Ref; 135 RefSet (elastic_team_ref_set_invalid); 137 SchemaVersion; 145 Ordinal;
  149 IndependenceMode = none|distinct_attempts|distinct_profiles|distinct_models; 151 TerminalStatus;
  171-175 ProcessBinding(bill, plan_hash); 184-186 CapacityRange(minimum, maximum); 202-204 IndependencePolicy(mode,
  min_distinct); 234-237 SlotBudget(max_tokens, max_wall_ms, max_attempts); 247 WorkerSlot (:268 max_attempts >=
  capacity.maximum); 297 ElasticTeamSpec (process :310, slots :311, slot() :332); 337 derive_worker_attempt_id(*,
  team_spec_ref, session_id, slot_id, ordinal); 350 WorkerAttempt (:375 self-supersede -> ValueError; content_ref
  :379); 384 WorkerAttemptOutcome(worker_attempt_id, terminal_status, error_code, recorded_at); 399
  CrewElasticTeamBinding (team_spec_ref :409; for_spec :414)
Grep src/probos/cognitive/elastic_team_store.py
  138 _MAX_LISTED_ATTEMPTS = 1_024; 152 ElasticTeamIntegrityError(ValueError); 418 __init__(self, db_path: str, ...);
  537 put_team_spec; 610 get_team_spec; 625 record_attempt; 692 _admit_attempt; 767 get_attempt;
  785 list_slot_attempts; 806 record_attempt_outcome; 874 get_attempt_outcome
Read src/probos/cognitive/profile_currency.py:67 ProfileComponentSource; :148-196 profile_drift(profile, source);
  :199-236 admit_current_qualified_attempt(qualifications, teams, components, attempt)
Read src/probos/cognitive/profile_qualification_store.py (moved by AD-1287 S3, BF-890, BF-892; signatures unchanged)
  :253 SlotAdmissionRefused(ValueError); :280-288 ProfileQualification(profile_ref, profile, status, deciding,
  invalidation_reasons, assessed_at_ms); :343-346 ProfileQualificationReader.get_qualification; :349-354
  TeamAttemptRecorder(get_team_spec, record_attempt); :787 get_profile(profile_ref) -> ExecutionProfile | None;
  :904 get_qualification(profile_ref) -> ProfileQualification | None; :1083-1111 check_slot_qualification(
  qualifications, spec, slot_id, profile_ref) -> ProfileQualification; :1114 admit_qualified_attempt;
  :1150-1187 learn_attempt_outcome (cancelled -> "not_evidence", nothing written, :1178-1185)
Read src/probos/cognitive/profile_qualification_store.py:587-607 _assess: status from evaluations and invalidations
  only; outcomes do not enter it (S3 D1, DECISIONS.md:121)
Grep src/probos/cognitive/execution_profile.py
  120-125 ModelComponent(provider, name, version); 163 ExecutionProfile; 173 model
Read src/probos/cognitive/crew_session.py:55-62 CrewSessionState (discussing, executing, verifying,
  blocked_needs_captain, done, failed); :491-498 CrewRecoveryContract(plan); :1818-1830 CrewSessionContract(state,
  facilitator_id); :2315 CrewSessionWorkerResolver; :2334 __init__(worker_resolver=..., :2335
  require_worker_eligibility=False); :3259 agent_principal; :3282 bind_team_spec_lookup; :3288-3324
  get_team_binding (ValueError crew_session_team_binding_invalid :3323; docstring :3296-3297 hands plan currency
  to AD-1288); :3386 recovery.plan.plan_hash; :3449-3453 worker_eligibility (ValueError
  crew_session_worker_eligibility_unwired when required and unbound); :5415 get_session; :5575 get_recovery
Grep src/probos/cognitive/crew_assignment.py
  59-61 CrewWorkerEligibility(identity, reason); 64-65 CrewWorkerEligibilityResolver.check_eligibility(agent_id)
Grep src/probos/federation/ard/jcs.py: 53 def canonicalize(value)
Read tests/test_ad1287_slot_qualification.py:628-642 (_S1_MODULES five names, _GATE_NAMES six); :645 _gate_references;
  :692 _scan_tree; :714-761 test #16 (docstring :717-718 predicts this change; owned :722-723; S3's edit :736;
  scan :757-758). SEARCH texts of Sections 2, 3, 4 each occur once.
Grep tests/test_ad1287_profile_qualification_store.py: 91 _Clock; 233 _started; 244 _evaluation
Grep tests/test_ad1287_slot_qualification.py: 36-38 imports (_spec, _profile, _Clock, _evaluation, _started);
  88 _World; 124 _variant; 145 _in_state
Grep tests/test_ad1287_s2a_profile_currency.py: 48-51 imports from other test modules; 108 _FakeSource; 199 _current_source
Read tests/test_ad1286_elastic_team_contract.py:52-81 _KAT_SPEC (analyse pins a fixed ref; review capacity 1,
  max_attempts 2); 145 _spec; 150 _slot; 157 _review_slot
Read tests/test_ad1127_crew_session_lifecycle_recovery.py:467-496 _new_session (facilitator-1, no worker_resolver);
  521 _vector_plan_payload; 536 _vector_insert; 46 _VECTOR_PLAN_HASH
Read tests/test_ad1286_crew_session_team_binding.py:42-58 (imports the AD-1127 harness); :118-120 _plan_bound_spec
Grep "## Era V — Civilization (Phases 31-36)" DECISIONS.md: 1 (line 11); "# ProbOS Progress" PROGRESS.md: 1 (line 1);
  the AD-1288 roadmap row docs/development/roadmap.md:528: 1
Read scripts/gen_ad_ledger.py:127-139 (keywords case-insensitive; _HEAD_WINDOW = 120); the Section 5 heading and
  the Section 6 headline hold none in their first 120 characters
Read src/probos/startup/finalize.py:2044-2103 _wire_elastic_team_store (crew-gated; ElasticTeamStore(db_path=...)
  :2072; the S2 wiring site)
gh issue view 1335 --comments: one comment (O-1 amended, O-4, R-1..R-5, #1333's two checks)
```

## Absence Verified (2026-10-15, `52dcbfa7`)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A1 | Nothing in `src/` calls the gates, `record_attempt` or `record_attempt_outcome`, or names `elastic_commission` | Grep `\.record_attempt\(\|admit_current_qualified_attempt\(\|admit_qualified_attempt\(\|\.record_attempt_outcome\(\|elastic_commission\|ElasticCommission\|learn_attempt_outcome\(` in `src/probos` | `profile_currency.py:199,236`, `profile_qualification_store.py:1114,1147,1150` (the gates and the S3 producer themselves) | yes |
| A2 | The store does not enforce `capacity.maximum` | Grep `capacity` in `elastic_team_store.py` (file unchanged since `d936fc24`) | no match; `_admit_attempt` (`:692-765`) raises only slot, budget, ordinal, pin and supersedes codes (`:708-765`) | yes |
| A3 | No worker authority-lease concept exists to reuse in S1 | Grep `^class \w*Lease\w*\|^class ExecutionGrant\b` in `src/probos` | `work_item_steps.py:1780` OwnedExecutionLease, `llm_client.py:195` _ClientLease, `turn_promotion.py:646` _OwnershipLease, `execution/authority.py:472` ExecutionGrant | yes; S3 decides between AD-1315 grants and a new lease |
| A4 | No `commission` name collides in the new class | Grep `def commission\(` in `src/probos` | `acm.py:413` (ACM birth commissioning, another class) | yes |
| A5 | AD-1287 S3 does not edit the lines Sections 2-4 match | `git log -1 f66cced7` (S3 on the base); Read `tests/test_ad1287_slot_qualification.py:714-761` at `52dcbfa7` | S3 changed only `:736`; the three SEARCH texts each occur once | yes |
| A6 | No AD-1286/1287 test besides test #16 scans `src/` | Grep `rglob\|os\.walk\|glob\(\|_SRC_PROBOS\|src/probos\|SRC_ROOT` in `tests/test_ad128[678]*.py` | `slot_qualification.py:700,722,733,757` (test #16); `s2a_profile_components.py:71,76` (tmp fixtures); `execution_profile.py:44,236` (PYTHONPATH); S3 files none | yes |
| A7 | Dynamic pools can lose a member to the scaler (S2 blind spot) | Grep `\.remove_agent\(\|\.add_agent\(` in `src/probos` | `scaler.py:90,119,172,192`, `runtime.py:6755` (`trust.py:987` is the trust network, not a pool) | yes; S2 must use a pool the scaler does not manage |
| A8 | No test added since `d936fc24` scans for the new module's names | `git diff --name-status --diff-filter=A d936fc24 52dcbfa7 -- tests` (13 files), then Grep `ast\.parse\|rglob\|glob\(\|read_text\|read_bytes` in them | `bf892_spawn_env_guard.py:479` (process launches), `standing_orders_layout.py:245` (retired names), `bf890_command_env.py:119`, `bf891_procedure_store_lock.py:338,862` (their own modules); the rest read `tmp_path` | yes |

## Prior Art and Blind Spots

- **Internal.** AD-1286 D3/D4 (the owner of the session-membership and plan checks), AD-1287 S1 O-1 (recovery reads instead of re-admitting) and S2a D1 (the currency gate) are absorbed directly. The S1 `_World` real-store harness is reused for the tests.
- **Kubernetes StatefulSet ordinal identity** ([docs](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/), re-fetched 2026-10-15: "each Pod in the StatefulSet will be assigned an integer ordinal, that is unique over the Set"; on deletion "they are terminated in reverse order"): a member's identity is its ordinal within the set, not a request. **Adopted** as D1: AD-1286 already derives the id from the ordinal, so the owner names ordinals. The highest-ordinal-first scale-down is **rejected**: the owner chooses which attempt to release.
- **ResourceQuota admission** ([docs](https://kubernetes.io/docs/concepts/policy/resource-quotas/), re-fetched 2026-10-15: "the quota system tracks usage"; a create that "violates a quota constraint" is rejected with `403 Forbidden`): usage is checked when a create arrives and a create over the hard limit is refused. **Adapted:** capacity is checked over live attempts at admission. The fetched page does not say how concurrent creates are serialised, so ProbOS does not rely on that model: one in-process lock serialises admission (D8), and the cross-instance gap is named (R-S1-1).
- **Blind spots raised by this slice:** (0) AD-1287 S3 learns no `cancelled` outcome, so a release that ends a provisioned attempt would hide its failure from learning; O-S1-1 now forbids that for S2. (1) an owner that becomes ineligible mid-session cannot commission, and nothing escalates in S1. Principle #13c applies to work, and S1 ends no work; S4's sweeper must escalate an unavailable owner. (2) Released attempts consume the slot's `max_attempts` budget; that is honest, because the budget counts incarnations. (3) Per-attempt outcome reads cost one connection each, at most 1,024 per slot, accepted for S1. (4) "Commission" already means ACM birth commissioning (`acm.py:413`), so the module is named `elastic_commission` to keep the two apart.

## Mutation campaign of record

Anchors are single lines of `src/probos/cognitive/elastic_commission.py`, each occurring exactly once; replacements are literal. Section 1 did not change in the 2026-10-15 revision, so the table stands as drafted. Baseline: Sections 1-7 installed on `52dcbfa7`, and the three M files plus `tests/test_ad1287_slot_qualification.py` pass.

| Id | File | Anchor | Replacement | Killer |
|---|---|---|---|---|
| C1 | src/probos/cognitive/elastic_commission.py | `if commissioning and session.state not in _OPEN_SESSION_STATES:` | `if False:` | M2 #2 state_verifying |
| C2 | src/probos/cognitive/elastic_commission.py | `if owner_id != session.facilitator_id:` | `if False:` | M2 #2 owner_not_facilitator |
| C3 | src/probos/cognitive/elastic_commission.py | `if eligibility is None or eligibility.check_eligibility(owner_id).identity is None:` | `if eligibility is None:` | M2 #2 owner_ineligible |
| C4 | src/probos/cognitive/elastic_commission.py | `if commissioning and binding.team_spec_ref != team_spec_ref:` | `if False:` | M2 #2 team_mismatch |
| C5 | src/probos/cognitive/elastic_commission.py | `if recovery is None or recovery.plan is None or recovery.plan.plan_hash != plan_hash:` | `if recovery is None or recovery.plan is None:` | M2 #2 plan_other_hash; M3 #2 |
| C6 | src/probos/cognitive/elastic_commission.py | `if existing.content_ref() != attempt.content_ref():` | `if False:` | M2 #3 ordinal_reused_new_profile |
| C7 | src/probos/cognitive/elastic_commission.py | `continue  # acknowledged from the store, never re-admitted (S1 O-1)` | `pass` | M2 #8 |
| C8 | src/probos/cognitive/elastic_commission.py | `if reservation.ordinal > slot.budget.max_attempts:` | `if False:` | M2 #3 budget_exhausted |
| C9 | src/probos/cognitive/elastic_commission.py | `if reservation.ordinal != next_ordinal:` | `if False:` | M2 #3 ordinal_gap |
| C10 | src/probos/cognitive/elastic_commission.py | `or predecessor in replaced` | `or False` | M2 #3 replace_already_replaced |
| C11 | src/probos/cognitive/elastic_commission.py | `or outcomes[predecessor].terminal_status not in _REPLACEABLE_STATUSES` | `or False` | M2 #3 replace_succeeded |
| C12 | src/probos/cognitive/elastic_commission.py | `if len(live_keys) >= slot.capacity.maximum:` | `if len(live_keys) > slot.capacity.maximum:` | M2 #4 |
| C13 | src/probos/cognitive/elastic_commission.py | `if drifts:` | `if False:` | M2 #5 component_drift_skill |
| C14 | src/probos/cognitive/elastic_commission.py | `if key is not None and key in live_keys and len(set(live_keys)) < slot.independence.min_distinct:` | `if key is not None and key in live_keys and len(set(live_keys)) <= slot.independence.min_distinct:` | M2 #6 |
| C15 | src/probos/cognitive/elastic_commission.py | `return (profile.model.provider, profile.model.name)` | `return (profile.model.provider, profile.model.version)` | M2 #7 |
| C16 | src/probos/cognitive/elastic_commission.py | `if mode == "distinct_profiles":` | `if mode == "distinct_profiles_disabled":` | M2 #6 |
| C17 | src/probos/cognitive/elastic_commission.py | `if predecessor is not None:` | `if False:` | M2 #3 replace_twice_in_one_request |
| C18 | src/probos/cognitive/elastic_commission.py | `if ended is not None and (ended.terminal_status, ended.error_code) != ("cancelled", RELEASE_ERROR_CODE):` | `if False:` | M2 #10 ended_failed |
| C19 | src/probos/cognitive/elastic_commission.py | `or attempt.session_id != request.session_id` | `or False` | M2 #10 other_session |
| C20 | src/probos/cognitive/elastic_commission.py | `or attempt.team_spec_ref != spec.content_ref()` | `or False` | M2 #10 other_spec |
| C21 | src/probos/cognitive/elastic_commission.py | `except ElasticTeamIntegrityError:` | `except ZeroDivisionError:` | M2 #12 |
| C22 | src/probos/cognitive/elastic_commission.py | `async with self._lock:  # one admission at a time: reads and writes never interleave` | `if True:` | M2 #15 |
| C23 | src/probos/cognitive/elastic_commission.py | `if len(set(keys)) != len(keys):` | `if False:` | M1 #3 |
| C24 | src/probos/cognitive/elastic_commission.py | `if any((ord(char) < 32 and char not in "\t\n") or ord(char) == 127 for char in value):` | `if False:` | M1 #5 nul |
| C25 | src/probos/cognitive/elastic_commission.py | `_REQUEST_DOMAIN: Final = b"probos.elastic_team/commission_request/v1\x00"` | `_REQUEST_DOMAIN: Final = b"probos.elastic_team/commission_request/v2\x00"` | M1 #2 |
| C26 | src/probos/cognitive/elastic_commission.py | `RELEASE_ERROR_CODE: Final = "released_by_owner"` | `RELEASE_ERROR_CODE: Final = "released"` | M2 #9 (asserts the literal) |
| C27 | src/probos/cognitive/elastic_commission.py | `_OPEN_SESSION_STATES: Final = frozenset({"discussing", "executing"})` | `_OPEN_SESSION_STATES: Final = frozenset({"discussing", "executing", "verifying"})` | M2 #2 state_verifying |
| C28 | src/probos/cognitive/elastic_commission.py | `if type(now) is not float or not math.isfinite(now) or now < 0.0:` | `if type(now) is not float:` | M2 #11 |
| C29 | src/probos/cognitive/elastic_commission.py | `return (profile.model.provider, profile.model.name)` | `return profile.model.name` | M2 #7 `[provider]` (added after review round 1, F1) |

Mutants C8, C9, C11 and C17 would otherwise be caught late by `ElasticTeamStore` with `ElasticTeamConflict`. Their killers must assert `CommissionRefused` with the exact code AND "wrote nothing", including earlier reservations of the same request.

## Milestones

| M | Scope | Calls (about) |
|---|---|---|
| Install | Sections 1-7, ledger regeneration, full-suite diagnostic (orchestrator) | n/a |
| M1 | `tests/test_ad1288_s1_commission_request.py` | 60 |
| M2 | `tests/test_ad1288_s1_commission_admission.py` | 150 |
| M3 | `tests/test_ad1288_s1_commission_chain.py`, then the focused gate (acceptance 9) | 120 |
| Campaign | the table above, once, on the committed tree | n/a |

=== BUILDER BRIEFS ===

### Brief M1 -- `tests/test_ad1288_s1_commission_request.py`

Write tests only; never edit `src/`. Target: `probos.cognitive.elastic_commission` (`CommissionRequest`, `SlotReservation`, `ReleaseRequest`, `CommissionReceipt`, `SlotView`, `TeamView`, `RELEASE_ERROR_CODE`). Implement M1 #1-8 from the contract `prompts/ad-1288-s1-commission-admission.md`, "Tests" section. Rules: each test asserts its own premise and has a negative control; validation errors surface as `pydantic.ValidationError` whose message contains the code (`commission_reservations_invalid`, `commission_reservation_duplicate`, `commission_rationale_invalid`, `elastic_team_ref_set_invalid`). For the known answer in #2, compute the expected digest in the test with `hashlib` and `probos.federation.ard.jcs.canonicalize`; never call `content_ref` to build the expectation. Valid ids match `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`; refs are 64 lowercase hex characters. Mutants this file must kill: C23 (#3), C24 (#5 `nul`), C25 (#2). Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1288_s1_commission_request.py -q -n 0`. Stop and report if any test cannot pass against the frozen source; do not weaken it.

### Brief M2 -- `tests/test_ad1288_s1_commission_admission.py`

Write tests only; never edit `src/`. Target: `ElasticCommissionService` over a REAL `ElasticTeamStore` and a REAL `ProfileQualificationStore` in `tmp_path`, with `_FakeSessions` (settable session `state`/`facilitator_id`, recovery `.plan.plan_hash`, a real `CrewElasticTeamBinding.for_spec(spec)`, a `worker_eligibility` that is a `_FakeEligibility`, None, or a property raising `ValueError`) and `_FakeSource` components. Import, do not copy (precedent `tests/test_ad1287_s2a_profile_currency.py:48-51`): `_World`, `_variant`, `_in_state` from `tests.test_ad1287_slot_qualification`; `_Clock`, `_evaluation` from `tests.test_ad1287_profile_qualification_store`; `_FakeSource`, `_current_source` from `tests.test_ad1287_s2a_profile_currency`; `_spec`, `_slot`, `_review_slot` from `tests.test_ad1286_elastic_team_contract`. Build `_World(tmp_path)` in a local fixture (`stop()` then `start()` is a restart). Commission into the `review` slot (its role and task class match `_variant` profiles; `analyse` pins a fixed ref). It holds capacity 1 and `max_attempts` 2, so for capacity, budget and independence tests store `_spec(slots=[_slot(), _review_slot(capacity=..., independence=..., budget=...)])` with `put_team_spec`, keeping `max_attempts >= capacity.maximum >= min_distinct`. `_variant("x", **{"model.provider": ...})` and `**{"model.name": ...}` vary the provider and the model name for #7. Implement M2 #1-16 from the contract. "Wrote nothing" = every slot's `list_slot_attempts` plus `get_attempt_outcome` snapshot is equal before and after. Each refusal asserts the exact `CommissionRefused` code (`str(exc)`) and has its accepted control. Killers you own: C1-C22, C26-C29 (see the contract's mutation table). C8, C9, C11 and C17 need BOTH the exact code and "wrote nothing" for earlier reservations of the same request. #15 needs the barrier premise control. Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1288_s1_commission_admission.py -q -n 0`. Stop and report a frozen-source defect rather than weakening a test.

### Brief M3 -- `tests/test_ad1288_s1_commission_chain.py`

Write tests only; never edit `src/`. Implement M3 #1-5 from the contract. Use a real `WorkItemStore` (`SQLiteConnectionFactory()`), `ChatThreadStore`, `ElasticTeamStore` and `ProfileQualificationStore` in `tmp_path`. You may import `_new_session`, `_vector_plan_payload`, `_vector_insert` and `_VECTOR_PLAN_HASH` from `tests.test_ad1127_crew_session_lifecycle_recovery` (precedent: `tests/test_ad1286_crew_session_team_binding.py:42-58`), `_plan_bound_spec` from `tests.test_ad1286_crew_session_team_binding` (`:118`), `_Clock`, `_started`, `_evaluation` from `tests.test_ad1287_profile_qualification_store`, `_current_source` from `tests.test_ad1287_s2a_profile_currency`, `_spec`, `_slot`, `_review_slot` from `tests.test_ad1286_elastic_team_contract`, and `_profile` from `tests.test_ad1287_execution_profile` (build a profile as `ExecutionProfile.model_validate(_profile(**{"model.version": v}))`, which is what `_variant` does). Commission into the `review` slot; it holds capacity 1 and `max_attempts` 2, so #1 (two attempts plus a replacement) and #3 (capacity 3, five commissions) bind a spec built with `_spec(slots=[_slot(), _review_slot(capacity=..., budget=...)])`. Do not import `tests.test_ad1287_slot_qualification` (#5 reads its text). Bind with the real `CrewSessionService.bind_team_spec` after `bind_team_spec_lookup(store)`. For admission, construct a second `CrewSessionService(work_item_store=..., chat_thread_store=..., worker_resolver=_FakeResolver())`, where `_FakeResolver.check_eligibility` returns an object with `.identity` set only for `facilitator-1` and `.resolve` raises. A restart means closing every store and constructing new instances of every store and service. #1 is the seam test: commission, restart, identical replay acknowledged, release, restart, replacement, restart, `team_view`, and work-item rows byte-identical (canonical JSON) before and after. #4 is an AST scan with non-vacuity controls in a scratch tree. Then run the focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1288_s1_commission_request.py tests/test_ad1288_s1_commission_admission.py tests/test_ad1288_s1_commission_chain.py -q -n 0`, then `tests/test_ad1287_slot_qualification.py tests/test_ad1287_s2b_drift_recorder.py -q -n 0`. Report the counts.
