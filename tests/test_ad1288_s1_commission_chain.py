"""AD-1288 S1 (#1335), M3: the commission chain on a real ``CrewSessionService`` and real stores, across restarts.

M1 pins the request contracts and M2 the admission rules (real team and qualification stores, fake sessions). This
file pins what neither can: that the real pieces compose. A real CrewSession binds a team spec on its parent
work-item row; ``ElasticCommissionService`` reads that binding through a second ``CrewSessionService`` (the one that
holds the owner-eligibility resolver) and commissions against real ``ProfileQualificationStore`` and
``ElasticTeamStore`` files. Every store and service is then closed and rebuilt, and the state must come back from the
files alone.

Tests 1-3 drive the chain: a restart cycle with a replay, a release and a replacement; a plan-bound session whose plan
goes stale; and concurrent commissions. Test 4 is the "not wired" scan for the new module (nothing in ``src/probos``
imports it or constructs its service), and test 5 pins the one deliberate edit to AD-1287 S1's own scan (its test 16),
by reading that file's text: this file does not import ``tests.test_ad1287_slot_qualification``.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import sqlite3
from collections.abc import AsyncIterator, Awaitable
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.crew_session import (
    CrewRecoveryContract,
    CrewRecoveryPlan,
    CrewSessionContract,
    CrewSessionService,
)
from probos.cognitive.elastic_commission import (
    CommissionReceipt,
    CommissionRefused,
    CommissionRequest,
    ElasticCommissionService,
    ReleaseRequest,
    SlotReservation,
    SlotView,
)
from probos.cognitive.elastic_team import (
    CREW_ELASTIC_TEAM_METADATA_KEY,
    CrewElasticTeamBinding,
    ElasticTeamSpec,
    WorkerAttempt,
    WorkerAttemptOutcome,
    derive_worker_attempt_id,
)
from probos.cognitive.elastic_team_store import ElasticTeamStore, ElasticTeamStoreUnavailable
from probos.cognitive.execution_profile import ExecutionProfile
from probos.cognitive.profile_currency import ProfileComponentSource
from probos.cognitive.profile_qualification_store import ProfileQualificationStore
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.threads import ChatThreadStore
from probos.workforce import WorkItem, WorkItemStore
from tests.test_ad1127_crew_session_lifecycle_recovery import (
    _VECTOR_PLAN_HASH,
    _new_session,
    _vector_insert,
    _vector_plan_payload,
)
from tests.test_ad1286_crew_session_team_binding import _plan_bound_spec
from tests.test_ad1286_elastic_team_contract import _review_slot, _slot, _spec
from tests.test_ad1287_execution_profile import _profile
from tests.test_ad1287_profile_qualification_store import _Clock, _evaluation, _started
from tests.test_ad1287_s2a_profile_currency import _current_source

_FACILITATOR = "facilitator-1"  # the facilitator ``_new_session`` gives its session
_OTHER_OWNER = "agent-1"  # an owner of that session who is not its facilitator
_SLOTS = ("analyse", "review")  # the KAT team's slots, in the spec's (slot id) order
_RATIONALE = "AD-1288 S1 chain test: the owner names the exact attempts"
_STALE_PLAN_HASH = "e" * 64
_SRC_PROBOS = Path(__file__).resolve().parent.parent / "src" / "probos"
_COMMISSION_MODULE = "elastic_commission"
_COMMISSION_CLASS = "ElasticCommissionService"
_COMMISSION_PATH = _SRC_PROBOS / "cognitive" / f"{_COMMISSION_MODULE}.py"
_AD1287_SCAN_TEST = Path(__file__).resolve().parent / "test_ad1287_slot_qualification.py"


# --------------------------------------------------------------------------------------
# Test doubles and helpers
# --------------------------------------------------------------------------------------


class _FakeEligibility:
    """What ``check_eligibility`` answers: an ``identity`` when the agent may act, else None."""

    def __init__(self, identity: object | None) -> None:
        self.identity = identity


class _FakeResolver:
    """The ``worker_resolver`` of the admission ``CrewSessionService``: eligible for ``facilitator-1`` only.

    ``resolve`` raises: commission admission asks who is eligible and never asks the resolver to assign work.
    """

    def check_eligibility(self, agent_id: str) -> _FakeEligibility:
        return _FakeEligibility(object() if agent_id == _FACILITATOR else None)

    def resolve(self, spec: object) -> object:
        raise AssertionError("commission admission must never ask the resolver to assign work")


class _StalePlanSessions:
    """The real ``CrewSessionService`` reads, except that the session's current plan reports another ``plan_hash``."""

    def __init__(self, real: CrewSessionService, plan_hash: str) -> None:
        self._real = real
        self._plan_hash = plan_hash

    async def get_session(self, parent_id: str) -> CrewSessionContract | None:
        return await self._real.get_session(parent_id)

    async def get_recovery(self, parent_id: str) -> CrewRecoveryContract | None:
        recovery = await self._real.get_recovery(parent_id)
        assert recovery is not None and recovery.plan is not None  # premise: there is a plan to report a hash of
        return recovery.model_copy(update={"plan": recovery.plan.model_copy(update={"plan_hash": self._plan_hash})})

    async def get_team_binding(self, parent_id: str) -> CrewElasticTeamBinding | None:
        return await self._real.get_team_binding(parent_id)

    @property
    def worker_eligibility(self) -> Any:
        return self._real.worker_eligibility


class _InFlight:
    """Counts the calls awaiting at once; ``peak`` is the most there ever were."""

    def __init__(self) -> None:
        self.now = 0
        self.peak = 0

    async def run(self, call: Awaitable[Any]) -> Any:
        self.now += 1
        self.peak = max(self.peak, self.now)
        try:
            return await call
        finally:
            self.now -= 1


def _review_profile(version: str) -> ExecutionProfile:
    """A profile for the KAT ``review`` slot (reviewer / finding_review), made distinct by its model version label.

    Built from ``_profile`` the way ``test_ad1287_slot_qualification._variant`` builds it, without importing that
    module (test 5 reads its text).
    """
    return ExecutionProfile.model_validate(_profile(**{"model.version": version}))


def _team_spec(*, maximum: int, attempts: int) -> ElasticTeamSpec:
    """The KAT team (bill-bound) whose ``review`` slot holds ``maximum`` live attempts and ``attempts`` in all."""
    review = _review_slot(
        capacity={"minimum": 1, "maximum": maximum},
        budget={"max_tokens": 100_000, "max_wall_ms": 600_000, "max_attempts": attempts},
    )
    return _spec(slots=[_slot(), review])


class _Chain:
    """Every store and service the chain touches, on four files in ``directory``.

    ``start`` always builds NEW instances of all of them, so ``stop()`` then ``start()`` is a restart in which nothing
    but the files carries over. The two clocks are the wall clock a real restart keeps: the qualification store's
    (which decides expiry) and the release stamp's (which counts its reads).
    """

    work: WorkItemStore
    teams: ElasticTeamStore
    qualifications: ProfileQualificationStore
    sessions: CrewSessionService
    service: ElasticCommissionService

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.qualification_clock = _Clock(1000.0)
        self.release_clock = _Clock(5000.0)
        # every review-slot profile declares the same skills and tools, so one source is current for all of them
        self.components: ProfileComponentSource = _current_source(_review_profile("components"))

    async def start(self) -> None:
        self.work = WorkItemStore(
            db_path=str(self.directory / "workforce.db"),
            tick_interval=1_000,
            connection_factory=SQLiteConnectionFactory(),
        )
        await self.work.start()
        self.teams = ElasticTeamStore(str(self.directory / "elastic_teams.db"))
        await self.teams.start()
        self.qualifications = await _started(
            self.directory / "profile_qualifications.db", clock=self.qualification_clock,
        )
        self.sessions = CrewSessionService(
            work_item_store=self.work,
            chat_thread_store=ChatThreadStore(self.directory / "threads.db"),
            worker_resolver=_FakeResolver(),
        )
        self.sessions.bind_team_spec_lookup(self.teams)
        self.service = ElasticCommissionService(
            sessions=self.sessions,
            teams=self.teams,
            profiles=self.qualifications,
            components=self.components,
            clock=self.release_clock,
        )

    async def stop(self) -> None:
        await self.qualifications.stop()
        await self.teams.stop()
        await self.work.stop()

    async def restart(self) -> None:
        """Close every store and build new instances of every store and service, asserting that is what happened."""
        before = (self.work, self.teams, self.qualifications, self.sessions, self.service)
        await self.stop()
        await self.start()
        after = (self.work, self.teams, self.qualifications, self.sessions, self.service)
        assert all(new is not old for new, old in zip(after, before, strict=True))  # nothing carries over in memory
        with pytest.raises(ElasticTeamStoreUnavailable):
            await before[1].get_team_spec("0" * 64)  # the old team store is closed: only the file holds the attempts


@pytest.fixture
async def chain(tmp_path: Path) -> AsyncIterator[_Chain]:
    opened = _Chain(tmp_path)
    await opened.start()
    try:
        yield opened
    finally:
        await opened.stop()  # whichever instances are current: a test that restarted replaced the first set


async def _qualified(chain: _Chain, version: str) -> str:
    """Register a review-slot profile, evaluate it as passing and return its reference once it reads ``qualified``."""
    ref = await chain.qualifications.register_profile(_review_profile(version))
    await chain.qualifications.record_evaluation(_evaluation(ref))
    qualification = await chain.qualifications.get_qualification(ref)
    assert qualification is not None
    assert qualification.status == "qualified"  # premise: no refusal below can be for want of this
    return ref


async def _bound_session(chain: _Chain, spec: ElasticTeamSpec, *, install_plan: bool) -> tuple[WorkItem, str]:
    """A real discussing CrewSession (the vector plan installed when asked) with ``spec`` really bound to it.

    The plan is installed the way ``test_ad1286_crew_session_team_binding`` installs it, from the named AD-1127
    harness helpers; a bill-bound spec binds beside it as well as a plan-bound one.
    """
    parent, binder, session = await _new_session(chain.work, chain.directory)
    if install_plan:
        await binder.install_recovery_plan(
            parent.id,
            expected_session=session,
            expected_recovery=None,
            plan=CrewRecoveryPlan.model_validate(_vector_plan_payload()),
            children=(_vector_insert(),),
        )
    spec_ref = await chain.teams.put_team_spec(spec)
    binder.bind_team_spec_lookup(chain.teams)
    bound = await binder.bind_team_spec(parent.id, spec_ref, expected_session=await binder.get_session(parent.id))
    assert bound == CrewElasticTeamBinding.for_spec(spec)  # premise: the session names exactly this spec
    return parent, spec_ref


def _reservation(slot_id: str, ordinal: int, profile_ref: str, supersedes: str | None = None) -> SlotReservation:
    return SlotReservation(
        slot_id=slot_id, ordinal=ordinal, execution_profile_ref=profile_ref, supersedes_attempt_id=supersedes,
    )


def _commission(
    session_id: str, team_spec_ref: str, *reservations: SlotReservation, owner_id: str = _FACILITATOR,
) -> CommissionRequest:
    return CommissionRequest(
        schema_version=1,
        session_id=session_id,
        team_spec_ref=team_spec_ref,
        owner_id=owner_id,
        reservations=list(reservations),
        rationale=_RATIONALE,
        evidence_refs=[],
    )


def _release(session_id: str, attempt_id: str) -> ReleaseRequest:
    return ReleaseRequest(schema_version=1, session_id=session_id, owner_id=_FACILITATOR, worker_attempt_id=attempt_id)


async def _history(
    chain: _Chain, session_id: str, spec_ref: str,
) -> dict[str, list[tuple[WorkerAttempt, WorkerAttemptOutcome | None]]]:
    """Every slot's attempts, each with its outcome: what "wrote nothing" compares before and after."""
    history: dict[str, list[tuple[WorkerAttempt, WorkerAttemptOutcome | None]]] = {}
    for slot_id in _SLOTS:
        attempts = await chain.teams.list_slot_attempts(session_id=session_id, team_spec_ref=spec_ref, slot_id=slot_id)
        history[slot_id] = [(a, await chain.teams.get_attempt_outcome(a.worker_attempt_id)) for a in attempts]
    return history


def _nothing() -> dict[str, list[tuple[WorkerAttempt, WorkerAttemptOutcome | None]]]:
    return {slot_id: [] for slot_id in _SLOTS}


def _row_counts(path: Path) -> dict[str, int]:
    """Row counts of every table in the SQLite file at ``path``, read straight from the file (tests only)."""
    with contextlib.closing(sqlite3.connect(path)) as raw:
        tables = [name for (name,) in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {table: raw.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


async def _work_rows(work: WorkItemStore, ids: tuple[str, ...]) -> dict[str, str]:
    """Each named work-item row, whole, as canonical JSON."""
    rows: dict[str, str] = {}
    for work_item_id in ids:
        row = await work.get_work_item(work_item_id)
        assert row is not None
        rows[work_item_id] = _canonical(row.to_dict())
    return rows


def _data_files(directory: Path) -> list[str]:
    """The files under ``directory``, bar SQLite's per-connection sidecars that come and go with each connection."""
    return sorted(
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and not path.name.endswith(("-wal", "-shm", "-journal"))
    )


async def _slot_view(chain: _Chain, session_id: str, slot_id: str) -> SlotView:
    view = await chain.service.team_view(session_id)
    assert view is not None
    return {slot.slot_id: slot for slot in view.slots}[slot_id]


def _identity(attempt: WorkerAttempt) -> tuple[str, int, str, str | None]:
    return (attempt.slot_id, attempt.ordinal, attempt.execution_profile_ref, attempt.supersedes_attempt_id)


# --------------------------------------------------------------------------------------
# 1. The whole chain, across three restarts
# --------------------------------------------------------------------------------------


async def test_commission_release_replace_across_restarts(chain: _Chain) -> None:
    """Commission, restart, replay, release, restart, replace, restart, view: the files alone carry the state.

    A real session binds a bill-bound spec (the vector plan is installed too, so a child work-item row exists); a
    second ``CrewSessionService`` over the same stores reads it for admission. Each restart builds new instances of
    every store and service. The parent and child work-item rows, the qualification evidence and the set of data
    files are the same at the end as before the first commission: admission wrote only attempts and one outcome,
    and only to the elastic team store.
    """
    parent, spec_ref = await _bound_session(chain, _team_spec(maximum=2, attempts=3), install_plan=True)
    child_id = _vector_insert().id
    p1, p2, p3 = [await _qualified(chain, version) for version in ("v1", "v2", "v3")]
    assert len({p1, p2, p3}) == 3  # premise: three distinct qualified profiles
    eligibility = chain.sessions.worker_eligibility
    assert eligibility is not None  # premise: the admission session service holds the resolver ...
    assert eligibility.check_eligibility(_FACILITATOR).identity is not None  # ... which knows only the facilitator
    assert eligibility.check_eligibility(_OTHER_OWNER).identity is None
    team_db = chain.directory / "elastic_teams.db"

    rows_before = await _work_rows(chain.work, (parent.id, child_id))
    assert CREW_ELASTIC_TEAM_METADATA_KEY in json.loads(rows_before[parent.id])["metadata"]  # premise: it is bound
    assert _canonical(parent.to_dict()) != rows_before[parent.id]  # control: the snapshot sees the rows' real writes
    files_before = _data_files(chain.directory)
    qualifications_before = {ref: await chain.qualifications.get_qualification(ref) for ref in (p1, p2, p3)}
    assert await _history(chain, parent.id, spec_ref) == _nothing()  # premise: nothing is recorded yet

    # commission two attempts; control: an owner who is not the session's facilitator is refused and writes nothing
    first = _commission(parent.id, spec_ref, _reservation("review", 1, p1), _reservation("review", 2, p2))
    with pytest.raises(CommissionRefused, match="^commission_owner_unauthorized$"):
        await chain.service.commission(
            _commission(parent.id, spec_ref, _reservation("review", 1, p1), owner_id=_OTHER_OWNER),
        )
    assert await _history(chain, parent.id, spec_ref) == _nothing()
    receipt = await chain.service.commission(first)
    a1, a2 = receipt.recorded
    assert [_identity(a1), _identity(a2)] == [("review", 1, p1, None), ("review", 2, p2, None)]
    assert [a.worker_attempt_id for a in receipt.recorded] == [
        derive_worker_attempt_id(team_spec_ref=spec_ref, session_id=parent.id, slot_id="review", ordinal=n)
        for n in (1, 2)
    ]
    assert receipt.acknowledged == ()
    assert receipt.request_ref == first.content_ref()
    stored = await _history(chain, parent.id, spec_ref)
    assert stored == {"analyse": [], "review": [(a1, None), (a2, None)]}
    counts = _row_counts(team_db)
    assert counts["elastic_worker_attempts"] == 2 and counts["elastic_attempt_outcomes"] == 0

    # restart 1: the identical request is acknowledged from the files alone, with no new row, and the view shows both
    # reserved; control: a request that reuses an ordinal for another profile is no replay, and is refused
    await chain.restart()
    replay = await chain.service.commission(first)
    assert replay.recorded == ()
    assert replay.acknowledged == (a1, a2)
    assert replay.request_ref == receipt.request_ref
    assert _row_counts(team_db) == counts
    assert await _history(chain, parent.id, spec_ref) == stored
    with pytest.raises(CommissionRefused, match="^commission_reservation_conflict$"):
        await chain.service.commission(
            _commission(parent.id, spec_ref, _reservation("review", 1, p1), _reservation("review", 2, p3)),
        )
    assert _row_counts(team_db) == counts
    assert await _history(chain, parent.id, spec_ref) == stored
    view = await chain.service.team_view(parent.id)
    assert view is not None and (view.session_id, view.team_spec_ref) == (parent.id, spec_ref)
    assert [slot.slot_id for slot in view.slots] == list(_SLOTS)
    analyse, review = view.slots
    assert (analyse.attempts, analyse.live, analyse.next_ordinal) == ((), 0, 1)
    assert (analyse.capacity_maximum, analyse.max_attempts) == (3, 6)
    assert (review.capacity_maximum, review.max_attempts) == (2, 3)
    assert review.attempts == (a1, a2) and review.outcomes == (None, None)  # both reserved: no outcome yet
    assert (review.live, review.next_ordinal) == (2, 3)

    # the replacement the owner will want once a2 is released; control: while a2 has no outcome, nothing may replace it
    replacement = _commission(parent.id, spec_ref, _reservation("review", 3, p3, a2.worker_attempt_id))
    with pytest.raises(CommissionRefused, match="^commission_replacement_invalid$"):
        await chain.service.commission(replacement)
    assert _row_counts(team_db) == counts
    assert await _history(chain, parent.id, spec_ref) == stored

    # release a2; its record stays, and it carries the first release's stamp
    assert chain.release_clock.reads == 0  # premise: nothing has been stamped yet
    released = await chain.service.release(_release(parent.id, a2.worker_attempt_id))
    assert (released.worker_attempt_id, released.terminal_status, released.error_code, released.recorded_at) == (
        a2.worker_attempt_id, "cancelled", "released_by_owner", 5000.0,
    )
    assert chain.release_clock.reads == 1

    # restart 2: the very request that was refused is now admissible, and records a NEW attempt superseding a2
    await chain.restart()
    replaced = await chain.service.commission(replacement)
    (a3,) = replaced.recorded
    assert replaced.acknowledged == ()
    assert _identity(a3) == ("review", 3, p3, a2.worker_attempt_id)
    assert a3.worker_attempt_id not in {a1.worker_attempt_id, a2.worker_attempt_id}  # a new id: a2's record is kept

    # restart 3: the view reads released and live attempts apart from the files alone
    await chain.restart()
    view = await chain.service.team_view(parent.id)
    assert view is not None
    analyse, review = view.slots
    assert (analyse.attempts, analyse.live, analyse.next_ordinal) == ((), 0, 1)
    assert review.attempts == (a1, a2, a3)
    assert review.outcomes == (None, released, None)
    assert review.outcomes[1] is not None and (review.outcomes[1].terminal_status, review.outcomes[1].error_code) == (
        "cancelled", "released_by_owner",
    )
    assert (review.live, review.next_ordinal) == (2, 4)  # a1 and a3 are live; a2 is released, not deleted
    assert await _history(chain, parent.id, spec_ref) == {
        "analyse": [], "review": [(a1, None), (a2, released), (a3, None)],
    }

    # a replayed release returns the first stamp, and does not read the clock again
    chain.release_clock.now = 6000.0
    assert await chain.service.release(_release(parent.id, a2.worker_attempt_id)) == released
    assert chain.release_clock.reads == 1

    # the chain wrote only attempts and one outcome, and only to the elastic team store
    assert await _work_rows(chain.work, (parent.id, child_id)) == rows_before
    assert _data_files(chain.directory) == files_before
    assert {ref: await chain.qualifications.get_qualification(ref) for ref in (p1, p2, p3)} == qualifications_before
    final = _row_counts(team_db)
    assert (final["elastic_worker_attempts"], final["elastic_attempt_outcomes"]) == (3, 1)
    assert final["elastic_team_specs"] == counts["elastic_team_specs"]


# --------------------------------------------------------------------------------------
# 2. A plan-bound spec admits on the installed plan, and only on it
# --------------------------------------------------------------------------------------


async def test_plan_bound_spec_admits_on_the_installed_plan(chain: _Chain) -> None:
    """A spec that names the installed plan admits; reads that report another plan hash refuse the same request."""
    parent, spec_ref = await _bound_session(chain, _plan_bound_spec(), install_plan=True)
    profile_ref = await _qualified(chain, "v1")
    request = _commission(parent.id, spec_ref, _reservation("review", 1, profile_ref))
    spec = await chain.teams.get_team_spec(spec_ref)
    assert spec is not None and spec.process.plan_hash == _VECTOR_PLAN_HASH  # premise: the spec names the plan
    recovery = await chain.sessions.get_recovery(parent.id)
    assert recovery is not None and recovery.plan is not None
    assert recovery.plan.plan_hash == _VECTOR_PLAN_HASH  # premise: ... and the session's current plan is that plan
    assert await _history(chain, parent.id, spec_ref) == _nothing()

    # control: the same request through reads that report another plan hash is refused, and writes nothing
    stale_reads = _StalePlanSessions(chain.sessions, _STALE_PLAN_HASH)
    stale_recovery = await stale_reads.get_recovery(parent.id)
    assert stale_recovery is not None and stale_recovery.plan is not None
    assert stale_recovery.plan.plan_hash == _STALE_PLAN_HASH != _VECTOR_PLAN_HASH
    assert stale_recovery.plan.model_copy(update={"plan_hash": _VECTOR_PLAN_HASH}) == recovery.plan  # only the hash
    assert await stale_reads.get_session(parent.id) == await chain.sessions.get_session(parent.id)
    assert await stale_reads.get_team_binding(parent.id) == await chain.sessions.get_team_binding(parent.id)
    stale = ElasticCommissionService(
        sessions=stale_reads,
        teams=chain.teams,
        profiles=chain.qualifications,
        components=chain.components,
        clock=chain.release_clock,
    )
    with pytest.raises(CommissionRefused, match="^commission_plan_stale$"):
        await stale.commission(request)
    assert await _history(chain, parent.id, spec_ref) == _nothing()

    # the installed plan admits it
    receipt = await chain.service.commission(request)
    (attempt,) = receipt.recorded
    assert _identity(attempt) == ("review", 1, profile_ref, None)
    assert receipt.acknowledged == ()
    assert await chain.teams.get_attempt(attempt.worker_attempt_id) == attempt
    assert await _history(chain, parent.id, spec_ref) == {"analyse": [], "review": [(attempt, None)]}


# --------------------------------------------------------------------------------------
# 3. Concurrent commissions on real stores
# --------------------------------------------------------------------------------------


async def test_concurrent_commissions_never_exceed_capacity_on_real_stores(chain: _Chain) -> None:
    """Five gathered commissions on a capacity-3 slot: three live attempts, two refusals, nothing else escapes."""
    parent, spec_ref = await _bound_session(chain, _team_spec(maximum=3, attempts=5), install_plan=False)
    profiles = [await _qualified(chain, f"v{n}") for n in range(1, 6)]
    assert len(set(profiles)) == 5  # premise: five distinct qualified profiles
    before = await _slot_view(chain, parent.id, "review")
    assert (before.capacity_maximum, before.max_attempts, before.live) == (3, 5, 0)  # premise: capacity is the limit
    requests = [_commission(parent.id, spec_ref, _reservation("review", n, profiles[n - 1])) for n in range(1, 6)]
    flight = _InFlight()

    results = await asyncio.gather(*(flight.run(chain.service.commission(r)) for r in requests), return_exceptions=True)

    assert flight.peak == 5  # premise: all five commissions were in flight at once
    # never anything but a receipt or a refusal: in particular no ``ElasticTeamConflict`` from a racing write
    assert all(isinstance(r, (CommissionReceipt, CommissionRefused)) for r in results), results
    assert [type(r) for r in results] == [CommissionReceipt] * 3 + [CommissionRefused] * 2
    # the fourth is refused for capacity; the fifth names ordinal 5 while the next free ordinal is still 4 (the fourth
    # recorded nothing), and the ordinal rule is checked before the capacity rule
    assert [str(r) for r in results if isinstance(r, CommissionRefused)] == [
        "commission_capacity_exceeded", "commission_ordinal_invalid",
    ]
    review = await _slot_view(chain, parent.id, "review")
    assert review.live <= review.capacity_maximum == 3  # never more than the slot's maximum ...
    assert review.live == 3  # ... and the maximum was reached
    recorded = tuple(a for r in results if isinstance(r, CommissionReceipt) for a in r.recorded)
    assert review.attempts == recorded  # exactly what the receipts say, in ordinal order
    assert [a.ordinal for a in recorded] == [1, 2, 3]
    assert [a.execution_profile_ref for a in recorded] == profiles[:3]

    # control: the refused request is admissible as soon as a live attempt is released, so capacity was the cause ...
    await chain.service.release(_release(parent.id, recorded[0].worker_attempt_id))
    retried = await chain.service.commission(requests[3])
    assert [_identity(a) for a in retried.recorded] == [("review", 4, profiles[3], None)]
    review = await _slot_view(chain, parent.id, "review")
    assert (review.live, len(review.attempts)) == (3, 4)
    # ... and the slot is full again: the fifth request now has its ordinal, and is refused for capacity
    with pytest.raises(CommissionRefused, match="^commission_capacity_exceeded$"):
        await chain.service.commission(requests[4])
    review = await _slot_view(chain, parent.id, "review")
    assert (review.live, len(review.attempts)) == (3, 4)


# --------------------------------------------------------------------------------------
# 4. Not wired
# --------------------------------------------------------------------------------------


def _references(tree: ast.AST, *, module: str = _COMMISSION_MODULE, callee: str = _COMMISSION_CLASS) -> list[str]:
    """Direct syntactic references in ``tree``: an import of ``module``, or a call whose callee is ``callee``.

    A callee is a name or an attribute (``registry.ElasticCommissionService(...)``). Not found here: a call through a
    plain alias, and a lookup by string (``getattr``, ``sys.modules``); this scan does not assert them either way.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name == callee:
                found.append(f"call of {name} at line {node.lineno}")
        elif isinstance(node, ast.ImportFrom):
            imported = [(node.module or "").split(".")[-1], *(alias.name for alias in node.names)]
            if module in imported:
                found.append(f"import-from at line {node.lineno}")
        elif isinstance(node, ast.Import):
            if any(alias.name.split(".")[-1] == module for alias in node.names):
                found.append(f"import at line {node.lineno}")
    return found


def _scan(
    root: Path, owner: Path | None, *, module: str = _COMMISSION_MODULE, callee: str = _COMMISSION_CLASS,
) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Every ``*.py`` under ``root`` bar ``owner``: ``(considered, parsed, offenders)`` as relative posix paths.

    A file is parsed only when its bytes name the module or the callee (any other file cannot import the one or call
    the other by name); ``offenders`` maps each parsed file to the references found in it.
    """
    needles = (module.encode(), callee.encode())
    considered: list[str] = []
    parsed: list[str] = []
    offenders: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        if path == owner:
            continue
        relative = path.relative_to(root).as_posix()
        considered.append(relative)
        raw = path.read_bytes()
        if not any(needle in raw for needle in needles):
            continue
        parsed.append(relative)
        references = _references(ast.parse(raw, filename=str(path)), module=module, callee=callee)
        if references:
            offenders[relative] = references
    return considered, parsed, offenders


_FORBIDDEN_SHAPES = (
    "ElasticCommissionService(sessions=s, teams=t, profiles=p, components=c)",
    "registry.ElasticCommissionService(sessions=s, teams=t, profiles=p, components=c)",
    "m = importlib.import_module('probos.cognitive.elastic_commission')\nm.ElasticCommissionService(sessions=s)",
    "async def f():\n    return ElasticCommissionService(sessions=s)",
    "from probos.cognitive.elastic_commission import ElasticCommissionService",
    "from probos.cognitive.elastic_commission import CommissionRequest",
    "from probos.cognitive import elastic_commission",
    "import probos.cognitive.elastic_commission",
    "import probos.cognitive.elastic_commission as commission",
    "from .elastic_commission import ElasticCommissionService",
    "from . import elastic_commission",
    "def late():\n    from probos.cognitive.elastic_commission import ElasticCommissionService\n",
)
_ALLOWED_SHAPES = (
    "owner_symbol = 'ElasticCommissionService'",
    "owner_module = 'probos.cognitive.elastic_commission'",
    "note = 'ElasticCommissionService is the class in probos.cognitive.elastic_commission'",
    '"""A docstring that names ElasticCommissionService and calls ElasticCommissionService(...)."""',
    "from probos.cognitive.elastic_commission_notes import ElasticCommissionService_",
    "service = ElasticCommissionServiceFactory(sessions=s)",
    "from probos.cognitive.elastic_team import WorkerAttempt",
)


def test_nothing_in_src_constructs_the_service(tmp_path: Path) -> None:
    """No file under ``src/probos`` bar the module itself imports ``elastic_commission`` or calls its service.

    The scan is AST-based, so a string or docstring that merely names the module or the class is not a reference, and
    it is not vacuous: each shape it exists to forbid is flagged, in a snippet, in the real tree (with other names)
    and in a scratch tree.
    """
    # premise: the module the scan spares is where it expects it, and it defines the class the scan is about
    assert _COMMISSION_PATH.is_file()
    owner_tree = ast.parse(_COMMISSION_PATH.read_bytes())
    assert any(isinstance(n, ast.ClassDef) and n.name == _COMMISSION_CLASS for n in ast.walk(owner_tree))

    # the walker flags each shape it forbids, and not a string, a docstring or a near-miss name
    for snippet in _FORBIDDEN_SHAPES:
        assert _references(ast.parse(snippet)), snippet
    for snippet in _ALLOWED_SHAPES:
        assert _references(ast.parse(snippet)) == [], snippet
    # ... nor only on snippets: told the names of a module the real file DOES use, it flags the real file
    assert _references(owner_tree, module="elastic_team", callee="WorkerAttempt")
    assert _references(owner_tree) == []  # ... and the real module neither imports itself nor builds its own service

    # the tree scan reports a violating file in a scratch tree, and spares the owner, a file that only names the
    # module and class in strings, and a file that names nothing
    package = tmp_path / "scratch" / "cognitive"
    package.mkdir(parents=True)
    (package / "offender.py").write_text(
        "from probos.cognitive.elastic_commission import ElasticCommissionService\n"
        "service = ElasticCommissionService(sessions=None, teams=None, profiles=None, components=None)\n",
        encoding="utf-8",
    )
    (package / "declares.py").write_text(
        '"""Names ElasticCommissionService and probos.cognitive.elastic_commission in text only."""\n'
        "OWNER = 'probos.cognitive.elastic_commission'\n"
        "CLASS = 'ElasticCommissionService'\n",
        encoding="utf-8",
    )
    (package / "unrelated.py").write_text("VALUE = 1\n", encoding="utf-8")
    scratch_owner = package / f"{_COMMISSION_MODULE}.py"
    scratch_owner.write_text(
        "from probos.cognitive import elastic_commission\nservice = elastic_commission.ElasticCommissionService()\n",
        encoding="utf-8",
    )
    considered, parsed, offenders = _scan(tmp_path / "scratch", scratch_owner)
    assert considered == ["cognitive/declares.py", "cognitive/offender.py", "cognitive/unrelated.py"]
    assert parsed == ["cognitive/declares.py", "cognitive/offender.py"]  # the strings-only file is parsed, not flagged
    assert list(offenders) == ["cognitive/offender.py"]
    # control: the exclusion is the only thing that spares the owner
    _, _, unspared = _scan(tmp_path / "scratch", None)
    assert sorted(unspared) == ["cognitive/elastic_commission.py", "cognitive/offender.py"]

    # the real tree: the scan reached it, and it holds no reference ...
    considered, _, offenders = _scan(_SRC_PROBOS, _COMMISSION_PATH)
    assert {"cognitive/crew_session.py", "cognitive/elastic_team.py"} <= set(considered)  # premise: it walked the tree
    assert f"cognitive/{_COMMISSION_MODULE}.py" not in considered  # premise: the owner was spared
    assert offenders == {}
    # ... and the same scan, told other names, finds the real importers there (a path or layout slip cannot hide)
    _, _, importers = _scan(_SRC_PROBOS, None, module="elastic_team", callee="WorkerAttempt")
    assert {
        "cognitive/crew_session.py",
        "cognitive/elastic_team_store.py",
        "cognitive/profile_currency.py",
        "cognitive/profile_qualification_store.py",
    } <= set(importers)


# --------------------------------------------------------------------------------------
# 5. AD-1287 S1's scan spares only the commission module
# --------------------------------------------------------------------------------------

_AD1287_MODULES = (
    "execution_profile",
    "profile_qualification_store",
    "profile_components",
    "profile_currency",
    "profile_drift_recorder",
)
_SCAN_SPARES = (
    '_ADMISSION_CONSUMERS = ("elastic_commission",)',
    "_scan_tree(_SRC_PROBOS, owned + consumers)",
)


def _s1_modules(text: str) -> tuple[str, ...]:
    """The tuple ``_S1_MODULES`` is assigned in ``text``, parsed and never imported."""
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and "_S1_MODULES" in [getattr(t, "id", "") for t in node.targets]:
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("no _S1_MODULES assignment in the text")


def _spares_only_the_commission_module(text: str) -> bool:
    """True when AD-1287 S1's scan text spares exactly ``elastic_commission`` beyond its five owned modules."""
    return all(line in text for line in _SCAN_SPARES) and _s1_modules(text) == _AD1287_MODULES


def test_s1_scan_spares_only_the_commission_module() -> None:
    """Pins the deliberate AD-1288 edit to AD-1287 S1's test 16, which this file reads and does not import."""
    # premise: the file and the five modules it owns are where this test expects them
    assert _AD1287_SCAN_TEST.is_file()
    assert all((_SRC_PROBOS / "cognitive" / f"{name}.py").is_file() for name in _AD1287_MODULES)
    text = _AD1287_SCAN_TEST.read_text(encoding="utf-8")

    assert all(line in text for line in _SCAN_SPARES)  # the commission module is spared as a consumer ...
    assert _s1_modules(text) == _AD1287_MODULES  # ... not added to the gate modules, which the S2b test imports
    assert "profile_drift_recorder" in _s1_modules(text)  # the premise S2b asserts on import
    assert _spares_only_the_commission_module(text)

    # control: each edit that undoes the change, or widens it, makes the same check fail
    for anchor, edit in (
        (_SCAN_SPARES[0], "_ADMISSION_CONSUMERS = ()"),
        (_SCAN_SPARES[1], "_scan_tree(_SRC_PROBOS, owned)"),
        ('"profile_drift_recorder",', '"profile_drift_recorder", "elastic_commission",'),
        ('"profile_drift_recorder",', ""),
    ):
        assert text.count(anchor) == 1, anchor  # premise: the anchor is present once, so the edit changes the text
        assert not _spares_only_the_commission_module(text.replace(anchor, edit)), (anchor, edit)
