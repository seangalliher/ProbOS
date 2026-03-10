# Phase 14b — ChromaDB Semantic Recall

## Phase Goal

Replace keyword-overlap bag-of-words similarity with real embedding-based semantic search across four subsystems: EpisodicMemory, WorkflowCache, CapabilityRegistry, and StrategyRecommender. ChromaDB runs embedded (no external server). "Find past tasks about deployment" matches "push to production." The system understands meaning, not just words.

---

## Architecture

Two components:

1. **Shared embedding utility** — wraps ChromaDB's default embedding function (ONNX MiniLM, ships with ChromaDB, no torch dependency). All four subsystems use this for similarity computation.

2. **ChromaDB-backed EpisodicMemory** — replaces the SQLite store with a ChromaDB collection. Episodes are stored as documents with metadata. Recall uses ChromaDB's similarity search. The other three subsystems (WorkflowCache, CapabilityRegistry, StrategyRecommender) do NOT need their own ChromaDB collections — they have small in-memory datasets and just need the embedding function for computing similarity scores.

**KnowledgeStore interaction:** KnowledgeStore (Phase 14) continues to persist episodes as JSON files in Git for durable versioned history. The two-tier pattern: ChromaDB is the hot-path retrieval engine, Git is long-term persistence. On warm boot, `seed()` loads episodes from Git into ChromaDB. On shutdown, nothing changes — KnowledgeStore already persists episodes on store.

**Mock stays unchanged:** `MockEpisodicMemory` keeps its current keyword-overlap implementation. Tests stay deterministic and fast with no ChromaDB dependency. Same pattern as MockLLMClient.

---

## Deliverables (build in this order)

### 1. Dependency + shared embedding utility

**File:** `pyproject.toml`
- Add `chromadb` to dependencies.

**File:** `src/probos/cognitive/embeddings.py` (NEW)
- `get_embedding_function()` — returns ChromaDB's default ONNX embedding function. Lazy-initialized singleton so the model loads once on first use.
- `compute_similarity(text_a: str, text_b: str) -> float` — convenience function: embeds both texts, returns cosine similarity (0.0–1.0). This is what WorkflowCache, CapabilityRegistry, and StrategyRecommender will use.
- `embed_text(text: str) -> list[float]` — convenience function: returns the embedding vector for a single text. Useful for callers that need raw vectors.
- Graceful fallback: if ChromaDB's embedding function fails to initialize (missing ONNX runtime, etc.), fall back to the existing keyword-overlap `_keyword_embedding()` from `episodic.py` with a logged warning. The system degrades to current behavior, never crashes.

### 2. EpisodicMemory ChromaDB upgrade

**File:** `src/probos/cognitive/episodic.py`
- Replace the SQLite-backed implementation with ChromaDB.
- `__init__()`: create a ChromaDB persistent client (stored in `data_dir` alongside current SQLite path) and a collection named `"episodes"`.
- `store()`: add the episode to the ChromaDB collection. Document text = episode's `input_text`. Metadata = `intent_type`, `outcome`, `timestamp`, `agent_ids`, `episode_id`. Use `episode_id` as the ChromaDB document ID for deduplication.
- `recall_similar(text, limit)`: ChromaDB `collection.query(query_texts=[text], n_results=limit)` — returns episodes ranked by semantic similarity. No more keyword-overlap cosine.
- `recall_by_intent(intent_type, limit)`: ChromaDB `collection.query()` with `where={"intent_type": intent_type}` metadata filter.
- `recent(limit)`: ChromaDB `collection.get()` sorted by timestamp metadata descending, limited.
- `get_stats()`: ChromaDB `collection.count()` plus metadata aggregation.
- `seed(episodes)`: bulk `collection.add()` — the warm boot path. Use `episode_id` as document ID so duplicates are skipped (same semantics as current INSERT OR IGNORE).
- `max_episodes` eviction: after `store()`, if `collection.count() > max_episodes`, query oldest by timestamp metadata and delete.
- Remove all SQLite imports and the `_keyword_embedding()` / `_cosine_similarity()` helper functions. These move to `embeddings.py` as the fallback.
- The class interface (`store`, `recall_similar`, `recall_by_intent`, `recent`, `get_stats`, `seed`) stays identical. Callers (runtime, decomposer, dreaming engine, KnowledgeStore) change nothing.

**File:** `src/probos/cognitive/episodic_mock.py`
- **Do NOT change.** MockEpisodicMemory stays as-is with keyword matching for tests.

### 3. WorkflowCache semantic fuzzy matching

**File:** `src/probos/cognitive/workflow_cache.py`
- Replace `_keyword_overlap()` in fuzzy lookup with `compute_similarity()` from `embeddings.py`.
- Fuzzy lookup: embed the input text, compare against stored workflow input texts using `compute_similarity()`, return the best match above a configurable similarity threshold (default 0.6).
- Pre-warm intent intersection check stays (it's a set operation, not a similarity computation).
- Exact lookup stays unchanged (normalized string equality).

### 4. CapabilityRegistry semantic matching

**File:** `src/probos/mesh/capability.py`
- Add an optional semantic matching tier to the existing matching pipeline.
- Current pipeline: exact match → substring match → keyword match → scored results.
- New pipeline: exact match → substring match → semantic match → scored results.
- Semantic match: use `compute_similarity()` from `embeddings.py` to compare the query against each capability descriptor. Return descriptors above a configurable threshold (default 0.5).
- Keyword match stays as a fallback if `compute_similarity` is unavailable (graceful degradation).

### 5. StrategyRecommender semantic matching

**File:** `src/probos/cognitive/strategy.py`
- Replace keyword-overlap scoring between the unhandled intent and existing intent descriptors with `compute_similarity()` from `embeddings.py`.
- The similarity score feeds into the existing confidence calculation (higher similarity = higher confidence that `add_skill` will work on an existing agent).
- Fallback to current keyword overlap if embeddings unavailable.

### 6. Runtime + config wiring

**File:** `src/probos/__main__.py`
- Remove `EpisodicMemory` SQLite temp dir creation. ChromaDB manages its own persistence in `data_dir`.
- Pass `data_dir` to the new `EpisodicMemory` constructor.

**File:** `src/probos/config.py`
- Add `similarity_threshold: float = 0.6` to `MemoryConfig` — used by EpisodicMemory recall and WorkflowCache fuzzy lookup.
- Add `semantic_matching: bool = True` to `MeshConfig` — feature flag for CapabilityRegistry semantic matching.

**File:** `config/system.yaml`
- Add `similarity_threshold` to the `memory:` section (commented, with default).
- Add `semantic_matching` to the `mesh:` section (commented, with default).

**File:** `src/probos/runtime.py`
- Pass updated config to components. No structural changes — the interfaces are unchanged.

### 7. Update PROGRESS.md

---

## Required Tests

### Embedding utility tests (in `tests/test_embeddings.py`, NEW)
- `get_embedding_function()` returns a callable (1 test)
- `embed_text()` returns non-empty list of floats (1 test)
- `compute_similarity()` identical text ≈ 1.0 (1 test)
- `compute_similarity()` different text < 0.8 (1 test)
- `compute_similarity()` semantically similar text > semantically different text (1 test) — e.g., "deploy the API" vs "push to production" scores higher than "deploy the API" vs "bake a cake"
- `compute_similarity()` empty text returns 0.0 (1 test)
- Fallback to keyword overlap when embedding function unavailable (1 test)

### EpisodicMemory ChromaDB tests (in `tests/test_episodic_chromadb.py`, NEW)
- Store and recall single episode via semantic similarity (1 test)
- Store multiple, recall returns semantically ranked results (1 test)
- Semantic recall: "deployment" query matches "push to production" episode (1 test) — the key semantic test
- recall_by_intent filters correctly with metadata (1 test)
- recent() returns most recent first by timestamp (1 test)
- get_stats returns correct counts (1 test)
- max_episodes eviction removes oldest (1 test)
- seed() bulk loads episodes (for warm boot) (1 test)
- seed() skips duplicate IDs (1 test)
- Episode round-trip: all fields survive store → recall (1 test)
- Empty collection returns empty results (1 test)

### Existing EpisodicMemory tests
- The 7 MockEpisodicMemory tests must still pass unchanged.
- The 4 Keyword Embedding tests should be updated to test the new `embeddings.py` utility instead. If the old `_keyword_embedding` function is removed from `episodic.py`, move these tests to `test_embeddings.py`.
- The 5 EpisodicMemory SQLite tests should be replaced by the 11 new ChromaDB tests above (they test the same interface, different backend).

### WorkflowCache tests
- Existing 22 tests must still pass. The fuzzy lookup test should now use semantic similarity instead of keyword overlap.
- New: fuzzy lookup matches "deploy API" to cached "push app to production" (1 test) — semantic match that keyword overlap would miss.

### CapabilityRegistry tests
- Existing 8 tests must still pass.
- New: semantic match finds "read a document" when searching for "open file" (1 test) — semantic match that substring/keyword would miss.
- New: semantic matching can be disabled via config flag (1 test).

### StrategyRecommender tests
- Existing tests must still pass.
- New: semantic similarity produces higher confidence for semantically similar intents than dissimilar ones (1 test).

### Integration tests
- Runtime integration tests must still pass.
- Episodic memory integration tests must still pass (runtime stores episodes, recall_similar works).
- KnowledgeStore episode persistence still works: store episode → persist to Git → seed back from Git → recall via ChromaDB (1 test).
- Warm boot integration: fresh ChromaDB + seed from KnowledgeStore produces searchable episodes (1 test).

---

## Milestone End-to-End Test

A runtime starts with an empty ChromaDB store. The participant says "read the project config file." The system decomposes, executes, stores an episode. Then the participant says "show me what I did with settings." The `recall_similar()` call matches "settings" to the episode about "config file" via semantic similarity — a match that keyword overlap would have missed because the words don't overlap. The recall returns the episode. The decomposer uses it as episodic context.

This demonstrates: ChromaDB storage, semantic recall, decomposer integration, and the meaning-based matching that is the whole point of this phase.

---

## Do NOT Build

- **Do NOT build the Semantic Knowledge Layer.** That is a separate future phase. This phase upgrades the four subsystems that currently use keyword overlap. The unified search-across-all-knowledge-types orchestrator is out of scope.
- **Do NOT change MockEpisodicMemory.** Tests use it for deterministic, fast execution with no ChromaDB dependency. Same pattern as MockLLMClient.
- **Do NOT add new slash commands.** The existing `/history`, `/recall`, `/cache` commands work through the same interfaces — they get semantic search for free.
- **Do NOT change the Experience Layer (panels, renderer, shell).** The upgrade is invisible to the rendering surface — same data, better retrieval.
- **Do NOT change the DreamingEngine or DreamScheduler.** They call `recall_similar()` and `store()` on EpisodicMemory — the interface is unchanged, they get semantic recall for free.
- **Do NOT change KnowledgeStore.** It persists Episode dicts to Git JSON files. The Episode type and serialization format are unchanged. KnowledgeStore doesn't know or care that the hot-path store switched from SQLite to ChromaDB.
- **Do NOT require an external server or API for embeddings.** ChromaDB's built-in ONNX embedding function runs locally with no server process. If it requires a dependency heavier than what `uv add chromadb` provides, document it but prefer the lightest path that works.
- **Do NOT change the AttentionManager.** Its `_compute_relevance()` keyword overlap over recent focus snapshots is a different concern (temporal relevance weighting, not semantic recall). It stays as-is.

---

## Build Order

1. `embeddings.py` (shared utility — everything depends on this)
2. `episodic.py` (ChromaDB upgrade — the core change)
3. `test_embeddings.py` + `test_episodic_chromadb.py` (validate the core)
4. `workflow_cache.py` (semantic fuzzy matching)
5. `capability.py` (semantic capability matching)
6. `strategy.py` (semantic strategy scoring)
7. Config + runtime wiring
8. Update/verify all existing tests
9. Integration tests (KnowledgeStore + warm boot)
10. Update PROGRESS.md

---

## Key Design Constraint

The `EpisodicMemory` class interface stays identical: `store()`, `recall_similar()`, `recall_by_intent()`, `recent()`, `get_stats()`, `seed()`. Every caller — runtime, decomposer, dreaming engine, KnowledgeStore — continues calling the same methods with the same signatures. The upgrade is a backend swap, not an API change. `MockEpisodicMemory` implements the same interface with keyword matching for tests.
