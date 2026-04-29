# Review: AD-680 — Expose Runtime Public Properties

**Reviewer:** Architect
**Date:** 2026-04-29
**Verdict:** ❌ **Not Ready** — Premise is largely incorrect. Major rework required.

**Re-review (2026-04-29, second pass): ❌ Still Not Ready.** Prompt unchanged since
first pass. Additionally confirmed: `runtime.emit_event` already exists as a public
wrapper at `runtime.py:771` (verified via BF-246's revision), so the largest workstream
in AD-680 (migrating ~20 `_emit_event` call sites) is also redundant — callers can
switch to `runtime.emit_event` today without any runtime change. AD-680 reduces to:
(a) `_emergence_metrics_engine` → public property (1 call site), and (b) audit and
migrate the ~20 existing `runtime._emit_event` call sites to `runtime.emit_event`. See
the original review for full detail.

---

## Summary

The prompt frames itself as a sweep-and-replace refactor that exposes five private attributes
(`_trust_network`, `_router`, `_emergence_metrics_engine`, `_emit_event`, `_add_event_listener_fn`)
as public properties and removes `# TODO(AD-571)` / `# TODO(AD-673)` markers. **Three of the
five attributes are already public, and the TODO markers do not exist anywhere in `src/`.**
Building this prompt as written would produce phantom-property aliases and a no-op test that
greps for comments that were never written.

---

## Required (must fix before building)

### 1. `_trust_network` does not exist — attribute is already public as `trust_network`

`src/probos/runtime.py` defines `self.trust_network = TrustNetwork(...)` at line 334 and
declares it as an instance attribute at line 190. There is no `_trust_network`.

`src/probos/startup/finalize.py:156` already calls `getattr(runtime, "trust_network", None)`.

A `@property` named `trust_network` would shadow / collide with the existing attribute.

**Action:** Remove the `trust_network` property from the prompt. Verify no caller uses
`runtime._trust_network` (grep returns zero matches in `src/`).

### 2. `_router` does not exist — attribute is already public as `hebbian_router`

`src/probos/runtime.py:303` defines `self.hebbian_router = HebbianRouter(...)`.
`src/probos/startup/finalize.py:164` already uses `getattr(runtime, "hebbian_router", None)`.

The proposed `runtime.router` property would *introduce* a second name for the same thing
and create a Demeter-violation surface ("which name do I use?"), the opposite of the AD's
goal. The verify-first note in the prompt acknowledges this risk but resolves it by saying
"use the actual name in the property body" — that solution still ships a
new public name (`router`) that doesn't match the existing `hebbian_router` attribute and
isn't consumed by any wiring code.

**Action:** Remove the `router` property entirely, OR commit to a single public name and
do a real rename (which is a different, larger AD).

### 3. `_add_event_listener_fn` does not exist

There is no `_add_event_listener_fn` attribute on `ProbOSRuntime` and no caller references
it. The actual API used by `_wire_anomaly_window` (`finalize.py:34`) is
`getattr(runtime, "add_event_listener", None)` — already public, no leading underscore.
The prompt seems to be conflating two things:

- The argument name `_add_event_listener_fn` used by callers like
  `AnomalyWindowManager(add_event_listener_fn=add_listener)` (this is a parameter name on
  the consumer, not a runtime attribute).
- A non-existent `runtime._add_event_listener_fn` attribute.

**Action:** Remove the `add_event_listener_fn` property. Document in the prompt that
`runtime.add_event_listener` is the existing public surface and no migration is needed.

### 4. The `# TODO(AD-571)` and `# TODO(AD-673)` comments do not exist

Workspace grep for `TODO\(AD-571\)|TODO\(AD-673\)` across `src/` returns **zero matches**.
The prompt's premise — "Each new wiring module either adds another TODO or copies the
pattern" — is not supported by the current source. The `# TODO(AD-571)` comments described
in `Reviews/README.md` were apparently planned but never landed (or were removed during
the AD-571 / AD-673 builds without recording an AD).

**Action:** Either (a) drop the "remove TODO" workstream entirely, or (b) reframe the
prompt as "audit the AD-571 and AD-673 builds, add the TODO markers that were dropped,
then immediately resolve them via the public properties below." Option (a) is cleaner.

### 5. Real targets are narrower than the prompt claims

Grep across `src/` for `runtime\._(emit_event|emergence_metrics_engine)` shows the actual
work required:

- `runtime._emit_event` — **20+ external call sites** in `startup/finalize.py`,
  `proactive.py`, `cognitive/cognitive_agent.py`, `routers/build.py`. This is the only
  one with a meaningful migration footprint.
- `runtime._emergence_metrics_engine` — exactly **one external access**, at
  `startup/finalize.py:160` inside `_populate_agent_tiers`.

Neither attribute has a `# TODO` marker. The other three names in the prompt
(`_trust_network`, `_router`, `_add_event_listener_fn`) do not exist as private attributes
to begin with.

**Action:** Reduce the prompt's scope to the two real targets:

| Property | Backing attribute | Sites |
|---|---|---|
| `emit_event` | `self._emit_event` | 20+ across startup/finalize.py, proactive.py, cognitive_agent.py, routers/build.py |
| `emergence_metrics_engine` | `self._emergence_metrics_engine` | 1 in startup/finalize.py |

### 6. `emit_event` as a `@property` returning a bound method has a subtle gotcha

If `_emit_event` is defined as a regular method on `ProbOSRuntime` (which it is — see
runtime.py:899, 774, 776 calling `self._emit_event(...)` as a method), then
`self._emit_event` already returns a bound method. A `@property` that returns
`self._emit_event` would create a new bound method on every access. That's harmless for
correctness but annoying for `id()` / equality checks in tests and creates a needless
allocation per call site. The cleaner refactor is to **rename** the method to `emit_event`
(or define a public `emit_event` method that calls the private one), not wrap it in a
property.

**Action:** Replace the `emit_event` property with one of:

- **Rename** `_emit_event` → `emit_event` (cleanest; one-shot migration matching the
  AD's stated philosophy of "no deprecation warnings, one-shot").
- Define `def emit_event(self, *args, **kwargs): return self._emit_event(*args, **kwargs)`
  as a thin public wrapper.

A property is the wrong shape for a callable-returning accessor.

### 7. Codebase invariant test (`test_no_remaining_runtime_underscore_access_in_startup`) needs scope adjustment

The proposed regex is:
```
runtime\._(trust_network|router|emergence_metrics_engine|emit_event|add_event_listener_fn)
```

After the rework above, only `emit_event` and `emergence_metrics_engine` remain. Update
the regex accordingly. Also: the test should scope to `src/probos/` not just
`src/probos/startup/` — the largest concentration of `runtime._emit_event` accesses is in
`proactive.py` and `cognitive_agent.py`, which are not under `startup/`.

---

## Recommended

### R1. Run a verify-first pass against the live runtime before publishing the next revision

Every assertion in the prompt about attribute names should be backed by a grep result
pasted into the prompt. The current draft fails at "verify the exact attribute names by
grepping" — that step was not done before the prompt was written.

### R2. State the scope honestly in the title and problem section

A more accurate title would be "AD-680: Promote `_emit_event` to public + audit
runtime accessor surface." The "five attributes" framing oversells.

### R3. Capture the rationale in DECISIONS.md

The "no deprecation warning, one-shot" choice is worth recording — future ADs that
promote private attributes can cite this precedent.

---

## Nits

- The "Place them grouped together near the top of the class (after `__init__`, before
  `start()`)" instruction has no value once the property count drops to one.
- `Awaitable[None]` in the type signature for `add_event_listener_fn` is inconsistent
  with the actual `add_event_listener` shape — moot once that property is removed.

---

## Verified

- The "no behavioral change" stance is correct *if* the prompt is rescoped to actual
  private attributes.
- The "do not add setters" rule is correct.
- The test-file location (`tests/test_runtime_public_properties.py`) is fine.

---

## Recommended Disposition

**Rewrite or split.** The cleanest path is:

1. **AD-680 (rewritten):** Promote `_emit_event` to a public method (rename or wrapper).
   ~20 call sites. ~3 tests. One commit.
2. **AD-680b (optional, low priority):** Promote `_emergence_metrics_engine` to public
   property. One call site. One test.
3. **Drop entirely:** the trust_network / router / add_event_listener migrations — they
   are no-ops because the public surface already exists.
