# AD-535: Graduated Compilation Levels — Build Prompt

**AD:** AD-535
**Depends:** AD-534 ✅, AD-534b ✅, AD-534c ✅, AD-357 ✅ (Earned Agency), AD-339 ✅ (Standing Orders)
**Scope:** OSS
**Branch:** `ad-535-graduated-compilation`

## Context

Currently, Cognitive JIT has a binary choice: full LLM reasoning (Level 1) or full deterministic replay (Level 4). Every new procedure starts at `compilation_level=1` but immediately replays at zero tokens — there is no graduated scaffolding. The `PROCEDURE_MIN_COMPILATION_LEVEL` config constant is set to `1` with the comment "AD-535 raises this."

AD-535 introduces four compilation levels with graduated LLM involvement:

| Level | Label | LLM Usage | Token Reduction |
|-------|-------|-----------|-----------------|
| 1 | Novice | Full LLM, no procedure | 0% (baseline) |
| 2 | Guided | LLM + procedure steps as hints | ~40% |
| 3 | Validated | Deterministic replay + LLM postcondition validation | ~80% |
| 4 | Autonomous | Pure deterministic, zero tokens | 100% |

Procedures progress upward through consecutive successes and demote on failure. Trust tiers (Earned Agency, AD-357) gate the maximum level an agent can use.

Additionally, `ProcedureStep` has four fields (`expected_output`, `expected_input`, `fallback_action`, `invariants`) that are populated by all extraction prompts but **never validated during replay**. AD-535 activates these at Level 3+ for per-step postcondition validation.

## Deferred Items (NOT in scope for AD-535)

These items are explicitly deferred to other ADs:

- **Level 5 (Expert — can teach others via Ward Room)** → AD-537 (Observational Learning)
- **Task criticality classification from Standing Orders** → AD-536 (Trust-Gated Promotion)
- **Captain approval workflow for Level 4 promotion on critical tasks** → AD-536 (Trust-Gated Promotion)
- **Procedure decay (lose a level per 30 days unused)** → AD-538 (Procedure Lifecycle)
- **Formal promotion ceremony / department chief approval** → AD-536 (Trust-Gated Promotion)

## Design Decisions

1. **Level transition trigger:** Metric-driven. `consecutive_successes` counter on each procedure record. N consecutive successes at current level → promote. Any failure → demote to Level 2 (Guided), not Level 1. Default promotion threshold: 3 consecutive successes (configurable as `COMPILATION_PROMOTION_THRESHOLD`). Reset `consecutive_successes` on any failure.

2. **Level 2 behavior (Guided):** Procedure steps injected into the LLM prompt as structured hints. Reuse `_decide_via_llm()` (extracted in AD-534b). Prepend the procedure's steps (formatted as guidance, not commands) to the observation context. The LLM reasons freely but has the procedure as scaffolding. ~40% token reduction because the LLM doesn't need to figure out the approach from scratch.

3. **Level 3 behavior (Validated):** Deterministic replay (same as current Level 4 behavior) followed by an LLM validation call. After replay produces output, call the LLM with a small validation prompt: the procedure output + `expected_output` + `postconditions` → "does this result satisfy the expected outcomes? YES/NO with reason." If YES → success, record completion. If NO → treat as failure, trigger service recovery via `_run_llm_fallback()`. ~80% token reduction (validation prompt is much smaller than full reasoning).

4. **Level 4 behavior (Autonomous):** Current zero-token replay behavior. No LLM involvement. This is what `_check_procedural_memory()` does today for all procedures, but AD-535 gates it behind quality threshold (must earn promotion through consecutive successes at Level 3).

5. **Trust tier clamping:** Ensign agents can only use Levels 1-2. Lieutenant agents can use Levels 1-4. Commander+ can use Levels 1-4 (Level 5 deferred to AD-537). Enforce in `_check_procedural_memory()` by clamping `procedure.compilation_level` to the agent's max allowed level based on trust score. New helper: `_max_compilation_level_for_trust(trust_score: float) -> int`.

6. **Per-step postcondition validation (Level 3):** Only activated at Level 3. Uses LLM to compare step result against `expected_output` (natural language description). A small LLM call per step: "Given step action: [action], output produced: [actual], expected outcome: [expected_output]. Does the output satisfy the expected outcome? Answer YES or NO with brief reason." This consumes the currently write-only `expected_output` field.

7. **`expected_input` / `invariants` / `fallback_action` activation:** At Level 3, before each step, validate `expected_input` against current context (same LLM pattern). If `invariants` are defined, check after step execution. If step fails and `fallback_action` is non-empty, include it as guidance in the service recovery prompt. These were write-only since AD-532 — AD-535 gives them purpose.

8. **Compound procedure interaction:** `_execute_compound_replay()` (AD-534c) currently operates at Level 4 (zero-token dispatch). At Level 3, each dispatched step's result is validated against its `expected_output` before dispatching the next step. The sequential dispatch loop in `_execute_compound_replay()` is the natural place. At Level 2, the compound procedure's steps are injected as hints but the LLM handles orchestration.

9. **Promotion location:** Promotion logic lives in `handle_intent()` after recording `record_completion()`. If procedure was cached and succeeded → call `record_consecutive_success()`. If `consecutive_successes >= COMPILATION_PROMOTION_THRESHOLD` AND agent trust allows next level → promote via `store.promote_compilation_level()`. Demotion on failure: immediately set `compilation_level = 2` and reset `consecutive_successes = 0`.

10. **No change to extraction prompts.** All extraction prompts already request `expected_output`, `expected_input`, `fallback_action`, `invariants`, `preconditions`, `postconditions`. The data model is already populated. AD-535 only adds consumption/validation logic.

## File-by-File Implementation

### Part 0: Config Constants

**File:** `src/probos/config.py`

Add after the AD-534b fallback learning constants:

```python
# AD-535: Graduated compilation
COMPILATION_PROMOTION_THRESHOLD: int = 3        # Consecutive successes to promote
COMPILATION_DEMOTION_LEVEL: int = 2              # Level to demote to on failure (Guided)
COMPILATION_MAX_LEVEL: int = 4                   # Maximum level (Level 5 deferred to AD-537)
COMPILATION_VALIDATION_TIMEOUT_SECONDS: float = 15.0  # LLM validation call timeout at Level 3
COMPILATION_TRUST_LEVEL_2_MIN: float = 0.0       # Ensign+ (any trust)
COMPILATION_TRUST_LEVEL_3_MIN: float = 0.5       # Lieutenant+ (TRUST_LIEUTENANT)
COMPILATION_TRUST_LEVEL_4_MIN: float = 0.5       # Lieutenant+ (TRUST_LIEUTENANT)
```

### Part 1: ProcedureStore — Consecutive Success Tracking

**File:** `src/probos/cognitive/procedure_store.py`

**1a. Schema migration:**

Add `consecutive_successes INTEGER DEFAULT 0` column to the `procedure_records` table. Follow the existing pattern for schema evolution (check if column exists, add if not).

**1b. New methods:**

```python
async def record_consecutive_success(self, procedure_id: str) -> int:
    """Increment consecutive_successes counter. Return new count."""
    # INCREMENT consecutive_successes WHERE id = procedure_id
    # Return the new value

async def reset_consecutive_successes(self, procedure_id: str) -> None:
    """Reset consecutive_successes to 0 (on any failure)."""
    # SET consecutive_successes = 0 WHERE id = procedure_id

async def promote_compilation_level(self, procedure_id: str, new_level: int) -> None:
    """Promote procedure to a higher compilation level. Reset consecutive_successes to 0."""
    # SET compilation_level = new_level, consecutive_successes = 0 WHERE id = procedure_id
    # Also update the in-memory Procedure object if cached
    # Log: "Procedure {name} promoted to Level {new_level}"

async def demote_compilation_level(self, procedure_id: str, new_level: int) -> None:
    """Demote procedure to a lower compilation level. Reset consecutive_successes to 0."""
    # SET compilation_level = new_level, consecutive_successes = 0 WHERE id = procedure_id
    # Log: "Procedure {name} demoted to Level {new_level}"
```

**1c. get_quality_metrics update:**

Add `consecutive_successes` to the dict returned by `get_quality_metrics()`, alongside the existing 4 counters and 4 derived rates.

### Part 2: Trust-Tier Clamping

**File:** `src/probos/cognitive/cognitive_agent.py`

**2a. New helper method:**

```python
def _max_compilation_level_for_trust(self, trust_score: float) -> int:
    """Return the maximum compilation level allowed for the given trust score.

    Ensign (trust < 0.5): Levels 1-2 (Novice, Guided)
    Lieutenant (trust 0.5-0.7): Levels 1-4 (full range)
    Commander+ (trust 0.7+): Levels 1-4 (Level 5 deferred to AD-537)
    """
    from probos.config import (
        COMPILATION_TRUST_LEVEL_3_MIN,
        COMPILATION_TRUST_LEVEL_4_MIN,
        COMPILATION_MAX_LEVEL,
    )
    if trust_score < COMPILATION_TRUST_LEVEL_3_MIN:
        return 2  # Ensign: max Level 2 (Guided)
    return min(4, COMPILATION_MAX_LEVEL)  # Lieutenant+: max Level 4
```

**2b. Clamp in `_check_procedural_memory()`:**

After loading the procedure (current line ~205), clamp its effective compilation level:

```python
# AD-535: Trust-tier clamping
trust_score = getattr(self, "_trust_score", 0.5)  # from perceive() context
max_level = self._max_compilation_level_for_trust(trust_score)
effective_level = min(procedure.compilation_level, max_level)
```

Use `effective_level` (not `procedure.compilation_level`) for all subsequent dispatch decisions in this method.

### Part 3: Level-Based Dispatch in `_check_procedural_memory()`

**File:** `src/probos/cognitive/cognitive_agent.py`

After the existing record_applied() call and procedure loading, replace the current unconditional text replay with level-based branching:

```python
# AD-535: Level-based dispatch
if effective_level <= 1:
    # Level 1 (Novice): Should not reach here — find_matching() filters by
    # min_compilation_level. If it does, fall through to LLM.
    return None

elif effective_level == 2:
    # Level 2 (Guided): LLM + procedure hints
    return self._build_guided_decision(procedure, observation, match_score)

elif effective_level == 3:
    # Level 3 (Validated): Deterministic replay + LLM validation
    return self._build_validated_decision(procedure, observation, match_score)

else:
    # Level 4 (Autonomous): Zero-token replay (current behavior)
    # existing _format_procedure_replay() + compound detection logic stays here
    ...
```

### Part 4: Level 2 — Guided Replay

**File:** `src/probos/cognitive/cognitive_agent.py`

**New method: `_build_guided_decision()`**

```python
async def _build_guided_decision(
    self, procedure: Any, observation: dict, match_score: float
) -> dict:
    """Level 2 (Guided): Call LLM with procedure steps injected as hints.

    The LLM reasons freely but has the learned procedure as scaffolding.
    ~40% token reduction vs full reasoning from scratch.
    """
    # Format procedure steps as guidance (not commands)
    hints = self._format_procedure_as_hints(procedure)

    # Inject hints into observation context
    guided_observation = dict(observation)
    guided_observation["procedure_hints"] = hints
    guided_observation["procedure_guidance"] = (
        f"A learned procedure '{procedure.name}' suggests the following approach. "
        f"Use these steps as guidance but apply your own judgment:\n\n{hints}"
    )

    # Call LLM with hints — reuse _decide_via_llm()
    decision = await self._decide_via_llm(guided_observation)

    # Tag for metric tracking
    decision["guided_by_procedure"] = True
    decision["procedure_id"] = procedure.id
    decision["procedure_name"] = procedure.name
    decision["compilation_level"] = 2
    return decision
```

**New method: `_format_procedure_as_hints()`**

```python
def _format_procedure_as_hints(self, procedure: Any) -> str:
    """Format procedure steps as guidance hints for Level 2 (Guided) replay.

    Differs from _format_procedure_replay() — framed as suggestions, not directives.
    Includes expected_input/output for each step as orientation.
    """
    lines = [f"Suggested approach based on prior success ('{procedure.name}'):"]
    for step in procedure.steps:
        line = f"  {step.step_number}. {step.action}"
        if step.expected_input:
            line += f"\n     Context: {step.expected_input}"
        if step.expected_output:
            line += f"\n     Expected result: {step.expected_output}"
        role = getattr(step, "agent_role", "")
        if role:
            line += f"\n     (Typically performed by: {role})"
        lines.append(line)
    if procedure.postconditions:
        lines.append(f"\nSuccess criteria: {procedure.postconditions}")
    return "\n".join(lines)
```

### Part 5: Level 3 — Validated Replay

**File:** `src/probos/cognitive/cognitive_agent.py`

**New method: `_build_validated_decision()`**

```python
async def _build_validated_decision(
    self, procedure: Any, observation: dict, match_score: float
) -> dict:
    """Level 3 (Validated): Deterministic replay + LLM postcondition validation.

    Execute procedure deterministically (same as Level 4), then call LLM
    to validate the result against expected outcomes. ~80% token reduction.
    If validation fails, return None to trigger LLM fallback.
    """
    # Step 1: Deterministic replay (same as Level 4)
    replay_output = self._format_procedure_replay(procedure, match_score)

    # Step 2: Validate via LLM
    validation_passed = await self._validate_replay_postconditions(
        procedure, replay_output, observation
    )

    if not validation_passed:
        # Validation failed — fall through to LLM via service recovery
        # Record as near-miss for AD-534b fallback learning
        self._last_fallback_info = {
            "type": "validation_failure",
            "procedure_id": procedure.id,
            "procedure_name": procedure.name,
            "score": match_score,
            "compilation_level": 3,
        }
        logger.info(
            "Level 3 validation failed for procedure %s — falling back to LLM",
            procedure.name,
        )
        return None  # Falls through to LLM in decide()

    # Validation passed — return as cached decision
    # Check for compound procedures (same logic as Level 4)
    is_compound = any(
        getattr(step, "resolved_agent_type", "") for step in procedure.steps
    ) and len(procedure.steps) >= 2

    decision = {
        "action": "execute",
        "llm_output": replay_output,
        "cached": True,
        "procedure_id": procedure.id,
        "procedure_name": procedure.name,
        "compilation_level": 3,
        "validated": True,
    }
    if is_compound:
        decision["compound"] = True
        decision["procedure"] = procedure

    return decision
```

**New method: `_validate_replay_postconditions()`**

```python
async def _validate_replay_postconditions(
    self, procedure: Any, replay_output: str, observation: dict
) -> bool:
    """Validate deterministic replay output against procedure postconditions.

    Uses a small LLM call to check whether the output satisfies expected outcomes.
    Returns True if validation passes, False otherwise.
    """
    from probos.config import COMPILATION_VALIDATION_TIMEOUT_SECONDS

    # Build validation prompt from procedure metadata
    validation_context = []

    # Procedure-level postconditions
    if procedure.postconditions:
        validation_context.append(f"Expected postconditions: {procedure.postconditions}")

    # Step-level expected outputs
    for step in procedure.steps:
        if step.expected_output:
            validation_context.append(
                f"Step {step.step_number} expected output: {step.expected_output}"
            )
        if step.invariants:
            for inv in step.invariants:
                validation_context.append(f"Step {step.step_number} invariant: {inv}")

    if not validation_context:
        # No postconditions defined — pass by default
        return True

    validation_prompt = (
        "You are a postcondition validator. Given the following procedure replay output "
        "and expected outcomes, determine if the output satisfies the expectations.\n\n"
        f"Procedure: {procedure.name}\n"
        f"Replay output:\n{replay_output[:2000]}\n\n"
        f"Expected outcomes:\n" + "\n".join(validation_context) + "\n\n"
        "Does the output satisfy the expected outcomes? "
        "Answer ONLY 'YES' or 'NO' followed by a brief reason."
    )

    try:
        llm_client = getattr(self, "_llm_client", None)
        if not llm_client:
            # No LLM client available — pass by default
            return True

        response = await asyncio.wait_for(
            llm_client.generate(validation_prompt, max_tokens=100),
            timeout=COMPILATION_VALIDATION_TIMEOUT_SECONDS,
        )

        answer = response.strip().upper()
        return answer.startswith("YES")

    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning(
            "Level 3 validation call failed for procedure %s: %s — passing by default",
            procedure.name, exc,
        )
        # On validation infrastructure failure, pass by default (fail-open for non-critical)
        return True
```

### Part 6: Level 3 Compound Validation

**File:** `src/probos/cognitive/cognitive_agent.py`

Modify `_execute_compound_replay()` to support Level 3 per-step validation.

In the sequential dispatch loop (after dispatching each step), if `compilation_level == 3`, validate the step result against `step.expected_output`:

```python
# Inside _execute_compound_replay(), after collecting step result:
if compilation_level == 3 and step.expected_output:
    step_valid = await self._validate_step_postcondition(
        step, step_result_text
    )
    if not step_valid:
        logger.info(
            "Compound step %d validation failed — aborting compound replay",
            step.step_number,
        )
        # Fall back to single-agent text replay
        return {"success": True, "result": text_fallback, "compound_aborted": True}
```

**New method: `_validate_step_postcondition()`**

```python
async def _validate_step_postcondition(
    self, step: Any, actual_output: str
) -> bool:
    """Validate a single step's output against its expected_output.

    Small LLM call. Used at Level 3 during compound replay.
    """
    from probos.config import COMPILATION_VALIDATION_TIMEOUT_SECONDS

    if not step.expected_output:
        return True

    prompt = (
        f"Step {step.step_number}: {step.action}\n"
        f"Actual output: {actual_output[:1000]}\n"
        f"Expected output: {step.expected_output}\n\n"
        "Does the actual output satisfy the expected output? YES or NO."
    )

    try:
        llm_client = getattr(self, "_llm_client", None)
        if not llm_client:
            return True
        response = await asyncio.wait_for(
            llm_client.generate(prompt, max_tokens=50),
            timeout=COMPILATION_VALIDATION_TIMEOUT_SECONDS,
        )
        return response.strip().upper().startswith("YES")
    except Exception:
        return True  # Fail-open
```

### Part 7: Promotion & Demotion Logic in `handle_intent()`

**File:** `src/probos/cognitive/cognitive_agent.py`

In `handle_intent()`, after the existing `record_completion()` / `record_fallback()` logic (post-execution), add promotion/demotion handling:

```python
# AD-535: Compilation level promotion/demotion
if decision.get("procedure_id") and hasattr(self, "_procedure_store"):
    procedure_id = decision["procedure_id"]
    store = self._procedure_store

    if result.get("success"):
        # Success — increment consecutive counter, check for promotion
        new_count = await store.record_consecutive_success(procedure_id)

        from probos.config import (
            COMPILATION_PROMOTION_THRESHOLD,
            COMPILATION_MAX_LEVEL,
        )

        # Get current procedure level
        proc = await store.get(procedure_id)
        if proc and new_count >= COMPILATION_PROMOTION_THRESHOLD:
            trust_score = getattr(self, "_trust_score", 0.5)
            max_allowed = self._max_compilation_level_for_trust(trust_score)
            next_level = proc.compilation_level + 1

            if next_level <= min(max_allowed, COMPILATION_MAX_LEVEL):
                await store.promote_compilation_level(procedure_id, next_level)
                logger.info(
                    "Procedure '%s' promoted to Level %d after %d consecutive successes",
                    proc.name, next_level, new_count,
                )
    else:
        # Failure — demote to Level 2 (Guided), reset consecutive counter
        from probos.config import COMPILATION_DEMOTION_LEVEL

        proc = await store.get(procedure_id)
        if proc and proc.compilation_level > COMPILATION_DEMOTION_LEVEL:
            await store.demote_compilation_level(
                procedure_id, COMPILATION_DEMOTION_LEVEL
            )
            logger.info(
                "Procedure '%s' demoted to Level %d after failure",
                proc.name, COMPILATION_DEMOTION_LEVEL,
            )
        else:
            await store.reset_consecutive_successes(procedure_id)
```

### Part 8: Level 2 Metric Recording

**File:** `src/probos/cognitive/cognitive_agent.py`

Level 2 (Guided) decisions have `guided_by_procedure: True` and `procedure_id` set, but `cached` is NOT set (since the LLM was called). Update `handle_intent()` to recognize guided decisions:

```python
# AD-535: Track Level 2 (Guided) procedure association
if decision.get("guided_by_procedure") and decision.get("procedure_id"):
    procedure_id = decision["procedure_id"]
    # Record completion/fallback for the guiding procedure
    if result.get("success"):
        await self._procedure_store.record_completion(procedure_id)
        await self._procedure_store.record_consecutive_success(procedure_id)
    else:
        await self._procedure_store.record_fallback(procedure_id)
        await self._procedure_store.reset_consecutive_successes(procedure_id)
```

### Part 9: PROCEDURE_MIN_COMPILATION_LEVEL Update

**File:** `src/probos/config.py`

Change the existing constant:

```python
PROCEDURE_MIN_COMPILATION_LEVEL = 2  # AD-535: Minimum Level 2 (Guided) for replay dispatch
```

This means `find_matching()` will only return procedures at Level 2+ for replay. Level 1 (Novice) procedures are never replayed — they serve as extraction records awaiting promotion. Newly extracted procedures start at Level 1 and must be promoted to Level 2 (via 3 consecutive LLM successes on the same intent pattern) before they can influence replay.

**Important:** This changes the behavior of ALL existing procedures. Existing Level 1 procedures will no longer be replayed until promoted. To handle migration, add a one-time promotion in ProcedureStore initialization: if any procedure has `compilation_level = 1` AND `total_completions >= COMPILATION_PROMOTION_THRESHOLD`, auto-promote to Level 2.

### Part 10: Migration — Existing Procedures

**File:** `src/probos/cognitive/procedure_store.py`

In the `_initialize_db()` method, after schema migration, add:

```python
# AD-535: Auto-promote qualifying Level 1 procedures to Level 2
await self._migrate_qualifying_procedures()
```

```python
async def _migrate_qualifying_procedures(self) -> None:
    """One-time migration: promote Level 1 procedures that already have
    enough completions to Level 2 (Guided). Handles transition from
    pre-AD-535 binary replay to graduated compilation."""
    from probos.config import COMPILATION_PROMOTION_THRESHOLD

    async with aiosqlite.connect(self._db_path) as db:
        cursor = await db.execute(
            "UPDATE procedure_records SET compilation_level = 2 "
            "WHERE compilation_level = 1 AND total_completions >= ? AND is_active = 1",
            (COMPILATION_PROMOTION_THRESHOLD,),
        )
        if cursor.rowcount > 0:
            logger.info(
                "AD-535 migration: promoted %d procedures from Level 1 to Level 2",
                cursor.rowcount,
            )
        await db.commit()
```

## Tests

**File:** `tests/test_graduated_compilation.py`

Create this file with the following test classes:

### TestCompilationConfig (4 tests)
1. `test_promotion_threshold_default` — `COMPILATION_PROMOTION_THRESHOLD == 3`
2. `test_demotion_level_default` — `COMPILATION_DEMOTION_LEVEL == 2`
3. `test_max_level_default` — `COMPILATION_MAX_LEVEL == 4`
4. `test_min_compilation_level` — `PROCEDURE_MIN_COMPILATION_LEVEL == 2`

### TestTrustClamping (5 tests)
5. `test_ensign_max_level_2` — trust 0.3 → max Level 2
6. `test_lieutenant_max_level_4` — trust 0.5 → max Level 4
7. `test_commander_max_level_4` — trust 0.7 → max Level 4
8. `test_senior_max_level_4` — trust 0.9 → max Level 4
9. `test_clamping_applied_in_check_procedural_memory` — procedure at Level 4 + Ensign trust → effective Level 2

### TestConsecutiveSuccessTracking (6 tests)
10. `test_record_consecutive_success_increments` — 1, 2, 3 after three calls
11. `test_reset_consecutive_successes` — drops to 0
12. `test_promote_compilation_level` — updates level AND resets consecutive counter
13. `test_demote_compilation_level` — updates level AND resets consecutive counter
14. `test_get_quality_metrics_includes_consecutive` — `consecutive_successes` in returned dict
15. `test_schema_migration_adds_column` — `consecutive_successes` column exists after init

### TestLevel2Guided (8 tests)
16. `test_guided_decision_calls_llm` — LLM is called (not zero-token)
17. `test_guided_decision_includes_procedure_hints` — observation contains procedure steps
18. `test_format_procedure_as_hints` — hint format includes step numbers, actions, expected outputs
19. `test_format_hints_with_agent_role` — includes "(Typically performed by: ...)"
20. `test_format_hints_with_postconditions` — includes success criteria
21. `test_format_hints_no_expected_output` — graceful when expected_output is empty
22. `test_guided_decision_tagged` — result has `guided_by_procedure=True`, `procedure_id`, `compilation_level=2`
23. `test_guided_metrics_recorded` — success/failure recorded against guiding procedure

### TestLevel3Validated (10 tests)
24. `test_validated_replay_calls_validation` — LLM validation call made after replay
25. `test_validated_replay_passes` — validation returns YES → cached decision returned
26. `test_validated_replay_fails` — validation returns NO → returns None (falls through to LLM)
27. `test_validated_replay_fail_sets_fallback_info` — `_last_fallback_info` type is `validation_failure`
28. `test_validation_no_postconditions_passes` — empty postconditions → passes by default
29. `test_validation_timeout_passes` — timeout → passes by default (fail-open)
30. `test_validation_includes_postconditions` — prompt contains procedure.postconditions
31. `test_validation_includes_step_expected_outputs` — prompt contains step-level expected_output
32. `test_validation_includes_invariants` — prompt contains step invariants
33. `test_validated_compound_detection` — compound procedures detected at Level 3

### TestLevel3StepValidation (6 tests)
34. `test_validate_step_postcondition_passes` — step output matches expected → True
35. `test_validate_step_postcondition_fails` — step output doesn't match → False
36. `test_validate_step_no_expected_output` — empty expected_output → True
37. `test_validate_step_llm_failure_passes` — LLM error → True (fail-open)
38. `test_compound_level_3_step_validation` — compound replay validates each step
39. `test_compound_level_3_step_failure_aborts` — step validation fails → aborts compound, returns text fallback

### TestLevel4Autonomous (4 tests)
40. `test_level_4_zero_token_replay` — no LLM call, same as current behavior
41. `test_level_4_compound_dispatch` — compound procedures dispatched same as AD-534c
42. `test_level_4_no_validation_call` — no postcondition validation at Level 4
43. `test_level_4_requires_trust` — Ensign cannot use Level 4 (clamped to 2)

### TestPromotion (10 tests)
44. `test_promote_after_consecutive_successes` — 3 successes → Level 2 to Level 3
45. `test_no_promote_below_threshold` — 2 successes → stays at current level
46. `test_promote_resets_counter` — after promotion, consecutive_successes = 0
47. `test_promote_capped_by_trust` — Ensign cannot promote beyond Level 2
48. `test_promote_capped_by_max_level` — cannot promote beyond COMPILATION_MAX_LEVEL (4)
49. `test_demote_on_failure` — any failure → demote to Level 2
50. `test_demote_resets_counter` — after demotion, consecutive_successes = 0
51. `test_no_demote_if_already_level_2` — failure at Level 2 → stays at Level 2, resets counter
52. `test_guided_success_counts_for_promotion` — Level 2 guided successes increment consecutive counter
53. `test_guided_failure_resets_counter` — Level 2 guided failure resets counter

### TestMigration (4 tests)
54. `test_migrate_qualifying_procedures` — Level 1 with enough completions → auto-promoted to Level 2
55. `test_migrate_ignores_low_completion` — Level 1 with few completions → stays Level 1
56. `test_migrate_ignores_inactive` — inactive Level 1 not promoted
57. `test_migrate_idempotent` — running migration twice has no adverse effect

### TestLevelDispatchRouting (5 tests)
58. `test_level_1_not_dispatched` — Level 1 procedures filtered by PROCEDURE_MIN_COMPILATION_LEVEL
59. `test_level_2_routes_to_guided` — Level 2 → _build_guided_decision()
60. `test_level_3_routes_to_validated` — Level 3 → _build_validated_decision()
61. `test_level_4_routes_to_autonomous` — Level 4 → current replay behavior
62. `test_mixed_levels_in_store` — multiple procedures at different levels, correct one dispatched

## Validation Checklist

### Config
- [ ] `COMPILATION_PROMOTION_THRESHOLD = 3`
- [ ] `COMPILATION_DEMOTION_LEVEL = 2`
- [ ] `COMPILATION_MAX_LEVEL = 4`
- [ ] `COMPILATION_VALIDATION_TIMEOUT_SECONDS = 15.0`
- [ ] `PROCEDURE_MIN_COMPILATION_LEVEL = 2` (changed from 1)
- [ ] Trust tier constants defined

### ProcedureStore
- [ ] `consecutive_successes` column added to schema
- [ ] `record_consecutive_success()` increments and returns new count
- [ ] `reset_consecutive_successes()` sets to 0
- [ ] `promote_compilation_level()` updates level + resets counter
- [ ] `demote_compilation_level()` updates level + resets counter
- [ ] `get_quality_metrics()` includes `consecutive_successes`
- [ ] Migration auto-promotes qualifying Level 1 procedures

### Trust Clamping
- [ ] `_max_compilation_level_for_trust()` returns correct max per trust tier
- [ ] `_check_procedural_memory()` clamps effective level
- [ ] Ensign agents cannot use Level 3 or 4

### Level 2 (Guided)
- [ ] `_build_guided_decision()` calls `_decide_via_llm()` with hints injected
- [ ] `_format_procedure_as_hints()` renders steps as suggestions
- [ ] Hints include expected_input, expected_output, agent_role, postconditions
- [ ] Decision tagged with `guided_by_procedure=True` and `procedure_id`
- [ ] Guided decisions tracked for promotion/demotion in `handle_intent()`

### Level 3 (Validated)
- [ ] `_build_validated_decision()` replays deterministically then validates
- [ ] `_validate_replay_postconditions()` calls LLM with postconditions + expected outputs
- [ ] Validation failure → returns None (triggers LLM fallback)
- [ ] Validation failure sets `_last_fallback_info` with type `validation_failure`
- [ ] No postconditions → passes by default
- [ ] LLM timeout/error → passes by default (fail-open)
- [ ] Compound procedures at Level 3 get per-step validation
- [ ] `_validate_step_postcondition()` checks individual steps
- [ ] Step validation failure aborts compound replay

### Level 4 (Autonomous)
- [ ] Zero-token replay (current behavior) unchanged
- [ ] Compound dispatch (AD-534c) unchanged
- [ ] Gated behind trust (Lieutenant+)

### Promotion/Demotion
- [ ] Success → `record_consecutive_success()`
- [ ] 3 consecutive successes → promote to next level
- [ ] Promotion resets consecutive counter
- [ ] Promotion capped by trust tier
- [ ] Promotion capped by `COMPILATION_MAX_LEVEL`
- [ ] Failure → demote to Level 2
- [ ] Demotion resets consecutive counter
- [ ] At Level 2 failure → no demotion, just reset counter
- [ ] Level 2 guided successes/failures tracked for promotion

### Deferred Items
- [ ] Level 5 (teaching) NOT implemented — deferred to AD-537
- [ ] Task criticality NOT implemented — deferred to AD-536
- [ ] Captain approval workflow NOT implemented — deferred to AD-536
- [ ] Procedure decay NOT implemented — deferred to AD-538
- [ ] Procedure promotion ceremony NOT implemented — deferred to AD-536

### Regression
- [ ] All existing Cognitive JIT tests pass (387 tests)
- [ ] All existing test suite passes
- [ ] Procedures with `compilation_level=1` and sufficient completions auto-migrate to Level 2
- [ ] Procedures with `compilation_level=1` and insufficient completions remain at Level 1 (not replayed)
- [ ] Existing compound replay (AD-534c) works at Level 4
- [ ] Existing fallback learning (AD-534b) works with new near-miss type `validation_failure`
- [ ] Existing evolution (FIX) preserves compilation_level
- [ ] Existing evolution (DERIVED) sets `max(parent_levels) - 1`
- [ ] New CAPTURED procedures start at Level 1 (unchanged)
