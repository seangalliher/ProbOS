# Build Prompt: AD-550 — Notebook Deduplication (Read-Before-Write)

**Ticket:** AD-550
**Priority:** High (84% of notebook content is redundant noise)
**Scope:** RecordsStore notebook write path, proactive engine notebook handler, self-monitoring context
**Principles Compliance:** DRY (eliminate redundant writes), Fail Fast (log-and-degrade on similarity check failure), Defense in Depth (gate at both context and write layers), Cloud-Ready Storage (abstract interface on RecordsStore)

---

## Context

Empirical analysis of 419 notebook files across 11 agents after 72 hours of autonomous operation (2026-04-01) found **~84% of content is redundant**. Agents write "establishing baseline, will monitor" at every startup cycle without referencing prior entries. The signal-to-noise ratio across the fleet is ~16%.

**Root cause:** No read-before-write mechanism. When an agent emits a `[NOTEBOOK topic-slug]` block during proactive think, the content is written directly to `RecordsStore.write_notebook()` without checking whether an existing entry for that topic already exists or contains semantically identical content.

**Existing infrastructure (do NOT rebuild):**
- `RecordsStore.write_notebook()` at `src/probos/knowledge/records_store.py:197` — convenience method, delegates to `write_entry()`
- `write_entry()` at `records_store.py:76` — generates YAML frontmatter, writes file, git commit. **Already overwrites same-path files** (line 121). Git history preserves old versions.
- Proactive engine notebook handler at `src/probos/proactive.py:1231-1259` — extracts `[NOTEBOOK topic-slug]` blocks, calls `write_notebook()`
- Self-monitoring notebook injection at `proactive.py:932-968` — queries agent's existing notebook entries, injects index + semantic snippet into context. **Agents already SEE their recent notebooks but don't CHECK before writing.**
- `list_entries()` at `records_store.py:255` — lists documents with optional filters
- `read_entry()` at `records_store.py:225` — reads document with classification access control
- `search()` at `records_store.py:343` — keyword search across records
- `_parse_document()` at `records_store.py:407` — parses YAML frontmatter + content

**Prior art to absorb (patterns, not code):**
- **BF-039 (EpisodicMemory dedup):** Jaccard word-level similarity, threshold 0.8, 30-minute window. Proven lightweight approach. Reuse for notebook content comparison.
- **AD-506b (peer repetition detection):** `check_peer_similarity()` in `ward_room/threads.py:22-80` — Jaccard word-level similarity with configurable threshold. Same pattern applies.
- **AD-411 (EmergentDetector dedup):** SHA-based dedup cache. Fast path for exact-match detection.
- **AD-538 (procedure lifecycle dedup):** `find_duplicate_candidates()` uses ChromaDB cosine similarity > 0.85. ChromaDB is NOT available in RecordsStore — use Jaccard instead for AD-550.

---

## Design

### Three-Layer Deduplication

**Layer 1: Enhanced context (preventive — reduce redundant writes at the source)**
Improve the self-monitoring notebook injection (`proactive.py:932-968`) so agents have stronger awareness of what they've already written, reducing the likelihood of generating redundant `[NOTEBOOK]` blocks.

**Layer 2: Content similarity gate (write-time — suppress identical content)**
Before calling `write_notebook()`, compare new content against existing entry for the same `topic_slug`. If content is near-identical and entry is fresh, suppress the write entirely.

**Layer 3: Cross-topic redirect (write-time — catch same content under different slugs)**
Before writing, scan the agent's other notebook entries for similar content under different topic slugs. If a match is found, suppress the write and log which existing entry already covers the topic.

---

## Deliverables

### Deliverable 1: Jaccard similarity utility

**File:** `src/probos/knowledge/records_store.py`

Add a module-level utility function (NOT on the class — it's a pure function):

```python
def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Word-level Jaccard similarity between two texts."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)
```

This mirrors the proven pattern from BF-039 and AD-506b.

### Deliverable 2: Update-in-place mechanics on RecordsStore

**File:** `src/probos/knowledge/records_store.py`

Modify `write_entry()` to support update-in-place:

1. Before writing, check if the file already exists at the target path.
2. If it exists, read the existing frontmatter via `_parse_document()`.
3. Preserve the original `created:` timestamp from the existing frontmatter.
4. Increment `revision:` count (default 1 if not present, else +1).
5. Set `updated:` to current timestamp.
6. Write the updated document.

This should be the DEFAULT behavior of `write_entry()` when a file already exists — all callers benefit.

**Key constraint:** Do NOT change the method signature. The update-in-place is automatic when a file exists at the target path.

### Deliverable 3: Notebook dedup gate on RecordsStore

**File:** `src/probos/knowledge/records_store.py`

Add a new method to `RecordsStore`:

```python
async def check_notebook_similarity(
    self,
    callsign: str,
    topic_slug: str,
    new_content: str,
    *,
    similarity_threshold: float = 0.8,
    staleness_hours: float = 72.0,
) -> dict:
    """Check if a notebook write is redundant.

    Returns:
        {
            "action": "write" | "update" | "suppress",
            "reason": str,
            "existing_path": str | None,  # Path to matched entry
            "existing_content": str | None,  # Content of matched entry
            "similarity": float,  # Similarity score
        }
    """
```

Logic:

1. **Exact topic match:** Read `notebooks/{callsign}/{topic_slug}.md`. If exists:
   - Parse frontmatter, get `updated:` timestamp.
   - If entry is within `staleness_hours` AND Jaccard similarity ≥ `similarity_threshold`: return `action="suppress"` with reason "content unchanged from recent entry".
   - If entry is within `staleness_hours` AND similarity < threshold: return `action="update"` with existing content (genuinely new content for same topic).
   - If entry is older than `staleness_hours`: return `action="update"` (stale, allow refresh).

2. **Cross-topic scan:** If no exact topic match OR exact match allows write, scan all `notebooks/{callsign}/*.md` entries updated within `staleness_hours`. Compare `new_content` against each via Jaccard. If any entry matches ≥ `similarity_threshold`:
   - Return `action="suppress"` with reason "similar content exists at {matched_path}" and `existing_path` pointing to the matched entry.

3. **No match:** Return `action="write"` (fresh content, proceed normally).

**Performance guard:** The cross-topic scan reads files from disk. Cap the scan to the 20 most recently updated entries (sort by `updated` frontmatter field). This limits I/O for agents with large notebook histories.

### Deliverable 4: Wire dedup gate into proactive notebook handler

**File:** `src/probos/proactive.py`

Modify the notebook handler at lines 1231-1259. Before calling `write_notebook()`:

```python
# AD-550: Read-before-write dedup gate
dedup_result = await self._runtime._records_store.check_notebook_similarity(
    callsign=callsign,
    topic_slug=topic_slug,
    new_content=notebook_content,
)

if dedup_result["action"] == "suppress":
    logger.info(
        "AD-550: Notebook write suppressed for %s/%s: %s (similarity=%.2f)",
        callsign, topic_slug, dedup_result["reason"], dedup_result["similarity"],
    )
    actions_executed.append({
        "type": "notebook_suppressed",
        "topic": topic_slug,
        "callsign": callsign,
        "reason": dedup_result["reason"],
    })
    continue  # Skip this notebook block

# action is "write" or "update" — proceed to write_notebook()
```

**Fail-safe:** Wrap the dedup check in try/except. On any failure, fall through to the normal write path. Log-and-degrade, never block on dedup failure.

```python
try:
    dedup_result = await self._runtime._records_store.check_notebook_similarity(...)
except Exception:
    logger.debug("AD-550: Dedup check failed for %s/%s, writing anyway", callsign, topic_slug, exc_info=True)
    dedup_result = {"action": "write", "reason": "dedup_check_failed", "existing_path": None, "existing_content": None, "similarity": 0.0}
```

### Deliverable 5: Enhanced self-monitoring notebook context

**File:** `src/probos/proactive.py`

Enhance the self-monitoring notebook injection at lines 932-968. Currently injects an index (last 5 topics + updated timestamps) and one semantic snippet. Strengthen this so agents are less likely to generate redundant writes:

1. **Topic list with content previews:** For each of the last 5 entries, include the first 150 characters of content (not just the topic name). This gives the agent enough context to recognize "I already wrote about this."

2. **Recency indicator:** Add how long ago each entry was updated in human-readable form ("2h ago", "1d ago", "3d ago"). Agents currently see raw ISO timestamps which are harder to reason about.

3. **Entry count per topic:** Show total notebook entry count. "You have N notebook entries across M topics." This awareness helps agents self-regulate.

### Deliverable 6: Configuration

**File:** `src/probos/config.py`

Add notebook dedup configuration to `RecordsConfig`:

```python
class RecordsConfig(BaseModel):
    enabled: bool = True
    repo_path: str = ""
    auto_commit: bool = True
    commit_debounce_seconds: float = 5.0
    max_episodes_per_hour: int = 20
    # AD-550: Notebook dedup settings
    notebook_dedup_enabled: bool = True
    notebook_similarity_threshold: float = 0.8
    notebook_staleness_hours: float = 72.0
    notebook_max_scan_entries: int = 20
```

Wire these values through `check_notebook_similarity()` — do not hardcode thresholds.

---

## Test Specification

**Test file:** `tests/test_ad550_notebook_dedup.py`

### Jaccard utility tests (3 tests)
1. `test_jaccard_identical_text` — same text → 1.0
2. `test_jaccard_completely_different` — no word overlap → 0.0
3. `test_jaccard_partial_overlap` — known word sets → expected ratio

### Update-in-place tests (4 tests)
4. `test_write_entry_preserves_created_on_overwrite` — write twice to same path, second write preserves first `created:` timestamp
5. `test_write_entry_increments_revision` — write twice, revision goes from absent to 2
6. `test_write_entry_updates_updated_timestamp` — second write has later `updated:` than first
7. `test_write_entry_new_file_has_no_revision` — first write to new path has no `revision:` field (or revision: 1)

### check_notebook_similarity tests (8 tests)
8. `test_suppress_identical_same_topic` — existing entry, same topic, Jaccard > 0.8, within 72h → suppress
9. `test_allow_update_same_topic_different_content` — existing entry, same topic, Jaccard < 0.8 → update
10. `test_allow_update_stale_entry` — existing entry older than 72h even if identical → update
11. `test_suppress_cross_topic_similar_content` — different topic_slug but Jaccard > 0.8 with existing entry → suppress with existing_path
12. `test_allow_write_no_existing_entries` — no matching entries → write
13. `test_scan_cap_limits_entries_checked` — with > 20 entries, only checks 20 most recent
14. `test_returns_existing_content_on_update` — action="update" result includes existing entry content
15. `test_empty_content_handling` — empty new content or empty existing content → write (don't crash)

### Proactive engine integration tests (5 tests)
16. `test_notebook_write_suppressed_when_similar` — mock dedup returning suppress → write_notebook NOT called, action logged
17. `test_notebook_write_proceeds_when_fresh` — mock dedup returning write → write_notebook called normally
18. `test_notebook_dedup_failure_falls_through` — mock dedup raising exception → write_notebook still called (log-and-degrade)
19. `test_suppressed_notebook_appears_in_actions` — suppressed write produces `notebook_suppressed` action entry
20. `test_dedup_disabled_skips_check` — `notebook_dedup_enabled=False` → no dedup check, direct write

### Self-monitoring context tests (3 tests)
21. `test_notebook_index_includes_content_preview` — context includes first 150 chars of each entry
22. `test_notebook_index_includes_recency` — context includes human-readable recency ("2h ago")
23. `test_notebook_index_includes_entry_count` — context includes total entry/topic counts

### Configuration tests (2 tests)
24. `test_records_config_dedup_defaults` — default values match spec (threshold 0.8, staleness 72h, scan 20)
25. `test_dedup_uses_configured_threshold` — custom threshold propagates to check_notebook_similarity

**Total: 25 tests**

---

## Validation Checklist

- [ ] All 25 tests pass
- [ ] Existing RecordsStore tests still pass (no regressions on write_entry, write_notebook, list_entries, search)
- [ ] Existing proactive engine tests still pass
- [ ] Dedup gate is wrapped in try/except — verify no exception propagation
- [ ] `notebook_dedup_enabled=False` bypasses all dedup logic cleanly
- [ ] Update-in-place preserves `created:` timestamp (verify via test)
- [ ] Cross-topic scan is capped at `notebook_max_scan_entries`
- [ ] No new imports beyond standard library (no ChromaDB, no numpy — pure Jaccard)
- [ ] Config values wired through, not hardcoded
- [ ] Self-monitoring context renders cleanly (no raw ISO timestamps, human-readable recency)

---

## Files Modified

| File | Change |
|------|--------|
| `src/probos/knowledge/records_store.py` | `_jaccard_similarity()` utility, update-in-place in `write_entry()`, `check_notebook_similarity()` method |
| `src/probos/proactive.py` | Dedup gate before `write_notebook()` call (~1231), enhanced self-monitoring context (~932) |
| `src/probos/config.py` | `RecordsConfig` gains 4 dedup fields |
| `tests/test_ad550_notebook_dedup.py` | 25 new tests |

## Files NOT Modified

| File | Reason |
|------|--------|
| `src/probos/cognitive/dreaming.py` | Dream consolidation is AD-551, not AD-550 |
| `src/probos/cognitive/episodic.py` | EpisodicMemory dedup is BF-039, separate system |
| `src/probos/ward_room/threads.py` | Peer repetition detection is AD-506b, separate system |
| `src/probos/cognitive/episode_clustering.py` | Clustering is AD-531, used by AD-551 |

---

## Notes on AD-551 Preparation

AD-550 lays groundwork for AD-551 (Notebook Consolidation — Dream Step 8):
- `_jaccard_similarity()` will be reused by AD-551 for intra-agent cluster detection
- `check_notebook_similarity()` scan logic could be extended for cross-agent scanning
- Update-in-place mechanics enable dream consolidation to merge entries in place
- AD-551 will add ChromaDB-backed semantic similarity if Jaccard proves insufficient for cross-agent convergence detection

Do NOT build AD-551 functionality in this prompt. Keep scope tight to AD-550.
