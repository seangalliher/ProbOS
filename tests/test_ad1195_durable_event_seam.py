"""AD-1195 (#1132) M1: the durable-event seam, end to end.

Real ``ProbOSRuntime._emit_event`` -> ``DurableEventRouter.offer`` -> one held
writer task -> a real ``EventLog`` row -> ``durable_answer``. Each test asserts
the premise it depends on (the writer really is inside ``log()``, the lock
really is held, the emit really ran off the loop) before asserting the outcome.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.infodynamic import EntropySignal, InfodynamicProbe, InfodynamicReport
from probos.event_persistence import (
    DECLARATIONS,
    DROP_MARKER_EVENT,
    OWNER_RECORDS,
    ROUTED_CATEGORY,
    Persistence,
    durable_record_key,
    is_routed,
    persistence_of,
)
from probos.events import EventType
from probos.runtime import ProbOSRuntime
from probos.substrate import durable_events as durable_events_module
from probos.substrate.durable_events import (
    DURABLE_PAYLOAD_MAX_BYTES,
    ROUTED_VALUES,
    DurableEventRouter,
    durable_answer,
)
from probos.substrate.event_log import EventLog, bounded_json_payload
from tests.test_proactive import _make_loop, _make_mock_agent, _make_mock_runtime

_ROUTER_LOGGER = "probos.substrate.durable_events"
_SHUTDOWN_LOGGER = "probos.startup.shutdown"
_WRITER_TASK = "durable-event-writer"
_JOIN_TASK = "durable-event-drain-join"
_ROUTED = sorted((m for m in EventType if m.value in ROUTED_VALUES), key=lambda m: m.name)
_NOT_ROUTED = sorted((m for m in EventType if m.value not in ROUTED_VALUES), key=lambda m: m.name)


# ── hosts, sinks and probes ───────────────────────────────────────────────────


class _EmitHost:
    """BF-708 shape: the unmodified runtime emission methods on a minimal object."""

    add_event_listener = ProbOSRuntime.add_event_listener
    _emit_event = ProbOSRuntime._emit_event
    _emit_event_local = ProbOSRuntime._emit_event_local
    _check_night_order_escalation = ProbOSRuntime._check_night_order_escalation

    def __init__(self, router: DurableEventRouter | None = None, *, nats_bus: Any = None) -> None:
        self._event_listeners: list[Any] = []
        self._live_event_listeners: list[Any] = []
        self._event_listener_tasks: set[asyncio.Task[Any]] = set()
        self._nats_publish_tasks: set[asyncio.Task[Any]] = set()
        self._nats_events_wired = False
        self.nats_bus = nats_bus
        if router is not None:
            self.durable_events = router


class _FakeConnectedBus:
    """A NATS bus that reports connected and records what it was asked to publish."""

    connected = True

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []

    async def js_publish(
        self, subject: str, event: dict[str, Any], headers: dict[str, Any] | None = None
    ) -> None:
        self.published.append((subject, event, headers))


class _RecordingSink:
    """A DurableEventSink that keeps every row it is given and answers with a row id."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def log(
        self,
        category: str,
        event: str,
        agent_id: str | None = None,
        agent_type: str | None = None,
        pool: str | None = None,
        detail: str | None = None,
        *,
        correlation_id: str | None = None,
        parent_event_id: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        self.rows.append({"category": category, "event": event, "agent_id": agent_id, "data": data})
        return len(self.rows)


class _GatedSink(_RecordingSink):
    """Every log() call parks until ``gate`` is set; ``entered`` proves the writer got inside."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.gate = asyncio.Event()
        self.calls = 0

    async def log(self, category: str, event: str, *args: Any, **kwargs: Any) -> int | None:
        self.calls += 1
        self.entered.set()
        await self.gate.wait()
        return await super().log(category, event, *args, **kwargs)


class _ScriptedSink(_RecordingSink):
    """Answers each log() call from ``script``: "ok", "none", or an exception to raise."""

    def __init__(self, script: list[Any]) -> None:
        super().__init__()
        self.script = list(script)
        self.calls: list[str] = []

    async def log(self, category: str, event: str, *args: Any, **kwargs: Any) -> int | None:
        self.calls.append(event)
        step = self.script.pop(0) if self.script else "ok"
        if isinstance(step, BaseException):
            raise step
        if step == "none":
            return None
        return await super().log(category, event, *args, **kwargs)


class _MarkerGatedSink(_RecordingSink):
    """Parks the first drop-marker write until ``gate`` opens, then fails it when ``fail``."""

    def __init__(self, *, fail: bool = False) -> None:
        super().__init__()
        self.marker_entered = asyncio.Event()
        self.gate = asyncio.Event()
        self.fail = fail
        self.marker_calls = 0

    async def log(self, category: str, event: str, *args: Any, **kwargs: Any) -> int | None:
        if event == DROP_MARKER_EVENT:
            self.marker_calls += 1
            if self.marker_calls == 1:
                self.marker_entered.set()
                await self.gate.wait()
                if self.fail:
                    raise RuntimeError("marker refused")
        return await super().log(category, event, *args, **kwargs)


class _ObservedEventLog(EventLog):
    """The real EventLog; ``entered``/``finished`` bracket log() and ``outcomes`` says how it ended."""

    def __init__(self, db_path: Path) -> None:
        super().__init__(db_path)
        self.entered = asyncio.Event()
        self.finished = asyncio.Event()
        self.outcomes: list[str] = []

    async def log(self, *args: Any, **kwargs: Any) -> int | None:
        self.entered.set()
        try:
            result = await super().log(*args, **kwargs)
        except asyncio.CancelledError:
            self.outcomes.append("cancelled")
            raise
        except Exception as exc:
            self.outcomes.append(type(exc).__name__)
            raise
        else:
            self.outcomes.append("ok")
            return result
        finally:
            self.finished.set()


class _GatedEventLog:
    """Wraps a real EventLog; routed writes park until ``gate`` opens."""

    def __init__(self, inner: EventLog) -> None:
        self.inner = inner
        self.entered = asyncio.Event()
        self.gate = asyncio.Event()

    async def log(self, *args: Any, **kwargs: Any) -> int | None:
        self.entered.set()
        await self.gate.wait()
        return await self.inner.log(*args, **kwargs)


class _HostileMapping(dict):
    """A payload whose items() raises, as a malformed producer's would."""

    def items(self) -> Any:
        raise RuntimeError("hostile items()")


def _bound_router(sink: Any, **kwargs: Any) -> DurableEventRouter:
    router = DurableEventRouter(sink, **kwargs)
    router.bind_loop(asyncio.get_running_loop())
    return router


def _live_tasks(name: str) -> list[asyncio.Task[Any]]:
    return [t for t in asyncio.all_tasks() if t.get_name() == name and not t.done()]


def _without_timestamp(envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in envelope.items() if key != "timestamp"}


def _messages(caplog: pytest.LogCaptureFixture, logger: str, level: int = logging.DEBUG) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == logger and r.levelno >= level]


def _record(request: pytest.FixtureRequest, name: str, value: object) -> None:
    """Attach a measured value to the JUnit XML (what record_property does, minus its xunit2 warning)."""
    request.node.user_properties.append((name, value))


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, f"condition not reached within {timeout}s"
        await asyncio.sleep(0.005)


def _hold_events_db_lock(
    db_path: Path, release: threading.Event, holding: threading.Event
) -> tuple[threading.Thread, list[BaseException]]:
    """Hold an EXCLUSIVE lock on events.db from another connection (AD-1274 shape)."""
    failed: list[BaseException] = []

    def _run() -> None:
        try:
            conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=60)
            conn.execute("BEGIN EXCLUSIVE")
        except BaseException as exc:  # pragma: no cover - premise failure
            failed.append(exc)
            holding.set()
            return
        holding.set()
        release.wait(30)
        conn.execute("ROLLBACK")
        conn.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread, failed


def _write_lock_is_held(db_path: Path) -> bool:
    """True when a second connection cannot take a write lock right now."""
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=0)
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        return "locked" in str(exc).lower()
    else:
        conn.execute("ROLLBACK")
        return False
    finally:
        conn.close()


def _stored_data_bytes(db_path: Path, row_id: int) -> int:
    """Bytes of the ``data`` column exactly as events.db stores it."""
    conn = sqlite3.connect(str(db_path))
    try:
        (raw,) = conn.execute("SELECT data FROM events WHERE id = ?", (row_id,)).fetchone()
    finally:
        conn.close()
    return len(raw.encode("utf-8"))


def _projected_bytes(payload: object) -> int:
    projected, _ = bounded_json_payload({"emitted_at": 0.0, "payload": payload})
    return len(json.dumps(projected, sort_keys=True, default=str))


@pytest.fixture
async def event_log(tmp_path: Path):
    log = EventLog(tmp_path / "events.db")
    await log.start()
    yield log
    await log.stop()


async def _reopen(db_path: Path) -> EventLog:
    log = EventLog(db_path)
    await log.start()
    return log


# ── premises the parametrized tests rely on ──────────────────────────────────


def test_route_premises_are_the_contract_counts() -> None:
    """BYTE-1/BYTE-2 parametrize over these sets; a drift must not silently shrink them."""
    assert len(EventType) == 396
    assert len(ROUTED_VALUES) == 28
    assert (len(_ROUTED), len(_NOT_ROUTED)) == (28, 368)
    assert {m.value for m in _ROUTED} == ROUTED_VALUES
    assert sum(1 for p in DECLARATIONS.values() if p is Persistence.DURABLE) == 36
    assert len(OWNER_RECORDS) == 8
    assert all(persistence_of(name) is Persistence.DURABLE for name in OWNER_RECORDS)
    assert all(is_routed(m.name) for m in _ROUTED)
    assert not any(is_routed(name) for name in OWNER_RECORDS)


# ── SEAM ─────────────────────────────────────────────────────────────────────


async def test_real_emit_of_durable_member_lands_one_row_answerable_by_helper(
    event_log: EventLog,
) -> None:
    """SEAM-1: real _emit_event -> router -> real EventLog -> row -> durable_answer."""
    router = _bound_router(event_log)
    host = _EmitHost(router)
    envelopes: list[dict[str, Any]] = []
    copies: list[dict[str, Any]] = []

    def _listener(event: dict[str, Any]) -> None:
        envelopes.append(event)
        copies.append(copy.deepcopy(event))

    host.add_event_listener(_listener)
    payload = {
        "threat_type": "prompt_injection",
        "severity": "high",
        "source": "input",
        "agent_id": "agent-7",
        "detail": "ignore previous instructions",
    }
    pristine = copy.deepcopy(payload)
    assert await event_log.query_structured(category=ROUTED_CATEGORY, limit=10) == []

    host._emit_event(EventType.THREAT_DETECTED, payload)
    stats = await router.drain(wait_budget_s=5.0)

    rows = await event_log.query_structured(
        category=ROUTED_CATEGORY, event="threat_detected", limit=10
    )
    assert len(rows) == 1
    (row,) = rows
    assert set(row["data"]["payload"]) == set(pristine)
    assert row["data"]["payload"] == pristine
    assert row["data"]["emitted_at"] == envelopes[0]["timestamp"]
    # A2 R5: this pinned the payload's agent_id in the indexed column; a routed row leaves it NULL.
    assert row["agent_id"] is None
    answer = await durable_answer(event_log, EventType.THREAT_DETECTED)
    assert answer.status == "recorded"
    assert answer.row is not None and answer.row["id"] == row["id"]
    assert answer.record_key == (ROUTED_CATEGORY, "threat_detected")
    assert await event_log.verify_chain() == (True, None)
    # The listener got the producer's own dict, unmodified, in an unmodified envelope.
    assert len(envelopes) == 1 and envelopes[0]["data"] is payload
    assert set(copies[0]) == {"type", "data", "timestamp"}
    assert copies[0]["type"] == "threat_detected" and copies[0]["data"] == pristine
    assert envelopes[0] == copies[0] and payload == pristine
    assert (stats.offered, stats.written, stats.pending, dict(stats.dropped)) == (1, 1, 0, {})


async def test_real_runtime_persists_routed_member_before_event_log_stops(tmp_path: Path) -> None:
    """SEAM-2: a real ProbOSRuntime start -> emit_event -> stop leaves an answerable row."""
    data_dir = tmp_path / "data"
    runtime = ProbOSRuntime(data_dir=data_dir)
    await runtime.start()
    try:
        # Premise: start() bound the router after Phase 1 opened the store.
        assert runtime.event_log.is_open
        assert isinstance(runtime.durable_events, DurableEventRouter)
        runtime.emit_event(EventType.CONFIG_CHANGED, {"key": "ad1195.seam", "old": 1, "new": 2})
    finally:
        await runtime.stop()
    assert not runtime.event_log.is_open

    log = await _reopen(data_dir / "events.db")
    try:
        answer = await durable_answer(log, EventType.CONFIG_CHANGED)
        routed = await log.query_structured(
            category=ROUTED_CATEGORY, event="config_changed", limit=100
        )
        stopped = await log.query_structured(category="system", event="stopped", limit=10)
        chain = await log.verify_chain()
    finally:
        await log.stop()
    mine = [r for r in routed if r["data"]["payload"].get("key") == "ad1195.seam"]
    assert answer.status == "recorded"
    assert len(mine) == 1 and len(stopped) == 1
    assert mine[0]["id"] < stopped[0]["id"]
    assert chain == (True, None)


# ── shutdown ─────────────────────────────────────────────────────────────────


async def test_shutdown_drains_a_parked_durable_row_before_the_stopped_row(tmp_path: Path) -> None:
    """The shutdown drain is what lets a still-parked routed row land before ('system','stopped')."""
    data_dir = tmp_path / "data"
    runtime = ProbOSRuntime(data_dir=data_dir)
    await runtime.start()
    gated = _GatedEventLog(runtime.event_log)
    released_by_drain: list[bool] = []
    stop_attempted = False
    try:
        await runtime.durable_events.drain()  # retire the boot router cleanly
        runtime.durable_events = _bound_router(gated)
        real_drain = runtime.drain_durable_events

        async def _drain_spy() -> Any:
            released_by_drain.append(gated.entered.is_set() and not gated.gate.is_set())
            gated.gate.set()
            return await real_drain()

        runtime.drain_durable_events = _drain_spy
        runtime.emit_event(EventType.CONFIG_CHANGED, {"key": "ad1195.shutdown"})
        await asyncio.wait_for(gated.entered.wait(), timeout=5.0)
        # Premise: the row is parked inside log(); only the drain opens the gate.
        assert not gated.gate.is_set()
        stop_attempted = True
        await runtime.stop()
    finally:
        gated.gate.set()
        if not stop_attempted:
            await runtime.stop()  # a started runtime left running would hang interpreter exit
    assert released_by_drain == [True]

    log = await _reopen(data_dir / "events.db")
    try:
        routed = await log.query_structured(
            category=ROUTED_CATEGORY, event="config_changed", limit=100
        )
        stopped = await log.query_structured(category="system", event="stopped", limit=10)
    finally:
        await log.stop()
    mine = [r for r in routed if r["data"]["payload"].get("key") == "ad1195.shutdown"]
    assert len(mine) == 1 and len(stopped) == 1
    assert mine[0]["id"] < stopped[0]["id"]


@pytest.mark.parametrize("shape", ["raises", "not_a_coroutine_function"])
async def test_shutdown_carries_on_past_a_drain_it_cannot_complete(
    shape: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A raising drain warns and shutdown continues; a non-coroutine attribute is skipped silently."""
    data_dir = tmp_path / "data"
    runtime = ProbOSRuntime(data_dir=data_dir)
    await runtime.start()
    router: DurableEventRouter | None = None
    calls: list[str] = []
    stop_attempted = False
    try:
        router = runtime.durable_events
        if shape == "raises":

            async def _drain() -> None:
                calls.append("raises")
                raise RuntimeError("ad1195 drain failure")

            runtime.drain_durable_events = _drain
        else:
            runtime.drain_durable_events = MagicMock(name="drain_durable_events")
        stop_attempted = True
        with caplog.at_level(logging.DEBUG, logger=_SHUTDOWN_LOGGER):
            await runtime.stop()
    finally:
        if not stop_attempted:
            await runtime.stop()  # a started runtime left running would hang interpreter exit
        if router is not None:
            await router.drain()  # stop the writer the patched drain left running
    warnings = [
        m for m in _messages(caplog, _SHUTDOWN_LOGGER)
        if m.startswith("AD-1195: durable event drain failed")
    ]
    if shape == "raises":
        assert calls == ["raises"] and len(warnings) == 1
        assert "queued durable rows may be lost and shutdown continues" in warnings[0]
    else:
        assert runtime.drain_durable_events.called is False and warnings == []
    assert not runtime.event_log.is_open
    log = await _reopen(data_dir / "events.db")
    try:
        stopped = await log.query_structured(category="system", event="stopped", limit=10)
    finally:
        await log.stop()
    assert len(stopped) == 1


# ── WEDGE ────────────────────────────────────────────────────────────────────


async def test_emit_never_blocks_while_writer_is_wedged_and_counts_overflow(
    request: pytest.FixtureRequest,
) -> None:
    """WEDGE-1: a writer parked inside log() never slows _emit_event; overflow is counted."""
    sink = _GatedSink()
    router = _bound_router(sink, queue_max=32)
    host = _EmitHost(router)
    seen: list[dict[str, Any]] = []
    host.add_event_listener(seen.append)
    durations: list[float] = []

    started = time.perf_counter()
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 0})
    durations.append(time.perf_counter() - started)
    await asyncio.wait_for(sink.entered.wait(), timeout=5.0)
    # Premise: the writer is parked INSIDE log() holding record 0, so the queue starts empty.
    assert sink.calls == 1 and not sink.gate.is_set() and sink.rows == []
    assert router.stats().pending == 0

    for seq in range(1, 83):
        started = time.perf_counter()
        host._emit_event(EventType.EGRESS_BLOCKED, {"seq": seq})
        durations.append(time.perf_counter() - started)
    stats = router.stats()
    # Premise: nothing yielded to the loop, so the writer is still parked on record 0.
    assert sink.calls == 1 and sink.rows == []
    ordered = sorted(durations)
    p99 = ordered[math.ceil(0.99 * len(ordered)) - 1]
    _record(request, "emit_count", len(durations))
    _record(request, "emit_ms_max", round(ordered[-1] * 1000, 4))
    _record(request, "emit_ms_p99", round(p99 * 1000, 4))
    _record(request, "emit_ms_median", round(ordered[len(ordered) // 2] * 1000, 4))
    # A1/E5: a sanity bound against a pathological slowdown, not a latency claim.
    assert len(durations) == 83 and ordered[-1] < 1.0
    assert len(seen) == 83
    assert stats.pending == 32
    assert dict(stats.dropped) == {"queue_full": 50}
    assert stats.offered == 83

    sink.gate.set()
    final = await router.drain(wait_budget_s=5.0)
    rows = [r for r in sink.rows if r["event"] == "egress_blocked"]
    markers = [r for r in sink.rows if r["event"] == DROP_MARKER_EVENT]
    assert (final.written, final.pending, final.markers_written) == (33, 0, 1)
    assert [r["data"]["payload"]["seq"] for r in rows] == list(range(33))
    assert len(markers) == 1
    marker = markers[0]["data"]
    assert marker["dropped"] == 50
    assert marker["by_reason"] == {"queue_full": 50}
    assert marker["by_event"] == {"egress_blocked": 50}
    assert marker["first_at"] <= marker["last_at"]


async def test_drain_returns_within_budget_against_a_locked_events_db_and_store_recovers(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    request: pytest.FixtureRequest,
) -> None:
    """WEDGE-2: the drain cancels an in-flight log() on a locked DB; the store stays usable."""
    db_path = tmp_path / "events.db"
    log = _ObservedEventLog(db_path)
    await log.start()
    release = threading.Event()
    holding = threading.Event()
    holder: threading.Thread | None = None
    try:
        warm_id = await log.log("system", "warmup")
        assert type(warm_id) is int
        log.entered.clear()
        log.finished.clear()
        log.outcomes.clear()
        holder, holder_failed = _hold_events_db_lock(db_path, release, holding)
        assert holding.wait(timeout=10) and not holder_failed
        # Premise: another connection really holds the write lock.
        assert _write_lock_is_held(db_path)

        router = _bound_router(log)
        _EmitHost(router)._emit_event(EventType.THREAT_DETECTED, {"threat_type": "wedge"})
        await asyncio.wait_for(log.entered.wait(), timeout=5.0)
        # Premise: the writer is inside log(), which has not returned.
        assert log.outcomes == [] and not log.finished.is_set()
        assert _write_lock_is_held(db_path)

        with caplog.at_level(logging.WARNING, logger=_ROUTER_LOGGER):
            started = time.perf_counter()
            stats = await asyncio.wait_for(router.drain(wait_budget_s=0.5), timeout=10.0)
            elapsed = time.perf_counter() - started
        _record(request, "drain_elapsed_s", round(elapsed, 4))
        errors = _messages(caplog, _ROUTER_LOGGER, logging.ERROR)
        # Premise: the drain spent its budget rather than finding an empty queue.
        assert any("wait budget" in m and "shutdown continues" in m for m in errors)
        assert elapsed < 0.5 + 0.5 + 1.5
        assert stats.written == 0
        assert router.unresolved("threat_detected") == 1  # the cancelled write

        release.set()
        holder.join(timeout=30)
        await asyncio.wait_for(log.finished.wait(), timeout=10.0)
        # Premise: the drain cancelled a log() that was in flight, not one that had finished.
        assert log.outcomes == ["cancelled"]
        # The store recovered: still open, writable, and the chain verifies.
        assert log.is_open
        probe_id = await log.log("system", "probe")
        assert type(probe_id) is int and probe_id > warm_id
        assert await log.verify_chain() == (True, None)
        assert await log.query_structured(category=ROUTED_CATEGORY, limit=10) == []
    finally:
        release.set()
        if holder is not None:
            holder.join(timeout=30)
        await log.stop()


# ── THREAD / NATS ────────────────────────────────────────────────────────────


async def test_off_loop_emit_hands_off_to_dispatch_loop(event_log: EventLog) -> None:
    """THREAD-1: an emit from a worker thread is handed to the bound loop and written."""
    router = _bound_router(event_log)
    host = _EmitHost(router)
    emitting_threads: list[int] = []
    host.add_event_listener(lambda event: emitting_threads.append(threading.get_ident()))

    await asyncio.to_thread(
        host._emit_event, EventType.SECRET_ROTATED, {"rotation": "ad1195", "agent_id": "a-1"}
    )
    # Premise: the emit really ran off the loop's thread.
    assert emitting_threads and emitting_threads[0] != threading.get_ident()
    await _wait_until(lambda: router.stats().written == 1)
    stats = await router.drain(wait_budget_s=5.0)

    rows = await event_log.query_structured(
        category=ROUTED_CATEGORY, event="secret_rotated", limit=10
    )
    assert len(rows) == 1 and rows[0]["data"]["payload"]["rotation"] == "ad1195"
    assert (stats.offered, stats.written, dict(stats.dropped)) == (1, 1, {})


async def test_off_loop_emit_after_loop_close_is_counted_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """THREAD-1: a hand-off to a closed loop is a counted drop, never an exception."""
    closed_loop = asyncio.new_event_loop()
    closed_loop.close()
    sink = _RecordingSink()
    router = DurableEventRouter(sink)
    router.bind_loop(closed_loop)
    host = _EmitHost(router)
    seen: list[dict[str, Any]] = []
    host.add_event_listener(seen.append)
    raised: list[BaseException] = []

    def _emit() -> None:
        try:
            host._emit_event(EventType.EGRESS_BLOCKED, {"host": "blocked.test"})
        except BaseException as exc:  # pragma: no cover - the defect this test catches
            raised.append(exc)

    with caplog.at_level(logging.WARNING, logger=_ROUTER_LOGGER):
        thread = threading.Thread(target=_emit)
        thread.start()
        thread.join(timeout=10)
    # Premise: the bound loop really is closed.
    assert closed_loop.is_closed()
    assert raised == [] and len(seen) == 1
    stats = router.stats()
    assert (stats.offered, dict(stats.dropped)) == (1, {"loop_closed": 1})
    assert sink.rows == []
    assert any("loop_closed" in m for m in _messages(caplog, _ROUTER_LOGGER, logging.WARNING))


async def test_connected_bus_off_loop_fallback_still_routes(
    event_log: EventLog, caplog: pytest.LogCaptureFixture
) -> None:
    """NATS-1: the hook sits ahead of the connected-bus no-loop early return."""
    router = _bound_router(event_log)
    bus = _FakeConnectedBus()
    host = _EmitHost(router, nats_bus=bus)
    seen: list[dict[str, Any]] = []
    host.add_event_listener(seen.append)

    with caplog.at_level(logging.WARNING, logger="probos.runtime"):
        await asyncio.to_thread(
            host._emit_event, EventType.MCP_BRIDGE_INVOKE, {"server": "s1", "tool": "t1"}
        )
    # Premise: the connected-bus branch took its no-loop fallback and returned early.
    assert any(
        "AD-637d: _emit_event called outside event loop" in m
        for m in _messages(caplog, "probos.runtime", logging.WARNING)
    )
    assert bus.published == [] and len(seen) == 1
    await _wait_until(lambda: router.stats().written == 1)
    await router.drain(wait_budget_s=5.0)
    rows = await event_log.query_structured(
        category=ROUTED_CATEGORY, event="mcp_bridge_invoke", limit=10
    )
    assert len(rows) == 1 and rows[0]["data"]["payload"] == {"server": "s1", "tool": "t1"}


# ── BYTE / HOST ──────────────────────────────────────────────────────────────


def _byte_hosts(router: DurableEventRouter) -> tuple[list[_EmitHost], list[_FakeConnectedBus]]:
    """Local and connected-bus hosts, each with and without the router."""
    routed_bus, plain_bus = _FakeConnectedBus(), _FakeConnectedBus()
    hosts = [
        _EmitHost(router),
        _EmitHost(),
        _EmitHost(router, nats_bus=routed_bus),
        _EmitHost(nats_bus=plain_bus),
    ]
    return hosts, [routed_bus, plain_bus]


async def _emit_on_every_host(
    member: EventType, payload: dict[str, Any], hosts: list[_EmitHost]
) -> list[list[dict[str, Any]]]:
    received: list[list[dict[str, Any]]] = [[] for _ in hosts]
    for host, got in zip(hosts, received):
        host.add_event_listener(got.append)
    for host in hosts:
        host._emit_event(member, payload)
    publishes = [task for host in hosts[2:] for task in host._nats_publish_tasks]
    # Premise: the connected-bus path really scheduled one publish per host.
    assert len(publishes) == 2
    await asyncio.gather(*publishes)
    assert all(not host._event_listener_tasks for host in hosts)
    return received


def _assert_identical_delivery(
    member: EventType,
    payload: dict[str, Any],
    received: list[list[dict[str, Any]]],
    buses: list[_FakeConnectedBus],
) -> None:
    routed_local, plain_local, routed_nats, plain_nats = received
    assert len(routed_local) == len(plain_local) == 1
    assert routed_local[0]["data"] is payload and plain_local[0]["data"] is payload
    assert set(routed_local[0]) == {"type", "data", "timestamp"}
    assert _without_timestamp(routed_local[0]) == _without_timestamp(plain_local[0])
    assert routed_nats == plain_nats == []
    ((r_subject, r_event, r_headers),) = buses[0].published
    ((p_subject, p_event, p_headers),) = buses[1].published
    assert r_subject == p_subject == f"system.events.{member.value}"
    assert r_headers == p_headers
    assert r_event["data"] is payload
    assert _without_timestamp(r_event) == _without_timestamp(p_event)


@pytest.mark.parametrize("member", _NOT_ROUTED, ids=lambda m: m.name)
async def test_non_routed_member_emits_exactly_as_a_host_without_a_router(
    member: EventType, caplog: pytest.LogCaptureFixture
) -> None:
    """BYTE-1: a non-routed member costs one set lookup and changes nothing observable."""
    sink = _RecordingSink()
    router = _bound_router(sink)
    hosts, buses = _byte_hosts(router)
    payload = {"agent_id": "agent-7", "count": 3, "nested": {"items": [1, 2, {"k": "v"}]}}
    pristine = copy.deepcopy(payload)
    with caplog.at_level(logging.DEBUG, logger=_ROUTER_LOGGER):
        received = await _emit_on_every_host(member, payload, hosts)
    _assert_identical_delivery(member, payload, received, buses)
    stats = router.stats()
    assert (stats.offered, stats.pending, dict(stats.dropped)) == (0, 0, {})
    assert sink.rows == []
    assert _live_tasks(_WRITER_TASK) == []
    assert _messages(caplog, _ROUTER_LOGGER) == []
    assert payload == pristine


@pytest.mark.parametrize("member", _ROUTED, ids=lambda m: m.name)
async def test_routed_member_is_delivered_and_published_exactly_as_without_a_router(
    member: EventType,
) -> None:
    """BYTE-2: routing is additive; delivery and publication match a host without a router."""
    sink = _RecordingSink()
    router = _bound_router(sink)
    hosts, buses = _byte_hosts(router)
    payload = {"agent_id": "agent-7", "count": 3, "nested": {"items": [1, 2, {"k": "v"}]}}
    pristine = copy.deepcopy(payload)
    received = await _emit_on_every_host(member, payload, hosts)
    _assert_identical_delivery(member, payload, received, buses)
    stats = await router.drain(wait_budget_s=5.0)
    rows = [r for r in sink.rows if r["event"] == member.value]
    assert (stats.offered, stats.written) == (2, 2)
    assert len(rows) == 2 and {r["category"] for r in rows} == {ROUTED_CATEGORY}
    # The row holds the governed read-side projection of {emitted_at, payload}
    # (Q8), which is what a governed reader of this row would see.
    projected, _ = bounded_json_payload({"emitted_at": 0.0, "payload": pristine})
    expected_payload = json.loads(json.dumps(projected))["payload"]
    assert all(json.loads(json.dumps(r["data"]["payload"])) == expected_payload for r in rows)
    # A2 R5: this pinned the payload's agent_id in the indexed column; routed rows leave it NULL.
    assert all(r["agent_id"] is None for r in rows)
    emitted = {received[0][0]["timestamp"], buses[0].published[0][1]["timestamp"]}
    assert {r["data"]["emitted_at"] for r in rows} == emitted
    assert payload == pristine


@pytest.mark.parametrize("shape", ["bf708_host", "runtime_new_double"])
async def test_host_without_a_router_attribute_emits_as_before(
    shape: str, caplog: pytest.LogCaptureFixture
) -> None:
    """HOST-1: a host that never grew ``durable_events`` emits exactly as it did."""
    if shape == "bf708_host":
        host: Any = _EmitHost()
    else:
        host = ProbOSRuntime.__new__(ProbOSRuntime)
        host._event_listeners = []
        host._live_event_listeners = []
        host._event_listener_tasks = set()
        host._nats_events_wired = False
        host.nats_bus = None
    # Premise: the host really has no router.
    assert not hasattr(host, "durable_events")
    seen: list[dict[str, Any]] = []
    host.add_event_listener(seen.append)
    with caplog.at_level(logging.DEBUG, logger=_ROUTER_LOGGER):
        host._emit_event(EventType.THREAT_DETECTED, {"x": 1})
        host._emit_event(EventType.NODE_START, {"y": 2})
    assert [e["type"] for e in seen] == ["threat_detected", "node_start"]
    assert [e["data"] for e in seen] == [{"x": 1}, {"y": 2}]
    assert _messages(caplog, _ROUTER_LOGGER) == []


async def test_owner_written_members_are_not_routed(event_log: EventLog) -> None:
    """OWNER-1: the 8 owner-written members yield no router rows (their owners write them)."""
    router = _bound_router(event_log)
    host = _EmitHost(router)
    for name in OWNER_RECORDS:
        host._emit_event(EventType[name], {"agent_id": "a-1", "owner": name})
    # Premise: a routed control through the same host IS persisted, so zero is not a dead router.
    host._emit_event(EventType.THREAT_DETECTED, {"control": True})
    stats = await router.drain(wait_budget_s=5.0)
    routed = await event_log.query_structured(category=ROUTED_CATEGORY, limit=100)
    assert [r["event"] for r in routed] == ["threat_detected"]
    assert (stats.offered, stats.written) == (1, 1)
    for name, pair in OWNER_RECORDS.items():
        assert durable_record_key(name, EventType[name].value) == pair
        assert not is_routed(name)


# ── PAYLOAD ──────────────────────────────────────────────────────────────────


async def _persist_one(
    event_log: EventLog, db_path: Path, payload: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    router = _bound_router(event_log)
    _EmitHost(router)._emit_event(EventType.DESIGN_GENERATED, payload)
    stats = await router.drain(wait_budget_s=5.0)
    assert stats.written == 1
    (row,) = await event_log.query_structured(
        category=ROUTED_CATEGORY, event="design_generated", limit=10
    )
    return row, _stored_data_bytes(db_path, row["id"])


async def test_payload_that_fits_is_stored_as_the_governed_projection(
    event_log: EventLog, tmp_path: Path
) -> None:
    """PAYLOAD-1: a fitting payload is stored whole, with a nested secret-named key redacted."""
    payload = {
        "agent_id": "architect-1",
        "title": "Seam",
        "details": {"api_key": "sk-live-ad1195", "note": "kept"},
        "steps": ["a", "b"],
    }
    # Premise: the projected payload fits the cap.
    assert _projected_bytes(payload) <= DURABLE_PAYLOAD_MAX_BYTES
    row, size = await _persist_one(event_log, tmp_path / "events.db", payload)
    stored = row["data"]["payload"]
    assert stored["details"] == {"api_key": "[REDACTED]", "note": "kept"}
    assert stored["steps"] == ["a", "b"] and stored["title"] == "Seam"
    assert "_truncated" not in stored
    assert "sk-live-ad1195" not in json.dumps(row)
    assert size <= DURABLE_PAYLOAD_MAX_BYTES


async def test_payload_over_the_cap_keeps_its_scalars(event_log: EventLog, tmp_path: Path) -> None:
    """PAYLOAD-2: past the cap, top-level scalars and top-level dicts' scalar fields survive."""
    payload = {
        "agent_id": "architect-1",
        "title": "T" * 300,
        "count": 7,
        "work_item": {
            "id": "wi-1",
            "status": "done",
            "description": "D" * 600,
            "api_token": "tok-ad1195",
            "steps": ["s"] * 10,
        },
        "llm_output": ["L" * 500] * 30,
    }
    # Premise: the full projection does not fit.
    assert _projected_bytes(payload) > DURABLE_PAYLOAD_MAX_BYTES
    row, size = await _persist_one(event_log, tmp_path / "events.db", payload)
    stored = row["data"]["payload"]
    assert stored["_truncated"] is True
    assert (stored["agent_id"], stored["count"], stored["title"]) == ("architect-1", 7, "T" * 128)
    assert stored["work_item"] == {
        "id": "wi-1",
        "status": "done",
        "description": "D" * 128,
        "api_token": "[REDACTED]",
    }
    assert "llm_output" not in stored
    assert "tok-ad1195" not in json.dumps(row)
    assert size <= DURABLE_PAYLOAD_MAX_BYTES


async def test_payload_whose_summary_is_still_too_big_keeps_only_its_keys(
    event_log: EventLog, tmp_path: Path
) -> None:
    """PAYLOAD-3: when even the summary cannot fit, only the top-level key names are kept."""
    payload = {f"field_{index:02d}": "V" * 500 for index in range(40)}
    # Premise: the projection keeps 31 of the values, and those alone, cut to 128
    # characters, already exceed the cap, so the summary cannot fit.
    summary_like = {f"field_{index:02d}": "V" * 128 for index in range(31)}
    assert _projected_bytes(summary_like) > DURABLE_PAYLOAD_MAX_BYTES
    row, size = await _persist_one(event_log, tmp_path / "events.db", payload)
    stored = row["data"]["payload"]
    assert set(stored) == {"_truncated", "keys"} and stored["_truncated"] is True
    assert stored["keys"] == [f"field_{index:02d}" for index in range(31)]
    assert "V" * 128 not in json.dumps(row)
    assert size <= DURABLE_PAYLOAD_MAX_BYTES


async def test_keys_only_stops_at_the_key_that_would_break_the_cap(
    event_log: EventLog, tmp_path: Path
) -> None:
    # json.dumps escapes each astral character as 12 ASCII bytes, so a few keys fill the cap.
    payload = {"\U0001F600" * 100 + f"{index:02d}": "V" * 500 for index in range(10)}
    row, size = await _persist_one(event_log, tmp_path / "events.db", payload)
    stored = row["data"]["payload"]
    keys = stored["keys"]
    assert set(stored) == {"_truncated", "keys"} and 0 < len(keys) < len(payload)
    assert keys == list(payload)[: len(keys)]
    # Premise: the next key really would have broken the cap.
    grown = {"emitted_at": row["data"]["emitted_at"], "payload": dict(stored, keys=[*keys, list(payload)[len(keys)]])}
    assert len(json.dumps(grown, sort_keys=True)) > DURABLE_PAYLOAD_MAX_BYTES
    assert size <= DURABLE_PAYLOAD_MAX_BYTES


async def test_a_pathological_timestamp_is_dropped_before_the_payload_keys(
    event_log: EventLog,
) -> None:
    router = _bound_router(event_log)
    timestamp = {f"t{index:02d}": "T" * 500 for index in range(40)}
    router.offer({"type": "design_generated", "data": {"a": 1, "b": 2}, "timestamp": timestamp})
    assert (await router.drain(wait_budget_s=5.0)).written == 1
    (row,) = await event_log.query_structured(
        category=ROUTED_CATEGORY, event="design_generated", limit=10
    )
    assert row["data"] == {"emitted_at": None, "payload": {"_truncated": True, "keys": ["a", "b"]}}


async def test_list_and_scalar_payloads_are_snapshotted_and_stored(event_log: EventLog) -> None:
    router = _bound_router(event_log)
    items = [0, 1, 2]
    router.offer({"type": "design_generated", "data": items, "timestamp": 1.0})
    router.offer({"type": "design_generated", "data": "plain text", "timestamp": 2.0})
    router.offer({"type": "design_generated", "data": ["L" * 500] * 40, "timestamp": 3.0})
    items.append(99)  # after the offer: the queued snapshot must not see it
    assert (await router.drain(wait_budget_s=5.0)).written == 3
    rows = await event_log.query_structured(
        category=ROUTED_CATEGORY, event="design_generated", limit=10
    )
    stored = {r["data"]["emitted_at"]: r["data"]["payload"] for r in rows}
    assert stored == {1.0: [0, 1, 2], 2.0: "plain text", 3.0: {"_truncated": True}}
    assert all(r["agent_id"] is None for r in rows)


# ── DRAIN / ANSWER ───────────────────────────────────────────────────────────


async def test_offer_after_drain_is_counted_closed_and_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DRAIN-1: after drain() an offer is a counted "closed" drop; no writer is re-armed."""
    sink = _RecordingSink()
    router = _bound_router(sink)
    host = _EmitHost(router)
    seen: list[dict[str, Any]] = []
    host.add_event_listener(seen.append)
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 1})
    first = await router.drain(wait_budget_s=5.0)
    # Premise: the router was live before the drain.
    assert first.written == 1
    with caplog.at_level(logging.WARNING, logger=_ROUTER_LOGGER):
        host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 2})
    stats = router.stats()
    assert (stats.offered, dict(stats.dropped)) == (2, {"closed": 1})
    assert [r["data"]["payload"]["seq"] for r in sink.rows] == [1]
    assert len(seen) == 2
    assert any("closed" in m for m in _messages(caplog, _ROUTER_LOGGER, logging.WARNING))
    assert _live_tasks(_WRITER_TASK) == []


async def test_bind_loop_re_arms_a_drained_router_and_marks_the_closed_drop(
    event_log: EventLog,
) -> None:
    """DRAIN-2: bind_loop re-arms; the drop from the closed window gets a marker row."""
    loop = asyncio.get_running_loop()
    router = _bound_router(event_log)
    host = _EmitHost(router)
    host._emit_event(EventType.SHIP_NAMED, {"name": "first"})
    assert (await router.drain(wait_budget_s=5.0)).written == 1
    host._emit_event(EventType.CREDENTIAL_TIER_DENIED, {"tier": "t3"})
    assert dict(router.stats().dropped) == {"closed": 1}

    router.bind_loop(loop)
    host._emit_event(EventType.SHIP_NAMED, {"name": "second"})
    stats = await router.drain(wait_budget_s=5.0)

    assert (stats.written, stats.markers_written) == (2, 1)
    named = await event_log.query_structured(category=ROUTED_CATEGORY, event="ship_named", limit=10)
    assert [r["data"]["payload"]["name"] for r in named] == ["second", "first"]
    markers = await event_log.query_structured(
        category=ROUTED_CATEGORY, event=DROP_MARKER_EVENT, limit=10
    )
    assert len(markers) == 1
    assert markers[0]["data"]["by_reason"] == {"closed": 1}
    assert markers[0]["data"]["by_event"] == {"credential_tier_denied": 1}
    denied = await durable_answer(event_log, EventType.CREDENTIAL_TIER_DENIED)
    assert denied.status == "unknown_dropped"
    assert denied.row is not None and denied.row["id"] == markers[0]["id"]
    assert (await durable_answer(event_log, EventType.SHIP_NAMED)).status == "recorded"


async def test_durable_answer_says_only_what_the_store_can_support(tmp_path: Path) -> None:
    """ANSWER-1: not_answerable for a non-DURABLE member, unavailable for a closed store."""
    never_opened = EventLog(tmp_path / "never.db")
    assert not never_opened.is_open
    unavailable = await durable_answer(never_opened, EventType.THREAT_DETECTED)
    assert (unavailable.status, unavailable.row) == ("unavailable", None)

    log = await _reopen(tmp_path / "events.db")
    try:
        assert log.is_open
        grandfathered = await durable_answer(log, EventType.NODE_START)
        assert (grandfathered.status, grandfathered.record_key) == ("not_answerable", None)
        assert persistence_of("NODE_START") is None
        operational = await durable_answer(log, EventType.AGENTIC_TOOL_CALL_STARTED)
        assert (operational.status, operational.record_key) == ("not_answerable", None)
        assert persistence_of("AGENTIC_TOOL_CALL_STARTED") is Persistence.OPERATIONAL
        never = await durable_answer(log, "THREAT_DETECTED")
        assert (never.status, never.member) == ("not_recorded", "THREAT_DETECTED")
        assert never.record_key == (ROUTED_CATEGORY, "threat_detected")
        owner = await durable_answer(log, "tool_invoked")
        assert (owner.status, owner.member, owner.record_key) == (
            "not_recorded", "TOOL_INVOKED", ("tool", "tool_invoked"),
        )
        await log.log("tool", "tool_invoked", data={"tool": "t"})
        assert (await durable_answer(log, EventType.TOOL_INVOKED)).status == "recorded"
        unknown = await durable_answer(log, "NOT_A_MEMBER")
        assert (unknown.status, unknown.member) == ("not_answerable", "NOT_A_MEMBER")
        assert (await durable_answer(log, 42)).status == "not_answerable"  # type: ignore[arg-type]
    finally:
        await log.stop()
    assert (await durable_answer(log, EventType.TOOL_INVOKED)).status == "unavailable"


async def test_only_a_marker_naming_the_member_or_other_makes_it_unknown_dropped(
    event_log: EventLog,
) -> None:
    await event_log.log(
        ROUTED_CATEGORY, DROP_MARKER_EVENT, data={"dropped": 1, "by_event": {"egress_blocked": 1}}
    )
    await event_log.log(ROUTED_CATEGORY, DROP_MARKER_EVENT, data={"dropped": 1, "by_event": "x"})
    # Premise: both markers are retained and neither names THREAT_DETECTED.
    assert len(await event_log.query_structured(category=ROUTED_CATEGORY, limit=10)) == 2
    assert (await durable_answer(event_log, EventType.THREAT_DETECTED)).status == "not_recorded"
    assert (await durable_answer(event_log, EventType.EGRESS_BLOCKED)).status == "unknown_dropped"
    await event_log.log(
        ROUTED_CATEGORY, DROP_MARKER_EVENT, data={"dropped": 3, "by_event": {"_other": 3}}
    )
    folded = await durable_answer(event_log, EventType.THREAT_DETECTED)
    assert folded.status == "unknown_dropped"
    assert folded.row is not None and folded.row["data"]["by_event"] == {"_other": 3}


class _ClosingSource:
    """A DurableEventSource that closes after its first query, as a stopping store would."""

    def __init__(self) -> None:
        self.is_open = True
        self.queries: list[tuple[str | None, str | None]] = []

    async def query_structured(
        self, *, category: str | None = None, event: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        self.queries.append((category, event))
        self.is_open = False
        return []  # what EventLog.query_structured returns once closed


@pytest.mark.parametrize(
    ("member", "queries"),
    [(EventType.THREAT_DETECTED, 2), (EventType.TOOL_INVOKED, 1)],
    ids=["routed", "owner"],
)
async def test_a_store_that_closes_mid_answer_is_unavailable_not_evidence_of_absence(
    member: EventType, queries: int
) -> None:
    source = _ClosingSource()
    answer = await durable_answer(source, member)
    # Premise: the store was open at the start and every query ran (and came back empty).
    assert len(source.queries) == queries and not source.is_open
    assert (answer.status, answer.row) == ("unavailable", None)
    assert answer.record_key == durable_record_key(member.name, member.value)


# ── branches of the router ───────────────────────────────────────────────────


async def test_offer_before_bind_is_counted_unbound_and_marked_after_the_first_write() -> None:
    sink = _RecordingSink()
    router = DurableEventRouter(sink)
    host = _EmitHost(router)
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 1})
    assert dict(router.stats().dropped) == {"unbound": 1}
    assert sink.rows == [] and _live_tasks(_WRITER_TASK) == []

    router.bind_loop(asyncio.get_running_loop())
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 2})
    stats = await router.drain(wait_budget_s=5.0)
    assert [r["event"] for r in sink.rows] == ["egress_blocked", DROP_MARKER_EVENT]
    assert sink.rows[1]["data"]["by_reason"] == {"unbound": 1}
    assert (stats.written, stats.markers_written) == (1, 1)


async def test_offer_survives_an_unhashable_type_and_a_hostile_payload() -> None:
    sink = _RecordingSink()
    router = _bound_router(sink)
    router.offer({"type": ["not", "hashable"], "data": {}, "timestamp": 1.0})
    assert router.stats().offered == 0

    host = _EmitHost(router)
    seen: list[dict[str, Any]] = []
    host.add_event_listener(seen.append)
    host._emit_event(EventType.THREAT_DETECTED, _HostileMapping(agent_id="a-1"))
    stats = router.stats()
    assert (stats.offered, dict(stats.dropped)) == (1, {"offer_error": 1})
    assert len(seen) == 1 and sink.rows == []


async def test_drop_warnings_are_rate_limited_per_episode(caplog: pytest.LogCaptureFixture) -> None:
    router = DurableEventRouter(_RecordingSink())
    host = _EmitHost(router)
    with caplog.at_level(logging.WARNING, logger=_ROUTER_LOGGER):
        for _ in range(513):
            host._emit_event(EventType.EGRESS_BLOCKED, {})
    assert dict(router.stats().dropped) == {"unbound": 513}
    assert len(_messages(caplog, _ROUTER_LOGGER, logging.WARNING)) == 3  # drops 1, 256 and 512


async def test_marker_by_event_keeps_32_names_and_folds_the_rest_into_other() -> None:
    members = list(EventType)[:40]
    sink = _RecordingSink()
    router = DurableEventRouter(sink, routes=[m.value for m in EventType])
    host = _EmitHost(router)
    for member in members:
        host._emit_event(member, {})
    router.bind_loop(asyncio.get_running_loop())
    host._emit_event(EventType.THREAT_DETECTED, {})
    await router.drain(wait_budget_s=5.0)
    (marker,) = [r["data"] for r in sink.rows if r["event"] == DROP_MARKER_EVENT]
    assert marker["dropped"] == 40
    assert len(marker["by_event"]) == 33 and marker["by_event"]["_other"] == 8
    assert sum(marker["by_event"].values()) == 40


async def test_a_stopped_writer_is_replaced_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    sink = _RecordingSink()
    router = _bound_router(sink)
    host = _EmitHost(router)
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 1})
    await _wait_until(lambda: len(sink.rows) == 1)
    (writer,) = _live_tasks(_WRITER_TASK)
    writer.cancel()
    await asyncio.wait({writer}, timeout=5.0)
    # Premise: the writer really stopped.
    assert writer.cancelled()
    with caplog.at_level(logging.ERROR, logger=_ROUTER_LOGGER):
        host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 2})
    await router.drain(wait_budget_s=5.0)
    assert [r["data"]["payload"]["seq"] for r in sink.rows] == [1, 2]
    assert any("writer stopped" in m for m in _messages(caplog, _ROUTER_LOGGER, logging.ERROR))


async def test_failed_and_unrecorded_writes_are_counted_and_the_writer_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    boom = RuntimeError("disk full")
    sink = _ScriptedSink([boom, boom, "none", "none", "ok"])
    router = _bound_router(sink)
    host = _EmitHost(router)
    with caplog.at_level(logging.WARNING, logger=_ROUTER_LOGGER):
        for seq in range(5):
            host._emit_event(EventType.EGRESS_BLOCKED, {"seq": seq})
        stats = await router.drain(wait_budget_s=5.0)
    assert (stats.failed, stats.not_recorded, stats.written) == (2, 2, 1)
    # A1/E1: these losses are drops in the episode now, so the success also writes a
    # marker. M1 pinned the one row alone, which left all four losses unrecorded.
    assert [r["event"] for r in sink.rows] == ["egress_blocked", DROP_MARKER_EVENT]
    assert sink.rows[0]["data"]["payload"]["seq"] == 4
    assert sink.rows[1]["data"]["by_reason"] == {"write_failed": 2, "not_recorded": 2}
    assert stats.markers_written == 1
    warnings = _messages(caplog, _ROUTER_LOGGER, logging.WARNING)
    # Each kind warns on its first occurrence only (then every 256th).
    assert sum("could not be written" in m and "RuntimeError" in m for m in warnings) == 1
    assert sum("was not recorded" in m for m in warnings) == 1


async def test_a_failed_marker_write_keeps_its_drops_for_the_next_marker() -> None:
    sink = _ScriptedSink(["ok", RuntimeError("marker refused"), "ok", "ok"])
    router = DurableEventRouter(sink)
    host = _EmitHost(router)
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 0})
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 1})
    router.bind_loop(asyncio.get_running_loop())
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 2})
    await _wait_until(lambda: len(sink.calls) == 2)
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 3})
    stats = await router.drain(wait_budget_s=5.0)
    assert sink.calls == ["egress_blocked", DROP_MARKER_EVENT, "egress_blocked", DROP_MARKER_EVENT]
    markers = [r for r in sink.rows if r["event"] == DROP_MARKER_EVENT]
    assert len(markers) == 1 and markers[0]["data"]["dropped"] == 2
    assert stats.markers_written == 1


async def test_drops_made_while_a_marker_write_fails_are_merged_into_the_next_marker() -> None:
    sink = _MarkerGatedSink(fail=True)
    router = DurableEventRouter(sink, queue_max=1)
    host = _EmitHost(router)
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 0})  # unbound
    router.bind_loop(asyncio.get_running_loop())
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 1})
    await asyncio.wait_for(sink.marker_entered.wait(), timeout=5.0)
    # Premise: the first marker write is parked and has taken the unbound drop with it.
    assert [r["event"] for r in sink.rows] == ["egress_blocked"]
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 2})  # queued
    host._emit_event(EventType.SHIP_NAMED, {"seq": 3})  # queue_full
    assert dict(router.stats().dropped) == {"unbound": 1, "queue_full": 1}
    sink.gate.set()
    stats = await router.drain(wait_budget_s=5.0)
    markers = [r["data"] for r in sink.rows if r["event"] == DROP_MARKER_EVENT]
    assert len(markers) == 1 and sink.marker_calls == 2
    (marker,) = markers
    assert marker["dropped"] == 2
    assert marker["by_reason"] == {"unbound": 1, "queue_full": 1}
    assert marker["by_event"] == {"egress_blocked": 1, "ship_named": 1}
    assert marker["first_at"] <= marker["last_at"]
    assert (stats.written, stats.markers_written) == (2, 1)


async def test_a_drain_that_cancels_a_marker_write_keeps_and_reports_its_drops(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = _MarkerGatedSink()
    router = DurableEventRouter(sink)
    host = _EmitHost(router)
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 0})  # unbound
    router.bind_loop(asyncio.get_running_loop())
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 1})
    await asyncio.wait_for(sink.marker_entered.wait(), timeout=5.0)
    # Premise: every admitted row is written; only the marker write is in flight.
    assert router.stats().written == 1
    with caplog.at_level(logging.WARNING, logger=_ROUTER_LOGGER):
        stats = await router.drain(wait_budget_s=0.2)
    assert (stats.markers_written, dict(stats.dropped)) == (0, {"unbound": 1})
    assert _messages(caplog, _ROUTER_LOGGER, logging.ERROR) == []
    warnings = _messages(caplog, _ROUTER_LOGGER, logging.WARNING)
    assert any(m.startswith("AD-1195: 1 dropped durable rows have no drop-marker row") for m in warnings)
    assert _live_tasks(_WRITER_TASK) == []
    assert [r["event"] for r in sink.rows] == ["egress_blocked"]


async def test_drain_with_a_dead_writer_spends_its_budget_and_does_not_cancel_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = _GatedSink()
    router = _bound_router(sink)
    host = _EmitHost(router)
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 0})
    await asyncio.wait_for(sink.entered.wait(), timeout=5.0)
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": 1})
    (writer,) = _live_tasks(_WRITER_TASK)
    writer.cancel()
    await asyncio.wait({writer}, timeout=5.0)
    # Premise: the writer is dead and one row is still queued behind it.
    assert writer.cancelled() and router.stats().pending == 1
    with caplog.at_level(logging.WARNING, logger=_ROUTER_LOGGER):
        stats = await router.drain(wait_budget_s=0.2)
    errors = _messages(caplog, _ROUTER_LOGGER, logging.ERROR)
    assert len(errors) == 1 and "wait budget" in errors[0] and "1 rows still queued" in errors[0]
    assert not any("had not stopped" in m for m in _messages(caplog, _ROUTER_LOGGER))
    assert (stats.written, stats.pending) == (0, 1)
    assert router.unresolved("egress_blocked") == 2  # the cancelled write and the queued one


async def test_drain_of_an_unused_router_returns_at_once_and_reports_unmarked_drops(
    caplog: pytest.LogCaptureFixture,
) -> None:
    router = DurableEventRouter(_RecordingSink())
    _EmitHost(router)._emit_event(EventType.EGRESS_BLOCKED, {})
    router.bind_loop(asyncio.get_running_loop())
    with caplog.at_level(logging.WARNING, logger=_ROUTER_LOGGER):
        started = time.perf_counter()
        stats = await router.drain(wait_budget_s=5.0)
        elapsed = time.perf_counter() - started
    assert elapsed < 0.5
    assert (stats.pending, stats.written, dict(stats.dropped)) == (0, 0, {"unbound": 1})
    assert _live_tasks(_WRITER_TASK) == []
    assert any("no drop-marker row" in m for m in _messages(caplog, _ROUTER_LOGGER, logging.WARNING))


async def test_cancelling_a_drain_propagates_and_leaves_no_join_task() -> None:
    sink = _GatedSink()
    router = _bound_router(sink)
    _EmitHost(router)._emit_event(EventType.EGRESS_BLOCKED, {})
    await asyncio.wait_for(sink.entered.wait(), timeout=5.0)
    drain = asyncio.create_task(router.drain(wait_budget_s=30.0))
    # Premise: the drain is waiting on its join task.
    await _wait_until(lambda: bool(_live_tasks(_JOIN_TASK)))
    drain.cancel()
    with pytest.raises(asyncio.CancelledError):
        await drain
    await _wait_until(lambda: not _live_tasks(_JOIN_TASK))
    sink.gate.set()
    await router.drain(wait_budget_s=5.0)
    assert _live_tasks(_WRITER_TASK) == []


async def test_a_thread_hand_off_that_lands_after_drain_is_counted_closed() -> None:
    sink = _RecordingSink()
    router = _bound_router(sink)
    host = _EmitHost(router)
    thread = threading.Thread(target=host._emit_event, args=(EventType.EGRESS_BLOCKED, {"seq": 1}))
    thread.start()
    thread.join(timeout=10)  # blocks the loop, so the hand-off is queued but cannot run yet
    # Premise: offered, and not yet accepted.
    assert (router.stats().offered, router.stats().pending) == (1, 0)
    await router.drain(wait_budget_s=5.0)
    await _wait_until(lambda: dict(router.stats().dropped) == {"closed": 1})
    assert sink.rows == []


@pytest.mark.parametrize("queue_max", [0, -1, True, 2.0, "8"])
def test_router_refuses_a_queue_bound_that_bounds_nothing(queue_max: Any) -> None:
    with pytest.raises(ValueError, match="queue_max"):
        DurableEventRouter(_RecordingSink(), queue_max=queue_max)


# ── A1: early-review repairs (E1-E4) ─────────────────────────────────────────


class _ScriptedEventLog:
    """Wraps a real EventLog; each routed row write first takes the next ``script`` step.

    A step is an exception to raise or "ok" to write through; drop-marker rows
    and an exhausted script always write through to the real store.
    """

    def __init__(self, inner: EventLog, script: list[Any]) -> None:
        self.inner = inner
        self.script = list(script)

    async def log(self, category: str, event: str, *args: Any, **kwargs: Any) -> int | None:
        if category == ROUTED_CATEGORY and event != DROP_MARKER_EVENT and self.script:
            step = self.script.pop(0)
            if isinstance(step, BaseException):
                raise step
        return await self.inner.log(category, event, *args, **kwargs)


def _stored_columns(db_path: Path, row_id: int) -> dict[str, Any]:
    """Every column of the row exactly as events.db stores it."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM events WHERE id = ?", (row_id,)).fetchone()
    finally:
        conn.close()
    return dict(row)


async def test_answer_is_unknown_pending_while_a_write_is_parked(event_log: EventLog) -> None:
    """E1: a routed write still inside log() is never read as evidence of absence in-process."""
    gated = _GatedEventLog(event_log)
    router = _bound_router(gated)
    _EmitHost(router)._emit_event(EventType.SECRET_ROTATED, {"rotation": "parked"})
    await asyncio.wait_for(gated.entered.wait(), timeout=5.0)
    try:
        # Premise: the writer is parked inside log() and nothing is stored yet.
        assert not gated.gate.is_set()
        assert await event_log.query_structured(category=ROUTED_CATEGORY, limit=10) == []
        # Without the router (an out-of-process read) the parked write is invisible.
        assert (await durable_answer(event_log, EventType.SECRET_ROTATED)).status == "not_recorded"
        assert router.unresolved("secret_rotated") == 1
        pending = await durable_answer(event_log, EventType.SECRET_ROTATED, router=router)
        assert (pending.status, pending.row) == ("unknown_pending", None)
        assert pending.record_key == (ROUTED_CATEGORY, "secret_rotated")
        # A member the router holds nothing of still gets the store's own answer.
        other = await durable_answer(event_log, EventType.THREAT_DETECTED, router=router)
        assert other.status == "not_recorded"
    finally:
        gated.gate.set()
    await router.drain(wait_budget_s=5.0)
    assert router.unresolved("secret_rotated") == 0
    recorded = await durable_answer(event_log, EventType.SECRET_ROTATED, router=router)
    assert recorded.status == "recorded"


async def test_failed_write_is_marked_and_answers_unknown_dropped(event_log: EventLog) -> None:
    """E1: a write that raises is a write_failed drop, so the next marker records it."""
    router = _bound_router(_ScriptedEventLog(event_log, [RuntimeError("disk full")]))
    host = _EmitHost(router)
    host._emit_event(EventType.SECRET_ROTATED, {"rotation": "failed"})
    await _wait_until(lambda: router.stats().failed == 1)
    # Premise: the write failed and nothing was stored for it.
    assert await event_log.query_structured(category=ROUTED_CATEGORY, limit=10) == []
    host._emit_event(EventType.EGRESS_BLOCKED, {"host": "after-the-failure"})
    stats = await router.drain(wait_budget_s=5.0)

    markers = await event_log.query_structured(
        category=ROUTED_CATEGORY, event=DROP_MARKER_EVENT, limit=10
    )
    assert len(markers) == 1
    assert markers[0]["data"]["by_reason"] == {"write_failed": 1}
    assert markers[0]["data"]["by_event"] == {"secret_rotated": 1}
    answer = await durable_answer(event_log, EventType.SECRET_ROTATED, router=router)
    assert answer.status == "unknown_dropped"
    assert answer.row is not None and answer.row["id"] == markers[0]["id"]
    assert (await durable_answer(event_log, EventType.EGRESS_BLOCKED)).status == "recorded"
    assert (stats.failed, stats.written, stats.markers_written) == (1, 1, 1)
    # A write loss is counted by `failed`; `dropped` stays the count refused before a write.
    assert dict(stats.dropped) == {}


async def test_unrecorded_write_counts_as_a_drop(event_log: EventLog) -> None:
    """E1: a write that returns no row id (EventLog does while closed) is a not_recorded drop."""
    router = _bound_router(event_log)
    host = _EmitHost(router)
    await event_log.stop()
    host._emit_event(EventType.SECRET_ROTATED, {"rotation": "unrecorded"})
    await _wait_until(lambda: router.stats().not_recorded == 1)
    await event_log.start()
    # Premise: the store was closed for that write, so nothing of it was stored.
    assert await event_log.query_structured(category=ROUTED_CATEGORY, limit=10) == []
    host._emit_event(EventType.EGRESS_BLOCKED, {"host": "after-the-reopen"})
    stats = await router.drain(wait_budget_s=5.0)

    markers = await event_log.query_structured(
        category=ROUTED_CATEGORY, event=DROP_MARKER_EVENT, limit=10
    )
    assert len(markers) == 1
    assert markers[0]["data"]["by_reason"] == {"not_recorded": 1}
    assert markers[0]["data"]["by_event"] == {"secret_rotated": 1}
    answer = await durable_answer(event_log, EventType.SECRET_ROTATED)
    assert answer.status == "unknown_dropped"
    assert answer.row is not None and answer.row["id"] == markers[0]["id"]
    assert (stats.not_recorded, stats.written, stats.markers_written) == (1, 1, 1)
    assert dict(stats.dropped) == {}


@pytest.mark.parametrize("shape", ["write_failed", "not_recorded", "unbound"])
async def test_a_loss_no_marker_records_yet_is_unknown_pending_in_process(
    shape: str, event_log: EventLog
) -> None:
    """E1: until a drop-marker row records a lost record, the in-process answer stays open.

    The reviewer's premise with nothing after it: one failing write and no later
    success, so no marker is ever written by the writer loop.
    """
    if shape == "write_failed":
        router = _bound_router(_ScriptedEventLog(event_log, [RuntimeError("disk full")]))
    elif shape == "not_recorded":
        router = _bound_router(event_log)
        await event_log.stop()
    else:
        router = DurableEventRouter(event_log)
    host = _EmitHost(router)
    host._emit_event(EventType.SECRET_ROTATED, {"rotation": shape})
    if shape == "write_failed":
        await _wait_until(lambda: router.stats().failed == 1)
    elif shape == "not_recorded":
        await _wait_until(lambda: router.stats().not_recorded == 1)
        await event_log.start()
    else:
        assert dict(router.stats().dropped) == {"unbound": 1}
    # Premise: nothing about the member reached the store, not even a drop marker.
    assert await event_log.query_structured(category=ROUTED_CATEGORY, limit=10) == []
    assert (await durable_answer(event_log, EventType.SECRET_ROTATED)).status == "not_recorded"
    assert router.unresolved("secret_rotated") == 1
    pending = await durable_answer(event_log, EventType.SECRET_ROTATED, router=router)
    assert (pending.status, pending.row) == ("unknown_pending", None)

    # A later write succeeds and writes the marker; from then on the store answers.
    if shape == "unbound":
        router.bind_loop(asyncio.get_running_loop())
    host._emit_event(EventType.EGRESS_BLOCKED, {"after": shape})
    stats = await router.drain(wait_budget_s=5.0)
    assert stats.markers_written == 1
    assert router.unresolved("secret_rotated") == 0
    assert router.unresolved("egress_blocked") == 0
    marked = await durable_answer(event_log, EventType.SECRET_ROTATED, router=router)
    assert marked.status == "unknown_dropped"
    assert marked.row is not None and marked.row["data"]["by_reason"] == {shape: 1}


async def test_unresolved_counts_a_hand_off_the_loop_has_not_run_yet(event_log: EventLog) -> None:
    """E1: a record in a thread's hand-off is unresolved before the loop has accepted it."""
    router = _bound_router(event_log)
    host = _EmitHost(router)
    thread = threading.Thread(
        target=host._emit_event, args=(EventType.EGRESS_BLOCKED, {"seq": "handed-off"})
    )
    thread.start()
    thread.join(timeout=10)  # blocks the loop, so the hand-off is scheduled but cannot run yet
    # Premise: offered and handed off, not yet accepted or dropped.
    stats = router.stats()
    assert (stats.offered, stats.pending, dict(stats.dropped)) == (1, 0, {})
    assert router.unresolved("egress_blocked") == 1
    await _wait_until(lambda: router.stats().written == 1)
    assert router.unresolved("egress_blocked") == 0
    await router.drain(wait_budget_s=5.0)


async def test_truncated_marker_scan_is_unknown_dropped_not_evidence(
    event_log: EventLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E2: a marker scan that read its whole bound without a match cannot establish absence."""
    monkeypatch.setattr(durable_events_module, "_MARKER_SCAN", 3)

    async def _marker(by_event: dict[str, int]) -> None:
        await event_log.log(
            ROUTED_CATEGORY, DROP_MARKER_EVENT, data={"dropped": 1, "by_event": by_event}
        )

    await _marker({"egress_blocked": 1})  # the oldest marker names the member
    await _marker({"ship_named": 1})
    # Control: fewer markers than the bound, so the scan read all of them.
    control = await durable_answer(event_log, EventType.EGRESS_BLOCKED)
    assert control.status == "unknown_dropped" and control.row is not None
    assert (await durable_answer(event_log, EventType.THREAT_DETECTED)).status == "not_recorded"

    await _marker({"ship_named": 1})
    await _marker({"ship_named": 1})
    # Premise: the newest 3 markers fill the bound and none names the member; an older one does.
    newest = await event_log.query_structured(
        category=ROUTED_CATEGORY, event=DROP_MARKER_EVENT, limit=3
    )
    every = await event_log.query_structured(
        category=ROUTED_CATEGORY, event=DROP_MARKER_EVENT, limit=10
    )
    assert len(newest) == 3 and all("egress_blocked" not in m["data"]["by_event"] for m in newest)
    assert len(every) == 4 and "egress_blocked" in every[-1]["data"]["by_event"]
    hidden = await durable_answer(event_log, EventType.EGRESS_BLOCKED)
    assert (hidden.status, hidden.row) == ("unknown_dropped", None)
    assert hidden.record_key == (ROUTED_CATEGORY, "egress_blocked")
    never_named = await durable_answer(event_log, EventType.THREAT_DETECTED)
    assert (never_named.status, never_named.row) == ("unknown_dropped", None)


def test_the_marker_scan_reads_up_to_1000_markers() -> None:
    """E2: the bound the truncated-scan rule is measured against."""
    assert durable_events_module._MARKER_SCAN == 1000


@pytest.mark.parametrize(
    "agent_id",
    [
        "Bearer sk-review-only-not-real-secret",
        "token:sk-review-only-not-real-secret",
        "captain@example.com",
        "agent 7",
        "agent-7\n",
        "a" * 257,
        "",
    ],
    ids=["bearer-secret", "charset-clean-secret", "email", "space", "trailing-newline", "257-chars", "empty"],
)
async def test_agent_id_the_projection_would_change_is_stored_as_null(
    agent_id: str, event_log: EventLog, tmp_path: Path
) -> None:
    """A2 R5 (was A1 E3): whatever agent_id holds, the indexed columns stay NULL.

    A1 E3 indexed an id that passed a charset and projection bar; A2 R5 indexes none,
    so the only copy is the payload's, projected as a governed reader would see it.
    """
    router = _bound_router(event_log)
    _EmitHost(router)._emit_event(
        EventType.THREAT_DETECTED, {"agent_id": agent_id, "threat_type": "ad1195-e3"}
    )
    assert (await router.drain(wait_budget_s=5.0)).written == 1
    (row,) = await event_log.query_structured(
        category=ROUTED_CATEGORY, event="threat_detected", limit=10
    )
    columns = _stored_columns(tmp_path / "events.db", row["id"])
    assert (columns["agent_id"], columns["correlation_id"]) == (None, None)
    projected, _ = bounded_json_payload(agent_id)
    assert row["data"]["payload"]["agent_id"] == projected
    whole_row = " ".join(str(value) for value in columns.values())
    if projected != agent_id:
        assert agent_id not in whole_row
    assert "sk-review-only-not-real-secret" not in whole_row


@pytest.mark.parametrize(
    "agent_id",
    [
        "a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        "counselor_counselor_0",
        "a" * 256,
    ],
    ids=["hex", "uuid", "pool-id", "256-chars"],
)
async def test_an_ordinary_agent_id_is_kept_only_in_the_payload_copy(
    agent_id: str, event_log: EventLog, tmp_path: Path
) -> None:
    router = _bound_router(event_log)
    _EmitHost(router)._emit_event(EventType.THREAT_DETECTED, {"agent_id": agent_id})
    assert (await router.drain(wait_budget_s=5.0)).written == 1
    (row,) = await event_log.query_structured(
        category=ROUTED_CATEGORY, event="threat_detected", limit=10
    )
    # A2 R5: this pinned A1 E3's rule, which indexed an ordinary id; the routed row then
    # answered AD-541's latest-row-for-this-agent query in place of the agent's own row.
    assert _stored_columns(tmp_path / "events.db", row["id"])["agent_id"] is None
    assert row["data"]["payload"]["agent_id"] == agent_id


async def test_stale_hand_off_after_drain_and_rebind_is_counted_closed(
    event_log: EventLog,
) -> None:
    """E4: a hand-off scheduled before a drain is refused by the binding that follows it."""
    loop = asyncio.get_running_loop()
    router = _bound_router(event_log)
    host = _EmitHost(router)
    thread = threading.Thread(
        target=host._emit_event, args=(EventType.EGRESS_BLOCKED, {"seq": "stale"})
    )
    thread.start()
    thread.join(timeout=10)  # blocks the loop, so the hand-off is scheduled but cannot run yet
    # Premise: offered and handed off, not yet accepted or dropped.
    assert (router.stats().offered, router.stats().pending, dict(router.stats().dropped)) == (
        1, 0, {},
    )
    await router.drain(wait_budget_s=5.0)  # no queue exists yet, so this returns without yielding
    # Premise: the hand-off was still pending when drain ran; nothing accepted or dropped it.
    assert (router.stats().pending, dict(router.stats().dropped)) == (0, {})
    assert _live_tasks(_WRITER_TASK) == []
    router.bind_loop(loop)
    ran = asyncio.Event()
    loop.call_soon(ran.set)  # FIFO: this runs only after the stale hand-off has run
    await asyncio.wait_for(ran.wait(), timeout=5.0)

    assert dict(router.stats().dropped) == {"closed": 1}
    assert router.stats().pending == 0 and _live_tasks(_WRITER_TASK) == []
    assert await event_log.query_structured(category=ROUTED_CATEGORY, limit=10) == []
    host._emit_event(EventType.EGRESS_BLOCKED, {"seq": "fresh"})
    stats = await router.drain(wait_budget_s=5.0)
    rows = await event_log.query_structured(
        category=ROUTED_CATEGORY, event="egress_blocked", limit=10
    )
    assert [r["data"]["payload"]["seq"] for r in rows] == ["fresh"]
    markers = await event_log.query_structured(
        category=ROUTED_CATEGORY, event=DROP_MARKER_EVENT, limit=10
    )
    assert len(markers) == 1 and markers[0]["data"]["by_reason"] == {"closed": 1}
    assert (stats.written, stats.markers_written) == (1, 1)


@pytest.mark.parametrize(
    ("step", "phrase"),
    [(RuntimeError("disk full"), "could not be written"), ("none", "was not recorded")],
    ids=["write_failed", "not_recorded"],
)
async def test_a_write_loss_that_opens_a_new_drop_episode_warns(
    step: Any, phrase: str, caplog: pytest.LogCaptureFixture
) -> None:
    """E1: the first loss of every drop episode warns, even past the write path's own rate limit."""
    sink = _ScriptedSink([step, "ok", "ok", step, "ok", "ok"])
    router = _bound_router(sink)
    host = _EmitHost(router)
    with caplog.at_level(logging.WARNING, logger=_ROUTER_LOGGER):
        for seq in range(4):
            host._emit_event(EventType.EGRESS_BLOCKED, {"seq": seq})
            await _wait_until(lambda n=seq: len(sink.calls) >= (1, 3, 4, 6)[n])
        stats = await router.drain(wait_budget_s=5.0)
    # Premise: two losses, each opening its own episode, and each recorded by its own marker.
    assert sink.calls == [
        "egress_blocked", "egress_blocked", DROP_MARKER_EVENT,
        "egress_blocked", "egress_blocked", DROP_MARKER_EVENT,
    ]
    assert stats.markers_written == 2 and stats.written == 2
    warnings = [m for m in _messages(caplog, _ROUTER_LOGGER, logging.WARNING) if phrase in m]
    assert len(warnings) == 2


# ── A2: routed rows stay out of legacy readers and indexed columns (R1-R5) ──


class _EpochTimestampEventLog:
    """A real EventLog whose ``query`` rows carry epoch-second timestamps, which AD-491 reads.

    AD-491's window filter calls ``float()`` on each row's timestamp, and EventLog writes
    ISO-8601 text, so over the unadapted store ``analyze()`` raises ValueError before it
    forms a bucket (measured on this tree; pre-existing, and outside AD-1195). Every
    ``query`` argument, ``exclude_category`` included, reaches the real EventLog as given.
    """

    def __init__(self, inner: EventLog) -> None:
        self.inner = inner

    async def query(self, **kwargs: Any) -> list[dict[str, Any]]:
        rows = await self.inner.query(**kwargs)
        return [dict(r, timestamp=datetime.fromisoformat(r["timestamp"]).timestamp()) for r in rows]


def _event_signal(report: InfodynamicReport) -> EntropySignal:
    return next(s for s in report.signals if s.name == "event_log_category")


@pytest.mark.parametrize(
    ("agent_id", "correlation_id", "redacted"),
    [
        ("agent-7", "corr-ad1195-col1", False),
        ("Bearer sk-review-only-not-real-secret", "Bearer sk-review-only-not-real-secret-two", True),
    ],
    ids=["ordinary", "secret-shaped"],
)
async def test_routed_row_leaves_the_indexed_columns_null_and_keeps_both_in_the_payload(
    agent_id: str, correlation_id: str, redacted: bool, event_log: EventLog, tmp_path: Path
) -> None:
    """COL-1 (A2 R5): agent_id and correlation_id live only in the routed row's projected payload."""
    payload = {"agent_id": agent_id, "correlation_id": correlation_id, "threat_type": "ad1195-col1"}
    projected, _ = bounded_json_payload(payload)
    # Premise: the projection keeps the ordinary values as they are and redacts the secret-shaped ones.
    assert (projected["agent_id"] != agent_id) is redacted
    assert (projected["correlation_id"] != correlation_id) is redacted
    router = _bound_router(event_log)
    _EmitHost(router)._emit_event(EventType.THREAT_DETECTED, payload)
    assert (await router.drain(wait_budget_s=5.0)).written == 1
    (row,) = await event_log.query_structured(
        category=ROUTED_CATEGORY, event="threat_detected", limit=10
    )

    columns = _stored_columns(tmp_path / "events.db", row["id"])

    assert (columns["agent_id"], columns["correlation_id"]) == (None, None)
    stored = row["data"]["payload"]
    assert (stored["agent_id"], stored["correlation_id"]) == (
        projected["agent_id"], projected["correlation_id"],
    )
    assert "sk-review-only-not-real-secret" not in " ".join(str(v) for v in columns.values())


async def test_the_latest_row_for_an_agent_stays_its_legacy_row(event_log: EventLog) -> None:
    """AD541-1 (A2 R5): AD-541's latest-row-for-an-agent read never lands on a routed row."""
    agent = "agent-ad541"
    legacy_id = await event_log.log(
        "lifecycle", "agent_wired", agent_id=agent, agent_type="architect"
    )
    router = _bound_router(event_log)
    _EmitHost(router)._emit_event(
        EventType.THREAT_DETECTED, {"agent_id": agent, "threat_type": "ad1195-ad541"}
    )
    assert (await router.drain(wait_budget_s=5.0)).written == 1
    # Premise: the routed row exists, is newer than the legacy row, and names the agent.
    (routed,) = await event_log.query_structured(
        category=ROUTED_CATEGORY, event="threat_detected", limit=10
    )
    assert type(legacy_id) is int and routed["id"] > legacy_id
    assert routed["data"]["payload"]["agent_id"] == agent

    # The AD-541 Pillar 1 call shape (cognitive_agent.py): one row, filtered by agent.
    latest = await event_log.query(agent_id=agent, limit=1)

    assert [(r["id"], r["category"], r["event"]) for r in latest] == [
        (legacy_id, "lifecycle", "agent_wired")
    ]


async def test_proactive_recent_events_list_only_legacy_rows(event_log: EventLog) -> None:
    """CTX-1 (A2 R2): the proactive prompt's recent system events are never routed rows."""
    for index in range(3):
        await event_log.log("system", f"ctx1_legacy_{index}", agent_type="architect")
    router = _bound_router(event_log)
    host = _EmitHost(router)
    for seq in range(11):
        host._emit_event(EventType.EGRESS_BLOCKED, {"seq": seq})
    assert (await router.drain(wait_budget_s=5.0)).written == 11
    # Premise: the read this context made before A2, an unfiltered query(limit=10),
    # returns routed rows only.
    unfiltered = await event_log.query(limit=10)
    assert len(unfiltered) == 10 and {r["category"] for r in unfiltered} == {ROUTED_CATEGORY}
    agent = _make_mock_agent()
    runtime = _make_mock_runtime(agents=[agent])
    runtime.event_log = event_log
    loop = _make_loop()
    loop.set_runtime(runtime)

    context = await loop._gather_context(agent, 0.7)

    assert context["recent_events"] == [
        {"category": "system", "event": f"ctx1_legacy_{index}", "agent_type": "architect"}
        for index in (2, 1, 0)
    ]


async def test_infodynamic_category_entropy_is_unchanged_by_routed_rows(
    event_log: EventLog,
) -> None:
    """ENT-1 (A2 R3): AD-491's event_log_category signal is the same with and without 50 routed rows."""
    for index in range(4):
        await event_log.log("system", f"ent1_system_{index}")
        await event_log.log("mesh", f"ent1_mesh_{index}")
    adapted = _EpochTimestampEventLog(event_log)
    probe = InfodynamicProbe(
        runtime=SimpleNamespace(event_log=adapted, trust_network=None, registry=None),
        event_window_seconds=3600.0,
    )
    without = _event_signal(await probe.analyze())
    router = _bound_router(event_log)
    host = _EmitHost(router)
    for seq in range(50):
        host._emit_event(EventType.EGRESS_BLOCKED, {"seq": seq})
    assert (await router.drain(wait_budget_s=5.0)).written == 50
    # Premise: all 50 routed rows are inside the probe's window, and an unfiltered read sees them.
    cutoff = time.time() - 3600.0
    routed = [r for r in await adapted.query(limit=10_000) if r["category"] == ROUTED_CATEGORY]
    assert len(routed) == 50 and all(r["timestamp"] >= cutoff for r in routed)

    with_routed = _event_signal(await probe.analyze())

    assert with_routed == without
    assert without.entropy == pytest.approx(1.0)
    assert (without.sample_size, without.bucket_count) == (8, 2)


async def test_query_exclude_category_leaves_out_exactly_that_category(event_log: EventLog) -> None:
    """Q-1 (A2 R1): exclude_category drops the named category's rows and nothing else."""
    await event_log.log("system", "q1_system")
    await event_log.log(ROUTED_CATEGORY, "q1_routed")
    await event_log.log("mesh", "q1_mesh")
    # Premise: an unfiltered read returns all three rows.
    assert [r["event"] for r in await event_log.query(limit=10)] == [
        "q1_mesh", "q1_routed", "q1_system",
    ]

    kept = await event_log.query(limit=10, exclude_category=ROUTED_CATEGORY)

    assert [(r["category"], r["event"]) for r in kept] == [
        ("mesh", "q1_mesh"), ("system", "q1_system"),
    ]


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"agent_id": "agent-q2", "exclude_category": ROUTED_CATEGORY}, ["q2_mesh", "q2_system_b"]),
        ({"agent_id": "agent-q2", "exclude_category": ROUTED_CATEGORY, "limit": 1}, ["q2_mesh"]),
        ({"category": "system", "exclude_category": "system"}, []),
        ({"category": "system", "agent_id": "agent-q2", "exclude_category": "system"}, []),
    ],
    ids=["with-agent", "with-agent-and-limit", "with-category", "with-category-and-agent"],
)
async def test_query_exclude_category_combines_with_category_agent_and_limit(
    filters: dict[str, Any], expected: list[str], event_log: EventLog
) -> None:
    """Q-2 (A2 R1): the exclusion is ANDed with the other filters and applied before the limit."""
    await event_log.log("system", "q2_system_a")
    await event_log.log("system", "q2_system_b", agent_id="agent-q2")
    await event_log.log("mesh", "q2_mesh", agent_id="agent-q2")
    await event_log.log(ROUTED_CATEGORY, "q2_routed", agent_id="agent-q2")
    # Premise: without the exclusion the same filters return a row the exclusion must remove.
    unexcluded = {key: value for key, value in filters.items() if key != "exclude_category"}
    assert [r["event"] for r in await event_log.query(**unexcluded)] != expected

    rows = await event_log.query(**filters)

    assert [r["event"] for r in rows] == expected


_HEAD_QUERY_SQL = (
    "SELECT id, timestamp, category, event, agent_id, agent_type, pool, detail, "
    "correlation_id, parent_event_id, data FROM events"
)


@pytest.mark.parametrize(
    ("filters", "where", "params"),
    [
        ({}, "", ["100"]),
        ({"category": "system", "limit": 5}, " WHERE category = ?", ["system", "5"]),
        ({"agent_id": "a-1", "limit": 1}, " WHERE agent_id = ?", ["a-1", "1"]),
        (
            {"category": "system", "agent_id": "a-1", "limit": 7},
            " WHERE category = ? AND agent_id = ?",
            ["system", "a-1", "7"],
        ),
    ],
    ids=["unfiltered", "category", "agent", "category-and-agent"],
)
@pytest.mark.parametrize("exclusion", ["omitted", "none", "empty"])
async def test_query_without_an_exclusion_sends_the_head_sql_and_params(
    exclusion: str,
    filters: dict[str, Any],
    where: str,
    params: list[str],
    event_log: EventLog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q-3 (A2 R1): unset (None) or empty, exclude_category leaves every caller's SQL as it was."""
    execute = event_log._db.execute
    sent: list[tuple[str, list[Any]]] = []

    def _recording_execute(sql: str, parameters: Any = None) -> Any:
        sent.append((sql, list(parameters)))
        return execute(sql, parameters)

    monkeypatch.setattr(event_log._db, "execute", _recording_execute)
    extra = {"omitted": {}, "none": {"exclude_category": None}, "empty": {"exclude_category": ""}}

    assert await event_log.query(**filters, **extra[exclusion]) == []

    assert sent == [(_HEAD_QUERY_SQL + where + " ORDER BY id DESC LIMIT ?", params)]
