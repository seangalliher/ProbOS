"""AD-798 + AD-799 + AD-800: container sandbox + per-thread workspace + egress policy.

A *command-shaped* sandbox surface complementary to the existing
``security.runtime_sandbox.RuntimeSandbox`` (which bounds in-process
coroutines). Where RuntimeSandbox guards CPU/memory of code we wrote,
``ContainerSandbox`` guards externally-executed commands — agent skills
that shell out, builder test runs in a project workspace, third-party
tool invocations.

Three backends:

* ``DockerContainerSandbox`` — real isolation. Spawns ``docker run``
  with ``--rm``, optional ``-v workspace:/workspace:rw`` (AD-799), and
  ``--network none`` | ``--network bridge`` | custom (AD-800). Returns
  a ``CommandOutcome`` carrying stdout/stderr/exit_code/wall_ms.
* ``InProcessContainerSandbox`` — fallback when docker is not present
  or not configured. Uses ``subprocess.run`` via
  ``loop.run_in_executor`` (per the WindowsSelectorEventLoop +
  shell_command.py:_run_sync convention). NO isolation — honest about
  it via ``isolated=False`` flag on the outcome. The caller decides if
  that's acceptable.

Both implement the ``ContainerSandbox`` Protocol. Factory
``get_container_sandbox(config)`` returns docker when configured + the
``docker`` binary is on PATH; otherwise honest-degrades to in-process
with a single startup warning.

EgressPolicy (AD-800):
    * ``"none"`` — ``--network none`` in docker; rejected in in-process
      backend (in-process cannot enforce egress; we refuse to silently
      give the caller something weaker than they asked for).
    * ``"bridge"`` — default docker network; in-process backend allows
      the host network with isolated=False.
    * ``"allowlist"`` — docker backend uses a custom user-defined
      network with iptables egress rules (operator pre-creates the
      network; we just attach to it). v1 substrate accepts the value
      but defers the network-create automation to AD-800a.

Per-thread workspace (AD-799):
    * Pairs with the AD-791 ``chat_threads.workspace_root`` column.
    * When set on a ``ContainerExec`` request, docker mounts that path
      as ``/workspace`` (read-write). In-process backend chdir's into
      it.
    * Path must resolve under the operator's configured workspace_root
      (no traversal escapes) — enforced at the
      ``resolve_thread_workspace`` helper.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

EgressPolicy = Literal["none", "bridge", "allowlist"]


@dataclass(frozen=True)
class SandboxLimits:
    wall_timeout_seconds: float = 60.0
    memory_mb: int = 512
    cpu_quota: float = 1.0


@dataclass(frozen=True)
class ContainerExec:
    """A single command execution request."""

    command: list[str]
    workspace_root: Path | None = None
    egress_policy: EgressPolicy = "bridge"
    image: str = "probos/cowork-base:latest"
    env: dict[str, str] = field(default_factory=dict)
    limits: SandboxLimits = field(default_factory=SandboxLimits)


@dataclass(frozen=True)
class CommandOutcome:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    wall_ms: float
    isolated: bool
    error: str | None = None


@runtime_checkable
class ContainerSandbox(Protocol):
    """Command-shaped sandbox. Async surface; implementations run
    blocking subprocess work in a thread executor.
    """

    async def run(self, request: ContainerExec) -> CommandOutcome:
        ...

    @property
    def name(self) -> str:
        ...


# ---------------- Workspace resolution (AD-799) ----------------


class WorkspaceEscapeError(ValueError):
    """Requested workspace path escapes the operator's configured root."""


def resolve_thread_workspace(
    *, configured_root: Path, thread_workspace: str | None
) -> Path | None:
    """Resolve ``thread_workspace`` under ``configured_root``.

    Returns ``None`` when ``thread_workspace`` is empty / None. Raises
    :class:`WorkspaceEscapeError` if the resolved path escapes
    ``configured_root`` (e.g. ``../../etc``). The directory is created
    if it doesn't exist (workspaces are persistent per-thread).
    """
    if not thread_workspace:
        return None
    root = Path(configured_root).resolve()
    candidate = (root / thread_workspace).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WorkspaceEscapeError(
            f"workspace '{thread_workspace}' escapes configured root {root}"
        ) from exc
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


# ---------------- In-process backend ----------------


class InProcessContainerSandbox:
    """No-isolation fallback. Honest about it (``isolated=False``).

    Rejects ``egress_policy="none"`` because we cannot enforce egress
    from in-process. Honesty over silent-weaken: caller asked for no
    egress; we don't have a way to provide it; we refuse rather than
    pretend.
    """

    name = "inprocess"

    async def run(self, request: ContainerExec) -> CommandOutcome:
        if request.egress_policy == "none":
            return CommandOutcome(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                wall_ms=0.0,
                isolated=False,
                error="InProcessContainerSandbox cannot enforce egress_policy='none'; install docker",
            )
        loop = asyncio.get_running_loop()
        cwd = str(request.workspace_root) if request.workspace_root else None
        env = {**os.environ, **request.env}
        t0 = time.monotonic()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(  # noqa: S603 - args list, no shell
                    request.command,
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                    env=env,
                    timeout=request.limits.wall_timeout_seconds,
                ),
            )
        except subprocess.TimeoutExpired:
            return CommandOutcome(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                wall_ms=(time.monotonic() - t0) * 1000,
                isolated=False,
                error=f"wall timeout after {request.limits.wall_timeout_seconds}s",
            )
        except FileNotFoundError as exc:
            return CommandOutcome(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                wall_ms=(time.monotonic() - t0) * 1000,
                isolated=False,
                error=f"command not found: {exc}",
            )
        return CommandOutcome(
            success=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            wall_ms=(time.monotonic() - t0) * 1000,
            isolated=False,
        )


# ---------------- Docker backend ----------------


class DockerContainerSandbox:
    """``docker run``-based isolation backend."""

    name = "docker"

    def __init__(self, *, docker_binary: str = "docker") -> None:
        self._docker = docker_binary

    def _build_args(self, request: ContainerExec) -> list[str]:
        args = [self._docker, "run", "--rm"]
        # AD-800: egress policy → network flag.
        if request.egress_policy == "none":
            args += ["--network", "none"]
        elif request.egress_policy == "bridge":
            args += ["--network", "bridge"]
        elif request.egress_policy == "allowlist":
            # Operator pre-creates a network with iptables egress rules.
            # AD-800a will automate this; v1 substrate just attaches.
            args += ["--network", "probos-egress-allowlist"]
        # AD-799: workspace mount.
        if request.workspace_root is not None:
            args += ["-v", f"{request.workspace_root}:/workspace:rw", "-w", "/workspace"]
        # Resource limits.
        args += [
            "--memory", f"{request.limits.memory_mb}m",
            "--cpus", f"{request.limits.cpu_quota}",
        ]
        for k, v in request.env.items():
            args += ["-e", f"{k}={v}"]
        args.append(request.image)
        args += list(request.command)
        return args

    async def run(self, request: ContainerExec) -> CommandOutcome:
        args = self._build_args(request)
        loop = asyncio.get_running_loop()
        t0 = time.monotonic()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(  # noqa: S603
                    args,
                    capture_output=True,
                    text=True,
                    timeout=request.limits.wall_timeout_seconds + 10,
                ),
            )
        except subprocess.TimeoutExpired:
            return CommandOutcome(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                wall_ms=(time.monotonic() - t0) * 1000,
                isolated=True,
                error=f"docker wall timeout after {request.limits.wall_timeout_seconds}s",
            )
        except FileNotFoundError:
            return CommandOutcome(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                wall_ms=(time.monotonic() - t0) * 1000,
                isolated=False,
                error="docker binary not found on PATH",
            )
        return CommandOutcome(
            success=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            wall_ms=(time.monotonic() - t0) * 1000,
            isolated=True,
        )


# ---------------- Factory ----------------


def get_container_sandbox(*, prefer_docker: bool = True) -> ContainerSandbox:
    """Return the best available ContainerSandbox.

    When ``prefer_docker`` is True (default) and ``docker`` is on PATH,
    returns :class:`DockerContainerSandbox`. Otherwise returns the
    in-process fallback with a single startup warning so the operator
    knows isolation is degraded.
    """
    if prefer_docker and shutil.which("docker"):
        logger.info("ContainerSandbox: using docker backend (AD-798)")
        return DockerContainerSandbox()
    logger.warning(
        "ContainerSandbox: docker not available; using in-process fallback "
        "(no isolation, AD-798 honest-degrade). Install Docker for sandboxing."
    )
    return InProcessContainerSandbox()
