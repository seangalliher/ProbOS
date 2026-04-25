# AD-534b: Fallback Learning — Build Prompt

**Depends on:** AD-534 ✅, AD-532b ✅, AD-532e ✅

**Goal:** Close the feedback loop: when a procedure replay fails (execution failure) or is skipped (near-miss), and the LLM path succeeds, capture the comparison pair and use it for targeted FIX evolution during dream time. Also fixes a metric accounting gap: `record_completion()` currently fires after formatting (always succeeds), not after execution (may fail). Adds service recovery: re-run through LLM on cached execution failure so the user never sees the procedure's mistake.

**Scope boundary:** AD-534b does NOT change how replay executes — replay is still monolithic text formatting. Step-by-step postcondition validation and Dreyfus compilation levels are AD-535.

**Principles compliance:** SOLID (new methods, no modification of existing Step 7/7b/7c logic), DRY (reuses `evolve_with_retry()`, `_attempt_procedure_evolution()` helper pattern, `_format_episode_blocks()`), Open/Closed (new Step 7d extends dream cycle without changing 7/7b/7c), Fail Fast (log-and-degrade on all failures — fallback learning is enhancement, never blocks intent pipeline), Interface Segregation (event-based decoupling between CognitiveAgent and DreamingEngine).

---

## Part 0: Metric Semantics Fix

**File:** `src/probos/cognitive/cognitive_agent.py`

### 0a. Remove premature `record_completion()` and `record_fallback()` from `_check_procedural_memory()`

Currently the method calls these inside the try/except block:
- `record_completion()` after `_format_procedure_replay()` succeeds (formatting always succeeds — metric is meaningless)
- `record_fallback()` on format exception (near-zero occurrence)

**Remove both calls.** Keep `record_selection()` and `record_applied()` where they are — those correctly measure intent (selection) and attempt (applied). The outcome metrics (completion/fallback) move to `handle_intent()` where actual execution results are known.

### 0b. Add post-execution metric recording to `handle_intent()`

After `act(decision)` returns and `success` is determined, add metric recording for cached decisions:

```python
# AD-534b: Post-execution metric recording for procedure replay
if decision.get("cached") and decision.get("procedure_id"):
    _store = getattr(self, '_procedure_store', None)
    if _store:
        try:
            if success:
                await _store.record_completion(decision["procedure_id"])
            else:
                await _store.record_fallback(decision["procedure_id"])
        except Exception:
            pass  # Never block intent pipeline for metrics
```

This must happen BEFORE the service recovery re-run (Part 2), so the fallback counter is incremented before we attempt recovery.

**Impact:** For base `CognitiveAgent` where `act()` always returns `success=True` for replayed text — no change in metric values (completion_rate stays ~100%). For `BuilderAgent` and other subclasses with real `act()` validation — metrics now reflect execution reality. No metric schema changes needed — same four counters, more meaningful semantics.

### 0c. Ensure `procedure_id` is in the decision dict

Verify that `_check_procedural_memory()` already includes `"procedure_id": procedure.id` in the returned decision dict. The existing code at lines 212-218 should already have this. If not, add it.

---

## Part 1: Near-Miss Capture

**File:** `src/probos/cognitive/cognitive_agent.py`

### 1a. Add fallback tracking instance state

Add to `CognitiveAgent.__init__()`:

```python
self._last_fallback_info: dict[str, Any] | None = None  # AD-534b: near-miss/failure context
```

This is set within `_check_procedural_memory()` when a procedure is relevant but rejected, and consumed/cleared by `handle_intent()` after the LLM path succeeds.

### 1b. Track near-miss rejections in `_check_procedural_memory()`

At each return-None point where a candidate procedure was found but rejected, set `self._last_fallback_info` before returning:

**(i) Score threshold rejection** — after `find_matching()` returns results but best score < `PROCEDURE_MATCH_THRESHOLD`:

```python
if best_result["score"] < PROCEDURE_MATCH_THRESHOLD:
    self._last_fallback_info = {
        "type": "score_threshold",
        "procedure_id": best_result["id"],
        "procedure_name": best_result.get("name", ""),
        "score": best_result["score"],
        "reason": f"Score {best_result['score']:.2f} below threshold {PROCEDURE_MATCH_THRESHOLD}",
    }
    return None
```

**(ii) Quality gate rejection** — when `effective_rate < 0.3` on a matching procedure:

```python
self._last_fallback_info = {
    "type": "quality_gate",
    "procedure_id": best_result["id"],
    "procedure_name": best_result.get("name", ""),
    "score": best_result["score"],
    "metrics": quality_metrics,
    "reason": f"Effective rate {effective_rate:.2f} below 0.3",
}
return None
```

**(iii) Negative procedure veto** — when a negative procedure blocks matching:

```python
self._last_fallback_info = {
    "type": "negative_veto",
    "procedure_id": negative_match["id"],
    "procedure_name": negative_match.get("name", ""),
    "score": negative_match["score"],
    "reason": "Blocked by negative procedure (anti-pattern match)",
}
return None
```

**(iv) Format exception** — in the existing except block (procedural replay attempted but formatting failed):

```python
except Exception as exc:
    self._last_fallback_info = {
        "type": "format_exception",
        "procedure_id": procedure.id,
        "procedure_name": procedure.name,
        "score": best.get("score", 0),
        "reason": f"Replay formatting failed: {exc}",
    }
    # record_fallback removed (moved to handle_intent)
    return None
```

**(v) No match at all** — when `find_matching()` returns empty results:

Do NOT set `_last_fallback_info` — no procedure was relevant. The reactive trigger (AD-532e) already handles the "no match" case via `_extraction_candidates`. AD-534b only captures cases where a procedure WAS relevant but wasn't used.

### 1c. Clear fallback info at start of `_check_procedural_memory()`

At the very top of the method:

```python
self._last_fallback_info = None  # Reset for this cycle
```

This ensures stale info from a previous call doesn't leak.

---

## Part 2: Post-Execution Fallback & Service Recovery

**File:** `src/probos/cognitive/cognitive_agent.py`

### 2a. Add `_run_llm_fallback()` private method

New async method on `CognitiveAgent`:

```python
async def _run_llm_fallback(self, observation: dict[str, Any]) -> dict[str, Any] | None:
    """AD-534b: Re-run through LLM path, skipping procedural memory and decision cache."""
```

Implementation:
1. Skip decision cache lookup and procedural memory check
2. Go directly to the LLM path: build messages, call `llm_client.complete()`, parse response
3. Return the decision dict (same format as `decide()` output) or `None` on failure
4. This method extracts the LLM-only portion of `decide()` into a callable unit

**DRY approach:** Rather than duplicating the LLM path, refactor `decide()` to call an internal `_decide_via_llm(observation)` method for its LLM path. Then `_run_llm_fallback()` just calls `_decide_via_llm()` directly, bypassing caches.

### 2b. Service recovery in `handle_intent()`

After the metric recording (Part 0b), add the service recovery block:

```python
# AD-534b: Service recovery — re-run LLM on cached execution failure
if decision.get("cached") and not success:
    _proc_id = decision.get("procedure_id", "")
    _proc_name = decision.get("procedure_name", "")
    logger.debug("Procedure replay failed, attempting LLM fallback: procedure=%s", _proc_name)
    try:
        llm_decision = await self._run_llm_fallback(observation)
        if llm_decision is not None:
            llm_result = self.act(llm_decision)
            llm_report = self.report(llm_result)
            llm_success = llm_report.get("success", False)
            if llm_success:
                # Service recovery succeeded — use LLM result
                result = llm_result
                report = llm_report
                success = True
                # Capture fallback learning event
                self._last_fallback_info = {
                    "type": "execution_failure",
                    "procedure_id": _proc_id,
                    "procedure_name": _proc_name,
                    "reason": "Procedure replay succeeded in formatting but failed in execution",
                }
    except Exception:
        logger.debug("LLM fallback recovery failed", exc_info=True)
        # Original failure stands — user sees the procedure's error
```

**Important:** This block runs before `update_confidence()` and before the `TASK_EXECUTION_COMPLETE` event emission. If recovery succeeds, `success` is now `True`, so confidence updates and event emission reflect the recovered state.

### 2c. Emit fallback learning event

After service recovery (whether it happened or not), and after the existing `TASK_EXECUTION_COMPLETE` event emission, emit the fallback learning event if near-miss or execution failure info was captured:

```python
# AD-534b: Emit fallback learning event for dream-time processing
if success and self._last_fallback_info is not None:
    _rt = getattr(self, '_runtime', None)
    if _rt and hasattr(_rt, '_emit_event'):
        try:
            _llm_output = (
                llm_decision.get("llm_output", "") if 'llm_decision' in dir() and llm_decision
                else decision.get("llm_output", "")
            )
            _rt._emit_event(EventType.PROCEDURE_FALLBACK_LEARNING, {
                "agent_id": self.id,
                "intent_type": intent.intent,
                "fallback_type": self._last_fallback_info["type"],
                "procedure_id": self._last_fallback_info["procedure_id"],
                "procedure_name": self._last_fallback_info.get("procedure_name", ""),
                "near_miss_score": self._last_fallback_info.get("score", 0.0),
                "rejection_reason": self._last_fallback_info.get("reason", ""),
                "llm_response": _llm_output[:MAX_FALLBACK_RESPONSE_CHARS],
                "timestamp": time.time(),
            })
        except Exception:
            pass  # Fire-and-forget
    self._last_fallback_info = None  # Consumed
```

**Guard:** Only emit when `success is True` — we need a successful LLM response to learn from. If both the procedure AND the LLM failed, there's nothing to learn (the task was genuinely too hard).

---

## Part 3: Event & Queue Infrastructure

### 3a. New EventType

**File:** `src/probos/events.py`

Add to the `EventType` enum, in the Counselor/Cognitive Health section (after `TASK_EXECUTION_COMPLETE`):

```python
PROCEDURE_FALLBACK_LEARNING = "procedure_fallback_learning"  # AD-534b: fallback evidence
```

Add a typed event dataclass:

```python
@dataclass
class ProcedureFallbackLearningEvent(BaseEvent):
    """Emitted when a procedure was relevant but skipped/failed, and the LLM succeeded (AD-534b)."""
    event_type: EventType = field(default=EventType.PROCEDURE_FALLBACK_LEARNING, init=False)
    agent_id: str = ""
    intent_type: str = ""
    fallback_type: str = ""        # "execution_failure" | "quality_gate" | "score_threshold" | "negative_veto" | "format_exception"
    procedure_id: str = ""
    procedure_name: str = ""
    near_miss_score: float = 0.0   # Cosine similarity score (0 for execution failures)
    rejection_reason: str = ""     # Human-readable reason for rejection/failure
    llm_response: str = ""         # What the LLM did (truncated to MAX_FALLBACK_RESPONSE_CHARS)
    timestamp: float = 0.0
```

### 3b. Config Constants

**File:** `src/probos/config.py`

Add after the existing procedure/evolution constants:

```python
MAX_FALLBACK_RESPONSE_CHARS: int = 4000  # Truncation limit for LLM response in fallback events
MAX_FALLBACK_QUEUE_SIZE: int = 50        # Cap on in-memory fallback queue per dream cycle
```

### 3c. Fallback Learning Queue on DreamingEngine

**File:** `src/probos/cognitive/dreaming.py`

Add to `DreamingEngine.__init__()`:

```python
self._fallback_learning_queue: list[dict[str, Any]] = []  # AD-534b: fallback evidence for dream-time processing
```

### 3d. DreamingEngine event subscriber

Add a new method to `DreamingEngine`:

```python
async def on_procedure_fallback_learning(self, event_data: dict[str, Any]) -> None:
    """AD-534b: Queue fallback evidence for dream-time targeted evolution."""
```

Implementation:
1. **Guard:** Return early if `self._procedure_store` is None or `self._llm_client` is None
2. **Queue cap:** If `len(self._fallback_learning_queue) >= MAX_FALLBACK_QUEUE_SIZE`, drop the oldest entry (FIFO eviction)
3. **Append:** Add the event_data dict to `self._fallback_learning_queue`
4. **Log:** Debug level: `"Fallback learning event queued: type=%s procedure=%s"`
5. **Log-and-degrade:** Entire method wrapped in try/except, never raises

### 3e. Wire event subscription

**File:** `src/probos/startup/dreaming.py`

After the existing `TASK_EXECUTION_COMPLETE` subscription (AD-532e), add:

```python
# AD-534b: Fallback learning event subscription
async def _on_fallback_learning(event: dict) -> None:
    try:
        await engine.on_procedure_fallback_learning(event.get("data", event))
    except Exception:
        logger.debug("Fallback learning handler failed", exc_info=True)

runtime.add_event_listener(
    _on_fallback_learning,
    event_types=[EventType.PROCEDURE_FALLBACK_LEARNING],
)
```

Import `EventType.PROCEDURE_FALLBACK_LEARNING` (should already be available from the existing `EventType` import).

---

## Part 4: Targeted FIX Evolution (Dream Step 7d)

**File:** `src/probos/cognitive/procedures.py`

### 4a. `_FALLBACK_FIX_SYSTEM_PROMPT`

New system prompt constant for fallback-targeted procedure repair. This is more specific than `_FIX_SYSTEM_PROMPT` because it receives the LLM's successful response as direct evidence:

Key instructions for the LLM:
1. You are given a procedure that was relevant to a task but either failed during execution or was rejected by quality gates
2. You are also given what the LLM actually did to succeed at the same task
3. **Compare** the procedure's steps with the LLM's approach — identify which steps diverged and why
4. **Diagnose** the root cause: did the task requirements shift? Did a precondition change? Is a step outdated? Is the procedure too narrow?
5. **Produce** a repaired procedure that incorporates the LLM's successful approach while maintaining the procedure's structure and intent
6. Include a `change_summary` explaining what was wrong and what you fixed, referencing specific step numbers
7. Include a `divergence_point` field: the step number where procedure and LLM first diverged (0 if entire approach changed)
8. Use the same JSON schema as `_FIX_SYSTEM_PROMPT` (name, description, steps with expected_input/output/fallback/invariants, preconditions, postconditions, change_summary), plus the additional `divergence_point` integer field

Include AD-541b READ-ONLY constraints (reference episode data, do not reconstruct narratives).

### 4b. `evolve_fix_from_fallback()`

New async function:

```python
async def evolve_fix_from_fallback(
    parent: Procedure,
    fallback_type: str,
    llm_response: str,
    rejection_reason: str,
    fresh_episodes: list[Any],
    llm_client: Any,
    retry_hint: str = "",
) -> EvolutionResult | None:
```

Implementation:
1. Build user prompt with:
   - The full parent procedure JSON (via `parent.to_dict()`)
   - The `fallback_type` (execution_failure, quality_gate, score_threshold, negative_veto, format_exception)
   - The `rejection_reason` string
   - The `llm_response` text (what the LLM did to succeed — the golden reference)
   - Formatted `fresh_episodes` via `_format_episode_blocks()` (additional context)
   - Optional `retry_hint` appended when non-empty
2. Call LLM with `_FALLBACK_FIX_SYSTEM_PROMPT` + user prompt, tier `"standard"`
3. Parse response with `_parse_procedure_json()`
4. Build steps with `_build_steps_from_data()`
5. Construct new `Procedure` with:
   - `evolution_type = "FIX"`
   - `generation = parent.generation + 1`
   - `parent_procedure_ids = [parent.id]`
   - `intent_types = parent.intent_types`
   - All other fields from parsed response
6. Generate `content_diff` via `_generate_content_diff(parent, new_procedure)`
7. Extract `change_summary` and `divergence_point` from parsed response
8. Return `EvolutionResult(procedure, content_diff, change_summary)` or `None` on any failure

**DRY:** Reuses `_format_episode_blocks()`, `_parse_procedure_json()`, `_build_steps_from_data()`, `_generate_content_diff()`. Follows the same structure as `evolve_fix_procedure()` — the difference is the prompt (targeted evidence instead of generic episodes).

### 4c. Handling `negative_veto` fallback type

When `fallback_type == "negative_veto"`, the learning signal is different: the negative procedure may be too broad (it blocked a successful task). Instead of evolving the negative procedure, add a narrowing annotation:

- Load the negative procedure via `procedure_store.get(procedure_id)`
- If the negative procedure has no `preconditions` or they're too broad → consider adding preconditions that would have allowed this specific task to pass
- This is handled by a branch in the dream Step 7d logic (not a separate function) — if `fallback_type == "negative_veto"`, append `(procedure_id, llm_response, intent_type)` to `_extraction_candidates` (reuse AD-532e mechanism) and log at debug level. Full negative procedure refinement deferred.

---

## Part 5: Dream Step 7d — Process Fallback Queue

**File:** `src/probos/cognitive/dreaming.py`

### 5a. New method `_process_fallback_learning()`

Add to `DreamingEngine`:

```python
async def _process_fallback_learning(self) -> int:
    """AD-534b: Dream Step 7d — process fallback learning queue for targeted FIX evolution."""
```

Implementation:
1. **Guard:** Return 0 if `self._fallback_learning_queue` is empty or `self._procedure_store` is None or `self._llm_client` is None
2. **Drain queue:** Take a copy of `self._fallback_learning_queue` and clear it: `queue = list(self._fallback_learning_queue); self._fallback_learning_queue.clear()`
3. **Group by procedure_id:** Multiple fallback events for the same procedure → process once with the most recent event (strongest signal)
4. **For each unique procedure_id:**
   a. **Anti-loop guard:** Skip if `procedure_id` in `self._addressed_degradations` within `EVOLUTION_COOLDOWN_SECONDS`
   b. **Load procedure:** `procedure = await self._procedure_store.get(procedure_id)`
   c. If procedure is None or not active → skip (may have been deactivated by Step 7b already)
   d. **Handle negative_veto type:** If `fallback_type == "negative_veto"`, log and add to `_extraction_candidates`, skip evolution (as per Part 4c)
   e. **Gather fresh episodes:** `recall_by_intent()` for each intent_type in the procedure's `intent_types` list. Limit to 10 most recent. Deduplicate by episode ID.
   f. **Call `evolve_with_retry(evolve_fix_from_fallback, ...)`** with:
      - `parent=procedure`
      - `fallback_type=event["fallback_type"]`
      - `llm_response=event["llm_response"]`
      - `rejection_reason=event["rejection_reason"]`
      - `fresh_episodes=episodes`
      - `llm_client=self._llm_client`
   g. **On success:** Save evolved procedure to `self._procedure_store` with `content_diff` and `change_summary`. If `fallback_type == "execution_failure"` → deactivate parent (it demonstrably failed). If `fallback_type` is a near-miss type (quality_gate, score_threshold) → keep parent active (it wasn't tried, might still work in other contexts).
   h. **Update `_addressed_degradations`** with procedure_id and current timestamp
5. **Return count** of successfully evolved procedures
6. **Log-and-degrade:** Per-procedure try/except — one failure doesn't stop processing others

### 5b. Wire Step 7d into dream_cycle()

In `dream_cycle()`, after Step 7c (negative procedure extraction) and before the final DreamReport construction:

```python
# Step 7d: Fallback learning (AD-534b)
fallback_evolutions = 0
try:
    fallback_evolutions = await self._process_fallback_learning()
    if fallback_evolutions > 0:
        logger.debug("Step 7d: Evolved %d procedures from fallback evidence", fallback_evolutions)
except Exception as e:
    logger.debug("Step 7d fallback learning failed: %s", e)
```

---

## Part 6: DreamReport Enhancement

**File:** `src/probos/types.py`

Add to the `DreamReport` dataclass:

```python
fallback_evolutions: int = 0   # AD-534b: procedures evolved from fallback learning evidence
fallback_events_processed: int = 0  # AD-534b: total fallback events processed in dream cycle
```

Populate in `dream_cycle()` when constructing the DreamReport:
- `fallback_evolutions = fallback_evolutions` (from Step 7d return value)
- `fallback_events_processed = len(queue)` (from the drained queue size — pass this from `_process_fallback_learning()` or return it as part of a stats dict)

Update `_process_fallback_learning()` to return a stats dict instead of just a count:

```python
return {"evolved": evolved_count, "processed": len(queue), "skipped_cooldown": skipped_count, "negative_veto_flagged": veto_count}
```

---

## Part 7: Tests

**File:** `tests/test_fallback_learning.py`

### Test Class 1: `TestMetricSemanticsFix`
1. `test_completion_not_recorded_in_check_procedural` — `_check_procedural_memory()` no longer calls `record_completion()`
2. `test_fallback_not_recorded_in_check_procedural` — `_check_procedural_memory()` no longer calls `record_fallback()` (except as near-miss info)
3. `test_completion_recorded_after_successful_act` — cached decision + act() returns success → `record_completion()` called in `handle_intent()`
4. `test_fallback_recorded_after_failed_act` — cached decision + act() returns failure → `record_fallback()` called in `handle_intent()`
5. `test_metrics_not_recorded_for_non_cached` — non-cached decision → no completion/fallback recording (LLM path doesn't track procedure metrics)
6. `test_procedure_id_in_decision_dict` — cached decision dict contains `"procedure_id"` key

### Test Class 2: `TestNearMissCapture`
7. `test_score_threshold_sets_fallback_info` — best match below threshold → `_last_fallback_info` set with type="score_threshold"
8. `test_quality_gate_sets_fallback_info` — effective_rate < 0.3 → `_last_fallback_info` set with type="quality_gate"
9. `test_negative_veto_sets_fallback_info` — negative procedure blocks match → `_last_fallback_info` set with type="negative_veto"
10. `test_format_exception_sets_fallback_info` — replay formatting raises → `_last_fallback_info` set with type="format_exception"
11. `test_no_match_does_not_set_fallback_info` — empty results from find_matching → `_last_fallback_info` remains None
12. `test_fallback_info_cleared_on_entry` — each call to `_check_procedural_memory()` resets `_last_fallback_info` to None
13. `test_fallback_info_includes_procedure_id` — all near-miss types include procedure_id in the info dict
14. `test_fallback_info_includes_reason` — all near-miss types include human-readable reason string

### Test Class 3: `TestServiceRecovery`
15. `test_cached_failure_triggers_llm_rerun` — cached decision + act fails → `_run_llm_fallback()` called
16. `test_llm_rerun_success_replaces_result` — LLM re-run succeeds → result/report/success updated to LLM values
17. `test_llm_rerun_failure_keeps_original` — LLM re-run also fails → original failure result stands
18. `test_llm_rerun_exception_nonfatal` — `_run_llm_fallback()` raises → original failure stands, no crash
19. `test_confidence_updated_with_recovered_success` — after service recovery, update_confidence() receives `True`
20. `test_non_cached_failure_no_rerun` — non-cached decision fails → no LLM re-run (normal failure)
21. `test_run_llm_fallback_skips_procedure_memory` — `_run_llm_fallback()` does not call `_check_procedural_memory()`
22. `test_run_llm_fallback_skips_decision_cache` — `_run_llm_fallback()` does not check decision cache

### Test Class 4: `TestFallbackEventEmission`
23. `test_event_emitted_on_near_miss_with_llm_success` — near-miss + LLM succeeds → PROCEDURE_FALLBACK_LEARNING event emitted
24. `test_event_not_emitted_on_near_miss_with_llm_failure` — near-miss + LLM fails → no event (nothing to learn)
25. `test_event_not_emitted_without_fallback_info` — no near-miss, normal LLM path → no event
26. `test_event_emitted_on_execution_failure_recovery` — cached failure + LLM recovery → event with type="execution_failure"
27. `test_event_contains_llm_response_truncated` — event llm_response truncated to MAX_FALLBACK_RESPONSE_CHARS
28. `test_event_contains_procedure_id_and_name` — event data includes procedure identifying info
29. `test_event_contains_rejection_reason` — event data includes human-readable reason
30. `test_event_emission_failure_nonfatal` — event emission raises → no crash (fire-and-forget)
31. `test_fallback_info_cleared_after_event` — `_last_fallback_info` set to None after event emission

### Test Class 5: `TestEventAndQueue`
32. `test_procedure_fallback_learning_event_type_exists` — `EventType.PROCEDURE_FALLBACK_LEARNING` exists
33. `test_procedure_fallback_learning_event_dataclass` — `ProcedureFallbackLearningEvent` has all fields
34. `test_dreaming_engine_queues_event` — `on_procedure_fallback_learning()` appends to `_fallback_learning_queue`
35. `test_queue_cap_evicts_oldest` — queue at MAX_FALLBACK_QUEUE_SIZE → oldest entry dropped on new event
36. `test_queue_guard_no_store` — procedure_store is None → event not queued (no crash)
37. `test_queue_handler_never_raises` — handler exception → caught, logged, no propagation

### Test Class 6: `TestFallbackFIXPromptAndEvolution`
38. `test_fallback_fix_prompt_exists` — `_FALLBACK_FIX_SYSTEM_PROMPT` is a non-empty string
39. `test_fallback_fix_prompt_mentions_comparison` — prompt contains "compare" or "diverge" language
40. `test_fallback_fix_prompt_mentions_llm_response` — prompt references "LLM" or "successful response"
41. `test_evolve_fix_from_fallback_basic` — mock LLM returns valid JSON → EvolutionResult with FIX procedure
42. `test_evolve_fix_from_fallback_includes_divergence_point` — response JSON includes divergence_point → captured
43. `test_evolve_fix_from_fallback_generation_incremented` — new procedure has generation = parent.generation + 1
44. `test_evolve_fix_from_fallback_parent_linked` — new procedure has parent_procedure_ids = [parent.id]
45. `test_evolve_fix_from_fallback_llm_decline` — LLM returns error JSON → returns None
46. `test_evolve_fix_from_fallback_llm_failure` — LLM raises → returns None
47. `test_evolve_fix_from_fallback_uses_episode_blocks` — function calls `_format_episode_blocks()` (DRY)
48. `test_evolve_fix_from_fallback_content_diff_generated` — EvolutionResult includes non-empty content_diff
49. `test_evolve_fix_from_fallback_accepts_retry_hint` — function accepts retry_hint kwarg, appends to prompt when non-empty

### Test Class 7: `TestDreamStep7d`
50. `test_step7d_processes_queue` — non-empty queue → `_process_fallback_learning()` processes entries
51. `test_step7d_empty_queue_returns_zero` — empty queue → returns `{"evolved": 0, "processed": 0, ...}`
52. `test_step7d_groups_by_procedure_id` — multiple events for same procedure → processed once (most recent)
53. `test_step7d_respects_anti_loop_guard` — procedure in `_addressed_degradations` within cooldown → skipped
54. `test_step7d_execution_failure_deactivates_parent` — fallback_type="execution_failure" + evolution succeeds → parent deactivated
55. `test_step7d_near_miss_keeps_parent_active` — fallback_type="quality_gate" + evolution succeeds → parent stays active
56. `test_step7d_negative_veto_flags_candidate` — fallback_type="negative_veto" → added to `_extraction_candidates`, no evolution
57. `test_step7d_saves_evolved_procedure` — evolution succeeds → saved to procedure_store with content_diff
58. `test_step7d_one_failure_continues` — first procedure raises during evolution → second still processed
59. `test_step7d_clears_queue_after_processing` — after processing, `_fallback_learning_queue` is empty
60. `test_step7d_uses_evolve_with_retry` — evolution called via `evolve_with_retry()` wrapper
61. `test_step7d_no_store_returns_zeros` — procedure_store is None → returns zeros dict

### Test Class 8: `TestDreamCycleIntegration`
62. `test_step7d_runs_after_step7c` — dream_cycle() calls `_process_fallback_learning()` after Step 7c
63. `test_step7d_failure_nonfatal_in_dream_cycle` — Step 7d raises → dream cycle continues to report
64. `test_dreamreport_fallback_fields` — DreamReport has `fallback_evolutions` and `fallback_events_processed` with default 0
65. `test_dreamreport_populated_from_step7d` — Step 7d results flow into DreamReport fields

### Test Class 9: `TestEndToEnd`
66. `test_full_pipeline_execution_failure` — procedure matched → replay → act fails → LLM re-run → LLM succeeds → event emitted → dream cycle → FIX evolution → new procedure stored
67. `test_full_pipeline_quality_gate_near_miss` — procedure matched but quality gate rejects → LLM succeeds → event emitted → dream cycle → FIX evolution with targeted evidence
68. `test_full_pipeline_score_threshold_near_miss` — procedure found but below threshold → LLM succeeds → event emitted → dream cycle → evolution uses comparison

---

## Cross-Cutting Requirements

- **DRY:** Reuse `evolve_with_retry()`, `_format_episode_blocks()`, `_parse_procedure_json()`, `_build_steps_from_data()`, `_generate_content_diff()`. Extract `_decide_via_llm()` from `decide()` for reuse by `_run_llm_fallback()`. Do NOT duplicate any helper logic.
- **Backward compatibility:** Step 7/7b/7c behavior unchanged. `_FIX_SYSTEM_PROMPT` and `evolve_fix_procedure()` unchanged (Step 7b still uses them). `_FALLBACK_FIX_SYSTEM_PROMPT` and `evolve_fix_from_fallback()` are additive.
- **Metric semantics:** Moving completion/fallback recording changes when counters increment, but the counter columns and diagnostic thresholds are unchanged. For base CognitiveAgent (act always success=True), effective metric values don't change.
- **Log-and-degrade:** All new code paths (service recovery, event emission, event handling, queue processing, evolution) must NEVER crash the system. All errors caught and logged at debug level. Fallback learning is enhancement, not critical path.
- **Anti-loop guard:** Step 7d shares `_addressed_degradations` with Step 7b and proactive scan. Same `EVOLUTION_COOLDOWN_SECONDS` (72h).
- **Conservative default:** LLM failure during evolution → skip. Queue overflow → evict oldest. Missing procedure → skip. No aggressive retry beyond `evolve_with_retry()`.
- **No blocking:** Event emission is fire-and-forget. Service recovery adds latency to the failed case only (re-running LLM), which is acceptable because the alternative is returning a failure to the user.
- **Config-driven:** `MAX_FALLBACK_RESPONSE_CHARS`, `MAX_FALLBACK_QUEUE_SIZE` are config constants.

---

## Validation Checklist

### Part 0 — Metric Semantics Fix
- [ ] `record_completion()` removed from `_check_procedural_memory()`
- [ ] `record_fallback()` removed from `_check_procedural_memory()` (replaced by near-miss info)
- [ ] `record_completion()` called in `handle_intent()` after act() success for cached decisions
- [ ] `record_fallback()` called in `handle_intent()` after act() failure for cached decisions
- [ ] `record_selection()` and `record_applied()` unchanged (still in `_check_procedural_memory()`)
- [ ] `procedure_id` present in cached decision dict
- [ ] Non-cached decisions do not trigger metric recording

### Part 1 — Near-Miss Capture
- [ ] `_last_fallback_info` initialized as None in `__init__()`
- [ ] Score threshold rejection sets fallback info with type="score_threshold"
- [ ] Quality gate rejection sets fallback info with type="quality_gate"
- [ ] Negative veto sets fallback info with type="negative_veto"
- [ ] Format exception sets fallback info with type="format_exception"
- [ ] No-match (empty results) does NOT set fallback info
- [ ] fallback info cleared at start of `_check_procedural_memory()`
- [ ] All near-miss types include procedure_id and reason

### Part 2 — Service Recovery
- [ ] `_run_llm_fallback()` method exists on CognitiveAgent
- [ ] Method skips procedural memory and decision cache
- [ ] `_decide_via_llm()` extracted from `decide()` for DRY reuse
- [ ] Cached failure triggers LLM re-run
- [ ] LLM re-run success replaces result/report/success
- [ ] LLM re-run failure preserves original failure
- [ ] Service recovery runs BEFORE update_confidence()
- [ ] Service recovery runs BEFORE TASK_EXECUTION_COMPLETE event
- [ ] Service recovery exception is non-fatal
- [ ] Non-cached failures do NOT trigger re-run

### Part 3 — Event & Queue
- [ ] `EventType.PROCEDURE_FALLBACK_LEARNING` exists
- [ ] `ProcedureFallbackLearningEvent` dataclass exists with all fields
- [ ] Event emitted from handle_intent() when success=True and fallback_info is not None
- [ ] Event NOT emitted when LLM also failed (nothing to learn)
- [ ] LLM response truncated to MAX_FALLBACK_RESPONSE_CHARS
- [ ] `_last_fallback_info` cleared after event emission
- [ ] Event emission is fire-and-forget (try/except pass)
- [ ] `_fallback_learning_queue` initialized in DreamingEngine.__init__()
- [ ] `on_procedure_fallback_learning()` appends to queue
- [ ] Queue cap enforced (evicts oldest on overflow)
- [ ] Event subscription wired in startup/dreaming.py
- [ ] Config constants added: MAX_FALLBACK_RESPONSE_CHARS, MAX_FALLBACK_QUEUE_SIZE

### Part 4 — Targeted FIX Evolution
- [ ] `_FALLBACK_FIX_SYSTEM_PROMPT` exists in procedures.py
- [ ] Prompt mentions comparison between procedure and LLM response
- [ ] Prompt asks for divergence_point
- [ ] Prompt includes AD-541b READ-ONLY constraints
- [ ] `evolve_fix_from_fallback()` function exists with correct signature
- [ ] Function reuses `_format_episode_blocks()`, `_parse_procedure_json()`, `_build_steps_from_data()`, `_generate_content_diff()` (DRY)
- [ ] Function accepts and uses `retry_hint` parameter
- [ ] Result has evolution_type="FIX", generation=parent+1, parent linked
- [ ] LLM failure → returns None
- [ ] Malformed JSON → returns None

### Part 5 — Dream Step 7d
- [ ] `_process_fallback_learning()` method exists on DreamingEngine
- [ ] Drains and clears `_fallback_learning_queue`
- [ ] Groups events by procedure_id (most recent wins)
- [ ] Respects anti-loop guard (`_addressed_degradations`)
- [ ] execution_failure + success → deactivates parent procedure
- [ ] near-miss types + success → keeps parent active
- [ ] negative_veto → flags as extraction candidate, no evolution
- [ ] Uses `evolve_with_retry()` wrapper
- [ ] Saves evolved procedure with content_diff and change_summary
- [ ] One procedure failure doesn't stop processing others
- [ ] Returns stats dict with evolved/processed/skipped_cooldown/negative_veto_flagged
- [ ] Called in dream_cycle() after Step 7c
- [ ] Step 7d failure is non-fatal in dream cycle

### Part 6 — DreamReport
- [ ] `fallback_evolutions` field added with default 0
- [ ] `fallback_events_processed` field added with default 0
- [ ] Fields populated from Step 7d return stats

### Part 7 — Tests
- [ ] All ~68 tests pass
- [ ] No existing tests broken
- [ ] `pytest tests/test_fallback_learning.py -v` — all green
- [ ] `pytest tests/ -x --timeout=30` — full suite green (pre-existing failures excluded)

### Cross-Cutting
- [ ] Step 7/7b/7c behavior unchanged
- [ ] `evolve_fix_procedure()` and `_FIX_SYSTEM_PROMPT` unchanged
- [ ] `_decide_via_llm()` extracted from decide() (no behavior change to decide)
- [ ] Event import added to cognitive_agent.py
- [ ] EventType import updated in startup/dreaming.py
- [ ] Config constants imported where needed
