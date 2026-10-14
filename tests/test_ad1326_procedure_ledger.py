"""AD-1326 (#1510), Milestone 1: the procedure challenge ledger and its ProcedureStore wiring.

The ledger tests run a real ``ProcedureChallengeLedger`` on a real aiosqlite connection from
``default_factory`` under ``tmp_path``. The ledger never opens or closes its connection: its owner
does (D1b), so every test that opens one closes it. The store tests run a real ``ProcedureStore``
on ``tmp_path``, with a recording ``ConnectionFactory`` wherever they must see the connections it
opens.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import inspect
import json
import logging
import sqlite3
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

import pytest

from probos.cognitive import procedure_challenges
from probos.cognitive.procedure_challenger import ProcedureChallenger, build_procedure_challenger
from probos.cognitive.procedure_challenges import (
    MAX_DECISION_CHARS,
    ChallengeRecord,
    ChallengeStatus,
    ProcedureChallengeLedger,
    bounded_text,
)
from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import Procedure, ProcedureStep
from probos.config import LIFECYCLE_ARCHIVE_DAYS, DreamingConfig, SystemConfig
from probos.infrastructure.backup_inventory import BackupRoot, discover
from probos.knowledge import embeddings
from probos.storage.registry import load_default_store_registry
from probos.storage.sqlite_factory import default_factory
from tests.fixtures.bf662_embedding_fakes import BF662EmbeddingFunctionA


class _StrSubclass(str):
    """A ``str`` that is not exactly a ``str``: ``bounded_text`` checks ``type(x) is str``."""


class _Clock:
    """An injected clock that only moves when the test moves it."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _FailingScriptConnection:
    """A ``DatabaseConnection`` double whose ``executescript`` raises; it records every call made on it."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls: list[str] = []

    async def execute(self, sql: str, parameters: Any = ()) -> None:
        self.calls.append("execute")

    async def executescript(self, sql_script: str) -> None:
        self.calls.append("executescript")
        raise self._error

    async def commit(self) -> None:
        self.calls.append("commit")

    async def close(self) -> None:
        self.calls.append("close")


class _RecordingFactory:
    """A ``ConnectionFactory`` that opens real connections through ``default_factory`` and records each one."""

    def __init__(self) -> None:
        self.connected: list[tuple[str, Any]] = []

    async def connect(self, db_path: str) -> Any:
        connection = await default_factory.connect(db_path)
        self.connected.append((db_path, connection))
        return connection

    def connection_for(self, filename: str) -> Any:
        (connection,) = [opened for path, opened in self.connected if Path(path).name == filename]
        return connection

    async def close_all(self) -> None:
        for _, connection in self.connected:
            await connection.close()  # idempotent: a connection a test already closed is left alone


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
async def ledger(tmp_path: Path, clock: _Clock) -> AsyncIterator[ProcedureChallengeLedger]:
    """A started ledger on a real connection it does not own: the fixture closes the connection."""
    connection = await default_factory.connect(str(tmp_path / "procedures_challenges.db"))
    try:
        started = ProcedureChallengeLedger(connection, clock=clock)
        await started.start()
        yield started
    finally:
        await connection.close()


@contextlib.asynccontextmanager
async def _running_store(
    root: Path, factory: _RecordingFactory | None = None,
) -> AsyncIterator[ProcedureStore]:
    """A started ``ProcedureStore`` that is stopped (and whose recorded connections are closed) on exit."""
    store = ProcedureStore(root, connection_factory=factory)
    try:
        await store.start()
        yield store
    finally:
        await store.stop()
        if factory is not None:
            await factory.close_all()


async def _add(ledger: ProcedureChallengeLedger, **overrides: Any) -> ChallengeRecord:
    arguments: dict[str, Any] = {
        "challenger_id": "c1",
        "champion_id": "champ",
        "used_episode_ids": ["e1", "e2"],
        "held_out_episode_ids": ["e3"],
        "context_episode_ids": ["e1", "e3"],
        "optimizer_tier": "deep",
        "optimizer_model": "model-x",
        **overrides,
    }
    return await ledger.add_challenger(**arguments)


async def _compare(ledger: ProcedureChallengeLedger, **overrides: Any) -> None:
    arguments: dict[str, Any] = {
        "challenger_id": "c1",
        "champion_id": "champ",
        "episode_id": "e1",
        "split": "used",
        "first_shown": "champion",
        "outcome": "challenger",
        "counted": True,
        "judgements": [],
        **overrides,
    }
    await ledger.record_comparison(**arguments)


def _procedure(procedure_id: str = "proc-1") -> Procedure:
    return Procedure(
        id=procedure_id,
        name="Read the log tail",
        description="Read the log tail and report errors",
        steps=[ProcedureStep(step_number=1, action="Read the log tail")],
        intent_types=["read"],
        extraction_date=1_000.0,
    )


# Every public coroutine method but ``start``, called with valid arguments: when one of them
# refuses, it is because of the ledger's state and not because of what it was given.
_LEDGER_CALLS: dict[str, Callable[[ProcedureChallengeLedger], Awaitable[Any]]] = {
    "add_challenger": lambda ledger: _add(ledger),
    "get": lambda ledger: ledger.get("c1"),
    "list_by_status": lambda ledger: ledger.list_by_status("pending"),
    "pending_count": lambda ledger: ledger.pending_count("champ"),
    "record_comparison": lambda ledger: _compare(ledger),
    "comparisons": lambda ledger: ledger.comparisons("c1"),
    "set_status": lambda ledger: ledger.set_status("c1", "retired", reason="r", expected=["pending"]),
    "increment_cycles": lambda ledger: ledger.increment_cycles("c1"),
    "record_cycle": lambda ledger: ledger.record_cycle(
        judge_calls=1, comparisons=1, deferred=0, promoted=0, retired=0,
    ),
    "recent_cycles": lambda ledger: ledger.recent_cycles(),
}


def _public_coroutine_methods() -> set[str]:
    return {
        name
        for name, _ in inspect.getmembers(ProcedureChallengeLedger, inspect.iscoroutinefunction)
        if not name.startswith("_")
    }


async def _methods_that_did_not_refuse(ledger: ProcedureChallengeLedger) -> list[str]:
    """The methods that did not raise ``RuntimeError`` when called, with what they did instead."""
    survivors: list[str] = []
    for name, call in _LEDGER_CALLS.items():
        try:
            await call(ledger)
        except RuntimeError:
            continue
        except Exception as error:  # refused, but not the way the ledger promises
            survivors.append(f"{name} raised {type(error).__name__} instead of RuntimeError")
        else:
            survivors.append(f"{name} did not raise")
    return survivors


async def _is_closed(connection: Any) -> bool:
    """Whether ``connection`` refuses a statement: aiosqlite says "no active connection", sqlite3 "closed database"."""
    try:
        await connection.execute("SELECT 1")
    except (ValueError, sqlite3.ProgrammingError):
        return True
    return False


def _worker_threads_since(before: frozenset[threading.Thread]) -> list[str]:
    return sorted(
        thread.name
        for thread in threading.enumerate()
        if thread not in before and "_connection_worker_thread" in thread.name
    )


async def _settled_worker_threads(
    before: frozenset[threading.Thread], *, expected: int, timeout: float = 10.0,
) -> list[str]:
    """The aiosqlite worker threads started since ``before`` that are alive, once ``expected`` are or ``timeout`` ends.

    A closed connection's worker thread ends a moment after ``close()`` returns, so the count is
    polled rather than read once.
    """
    deadline = time.monotonic() + timeout
    while True:
        alive = _worker_threads_since(before)
        if len(alive) == expected or time.monotonic() >= deadline:
            return alive
        await asyncio.sleep(0.02)


# ---------------------------------------------------------------------------
# start / detach / constructor
# ---------------------------------------------------------------------------


async def test_start_creates_its_tables_in_its_own_file(tmp_path: Path) -> None:
    path = tmp_path / "procedures_challenges.db"
    connection = await default_factory.connect(str(path))
    try:
        await ProcedureChallengeLedger(connection).start()
        cursor = await connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = sorted(row[0] for row in await cursor.fetchall())
    finally:
        await connection.close()

    assert tables == ["procedure_challenge_cycles", "procedure_challenges", "procedure_comparisons"]
    assert path.exists()
    assert not (tmp_path / "procedures.db").exists()  # nothing was put in the store's file


async def test_start_failure_propagates_and_leaves_the_connection_to_its_owner() -> None:
    failure = sqlite3.OperationalError("disk I/O error")
    connection = _FailingScriptConnection(failure)
    ledger = ProcedureChallengeLedger(connection)

    with pytest.raises(sqlite3.OperationalError) as raised:
        await ledger.start()

    assert raised.value is failure
    assert "executescript" in connection.calls  # premise: the schema step is what failed
    assert "close" not in connection.calls  # the owner closes it, not the ledger
    assert await _methods_that_did_not_refuse(ledger) == []  # and the ledger never started


def test_constructor_refuses_a_missing_connection() -> None:
    with pytest.raises(ValueError, match="procedure_challenge_connection_missing"):
        ProcedureChallengeLedger(None)  # type: ignore[arg-type]


async def test_methods_refuse_before_start_and_after_detach(tmp_path: Path) -> None:
    assert set(_LEDGER_CALLS) == _public_coroutine_methods() - {"start"}  # the table covers every method
    connection = await default_factory.connect(str(tmp_path / "procedures_challenges.db"))
    try:
        ledger = ProcedureChallengeLedger(connection)
        assert await _methods_that_did_not_refuse(ledger) == []  # before start

        await ledger.start()
        assert await ledger.pending_count("champ") == 0  # premise: started, it answers
        ledger.detach()
        assert await _methods_that_did_not_refuse(ledger) == []  # after detach

        cursor = await connection.execute("SELECT 1")  # detach left the connection open
        assert await cursor.fetchone() == (1,)
    finally:
        await connection.close()


# ---------------------------------------------------------------------------
# add_challenger / get
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param(
            {
                "challenger_id": "c1",
                "champion_id": "champ",
                "used_episode_ids": ["e1", "e2"],
                "held_out_episode_ids": ["e3"],
                "context_episode_ids": ["e1", "e3"],
                "optimizer_tier": "deep",
                "optimizer_model": "model-x",
            },
            id="typical",
        ),
        pytest.param(
            {
                "challenger_id": "c" * 128,
                "champion_id": "p" * 128,
                "used_episode_ids": [f"u{index}" for index in range(20)],
                "held_out_episode_ids": [f"h{index}" for index in range(20)],
                "context_episode_ids": [f"u{index}" for index in range(20)],
                "optimizer_tier": "t" * 128,
                "optimizer_model": "m" * 256,
            },
            id="every-field-at-its-bound",
        ),
        pytest.param(
            {
                "challenger_id": "c1",
                "champion_id": "champ",
                "used_episode_ids": (),
                "held_out_episode_ids": (),
                "context_episode_ids": (),
            },
            id="no-episodes-and-no-optimizer",
        ),
    ],
)
async def test_add_challenger_round_trips(
    ledger: ProcedureChallengeLedger, clock: _Clock, fields: dict[str, Any],
) -> None:
    clock.now = 1_234.5

    record = await ledger.add_challenger(**fields)
    stored = await ledger.get(fields["challenger_id"])

    expected = ChallengeRecord(
        challenger_id=fields["challenger_id"],
        champion_id=fields["champion_id"],
        status="pending",
        created_at=1_234.5,
        cycles_pending=0,
        used_episode_ids=tuple(fields["used_episode_ids"]),
        held_out_episode_ids=tuple(fields["held_out_episode_ids"]),
        context_episode_ids=tuple(fields["context_episode_ids"]),
        optimizer_tier=fields.get("optimizer_tier", ""),
        optimizer_model=fields.get("optimizer_model", ""),
        decision_reason="",
        decided_at=0.0,
    )
    assert record == expected
    assert stored == expected  # every field survives the trip through the file
    assert await ledger.get("no-such-challenger") is None


def _rejected(overrides: dict[str, Any], message: str, case: str) -> Any:
    return pytest.param(overrides, ValueError, message, False, id=case)


_CHALLENGER_ID = "procedure_challenge_challenger_id_invalid"
_CHAMPION_ID = "procedure_challenge_champion_id_invalid"
_EPISODE_IDS = "procedure_challenge_episode_ids_invalid"


@pytest.mark.parametrize(
    ("overrides", "error", "message", "already_recorded"),
    [
        _rejected({"challenger_id": ""}, _CHALLENGER_ID, "empty-challenger-id"),
        _rejected({"champion_id": ""}, _CHAMPION_ID, "empty-champion-id"),
        _rejected({"challenger_id": "c\x001"}, _CHALLENGER_ID, "nul-in-challenger-id"),
        _rejected({"champion_id": "ch\x00amp"}, _CHAMPION_ID, "nul-in-champion-id"),
        _rejected({"challenger_id": "x" * 129}, _CHALLENGER_ID, "challenger-id-of-129-characters"),
        _rejected({"champion_id": "x" * 129}, _CHAMPION_ID, "champion-id-of-129-characters"),
        _rejected({"challenger_id": "c\ud8001"}, _CHALLENGER_ID, "lone-surrogate-in-challenger-id"),
        _rejected({"challenger_id": None}, _CHALLENGER_ID, "none-challenger-id"),
        _rejected({"challenger_id": "champ"}, "procedure_challenge_self_challenge", "self-challenge"),
        _rejected(
            {
                "used_episode_ids": ["e1", "e2"],
                "held_out_episode_ids": ["e2", "e3"],
                "context_episode_ids": ["e1"],
            },
            _EPISODE_IDS,
            "used-and-held-out-overlap",
        ),
        _rejected({"context_episode_ids": ["e9"]}, _EPISODE_IDS, "context-outside-used-and-held-out"),
        _rejected(
            {
                "used_episode_ids": [f"e{index}" for index in range(21)],
                "held_out_episode_ids": [],
                "context_episode_ids": [],
            },
            _EPISODE_IDS,
            "21-episode-ids",
        ),
        _rejected({"used_episode_ids": ["e1", "e1"]}, _EPISODE_IDS, "duplicate-episode-id"),
        _rejected({"used_episode_ids": ["e1", ""]}, _EPISODE_IDS, "empty-episode-id"),
        _rejected({"held_out_episode_ids": ["e\ud8003"]}, _EPISODE_IDS, "lone-surrogate-in-episode-id"),
        _rejected({"used_episode_ids": [1, 2]}, _EPISODE_IDS, "non-str-episode-ids"),
        _rejected({"used_episode_ids": "e1"}, _EPISODE_IDS, "bare-str-for-used"),
        _rejected({"held_out_episode_ids": "e3"}, _EPISODE_IDS, "bare-str-for-held-out"),
        _rejected({"context_episode_ids": "e1"}, _EPISODE_IDS, "bare-str-for-context"),
        _rejected({"used_episode_ids": None}, _EPISODE_IDS, "none-for-used"),
        pytest.param(
            {}, sqlite3.IntegrityError, "UNIQUE constraint failed", True, id="duplicate-challenger",
        ),
    ],
)
async def test_add_challenger_rejects_bad_ids(
    ledger: ProcedureChallengeLedger,
    overrides: dict[str, Any],
    error: type[Exception],
    message: str,
    already_recorded: bool,
) -> None:
    if already_recorded:
        await _add(ledger)

    with pytest.raises(error, match=message):
        await _add(ledger, **overrides)

    # Nothing new was recorded: the refusal came before the insert, or the insert did not happen.
    assert len(await ledger.list_by_status("pending")) == (1 if already_recorded else 0)


async def test_add_challenger_bounds_the_optimizer_fields(ledger: ProcedureChallengeLedger) -> None:
    """Unlike an id, an optimizer tier or model is cut to its bound, never refused."""
    record = await _add(
        ledger,
        optimizer_tier="t\x00" + "t" * 300,
        optimizer_model="m" * 300 + "\ud800",
    )

    stored = await ledger.get("c1")
    assert stored == record
    assert stored.optimizer_tier == "t" * 128
    assert stored.optimizer_model == "m" * 256


async def test_add_challenger_enforces_the_pending_cap_atomically(
    ledger: ProcedureChallengeLedger, clock: _Clock,
) -> None:
    """R1 (F5): counting a champion's open challengers and inserting the new one happen under one lock.

    Two overlapping submits for one champion with room for one: exactly one is admitted. The other is
    recorded ``retired`` rather than refused, so the inactive procedure row it names stays accounted for.
    """
    first, second = await asyncio.gather(
        _add(ledger, challenger_id="c1", max_pending=1),
        _add(ledger, challenger_id="c2", max_pending=1),
    )

    assert sorted((first.status, second.status)) == ["pending", "retired"]
    admitted, refused = (first, second) if first.status == "pending" else (second, first)
    assert (admitted.decision_reason, admitted.decided_at) == ("", 0.0)
    assert refused.decision_reason.startswith("pending_limit:")
    assert refused.decided_at > 0
    assert await ledger.get(admitted.challenger_id) == admitted  # the returned records are the stored rows
    assert await ledger.get(refused.challenger_id) == refused
    assert await ledger.pending_count("champ") == 1  # the retired row is not an open challenger

    # A promoting challenger still holds its slot.
    assert await ledger.set_status(
        admitted.challenger_id, "promoting", reason="claimed", expected=["pending"],
    ) is True
    third = await _add(ledger, challenger_id="c3", max_pending=1)
    assert third.status == "retired"
    assert third.decision_reason.startswith("pending_limit:")
    assert await ledger.pending_count("champ") == 1

    # Another champion's cap is its own.
    other = await _add(ledger, challenger_id="c4", champion_id="other", max_pending=1)
    assert other.status == "pending"
    assert await ledger.pending_count("other") == 1

    # Without max_pending nothing is capped: what the existing callers get.
    uncapped = [await _add(ledger, challenger_id=f"u{index}") for index in range(3)]
    assert [record.status for record in uncapped] == ["pending"] * 3
    assert await ledger.pending_count("champ") == 4  # the promoting one and the three uncapped


@pytest.mark.parametrize(
    "max_pending",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(True, id="bool-is-not-an-int"),
        pytest.param(1.5, id="float"),
    ],
)
async def test_add_challenger_rejects_a_bad_cap(ledger: ProcedureChallengeLedger, max_pending: Any) -> None:
    """R1 (F5): a cap that is not a positive ``int`` is refused before anything is written."""
    with pytest.raises(ValueError, match="procedure_challenge_max_pending_invalid"):
        await _add(ledger, max_pending=max_pending)

    assert await ledger.get("c1") is None  # nothing was recorded, not even a retired row
    for status in ("pending", "promoting", "promoted", "retired"):
        assert await ledger.list_by_status(status) == []
    # The same call with a valid cap is accepted: it was the cap that was refused.
    assert (await _add(ledger, max_pending=1)).status == "pending"


# ---------------------------------------------------------------------------
# set_status / list_by_status / pending_count
# ---------------------------------------------------------------------------


async def test_set_status_is_conditional_on_expected(
    ledger: ProcedureChallengeLedger, clock: _Clock,
) -> None:
    await _add(ledger)
    clock.now = 2_000.0
    assert await ledger.set_status("c1", "retired", reason="not better", expected=["pending"]) is True
    retired = await ledger.get("c1")
    assert (retired.status, retired.decision_reason, retired.decided_at) == ("retired", "not better", 2_000.0)

    clock.now = 3_000.0
    assert await ledger.set_status("c1", "promoted", reason="too late", expected=["pending"]) is False
    assert await ledger.get("c1") == retired  # the refused move wrote nothing: status, reason, time

    # Any of several expected statuses will do, and a challenger that does not exist is in none of them.
    await _add(ledger, challenger_id="c2")
    assert await ledger.set_status("c2", "promoting", reason="claimed", expected=["pending"]) is True
    assert await ledger.set_status("c2", "promoted", reason="done", expected=("pending", "promoting")) is True
    assert (await ledger.get("c2")).status == "promoted"
    assert await ledger.set_status("missing", "retired", reason="r", expected=["pending"]) is False

    # An unknown status, an unknown expected status and an empty expected list are refused outright.
    await _add(ledger, challenger_id="c3")
    refused = []
    for status, expected in (("bogus", ["pending"]), ("retired", ["bogus"]), ("retired", [])):
        with pytest.raises(ValueError, match="procedure_challenge_status_invalid"):
            await ledger.set_status("c3", status, reason="r", expected=expected)  # type: ignore[arg-type]
        refused.append((await ledger.get("c3")).status)
    assert refused == ["pending", "pending", "pending"]  # and none of them moved the challenger


async def test_set_status_stores_a_bounded_decision_reason(ledger: ProcedureChallengeLedger) -> None:
    await _add(ledger)
    reason = "a\x00b\ud800" + "c" * 2 * 1000

    assert await ledger.set_status("c1", "retired", reason=reason, expected=["pending"]) is True

    stored = (await ledger.get("c1")).decision_reason
    assert stored == ("ab?" + "c" * 1000)[:1000]  # the contract's bound, not the module's constant
    stored.encode("utf-8")  # strict: a lone surrogate would raise


async def test_list_by_status_orders_by_created_then_id(
    ledger: ProcedureChallengeLedger, clock: _Clock,
) -> None:
    # Inserted c, a, b, z: the order of creation is neither the id order nor the row order.
    for challenger_id, created_at in (("c", 10.0), ("a", 10.0), ("b", 5.0), ("z", 1.0)):
        clock.now = created_at
        await _add(ledger, challenger_id=challenger_id)
    clock.now = 99.0
    assert await ledger.set_status("z", "retired", reason="r", expected=["pending"]) is True

    assert [r.challenger_id for r in await ledger.list_by_status("pending")] == ["b", "a", "c"]
    assert [r.challenger_id for r in await ledger.list_by_status("retired")] == ["z"]
    assert await ledger.list_by_status("promoted") == []


async def test_list_by_status_refuses_an_unknown_status(ledger: ProcedureChallengeLedger) -> None:
    with pytest.raises(ValueError, match="procedure_challenge_status_invalid"):
        await ledger.list_by_status("bogus")  # type: ignore[arg-type]


async def test_pending_count_counts_pending_and_promoting_only(ledger: ProcedureChallengeLedger) -> None:
    for challenger_id in ("pending", "promoting", "promoted", "retired"):
        await _add(ledger, challenger_id=challenger_id)
    await _add(ledger, challenger_id="of-another-champion", champion_id="other")
    for status in ("promoting", "promoted", "retired"):
        assert await ledger.set_status(status, status, reason="r", expected=["pending"]) is True

    assert await ledger.pending_count("champ") == 2  # the pending one and the promoting one
    assert await ledger.pending_count("other") == 1
    assert await ledger.pending_count("nobody") == 0


# ---------------------------------------------------------------------------
# record_comparison / comparisons
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"split": "train"}, id="unknown-split"),
        pytest.param({"split": ""}, id="empty-split"),
        pytest.param({"first_shown": "both"}, id="unknown-first-shown"),
        pytest.param({"first_shown": "tie"}, id="an-outcome-is-not-a-side"),
        pytest.param({"outcome": "win"}, id="unknown-outcome"),
        pytest.param({"outcome": "invalid", "counted": True}, id="an-invalid-outcome-is-never-counted"),
        pytest.param({"counted": 1}, id="counted-is-a-bool-not-an-int"),
        pytest.param({"counted": "yes"}, id="counted-is-a-bool-not-a-str"),
        pytest.param({"counted": None}, id="counted-is-a-bool-not-none"),
    ],
)
async def test_record_comparison_validates_enums_and_never_counts_invalid(
    ledger: ProcedureChallengeLedger, overrides: dict[str, Any],
) -> None:
    await _add(ledger)

    with pytest.raises(ValueError, match="procedure_comparison_invalid"):
        await _compare(ledger, **overrides)

    assert await ledger.comparisons("c1") == []  # nothing was recorded


async def test_record_comparison_stores_every_valid_combination(ledger: ProcedureChallengeLedger) -> None:
    """The positive control of the validation test: every valid value is accepted and read back as given."""
    await _add(ledger)
    combinations = [
        (split, first_shown, outcome, counted)
        for split in ("used", "held_out")
        for first_shown in ("champion", "challenger")
        for outcome in ("champion", "challenger", "tie", "invalid")
        for counted in (True, False)
        if not (outcome == "invalid" and counted)  # the one combination that is refused
    ]
    for index, (split, first_shown, outcome, counted) in enumerate(combinations):
        await _compare(
            ledger, episode_id=f"e{index}", split=split, first_shown=first_shown, outcome=outcome, counted=counted,
        )

    stored = await ledger.comparisons("c1")
    assert [(r.split, r.first_shown, r.outcome, r.counted) for r in stored] == combinations
    assert all(type(r.counted) is bool for r in stored)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"challenger_id": ""}, id="empty-challenger-id"),
        pytest.param({"champion_id": "ch\x00amp"}, id="nul-in-champion-id"),
        pytest.param({"episode_id": "e" * 129}, id="episode-id-of-129-characters"),
        pytest.param({"episode_id": "e\ud8001"}, id="lone-surrogate-in-episode-id"),
    ],
)
async def test_record_comparison_refuses_bad_ids(
    ledger: ProcedureChallengeLedger, overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="procedure_challenge_.*_invalid"):
        await _compare(ledger, **overrides)

    assert await ledger.comparisons("c1") == []


async def test_record_comparison_persists_bounded_reason_with_surrogate_and_nul(
    ledger: ProcedureChallengeLedger,
) -> None:
    # What a provider's JSON can hand back: json.loads lets a lone surrogate escape through.
    raw_reason = json.loads('"a\\ud800b\\u0000c"')
    assert "\ud800" in raw_reason and "\x00" in raw_reason  # premise: it carries both
    reason = bounded_text(raw_reason, MAX_DECISION_CHARS)
    judgements = [
        {"order": "champion_first", "winner": "challenger", "reason": reason, "model": "judge-a", "tier": "standard"},
        {"order": "challenger_first", "winner": "challenger", "reason": "plain", "model": "judge-a", "tier": "standard"},
    ]
    await _add(ledger)

    await _compare(ledger, judgements=judgements)

    (record,) = await ledger.comparisons("c1")
    assert list(record.judgements) == judgements  # round-trips
    assert record.judgements[0]["reason"] == "a?bc"  # NUL removed, surrogate replaced
    assert json.dumps(record.judgements, ensure_ascii=False).encode("utf-8")  # strict encode succeeds


def _judgements_of_payload_bytes(size: int) -> list[dict[str, str]]:
    """One judgement whose JSON payload, as ``record_comparison`` builds it, is exactly ``size`` UTF-8 bytes."""
    overhead = len(json.dumps([{"reason": ""}], ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return [{"reason": "x" * (size - overhead)}]


@pytest.mark.parametrize(
    "judgements",
    [
        pytest.param([{"reason": "a\ud800b"}], id="raw-lone-surrogate"),
        pytest.param([{"reason": "x" * 9 * 1024}], id="9-KB-of-ascii"),
        pytest.param(_judgements_of_payload_bytes(8192 + 1), id="one-byte-over-the-bound"),
        pytest.param([{"reason": "é" * 4100}], id="multibyte-text-is-counted-in-bytes-not-characters"),
    ],
)
async def test_record_comparison_rejects_unencodable_or_oversized_judgements(
    ledger: ProcedureChallengeLedger, judgements: list[dict[str, str]],
) -> None:
    with pytest.raises(ValueError):
        await _compare(ledger, judgements=judgements)

    assert await ledger.comparisons("c1") == []


async def test_record_comparison_accepts_judgements_at_exactly_the_byte_bound(
    ledger: ProcedureChallengeLedger,
) -> None:
    """The positive control of the size test: the bound itself is allowed, one byte more is not."""
    judgements = _judgements_of_payload_bytes(8192)

    await _compare(ledger, judgements=judgements)

    (record,) = await ledger.comparisons("c1")
    assert list(record.judgements) == judgements


async def test_retired_challenger_keeps_its_comparisons(ledger: ProcedureChallengeLedger) -> None:
    await _add(ledger)
    for episode_id in ("e1", "e2"):
        await _compare(
            ledger, episode_id=episode_id, judgements=[{"order": "champion_first", "reason": f"{episode_id} reason"}],
        )
    before = await ledger.comparisons("c1")
    assert len(before) == 2

    assert await ledger.set_status("c1", "retired", reason="expired", expected=["pending"]) is True

    assert await ledger.comparisons("c1") == before  # both rows, both reasons, in the same order
    retired = await ledger.get("c1")
    assert (retired.status, retired.decision_reason) == ("retired", "expired")


# ---------------------------------------------------------------------------
# increment_cycles / record_cycle / recent_cycles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["promoting", "promoted", "retired"])
async def test_increment_cycles_only_moves_pending(ledger: ProcedureChallengeLedger, status: str) -> None:
    await _add(ledger)
    assert await ledger.increment_cycles("c1") == 1
    assert await ledger.increment_cycles("c1") == 2

    assert await ledger.set_status("c1", status, reason="decided", expected=["pending"]) is True  # type: ignore[arg-type]

    assert await ledger.increment_cycles("c1") == 2  # the stored value, not moved
    assert (await ledger.get("c1")).cycles_pending == 2
    assert await ledger.increment_cycles("no-such-challenger") == 0


async def test_record_cycle_and_recent_cycles(ledger: ProcedureChallengeLedger, clock: _Clock) -> None:
    assert await ledger.recent_cycles() == []
    cycles = [
        (100.0, {"judge_calls": 1, "comparisons": 2, "deferred": 1, "promoted": 0, "retired": 0}),
        (200.0, {"judge_calls": 2, "comparisons": 4, "deferred": 0, "promoted": 0, "retired": 1}),
        (300.0, {"judge_calls": 3, "comparisons": 6, "deferred": 1, "promoted": 1, "retired": 2}),
    ]
    for recorded_at, counts in cycles:
        clock.now = recorded_at
        await ledger.record_cycle(**counts)

    newest_first = [{"recorded_at": recorded_at, **counts} for recorded_at, counts in reversed(cycles)]
    assert await ledger.recent_cycles() == newest_first
    assert await ledger.recent_cycles(limit=2) == newest_first[:2]
    assert await ledger.recent_cycles(limit=0) == newest_first[:1]  # a limit below one still returns one row

    # A negative count and anything that is not exactly an int is refused, and none of it is recorded.
    survivors = []
    for field in ("judge_calls", "comparisons", "deferred", "promoted", "retired"):
        for bad in (-1, 1.5, "2", None, True):
            counts = {"judge_calls": 0, "comparisons": 0, "deferred": 0, "promoted": 0, "retired": 0, field: bad}
            try:
                await ledger.record_cycle(**counts)  # type: ignore[arg-type]
            except ValueError:
                continue
            survivors.append((field, bad))
    assert survivors == []
    assert len(await ledger.recent_cycles()) == 3


# ---------------------------------------------------------------------------
# the module itself
# ---------------------------------------------------------------------------


def test_ledger_module_issues_no_delete() -> None:
    """D6: no method of the ledger deletes, so a retired challenger keeps its evidence.

    A raw scan of the module's source text, on purpose: a DELETE in any string, f-string or helper
    is found without parsing anything.
    """
    source = Path(procedure_challenges.__file__).read_text(encoding="utf-8")

    offending = [number for number, line in enumerate(source.splitlines(), 1) if "DELETE" in line]
    assert "DELETE" not in source, f"procedure_challenges.py contains DELETE on line(s) {offending}"


@pytest.mark.parametrize(
    ("value", "limit", "expected"),
    [
        pytest.param("a\x00b\x00", 10, "ab", id="nul-removed"),
        pytest.param("a\ud800b", 10, "a?b", id="lone-surrogate-replaced"),
        pytest.param("\ud800\udc00", 10, "??", id="a-split-surrogate-pair-is-two-lone-surrogates"),
        pytest.param("abcdef", 3, "abc", id="cut-to-the-limit"),
        pytest.param("abc", 3, "abc", id="exactly-the-limit-is-kept"),
        pytest.param("a\x00bcdef", 3, "abc", id="nul-removed-before-the-cut"),
        pytest.param("\ud800\ud800", 1, "?", id="surrogate-replaced-before-the-cut"),
        pytest.param("é😀x", 2, "é😀", id="the-limit-counts-characters-not-bytes"),
        pytest.param("", 5, "", id="empty-string"),
        pytest.param(None, 5, "", id="none"),
        pytest.param(5, 5, "", id="int"),
        pytest.param(b"abc", 5, "", id="bytes"),
        pytest.param(_StrSubclass("abc"), 5, "", id="str-subclass"),
        pytest.param("abc", 0, "", id="limit-zero"),
        pytest.param("abcdef", -2, "", id="negative-limit"),
    ],
)
def test_bounded_text_removes_nul_replaces_surrogate_and_cuts(value: object, limit: int, expected: str) -> None:
    cleaned = bounded_text(value, limit)

    assert cleaned == expected
    assert type(cleaned) is str
    cleaned.encode("utf-8")  # strict: a lone surrogate would raise


# ---------------------------------------------------------------------------
# ProcedureStore owns the ledger's connection (D1, D1b)
# ---------------------------------------------------------------------------


async def test_procedure_store_opens_the_ledger_beside_procedures_db(tmp_path: Path) -> None:
    root = tmp_path / "procedures"

    async with _running_store(root) as store:
        assert isinstance(store.challenges, ProcedureChallengeLedger)
        assert (root / "procedures_challenges.db").exists()
        assert (root / "procedures.db").exists()
        assert await store.challenges.pending_count("champ") == 0  # started, not merely built


async def test_procedure_store_opens_the_ledger_on_its_own_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class _RecordingLedger(ProcedureChallengeLedger):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            constructed.append((args, kwargs))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(procedure_challenges, "ProcedureChallengeLedger", _RecordingLedger)
    factory = _RecordingFactory()

    async with _running_store(tmp_path / "procedures", factory) as store:
        paths = [path for path, _ in factory.connected]
        assert len(paths) == 2 and len(set(paths)) == 2  # exactly two connects, on distinct paths
        assert sum(path.endswith("procedures.db") for path in paths) == 1
        assert sum(path.endswith("procedures_challenges.db") for path in paths) == 1
        # The ledger got the connection the STORE's factory opened, and nothing else: no factory of its own.
        assert constructed == [((factory.connection_for("procedures_challenges.db"),), {})]
        assert isinstance(store.challenges, _RecordingLedger)

    assert not any("factory" in name for name in inspect.signature(ProcedureChallengeLedger.__init__).parameters)


async def test_procedure_store_stop_closes_the_ledger(tmp_path: Path) -> None:
    factory = _RecordingFactory()

    async with _running_store(tmp_path / "procedures", factory) as store:
        old_ledger = store.challenges
        assert old_ledger is not None
        ledger_connection = factory.connection_for("procedures_challenges.db")
        assert not await _is_closed(ledger_connection)  # premise: open until the store stops

        await store.stop()

        assert store.challenges is None
        assert vars(store)["_challenges_db"] is None  # test-side read: the closed connection is not kept for a second close
        with pytest.raises(RuntimeError):
            await old_ledger.pending_count("champ")
        assert await _is_closed(ledger_connection)  # a further execute raises


async def test_ledger_start_failure_leaves_the_store_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    async def failing_start(self: ProcedureChallengeLedger) -> None:
        raise sqlite3.OperationalError("simulated schema failure")

    monkeypatch.setattr(ProcedureChallengeLedger, "start", failing_start)
    factory = _RecordingFactory()
    before = frozenset(threading.enumerate())

    with caplog.at_level(logging.WARNING):
        async with _running_store(tmp_path / "procedures", factory) as store:  # start() succeeds
            warnings = [
                record for record in caplog.records
                if record.levelno == logging.WARNING and "AD-1326" in record.getMessage()
            ]
            assert store.challenges is None
            assert vars(store)["_challenges_db"] is None  # test-side read: the store holds no connection
            assert await _is_closed(factory.connection_for("procedures_challenges.db"))  # and it was closed
            assert len(warnings) == 1
            # Only the store's own connection is left: the ledger's worker thread has ended.
            assert len(await _settled_worker_threads(before, expected=1)) == 1
            # The store keeps working without its ledger.
            await store.save(_procedure())
            assert (await store.get("proc-1")).id == "proc-1"

    assert await _settled_worker_threads(before, expected=0) == []


async def test_last_resort_close_reaches_the_ledger_connection(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    # The helpers under test, imported test-side: BF-882's last-resort close of a rollback whose
    # component's stop() failed and is never called again.
    from probos.startup.shutdown import _direct_connections, _RollbackSteps

    before = frozenset(threading.enumerate())  # taken before store.start()
    store = ProcedureStore(tmp_path / "procedures")
    try:
        await store.start()
        assert store.challenges is not None  # premise: the ledger is open
        assert len(await _settled_worker_threads(before, expected=2)) == 2  # premise: two worker threads

        closable, raw = _direct_connections(store)
        assert {name for name, _ in closable} == {"_db", "_challenges_db"}
        assert raw == []
        connections = dict(closable)

        # As in a rollback whose store.stop() raised before any cleanup: stop() is never called.
        steps = _RollbackSteps(rollback=True)
        steps.keep_failed("procedure store stop", store)
        with caplog.at_level(logging.WARNING):
            await steps.settle_failed()

        for name, connection in connections.items():
            assert await _is_closed(connection), f"{name} was left open by the last-resort close"
        assert await _settled_worker_threads(before, expected=0) == []
        messages = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
        assert any(
            message.startswith("BF-882: last-resort close of ProcedureStore._challenges_db ")
            for message in messages
        ), messages
    finally:
        await store.stop()  # the Chroma client is not a connection; the closed ones are left alone


async def test_challenger_survives_a_store_restart(tmp_path: Path) -> None:
    """The whole chain: store start, ledger write, store stop, a new store on the same directory, read."""
    root = tmp_path / "procedures"
    async with _running_store(root) as first:
        await first.challenges.add_challenger(
            challenger_id="c1", champion_id="champ",
            used_episode_ids=["e1"], held_out_episode_ids=["e2"], context_episode_ids=["e1"],
        )
        await first.challenges.record_comparison(
            challenger_id="c1", champion_id="champ", episode_id="e1", split="used",
            first_shown="champion", outcome="challenger", counted=True, judgements=[{"reason": "better"}],
        )

    async with _running_store(root) as second:
        record = await second.challenges.get("c1")
        assert record is not None
        assert (record.champion_id, record.status) == ("champ", "pending")
        (comparison,) = await second.challenges.comparisons("c1")
        assert comparison.judgements == ({"reason": "better"},)


async def test_backup_copies_the_ledger_after_procedures_db(tmp_path: Path) -> None:
    """R2 (R2-3): the hot backup copies databases in ``discover`` order, so the ledger must sort after procedures.db.

    A ledger copied first can be older than ``procedures.db``, the one pairing that holds a pending row beside an
    active challenger. The first file name, ``procedure_challenges.db``, sorted before ``procedures.db`` (``_`` is
    0x5F, ``s`` is 0x73); ``procedures_challenges.db`` sorts after it (``.`` is 0x2E, ``_`` is 0x5F).
    """
    data_dir = tmp_path / "data"
    async with _running_store(data_dir / "procedures"):
        pass  # a real store, started and stopped: the files a snapshot finds on disk

    # As tests/test_ad1265_backup_coverage.py does: the real inventory over the real files.
    discovered = discover([BackupRoot("data", data_dir)], backup_root=data_dir / "backups")

    relative_paths = [str(entry.relative_path) for entry in discovered]
    assert "procedures/procedures.db" in relative_paths  # premise: the store's real files are found at all
    assert "procedures/procedures_challenges.db" in relative_paths
    assert relative_paths.index("procedures/procedures.db") < relative_paths.index(
        "procedures/procedures_challenges.db"
    )
    declaration = load_default_store_registry().get("cognitive.procedure-challenges")
    assert declaration is not None  # premise: the ledger is declared
    assert declaration.canonical_path == "procedures/procedures_challenges.db"


# ---------------------------------------------------------------------------
# ProcedureStore.sync_routing_index (R1, F1)
# ---------------------------------------------------------------------------


@pytest.fixture
def deterministic_embeddings(monkeypatch: pytest.MonkeyPatch) -> BF662EmbeddingFunctionA:
    """The semantic index opens without a model: a store builds it on a deterministic embedding backend.

    The three lookups ``ProcedureStore._init_chroma`` makes are replaced on ``probos.knowledge.embeddings``,
    as ``tests/test_procedure_store.py`` does, and put back when the test ends.
    """
    function = BF662EmbeddingFunctionA()
    backend_id = embeddings.get_embedding_backend_id(function)
    monkeypatch.setattr(embeddings, "get_collection_embedding_function", lambda: function)
    monkeypatch.setattr(embeddings, "get_active_embedding_model_name", lambda: function.name())
    monkeypatch.setattr(embeddings, "get_active_embedding_backend_id", lambda: backend_id)
    return function


class _FailingWrite:
    """Stands in for a Chroma collection write: records the keyword arguments of each call, then raises."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        raise RuntimeError("simulated semantic index failure")


def _live_collection(store: ProcedureStore) -> Any:
    """The store's open Chroma collection: a test-side read, because the tests patch this very object."""
    collection = vars(store)["_chroma_collection"]
    assert collection is not None, "premise: the semantic index is open"
    return collection


async def _routed_ids(store: ProcedureStore, query: str) -> list[str]:
    """The ids routing gives ``query``: ``find_matching`` reads the semantic index, then the SQLite row."""
    return [match["id"] for match in await store.find_matching(query)]


def _index_says_active(store: ProcedureStore, procedure_id: str) -> bool:
    """What the semantic index itself says about ``procedure_id``: its entry's ``is_active`` (a test-side read).

    Since R2 (section 3g) ``find_matching`` admits a match only through its active SQLite row, so routing no
    longer shows an entry that went stale: the tests that stage one read the live collection's metadata.
    """
    entries = _live_collection(store).get(ids=[procedure_id], include=["metadatas"])["metadatas"]
    assert len(entries) == 1, f"premise: the semantic index holds one entry for {procedure_id}"
    return entries[0]["is_active"]


@pytest.mark.usefixtures("deterministic_embeddings")
async def test_sync_routing_index_rewrites_the_entry_from_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1 (F1): a deactivation whose index update failed leaves the entry active until it is rewritten from SQLite.

    R2 (section 3g): ``find_matching`` no longer routes by a stale entry, so the premise reads the entry itself.
    """
    champion = _procedure("champ")
    async with _running_store(tmp_path / "procedures") as store:
        await store.save(champion)
        collection = _live_collection(store)
        assert await _routed_ids(store, champion.description) == ["champ"]  # premise: it routes while active

        failing_update = _FailingWrite()
        with monkeypatch.context() as patched:
            patched.setattr(collection, "update", failing_update)
            await store.deactivate("champ", superseded_by="challenger")  # swallows the index failure, as before

        # Premises: the index update was attempted and failed, SQLite says inactive, the index entry still says active.
        assert [call["ids"] for call in failing_update.calls] == [["champ"]]
        stored = await store.get("champ")
        assert stored is not None
        assert (stored.is_active, stored.superseded_by) == (False, "challenger")
        assert _index_says_active(store, "champ") is True
        # This line used to assert ``_routed_ids(store, champion.description) == ["champ"]`` ("the pre-existing
        # store behaviour"): that pinned the stale-entry hazard review round 2 found (R2-1), not a contract.
        # ``find_matching`` now admits only a row SQLite says is active (3g), so the entry is read directly; the
        # routing result is pinned by test_find_matching_admits_only_rows_active_in_sqlite.

        assert await store.sync_routing_index("champ") is True

        # Rewritten from the SQLite row, not deleted (the read refuses a missing entry).
        assert _index_says_active(store, "champ") is False
        assert await _routed_ids(store, champion.description) == []


@pytest.mark.usefixtures("deterministic_embeddings")
async def test_find_matching_admits_only_rows_active_in_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R2 (R2-1): SQLite's ``is_active`` decides admission, whatever the semantic index still says.

    A procedure deactivated while its index update failed keeps an active index entry. ``find_matching`` used
    to return it, so a retired challenger kept routing after a failed reconciliation (the reviewer's probe).
    """
    stale, live = _procedure("p-stale"), _procedure("p-live")  # one description: both match the same query
    async with _running_store(tmp_path / "procedures") as store:
        await store.save(stale)
        await store.save(live)
        collection = _live_collection(store)
        # Premise: both match the query while active.
        assert sorted(await _routed_ids(store, stale.description)) == ["p-live", "p-stale"]

        failing_update = _FailingWrite()
        with monkeypatch.context() as patched:
            patched.setattr(collection, "update", failing_update)
            await store.deactivate("p-stale")  # swallows the index failure, as before

        # Premises: the index update was attempted and failed, SQLite says inactive, the entry still says active.
        assert [call["ids"] for call in failing_update.calls] == [["p-stale"]]
        stored = await store.get("p-stale")
        assert stored is not None
        assert stored.is_active is False
        assert _index_says_active(store, "p-stale") is True

        matches = await store.find_matching(stale.description)

        assert [match["id"] for match in matches] == ["p-live"]
        assert list(matches[0]) == [  # the row has the keys, in the order, it had at base
            "id", "name", "evolution_type", "compilation_level", "intent_types", "total_selections",
            "total_applied", "total_completions", "total_fallbacks", "is_negative", "score",
        ]
        # Positive control: once the entry agrees with SQLite the result is the same, so the drop was SQLite's.
        assert await store.sync_routing_index("p-stale") is True
        assert _index_says_active(store, "p-stale") is False
        assert await store.find_matching(stale.description) == matches


@pytest.mark.usefixtures("deterministic_embeddings")
async def test_sync_routing_index_reports_a_failed_index_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """R1 (F1): the index write fails: False (routing may disagree), and the log says why, once."""
    async with _running_store(tmp_path / "procedures") as store:
        await store.save(_procedure("champ"))
        collection = _live_collection(store)
        failing_upsert = _FailingWrite()
        caplog.clear()

        with monkeypatch.context() as patched, caplog.at_level(logging.WARNING):
            patched.setattr(collection, "upsert", failing_upsert)
            synced = await store.sync_routing_index("champ")

        warnings = [
            record for record in caplog.records
            if record.levelno >= logging.WARNING and record.name == ProcedureStore.__module__
        ]
        assert synced is False
        assert [call["ids"] for call in failing_upsert.calls] == [["champ"]]  # the write was tried, once
        assert [(record.levelno, record.funcName) for record in warnings] == [(logging.WARNING, "_save_to_chroma")]
        assert "champ" in warnings[0].getMessage()
        assert "simulated semantic index failure" in warnings[0].getMessage()
        # With the write working again the same call is True: the False came from the write, not the store.
        assert await store.sync_routing_index("champ") is True


@pytest.mark.usefixtures("deterministic_embeddings")
async def test_sync_routing_index_is_true_without_an_index_or_a_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1 (F1): True where routing cannot disagree with SQLite, and nothing is written.

    A store without an index matches nothing, and ``find_matching`` drops an id that has no row.
    """

    async def no_index(self: ProcedureStore) -> None:
        return None

    # A store that runs without a semantic index (what a failed index start leaves).
    no_index_root = tmp_path / "no-index"
    with monkeypatch.context() as patched:
        patched.setattr(ProcedureStore, "_init_chroma", no_index)
        async with _running_store(no_index_root) as store:
            await store.save(_procedure("champ"))
            assert vars(store)["_chroma_collection"] is None  # premise: there is no index
            assert await _routed_ids(store, "Read the log tail and report errors") == []  # so nothing routes
            assert await store.sync_routing_index("champ") is True
            assert vars(store)["_chroma_collection"] is None  # nothing was opened to write to
    assert not (no_index_root / "chroma").exists()  # and no index was created on disk

    # An indexed store asked about an id it has no row for.
    async with _running_store(tmp_path / "indexed") as store:
        await store.save(_procedure("champ"))
        collection = _live_collection(store)
        write = _FailingWrite()
        with monkeypatch.context() as patched:
            patched.setattr(collection, "upsert", write)
            patched.setattr(collection, "update", write)
            assert await store.sync_routing_index("no-such-procedure") is True
        assert write.calls == []  # no write of either kind was attempted
        assert collection.get()["ids"] == ["champ"]  # and the index holds what it held


# ---------------------------------------------------------------------------
# Review round 3 (R3-2): a failed or cancelled ledger write is rolled back
# ---------------------------------------------------------------------------


class _FaultingConnection:
    """A ``DatabaseConnection`` over a real connection: it forwards every call and raises an armed error once.

    ``arm(prefix, error)`` makes the first later call whose text starts with ``prefix`` raise ``error`` instead of
    reaching the real connection, and then disarms. A call's text is its SQL, or ``COMMIT`` for ``commit``. ``fired``
    lists the calls that raised and ``open_at_fault`` whether the real connection held an open transaction at each,
    so a test shows that its injected failure happened, and inside a transaction, before it trusts what follows.
    """

    def __init__(self, real: Any) -> None:
        self.real = real
        self.fired: list[str] = []
        self.open_at_fault: list[bool] = []
        self._armed: list[tuple[str | tuple[str, ...], BaseException]] = []

    def arm(self, prefix: str | tuple[str, ...], error: BaseException) -> None:
        self._armed.append((prefix, error))

    def _reach(self, call: str) -> None:
        for index, (prefix, error) in enumerate(self._armed):
            if call.lstrip().startswith(prefix):
                del self._armed[index]
                self.fired.append(call.lstrip())
                self.open_at_fault.append(self.real.in_transaction)
                raise error

    async def execute(self, sql: str, parameters: Any = ()) -> Any:
        self._reach(sql)
        return await self.real.execute(sql, parameters)

    async def executescript(self, sql_script: str) -> Any:
        return await self.real.executescript(sql_script)

    async def commit(self) -> None:
        self._reach("COMMIT")
        await self.real.commit()

    async def close(self) -> None:
        await self.real.close()


@dataclass
class _FaultableLedger:
    """A started ledger on a ``_FaultingConnection``, and the file it writes (for an independent reader)."""

    ledger: ProcedureChallengeLedger
    connection: _FaultingConnection
    path: Path

    @property
    def in_transaction(self) -> bool:
        """Whether the REAL connection holds an open transaction (the wrapper only forwards to it)."""
        return self.connection.real.in_transaction


@pytest.fixture
async def faultable(tmp_path: Path, clock: _Clock) -> AsyncIterator[_FaultableLedger]:
    """A started ledger on a disarmed ``_FaultingConnection``, holding one ``pending`` challenger (``c1``)."""
    path = tmp_path / "procedures_challenges.db"
    real = await default_factory.connect(str(path))
    try:
        connection = _FaultingConnection(real)
        ledger = ProcedureChallengeLedger(connection, clock=clock)
        await ledger.start()
        await _add(ledger)
        yield _FaultableLedger(ledger, connection, path)
    finally:
        await real.close()


_STATUS_ORDER: tuple[str, ...] = get_args(ChallengeStatus)


def _view(**changes: Any) -> dict[str, Any]:
    """The state the ledger holds when ``faultable`` is ready (one ``pending`` challenger ``c1``), with ``changes``."""
    state: dict[str, Any] = {
        "challenges": [("c1", "pending", 0, "")],
        "by_status": [("pending", "c1")],
        "comparisons": [],
        "cycles": [],
    }
    return {**state, **changes}


async def _ledger_view(ledger: ProcedureChallengeLedger) -> dict[str, Any]:
    """What the ledger's own reads say. They run on the writer's connection, so they also see its open transaction."""
    challenges: list[tuple[Any, ...]] = []
    for challenger_id in ("c1", "c2"):
        record = await ledger.get(challenger_id)
        if record is not None:
            challenges.append((record.challenger_id, record.status, record.cycles_pending, record.decision_reason))
    by_status: list[tuple[str, str]] = []
    for status in _STATUS_ORDER:
        by_status.extend((status, record.challenger_id) for record in await ledger.list_by_status(status))
    return {
        "challenges": challenges,
        "by_status": by_status,
        "comparisons": [(row.episode_id, row.outcome, row.counted) for row in await ledger.comparisons("c1")],
        "cycles": [
            (row["judge_calls"], row["comparisons"], row["deferred"], row["promoted"], row["retired"])
            for row in await ledger.recent_cycles()
        ],
    }


def _file_view(path: Path) -> dict[str, Any]:
    """The same facts as an independent reader of the file sees them: a second connection, so committed rows only."""
    reader = sqlite3.connect(path)
    try:
        challenges = reader.execute(
            "SELECT challenger_id, status, cycles_pending, decision_reason FROM procedure_challenges "
            "WHERE challenger_id IN ('c1', 'c2') ORDER BY challenger_id"
        ).fetchall()
        by_status = [
            (status, row[0])
            for status in _STATUS_ORDER
            for row in reader.execute(
                "SELECT challenger_id FROM procedure_challenges WHERE status = ? ORDER BY created_at, challenger_id",
                (status,),
            ).fetchall()
        ]
        comparisons = [
            (episode_id, outcome, bool(counted))
            for episode_id, outcome, counted in reader.execute(
                "SELECT episode_id, outcome, counted FROM procedure_comparisons "
                "WHERE challenger_id = 'c1' ORDER BY id"
            ).fetchall()
        ]
        cycles = reader.execute(
            "SELECT judge_calls, comparisons, deferred, promoted, retired FROM procedure_challenge_cycles "
            "ORDER BY id DESC"
        ).fetchall()
    finally:
        reader.close()
    return {"challenges": challenges, "by_status": by_status, "comparisons": comparisons, "cycles": cycles}


# The five ledger writers: valid arguments for the ledger ``faultable`` holds, and the state a success leaves.
_WRITERS = [
    pytest.param(
        lambda ledger: _add(ledger, challenger_id="c2"),
        _view(
            challenges=[("c1", "pending", 0, ""), ("c2", "pending", 0, "")],
            by_status=[("pending", "c1"), ("pending", "c2")],
        ),
        id="add_challenger",
    ),
    pytest.param(
        lambda ledger: _compare(ledger),
        _view(comparisons=[("e1", "challenger", True)]),
        id="record_comparison",
    ),
    pytest.param(
        lambda ledger: ledger.set_status("c1", "retired", reason="r", expected=["pending"]),
        _view(challenges=[("c1", "retired", 0, "r")], by_status=[("retired", "c1")]),
        id="set_status",
    ),
    pytest.param(
        lambda ledger: ledger.increment_cycles("c1"),
        _view(challenges=[("c1", "pending", 1, "")]),
        id="increment_cycles",
    ),
    pytest.param(
        lambda ledger: ledger.record_cycle(judge_calls=1, comparisons=1, deferred=0, promoted=0, retired=0),
        _view(cycles=[(1, 1, 0, 0, 0)]),
        id="record_cycle",
    ),
]


@pytest.mark.parametrize(
    "point",
    [pytest.param(("INSERT", "UPDATE"), id="execute"), pytest.param("COMMIT", id="commit")],
)
@pytest.mark.parametrize(("write", "after"), _WRITERS)
async def test_failed_ledger_write_is_rolled_back(
    faultable: _FaultableLedger,
    write: Callable[[ProcedureChallengeLedger], Awaitable[Any]],
    after: dict[str, Any],
    point: str | tuple[str, ...],
) -> None:
    """R3 (R3-2): a write that fails after ``BEGIN IMMEDIATE`` leaves no open transaction and no trace behind.

    Left open, the transaction let the ledger's own reads see a row no other reader could, and a later cycle skipped
    the durable transition it never made. The writer's data statement (``execute``) or its ``commit`` raises once;
    the ledger's own reads and an independent reader of the file must both show the state before the call.
    """
    ledger, connection = faultable.ledger, faultable.connection
    before = _view()
    # Premises: the independent reader sees the committed challenger, as the ledger's own reads do; nothing is open.
    assert _file_view(faultable.path) == before
    assert await _ledger_view(ledger) == before
    assert faultable.in_transaction is False

    injected = sqlite3.OperationalError("simulated ledger failure")
    connection.arm(point, injected)
    with pytest.raises(sqlite3.OperationalError) as raised:
        await write(ledger)

    # Premises: the writer raised the injected error, it fired once, and inside the transaction the writer had begun.
    assert raised.value is injected
    assert len(connection.fired) == 1 and connection.fired[0].startswith(point)
    assert connection.open_at_fault == [True]

    assert faultable.in_transaction is False
    assert await _ledger_view(ledger) == before
    assert _file_view(faultable.path) == before

    # The fault is gone: the same write succeeds, and both readers see it (the healthy path still commits).
    await write(ledger)
    assert await _ledger_view(ledger) == after
    assert _file_view(faultable.path) == after
    assert faultable.in_transaction is False


async def test_cancelled_ledger_write_is_rolled_back(faultable: _FaultableLedger) -> None:
    """R3 (R3-2): a cancellation during the commit is rolled back too, and it still propagates.

    ``CancelledError`` is a ``BaseException``: a handler written for ``Exception`` would leave the transaction open.
    """
    ledger, connection = faultable.ledger, faultable.connection
    assert await ledger.set_status("c1", "promoting", reason="held out", expected=("pending",)) is True
    before = _view(challenges=[("c1", "promoting", 0, "held out")], by_status=[("promoting", "c1")])
    # Premises: the independent reader sees the committed ``promoting``, as the ledger's own reads do.
    assert _file_view(faultable.path) == before
    assert await _ledger_view(ledger) == before

    cancelled = asyncio.CancelledError()
    connection.arm("COMMIT", cancelled)
    with pytest.raises(asyncio.CancelledError) as raised:
        await ledger.set_status("c1", "promoted", reason="won", expected=("promoting",))

    # Premises: the cancellation is the injected one, and it hit the commit of an open transaction.
    assert raised.value is cancelled
    assert connection.fired == ["COMMIT"]
    assert connection.open_at_fault == [True]

    assert faultable.in_transaction is False
    assert await _ledger_view(ledger) == before
    assert _file_view(faultable.path) == before


async def test_failed_rollback_is_logged_and_the_write_error_propagates(
    faultable: _FaultableLedger, caplog: pytest.LogCaptureFixture,
) -> None:
    """R3 (R3-2): a rollback that itself fails is logged, and the caller gets the write's own error, not the rollback's.

    The transaction then stays open (the named residual): the next write's ``BEGIN IMMEDIATE`` meets it and refuses,
    so nothing is built on it and nothing is ever committed.
    """
    ledger, connection = faultable.ledger, faultable.connection
    before = _view()
    assert _file_view(faultable.path) == before  # premise: the independent reader sees the committed challenger

    commit_error = sqlite3.OperationalError("simulated commit failure")
    rollback_error = sqlite3.OperationalError("simulated rollback failure")
    connection.arm("COMMIT", commit_error)
    connection.arm("ROLLBACK", rollback_error)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(sqlite3.OperationalError) as raised:
            await ledger.increment_cycles("c1")

    # Premises: both injected failures fired, in this order, each inside the open transaction.
    assert connection.fired == ["COMMIT", "ROLLBACK"]
    assert connection.open_at_fault == [True, True]

    assert raised.value is commit_error
    errors = [
        record for record in caplog.records
        if record.name == "probos.cognitive.procedure_challenges" and record.levelno == logging.ERROR
    ]
    assert len(errors) == 1
    assert "AD-1326" in errors[0].getMessage()
    assert errors[0].exc_info is not None and errors[0].exc_info[1] is rollback_error  # the log carries the rollback's

    # The transaction is still open, so the next write refuses at its BEGIN IMMEDIATE; nothing is ever committed.
    assert faultable.in_transaction is True
    with pytest.raises(sqlite3.OperationalError, match="within a transaction"):
        await ledger.increment_cycles("c1")
    assert connection.fired == ["COMMIT", "ROLLBACK"]  # that error was SQLite's own, not another injected one
    assert _file_view(faultable.path) == before


async def test_a_write_that_cannot_begin_issues_no_rollback_and_logs_nothing(
    faultable: _FaultableLedger, caplog: pytest.LogCaptureFixture,
) -> None:
    """R3 (R3-2): a write whose ``BEGIN IMMEDIATE`` fails began nothing, so it rolls nothing back and logs nothing.

    A ``ROLLBACK`` with no open transaction is refused by SQLite, and the handler's ERROR line would then name an open
    transaction that never existed. The next write is unaffected. (The statement is ``BEGIN IMMEDIATE``, which takes
    the write lock at once: an armed failure on that prefix never fires for a deferred ``BEGIN``.)
    """
    ledger, connection = faultable.ledger, faultable.connection
    before = _view()
    assert _file_view(faultable.path) == before  # premise: the independent reader sees the committed challenger

    injected = sqlite3.OperationalError("database is locked")
    connection.arm("BEGIN IMMEDIATE", injected)
    connection.arm("ROLLBACK", RuntimeError("a rollback was issued for a transaction that never began"))
    with caplog.at_level(logging.ERROR):
        with pytest.raises(sqlite3.OperationalError) as raised:
            await ledger.set_status("c1", "promoting", reason="held out", expected=("pending",))

    # Premises: the injected failure fired at the BEGIN, outside any transaction; the rollback trap stayed armed.
    assert raised.value is injected
    assert connection.fired == ["BEGIN IMMEDIATE"]
    assert connection.open_at_fault == [False]

    assert [r for r in caplog.records if r.name == "probos.cognitive.procedure_challenges" and r.levelno >= logging.ERROR] == []
    assert faultable.in_transaction is False
    assert await _ledger_view(ledger) == before
    assert _file_view(faultable.path) == before
    assert await ledger.set_status("c1", "promoting", reason="held out", expected=("pending",)) is True  # not wedged


_LEDGER_WRITERS = ("add_challenger", "record_comparison", "set_status", "increment_cycles", "record_cycle")


def _is_commit_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "commit"


def _opens_write_transaction(node: ast.AST) -> bool:
    """Whether ``node`` is an ``async with _write_transaction(...)`` statement."""
    return isinstance(node, ast.AsyncWith) and any(
        isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Name)
        and item.context_expr.func.id == "_write_transaction"
        for item in node.items
    )


def _commit_call_scopes(tree: ast.AST) -> list[str]:
    """The dotted scope (the classes and functions it sits in) of every ``.commit(...)`` call under ``tree``."""
    scopes: list[str] = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = (*scope, node.name)
        if _is_commit_call(node):
            scopes.append(".".join(scope))
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree, ())
    return scopes


def test_every_ledger_writer_runs_in_one_transaction() -> None:
    """R3 (R3-2): each writer opens exactly one ``_write_transaction`` and never commits itself.

    A scan of the module's syntax tree, on purpose (as ``test_ledger_module_issues_no_delete`` scans its text): the
    behaviour tests above fail one writer at a time, this one fails a writer that was edited, or added, to commit on
    its own, which is the one way to leave a transaction half open again.
    """
    tree = ast.parse(Path(procedure_challenges.__file__).read_text(encoding="utf-8"))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    methods = {
        node.name: node
        for node in classes["ProcedureChallengeLedger"].body
        if isinstance(node, ast.AsyncFunctionDef)
    }
    assert set(_LEDGER_WRITERS) <= set(methods), "premise: the five writers are coroutine methods of the ledger"

    for name in _LEDGER_WRITERS:
        transactions = [node for node in ast.walk(methods[name]) if _opens_write_transaction(node)]
        commits = [node for node in ast.walk(methods[name]) if _is_commit_call(node)]
        assert len(transactions) == 1, f"{name} must run in exactly one `async with _write_transaction(`"
        assert commits == [], f"{name} must not commit itself: _write_transaction commits"

    # Every ``.commit(`` call in the module: the helper's, and the schema's in ``start``; no writer's.
    assert sorted(_commit_call_scopes(tree)) == ["ProcedureChallengeLedger.start", "_write_transaction"]


# ---------------------------------------------------------------------------
# Review round 4 (R4-1): a cancelled call stays on the worker thread's queue
# ---------------------------------------------------------------------------
#
# aiosqlite runs one connection's calls in order on one worker thread, and cancelling the coroutine that awaits a call
# does not withdraw it: a ``BEGIN IMMEDIATE`` cancelled while it waits on another connection's lock can still take
# effect, and a cancelled ``COMMIT`` can still commit. ``_FaultingConnection`` raises before the real call is queued, so
# it can never leave a call behind. The rig below forwards every call to a real ``default_factory`` connection, so what
# the tests exercise is the worker thread's own queue.


class _QueueingConnection(_FaultingConnection):
    """A ``_FaultingConnection`` that lets a call be abandoned after it is queued, and records what became of each call.

    ``calls`` lists each call's text when it is made (its SQL, or ``COMMIT``), ``verbs`` their first words, and
    ``outcomes`` the ``(verb, outcome)`` of each call as it ends: ``ok``, ``cancelled`` (the awaiting coroutine was
    cancelled; the worker thread still runs the call) or the error's message. Three switches shape what a writer sees:

    * ``cancel_commit_after_queueing``: ``commit`` queues the real COMMIT as a task it keeps (``kept``) and then raises
      ``CancelledError``, as a caller cancelled mid-commit leaves it.
    * ``rollback_gate``: a ``ROLLBACK`` sets ``rollback_started`` and waits for the gate before it is forwarded.
    * ``commit_gate`` (R5): ``commit`` is recorded in ``calls``, sets ``commit_started`` and waits for the gate before
      it forwards the COMMIT, which parks a writer after its UPDATE with its transaction open and nothing committed. A
      cancellation while it waits never forwards the COMMIT.
    """

    def __init__(self, real: Any) -> None:
        super().__init__(real)
        self.calls: list[str] = []
        self.outcomes: list[tuple[str, str]] = []
        self.kept: list[asyncio.Task[None]] = []
        self.cancel_commit_after_queueing = False
        self.rollback_gate: asyncio.Event | None = None
        self.rollback_started = asyncio.Event()
        self.commit_gate: asyncio.Event | None = None
        self.commit_started = asyncio.Event()

    @property
    def verbs(self) -> list[str]:
        return [call.split(None, 1)[0] for call in self.calls]

    def forget(self) -> None:
        """Drop what was recorded so far, and the faults that fired, so a test reads only its own calls."""
        self.calls.clear()
        self.outcomes.clear()
        self.fired.clear()
        self.open_at_fault.clear()

    async def _forwarded(self, call: str, forwarded: Awaitable[Any]) -> Any:
        """Await ``forwarded`` (the call, made on the real connection) and record how it ended."""
        verb = call.split(None, 1)[0]
        try:
            result = await forwarded
        except asyncio.CancelledError:
            self.outcomes.append((verb, "cancelled"))
            raise
        except Exception as error:
            self.outcomes.append((verb, str(error)))
            raise
        self.outcomes.append((verb, "ok"))
        return result

    async def execute(self, sql: str, parameters: Any = ()) -> Any:
        call = sql.lstrip()
        self.calls.append(call)
        if call.startswith("ROLLBACK") and self.rollback_gate is not None:
            self.rollback_started.set()
            await self.rollback_gate.wait()
        return await self._forwarded(call, super().execute(sql, parameters))

    async def commit(self) -> None:
        self.calls.append("COMMIT")
        if self.cancel_commit_after_queueing:
            self.kept.append(asyncio.create_task(self.real.commit()))
            await asyncio.sleep(0)  # the kept task's first step queues the real COMMIT on the worker thread
            self.outcomes.append(("COMMIT", "cancelled"))
            raise asyncio.CancelledError()
        if self.commit_gate is not None:
            self.commit_started.set()
            await self.commit_gate.wait()  # a cancellation here never forwards the COMMIT
        await self._forwarded("COMMIT", super().commit())


@dataclass
class _QueueingLedger(_FaultableLedger):
    """A started ledger on a ``_QueueingConnection``, and the file it writes (for an independent reader)."""

    connection: _QueueingConnection


@pytest.fixture
async def queueing(tmp_path: Path, clock: _Clock) -> AsyncIterator[_QueueingLedger]:
    """A started ledger on a ``_QueueingConnection`` over a real connection, holding ``pending`` ``c1``.

    The wrapper has recorded nothing yet when the test starts.
    """
    path = tmp_path / "procedures_challenges.db"
    real = await default_factory.connect(str(path))
    try:
        connection = _QueueingConnection(real)
        ledger = ProcedureChallengeLedger(connection, clock=clock)
        await ledger.start()
        await _add(ledger)
        connection.forget()
        yield _QueueingLedger(ledger, connection, path)
    finally:
        await real.close()


class _WriteLockHolder:
    """An independent connection holding SQLite's write lock on a file until released, as another process would."""

    def __init__(self, path: Path) -> None:
        connection = sqlite3.connect(path, timeout=0, isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE")
        except BaseException:
            connection.close()
            raise
        self._connection: sqlite3.Connection | None = connection

    def release(self) -> None:
        """Roll back and close; releasing twice does nothing, so a test can also release in ``finally``."""
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.execute("ROLLBACK")
            finally:
                connection.close()


def _write_lock_is_held(path: Path) -> bool:
    """Whether a fresh connection is refused SQLite's write lock on ``path`` at once (``timeout=0``: it never waits)."""
    probe = sqlite3.connect(path, timeout=0, isolation_level=None)
    try:
        try:
            probe.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as error:
            assert "locked" in str(error), f"the refusal is the lock's, not another failure: {error}"
            return True
        probe.execute("ROLLBACK")
        return False
    finally:
        probe.close()


async def _until(
    condition: Callable[[], bool], what: str, *, interval: float = 0.005, timeout: float = 10.0,
) -> None:
    """Poll ``condition`` on the event loop until it holds; fail, naming ``what``, if it has not within ``timeout``."""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, f"timed out after {timeout} s waiting for {what}"
        await asyncio.sleep(interval)


async def _finish(writer: asyncio.Task[Any]) -> None:
    """Wait for ``writer`` to end, however it ends, and fail if it has not ended within the bound."""
    done, _ = await asyncio.wait({writer}, timeout=10.0)
    assert writer in done, "premise: the writer ends once what it waited on has been released"


async def _settle(writer: asyncio.Task[Any]) -> None:
    """Leave no task behind: cancel ``writer`` if it still runs, wait for it, and retrieve what it ended with."""
    if not writer.done():
        writer.cancel()
    await asyncio.wait({writer}, timeout=10.0)
    if writer.done() and not writer.cancelled():
        writer.exception()


@contextlib.asynccontextmanager
async def _blocked_writer(rig: _QueueingLedger) -> AsyncIterator[tuple[_WriteLockHolder, asyncio.Task[bool]]]:
    """``set_status("c1", "promoting")`` as a task whose ``BEGIN IMMEDIATE`` waits on an independent connection's lock.

    Premises, asserted before it yields: a fresh connection is refused the write lock (the holder has it); the writer's
    BEGIN has been queued on the ledger connection's worker thread and nothing has answered it: no call has ended and
    no transaction is open. On exit the holder lets go and the writer, if it still runs, is cancelled and awaited, so
    no test leaves a lock or a task behind.
    """
    holder = _WriteLockHolder(rig.path)
    writer: asyncio.Task[bool] | None = None
    try:
        assert _write_lock_is_held(rig.path) is True, "premise: the independent connection holds the write lock"
        writer = asyncio.create_task(rig.ledger.set_status("c1", "promoting", reason="r", expected=("pending",)))
        await _until(
            lambda: "BEGIN IMMEDIATE" in rig.connection.calls, "the writer's BEGIN IMMEDIATE to be queued", interval=0,
        )
        assert not writer.done() and rig.connection.outcomes == [], "premise: the BEGIN is waiting on the lock"
        assert rig.in_transaction is False, "premise: the transaction the BEGIN asks for is not open"
        yield holder, writer
    finally:
        try:
            holder.release()
        finally:
            if writer is not None:
                await _settle(writer)


async def _assert_ledger_is_free(
    rig: _QueueingLedger, caplog: pytest.LogCaptureFixture, *, status: str,
) -> None:
    """What ends every R4-1 test: nothing is left open or logged, and the ledger takes the next write.

    ``status`` is the status the test left ``c1`` in (``pending`` or ``promoting``). The ledger connection holds no
    transaction and no ERROR came from ``probos.cognitive.procedure_challenges``; a write the status allows commits
    and an independent reader sees it; and a fresh connection can take the write lock and give it back.
    """
    assert rig.in_transaction is False
    errors = [
        record for record in caplog.records
        if record.name == "probos.cognitive.procedure_challenges" and record.levelno >= logging.ERROR
    ]
    assert errors == []
    if status == "pending":
        assert await rig.ledger.increment_cycles("c1") == 1
        assert await rig.ledger.set_status("c1", "promoting", reason="again", expected=("pending",)) is True
        assert _file_view(rig.path)["challenges"] == [("c1", "promoting", 1, "again")]
    else:
        assert status == "promoting"
        assert await rig.ledger.set_status("c1", "promoted", reason="again", expected=("promoting",)) is True
        assert _file_view(rig.path)["challenges"] == [("c1", "promoted", 0, "again")]
    assert _write_lock_is_held(rig.path) is False


async def test_a_cancelled_begin_is_rolled_back_after_it_takes_effect(
    queueing: _QueueingLedger, caplog: pytest.LogCaptureFixture,
) -> None:
    """R4 (R4-1): a ``BEGIN IMMEDIATE`` cancelled while it waited on another connection's lock is still rolled back.

    The reviewer's case. Cancelling the caller does not withdraw the queued ``BEGIN``: when the lock is freed it takes
    effect and opens a transaction nobody awaits. The writer therefore holds the ledger lock until its ``ROLLBACK``,
    queued behind the ``BEGIN``, has run. Round 3 rolled back only a ``BEGIN`` that had returned, so this one was left
    open (``in_transaction`` True) and the next write refused ("cannot start a transaction within a transaction").
    """
    ledger, connection = queueing.ledger, queueing.connection
    assert _file_view(queueing.path) == _view()  # premise: the independent reader sees the committed challenger
    async with _blocked_writer(queueing) as (holder, writer):
        await asyncio.sleep(0.05)
        assert not writer.done() and connection.outcomes == []  # premise: the BEGIN is still blocked on the lock
        assert queueing.in_transaction is False

        writer.cancel()
        await asyncio.sleep(0.05)

        # Premises: the cancellation landed while the BEGIN waited (it ended cancelled, before it took effect), and the
        # cancelled writer is not done: it holds the ledger lock until its rollback has run (the premise of the fix).
        assert connection.outcomes == [("BEGIN", "cancelled")]
        assert not writer.done()

        holder.release()  # the queued BEGIN now takes effect, and the ROLLBACK queued behind it undoes it
        await _finish(writer)

    with pytest.raises(asyncio.CancelledError):
        await writer
    assert writer.cancelled()
    assert connection.verbs == ["BEGIN", "ROLLBACK"]
    assert connection.outcomes == [("BEGIN", "cancelled"), ("ROLLBACK", "ok")]  # the ROLLBACK undid an open transaction
    assert await _ledger_view(ledger) == _view()
    assert _file_view(queueing.path) == _view()
    await _assert_ledger_is_free(queueing, caplog, status="pending")


async def test_a_cancelled_begin_that_never_takes_effect_logs_nothing(
    queueing: _QueueingLedger, caplog: pytest.LogCaptureFixture,
) -> None:
    """R4 (R4-1): a cancelled ``BEGIN`` that fails on the busy timeout leaves a ``ROLLBACK`` with nothing to undo.

    SQLite refuses that ``ROLLBACK`` ("no transaction is active"). The goal already holds, so it is not logged: an ERROR
    would name an open transaction that never existed. The ledger connection's busy timeout is lowered to 100 ms, so the
    queued ``BEGIN`` gives up while the independent connection still holds the lock; the holder is released only after
    the ``ROLLBACK`` has been answered, so the ``BEGIN`` cannot have taken effect.
    """
    ledger, connection = queueing.ledger, queueing.connection
    assert _file_view(queueing.path) == _view()  # premise: the independent reader sees the committed challenger
    await connection.real.execute("PRAGMA busy_timeout=100")  # a BEGIN that waits on the lock now fails after 100 ms
    async with _blocked_writer(queueing) as (holder, writer):
        writer.cancel()  # at once: the 100 ms timeout started with the BEGIN, and the premises above were synchronous

        await _until(
            lambda: any(verb == "ROLLBACK" for verb, _ in connection.outcomes), "the queued ROLLBACK to be answered",
        )
        # Premise: the holder kept the lock throughout, so the BEGIN failed on it and never took effect.
        assert _write_lock_is_held(queueing.path) is True
        await _finish(writer)
        holder.release()

    with pytest.raises(asyncio.CancelledError):
        await writer
    assert writer.cancelled()
    assert connection.verbs == ["BEGIN", "ROLLBACK"]
    begin, rollback = connection.outcomes
    assert begin == ("BEGIN", "cancelled")  # premise: the cancellation landed while the BEGIN waited
    assert rollback[0] == "ROLLBACK" and "no transaction is active" in rollback[1]  # SQLite's refusal: nothing to undo
    assert await _ledger_view(ledger) == _view()
    assert _file_view(queueing.path) == _view()
    await _assert_ledger_is_free(queueing, caplog, status="pending")


async def test_a_cancelled_commit_that_still_commits_is_durable_and_logs_nothing(
    queueing: _QueueingLedger, caplog: pytest.LogCaptureFixture,
) -> None:
    """R4 (R4-1): a ``COMMIT`` cancelled after it was queued still commits; the ``ROLLBACK`` finds nothing open.

    The write is durable although its caller saw the cancellation (accepted, D12: every ledger writer is a conditional
    or idempotent step the next dream cycle re-reads from the ledger). The ``ROLLBACK`` is queued behind the ``COMMIT``,
    so it runs after it and SQLite refuses it ("no transaction is active"); that refusal is not logged.
    """
    ledger, connection = queueing.ledger, queueing.connection
    assert _file_view(queueing.path) == _view()  # premise: the independent reader sees the committed challenger
    connection.cancel_commit_after_queueing = True

    with pytest.raises(asyncio.CancelledError):
        await ledger.set_status("c1", "promoting", reason="held out", expected=("pending",))

    connection.cancel_commit_after_queueing = False
    await asyncio.gather(*connection.kept)  # the real COMMIT's own task has settled before anything is asserted
    # Premises: one COMMIT was queued and then abandoned by its caller, and one ROLLBACK ran after it and was refused.
    assert len(connection.kept) == 1
    assert connection.verbs == ["BEGIN", "UPDATE", "COMMIT", "ROLLBACK"]
    *earlier, (verb, outcome) = connection.outcomes
    assert earlier == [("BEGIN", "ok"), ("UPDATE", "ok"), ("COMMIT", "cancelled")]
    assert verb == "ROLLBACK" and "no transaction is active" in outcome

    promoting = _view(challenges=[("c1", "promoting", 0, "held out")], by_status=[("promoting", "c1")])
    assert _file_view(queueing.path) == promoting  # durable: the write stands although its caller saw the cancellation
    assert await _ledger_view(ledger) == promoting
    await _assert_ledger_is_free(queueing, caplog, status="promoting")


async def test_a_second_cancellation_during_cleanup_still_rolls_back(
    queueing: _QueueingLedger, caplog: pytest.LogCaptureFixture,
) -> None:
    """R4 (R4-1): cancellations that reach the writer while its rollback is pending are absorbed; it still rolls back.

    The first cancel ends the ``BEGIN``'s wait and starts the cleanup; the second is issued before the cleanup task has
    queued its ``ROLLBACK``, the third while the writer waits for it. Were the cleanup awaited unshielded, the second
    would cancel it before it queued anything and the late ``BEGIN`` would be left open. The writer holds the lock until
    its one ``ROLLBACK`` has run, and then raises the cancellation.
    """
    ledger, connection = queueing.ledger, queueing.connection
    assert _file_view(queueing.path) == _view()  # premise: the independent reader sees the committed challenger
    async with _blocked_writer(queueing) as (holder, writer):
        await asyncio.sleep(0.05)
        assert not writer.done() and connection.outcomes == []  # premise: the BEGIN is still blocked on the lock

        writer.cancel()
        await asyncio.sleep(0)
        # Premise: the first cancel ended the BEGIN's wait; its cleanup has not yet queued the ROLLBACK.
        assert connection.outcomes == [("BEGIN", "cancelled")] and connection.verbs == ["BEGIN"]
        writer.cancel()
        await asyncio.sleep(0)
        writer.cancel()
        await asyncio.sleep(0.05)

        # Premises: the writer absorbed all three; it is not done, and the one ROLLBACK is queued behind the BEGIN.
        assert not writer.done()
        assert connection.verbs == ["BEGIN", "ROLLBACK"]
        assert connection.outcomes == [("BEGIN", "cancelled")]

        holder.release()  # the queued BEGIN now takes effect, and the ROLLBACK queued behind it undoes it
        await _finish(writer)

    with pytest.raises(asyncio.CancelledError):
        await writer
    assert writer.cancelled()
    assert connection.verbs == ["BEGIN", "ROLLBACK"]
    assert connection.outcomes == [("BEGIN", "cancelled"), ("ROLLBACK", "ok")]  # the ROLLBACK undid an open transaction
    assert await _ledger_view(ledger) == _view()
    assert _file_view(queueing.path) == _view()
    await _assert_ledger_is_free(queueing, caplog, status="pending")


async def test_a_cancellation_during_rollback_waits_for_it_and_is_delivered(
    queueing: _QueueingLedger, caplog: pytest.LogCaptureFixture,
) -> None:
    """R4 (R4-1): a cancellation that arrives while the rollback runs waits for it, and is delivered after it.

    The commit fails inside the open transaction and its ``ROLLBACK`` is held at a gate. The cancel that reaches the
    writer there does not abandon the rollback (the transaction would stay open under a released lock): the writer
    waits for it, and once it has run raises the cancellation, not the commit's ``OperationalError``, so a caller's
    timeout or task group still sees its cancellation.
    """
    ledger, connection = queueing.ledger, queueing.connection
    assert _file_view(queueing.path) == _view()  # premise: the independent reader sees the committed challenger
    injected = sqlite3.OperationalError("injected")
    connection.arm("COMMIT", injected)
    gate = asyncio.Event()
    connection.rollback_gate = gate
    writer = asyncio.create_task(ledger.set_status("c1", "promoting", reason="held out", expected=("pending",)))
    try:
        await asyncio.wait_for(connection.rollback_started.wait(), timeout=10.0)
        # Premises: the commit failed inside the open transaction, and the writer now waits on its own ROLLBACK.
        assert connection.fired == ["COMMIT"] and connection.open_at_fault == [True]
        assert queueing.in_transaction is True and not writer.done()

        writer.cancel()
        await asyncio.sleep(0.05)
        assert not writer.done()  # the writer waits for the rollback ...
        assert queueing.in_transaction is True  # ... which has not run yet

        gate.set()
        await _finish(writer)
    finally:
        gate.set()
        await _settle(writer)

    with pytest.raises(asyncio.CancelledError):  # delivered after the cleanup, and not the commit's OperationalError
        await writer
    assert writer.cancelled()
    assert connection.outcomes == [("BEGIN", "ok"), ("UPDATE", "ok"), ("COMMIT", "injected"), ("ROLLBACK", "ok")]
    assert await _ledger_view(ledger) == _view()
    assert _file_view(queueing.path) == _view()
    await _assert_ledger_is_free(queueing, caplog, status="pending")


# ---------------------------------------------------------------------------
# Review round 3 (R3-3): the routing index publishes the activity column
# ---------------------------------------------------------------------------


class _FaultingFactory:
    """A ``ConnectionFactory`` whose connections are ``_FaultingConnection`` s over real ones, found by file name.

    ``wrapper`` is the class each connection is wrapped in: ``_QueueingConnection`` for a test that gates a commit (R5).
    """

    def __init__(self, wrapper: type[_FaultingConnection] = _FaultingConnection) -> None:
        self.connected: dict[str, _FaultingConnection] = {}
        self._wrapper = wrapper

    async def connect(self, db_path: str) -> _FaultingConnection:
        connection = self._wrapper(await default_factory.connect(db_path))
        self.connected[Path(db_path).name] = connection
        return connection

    async def close_all(self) -> None:
        for connection in self.connected.values():
            await connection.close()  # idempotent: a connection the store already closed is left alone


def _is_active_column(db_path: Path, procedure_id: str) -> int | None:
    """The ``is_active`` column of a procedure's row as an independent reader of ``procedures.db`` sees it."""
    reader = sqlite3.connect(db_path)
    try:
        row = reader.execute("SELECT is_active FROM procedure_records WHERE id = ?", (procedure_id,)).fetchone()
    finally:
        reader.close()
    return row[0] if row else None


def _snapshot_lineage(db_path: Path, procedure_id: str) -> tuple[bool, str]:
    """A procedure's ``(is_active, superseded_by)`` as its JSON ``content_snapshot`` says them (R5-2).

    An independent reader of ``procedures.db``. ``deactivate`` leaves the snapshot stale when it swallows a failed
    snapshot UPDATE after the columns commit, and ``ProcedureStore.get`` rebuilds a procedure from it.
    """
    reader = sqlite3.connect(db_path)
    try:
        row = reader.execute(
            "SELECT content_snapshot FROM procedure_records WHERE id = ?", (procedure_id,),
        ).fetchone()
    finally:
        reader.close()
    assert row is not None, f"premise: {procedure_id} has a row in procedures.db"
    snapshot = json.loads(row[0])
    return snapshot["is_active"], snapshot["superseded_by"]


@pytest.mark.usefixtures("deterministic_embeddings")
async def test_sync_routing_index_publishes_the_activity_column(tmp_path: Path) -> None:
    """R3 (R3-3): the index entry's ``is_active`` is the column's, which admission reads, not the JSON snapshot's.

    ``deactivate`` commits the column and then swallows a failed ``content_snapshot`` UPDATE, so the snapshot keeps
    saying active while the column says inactive (the reviewer's case); ``get`` keeps reading the snapshot and
    ``routing_state`` reads the columns (R6-1). A sync that published the snapshot's flag would turn the entry,
    correct until then, back to active.
    """
    factory = _FaultingFactory()
    store = ProcedureStore(tmp_path / "procedures", connection_factory=factory)
    try:
        await store.start()
        procedures_db = factory.connected["procedures.db"]
        db_path = tmp_path / "procedures" / "procedures.db"
        await store.save(_procedure("champ"))
        assert _is_active_column(db_path, "champ") == 1  # premise: the independent reader sees the saved, active row
        procedures_db.arm(
            "UPDATE procedure_records SET content_snapshot", sqlite3.OperationalError("simulated snapshot failure"),
        )

        await store.deactivate("champ", superseded_by="challenger")  # swallows the snapshot failure, as before

        # Premises: the snapshot UPDATE failed once, inside deactivate's open transaction (after its column UPDATE),
        # the column says inactive, the snapshot still says active, and the index entry agrees with the column.
        assert len(procedures_db.fired) == 1
        assert procedures_db.fired[0].startswith("UPDATE procedure_records SET content_snapshot")
        assert procedures_db.open_at_fault == [True]
        assert _is_active_column(db_path, "champ") == 0
        assert _snapshot_lineage(db_path, "champ") == (True, "")  # raw premise: the JSON snapshot is stale
        champion = await store.get("champ")  # get rebuilds from the stale snapshot (base behaviour; R6-1)
        assert champion is not None and champion.is_active is True and champion.superseded_by == ""
        assert await store.routing_state("champ") == (False, "challenger")  # R6-1: the columns admission reads
        assert _index_says_active(store, "champ") is False

        assert await store.sync_routing_index("champ") is True

        assert _index_says_active(store, "champ") is False  # published from the column, not turned back by the snapshot

        # Positive control: a row whose column is 1 publishes active, so the False above is the column's.
        await store.save(_procedure("p-live"))
        assert _is_active_column(db_path, "p-live") == 1  # premise: its column is 1
        _live_collection(store).update(ids=["p-live"], metadatas=[{"is_active": False}])  # a stale, inactive entry
        assert _index_says_active(store, "p-live") is False  # premise
        assert await store.sync_routing_index("p-live") is True
        assert _index_says_active(store, "p-live") is True
    finally:
        await store.stop()
        await factory.close_all()


# ---------------------------------------------------------------------------
# Review round 3 (R3-5): routing consults the ledger the store owns
# ---------------------------------------------------------------------------

# The transitions that take a ``pending`` challenger to each status (each is ``expected`` to be its predecessor).
_PATH_TO_STATUS: dict[str, tuple[str, ...]] = {
    "pending": (),
    "promoting": ("promoting",),
    "promoted": ("promoting", "promoted"),
    "retired": ("retired",),
}

# The keys, in order, of a row ``find_matching`` returns: the ones it had at base, then the ``score`` it adds.
_ROUTING_ROW_KEYS = [
    "id", "name", "evolution_type", "compilation_level", "intent_types", "total_selections",
    "total_applied", "total_completions", "total_fallbacks", "is_negative", "score",
]


async def _move_to_status(ledger: ProcedureChallengeLedger, challenger_id: str, status: str) -> ChallengeRecord:
    """Take a ``pending`` challenger to ``status`` through the ledger's transitions; return its stored record."""
    previous = "pending"
    for step in _PATH_TO_STATUS[status]:
        assert await ledger.set_status(challenger_id, step, reason="staged", expected=[previous]) is True
        previous = step
    record = await ledger.get(challenger_id)
    assert record is not None and record.status == status  # premise: the ledger holds the row in ``status``
    return record


async def _stage_active_challenger(store: ProcedureStore, status: str) -> None:
    """The restored state R3-5 is about: champion and challenger both saved ACTIVE, the challenger's row in ``status``.

    The premises are asserted here, before any test routes: SQLite and the semantic index both say active for both.
    """
    ledger = store.challenges
    assert ledger is not None, "premise: the ledger is open"
    await store.save(_procedure("champ"))
    await store.save(_procedure("chal"))  # one description: both match the same query
    await _add(ledger, challenger_id="chal")
    await _move_to_status(ledger, "chal", status)
    assert sorted(row["id"] for row in await store.list_active()) == ["chal", "champ"]
    assert _index_says_active(store, "champ") is True
    assert _index_says_active(store, "chal") is True


def _ledger_file_status(root: Path, challenger_id: str) -> str | None:
    """A challenger's status as an independent reader of ``procedures_challenges.db`` sees it (committed rows only)."""
    reader = sqlite3.connect(root / "procedures_challenges.db")
    try:
        row = reader.execute(
            "SELECT status FROM procedure_challenges WHERE challenger_id = ?", (challenger_id,),
        ).fetchone()
    finally:
        reader.close()
    return row[0] if row else None


async def test_challenge_record_bars_routing_table(ledger: ProcedureChallengeLedger) -> None:
    """R3 (R3-5): a challenger the ledger holds undecided (``pending``) or lost (``retired``) bars routing.

    The records come from a real ledger, one in each status it knows, as ``ProcedureStore`` reads them.
    """
    expected = {"pending": True, "promoting": False, "promoted": False, "retired": True}
    assert set(expected) == set(_STATUS_ORDER)  # premise: the table names every status a challenger can have

    observed: dict[str, bool] = {}
    for status in expected:
        await _add(ledger, challenger_id=f"c-{status}")
        observed[status] = (await _move_to_status(ledger, f"c-{status}", status)).bars_routing

    assert observed == expected


@pytest.mark.usefixtures("deterministic_embeddings")
@pytest.mark.parametrize("status", ["pending", "retired"])
async def test_find_matching_refuses_a_challenger_the_ledger_holds_undecided(tmp_path: Path, status: str) -> None:
    """R3 (R3-5): a challenger the ledger holds ``pending`` or ``retired`` does not route, whatever SQLite says.

    The restored state (a raw-copy fallback or a manual copy pairs an older ledger with a newer ``procedures.db``): the
    challenger is active in SQLite and in the index, and its ledger row says it has not won.
    """
    async with _running_store(tmp_path / "procedures") as store:
        await _stage_active_challenger(store, status)  # premises: active in SQLite and the index; the row in ``status``

        matches = await store.find_matching(_procedure().description)

        assert [match["id"] for match in matches] == ["champ"]
        assert list(matches[0]) == _ROUTING_ROW_KEYS


@pytest.mark.usefixtures("deterministic_embeddings")
@pytest.mark.parametrize("status", ["promoting", "promoted"])
async def test_find_matching_admits_a_promoting_or_promoted_challenger(tmp_path: Path, status: str) -> None:
    """R3 (R3-5): a challenger whose ledger row says it is winning, or has won, routes as it always did."""
    async with _running_store(tmp_path / "procedures") as store:
        await _stage_active_challenger(store, status)  # premises: active in SQLite and the index; the row in ``status``

        matches = await store.find_matching(_procedure().description)

        assert sorted(match["id"] for match in matches) == ["chal", "champ"]
        assert all(list(match) == _ROUTING_ROW_KEYS for match in matches)


@pytest.mark.usefixtures("deterministic_embeddings")
@pytest.mark.parametrize("fault", ["not_open", "read_fails"])
async def test_find_matching_without_a_readable_ledger_admits_on_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fault: str,
) -> None:
    """R3 (R3-5): with no ledger to ask, or one whose read raises, SQLite alone admits, as before AD-1326 (fail-open).

    The ``pending`` row is written before the fault, so the challenger the readable ledger bars is returned beside the
    champion. ``read_fails`` fails the read of the challenger's row: one failed read, one WARNING (a ledger that failed
    every read would log one per admitted match).
    """
    root = tmp_path / "procedures"
    query = _procedure().description
    async with _running_store(root) as healthy:
        await _stage_active_challenger(healthy, "pending")
        # Control: while the ledger is readable, its ``pending`` row bars the challenger.
        assert [match["id"] for match in await healthy.find_matching(query)] == ["champ"]

    async def failing_start(self: ProcedureChallengeLedger) -> None:
        raise sqlite3.OperationalError("simulated schema failure")

    failed_reads: list[str] = []
    with monkeypatch.context() as patched:
        if fault == "not_open":
            patched.setattr(ProcedureChallengeLedger, "start", failing_start)
        async with _running_store(root) as store:
            if fault == "not_open":
                assert store.challenges is None  # premise: the ledger did not open
            else:
                ledger = store.challenges
                assert ledger is not None  # premise: the ledger is open, and the read of the challenger raises
                real_get = ledger.get

                async def failing_get(challenger_id: str) -> ChallengeRecord | None:
                    if challenger_id != "chal":
                        return await real_get(challenger_id)
                    failed_reads.append(challenger_id)
                    raise RuntimeError("simulated ledger read failure")

                patched.setattr(ledger, "get", failing_get)
            assert _ledger_file_status(root, "chal") == "pending"  # premise: the row was written before the fault
            caplog.clear()
            with caplog.at_level(logging.WARNING):
                matches = await store.find_matching(query)

    assert sorted(match["id"] for match in matches) == ["chal", "champ"]  # SQLite alone admitted the challenger
    warnings = [
        record for record in caplog.records
        if record.levelno == logging.WARNING and "AD-1326" in record.getMessage()
    ]
    if fault == "read_fails":
        assert failed_reads == ["chal"]  # the read was tried, and raised, once
        assert len(warnings) == 1
    else:
        assert warnings == []  # there was nothing to read, so nothing to warn about


# ---------------------------------------------------------------------------
# Review round 4 (R4-2): a restored completed promotion routes with no dream cycle
# ---------------------------------------------------------------------------

# The champion's row in ``procedures.db`` per variant: ``(is_active, superseded_by)``, or ``None`` once it is gone.
_RESTORED_CHAMPION: dict[str, tuple[int, str] | None] = {
    "completed": (0, "ch-a"),
    "champion_active": (1, ""),
    "superseded_by_another": (0, "other"),
    "champion_missing": None,
    "retired_completed": (0, "ch-a"),
}


def _record_state(db_path: Path, procedure_id: str) -> tuple[int, str] | None:
    """A procedure's ``(is_active, superseded_by)`` as an independent reader of ``procedures.db`` sees them."""
    reader = sqlite3.connect(db_path)
    try:
        row = reader.execute(
            "SELECT is_active, superseded_by FROM procedure_records WHERE id = ?", (procedure_id,),
        ).fetchone()
    finally:
        reader.close()
    return (row[0], row[1]) if row else None


async def _stage_restored_pair(store: ProcedureStore, root: Path, variant: str) -> None:
    """An older ledger beside a newer ``procedures.db``, in the ``variant`` ``_RESTORED_CHAMPION`` names.

    The champion ``champ`` and the challenger ``ch-a`` are saved ACTIVE and ``ch-a``'s ledger row is ``pending``
    (``retired`` for ``retired_completed``); then the champion is left as the variant says: ``completed`` is what
    ``_complete_promotion`` leaves in ``procedures.db`` (the champion inactive, superseded by ``ch-a``) while the ledger
    still says ``pending``. The premises are asserted here, before any test routes: SQLite and the semantic index both
    say ``ch-a`` is active, and the ledger row and the champion's row are what the variant says they are.
    """
    ledger = store.challenges
    assert ledger is not None, "premise: the ledger is open"
    await store.save(_procedure("champ"))
    await store.save(_procedure("ch-a"))  # one description: both match the same query
    await _add(ledger, challenger_id="ch-a")
    if variant == "retired_completed":
        await _move_to_status(ledger, "ch-a", "retired")
    if variant in ("completed", "retired_completed"):
        await store.deactivate("champ", superseded_by="ch-a")
    elif variant == "superseded_by_another":
        await store.deactivate("champ", superseded_by="other")
    elif variant == "champion_missing":
        assert await store.delete("champ") is True
    else:
        assert variant == "champion_active"  # the champion is left active

    assert "ch-a" in [row["id"] for row in await store.list_active()]
    assert _index_says_active(store, "ch-a") is True
    assert _ledger_file_status(root, "ch-a") == ("retired" if variant == "retired_completed" else "pending")
    assert _record_state(root / "procedures.db", "champ") == _RESTORED_CHAMPION[variant]


@pytest.mark.usefixtures("deterministic_embeddings")
@pytest.mark.parametrize(
    ("variant", "expected"),
    [
        pytest.param("completed", ["ch-a"], id="completed"),
        pytest.param("champion_active", ["champ"], id="champion_active"),
        pytest.param("superseded_by_another", [], id="superseded_by_another"),
        pytest.param("champion_missing", [], id="champion_missing"),
        pytest.param("retired_completed", [], id="retired_completed"),
    ],
)
async def test_find_matching_admits_a_pending_challenger_whose_promotion_procedures_db_holds(
    tmp_path: Path, variant: str, expected: list[str],
) -> None:
    """R4 (R4-2): a ``pending`` challenger whose champion ``procedures.db`` already shows superseded by it routes.

    ``procedures.db`` holds a completed promotion (the champion inactive, ``superseded_by`` the challenger) that the
    older ledger has not recorded: the pair the next dream cycle records as ``restored_promotion``. No service is
    built here, so this is admission alone. Only that pair is admitted: a champion still active, superseded by another
    procedure or gone still bars the ``pending`` challenger, and a ``retired`` one is barred whatever the champion says.
    """
    root = tmp_path / "procedures"
    async with _running_store(root) as store:
        await _stage_restored_pair(store, root, variant)  # premises: ``ch-a`` active in SQLite and the index; the rest

        matches = await store.find_matching(_procedure().description)

        assert [match["id"] for match in matches] == expected
        assert all(list(match) == _ROUTING_ROW_KEYS for match in matches)


@pytest.mark.usefixtures("deterministic_embeddings")
async def test_flag_off_routes_a_restored_completed_promotion(tmp_path: Path) -> None:
    """R4 (R4-2): with the challenger flag off, a restored completed promotion routes with no reconciliation.

    The reviewer's case. No service is built while the flag is off, so nothing ever runs the reconciliation that would
    move the ``pending`` row to ``promoted``; round 3 routed neither procedure until it did. After a restore (a fresh
    store over the same directory) the older ledger still says ``pending`` and holds its comparison, and routing needs
    nothing more than ``procedures.db``: ``ch-a`` routes, and the ledger is as the restore left it.
    """
    root = tmp_path / "procedures"
    query = _procedure().description
    async with _running_store(root) as staged:
        await _stage_restored_pair(staged, root, "completed")
        assert staged.challenges is not None
        await _compare(staged.challenges, challenger_id="ch-a")  # one counted comparison

    disabled = SystemConfig(dreaming=DreamingConfig(procedure_challenger_enabled=False))
    async with _running_store(root) as restarted:  # a fresh store over the same directory, as after a restore
        ledger = restarted.challenges
        assert ledger is not None, "premise: the ledger is open"
        # Premise: the flag builds no service (as ``test_build_returns_none_when_disabled``), and it alone decides that.
        stand_ins: dict[str, Any] = {"episodic_memory": object(), "llm_client": object(), "emit_event_fn": None}
        assert build_procedure_challenger(config=disabled, procedure_store=restarted, **stand_ins) is None
        built = build_procedure_challenger(config=SystemConfig(), procedure_store=restarted, **stand_ins)
        assert isinstance(built, ProcedureChallenger)
        # Premises: ``procedures.db`` holds the completed promotion; the ledger still says ``pending`` and has its row.
        assert _record_state(root / "procedures.db", "champ") == (0, "ch-a")
        before = await ledger.get("ch-a")
        assert before is not None and before.status == "pending"
        assert len(await ledger.comparisons("ch-a")) == 1

        matches = await restarted.find_matching(query)

        assert [match["id"] for match in matches] == ["ch-a"]
        assert list(matches[0]) == _ROUTING_ROW_KEYS
        assert await ledger.get("ch-a") == before  # routing wrote nothing: it needed no reconciliation
        assert len(await ledger.comparisons("ch-a")) == 1
    assert _ledger_file_status(root, "ch-a") == "pending"


# ---------------------------------------------------------------------------
# Review round 5 (R5-1): a ledger read waits for an in-flight write
# ---------------------------------------------------------------------------
#
# The ledger has one connection, and a read on it sees that connection's own open transaction. Before R5-1 a read issued
# between a writer's ``UPDATE`` and its ``COMMIT`` (or before its cleanup ``ROLLBACK`` had run) returned the status the
# writer had not committed, and ``ProcedureStore._get_index_row`` admitted a ``promoting`` challenger from a transition
# that was then rolled back. Every public read now takes the ledger lock, which a writer holds from ``BEGIN IMMEDIATE``
# until its ``COMMIT`` or its ``ROLLBACK`` has run. The writers below are parked at their COMMIT
# (``_QueueingConnection.commit_gate``): the UPDATE is applied on the ledger's connection and nothing is committed.


async def _status_on_the_ledger_connection(rig: _QueueingLedger) -> str:
    """``c1``'s status as the ledger's own connection sees it: that includes its open transaction's uncommitted write.

    Asked of the real connection directly, past the ledger lock and the wrapper's record, so it is the answer a read
    that did not wait for the writer would have returned.
    """
    cursor = await rig.connection.real.execute("SELECT status FROM procedure_challenges WHERE challenger_id = 'c1'")
    row = await cursor.fetchone()
    assert row is not None, "premise: the ledger's connection holds c1"
    return row[0]


# The five public reads of the ledger ``queueing`` holds: the call, its result as the rows ``_file_view`` reports, and
# the share of an independent reader's view that those rows must equal once the writer has committed.
_LEDGER_READS = [
    pytest.param(
        lambda ledger: ledger.get("c1"),
        lambda record: [(record.challenger_id, record.status, record.cycles_pending, record.decision_reason)],
        lambda view: view["challenges"],
        id="get",
    ),
    pytest.param(
        lambda ledger: ledger.list_by_status("pending"),
        lambda records: [("pending", record.challenger_id) for record in records],
        lambda view: [entry for entry in view["by_status"] if entry[0] == "pending"],
        id="list_by_status",
    ),
    pytest.param(
        lambda ledger: ledger.pending_count("champ"),
        lambda count: count,
        lambda view: sum(1 for _, status, _, _ in view["challenges"] if status in ("pending", "promoting")),
        id="pending_count",
    ),
    pytest.param(
        lambda ledger: ledger.comparisons("c1"),
        lambda rows: [(row.episode_id, row.outcome, row.counted) for row in rows],
        lambda view: view["comparisons"],
        id="comparisons",
    ),
    pytest.param(
        lambda ledger: ledger.recent_cycles(),
        lambda rows: [
            (row["judge_calls"], row["comparisons"], row["deferred"], row["promoted"], row["retired"]) for row in rows
        ],
        lambda view: view["cycles"],
        id="recent_cycles",
    ),
]


@pytest.mark.parametrize(("read", "as_rows", "from_view"), _LEDGER_READS)
async def test_every_public_ledger_read_waits_for_an_in_flight_write(
    queueing: _QueueingLedger,
    caplog: pytest.LogCaptureFixture,
    read: Callable[[ProcedureChallengeLedger], Awaitable[Any]],
    as_rows: Callable[[Any], Any],
    from_view: Callable[[dict[str, Any]], Any],
) -> None:
    """R5 (R5-1): a ledger read issued while a writer's transaction is open waits for it and answers committed state.

    The writer (``set_status``: ``pending`` -> ``promoting``) is parked at its COMMIT with its UPDATE applied.
    Premises, asserted before the read is issued: the ledger's own connection says ``promoting``, which a read that did
    not wait would have returned, while an independent reader still sees ``pending``. The read must then stay
    unfinished and issue no SQL while the writer is parked (it waits for the writer, not for SQLite); once the writer
    commits it answers what an independent reader then sees: ``get`` says ``promoting`` and
    ``list_by_status("pending")`` is empty. A comparison and a cycle are recorded first, so that ``comparisons`` and
    ``recent_cycles`` have rows to return.
    """
    ledger, connection = queueing.ledger, queueing.connection
    await _compare(ledger)
    await ledger.record_cycle(judge_calls=1, comparisons=1, deferred=0, promoted=0, retired=0)
    connection.forget()
    committed_before = _view(comparisons=[("e1", "challenger", True)], cycles=[(1, 1, 0, 0, 0)])
    assert _file_view(queueing.path) == committed_before  # premise: the independent reader sees the committed rows

    gate = asyncio.Event()
    connection.commit_gate = gate
    writer = asyncio.create_task(ledger.set_status("c1", "promoting", reason="r", expected=("pending",)))
    reading: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(connection.commit_started.wait(), timeout=10.0)
        # Premises: the writer is parked at its COMMIT with its UPDATE applied, and nothing is committed.
        assert connection.verbs == ["BEGIN", "UPDATE", "COMMIT"]
        assert connection.outcomes == [("BEGIN", "ok"), ("UPDATE", "ok")]
        assert queueing.in_transaction is True and not writer.done()
        assert await _status_on_the_ledger_connection(queueing) == "promoting"  # what an unlocked read would answer
        assert _file_view(queueing.path) == committed_before  # the independent reader still sees ``pending``

        reading = asyncio.create_task(read(ledger))
        await asyncio.sleep(0.05)
        assert not reading.done()  # it waits for the writer, not for SQLite
        assert connection.verbs == ["BEGIN", "UPDATE", "COMMIT"]  # it has issued no SQL: parked on the ledger lock

        gate.set()
        await _finish(writer)
        await _finish(reading)
    finally:
        gate.set()
        await _settle(writer)
        if reading is not None:
            await _settle(reading)

    assert reading is not None
    assert writer.result() is True
    committed = _file_view(queueing.path)
    assert committed == _view(
        challenges=[("c1", "promoting", 0, "r")], by_status=[("promoting", "c1")],
        comparisons=[("e1", "challenger", True)], cycles=[(1, 1, 0, 0, 0)],
    )  # the write committed
    assert as_rows(reading.result()) == from_view(committed)  # the read answered what an independent reader sees
    assert connection.verbs == ["BEGIN", "UPDATE", "COMMIT", "SELECT"]  # its one SELECT ran after the COMMIT
    assert connection.outcomes == [("BEGIN", "ok"), ("UPDATE", "ok"), ("COMMIT", "ok"), ("SELECT", "ok")]
    await _assert_ledger_is_free(queueing, caplog, status="promoting")


async def test_a_read_during_a_rolled_back_write_returns_the_committed_row(
    queueing: _QueueingLedger, caplog: pytest.LogCaptureFixture,
) -> None:
    """R5 (R5-1): a read queued behind a writer that is then cancelled answers the committed row, not the write.

    The reviewer's interleaving. The writer is parked at its COMMIT, a read is queued, and the writer is cancelled at
    the gate: its COMMIT is never forwarded and its cleanup ``ROLLBACK`` undoes the UPDATE. Until then the ledger's own
    connection says ``promoting``, so a read that did not wait would have answered with a transition that never
    committed. The read answers ``pending`` (``decision_reason`` empty); on the connection's record the writer's calls
    end with its ROLLBACK, and the read's SELECT follows it.
    """
    ledger, connection = queueing.ledger, queueing.connection
    assert _file_view(queueing.path) == _view()  # premise: the independent reader sees the committed challenger
    gate = asyncio.Event()
    connection.commit_gate = gate
    writer = asyncio.create_task(ledger.set_status("c1", "promoting", reason="r", expected=("pending",)))
    reading: asyncio.Task[ChallengeRecord | None] | None = None
    try:
        await asyncio.wait_for(connection.commit_started.wait(), timeout=10.0)
        # Premises: the writer is parked at its COMMIT with its UPDATE applied, and nothing is committed.
        assert connection.verbs == ["BEGIN", "UPDATE", "COMMIT"]
        assert queueing.in_transaction is True and not writer.done()
        assert await _status_on_the_ledger_connection(queueing) == "promoting"  # what an unlocked read would answer
        assert _file_view(queueing.path) == _view()  # the independent reader still sees ``pending``

        reading = asyncio.create_task(ledger.get("c1"))
        await asyncio.sleep(0.05)
        assert not reading.done()  # the read is queued behind the writer, not answered with its uncommitted status

        writer.cancel()  # at the gate: the COMMIT is never forwarded, and the cleanup ROLLBACK undoes the UPDATE
        await _finish(writer)
        await _finish(reading)
    finally:
        gate.set()
        await _settle(writer)
        if reading is not None:
            await _settle(reading)

    assert reading is not None
    assert writer.cancelled()
    record = reading.result()
    assert record is not None and (record.status, record.decision_reason) == ("pending", "")
    assert _file_view(queueing.path) == _view()
    assert connection.verbs == ["BEGIN", "UPDATE", "COMMIT", "ROLLBACK", "SELECT"]  # the SELECT ran after the ROLLBACK
    assert connection.outcomes == [("BEGIN", "ok"), ("UPDATE", "ok"), ("ROLLBACK", "ok"), ("SELECT", "ok")]  # no COMMIT
    await _assert_ledger_is_free(queueing, caplog, status="pending")


@pytest.mark.usefixtures("deterministic_embeddings")
async def test_find_matching_waits_for_a_rolled_back_promotion_and_routes_the_champion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R5 (R5-1): a routing lookup waits for an in-flight promotion; once it is rolled back the champion routes alone.

    The reviewer's route: ``find_matching`` -> ``_get_index_row`` -> ``ledger.get``, issued while a dream's
    ``set_status("chal", "promoting")`` is between its UPDATE and its COMMIT. Read on the writer's connection, ``chal``
    was ``promoting``, which routes (R3-5); the write was then cancelled and rolled back, the row is ``pending`` again,
    and ``chal`` had routed for the lookups that overlapped it. The lookup now waits behind the writer, and once the
    cancelled write has been rolled back it routes the champion only. The ledger's ``get`` is wrapped to signal that the
    lookup has reached it, so that "still waiting" is shown at the ledger and not merely in the semantic index.
    """
    root = tmp_path / "procedures"
    factory = _FaultingFactory(wrapper=_QueueingConnection)
    store = ProcedureStore(root, connection_factory=factory)
    gate = asyncio.Event()
    writer: asyncio.Task[bool] | None = None
    routing: asyncio.Task[list[dict[str, Any]]] | None = None
    try:
        await store.start()
        ledger = store.challenges
        assert ledger is not None, "premise: the ledger is open"
        connection = factory.connected["procedures_challenges.db"]
        assert isinstance(connection, _QueueingConnection), "premise: the factory wrapped the ledger's connection"
        await _stage_active_challenger(store, "pending")  # premises: both active in SQLite and the index

        arrived = asyncio.Event()
        real_get = ledger.get

        async def noting_get(challenger_id: str) -> ChallengeRecord | None:
            arrived.set()  # the routing lookup has reached the ledger read
            return await real_get(challenger_id)

        monkeypatch.setattr(ledger, "get", noting_get)
        connection.forget()
        connection.commit_gate = gate
        writer = asyncio.create_task(ledger.set_status("chal", "promoting", reason="r", expected=("pending",)))
        await asyncio.wait_for(connection.commit_started.wait(), timeout=10.0)
        # Premises: the writer is parked at its COMMIT with its UPDATE applied; the independent reader sees pending.
        assert connection.verbs == ["BEGIN", "UPDATE", "COMMIT"]
        assert connection.real.in_transaction is True and not writer.done()
        assert _ledger_file_status(root, "chal") == "pending"

        routing = asyncio.create_task(store.find_matching(_procedure().description))
        await asyncio.wait_for(arrived.wait(), timeout=10.0)
        await asyncio.sleep(0.05)
        assert not routing.done()  # the lookup is at the ledger read, and waits for the writer
        assert connection.verbs == ["BEGIN", "UPDATE", "COMMIT"]  # it has issued no SQL on the ledger's connection

        writer.cancel()  # at the gate: the COMMIT is never forwarded, and the cleanup ROLLBACK undoes the UPDATE
        await _finish(writer)
        await _finish(routing)

        assert writer.cancelled()
        matches = routing.result()
        assert [match["id"] for match in matches] == ["champ"]  # ``chal`` is ``pending``, not the ``promoting`` it was
        assert list(matches[0]) == _ROUTING_ROW_KEYS
        record = await ledger.get("chal")
        assert record is not None and record.status == "pending"
    finally:
        gate.set()
        if writer is not None:
            await _settle(writer)
        if routing is not None:
            await _settle(routing)
        await store.stop()
        await factory.close_all()


# ---------------------------------------------------------------------------
# Review round 6 (R6-1): lineage decisions read the columns, ``get`` keeps the snapshot
# ---------------------------------------------------------------------------


def _lifecycle_state(
    db_path: Path, procedure_id: str,
) -> tuple[tuple[int, int, int], tuple[bool, bool, int]]:
    """A procedure's ``(is_active, is_archived, compilation_level)``: its columns, then its JSON snapshot (R6-1).

    An independent reader of ``procedures.db``. ``restore_procedure`` commits the columns and swallows a refused
    ``content_snapshot`` UPDATE, and ``demote_compilation_level`` writes the column only; both leave the snapshot that
    ``ProcedureStore.get`` rebuilds a procedure from apart from the columns.
    """
    reader = sqlite3.connect(db_path)
    try:
        row = reader.execute(
            "SELECT is_active, COALESCE(is_archived, 0), compilation_level, content_snapshot "
            "FROM procedure_records WHERE id = ?", (procedure_id,),
        ).fetchone()
    finally:
        reader.close()
    assert row is not None, f"premise: {procedure_id} has a row in procedures.db"
    snapshot = json.loads(row[3])
    return (row[0], row[1], row[2]), (snapshot["is_active"], snapshot["is_archived"], snapshot["compilation_level"])


@pytest.mark.usefixtures("deterministic_embeddings")
async def test_routing_state_reads_the_columns_not_the_snapshot(tmp_path: Path) -> None:
    """R6 (R6-1): ``routing_state`` is the row's ``(is_active, superseded_by)`` columns; ``get`` keeps the snapshot.

    ``deactivate`` commits the columns and then swallows a failed ``content_snapshot`` UPDATE, so the JSON snapshot
    that ``get`` rebuilds a procedure from keeps saying active and unsuperseded: the base behaviour, which round 5 had
    changed and round 6 restored for every caller of ``get``. Admission, the published index flag and the challenger's
    activity decisions read the columns through ``routing_state``, which is ``None`` for an unknown id and for a store
    whose database is closed.
    """
    factory = _FaultingFactory()
    store = ProcedureStore(tmp_path / "procedures", connection_factory=factory)
    try:
        await store.start()
        procedures_db = factory.connected["procedures.db"]
        db_path = tmp_path / "procedures" / "procedures.db"
        await store.save(_procedure("champ"))
        procedures_db.arm(
            "UPDATE procedure_records SET content_snapshot", sqlite3.OperationalError("simulated snapshot failure"),
        )

        await store.deactivate("champ", superseded_by="chal")  # swallows the snapshot failure, as before

        # Premises: the snapshot UPDATE was refused once, and the column and the JSON snapshot now disagree.
        assert len(procedures_db.fired) == 1
        assert procedures_db.fired[0].startswith("UPDATE procedure_records SET content_snapshot")
        assert _is_active_column(db_path, "champ") == 0
        assert _snapshot_lineage(db_path, "champ") == (True, "")

        assert await store.routing_state("champ") == (False, "chal")  # the columns
        champion = await store.get("champ")  # base ``get``: the stale snapshot, nothing merged from the columns
        assert champion is not None and champion.is_active is True and champion.superseded_by == ""
        assert await store.routing_state("absent") is None  # no row

        # Positive control: a healthy saved row reads back active and unsuperseded, so the pair above is the columns'.
        await store.save(_procedure("p"))
        assert await store.routing_state("p") == (True, "")

        await store.stop()  # the database is closed: ``_db`` is unset
        assert await store.routing_state("champ") is None
    finally:
        await store.stop()
        await factory.close_all()


@pytest.mark.usefixtures("deterministic_embeddings")
async def test_restore_with_a_refused_snapshot_publishes_no_active_entry_at_a_stale_level(tmp_path: Path) -> None:
    """R6 (R6-1): a restore whose snapshot UPDATE is refused publishes no ACTIVE entry at the snapshot's old level.

    The reviewer's consumer case. ``restore_procedure`` commits the columns (``is_active=1, is_archived=0,
    compilation_level=1``), swallows a refused ``content_snapshot`` UPDATE, and publishes the object ``get`` returns to
    the semantic index. Round 5's ``get`` took ``is_active`` from the column and everything else from the snapshot, so
    the entry was ACTIVE at the snapshot's level 4, and ``CognitiveAgent._check_procedural_memory`` dispatches on the
    level it reads from ``get``: a procedure restored to Level 1 replayed autonomously. With ``get`` reading the
    snapshot again the entry is inactive, and the procedure does not route until it is saved again (Blind spot 18).
    """
    factory = _FaultingFactory()
    store = ProcedureStore(tmp_path / "procedures", connection_factory=factory)
    description = _procedure().description
    try:
        await store.start()
        procedures_db = factory.connected["procedures.db"]
        db_path = tmp_path / "procedures" / "procedures.db"
        procedure = _procedure("p")
        procedure.compilation_level = 4
        procedure.last_used_at = 1_000.0
        await store.save(procedure)
        # Control: while ``p`` is active at level 4 the lookup below finds it, so its later absence is the entry's.
        assert [match["id"] for match in await store.find_matching(description, min_compilation_level=2)] == ["p"]
        await store.demote_compilation_level("p", 1)  # the column only: the snapshot keeps saying level 4
        archived = await store.archive_stale_procedures(now=1_000.0 + (LIFECYCLE_ARCHIVE_DAYS + 1) * 86_400)
        assert [entry["id"] for entry in archived] == ["p"]  # premise: unused at Level 1 for long enough, so archived
        procedures_db.arm(
            "UPDATE procedure_records SET content_snapshot", sqlite3.OperationalError("simulated snapshot failure"),
        )

        assert await store.restore_procedure("p") is True

        # Premises: the snapshot UPDATE was refused once, and the columns and the JSON snapshot disagree.
        assert len(procedures_db.fired) == 1
        assert procedures_db.fired[0].startswith("UPDATE procedure_records SET content_snapshot")
        columns, snapshot = _lifecycle_state(db_path, "p")
        assert columns == (1, 0, 1)  # (is_active, is_archived, compilation_level): restored to Level 1
        assert snapshot == (False, True, 4)  # the JSON still says inactive, archived, level 4

        restored = await store.get("p")  # base ``get``: nothing is merged from the columns
        assert restored is not None and restored.is_active is False and restored.compilation_level == 4
        assert _index_says_active(store, "p") is False  # no ACTIVE entry whose replay level contradicts the column
        matches = await store.find_matching(description, min_compilation_level=2)
        assert "p" not in [match["id"] for match in matches]
    finally:
        await store.stop()
        await factory.close_all()
