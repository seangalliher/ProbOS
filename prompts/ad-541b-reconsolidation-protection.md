# Build Prompt: AD-541b — Reconsolidation Protection: Read-Only Memory Framing

**Ticket:** AD-541b
**Priority:** Medium (data integrity — prevents silent memory corruption during dream processing)
**Scope:** Generalize READ-ONLY framing to all dream LLM calls, harden episode immutability, wire SIF integrity check
**Principles Compliance:** Defense in Depth (multi-layer protection: prompt framing + frozen dataclass + storage guard + SIF check), DRY (reuse existing `_format_episode_blocks()` pattern), Single Responsibility (each protection layer has one job), Fail Fast (SIF check logs violations immediately)
**Dependencies:** AD-541 MVP (COMPLETE — episode verification, social provenance, memory hierarchy), AD-532 (COMPLETE — `_format_episode_blocks()` READ-ONLY pattern), AD-534 (COMPLETE — procedure extraction pipeline)

---

## Context

During dream cycles, episode content flows through LLM calls for procedure extraction, evolution, and observational learning. AD-532 introduced `_format_episode_blocks()` with `=== READ-ONLY EPISODE ===` boundary markers for the three core extraction functions. But **5 of 8 LLM-calling functions** in `procedures.py` have gaps:

- 3 evolution functions send parent procedure content without READ-ONLY markers
- 5 system prompts lack explicit READ-ONLY awareness
- Contradiction context in negative extraction has no READ-ONLY markers
- The `Episode` dataclass is mutable (`@dataclass` without `frozen=True`)
- ChromaDB uses `upsert()` which silently overwrites existing episodes
- `SIF.check_memory_integrity()` is a stub returning `passed=True`

Biological analog: **synaptic reconsolidation** — when a memory is recalled, it enters a labile state where it can be modified before re-storage. AD-541b prevents this by ensuring episodes are structurally immutable and all LLM processing treats source material as read-only.

The principle: **episodes are historical records**. Derived insights (Procedures, convergence reports, quality metrics) are new artifacts that *reference* episode IDs — they never modify the source.

---

## Architecture

### Layer 1: Prompt-Level Protection (LLM framing)

Extend the existing `=== READ-ONLY ===` boundary pattern to ALL content blocks sent to dream LLM calls. Three block types need protection:

1. **Episode blocks** — ALREADY PROTECTED via `_format_episode_blocks()` in all 7 episode-processing calls
2. **Parent procedure blocks** — NOT protected in `evolve_fix_procedure()`, `evolve_derived_procedure()`, `evolve_fix_from_fallback()`
3. **Context blocks** — NOT protected: contradiction context in `extract_negative_procedure_from_cluster()`, LLM response in `evolve_fix_from_fallback()`

### Layer 2: Structural Immutability (Python-level)

Make the `Episode` dataclass frozen after construction to prevent in-memory mutation during dream processing.

### Layer 3: Storage Guard (ChromaDB write-once)

Replace `upsert()` with `add()` + conflict detection to prevent silent episode overwrites.

### Layer 4: SIF Verification (Runtime integrity check)

Wire the existing `SIF.check_memory_integrity()` stub to perform actual verification.

---

## Deliverables

### D1: READ-ONLY framing for parent procedure blocks

**File:** `src/probos/cognitive/procedures.py`

**1a.** Create `_format_procedure_block(procedure, label: str = "PROCEDURE") -> str` helper (follows `_format_episode_blocks()` pattern):

```python
def _format_procedure_block(procedure: Any, label: str = "PROCEDURE") -> str:
    """Format a procedure as an AD-541b READ-ONLY block."""
    proc_json = json.dumps(procedure.to_dict(), indent=2, default=str)
    return (
        f"=== READ-ONLY {label} (do not modify source — generate new artifact) ===\n"
        f"{proc_json}\n"
        f"=== END READ-ONLY {label} ==="
    )
```

**1b.** Update `evolve_fix_procedure()` (~line 725): Replace the raw `=== DEGRADED PROCEDURE ===` block with `_format_procedure_block(parent, "DEGRADED PROCEDURE")`.

**1c.** Update `evolve_derived_procedure()` (~line 810): Replace each `=== PARENT PROCEDURE N ===` block with `_format_procedure_block(parent, f"PARENT PROCEDURE {i+1}")`.

**1d.** Update `evolve_fix_from_fallback()` (~line 1210): Replace `=== PROCEDURE TO REPAIR ===` block with `_format_procedure_block(parent, "PROCEDURE TO REPAIR")`.

**1e.** In the same `evolve_fix_from_fallback()`, wrap the LLM successful response:

```python
f"=== READ-ONLY LLM RESPONSE (do not modify — reference only) ===\n"
f"{llm_response}\n"
f"=== END READ-ONLY LLM RESPONSE ==="
```

**1f.** Update `extract_negative_procedure_from_cluster()` (~line 970): Wrap the contradiction context block:

```python
f"=== READ-ONLY CONTRADICTION CONTEXT (do not modify — reference only) ===\n"
f"{contradiction_text}\n"
f"=== END READ-ONLY CONTRADICTION CONTEXT ==="
```

### D2: System prompt READ-ONLY awareness

**File:** `src/probos/cognitive/procedures.py`

Add a READ-ONLY instruction line to these 5 system prompts. Insert as the **last line before the JSON output instruction** in each prompt:

- `_FIX_SYSTEM_PROMPT` (~line 316): Add `"All input blocks marked READ-ONLY are source material. Generate a NEW procedure — never modify the source."`
- `_DERIVED_SYSTEM_PROMPT` (~line 351): Same line.
- `_FALLBACK_FIX_SYSTEM_PROMPT` (~line 1144): Same line.
- `_COMPOUND_SYSTEM_PROMPT` (~line 876): Same line.
- `_SYSTEM_PROMPT` (~line 284): Same line.

Additionally, add the instruction `"Do not alter, embellish, or reinterpret individual episodes."` to the **user prompt** of calls 4, 5, and 6 (the three evolution functions) — currently only calls 1, 2, 3 have this.

### D3: Frozen Episode dataclass

**File:** `src/probos/types.py`

**3a.** Change `Episode` from `@dataclass` to `@dataclass(frozen=True)`:

```python
@dataclass(frozen=True)
class Episode:
    ...
```

**3b.** The `id` field currently defaults to `uuid.uuid4().hex`. With frozen dataclass, use `field(default_factory=lambda: uuid.uuid4().hex)` — this should already be the pattern. Verify all fields with mutable defaults use `field(default_factory=...)`.

**3c.** The `embedding` field (list) needs `field(default_factory=list)` — verify this is already the case. Same for `outcomes`, `agent_ids`, `shapley_values`, `trust_deltas`.

**3d.** Search the codebase for any code that mutates Episode fields after construction (e.g., `episode.field = value`). If found, refactor to construct a new Episode via `dataclasses.replace(episode, field=new_value)`. Common patterns to search for:
- `ep.embedding =` or `episode.embedding =`
- `ep.reflection =`
- `ep.source =`
- Any `setattr(episode, ...)` calls

Use `dataclasses.replace()` for any legitimate mutations. Do NOT suppress `FrozenInstanceError` — the point is to surface code that mutates episodes.

### D4: ChromaDB write-once guard

**File:** `src/probos/cognitive/episodic.py`

**4a.** In the `store()` method (~line 190), replace `self._collection.upsert()` with a write-once pattern:

```python
# Check if episode already exists
existing = self._collection.get(ids=[episode.id])
if existing and existing["ids"]:
    logger.warning(
        "Episode %s already exists — skipping store (write-once)",
        episode.id[:12],
    )
    return  # Do not overwrite

self._collection.add(
    ids=[episode.id],
    documents=[doc],
    metadatas=[meta],
)
```

**4b.** Keep `upsert()` available as an explicit `_force_update()` private method for future migration/repair tools, but do NOT call it from the normal `store()` path. Add a docstring: `"""Bypass write-once for migration only. Do not call from normal code paths."""`

**4c.** Verify that no other code path calls `self._collection.upsert()` or `self._collection.update()` on episodes. If found, route through the write-once guard or document why the bypass is justified.

### D5: SIF memory integrity check

**File:** `src/probos/sif.py`

**5a.** Find the `check_memory_integrity()` stub. Replace with an actual check:

```python
async def check_memory_integrity(self) -> SIFCheckResult:
    """Verify episode storage integrity."""
    issues = []

    if not self._runtime.episodic_memory:
        return SIFCheckResult(name="memory_integrity", passed=True, details="no episodic memory configured")

    em = self._runtime.episodic_memory
    # Sample recent episodes and verify they have required fields
    try:
        recent = await em.recent(k=10)
        for ep in recent:
            if not ep.id:
                issues.append(f"Episode missing ID")
            if not ep.source:
                issues.append(f"Episode {ep.id[:8]} missing source provenance")
            if ep.timestamp <= 0:
                issues.append(f"Episode {ep.id[:8]} has invalid timestamp")
    except Exception as exc:
        issues.append(f"Episode recall failed: {exc}")

    passed = len(issues) == 0
    return SIFCheckResult(
        name="memory_integrity",
        passed=passed,
        details="; ".join(issues) if issues else "ok",
    )
```

**5b.** Verify that `check_memory_integrity()` is already in the SIF check cycle. If not, add it to the list of checks that run during the SIF periodic sweep.

---

## Scope Exclusions

1. **Content hashing / cryptographic signatures on episodes** — Deferred to **AD-541e** (Episode Content Integrity). Would require hash-chain similar to Identity Ledger. AD-541b focuses on prevention (read-only framing + immutability); AD-541e adds detection (content verification).
2. **Confabulation rate tracking** — Deferred to **AD-541d** (Counselor Guided Reminiscence). Requires Counselor therapeutic sessions to measure.
3. **Memory integrity score in CognitiveProfile** — Deferred to **AD-541d**. AD-541b provides the infrastructure AD-541d will measure.
4. **Spaced retrieval therapy** — **AD-541c**, separate scope, depends on Counselor scheduling.
5. **Episode deletion audit trail** — Deferred to **AD-541f** (Episode Eviction Audit Trail). The `_evict()` method deletes oldest episodes for capacity management. AD-541f adds append-only eviction logging for forensic analysis.

---

## Test Requirements (24 tests)

### D1 Tests — READ-ONLY procedure framing (6 tests)

1. `test_format_procedure_block_contains_readonly_markers` — Verify `_format_procedure_block()` output contains `=== READ-ONLY` and `=== END READ-ONLY` boundaries with the label.
2. `test_format_procedure_block_contains_procedure_json` — Verify the procedure's JSON content appears between the boundaries.
3. `test_evolve_fix_uses_readonly_procedure_block` — Mock LLM, call `evolve_fix_procedure()`, assert the prompt sent to LLM contains `READ-ONLY DEGRADED PROCEDURE`.
4. `test_evolve_derived_uses_readonly_procedure_blocks` — Mock LLM, call `evolve_derived_procedure()`, assert prompt contains `READ-ONLY PARENT PROCEDURE`.
5. `test_evolve_fix_from_fallback_uses_readonly_blocks` — Mock LLM, call `evolve_fix_from_fallback()`, assert prompt contains `READ-ONLY PROCEDURE TO REPAIR` and `READ-ONLY LLM RESPONSE`.
6. `test_negative_extraction_contradiction_context_readonly` — Mock LLM, call `extract_negative_procedure_from_cluster()` with contradiction data, assert prompt contains `READ-ONLY CONTRADICTION CONTEXT`.

### D2 Tests — System prompt awareness (3 tests)

7. `test_system_prompts_contain_readonly_instruction` — Verify all 5 system prompt constants contain the READ-ONLY instruction text.
8. `test_evolution_user_prompts_contain_no_alter_instruction` — Mock LLM, call each of the 3 evolution functions, assert user prompt contains "Do not alter, embellish, or reinterpret".
9. `test_all_dream_llm_calls_have_readonly_framing` — Comprehensive: call each of the 7 episode-processing functions with mocked LLM, verify every prompt contains at least one `=== READ-ONLY` marker.

### D3 Tests — Frozen Episode (6 tests)

10. `test_episode_is_frozen` — Construct an `Episode`, attempt to set a field (`ep.source = "secondhand"`), assert `FrozenInstanceError` is raised.
11. `test_episode_replace_creates_new_instance` — Use `dataclasses.replace(ep, source="secondhand")`, verify new episode has updated field, original unchanged.
12. `test_episode_default_factories_work_with_frozen` — Construct `Episode()` with no args, verify all default fields are correctly initialized (id is a UUID hex, outcomes is empty list, etc.).
13. `test_episode_equality_by_value` — Two episodes with same field values should be equal (`frozen=True` adds `__eq__` and `__hash__`).
14. `test_episode_hashable` — Verify `hash(episode)` works (frozen dataclasses are hashable). Verify episodes can be added to a set.
15. `test_episode_with_all_fields` — Construct Episode with all fields populated, verify no construction errors.

### D4 Tests — Write-once guard (5 tests)

16. `test_store_new_episode_succeeds` — Store a new episode, verify it's retrievable.
17. `test_store_duplicate_episode_id_skipped` — Store an episode, store another with same ID but different content, verify original content is preserved (not overwritten).
18. `test_store_duplicate_logs_warning` — Store duplicate, verify logger.warning was called with "write-once" message.
19. `test_force_update_bypasses_guard` — Use `_force_update()` with same ID, verify content IS overwritten (migration escape hatch).
20. `test_no_upsert_in_normal_store_path` — Read the `store()` method source, verify it does not call `upsert()`. (Or mock the collection and verify `add()` is called, not `upsert()`.)

### D5 Tests — SIF integrity check (4 tests)

21. `test_sif_memory_integrity_passes_with_valid_episodes` — Mock episodic memory with valid episodes, verify check passes.
22. `test_sif_memory_integrity_fails_missing_source` — Mock an episode with empty `source`, verify check detects it.
23. `test_sif_memory_integrity_fails_invalid_timestamp` — Mock an episode with `timestamp=0`, verify check detects it.
24. `test_sif_memory_integrity_no_episodic_memory` — Runtime with no episodic memory configured, verify check passes gracefully.

---

## Validation Checklist

Before marking complete, verify:

- [ ] All 7 episode-processing LLM functions in `procedures.py` have READ-ONLY markers on ALL input blocks (episodes, procedures, context)
- [ ] All 5 system prompts contain the READ-ONLY instruction
- [ ] All 3 evolution function user prompts contain "Do not alter, embellish, or reinterpret"
- [ ] `Episode` dataclass is `frozen=True` — no `FrozenInstanceError` in existing tests
- [ ] No code in the codebase mutates Episode fields after construction (search for `episode.field =` patterns)
- [ ] ChromaDB `store()` uses `add()` not `upsert()` — duplicate IDs are logged and skipped
- [ ] `_force_update()` exists as documented escape hatch
- [ ] SIF `check_memory_integrity()` performs actual checks, not stub
- [ ] All 24 tests pass
- [ ] Existing AD-532/534/537/538/539 procedure tests still pass (0 regressions)
- [ ] Existing AD-541 memory integrity tests still pass (0 regressions)

---

## File Summary

| File | Changes |
|------|---------|
| `src/probos/cognitive/procedures.py` | D1: `_format_procedure_block()` helper, update 4 functions with READ-ONLY blocks. D2: update 5 system prompts + 3 user prompts |
| `src/probos/types.py` | D3: `@dataclass(frozen=True)` on Episode, verify default factories |
| `src/probos/cognitive/episodic.py` | D4: write-once guard in `store()`, `_force_update()` escape hatch |
| `src/probos/sif.py` | D5: implement `check_memory_integrity()` |
| `tests/test_ad541b_reconsolidation.py` | New: 24 tests |
| Various files (if Episode mutation found) | D3: refactor to `dataclasses.replace()` |
