"""AD-1287 S3 (M2): the outcome-learning producer, and the one chain on the real stores.

Contract: ``prompts/ad-1287-s3-outcome-learning.md``, "Tests" and M2 (7 tests), with decisions D2, D3 and D6. Tests 1-5
drive ``learn_attempt_outcome`` through two hand-written doubles, ``_FakeAttempts`` (an ``AttemptOutcomeReader``) and
``_FakeOutcomes`` (a ``ProfileOutcomeRecorder``). Each double notes its calls, so a test can say exactly which reads and
writes happened, and that none did. Test 6 is the seam test: the real ``ElasticTeamStore`` and the real
``ProfileQualificationStore`` on two ``tmp_path`` files, admission through ``admit_qualified_attempt``, outcomes through
``record_attempt_outcome``, learning through ``learn_attempt_outcome``, then a restart in which nothing but the two files
carries over. Test 7 compares the real methods' signatures with the two ports. Nothing here uses a mock library.

The helpers are copies, never imports from another test module: ``_Clock`` and ``_World`` from the S1 store and slot
tests, ``_PROFILE`` and ``_evaluation`` from the S1 profile tests, ``_attempt`` and the one-slot ``_SPEC`` from AD-1286's
contract tests. Direct ``sqlite3`` is used once, to count ``profile_outcomes`` rows from outside the store.
"""

from __future__ import annotations

import contextlib
import copy
import inspect
import logging
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, get_type_hints

import pytest
from pydantic import TypeAdapter

import probos.cognitive.profile_qualification_store as store_module
from probos.cognitive.elastic_team import (
    ElasticId,
    ElasticTeamSpec,
    WorkerAttempt,
    WorkerAttemptOutcome,
    derive_worker_attempt_id,
)
from probos.cognitive.elastic_team_store import ElasticTeamStore, ElasticTeamStoreUnavailable
from probos.cognitive.execution_profile import EvaluationRecord, ExecutionProfile
from probos.cognitive.profile_qualification_store import (
    AttemptOutcomeReader,
    ProfileOutcomeLearning,
    ProfileOutcomeRecorder,
    ProfileOutcomeState,
    ProfileQualificationStore,
    ProfileQualificationStoreUnavailable,
    RecordedProfileOutcome,
    SlotAdmissionRefused,
    admit_qualified_attempt,
    learn_attempt_outcome,
)

_LOGGER = store_module.logger.name
_TASK_CLASS = "finding_review"
_SPEC_REF = "b" * 64  # tests 1-5 never read a spec or a profile: any well-formed reference names them
_PROFILE_REF = "a" * 64
# AD-1286's outcome codes: ``succeeded`` has none, and the other two must have one (``elastic_attempt_outcome_invalid``)
_CODES: dict[str, str | None] = {"succeeded": None, "failed": "model_timeout", "cancelled": "owner_cancelled"}
# ids the producer must refuse before it reads anything: empty, not the id grammar, too long, and not a string
_MALFORMED_IDS: tuple[Any, ...] = ("", "not an id", "x" * 129, None)
_ID_GRAMMAR = TypeAdapter(ElasticId)  # AD-1286's own id grammar: what the producer's malformed-id check is made of

# the S1 profile fixture: a reviewer for task class ``finding_review``, whose suite needs 4 samples and 7500 bp passing
_PROFILE: dict[str, Any] = {
    "schema_version": 1,
    "role_id": "reviewer",
    "task_class": _TASK_CLASS,
    "skills": [
        {"skill_name": "code-review", "resource_digest": "1" * 64},
        {"skill_name": "audit-trail", "resource_digest": "2" * 64},
    ],
    "model": {"provider": "anthropic", "name": "claude-sonnet-5.5", "version": "2026-09-01"},
    "prompts": [{"prompt_id": "review.system", "revision_digest": "3" * 64}],
    "tools": [{"tool_id": "codebase_query", "schema_digest": "4" * 64, "implementation_digest": "5" * 64}],
    "policy": {"policy_digest": "6" * 64},
    "evaluation_suite": {
        "qualification_id": "finding_review",
        "suite_revision": 1,
        "dataset_digest": "d" * 64,
        "min_samples": 4,
        "min_pass_bp": 7500,
        "validity_seconds": 86400,
    },
}
# AD-1286's KAT spec cut to its ``review`` slot (reviewer / finding_review, no pinned profile): the slot ``_PROFILE`` fills
_SPEC: dict[str, Any] = {
    "schema_version": 1,
    "team_id": "review-team",
    "revision": 1,
    "process": {"bill": {"bill_id": "incident-review", "bill_version": 3}, "plan_hash": None},
    "slots": [
        {
            "slot_id": "review",
            "role_id": "reviewer",
            "task_class": _TASK_CLASS,
            "capacity": {"minimum": 1, "maximum": 1},
            "qualification": {"qualification_ids": ["finding_review"], "pinned_profile_refs": []},
            "independence": {"mode": "none", "min_distinct": 1},
            "merge": {"kind": "single", "quorum": None, "reducer_id": None, "adjudicator_slot_id": None},
            "budget": {"max_tokens": 100000, "max_wall_ms": 600000, "max_attempts": 2},
            "authority": {"tool_scopes": [], "data_scopes": ["incident.records"]},
        },
    ],
}


# --------------------------------------------------------------------------------------
# Test doubles and helpers
# --------------------------------------------------------------------------------------


class _Clock:
    """A wall clock, in seconds, that a test can move."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _FakeAttempts:
    """An ``AttemptOutcomeReader`` answering every question with one canned attempt and one canned outcome, whichever id
    is asked, and noting each call in ``calls``, in order."""

    def __init__(self, attempt: WorkerAttempt | None, outcome: WorkerAttemptOutcome | None) -> None:
        self.attempt = attempt
        self.outcome = outcome
        self.calls: list[tuple[str, Any]] = []

    async def get_attempt(self, worker_attempt_id: str) -> WorkerAttempt | None:
        self.calls.append(("get_attempt", worker_attempt_id))
        return self.attempt

    async def get_attempt_outcome(self, worker_attempt_id: str) -> WorkerAttemptOutcome | None:
        self.calls.append(("get_attempt_outcome", worker_attempt_id))
        return self.outcome


class _FakeOutcomes:
    """A ``ProfileOutcomeRecorder`` that, like the real store, keeps the first row it stored for each attempt and returns
    that row on every repeat. Each call is noted in ``calls``; the rows it stored are in ``rows``."""

    def __init__(self) -> None:
        self.calls: list[tuple[WorkerAttempt, WorkerAttemptOutcome]] = []
        self.rows: dict[str, RecordedProfileOutcome] = {}

    async def record_profile_outcome(
        self, attempt: WorkerAttempt, outcome: WorkerAttemptOutcome,
    ) -> RecordedProfileOutcome:
        self.calls.append((attempt, outcome))
        stored = self.rows.get(attempt.worker_attempt_id)
        if stored is None:
            alpha, beta = (3, 2) if outcome.terminal_status == "succeeded" else (2, 3)
            stored = RecordedProfileOutcome(
                attempt.worker_attempt_id,
                attempt.execution_profile_ref,
                _TASK_CLASS,
                outcome.terminal_status,
                outcome.error_code,
                len(self.rows) + 1,
                alpha,
                beta,
                1_000 * len(self.calls),  # a later call would stamp a later time: only the first call's stamp is kept
            )
            self.rows[attempt.worker_attempt_id] = stored
        return stored


class _World:
    """The two real stores the chain joins, each on its own file, and the clock the qualification side reads.

    ``start`` always builds NEW store instances, so ``stop()`` then ``start()`` is a restart in which nothing but the two
    files carries over. The team store keeps its own wall clock: a test moves the qualification store's through ``clock``.
    """

    qualifications: ProfileQualificationStore
    teams: ElasticTeamStore

    def __init__(self, directory: Path) -> None:
        self.clock = _Clock(1000.0)
        self.qualifications_path = directory / "profile_qualifications.db"
        self.teams_path = directory / "elastic_teams.db"

    async def start(self) -> None:
        self.qualifications = ProfileQualificationStore(str(self.qualifications_path), clock=self.clock)
        await self.qualifications.start()
        self.teams = ElasticTeamStore(str(self.teams_path))
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


def _attempt(**overrides: Any) -> WorkerAttempt:
    """A valid attempt: ordinal 1 of the ``review`` slot in ``session-1``; the id is derived unless one is supplied."""
    fields: dict[str, Any] = {
        "schema_version": 1,
        "team_spec_ref": _SPEC_REF,
        "session_id": "session-1",
        "slot_id": "review",
        "ordinal": 1,
        "execution_profile_ref": _PROFILE_REF,
        "supersedes_attempt_id": None,
    }
    fields.update(overrides)
    if "worker_attempt_id" not in fields:
        fields["worker_attempt_id"] = derive_worker_attempt_id(
            team_spec_ref=fields["team_spec_ref"],
            session_id=fields["session_id"],
            slot_id=fields["slot_id"],
            ordinal=fields["ordinal"],
        )
    return WorkerAttempt.model_validate(fields)


def _outcome(worker_attempt_id: str, status: str) -> WorkerAttemptOutcome:
    """AD-1286's recorded terminal state of an attempt (``succeeded``, ``failed`` or ``cancelled``)."""
    return WorkerAttemptOutcome.model_validate(
        {
            "worker_attempt_id": worker_attempt_id,
            "terminal_status": status,
            "error_code": _CODES[status],
            "recorded_at": 2000.0,
        }
    )


def _profile_model() -> ExecutionProfile:
    return ExecutionProfile.model_validate(copy.deepcopy(_PROFILE))


def _evaluation(profile_ref: str) -> EvaluationRecord:
    """A passing evaluation of the profile: four cases, as many as its suite needs, all passed."""
    return EvaluationRecord.model_validate(
        {
            "schema_version": 1,
            "profile_ref": profile_ref,
            "evaluation_id": "eval-1",
            "evaluator_id": "qual-harness",
            "structurally_valid": True,
            "observations": [
                {"case_id": f"c{number:03d}", "passed": True, "score_bp": 9000, "cost_micro_usd": 120, "latency_ms": 800}
                for number in range(1, 5)
            ],
        }
    )


def _is_well_formed(value: Any) -> bool:
    """Whether AD-1286's own id grammar accepts ``value``."""
    try:
        _ID_GRAMMAR.validate_python(value)
    except ValueError:
        return False
    return True


def _outcome_rows(path: Path) -> int:
    """How many rows ``profile_outcomes`` holds, counted straight from the file by a connection of the test's own."""
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return int(raw.execute("SELECT COUNT(*) FROM profile_outcomes").fetchone()[0])


async def _assert_learned(attempt: WorkerAttempt, outcome: WorkerAttemptOutcome) -> None:
    """The accepted neighbour of each refusal in this file: the same call over a matching, ended attempt records it."""
    asked = attempt.worker_attempt_id
    assert outcome.worker_attempt_id == asked  # premise: the reader's answers are about the attempt asked for
    assert outcome.terminal_status in ("succeeded", "failed")  # premise: a status that is evidence
    attempts = _FakeAttempts(attempt, outcome)
    outcomes = _FakeOutcomes()

    learning = await learn_attempt_outcome(outcomes, attempts, asked)

    assert learning == ProfileOutcomeLearning(asked, "recorded", outcomes.rows[asked])
    assert attempts.calls == [("get_attempt", asked), ("get_attempt_outcome", asked)]
    assert outcomes.calls == [(attempt, outcome)]


# --------------------------------------------------------------------------------------
# 1-5. learn_attempt_outcome over doubles
# --------------------------------------------------------------------------------------


async def test_pending_when_no_outcome_and_nothing_written() -> None:
    attempt = _attempt()
    asked = attempt.worker_attempt_id
    attempts = _FakeAttempts(attempt, None)
    outcomes = _FakeOutcomes()
    assert attempts.outcome is None  # premise: AD-1286 holds the attempt but no outcome: it has not ended

    learning = await learn_attempt_outcome(outcomes, attempts, asked)

    assert learning == ProfileOutcomeLearning(asked, "pending", None)
    assert attempts.calls == [("get_attempt", asked), ("get_attempt_outcome", asked)]
    assert outcomes.calls == []
    assert outcomes.rows == {}
    await _assert_learned(attempt, _outcome(asked, "succeeded"))  # control: once it has ended, the same call learns it


async def test_cancelled_is_not_evidence_and_nothing_written(caplog: pytest.LogCaptureFixture) -> None:
    attempt = _attempt()
    asked = attempt.worker_attempt_id
    cancelled = _outcome(asked, "cancelled")
    assert cancelled.terminal_status == "cancelled"  # premise: AD-1286's owner-side termination, which carries a code
    assert cancelled.error_code is not None
    attempts = _FakeAttempts(attempt, cancelled)
    outcomes = _FakeOutcomes()

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        learning = await learn_attempt_outcome(outcomes, attempts, asked)

    assert learning == ProfileOutcomeLearning(asked, "not_evidence", None)
    assert attempts.calls == [("get_attempt", asked), ("get_attempt_outcome", asked)]
    assert outcomes.calls == []
    assert outcomes.rows == {}
    skipped = [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno == logging.INFO]
    assert len(skipped) == 1  # the skip is logged once, at info, naming the attempt, its status and its profile
    assert asked in skipped[0]
    assert "cancelled" in skipped[0]
    assert attempt.execution_profile_ref in skipped[0]
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        await _assert_learned(attempt, _outcome(asked, "failed"))  # control: the neighbour status, failed, is learned
    assert [r for r in caplog.records if r.name == _LOGGER] == []  # ... and nothing is logged as skipped


@pytest.mark.parametrize("case", ["malformed", "unknown"])
async def test_malformed_and_unknown_attempts_are_refused(case: str) -> None:
    attempt = _attempt()
    ended = _outcome(attempt.worker_attempt_id, "succeeded")
    if case == "malformed":
        # the reader holds the attempt and its outcome, so a refusal here is the producer's, not an empty reader's
        asked_ids, held, code = _MALFORMED_IDS, attempt, "profile_outcome_attempt_invalid"
    else:
        asked_ids, held, code = (attempt.worker_attempt_id,), None, "profile_outcome_attempt_unknown"
    # premise: the malformed ids fail AD-1286's id grammar; the unknown one passes it, so only the reader can refuse it
    assert [_is_well_formed(asked) for asked in asked_ids] == [case == "unknown"] * len(asked_ids)

    for asked in asked_ids:
        attempts = _FakeAttempts(held, ended)
        outcomes = _FakeOutcomes()

        with pytest.raises(ValueError) as refused:
            await learn_attempt_outcome(outcomes, attempts, asked)

        assert type(refused.value) is ValueError, asked
        assert refused.value.args == (code,), asked
        # a malformed id is refused before any read; an unknown one after the attempt read alone
        assert attempts.calls == ([] if case == "malformed" else [("get_attempt", asked)]), asked
        assert outcomes.calls == [], asked
        assert outcomes.rows == {}, asked
    await _assert_learned(attempt, ended)  # control: the id the reader does hold is learned


@pytest.mark.parametrize("answers_for", ["attempt", "outcome"])
async def test_a_reader_answering_for_another_attempt_is_refused(answers_for: str) -> None:
    attempt = _attempt()
    asked = attempt.worker_attempt_id
    other = _attempt(session_id="session-2")
    assert other.worker_attempt_id != asked  # premise: a second, different attempt
    ended = _outcome(asked, "succeeded")
    if answers_for == "attempt":
        # the attempt answered is another's, and the outcome held is the asked one's: only the first check can refuse
        answered_attempt, answered_outcome = other, ended
        expected_reads = [("get_attempt", asked)]  # a mismatched attempt ends the call before the outcome is read
    else:
        # the attempt answered is the asked one's, and the outcome held is another's: only the second check can refuse
        answered_attempt, answered_outcome = attempt, _outcome(other.worker_attempt_id, "succeeded")
        expected_reads = [("get_attempt", asked), ("get_attempt_outcome", asked)]
    assert [answered_attempt.worker_attempt_id == asked, answered_outcome.worker_attempt_id == asked] == (
        [False, True] if answers_for == "attempt" else [True, False]
    )
    attempts = _FakeAttempts(answered_attempt, answered_outcome)
    outcomes = _FakeOutcomes()

    with pytest.raises(ValueError) as refused:
        await learn_attempt_outcome(outcomes, attempts, asked)

    assert type(refused.value) is ValueError
    assert refused.value.args == ("profile_outcome_evidence_mismatch",)
    assert attempts.calls == expected_reads
    assert outcomes.calls == []
    assert outcomes.rows == {}
    await _assert_learned(attempt, ended)  # control: the matching pair is learned


async def test_recorded_returns_the_stored_row_on_every_repeat() -> None:
    attempt = _attempt()
    asked = attempt.worker_attempt_id
    outcome = _outcome(asked, "succeeded")
    attempts = _FakeAttempts(attempt, outcome)
    outcomes = _FakeOutcomes()
    assert outcomes.rows == {}  # premise: nothing is stored before the first learn

    results = [await learn_attempt_outcome(outcomes, attempts, asked) for _ in range(3)]

    stored = outcomes.rows[asked]
    assert len(outcomes.rows) == 1
    assert stored.learned_at_ms == 1_000  # the double kept the FIRST call's row: a later call would have stamped 2_000
    assert results == [ProfileOutcomeLearning(asked, "recorded", stored)] * 3
    assert all(result.recorded is stored for result in results)
    # every repeat reads afresh and asks the recorder again: the producer keeps nothing, idempotency is the recorder's
    assert attempts.calls == [("get_attempt", asked), ("get_attempt_outcome", asked)] * 3
    assert outcomes.calls == [(attempt, outcome)] * 3


# --------------------------------------------------------------------------------------
# 6. The seam: admit, record, learn, restart, replay on the real stores
# --------------------------------------------------------------------------------------


async def test_chain_admit_record_learn_restart_replay(world: _World, tmp_path: Path) -> None:
    profile = _profile_model()
    assert profile.task_class == _TASK_CLASS  # premise: the fixture profile is the review slot's
    spec_ref = await world.teams.put_team_spec(ElasticTeamSpec.model_validate(_SPEC))
    ref = await world.qualifications.register_profile(profile)
    attempts = [
        _attempt(team_spec_ref=spec_ref, session_id=f"session-{number}", execution_profile_ref=ref)
        for number in (1, 2, 3)
    ]
    ids = [attempt.worker_attempt_id for attempt in attempts]
    assert len(set(ids)) == 3  # premise: three distinct attempts of the one slot, one per session
    registered = await world.qualifications.get_qualification(ref)
    assert registered is not None
    assert registered.status == "unevaluated"  # premise: registered, with no evidence yet
    with pytest.raises(SlotAdmissionRefused) as refused:
        await admit_qualified_attempt(world.qualifications, world.teams, attempts[0])
    assert refused.value.args == ("profile_status_unevaluated",)  # premise: the gate refuses a profile not qualified
    assert await world.teams.get_attempt(ids[0]) is None  # ... and records nothing
    with pytest.raises(ValueError) as nothing_to_learn:
        await learn_attempt_outcome(world.qualifications, world.teams, ids[0])
    assert nothing_to_learn.value.args == ("profile_outcome_attempt_unknown",)  # ... so there is nothing to learn

    await world.qualifications.record_evaluation(_evaluation(ref))
    qualified = await world.qualifications.get_qualification(ref)
    assert qualified is not None
    assert qualified.status == "qualified"
    for attempt in attempts:
        assert await admit_qualified_attempt(world.qualifications, world.teams, attempt) == attempt
        assert await world.teams.get_attempt(attempt.worker_attempt_id) == attempt
    # AD-1286 records how each ended: succeeded, failed, and cancelled (an owner-side termination, not a profile result)
    for ended in (_outcome(ids[0], "succeeded"), _outcome(ids[1], "failed"), _outcome(ids[2], "cancelled")):
        assert await world.teams.record_attempt_outcome(ended) == ended
    # premise: recording an outcome in AD-1286 learns nothing; learning is the producer's own step
    assert await world.qualifications.get_outcome_state(ref) == ProfileOutcomeState(ref, _TASK_CLASS, 2, 2, 0, None)
    assert _outcome_rows(world.qualifications_path) == 0

    first = [await learn_attempt_outcome(world.qualifications, world.teams, attempt_id) for attempt_id in ids]

    stamp = 1_000_000  # the qualification clock's 1000.0 seconds, in milliseconds
    assert first == [
        ProfileOutcomeLearning(
            ids[0], "recorded", RecordedProfileOutcome(ids[0], ref, _TASK_CLASS, "succeeded", None, 1, 3, 2, stamp)
        ),
        ProfileOutcomeLearning(
            ids[1], "recorded", RecordedProfileOutcome(ids[1], ref, _TASK_CLASS, "failed", "model_timeout", 2, 3, 3, stamp)
        ),
        ProfileOutcomeLearning(ids[2], "not_evidence", None),
    ]
    assert _outcome_rows(world.qualifications_path) == 2  # the cancelled attempt wrote nothing

    before = (world.qualifications, world.teams)
    await world.stop()
    await world.start()  # NEW instances on the same two files: nothing but the files carries over
    assert world.qualifications is not before[0]
    assert world.teams is not before[1]
    with pytest.raises(ProfileQualificationStoreUnavailable):
        await before[0].get_outcome_state(ref)  # premise: the first instances are stopped, so cannot be what answers
    with pytest.raises(ElasticTeamStoreUnavailable):
        await before[1].get_attempt(ids[0])
    world.clock.now = 1060.0  # a replay that wrote a row would stamp it a minute later
    assert _outcome_rows(world.qualifications_path) == 2  # premise: the rows crossed the restart in the file

    state = await world.qualifications.get_outcome_state(ref)
    assert state == ProfileOutcomeState(ref, profile.task_class, 3, 3, 2, first[1].recorded)
    replayed = [await learn_attempt_outcome(world.qualifications, world.teams, attempt_id) for attempt_id in ids]
    assert replayed == first  # the same dispositions and the same rows, with the first learn's stamp
    assert _outcome_rows(world.qualifications_path) == 2  # ... and no row was added
    assert await world.qualifications.get_outcome_state(ref) == state

    stores = ("profile_qualifications.db", "elastic_teams.db")
    present = {entry.name for entry in tmp_path.iterdir()}
    assert set(stores) <= present  # both stores' files are there, so the next line is not vacuous
    assert present <= {f"{name}{suffix}" for name in stores for suffix in ("", "-wal", "-shm")}


# --------------------------------------------------------------------------------------
# 7. The real stores satisfy the ports
# --------------------------------------------------------------------------------------


def _call_shape(function: Any) -> tuple[bool, list[tuple[str, Any, bool]], dict[str, Any]]:
    """What a caller of a method relies on: whether it is awaited, its parameters after ``self`` as
    ``(name, kind, has_default)`` from ``inspect.signature``, and its annotations resolved to the types they name."""
    parameters = list(inspect.signature(function).parameters.values())[1:]
    return (
        inspect.iscoroutinefunction(function),
        [(p.name, p.kind, p.default is not inspect.Parameter.empty) for p in parameters],
        get_type_hints(function),
    )


class _DriftedReader:
    """Three ways to drift from ``AttemptOutcomeReader.get_attempt``: a renamed parameter, a blocking method, another
    return type."""

    async def renamed(self, attempt_id: str) -> WorkerAttempt | None: ...

    def blocking(self, worker_attempt_id: str) -> WorkerAttempt | None: ...

    async def other_return(self, worker_attempt_id: str) -> WorkerAttemptOutcome | None: ...


def test_the_real_stores_satisfy_the_ports() -> None:
    pairs = [
        (AttemptOutcomeReader, "get_attempt", ElasticTeamStore),
        (AttemptOutcomeReader, "get_attempt_outcome", ElasticTeamStore),
        (ProfileOutcomeRecorder, "record_profile_outcome", ProfileQualificationStore),
    ]
    declared = {
        (port, name)
        for port in (AttemptOutcomeReader, ProfileOutcomeRecorder)
        for name, value in vars(port).items()
        if not name.startswith("_") and inspect.isfunction(value)
    }
    assert declared == {(port, name) for port, name, _real in pairs}  # premise: every method the ports declare is compared
    port_parameters = {
        name: [parameter[0] for parameter in _call_shape(getattr(port, name))[1]] for port, name, _real in pairs
    }
    # premise: the ports name the parameters the producer passes, so a parameter comparison is not vacuous
    assert port_parameters == {
        "get_attempt": ["worker_attempt_id"],
        "get_attempt_outcome": ["worker_attempt_id"],
        "record_profile_outcome": ["attempt", "outcome"],
    }

    for port, name, real in pairs:
        wanted = _call_shape(getattr(port, name))
        assert wanted[0] is True, name  # the ports are awaited
        assert _call_shape(getattr(real, name)) == wanted, name

    # control: the comparison tells a drifted method from a matching one
    reference = _call_shape(AttemptOutcomeReader.get_attempt)
    assert _call_shape(ElasticTeamStore.get_attempt) == reference
    for drifted in (_DriftedReader.renamed, _DriftedReader.blocking, _DriftedReader.other_return):
        assert _call_shape(drifted) != reference, drifted.__name__
