# Review: AD-633 v1 — `_wire_predictive_branching` finalize wirer + config seam
**Verdict:** ✅ Approved (self-review)
**Closes the remaining gap on AD-633: substrate already shipped; this prompt wires the finalize seam and adds the Pydantic config. One Recommended sharpening on the engine-config contract.**

## Required (must fix before building)
_None._

## Recommended
1. **The PredictiveBranchingConfig field set covers the test surface but does not include any engine-internal weight knobs (HEBBIAN_WEIGHT, THREAD_ACTIVITY_WEIGHT, etc).** Those are class constants on `PredictionEngine` (engine.py:96-100) — intentionally not config-controlled in v1. The prompt is silent on this. Add one Non-Goal: "Do NOT promote `PredictionEngine.HEBBIAN_WEIGHT` (and siblings) to PredictiveBranchingConfig — those are deliberate class constants, deferred to AD-633k if rebalancing is needed."

## Nits
1. D2's `runtime._idle_speculation_policy = NoOpIdleSpeculationPolicy()` and `runtime._preplay_hook = NoOpPreplayHook()` assign to private-prefixed attributes, but no consumer reads them yet. Worth a comment or AD-reference (`# AD-633f / AD-633g consumer surfaces`) so the next architect knows why they exist on the runtime.
2. The `model_validator(mode="after")` invariant uses `<=` for the threshold ordering — equality is permitted and matches the engine's `_tier_for` cutoffs (which use strict `<`). Correct, but the rationale ("the package's `<` boundaries permit equal thresholds") would help a future reader.
3. Defaults for `cache_max_entries`, `cache_ttl_seconds`, `budget_*` are reasonable but not test-grounded — Builder may discover the integration tests want different values. Mitigated by `enabled=False` default; defaults can be tuned in a successor AD without breaking anyone.

## Verified
- ✅ All package public exports listed at `predictive_branching/__init__.py:7-46`.
- ✅ All five collaborator constructors: `PredictionEngine(*, hebbian_router, ontology, config, circuit_breaker=None)`, `SpeculationCache(*, max_entries, ttl_seconds, emit_event=None)`, `SpeculationBudget(*, tokens_per_window, window_seconds, flush_rate_threshold, flush_rate_window_seconds)`, `AccuracyTracker(*, ring_size)` (with `>= 10` precondition), `SpeculationExecutor(*, sub_task_executor, cache, budget, accuracy_tracker, emit_event=None)`.
- ✅ Test contract at `test_ad633_predictive_branching.py:557-587` (G class):
  - `PredictiveBranchingConfig().enabled is False` — **default-False, contradicts the user request's "enabled: bool = True"; the prompt correctly follows the test.**
  - `_wire_predictive_branching` is sync, kwarg-only, returns `bool`.
- ✅ `runtime.py:632-636` declares the five `Any` stubs with the comment "set by `_wire_predictive_branching`" — the wirer is the agreed seam.
- ✅ The neighbor pattern (`_wire_anomaly_window`, `_wire_task_context`) at `finalize.py:25/105` matches the wirer shape.
- ✅ Tier-2 log-and-degrade invocation in `finalize_startup` matches the AD-673 precedent.

## Risk
LOW. Default-disabled means production behavior unchanged. The construction path is exercised by 2 new tests; the disabled path is already covered by the existing G-class tests.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved — HEBBIAN_WEIGHT frozen-baseline Non-Goal added; v1 scope discipline documented.

### Required / Recommended / Nits
None.

### Verified
- **Recommended #1 landed**: Non-Goal pins `PredictionEngine.HEBBIAN_WEIGHT`, `THREAD_ACTIVITY_WEIGHT` at `engine.py:96-100` as **deliberate frozen baselines for v1**; rebalancing deferred to AD-633k once AD-633e accuracy data justifies tuning surface. Forcing function cited.
- Verified at HEAD: `predictive_branching/engine.py:94-95` shows the constants used at `:192-193`.
- Defaults match published thresholds and test expectations (`enabled=False`).
- Field validators enforce confidence ranges, `accuracy_ring_size >= 10`, monotonic confidence ordering.
- `_wire_predictive_branching` is sync, kwarg-only, returns bool — matches G-class test expectations exactly.
- Defensive: missing `hebbian_router` returns False with WARNING; `sub_task_executor=None` deferred to AD-633j.
- Phantom-API sweep: all 7 imports confirmed at `predictive_branching/__init__.py:7-30`.
- 2 new G-class tests; no duplication.
