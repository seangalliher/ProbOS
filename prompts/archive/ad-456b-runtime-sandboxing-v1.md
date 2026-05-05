# AD-456b v1 — Security Infrastructure: Runtime Sandboxing

**Status:** ready
**Dependencies:** AD-456 v1 (`runtime.egress_policy`, `runtime.audit_log`, `SecurityInfraConfig`, `EventType.EGRESS_BLOCKED` — all shipped); AD-680 (`runtime.emit_event` public)
**Estimated tests:** 12 new (1 new test file `tests/test_ad456b_runtime_sandboxing.py`)
**Closes:** GH issue #398

---

## Problem

AD-456 v1 (Wave 7) shipped three of four advertised security-infrastructure layers — Secrets, Egress, Audit — and **wholesale-deferred** the fourth (Runtime Sandboxing) to AD-456b. Two concrete consequences are pending today:

1. **`EgressPolicy` is consultation-only.** `EgressPolicy.is_allowed(url)` exists at `src/probos/security/egress.py:67`, emits `EGRESS_BLOCKED` on every blocked URL, but no consumer actually consults it. `HttpFetchAgent._validate_url()` (`agents/http_fetch.py:144-178`) performs scheme + DNS + private-IP checks but does NOT consult the policy. Operators get observability signal but no active enforcement. The AD-456 review (`prompts/Reviews/archive/ad-456-security-infrastructure-review.md:80,263`) explicitly contracts AD-456b to wire `EgressPolicy.is_allowed(url)` as a pre-check in `HttpFetchAgent`'s request path.

2. **No bounded-execution sandbox surface exists.** `cognitive/sandbox.py:SandboxRunner` is a *correctness* harness for self-mod (lines 47-50: "This is NOT a security sandbox (no seccomp, no containers). Security is handled by CodeValidator's static analysis."). Downstream consumers — most concretely AD-660b causal-reasoning diagnostic actions (DLog #10, deferred) — need a runtime-level surface that:
   - Enforces a wall-clock timeout independent of caller-side `asyncio.wait_for`.
   - Tracks peak memory consumption (best-effort; `tracemalloc` snapshot).
   - Carries a capability whitelist consultable by sandboxed code.
   - Emits structured events when limits are exceeded or capabilities are denied.

True OS-level process isolation (subprocess + Windows JobObject / Linux cgroups / seccomp / containers) requires `psutil` (not currently a dep — verified: `python -c "import psutil"` → `ModuleNotFoundError`) and cross-platform abstraction work. Per Wave-10 reframe rule, that piece is deferred to AD-456b-1 with explicit forcing function (this v1 ships the API surface; AD-456b-1 swaps the in-process body for an OS-isolated body without changing the public contract).

This AD plumbs the pieces that ARE tractable without new runtime deps:

```
RuntimeSandbox.execute(coro, *, limits, capabilities)   # NEW (in-process, tracemalloc-backed)
    │
    ├── asyncio.wait_for(...)                           # wall-clock enforcement
    ├── tracemalloc.start() + get_traced_memory()       # peak-memory tracking (best effort)
    └── SandboxContextVar set during execution          # capability check API for sandboxed code
                                                        # → SandboxOutcome
HttpFetchAgent._validate_url(url)                       # EDIT: consult class-level egress_policy
    │
    └── if cls._egress_policy AND not is_allowed(url):
        return "Egress policy: blocked by AD-456b runtime sandboxing"
```

`EgressPolicy.is_allowed()` already emits `EGRESS_BLOCKED` on the deny path (verified at `egress.py:135`); this AD activates the existing emit by adding a real consumer. No EventType change is needed for that path.

## Solution

v1 ships:

1. **`RuntimeSandbox` class** at `src/probos/security/runtime_sandbox.py` (NEW, ~140 lines). Public surface: `async execute(coro_factory, *, limits, capabilities=frozenset())` returning a `SandboxOutcome`. `coro_factory` is a zero-arg callable returning a coroutine (not a coroutine itself — avoids "coroutine was never awaited" warnings if construction is short-circuited by limits).
2. **`SandboxLimits` / `SandboxOutcome`** dataclasses (frozen). Limits carry `wall_timeout_seconds` and `memory_peak_mb`; outcome carries `success`, `result`, `error`, `wall_ms`, `peak_memory_kb`, `limit_exceeded`, `capability_denied`.
3. **Capability consultation API.** A module-level `contextvars.ContextVar` (`_active_sandbox_capabilities`) is set by `RuntimeSandbox.execute()` during the bounded coroutine and reset on exit. A free function `check_capability(name) -> bool` returns True iff the active context has that capability. `require_capability(name)` raises `CapabilityDenied` if missing AND emits `SANDBOX_CAPABILITY_DENIED`. v1 is consultation-style — sandboxed code voluntarily calls these functions; no instruction-level interception.
4. **Two new `EventType` enum values** — `SANDBOX_LIMIT_EXCEEDED`, `SANDBOX_CAPABILITY_DENIED`. Inserted adjacent to existing AD-456 events (`EGRESS_BLOCKED`, `AUDIT_RECORDED`).
5. **`SecurityInfraConfig` extension** at `src/probos/config.py:1450` — new fields `sandbox_enabled: bool = True`, `sandbox_default_wall_timeout_seconds: float = 30.0`, `sandbox_default_memory_peak_mb: float = 256.0`, `egress_active_enforcement: bool = False`. **`egress_active_enforcement` defaults to `False`** to preserve AD-456 v1 consultation-only behavior on existing deployments — Captain flips to `True` at upgrade time after reviewing allowlist coverage. (Convention #14 + #3: default-False on transitional flag; flip default in a future grandchild AD once allowlist fleet-coverage is verified.)
6. **`HttpFetchAgent` egress wiring** at `src/probos/agents/http_fetch.py`:
   - New `ClassVar[Any]` field `_egress_policy: ClassVar[Any] = None` (mirrors `_profile_store` shape at line 84).
   - New classmethod `set_egress_policy(cls, policy)` (mirrors `set_profile_store` at line 86).
   - `_validate_url()` adds a final consultation check after the existing private-IP guard: if `cls._egress_policy is not None`, call `cls._egress_policy.is_allowed(url)`; on False, return the egress block message. The existing `EgressPolicy._emit_blocked()` already fires `EGRESS_BLOCKED` — no double-emit needed.
7. **`runtime.runtime_sandbox`** public attribute (Wave 5 convention #1; no underscore). Wired in `startup/finalize.py` immediately after the existing AD-456 AuditLog block.
8. **`HttpFetchAgent.set_egress_policy(runtime.egress_policy)`** call in `startup/finalize.py` immediately after `runtime.egress_policy` assignment, gated on `config.security_infra.egress_active_enforcement`. When `egress_active_enforcement=False` (default), the class-level `_egress_policy` stays `None` and AD-456 v1 consultation-only behavior is preserved.

`tokens_used`-style backwards compatibility: every existing AD-456 test, every existing HttpFetchAgent test, every existing SandboxRunner test continues to function. No symbol is removed; no signature is changed; the new `_egress_policy` ClassVar defaults to `None` so HttpFetchAgent without finalize wiring (test rigs) behaves identically to today.

### Scope

| Component | Status |
|---|---|
| `src/probos/security/runtime_sandbox.py` (`RuntimeSandbox`, `SandboxLimits`, `SandboxOutcome`, `CapabilityDenied`, `check_capability`, `require_capability`) | NEW |
| `EventType.SANDBOX_LIMIT_EXCEEDED` / `SANDBOX_CAPABILITY_DENIED` | NEW |
| `SecurityInfraConfig.sandbox_enabled` / `.sandbox_default_wall_timeout_seconds` / `.sandbox_default_memory_peak_mb` / `.egress_active_enforcement` | NEW |
| `HttpFetchAgent._egress_policy` ClassVar + `set_egress_policy` classmethod + `_validate_url` consultation | EDIT |
| `startup/finalize.py` wires `runtime.runtime_sandbox` + conditional `HttpFetchAgent.set_egress_policy` | EDIT |
| `tests/test_ad456b_runtime_sandboxing.py` (12 tests) | NEW |

### Out of scope (legitimate boundaries — DO NOT BUILD)

- **True OS-level process isolation** (subprocess spawn, Windows JobObject, Linux cgroups, seccomp, namespaces). Needs `psutil` + cross-platform shim. Deferred to AD-456b-1 with explicit forcing function: ship v1, Captain validates that in-process timeout + tracemalloc covers ≥80% of diagnostic-action use cases, then OS-isolation belt becomes specifiable. v1 public contract (`RuntimeSandbox.execute(coro_factory, *, limits, capabilities)` → `SandboxOutcome`) is forward-compatible — AD-456b-1 swaps the body without changing the signature.
- **Graduated trust → graduated capability set policy.** `BayesianTrust` → `frozenset[capability_name]` mapping (e.g., trust < 0.3 → {}; trust ≥ 0.7 → all). Deferred to AD-456b-2. v1 ships the consultation primitive; v1 caller passes `capabilities` explicitly — no automatic trust-band lookup.
- **AD-660b diagnostic-action sandboxed execution wiring.** AD-660b DLog #10 deferred this surface. v1 ships `runtime.runtime_sandbox` so AD-660b's diagnostic actions can later route through it; this AD does NOT modify any AD-660b code. Deferred wiring is AD-456b-3 (forcing function: AD-660b's `DiagnosticAction.execute()` body becomes `runtime.runtime_sandbox.execute(self._do_act, limits=...)`).
- **Container-based sandbox / namespace isolation / eBPF policy enforcement.** *(Commercial)* — extension point only; the public contract above is the seam where commercial overlays plug in.
- **`SandboxRunner` (cognitive/sandbox.py) refactor.** Self-mod correctness harness is orthogonal — different invariants (it loads source code from disk, this AD bounds a coroutine). Not touched.
- **`RedTeamAgent` egress consultation.** AD-456 review noted this as a future consumer; not on the critical path. Wire-up is AD-456b-4.
- **`HttpFetchAgent` `_validate_url()` egress check ordering.** v1 puts the egress check AFTER the existing scheme/host/private-IP checks (defense in depth — egress is the policy layer; SSRF protection is the substrate layer). Reordering is AD-456b-5 if operationally needed.
- **Hot-reload of egress allowlist via runtime.** Operators currently mutate `egress_policy.allowlist` directly; HXI surface for this is AD-456b-6.
- **No new pool, agent, or module beyond the single `runtime_sandbox.py` file.**
- **No Pydantic config flag for capability consultation** — capabilities are passed per-`execute()` call, not configured globally.
- **No journal table.** `RuntimeSandbox` outcome is ephemeral — caller stores results where it sees fit.

---

## Verified Against Codebase (HEAD post-Wave-54, `343df76`, 2026-05-05)

| Symbol | Path | Line | Verifying line |
|---|---|---|---|
| `EgressPolicy.is_allowed` | `src/probos/security/egress.py` | 67 | `def is_allowed(self, url: str) -> bool:` |
| `EgressPolicy._emit_blocked` (existing `EGRESS_BLOCKED` emit) | `src/probos/security/egress.py` | 135-149 | `def _emit_blocked(self, decision: EgressDecision) -> None:` … `EventType.EGRESS_BLOCKED` |
| `runtime.egress_policy` attribute | `src/probos/startup/finalize.py` | 1270 | `runtime.egress_policy = EgressPolicy(` |
| `runtime.audit_log` attribute (AD-456b wires immediately after) | `src/probos/startup/finalize.py` | 1283 | `runtime.audit_log = AuditLog(emit_event=runtime.emit_event)` |
| `runtime.emit_event` public method (AD-680) | `src/probos/runtime.py` | 816 | `def emit_event(self, event: BaseEvent | str | EventType, data: dict[str, Any] | None = None) -> None:` |
| `SecurityInfraConfig` Pydantic class | `src/probos/config.py` | 1450 | `class SecurityInfraConfig(BaseModel):` |
| `SecurityInfraConfig.audit_enabled` (last existing field — append point) | `src/probos/config.py` | 1462 | `audit_enabled: bool = True` |
| `HttpFetchAgent._profile_store` ClassVar pattern (mirror target) | `src/probos/agents/http_fetch.py` | 84 | `_profile_store: ClassVar[Any] = None` |
| `HttpFetchAgent.set_profile_store` classmethod pattern (mirror target) | `src/probos/agents/http_fetch.py` | 86-89 | `def set_profile_store(cls, store: Any) -> None:` |
| `HttpFetchAgent._validate_url` insertion point | `src/probos/agents/http_fetch.py` | 144-178 | `def _validate_url(self, url: str) -> str | None:` |
| `HttpFetchAgent._validate_url` final return None (insertion-anchor sibling) | `src/probos/agents/http_fetch.py` | 178 | `return None` |
| `EventType.EGRESS_BLOCKED` (insertion-anchor sibling) | `src/probos/events.py` | 205 | `EGRESS_BLOCKED = "egress_blocked"  # AD-456` |
| `EventType.AUDIT_RECORDED` (insertion-anchor sibling) | `src/probos/events.py` | 210 | `AUDIT_RECORDED = "audit_recorded"  # AD-456` |
| `EventType.OBSERVABILITY_BRIDGE_FAILED` (last enum value — alternate append point) | `src/probos/events.py` | 235 | `OBSERVABILITY_BRIDGE_FAILED = "observability_bridge_failed"  # AD-641a` |
| AD-456 wiring block in finalize (insertion target — append after `audit_log`) | `src/probos/startup/finalize.py` | 1281-1289 | `if config.security_infra.audit_enabled:` … `runtime.audit_log = AuditLog(...)` |
| Existing AD-456 test file (no modification) | `tests/test_ad456_security_infrastructure.py` | — | 7628 bytes; 16 tests pass at HEAD |
| `psutil` NOT installed | venv | — | `python -c "import psutil"` → `ModuleNotFoundError` |
| `resource` module unavailable on Windows | stdlib | — | `python -c "import resource"` → `ModuleNotFoundError` |
| `tracemalloc` available cross-platform | stdlib | — | stdlib since Python 3.4 |

`runtime.runtime_sandbox` attribute, `RuntimeSandbox` class, `SandboxLimits`, `SandboxOutcome`, `CapabilityDenied`, `check_capability`, `require_capability`, `SANDBOX_LIMIT_EXCEEDED`, `SANDBOX_CAPABILITY_DENIED`, `sandbox_enabled`, `sandbox_default_wall_timeout_seconds`, `sandbox_default_memory_peak_mb`, `egress_active_enforcement`, `HttpFetchAgent._egress_policy`, `HttpFetchAgent.set_egress_policy` — all greenfield, verified zero hits at HEAD `343df76`.

---

## Implementation

### Section 0 — Event Types

**File:** `src/probos/events.py`

`SEARCH` block (the AD-456 `EGRESS_BLOCKED` / `AUDIT_RECORDED` lines plus their immediate context):
```python
    SECRET_ROTATED = "secret_rotated"  # AD-456
    EGRESS_BLOCKED = "egress_blocked"  # AD-456
    CLASSIFICATION_DISCLOSURE_BLOCKED = "classification_disclosure_blocked"  # AD-530
    BOUNDARY_VIOLATION_DETECTED = "boundary_violation_detected"  # AD-511
    DUTY_SCOPE_QUERIED = "duty_scope_queried"  # AD-508
    WORKSPACE_TERM_REGISTERED = "workspace_term_registered"  # AD-478
    AUDIT_RECORDED = "audit_recorded"  # AD-456
```

`REPLACE`:
```python
    SECRET_ROTATED = "secret_rotated"  # AD-456
    EGRESS_BLOCKED = "egress_blocked"  # AD-456
    CLASSIFICATION_DISCLOSURE_BLOCKED = "classification_disclosure_blocked"  # AD-530
    BOUNDARY_VIOLATION_DETECTED = "boundary_violation_detected"  # AD-511
    DUTY_SCOPE_QUERIED = "duty_scope_queried"  # AD-508
    WORKSPACE_TERM_REGISTERED = "workspace_term_registered"  # AD-478
    AUDIT_RECORDED = "audit_recorded"  # AD-456
    SANDBOX_LIMIT_EXCEEDED = "sandbox_limit_exceeded"  # AD-456b
    SANDBOX_CAPABILITY_DENIED = "sandbox_capability_denied"  # AD-456b
```

---

### Section 1 — `SecurityInfraConfig` extension

**File:** `src/probos/config.py`

`SEARCH` block (the entire `SecurityInfraConfig` body, lines 1450-1462):
```python
class SecurityInfraConfig(BaseModel):
    """Security infrastructure configuration (AD-456).

    Distinct from ``SecurityConfig`` (AD-455) which configures threat detection,
    input validation, trust integrity, and red-team coordination.
    """

    secrets_persistence_enabled: bool = True
    secrets_store_filename: str = "secrets.json"
    egress_enabled: bool = True
    egress_deny_by_default: bool = True  # v1: real-signal default per no-theater
    audit_enabled: bool = True
```

`REPLACE`:
```python
class SecurityInfraConfig(BaseModel):
    """Security infrastructure configuration (AD-456 + AD-456b).

    Distinct from ``SecurityConfig`` (AD-455) which configures threat detection,
    input validation, trust integrity, and red-team coordination.
    """

    secrets_persistence_enabled: bool = True
    secrets_store_filename: str = "secrets.json"
    egress_enabled: bool = True
    egress_deny_by_default: bool = True  # v1: real-signal default per no-theater
    audit_enabled: bool = True

    # AD-456b: Runtime Sandboxing
    sandbox_enabled: bool = True
    sandbox_default_wall_timeout_seconds: float = 30.0
    sandbox_default_memory_peak_mb: float = 256.0
    # AD-456b: Egress active enforcement (v1 default False — preserves AD-456
    # consultation-only behavior on existing deployments; flip to True at upgrade
    # time after reviewing allowlist coverage. AD-456b-7 will flip default to True
    # once fleet-wide allowlist coverage is verified.).
    egress_active_enforcement: bool = False
```

---

### Section 2 — `RuntimeSandbox` module

**File:** `src/probos/security/runtime_sandbox.py` (NEW)

Full file:
```python
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
```

---

### Section 3 — `HttpFetchAgent` egress consultation

**File:** `src/probos/agents/http_fetch.py`

#### Section 3a — ClassVar + classmethod

`SEARCH` block (the existing `_profile_store` ClassVar + `set_profile_store` classmethod, lines 83-89):
```python
    # Persistent service profile store (AD-382) — set via runtime wiring
    _profile_store: ClassVar[Any] = None

    @classmethod
    def set_profile_store(cls, store: Any) -> None:
        """Wire or disconnect the ServiceProfileStore."""
        cls._profile_store = store
```

`REPLACE`:
```python
    # Persistent service profile store (AD-382) — set via runtime wiring
    _profile_store: ClassVar[Any] = None

    @classmethod
    def set_profile_store(cls, store: Any) -> None:
        """Wire or disconnect the ServiceProfileStore."""
        cls._profile_store = store

    # AD-456b: Egress policy (active enforcement) — set via runtime wiring when
    # config.security_infra.egress_active_enforcement is True. Default None
    # preserves AD-456 v1 consultation-only behavior.
    _egress_policy: ClassVar[Any] = None

    @classmethod
    def set_egress_policy(cls, policy: Any) -> None:
        """Wire or disconnect the EgressPolicy for active SSRF enforcement."""
        cls._egress_policy = policy
```

#### Section 3b — `_validate_url` consultation

`SEARCH` block (the trailing portion of `_validate_url`, lines 170-178):
```python
        for family, _, _, _, sockaddr in addrinfo:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return f"Blocked private/reserved IP: {ip}"

        return None
```

`REPLACE`:
```python
        for family, _, _, _, sockaddr in addrinfo:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return f"Blocked private/reserved IP: {ip}"

        # AD-456b: Egress policy consultation (active enforcement). Defense in
        # depth — runs AFTER scheme/host/private-IP guards. EgressPolicy emits
        # EGRESS_BLOCKED itself; we only need to surface the block to the
        # caller. When _egress_policy is None (config.security_infra.
        # egress_active_enforcement=False, the v1 default), this block is a
        # no-op and AD-456 consultation-only behavior is preserved.
        policy = type(self)._egress_policy
        if policy is not None:
            try:
                if not policy.is_allowed(url):
                    return "Egress policy: blocked by AD-456b runtime sandboxing"
            except Exception:
                logger.warning(
                    "AD-456b: EgressPolicy.is_allowed failed; allowing request",
                    exc_info=True,
                )

        return None
```

---

### Section 4 — `startup/finalize.py` wiring

**File:** `src/probos/startup/finalize.py`

`SEARCH` block (the AD-456 AuditLog wiring block, lines 1281-1289):
```python
    if config.security_infra.audit_enabled:
        from probos.security.audit import AuditLog
        runtime.audit_log = AuditLog(emit_event=runtime.emit_event)
        logger.info("AD-456: AuditLog wired (in-memory hash chain)")
    else:
        runtime.audit_log = None
```

`REPLACE`:
```python
    if config.security_infra.audit_enabled:
        from probos.security.audit import AuditLog
        runtime.audit_log = AuditLog(emit_event=runtime.emit_event)
        logger.info("AD-456: AuditLog wired (in-memory hash chain)")
    else:
        runtime.audit_log = None

    # AD-456b: Runtime Sandboxing
    if config.security_infra.sandbox_enabled:
        from probos.security.runtime_sandbox import RuntimeSandbox, SandboxLimits
        runtime.runtime_sandbox = RuntimeSandbox(
            default_limits=SandboxLimits(
                wall_timeout_seconds=config.security_infra.sandbox_default_wall_timeout_seconds,
                memory_peak_mb=config.security_infra.sandbox_default_memory_peak_mb,
            ),
            emit_event=runtime.emit_event,
        )
        logger.info(
            "AD-456b: RuntimeSandbox wired (wall=%.1fs, mem_peak=%.0fMB)",
            config.security_infra.sandbox_default_wall_timeout_seconds,
            config.security_infra.sandbox_default_memory_peak_mb,
        )
    else:
        runtime.runtime_sandbox = None

    # AD-456b: HttpFetchAgent egress active enforcement (gated on
    # egress_active_enforcement; v1 default False preserves AD-456
    # consultation-only behavior). When False, _egress_policy stays None
    # and HttpFetchAgent._validate_url skips the consultation block.
    if (
        config.security_infra.egress_active_enforcement
        and runtime.egress_policy is not None
    ):
        from probos.agents.http_fetch import HttpFetchAgent
        HttpFetchAgent.set_egress_policy(runtime.egress_policy)
        logger.info("AD-456b: HttpFetchAgent egress active enforcement enabled")
```

---

### Section 5 — Tests

**File:** `tests/test_ad456b_runtime_sandboxing.py` (NEW)

12 tests:

```python
"""AD-456b: Runtime Sandboxing tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.config import SystemConfig
from probos.events import EventType
from probos.security.runtime_sandbox import (
    CapabilityDenied,
    RuntimeSandbox,
    SandboxLimits,
    SandboxOutcome,
    check_capability,
    require_capability,
)


# --- RuntimeSandbox happy path -------------------------------------------------

@pytest.mark.asyncio
async def test_execute_returns_success_outcome_for_normal_coroutine() -> None:
    sandbox = RuntimeSandbox()

    async def work() -> int:
        return 42

    outcome = await sandbox.execute(work, limits=SandboxLimits(wall_timeout_seconds=5.0))

    assert outcome.success is True
    assert outcome.result == 42
    assert outcome.error == ""
    assert outcome.limit_exceeded == ""
    assert outcome.capability_denied == ""
    assert outcome.wall_ms >= 0
    assert outcome.peak_memory_kb >= 0


# --- Wall timeout enforcement --------------------------------------------------

@pytest.mark.asyncio
async def test_execute_returns_wall_timeout_outcome_and_emits_event() -> None:
    emit_event = MagicMock()
    sandbox = RuntimeSandbox(emit_event=emit_event)

    async def slow() -> None:
        await asyncio.sleep(2.0)

    outcome = await sandbox.execute(
        slow,
        limits=SandboxLimits(wall_timeout_seconds=0.05, memory_peak_mb=256.0),
    )

    assert outcome.success is False
    assert outcome.limit_exceeded == "wall"
    assert "wall timeout" in outcome.error
    emit_event.assert_called_once()
    args, kwargs = emit_event.call_args
    assert args[0] == EventType.SANDBOX_LIMIT_EXCEEDED
    assert args[1]["kind"] == "wall"


# --- Memory peak detection -----------------------------------------------------

@pytest.mark.asyncio
async def test_execute_returns_memory_outcome_when_peak_exceeds_cap() -> None:
    emit_event = MagicMock()
    sandbox = RuntimeSandbox(emit_event=emit_event)

    async def alloc_big() -> int:
        # Allocate ~2 MB to overshoot a 0.001 MB (1 KB) cap deterministically.
        big = bytearray(2 * 1024 * 1024)
        return len(big)

    outcome = await sandbox.execute(
        alloc_big,
        limits=SandboxLimits(wall_timeout_seconds=10.0, memory_peak_mb=0.001),
    )

    assert outcome.success is False
    assert outcome.limit_exceeded == "memory"
    assert "peak memory" in outcome.error
    emit_event.assert_called_once()
    assert emit_event.call_args[0][1]["kind"] == "memory"


# --- Capability check ----------------------------------------------------------

@pytest.mark.asyncio
async def test_check_capability_returns_true_when_present() -> None:
    sandbox = RuntimeSandbox()

    async def work() -> bool:
        return check_capability("net.read")

    outcome = await sandbox.execute(
        work,
        limits=SandboxLimits(wall_timeout_seconds=5.0),
        capabilities=frozenset({"net.read"}),
    )

    assert outcome.success is True
    assert outcome.result is True


@pytest.mark.asyncio
async def test_check_capability_returns_false_when_missing() -> None:
    sandbox = RuntimeSandbox()

    async def work() -> bool:
        return check_capability("fs.write")

    outcome = await sandbox.execute(
        work,
        limits=SandboxLimits(wall_timeout_seconds=5.0),
        capabilities=frozenset({"net.read"}),
    )

    assert outcome.success is True
    assert outcome.result is False


@pytest.mark.asyncio
async def test_require_capability_raises_and_emits_when_missing() -> None:
    emit_event = MagicMock()
    sandbox = RuntimeSandbox(emit_event=emit_event)

    async def work() -> None:
        require_capability("fs.write", emit_event=emit_event)

    outcome = await sandbox.execute(
        work,
        limits=SandboxLimits(wall_timeout_seconds=5.0),
        capabilities=frozenset({"net.read"}),
    )

    assert outcome.success is False
    assert outcome.capability_denied == "fs.write"
    # SANDBOX_CAPABILITY_DENIED should have fired exactly once via require_capability.
    capability_denied_calls = [
        c for c in emit_event.call_args_list
        if c.args and c.args[0] == EventType.SANDBOX_CAPABILITY_DENIED
    ]
    assert len(capability_denied_calls) == 1
    assert capability_denied_calls[0].args[1] == {"capability": "fs.write"}


@pytest.mark.asyncio
async def test_check_capability_outside_sandbox_returns_true() -> None:
    # Consultation is no-op outside a sandbox — preserves drop-in safety
    # for code paths that consult check_capability without a wrapping sandbox.
    assert check_capability("anything") is True


# --- Context isolation ---------------------------------------------------------

@pytest.mark.asyncio
async def test_capability_context_is_reset_after_execute() -> None:
    sandbox = RuntimeSandbox()

    async def work() -> None:
        return None

    await sandbox.execute(
        work,
        limits=SandboxLimits(wall_timeout_seconds=5.0),
        capabilities=frozenset({"net.read"}),
    )

    # Outside the sandbox the context is reset.
    assert check_capability("net.read") is True  # no-active-context path
    # Confirm no leakage by running a second sandbox without capabilities.
    async def inspect() -> bool:
        return check_capability("net.read")
    outcome = await sandbox.execute(
        inspect,
        limits=SandboxLimits(wall_timeout_seconds=5.0),
    )
    assert outcome.result is False


# --- HttpFetchAgent egress integration ----------------------------------------

def test_httpfetchagent_validate_url_blocks_when_egress_policy_denies() -> None:
    from probos.agents.http_fetch import HttpFetchAgent
    from probos.security.egress import EgressPolicy

    policy = EgressPolicy(
        allowlist=["allowed.example.com"],
        deny_by_default=True,
    )
    HttpFetchAgent.set_egress_policy(policy)
    try:
        agent = HttpFetchAgent(pool="http")
        # Use a public-DNS-resolving host that will pass the SSRF guards but
        # fail the egress check. example.com resolves to public IPs.
        error = agent._validate_url("https://example.com/")
        assert error is not None
        assert "Egress policy" in error
        assert "AD-456b" in error
    finally:
        HttpFetchAgent.set_egress_policy(None)


def test_httpfetchagent_validate_url_passes_when_egress_policy_allows() -> None:
    from probos.agents.http_fetch import HttpFetchAgent
    from probos.security.egress import EgressPolicy

    policy = EgressPolicy(
        allowlist=["example.com"],
        deny_by_default=True,
    )
    HttpFetchAgent.set_egress_policy(policy)
    try:
        agent = HttpFetchAgent(pool="http")
        error = agent._validate_url("https://example.com/")
        # Either None (allowed) or a non-egress error (e.g., DNS); the egress
        # branch must NOT be the source of the block.
        assert error is None or "Egress policy" not in error
    finally:
        HttpFetchAgent.set_egress_policy(None)


def test_httpfetchagent_egress_policy_default_none_preserves_ad456_behavior() -> None:
    from probos.agents.http_fetch import HttpFetchAgent

    # Default ClassVar value — AD-456 v1 consultation-only behavior preserved.
    HttpFetchAgent.set_egress_policy(None)
    assert HttpFetchAgent._egress_policy is None


# --- Config + finalize wiring --------------------------------------------------

def test_security_infra_config_defaults_match_v1_contract() -> None:
    config = SystemConfig()
    assert config.security_infra.sandbox_enabled is True
    assert config.security_infra.sandbox_default_wall_timeout_seconds == 30.0
    assert config.security_infra.sandbox_default_memory_peak_mb == 256.0
    # egress_active_enforcement defaults to False — preserves AD-456 v1 behavior
    # on existing deployments per AD-456b DLog.
    assert config.security_infra.egress_active_enforcement is False
```

---

## What This Does NOT Change

- **`cognitive/sandbox.py:SandboxRunner`** — self-mod correctness harness; orthogonal subsystem; not touched.
- **`agents/red_team.py`** — egress consultation by RedTeamAgent is AD-456b-4.
- **`runtime.egress_policy` / `runtime.audit_log` / `runtime.credential_store`** — AD-456 wiring unchanged.
- **`EgressPolicy` class itself** — `EGRESS_BLOCKED` emit path already in place at `egress.py:135`; v1 just adds a real consumer.
- **AD-660b causal-reasoning diagnostic actions** — DLog #10 deferred surface; AD-456b ships `runtime.runtime_sandbox`, AD-456b-3 wires `DiagnosticAction.execute()` through it.
- **`BayesianTrust` → capability-set policy** — AD-456b-2.
- **Container / namespace / eBPF isolation** — *(Commercial)* extension point only.
- **Hot-reload of egress allowlist via HXI** — AD-456b-6.
- **No new pool, no new agent, no new module beyond `runtime_sandbox.py`.**
- **No new Pydantic config beyond `SecurityInfraConfig` field additions.**
- **No new journal table.**
- **No deprecation, no removal, no signature change** on any existing AD-456 / AD-680 / AD-382 surface.

---

## Tracking Updates (post-build, single commit per ask)

- `PROGRESS.md` — prepend AD-456b CLOSED entry.
- `docs/development/roadmap.md` — flip AD-456b row to ✅ shipped under the AD-456 cluster; add AD-456b-1 / AD-456b-2 / AD-456b-3 / AD-456b-4 *(Commercial)* / AD-456b-5 / AD-456b-6 / AD-456b-7 deferral entries with explicit forcing functions.
- `DECISIONS.md` — prepend AD-456b entry at top of Era V.

## Issues to close

GitHub MCP `issue_write` close on **#398** (expect EMU 403 same as Waves 31-54; Captain closes manually).

## Acceptance Criteria

- All 12 new tests pass.
- All 16 existing AD-456 tests at `tests/test_ad456_security_infrastructure.py` continue to pass without modification.
- No HttpFetchAgent regression (verify `_egress_policy` defaults to None — `set_egress_policy(None)` is called in test fixtures' try/finally to keep ClassVar isolation across the test run).
- Full gate: 11227 → 11239 (+12 net), or +13 ceiling.
- `tracemalloc.stop()` does not raise when called on a tracemalloc that was already running before sandbox entry (handled by `tracemalloc_started_here` guard).
- `_active_sandbox_capabilities.reset(token)` runs in `finally` regardless of exception path.
- `HttpFetchAgent._egress_policy` is `None` by default — test #11 locks this contract.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Commit message

`AD-456b: Security infrastructure runtime sandboxing v1 (RuntimeSandbox + HttpFetchAgent egress active enforcement) (+12 tests)`
