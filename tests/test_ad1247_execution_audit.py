"""AD-1247: a per-execution audit record that can be trusted.

BF-763 (#1221) removed a false consensus claim from the execution paths. The
Captain's decision was to replace it with accountability rather than a gate:
*"give run_python the same amount of autonomy that you have."* A foreground
coding agent's freedom is paid for by a human watching; an unattended agent's is
paid for by a record afterwards. That trade only holds if the record is
trustworthy, so an unreliable one is worse than an acknowledged absence.

The record is written by ``CodeExecutionTool`` (the AGENTIC path). The mesh
``CodeRunnerAgent`` path is explicitly NOT covered -- see the module docstrings,
which say so, and BF-787.

Five defects an earlier revision had, each with a test below:

1. ``launched`` was set before ``sandbox.run()``. ``run()`` only QUEUES work --
   ``Popen`` happens later inside the executor -- so records were produced for
   runs that never started. Now keyed off a ``threading.Event`` the sandbox sets
   after ``Popen`` returns.
2. A failure AFTER the normal audit wrote a second record, so one execution
   looked like two.
3. The fallback records dropped ``success`` / ``exit_code`` / ``timed_out``
   because ``res`` was scoped inside the ``try``.
4. ``fetch_broker`` was only asserted on the cancellation path, so a mutant
   forcing it False on every success left the suite green.
5. With no audit sink the record vanishes silently, and a test pinned that
   fail-open as correct.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos.tools.code_execution_tool as mod_tool
from probos.execution.isolation import (
    ExecutionRequest,
    ExecutionResult,
    LaunchOutcome,
    SubprocessSandbox,
)
from probos.execution.audit import AUDIT_DETAIL_ALLOWLIST
from probos.tools.code_execution_tool import CodeExecutionTool


class _Audit:
    """The real ``AuditLog`` surface: keyword-only ``append``.

    ``append`` only STORES. Validation lives in ``records`` because ``_audit``
    wraps the append in ``except Exception`` -- and ``AssertionError`` is an
    ``Exception``, so a check raised from inside ``append`` is swallowed by
    production code and the guard is inert. A mutation proved exactly that.
    Validating in the property means every test that reads ``.records``,
    including the ones asserting it is EMPTY, enforces the invariant.
    """

    def __init__(self) -> None:
        self.entries: list[tuple[str, dict[str, Any]]] = []

    def append(self, *, category: str, detail: str) -> None:
        self.entries.append((category, json.loads(detail)))

    @property
    def records(self) -> list[dict[str, Any]]:
        found = [d for c, d in self.entries if c == "code_execution"]
        for payload in found:
            assert "execution_id" in payload, f"record without an id: {payload}"
            assert len(payload["execution_id"]) == 32, payload["execution_id"]
            assert payload.get("launch_state") in ("launched", "unknown"), payload
        return found


def _runtime(tmp_path: Path, *, audit: Any, **exec_kw: Any) -> Any:
    cfg = SimpleNamespace(
        enabled=True,
        scratch_dir=str(tmp_path / "scratch"),
        timeout_seconds=30,
        max_output_bytes=65536,
        max_memory_mb=512,
        stage_thread_artifacts=False,
        fetch_broker_enabled=False,
        persistent_workspaces=False,
        **exec_kw,
    )
    return SimpleNamespace(
        config=SimpleNamespace(execution=cfg, dependency=None),
        audit_log=audit,
        agent_registry=None,
        artifact_store=None,
    )


async def _invoke(tool: CodeExecutionTool, code: str) -> Any:
    return await tool.invoke({"code": code}, {"agent_id": "ezri"})


# ── 1. the launch signal ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_sandbox_signals_launch_only_after_popen(tmp_path):
    """The signal must mean "a child exists", not "we intended one"."""
    launch = LaunchOutcome()
    sandbox = SubprocessSandbox(scratch_root=str(tmp_path))

    res = await sandbox.run(
        ExecutionRequest(
            code="print('ran')",
            workdir=tmp_path / "wd",
            timeout_seconds=30,
            launch_outcome=launch,
        )
    )

    assert res.success is True
    assert launch.launched is True
    assert launch.resolved.is_set() is True


@pytest.mark.asyncio
async def test_the_launch_question_resolves_at_popen_not_at_completion(tmp_path):
    """``resolved`` must mean "the answer is known", not "the run finished".

    An earlier revision set it only in the wrapper's ``finally``, so a caller
    unwinding beside a long-running child blocked for its entire bounded wait
    even though the answer was available the moment ``Popen`` returned.

    Asserted while the child is STILL RUNNING, which is the only window where
    the two timings differ.
    """
    launch = LaunchOutcome()
    sandbox = SubprocessSandbox(scratch_root=str(tmp_path))

    task = asyncio.create_task(
        sandbox.run(
            ExecutionRequest(
                code="import time; time.sleep(3)",
                workdir=tmp_path / "wd",
                timeout_seconds=30,
                launch_outcome=launch,
            )
        )
    )
    # Wait for the answer, but far less than the child's lifetime.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, launch.resolved.wait, 10.0)

    assert launch.resolved.is_set() is True
    assert launch.launched is True
    assert not task.done(), "resolved fired only after the run completed"

    await task


@pytest.mark.asyncio
async def test_a_failure_to_spawn_resolves_as_not_launched(tmp_path):
    """A missing executable never reaches Popen's return.

    This is the case that produced a record for a run that never happened: the
    old code set its flag before awaiting, so a process that failed to spawn was
    indistinguishable from one that ran. The question must still be ANSWERED --
    ``resolved`` set by the wrapper's ``finally``, ``launched`` false -- or a
    caller waiting on it would burn its whole bound.
    """
    launch = LaunchOutcome()
    sandbox = SubprocessSandbox(scratch_root=str(tmp_path))

    res = await sandbox.run(
        ExecutionRequest(
            argv=[str(tmp_path / "definitely-not-an-executable")],
            workdir=tmp_path / "wd",
            timeout_seconds=30,
            launch_outcome=launch,
        )
    )

    assert res.success is False
    assert launch.launched is False
    assert launch.resolved.is_set() is True


@pytest.mark.asyncio
async def test_an_unusable_request_still_resolves_the_launch_question(tmp_path):
    """Neither code nor argv returns early -- `resolved` must still be set.

    An early return that skipped the handshake would make the caller's bounded
    wait burn its full timeout on every malformed request.
    """
    launch = LaunchOutcome()
    sandbox = SubprocessSandbox(scratch_root=str(tmp_path))

    res = await sandbox.run(
        ExecutionRequest(workdir=tmp_path / "wd", launch_outcome=launch)
    )

    assert res.success is False
    assert launch.launched is False
    assert launch.resolved.is_set() is True


@pytest.mark.asyncio
async def test_a_timed_out_run_still_counts_as_launched(tmp_path):
    """The child existed and did work; the kill path must not erase that."""
    launch = LaunchOutcome()
    sandbox = SubprocessSandbox(scratch_root=str(tmp_path))

    res = await sandbox.run(
        ExecutionRequest(
            code="import time; time.sleep(30)",
            workdir=tmp_path / "wd",
            timeout_seconds=1.0,
            launch_outcome=launch,
        )
    )

    assert res.timed_out is True
    assert launch.launched is True


@pytest.mark.asyncio
async def test_a_request_without_an_outcome_still_runs(tmp_path):
    """Every existing caller passes none; they must be unaffected."""
    sandbox = SubprocessSandbox(scratch_root=str(tmp_path))

    res = await sandbox.run(
        ExecutionRequest(code="print('ok')", workdir=tmp_path / "wd", timeout_seconds=30)
    )

    assert res.success is True


@pytest.mark.asyncio
async def test_a_run_that_never_starts_produces_no_record(tmp_path, monkeypatch):
    """Acceptance 1. A queued-but-never-started run is not an execution."""
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    async def _never_launches(self, request):
        # Faithful to the real contract: run() returns a result and simply
        # never sets the signal, exactly as a spawn failure does.
        return ExecutionResult(success=False, error="boom", workdir=str(request.workdir))

    monkeypatch.setattr(SubprocessSandbox, "run", _never_launches)

    await _invoke(tool, "print('x')")

    assert audit.records == []


# ── 2. exactly one record ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_successful_run_produces_exactly_one_record(tmp_path):
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    result = await _invoke(tool, "print('hello')")

    assert result.error is None
    assert len(audit.records) == 1
    rec = audit.records[0]
    assert rec["agent_id"] == "ezri"
    assert rec["success"] is True
    assert rec["exit_code"] == 0
    assert rec["timed_out"] is False


@pytest.mark.asyncio
async def test_a_failure_after_the_audit_does_not_add_a_second(tmp_path, monkeypatch):
    """Acceptance 2. One execution must never appear as two runs.

    ``_unimportable_summary`` runs AFTER the normal audit, so an exception there
    took the `except` branch, which checked `launched` but not `not audited`.
    """
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    def _boom(self, code):
        raise RuntimeError("after the audit")

    monkeypatch.setattr(CodeExecutionTool, "_unimportable_summary", _boom)

    result = await _invoke(tool, "print('hello')")

    assert result.error is not None
    assert len(audit.records) == 1, "one execution, one record"


# ── 3. the fallback carries what was known ─────────────────────────────────

@pytest.mark.asyncio
async def test_a_late_failure_keeps_the_fields_already_known(tmp_path, monkeypatch):
    """Acceptance 3. `res` existed; the record must not fall back to defaults."""
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    async def _boom(self, *a, **kw):
        raise RuntimeError("artifact capture died")

    monkeypatch.setattr(CodeExecutionTool, "_capture_artifacts", _boom)

    await _invoke(tool, "print('hello')")

    assert len(audit.records) == 1
    rec = audit.records[0]
    assert rec["error_type"] == "RuntimeError"
    # The child ran and exited 0 -- that is known and must survive.
    assert rec["success"] is True
    assert rec["exit_code"] == 0
    assert rec["timed_out"] is False


@pytest.mark.asyncio
async def test_cancellation_after_a_launched_run_is_recorded(tmp_path, monkeypatch):
    """Acceptance 5. The fake must NOT satisfy this by raising immediately.

    The old cancellation test used a sandbox that raised before doing anything,
    so it could not tell queued from launched and pinned the defect as contract.
    Here the sandbox genuinely sets the launch signal first.
    """
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    async def _launch_then_cancel(self, request):
        if request.launch_outcome is not None:
            request.launch_outcome.launched = True
            request.launch_outcome.resolved.set()
        raise asyncio.CancelledError()

    monkeypatch.setattr(SubprocessSandbox, "run", _launch_then_cancel)

    with pytest.raises(asyncio.CancelledError):
        await _invoke(tool, "print('x')")

    assert len(audit.records) == 1
    assert audit.records[0]["error_type"] == "cancelled"


@pytest.mark.asyncio
async def test_cancellation_before_launch_is_not_recorded(tmp_path, monkeypatch):
    """The other half of acceptance 5, and the one the old fake could not see."""
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    async def _cancel_while_queued(self, request):
        if request.launch_outcome is not None:
            request.launch_outcome.resolved.set()
        raise asyncio.CancelledError()

    monkeypatch.setattr(SubprocessSandbox, "run", _cancel_while_queued)

    with pytest.raises(asyncio.CancelledError):
        await _invoke(tool, "print('x')")

    assert audit.records == []


# ── 4. fetch_broker on the success path ────────────────────────────────────

@pytest.mark.asyncio
async def test_a_cancellation_during_the_launch_window_still_records(tmp_path):
    """The race that produced an executed script with ZERO records.

    ``run_in_executor`` does not stop when the awaiting task is cancelled, so a
    child can be created AFTER the tool's ``finally`` has already looked. Reading
    a bare flag at that moment reports "never ran" for a script that is about to
    run -- the one failure an audit trail must not have.

    Here the sandbox resolves the launch outcome only after a delay, exactly as
    a real thread that has not reached ``Popen`` yet would.
    """
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))
    started = threading.Event()

    async def _slow_launch(_self, request):
        started.set()

        def _worker():
            time.sleep(0.3)
            request.launch_outcome.launched = True
            request.launch_outcome.resolved.set()

        threading.Thread(target=_worker, daemon=True).start()
        await asyncio.sleep(30)  # never completes; the caller cancels us
        return ExecutionResult(success=True)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(SubprocessSandbox, "run", _slow_launch)
        task = asyncio.create_task(_invoke(tool, "print('x')"))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert len(audit.records) == 1, "a launched child must not vanish from the trail"
    assert audit.records[0]["error_type"] == "cancelled"
    assert audit.records[0]["launch_state"] == "launched"


@pytest.mark.asyncio
async def test_an_unresolved_launch_is_recorded_as_unknown(tmp_path, caplog):
    """The bound expired, so neither answer is available.

    Recording nothing would silently drop a run that may be about to start;
    recording it as launched would assert something unverified. The third option
    is the honest one -- write the record and SAY the launch is unconfirmed.
    """
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))
    started = threading.Event()

    async def _never_resolves(_self, request):
        started.set()
        await asyncio.sleep(30)
        return ExecutionResult(success=True)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(SubprocessSandbox, "run", _never_resolves)
        mp.setattr(mod_tool, "_LAUNCH_RESOLVE_SECONDS", 0.05)
        task = asyncio.create_task(_invoke(tool, "print('x')"))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5.0)
        with caplog.at_level(logging.WARNING, logger="probos.tools.code_execution_tool"):
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    assert len(audit.records) == 1, "an unconfirmed run must not be dropped"
    assert audit.records[0]["launch_state"] == "unknown"
    assert any("launch_state=unknown" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_hostile_broker_teardown_still_removes_the_workdir(tmp_path):
    """A BaseException from ``broker.stop()`` must not leak the scratch dir.

    ``rmtree`` sat sequentially after the broker shutdown, so a teardown that
    raised skipped it. One audit record, one leftover workdir.
    """

    class _HostileBroker:
        async def stop(self):
            raise KeyboardInterrupt("teardown exploded")

    audit = _Audit()
    scratch = tmp_path / "scratch"
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    async def _fake_broker(self, cfg, workdir):
        return ({}, _HostileBroker())

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(CodeExecutionTool, "_start_fetch_broker", _fake_broker)
        with pytest.raises(KeyboardInterrupt):
            await _invoke(tool, "print('hello')")

    leftover = list(scratch.glob("exec-*")) if scratch.exists() else []
    assert leftover == [], f"workdir leaked: {leftover}"


@pytest.mark.asyncio
async def test_a_sink_that_raises_baseexception_does_not_double_record(tmp_path):
    """The real ``AuditLog`` appends and THEN emits an event.

    A listener raising ``BaseException`` there leaves the entry written but
    unwinds past the flag, so a `finally` keyed off "did the call return" writes
    a second record for one execution. The flag is therefore set BEFORE the
    append, not after.
    """

    class _AppendThenExplode:
        def __init__(self) -> None:
            self.entries: list[tuple[str, dict[str, Any]]] = []

        def append(self, *, category: str, detail: str) -> None:
            self.entries.append((category, json.loads(detail)))
            raise asyncio.CancelledError()  # a BaseException, like a real listener

        @property
        def records(self) -> list[dict[str, Any]]:
            return [d for c, d in self.entries if c == "code_execution"]

    audit = _AppendThenExplode()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    with pytest.raises(asyncio.CancelledError):
        await _invoke(tool, "print('hello')")

    assert len(audit.records) == 1, "one execution, one record"


@pytest.mark.asyncio
async def test_the_workdir_is_cleaned_even_when_the_sink_explodes(tmp_path):
    """An audit write must not become two new defects.

    The audit call sits in its own nested ``try/finally`` so a sink that raises
    cannot skip the broker teardown and the workdir removal below it.
    """

    class _Explode:
        def append(self, **_kw: Any) -> None:
            raise asyncio.CancelledError()

    scratch = tmp_path / "scratch"
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=_Explode()))

    with pytest.raises(asyncio.CancelledError):
        await _invoke(tool, "print('hello')")

    leftover = list(scratch.glob("exec-*")) if scratch.exists() else []
    assert leftover == [], f"workdir leaked: {leftover}"


@pytest.mark.asyncio
async def test_a_partial_capture_omits_artifact_count_rather_than_lying(
    tmp_path, monkeypatch
):
    """Zero is a claim. Absence is not.

    A run torn down partway through artifact capture had already persisted one
    artifact while the record said ``artifact_count: 0``. An acknowledged
    absence beats a false count -- that is this AD's whole premise.
    """
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    async def _die_mid_capture(self, *a, **kw):
        raise RuntimeError("capture interrupted")

    monkeypatch.setattr(CodeExecutionTool, "_capture_artifacts", _die_mid_capture)

    await _invoke(tool, "print('hello')")

    assert len(audit.records) == 1
    assert "artifact_count" not in audit.records[0]
    # The fields that WERE known still survive.
    assert audit.records[0]["success"] is True


@pytest.mark.asyncio
async def test_every_record_carries_an_execution_correlation_id(tmp_path):
    """Audit sequence identifies a ROW, not the invocation it represents.

    Without a correlation key, two identical runs by the same agent produce
    indistinguishable records and cannot be reconciled after the fact.
    """
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    await _invoke(tool, "print('a')")
    await _invoke(tool, "print('a')")

    ids = [r["execution_id"] for r in audit.records]
    assert len(ids) == 2
    assert len(set(ids)) == 2, "each invocation needs its own id"
    assert all(len(i) == 32 for i in ids)


@pytest.mark.asyncio
async def test_fetch_broker_is_false_on_a_plain_successful_run(tmp_path):
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    await _invoke(tool, "print('hello')")

    assert audit.records[0]["fetch_broker"] is False


@pytest.mark.asyncio
async def test_fetch_broker_is_true_on_a_successful_brokered_run(tmp_path, monkeypatch):
    """Acceptance 4. A mutant forcing this False on success used to survive."""
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    async def _fake_broker(self, cfg, workdir):
        return ({"PROBOS_FETCH_URL": "http://127.0.0.1:1"}, None)

    monkeypatch.setattr(CodeExecutionTool, "_start_fetch_broker", _fake_broker)

    await _invoke(tool, "print('hello')")

    assert len(audit.records) == 1
    assert audit.records[0]["fetch_broker"] is True
    assert audit.records[0]["success"] is True


# ── 5. the absent sink is allowed but never silent ─────────────────────────

@pytest.mark.asyncio
async def test_no_sink_does_not_fail_the_execution(tmp_path, caplog):
    """Acceptance 6. Auditing must not become a new way to lose work."""
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=None))

    with caplog.at_level(logging.WARNING, logger="probos.tools.code_execution_tool"):
        result = await _invoke(tool, "print('hello')")

    assert result.error is None
    assert result.output["success"] is True


@pytest.mark.asyncio
async def test_no_sink_is_reported_not_swallowed(tmp_path, caplog):
    """The absence is permitted; being SILENT about it is not."""
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=None))

    with caplog.at_level(logging.WARNING, logger="probos.tools.code_execution_tool"):
        await _invoke(tool, "print('hello')")

    warnings = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "AD-1247" in r.getMessage()
    ]
    assert warnings, "an untrailed execution must be visible in the log"
    assert "audit_enabled" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_the_absence_warning_does_not_repeat(tmp_path, caplog):
    """A long-running vessel must not have its log filled by this."""
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=None))

    with caplog.at_level(logging.WARNING, logger="probos.tools.code_execution_tool"):
        await _invoke(tool, "print('a')")
        await _invoke(tool, "print('b')")
        await _invoke(tool, "print('c')")

    warnings = [r for r in caplog.records if "AD-1247" in r.getMessage()]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_a_failing_sink_does_not_fail_the_execution(tmp_path):
    class _BrokenAudit:
        def append(self, **_kw: Any) -> None:
            raise RuntimeError("sink is down")

    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=_BrokenAudit()))

    result = await _invoke(tool, "print('hello')")

    assert result.error is None
    assert result.output["success"] is True


# ── 7. the record's shape ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_source_is_recorded_as_a_digest_never_as_text(tmp_path):
    """Acceptance 7. Code an agent runs can carry credentials it was given."""
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))
    secret = "SUPER_SECRET_TOKEN_ab12cd34"

    await _invoke(tool, f"print('{secret}')")

    blob = json.dumps(audit.entries)
    assert secret not in blob
    rec = audit.records[0]
    assert len(rec["code_sha256"]) == 64
    assert rec["code_chars"] > 0


@pytest.mark.asyncio
async def test_the_digest_is_the_real_hash_and_distinguishes_scripts(tmp_path):
    """A digest that is a constant is not a digest.

    Asserting only "64 hex characters" let a mutation replacing every hash with
    64 zeros pass the whole suite -- every script would become
    indistinguishable in the trail while the audit tests stayed green. That is
    an audit-integrity failure the suite was supposed to catch.
    """
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))
    first, second = "print('alpha')", "print('beta')"

    await _invoke(tool, first)
    await _invoke(tool, second)

    digests = [r["code_sha256"] for r in audit.records]
    assert digests[0] == hashlib.sha256(first.encode("utf-8")).hexdigest()
    assert digests[1] == hashlib.sha256(second.encode("utf-8")).hexdigest()
    assert digests[0] != digests[1]


@pytest.mark.asyncio
async def test_a_failure_before_the_sandbox_records_nothing_and_does_not_stall(
    tmp_path, monkeypatch
):
    """Nothing was submitted, so "unknown" would not be uncertain -- it is a no.

    The bounded wait was unconditional, so a failure BEFORE ``sandbox.run`` was
    ever called blocked the loop for the full 2s and then wrote a record saying
    a script may have run. Neither was true: no worker existed.
    """
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    async def _die_early(self, *a, **kw):
        raise RuntimeError("failed before the sandbox")

    monkeypatch.setattr(CodeExecutionTool, "_maybe_install_missing", _die_early)

    started = time.monotonic()
    result = await _invoke(tool, "print('x')")
    elapsed = time.monotonic() - started

    assert result.error is not None
    assert audit.records == []
    assert elapsed < 1.0, f"the pre-sandbox path waited {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_the_record_carries_only_allowlisted_keys(tmp_path):
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    await _invoke(tool, "print('hello')")

    assert set(audit.records[0]) <= AUDIT_DETAIL_ALLOWLIST


@pytest.mark.asyncio
async def test_the_allowlist_actually_filters(tmp_path, monkeypatch):
    """Prove the filter RUNS, not merely that today's keys happen to comply.

    Every key `_audit` builds is already allowlisted, so deleting the filter
    changes no current output and a mutation removing it survives. The filter
    exists for the key a future edit adds without updating the allowlist -- so
    the test has to create that situation rather than wait for it.
    The filter now lives in the shared builder (AD-1280), so the patch has to
    reach `probos.execution.audit` -- patching the re-export on the tool module
    would no longer touch the production read, and the test would pass while
    proving nothing. The assertions are unchanged: softening them would pin the
    removal of a security filter as contract.
    """
    import probos.execution.audit as mod

    narrowed = frozenset(AUDIT_DETAIL_ALLOWLIST - {"code_sha256"})
    monkeypatch.setattr(mod, "AUDIT_DETAIL_ALLOWLIST", narrowed)

    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    await _invoke(tool, "print('hello')")

    rec = audit.records[0]
    assert "code_sha256" not in rec
    # ...and the still-allowed keys survived, so this is filtering and not a
    # blanket wipe.
    assert "execution_id" in rec
    assert "agent_id" in rec
    assert "success" in rec


@pytest.mark.asyncio
async def test_error_type_is_a_class_name_not_an_exception_message(tmp_path, monkeypatch):
    """An exception message can carry script source, a path, or a credential."""
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    async def _boom(self, *a, **kw):
        raise RuntimeError("LEAKED_SECRET_zz99")

    monkeypatch.setattr(CodeExecutionTool, "_capture_artifacts", _boom)

    await _invoke(tool, "print('hello')")

    rec = audit.records[0]
    assert rec["error_type"] == "RuntimeError"
    assert "LEAKED_SECRET_zz99" not in json.dumps(audit.entries)


@pytest.mark.asyncio
async def test_the_record_is_written_under_the_code_execution_category(tmp_path):
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))

    await _invoke(tool, "print('hello')")

    assert [c for c, _ in audit.entries] == ["code_execution"]
