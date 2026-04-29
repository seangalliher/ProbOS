# AD-448: Wrapped Tool Executor

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~9

---

## Problem

`ToolRegistry.check_and_invoke()` performs permission checking and tool
invocation in a single method (registry.py:269-321). There's no hook
point for pre/post execution behavior — no timing, no audit logging,
no parameter sanitization, no result transformation.

Adding these concerns directly to `check_and_invoke()` would violate
single responsibility. AD-448 adds a `ToolExecutor` wrapper that sits
ABOVE the registry's permission chain, providing pre/post hooks without
duplicating the permission logic.

## ANTI-PATTERN WARNING

**Do NOT re-implement permission resolution.** The `ToolRegistry`
already has a 4-layer permission chain (scope → restriction → rank gate →
Captain override) plus LOTO locking. The `ToolExecutor` MUST delegate
to `ToolRegistry.check_and_invoke()` for all permission and invocation
logic. It only wraps the call with pre/post hooks.

## Fix

### Section 1: Create `ToolExecutor`

**File:** `src/probos/tools/executor.py` (new file)

```python
"""Wrapped Tool Executor — pre/post hooks around tool invocation (AD-448).

Sits above ToolRegistry.check_and_invoke(), adding:
- Pre-invoke hooks (parameter validation, audit logging)
- Post-invoke hooks (result logging, timing)
- Centralized timing for tool call telemetry

Does NOT duplicate permission resolution or LOTO — those stay in
ToolRegistry. This is a decorator pattern, not a replacement.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.tools.protocol import ToolResult

logger = logging.getLogger(__name__)

# Hook type: receives context dict, can modify it. Returns True to proceed,
# False to abort invocation.
PreHook = Callable[[dict[str, Any]], bool]
# Post-hook: receives context + result
PostHook = Callable[[dict[str, Any], "ToolResult"], None]


@dataclass
class InvocationContext:
    """Context passed through the hook chain (AD-448)."""

    agent_id: str
    tool_id: str
    params: dict[str, Any]
    start_time: float = field(default_factory=time.perf_counter)
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolExecutor:
    """Wraps ToolRegistry with pre/post invocation hooks (AD-448).

    Usage:
        executor = ToolExecutor(registry=tool_registry)
        executor.add_pre_hook(my_audit_hook)
        result = await executor.invoke(agent_id, tool_id, params, ...)

    The executor delegates ALL permission checks and invocation to
    ToolRegistry.check_and_invoke(). It adds:
    - Pre-hooks: run before invocation. If any returns False, invocation
      is aborted with an error ToolResult.
    - Post-hooks: run after invocation with the result.
    - Timing: elapsed time is recorded on InvocationContext.
    """

    def __init__(self, *, registry: Any) -> None:
        self._registry = registry
        self._pre_hooks: list[PreHook] = []
        self._post_hooks: list[PostHook] = []

    def add_pre_hook(self, hook: PreHook) -> None:
        """Register a pre-invocation hook."""
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook: PostHook) -> None:
        """Register a post-invocation hook."""
        self._post_hooks.append(hook)

    async def invoke(
        self,
        agent_id: str,
        tool_id: str,
        params: dict[str, Any],
        **kwargs: Any,
    ) -> "ToolResult":
        """Execute a tool call with pre/post hooks.

        Delegates to ToolRegistry.check_and_invoke() for permission
        checking and actual invocation.

        Args:
            agent_id: The agent requesting the tool
            tool_id: The tool to invoke
            params: Tool parameters
            **kwargs: Forwarded to check_and_invoke (required, agent_department,
                      agent_rank, agent_types, context)
        """
        from probos.tools.protocol import ToolResult

        ctx = InvocationContext(
            agent_id=agent_id,
            tool_id=tool_id,
            params=params,
        )
        hook_context = {
            "agent_id": agent_id,
            "tool_id": tool_id,
            "params": params,
            "invocation": ctx,
        }

        # Run pre-hooks
        for hook in self._pre_hooks:
            try:
                if not hook(hook_context):
                    logger.debug(
                        "AD-448: Pre-hook aborted invocation %s/%s",
                        agent_id[:12], tool_id,
                    )
                    return ToolResult(
                        error=f"Pre-hook aborted invocation of {tool_id}",
                    )
            except Exception:
                logger.warning(
                    "AD-448: Pre-hook error for %s/%s",
                    agent_id[:12], tool_id, exc_info=True,
                )
                # Pre-hook failure does NOT abort — fail open

        # Delegate to registry (permission + invocation)
        result = await self._registry.check_and_invoke(
            agent_id, tool_id, params, **kwargs,
        )

        # Record timing
        ctx.duration_ms = (time.perf_counter() - ctx.start_time) * 1000

        # Run post-hooks
        for hook in self._post_hooks:
            try:
                hook(hook_context, result)
            except Exception:
                logger.warning(
                    "AD-448: Post-hook error for %s/%s",
                    agent_id[:12], tool_id, exc_info=True,
                )

        return result

    @property
    def hook_count(self) -> int:
        """Total registered hooks."""
        return len(self._pre_hooks) + len(self._post_hooks)
```

### Section 2: Add `TOOL_INVOKED` event type

**File:** `src/probos/events.py`

Add after `TOOL_PERMISSION_DENIED`:

SEARCH:
```python
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
```

REPLACE:
```python
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
    TOOL_INVOKED = "tool_invoked"  # AD-448
```

**Note:** If AD-445 or AD-676 have already built (adding events after
this line), update the SEARCH block accordingly.

### Section 3: Add default audit post-hook

**File:** `src/probos/tools/executor.py`

Add a factory function for the standard audit hook:

```python
def make_audit_hook(
    emit_fn: Callable[[str, dict[str, Any]], None] | None = None,
) -> PostHook:
    """Create a post-hook that emits TOOL_INVOKED events (AD-448)."""

    def audit_hook(ctx: dict[str, Any], result: "ToolResult") -> None:
        if emit_fn:
            from probos.events import EventType
            emit_fn(EventType.TOOL_INVOKED, {
                "agent_id": ctx["agent_id"],
                "tool_id": ctx["tool_id"],
                "duration_ms": ctx["invocation"].duration_ms,
                "error": result.error,
                "timestamp": time.time(),
            })

    return audit_hook
```

### Section 4: Wire ToolExecutor in startup

**File:** `src/probos/startup/finalize.py`

Find where ToolRegistry is accessed. Grep for:
```
grep -n "tool_registry\|ToolRegistry" src/probos/startup/finalize.py
```

Add after ToolRegistry is available:

```python
    # AD-448: Wrapped Tool Executor
    from probos.tools.executor import ToolExecutor, make_audit_hook
    tool_executor = ToolExecutor(registry=runtime.tool_registry)
    # Wire audit hook
    audit_hook = make_audit_hook(
        emit_fn=runtime.emit_event if hasattr(runtime, 'emit_event') else None,
    )
    tool_executor.add_post_hook(audit_hook)
    runtime._tool_executor = tool_executor
    logger.info("AD-448: ToolExecutor initialized with %d hooks", tool_executor.hook_count)
```

## Tests

**File:** `tests/test_ad448_wrapped_tool_executor.py`

9 tests:

1. `test_invocation_context_creation` — create `InvocationContext`, verify fields
2. `test_executor_delegates_to_registry` — mock registry, call `executor.invoke()`,
   verify `check_and_invoke` was called with correct args
3. `test_pre_hook_runs_before_invocation` — add pre-hook that records call order,
   verify it runs before registry
4. `test_pre_hook_abort` — add pre-hook returning False, verify invocation
   is aborted and ToolResult has error
5. `test_post_hook_receives_result` — add post-hook, verify it receives
   the ToolResult from registry
6. `test_timing_recorded` — invoke, verify `InvocationContext.duration_ms > 0`
7. `test_pre_hook_error_fails_open` — add pre-hook that raises, verify
   invocation proceeds (not aborted)
8. `test_audit_hook_emits_event` — wire `make_audit_hook` with mock emit_fn,
   invoke, verify `TOOL_INVOKED` event emitted
9. `test_tool_invoked_event_type_exists` — verify `EventType.TOOL_INVOKED` exists

## What This Does NOT Change

- `ToolRegistry.check_and_invoke()` unchanged — ToolExecutor wraps it
- Permission resolution chain (4 layers) unchanged
- LOTO locking unchanged
- `ToolPermission` enum unchanged
- Does NOT modify existing tool call sites — they continue using
  `ToolRegistry.check_and_invoke()` directly. Future AD can migrate
  callers to use ToolExecutor.
- Does NOT add parameter sanitization hooks (future enhancement)
- Does NOT add result caching (future enhancement)

## Tracking

- `PROGRESS.md`: Add AD-448 as COMPLETE
- `docs/development/roadmap.md`: Update AD-448 status

## Acceptance Criteria

- `ToolExecutor` wraps `ToolRegistry.check_and_invoke()` without duplicating logic
- Pre-hooks can abort invocation
- Post-hooks receive result
- Timing is recorded
- `make_audit_hook()` emits `TOOL_INVOKED` events
- `EventType.TOOL_INVOKED` exists
- All 9 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# ToolRegistry
grep -n "class ToolRegistry" src/probos/tools/registry.py
  49: class ToolRegistry

# check_and_invoke
grep -n "async def check_and_invoke" src/probos/tools/registry.py
  269: check_and_invoke(agent_id, tool_id, params, *, required, agent_department, agent_rank, agent_types, context)

# ToolResult
grep -n "class ToolResult" src/probos/tools/protocol.py
  69: @dataclass(frozen=True) class ToolResult

# Permission chain
grep -n "resolve_permission\|Layer" src/probos/tools/registry.py | head -10
  191: def resolve_permission(...)
  214: Layer 1: Scope
  218: Layer 2: Restriction
  224: Layer 3: Rank gate
  236: Layer 4: Captain override

# No existing executor/wrapper
grep -rn "ToolExecutor\|tool_executor" src/probos/ → no matches
```
