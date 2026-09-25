"""Issue #1417: every run_python child has an owner that can stop it.

Before #1417 only an AD-1246 long run carried a ``KillSwitch``. Every other
``CodeExecutionTool.invoke`` run and the mesh ``CodeRunnerAgent`` script had
none, so cancelling the awaiter (BF-733's watchdog, the IntentBus TTL) orphaned
the child, and ``shutdown()``'s long-run close could not reach it before
``os._exit``. These tests drive real ``SubprocessSandbox`` children through the
real tool, mesh agent, ``run_with_promotion`` and ``shutdown()``. The fakes are
copied from the #1417 probes and the AD-1246 tests, never imported.
``SHUTDOWN_REFUSAL`` and ``track_inline_run`` are imported inside the tests that
use them, so the file collects at the base and T7/T8 run there unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.agents.code_runner import CodeRunnerAgent
from probos.artifacts import ArtifactStore
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock
from probos.cognitive.turn_promotion import _ACK_TEMPLATE, _REPORT_ABANDONED, run_with_promotion
from probos.config import ExecutionConfig
from probos.execution.isolation import KillSwitch, SubprocessSandbox
from probos.execution.long_runs import LongRunService
from probos.startup.shutdown import shutdown
from probos.tools.code_execution_tool import CodeExecutionTool
from probos.tools.permissions import ToolPermissionStore
from probos.tools.registry import ToolRegistry
from probos.types import IntentMessage
from probos.workforce import WorkItem

_LONG_RUNS_LOGGER = "probos.execution.long_runs"
_CONTEXT = {"agent_id": "issue1417-agent", "thread_id": ""}


@pytest.fixture(scope="module", autouse=True)
def _assert_tested_source_matches_worktree() -> None:
    import probos.agents.code_runner as runner_module
    import probos.execution.isolation as isolation_module
    import probos.execution.long_runs as long_runs_module
    import probos.tools.code_execution_tool as tool_module

    source = Path(__file__).resolve().parents[1] / "src"
    for module in (runner_module, isolation_module, long_runs_module, tool_module):
        assert Path(module.__file__).resolve().is_relative_to(source), module.__name__


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class _Child:
    """A real sandbox child: it writes its pid, then appends one numbered line every 0.1 s.

    It starts nothing itself, so no grandchild holds the sandbox pipes (contract H-7).
    """

    def __init__(self, root: Path, beats: int) -> None:
        # Contract 5.1: a child that survives must stay visible, about 6 s at least.
        assert beats >= 60
        self.total = beats
        self.beat_file = root / "beats.txt"
        self.pid_file = root / "child.pid"
        self.code = (
            "import os, time\n"
            f"with open({str(self.pid_file)!r}, 'w', encoding='utf-8') as handle:\n"
            "    handle.write(str(os.getpid()))\n"
            f"path = {str(self.beat_file)!r}\n"
            f"for i in range({beats}):\n"
            "    with open(path, 'a', encoding='utf-8') as handle:\n"
            "        handle.write(f'{i}\\n')\n"
            "    time.sleep(0.1)\n"
            f"print('beats done: {beats}')\n"
        )

    def beats(self) -> int:
        return self.beat_file.read_bytes().count(b"\n") if self.beat_file.exists() else 0

    async def wait_for_beats(self, count: int = 3, *, timeout: float = 10.0) -> None:
        """Premise: the child is running."""
        deadline = time.monotonic() + timeout
        while self.beats() < count:
            assert time.monotonic() < deadline, f"premise: the child never reached {count} beats"
            await asyncio.sleep(0.05)

    async def counts_after(self, moment: float) -> tuple[int, int]:
        """The beat count at ``moment`` + 0.5 s, and one second after that."""
        await asyncio.sleep(max(0.0, moment + 0.5 - time.monotonic()))
        first = self.beats()
        await asyncio.sleep(1.0)
        return first, self.beats()

    async def stop(self, *, bound: float = 10.0) -> None:
        """Cleanup: wait up to ``bound`` for the child to stop beating, else kill it by pid."""
        deadline = time.monotonic() + bound
        previous = self.beats()
        while True:
            await asyncio.sleep(0.6)
            current = self.beats()
            if current == previous:
                return
            if time.monotonic() >= deadline:
                break
            previous = current
        # Still beating, so the pid in the file is this child's and it is alive.
        try:
            os.kill(int(self.pid_file.read_text(encoding="utf-8")), signal.SIGTERM)
        except (OSError, ValueError):
            pass


async def _settle(task: asyncio.Task[Any] | None) -> None:
    """Cleanup: let a leftover awaiter finish (bounded), else cancel it."""
    if task is None:
        return
    if not task.done():
        await asyncio.wait({task}, timeout=15.0)
    if not task.done():
        task.cancel()
        await asyncio.wait({task}, timeout=15.0)
    if task.done() and not task.cancelled():
        task.exception()


class _Audit:
    """Copied from the #1417 probes. Its durable stream is open, so a healthy run carries no ``audit`` key."""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def durable_stream_open(self) -> bool:
        return True

    def append(self, *, category: str, detail: str) -> None:
        self.records.append((category, json.loads(detail)))

    def code_execution(self) -> list[dict[str, Any]]:
        return [detail for category, detail in self.records if category == "code_execution"]


def _tool_runtime(root: Path, service: Any, audit: _Audit) -> SimpleNamespace:
    """The #1417 P-2 probe's tool runtime, carrying the long-run service."""
    return SimpleNamespace(
        config=SimpleNamespace(execution=ExecutionConfig(enabled=True, scratch_dir=str(root / "scratch"))),
        audit_log=audit,
        execution_long_runs=service,
    )


def _mesh_agent(root: Path, service: Any, audit: _Audit, *, agent_id: str) -> CodeRunnerAgent:
    """The #1417 P-3 probe's mesh agent, on a runtime carrying the long-run service."""
    cfg = ExecutionConfig(
        enabled=True, scratch_dir=str(root / "scratch"), workspace_root=str(root / "workspaces"),
    )
    runtime = SimpleNamespace(
        config=SimpleNamespace(execution=cfg), audit_log=audit, execution_long_runs=service,
    )
    return CodeRunnerAgent(agent_id=agent_id, runtime=runtime)


def _close_messages(
    service: LongRunService, caplog: pytest.LogCaptureFixture, reason: str = "t",
) -> list[str]:
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=_LONG_RUNS_LOGGER):
        service.close(reason)
    return [record.getMessage() for record in caplog.records if record.name == _LONG_RUNS_LOGGER]


def _assert_close_is_logged_while_a_run_is_held(caplog: pytest.LogCaptureFixture) -> None:
    """Premise for "close logs nothing": the same capture sees a close that reached a run."""
    control = LongRunService()
    ticket = control.admit("control-run", limit=1)
    assert ticket is not None
    try:
        messages = _close_messages(control, caplog, "control")
        assert any("long-run service closed" in message for message in messages), messages
    finally:
        ticket.finish()


def _attach_running_child(switch: KillSwitch) -> Any:
    """Copied from test_ad1246_long_run_units.py: ``fire`` reads only ``returncode``."""
    child = SimpleNamespace(returncode=None)
    assert switch.attach(child) is True
    return child


# The #1417 P-1 probe's DM-turn fakes.


class _Resp:
    def __init__(self, blocks: list[Any], content: str = "") -> None:
        self.content_blocks = blocks
        self.content = content
        self.tokens_used = 1


class _LLM:
    def __init__(self, responses: list[_Resp]) -> None:
        self._r = list(responses)

    async def complete(self, req: Any, **_kw: Any) -> _Resp:
        return self._r.pop(0) if self._r else _Resp([], "done")


class _Attachments:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def write(self, h: str, blob: bytes, mime: str, origin: str | None = None) -> None:
        self.blobs[h] = blob

    async def read(self, h: str) -> bytes:
        return self.blobs[h]


class _WorkItems:
    def __init__(self) -> None:
        self.created: list[WorkItem] = []
        self.transitions: list[tuple[str, str]] = []

    async def create_work_item(self, **kw: Any) -> WorkItem:
        item = WorkItem(status="open", **kw)
        self.created.append(item)
        return item

    async def transition_work_item(self, wid: str, status: str, source: str = "system") -> Any:
        self.transitions.append((wid, status))
        return SimpleNamespace(id=wid, status=status)


class _Threads:
    def __init__(self) -> None:
        self.appended: list[tuple[float, str]] = []

    def append_message_once(
        self, thread_id: str, *, message_id: str, author_id: str, role: str, body: str,
        created_at: Any, metadata: Any = None,
    ) -> Any:
        self.appended.append((time.monotonic(), body))
        return SimpleNamespace(id=message_id, thread_id=thread_id, body=body)


async def _drain(hold: set[asyncio.Task[Any]]) -> None:
    while hold:
        await asyncio.gather(*tuple(hold), return_exceptions=True)
        await asyncio.sleep(0)


async def _cancel_all(tasks: set[asyncio.Task[Any]]) -> None:
    pending = tuple(tasks)
    for task in pending:
        if not task.done():
            task.cancel()
    if pending:
        await asyncio.wait(pending, timeout=15.0)


# Copied from test_ad1246_long_run_promotion.py.


class _FakeShutdownRegistry:
    def all(self) -> list[Any]:
        return []


class _FakeShutdownRuntime:
    """Only what ``shutdown()`` reads up to its ``_started`` short-circuit is populated."""

    def __init__(
        self, *, data_dir: Path, execution_long_runs: LongRunService, crew_orchestrator: Any,
    ) -> None:
        self._data_dir = data_dir
        self._started = False
        self._shutdown_started = False
        self._session_id = "issue1417-test-session"
        self._start_time_wall = 0.0
        self._start_time = 0.0
        self.registry = _FakeShutdownRegistry()
        self.ontology = None
        self.confab_probe_tasks: set[Any] = set()
        self._confab_probe_scheduling_open = True
        self.dream_scheduler = None
        self.episodic_memory = None
        self.config = None
        self.execution_long_runs = execution_long_runs
        self.crew_orchestrator = crew_orchestrator

    def close_confab_probe_scheduling(self) -> None:
        self._confab_probe_scheduling_open = False


# ---------------------------------------------------------------------------
# T1-T6: the child stops when nothing is left to await it
# ---------------------------------------------------------------------------


async def test_invoke_cancelled_inline_run_kills_the_child(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    service = LongRunService()
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_tool_runtime(tmp_path, service, audit))
    child = _Child(tmp_path, 80)
    task = asyncio.create_task(tool.invoke({"code": child.code, "timeout": 60}, dict(_CONTEXT)))
    try:
        await child.wait_for_beats(3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        first, second = await child.counts_after(time.monotonic())
        # Before #1417 the orphaned child kept beating (P-1: 16 -> 26).
        assert first == second < child.total
        records = audit.code_execution()
        assert len(records) == 1
        assert records[0]["error_type"] == "cancelled"
        assert records[0]["launch_state"] == "launched"
        _assert_close_is_logged_while_a_run_is_held(caplog)
        assert _close_messages(service, caplog) == []
    finally:
        service.close("cleanup")
        await child.stop()
        await _settle(task)


async def test_bf733_abandoned_inline_run_is_stopped_when_reported(tmp_path: Path) -> None:
    child = _Child(tmp_path, 70)
    cfg = ExecutionConfig(enabled=True, scratch_dir=str(tmp_path / "scratch"))
    # Premise: an unarmed vessel, so the call takes the inline path.
    assert cfg.max_runtime_seconds == 0.0
    runtime = SimpleNamespace(
        config=SimpleNamespace(execution=cfg, mcp=None),
        tool_registry=ToolRegistry(),
        tool_permission_store=ToolPermissionStore(),
        intent_bus=None, intent_grant_store=None, mcp_workbench=None,
        attachment_store=_Attachments(),
        artifact_store=ArtifactStore(tmp_path / "artifacts.db"),
        emit_event=None,
        audit_log=_Audit(),
        work_item_store=_WorkItems(),
        chat_thread_store=_Threads(),
    )
    llm = _LLM([
        _Resp([ToolUseBlock(tool_call=ToolCallRequest(
            name="run_python", arguments={"code": child.code, "timeout": 60},
        ))]),
        _Resp([], "The run finished."),
    ])
    executor = WorkItemAgenticExecutor(llm_client=llm)

    async def _turn() -> str:
        outcome = await executor.run(
            agent_id="ezri", instructions="You are Ezri.", task_text="run it",
            runtime=runtime, department="science", rank="lieutenant",
            thread_id="thread-1", max_iterations=4, tier="standard",
        )
        return outcome.final_text

    hold: set[asyncio.Task[Any]] = set()
    try:
        ack = await run_with_promotion(
            _turn, promote_after_seconds=0.6, runtime=runtime, agent_id="ezri",
            thread_id="thread-1", request_text="run it", hold=hold, deadline_seconds=1.0,
        )
        # Premise: the turn was promoted, and its child is running.
        assert ack == _ACK_TEMPLATE.format(work_item_id=runtime.work_item_store.created[0].id)
        await child.wait_for_beats(3)
        await asyncio.wait_for(_drain(hold), timeout=15)
        reported_at = time.monotonic()
        assert [body for _, body in runtime.chat_thread_store.appended] == [_REPORT_ABANDONED]
        assert [status for _, status in runtime.work_item_store.transitions] == ["in_progress", "failed"]
        first, second = await child.counts_after(reported_at)
        # "...so I stopped it" was false before #1417 (P-1: 16 -> 26).
        assert first == second < child.total
    finally:
        await child.stop()
        await _cancel_all(hold)


async def test_mesh_run_python_cancelled_by_ttl_kills_the_child(tmp_path: Path) -> None:
    service = LongRunService()
    audit = _Audit()
    agent = _mesh_agent(tmp_path, service, audit, agent_id="cr-t3")
    child = _Child(tmp_path, 70)
    msg = IntentMessage(intent="run_python", params={"code": child.code, "timeout": 60}, ttl_seconds=1.0)
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(agent.handle_intent(msg), msg.ttl_seconds)
        cancelled_at = time.monotonic()
        # Premise: the child was running when the TTL cancelled its handler.
        assert child.beats() >= 1
        first, second = await child.counts_after(cancelled_at)
        # Before #1417 the child outlived its handler (P-3: 10 -> 20).
        assert first == second < child.total
        records = audit.code_execution()
        assert len(records) == 1
        assert records[0]["error_type"] == "cancelled"
        assert records[0]["launch_state"] == "launched"
        assert await service.wait_settled(0.01) is True
    finally:
        service.close("cleanup")
        await child.stop()


async def test_shutdown_kills_an_inline_tool_run_before_returning(tmp_path: Path) -> None:
    service = LongRunService()
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_tool_runtime(tmp_path, service, audit))
    fake = _FakeShutdownRuntime(data_dir=tmp_path, execution_long_runs=service, crew_orchestrator=None)
    child = _Child(tmp_path, 70)
    task = asyncio.create_task(tool.invoke({"code": child.code, "timeout": 60}, dict(_CONTEXT)))
    try:
        await child.wait_for_beats(3)
        await asyncio.wait_for(shutdown(fake, "issue1417"), 10)
        returned_at = time.monotonic()
        records_at_return = list(audit.code_execution())
        # Before #1417 shutdown returned at once and the child ran on (P-2: 3 -> 13).
        assert len(records_at_return) == 1
        assert records_at_return[0]["error_type"] == "stopped_at_shutdown"
        first, second = await child.counts_after(returned_at)
        assert first == second < child.total
        result = await asyncio.wait_for(task, 10)
        assert result.error == "stopped: shutdown"
        assert result.output["success"] is False
        assert service.closed is True
        assert service.active_count == 0
    finally:
        service.close("cleanup")
        await child.stop()
        await _settle(task)


async def test_shutdown_kills_an_inline_mesh_run_and_records_it(tmp_path: Path) -> None:
    service = LongRunService()
    audit = _Audit()
    agent = _mesh_agent(tmp_path, service, audit, agent_id="cr-t5")
    child = _Child(tmp_path, 70)
    task = asyncio.create_task(agent.handle_intent(
        IntentMessage(intent="run_python", params={"code": child.code, "timeout": 60}),
    ))
    try:
        await child.wait_for_beats(3)
        service.close("shutdown")
        closed_at = time.monotonic()
        result = await asyncio.wait_for(task, 15)
        # Before #1417 the run went on to succeed after the close.
        assert result.success is False
        assert result.error == "stopped: shutdown"
        records = audit.code_execution()
        assert len(records) == 1
        assert records[0]["error_type"] == "stopped_at_shutdown"
        first, second = await child.counts_after(closed_at)
        assert first == second < child.total
        assert await service.wait_settled(0.01) is True
    finally:
        service.close("cleanup")
        await child.stop()
        await _settle(task)


@pytest.mark.parametrize("path", ["tool", "mesh"])
async def test_run_requested_after_close_is_refused_before_launch(tmp_path: Path, path: str) -> None:
    service = LongRunService()
    service.close("shutdown")
    audit = _Audit()
    sentinel = tmp_path / "sentinel.txt"
    code = f"open({str(sentinel)!r}, 'w').write('ran')\n"
    if path == "tool":
        tool = CodeExecutionTool(runtime=_tool_runtime(tmp_path, service, audit))
        error = (await asyncio.wait_for(tool.invoke({"code": code}, dict(_CONTEXT)), 30)).error
    else:
        agent = _mesh_agent(tmp_path, service, audit, agent_id="cr-t6")
        error = (await asyncio.wait_for(agent.handle_intent(
            IntentMessage(intent="run_python", params={"code": code}),
        ), 30)).error
    await asyncio.sleep(1.5)
    # Before #1417 the script launched after shutdown began.
    assert not sentinel.exists()
    assert audit.code_execution() == []
    if path == "tool":
        assert list((tmp_path / "scratch").glob("exec-*")) == []
    from probos.execution.long_runs import SHUTDOWN_REFUSAL

    assert error == SHUTDOWN_REFUSAL


# ---------------------------------------------------------------------------
# T7-T9: a run that ends on its own is unchanged, and releases its ticket
# ---------------------------------------------------------------------------

# Captured from the unmodified base (335e2dd5) by running these exact calls (#1417 M1).
# stdout folds CRLF to LF and a timed-out child's exit code is only non-zero (H-12), so these hold on POSIX too.
_T7_CONTEXT = {"agent_id": "t7-agent", "thread_id": ""}
_T7_CASES: dict[str, tuple[dict[str, Any], str | None, dict[str, Any], dict[str, Any]]] = {
    "success": (
        {"code": "print('hi')"},
        None,
        {
            "stdout": "hi\n", "stderr": "", "exit_code": 0, "success": True, "timed_out": False,
            "artifacts": [], "artifact_details": [],
        },
        {
            "agent_id": "t7-agent", "artifact_count": 0, "code_chars": 11,
            "code_sha256": "c2d0a5e0790d97a015387a995c0d0b5eb3e88138466586fc980787c9b1731eb8",
            "exit_code": 0, "fetch_broker": False, "launch_state": "launched", "stream": "queued",
            "success": True, "timed_out": False, "timeout_seconds": 30.0,
        },
    ),
    "nonzero": (
        {"code": "raise SystemExit(3)"},
        None,
        {
            "stdout": "", "stderr": "", "exit_code": 3, "success": False, "timed_out": False,
            "artifacts": [], "artifact_details": [],
        },
        {
            "agent_id": "t7-agent", "artifact_count": 0, "code_chars": 19,
            "code_sha256": "8e3139644807bb164bd2e81e8fe63563d2f72545e2e963323e5dbd124f580c16",
            "exit_code": 3, "fetch_broker": False, "launch_state": "launched", "stream": "queued",
            "success": False, "timed_out": False, "timeout_seconds": 30.0,
        },
    ),
    "timeout": (
        {"code": "import time\ntime.sleep(5)", "timeout": 1},
        "timed out",
        {
            "stdout": "", "stderr": "", "success": False, "timed_out": True,
            "artifacts": [], "artifact_details": [],
        },
        {
            "agent_id": "t7-agent", "artifact_count": 0, "code_chars": 25,
            "code_sha256": "248d4774c2fdab259d71d83f14b9e789bb3a60159fa1b42b3180a71614097ec6",
            "error_type": "sandbox_error", "fetch_broker": False, "launch_state": "launched",
            "stream": "queued", "success": False, "timed_out": True, "timeout_seconds": 1.0,
        },
    ),
}
_T8_CASES: dict[str, tuple[dict[str, Any], bool, dict[str, Any], dict[str, Any]]] = {
    "success": (
        {"code": "print('hi')"},
        True,
        {
            "stdout": "hi\n", "stderr": "", "exit_code": 0, "timed_out": False, "tier": 1,
            "installed": [], "owner": "code_runner", "persistent": True,
        },
        {
            "agent_id": "code_runner", "code_chars": 11,
            "code_sha256": "c2d0a5e0790d97a015387a995c0d0b5eb3e88138466586fc980787c9b1731eb8",
            "exit_code": 0, "fetch_broker": False, "launch_state": "launched", "stream": "queued",
            "success": True, "timed_out": False, "timeout_seconds": 30.0,
        },
    ),
    "nonzero": (
        {"code": "raise SystemExit(3)"},
        False,
        {
            "stdout": "", "stderr": "", "exit_code": 3, "timed_out": False, "tier": 1,
            "installed": [], "owner": "code_runner", "persistent": True,
        },
        {
            "agent_id": "code_runner", "code_chars": 19,
            "code_sha256": "8e3139644807bb164bd2e81e8fe63563d2f72545e2e963323e5dbd124f580c16",
            "exit_code": 3, "fetch_broker": False, "launch_state": "launched", "stream": "queued",
            "success": False, "timed_out": False, "timeout_seconds": 30.0,
        },
    ),
}


def _trail(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in ("execution_id", "duration_ms")}


@pytest.mark.parametrize("case", ["success", "nonzero", "timeout"])
async def test_normal_tool_runs_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    params, error, output, record = _T7_CASES[case]
    constructed: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    real_init = SubprocessSandbox.__init__

    def _recording_init(self: Any, *args: Any, **kwargs: Any) -> None:
        constructed.append((args, dict(kwargs)))
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(SubprocessSandbox, "__init__", _recording_init)
    audit = _Audit()
    tool = CodeExecutionTool(runtime=_tool_runtime(tmp_path, LongRunService(), audit))
    result = await asyncio.wait_for(tool.invoke(dict(params), dict(_T7_CONTEXT)), 30)

    seen = dict(result.output)
    seen["stdout"] = seen["stdout"].replace("\r\n", "\n")
    records = audit.code_execution()
    assert len(records) == 1
    trail = _trail(records[0])
    if case == "timeout":
        assert seen.pop("exit_code") != 0
        assert trail.pop("exit_code") != 0
    assert result.error == error
    assert seen == output
    assert trail == record
    assert constructed == [((), {"scratch_root": str(tmp_path / "scratch")})]


@pytest.mark.parametrize("case", ["success", "nonzero"])
async def test_normal_mesh_runs_are_unchanged(tmp_path: Path, case: str) -> None:
    params, success, data, record = _T8_CASES[case]
    audit = _Audit()
    agent = _mesh_agent(tmp_path, LongRunService(), audit, agent_id=f"t8-{case}")
    result = await asyncio.wait_for(
        agent.handle_intent(IntentMessage(intent="run_python", params=dict(params))), 30,
    )

    seen = {key: value for key, value in dict(result.result).items() if key != "duration_ms"}
    seen["stdout"] = seen["stdout"].replace("\r\n", "\n")
    records = audit.code_execution()
    assert len(records) == 1
    assert result.success is success
    assert result.error is None
    assert seen == {**data, "workspace": str(tmp_path / "workspaces" / "code_runner")}
    assert _trail(records[0]) == record


@pytest.mark.parametrize("exit_path", ["completed", "sandbox_raised"])
async def test_every_exit_path_releases_the_inline_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    exit_path: str,
) -> None:
    tracked: list[Any] = []
    real_track = getattr(LongRunService, "track", None)
    if real_track is not None:
        def _recording_track(self: LongRunService, execution_id: str) -> Any:
            ticket = real_track(self, execution_id)
            tracked.append(ticket)
            return ticket

        monkeypatch.setattr(LongRunService, "track", _recording_track)
    if exit_path == "sandbox_raised":
        async def _raising_run(self: Any, request: Any) -> Any:
            raise RuntimeError("sandbox refused (#1417 T9)")

        monkeypatch.setattr(SubprocessSandbox, "run", _raising_run)
    service = LongRunService()
    tool = CodeExecutionTool(runtime=_tool_runtime(tmp_path, service, _Audit()))
    result = await asyncio.wait_for(tool.invoke({"code": "print('t9')"}, dict(_CONTEXT)), 30)

    # Premise: the run left through the exit path this case names.
    if exit_path == "completed":
        assert result.error is None
        assert result.output["success"] is True
    else:
        assert result.error == "execution failed: sandbox refused (#1417 T9)"
    # Premise: a ticket was tracked during the run (none exists at the base).
    assert len(tracked) == 1
    _assert_close_is_logged_while_a_run_is_held(caplog)
    assert _close_messages(service, caplog) == []
    assert await service.wait_settled(0.01) is True


# ---------------------------------------------------------------------------
# U1-U9: LongRunService.track and track_inline_run
# ---------------------------------------------------------------------------


async def test_track_returns_a_slotless_ticket_with_its_own_switch() -> None:
    service = LongRunService()
    first = service.track("a")
    second = service.track("b")
    try:
        assert first is not None and second is not None
        assert first.executor is None
        assert second.executor is None
        assert not first.settled.done()
        assert not second.settled.done()
        assert isinstance(first.kill_switch, KillSwitch)
        assert first.kill_switch is not second.kill_switch
        assert service.active_count == 0
    finally:
        for ticket in (first, second):
            if ticket is not None:
                ticket.finish()
        service.close("test")


async def test_track_accepts_a_duplicate_id_and_close_fires_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signalled: list[Any] = []
    monkeypatch.setattr(SubprocessSandbox, "_kill", staticmethod(signalled.append))
    service = LongRunService()
    first = service.track("x")
    second = service.track("x")
    assert first is not None and second is not None
    children = [
        _attach_running_child(first.kill_switch), _attach_running_child(second.kill_switch),
    ]
    try:
        service.close("shutdown")
        assert first.kill_switch.reason == "shutdown"
        assert second.kill_switch.reason == "shutdown"
        assert len(signalled) == 2
        assert {id(child) for child in signalled} == {id(child) for child in children}
    finally:
        first.finish()
        second.finish()
        assert await service.wait_settled(1.0) is True


async def test_track_after_close_returns_none() -> None:
    service = LongRunService()
    service.close("shutdown")
    assert service.track("late") is None
    assert service.admit("late", limit=2) is None


async def test_close_logs_long_and_inline_counts_once(caplog: pytest.LogCaptureFixture) -> None:
    service = LongRunService()
    long_ticket = service.admit("long-run", limit=1)
    inline_ticket = service.track("inline-run")
    assert long_ticket is not None and inline_ticket is not None
    try:
        with caplog.at_level(logging.INFO, logger=_LONG_RUNS_LOGGER):
            service.close("shutdown")
            service.close("again")
        closes = [r.getMessage() for r in caplog.records if "long-run service closed" in r.getMessage()]
        assert len(closes) == 1
        assert "1 long and 1 inline" in closes[0]
        # MU-3 (contract 5.4) must fail here too: the counts alone do not show that both fired.
        assert long_ticket.kill_switch.reason == "shutdown"
        assert inline_ticket.kill_switch.reason == "shutdown"
    finally:
        long_ticket.finish()
        inline_ticket.finish()
        assert await service.wait_settled(1.0) is True


async def test_close_after_inline_tickets_finished_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Premise: the same close logs while an inline run is tracked, so the silence below is not a muted logger.
    control = LongRunService()
    held = control.track("held")
    assert held is not None
    try:
        assert any("long-run service closed" in m for m in _close_messages(control, caplog, "control"))
    finally:
        held.finish()
    service = LongRunService()
    ticket = service.track("inline-run")
    assert ticket is not None
    ticket.finish()
    assert _close_messages(service, caplog, "shutdown") == []


async def test_wait_settled_waits_for_an_inline_ticket_and_names_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = LongRunService()
    ticket = service.track("inline-never-finishes")
    assert ticket is not None
    try:
        with caplog.at_level(logging.WARNING, logger=_LONG_RUNS_LOGGER):
            assert await service.wait_settled(0.2) is False
        warnings = [
            r.getMessage() for r in caplog.records
            if r.name == _LONG_RUNS_LOGGER and r.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        assert "inline-never-finishes" in warnings[0]
    finally:
        ticket.finish()
    assert await service.wait_settled(1.0) is True
    service.close("test")


async def test_wait_settled_does_not_suspend_after_inline_tickets_finished() -> None:
    loop = asyncio.get_running_loop()
    # Premise: one suspension is enough to run a callback scheduled with call_soon.
    control = asyncio.Event()
    loop.call_soon(control.set)
    await asyncio.sleep(0)
    assert control.is_set()

    service = LongRunService()
    try:
        ticket = service.track("inline-run")
        assert ticket is not None
        ticket.finish()
        flag = asyncio.Event()
        loop.call_soon(flag.set)
        assert await service.wait_settled(1.0) is True
        assert not flag.is_set()
        await asyncio.sleep(0)
    finally:
        service.close("test")


async def test_finish_releases_only_its_own_ticket() -> None:
    service = LongRunService()
    first = service.track("x")
    second = service.track("x")
    assert first is not None and second is not None
    try:
        first.finish()
        first.finish()
        service.close("shutdown")
        assert second.kill_switch.reason == "shutdown"
        assert first.kill_switch.reason is None
    finally:
        second.finish()
        assert await service.wait_settled(1.0) is True


@pytest.mark.parametrize("kind", ["None", "namespace", "magicmock"])
async def test_track_inline_run_without_a_service_is_untracked(kind: str) -> None:
    from probos.execution.long_runs import track_inline_run

    candidate = {"None": None, "namespace": SimpleNamespace(), "magicmock": MagicMock()}[kind]
    ticket = track_inline_run(candidate, "id")
    other = track_inline_run(candidate, "id")
    assert ticket is not None and other is not None
    assert isinstance(ticket.kill_switch, KillSwitch)
    assert ticket.kill_switch is not other.kill_switch
    assert ticket.kill_switch.reason is None
    assert ticket.executor is None
    ticket.finish()
    ticket.finish()
    other.finish()
    assert ticket.settled.done()
    if kind == "magicmock":
        # H-9: nothing is called on an object that is not the service.
        assert candidate.mock_calls == []

    # Control: a real service tracks the run, so its close reaches it.
    service = LongRunService()
    control = track_inline_run(service, "id")
    assert control is not None
    service.close("shutdown")
    assert control.kill_switch.reason == "shutdown"
    control.finish()
