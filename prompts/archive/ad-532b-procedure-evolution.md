# AD-532b: Procedure Evolution Types (FIX / DERIVED)

**Context:** AD-532 (CLOSED) extracts CAPTURED procedures from success-dominant episode clusters. AD-533 (CLOSED) persists them with a Version DAG schema (lineage parents table, `content_diff`/`change_summary` columns, `deactivate()` method). AD-534 (CLOSED) replays matching procedures at zero tokens and populates quality metrics (`record_selection()`, `record_applied()`, `record_completion()`, `record_fallback()`). AD-534's `_diagnose_procedure_health()` already computes FIX/DERIVED diagnoses but only logs them.

AD-532b closes the loop: when procedure quality degrades at runtime, the dream cycle detects the degradation and **evolves** the procedure — either repairing it in-place (FIX) or creating a specialized variant (DERIVED).

**Problem:** Procedures are static after extraction. When the environment changes (codebase updates, new patterns, user behavior shifts), a once-effective procedure may degrade. Quality metrics detect this (falling `effective_rate`, rising `fallback_rate`), and `_diagnose_procedure_health()` produces a diagnosis string — but nothing acts on it. Without evolution, degraded procedures either keep failing (wasting the replay attempt + LLM fallback) or must be manually deleted.

**Scope:** This AD covers:
- **FIX evolution** — Re-extract from fresh episodes when a procedure degrades. Deactivate parent, increment generation, set lineage.
- **DERIVED evolution** — Create specialized variant from 1+ parent procedures. Parents stay active. New branch in DAG.
- **Evolution prompts** — Modified LLM prompts for FIX (include parent + failure context) and DERIVED (include parents + specialization goal).
- **`content_diff` / `change_summary`** — Populate the existing AD-533 schema columns.
- **Anti-loop guard** — `_addressed_degradations` dict prevents re-evolving the same procedure within a cooldown window.
- **Dream cycle Step 7b** — Evolution scan runs after CAPTURED extraction.
- **DreamReport extension** — `procedures_evolved` counter.

**Deferred (later ADs):**
- AD-532e: LLM confirmation gate before evolution, apply-retry with LLM correction, post-execution reactive trigger, proactive periodic health scan trigger
- AD-534b: Fallback learning (replay fails → LLM succeeds → compare → trigger FIX)
- AD-535: Graduated compilation levels (Dreyfus 1-5, level transitions)
- AD-538: Procedure lifecycle management (decay, re-validation, dedup, archival)

**Dependencies (all COMPLETE):**
- AD-533 ✅ — `ProcedureStore` with `save()`, `deactivate()`, `get_quality_metrics()`, `list_active()`, lineage parents, `content_diff`/`change_summary` columns
- AD-534 ✅ — Quality metrics populated via `record_*()` methods, `_diagnose_procedure_health()` computes diagnoses
- AD-532 ✅ — `extract_procedure_from_cluster()`, `Procedure`/`ProcedureStep` dataclasses, `_SYSTEM_PROMPT`
- EpisodicMemory ✅ — `recall_by_intent(intent_type)` finds episodes by intent type

**Principles:** SOLID (evolution functions = single responsibility — produce evolved procedures), DRY (reuse `_FENCE_RE` regex and JSON parsing from `extract_procedure_from_cluster()`; reuse `ProcedureStore.save()`/`deactivate()` for persistence), Law of Demeter (DreamingEngine calls evolution functions, doesn't reach into store internals), Fail Fast (log-and-degrade — evolution failures don't break dream cycles), Cloud-Ready Storage (all persistence via `ProcedureStore`, never direct DB access).

---

## Part 0: Evolution Functions — `evolve_fix_procedure()` and `evolve_derived_procedure()`

### File: `src/probos/cognitive/procedures.py`

These functions live alongside `extract_procedure_from_cluster()` — they are extraction variants, same file, same patterns.

### 0a: FIX System Prompt

Add a new constant `_FIX_SYSTEM_PROMPT` after the existing `_SYSTEM_PROMPT`. This prompt instructs the LLM to repair a degraded procedure:

```python
_FIX_SYSTEM_PROMPT = """\
You are a procedure repair engine. A previously extracted procedure has degraded
in quality (high fallback rate, low completion rate, or low effectiveness).
You are given the original procedure, its quality metrics, the specific diagnosis,
and fresh successful episodes that represent how the task is NOW being accomplished.

Your job: produce a REPAIRED version of the procedure that reflects current reality.

Output ONLY valid JSON matching this schema:
{
  "name": "short human-readable label",
  "description": "what this procedure accomplishes",
  "steps": [
    {
      "step_number": 1,
      "action": "what to do",
      "expected_input": "state before this step",
      "expected_output": "state after this step",
      "fallback_action": "what to do if this step fails",
      "invariants": ["what must remain true"]
    }
  ],
  "preconditions": ["what must be true before starting"],
  "postconditions": ["what must be true when done"],
  "change_summary": "one-sentence summary of what changed and why"
}

Rules:
- Keep the same logical intent — this is a REPAIR, not a new procedure
- Reference episode IDs from the fresh episodes, do not reconstruct narratives
- Steps should be deterministic and replayable without LLM assistance
- The change_summary must explain what was wrong and what you fixed
- If no repair can be determined, return {"error": "no_repair_possible"}
"""
```

### 0b: DERIVED System Prompt

Add a new constant `_DERIVED_SYSTEM_PROMPT`:

```python
_DERIVED_SYSTEM_PROMPT = """\
You are a procedure specialization engine. You are given one or more parent
procedures and episodes showing contexts where the parent(s) don't fully succeed.
Your job: create a SPECIALIZED variant that handles the failing cases better.

Output ONLY valid JSON matching this schema:
{
  "name": "short human-readable label (should reflect the specialization)",
  "description": "what this specialized procedure accomplishes",
  "steps": [
    {
      "step_number": 1,
      "action": "what to do",
      "expected_input": "state before this step",
      "expected_output": "state after this step",
      "fallback_action": "what to do if this step fails",
      "invariants": ["what must remain true"]
    }
  ],
  "preconditions": ["what must be true before starting (should be MORE specific than parent)"],
  "postconditions": ["what must be true when done"],
  "change_summary": "one-sentence summary of how this specializes the parent(s)"
}

Rules:
- The preconditions should be NARROWER than the parent — this handles a specific subset
- Reference episode IDs, do not reconstruct narratives
- Steps should be deterministic and replayable without LLM assistance
- If no useful specialization can be determined, return {"error": "no_specialization_possible"}
"""
```

### 0c: `evolve_fix_procedure()` Function

Add this function after `extract_procedure_from_cluster()`:

```python
async def evolve_fix_procedure(
    parent: Procedure,
    diagnosis: str,
    metrics: dict[str, Any],
    fresh_episodes: list[Any],
    llm_client: Any,
) -> Procedure | None:
    """Evolve a FIX replacement for a degraded procedure.

    The parent is deactivated by the caller after successful evolution.
    Returns None if the LLM cannot produce a repair.
    """
```

**Implementation:**
1. Build user prompt including:
   - The parent procedure as JSON (`parent.to_dict()`) under a "=== DEGRADED PROCEDURE ===" header
   - The diagnosis string (e.g., `"FIX:high_fallback_rate"`)
   - The quality metrics dict (e.g., `"effective_rate: 0.35, fallback_rate: 0.52"`)
   - Fresh episodes formatted with AD-541b READ-ONLY framing (reuse the same block format from `extract_procedure_from_cluster()`)
   - Instruction: "Repair this procedure based on the fresh episodes. The diagnosis explains what degraded."
2. Call `llm_client.complete()` with `_FIX_SYSTEM_PROMPT`, `tier="standard"`, `temperature=0.0`, `max_tokens=2048`
3. Parse response using `_FENCE_RE` regex (same as existing extraction)
4. Check for `{"error": ...}` — return None
5. Build `Procedure` from parsed JSON with:
   - `evolution_type="FIX"`
   - `generation=parent.generation + 1`
   - `parent_procedure_ids=[parent.id]`
   - `intent_types=parent.intent_types` (same intent family)
   - `origin_cluster_id=parent.origin_cluster_id` (preserves lineage to original cluster)
   - `origin_agent_ids=parent.origin_agent_ids`
   - `compilation_level=parent.compilation_level` (FIX preserves the parent's level)
   - `tags=parent.tags` (inherit tags)
6. Generate `content_diff` using `difflib.unified_diff()` on `json.dumps(parent.to_dict(), indent=2)` vs. `json.dumps(new_procedure.to_dict(), indent=2)`
7. Extract `change_summary` from the LLM response JSON (the `"change_summary"` field)
8. Return the new `Procedure` (caller handles persistence + deactivation)
9. Wrap entire function body in `try/except Exception` — log-and-degrade, return None

**Important:** The `content_diff` and `change_summary` are NOT stored on the `Procedure` dataclass — they are returned separately (as a tuple or via a small return dataclass) so the caller can pass them to `ProcedureStore.save()` and the SQLite update. Add a return type `tuple[Procedure, str, str] | None` (procedure, content_diff, change_summary) or create a small `EvolutionResult` dataclass in the same file:

```python
@dataclass
class EvolutionResult:
    """Result of a FIX or DERIVED evolution."""
    procedure: Procedure
    content_diff: str
    change_summary: str
```

### 0d: `evolve_derived_procedure()` Function

Add this function after `evolve_fix_procedure()`:

```python
async def evolve_derived_procedure(
    parents: list[Procedure],
    fresh_episodes: list[Any],
    llm_client: Any,
) -> EvolutionResult | None:
    """Create a specialized DERIVED variant from 1+ parent procedures.

    Parents stay active (DERIVED branches, does not replace).
    Returns None if the LLM cannot produce a specialization.
    """
```

**Implementation:**
1. Build user prompt including:
   - Each parent procedure as JSON under numbered "=== PARENT PROCEDURE N ===" headers
   - Fresh episodes (both success and failure cases if available) with AD-541b READ-ONLY framing
   - For multi-parent: "Create a specialized procedure that combines the strengths of these parent procedures for the specific context shown in the episodes."
   - For single-parent: "Create a specialized variant that handles the cases where the parent procedure fails."
2. Call `llm_client.complete()` with `_DERIVED_SYSTEM_PROMPT`, `tier="standard"`, `temperature=0.0`, `max_tokens=2048`
3. Parse response (same `_FENCE_RE` pattern)
4. Check for `{"error": ...}` — return None
5. Build `Procedure` with:
   - `evolution_type="DERIVED"`
   - `generation=max(p.generation for p in parents) + 1`
   - `parent_procedure_ids=[p.id for p in parents]`
   - `intent_types` = union of all parents' `intent_types`
   - `origin_cluster_id=""` (DERIVED has no single origin cluster)
   - `origin_agent_ids` = union of all parents' `origin_agent_ids`
   - `compilation_level=max(p.compilation_level for p in parents) - 1` (starts one level below best parent, minimum 1)
   - `tags` = union of all parents' tags
6. Generate `content_diff` — for single parent, diff against parent. For multi-parent, diff against the first parent (convention).
7. Extract `change_summary` from LLM response
8. Return `EvolutionResult(procedure, content_diff, change_summary)`
9. Wrap in `try/except Exception` — log-and-degrade, return None

### 0e: Helper — Build Episode Blocks

Extract the AD-541b episode block formatting into a shared helper so all three extraction functions (CAPTURED, FIX, DERIVED) use the same format:

```python
def _format_episode_blocks(episodes: list[Any]) -> str:
    """Format episodes as AD-541b READ-ONLY blocks."""
    blocks = []
    for ep in episodes:
        block = (
            "=== READ-ONLY EPISODE (do not modify, summarize, or reinterpret) ===\n"
            f"Episode ID: {ep.id}\n"
            f"User Input: {ep.user_input}\n"
            f"Outcomes: {json.dumps(ep.outcomes, default=str)}\n"
            f"DAG Summary: {json.dumps(ep.dag_summary, default=str)}\n"
            f"Reflection: {ep.reflection or 'none'}\n"
            f"Agents: {ep.agent_ids}\n"
            "=== END READ-ONLY EPISODE ==="
        )
        blocks.append(block)
    return "\n\n".join(blocks)
```

Refactor `extract_procedure_from_cluster()` to call `_format_episode_blocks()` instead of its inline loop. This is DRY — three functions, one format.

---

## Part 1: `ProcedureStore` Enhancement — Persist Evolution Metadata

### File: `src/probos/cognitive/procedure_store.py`

The `save()` method already persists procedures to SQLite + Ship's Records + ChromaDB. It already writes `parent_procedure_ids` to the lineage table. But it does NOT currently write `content_diff` or `change_summary` — those columns exist but are always NULL.

### 1a: Extend `save()` to accept optional `content_diff` and `change_summary`

Add optional parameters to `save()`:

```python
async def save(
    self, procedure: Procedure,
    *, content_diff: str = "", change_summary: str = "",
) -> None:
```

In the SQLite INSERT/UPDATE, populate `content_diff` and `change_summary` from these parameters.

### 1b: Return evolution metadata from `get()`

The `get()` method reconstructs a `Procedure` from `content_snapshot`. It should also return `content_diff` and `change_summary` if they exist. Since the `Procedure` dataclass doesn't have these fields, either:
- **(a)** Return them as a separate dict alongside the Procedure — `get()` returns `tuple[Procedure, dict]`
- **(b)** Just make them available via a separate method `get_evolution_metadata(procedure_id)` returning `{"content_diff": ..., "change_summary": ...}`

**Choose (b)** — it's non-breaking. Add a new method:

```python
async def get_evolution_metadata(self, procedure_id: str) -> dict[str, str]:
    """Return content_diff and change_summary for a procedure."""
```

Queries the SQLite `procedure_records` table for these two columns.

---

## Part 2: Anti-Loop Guard

### File: `src/probos/cognitive/dreaming.py`

### 2a: Add `_addressed_degradations` dict to `DreamingEngine.__init__()`

```python
self._addressed_degradations: dict[str, float] = {}  # AD-532b: procedure_id -> timestamp
```

### 2b: Add config constant

### File: `src/probos/config.py`

```python
EVOLUTION_COOLDOWN_SECONDS = 259200  # 72 hours — don't re-evolve same procedure within this window
```

### 2c: Guard logic

Before attempting evolution on a degraded procedure, check:
```python
import time
now = time.time()
last_attempt = self._addressed_degradations.get(procedure_id, 0.0)
if now - last_attempt < EVOLUTION_COOLDOWN_SECONDS:
    continue  # skip — already addressed recently
```

After a successful evolution (or failed attempt), record:
```python
self._addressed_degradations[procedure_id] = time.time()
```

---

## Part 3: Dream Cycle Step 7b — Evolution Scan

### File: `src/probos/cognitive/dreaming.py`

Insert a new step **between** the existing Step 7 (CAPTURED extraction, ends at line ~238) and Step 8 (gap prediction, starts at line ~240). This step scans active procedures for degraded quality and triggers evolution.

### 3a: Step 7b Implementation

```python
# Step 7b: Procedure evolution from degraded metrics (AD-532b)
procedures_evolved = 0
if self._llm_client and self._procedure_store:
    try:
        procedures_evolved = await self._evolve_degraded_procedures(episodes)
    except Exception as e:
        logger.debug("Procedure evolution scan failed (non-critical): %s", e)
```

### 3b: `_evolve_degraded_procedures()` Method

Add a new private method on `DreamingEngine`:

```python
async def _evolve_degraded_procedures(self, episodes: list) -> int:
    """Scan active procedures for degraded metrics and evolve. Returns count of evolved."""
```

**Implementation:**
1. Call `self._procedure_store.list_active()` to get all active procedures
2. For each procedure:
   a. Call `self._procedure_store.get_quality_metrics(procedure_id)`
   b. Skip if `total_selections < PROCEDURE_MIN_SELECTIONS` (from config, default 5) — not enough data
   c. Apply the same three diagnosis rules as `_diagnose_procedure_health()` in `cognitive_agent.py`:
      - `fallback_rate > PROCEDURE_HEALTH_FALLBACK_RATE` → FIX
      - `applied_rate > PROCEDURE_HEALTH_APPLIED_RATE and completion_rate < PROCEDURE_HEALTH_COMPLETION_RATE` → FIX
      - `effective_rate < PROCEDURE_HEALTH_EFFECTIVE_RATE and applied_rate > PROCEDURE_HEALTH_DERIVED_APPLIED` → DERIVED
   d. If no diagnosis → skip
   e. Check anti-loop guard (`_addressed_degradations`) → skip if within cooldown
   f. Load the full `Procedure` via `self._procedure_store.get(procedure_id)`
   g. Find fresh episodes via `self.episodic_memory.recall_by_intent(intent_type)` for each of the procedure's `intent_types`. Combine and deduplicate by episode ID. Limit to 10 most recent.
   h. If no fresh episodes → skip (can't evolve without evidence)
   i. Call the appropriate evolution function:
      - FIX diagnosis → `await evolve_fix_procedure(parent, diagnosis, metrics, fresh_episodes, self._llm_client)`
      - DERIVED diagnosis → `await evolve_derived_procedure([parent], fresh_episodes, self._llm_client)`
   j. If evolution returns None → record in anti-loop guard, continue
   k. If evolution returns an `EvolutionResult`:
      - Save the new procedure: `await self._procedure_store.save(result.procedure, content_diff=result.content_diff, change_summary=result.change_summary)`
      - For FIX: deactivate the parent: `await self._procedure_store.deactivate(parent.id, superseded_by=result.procedure.id)`
      - For DERIVED: parents stay active (no deactivation)
      - Record in anti-loop guard
      - Increment `procedures_evolved`
      - Append to `procedures` list (the one used in DreamReport)
      - Log: `"Procedure evolved (%s): '%s' -> '%s'", evolution_type, parent.name, result.procedure.name`
3. Return `procedures_evolved`

**Import** `evolve_fix_procedure`, `evolve_derived_procedure`, `EvolutionResult` from `probos.cognitive.procedures` at the top of the file (alongside the existing `extract_procedure_from_cluster` import).

**Import** `EVOLUTION_COOLDOWN_SECONDS`, `PROCEDURE_MIN_SELECTIONS`, and all `PROCEDURE_HEALTH_*` constants from `probos.config`.

### 3c: Diagnosis Helper

To avoid duplicating the diagnosis rules from `cognitive_agent.py`, extract a standalone function that both files can use. Add to `procedures.py`:

```python
def diagnose_procedure_health(metrics: dict[str, Any], min_selections: int = 5) -> str | None:
    """Rule-based health diagnosis. Returns diagnosis string or None.

    Rules (first match wins, from OpenSpace):
    - fallback_rate > threshold -> "FIX:high_fallback_rate"
    - applied_rate > threshold AND completion_rate < threshold -> "FIX:low_completion"
    - effective_rate < threshold AND applied_rate > threshold -> "DERIVED:low_effective_rate"
    """
```

Use the config constants for thresholds. This function is pure — takes metrics dict, returns a string or None.

Then refactor `CognitiveAgent._diagnose_procedure_health()` to call this shared function instead of duplicating the logic. The CognitiveAgent method becomes a thin wrapper that calls the shared function and does the logging.

---

## Part 4: DreamReport Extension

### File: `src/probos/types.py`

Add a new field to `DreamReport`:

```python
procedures_evolved: int = 0  # AD-532b
```

Add **after** the existing `procedures` field. Use in the DreamReport construction in `dream_cycle()`.

### Update the DreamReport construction in `dreaming.py`

In the `DreamReport(...)` constructor call (around line 251), add:

```python
procedures_evolved=procedures_evolved,
```

### Update the log line

In the `logger.info("dream-cycle: ...")` call (around line 266), add `evolved=%d` and include `procedures_evolved` in the format args.

---

## Part 5: Tests

### File: `tests/test_procedure_evolution.py` (NEW)

Write comprehensive tests covering:

**5a: `_format_episode_blocks()` helper**
- Formats episodes with READ-ONLY framing
- Handles empty episodes list
- Handles episodes with None reflection

**5b: `evolve_fix_procedure()`**
- Returns `EvolutionResult` on successful repair
- Sets `evolution_type="FIX"`, `generation=parent.generation+1`, `parent_procedure_ids=[parent.id]`
- Preserves `intent_types`, `compilation_level`, `tags` from parent
- Generates non-empty `content_diff`
- Extracts `change_summary` from LLM response
- Returns None when LLM returns `{"error": ...}`
- Returns None on LLM exception (log-and-degrade)
- Returns None on malformed JSON

**5c: `evolve_derived_procedure()`**
- Returns `EvolutionResult` on successful specialization
- Sets `evolution_type="DERIVED"`, `generation=max(parents)+1`, `parent_procedure_ids` contains all parent IDs
- `compilation_level = max(parents) - 1`, minimum 1
- `intent_types` is union of all parents' intent types
- Handles single-parent DERIVED
- Handles multi-parent DERIVED (2 parents)
- Returns None when LLM returns `{"error": ...}`
- Returns None on exception

**5d: `diagnose_procedure_health()` shared function**
- Returns `"FIX:high_fallback_rate"` when `fallback_rate > 0.4`
- Returns `"FIX:low_completion"` when `applied_rate > 0.4 and completion_rate < 0.35`
- Returns `"DERIVED:low_effective_rate"` when `effective_rate < 0.55 and applied_rate > 0.25`
- Returns None when no rule matches
- Returns None when `total_selections < min_selections`
- First-match-wins priority (FIX fallback checked before FIX completion)

**5e: Anti-loop guard**
- Skips procedure within cooldown window
- Processes procedure after cooldown expires
- Records timestamp after evolution attempt (success or failure)

**5f: `_evolve_degraded_procedures()` integration**
- Calls `list_active()` and `get_quality_metrics()` for each
- Triggers FIX for high fallback rate
- Triggers DERIVED for low effective rate
- Deactivates parent on FIX, keeps parent active on DERIVED
- Saves evolved procedure with content_diff and change_summary
- Skips procedures with insufficient selections
- Handles empty procedure list gracefully
- Handles evolution function returning None
- Handles store/memory exceptions (log-and-degrade)

**5g: DreamReport**
- `procedures_evolved` field defaults to 0
- Field is populated after Step 7b

**5h: `ProcedureStore.save()` with evolution metadata**
- `content_diff` persisted to SQLite
- `change_summary` persisted to SQLite
- `get_evolution_metadata()` returns both fields
- `get_evolution_metadata()` returns empty strings for procedures without evolution data

**5i: Refactored `extract_procedure_from_cluster()`**
- Still works correctly after `_format_episode_blocks()` extraction (no regression)

**5j: CognitiveAgent._diagnose_procedure_health() refactor**
- Still produces same diagnoses after refactor to call shared function
- Existing AD-534 tests still pass

---

## Validation Checklist

After implementation, verify each item:

### Part 0 — Evolution functions
- [ ] `EvolutionResult` dataclass exists with `procedure`, `content_diff`, `change_summary`
- [ ] `_format_episode_blocks()` helper exists and is used by all three extraction functions
- [ ] `extract_procedure_from_cluster()` refactored to use helper (no behavior change)
- [ ] `_FIX_SYSTEM_PROMPT` includes parent procedure, diagnosis, metrics, and change_summary in schema
- [ ] `_DERIVED_SYSTEM_PROMPT` includes parent(s), specialization goal, and change_summary in schema
- [ ] `evolve_fix_procedure()` returns `EvolutionResult | None`
- [ ] FIX: `evolution_type="FIX"`, `generation=parent+1`, `parent_procedure_ids=[parent.id]`
- [ ] FIX: preserves `intent_types`, `compilation_level`, `tags` from parent
- [ ] `evolve_derived_procedure()` returns `EvolutionResult | None`
- [ ] DERIVED: `evolution_type="DERIVED"`, `generation=max(parents)+1`, multi-parent IDs
- [ ] DERIVED: `compilation_level = max(parents) - 1`, minimum 1
- [ ] DERIVED: `intent_types` is union of all parents
- [ ] `content_diff` generated via `difflib.unified_diff()`
- [ ] `change_summary` extracted from LLM response JSON
- [ ] Both functions log-and-degrade on any exception

### Part 1 — Store enhancement
- [ ] `save()` accepts optional `content_diff` and `change_summary` kwargs
- [ ] `content_diff` and `change_summary` written to SQLite `procedure_records`
- [ ] `get_evolution_metadata()` method returns both fields
- [ ] Existing `save()` calls (AD-533 Step 7) still work without kwargs

### Part 2 — Anti-loop guard
- [ ] `_addressed_degradations` dict on DreamingEngine
- [ ] `EVOLUTION_COOLDOWN_SECONDS` in config.py (259200 = 72 hours)
- [ ] Guard checks before evolution attempt
- [ ] Guard records after evolution attempt (success or failure)
- [ ] Guard cooldown window works correctly

### Part 3 — Dream cycle Step 7b
- [ ] Step 7b inserted between Step 7 and Step 8
- [ ] `_evolve_degraded_procedures()` returns count of evolved
- [ ] Scans all active procedures via `list_active()`
- [ ] Applies diagnosis rules (shared function from `procedures.py`)
- [ ] Skips procedures with < `PROCEDURE_MIN_SELECTIONS` selections
- [ ] Finds fresh episodes via `recall_by_intent()` for each intent type
- [ ] Calls `evolve_fix_procedure()` for FIX diagnoses
- [ ] Calls `evolve_derived_procedure()` for DERIVED diagnoses
- [ ] FIX: saves new + deactivates parent via `deactivate()`
- [ ] DERIVED: saves new, parents stay active
- [ ] Passes `content_diff` and `change_summary` to `save()`
- [ ] `diagnose_procedure_health()` shared function in `procedures.py`
- [ ] `CognitiveAgent._diagnose_procedure_health()` refactored to use shared function
- [ ] Step 7b failure is non-critical (log-and-degrade)

### Part 4 — DreamReport
- [ ] `procedures_evolved: int = 0` field added to DreamReport
- [ ] Field populated in DreamReport construction
- [ ] Included in dream-cycle log line

### Cross-cutting
- [ ] No import cycles
- [ ] All existing tests pass (AD-532: 29, AD-533: 49, AD-534: 35)
- [ ] New tests pass
- [ ] `_FENCE_RE` regex reused (not duplicated)
- [ ] All config constants imported from `probos.config`
- [ ] Imports at top of each modified file (no inline imports except log-and-degrade fallbacks)
