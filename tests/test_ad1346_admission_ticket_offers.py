"""AD-1346 M3d3b2 (#1604): the recorder's offers, the work ticket's findings written to ``admission_shadow.db``.

``AdmissionService.hold`` offers the finding of each issue the registry answers, and ``AdmissionService._check_ticket``
the finding of each sink check, to ``ShadowRecorder.offer_ticket``; the recorder writes them behind, in the
transaction of its verdicts. Every case but TO3 builds a real ``AdmissionShadowStore`` under ``tmp_path``, and the cases
that read one back do so with SQL or with the report's queries on a ``mode=ro`` connection.

- TO1  ``offer_ticket`` counts each finding by UTC day, operation, code, work kind and ``off_loop``, keeps no sample of
       ``ticket_issued`` or ``ticket_live``, keeps a ``ticket_missing`` sample in the missing ring and the others in
       ``ticket_samples``, each as ``persisted_finding`` JSON; the marker row counts five
       offered and five written. With no room in the sample buffer, one finding of each code drops a sample for every
       code but those two and ``ticket_missing``, and a finding of each work kind in ``WORK_KINDS`` and of the empty
       one is counted.
- TO2  it raises ``TypeError`` for an object that is not a ``TicketFinding``, for an instance of a subclass of it and
       for an ``off_loop`` of 1, and
       ``ValueError`` for an unknown work kind and for a ``str`` subclass operation, code or work kind, and counts and
       keeps none of them.
- TO3  ``offer_ticket`` is a plain function: no await, and none of the store, task, wait or I/O names R2 forbids
       ``offer`` to call.
- TO4  beyond ``PENDING_KEY_LIMIT`` pending keys a new key is dropped, counted and not sampled; each ring's buffer
       keeps its own limit and counts its overflow; an offer after ``stop`` began is counted as late and not written.
- TO5  a work-ticket part whose write raises (a hand-built finding whose ``ticket_id`` is None) is written again at once
       with its finding counts and the samples of both buffers counted as dropped in the work-ticket markers, beside the
       dropped counts it already held, and the verdicts are written by that second write; a part of counts only whose
       first write fails and whose second commits is written as dropped too (register R59), and so is a part whose two
       samples, one in each buffer, fall in two hours that held no dropped count, each counted once in its own hour.
- TO6  a batch whose two writes raise is put back whole, its own samples kept first within the two buffers, and written
       by the next flush; the marker rows of its two hours then hold every offer, the restored dropped counts and every
       overflow, each under the hour of its offer.
- TO7  ``stop`` logs each of the four failed writes and then a warning whose arguments count the verdicts, samples,
       work-ticket findings and work-ticket samples it could not write, four different counts in that order; a batch
       put back within both buffers counts no sample as dropped.
- TO8  the service offers the finding of each issue (a refused one included) and of each sink check, with
       ``off_loop`` for the check handed to its loop, each on the loop's thread.
- TO9  an offer that raises is one counted failure: ``hold`` returns ``NO_HOLD`` with the carrier as it was and the
       issued entry registered, and each sink check whose offer raises counts one failure more, a handed-over one after
       its off-loop count.
- TO10 #1604 property 5, persisted: in the real run entry, after a Captain's stop on the delegating agent, the next
       model and tool calls of its delegated child and then its own count ``ticket_revoked``; after ``stop`` the report
       shows them by operation, their samples with digested ids and the stop's id, and the markers offered equal to
       written.
- TO11 the wiring: on a boot whose LLM client is an ``OpenAICompatibleClient``, after one model call and
       ``runtime.stop()``, the store holds a ``model_call`` ``ticket_missing`` count and the boot's marker row has
       offered equal to written and no finding dropped.
- TO12 ``COUNTER_NAMES`` appends the five ``ticket_`` totals, the two buffer limits are the ring sizes, and ``start``
       marks the boot's hour in the work-ticket markers.

TO8 and TO9 each run one sink check on a worker thread (``asyncio.to_thread``). TO11 boots a ``ProbOSRuntime`` with
``SystemConfig()`` and the naming ceremony, the proactive loop and QA turned off, and with a gateway that starts no
health probe and answers each request with a canned response in place of sending it, as
``tests/test_ad1346_admission_ticket_sinks.py`` does.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from probos.admission import AdmissionService
from probos.admission import recorder as recorder_module
from probos.admission import tickets as tickets_module
from probos.admission.carrier import CURRENT_TICKET, NO_HOLD
from probos.admission.recorder import COUNTER_NAMES, ShadowRecorder
from probos.admission.report import open_read_only, run_query
from probos.admission.store import (
    STORE_FILENAME,
    TICKET_MISSING_RING_SIZE,
    TICKET_SAMPLE_RING_SIZE,
    AdmissionShadowStore,
    ShadowBatch,
    persisted_finding,
    ticket_digest,
    utc_hour,
)
from probos.admission.taxonomy import SEAM_MODEL_CALL, TICKET_REASON_CODES, WORK_KINDS
from probos.admission.tickets import TicketFinding, TicketRegistry
from probos.agent_stop import SEAM_INTENT, SEAM_TOOL, AgentStopService
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.runtime import ProbOSRuntime
from probos.substrate.registry import AgentRegistry
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse
from tests.fixtures.ad1343_seam_census import function
from tests.fixtures.ad1346_shadow import HOUR, T0, admit, refuse, rows

INSTANCE_ID = "ad1346-m3d3b2-ship"
VESSEL_NAME = "Ad1346m3d3b2"
AGENT_A = "ad1346-m3d3b2-agent-a"
AGENT_B = "ad1346-m3d3b2-agent-b"
RAW_ID = "0123456789abcdef" * 2  # the form of an id the registry issues
DAY = "2026-10-28"  # the UTC day of T0
_ABSENT = "ad1346_m3d3b2_absent"  # a tool id no registry holds: the tool sink answers "not found" and runs nothing
FINDINGS = (
    "SELECT day, operation, code, work_kind, off_loop, findings FROM ticket_findings "
    "ORDER BY operation, code, work_kind, off_loop"
)
MARKERS = "SELECT boot_id, hour, offered, written, dropped, samples_dropped FROM ticket_markers ORDER BY hour"


class _Clock:
    """An injected wall clock that only the test moves."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Kind(str):
    """A ``str`` subclass: it equals and hashes as the ``str`` it is built from, and it is not an exact ``str``."""

    __slots__ = ()


class _SubFinding(TicketFinding):
    """A ``TicketFinding`` subclass: it holds every field of one, and it is not an exact ``TicketFinding``."""

    __slots__ = ()


class _FailingStore(AdmissionShadowStore):
    """A real store whose first ``failures`` writes raise; the first of them calls ``during``, when it is set, before it
    raises."""

    def __init__(self, *, data_dir: Path, failures: int) -> None:
        super().__init__(data_dir=data_dir)
        self.failures = failures
        self.during: Callable[[], None] | None = None
        self.attempts = 0

    async def write_batch(self, boot_id: str, batch: ShadowBatch) -> int:
        self.attempts += 1
        if self.attempts <= self.failures:
            during, self.during = self.during, None
            if during is not None:
                during()
            raise OSError("INJECTED ticket record write failure")
        return await super().write_batch(boot_id, batch)


class _ThreadRecordingRecorder(ShadowRecorder):
    """A recorder that records the thread each ``offer_ticket`` runs on."""

    def __init__(self, store: AdmissionShadowStore, **kwargs: Any) -> None:
        super().__init__(store, **kwargs)
        self.threads: list[int] = []

    def offer_ticket(self, finding: TicketFinding, *, off_loop: bool) -> None:
        self.threads.append(threading.get_ident())
        super().offer_ticket(finding, off_loop=off_loop)


class _RaisingTicketRecorder(ShadowRecorder):
    """A recorder whose ``offer_ticket`` raises."""

    def offer_ticket(self, finding: TicketFinding, *, off_loop: bool) -> None:
        raise RuntimeError("INJECTED ticket offer failure")


class _OfflineGateway(OpenAICompatibleClient):
    """The model gateway with no endpoint: it starts no health probe and answers with a canned response where it would
    send the request."""

    async def start_health_probe(self, interval_seconds: float = 30.0, emit_fn: Any = None) -> None:
        return None

    async def _complete_inner(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content="ad1346-m3d3b2", model="m", tier="standard")


class _ScriptedRun(WorkItemAgenticExecutor):
    """The real run entry (its stop check, shadow statement and hold) over a scripted body in place of the agentic loop."""

    def __init__(self, bodies: dict[str, Callable[[dict[str, Any]], Awaitable[str]]]) -> None:
        super().__init__(llm_client=None)
        self.bodies = bodies

    async def _run_reserved(self, **arguments: Any) -> Any:
        return await self.bodies[arguments["agent_id"]](arguments)


def _issued() -> TicketFinding:
    return TicketFinding(
        "issue", "ticket_issued", f"Ticket {RAW_ID} issued to {AGENT_A} for intent at intent, depth 0.",
        ticket_id=RAW_ID, principal_key=AGENT_A, work_kind="intent",
    )


def _live() -> TicketFinding:
    return TicketFinding(
        SEAM_TOOL, "ticket_live", f"Ticket {RAW_ID} of {AGENT_A} is live at tool.", ticket_id=RAW_ID,
        principal_key=AGENT_A, work_kind="intent",
    )


def _revoked() -> TicketFinding:
    return TicketFinding(
        SEAM_TOOL, "ticket_revoked",
        f"Ticket {RAW_ID} is revoked: its principal or an ancestor's is under the Captain's stop s.",
        ticket_id=RAW_ID, principal_key=AGENT_A, work_kind="agentic_run", stop_id="s",
    )


def _expired() -> TicketFinding:
    return TicketFinding(
        SEAM_TOOL, "ticket_expired", f"Ticket {RAW_ID} ended: it expired, or was released when its work ended.",
        ticket_id=RAW_ID, principal_key=AGENT_A, work_kind="agentic_run",
    )


def _missing() -> TicketFinding:
    return TicketFinding(SEAM_MODEL_CALL, "ticket_missing", "No ticket was presented at model_call.", presented_key=AGENT_A)


def _unknown() -> TicketFinding:
    return TicketFinding(SEAM_TOOL, "ticket_unknown", "The presented object is not a ticket the registry holds.")


async def _settle() -> None:
    """Let the loop run the checks a sink elsewhere handed to it."""
    for _ in range(3):
        await asyncio.sleep(0)


async def _until(check: Callable[[], Awaitable[bool]], timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not await check():
        assert loop.time() < deadline, "the condition did not hold in time"
        await asyncio.sleep(0.01)


def _tools(stops: AgentStopService, service: AdmissionService) -> ToolRegistry:
    registry = ToolRegistry()
    registry.set_stop_gate(stops)
    registry.set_admission(service)
    return registry


def _gateway(service: AdmissionService) -> _OfflineGateway:
    client = _OfflineGateway()
    client.set_admission(service)
    return client


async def _run(runner: _ScriptedRun, runtime: SimpleNamespace, agent_id: str, extra: dict[str, Any] | None = None) -> Any:
    """The real run entry: its stop check, shadow statement and hold, then the scripted body under the hold."""
    return await runner.run(agent_id=agent_id, instructions="i", task_text="t", runtime=runtime, extra_context=extra)


def _config() -> SystemConfig:
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    config.admission.shadow_enabled = True
    return config


@pytest_asyncio.fixture
async def identities(tmp_path: Path) -> AsyncIterator[IdentityService]:
    """The real facade over a started identity registry and a ``CallsignRegistry`` bound to an empty ``AgentRegistry``."""
    registry = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await registry.start()
        await registry.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        callsigns = CallsignRegistry()
        callsigns.bind_registry(AgentRegistry())
        yield IdentityService(registry, callsigns)
    finally:
        await registry.stop()


@pytest_asyncio.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    """A real Captain's stop record."""
    record = AgentStopService(data_dir=tmp_path / "stops")
    await record.start()
    try:
        yield record
    finally:
        await record.stop()


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[AdmissionShadowStore]:
    shadow = AdmissionShadowStore(data_dir=tmp_path / "data")
    await shadow.start()
    try:
        yield shadow
    finally:
        await shadow.stop()


@pytest.fixture
def tickets(stops: AgentStopService) -> TicketRegistry:
    """A production-shaped registry at the default delegation depth of 1, on a clock that does not move."""
    return TicketRegistry(stops, max_depth=1, clock=lambda: 1_000.0)


async def test_offer_ticket_counts_every_finding_and_samples_all_but_issued_and_live_in_two_rings(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TO1 (kills OX-5, OX-7, OX-8, OX-9, OX-11, OX-14, OX-15, OX-18, OX-19, OX-20, OX-23, OX-40, OX-43, OX-44); then
    one finding of each code and of each work kind, with no room in the sample buffer."""
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    revoked, missing, unknown = _revoked(), _missing(), _unknown()
    recorder.offer_ticket(_issued(), off_loop=False)
    recorder.offer_ticket(_live(), off_loop=False)
    recorder.offer_ticket(revoked, off_loop=False)
    recorder.offer_ticket(missing, off_loop=True)
    recorder.offer_ticket(unknown, off_loop=False)
    await recorder.stop()
    assert await rows(store.path, FINDINGS) == [
        (DAY, "issue", "ticket_issued", "intent", 0, 1),
        (DAY, "model_call", "ticket_missing", "", 1, 1),
        (DAY, "tool", "ticket_live", "intent", 0, 1),
        (DAY, "tool", "ticket_revoked", "agentic_run", 0, 1),
        (DAY, "tool", "ticket_unknown", "", 0, 1),
    ]
    ring = "SELECT code, off_loop, recorded_at, finding_json FROM {} ORDER BY seq"
    kept = await rows(store.path, ring.format("ticket_samples"))
    assert [(code, off_loop, at, json.loads(text)) for code, off_loop, at, text in kept] == [
        ("ticket_revoked", 0, T0, persisted_finding(revoked)), ("ticket_unknown", 0, T0, persisted_finding(unknown)),
    ]
    held = await rows(store.path, ring.format("ticket_missing_samples"))
    assert [(code, off_loop, at, json.loads(text)) for code, off_loop, at, text in held] == [
        ("ticket_missing", 1, T0, persisted_finding(missing)),
    ]
    assert await rows(store.path, MARKERS) == [(recorder.boot_id, utc_hour(T0), 5, 5, 0, 0)]
    assert recorder.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {"ticket_offered": 5, "ticket_written": 5}
    monkeypatch.setattr(recorder_module, "TICKET_SAMPLE_BUFFER_LIMIT", 0)
    every = ShadowRecorder(store, wall_clock=_Clock(T0))  # never started: it holds no task and writes nothing
    for code in TICKET_REASON_CODES:
        every.offer_ticket(TicketFinding(SEAM_TOOL, code, "c"), off_loop=False)
    for work_kind in (*WORK_KINDS, ""):
        every.offer_ticket(TicketFinding(SEAM_TOOL, "ticket_live", "c", work_kind=work_kind), off_loop=False)
    assert every.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "ticket_offered": len(TICKET_REASON_CODES) + len(WORK_KINDS) + 1,
        "ticket_samples_dropped": len(TICKET_REASON_CODES) - 3,
    }, "every code but ticket_issued, ticket_live and ticket_missing offers a sample to the buffer of 0"


async def test_offer_ticket_refuses_a_finding_it_cannot_bound_and_keeps_nothing_of_it(store: AdmissionShadowStore) -> None:
    """TO2 (kills OX-2, OX-3, OX-4): register R53's checks, made before anything is counted."""
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    with pytest.raises(TypeError, match="TicketFinding"):
        recorder.offer_ticket(object(), off_loop=False)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="bool"):
        recorder.offer_ticket(_missing(), off_loop=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="TicketFinding"):
        recorder.offer_ticket(_SubFinding(SEAM_TOOL, "ticket_live", "c", work_kind="intent"), off_loop=False)
    with pytest.raises(ValueError, match="WORK_KINDS"):
        recorder.offer_ticket(TicketFinding(SEAM_TOOL, "ticket_live", "c", work_kind="not_a_work_kind"), off_loop=False)
    for subclassed in (
        TicketFinding(_Kind(SEAM_TOOL), "ticket_live", "c", work_kind="intent"),
        TicketFinding(SEAM_TOOL, _Kind("ticket_live"), "c", work_kind="intent"),
        TicketFinding(SEAM_TOOL, "ticket_live", "c", work_kind=_Kind("intent")),
    ):
        with pytest.raises(ValueError, match="WORK_KINDS"):
            recorder.offer_ticket(subclassed, off_loop=False)
    await recorder.stop()
    assert recorder.counters() == dict.fromkeys(COUNTER_NAMES, 0)
    assert await rows(
        store.path,
        "SELECT (SELECT COUNT(*) FROM ticket_findings), (SELECT COUNT(*) FROM ticket_samples), "
        "(SELECT COUNT(*) FROM ticket_missing_samples), (SELECT COUNT(*) FROM ticket_markers)",
    ) == [(0, 0, 0, 0)]


def test_offer_ticket_awaits_nothing_and_calls_no_store_task_wait_or_io_name() -> None:
    """TO3: #1601's bottleneck rule on the hot path, as R2 holds ``offer`` to it."""
    node = function("src/probos/admission/recorder.py", "ShadowRecorder.offer_ticket")
    assert isinstance(node, ast.FunctionDef), "offer_ticket must not be a coroutine"
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


async def test_the_key_limit_and_each_ring_buffer_drop_and_count_and_a_late_offer_is_counted_in_memory(
    store: AdmissionShadowStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TO4 (kills OX-1, OX-6, OX-10, OX-12, OX-13, OX-16)."""
    monkeypatch.setattr(recorder_module, "PENDING_KEY_LIMIT", 3)
    monkeypatch.setattr(recorder_module, "TICKET_MISSING_BUFFER_LIMIT", 1)
    monkeypatch.setattr(recorder_module, "TICKET_SAMPLE_BUFFER_LIMIT", 2)
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    # keys: missing (1), revoked (2), unknown (3, its sample beyond the buffer of 2), expired (a fourth key: dropped)
    for finding in (_missing(), _missing(), _revoked(), _revoked(), _unknown(), _expired()):
        recorder.offer_ticket(finding, off_loop=False)
    await recorder.stop()
    recorder.offer_ticket(_revoked(), off_loop=False)
    await recorder.stop()
    assert await rows(store.path, FINDINGS) == [
        (DAY, "model_call", "ticket_missing", "", 0, 2),
        (DAY, "tool", "ticket_revoked", "agentic_run", 0, 2),
        (DAY, "tool", "ticket_unknown", "", 0, 1),
    ]
    assert await rows(store.path, "SELECT code FROM ticket_samples ORDER BY seq") == [("ticket_revoked",), ("ticket_revoked",)]
    assert await rows(store.path, "SELECT code FROM ticket_missing_samples ORDER BY seq") == [("ticket_missing",)]
    assert await rows(store.path, MARKERS) == [(recorder.boot_id, utc_hour(T0), 6, 5, 1, 2)]
    assert recorder.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "ticket_offered": 6, "ticket_written": 5, "ticket_dropped": 1, "ticket_samples_dropped": 2, "ticket_late": 1,
    }


async def test_a_ticket_part_whose_write_raises_is_counted_as_dropped_and_the_verdicts_are_written(
    store: AdmissionShadowStore, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TO5 (kills OX-21, OX-22, OX-24, OX-25, OX-26, OX-37, OX-38, OX-39, OX-50, OX-51, OX-52): D150, first with a
    cause the store meets, on a part that also holds two dropped keys, a sample dropped at its offer and a
    ``ticket_missing`` sample; then with a cause that clears before the second write, on a part of counts only (register
    R59), and on a part whose two samples, one in each buffer, fall in two hours that held no dropped count."""
    caplog.set_level(logging.DEBUG, logger="probos.admission.recorder")
    monkeypatch.setattr(recorder_module, "PENDING_KEY_LIMIT", 3)
    monkeypatch.setattr(recorder_module, "TICKET_SAMPLE_BUFFER_LIMIT", 1)
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    poisoned = TicketFinding(SEAM_TOOL, "ticket_unknown", "c", ticket_id=None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        persisted_finding(poisoned)  # premise: the ring row of this sample cannot be built
    recorder.offer(refuse(), 1)
    # keys: issued (1), unknown (2: the poisoned sample kept, the next unknown's beyond the buffer of 1) and missing
    # (3, its sample in the missing buffer); expired and live need a fourth and a fifth key: dropped (two, against the
    # one sample dropped at its offer)
    for finding in (_issued(), poisoned, _unknown(), _missing(), _expired(), _live()):
        recorder.offer_ticket(finding, off_loop=False)
    await recorder.stop()
    assert await rows(store.path, "SELECT outcome, decisions FROM shadow_aggregates") == [("would_refuse", 1)]
    assert await rows(store.path, "SELECT SUM(offered), SUM(written) FROM shadow_markers") == [(1, 1)]
    assert await rows(
        store.path,
        "SELECT (SELECT COUNT(*) FROM ticket_findings), (SELECT COUNT(*) FROM ticket_samples), "
        "(SELECT COUNT(*) FROM ticket_missing_samples)",
    ) == [(0, 0, 0)]
    assert await rows(store.path, MARKERS) == [(recorder.boot_id, utc_hour(T0), 6, 0, 6, 3)]
    assert recorder.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "offered": 1, "written": 1, "flush_failures": 1, "ticket_offered": 6, "ticket_dropped": 6,
        "ticket_samples_dropped": 3,
    }
    records = [r for r in caplog.records if r.name == "probos.admission.recorder"]
    assert [r.levelno for r in records] == [logging.WARNING]
    shadow = _FailingStore(data_dir=tmp_path / "transient", failures=1)
    await shadow.start()
    try:
        transient = ShadowRecorder(shadow, wall_clock=_Clock(T0))
        transient.offer_ticket(_issued(), off_loop=False)
        await transient.stop()
    finally:
        await shadow.stop()
    assert shadow.attempts == 2
    assert await rows(shadow.path, "SELECT COUNT(*) FROM ticket_findings") == [(0,)]
    assert await rows(shadow.path, MARKERS) == [(transient.boot_id, utc_hour(T0), 1, 0, 1, 0)]
    assert transient.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "flush_failures": 1, "ticket_offered": 1, "ticket_dropped": 1,
    }
    rewritten_store = _FailingStore(data_dir=tmp_path / "rewritten", failures=1)
    await rewritten_store.start()
    try:
        clock = _Clock(T0)
        rewritten = ShadowRecorder(rewritten_store, wall_clock=clock)
        rewritten.offer_ticket(_revoked(), off_loop=False)
        clock.now = T0 + HOUR
        rewritten.offer_ticket(_missing(), off_loop=False)
        await rewritten.stop()
    finally:
        await rewritten_store.stop()
    assert rewritten_store.attempts == 2
    assert await rows(
        rewritten_store.path,
        "SELECT (SELECT COUNT(*) FROM ticket_findings), (SELECT COUNT(*) FROM ticket_samples), "
        "(SELECT COUNT(*) FROM ticket_missing_samples)",
    ) == [(0, 0, 0)]
    assert await rows(rewritten_store.path, MARKERS) == [
        (rewritten.boot_id, utc_hour(T0), 1, 0, 1, 1), (rewritten.boot_id, utc_hour(T0 + HOUR), 1, 0, 1, 1),
    ], "each rewritten sample adds one in its own hour, which held no dropped count"
    assert rewritten.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "flush_failures": 1, "ticket_offered": 2, "ticket_dropped": 2, "ticket_samples_dropped": 2,
    }


async def test_a_batch_whose_two_writes_raise_is_put_back_whole_within_the_ticket_buffers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TO6 (kills OX-27 to OX-36): the batch of the first flush, with two dropped keys and a dropped sample, fails
    twice; offers made in the next hour while its first write is in flight overflow both buffers, by two and by one,
    when it is put back, and the batch's own samples are the ones kept."""
    monkeypatch.setattr(recorder_module, "FLUSH_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(recorder_module, "PENDING_KEY_LIMIT", 2)
    monkeypatch.setattr(recorder_module, "TICKET_SAMPLE_BUFFER_LIMIT", 2)
    monkeypatch.setattr(recorder_module, "TICKET_MISSING_BUFFER_LIMIT", 1)
    shadow = _FailingStore(data_dir=tmp_path / "data", failures=2)
    await shadow.start()
    try:
        clock = _Clock(T0)
        recorder = ShadowRecorder(shadow, wall_clock=clock)

        other_missing = TicketFinding(
            SEAM_MODEL_CALL, "ticket_missing", "No ticket was presented at model_call.", presented_key=AGENT_B,
        )

        def during() -> None:  # next hour: two samples of a new key, and a missing sample told apart from the batch's
            clock.now = T0 + HOUR
            recorder.offer_ticket(_expired(), off_loop=False)
            recorder.offer_ticket(_expired(), off_loop=False)
            recorder.offer_ticket(other_missing, off_loop=False)

        shadow.during = during
        recorder.start()
        # three revoked (the third beyond the sample buffer), one missing, one unknown and one live (a third and a
        # fourth key: dropped)
        for finding in (_revoked(), _revoked(), _revoked(), _missing(), _unknown(), _live()):
            recorder.offer_ticket(finding, off_loop=False)

        async def written_after_the_failures() -> bool:
            return shadow.attempts >= 3

        await _until(written_after_the_failures)
        await recorder.stop()
    finally:
        await shadow.stop()
    assert shadow.attempts == 3
    assert await rows(shadow.path, FINDINGS) == [
        (DAY, "model_call", "ticket_missing", "", 0, 2), (DAY, "tool", "ticket_expired", "agentic_run", 0, 2),
        (DAY, "tool", "ticket_revoked", "agentic_run", 0, 3),
    ]
    assert await rows(shadow.path, "SELECT code FROM ticket_samples ORDER BY seq") == [("ticket_revoked",)] * 2
    held = await rows(shadow.path, "SELECT finding_json FROM ticket_missing_samples")
    assert [json.loads(text) for (text,) in held] == [persisted_finding(_missing())]
    assert await rows(shadow.path, MARKERS) == [
        (recorder.boot_id, utc_hour(T0), 6, 4, 2, 1), (recorder.boot_id, utc_hour(T0 + HOUR), 3, 3, 0, 3),
    ]
    assert recorder.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "flush_failures": 2, "ticket_offered": 9, "ticket_written": 7, "ticket_dropped": 2, "ticket_samples_dropped": 4,
    }


async def test_stop_logs_each_failed_write_and_the_counts_it_could_not_write(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """TO7 (kills OX-41, OX-42): two flushes of two writes each, every one of them raising; each batch they put back is
    within both work-ticket buffers."""
    caplog.set_level(logging.DEBUG, logger="probos.admission.recorder")
    shadow = _FailingStore(data_dir=tmp_path / "data", failures=10)
    await shadow.start()
    try:
        recorder = ShadowRecorder(shadow, wall_clock=_Clock(T0))
        recorder.offer(refuse(), 1)
        recorder.offer(admit(), 1)
        # four findings under three keys, and three samples in two buffers: the warning's four counts differ
        for finding in (_missing(), _missing(), _unknown(), _issued()):
            recorder.offer_ticket(finding, off_loop=False)
        await recorder.stop()
    finally:
        await shadow.stop()
    assert shadow.attempts == 4
    records = [r for r in caplog.records if r.name == "probos.admission.recorder"]
    assert [r.levelno for r in records] == [logging.WARNING, logging.DEBUG, logging.DEBUG, logging.DEBUG, logging.WARNING]
    assert records[-1].args == (2, 1, 4, 3)
    assert recorder.counters() == dict.fromkeys(COUNTER_NAMES, 0) | {
        "offered": 2, "flush_failures": 4, "ticket_offered": 4,
    }, "each put-back batch is within both buffers: nothing is counted as dropped"
    assert await rows(shadow.path, "SELECT COUNT(*) FROM ticket_markers") == [(0,)]


async def test_the_service_offers_each_issue_and_sink_finding_on_the_thread_of_its_check(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, store: AdmissionShadowStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TO8 (kills OX-48, OX-49): D152's two offer points; the model call is checked on a worker thread and handed to the
    service's loop."""
    recorder = _ThreadRecordingRecorder(store, wall_clock=_Clock(T0))
    service = AdmissionService(identities, stops, recorder=recorder, tickets=tickets, loop=asyncio.get_running_loop())
    hold = service.hold(presented_id=AGENT_A, work_kind="intent", seam=SEAM_INTENT, child=False)
    try:
        assert CURRENT_TICKET.get() is not None, "premise: the hold carried its ticket"
        service.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A)
        await asyncio.to_thread(service.check_ticket, effect=SEAM_MODEL_CALL, presented_id=None)
        await _settle()
    finally:
        hold.end()
    monkeypatch.setattr(tickets_module, "MAX_TICKETS", 0)
    service.hold(presented_id=AGENT_A, work_kind="intent", seam=SEAM_INTENT, child=False).end()
    await recorder.stop()
    assert await rows(store.path, FINDINGS) == [
        (DAY, "issue", "ticket_issued", "intent", 0, 1),
        (DAY, "issue", "ticket_registry_full", "intent", 0, 1),
        (DAY, "model_call", "ticket_live", "intent", 1, 1),
        (DAY, "tool", "ticket_live", "intent", 0, 1),
    ]
    assert await rows(store.path, "SELECT operation, code FROM ticket_samples") == [("issue", "ticket_registry_full")]
    assert recorder.threads == [threading.get_ident()] * 4, "each offer ran on the loop's thread"
    assert service.off_loop_checks() == {SEAM_MODEL_CALL: 1} and service.failures == 0


async def test_an_offer_that_raises_is_one_counted_failure_and_hold_leaves_the_carrier_as_it_was(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, store: AdmissionShadowStore,
) -> None:
    """TO9: #1604 property 6 for the offers; an offer that raises counts one failure, in ``hold`` it runs before the
    carrier is set, and in ``_check_ticket`` after the off-loop count."""
    plain = AdmissionService(identities, stops, tickets=tickets)
    service = AdmissionService(
        identities, stops, recorder=_RaisingTicketRecorder(store), tickets=tickets, loop=asyncio.get_running_loop(),
    )
    outer = plain.hold(presented_id=AGENT_A, work_kind="intent", seam=SEAM_INTENT, child=False)
    try:
        assert outer.ticket is not None and CURRENT_TICKET.get() is outer.ticket, "premise: the outer hold is carried"
        assert service.hold(presented_id=AGENT_B, work_kind="intent", seam=SEAM_INTENT, child=False) is NO_HOLD
        assert CURRENT_TICKET.get() is outer.ticket, "the carrier is as it was"
        assert service.failures == 1 and len(tickets) == 2, "one failure; the issued entry stays registered"
        service.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A)
        assert service.failures == 2
        await asyncio.to_thread(service.check_ticket, effect=SEAM_MODEL_CALL, presented_id=None)
        await _settle()
        assert service.failures == 3 and service.off_loop_checks() == {SEAM_MODEL_CALL: 1}, (
            "the handed-over check was counted off the loop before its offer raised"
        )
    finally:
        outer.end()
    assert tickets.tally() == {
        ("issue", "ticket_issued"): 2, ("tool", "ticket_live"): 1, ("model_call", "ticket_live"): 1,
    }


async def test_a_captains_stop_reaches_a_run_and_its_delegated_child_in_the_persisted_record(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, store: AdmissionShadowStore,
) -> None:
    """TO10: the chain of register R52, from the sinks of a real run entry to the report's queries (#1604 properties 5
    and 8)."""
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    service = AdmissionService(identities, stops, recorder=recorder, tickets=tickets, loop=asyncio.get_running_loop())
    tools = _tools(stops, service)
    gateway = _gateway(service)
    runtime = SimpleNamespace(tool_registry=tools, admission_service=service)
    seen: dict[str, Any] = {}

    async def model_and_tool(agent_id: str) -> None:
        await gateway.complete(LLMRequest(prompt="p", agent_id=agent_id))
        await tools.check_and_invoke(agent_id, _ABSENT, {})

    async def parent(arguments: dict[str, Any]) -> str:
        seen["parent"] = CURRENT_TICKET.get()
        await model_and_tool(AGENT_A)
        result = await _run(runner, runtime, AGENT_B, {"_delegation_depth": 1})
        await model_and_tool(AGENT_A)
        return result

    async def child(arguments: dict[str, Any]) -> str:
        seen["child"] = CURRENT_TICKET.get()
        await model_and_tool(AGENT_B)
        issued = await stops.issue_stop(AGENT_A, reason="ad1346-m3d3b2: the Captain stops the delegating agent")
        seen["stop_id"] = issued.record.stop_id
        await model_and_tool(AGENT_B)
        return "child ran"

    runner = _ScriptedRun({AGENT_A: parent, AGENT_B: child})
    assert await _run(runner, runtime, AGENT_A) == "child ran"
    assert seen["parent"] is not None and seen["child"] is not None, "premise: both runs held a ticket"
    parent_id, child_id = seen["parent"].ticket_id, seen["child"].ticket_id
    assert service.failures == 0
    await recorder.stop()
    db = await open_read_only(store.path)
    try:
        by_operation = await run_query(db, "ticket_findings_by_operation", (DAY,))
        samples = await run_query(db, "ticket_samples", (10,))
        missing = await run_query(db, "ticket_missing_samples", (10,))
        markers = await run_query(db, "ticket_markers_by_boot")
    finally:
        await db.close()
    assert by_operation == [
        ("issue", "ticket_issued", "agentic_run", 0, 2),
        ("model_call", "ticket_live", "agentic_run", 0, 2),
        ("model_call", "ticket_revoked", "agentic_run", 0, 2),
        ("tool", "ticket_live", "agentic_run", 0, 2),
        ("tool", "ticket_revoked", "agentic_run", 0, 2),
    ]
    assert [(row[3], row[4]) for row in samples] == [("tool", "ticket_revoked"), ("model_call", "ticket_revoked")] * 2
    bodies = [json.loads(row[7]) for row in samples]
    assert [(body["ticket_id"], body["parent_id"], body["depth"]) for body in bodies] == [
        (ticket_digest(parent_id), "", 0), (ticket_digest(parent_id), "", 0),
        (ticket_digest(child_id), ticket_digest(parent_id), 1), (ticket_digest(child_id), ticket_digest(parent_id), 1),
    ], "newest first: the delegating run's two calls after the child returned, then the child's two"
    assert all(body["stop_id"] == seen["stop_id"] for body in bodies)
    assert not any(parent_id in row[7] or child_id in row[7] for row in samples), "no raw ticket id in a ring row"
    assert missing == []
    assert markers == [(recorder.boot_id, utc_hour(T0), utc_hour(T0), 10, 10, 0, 0)]


async def test_a_boot_persists_a_model_calls_finding_after_the_runtime_stops(tmp_path: Path) -> None:
    """TO11: the wiring of the record, on one boot."""
    runtime = ProbOSRuntime(config=_config(), data_dir=tmp_path / "boot", llm_client=_OfflineGateway())
    await runtime.start()
    try:
        recorder = runtime.admission_shadow_recorder
        assert isinstance(recorder, ShadowRecorder) and isinstance(runtime.llm_client, _OfflineGateway), (
            "premise: the boot built the recorder and kept the gateway"
        )
        boot_id = recorder.boot_id
        await runtime.llm_client.complete(LLMRequest(prompt="ad1346-m3d3b2"))
    finally:
        await runtime.stop()
    db = await open_read_only(tmp_path / "boot" / STORE_FILENAME)
    try:
        by_operation = await run_query(db, "ticket_findings_by_operation", ("1970-01-01",))
        markers = await run_query(db, "ticket_markers_by_boot")
    finally:
        await db.close()
    assert any(row[:3] == ("model_call", "ticket_missing", "") and row[4] >= 1 for row in by_operation), by_operation
    mine = [row for row in markers if row[0] == boot_id]
    assert len(mine) == 1 and mine[0][3] == mine[0][4] >= 1 and mine[0][5] == 0, mine


async def test_the_counters_append_five_ticket_totals_and_start_marks_the_ticket_hour(store: AdmissionShadowStore) -> None:
    """TO12 (kills OX-17, OX-45, OX-46, OX-47)."""
    assert COUNTER_NAMES[8:] == (
        "ticket_offered", "ticket_written", "ticket_dropped", "ticket_samples_dropped", "ticket_late",
    )
    assert recorder_module.TICKET_SAMPLE_BUFFER_LIMIT == TICKET_SAMPLE_RING_SIZE
    assert recorder_module.TICKET_MISSING_BUFFER_LIMIT == TICKET_MISSING_RING_SIZE
    recorder = ShadowRecorder(store, wall_clock=_Clock(T0))
    recorder.start()
    await recorder.stop()
    assert await rows(store.path, MARKERS) == [(recorder.boot_id, utc_hour(T0), 0, 0, 0, 0)]
