"""AD-1205: production crossings, without changing frozen legacy contracts."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.capability_request import CapabilityRequestStore
from probos.cognitive.agentic_dispatch import (
    ObservedWorkItemAgenticOutcome,
    WorkItemAgenticExecutor,
    WorkItemAgenticOutcome,
    classify_tool_fault_error,
    handled_fault_observation,
    tool_fault_adapter_kind,
    tool_fault_capture,
    tool_fault_id_resolver,
)
from probos.cognitive.cognitive_agent import (
    CognitiveAgent, _fault_request_text, _file_pass_defect, _promotion_request_text,
)
from probos.cognitive.continue_or_ask import resolve_exhausted_turn
from probos.cognitive.repair_dispatch import wire_repair_dispatcher
from probos.cognitive.repair_verification import find_failing_arguments
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolCallResult,
    ToolUseBlock,
    llm_function_name,
)
from probos.config import DmAgenticConfig, RepairConfig
from probos.execution.isolation import (
    CancelCleanup, ExecutionRequest, ExecutionResult, LaunchOutcome, SubprocessSandbox,
)
from probos.fault_detection import (
    FaultObservationResult, ToolFaultAdapterKind, ToolFaultCapture, ToolFaultTurn,
)
from probos.fault_report import FaultReport, FaultReportStore, ToolDefect, error_signature
from probos.tools.code_execution_tool import CodeExecutionTool, _execution_error
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResult
from probos.tools.registry import ToolRegistry
from tests.test_ad1066_code_execution_tool import (
    _ctx, _loop_runtime, _runtime, _tool_use,
)
from tests.test_ad1257_defect_follows_failure import (
    _FailingTool,
    _FakeLLMResponse,
    _RecordingFaultStore,
    _ScriptedLLM,
    _agent,
    _exec_runtime,
    _standing_rule,
    _text_response,
    _tool_use_response,
)

SOURCE = Path(__file__).resolve().parents[1] / "src"
HISTORIC_STDERR = (
    "python.exe: can't open file "
    "'D:\\ProbOS\\data\\execution\\scratch\\exec-a7710def\\"
    "data\\execution\\scratch\\exec-a7710def\\script.py'"
)
HISTORIC_SIGNATURE = "d7e439af0281014e261e38dc45f51aa8927aa2422cc67a82e94f99d5d9c5b577"
GENERATED_ENTRY_ERROR_PREFIX = "generated entry pre-launch check failed:"


def _assert_candidate_origins() -> None:
    origins = {
        name: Path(module.__file__).resolve()
        for name, module in tuple(sys.modules.items())
        if (name == "probos" or name.startswith("probos."))
        and getattr(module, "__file__", None)
    }
    assert origins and all(path.is_relative_to(SOURCE) for path in origins.values()), origins


@pytest.fixture(autouse=True)
def _owned_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _assert_candidate_origins()
    assert tmp_path.is_absolute() and tmp_path.is_dir()
    monkeypatch.setenv("PROBOS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    yield
    _assert_candidate_origins()


def _launch_result(**overrides) -> ExecutionResult:
    fields = {
        "success": False,
        "exit_code": 2,
        "timed_out": False,
        "stdout": "",
        "stderr": HISTORIC_STDERR,
    }
    fields.update(overrides)
    return ExecutionResult(**fields)


@pytest.mark.parametrize("stderr", [
    HISTORIC_STDERR,
    HISTORIC_STDERR + ": [Errno 2] No such file or directory\n",
    "/usr/bin/python3.12: can't open file '/tmp/exec-abc123/script.py'",
    '"C:\\Program Files\\Python\\python.exe": can\'t open file \'C:\\tmp\\exec-abcd\\script.py\'\r\n',
])
def test_stderr_diagnostic_alone_does_not_authenticate_launch_failure(stderr: str) -> None:
    # R1: matching text alone never established that user code did not run.
    assert _execution_error(_launch_result(stderr=stderr)) is None


@pytest.mark.parametrize("overrides", [
    {"success": True}, {"success": 0}, {"success": None},
    {"exit_code": True}, {"exit_code": "2"}, {"exit_code": 1},
    {"timed_out": True}, {"timed_out": 0}, {"timed_out": None},
    {"stdout": " "}, {"stdout": None},
    {"stderr": ""}, {"stderr": None},
    {"stderr": "ordinary script failed"},
    {"stderr": "ModuleNotFoundError: No module named 'missing'"},
    {"stderr": HISTORIC_STDERR.replace("script.py", "user.py")},
    {"stderr": HISTORIC_STDERR.replace("exec-a7710def", "other-a7710def")},
    {"stderr": HISTORIC_STDERR.replace("python.exe", "user.exe")},
    {"stderr": "unrelated output\n" + HISTORIC_STDERR},
    {"stderr": HISTORIC_STDERR + "\nextra output"},
    {"stderr": HISTORIC_STDERR + ": [Errno 13] Permission denied"},
])
def test_launch_error_other_payloads_are_not_infrastructure_faults(overrides: dict) -> None:
    assert _execution_error(_launch_result(**overrides)) is None


def test_launch_error_existing_error_is_preserved() -> None:
    result = _launch_result(error="Explicit sandbox failure")
    assert _execution_error(result) is result.error


async def test_real_user_script_historic_stderr_is_not_a_launch_fault(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    assert Path(runtime.config.execution.scratch_dir).is_relative_to(tmp_path)
    code = "import sys\nsys.stderr.write(" + repr(HISTORIC_STDERR) + ")\nraise SystemExit(2)\n"
    result = await CodeExecutionTool(runtime=runtime).invoke({"code": code}, _ctx())
    assert result.output["success"] is False
    assert result.output["exit_code"] == 2 and result.output["timed_out"] is False
    assert result.output["stdout"] == ""
    assert result.output["stderr"] == HISTORIC_STDERR
    # R1: this script actually ran; its printed diagnostic was a spoof, not
    # evidence of a generated-entry launch failure.
    assert result.error is None
    normalized = ToolCallResult.from_tool_result("bf715", result, 1.0)
    assert normalized.is_error is False
    assert normalized.output == str(result.output)
    assert not list((tmp_path / "scratch").glob("exec-*"))


def _bad_generated_entry(monkeypatch, tmp_path: Path, mode: str):
    original = SubprocessSandbox._build_argv
    plans = []

    def build(request: ExecutionRequest, workdir: Path) -> list[Any]:
        assert workdir.is_absolute() and workdir.is_relative_to(tmp_path)
        argv: list[Any] | None = original(request, workdir)
        assert argv and request.code is not None and not request.argv
        expected = workdir / ("_probos_launch.py" if request.import_workdir else "script.py")
        assert Path(argv[-1]) == expected and expected.is_file()
        if mode == "missing-script":
            (workdir / "script.py").unlink()
        elif mode == "missing-launcher":
            assert request.import_workdir
            expected.unlink()
        elif mode == "doubled":
            argv[-1] = str(Path("execution") / "scratch" / workdir.name / expected.name)
            assert not (workdir / argv[-1]).exists()
        elif mode == "wrong-entry":
            wrong = workdir / "other.py"
            wrong.write_text(request.code, encoding="utf-8")
            argv[-1] = str(wrong)
        elif mode == "wrong-command":
            argv[1] = "-c"
        elif mode == "missing-argument":
            argv.pop()
        elif mode == "empty-entry":
            argv[-1] = ""
        elif mode == "nontext-entry":
            argv[-1] = expected
        else:
            raise AssertionError(f"unknown fixture mode: {mode}")
        plans.append((request, workdir, list(argv)))
        return argv

    monkeypatch.setattr(SubprocessSandbox, "_build_argv", staticmethod(build))
    return plans


@pytest.mark.parametrize(("mode", "launcher"), [
    ("missing-script", False), ("missing-script", True),
    ("missing-launcher", True), ("doubled", False), ("doubled", True),
    ("wrong-entry", False), ("wrong-entry", True),
    ("wrong-command", False), ("wrong-command", True),
    ("missing-argument", False), ("empty-entry", False), ("nontext-entry", True),
])
@pytest.mark.parametrize("owned_workdir", [False, True])
async def test_generated_entry_guard_rejects_bad_plan_before_popen(
    tmp_path: Path, monkeypatch, mode: str, launcher: bool, owned_workdir: bool,
) -> None:
    plans = _bad_generated_entry(monkeypatch, tmp_path, mode)
    launches = []

    def forbidden_launch(*args, **kwargs):
        launches.append((args, kwargs))
        raise AssertionError("pre-launch validation must prevent Popen")

    monkeypatch.setattr("probos.execution.isolation.subprocess.Popen", forbidden_launch)
    launch = LaunchOutcome()
    cleanup = CancelCleanup()
    request = ExecutionRequest(
        code="open('entered.txt', 'w').write('user code ran')",
        workdir=None if owned_workdir else Path("execution") / "scratch" / "exec-relative",
        import_workdir=launcher, launch_outcome=launch, cleanup_on_cancel=cleanup,
    )
    result = await SubprocessSandbox(scratch_root=str(tmp_path / "scratch")).run(request)
    assert len(plans) == 1 and launches == [], "one bad plan, no launch or retry"
    assert result.success is False and "pre-launch check" in result.error
    assert result.exit_code is None and result.stdout == result.stderr == ""
    assert result.timed_out is False and result.child_reaped is True
    assert launch.resolved.is_set() and launch.launched is False
    assert cleanup.safe_to_remove
    assert result.workdir == str(plans[0][1])
    assert not (Path(result.workdir) / "entered.txt").exists()
    if owned_workdir:
        assert not Path(result.workdir).exists(), "sandbox still owns ephemeral cleanup"


@pytest.mark.parametrize("doubled", [False, True])
@pytest.mark.parametrize("entry", ["script.py", "_probos_launch.py"])
def test_real_interpreter_missing_entry_has_real_origin_without_user_code(
    tmp_path: Path, doubled: bool, entry: str,
) -> None:
    workdir = tmp_path / "execution" / "scratch" / "exec-origin"
    assert workdir.is_relative_to(tmp_path)
    assert Path(sys.executable).is_absolute() and Path(sys.executable).is_file()
    workdir.mkdir(parents=True)
    marker = workdir / "entered.txt"
    if doubled:
        (workdir / entry).write_text(
            "open('entered.txt', 'w').write('user code ran')", encoding="utf-8",
        )
        argument = Path("execution") / "scratch" / "exec-origin" / entry
    else:
        argument = workdir / entry
    actual_target = (workdir / argument).resolve()
    assert actual_target.is_relative_to(workdir) and not actual_target.exists()
    argv = [sys.executable, "-I", "-B", str(argument)]
    result = subprocess.run(argv, cwd=str(workdir), capture_output=True, timeout=10, check=False)
    assert result.args == argv and result.returncode == 2 and result.stdout == b""
    stderr = result.stderr.decode("utf-8")
    # CPython formats the path with repr(), including doubled Windows slashes.
    assert f"can't open file {str(actual_target)!r}" in stderr
    assert not marker.exists()
    # This is a real interpreter diagnostic, not the production guard's
    # host error, and not the controlled historical identity fixture below.


async def test_controlled_historical_error_preserves_signature_trace_and_arguments(
    tmp_path: Path, monkeypatch,
) -> None:
    calls = []

    async def historical_result(_sandbox, request):
        calls.append(request)
        return _launch_result(error=HISTORIC_STDERR)

    monkeypatch.setattr(SubprocessSandbox, "run", historical_result)
    runtime = _loop_runtime(tmp_path, enabled=True)
    runtime.attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")
    store = FaultReportStore(str(tmp_path / "faults.db"))
    runtime.fault_report_store = store
    await store.start()
    arguments = {"code": "print('historical identity fixture, not launch evidence')"}
    try:
        for _ in range(3):
            outcome = await _run(runtime, [
                _tool_use("run_python", arguments), _text_response("Honest fallback"),
            ])
            trace = json.loads(await runtime.attachment_store.read(outcome.tool_trace_ref))
            assert trace[0]["output"] == HISTORIC_STDERR and trace[0]["is_error"] is True
            assert trace[0]["error_signature"] == HISTORIC_SIGNATURE
            assert find_failing_arguments(trace, tool_id="run_python", signature=HISTORIC_SIGNATURE) == arguments
        assert len(calls) == 3 and store.list_open()[0].signature == HISTORIC_SIGNATURE
    finally:
        await store.stop()
    reopened = FaultReportStore(str(tmp_path / "faults.db"))
    await reopened.start()
    try:
        report = reopened.list_open()[0]
        assert report.signature == HISTORIC_SIGNATURE and report.occurrences == 1
        assert report.error_text == HISTORIC_STDERR
    finally:
        await reopened.stop()


@pytest.mark.parametrize(("root_word", "generic_category"), [
    ("ordinary", "other"), ("invalid", "invalid_params"),
    ("permission", "permission_denied"), ("cancelled", "cancelled"),
])
def test_generated_entry_prefix_is_observer_only_classification(
    root_word: str, generic_category: str,
) -> None:
    from probos.tools.executor import classify_tool_error

    error = (
        f"{GENERATED_ENTRY_ERROR_PREFIX} required generated file is missing: "
        rf"C:\owned\{root_word}-root\exec-fixture\script.py"
    )
    assert classify_tool_error(error) == generic_category
    assert classify_tool_fault_error(error) == "other"


@pytest.mark.parametrize(("root_word", "category"), [
    ("invalid", "invalid_params"), ("permission", "permission_denied"),
    ("cancelled", "cancelled"),
])
@pytest.mark.parametrize("prefix", [
    "generated entry pre-launch check failed",
    "generated entry pre-launch check failed :",
    "Generated entry pre-launch check failed:",
    " generated entry pre-launch check failed:",
    "wrapper: generated entry pre-launch check failed:",
    "generated entry pre-launch check failed-ish:",
])
def test_near_generated_entry_prefix_keeps_generic_policy_classification(
    root_word: str, category: str, prefix: str,
) -> None:
    from probos.tools.executor import classify_tool_error

    error = f"{prefix} " + rf"C:\owned\{root_word}-root\exec-fixture\script.py"
    assert classify_tool_fault_error(error) == classify_tool_error(error) == category


@pytest.mark.parametrize(("error", "category"), [
    ("permission denied", "permission_denied"),
    ("invalid parameter", "invalid_params"),
    ("operation cancelled", "cancelled"),
    ("requires_confirmation", "permission_denied"),
    ("consensus_blocked", "permission_denied"),
    ("network connection failed", "network"),
    (None, None), ("", "other"), (False, "other"),
    ({"error": GENERATED_ENTRY_ERROR_PREFIX}, "other"),
])
def test_generated_entry_exception_preserves_ordinary_policy_and_empty_results(
    error: Any, category: str | None,
) -> None:
    assert classify_tool_fault_error(error) == category


@pytest.mark.parametrize("root_word", ["ordinary", "invalid", "permission", "cancelled"])
@pytest.mark.parametrize("mode", ["missing-script", "doubled"])
async def test_guarded_sandbox_error_crosses_real_tool_trace_observer_and_reopened_store(
    tmp_path: Path, monkeypatch, mode: str, root_word: str,
) -> None:
    from probos.execution.audit import ExecutionAuditor
    from tests.test_ad1247_execution_audit import _Audit

    plans = _bad_generated_entry(monkeypatch, tmp_path, mode)
    launches = []

    def forbidden_launch(*args, **kwargs):
        launches.append((args, kwargs))
        raise AssertionError("guarded bad plan must never launch")

    monkeypatch.setattr("probos.execution.isolation.subprocess.Popen", forbidden_launch)
    audits = []
    record = ExecutionAuditor.record

    def observe_audit(self, **kwargs):
        audits.append(kwargs)
        return record(self, **kwargs)

    monkeypatch.setattr(ExecutionAuditor, "record", observe_audit)
    runtime = _loop_runtime(tmp_path, enabled=True)
    scratch_root = tmp_path / f"{root_word}-scratch"
    assert scratch_root.is_absolute() and scratch_root.is_relative_to(tmp_path)
    runtime.config.execution.scratch_dir = str(scratch_root)
    runtime.audit_log = _Audit()
    runtime.attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")
    store = FaultReportStore(str(tmp_path / "faults.db"))
    runtime.fault_report_store = store
    arguments = {"code": "open('entered.txt', 'w').write('user code ran')"}
    turns = []
    errors = []
    signatures = []
    await store.start()
    try:
        for index in range(3):
            turn = ToolFaultTurn()
            turns.append(turn.identity)
            outcome = await _run(runtime, [
                _tool_use("run_python", arguments), _text_response("Honest fallback"),
            ], fault_turn=turn)
            assert outcome.stopped_reason == "complete" and outcome.tool_defect is None
            trace = json.loads(await runtime.attachment_store.read(outcome.tool_trace_ref))
            error = audits[index]["result"].error
            errors.append(error)
            assert error.startswith(GENERATED_ENTRY_ERROR_PREFIX)
            assert str(scratch_root) in error and plans[index][1].parent == scratch_root
            assert trace[0]["is_error"] is True and trace[0]["output"] == error
            assert "can't open file" not in trace[0]["output"]
            signature = error_signature(tool_id="run_python", error_text=error)
            signatures.append(signature)
            assert trace[0]["error_signature"] == signature
            assert find_failing_arguments(
                trace, tool_id="run_python", signature=trace[0]["error_signature"],
            ) == arguments
            assert len(store.list_open()) == int(index == 2)
            assert len(plans) == len(audits) == index + 1 and launches == []
        assert len(turns) == len(set(turns)) == 3
        assert len(set(signatures)) == 1
        assert all(classify_tool_fault_error(error) == "other" for error in errors)
        assert store.list_open()[0].occurrences == 1
        assert runtime.audit_log.records == [], "no fabricated execution audit for a non-launch"
        for audit, (request, workdir, _argv) in zip(audits, plans):
            assert audit["launch_state"] == "not_launched" and audit["error_type"] == "sandbox_error"
            result = audit["result"]
            assert result.stdout == result.stderr == "" and result.exit_code is None
            assert request.launch_outcome.resolved.is_set() and not request.launch_outcome.launched
            assert request.cleanup_on_cancel.safe_to_remove
            assert not workdir.exists(), "tool-owned cleanup still runs on pre-launch failure"
    finally:
        await store.stop()
    reopened = FaultReportStore(str(tmp_path / "faults.db"))
    await reopened.start()
    try:
        report = reopened.list_open()[0]
        assert report.occurrences == 1 and "pre-launch check" in report.error_text
        assert report.signature == signatures[-1] and report.error_text == errors[-1][:2000]
        assert report.attempted == ""
        trace = json.loads(await runtime.attachment_store.read(report.tool_trace_ref))
        assert find_failing_arguments(trace, tool_id=report.tool_id, signature=report.signature) == arguments
    finally:
        await reopened.stop()


@pytest.mark.parametrize("launcher", [False, True])
async def test_explicit_argv_precedence_and_empty_argv_generated_branch(tmp_path, launcher: bool) -> None:
    sandbox = SubprocessSandbox(scratch_root=str(tmp_path / "scratch"))
    workdir = tmp_path / "exec-explicit"
    launch = LaunchOutcome()
    result = await sandbox.run(ExecutionRequest(
        argv=[sys.executable, "-I", "-B", "-c", "print('explicit command')"],
        code="raise AssertionError('generated code must not run')",
        workdir=workdir, import_workdir=launcher, launch_outcome=launch,
    ))
    assert result.success and result.stdout.strip() == "explicit command"
    assert launch.launched and launch.resolved.is_set()
    assert not (workdir / "script.py").exists() and not (workdir / "_probos_launch.py").exists()
    empty = await sandbox.run(ExecutionRequest(
        argv=[], code="print('generated command')", workdir=workdir, import_workdir=launcher,
    ))
    assert empty.success and empty.stdout.strip() == "generated command"
    assert (workdir / "script.py").is_file()
    assert (workdir / "_probos_launch.py").is_file() is launcher


@pytest.mark.parametrize("launcher", [False, True])
async def test_generated_entry_guard_accepts_correct_cwd_relative_entry(tmp_path, monkeypatch, launcher: bool) -> None:
    build = SubprocessSandbox._build_argv
    plans = []

    def relative_entry(request, workdir):
        argv = build(request, workdir)
        assert workdir.is_relative_to(tmp_path)
        argv[-1] = Path(argv[-1]).name
        plans.append((list(argv), workdir))
        return argv

    monkeypatch.setattr(SubprocessSandbox, "_build_argv", staticmethod(relative_entry))
    launch = LaunchOutcome()
    result = await SubprocessSandbox(scratch_root=str(tmp_path / "scratch")).run(ExecutionRequest(
        code="print('correct relative entry')", import_workdir=launcher, launch_outcome=launch,
    ))
    assert result.success and result.stdout.strip() == "correct relative entry"
    assert len(plans) == 1 and launch.launched and launch.resolved.is_set()
    assert plans[0][0][-1] == ("_probos_launch.py" if launcher else "script.py")
    assert not plans[0][1].exists()


@pytest.mark.parametrize("spoof", ["unrelated", "same-workdir", "nested-interpreter"])
async def test_real_user_diagnostic_spoofs_keep_outcomes_cleanup_and_one_audit(
    tmp_path, spoof: str, monkeypatch,
) -> None:
    from tests.test_ad1247_execution_audit import _Audit, _runtime as audit_runtime

    audit = _Audit()
    runtime = audit_runtime(tmp_path, audit=audit)
    launches = []
    popen = subprocess.Popen

    def record_launch(*args, **kwargs):
        launches.append((args, kwargs))
        return popen(*args, **kwargs)

    monkeypatch.setattr("probos.execution.isolation.subprocess.Popen", record_launch)
    if spoof == "nested-interpreter":
        code = (
            "import os, subprocess, sys\n"
            "child = subprocess.run([sys.executable, '-I', '-B', "
            "os.path.join(os.getcwd(), 'exec-nested', 'script.py')], capture_output=True)\n"
            "sys.stderr.buffer.write(child.stderr)\n"
            "raise SystemExit(child.returncode)\n"
        )
    else:
        target = (
            "os.path.join(os.getcwd(), 'script.py')" if spoof == "same-workdir"
            else repr(r"C:\unrelated\exec-other\script.py")
        )
        code = (
            "import os, sys\n"
            f"target = {target}\n"
            "diagnostic = f\"{sys.executable}: can't open file '{target}': [Errno 2] No such file or directory\\n\"\n"
            "sys.stderr.buffer.write(diagnostic.encode('utf-8'))\n"
            "raise SystemExit(2)\n"
        )
    result = await CodeExecutionTool(runtime=runtime).invoke({"code": code}, _ctx())
    assert len(launches) == 1 and result.error is None
    assert result.output["exit_code"] == 2 and result.output["success"] is False
    assert result.output["timed_out"] is False and result.output["stdout"] == ""
    assert "can't open file" in result.output["stderr"]
    if spoof == "same-workdir":
        assert str(Path(launches[0][1]["cwd"]) / "script.py") in result.output["stderr"]
    assert ToolCallResult.from_tool_result("spoof", result, 1).is_error is False
    assert len(audit.records) == 1 and audit.records[0]["launch_state"] == "launched"
    assert not Path(launches[0][1]["cwd"]).exists()


async def test_disappearance_after_prelaunch_check_is_not_attributed_by_stderr(
    tmp_path, monkeypatch,
) -> None:
    popen = subprocess.Popen
    launches = []

    def disappear_after_check(argv, **kwargs):
        entry = Path(argv[-1])
        assert entry.is_relative_to(tmp_path) and entry.is_file()
        launches.append(entry)
        entry.unlink()
        return popen(argv, **kwargs)

    monkeypatch.setattr("probos.execution.isolation.subprocess.Popen", disappear_after_check)
    result = await CodeExecutionTool(runtime=_runtime(tmp_path)).invoke({"code": "print('not entered')"}, _ctx())
    assert len(launches) == 1
    assert result.output["exit_code"] == 2 and "can't open file" in result.output["stderr"]
    assert result.output["stdout"] == "" and result.error is None
    assert ToolCallResult.from_tool_result("post-check", result, 1).is_error is False
    assert not launches[0].parent.exists()


@pytest.fixture
async def faults(tmp_path: Path):
    events = []
    path = tmp_path / "faults.db"
    store = FaultReportStore(
        str(path), emit_event=lambda event, data: events.append((event, dict(data))),
    )
    assert Path(store.db_path).is_relative_to(tmp_path)
    await store.start()
    try:
        yield store, events
    finally:
        await store.stop()


def _observer_runtime(store, *, tool_id="fixture_failure", error="fixture subsystem unavailable"):
    registry = ToolRegistry()
    tool = _FailingTool(tool_id, error)
    registry.register(tool, provider="test", default_permissions={"ensign": "read"})
    runtime = _exec_runtime(registry, ToolPermissionStore())
    runtime.fault_report_store = store
    runtime.config.dm_agentic = DmAgenticConfig(enabled=True, max_iterations=3)
    runtime.action_approval_store = None
    runtime.capability_request_store = None
    return runtime, tool


async def _run(runtime, responses, **kwargs) -> WorkItemAgenticOutcome:
    return await WorkItemAgenticExecutor(llm_client=_ScriptedLLM(responses)).run(
        agent_id="counselor-ezri", instructions="Fixture instructions",
        task_text="assembled context must not be persisted", runtime=runtime,
        thread_id="owned-thread", **kwargs,
    )


async def _dm(agent, raw="Captain raw request") -> str:
    return await CognitiveAgent._maybe_run_conversational_agentic(
        agent, {
            "intent": "direct_message", "thread_id": "owned-thread",
            "params": {"captain_message": raw},
        },
        system_prompt="Private assembled instructions",
        user_message="Private assembled context, code and delegated evidence",
    )


def _use_with_text(tool: str, text: str) -> _FakeLLMResponse:
    return _FakeLLMResponse(
        content_blocks=[
            TextBlock(text=text),
            ToolUseBlock(tool_call=ToolCallRequest(name=tool, arguments={})),
        ], content=text,
    )


async def test_real_completed_dm_single_failure_turns_file_on_third_only(faults) -> None:
    store, events = faults
    runtime, tool = _observer_runtime(store)
    agent = _agent(runtime)
    for index in range(3):
        agent._llm_client = _ScriptedLLM([
            _tool_use_response(tool.tool_id), _text_response("Honest inline fallback."),
        ])
        assert await _dm(agent, raw=f"raw request {index}") == "Honest inline fallback."
        assert len(store.list_open()) == (1 if index == 2 else 0)
    assert tool.invocations == 3 and len(events) == 1
    report = store.list_open()[0]
    assert report.occurrences == 1 and report.attempted == "raw request 2"
    assert report.thread_id == "owned-thread"
    agent._llm_client = _ScriptedLLM([
        _tool_use_response(tool.tool_id), _text_response("Honest inline fallback."),
    ])
    await _dm(agent)
    assert store.list_open()[0].occurrences == 2 and len(events) == 2


async def test_real_completed_dm_two_hit_control_files_once_on_first_turn(faults) -> None:
    store, events = faults
    runtime, tool = _observer_runtime(store)
    agent = _agent(runtime)
    agent._llm_client = _ScriptedLLM([
        _tool_use_response(tool.tool_id), _tool_use_response(tool.tool_id),
        _text_response("Honest completed fallback."),
    ])
    assert await _dm(agent) == "Honest completed fallback."
    assert tool.invocations == 2 and len(events) == 1
    assert store.list_open()[0].occurrences == 1
    assert store.list_open()[0].attempted == "Captain raw request"


async def test_real_executor_dm_hook_and_exhaustion_reuse_one_publication(faults) -> None:
    store, events = faults
    runtime, tool = _observer_runtime(store)
    outcome = await _run(runtime, [
        _use_with_text(tool.tool_id, "Partial work."),
        _use_with_text(tool.tool_id, "Still partial."),
    ], max_iterations=2)
    assert type(outcome) is ObservedWorkItemAgenticOutcome
    assert outcome.stopped_reason == "max_iterations" and outcome.tool_defect.count == 2
    assert tool.invocations == 2 and len(events) == 1
    filed = {}
    for _ in range(2):
        await _file_pass_defect(
            outcome, filed, runtime=runtime, agent_id="counselor-ezri",
            thread_id="owned-thread", attempted="raw request",
        )

    async def no_reinvoke(_text):
        raise AssertionError("one-pass exhaustion must not reinvoke")

    text = await resolve_exhausted_turn(
        outcome, reinvoke=no_reinvoke, runtime=runtime, agent_id="counselor-ezri",
        base_task_text="private context", config=SimpleNamespace(
            continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        ),
    )
    report = store.list_open()[0]
    assert report.id in text and report.occurrences == 1 and len(events) == 1
    assert filed == {outcome.tool_defect.signature: report.id}


async def test_real_dm_continuations_share_one_turn_and_do_not_manufacture_votes(faults, tmp_path) -> None:
    store, events = faults
    runtime, tool = _observer_runtime(store)
    runtime.config.dm_agentic = DmAgenticConfig(
        enabled=True, max_iterations=1,
        continue_or_ask_enabled=True, continue_or_ask_max_passes=3,
    )
    approvals = await _standing_rule(tmp_path)
    runtime.action_approval_store = approvals
    agent = _agent(runtime)
    try:
        for turn in range(3):
            agent._llm_client = _ScriptedLLM([
                _use_with_text(tool.tool_id, f"Partial step {index}.") for index in range(3)
            ])
            await _dm(agent)
            assert tool.invocations == (turn + 1) * 3, "premise: all continuation passes ran"
            assert len(events) == (1 if turn == 2 else 0)
        assert store.list_open()[0].occurrences == 1
    finally:
        await approvals.stop()


async def test_actual_dm_repeated_fault_across_continuations_and_exhaustion_files_once(faults, tmp_path) -> None:
    store, events = faults
    runtime, tool = _observer_runtime(store)
    runtime.config.dm_agentic = DmAgenticConfig(
        enabled=True, max_iterations=2,
        continue_or_ask_enabled=True, continue_or_ask_max_passes=2,
    )
    approvals = await _standing_rule(tmp_path)
    runtime.action_approval_store = approvals
    agent = _agent(runtime)
    agent._llm_client = _ScriptedLLM([
        _use_with_text(tool.tool_id, f"Partial step {index}.") for index in range(4)
    ])
    try:
        text = await _dm(agent)
        assert tool.invocations == 4
        report = store.list_open()[0]
        assert report.id in text and report.occurrences == 1 and len(events) == 1
        assert report.attempted == "Captain raw request"
    finally:
        await approvals.stop()


def test_base_twelve_fields_and_defaults_stay_frozen_and_subtype_is_shallow() -> None:
    names = [
        "final_text", "stopped_reason", "denied_tools", "tool_trace_ref",
        "total_tokens", "artifact_refs", "token_source", "tool_failures",
        "tool_defect", "tool_defect_evaluated", "tool_invocations", "delegation_evidence",
    ]
    base = WorkItemAgenticOutcome()
    assert [field.name for field in dataclasses.fields(base)] == names
    assert list(vars(base)) == names
    assert not hasattr(base, "fault_observation")
    marker = FaultObservationResult()
    observed = ObservedWorkItemAgenticOutcome(**vars(base), fault_observation=marker)
    for name in names:
        assert getattr(observed, name) is getattr(base, name)
    assert observed.fault_observation is marker
    assert not observed.__dataclass_params__.frozen
    assert inspect.signature(ObservedWorkItemAgenticOutcome).parameters[
        "fault_observation"
    ].kind is inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(TypeError):
        ObservedWorkItemAgenticOutcome()


@pytest.mark.parametrize("payload", [None, {}, SimpleNamespace(attempts=(), failed=False)])
def test_observed_carrier_requires_exact_valid_result(payload) -> None:
    with pytest.raises(ValueError, match="fault_observation_result_invalid"):
        ObservedWorkItemAgenticOutcome(fault_observation=payload)
    legacy = WorkItemAgenticOutcome()
    legacy.fault_observation = payload
    assert handled_fault_observation(legacy) is None


async def test_damaged_observed_carrier_does_not_reopen_legacy_filing(caplog) -> None:
    store = _RecordingFaultStore()
    defect = ToolDefect(tool_id="fixture", error_text="defective tool", count=2)
    outcome = ObservedWorkItemAgenticOutcome(
        final_text="Partial", stopped_reason="max_iterations",
        tool_defect=defect, tool_defect_evaluated=True,
        fault_observation=FaultObservationResult(),
    )
    outcome.fault_observation = {"attempts": [(defect.signature, "forged-id")]}
    await _file_pass_defect(
        outcome, {}, runtime=SimpleNamespace(fault_report_store=store),
        agent_id="agent", thread_id="", attempted="",
    )
    assert store.records == []
    handled = handled_fault_observation(outcome)
    assert handled.failed and handled.attempts == () and caplog.records


async def test_supported_empty_and_reporting_failure_return_observed_type(faults) -> None:
    store, events = faults
    runtime, _tool = _observer_runtime(store)
    empty = await _run(runtime, [_text_response("No tool needed.")])
    assert type(empty) is ObservedWorkItemAgenticOutcome
    assert empty.fault_observation == FaultObservationResult()
    assert events == []

    class BrokenObserver:
        async def observe_tool_run(self, **kwargs):
            raise RuntimeError("observation sink unavailable")

    runtime.fault_report_store = BrokenObserver()
    failure = await _run(runtime, [_text_response("Completed anyway.")])
    assert type(failure) is ObservedWorkItemAgenticOutcome
    assert failure.fault_observation.failed and failure.final_text == "Completed anyway."


async def test_unsupported_observer_preserves_exact_base_and_private_kwargs(monkeypatch) -> None:
    runtime, _tool = _observer_runtime(_RecordingFaultStore())
    calls = []
    original = WorkItemAgenticExecutor._run_reserved

    async def record(self, **kwargs):
        calls.append(kwargs)
        return await original(self, **kwargs)

    class UnexpectedTurn:
        def __init__(self):
            raise AssertionError("unsupported path must not allocate a turn")

    monkeypatch.setattr(WorkItemAgenticExecutor, "_run_reserved", record)
    monkeypatch.setattr("probos.cognitive.agentic_dispatch.ToolFaultTurn", UnexpectedTurn)
    result = await _run(runtime, [_text_response("Done")])
    assert type(result) is WorkItemAgenticOutcome
    assert "fault_turn" not in calls[0] and "fault_attempted" not in calls[0]


@pytest.mark.parametrize("stopped_reason", ["complete", "max_iterations", "token_budget", "error"])
async def test_direct_executor_observes_all_returned_stop_reasons(faults, stopped_reason: str) -> None:
    from tests.test_ad1191_delegation_wire import _LLM

    store, _events = faults
    runtime, tool = _observer_runtime(store)
    for _ in range(3):
        responses = [_tool_use_response(tool.tool_id)]
        if stopped_reason == "error":
            responses.append(RuntimeError("fixture LLM failure after completed tool"))
        else:
            responses.append(_text_response("Honest fallback"))
        outcome = await WorkItemAgenticExecutor(llm_client=_LLM(responses)).run(
            agent_id="counselor-ezri", instructions="", task_text="", runtime=runtime,
            max_iterations=1 if stopped_reason == "max_iterations" else 3,
            token_budget=2 if stopped_reason == "token_budget" else None,
        )
        assert outcome.stopped_reason == stopped_reason
        assert type(outcome) is ObservedWorkItemAgenticOutcome
        assert outcome.tool_defect is None
    assert tool.invocations == 3 and store.list_open()[0].occurrences == 1


class _LocalFaultEvents:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.listeners: list = []
        self.delivered = 0

    def add_event_listener(self, listener, event_types=None):
        self.listeners.append((listener, event_types))

    def emit(self, event, data):
        self.events.append({"type": event.value, "data": dict(data)})

    async def drain(self):
        while self.delivered < len(self.events):
            event = self.events[self.delivered]
            self.delivered += 1
            for listener, _event_types in self.listeners:
                await listener(event)


@pytest.mark.parametrize("repair_enabled", [False, True])
async def test_user_printed_diagnostic_does_not_file_or_request_repair(
    tmp_path: Path, repair_enabled: bool,
) -> None:
    bus = _LocalFaultEvents()
    runtime = _loop_runtime(tmp_path, enabled=True)
    runtime.data_dir = tmp_path
    runtime.attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")
    runtime.add_event_listener = bus.add_event_listener
    store = FaultReportStore(str(tmp_path / "faults.db"), emit_event=bus.emit)
    requests = CapabilityRequestStore(str(tmp_path / "requests.db"))
    runtime.fault_report_store = store
    runtime.capability_request_store = requests
    runtime.config.repair = RepairConfig(enabled=repair_enabled)
    await store.start()
    await requests.start()
    dispatcher = wire_repair_dispatcher(runtime, runtime.config)
    assert dispatcher is not None and len(bus.listeners) == 1
    code = "import sys\nsys.stderr.write(" + repr(HISTORIC_STDERR) + ")\nraise SystemExit(2)\n"
    try:
        assert Path(store.db_path).is_relative_to(tmp_path)
        assert Path(requests.db_path).is_relative_to(tmp_path)
        for index in range(5):
            outcome = await _run(runtime, [
                _tool_use("run_python", {"code": code}),
                _text_response("Honest inline fallback."),
            ], rank="lieutenant")
            assert outcome.stopped_reason == "complete" and outcome.tool_defect is None
            assert type(outcome) is ObservedWorkItemAgenticOutcome
            trace = json.loads(await runtime.attachment_store.read(outcome.tool_trace_ref))
            # R1: submitted code printed this text, so the old positive
            # launch-origin/signature assertions pinned a false diagnosis.
            assert len(trace) == 1 and trace[0]["is_error"] is False
            assert "error_signature" not in trace[0]
            assert find_failing_arguments(
                trace, tool_id="run_python", signature=HISTORIC_SIGNATURE,
            ) is None
            await bus.drain()
            assert store.list_open() == [] and await requests.list_pending() == []
        assert bus.events == []
    finally:
        await store.stop()
        await requests.stop()
    reopened = FaultReportStore(str(tmp_path / "faults.db"))
    await reopened.start()
    try:
        assert reopened.list_open() == []
        with sqlite3.connect(tmp_path / "faults.db") as db:
            assert db.execute("SELECT COUNT(*) FROM fault_reports").fetchone() == (0,)
    finally:
        await reopened.stop()


class _ObservedExecutor(WorkItemAgenticExecutor):
    def __init__(self, responses: list[Any]) -> None:
        super().__init__(llm_client=_ScriptedLLM(responses))
        self.calls: list[dict[str, Any]] = []
        self.outcomes: list[WorkItemAgenticOutcome] = []

    async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
        self.calls.append(dict(kwargs))
        outcome = await super().run(**kwargs)
        self.outcomes.append(outcome)
        return outcome


class _SequencedTool(_FailingTool):
    def __init__(self, tool_id: str, errors: list[str | None]) -> None:
        super().__init__(tool_id)
        self.errors = list(errors)
        self.contexts: list[dict[str, Any]] = []

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.invocations += 1
        self.contexts.append(dict(context or {}))
        error = self.errors.pop(0) if self.errors else None
        return ToolResult(output="successful result" if error is None else "", error=error)


@pytest.fixture
async def work_items(tmp_path: Path):
    from probos.workforce import WorkItemStore

    store = WorkItemStore(db_path=str(tmp_path / "work-items.db"), tick_interval=1000)
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


async def test_native_real_loop_observes_each_build_without_changing_metadata(
    faults, tmp_path: Path,
) -> None:
    from probos.cognitive.builder import BuildSpec
    from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness
    from probos.tools.executor import ToolExecutor

    store, events = faults
    runtime, tool = _observer_runtime(store, tool_id="read_file")
    runtime.data_dir = tmp_path / "data"
    work_dir = tmp_path / "repository"
    work_dir.mkdir()
    spec = BuildSpec(title="Fixture", description="Private build instructions")
    results = []
    for index in range(4):
        harness = NativeBuilderHarness(
            runtime=runtime,
            llm_client=_ScriptedLLM([
                _tool_use_response(tool.tool_id),
                _text_response("No file changes; tool failed."),
            ]),
            tool_executor=ToolExecutor(registry=runtime.tool_registry),
            tool_registry=runtime.tool_registry,
        )
        results.append(await harness.run_build(
            spec, str(work_dir), agent_id="builder", rank="ensign",
        ))
        assert tool.invocations == index + 1
        assert len(events) == max(0, index - 1)
    assert all(result == results[0] for result in results)
    assert set(results[0]) == {"file_changes", "llm_output", "builder_source", "metadata"}
    assert set(results[0]["metadata"]) == {
        "builder_type", "iterations", "tools_used", "compactions",
        "stopped_reason", "total_tokens", "token_source",
    }
    report = store.list_open()[0]
    assert report.occurrences == 2 and report.agent_id == "builder"
    assert report.tool_trace_ref is None and report.attempted == "" and report.thread_id == ""


async def test_delegated_real_parent_child_loops_file_child_fault_and_preserve_evidence(
    faults, tmp_path: Path,
) -> None:
    from probos.config import AgenticToolsConfig
    from tests.test_ad1072_agentic_tools import (
        _Agent, _callsign_registry, _delegation_runtime,
    )

    store, events = faults
    callsigns, agents = _callsign_registry(tmp_path, [
        _Agent("ezri-1", "ezri", agent_type="counselor", rank="lieutenant"),
        _Agent("bashir-1", "bashir", agent_type="diagnostician", rank="lieutenant"),
    ])
    tool = _FailingTool("fixture_failure", "fixture subsystem unavailable")
    runtime = _delegation_runtime(
        tmp_path, cs=callsigns, agent_registry=agents, extra_tools=[tool],
        agentic_tools=AgenticToolsConfig(delegation_enabled=True),
    )
    runtime.fault_report_store = store
    runtime.attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")
    responses = []
    for _ in range(3):
        responses.extend([
            _tool_use("delegate_task", {"task": "Private delegated request", "to": "bashir"}),
            _tool_use_response(tool.tool_id),
            _text_response("Honest child fallback."),
            _text_response("Captain, the child used a fallback."),
        ])
    executor = _ObservedExecutor(responses)
    for index in range(3):
        outcome = await executor.run(
            agent_id="ezri-1", instructions="Private parent instructions",
            task_text="Private parent context", runtime=runtime,
            rank="lieutenant", thread_id="delegated-thread", max_iterations=6,
        )
        assert outcome.final_text == "Captain, the child used a fallback."
        assert outcome.stopped_reason == "complete" and outcome.tool_defect is None
        assert outcome.delegation_evidence is not None
        assert tool.invocations == index + 1
        assert len(events) == int(index == 2)
        parent_trace = json.loads(await runtime.attachment_store.read(outcome.tool_trace_ref))
        assert len(parent_trace) == 1 and parent_trace[0]["name"] == "delegate_task"
        assert "fault_observation" not in parent_trace[0]["output"]
    report = store.list_open()[0]
    assert report.agent_id == "bashir-1" and report.thread_id == "delegated-thread"
    assert report.occurrences == 1 and report.attempted == ""
    child_trace = json.loads(await runtime.attachment_store.read(report.tool_trace_ref))
    assert find_failing_arguments(
        child_trace, tool_id=tool.tool_id, signature=report.signature,
    ) == {}
    assert [entry["name"] for entry in child_trace] == [tool.tool_id]


async def test_real_crew_outer_passes_share_child_turn_and_preserve_plan_and_fourteen_keys(
    faults, work_items, tmp_path: Path,
) -> None:
    from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
    from probos.crew_utils import CREW_EXECUTION_KEYS
    from tests.test_ad1155_loop_until_done import (
        _FakeAgent, _FakeRegistry, _child, _executor, _plan_identity,
    )

    store, events = faults
    runtime, tool = _observer_runtime(store)
    progress = _SequencedTool("progress_probe", [])
    runtime.tool_registry.register(progress, provider="test", default_permissions={"ensign": "read"})
    runtime.attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")
    assert inspect.signature(WorkItemAgenticExecutor.run).parameters["max_iterations"].default is None
    inner_limit = inspect.signature(AgenticLoop).parameters["max_iterations"].default
    assert type(inner_limit) is int and inner_limit > 1
    for child_index in range(3):
        responses = []
        for outer in range(3):
            responses.append(_use_with_text(tool.tool_id, f"Pass {outer} partial."))
            responses.extend(
                _use_with_text(progress.tool_id, f"Pass {outer} progress {step}.")
                for step in range(inner_limit - 1)
            )
        executor = _ObservedExecutor(responses)
        parent = await work_items.create_work_item(title="Parent", work_type="work_order")
        child = await _child(work_items, parent_id=parent.id)
        plan_before = _plan_identity(child)
        crew = _executor(
            work_items, _FakeRegistry({"a1": _FakeAgent("a1")}), executor,
            runtime=runtime, crew_loop_until_done_enabled=True,
            crew_loop_until_done_max_iterations=3,
        )
        await crew.run(parent.id)
        assert len(executor.calls) == 3, "premise: every real outer pass ran"
        assert all(type(value) is ObservedWorkItemAgenticOutcome for value in executor.outcomes)
        assert all(value.tool_defect is None for value in executor.outcomes)
        turn = executor.calls[0]["fault_turn"]
        assert all(call["fault_turn"] is turn for call in executor.calls)
        assert tool.invocations == (child_index + 1) * 3
        assert len(events) == int(child_index == 2)
        after = await work_items.get_work_item(child.id)
        assert after is not None and _plan_identity(after) == plan_before
        assert set(after.metadata["crew_execution"]) == set(CREW_EXECUTION_KEYS)
        assert len(after.metadata["crew_execution"]) == 14
        assert after.metadata["crew_execution"]["stopped_reason"] == "max_iterations"
    assert store.list_open()[0].occurrences == 1
    assert store.list_open()[0].attempted == ""


@pytest.mark.parametrize("session", [False, True], ids=["legacy", "session"])
@pytest.mark.parametrize("failures_per_pass", [1, 2], ids=["single", "same-run"])
async def test_real_corrections_share_episode_turn_and_project_only_observation(
    faults, work_items, tmp_path: Path, session: bool, failures_per_pass: int,
) -> None:
    from probos.cognitive.crew_executor import SubtaskResult
    from probos.cognitive.crew_verifier import SubtaskVerifier
    from probos.consensus.trust import TrustNetwork
    from probos.fault_detection import ToolFaultObservationPort
    from tests.test_ad1126_verified_finalization import _Agent, _Registry

    store, events = faults
    runtime, tool = _observer_runtime(store)
    runtime.attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")
    ambient_events = []
    runtime.emit_event = lambda *args: ambient_events.append(args)
    runtime.arbitrary_authority = object()
    await runtime.tool_permission_store.issue_grant("producer", tool.tool_id, ToolPermission.READ)
    registry = _Registry([_Agent("producer"), _Agent("judge")])
    trust = TrustNetwork()
    tokens = []
    for episode in range(3):
        child = await work_items.create_work_item(title="Correction", work_type="task")
        initial = SubtaskResult(
            work_item_id=child.id, spec_id="s1", agent_id="producer",
            output="Initial incomplete evidence", status="done",
        )
        executor = _ObservedExecutor([
            *[_tool_use_response(tool.tool_id) for _ in range(failures_per_pass)],
            _text_response("First honest revision."),
            *[_tool_use_response(tool.tool_id) for _ in range(failures_per_pass)],
            _text_response("Second honest revision."),
        ])
        judge = _ScriptedLLM([
            _text_response(json.dumps({
                "accepted": accepted, "confidence": 0.8,
                "critique": "Supply the remaining evidence." if not accepted else "Checked.",
            }))
            for accepted in (False, False, True)
        ])
        verifier = SubtaskVerifier(
            llm_client=judge, work_item_store=work_items, agent_registry=registry,
            trust_network=trust, agentic_executor=executor, runtime=runtime,
            max_convergence_rounds=2,
        )
        if session:
            result = await verifier.converge_for_session(
                initial, instructions="Private correction instructions",
                task_text="Private task and earlier evidence", expected_output="Checked result",
                parent_id="parent", thread_id="correction-thread", department="engineering",
                rank="ensign",
            )
            assert result.accepted and result.rounds_used == 2
            assert len(result.history) == 3 and result.history[0].result_text == initial.output
            for call in executor.calls:
                projected = call["runtime"]
                assert projected is not runtime
                assert type(projected.fault_observer) is ToolFaultObservationPort
                assert projected.emit_event is None and projected.event_emit_fn is None
                assert {name for name in dir(projected.fault_observer) if not name.startswith("_")} == {
                    "observe_tool_run",
                }
                for forbidden in ("fault_report_store", "arbitrary_authority", "_runtime"):
                    assert not hasattr(projected, forbidden)
        else:
            result = await verifier.converge(
                initial, instructions="Private correction instructions",
                task_text="Private task and earlier evidence",
            )
            assert result.status == "converged" and result.rounds == 2
        assert len(executor.calls) == 2
        assert tool.invocations == (episode + 1) * 2 * failures_per_pass
        assert all(type(value) is ObservedWorkItemAgenticOutcome for value in executor.outcomes)
        if failures_per_pass == 2:
            assert all(value.tool_defect.count == 2 for value in executor.outcomes)
        else:
            assert all(value.tool_defect is None for value in executor.outcomes)
        turn = executor.calls[0]["fault_turn"]
        assert executor.calls[1]["fault_turn"] is turn and turn not in tokens
        tokens.append(turn)
        assert all("fault_attempted" not in call for call in executor.calls)
        assert len(events) == (episode + 1 if failures_per_pass == 2 else int(episode == 2))
        assert trust.get_record("producer") is None and trust.get_record("judge") is None
    report = store.list_open()[0]
    assert report.agent_id == "producer" and report.attempted == ""
    assert report.occurrences == (3 if failures_per_pass == 2 else 1)
    assert report.thread_id == ("correction-thread" if session else "")
    trace = json.loads(await runtime.attachment_store.read(report.tool_trace_ref))
    assert find_failing_arguments(trace, tool_id=tool.tool_id, signature=report.signature) == {}
    if session:
        assert ambient_events == []


@pytest.mark.parametrize("error", [
    "short fixture error",
    "9" * 6000 + " logical-state failure " * 600,
    "abcdef" * 1000 + " logical-state failure " * 600,
    "caf\u00e9 \u03bb \u6e2c\u8a66 fixture failure",
], ids=["short", "digit-collapse", "hex-collapse", "unicode"])
async def test_real_alias_trace_and_cross_turn_report_share_untruncated_identity(
    faults, tmp_path: Path, error: str,
) -> None:
    store, events = faults
    runtime, tool = _observer_runtime(store, tool_id="fixture.reader", error=error)
    runtime.attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")
    alias = llm_function_name(tool.tool_id)
    assert alias != tool.tool_id
    arguments = {"request": "fixture-query", "sequence": 7}
    expected = error_signature(tool_id=tool.tool_id, error_text=error)
    for index in range(3):
        outcome = await _run(runtime, [
            _tool_use(alias, arguments), _text_response("Honest fallback"),
        ])
        assert outcome.tool_defect is None and outcome.tool_defect_evaluated
        trace = json.loads(await runtime.attachment_store.read(outcome.tool_trace_ref))
        assert trace[0]["name"] == alias and trace[0]["error_signature"] == expected
        assert find_failing_arguments(
            trace, tool_id=tool.tool_id, signature=expected, observed_as=alias,
        ) == arguments
        assert len(events) == int(index == 2)
    assert tool.invocations == 3
    report = store.list_open()[0]
    assert report.signature == expected and report.tool_id == tool.tool_id
    assert report.observed_as == alias and report.error_text == error[:2000]
    assert find_failing_arguments(
        json.loads(await runtime.attachment_store.read(report.tool_trace_ref)),
        tool_id=report.tool_id, signature=report.signature, observed_as=report.observed_as,
    ) == arguments
    if len(error) > 8192:
        assert len(trace[0]["output"]) <= 8192 < len(error)
        assert error_signature(tool_id=tool.tool_id, error_text=trace[0]["output"]) != expected
        assert error_signature(tool_id=tool.tool_id, error_text=report.error_text) != expected
    with sqlite3.connect(store.db_path) as db:
        assert db.execute(
            "SELECT signature, tool_id, observed_as, occurrences FROM fault_reports"
        ).fetchall() == [(expected, tool.tool_id, alias, 1)]


async def test_real_dm_keeps_only_raw_attempted_text_and_no_pending_rows(faults) -> None:
    store, _events = faults
    runtime, tool = _observer_runtime(store)
    agent = _agent(runtime)
    for index in range(3):
        agent._llm_client = _ScriptedLLM([
            _tool_use_response(tool.tool_id), _text_response("Honest fallback"),
        ])
        await _dm(agent, raw=f"raw-captain-{index}")
        with sqlite3.connect(store.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM fault_reports").fetchone() == (int(index == 2),)
            assert db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall() == [("fault_reports",)]
    report = store.list_open()[0]
    assert report.attempted == "raw-captain-2"
    persisted = json.dumps(report.to_dict())
    for private in (
        "Private assembled instructions", "Private assembled context",
        "code and delegated evidence", "raw-captain-0", "raw-captain-1",
    ):
        assert private not in persisted


@pytest.mark.parametrize(("params", "expected"), [
    ({"captain_message": ""}, ""),
    ({}, ""),
    ({"captain_message": {"private": "PRIVATE_RAW_OBJECT"}}, ""),
    ({"captain_message": " \t\n"}, " \t\n"),
    ({" captain_message": "PRIVATE_LOOKALIKE"}, ""),
])
async def test_real_dm_fault_attempted_uses_only_exact_raw_key(
    faults, params: dict[str, Any], expected: str,
) -> None:
    store, events = faults
    runtime, tool = _observer_runtime(store)
    agent = _agent(runtime)
    params = {
        **params,
        "text": "PRIVATE_ATTACHMENT PRIVATE_RECALL PRIVATE_VISUAL",
        "attachments": [{"name": "image.png", "description": "PRIVATE_IMAGE"}],
    }
    for index in range(3):
        agent._llm_client = _ScriptedLLM([
            _tool_use_response(tool.tool_id), _text_response("Honest fallback"),
        ])
        result = await CognitiveAgent._maybe_run_conversational_agentic(
            agent, {
                "intent": "direct_message", "thread_id": "owned-thread",
                "params": params, "captain_message": "PRIVATE_TOP_LEVEL",
            },
            system_prompt="PRIVATE_SYSTEM",
            user_message="PRIVATE_ASSEMBLED " + params["text"],
        )
        assert result == "Honest fallback" and tool.invocations == index + 1
        assert len(store.list_open()) == int(index == 2)
    assert store.list_open()[0].attempted == expected
    assert "PRIVATE_" not in json.dumps(store.list_open()[0].to_dict())
    assert "PRIVATE_" not in repr(events)


class _FaultMcpBridge:
    def __init__(self) -> None:
        self.calls = 0

    async def invoke(self, *_args: Any) -> Any:
        self.calls += 1
        raise RuntimeError("fixture MCP transport unavailable")


def _mcp_fixture():
    from probos.cognitive.agentic_dispatch import _McpTool
    from probos.integrations.mcp_bridge.risk import McpToolRisk

    class _Risk:
        risk = McpToolRisk.OPEN

        def get_risk_sync(self, _server_id: str, _tool_name: str) -> McpToolRisk:
            return self.risk

    async def no_consensus(*_args):
        raise AssertionError("fixture must never request consensus")

    risk = _Risk()
    bridge = _FaultMcpBridge()
    tool = _McpTool(
        bridge=bridge, server_url="http://unused.invalid", server_name="owned",
        server_id="owned-server", tool_name="write", name="Fixture MCP",
        description="Isolated fixture", input_schema={"type": "object"},
        server_default_risk="open", risk_store=risk,
        consensus_invoke=no_consensus, authorize=lambda _agent: True,
    )
    return tool, bridge, risk


async def _browser_fixture(agent_id: str = "counselor-ezri"):
    from tests.test_ad706_browser_tool import _FakePage, _make_tool

    class _FaultPage(_FakePage):
        failures = 0

        async def screenshot(self) -> bytes:
            self.failures += 1
            raise RuntimeError("fixture browser unavailable")

    page = _FaultPage(list_elements=[{"role": "button", "text": "Pay now", "selector": "#pay"}])
    browser, _, _, events = _make_tool(page=page)
    navigation = await browser.invoke(
        {"action": "goto", "url": "https://bank.example/transfer"},
        {"agent_id": agent_id},
    )
    assert navigation.error is None
    session_id = navigation.metadata["session_id"]
    state = await browser.invoke(
        {"action": "state", "session_id": session_id}, {"agent_id": agent_id},
    )
    assert state.error is None
    return browser, page, session_id, events


async def _grant_fixture(runtime, tool, agent_id="counselor-ezri") -> None:
    runtime.tool_registry.register(tool, provider="test")
    await runtime.tool_permission_store.issue_grant(agent_id, tool.tool_id, ToolPermission.READ)


@pytest.mark.parametrize("structured", [False, True])
async def test_mcp_confirmation_is_neutral_through_real_shared_loop(faults, structured: bool) -> None:
    from probos.config import AgenticLoopConfig
    from probos.integrations.mcp_bridge.risk import McpToolRisk

    store, events = faults
    runtime, _ = _observer_runtime(store)
    runtime.config.agentic_loop = AgenticLoopConfig(structured_tool_messages=structured)
    tool, bridge, risk = _mcp_fixture()
    risk.risk = McpToolRisk.CONFIRM
    await _grant_fixture(runtime, tool)
    alias = llm_function_name(tool.tool_id)
    assert alias != tool.tool_id and tool_fault_adapter_kind(runtime.tool_registry, tool.tool_id) is ToolFaultAdapterKind.MCP
    for _ in range(4):
        result = await _run(runtime, [
            _tool_use_response(alias), _text_response("Awaiting authorization"),
        ])
        assert type(result) is ObservedWorkItemAgenticOutcome
        assert result.tool_defect is None and not result.fault_observation.failed
    assert bridge.calls == 0 and events == [] and store.list_open() == []
    # Exact requires_confirmation is observer-only noise, not a new legacy policy.
    legacy = await _run(runtime, [
        _tool_use_response(alias), _tool_use_response(alias), _text_response("Awaiting authorization"),
    ])
    assert legacy.tool_defect.count == 2 and bridge.calls == 0
    assert store.list_open()[0].occurrences == 1


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("same_batch", [False, True])
async def test_browser_intervention_preserves_pending_failures(
    faults, structured: bool, same_batch: bool,
) -> None:
    from probos.config import AgenticLoopConfig

    store, events = faults
    runtime, _ = _observer_runtime(store)
    runtime.config.agentic_loop = AgenticLoopConfig(structured_tool_messages=structured)
    browser, page, session_id, browser_events = await _browser_fixture()
    await _grant_fixture(runtime, browser)
    try:
        failure = {"action": "screenshot", "session_id": session_id}
        neutral = {"action": "click", "index": 0, "session_id": session_id}
        for _ in range(2):
            await _run(runtime, [_tool_use("browser", failure), _text_response("Honest fallback")])
        assert page.failures == 2 and store.list_open() == []
        if same_batch:
            calls = _FakeLLMResponse(content_blocks=[
                ToolUseBlock(tool_call=ToolCallRequest(name="browser", arguments=neutral)),
                ToolUseBlock(tool_call=ToolCallRequest(name="browser", arguments=failure)),
            ])
            result = await _run(runtime, [calls, _text_response("Honest fallback")])
        else:
            neutral_outcome = await _run(runtime, [
                _tool_use("browser", neutral), _text_response("Awaiting authorization"),
            ])
            assert not neutral_outcome.fault_observation.failed and store.list_open() == []
            result = await _run(runtime, [_tool_use("browser", failure), _text_response("Honest fallback")])
        assert result.tool_defect is None and not result.fault_observation.failed
        assert page.failures == 3 and store.list_open()[0].occurrences == 1
        assert len(events) == 1
        assert not any(call[0] == "click" for call in page.calls)
        assert sum(event.value == "tool_intervention_required" for event, _ in browser_events) == 1
    finally:
        await browser.stop()


@pytest.mark.parametrize(("observation", "expected"), [
    ({}, ""),
    ({"params": None}, ""),
    ({"params": []}, ""),
    ({"params": "PRIVATE_PARAMS"}, ""),
    ({"captain_message": "PRIVATE_TOP", "params": {"text": "PRIVATE_ENRICHED"}}, ""),
    ({"params": {"captain_message ": "PRIVATE_LOOKALIKE"}}, ""),
    ({"params": {"captain_message": ""}}, ""),
    ({"params": {"captain_message": " \t\n"}}, " \t\n"),
    ({"params": {"captain_message": "exact raw request"}}, "exact raw request"),
    ({"params": {"captain_message": 1}}, ""),
])
def test_fault_raw_selector_exact_boundary(observation: dict[str, Any], expected: str) -> None:
    assert _fault_request_text(observation) == expected
    if expected == "":
        assert _promotion_request_text(observation, "PRIVATE_DISPLAY"), "promotion keeps its old fallback"


@pytest.mark.parametrize(("raw", "expected"), [
    ({}, ""), ({"captain_message": ""}, ""), ({"captain_message": []}, ""),
    ({"captain_message": " \t\n"}, " \t\n"),
    ({"captain_message ": "PRIVATE_LOOKALIKE"}, ""),
])
@pytest.mark.parametrize("exhausted", [False, True])
async def test_legacy_dm_raw_selection_and_explicit_exhaustion_override(
    raw: dict[str, Any], expected: str, exhausted: bool, monkeypatch,
) -> None:
    store = _RecordingFaultStore()
    runtime, tool = _observer_runtime(store)
    runtime.config.dm_agentic = DmAgenticConfig(
        enabled=True, max_iterations=2 if exhausted else 3,
        continue_or_ask_enabled=exhausted, continue_or_ask_max_passes=1,
    )
    agent = _agent(runtime)
    agent._llm_client = _ScriptedLLM([
        _use_with_text(tool.tool_id, "Partial evidence"),
        _use_with_text(tool.tool_id, "Still partial"),
        *([] if exhausted else [_text_response("Honest fallback")]),
    ])
    overrides = []
    original = resolve_exhausted_turn

    async def resolve(*args, **kwargs):
        overrides.append(kwargs["fault_attempted"])
        assert kwargs["display_task_text"] == _promotion_request_text(
            {"params": {**raw, "text": "PRIVATE_ENRICHED"}}, "PRIVATE_ASSEMBLED",
        )
        return await original(*args, **kwargs)

    monkeypatch.setattr("probos.cognitive.continue_or_ask.resolve_exhausted_turn", resolve)
    text = await CognitiveAgent._maybe_run_conversational_agentic(
        agent, {"intent": "direct_message", "params": {**raw, "text": "PRIVATE_ENRICHED"}},
        system_prompt="PRIVATE_SYSTEM", user_message="PRIVATE_ASSEMBLED",
    )
    assert text and tool.invocations == 2
    assert len(store.records) == 1 and store.records[0]["attempted"] == expected
    assert "PRIVATE_" not in repr(store.records)
    assert overrides == ([expected] if exhausted else [])


@pytest.mark.parametrize(("override", "display", "expected"), [
    ({}, "PRIVATE_DISPLAY", "PRIVATE_DISPLAY"),
    ({"fault_attempted": None}, "", "PRIVATE_BASE"),
    ({"fault_attempted": ""}, "PRIVATE_DISPLAY", ""),
    ({"fault_attempted": " \t\n"}, "PRIVATE_DISPLAY", " \t\n"),
    ({"fault_attempted": "raw"}, "PRIVATE_DISPLAY", "raw"),
    ({"fault_attempted": {}}, "PRIVATE_DISPLAY", ""),
    ({"fault_attempted": False}, "PRIVATE_DISPLAY", ""),
    ({"fault_attempted": 1}, "PRIVATE_DISPLAY", ""),
])
async def test_exhaustion_fault_override_empty_malformed_and_omitted_compatibility(
    override: dict[str, Any], display: str, expected: str,
) -> None:
    store = _RecordingFaultStore()
    outcome = WorkItemAgenticOutcome(
        final_text="Partial evidence", stopped_reason="max_iterations",
        tool_defect=ToolDefect(tool_id="fixture", error_text="fixture unavailable", count=2),
        tool_defect_evaluated=True,
    )

    async def no_reinvoke(_text):
        raise AssertionError("one-pass exhaustion must not reinvoke")

    text = await resolve_exhausted_turn(
        outcome, reinvoke=no_reinvoke, runtime=SimpleNamespace(fault_report_store=store),
        agent_id="agent", base_task_text="PRIVATE_BASE", display_task_text=display,
        config=SimpleNamespace(continue_or_ask_enabled=True, continue_or_ask_max_passes=1),
        **override,
    )
    assert text and len(store.records) == 1 and store.records[0]["attempted"] == expected


async def test_fault_raw_selector_runs_once_across_continuations(faults, tmp_path, monkeypatch) -> None:
    store, _events = faults
    runtime, tool = _observer_runtime(store)
    runtime.config.dm_agentic = DmAgenticConfig(
        enabled=True, max_iterations=1,
        continue_or_ask_enabled=True, continue_or_ask_max_passes=3,
    )
    approvals = await _standing_rule(tmp_path)
    runtime.action_approval_store = approvals
    agent = _agent(runtime)
    agent._llm_client = _ScriptedLLM([
        _use_with_text(tool.tool_id, f"Partial step {index}") for index in range(3)
    ])
    calls = []

    def select(observation):
        calls.append(observation)
        return _fault_request_text(observation)

    monkeypatch.setattr("probos.cognitive.cognitive_agent._fault_request_text", select)
    try:
        assert await _dm(agent, raw="")
        assert tool.invocations == 3 and len(calls) == 1
    finally:
        await approvals.stop()


@pytest.mark.parametrize("adapter", ["mcp", "browser"])
@pytest.mark.parametrize("repair_enabled", [False, True])
@pytest.mark.parametrize("raw_present", [False, True], ids=["raw-missing", "raw-empty"])
@pytest.mark.parametrize("structured", [False, True])
async def test_real_governed_fault_chain_neutral_turn_privacy_and_one_approval(
    tmp_path: Path, adapter: str, repair_enabled: bool, raw_present: bool, structured: bool,
) -> None:
    from probos.config import AgenticLoopConfig
    from probos.integrations.mcp_bridge.risk import McpToolRisk

    bus = _LocalFaultEvents()  # Isolated listener drain, not live runtime transport.
    fault_path, request_path = tmp_path / "faults.db", tmp_path / "requests.db"
    assert fault_path.parent == tmp_path and request_path.parent == tmp_path
    store = FaultReportStore(str(fault_path), emit_event=bus.emit)
    requests = CapabilityRequestStore(str(request_path))
    runtime, _ = _observer_runtime(store)
    runtime.config.agentic_loop = AgenticLoopConfig(structured_tool_messages=structured)
    runtime.config.repair = RepairConfig(enabled=repair_enabled)
    runtime.add_event_listener = bus.add_event_listener
    runtime.capability_request_store = requests
    browser = None
    if adapter == "mcp":
        tool, bridge, risk = _mcp_fixture()
        failure_params = neutral_params = {}
    else:
        browser, page, session_id, _ = await _browser_fixture()
        tool = browser
        failure_params = {"action": "screenshot", "session_id": session_id}
        neutral_params = {"action": "click", "index": 0, "session_id": session_id}
    await _grant_fixture(runtime, tool)
    alias = llm_function_name(tool.tool_id)
    agent = _agent(runtime)
    await store.start()
    await requests.start()
    dispatcher = wire_repair_dispatcher(runtime, runtime.config)
    assert dispatcher is not None and len(bus.listeners) == 1
    params = {
        "text": "PRIVATE_ATTACHMENT PRIVATE_RECALL PRIVATE_VISUAL",
        "attachments": [{"name": "image.png", "description": "PRIVATE_IMAGE"}],
        **({"captain_message": ""} if raw_present else {}),
    }
    try:
        for index, neutral in enumerate((False, False, True, False, False)):
            if adapter == "mcp":
                risk.risk = McpToolRisk.CONFIRM if neutral else McpToolRisk.OPEN
            agent._llm_client = _ScriptedLLM([
                _tool_use(alias, neutral_params if neutral else failure_params),
                _text_response("Honest fallback"),
            ])
            text = await CognitiveAgent._maybe_run_conversational_agentic(
                agent, {"intent": "direct_message", "thread_id": "owned-thread", "params": params},
                system_prompt="PRIVATE_SYSTEM", user_message="PRIVATE_ASSEMBLED " + params["text"],
            )
            assert text == "Honest fallback"
            genuine = (1, 2, 2, 3, 4)[index]
            assert (bridge.calls if adapter == "mcp" else page.failures) == genuine
            await bus.drain()
            assert len(store.list_open()) == int(genuine >= 3)
            assert len(bus.events) == max(0, genuine - 2)
            pending = await requests.list_pending()
            assert len(pending) == int(repair_enabled and genuine >= 4)
            if genuine >= 3:
                report = store.list_open()[0]
                assert report.occurrences == genuine - 2 and report.attempted == ""
                assert "PRIVATE_" not in json.dumps(report.to_dict())
            assert "PRIVATE_" not in repr(bus.events) + repr(pending)
        report = store.list_open()[0]
        assert report.tool_id == tool.tool_id and report.occurrences == 2
        for event in bus.events:
            assert set(event["data"]) == {"fault_id", "tool_id", "signature", "occurrences", "status"}
        if repair_enabled:
            request = (await requests.list_pending())[0]
            assert request.status == "pending" and request.kind == "action"
            assert request.payload["scope_key"] == tool.tool_id
            assert request.payload["params"]["targets"] == ",".join(dispatcher.targets)
            assert request.payload["params"]["fault_id"] == report.id
        if browser is not None:
            assert not any(call[0] == "click" for call in page.calls)
    finally:
        if browser is not None:
            await browser.stop()
        await store.stop()
        await requests.stop()
    reopened = FaultReportStore(str(fault_path))
    reopened_requests = CapabilityRequestStore(str(request_path))
    await reopened.start()
    await reopened_requests.start()
    try:
        assert reopened.list_open()[0].attempted == ""
        assert reopened.list_open()[0].occurrences == 2
        assert len(await reopened_requests.list_pending()) == int(repair_enabled)
        with sqlite3.connect(fault_path) as db:
            rows = db.execute("SELECT * FROM fault_reports").fetchall()
            assert len(rows) == 1 and "PRIVATE_" not in repr(rows)
    finally:
        await reopened.stop()
        await reopened_requests.stop()


async def test_adapter_query_projection_limits_aliases_and_current_registration(faults) -> None:
    from probos.cognitive.crew_verifier import (
        _ProjectedToolDefinition, _SessionProjectedToolRegistry, _session_correction_runtime,
    )
    from probos.integrations.mcp_bridge.risk import McpToolRisk
    from probos.tools.protocol import ToolType

    store, events = faults
    runtime, fake = _observer_runtime(store)
    tool, bridge, risk = _mcp_fixture()
    risk.risk = McpToolRisk.CONFIRM
    await _grant_fixture(runtime, tool)
    projected = _session_correction_runtime(
        runtime, agent_id="counselor-ezri", department="counseling", rank="lieutenant",
    )
    registry = projected.tool_registry
    assert type(registry.get_tool(tool.tool_id)) is _ProjectedToolDefinition
    assert registry.tool_fault_adapter_kind(tool.tool_id) is ToolFaultAdapterKind.MCP
    assert registry.tool_fault_adapter_kind("missing") is None
    assert tool_fault_adapter_kind(None, tool.tool_id) is None
    assert tool_fault_adapter_kind(runtime.tool_registry, fake.tool_id) is None
    alias = llm_function_name(tool.tool_id)
    for _ in range(4):
        result = await _run(projected, [
            _tool_use_response(alias), _text_response("Awaiting authorization"),
        ])
        assert not result.fault_observation.failed
    assert bridge.calls == 0 and store.list_open() == [] and events == []

    definition = registry.get_tool(tool.tool_id)
    for backed, denied in ((False, False), (True, True)):
        restricted = _SessionProjectedToolRegistry(
            source_registry=runtime.tool_registry,
            source_backed_ids=frozenset({tool.tool_id}) if backed else frozenset(),
            explicit_denial_ids=frozenset({tool.tool_id}) if denied else frozenset(),
        )
        restricted.register(definition, provider="test")
        assert restricted.tool_fault_adapter_kind(tool.tool_id) is None
    disabled = _SessionProjectedToolRegistry(
        source_registry=runtime.tool_registry,
        source_backed_ids=frozenset({tool.tool_id}), explicit_denial_ids=frozenset(),
    )
    disabled.register(definition, provider="test", enabled=False)
    assert disabled.tool_fault_adapter_kind(tool.tool_id) is None
    runtime.tool_registry.register(tool, provider="test", enabled=False)
    assert tool_fault_adapter_kind(runtime.tool_registry, tool.tool_id) is None
    assert registry.tool_fault_adapter_kind(tool.tool_id) is None
    runtime.tool_registry.register(tool, provider="test")
    assert registry.tool_fault_adapter_kind(tool.tool_id) is ToolFaultAdapterKind.MCP
    replacement = _FailingTool(tool.tool_id)
    runtime.tool_registry.register(replacement, provider="test")
    assert registry.tool_fault_adapter_kind(tool.tool_id) is None
    # A type label/name plus adapter-shaped flags is not an adapter identity.
    class _PretendBrowser(_FailingTool):
        tool_type = ToolType.BROWSER

    runtime.tool_registry.register(_PretendBrowser("browser"), provider="test")
    capture = tool_fault_capture(runtime.tool_registry, resolve_tool_id=tool_fault_id_resolver(runtime.tool_registry))
    raw = ToolResult(
        output={"intervention_required": True, "tier": 3, "session_id": "fixture"},
        metadata={"tier": 3, "session_id": "fixture"},
    )
    capture.record("call", "browser", raw)
    assert not capture.is_neutral("call", "browser")


@pytest.mark.parametrize("session", [False, True], ids=["legacy", "projected"])
async def test_real_correction_refusal_preserves_episode_vote(faults, work_items, session: bool) -> None:
    from probos.cognitive.crew_executor import SubtaskResult
    from probos.cognitive.crew_verifier import SubtaskVerifier
    from probos.consensus.trust import TrustNetwork
    from tests.test_ad1126_verified_finalization import _Agent, _Registry

    store, events = faults
    runtime, _ = _observer_runtime(store)
    browser, page, session_id, browser_events = await _browser_fixture(agent_id="producer")
    await _grant_fixture(runtime, browser, "producer")
    agents = _Registry([_Agent("producer"), _Agent("judge")])
    try:
        for episode in range(3):
            child = await work_items.create_work_item(title="Correction", work_type="task")
            initial = SubtaskResult(
                work_item_id=child.id, spec_id="s1", agent_id="producer",
                output="Initial incomplete evidence", status="done",
            )
            responses = []
            for params in (
                {"action": "screenshot", "session_id": session_id},
                {"action": "click", "index": 0, "session_id": session_id},
            ):
                responses.extend([
                    _FakeLLMResponse(content_blocks=[ToolUseBlock(tool_call=ToolCallRequest(
                        id="reused-provider-id", name="browser", arguments=params,
                    ))]),
                    _text_response("Honest correction evidence"),
                ])
            executor = _ObservedExecutor(responses)
            verifier = SubtaskVerifier(
                llm_client=_ScriptedLLM([
                    _text_response(json.dumps({
                        "accepted": accepted, "confidence": 0.8,
                        "critique": "Supply remaining evidence." if not accepted else "Checked.",
                    })) for accepted in (False, False, True)
                ]),
                work_item_store=work_items, agent_registry=agents,
                trust_network=TrustNetwork(), agentic_executor=executor, runtime=runtime,
                max_convergence_rounds=2,
            )
            if session:
                result = await verifier.converge_for_session(
                    initial, instructions="Private instructions", task_text="Private context",
                    expected_output="Checked", parent_id="parent", thread_id="owned-thread",
                    department="engineering", rank="ensign",
                )
                assert result.accepted and result.rounds_used == 2
            else:
                result = await verifier.converge(initial, instructions="", task_text="Private context")
                assert result.status == "converged" and result.rounds == 2
            assert len(executor.outcomes) == 2 and page.failures == episode + 1
            assert all(not outcome.fault_observation.failed for outcome in executor.outcomes)
            assert executor.calls[0]["fault_turn"] is executor.calls[1]["fault_turn"]
            assert len(events) == int(episode == 2)
        assert store.list_open()[0].occurrences == 1
        assert not any(call[0] == "click" for call in page.calls)
        assert sum(event.value == "tool_intervention_required" for event, _ in browser_events) == 3
    finally:
        await browser.stop()


@pytest.mark.parametrize("structured", [False, True])
async def test_raw_capture_preserves_result_transcript_and_event_bytes(structured: bool, monkeypatch) -> None:
    from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
    from probos.types import LLMResponse
    from tests.test_ad1147_parallel_tools import _CapturingClient, _RecordingEmit, _final_response

    class _Executor:
        async def invoke(self, **_kwargs):
            return ToolResult(
                output={"intervention_required": True, "tier": 3, "session_id": "not-an-adapter"},
                metadata={"tier": 3, "session_id": "not-an-adapter"},
            )

    monkeypatch.setattr("probos.cognitive.swe_harness.agentic_loop.time.perf_counter", lambda: 42.0)
    values = []
    for supported in (False, True):
        # Timestamp is input evidence too: compare identical requests rather
        # than two independently sampled wall clocks, without dropping a field.
        client = _CapturingClient(responses=[
            LLMResponse(content="", tokens_used=1, content_blocks=[
                ToolUseBlock(tool_call=ToolCallRequest(
                    name="fixture", arguments={}, id="call-0", timestamp=42.0,
                )),
            ]),
            _final_response(),
        ])
        events = _RecordingEmit()
        capture = ToolFaultCapture(adapter_kind=lambda _name: None)
        loop = AgenticLoop(
            llm_client=client, tool_executor=_Executor(), event_emit_fn=events,
            structured_tool_messages=structured,
        )
        result = await loop.run(
            system_prompt="Instructions", user_message="Task", tools=[], context={"agent_id": "agent"},
            **({"fault_capture": capture} if supported else {}),
        )
        values.append((
            dataclasses.asdict(result), events.events,
            [(r.prompt, r.messages, r.system_prompt, r.tools, r.tool_choice) for r in client.requests],
        ))
        if supported:
            assert not capture.is_neutral("call-0", "fixture")
        assert result.tool_results[0].is_error is False
    assert values[0] == values[1]


@pytest.mark.parametrize("structured", [False, True])
async def test_parallel_capture_follows_request_identity_not_completion_order(structured: bool) -> None:
    from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
    from probos.fault_detection import collect_tool_fault_batch
    from tests.test_ad1147_parallel_tools import _CapturingClient, _TimingExecutor, _final_response, _tool_response

    calls = []
    executor = _TimingExecutor(delays={"web_search": 0.04, "read_page": 0.001})
    capture = ToolFaultCapture(adapter_kind=lambda name: calls.append(name))
    client = _CapturingClient(responses=[
        _tool_response("web_search", "read_page", "write_file"), _final_response(),
    ])
    loop = AgenticLoop(
        llm_client=client, tool_executor=executor, parallel_tool_calls_enabled=True,
        structured_tool_messages=structured,
    )
    result = await loop.run(
        system_prompt="", user_message="", tools=[], context={"agent_id": "agent"},
        fault_capture=capture,
    )
    assert executor.peak_concurrency == 2 and executor.finished == ["read_page", "web_search", "write_file"]
    assert calls == executor.finished
    assert [item.id for item in result.tool_results] == ["call-0", "call-1", "call-2"]
    batch = collect_tool_fault_batch(result, classify_error=classify_tool_fault_error, fault_capture=capture)
    assert [item.tool_id for item in batch.tools] == ["web_search", "read_page", "write_file"]
    assert all(item.succeeded for item in batch.tools)


@pytest.mark.parametrize("path", ["shared", "native"])
async def test_reused_executor_owns_distinct_captures_for_overlapping_runs(faults, tmp_path, monkeypatch, path: str) -> None:
    from probos.cognitive.builder import BuildSpec
    from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness
    from probos.tools.executor import ToolExecutor

    class _ReadBarrier(_WaitingTool):
        @property
        def tool_id(self):
            return "read_file"

    store, events = faults
    tool = _ReadBarrier(goal=2)
    runtime = _waiting_runtime(store, tool)
    capture_calls = []
    record = ToolFaultCapture.record

    def capture_record(self, request_id, name, raw_result):
        capture_calls.append((self, request_id, name, type(raw_result)))
        record(self, request_id, name, raw_result)

    monkeypatch.setattr(ToolFaultCapture, "record", capture_record)
    response = _FakeLLMResponse(content_blocks=[ToolUseBlock(tool_call=ToolCallRequest(
        id="same-provider-id-across-runs", name="read_file", arguments={},
    ))])
    llm = _ScriptedLLM([
        response, response, _text_response("Fallback"), _text_response("Fallback"),
        response, _text_response("Fallback"),
    ])
    if path == "native":
        repository = tmp_path / "repository"
        repository.mkdir()
        harness = NativeBuilderHarness(
            runtime=runtime, llm_client=llm, tool_executor=ToolExecutor(registry=runtime.tool_registry),
            tool_registry=runtime.tool_registry,
        )

        async def run():
            return await harness.run_build(BuildSpec(title="Fixture", description=""), str(repository))
    else:
        executor = WorkItemAgenticExecutor(llm_client=llm)

        async def run():
            return await executor.run(agent_id="agent", instructions="", task_text="", runtime=runtime)

    tasks = [asyncio.create_task(run()), asyncio.create_task(run())]
    try:
        await asyncio.wait_for(tool.entered.wait(), 3)
        assert tool.invocations == 2 and capture_calls == []
        tool.release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 3)
        await run()
    finally:
        tool.release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert len(capture_calls) == 3 and len({id(call[0]) for call in capture_calls}) == 3
    assert all(call[1:] == ("same-provider-id-across-runs", "read_file", ToolResult) for call in capture_calls)
    assert len(events) == 1 and store.list_open()[0].occurrences == 1


@pytest.mark.parametrize("failure", ["query", "record", "overflow", "duplicate-id"])
async def test_real_capture_failure_preserves_execution_and_suppresses_legacy(faults, failure: str, monkeypatch) -> None:
    store, events = faults
    runtime, tool = _observer_runtime(store)
    count = 1025 if failure == "overflow" else 2
    if failure in ("query", "record"):
        def broken(*_args, **_kwargs):
            raise RuntimeError("fixture diagnostic capture failure")

        monkeypatch.setattr(
            "probos.cognitive.agentic_dispatch.tool_fault_adapter_kind"
            if failure == "query" else "probos.fault_detection.ToolFaultCapture.record",
            broken,
        )
    response = _FakeLLMResponse(content="Partial work", content_blocks=[
        TextBlock(text="Partial work"),
        *[ToolUseBlock(tool_call=ToolCallRequest(
            id="duplicate" if failure == "duplicate-id" else f"call-{index}",
            name=tool.tool_id, arguments={},
        )) for index in range(count)],
    ])
    outcome = await _run(runtime, [response], max_iterations=1)
    assert tool.invocations == count
    if failure != "duplicate-id":
        assert outcome.tool_defect.count == count
    assert outcome.stopped_reason == "max_iterations" and outcome.final_text == "Partial work"
    assert type(outcome) is ObservedWorkItemAgenticOutcome and outcome.fault_observation.failed
    assert store.list_open() == [] and events == []
    await _reuse_handled_outcome(outcome, runtime)
    assert store.list_open() == [] and events == []


@pytest.mark.parametrize("path", ["shared", "native"])
async def test_unsupported_shared_and_native_preserve_loop_kwargs(tmp_path, monkeypatch, path: str) -> None:
    from probos.cognitive.builder import BuildSpec
    from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
    from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness
    from probos.tools.executor import ToolExecutor

    runtime, _ = _observer_runtime(_RecordingFaultStore())
    calls = []
    original = AgenticLoop.run

    async def run(self, **kwargs):
        calls.append(kwargs)
        return await original(self, **kwargs)

    def forbidden_capture(*_args, **_kwargs):
        raise AssertionError("unsupported observer must not allocate raw capture")

    monkeypatch.setattr(AgenticLoop, "run", run)
    monkeypatch.setattr(ToolFaultCapture, "__init__", forbidden_capture)
    if path == "shared":
        result = await _run(runtime, [_text_response("Done")])
        assert type(result) is WorkItemAgenticOutcome
    else:
        repository = tmp_path / "repository"
        repository.mkdir()
        harness = NativeBuilderHarness(
            runtime=runtime, llm_client=_ScriptedLLM([_text_response("Done")]),
            tool_executor=ToolExecutor(registry=runtime.tool_registry), tool_registry=runtime.tool_registry,
        )
        result = await harness.run_build(BuildSpec(title="Fixture", description=""), str(repository))
        assert result["llm_output"] == "Done"
    assert len(calls) == 1 and "fault_capture" not in calls[0]


@pytest.mark.parametrize("interruption", [
    [None], ["different failure"], ["fixture subsystem unavailable", "different failure"],
    ["fixture subsystem unavailable", None],
], ids=["success", "different-error", "mixed-errors", "mixed-success"])
async def test_real_executor_resets_pending_streak_without_forging_legacy_verdicts(
    faults, interruption: list[str | None],
) -> None:
    store, events = faults
    error = "fixture subsystem unavailable"
    tool = _SequencedTool("sequence_probe", [error, error, *interruption, error, error, error])
    registry = ToolRegistry()
    registry.register(tool, provider="test")
    runtime = _exec_runtime(registry, ToolPermissionStore())
    runtime.fault_report_store = store
    for count in (1, 1, len(interruption), 1, 1):
        outcome = await _run(runtime, [
            *[_tool_use_response(tool.tool_id) for _ in range(count)],
            _text_response("Honest fallback"),
        ])
        assert outcome.tool_defect is None
        assert store.list_open() == []
    outcome = await _run(runtime, [
        _tool_use_response(tool.tool_id), _text_response("Honest fallback"),
    ])
    assert outcome.tool_defect is None and len(events) == 1
    assert store.list_open()[0].occurrences == 1
    assert tool.invocations == 5 + len(interruption)


@pytest.mark.parametrize("noise_name", [
    "_APPROVAL_PARKED_REFUSAL", "_APPROVAL_PARKED_REFUSAL_NO_ID",
    "_APPROVAL_INBOX_FULL_REFUSAL", "_APPROVAL_CREDENTIAL_REFUSAL",
    "_BROWSER_READ_ONLY_REFUSAL", "consensus_blocked",
])
async def test_real_loop_policy_refusals_do_not_become_systemic_faults(faults, noise_name: str) -> None:
    from probos.cognitive import agentic_dispatch

    store, events = faults
    noise = (
        noise_name if noise_name == "consensus_blocked"
        else getattr(agentic_dispatch, noise_name).format(request_id="existing-approval")
    )
    assert classify_tool_fault_error(noise) == "permission_denied"
    runtime, tool = _observer_runtime(store, error=noise)
    for _ in range(3):
        outcome = await _run(runtime, [
            _tool_use_response(tool.tool_id), _text_response("Awaiting authorization."),
        ])
        assert outcome.tool_defect is None and outcome.stopped_reason == "complete"
    assert tool.invocations == 3 and store.list_open() == [] and events == []


async def test_real_permission_denial_is_not_invocation_or_cross_turn_failure(faults) -> None:
    store, events = faults
    tool = _FailingTool("denied_probe")
    registry = ToolRegistry()
    registry.register(tool, provider="test", default_permissions={"ensign": "none"})
    runtime = _exec_runtime(registry, ToolPermissionStore())
    runtime.fault_report_store = store
    for _ in range(3):
        outcome = await _run(runtime, [
            _tool_use_response(tool.tool_id), _text_response("Authorization required."),
        ])
        assert outcome.denied_tools == [tool.tool_id]
        assert outcome.tool_defect is None
    assert tool.invocations == 0 and events == [] and store.list_open() == []


@pytest.mark.parametrize("status", ["repaired", "dismissed"])
async def test_real_closure_then_restart_needs_fresh_qualification(tmp_path: Path, status: str) -> None:
    path = tmp_path / "restart-closure.db"
    store = FaultReportStore(str(path))
    await store.start()
    runtime, tool = _observer_runtime(store)

    async def once() -> None:
        outcome = await _run(runtime, [
            _tool_use_response(tool.tool_id), _text_response("Honest fallback"),
        ])
        assert outcome.tool_defect is None

    try:
        for _ in range(3):
            await once()
        old = store.list_open()[0]
        await store.resolve(old.id, status=status)
        await once()
        await once()
        assert store.list_open() == []
    finally:
        await store.stop()
    reopened = FaultReportStore(str(path))
    await reopened.start()
    runtime.fault_report_store = reopened
    try:
        assert reopened.get(old.id).status == status
        await once()
        await once()
        assert reopened.list_open() == []
        await once()
        current = reopened.list_open()[0]
        assert current.id != old.id and current.occurrences == 1
        with sqlite3.connect(path) as db:
            assert db.execute(
                "SELECT status, occurrences FROM fault_reports ORDER BY first_seen_at"
            ).fetchall() == [(status, 1), ("open", 1)]
            assert db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall() == [("fault_reports",)]
    finally:
        await reopened.stop()


class _WaitingTool(_FailingTool):
    def __init__(self, goal: int = 1) -> None:
        super().__init__("waiting_probe", "fixture subsystem unavailable")
        self.goal = goal
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = 0

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.invocations += 1
        if self.invocations >= self.goal:
            self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return ToolResult(output="", error="fixture subsystem unavailable")


def _waiting_runtime(store: FaultReportStore, tool: _WaitingTool) -> SimpleNamespace:
    registry = ToolRegistry()
    registry.register(tool, provider="test")
    runtime = _exec_runtime(registry, ToolPermissionStore())
    runtime.fault_report_store = store
    return runtime


async def test_real_execution_cancellation_is_not_a_completed_observation(faults) -> None:
    store, events = faults
    tool = _WaitingTool()
    runtime = _waiting_runtime(store, tool)
    task = asyncio.create_task(_run(runtime, [_tool_use_response(tool.tool_id)]))
    try:
        await asyncio.wait_for(tool.entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        tool.release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert tool.cancelled == 1 and store.list_open() == []
    for index in range(3):
        await _run(runtime, [
            _tool_use_response(tool.tool_id), _text_response("Honest fallback"),
        ])
        assert len(events) == int(index == 2)
    assert tool.invocations == 4 and store.list_open()[0].occurrences == 1


async def test_real_overlapping_execution_is_not_serialized_by_diagnosis(faults) -> None:
    store, events = faults
    tool = _WaitingTool(goal=3)
    runtime = _waiting_runtime(store, tool)
    tasks = [
        asyncio.create_task(_run(runtime, [
            _tool_use_response(tool.tool_id), _text_response("Honest fallback"),
        ]))
        for _ in range(3)
    ]
    try:
        await asyncio.wait_for(tool.entered.wait(), 2)
        assert tool.invocations == 3 and events == [], "premise: all tools overlap before publication"
        tool.release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks), 2)
    finally:
        tool.release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert len(events) == 1 and store.list_open()[0].occurrences == 1
    for outcome in outcomes:
        await _file_pass_defect(
            outcome, {}, runtime=runtime, agent_id="counselor-ezri",
            thread_id="owned-thread", attempted="unused legacy description",
        )
    assert len(events) == 1 and store.list_open()[0].occurrences == 1


async def _reuse_handled_outcome(outcome: WorkItemAgenticOutcome, runtime: Any) -> str:
    filed: dict[str, str] = {}
    for _ in range(2):
        await _file_pass_defect(
            outcome, filed, runtime=runtime, agent_id="counselor-ezri",
            thread_id="owned-thread", attempted="unused legacy description",
        )

    async def no_reinvoke(_text: str) -> WorkItemAgenticOutcome:
        raise AssertionError("diagnostic publication must not re-execute the task")

    return await resolve_exhausted_turn(
        outcome, reinvoke=no_reinvoke, runtime=runtime, agent_id="counselor-ezri",
        base_task_text="private assembled task", config=SimpleNamespace(
            continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        ),
    )


@pytest.mark.parametrize("failure", ["persistence", "emitter"])
async def test_real_store_internal_failure_id_is_not_a_delivery_receipt(
    tmp_path: Path, failure: str, caplog,
) -> None:
    path = tmp_path / "failure.db"
    emissions = []

    def emit(event: Any, data: dict[str, Any]) -> None:
        emissions.append((event, data))
        if failure == "emitter":
            raise RuntimeError("fixture event delivery failed")

    store = FaultReportStore(str(path), emit_event=emit)
    await store.start()
    try:
        if failure == "persistence":
            with sqlite3.connect(path) as db:
                db.execute(
                    "CREATE TRIGGER fail_insert BEFORE INSERT ON fault_reports "
                    "BEGIN SELECT RAISE(FAIL, 'fixture persistence failed'); END"
                )
        runtime, tool = _observer_runtime(store)
        outcome = await _run(runtime, [
            _use_with_text(tool.tool_id, "Partial work."),
            _use_with_text(tool.tool_id, "Still partial."),
        ], max_iterations=2)
        report = store.list_open()[0]
        assert type(outcome) is ObservedWorkItemAgenticOutcome
        assert outcome.fault_observation.fault_id(report.signature) == report.id
        # The unchanged store degrades internally; an ID alone proves neither write nor delivery.
        assert not outcome.fault_observation.failed
        await _reuse_handled_outcome(outcome, runtime)
        assert len(emissions) == 1 and report.occurrences == 1
        if failure == "persistence":
            assert any("memory for this session only" in record.message for record in caplog.records)
    finally:
        await store.stop()
    reopened = FaultReportStore(str(path))
    await reopened.start()
    try:
        assert len(reopened.list_open()) == int(failure == "emitter")
    finally:
        await reopened.stop()


class _InterruptedPublicationStore(FaultReportStore):
    def __init__(self, path: Path, mode: str) -> None:
        super().__init__(str(path))
        self.mode = mode
        self.publications = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def file_fault(self, **kwargs: Any) -> FaultReport:
        self.publications += 1
        if self.mode == "raise":
            raise RuntimeError("fixture publisher unavailable")
        if self.mode == "cancel":
            self.entered.set()
            await self.release.wait()
        return await super().file_fault(**kwargs)


@pytest.mark.parametrize("mode", ["raise", "cancel"])
async def test_real_publication_interruption_keeps_reservation_through_later_pass_and_hooks(
    tmp_path: Path, mode: str,
) -> None:
    store = _InterruptedPublicationStore(tmp_path / "interrupted.db", mode)
    await store.start()
    runtime, tool = _observer_runtime(store)
    turn = ToolFaultTurn()

    async def run(token: ToolFaultTurn) -> WorkItemAgenticOutcome:
        return await _run(runtime, [
            _use_with_text(tool.tool_id, "Partial work."),
            _use_with_text(tool.tool_id, "Still partial."),
        ], max_iterations=2, fault_turn=token)

    task = asyncio.create_task(run(turn))
    try:
        if mode == "cancel":
            await asyncio.wait_for(store.entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            first = await task
            assert first.fault_observation.failed
        assert store.publications == 1 and store.list_open() == []
        store.mode = ""
        store.release.set()
        later = await asyncio.wait_for(run(turn), 2)
        assert later.fault_observation.failed
        assert later.fault_observation.fault_id(later.tool_defect.signature) == ""
        await _reuse_handled_outcome(later, runtime)
        assert store.publications == 1 and store.list_open() == []
        await asyncio.wait_for(run(ToolFaultTurn()), 2)
        assert store.publications == 2 and store.list_open()[0].occurrences == 1
    finally:
        store.release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await store.stop()


@pytest.mark.parametrize("sink", [
    None, object(), SimpleNamespace(observe_tool_run=None), SimpleNamespace(observe_tool_run=7),
])
async def test_unsupported_observation_surface_allocates_no_turn_or_kwargs(sink, monkeypatch) -> None:
    runtime, _tool = _observer_runtime(sink)
    calls = []
    original = WorkItemAgenticExecutor._run_reserved

    async def record(self, **kwargs):
        calls.append(kwargs)
        return await original(self, **kwargs)

    class UnexpectedTurn:
        def __init__(self):
            raise AssertionError("unsupported observer must not allocate a turn")

    monkeypatch.setattr(WorkItemAgenticExecutor, "_run_reserved", record)
    monkeypatch.setattr("probos.cognitive.agentic_dispatch.ToolFaultTurn", UnexpectedTurn)
    outcome = await _run(runtime, [_text_response("Uninstrumented completion")])
    assert type(outcome) is WorkItemAgenticOutcome
    assert "fault_turn" not in calls[0] and "fault_attempted" not in calls[0]


@pytest.mark.parametrize("payload", [None, {}, SimpleNamespace(attempts=(), failed=False)])
async def test_real_executor_rejects_malformed_sink_result_without_legacy_refiling(payload, caplog) -> None:
    legacy_store = _RecordingFaultStore()
    runtime, tool = _observer_runtime(legacy_store)

    class MalformedSink:
        async def observe_tool_run(self, **kwargs: Any) -> Any:
            return payload

    runtime.fault_observer = MalformedSink()
    outcome = await _run(runtime, [
        _use_with_text(tool.tool_id, "Partial work."),
        _use_with_text(tool.tool_id, "Still partial."),
    ], max_iterations=2)
    assert type(outcome) is ObservedWorkItemAgenticOutcome
    assert outcome.fault_observation == FaultObservationResult(failed=True)
    await _reuse_handled_outcome(outcome, runtime)
    assert legacy_store.records == [] and tool.invocations == 2
    assert any("legacy publication is suppressed" in r.message for r in caplog.records)
