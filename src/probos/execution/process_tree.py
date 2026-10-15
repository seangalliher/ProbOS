"""BF-893 (#1544): the one owner of ending a spawned command's whole process tree.

A command started through a shell -- ``run_command`` in the native SWE harness,
``ShellCommandAgent``, the red team's re-run -- runs as the shell's child. Killing only
the shell on a timeout left the command running, so a caller told "timed out" could
still see its effects (a push, a write, a build).

POSIX: the shell starts a new session (``start_new_session=True``), so it and everything
it starts share one process group, and :meth:`ProcessTree.kill` sends ``SIGKILL`` to it.
Windows: the shell starts suspended (``CREATE_SUSPENDED``); :meth:`ProcessTree.attach`
puts it in a new job object and only then resumes it, so every process it starts is in
the job from its first instruction, and :meth:`ProcessTree.kill` ends the job
(``TerminateJobObject``), reaching even a descendant whose parent has exited.

Not covered: a descendant that leaves on purpose (``setsid`` or a double fork on POSIX;
work handed to a scheduler, service or COM server on either platform) outlives the
timeout, as before. Only a timeout kills: a command that finishes in time leaves its
background descendants running, as before (the job is not kill-on-close).
The job sets no breakaway-OK limit; a Windows descendant that asks to break away from it
(``CREATE_BREAKAWAY_FROM_JOB``) was observed to start normally and still be ended by a timeout.
"""

from __future__ import annotations

import ctypes
import functools
import logging
import os
import signal
import sys
import threading
import types
from typing import Any, Protocol

logger = logging.getLogger(__name__)

#: ``CREATE_SUSPENDED`` from winbase.h; ``subprocess`` does not export it.
CREATE_SUSPENDED = 0x00000004
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_SUSPEND_RESUME = 0x0800
#: The exit code ``subprocess.Popen.kill`` gives a process on Windows.
_KILLED_EXIT_CODE = 1


class SpawnedProcess(Protocol):
    """What :class:`ProcessTree` needs; ``subprocess.Popen`` and ``asyncio.subprocess.Process`` both fit."""

    @property
    def pid(self) -> int: ...

    def kill(self) -> None: ...


def process_tree_popen_kwargs(platform: str | None = None) -> dict[str, Any]:
    """Spawn keywords that make the child the root of a tree :class:`ProcessTree` can end.

    Pass them to ``subprocess.Popen`` or ``asyncio.create_subprocess_*`` and call
    :meth:`ProcessTree.attach` on the result at once: on Windows the child stays
    suspended until then.
    """
    plat = sys.platform if platform is None else platform
    if plat == "win32":
        return {"creationflags": CREATE_SUSPENDED}
    return {"start_new_session": True}


def _kill_direct(proc: SpawnedProcess) -> None:
    try:
        proc.kill()
    except OSError:
        pass  # already gone (ProcessLookupError is an OSError)


@functools.lru_cache(maxsize=1)
def _win32() -> Any:
    """kernel32/ntdll entry points with explicit signatures (a 64-bit HANDLE must not truncate)."""
    if sys.platform != "win32":
        raise OSError("BF-893: job objects exist only on Windows")
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    ntdll.NtResumeProcess.restype = ctypes.c_long  # NTSTATUS
    return types.SimpleNamespace(
        create_job=kernel32.CreateJobObjectW,
        open_process=kernel32.OpenProcess,
        assign=kernel32.AssignProcessToJobObject,
        terminate_job=kernel32.TerminateJobObject,
        close=kernel32.CloseHandle,
        resume=ntdll.NtResumeProcess,
    )


def _contain_suspended(proc: SpawnedProcess) -> int | None:
    """Put a suspended child in a new job, then resume it. The job handle, or None when no job could hold it."""
    api = _win32()
    handle = api.open_process(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE | _PROCESS_SUSPEND_RESUME, False, proc.pid)
    if not handle:
        error = ctypes.get_last_error()
        _kill_direct(proc)
        raise OSError(error, f"BF-893: could not open the spawned command (pid {proc.pid}) to start it; it was killed")
    try:
        job = api.create_job(None, None)
        if not job:
            logger.warning(
                "BF-893: no job object for pid %s (error %s); a timeout will end only the shell, not the command under it",
                proc.pid, ctypes.get_last_error(),
            )
        elif not api.assign(job, handle):
            logger.warning(
                "BF-893: could not place pid %s in a job object (error %s); a timeout will end only the shell, "
                "not the command under it", proc.pid, ctypes.get_last_error(),
            )
            api.close(job)
            job = None
        status = api.resume(handle)
        if status != 0:
            if job:
                api.terminate_job(job, _KILLED_EXIT_CODE)
                api.close(job)
            _kill_direct(proc)
            raise OSError(
                f"BF-893: could not start the spawned command (pid {proc.pid}, "
                f"NTSTATUS {status & 0xFFFFFFFF:#010x}); it was killed"
            )
        return int(job) if job else None
    finally:
        api.close(handle)


class ProcessTree:
    """Ends a spawned command and every process it started.

    Build it with :meth:`attach`. Built directly with neither a job nor a group it can
    end only the process itself -- the pre-BF-893 behaviour, used when the platform
    could not give a tree.
    """

    def __init__(self, proc: SpawnedProcess, *, job: int | None = None, group: int | None = None) -> None:
        self._proc = proc
        self._job = job
        self._group = group

    @classmethod
    def attach(cls, proc: SpawnedProcess) -> ProcessTree:
        """Own *proc*'s tree. Call it right after spawning with :func:`process_tree_popen_kwargs`.

        Raises ``OSError`` only on Windows, after killing the child, when the suspended
        child cannot be opened or resumed.
        """
        if sys.platform == "win32":
            return cls(proc, job=_contain_suspended(proc))
        return cls(proc, group=proc.pid)

    def kill(self) -> None:
        """End the whole tree. Never raises; a command that already exited is not an error."""
        if sys.platform == "win32":
            if self._job is not None:
                if _win32().terminate_job(self._job, _KILLED_EXIT_CODE):
                    return
                logger.warning(
                    "BF-893: could not end the job of pid %s (error %s); ending only the shell",
                    self._proc.pid, ctypes.get_last_error(),
                )
        elif self._group is not None:
            if self._group == os.getpgrp():
                logger.error(
                    "BF-893: refusing to signal the runtime's own process group %s; ending only pid %s",
                    self._group, self._proc.pid,
                )
            else:
                try:
                    os.killpg(self._group, signal.SIGKILL)
                    return
                except ProcessLookupError:
                    pass  # the group is gone: nothing of the tree is left
                except OSError as exc:
                    logger.warning(
                        "BF-893: could not signal process group %s (%s); ending only the shell", self._group, exc,
                    )
        _kill_direct(self._proc)

    def close(self) -> None:
        """Release the job handle. Ends nothing: only :meth:`kill` does."""
        if sys.platform == "win32" and self._job is not None:
            _win32().close(self._job)
        self._job = None

    def __enter__(self) -> ProcessTree:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: types.TracebackType | None) -> None:
        self.close()


class ProcessTreeSlot:
    """Lets an async caller end a worker thread's tree when the caller gives up (BF-893).

    The worker holds its tree (:meth:`hold`) right after :meth:`ProcessTree.attach` and releases
    it (:meth:`release`) before the tree is closed; :meth:`cancel` ends a held tree and makes a
    later :meth:`hold` end its tree at once. Cancelling and holding share one lock, and the kill
    runs under it, so a job handle is never closed while it is being ended.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tree: ProcessTree | None = None
        self._cancelled = False

    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def hold(self, tree: ProcessTree) -> bool:
        """Register *tree*. When the slot is already cancelled, end it and return False."""
        with self._lock:
            if not self._cancelled:
                self._tree = tree
                return True
        tree.kill()
        return False

    def release(self) -> None:
        with self._lock:
            self._tree = None

    def cancel(self) -> None:
        """Mark the slot cancelled and end any held tree. A failure to end it is logged, not raised."""
        with self._lock:
            self._cancelled = True
            tree, self._tree = self._tree, None
            if tree is None:
                return
            try:
                tree.kill()
            except Exception:
                logger.warning("BF-893: ending a cancelled command's tree failed", exc_info=True)
