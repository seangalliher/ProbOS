# BF-134: Recall Pipeline Semantic Threshold + FTS Scoring + Watch Section Filtering

**Type:** Bug Fix
**Scope:** 2 Python files + config + tests
**Depends on:** BF-027 (original threshold lowering), BF-133 (anchor gate + Ward Room framing), AD-570 (anchor metadata promotion), AD-567b (salience-weighted recall), AD-582 (memory competency probes)
**Issue:** #136

---

## Overview

The entire crew (14/14 agents) fails three qualification probes: `seeded_recall_probe` (0.048–0.223), `temporal_reasoning_probe` (0.000–0.216), and `knowledge_update_probe` (0.000–0.750). Meanwhile `episodic_recall_probe` passes at 1.000 and `confabulation_probe` passes at 1.000. The cognitive architecture is sound — the recall pipeline is dropping valid episodes before agents ever see them.

**Root cause:** Three interrelated defects in `episodic.py`:

1. **Semantic threshold too aggressive.** `recall_for_agent_scored()` filters episodes below `min(self.relevance_threshold, 0.3)` cosine similarity. MiniLM is a sentence-similarity model, not a QA model — questions ("What pool health threshold was configured?") and their factual answers ("The pool health threshold was set to 0.7") produce cosine similarity of ~0.15–0.35. Episodes fall below 0.3 and are silently dropped. BF-027 originally lowered this from 0.7 to 0.3 for the same reason (Captain phrasing ≠ episode text). Now that BF-133's `anchor_confidence_gate` (0.3) provides quality filtering, the semantic threshold can be further relaxed without introducing noise — double-filtering produces excessive recall loss.

2. **FTS keyword hits get zero semantic credit.** When FTS5 keyword search finds an episode not found by semantic search, it's merged with `similarity=0.0` (`episodic.py:1424`). The composite score formula weights semantic at 0.35 — so a keyword-only hit loses 35% of its possible score. These episodes exist and have keyword relevance but score below organically similar episodes.

3. **Temporal filtering can't use watch section metadata.** `recall_by_anchor()` has no `watch_section` parameter, and `watch_section` is not promoted to top-level ChromaDB metadata (unlike `department`, `channel`, `trigger_type`, `trigger_agent`). AD-582c's `TemporalReasoningProbe` seeds episodes with `watch_section` metadata and expects filtering — but the retrieval path falls through to semantic search where "What happened during first watch?" has low overlap with "Pool health dropped to 45%."

**Evidence:** `retrieval_accuracy_benchmark` (bypasses cognitive pipeline, calls `recall_for_agent()` directly) scores 0.300–0.550 — episodes ARE in ChromaDB at marginal similarity. The threshold drops them.

---

## Prior Work Absorption

| Prior Work | What to Reuse | What NOT to Touch |
|---|---|---|
| **BF-027** (threshold lowering) | Same reasoning extends: shard filter provides safety, threshold can relax. Three sites use `min(self.relevance_threshold, 0.3)`: lines 937 and 1295. | BF-027's design rationale is still valid — just continue it |
| **BF-133** (anchor gate + WR framing) | `anchor_confidence_gate` (default 0.3) already provides quality filtering. This is why semantic threshold can be relaxed safely — two filters instead of one. | Probe framing is correct — no changes to `memory_probes.py` |
| **AD-570** (anchor metadata promotion) | Exact pattern at `_episode_to_metadata()` lines 1216–1227: promote to `metadata["anchor_<field>"]` with `or ""` coercion. Migration via `migrate_anchor_metadata()` at line 124 with upsert backfill. Where-clause construction at lines 1552–1570. | Migration guard at line 151 checks `"anchor_department" in meta` — already-migrated episodes need watch_section backfilled separately |
| **AD-567b** (salience-weighted recall) | FTS5 merge at line 1424: `ep_map[ep_id] = (ep, 0.0)`. Composite score formula at lines 1357–1363. | Score formula weights unchanged — only the FTS floor changes |
| **AD-582c** (TemporalReasoningProbe) | Seeds episodes with `watch_section` metadata, expects anchor-based temporal filtering. Will benefit directly from watch_section promotion. | No changes to the probe — it's correctly designed, just missing infrastructure |
| **AD-579** (Tiered Loading) | Planned, not started. Complementary to this fix (AD-579b adds `valid_from`/`valid_until`). No conflict — both add where-clause filters to `recall_by_anchor()`. | Do NOT implement AD-579 features |
| **MemoryConfig** (config.py) | `relevance_threshold: float = 0.7` at line 260, `anchor_confidence_gate: float = 0.3` at line 282, `recall_weights` at lines 265–272. Add new config fields here. | Do NOT change existing config defaults |

---

## Phase 1: Config Fields

**File:** `src/probos/config.py`

Add two new fields to `MemoryConfig` (near existing `relevance_threshold` at line 260):

```python
# BF-134: Agent-scoped recall threshold (replaces hardcoded 0.3 from BF-027).
# MiniLM question-vs-statement cosine similarity is typically 0.15-0.35.
# Anchor confidence gate provides quality filtering, allowing semantic
# threshold to be relaxed.
agent_recall_threshold: float = 0.15

# BF-134: Minimum semantic similarity floor for FTS5 keyword-only hits.
# Episodes found by keyword search but not semantic search get this
# floor instead of 0.0, preventing keyword-relevant episodes from
# being buried by the composite score formula.
fts_keyword_semantic_floor: float = 0.2
```

---

## Phase 2: Semantic Threshold + FTS Floor

**File:** `src/probos/cognitive/episodic.py`

### Change 1: Store config values in `__init__`

In `EpisodicMemory.__init__()` (line 358 area), accept the new config values. The `relevance_threshold` is already stored as `self.relevance_threshold` at line 364. Add:

```python
self._agent_recall_threshold = agent_recall_threshold  # BF-134
self._fts_keyword_floor = fts_keyword_floor  # BF-134
```

Add `agent_recall_threshold: float = 0.15` and `fts_keyword_floor: float = 0.2` to the `__init__` signature with defaults.

### Change 2: Update `recall_for_agent()` threshold (line 937 area)

Find:
```python
agent_recall_threshold = min(self.relevance_threshold, 0.3)
```

Replace with:
```python
agent_recall_threshold = min(self.relevance_threshold, self._agent_recall_threshold)
```

### Change 3: Update `recall_for_agent_scored()` threshold (line 1295)

Find:
```python
agent_recall_threshold = min(self.relevance_threshold, 0.3)
```

Replace with:
```python
agent_recall_threshold = min(self.relevance_threshold, self._agent_recall_threshold)
```

### Change 4: FTS keyword floor (line 1424 in `recall_weighted()`)

Find:
```python
ep_map[ep_id] = (ep, 0.0)  # No semantic score for keyword-only hits
```

Replace with:
```python
ep_map[ep_id] = (ep, self._fts_keyword_floor)  # BF-134: keyword presence implies baseline relevance
```

### Change 5: Wire config in startup

**File:** `src/probos/startup/cognitive_services.py`

Where `EpisodicMemory` is constructed, pass the new config values from `MemoryConfig`:

```python
agent_recall_threshold=memory_config.agent_recall_threshold,
fts_keyword_floor=memory_config.fts_keyword_semantic_floor,
```

---

## Phase 3: Watch Section Metadata Promotion

**File:** `src/probos/cognitive/episodic.py`

### Change 6: Promote watch_section in `_episode_to_metadata()` (line 1217 area)

After the existing 4 promoted fields inside the `if ep.anchors:` branch, add:

```python
metadata["anchor_watch_section"] = ep.anchors.watch_section or ""
```

In the `else` branch, add:

```python
metadata["anchor_watch_section"] = ""
```

### Change 7: Update migration

The existing `migrate_anchor_metadata()` at line 124 has a guard at line 151: `if "anchor_department" in meta:` — this skips already-migrated episodes.

**Problem:** Already-migrated episodes have `anchor_department` but NOT `anchor_watch_section`. Need to backfill both new and existing episodes.

**Solution:** Change the migration guard to check for the NEW field specifically:

```python
# BF-134: Check for the newest promoted field, not just any promoted field.
# Episodes migrated by AD-570 have anchor_department but lack anchor_watch_section.
if "anchor_watch_section" in meta:
    continue  # Already has all promoted fields
```

In the migration body, extract `watch_section` from `anchors_data` and add it to the metadata:

```python
meta["anchor_watch_section"] = anchors_data.get("watch_section", "") or ""
```

**Also** ensure the 4 existing fields are still written (in case they were missed somehow). The migration should write all 5 fields regardless of which are present — idempotent upsert.

### Change 8: Add `watch_section` parameter to `recall_by_anchor()` (line 1495)

Add `watch_section: str = ""` to the method signature.

In the where-clause construction block (line 1552 area), after the existing trigger_agent condition, add:

```python
if watch_section:
    conditions.append({"anchor_watch_section": watch_section})
```

### Change 9: Wire `watch_section` in `_try_anchor_recall()` (cognitive_agent.py line 2799)

The `AnchorQuery` dataclass already has `watch_section: str = ""` (source_governance.py line 611). Pass it through:

```python
results = await em.recall_by_anchor(
    department=anchor.department,
    trigger_agent=anchor.trigger_agent,
    participants=anchor.participants if anchor.participants else None,
    time_range=anchor.time_range,
    watch_section=anchor.watch_section,  # BF-134
    semantic_query=anchor.semantic_query,
    agent_id=agent_mem_id,
    limit=10,
)
```

---

## Phase 4: Tests

**File:** `tests/test_anchor_indexed_recall.py` (existing, ~23 tests)

### Updated tests:

1. **`test_episode_to_metadata_promotes_anchor_fields`** — Assert `anchor_watch_section` is present in promoted metadata.

2. **`test_episode_to_metadata_empty_anchors`** — Assert `anchor_watch_section` is `""` when anchors are None.

3. **`test_migrate_backfills_existing`** — Verify migration adds `anchor_watch_section` to episodes that already have `anchor_department` but not `anchor_watch_section`.

### New tests:

4. **`test_recall_by_anchor_watch_section_filter`** — Store 4 episodes: 2 with `watch_section="first_watch"`, 2 with `watch_section="second_watch"`. Call `recall_by_anchor(watch_section="first_watch")`. Assert only the 2 first_watch episodes are returned.

5. **`test_recall_by_anchor_watch_section_combined_with_department`** — Store episodes across departments and watch sections. Filter by both. Assert correct intersection.

6. **`test_migrate_backfills_watch_section_on_already_migrated`** — Create episodes with `anchor_department` already present but no `anchor_watch_section`. Run migration. Assert `anchor_watch_section` is populated from `anchors_json`.

**File:** `tests/test_ad567b_anchor_recall.py` (existing, AD-567b tests)

### Updated tests:

7. **`test_fts5_semantic_merge`** — Update to verify FTS-only hits get `similarity=0.2` (the configured floor) instead of `0.0`.

### New tests:

8. **`test_agent_recall_threshold_configurable`** — Create `EpisodicMemory` with `agent_recall_threshold=0.1`. Store an episode. Verify that an episode with cosine similarity 0.12 is returned (would be filtered at 0.3).

9. **`test_agent_recall_threshold_default`** — Verify default `agent_recall_threshold` is 0.15 (not 0.3).

10. **`test_fts_keyword_floor_configurable`** — Create `EpisodicMemory` with `fts_keyword_floor=0.3`. Trigger FTS-only merge. Assert the episode gets `similarity=0.3`.

11. **`test_fts_keyword_floor_boosts_composite_score`** — Store an episode findable by keyword but not semantic search. With `fts_keyword_floor=0.2`, verify composite score includes `0.35 * 0.2 = 0.07` semantic component (not 0.0).

12. **`test_threshold_and_anchor_gate_work_together`** — Store an episode with low semantic similarity (0.18) but good anchor confidence (0.5). With `agent_recall_threshold=0.15` and `anchor_confidence_gate=0.3`, verify it passes both filters. With `anchor_confidence_gate=0.6`, verify it's filtered by anchor gate (not threshold).

---

## Engineering Principles Compliance

| Principle | How Applied |
|---|---|
| **SRP** | Fix is isolated to retrieval scoring — no changes to cognitive pipeline, probes, or episode creation |
| **OCP** | New config fields extend `MemoryConfig` without changing existing fields or defaults |
| **DRY** | Watch section promotion follows exact existing pattern (4 fields already promoted). FTS floor uses same merge pattern. No new abstractions needed |
| **Fail Fast / Log-and-Degrade** | Migration is non-fatal (wrapped in try/except). Threshold relaxation is safe because anchor confidence gate provides quality filtering |
| **Defense in Depth** | Two-tier filtering preserved: semantic threshold (now configurable, default 0.15) + anchor gate (0.3). Shard filter (agent_ids) provides additional safety margin |
| **Cloud-Ready** | ChromaDB metadata promotion — no new storage backends. Config-driven values, no hardcoded constants |
| **Law of Demeter** | Uses existing public APIs (`recall_by_anchor()`, `_episode_to_metadata()`). No private member access |
| **ISP** | `watch_section` parameter is optional with empty-string default — callers that don't need it are unaffected |

---

## Files Modified Summary

| File | Changes |
|---|---|
| `src/probos/config.py` | 2 new `MemoryConfig` fields: `agent_recall_threshold`, `fts_keyword_semantic_floor` |
| `src/probos/cognitive/episodic.py` | `__init__` new params, threshold in 2 recall methods, FTS floor, `_episode_to_metadata()` watch_section, migration guard update, `recall_by_anchor()` watch_section param |
| `src/probos/cognitive/cognitive_agent.py` | `_try_anchor_recall()`: pass `watch_section` to `recall_by_anchor()` |
| `src/probos/startup/cognitive_services.py` | Pass new config values to `EpisodicMemory` constructor |
| `tests/test_anchor_indexed_recall.py` | 3 updated + 3 new tests |
| `tests/test_ad567b_anchor_recall.py` | 1 updated + 4 new tests |

**Total: 6 files, ~12 tests (3 updated + 7 new + 2 migration tests)**

---

## What NOT to Change

- **No changes to `memory_probes.py`.** The probes are correctly designed — the infrastructure is what's broken.
- **No changes to `source_governance.py`.** `parse_anchor_query()` already extracts `watch_section` correctly.
- **No changes to `proactive.py`.** Episode creation paths are not the problem — retrieval is.
- **No changes to `qualification_tests.py`.** The `_send_probe()` path through `handle_intent()` is correct.
- **Do NOT change the `anchor_confidence_gate` default (0.3).** It provides the quality filtering that makes threshold relaxation safe.
- **Do NOT implement AD-579 features** (tiered loading, temporal validity windows). That's a separate architecture change.
- **Do NOT change the composite score weights** (0.35/0.10/0.15/0.10/0.20/0.10). The weights are fine — the inputs are the problem.

---

## Builder Verification Checklist

After implementation, verify:

- [ ] Run `python -m pytest tests/test_anchor_indexed_recall.py tests/test_ad567b_anchor_recall.py -v` — all tests pass including new/updated
- [ ] Run `python -m pytest tests/ -k "episodic" -v` — no regressions in episodic memory tests
- [ ] Run `python -m pytest tests/ -k "recall" -v` — no regressions in recall-related tests
- [ ] Grep for `min(self.relevance_threshold, 0.3)` — should appear zero times (replaced by config field)
- [ ] Grep for `anchor_watch_section` — exists in `episodic.py` (metadata + migration + recall_by_anchor)
- [ ] Grep for `agent_recall_threshold` — exists in `config.py` and `episodic.py`
- [ ] Grep for `fts_keyword_semantic_floor` — exists in `config.py`
- [ ] Grep for `fts_keyword_floor` — exists in `episodic.py` (constructor + recall_weighted)
- [ ] Verify `recall_by_anchor` signature includes `watch_section: str = ""`
- [ ] Verify `_try_anchor_recall` passes `watch_section=anchor.watch_section`
- [ ] Full suite: `python -m pytest tests/ --timeout=30 -x` — no regressions
- [ ] Update tracking: PROGRESS.md (BF-134 CLOSED), DECISIONS.md, roadmap.md bug tracker entries
