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

AD-738g (#1662): a process is fixed by a ``WorkerKey``. ``PiperWorkerKey`` is BF-918's
key, unchanged; ``KokoroWorkerKey`` runs ``scripts/kokoro_worker.py``, which speaks the
same line protocol and takes each request's voice and speed as extra fields. One Kokoro
process serves every voice, and a request it answers without audio does not retire it.
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
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Callable, Iterator, Mapping, Protocol, TypeVar

from probos.execution.command_env import trusted_command_env
from probos.utils.step_timing import TimingLines, ms_between

logger = logging.getLogger(__name__)

#: Threads for voice work: Piper requests and rhubarb/ffmpeg runs.
VOICE_EXECUTOR_WORKERS = 4
#: Voice work admitted at once, running or queued; beyond it work is refused and degrades.
VOICE_MAX_IN_FLIGHT = 4 * VOICE_EXECUTOR_WORKERS
#: Resident Piper processes at once (each holds a voice model in memory).
PIPER_MAX_RESIDENT = 4
#: How much of a dead process's stderr its warning quotes.
_STDERR_TAIL_BYTES = 500
#: BF-930: a Piper request that takes at least this long (milliseconds) is reported with its steps (log-only).
SLOW_SYNTHESIS_MS = 750.0
#: AD-738g S3a (#1662): the phoneme-timing file a Kokoro worker writes beside each WAV. The worker cannot
#: import this module, so ``scripts/kokoro_worker.py`` keeps its own ``TIMING_SUFFIX`` and a test pins the two equal.
TIMING_SUFFIX = ".timing.json"
#: AD-738g S3a: a timing file over this size is not read (4096 timed symbols of about 45 bytes each, with headroom).
TIMING_MAX_BYTES = 262144

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


class WorkerKey(Protocol):
    """AD-738g (#1662): what one resident process is fixed to; implemented by frozen, hashable dataclasses.

    ``label`` names the engine in logs and in the temporary directory, ``name`` names the
    model in logs, and ``retire_on_empty`` says whether a request answered without audio
    retires the process (Piper: yes, as BF-918 shipped; Kokoro: no, its worker answers a
    request it cannot speak and stays healthy, and a restart reloads the model).
    AD-738g S3a: ``timing_sidecar`` says whether the worker may leave a phoneme-timing file
    beside the WAV (``TIMING_SUFFIX``), which the outcome then carries (Piper: no; Kokoro: yes).
    """

    @property
    def label(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def retire_on_empty(self) -> bool: ...

    @property
    def timing_sidecar(self) -> bool: ...

    def argv(self, output_dir: Path) -> list[str]: ...


@dataclass(frozen=True)
class PiperWorkerKey:
    """What one resident process is fixed to: the binary, the model and the prosody flags."""

    binary: str
    model: str
    noise_scale: float
    length_scale: float
    noise_w: float
    sentence_silence: float

    @property
    def label(self) -> str:
        return "piper"

    @property
    def name(self) -> str:
        return Path(self.model).stem

    @property
    def retire_on_empty(self) -> bool:
        return True

    @property
    def timing_sidecar(self) -> bool:
        return False

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
class KokoroWorkerKey:
    """AD-738g (#1662): one resident Kokoro worker (``scripts/kokoro_worker.py``) serves every voice.

    The voice and speed travel on each request line (``fields``); the process is fixed to
    the interpreter, the model, the voices file, the thread count and the default voice.
    ``-I`` keeps ``PYTHON*`` variables, the user site and the script's and working directories
    off ``sys.path``. The worker cannot import ``probos`` because its venv does not contain it
    (``scripts/kokoro-fetch.ps1`` checks this), not because of ``-I``.
    """

    python: str
    script: str
    model: str
    voices: str
    threads: int
    default_voice: str

    @property
    def label(self) -> str:
        return "kokoro"

    @property
    def name(self) -> str:
        return Path(self.model).stem

    @property
    def retire_on_empty(self) -> bool:
        return False

    @property
    def timing_sidecar(self) -> bool:
        return True

    def argv(self, output_dir: Path) -> list[str]:
        """The process's command line. Each request names its own output file, so ``output_dir`` is unused."""
        return [
            self.python, "-I", self.script,
            "--model", self.model,
            "--voices", self.voices,
            "--threads", str(self.threads),
            "--default-voice", self.default_voice,
        ]


@dataclass(frozen=True)
class PiperOutcome:
    """One request's result. ``audio`` is set only when ``reason`` is ``ok``.

    AD-738g S3a: ``timing`` is the worker's phoneme-timing file for that audio, when its key has
    ``timing_sidecar`` and the file was there and within ``TIMING_MAX_BYTES``; otherwise ``None``.
    """

    audio: bytes | None
    reason: str
    returncode: int | None = None
    stderr_tail: str = ""
    timing: bytes | None = None


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

    def __init__(self, key: WorkerKey) -> None:
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
        # BF-930: log-only. When the last request's blocking call started and ended on its thread (``time.perf_counter``).
        self.thread_started = 0.0
        self.thread_ended = 0.0

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def synthesize_blocking(
        self, text: str, timeout: float, fields: Mapping[str, str | float] | None = None,
    ) -> PiperOutcome:
        """Run one request; starts the process first when it is not running.

        Refused (``closed``) once the worker is closed. When ``close`` came while this
        request ran, the request releases the worker before it returns. AD-738g:
        ``fields`` (Kokoro's voice and speed) join the request line.
        """
        self.thread_started = time.perf_counter()  # BF-930: log-only
        with self._state:
            if self._closed:  # closed while this request was queued: start nothing
                return PiperOutcome(None, "closed")
            self._running = True
        try:
            # AD-738g: without fields the call keeps BF-918's two arguments (test stand-ins
            # replace this method with that signature: test_bf930_voice_path_timing.py).
            return self._request(text, timeout) if fields is None else self._request(text, timeout, fields)
        finally:
            self.thread_ended = time.perf_counter()  # BF-930: log-only
            with self._state:
                self._running = False
                release = self._closed
            if release:
                self._release(wait_seconds=0.5)

    def _request(
        self, text: str, timeout: float, fields: Mapping[str, str | float] | None = None,
    ) -> PiperOutcome:
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
                return PiperOutcome(None, f"error: no pipes to the {self.key.label} process")
            out = out_dir / f"{uuid.uuid4().hex}.wav"
            # One JSON object per line. ensure_ascii keeps every byte on the pipe ASCII,
            # and a line break in the text becomes a space, as the one-shot path's Piper
            # joined stdin's lines.
            payload: dict[str, str | float] = {"text": " ".join(text.splitlines()), "output_file": str(out)}
            if fields:
                # AD-738g: per-request fields follow the two above and never replace them.
                payload.update({name: value for name, value in fields.items() if name not in payload})
            line = json.dumps(payload, ensure_ascii=True)
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
            if not audio:
                return PiperOutcome(None, "empty")
            # AD-738g S3a: a timing key's worker may have left phoneme timings beside the WAV.
            timing = self._read_timing(out) if self.key.timing_sidecar else None
            return PiperOutcome(audio, "ok", timing=timing)
        except (OSError, ValueError) as exc:
            if self._timed_out:
                return PiperOutcome(None, "timeout")
            return PiperOutcome(None, f"error: {type(exc).__name__}: {exc}")
        finally:
            if out is not None:
                # AD-738g S3a: the timing file goes with its WAV (a leftover would also go with the directory).
                leftovers = (out, out.with_name(out.name + TIMING_SUFFIX)) if self.key.timing_sidecar else (out,)
                for leftover in leftovers:
                    try:
                        leftover.unlink(missing_ok=True)
                    except OSError:
                        pass

    @staticmethod
    def _read_timing(wav: Path) -> bytes | None:
        """AD-738g S3a: the timing file beside ``wav``. ``None`` when there is none (a model that reports
        no durations, or a write the worker gave up on), when it cannot be read, or when it is over
        ``TIMING_MAX_BYTES``; the last two log one WARNING. Never raises."""
        path = wav.with_name(wav.name + TIMING_SUFFIX)
        try:
            with path.open("rb") as handle:
                data = handle.read(TIMING_MAX_BYTES + 1)
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning(
                "AD-738g: cannot read the timing file (%s: %s); this sentence has no synthesizer timings",
                type(exc).__name__, exc,
            )
            return None
        if len(data) > TIMING_MAX_BYTES:
            logger.warning(
                "AD-738g: the timing file is over %d bytes; this sentence has no synthesizer timings",
                TIMING_MAX_BYTES,
            )
            return None
        return data

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
        directory = Path(tempfile.mkdtemp(prefix=f"probos-{self.key.label}-"))
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
        logger.info("BF-918: resident %s started (voice=%s)", self.key.label, self.key.name)

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
        self._resident: OrderedDict[WorkerKey, PiperWorker] = OrderedDict()
        self._busy: set[WorkerKey] = set()
        # BF-918: evicted workers whose close has not run yet; ``close`` reaches them here.
        self._retiring: set[PiperWorker] = set()
        self._locks: dict[WorkerKey, asyncio.Lock] = {}
        self._timing = TimingLines(logger)  # BF-930: log-only

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

    async def synthesize(
        self, key: WorkerKey, text: str, timeout: float, *, fields: Mapping[str, str | float] | None = None,
    ) -> bytes | None:
        """WAV bytes for ``text`` from the resident process for ``key``, or ``None`` to degrade.

        AD-738g: ``fields`` join the request line (Kokoro's voice and speed); Piper passes
        none, so its line is unchanged. AD-738g S3a: ``synthesize_outcome`` without the timing.
        """
        outcome = await self.synthesize_outcome(key, text, timeout, fields=fields)
        return None if outcome is None else outcome.audio

    async def synthesize_outcome(
        self, key: WorkerKey, text: str, timeout: float, *, fields: Mapping[str, str | float] | None = None,
    ) -> PiperOutcome | None:
        """AD-738g S3a: the ``ok`` outcome for ``text`` (its WAV bytes and, for a ``timing_sidecar``
        key, its timing file or ``None``), or ``None`` to degrade. Admission, locking, retirement and
        the BF-930 timing line are ``synthesize``'s, unchanged."""
        with self.admit() as admitted:
            if not admitted:
                if not self._closed:
                    logger.warning(
                        "BF-918: voice work refused, %d request(s) already in flight (limit %d); "
                        "the browser speaks this one",
                        self._in_flight, self._max_in_flight,
                    )
                return None
            t_enter = time.perf_counter()  # BF-930: log-only stamps; the awaits below keep their order
            lock = self._locks.setdefault(key, asyncio.Lock())
            async with lock:
                t_locked = time.perf_counter()
                if self._closed:
                    return None
                worker = await self._claim(key)
                if worker is None:
                    return None
                t_claimed = time.perf_counter()
                loop = asyncio.get_running_loop()
                self._busy.add(key)
                try:
                    cold = not worker.alive
                    t_submit = time.perf_counter()
                    # AD-738g: no third argument without fields (D8 of the contract).
                    extra: tuple[Mapping[str, str | float], ...] = () if fields is None else (fields,)
                    future = loop.run_in_executor(self.executor, worker.synthesize_blocking, text, timeout, *extra)
                    outcome = await future
                    t_resumed = time.perf_counter()
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
                    logger.warning("BF-918: %s request failed; the browser speaks this one", key.label, exc_info=True)
                    self._forget(key, worker)
                    return None
                finally:
                    self._busy.discard(key)
                # BF-930: log-only. Where a slow request's time went (milliseconds, monotonic clock).
                total_ms = ms_between(t_enter, t_resumed)
                # BF-930: a request that shutdown ended is not timed; one refused at the thread's entry set no end stamp.
                if total_ms >= SLOW_SYNTHESIS_MS and outcome.reason != "closed":
                    self._timing.emit(
                        "BF-930: %s request slow chars=%d voice=%s total_ms=%.0f lock_wait_ms=%.0f claim_ms=%.0f "
                        "pool_wait_ms=%.0f work_ms=%.0f resume_lag_ms=%.0f cold=%s result=%s in_flight=%d",
                        key.label, len(text), key.name, total_ms, ms_between(t_enter, t_locked),
                        ms_between(t_locked, t_claimed), ms_between(t_submit, worker.thread_started),
                        ms_between(worker.thread_started, worker.thread_ended),
                        ms_between(worker.thread_ended, t_resumed), "yes" if cold else "no",
                        "ok" if outcome.audio is not None else "failed", self._in_flight,
                    )
                if outcome.audio is not None:
                    return outcome
                if not self._closed:  # a request that shutdown ended is not a voice failure
                    self._log_failure(key.label, outcome, text, timeout)
                if outcome.reason == "empty" and not key.retire_on_empty:
                    return None  # AD-738g: the worker answered without audio; it stays resident
                if self._resident.get(key) is worker:
                    del self._resident[key]
                await self._retire(worker)
                return None

    async def _claim(self, key: WorkerKey) -> PiperWorker | None:
        """The resident worker for ``key``, made when missing; the least recently used idle one makes room."""
        worker = self._resident.get(key)
        if worker is not None:
            self._resident.move_to_end(key)
            return worker
        while len(self._resident) >= self._max_resident:
            idle = next((k for k in self._resident if k not in self._busy), None)
            if idle is None:
                logger.warning(
                    "BF-918: all %d resident voice processes are busy; the browser speaks this one",
                    self._max_resident,
                )
                return None
            await self._retire(self._resident.pop(idle))
        worker = PiperWorker(key)
        self._resident[key] = worker
        return worker

    def _forget(self, key: WorkerKey, worker: PiperWorker) -> None:
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
    def _log_failure(label: str, outcome: PiperOutcome, text: str, timeout: float) -> None:
        if outcome.reason == "timeout":
            logger.warning(
                "AD-738/BF-918: %s timed out after %ss synthesizing %d chars; killed, "
                "and the next request starts a new process",
                label, timeout, len(text),
            )
        elif outcome.reason == "exited":
            logger.warning("AD-738/BF-918: %s exit=%s; stderr=%s", label, outcome.returncode, outcome.stderr_tail)
        elif outcome.reason == "empty":
            logger.warning("AD-738/BF-918: %s produced 0 bytes; degrading", label)
        else:
            logger.warning("AD-738/BF-918: %s subprocess failed: %s", label, outcome.reason)

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
            logger.info("BF-918: voice synthesis closed; stopped %d resident voice process(es)", len(workers))
