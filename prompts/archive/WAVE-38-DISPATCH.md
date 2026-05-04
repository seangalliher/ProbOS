# Wave 38 Dispatch — AD-688 v1 Oracle Graph Integration

**Status:** Pending
**Issue:** #382 (closes on merge)
**Prompt:** [`prompts/ad-688-oracle-graph-integration-v1.md`](ad-688-oracle-graph-integration-v1.md)
**Wave-plan slot:** id `"38"` (already populated, status `pending`)
**Predecessor:** Wave 37 (AD-687 v1 Knowledge Edge Store, commit `def4f37`, gate baseline 10990)
**Expected gate after build:** 11000–11002 (+10–11; one test may be absorbed by the known `test_knowledge_store::test_auto_commit_after_debounce` xdist flake)

---

## v1 Scope (one line)

Stitch the **Knowledge Edge Store (AD-687)** onto the **Oracle Service (AD-686/Wave-36)** as Tier 6: `_query_graph` async tier method + `_expand_via_graph` post-merge 1-hop enrichment + `attach_knowledge_graph` late-bind setter + runtime wiring at `runtime.py:1614` + provenance tags `[knowledge graph]` / `[graph expansion: <parent>]` + `"graph"` added to default `active_tiers` list.

**Captain's "complete v1" standing convention applies.** No deferral within AD-688 spec. Out-of-scope items are separate-issue work (#383/#384/#385/#386/#387), not v1 deferrals.

## Phase Context

Phase A (Foundation) of the Unified Knowledge Graph + Oracle Unification stack — **third of four** Phase-A ADs:
- AD-686 ✅ (Wave 36, Tier 5 Semantic) — `attach_semantic_layer` mirror precedent
- AD-687 ✅ (Wave 37, Edge Store + Protocol)
- **AD-688 (this) — Oracle ↔ Graph stitching**
- AD-689 (#383) — Edge backfill from existing data
- AD-690 (#384) — Dream Step 10 inference

After AD-688 lands the graph is **queryable but still empty in production**. Production utility arrives once AD-689 backfills it.

## Dependencies — Verify-First Findings (HEAD `ef34c85`)

| Dep | Status | Used in v1? |
|---|---|---|
| `OracleService.__init__` kwargs-only ctor | Shipped (`oracle_service.py:50–69`) | YES — append 10th kwarg `knowledge_graph` after `semantic_layer` |
| `attach_semantic_layer` setter (AD-686 Wave 36) | Shipped (`oracle_service.py:72–79`) | YES — mirrored exactly as `attach_knowledge_graph` |
| `_query_semantic` Tier-5 method shape | Shipped (`oracle_service.py:343–378`) | YES — mirrored as `_query_graph` (no `types=` kwarg) |
| Default `active_tiers` list | Shipped at `oracle_service.py:102` (5 tiers) | YES — append `"graph"` (6 tiers) |
| `OracleResult` frozen dc with separate `provenance: str` field | Shipped (`oracle_service.py:22–30`) | YES — provenance lives in dedicated field NOT metadata (Decision Log #1) |
| `KnowledgeEdgeStorage` Protocol + `find_edges` + `traverse` | Shipped (`knowledge/edges.py:130–167`) | YES — Tier 6 uses both |
| `KnowledgeEdge.weight`, `.confidence`, `.source_type`, `.source_id`, `.relation`, `.target_type`, `.target_id`, `.id` | Shipped (`knowledge/edges.py:73–96`) | YES — all read by Tier 6 + expansion |
| `runtime.knowledge_edges` adoption | Shipped (`runtime.py:1612`) | YES — late-bind setter inserted immediately after this line |
| `runtime.oracle` public alias = `runtime._oracle_service` | Shipped (`runtime.py:1326–1327`) | YES — same instance; reach via `_oracle_service` to mirror AD-686 wiring at `runtime.py:1531` |
| Phase ordering (cognitive → structural → communication) | Verified at `runtime.py:1326`, `1531`, `1612` | Late-bind at line 1614+ is safe — Oracle exists ≥285 lines earlier |

**Zero existing references** in `src/` or `tests/` for: `_query_graph`, `_expand_via_graph`, `attach_knowledge_graph`, `_extract_entity_tokens`, `_record_graph_hit`, `_GRAPH_DIRECT_LIMIT`, `_GRAPH_TRAVERSE_LIMIT`, `_GRAPH_EXPANSION_PER_PARENT`, `_GRAPH_HOP_PROXIMITY_*`, `_GRAPH_EXPANSION_DISCOUNT`, `_GRAPH_STOPWORDS`. Fully greenfield within `oracle_service.py`.

## Decision Log (architect calls — full list in prompt §"Decision Log")

1. **`OracleResult.provenance` is a top-level field, NOT a metadata key.** Captain's spec said `metadata: "[knowledge graph]"`; live shape has `provenance: str` separately at `oracle_service.py:29`. Tier 6 hits set `provenance="[knowledge graph]"`; expansion sets `provenance=f"[graph expansion: {parent.provenance}]"`. Parent's original provenance is mirrored into `metadata["expansion_source"]` for downstream filtering. **Builder must NOT relocate provenance into metadata** — it would break `query_formatted()` at `oracle_service.py:199`.
2. **Entity extraction = exact `entity_id` token match (v1 simple).** Lowercase + split + drop short/stopword tokens + dedupe; loop tokens through `find_edges(source_id=token)` AND `find_edges(target_id=token)`. NOT NER. AD-691 (#385) will add embedding-based fuzzy matching. Documented inline in module docstring.
3. **Hop-proximity scoring: 1.0 direct / 0.6 two-hop.** Direct = `find_edges` hit. 2-hop = `traverse(max_hops=1)` from each direct match's target. Score = `weight × confidence × hop_proximity`. Inline caps `_GRAPH_DIRECT_LIMIT=10`, `_GRAPH_TRAVERSE_LIMIT=5` per direct match.
4. **Dedupe by `edge.id` keeping max score.** A single edge can match multiple tokens / both directions / direct + traverse; keep the highest-scoring instance.
5. **`_expand_via_graph` runs BEFORE final sort/truncate.** Order: all 6 tiers run → expansion runs on top-K parents → all results sorted → truncated at `k_per_tier × 6`. Expansion results compete on score in the merged ranking.
6. **Expansion skips parents with `source_tier == "graph"`** — no double-counting.
7. **Expansion score** = `parent.score × 0.7 × edge.weight × edge.confidence`. Per-parent cap `_GRAPH_EXPANSION_PER_PARENT=5` prevents one rich parent from swamping the merge.
8. **Default `active_tiers` becomes 6 entries.** Order: `["episodic", "records", "operational", "archive", "semantic", "graph"]`. Backward-compatible — explicit `tiers=` callers unchanged.
9. **NO new EventType, NO new Pydantic config, NO new module.** All edits in `cognitive/oracle_service.py` + `runtime.py` + 1 new test file. Graph "enabled" implicit in `runtime.knowledge_edges is not None`.
10. **Cloud-Ready preserved.** `_knowledge_graph` typed `Any` to avoid `cognitive ↔ knowledge` import cycle; Protocol contract documented in method docstrings instead. Mirrors AD-686's `_semantic_layer: Any` precedent.
11. **`runtime.oracle` already exists** (AD-686 public alias at `runtime.py:1327`). **No new `runtime.X` attribute** in this AD; the late-bind reaches the existing instance via `runtime._oracle_service` (mirrors AD-686 wiring at `runtime.py:1531`).

## Phantom-API Pre-Check

Run before commit:

```pwsh
./scripts/phantom-api-precheck.ps1 prompts/ad-688-oracle-graph-integration-v1.md
```

**Expected:** ~6–10 FP candidates, all introduced-in-prompt-not-in-index. Documented FP class:

- `_query_graph`, `_expand_via_graph`, `_extract_entity_tokens`, `_record_graph_hit` — all introduced by Section 4.
- `attach_knowledge_graph` — introduced by Section 1b.
- `_GRAPH_DIRECT_LIMIT`, `_GRAPH_TRAVERSE_LIMIT`, `_GRAPH_EXPANSION_PER_PARENT`, `_GRAPH_HOP_PROXIMITY_DIRECT`, `_GRAPH_HOP_PROXIMITY_TWO_HOP`, `_GRAPH_EXPANSION_DISCOUNT`, `_GRAPH_MIN_TOKEN_LEN`, `_GRAPH_STOPWORDS` — all introduced by Section 2a.
- `OracleService(knowledge_graph=...)` kwarg — introduced by Section 1a.

If non-FP phantoms surface, document in build report; do NOT fix without architect review. Same intro-not-in-index FP class as Waves 27/28/29/31/32/33/35/36.

## Test Plan (11 tests; ≥10-floor for "complete v1" with 1-test margin)

1. `test_attach_knowledge_graph_late_binds` — late-bind setter swaps in graph; idempotent.
2. `test_query_graph_method_shape` — async, returns `list[OracleResult]`, `(query_text, *, k)`.
3. `test_query_graph_unattached_returns_empty` — `_knowledge_graph is None` → `[]`, debug log only.
4. `test_query_graph_one_hop_direct_match_source` — token matches `source_id` → 1 result with `provenance="[knowledge graph]"`, score = w × c × 1.0.
5. `test_query_graph_one_hop_direct_match_target` — token matches `target_id` (separate edge); same hop_proximity=1.0.
6. `test_query_graph_two_hop_with_proximity_discount` — A→B→C chain; B→C returned at 0.6× discount via `traverse`.
7. `test_query_graph_dedupe_keeps_highest_score` — same edge X→Y matched by both source-token and target-token → exactly one entry.
8. `test_default_active_tiers_includes_graph` — `query()` with all 6 tiers attached invokes `_query_graph` (spy/mock).
9. `test_expand_via_graph_happy_path` — 5 parents, each with token in `content` matching graph → expansion emitted with `[graph expansion: …]` provenance; score = parent × 0.7 × w × c.
10. `test_expand_via_graph_skips_graph_parents` — Tier 6 hit in top-K is NOT re-expanded.
11. `test_expand_via_graph_respects_top_k_and_per_parent_cap` — 10 parents but `top_k=3`; per-parent cap 5 → ≤15 expansion results.

Optional fold-in: `test_runtime_attaches_knowledge_graph_to_oracle` (smoke, mocks runtime slots + replays attach try/except) → if added, count = 12.

**Test-count baseline:** 10990 (post-Wave-37). Expected: 11000–11002 (+10–11 net; one may absorb).

Drop targets if drift: test #5 (target_id symmetry) or #11 (per-parent cap) — keeps 10-test floor.

## Build Quality Reminders

- **Property collision (Wave 32 retrospective).** `OracleService` is NOT a `CognitiveAgent` subclass; no `@property` shadow risk. **No new `runtime.X` attribute** — `runtime.oracle` and `runtime.knowledge_edges` already exist.
- **`provenance` field discipline.** Watch for any test or builder mistake that puts `"[knowledge graph]"` into `metadata` — it MUST live in the dedicated `provenance` field. `query_formatted()` reads `r.provenance` directly.
- **Stopword set tuning.** If a test fixture uses a 3-letter token that happens to be in `_GRAPH_STOPWORDS`, the test will silently emit `[]` from `_query_graph`. Use 4+-letter tokens like `alice`, `engine`, `dept` in fixtures, or pick tokens explicitly NOT in the stopword list (e.g., `engine`, `agent`, `medical`).
- **Late-bind ordering verified.** `runtime.py:1612` adopts `comm.knowledge_edges`; the new attach block goes immediately after. Oracle exists since `runtime.py:1326`.
- **`KnowledgeEdge.weight` and `.confidence` are floats in [0.0, 1.0]** (validated by AD-687 `__post_init__`). `_record_graph_hit` calls `float()` defensively in case a stub returns non-float.
- **Type narrowing via `Any`** to avoid `cognitive ↔ knowledge` circular import (mirrors AD-686 `_semantic_layer: Any`).

## Hard Stops (escalate to architect, do NOT proceed)

1. **`OracleService` ctor signature changed** beyond appending the 10th `knowledge_graph` kwarg.
2. **`OracleResult` shape changed** in any way (frozen dc, 5 fields stable since AD-462e).
3. **`KnowledgeEdgeStorage` Protocol signature changed** (would break the call sites).
4. **Phase ordering inverted** — if `runtime.knowledge_edges` is set BEFORE `_oracle_service`, the late-bind block at `runtime.py:1614+` becomes a no-op-with-warning silent regression.
5. **`query_formatted()` modified.** Out of scope; provenance-field discipline preserves it.

## Trackers to Update Post-Build

- **PROGRESS.md** — prepend AD-688 v1 entry (Wave 38).
- **roadmap.md** — flip AD-688 status: Scoped → Complete.
- **DECISIONS.md** — prepend at top of Era V.
- **GH issue #382** — Captain closes manually (EMU 403 blocks MCP issue close per Wave 27+ precedent).

## Single-Commit Mandate

```
Wave 38: AD-688 v1 Oracle graph integration (Tier 6 + post-merge expansion)
```

Pushed to origin/main. Wave plan id="38" already populated — left untouched in this draft commit.
