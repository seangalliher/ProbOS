# Review: AD-448 — Wrapped Tool Executor

**Verdict:** ⚠️ Conditional
**Headline:** Missing event type; verify no recursion on permission delegation.

## Required

1. **`EventType.TOOL_INVOKED` does not exist.** Add to [src/probos/events.py](src/probos/events.py) before the audit hook in Section 3 fires.
2. **Verify ToolRegistry delegation contract.** `ToolExecutor.invoke()` calls `ToolRegistry.check_and_invoke()`. Confirmed [tools/registry.py:270](src/probos/tools/registry.py#L270) — `check_and_invoke()` does NOT call back into an executor, so no recursion risk. Document this explicitly so the builder doesn't add unnecessary defensive checks.

## Recommended

1. Audit-hook emission of `TOOL_INVOKED` (with `duration_ms`, `error`, `timestamp`) requires the new event type to be in scope at every call site that subscribes. Add a one-line acceptance criterion: "Every TOOL_INVOKED subscriber compiles after the enum addition."
2. Pre-hook abort returns `ToolResult(error=...)` (fail-open). Pre-hook *exceptions* are logged and do NOT abort — confirmed via the comment `# Pre-hook failure does NOT abort — fail open`. Worth restating in the docstring for `invoke()`.

## Nits

- `InvocationContext` uses `frozen=True` — good for hook-chain immutability.
- `TYPE_CHECKING` guard for `ToolResult` import is correct (avoids circular import).
- `hook_count` property is good for test introspection.

## Verified

- `ToolRegistry.check_and_invoke()` signature at [src/probos/tools/registry.py:270](src/probos/tools/registry.py#L270) — async, returns `ToolResult`, accepts `(agent_id, tool_id, params)` plus keyword-only args (`required`, `agent_department`, `agent_rank`, `agent_types`, `context`).
- `ToolResult` is a frozen dataclass at [src/probos/tools/protocol.py:74-80](src/probos/tools/protocol.py#L74) with `output`, `error`, `duration_ms`, `metadata`.
- `ToolPermission` enum at [src/probos/tools/protocol.py:28-38](src/probos/tools/protocol.py#L28) with `READ` default.
- No conflicts with existing tool invocation patterns.

---

## Second-Pass Re-review (2026-04-29)

**Verdict:** ⚠️ Conditional.

| Prior Item | Status |
|---|---|
| Add `EventType.TOOL_INVOKED` | ❌ Still missing — grep confirms absent in [events.py](src/probos/events.py). Section 2 still requires the addition. |
| ToolRegistry delegation — no recursion risk | ✅ Re-verified |
| Pre-hook fail-open documented | ✅ |

Batch the `TOOL_INVOKED` enum addition with AD-445/446 enum edits in a single events.py pass.
