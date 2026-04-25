# AD-538: Procedure Lifecycle Management

**Type:** Build Prompt
**AD:** 538
**Title:** Procedure Lifecycle Management — Decay, Re-validation, Deduplication, Archival
**Depends:** AD-533 ✅ (ProcedureStore), AD-534 ✅ (Replay/Quality Metrics), AD-535 ✅ (Graduated Compilation), AD-537 ✅ (Observational Learning), DreamingEngine ✅ (existing), RecordsStore ✅ (existing)
**Branch:** `ad-538-procedure-lifecycle`

---

## Context

Procedures currently have no lifecycle. Once created via dream extraction (AD-532) or observational learning (AD-537), they live forever in the ProcedureStore with no maintenance. A procedure extracted for a codebase that has since been refactored will silently fail at replay time. A procedure unused for months occupies the semantic index and distorts match results. Two procedures that cover the same intent with slight variations compete for selection without being consolidated.

The Cognitive JIT pipeline is complete from creation through promotion (AD-531→537), but the store itself is a write-mostly accumulator. AD-538 adds the missing lifecycle: decay, re-validation, deduplication, and archival. After AD-538, the procedure store stays fresh and relevant — old knowledge fades unless reinforced, stale knowledge is re-validated before being trusted, duplicate knowledge is merged, and truly obsolete knowledge is archived to Ship's Records.

**Intellectual lineage:**
- **Ebbinghaus (1885)** — Forgetting Curve. Knowledge decays without rehearsal. The decay mechanism mirrors this: unused procedures lose compilation levels, requiring re-validation before they're trusted again.
- **Spaced Repetition (Pimsleur 1967, Leitner 1972)** — Successful use reinforces and extends the decay window. A Level 4 procedure used regularly never decays.
- **Hebbian Decay** — ProbOS already implements Hebbian weight decay in Dream Step 2. AD-538 applies the same principle to procedures: connections not reinforced fade.

---

## Engineering Principles Compliance

- **SOLID (S):** Lifecycle operations are new methods on ProcedureStore (decay, archive, dedup), not bolted onto existing extraction or evolution methods. Dream step is a distinct function in dreaming.py.
- **SOLID (O):** Extends DreamingEngine via new Step 7f (after 7e observational, before 8 gap prediction). Extends ProcedureStore with lifecycle methods via public API. No modification to existing extraction/evolution functions.
- **SOLID (D):** Lifecycle operations depend on ProcedureStore abstraction (public `get_quality_metrics()`, `list_active()`, `deactivate()`), not internal SQLite queries.
- **Law of Demeter:** Don't reach into ProcedureStore's `_db`. Use public methods. Add new public methods where needed.
- **Fail Fast:** If a procedure can't be archived (RecordsStore unavailable), log and skip — don't block the dream cycle. Decay is always safe (worst case: procedure drops a level and gets re-validated on next use).
- **DRY:** Reuse `deactivate()` for archival (it already marks `is_active=0`). Reuse `get_quality_metrics()` for decay decisions. Reuse ChromaDB `find_matching()` for dedup similarity scoring. Reuse existing `diagnose_procedure_health()` pattern for lifecycle diagnosis.
- **Cloud-Ready Storage:** New columns follow existing ProcedureStore migration pattern.

---

## What NOT to Build

- **CodebaseIndex file watchers** — The roadmap mentions re-validation when codebase files change. CodebaseIndex has NO file watching capability. Building a file watcher is out of scope for AD-538. Instead, re-validation is triggered by **staleness** (time since last use) — a procedure unused for N days is probably stale regardless of why. File-change-triggered re-validation is a future enrichment when CodebaseIndex gets incremental re-indexing.
- **Procedure embedding generation** — ChromaDB already stores embeddings from `save()`. Dedup uses existing `find_matching()`. No new embedding model or custom similarity math.
- **Version diff UI** — AD-538 adds the data model for evolution diffs (already partially exists via `content_diff` and `change_summary`). HXI visualization is a separate concern.
- **Ship's Records archival cleanup** — AD-538 writes archived procedures to the `_archived/` directory in RecordsStore. Archival retention policy (e.g., delete after 1 year) is a future concern.
- **Automatic merge execution** — Dedup identifies merge candidates and flags them. Automatic merge (choosing the winner, combining stats) is too risky without human review. AD-538 flags; the Captain decides via shell command.

---

## What to Build

### Part 0: Config Constants

File: `src/probos/config.py`

Add constants:

```python
# AD-538: Procedure Lifecycle
LIFECYCLE_DECAY_DAYS: int = 30                  # Unused for this many days → lose 1 compilation level
LIFECYCLE_ARCHIVE_DAYS: int = 90                # Unused at Level 1 for this many days → archived
LIFECYCLE_DEDUP_SIMILARITY_THRESHOLD: float = 0.85  # ChromaDB cosine similarity → flag as duplicate
LIFECYCLE_DEDUP_MAX_CANDIDATES: int = 50        # Max procedures to scan for dedup per dream
LIFECYCLE_REVALIDATION_LEVEL: int = 2           # Decayed procedures drop to this level (Guided)
LIFECYCLE_MIN_SELECTIONS_FOR_DECAY: int = 3     # Don't decay procedures that haven't had a fair chance
```

---

### Part 1: ProcedureStore — `last_used_at` Column + Migration

File: `src/probos/cognitive/procedure_store.py`

**Problem:** There is no `last_used_at` column. The `updated_at` column is overloaded — it changes on every counter increment, level change, or promotion status change. Decay needs to know "when was this procedure last *selected for replay*?" not "when was any metadata last changed."

**Migration:** Add column via the existing `_migrate()` pattern:

```python
# AD-538: Procedure lifecycle
("last_used_at", "REAL DEFAULT 0.0"),
("is_archived", "INTEGER DEFAULT 0"),
```

**Update `record_selection()`** to also set `last_used_at = time.time()` when a procedure is selected for replay. This is the "rehearsal" timestamp that resets the decay clock.

**Update `save()`** to set `last_used_at = procedure.extraction_date` for newly created procedures (creation counts as first use).

**Add `last_used_at` and `is_archived` fields to the Procedure dataclass** in `procedures.py`:

```python
last_used_at: float = 0.0    # timestamp of last replay selection (AD-538)
is_archived: bool = False     # archived (removed from active index) (AD-538)
```

Update `to_dict()` and `from_dict()` accordingly.

---

### Part 2: ProcedureStore — Decay Method

File: `src/probos/cognitive/procedure_store.py`

New method: `decay_stale_procedures()`

```python
async def decay_stale_procedures(self, now: float | None = None) -> list[dict]:
    """AD-538: Decay procedures unused for longer than LIFECYCLE_DECAY_DAYS.

    Returns list of dicts describing what was decayed:
    [{"id": str, "name": str, "old_level": int, "new_level": int}]
    """
```

**Logic:**

1. Query all active, non-archived, non-negative procedures where:
   - `last_used_at > 0` (has been used at least once)
   - `last_used_at < now - (LIFECYCLE_DECAY_DAYS * 86400)`
   - `compilation_level > 1` (can't decay below Level 1)
   - `total_selections >= LIFECYCLE_MIN_SELECTIONS_FOR_DECAY` (had a fair chance)

2. For each qualifying procedure:
   - Reduce `compilation_level` by 1.
   - Reset `consecutive_successes` to 0 (must re-earn promotion).
   - Update `updated_at`.
   - Update the `content_snapshot` JSON blob.
   - Update ChromaDB metadata.
   - Log: "Procedure '{name}' decayed from Level {old} to Level {new} (unused for {days} days)."

3. Return the list of decay actions taken.

**Important:** Decay to Level 1 does NOT deactivate. It means the procedure will run in Novice mode (LLM verification required) on next use — which IS the re-validation mechanism. The LLM verifies the procedure is still correct for the current context. If the Novice replay succeeds, the procedure starts climbing back up. If it fails, the normal evolution pipeline (AD-532b) creates a FIX variant.

**Interaction with AD-536 promotion:** A decayed procedure that was previously `promotion_status="approved"` loses its Level 5 eligibility until it re-earns its way back. The `_max_compilation_level_for_promoted()` logic still gates Level 5 on compilation level — a decayed procedure at Level 2 can't jump back to Level 5 without climbing through 3 and 4 via consecutive successes. Promotion status itself is NOT revoked by decay (the institutional approval still stands; the individual agent just needs to re-validate competence).

---

### Part 3: ProcedureStore — Archival Method

File: `src/probos/cognitive/procedure_store.py`

New method: `archive_stale_procedures()`

```python
async def archive_stale_procedures(self, now: float | None = None) -> list[dict]:
    """AD-538: Archive procedures at Level 1 unused for LIFECYCLE_ARCHIVE_DAYS.

    Returns list of dicts describing what was archived:
    [{"id": str, "name": str, "days_unused": int}]
    """
```

**Logic:**

1. Query all active, non-archived procedures where:
   - `compilation_level == 1`
   - `last_used_at > 0` and `last_used_at < now - (LIFECYCLE_ARCHIVE_DAYS * 86400)`

2. For each qualifying procedure:
   - Set `is_archived = 1` in SQLite.
   - Set `is_active = 0` (removes from active dispatch).
   - Update `content_snapshot` JSON blob with `is_archived: true`.
   - Write to Ship's Records under `procedures/_archived/{id}.yaml` via RecordsStore (if available).
   - Remove from ChromaDB semantic index (so archived procedures don't distort match results).
   - Log: "Procedure '{name}' archived (unused at Level 1 for {days} days)."

3. Return the list of archival actions.

**Restoration:** Add a `restore_procedure()` method:

```python
async def restore_procedure(self, procedure_id: str) -> bool:
    """AD-538: Restore an archived procedure to active status at Level 1."""
```

Sets `is_archived = 0`, `is_active = 1`, `compilation_level = 1`, `last_used_at = now`, re-adds to ChromaDB. This is the "it came back" path — if a similar pattern re-emerges, the Captain can restore an archived procedure rather than extracting from scratch.

---

### Part 4: ProcedureStore — Deduplication Detection

File: `src/probos/cognitive/procedure_store.py`

New method: `find_duplicate_candidates()`

```python
async def find_duplicate_candidates(self) -> list[dict]:
    """AD-538: Find procedure pairs with high semantic similarity.

    Returns list of candidate merge pairs:
    [{"primary_id": str, "primary_name": str, "duplicate_id": str,
      "duplicate_name": str, "similarity": float}]
    """
```

**Logic:**

1. Load all active, non-negative, non-archived procedures (up to `LIFECYCLE_DEDUP_MAX_CANDIDATES`).

2. For each procedure, query ChromaDB `find_matching()` with the procedure's name + description as the query text.

3. Filter matches where:
   - `similarity > LIFECYCLE_DEDUP_SIMILARITY_THRESHOLD` (0.85)
   - The match is a different procedure (not self)
   - Both procedures share at least one `intent_type` (semantic similarity alone isn't enough — they must serve the same purpose)
   - The pair hasn't been flagged before (track flagged pairs to avoid re-flagging)

4. For each qualifying pair, determine the **primary** (higher `total_completions`, then higher `compilation_level`, then newer `extraction_date`) and the **duplicate**.

5. Return the sorted list of candidates.

**Important:** This method ONLY detects and flags. It does NOT merge. Merging requires a separate `merge_procedures()` method called explicitly by the Captain via shell command.

### Part 4b: Merge Method

New method: `merge_procedures()`

```python
async def merge_procedures(self, primary_id: str, duplicate_id: str) -> bool:
    """AD-538: Merge duplicate into primary. Deactivates duplicate,
    transfers stats to primary."""
```

**Logic:**
1. Load both procedures. Validate both exist and are active.
2. Add duplicate's `total_selections`, `total_applied`, `total_completions`, `total_fallbacks` to primary (preserving the combined track record).
3. Merge `tags` lists (union, deduplicated).
4. Merge `intent_types` lists (union, deduplicated).
5. If duplicate has `learned_via != "direct"`, preserve the observational provenance in primary's tags as `merged_from_observed:{duplicate.id}`.
6. Deactivate the duplicate via existing `deactivate(duplicate_id, superseded_by=primary_id)`.
7. Log: "Merged procedure '{dup.name}' into '{primary.name}' (similarity: {score})."
8. Return `True` on success.

---

### Part 5: Dream Step 7f — Lifecycle Maintenance

File: `src/probos/cognitive/dreaming.py`

Add **Step 7f** after Step 7e (observational learning) and before Step 8 (gap prediction).

```python
# Step 7f: Procedure lifecycle maintenance (AD-538)
```

**How it works:**

1. **Decay:** Call `procedure_store.decay_stale_procedures()`. Record count in `DreamReport.procedures_decayed`.

2. **Archive:** Call `procedure_store.archive_stale_procedures()`. Record count in `DreamReport.procedures_archived`.

3. **Dedup detection:** Call `procedure_store.find_duplicate_candidates()`. Record count in `DreamReport.dedup_candidates_found`. Log each candidate pair. Do NOT auto-merge — just flag and report.

4. Total Step 7f time recorded in DreamReport.

**Gate check:** If no ProcedureStore available, skip entirely.

**Performance:** Decay and archive are simple SQL queries. Dedup requires ChromaDB queries but is bounded by `LIFECYCLE_DEDUP_MAX_CANDIDATES`. Total Step 7f should complete in <100ms for typical stores (<200 procedures).

---

### Part 6: DreamReport Updates

File: `src/probos/types.py`

Add to the `DreamReport` dataclass:

```python
# AD-538: Procedure lifecycle
procedures_decayed: int = 0
procedures_archived: int = 0
dedup_candidates_found: int = 0
```

---

### Part 7: Shell Commands

File: `src/probos/experience/commands/commands_procedure.py`

Add to the existing `/procedure` command group:

**`/procedure stale [--days <N>]`**
- Lists procedures that would be affected by decay (unused for > N days, default: `LIFECYCLE_DECAY_DAYS`).
- Output: name, level, last_used_at (relative), total_completions.
- Does NOT apply decay — purely informational. Decay happens automatically in dreams.

**`/procedure archived [--count <N>]`**
- Lists archived procedures (most recently archived first).
- Output: name, archived date (relative), original level, total_completions.

**`/procedure restore <procedure_id>`**
- Calls `procedure_store.restore_procedure()`.
- Output: "Restored procedure '{name}' to Level 1 (active)." or error.

**`/procedure duplicates`**
- Calls `procedure_store.find_duplicate_candidates()`.
- Output: table of candidate pairs with similarity score.

**`/procedure merge <primary_id> <duplicate_id>`**
- Calls `procedure_store.merge_procedures()`.
- Output: "Merged '{dup}' into '{primary}'. Combined stats: {completions} completions." or error.

---

### Part 8: API Endpoints

File: `src/probos/routers/procedures.py`

Add to the existing procedures router:

**`GET /procedures/stale`**
- Query params: `days` (optional, default: `LIFECYCLE_DECAY_DAYS`)
- Returns procedures that haven't been used within the specified window.

**`GET /procedures/archived`**
- Query params: `limit` (optional, default: 20)
- Returns archived procedures.

**`POST /procedures/restore`**
- Body: `{ "procedure_id": str }`
- Restores an archived procedure.

**`GET /procedures/duplicates`**
- Returns duplicate candidate pairs with similarity scores.

**`POST /procedures/merge`**
- Body: `{ "primary_id": str, "duplicate_id": str }`
- Merges duplicate into primary.

---

## Guard Rails

### What to check before each Part

1. **Read the file you're modifying** before making changes.
2. **Search for existing implementations** — `deactivate()`, `get_quality_metrics()`, and `find_matching()` are your building blocks.
3. **Run targeted tests** after each Part completes.
4. **Follow existing patterns** — the AD-536/537 migration pattern, the Dream Step 7a-7e pattern, the existing shell command pattern.

### Interactions with existing code

- **`record_selection()` already exists** (line 571). Add `last_used_at = time.time()` to this method. This is the lightest touch — one line addition to an existing atomic increment method.
- **`deactivate()` already handles `is_active = 0`** (line 772). Archival reuses this logic but adds `is_archived = 1` and ChromaDB removal.
- **`find_matching()` uses ChromaDB** (line 484). Dedup calls this per-procedure, which means N ChromaDB queries. Bounded by `LIFECYCLE_DEDUP_MAX_CANDIDATES`.
- **`content_snapshot` JSON blob** — the get() method deserializes from this blob. New fields (`last_used_at`, `is_archived`) must be in both the SQLite columns AND the JSON blob (follow the `is_active`/`superseded_by` pattern from `deactivate()`).
- **DreamReport** — follow the AD-537 pattern (added `procedures_observed`, `observation_threads_scanned`, `teaching_dms_processed`). Just add new int fields.
- **Procedure.from_dict()** — must handle missing keys for backward compatibility (procedures serialized before AD-538 won't have `last_used_at` or `is_archived`). Use `.get("last_used_at", 0.0)` pattern.

### Scope boundaries

- **Decay is automatic.** It runs every dream cycle. No manual trigger needed (but `/procedure stale` lets the Captain preview what will decay).
- **Archival is automatic.** It runs every dream cycle. Captain can restore manually.
- **Dedup is detection-only.** Flagging is automatic. Merging is manual (Captain decides via `/procedure merge`). This prevents data loss — the Captain can review why two procedures are similar before deciding to merge.
- **No file-change re-validation.** CodebaseIndex has no file watchers. Staleness-based decay is the re-validation trigger. If a procedure is unused (because the relevant task type stopped occurring), it decays on schedule. If it's still used but the underlying code changed, it will fail at replay → fallback → evolution pipeline handles it (AD-534b).

---

## Tests

Target: **50-60 tests across 6 test files.**

### `tests/test_procedure_decay.py` (~10 tests)

1. `test_decay_reduces_compilation_level` — Level 4 unused for 30 days → Level 3
2. `test_decay_never_below_level_1` — Level 1 procedure unaffected by decay
3. `test_decay_resets_consecutive_successes` — consecutive_successes zeroed on decay
4. `test_decay_respects_min_selections` — procedure with <3 selections not decayed
5. `test_decay_skips_recently_used` — procedure used 10 days ago not decayed
6. `test_decay_skips_negative` — negative (anti-pattern) procedures not decayed
7. `test_decay_skips_archived` — already archived procedures not decayed
8. `test_decay_multiple_levels` — Level 4 unused 60 days → Level 3 (one level per cycle, not two)
9. `test_decay_returns_report` — return value includes id, name, old_level, new_level
10. `test_decay_updates_content_snapshot` — JSON blob reflects new level

### `tests/test_procedure_archival.py` (~10 tests)

1. `test_archive_stale_level_1` — Level 1 unused for 90 days → archived
2. `test_archive_sets_is_active_false` — is_active=0 after archival
3. `test_archive_sets_is_archived_true` — is_archived=1 after archival
4. `test_archive_skips_higher_levels` — Level 2+ not archived even if unused 90 days
5. `test_archive_writes_to_records` — RecordsStore `_archived/` receives YAML (if available)
6. `test_archive_removes_from_chromadb` — ChromaDB collection no longer contains archived procedure
7. `test_archive_returns_report` — return value includes id, name, days_unused
8. `test_restore_sets_active` — restore: is_active=1, is_archived=0, level=1
9. `test_restore_sets_last_used_at` — restore: last_used_at = now
10. `test_restore_readds_to_chromadb` — ChromaDB collection contains restored procedure

### `tests/test_procedure_dedup.py` (~10 tests)

1. `test_find_duplicates_high_similarity` — two near-identical procedures → flagged
2. `test_find_duplicates_low_similarity_skipped` — different procedures → not flagged
3. `test_find_duplicates_requires_shared_intent` — similar text but different intent_types → not flagged
4. `test_find_duplicates_primary_selection` — higher completion count wins primary
5. `test_find_duplicates_self_skip` — procedure doesn't match against itself
6. `test_merge_transfers_stats` — completion counts summed after merge
7. `test_merge_deactivates_duplicate` — duplicate has is_active=0, superseded_by=primary
8. `test_merge_unions_tags` — tags from both procedures combined
9. `test_merge_unions_intent_types` — intent_types from both combined
10. `test_merge_preserves_observational_provenance` — learned_via info tagged on primary

### `tests/test_dream_step_7f.py` (~8 tests)

1. `test_step_7f_runs_decay` — dream cycle calls decay_stale_procedures
2. `test_step_7f_runs_archival` — dream cycle calls archive_stale_procedures
3. `test_step_7f_runs_dedup` — dream cycle calls find_duplicate_candidates
4. `test_step_7f_updates_dream_report` — procedures_decayed, procedures_archived, dedup_candidates_found
5. `test_step_7f_no_store_graceful` — no ProcedureStore → step completes silently
6. `test_step_7f_runs_after_7e` — ordering: observational before lifecycle
7. `test_step_7f_decay_before_archive` — within step: decay runs first (may create Level 1), then archive checks
8. `test_step_7f_dedup_does_not_auto_merge` — dedup flags but does not call merge

### `tests/test_lifecycle_commands.py` (~7 tests)

1. `test_procedure_stale_command` — `/procedure stale` lists stale procedures
2. `test_procedure_stale_custom_days` — `--days 60` filter works
3. `test_procedure_archived_command` — `/procedure archived` lists archived procedures
4. `test_procedure_restore_command` — `/procedure restore <id>` restores
5. `test_procedure_duplicates_command` — `/procedure duplicates` lists candidates
6. `test_procedure_merge_command` — `/procedure merge <p> <d>` merges
7. `test_procedure_merge_invalid_ids` — bad IDs → error message

### `tests/test_lifecycle_routing.py` (~7 tests)

1. `test_api_stale_endpoint` — GET `/procedures/stale` returns stale procedures
2. `test_api_stale_custom_days` — `?days=60` query param works
3. `test_api_archived_endpoint` — GET `/procedures/archived` returns archived procedures
4. `test_api_restore_endpoint` — POST `/procedures/restore` restores procedure
5. `test_api_duplicates_endpoint` — GET `/procedures/duplicates` returns candidates
6. `test_api_merge_endpoint` — POST `/procedures/merge` merges
7. `test_api_merge_invalid` — bad IDs → 400 error

---

### `tests/test_procedure_last_used.py` (~5 tests)

1. `test_last_used_at_on_save` — newly saved procedure has last_used_at = extraction_date
2. `test_last_used_at_updated_on_selection` — record_selection() updates last_used_at
3. `test_last_used_at_persists` — save + get preserves last_used_at
4. `test_last_used_at_migration` — migration adds column with default 0.0
5. `test_to_dict_includes_last_used_at` — serialization includes new fields

---

## Existing Test Updates

Search for tests that may need adjustment:

- Tests that mock ProcedureStore and call `record_selection()` may need updating if the method signature changes (it doesn't — we're just adding a side effect).
- Tests that check `list_active()` results should still pass since archived procedures have `is_active=0`.
- Tests that count total procedures should be aware that `is_archived` procedures exist but are inactive.

---

## Verification

After all parts are complete:

1. Run all AD-538 tests: `uv run pytest tests/test_procedure_decay.py tests/test_procedure_archival.py tests/test_procedure_dedup.py tests/test_dream_step_7f.py tests/test_lifecycle_commands.py tests/test_lifecycle_routing.py tests/test_procedure_last_used.py -v`
2. Run all Cognitive JIT tests: `uv run pytest tests/test_episode_clustering.py tests/test_procedure_extraction.py tests/test_procedure_store.py tests/test_replay_dispatch.py tests/test_procedure_evolution.py tests/test_negative_extraction.py tests/test_compound_procedures.py tests/test_reactive_proactive.py tests/test_fallback_learning.py tests/test_multi_agent_replay_dispatch.py tests/test_graduated_compilation.py tests/test_procedure_criticality.py tests/test_promotion_eligibility.py tests/test_promotion_routing.py tests/test_promotion_approval.py tests/test_promotion_commands.py tests/test_promotion_integration.py tests/test_procedure_store_promotion.py tests/test_observational_extraction.py tests/test_dream_step_7e.py tests/test_teaching_protocol.py tests/test_level_5_dispatch.py tests/test_procedure_learned_via.py tests/test_observational_commands.py tests/test_observational_routing.py -v`
3. Run full suite: `uv run pytest tests/ -x -q`
