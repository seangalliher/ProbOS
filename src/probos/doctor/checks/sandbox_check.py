"""AD-801: sandbox backend availability (forward-compatible with AD-798)."""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


def _docker_info_sync(timeout_s: float) -> tuple[bool, str]:
    """Synchronous `docker info` probe.

    Uses `subprocess.run` (not `asyncio.create_subprocess_exec`) so the
    check works when called from a FastAPI handler under
    `WindowsSelectorEventLoop` — see `src/probos/agents/shell_command.py:154`
    for the canonical `_run_sync` pattern this mirrors.
    """
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (FileNotFoundError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    except subprocess.TimeoutExpired:
        return False, "docker info timed out"
    if proc.returncode == 0:
        return True, (proc.stdout.strip() or "ok")
    return False, (proc.stderr.strip() or "non-zero exit")


async def _docker_available(timeout_s: float = 3.0) -> tuple[bool, str]:
    """Async wrapper — dispatches the blocking probe to the default executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _docker_info_sync, timeout_s)


@dataclass(frozen=True)
class _SandboxCheck:
    name: str = "sandbox"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        # `sandbox_backend` doesn't ship in config until AD-798 lands; we
        # read it defensively with `getattr` so this check is meaningful
        # today (informational) and naturally becomes load-bearing later.
        sec = getattr(ctx.config, "security", None) if ctx.config else None
        backend = getattr(sec, "sandbox_backend", "inprocess") if sec else "inprocess"

        if backend == "inprocess":
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Sandbox backend: in-process (AD-456b)",
            )

        if backend == "container":
            ok, detail = await _docker_available()
            if ok:
                return CheckResult(
                    outcome=CheckOutcome.OK,
                    message=f"Sandbox backend: container — docker {detail}",
                )
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message="Sandbox backend: container — docker unavailable",
                remediation=f"Install or start Docker, or set config.security.sandbox_backend='inprocess'. ({detail})",
            )

        return CheckResult(
            outcome=CheckOutcome.WARN,
            message=f"Sandbox backend: unknown value '{backend}'",
            remediation="Set config.security.sandbox_backend to 'inprocess' or 'container'.",
        )


register_check(_SandboxCheck())
