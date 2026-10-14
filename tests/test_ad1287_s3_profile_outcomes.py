"""AD-1287 S3 (M1): the profile-qualification store's outcome table, its layout extension and its two new methods.

Contract: ``prompts/ad-1287-s3-outcome-learning.md``, "Tests", M1 (tests #1-#17; #10 also names
``test_an_unregistered_profile_is_refused_and_nothing_written``). The real ``ProfileQualificationStore`` runs on files
in ``tmp_path``; the real ``ElasticTeamStore`` is the second store only where the slot boundary is crossed (#15).
Direct ``sqlite3`` is used in this file only: it plays the file-level writer that builds an S1 file from S1's own
statements, inserts raw rows (the triggers allow new rows) and attempts the writes the triggers refuse.
The helpers are copies of the ones in ``tests/test_ad1287_profile_qualification_store.py`` and
``tests/test_ad1287_slot_qualification.py``: nothing is imported from another test module. Doubles are hand-written;
no mock library.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import dataclasses
import hashlib
import logging
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

import probos.cognitive.profile_qualification_store as store_module
from probos.cognitive.elastic_team import (
    AuthorityCeiling,
    ElasticTeamSpec,
    WorkerAttempt,
    WorkerAttemptOutcome,
    derive_worker_attempt_id,
)
from probos.cognitive.elastic_team_store import ElasticTeamStore
from probos.cognitive.execution_profile import EvaluationRecord, ExecutionProfile, expires_at_ms
from probos.cognitive.profile_qualification_store import (
    ProfileOutcomeLearning,
    ProfileOutcomeState,
    ProfileQualificationConflict,
    ProfileQualificationIntegrityError,
    ProfileQualificationStore,
    ProfileQualificationStoreUnavailable,
    RecordedProfileOutcome,
    SlotAdmissionRefused,
    admit_qualified_attempt,
    check_slot_qualification,
)
from probos.storage.sqlite_factory import SQLiteConnectionFactory

_LOGGER = store_module.logger.name
_TABLES = ("execution_profiles", "profile_evaluations", "profile_invalidations")  # S1's three tables
_OUTCOME_COLUMNS = (  # the STORED columns of profile_outcomes, in the order a raw INSERT names them
    "worker_attempt_id", "profile_ref", "task_class", "observation", "terminal_status", "error_code", "alpha", "beta",
    "learned_at_ms", "schema_version",
)
# the four objects S3 adds, alphabetically: the table and its three triggers
_S3_NAMES = (
    "profile_outcomes", "profile_outcomes_no_delete", "profile_outcomes_no_replace", "profile_outcomes_no_update",
)
_MAX_SEQ = 2**53 - 1  # the largest observation number the store may draw: the test's own literal, not the module's
_TEAM_SPEC_REF = "b" * 64  # an attempt's spec reference where no team store is involved
_RAW_ATTEMPT_ID = "wa-" + "1" * 64  # the attempt id a raw writer's row carries
_ADDED = "added the S3 outcome table"  # what start() logs at INFO when it extends an S1 file

_PROFILE: dict[str, Any] = {
    "schema_version": 1,
    "role_id": "reviewer",
    "task_class": "finding_review",
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
# a team with one slot, which the fixture profile fills (reviewer / finding_review / suite "finding_review")
_SPEC: dict[str, Any] = {
    "schema_version": 1,
    "team_id": "review-team",
    "revision": 1,
    "process": {"bill": {"bill_id": "incident-review", "bill_version": 3}, "plan_hash": None},
    "slots": [
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


# --------------------------------------------------------------------------------------
# Test doubles and helpers
# --------------------------------------------------------------------------------------


class _Clock:
    """A wall clock the test can move (seconds), counting its reads in ``reads``."""

    def __init__(self, now: Any = 1000.0) -> None:
        self.now = now
        self.reads = 0

    def __call__(self) -> Any:
        self.reads += 1
        return self.now


class _ProxyConnection:
    """Delegates ``execute`` / ``commit`` / ``close`` to a real connection and notes every statement.

    When its factory is armed with an SQL prefix, the matching statement runs on the real connection first, and
    ``RuntimeError("injected")`` follows it, so the failure arrives with that statement's work pending in the
    open transaction. The cursor is closed before the raise and nothing is stored.
    """

    def __init__(self, real: Any, factory: _ProxyFactory) -> None:
        self._real = real
        self._factory = factory

    async def execute(self, sql: str, parameters: Sequence[Any] = ()) -> Any:
        factory = self._factory
        factory.executed.append(sql)
        cursor = await self._real.execute(sql, parameters)
        if factory.fail_on is not None and sql.startswith(factory.fail_on):
            await cursor.close()
            factory.fired += 1
            raise RuntimeError("injected")
        return cursor

    async def commit(self) -> None:
        await self._real.commit()

    async def close(self) -> None:
        await self._real.close()


class _ProxyFactory:
    """Wraps ``SQLiteConnectionFactory``: records the statements it ran and fails on an armed statement prefix."""

    def __init__(self) -> None:
        self._real = SQLiteConnectionFactory()
        self.fail_on: str | None = None  # raise RuntimeError("injected") once a statement with this prefix has run
        self.fired = 0  # how many times the injected failure was raised
        self.executed: list[str] = []  # every statement any of this factory's connections was given

    async def connect(self, db_path: str) -> _ProxyConnection:
        return _ProxyConnection(await self._real.connect(db_path), self)


class _World:
    """The two real stores the slot boundary joins, each on its own file, and the clock the qualification side reads.

    Copied from ``tests/test_ad1287_slot_qualification.py``; the qualification file's path is public here because
    a test writes a raw row into it.
    """

    qualifications: ProfileQualificationStore
    teams: ElasticTeamStore

    def __init__(self, directory: Path) -> None:
        self.clock = _Clock(1000.0)
        self.qualifications_path = directory / "profile_qualifications.db"
        self._teams_path = directory / "elastic_teams.db"

    async def start(self) -> None:
        self.qualifications = await _started(self.qualifications_path, clock=self.clock)
        self.teams = ElasticTeamStore(str(self._teams_path))
        await self.teams.start()

    async def stop(self) -> None:
        await self.qualifications.stop()
        await self.teams.stop()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "profile_qualifications.db"


@pytest.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    opened = _World(tmp_path)
    await opened.start()
    try:
        yield opened
    finally:
        await opened.stop()


async def _started(path: Path, **kwargs: Any) -> ProfileQualificationStore:
    """A started store on ``path``. It holds no connection between calls, so one left unstopped leaks nothing."""
    store = ProfileQualificationStore(str(path), **kwargs)
    await store.start()
    return store


def _profile_dict(**path_overrides: Any) -> dict[str, Any]:
    """A deep copy of ``_PROFILE`` with each dotted path set: ``_profile_dict(**{"model.version": "x"})``."""
    data = copy.deepcopy(_PROFILE)
    for path, value in path_overrides.items():
        *parents, leaf = path.split(".")
        node: Any = data
        for part in parents:
            node = node[int(part)] if part.isdigit() else node[part]
        node[int(leaf) if leaf.isdigit() else leaf] = copy.deepcopy(value)
    return data


def _profile_model(**overrides: Any) -> ExecutionProfile:
    return ExecutionProfile.model_validate(_profile_dict(**overrides))


def _evaluation(profile_ref: str, evaluation_id: str = "eval-1") -> EvaluationRecord:
    """A passing run of four cases: with the fixture suite (four samples, 75 %) it qualifies the profile."""
    return EvaluationRecord.model_validate({
        "schema_version": 1,
        "profile_ref": profile_ref,
        "evaluation_id": evaluation_id,
        "evaluator_id": "qual-harness",
        "structurally_valid": True,
        "observations": [
            {"case_id": f"c{number:03d}", "passed": True, "score_bp": 9000, "cost_micro_usd": 120, "latency_ms": 800}
            for number in range(1, 5)
        ],
    })


def _attempt(
    profile_ref: str, session_id: str = "session-1", team_spec_ref: str = _TEAM_SPEC_REF, ordinal: int = 1,
) -> WorkerAttempt:
    """An attempt of the ``review`` slot naming ``profile_ref``; its id derives from spec, session, slot and ordinal."""
    return WorkerAttempt.model_validate({
        "schema_version": 1,
        "worker_attempt_id": derive_worker_attempt_id(
            team_spec_ref=team_spec_ref, session_id=session_id, slot_id="review", ordinal=ordinal,
        ),
        "team_spec_ref": team_spec_ref,
        "session_id": session_id,
        "slot_id": "review",
        "ordinal": ordinal,
        "execution_profile_ref": profile_ref,
        "supersedes_attempt_id": None,
    })


def _outcome(attempt: WorkerAttempt, status: str = "succeeded", code: str | None = None) -> WorkerAttemptOutcome:
    """AD-1286's terminal outcome of ``attempt``; ``recorded_at`` is a float, ``code`` is None exactly for success."""
    return WorkerAttemptOutcome(
        worker_attempt_id=attempt.worker_attempt_id, terminal_status=status, error_code=code, recorded_at=2000.0,
    )


async def _registered(path: Path, **kwargs: Any) -> tuple[ProfileQualificationStore, ExecutionProfile, str]:
    """A started store holding the fixture profile: ``(store, profile, profile_ref)``."""
    store = await _started(path, **kwargs)
    profile = _profile_model()
    return store, profile, await store.register_profile(profile)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _journal_mode(path: Path) -> str:
    """The journal mode a fresh raw connection reads from the file (``wal`` is stored in it; ``delete`` is the default)."""
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return str(raw.execute("PRAGMA journal_mode").fetchone()[0])


def _catalog(path: Path) -> list[tuple[Any, ...]]:
    """Every ``sqlite_master`` row as ``(type, name, tbl_name, sql)``, SQLite's own ``sqlite_autoindex_*`` ones included."""
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return raw.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall()


def _own(catalog: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """The catalog rows of the store's own objects: SQLite's ``sqlite_*`` ones are left out."""
    return [row for row in catalog if not row[1].startswith("sqlite_")]


def _own_objects(path: Path) -> dict[tuple[str, str], Any]:
    """``(type, name) -> stored definition`` of the file's own schema objects."""
    return {(kind, name): sql for kind, name, _table, sql in _own(_catalog(path))}


def _key(statement: str) -> tuple[str, str]:
    """``(type, name)`` of the object one schema statement creates, as ``sqlite_master`` names it."""
    _create, kind, name = statement.split(" ", 3)[:3]
    return kind.lower(), name


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


def _rows(path: Path, table: str) -> list[dict[str, Any]]:
    """Every row of ``table`` read straight from the file, by column name (tests only)."""
    with contextlib.closing(sqlite3.connect(path)) as raw:
        raw.row_factory = sqlite3.Row
        return [dict(row) for row in raw.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]


def _outcome_row(profile_ref: str, attempt_id: str = _RAW_ATTEMPT_ID, **changes: Any) -> dict[str, Any]:
    """A raw ``profile_outcomes`` row the store verifies: the profile's first outcome, a success, ``(3, 2)``."""
    row: dict[str, Any] = {
        "worker_attempt_id": attempt_id,
        "profile_ref": profile_ref,
        "task_class": "finding_review",
        "observation": 1,
        "terminal_status": "succeeded",
        "error_code": None,
        "alpha": 3,
        "beta": 2,
        "learned_at_ms": 1_000_000,
        "schema_version": 1,
    }
    row.update(changes)
    return row


def _raw_insert(raw: sqlite3.Connection, row: dict[str, Any], verb: str = "INSERT") -> None:
    columns = ", ".join(_OUTCOME_COLUMNS)
    marks = ", ".join("?" for _ in _OUTCOME_COLUMNS)
    raw.execute(f"{verb} INTO profile_outcomes ({columns}) VALUES ({marks})", tuple(row[name] for name in _OUTCOME_COLUMNS))


def _insert_outcome(path: Path, row: dict[str, Any]) -> None:
    """A raw writer's new row (the triggers allow new rows), committed on its own connection."""
    with contextlib.closing(sqlite3.connect(path)) as raw:
        _raw_insert(raw, row)
        raw.commit()


async def _with_raw_outcome(
    path: Path, **changes: Any,
) -> tuple[ProfileQualificationStore, str]:
    """A started store holding the fixture profile and ONE raw outcome row of it (``changes`` edit that row)."""
    store, _profile, ref = await _registered(path, clock=_Clock(1000.0))
    assert _rows(path, "profile_outcomes") == []  # premise: the raw row is the profile's only, so its latest
    _insert_outcome(path, _outcome_row(ref, **changes))
    return store, ref


def _logged(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    """The messages the store's logger emitted at exactly ``level``."""
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno == level]


def _added(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The INFO messages saying that a start added the S3 outcome table to an S1 file."""
    return [message for message in _logged(caplog, logging.INFO) if _ADDED in message]


# --------------------------------------------------------------------------------------
# 1-5. The layout: created fresh, extended from S1, refused when partial
# --------------------------------------------------------------------------------------


async def test_fresh_file_holds_the_s1_and_s3_layout(db_path: Path) -> None:
    s1 = {_key(statement): statement for statement in store_module._SCHEMA_STATEMENTS}
    s3 = {_key(statement): statement for statement in store_module._OUTCOME_STATEMENTS}
    assert (len(s1), len(s3)) == (15, 4)  # premise: S1's fifteen statements and S3's four
    assert not set(s1) & set(s3)  # and no object is both
    assert not db_path.exists()  # premise: there is no pre-existing file for the start to accept

    store = await _started(db_path)

    stored = _own_objects(db_path)
    assert len(stored) == 19  # the store's own objects: SQLite's sqlite_autoindex_* ones are not counted
    assert sorted(kind for kind, _name in stored) == ["index"] * 3 + ["table"] * 4 + ["trigger"] * 12
    assert {key: stored[key] for key in s1} == s1  # every S1 object holds exactly its S1 statement
    assert {key: stored[key] for key in s3} == s3  # and every S3 object exactly its S3 statement
    assert set(stored) == set(s1) | set(s3)  # and nothing else is there
    assert _rows(db_path, "profile_outcomes") == []  # the outcome table exists and is empty
    await store.stop()
    second = await _started(db_path)  # a NEW instance accepts the file that the first one created
    assert await second.get_profile("a" * 64) is None  # started: the calls are served, not refused
    assert await second.get_outcome_state("a" * 64) is None


async def test_an_s1_file_is_extended_once_and_keeps_every_s1_object_and_row(
    db_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    profile = _profile_model()
    ref = profile.content_ref()
    record = _evaluation(ref)
    issued_ms = 1_000_000
    _run_script(db_path, store_module._SCHEMA_STATEMENTS)  # an S1 file: built raw from S1's own statements
    with contextlib.closing(sqlite3.connect(db_path)) as raw:  # one profile and one passing evaluation, canonical text
        raw.execute(
            "INSERT INTO execution_profiles (profile_ref, schema_version, canonical_json, recorded_at_ms) "
            "VALUES (?, ?, ?, ?)",
            (ref, 1, profile.canonical_bytes().decode("utf-8"), issued_ms),
        )
        raw.execute(
            "INSERT INTO profile_evaluations (evidence_ref, seq, issued_at_ms, expires_at_ms, schema_version, "
            "canonical_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.content_ref(), 1, issued_ms, expires_at_ms(profile, issued_ms), 1,
                record.canonical_bytes().decode("utf-8"),
            ),
        )
        raw.commit()
    s1_catalog = _catalog(db_path)
    s1_own = _own(s1_catalog)
    s1_rows = {table: _rows(db_path, table) for table in _TABLES}
    assert len(s1_own) == 15  # premise: the fifteen S1 objects
    assert not any("outcome" in row[1] for row in s1_catalog)  # and no S3 object, not even part of one
    assert [len(rows) for rows in s1_rows.values()] == [1, 1, 0]  # premise: the profile and its evaluation are there
    assert _journal_mode(db_path) == "delete"
    store = ProfileQualificationStore(str(db_path), clock=_Clock(1000.0))

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        await store.start()

    assert len(_added(caplog)) == 1  # one INFO: this start added the S3 outcome table
    catalog = _catalog(db_path)
    own = _own(catalog)
    assert len(own) == 19
    assert [row for row in own if row in s1_own] == s1_own  # each of the fifteen S1 rows (type, name, table, sql) is unchanged
    assert set(s1_catalog) <= set(catalog)  # SQLite's own autoindex rows of the S1 tables included
    assert sorted(row[1] for row in own if row not in s1_own) == list(_S3_NAMES)  # the four S3 objects are all it added
    assert {table: _rows(db_path, table) for table in _TABLES} == s1_rows  # every S1 table row is unchanged
    assert _journal_mode(db_path) == "wal"  # an accepted start requests WAL, as it does for any file
    qualification = await store.get_qualification(ref)  # the raw evaluation is read as it was written
    assert qualification is not None
    assert qualification.status == "qualified"
    assert qualification.deciding is not None
    assert (qualification.deciding.evidence_ref, qualification.deciding.seq) == (record.content_ref(), 1)
    assert qualification.deciding.record == record
    attempt = _attempt(ref)  # learning works on the extended file
    learned = await store.record_profile_outcome(attempt, _outcome(attempt))
    assert (learned.alpha, learned.beta, learned.observation) == (3, 2, 1)
    await store.stop()

    caplog.clear()
    second = ProfileQualificationStore(str(db_path), clock=_Clock(2000.0))
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        await second.start()  # a new instance on the extended file: it holds the S3 objects, so nothing is added
    assert _added(caplog) == []
    assert len(_own(_catalog(db_path))) == 19
    assert await second.get_outcome_state(ref) == ProfileOutcomeState(ref, "finding_review", 3, 2, 1, learned)


def _partial_layout(case: str) -> tuple[tuple[str, ...], list[str]]:
    """The S3 statements a raw writer adds to an S1 file for ``case``, and the objects ``start()`` should name."""
    def statement(prefix: str) -> str:
        found = [text for text in store_module._OUTCOME_STATEMENTS if text.startswith(prefix)]
        assert len(found) == 1, prefix  # premise: exactly one statement of the module begins this way
        return found[0]

    table = statement("CREATE TABLE profile_outcomes ")
    no_update = statement("CREATE TRIGGER profile_outcomes_no_update ")
    no_delete = statement("CREATE TRIGGER profile_outcomes_no_delete ")
    no_replace = statement("CREATE TRIGGER profile_outcomes_no_replace ")
    if case == "table_only":
        return (table,), ["profile_outcomes_no_delete", "profile_outcomes_no_replace", "profile_outcomes_no_update"]
    if case == "table_and_two_triggers":
        return (table, no_update, no_delete), ["profile_outcomes_no_replace"]
    if case == "edited_outcome_trigger":
        clause = " OR (profile_ref = NEW.profile_ref AND observation = NEW.observation)"
        assert no_replace.count(clause) == 1  # premise: the clause that is left out is there once
        return (table, no_update, no_delete, no_replace.replace(clause, "")), ["profile_outcomes_no_replace"]
    assert case == "outcome_table_without_check", case
    check = " CHECK (schema_version = 1)"
    assert table.count(check) == 1  # premise: the constraint that is left out is there once
    return (table.replace(check, ""), no_update, no_delete, no_replace), ["profile_outcomes"]


@pytest.mark.parametrize(
    "case", ["table_only", "table_and_two_triggers", "edited_outcome_trigger", "outcome_table_without_check"],
)
async def test_partial_s3_objects_are_refused_and_the_file_is_left_unchanged(
    tmp_path: Path, db_path: Path, caplog: pytest.LogCaptureFixture, case: str,
) -> None:
    s1_statements = tuple(store_module._SCHEMA_STATEMENTS)
    s3_statements = tuple(store_module._OUTCOME_STATEMENTS)
    extra, named = _partial_layout(case)
    _run_script(db_path, s1_statements + extra)  # an S1 file that holds part of the S3 objects, in rollback mode
    own = _own_objects(db_path)
    assert len(own) == 15 + len(extra)  # premise: S1's fifteen objects and the ones this case adds
    assert own != {_key(text): text for text in s1_statements}  # premise: not an S1 file, so nothing is added to it
    assert own != {_key(text): text for text in s1_statements + s3_statements}  # and not the complete layout
    assert _journal_mode(db_path) == "delete"  # premise: rollback mode, which a start that wrote would change
    sha_before = _file_sha256(db_path)
    catalog_before = _catalog(db_path)
    files_before = sorted(entry.name for entry in db_path.parent.iterdir())
    store = ProfileQualificationStore(str(db_path), clock=_Clock())

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        with pytest.raises(ProfileQualificationStoreUnavailable) as refused:
            await store.start()

    assert refused.value.args == ("profile_qualification_layout_mismatch",)
    errors = _logged(caplog, logging.ERROR)
    assert len(errors) == 1
    message = errors[0].replace(str(db_path), "<db>")  # the message also names the file's path
    assert f"differently defined: {', '.join(named)});" in message  # the S3 objects that are missing or changed, by name
    assert _added(caplog) == []  # nothing was added to a file that is not exactly S1
    assert _file_sha256(db_path) == sha_before  # not one byte of the file changed
    assert _catalog(db_path) == catalog_before
    assert _journal_mode(db_path) == "delete"  # in particular, WAL was not set on it
    assert sorted(entry.name for entry in db_path.parent.iterdir()) == files_before  # and no sibling file appeared
    with pytest.raises(ProfileQualificationStoreUnavailable) as unavailable:  # the store stayed stopped
        await store.get_outcome_state("a" * 64)
    assert unavailable.value.args == ("profile_qualification_store_unavailable",)

    # negative control: the same S1 statements plus ALL FOUR S3 ones, raw, are accepted, and nothing is added to them
    control = tmp_path / "control.db"
    _run_script(control, s1_statements + s3_statements)
    control_objects = _own_objects(control)
    assert len(control_objects) == 19  # premise: the complete layout
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        accepted = await _started(control)
    assert _own_objects(control) == control_objects  # the accepted file's objects are as they were
    assert _logged(caplog, logging.ERROR) == [] and _added(caplog) == []
    assert await accepted.get_outcome_state("a" * 64) is None  # and the store serves


async def test_an_extension_failing_midway_leaves_the_s1_layout_and_a_later_start_extends_it(db_path: Path) -> None:
    _run_script(db_path, store_module._SCHEMA_STATEMENTS)  # an S1 file in rollback mode
    s1_catalog = _catalog(db_path)
    assert len(_own(s1_catalog)) == 15  # premise: exactly the S1 layout
    assert _journal_mode(db_path) == "delete"
    factory = _ProxyFactory()
    factory.fail_on = "CREATE TRIGGER profile_outcomes_no_delete "  # after the table and no_update, before no_replace
    store = ProfileQualificationStore(str(db_path), clock=_Clock(), connection_factory=factory)

    with pytest.raises(RuntimeError, match="injected"):
        await store.start()

    assert factory.fired == 1  # premise: the failure was injected at the boundary this test is about
    created = [text for text in factory.executed if text.startswith("CREATE ")]
    assert [_key(text) for text in created] == [  # the extension was part-way through: the table, then no_update, then no_delete
        ("table", "profile_outcomes"), ("trigger", "profile_outcomes_no_update"), ("trigger", "profile_outcomes_no_delete"),
    ]
    assert _catalog(db_path) == s1_catalog  # the S1 layout, exactly: the work of the failed extension is gone
    assert _journal_mode(db_path) == "delete"  # and WAL was never requested
    with pytest.raises(ProfileQualificationStoreUnavailable) as unavailable:  # the store stayed stopped
        await store.get_outcome_state("a" * 64)
    assert unavailable.value.args == ("profile_qualification_store_unavailable",)

    factory.fail_on = None
    await store.start()  # a later start extends the same file

    assert len(_own_objects(db_path)) == 19
    assert set(s1_catalog) <= set(_catalog(db_path))  # every S1 row is as it was
    assert await store.get_outcome_state("a" * 64) is None  # started: the new calls are served
    assert factory.fired == 1  # the failure was not injected again


async def test_two_concurrent_starts_on_an_s1_file_both_succeed(
    db_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    profile = _profile_model()
    ref = profile.content_ref()
    _run_script(db_path, store_module._SCHEMA_STATEMENTS)  # an S1 file in rollback mode
    assert len(_own_objects(db_path)) == 15  # premise: exactly the S1 layout
    assert _journal_mode(db_path) == "delete"
    first = ProfileQualificationStore(str(db_path), clock=_Clock(1000.0))
    second = ProfileQualificationStore(str(db_path), clock=_Clock(1000.0))

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        await asyncio.gather(first.start(), second.start())  # two instances: each has its own lock, so they do race

    assert len(_added(caplog)) == 1  # one of them extended the file; the other found it extended
    assert _logged(caplog, logging.ERROR) == []
    objects = _catalog(db_path)
    assert len(_own(objects)) == 19  # the S3 objects exist once each
    assert len({row[1] for row in objects}) == len(objects)  # no name is there twice
    assert _journal_mode(db_path) == "wal"
    assert await first.register_profile(profile) == ref  # both serve, and each sees what the other wrote
    attempt = _attempt(ref)
    learned = await second.record_profile_outcome(attempt, _outcome(attempt))
    assert (learned.observation, learned.alpha, learned.beta) == (1, 3, 2)
    assert await first.get_outcome_state(ref) == ProfileOutcomeState(ref, "finding_review", 3, 2, 1, learned)


# --------------------------------------------------------------------------------------
# 6-10. Learning: the counts, the prior, idempotency, conflicts and bad input
# --------------------------------------------------------------------------------------


async def test_succeeded_adds_alpha_and_failed_adds_beta_from_the_2_2_prior(db_path: Path) -> None:
    clock = _Clock(1000.0)
    store, _profile, ref = await _registered(db_path, clock=clock)
    assert _rows(db_path, "profile_outcomes") == []  # premise: nothing learned yet
    steps = [  # (session, status, code, clock, (alpha, beta) after it)
        ("session-1", "succeeded", None, 1000.0, (3, 2)),
        ("session-2", "failed", "model_timeout", 2000.0, (3, 3)),
        ("session-3", "succeeded", None, 3000.0, (4, 3)),
    ]
    learned: list[RecordedProfileOutcome] = []

    for number, (session, status, code, now, counts) in enumerate(steps, start=1):
        attempt = _attempt(ref, session_id=session)
        clock.now = now
        row = await store.record_profile_outcome(attempt, _outcome(attempt, status, code))
        learned.append(row)
        assert row == RecordedProfileOutcome(
            attempt.worker_attempt_id, ref, "finding_review", status, code, number, counts[0], counts[1], int(now * 1000),
        )
        # the profile's latest row is its state
        assert await store.get_outcome_state(ref) == ProfileOutcomeState(ref, "finding_review", *counts, number, row)

    stored = {row["worker_attempt_id"]: row for row in _rows(db_path, "profile_outcomes")}
    assert len(stored) == 3 and len(learned) == 3
    for row in learned:  # the profile, its task class, AD-1286's status and error code and the counts after it are stored
        assert stored[row.worker_attempt_id] == {
            "worker_attempt_id": row.worker_attempt_id, "profile_ref": ref, "task_class": "finding_review",
            "observation": row.observation, "terminal_status": row.terminal_status, "error_code": row.error_code,
            "alpha": row.alpha, "beta": row.beta, "learned_at_ms": row.learned_at_ms, "schema_version": 1,
        }
    assert [row.error_code for row in learned] == [None, "model_timeout", None]


async def test_unobserved_profile_reports_the_prior_and_unknown_reports_none(db_path: Path) -> None:
    store, _profile, ref = await _registered(db_path, clock=_Clock())
    assert _rows(db_path, "profile_outcomes") == []  # premise: nothing is learned for the registered profile
    unknown = "a" * 64
    assert ref != unknown  # premise: the unknown reference is not the registered one

    state = await store.get_outcome_state(ref)

    assert state == ProfileOutcomeState(ref, "finding_review", 2, 2, 0, None)
    assert state is not None
    assert (state.alpha, state.beta, state.observations, state.latest) == (2, 2, 0, None)
    assert await store.get_outcome_state(unknown) is None
    for malformed in ("x", "A" * 64, "a" * 63, "", None, 5):
        with pytest.raises(ValueError) as refused:
            await store.get_outcome_state(malformed)  # type: ignore[arg-type]
        assert type(refused.value) is ValueError, malformed
        assert refused.value.args == ("execution_profile_ref_invalid",), malformed


async def test_learning_is_idempotent_and_survives_restart(db_path: Path) -> None:
    clock = _Clock(1000.0)
    store, _profile, ref = await _registered(db_path, clock=clock)
    succeeded, failed = _attempt(ref, session_id="session-ok"), _attempt(ref, session_id="session-bad")
    ok_outcome, bad_outcome = _outcome(succeeded), _outcome(failed, "failed", "model_timeout")
    first_ok = await store.record_profile_outcome(succeeded, ok_outcome)
    first_bad = await store.record_profile_outcome(failed, bad_outcome)
    assert (first_ok.learned_at_ms, first_bad.learned_at_ms) == (1_000_000, 1_000_000)
    rows_before = _rows(db_path, "profile_outcomes")
    state_before = await store.get_outcome_state(ref)
    assert len(rows_before) == 2
    assert state_before == ProfileOutcomeState(ref, "finding_review", 3, 3, 2, first_bad)

    clock.now = 2000.0  # time has moved: a repeat that wrote would stamp 2_000_000
    assert await store.record_profile_outcome(succeeded, ok_outcome) == first_ok  # the identical row, first learned_at_ms
    assert await store.record_profile_outcome(failed, bad_outcome) == first_bad
    assert _rows(db_path, "profile_outcomes") == rows_before  # one row each: the repeats wrote nothing
    assert await store.get_outcome_state(ref) == state_before

    await store.stop()
    reopened = await _started(db_path, clock=_Clock(3000.0))  # a restart: nothing but the file carries over
    assert await reopened.record_profile_outcome(succeeded, ok_outcome) == first_ok
    assert await reopened.record_profile_outcome(failed, bad_outcome) == first_bad
    assert _rows(db_path, "profile_outcomes") == rows_before
    assert await reopened.get_outcome_state(ref) == state_before  # the state is unchanged by the repeats

    other = _attempt(ref, session_id="session-other")  # control: a different attempt is learned, with the new clock
    third = await reopened.record_profile_outcome(other, _outcome(other))
    assert (third.observation, third.alpha, third.beta, third.learned_at_ms) == (3, 4, 3, 3_000_000)
    assert len(_rows(db_path, "profile_outcomes")) == 3


@pytest.mark.parametrize("change", ["other_status", "other_error_code", "other_profile"])
async def test_a_different_outcome_or_profile_for_a_learned_attempt_is_refused(db_path: Path, change: str) -> None:
    store, _profile, ref = await _registered(db_path, clock=_Clock(1000.0))
    other_ref = await store.register_profile(_profile_model(**{"model.version": "2026-10-01"}))
    assert other_ref != ref  # premise: a second registered profile
    attempt = _attempt(ref)
    outcome = _outcome(attempt, "failed", "model_timeout")
    learned = await store.record_profile_outcome(attempt, outcome)
    rows_before = _rows(db_path, "profile_outcomes")
    state_before = await store.get_outcome_state(ref)
    other_state_before = await store.get_outcome_state(other_ref)
    assert len(rows_before) == 1 and learned.observation == 1  # premise: the attempt is learned
    assert other_state_before == ProfileOutcomeState(other_ref, "finding_review", 2, 2, 0, None)
    if change == "other_status":
        call = (attempt, _outcome(attempt, "succeeded"))
    elif change == "other_error_code":
        call = (attempt, _outcome(attempt, "failed", "tool_error"))
    else:
        moved = _attempt(other_ref)  # the same attempt id: it derives from spec, session, slot and ordinal, not the profile
        assert moved.worker_attempt_id == attempt.worker_attempt_id and moved.execution_profile_ref == other_ref
        call = (moved, outcome)

    with pytest.raises(ProfileQualificationConflict) as refused:
        await store.record_profile_outcome(*call)

    assert type(refused.value) is ProfileQualificationConflict
    assert refused.value.args == ("profile_outcome_conflict",)
    assert _rows(db_path, "profile_outcomes") == rows_before  # nothing was written, and the first row stands
    assert await store.get_outcome_state(ref) == state_before
    assert await store.get_outcome_state(other_ref) == other_state_before  # nothing was learned for the other profile
    assert await store.record_profile_outcome(attempt, outcome) == learned  # control: the identical call is accepted
    fresh = _attempt(other_ref, session_id="session-fresh")  # control: a NEW attempt of the other profile is learned
    accepted = await store.record_profile_outcome(fresh, _outcome(fresh))
    assert (accepted.profile_ref, accepted.observation, accepted.alpha, accepted.beta) == (other_ref, 1, 3, 2)


@pytest.mark.parametrize("case", ["wrong_type", "attempt_mismatch", "cancelled"])
async def test_bad_input_is_refused_before_any_read(db_path: Path, case: str) -> None:
    clock = _Clock(1000.0)
    store, _profile, ref = await _registered(db_path, clock=clock)
    attempt = _attempt(ref)
    outcome = _outcome(attempt)
    other = _attempt(ref, session_id="session-2")  # another attempt: its outcome names another id
    if case == "wrong_type":
        expected: tuple[type[Exception], str] = (TypeError, "profile_outcome_type_invalid")
        calls: list[tuple[Any, Any]] = [
            (attempt.model_dump(), outcome), (attempt, outcome.model_dump()), (outcome, attempt), (None, None),
        ]
    elif case == "attempt_mismatch":
        expected = (ValueError, "profile_outcome_attempt_mismatch")
        calls = [(attempt, _outcome(other))]
    else:
        expected = (ValueError, "profile_outcome_not_evidence")
        calls = [(attempt, _outcome(attempt, "cancelled", "operator_cancelled"))]
    assert _rows(db_path, "profile_outcomes") == []  # premise: nothing is learned yet
    clock.reads = 0  # the registration above read it; what follows must not

    for bad_attempt, bad_outcome in calls:
        with pytest.raises(expected[0]) as refused:
            await store.record_profile_outcome(bad_attempt, bad_outcome)
        assert type(refused.value) is expected[0]
        assert refused.value.args == (expected[1],)

    assert clock.reads == 0  # refused before any read: the clock was never asked
    assert _rows(db_path, "profile_outcomes") == []
    learned = await store.record_profile_outcome(attempt, outcome)  # control: well-formed input is served, and reads once
    assert (learned.observation, clock.reads) == (1, 1)


async def test_an_unregistered_profile_is_refused_and_nothing_written(db_path: Path) -> None:
    store = await _started(db_path, clock=_Clock(1000.0))
    profile = _profile_model()
    attempt = _attempt(profile.content_ref())
    assert await store.get_profile(profile.content_ref()) is None  # premise: the attempt's profile is not registered

    with pytest.raises(ProfileQualificationConflict) as refused:
        await store.record_profile_outcome(attempt, _outcome(attempt))

    assert type(refused.value) is ProfileQualificationConflict
    assert refused.value.args == ("profile_unknown",)
    assert _rows(db_path, "profile_outcomes") == []  # nothing was written
    assert _rows(db_path, "execution_profiles") == []  # and the refused call did not register the profile either
    await store.register_profile(profile)  # control: once the profile is registered, the same call is accepted
    learned = await store.record_profile_outcome(attempt, _outcome(attempt))
    assert (learned.observation, learned.alpha, learned.beta) == (1, 3, 2)
    assert len(_rows(db_path, "profile_outcomes")) == 1


# --------------------------------------------------------------------------------------
# 11-14. Integrity: tampered rows, the engine's own guards, the version CHECK and the observation bound
# --------------------------------------------------------------------------------------

# What a raw writer changes in an otherwise consistent first-outcome row (a success, observation 1, counts (3, 2)).
# Each row fails the check named by its id; ``observation_zero`` cannot fail only one, because no counts are
# consistent with observation 0 and an outcome at the same time.
_TAMPERED: dict[str, dict[str, Any]] = {
    "sum": {"alpha": 3, "beta": 3},  # the counts add up to 6 where the prior and one observation give 5
    "task_class": {"task_class": "finding_audit"},  # not the profile's task class
    "succeeded_with_code": {"error_code": "model_timeout"},
    "failed_without_code": {"terminal_status": "failed", "error_code": None, "alpha": 2, "beta": 3},
    "bad_code": {"terminal_status": "failed", "error_code": "Model Timeout", "alpha": 2, "beta": 3},
    "learned_at_negative": {"learned_at_ms": -1},
    "observation_zero": {"observation": 0, "alpha": 2, "beta": 2},
    "status_cancelled": {"terminal_status": "cancelled", "error_code": "operator_cancelled", "alpha": 2, "beta": 3},
    "alpha_below_own_count": {"alpha": 2, "beta": 3},  # a success that left alpha under the prior plus itself
}


@pytest.mark.parametrize("case", list(_TAMPERED))
async def test_tampered_outcome_rows_are_integrity_errors(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, case: str,
) -> None:
    changes = _TAMPERED[case]
    control_store, control_ref = await _with_raw_outcome(tmp_path / "control.db")  # negative control: consistent
    consistent = RecordedProfileOutcome(_RAW_ATTEMPT_ID, control_ref, "finding_review", "succeeded", None, 1, 3, 2, 1_000_000)
    assert await control_store.get_outcome_state(control_ref) == ProfileOutcomeState(
        control_ref, "finding_review", 3, 2, 1, consistent,
    )  # a consistent raw row is read as the profile's state
    follow = _attempt(control_ref, session_id="session-next")
    extended = await control_store.record_profile_outcome(follow, _outcome(follow))
    assert (extended.observation, extended.alpha, extended.beta) == (2, 4, 2)  # and the next outcome is learned on it

    path = tmp_path / "tampered.db"
    store, ref = await _with_raw_outcome(path, **changes)
    stored = _rows(path, "profile_outcomes")
    assert stored == [_outcome_row(ref, **changes)]  # premise: the raw row is the profile's only, and so its latest
    assert stored != [_outcome_row(ref)]  # and it is not the consistent row
    next_attempt = _attempt(ref, session_id="session-next")

    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        with pytest.raises(ProfileQualificationIntegrityError) as read_refused:
            await store.get_outcome_state(ref)
        with pytest.raises(ProfileQualificationIntegrityError) as write_refused:
            await store.record_profile_outcome(next_attempt, _outcome(next_attempt))

    assert read_refused.value.args == ("profile_qualification_integrity",)
    assert write_refused.value.args == ("profile_qualification_integrity",)
    errors = _logged(caplog, logging.ERROR)
    assert len(errors) == 2 and all("profile outcome" in message for message in errors)
    assert _rows(path, "profile_outcomes") == stored  # the refused learn wrote nothing


@pytest.mark.parametrize("attack", ["update", "delete", "replace_by_attempt", "replace_by_observation"])
async def test_the_database_refuses_update_delete_and_replace_of_outcomes(db_path: Path, attack: str) -> None:
    store, _profile, ref = await _registered(db_path, clock=_Clock(1000.0))
    attempt = _attempt(ref)
    learned = await store.record_profile_outcome(attempt, _outcome(attempt))
    rows_before = _rows(db_path, "profile_outcomes")
    assert len(rows_before) == 1 and rows_before[0]["observation"] == 1  # premise: one stored outcome to attack
    attempt_id = attempt.worker_attempt_id
    replacing: dict[str, Any] | None = None
    if attack == "update":
        statement, params = "UPDATE profile_outcomes SET beta = beta + 1 WHERE worker_attempt_id = ?", (attempt_id,)
    elif attack == "delete":
        statement, params = "DELETE FROM profile_outcomes WHERE worker_attempt_id = ?", (attempt_id,)
    elif attack == "replace_by_attempt":  # the stored attempt's id, with an observation no stored row holds
        replacing = _outcome_row(ref, attempt_id, observation=2, alpha=4, beta=2)
    else:  # another attempt, in the place (profile, observation) the stored row holds
        replacing = _outcome_row(ref, _RAW_ATTEMPT_ID, observation=1)

    with contextlib.closing(sqlite3.connect(db_path)) as raw:  # default pragmas: no foreign keys, no recursive triggers
        with pytest.raises(sqlite3.IntegrityError, match="profile_qualification_immutable"):
            if replacing is None:
                raw.execute(statement, params)
            else:
                _raw_insert(raw, replacing, "INSERT OR REPLACE")
        raw.rollback()

    assert _rows(db_path, "profile_outcomes") == rows_before  # not one row changed, went or was replaced
    assert await store.get_outcome_state(ref) == ProfileOutcomeState(ref, "finding_review", 3, 2, 1, learned)
    # negative control: a genuinely new row (a new attempt in a new place) is accepted by the same database
    _insert_outcome(db_path, _outcome_row(ref, "wa-" + "2" * 64, observation=2, alpha=4, beta=2))
    assert len(_rows(db_path, "profile_outcomes")) == 2
    state = await store.get_outcome_state(ref)
    assert state is not None and (state.alpha, state.beta, state.observations) == (4, 2, 2)


async def test_the_outcome_schema_version_check_refuses_other_versions(db_path: Path) -> None:
    store, _profile, ref = await _registered(db_path, clock=_Clock())
    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        assert raw.execute("PRAGMA foreign_keys").fetchone() == (0,)  # premise: this connection enforces nothing but CHECKs
        _raw_insert(raw, _outcome_row(ref, "wa-" + "a" * 64, schema_version=1))  # control: version 1 is accepted
        raw.commit()
        for version in (0, 2, 99):
            with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
                _raw_insert(raw, _outcome_row(ref, "wa-" + "b" * 64, observation=2, alpha=4, schema_version=version))
            raw.rollback()

    stored = _rows(db_path, "profile_outcomes")
    assert [row["schema_version"] for row in stored] == [1]  # only the version-1 row was stored
    state = await store.get_outcome_state(ref)  # and it is the row the store reads
    assert state is not None and (state.alpha, state.beta, state.observations) == (3, 2, 1)


async def test_the_observation_bound_is_refused_before_any_write(tmp_path: Path) -> None:
    half = 2**52
    assert _MAX_SEQ - 1 == 2**53 - 2  # premise: the neighbour below uses the number just under the bound
    assert (half + 2) + (half + 1) == 4 + _MAX_SEQ  # premise: these counts are consistent with observation 2**53 - 1
    path = tmp_path / "at_bound.db"
    store, _profile, ref = await _registered(path, clock=_Clock(1000.0))
    holder = _attempt(ref, session_id="session-holder")
    _insert_outcome(path, _outcome_row(ref, holder.worker_attempt_id, observation=_MAX_SEQ, alpha=half + 2, beta=half + 1))
    state = await store.get_outcome_state(ref)  # premise: the raw row verifies, so only the bound can refuse a learn
    assert state is not None
    assert (state.alpha, state.beta, state.observations) == (half + 2, half + 1, _MAX_SEQ)
    assert state.latest is not None
    rows_before = _rows(path, "profile_outcomes")
    assert len(rows_before) == 1

    for session, status, code in (("session-s", "succeeded", None), ("session-f", "failed", "model_timeout")):
        attempt = _attempt(ref, session_id=session)
        with pytest.raises(ProfileQualificationConflict) as exhausted:
            await store.record_profile_outcome(attempt, _outcome(attempt, status, code))
        assert type(exhausted.value) is ProfileQualificationConflict
        assert exhausted.value.args == ("profile_sequence_exhausted",), status
        assert _rows(path, "profile_outcomes") == rows_before  # nothing was written
    assert await store.get_outcome_state(ref) == state
    assert await store.record_profile_outcome(holder, _outcome(holder)) == state.latest  # the replay allocates nothing

    # negative control: one below the bound is accepted, and reaches it; the next learn is then refused
    below = tmp_path / "below_bound.db"
    control, _profile2, control_ref = await _registered(below, clock=_Clock(1000.0))
    _insert_outcome(below, _outcome_row(control_ref, observation=_MAX_SEQ - 1, alpha=half + 1, beta=half + 1))
    reaching = _attempt(control_ref, session_id="session-reaching")
    reached = await control.record_profile_outcome(reaching, _outcome(reaching))
    assert (reached.observation, reached.alpha, reached.beta) == (_MAX_SEQ, half + 2, half + 1)
    assert len(_rows(below, "profile_outcomes")) == 2
    beyond = _attempt(control_ref, session_id="session-beyond")
    with pytest.raises(ProfileQualificationConflict) as beyond_refused:
        await control.record_profile_outcome(beyond, _outcome(beyond))
    assert beyond_refused.value.args == ("profile_sequence_exhausted",)
    assert len(_rows(below, "profile_outcomes")) == 2


# --------------------------------------------------------------------------------------
# 15-17. Learning gates nothing; the clock; the result types
# --------------------------------------------------------------------------------------


async def test_learning_gates_nothing(world: _World) -> None:
    qualifications, teams = world.qualifications, world.teams
    spec = ElasticTeamSpec.model_validate(_SPEC)
    spec_ref = await teams.put_team_spec(spec)
    slot = spec.slot("review")
    assert slot is not None
    good = await qualifications.register_profile(_profile_model())
    await qualifications.record_evaluation(_evaluation(good))
    unevaluated = await qualifications.register_profile(_profile_model(**{"model.version": "2026-10-01"}))
    assert good != unevaluated  # premise: two registered profiles, one of them evaluated

    # (a) a qualified profile with only failures learned is still qualified, a candidate, and admitted
    for number in (1, 2, 3):
        failing = _attempt(good, session_id=f"session-failed-{number}", team_spec_ref=spec_ref)
        await qualifications.record_profile_outcome(failing, _outcome(failing, "failed", "model_timeout"))
    state = await qualifications.get_outcome_state(good)
    assert state is not None and (state.alpha, state.beta, state.observations) == (2, 5, 3)  # premise: failures only
    qualification = await qualifications.get_qualification(good)
    assert qualification is not None and qualification.status == "qualified"
    found = await qualifications.find_slot_candidates(slot)
    assert [candidate.profile_ref for candidate in found.candidates] == [good]
    admitted = _attempt(good, session_id="session-admitted", team_spec_ref=spec_ref)
    assert await admit_qualified_attempt(qualifications, teams, admitted) == admitted
    assert await teams.get_attempt(admitted.worker_attempt_id) == admitted  # AD-1286's store holds it

    # (b) an unevaluated profile with successes learned is still refused
    for number in (1, 2, 3, 4):
        winning = _attempt(unevaluated, session_id=f"session-won-{number}", team_spec_ref=spec_ref)
        await qualifications.record_profile_outcome(winning, _outcome(winning))
    won = await qualifications.get_outcome_state(unevaluated)
    assert won is not None and (won.alpha, won.beta, won.observations) == (6, 2, 4)  # premise: successes only
    unevaluated_qualification = await qualifications.get_qualification(unevaluated)
    assert unevaluated_qualification is not None and unevaluated_qualification.status == "unevaluated"
    candidates_now = await qualifications.find_slot_candidates(slot)
    assert [candidate.profile_ref for candidate in candidates_now.candidates] == [good]  # the unevaluated one is turned away
    refused_attempt = _attempt(unevaluated, session_id="session-refused", team_spec_ref=spec_ref)
    with pytest.raises(SlotAdmissionRefused) as refused:
        await admit_qualified_attempt(qualifications, teams, refused_attempt)
    assert refused.value.args == ("profile_status_unevaluated",)
    assert await teams.get_attempt(refused_attempt.worker_attempt_id) is None  # nothing was recorded

    # (c) after a tampered latest outcome row the S1 reads return what they returned before; only the outcome read raises
    async def s1_reads() -> tuple[Any, ...]:
        return (
            await qualifications.get_qualification(good),
            await qualifications.find_slot_candidates(slot),
            await check_slot_qualification(qualifications, spec, "review", good),
        )

    before = await s1_reads()
    assert before[0] is not None and before[0].status == "qualified"  # premise: the profile qualifies, at this fixed clock
    _insert_outcome(
        world.qualifications_path,
        _outcome_row(good, "wa-" + "3" * 64, observation=4, alpha=3, beta=5, task_class="finding_audit"),
    )
    with pytest.raises(ProfileQualificationIntegrityError):  # premise: the tamper is the profile's latest and is noticed
        await qualifications.get_outcome_state(good)
    assert await s1_reads() == before
    later = _attempt(good, session_id="session-later", team_spec_ref=spec_ref)
    assert await admit_qualified_attempt(qualifications, teams, later) == later  # and the slot boundary still admits


async def test_outcome_calls_read_the_clock_once(db_path: Path) -> None:
    clock = _Clock(1000.0)
    store = await _started(db_path, clock=clock)
    assert clock.reads == 0  # premise: start() reads no clock
    profile, other_profile = _profile_model(), _profile_model(**{"model.version": "2026-10-01"})
    ref, other_ref = await store.register_profile(profile), await store.register_profile(other_profile)
    assert clock.reads == 2  # premise: one read per served call
    attempt, second = _attempt(ref), _attempt(ref, session_id="session-2")
    unregistered = _attempt("c" * 64)
    outcome = _outcome(attempt)
    # (label, call, the exception it raises or None, reads)
    cases: list[tuple[str, Callable[[], Awaitable[Any]], type[Exception] | None, int]] = [
        ("get_outcome_state, nothing learned", lambda: store.get_outcome_state(other_ref), None, 1),
        ("record_profile_outcome, new", lambda: store.record_profile_outcome(attempt, outcome), None, 1),
        ("record_profile_outcome, repeat", lambda: store.record_profile_outcome(attempt, outcome), None, 1),
        ("get_outcome_state, learned", lambda: store.get_outcome_state(ref), None, 1),
        ("get_outcome_state, unknown", lambda: store.get_outcome_state("a" * 64), None, 1),
        # refused by what the store holds, after the arguments passed: the clock was read
        (
            "record_profile_outcome, unregistered profile",
            lambda: store.record_profile_outcome(unregistered, _outcome(unregistered)), ProfileQualificationConflict, 1,
        ),
        (
            "record_profile_outcome, conflict",
            lambda: store.record_profile_outcome(attempt, _outcome(attempt, "failed", "model_timeout")),
            ProfileQualificationConflict, 1,
        ),
        # refused input: nothing was read
        ("record_profile_outcome, wrong type", lambda: store.record_profile_outcome(None, outcome), TypeError, 0),  # type: ignore[arg-type]
        (
            "record_profile_outcome, attempt mismatch",
            lambda: store.record_profile_outcome(attempt, _outcome(second)), ValueError, 0,
        ),
        (
            "record_profile_outcome, cancelled",
            lambda: store.record_profile_outcome(attempt, _outcome(attempt, "cancelled", "operator_cancelled")),
            ValueError, 0,
        ),
        ("get_outcome_state, malformed", lambda: store.get_outcome_state("x"), ValueError, 0),
    ]

    for label, call, raises, reads in cases:
        before = clock.reads
        if raises is None:
            await call()
        else:
            with pytest.raises(raises):
                await call()
        assert clock.reads - before == reads, label

    reads_before_stop = clock.reads
    await store.stop()
    for label, stopped_call in (
        ("get_outcome_state", lambda: store.get_outcome_state(ref)),
        ("record_profile_outcome", lambda: store.record_profile_outcome(attempt, outcome)),
    ):
        with pytest.raises(ProfileQualificationStoreUnavailable) as unavailable:  # a stopped store is refused unread
            await stopped_call()
        assert unavailable.value.args == ("profile_qualification_store_unavailable",), label
    await store.start()
    assert clock.reads == reads_before_stop  # neither the stopped calls, stop() nor start() read the clock


_AUTHORITY_WORDS = ("scope", "rank", "lease", "grant", "authority", "permission")


def _authority_named(names: set[str]) -> set[str]:
    return {name for name in names if any(word in name for word in _AUTHORITY_WORDS)}


def test_outcome_result_types_carry_no_authority_fields() -> None:
    result_types = (RecordedProfileOutcome, ProfileOutcomeState, ProfileOutcomeLearning)
    names = {field.name for result_type in result_types for field in dataclasses.fields(result_type)}

    # the walk reaches every field of the three types (a walk that found nothing would pass vacuously)
    assert {
        "worker_attempt_id", "profile_ref", "task_class", "terminal_status", "error_code", "observation", "alpha",
        "beta", "learned_at_ms", "observations", "latest", "disposition", "recorded",
    } <= names
    assert _authority_named(names) == set()
    # negative control: the same words flag AD-1286's AuthorityCeiling
    assert "tool_scopes" in _authority_named(set(AuthorityCeiling.model_fields))
