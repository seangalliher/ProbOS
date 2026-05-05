"""AD-456b: RuntimeSandbox — bounded-execution surface for runtime tasks.

v1 ships an in-process, ``tracemalloc``-backed sandbox with three guarantees:

1. **Wall-clock timeout** via ``asyncio.wait_for``.
2. **Best-effort peak memory tracking** via ``tracemalloc.get_traced_memory``.
3. **Capability consultation** via a ``contextvars.ContextVar`` set during the
   bounded coroutine; sandboxed code voluntarily calls ``check_capability`` /
   ``require_capability``.

True OS-level isolation (subprocess + Windows JobObject / Linux cgroups /
seccomp) is deferred to AD-456b-1 — the public contract here
(``RuntimeSandbox.execute(coro_factory, *, limits, capabilities)`` returning
``SandboxOutcome``) is forward-compatible: AD-456b-1 will swap the body for an
OS-isolated body without changing the signature.

This module is **not** ``cognitive/sandbox.py:SandboxRunner`` — that is the
self-mod correctness harness for loading generated agent source code. This is a
runtime-side bounded-execution surface intended for diagnostic actions
(AD-660b → AD-456b-3), externally-supplied callbacks, and other code paths
where the caller wants enforced limits + auditable denial events.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


# Context-local capability set. Set by RuntimeSandbox.execute() and reset on
# exit. Sandboxed code reads via check_capability / require_capability.
_active_sandbox_capabilities: contextvars.ContextVar[frozenset[str] | None] = (
    contextvars.ContextVar("probos_ad456b_sandbox_capabilities", default=None)
)


class CapabilityDenied(Exception):
    """Raised by ``require_capability`` when the active sandbox context does
    not include the requested capability. Caught by ``RuntimeSandbox.execute``
    and surfaced as ``SandboxOutcome.capability_denied``.
    """


@dataclass(frozen=True)
class SandboxLimits:
    """Limits enforced by RuntimeSandbox during a single ``execute`` call."""

    wall_timeout_seconds: float = 30.0
    memory_peak_mb: float = 256.0


@dataclass(frozen=True)
class SandboxOutcome:
    """Result of a single ``RuntimeSandbox.execute`` call."""

    success: bool
    result: Any = None
    error: str = ""
    wall_ms: float = 0.0
    peak_memory_kb: int = 0
    limit_exceeded: str = ""        # "wall" / "memory" / "" if neither
    capability_denied: str = ""     # capability name; empty if not denied


def check_capability(name: str) -> bool:
    """Return True iff the currently-active sandbox context contains
    ``name``. Returns True when no sandbox is active (consultation is
    no-op outside a sandbox).
    """
    active = _active_sandbox_capabilities.get()
    if active is None:
        return True
    return name in active


def require_capability(name: str, *, emit_event: Callable[..., None] | None = None) -> None:
    """Raise ``CapabilityDenied`` iff the currently-active sandbox context
    lacks ``name``. No-op outside a sandbox. Emits ``SANDBOX_CAPABILITY_DENIED``
    via ``emit_event`` when provided.
    """
    if check_capability(name):
        return
    if emit_event is not None:
        try:
            emit_event(
                EventType.SANDBOX_CAPABILITY_DENIED,
                {"capability": name},
            )
        except Exception:
            logger.warning(
                "AD-456b: SANDBOX_CAPABILITY_DENIED emit failed (capability=%s)",
                name,
                exc_info=True,
            )
    raise CapabilityDenied(name)


@dataclass
class RuntimeSandbox:
    """Bounded-execution surface for runtime tasks.

    Public API:
        ``await execute(coro_factory, *, limits=None, capabilities=frozenset())``

    ``coro_factory`` is a zero-arg callable returning a coroutine (not a
    coroutine itself — avoids "coroutine was never awaited" warnings if
    construction is short-circuited by a check).
    """

    default_limits: SandboxLimits = field(default_factory=SandboxLimits)
    emit_event: Any | None = None

    async def execute(
        self,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        limits: SandboxLimits | None = None,
        capabilities: frozenset[str] = frozenset(),
    ) -> SandboxOutcome:
        effective = limits or self.default_limits
        memory_cap_bytes = int(effective.memory_peak_mb * 1024 * 1024)

        # Set capability context. Token captured for guaranteed reset.
        token = _active_sandbox_capabilities.set(capabilities)

        # tracemalloc may already be running globally — track whether we
        # started it here so we don't stop someone else's tracking.
        tracemalloc_started_here = False
        if not tracemalloc.is_tracing():
            tracemalloc.start()
            tracemalloc_started_here = True

        # Reset peak counter for this execution so we measure delta only.
        # Tier-1 swallow: tracemalloc.reset_peak (Python 3.9+) is safe to call
        # when tracing is active; the guard handles the unlikely race where
        # another caller stops tracing between is_tracing() and reset_peak().
        try:
            tracemalloc.reset_peak()
        except Exception:
            pass

        t_start = time.monotonic()
        try:
            try:
                result = await asyncio.wait_for(
                    coro_factory(),
                    timeout=effective.wall_timeout_seconds,
                )
            except asyncio.TimeoutError:
                wall_ms = (time.monotonic() - t_start) * 1000
                peak_kb = self._peak_kb()
                self._emit_limit_exceeded(
                    "wall", wall_ms=wall_ms, peak_kb=peak_kb,
                    timeout=effective.wall_timeout_seconds,
                )
                return SandboxOutcome(
                    success=False,
                    error=f"wall timeout after {effective.wall_timeout_seconds}s",
                    wall_ms=wall_ms,
                    peak_memory_kb=peak_kb,
                    limit_exceeded="wall",
                )
            except CapabilityDenied as e:
                return SandboxOutcome(
                    success=False,
                    error=f"capability denied: {e}",
                    wall_ms=(time.monotonic() - t_start) * 1000,
                    peak_memory_kb=self._peak_kb(),
                    capability_denied=str(e),
                )
            except Exception as e:
                return SandboxOutcome(
                    success=False,
                    error=f"{type(e).__name__}: {e}",
                    wall_ms=(time.monotonic() - t_start) * 1000,
                    peak_memory_kb=self._peak_kb(),
                )

            wall_ms = (time.monotonic() - t_start) * 1000
            peak_kb = self._peak_kb()
            peak_bytes = peak_kb * 1024
            if peak_bytes > memory_cap_bytes:
                self._emit_limit_exceeded(
                    "memory", wall_ms=wall_ms, peak_kb=peak_kb,
                    cap_mb=effective.memory_peak_mb,
                )
                return SandboxOutcome(
                    success=False,
                    error=(
                        f"peak memory {peak_kb} KB exceeded "
                        f"{effective.memory_peak_mb} MB cap"
                    ),
                    result=result,
                    wall_ms=wall_ms,
                    peak_memory_kb=peak_kb,
                    limit_exceeded="memory",
                )

            return SandboxOutcome(
                success=True,
                result=result,
                wall_ms=wall_ms,
                peak_memory_kb=peak_kb,
            )
        finally:
            _active_sandbox_capabilities.reset(token)
            if tracemalloc_started_here:
                try:
                    tracemalloc.stop()
                except Exception:
                    pass

    def _peak_kb(self) -> int:
        try:
            _, peak = tracemalloc.get_traced_memory()
            return peak // 1024
        except Exception:
            return 0

    def _emit_limit_exceeded(self, kind: str, **fields: Any) -> None:
        if not self.emit_event:
            return
        try:
            payload = {"kind": kind}
            payload.update(fields)
            self.emit_event(EventType.SANDBOX_LIMIT_EXCEEDED, payload)
        except Exception:
            logger.warning(
                "AD-456b: SANDBOX_LIMIT_EXCEEDED emit failed (kind=%s)", kind,
                exc_info=True,
            )
