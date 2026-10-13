"""AD-1287 S1 (M2): ProfileQualificationStore -- insert-only evidence, expiry, invalidation and integrity.

Contract: ``prompts/ad-1287-s1-execution-profile-qualification.md``, Section 5 (47 tests: #1-#25, the review round 1
additions #26-#32, #33, a failed close, which is D9's log-and-degrade tier, the review round 2 additions #34-#37, #38,
the store registry's detector still seeing this module's tables, the review round 3 additions #39-#44: a start
that fails while creating, an invalid stored maximum sequence, and the WAL switch, and the review round 4 additions
#45-#47: the WAL switch runs with the busy handler off, an EXCLUSIVE lock holder does not stretch it, and an
``OperationalError`` with no SQLite error code propagates unchanged).
Direct ``sqlite3`` is used in this file only: it plays the file-level writer that the store's triggers, CHECKs,
generated columns and
read-time verification are written against. ``_PROFILE``, ``_profile``, ``_record`` and ``_observations`` come from the M1
test module; they return plain dicts, so this file wraps them with ``model_validate``.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import dataclasses
import hashlib
import importlib.util
import inspect
import json
import logging
import sqlite3
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

import probos.cognitive.profile_qualification_store as store_module
from probos.cognitive.elastic_team import AuthorityCeiling, WorkerSlot, canonicalize_projection
from probos.cognitive.execution_profile import EvaluationRecord, ExecutionProfile
from probos.cognitive.profile_qualification_store import (
    CandidateQueryResult,
    ProfileQualification,
    ProfileQualificationConflict,
    ProfileQualificationIntegrityError,
    ProfileQualificationStore,
    ProfileQualificationStoreUnavailable,
    RecordedEvaluation,
    RecordedInvalidation,
)
from probos.storage.registry import load_default_store_registry
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from tests.test_ad1286_elastic_team_contract import _review_slot
from tests.test_ad1287_execution_profile import (
    _PROFILE,
    _all_field_names,
    _authority_named,
    _observations,
    _probos_imports,
    _profile,
    _record,
)

_LOGGER = "probos.cognitive.profile_qualification_store"
_TABLES = ("execution_profiles", "profile_evaluations", "profile_invalidations")
_COLUMNS: dict[str, tuple[str, ...]] = {  # the STORED columns: a raw INSERT must omit the generated ones (round 1, A1)
    "execution_profiles": ("profile_ref", "schema_version", "canonical_json", "recorded_at_ms"),
    "profile_evaluations": (
        "evidence_ref", "seq", "issued_at_ms", "expires_at_ms", "schema_version", "canonical_json",
    ),
    "profile_invalidations": (
        "profile_ref", "invalidation_id", "seq", "reason_code", "invalidated_at_ms", "schema_version",
    ),
}
_KEYS: dict[str, tuple[str, ...]] = {  # the primary key of each table: the columns that name one row
    "execution_profiles": ("profile_ref",),
    "profile_evaluations": ("evidence_ref",),
    "profile_invalidations": ("profile_ref", "invalidation_id"),
}

_DataCall = Callable[[ProfileQualificationStore], Awaitable[Any]]


# --------------------------------------------------------------------------------------
# Test doubles and helpers
# --------------------------------------------------------------------------------------


class _Clock:
    """A wall clock the test can move (seconds), counting its reads in ``reads``.

    The store reads it exactly once per data-method call that passes argument checks on a started store, including a call it then refuses because the value read is not a valid time, and never in ``start``, ``stop``, an argument refusal or a call on a store that is not started.
    """

    def __init__(self, now: Any = 1000.0) -> None:
        self.now = now
        self.reads = 0

    def __call__(self) -> Any:
        self.reads += 1
        return self.now


class _FakeCursor:
    """The cursor of a statement the proxy answered itself: the rows it was given, and a ``close`` that does nothing."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    async def close(self) -> None:
        return None


class _ProxyConnection:
    """Delegates ``execute`` / ``commit`` / ``close`` to a real connection and counts COMMITs.

    When its factory is armed with an SQL prefix, the matching statement runs on the real connection first, so
    the failure or the park arrives with that row pending in an open transaction. The cursor is closed before
    either and nothing is stored. Measured (orchestrator probe ``probe_1287_r1_cursor.py``, round 1): a retained
    cursor of a completed INSERT does not keep the write lock after the connection closes, and an un-exhausted
    SELECT cursor does. Closing the cursor here is defensive; it is not load-bearing for the INSERT park.

    When the factory's ``foreign_keys`` is a list, the connection's first statement that is not a PRAGMA is
    preceded by a read of ``PRAGMA foreign_keys`` on the real connection, and the value read is appended to that
    list: the setting this connection's first statement ran under (review round 2, C4). Nothing is stored.

    For ``PRAGMA journal_mode=WAL`` it counts the tries and either raises the factory's ``wal_raise`` or answers with
    the factory's ``wal_answer`` without running the statement, or runs it and counts and signals an
    ``OperationalError``; the armed ``fail_on`` / ``park_on`` apply to it as to any statement; and it can hold
    the caller after its next COMMIT until the factory's ``resume`` is set (review rounds 3 and 4, H1, E3, E4a).
    """

    def __init__(self, real: Any, factory: _ProxyFactory) -> None:
        self._real = real
        self._factory = factory
        self._past_pragmas = False  # set by this connection's first statement that is not a PRAGMA
        self._recorded: list[str] | None = None  # this connection's own statements, when the factory arms recording
        if factory.statements is not None:  # review round 4, #45: each new connection adds a list of its own
            self._recorded = []
            factory.statements.append(self._recorded)

    async def execute(self, sql: str, parameters: Sequence[Any] = ()) -> Any:
        factory = self._factory
        if self._recorded is not None:  # first thing, before the statement runs, is answered or raises here
            self._recorded.append(sql)
        if not self._past_pragmas and not sql.lstrip().upper().startswith("PRAGMA"):
            self._past_pragmas = True
            if factory.foreign_keys is not None:  # read the setting this statement is about to run under (C4)
                probe = await self._real.execute("PRAGMA foreign_keys")
                factory.foreign_keys.append((await probe.fetchone())[0])
                await probe.close()
        if sql.startswith("PRAGMA journal_mode=WAL"):  # the store's WAL switch (review rounds 3 and 4)
            factory.wal_tries += 1
            if factory.wal_raise is not None:  # raised as given, without running the statement (round 4, E3)
                raise factory.wal_raise
            if factory.wal_answer is not None:  # answered here: the real statement is not run
                cursor = _FakeCursor([(factory.wal_answer,)])
            else:
                try:
                    cursor = await self._real.execute(sql, parameters)
                except sqlite3.OperationalError:  # the real switch was refused: SQLITE_BUSY while another lock is held
                    factory.wal_busy += 1
                    factory.wal_refused.set()
                    raise
        else:
            cursor = await self._real.execute(sql, parameters)
        if factory.fail_on is not None and sql.startswith(factory.fail_on):
            await cursor.close()
            factory.fired += 1
            raise RuntimeError("injected")
        if factory.park_on is not None and sql.startswith(factory.park_on):
            await cursor.close()
            factory.parked.set()
            await factory.never.wait()  # never set: a parked call leaves only by being cancelled
        return cursor

    async def commit(self) -> None:
        factory = self._factory
        factory.commits += 1
        await self._real.commit()
        if factory.pause_after_commit:  # hold the caller between its COMMIT and what it does next (round 3, H1)
            factory.pause_after_commit = False
            factory.committed.set()
            await factory.resume.wait()

    async def close(self) -> None:
        await self._real.close()
        if self._factory.fail_close:  # the real connection is closed, THEN this raises (AD-1299 S1b's fail_close)
            self._factory.close_fired += 1
            raise RuntimeError("injected close failure")


class _ProxyFactory:
    """Wraps ``SQLiteConnectionFactory``: counts COMMITs; can fail or park on an armed statement, fail closes,
    record ``PRAGMA foreign_keys`` before each connection's first non-PRAGMA statement, hold a caller after its
    next COMMIT, count, answer or raise on the WAL switch, and record each connection's statements."""

    def __init__(self) -> None:
        self._real = SQLiteConnectionFactory()
        self.fail_on: str | None = None  # raise RuntimeError("injected") once this statement has run
        self.park_on: str | None = None  # hold the caller once this statement has run
        self.fired = 0  # how many times the injected failure was raised
        self.fail_close = False  # close the real connection, THEN raise RuntimeError("injected close failure")
        self.close_fired = 0  # how many times the injected close failure was raised
        self.commits = 0  # every commit() any of this factory's connections was asked to make
        self.foreign_keys: list[int] | None = None  # a list arms the probe: each connection appends what it read
        self.parked = asyncio.Event()  # set when a call has parked
        self.never = asyncio.Event()  # never set
        self.pause_after_commit = False  # True: the next commit() runs, then waits for ``resume`` (round 3, H1)
        self.committed = asyncio.Event()  # set when that paused commit() has run
        self.resume = asyncio.Event()  # set by the test to let the paused caller go on
        self.wal_tries = 0  # how many times PRAGMA journal_mode=WAL reached the proxy
        self.wal_busy = 0  # how many of those the real connection refused with an OperationalError
        self.wal_refused = asyncio.Event()  # set on the first such refusal
        self.wal_answer: str | None = None  # a mode: answer the switch with it, without running the statement
        self.wal_raise: BaseException | None = None  # raise this on the switch, without running it (round 4, E3)
        self.statements: list[list[str]] | None = None  # a list arms recording: each new connection adds its own SQL list

    async def connect(self, db_path: str) -> _ProxyConnection:
        return _ProxyConnection(await self._real.connect(db_path), self)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "profile_qualifications.db"


async def _started(path: Path, **kwargs: Any) -> ProfileQualificationStore:
    """A started store on ``path``. It holds no connection between calls, so one left unstopped leaks nothing."""
    store = ProfileQualificationStore(str(path), **kwargs)
    await store.start()
    return store


def _profile_model(**overrides: Any) -> ExecutionProfile:
    return ExecutionProfile.model_validate(_profile(**overrides))


def _evaluation(profile_ref: str, evaluation_id: str = "eval-1", **kwargs: Any) -> EvaluationRecord:
    return EvaluationRecord.model_validate(_record(profile_ref, evaluation_id, **kwargs))


async def _registered(path: Path, **kwargs: Any) -> tuple[ProfileQualificationStore, ExecutionProfile, str]:
    """A started store holding the fixture profile: ``(store, profile, profile_ref)``."""
    store = await _started(path, **kwargs)
    profile = _profile_model()
    return store, profile, await store.register_profile(profile)


async def _populated(path: Path) -> tuple[ProfileQualificationStore, str]:
    """One profile, one evaluation of it (seq 1) and one invalidation recorded after it (seq 2)."""
    store, _profile_, ref = await _registered(path, clock=_Clock())
    await store.record_evaluation(_evaluation(ref))
    await store.invalidate_profile(ref, "inv-1", "evaluator_revoked")
    return store, ref


async def _status(store: ProfileQualificationStore, profile_ref: str) -> ProfileQualification:
    qualification = await store.get_qualification(profile_ref)
    assert qualification is not None
    return qualification


def _rows(path: Path, table: str) -> list[dict[str, Any]]:
    """Every row of ``table`` read straight from the file, by column name (tests only)."""
    with contextlib.closing(sqlite3.connect(path)) as raw:
        raw.row_factory = sqlite3.Row
        return [dict(row) for row in raw.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]


def _snapshot(path: Path) -> dict[str, list[dict[str, Any]]]:
    return {table: _rows(path, table) for table in _TABLES}


def _counts(path: Path) -> tuple[int, ...]:
    """Row counts of ``(execution_profiles, profile_evaluations, profile_invalidations)``."""
    return tuple(len(_rows(path, table)) for table in _TABLES)


def _tamper(path: Path, drop_trigger: str, statement: str, params: tuple[Any, ...]) -> None:
    """Defeat one guard trigger and rewrite a row, as a file-level attacker could.

    Follows ``tests/test_ad1286_elastic_team_store.py:158``; it also asserts the rewrite reached one row, so a
    ``WHERE`` that matches nothing cannot leave a case passing for the wrong reason.
    """
    raw = sqlite3.connect(path)
    try:
        raw.execute(f"DROP TRIGGER {drop_trigger}")
        assert raw.execute(statement, params).rowcount == 1
        raw.commit()
    finally:
        raw.close()


def _insert_sql(table: str, verb: str) -> str:
    columns = _COLUMNS[table]
    return f"{verb} INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})"


def _values(table: str, row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row[column] for column in _COLUMNS[table])


def _data_calls(profile: ExecutionProfile, profile_ref: str, record: EvaluationRecord) -> dict[str, _DataCall]:
    """The six data methods, with arguments well formed in every respect but the store's state."""
    slot = WorkerSlot.model_validate(_review_slot())
    return {
        "register_profile": lambda store: store.register_profile(profile),
        "get_profile": lambda store: store.get_profile(profile_ref),
        "record_evaluation": lambda store: store.record_evaluation(record),
        "invalidate_profile": lambda store: store.invalidate_profile(profile_ref, "inv-1", "evaluator_revoked"),
        "get_qualification": lambda store: store.get_qualification(profile_ref),
        "find_slot_candidates": lambda store: store.find_slot_candidates(slot),
    }


async def _assert_every_call_raises_unavailable(
    store: ProfileQualificationStore, calls: dict[str, _DataCall], code: str,
) -> None:
    for name, call in calls.items():
        try:
            await call(store)
        except ProfileQualificationStoreUnavailable as refused:
            assert refused.args == (code,), name
        else:
            pytest.fail(f"{name} did not raise ProfileQualificationStoreUnavailable({code!r})")


# --------------------------------------------------------------------------------------
# 1-2. Construction and lifecycle
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", ":memory:", None, 5], ids=["empty", "memory", "none", "int"])
def test_constructor_refuses_bad_paths(bad: Any) -> None:
    with pytest.raises(ValueError) as refused:
        ProfileQualificationStore(bad)

    assert type(refused.value) is ValueError
    assert refused.value.args == ("profile_qualification_store_path_invalid",)


async def test_unstarted_and_stopped_store_raise_unavailable(db_path: Path) -> None:
    profile = _profile_model()
    ref = profile.content_ref()
    calls = _data_calls(profile, ref, _evaluation(ref))
    # the list under test is the store's whole public async surface, so a seventh data method cannot slip past it
    public = {name for name, _ in inspect.getmembers(ProfileQualificationStore, inspect.iscoroutinefunction)
              if not name.startswith("_")}
    assert public - {"start", "stop"} == set(calls)
    store = ProfileQualificationStore(str(db_path), clock=_Clock())

    await _assert_every_call_raises_unavailable(store, calls, "profile_qualification_store_unavailable")
    assert not db_path.exists()  # before start() nothing was opened, let alone created

    await store.start()
    await store.start()  # idempotent
    assert await store.register_profile(profile) == ref
    await store.stop()
    await store.stop()  # idempotent
    await _assert_every_call_raises_unavailable(store, calls, "profile_qualification_store_unavailable")

    await store.start()  # start after stop works, and what was recorded before the stop is still there
    assert await store.get_profile(ref) == profile


# --------------------------------------------------------------------------------------
# 3-4. Profiles
# --------------------------------------------------------------------------------------


async def test_register_profile_is_idempotent_and_survives_restart(db_path: Path) -> None:
    clock = _Clock(1000.0)
    store = await _started(db_path, clock=clock)
    profile = _profile_model()

    ref = await store.register_profile(profile)
    first_rows = _rows(db_path, "execution_profiles")
    clock.now = 2000.0
    again = await store.register_profile(profile)

    assert ref == again == profile.content_ref()
    assert len(first_rows) == 1
    assert _rows(db_path, "execution_profiles") == first_rows  # still one row, and the second call changed nothing
    reopened = await _started(db_path, clock=clock)
    assert await reopened.get_profile(ref) == profile


async def test_get_profile_unknown_and_malformed(db_path: Path) -> None:
    store = await _started(db_path, clock=_Clock())
    unknown = "a" * 64

    assert await store.get_profile(unknown) is None
    assert await store.get_qualification(unknown) is None
    for malformed in ("x", "A" * 64, "a" * 63, None, 5):
        for read in (store.get_profile, store.get_qualification):
            with pytest.raises(ValueError) as refused:
                await read(malformed)
            assert type(refused.value) is ValueError, (read.__name__, malformed)
            assert refused.value.args == ("execution_profile_ref_invalid",), (read.__name__, malformed)


# --------------------------------------------------------------------------------------
# 5-7. Recording evaluations
# --------------------------------------------------------------------------------------


async def test_record_evaluation_stamps_issue_expiry_and_sequence(db_path: Path) -> None:
    store, _profile_, ref = await _registered(db_path, clock=_Clock(1000.0))
    record = _evaluation(ref)
    assert 1_000_000 + _PROFILE["evaluation_suite"]["validity_seconds"] * 1_000 == 87_400_000  # premise: one day

    recorded = await store.record_evaluation(record)

    assert isinstance(recorded, RecordedEvaluation)
    assert (recorded.issued_at_ms, recorded.expires_at_ms, recorded.seq) == (1_000_000, 87_400_000, 1)
    assert recorded.record == record
    assert recorded.evidence_ref == record.content_ref()
    rows = _rows(db_path, "profile_evaluations")
    assert len(rows) == 1
    assert rows[0]["canonical_json"] == record.canonical_bytes().decode()


async def test_identical_evaluation_is_idempotent(db_path: Path) -> None:
    clock = _Clock(1000.0)
    store, _profile_, ref = await _registered(db_path, clock=clock)
    record = _evaluation(ref)
    first = await store.record_evaluation(record)
    clock.now = 5000.0

    second = await store.record_evaluation(record)

    assert second == first
    assert (second.seq, second.issued_at_ms) == (1, 1_000_000)  # the first call's stamps, not the later clock's
    assert len(_rows(db_path, "profile_evaluations")) == 1


async def test_conflicting_or_unregistered_evaluation_writes_nothing(db_path: Path) -> None:
    store, _profile_, ref = await _registered(db_path, clock=_Clock())
    await store.record_evaluation(_evaluation(ref, "eval-1"))
    before = _snapshot(db_path)
    different = _record(ref, "eval-1")
    different["observations"] = _observations(3, 4)  # same evaluation_id, other observations
    unregistered = _evaluation("b" * 64, "eval-9")

    with pytest.raises(ProfileQualificationConflict) as conflict:
        await store.record_evaluation(EvaluationRecord.model_validate(different))
    with pytest.raises(ProfileQualificationConflict) as unknown:
        await store.record_evaluation(unregistered)

    assert conflict.value.args == ("profile_evaluation_conflict",)
    assert unknown.value.args == ("profile_unknown",)
    assert _counts(db_path) == (1, 1, 0)
    assert _snapshot(db_path) == before


# --------------------------------------------------------------------------------------
# 8-12. Status from stored evidence
# --------------------------------------------------------------------------------------


async def test_registered_unevaluated_profile_reports_unevaluated(db_path: Path) -> None:
    store, profile, ref = await _registered(db_path, clock=_Clock(1000.0))

    qualification = await _status(store, ref)

    assert qualification.status == "unevaluated"
    assert qualification.deciding is None
    assert qualification.invalidation_reasons == ()
    assert (qualification.profile_ref, qualification.profile) == (ref, profile)
    assert qualification.assessed_at_ms == 1_000_000


@pytest.mark.parametrize(
    ("passes", "total", "structurally_valid", "expected"),
    [
        pytest.param(4, 4, True, "qualified", id="four_of_four"),
        pytest.param(3, 4, True, "qualified", id="three_of_four_at_threshold"),
        pytest.param(2, 4, True, "failed", id="two_of_four"),
        pytest.param(3, 3, True, "insufficient_sample", id="three_of_three"),
        pytest.param(4, 4, False, "structurally_invalid", id="structurally_invalid"),
    ],
)
async def test_statuses_from_stored_evidence(
    db_path: Path, passes: int, total: int, structurally_valid: bool, expected: str,
) -> None:
    store, _profile_, ref = await _registered(db_path, clock=_Clock())
    recorded = await store.record_evaluation(
        _evaluation(ref, passes=passes, total=total, structurally_valid=structurally_valid)
    )

    qualification = await _status(store, ref)

    assert qualification.status == expected
    assert qualification.deciding == recorded


async def test_latest_evaluation_decides(db_path: Path) -> None:
    store, _profile_, ref = await _registered(db_path, clock=_Clock())

    await store.record_evaluation(_evaluation(ref, "eval-1"))
    after_pass = await _status(store, ref)
    await store.record_evaluation(_evaluation(ref, "eval-2", passes=2))
    after_fail = await _status(store, ref)
    await store.record_evaluation(_evaluation(ref, "eval-3"))
    after_repass = await _status(store, ref)

    assert after_pass.status == "qualified"  # premise: the earlier pass really qualified it
    assert after_fail.status == "failed"  # a newer failed run is not masked by the older pass
    assert after_fail.deciding is not None and after_fail.deciding.seq == 2
    assert after_repass.status == "qualified"
    assert after_repass.deciding is not None and after_repass.deciding.seq == 3


async def test_expiry_survives_restart(db_path: Path) -> None:
    store, _profile_, ref = await _registered(db_path, clock=_Clock(1000.0))
    await store.record_evaluation(_evaluation(ref))  # issued at 1_000_000 ms, valid for one day
    assert 1_000_000 + _PROFILE["evaluation_suite"]["validity_seconds"] * 1_000 == 87_400_000  # premise

    clock = _Clock(87399.5)
    reopened = await _started(db_path, clock=clock)
    just_before = await _status(reopened, ref)
    clock.now = 87400.0
    at_expiry = await _status(reopened, ref)

    assert just_before.status == "qualified"
    assert at_expiry.status == "expired"


async def test_invalidation_applies_to_earlier_evaluations_and_survives_restart(db_path: Path) -> None:
    clock = _Clock()
    store, _profile_, ref = await _registered(db_path, clock=clock)
    await store.record_evaluation(_evaluation(ref, "eval-1"))
    assert (await _status(store, ref)).status == "qualified"  # premise: it qualified before the invalidation

    await store.invalidate_profile(ref, "inv-1", "evaluator_revoked")
    invalidated = await _status(store, ref)
    reopened = await _started(db_path, clock=clock)
    after_restart = await _status(reopened, ref)
    await reopened.record_evaluation(_evaluation(ref, "eval-2"))
    requalified = await _status(reopened, ref)

    assert (invalidated.status, invalidated.invalidation_reasons) == ("invalidated", ("evaluator_revoked",))
    assert (after_restart.status, after_restart.invalidation_reasons) == ("invalidated", ("evaluator_revoked",))
    assert (requalified.status, requalified.invalidation_reasons) == ("qualified", ())
    assert requalified.deciding is not None and requalified.deciding.record.evaluation_id == "eval-2"


# --------------------------------------------------------------------------------------
# 13-15. Invalidation records and the store-wide sequence
# --------------------------------------------------------------------------------------


async def test_invalidation_is_idempotent_and_conflicts_on_another_reason(db_path: Path) -> None:
    clock = _Clock(1000.0)
    store, _profile_, ref = await _registered(db_path, clock=clock)
    first = await store.invalidate_profile(ref, "inv-1", "evaluator_revoked")
    clock.now = 2000.0

    again = await store.invalidate_profile(ref, "inv-1", "evaluator_revoked")
    with pytest.raises(ProfileQualificationConflict) as conflict:
        await store.invalidate_profile(ref, "inv-1", "manual")

    assert isinstance(first, RecordedInvalidation)
    assert again == first
    assert again.invalidated_at_ms == 1_000_000  # the first call's stamp, not the later clock's
    assert conflict.value.args == ("profile_invalidation_conflict",)
    rows = _rows(db_path, "profile_invalidations")
    assert len(rows) == 1
    assert rows[0]["reason_code"] == "evaluator_revoked"


async def test_invalidation_refuses_bad_input_and_unknown_profile(db_path: Path) -> None:
    store, _profile_, ref = await _registered(db_path, clock=_Clock())
    before = _snapshot(db_path)
    bad_inputs: list[tuple[Any, Any, Any]] = [
        ("x", "inv-1", "evaluator_revoked"),  # malformed reference
        (ref, "bad id", "evaluator_revoked"),  # malformed invalidation id
        (ref, "inv-1", "Bad"),  # reason code with an uppercase letter
        (ref, "inv-1", ""),  # empty reason code
        (ref, "inv-1", "a" * 65),  # reason code one character too long
        (ref, "inv-1", 5),  # reason code that is not text
    ]

    for arguments in bad_inputs:
        with pytest.raises(ValueError) as refused:
            await store.invalidate_profile(*arguments)
        assert type(refused.value) is ValueError, arguments
        assert refused.value.args == ("profile_invalidation_invalid",), arguments
    with pytest.raises(ProfileQualificationConflict) as unknown:
        await store.invalidate_profile("c" * 64, "inv-1", "evaluator_revoked")

    assert unknown.value.args == ("profile_unknown",)
    assert _counts(db_path) == (1, 0, 0)  # zero invalidation rows; the registered profile is untouched
    assert _snapshot(db_path) == before


async def test_sequence_is_store_wide(db_path: Path) -> None:
    store, _profile_, ref_a = await _registered(db_path, clock=_Clock())
    ref_b = await store.register_profile(_profile_model(**{"model.name": "gpt-5"}))

    first = await store.record_evaluation(_evaluation(ref_a))
    invalidation = await store.invalidate_profile(ref_a, "inv-1", "evaluator_revoked")
    second = await store.record_evaluation(_evaluation(ref_b))

    assert ref_a != ref_b
    assert first.seq == 1
    assert invalidation.seq == 2
    assert second.seq == 3  # the second profile's first evaluation continues the one sequence


_DRIFTS: dict[str, dict[str, Any]] = {
    "skill_resource": {"skills.0.resource_digest": "a" * 64},
    "model_version": {"model.version": "2026-10-01"},
    "prompt_revision": {"prompts.0.revision_digest": "a" * 64},
    "tool_schema": {"tools.0.schema_digest": "a" * 64},
    "tool_implementation": {"tools.0.implementation_digest": "a" * 64},
    "policy": {"policy.policy_digest": "a" * 64},
    "suite_dataset": {"evaluation_suite.dataset_digest": "a" * 64},
}


@pytest.mark.parametrize("drift", list(_DRIFTS))
async def test_component_drift_starts_unevaluated_across_restart(db_path: Path, drift: str) -> None:
    clock = _Clock()
    store, _profile_, base_ref = await _registered(db_path, clock=clock)
    await store.record_evaluation(_evaluation(base_ref))
    drifted_ref = await store.register_profile(_profile_model(**_DRIFTS[drift]))

    base = await _status(store, base_ref)
    drifted = await _status(store, drifted_ref)

    assert drifted_ref != base_ref
    assert base.status == "qualified"  # premise: the base profile carries evidence
    assert drifted.status == "unevaluated"  # one changed component, so it inherits none of it
    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        count = raw.execute("SELECT COUNT(*) FROM profile_evaluations WHERE profile_ref = ?", (drifted_ref,))
        assert count.fetchone() == (0,)
    reopened = await _started(db_path, clock=clock)
    assert await reopened.get_qualification(base_ref) == base
    assert await reopened.get_qualification(drifted_ref) == drifted


# --------------------------------------------------------------------------------------
# 17-19. What the database itself refuses, and what the store refuses to read back
# --------------------------------------------------------------------------------------

_UPDATES: dict[str, str] = {  # each changes one STORED non-key column (a generated one is refused by the engine, #31)
    "execution_profiles": "UPDATE execution_profiles SET recorded_at_ms = recorded_at_ms + 1 WHERE profile_ref = ?",
    "profile_evaluations": "UPDATE profile_evaluations SET issued_at_ms = issued_at_ms + 1 WHERE evidence_ref = ?",
    "profile_invalidations": (
        "UPDATE profile_invalidations SET reason_code = 'manual' WHERE profile_ref = ? AND invalidation_id = ?"
    ),
}
# An INSERT OR REPLACE that collides with the stored row on exactly ONE unique key, every other key being fresh:
# without the guard trigger each would silently replace the stored row. ``evaluation_id`` is a generated column and
# cannot be inserted, so ``_violation`` writes a fresh one into the evaluation's canonical text instead.
_REPLACES: dict[str, dict[str, Any]] = {
    "execution_profiles/replace_by_key": {"recorded_at_ms": 2},
    "profile_evaluations/replace_by_key": {"seq": 50, "evaluation_id": "eval-50"},
    "profile_evaluations/replace_through_seq": {"evidence_ref": "e" * 64, "evaluation_id": "eval-51"},
    "profile_evaluations/replace_through_evaluation_id": {"evidence_ref": "f" * 64, "seq": 52},
    "profile_invalidations/replace_by_key": {"seq": 53},
    "profile_invalidations/replace_through_seq": {"invalidation_id": "inv-54"},
}
_IMMUTABILITY_CASES = [
    *(
        pytest.param(table, operation, id=f"{table}-{operation}")
        for table in _TABLES
        for operation in ("update", "delete", "replace_by_key")
    ),
    pytest.param("profile_evaluations", "replace_through_seq", id="profile_evaluations-replace_through_seq"),
    pytest.param(
        "profile_evaluations", "replace_through_evaluation_id", id="profile_evaluations-replace_through_evaluation_id"
    ),
    pytest.param("profile_invalidations", "replace_through_seq", id="profile_invalidations-replace_through_seq"),
]


def _naming(canonical_json: str, evaluation_id: str) -> str:
    """An evaluation's JSON text naming another ``evaluation_id``; the generated column of that name follows it."""
    return json.dumps({**json.loads(canonical_json), "evaluation_id": evaluation_id})


def _violation(table: str, operation: str, stored: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    """One statement that would change, remove or replace ``stored`` (the table's only row), with its parameters."""
    key = tuple(stored[column] for column in _KEYS[table])
    if operation == "update":
        return _UPDATES[table], key
    if operation == "delete":
        return f"DELETE FROM {table} WHERE {' AND '.join(f'{column} = ?' for column in _KEYS[table])}", key
    overrides = _REPLACES[f"{table}/{operation}"]
    colliding = {**stored, **overrides}
    if "evaluation_id" in overrides:  # generated from the canonical text, so a fresh id has to be written there
        colliding["canonical_json"] = _naming(stored["canonical_json"], overrides["evaluation_id"])
    return _insert_sql(table, "INSERT OR REPLACE"), _values(table, colliding)


@pytest.mark.parametrize(("table", "operation"), _IMMUTABILITY_CASES)
async def test_database_refuses_update_delete_and_replace(db_path: Path, table: str, operation: str) -> None:
    await _populated(db_path)
    before = _snapshot(db_path)
    assert len(before[table]) == 1  # premise: the row exists (and is the table's only one)
    sql, params = _violation(table, operation, before[table][0])

    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        with pytest.raises(sqlite3.IntegrityError, match="profile_qualification_immutable"):
            raw.execute(sql, params)
        raw.rollback()

    assert _snapshot(db_path) == before


def _fresh_row(table: str, version: int, marker: str, seq: int) -> dict[str, Any]:
    """A complete row of STORED columns for ``table`` at ``version`` whose key and ``seq`` collide with nothing here.

    The generated columns are not part of it: the canonical text names them (valid JSON naming fresh ids).
    """
    return {
        "execution_profiles": {
            "profile_ref": marker * 64, "schema_version": version, "recorded_at_ms": 1,
            "canonical_json": json.dumps({"role_id": "reviewer", "task_class": "finding_review"}),
        },
        "profile_evaluations": {
            "evidence_ref": marker * 64, "seq": seq, "issued_at_ms": 1, "expires_at_ms": 2,
            "schema_version": version,
            "canonical_json": json.dumps({"profile_ref": "9" * 64, "evaluation_id": f"eval-{marker}"}),
        },
        "profile_invalidations": {
            "profile_ref": "9" * 64, "invalidation_id": f"inv-{marker}", "seq": seq,
            "reason_code": "evaluator_revoked", "invalidated_at_ms": 1, "schema_version": version,
        },
    }[table]


@pytest.mark.parametrize("table", _TABLES)
async def test_schema_version_check_refuses_other_versions(db_path: Path, table: str) -> None:
    await _started(db_path, clock=_Clock())  # creates the schema; no rows
    sql = _insert_sql(table, "INSERT")

    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        # premise: the parent profile does not exist here, and this connection does not enforce parent keys
        assert raw.execute("PRAGMA foreign_keys").fetchone() == (0,)
        # premise: the same INSERT at version 1, with another fresh key, succeeds
        raw.execute(sql, _values(table, _fresh_row(table, 1, "b", 11)))
        raw.commit()

        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            raw.execute(sql, _values(table, _fresh_row(table, 2, "a", 10)))
        raw.rollback()

    rows = _rows(db_path, table)
    assert [row["schema_version"] for row in rows] == [1]  # only the version-1 row was stored


_TAMPERS = (
    "profile_json_reindented",
    "evaluation_passed_flipped",
    "evaluation_expires_shifted",
    "evaluation_seq_text",
    "invalidation_reason_malformed",
    "moved_evaluation",
)


def _tamper_plan(
    case: str, rows: dict[str, list[dict[str, Any]]], moved_to: str,
) -> tuple[str, str, tuple[Any, ...], str]:
    """``(trigger to drop, UPDATE, parameters, read path)`` for one tamper of the one stored profile's rows.

    ``moved_to`` is the reference of a second registered profile, used only by ``moved_evaluation``.
    """
    profile = rows["execution_profiles"][0]
    evaluation = rows["profile_evaluations"][0]
    invalidation = rows["profile_invalidations"][0]
    if case == "profile_json_reindented":
        reindented = json.dumps(json.loads(profile["canonical_json"]), indent=1)
        return (
            "execution_profiles_no_update",
            "UPDATE execution_profiles SET canonical_json = ? WHERE profile_ref = ?",
            (reindented, profile["profile_ref"]),
            "get_profile",
        )
    if case == "moved_evaluation":
        # The evaluation's own canonical text is rewritten to name another profile, and its ``evidence_ref`` is left
        # alone. ``profile_ref`` is generated from that text, so the row now lands under ``moved_to``; the text is
        # canonical, so only its content identity no longer matches the stored key.
        content = json.loads(evaluation["canonical_json"])
        content["profile_ref"] = moved_to
        return (
            "profile_evaluations_no_update",
            "UPDATE profile_evaluations SET canonical_json = ? WHERE evidence_ref = ?",
            (canonicalize_projection(content).decode("utf-8"), evaluation["evidence_ref"]),
            "get_qualification",
        )
    if case == "evaluation_passed_flipped":
        content = json.loads(evaluation["canonical_json"])
        content["observations"][0]["passed"] = not content["observations"][0]["passed"]
        # canonical text of the forged record: only its content identity no longer matches the stored key
        forged = EvaluationRecord.model_validate(content).canonical_bytes().decode()
        return (
            "profile_evaluations_no_update",
            "UPDATE profile_evaluations SET canonical_json = ? WHERE evidence_ref = ?",
            (forged, evaluation["evidence_ref"]),
            "get_qualification",
        )
    if case == "evaluation_expires_shifted":
        return (
            "profile_evaluations_no_update",
            "UPDATE profile_evaluations SET expires_at_ms = expires_at_ms + ? WHERE evidence_ref = ?",
            (10**9, evaluation["evidence_ref"]),
            "get_qualification",
        )
    if case == "evaluation_seq_text":
        return (
            "profile_evaluations_no_update",
            "UPDATE profile_evaluations SET seq = 'x' WHERE evidence_ref = ?",
            (evaluation["evidence_ref"],),
            "get_qualification",
        )
    assert case == "invalidation_reason_malformed"
    return (
        "profile_invalidations_no_update",
        "UPDATE profile_invalidations SET reason_code = 'Bad Reason' WHERE profile_ref = ? AND invalidation_id = ?",
        (invalidation["profile_ref"], invalidation["invalidation_id"]),
        "get_qualification",
    )


@pytest.mark.parametrize("case", _TAMPERS)
async def test_tampered_rows_are_integrity_errors(
    db_path: Path, case: str, caplog: pytest.LogCaptureFixture,
) -> None:
    store, ref = await _populated(db_path)
    read_ref = ref
    if case == "moved_evaluation":  # the evaluation of ``ref`` is rewritten to name a second profile, and read there
        read_ref = await store.register_profile(_profile_model(**{"model.name": "gpt-5"}))
        assert read_ref != ref  # premise: a different profile
    drop_trigger, statement, params, read_name = _tamper_plan(case, _snapshot(db_path), read_ref)
    read = {"get_profile": store.get_profile, "get_qualification": store.get_qualification}[read_name]
    await read(read_ref)  # premise: before the tamper this very read path succeeds

    _tamper(db_path, drop_trigger, statement, params)

    if case == "moved_evaluation":  # premise: the edited row now lands under the second profile, and nowhere else
        with contextlib.closing(sqlite3.connect(db_path)) as raw:
            assert raw.execute("SELECT profile_ref FROM profile_evaluations").fetchall() == [(read_ref,)]
    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        with pytest.raises(ProfileQualificationIntegrityError) as refused:
            await read(read_ref)
    assert refused.value.args == ("profile_qualification_integrity",)
    errors = [record for record in caplog.records if record.name == _LOGGER and record.levelno == logging.ERROR]
    assert len(errors) == 1


# --------------------------------------------------------------------------------------
# 20-22. The clock, a failed write and a cancelled write
# --------------------------------------------------------------------------------------


# (a refused clock, the accepted clock right beside it or None): the boundary control runs once per pair, so each edge
# of the accepted range is pinned from both sides. None: this refused clock sits on no edge. Ints of any size and
# the infinities are compared exactly, so none of them can raise anything but the unavailable error (round 1, A3).
_CLOCK_CASES = [
    pytest.param(float("nan"), None, id="nan"),
    pytest.param(float("inf"), None, id="inf"),
    pytest.param(float("-inf"), None, id="-inf"),
    pytest.param(-1.0, 0.0, id="negative-float"),
    pytest.param(-1, 0, id="negative-int"),
    pytest.param(253402300800, 253402300799, id="above-maximum-int"),
    pytest.param(253402300799.5, 253402300799.0, id="above-maximum-float"),
    pytest.param(10**1000, None, id="huge-int"),
    pytest.param(-(10**1000), None, id="huge-negative-int"),
    pytest.param("1", None, id="text"),
    pytest.param(True, None, id="bool"),
    pytest.param(None, None, id="none"),
]


@pytest.mark.parametrize(("bad_clock", "accepted_beside"), _CLOCK_CASES)
async def test_invalid_clock_refuses_every_call(db_path: Path, bad_clock: Any, accepted_beside: Any) -> None:
    clock = _Clock(1000.0)
    store, _profile_, ref = await _registered(db_path, clock=clock)
    unregistered = _profile_model(**{"model.name": "gpt-5"})
    calls = _data_calls(unregistered, ref, _evaluation(ref))
    before = _snapshot(db_path)
    clock.now = bad_clock

    await _assert_every_call_raises_unavailable(store, calls, "profile_qualification_clock_invalid")

    assert _snapshot(db_path) == before  # unchanged: the registered profile, and no evaluation or invalidation
    clock.now = 1000.0
    for call in calls.values():  # positive control: each call was well formed, so a good clock lets it through
        await call(store)
    assert _counts(db_path) == (2, 1, 1)  # and now they do record: the second profile, one evaluation, one invalidation

    if accepted_beside is not None:  # boundary control: the accepted clock on the other side of this edge works
        edge_store, _edge_profile, edge_ref = await _registered(
            db_path.with_name("boundary.db"), clock=_Clock(accepted_beside),
        )
        await edge_store.record_evaluation(_evaluation(edge_ref))
        edge = await _status(edge_store, edge_ref)
        assert edge.status == "qualified"
        assert edge.deciding is not None
        assert edge.deciding.issued_at_ms == int(accepted_beside * 1000)  # at the maximum, the stamp bound itself


async def test_failed_write_records_nothing(db_path: Path) -> None:
    factory = _ProxyFactory()
    store, _profile_, ref = await _registered(db_path, clock=_Clock(), connection_factory=factory)
    record = _evaluation(ref)
    factory.fail_on = "INSERT INTO profile_evaluations"

    with pytest.raises(RuntimeError, match="injected"):
        await store.record_evaluation(record)

    assert factory.fired == 1  # premise: the failure arrived after the real INSERT ran on the real connection
    assert len(_rows(db_path, "profile_evaluations")) == 0  # its uncommitted row died with the connection
    factory.fail_on = None
    retried = await store.record_evaluation(record)
    assert retried.seq == 1


async def test_cancel_before_commit_records_nothing_and_retry_is_safe(db_path: Path) -> None:
    factory = _ProxyFactory()
    store, _profile_, ref = await _registered(db_path, clock=_Clock(), connection_factory=factory)
    record = _evaluation(ref)
    factory.park_on = "INSERT INTO profile_evaluations"
    commits_before = factory.commits
    task = asyncio.create_task(store.record_evaluation(record))

    await asyncio.wait_for(factory.parked.wait(), 5)
    assert not task.done()  # premise: the call is still in flight, parked after the real INSERT
    assert factory.commits == commits_before  # premise: that call never asked for a COMMIT
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelled()
    assert len(_rows(db_path, "profile_evaluations")) == 0  # the uncommitted row died with the connection
    factory.park_on = None
    retried = await asyncio.wait_for(store.record_evaluation(record), 5)  # the lock is free and the retry is safe
    assert retried.seq == 1


# --------------------------------------------------------------------------------------
# 23-25. Declaration, imports and authority
# --------------------------------------------------------------------------------------


def test_store_is_declared() -> None:
    declaration = load_default_store_registry().get("cognitive.profile-qualifications")

    assert declaration is not None
    assert declaration.owner_symbol == "ProfileQualificationStore"
    assert declaration.canonical_path == "profile_qualifications.db"
    assert declaration.lifecycle_owner == "unowned"
    # the declaration names this very class
    assert (ProfileQualificationStore.__module__, ProfileQualificationStore.__name__) == (
        declaration.owner_module, declaration.owner_symbol,
    )


_ALLOWED_PROBOS_IMPORTS = {
    "probos.cognitive.elastic_team",
    "probos.cognitive.execution_profile",
    "probos.protocols",
    "probos.storage.sqlite_factory",
}


def test_store_module_imports_only_its_owners() -> None:
    source = Path(store_module.__file__).read_text(encoding="utf-8")

    assert _probos_imports(ast.parse(source)) == _ALLOWED_PROBOS_IMPORTS
    # negative controls: the helper sees an import outside the allowlist whatever its form or depth
    assert _probos_imports(ast.parse("import probos.tools.registry")) == {"probos.tools.registry"}
    assert _probos_imports(ast.parse("from probos.tools import registry")) == {"probos.tools"}
    assert _probos_imports(ast.parse("def late():\n    import probos.tools.registry\n")) == {"probos.tools.registry"}
    assert _probos_imports(ast.parse("from . import registry")) == {"."}


def test_store_result_types_carry_no_authority_fields() -> None:
    result_types = (RecordedEvaluation, RecordedInvalidation, ProfileQualification, CandidateQueryResult)
    names = {field.name for result_type in result_types for field in dataclasses.fields(result_type)}

    # the walk reaches every result type (a walk that found nothing would pass vacuously)
    assert {
        "evidence_ref", "seq", "issued_at_ms", "expires_at_ms", "record", "invalidation_id", "reason_code",
        "invalidated_at_ms", "profile", "status", "deciding", "invalidation_reasons", "assessed_at_ms",
        "candidates", "examined", "complete", "next_after",
    } <= names
    assert _authority_named(names) == set()
    # negative control: the same words flag AD-1286's AuthorityCeiling
    assert "tool_scopes" in _authority_named(_all_field_names(AuthorityCeiling))


# --------------------------------------------------------------------------------------
# 26. A store stamp out of type or range is an integrity error (review round 1, A2)
# --------------------------------------------------------------------------------------

_MAX_STAMP_MS = 253_402_300_799_000  # 9999-12-31T23:59:59Z in ms: the largest time the store stamps (D4)
_STAMP_CASES = [
    pytest.param("evaluation_issued_above_maximum", True, id="evaluation-issued-above-maximum"),
    pytest.param("evaluation_issued_negative", True, id="evaluation-issued-negative"),
    pytest.param("evaluation_seq_above_maximum", True, id="evaluation-seq-above-maximum"),
    pytest.param("invalidation_stamp_above_maximum", True, id="invalidation-stamp-above-maximum"),
    pytest.param("profile_recorded_not_a_number", True, id="profile-recorded-not-a-number"),
    pytest.param("profile_recorded_above_maximum", True, id="profile-recorded-above-maximum"),
    pytest.param("evaluation_issued_at_maximum", False, id="premise-control-evaluation-issued-at-maximum"),
]


def _stamp_plan(
    case: str, rows: dict[str, list[dict[str, Any]]],
) -> tuple[str, str, tuple[Any, ...], tuple[str, ...]]:
    """``(trigger to drop, UPDATE, parameters, read paths)`` writing one store stamp into the stored rows.

    An evaluation's ``expires_at_ms`` is recomputed along with its ``issued_at_ms``, so the stamp's range is the only
    thing wrong with the row. The read paths are the ones this test runs, not every path that uses the row: evaluation replay and ``find_slot_candidates`` also use an evaluation and are not asserted here.
    """
    profile = rows["execution_profiles"][0]
    evaluation = rows["profile_evaluations"][0]
    invalidation = rows["profile_invalidations"][0]
    validity_ms = evaluation["expires_at_ms"] - evaluation["issued_at_ms"]
    assert validity_ms == _profile_model().evaluation_suite.validity_seconds * 1_000  # premise: the row is honest
    if case.startswith("evaluation_issued"):
        issued = {
            "evaluation_issued_above_maximum": _MAX_STAMP_MS + 1,
            "evaluation_issued_negative": -1,
            "evaluation_issued_at_maximum": _MAX_STAMP_MS,
        }[case]
        return (
            "profile_evaluations_no_update",
            "UPDATE profile_evaluations SET issued_at_ms = ?, expires_at_ms = ? WHERE evidence_ref = ?",
            (issued, issued + validity_ms, evaluation["evidence_ref"]),
            ("get_qualification",),
        )
    if case == "evaluation_seq_above_maximum":
        return (
            "profile_evaluations_no_update",
            "UPDATE profile_evaluations SET seq = ? WHERE evidence_ref = ?",
            (2**53, evaluation["evidence_ref"]),
            ("get_qualification",),
        )
    if case == "invalidation_stamp_above_maximum":
        return (
            "profile_invalidations_no_update",
            "UPDATE profile_invalidations SET invalidated_at_ms = ? WHERE profile_ref = ? AND invalidation_id = ?",
            (_MAX_STAMP_MS + 1, invalidation["profile_ref"], invalidation["invalidation_id"]),
            ("get_qualification", "replay_invalidation"),  # replaying the identical invalidate_profile reads it too
        )
    assert case in {"profile_recorded_not_a_number", "profile_recorded_above_maximum"}
    return (
        "execution_profiles_no_update",
        "UPDATE execution_profiles SET recorded_at_ms = ? WHERE profile_ref = ?",
        ("not-a-number" if case == "profile_recorded_not_a_number" else _MAX_STAMP_MS + 1, profile["profile_ref"]),
        ("get_profile",),
    )


@pytest.mark.parametrize(("case", "refused"), _STAMP_CASES)
async def test_out_of_range_stamps_are_integrity_errors(
    db_path: Path, case: str, refused: bool, caplog: pytest.LogCaptureFixture,
) -> None:
    store, ref = await _populated(db_path)
    reads: dict[str, Callable[[], Awaitable[Any]]] = {
        "get_profile": lambda: store.get_profile(ref),
        "get_qualification": lambda: store.get_qualification(ref),
        "replay_invalidation": lambda: store.invalidate_profile(ref, "inv-1", "evaluator_revoked"),
    }
    drop_trigger, statement, params, read_names = _stamp_plan(case, _snapshot(db_path))
    for name in read_names:
        await reads[name]()  # premise: before the rewrite every read path of this case succeeds

    _tamper(db_path, drop_trigger, statement, params)

    if not refused:  # premise control: the bound itself is in range, so the same rewrite is read back, not refused
        qualification = await store.get_qualification(ref)
        assert qualification is not None
        assert qualification.deciding is not None
        assert qualification.deciding.issued_at_ms == _MAX_STAMP_MS
        return
    for name in read_names:
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger=_LOGGER):
            with pytest.raises(ProfileQualificationIntegrityError) as raised:
                await reads[name]()
        assert raised.value.args == ("profile_qualification_integrity",), name
        errors = [record for record in caplog.records if record.name == _LOGGER and record.levelno == logging.ERROR]
        assert len(errors) == 1, name


# --------------------------------------------------------------------------------------
# 27-29. WITHOUT ROWID is what stops a rowid replacement (review round 1, A4)
# --------------------------------------------------------------------------------------


def _refusal_message(statement: str) -> str:
    """What a refused statement raises: the trigger's code, or SQLite's own refusal of a ``rowid`` column."""
    return "rowid" if "(rowid," in statement else "profile_qualification_immutable"


def _rowid_replace(table: str) -> str:
    """``INSERT OR REPLACE`` naming ``rowid`` 1 (the first stored row) and every STORED column of ``table``.

    Built with ``_fresh_row``'s values, whose key, ``seq`` and evaluation id collide with NOTHING stored: on a rowid
    table this would silently replace the first row, and no guard trigger or unique key could be what refuses it.
    """
    columns = _COLUMNS[table]
    return f"INSERT OR REPLACE INTO {table} (rowid, {', '.join(columns)}) VALUES (1, {', '.join('?' for _ in columns)})"


@pytest.mark.parametrize(
    "table",
    [
        pytest.param("execution_profiles", id="rowid-replace-profiles"),
        pytest.param("profile_evaluations", id="rowid-replace-evaluations"),
        pytest.param("profile_invalidations", id="rowid-replace-invalidations"),
    ],
)
async def test_rowid_replacement_is_refused_on_every_table(db_path: Path, table: str) -> None:
    await _populated(db_path)
    before = _snapshot(db_path)
    assert all(before.values())  # premise: every table holds a row, so "unchanged" is not vacuous
    statement = _rowid_replace(table)
    params = _values(table, _fresh_row(table, 1, "a", 40))

    with contextlib.closing(sqlite3.connect(db_path)) as raw:  # DEFAULT pragmas: no foreign keys, no recursive triggers
        assert raw.execute("PRAGMA foreign_keys").fetchone() == (0,)
        assert raw.execute("PRAGMA recursive_triggers").fetchone() == (0,)
        # premise: the same values without the rowid are accepted, so nothing of theirs collides with a stored row
        raw.execute(_insert_sql(table, "INSERT"), params)
        raw.rollback()

        with pytest.raises(sqlite3.DatabaseError, match=_refusal_message(statement)):
            raw.execute(statement, params)
        raw.rollback()

    assert _snapshot(db_path) == before


async def test_every_table_is_without_rowid(db_path: Path) -> None:
    """With no implicit rowid there is no hidden mutable key a REPLACE could match instead of the guards' keys."""
    await _populated(db_path)
    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        definitions = dict(raw.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'"))

    assert set(definitions) == set(_TABLES)
    for table, definition in definitions.items():
        assert definition.rstrip().upper().endswith("WITHOUT ROWID"), table


async def test_raw_genuinely_new_rows_are_accepted(db_path: Path) -> None:
    """Negative control for #17 and #27: the guards refuse a stored row's key, not every raw write.

    On the same kind of raw default-pragma connection, a plain INSERT of one fresh row per table (a fresh key, a fresh
    ``seq`` and valid JSON naming fresh ids) is stored.
    """
    await _populated(db_path)
    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        before = {table: raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _TABLES}
        assert before == dict.fromkeys(_TABLES, 1)  # premise: one row per table, as #27 and #17 assume
        for table in _TABLES:
            raw.execute(_insert_sql(table, "INSERT"), _values(table, _fresh_row(table, 1, "a", 40)))
        raw.commit()
        after = {table: raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _TABLES}

    assert after == {table: before[table] + 1 for table in _TABLES}


# --------------------------------------------------------------------------------------
# 30. The next sequence number costs the same however many rows are stored (review round 1, A5)
# --------------------------------------------------------------------------------------

_SCAN_SQL = (  # the round-0 query, kept to show that the measurement tells a scan from an index read
    "SELECT MAX(seq) FROM (SELECT seq FROM profile_evaluations UNION ALL SELECT seq FROM profile_invalidations)"
)


def _vm_steps(raw: sqlite3.Connection, sql: str) -> tuple[int, Any]:
    """``(virtual-machine steps, the single value)`` of running ``sql`` once. A count, so no clock is involved."""
    steps = 0

    def tick() -> int:
        nonlocal steps
        steps += 1
        return 0  # carry on

    raw.set_progress_handler(tick, 1)
    try:
        rows = raw.execute(sql).fetchall()
    finally:
        raw.set_progress_handler(None, 0)
    return steps, rows[0][0]


def _insert_numbered_rows(raw: sqlite3.Connection, first: int, last: int) -> None:
    """Raw-insert evaluation and invalidation number ``first``..``last``; the two tables interleave their ``seq``."""
    raw.executemany(
        _insert_sql("profile_evaluations", "INSERT"),
        [
            (
                f"{number:064x}", 2 * number - 1, 1, 2, 1,
                json.dumps({"profile_ref": "9" * 64, "evaluation_id": f"eval-{number}"}),
            )
            for number in range(first, last + 1)
        ],
    )
    raw.executemany(
        _insert_sql("profile_invalidations", "INSERT"),
        [("9" * 64, f"inv-{number}", 2 * number, "evaluator_revoked", 1, 1) for number in range(first, last + 1)],
    )
    raw.commit()


async def test_next_seq_work_does_not_grow_with_rows(db_path: Path) -> None:
    await _started(db_path, clock=_Clock())  # creates the schema; no rows
    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        assert raw.execute("PRAGMA foreign_keys").fetchone() == (0,)  # raw inserts need no parent profile
        scan: dict[int, tuple[int, Any]] = {}
        shipped: dict[int, tuple[int, Any]] = {}
        stored = 0
        for size in (10, 1000):
            _insert_numbered_rows(raw, stored + 1, size)
            stored = size
            scan[size] = _vm_steps(raw, _SCAN_SQL)
            shipped[size] = _vm_steps(raw, store_module._NEXT_SEQ_SQL)

    # premise: the round-0 scan grows with the rows, so this measurement can tell a scan from an index read
    assert scan[1000][0] > 10 * scan[10][0]
    # the shipped query does the same work at 1000 rows per table as at 10 (two steps of slack, no more)
    assert shipped[1000][0] <= shipped[10][0] + 2
    # and both queries return the same maximum, at both sizes
    assert shipped[10][1] == scan[10][1] == 2 * 10
    assert shipped[1000][1] == scan[1000][1] == 2 * 1000


# --------------------------------------------------------------------------------------
# 31. The selection columns are generated from the canonical text (review round 1, A1)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "column"),
    [
        pytest.param("execution_profiles", "role_id", id="profiles-role_id"),
        pytest.param("execution_profiles", "task_class", id="profiles-task_class"),
        pytest.param("profile_evaluations", "profile_ref", id="evaluations-profile_ref"),
        pytest.param("profile_evaluations", "evaluation_id", id="evaluations-evaluation_id"),
    ],
)
async def test_selection_columns_are_generated_and_refuse_writes(db_path: Path, table: str, column: str) -> None:
    store, ref = await _populated(db_path)
    rows_before = _snapshot(db_path)
    profile_before = await store.get_profile(ref)
    qualification_before = await store.get_qualification(ref)
    assert profile_before is not None  # premise: both read paths see the data
    assert qualification_before is not None

    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        hidden = {row[1]: row[6] for row in raw.execute(f"PRAGMA table_xinfo({table})")}
        assert hidden["canonical_json"] == 0  # premise: an ordinary stored column reads 0 here...
        assert hidden[column] == 2  # ...and the selection column is a VIRTUAL generated one
        for suffix in ("no_update", "no_delete", "no_replace"):  # with every trigger gone, only the engine can refuse
            raw.execute(f"DROP TRIGGER {table}_{suffix}")
        raw.commit()
        with pytest.raises(sqlite3.OperationalError, match="generated column"):
            raw.execute(f"UPDATE {table} SET {column} = 'x'")
        raw.rollback()

    assert _snapshot(db_path) == rows_before  # the A1 reproduction (a column edit that moves a row) cannot be set up
    assert await store.get_profile(ref) == profile_before
    assert await store.get_qualification(ref) == qualification_before


# --------------------------------------------------------------------------------------
# 32. The clock is read once per data call that gets that far (review round 1, B3)
# --------------------------------------------------------------------------------------


async def test_clock_is_read_once_per_data_call_and_never_otherwise(db_path: Path) -> None:
    clock = _Clock()
    baseline = clock.reads
    clock()
    assert clock.reads == baseline + 1  # premise: the counter counts

    store = ProfileQualificationStore(str(db_path), clock=clock)
    profile = _profile_model()
    ref = profile.content_ref()
    valid = _data_calls(profile, ref, _evaluation(ref))  # in order, so each can rely on the one before it
    malformed: dict[str, tuple[_DataCall, type[Exception], str]] = {
        "register_profile": (lambda s: s.register_profile({}), TypeError, "execution_profile_type_invalid"),
        "get_profile": (lambda s: s.get_profile("x"), ValueError, "execution_profile_ref_invalid"),
        "record_evaluation": (lambda s: s.record_evaluation({}), TypeError, "profile_evaluation_type_invalid"),
        "invalidate_profile": (
            lambda s: s.invalidate_profile(ref, "bad id", "evaluator_revoked"), ValueError,
            "profile_invalidation_invalid",
        ),
        "get_qualification": (lambda s: s.get_qualification("x"), ValueError, "execution_profile_ref_invalid"),
        "find_slot_candidates": (lambda s: s.find_slot_candidates({}), TypeError, "profile_slot_type_invalid"),
    }
    assert list(malformed) == list(valid)  # premise: one malformed call per data method
    reads: dict[str, int] = {}

    async def refused(label: str, call: _DataCall, error: type[Exception], code: str) -> None:
        before = clock.reads
        with pytest.raises(error) as raised:
            await call(store)
        reads[label] = clock.reads - before
        assert raised.value.args == (code,), label

    async def served(label: str, call: _DataCall) -> None:
        before = clock.reads
        await call(store)
        reads[label] = clock.reads - before

    unavailable = "profile_qualification_store_unavailable"
    for name, call in valid.items():
        await refused(f"unstarted {name}", call, ProfileQualificationStoreUnavailable, unavailable)
    before = clock.reads
    await store.start()
    reads["start"] = clock.reads - before
    for name, (call, error, code) in malformed.items():
        await refused(f"malformed {name}", call, error, code)
    for name, call in valid.items():
        await served(f"started {name}", call)
    before = clock.reads
    await store.stop()
    reads["stop"] = clock.reads - before
    for name, call in valid.items():
        await refused(f"stopped {name}", call, ProfileQualificationStoreUnavailable, unavailable)

    names = list(valid)
    assert reads == {
        **{f"unstarted {name}": 0 for name in names},
        "start": 0,
        **{f"malformed {name}": 0 for name in names},
        **{f"started {name}": 1 for name in names},
        "stop": 0,
        **{f"stopped {name}": 0 for name in names},
    }

    # R2 (C3b): a call refused because the clock returned an invalid time has still read the clock, exactly once
    clock.now = float("nan")
    await store.start()
    invalid_clock_reads: dict[str, int] = {}
    for name, call in valid.items():
        before = clock.reads
        with pytest.raises(ProfileQualificationStoreUnavailable) as invalid:
            await call(store)
        invalid_clock_reads[name] = clock.reads - before
        assert invalid.value.args == ("profile_qualification_clock_invalid",), name
    await store.stop()
    assert invalid_clock_reads == {name: 1 for name in names}


# --------------------------------------------------------------------------------------
# 33. A failed close (D9: log-and-degrade)
# --------------------------------------------------------------------------------------


async def test_close_failure_is_logged_and_the_operation_result_stands(
    db_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    factory = _ProxyFactory()
    store = await _started(db_path, clock=_Clock(), connection_factory=factory)
    profile = _profile_model()
    ref = profile.content_ref()
    factory.fail_close = True  # from here on every connection is really closed, THEN its close() raises

    # (a) the operation's own result stands: the profile was committed before the close failed
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        registered = await store.register_profile(profile)
    assert factory.close_fired == 1  # premise: the injected close failure fired during that call
    assert registered == ref
    assert _counts(db_path) == (1, 0, 0)
    # (b) and the failed close was logged once, at warning, with the exception it raised
    warnings = [record for record in caplog.records if record.name == _LOGGER and record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "closing a profile qualification connection failed" in warnings[0].getMessage()
    assert warnings[0].exc_info is not None
    assert str(warnings[0].exc_info[1]) == "injected close failure"
    recorded = await store.record_evaluation(_evaluation(ref))  # a write's result stands the same way
    assert (factory.close_fired, recorded.seq) == (2, 1)
    assert _counts(db_path) == (1, 1, 0)

    # (c) an operation that itself fails keeps its own error: the close failure does not replace it
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        with pytest.raises(ProfileQualificationConflict) as refused:
            await store.record_evaluation(_evaluation(ref, passes=2))  # same evaluation_id, other observations
    assert factory.close_fired == 3  # premise: the close failure fired on this call too
    assert type(refused.value) is ProfileQualificationConflict
    assert refused.value.args == ("profile_evaluation_conflict",)
    assert len([r for r in caplog.records if r.name == _LOGGER and r.levelno == logging.WARNING]) == 1
    assert _counts(db_path) == (1, 1, 0)  # the refused write recorded nothing

    # (d) disarmed, the store carries on: the next sequence number is 2, and a healthy close logs nothing
    factory.fail_close = False
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        later = await store.record_evaluation(_evaluation(ref, "eval-2"))
    assert later.seq == 2
    assert factory.close_fired == 3  # no further injected failure
    assert [r for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.WARNING] == []
    assert _counts(db_path) == (1, 2, 0)


# --------------------------------------------------------------------------------------
# 34-37. Review round 2 (C1: the layout check, C2: the sequence bound, C4: foreign keys on every connection)
# --------------------------------------------------------------------------------------

# The layout the store created before review round 1: the round-1 ``_SCHEMA`` text, verbatim, with four lines
# changed so that the two selection columns of ``execution_profiles`` and the two of ``profile_evaluations`` are
# stored ``NOT NULL`` columns again (not ``GENERATED ... VIRTUAL``). It is a literal on purpose: it must not import
# or derive from the module (#34).
_OLD_LAYOUT_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_profiles (
    profile_ref TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1), -- execution_profiles
    canonical_json TEXT NOT NULL,
    recorded_at_ms INTEGER NOT NULL,
    role_id TEXT NOT NULL,
    task_class TEXT NOT NULL
) WITHOUT ROWID; -- end execution_profiles
CREATE INDEX IF NOT EXISTS execution_profiles_by_slot ON execution_profiles (role_id, task_class, profile_ref);
CREATE TABLE IF NOT EXISTS profile_evaluations (
    evidence_ref TEXT PRIMARY KEY,
    seq INTEGER NOT NULL UNIQUE,
    issued_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1), -- profile_evaluations
    canonical_json TEXT NOT NULL,
    profile_ref TEXT NOT NULL
        REFERENCES execution_profiles (profile_ref),
    evaluation_id TEXT NOT NULL,
    UNIQUE (profile_ref, evaluation_id)
) WITHOUT ROWID; -- end profile_evaluations
CREATE INDEX IF NOT EXISTS profile_evaluations_latest ON profile_evaluations (profile_ref, seq);
CREATE TABLE IF NOT EXISTS profile_invalidations (
    profile_ref TEXT NOT NULL REFERENCES execution_profiles (profile_ref),
    invalidation_id TEXT NOT NULL,
    seq INTEGER NOT NULL UNIQUE,
    reason_code TEXT NOT NULL,
    invalidated_at_ms INTEGER NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1), -- profile_invalidations
    PRIMARY KEY (profile_ref, invalidation_id)
) WITHOUT ROWID; -- end profile_invalidations
CREATE INDEX IF NOT EXISTS profile_invalidations_latest ON profile_invalidations (profile_ref, seq);
CREATE TRIGGER IF NOT EXISTS execution_profiles_no_update BEFORE UPDATE ON execution_profiles
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END;
CREATE TRIGGER IF NOT EXISTS execution_profiles_no_delete BEFORE DELETE ON execution_profiles
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END;
CREATE TRIGGER IF NOT EXISTS execution_profiles_no_replace BEFORE INSERT ON execution_profiles
WHEN EXISTS (SELECT 1 FROM execution_profiles WHERE profile_ref = NEW.profile_ref)
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END;
CREATE TRIGGER IF NOT EXISTS profile_evaluations_no_update BEFORE UPDATE ON profile_evaluations
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END;
CREATE TRIGGER IF NOT EXISTS profile_evaluations_no_delete BEFORE DELETE ON profile_evaluations
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END;
CREATE TRIGGER IF NOT EXISTS profile_evaluations_no_replace BEFORE INSERT ON profile_evaluations
WHEN EXISTS (SELECT 1 FROM profile_evaluations WHERE evidence_ref = NEW.evidence_ref OR seq = NEW.seq
             OR (profile_ref = json_extract(NEW.canonical_json, '$.profile_ref')
                 AND evaluation_id = json_extract(NEW.canonical_json, '$.evaluation_id')))
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END;
CREATE TRIGGER IF NOT EXISTS profile_invalidations_no_update BEFORE UPDATE ON profile_invalidations
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END;
CREATE TRIGGER IF NOT EXISTS profile_invalidations_no_delete BEFORE DELETE ON profile_invalidations
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END;
CREATE TRIGGER IF NOT EXISTS profile_invalidations_no_replace BEFORE INSERT ON profile_invalidations
WHEN EXISTS (SELECT 1 FROM profile_invalidations WHERE seq = NEW.seq
             OR (profile_ref = NEW.profile_ref AND invalidation_id = NEW.invalidation_id))
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END;
"""


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _journal_mode(path: Path) -> str:
    """The journal mode a fresh raw connection reads from the file (``wal`` is stored in it; ``delete`` is the default)."""
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return str(raw.execute("PRAGMA journal_mode").fetchone()[0])


def _hidden(path: Path, table: str) -> dict[str, int]:
    """``PRAGMA table_xinfo`` hidden flag per column: 0 a stored column, 2 a VIRTUAL generated one."""
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return {row[1]: row[6] for row in raw.execute(f"PRAGMA table_xinfo({table})")}


def _catalog(path: Path) -> list[tuple[Any, ...]]:
    """Every ``sqlite_master`` row as ``(type, name, tbl_name, sql)``, SQLite's own ``sqlite_autoindex_*`` ones included."""
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return raw.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall()


def _run_script(path: Path, statements: Sequence[str]) -> None:
    """Run ``statements`` in ONE transaction on ``path`` with raw ``sqlite3``: no store, the file's own journal mode."""
    raw = sqlite3.connect(path, isolation_level=None)  # autocommit, so the only transaction is the explicit one
    try:
        raw.execute("BEGIN")
        for statement in statements:
            raw.execute(statement)
        raw.execute("COMMIT")
    finally:
        raw.close()  # an error before COMMIT leaves that transaction open, and closing the connection discards it


# --------------------------------------------------------------------------------------
# 34. A file holding another layout is refused, and left exactly as it was (review round 2, C1)
# --------------------------------------------------------------------------------------


async def test_start_refuses_the_pre_round_1_layout_and_leaves_the_file_unmodified(
    db_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    profile = _profile_model()
    ref = profile.content_ref()
    with contextlib.closing(sqlite3.connect(db_path)) as raw:  # the old layout, with one profile stored in it
        raw.executescript(_OLD_LAYOUT_SCHEMA)
        raw.execute(
            "INSERT INTO execution_profiles (profile_ref, schema_version, canonical_json, recorded_at_ms, role_id, "
            "task_class) VALUES (?, ?, ?, ?, ?, ?)",
            (ref, 1, profile.canonical_bytes().decode(), 1_000_000, profile.role_id, profile.task_class),
        )
        raw.commit()
    assert _hidden(db_path, "execution_profiles")["role_id"] == 0  # premise: a stored column, not a generated one
    assert _journal_mode(db_path) == "delete"  # premise: rollback mode, which a start that wrote would change
    sha_before = _file_sha256(db_path)
    files_before = sorted(entry.name for entry in db_path.parent.iterdir())
    store = ProfileQualificationStore(str(db_path), clock=_Clock())

    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        with pytest.raises(ProfileQualificationStoreUnavailable) as refused:
            await store.start()
    assert refused.value.args == ("profile_qualification_layout_mismatch",)
    errors = [r for r in caplog.records if r.name == _LOGGER and r.levelno == logging.ERROR]
    assert len(errors) == 1
    named = errors[0].getMessage().replace(str(db_path), "<db>")  # the message also names the file's path
    assert "execution_profiles" in named and "profile_evaluations" in named  # a subset: no trigger name is asserted
    await _assert_every_call_raises_unavailable(
        store, _data_calls(profile, ref, _evaluation(ref)), "profile_qualification_store_unavailable",
    )
    with pytest.raises(ProfileQualificationStoreUnavailable) as again:
        await store.start()  # the store stayed stopped, and refuses again for the same reason
    assert again.value.args == ("profile_qualification_layout_mismatch",)

    assert _file_sha256(db_path) == sha_before  # not one byte of the file changed
    assert _journal_mode(db_path) == "delete"  # in particular, WAL was not set on it
    assert not (db_path.parent / f"{db_path.name}-wal").exists()
    assert sorted(entry.name for entry in db_path.parent.iterdir()) == files_before  # and no sibling file appeared


# --------------------------------------------------------------------------------------
# 35. Only a file holding no schema, or exactly this module's layout, starts (review round 2, C1)
# --------------------------------------------------------------------------------------


def _module_statement(prefix: str) -> str:
    """The one statement of the module's layout that begins with ``prefix`` (a premise: there is exactly one)."""
    found = [statement for statement in store_module._SCHEMA_STATEMENTS if statement.startswith(prefix)]
    assert len(found) == 1, prefix
    return found[0]


def _raw_edit(case: str) -> tuple[tuple[str, ...], str]:
    """What a file-level writer runs against a layout the store created, and the one object that it changes."""
    if case == "missing_trigger":
        return ("DROP TRIGGER profile_evaluations_no_update",), "profile_evaluations_no_update"
    if case == "extra_trigger":
        extra = "CREATE TRIGGER profile_extra AFTER INSERT ON profile_invalidations BEGIN SELECT 1; END"
        return (extra,), "profile_extra"
    if case == "extra_table":
        return ("CREATE TABLE unrelated (x)",), "unrelated"
    if case == "extra_index":
        return ("CREATE INDEX profile_extra_index ON profile_invalidations (reason_code)",), "profile_extra_index"
    if case == "weakened_trigger":
        original = _module_statement("CREATE TRIGGER profile_evaluations_no_replace ")
        assert original.count(" OR seq = NEW.seq") == 1  # premise: the clause that is left out is there once
        weakened = original.replace(" OR seq = NEW.seq", "")
        return ("DROP TRIGGER profile_evaluations_no_replace", weakened), "profile_evaluations_no_replace"
    assert case == "changed_index", case
    narrower = "CREATE INDEX profile_evaluations_latest ON profile_evaluations (profile_ref)"
    return ("DROP INDEX profile_evaluations_latest", narrower), "profile_evaluations_latest"


@pytest.mark.parametrize(
    "case",
    [
        "fresh", "module_statements_rollback",
        "missing_trigger", "extra_trigger", "extra_table", "extra_index", "weakened_trigger", "changed_index",
        "generated_expression",
    ],
)
async def test_start_accepts_only_this_layout(db_path: Path, caplog: pytest.LogCaptureFixture, case: str) -> None:
    profile = _profile_model()
    ref = profile.content_ref()
    statements = tuple(store_module._SCHEMA_STATEMENTS)

    if case == "fresh":  # accepted: no file at all
        assert not db_path.exists()  # premise: there is no pre-existing file for the start to accept
        store = await _started(db_path)
        objects = _catalog(db_path)
        ours = sorted(kind for kind, name, _table, _sql in objects if not name.startswith("sqlite_"))
        assert ours == ["index"] * 3 + ["table"] * 3 + ["trigger"] * 9  # premise: the fifteen objects of this layout
        assert any(name.startswith("sqlite_autoindex_") for _kind, name, _table, _sql in objects)  # and SQLite's own
        assert await store.get_profile(ref) is None  # started: a data call is served, not refused
        await store.stop()
        second = await _started(db_path)  # a NEW instance accepts the file that the first one created
        assert await second.get_profile(ref) is None
        return
    if case == "module_statements_rollback":  # accepted: the module's own statements, run raw, in rollback mode
        _run_script(db_path, statements)
        assert _journal_mode(db_path) == "delete"  # premise: rollback mode before the start
        store = await _started(db_path)
        assert await store.get_profile(ref) is None
        assert _journal_mode(db_path) == "wal"  # an accepted start writes: what #34's unchanged file is measured against
        return

    if case == "generated_expression":  # refused: a NEW file, built raw, whose only difference is an expression
        profiles = _module_statement("CREATE TABLE execution_profiles ")
        assert profiles.count("'$.role_id'") == 1  # premise: the expression that is changed is there once
        edited = tuple(
            statement.replace("'$.role_id'", "'$.task_class'") if statement is profiles else statement
            for statement in statements
        )
        _run_script(db_path, edited)
        assert _hidden(db_path, "execution_profiles")["role_id"] == 2  # premise: still VIRTUAL generated
        named = "execution_profiles"
    else:  # refused: a file the store created, then edited raw
        store, _ref = await _populated(db_path)
        await store.stop()
        edit, named = _raw_edit(case)
        catalog_created = _catalog(db_path)
        _run_script(db_path, edit)
        assert _catalog(db_path) != catalog_created  # premise: the edit changed the layout

    catalog_before, counts_before = _catalog(db_path), _counts(db_path)
    refusing = ProfileQualificationStore(str(db_path), clock=_Clock())
    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        with pytest.raises(ProfileQualificationStoreUnavailable) as refused:
            await refusing.start()
    assert refused.value.args == ("profile_qualification_layout_mismatch",)
    errors = [r for r in caplog.records if r.name == _LOGGER and r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert named in errors[0].getMessage().replace(str(db_path), "<db>")  # the message also names the file's path
    assert (_catalog(db_path), _counts(db_path)) == (catalog_before, counts_before)  # the file was left as it was
    with pytest.raises(ProfileQualificationStoreUnavailable) as unavailable:
        await refusing.get_profile(ref)
    assert unavailable.value.args == ("profile_qualification_store_unavailable",)


# --------------------------------------------------------------------------------------
# 36. A write needing a sequence above the bound is refused before anything is written (review round 2, C2)
# --------------------------------------------------------------------------------------

_MAX_SEQ = 2**53 - 1  # the largest sequence number the store may draw (D4): the test's own literal, not the module's


@pytest.mark.parametrize("writer", ["record_evaluation", "invalidate_profile"])
async def test_sequence_bound_is_refused_before_any_write(db_path: Path, writer: str) -> None:
    assert _MAX_SEQ - 1 == 2**53 - 2  # premise: the raw row below takes the number just under the bound
    store, _profile_, ref = await _registered(db_path, clock=_Clock())
    raw_invalidation = {
        "profile_ref": ref, "invalidation_id": "inv-0", "seq": _MAX_SEQ - 1, "reason_code": "evaluator_revoked",
        "invalidated_at_ms": 1_000_000, "schema_version": 1,
    }
    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        raw.execute(
            _insert_sql("profile_invalidations", "INSERT"), _values("profile_invalidations", raw_invalidation),
        )
        raw.commit()
    writers: dict[str, Callable[[int], Awaitable[Any]]] = {
        "record_evaluation": lambda n: store.record_evaluation(_evaluation(ref, f"eval-{n}")),
        "invalidate_profile": lambda n: store.invalidate_profile(ref, f"inv-{n}", "evaluator_revoked"),
    }
    other = next(name for name in writers if name != writer)

    first = await writers[writer](1)  # the last number under the bound is still handed out
    assert first.seq == _MAX_SEQ
    snapshot = _snapshot(db_path)
    for name, number in ((writer, 2), (other, 3)):  # either writer, each with an id that has not been used
        with pytest.raises(ProfileQualificationConflict) as exhausted:
            await writers[name](number)
        assert exhausted.value.args == ("profile_sequence_exhausted",), name
    assert _snapshot(db_path) == snapshot  # neither refusal wrote anything
    assert await writers[writer](1) == first  # the identical replay allocates nothing and returns the stored row
    assert isinstance(await store.get_qualification(ref), ProfileQualification)  # every row is still readable


# --------------------------------------------------------------------------------------
# 37. Foreign keys are on before the first statement of every connection (review round 2, C4)
# --------------------------------------------------------------------------------------


async def test_foreign_keys_are_on_before_the_first_statement_of_every_connection(db_path: Path) -> None:
    factory = _ProxyFactory()
    settings: list[int] = []  # what each connection read from PRAGMA foreign_keys just before its first statement
    factory.foreign_keys = settings
    store = ProfileQualificationStore(str(db_path), clock=_Clock(), connection_factory=factory)
    profile = _profile_model()
    ref = profile.content_ref()
    record = _evaluation(ref)
    seen: dict[str, list[int]] = {}

    await store.start()  # a new file
    seen["start (new file)"] = list(settings)
    await store.register_profile(profile)  # populate: a profile, an evaluation of it and an invalidation after it
    await store.record_evaluation(record)
    await store.invalidate_profile(ref, "inv-1", "evaluator_revoked")
    await store.stop()
    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        assert raw.execute("PRAGMA foreign_keys").fetchone()[0] == 0  # premise: a connection that sets nothing has it off

    settings.clear()
    await store.start()  # the populated file
    seen["start"] = list(settings)
    for name, call in _data_calls(profile, ref, record).items():
        settings.clear()
        await call(store)
        seen[name] = list(settings)

    assert len(seen) == 8  # premise: start on a new file, start on a populated one and the six data methods
    for label, entries in seen.items():
        assert entries, label  # the proxy saw a connection of this call
        assert set(entries) == {1}, label  # and each one had foreign keys on before its first statement


# --------------------------------------------------------------------------------------
# 38. The store's tables are visible to the store-registry detector (R2b)
# --------------------------------------------------------------------------------------


def test_store_tables_are_visible_to_the_store_registry_detector(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Path(__file__).resolve().parent.parent / "scripts" / "check_store_registry.py"
    spec = importlib.util.spec_from_file_location("check_store_registry", script)
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    # Registered before exec_module, because the checker defines dataclasses that re-read sys.modules under PEP 563,
    # and put back at teardown, so loading it here neither replaces nor leaks the copy test_ad1256_store_registry holds.
    monkeypatch.setitem(sys.modules, "check_store_registry", checker)
    spec.loader.exec_module(checker)
    _T = (
        "CREATE TABLE execution_profiles (x)",
        "CREATE TABLE profile_evaluations (x)",
        "CREATE TABLE profile_invalidations (x)",
    )
    tables = ("execution_profiles", "profile_evaluations", "profile_invalidations")

    # Premise (the negative control), asserted first so the assertion on the module cannot pass vacuously: the
    # detector reads a named constant bound to a CREATE TABLE string and a CREATE TABLE text passed to execute (a
    # literal, or an f-string with dynamic parts); it does not follow a tuple element run through a loop variable.
    # The same three statements as the elements of one tuple, run through a loop variable, are invisible to
    # it (the shape round 2 shipped); bound to their own names they are seen.
    in_one_tuple = "S = (\n" + "".join(f"    {t!r},\n" for t in _T) + ")\nfor s in S:\n    db.execute(s)\n"
    each_named = "".join(f"_T{i} = {t!r}\n" for i, t in enumerate(_T))
    assert checker.detect_tables(in_one_tuple) == ()
    assert checker.detect_tables(each_named) == tables

    assert checker.detect_tables(Path(store_module.__file__).read_text(encoding="utf-8")) == tables


# --------------------------------------------------------------------------------------
# 39. A start that fails while creating leaves no layout (review round 3, D2.1)
# --------------------------------------------------------------------------------------

_FIFTEEN = ["index"] * 3 + ["table"] * 3 + ["trigger"] * 9  # the kinds of the fifteen objects of this layout (#35)


def _own_kinds(path: Path) -> list[str]:
    """The kind of every object in the file's catalog that is not SQLite's own (``sqlite_*``), sorted."""
    return sorted(kind for kind, name, _table, _sql in _catalog(path) if not name.startswith("sqlite_"))


async def test_a_start_failing_while_creating_leaves_no_layout_and_a_later_start_creates_it(db_path: Path) -> None:
    prefix = "CREATE TRIGGER execution_profiles_no_delete "
    creating = [i for i, statement in enumerate(store_module._SCHEMA_STATEMENTS) if statement.startswith(prefix)]
    assert creating == [7]  # premise: exactly one statement begins so, and seven objects are created before it
    factory = _ProxyFactory()
    factory.fail_on = prefix  # that statement runs, THEN RuntimeError("injected") is raised inside the transaction
    store = ProfileQualificationStore(str(db_path), clock=_Clock(), connection_factory=factory)
    ref = _profile_model().content_ref()

    with pytest.raises(RuntimeError, match="injected"):
        await store.start()
    assert factory.fired == 1  # the injected failure is what ended the start
    with pytest.raises(ProfileQualificationStoreUnavailable) as stopped:
        await store.get_profile(ref)
    assert stopped.value.args == ("profile_qualification_store_unavailable",)  # the failed start left it stopped
    assert _own_kinds(db_path) == []  # seven objects had been created when it failed; none of them was kept

    factory.fail_on = None
    await store.start()  # a later start, on the same instance
    assert await store.get_profile(ref) is None  # started: a data call is served
    assert _own_kinds(db_path) == _FIFTEEN  # and the whole layout is there


# --------------------------------------------------------------------------------------
# 40. An invalid stored maximum sequence is an integrity error (review round 3, D2.3)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("writer", ["record_evaluation", "invalidate_profile"])
async def test_an_invalid_stored_maximum_sequence_is_an_integrity_error(
    db_path: Path, caplog: pytest.LogCaptureFixture, writer: str,
) -> None:
    store, _profile_, ref = await _registered(db_path, clock=_Clock())
    raw_invalidation = {  # otherwise valid; its sequence number, 0, is below the store's range of 1 to 2**53 - 1
        "profile_ref": ref, "invalidation_id": "inv-0", "seq": 0, "reason_code": "evaluator_revoked",
        "invalidated_at_ms": 1_000_000, "schema_version": 1,
    }
    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        raw.execute(
            _insert_sql("profile_invalidations", "INSERT"), _values("profile_invalidations", raw_invalidation),
        )
        raw.commit()
        highest = raw.execute(
            "SELECT MAX(seq) FROM (SELECT seq FROM profile_evaluations UNION ALL "
            "SELECT seq FROM profile_invalidations)"
        ).fetchone()[0]
    assert highest == 0  # premise: the highest sequence stored in either table is the invalid one
    writers: dict[str, Callable[[], Awaitable[Any]]] = {
        "record_evaluation": lambda: store.record_evaluation(_evaluation(ref, "eval-1")),
        "invalidate_profile": lambda: store.invalidate_profile(ref, "inv-1", "evaluator_revoked"),
    }
    snapshot = _snapshot(db_path)

    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        with pytest.raises(ProfileQualificationIntegrityError) as refused:
            await writers[writer]()  # a new id, so the write is no replay: it must draw the next sequence number

    assert refused.value.args == ("profile_qualification_integrity",)
    errors = [r for r in caplog.records if r.name == _LOGGER and r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert _snapshot(db_path) == snapshot  # the refused write recorded nothing


# --------------------------------------------------------------------------------------
# 41-44. The WAL switch after the layout commit (review round 3, H1)
# --------------------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _write_lock_taken_after_the_commit(
    store: ProfileQualificationStore, factory: _ProxyFactory, path: Path, *, begin: str = "BEGIN IMMEDIATE",
) -> AsyncIterator[tuple[asyncio.Task[None], sqlite3.Connection]]:
    """Run ``store.start()`` as a task that ``factory.pause_after_commit`` holds right after its COMMIT, and take
    the file's write lock with a raw connection in that window: reviewer D1's reproduction (review round 3, H1).
    ``begin`` is the statement the holder runs: ``BEGIN IMMEDIATE`` takes a RESERVED lock, ``BEGIN EXCLUSIVE`` an
    EXCLUSIVE one (review round 4, E1).

    Yields ``(start task, lock holder)``. The caller sets ``factory.resume`` and ends the holder's transaction
    (``ROLLBACK``) when it chooses; leaving the block closes the holder, cancels a start that is still running and
    retrieves the outcome of one that already ended, so a failing test leaves nothing behind and asyncio reports
    nothing at teardown.
    """
    starting = asyncio.create_task(store.start())
    holder: sqlite3.Connection | None = None
    try:
        await asyncio.wait_for(factory.committed.wait(), 5)  # the layout is committed, and the store holds no lock
        holder = sqlite3.connect(path, isolation_level=None)  # autocommit: the only transaction is the explicit one
        holder.execute(begin)
        yield starting, holder
    finally:
        if holder is not None:
            holder.close()  # a transaction still open is discarded
        if not starting.done():
            starting.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):  # the test's own failure is already propagating
                await starting
        elif not starting.cancelled():
            starting.exception()  # retrieve a failure the test did not await, so asyncio reports nothing at teardown


async def test_the_wal_switch_is_tried_again_while_another_connection_holds_the_lock(
    db_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    factory = _ProxyFactory()
    factory.pause_after_commit = True  # the start is held right after its COMMIT, with the layout already in the file
    store = ProfileQualificationStore(str(db_path), clock=_Clock(), connection_factory=factory)
    ref = _profile_model().content_ref()
    assert not db_path.exists()  # premise: a fresh file, so this start creates the layout and then asks for WAL

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        async with _write_lock_taken_after_the_commit(store, factory, db_path) as (starting, holder):
            factory.resume.set()  # the start goes on to its WAL switch, which now finds the file locked
            await asyncio.wait_for(factory.wal_refused.wait(), 5)
            assert factory.wal_busy >= 1  # premise: the race was hit and the switch was refused (D1's reproduction)
            holder.execute("ROLLBACK")  # the lock is free: a later try can succeed
            assert await asyncio.wait_for(starting, 10) is None  # the start returned; it did not raise

    assert factory.wal_tries >= 2  # refused at least once, then tried again
    assert _journal_mode(db_path) == "wal"
    assert [r for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.WARNING] == []
    assert await store.get_profile(ref) is None  # started: a data call is served


async def test_a_wal_switch_still_busy_after_every_try_starts_with_a_warning(
    db_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store_module, "_WAL_ATTEMPTS", 3)  # a budget of three tries, none of them waiting
    monkeypatch.setattr(store_module, "_WAL_RETRY_DELAY_S", 0)
    factory = _ProxyFactory()
    factory.pause_after_commit = True  # the start is held right after its COMMIT, with the layout already in the file
    store = ProfileQualificationStore(str(db_path), clock=_Clock(), connection_factory=factory)
    profile = _profile_model()
    assert not db_path.exists()  # premise: a fresh file

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        async with _write_lock_taken_after_the_commit(store, factory, db_path) as (starting, holder):
            factory.resume.set()  # the start goes on to its WAL switch, which now finds the file locked
            await asyncio.wait_for(factory.wal_refused.wait(), 5)
            assert factory.wal_busy >= 1  # premise: the switch is refused while the raw lock is held
            assert await asyncio.wait_for(starting, 10) is None  # the lock is held to the end, yet the start returned
            assert factory.wal_tries == 3 == factory.wal_busy  # every try of the budget found the file busy
            warnings = [r for r in caplog.records if r.name == _LOGGER and r.levelno == logging.WARNING]
            assert len(warnings) == 1
            message = warnings[0].getMessage().replace(str(db_path), "<db>")  # the message also names the file's path
            assert "not in WAL mode" in message and "busy on every try" in message
            holder.execute("ROLLBACK")

    assert _journal_mode(db_path) == "delete"  # the switch never happened: the file is in rollback mode
    ref = await store.register_profile(profile)  # and the store serves in it
    assert await store.get_profile(ref) == profile


async def test_a_wal_switch_answered_with_another_mode_starts_with_a_warning(
    db_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    factory = _ProxyFactory()
    factory.wal_answer = "delete"  # the proxy answers the switch itself: the real statement is not run
    store = ProfileQualificationStore(str(db_path), clock=_Clock(), connection_factory=factory)
    ref = _profile_model().content_ref()
    assert not db_path.exists()  # premise: a fresh file, so the start reaches the switch

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await store.start()

    assert factory.wal_tries == 1  # an answered mode is final: it is not tried again
    warnings = [r for r in caplog.records if r.name == _LOGGER and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage().replace(str(db_path), "<db>")  # the message also names the file's path
    assert "not in WAL mode" in message and "delete" in message
    assert _journal_mode(db_path) == "delete"  # the switch was not run, so the file is still in rollback mode
    assert await store.get_profile(ref) is None  # started: a data call is served


async def test_two_concurrent_fresh_starts_both_succeed_in_wal(db_path: Path) -> None:
    """Two instances start on one fresh file at once. In whichever order the event loop and SQLite interleave them,
    both start, the layout exists once and whole, and the file ends in WAL: reviewer D1's healthy concurrent start,
    end to end (#41 stages the window between the layout commit and the WAL switch by hand)."""
    first = ProfileQualificationStore(str(db_path), clock=_Clock())
    second = ProfileQualificationStore(str(db_path), clock=_Clock())
    ref = _profile_model().content_ref()
    assert not db_path.exists()  # premise: a fresh file, empty for whichever start reaches it first

    await asyncio.wait_for(asyncio.gather(first.start(), second.start()), 15)

    assert await first.get_profile(ref) is None  # both started: each serves a data call
    assert await second.get_profile(ref) is None
    assert _own_kinds(db_path) == _FIFTEEN  # the layout was created once, and whole
    assert _journal_mode(db_path) == "wal"


# --------------------------------------------------------------------------------------
# 45-47. The WAL switch's busy handler, and an error that carries no SQLite code (review round 4, E1, E3)
# --------------------------------------------------------------------------------------


async def test_the_wal_switch_runs_with_the_busy_handler_off(db_path: Path) -> None:
    """Under another connection's EXCLUSIVE lock SQLite runs the busy handler before it answers ``SQLITE_BUSY``
    (7.45 s for one try at ``busy_timeout=5000``, measured by reviewer E), so the retry loop's budget holds only if
    the handler is off for the switch. This test pins the order of the statements, with no clock; #46 pins the time."""
    factory = _ProxyFactory()
    factory.statements = []  # arms recording: each connection the store opens adds a list of its own statements
    store = ProfileQualificationStore(str(db_path), clock=_Clock(), connection_factory=factory)
    assert not db_path.exists()  # premise: a fresh file, so the start reaches the WAL switch with nothing in its way

    await store.start()

    switching = [s for s in factory.statements if any(q.startswith("PRAGMA journal_mode=WAL") for q in s)]
    assert len(switching) == 1  # premise: exactly one connection ran the switch, and its list is the one to read
    statements = switching[0]
    assert "PRAGMA busy_timeout=5000" in statements  # premise: the connection's own handler was set ...
    assert "PRAGMA busy_timeout=0" in statements  # ... and was turned off before the switch
    off = statements.index("PRAGMA busy_timeout=0")
    switch = next(i for i, q in enumerate(statements) if q.startswith("PRAGMA journal_mode=WAL"))
    assert statements.index("PRAGMA busy_timeout=5000") < off < switch  # set to 5 s, then off, then the switch
    assert all(q.startswith("PRAGMA journal_mode=WAL") for q in statements[off + 1:])  # off for the switch only

    recorded = len(factory.statements)
    await store.register_profile(_profile_model())
    later = factory.statements[recorded:]
    assert later  # premise: the call opened a connection of its own, so there is a list to check
    assert all("PRAGMA busy_timeout=5000" in s for s in later)  # every later connection has the handler on ...
    assert not any("PRAGMA busy_timeout=0" in s for s in later)  # ... and none turned it off
    assert _journal_mode(db_path) == "wal"


async def test_an_exclusive_lock_holder_does_not_stretch_the_wal_switch_by_the_busy_timeout(
    db_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reviewer E measured 7.45 s for ONE try of the switch under another connection's EXCLUSIVE lock with the busy
    handler on, so the loop's "about 5 s" was minutes. Two tries against that lock must end in a small part of one
    handler run: every try answers ``SQLITE_BUSY`` at once and no sleep runs, so it takes milliseconds. Unfixed, each
    try runs the 5 s handler (>= 10 s for two), and 2.5 s is half of ONE handler run, so even one unfixed try fails
    it while a loaded runner keeps more than two seconds of room. The 30 s ``wait_for`` lets an unfixed start end
    and fail on the assertion below, not on a timeout."""
    monkeypatch.setattr(store_module, "_WAL_ATTEMPTS", 2)  # two tries ...
    monkeypatch.setattr(store_module, "_WAL_RETRY_DELAY_S", 0)  # ... and no sleep between them: only the handler waits
    factory = _ProxyFactory()
    factory.pause_after_commit = True  # the start is held right after its COMMIT, with the layout already in the file
    store = ProfileQualificationStore(str(db_path), clock=_Clock(), connection_factory=factory)
    assert not db_path.exists()  # premise: a fresh file

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        async with _write_lock_taken_after_the_commit(
            store, factory, db_path, begin="BEGIN EXCLUSIVE",
        ) as (starting, holder):
            started_at = time.monotonic()
            factory.resume.set()  # the start goes on to its WAL switch, which now meets an EXCLUSIVE lock
            await asyncio.wait_for(starting, 30)  # the lock is held to the end, yet the start returned
            elapsed = time.monotonic() - started_at
            holder.execute("ROLLBACK")

    assert factory.wal_busy == 2 == factory.wal_tries  # premise: both tries met the EXCLUSIVE lock
    assert elapsed < 2.5, f"two tries against an EXCLUSIVE lock took {elapsed:.2f} s: the busy handler ran"
    warnings = [r for r in caplog.records if r.name == _LOGGER and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "busy on every try" in warnings[0].getMessage().replace(str(db_path), "<db>")  # the message names the path
    assert _journal_mode(db_path) == "delete"  # the switch never happened: the file is in rollback mode


async def test_an_operational_error_without_an_sqlite_code_propagates_unchanged(
    db_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """An ``OperationalError`` a connection wrapper built itself carries no ``sqlite_errorcode`` (Python sets it only
    on errors the library raised). The retry must not read it as one: it propagates as the same object, not as an
    ``AttributeError`` in its place, and it is not retried."""
    err = sqlite3.OperationalError("injected wal failure")
    assert not hasattr(err, "sqlite_errorcode")  # premise: an error built here carries no SQLite code
    factory = _ProxyFactory()
    factory.wal_raise = err  # the proxy raises it on the switch, without running the statement
    store = ProfileQualificationStore(str(db_path), clock=_Clock(), connection_factory=factory)
    ref = _profile_model().content_ref()
    assert not db_path.exists()  # premise: a fresh file, so the start reaches the switch

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        with pytest.raises(sqlite3.OperationalError) as raised:
            await store.start()

    assert raised.value is err  # the very object the connection raised
    assert factory.wal_tries == 1  # it was not tried again
    assert [r for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.WARNING] == []
    with pytest.raises(ProfileQualificationStoreUnavailable) as stopped:
        await store.get_profile(ref)
    assert stopped.value.args == ("profile_qualification_store_unavailable",)  # the failed start left it stopped

    factory.wal_raise = None  # disarm
    await store.start()  # a later start on the same instance succeeds
    assert await store.get_profile(ref) is None  # started: a data call is served
