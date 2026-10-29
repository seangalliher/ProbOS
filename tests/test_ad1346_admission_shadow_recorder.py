"""AD-1346 M3b (#1604): the shadow recorder over a real ``AdmissionShadowStore`` in ``tmp_path``.

- R1  ``offer`` counts each verdict by UTC hour and latency bucket and keeps only would-refuse samples; the marker
      row counts what was offered and written.
- R2  ``offer`` is a plain function: no await, and no store, task, wait or I/O call.
- R3  a full sample buffer drops the sample, counts it, and still counts the verdict.
- R4  a verdict that needs a new pending key beyond ``PENDING_KEY_LIMIT`` is dropped, counted and not sampled.
- R5  a write that fails stays pending; ``stop`` writes it once and logs the failure once, at WARNING.
- R6  a batch put back after a failed write keeps at most ``SAMPLE_BUFFER_LIMIT`` samples and counts the rest.
- R7  the flusher writes on its cadence while the recorder runs, and has ended when ``stop`` returns.
- R8  ``start`` marks the boot's hour (a marker row of zeros) and runs once; the recorder takes only the store.
- R9  an offer after ``stop`` began is counted as late and not written.
- R10 the recorder prunes at its first flush of each UTC day of its wall clock.
- R11 ``AdmissionService.shadow`` offers each verdict and its measured time; ``decide`` offers nothing; the
      constructor takes a ``ShadowRecorder`` or None.
- R12 a recorder whose ``offer`` raises is a counted shadow failure, after the verdict was tallied.
- R13 ``stop`` does not return while a write is in flight.
"""

from __future__ import annotations

import ast
import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from probos.admission import AdmissionService, AdmissionVerdict, WorkRequest
from probos.admission import recorder as recorder_module
from probos.admission.recorder import COUNTER_NAMES, FLUSHER_TASK_NAME, ShadowRecorder
from probos.admission.store import DAY_SECONDS, AdmissionShadowStore, ShadowBatch, utc_hour
from probos.agent_stop import AgentStopService
from probos.crew_profile import CallsignRegistry
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.substrate.registry import AgentRegistry
from tests.fixtures.ad1343_seam_census import function
from tests.fixtures.ad1346_shadow import T0, admit, refuse, rows

INSTANCE_ID = "ad1346-m3b-ship"
MARKERS = "SELECT boot_id, hour, offered, written, dropped, samples_dropped FROM shadow_markers ORDER BY hour"
TOTALS = "SELECT SUM(offered), SUM(written), SUM(dropped), SUM(samples_dropped) FROM shadow_markers"


class _Clock:
    """An injected wall clock the test moves."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _FailingStore(AdmissionShadowStore):
    """A real store whose first ``failures`` writes call ``during`` (an offer while a write is in flight), then raise."""

    def __init__(self, *, data_dir: Path, failures: int) -> None:
        super().__init__(data_dir=data_dir)
        self.failures = failures
        self.during: Callable[[], None] | None = None
        self.attempts = 0

    async def write_batch(self, boot_id: str, batch: ShadowBatch) -> int:
        self.attempts += 1
        if self.attempts <= self.failures:
            if self.during is not None:
                self.during()
            raise OSError("INJECTED shadow store write failure")
        return await super().write_batch(boot_id, batch)


class _CountingStore(AdmissionShadowStore):
    """A real store that records the ``now`` of each prune."""

    def __init__(self, *, data_dir: Path) -> None:
        super().__init__(data_dir=data_dir)
        self.prunes: list[float] = []

    async def prune(self, now: float) -> tuple[int, int]:
        self.prunes.append(now)
        return await super().prune(now)


class _GatedStore(AdmissionShadowStore):
    """A real store whose writes wait for ``gate``."""

    def __init__(self, *, data_dir: Path) -> None:
        super().__init__(data_dir=data_dir)
        self.entered = asyncio.Event()
        self.gate = asyncio.Event()

    async def write_batch(self, boot_id: str, batch: ShadowBatch) -> int:
        self.entered.set()
        await self.gate.wait()
        return await super().write_batch(boot_id, batch)


class _RaisingRecorder(ShadowRecorder):
    def offer(self, verdict: AdmissionVerdict, elapsed_ns: int) -> None:
        raise RuntimeError("INJECTED recorder failure")


async def _until(check: Callable[[], Awaitable[bool]], timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not await check():
        assert loop.time() < deadline, "the condition did not hold in time"
        await asyncio.sleep(0.01)


async def _at_least(items: list[Any], count: int) -> bool:
    return len(items) >= count


def _flushers() -> list[asyncio.Task[Any]]:
    return [task for task in asyncio.all_tasks() if task.get_name() == FLUSHER_TASK_NAME and not task.done()]


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[AdmissionShadowStore]:
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    try:
        yield shadow
    finally:
        await shadow.stop()


@pytest_asyncio.fixture
async def identities(tmp_path: Path) -> AsyncIterator[IdentityService]:
    """The real facade over a started identity registry and a ``CallsignRegistry`` bound to an empty ``AgentRegistry``."""
    registry = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await registry.start()
        await registry.start(instance_id=INSTANCE_ID, vessel_name="Ad1346m3b", version="1")
        callsigns = CallsignRegistry()
        callsigns.bind_registry(AgentRegistry())
        yield IdentityService(registry, callsigns)
    finally:
        await registry.stop()


@pytest_asyncio.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    record = AgentStopService(data_dir=tmp_path / "stops")
    await record.start()
    try:
        yield record
    finally:
        await record.stop()


async def test_offer_counts_every_verdict_and_keeps_only_would_refuse_samples(store: AdmissionShadowStore) -> None:
    """R1 (kills RC-2, RC-3, RC-5, RC-13)."""
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    recorder.offer(admit(), 1000)
    recorder.offer(admit(), 1000)
    recorder.offer(refuse(), 1000)
    await recorder.stop()
    assert await rows(store.path, "SELECT day, outcome, latency_bucket, decisions FROM shadow_aggregates ORDER BY outcome") == [
        ("2026-10-28", "admit", 10, 2), ("2026-10-28", "would_refuse", 10, 1),
    ]
    assert await rows(store.path, "SELECT reason_code, latency_ns FROM shadow_samples") == [("identity_unresolved", 1000)]
    assert await rows(store.path, MARKERS) == [(recorder.boot_id, utc_hour(T0), 3, 3, 0, 0)]
    assert len(recorder.boot_id) == 32 and int(recorder.boot_id, 16) >= 0
    assert recorder.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {"offered": 3, "written": 3}


def test_offer_awaits_nothing_and_does_no_io() -> None:
    """R2: #1601's bottleneck rule on the hot path; ``offer`` is synchronous and calls no store, task, wait or I/O name."""
    node = function("src/probos/admission/recorder.py", "ShadowRecorder.offer")
    assert isinstance(node, ast.FunctionDef), "offer must not be a coroutine"
    forbidden = {
        "write_batch", "prune", "connect", "execute", "executemany", "commit", "create_task", "sleep", "wait",
        "wait_for", "open", "acquire", "dumps", "run_in_executor",
    }
    for child in ast.walk(node):
        assert not isinstance(child, (ast.Await, ast.AsyncFor, ast.AsyncWith)), child.lineno
        if isinstance(child, ast.Call):
            func = child.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            assert name not in forbidden, (child.lineno, name)


async def test_a_full_sample_buffer_drops_the_sample_and_still_counts_the_verdict(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3 (kills RC-6)."""
    monkeypatch.setattr(recorder_module, "SAMPLE_BUFFER_LIMIT", 2)
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    for _ in range(3):
        recorder.offer(refuse(), 1)
    await recorder.stop()
    assert await rows(store.path, "SELECT COUNT(*) FROM shadow_samples") == [(2,)]
    assert await rows(store.path, TOTALS) == [(3, 3, 0, 1)]
    assert recorder.counters()["samples_dropped"] == 1


async def test_a_new_key_beyond_the_pending_limit_is_dropped_and_counted(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R4 (kills RC-4)."""
    monkeypatch.setattr(recorder_module, "PENDING_KEY_LIMIT", 1)
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    recorder.offer(refuse(), 1)
    recorder.offer(refuse(), 1)
    recorder.offer(refuse(seam="tool"), 1)  # needs a second key
    await recorder.stop()
    assert await rows(store.path, "SELECT seam, decisions FROM shadow_aggregates") == [("intent", 2)]
    assert await rows(store.path, "SELECT seam FROM shadow_samples") == [("intent",), ("intent",)]
    assert await rows(store.path, TOTALS) == [(3, 2, 1, 0)]
    assert recorder.counters()["dropped"] == 1


async def test_a_failed_write_stays_pending_and_is_written_once(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """R5 (kills RC-10, RC-14, RC-17)."""
    caplog.set_level(logging.DEBUG, logger="probos.admission.recorder")
    shadow = _FailingStore(data_dir=tmp_path / "data", failures=1)
    await shadow.start()
    try:
        recorder = ShadowRecorder(shadow, wall_clock=_Clock(T0))
        recorder.offer(refuse(), 1)
        recorder.offer(refuse(), 1)
        await recorder.stop()
    finally:
        await shadow.stop()
    assert shadow.attempts == 2
    assert await rows(shadow.path, "SELECT decisions FROM shadow_aggregates") == [(2,)]
    assert await rows(shadow.path, "SELECT COUNT(*) FROM shadow_samples") == [(2,)]
    assert recorder.counters()["flush_failures"] == 1 and recorder.counters()["written"] == 2
    records = [r for r in caplog.records if r.name == "probos.admission.recorder"]
    assert [r.levelno for r in records] == [logging.WARNING]
    assert records[0].exc_info is not None and "INJECTED" in str(records[0].exc_info[1])


async def test_a_restored_batch_keeps_at_most_the_sample_buffer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R6: an offer made while a write is in flight, then that write fails, overflows the buffer (kills RC-15, RC-16)."""
    monkeypatch.setattr(recorder_module, "SAMPLE_BUFFER_LIMIT", 2)
    monkeypatch.setattr(recorder_module, "FLUSH_INTERVAL_SECONDS", 0.01)
    shadow = _FailingStore(data_dir=tmp_path / "data", failures=1)
    await shadow.start()
    try:
        recorder = ShadowRecorder(shadow, wall_clock=_Clock(T0))
        shadow.during = lambda: recorder.offer(refuse(), 1)
        recorder.start()
        recorder.offer(refuse(), 1)
        recorder.offer(refuse(), 1)

        async def written_after_the_failure() -> bool:
            return shadow.attempts >= 2

        await _until(written_after_the_failure)
        await recorder.stop()
    finally:
        await shadow.stop()
    assert await rows(shadow.path, "SELECT COUNT(*) FROM shadow_samples") == [(2,)]
    assert await rows(shadow.path, TOTALS) == [(3, 3, 0, 1)]
    assert recorder.counters()["samples_dropped"] == 1


async def test_the_flusher_writes_on_its_cadence_and_stop_awaits_its_last_flush(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R7 (kills RC-8)."""
    monkeypatch.setattr(recorder_module, "FLUSH_INTERVAL_SECONDS", 0.01)
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    recorder.start()
    tasks = _flushers()
    assert len(tasks) == 1
    recorder.offer(admit(), 1)

    async def written_once() -> bool:
        return await rows(store.path, "SELECT COALESCE(SUM(written), 0) FROM shadow_markers") == [(1,)]

    await _until(written_once)
    recorder.offer(admit(), 1)
    await recorder.stop()
    assert all(task.done() for task in tasks) and _flushers() == []
    assert await rows(store.path, "SELECT SUM(offered), SUM(written) FROM shadow_markers") == [(2, 2)]


async def test_start_marks_the_boot_and_runs_once(store: AdmissionShadowStore) -> None:
    """R8 (kills RC-7)."""
    with pytest.raises(TypeError, match="AdmissionShadowStore"):
        ShadowRecorder(object())  # type: ignore[arg-type]
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    recorder.start()
    with pytest.raises(RuntimeError, match="starts once"):
        recorder.start()
    await recorder.stop()
    assert await rows(store.path, MARKERS) == [(recorder.boot_id, utc_hour(T0), 0, 0, 0, 0)]
    with pytest.raises(RuntimeError, match="starts once"):
        recorder.start()


async def test_an_offer_after_stop_began_is_counted_late_and_not_written(store: AdmissionShadowStore) -> None:
    """R9 (kills RC-1)."""
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    recorder.offer(admit(), 1)
    await recorder.stop()
    recorder.offer(admit(), 1)
    await recorder.stop()
    assert recorder.counters()["late"] == 1 and recorder.counters()["offered"] == 1
    assert await rows(store.path, "SELECT SUM(decisions) FROM shadow_aggregates") == [(1,)]


async def test_the_recorder_prunes_once_per_utc_day(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R10 (kills RC-11, RC-12)."""
    monkeypatch.setattr(recorder_module, "FLUSH_INTERVAL_SECONDS", 0.01)
    shadow = _CountingStore(data_dir=tmp_path / "data")
    await shadow.start()
    clock = _Clock(T0)
    try:
        recorder = ShadowRecorder(shadow, wall_clock=clock)
        recorder.start()
        await _until(lambda: _at_least(shadow.prunes, 1))
        await asyncio.sleep(0.1)  # about ten more flushes on the same UTC day
        assert len(shadow.prunes) == 1
        clock.now = T0 + DAY_SECONDS
        await _until(lambda: _at_least(shadow.prunes, 2))
        await asyncio.sleep(0.1)
        await recorder.stop()
    finally:
        await shadow.stop()
    assert shadow.prunes == [T0, T0 + DAY_SECONDS]


async def test_the_service_offers_each_shadow_verdict_and_its_time_to_its_recorder(
    identities: IdentityService, stops: AgentStopService, store: AdmissionShadowStore,
) -> None:
    """R11 (kills SV-1, SV-2, SV-3, SV-4)."""
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    ticks = iter([0, 1000])
    gate = AdmissionService(identities, stops, clock=lambda: next(ticks), recorder=recorder)
    assert vars(gate)["_recorder"] is recorder
    assert gate.shadow(presented_id="nobody", work_kind="intent", seam="intent", origin="captain", origin_id="captain") is None
    assert gate.failures == 0 and recorder.counters()["offered"] == 1
    gate.decide(WorkRequest("nobody", "intent", "intent", "captain", "captain"))
    assert recorder.counters()["offered"] == 1, "decide() offers nothing"
    await recorder.stop()
    assert await rows(store.path, "SELECT seam, outcome, reason_code, latency_bucket, decisions FROM shadow_aggregates") == [
        ("intent", "would_refuse", "identity_unresolved", 10, 1),
    ]
    assert vars(AdmissionService(identities, stops))["_recorder"] is None
    with pytest.raises(TypeError, match="ShadowRecorder"):
        AdmissionService(identities, stops, recorder=object())  # type: ignore[arg-type]


async def test_a_raising_recorder_is_a_counted_shadow_failure(
    identities: IdentityService, stops: AgentStopService, store: AdmissionShadowStore,
) -> None:
    """R12: ``shadow``'s ``except Exception`` holds the offer; the verdict was tallied before it."""
    gate = AdmissionService(identities, stops, recorder=_RaisingRecorder(store))
    assert gate.shadow(presented_id="nobody", work_kind="intent", seam="intent", origin="captain", origin_id="captain") is None
    assert gate.failures == 1
    assert gate.tally() == {("intent", "intent", "identity_unresolved"): 1}


async def test_stop_waits_for_a_write_in_flight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R13 (kills RC-9)."""
    monkeypatch.setattr(recorder_module, "FLUSH_INTERVAL_SECONDS", 0.01)
    shadow = _GatedStore(data_dir=tmp_path / "data")
    await shadow.start()
    try:
        recorder = ShadowRecorder(shadow, wall_clock=_Clock(T0))
        recorder.start()
        recorder.offer(admit(), 1)
        await asyncio.wait_for(shadow.entered.wait(), 5)
        stopping = asyncio.create_task(recorder.stop())
        await asyncio.sleep(0.05)
        assert not stopping.done(), "stop() returned while a write was in flight"
        shadow.gate.set()
        await asyncio.wait_for(stopping, 5)
        assert _flushers() == []
    finally:
        shadow.gate.set()
        await shadow.stop()
    assert await rows(shadow.path, "SELECT SUM(offered), SUM(written) FROM shadow_markers") == [(1, 1)]
