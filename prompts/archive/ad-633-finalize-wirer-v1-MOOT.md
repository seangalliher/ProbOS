# AD-633 v1 — `_wire_predictive_branching` finalize wirer + config seam

**Issue:** [#489](https://github.com/seangalliher/ProbOS/issues/489)
**Type:** Architecture Decision (substrate-already-shipped; finalize plumbing only)
**Depends on:** AD-633a/b/c/d/e (engine, cache, budget, executor, accuracy, policy modules — all shipped under `src/probos/cognitive/predictive_branching/`).
**Wave:** 129

## Goal

The AD-633 Predictive Cognitive Branching package shipped its substrate (engine, cache, budget, executor, accuracy tracker, policy seams). Wire-up was deferred — the finalize seam `_wire_predictive_branching` is referenced by `tests/test_ad633_predictive_branching.py:629` and the runtime stubs at `runtime.py:632–636` but the function does not exist in `startup/finalize.py`. There is also no `PredictiveBranchingConfig` Pydantic model. AD-633 v1 (this prompt) closes those two gaps. No business logic in the package changes.

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/cognitive/predictive_branching/__init__.py:7-30` exports `PredictionEngine`, `SpeculationCache`, `SpeculationBudget`, `SpeculationExecutor`, `AccuracyTracker`, `IdleSpeculationPolicy`, `NoOpIdleSpeculationPolicy`, `PreplayHook`, `NoOpPreplayHook`, `ConfidenceTier`, `PredictionDescriptor`, `compute_signature`.
- ✅ `src/probos/cognitive/predictive_branching/engine.py:103-114` `PredictionEngine.__init__(*, hebbian_router, ontology, config, circuit_breaker=None)` — the wirer must construct with these kwargs; the `config` arg here is the package's `PredictiveBranchingConfig` (engine reads `cfg.cheap_tier_min_confidence`, `cfg.standard_tier_min_confidence`, `cfg.anticipatory_tier_min_confidence` at `engine.py:218-226`).
- ✅ `src/probos/cognitive/predictive_branching/budget.py:43-58` `SpeculationBudget.__init__(*, tokens_per_window, window_seconds, flush_rate_threshold, flush_rate_window_seconds)` — these are the four budget knobs the package reads.
- ✅ `src/probos/cognitive/predictive_branching/cache.py:39-50` `SpeculationCache.__init__(*, max_entries, ttl_seconds, emit_event=None)`.
- ✅ `src/probos/cognitive/predictive_branching/accuracy.py:38-43` `AccuracyTracker.__init__(*, ring_size)` (must be `>= 10`).
- ✅ `src/probos/cognitive/predictive_branching/executor.py:42-57` `SpeculationExecutor.__init__(*, sub_task_executor, cache, budget, accuracy_tracker, emit_event=None)`.
- ✅ `src/probos/cognitive/predictive_branching/policy.py:43-57` `NoOpIdleSpeculationPolicy()` and `NoOpPreplayHook()` are zero-arg defaults; both ship today as the v1 stable defaults until AD-633f-1 / AD-633g-1 land.
- ✅ `src/probos/runtime.py:632-636` declares the stubs:
  ```
  self.prediction_engine: Any = None
  self.speculation_cache: Any = None
  self.speculation_executor: Any = None
  self.speculation_budget: Any = None
  self.accuracy_tracker: Any = None
  ```
  with the comment `# AD-633: Predictive cognitive branching (set by _wire_predictive_branching)` — the wirer is the agreed seam.
- ✅ `tests/test_ad633_predictive_branching.py:557-587` (Class G — TestConfigAndWiring) asserts:
  - `PredictiveBranchingConfig().enabled is False` — **default is False, not True** (verify-first finding: contradicts the original dispatch's `enabled: bool = True`; this prompt follows the test).
  - `SystemConfig().predictive_branching.enabled is False`.
  - `_wire_predictive_branching(runtime=runtime, config=config)` is called as a kwarg-only **sync** function returning **`bool`**; returns `False` when disabled and leaves all five runtime attributes `None`.
- ✅ `tests/test_ad633_predictive_branching.py:21-37` imports `PredictiveBranchingConfig` and `SystemConfig` from `probos.config` — neither exists yet for `predictive_branching` (`grep "PredictiveBranchingConfig" src/probos/config.py` returns 0 hits at HEAD).
- ✅ `src/probos/startup/finalize.py:25-79` shows the canonical sync wirer shape: `def _wire_anomaly_window(*, runtime: Any, config: "SystemConfig") -> bool:` — early-return on disabled, construct types, assign to runtime attributes, return `True` on success / `False` on skip.
- ✅ `src/probos/startup/finalize.py:1107` is the `return FinalizationResult(...)` statement; new wirer invocation must be inserted before it. The existing `_wire_tiered_knowledge_loader` invocation at `:283` is a good neighbor: it follows the proactive-loop block and precedes the records-store wiring.
- ✅ `src/probos/config.py:1486-1565` defines `class SystemConfig(BaseModel)`; the new `predictive_branching` field is added adjacent to `anomaly_window` (line 1535) and `task_context` (line 1547), all of which use the bare-default pattern (`X: XConfig = XConfig()`). This prompt mirrors that pattern.
- ✅ `_cfg()` helper in the test file (line 74) calls `PredictiveBranchingConfig(**overrides)` with no defaults supplied — every field on the config must have a sensible default (per `.github/copilot-instructions.md` Configuration Standards: "every field has a sensible default — ProbOS must boot with zero config").

## Scope

Three small additive changes:

1. New `PredictiveBranchingConfig` Pydantic model in `config.py`, wired onto `SystemConfig.predictive_branching`.
2. New `_wire_predictive_branching` sync wirer in `startup/finalize.py`, invoked from `finalize_startup`.
3. Two focused tests for the wirer (the existing G-class tests in `test_ad633_predictive_branching.py:557-587` already cover the `enabled=False` skip path; this prompt adds the `enabled=True` constructed-types path that those tests do not cover).

Do **not** modify any module under `src/probos/cognitive/predictive_branching/`. Do **not** touch the existing 33 tests in `test_ad633_predictive_branching.py`. Do **not** wire the SubTaskExecutor — `SpeculationExecutor` accepts `sub_task_executor=None` at `executor.py:38-40` and that is the safe v1 default.

## Deliverables

### D1. `PredictiveBranchingConfig` Pydantic model in `src/probos/config.py`

Insert adjacent to `AnomalyWindowConfig` (around `config.py:801`) — a sibling cognitive-substrate config class. Mirror the AD-673 anomaly-window precedent.

```python
class PredictiveBranchingConfig(BaseModel):
    """AD-633: Predictive cognitive branching — speculation engine config.

    Defaults match the package's published thresholds and the test
    expectations in tests/test_ad633_predictive_branching.py. ``enabled``
    is False in v1: the substrate is shipped but operational dispatch
    requires deliberate opt-in (per AD-633e accuracy data forcing function).
    Flip to True only after AD-633f-1 / AD-633g-1 readiness signals.
    """

    enabled: bool = False

    # --- Tier confidence thresholds (engine.py:218-226) ---
    cheap_tier_min_confidence: float = 0.30
    standard_tier_min_confidence: float = 0.60
    anticipatory_tier_min_confidence: float = 0.85

    # --- Cache (cache.py:39-50) ---
    cache_max_entries: int = 256
    cache_ttl_seconds: float = 300.0  # 5 min — matches engine THREAD_ACTIVITY_WINDOW

    # --- Budget (budget.py:43-58) ---
    budget_tokens_per_window: int = 10_000
    budget_window_seconds: float = 300.0
    budget_flush_rate_threshold: float = 0.30
    budget_flush_rate_window_seconds: float = 3600.0  # 1 hour rolling

    # --- Accuracy tracker (accuracy.py:38-43; ring_size must be >= 10) ---
    accuracy_ring_size: int = 100
```

Add `pydantic.field_validator`s:

- `cheap_tier_min_confidence`, `standard_tier_min_confidence`, `anticipatory_tier_min_confidence` ∈ `[0.0, 1.0]`.
- `cache_max_entries >= 1`.
- `cache_ttl_seconds >= 1.0`.
- `budget_tokens_per_window >= 0`.
- `budget_window_seconds >= 1.0`.
- `budget_flush_rate_threshold ∈ [0.0, 1.0]`.
- `budget_flush_rate_window_seconds > 0`.
- `accuracy_ring_size >= 10` (matches `AccuracyTracker.__init__` precondition at `accuracy.py:39`).

A `model_validator(mode="after")` invariant: `cheap_tier_min_confidence <= standard_tier_min_confidence <= anticipatory_tier_min_confidence`.

Wire onto `SystemConfig` (insert adjacent to `anomaly_window: AnomalyWindowConfig = AnomalyWindowConfig()  # AD-673` at `config.py:1535`):

```python
predictive_branching: PredictiveBranchingConfig = PredictiveBranchingConfig()  # AD-633
```

### D2. `_wire_predictive_branching` in `src/probos/startup/finalize.py`

Insert immediately after `_wire_task_context` (currently ends at `config.py finalize.py:131`). Sync function, kwarg-only, returns `bool` — matches the assertion shape in `tests/test_ad633_predictive_branching.py:577` (`result = _wire_predictive_branching(...); assert result is False`).

```python
def _wire_predictive_branching(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-633: Wire predictive cognitive branching seams onto the runtime.

    Returns True iff the engine and its collaborators were constructed and
    assigned to ``runtime.{prediction_engine, speculation_cache,
    speculation_budget, speculation_executor, accuracy_tracker}``.
    Returns False when the feature is disabled in config; in that case the
    five runtime attributes remain at their startup defaults (None).

    The SubTaskExecutor wiring is deliberately deferred: ``SpeculationExecutor``
    accepts ``sub_task_executor=None`` and ``dispatch()`` returns None in that
    case (executor.py:38-40 + executor tests). A future AD-633j connects the
    real executor once AD-632 is universally on.
    """
    cfg = getattr(config, "predictive_branching", None)
    if cfg is None or not cfg.enabled:
        return False

    from probos.cognitive.predictive_branching import (
        AccuracyTracker,
        NoOpIdleSpeculationPolicy,
        NoOpPreplayHook,
        PredictionEngine,
        SpeculationBudget,
        SpeculationCache,
        SpeculationExecutor,
    )

    hebbian_router = getattr(runtime, "hebbian_router", None)
    ontology = getattr(runtime, "ontology", None)
    if hebbian_router is None:
        # Hard requirement of PredictionEngine — degrade rather than crash.
        logger.warning(
            "AD-633: hebbian_router missing on runtime; predictive branching disabled"
        )
        return False

    emit_event_fn: Callable[[str, dict[str, Any]], None] | None = getattr(
        runtime, "_emit_event", None
    )

    cache = SpeculationCache(
        max_entries=cfg.cache_max_entries,
        ttl_seconds=cfg.cache_ttl_seconds,
        emit_event=emit_event_fn,
    )
    budget = SpeculationBudget(
        tokens_per_window=cfg.budget_tokens_per_window,
        window_seconds=cfg.budget_window_seconds,
        flush_rate_threshold=cfg.budget_flush_rate_threshold,
        flush_rate_window_seconds=cfg.budget_flush_rate_window_seconds,
    )
    accuracy_tracker = AccuracyTracker(ring_size=cfg.accuracy_ring_size)
    engine = PredictionEngine(
        hebbian_router=hebbian_router,
        ontology=ontology,
        config=cfg,
        circuit_breaker=getattr(runtime, "_circuit_breaker", None),
    )
    executor = SpeculationExecutor(
        sub_task_executor=None,  # AD-633j will replace this with the real executor
        cache=cache,
        budget=budget,
        accuracy_tracker=accuracy_tracker,
        emit_event=emit_event_fn,
    )

    runtime.prediction_engine = engine
    runtime.speculation_cache = cache
    runtime.speculation_budget = budget
    runtime.speculation_executor = executor
    runtime.accuracy_tracker = accuracy_tracker

    # Default v1 policy seams. Concrete impls land in AD-633f-1 / AD-633g-1
    # once accuracy + dream-step-registry forcing functions trigger.
    runtime._idle_speculation_policy = NoOpIdleSpeculationPolicy()
    runtime._preplay_hook = NoOpPreplayHook()

    logger.info(
        "Startup [predictive_branching]: wired engine + cache(max=%d, ttl=%.1fs) + "
        "budget(%d tok/%.1fs) + accuracy(ring=%d)",
        cfg.cache_max_entries,
        cfg.cache_ttl_seconds,
        cfg.budget_tokens_per_window,
        cfg.budget_window_seconds,
        cfg.accuracy_ring_size,
    )
    return True
```

### D3. Invocation in `finalize_startup`

In `src/probos/startup/finalize.py` `finalize_startup`, immediately after the `_wire_task_context` invocation block (around line 287–289), add:

```python
try:
    _wire_predictive_branching(runtime=runtime, config=config)
except Exception:
    logger.warning(
        "AD-633: _wire_predictive_branching raised; predictive branching disabled",
        exc_info=True,
    )
```

Tier-2 log-and-degrade. Never raise — a broken speculation seam must not block startup.

### D4. Tests in `tests/test_ad633_predictive_branching.py`

Add **two** focused tests in the existing `TestConfigAndWiring` class (Class G). The existing 2 G-tests already cover defaults + disabled-skip. The new 2 tests cover the enabled-construction path. Total: 4 G-tests (35 file-total, up from 33).

```python
def test_wirer_constructs_all_five_seams_when_enabled(self) -> None:
    from probos.startup.finalize import _wire_predictive_branching
    from probos.cognitive.predictive_branching import (
        AccuracyTracker, PredictionEngine, SpeculationBudget,
        SpeculationCache, SpeculationExecutor,
    )

    runtime = SimpleNamespace(
        hebbian_router=_StubHebbian(),
        ontology=_StubOntology(),
        prediction_engine=None,
        speculation_cache=None,
        speculation_budget=None,
        speculation_executor=None,
        accuracy_tracker=None,
        _emit_event=lambda et, d: None,
        _circuit_breaker=None,
    )
    config = SystemConfig(predictive_branching=PredictiveBranchingConfig(enabled=True))

    result = _wire_predictive_branching(runtime=runtime, config=config)

    assert result is True
    assert isinstance(runtime.prediction_engine, PredictionEngine)
    assert isinstance(runtime.speculation_cache, SpeculationCache)
    assert isinstance(runtime.speculation_budget, SpeculationBudget)
    assert isinstance(runtime.speculation_executor, SpeculationExecutor)
    assert isinstance(runtime.accuracy_tracker, AccuracyTracker)


def test_wirer_returns_false_when_hebbian_router_missing(self) -> None:
    from probos.startup.finalize import _wire_predictive_branching

    runtime = SimpleNamespace(
        hebbian_router=None,
        ontology=_StubOntology(),
        prediction_engine=None,
        speculation_cache=None,
        speculation_budget=None,
        speculation_executor=None,
        accuracy_tracker=None,
    )
    config = SystemConfig(predictive_branching=PredictiveBranchingConfig(enabled=True))

    result = _wire_predictive_branching(runtime=runtime, config=config)

    assert result is False
    assert runtime.prediction_engine is None
```

The existing skip-path test at `:577` (`test_wirer_no_op_when_disabled`) already covers the `enabled=False` case — do **not** duplicate.

## Non-Goals

- Do NOT promote `PredictionEngine.HEBBIAN_WEIGHT`, `THREAD_ACTIVITY_WEIGHT`, or any of the engine's class-constant weights (engine.py:96-100) to `PredictiveBranchingConfig`. Those are **deliberate class constants** in v1 — the substrate ships them frozen so accuracy data accumulates against a known baseline. Rebalancing to config-driven weights is deferred to AD-633k once AD-633e accuracy data justifies the tuning surface.
- Do NOT modify any module under `src/probos/cognitive/predictive_branching/`.
- Do NOT wire the real `SubTaskExecutor` into `SpeculationExecutor` — deferred to AD-633j.
- Do NOT register operational hooks in `cognitive_agent._decide_via_llm` — the existing AD-633d hook is in place; this prompt only constructs the seams.
- Do NOT add a slash command, HXI surface, or introspection panel.
- Do NOT change `BaseAgent`, `IntentMessage`, `RuntimeProtocol`.
- Do NOT replace the runtime stubs at `runtime.py:632-636` with typed attributes — the `Any` types are intentional during incremental rollout.

## Acceptance

- Focused: `pytest tests/test_ad633_predictive_branching.py -v -n 0` — 35/35 pass (33 existing + 2 new).
- Full gate: `pytest tests/ -q -n 16 --dist=loadfile` — green or only environmental flakes.
- `git diff` shows changes only in: `src/probos/config.py`, `src/probos/startup/finalize.py`, `tests/test_ad633_predictive_branching.py`. No new files; no edits under `src/probos/cognitive/predictive_branching/`; no edits to `runtime.py`.
- `runtime.prediction_engine` (and the four siblings) remain `None` when `predictive_branching.enabled=False` — verified by the existing `test_wirer_no_op_when_disabled`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Tracking

- Closes [#489](https://github.com/seangalliher/ProbOS/issues/489).
- DECISIONS.md entry stub: `### AD-633 — Predictive Cognitive Branching finalize wirer + config seam` — wired the substrate (engine, cache, budget, executor, accuracy tracker, no-op policy seams) shipped under `cognitive/predictive_branching/` into the finalize phase; introduces `PredictiveBranchingConfig` (default-disabled, opt-in until AD-633e accuracy data justifies the energy cost).

## Revision (2026-05-08)

- **Recommended #1 applied**: Added a Non-Goal pinning `PredictionEngine.HEBBIAN_WEIGHT`, `THREAD_ACTIVITY_WEIGHT`, and the other class-constant weights at `engine.py:96-100` as deliberate frozen baselines for v1 — not promoted to `PredictiveBranchingConfig`. Rebalancing is deferred to AD-633k once AD-633e accuracy data justifies the tuning surface.
