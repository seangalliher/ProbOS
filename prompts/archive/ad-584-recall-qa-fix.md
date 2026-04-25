# AD-584: Recall Pipeline Q→A Fix — Embedding Model Swap + Query Reformulation

**Scope:** AD-584a (embedding model swap) + AD-584b (query reformulation + BF-029 prefix removal)
**Prerequisite research:** `docs/research/recall-pipeline-research-synthesis.md`
**Root cause:** `all-MiniLM-L6-v2` is a sentence-similarity model, not QA-trained. Questions and answers occupy different embedding subspaces — cosine similarity for valid Q→A pairs: 0.10–0.35, regardless of threshold tuning. BF-134 (threshold + FTS fixes) was necessary but insufficient.

---

## Problem

ProbOS qualification probes (`SeededRecallProbe`, `TemporalReasoningProbe`, `KnowledgeUpdateProbe`) fail because they ask questions about stored facts. The embedding model returns near-zero similarity between "What pool health threshold was configured?" and "The pool health threshold was set to 0.7 during this session." The BF-029 "Ward Room {callsign}" prefix prepended to queries actively pollutes embeddings by injecting non-question tokens.

## Solution — 2 Tiers (Interdependent)

### Tier 1: Swap Embedding Model

Replace `all-MiniLM-L6-v2` with `multi-qa-MiniLM-L6-cos-v1`. Same architecture (MiniLM-L6), same dimensions (384), same ONNX runtime, same inference speed. Trained on 215M question-answer pairs. Expected cosine improvement: 0.10–0.35 → 0.50–0.75 for Q→A queries.

### Tier 2: Template-Based Query Reformulation

Before embedding, detect question patterns and reformulate to declarative expected-answer templates. Zero LLM cost. Embed BOTH original and reformulated queries, take max similarity. Remove BF-029 prefix.

---

## File-by-File Changes

### 1. `src/probos/knowledge/embeddings.py` (160 lines currently)

**Change A — Model swap (line 84-107):**

The current `get_embedding_function()` returns `DefaultEmbeddingFunction()` which uses `all-MiniLM-L6-v2`. Change to use `multi-qa-MiniLM-L6-cos-v1`.

ChromaDB's `DefaultEmbeddingFunction` hardcodes the model name. Use `chromadb.utils.embedding_functions.ONNXMiniLM_L6_V2()` is also hardcoded. Instead, use the SentenceTransformer embedding function or a thin wrapper:

```python
# Option A — use chromadb's SentenceTransformerEmbeddingFunction:
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

_MODEL_NAME = "multi-qa-MiniLM-L6-cos-v1"

def get_embedding_function():
    global _ef
    if _ef is None:
        try:
            _ef = SentenceTransformerEmbeddingFunction(model_name=_MODEL_NAME)
        except Exception:
            _ef = _keyword_overlap_ef
    return _ef
```

**IMPORTANT:** `SentenceTransformerEmbeddingFunction` requires `sentence-transformers` package. Check if it's in `pyproject.toml` / `requirements.txt`. If not, add it. The current `DefaultEmbeddingFunction` uses ONNX via `onnxruntime` — it's a different runtime. If `sentence-transformers` is too heavy a dependency, an alternative is to download the ONNX model directly and adapt the existing ONNX wrapper. Verify which approach is lighter before implementing.

**Fallback:** Keep the `_keyword_overlap_ef` fallback (lines 36-73) unchanged. It catches environments where neither ONNX nor sentence-transformers is available.

**Change B — Add model name accessor:**

Add a module-level function to expose the model name for migration detection:

```python
def get_embedding_model_name() -> str:
    """Return the active embedding model name for migration detection."""
    return _MODEL_NAME
```

**Change C — Add query reformulation function:**

Add a `reformulate_query(text: str) -> list[str]` function that returns a list of query variants (original + reformulated). Keep it in this file since it's tightly coupled to embedding strategy.

Pattern matching (regex-based, ~50 lines):

| Pattern | Reformulation |
|---------|---------------|
| `What is/are X?` | `"X is"` |
| `What was/were X?` | `"X was"` |
| `How does X work?` | `"X works by"` |
| `How did X happen?` | `"X happened by"` |
| `Who did/does X?` | `"X"` (strip question structure) |
| `When did X?` | `"X happened"` |
| `Why did/does X?` | `"X because"` |
| `How many/much X?` | `"the number of X is"` / `"X is"` |
| `Did X?` / `Is X?` / `Was X?` | `"X"` (strip question structure) |

Rules:
- If no question pattern detected, return `[text]` (original only — not every query is a question)
- Strip trailing `?` from all variants
- Return `[original_stripped, reformulated]` — caller embeds both and uses max similarity
- Do NOT modify non-question text (e.g., statement-to-statement recall must still work)

### 2. `src/probos/config.py` (~lines 255-299, `MemoryConfig`)

Add to `MemoryConfig`:

```python
embedding_model: str = "multi-qa-MiniLM-L6-cos-v1"
query_reformulation_enabled: bool = True
```

The `embedding_model` field is used by migration detection (compare stored model vs. config). The `query_reformulation_enabled` flag allows disabling reformulation for debugging.

### 3. `src/probos/cognitive/episodic.py` (major changes)

**Change A — Migration function (new, top of file near existing migrations):**

Add `migrate_embedding_model(collection, episodes_db_path: str, model_name: str)`:

1. Store the current model name in ChromaDB collection metadata: `collection.modify(metadata={"hnsw:space": "cosine", "embedding_model": model_name})`
2. On startup, read `collection.metadata.get("embedding_model")` — if missing or different from current `get_embedding_model_name()`, trigger re-embedding
3. Re-embedding procedure:
   - Read all episode documents from the collection: `existing = collection.get(include=["documents", "metadatas"])`
   - Delete the collection: `client.delete_collection("episodes")`
   - Recreate with new embedding function: `collection = client.get_or_create_collection("episodes", embedding_function=ef, metadata={"hnsw:space": "cosine", "embedding_model": model_name})`
   - Re-add all documents in batches (batch size 100): `collection.add(ids=batch_ids, documents=batch_docs, metadatas=batch_metas)`
   - Log migration timing and count

**CRITICAL:** This must happen in `start()` AFTER the collection is created but BEFORE any queries. Existing migration ordering: BF-103 → AD-570 → AD-570b → **AD-584 embedding model** (new, last). The migration MUST handle the case where `collection.get()` returns episodes with no documents (possible if documents were stored as None — check defensive).

**Pattern reference:** Follow `migrate_anchor_metadata()` (line 135) for batch upsert patterns and `migrate_episode_agent_ids()` (line 52) for startup sequencing.

**Change B — Dual-query in `recall_for_agent_scored()` (~lines 1303-1358):**

Currently, one query goes to ChromaDB:
```python
results = self._collection.query(query_texts=[query], n_results=n_results, ...)
```

With reformulation:
```python
from probos.knowledge.embeddings import reformulate_query

query_variants = reformulate_query(query) if self._query_reformulation_enabled else [query]
# Query ChromaDB with ALL variants at once
results = self._collection.query(query_texts=query_variants, n_results=n_results, ...)
# Merge results: for each episode, take the BEST (lowest distance) across variants
# ChromaDB returns results per query — flatten and dedup by episode ID, keeping min distance
```

ChromaDB's `query()` accepts a list of `query_texts` and returns results per query. Merge logic:
- Iterate over all result sets, build a dict of `{episode_id: min_distance}`
- Convert back to sorted list by distance ascending
- Truncate to `n_results`

**Change C — Same dual-query in `recall_weighted()` (~lines 1408-1522):**

Apply same reformulation pattern at the ChromaDB query step inside `recall_weighted()`. The semantic distances feed into `score_recall()` — use the best (lowest) distance per episode.

**Change D — Pass config flag through constructor:**

Add `query_reformulation_enabled: bool = True` to `EpisodicMemory.__init__()`. Store as `self._query_reformulation_enabled`.

### 4. `src/probos/cognitive/cognitive_agent.py` (~lines 2465-2484)

**Remove BF-029 prefix from `_recall_relevant_memories()`:**

Current (lines 2470-2484):
```python
if intent.intent == "direct_message":
    callsign = self._runtime.callsign_registry.get_callsign(self.agent_type) or ""
    captain_text = params.get("text", "")[:150]
    query = f"Ward Room {callsign} {captain_text}".strip()[:200]
```

Change to:
```python
if intent.intent == "direct_message":
    captain_text = params.get("text", "")[:200]
    query = captain_text.strip()
```

Remove the `callsign_registry` lookup for query construction (it's still used elsewhere in the method — don't remove the variable if used later, but check). The `[:200]` truncation stays for ChromaDB query length limits.

**Why safe to remove:** The BF-029 prefix was a workaround for MiniLM's inability to match questions to Ward Room content. With `multi-qa-MiniLM-L6-cos-v1` (QA-trained), the question text alone produces good similarity to stored Ward Room episodes. The `[Ward Room]`/`[Ward Room reply]` prefixes remain on the stored episode content (in `threads.py:416` and `messages.py:217`) — those are useful content framing. Only the query-side prefix is removed.

**Keep the BF-029 comment updated:**
```python
# AD-584b: Removed BF-029 "Ward Room {callsign}" query prefix.
# With multi-qa-MiniLM-L6-cos-v1, the QA-trained model bridges
# question→answer gaps without prefix workarounds.
```

### 5. `src/probos/knowledge/semantic.py` (~lines 50-66, 302-378)

**Change A — Model migration in `start()`:**

SemanticKnowledgeLayer's 5 collections (`sk_agents`, `sk_skills`, `sk_workflows`, `sk_qa_reports`, `sk_events`) also use `get_embedding_function()`. They need re-embedding on model change.

In `start()`, after creating collections, check each collection's metadata for `embedding_model`. If missing or mismatched:
1. Delete the collection
2. Recreate with new embedding function and `embedding_model` in metadata
3. Call `reindex_from_store()` to repopulate (this is sufficient for semantic collections — their data comes from KnowledgeStore, not ChromaDB)

**Change B — Update `reindex_from_store()` to handle events:**

Currently events are not re-indexed by `reindex_from_store()`. Add event re-indexing from the events collection (or accept that events will be lost on model migration — document this tradeoff).

### 6. `src/probos/cognitive/procedure_store.py` (~lines 274-293)

**Change — Model migration in `_init_chroma()`:**

Same pattern as episodic and semantic: check collection metadata for `embedding_model`, delete+recreate if mismatched. ProcedureStore data is backed by SQLite (`procedures.db`), so the ChromaDB collection can be repopulated from the SQLite source.

Add a `_reindex_chroma()` method that reads all procedures from SQLite and upserts into the fresh collection.

### 7. `src/probos/__main__.py` (~lines 280-296)

**Change — Pass config to EpisodicMemory:**

Add `query_reformulation_enabled` from `MemoryConfig` to `EpisodicMemory` constructor:

```python
EpisodicMemory(
    db_path=str(episodic_db),
    max_episodes=...,
    relevance_threshold=...,
    verify_content_hash=...,
    eviction_audit=...,
    agent_recall_threshold=...,
    fts_keyword_floor=...,
    query_reformulation_enabled=config.memory.query_reformulation_enabled,  # NEW
)
```

### 8. `src/probos/startup/cognitive_services.py` (~lines 174-207)

**Change — Add embedding model migration step:**

After existing migrations (BF-103, AD-570, AD-570b), add AD-584 embedding model migration:

```python
# AD-584: Embedding model migration
from probos.knowledge.embeddings import get_embedding_model_name
await episodic.migrate_embedding_model(get_embedding_model_name())
```

The migration method on EpisodicMemory handles the detection and re-embedding internally.

---

## Test Plan — `tests/test_ad584_recall_qa_fix.py`

**~30 tests across 4 groups:**

### Group 1: Embedding Model (6 tests)
1. `test_get_embedding_function_returns_callable` — embedding function is not None
2. `test_get_embedding_model_name_returns_string` — model name matches config
3. `test_embedding_produces_384_dimensions` — verify dimension compatibility
4. `test_embedding_qa_similarity_above_threshold` — embed a Q→A pair ("What was the threshold?" / "The threshold was set to 0.7"), verify cosine similarity > 0.4 (this is the core regression test)
5. `test_embedding_statement_similarity_preserved` — embed two similar statements, verify cosine similarity > 0.5 (no regression on statement→statement)
6. `test_keyword_fallback_still_works` — when embedding function fails, keyword overlap fallback activates

### Group 2: Query Reformulation (10 tests)
7. `test_reformulate_what_is` — "What is X?" → ["What is X", "X is"]
8. `test_reformulate_what_was` — "What was X?" → ["What was X", "X was"]
9. `test_reformulate_how_does` — "How does X work?" → ["How does X work", "X works by"]
10. `test_reformulate_who_did` — "Who did X?" → ["Who did X", "X"]
11. `test_reformulate_when_did` — "When did X happen?" → ["When did X happen", "X happened"]
12. `test_reformulate_why_did` — "Why did X fail?" → ["Why did X fail", "X failed because"]
13. `test_reformulate_how_many` — "How many X?" → ["How many X", "the number of X is"]
14. `test_reformulate_yes_no` — "Did X happen?" → ["Did X happen", "X happened"]
15. `test_reformulate_non_question` — "The threshold was 0.7" → ["The threshold was 0.7"] (passthrough)
16. `test_reformulate_strips_question_mark` — trailing ? removed from all variants

### Group 3: Recall Pipeline Integration (10 tests)
17. `test_recall_for_agent_scored_uses_reformulation` — store a fact, query with a question, verify the fact is returned (end-to-end with real embedding)
18. `test_recall_for_agent_scored_without_reformulation` — same test with `query_reformulation_enabled=False`, verify fact still returns (but possibly lower score)
19. `test_recall_weighted_uses_reformulation` — same end-to-end through `recall_weighted()` 
20. `test_dual_query_dedup` — when original and reformulated both match the same episode, it appears once (not duplicated)
21. `test_dual_query_takes_best_score` — episode matched by reformulated query gets the better (lower distance) score
22. `test_bf029_prefix_removed` — `_recall_relevant_memories()` for `direct_message` intent does NOT prepend "Ward Room {callsign}" to query
23. `test_query_still_works_for_ward_room_recall` — store a Ward Room episode (`[Ward Room reply] Counselor: ...`), ask about it without prefix, verify it's recalled
24. `test_non_dm_intent_unaffected` — `ward_room_notification` and other intents still construct queries correctly (no regression)
25. `test_basic_tier_recalls_with_new_model` — Ensign-rank agent (BASIC tier, k=3) can recall a seeded Q→A pair
26. `test_classify_retrieval_strategy_unaffected` — `classify_retrieval_strategy()` returns same results (no regression)

### Group 4: Migration (4 tests)
27. `test_migration_detects_model_mismatch` — create collection with old model metadata, verify migration triggers
28. `test_migration_preserves_episode_count` — after migration, same number of episodes exist
29. `test_migration_updates_metadata` — after migration, collection metadata has new model name  
30. `test_migration_skips_when_model_matches` — when model already matches, no re-embedding occurs

---

## Existing Test Updates

### `tests/test_cognitive_agent.py`

**2 tests need updating (BF-029 prefix assertions):**

1. `TestRecallQueryEnrichment.test_recall_query_includes_ward_room_and_callsign` (~line 930-948):
   - Currently asserts `query.startswith("Ward Room Counselor")`
   - Change to assert query equals the captain's text (stripped, truncated)
   - Update test name to `test_recall_query_uses_captain_text_directly`

2. `TestRecallQueryEnrichment.test_recall_query_works_without_callsign_registry` (~line 950-968):
   - Currently asserts `query.startswith("Ward Room")`  
   - Change to assert query equals the captain's text (no prefix)
   - Update test name to reflect new behavior

**Tests that should pass without changes (verify):**
- `TestMemoryPresentationPreference` tests (input-over-reflection preference — BF-029 Issue B — unchanged)
- `TestEndToEndWardRoomRecall` tests (Ward Room episode format unchanged, only query changes)
- Fallback behavior tests

### `tests/test_ad567b_anchor_recall.py`

- `score_recall()` weight tests should pass unchanged (weights not modified in this AD)
- `recall_weighted()` integration tests should pass (reformulation adds query variants but same scoring pipeline)

### `tests/test_memory_probes.py` or `tests/test_memory_architecture.py`

- Memory probe test infrastructure (`_ward_room_content()` wrapper) — may need to be checked but should work: episodes are still stored with `[Ward Room]` prefix, only the query side changes

---

## Engineering Principles Compliance

| Principle | How Satisfied |
|-----------|---------------|
| **SRP** | `reformulate_query()` is a pure function in `embeddings.py` (embedding strategy). Migration logic stays in each consumer's module. No god functions. |
| **OCP** | `reformulate_query()` returns a list — callers use it generically. New patterns can be added without changing callers. |
| **LSP** | Embedding function contract unchanged — still returns `list[list[float]]` of 384 dimensions. |
| **ISP** | `get_embedding_model_name()` is a narrow interface for migration detection. |
| **DIP** | EpisodicMemory depends on `get_embedding_function()` abstraction, not on a specific model class. Model name is config-driven. |
| **Law of Demeter** | Migration uses collection's public `.get()`, `.add()`, `.modify()` APIs. No private attribute access. |
| **DRY** | Migration pattern follows established BF-103/AD-570 approach. `reformulate_query()` is one function called from multiple recall paths. |
| **Fail Fast** | If embedding function creation fails → keyword fallback (existing). If migration fails → log error, continue with stale embeddings (degraded, not crashed). |
| **Defense in Depth** | Model name stored in collection metadata AND config — double-source for migration detection. Original query always included alongside reformulated (never lose the original signal). |
| **Cloud-Ready** | No new SQLite. ChromaDB migration uses collection public APIs. No hardcoded paths. |

---

## Prior Work Absorbed

| Prior Work | What We Absorb | How |
|------------|----------------|-----|
| BF-029 (Ward Room Recall Quality) | Understanding that prefix was a workaround, not a solution. Remove prefix, keep episode storage format. | Remove query prefix at `cognitive_agent.py:2480` |
| BF-133 (Probe Anchor Gate Fix) | Test episodes need realistic framing. Probes go through full `handle_intent()` pipeline. | Tests use realistic episode format |
| BF-134 (Threshold + FTS Fix) | `agent_recall_threshold=0.15` and `fts_keyword_floor=0.2` remain. Migration guard pattern reused. | No threshold changes in this AD |
| AD-567b (Salience-Weighted Recall) | `score_recall()` composite formula, `recall_weighted()` API — these are the integration points. | Reformulation feeds into existing scoring unchanged |
| AD-567d (Activation Tracker) | Activation recording in recall methods must be preserved during reformulation changes. | Don't remove activation tracking at recall sites |
| AD-570 (Anchor Metadata Promotion) | Migration pattern: batch upsert, startup sequencing in `cognitive_services.py`. | Follow same pattern for model migration |
| AD-462c (Variable Recall Tiers) | BASIC tier (k=3, no salience) used by Ensign agents in probes. Must work with new model. | Test includes BASIC tier verification |
| AD-568a (Source Governance) | `classify_retrieval_strategy()` determines NONE/SHALLOW/DEEP. Reformulation happens after strategy but before ChromaDB query. | Reformulation in recall methods, not in intent handler |
| AD-582 (Memory Probes) | SeededRecallProbe is the primary measurement instrument. Goes through `handle_intent()` → full pipeline. | Probes are acceptance criteria, not just tests |
| Cognitive science research | Graesser & Black (1985) expected-answer templates. Template reformulation = pseudo-HyDE at zero cost. | `reformulate_query()` implements template patterns |

---

## What This AD Does NOT Do (Explicit Scope Boundaries)

1. **Does NOT change composite scoring weights** — that's AD-584c (separate prompt)
2. **Does NOT embed reflection alongside user_input** — that's AD-584d (separate prompt)
3. **Does NOT add convergence bonus to scoring** — that's AD-584c
4. **Does NOT add LLM calls to the recall path** — template reformulation is regex only
5. **Does NOT change FTS5 keyword search** — keyword pipeline unchanged
6. **Does NOT modify Ward Room episode storage format** — `[Ward Room]`/`[Ward Room reply]` prefixes stay on stored content
7. **Does NOT require `sentence-transformers` if ONNX model is available** — attempt ONNX first, fall back to sentence-transformers, fall back to keyword

---

## Verification

1. Run new tests: `pytest tests/test_ad584_recall_qa_fix.py -v`
2. Run updated BF-029 tests: `pytest tests/test_cognitive_agent.py -k "RecallQueryEnrichment" -v`
3. Run AD-567b recall tests: `pytest tests/test_ad567b_anchor_recall.py -v` (no regression)
4. Run AD-567c anchor quality tests: `pytest tests/test_ad567c_anchor_quality.py -v` (no regression)
5. Run memory probe tests: `pytest tests/ -k "probe" -v` (probes are the acceptance criteria)
6. Run selective encoding tests: `pytest tests/test_selective_encoding.py -v` (no regression)
7. Full suite: `pytest tests/ --timeout=30 -x` (no regressions)

---

## Expected Impact

| Probe | Before | After AD-584a+b | Measurement |
|-------|--------|-----------------|-------------|
| SeededRecallProbe | 0.000–0.149 | 0.500–0.800 | Q→A cosine jumps with multi-qa model |
| TemporalReasoningProbe | 0.000–0.012 | 0.200–0.500 | Better semantic match for temporal queries |
| KnowledgeUpdateProbe | 0.000–0.500 | 0.400–0.800 | Fact updates better matched |
| RetrievalAccuracyBenchmark | 0.300–0.550 | 0.350–0.600 | Already passes; slight improvement |

## Dependency Note

The builder should verify the ONNX availability of `multi-qa-MiniLM-L6-cos-v1` before choosing the embedding function wrapper. Check:
1. Does `chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction("multi-qa-MiniLM-L6-cos-v1")` work out of the box?
2. If not, is there an ONNX model file on HuggingFace for this model?
3. Fallback: use `sentence-transformers` library with `SentenceTransformer("multi-qa-MiniLM-L6-cos-v1")`
4. Last resort: use `onnxruntime` directly with downloaded ONNX weights

The model MUST be downloadable at first run (no pre-bundling). Cache in ChromaDB's default model cache directory.
