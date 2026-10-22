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

import errno
import logging
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
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


#: AD-1341 S1 A7 (F3): the largest PID ``_read_pid_from`` returns. No supported platform issues a larger one (Linux's
#: ``pid_max`` is at most 2**22), and ``is_pid_alive``'s platform calls take a C int.
_MAX_PID = 2**31 - 1

#: AD-1341 S1 A8 (F3): the longest marker ``_read_pid_from`` accepts, in bytes. The writer stores at most ten ASCII
#: digits; anything longer is garbage, so the read is bounded and ``int`` never sees more than this many digits
#: (CPython refuses to convert more than ``sys.get_int_max_str_digits()``, 4,300 by default).
_MAX_MARKER_BYTES = 64


def _read_pid_from(pidfile: Path) -> int | None:
    """The PID ``pidfile`` names, or None when it cannot be read or is not a PID (AD-816's garbage).

    AD-1341 S1 A7 and A8 (F3): total over what the path holds, so the acquire replaces a malformed marker and the
    probe ignores it, instead of raising or blocking on every retry. Only a regular file is opened (opening a FIFO
    blocks until a writer appears), and at most one byte beyond ``_MAX_MARKER_BYTES`` is read; a longer file is
    garbage. The bytes are never decoded: once ASCII whitespace is stripped they must be ASCII digits (leading zeros
    allowed; ``bytes.isdigit`` is ASCII-only, so a superscript two, a sign or an underscore is garbage), so ``int``
    cannot raise, and the number must not exceed ``_MAX_PID``.
    """
    if not os.path.isfile(pidfile):  # A8 (F3): a FIFO would block the open; a directory or a device holds no marker
        return None
    try:
        with pidfile.open("rb") as marker:
            data = marker.read(_MAX_MARKER_BYTES + 1)
    except OSError:
        return None
    if len(data) > _MAX_MARKER_BYTES:  # A8 (F3): longer than any marker the writer makes
        return None
    digits = data.strip()
    if not digits.isdigit():
        return None
    pid = int(digits)
    return pid if pid <= _MAX_PID else None


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


#: AD-1341 S1 A4 (F2): how long an acquirer waits for another to finish inspecting or replacing the pidfile.
_TAKEOVER_WAIT_S = 10.0

#: AD-1341 S1 A6 (F2): the lock call's errors that mean another process holds the lock (py-filelock's set).
#: ``msvcrt.locking`` reports a held byte as EACCES; ``flock`` as EWOULDBLOCK (EAGAIN), or EACCES where a filesystem
#: emulates it. Any other error means this filesystem cannot lock, which no wait cures.
_CONTENTION_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK})


class PidfileLockUnavailable(RuntimeError):
    """The data directory's filesystem refused the takeover lock other than by contention (AD-1341 S1 A6, F2).

    There is no owner to stop and no wait cures it, so ProbOS refuses the directory rather than run unguarded.
    Deliberately not an ``AnotherInstanceRunning``: its handlers tell the Captain to stop a vessel.
    """

    def __init__(self, data_dir: Path, lock_path: Path, error: OSError) -> None:
        super().__init__(
            f"ProbOS cannot lock files in {data_dir}, so it cannot keep a second instance out and refuses to use "
            f"it. Use a data directory on a filesystem with file locks (--data-dir).\n"
            f"Lock file: {lock_path}\n"
            f"Error: {error}"
        )
        self.data_dir = data_dir
        self.lock_path = lock_path
        self.error = error


def _try_lock(fd: int) -> bool:
    """One non-blocking attempt at the OS lock on byte 0 of ``fd``: True when this process now holds it, False when
    another process does. Any other error is re-raised (A6, F2): this filesystem cannot lock."""
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in _CONTENTION_ERRNOS:
            return False  # another process holds it: wait, then refuse (fail closed)
        raise
    return True


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def _takeover_lock(data_dir: Path) -> Iterator[None]:
    """One process at a time creates, inspects or replaces ``probos.pid`` (AD-1341 S1 A4, F2).

    Without it, two acquirers that both read a stale PID could interleave: one replaced the stale file, the other
    then removed that fresh file by name and created its own, and both held the guard. The lock is the OS's, on
    ``probos.pid.lock``, which is never removed: the OS releases it when its holder exits, so a crash leaves no
    stale lock to break. It is held only for the acquire, never while a vessel or a reset runs. Waiting longer
    than ``_TAKEOVER_WAIT_S`` refuses, as a live owner does. A lock call that fails other than by contention raises
    ``PidfileLockUnavailable`` at once, with the lock file and the original error (A6, F2).
    """
    lock_path = Path(data_dir) / "probos.pid.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + _TAKEOVER_WAIT_S
        try:
            while not _try_lock(fd):
                if time.monotonic() >= deadline:
                    raise AnotherInstanceRunning(pid=-1, data_dir=Path(data_dir), pidfile=lock_path)
                time.sleep(0.02)
        except OSError as exc:  # A6 (F2): not contention (_try_lock re-raised it), so no wait can cure it
            raise PidfileLockUnavailable(Path(data_dir), lock_path, exc) from exc
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def acquire_pidfile(data_dir: Path) -> Path:
    """Atomically acquire the per-data-dir pidfile.

    Returns the acquired path on success. Raises
    :class:`AnotherInstanceRunning` if another live runtime holds it.
    Removes + retries once when the existing pidfile is stale. The whole
    sequence runs under ``_takeover_lock`` (AD-1341 S1 A4), so a second
    acquirer of a stale pidfile finds the first's live PID and refuses.
    """
    with _takeover_lock(data_dir):
        return _acquire_unlocked(data_dir)


def _acquire_unlocked(data_dir: Path) -> Path:
    """``acquire_pidfile``'s sequence; the caller holds ``_takeover_lock``."""
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
