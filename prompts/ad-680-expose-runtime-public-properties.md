# AD-680: Expose Runtime Public Properties — Eliminate Wiring-Code Private-Attr Access

**Status:** Ready for builder
**Issue:** TBD
**Dependencies:** AD-571 (introduced first wave of TODOs), AD-673 (introduced second wave), AD-300+ (runtime architecture)
**Estimated tests:** ~6

---

## Problem

Multiple cross-cutting modules (`startup/*.py` wiring code, AD-571 tier registry population, AD-673 anomaly window wiring, several others) reach into `ProbOSRuntime` private attributes:

- `runtime._trust_network`
- `runtime._router` (HebbianRouter)
- `runtime._emergence_metrics_engine`
- `runtime._emit_event`
- `runtime._add_event_listener_fn`

These accesses are flagged with `# TODO(AD-571): Replace with public property once ProbOSRuntime exposes ...` comments. Each new wiring module either adds another TODO or copies the pattern, so the smell compounds. The Builder note for both AD-571 and AD-673 explicitly justified the access as "acceptable in startup wiring code," which is true but does not scale.

This violates the Open/Closed and Demeter principles in §"Engineering Principles" of `.github/copilot-instructions.md`. It also makes refactoring `ProbOSRuntime` internals brittle — any rename of `_trust_network` would silently break all wiring sites.

## Solution

Expose the five attributes above as **public read-only properties** on `ProbOSRuntime`, then sweep all known wiring sites to use the new public surface. Remove the corresponding `# TODO(AD-571)` and `# TODO(AD-673)` comments.

This is a pure refactor — no behavioral change. The bar for shipping is "all existing tests still pass + the new property-existence tests pass."

---

## Implementation

### 1. Add public properties to `ProbOSRuntime`

**File:** `src/probos/runtime.py`

Add five `@property` definitions on `ProbOSRuntime`. Each returns the existing underlying private attribute. Place them grouped together near the top of the class (after `__init__`, before `start()`).

```python
@property
def trust_network(self) -> "TrustNetwork":
    """Public accessor for trust network (AD-680). Read-only."""
    return self._trust_network

@property
def router(self) -> "HebbianRouter":
    """Public accessor for the Hebbian router (AD-680). Read-only."""
    return self._router

@property
def emergence_metrics_engine(self) -> "EmergenceMetricsEngine":
    """Public accessor for emergence metrics engine (AD-680). Read-only."""
    return self._emergence_metrics_engine

@property
def emit_event(self) -> Callable[[str, Any], None]:
    """Public accessor for the event-emission callable (AD-680).

    Returns the bound `_emit_event` method. Wiring code should call this
    rather than reaching for the private attribute.
    """
    return self._emit_event

@property
def add_event_listener_fn(self) -> Callable[[str, Callable[[Any], Awaitable[None]]], None]:
    """Public accessor for the event-listener registration callable (AD-680).

    Returns the bound `_add_event_listener_fn`.
    """
    return self._add_event_listener_fn
```

**Builder notes:**
- Use `from __future__ import annotations` if not already present — keeps the type-string forward references clean.
- If `_emit_event` or `_add_event_listener_fn` are already methods (not callables stored as attributes), the property may need to return `self._emit_event` directly (Python bound methods work as callables).
- **Verify first:** confirm the exact attribute names by grepping `src/probos/runtime.py` for `self\._(trust_network|router|emergence_metrics_engine|emit_event|add_event_listener_fn)`. If any name differs, use the actual name in the property body but keep the public property name as listed above.
- Do NOT add setters. These are read-only views into runtime state.
- Do NOT add deprecation warnings on the private attributes — this is a one-shot migration.

### 2. Sweep wiring sites

Replace every `runtime._<attr>` access in non-runtime modules with `runtime.<public_name>`. Remove the corresponding `# TODO(AD-571)` and `# TODO(AD-673)` comments. The known sites:

- `src/probos/startup/agent_tiers.py` (or wherever `_populate_agent_tiers` lives) — AD-571's primary site. Multiple accesses to `_trust_network`, `_router`, `_emergence_metrics_engine`.
- `src/probos/startup/anomaly_window.py` (or `_wire_anomaly_window`) — AD-673's primary site. Accesses to `_emit_event` and `_add_event_listener_fn`.

**Builder note:** Run a workspace grep for each pattern to find any other sites:
```
grep -rn "runtime\._trust_network" src/
grep -rn "runtime\._router" src/
grep -rn "runtime\._emergence_metrics_engine" src/
grep -rn "runtime\._emit_event" src/
grep -rn "runtime\._add_event_listener_fn" src/
```
Replace ALL of them. Do NOT touch accesses inside `runtime.py` itself — those are legitimate private accesses by the owning class. Do NOT touch accesses inside test files unless they're testing the wiring layer (in which case, update them to use the public surface).

**Builder note:** `getattr(runtime, "_emit_event", None)` patterns should become `runtime.emit_event` (no fallback needed — the public property always exists).

### 3. Remove TODOs

After each replacement, delete the adjacent `# TODO(AD-571)` or `# TODO(AD-673)` comment. The TODO has been fulfilled.

### 4. Type-checking sanity

If `ProbOSRuntime` has a `typing.Protocol` definition elsewhere (e.g., in `runtime_protocol.py` or similar) that wiring code imports, add the new property signatures to that Protocol too so static analysis sees them.

**Verify first:** grep for `class.*Runtime.*Protocol` and `RuntimeProtocol` to find any existing protocol definition. If none exists, skip this step.

---

## Test Plan

Add tests in `tests/test_runtime_public_properties.py`:

1. `test_trust_network_property_exists` — instantiate ProbOSRuntime (or a minimal fake), assert `runtime.trust_network is runtime._trust_network`.
2. `test_router_property_exists` — same for `router`.
3. `test_emergence_metrics_engine_property_exists` — same.
4. `test_emit_event_property_returns_callable` — assert `callable(runtime.emit_event)` is True.
5. `test_add_event_listener_fn_property_returns_callable` — same.
6. `test_no_remaining_runtime_underscore_access_in_startup` — codebase invariant: `grep -rn "runtime\._\(trust_network\|router\|emergence_metrics_engine\|emit_event\|add_event_listener_fn\)" src/probos/startup/` returns zero matches. Implement as a Python test using `pathlib.Path.rglob` and a regex; assert the match list is empty.

Use `_FakeRuntime` stubs where instantiating the full runtime is heavy. The properties should be exercisable on any object that has the corresponding underscore attribute, so a tiny fake works.

---

## Acceptance Criteria

- All five public properties added to `ProbOSRuntime` and pass type-check.
- All wiring sites in `src/probos/startup/` (and any other discovered locations) migrated to public properties.
- All `# TODO(AD-571)` and `# TODO(AD-673)` comments referencing this migration removed.
- All 6 new tests pass.
- Full xdist gate (`pytest tests/ -q -n auto`) — apply standard xdist worker-crash triage rule. No new real failures introduced.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## What This Does NOT Change

- No behavioral change. The properties return the same object the private attributes already pointed to.
- No new event emission, no new wiring topology, no new agent classification logic.
- The private attributes remain accessible from inside `ProbOSRuntime` itself — this AD only changes the *external* access pattern.
- Does NOT touch `runtime.intent_bus`, `runtime.config`, or other already-public properties on ProbOSRuntime.
- Does NOT add setters for any of the new properties — they are read-only.
