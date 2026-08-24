"""AD-993: Tier-1 isolation substrate for sandboxed code execution.

This is the foundation for letting crew agents safely create + run Python scripts
and install libraries to perform tasks (the GitHub Copilot / Claude Code pattern),
bounded by a **tiered isolation model** so the strength of the boundary can grow
without changing callers. (Not "attributable" -- ``ExecutionRequest`` and
``ExecutionResult`` carry no actor, intent or correlation field. AD-1247.)

**Two things are named ``run_python`` and NEITHER is quorum-approved before it
runs** (BF-763, BF-779). The agentic TOOL (``CodeExecutionTool``) resolves an
effective tool permission via ``tools/executor.py`` and ``tools/registry.py`` --
note that registration grants it ship-wide READ, so with no permission store
configured that check passes by default -- and nothing votes on the script. The
mesh INTENT declares ``requires_consensus=True`` on ``CodeRunnerAgent``, and that
agent executes in ``act()``, i.e. during the broadcast phase, while ``runtime``
evaluates quorum on the results afterwards -- and only when the plan's
model-chosen ``use_consensus`` was true, which defaults false. Compare
``FileWriterAgent``, which is
the pattern done right: its ``act()`` returns a proposal explicitly "not
executed" and a separate ``commit_write()`` runs after approval. Say "not
quorum-approved", not "ungoverned" -- the distinction is the whole point of
BF-763.

Tiered isolation (the ``IsolationBackend`` abstraction):

* **Tier 1 — ``SubprocessSandbox`` (this module).** Runs the submitted source in
  a child process against a working folder, with a timeout and output
  caps, and ``allow_network`` defaulting off. This is the Copilot "restrict the
  harness to a working folder" model.

  **What this module provides:** a child process, so the script does not share
  the runtime's interpreter state -- but it runs as the same user, and on the
  tested Windows host a child recovered 34/34 canary bytes from its parent via
  ``OpenProcess`` / ``ReadProcessMemory``, so a separate address space is not a
  confinement boundary (such access is OS-policy dependent, not universal); a
  timeout TRIGGER, which is not a return deadline -- ``run()`` can return well
  after it, because a surviving descendant can hold the output pipe open
  (observed on Windows: a 200 ms request returned at ~1.3 s). What ``_kill``
  signals differs by platform and has fallbacks; read it rather than trusting a
  summary here. See BF-781; output caps; environment scrubbing and ``-I``;
  and, on POSIX only, best-effort ``RLIMIT_AS`` / ``RLIMIT_CPU`` / ``RLIMIT_FSIZE``
  -- best-effort because setting them can fail and the failure is swallowed, and
  Windows has no equivalent hook here. It is NOT a kernel-enforced containment
  boundary: a determined script can read host files by absolute path, and network
  cannot be hard-blocked cross-platform without OS namespaces. Hard containment is
  Tier 2.

  This list is deliberately not written as exhaustive. Two earlier revisions
  claimed to enumerate the boundary completely and were wrong both times -- once
  by naming a consensus gate that does not exist, once by presenting an
  incomplete inventory as complete. Read the code for the full set.

  **Callers, not this module, decide what else applies.** Earlier revisions of
  this docstring enumerated "the real boundary at Tier 1" as a list including
  controls the calling paths did not have; that framing produced a false claim
  three revisions running, because a module cannot honestly summarise what its
  callers do. So it no longer tries. For what actually governs each caller see
  BF-779 (what consensus does and does not gate) and AD-1247 (the agentic path
  attempts a per-execution audit record when the sink is enabled; the mesh
  path's absence is BF-787). Do not restate their conclusions here -- link them.
* **Tier 2 — OS-native sandbox (AD-995, future).** Policy-driven, kernel-enforced
  isolation: bubblewrap (Linux), seatbelt (macOS), AppContainer (Windows), or
  ``microsoft/mxc`` once it matures — behind THIS SAME protocol.
* **Tier 3 — container / VM (AD-996, future, deferred).** Docker / WSL / microVM
  for hostile, multi-tenant, or reproducible-environment workloads.

Backends are pluggable behind ``IsolationBackend`` (``typing.Protocol``) so the
heavier tiers slot in without touching callers — the cloud-ready-storage
abstraction pattern applied to execution. A task is either deemed safe enough for
Tier 1 or escalates to a higher tier; the escalation policy lives with the caller
(AD-994 / AD-995).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# POSIX-only resource limits; absent on Windows (Tier 1 there degrades to
# timeout-only — another reason the OS-native Tier 2 matters on Windows).
try:  # pragma: no cover - platform-dependent import
    import resource as _resource
except ImportError:  # Windows
    _resource = None  # type: ignore[assignment]


class IsolationTier(IntEnum):
    """Strength of the isolation boundary. Higher = stronger + heavier."""

    SUBPROCESS = 1   # working-folder + subprocess + resource bounds (this module)
    OS_SANDBOX = 2   # kernel-enforced (bubblewrap/seatbelt/AppContainer/MXC)
    CONTAINER = 3    # container / VM (Docker / WSL / microVM)


@dataclass
class LaunchOutcome:
    """AD-1247: whether a child process was created, and whether that is known.

    ``run()`` hands work to an executor thread, and cancelling the awaiting task
    does NOT stop that thread -- it keeps going and may spawn the child after
    the caller has already given up. A bare "launched" flag read at that moment
    reports False for a script that is about to run, which is the one failure an
    audit trail must not have.

    So ``resolved`` is set as soon as the launch question has an ANSWER: right
    after ``Popen`` returns on the spawn path, and in a ``finally`` on every
    path that exits without spawning. It does NOT wait for the run to finish --
    an earlier revision resolved it on return, which made a caller unwinding
    beside a long-running child block for its whole bounded wait.

    ``launched`` is written before ``resolved`` is set and read after waiting on
    it, so the Event is the memory barrier between the two threads. A caller
    whose bounded wait EXPIRES has neither answer and must say so rather than
    assume either one.
    """

    resolved: threading.Event = field(default_factory=threading.Event)
    launched: bool = False


@dataclass
class CancelCleanup:
    """Ownership handshake for removing a scratch dir after a cancelled run.

    BF-788: the worker outlives the cancelled await, so it is usually the only
    place that can remove the directory once the child releases it. But a
    single flag races -- the worker can read it in the instant before the loop
    sets it, and then neither side cleans up. Each side publishes its own flag
    before reading the other's, so the one that observes last does the work.
    The loop side removes when the worker got there first, and the caller
    removes when no worker ever ran, so the worker is the common owner rather
    than the only one.

    ``started`` answers a different question: whether a worker has ENTERED
    ``_run_sync``. When the executor is saturated, cancelling the awaiting task
    cancels the QUEUED job outright and ``_run_sync`` never runs, so nobody
    would ever publish ``finished``. The caller must own removal in that case
    -- and must NOT own it otherwise, because removing while a child is live
    deletes the files it is using (measured: the script died with
    FileNotFoundError).

    NOT airtight: a ThreadPoolExecutor future stops being cancellable slightly
    BEFORE it invokes the callable, so there is a window where the job is
    running but ``started`` is still clear. Filed; HEAD removes unconditionally
    and corrupts in that same window.
    """

    cancelled: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    started: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _claimed: bool = False

    def claim(self) -> bool:
        """Take ownership of the removal. First caller wins; the rest decline.

        The two flag reads can BOTH succeed: if `cancelled` and `finished` are
        set before either side reads, each sees the other's and removes.
        Measured `REMOVE_CALL_COUNT=2` on separate threads. `rmtree` is
        idempotent, but two retry loops occupy two executor threads and can
        both warn about the same directory.
        """
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True


def _still_present(workdir: Path) -> bool:
    """Is the directory entry still there?

    BF-788: anything that prevents a definite answer counts as PRESENT.
    Guessing "gone" is exactly how the original leak stayed silent, and
    ``os.path.lexists`` does precisely that -- it catches the error internally
    and returns False, so a PermissionError reads as success.
    """
    try:
        os.lstat(workdir)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _remove_workdir(workdir: Path, *, attempts: int = 8, delay: float = 0.2) -> None:
    """Remove the scratch dir, retrying while something still holds it.

    BF-788: normally called on a worker thread, but the shutdown fallbacks call
    it inline, where its bounded sleeps run on the calling thread. It occupies
    that thread for up to ~9s in the pathological case.

    ``os.lstat``, NOT ``os.path.lexists``: `lexists` catches OSError internally
    and returns False, so a PermissionError would read as "already gone" and
    this function would report success while the directory remained -- exactly
    the silent failure BF-788 exists to remove. Only FileNotFoundError means
    gone; every other OSError is reported.

    The delay backs off (0.2 -> 2.0s, ~9s total) because the process holding
    the directory is not always the child: a DETACHED grandchild inherits the
    workdir as its cwd and outlives it, and a flat 0.8s budget gave up while
    one was still running. The bound is a decision, not an inheritance -- a
    descendant can outlive any budget, so exhaustion warns rather than
    pretending.
    """
    wait = delay
    for remaining in range(attempts - 1, -1, -1):
        shutil.rmtree(workdir, ignore_errors=True)
        try:
            os.lstat(workdir)
        except FileNotFoundError:
            return  # genuinely gone
        except OSError as exc:
            # Cannot tell whether it survived. Saying nothing here would
            # restore the silent-leak property this fix exists to remove.
            logger.warning(
                "BF-788: could not determine whether sandbox workdir %s was "
                "removed (%s: %s); it may be left on disk.",
                workdir, type(exc).__name__, exc,
            )
            return
        if remaining:
            time.sleep(wait)
            wait = min(wait * 2, 2.0)

    logger.warning(
        "BF-788: sandbox workdir %s was still present after %d removal "
        "attempts and may remain on disk. Something may still hold it -- a "
        "detached descendant, or a child that could not be reaped.",
        workdir, attempts,
    )


#: BF-840: the supported name. ``_remove_workdir`` stays as an alias because
#: BF-788's consumer and its tests bind and monkeypatch that name; renaming
#: those would be churn on just-shipped code for no behavioural gain. New
#: consumers outside this module import ``remove_workdir``.
remove_workdir = _remove_workdir


async def remove_workdir_off_loop(workdir: Path) -> None:
    """Remove a scratch dir without freezing the event loop.

    BF-840: both `CodeRunnerAgent._reap` and `SkillForge._smoke_test` clean up
    in a ``finally`` inside ``async def``. Calling `remove_workdir` directly
    there blocks the loop for as long as it retries -- measured at a 0.250s
    heartbeat gap for a 0.25s sleep, so the real 0.2->2.0s backoff would stall
    every other task for up to ~9s.

    **The ``shield`` is what makes this survive cancellation.** Measured, with
    a second cancellation landing on the await; ``queued`` is the executor's
    queue depth at that moment:

        staged (run_in_executor + shield)  queued=1 calls=1
        bare to_thread (no shield)         queued=1 calls=0
        shield(to_thread(...))             queued=0 calls=1

    An unshielded await -- ``to_thread`` or otherwise -- lets the cancellation
    cancel the future while it is still QUEUED, and the cleanup never runs.
    (Cancellation cannot stop a removal that has already started on a worker.)
    The shielded ``to_thread`` row shows ``queued=0`` because that task had not
    submitted yet when the cancellation arrived, and it still cleaned up:
    shielding, not submission order, is the property that matters.
    ``run_in_executor`` is used rather than ``to_thread`` because it also
    submits before the first suspension point, so the work is queued even if
    the caller is never suspended; but that is a secondary property.

    Falls back to a synchronous removal when submission fails. In practice that
    means a running loop whose executor has already shut down, not the absence
    of a loop -- reaching this via ``await`` implies one. The fallback blocks
    the caller, potentially for the whole ~9s budget; blocking is strictly
    better than silently skipping cleanup, which is the defect being fixed.

    **The removal can run twice, and that is deliberate.**
    ``ThreadPoolExecutor.submit`` can ENQUEUE the job and then raise while
    starting a worker, so the fallback and the queued job may both remove the
    same directory. `remove_workdir` is idempotent -- measured over 100
    simultaneous two-thread removals with zero leftovers, warnings or
    exceptions -- so the cost is redundant work plus, when a directory is
    genuinely held, a duplicate or STALE give-up warning: one remover can give
    up and warn while the other subsequently succeeds.

    **Precondition: the directory must not be a reused path.** A queued
    duplicate can land after the fallback has returned, so if the path were
    recreated in between, the duplicate would delete the replacement --
    measured. Both callers allocate fresh ``uuid4``/``mkdtemp`` paths per run,
    which is what makes this safe; do not call this on a stable directory.

    An earlier revision claimed the removal once and had the loser wait on a
    completion Event. That was worse: it swallowed the winner's exception, its
    bounded wait could expire and return indistinguishably from success, and it
    documented a completion guarantee the code did not provide. A duplicated
    idempotent removal is a smaller problem than a false guarantee, so the
    machinery was removed rather than extended.
    """
    try:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, remove_workdir, workdir)
    except RuntimeError:
        remove_workdir(workdir)
        return
    # Shielded: a cancellation landing here must not cancel the removal.
    # An exception from the worker reaches a caller that is still awaiting.
    # If a cancellation wins the await instead, the caller sees CancelledError
    # and a later worker failure is reported by the loop's exception handler
    # rather than to this caller.
    await asyncio.shield(future)


@dataclass
class ExecutionRequest:
    """One unit of work to run under isolation. Either ``code`` (Python source,
    written to ``script.py`` in the scratch dir) OR ``argv`` (an explicit command
    line, e.g. a ``pip install`` invocation) must be provided."""

    code: str | None = None
    argv: list[str] | None = None
    workdir: Path | None = None              # scratch dir; created ephemeral if None
    timeout_seconds: float = 30.0
    max_output_bytes: int = 64 * 1024
    max_memory_mb: int = 512
    allow_network: bool = False              # AD-1233: deterrent at Tier 1 by decision, not oversight; see _build_env
    env: dict[str, str] | None = None        # extra env on top of a scrubbed base
    python_executable: str | None = None     # default: sys.executable
    # AD-1221: make the working directory importable, so a helper module the
    # ship generated there (e.g. `ship.py`) can be imported by the script.
    # Default False keeps every existing caller byte-identical.
    import_workdir: bool = False
    # AD-1247: set once the child process actually exists. `run()` only QUEUES
    # work on an executor -- `Popen` happens later, inside `_run_sync` -- so a
    # caller that flips its own flag before awaiting `run()` is recording an
    # intention, not an execution. Probes produced audit records for a missing
    # executable and for a run cancelled while still queued, neither of which
    # ever started a process. See `LaunchOutcome` for why this resolves both
    # answers rather than only signalling success.
    launch_outcome: LaunchOutcome | None = None
    # BF-788: opt in to removal of `workdir` when the awaiting caller is
    # cancelled. Usually the worker does it -- it is still running after the
    # child releases the directory -- but the loop side takes it when the
    # worker finished first, and the caller takes it when no worker ever ran.
    cleanup_on_cancel: "CancelCleanup | None" = None


@dataclass
class ExecutionResult:
    """The outcome of an isolated execution.

    ``run`` honest-degrades ordinary failures into one of these rather than
    raising; it is not proof against cancellation of the awaiting task.
    """

    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    duration_ms: float = 0.0
    tier: int = int(IsolationTier.SUBPROCESS)
    error: str = ""
    workdir: str = ""


@runtime_checkable
class IsolationBackend(Protocol):
    """Pluggable isolation backend. Tier 2/3 implement the same surface."""

    tier: IsolationTier

    def available(self) -> bool:
        """True if this backend can run on the current host (deps present)."""
        ...

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute ``request`` under isolation; honest-degrade, never raise."""
        ...


# Environment variables kept from the host for a minimal, predictable base env.
_ENV_PASSTHROUGH = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "TZ")
# Discard-port proxy: a SOFT network deterrent for well-behaved libraries
# (requests/urllib honor *_proxy). Hard network isolation is Tier 2.
_BLACKHOLE_PROXY = "http://127.0.0.1:9"


class SubprocessSandbox:
    """Tier-1 isolation backend: subprocess + ephemeral working folder.

    Mirrors ``ShellCommandAgent`` execution mechanics (``subprocess.Popen`` in a
    thread executor) so it works under any event-loop policy, including the
    Windows selector loop. Resource limits are applied via ``preexec_fn`` on
    POSIX; on Windows the bound is the timeout. ``run`` honest-degrades every
    ordinary failure into a failed ``ExecutionResult`` rather than raising --
    but it is not exception-proof: cancelling the awaiting task raises
    ``CancelledError`` out of the await, and the executor thread keeps going
    (see ``LaunchOutcome``).
    """

    tier: IsolationTier = IsolationTier.SUBPROCESS

    def __init__(self, *, scratch_root: Path | str = "data/execution") -> None:
        self._scratch_root = Path(scratch_root)

    def available(self) -> bool:
        return True  # always available — pure stdlib + the running interpreter

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        loop = asyncio.get_running_loop()
        # BF-788: resolve BEFORE the child starts, so the request, the child's
        # cwd and both cleanup sites name one absolute path. `_run_sync_inner`
        # resolves a local copy; if the process cwd moved in between, cleanup
        # would target a different directory than the child used.
        if request.workdir is not None:
            try:
                request.workdir = Path(request.workdir).resolve()
            except (OSError, ValueError) as exc:
                # This class promises to degrade ordinary failures into a
                # failed result. A malformed path (embedded NUL raises
                # ValueError) is one, and resolving here is what introduced
                # the chance of raising at all.
                logger.warning(
                    "BF-788: sandbox workdir %r could not be resolved (%s: %s); "
                    "refusing the run rather than executing against an "
                    "ambiguous path.", request.workdir, type(exc).__name__, exc,
                )
                # AD-1247: this is an exit path, so the launch question gets
                # its answer here too. No child was created and none will be.
                if request.launch_outcome is not None:
                    request.launch_outcome.resolved.set()
                return ExecutionResult(
                    success=False,
                    error=f"invalid workdir: {exc}",
                    tier=int(self.tier),
                )
        try:
            return await loop.run_in_executor(None, self._run_sync, request)
        except asyncio.CancelledError:
            cleanup = request.cleanup_on_cancel
            if cleanup is not None:
                cleanup.cancelled.set()
                # The worker publishes `finished` BEFORE reading `cancelled`.
                # If it is already visible, the worker has been past its check
                # and will not clean up -- so this side owns it. Handing it to
                # the executor keeps the sleep off the loop.
                if (
                    cleanup.finished.is_set()
                    and request.workdir is not None
                    and cleanup.claim()
                ):
                    try:
                        loop.run_in_executor(None, _remove_workdir, request.workdir)
                    except RuntimeError:
                        # The executor is already shutting down. Letting this
                        # escape would replace CancelledError with a
                        # RuntimeError -- a caller unwinding would see the
                        # wrong exception AND the directory would survive.
                        # Bounded, and only on a loop that is going away.
                        _remove_workdir(request.workdir)
            raise

    # ------------------------------------------------------------------

    def _run_sync(self, request: ExecutionRequest) -> ExecutionResult:
        cleanup = request.cleanup_on_cancel
        if cleanup is not None:
            # BF-788: FIRST statement. From here a child may come to exist, so
            # the caller must stop treating the directory as its own. A queued
            # job that was cancelled never reaches this line, which is exactly
            # the distinction the caller needs.
            cleanup.started.set()
        try:
            return self._run_sync_inner(request)
        finally:
            # AD-1247: the launch question ALWAYS gets an answer, on every exit
            # path including the ones that never reached Popen. A caller
            # unwinding under cancellation is waiting on this.
            if request.launch_outcome is not None:
                request.launch_outcome.resolved.set()
            # BF-788: normally reached after the child has exited, which is the
            # earliest moment a Windows handle can be released. An abnormal
            # `communicate()` now kills and reaps the child first; if that
            # reaping itself fails, this can still run beside a live process
            # (filed -- HEAD has the same hazard and does not even try).
            #
            # `finished` is published FIRST. The two ordered checks are what
            # close the race: whichever side observes the other's flag last
            # performs the removal, so neither can skip it believing the other
            # will. `claim()` then ensures only ONE of them acts when both
            # observe.
            cleanup = request.cleanup_on_cancel
            if cleanup is not None:
                cleanup.finished.set()
                if (
                    cleanup.cancelled.is_set()
                    and request.workdir is not None
                    and cleanup.claim()
                ):
                    _remove_workdir(request.workdir)
    def _run_sync_inner(self, request: ExecutionRequest) -> ExecutionResult:
        started = time.monotonic()
        created_workdir = request.workdir is None
        workdir = Path(request.workdir) if request.workdir else (
            self._scratch_root / uuid.uuid4().hex
        )
        # BF-715: absolutise BEFORE anything downstream uses it. The child runs
        # with ``cwd=workdir``, so a RELATIVE workdir makes the script path in
        # argv resolve a second time against the new cwd:
        #
        #   argv script : data/execution/scratch/exec-A/script.py
        #   child cwd   : data/execution/scratch/exec-A
        #   child opens : data/execution/scratch/exec-A/
        #                 data/execution/scratch/exec-A/script.py   -> ENOENT
        #
        # ``execution.scratch_dir`` defaults to the relative
        # ``data/execution/scratch``, so this fired on the default configuration
        # for every code_execution_tool run: exit code 2, "can't open file", and
        # an agent that correctly reported it could not produce its artifact.
        # Resolving here fixes the script path, the cwd and the ``workdir``
        # string returned to callers in one place, and makes the whole
        # invocation independent of the parent's current directory.
        workdir = workdir.resolve()
        try:
            workdir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return ExecutionResult(
                success=False, error=f"could not create scratch dir: {exc}",
            )

        try:
            argv = self._build_argv(request, workdir)
            if argv is None:
                return ExecutionResult(
                    success=False,
                    error="ExecutionRequest needs either code or argv",
                    workdir=str(workdir),
                )
            env = self._build_env(request)
            popen_kwargs = self._platform_kwargs(request)

            proc = subprocess.Popen(
                argv,
                cwd=str(workdir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **popen_kwargs,
            )
            # AD-1247: the child exists from here. `launched` is written FIRST
            # and `resolved` set immediately after, so a caller that waits on
            # `resolved` and then reads `launched` cannot see a torn value --
            # the Event is the memory barrier between this thread and the loop.
            #
            # Resolved HERE, not in the wrapper's `finally`: setting it only on
            # return would make it mean "the whole run finished", so a caller
            # unwinding while a 30-second child is still running would block for
            # its entire bounded wait despite the answer being known the moment
            # Popen returned.
            if request.launch_outcome is not None:
                request.launch_outcome.launched = True
                request.launch_outcome.resolved.set()
            try:
                out_b, err_b = proc.communicate(timeout=request.timeout_seconds)
                timed_out = False
            except subprocess.TimeoutExpired:
                self._kill(proc)
                out_b, err_b = proc.communicate()
                timed_out = True
            except BaseException:
                # BF-788: any other failure here (a pipe error, a cancellation
                # unwinding the thread) would otherwise return with the child
                # STILL RUNNING, and every caller treats return as "the child
                # is gone" -- cleanup then deletes files out from under it.
                # Measured on both HEAD and this branch: the script saw
                # FileNotFoundError. Reap it before returning. If the reap
                # itself fails the hazard remains, which is why that path warns
                # rather than pretending (filed).
                self._kill(proc)
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001 — already failing; best effort
                    logger.warning(
                        "BF-788: sandbox child %s did not exit after being "
                        "killed; its workdir may still be in use.", proc.pid,
                    )
                raise

            cap = request.max_output_bytes
            stdout = (out_b or b"")[:cap].decode("utf-8", errors="replace")
            stderr = (err_b or b"")[:cap].decode("utf-8", errors="replace")
            duration_ms = (time.monotonic() - started) * 1000.0
            return ExecutionResult(
                success=(not timed_out and proc.returncode == 0),
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode,
                timed_out=timed_out,
                duration_ms=duration_ms,
                tier=int(self.tier),
                error=("timed out" if timed_out else ""),
                workdir=str(workdir),
            )
        except Exception as exc:  # honest-degrade: never raise out of run
            logger.warning(
                "AD-993: SubprocessSandbox execution failed: %s: %s",
                type(exc).__name__, exc,
            )
            return ExecutionResult(
                success=False, error=repr(exc), workdir=str(workdir),
            )
        finally:
            if created_workdir:
                # BF-840: was a one-shot ``shutil.rmtree(ignore_errors=True)``.
                # ``ExecutionRequest.workdir`` defaults to None and this class
                # is exported, so this branch belongs to any caller that lets
                # the sandbox pick the directory -- measured surviving a single
                # transient removal failure. Every in-repo production caller
                # currently passes an explicit workdir, but "no caller in this
                # repo" is not the same as dead, and this is already on a
                # worker thread, so the retry costs the loop nothing.
                remove_workdir(workdir)

    # ------------------------------------------------------------------

    @staticmethod
    def _build_argv(request: ExecutionRequest, workdir: Path) -> list[str] | None:
        if request.argv:
            return list(request.argv)
        if request.code is not None:
            py = request.python_executable or sys.executable
            script = workdir / "script.py"
            script.write_text(request.code, encoding="utf-8")
            # -I = isolated mode (ignore env vars + user site); -B = no .pyc.
            if not request.import_workdir:
                return [py, "-I", "-B", str(script)]
            # AD-1221: `-I` implies `-P`, which deliberately does NOT prepend
            # the script's directory to sys.path — that is what stops a file in
            # the working directory from shadowing a stdlib module, and it is
            # not something to give up in exchange for a feature (Design
            # Principle 13b). So keep `-I` and add the one directory we chose,
            # via a launcher. `runpy` compiles script.py as its own file, so
            # the agent's tracebacks still report the agent's real line numbers
            # — which a prepended prelude inside script.py would have silently
            # shifted, turning every sandbox error message into a small lie.
            launcher = workdir / "_probos_launch.py"
            launcher.write_text(
                "import runpy, sys, os\n"
                "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
                "sys.argv = ['script.py']\n"
                "runpy.run_path(\n"
                "    os.path.join(os.path.dirname(os.path.abspath(__file__)),\n"
                "                 'script.py'),\n"
                "    run_name='__main__',\n"
                ")\n",
                encoding="utf-8",
            )
            return [py, "-I", "-B", str(launcher)]
        return None

    @staticmethod
    def _build_env(request: ExecutionRequest) -> dict[str, str]:
        env: dict[str, str] = {
            k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ
        }
        if not request.allow_network:
            # AD-1233 (#1186): a DECIDED posture, not an inherited default.
            #
            # These four variables are a deterrent, not a boundary. requests and
            # httpx honour them -- which covers every library an agent actually
            # reaches for -- and a raw socket ignores them entirely. The Captain
            # chose to keep it soft rather than add OS-level egress blocking,
            # because the governed way out already exists: AD-1221's fetch
            # broker performs the ordinary mesh fetch, with SSRF validation,
            # per-domain rate limiting and audit. Hardening this would push
            # agents toward smuggling bytes through their own context window
            # (the exact cost AD-1221 was built to remove) and would buy little,
            # since the threat model here is a confused agent rather than a
            # hostile one -- code reaching the sandbox has already passed
            # approval-gated install and the tier-3 gate.
            #
            # What it defends: an agent that casually calls requests.get()
            # inside run_python fails fast and is pushed to the broker.
            # What it costs: a raw socket is unimpeded, so this must never be
            # cited as an enforced boundary by a later AD. Design Principle 13
            # -- a capability ceiling must be a decision, and this one is.
            env["http_proxy"] = _BLACKHOLE_PROXY
            env["https_proxy"] = _BLACKHOLE_PROXY
            env["HTTP_PROXY"] = _BLACKHOLE_PROXY
            env["HTTPS_PROXY"] = _BLACKHOLE_PROXY
            env["no_proxy"] = ""
        if request.env:
            env.update(request.env)
        return env

    def _platform_kwargs(self, request: ExecutionRequest) -> dict:
        kwargs: dict = {}
        if sys.platform == "win32":
            # New process group so we can signal the whole tree on timeout.
            kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0,
            )
        else:
            kwargs["start_new_session"] = True  # own process group (killpg)
            if _resource is not None:
                kwargs["preexec_fn"] = self._make_limits(request)  # noqa: PLW1509
        return kwargs

    @staticmethod
    def _make_limits(request: ExecutionRequest):
        mem_bytes = max(64, int(request.max_memory_mb)) * 1024 * 1024
        cpu_seconds = max(1, int(request.timeout_seconds) + 1)
        fsize_bytes = 256 * 1024 * 1024  # 256 MB max single-file write

        def _apply() -> None:  # pragma: no cover - POSIX child process only
            try:
                _resource.setrlimit(_resource.RLIMIT_AS, (mem_bytes, mem_bytes))
                _resource.setrlimit(_resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
                _resource.setrlimit(_resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))
            except (ValueError, OSError):
                pass  # best-effort; the timeout is the backstop

        return _apply

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        try:
            if sys.platform != "win32" and proc.pid:
                os.killpg(os.getpgid(proc.pid), 9)
            else:
                proc.kill()
        except (ProcessLookupError, OSError):
            try:
                proc.kill()
            except OSError:
                pass
