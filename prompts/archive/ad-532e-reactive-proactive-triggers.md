# AD-532e: Reactive & Proactive Extraction Triggers — Build Prompt

**Depends on:** AD-533 ✅, AD-534 ✅, AD-532b ✅

**Goal:** Add two new trigger paths for procedure evolution beyond dream consolidation: (1) reactive post-execution analysis that detects divergence after each significant task, and (2) proactive periodic metric scan that catches degraded procedures between dream cycles. Both gated by LLM confirmation. Also adds apply-retry with LLM correction for all evolution paths.

**Principles compliance:** SOLID (new functions, no modification of existing Step 7/7b/7c logic), DRY (reuses `diagnose_procedure_health()`, `evolve_fix_procedure()`, `evolve_derived_procedure()`), Open/Closed (new trigger paths extend the system without changing existing dream-time evolution), Fail Fast (log-and-degrade on all failures), Interface Segregation (event-based decoupling via EventType).

---

## Part 0: LLM Confirmation Gate & Apply-Retry

**File:** `src/probos/cognitive/procedures.py`

### 0a. LLM Confirmation Gate

New async function:

```python
async def confirm_evolution_with_llm(
    procedure_name: str,
    diagnosis: str,
    evidence: str,
    llm_client: Any,
) -> bool:
```

Implementation:
1. Build a system prompt: "You are a procedure evolution gate. Given a procedure's health diagnosis and supporting evidence, determine whether evolution should be triggered. Answer with exactly YES or NO on the first line, followed by a brief reason."
2. Build user prompt with procedure name, diagnosis string (e.g., `"FIX:high_fallback_rate"`), and evidence text (e.g., metric values, recent failure context)
3. Call LLM with tier `"standard"`
4. Parse response: strip whitespace, check if first line starts with "YES" (case-insensitive). Only exact "YES" proceeds. Any other response including "MAYBE", "PROBABLY", empty, or LLM failure → return `False`
5. Log decision at debug level: `"Evolution gate: procedure=%s diagnosis=%s decision=%s"`
6. On any exception → return `False` (conservative, log-and-degrade)

### 0b. Apply-Retry Wrapper

New async function:

```python
async def evolve_with_retry(
    evolve_fn: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    **kwargs: Any,
) -> Any:
```

Implementation:
1. Call `await evolve_fn(*args, **kwargs)`
2. If result is not `None` → return result (success on first try)
3. On `None` return (parse failure, LLM decline): retry up to `max_retries - 1` more times
4. On each retry: log at debug level `"Evolution retry %d/%d for %s"`, include a `retry_hint` kwarg in the call: `kwargs["retry_hint"] = f"Previous attempt returned no usable result. Please ensure valid JSON output."`
5. If all retries exhausted → return `None`
6. On exception during any attempt → catch, log, count as failed attempt, continue retrying

**Note:** The existing evolution functions (`evolve_fix_procedure`, `evolve_derived_procedure`) must accept and ignore an optional `retry_hint` keyword argument. Add `**kwargs` to their signatures if not already present, OR add an explicit `retry_hint: str = ""` parameter and append it to the user prompt when non-empty.

### 0c. Config Constants

**File:** `src/probos/config.py`

Add after the existing procedure constants:

```python
REACTIVE_COOLDOWN_SECONDS: int = 60       # Per-agent cooldown for reactive checks
PROACTIVE_SCAN_INTERVAL_SECONDS: int = 300  # 5 minutes between proactive scans
EVOLUTION_MAX_RETRIES: int = 3              # Max retry attempts for evolution
```

---

## Part 1: Reactive Trigger (Post-Execution)

### 1a. New EventType

**File:** `src/probos/events.py`

Add to the `EventType` enum, in the Counselor/Cognitive Health section:

```python
TASK_EXECUTION_COMPLETE = "task_execution_complete"  # AD-532e: reactive trigger
```

Add a typed event dataclass:

```python
@dataclass
class TaskExecutionCompleteEvent(BaseEvent):
    """Emitted after a cognitive agent completes a task via LLM path."""
    event_type: EventType = field(default=EventType.TASK_EXECUTION_COMPLETE, init=False)
    agent_id: str = ""
    agent_type: str = ""
    intent_type: str = ""
    success: bool = False
    used_procedure: bool = False  # True if procedural replay was used (no reactive needed)
```

### 1b. Emit Event from CognitiveAgent

**File:** `src/probos/cognitive/cognitive_agent.py`

In `handle_intent()`, after `self.update_confidence(success)` (line 670) and before the `return IntentResult(...)`, emit the event:

```python
# AD-532e: Reactive trigger — emit task completion for procedure evolution monitoring
_rt = getattr(self, '_runtime', None)
if _rt and hasattr(_rt, '_emit_event'):
    try:
        _rt._emit_event(EventType.TASK_EXECUTION_COMPLETE, {
            "agent_id": self.id,
            "agent_type": getattr(self, 'agent_type', ''),
            "intent_type": intent.intent,
            "success": success,
            "used_procedure": decision.get("cached", False),
        })
    except Exception:
        pass  # Fire-and-forget, never block the intent pipeline
```

Add `EventType` to the imports at the top of the file.

**Important:** Do NOT emit for skill dispatch (the early return at line 653). Only emit for the cognitive lifecycle path.

### 1c. Reactive Handler on DreamingEngine

**File:** `src/probos/cognitive/dreaming.py`

Add a new method to `DreamingEngine`:

```python
async def on_task_execution_complete(self, event_data: dict[str, Any]) -> None:
    """AD-532e: Reactive trigger — analyze post-execution for evolution opportunities."""
```

Implementation:
1. **Guard clauses** — return early if:
   - `event_data.get("used_procedure")` is True (replay succeeded, nothing to analyze)
   - `event_data.get("success")` is False (failures handled by dream cycle Step 7c)
   - `self._procedure_store` is None or `self._llm_client` is None
2. **Rate limit** — maintain `_reactive_cooldowns: dict[str, float]` (agent_id → last check timestamp). Skip if within `REACTIVE_COOLDOWN_SECONDS` (default 60s)
3. **Find matching procedure** — call `self._procedure_store.find_matching(intent_type, threshold=PROCEDURE_MATCH_THRESHOLD)`. If no match → add to `_extraction_candidates` dict (intent_type → timestamp) and return
4. **If match found** — load quality metrics via `self._procedure_store.get_quality_metrics(procedure_id)`. Check if `completion_rate` is declining (compare against threshold) or `fallback_rate` is rising
5. **If metrics suggest divergence** — run `diagnose_procedure_health(metrics)`. If diagnosis is not None:
   - Check anti-loop guard (`_addressed_degradations`)
   - Call `confirm_evolution_with_llm()` with procedure name, diagnosis, and evidence (metric summary)
   - If confirmed → call `evolve_with_retry(evolve_fix_procedure, ...)` or `evolve_with_retry(evolve_derived_procedure, ...)` based on diagnosis prefix
   - If evolution succeeds → save to `_procedure_store`, update `_addressed_degradations`
6. **Log-and-degrade** — entire method wrapped in try/except, never raises

### 1d. Extraction Candidates Tracking

Add to `DreamingEngine.__init__()`:

```python
self._extraction_candidates: dict[str, float] = {}  # AD-532e: intent_type -> timestamp
self._reactive_cooldowns: dict[str, float] = {}  # AD-532e: agent_id -> last reactive check
```

These are in-memory only (reset on restart, which is fine — they're optimization hints, not critical state).

---

## Part 2: Proactive Scan (Periodic Metric Health)

### 2a. Proactive Scan Method on DreamingEngine

**File:** `src/probos/cognitive/dreaming.py`

Add a new method:

```python
async def proactive_procedure_scan(self) -> dict[str, Any]:
    """AD-532e: Proactive trigger — periodic health scan of all active procedures."""
```

Implementation:
1. **Guard** — return `{"scanned": 0, "evolved": 0}` if `self._procedure_store` is None or `self._llm_client` is None
2. **List active procedures** — `procedures = await self._procedure_store.list_active()`
3. **For each procedure:**
   a. Get quality metrics: `metrics = await self._procedure_store.get_quality_metrics(proc_id)`
   b. Run diagnosis: `diagnosis = diagnose_procedure_health(metrics, min_selections=PROCEDURE_MIN_SELECTIONS)`
   c. If `diagnosis is None` → skip (healthy)
   d. Check anti-loop guard: if `proc_id` in `_addressed_degradations` and within `EVOLUTION_COOLDOWN_SECONDS` → skip
   e. **LLM confirmation gate**: `confirmed = await confirm_evolution_with_llm(proc_name, diagnosis, evidence_str, self._llm_client)`
   f. If not confirmed → record in `_addressed_degradations` (prevent re-checking), continue
   g. If confirmed → evolve with retry (same logic as Step 7b: load recent episodes, call `evolve_with_retry(evolve_fix_procedure, ...)` or `evolve_with_retry(evolve_derived_procedure, ...)`)
   h. If evolution succeeds → save, deactivate parent (for FIX), update `_addressed_degradations`
4. **Return stats** — `{"scanned": total_scanned, "evolved": total_evolved, "skipped_cooldown": count}`
5. **Log-and-degrade** — entire method wrapped in try/except per procedure (one failure doesn't stop scanning others)

**DRY with Step 7b:** The proactive scan and Step 7b (`_evolve_degraded_procedures`) share the same logic core: list procedures → diagnose → evolve. The difference is:
- Step 7b: runs during dream cycle, NO confirmation gate, has access to fresh episode clusters
- Proactive scan: runs between dream cycles, WITH confirmation gate, recalls episodes from EpisodicMemory

Extract the shared diagnosis+evolve loop into a private helper `_attempt_procedure_evolution(proc, diagnosis, metrics, require_confirmation=False) -> bool` that both Step 7b and proactive scan call. Step 7b passes `require_confirmation=False`, proactive scan passes `require_confirmation=True`.

### 2b. Wire Proactive Scan on DreamScheduler

**File:** `src/probos/cognitive/dreaming.py`

In `DreamScheduler._monitor_loop()`, add a third tier between micro-dream and full-dream:

```python
# Tier 1.5: Proactive procedure scan (AD-532e)
if (
    not self._is_dreaming
    and self._last_proactive_scan_time is not None
    and now - self._last_proactive_scan_time >= PROACTIVE_SCAN_INTERVAL_SECONDS
):
    try:
        scan_result = await self.engine.proactive_procedure_scan()
        self._last_proactive_scan_time = now
        if scan_result.get("evolved", 0) > 0:
            logger.debug("Proactive scan evolved %d procedures", scan_result["evolved"])
    except Exception as e:
        logger.debug("Proactive procedure scan failed: %s", e)
```

Add to `DreamScheduler.__init__()`:

```python
self._last_proactive_scan_time: float = 0.0  # AD-532e
```

Import `PROACTIVE_SCAN_INTERVAL_SECONDS` from config.

### 2c. Wire Reactive Event Subscription

**File:** `src/probos/startup/dreaming.py`

After the DreamingEngine is created and wired, subscribe to the reactive event:

```python
# AD-532e: Reactive trigger subscription
if hasattr(runtime, 'add_event_listener'):
    async def _on_task_complete(event: dict) -> None:
        try:
            await engine.on_task_execution_complete(event.get("data", event))
        except Exception:
            logger.debug("Reactive trigger handler failed", exc_info=True)

    runtime.add_event_listener(
        _on_task_complete,
        event_types=[EventType.TASK_EXECUTION_COMPLETE],
    )
```

Import `EventType` in the startup module.

---

## Part 3: DreamReport Enhancement

**File:** `src/probos/types.py`

Add to the `DreamReport` dataclass:

```python
proactive_evolutions: int = 0  # AD-532e: procedures evolved by proactive scan
reactive_flags: int = 0        # AD-532e: extraction candidates flagged by reactive trigger
```

These are NOT populated during dream_cycle() (they happen between dreams). They're populated by `proactive_procedure_scan()` return values and logged separately. Include them in DreamReport for completeness so the unified stats surface is available.

---

## Part 4: Tests

**File:** `tests/test_reactive_proactive_triggers.py`

### Test Class 1: `TestLLMConfirmationGate`
1. `test_confirm_yes` — LLM returns "YES\nReason..." → returns True
2. `test_confirm_no` — LLM returns "NO\nReason..." → returns False
3. `test_confirm_maybe` — LLM returns "MAYBE" → returns False (conservative)
4. `test_confirm_empty` — LLM returns "" → returns False
5. `test_confirm_llm_failure` — LLM raises exception → returns False
6. `test_confirm_case_insensitive` — LLM returns "yes" → returns True
7. `test_confirm_leading_whitespace` — LLM returns "  YES" → returns True

### Test Class 2: `TestEvolveWithRetry`
8. `test_retry_success_first_try` — evolve_fn returns result on first call → returns result, called once
9. `test_retry_success_second_try` — evolve_fn returns None then result → returns result, called twice
10. `test_retry_all_fail` — evolve_fn returns None 3 times → returns None, called 3 times
11. `test_retry_exception_then_success` — evolve_fn raises then returns result → returns result
12. `test_retry_max_retries_configurable` — max_retries=1 → only one attempt
13. `test_retry_passes_retry_hint` — second call receives retry_hint kwarg

### Test Class 3: `TestEventTypeAndEmission`
14. `test_task_execution_complete_event_type_exists` — `EventType.TASK_EXECUTION_COMPLETE` exists
15. `test_task_execution_complete_event_dataclass` — `TaskExecutionCompleteEvent` has all fields
16. `test_event_emitted_on_llm_path` — mock CognitiveAgent with runtime._emit_event → event emitted after handle_intent()
17. `test_event_not_emitted_on_skill_path` — skill dispatch → no event emitted
18. `test_event_not_emitted_without_runtime` — no runtime → no crash, no event

### Test Class 4: `TestReactiveTrigger`
19. `test_reactive_skips_procedure_replay` — used_procedure=True → returns immediately
20. `test_reactive_skips_failure` — success=False → returns immediately
21. `test_reactive_rate_limited` — two calls within REACTIVE_COOLDOWN_SECONDS → second skipped
22. `test_reactive_no_match_flags_candidate` — no matching procedure → intent_type added to _extraction_candidates
23. `test_reactive_match_healthy_no_action` — matching procedure with healthy metrics → no evolution
24. `test_reactive_match_degraded_confirmed_evolves` — degraded metrics + LLM confirms YES → evolution triggered
25. `test_reactive_match_degraded_denied_skips` — degraded metrics + LLM confirms NO → no evolution
26. `test_reactive_respects_anti_loop_guard` — procedure in _addressed_degradations within cooldown → skipped
27. `test_reactive_never_raises` — internal error → caught, logged, no exception

### Test Class 5: `TestProactiveScan`
28. `test_proactive_scans_all_active` — list_active returns 3 procedures → all 3 checked
29. `test_proactive_skips_healthy` — healthy metrics → no evolution, scanned count incremented
30. `test_proactive_evolves_confirmed` — degraded + confirmed → evolved, count incremented
31. `test_proactive_skips_denied` — degraded + denied → not evolved, addressed_degradations updated
32. `test_proactive_respects_cooldown` — procedure in cooldown → skipped
33. `test_proactive_returns_stats` — returns dict with scanned, evolved, skipped_cooldown keys
34. `test_proactive_one_failure_continues` — first procedure raises during evolution → second still scanned
35. `test_proactive_no_store_returns_zeros` — procedure_store is None → returns {scanned: 0, evolved: 0}

### Test Class 6: `TestDreamSchedulerProactiveTier`
36. `test_proactive_scan_triggered_on_interval` — simulate time passage > PROACTIVE_SCAN_INTERVAL_SECONDS → scan called
37. `test_proactive_scan_not_during_dreaming` — _is_dreaming=True → scan not called
38. `test_proactive_scan_failure_nonfatal` — scan raises → monitor loop continues

### Test Class 7: `TestDreamReportFields`
39. `test_dreamreport_proactive_evolutions_default_zero` — DreamReport() has proactive_evolutions=0
40. `test_dreamreport_reactive_flags_default_zero` — DreamReport() has reactive_flags=0

---

## Cross-Cutting Requirements

- **DRY:** Reuse `diagnose_procedure_health()`, `evolve_fix_procedure()`, `evolve_derived_procedure()` from procedures.py. Extract shared diagnosis+evolve loop into a helper used by both Step 7b and proactive scan.
- **Backward compatibility:** Step 7b behavior unchanged — no confirmation gate added to dream-time evolution (per roadmap: "Dream consolidation does not require confirmation").
- **Log-and-degrade:** Reactive handler and proactive scan must NEVER crash the system. All errors caught and logged at debug level.
- **Anti-loop guard:** Both reactive and proactive triggers share `_addressed_degradations` with Step 7b. Same 72h cooldown.
- **Conservative default:** Ambiguous LLM responses = skip evolution. LLM failure = skip. Missing data = skip.
- **No blocking:** Reactive event handler is async, fire-and-forget from the event system. Event emission in handle_intent() is try/except pass — never blocks the intent pipeline.
- **Config-driven:** All intervals and thresholds are config constants, not hardcoded.

---

## Validation Checklist

### Part 0 — Confirmation Gate & Retry
- [ ] `confirm_evolution_with_llm()` exists in procedures.py
- [ ] Returns True only on "YES", False on everything else
- [ ] LLM failure → returns False (conservative)
- [ ] `evolve_with_retry()` exists in procedures.py
- [ ] Retries up to `max_retries` times on None result
- [ ] Passes `retry_hint` on subsequent attempts
- [ ] Exception during attempt → counts as failure, continues retrying
- [ ] Config constants added: `REACTIVE_COOLDOWN_SECONDS`, `PROACTIVE_SCAN_INTERVAL_SECONDS`, `EVOLUTION_MAX_RETRIES`

### Part 1 — Reactive Trigger
- [ ] `EventType.TASK_EXECUTION_COMPLETE` exists in events.py
- [ ] `TaskExecutionCompleteEvent` dataclass exists with all fields
- [ ] Event emitted from CognitiveAgent.handle_intent() after update_confidence()
- [ ] Event NOT emitted for skill dispatch path
- [ ] Event emission wrapped in try/except (fire-and-forget)
- [ ] `on_task_execution_complete()` method exists on DreamingEngine
- [ ] Skips used_procedure=True, success=False
- [ ] Rate-limited by `REACTIVE_COOLDOWN_SECONDS` per agent
- [ ] No match → adds to `_extraction_candidates`
- [ ] Match + degraded + confirmed → evolves with retry
- [ ] Match + degraded + denied → skips, records in `_addressed_degradations`
- [ ] Respects anti-loop guard
- [ ] Never raises (log-and-degrade)

### Part 2 — Proactive Scan
- [ ] `proactive_procedure_scan()` method exists on DreamingEngine
- [ ] Scans all active procedures via list_active()
- [ ] Uses `diagnose_procedure_health()` for each
- [ ] Gates through `confirm_evolution_with_llm()` (unlike Step 7b)
- [ ] Evolves with `evolve_with_retry()` on confirmation
- [ ] Shares `_addressed_degradations` with Step 7b
- [ ] Returns stats dict with scanned/evolved/skipped_cooldown
- [ ] One procedure failure doesn't stop scanning others
- [ ] DreamScheduler runs proactive scan on `PROACTIVE_SCAN_INTERVAL_SECONDS` interval
- [ ] Proactive scan not run during dreaming
- [ ] Scan failure doesn't crash monitor loop
- [ ] Shared helper extracted for diagnosis+evolve loop (DRY with Step 7b)

### Part 3 — DreamReport
- [ ] `proactive_evolutions` field added with default 0
- [ ] `reactive_flags` field added with default 0

### Part 4 — Tests
- [ ] All ~40 tests pass
- [ ] No existing tests broken
- [ ] `pytest tests/test_reactive_proactive_triggers.py -v` — all green
- [ ] `pytest tests/ -x --timeout=30` — full suite green (pre-existing failures excluded)

### Cross-Cutting
- [ ] Step 7b behavior unchanged (no confirmation gate)
- [ ] Evolution functions accept retry_hint parameter gracefully
- [ ] Event import added to cognitive_agent.py
- [ ] Event subscription wired in startup/dreaming.py
- [ ] `_extraction_candidates` and `_reactive_cooldowns` initialized in DreamingEngine.__init__()
