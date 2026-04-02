# AD-532c: Negative Procedure Extraction (Anti-Patterns)

**Context:** AD-532 (CLOSED) extracts positive CAPTURED procedures from success-dominant clusters. AD-532b (CLOSED) evolves degraded procedures via FIX/DERIVED. AD-533's `ProcedureStore` already fully supports negative procedures: `is_negative` field, `records/procedures/anti-patterns/` Ship's Records path, ChromaDB metadata, SQLite index, and `exclude_negative` query filter. AD-534's `_check_procedural_memory()` already checks for negative procedure matches, logs a warning, and forces the LLM path. AD-403's `detect_contradictions()` identifies episode pairs with high similarity but disagreeing outcomes.

**Everything is wired except the producer.** No code currently creates negative procedures. Failure-dominant clusters (`is_failure_dominant=True`, failure rate >50%) are explicitly skipped in the dream cycle extraction loop. Contradictions are detected, counted, and logged but never feed into procedure extraction.

**Problem:** Agents repeat known mistakes because anti-patterns are not codified. A failure-dominant cluster indicates a systematic bad approach — the same wrong pattern appears in multiple failed episodes. Contradictions indicate a pattern that used to work but now fails. Without negative procedures, the only defense is the agent's LLM reasoning each time, which may rediscover the same bad approach.

**Scope:** This AD covers:
- **Negative extraction prompt** — LLM prompt for anti-pattern extraction ("when you see X, do NOT do Y because Z happened").
- **`extract_negative_procedure_from_cluster()`** — Extraction function for failure-dominant clusters, produces `Procedure(is_negative=True)`.
- **Dream cycle Step 7c** — Iterates failure-dominant clusters, enriched with contradiction context from AD-403.
- **DreamReport extension** — `negative_procedures_extracted` counter.

**Deferred:**
- AD-532e: Reactive/proactive triggers for negative extraction
- AD-538: Lifecycle management for negative procedures (decay, archival)

**Dependencies (all COMPLETE):**
- AD-532 ✅ — `extract_procedure_from_cluster()`, `_format_episode_blocks()`, `_parse_procedure_json()`, `_build_steps_from_data()` helpers
- AD-533 ✅ — `ProcedureStore` with full `is_negative` support (save, index, filter, query, anti-patterns directory)
- AD-534 ✅ — Negative procedure check in `_check_procedural_memory()` (the consumer)
- AD-403 ✅ — `detect_contradictions()` → `list[Contradiction]`, `Contradiction` dataclass in `contradiction_detector.py`

**Principles:** SOLID (extraction function = single responsibility), DRY (reuse `_format_episode_blocks()`, `_parse_procedure_json()`, `_build_steps_from_data()` from AD-532/532b), Fail Fast (log-and-degrade — negative extraction failures don't break dream cycles), AD-541b READ-ONLY framing for all episode content.

---

## Part 0: Negative Extraction Prompt and Function

### File: `src/probos/cognitive/procedures.py`

### 0a: `_NEGATIVE_SYSTEM_PROMPT`

Add a new constant after `_DERIVED_SYSTEM_PROMPT`. This prompt instructs the LLM to extract an anti-pattern — what NOT to do:

```python
_NEGATIVE_SYSTEM_PROMPT = """\
You are an anti-pattern extraction engine. You analyze FAILED execution episodes
and extract the common mistake — the specific steps that were taken that led to
failure. This becomes a "negative procedure" — a warning of what NOT to do.

Output ONLY valid JSON matching this schema:
{
  "name": "short label describing the anti-pattern",
  "description": "what goes wrong when this pattern is followed",
  "steps": [
    {
      "step_number": 1,
      "action": "the BAD action that was taken",
      "expected_input": "state before this step",
      "expected_output": "what the agent EXPECTED (but did not get)",
      "fallback_action": "what SHOULD be done instead",
      "invariants": ["what was violated"]
    }
  ],
  "preconditions": ["conditions under which this anti-pattern is dangerous"],
  "postconditions": ["the negative outcomes that result from following this pattern"]
}

Rules:
- Reference episode IDs, do not reconstruct narratives
- Extract the COMMON failure pattern across episodes, not any single episode's exact steps
- The "fallback_action" for each step should describe the CORRECT approach to take instead
- Preconditions should describe WHEN this anti-pattern is tempting but dangerous
- Postconditions should describe the BAD outcomes (errors, failures, user dissatisfaction)
- If no common anti-pattern can be extracted, return {"error": "no_common_antipattern"}
"""
```

### 0b: `extract_negative_procedure_from_cluster()`

Add this function after the existing `evolve_derived_procedure()` function:

```python
async def extract_negative_procedure_from_cluster(
    cluster: Any,  # EpisodeCluster (failure-dominant)
    episodes: list[Any],  # Episode objects in this cluster
    llm_client: Any,  # BaseLLMClient
    contradictions: list[Any] | None = None,  # Contradiction objects (AD-403)
) -> Procedure | None:
    """Extract a negative procedure (anti-pattern) from a failure-dominant cluster.

    Uses AD-541b READ-ONLY episode framing. Optionally enriched with
    contradiction context from AD-403.

    Returns None if extraction fails (log-and-degrade).
    """
```

**Implementation:**
1. Build user prompt with:
   - Episode blocks using `_format_episode_blocks(episodes)` (DRY — reuse existing helper)
   - Cluster metadata: `cluster.cluster_id`, `cluster.success_rate`, `cluster.intent_types`
   - Instruction: "Extract the common anti-pattern from these {len(episodes)} failed episodes (cluster {cluster_id}, {1-success_rate:.0%} failure rate, intent types: {intent_types})."
2. **If contradictions are provided**, append a contradiction context section:
   ```
   === CONTRADICTION CONTEXT (AD-403) ===
   The following contradictions were detected — episodes with similar inputs
   but opposite outcomes. The failure outcomes may explain WHY this pattern is bad:

   Contradiction 1: Episode {older_id} ({older_outcome}) vs Episode {newer_id} ({newer_outcome})
     Intent: {intent}, Agent: {agent_id}, Similarity: {similarity:.2f}
     {description}
   === END CONTRADICTION CONTEXT ===
   ```
   Only include contradictions whose `intent` matches one of the cluster's `intent_types`. Limit to 5 most relevant (highest similarity).
3. Call `llm_client.complete()` with `_NEGATIVE_SYSTEM_PROMPT`, `tier="standard"`, `temperature=0.0`, `max_tokens=2048`.
4. Parse response using `_parse_procedure_json()` (DRY — reuse existing helper).
5. Check for `{"error": ...}` — return None.
6. Build steps using `_build_steps_from_data()` (DRY — reuse existing helper).
7. Build `Procedure` with:
   - `is_negative=True`
   - `evolution_type="CAPTURED"` (this is an initial extraction, not FIX/DERIVED)
   - `compilation_level=1`
   - `intent_types=cluster.intent_types`
   - `origin_cluster_id=cluster.cluster_id`
   - `origin_agent_ids=cluster.participating_agents`
   - `provenance=cluster.episode_ids`
   - `extraction_date=time.time()`
8. Return the `Procedure`.
9. Wrap entire function body in `try/except Exception` — log-and-degrade, return None.

---

## Part 1: Dream Cycle Step 7c — Negative Extraction

### File: `src/probos/cognitive/dreaming.py`

### 1a: Step 7c Implementation

Insert a new step **after** Step 7b (evolution scan) and **before** Step 8 (gap prediction). This step iterates failure-dominant clusters and calls the negative extraction function.

```python
# Step 7c: Negative procedure extraction from failure clusters (AD-532c)
negative_procedures_extracted = 0
if self._llm_client and clusters:
    for cluster in clusters:
        # Only extract from failure-dominant clusters
        if not cluster.is_failure_dominant:
            continue
        # Skip clusters we've already processed (same dedup set as positive)
        if cluster.cluster_id in self._extracted_cluster_ids:
            continue
        # Skip clusters already persisted (cross-session, AD-533)
        if self._procedure_store:
            try:
                if await self._procedure_store.has_cluster(cluster.cluster_id):
                    self._extracted_cluster_ids.add(cluster.cluster_id)
                    continue
            except Exception:
                pass
        try:
            # Get the actual Episode objects for this cluster
            matched_episodes = [
                ep for ep in episodes
                if ep.id in cluster.episode_ids
            ]
            if not matched_episodes:
                continue
            # Find relevant contradictions (AD-403) for this cluster's intent types
            relevant_contradictions = [
                c for c in contradictions
                if c.intent in cluster.intent_types
            ] if contradictions else []
            procedure = await extract_negative_procedure_from_cluster(
                cluster=cluster,
                episodes=matched_episodes,
                llm_client=self._llm_client,
                contradictions=relevant_contradictions or None,
            )
            if procedure:
                procedures.append(procedure)
                negative_procedures_extracted += 1
                self._extracted_cluster_ids.add(cluster.cluster_id)
                # AD-533: Persist to store
                if self._procedure_store:
                    try:
                        await self._procedure_store.save(procedure)
                    except Exception as e:
                        logger.debug(
                            "Negative procedure persistence failed (non-critical): %s", e
                        )
                logger.info(
                    "Negative procedure extracted from cluster %s: '%s' (%d steps)",
                    cluster.cluster_id[:8],
                    procedure.name,
                    len(procedure.steps),
                )
        except Exception as e:
            logger.debug(
                "Negative extraction failed for cluster %s (non-critical): %s",
                cluster.cluster_id[:8], e,
            )
```

### 1b: Pass `contradictions` into scope

The `contradictions` variable is computed at Step 3.5 (line ~147). It is currently a local variable in `dream_cycle()`. Ensure it is accessible to Step 7c's code block. It should already be in scope since all steps are in the same method body — verify this during implementation. If for any reason it is not in scope, move the declaration earlier or assign a default `contradictions = []` before Step 3.5.

### 1c: Import

Add `extract_negative_procedure_from_cluster` to the import from `probos.cognitive.procedures` at the top of `dreaming.py` (alongside the existing `extract_procedure_from_cluster`, `evolve_fix_procedure`, `evolve_derived_procedure` imports).

---

## Part 2: DreamReport Extension

### File: `src/probos/types.py`

Add a new field to `DreamReport`:

```python
negative_procedures_extracted: int = 0  # AD-532c
```

Add **after** the existing `procedures_evolved` field.

### File: `src/probos/cognitive/dreaming.py`

In the `DreamReport(...)` constructor call, add:

```python
negative_procedures_extracted=negative_procedures_extracted,
```

Update the `logger.info("dream-cycle: ...")` log line to include `negatives=%d` and the `negative_procedures_extracted` value.

---

## Part 3: Tests

### File: `tests/test_negative_extraction.py` (NEW)

Write comprehensive tests covering:

**3a: `extract_negative_procedure_from_cluster()`**
- Returns `Procedure` with `is_negative=True` on successful extraction
- Sets `evolution_type="CAPTURED"`, `compilation_level=1`
- Sets `intent_types`, `origin_cluster_id`, `origin_agent_ids`, `provenance` from cluster
- Reuses `_format_episode_blocks()` for episode formatting (verify READ-ONLY framing in LLM call)
- Returns None when LLM returns `{"error": "no_common_antipattern"}`
- Returns None on LLM exception (log-and-degrade)
- Returns None on malformed JSON
- Handles empty episodes list gracefully

**3b: Contradiction enrichment**
- Contradiction context included in LLM prompt when contradictions provided
- Only contradictions matching cluster intent types are included
- Contradictions limited to 5 most relevant (highest similarity)
- Works correctly when contradictions is None (no contradiction section in prompt)
- Works correctly when contradictions is empty list

**3c: Dream cycle Step 7c integration**
- Processes failure-dominant clusters (is_failure_dominant=True)
- Skips success-dominant clusters
- Skips already-processed clusters (in-memory dedup)
- Skips clusters already in store (cross-session dedup via has_cluster())
- Calls extract_negative_procedure_from_cluster with correct args
- Passes relevant contradictions (filtered by intent type) to extraction function
- Saves extracted negative procedures to store via store.save()
- Increments negative_procedures_extracted counter
- Store save failure is non-critical (log-and-degrade)
- Extraction failure is non-critical (log-and-degrade)
- Empty cluster list handled gracefully

**3d: DreamReport**
- `negative_procedures_extracted` field defaults to 0
- Field is populated after Step 7c

**3e: End-to-end pipeline verification**
- Negative procedure extracted during dream cycle → saved to ProcedureStore with is_negative=True → consumed by _check_procedural_memory() negative check (verify the full pipeline conceptually — mock-based, not integration test)

---

## Validation Checklist

After implementation, verify each item:

### Part 0 — Extraction function
- [ ] `_NEGATIVE_SYSTEM_PROMPT` exists with anti-pattern extraction instructions
- [ ] Schema in prompt includes steps with BAD actions and fallback_action as CORRECT approach
- [ ] `extract_negative_procedure_from_cluster()` is async, returns `Procedure | None`
- [ ] Sets `is_negative=True` on returned Procedure
- [ ] Sets `evolution_type="CAPTURED"`, `compilation_level=1`
- [ ] Sets `intent_types`, `origin_cluster_id`, `origin_agent_ids`, `provenance` from cluster
- [ ] Uses `_format_episode_blocks()` (DRY — not a duplicate implementation)
- [ ] Uses `_parse_procedure_json()` (DRY)
- [ ] Uses `_build_steps_from_data()` (DRY)
- [ ] Contradiction context section included when contradictions are provided
- [ ] Contradiction filtering: only those matching cluster intent types
- [ ] Contradiction limit: max 5, sorted by similarity descending
- [ ] Log-and-degrade on any exception (returns None, logs debug)

### Part 1 — Dream cycle Step 7c
- [ ] Step 7c inserted after Step 7b and before Step 8
- [ ] Iterates `is_failure_dominant` clusters only
- [ ] Skips already-processed clusters (same `_extracted_cluster_ids` set)
- [ ] Skips clusters already in store (cross-session dedup via `has_cluster()`)
- [ ] Passes relevant contradictions filtered by intent type
- [ ] Calls `extract_negative_procedure_from_cluster()` with correct args
- [ ] Saves to ProcedureStore on success
- [ ] Updates `_extracted_cluster_ids` on success
- [ ] Increments `negative_procedures_extracted` counter
- [ ] Each failure is non-critical (log-and-degrade, continues loop)
- [ ] Import added for `extract_negative_procedure_from_cluster`

### Part 2 — DreamReport
- [ ] `negative_procedures_extracted: int = 0` field added
- [ ] Field populated in DreamReport construction
- [ ] Included in dream-cycle log line

### Cross-cutting
- [ ] No import cycles
- [ ] All existing tests pass (AD-532: 29, AD-533: 49, AD-534: 35, AD-532b: 48)
- [ ] New tests pass
- [ ] `_format_episode_blocks()`, `_parse_procedure_json()`, `_build_steps_from_data()` reused (not duplicated)
- [ ] Same `_extracted_cluster_ids` set used for both positive and negative cluster dedup
- [ ] ProcedureStore.save() handles is_negative=True correctly (routes to anti-patterns directory — already tested in AD-533)
