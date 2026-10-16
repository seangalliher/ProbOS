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
