"""BF-918 (#1626): a stand-in for a resident ``piper --json-input`` process.

Only the process is fake. The worker under test writes real JSON lines to it and
reads real path lines back, and each WAV is written into the worker's own
directory, so the code path is the production one. Nothing here needs piper.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

#: How long a fake read waits for an answer before reporting end of file.
_READ_DEADLINE_S = 10.0


class _Stdin:
    def __init__(self, proc: "FakePiperProcess") -> None:
        self._proc = proc
        self.closed = False  # BF-918 A2: what the worker released is observable

    def write(self, data: bytes) -> int:
        self._proc.accept(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _Stdout:
    def __init__(self, proc: "FakePiperProcess") -> None:
        self._proc = proc
        self.closed = False

    def readline(self) -> bytes:
        return self._proc.next_line()

    def close(self) -> None:
        self.closed = True


class FakePiperProcess:
    """One fake resident process. ``mode`` decides how it answers each request.

    ``ok``: writes ``wav`` to the request's ``output_file`` and prints that path.
    ``empty``: writes an empty file and prints its path.
    ``hang``: never answers; a read returns end of file once killed.
    ``exit``: writes ``stderr_bytes`` to the stderr file it was given and exits with code 1.
    ``gate``: as ``ok``, but answers only once ``release`` is set.
    """

    def __init__(
        self,
        args: list[str],
        kwargs: dict[str, Any],
        *,
        mode: str,
        wav: bytes,
        stderr_bytes: bytes,
        release: threading.Event | None,
    ) -> None:
        self.args = list(args)
        self.kwargs = dict(kwargs)
        self.mode = mode
        self.wav = wav
        self.stderr_bytes = stderr_bytes
        self.release = release
        self.requests: list[dict[str, Any]] = []
        self.request_threads: list[str] = []
        self.killed = False
        self.overlapped = False
        self.returncode: int | None = None
        self._busy = False
        self._lines: list[bytes] = []
        self._cond = threading.Condition()
        self.stdin = _Stdin(self)
        self.stdout = _Stdout(self)

    def accept(self, data: bytes) -> None:
        with self._cond:
            if self.returncode is not None:
                raise BrokenPipeError("the fake piper process has exited")
            if self._busy:
                self.overlapped = True
            self._busy = True
            request = json.loads(data.decode("ascii"))
            self.requests.append(request)
            self.request_threads.append(threading.current_thread().name)
        if self.mode == "hang":
            return
        if self.mode == "exit":
            stderr = self.kwargs.get("stderr")
            if stderr is not None and hasattr(stderr, "write"):
                stderr.write(self.stderr_bytes)
                stderr.flush()
            self._exit(1)
            return
        if self.mode == "gate" and self.release is not None:
            self.release.wait(timeout=_READ_DEADLINE_S)
        out = Path(request["output_file"])
        out.write_bytes(b"" if self.mode == "empty" else self.wav)
        with self._cond:
            self._busy = False
            self._lines.append(str(out).encode("utf-8") + b"\n")
            self._cond.notify_all()

    def next_line(self) -> bytes:
        deadline = time.monotonic() + _READ_DEADLINE_S
        with self._cond:
            while not self._lines and self.returncode is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return b""
                self._cond.wait(timeout=remaining)
            return self._lines.pop(0) if self._lines else b""

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self._exit(-9)

    def _exit(self, code: int) -> None:
        with self._cond:
            if self.returncode is None:
                self.returncode = code
            self._busy = False
            self._cond.notify_all()


class FakePiperLauncher:
    """Stands in for ``subprocess.Popen``. The n-th launch uses the n-th mode; the last repeats."""

    def __init__(
        self,
        *modes: str,
        wav: bytes = b"RIFF fake wav",
        stderr_bytes: bytes = b"",
        release: threading.Event | None = None,
        spawn_gate: threading.Event | None = None,
    ) -> None:
        self.modes = list(modes) or ["ok"]
        self.wav = wav
        self.stderr_bytes = stderr_bytes
        self.release = release
        # BF-918 A2: a launch sets ``spawning`` and then waits for ``spawn_gate`` (if given),
        # so a test can close the worker while ``Popen`` has not returned.
        self.spawn_gate = spawn_gate
        self.spawning = threading.Event()
        self.launched: list[FakePiperProcess] = []
        self.launch_threads: list[str] = []

    def __call__(self, args: list[str], *_pos: Any, **kwargs: Any) -> FakePiperProcess:
        self.spawning.set()
        if self.spawn_gate is not None:
            self.spawn_gate.wait(timeout=_READ_DEADLINE_S)
        mode = self.modes[min(len(self.launched), len(self.modes) - 1)]
        proc = FakePiperProcess(
            args, kwargs, mode=mode, wav=self.wav, stderr_bytes=self.stderr_bytes, release=self.release,
        )
        self.launched.append(proc)
        self.launch_threads.append(threading.current_thread().name)
        return proc
