"""AD-816: single-instance guard via atomic pidfile acquisition.

Atomically acquires ``{data_dir}/probos.pid`` using ``os.open(..., O_CREAT |
O_EXCL)`` — either we win and own the file, or we lose and inspect the
existing contents:

* live PID  → raise :class:`AnotherInstanceRunning`
* stale PID → remove and retry once

Different ``data_dir`` paths are independent nodes; the guard only
prevents two runtimes from sharing the same data directory.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class AnotherInstanceRunning(RuntimeError):
    def __init__(self, pid: int, data_dir: Path, pidfile: Path) -> None:
        super().__init__(
            f"Another ProbOS instance (PID {pid}) is already using "
            f"{data_dir}. Pass --data-dir to run a second sandbox, or "
            f"stop the existing instance first.\n"
            f"Pidfile: {pidfile}"
        )
        self.pid = pid
        self.data_dir = data_dir
        self.pidfile = pidfile


def is_pid_alive(pid: int) -> bool:
    """Whether ``pid`` names a process that is still running.

    Public because it is the repo's one answer to that question: AD-1265's
    backup sweep decides whether a working directory is abandoned or merely
    someone else's in-flight write, and a second implementation of liveness
    would be a second set of platform bugs.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _is_pid_alive_windows(pid)
    return _is_pid_alive_posix(pid)


def _is_pid_alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _is_pid_alive_windows(pid: int) -> bool:
    import ctypes

    SYNCHRONIZE = 0x00100000
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(
        SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        last_error = kernel32.GetLastError()
        return last_error != 87  # ERROR_INVALID_PARAMETER
    exit_code = ctypes.c_ulong(0)
    got = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
    kernel32.CloseHandle(handle)
    if not got:
        return True
    return exit_code.value == 259  # STILL_ACTIVE


def _read_pid_from(pidfile: Path) -> int | None:
    try:
        raw = pidfile.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    return int(raw)


def _try_atomic_create(pidfile: Path, pid: int) -> bool:
    """Return True iff we created ``pidfile`` (it didn't exist before)."""
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(pidfile), flags, 0o644)
    except FileExistsError:
        return False
    try:
        os.write(fd, str(pid).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def acquire_pidfile(data_dir: Path) -> Path:
    """Atomically acquire the per-data-dir pidfile.

    Returns the acquired path on success. Raises
    :class:`AnotherInstanceRunning` if another live runtime holds it.
    Removes + retries once when the existing pidfile is stale.
    """
    pidfile = Path(data_dir) / "probos.pid"
    own_pid = os.getpid()

    if _try_atomic_create(pidfile, own_pid):
        return pidfile

    existing = _read_pid_from(pidfile)
    if existing is None:
        logger.warning(
            "AD-816: pidfile %s unreadable/garbage; removing and retrying",
            pidfile,
        )
        try:
            pidfile.unlink(missing_ok=True)
        except OSError:
            pass
        if _try_atomic_create(pidfile, own_pid):
            return pidfile
        raise AnotherInstanceRunning(
            pid=-1, data_dir=Path(data_dir), pidfile=pidfile
        )

    if existing == own_pid:
        try:
            pidfile.unlink(missing_ok=True)
        except OSError:
            pass
        if _try_atomic_create(pidfile, own_pid):
            return pidfile

    if is_pid_alive(existing):
        raise AnotherInstanceRunning(
            pid=existing, data_dir=Path(data_dir), pidfile=pidfile
        )

    logger.info(
        "AD-816: removing stale pidfile %s (PID %d no longer running)",
        pidfile, existing,
    )
    try:
        pidfile.unlink(missing_ok=True)
    except OSError:
        pass
    if _try_atomic_create(pidfile, own_pid):
        return pidfile

    new_existing = _read_pid_from(pidfile)
    raise AnotherInstanceRunning(
        pid=new_existing or -1, data_dir=Path(data_dir), pidfile=pidfile
    )


def assert_no_other_instance(data_dir: Path) -> None:
    """Read-only liveness probe; does NOT acquire the pidfile.

    Use :func:`acquire_pidfile` from the runtime boot path — it closes
    the TOCTOU race. This API is here for read-only consumers (doctor).
    """
    pidfile = Path(data_dir) / "probos.pid"
    if not pidfile.exists():
        return
    existing = _read_pid_from(pidfile)
    if existing is None or existing == os.getpid():
        return
    if is_pid_alive(existing):
        raise AnotherInstanceRunning(
            pid=existing, data_dir=Path(data_dir), pidfile=pidfile
        )
