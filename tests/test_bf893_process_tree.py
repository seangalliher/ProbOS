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

The four shared-deadline tests (``..._queued_past_the_deadline_never_starts_the_command`` and
``..._started_late_leaves_no_descendant_when_the_timeout_is_reported``, for the shell agent and the red
team) cover ``ShellCommandAgent._run_command`` and ``RedTeamAgent._verify_run_command``, which run their
worker on the loop's shared default executor and give it one deadline, measured from submission. They put
that executor under contention (one thread, held by a test-owned event) so the worker is picked up late:
past the deadline it must run nothing, and inside it it must end the command's whole tree before the call
reports the timeout. The ``_started_late_`` tests and the cancellation tests use a grandchild that writes a
heartbeat (``beater.py``). It loops only while ``<marker>.stop`` does not exist (and for at most 60 s), so a
test's cleanup writes that file and waits briefly: nothing in this module signals a PID (a PID read back
from a file can belong to a stranger once its process is gone). They poll with ``asyncio.sleep``, never
``asyncio.to_thread``: the executor they hold is the one ``to_thread`` would queue behind.

The cancellation tests (``test_shell_cancel_ends_tree``, ``test_redteam_outer_timeout_ends_rerun``,
``test_swe_run_command_cancel_ends_tree``, ``test_queued_worker_cancelled_runs_nothing``,
``test_backstop_timeout_cancels_the_held_slot`` and the ``ProcessTreeSlot`` tests) cover a caller that gives up
before the deadline: an enclosing timeout or a cancelled task must end the worker's command tree at once, not
leave it running to the worker's own deadline.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.agents.red_team import RedTeamAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.cognitive.swe_harness.tools import RunCommandTool
from probos.execution.command_env import build_command_env
from probos.execution.process_tree import ProcessTree, ProcessTreeSlot, process_tree_popen_kwargs
from probos.types import IntentMessage, IntentResult, VerificationResult

_ON_WINDOWS = sys.platform == "win32"

#: How long the grandchild sleeps before it writes its marker (the contract's S).
_SLEEP_SECONDS = 3

#: A process-group id no process can hold: above the largest pid a POSIX system hands out (2**22 on Linux).
_NO_SUCH_GROUP = 2**22 + 4321

#: The failure message of every "the marker never appears after a timeout" check.
_SURVIVED = "the grandchild survived the timeout and wrote its marker"

#: How long the heartbeat grandchild may beat (one beat per 0.1 s). Nothing waits for that: a test ends it first.
_BEAT_LIMIT_SECONDS = 60

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

#: The same shape as the spawner (root records the grandchild's pid in ``.started``, then waits), but the
#: grandchild is this script again and appends a line to ``marker + ".beat"`` every 0.1 s, for up to ``limit``
#: seconds and only while ``marker + ".stop"`` does not exist: a heartbeat that only a live process can
#: advance, and that a test ends by writing the stop file (no signal, no pid).
_BEATER_SOURCE = """\
import os, pathlib, subprocess, sys, time


def beat(marker, limit):
    end = time.monotonic() + limit
    with open(marker + ".beat", "a") as out:
        n = 0
        while time.monotonic() < end and not os.path.exists(marker + ".stop"):
            n += 1
            out.write(f"{n}\\n")
            out.flush()
            time.sleep(0.1)


if sys.argv[1] == "--beat":
    beat(sys.argv[2], float(sys.argv[3]))
else:
    marker, limit = sys.argv[1], sys.argv[2]
    child = subprocess.Popen([sys.executable, __file__, "--beat", marker, limit])
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


@pytest.fixture
def beater(tmp_path: Path) -> Path:
    """``beater.py`` in this test's ``tmp_path``: a spawner whose grandchild writes a heartbeat."""
    path = tmp_path / "beater.py"
    path.write_text(_BEATER_SOURCE, encoding="utf-8")
    return path


def _appears(path: Path, within: float) -> bool:
    """True once *path* exists, polling every 0.1 s for at most *within* seconds."""
    deadline = time.monotonic() + within
    while not path.exists():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


async def _appears_async(path: Path, within: float) -> bool:
    """:func:`_appears` for tests that hold the default executor: polls with ``asyncio.sleep``, never a thread."""
    deadline = time.monotonic() + within
    while not path.exists():
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.1)
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


def _beats(marker: Path) -> int:
    """How many beats the heartbeat grandchild has written so far (0 before its first)."""
    try:
        return len(Path(f"{marker}.beat").read_text().splitlines())
    except FileNotFoundError:
        return 0


def _beating(marker: Path, over: float = 0.3) -> bool:
    """Whether the heartbeat advances within *over* seconds. Only a live process can write a beat."""
    before = _beats(marker)
    time.sleep(over)
    return _beats(marker) > before


def _request_stop(marker: Path) -> None:
    """Ask the heartbeat grandchild to stop: it beats only while ``<marker>.stop`` does not exist (and for 60 s)."""
    Path(f"{marker}.stop").write_text("stop", encoding="utf-8")


def _stop_heartbeat(marker: Path) -> None:
    """Cooperative teardown for a heartbeat grandchild: request the stop, then wait briefly for the beats to cease.

    Nothing is signalled: a pid read back from a file (or any pid, once its process has exited) can belong to a
    stranger. A grandchild that ignored the request still ends by itself at its 60 s limit.
    """
    _request_stop(marker)
    for _ in range(8):
        if not _beating(marker, over=0.25):
            return


class _SpawnSpy:
    """Stands in for the ``subprocess`` name inside one agent module: records each ``Popen`` and runs it for real.

    A command started past its deadline is ended within milliseconds, usually before it can write ``.started``,
    so the only certain evidence that nothing was started is that ``Popen`` was never called.
    """

    def __init__(self) -> None:
        self.spawned: list[object] = []

    def Popen(self, args: Any, *popen_args: Any, **popen_kwargs: Any) -> subprocess.Popen[bytes]:  # noqa: N802
        self.spawned.append(args)
        return subprocess.Popen(args, *popen_args, **popen_kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(subprocess, name)


def _watch_spawns(monkeypatch: pytest.MonkeyPatch, module: str) -> list[object]:
    """Every ``subprocess.Popen`` that the agent module *module* starts for the rest of the test, in order."""
    spy = _SpawnSpy()
    monkeypatch.setattr(f"{module}.subprocess", spy)
    return spy.spawned


class _ContendedCall:
    """The running loop's default executor cut to one thread, that thread held, and a call queued behind the hold.

    Reproduces a busy shared pool: whatever the call hands to ``run_in_executor(None, ...)`` waits for
    :meth:`release`. ``hold=False`` leaves the thread free (the same one-thread pool without the contention), so a
    test can ask with :meth:`is_free` whether a cancelled call released its thread. Leaving the block always
    asks each heartbeat grandchild in *heartbeats* to stop (so a worker waiting on its command ends and the pool
    can be joined), releases the hold, cancels the call if it is still pending and shuts the pool down: a
    failing test leaves no thread blocked.
    """

    def __init__(self, *, hold: bool = True, heartbeats: tuple[Path, ...] = ()) -> None:
        self._hold = hold
        self._heartbeats = heartbeats
        self._release = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bf893-contention")
        self._held: asyncio.Future[bool] | None = None
        self._call: asyncio.Task[Any] | None = None

    async def __aenter__(self) -> _ContendedCall:
        loop = asyncio.get_running_loop()
        loop.set_default_executor(self._pool)
        if self._hold:
            self._held = loop.run_in_executor(None, self._release.wait, 30)  # occupies the pool's only thread
        return self

    def submit(self, call: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """Start *call* now; any job it hands to the default executor queues behind the hold."""
        self._call = asyncio.create_task(call)
        return self._call

    def release(self) -> None:
        self._release.set()

    async def is_free(self, within: float) -> bool:
        """Whether the pool's only thread runs a trivial job within *within* s: nothing else is running on it."""
        try:
            await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, int), timeout=within)
        except TimeoutError:
            return False
        return True

    async def __aexit__(self, *exc_info: object) -> None:
        for marker in self._heartbeats:
            _request_stop(marker)
        self._release.set()
        if self._call is not None and not self._call.done():
            self._call.cancel()
        await asyncio.gather(*(t for t in (self._held, self._call) if t is not None), return_exceptions=True)
        self._pool.shutdown(wait=True)
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor())  # leave the loop a usable default


def _rerun(agent: RedTeamAgent, command: str, claimed_stdout: str = "") -> Coroutine[Any, Any, VerificationResult]:
    """The red team's verdict on a claimed run of *command* (exit 0, output *claimed_stdout*), as an awaitable."""
    intent = IntentMessage(intent="run_command", params={"command": command})
    claimed = IntentResult(
        intent_id=intent.id, agent_id="shell-1", success=True,
        result={"exit_code": 0, "stdout": claimed_stdout}, confidence=0.8,
    )
    return agent._verify_run_command("shell-1", intent, claimed, intent.params)


async def _beats_until_ended(marker: Path, call: asyncio.Task[Any]) -> None:
    """Control for the heartbeat checks: a command nothing ends keeps beating, until the test asks it to stop.

    *call* runs a heartbeat command under a generous deadline and is never cancelled. Wait for its grandchild to
    start, watch the count advance (so "unchanged" in the real check can be told from "still beating"), then ask
    the grandchild to stop (the stop file), let the call finish and see the count stop.
    """
    assert await _appears_async(_started(marker), 20), "control: the grandchild never started"
    first = _beats(marker)
    await asyncio.sleep(0.5)
    assert _beats(marker) > first, "control: a command nothing ended did not keep beating"
    _request_stop(marker)
    await asyncio.wait_for(call, timeout=20)
    stopped = _beats(marker)
    await asyncio.sleep(0.5)
    assert _beats(marker) == stopped, "control: the stop request did not end the heartbeat"


async def _heartbeat_is_running(marker: Path, call: asyncio.Task[Any]) -> None:
    """Premise for the cancellation tests: the grandchild has started and beaten, and *call* still waits on it."""
    assert await _appears_async(_started(marker), 20), "premise: the grandchild never started"
    deadline = time.monotonic() + 20
    while _beats(marker) < 2 and not call.done() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    assert not call.done(), "premise: the call ended before the heartbeat ran"
    assert _beats(marker) >= 2, "premise: the heartbeat did not advance"


async def _assert_silent_after_the_call(marker: Path) -> None:
    """Called the moment a call ends (timeout reported, or cancelled): the grandchild had beaten, and beats no more."""
    assert _started(marker).exists(), "premise: the grandchild did not exist when the call ended"
    ended = _beats(marker)
    assert ended >= 2, "premise: the heartbeat had not advanced when the call ended"
    await asyncio.sleep(1.0)
    assert _beats(marker) == ended, "a descendant was still beating after the call ended"


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


_FakeTree = _FakeProcess  # a ``ProcessTreeSlot`` only ever calls ``kill()`` on the tree it holds


def _recording_slot(events: list[str]) -> type[ProcessTreeSlot]:
    """A ``ProcessTreeSlot`` that records ``hold`` / ``release`` / ``cancel`` calls in *events*, then delegates."""

    class Recording(ProcessTreeSlot):
        def hold(self, tree: ProcessTree) -> bool:
            events.append("hold")
            return super().hold(tree)

        def release(self) -> None:
            events.append("release")
            super().release()

        def cancel(self) -> None:
            events.append("cancel")
            super().cancel()

    return Recording


def _site(name: str, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The shell agent (``"shell"``) or the red team (``"red_team"``), each on a generous 20 s budget.

    ``module`` is the agent module a spawn spy watches; ``call(command)`` is the async entry point a caller awaits
    (and may cancel); ``worker(command, slot)`` is its blocking worker on a 20 s deadline; ``in_time(result)`` says
    whether a call's result is that of a command that ran to completion; ``refusal`` is what the worker returns
    when it ran nothing.
    """
    if name == "shell":
        agent = ShellCommandAgent(pool="shell")
        agent.DEFAULT_TIMEOUT = 20.0
        return SimpleNamespace(
            module="probos.agents.shell_command",
            call=agent._run_command,
            worker=lambda command, slot: agent._run_sync(command, time.monotonic() + 20.0, slot),
            in_time=lambda result: result.get("success") is True,
            refusal={"success": False, "error": "Command timed out after 20.0s"},
        )
    monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 20.0)
    red = RedTeamAgent(pool="red_team")
    return SimpleNamespace(
        module="probos.agents.red_team",
        call=lambda command: _rerun(red, command),
        worker=lambda command, slot: RedTeamAgent._run_verify_sync(
            command, build_command_env(), time.monotonic() + 20.0, slot,
        ),
        in_time=lambda verdict: verdict.verified is True,
        refusal=None,
    )


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
    # The worker enforces the shared deadline itself: its communicate() budget ends at that deadline, it kills the
    # tree and only then returns its own timeout result. The caller's wait_for is a later backstop (deadline +
    # WORKER_TEARDOWN_GRACE), so the tree is already gone when this call returns; the whole window is still
    # polled for a marker that must never come.
    assert not await asyncio.to_thread(_appears, marker, 10), _SURVIVED


@pytest.mark.timeout(90)
async def test_red_team_rerun_timeout_ends_the_grandchild(tmp_path: Path, spawner: Path) -> None:
    """The red team's re-run ends the grandchild when it times out (limit ``_RERUN_TIMEOUT_S``, 5 s). Kills M16."""
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


@pytest.mark.timeout(90)
async def test_shell_agent_worker_queued_past_the_deadline_never_starts_the_command(
    tmp_path: Path, spawner: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A worker the busy executor reaches only after the shared deadline runs nothing and reports the timeout.

    The caller's wait is a backstop later than the deadline (``DEFAULT_TIMEOUT + WORKER_TEARDOWN_GRACE``), so the
    queued job is still there to be picked up. Two probes, because a command started past its deadline is ended
    within milliseconds and might never write ``.started``: ``Popen`` is never called, and no ``.started``
    appears in the 3 s after the call returns.
    """
    spawned = _watch_spawns(monkeypatch, "probos.agents.shell_command")
    agent = ShellCommandAgent(pool="shell")

    # Control: with a generous deadline and a free executor the same call does start the command.
    agent.DEFAULT_TIMEOUT = 10.0
    control_marker = tmp_path / "control"
    control = await agent._run_command(_spawner_command(spawner, control_marker, 1, powershell=_ON_WINDOWS))
    assert control["success"] is True, "control: an in-time shell command failed"
    assert control["data"]["exit_code"] == 0
    assert len(spawned) == 1, "control: the command was not started through subprocess.Popen"
    assert _started(control_marker).exists(), "control: the grandchild never started"
    spawned.clear()

    # Test: a 1.5 s deadline, and the executor's only thread is held until 2.5 s.
    agent.DEFAULT_TIMEOUT = 1.5
    marker = tmp_path / "marker"
    async with _ContendedCall() as contended:
        call = contended.submit(agent._run_command(_spawner_command(spawner, marker, 7, powershell=_ON_WINDOWS)))
        await asyncio.sleep(2.5)  # past the deadline (1.5 s), before the caller's backstop (1.5 s + 5 s)
        assert not call.done(), "premise: the call returned while the executor was still held: no later backstop"
        assert not _started(marker).exists(), "premise: the command started while the executor was still held"
        contended.release()
        result = await asyncio.wait_for(call, timeout=10)
    assert result == {"success": False, "error": "Command timed out after 1.5s"}
    assert spawned == [], "a worker picked up past the deadline started the command"
    assert not await _appears_async(_started(marker), 3), "a command was started after the timeout was reported"


@pytest.mark.timeout(90)
async def test_shell_agent_worker_started_late_leaves_no_descendant_when_the_timeout_is_reported(
    tmp_path: Path, beater: Path,
) -> None:
    """A worker picked up late but inside the deadline ends the command's whole tree before the call reports.

    Before the single deadline the worker's own budget began at pickup, so with the executor busy the caller
    reported the timeout while the command it had started was still running. The descendant here is a real
    grandchild writing a heartbeat; it must not beat once the call has returned.
    """
    agent = ShellCommandAgent(pool="shell")
    control_marker = tmp_path / "control"
    marker = tmp_path / "marker"
    try:
        # Control: with a generous deadline nothing ends the command, so its heartbeat keeps advancing.
        agent.DEFAULT_TIMEOUT = 10.0
        control = asyncio.create_task(
            agent._run_command(_spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control)

        # Test: a 3.0 s deadline; the executor's only thread is held for 1.0 s, so the worker starts late but in time.
        # The teardown grace is cut to 0.5 s so that 1.0 s of pickup delay outlasts it, as a delay over the production
        # 5 s would: a worker that kept a fresh full budget instead of the shared deadline then ends after the
        # caller's backstop, which reports the timeout while the command still runs.
        agent.DEFAULT_TIMEOUT = 3.0
        agent.WORKER_TEARDOWN_GRACE = 0.5
        async with _ContendedCall(heartbeats=(marker,)) as contended:
            call = contended.submit(
                agent._run_command(_spawner_command(beater, marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
            )
            await asyncio.sleep(1.0)
            assert not _started(marker).exists(), "premise: the command started while the executor was still held"
            contended.release()
            result = await asyncio.wait_for(call, timeout=15)
            assert result == {"success": False, "error": "Command timed out after 3.0s"}
            await _assert_silent_after_the_call(marker)
    finally:
        _stop_heartbeat(control_marker)
        _stop_heartbeat(marker)


@pytest.mark.timeout(90)
async def test_red_team_rerun_queued_past_the_deadline_never_starts_the_command(
    tmp_path: Path, spawner: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A re-run the busy executor reaches only after the shared deadline runs nothing and reports the timeout.

    Same two probes as the shell agent's test: ``Popen`` is never called, and no ``.started`` appears. The verdict
    must be the worker's ("Verification command timed out"), not the backstop's bare "Verification error: ".
    """
    spawned = _watch_spawns(monkeypatch, "probos.agents.red_team")
    agent = RedTeamAgent(pool="red_team")

    # Control: with a generous deadline and a free executor the same call does start the re-run, which verifies.
    monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 10.0)
    control_marker = tmp_path / "control"
    control = await _rerun(agent, _spawner_command(spawner, control_marker, 1, powershell=_ON_WINDOWS))
    assert control.verified is True, "control: an in-time re-run was not verified"
    assert len(spawned) == 1, "control: the re-run was not started through subprocess.Popen"
    assert _started(control_marker).exists(), "control: the grandchild never started"
    spawned.clear()

    # Test: a 1.5 s deadline, and the executor's only thread is held until 2.5 s.
    monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 1.5)
    marker = tmp_path / "marker"
    async with _ContendedCall() as contended:
        call = contended.submit(_rerun(agent, _spawner_command(spawner, marker, 7, powershell=_ON_WINDOWS)))
        await asyncio.sleep(2.5)  # past the deadline (1.5 s), before the caller's backstop (1.5 s + 5 s)
        assert not call.done(), "premise: the call returned while the executor was still held: no later backstop"
        assert not _started(marker).exists(), "premise: the re-run started while the executor was still held"
        contended.release()
        verdict = await asyncio.wait_for(call, timeout=10)
    assert verdict.verified is False
    assert verdict.discrepancy == "Verification command timed out"
    assert spawned == [], "a worker picked up past the deadline started the re-run"
    assert not await _appears_async(_started(marker), 3), "a re-run was started after the timeout was reported"


@pytest.mark.timeout(90)
async def test_red_team_rerun_started_late_leaves_no_descendant_when_the_timeout_is_reported(
    tmp_path: Path, beater: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A re-run picked up late but inside the deadline ends its whole tree before the call reports the timeout."""
    agent = RedTeamAgent(pool="red_team")
    control_marker = tmp_path / "control"
    marker = tmp_path / "marker"
    try:
        # Control: with a generous deadline nothing ends the re-run, so its heartbeat keeps advancing.
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 10.0)
        control = asyncio.create_task(
            _rerun(agent, _spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control)

        # Test: a 3.0 s deadline; the executor's only thread is held for 1.0 s, so the worker starts late but in time.
        # The teardown grace is cut to 0.5 s for the reason given in the shell agent's test.
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 3.0)
        monkeypatch.setattr("probos.agents.red_team._RERUN_TEARDOWN_GRACE_S", 0.5)
        async with _ContendedCall(heartbeats=(marker,)) as contended:
            call = contended.submit(
                _rerun(agent, _spawner_command(beater, marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
            )
            await asyncio.sleep(1.0)
            assert not _started(marker).exists(), "premise: the re-run started while the executor was still held"
            contended.release()
            verdict = await asyncio.wait_for(call, timeout=15)
            assert verdict.verified is False
            assert verdict.discrepancy == "Verification command timed out"
            await _assert_silent_after_the_call(marker)
    finally:
        _stop_heartbeat(control_marker)
        _stop_heartbeat(marker)


@pytest.mark.timeout(90)
async def test_shell_cancel_ends_tree(tmp_path: Path, beater: Path) -> None:
    """Cancelling the task that awaits ``ShellCommandAgent._run_command`` ends the command's whole tree.

    Before the slot, a cancellation (or an enclosing ``wait_for`` timing out) left the worker thread's command
    running to its own deadline. The budget here is 20 s, so only the cancellation can end it in time, and the
    one-thread pool must get its thread back.
    """
    agent = ShellCommandAgent(pool="shell")
    agent.DEFAULT_TIMEOUT = 20.0
    control_marker = tmp_path / "control"
    marker = tmp_path / "marker"
    try:
        # Control: never cancelled, the same call keeps beating.
        control = asyncio.create_task(
            agent._run_command(_spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control)

        async with _ContendedCall(hold=False, heartbeats=(marker,)) as pool:
            call = pool.submit(
                agent._run_command(_spawner_command(beater, marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
            )
            await _heartbeat_is_running(marker, call)
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
            await _assert_silent_after_the_call(marker)
            assert await pool.is_free(3.0), "the cancelled call left its worker thread running the command"
    finally:
        _stop_heartbeat(control_marker)
        _stop_heartbeat(marker)


@pytest.mark.timeout(90)
async def test_redteam_outer_timeout_ends_rerun(
    tmp_path: Path, beater: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An enclosing ``wait_for`` that times out first ends the red team's re-run tree, not only the await.

    The runtime wraps the re-run in a shorter timer than the re-run's own budget; the cancellation that timer sends
    used to leave the command running to the worker's deadline while the caller was told "timed out". Here the
    re-run has 5 s and the outer timer 1 s, started once the heartbeat runs (a slow start cannot fail the premise).
    """
    agent = RedTeamAgent(pool="red_team")
    control_marker = tmp_path / "control"
    marker = tmp_path / "marker"
    try:
        # Control: never timed out from outside, the same re-run keeps beating.
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 10.0)
        control = asyncio.create_task(
            _rerun(agent, _spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
        )
        await _beats_until_ended(control_marker, control)

        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 5.0)
        async with _ContendedCall(hold=False, heartbeats=(marker,)) as pool:
            started_at = time.monotonic()
            rerun = pool.submit(
                _rerun(agent, _spawner_command(beater, marker, _BEAT_LIMIT_SECONDS, powershell=_ON_WINDOWS)),
            )
            await _heartbeat_is_running(marker, rerun)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(rerun, timeout=1.0)
            assert time.monotonic() - started_at < 4.5, "the re-run's own 5 s budget ended it, not the outer timer"
            await _assert_silent_after_the_call(marker)
            assert await pool.is_free(3.0), "the timed-out re-run left its worker thread running the command"
    finally:
        _stop_heartbeat(control_marker)
        _stop_heartbeat(marker)


@pytest.mark.timeout(90)
@pytest.mark.parametrize("site_name", ["shell", "red_team"])
async def test_queued_worker_cancelled_runs_nothing(
    site_name: str, tmp_path: Path, spawner: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A call cancelled while queued behind a busy pool starts nothing; neither does a worker with a cancelled slot.

    Phase 1 is end to end: the pool's only thread is held, the call is submitted and cancelled while its job is
    queued, then the thread is released. (The pool itself drops a cancelled queued job, so this phase cannot see
    the worker's own check.) Phase 2 hands the worker an already-cancelled slot, as when the caller gives up just
    after a thread picked the job up: it must run nothing. Both phases are judged by ``Popen`` (a command started
    and ended within milliseconds never writes ``.started``) and by ``.started``.
    """
    site = _site(site_name, monkeypatch)
    spawned = _watch_spawns(monkeypatch, site.module)

    # Control: on a free pool, with a live slot, the same call does start the command and it completes.
    control_marker = tmp_path / "control"
    assert site.in_time(await site.call(_spawner_command(spawner, control_marker, 1, powershell=_ON_WINDOWS))), (
        "control: an in-time call did not complete"
    )
    assert len(spawned) == 1, "control: the command was not started through subprocess.Popen"
    assert _started(control_marker).exists(), "control: the grandchild never started"
    spawned.clear()

    marker = tmp_path / "marker"
    command = _spawner_command(spawner, marker, 7, powershell=_ON_WINDOWS)
    async with _ContendedCall() as contended:
        call = contended.submit(site.call(command))
        await asyncio.sleep(0.5)
        assert not call.done(), "premise: the call returned while its job was still queued"
        assert spawned == [] and not _started(marker).exists(), "premise: the command started while the pool was held"
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        contended.release()
        await asyncio.sleep(0.5)  # the released thread now reaches the cancelled job
    assert spawned == [], "a call cancelled while queued started its command"
    assert not await _appears_async(_started(marker), 3), "a call cancelled while queued started its command"

    slot = ProcessTreeSlot()
    slot.cancel()
    refused = await asyncio.get_running_loop().run_in_executor(None, site.worker, command, slot)
    assert refused == site.refusal
    assert spawned == [], "a worker handed a cancelled slot started its command"
    assert not _started(marker).exists(), "a worker handed a cancelled slot started its command"


@pytest.mark.timeout(90)
@pytest.mark.parametrize("site_name", ["shell", "red_team"])
async def test_backstop_timeout_cancels_the_held_slot(site_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the caller's backstop gives up on a worker that never returns, the tree that worker holds is ended.

    The worker is a stand-in that holds a fake tree in the slot it is handed, then waits (a wedged worker). No real
    command runs, so the only thing that can end the held tree is the backstop's own ``slot.cancel()``. Control:
    the same stand-in released at once returns in time and its tree is left alone.
    """
    release = threading.Event()
    held: list[_FakeTree] = []

    def stand_in(slot: ProcessTreeSlot) -> None:
        held.append(_FakeTree())
        assert slot.hold(held[-1]) is True
        release.wait(10)

    if site_name == "shell":
        agent = ShellCommandAgent(pool="shell")
        agent.DEFAULT_TIMEOUT = 0.5
        agent.WORKER_TEARDOWN_GRACE = 0.5
        monkeypatch.setattr(
            ShellCommandAgent, "_run_sync",
            lambda self, command, deadline=None, slot=None: stand_in(slot) or {"success": True, "data": {}},
        )

        def call() -> Coroutine[Any, Any, Any]:
            return agent._run_command("ignored")

        def in_time(result: Any) -> bool:
            return result == {"success": True, "data": {}}

        def gave_up(result: Any) -> bool:
            return result == {"success": False, "error": "Command timed out after 0.5s"}
    else:
        agent = RedTeamAgent(pool="red_team")
        monkeypatch.setattr("probos.agents.red_team._RERUN_TIMEOUT_S", 0.5)
        monkeypatch.setattr("probos.agents.red_team._RERUN_TEARDOWN_GRACE_S", 0.5)
        monkeypatch.setattr(
            RedTeamAgent, "_run_verify_sync",
            staticmethod(lambda command, env, deadline=None, slot=None: stand_in(slot) or (0, "")),
        )

        def call() -> Coroutine[Any, Any, Any]:
            return _rerun(agent, "ignored")

        def in_time(result: Any) -> bool:
            return result.verified is True

        def gave_up(result: Any) -> bool:
            return result.verified is False and result.discrepancy == "Verification error: "

    try:
        release.set()
        assert in_time(await call()), "control: a stand-in that returns at once was not answered"
        assert held[0].kill_calls == 0, "control: a worker that returned in time had its tree ended"

        release.clear()
        assert gave_up(await call())
        assert len(held) == 2, "premise: the wedged worker never held its tree"
        assert held[1].kill_calls == 1, "the backstop gave up on the worker without ending the tree it held"
    finally:
        release.set()


@pytest.mark.timeout(90)
def test_slot_hold_after_cancel_kills() -> None:
    """A tree handed to a slot that was already cancelled is ended at once, and ``hold`` says so."""
    control = _FakeTree()
    assert ProcessTreeSlot().hold(control) is True, "control: a live slot refused a tree"
    assert control.kill_calls == 0, "control: a live slot ended the tree it was handed"

    slot = ProcessTreeSlot()
    slot.cancel()
    tree = _FakeTree()
    assert slot.hold(tree) is False
    assert tree.kill_calls == 1
    assert slot.cancelled() is True


@pytest.mark.timeout(90)
def test_slot_release_then_cancel_noop() -> None:
    """A tree the worker has released is no longer the slot's to end: a late ``cancel`` leaves it alone."""
    held = _FakeTree()
    control = ProcessTreeSlot()
    assert control.hold(held) is True
    control.cancel()
    assert held.kill_calls == 1, "control: cancel did not end a tree the slot still held"

    released = _FakeTree()
    slot = ProcessTreeSlot()
    assert slot.hold(released) is True
    slot.release()
    slot.cancel()
    assert released.kill_calls == 0
    assert slot.cancelled() is True


@pytest.mark.timeout(90)
def test_slot_cancel_swallows_a_failing_kill(caplog: pytest.LogCaptureFixture) -> None:
    """``cancel`` never raises when ending the held tree fails: it logs, so the caller's own cancellation survives."""
    healthy = _FakeTree()
    control = ProcessTreeSlot()
    control.hold(healthy)
    control.cancel()
    assert healthy.kill_calls == 1, "control: cancel did not end a tree the slot still held"

    failing = _FakeTree(kill_error=OSError("cannot end it"))
    slot = ProcessTreeSlot()
    slot.hold(failing)
    with caplog.at_level(logging.WARNING, logger="probos.execution.process_tree"):
        slot.cancel()
    assert failing.kill_calls == 1
    assert slot.cancelled() is True
    assert any("BF-893" in record.getMessage() for record in caplog.records)


@pytest.mark.timeout(90)
async def test_swe_run_command_cancel_ends_tree(tmp_path: Path, beater: Path) -> None:
    """Cancelling ``RunCommandTool.invoke`` while its command runs ends the command's whole tree."""
    tool = RunCommandTool(_FakeRuntime())
    control_marker = tmp_path / "control"
    marker = tmp_path / "marker"
    try:
        # Control: never cancelled, the same call keeps beating.
        control = asyncio.create_task(tool.invoke(
            {"command": _spawner_command(beater, control_marker, _BEAT_LIMIT_SECONDS, powershell=False), "timeout": 20},
        ))
        await _beats_until_ended(control_marker, control)

        call = asyncio.create_task(tool.invoke(
            {"command": _spawner_command(beater, marker, _BEAT_LIMIT_SECONDS, powershell=False), "timeout": 20},
        ))
        try:
            await _heartbeat_is_running(marker, call)
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
            await _assert_silent_after_the_call(marker)
        finally:
            _request_stop(marker)  # a command the cancellation failed to end ends now, so the call can settle
            await asyncio.gather(call, return_exceptions=True)
    finally:
        _stop_heartbeat(control_marker)
        _stop_heartbeat(marker)


@pytest.mark.timeout(90)
async def test_in_time_result_unchanged_with_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An in-time command answers exactly as before the slot existed; the slot is held and released, never cancelled."""
    printer = tmp_path / "printer.py"
    printer.write_text("print('bf893-ok')\n", encoding="utf-8")
    command = _printer_command(printer, powershell=_ON_WINDOWS)

    # Control: the recording slot does see a cancel, so "never cancelled" below can fail.
    probe: list[str] = []
    _recording_slot(probe)().cancel()
    assert probe == ["cancel"], "control: the recording slot did not record a cancel"

    shell_events: list[str] = []
    monkeypatch.setattr("probos.agents.shell_command.ProcessTreeSlot", _recording_slot(shell_events))
    answered = await ShellCommandAgent(pool="shell")._run_command(command)
    assert set(answered) == {"success", "data"}
    assert set(answered["data"]) == {"stdout", "stderr", "exit_code", "command"}
    assert answered["success"] is True
    assert answered["data"]["exit_code"] == 0
    assert "bf893-ok" in answered["data"]["stdout"]
    assert shell_events == ["hold", "release"]

    red_events: list[str] = []
    monkeypatch.setattr("probos.agents.red_team.ProcessTreeSlot", _recording_slot(red_events))
    agent = RedTeamAgent(pool="red_team")
    agreed = await _rerun(agent, command, claimed_stdout="bf893-ok")
    assert agreed.verified is True
    assert agreed.discrepancy == ""
    assert red_events == ["hold", "release"]
    red_events.clear()
    disagreed = await _rerun(agent, command, claimed_stdout="something else")
    assert disagreed.verified is False
    assert disagreed.discrepancy == "Stdout mismatch"
    assert red_events == ["hold", "release"]
