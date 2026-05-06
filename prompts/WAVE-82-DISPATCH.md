# WAVE 82 DISPATCH — AD-633 v1 Predictive Cognitive Branching (6 OSS sub-ADs in one build)

**Wave id:** 82
**Umbrella AD:** AD-633 (Predictive Cognitive Branching — pre-computation, anticipatory reasoning, goal origination)
**OSS sub-ADs in scope (concrete build):** AD-633a (Prediction Engine), AD-633b (Speculation Executor + Cache), AD-633c (Speculation Budget), AD-633d (Decision Pipeline Integration), AD-633e (Prediction Accuracy Tracking), AD-633h (Prediction Error as Emergence Signal — emit side)
**OSS sub-ADs in scope (Protocol seam only):** AD-633f (Anticipatory Reasoning — `IdleSpeculationPolicy` Protocol + default no-op), AD-633g (Preplay Dream Step — `PreplayHook` Protocol + default no-op)
**OSS sub-ADs deferred (forcing function documented in module docstring):** AD-633i (Cognitive JIT compilation — consumer is AD-531–539's surface; verified absent at HEAD)
**Closes:** GH issue #228
**HEAD at draft:** `d85611f` (post-Wave-81)
**Baseline test count:** 11580 → expected **≥ 11615** pytest (Δ ≥ +35)
**Builder required:** true (one focused build prompt)
**AD numbering:** Highest stem in trackers at draft is **AD-696** (Wave 72). AD-633 is the umbrella AD pre-allocated at GH #228 creation; sub-ADs 633a–i are pre-allocated. **No new AD number is minted by this wave.**

## Verdict

Verify-first against HEAD `d85611f` confirms the substrate AD-633 v1 needs is in place:

- **AD-573 working memory:** `src/probos/cognitive/agent_working_memory.py:39` `WorkingMemoryEntry`; `cognitive_agent.py:163-164` per-agent `AgentWorkingMemory` instance; public `working_memory` property (line 266); `has_engagement(engagement_type)` (line 803). Speculation cache reuses this surface for engagement signals.
- **AD-632 sub-task protocol:** `src/probos/cognitive/sub_task.py` `SubTaskExecutor` (line 174), `can_execute(chain)` (217), `async execute(...)` (224), `SubTaskType.{QUERY,ANALYZE,COMPOSE,EVALUATE,REFLECT}` (29). `runtime._sub_task_executor` is set in `finalize.py:2427` and attached to agents via `set_sub_task_executor()` (`cognitive_agent.py:220`). v1's SpeculationExecutor wraps this — speculative chains dispatch through the same executor, separate token accounting.
- **HebbianRouter:** `mesh/routing.py:251` `get_weight(source, target, rel_type=None) -> float`. Public read API; deterministic. Engine consumes for confidence component.
- **Ontology:** `ontology/departments.py:65` `get_agent_department(agent_type)`, `:85` `get_post_for_agent(agent_type)`. Engine consumes for department-membership component.
- **Circuit breaker:** `proactive.py` `_circuit_breaker.should_allow_think(agent.id)` (line 540) — Engine reads circuit breaker status as a hard gate (do-not-speculate when OPEN).
- **EarnedAgency / trust tier:** `src/probos/earned_agency.py` `AgencyLevel`; `Rank.from_trust(score)` used in `proactive.py:533` for proactive-think gating. v1's SpeculationBudget reads agency level to gate Standard-tier speculation.
- **AD-654c Dispatcher / AD-581 DepartmentDispatcher:** present at HEAD post-Wave-81. v1 does NOT touch these — speculation is per-agent intra-process; no routing decision involved.
- **AD-557 EmergenceMetricsEngine:** `cognitive/emergence_metrics.py:352`. **Has no `record_signal`-style public API** at HEAD (verified — only `compute_emergence_metrics()` and snapshot getters). v1 emits `PREDICTION_ERROR_RECORDED` events; AD-557 listener integration is genuinely deferred (no consumer signal yet) — same Protocol-seam pattern Wave 81 used for the Standing Orders predicate.
- **`_decide_via_llm()` hook site:** `cognitive_agent.py:1410` `async def _decide_via_llm(self, observation: dict) -> dict`. v1's pre-LLM cache check inserts a single early-return shaped exactly like the AD-534b `chain_result` early-return at lines 1383-1389.
- **ProactiveCognitiveLoop:** `proactive.py:153` `class ProactiveCognitiveLoop`, `_run_cycle()` at 491. The idle-cycle integration AD-633f calls for is non-trivial — proper integration requires a new policy decision inside `_run_cycle` AFTER agency/cooldown/circuit-breaker gates, plus a speculation-dispatch path that doesn't bleed into operational tokens. v1 ships the **Protocol seam and default no-op policy only**; concrete idle-time speculation is the AD-633f-1 follow-on. This honors Captain rule because the consumer signal (ProactiveCognitiveLoop integration tests + a working idle scheduler that can demonstrate non-trivial accuracy gain) hasn't materialized at HEAD.
- **Dream adapter Step 13:** `src/probos/dream_adapter.py` exposes `on_pre_dream`/`on_post_dream`/`on_post_micro_dream` hooks but no extensible "step N" registry. Adding a Step 13 forward-simulation pass requires either a new step registry OR injecting the preplay logic into `on_post_dream`. v1 ships the **`PreplayHook` Protocol seam and default no-op**; concrete forward-simulation logic + dream-step wiring is the AD-633g-1 follow-on. Same Protocol-seam justification.
- **AD-531–539 Cognitive JIT consumer:** verified absent at HEAD via `grep "class.*JIT|cognitive_jit"` — `learned_shortcuts/protocol.py:18` references `'cognitive_jit'` as a *future* backend identifier in the LearnedShortcutBackend Protocol. The AD-633i compile-predictions-into-procedures surface has no consumer to subscribe to the predictions stream. **AD-633i is hard-deferred** with forcing function documented in the engine module docstring; this is the only sub-AD where deferral is unavoidable per the Captain rule (consumer doesn't exist).

AD-633 v1 (six concrete sub-ADs + two Protocol seams + one hard-deferred-with-forcing-function) is **fully buildable in one wave**. Captain rule "don't defer unless no choice" is honored: every sub-AD with a consumer at HEAD ships concretely or as Protocol seam in v1; only AD-633i (no consumer) is deferred.

| GH #228 sub-AD | Wave 82 action |
|---|---|
| AD-633a Prediction Engine Foundation (deterministic confidence scoring) | **BUILD.** New `src/probos/cognitive/predictive_branching/engine.py`. `PredictionEngine.score(*, agent_id, agent_type, observation) -> PredictionDescriptor`. Confidence computed deterministically as weighted sum: `0.4 × hebbian_weight + 0.2 × recent_thread_activity + 0.2 × department_membership + 0.2 × working_memory_engagement_match`. Confidence bucketed into `ConfidenceTier.{ZERO_COST, CHEAP, STANDARD, ANTICIPATORY}`. Circuit-breaker OPEN forces tier ZERO_COST regardless of confidence. Pure decision — no I/O, no event emission. |
| AD-633b Speculation Executor + Cache (Working Memory integration) | **BUILD.** New `src/probos/cognitive/predictive_branching/executor.py` (`SpeculationExecutor` wraps `runtime._sub_task_executor`; speculative chains tagged `source="speculation"`; tokens accounted to speculation budget pool, NOT operational pool) + new `src/probos/cognitive/predictive_branching/cache.py` (`SpeculationCache` TTL+FIFO bounded; key `(agent_id, intent_type, signature_hash)`; `lookup() / store() / evict() / flush_expired()`; emits `PREDICTION_HIT` / `PREDICTION_FLUSHED` events). |
| AD-633c Speculation Budget Management (separate from operational budget) | **BUILD.** New `src/probos/cognitive/predictive_branching/budget.py`. `SpeculationBudget(*, tokens_per_window, window_seconds, agency_gate)`. Per-agent rolling window; `try_reserve(tokens, agent_agency_level) -> bool`; `record_consumption(tokens)`; `record_outcome(*, hit: bool)`; **flush-rate feedback**: when 1-hour rolling flush rate >30%, halves the agent's speculation budget for the next window (auto-recovery on next window if flush rate drops). EarnedAgency `AgencyLevel` gates Standard-tier speculation (Cheap allowed at all levels; Standard requires `EXECUTING` or above; Anticipatory is gated by AD-633f Protocol — no concrete consumer in v1). |
| AD-633d Decision Pipeline Integration (consume pre-computed results) | **BUILD.** Modify `src/probos/cognitive/cognitive_agent.py:_decide_via_llm()` — single pre-LLM cache check at the function head: compute observation signature → `runtime.speculation_cache.lookup(...)` → on hit, prepend cached analysis to `observation["_speculation_prefetch"]` and emit `PREDICTION_HIT`; on miss, emit `PREDICTION_MISS` and proceed to LLM. The cached analysis is **not a decision** — it's pre-computed observation context (sub-task results) that the LLM still consumes. This shape mirrors AD-585 `_knowledge_ambient` injection (lines 1428-1444). Tier-2 log-and-degrade: any cache failure logs WARNING and proceeds normally. |
| AD-633e Prediction Accuracy Tracking (feedback loop) | **BUILD.** New `src/probos/cognitive/predictive_branching/accuracy.py`. `AccuracyTracker` per-agent ring buffer of last-N prediction outcomes (`PredictionOutcome.{HIT, MISS, FLUSHED, ERROR}`). `record(*, agent_id, outcome)`, `get_rates(agent_id) -> AccuracyRates(hit_rate, miss_rate, flush_rate, error_rate, sample_count)`. Drives AD-633c flush-rate feedback. Pure data-path — emits no events itself; consumes events emitted by cache/executor. |
| AD-633h Prediction Error as Emergence Signal | **BUILD (emit side only).** New `EventType.PREDICTION_ERROR_RECORDED` emitted by `SpeculationExecutor` when actual outcome diverges from predicted (post-decision check via cache flush + observed action mismatch). AD-557 listener integration is the documented follow-on AD-633h-1 (no consumer signal yet — `EmergenceMetricsEngine` has no `record_signal` API at HEAD). |
| AD-633f Anticipatory Reasoning Mode | **PROTOCOL SEAM.** New `src/probos/cognitive/predictive_branching/policy.py`: `IdleSpeculationPolicy` Protocol (`should_speculate_now(*, agent_id, runtime) -> SpeculationRequest \| None`). v1 ships `NoOpIdleSpeculationPolicy` (always returns `None`). ProactiveCognitiveLoop integration is **not** wired in v1 — `runtime.speculation_executor` exposes `dispatch_anticipatory(request)` so the future idle-cycle subscriber has a stable target. Forcing function: AD-633f-1 once accuracy data shows ≥10% hit rate for opportunistic predictions. |
| AD-633g Preplay Dream Step (forward simulation during dream) | **PROTOCOL SEAM.** Same `policy.py` adds `PreplayHook` Protocol (`generate_preplay_predictions(*, dream_report, runtime) -> list[SpeculationRequest]`). v1 ships `NoOpPreplayHook`. `dream_adapter` integration is **not** wired in v1 — adding a Step 13 to the dream pipeline requires either a step registry refactor or an `on_post_dream` extension; both are scope-creep here. Forcing function: AD-633g-1 once dream consolidation surfaces a stable list-of-implementation-intentions output. |
| AD-633i Cognitive JIT compilation (predictions → procedures) | **HARD DEFER.** Forcing function in engine module docstring. Verified absent at HEAD: `learned_shortcuts/protocol.py:18` calls JIT a *future* backend; no `class CognitiveJIT`, no `runtime.cognitive_jit`. AD-633i ships when AD-531–539 lands a JIT consumer. v1 emits the existing `PREDICTION_HIT` events that JIT will subscribe to — no additional surface needed. |
| Pydantic config | **BUILD.** `PredictiveBranchingConfig` Pydantic model + field on `SystemConfig`. Default-False (operator opt-in — speculation actually consumes tokens, AD-695 default-False precedent applies). |
| Finalize wirer | **BUILD.** `_wire_predictive_branching(*, runtime, config) -> bool` mirrors `_wire_hybrid_dispatch` shape. Gated on `runtime.hebbian_router` AND `runtime.ontology` AND `runtime._sub_task_executor` (private — tier-2 log-and-degrade if absent; *not* a request to expose it publicly in this wave — that's a separate AD-632j candidate). Sets `runtime.prediction_engine`, `runtime.speculation_cache`, `runtime.speculation_executor`, `runtime.speculation_budget`, `runtime.accuracy_tracker` as public attributes (Wave 5 conv #1). |

## Reframe decision (Captain rule applied)

**Six-of-nine concrete + two Protocol seams + one hard-defer. No reframe avoidable.**

Three things that LOOK like deferrals but aren't:

1. **AD-633f / AD-633g shipped as Protocol seams, not punted.** The umbrella's two complex consumer integrations (idle-cycle anticipatory speculation; dream Step 13 preplay) require subscriber surfaces that aren't ready at HEAD. ProactiveCognitiveLoop's idle integration needs accuracy-tracking data to drive a non-trivial policy (without that, the policy IS no-op — shipping idle integration without data means shipping unreachable code paths). Dream adapter has no step-registry surface; adding one is a separate AD by itself. Same Protocol-seam pattern Wave 81 used for `StandingOrderPredicate` and dream-cycle threshold auto-tuning. Both Protocols + default no-ops + stable dispatch entry points (`runtime.speculation_executor.dispatch_anticipatory(request)`) ship in v1 — when consumer signal arrives, the policy implementation lands without disturbing the engine.

2. **AD-633h "feeds emergence metrics" ships as event-emit only.** `EmergenceMetricsEngine` has no `record_signal()` / `add_signal()` / `feed_prediction_error()` API at HEAD (verified by `grep "def record\|def update\|def feed\|def add_signal" src/probos/cognitive/emergence_metrics.py` — only PID/snapshot computation). Adding such an API on AD-557 to consume predictions errors is its own AD. v1 emits `PREDICTION_ERROR_RECORDED` events; AD-557 wiring is AD-633h-1.

3. **AD-633i "JIT compilation of predictions" hard-deferred.** Captain rule explicitly allows "unless no choice." `learned_shortcuts/protocol.py:18` documents `'cognitive_jit'` as *future*. There is no `class CognitiveJIT`, no `runtime.cognitive_jit`, no consumer of "repeated predictions → procedures" anywhere in `src/probos/`. Building AD-633i in v1 means writing a producer for a non-existent consumer — exactly the unreachable-code anti-pattern. AD-633i ships when AD-531–539 lands; v1 emits events JIT will subscribe to.

GH #228 closure note: "Closed by Wave 82 (six concrete OSS sub-ADs 633a/b/c/d/e/h + two Protocol seams 633f/g). AD-633i hard-deferred until AD-531–539 Cognitive JIT consumer ships. No premium-feature specs (umbrella is fully OSS). AD-633h AD-557 listener, AD-633f idle-cycle integration, AD-633g dream Step 13, and AD-633i JIT compilation all ship as forcing-function follow-ons (633f-1, 633g-1, 633h-1, 633i)."

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  d85611f

# AD-573 working memory substrate (verified shipped):
src/probos/cognitive/agent_working_memory.py:39    # @dataclass WorkingMemoryEntry
src/probos/cognitive/agent_working_memory.py:803   # def has_engagement(engagement_type=None) -> bool
src/probos/cognitive/agent_working_memory.py:812   # def get_engagement(engagement_id) -> ActiveEngagement | None
src/probos/cognitive/cognitive_agent.py:163-164    # AgentWorkingMemory instance per CognitiveAgent
src/probos/cognitive/cognitive_agent.py:266        # @property working_memory

# AD-632 sub-task protocol (verified shipped):
src/probos/cognitive/sub_task.py:29-35     # SubTaskType enum: QUERY/ANALYZE/COMPOSE/EVALUATE/REFLECT
src/probos/cognitive/sub_task.py:43        # @dataclass(frozen=True) SubTaskSpec
src/probos/cognitive/sub_task.py:71        # @dataclass SubTaskChain(steps, chain_timeout_ms, fallback, source)
src/probos/cognitive/sub_task.py:84        # SubTaskHandler Protocol
src/probos/cognitive/sub_task.py:174       # class SubTaskExecutor
src/probos/cognitive/sub_task.py:217       # def can_execute(chain) -> bool
src/probos/cognitive/sub_task.py:224       # async def execute(...)
src/probos/cognitive/cognitive_agent.py:170     # self._sub_task_executor = None
src/probos/cognitive/cognitive_agent.py:220-222  # def set_sub_task_executor(executor)
src/probos/startup/finalize.py:2388-2443   # _wire SubTaskExecutor block; runtime._sub_task_executor (private at HEAD)

# HebbianRouter (verified — same surface used in Wave 81):
src/probos/mesh/routing.py:251-260   # def get_weight(source, target, rel_type=None) -> float

# Ontology (verified shipped):
src/probos/ontology/departments.py:65-72   # get_agent_department(agent_type) -> str | None
src/probos/ontology/departments.py:85-90   # get_post_for_agent(agent_type) -> Post | None

# Circuit breaker (verified shipped):
src/probos/proactive.py:540   # self._circuit_breaker.should_allow_think(agent.id)
# AD-488 _CircuitBreaker exposes should_allow_think(); reused as hard gate.

# Earned Agency / Rank gating (verified shipped):
src/probos/earned_agency.py:1     # "AD-357 Earned Agency"
src/probos/earned_agency.py:12    # AgencyLevel enum
src/probos/proactive.py:533       # rank = Rank.from_trust(trust_score); can_think_proactively(rank)

# Decision pipeline integration site (verified shipped):
src/probos/cognitive/cognitive_agent.py:1410   # async def _decide_via_llm(self, observation: dict) -> dict
src/probos/cognitive/cognitive_agent.py:1383-1389  # AD-534b chain_result early-return — exact precedent for v1 cache-check shape
src/probos/cognitive/cognitive_agent.py:1428-1444  # AD-585 _knowledge_ambient injection — exact precedent for _speculation_prefetch injection

# AD-557 emergence metrics (verified — no record_signal API):
src/probos/cognitive/emergence_metrics.py:352  # class EmergenceMetricsEngine
src/probos/cognitive/emergence_metrics.py:355  # __init__(config: EmergenceMetricsConfig | None = None)
src/probos/cognitive/emergence_metrics.py:368  # latest_snapshot()
src/probos/cognitive/emergence_metrics.py:373  # snapshots()
src/probos/cognitive/emergence_metrics.py:377  # async compute_emergence_metrics(...)
# 0 hits for "def record_signal | def add_signal | def feed_prediction_error" — confirms event-emit-only path for AD-633h v1.

# Dream adapter (verified — no step registry):
src/probos/dream_adapter.py:125  # on_pre_dream
src/probos/dream_adapter.py:140  # on_post_dream(dream_report)
src/probos/dream_adapter.py:298  # on_post_micro_dream
# 0 hits for "step_13 | preplay" — confirms PreplayHook seam-only path.

# Cognitive JIT (verified absent — AD-633i defer justified):
src/probos/cognitive/learned_shortcuts/protocol.py:18  # "Backend identifier, e.g. 'workflow_cache' / 'cognitive_jit'."
# 0 hits for "class CognitiveJIT | runtime.cognitive_jit | cognitive_jit_compiler".

# Event surface (verified collision-free):
src/probos/events.py:300-301  SUB_TASK_COMPLETED / SUB_TASK_CHAIN_COMPLETED  # AD-632 (orthogonal)
src/probos/events.py:315-316  HYBRID_DISPATCH_DIRECT / HYBRID_DISPATCH_BROADCAST  # AD-581 (Wave 81)
# 0 hits for PREDICTION_HIT | PREDICTION_MISS | PREDICTION_FLUSHED | PREDICTION_ERROR_RECORDED — all greenfield names safe to add.

# Config insertion anchor:
src/probos/config.py:1876   # class EmergenceMetricsConfig (AD-557) — adjacent insertion zone
src/probos/config.py:2469   # emergence_metrics field on SystemConfig
src/probos/config.py:2486   # working_memory: WorkingMemoryConfig (AD-573)
# AD-633 inserts PredictiveBranchingConfig adjacent to WorkingMemoryConfig (~2486-2490)
# and the field on SystemConfig adjacent to working_memory (~2486).

# Finalize wiring anchor:
src/probos/startup/finalize.py:715-758    # _wire_consultation_dispatch — same shape precedent
src/probos/startup/finalize.py:762-?      # _wire_hybrid_dispatch (AD-581) — same shape precedent
src/probos/startup/finalize.py:2388-2443  # _wire SubTaskExecutor block — _wire_predictive_branching invocation goes IMMEDIATELY AFTER this block (depends on runtime._sub_task_executor being set)
```

## Files this wave produces

- `prompts/WAVE-82-DISPATCH.md` (this file)
- `prompts/ad-633-predictive-branching-v1.md` (single build prompt; sections 0–9)
- `prompts/wave-plan.yaml` (append id `"82"` entry, depends_on `["81"]`, status `pending`)

## Builder will modify

| File | Change |
|---|---|
| `src/probos/events.py` | +4 EventType values (PREDICTION_HIT, PREDICTION_MISS, PREDICTION_FLUSHED, PREDICTION_ERROR_RECORDED) |
| `src/probos/cognitive/predictive_branching/__init__.py` | NEW — public exports |
| `src/probos/cognitive/predictive_branching/engine.py` | NEW — PredictionEngine, ConfidenceTier, PredictionDescriptor, signature helper |
| `src/probos/cognitive/predictive_branching/cache.py` | NEW — SpeculationCache (TTL+FIFO bounded; emits HIT/FLUSHED) |
| `src/probos/cognitive/predictive_branching/executor.py` | NEW — SpeculationExecutor (wraps SubTaskExecutor; tagged source; emits ERROR; exposes dispatch_anticipatory) |
| `src/probos/cognitive/predictive_branching/budget.py` | NEW — SpeculationBudget (rolling window; agency gate; flush-rate feedback) |
| `src/probos/cognitive/predictive_branching/accuracy.py` | NEW — AccuracyTracker (ring buffer + AccuracyRates) |
| `src/probos/cognitive/predictive_branching/policy.py` | NEW — IdleSpeculationPolicy + PreplayHook Protocols + NoOp default impls |
| `src/probos/cognitive/cognitive_agent.py` | +pre-LLM cache check at head of `_decide_via_llm` (AD-633d hook) |
| `src/probos/config.py` | +PredictiveBranchingConfig + SystemConfig field |
| `src/probos/startup/finalize.py` | +_wire_predictive_branching + invocation immediately after AD-632 SubTaskExecutor wiring block |
| `src/probos/runtime.py` | +typed attribute declarations: prediction_engine, speculation_cache, speculation_executor, speculation_budget, accuracy_tracker (set by wirer) |
| `tests/test_ad633_predictive_branching.py` | NEW — ~35 tests across engine, cache, executor, budget, accuracy, hook, config, wiring |

## Acceptance criteria (delegated to ad-633 prompt)

See `prompts/ad-633-predictive-branching-v1.md`. Highlights:

- 35 focused tests pass (matching scope; 5 more than Wave 81 reflects 2 extra modules — budget + accuracy — and Protocol-seam tests).
- Full pytest gate: `pytest tests/ -q -n 4 --dist=loadfile` reports ≥ 11615 passed (Δ ≥ +35).
- Phantom-API pre-check on the prompt body: 0 NEW phantoms (intra-prompt-introduction FPs excluded).
- No commercial language anywhere — no pricing, no premium-feature specs, no third-party-product positioning, no `*(Commercial)*` AD body content. (AD-633 has zero commercial sub-ADs — entirely OSS.)
- All changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- GH #228 closes with the closure note in the Reframe decision section above.

## Hard-stops (real, narrow)

1. `runtime._sub_task_executor` is `None` at the wirer invocation site (config.sub_task disabled or wiring failed earlier) → wirer logs INFO and skips; tests construct SpeculationExecutor directly with stubbed sub-task executor; no source change required.
2. `runtime.hebbian_router` or `runtime.ontology` missing in test rig → engine falls back to confidence floor 0 (always returns ZERO_COST tier); no test regression because v1 default-False — speculation simply doesn't fire.
3. `_decide_via_llm` cache-check raises → tier-2 log-and-degrade catches; agent proceeds to normal LLM path; visible in WARNING log only.
4. Prediction signature collision causes wrong cached analysis served → guarded by signature including `agent_id` + `intent_type` + observation hash; collisions across distinct semantic contexts are vanishingly rare; if observed, AD-633a-1 expands signature surface.

## Out of scope (do NOT build in this wave)

- AD-633i Cognitive JIT compilation of predictions (no consumer at HEAD; deferred until AD-531–539 lands)
- Concrete IdleSpeculationPolicy implementation that drives ProactiveCognitiveLoop (Protocol seam only; needs AD-633e accuracy data first)
- Concrete PreplayHook implementation + dream Step 13 wiring (Protocol seam only; needs dream-step registry refactor)
- AD-557 EmergenceMetricsEngine listener for `PREDICTION_ERROR_RECORDED` (event emit only; AD-557 has no consumer surface at HEAD)
- HXI surface for prediction accuracy / hit rates (no API endpoint, no UI; observability is via EventType only)
- LLM-driven prediction confidence (engine is purely deterministic; LLM-scored confidence is a separate AD)
- Cross-agent shared speculation cache (per-agent only in v1; cross-agent sharing needs federation surface)
- Persistent speculation cache (in-memory only; restart = empty cache; persistence is future AD)
- Speculation cancellation / pre-emption when operational work arrives (executor runs to completion in v1; pre-emption is a separate AD)
