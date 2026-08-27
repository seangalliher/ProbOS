"""AD-1280 / BF-787: the mesh path leaves a record too.

AD-1247 gave the AGENTIC ``run_python`` path a per-execution ``code_execution``
audit record. The MESH path -- ``CodeRunnerAgent``, reached through the
``run_python`` / ``install_package`` intents -- wrote none, and its own module
docstring said so. These tests pin the record it writes now, and the three
decisions that shape it:

* **Only the script run is an execution.** A ``run_python`` turn can reach
  ``sandbox.run`` three times (venv create, pip install, the script) and only
  the third produces a record. ``install_package`` produces none at all: an
  execution entry for something that ran no submitted source corrupts the trail
  in the same direction as a record for a run that never started.
* **``agent_id`` is the delegating owner**, not the code-runner -- the mesh
  analogue of the tool's ``requesting_agent``.
* **``unknown`` is reachable here too.** ``handle_intent`` is awaited from the
  bus, so a cancelled turn unwinds through ``await sandbox.run(...)`` while the
  executor thread keeps going.

A fake sandbox that raises before anything starts looks identical to a launched
run under a weak assertion -- AD-1247 shipped exactly that defect before review
caught it. So the launched/queued tests assert on ``LaunchOutcome`` state
captured from the real ``ExecutionRequest``, or drive a stub that genuinely
resolves the launch outcome from another thread first.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos.agents.code_runner as mod_runner
from probos.agents.code_runner import CodeRunnerAgent
from probos.config import ExecutionConfig
from probos.execution.audit import AUDIT_DETAIL_ALLOWLIST
from probos.execution.isolation import ExecutionRequest, ExecutionResult, SubprocessSandbox
from probos.tools.code_execution_tool import CodeExecutionTool
from probos.types import IntentMessage


class _Audit:
    """The real ``AuditLog`` surface: keyword-only ``append``.

    ``append`` only STORES. Validation lives in ``records`` because ``record``
    wraps the append in ``except Exception`` -- and ``AssertionError`` is an
    ``Exception``, so a check raised from inside ``append`` is swallowed by
    production code and the guard is inert (AD-1247 measured this). Validating
    in the property means every test that reads ``.records``, including the ones
    asserting it is EMPTY, enforces the invariant.
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


def _agent(tmp_path: Path, *, audit: Any, **exec_kwargs: Any) -> CodeRunnerAgent:
    """A real agent over a REAL ``ExecutionConfig`` (BF-287: no MagicMock at the
    config boundary -- a phantom attribute would pass against a mock)."""
    exec_kwargs.setdefault("enabled", True)
    exec_kwargs.setdefault("scratch_dir", str(tmp_path / "exec"))
    exec_kwargs.setdefault("workspace_root", str(tmp_path / "workspaces"))
    cfg = ExecutionConfig(**exec_kwargs)
    runtime = SimpleNamespace(config=SimpleNamespace(execution=cfg), audit_log=audit)
    return CodeRunnerAgent(agent_id="cr-test", runtime=runtime)


async def _call(agent: CodeRunnerAgent, intent: str, **params: Any) -> dict[str, Any]:
    res = await agent.handle_intent(IntentMessage(intent=intent, params=params))
    return {"success": res.success, "data": res.result, "error": res.error}


def _spy_on_sandbox(monkeypatch: Any, seen: list[ExecutionRequest]) -> None:
    """Capture every ``ExecutionRequest`` and still run it for real.

    Lets a test assert on the ``LaunchOutcome`` the agent actually passed, which
    is the only thing that distinguishes "a child existed" from "we intended
    one".
    """
    real_run = SubprocessSandbox.run

    async def _spy(self: Any, request: ExecutionRequest) -> ExecutionResult:
        seen.append(request)
        return await real_run(self, request)

    monkeypatch.setattr(SubprocessSandbox, "run", _spy)


def _stub_argv_runs(monkeypatch: Any, seen: list[ExecutionRequest]) -> None:
    """Answer venv/pip ``argv`` runs synthetically; run ``code`` for real.

    The venv and pip ``sandbox.run`` CALLS still happen -- which is what
    Decision 2 is about -- but neither needs a network or a real venv, so the
    tests stay deterministic and fast.
    """
    real_run = SubprocessSandbox.run

    async def _spy(self: Any, request: ExecutionRequest) -> ExecutionResult:
        seen.append(request)
        if request.argv is not None:
            return ExecutionResult(success=True, stdout="ok")
        return await real_run(self, request)

    monkeypatch.setattr(SubprocessSandbox, "run", _spy)


# ── 1. one record per launched execution ───────────────────────────────────

@pytest.mark.asyncio
async def test_a_launched_mesh_run_produces_exactly_one_record(tmp_path, monkeypatch):
    """Acceptance 1, through the REAL sandbox and a real child process."""
    audit = _Audit()
    seen: list[ExecutionRequest] = []
    _spy_on_sandbox(monkeypatch, seen)
    agent = _agent(tmp_path, audit=audit)

    res = await _call(agent, "run_python", code="print('hello-from-mesh')")

    assert res["success"] is True
    # The premise: the agent wired an outcome and a child really existed.
    assert seen[-1].launch_outcome is not None, "no launch outcome was passed"
    assert seen[-1].launch_outcome.launched is True
    assert len(audit.records) == 1
    rec = audit.records[0]
    assert rec["launch_state"] == "launched"
    assert rec["success"] is True
    assert rec["exit_code"] == 0
    assert rec["timed_out"] is False


@pytest.mark.asyncio
async def test_a_run_that_never_starts_produces_no_record(tmp_path, monkeypatch):
    """Acceptance 2. A queued-but-never-started run is not an execution."""
    audit = _Audit()
    agent = _agent(tmp_path, audit=audit)

    async def _never_launches(self, request):
        # Faithful to the real contract: run() returns a result and simply
        # never sets the signal, exactly as a spawn failure does.
        return ExecutionResult(success=False, error="boom", workdir=str(request.workdir))

    monkeypatch.setattr(SubprocessSandbox, "run", _never_launches)

    await _call(agent, "run_python", code="print('x')")

    assert audit.records == []


@pytest.mark.asyncio
async def test_a_failure_to_spawn_produces_no_record(tmp_path, monkeypatch):
    """Acceptance 3, with a REAL unspawnable interpreter rather than a mock.

    ``sandbox.run`` only QUEUES; ``Popen`` happens later inside the executor, so
    a stub that raises before any thread starts cannot tell the two apart. Here
    the sandbox is real and the interpreter genuinely does not exist, so the
    launch question is ANSWERED (``resolved`` set) with the answer "no".
    Only ``_prepare_venv`` is stood in for, because a real one needs a network.
    """
    audit = _Audit()
    seen: list[ExecutionRequest] = []
    _spy_on_sandbox(monkeypatch, seen)
    missing = tmp_path / "definitely-not-an-interpreter"

    async def _fake_prep(self, sandbox, venv_dir, packages, cfg):
        return {"success": True, "python": str(missing), "stdout": ""}

    monkeypatch.setattr(CodeRunnerAgent, "_prepare_venv", _fake_prep)
    agent = _agent(tmp_path, audit=audit, allow_package_install=True)

    res = await _call(agent, "run_python", code="print('x')", packages=["anything"])

    assert res["success"] is False
    launch = seen[-1].launch_outcome
    assert launch is not None
    assert launch.launched is False
    assert launch.resolved.is_set() is True, "the launch question must be answered"
    assert audit.records == []


@pytest.mark.asyncio
async def test_a_timed_out_run_still_counts_as_launched(tmp_path):
    """The child existed and did work; the kill path must not erase that."""
    audit = _Audit()
    agent = _agent(tmp_path, audit=audit, timeout_seconds=1.0)

    res = await _call(agent, "run_python", code="import time; time.sleep(30)")

    assert res["data"]["timed_out"] is True
    assert len(audit.records) == 1
    assert audit.records[0]["launch_state"] == "launched"
    assert audit.records[0]["timed_out"] is True


# ── 2. teardown: launched, not launched, and unknown ───────────────────────

@pytest.mark.asyncio
async def test_cancellation_after_a_launched_run_is_recorded(tmp_path):
    """The race that would produce an executed script with ZERO records.

    ``run_in_executor`` does not stop when the awaiting task is cancelled, so a
    child can be created AFTER the agent's ``finally`` has already looked.
    Deliberately NOT a stub that raises immediately -- that shape cannot tell
    queued from launched, and AD-1247 pinned the defect as contract with it.
    Here the launch outcome is resolved from another thread, exactly as a real
    worker that has not reached ``Popen`` yet would.
    """
    audit = _Audit()
    agent = _agent(tmp_path, audit=audit)
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
        task = asyncio.create_task(_call(agent, "run_python", code="print('x')"))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert len(audit.records) == 1, "a launched child must not vanish from the trail"
    assert audit.records[0]["launch_state"] == "launched"
    assert audit.records[0]["error_type"] == "cancelled"


@pytest.mark.asyncio
async def test_cancellation_before_launch_is_not_recorded(tmp_path, monkeypatch):
    """The other half: the sandbox ANSWERED, and the answer was "never spawned"."""
    audit = _Audit()
    agent = _agent(tmp_path, audit=audit)

    async def _cancel_while_queued(self, request):
        request.launch_outcome.resolved.set()
        raise asyncio.CancelledError()

    monkeypatch.setattr(SubprocessSandbox, "run", _cancel_while_queued)

    with pytest.raises(asyncio.CancelledError):
        await _call(agent, "run_python", code="print('x')")

    assert audit.records == []


@pytest.mark.asyncio
async def test_an_unresolved_launch_is_recorded_as_unknown(tmp_path, caplog):
    """The bound expired, so neither answer is available.

    Recording nothing would silently drop a run that may be about to start;
    recording it as launched would assert something unverified. The third option
    is the honest one -- write the record and SAY the launch is unconfirmed.
    """
    audit = _Audit()
    agent = _agent(tmp_path, audit=audit)
    started = threading.Event()

    async def _never_resolves(_self, request):
        started.set()
        await asyncio.sleep(30)
        return ExecutionResult(success=True)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(SubprocessSandbox, "run", _never_resolves)
        mp.setattr(mod_runner, "LAUNCH_RESOLVE_SECONDS", 0.05)
        task = asyncio.create_task(_call(agent, "run_python", code="print('x')"))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5.0)
        with caplog.at_level(logging.WARNING):
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    assert len(audit.records) == 1, "an unconfirmed run must not be dropped"
    assert audit.records[0]["launch_state"] == "unknown"
    assert any("launch_state=unknown" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_failure_after_the_audit_does_not_add_a_second(tmp_path, monkeypatch):
    """One execution must never appear in the trail as two runs.

    The record is written the moment ``sandbox.run`` returns; everything after
    it -- here, reading the result into the reply -- unwinds into the same
    ``finally``, which must see the attempted-flag and stay quiet.
    """

    class _DiesAfterTheRecord:
        success, error, exit_code, timed_out = True, "", 0, False
        tier, duration_ms = 1, 1.0

        @property
        def stdout(self) -> str:
            raise RuntimeError("after the audit")

    audit = _Audit()
    agent = _agent(tmp_path, audit=audit)

    async def _launched(self, request):
        request.launch_outcome.launched = True
        request.launch_outcome.resolved.set()
        return _DiesAfterTheRecord()

    monkeypatch.setattr(SubprocessSandbox, "run", _launched)

    with pytest.raises(RuntimeError):
        await _call(agent, "run_python", code="print('x')")

    assert len(audit.records) == 1, "one execution, one record"


# ── 3. only the script run is an execution (Decision 2) ────────────────────

@pytest.mark.asyncio
async def test_installing_packages_does_not_add_a_second_record(tmp_path, monkeypatch):
    """A ``run_python`` turn WITH packages is still ONE execution.

    The pip run reaches ``sandbox.run`` for real; auditing it too would put a
    second entry in the trail for one thing the agent asked for.
    """
    audit = _Audit()
    seen: list[ExecutionRequest] = []
    _stub_argv_runs(monkeypatch, seen)
    # Skip venv creation by making the interpreter already "present", and point
    # it at the real one so the script genuinely runs.
    monkeypatch.setattr(mod_runner, "_venv_python", lambda _d: Path(sys.executable))
    agent = _agent(tmp_path, audit=audit, allow_package_install=True)

    res = await _call(agent, "run_python", code="print('with-packages')", packages=["anything"])

    assert res["success"] is True
    # The premise: an argv run really was submitted, so "one record" is a
    # statement about a turn that reached the install path.
    assert [r for r in seen if r.argv is not None], "pip never reached the sandbox"
    assert [r for r in seen if r.code is not None], "the script never ran"
    assert len(audit.records) == 1


@pytest.mark.asyncio
async def test_install_package_alone_produces_no_record(tmp_path, monkeypatch):
    """``install_package`` runs no submitted source, so it is not an execution.

    Both argv sites -- venv create and pip install -- are exercised, so a record
    written at either one shows up here.
    """
    audit = _Audit()
    seen: list[ExecutionRequest] = []
    _stub_argv_runs(monkeypatch, seen)
    agent = _agent(tmp_path, audit=audit, allow_package_install=True)

    res = await _call(agent, "install_package", packages=["anything"])

    assert res["success"] is True
    assert len([r for r in seen if r.argv is not None]) == 2, "venv + pip must both run"
    assert audit.records == []


# ── 4. the record's shape ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_source_is_recorded_as_a_digest_never_as_text(tmp_path):
    """Code an agent runs can carry credentials it was legitimately given."""
    audit = _Audit()
    agent = _agent(tmp_path, audit=audit)
    secret = "SUPER_SECRET_TOKEN_ab12cd34"

    await _call(agent, "run_python", code=f"print('{secret}')")

    assert secret not in json.dumps(audit.entries)
    rec = audit.records[0]
    assert len(rec["code_sha256"]) == 64
    assert rec["code_chars"] > 0


@pytest.mark.asyncio
async def test_the_digest_is_the_real_hash_and_distinguishes_scripts(tmp_path):
    """A digest that is a constant is not a digest.

    Asserting only "64 hex characters" let a mutation replacing every hash with
    64 zeros pass AD-1247's whole suite -- every script would become
    indistinguishable in the trail while the audit tests stayed green.
    """
    audit = _Audit()
    agent = _agent(tmp_path, audit=audit)
    first, second = "print('alpha')", "print('beta')"

    await _call(agent, "run_python", code=first)
    await _call(agent, "run_python", code=second)

    digests = [r["code_sha256"] for r in audit.records]
    assert digests[0] == hashlib.sha256(first.encode("utf-8")).hexdigest()
    assert digests[1] == hashlib.sha256(second.encode("utf-8")).hexdigest()
    assert digests[0] != digests[1]


@pytest.mark.asyncio
async def test_the_record_carries_only_allowlisted_keys(tmp_path):
    """Prove the filter RUNS, not merely that today's keys happen to comply.

    Every key the builder produces is already allowlisted, so deleting the
    filter changes no current output and a mutation removing it survives. The
    filter exists for the key a future edit adds without updating the allowlist
    -- so the test has to create that situation rather than wait for it.
    """
    audit = _Audit()
    agent = _agent(tmp_path, audit=audit)

    await _call(agent, "run_python", code="print('hello')")
    assert set(audit.records[0]) <= AUDIT_DETAIL_ALLOWLIST

    import probos.execution.audit as mod

    narrowed = frozenset(AUDIT_DETAIL_ALLOWLIST - {"code_sha256"})
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "AUDIT_DETAIL_ALLOWLIST", narrowed)
        narrowed_audit = _Audit()
        await _call(_agent(tmp_path, audit=narrowed_audit), "run_python", code="print('hi')")

    rec = narrowed_audit.records[0]
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
    agent = _agent(tmp_path, audit=audit)

    async def _launch_then_die(self, request):
        request.launch_outcome.launched = True
        request.launch_outcome.resolved.set()
        raise RuntimeError("LEAKED_SECRET_zz99")

    monkeypatch.setattr(SubprocessSandbox, "run", _launch_then_die)

    with pytest.raises(RuntimeError):
        await _call(agent, "run_python", code="print('x')")

    assert len(audit.records) == 1
    assert audit.records[0]["error_type"] == "RuntimeError"
    assert "LEAKED_SECRET_zz99" not in json.dumps(audit.entries)


@pytest.mark.asyncio
async def test_the_agent_id_is_the_delegating_owner_not_the_runner(tmp_path):
    """The record names the agent the code ran FOR, not the executor.

    ``workspace_owner`` is how a delegating crew agent signs its own name to a
    run, and it is the mesh analogue of the tool's ``requesting_agent``. Naming
    the code-runner instead would make every mesh execution in the trail
    attributable to the same agent, which is no attribution at all.
    """
    audit = _Audit()
    agent = _agent(tmp_path, audit=audit)

    await _call(agent, "run_python", code="print('x')", workspace_owner="ezri")

    rec = audit.records[0]
    assert rec["agent_id"] == "ezri"
    assert rec["agent_id"] != agent.id
    assert rec["agent_id"] != agent.agent_type


@pytest.mark.asyncio
async def test_every_record_carries_a_32_char_execution_correlation_id(tmp_path):
    """Audit sequence identifies a ROW, not the invocation it represents."""
    audit = _Audit()
    agent = _agent(tmp_path, audit=audit)

    await _call(agent, "run_python", code="print('a')")
    await _call(agent, "run_python", code="print('a')")

    ids = [r["execution_id"] for r in audit.records]
    assert len(ids) == 2
    assert len(set(ids)) == 2, "each invocation needs its own id"
    assert all(len(i) == 32 for i in ids)


# ── 5. the absent or broken sink is allowed but never silent ───────────────

@pytest.mark.asyncio
async def test_no_sink_does_not_fail_the_execution(tmp_path):
    """Auditing must not become a new way to lose work."""
    agent = _agent(tmp_path, audit=None)

    res = await _call(agent, "run_python", code="print('hello')")

    assert res["success"] is True
    assert res["error"] is None


@pytest.mark.asyncio
async def test_no_sink_is_reported_not_swallowed(tmp_path, caplog):
    """The absence is permitted; being SILENT about it is not."""
    agent = _agent(tmp_path, audit=None)

    with caplog.at_level(logging.WARNING):
        await _call(agent, "run_python", code="print('hello')")

    warnings = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "no audit sink" in r.getMessage()
    ]
    assert warnings, "an untrailed mesh execution must be visible in the log"
    assert "audit_enabled" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_the_absence_warning_does_not_repeat(tmp_path, caplog):
    """A long-running vessel must not have its log filled by this."""
    agent = _agent(tmp_path, audit=None)

    with caplog.at_level(logging.WARNING):
        await _call(agent, "run_python", code="print('a')")
        await _call(agent, "run_python", code="print('b')")
        await _call(agent, "run_python", code="print('c')")

    warnings = [r for r in caplog.records if "no audit sink" in r.getMessage()]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_a_failing_sink_does_not_fail_the_execution(tmp_path):
    class _BrokenAudit:
        def append(self, **_kw: Any) -> None:
            raise RuntimeError("sink is down")

    agent = _agent(tmp_path, audit=_BrokenAudit())

    res = await _call(agent, "run_python", code="print('hello')")

    assert res["success"] is True
    assert res["error"] is None


@pytest.mark.asyncio
async def test_the_workdir_is_still_reaped_when_the_sink_explodes(tmp_path, monkeypatch):
    """An audit write must not become two new defects.

    The teardown record sits in its own nested ``try/finally`` so a sink raising
    ``BaseException`` -- which is deliberately NOT swallowed -- cannot skip the
    ephemeral workdir reap below it. Driven down the teardown path, because that
    is the only place the nesting discriminates: on the normal path the record
    is written inside the ``try`` and the outer ``finally`` already covers it.
    """

    class _Explode:
        def append(self, **_kw: Any) -> None:
            raise asyncio.CancelledError()

    scratch = tmp_path / "exec"
    agent = _agent(tmp_path, audit=_Explode(), persistent_workspaces=False)

    async def _launch_then_die(self, request):
        request.launch_outcome.launched = True
        request.launch_outcome.resolved.set()
        raise RuntimeError("torn down mid-run")

    monkeypatch.setattr(SubprocessSandbox, "run", _launch_then_die)

    with pytest.raises(asyncio.CancelledError):
        await _call(agent, "run_python", code="print('hello')")

    leftover = [p for p in scratch.iterdir() if p.is_dir()] if scratch.exists() else []
    assert leftover == [], f"workdir leaked: {leftover}"


# ── 6. one builder, two call sites ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_tool_and_the_mesh_path_share_one_record_builder(tmp_path):
    """The extraction must not silently fork.

    ``artifact_count`` is the one key the mesh record does not carry, and its
    absence is a decision rather than a gap: the mesh path captures no
    artifacts, and AD-1247's premise is that an acknowledged absence beats a
    false zero. Every other key must match, or the two paths have drifted.
    """
    code = "print('shared')"
    tool_audit = _Audit()
    tool = CodeExecutionTool(
        runtime=SimpleNamespace(
            config=SimpleNamespace(
                execution=SimpleNamespace(
                    enabled=True,
                    scratch_dir=str(tmp_path / "tool-scratch"),
                    timeout_seconds=30,
                    max_output_bytes=65536,
                    max_memory_mb=512,
                    stage_thread_artifacts=False,
                    fetch_broker_enabled=False,
                ),
                dependency=None,
            ),
            audit_log=tool_audit,
            agent_registry=None,
            artifact_store=None,
        )
    )
    await tool.invoke({"code": code}, {"agent_id": "ezri"})

    mesh_audit = _Audit()
    await _call(_agent(tmp_path, audit=mesh_audit), "run_python", code=code)

    tool_keys = set(tool_audit.records[0])
    mesh_keys = set(mesh_audit.records[0])
    assert tool_keys, "the tool wrote nothing to compare against"
    assert mesh_keys == tool_keys - {"artifact_count"}
    assert "artifact_count" not in mesh_keys
    # The same source through the same builder must digest identically.
    assert mesh_audit.records[0]["code_sha256"] == tool_audit.records[0]["code_sha256"]
