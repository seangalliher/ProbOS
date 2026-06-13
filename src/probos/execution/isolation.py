"""AD-993: Tier-1 isolation substrate for governed ephemeral code execution.

This is the foundation for letting crew agents safely create + run Python scripts
and install libraries to perform tasks (the GitHub Copilot / Claude Code pattern),
done the ProbOS way: governed by consensus + trust + the episodic log, with a
**tiered isolation model** so the strength of the boundary can grow without
changing callers.

Tiered isolation (the ``IsolationBackend`` abstraction):

* **Tier 1 — ``SubprocessSandbox`` (this module).** Subprocess isolation +
  ephemeral working folder + resource limits (POSIX) + timeout + output caps +
  network-off-by-default. This is the Copilot "restrict the harness to a working
  folder" model. **Be honest about what it is:** PROCESS ISOLATION + RESOURCE
  BOUNDS + CONFINEMENT-BY-CONVENTION, *governed by consensus* — NOT a
  kernel-enforced containment boundary. A determined script can still read host
  files by absolute path, and network cannot be hard-blocked cross-platform
  without OS namespaces. The real boundary at Tier 1 is: (a) the consensus gate
  (every execution is quorum-authorized), (b) resource + time bounds (it can't
  exhaust the host), (c) the ephemeral scratch dir, and (d) it runs out-of-process
  so it cannot corrupt the runtime. Hard containment is Tier 2.
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
    allow_network: bool = False              # soft at Tier 1 (proxy hint); hard at Tier 2
    env: dict[str, str] | None = None        # extra env on top of a scrubbed base
    python_executable: str | None = None     # default: sys.executable


@dataclass
class ExecutionResult:
    """The outcome of an isolated execution. Never raises out of ``run``."""

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
    POSIX; on Windows the bound is the timeout. Never raises out of ``run``.
    """

    tier: IsolationTier = IsolationTier.SUBPROCESS

    def __init__(self, *, scratch_root: Path | str = "data/execution") -> None:
        self._scratch_root = Path(scratch_root)

    def available(self) -> bool:
        return True  # always available — pure stdlib + the running interpreter

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._run_sync, request)

    # ------------------------------------------------------------------

    def _run_sync(self, request: ExecutionRequest) -> ExecutionResult:
        started = time.monotonic()
        created_workdir = request.workdir is None
        workdir = Path(request.workdir) if request.workdir else (
            self._scratch_root / uuid.uuid4().hex
        )
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
            try:
                out_b, err_b = proc.communicate(timeout=request.timeout_seconds)
                timed_out = False
            except subprocess.TimeoutExpired:
                self._kill(proc)
                out_b, err_b = proc.communicate()
                timed_out = True

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
                shutil.rmtree(workdir, ignore_errors=True)

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
            return [py, "-I", "-B", str(script)]
        return None

    @staticmethod
    def _build_env(request: ExecutionRequest) -> dict[str, str]:
        env: dict[str, str] = {
            k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ
        }
        if not request.allow_network:
            # Soft deterrent only (well-behaved libs honor proxy env). Hard
            # network isolation is Tier 2.
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
