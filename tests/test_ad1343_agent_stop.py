"""AD-1343 S1 (#1595): the Captain's stop for one crew agent: the record and its store, the Captain routes and the sinks (T1 to T26).

The tests of ``prompts/ad-1343-captain-agent-stop-s1.md`` for Sections 1 to 8: ``AgentStopService`` over a real ``agent_stops.db``
in ``tmp_path`` (T1 to T13), the tool sink and the projected correction registry (T14 to T16), Ward Room routing (T17), the
browser ACK (T18), the Captain routes under ``/api/stops`` driven through ``httpx.ASGITransport`` on the test's own loop (T19 to
T25) and the refusal a sender reads (T26). The seam census is ``tests/test_ad1343_stop_seam_inventory.py``; the crossing tests,
which boot a real runtime, are ``tests/test_ad1343_stop_crossing.py``.

Every store lives in ``tmp_path``; the live data directory is never read. The connection factory that makes one statement fail
(T4, T5, T23, T24) is test-local. Nothing here sleeps, waits on a timer or orders anything by wall-clock time: the service's
clock is injected, and rows are read in insertion order with the standard library, never through the service under test.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

from probos.agent_stop import (
    LIFT_NOTE,
    MAX_REASON_CHARS,
    S1_SCOPE,
    SEAM_INTENT,
    SEAM_TOOL,
    SEAM_WARD_ROOM,
    SEAMS,
    AgentStopService,
    StopNotFound,
    active_stop,
)
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.config import AuthConfig, SystemConfig
from probos.dm_reply import DmReply
from probos.routers import agent_stop as stop_routes
from probos.storage.sqlite_factory import default_factory
from probos.substrate.event_log import EventLog
from probos.types import IntentMessage

AGENT = "ad1343_surgeon_0_3c9a1f20"  # a slot id, as BF-907 keys trust and identity
OTHER = "ad1343_counselor_0_8d41b7e6"
THIRD = "ad1343_architect_0_1d2e3f40"
VISITOR = "ad1343_visitor_0_77aa0042"
OVERRIDER = "ad1343_overrider_0_90b13d55"
CONSULT_OVERRIDER = "ad1343_consultant_0_5e6f7a81"
DID = "did:probos:ad1343-ship:agent:7f0c2f4e-3d0a-4d3e-9f57-0c5f1d6b2a11"
CERTIFICATE_UUID = "7f0c2f4e-3d0a-4d3e-9f57-0c5f1d6b2a11"
CREW_TYPE = "ad1343_crew"
VISITOR_TYPE = "ad1343_visitor"
REASON = "AD-1343 test: the Captain's private reason for the stop"
LIFT_REASON = "AD-1343 test: the Captain's private reason for the lift"
PRIVATE_FRAGMENT = "Captain's private reason"  # in both reasons above; no order, event or answer to a sender may carry it
TOKEN = "ad1343-crew-scope-token"
STOPS = "/api/stops"


class _Clock:
    """Test-local clock: ``_Clock()`` ticks one second per reading from a fixed start; ``_Clock(5.0, 3.0)`` answers those readings first."""

    def __init__(self, *readings: float) -> None:
        self._readings = list(readings)
        self._now = 1_700_000_000.0

    def __call__(self) -> float:
        if self._readings:
            return self._readings.pop(0)
        self._now += 1.0
        return self._now


class _FlakyConnection:
    """Test-local connection wrapper: forwards every call; an ``execute`` whose statement starts with a ``fail_on`` prefix raises."""

    def __init__(self, inner: Any, factory: _FlakyFactory) -> None:
        self._inner = inner
        self._factory = factory

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
        self._factory.statements.append(sql)
        if sql.lstrip().startswith(self._factory.fail_on):
            raise sqlite3.OperationalError("disk I/O error (simulated by the test)")
        return self._inner.execute(sql, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _FlakyFactory:
    """Test-local connection factory: the SQLite default, but a statement starting with a ``fail_on`` prefix raises."""

    def __init__(self, *fail_on: str) -> None:
        self.fail_on = fail_on
        self.statements: list[str] = []

    async def connect(self, db_path: str) -> _FlakyConnection:
        return _FlakyConnection(await default_factory.connect(db_path), self)


class _FailingEventLog:
    """Test-local event log whose ``log`` always raises, as a locked ``events.db`` does once the write budget is spent."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def log(self, *args: Any, **kwargs: Any) -> int | None:
        self.calls.append(kwargs.get("event", ""))
        raise TimeoutError("AD-1343 test: the EventLog write budget is spent")


class _StrSubclass(str):
    """A ``str`` that is not exactly a ``str``: the service accepts only the real type."""


class _OverridingAgent(CognitiveAgent):
    """A crew agent whose own ``handle_intent`` is not the one the stop guards."""

    async def handle_intent(self, intent: Any) -> Any:
        return None


class _ConsultOverridingAgent(CognitiveAgent):
    """A crew agent that overrides only ``handle_consultation_request``: the stop does not guard that either."""

    async def handle_consultation_request(self, *args: Any, **kwargs: Any) -> Any:
        return None


class _FakeOntology:
    def __init__(self, *crew_types: str) -> None:
        self._crew_types = frozenset(crew_types)

    def get_crew_agent_types(self) -> frozenset[str]:
        return self._crew_types


class _FakeRegistry:
    def __init__(self, *agents: Any) -> None:
        self._agents = {agent.id: agent for agent in agents}

    def get(self, agent_id: str) -> Any:
        return self._agents.get(agent_id)


class _FakeIdentities:
    """Test-local identity registry: ``resolve_slot_id`` answers from a table, as BF-907's resolver does, and None otherwise."""

    def __init__(self, slots: dict[str, str]) -> None:
        self._slots = slots

    def resolve_slot_id(self, identity: str) -> str | None:
        return self._slots.get(identity)


def _agent(agent_id: str, agent_type: str, cls: type[CognitiveAgent] = CognitiveAgent) -> CognitiveAgent:
    agent = cls.__new__(cls)
    agent.id = agent_id
    agent.agent_type = agent_type
    return agent


def _stop_rows(data_dir: Path) -> list[dict[str, Any]]:
    """Every row of ``agent_stops.db`` in insertion order, read with the standard library."""
    with contextlib.closing(sqlite3.connect(data_dir / "agent_stops.db")) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM agent_stops ORDER BY rowid")]


def _stop_log(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    """What ``probos.agent_stop`` logged, as ``(level, message)``."""
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == "probos.agent_stop"]


def _bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@contextlib.asynccontextmanager
async def _service(data_dir: Path, **kwargs: Any) -> AsyncIterator[AgentStopService]:
    """A started ``AgentStopService`` over ``data_dir``, closed when the block ends."""
    service = AgentStopService(data_dir=data_dir, **kwargs)
    await service.start()
    try:
        yield service
    finally:
        await service.stop()


@contextlib.asynccontextmanager
async def _client(runtime: Any) -> AsyncIterator[httpx.AsyncClient]:
    """The stop router on a minimal app over ``runtime``, called in the test's own loop (never ``TestClient``)."""
    app = FastAPI()
    app.include_router(stop_routes.router)
    app.state.runtime = runtime
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@dataclass
class _Rig:
    service: AgentStopService
    runtime: SimpleNamespace
    client: httpx.AsyncClient
    data_dir: Path


@contextlib.asynccontextmanager
async def _rig(
    tmp_path: Path,
    *,
    token: str = TOKEN,
    fail_on: tuple[str, ...] = (),
    clock: Callable[[], float] | None = None,
    identities: dict[str, str] | None = None,
) -> AsyncIterator[_Rig]:
    """A real service on ``tmp_path / "stops"`` behind the router, over a registry of crew, a visitor and an overrider."""
    factory = _FlakyFactory(*fail_on) if fail_on else None
    data_dir = tmp_path / "stops"
    async with _service(data_dir, connection_factory=factory, clock=clock or _Clock()) as service:
        runtime = SimpleNamespace(
            agent_stops=service,
            config=SystemConfig(auth=AuthConfig(crew_scope_token=token)),
            registry=_FakeRegistry(
                _agent(AGENT, CREW_TYPE),
                _agent(OTHER, CREW_TYPE),
                _agent(VISITOR, VISITOR_TYPE),
                _agent(OVERRIDER, CREW_TYPE, _OverridingAgent),
                _agent(CONSULT_OVERRIDER, CREW_TYPE, _ConsultOverridingAgent),
            ),
            ontology=_FakeOntology(CREW_TYPE),
            identity_registry=_FakeIdentities(identities or {}),
        )
        async with _client(runtime) as client:
            yield _Rig(service, runtime, client, data_dir)


# ---------------------------------------------------------------------------
# The record and its store (T1 to T8)
# ---------------------------------------------------------------------------


# T1
async def test_a_stop_is_applied_written_and_survives_a_restart(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    async with _service(tmp_path, clock=_Clock()) as first:
        assert first.stop_for(AGENT) is None  # premise: a fresh store stops nobody
        issued = await first.issue_stop(AGENT, reason=REASON)
        assert issued.durable is True and issued.already_stopped is False
        assert first.stop_for(AGENT) == issued.record  # applied to the view every seam reads
    record = issued.record
    assert (record.agent_id, record.reason, record.issued_by) == (AGENT, REASON, "captain")

    with caplog.at_level(logging.WARNING, logger="probos.agent_stop"):
        async with _service(tmp_path) as second:
            assert second.stop_for(AGENT) == record  # the same order read back from the file: id, reason, issuer and time
            warned = [line for level, line in _stop_log(caplog) if level == logging.WARNING]
            assert any(AGENT in line for line in warned)  # the startup warning names every agent still stopped (D10)
            second.refusal(AGENT, SEAM_INTENT)
            lifted = await second.lift_stop(AGENT, reason=LIFT_REASON)
            assert lifted.record == record and lifted.refused == {"intent": 1}
            assert second.stop_for(AGENT) is None

    async with _service(tmp_path) as third:
        assert third.stop_for(AGENT) is None  # a lifted order is not loaded again
    rows = _stop_rows(tmp_path)
    assert len(rows) == 1  # the lift updated its row; nothing was deleted
    row = rows[0]
    assert (row["stop_id"], row["agent_id"], row["reason"], row["issued_by"]) == (record.stop_id, AGENT, REASON, "captain")
    assert row["lifted_by"] == "captain" and row["lift_reason"] == LIFT_REASON and row["lifted_at"] == lifted.lifted_at
    assert json.loads(row["refused_json"]) == {"intent": 1}


# T2
async def test_issuing_twice_keeps_one_active_order(tmp_path: Path) -> None:
    async with _service(tmp_path, clock=_Clock()) as service:
        first = await service.issue_stop(AGENT, reason=REASON)
        assert first.durable is True and first.already_stopped is False  # premise: the first issue wrote an order
        second = await service.issue_stop(AGENT, reason="AD-1343 test: a second reason that must not replace the first")
        assert second.already_stopped is True and second.durable is True
        assert second.record == first.record  # the order in force comes back unchanged: same id, same reason
        assert service.active() == (first.record,)
    rows = _stop_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["lifted_at"] is None  # one row, in force


# T2 (concurrent)
async def test_three_concurrent_issues_make_one_order(tmp_path: Path) -> None:
    async with _service(tmp_path, clock=_Clock()) as service:
        assert service.stop_for(AGENT) is None  # premise: nothing is stopped yet
        results = await asyncio.gather(*(service.issue_stop(AGENT, reason=REASON) for _ in range(3)))
        assert sorted(result.already_stopped for result in results) == [False, True, True]  # exactly one issue made the order
        assert len({result.record.stop_id for result in results}) == 1  # and all three answer with that same order
        assert service.active() == (results[0].record,)
    rows = _stop_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["lifted_at"] is None  # one row, in force


# T3
async def test_a_lifted_agent_can_be_stopped_again_and_history_is_kept(tmp_path: Path) -> None:
    async with _service(tmp_path, clock=_Clock()) as service:
        first = await service.issue_stop(AGENT, reason=REASON)
        await service.lift_stop(AGENT, reason=LIFT_REASON)
        assert service.stop_for(AGENT) is None  # premise: the first order is lifted
        second = await service.issue_stop(AGENT, reason=REASON)
        assert second.durable is True and second.already_stopped is False
        assert second.record.stop_id != first.record.stop_id
        assert service.stop_for(AGENT) == second.record
        assert service.refused_counts(second.record.stop_id) == {}  # counts belong to an order, so a new order starts at zero
    rows = _stop_rows(tmp_path)
    assert [row["stop_id"] for row in rows] == [first.record.stop_id, second.record.stop_id]  # both orders are on record
    assert [row["lifted_at"] is None for row in rows] == [False, True]  # the first lifted, the second in force
    async with _service(tmp_path) as restarted:  # a restart loads the second order, not the lifted first
        assert restarted.stop_for(AGENT) is not None and restarted.stop_for(AGENT).stop_id == second.record.stop_id
        assert restarted.stop_for(AGENT).stop_id != first.record.stop_id
    assert [row["stop_id"] for row in _stop_rows(tmp_path)] == [first.record.stop_id, second.record.stop_id]  # both rows still on file


# T4
async def test_a_failed_write_still_stops_the_agent_until_restart(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    factory = _FlakyFactory("INSERT", "UPDATE")
    with caplog.at_level(logging.ERROR, logger="probos.agent_stop"):
        async with _service(tmp_path, connection_factory=factory, clock=_Clock()) as service:
            issued = await service.issue_stop(AGENT, reason=REASON)
            assert any(sql.lstrip().startswith("INSERT") for sql in factory.statements)  # premise: the write was tried, and failed
            assert issued.durable is False and issued.already_stopped is False
            assert service.refusal(AGENT, SEAM_TOOL) == issued.record  # the agent is stopped all the same
            again = await service.issue_stop(AGENT, reason=REASON)
            assert again.already_stopped is True and again.record == issued.record
            assert again.durable is False  # asked again, the answer is still honest about the unwritten order

            async with _service(tmp_path) as restarted:  # a restart reads the file, which never got the order
                assert restarted.stop_for(AGENT) is None
            assert _stop_rows(tmp_path) == []

            factory.statements.clear()
            lifted = await service.lift_stop(AGENT, reason=LIFT_REASON)  # UPDATE would raise: the lift must not write
            assert lifted.record == issued.record and lifted.refused == {"tool": 1}
            assert service.stop_for(AGENT) is None
            assert not any(sql.lstrip().startswith("UPDATE") for sql in factory.statements)
    assert any(level == logging.ERROR and issued.record.stop_id in line for level, line in _stop_log(caplog))  # the failure is loud


# T5
async def test_a_failed_lift_write_leaves_the_agent_stopped(tmp_path: Path) -> None:
    factory = _FlakyFactory("UPDATE")
    async with _service(tmp_path, connection_factory=factory, clock=_Clock()) as service:
        issued = await service.issue_stop(AGENT, reason=REASON)
        assert issued.durable is True  # premise: the order was written; only the lift's write fails
        service.refusal(AGENT, SEAM_INTENT)
        with pytest.raises(sqlite3.OperationalError):
            await service.lift_stop(AGENT, reason=LIFT_REASON)
        assert service.stop_for(AGENT) == issued.record  # written before applied: the agent is still stopped
        assert service.refused_counts(issued.record.stop_id) == {"intent": 1}  # and nothing was discarded
    rows = _stop_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["lifted_at"] is None
    async with _service(tmp_path) as restarted:
        assert restarted.stop_for(AGENT) == issued.record  # a restart still finds the order


# T6
async def test_lifting_an_agent_that_is_not_stopped_raises(tmp_path: Path) -> None:
    async with _service(tmp_path, clock=_Clock()) as service:
        with pytest.raises(StopNotFound):
            await service.lift_stop(AGENT, reason=LIFT_REASON)  # never stopped
        await service.issue_stop(AGENT, reason=REASON)
        await service.lift_stop(AGENT, reason=LIFT_REASON)
        assert service.stop_for(AGENT) is None  # premise: the one order is lifted
        with pytest.raises(StopNotFound):
            await service.lift_stop(AGENT, reason=LIFT_REASON)  # already lifted
        with pytest.raises(StopNotFound):
            await service.lift_stop(OTHER, reason=LIFT_REASON)  # another agent, never stopped
    rows = _stop_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["lift_reason"] == LIFT_REASON  # the refused lifts wrote nothing


# T7
async def test_a_reason_is_required_and_bounded(tmp_path: Path) -> None:
    bad_reasons = ("", "   ", "\t\r\n", "x" * (MAX_REASON_CHARS + 1), None, 7, b"a reason", _StrSubclass("a reason"))
    async with _service(tmp_path, clock=_Clock()) as service:
        for bad in bad_reasons:
            with pytest.raises(ValueError):
                await service.issue_stop(AGENT, reason=bad)  # type: ignore[arg-type]
            assert service.stop_for(AGENT) is None  # nothing applied
        for bad_id in ("", None, 7, b"agent", _StrSubclass(AGENT)):
            with pytest.raises(ValueError):
                await service.issue_stop(bad_id, reason=REASON)  # type: ignore[arg-type]  # an agent id is a non-empty str too
        assert service.active() == ()
        assert _stop_rows(tmp_path) == []

        await service.issue_stop(AGENT, reason=REASON)
        for bad in bad_reasons:
            with pytest.raises(ValueError):
                await service.lift_stop(AGENT, reason=bad)  # type: ignore[arg-type]  # the lift's reason is bounded the same way
            assert service.stop_for(AGENT) is not None  # nothing lifted

        edge = "y" * MAX_REASON_CHARS
        assert (await service.issue_stop(OTHER, reason=edge)).record.reason == edge  # the bound is inclusive
        padded = await service.issue_stop(THIRD, reason="  keep this  ")
        assert padded.record.reason == "keep this"  # stored stripped

        # the minimum is one character, not two: a one-character reason is valid for an order and for its lift
        one_char = await service.issue_stop(VISITOR, reason="x")
        assert one_char.record.reason == "x" and one_char.already_stopped is False
        assert (await service.lift_stop(VISITOR, reason="x")).record == one_char.record
        assert service.stop_for(VISITOR) is None
        assert _stop_rows(tmp_path)[-1]["lift_reason"] == "x"


# T8
async def test_refusals_are_counted_by_seam_and_an_unknown_seam_is_a_bug(tmp_path: Path) -> None:
    assert SEAMS == frozenset({
        "intent", "consultation", "tool", "proactive", "ward_room", "dm_route", "group_fanout", "browser_action_ack",
        "agentic_run", "delegation",  # A2 (F1): the run entry and correction rounds; a delegated task
        "agent_work",  # AD-1347 S1 (#1627): a create refused for a stopped requester is counted at its own seam
    })  # the seam names the Captain reads in every answer
    async with _service(tmp_path, clock=_Clock()) as service:
        record = (await service.issue_stop(AGENT, reason=REASON)).record
        assert service.refusal(OTHER, SEAM_INTENT) is None  # not stopped: no refusal and nothing counted
        assert service.refused_counts(record.stop_id) == {}
        for seam in (SEAM_INTENT, SEAM_INTENT, SEAM_TOOL, SEAM_WARD_ROOM):
            assert service.refusal(AGENT, seam) == record
        base = {"intent": 2, "tool": 1, "ward_room": 1}
        assert service.refused_counts(record.stop_id) == base

        for bad in ("ad1343-no-such-seam", "", "Intent"):
            with pytest.raises(ValueError):
                service.refusal(AGENT, bad)
        with pytest.raises(ValueError):
            service.refusal(OTHER, "ad1343-no-such-seam")  # a bug even for an agent that is not stopped
        assert service.refused_counts(record.stop_id) == base  # an unknown seam counted nothing

        copy = service.refused_counts(record.stop_id)
        copy["intent"] = 99
        assert service.refused_counts(record.stop_id) == base  # the answer is a copy

        for seam in SEAMS:
            assert service.refusal(AGENT, seam) == record  # every seam constant is accepted
        counted = {seam: base.get(seam, 0) + 1 for seam in SEAMS}
        assert service.refused_counts(record.stop_id) == counted

        lifted = await service.lift_stop(AGENT, reason=LIFT_REASON)
        assert lifted.refused == counted  # the counts come back in the lift
        assert service.refused_counts(record.stop_id) == {}  # and go with the order


async def test_a_refusal_logs_info_once_per_seam_then_debug_and_never_the_reason(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    # Pins the level choice in AgentStopService.refusal: the first refusal at a seam is INFO, every later one at
    # that seam is DEBUG, so a stopped agent that keeps being offered work cannot flood the INFO log.
    with caplog.at_level(logging.DEBUG, logger="probos.agent_stop"):
        async with _service(tmp_path, clock=_Clock()) as service:
            record = (await service.issue_stop(AGENT, reason=REASON)).record
            seen = list(_stop_log(caplog))  # everything the stop logger wrote, kept across the clears below
            caplog.clear()
            assert [line for line in _stop_log(caplog) if line[0] >= logging.INFO] == []  # premise: only refusals follow

            assert service.refusal(AGENT, SEAM_INTENT) == record
            first = _stop_log(caplog)
            seen += first
            assert len(first) == 1
            assert first[0][0] == logging.INFO
            for fragment in (SEAM_INTENT, AGENT, record.stop_id, "(1 at this seam)"):
                assert fragment in first[0][1]

            caplog.clear()
            assert service.refusal(AGENT, SEAM_INTENT) == record
            second = _stop_log(caplog)
            seen += second
            assert [line for line in second if line[0] >= logging.INFO] == []  # the repeat never reaches INFO
            assert len(second) == 1
            assert second[0][0] == logging.DEBUG
            assert "(2 at this seam)" in second[0][1]

            caplog.clear()
            assert service.refusal(AGENT, SEAM_TOOL) == record
            other_seam = _stop_log(caplog)
            seen += other_seam
            assert len(other_seam) == 1
            assert other_seam[0][0] == logging.INFO  # the count is per seam
            assert SEAM_TOOL in other_seam[0][1]
            assert "(1 at this seam)" in other_seam[0][1]

            caplog.clear()
            assert service.refusal(OTHER, SEAM_INTENT) is None
            assert _stop_log(caplog) == []  # an agent that is not stopped writes nothing

        assert len(seen) >= 3  # premise: the check below looked at the three refusal lines
        assert not any(PRIVATE_FRAGMENT in message for _, message in seen)  # the Captain's reason is never logged


# T9
async def test_the_eventlog_records_order_and_lift_with_the_captain_and_without_the_reason(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    event_log = EventLog(db_path=tmp_path / "events.db")
    await event_log.start()
    try:
        with caplog.at_level(logging.DEBUG, logger="probos.agent_stop"):
            async with _service(tmp_path / "stops", event_log=event_log, clock=_Clock()) as service:
                issued = await service.issue_stop(AGENT, reason=REASON)
                service.refusal(AGENT, SEAM_INTENT)
                lifted = await service.lift_stop(AGENT, reason=LIFT_REASON)
    finally:
        await event_log.stop()

    with contextlib.closing(sqlite3.connect(tmp_path / "events.db")) as conn:
        everything = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
        stop_rows = conn.execute(
            "SELECT category, event, agent_id, data FROM events WHERE category = 'agent_stop' ORDER BY id"
        ).fetchall()
    assert [(row[0], row[1], row[2]) for row in stop_rows] == [
        ("agent_stop", "agent_stop_issued", AGENT),
        ("agent_stop", "agent_stop_lifted", AGENT),
    ]
    issued_data, lifted_data = (json.loads(row[3]) for row in stop_rows)
    assert issued_data["initiated_by"] == "captain" and lifted_data["initiated_by"] == "captain"
    assert issued_data["stop_id"] == lifted_data["stop_id"] == issued.record.stop_id
    assert issued_data["issued_at"] == issued.record.issued_at and issued_data["durable"] is True
    assert issued_data["reason_chars"] == len(REASON)
    assert lifted_data["lifted_at"] == lifted.lifted_at and lifted_data["refused"] == {"intent": 1}
    assert PRIVATE_FRAGMENT not in json.dumps(everything, default=str)  # no column of any row carries a reason: agents can query this log
    # privacy by allowlist: the data of each row has exactly these keys, so a new key (a reason, say) fails here
    assert set(issued_data) == {"stop_id", "initiated_by", "issued_at", "reason_chars", "durable"}
    assert set(lifted_data) == {"stop_id", "initiated_by", "issued_at", "lifted_at", "refused"}
    logged = _stop_log(caplog)
    assert len(logged) >= 1  # premise: the stop logger wrote at least the refusal line, so the check below looks at something
    for _, message in logged:
        assert PRIVATE_FRAGMENT not in message and REASON not in message and LIFT_REASON not in message  # no log line carries a reason


# T10
async def test_an_eventlog_failure_does_not_undo_a_stop(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    event_log = _FailingEventLog()
    with caplog.at_level(logging.WARNING, logger="probos.agent_stop"):
        async with _service(tmp_path, event_log=event_log, clock=_Clock()) as service:
            issued = await service.issue_stop(AGENT, reason=REASON)
            assert event_log.calls == ["agent_stop_issued"]  # premise: the EventLog was asked, and raised
            assert issued.durable is True and issued.already_stopped is False
            assert service.stop_for(AGENT) == issued.record  # the stop is applied
            assert [row["stop_id"] for row in _stop_rows(tmp_path)] == [issued.record.stop_id]  # and written

            lifted = await service.lift_stop(AGENT, reason=LIFT_REASON)  # the lift survives the same failure
            assert event_log.calls == ["agent_stop_issued", "agent_stop_lifted"]
            assert lifted.record == issued.record and service.stop_for(AGENT) is None
    warned = [line for level, line in _stop_log(caplog) if level == logging.WARNING]
    assert sum(issued.record.stop_id in line for line in warned) == 2  # one visible warning per lost event
    assert _stop_rows(tmp_path)[0]["lifted_at"] == lifted.lifted_at


# T11
async def test_start_raises_when_the_store_cannot_be_opened(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("a file where the data directory should be", encoding="utf-8")
    assert blocker.is_file()  # premise: the data directory path is a file
    service = AgentStopService(data_dir=blocker)
    with pytest.raises(OSError):
        await service.start()
    assert service.stop_for(AGENT) is None  # nothing was loaded
    await service.stop()  # closing a service that never opened is harmless


# T12
async def test_closing_keeps_the_in_memory_view(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    service = AgentStopService(data_dir=tmp_path, clock=_Clock())
    await service.start()
    try:
        issued = await service.issue_stop(AGENT, reason=REASON)
        assert issued.durable is True  # premise: written while the store was open
        await service.stop()
        assert service.stop_for(AGENT) == issued.record  # the view outlives the store
        assert service.refusal(AGENT, SEAM_INTENT) == issued.record  # and still refuses

        with caplog.at_level(logging.ERROR, logger="probos.agent_stop"):
            late = await service.issue_stop(OTHER, reason=REASON)
        assert late.durable is False and service.stop_for(OTHER) == late.record  # stopped, though the closed store cannot hold it
        errors = [line for level, line in _stop_log(caplog) if level == logging.ERROR]
        assert len(errors) == 1  # the unwritten order is loud, once
        for fragment in (late.record.stop_id, OTHER, "NOT written"):
            assert fragment in errors[0]
        with pytest.raises(RuntimeError):
            await service.lift_stop(AGENT, reason=LIFT_REASON)  # the closed store cannot take the lift ...
        assert service.stop_for(AGENT) == issued.record  # ... so the stop stays in force
        lifted_late = await service.lift_stop(OTHER, reason=LIFT_REASON)  # an order that never reached the store needs none
        assert lifted_late.record == late.record and service.stop_for(OTHER) is None
    finally:
        await service.stop()  # closing twice is harmless
    rows = _stop_rows(tmp_path)
    assert [row["agent_id"] for row in rows] == [AGENT] and rows[0]["lifted_at"] is None


# T13
async def test_only_a_real_service_answers(tmp_path: Path) -> None:
    async with _service(tmp_path, clock=_Clock()) as service:
        record = (await service.issue_stop(AGENT, reason=REASON)).record
        assert active_stop(service, AGENT, SEAM_INTENT) == record  # premise: a real service answers
        assert service.refused_counts(record.stop_id) == {"intent": 1}

        assert active_stop(None, AGENT, SEAM_INTENT) is None
        gate = MagicMock()
        assert active_stop(gate, AGENT, SEAM_INTENT) is None
        gate.refusal.assert_not_called()  # a double that is not the service is never asked
        spec_gate = MagicMock(spec=AgentStopService)
        assert active_stop(spec_gate, AGENT, SEAM_INTENT) is None  # asked, but only an exact StopRecord is believed
        spec_gate.refusal.assert_called_once_with(AGENT, SEAM_INTENT)

        for bad_id in (None, 7, b"agent", _StrSubclass(AGENT)):
            assert active_stop(service, bad_id, SEAM_INTENT) is None
            assert service.stop_for(bad_id) is None  # type: ignore[arg-type]
        assert service.refused_counts(record.stop_id) == {"intent": 1}  # none of those counted a refusal


# ---------------------------------------------------------------------------
# The Captain routes (T19 to T25) and the sender's refusal (T26)
# ---------------------------------------------------------------------------


# T19
async def test_the_stop_routes_refuse_an_open_gate(tmp_path: Path) -> None:
    async with _rig(tmp_path, token="") as rig:
        assert rig.runtime.config.auth.crew_scope_token == ""  # premise: no token, so require_crew_scope lets every caller through
        responses = [
            await rig.client.get(STOPS),
            await rig.client.post(f"{STOPS}/{AGENT}", json={"reason": REASON}),
            await rig.client.post(f"{STOPS}/{AGENT}/lift", json={"reason": LIFT_REASON}),
            await rig.client.post(f"{STOPS}/{AGENT}", json={"reason": REASON}, headers=_bearer("any-token-at-all")),
        ]
        applied = rig.service.active()
    assert [response.status_code for response in responses] == [403, 403, 403, 403]
    assert {response.json()["detail"] for response in responses} == {"agent_stop_requires_crew_scope_token"}
    assert applied == () and _stop_rows(rig.data_dir) == []  # the store was not touched

    runtime = SimpleNamespace(agent_stops=None, config=SystemConfig())  # no service yet: 503 comes before the token question
    async with _client(runtime) as client:
        unavailable = await client.get(STOPS)
    assert unavailable.status_code == 503 and unavailable.json()["detail"] == "agent_stop_unavailable"


# T20
async def test_the_stop_routes_require_the_captain_token(tmp_path: Path) -> None:
    refused_calls = (
        ("GET", STOPS, None),
        ("POST", f"{STOPS}/{AGENT}", {"reason": REASON}),
        ("POST", f"{STOPS}/{AGENT}/lift", {"reason": LIFT_REASON}),
    )
    async with _rig(tmp_path, clock=_Clock(2000.0, 1000.0)) as rig:
        assert rig.runtime.config.auth.crew_scope_token == TOKEN  # premise: a token is configured
        refused = []
        for method, path, body in refused_calls:
            refused.append((await rig.client.request(method, path, json=body)).status_code)  # no Authorization header
            refused.append((await rig.client.request(method, path, json=body, headers=_bearer("a-wrong-token"))).status_code)
        applied = rig.service.active()

        listed_empty = await rig.client.get(STOPS, headers=_bearer())
        issued = await rig.client.post(f"{STOPS}/{AGENT}", json={"reason": REASON}, headers=_bearer())
        issued_other = await rig.client.post(f"{STOPS}/{OTHER}", json={"reason": REASON}, headers=_bearer())
        rig.service.refusal(AGENT, SEAM_INTENT)
        listed = await rig.client.get(STOPS, headers=_bearer())
        lifted = await rig.client.post(f"{STOPS}/{AGENT}/lift", json={"reason": LIFT_REASON}, headers=_bearer())
    assert refused == [401] * 6
    assert applied == ()  # a refused call applied nothing
    assert [r.status_code for r in (listed_empty, issued, issued_other, listed, lifted)] == [200] * 5
    assert listed_empty.json() == {"stops": [], "scope": S1_SCOPE}
    stops = listed.json()["stops"]
    assert [stop["agent_id"] for stop in stops] == [OTHER, AGENT]  # oldest first: OTHER was issued at 1000.0, AGENT at 2000.0
    assert [stop["refused"] for stop in stops] == [{}, {"intent": 1}]  # refusals by seam since this start
    assert all(stop["reason"] == REASON for stop in stops)  # the Captain sees the reason
    assert listed.json()["scope"] == S1_SCOPE


# T21
async def test_issue_resolves_a_did_to_the_slot_and_answers_with_scope(tmp_path: Path) -> None:
    async with _rig(tmp_path, identities={DID: AGENT, CERTIFICATE_UUID: AGENT}) as rig:
        by_did = await rig.client.post(f"{STOPS}/{DID}", json={"reason": REASON}, headers=_bearer())
        in_force = rig.service.stop_for(AGENT)
        by_slot = await rig.client.post(f"{STOPS}/{OTHER}", json={"reason": REASON}, headers=_bearer())  # a slot id is kept as given
        lifted = await rig.client.post(f"{STOPS}/{CERTIFICATE_UUID}/lift", json={"reason": LIFT_REASON}, headers=_bearer())
    assert by_did.status_code == 200, by_did.text
    body = by_did.json()
    assert body["status"] == "stopped" and body["already_stopped"] is False
    assert body["stop"]["agent_id"] == AGENT  # the slot id, not the DID the Captain typed
    assert body["scope"] == S1_SCOPE
    assert in_force is not None and in_force.stop_id == body["stop"]["stop_id"]
    assert body["stop"]["since"] == "2023-11-14T22:13:21+00:00"  # the first reading of the injected clock
    assert by_slot.status_code == 200 and by_slot.json()["stop"]["agent_id"] == OTHER
    assert lifted.status_code == 200 and lifted.json()["stop"]["agent_id"] == AGENT  # a lift resolves the same way


async def test_issuing_again_through_the_route_reports_the_order_already_in_force(tmp_path: Path) -> None:
    other_reason = "AD-1343 test: a second reason that must not replace the first"
    assert other_reason != REASON  # premise: the second order differs from the first
    async with _rig(tmp_path / "durable") as rig:
        first = await rig.client.post(f"{STOPS}/{AGENT}", json={"reason": REASON}, headers=_bearer())
        second = await rig.client.post(f"{STOPS}/{AGENT}", json={"reason": other_reason}, headers=_bearer())
        active = rig.service.active()
        durable_rows = _stop_rows(rig.data_dir)
        other = await rig.client.post(f"{STOPS}/{OTHER}", json={"reason": REASON}, headers=_bearer())
    assert first.status_code == 200, first.text
    assert first.json()["already_stopped"] is False
    assert second.status_code == 200, second.text
    assert second.json()["already_stopped"] is True  # the repeated order is reported as already in force
    assert second.json()["stop"]["stop_id"] == first.json()["stop"]["stop_id"]
    assert second.json()["stop"]["reason"] == REASON  # the second reason did not replace the first
    assert other.status_code == 200, other.text
    assert other.json()["already_stopped"] is False  # the flag is per agent
    assert [stop.agent_id for stop in active] == [AGENT]  # exactly one order in force after two issues
    assert len(durable_rows) == 1 and durable_rows[0]["agent_id"] == AGENT  # and exactly one row written

    async with _rig(tmp_path / "volatile", fail_on=("INSERT",)) as rig:
        first_v = await rig.client.post(f"{STOPS}/{AGENT}", json={"reason": REASON}, headers=_bearer())
        second_v = await rig.client.post(f"{STOPS}/{AGENT}", json={"reason": REASON}, headers=_bearer())
        in_force = rig.service.stop_for(AGENT)
        volatile_rows = _stop_rows(rig.data_dir)
    assert first_v.status_code == 503, first_v.text
    assert second_v.status_code == 503, second_v.text
    detail_first, detail_second = first_v.json()["detail"], second_v.json()["detail"]
    assert detail_first["code"] == "stop_not_durable" and detail_second["code"] == "stop_not_durable"
    assert detail_first["applied_until_restart"] is True and detail_second["applied_until_restart"] is True
    assert detail_first["already_stopped"] is False
    assert detail_second["already_stopped"] is True
    assert detail_first["stop"]["stop_id"] == detail_second["stop"]["stop_id"]
    assert in_force is not None and in_force.stop_id == detail_first["stop"]["stop_id"]  # in force although never written
    assert volatile_rows == []


# T22
async def test_issue_refuses_unknown_non_crew_and_unenforceable_agents(tmp_path: Path) -> None:
    assert _OverridingAgent.handle_intent is not CognitiveAgent.handle_intent  # premise: the overrider is not what the stop guards
    assert _ConsultOverridingAgent.handle_consultation_request is not CognitiveAgent.handle_consultation_request  # premise
    assert _ConsultOverridingAgent.handle_intent is CognitiveAgent.handle_intent  # premise: it overrides only the consultation entry
    cases = (
        (f"{STOPS}/ad1343_nobody_0_00000000", 404, "agent_not_found"),
        (f"{STOPS}/{VISITOR}", 422, "not_crew"),
        (f"{STOPS}/{OVERRIDER}", 422, "stop_not_enforceable"),
        (f"{STOPS}/{CONSULT_OVERRIDER}", 422, "stop_not_enforceable"),
    )
    async with _rig(tmp_path) as rig:
        results = [await rig.client.post(path, json={"reason": REASON}, headers=_bearer()) for path, _, _ in cases]
        invalid = [
            await rig.client.post(f"{STOPS}/{AGENT}", json=body, headers=_bearer())
            for body in (None, {}, {"reason": ""}, {"reason": "x" * (MAX_REASON_CHARS + 1)}, {"reason": REASON, "extra": True})
        ]
        blank = await rig.client.post(f"{STOPS}/{AGENT}", json={"reason": "   "}, headers=_bearer())
        applied = rig.service.active()
    assert [(r.status_code, r.json()["detail"]) for r in results] == [(status, detail) for _, status, detail in cases]
    assert [r.status_code for r in invalid] == [422] * 5  # the body must carry a reason of 1..500 characters
    assert blank.status_code == 422 and "reason" in blank.json()["detail"]  # a blank reason passes the schema and is refused by the service
    assert applied == ()  # no refusal applied a stop


# T23
async def test_a_not_durable_issue_answers_503_and_is_in_force(tmp_path: Path) -> None:
    async with _rig(tmp_path, fail_on=("INSERT",)) as rig:
        response = await rig.client.post(f"{STOPS}/{AGENT}", json={"reason": REASON}, headers=_bearer())
        in_force = rig.service.stop_for(AGENT)
        rows = _stop_rows(rig.data_dir)
    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "stop_not_durable" and detail["applied_until_restart"] is True
    assert detail["status"] == "stopped" and detail["already_stopped"] is False
    assert detail["stop"]["agent_id"] == AGENT and detail["scope"] == S1_SCOPE
    assert in_force is not None and in_force.stop_id == detail["stop"]["stop_id"]  # the order is in force although it was not written
    assert rows == []  # and it ends at the next restart


# T24
async def test_lift_answers_with_refusal_counts_404_when_not_stopped_and_503_when_unwritten(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    async with _rig(tmp_path / "lifted") as rig:
        issued = await rig.client.post(f"{STOPS}/{AGENT}", json={"reason": REASON}, headers=_bearer())
        assert issued.status_code == 200  # premise: the agent is stopped
        stop_id = issued.json()["stop"]["stop_id"]
        for seam in (SEAM_INTENT, SEAM_INTENT, SEAM_TOOL):
            rig.service.refusal(AGENT, seam)
        invalid = [
            await rig.client.post(f"{STOPS}/{AGENT}/lift", json=body, headers=_bearer())
            for body in (None, {}, {"reason": ""}, {"reason": "   "}, {"reason": REASON, "extra": True})
        ]
        still_in_force = rig.service.stop_for(AGENT)
        lifted = await rig.client.post(f"{STOPS}/{AGENT}/lift", json={"reason": LIFT_REASON}, headers=_bearer())
        after = rig.service.stop_for(AGENT)
        again = await rig.client.post(f"{STOPS}/{AGENT}/lift", json={"reason": LIFT_REASON}, headers=_bearer())
        never = await rig.client.post(f"{STOPS}/{OTHER}/lift", json={"reason": LIFT_REASON}, headers=_bearer())
    assert [r.status_code for r in invalid] == [422] * 5
    assert still_in_force is not None  # a lift with no usable reason lifted nothing
    assert lifted.status_code == 200, lifted.text
    body = lifted.json()
    assert body["status"] == "lifted" and body["stop"]["stop_id"] == stop_id and body["stop"]["agent_id"] == AGENT
    assert body["refused_while_stopped"] == {"intent": 2, "tool": 1}
    assert body["note"] == LIFT_NOTE and isinstance(body["lifted_at"], float)
    assert body["scope"] == S1_SCOPE  # A2 (F5): an answer that reports an order carries scope
    assert after is None  # applied: the agent is no longer stopped
    assert (again.status_code, again.json()["detail"]) == (404, "no_active_stop")  # lifted already
    assert (never.status_code, never.json()["detail"]) == (404, "no_active_stop")  # never stopped

    async with _rig(tmp_path / "unwritten", fail_on=("UPDATE",)) as rig:
        issued = await rig.client.post(f"{STOPS}/{AGENT}", json={"reason": REASON}, headers=_bearer())
        assert issued.status_code == 200  # premise: the order was written; only the lift's write fails
        with caplog.at_level(logging.ERROR, logger="probos.routers.agent_stop"):
            failed = await rig.client.post(f"{STOPS}/{AGENT}/lift", json={"reason": LIFT_REASON}, headers=_bearer())
        in_force = rig.service.stop_for(AGENT)
        rows = _stop_rows(rig.data_dir)
    assert (failed.status_code, failed.json()["detail"]) == (503, "stop_store_write_failed")
    route_errors = [r.getMessage() for r in caplog.records if r.name == "probos.routers.agent_stop" and r.levelno >= logging.ERROR]
    assert len(route_errors) == 1  # the failed lift is loud, once
    assert AGENT in route_errors[0] and "not written" in route_errors[0] and "stays stopped" in route_errors[0]
    assert in_force is not None and in_force.stop_id == issued.json()["stop"]["stop_id"]  # the agent is still stopped
    assert len(rows) == 1 and rows[0]["lifted_at"] is None


# T25
def test_the_api_serves_the_stop_routes() -> None:
    from probos.api import create_app

    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime._data_dir = runtime.data_dir = None  # BF-326: a MagicMock path makes create_app mkdir a stray dir
    app = create_app(runtime)

    endpoints = {(route.path, method): route.endpoint for route in app.routes for method in getattr(route, "methods", ())}
    expected = {
        (route.path, method): route.endpoint for route in stop_routes.router.routes for method in route.methods
    }
    assert set(expected) == {(STOPS, "GET"), (f"{STOPS}/{{agent_id}}", "POST"), (f"{STOPS}/{{agent_id}}/lift", "POST")}
    for key, handler in expected.items():
        assert endpoints[key] is handler, key  # the app serves this router's handlers, not lookalikes
    assert {path for path, _method in endpoints if path.startswith(STOPS)} == {path for path, _method in expected}


# T26
async def test_refuse_intent_names_the_stop_and_abstains_from_a_broadcast(tmp_path: Path) -> None:
    async with _service(tmp_path, clock=_Clock()) as service:
        record = (await service.issue_stop(AGENT, reason=REASON)).record

    targeted = IntentMessage(intent="direct_message", params={"text": "hello"}, target_agent_id=AGENT)
    refused = record.refuse_intent(targeted, AGENT)
    assert refused is not None
    assert refused.success is False and refused.confidence == 0.0
    assert refused.intent_id == targeted.id and refused.agent_id == AGENT
    assert record.stop_id in refused.result and refused.error == refused.result
    assert "since 2023-11-14T22:13:21+00:00" in refused.result  # the order's start time (the first reading of _Clock()) reaches the sender's text
    detail = refused.metadata["agent_stop"]
    assert detail["since"] == "2023-11-14T22:13:21+00:00"  # and the metadata
    assert detail["code"] == "agent_stopped" and detail["stop_id"] == record.stop_id and detail["agent_id"] == AGENT
    assert PRIVATE_FRAGMENT not in refused.result and PRIVATE_FRAGMENT not in json.dumps(refused.metadata)  # the sender learns of the order, never the reason
    assert record.stop_id in DmReply.from_intent_result(refused).render()  # the DM route shows the stop to the Captain's chat

    broadcast = IntentMessage(intent="direct_message", params={"text": "hello"})
    assert record.refuse_intent(broadcast, AGENT) is None  # addressed to no one: the stopped agent abstains
    elsewhere = IntentMessage(intent="direct_message", params={"text": "hello"}, target_agent_id=OTHER)
    assert record.refuse_intent(elsewhere, AGENT) is None  # addressed to someone else


# ---------------------------------------------------------------------------
# The tool sink, the correction registry, Ward Room routing and the browser ACK (T14 to T18): Milestone M2
# ---------------------------------------------------------------------------
# The imports these tests need stay with them: Milestone M1's header above is left as it was reviewed.

from probos.cognitive.crew_verifier import _SessionProjectedToolRegistry  # noqa: E402
from probos.cognitive.dm.action_dispatcher import ActionDispatcher, ActionStatus, DispatchedAction  # noqa: E402
from probos.execution.effect_broker import EffectDenied  # noqa: E402
from probos.routers import agent_actions as action_routes  # noqa: E402
from probos.tools.protocol import ToolResult, ToolType  # noqa: E402
from probos.tools.registry import ToolRegistry  # noqa: E402
from probos.types import DispatchAdmission  # noqa: E402
from probos.ward_room_router import WardRoomRouter  # noqa: E402

UNKNOWN_TOOL = "ad1343-no-such-tool"  # an id no registry holds
CALLSIGN = "Bones"  # AGENT's callsign: the Ward Room notice must name it
OTHER_CALLSIGN = "Number One"
THREAD = "ad1343-thread-0001"
BROWSER_ACTION = "ad1343-action-0001"


class _ProbeTool:
    """Test-local tool that counts how often it is run. Registered without a permission matrix, so every rank may read it."""

    def __init__(self) -> None:
        self.tool_id = "ad1343_probe_tool"
        self.name = "AD-1343 probe tool"
        self.description = "Counts its invocations"
        self.input_schema: dict[str, Any] = {"type": "object", "properties": {}}
        self.output_schema: dict[str, Any] = {"type": "object"}
        self.calls: list[dict[str, Any]] = []

    @property
    def tool_type(self) -> ToolType:
        return ToolType.INFRA_SERVICE

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls.append(dict(context or {}))
        return ToolResult(output="ran")


# T14
async def test_the_tool_sink_refuses_before_any_lookup_and_is_inert_without_a_stop(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    gated_tool, free_tool = _ProbeTool(), _ProbeTool()
    gated, free = ToolRegistry(), ToolRegistry()
    gated.register(gated_tool)
    free.register(free_tool)
    async with _service(tmp_path, clock=_Clock()) as service:
        gated.set_stop_gate(service)
        assert gated.stop_gate is service and free.stop_gate is None  # premise: the two registries differ only by the gate

        # Golden: with nothing stopped, the registry that has the gate answers exactly as the one that has none.
        def _captured() -> list[tuple[str, int, str]]:
            return [(r.name, r.levelno, r.getMessage()) for r in caplog.records if r.levelno >= logging.INFO]

        with caplog.at_level(logging.INFO):  # every logger: a probe added to the sink for an agent that is not stopped must show
            caplog.clear()
            unknown_free = await free.check_and_invoke(AGENT, UNKNOWN_TOOL, {})
            unknown_free_log = _captured()
            caplog.clear()
            unknown_gated = await gated.check_and_invoke(AGENT, UNKNOWN_TOOL, {})
            unknown_gated_log = _captured()
            caplog.clear()
            known_free = await free.check_and_invoke(AGENT, free_tool.tool_id, {})
            known_free_log = _captured()
            caplog.clear()
            known_gated = await gated.check_and_invoke(AGENT, gated_tool.tool_id, {})
            known_gated_log = _captured()
        assert unknown_free == ToolResult(error=f"Tool '{UNKNOWN_TOOL}' not found")  # premise: what 'not found' looks like
        assert unknown_gated == unknown_free
        assert known_free == ToolResult(output="ran")
        assert known_gated == known_free
        assert unknown_gated_log == unknown_free_log  # the gate adds no log line for an agent that is not stopped
        assert known_gated_log == known_free_log
        # and the stop module writes nothing at all on this path (the registry without a gate also runs the sink's check,
        # so a line logged there would appear in both lists and the equality above alone would not see it)
        for captured in (unknown_free_log, unknown_gated_log, known_free_log, known_gated_log):
            assert [line for line in captured if line[0] == "probos.agent_stop"] == []
        assert (len(gated_tool.calls), len(free_tool.calls)) == (1, 1)

        record = (await service.issue_stop(AGENT, reason=REASON)).record
        refused = await gated.check_and_invoke(AGENT, UNKNOWN_TOOL, {})  # no registry holds this id: the stop answers before the lookup
        assert refused.success is False and "not found" not in refused.error
        detail = refused.metadata["agent_stop"]
        assert detail["code"] == "agent_stopped" and detail["stop_id"] == record.stop_id and detail["agent_id"] == AGENT
        assert UNKNOWN_TOOL in refused.error and record.stop_id in refused.error
        assert PRIVATE_FRAGMENT not in refused.error and PRIVATE_FRAGMENT not in json.dumps(refused.metadata)  # the order, never the reason

        refused_known = await gated.check_and_invoke(AGENT, gated_tool.tool_id, {})  # a registered, permitted tool is not run either
        assert refused_known.metadata["agent_stop"]["stop_id"] == record.stop_id and len(gated_tool.calls) == 1
        assert await gated.check_and_invoke(OTHER, gated_tool.tool_id, {}) == known_free  # the order names one agent
        assert len(gated_tool.calls) == 2
        assert service.refused_counts(record.stop_id) == {"tool": 2}  # the two refusals, counted at the tool seam

        await service.lift_stop(AGENT, reason=LIFT_REASON)
        assert await gated.check_and_invoke(AGENT, gated_tool.tool_id, {}) == known_free  # lifted: inert again
        assert len(gated_tool.calls) == 3


# T15
async def test_a_strict_tool_call_is_denied_with_the_stop_reason_code(tmp_path: Path) -> None:
    tool = _ProbeTool()
    registry = ToolRegistry()
    registry.register(tool)
    permit: Any = object()  # no broker is armed, so nothing reads the permit: it only makes the call a strict one
    async with _service(tmp_path, clock=_Clock()) as service:
        registry.set_stop_gate(service)
        ran = await registry.check_and_invoke(AGENT, tool.tool_id, {}, effect_permit=permit)
        assert ran == ToolResult(output="ran") and len(tool.calls) == 1  # premise: a permit alone denies nothing
        record = (await service.issue_stop(AGENT, reason=REASON)).record

        with pytest.raises(EffectDenied) as denied:
            await registry.check_and_invoke(AGENT, tool.tool_id, {}, effect_permit=permit)
        assert denied.value.reason_code == "agent_stopped"
        result = denied.value.result
        assert result is not None and result.success is False
        assert result.metadata["agent_stop"]["stop_id"] == record.stop_id
        assert PRIVATE_FRAGMENT not in (result.error or "") and PRIVATE_FRAGMENT not in json.dumps(result.metadata)
        assert len(tool.calls) == 1  # not run again
        assert service.refused_counts(record.stop_id) == {"tool": 1}

        with pytest.raises(EffectDenied) as unknown:  # an id no registry holds: still the stop, never 'not found'
            await registry.check_and_invoke(AGENT, UNKNOWN_TOOL, {}, effect_permit=permit)
        assert unknown.value.reason_code == "agent_stopped"
        assert await registry.check_and_invoke(OTHER, tool.tool_id, {}, effect_permit=permit) == ToolResult(output="ran")  # another agent


# T16
async def test_a_projected_correction_registry_enforces_its_sources_stop(tmp_path: Path) -> None:
    tool = _ProbeTool()
    source = ToolRegistry()
    source.register(tool)
    async with _service(tmp_path, clock=_Clock()) as service:
        source.set_stop_gate(service)
        projected = _SessionProjectedToolRegistry(
            source_registry=source, source_backed_ids=frozenset(), explicit_denial_ids=frozenset(),
        )
        assert projected.stop_gate is service  # the projection enforces its source's stop, not a gate of its own
        not_found = ToolResult(error=f"Tool '{UNKNOWN_TOOL}' not found")
        assert await projected.check_and_invoke(AGENT, UNKNOWN_TOOL, {}) == not_found  # premise: nothing is stopped yet

        record = (await service.issue_stop(AGENT, reason=REASON)).record
        refused = await projected.check_and_invoke(AGENT, UNKNOWN_TOOL, {})
        assert refused.success is False and "not found" not in refused.error
        assert refused.metadata["agent_stop"]["stop_id"] == record.stop_id

        backed = _SessionProjectedToolRegistry(
            source_registry=source, source_backed_ids=frozenset({tool.tool_id}), explicit_denial_ids=frozenset(),
        )
        backed_refusal = await backed.check_and_invoke(AGENT, tool.tool_id, {})  # a source-backed id goes to the source, which holds the same stop
        assert backed_refusal.metadata["agent_stop"]["stop_id"] == record.stop_id and tool.calls == []
        assert service.refused_counts(record.stop_id) == {"tool": 2}  # one refusal from the projection's own check, one from the source's

    # A source that has no stop (a registry never given one, or a double that lacks the property) leaves the projection ungated.
    bare = _SessionProjectedToolRegistry(
        source_registry=ToolRegistry(), source_backed_ids=frozenset(), explicit_denial_ids=frozenset(),
    )
    lacking = _SessionProjectedToolRegistry(
        source_registry=SimpleNamespace(), source_backed_ids=frozenset(), explicit_denial_ids=frozenset(),
    )
    assert bare.stop_gate is None and lacking.stop_gate is None


class _RecordingBus:
    """Test-local intent bus: admits every dispatch and keeps the intents it was given, in order."""

    def __init__(self) -> None:
        self.intents: list[IntentMessage] = []

    async def dispatch_async(self, intent: IntentMessage, *, raise_on_denial: bool = False) -> DispatchAdmission:
        self.intents.append(intent)
        return DispatchAdmission(True)


class _RecordingWardRoom:
    """Test-local Ward Room: keeps every ``create_post``; with ``fail`` it raises instead, as a closed store does."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.attempts = 0
        self.posts: list[dict[str, Any]] = []

    async def create_post(self, **kwargs: Any) -> None:
        self.attempts += 1
        if self.fail:
            raise RuntimeError("AD-1343 test: the Ward Room refused the post")
        self.posts.append(kwargs)


def _ward_router(
    agent_stops: Any, room: _RecordingWardRoom | None, bus: _RecordingBus, *, crew: bool = True,
) -> WardRoomRouter:
    """A real router over the fakes above; ``agent_stops`` is passed by keyword, as the runtime wires it."""
    agents = (SimpleNamespace(id=AGENT, callsign=CALLSIGN), SimpleNamespace(id=OTHER, callsign=OTHER_CALLSIGN)) if crew else ()
    return WardRoomRouter(
        ward_room=room,
        registry=_FakeRegistry(*agents),
        intent_bus=bus,
        trust_network=None,
        ontology=None,
        callsign_registry=None,
        episodic_memory=None,
        event_emitter=lambda *args, **kwargs: None,
        event_log=None,
        config=SystemConfig(),
        agent_stops=agent_stops,
    )


async def _route(router: WardRoomRouter, *, mentioned: set[str]) -> None:
    """One Captain post in a ship channel that targets ``a`` (``AGENT``) and ``b`` (``OTHER``), in that order."""
    await router._route_to_agents(
        target_agent_ids=[AGENT, OTHER],
        is_captain=True,
        is_agent_post=False,
        mentioned_agent_ids=mentioned,
        channel=SimpleNamespace(channel_type="ship", name="general"),
        thread_id=THREAD,
        channel_id="ad1343-channel",
        event_type="ward_room_post_created",
        title="AD-1343 test thread",
        author_id="captain",
        data={"author_callsign": "Captain"},
        thread_context="context",
        cooldown=0,
        current_round=0,
        round_participants=set(),
    )


def _dispatched(bus: _RecordingBus) -> list[tuple[str | None, dict[str, Any]]]:
    return [(intent.target_agent_id, intent.params) for intent in bus.intents]


# T17
async def test_ward_room_routing_skips_a_stopped_agent_and_tells_a_direct_thread_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    async with _service(tmp_path, clock=_Clock()) as service:
        # Golden: with nothing stopped, a router that has an empty service routes exactly as one built without the service.
        runs: dict[str, Any] = {}
        for name, gate in (("none", None), ("empty", service)):
            bus, room = _RecordingBus(), _RecordingWardRoom()
            await _route(_ward_router(gate, room, bus), mentioned={AGENT})
            runs[name] = (_dispatched(bus), room.posts)
        golden, no_posts = runs["none"]
        assert [target for target, _params in golden] == [AGENT, OTHER]  # premise: both agents are routed when nothing is stopped
        assert runs["empty"] == (golden, no_posts) and no_posts == []

        record = (await service.issue_stop(AGENT, reason=REASON)).record
        bus, room = _RecordingBus(), _RecordingWardRoom()
        router = _ward_router(service, room, bus)
        await _route(router, mentioned={AGENT})
        assert _dispatched(bus) == [golden[1]]  # only b is dispatched, with the params it always had
        assert len(room.posts) == 1
        post = room.posts[0]
        assert (post["thread_id"], post["author_id"], post["author_callsign"]) == (THREAD, "system", "System")
        assert post["body"].startswith("[System] ") and CALLSIGN in post["body"] and record.stop_id in post["body"]
        assert PRIVATE_FRAGMENT not in post["body"]  # the thread learns of the order, never the reason
        assert record.sender_detail()["since"] in post["body"]  # A2 (F6): when the order began, as senders are promised
        assert "will not reply" not in post["body"] and "may still post" in post["body"]  # A2 (F6): S2 lets a running turn post
        assert service.refused_counts(record.stop_id) == {"ward_room": 1}

        await _route(router, mentioned={AGENT})  # the same thread again
        assert [target for target, _params in _dispatched(bus)] == [OTHER, OTHER]  # b is routed again, a is skipped again
        assert len(room.posts) == 1  # the thread was told once
        assert service.refused_counts(record.stop_id) == {"ward_room": 2}

        quiet_bus, quiet_room = _RecordingBus(), _RecordingWardRoom()
        await _route(_ward_router(service, quiet_room, quiet_bus), mentioned=set())  # nobody addressed a
        assert [target for target, _params in _dispatched(quiet_bus)] == [OTHER] and quiet_room.posts == []

        bare_bus, bare_room = _RecordingBus(), _RecordingWardRoom()
        await _route(_ward_router(service, bare_room, bare_bus, crew=False), mentioned={AGENT})  # the registry knows no callsign for a
        assert len(bare_room.posts) == 1 and AGENT[:8] in bare_room.posts[0]["body"] and CALLSIGN not in bare_room.posts[0]["body"]

        failing_bus, failing_room = _RecordingBus(), _RecordingWardRoom(fail=True)
        with caplog.at_level(logging.WARNING, logger="probos.ward_room_router"):
            await _route(_ward_router(service, failing_room, failing_bus), mentioned={AGENT})
        assert failing_room.attempts == 1 and failing_room.posts == []  # the notice was tried and refused
        assert [target for target, _params in _dispatched(failing_bus)] == [OTHER]  # and b was still routed
        warned = [r.getMessage() for r in caplog.records if r.name == "probos.ward_room_router" and r.levelno == logging.WARNING]
        assert any("stop notice" in line and AGENT in line for line in warned)  # degraded visibly, not silently

        silent_bus = _RecordingBus()
        await _route(_ward_router(service, None, silent_bus), mentioned={AGENT})  # a router with no Ward Room posts nothing
        assert [target for target, _params in _dispatched(silent_bus)] == [OTHER]


class _RecordingBrowserTool:
    """Test-local browser tool: keeps every invocation and answers as a successful click."""

    def __init__(self) -> None:
        self.invocations: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> Any:
        self.invocations.append((dict(params), context))
        return SimpleNamespace(output={"clicked": True}, error=None)


class _SpyDispatcher(ActionDispatcher):
    """The real in-memory dispatcher, plus a record of every ``mark_*`` the route makes."""

    def __init__(self) -> None:
        super().__init__()
        self.marked: list[tuple[str, str]] = []

    def mark_executed(
        self, action_id: str, *, result: Any | None = None, after_frame_ref: str | None = None,
    ) -> DispatchedAction | None:
        self.marked.append(("executed", action_id))
        return super().mark_executed(action_id, result=result, after_frame_ref=after_frame_ref)

    def mark_aborted(self, action_id: str, *, error: str | None = None) -> DispatchedAction | None:
        self.marked.append(("aborted", action_id))
        return super().mark_aborted(action_id, error=error)

    def mark_failed(self, action_id: str, *, error: str) -> DispatchedAction | None:
        self.marked.append(("failed", action_id))
        return super().mark_failed(action_id, error=error)


def _ack_runtime(service: AgentStopService) -> SimpleNamespace:
    """A runtime holding one tier-2 click by ``AGENT`` that waits for the Captain's ACK."""
    dispatcher = _SpyDispatcher()
    dispatcher.register(
        DispatchedAction(
            action_id=BROWSER_ACTION, agent_id=AGENT, captain_id="captain", thread_id=THREAD, verb="click",
            args={"selector": "#submit"}, raw_intent="submit the form", tier=2,
            status=ActionStatus.ACK_PENDING, proposed_at=1_700_000_000.0,
        )
    )
    return SimpleNamespace(
        agent_stops=service,
        config=SystemConfig(auth=AuthConfig(crew_scope_token=TOKEN)),
        action_dispatcher=dispatcher,
        browser_tool=_RecordingBrowserTool(),
    )


@contextlib.asynccontextmanager
async def _ack_client(runtime: Any) -> AsyncIterator[httpx.AsyncClient]:
    """The browser-action router on a minimal app over ``runtime``, called in the test's own loop."""
    app = FastAPI()
    app.include_router(action_routes.router)
    app.state.runtime = runtime
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


# T18
async def test_a_browser_action_ack_for_a_stopped_agent_is_refused_and_stays_pending(tmp_path: Path) -> None:
    ack = f"/api/browser/actions/{BROWSER_ACTION}/ack"
    async with _service(tmp_path, clock=_Clock()) as service:
        # Golden: AGENT is not stopped (an order for another agent is in force), so the ACK runs the action as it always did.
        await service.issue_stop(OTHER, reason=REASON)
        free = _ack_runtime(service)
        async with _ack_client(free) as client:
            ran = await client.post(ack, headers=_bearer())
        assert ran.status_code == 200 and ran.json()["ok"] is True
        assert free.browser_tool.invocations == [({"action": "click", "selector": "#submit"}, {"agent_id": AGENT})]
        assert free.action_dispatcher.marked == [("executed", BROWSER_ACTION)]

        record = (await service.issue_stop(AGENT, reason=REASON)).record
        held = _ack_runtime(service)
        pending = held.action_dispatcher.get(BROWSER_ACTION)
        assert pending is not None and pending.status is ActionStatus.ACK_PENDING  # premise: the action waits for the Captain
        async with _ack_client(held) as client:
            refused = await client.post(ack, headers=_bearer())
        assert refused.status_code == 409
        body = refused.json()
        assert body["code"] == "agent_stopped" and body["stop_id"] == record.stop_id and body["agent_id"] == AGENT
        assert PRIVATE_FRAGMENT not in refused.text  # the Captain's reason is not in the answer
        assert held.browser_tool.invocations == []  # the browser tool was not invoked
        assert held.action_dispatcher.marked == []  # no mark_* call: nothing is executed, failed or aborted
        assert pending.status is ActionStatus.ACK_PENDING  # the action stays pending
        assert service.refused_counts(record.stop_id) == {"browser_action_ack": 1}

        lifted = await service.lift_stop(AGENT, reason=LIFT_REASON)
        assert lifted.refused == {"browser_action_ack": 1}
        async with _ack_client(held) as client:
            resumed = await client.post(ack, headers=_bearer())  # once the stop is lifted the same pending action can be ACKed
        assert resumed.status_code == 200 and resumed.json()["ok"] is True
        assert len(held.browser_tool.invocations) == 1 and held.action_dispatcher.marked == [("executed", BROWSER_ACTION)]


class _FanoutStore:
    """Test-local thread store for one fan-out round: an empty thread."""

    def list_messages(self, thread_id: str, *, limit: int = 1000, before: float | None = None) -> list[Any]:
        return []

    def get_thread(self, thread_id: str) -> None:
        return None


class _RecordingIntentBus:
    """Test-local intent bus: records every send and answers with no result (a decline, as an agent with nothing to say)."""

    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send(self, intent: Any, **kwargs: Any) -> None:
        self.sent.append(intent)
        return None


# T18 (group fan-out)
async def test_a_stopped_agent_is_declined_in_a_group_fan_out_round(tmp_path: Path) -> None:
    from probos.routers.thread_fanout import _fan_one_round

    async def _round(runtime: SimpleNamespace, agent_id: str) -> list[dict[str, Any]]:
        return await _fan_one_round(
            runtime, _FanoutStore(), THREAD, trigger_body="hello", candidate_ids=[agent_id], exclude_ids=set(),
            vision_messages=None, sanity_gate=None, t_start=0.0, broadcast=True,
        )

    async with _service(tmp_path, clock=_Clock()) as service:
        bus = _RecordingIntentBus()
        runtime = SimpleNamespace(
            agent_stops=service, intent_bus=bus, registry=_FakeRegistry(_agent(AGENT, CREW_TYPE), _agent(OTHER, CREW_TYPE)),
        )
        free = await _round(runtime, OTHER)  # control: OTHER is not stopped, so the same path is walked and the bus is asked
        assert [intent.target_agent_id for intent in bus.sent] == [OTHER]  # premise: the round reaches the send for an agent that speaks
        assert free == []  # (the fake bus returns nothing: a decline, thinned out of the round's replies)
        assert service.active() == ()  # premise: nothing is stopped yet

        record = (await service.issue_stop(AGENT, reason=REASON)).record
        bus.sent.clear()
        # The decline dict is internal to the round (it is thinned out before the round returns), so the observable proof
        # of the stopped branch is: no reply, no send, and exactly one refusal counted at the group_fanout seam.
        replies = await _round(runtime, AGENT)
        assert replies == []  # a declined slot is not a reply
        assert bus.sent == []  # the bus was never asked to send for the stopped agent
        assert service.refused_counts(record.stop_id) == {"group_fanout": 1}  # the group_fanout seam refused it, once
