# Build Prompt: AD-551 — Notebook Consolidation (Dream Step 7g)

**Ticket:** AD-551
**Priority:** Medium (noise reduction pipeline, step 2 of 6)
**Scope:** Dream engine extension, RecordsStore consolidation, cross-agent convergence detection
**Principles Compliance:** DRY, Fail Fast (log-and-degrade), Law of Demeter, Cloud-Ready Storage
**Dependencies:** AD-434 (Ship's Records — COMPLETE), AD-531 (Episode Clustering — COMPLETE), AD-550 (Notebook Dedup — COMPLETE)

---

## Context

AD-550 added read-before-write dedup to the notebook system, gating ~60-70% of redundant writes at the source. But notebooks that were already written (or that passed the dedup gate with slightly different content) still accumulate. AD-551 adds a dream consolidation step that periodically:

1. **Intra-agent consolidation:** Clusters each agent's notebook entries by semantic similarity, merges redundant entries into canonical documents
2. **Cross-agent convergence detection:** Identifies when 3+ agents from 2+ departments independently wrote about the same topic with convergent conclusions — the crew's collective intelligence producing a validated finding
3. **Quantitative enrichment:** Auto-attaches available system metrics to consolidated entries

The iatrogenic trust detection convergence (Chapel + Cortez + Keiko, 2026-04-01) is the motivating case: three agents independently reached the same conclusion through different professional lenses, buried across 419 files. AD-551 would have surfaced that automatically.

---

## Architecture

### Where in the Dream Pipeline

The new step goes **after Step 7f (procedure lifecycle) and before the current Step 8 (gap detection)**. Following the existing sub-step naming convention, this is **Step 7g** — it's part of the knowledge-processing series (Steps 7–7f all process learned knowledge), not a new top-level step. This avoids renumbering existing Steps 8 and 9.

### RecordsStore Access

The dream engine currently accesses RecordsStore indirectly via `getattr(self._procedure_store, "_records_store", None)` (dreaming.py line 472). This violates Law of Demeter.

**Fix:** Wire `records_store` directly into `DreamingEngine.__init__()` as a new parameter. Follow the existing pattern of `ward_room`, `llm_client`, `procedure_store`, etc.

### Similarity Infrastructure

AD-550 added `_jaccard_similarity()` to `records_store.py` as a module-level helper. The shared canonical location is `cognitive/similarity.py` (`jaccard_similarity()` + `text_to_words()`). For intra-agent consolidation, Jaccard word-level similarity is sufficient (proven in BF-039, AD-506b, AD-550). ChromaDB embeddings are more powerful but add complexity — defer embedding-based consolidation to a future enhancement.

For cross-agent convergence, Jaccard is also sufficient for the MVP: compare conclusion sections of entries across agents.

---

## Deliverables

### Deliverable 1: Wire RecordsStore into DreamingEngine

**Files:** `src/probos/cognitive/dreaming.py`, `src/probos/startup/dreaming.py`, `src/probos/startup/finalize.py`

1. Add `records_store: Any = None` parameter to `DreamingEngine.__init__()` (after `emergence_metrics_engine`, line 69).
2. Store as `self._records_store = records_store`.
3. In `init_dreaming()` at `startup/dreaming.py` line 66-81, pass `records_store` to the `DreamingEngine` constructor. The records store isn't available at Phase 5 (dreaming init) — it's created in Phase 4 (cognitive services). So either:
   - Accept it as a parameter to `init_dreaming()` (preferred — matches `llm_client`, `procedure_store` pattern), OR
   - Late-wire it in `finalize.py` (matches `ward_room`, `get_department` pattern)

   **Check:** Read `startup/cognitive_services.py` to see if records_store is created before `init_dreaming()` is called. If yes, pass it directly. If no, late-wire in `finalize.py` at the existing AD-557 wiring block (line 86-92).

4. Update the existing `getattr(self._procedure_store, "_records_store", None)` usage in Step 8 (gap detection, line 472) to use `self._records_store` directly.

### Deliverable 2: Intra-Agent Notebook Consolidation (Step 7g)

**File:** `src/probos/cognitive/dreaming.py`

Add Step 7g between Step 7f and Step 8. Follow the existing error handling pattern (initialize counters before try, `except Exception`, `logger.debug` with "(non-critical)").

**Algorithm:**

```
1. Guard: if not self._records_store: skip
2. Get list of all agents with notebooks:
   - Use records_store.list_entries("notebooks/") to get all notebook entries
   - Group by agent (callsign = path.split("/")[1])
3. For each agent with 3+ entries:
   a. Load all entry contents via records_store.read_entry()
      Use reader_id="system" for dream consolidation access (bypasses classification)
      NOTE: read_entry() enforces classification. Dream consolidation needs system-level
      access. If read_entry() blocks on classification, either:
      - Add a reader_id="system" bypass, OR
      - Read files directly via _safe_path() (less clean but matches existing Step 8 pattern)
   b. Compute pairwise Jaccard similarity (using text_to_words + jaccard_similarity
      from cognitive/similarity.py)
   c. Find clusters: entries with similarity >= consolidation_threshold (config, default 0.6)
      Use simple single-linkage: if entry A matches B and B matches C, they form one cluster.
   d. For each cluster of 2+ entries:
      - Select the MOST RECENT entry as the "primary" (highest `updated` timestamp)
      - Merge content: concatenate unique observations from non-primary entries
      - Build consolidated content with:
        - Original primary content
        - "## Consolidated Observations" section with unique content from other entries
        - "Consolidated from N entries" note in frontmatter
      - Write the consolidated entry to the primary's path via records_store.write_entry()
        (this triggers AD-550's update-in-place: preserves created, increments revision)
      - Move non-primary entries to _archived/{original_path} via file rename + git add
      - Track: increment notebook_consolidations counter
4. Log summary: "Step 7g: Consolidated {n} notebook clusters across {m} agents"
```

**Important:** This step does NOT use LLM calls. It's deterministic text merging. LLM-powered summarization is a future enhancement. Keep it simple — concatenate unique content, let the agent update it naturally on next write (which AD-550's dedup gate will route to an update).

**Config:** Add to `DreamingConfig` in `config.py`:
```python
# AD-551: Notebook consolidation
notebook_consolidation_enabled: bool = True
notebook_consolidation_threshold: float = 0.6  # Jaccard similarity for clustering
notebook_consolidation_min_entries: int = 2     # Minimum cluster size to consolidate
```

### Deliverable 3: Cross-Agent Convergence Detection

**Files:** `src/probos/cognitive/dreaming.py`, `src/probos/events.py`

After intra-agent consolidation, scan for cross-agent convergence:

```
1. Guard: need entries from 3+ agents across 2+ departments
2. Collect all notebook entries with their agent callsign and department
   (department from frontmatter, or resolve via self._get_department if available)
3. Build a cross-agent similarity matrix:
   - For each pair of entries from DIFFERENT agents, compute Jaccard similarity
   - Track matches above convergence_threshold (config, default 0.5)
4. Find convergence clusters:
   - Group matches where 3+ agents from 2+ departments have similar content
   - Compute cluster coherence: average pairwise similarity
5. For each convergence cluster:
   a. Generate a Convergence Report as a Ship's Records document:
      - Path: reports/convergence/convergence-{timestamp_slug}.md
      - Classification: "ship" (visible to all crew)
      - Frontmatter: author="system", type="convergence_report",
        contributing_agents=[list], contributing_departments=[list],
        coherence_score=float, topic=inferred_topic
      - Content: "## Convergence Report", "### Contributing Perspectives"
        (one subsection per agent with their notebook snippet),
        "### Convergent Finding" (the shared conclusion extracted as the
        intersection of all contributing entries)
      - Write via records_store.write_entry()
   b. Emit CONVERGENCE_DETECTED event (new EventType)
   c. Track: append to convergence_reports list for DreamReport
6. Log summary: "Step 7g: Detected {n} convergence events"
```

**New EventType:** Add `CONVERGENCE_DETECTED = "convergence_detected"` to `events.py` EventType enum.

**Config:** Add to `DreamingConfig`:
```python
notebook_convergence_threshold: float = 0.5    # Cross-agent similarity threshold
notebook_convergence_min_agents: int = 3        # Minimum agents for convergence
notebook_convergence_min_departments: int = 2   # Minimum departments for convergence
```

### Deliverable 4: DreamReport Extension

**File:** `src/probos/types.py`

Add new fields to `DreamReport` (after the AD-557 emergence metrics block):

```python
# AD-551: Notebook consolidation
notebook_consolidations: int = 0
notebook_entries_archived: int = 0
convergence_reports_generated: int = 0
convergence_reports: list[Any] = field(default_factory=list)
```

Update the DreamReport construction at the end of `dream_cycle()` to include these fields.

Update the `DREAM_COMPLETE` event emission in `DreamScheduler` (3 locations: lines ~1393, ~1436, ~1497) to include `notebook_consolidations` and `convergence_reports_generated` in the event data dict.

### Deliverable 5: Convergence Bridge Notification

**Files:** `src/probos/bridge_alerts.py`, `src/probos/dream_adapter.py`

When convergence is detected during dreams, the Bridge should know. Add a new signal processor method to `BridgeAlertService`:

```python
def check_convergence(self, convergence_data: dict) -> list[BridgeAlert]:
```

Pattern: if `convergence_reports_generated > 0`, emit an ADVISORY-level alert:
- Title: "Crew Convergence Detected"
- Body: "{n} agents from {m} departments independently reached convergent conclusions on {topic}"
- Severity: ADVISORY (All Hands channel + Captain notification)
- Dedup key: `convergence:{topic_slug}` with standard 300s cooldown

Wire this into the post-dream flow. The `DreamAdapter` or runtime's `_on_post_dream()` handler should call `bridge_alerts.check_convergence()` when the DreamReport has `convergence_reports_generated > 0`.

---

## Files Modified (Expected)

| File | Change |
|------|--------|
| `src/probos/cognitive/dreaming.py` | `records_store` param, Step 7g (consolidation + convergence), update Step 8 getattr |
| `src/probos/startup/dreaming.py` | Pass `records_store` to DreamingEngine (or accept as param) |
| `src/probos/startup/finalize.py` | Late-wire `records_store` if not available at Phase 5 |
| `src/probos/types.py` | DreamReport new fields |
| `src/probos/events.py` | `CONVERGENCE_DETECTED` EventType |
| `src/probos/config.py` | DreamingConfig notebook consolidation/convergence settings |
| `src/probos/bridge_alerts.py` | `check_convergence()` signal processor |
| `src/probos/dream_adapter.py` | Wire convergence → bridge alert in post-dream |
| `tests/test_ad551_notebook_consolidation.py` | New test file |

---

## Prior Work to Absorb

| Source | What to Reuse | How |
|--------|---------------|-----|
| AD-550 `check_notebook_similarity()` | Dedup check pattern, `_jaccard_similarity()` in `records_store.py` | Use `cognitive/similarity.py` canonical versions instead (DRY). Do NOT add another copy. |
| AD-550 update-in-place | `write_entry()` preserves `created`, increments `revision` | Consolidated writes go through `write_entry()` — get this for free |
| AD-531 `cluster_episodes()` | Agglomerative clustering pattern in `episode_clustering.py` | Pattern reuse only — notebook clustering is simpler (Jaccard, no embeddings needed) |
| AD-506b `check_peer_similarity()` | Cross-agent similarity pattern in `ward_room/threads.py` | Conceptual pattern for cross-agent convergence detection |
| `cognitive/similarity.py` | `jaccard_similarity()`, `text_to_words()` | Import directly — this is the canonical shared location |
| Step 7/7c procedure extraction | Cluster → iterate → process → persist pattern in `dreaming.py` | Follow same structure for cluster → consolidate → write |
| Step 8 gap detection (line 472) | `getattr(self._procedure_store, "_records_store", None)` | Replace with direct `self._records_store` (Deliverable 1) |
| `BridgeAlertService.check_vitals()` | Signal processor pattern with dedup in `bridge_alerts.py` | Follow for `check_convergence()` |
| DreamScheduler event emission | DREAM_COMPLETE event pattern at 3 locations | Follow for adding consolidation counts to event data |

---

## Tests (25 minimum)

### TestNotebookConsolidation (10 tests)
1. Two similar entries (same agent, similarity > threshold) → consolidated into one, other archived
2. Three similar entries → all merged into primary (most recent)
3. Entries below threshold → not consolidated
4. Entries from different agents → not consolidated (intra-agent only)
5. Single entry agent → skipped (min_entries guard)
6. Consolidated entry preserves original `created` timestamp (AD-550 update-in-place)
7. Consolidated entry has incremented `revision` count
8. Archived entries moved to `_archived/` path
9. DreamReport.notebook_consolidations reflects count
10. Consolidation disabled via config → step skipped

### TestCrossAgentConvergence (8 tests)
11. 3 agents, 2 departments, similar content → convergence report generated
12. 2 agents only → below threshold, no convergence
13. 3 agents same department → below department threshold, no convergence
14. Convergence report written to `reports/convergence/` path
15. Convergence report has correct frontmatter (contributing_agents, departments, coherence_score)
16. CONVERGENCE_DETECTED event emitted with correct data
17. DreamReport.convergence_reports_generated reflects count
18. Convergence detection disabled via config threshold → skipped

### TestDreamEngineWiring (3 tests)
19. DreamingEngine accepts `records_store` parameter
20. Step 8 (gap detection) uses `self._records_store` directly (not getattr chain)
21. Step 7g skipped gracefully when `records_store` is None

### TestConvergenceBridgeAlert (3 tests)
22. `check_convergence()` returns ADVISORY alert when convergence detected
23. Dedup key prevents duplicate alerts within cooldown
24. No alert when convergence_reports_generated == 0

### TestDreamReportFields (1 test)
25. DreamReport includes notebook_consolidation and convergence fields with correct defaults

---

## Validation Checklist

- [ ] Step 7g executes without error when records_store is None (guard clause)
- [ ] Step 7g executes without error when records_store has no notebooks
- [ ] Intra-agent consolidation merges 2+ similar entries into one
- [ ] Non-primary entries are moved to `_archived/`
- [ ] Cross-agent convergence detected when 3+ agents from 2+ departments converge
- [ ] Convergence report written to Ship's Records with correct classification
- [ ] CONVERGENCE_DETECTED event emitted
- [ ] Bridge alert fires on convergence
- [ ] DreamReport includes all new fields
- [ ] DREAM_COMPLETE event includes notebook consolidation counts
- [ ] All existing dream cycle steps still pass (0 regressions)
- [ ] `records_store` wired directly (no getattr chain)
- [ ] Config knobs are in DreamingConfig with sensible defaults
- [ ] Log-and-degrade: Step 7g failure doesn't crash dream cycle

---

## Notes

- **No LLM calls in this step.** Consolidation is deterministic text merging. LLM-powered summarization is a future enhancement (when convergence reports could be LLM-polished).
- **Step numbering:** This is Step 7g, not Step 8. The current Step 8 (gap detection) and Step 9 (emergence metrics) keep their numbers.
- **AD-554 (real-time convergence)** is the natural follow-on — AD-551 detects convergence during dreams, AD-554 detects it in real-time after each notebook write.
- **The `_jaccard_similarity()` in `records_store.py`** (added by AD-550) duplicates `jaccard_similarity()` from `cognitive/similarity.py`. The builder should use the canonical `cognitive/similarity.py` versions for AD-551 code. Do NOT add another copy. If the records_store copy can be replaced with an import from `cognitive/similarity.py` without creating circular dependencies, do so as a DRY cleanup — but only if it's safe. Check import graph first.
- **Git operations for archive:** Moving files to `_archived/` should use `records_store._git("mv", old_path, new_path)` if available, or filesystem rename + git add. Check what git operations RecordsStore supports. The `_git()` helper at line 599 is a general-purpose async git wrapper that accepts any arguments.
- **read_entry() classification bypass:** Dream consolidation is a system-level operation. If `read_entry()` blocks on classification checks for `reader_id="system"`, you may need to add a system bypass or read files directly. Check the classification logic at `records_store.py` lines 247-252.
