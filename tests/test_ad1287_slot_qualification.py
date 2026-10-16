"""AD-1287 S1 (M3): the candidate query, the slot boundary and the two-store seam.

Contract: ``prompts/ad-1287-s1-execution-profile-qualification.md``, Section 6 (16 tests) and D5. The real stores are
``ProfileQualificationStore`` and ``ElasticTeamStore`` on two ``tmp_path`` files, started, and restarted where a test
says so. ``_FakeReader`` and ``_FakeTeams`` are hand-written doubles for the two narrow ports the gate depends on;
nothing here uses a mock library. ``_Clock``, ``_evaluation`` and ``_started`` come from the M2 test module, ``_spec``,
``_slot``, ``_review_slot`` and ``_attempt`` from AD-1286's contract tests, and ``_profile`` from the M1 test module.
"""

from __future__ import annotations

import ast
import dataclasses
import logging
import textwrap
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

import probos.cognitive.profile_qualification_store as store_module
from probos.cognitive.elastic_team import ElasticTeamSpec, WorkerAttempt, WorkerSlot
from probos.cognitive.elastic_team_store import ElasticTeamConflict, ElasticTeamStore
from probos.cognitive.execution_profile import ExecutionProfile
from probos.cognitive.profile_qualification_store import (
    MAX_CANDIDATES,
    ProfileQualification,
    ProfileQualificationStore,
    ProfileQualificationStoreUnavailable,
    SlotAdmissionRefused,
    admit_qualified_attempt,
    check_slot_qualification,
)
from probos.cognitive.skill_catalog import CognitiveSkillCatalog
from tests.test_ad1286_elastic_team_contract import _attempt, _review_slot, _slot, _spec
from tests.test_ad1287_execution_profile import _profile
from tests.test_ad1287_profile_qualification_store import _Clock, _evaluation, _started

_LOGGER = store_module.logger.name
_SRC_PROBOS = Path(__file__).resolve().parent.parent / "src" / "probos"
# an analyst profile for AD-1286's ``analyse`` slot (role, task class and the suite id that slot names)
_ANALYST: dict[str, Any] = {
    "role_id": "analyst",
    "task_class": "evidence_analysis",
    "evaluation_suite.qualification_id": "evidence_analysis",
}
_NON_QUALIFIED = ("unevaluated", "expired", "invalidated", "insufficient_sample", "failed", "structurally_invalid")


# --------------------------------------------------------------------------------------
# Test doubles and helpers
# --------------------------------------------------------------------------------------


class _FakeReader:
    """A ``ProfileQualificationReader`` answering every question with one canned result, and noting the questions."""

    def __init__(self, answer: ProfileQualification | None) -> None:
        self.answer = answer
        self.asked: list[str] = []

    async def get_qualification(self, profile_ref: str) -> ProfileQualification | None:
        self.asked.append(profile_ref)
        return self.answer


class _FakeTeams:
    """A ``TeamAttemptRecorder`` with one spec (or none) that records its calls; ``record_attempt`` can fail."""

    def __init__(self, spec: ElasticTeamSpec | None, record_error: BaseException | None = None) -> None:
        self._spec = spec
        self._record_error = record_error
        self.spec_lookups: list[str] = []
        self.recorded: list[WorkerAttempt] = []

    async def get_team_spec(self, team_spec_ref: str) -> ElasticTeamSpec | None:
        self.spec_lookups.append(team_spec_ref)
        return self._spec

    async def record_attempt(self, attempt: WorkerAttempt) -> WorkerAttempt:
        self.recorded.append(attempt)
        if self._record_error is not None:
            raise self._record_error
        return attempt


class _World:
    """The two real stores the slot boundary joins, each on its own file, and the clock the qualification side reads.

    ``start`` always builds NEW store instances, so ``stop()`` then ``start()`` is a restart in which nothing but the
    two files carries over. The team store keeps its own wall clock: only the qualification store's clock decides
    expiry, and a test moves it through ``clock``.
    """

    qualifications: ProfileQualificationStore
    teams: ElasticTeamStore

    def __init__(self, directory: Path) -> None:
        self.clock = _Clock(1000.0)
        self._qualifications_path = directory / "profile_qualifications.db"
        self._teams_path = directory / "elastic_teams.db"

    async def start(self) -> None:
        self.qualifications = await _started(self._qualifications_path, clock=self.clock)
        self.teams = ElasticTeamStore(str(self._teams_path))
        await self.teams.start()

    async def stop(self) -> None:
        await self.qualifications.stop()
        await self.teams.stop()


@pytest.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    opened = _World(tmp_path)
    await opened.start()
    try:
        yield opened
    finally:
        await opened.stop()  # whichever instances are current: a test that restarted replaced the first pair


def _variant(version: str, **overrides: Any) -> ExecutionProfile:
    """A profile for AD-1286's ``review`` slot (reviewer / finding_review), made distinct by its model version label.

    ``overrides`` are dotted paths as in ``_profile``. Every profile in a test gets its own ``version``, so no two
    share a reference.
    """
    return ExecutionProfile.model_validate(_profile(**{"model.version": version, **overrides}))


# how the evaluator reported each state (``unevaluated`` has no evaluation; ``expired`` and ``invalidated`` were
# qualified when evaluated and are brought to their state afterwards)
_EVALUATIONS: dict[str, dict[str, Any]] = {
    "qualified": {},
    "expired": {},
    "invalidated": {},
    "insufficient_sample": {"passes": 3, "total": 3},
    "failed": {"passes": 2, "total": 4},
    "structurally_invalid": {"structurally_valid": False},
}


async def _in_state(world: _World, state: str, version: str, **overrides: Any) -> str:
    """Register a review-slot profile (``overrides`` change it), bring it to ``state`` and return its reference.

    ``expired`` gives the suite a one second validity and then moves the world's clock two seconds on. The reported
    status is asserted, so a case can never pass for want of the state it names.
    """
    if state == "expired":
        overrides = {"evaluation_suite.validity_seconds": 1, **overrides}
    ref = await world.qualifications.register_profile(_variant(version, **overrides))
    if state in _EVALUATIONS:
        await world.qualifications.record_evaluation(_evaluation(ref, **_EVALUATIONS[state]))
    if state == "invalidated":
        await world.qualifications.invalidate_profile(ref, "inv-1", "evaluator_revoked")
    if state == "expired":
        world.clock.now += 2.0
    qualification = await world.qualifications.get_qualification(ref)
    assert qualification is not None
    assert qualification.status == state
    return ref


def _review() -> WorkerSlot:
    return WorkerSlot.model_validate(_review_slot())


def _refs(candidates: tuple[ProfileQualification, ...]) -> list[str]:
    return [candidate.profile_ref for candidate in candidates]


# --------------------------------------------------------------------------------------
# 1-6. The candidate query
# --------------------------------------------------------------------------------------


async def test_candidates_are_only_qualified_profiles_meeting_the_slot(world: _World) -> None:
    q1 = await _in_state(world, "qualified", "q1")
    q2 = await _in_state(world, "qualified", "q2")
    await _in_state(world, "unevaluated", "u")
    await _in_state(world, "expired", "e")
    await _in_state(world, "invalidated", "i")
    await _in_state(world, "failed", "f")
    await _in_state(world, "structurally_invalid", "s")
    await _in_state(world, "insufficient_sample", "n")
    await _in_state(world, "qualified", "r", role_id="auditor")
    await _in_state(world, "qualified", "t", task_class="finding_audit")
    await _in_state(world, "qualified", "x", **{"evaluation_suite.qualification_id": "other"})

    result = await world.qualifications.find_slot_candidates(_review())

    assert _refs(result.candidates) == sorted([q1, q2])  # exactly the two, in this order
    assert all(candidate.status == "qualified" and candidate.deciding is not None for candidate in result.candidates)
    assert result.complete is True
    assert result.next_after is None
    # the role and task class are selected by the query, so R and T are never examined; X and the six
    # non-qualified profiles are examined and turned away
    assert result.examined == 9


@pytest.mark.parametrize("stronger", ["lower_ref", "higher_ref"])
async def test_candidates_are_in_reference_order_not_ranked(world: _World, stronger: str) -> None:
    low, high = sorted((_variant("p1"), _variant("p2")), key=lambda profile: profile.content_ref())
    passes = {"lower_ref": (4, 3), "higher_ref": (3, 4)}[stronger]  # the one with more passes is 4/4, the other 3/4
    refs = []
    for profile, passed in zip((low, high), passes):
        ref = await world.qualifications.register_profile(profile)
        await world.qualifications.record_evaluation(_evaluation(ref, passes=passed, total=4))  # 3/4 is exactly 7500 bp
        refs.append(ref)

    result = await world.qualifications.find_slot_candidates(_review())

    assert refs == sorted(refs)  # premise: low sorts before high
    assert _refs(result.candidates) == refs  # reference order, whichever candidate has more passes
    assert [candidate.deciding.record.pass_count for candidate in result.candidates] == list(passes)  # premise


async def test_query_is_bounded_and_resumable(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    refs = sorted([await _in_state(world, "qualified", f"v{number}") for number in range(5)])
    slot = _review()
    monkeypatch.setattr(store_module, "_MAX_SCAN", 3)

    first = await world.qualifications.find_slot_candidates(slot)

    assert first.examined == 3
    assert _refs(first.candidates) == refs[:3]
    assert first.complete is False
    assert first.next_after == refs[2]  # the third in reference order

    rest = await world.qualifications.find_slot_candidates(slot, after=first.next_after)

    assert rest.examined == 2
    assert _refs(rest.candidates) == refs[3:]
    assert rest.complete is True
    assert rest.next_after is None

    one = await world.qualifications.find_slot_candidates(slot, limit=1)

    assert one.examined == 1
    assert _refs(one.candidates) == refs[:1]
    assert one.complete is False
    assert one.next_after == refs[0]

    monkeypatch.undo()  # the scan bound is back to its real value
    assert store_module._MAX_SCAN > len(refs)  # premise: it now covers every stored profile
    everything = await world.qualifications.find_slot_candidates(slot, limit=len(refs))

    assert everything.examined == len(refs)
    assert _refs(everything.candidates) == refs
    assert everything.complete is True
    assert everything.next_after is None


async def test_query_is_deterministic(world: _World) -> None:
    await _in_state(world, "qualified", "q1")
    await _in_state(world, "qualified", "q2")
    await _in_state(world, "failed", "f")
    await _in_state(world, "unevaluated", "u")
    slot = _review()

    first = await world.qualifications.find_slot_candidates(slot)
    second = await world.qualifications.find_slot_candidates(slot)

    assert len(first.candidates) == 2  # premise: there is something to compare
    assert first == second


_BAD_QUERY_ARGUMENTS: list[Any] = [
    # (the argument that is bad, a builder of its bad value, the error type, the stable code)
    pytest.param("slot", _review_slot, TypeError, "profile_slot_type_invalid", id="slot-as-dict"),
    pytest.param("slot", lambda: None, TypeError, "profile_slot_type_invalid", id="slot-none"),
    pytest.param("slot", _spec, TypeError, "profile_slot_type_invalid", id="slot-is-a-team-spec"),
    *[
        pytest.param("limit", lambda bad=bad: bad, ValueError, "profile_query_invalid", id=f"limit-{name}")
        for name, bad in (("zero", 0), ("negative", -1), ("over-max", MAX_CANDIDATES + 1), ("true", True),
                          ("float", 1.0), ("text", "16"), ("none", None))
    ],
    *[
        pytest.param("after", lambda bad=bad: bad, ValueError, "profile_query_invalid", id=f"after-{name}")
        for name, bad in (("short", "x"), ("empty", ""), ("uppercase", "A" * 64), ("too-short", "a" * 63),
                          ("not-text", 5))
    ],
]


@pytest.mark.parametrize(("argument", "build", "error_type", "code"), _BAD_QUERY_ARGUMENTS)
async def test_query_refuses_bad_arguments(
    world: _World, argument: str, build: Any, error_type: type[Exception], code: str,
) -> None:
    query = world.qualifications.find_slot_candidates
    slot = _review()
    # premise: a well formed call works, and so do the edges of the allowed range
    await query(slot)
    await query(slot, limit=1)
    await query(slot, limit=MAX_CANDIDATES, after="0" * 64)
    arguments = {"slot": slot, argument: build()}

    with pytest.raises(error_type) as refused:
        await query(arguments.pop("slot"), **arguments)

    assert type(refused.value) is error_type  # not a subclass: these are the stable argument codes
    assert refused.value.args == (code,)


async def test_pinned_slot_narrows_candidates(world: _World) -> None:
    x = await _in_state(world, "qualified", "x", **_ANALYST)
    y = await _in_state(world, "qualified", "y", **_ANALYST)
    unevaluated = await _in_state(world, "unevaluated", "z", **_ANALYST)
    wanted = ["evidence_analysis"]
    open_slot = _spec(
        slots=[_slot(qualification={"qualification_ids": wanted, "pinned_profile_refs": []}), _review_slot()],
    ).slot("analyse")
    pinned_slot = _spec(
        slots=[_slot(qualification={"qualification_ids": wanted, "pinned_profile_refs": [x]}), _review_slot()],
    ).slot("analyse")
    unevaluated_slot = _spec(
        slots=[
            _slot(qualification={"qualification_ids": wanted, "pinned_profile_refs": [unevaluated]}),
            _review_slot(),
        ],
    ).slot("analyse")

    unpinned = await world.qualifications.find_slot_candidates(open_slot)
    pinned = await world.qualifications.find_slot_candidates(pinned_slot)
    pinned_unqualified = await world.qualifications.find_slot_candidates(unevaluated_slot)

    assert _refs(unpinned.candidates) == sorted([x, y])  # premise: without the pin both analysts qualify
    assert _refs(pinned.candidates) == [x]  # the pin narrows the set to X
    assert pinned.complete is True
    assert pinned_unqualified.candidates == ()  # pinning never promotes: every slot still needs a qualified profile


# --------------------------------------------------------------------------------------
# 7. Discoverable is not qualified
# --------------------------------------------------------------------------------------


async def test_unevaluated_catalog_skill_is_discoverable_but_not_qualified(world: _World, tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent("""\
            ---
            name: code-review
            description: Reviews a change for correctness
            ---

            ## Instructions
            Review the change.
        """),
        encoding="utf-8",
    )
    catalog = CognitiveSkillCatalog(skills_dir=tmp_path / "skills")
    await catalog.start()
    try:
        assert catalog.get_entry("code-review") is not None  # premise: the catalog discovered it
        assert (await catalog.validate_skill("code-review")).valid  # premise: and valid by the catalog's own rules
        named = _variant("v1", skills=[{"skill_name": "code-review", "resource_digest": "1" * 64}])
        ref = await world.qualifications.register_profile(named)  # names the catalog skill; never evaluated

        qualification = await world.qualifications.get_qualification(ref)
        candidates = await world.qualifications.find_slot_candidates(_review())

        assert qualification is not None
        assert [skill.skill_name for skill in qualification.profile.skills] == ["code-review"]
        assert qualification.status == "unevaluated"  # naming a discoverable skill qualifies nothing
        assert candidates.candidates == ()  # so the slot query excludes it
        assert catalog.get_entry("code-review") is not None  # while the catalog still returns the entry
    finally:
        await catalog.stop()


# --------------------------------------------------------------------------------------
# 8-9. check_slot_qualification
# --------------------------------------------------------------------------------------

_REFUSALS: list[Any] = [
    # (the state the profile is brought to or None for unregistered, its overrides, the slot asked for, the code)
    pytest.param("qualified", {}, "ghost", "slot_unknown", id="slot_unknown"),
    pytest.param(None, {}, "review", "profile_unknown", id="profile_unknown"),
    pytest.param("qualified", {"role_id": "auditor"}, "review", "profile_role_mismatch", id="role_mismatch"),
    pytest.param(
        "qualified", {"task_class": "finding_audit"}, "review", "profile_task_class_mismatch",
        id="task_class_mismatch",
    ),
    pytest.param(
        "qualified", {"evaluation_suite.qualification_id": "other"}, "review", "profile_qualification_id_mismatch",
        id="qualification_id_mismatch",
    ),
    pytest.param("qualified", _ANALYST, "analyse", "profile_not_pinned", id="not_pinned"),
    *[
        pytest.param(state, {}, "review", f"profile_status_{state}", id=f"status_{state}")
        for state in _NON_QUALIFIED
    ],
    # the slot's declared constraints are checked before the status: an unevaluated auditor is an auditor first
    pytest.param(
        "unevaluated", {"role_id": "auditor"}, "review", "profile_role_mismatch", id="constraints_before_status",
    ),
    pytest.param("qualified", {}, "review", None, id="qualified"),
]


@pytest.mark.parametrize(("state", "overrides", "slot_id", "code"), _REFUSALS)
async def test_check_slot_qualification_refusal_codes(
    world: _World, state: str | None, overrides: dict[str, Any], slot_id: str, code: str | None,
) -> None:
    spec = _spec()
    if state is None:
        ref = _variant("never-registered").content_ref()
    else:
        ref = await _in_state(world, state, "v1", **overrides)

    if code is None:
        qualification = await check_slot_qualification(world.qualifications, spec, slot_id, ref)

        assert qualification == await world.qualifications.get_qualification(ref)
        assert (qualification.profile_ref, qualification.status) == (ref, "qualified")
        assert qualification.deciding is not None
    else:
        with pytest.raises(SlotAdmissionRefused) as refused:
            await check_slot_qualification(world.qualifications, spec, slot_id, ref)

        assert type(refused.value) is SlotAdmissionRefused
        assert refused.value.args == (code,)


@pytest.mark.parametrize("shape", ["other-profiles-evidence", "forged-label", "stale-label"])
async def test_check_slot_qualification_refuses_mismatched_reader_evidence(world: _World, shape: str) -> None:
    spec = _spec()
    a = await _in_state(world, "qualified", "a")
    b = await _in_state(world, "qualified", "b")
    evidence_of_a = await world.qualifications.get_qualification(a)
    evidence_of_b = await world.qualifications.get_qualification(b)
    assert evidence_of_a is not None
    assert evidence_of_b is not None
    # premise: both are genuine and qualified, so the only thing wrong below is whose evidence it is
    assert [(e.profile_ref, e.status) for e in (evidence_of_a, evidence_of_b)] == [(a, "qualified"), (b, "qualified")]
    assert a != b
    honest = _FakeReader(evidence_of_b)
    assert await check_slot_qualification(honest, spec, "review", b) == evidence_of_b  # control: B's own evidence
    assert honest.asked == [b]
    # what a misbehaving reader answers when asked about B. Each shape is wrong in a way only one half of the
    # gate's check can see: the label says B but the profile is A's, or the profile is B's but the label says A
    answers = {
        "other-profiles-evidence": evidence_of_a,
        "forged-label": dataclasses.replace(evidence_of_a, profile_ref=b),
        "stale-label": dataclasses.replace(evidence_of_b, profile_ref=a),
    }
    reader = _FakeReader(answers[shape])

    with pytest.raises(SlotAdmissionRefused) as refused:
        await check_slot_qualification(reader, spec, "review", b)

    assert type(refused.value) is SlotAdmissionRefused
    assert refused.value.args == ("profile_evidence_mismatch",)
    assert reader.asked == [b]  # premise: it was B that the gate asked about


# --------------------------------------------------------------------------------------
# 10-15. admit_qualified_attempt
# --------------------------------------------------------------------------------------


async def test_slot_boundary_refuses_unqualified_and_admits_the_exact_qualified_profile_across_restart(
    world: _World,
) -> None:
    spec = _spec()
    spec_ref = await world.teams.put_team_spec(spec)
    a = await world.qualifications.register_profile(_variant("a"))
    b = await world.qualifications.register_profile(_variant("b"))
    await world.qualifications.record_evaluation(_evaluation(a))
    before = (world.qualifications, world.teams)
    await world.stop()
    await world.start()  # NEW instances on the same two files: nothing but the files carries over
    assert world.qualifications is not before[0]
    assert world.teams is not before[1]
    with pytest.raises(ProfileQualificationStoreUnavailable):
        await before[0].get_qualification(a)  # premise: the first instance is stopped, so it cannot be what answers
    assert await world.teams.get_team_spec(spec_ref) == spec  # premise: the spec crossed the restart in the file
    statuses = [(await world.qualifications.get_qualification(ref)).status for ref in (a, b)]
    assert statuses == ["qualified", "unevaluated"]  # premise: decided from the persisted evaluation
    # one ordinal-1 id for both attempts: they differ only in the profile they name
    attempt_b = _attempt(team_spec_ref=spec_ref, slot_id="review", execution_profile_ref=b)
    attempt_a = _attempt(team_spec_ref=spec_ref, slot_id="review", execution_profile_ref=a)
    assert attempt_a.worker_attempt_id == attempt_b.worker_attempt_id

    with pytest.raises(SlotAdmissionRefused) as refused:
        await admit_qualified_attempt(world.qualifications, world.teams, attempt_b)

    assert type(refused.value) is SlotAdmissionRefused
    assert refused.value.args == ("profile_status_unevaluated",)
    assert await world.teams.get_attempt(attempt_b.worker_attempt_id) is None

    admitted = await admit_qualified_attempt(world.qualifications, world.teams, attempt_a)

    # if the refused call had recorded anything under this id, AD-1286 would have raised elastic_attempt_conflict
    assert admitted == attempt_a
    stored = await world.teams.get_attempt(attempt_a.worker_attempt_id)
    assert stored is not None
    assert stored.execution_profile_ref == a


@pytest.mark.parametrize("state", [*_NON_QUALIFIED, "drifted"])
async def test_slot_boundary_refuses_each_disqualifying_profile_and_records_nothing(
    world: _World, state: str, caplog: pytest.LogCaptureFixture,
) -> None:
    spec = _spec()
    spec_ref = await world.teams.put_team_spec(spec)
    if state == "drifted":
        await _in_state(world, "qualified", "v1")  # A is qualified
        named = await world.qualifications.register_profile(_variant("v2"))  # A with its model.version changed
        drifted = await world.qualifications.get_qualification(named)
        assert drifted is not None
        assert drifted.status == "unevaluated"  # premise: registered, and no credential carried over from A
        expected = "unevaluated"
    else:
        named = await _in_state(world, state, "v1")
        expected = state
    qualifying = await _in_state(world, "qualified", "v-ok")  # for the control at the end
    attempt = _attempt(team_spec_ref=spec_ref, slot_id="review", execution_profile_ref=named)

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        with pytest.raises(SlotAdmissionRefused) as refused:
            await admit_qualified_attempt(world.qualifications, world.teams, attempt)

    assert type(refused.value) is SlotAdmissionRefused
    assert refused.value.args == (f"profile_status_{expected}",)
    refusals = [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno == logging.INFO]
    assert len(refusals) == 1  # the refusal is logged at info, naming the profile and the code
    assert named in refusals[0]
    assert f"profile_status_{expected}" in refusals[0]
    assert await world.teams.get_attempt(attempt.worker_attempt_id) is None
    listed = {"session_id": attempt.session_id, "team_spec_ref": spec_ref, "slot_id": "review"}
    assert await world.teams.list_slot_attempts(**listed) == ()
    # control: the lookups above do see a recorded attempt, and the refused call left nothing under this id
    same_id = _attempt(team_spec_ref=spec_ref, slot_id="review", execution_profile_ref=qualifying)
    assert same_id.worker_attempt_id == attempt.worker_attempt_id
    admitted = await admit_qualified_attempt(world.qualifications, world.teams, same_id)
    assert await world.teams.get_attempt(attempt.worker_attempt_id) == admitted
    assert await world.teams.list_slot_attempts(**listed) == (admitted,)


async def test_refusal_never_calls_record_attempt(world: _World) -> None:
    spec = _spec()
    ref = await _in_state(world, "unevaluated", "v1")
    teams = _FakeTeams(spec)
    attempt = _attempt(team_spec_ref=spec.content_ref(), slot_id="review", execution_profile_ref=ref)

    with pytest.raises(SlotAdmissionRefused) as refused:
        await admit_qualified_attempt(world.qualifications, teams, attempt)

    assert refused.value.args == ("profile_status_unevaluated",)
    assert teams.recorded == []  # record_attempt was never called
    assert teams.spec_lookups == [spec.content_ref()]  # the spec was looked up, once


async def test_record_attempt_errors_propagate_unchanged(world: _World) -> None:
    spec = _spec()
    ref = await _in_state(world, "qualified", "v1")
    failure = ElasticTeamConflict("elastic_attempt_budget_exhausted")
    teams = _FakeTeams(spec, record_error=failure)
    attempt = _attempt(team_spec_ref=spec.content_ref(), slot_id="review", execution_profile_ref=ref)

    with pytest.raises(ElasticTeamConflict) as raised:
        await admit_qualified_attempt(world.qualifications, teams, attempt)

    assert teams.recorded == [attempt]  # premise: the gate admitted the attempt and handed it on, once
    assert raised.value is failure  # the very exception, not a wrapper or a copy
    assert raised.value.args == ("elastic_attempt_budget_exhausted",)


async def test_unknown_spec_is_refused(world: _World) -> None:
    spec = _spec()
    ref = await _in_state(world, "qualified", "v1")
    teams = _FakeTeams(None)
    attempt = _attempt(team_spec_ref=spec.content_ref(), slot_id="review", execution_profile_ref=ref)

    with pytest.raises(SlotAdmissionRefused) as refused:
        await admit_qualified_attempt(world.qualifications, teams, attempt)

    assert type(refused.value) is SlotAdmissionRefused
    assert refused.value.args == ("slot_spec_unknown",)
    assert teams.spec_lookups == [spec.content_ref()]
    assert teams.recorded == []
    for wrong in (None, attempt.model_dump(), spec):  # not a WorkerAttempt: refused before anything is looked up
        with pytest.raises(TypeError) as mistyped:
            await admit_qualified_attempt(world.qualifications, teams, wrong)
        assert type(mistyped.value) is TypeError
        assert mistyped.value.args == ("elastic_attempt_type_invalid",)
    assert teams.spec_lookups == [spec.content_ref()]
    assert teams.recorded == []
    for wrong in (None, spec.model_dump()):  # check_slot_qualification names its own argument the same way
        with pytest.raises(TypeError) as mistyped:
            await check_slot_qualification(world.qualifications, wrong, "review", ref)
        assert type(mistyped.value) is TypeError
        assert mistyped.value.args == ("profile_slot_type_invalid",)


async def test_identical_replay_after_expiry_is_refused(world: _World) -> None:
    spec = _spec()
    spec_ref = await world.teams.put_team_spec(spec)
    ref = await _in_state(world, "qualified", "v1")
    attempt = _attempt(team_spec_ref=spec_ref, slot_id="review", execution_profile_ref=ref)
    first = await admit_qualified_attempt(world.qualifications, world.teams, attempt)
    # premise: while the profile still qualifies, an identical replay is acknowledged
    assert await admit_qualified_attempt(world.qualifications, world.teams, attempt) == first
    world.clock.now = 1000.0 + 86_400.0 + 1.0  # past the suite's validity
    expired = await world.qualifications.get_qualification(ref)
    assert expired is not None
    assert expired.status == "expired"  # premise

    with pytest.raises(SlotAdmissionRefused) as refused:
        await admit_qualified_attempt(world.qualifications, world.teams, attempt)

    assert type(refused.value) is SlotAdmissionRefused
    assert refused.value.args == ("profile_status_expired",)
    assert await world.teams.get_attempt(attempt.worker_attempt_id) == first  # the first record is still there


# --------------------------------------------------------------------------------------
# 16. Not wired
# --------------------------------------------------------------------------------------

# AD-1287 S2a added two modules and a gate, and S2b a module and a recorder: the scan covers them, and spares them
# as owners, the same way
_S1_MODULES = (
    "execution_profile",
    "profile_qualification_store",
    "profile_components",
    "profile_currency",
    "profile_drift_recorder",
)
_GATE_NAMES = (
    "ProfileQualificationStore",
    "admit_qualified_attempt",
    "check_slot_qualification",
    "admit_current_qualified_attempt",
    "RegistryComponentSource",
    "record_component_drift",
)
# AD-1288 S1: the one consumer allowed to import the S1/S2a modules and call the gate (O-1). Not a gate module, so it
# is spared as an owner here rather than added to ``_S1_MODULES`` (which the S2b test imports).
_ADMISSION_CONSUMERS = ("elastic_commission",)


def _gate_references(tree: ast.AST) -> list[str]:
    """Direct syntactic references in ``tree``: an import of an S1 module, or a call whose callee is a gate name or an attribute named one. Not found here: a call through a plain alias (``S = ProfileQualificationStore; S()``) or a lookup by string (``getattr``, ``sys.modules``)."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name in _GATE_NAMES:
                found.append(f"call of {name} at line {node.lineno}")
        elif isinstance(node, ast.ImportFrom):
            imported = [(node.module or "").split(".")[-1], *(alias.name for alias in node.names)]
            if any(name in _S1_MODULES for name in imported):
                found.append(f"import-from at line {node.lineno}")
        elif isinstance(node, ast.Import):
            if any(alias.name.split(".")[-1] in _S1_MODULES for alias in node.names):
                found.append(f"import at line {node.lineno}")
    return found


_FORBIDDEN_SHAPES = (
    "ProfileQualificationStore('x.db')",
    "registry.ProfileQualificationStore('x.db')",
    "m = importlib.import_module('probos.cognitive.profile_qualification_store')\nm.ProfileQualificationStore('x.db')",
    "async def f():\n    return await admit_qualified_attempt(q, t, a)",
    "async def f():\n    return await module.admit_qualified_attempt(q, t, a)",
    "async def f():\n    return await check_slot_qualification(q, s, 'a', 'b')",
    "async def f():\n    return await module.check_slot_qualification(q, s, 'a', 'b')",
    "from probos.cognitive.profile_qualification_store import ProfileQualificationStore",
    "from probos.cognitive import profile_qualification_store",
    "import probos.cognitive.profile_qualification_store as store",
    "from probos.cognitive.execution_profile import ExecutionProfile",
    "from probos.cognitive import execution_profile",
    "import probos.cognitive.execution_profile",
    "from .execution_profile import ExecutionProfile",
    "from . import profile_qualification_store",
    "def late():\n    from probos.cognitive.profile_qualification_store import admit_qualified_attempt\n",
)
_ALLOWED_SHAPES = (
    "owner_symbol = 'ProfileQualificationStore'",
    "owner_module = 'probos.cognitive.profile_qualification_store'",
    "note = 'admit_qualified_attempt, check_slot_qualification and probos.cognitive.execution_profile'",
    '"""A docstring that names ProfileQualificationStore and calls admit_qualified_attempt(...)."""',
    "ref = attempt.execution_profile_ref",
    "from probos.cognitive.elastic_team import WorkerAttempt",
)


def _scan_tree(root: Path, owned: list[Path]) -> tuple[list[str], dict[str, list[str]]]:
    """Parse every ``*.py`` under ``root`` (bar ``owned``) that names an S1 module or a gate function.

    Returns the relative paths that were parsed and, for each path with any, the references found in it.
    """
    needles = tuple(name.encode() for name in (*_S1_MODULES, *_GATE_NAMES))
    parsed: list[str] = []
    offenders: dict[str, list[str]] = {}
    for path in root.rglob("*.py"):
        if path in owned:
            continue
        raw = path.read_bytes()
        if not any(needle in raw for needle in needles):
            continue  # names no S1 module or gate name, so it holds no direct syntactic reference: not worth a parse
        relative = path.relative_to(root).as_posix()
        parsed.append(relative)
        references = _gate_references(ast.parse(raw, filename=str(path)))
        if references:
            offenders[relative] = references
    return parsed, offenders


def test_nothing_in_src_constructs_the_store_or_calls_the_gate(tmp_path: Path) -> None:
    """Pins D5: no file under ``src/probos`` except the S1 and S2a modules (``_S1_MODULES``) holds a direct syntactic reference to them (an import of one of them, or a call of the store, a gate function or the S2a source by name or attribute).

    AD-1288 (commission admission) constructs the store and routes admission through ``admit_current_qualified_attempt``,
    and changes this test deliberately. The scan is AST-based: a string that merely names a store, a module or a
    function (as the store declaration does) is not a reference.
    Calls through a plain alias and lookups by string are not covered; this test does not assert them either way.
    """
    owned = [_SRC_PROBOS / "cognitive" / f"{name}.py" for name in _S1_MODULES]
    assert all(path.is_file() for path in owned)  # premise: the modules the scan excludes are where it expects them
    # AD-1288 S1: commission admission is spared too, and it really references the gate, so sparing it is not vacuous
    consumers = [_SRC_PROBOS / "cognitive" / f"{name}.py" for name in _ADMISSION_CONSUMERS]
    assert all(path.is_file() for path in consumers)
    assert all(_gate_references(ast.parse(path.read_bytes())) for path in consumers)

    # the scanner is not vacuous: it flags each shape it exists to forbid, and not a string that merely names one
    for snippet in _FORBIDDEN_SHAPES:
        assert _gate_references(ast.parse(snippet)), snippet
    for snippet in _ALLOWED_SHAPES:
        assert _gate_references(ast.parse(snippet)) == [], snippet
    # ... nor on the real thing: the store module does import execution_profile, so only the exclusion spares it
    assert _gate_references(ast.parse(owned[1].read_bytes()))
    # ... and the real declaration names the store, its module and the gate only as strings
    declared = (_SRC_PROBOS / "cognitive" / "storage_declarations.py").read_text(encoding="utf-8")
    assert "probos.cognitive.profile_qualification_store" in declared
    assert "ProfileQualificationStore" in declared
    assert "admit_current_qualified_attempt" in declared
    assert _gate_references(ast.parse(declared)) == []

    # the tree scan is not vacuous either: in a scratch tree it reports a violating file, and spares the excluded
    # owner, a file that only names things as strings, and a file that names nothing
    scratch = tmp_path / "scratch" / "cognitive"
    scratch.mkdir(parents=True)
    (scratch / "offender.py").write_text(
        "from probos.cognitive.profile_qualification_store import ProfileQualificationStore\n"
        "store = ProfileQualificationStore('x.db')\n",
        encoding="utf-8",
    )
    (scratch / "declares.py").write_text("OWNER = 'probos.cognitive.profile_qualification_store'\n", encoding="utf-8")
    (scratch / "unrelated.py").write_text("VALUE = 1\n", encoding="utf-8")
    (scratch / "execution_profile.py").write_text(
        "from probos.cognitive.profile_qualification_store import ProfileQualificationStore\n", encoding="utf-8",
    )
    scratch_parsed, scratch_offenders = _scan_tree(tmp_path / "scratch", [scratch / "execution_profile.py"])
    assert sorted(scratch_parsed) == ["cognitive/declares.py", "cognitive/offender.py"]
    assert list(scratch_offenders) == ["cognitive/offender.py"]

    parsed, offenders = _scan_tree(_SRC_PROBOS, owned + consumers)
    # premise: the scan reached the tree, and parsed files that only mention the names (``execution_profile_ref``,
    # strings) rather than skipping or flagging them
    assert {"cognitive/elastic_team.py", "cognitive/storage_declarations.py"} <= set(parsed)
    assert offenders == {}
