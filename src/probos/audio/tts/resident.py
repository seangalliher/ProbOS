"""BF-918 (#1626): resident Piper synthesis on a dedicated, bounded executor.

Before BF-918 every ``POST /api/avatars/tts`` started ``piper`` and loaded its voice
model (about 0.5 s of every call, measured 2026-10-22), and Piper, rhubarb and ffmpeg
ran on asyncio's default thread pool, which about 100 call sites share with crew
cognition. This module keeps one ``piper --json-input`` process per voice and prosody
set, and runs all voice work on its own executor.

Piper fixes the model and the prosody flags per process (a JSON line carries only
``text``, ``output_file``, ``speaker_id`` and ``speaker``: rhasspy/piper
``src/cpp/main.cpp``), so a process is keyed by both. The per-emotion prosody table
(``prosody.py``) is finite, so the keys are too.

Kept from the one-shot path: the per-request timeout (a hung process is killed and
the next request starts a new one); honest degrade to ``None``; BF-282 (each WAV goes
to a file, never stdout); BF-280 (``subprocess.Popen`` in a thread, never an asyncio
subprocess); BF-892 (``env=trusted_command_env()``). New: a clean stop with the
runtime (``close``, called from ``startup/shutdown.py``).

Not ``loop.set_default_executor``: that would change the pool under every other
caller, crew cognition included, and bound none of them.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import json
import logging
import shutil
import subprocess
import tempfile
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Callable, Iterator, TypeVar

from probos.execution.command_env import trusted_command_env

logger = logging.getLogger(__name__)

#: Threads for voice work: Piper requests and rhubarb/ffmpeg runs.
VOICE_EXECUTOR_WORKERS = 4
#: Voice work admitted at once, running or queued; beyond it work is refused and degrades.
VOICE_MAX_IN_FLIGHT = 4 * VOICE_EXECUTOR_WORKERS
#: Resident Piper processes at once (each holds a voice model in memory).
PIPER_MAX_RESIDENT = 4
#: How much of a dead process's stderr its warning quotes.
_STDERR_TAIL_BYTES = 500

_T = TypeVar("_T")


class VoiceWorkRefused(OSError):
    """BF-918: the voice executor refused work, or its shutdown cancelled queued work.

    An ``OSError``, so the subprocess helpers' existing log-and-degrade handlers
    (ffmpeg and rhubarb return ``None`` or ``[]`` on ``OSError`` and remove their
    converted file) degrade on it unchanged.
    """


def _caller_cancelled() -> bool:
    """True when the running task itself was asked to stop, not when an executor future was cancelled."""
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


async def run_voice_work(executor: concurrent.futures.Executor | None, fn: Callable[..., _T], *args: Any) -> _T:
    """``fn(*args)`` on ``executor`` (``None``: asyncio's default pool).

    Raises ``VoiceWorkRefused`` when the executor is shut down, or when its shutdown
    cancelled the work before it ran; a cancellation of the calling task propagates.
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(executor, fn, *args)
    except RuntimeError as exc:
        raise VoiceWorkRefused(f"BF-918: voice work refused: {exc}") from exc
    except asyncio.CancelledError:
        if _caller_cancelled():
            raise
        raise VoiceWorkRefused("BF-918: the voice executor shut down before this work ran") from None


@dataclass(frozen=True)
class PiperWorkerKey:
    """What one resident process is fixed to: the binary, the model and the prosody flags."""

    binary: str
    model: str
    noise_scale: float
    length_scale: float
    noise_w: float
    sentence_silence: float

    def argv(self, output_dir: Path) -> list[str]:
        """The process's command line. ``--output_dir`` is a fallback; each request names its own file."""
        return [
            self.binary,
            "--model", self.model,
            "--json-input",
            "--output_dir", str(output_dir),
            "--noise_scale", str(self.noise_scale),
            "--length_scale", str(self.length_scale),
            "--noise_w", str(self.noise_w),
            "--sentence_silence", str(self.sentence_silence),
        ]


@dataclass(frozen=True)
class PiperOutcome:
    """One request's result. ``audio`` is set only when ``reason`` is ``ok``."""

    audio: bytes | None
    reason: str
    returncode: int | None = None
    stderr_tail: str = ""


class PiperWorker:
    """One resident ``piper --json-input`` process for one ``PiperWorkerKey``.

    ``synthesize_blocking`` blocks: the service runs it on the voice executor, one
    request at a time per worker (it holds the key's lock). The process, its stderr
    file and its output directory belong to this object until they are released.

    BF-918 lifecycle: open (idle, or running one request) until ``close``, then closed
    for good. Exactly one party releases the resources: ``close`` when the worker is
    idle, or the running request on its own thread when it returns (``close`` then only
    kills the process, so no pipe is closed under a read). A closed worker refuses
    every later request and starts nothing.
    """

    def __init__(self, key: PiperWorkerKey) -> None:
        self.key = key
        self._proc: subprocess.Popen[bytes] | None = None
        self._dir: Path | None = None
        self._stderr: IO[bytes] | None = None
        self._timed_out = False
        # Guards the two flags below and every swap of the three resources above;
        # never held across a blocking call.
        self._state = threading.Lock()
        self._running = False
        self._closed = False

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def synthesize_blocking(self, text: str, timeout: float) -> PiperOutcome:
        """Run one request; starts the process first when it is not running.

        Refused (``closed``) once the worker is closed. When ``close`` came while this
        request ran, the request releases the worker before it returns.
        """
        with self._state:
            if self._closed:  # closed while this request was queued: start nothing
                return PiperOutcome(None, "closed")
            self._running = True
        try:
            return self._request(text, timeout)
        finally:
            with self._state:
                self._running = False
                release = self._closed
            if release:
                self._release(wait_seconds=0.5)

    def _request(self, text: str, timeout: float) -> PiperOutcome:
        """One request on this worker's process; ``synthesize_blocking`` owns the lifecycle around it."""
        out: Path | None = None
        try:
            if not self.alive:
                self._spawn()
                if self._closed:  # closed while Popen ran, so close found no process to kill
                    self.kill()
                    return PiperOutcome(None, "closed")
            proc, out_dir = self._proc, self._dir
            if proc is None or out_dir is None or proc.stdin is None or proc.stdout is None:
                return PiperOutcome(None, "error: no pipes to the piper process")
            out = out_dir / f"{uuid.uuid4().hex}.wav"
            # One JSON object per line. ensure_ascii keeps every byte on the pipe ASCII,
            # and a line break in the text becomes a space, as the one-shot path's Piper
            # joined stdin's lines.
            line = json.dumps({"text": " ".join(text.splitlines()), "output_file": str(out)}, ensure_ascii=True)
            self._timed_out = False
            timer = threading.Timer(timeout, self._expire, args=(proc,))
            timer.daemon = True
            timer.start()
            try:
                proc.stdin.write(line.encode("ascii") + b"\n")
                proc.stdin.flush()
                answered = self._await_answer(proc.stdout, out.name)
            finally:
                timer.cancel()
            if self._timed_out:
                return PiperOutcome(None, "timeout")
            if not answered:
                return PiperOutcome(None, "exited", self._reap(proc), self._stderr_tail())
            audio = out.read_bytes() if out.is_file() else b""
            return PiperOutcome(audio, "ok") if audio else PiperOutcome(None, "empty")
        except (OSError, ValueError) as exc:
            if self._timed_out:
                return PiperOutcome(None, "timeout")
            return PiperOutcome(None, f"error: {type(exc).__name__}: {exc}")
        finally:
            if out is not None:
                try:
                    out.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _await_answer(stdout: IO[bytes], name: str) -> bool:
        """Read lines until Piper prints the path of ``name``; False at end of file."""
        while True:
            reply = stdout.readline()
            if not reply:
                return False
            if Path(reply.decode("utf-8", errors="replace").strip()).name == name:
                return True

    @staticmethod
    def _reap(proc: subprocess.Popen[bytes]) -> int | None:
        try:
            return proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            return None

    def _stderr_tail(self) -> str:
        if self._dir is None:
            return ""
        try:
            data = (self._dir / "stderr.log").read_bytes()
        except OSError:
            return ""
        return data[-_STDERR_TAIL_BYTES:].decode("utf-8", errors="replace")

    def _expire(self, proc: subprocess.Popen[bytes]) -> None:
        self._timed_out = True
        try:
            proc.kill()
        except OSError:
            pass

    def _spawn(self) -> None:
        self._release(wait_seconds=2.0)  # a dead process's leftovers; the worker stays open
        directory = Path(tempfile.mkdtemp(prefix="probos-piper-"))
        # BF-918 A5: the worker owns the directory from its creation, so ``_release`` removes it
        # even when the open below fails (with no stderr file yet, it closes none).
        with self._state:
            self._dir = directory
        # BF-918: stderr goes to a file, so Piper's per-line log can never fill a pipe and block it.
        stderr = (directory / "stderr.log").open("wb")
        with self._state:
            self._stderr = stderr
        proc = subprocess.Popen(
            self.key.argv(directory),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            env=trusted_command_env(),
        )
        with self._state:
            self._proc = proc
        logger.info("BF-918: resident piper started (voice=%s)", Path(self.key.model).stem)

    def kill(self) -> None:
        """Kill the process if it runs. Never blocks."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    def close(self, wait_seconds: float = 2.0) -> None:
        """Refuse every later request, and release the process, pipes, stderr file and directory.

        Idempotent; never raises. On a worker running a request it only kills the
        process: that request releases the rest on its own thread when it returns, so
        no pipe is closed under its read.
        """
        with self._state:
            self._closed = True
            running = self._running
        if running:
            self.kill()  # the running request releases the rest when it returns
            return
        self._release(wait_seconds)

    def _release(self, wait_seconds: float) -> None:
        """Kill the process and release its pipes, stderr file and directory; a no-op once released."""
        with self._state:
            proc, self._proc = self._proc, None
            stderr, self._stderr = self._stderr, None
            directory, self._dir = self._dir, None
        if proc is not None:
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
            try:
                proc.wait(timeout=wait_seconds)
            except subprocess.TimeoutExpired:
                pass
            for stream in (proc.stdin, proc.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        if stderr is not None:
            try:
                stderr.close()
            except OSError:
                pass
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)


class VoiceSynthesisService:
    """BF-918: the runtime's voice work: one bounded executor and the resident Piper processes.

    Owned by the runtime (``runtime.voice_synthesis``), built with it (constructing it
    starts nothing) and closed at shutdown. Everything but the workers' blocking
    methods runs on the event loop. Work beyond ``max_in_flight`` is refused and
    degrades (the browser speaks that sentence, or keeps its heuristic lip-sync); it
    never queues without bound.
    """

    def __init__(
        self,
        *,
        workers: int = VOICE_EXECUTOR_WORKERS,
        max_in_flight: int = VOICE_MAX_IN_FLIGHT,
        max_resident: int = PIPER_MAX_RESIDENT,
    ) -> None:
        if min(workers, max_in_flight, max_resident) < 1:
            raise ValueError("BF-918: voice synthesis limits must be at least 1")
        self._workers = workers
        self._max_in_flight = max_in_flight
        self._max_resident = max_resident
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._in_flight = 0
        self._closed = False
        self._resident: OrderedDict[PiperWorkerKey, PiperWorker] = OrderedDict()
        self._busy: set[PiperWorkerKey] = set()
        # BF-918: evicted workers whose close has not run yet; ``close`` reaches them here.
        self._retiring: set[PiperWorker] = set()
        self._locks: dict[PiperWorkerKey, asyncio.Lock] = {}

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def resident_count(self) -> int:
        return len(self._resident)

    @property
    def executor(self) -> concurrent.futures.ThreadPoolExecutor:
        """The voice executor, made on first use. Raises ``RuntimeError`` once closed."""
        if self._closed:
            raise RuntimeError("BF-918: the voice synthesis service is closed")
        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=self._workers,
                thread_name_prefix="probos-voice",
            )
        return self._executor

    @contextlib.contextmanager
    def admit(self) -> Iterator[bool]:
        """Yield True and hold one slot while voice work runs; False when closed or full."""
        if self._closed or self._in_flight >= self._max_in_flight:
            yield False
            return
        self._in_flight += 1
        try:
            yield True
        finally:
            self._in_flight -= 1

    async def synthesize(self, key: PiperWorkerKey, text: str, timeout: float) -> bytes | None:
        """WAV bytes for ``text`` from the resident process for ``key``, or ``None`` to degrade."""
        with self.admit() as admitted:
            if not admitted:
                if not self._closed:
                    logger.warning(
                        "BF-918: voice work refused, %d request(s) already in flight (limit %d); "
                        "the browser speaks this one",
                        self._in_flight, self._max_in_flight,
                    )
                return None
            lock = self._locks.setdefault(key, asyncio.Lock())
            async with lock:
                if self._closed:
                    return None
                worker = await self._claim(key)
                if worker is None:
                    return None
                loop = asyncio.get_running_loop()
                self._busy.add(key)
                try:
                    future = loop.run_in_executor(self.executor, worker.synthesize_blocking, text, timeout)
                    outcome = await future
                except asyncio.CancelledError:
                    # The caller went away, or shutdown cancelled the request while it was queued.
                    # Close the worker (mid-request on its thread, it is killed and releases itself
                    # when that request returns) and drop it, so no later request shares its pipes.
                    self._forget(key, worker)
                    if not _caller_cancelled():
                        return None  # shutdown, not the caller: degrade, as a refusal does
                    raise
                except Exception:
                    # The executor shut down (the runtime is stopping) or the worker raised what
                    # it does not handle: degrade, and never reuse that worker.
                    logger.warning("BF-918: piper request failed; the browser speaks this one", exc_info=True)
                    self._forget(key, worker)
                    return None
                finally:
                    self._busy.discard(key)
                if outcome.audio is not None:
                    return outcome.audio
                if not self._closed:  # a request that shutdown ended is not a piper failure
                    self._log_failure(outcome, text, timeout)
                if self._resident.get(key) is worker:
                    del self._resident[key]
                await self._retire(worker)
                return None

    async def _claim(self, key: PiperWorkerKey) -> PiperWorker | None:
        """The resident worker for ``key``, made when missing; the least recently used idle one makes room."""
        worker = self._resident.get(key)
        if worker is not None:
            self._resident.move_to_end(key)
            return worker
        while len(self._resident) >= self._max_resident:
            idle = next((k for k in self._resident if k not in self._busy), None)
            if idle is None:
                logger.warning(
                    "BF-918: all %d resident piper processes are busy; the browser speaks this one",
                    self._max_resident,
                )
                return None
            await self._retire(self._resident.pop(idle))
        worker = PiperWorker(key)
        self._resident[key] = worker
        return worker

    def _forget(self, key: PiperWorkerKey, worker: PiperWorker) -> None:
        if self._resident.get(key) is worker:
            del self._resident[key]
        worker.close(wait_seconds=0.5)

    async def _retire(self, worker: PiperWorker) -> None:
        """Close a worker that has no request in flight, off the event loop when the executor takes it.

        Until its close has run the worker stays in ``_retiring``, where the service's
        ``close`` reaches it; the ``finally`` closes it here when the executor refused
        the close or a shutdown or the caller cancelled it. ``PiperWorker.close`` is
        idempotent, so once the queued close has run both are no-ops.
        """
        self._retiring.add(worker)
        worker.kill()
        try:
            await run_voice_work(self.executor, worker.close)
        except (VoiceWorkRefused, RuntimeError):
            pass  # closed or closing (``executor`` raises RuntimeError once closed): the finally closes it
        finally:
            self._retiring.discard(worker)
            worker.close(wait_seconds=0.5)  # a no-op once the queued close has run

    @staticmethod
    def _log_failure(outcome: PiperOutcome, text: str, timeout: float) -> None:
        if outcome.reason == "timeout":
            logger.warning(
                "AD-738/BF-918: piper timed out after %ss synthesizing %d chars; killed, "
                "and the next request starts a new process",
                timeout, len(text),
            )
        elif outcome.reason == "exited":
            logger.warning("AD-738/BF-918: piper exit=%s; stderr=%s", outcome.returncode, outcome.stderr_tail)
        elif outcome.reason == "empty":
            logger.warning("AD-738/BF-918: piper produced 0 bytes; degrading")
        else:
            logger.warning("AD-738/BF-918: piper subprocess failed: %s", outcome.reason)

    def close(self) -> None:
        """Stop every resident process and the executor; refuse all later work. Idempotent; never awaits.

        Every worker the service holds, resident or retiring, is closed here: an idle
        one is released now; a running one is killed, and its request releases it on its
        voice thread when it returns (``PiperWorker.close``). Queued work is cancelled,
        and its requests degrade instead of raising.
        """
        if self._closed:
            return
        self._closed = True
        workers = [*self._resident.values(), *self._retiring]
        self._resident.clear()
        for worker in workers:
            worker.kill()
        for worker in workers:
            worker.close(wait_seconds=0.5)  # a running worker releases itself when its request returns
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        if workers:
            logger.info("BF-918: voice synthesis closed; stopped %d resident piper process(es)", len(workers))
