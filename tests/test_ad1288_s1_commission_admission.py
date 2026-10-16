"""AD-1288 S1 (M2): the commission admission rules on real team and qualification stores, with fake sessions.

Contract: ``prompts/ad-1288-s1-commission-admission.md``, Tests, M2 (16 tests), and its mutation table (C1-C22,
C26-C28). Beyond the sixteen, a few extra tests pin branches the sixteen leave open: the open session states, a spec
with no plan, an unknown live profile under ``distinct_models``, the modes that never refuse a repeat, release ignoring
the session state and the plan (the controls #10 names), released attempts still consuming the attempt budget (the
contract's blind spot 2), and ``team_view`` on a spec the store does not hold.
``ElasticCommissionService`` runs over a REAL ``ElasticTeamStore`` and ``ProfileQualificationStore`` in ``tmp_path``
(``_World``: two files) with a ``_FakeSessions`` that answers the four ``CommissionSessions`` reads from settable
attributes and notes every call, and a ``_FakeSource`` that reports every component current unless a test says
otherwise. Nothing here uses a mock library. ``_World``, ``_variant`` and ``_in_state`` come from AD-1287's slot tests,
``_Clock`` from its store tests, ``_FakeSource`` and ``_current_source`` from S2a's, and ``_spec``, ``_review_slot``
and ``_attempt`` from AD-1286's contract tests.

The spec in use has two reviewer slots, ``audit`` and ``review`` (the KAT ``analyse`` slot pins a fixed profile, so
nothing commissions into it); ``_variant`` profiles meet both. ``review`` takes the capacity, the attempt budget and
the independence policy a test needs.

"Wrote nothing" means a snapshot of every slot's attempts and of each attempt's outcome (``list_slot_attempts`` and
``get_attempt_outcome``) is equal before and after. Every refusal asserts its exact code, and each has its accepted
neighbour: the same request once the one defect is undone, or the identical request that was valid all along. Where
a refusal sits behind an earlier valid reservation of the same request, that reservation is part of the snapshot too:
a check that ran late (at the store, after the earlier attempt was recorded) would change both the error type and
the snapshot.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import probos.cognitive.elastic_commission as commission_module
from probos.cognitive.elastic_commission import (
    CommissionReceipt,
    CommissionRefused,
    CommissionRequest,
    ElasticCommissionService,
    ReleaseRequest,
    SlotReservation,
    SlotView,
    TeamView,
)
from probos.cognitive.elastic_team import (
    CrewElasticTeamBinding,
    ElasticTeamSpec,
    WorkerAttempt,
    WorkerAttemptOutcome,
    derive_worker_attempt_id,
)
from probos.cognitive.elastic_team_store import ElasticTeamIntegrityError
from probos.cognitive.profile_currency import LiveSkill, profile_drift
from probos.cognitive.profile_qualification_store import SlotAdmissionRefused
from tests.test_ad1286_elastic_team_contract import _attempt, _review_slot, _spec
from tests.test_ad1287_profile_qualification_store import _Clock
from tests.test_ad1287_s2a_profile_currency import _FakeSource, _current_source
from tests.test_ad1287_slot_qualification import _World, _in_state, _variant

_LOGGER = commission_module.logger.name
_SESSION = "session-1"
_OWNER = "facilitator-1"
_RATIONALE = "AD-1288 S1: reserve the reviewers this session needs"
_PLAN = "c" * 64
_OTHER_PLAN = "d" * 64
_CHANGED = "9" * 64  # a digest no fixture profile declares
_UNKNOWN_ATTEMPT = "wa-" + "0" * 64  # a well-formed attempt id that no attempt carries
_PLAN_PROCESS: dict[str, Any] = {"bill": {"bill_id": "incident-review", "bill_version": 3}, "plan_hash": _PLAN}


# --------------------------------------------------------------------------------------
# Test doubles
# --------------------------------------------------------------------------------------


@dataclass
class _FakeSession:
    """The two session fields admission reads."""

    state: str
    facilitator_id: str


@dataclass(frozen=True)
class _FakePlan:
    plan_hash: str


@dataclass(frozen=True)
class _FakeRecovery:
    plan: _FakePlan | None


@dataclass(frozen=True)
class _FakeVerdict:
    """What ``check_eligibility`` returns: an identity when the agent is eligible, None when it is not."""

    identity: str | None


class _FakeEligibility:
    """A worker-eligibility resolver that reports an identity for the agents it was given and none for anyone else."""

    def __init__(self, *eligible: str) -> None:
        self.eligible = set(eligible)
        self.asked: list[str] = []

    def check_eligibility(self, agent_id: str) -> _FakeVerdict:
        self.asked.append(agent_id)
        return _FakeVerdict("identity" if agent_id in self.eligible else None)


class _FakeSessions:
    """The four ``CommissionSessions`` reads, answered from settable attributes; every call is noted in ``calls``.

    It answers every session id alike, so a test names another session only in its request. ``unwired`` makes
    ``worker_eligibility`` raise as ``CrewSessionService`` does when a resolver is required and absent, and
    ``binding_error`` makes ``get_team_binding`` raise.
    """

    def __init__(
        self,
        session: _FakeSession | None,
        recovery: _FakeRecovery | None,
        binding: CrewElasticTeamBinding | None,
        resolver: _FakeEligibility | None,
    ) -> None:
        self.session = session
        self.recovery = recovery
        self.binding = binding
        self.resolver = resolver
        self.binding_error: BaseException | None = None
        self.unwired = False
        self.calls: list[tuple[str, str | None]] = []

    async def get_session(self, parent_id: str) -> _FakeSession | None:
        self.calls.append(("get_session", parent_id))
        return self.session

    async def get_recovery(self, parent_id: str) -> _FakeRecovery | None:
        self.calls.append(("get_recovery", parent_id))
        return self.recovery

    async def get_team_binding(self, parent_id: str) -> CrewElasticTeamBinding | None:
        self.calls.append(("get_team_binding", parent_id))
        if self.binding_error is not None:
            raise self.binding_error
        return self.binding

    @property
    def worker_eligibility(self) -> _FakeEligibility | None:
        self.calls.append(("worker_eligibility", None))
        if self.unwired:
            raise ValueError("crew_session_worker_eligibility_unwired")
        return self.resolver


class _FakeBarrierSource(_FakeSource):
    """The first ``skill_state`` question waits up to ``wait`` seconds for a second one to arrive while it is open.

    ``overlapped`` records whether a second question arrived. Later questions answer at once (still noting overlap),
    so one commission that holds the lock costs one wait, and two that run side by side release each other.
    ``release()`` ends the wait when the test knows no second question is coming.
    """

    def __init__(self, skills: dict[str, Any], tools: dict[str, Any], wait: float = 0.2) -> None:
        super().__init__(skills, tools)
        self.wait = wait
        self.overlapped = False
        self._open = 0
        self._waited = False
        self._second_arrived = asyncio.Event()

    def release(self) -> None:
        """End the first question's wait now, without recording an overlap: the test knows no second asker is coming."""
        self._second_arrived.set()

    async def skill_state(self, skill_name: str) -> Any:
        self._open += 1
        try:
            if self._open > 1:
                self.overlapped = True
                self._second_arrived.set()
            elif not self._waited:
                self._waited = True
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._second_arrived.wait(), timeout=self.wait)
            return await super().skill_state(skill_name)
        finally:
            self._open -= 1


class _FakeFlipSource(_FakeSource):
    """Current for its first ``current_checks`` profile checks, then reports every tool schema as changed.

    One ``profile_drift`` asks every skill and then every tool, and the fixture profile declares exactly one tool, so
    each check is one ``tool_schema_digest`` question and counting those counts the checks (in ``checks``).
    """

    def __init__(self, skills: dict[str, Any], tools: dict[str, Any], current_checks: int) -> None:
        super().__init__(skills, tools)
        self.current_checks = current_checks
        self.checks = 0

    async def tool_schema_digest(self, tool_id: str) -> Any:
        self.checks += 1
        if self.checks > self.current_checks:
            self.tool_questions.append(tool_id)
            return _CHANGED
        return await super().tool_schema_digest(tool_id)


# --------------------------------------------------------------------------------------
# The rig
# --------------------------------------------------------------------------------------


def _team(
    maximum: int = 1, attempts: int = 2, mode: str = "none", distinct: int = 1, **overrides: Any
) -> ElasticTeamSpec:
    """Two reviewer slots, ``audit`` and ``review``; ``review`` takes the capacity maximum, attempt budget and policy.

    ``overrides`` replace top-level spec keys (``revision``, ``process``). The defaults are the KAT review slot.
    """
    base = _review_slot()
    review = _review_slot(
        capacity={**base["capacity"], "maximum": maximum},
        independence={"mode": mode, "min_distinct": distinct},
        budget={**base["budget"], "max_attempts": attempts},
    )
    return _spec(slots=[_review_slot(slot_id="audit"), review], **overrides)


def _res(slot_id: str, ordinal: int, profile_ref: str, supersedes: str | None = None) -> SlotReservation:
    return SlotReservation(
        slot_id=slot_id, ordinal=ordinal, execution_profile_ref=profile_ref, supersedes_attempt_id=supersedes
    )


def _earlier(profile_ref: str) -> SlotReservation:
    """A valid reservation that sorts before every ``review`` reservation: it is admitted before a later one fails."""
    return _res("audit", 1, profile_ref)


@dataclass
class _Rig:
    """One commission service over the world's two real stores and a ``_FakeSessions`` bound to ``spec``."""

    world: _World
    spec: ElasticTeamSpec
    sessions: _FakeSessions
    source: _FakeSource
    clock: _Clock
    service: ElasticCommissionService
    specs: list[ElasticTeamSpec]  # every spec the rig stored, bound or not: the snapshot reads them all

    @property
    def ref(self) -> str:
        return self.spec.content_ref()

    def make_service(
        self, *, components: _FakeSource | None = None, clock: _Clock | None = None
    ) -> ElasticCommissionService:
        """Another service over the same stores and sessions, with other components or another clock."""
        return ElasticCommissionService(
            sessions=self.sessions,
            teams=self.world.teams,
            profiles=self.world.qualifications,
            components=self.source if components is None else components,
            clock=self.clock if clock is None else clock,
        )

    def request(
        self,
        *reservations: SlotReservation,
        owner_id: str = _OWNER,
        session_id: str = _SESSION,
        spec: ElasticTeamSpec | None = None,
    ) -> CommissionRequest:
        return CommissionRequest(
            schema_version=1,
            session_id=session_id,
            team_spec_ref=(self.spec if spec is None else spec).content_ref(),
            owner_id=owner_id,
            reservations=list(reservations),
            rationale=_RATIONALE,
            evidence_refs=[],
        )

    def release_request(
        self, attempt_id: str, *, owner_id: str = _OWNER, session_id: str = _SESSION
    ) -> ReleaseRequest:
        return ReleaseRequest(schema_version=1, session_id=session_id, owner_id=owner_id, worker_attempt_id=attempt_id)

    def attempt_id(self, slot_id: str, ordinal: int) -> str:
        return derive_worker_attempt_id(
            team_spec_ref=self.ref, session_id=_SESSION, slot_id=slot_id, ordinal=ordinal
        )

    async def store(self, spec: ElasticTeamSpec) -> None:
        await self.world.teams.put_team_spec(spec)
        self.specs.append(spec)

    async def seed(
        self,
        slot_id: str,
        ordinal: int,
        profile_ref: str,
        supersedes: str | None = None,
        *,
        end: str | None = None,
        spec: ElasticTeamSpec | None = None,
    ) -> WorkerAttempt:
        """Record an attempt straight in the team store (set-up, not the code under test), optionally ended."""
        attempt = await self.world.teams.record_attempt(
            _attempt(
                team_spec_ref=(self.spec if spec is None else spec).content_ref(),
                session_id=_SESSION,
                slot_id=slot_id,
                ordinal=ordinal,
                execution_profile_ref=profile_ref,
                supersedes_attempt_id=supersedes,
            )
        )
        if end is not None:
            await self.end(attempt, end)
        return attempt

    async def end(
        self, attempt: WorkerAttempt, status: str = "failed", error_code: str | None = None
    ) -> WorkerAttemptOutcome:
        """Record an outcome straight in the team store (set-up): ``succeeded`` carries no code, the rest one."""
        return await self.world.teams.record_attempt_outcome(
            WorkerAttemptOutcome(
                worker_attempt_id=attempt.worker_attempt_id,
                terminal_status=status,
                error_code=None if status == "succeeded" else (error_code or "worker_failed"),
                recorded_at=1500.0,
            )
        )

    async def snapshot(self) -> dict[tuple[str, str], tuple[tuple[WorkerAttempt, WorkerAttemptOutcome | None], ...]]:
        """Every slot's attempts with their outcomes, for every spec the rig stored: what "wrote nothing" compares."""
        teams = self.world.teams
        state: dict[tuple[str, str], tuple[tuple[WorkerAttempt, WorkerAttemptOutcome | None], ...]] = {}
        for spec in self.specs:
            ref = spec.content_ref()
            for slot in spec.slots:
                attempts = await teams.list_slot_attempts(session_id=_SESSION, team_spec_ref=ref, slot_id=slot.slot_id)
                rows: list[tuple[WorkerAttempt, WorkerAttemptOutcome | None]] = []
                for attempt in attempts:
                    rows.append((attempt, await teams.get_attempt_outcome(attempt.worker_attempt_id)))
                state[(ref, slot.slot_id)] = tuple(rows)
        return state

    async def live(self, slot_id: str) -> int:
        """How many attempts of ``slot_id`` in the bound spec have no outcome."""
        return sum(1 for _, outcome in (await self.snapshot())[(self.ref, slot_id)] if outcome is None)


async def _rig(world: _World, spec: ElasticTeamSpec | None = None, *, state: str = "executing") -> _Rig:
    """A session in ``state``, its facilitator ``_OWNER`` eligible, bound to ``spec`` (stored), components current."""
    spec = _team() if spec is None else spec
    await world.teams.put_team_spec(spec)
    sessions = _FakeSessions(
        session=_FakeSession(state, _OWNER),
        recovery=_FakeRecovery(_FakePlan(_PLAN)),
        binding=CrewElasticTeamBinding.for_spec(spec),
        resolver=_FakeEligibility(_OWNER),
    )
    source = _current_source(_variant("components"))
    clock = _Clock(5000.0)
    service = ElasticCommissionService(
        sessions=sessions, teams=world.teams, profiles=world.qualifications, components=source, clock=clock
    )
    return _Rig(world, spec, sessions, source, clock, service, [spec])


async def _refused(rig: _Rig, request: CommissionRequest, code: str) -> CommissionRefused:
    """``commission`` refuses ``request`` with exactly ``code`` and the stores hold exactly what they held before."""
    before = await rig.snapshot()
    with pytest.raises(CommissionRefused) as caught:
        await rig.service.commission(request)
    assert type(caught.value) is CommissionRefused
    assert str(caught.value) == code
    assert await rig.snapshot() == before
    return caught.value


async def _release_refused(rig: _Rig, request: ReleaseRequest, code: str) -> None:
    before = await rig.snapshot()
    with pytest.raises(CommissionRefused) as caught:
        await rig.service.release(request)
    assert type(caught.value) is CommissionRefused
    assert str(caught.value) == code
    assert await rig.snapshot() == before


@pytest.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    opened = _World(tmp_path)
    await opened.start()
    try:
        yield opened
    finally:
        await opened.stop()


# --------------------------------------------------------------------------------------
# 1. The happy path
# --------------------------------------------------------------------------------------


async def test_commission_records_exact_attempts_in_slot_and_ordinal_order(world: _World) -> None:
    rig = await _rig(world, _team(maximum=2, attempts=3))
    p1 = await _in_state(world, "qualified", "p1")
    p2 = await _in_state(world, "qualified", "p2")
    assert all(not rows for rows in (await rig.snapshot()).values())  # premise: nothing is recorded yet
    # given out of order on purpose: the request sorts them by (slot, ordinal)
    request = rig.request(_res("review", 2, p2), _res("review", 1, p1), _res("audit", 1, p1))

    receipt = await rig.service.commission(request)

    order = [("audit", 1, p1), ("review", 1, p1), ("review", 2, p2)]
    assert [attempt.worker_attempt_id for attempt in receipt.recorded] == [
        derive_worker_attempt_id(team_spec_ref=rig.ref, session_id=_SESSION, slot_id=slot_id, ordinal=ordinal)
        for slot_id, ordinal, _ in order
    ]
    assert receipt.recorded == tuple(
        _attempt(
            team_spec_ref=rig.ref,
            session_id=_SESSION,
            slot_id=slot_id,
            ordinal=ordinal,
            execution_profile_ref=profile_ref,
            supersedes_attempt_id=None,
        )
        for slot_id, ordinal, profile_ref in order
    )
    assert receipt.acknowledged == ()
    assert receipt.request_ref == request.content_ref()
    for attempt in receipt.recorded:
        assert await world.teams.get_attempt(attempt.worker_attempt_id) == attempt
        assert await world.teams.get_attempt_outcome(attempt.worker_attempt_id) is None  # reserved, not ended
    snapshot = await rig.snapshot()
    assert [a for a, _ in snapshot[(rig.ref, "audit")]] == [receipt.recorded[0]]
    assert [a for a, _ in snapshot[(rig.ref, "review")]] == list(receipt.recorded[1:])


# --------------------------------------------------------------------------------------
# 2. Authorization: each refusal writes nothing; undoing the one defect admits the same request
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Defective:
    """A rig with exactly one authorization defect applied, the request it refuses and the undo that admits it."""

    rig: _Rig
    code: str
    request: CommissionRequest
    repair: Callable[[], Awaitable[None]]


def _swap(sessions: _FakeSessions, **changes: Any) -> Callable[[], Awaitable[None]]:
    """Set the named attributes now; the returned coroutine function puts the old values back."""
    saved = {name: getattr(sessions, name) for name in changes}
    for name, value in changes.items():
        setattr(sessions, name, value)

    async def repair() -> None:
        for name, value in saved.items():
            setattr(sessions, name, value)

    return repair


async def _plain(world: _World, profile: str, code: str, **defect: Any) -> _Defective:
    rig = await _rig(world)
    return _Defective(rig, code, rig.request(_res("review", 1, profile)), _swap(rig.sessions, **defect))


async def _owner_not_facilitator(world: _World, profile: str) -> _Defective:
    defective = await _plain(
        world, profile, "commission_owner_unauthorized", session=_FakeSession("executing", "facilitator-2")
    )
    resolver = defective.rig.sessions.resolver
    assert resolver is not None
    assert resolver.check_eligibility(_OWNER).identity is not None  # premise: the requesting owner IS eligible
    return defective


async def _owner_ineligible(world: _World, profile: str) -> _Defective:
    defective = await _plain(
        world, profile, "commission_owner_unavailable", resolver=_FakeEligibility("facilitator-2")
    )
    assert defective.rig.sessions.session is not None
    assert defective.rig.sessions.session.facilitator_id == _OWNER  # premise: the owner IS the facilitator
    return defective


async def _team_mismatch(world: _World, profile: str) -> _Defective:
    rig = await _rig(world)
    other = _team(revision=2)  # a stored spec that is not the one the request names
    await rig.store(other)
    request = rig.request(_res("review", 1, profile))
    assert other.content_ref() != request.team_spec_ref
    return _Defective(
        rig, "commission_team_mismatch", request, _swap(rig.sessions, binding=CrewElasticTeamBinding.for_spec(other))
    )


async def _spec_unknown(world: _World, profile: str) -> _Defective:
    rig = await _rig(world)
    unstored = _team(revision=2)
    assert await world.teams.get_team_spec(unstored.content_ref()) is None  # premise: the store holds no such spec
    _swap(rig.sessions, binding=CrewElasticTeamBinding.for_spec(unstored))  # the session and the request name it

    async def repair() -> None:
        await rig.store(unstored)  # the binding keeps naming it: the one thing missing was the stored spec

    request = rig.request(_res("review", 1, profile), spec=unstored)
    return _Defective(rig, "commission_team_spec_unknown", request, repair)


async def _planned(world: _World, profile: str, **defect: Any) -> _Defective:
    rig = await _rig(world, _team(process=_PLAN_PROCESS))
    assert rig.spec.process.plan_hash == _PLAN  # premise: the spec names a plan; the session's own plan matches it
    assert rig.sessions.recovery is not None and rig.sessions.recovery.plan is not None
    assert rig.sessions.recovery.plan.plan_hash == _PLAN
    request = rig.request(_res("review", 1, profile))
    return _Defective(rig, "commission_plan_stale", request, _swap(rig.sessions, **defect))


_AUTHORIZATION: dict[str, Callable[[_World, str], Awaitable[_Defective]]] = {
    "session_unknown": lambda w, p: _plain(w, p, "commission_session_unknown", session=None),
    "state_verifying": lambda w, p: _plain(
        w, p, "commission_session_state_invalid", session=_FakeSession("verifying", _OWNER)
    ),
    "state_done": lambda w, p: _plain(w, p, "commission_session_state_invalid", session=_FakeSession("done", _OWNER)),
    "owner_not_facilitator": _owner_not_facilitator,
    "resolver_none": lambda w, p: _plain(w, p, "commission_owner_unavailable", resolver=None),
    "resolver_raises": lambda w, p: _plain(w, p, "commission_owner_unavailable", unwired=True),
    "owner_ineligible": _owner_ineligible,
    "unbound": lambda w, p: _plain(w, p, "commission_team_unbound", binding=None),
    "binding_invalid": lambda w, p: _plain(
        w, p, "commission_team_binding_invalid", binding_error=ValueError("crew_elastic_team_binding_invalid")
    ),
    "team_mismatch": _team_mismatch,
    "spec_unknown": _spec_unknown,
    "plan_no_recovery": lambda w, p: _planned(w, p, recovery=None),
    "plan_other_hash": lambda w, p: _planned(w, p, recovery=_FakeRecovery(_FakePlan(_OTHER_PLAN))),
    "plan_not_installed": lambda w, p: _planned(w, p, recovery=_FakeRecovery(None)),
}


@pytest.mark.parametrize("case", list(_AUTHORIZATION))
async def test_authorization_refusals_write_nothing(world: _World, case: str) -> None:
    profile = await _in_state(world, "qualified", "p1")
    defective = await _AUTHORIZATION[case](world, profile)

    await _refused(defective.rig, defective.request, defective.code)

    # the accepted neighbour: undo the one defect and the same request is admitted (a retry that had been
    # acknowledged, not recorded, would show that the refused call had written)
    await defective.repair()
    receipt = await defective.rig.service.commission(defective.request)
    assert len(receipt.recorded) == 1
    assert receipt.acknowledged == ()


@pytest.mark.parametrize("state", ["discussing", "executing"])
async def test_open_session_states_are_accepted(world: _World, state: str) -> None:
    rig = await _rig(world, state=state)
    profile = await _in_state(world, "qualified", "p1")

    receipt = await rig.service.commission(rig.request(_res("review", 1, profile)))

    assert len(receipt.recorded) == 1


async def test_a_spec_without_a_plan_never_asks_the_session_for_one(world: _World) -> None:
    rig = await _rig(world)  # the KAT spec names a bill only
    profile = await _in_state(world, "qualified", "p1")
    assert rig.spec.process.plan_hash is None
    rig.sessions.recovery = None  # no plan is installed, and none is needed

    receipt = await rig.service.commission(rig.request(_res("review", 1, profile)))

    assert len(receipt.recorded) == 1
    assert "get_recovery" not in [name for name, _ in rig.sessions.calls]


# --------------------------------------------------------------------------------------
# 3. Reservation rules: each refusal writes nothing, including the earlier valid reservation of the same request
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Reserving:
    """A refused request (``bad``), its accepted neighbour (``good``) and what must change between them (``fix``)."""

    code: str
    bad: tuple[SlotReservation, ...]
    good: tuple[SlotReservation, ...]
    fix: Callable[[], Awaitable[None]] | None = None


async def _slot_unknown(rig: _Rig, p1: str, p2: str) -> _Reserving:
    return _Reserving(
        "commission_slot_unknown",
        bad=(_earlier(p1), _res("ghost", 1, p1)),
        good=(_earlier(p1), _res("review", 1, p1)),
    )


async def _conflict(rig: _Rig, p1: str, p2: str) -> _Reserving:
    await rig.seed("review", 1, p1)  # recorded without a predecessor; the request asks for the same ordinal with one
    return _Reserving(
        "commission_reservation_conflict",
        bad=(_earlier(p1), _res("review", 1, p1, "some-other-attempt")),
        good=(_earlier(p1), _res("review", 1, p1)),
    )


async def _budget_exhausted(rig: _Rig, p1: str, p2: str) -> _Reserving:
    assert rig.spec.slot("review").budget.max_attempts == 4  # premise: ordinal 5 is one past the attempt budget
    for ordinal in (1, 2, 3):
        await rig.seed("review", ordinal, p1, end="failed")  # all ended, so capacity is never the obstacle
    return _Reserving(
        "commission_budget_exhausted",
        bad=(_earlier(p1), _res("review", 4, p1), _res("review", 5, p1)),
        good=(_earlier(p1), _res("review", 4, p1)),
    )


async def _ordinal_gap(rig: _Rig, p1: str, p2: str) -> _Reserving:
    return _Reserving(
        "commission_ordinal_invalid",
        bad=(_earlier(p1), _res("review", 2, p1)),  # the slot holds no attempt, so ordinal 1 is next
        good=(_earlier(p1), _res("review", 1, p1)),
    )


async def _ordinal_reused_new_profile(rig: _Rig, p1: str, p2: str) -> _Reserving:
    assert p1 != p2
    await rig.seed("review", 1, p1)
    return _Reserving(
        "commission_reservation_conflict",
        bad=(_earlier(p1), _res("review", 1, p2)),  # ordinal 1 holds p1; p2 is qualified and current, but not p1
        good=(_earlier(p1), _res("review", 1, p1)),
    )


async def _replace_unknown(rig: _Rig, p1: str, p2: str) -> _Reserving:
    first = await rig.seed("review", 1, p1, end="failed")
    return _Reserving(
        "commission_replacement_invalid",
        bad=(_earlier(p1), _res("review", 2, p1, _UNKNOWN_ATTEMPT)),
        good=(_earlier(p1), _res("review", 2, p1, first.worker_attempt_id)),
    )


async def _replace_live(rig: _Rig, p1: str, p2: str) -> _Reserving:
    first = await rig.seed("review", 1, p1)  # no outcome yet

    async def end_it() -> None:
        await rig.end(first)

    request = (_earlier(p1), _res("review", 2, p1, first.worker_attempt_id))
    return _Reserving("commission_replacement_invalid", bad=request, good=request, fix=end_it)


async def _replace_succeeded(rig: _Rig, p1: str, p2: str) -> _Reserving:
    first = await rig.seed("review", 1, p1, end="succeeded")
    second = await rig.seed("review", 2, p1, end="failed")
    return _Reserving(
        "commission_replacement_invalid",
        bad=(_earlier(p1), _res("review", 3, p1, first.worker_attempt_id)),  # a succeeded attempt is never replaced
        good=(_earlier(p1), _res("review", 3, p1, second.worker_attempt_id)),
    )


async def _replace_already_replaced(rig: _Rig, p1: str, p2: str) -> _Reserving:
    first = await rig.seed("review", 1, p1, end="failed")
    second = await rig.seed("review", 2, p1, first.worker_attempt_id, end="failed")  # already replaces the first
    return _Reserving(
        "commission_replacement_invalid",
        bad=(_earlier(p1), _res("review", 3, p1, first.worker_attempt_id)),
        good=(_earlier(p1), _res("review", 3, p1, second.worker_attempt_id)),
    )


async def _replace_twice_in_one_request(rig: _Rig, p1: str, p2: str) -> _Reserving:
    first = await rig.seed("review", 1, p1, end="failed")
    return _Reserving(
        "commission_replacement_invalid",
        bad=(
            _earlier(p1),
            _res("review", 2, p1, first.worker_attempt_id),
            _res("review", 3, p1, first.worker_attempt_id),  # the same predecessor, a second time
        ),
        good=(_earlier(p1), _res("review", 2, p1, first.worker_attempt_id), _res("review", 3, p1)),
    )


async def _self_supersede(rig: _Rig, p1: str, p2: str) -> _Reserving:
    return _Reserving(
        "commission_replacement_invalid",
        bad=(_earlier(p1), _res("review", 1, p1, rig.attempt_id("review", 1))),  # names itself as its predecessor
        good=(_earlier(p1), _res("review", 1, p1)),
    )


async def _capacity(rig: _Rig, p1: str, p2: str) -> _Reserving:
    assert rig.spec.slot("review").capacity.maximum == 3
    seeded = [await rig.seed("review", ordinal, p1) for ordinal in (1, 2, 3)]  # three live attempts: the maximum

    async def free_one() -> None:
        await rig.end(seeded[-1])

    request = (_earlier(p1), _res("review", 4, p1))
    return _Reserving("commission_capacity_exceeded", bad=request, good=request, fix=free_one)


_RESERVATIONS: dict[str, Callable[[_Rig, str, str], Awaitable[_Reserving]]] = {
    "slot_unknown": _slot_unknown,
    "conflict": _conflict,
    "budget_exhausted": _budget_exhausted,
    "ordinal_gap": _ordinal_gap,
    "ordinal_reused_new_profile": _ordinal_reused_new_profile,
    "replace_unknown": _replace_unknown,
    "replace_live": _replace_live,
    "replace_succeeded": _replace_succeeded,
    "replace_already_replaced": _replace_already_replaced,
    "replace_twice_in_one_request": _replace_twice_in_one_request,
    "self_supersede": _self_supersede,
    "capacity": _capacity,
}


@pytest.mark.parametrize("case", list(_RESERVATIONS))
async def test_reservation_refusals_write_nothing(world: _World, case: str) -> None:
    rig = await _rig(world, _team(maximum=3, attempts=4))
    p1 = await _in_state(world, "qualified", "p1")
    p2 = await _in_state(world, "qualified", "p2")
    reserving = await _RESERVATIONS[case](rig, p1, p2)

    await _refused(rig, rig.request(*reserving.bad), reserving.code)

    if reserving.fix is not None:
        await reserving.fix()
    before = await rig.snapshot()
    receipt = await rig.service.commission(rig.request(*reserving.good))  # the accepted neighbour
    # the earlier valid reservation was not recorded by the refused call; it is recorded now
    assert receipt.recorded[0].slot_id == "audit"
    assert len(receipt.recorded) + len(receipt.acknowledged) == len(reserving.good)
    assert await rig.snapshot() != before


# --------------------------------------------------------------------------------------
# 4. Capacity
# --------------------------------------------------------------------------------------


async def test_capacity_boundary(world: _World) -> None:
    rig = await _rig(world, _team(maximum=3, attempts=5))
    p1 = await _in_state(world, "qualified", "p1")
    assert rig.spec.slot("review").capacity.maximum == 3  # premise: a capacity of three, with budget to spare

    full = await rig.service.commission(rig.request(*(_res("review", ordinal, p1) for ordinal in (1, 2, 3))))
    assert len(full.recorded) == 3  # `maximum` live attempts are accepted
    assert await rig.live("review") == 3  # premise: all three are live

    await _refused(rig, rig.request(_res("review", 4, p1)), "commission_capacity_exceeded")  # one more is not

    released = await rig.service.release(rig.release_request(full.recorded[0].worker_attempt_id))
    assert released.terminal_status == "cancelled"
    assert await rig.live("review") == 2  # premise: the release freed a place

    again = await rig.service.commission(rig.request(_res("review", 4, p1)))  # the accepted neighbour
    assert [attempt.ordinal for attempt in again.recorded] == [4]
    assert await rig.live("review") == 3


# --------------------------------------------------------------------------------------
# 5. Qualification and currency codes pass through unchanged
# --------------------------------------------------------------------------------------


async def _bad_profile(world: _World, source: _FakeSource, case: str) -> str:
    """A profile ref that the ``review`` slot refuses for the reason ``case`` names; drift is set on ``source``."""
    if case == "profile_unknown":
        ref = "e" * 64
        assert await world.qualifications.get_qualification(ref) is None
        return ref
    if case == "profile_status_expired":
        return await _in_state(world, "expired", "bad")
    if case == "profile_status_unevaluated":
        return await _in_state(world, "unevaluated", "bad")
    if case == "role_mismatch":
        return await _in_state(world, "qualified", "bad", role_id="auditor")
    ref = await _in_state(world, "qualified", "bad")  # qualified, but a component it declares has changed since
    if case == "component_drift_skill":
        source.skills["code-review"] = LiveSkill(_CHANGED, True)
    else:
        source.tools["codebase_query"] = _CHANGED
    return ref


@pytest.mark.parametrize(
    "case",
    [
        "profile_unknown",
        "profile_status_expired",
        "profile_status_unevaluated",
        "role_mismatch",
        "component_drift_skill",
        "component_drift_tool_schema",
    ],
)
async def test_qualification_and_currency_codes_pass_through(world: _World, case: str) -> None:
    code = {"role_mismatch": "profile_role_mismatch"}.get(case, case)  # the other ids are the codes themselves
    rig = await _rig(world)
    bad = await _bad_profile(world, rig.source, case)

    await _refused(rig, rig.request(_res("review", 1, bad)), code)  # the S1 or S2a code, carried unchanged

    # the accepted neighbour: components current again, and a qualified profile
    current = _current_source(_variant("components"))
    rig.source.skills.update(current.skills)
    rig.source.tools.update(current.tools)
    good = await _in_state(world, "qualified", "good")
    receipt = await rig.service.commission(rig.request(_res("review", 1, good)))
    assert [attempt.execution_profile_ref for attempt in receipt.recorded] == [good]


# --------------------------------------------------------------------------------------
# 6-7. Independence
# --------------------------------------------------------------------------------------


async def test_distinct_profiles_allows_a_repeat_only_after_min_distinct(world: _World) -> None:
    rig = await _rig(world, _team(maximum=3, attempts=4, mode="distinct_profiles", distinct=2))
    slot = rig.spec.slot("review")
    policy = (slot.independence.mode, slot.independence.min_distinct, slot.capacity.maximum)
    assert policy == ("distinct_profiles", 2, 3)  # premise
    a = await _in_state(world, "qualified", "a")
    b = await _in_state(world, "qualified", "b")
    assert a != b

    first = await rig.service.commission(rig.request(_res("review", 1, a)))
    assert len(first.recorded) == 1
    # A then A: one distinct live profile, fewer than min_distinct
    await _refused(rig, rig.request(_res("review", 2, a)), "commission_independence_unmet")
    second = await rig.service.commission(rig.request(_res("review", 2, b)))  # the accepted neighbour: B
    assert len(second.recorded) == 1
    # A, B, then A: two distinct live profiles are enough, so a repeat is allowed
    third = await rig.service.commission(rig.request(_res("review", 3, a)))
    assert [attempt.execution_profile_ref for attempt in third.recorded] == [a]
    assert await rig.live("review") == 3


@pytest.mark.parametrize(
    "dimension, override",
    [
        pytest.param("provider", {"model.provider": "other-provider"}, id="provider"),
        pytest.param("name", {"model.name": "claude-other"}, id="name"),
    ],
)
async def test_distinct_models_compares_provider_and_name_not_version(
    world: _World, dimension: str, override: dict[str, str]
) -> None:
    # each case runs on a fresh rig and a fresh live baseline: one live attempt, so distinct keys (1) < min_distinct (2)
    rig = await _rig(world, _team(maximum=3, attempts=4, mode="distinct_models", distinct=2))
    assert rig.spec.slot("review").independence.mode == "distinct_models"
    base = await _in_state(world, "qualified", "v1")
    other_version = await _in_state(world, "qualified", "v2")  # the same provider and model name, another version
    neighbour = await _in_state(world, "qualified", "v1", **override)  # differs from the baseline in ONE dimension
    assert len({base, other_version, neighbour}) == 3  # three different profiles

    base_model = (await world.qualifications.get_profile(base)).model
    version_model = (await world.qualifications.get_profile(other_version)).model
    neighbour_model = (await world.qualifications.get_profile(neighbour)).model
    assert (version_model.provider, version_model.name) == (base_model.provider, base_model.name)  # premise
    assert version_model.version != base_model.version  # premise
    if dimension == "provider":
        assert neighbour_model.name == base_model.name  # premise
        assert neighbour_model.provider != base_model.provider  # premise
    else:
        assert neighbour_model.provider == base_model.provider  # premise
        assert neighbour_model.name != base_model.name  # premise

    first = await rig.service.commission(rig.request(_res("review", 1, base)))
    assert len(first.recorded) == 1
    await _refused(rig, rig.request(_res("review", 2, other_version)), "commission_independence_unmet")
    second = await rig.service.commission(rig.request(_res("review", 2, neighbour)))  # the accepted neighbour
    assert [attempt.execution_profile_ref for attempt in second.recorded] == [neighbour]


async def test_distinct_models_refuses_when_a_live_profile_is_unknown(world: _World) -> None:
    rig = await _rig(world, _team(maximum=2, attempts=3, mode="distinct_models", distinct=2))
    absent = _variant("absent")  # never registered: the profile store cannot say which model its live attempt uses
    fresh = await _in_state(world, "qualified", "fresh", **{"model.name": "claude-other"})
    assert await world.qualifications.get_profile(absent.content_ref()) is None
    await rig.seed("review", 1, absent.content_ref())

    await _refused(rig, rig.request(_res("review", 2, fresh)), "commission_live_profile_unknown")

    await world.qualifications.register_profile(absent)  # the accepted neighbour: the live profile is now known
    receipt = await rig.service.commission(rig.request(_res("review", 2, fresh)))
    assert [attempt.execution_profile_ref for attempt in receipt.recorded] == [fresh]


@pytest.mark.parametrize("mode", ["none", "distinct_attempts"])
async def test_repeats_are_never_refused_without_a_distinct_policy(world: _World, mode: str) -> None:
    rig = await _rig(world, _team(maximum=2, attempts=2, mode=mode))
    assert rig.spec.slot("review").independence.mode == mode
    profile = await _in_state(world, "qualified", "p1")

    receipt = await rig.service.commission(rig.request(_res("review", 1, profile), _res("review", 2, profile)))

    assert [attempt.execution_profile_ref for attempt in receipt.recorded] == [profile, profile]


# --------------------------------------------------------------------------------------
# 8. Replay
# --------------------------------------------------------------------------------------


async def test_identical_replay_is_acknowledged_without_readmission(world: _World) -> None:
    rig = await _rig(world, _team(maximum=2, attempts=3))
    profile = await _in_state(world, "qualified", "p1", **{"evaluation_suite.validity_seconds": 1})
    request = rig.request(_res("review", 1, profile))
    first = await rig.service.commission(request)
    stored = first.recorded[0]
    assert await world.teams.get_attempt(stored.worker_attempt_id) == stored

    world.clock.now += 2.0
    qualification = await world.qualifications.get_qualification(profile)
    assert qualification is not None
    assert qualification.status == "expired"  # premise: the profile no longer qualifies
    asked = (list(rig.source.skill_questions), list(rig.source.tool_questions))
    before = await rig.snapshot()

    replay = await rig.service.commission(request)

    assert replay.recorded == ()
    assert replay.acknowledged == (stored,)
    assert replay.request_ref == first.request_ref
    assert await rig.snapshot() == before
    assert (rig.source.skill_questions, rig.source.tool_questions) == asked  # nothing was re-admitted or re-checked
    # the control: a NEW reservation with the same, now expired, profile is refused
    await _refused(rig, rig.request(_res("review", 2, profile)), "profile_status_expired")


# --------------------------------------------------------------------------------------
# 9-11. Release
# --------------------------------------------------------------------------------------


async def test_release_then_replacement_keeps_the_released_record(world: _World) -> None:
    rig = await _rig(world)
    profile = await _in_state(world, "qualified", "p1")
    original = rig.request(_res("review", 1, profile))
    first = (await rig.service.commission(original)).recorded[0]
    replacement = rig.request(_res("review", 2, profile, first.worker_attempt_id))
    # control: while the attempt is live it cannot be replaced
    await _refused(rig, replacement, "commission_replacement_invalid")

    release = rig.release_request(first.worker_attempt_id)
    released = await rig.service.release(release)

    assert released.worker_attempt_id == first.worker_attempt_id
    assert released.terminal_status == "cancelled"
    assert released.error_code == "released_by_owner"
    assert released.recorded_at == 5000.0
    assert await world.teams.get_attempt_outcome(first.worker_attempt_id) == released

    rig.clock.now = 6000.0  # time passes; a replay is not a second release
    replay = await rig.service.release(release)
    assert replay == released
    assert replay.recorded_at == 5000.0

    receipt = await rig.service.commission(replacement)

    assert [attempt.worker_attempt_id for attempt in receipt.recorded] == [rig.attempt_id("review", 2)]
    assert receipt.recorded[0].supersedes_attempt_id == first.worker_attempt_id
    assert await world.teams.get_attempt(first.worker_attempt_id) == first
    assert await world.teams.get_attempt_outcome(first.worker_attempt_id) == released
    # the released record is still a record: the original request replays as an acknowledgement, not a new attempt
    again = await rig.service.commission(original)
    assert again.recorded == ()
    assert again.acknowledged == (first,)


async def test_released_attempts_still_consume_the_attempt_budget(world: _World) -> None:
    rig = await _rig(world)  # the review slot: capacity 1, two attempts
    profile = await _in_state(world, "qualified", "p1")
    assert rig.spec.slot("review").budget.max_attempts == 2
    first = (await rig.service.commission(rig.request(_res("review", 1, profile)))).recorded[0]
    await rig.service.release(rig.release_request(first.worker_attempt_id))
    # the accepted neighbour: ordinal 2 is the last one the budget allows
    second = (
        await rig.service.commission(rig.request(_res("review", 2, profile, first.worker_attempt_id)))
    ).recorded[0]
    await rig.service.release(rig.release_request(second.worker_attempt_id))
    assert await rig.live("review") == 0  # nothing is live, so capacity is not what refuses the next one

    await _refused(
        rig, rig.request(_res("review", 3, profile, second.worker_attempt_id)), "commission_budget_exhausted"
    )


@dataclass(frozen=True)
class _Releasing:
    code: str
    request: ReleaseRequest


async def _unknown_attempt(rig: _Rig, p1: str, live: WorkerAttempt) -> _Releasing:
    return _Releasing("release_attempt_unknown", rig.release_request(_UNKNOWN_ATTEMPT))


async def _other_session(rig: _Rig, p1: str, live: WorkerAttempt) -> _Releasing:
    assert live.session_id == _SESSION  # premise: the attempt belongs to session-1; the request names session-2
    return _Releasing("release_attempt_unknown", rig.release_request(live.worker_attempt_id, session_id="session-2"))


async def _other_spec(rig: _Rig, p1: str, live: WorkerAttempt) -> _Releasing:
    other = _team(maximum=2, attempts=3, revision=2)
    await rig.store(other)
    foreign = await rig.seed("review", 1, p1, spec=other)  # this session's attempt, under a spec it is not bound to
    assert foreign.session_id == _SESSION
    assert foreign.team_spec_ref == other.content_ref() != rig.ref
    return _Releasing("release_attempt_unknown", rig.release_request(foreign.worker_attempt_id))


async def _ended(rig: _Rig, p1: str, status: str, error_code: str | None = None) -> _Releasing:
    second = await rig.seed("review", 2, p1)
    await rig.end(second, status, error_code)
    return _Releasing("release_attempt_ended", rig.release_request(second.worker_attempt_id))


async def _not_owner(rig: _Rig, p1: str, live: WorkerAttempt) -> _Releasing:
    request = rig.release_request(live.worker_attempt_id, owner_id="intruder")
    return _Releasing("commission_owner_unauthorized", request)


_RELEASES: dict[str, Callable[[_Rig, str, WorkerAttempt], Awaitable[_Releasing]]] = {
    "unknown_attempt": _unknown_attempt,
    "other_session": _other_session,
    "other_spec": _other_spec,
    "ended_failed": lambda rig, p1, live: _ended(rig, p1, "failed"),
    "not_owner": _not_owner,
    "ended_succeeded": lambda rig, p1, live: _ended(rig, p1, "succeeded"),
    "ended_cancelled_other_code": lambda rig, p1, live: _ended(rig, p1, "cancelled", "lease_expired"),
}


@pytest.mark.parametrize("case", list(_RELEASES))
async def test_release_refusals(world: _World, case: str) -> None:
    rig = await _rig(world, _team(maximum=2, attempts=3))
    p1 = await _in_state(world, "qualified", "p1")
    live = await rig.seed("review", 1, p1)
    releasing = await _RELEASES[case](rig, p1, live)

    await _release_refused(rig, releasing.request, releasing.code)

    # the accepted neighbour: the owner releases the live attempt of the bound spec in its own session
    released = await rig.service.release(rig.release_request(live.worker_attempt_id))
    assert (released.worker_attempt_id, released.terminal_status, released.error_code) == (
        live.worker_attempt_id,
        "cancelled",
        "released_by_owner",
    )


@pytest.mark.parametrize("case", ["state_verifying", "stale_plan"])
async def test_release_ignores_the_session_state_and_the_plan(world: _World, case: str) -> None:
    rig = await _rig(world, _team(process=_PLAN_PROCESS) if case == "stale_plan" else None)
    profile = await _in_state(world, "qualified", "p1")
    attempt = await rig.seed("review", 1, profile)
    if case == "state_verifying":
        rig.sessions.session = _FakeSession("verifying", _OWNER)
        code = "commission_session_state_invalid"
    else:
        rig.sessions.recovery = _FakeRecovery(_FakePlan(_OTHER_PLAN))
        code = "commission_plan_stale"
    await _refused(rig, rig.request(_res("review", 2, profile)), code)  # premise: commissioning is refused here

    released = await rig.service.release(rig.release_request(attempt.worker_attempt_id))

    assert (released.terminal_status, released.error_code) == ("cancelled", "released_by_owner")


@pytest.mark.parametrize(
    "now",
    [
        pytest.param(1000, id="int"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(-1.0, id="negative"),
        pytest.param(float("inf"), id="infinite"),
    ],
)
async def test_release_refuses_a_bad_clock_and_writes_nothing(world: _World, now: Any) -> None:
    rig = await _rig(world)
    profile = await _in_state(world, "qualified", "p1")
    attempt = await rig.seed("review", 1, profile)
    request = rig.release_request(attempt.worker_attempt_id)
    before = await rig.snapshot()

    with pytest.raises(ValueError, match=r"^commission_clock_invalid$") as caught:
        await rig.make_service(clock=_Clock(now)).release(request)

    assert type(caught.value) is ValueError  # a bad clock is not a refusal of the request
    assert await rig.snapshot() == before
    assert await world.teams.get_attempt_outcome(attempt.worker_attempt_id) is None
    # the accepted neighbour: a finite, non-negative float (zero is the boundary) records the release
    released = await rig.make_service(clock=_Clock(0.0)).release(request)
    assert released.recorded_at == 0.0


# --------------------------------------------------------------------------------------
# 12. Binding integrity
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("operation", ["commission", "release"])
async def test_binding_integrity_error_propagates(world: _World, operation: str) -> None:
    rig = await _rig(world)
    profile = await _in_state(world, "qualified", "p1")

    async def attempt_it() -> object:
        if operation == "commission":
            return await rig.service.commission(rig.request(_res("review", 1, profile)))
        return await rig.service.release(rig.release_request(_UNKNOWN_ATTEMPT))

    before = await rig.snapshot()
    integrity = ElasticTeamIntegrityError("elastic_team_spec_integrity")
    rig.sessions.binding_error = integrity

    with pytest.raises(ElasticTeamIntegrityError) as caught:
        await attempt_it()

    assert caught.value is integrity  # unchanged: data integrity is not a refusal
    assert not isinstance(caught.value, CommissionRefused)
    assert await rig.snapshot() == before

    # control: any other ValueError from the binding read is a refusal, with the original as its cause
    plain = ValueError("crew_elastic_team_binding_invalid")
    rig.sessions.binding_error = plain
    with pytest.raises(CommissionRefused) as refused:
        await attempt_it()
    assert str(refused.value) == "commission_team_binding_invalid"
    assert refused.value.__cause__ is plain


# --------------------------------------------------------------------------------------
# 13. A failure while recording keeps what was recorded
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current_checks", "kept"),
    [pytest.param(3, 1, id="second_attempt"), pytest.param(2, 0, id="first_attempt")],
)
async def test_write_phase_failure_keeps_earlier_attempts_and_a_retry_acknowledges_them(
    world: _World, caplog: pytest.LogCaptureFixture, current_checks: int, kept: int
) -> None:
    rig = await _rig(world, _team(maximum=2, attempts=3))
    profile = await _in_state(world, "qualified", "p1")
    flip = _FakeFlipSource(dict(rig.source.skills), dict(rig.source.tools), current_checks)
    request = rig.request(_res("review", 1, profile), _res("review", 2, profile))
    ids = [rig.attempt_id("review", 1), rig.attempt_id("review", 2)]

    with caplog.at_level(logging.WARNING, logger=_LOGGER), pytest.raises(SlotAdmissionRefused) as caught:
        await rig.make_service(components=flip).commission(request)

    # prevalidation (two checks) saw current components; the gate then read a drifted tool schema
    assert type(caught.value) is SlotAdmissionRefused
    assert not isinstance(caught.value, CommissionRefused)
    assert str(caught.value) == "component_drift_tool_schema"
    assert flip.checks == 3 + kept  # two for prevalidation, one per attempt the gate admitted, and the failing one
    held = (await rig.snapshot())[(rig.ref, "review")]
    assert [attempt.worker_attempt_id for attempt, _ in held] == ids[:kept]  # earlier attempts stay recorded
    assert all(outcome is None for _, outcome in held)
    warnings = [r for r in caplog.records if r.name == _LOGGER and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert f"the {kept} attempt(s) it recorded before stay recorded" in message
    assert ids[kept] in message  # it names the attempt it stopped at
    assert request.content_ref() in message

    # the accepted neighbour: an identical retry with a current source acknowledges what stayed and records the rest
    retry = await rig.make_service(components=_current_source(_variant("components"))).commission(request)
    assert tuple(attempt for attempt, _ in held) == retry.acknowledged
    assert [attempt.worker_attempt_id for attempt in retry.recorded] == ids[kept:]


# --------------------------------------------------------------------------------------
# 14. Bad input
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("operation", ["commission", "release", "team_view"])
async def test_bad_input_reads_nothing(world: _World, operation: str) -> None:
    rig = await _rig(world, _team(maximum=2, attempts=3))  # room for the live attempt and the good commission below
    profile = await _in_state(world, "qualified", "p1")
    attempt = await rig.seed("review", 1, profile)
    good_commission = rig.request(_res("review", 2, profile))
    good_release = rig.release_request(attempt.worker_attempt_id)
    before = await rig.snapshot()

    if operation == "commission":
        with pytest.raises(TypeError, match=r"^commission_request_type_invalid$"):
            await rig.service.commission("not a request")  # type: ignore[arg-type]
        with pytest.raises(ValidationError):  # model_copy(update=...) skips validation; the service validates again
            await rig.service.commission(good_commission.model_copy(update={"owner_id": "bad id!"}))
    elif operation == "release":
        with pytest.raises(TypeError, match=r"^commission_release_type_invalid$"):
            await rig.service.release("not a request")  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            await rig.service.release(good_release.model_copy(update={"worker_attempt_id": "bad id!"}))
    else:
        with pytest.raises(ValidationError):
            await rig.service.team_view("bad id!")
        with pytest.raises(ValidationError):
            await rig.service.team_view(7)  # type: ignore[arg-type]

    assert rig.sessions.calls == []  # the sessions saw nothing
    assert await rig.snapshot() == before

    # the accepted neighbour: a good request does read the sessions (so the empty call list above means something)
    if operation == "commission":
        assert len((await rig.service.commission(good_commission)).recorded) == 1
    elif operation == "release":
        assert (await rig.service.release(good_release)).terminal_status == "cancelled"
    else:
        assert await rig.service.team_view(_SESSION) is not None
    assert rig.sessions.calls != []


# --------------------------------------------------------------------------------------
# 15. The lock
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["different_ordinals", "different_slots", "same_ordinal"])
async def test_lock_serialises_concurrent_commissions(world: _World, case: str) -> None:
    rig = await _rig(world, _team(maximum=2, attempts=2))
    p1 = await _in_state(world, "qualified", "p1")
    p2 = await _in_state(world, "qualified", "p2")
    pair = {
        # the contract's scenario: serialised, the second sees the first's attempt; unserialised it asks for ordinal 2
        # of an empty slot and is refused before it asks the source anything, so it cannot overlap
        "different_ordinals": (_res("review", 1, p1), _res("review", 2, p1)),
        # both are valid whatever the other does, so unserialised they must reach the source together
        "different_slots": (_res("audit", 1, p1), _res("review", 1, p1)),
        "same_ordinal": (_res("review", 1, p1), _res("review", 1, p2)),
    }[case]

    # premise control 1: the barrier DOES see two askers when nothing serialises them (two drift checks side by side)
    probe = _FakeBarrierSource(dict(rig.source.skills), dict(rig.source.tools))
    profile = await world.qualifications.get_profile(p1)
    assert profile is not None
    await asyncio.gather(profile_drift(profile, probe), profile_drift(profile, probe))
    assert probe.overlapped is True

    # premise control 2: two services over the same stores share no lock. The same pair, in another session (the
    # snapshot below does not read it), then overlaps at the barrier, or, for different_ordinals, loses its second
    # commission to the ordinal check. This is what the lock below prevents. Nothing here depends on how fast the
    # machine is: overlap ends the first wait at once, and for different_ordinals (whose second commission never asks
    # a question) the test releases the first wait itself once the second commission is done; the long window is only
    # a safety net.
    loose = _FakeBarrierSource(dict(rig.source.skills), dict(rig.source.tools), wait=5.0)
    tasks = [
        asyncio.create_task(rig.make_service(components=loose).commission(rig.request(r, session_id="session-2")))
        for r in pair
    ]
    if case == "different_ordinals":
        await asyncio.wait([tasks[1]])
        loose.release()
    unserialised = await asyncio.gather(*tasks, return_exceptions=True)
    if case == "different_ordinals":
        assert isinstance(unserialised[0], CommissionReceipt)
        assert type(unserialised[1]) is CommissionRefused
        assert str(unserialised[1]) == "commission_ordinal_invalid"
        assert loose.overlapped is False
    else:
        assert loose.overlapped is True

    # the real thing: one service, one lock. The first question waits out the window (the second commission is held at
    # the lock and cannot ask), so the window only has to outlast a second commission that is NOT held. The contract's
    # 0.2 s is the floor (the second commission reaches the barrier about 3 ms behind the first); 0.5 s keeps a loaded
    # machine from letting a lockless service slip through.
    barrier = _FakeBarrierSource(dict(rig.source.skills), dict(rig.source.tools), wait=0.5)
    service = rig.make_service(components=barrier)
    results = await asyncio.gather(*(service.commission(rig.request(r)) for r in pair), return_exceptions=True)

    assert barrier.overlapped is False  # one commission at a time: the second never asked a question during the first
    if case == "same_ordinal":
        # whichever ran first holds ordinal 1; the other is refused by admission, never by a late store conflict
        assert sorted(type(result).__name__ for result in results) == ["CommissionReceipt", "CommissionRefused"]
        refused = next(result for result in results if not isinstance(result, CommissionReceipt))
        assert str(refused) == "commission_reservation_conflict"
    else:
        # (the contract allows a second refusal here; gather starts the first task first, so it takes the lock first)
        assert [type(result) for result in results] == [CommissionReceipt, CommissionReceipt]
    recorded = sum(len(result.recorded) for result in results if isinstance(result, CommissionReceipt))
    assert sum(len(rows) for rows in (await rig.snapshot()).values()) == recorded


# --------------------------------------------------------------------------------------
# 16. The team view
# --------------------------------------------------------------------------------------


async def test_team_view_reports_reserved_and_terminal(world: _World) -> None:
    rig = await _rig(world, _team(maximum=3, attempts=4))
    profile = await _in_state(world, "qualified", "p1")
    before = await rig.snapshot()

    empty = await rig.service.team_view(_SESSION)
    assert empty == TeamView(
        session_id=_SESSION,
        team_spec_ref=rig.ref,
        slots=(SlotView("audit", 1, 2, (), (), 0, 1), SlotView("review", 3, 4, (), (), 0, 1)),
    )

    receipt = await rig.service.commission(
        rig.request(_earlier(profile), *(_res("review", ordinal, profile) for ordinal in (1, 2, 3)))
    )
    audit, r1, r2, r3 = receipt.recorded
    reserved = await rig.service.team_view(_SESSION)
    assert reserved == TeamView(
        session_id=_SESSION,
        team_spec_ref=rig.ref,
        slots=(
            SlotView("audit", 1, 2, (audit,), (None,), 1, 2),
            SlotView("review", 3, 4, (r1, r2, r3), (None, None, None), 3, 4),
        ),
    )

    failed = await rig.end(r1)  # the first attempt failed; the second is released; the third is still live
    released = await rig.service.release(rig.release_request(r2.worker_attempt_id))
    snapshot = await rig.snapshot()
    terminal = await rig.service.team_view(_SESSION)

    assert terminal == TeamView(
        session_id=_SESSION,
        team_spec_ref=rig.ref,
        slots=(
            SlotView("audit", 1, 2, (audit,), (None,), 1, 2),
            SlotView("review", 3, 4, (r1, r2, r3), (failed, released, None), 1, 4),  # aligned with the attempts
        ),
    )
    assert await rig.snapshot() == snapshot  # reading the view wrote nothing
    assert before != snapshot

    rig.sessions.binding = None
    assert await rig.service.team_view(_SESSION) is None  # an unbound session has no team


async def test_team_view_refuses_a_bound_spec_the_store_does_not_hold(world: _World) -> None:
    rig = await _rig(world)
    unstored = _team(revision=2)
    assert await world.teams.get_team_spec(unstored.content_ref()) is None
    assert await rig.service.team_view(_SESSION) is not None  # the control: the stored spec has a view
    rig.sessions.binding = CrewElasticTeamBinding.for_spec(unstored)

    with pytest.raises(CommissionRefused) as caught:
        await rig.service.team_view(_SESSION)

    assert str(caught.value) == "commission_team_spec_unknown"
