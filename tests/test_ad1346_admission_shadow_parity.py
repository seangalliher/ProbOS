"""AD-1346 M3c1 (#1604): parity with each site's own check, over a real ``AdmissionShadowStore`` in ``tmp_path``.

- P1  an offer with today's outcome is counted for parity, and each disagreement is kept as a sample.
- P2  ``is_disagreement`` is true when exactly one of the two outcomes refuses.
- P3  a full disagreement buffer drops the sample, counts it in memory and still counts parity.
- P4  a failed write puts its parity counts and disagreements back, within the buffer, and they are written once.
- P5  the store adds parity counts by UTC day, keeps the newest ``DISAGREEMENT_RING_SIZE`` disagreements, and
      ``prune`` deletes parity days before the retention window.
- P6  a version-1 file with only M3b's three tables opens, keeps its rows and gains the two M3c tables.
- P7  ``shadow`` hands today's outcome to the recorder and counts an unknown one as a failure.
- P8  a logging handler that raises does not escape ``shadow`` (F-212).
- P9  after ``close``, ``shadow`` decides, counts and offers nothing; ``decide`` still answers.
- P10 ``shadow_at`` calls only an exact ``AdmissionService`` and maps ``refused`` to today's outcome.
- P11 a flush that raises leaves the flusher running and is counted as ``flush_errors`` (R1).
- P12 the two report queries answer on a ``mode=ro`` connection.
- P13 the parity key space and the disagreement ring are bounded by named constants.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from probos.admission import AdmissionService, WorkRequest
from probos.admission import recorder as recorder_module
from probos.admission import store as store_module
from probos.admission.recorder import FLUSHER_TASK_NAME, ShadowRecorder, is_disagreement
from probos.admission.report import open_read_only, run_query
from probos.admission.seam import shadow_at
from probos.admission.store import (
    AGGREGATE_RETENTION_DAYS,
    AGGREGATE_ROW_LIMIT,
    DAY_SECONDS,
    DISAGREEMENT_RING_SIZE,
    STORE_FILENAME,
    AdmissionShadowStore,
    ShadowBatch,
    ShadowDisagreement,
    utc_hour,
)
from probos.admission.taxonomy import REASON_CODES, SEAMS, TODAY_OUTCOMES, WORK_KINDS
from probos.agent_stop import AgentStopService
from probos.crew_profile import CallsignRegistry
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.storage.sqlite_factory import default_factory
from probos.substrate.registry import AgentRegistry
from tests.fixtures.ad1346_shadow import T0, admit, refuse, rows

BOOT = "boot-a"
INSTANCE_ID = "ad1346-m3c1-ship"
DAY = "2026-10-28"
KEY = ("intent", "intent", "admit", "would_refuse", "identity_unresolved")
PARITY = (
    "SELECT day, work_kind, seam, today_outcome, outcome, reason_code, decisions FROM shadow_parity "
    "ORDER BY day, today_outcome, outcome"
)
TABLES = "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
#: M3b's three tables (the columns and keys of store.py's _SCHEMA at tree 04d0eb50) and its version row, with one
#: aggregate row.
M3B_FILE = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
INSERT INTO schema_version (version) VALUES (1);
CREATE TABLE shadow_aggregates (
    day TEXT NOT NULL, work_kind TEXT NOT NULL, seam TEXT NOT NULL, outcome TEXT NOT NULL, reason_code TEXT NOT NULL,
    latency_bucket INTEGER NOT NULL, decisions INTEGER NOT NULL,
    PRIMARY KEY (day, work_kind, seam, outcome, reason_code, latency_bucket)
);
CREATE TABLE shadow_samples (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, boot_id TEXT NOT NULL, hour TEXT NOT NULL, recorded_at REAL NOT NULL,
    work_kind TEXT NOT NULL, seam TEXT NOT NULL, outcome TEXT NOT NULL, reason_code TEXT NOT NULL,
    latency_ns INTEGER NOT NULL, verdict_json TEXT NOT NULL
);
CREATE TABLE shadow_markers (
    boot_id TEXT NOT NULL, hour TEXT NOT NULL, offered INTEGER NOT NULL, written INTEGER NOT NULL,
    dropped INTEGER NOT NULL, samples_dropped INTEGER NOT NULL, PRIMARY KEY (boot_id, hour)
);
INSERT INTO shadow_aggregates VALUES ('2026-10-27', 'intent', 'intent', 'admit', 'admitted', 3, 9);
"""


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


class _RaisingHandler(logging.Handler):
    """A handler whose ``emit`` raises, F-212's class."""

    def __init__(self, error: type[Exception]) -> None:
        super().__init__(level=logging.DEBUG)
        self.error = error
        self.calls = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.calls += 1
        raise self.error("INJECTED logging handler failure")


class _Str(str):
    """A ``str`` subclass, which is not an exact ``str``."""


async def _until(check: Callable[[], Awaitable[bool]], timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not await check():
        assert loop.time() < deadline, "the condition did not hold in time"
        await asyncio.sleep(0.01)


def _flushers() -> list[asyncio.Task[Any]]:
    return [task for task in asyncio.all_tasks() if task.get_name() == FLUSHER_TASK_NAME and not task.done()]


def _shadow(gate: AdmissionService, presented_id: str, **extra: Any) -> None:
    values: dict[str, Any] = {
        "work_kind": "intent", "seam": "intent", "origin": "system", "origin_id": "ad1346-m3c1", **extra,
    }
    return gate.shadow(presented_id=presented_id, **values)


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
        await registry.start(instance_id=INSTANCE_ID, vessel_name="Ad1346m3c1", version="1")
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


async def test_an_offer_with_todays_outcome_counts_parity_and_keeps_each_disagreement(store: AdmissionShadowStore) -> None:
    """P1 (kills RC-1, RC-2, RC-3, RC-8, ST-4)."""
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    recorder.offer(admit(), 1, today_outcome="admit")
    recorder.offer(admit(), 1, today_outcome="refuse")
    recorder.offer(refuse(), 1, today_outcome="admit")
    recorder.offer(refuse(), 1, today_outcome="refuse")
    recorder.offer(admit(), 1)
    await recorder.stop()
    assert await rows(store.path, PARITY) == [
        (DAY, "intent", "intent", "admit", "admit", "admitted", 1),
        (DAY, "intent", "intent", "admit", "would_refuse", "identity_unresolved", 1),
        (DAY, "intent", "intent", "refuse", "admit", "admitted", 1),
        (DAY, "intent", "intent", "refuse", "would_refuse", "identity_unresolved", 1),
    ]
    kept = await rows(
        store.path, "SELECT boot_id, today_outcome, outcome, reason_code, verdict_json FROM shadow_disagreements ORDER BY seq",
    )
    assert [row[1:4] for row in kept] == [("refuse", "admit", "admitted"), ("admit", "would_refuse", "identity_unresolved")]
    assert [json.loads(row[4]) for row in kept] == [admit().to_dict(), refuse().to_dict()]
    assert {row[0] for row in kept} == {recorder.boot_id}
    assert await rows(store.path, "SELECT SUM(decisions) FROM shadow_aggregates") == [(5,)]
    assert recorder.counters()["disagreement_samples_dropped"] == 0


@pytest.mark.parametrize(
    ("outcome", "today", "expected"),
    [("admit", "admit", False), ("admit", "refuse", True), ("would_refuse", "admit", True), ("would_refuse", "refuse", False)],
    ids=["admit-admit", "admit-refuse", "refuse-admit", "refuse-refuse"],
)
def test_is_disagreement_is_true_when_exactly_one_outcome_refuses(outcome: str, today: str, expected: bool) -> None:
    """P2 (kills RC-5)."""
    assert is_disagreement(outcome, today) is expected


async def test_a_full_disagreement_buffer_drops_the_sample_and_still_counts_parity(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P3 (kills RC-4)."""
    monkeypatch.setattr(recorder_module, "DISAGREEMENT_BUFFER_LIMIT", 2)
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    for _ in range(3):
        recorder.offer(refuse(), 1, today_outcome="admit")
    await recorder.stop()
    assert await rows(store.path, "SELECT COUNT(*) FROM shadow_disagreements") == [(2,)]
    assert await rows(store.path, "SELECT SUM(decisions) FROM shadow_parity") == [(3,)]
    assert recorder.counters()["disagreement_samples_dropped"] == 1


async def test_a_failed_write_puts_parity_and_disagreements_back_within_the_buffer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P4 (kills RC-6, RC-7)."""
    monkeypatch.setattr(recorder_module, "FLUSH_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(recorder_module, "DISAGREEMENT_BUFFER_LIMIT", 2)
    shadow = _FailingStore(data_dir=tmp_path / "data", failures=1)
    await shadow.start()
    try:
        recorder = ShadowRecorder(shadow, wall_clock=_Clock(T0))
        recorder.offer(refuse(), 1, today_outcome="admit")
        recorder.offer(refuse(), 1, today_outcome="admit")
        shadow.during = lambda: recorder.offer(admit(), 1, today_outcome="refuse")
        recorder.start()

        async def second_attempt() -> bool:
            return shadow.attempts >= 2

        await _until(second_attempt)
        await recorder.stop()
    finally:
        await shadow.stop()
    assert await rows(
        shadow.path,
        "SELECT today_outcome, outcome, SUM(decisions) FROM shadow_parity GROUP BY today_outcome, outcome ORDER BY today_outcome",
    ) == [("admit", "would_refuse", 2), ("refuse", "admit", 1)]
    assert await rows(shadow.path, "SELECT today_outcome FROM shadow_disagreements ORDER BY seq") == [("admit",), ("admit",)]
    counters = recorder.counters()
    assert (counters["flush_failures"], counters["disagreement_samples_dropped"], counters["written"]) == (1, 1, 3)


async def test_the_store_adds_parity_by_day_keeps_the_newest_disagreements_and_prunes_parity(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P5 (kills ST-1, ST-2, ST-3)."""
    monkeypatch.setattr(store_module, "DISAGREEMENT_RING_SIZE", 2)
    hour, old = utc_hour(T0), utc_hour(T0 - AGGREGATE_RETENTION_DAYS * DAY_SECONDS)
    items = [ShadowDisagreement(hour, T0 + n, refuse(), 7, "admit") for n in range(3)]
    await store.write_batch(BOOT, ShadowBatch({}, [], {}, {}, {}, parity={(old, *KEY): 4, (hour, *KEY): 2}, disagreements=items))
    await store.write_batch(BOOT, ShadowBatch({}, [], {}, {}, {}, parity={(hour, *KEY): 1}))
    assert await rows(store.path, PARITY) == [(old[:10], *KEY, 4), (DAY, *KEY, 3)]
    assert await rows(store.path, "SELECT recorded_at, latency_ns FROM shadow_disagreements ORDER BY seq") == [
        (T0 + 1, 7), (T0 + 2, 7),
    ]
    assert await store.prune(T0) == (0, 0), "the counts prune returns leave the parity rows out"
    assert await rows(store.path, PARITY) == [(DAY, *KEY, 3)]


async def test_a_version_1_file_with_m3bs_three_tables_opens_keeps_its_rows_and_gains_two(tmp_path: Path) -> None:
    """P6: D58's compatibility path (kills ST-5)."""
    path = tmp_path / "data" / STORE_FILENAME
    path.parent.mkdir(parents=True)
    db = await default_factory.connect(str(path))
    try:
        await db.executescript(M3B_FILE)
        await db.commit()
    finally:
        await db.close()
    assert await rows(path, TABLES) == [("schema_version",), ("shadow_aggregates",), ("shadow_markers",), ("shadow_samples",)]
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    await shadow.stop()
    assert await rows(path, TABLES) == [
        ("schema_version",), ("shadow_aggregates",), ("shadow_disagreements",), ("shadow_markers",),
        ("shadow_parity",), ("shadow_samples",),
    ]
    assert await rows(path, "SELECT version FROM schema_version") == [(1,)]
    assert await rows(path, "SELECT * FROM shadow_aggregates") == [("2026-10-27", "intent", "intent", "admit", "admitted", 3, 9)]


async def test_shadow_hands_todays_outcome_to_the_recorder_and_counts_an_unknown_one_as_a_failure(
    identities: IdentityService, stops: AgentStopService, store: AdmissionShadowStore,
) -> None:
    """P7 (kills SV-3, SV-4)."""
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    gate = AdmissionService(identities, stops, recorder=recorder)
    assert _shadow(gate, "system:ship_computer", today_outcome="refuse") is None
    assert _shadow(gate, "nobody", today_outcome="refuse") is None
    assert _shadow(gate, "nobody") is None
    assert gate.failures == 0
    for unknown in ("maybe", _Str("admit"), 1):
        assert _shadow(gate, "nobody", today_outcome=unknown) is None
    assert gate.failures == 3 and recorder.counters()["offered"] == 3
    await recorder.stop()
    assert await rows(store.path, PARITY) == [
        (DAY, "intent", "intent", "refuse", "admit", "admitted", 1),
        (DAY, "intent", "intent", "refuse", "would_refuse", "identity_unresolved", 1),
    ]
    assert await rows(store.path, "SELECT today_outcome, outcome FROM shadow_disagreements") == [("refuse", "admit")]


@pytest.mark.parametrize("error", [RuntimeError, RecursionError], ids=["runtime-error", "recursion-error"])
async def test_a_logging_handler_that_raises_does_not_escape_shadow(
    identities: IdentityService, stops: AgentStopService, caplog: pytest.LogCaptureFixture, error: type[Exception],
) -> None:
    """P8: F-212 decided for ``shadow`` (D59) (kills SV-5)."""
    caplog.set_level(logging.DEBUG, logger="probos.admission.service")
    handler = _RaisingHandler(error)
    log = logging.getLogger("probos.admission.service")
    log.addHandler(handler)
    try:
        gate = AdmissionService(identities, stops)
        assert _shadow(gate, "nobody", seam="subprocess") is None
        assert _shadow(gate, "nobody", seam="subprocess") is None
    finally:
        log.removeHandler(handler)
    assert gate.failures == 2 and handler.calls == 2


async def test_after_close_shadow_decides_counts_and_offers_nothing(
    identities: IdentityService, stops: AgentStopService, store: AdmissionShadowStore,
) -> None:
    """P9 (kills SV-1, SV-2)."""
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    gate = AdmissionService(identities, stops, recorder=recorder)
    assert vars(gate)["_closed"] is False
    assert _shadow(gate, "nobody") is None
    gate.close()
    gate.close()
    assert vars(gate)["_closed"] is True
    assert _shadow(gate, "nobody", today_outcome="admit") is None
    assert _shadow(gate, "nobody", seam="subprocess") is None
    assert gate.tally() == {("intent", "intent", "identity_unresolved"): 1} and gate.failures == 0
    assert recorder.counters()["offered"] == 1
    assert gate.decide(WorkRequest("nobody", "intent", "intent", "system", "ad1346-m3c1")).outcome == "would_refuse"
    await recorder.stop()


async def test_shadow_at_calls_only_an_exact_admission_service_and_maps_refused(
    identities: IdentityService, stops: AgentStopService, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P10 (kills SM-1, SM-2)."""
    assert list(inspect.signature(shadow_at).parameters) == [
        "service", "presented_id", "work_kind", "seam", "origin", "origin_id", "refused",
    ]
    spec = MagicMock(spec=AdmissionService)
    for service in (None, object(), spec):
        assert shadow_at(
            service, presented_id="x", work_kind="intent", seam="intent", origin="system", origin_id="t", refused=True,
        ) is None
    assert spec.shadow.call_count == 0
    calls: list[dict[str, Any]] = []
    gate = AdmissionService(identities, stops)
    monkeypatch.setattr(gate, "shadow", lambda **kwargs: calls.append(kwargs))
    for refused in (True, False, 1):
        assert shadow_at(
            gate, presented_id="x", work_kind="intent", seam="intent", origin="system", origin_id="t", refused=refused,
        ) is None
    assert [call["today_outcome"] for call in calls] == ["refuse", "admit", "admit"]
    assert calls[0] == {
        "presented_id": "x", "work_kind": "intent", "seam": "intent", "origin": "system", "origin_id": "t",
        "today_outcome": "refuse",
    }


async def test_a_flush_that_raises_leaves_the_flusher_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """P11: R1 decided (D59): a write fails and its warning's handler raises; the flusher counts it and writes next time (kills RC-9)."""
    monkeypatch.setattr(recorder_module, "FLUSH_INTERVAL_SECONDS", 0.01)
    caplog.set_level(logging.DEBUG, logger="probos.admission.recorder")
    handler = _RaisingHandler(RuntimeError)
    log = logging.getLogger("probos.admission.recorder")
    shadow = _FailingStore(data_dir=tmp_path / "data", failures=1)
    await shadow.start()
    log.addHandler(handler)
    try:
        recorder = ShadowRecorder(shadow, wall_clock=_Clock(T0))
        recorder.offer(admit(), 1, today_outcome="admit")
        recorder.start()

        async def written() -> bool:
            return await rows(shadow.path, "SELECT SUM(offered), SUM(written) FROM shadow_markers") == [(1, 1)]

        await _until(written)
        assert recorder.counters()["flush_errors"] == 1 and handler.calls >= 1
        assert len(_flushers()) == 1, "the flusher is still running"
        await recorder.stop()
    finally:
        log.removeHandler(handler)
        await shadow.stop()
    assert _flushers() == []


async def test_the_parity_queries_answer_on_a_read_only_connection(tmp_path: Path) -> None:
    """P12 (kills RP-1)."""
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    try:
        hour = utc_hour(T0)
        await shadow.write_batch(BOOT, ShadowBatch(
            {}, [], {}, {}, {},
            parity={(hour, "tool_call", "tool", "refuse", "admit", "admitted"): 2},
            disagreements=[ShadowDisagreement(hour, T0, admit(work_kind="tool_call", seam="tool"), 9, "refuse")],
        ))
    finally:
        await shadow.stop()
    db = await open_read_only(tmp_path / "data" / STORE_FILENAME)
    try:
        assert await run_query(db, "parity_by_work_kind", (DAY,)) == [("tool_call", "tool", "refuse", "admit", "admitted", 2)]
        assert await run_query(db, "parity_by_work_kind", ("2026-10-29",)) == []
        newest = await run_query(db, "disagreement_samples", (1,))
        assert [row[3:9] for row in newest] == [("tool_call", "tool", "refuse", "admit", "admitted", 9)]
    finally:
        await db.close()


def test_the_parity_key_space_and_the_disagreement_ring_are_bounded() -> None:
    """P13: D58's bounds."""
    assert TODAY_OUTCOMES == ("admit", "refuse")
    assert DISAGREEMENT_RING_SIZE == 1_000 and recorder_module.DISAGREEMENT_BUFFER_LIMIT == DISAGREEMENT_RING_SIZE
    one_day = len(WORK_KINDS) * len(SEAMS) * len(TODAY_OUTCOMES) * len(REASON_CODES)
    assert one_day * AGGREGATE_RETENTION_DAYS < AGGREGATE_ROW_LIMIT, one_day
    assert recorder_module.COUNTER_NAMES[-2:] == ("disagreement_samples_dropped", "flush_errors")
