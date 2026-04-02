# AD-534: Replay-First Dispatch (Zero-Token Procedure Replay)

**Context:** AD-531 clusters episodes, AD-532 extracts procedures from success clusters, AD-533 persists them in a hybrid store (Ship's Records + SQLite index + ChromaDB). But nothing *uses* the stored procedures yet. Every agent task still invokes the LLM regardless of whether the agent has solved it before. AD-534 closes the loop: `decide()` checks procedural memory BEFORE the LLM call. If a matching procedure exists with sufficient quality metrics, replay deterministically at zero tokens.

**Problem:** `CognitiveAgent.decide()` always calls the LLM. Episodes cluster → procedures extract → procedures store → but then what? The crew re-invokes the LLM for every repeat task. This is the "payoff" AD — the one that actually saves tokens. The minimum viable slice (AD-531 → AD-532 → AD-533 → **AD-534**) delivers: "the agent remembers how it solved this before and just does it."

**Scope (slim):** This AD covers only:
- **Procedural memory check** — semantic match against ProcedureStore before LLM call.
- **Replay execution** — format procedure steps as the response. Zero tokens.
- **Quality metric recording** — track selection/applied/completion/fallback per procedure.
- **Negative procedure check** — skip known anti-patterns before replaying.
- **Health diagnosis (log-only)** — compute metric-based diagnosis, log it. No evolution actions.
- **Journal integration** — record replays with `cached=True` and `procedure_id`.

**Deferred (tracked as separate ADs):**
- AD-534b: Fallback learning (compare failed replay with successful LLM response, annotate procedure)
- AD-535: Graduated compilation levels (step-by-step postcondition validation, Dreyfus level promotion, Level 2 guided mode with LLM-as-scaffold)
- AD-532b: FIX/DERIVED evolution actions from health diagnosis results
- AD-536: Trust-gated promotion and governance

**Principles:** SOLID (new private methods on CognitiveAgent, single responsibility), Law of Demeter (access store via runtime property, not deep chain), Fail Fast (log-and-degrade — replay failure falls through to LLM, never blocks cognition), DRY (reuse existing ProcedureStore.find_matching() and journal.record() APIs).

---

## Part 0: Infrastructure Wiring

### File: `src/probos/runtime.py`

**Add a public property for procedure_store.** Follow the pattern of existing service properties (e.g., `cognitive_journal`).

Find where other service properties are exposed (search for `@property` near `cognitive_journal` or similar). Add:

```python
@property
def procedure_store(self):
    """AD-534: Procedure store for replay-first dispatch."""
    return self._procedure_store
```

This exposes `self._procedure_store` (already initialized at line ~1094) as a public API. Agents access it via `self._runtime.procedure_store`.

### File: `src/probos/config.py`

**Add Cognitive JIT dispatch constants** (after the Trust constants block, around line 28):

```python
# ─── Cognitive JIT (AD-534) ───────────────────────────────────────
# Replay-first dispatch thresholds for procedural memory.

PROCEDURE_MATCH_THRESHOLD = 0.6     # Minimum semantic similarity for replay
PROCEDURE_MIN_COMPILATION_LEVEL = 1  # Minimum Dreyfus level for replay (AD-535 raises this)
PROCEDURE_MIN_SELECTIONS = 5        # Minimum selections before health diagnosis
PROCEDURE_HEALTH_FALLBACK_RATE = 0.4    # FIX diagnosis threshold
PROCEDURE_HEALTH_COMPLETION_RATE = 0.35  # FIX diagnosis (with applied > 0.4)
PROCEDURE_HEALTH_APPLIED_RATE = 0.4      # FIX diagnosis trigger
PROCEDURE_HEALTH_EFFECTIVE_RATE = 0.55   # DERIVED diagnosis threshold
PROCEDURE_HEALTH_DERIVED_APPLIED = 0.25  # DERIVED minimum applied_rate
```

### File: `src/probos/cognitive/journal.py`

**Add `procedure_id` column via schema migration.** In the `start()` method (currently line ~70), find the migration block (lines 76-84) that adds `intent_id`, `dag_node_id`, `response_hash`. Add `procedure_id` to that migration list:

```python
for col, typedef in [
    ("intent_id", "TEXT NOT NULL DEFAULT ''"),
    ("dag_node_id", "TEXT NOT NULL DEFAULT ''"),
    ("response_hash", "TEXT NOT NULL DEFAULT ''"),
    ("procedure_id", "TEXT NOT NULL DEFAULT ''"),  # AD-534: procedure replay tracking
]:
```

**Add `procedure_id` to the `record()` method signature** (currently line ~143). Add after `response_hash`:

```python
procedure_id: str = "",  # AD-534: procedure ID if this was a replay
```

**Add `procedure_id` to the INSERT statement** — add to both the column list and the VALUES placeholder. Follow the same pattern as the existing columns.

### Tests (~5 tests)

- `test_runtime_exposes_procedure_store_property` — verify `runtime.procedure_store` returns the store
- `test_runtime_procedure_store_none_when_not_initialized` — verify returns None before startup
- `test_journal_schema_has_procedure_id_column` — verify column exists after start()
- `test_journal_record_accepts_procedure_id` — verify record() accepts and stores procedure_id
- `test_config_procedure_constants_exist` — verify all constants importable

---

## Part 1: Procedural Memory Check

### File: `src/probos/cognitive/cognitive_agent.py`

**Add a property to access the procedure store** (after `_cognitive_journal` property, currently line ~78):

```python
@property
def _procedure_store(self):
    """AD-534: Access procedure store via runtime (Ship's Computer service)."""
    if self._runtime and hasattr(self._runtime, 'procedure_store'):
        return self._runtime.procedure_store
    return None
```

**Add the procedural memory check method.** This is a new private async method on CognitiveAgent. Place it after the `_cognitive_journal` and `_procedure_store` properties, before `perceive()`:

```python
async def _check_procedural_memory(self, observation: dict) -> dict | None:
    """AD-534: Check for a matching procedure before calling the LLM.

    Returns a decision dict if a procedure was replayed successfully,
    or None to fall through to the LLM path.
    """
    store = self._procedure_store
    if not store:
        return None

    # Extract query text from observation
    params = observation.get("params", {})
    query = ""
    if isinstance(params, dict):
        query = params.get("message", "") or params.get("query", "")
    if not query:
        query = observation.get("intent", "")
    if not query:
        return None

    from probos.config import (
        PROCEDURE_MATCH_THRESHOLD,
        PROCEDURE_MIN_COMPILATION_LEVEL,
    )

    # 1. Negative procedure check — warn even before positive match
    try:
        neg_matches = await store.find_matching(
            query, n_results=3, exclude_negative=False,
        )
        for nm in neg_matches:
            if nm.get("is_negative") and nm.get("score", 0) >= PROCEDURE_MATCH_THRESHOLD:
                logger.warning(
                    "AD-534: Negative procedure match for '%s': %s (score=%.3f). "
                    "Avoiding known anti-pattern.",
                    query[:50], nm.get("name"), nm.get("score"),
                )
                # Don't return — fall through to LLM with warning logged.
                # The LLM path will handle the task correctly.
                return None
    except Exception:
        logger.debug("Negative procedure check failed (non-critical)", exc_info=True)

    # 2. Find matching positive procedures
    try:
        matches = await store.find_matching(
            query,
            n_results=3,
            min_compilation_level=PROCEDURE_MIN_COMPILATION_LEVEL,
            exclude_negative=True,
        )
    except Exception:
        logger.debug("Procedure store query failed (non-critical)", exc_info=True)
        return None

    if not matches:
        return None

    best = matches[0]

    # 3. Score threshold gate
    if best.get("score", 0) < PROCEDURE_MATCH_THRESHOLD:
        return None

    # 4. Quality metric gate — don't replay procedures with poor track record
    try:
        metrics = await store.get_quality_metrics(best["id"])
    except Exception:
        metrics = {}

    if metrics.get("total_selections", 0) >= 5:
        eff_rate = metrics.get("effective_rate", 1.0)
        if eff_rate < 0.3:
            logger.info(
                "AD-534: Skipping procedure '%s' — poor effective_rate (%.2f)",
                best.get("name"), eff_rate,
            )
            self._diagnose_procedure_health(best["id"], best.get("name", ""), metrics)
            return None

    # 5. Record selection
    try:
        await store.record_selection(best["id"])
    except Exception:
        logger.debug("record_selection failed", exc_info=True)

    # 6. Load full procedure
    try:
        procedure = await store.get(best["id"])
    except Exception:
        logger.debug("Procedure load failed", exc_info=True)
        return None

    if not procedure:
        return None

    # 7. Record applied (replay attempt begins)
    try:
        await store.record_applied(best["id"])
    except Exception:
        logger.debug("record_applied failed", exc_info=True)

    # 8. Execute replay
    try:
        replay_output = self._format_procedure_replay(procedure, best.get("score", 0))

        # Record completion
        try:
            await store.record_completion(best["id"])
        except Exception:
            logger.debug("record_completion failed", exc_info=True)

        # Health diagnosis (log-only, feeds future AD-532b)
        try:
            updated_metrics = await store.get_quality_metrics(best["id"])
            self._diagnose_procedure_health(best["id"], procedure.name, updated_metrics)
        except Exception:
            logger.debug("Health diagnosis failed (non-critical)", exc_info=True)

        logger.info(
            "AD-534: Procedure replay for '%s' — '%s' (score=%.3f, 0 tokens)",
            observation.get("intent", ""), procedure.name, best.get("score", 0),
        )

        return {
            "action": "execute",
            "llm_output": replay_output,
            "cached": True,
            "procedure_id": procedure.id,
            "procedure_name": procedure.name,
        }

    except Exception:
        # Replay failed — record fallback, fall through to LLM
        logger.info(
            "AD-534: Procedure replay failed for '%s' — falling back to LLM",
            procedure.name,
        )
        try:
            await store.record_fallback(best["id"])
        except Exception:
            logger.debug("record_fallback failed", exc_info=True)
        return None
```

### Tests (~10 tests)

- `test_check_procedural_memory_returns_none_without_store` — no runtime/store → None
- `test_check_procedural_memory_returns_none_empty_query` — empty observation → None
- `test_check_procedural_memory_returns_none_no_matches` — store returns empty → None
- `test_check_procedural_memory_returns_none_below_threshold` — score too low → None
- `test_check_procedural_memory_returns_none_poor_effective_rate` — quality gate blocks replay
- `test_check_procedural_memory_returns_decision_on_match` — good match → decision dict
- `test_check_procedural_memory_decision_has_cached_true` — verify `cached=True` in result
- `test_check_procedural_memory_decision_has_procedure_id` — verify `procedure_id` present
- `test_check_procedural_memory_records_selection_and_applied` — verify metric calls
- `test_check_procedural_memory_records_fallback_on_error` — replay error → fallback recorded

---

## Part 2: Replay Formatting & Health Diagnosis

### File: `src/probos/cognitive/cognitive_agent.py`

**Add the replay formatter.** This method formats a procedure into a text response that `act()` can consume. Place it after `_check_procedural_memory()`:

```python
def _format_procedure_replay(self, procedure: Any, match_score: float = 0.0) -> str:
    """AD-534: Format a procedure for deterministic replay output.

    The procedure's steps become the structured response,
    replacing the LLM call entirely.
    """
    lines = [
        f"[Procedure Replay: {procedure.name}]",
        f"Match score: {match_score:.3f} | Steps: {len(procedure.steps)}",
        "",
    ]
    if procedure.description:
        lines.append(procedure.description)
        lines.append("")

    for step in procedure.steps:
        lines.append(f"**Step {step.step_number}:** {step.action}")
        if step.expected_output:
            lines.append(f"  → Expected: {step.expected_output}")
        if step.fallback_action:
            lines.append(f"  ⚠ Fallback: {step.fallback_action}")

    if procedure.postconditions:
        lines.append("")
        lines.append("**Postconditions:**")
        for pc in procedure.postconditions:
            lines.append(f"  - {pc}")

    return "\n".join(lines)
```

**Add the health diagnosis method.** This computes the OpenSpace metric-based health diagnosis (rule-based, first match wins). Results are logged only — AD-532b will add evolution actions.

```python
def _diagnose_procedure_health(
    self, procedure_id: str, procedure_name: str, metrics: dict
) -> None:
    """AD-534: Metric-based health diagnosis (OpenSpace absorbed pattern).

    Rule-based, first match wins. Logs diagnosis for future
    AD-532b FIX/DERIVED evolution. No action taken here.
    """
    from probos.config import (
        PROCEDURE_MIN_SELECTIONS,
        PROCEDURE_HEALTH_FALLBACK_RATE,
        PROCEDURE_HEALTH_COMPLETION_RATE,
        PROCEDURE_HEALTH_APPLIED_RATE,
        PROCEDURE_HEALTH_EFFECTIVE_RATE,
        PROCEDURE_HEALTH_DERIVED_APPLIED,
    )

    selections = metrics.get("total_selections", 0)
    if selections < PROCEDURE_MIN_SELECTIONS:
        return  # Not enough data for diagnosis

    fallback_rate = metrics.get("fallback_rate", 0.0)
    applied_rate = metrics.get("applied_rate", 0.0)
    completion_rate = metrics.get("completion_rate", 0.0)
    effective_rate = metrics.get("effective_rate", 0.0)

    diagnosis = None

    if fallback_rate > PROCEDURE_HEALTH_FALLBACK_RATE:
        diagnosis = "FIX:high_fallback_rate"
    elif applied_rate > PROCEDURE_HEALTH_APPLIED_RATE and completion_rate < PROCEDURE_HEALTH_COMPLETION_RATE:
        diagnosis = "FIX:low_completion_despite_application"
    elif effective_rate < PROCEDURE_HEALTH_EFFECTIVE_RATE and applied_rate > PROCEDURE_HEALTH_DERIVED_APPLIED:
        diagnosis = "DERIVED:low_effective_rate"

    if diagnosis:
        logger.warning(
            "AD-534: Procedure health diagnosis for '%s' (%s): %s "
            "(selections=%d, fallback=%.2f, applied=%.2f, completion=%.2f, effective=%.2f)",
            procedure_name, procedure_id[:8], diagnosis,
            selections, fallback_rate, applied_rate, completion_rate, effective_rate,
        )
```

### Tests (~8 tests)

- `test_format_procedure_replay_includes_name` — procedure name in output
- `test_format_procedure_replay_includes_steps` — steps formatted with numbers
- `test_format_procedure_replay_includes_postconditions` — postconditions present
- `test_format_procedure_replay_empty_steps` — handles procedure with no steps
- `test_diagnose_health_skips_below_min_selections` — < 5 selections → no diagnosis
- `test_diagnose_health_fix_high_fallback` — fallback > 0.4 → FIX diagnosis logged
- `test_diagnose_health_fix_low_completion` — applied > 0.4 + completion < 0.35 → FIX
- `test_diagnose_health_derived_low_effective` — effective < 0.55 + applied > 0.25 → DERIVED

---

## Part 3: Integration into `decide()`

### File: `src/probos/cognitive/cognitive_agent.py`

**Insert the procedural memory check into `decide()`.** The check goes AFTER the decision cache miss counter (line ~201) and BEFORE the LLM call preparation (line ~203). The dispatch order is:
1. Decision cache (AD-272) — exact hash match, in-memory, fastest
2. **Procedural memory (AD-534)** — semantic match, persistent, NEW
3. LLM call — full prompt build + API call, most expensive

Find the line that reads:
```python
_CACHE_MISSES[self.agent_type] = _CACHE_MISSES.get(self.agent_type, 0) + 1
```

**Insert immediately after that line** (before `user_message = self._build_user_message(observation)`):

```python
        # --- AD-534: Procedural memory check (semantic match) ---
        procedural_result = await self._check_procedural_memory(observation)
        if procedural_result is not None:
            # Record in journal (fire-and-forget)
            if self._cognitive_journal:
                try:
                    import uuid as _uuid
                    await self._cognitive_journal.record(
                        entry_id=_uuid.uuid4().hex,
                        timestamp=time.time(),
                        agent_id=self.id,
                        agent_type=self.agent_type,
                        intent=observation.get("intent", ""),
                        intent_id=observation.get("intent_id", ""),
                        cached=True,
                        total_tokens=0,
                        procedure_id=procedural_result.get("procedure_id", ""),
                    )
                except Exception:
                    logger.debug("Journal recording failed", exc_info=True)
            return procedural_result
```

**Do NOT move or modify any existing code.** The decision cache check stays before this. The LLM call stays after this. Only insert the new block.

### Tests (~8 tests)

- `test_decide_checks_procedural_memory_after_cache_miss` — verify call order: cache → procedure → LLM
- `test_decide_returns_procedural_result_when_matched` — good match → returns without LLM call
- `test_decide_skips_llm_on_procedural_hit` — verify `llm_client.complete` NOT called on hit
- `test_decide_falls_through_to_llm_on_no_match` — no match → LLM called normally
- `test_decide_procedural_replay_journal_entry` — verify journal record with `cached=True`, `procedure_id`
- `test_decide_procedural_replay_zero_tokens` — verify `total_tokens=0` in journal entry
- `test_decide_decision_cache_takes_priority` — cache hit → procedural memory NOT checked
- `test_decide_procedural_failure_falls_through_to_llm` — procedure_store error → LLM path

---

## Part 4: Negative Procedure Integration

The negative procedure check is already embedded in `_check_procedural_memory()` (Part 1). This part adds targeted tests to verify the anti-pattern detection flow.

### Tests (~4 tests)

- `test_negative_procedure_blocks_replay` — negative match above threshold → returns None (falls to LLM)
- `test_negative_procedure_logs_warning` — verify warning log includes procedure name and score
- `test_negative_procedure_check_failure_noncritical` — store error on negative check → continues to positive search
- `test_positive_match_not_blocked_by_low_score_negative` — negative match below threshold → positive replay proceeds

---

## Validation Checklist

After building, verify:

1. **Part 0 — Infrastructure:**
   - [ ] `runtime.procedure_store` property exists and returns the store
   - [ ] `runtime.procedure_store` returns None before startup
   - [ ] Journal `procedure_id` column created via migration (idempotent)
   - [ ] `journal.record()` accepts `procedure_id` kwarg
   - [ ] `procedure_id` persisted in journal table
   - [ ] All config constants importable from `probos.config`

2. **Part 1 — Procedural memory check:**
   - [ ] `_procedure_store` property accesses store via runtime
   - [ ] `_check_procedural_memory()` is async, returns `dict | None`
   - [ ] Returns None when: no store, no query, no matches, below threshold, poor quality
   - [ ] Returns decision dict when: good match above threshold with acceptable quality
   - [ ] Decision dict has: `action`, `llm_output`, `cached=True`, `procedure_id`, `procedure_name`
   - [ ] Calls `record_selection()` before loading procedure
   - [ ] Calls `record_applied()` before replay
   - [ ] Calls `record_completion()` after successful replay
   - [ ] Calls `record_fallback()` after failed replay
   - [ ] All store/metric errors are caught (log-and-degrade, never raises)

3. **Part 2 — Replay formatting & health diagnosis:**
   - [ ] `_format_procedure_replay()` returns formatted string with name, steps, postconditions
   - [ ] Format includes step numbers, actions, expected outputs, fallback actions
   - [ ] `_diagnose_procedure_health()` implements three rules (FIX high fallback, FIX low completion, DERIVED low effective)
   - [ ] Diagnosis skips procedures with < `PROCEDURE_MIN_SELECTIONS` selections
   - [ ] Diagnosis logs warning (only) — no evolution actions taken

4. **Part 3 — decide() integration:**
   - [ ] Procedural check inserted AFTER decision cache miss, BEFORE LLM call
   - [ ] Decision cache still checked first (no regression)
   - [ ] Procedural hit returns immediately (LLM never called)
   - [ ] Procedural miss falls through to LLM normally
   - [ ] Journal records procedural replay with `cached=True`, `total_tokens=0`, `procedure_id`
   - [ ] Existing LLM cache and strategy logic unchanged

5. **Part 4 — Negative procedures:**
   - [ ] Negative match above threshold → returns None (falls to LLM)
   - [ ] Negative match failure is non-critical
   - [ ] Warning logged with procedure name and score

6. **Cross-cutting:**
   - [ ] No import cycles
   - [ ] All existing tests still pass (especially AD-272 decision cache tests)
   - [ ] BuilderAgent.decide() inherits procedural check via super().decide()
   - [ ] No new dependencies introduced (uses only existing ProcedureStore, Journal, config)
   - [ ] Pre-commit hook passes (no commercial content)
   - [ ] ~35 new tests total
