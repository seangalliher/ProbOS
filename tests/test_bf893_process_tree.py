"""BF-893 (#1544): a timeout ends the command's whole process tree.

``run_command`` (the native SWE harness), ``ShellCommandAgent`` and the red team's re-run each
start a command through a shell. Killing only the shell on a timeout used to leave the command
running, so a caller told "timed out" could still see its effects (a push, a write, a build).

Every test here starts a shell whose command starts a *grandchild* that writes a marker file
after S seconds, then asks whether the marker ever appears. A "never appears" claim is only
worth something if the grandchild really existed and really could write its marker on this
platform, so each such test asserts a premise first (the grandchild's ``.started`` file) and
each production-path test runs a control (the same command, left alone, writes its marker).
A failed premise fails loudly; nothing here skips or passes vacuously.

Children write only marker files under ``tmp_path``. No test prints or compares an environment.

Platforms: ``test_windows_child_does_not_run_before_attach`` runs on Windows only;
``test_posix_child_leads_its_own_group`` and ``test_kill_never_signals_the_runtimes_own_group``
run on POSIX only; the rest run on both. The timing margins (the grandchild outlives the
timeout by at least 3 s, and each "never appears" window spans the grandchild's whole sleep)
are the build contract's.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from probos.agents.red_team import RedTeamAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.cognitive.swe_harness.tools import RunCommandTool
from probos.execution.command_env import build_command_env
from probos.execution.process_tree import ProcessTree, process_tree_popen_kwargs

_ON_WINDOWS = sys.platform == "win32"

#: How long the grandchild sleeps before it writes its marker (the contract's S).
_SLEEP_SECONDS = 3

#: A process-group id no process can hold: above the largest pid a POSIX system hands out (2**22 on Linux).
_NO_SUCH_GROUP = 2**22 + 4321

#: The failure message of every "the marker never appears after a timeout" check.
_SURVIVED = "the grandchild survived the timeout and wrote its marker"

#: The spawner starts a grandchild that writes ``marker`` after ``seconds``, records the grandchild's
#: pid in ``marker + ".started"``, then waits for it.
_SPAWNER_SOURCE = """\
import pathlib, subprocess, sys
marker, seconds = sys.argv[1], float(sys.argv[2])
code = f"import pathlib, time; time.sleep({seconds}); pathlib.Path({marker!r}).write_text('done')"
child = subprocess.Popen([sys.executable, "-c", code])
pathlib.Path(marker + ".started").write_text(str(child.pid))
child.wait()
"""


@pytest.fixture
def spawner(tmp_path: Path) -> Path:
    """``spawner.py`` in this test's ``tmp_path``.

    Deliberately shadows the agent-spawner fixture of the same name in ``tests/conftest.py``: it
    takes only ``tmp_path``, and nothing in this module wants an ``AgentSpawner``.
    """
    path = tmp_path / "spawner.py"
    path.write_text(_SPAWNER_SOURCE, encoding="utf-8")
    return path


def _appears(path: Path, within: float) -> bool:
    """True once *path* exists, polling every 0.1 s for at most *within* seconds."""
    deadline = time.monotonic() + within
    while not path.exists():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def _started(marker: Path) -> Path:
    """The file the spawner writes as soon as it has started the grandchild."""
    return Path(f"{marker}.started")


def _spawner_command(spawner: Path, marker: Path, seconds: float, *, powershell: bool) -> str:
    """The shell command line that runs the spawner; PowerShell needs the call operator ``&`` in front."""
    line = f'"{sys.executable}" "{spawner}" "{marker}" {seconds}'
    return f"& {line}" if powershell else line


def _printer_command(printer: Path, *, powershell: bool) -> str:
    """The shell command line that runs a script printing ``bf893-ok``."""
    line = f'"{sys.executable}" "{printer}"'
    return f"& {line}" if powershell else line


def _marker_writer(marker: Path) -> list[str]:
    """argv for a Python child that writes *marker* at once and exits."""
    code = f"import pathlib; pathlib.Path({str(marker)!r}).write_text('done')"
    return [sys.executable, "-c", code]


def _quiet_stdio() -> dict[str, int]:
    """stdio for children these tests start directly: they write only markers, so no pipe is needed."""
    return {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


def _spawn_shell(command: str, **popen_kwargs: Any) -> subprocess.Popen[bytes]:
    """Start *command* in the shell the agents use here: PowerShell on win32, ``/bin/sh`` elsewhere."""
    if _ON_WINDOWS:
        return subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", command],
            env=build_command_env(), **_quiet_stdio(), **popen_kwargs,
        )
    return subprocess.Popen(
        command, shell=True, env=build_command_env(), **_quiet_stdio(), **popen_kwargs,
    )


def _reap(proc: subprocess.Popen[bytes] | None) -> None:
    """Kill and wait for *proc*. Never raises, so cleanup cannot mask the assertion that is failing."""
    if proc is None:
        return
    try:
        proc.kill()
    except OSError:
        pass  # already gone: nothing to kill, and the wait below still reaps it
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass  # a stuck child is reported by the assertion that led here, not by its cleanup


class _FakeProcess:
    """A ``SpawnedProcess``: a pid, and a ``kill()`` that counts its calls and may raise."""

    pid = 4242

    def __init__(self, kill_error: OSError | None = None) -> None:
        self.kill_calls = 0
        self._kill_error = kill_error

    def kill(self) -> None:
        self.kill_calls += 1
        if self._kill_error is not None:
            raise self._kill_error


class _FakeRuntime:
    """``RunCommandTool`` stores the runtime but never reads it on the command path."""


@pytest.mark.timeout(90)
def test_premise_killing_only_the_shell_leaves_the_grandchild(tmp_path: Path, spawner: Path) -> None:
    """Without a tree, killing the shell leaves the grandchild running: the defect is observable here.

    This is the premise that makes every "the marker never appears" check below non-vacuous. On POSIX
    it holds even when dash execs the spawner, because the grandchild is then orphaned to init.
    """
    marker = tmp_path / "marker"
    proc = _spawn_shell(_spawner_command(spawner, marker, _SLEEP_SECONDS, powershell=_ON_WINDOWS))
    try:
        assert _appears(_started(marker), 20), "premise: the grandchild never started"
        proc.kill()
        proc.wait(timeout=10)
        assert _appears(marker, _SLEEP_SECONDS + 8), (
            "premise: killing only the shell also ended the grandchild, so this platform does not show "
            "the BF-893 defect and the 'never appears' checks below would pass vacuously"
        )
    finally:
        _reap(proc)


@pytest.mark.timeout(90)
def test_process_tree_kill_ends_the_grandchild(tmp_path: Path, spawner: Path) -> None:
    """``ProcessTree.kill`` ends the shell and the grandchild it started. Kills M21 (Windows)."""
    marker = tmp_path / "marker"
    proc = _spawn_shell(
        _spawner_command(spawner, marker, _SLEEP_SECONDS, powershell=_ON_WINDOWS), **process_tree_popen_kwargs(),
    )
    tree: ProcessTree | None = None
    try:
        tree = ProcessTree.attach(proc)
        assert _appears(_started(marker), 20), "premise: the grandchild never started"
        tree.kill()
        proc.wait(timeout=10)
        assert not _appears(marker, _SLEEP_SECONDS + 3), "the grandchild survived the tree kill and wrote its marker"
    finally:
        if tree is not None:
            if proc.poll() is None:
                tree.kill()  # still running after a failure: end the whole tree, not only the shell
            tree.close()
        _reap(proc)


@pytest.mark.timeout(90)
def test_kill_after_the_command_exited_is_not_an_error() -> None:
    """Ending a tree whose command already exited and was reaped neither raises nor changes its exit status."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"], **_quiet_stdio(), **process_tree_popen_kwargs())
    try:
        with ProcessTree.attach(proc) as tree:
            assert proc.wait(timeout=30) == 0, "premise: the command did not exit cleanly on its own"
            tree.kill()
            tree.kill()
        assert proc.returncode == 0
    finally:
        _reap(proc)


@pytest.mark.timeout(90)
def test_direct_tree_kills_only_the_process() -> None:
    """A tree built with neither job nor group ends just the process; one that already vanished is not an error."""
    live = _FakeProcess()
    ProcessTree(live).kill()
    assert live.kill_calls == 1

    gone = _FakeProcess(kill_error=ProcessLookupError("no such process"))
    ProcessTree(gone).kill()  # must swallow the ProcessLookupError
    assert gone.kill_calls == 1


@pytest.mark.skipif(not _ON_WINDOWS, reason="CREATE_SUSPENDED and job objects are Windows-only (POSIX: new session)")
@pytest.mark.timeout(90)
def test_windows_child_does_not_run_before_attach(tmp_path: Path) -> None:
    """Under the tree's spawn keywords the child stays suspended until ``attach``. Kills M18 (Windows)."""
    control_marker = tmp_path / "control"
    control = subprocess.Popen(_marker_writer(control_marker), **_quiet_stdio())
    try:
        assert _appears(control_marker, 10), "control: a child started without the tree's keywords never ran"
    finally:
        _reap(control)

    marker = tmp_path / "suspended"
    proc = subprocess.Popen(_marker_writer(marker), **_quiet_stdio(), **process_tree_popen_kwargs())
    tree: ProcessTree | None = None
    try:
        assert not _appears(marker, 1.5), "the child ran before attach: it was not started suspended"
        assert proc.poll() is None, "premise: the suspended child is gone, so 'no marker yet' proves nothing"
        tree = ProcessTree.attach(proc)
        assert _appears(marker, 10), "attach did not resume the child"
    finally:
        if tree is not None:
            if proc.poll() is None:
                tree.kill()  # still running after a failure: end its tree, not only the child
            tree.close()
        _reap(proc)


@pytest.mark.skipif(_ON_WINDOWS, reason="process groups are POSIX; Windows contains the tree in a job object")
@pytest.mark.timeout(90)
def test_posix_child_leads_its_own_group() -> None:
    """Under the tree's spawn keywords the child is the leader of a new process group. Kills M17 (POSIX)."""
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    leader = subprocess.Popen(sleeper, **_quiet_stdio(), **process_tree_popen_kwargs())
    follower: subprocess.Popen[bytes] | None = None
    try:
        follower = subprocess.Popen(sleeper, **_quiet_stdio())
        assert os.getpgid(leader.pid) == leader.pid
        assert os.getpgid(follower.pid) == os.getpgrp(), "control: a child started without the keywords left our group"
    finally:
        _reap(leader)
        _reap(follower)


@pytest.mark.skipif(_ON_WINDOWS, reason="process groups and os.killpg are POSIX")
@pytest.mark.timeout(90)
def test_kill_never_signals_the_runtimes_own_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tree whose group is the runtime's own is never signalled (SIGKILL there ends the runtime). Kills M20."""
    signalled: list[tuple[int, int]] = []
    monkeypatch.setattr("probos.execution.process_tree.os.killpg", lambda pgid, sig: signalled.append((pgid, sig)))

    # Control: the recorder is live. A group that is not ours is signalled through it (nothing real is sent).
    ProcessTree(_FakeProcess(), group=_NO_SUCH_GROUP).kill()
    assert signalled == [(_NO_SUCH_GROUP, signal.SIGKILL)], "control: a foreign group was not signalled"

    signalled.clear()
    ours = _FakeProcess()
    ProcessTree(ours, group=os.getpgrp()).kill()
    assert signalled == []
    assert ours.kill_calls == 1


@pytest.mark.timeout(90)
async def test_run_command_timeout_ends_the_grandchild(tmp_path: Path, spawner: Path) -> None:
    """``run_command`` ends the grandchild when it times out. Kills M14.

    ``run_command`` runs its command under cmd.exe on Windows and ``/bin/sh`` elsewhere, never PowerShell.
    """
    tool = RunCommandTool(_FakeRuntime())

    # Control: left alone, the grandchild finishes and writes its marker.
    control_marker = tmp_path / "control"
    control = await tool.invoke(
        {"command": _spawner_command(spawner, control_marker, 1, powershell=False), "timeout": 60},
    )
    assert control.success, "control: an in-time run_command call failed"
    assert control.output["exit_code"] == 0
    assert await asyncio.to_thread(_appears, control_marker, 3), "control: the grandchild never wrote its marker"

    marker = tmp_path / "marker"
    result = await tool.invoke(
        {"command": _spawner_command(spawner, marker, 7, powershell=False), "timeout": 4.0},
    )
    assert result.error == "run_command timed out after 4.0s"
    assert _started(marker).exists(), "premise: the grandchild did not exist when the timeout fired"
    assert not marker.exists(), "premise: the grandchild had already written its marker when the timeout fired"
    assert not await asyncio.to_thread(_appears, marker, 10), _SURVIVED


@pytest.mark.timeout(90)
async def test_shell_agent_timeout_ends_the_grandchild(tmp_path: Path, spawner: Path) -> None:
    """``ShellCommandAgent`` ends the grandchild when it times out. Kills M15.

    ``_run_command`` is called directly: it bypasses ``decide()``, which refuses a command led by ``&``.
    """
    agent = ShellCommandAgent(pool="shell")

    # Control: with 60 s allowed, the grandchild finishes and writes its marker.
    agent.DEFAULT_TIMEOUT = 60.0
    control_marker = tmp_path / "control"
    control = await agent._run_command(_spawner_command(spawner, control_marker, 1, powershell=_ON_WINDOWS))
    assert control["success"] is True, "control: an in-time shell command failed"
    assert control["data"]["exit_code"] == 0
    assert await asyncio.to_thread(_appears, control_marker, 3), "control: the grandchild never wrote its marker"

    agent.DEFAULT_TIMEOUT = 4.0
    marker = tmp_path / "marker"
    result = await agent._run_command(_spawner_command(spawner, marker, 7, powershell=_ON_WINDOWS))
    assert result == {"success": False, "error": "Command timed out after 4.0s"}
    assert _started(marker).exists(), "premise: the grandchild did not exist when the timeout fired"
    # The worker thread's own communicate() timeout fires right after the outer wait_for, so "absent now"
    # proves nothing yet: poll the whole window.
    assert not await asyncio.to_thread(_appears, marker, 10), _SURVIVED


@pytest.mark.timeout(90)
async def test_red_team_rerun_timeout_ends_the_grandchild(tmp_path: Path, spawner: Path) -> None:
    """The red team's re-run ends the grandchild when it times out (its limit is a fixed 5 s). Kills M16."""
    # Control: left alone, the grandchild finishes inside the limit and writes its marker.
    control_marker = tmp_path / "control"
    control = await asyncio.to_thread(
        RedTeamAgent._run_verify_sync,
        _spawner_command(spawner, control_marker, 1, powershell=_ON_WINDOWS), build_command_env(),
    )
    assert control is not None, "control: an in-time re-run timed out or failed"
    assert control[0] == 0
    assert isinstance(control[1], str)
    assert await asyncio.to_thread(_appears, control_marker, 3), "control: the grandchild never wrote its marker"

    marker = tmp_path / "marker"
    rerun = await asyncio.to_thread(
        RedTeamAgent._run_verify_sync,
        _spawner_command(spawner, marker, 8, powershell=_ON_WINDOWS), build_command_env(),
    )
    assert rerun is None
    assert _started(marker).exists(), "premise: the grandchild did not exist when the timeout fired"
    assert not await asyncio.to_thread(_appears, marker, 11), _SURVIVED


@pytest.mark.timeout(90)
async def test_in_time_results_are_unchanged(tmp_path: Path) -> None:
    """A command that finishes in time returns exactly what it returned before BF-893. Kills M19 (Windows).

    If the suspended child were never resumed (M19) each call would time out instead of answering.
    """
    printer = tmp_path / "printer.py"
    printer.write_text("print('bf893-ok')\n", encoding="utf-8")

    ran = await RunCommandTool(_FakeRuntime()).invoke(
        {"command": _printer_command(printer, powershell=False), "timeout": 30},
    )
    assert ran.success, "run_command did not answer in time"
    assert set(ran.output) == {"stdout", "stderr", "exit_code"}
    assert ran.output["exit_code"] == 0
    assert "bf893-ok" in ran.output["stdout"]

    agent = ShellCommandAgent(pool="shell")
    answered = await agent._run_command(_printer_command(printer, powershell=_ON_WINDOWS))
    assert set(answered) == {"success", "data"}, "the shell agent did not answer in time"
    assert set(answered["data"]) == {"stdout", "stderr", "exit_code", "command"}
    assert answered["success"] is True
    assert answered["data"]["exit_code"] == 0
    assert "bf893-ok" in answered["data"]["stdout"]

    rerun = await asyncio.to_thread(
        RedTeamAgent._run_verify_sync, _printer_command(printer, powershell=_ON_WINDOWS), build_command_env(),
    )
    assert rerun is not None, "the red team's re-run did not answer in time"
    assert rerun[0] == 0
    assert isinstance(rerun[1], str)
    assert "bf893-ok" in rerun[1]
