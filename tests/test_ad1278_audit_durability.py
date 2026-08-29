"""AD-1278 / BF-780: the record that replaced the gate has to outlive the process.

BF-763 removed the quorum gate on ``run_python`` on the argument that the
per-execution audit record IS the substitute control. That record was
best-effort in four ways: an in-memory list, a sink that shipped OFF, no
shutdown drain, and unbounded growth with one asyncio task per append.

The posture recorded in AD-1278 is **durable-preferred with honest
degradation**, not durable-required -- a launch-time sink check would prove the
sink existed at t=0 and nothing about whether THIS record survives, while
costing availability. So these tests pin two things together:

* the good path is the default and the losses are closed (drain, cap,
  backpressure); and
* every remaining loss is VISIBLE -- in the run's own result, not only in a log
  line nobody reads.

The pair that matters most is ``test_truncated_chain_verifies_as_intact`` and
``test_tampered_truncated_chain_reports_broken``. Neither alone proves anything:
together they prove a bounded log and a mutated one are still distinguishable.
A cap that made ``verify_chain`` cry tamper on every boot would be worse than no
cap at all.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from probos.agents.code_runner import CodeRunnerAgent
from probos.config import ExecutionConfig, SecurityInfraConfig
from probos.execution.audit import ExecutionAuditor
from probos.security.audit import AuditEntry, AuditLog, AuditLogPersistence
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.tools.code_execution_tool import CodeExecutionTool
from probos.types import IntentMessage

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------

class _RecordingSink:
    """Confirms every batch, and remembers how many commits it took.

    ``batches`` is the direct evidence for "one commit per batch": a writer that
    reverted to per-row commits would show one batch per entry.
    """

    def __init__(self) -> None:
        self.batches: list[list[AuditEntry]] = []

    async def persist_entries(self, entries: Any) -> list[int]:
        rows = list(entries)
        self.batches.append(rows)
        return [e.sequence for e in rows]


class _WedgedSink:
    """Accepts a batch and never returns -- a sink that has stopped answering."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def persist_entries(self, entries: Any) -> list[int]:
        self.entered.set()
        await asyncio.Event().wait()
        return []  # pragma: no cover - unreachable


class _GatedSink:
    """Holds the first batch until released, then forwards to a real sink.

    The only way to see whether an overflowed entry SPILLED or was discarded is
    to force ``QueueFull`` against a sink that afterwards genuinely persists,
    then read the database back. A sink that never returns cannot answer that.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()
        self._held = False

    async def persist_entries(self, entries: Any) -> list[int]:
        if not self._held:
            self._held = True
            self.entered.set()
            await self.gate.wait()
        return await self._inner.persist_entries(entries)


class _FlakySink:
    """Refuses the first ``failures`` batch attempts, then forwards.

    ``persist_entries`` is all-or-nothing, so a writer that SKIPS a refused
    batch lets the next success confirm a higher range than the failure -- the
    hole that survives a perfectly behaved queue.
    """

    def __init__(self, inner: Any, failures: int) -> None:
        self._inner = inner
        self._remaining = failures
        self.attempts = 0

    async def persist_entries(self, entries: Any) -> list[int]:
        self.attempts += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise RuntimeError("database is locked")
        return await self._inner.persist_entries(entries)


class _BreakingSink:
    """Forwards until ``break_at`` appears in a batch, then refuses for ever."""

    def __init__(self, inner: Any, break_at: int) -> None:
        self._inner = inner
        self._break_at = break_at

    async def persist_entries(self, entries: Any) -> list[int]:
        rows = list(entries)
        if any(e.sequence >= self._break_at for e in rows):
            raise RuntimeError("disk full")
        return await self._inner.persist_entries(rows)


async def _wedge(log: AuditLog, sink: _WedgedSink) -> None:
    """Get the writer running and blocked inside the sink."""
    await asyncio.wait_for(sink.entered.wait(), timeout=5.0)


# ---------------------------------------------------------------------------
# Runtime / tool doubles (BF-287: real config objects, never MagicMock)
# ---------------------------------------------------------------------------

def _tool_runtime(tmp_path: Path, *, audit: Any) -> Any:
    cfg = SimpleNamespace(
        enabled=True,
        scratch_dir=str(tmp_path / "scratch"),
        timeout_seconds=30,
        max_output_bytes=65536,
        max_memory_mb=512,
        stage_thread_artifacts=False,
        fetch_broker_enabled=False,
        persistent_workspaces=False,
    )
    return SimpleNamespace(
        config=SimpleNamespace(execution=cfg, dependency=None),
        audit_log=audit,
        agent_registry=None,
        artifact_store=None,
    )


def _mesh_agent(tmp_path: Path, *, audit: Any) -> CodeRunnerAgent:
    cfg = ExecutionConfig(
        enabled=True,
        scratch_dir=str(tmp_path / "exec"),
        workspace_root=str(tmp_path / "workspaces"),
    )
    runtime = SimpleNamespace(
        config=SimpleNamespace(execution=cfg), audit_log=audit,
    )
    return CodeRunnerAgent(agent_id="cr-ad1278", runtime=runtime)


def _drain_runtime(log: AuditLog, persistence: AuditLogPersistence | None) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(security_infra=SecurityInfraConfig()),
        audit_log=log,
        audit_log_persistence=persistence,
    )


async def _open_persistence(db_file: Path) -> AuditLogPersistence:
    persistence = AuditLogPersistence(
        db_path=str(db_file), connection_factory=SQLiteConnectionFactory(),
    )
    await persistence.start()
    return persistence


# ===========================================================================
# Slice A -- the losses that need no policy
# ===========================================================================

@pytest.mark.asyncio
async def test_shutdown_drain_flushes_the_last_append(tmp_path: Path) -> None:
    """append -> shutdown drain -> the row is ON DISK.

    The crossing test. Asserting that the drain was CALLED would have passed
    against every version of this that lost the tail; the only thing that
    settles it is reopening the database afterwards and finding the FINAL entry
    there, having never awaited a flush ourselves.
    """
    from probos.startup.shutdown import _drain_audit_log

    db_file = tmp_path / "audit.db"
    persistence = await _open_persistence(db_file)
    log = AuditLog()
    log.attach_persistence(persistence)

    for i in range(5):
        log.append(category="code_execution", detail=f"run-{i}")
    last = log.entries[-1]

    runtime = _drain_runtime(log, persistence)
    await _drain_audit_log(runtime)

    assert runtime.audit_log_persistence is None

    reopened = await _open_persistence(db_file)
    try:
        rows = await reopened.load_entries()
        assert [r.sequence for r in rows] == [0, 1, 2, 3, 4]
        assert rows[-1].entry_hash == last.entry_hash
        assert rows[-1].detail == "run-4"
    finally:
        await reopened.stop()


def test_shutdown_calls_both_audit_phases_in_order() -> None:
    """The helpers are reached from the real teardown, in the right places.

    AD-1278 revision 3 CHANGED this test. It previously asserted exactly ONE
    ``_drain_audit_log`` call site and said nothing about where it sat. That
    passed against the rejected build, whose single drain ran ~138 lines before
    the pools -- and because ``drain()`` closes registration, every audit-worthy
    event from pool, mesh and semantic-layer teardown could then only be
    recorded in memory. Position relative to those teardowns is the property
    that matters, so it is what is asserted now.
    """
    from probos.startup import shutdown as shutdown_mod

    source = inspect.getsource(shutdown_mod.shutdown)
    flush = source.find("await _flush_audit_log(runtime)")
    pools = source.find("await _stop_pools_and_drain_intent_bus(")
    semantic = source.find("await runtime._semantic_layer.stop()")
    drain = source.find("await _drain_audit_log(runtime)")
    started_false = source.find("runtime._started = False")

    assert -1 not in (flush, pools, semantic, drain, started_false)
    assert source.count("await _flush_audit_log(runtime)") == 1
    assert source.count("await _drain_audit_log(runtime)") == 1
    # Phase 1 early, registration still open.
    assert flush < pools
    # Phase 2 after everything that could still append, before the last line.
    assert semantic < drain < started_false


@pytest.mark.asyncio
async def test_a_raising_semantic_stop_still_drains_the_audit_log(
    tmp_path: Path,
) -> None:
    """Review reproduced the skip: a raising ``_semantic_layer.stop()`` gave
    ``drain_called=False``, losing the tail on exactly the failure path an
    investigator most wants the record for. Position alone did not protect it,
    so the drain sits in a ``finally``."""
    from probos.startup import shutdown as shutdown_mod

    source = inspect.getsource(shutdown_mod.shutdown)
    semantic = source.find("await runtime._semantic_layer.stop()")
    drain = source.find("await _drain_audit_log(runtime)")
    finally_marker = source.rfind("finally:", semantic, drain)

    # PREMISE: both anchors were found, or the ordering below proves nothing.
    assert -1 not in (semantic, drain)
    assert finally_marker != -1, (
        "phase 2 is not in a finally after the semantic stop; a raising stop() "
        "skips the authoritative drain and the tail is lost"
    )


@pytest.mark.asyncio
async def test_drain_closes_registration_so_later_appends_are_not_queued(
    tmp_path: Path,
) -> None:
    """Registration closes FIRST, so the drain has a fixed target.

    Without this the drain chases a moving queue and can never prove it
    finished. An append after the drain still joins the in-memory chain -- it
    just stops claiming durability it will not get.
    """
    persistence = await _open_persistence(tmp_path / "audit.db")
    try:
        log = AuditLog(max_entries=0)
        log.attach_persistence(persistence)
        log.append(category="code_execution", detail="before")
        assert await log.drain(timeout_seconds=2.0) == 0

        assert log.durable_stream_open() is False
        late = log.append(category="code_execution", detail="after")

        assert isinstance(late, AuditEntry)
        assert log.entries[-1] is late
        assert log._queue is not None and log._queue.qsize() == 0
        assert [r.detail for r in await persistence.load_entries()] == ["before"]
    finally:
        await persistence.stop()


@pytest.mark.asyncio
async def test_drain_is_bounded_when_the_sink_is_wedged() -> None:
    """A drain that hangs shutdown is a worse defect than the tail it saves."""
    sink = _WedgedSink()
    log = AuditLog(max_entries=0)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    log.append(category="code_execution", detail="wedged")
    await _wedge(log, sink)
    log.append(category="code_execution", detail="stuck-behind-it")

    # The test is bounded too, so a regression FAILS rather than hanging CI.
    unflushed = await asyncio.wait_for(
        log.drain(timeout_seconds=0.2), timeout=5.0,
    )

    assert unflushed >= 1


@pytest.mark.asyncio
async def test_wedged_drain_logs_the_loss_at_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The tail loss is a stated fact, not a silence."""
    sink = _WedgedSink()
    log = AuditLog(max_entries=0)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    log.append(category="code_execution", detail="a")
    await _wedge(log, sink)
    log.append(category="code_execution", detail="b")

    caplog.set_level(logging.ERROR, logger="probos.security.audit")
    unflushed = await asyncio.wait_for(
        log.drain(timeout_seconds=0.1), timeout=5.0,
    )

    errors = [
        r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR
    ]
    assert any("unflushed" in m for m in errors), errors
    assert any(str(unflushed) in m for m in errors), errors
    assert any("not confirmed on disk" in m.lower() for m in errors), errors


@pytest.mark.asyncio
async def test_drain_reraises_cancellation() -> None:
    """Cancellation belongs to the shutdown, not to this drain."""
    sink = _WedgedSink()
    log = AuditLog(max_entries=0)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    log.append(category="code_execution", detail="a")
    await _wedge(log, sink)
    writer = log._writer_task
    assert writer is not None

    draining = asyncio.create_task(log.drain(timeout_seconds=30.0))
    await asyncio.sleep(0)
    draining.cancel()

    with pytest.raises(asyncio.CancelledError):
        await draining

    await asyncio.wait({writer}, timeout=5.0)
    assert writer.cancelled() is True


@pytest.mark.asyncio
async def test_queue_full_does_not_raise_from_append() -> None:
    """``append`` is synchronous and must never raise or block on backpressure."""
    sink = _WedgedSink()
    log = AuditLog(max_entries=0, write_queue_maxsize=1)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    log.append(category="code_execution", detail="taken-by-the-writer")
    await _wedge(log, sink)

    entries = [
        log.append(category="code_execution", detail=f"pressure-{i}")
        for i in range(10)
    ]

    assert all(isinstance(e, AuditEntry) for e in entries)
    assert len(log.entries) == 11
    # AD-1278 revision 3: `_dropped` became `_spilled`. Overflow no longer
    # discards -- a discarded sequence poisons the on-disk chain.
    assert log._spilled >= 1
    # The chain is still whole in memory -- backpressure loses DURABILITY, not
    # the record.
    assert log.verify_chain() is True

    await asyncio.wait_for(log.drain(timeout_seconds=0.05), timeout=5.0)


@pytest.mark.asyncio
async def test_n_appends_do_not_create_n_tasks() -> None:
    """Gap 4's direct regression: 1,000 appends used to mint 1,000 tasks."""
    sink = _WedgedSink()
    log = AuditLog(max_entries=0, write_queue_maxsize=10_000)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    log.append(category="code_execution", detail="first")
    await _wedge(log, sink)
    writer = log._writer_task

    for i in range(200):
        log.append(category="code_execution", detail=f"n-{i}")

    named = [t for t in asyncio.all_tasks() if t.get_name() == "audit-log-writer"]
    assert len(named) == 1
    assert log._writer_task is writer

    await asyncio.wait_for(log.drain(timeout_seconds=0.05), timeout=5.0)


@pytest.mark.asyncio
async def test_the_writer_commits_in_batches() -> None:
    """One commit per batch, not per row."""
    sink = _RecordingSink()
    log = AuditLog(max_entries=0)
    log.attach_persistence(sink)  # type: ignore[arg-type]

    for i in range(25):
        log.append(category="code_execution", detail=f"b-{i}")
    await log.flush()

    assert sum(len(b) for b in sink.batches) == 25
    assert len(sink.batches) < 25


def test_append_remains_sync_with_no_running_loop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The sync path stays a debug-logged no-op, never an error."""
    log = AuditLog()
    log.attach_persistence(_RecordingSink())  # type: ignore[arg-type]

    caplog.set_level(logging.DEBUG, logger="probos.security.audit")
    entry = log.append(category="code_execution", detail="sync")

    assert isinstance(entry, AuditEntry)
    assert log._queue is None
    assert log._writer_task is None
    assert any("without running loop" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_tool_result_labels_a_run_with_no_sink(tmp_path: Path) -> None:
    """Acceptance 7, agentic path: the run says so in its OWN result."""
    tool = CodeExecutionTool(runtime=_tool_runtime(tmp_path, audit=None))

    res = await tool.invoke({"code": "print('x')"}, {"agent_id": "ezri"})

    assert res.output is not None
    assert res.output["audit"] == "absent"


@pytest.mark.asyncio
async def test_intent_result_labels_a_run_with_no_sink(tmp_path: Path) -> None:
    """Acceptance 7, MESH path -- the half a one-path fix would have missed."""
    agent = _mesh_agent(tmp_path, audit=None)

    res = await agent.handle_intent(
        IntentMessage(intent="run_python", params={"code": "print('x')"}),
    )

    assert res is not None
    assert res.result is not None
    assert res.result["audit"] == "absent"


@pytest.mark.asyncio
async def test_a_queued_run_carries_no_label(tmp_path: Path) -> None:
    """The happy path is unchanged -- the label means something because it is
    absent when the record IS admitted to the durable stream.

    AD-1278 revision 3 CHANGED this test. It was
    ``test_a_durable_run_carries_no_label`` and asserted ``record["durable"] is
    True`` -- i.e. it pinned as CONTRACT the claim that a synchronous ``record``
    call can know the entry reached disk. It cannot: the writer commits later.
    The suppressed label is now ``"queued"`` (admission, observable) and the
    record carries ``stream``, never ``durable``.
    """
    sink = _RecordingSink()
    log = AuditLog(max_entries=0)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    tool = CodeExecutionTool(runtime=_tool_runtime(tmp_path, audit=log))

    res = await tool.invoke({"code": "print('x')"}, {"agent_id": "ezri"})

    assert res.output is not None
    assert "audit" not in res.output
    await log.flush()
    record = json.loads(log.entries[-1].detail)
    assert record["stream"] == "queued"
    assert "durable" not in record


def test_both_auditors_warn_independently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AD-1280's per-instance sentinel: two untrailed paths is two facts.

    A shared process-wide flag would report the first and hide the second, and
    an operator seeing only the agentic warning would reasonably conclude the
    mesh path was trailed.
    """
    runtime = SimpleNamespace(audit_log=None)
    first = ExecutionAuditor(runtime)
    second = ExecutionAuditor(runtime)

    caplog.set_level(logging.WARNING, logger="probos.execution.audit")
    outcomes = [
        auditor.record(
            execution_id="i" * 32,
            agent_id="ezri",
            code="print(1)",
            timeout_seconds=1.0,
            duration_ms=1.0,
            launch_state="launched",
        )
        for auditor in (first, second, first, second)
    ]

    assert outcomes == ["absent"] * 4
    warnings = [
        r for r in caplog.records if "no audit sink" in r.getMessage()
    ]
    assert len(warnings) == 2


@pytest.mark.asyncio
async def test_result_labels_a_run_whose_entry_was_spilled(
    tmp_path: Path,
) -> None:
    """Queue full -> the entry SPILLS, and it is on disk afterwards.

    AD-1278 revision 3 CHANGED this test. It was
    ``test_result_labels_a_run_whose_entry_was_dropped`` and asserted
    ``record["durable"] is False`` plus ``output["audit"] == "in-memory-only"``
    -- pinning queue-full DISCARD as the contract. Discarding a sequence leaves
    the next persisted row's ``prior_hash`` pointing at a row that is not there,
    so the rehydrated chain reports ``broken`` forever. Overflow now spills, and
    a full queue is therefore no longer a durability failure: the stream is
    still open, so the run is ``"queued"`` and carries no label. What the test
    settles is that the spilled entry REACHES THE DATABASE.
    """
    db_file = tmp_path / "audit.db"
    persistence = await _open_persistence(db_file)
    gated = _GatedSink(persistence)
    log = AuditLog(max_entries=0, write_queue_maxsize=1)
    log.attach_persistence(gated)  # type: ignore[arg-type]
    try:
        log.append(category="seed", detail="taken-by-the-writer")
        await asyncio.wait_for(gated.entered.wait(), timeout=5.0)
        log.append(category="seed", detail="fills-the-queue")
        log.append(category="seed", detail="overflows")
        assert log._spilled >= 1
        assert log.durable_stream_open() is True

        tool = CodeExecutionTool(runtime=_tool_runtime(tmp_path, audit=log))
        res = await tool.invoke({"code": "print('x')"}, {"agent_id": "ezri"})

        assert res.output is not None
        assert "audit" not in res.output
        record = json.loads(log.entries[-1].detail)
        assert record["stream"] == "queued"

        gated.gate.set()
        await asyncio.wait_for(log.drain(timeout_seconds=5.0), timeout=10.0)
        rows = await persistence.load_entries()
        assert [r.sequence for r in rows] == [e.sequence for e in log.entries]
    finally:
        await persistence.stop()


# ===========================================================================
# Slice B -- the policy half
# ===========================================================================

async def _capped_log(cap: int, count: int) -> tuple[AuditLog, _RecordingSink]:
    sink = _RecordingSink()
    log = AuditLog(max_entries=cap)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    for i in range(count):
        log.append(category="code_execution", detail=f"e-{i}")
        await log.flush()
    return log, sink


@pytest.mark.asyncio
async def test_entries_are_capped_at_audit_max_entries() -> None:
    log, _ = await _capped_log(cap=3, count=10)

    assert len(log.entries) == 3


@pytest.mark.asyncio
async def test_eviction_is_fifo_from_the_head() -> None:
    """Only head-eviction leaves a contiguous, verifiable suffix."""
    log, _ = await _capped_log(cap=3, count=10)

    assert [e.sequence for e in log.entries] == [7, 8, 9]


@pytest.mark.asyncio
async def test_unpersisted_entries_are_not_evicted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With a sink ATTACHED and behind, the cap never destroys the only copy.

    AD-1278 revision 3 CHANGED this test. It previously ran with NO persistence
    attached and asserted the list grew past the cap -- pinning an
    undifferentiated refusal to evict. That silently defeated ``max_entries`` in
    the commonest deployment (persistence off), so the memory bound was
    decorative exactly where it was most needed. The persistence-off case is now
    ``test_cap_evicts_normally_when_persistence_is_off``; this test keeps the
    half that was always right -- an entry somebody was PROMISED would be
    durable, and which is not yet durable, is untouchable.
    """
    sink = _WedgedSink()
    log = AuditLog(max_entries=3)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    caplog.set_level(logging.WARNING, logger="probos.security.audit")

    log.append(category="code_execution", detail="e-0")
    await _wedge(log, sink)
    for i in range(1, 10):
        log.append(category="code_execution", detail=f"e-{i}")

    assert len(log.entries) == 10
    assert log._truncated_at is None
    assert log.chain_state()[0] == "intact"
    assert any("over its 3 cap" in r.getMessage() for r in caplog.records)

    await asyncio.wait_for(log.drain(timeout_seconds=0.05), timeout=5.0)


@pytest.mark.asyncio
async def test_truncated_chain_verifies_as_intact() -> None:
    """A bounded log must not report itself as tampered.

    Paired with ``test_tampered_truncated_chain_reports_broken``. The control
    below is the load-bearing half: WITHOUT the anchor the same suffix fails,
    so this test cannot pass by accident on a chain that was never truncated.
    """
    log, _ = await _capped_log(cap=3, count=10)
    assert log._truncated_at is not None

    assert log.verify_chain() is True

    unanchored = AuditLog(max_entries=0)
    unanchored.entries.extend(log.entries)
    assert unanchored.verify_chain() is False


@pytest.mark.asyncio
async def test_truncated_chain_reports_truncated_not_intact() -> None:
    """Silent truncation reported as complete is the same lie the other way up."""
    log, _ = await _capped_log(cap=3, count=10)

    state, first_sequence, evicted = log.chain_state()

    assert state == "truncated"
    assert first_sequence == 7
    assert evicted == 7


@pytest.mark.asyncio
async def test_tampered_truncated_chain_reports_broken() -> None:
    """Truncation and tampering stay distinguishable AFTER a truncation."""
    log, _ = await _capped_log(cap=3, count=10)

    log.entries[1] = dataclasses.replace(log.entries[1], detail="MUTATED")

    assert log.verify_chain() is False
    assert log.chain_state()[0] == "broken"


@pytest.mark.asyncio
async def test_watermark_is_monotonic() -> None:
    """A freely-settable anchor would let tampering masquerade as truncation:
    move it to the break and a mutated chain verifies as intact."""
    log = AuditLog(max_entries=0)
    log.mark_truncated(5, "a" * 64)

    with pytest.raises(ValueError):
        log.mark_truncated(3, "b" * 64)
    with pytest.raises(ValueError):
        log.mark_truncated(5, "c" * 64)

    assert log._truncated_at == (5, "a" * 64)
    log.mark_truncated(6, "d" * 64)
    assert log._truncated_at == (6, "d" * 64)


@pytest.mark.asyncio
async def test_watermark_only_moves_via_eviction() -> None:
    """Appending, verifying and reading state never anchor the chain."""
    log = AuditLog(max_entries=0)
    for i in range(20):
        log.append(category="code_execution", detail=f"e-{i}")
    log.verify_chain()
    log.chain_state()

    assert log._truncated_at is None

    evicting, _ = await _capped_log(cap=2, count=5)
    assert evicting._truncated_at is not None
    assert evicting._truncated_at[0] == 2


@pytest.mark.asyncio
async def test_load_entries_respects_the_cap(tmp_path: Path) -> None:
    """A boot that rehydrated every row rebuilds the list the cap prevents."""
    persistence = await _open_persistence(tmp_path / "audit.db")
    try:
        log = AuditLog(max_entries=0)
        log.attach_persistence(persistence)
        for i in range(10):
            log.append(category="code_execution", detail=f"e-{i}")
        await log.flush()

        bounded = await persistence.load_entries(limit=3)
        assert [e.sequence for e in bounded] == [7, 8, 9]

        unbounded = await persistence.load_entries()
        assert [e.sequence for e in unbounded] == list(range(10))

        assert await persistence.watermark_before(7) == (6, unbounded[6].entry_hash)
        assert await persistence.watermark_before(0) is None
    finally:
        await persistence.stop()


@pytest.mark.asyncio
async def test_boot_sets_the_watermark_before_verifying(tmp_path: Path) -> None:
    """The ordering bug: a legitimately-capped rehydrate must not log tamper.

    Driving the exact sequence ``finalize`` uses, plus the counter-case that
    proves the ORDER is what matters rather than the presence of a watermark.
    """
    persistence = await _open_persistence(tmp_path / "audit.db")
    try:
        seed = AuditLog(max_entries=0)
        seed.attach_persistence(persistence)
        for i in range(10):
            seed.append(category="code_execution", detail=f"e-{i}")
        await seed.flush()

        loaded = await persistence.load_entries(limit=3)
        watermark = await persistence.watermark_before(loaded[0].sequence)
        assert watermark is not None

        rehydrated = AuditLog(max_entries=3)
        rehydrated.mark_truncated(*watermark)
        rehydrated.entries.extend(loaded)
        rehydrated.mark_persisted_through(loaded[-1].sequence)

        assert rehydrated.verify_chain() is True
        assert rehydrated.chain_state()[0] == "truncated"

        # Counter-case: the same rows without the anchor read as tampered.
        unanchored = AuditLog(max_entries=3)
        unanchored.entries.extend(loaded)
        assert unanchored.verify_chain() is False

        # A NEW append continues the sequence rather than colliding with a
        # persisted row -- `len(entries)` would have said 3.
        assert rehydrated.append(category="code_execution", detail="next").sequence == 10
    finally:
        await persistence.stop()


def test_finalize_anchors_before_it_verifies() -> None:
    """Guard the ORDER in the one production caller.

    A behavioural test of the sequence cannot see finalize doing it backwards,
    and finalize's audit block is deliberately not refactored for testability.
    """
    from probos.startup import finalize as finalize_mod

    source = inspect.getsource(finalize_mod.finalize_startup)
    anchor = source.find("runtime.audit_log.mark_truncated(*watermark)")
    verify = source.find("if not runtime.audit_log.verify_chain():")
    load = source.find("await persistence.load_entries(")

    assert anchor != -1 and verify != -1 and load != -1
    assert anchor < verify
    assert "limit=config.security_infra.audit_max_entries" in source


def test_persistence_default_is_true() -> None:
    """Acceptance 8, in BOTH places -- the YAML has drifted from the model before."""
    assert SecurityInfraConfig().audit_persistence_enabled is True

    shipped = yaml.safe_load((_REPO_ROOT / "config" / "system.yaml").read_text())
    assert shipped["security_infra"]["audit_persistence_enabled"] is True


def test_the_new_bounds_exist_on_the_model() -> None:
    """BF-758's lesson: assert a config field exists ON THE MODEL, never infer
    it from a successful ``getattr``."""
    fields = SecurityInfraConfig.model_fields
    assert "audit_max_entries" in fields
    assert "audit_drain_timeout_s" in fields
    assert "audit_write_queue_maxsize" in fields
    assert "audit_spill_maxsize" in fields

    cfg = SecurityInfraConfig()
    assert cfg.audit_max_entries == 10_000
    assert cfg.audit_drain_timeout_s == 2.0
    assert cfg.audit_write_queue_maxsize == 1000
    assert cfg.audit_write_max_retries == 3
    assert cfg.audit_spill_maxsize == 10_000
    # Deliberately NOT `shutdown_drain_timeout_s` (30.0), which is larger than
    # the 10s `__main__.py` allows the whole teardown.
    assert cfg.audit_drain_timeout_s < 10.0


# ===========================================================================
# Revision 3 -- the non-contiguous case.
#
# The rejected build ran seventeen mutants, killed all of them, and shipped two
# Criticals: not one mutant constructed a stream with a HOLE in it. A hole is
# not a bookkeeping error. ``prior_hash`` chains each row to its predecessor, so
# a sequence that never reaches SQLite leaves the next persisted row pointing at
# a row that is not there, and the rehydrated chain reports ``broken`` at every
# future boot. These tests are about the durable artefact, not the watermark.
# ===========================================================================

async def _overflow_against_sqlite(
    tmp_path: Path, *, cap: int, count: int,
) -> tuple[AuditLog, AuditLogPersistence, Path]:
    """Force ``QueueFull`` against a REAL sink, then let it catch up.

    A wedged sink cannot answer the question these tests ask -- whether the
    overflowed entries eventually reach the database -- so the sink here is
    genuine SQLite behind a gate.
    """
    db_file = tmp_path / "audit.db"
    persistence = await _open_persistence(db_file)
    gated = _GatedSink(persistence)
    log = AuditLog(max_entries=cap, write_queue_maxsize=1)
    log.attach_persistence(gated)  # type: ignore[arg-type]
    log.append(category="code_execution", detail="e-0")
    await asyncio.wait_for(gated.entered.wait(), timeout=5.0)
    for i in range(1, count):
        log.append(category="code_execution", detail=f"e-{i}")
    # The probe asserts its own premise: without an overflow every assertion
    # below would pass against a build that drops on QueueFull.
    assert log._spilled >= 1, "the queue never overflowed; this proves nothing"
    gated.gate.set()
    await asyncio.wait_for(log.drain(timeout_seconds=5.0), timeout=15.0)
    return log, persistence, db_file


@pytest.mark.asyncio
async def test_queue_overflow_leaves_no_hole_in_the_persisted_stream(
    tmp_path: Path,
) -> None:
    """The headline test. Overflow SPILLS; the persisted set is contiguous.

    Against the rejected build this measured ``db [0, 3]`` for four appends --
    two sequences that existed in memory and never reached disk.
    """
    log, persistence, _ = await _overflow_against_sqlite(
        tmp_path, cap=0, count=12,
    )
    try:
        rows = await persistence.load_entries()
        sequences = [r.sequence for r in rows]

        assert sequences == list(range(12))
        assert log._spilled >= 1
    finally:
        await persistence.stop()


def test_watermark_refuses_a_non_contiguous_advance(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One integer cannot represent a set with a hole in it.

    ``max(confirmed)`` turned "this batch committed" -- a point observation --
    into "everything at or below this is on disk", a range property. Accepting
    the jump is how the only copy of an unpersisted entry gets deleted.
    """
    log = AuditLog(max_entries=0)
    for i in range(6):
        log.append(category="code_execution", detail=f"e-{i}")

    log.mark_persisted_through(0)
    assert log._persisted_through == 0

    caplog.set_level(logging.ERROR, logger="probos.security.audit")
    log.mark_persisted_through(3)

    assert log._persisted_through == 0
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("non-contiguous" in m for m in errors), errors

    # The step that IS contiguous still moves it.
    log.mark_persisted_through(1)
    assert log._persisted_through == 1


@pytest.mark.asyncio
async def test_eviction_never_drops_an_entry_absent_from_the_sink(
    tmp_path: Path,
) -> None:
    """The reproduction, asserted. Nothing evicted may be missing from the DB.

    Measured against the rejected build: ``mem [2, 3]`` after eviction while
    ``db [0, 3]`` -- sequences 1 and 2 existed nowhere at all.
    """
    log, persistence, _ = await _overflow_against_sqlite(
        tmp_path, cap=4, count=12,
    )
    try:
        db_sequences = {r.sequence for r in await persistence.load_entries()}
        assert log._truncated_at is not None, "nothing was evicted; this proves nothing"
        evicted = set(range(log._truncated_at[0] + 1))

        assert evicted - db_sequences == set()
        assert len(log.entries) == 4
    finally:
        await persistence.stop()


@pytest.mark.asyncio
async def test_rehydrated_chain_is_intact_after_overflow(tmp_path: Path) -> None:
    """The chain half of the same scenario -- the amendment that decided rev 3.

    A watermark fix alone leaves this failing: the rejected build rehydrated to
    ``verify False`` / ``('broken', 0, 0)`` because a persisted row's
    ``prior_hash`` named a row that was never written.
    """
    _log, persistence, db_file = await _overflow_against_sqlite(
        tmp_path, cap=4, count=12,
    )
    await persistence.stop()

    reopened = await _open_persistence(db_file)
    try:
        loaded = await reopened.load_entries()
        assert len(loaded) == 12

        rehydrated = AuditLog(max_entries=0)
        rehydrated.entries.extend(loaded)

        assert rehydrated.verify_chain() is True
        assert rehydrated.chain_state()[0] != "broken"
    finally:
        await reopened.stop()


@pytest.mark.asyncio
async def test_failed_batch_is_retried_not_skipped(tmp_path: Path) -> None:
    """Hole source #2, which survives a perfectly behaved queue.

    ``persist_entries`` is all-or-nothing, so a writer that moves on after a
    refusal lets the NEXT success confirm a higher range than the failure.
    """
    persistence = await _open_persistence(tmp_path / "audit.db")
    flaky = _FlakySink(persistence, failures=1)
    log = AuditLog(max_entries=0)
    log.attach_persistence(flaky)  # type: ignore[arg-type]
    try:
        for i in range(4):
            log.append(category="code_execution", detail=f"e-{i}")
            await log.flush(timeout_seconds=5.0)

        assert flaky.attempts >= 5, "the sink never refused; this proves nothing"
        rows = await persistence.load_entries()
        assert [r.sequence for r in rows] == [0, 1, 2, 3]
        assert log._persisted_through == 3
    finally:
        await asyncio.wait_for(log.drain(timeout_seconds=1.0), timeout=5.0)
        await persistence.stop()


@pytest.mark.asyncio
async def test_exhausted_retries_terminate_the_stream(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """The durable stream ENDS rather than writing past a gap.

    Terminating is the trade this AD accepts: a persisted chain with a hole
    lies about its own integrity at every future boot, while one that stops
    says plainly where it ended and rehydrates cleanly.
    """
    db_file = tmp_path / "audit.db"
    persistence = await _open_persistence(db_file)
    breaking = _BreakingSink(persistence, break_at=1)
    log = AuditLog(max_entries=0, write_max_retries=1)
    log.attach_persistence(breaking)  # type: ignore[arg-type]
    caplog.set_level(logging.ERROR, logger="probos.security.audit")
    try:
        log.append(category="code_execution", detail="e-0")
        await log.flush(timeout_seconds=5.0)
        assert log._persisted_through == 0

        log.append(category="code_execution", detail="e-1")
        await log.flush(timeout_seconds=5.0)

        assert log._stream_broken_at == 1
        assert log.durable_stream_open() is False

        log.append(category="code_execution", detail="e-2")
        await asyncio.sleep(0.05)

        rows = await persistence.load_entries()
        assert [r.sequence for r in rows] == [0], "the chain gained a hole"
        errors = [
            r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR
        ]
        # BF-861 reworded this: the message used to hard-code "the audit sink
        # refused sequence N on M consecutive attempts", which is only one of
        # the two ways to get here now. The cause moved into a parameter, so
        # this pins the ending AND that this ending names the refusing sink.
        assert any("ENDING the durable audit stream" in m for m in errors), errors
        assert any("refused sequence 1 on 2 consecutive attempts" in m for m in errors), errors
    finally:
        await persistence.stop()

    reopened = await _open_persistence(db_file)
    try:
        rehydrated = AuditLog(max_entries=0)
        rehydrated.entries.extend(await reopened.load_entries())
        assert rehydrated.verify_chain() is True
    finally:
        await reopened.stop()


def test_cap_evicts_normally_when_persistence_is_off() -> None:
    """With no sink attached the log is a ring buffer BY THE OPERATOR'S CHOICE.

    The rejected build refused to evict here too, which made ``audit_max_entries``
    decorative in the commonest deployment -- a memory bound that quietly does
    not exist. Nobody was promised a durable copy, so there is no "only copy on
    disk" to protect, and the truncation watermark keeps the remainder
    verifiable.
    """
    log = AuditLog(max_entries=3)

    for i in range(10):
        log.append(category="code_execution", detail=f"e-{i}")

    assert len(log.entries) == 3
    assert [e.sequence for e in log.entries] == [7, 8, 9]
    assert log.chain_state()[0] == "truncated"
    assert log.verify_chain() is True


# ===========================================================================
# Revision 3 -- labelling. `record` reports admission, never disk.
# ===========================================================================

def _auditor_outcome(audit: Any) -> str:
    return ExecutionAuditor(SimpleNamespace(audit_log=audit)).record(
        execution_id="i" * 32,
        agent_id="ezri",
        code="print(1)",
        timeout_seconds=1.0,
        duration_ms=1.0,
        launch_state="launched",
    )


@pytest.mark.asyncio
async def test_record_never_returns_durable() -> None:
    """"durable" left the vocabulary: nothing synchronous can honestly say it.

    ``record`` returns before the writer has touched SQLite, so a "durable"
    answer would be a forecast written down as an outcome.
    """
    sink = _RecordingSink()
    open_stream = AuditLog(max_entries=0)
    open_stream.attach_persistence(sink)  # type: ignore[arg-type]

    outcomes = [
        _auditor_outcome(None),
        _auditor_outcome(AuditLog(max_entries=0)),
        _auditor_outcome(open_stream),
    ]

    assert outcomes == ["absent", "in-memory-only", "queued"]
    assert "durable" not in outcomes
    await open_stream.flush()


@pytest.mark.asyncio
async def test_record_detail_carries_stream_not_durable() -> None:
    """A record cannot attest its own durability; its row in SQLite can."""
    from probos.execution.audit import AUDIT_DETAIL_ALLOWLIST

    assert "durable" not in AUDIT_DETAIL_ALLOWLIST
    assert "stream" in AUDIT_DETAIL_ALLOWLIST

    sink = _RecordingSink()
    log = AuditLog(max_entries=0)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    _auditor_outcome(log)
    await log.flush()
    queued = json.loads(log.entries[-1].detail)

    memory_only = AuditLog(max_entries=0)
    _auditor_outcome(memory_only)
    recorded = json.loads(memory_only.entries[-1].detail)

    assert queued["stream"] == "queued"
    assert recorded["stream"] == "memory-only"
    assert "durable" not in queued and "durable" not in recorded


@pytest.mark.asyncio
async def test_both_paths_suppress_queued_and_surface_in_memory_only(
    tmp_path: Path,
) -> None:
    """One test over BOTH result types, so a one-path fix cannot pass it.

    Revision 1 shipped a one-path change once. The comparison lives at
    ``tools/code_execution_tool.py`` and ``agents/code_runner.py`` and the two
    are one atomic edit: reverting either would emit a label on every healthy
    run, which trains the Captain to ignore the field.
    """
    sink = _RecordingSink()
    healthy = AuditLog(max_entries=0)
    healthy.attach_persistence(sink)  # type: ignore[arg-type]
    degraded = AuditLog(max_entries=0)

    tool_ok = await CodeExecutionTool(
        runtime=_tool_runtime(tmp_path / "a", audit=healthy),
    ).invoke({"code": "print('x')"}, {"agent_id": "ezri"})
    mesh_ok = await _mesh_agent(tmp_path / "b", audit=healthy).handle_intent(
        IntentMessage(intent="run_python", params={"code": "print('x')"}),
    )
    tool_bad = await CodeExecutionTool(
        runtime=_tool_runtime(tmp_path / "c", audit=degraded),
    ).invoke({"code": "print('x')"}, {"agent_id": "ezri"})
    mesh_bad = await _mesh_agent(tmp_path / "d", audit=degraded).handle_intent(
        IntentMessage(intent="run_python", params={"code": "print('x')"}),
    )

    assert tool_ok.output is not None and "audit" not in tool_ok.output
    assert mesh_ok is not None and mesh_ok.result is not None
    assert "audit" not in mesh_ok.result
    assert tool_bad.output is not None
    assert tool_bad.output["audit"] == "in-memory-only"
    assert mesh_bad is not None and mesh_bad.result is not None
    assert mesh_bad.result["audit"] == "in-memory-only"
    await healthy.flush()


@pytest.mark.asyncio
async def test_durable_stream_open_is_false_after_stream_breaks(
    tmp_path: Path,
) -> None:
    """Once the stream ends, every later run self-labels until restart."""
    persistence = await _open_persistence(tmp_path / "audit.db")
    breaking = _BreakingSink(persistence, break_at=0)
    log = AuditLog(max_entries=0, write_max_retries=0)
    log.attach_persistence(breaking)  # type: ignore[arg-type]
    try:
        assert log.durable_stream_open() is True
        log.append(category="code_execution", detail="e-0")
        await log.flush(timeout_seconds=5.0)

        assert log._stream_broken_at == 0
        assert log.durable_stream_open() is False
        assert _auditor_outcome(log) == "in-memory-only"
    finally:
        await persistence.stop()


# ===========================================================================
# Revision 3 -- drain placement.
# ===========================================================================

@pytest.mark.asyncio
async def test_phase_one_flush_leaves_registration_open(tmp_path: Path) -> None:
    """Phase 1 must NOT close registration.

    Pools, the intent bus, the knowledge store, the mesh services and the
    semantic layer all tear down after it, and every one can produce an
    audit-worthy event. Closing registration there would leave the most
    failure-prone stretch of the run the one stretch with no durable record.
    """
    from probos.startup.shutdown import _flush_audit_log

    persistence = await _open_persistence(tmp_path / "audit.db")
    log = AuditLog(max_entries=0)
    log.attach_persistence(persistence)
    try:
        log.append(category="code_execution", detail="before-phase-one")
        runtime = _drain_runtime(log, persistence)
        await _flush_audit_log(runtime)

        assert log._writer_closed is False
        assert log.durable_stream_open() is True
        assert runtime.audit_log_persistence is persistence

        log.append(category="code_execution", detail="during-teardown")
        await log.flush(timeout_seconds=5.0)
        assert [r.detail for r in await persistence.load_entries()] == [
            "before-phase-one", "during-teardown",
        ]
    finally:
        await asyncio.wait_for(log.drain(timeout_seconds=1.0), timeout=5.0)
        await persistence.stop()


class _SeamRegistry:
    def all(self) -> list:
        return []

    async def unregister(self, agent_id: str) -> None:
        return None

    @property
    def count(self) -> int:
        return 0


class _SeamSemanticLayer:
    """Stops between the two audit phases, and appends while doing so."""

    def __init__(self, log: AuditLog) -> None:
        self._log = log

    async def stop(self) -> None:
        self._log.append(category="code_execution", detail="stopped-late")


class _Absent:
    """Falsy stand-in for every runtime attribute this test does not provide.

    ``shutdown()`` mixes ``if runtime.x:`` guards with unguarded
    ``hasattr(...)``-then-call patterns, so plain ``None`` is not enough: the
    stand-in has to be falsy AND tolerate an attribute call or an await.
    """

    def __bool__(self) -> bool:
        return False

    def __getattr__(self, name: str) -> "_Absent":
        return _Absent()

    def __call__(self, *args: Any, **kwargs: Any) -> "_Absent":
        return _Absent()

    def __iter__(self) -> Any:
        return iter(())

    def __len__(self) -> int:
        return 0

    def __await__(self) -> Any:
        async def _nothing() -> None:
            return None

        return _nothing().__await__()


class _SeamRuntime:
    """Enough of a runtime for the REAL ``shutdown()`` to run end to end.

    Every attribute the teardown does not need answers ``_Absent``, so each
    ``if runtime.x:`` step is skipped. A MagicMock cannot stand in here: its
    auto-created attributes are truthy, so shutdown would try to await two
    hundred of them.
    """

    def __init__(self, *, data_dir: Path, log: AuditLog, persistence: Any) -> None:
        self._data_dir = data_dir
        self._started = True
        self._shutdown_started = False
        self._session_id = "ad1278-seam"
        self._start_time_wall = 0.0
        self._start_time = 0.0
        self.registry = _SeamRegistry()
        self.pools: dict = {}
        self.confab_probe_tasks: set = set()
        self.config = SimpleNamespace(
            memory=SimpleNamespace(
                shutdown_drain_timeout_s=1.0,
                shutdown_consolidation_timeout_s=1.0,
            ),
            security_infra=SecurityInfraConfig(),
        )
        self.audit_log = log
        self.audit_log_persistence = persistence
        self._semantic_layer = _SeamSemanticLayer(log)

    def __getattr__(self, name: str) -> Any:
        return _Absent()

    def close_confab_probe_scheduling(self) -> None:
        return None

    def emit_event(self, *args: Any, **kwargs: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_an_append_during_pool_teardown_reaches_disk(tmp_path: Path) -> None:
    """THE SEAM TEST: append during teardown -> row in SQLite.

    Phase 1 and the drain tests each prove one half. Only this one crosses the
    seam, and half-chain evidence -- every link correct, the chain dead -- is
    this repo's dominant defect shape. The rejected build closed registration
    ~138 lines before the pools, so this entry would have died in memory.
    """
    from probos.startup.shutdown import shutdown

    db_file = tmp_path / "audit.db"
    persistence = await _open_persistence(db_file)
    log = AuditLog(max_entries=0)
    log.attach_persistence(persistence)
    log.append(category="code_execution", detail="before-teardown")

    runtime = _SeamRuntime(data_dir=tmp_path, log=log, persistence=persistence)
    await shutdown(runtime, reason="ad1278-seam")

    # The premise: the late append actually happened, so a green assertion
    # below cannot come from a teardown that never reached the semantic layer.
    assert [e.detail for e in log.entries][-1] == "stopped-late"

    reopened = await _open_persistence(db_file)
    try:
        details = [r.detail for r in await reopened.load_entries()]
        assert details == ["before-teardown", "stopped-late"]
    finally:
        await reopened.stop()


# ===========================================================================
# Slice E -- BF-861 (#1331): what termination OWNS
#
# AD-1278 made the spill unbounded on purpose: dropping an entry that could not
# enter the queue would put back the chain hole the spill exists to prevent.
# That is the guarantee, and #1331 is its price -- 5,000 appends against a
# wedged sink held 5,000 entries at a cap of 3, because nothing above
# `_persisted_through` is evictable and the watermark never moves again.
#
# The fix is not "evict once the writer lets go". Two review rounds tried that
# and the second reproduced the defect it was fixing, because a bound that
# waits on the liveness of a wedged component is not a bound. Termination
# DISOWNS instead: it stops accounting for the in-flight batch, so the eviction
# predicate is `_stream_broken_at is not None` alone. Safe because eviction
# cannot reach that batch at all -- `_next_batch` holds it in its own list and
# `AuditEntry` is frozen, so `del self.entries[:n]` drops slots, not entries.
# `test_eviction_does_not_take_the_in_flight_batch_off_the_disk` is the proof.
# ===========================================================================

class _ModalSink:
    """One sink whose behaviour is switchable while the writer holds a batch.

    Every BF-861 case needs the sink to stop answering while appends pile up
    and THEN do something specific -- keep hanging, start refusing, or catch
    up. Three separate sinks would each have to be re-wedged from scratch, and
    the state that matters (which batch is in flight) does not survive that.
    """

    def __init__(self, mode: str = "wedge") -> None:
        self.mode = mode
        self.entered = asyncio.Event()
        self.gate = asyncio.Event()
        self.seen: list[list[int]] = []
        self.persisted: list[int] = []

    async def persist_entries(self, entries: Any) -> list[int]:
        rows = list(entries)
        self.seen.append([e.sequence for e in rows])
        self.entered.set()
        if self.mode == "wedge":
            await self.gate.wait()
        if self.mode == "refuse":
            raise RuntimeError("the sink is refusing")
        self.persisted.extend(e.sequence for e in rows)
        if self.mode == "partial":
            # Wrote them all, confirmed only the last. `_advance_persisted`
            # refuses the resulting jump, so the watermark STOPS while the
            # writer's batch head keeps climbing -- the only way the two
            # termination call sites report different sequences.
            return [rows[-1].sequence]
        return [e.sequence for e in rows]


async def _wedge_the_writer(log: AuditLog, sink: _ModalSink) -> None:
    """Append one entry and leave the writer blocked inside the sink.

    Every case below needs the writer HOLDING a batch, because that is what
    makes the queue back up and the spill grow. Without it the appends drain
    and nothing under test is ever reached.
    """
    log.append(category="code_execution", detail="held-by-the-writer")
    await asyncio.wait_for(sink.entered.wait(), timeout=5.0)


@pytest.mark.asyncio
async def test_the_spill_is_bounded_by_ending_the_stream_not_by_dropping() -> None:
    """At the ceiling the stream ENDS; nothing is shed from an open one.

    The distinction is the whole design. Shedding would bound memory too, and
    would restore exactly the hole BF-780 exists to prevent -- the next
    persisted row chained to a row that is not there, reported as tampering at
    every future boot. Ending says where the chain stops instead.
    """
    sink = _ModalSink()
    log = AuditLog(max_entries=0, write_queue_maxsize=1, spill_maxsize=5)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    await _wedge_the_writer(log, sink)

    for i in range(200):
        log.append(category="code_execution", detail=f"pressure-{i}")

    # The premise: the queue really did overflow. Without this a build that
    # never spills would pass every assertion below.
    assert log._spilled >= 1, "the queue never overflowed; this proves nothing"
    assert log._stream_broken_at is not None
    assert len(log._spill) <= 5
    assert log.durable_stream_open() is False
    # Ended, not shed: the in-memory chain is still whole and contiguous.
    assert [e.sequence for e in log.entries] == list(range(201))
    assert log.verify_chain() is True

    await asyncio.wait_for(log.drain(timeout_seconds=0.05), timeout=5.0)


@pytest.mark.asyncio
async def test_a_terminated_stream_lets_the_cap_apply_again() -> None:
    """#1331 itself. 5,000 appends at a cap of 3 must leave 3.

    Measured on HEAD: 5000. Nothing above ``_persisted_through`` is evictable
    and a terminated stream never advances that watermark again, so the cap
    became decorative at exactly the moment memory started growing without
    limit.
    """
    sink = _ModalSink()
    log = AuditLog(max_entries=3, write_queue_maxsize=1, spill_maxsize=5)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    await _wedge_the_writer(log, sink)

    for i in range(4_999):
        log.append(category="code_execution", detail=f"n-{i}")

    assert len(log.entries) == 3
    assert log._stream_broken_at is not None
    # Bounded AND still verifiable: a cap that made every boot cry tamper
    # would be worse than no cap.
    assert log.verify_chain() is True
    assert log.chain_state()[0] == "truncated"

    await asyncio.wait_for(log.drain(timeout_seconds=0.05), timeout=5.0)


@pytest.mark.asyncio
async def test_eviction_does_not_take_the_in_flight_batch_off_the_disk() -> None:
    """The crux. An evicted entry still reaches the sink when it recovers.

    Two review rounds asked to gate eviction on writer state to protect this
    batch. It needs no protecting: ``_next_batch`` copied it into its own list
    and ``AuditEntry`` is frozen, so ``del self.entries[:n]`` drops list slots
    and the writer's references are untouched. This is the regression guard
    against a future "protect the writer" gate, which would trade a real memory
    bound for a hazard that does not exist.
    """
    sink = _ModalSink()
    log = AuditLog(max_entries=3, write_queue_maxsize=1, spill_maxsize=5)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    await _wedge_the_writer(log, sink)
    held = list(sink.seen[0])
    assert held == [0], sink.seen

    for i in range(50):
        log.append(category="code_execution", detail=f"n-{i}")

    writer = log._writer_task
    assert writer is not None
    assert log._stream_broken_at is not None
    assert len(log.entries) == 3
    # The premise: eviction really did pass the in-flight sequence. If it is
    # still in `entries` the release below proves nothing.
    assert held[0] not in [e.sequence for e in log.entries]

    sink.gate.set()
    await asyncio.wait({writer}, timeout=5.0)

    assert writer.done(), "the writer never finished its disowned batch"
    assert sink.persisted == held
    # Contiguous from genesis: the disk chain ends cleanly rather than gaining
    # the hole the spill exists to prevent.
    assert sink.persisted == list(range(len(sink.persisted)))

    await asyncio.wait_for(log.drain(timeout_seconds=0.05), timeout=5.0)


def test_finalize_passes_the_ceiling_through() -> None:
    """BF-861: the operator's ceiling has to reach the log.

    A source scan because the two defaults are the SAME number: drop the kwarg
    and every behavioural test still passes, while an operator who lowered
    ``audit_spill_maxsize`` is silently ignored. That is the whole failure
    mode, and it is invisible to anything that runs at defaults.
    """
    from probos.startup import finalize as finalize_mod

    source = inspect.getsource(finalize_mod.finalize_startup)
    assert "spill_maxsize=config.security_infra.audit_spill_maxsize" in source
    # Both ends of that seam, too: a dataclass default below the config default
    # would silently un-bound every `AuditLog()` built outside finalize.
    assert AuditLog().spill_maxsize == SecurityInfraConfig().audit_spill_maxsize


@pytest.mark.asyncio
async def test_a_terminated_log_reports_no_unflushed_tail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The loss is announced ONCE, by the termination, naming its cause.

    ``drain`` counts what the log still ACCOUNTS FOR, and termination disowned
    the in-flight batch, so that count is zero and shutdown files no second
    report for a loss already explained. Without the disown ``drain`` reports a
    tail it can never resolve, because the writer it is counting is the wedged
    one -- and reports it with a different cause than the real one.

    This is the disown's only unmasked effect. ``_enforce_cap`` keys on
    termination alone and ``_await_quiescent`` has its own terminated-stream
    early return, so both of those stay green with the disown removed.
    """
    sink = _ModalSink()
    log = AuditLog(max_entries=0, write_queue_maxsize=1, spill_maxsize=3)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    await _wedge_the_writer(log, sink)

    for i in range(8):
        log.append(category="code_execution", detail=f"n-{i}")

    assert log._stream_broken_at is not None
    # The premise: the writer is still inside the sink holding its batch, so a
    # zero below comes from the disown and not from an idle writer.
    assert sink.seen == [[0]], sink.seen
    assert sink.persisted == []

    caplog.set_level(logging.ERROR, logger="probos.security.audit")
    unflushed = await asyncio.wait_for(
        log.drain(timeout_seconds=0.2), timeout=10.0,
    )

    assert unflushed == 0
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert not any("audit drain expired" in m for m in errors), errors


def test_termination_is_forward_only() -> None:
    """First termination wins. This number is where the disk chain ends.

    A direct call because the ordinary path cannot discriminate this: once the
    ceiling reports ``_persisted_through + 1`` the two call sites report the
    SAME quantity by construction -- ``persist_entries`` is all-or-nothing and
    ``_advance_persisted`` walks contiguously, so ``batch[0].sequence`` IS
    ``_persisted_through + 1``. Measured on the fixed build: ceiling 0 then
    refusal 0 on a cold log, 1 then 1 after one confirmed batch. The
    divergence that IS reachable is pinned by the test below this one.
    """
    log = AuditLog(max_entries=0)

    log._terminate_stream(7, "the spill ceiling")
    assert log._stream_broken_at == 7

    log._terminate_stream(2, "a refusing sink")
    assert log._stream_broken_at == 7

    log._terminate_stream(99, "another refusing sink")
    assert log._stream_broken_at == 7


@pytest.mark.asyncio
async def test_a_later_termination_cannot_overstate_where_the_chain_ended() -> None:
    """The forward-only guard against the divergence that is actually reachable.

    An under-reporting sink -- one that writes a batch but confirms only part
    of it -- makes ``_advance_persisted`` refuse the jump, so the watermark
    stops while the writer's batch head climbs. The ceiling then names the
    true end while a later refusal would name a much higher sequence, claiming
    everything between them reached disk. Measured without the guard: ceiling
    1, refusal 4, final 4.
    """
    sink = _ModalSink(mode="serve")
    log = AuditLog(
        max_entries=0, write_queue_maxsize=4, spill_maxsize=3,
        write_max_retries=0,
    )
    log.attach_persistence(sink)  # type: ignore[arg-type]

    log.append(category="code_execution", detail="seed")
    await log.flush(timeout_seconds=5.0)
    assert log._persisted_through == 0

    sink.mode = "partial"
    for i in range(3):
        log.append(category="code_execution", detail=f"p-{i}")
    await log.flush(timeout_seconds=5.0)
    # The premise: the watermark really did stall. Without this the batch head
    # and `_persisted_through + 1` stay equal and the guard is untestable.
    assert log._persisted_through == 0, "the watermark did not stall"

    sink.mode = "wedge"
    sink.entered.clear()
    log.append(category="code_execution", detail="held")
    await asyncio.wait_for(sink.entered.wait(), timeout=5.0)
    held = list(sink.seen[-1])
    assert held[0] > log._persisted_through + 1, (held, log._persisted_through)

    for i in range(12):
        log.append(category="code_execution", detail=f"n-{i}")
    ceiling = log._stream_broken_at
    assert ceiling == log._persisted_through + 1

    writer = log._writer_task
    assert writer is not None
    sink.mode = "refuse"
    sink.gate.set()
    await asyncio.wait({writer}, timeout=5.0)

    assert log._stream_broken_at == ceiling, (
        f"a later refusal moved the reported end to {log._stream_broken_at}, "
        f"claiming sequences {ceiling}-{log._stream_broken_at} reached disk"
    )

    await asyncio.wait_for(log.drain(timeout_seconds=0.05), timeout=5.0)


@pytest.mark.asyncio
async def test_the_reported_end_never_overstates_the_durable_end() -> None:
    """``_stream_broken_at`` may understate durability; it may never overstate.

    Terminating also DISCARDS the write queue, whose sequences sit BELOW the
    spill's. Reporting the spill head would therefore claim those queued
    sequences reached disk -- overstating the durable end by up to
    ``write_queue_maxsize``, which defaults to 1000.
    """
    sink = _ModalSink()
    log = AuditLog(max_entries=0, write_queue_maxsize=1, spill_maxsize=3)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    await _wedge_the_writer(log, sink)

    for i in range(8):
        log.append(category="code_execution", detail=f"n-{i}")

    broken_at = log._stream_broken_at
    assert broken_at is not None
    writer = log._writer_task
    assert writer is not None

    sink.gate.set()
    await asyncio.wait({writer}, timeout=5.0)

    appended = [e.sequence for e in log.entries]
    missing = sorted(set(appended) - set(sink.persisted))
    # The premise: something really was lost, or an overstatement is
    # unobservable and this test is green for the wrong reason.
    assert missing, f"nothing was lost; persisted={sink.persisted}"
    assert broken_at <= missing[0], (
        f"reported the chain ending at {broken_at} while sequence "
        f"{missing[0]} never reached the sink"
    )

    await asyncio.wait_for(log.drain(timeout_seconds=0.05), timeout=5.0)


@pytest.mark.asyncio
async def test_a_zero_ceiling_restores_the_unbounded_buffer() -> None:
    """The documented opt-out. ``<= 0`` is the pre-BF-861 behaviour, verbatim."""
    sink = _ModalSink()
    log = AuditLog(max_entries=0, write_queue_maxsize=1, spill_maxsize=0)
    log.attach_persistence(sink)  # type: ignore[arg-type]
    await _wedge_the_writer(log, sink)

    for i in range(200):
        log.append(category="code_execution", detail=f"pressure-{i}")

    assert log._stream_broken_at is None
    assert len(log._spill) > 100
    assert log.durable_stream_open() is True

    await asyncio.wait_for(log.drain(timeout_seconds=0.05), timeout=5.0)


@pytest.mark.asyncio
async def test_the_ceiling_does_not_fire_while_the_sink_keeps_up() -> None:
    """No false termination. It is BACKLOG that ends the stream, never volume.

    Sixty appends past a ceiling of four, spilling on every burst and never
    more than two behind. A ceiling that counted total overflows rather than
    the live buffer would end a perfectly healthy stream here.
    """
    sink = _ModalSink(mode="serve")
    log = AuditLog(max_entries=0, write_queue_maxsize=1, spill_maxsize=4)
    log.attach_persistence(sink)  # type: ignore[arg-type]

    for burst in range(20):
        for i in range(3):
            log.append(category="code_execution", detail=f"k-{burst}-{i}")
        await log.flush(timeout_seconds=5.0)

    # The premise: the spill was exercised on nearly every burst, so this
    # measures a ceiling that held rather than one that was never approached.
    assert log._spilled >= 20, log._spilled
    assert log._stream_broken_at is None
    assert log.durable_stream_open() is True
    assert sorted(sink.persisted) == list(range(60))
    assert log.verify_chain() is True

    await asyncio.wait_for(log.drain(timeout_seconds=0.05), timeout=5.0)
