# AD-680: Promote `_emit_event` and `_emergence_metrics_engine` to Public API

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~4

---

## Problem

External modules reach into `ProbOSRuntime` private attributes for event emission and
emergence metrics access. This violates Demeter and makes runtime refactoring brittle.

Two real targets remain:

| Private attribute | External call sites | Files |
|---|---|---|
| `runtime._emit_event(...)` | ~61 | 8 files (finalize.py, proactive.py, cognitive_agent.py, build.py, chat.py, design.py, builder.py, jit_bridge.py) |
| `runtime._emergence_metrics_engine` | 8 | 4 files (finalize.py, collective_tests.py, system.py, vitals_monitor.py) |

**Note:** `trust_network`, `hebbian_router`, and `add_event_listener` are already public —
no action needed for those.

## Fix

### Section 1: Update `emit_event` type hint to accept `EventType`

**File:** `src/probos/runtime.py`

The public `emit_event` method (line 771) currently has this signature:

```python
def emit_event(self, event: BaseEvent | str, data: dict[str, Any] | None = None) -> None:
```

Most callers pass `EventType` enum values (e.g., `EventType.BUILD_RESOLVED`). This works
at runtime because `_emit_event` handles `EventType`, but the type hint is incomplete.

SEARCH:
```python
    def emit_event(self, event: BaseEvent | str, data: dict[str, Any] | None = None) -> None:
```

REPLACE:
```python
    def emit_event(self, event: BaseEvent | str | EventType, data: dict[str, Any] | None = None) -> None:
```

Also update the `RuntimeProtocol` definition.

**File:** `src/probos/protocols.py` (line 105)

SEARCH:
```python
    def emit_event(self, event: BaseEvent | str, data: dict[str, Any] | None = None) -> None: ...
```

REPLACE:
```python
    def emit_event(self, event: BaseEvent | str | EventType, data: dict[str, Any] | None = None) -> None: ...
```

Verify `EventType` is already imported in both files (it should be — grep for
`from probos.events import`).

### Section 2: Add `emergence_metrics_engine` property

**File:** `src/probos/runtime.py`

Add a public read-only property near the other public accessors. Find
`self._emergence_metrics_engine` initialization (line 519) to confirm the attribute name.

```python
    @property
    def emergence_metrics_engine(self) -> Any:
        """Public accessor for emergence metrics engine (AD-680). Read-only."""
        return self._emergence_metrics_engine
```

Do NOT add a setter.

### Section 3: Migrate all external `_emit_event` call sites

Replace every `runtime._emit_event`, `rt._emit_event`, and `self._runtime._emit_event`
in modules **outside** `runtime.py` with the public `emit_event` equivalent.

**Files to modify (run grep to confirm — do not rely on this list alone):**

```
src/probos/startup/finalize.py         (~15 sites)
src/probos/routers/build.py            (~15 sites)
src/probos/routers/chat.py             (~8 sites)
src/probos/routers/design.py           (~6 sites)
src/probos/cognitive/cognitive_agent.py (~6 sites)
src/probos/proactive.py                (~4 sites)
src/probos/cognitive/builder.py        (~2 sites)
src/probos/sop/jit_bridge.py           (~1 site)
```

**Replacement rules:**

1. Direct calls: `rt._emit_event(EventType.X, {...})` → `rt.emit_event(EventType.X, {...})`
2. Lambda wrappers: `lambda event_type, data: runtime._emit_event(event_type, data)` → `runtime.emit_event`
   (the public method already has the same signature, so the lambda is unnecessary —
   just pass `runtime.emit_event` directly as the callable)
3. `getattr` defensive patterns: `getattr(runtime, "_emit_event", None)` → `runtime.emit_event`
   (no fallback needed — the public method always exists on `ProbOSRuntime`)
4. `hasattr` guards: `hasattr(_rt, '_emit_event') and _rt._emit_event` → just call `_rt.emit_event`

**Do NOT touch:**
- `self._emit_event` inside `runtime.py` itself (legitimate private access by the owning class)
- `self._emit_event` on OTHER classes (e.g., `TrustNetwork._emit_event`, `CognitiveQueue._emit_event`,
  `WardRoomService._emit_event`) — these are local attributes on those classes, not runtime accesses.
  They store a callback passed during construction. Leave them alone.
- Test files — unless they directly call `runtime._emit_event` (update those too)

**How to distinguish:** If the line has `runtime._emit_event` or `rt._emit_event` or
`self._runtime._emit_event` where the object is a `ProbOSRuntime` instance, migrate it.
If the line has `self._emit_event` where `self` is NOT `ProbOSRuntime`, leave it.

### Section 4: Migrate all external `_emergence_metrics_engine` accesses

Replace `getattr(runtime, "_emergence_metrics_engine", None)` with
`getattr(runtime, "emergence_metrics_engine", None)` in all external modules.

**Files (grep to confirm):**

```
src/probos/startup/finalize.py                  (1 site, line ~160)
src/probos/cognitive/collective_tests.py         (4 sites)
src/probos/routers/system.py                     (2 sites)
src/probos/agents/medical/vitals_monitor.py      (1 site)
```

Keep the `getattr(..., None)` pattern — the property may return `None` if metrics engine
hasn't been initialized yet (line 519: `self._emergence_metrics_engine: Any = None`).

## Tests

**File:** `tests/test_ad680_public_runtime_api.py`

4 tests:

1. `test_emit_event_accepts_event_type_enum` — call `runtime.emit_event(EventType.LLM_HEALTH_CHANGED, {"new_status": "degraded"})`,
   verify no TypeError (smoke test for the updated type hint)
2. `test_emergence_metrics_engine_property` — set `runtime._emergence_metrics_engine = sentinel`,
   verify `runtime.emergence_metrics_engine is sentinel`
3. `test_emergence_metrics_engine_default_none` — fresh runtime, verify
   `runtime.emergence_metrics_engine is None`
4. `test_no_private_emit_event_in_external_modules` — codebase invariant: scan all `.py` files
   under `src/probos/` **except** `runtime.py` for the pattern `runtime\._emit_event|rt\._emit_event|self\._runtime\._emit_event`.
   Assert zero matches. Implement with `pathlib.Path.rglob("*.py")` and `re.search`.

Use `_FakeRuntime` stubs or `unittest.mock.MagicMock` where instantiating the full runtime
is heavy.

## What This Does NOT Change

- No behavioral change — `emit_event` delegates to `_emit_event`, same execution path
- `_emit_event` remains as the private implementation inside `runtime.py`
- `self._emit_event` on non-runtime classes (TrustNetwork, CognitiveQueue, etc.) is untouched
- No changes to `trust_network`, `hebbian_router`, `add_event_listener` — already public
- No new event types, no new wiring topology
- Does NOT add setters for any property

## Tracking

- `PROGRESS.md`: Add AD-680 as COMPLETE
- `docs/development/roadmap.md`: Add AD-680 entry
- `DECISIONS.md`: Record "no deprecation warning, one-shot migration" precedent for future
  private→public promotions

## Acceptance Criteria

- `emit_event` type hint includes `EventType` on both `ProbOSRuntime` and `RuntimeProtocol`
- `emergence_metrics_engine` property exists and returns `_emergence_metrics_engine`
- Zero external callers of `runtime._emit_event` remain outside `runtime.py`
- Zero external callers of `runtime._emergence_metrics_engine` remain
- All 4 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no new real failures
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
grep -n "def _emit_event" src/probos/runtime.py
  719:    def _emit_event(self, event_type: str | EventType, ...)

grep -n "def emit_event" src/probos/runtime.py
  771:    def emit_event(self, event: BaseEvent | str, ...)

grep -n "def emit_event" src/probos/protocols.py
  105:    def emit_event(self, event: BaseEvent | str, ...)

grep -n "_emergence_metrics_engine" src/probos/runtime.py
  519:        self._emergence_metrics_engine: Any = None
  1449:        self._emergence_metrics_engine = ...

External _emit_event sites (excluding runtime.py, excluding self._emit_event on other classes):
  61 call sites across 8 files

External _emergence_metrics_engine sites:
  8 call sites across 4 files (finalize.py, collective_tests.py, system.py, vitals_monitor.py)

Already-public attributes (NO action needed):
  runtime.trust_network — runtime.py:334, finalize.py:156
  runtime.hebbian_router — runtime.py:303, finalize.py:164
  runtime.add_event_listener — finalize.py:34 (already public method)
  runtime.emit_event — runtime.py:771 (exists, just underused)
```
