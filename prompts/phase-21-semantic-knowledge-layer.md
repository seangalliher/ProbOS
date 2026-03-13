# Phase 21 — Semantic Knowledge Layer

## Context

You are building Phase 21 of ProbOS, a probabilistic agent-native OS runtime. Read `PROGRESS.md` for full architectural context. Current state: **1409/1409 tests passing + 11 skipped. Latest AD: AD-240.**

ProbOS has 7 knowledge types scattered across separate stores:
1. **Episodes** — ChromaDB collection (semantic search, recall by intent)
2. **Designed agents** — KnowledgeStore .py + .json (file system, no search)
3. **Skills** — KnowledgeStore .py + .json (file system, no search)
4. **Trust snapshots** — KnowledgeStore single JSON (file system)
5. **Routing weights** — KnowledgeStore single JSON (file system)
6. **Workflow cache** — KnowledgeStore single JSON (file system)
7. **QA reports** — KnowledgeStore per-agent JSON (file system)

Each is searchable only through its own API. There is no way to ask "what agents have I built for text processing?" or "show me tasks that failed due to missing permissions" across all knowledge types at once.

This phase adds a **Semantic Knowledge Layer** — a thin query orchestrator over ChromaDB collections that enables unified cross-type semantic search. Each knowledge type gets its own ChromaDB collection with typed metadata. The layer fans out queries and merges results by relevance.

### Phase 20 cleanup (AD-241)

Two minor issues from Phase 20 need fixing first:
1. `EmergentDetector._extract_pool()` is fragile — uses `parts[-3]` heuristic that breaks for compound pool names (`filesystem_writers`, `red_team`)
2. `EmergentDetector._all_patterns` list grows unbounded (no eviction)

---

## Pre-Build Audit

Before writing any code, verify:

1. **Latest AD number in PROGRESS.md** — confirm AD-240 is the latest. Phase 21 AD numbers start at **AD-241**. If AD-240 is NOT the latest, adjust all AD numbers in this prompt upward accordingly.
2. **Test count** — confirm 1409 tests pass before starting: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
3. **Read these files thoroughly:**
   - `src/probos/knowledge/store.py` — understand `KnowledgeStore` API: `store_episode()`, `load_episodes()`, `store_agent()`, `load_agents()`, `store_skill()`, `load_skills()`, `store_trust_snapshot()`, `store_routing_weights()`, `store_workflows()`, `store_qa_report()`, `load_qa_reports()`, `artifact_counts()`. The Semantic Knowledge Layer indexes artifacts on write
   - `src/probos/cognitive/episodic.py` — understand `EpisodicMemory`: ChromaDB PersistentClient, `_collection`, `store()`, `recall()`, `recall_by_intent()`, `recent()`, `seed()`, `_episode_to_metadata()`, `_metadata_to_episode()`. Episodes already have a ChromaDB collection — the knowledge layer does NOT replace this, it indexes other knowledge types in parallel collections
   - `src/probos/cognitive/embeddings.py` — understand `get_embedding_function()` (lazy singleton ONNX MiniLM), `embed_text()`, `compute_similarity()`. The knowledge layer uses the same embedding function for all its collections
   - `src/probos/substrate/identity.py` — understand `generate_agent_id()` format: `{agent_type}_{pool_name}_{index}_{hash8}`. The `_extract_pool()` fix needs this
   - `src/probos/cognitive/emergent_detector.py` — understand `_extract_pool()` (the fragile method to fix), `_all_patterns` (the unbounded list to cap)
   - `src/probos/runtime.py` — understand where `knowledge_store.store_*()` calls happen — these are the hook points for auto-indexing. Also understand the warm boot path `_restore_from_knowledge()`
   - `src/probos/agents/introspect.py` — understand `IntrospectionAgent` pattern: `intent_descriptors`, `_handled_intents`, handler dispatch
   - `src/probos/experience/shell.py` — understand command registration pattern
   - `src/probos/experience/panels.py` — understand rendering pattern
   - `src/probos/cognitive/llm_client.py` — understand `MockLLMClient` regex patterns
   - `src/probos/types.py` — understand `Episode`, `Skill`, `IntentDescriptor`

---

## What To Build

### Step 1: Phase 20 Cleanup (AD-241)

**Files:** `src/probos/cognitive/emergent_detector.py`, `src/probos/substrate/identity.py`, `src/probos/cognitive/decomposer.py`

**AD-241: Fix `_extract_pool()` fragility, cap `_all_patterns` growth, and fix reflect prompt for structured data.**

**Part 1 — Pool extraction fix:**

The problem: `generate_agent_id()` produces IDs like `file_reader_filesystem_0_abc12345` or `file_writer_filesystem_writers_0_def67890`. The format is `{type}_{pool}_{index}_{hash8}`. Both `type` and `pool` can contain underscores, making naive splitting ambiguous.

The fix: **add a `parse_agent_id()` function to `identity.py`** that reverses the generation:

```python
def parse_agent_id(agent_id: str) -> dict[str, str] | None:
    """Parse a deterministic agent ID back into its components.

    Returns {"agent_type": ..., "pool_name": ..., "index": ..., "hash": ...}
    or None if the ID doesn't match the deterministic format.

    Strategy: the ID was generated as f"{type}_{pool}_{index}_{hash8}".
    The hash is always exactly 8 hex chars. The index is always a non-negative
    integer. We parse from the RIGHT side (hash and index are unambiguous),
    then need to split the remainder into type and pool.

    Since we can't distinguish type from pool by syntax alone (both can
    contain underscores), we store a mapping during generation and consult
    it during parsing. As a fallback, we return the full prefix before the
    index as "agent_type" and empty string as "pool_name".
    """
```

**Simplest reliable approach:** Since `generate_agent_id()` and `generate_pool_ids()` are the only producers of deterministic IDs, maintain a module-level registry `_ID_REGISTRY: dict[str, dict]` that `generate_agent_id()` populates on each call: `_ID_REGISTRY[id] = {"agent_type": type, "pool_name": pool, "index": index}`. Then `parse_agent_id()` looks up the ID and returns the stored components. For IDs not in the registry (e.g., restored from persistence), fall back to right-to-left parsing: the last segment is the 8-char hash, the second-to-last is the integer index, and the rest is `{type}_{pool}` which we return as `prefix`.

Then update `EmergentDetector._extract_pool()` to use `parse_agent_id()`:

```python
@staticmethod
def _extract_pool(agent_id: str) -> str:
    from probos.substrate.identity import parse_agent_id
    parsed = parse_agent_id(agent_id)
    if parsed and parsed.get("pool_name"):
        return parsed["pool_name"]
    # Fallback: return the prefix segments minus last two (index_hash)
    parts = agent_id.split("_")
    if len(parts) >= 4:
        return "_".join(parts[:-2])  # everything except index and hash
    return ""
```

**Part 2 — Cap `_all_patterns`:**

Add eviction to `analyze()`:

```python
self._all_patterns.extend(patterns)
# Cap pattern history
if len(self._all_patterns) > 500:
    self._all_patterns = self._all_patterns[-500:]
```

**Part 3 — Reflect prompt structured data extraction fix:**

**File:** `src/probos/cognitive/decomposer.py`

The `REFLECT_PROMPT` currently tells the LLM to "synthesize a clear, concise response" but gives no guidance on parsing structured data (XML, JSON, HTML) from agent results. When `http_fetch` returns an RSS feed (12KB of XML), the LLM describes the fetch result instead of extracting `<title>` elements to answer the user's question. This was observed in production: "what is the latest headline news from the New York Times" → fetched RSS XML successfully → reflect said "the feed was successfully retrieved, you can use an RSS reader" instead of presenting headlines.

Add a new rule to `REFLECT_PROMPT`, after rule 5:

```
6. If results contain structured data (XML, JSON, HTML, CSV), extract and present \
the relevant content to answer the user's question. Do NOT describe the format or \
suggest the user access it themselves — parse the data and give the answer directly.
```

The updated `REFLECT_PROMPT` should read:

```python
REFLECT_PROMPT = """\
You are analyzing results returned by ProbOS agents in response to a user request.
You will receive the user's original request and the results from each agent operation.
Synthesize a clear, concise response that directly answers the user's question.

CRITICAL RULES:
1. If a result shows success=True and output=<data>, the operation SUCCEEDED. \
USE that output data to answer the user. NEVER say the operation failed.
2. If the output is a date/time and the user asked about a different timezone, \
calculate the conversion yourself (e.g. UTC+9 for Tokyo, UTC-7 for Denver, etc.).
3. Focus on answering what the user asked \u2014 do not describe the operations \
that were performed.
4. Each result line starts with [completed] or [failed] \u2014 trust that status.
5. Even partial or imperfect data is better than saying you couldn\u2019t retrieve it.
6. If results contain structured data (XML, JSON, HTML, CSV), extract and present \
the relevant content to answer the user's question. Do NOT describe the format or \
suggest the user access it themselves \u2014 parse the data and give the answer directly.

Respond with plain text only. No JSON. No markdown code fences.
"""
```

**Run tests after this step: all 1409 existing tests must still pass.**

---

### Step 2: SemanticKnowledgeLayer Core Module (AD-242)

**File:** `src/probos/knowledge/semantic.py` (new)

**AD-242: `SemanticKnowledgeLayer` — unified semantic search across all knowledge types.** A thin orchestrator over ChromaDB collections that enables cross-type queries.

**Architecture:**

```
User query ──→ SemanticKnowledgeLayer.search()
                  ├─→ collection "sk_agents"     → agent matches
                  ├─→ collection "sk_skills"      → skill matches
                  ├─→ collection "sk_workflows"   → workflow matches
                  ├─→ collection "sk_qa_reports"  → QA matches
                  └─→ collection "sk_events"      → system event matches
                  ↓
              Merge by score, return ranked results
```

Note: **Episodes already have their own ChromaDB collection** managed by `EpisodicMemory`. The knowledge layer does NOT create a duplicate episode collection. Instead, `search()` also queries `EpisodicMemory.recall()` to include episodes in cross-type results.

**Core class:**

```python
class SemanticKnowledgeLayer:
    """Unified semantic search across all ProbOS knowledge types.

    Manages ChromaDB collections for non-episode knowledge (agents, skills,
    workflows, QA reports, system events). Episodes are queried via the
    existing EpisodicMemory.

    Each collection stores documents with typed metadata enabling
    both semantic search and structured filtering.
    """

    # Collection names (prefixed to avoid collision with episodic "episodes")
    COLLECTIONS = {
        "agents": "sk_agents",
        "skills": "sk_skills",
        "workflows": "sk_workflows",
        "qa_reports": "sk_qa_reports",
        "events": "sk_events",
    }
```

**Constructor:**
```python
def __init__(
    self,
    db_path: str | Path,
    episodic_memory: Any = None,
) -> None:
```

Takes a db_path for the ChromaDB PersistentClient (can share the same directory as EpisodicMemory — ChromaDB supports multiple collections per client). Accepts optional `episodic_memory` reference for cross-type episode queries.

**Lifecycle:**
```python
async def start(self) -> None:
    """Initialize ChromaDB client and create/get all collections."""
    import chromadb
    from probos.cognitive.embeddings import get_embedding_function

    self._client = chromadb.PersistentClient(path=str(self._db_path))
    ef = get_embedding_function()
    for name, collection_name in self.COLLECTIONS.items():
        self._collections[name] = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

async def stop(self) -> None:
    """Close ChromaDB client."""
```

**Indexing methods — one per knowledge type:**

All metadata dicts include an optional `source_node: str = ""` field (empty string for local). This field is not populated in Phase 21 but reserves the schema slot for future federation sync — when a peer node's knowledge arrives via Git pull, `source_node` will carry the originating `node_id`, enabling cross-node provenance in search results.

```python
async def index_agent(self, agent_type: str, intent_name: str,
                       description: str, strategy: str,
                       source_snippet: str = "",
                       source_node: str = "") -> None:
    """Index a designed agent for semantic search.

    Document: "{agent_type}: {intent_name} — {description}"
    Metadata: type="agent", agent_type, intent_name, strategy, source_node, indexed_at
    """

async def index_skill(self, intent_name: str, description: str,
                       target_agent: str = "",
                       source_node: str = "") -> None:
    """Index a skill for semantic search.

    Document: "Skill {intent_name}: {description}"
    Metadata: type="skill", intent_name, target_agent, source_node, indexed_at
    """

async def index_workflow(self, pattern: str, intent_names: list[str],
                          hit_count: int = 0,
                          source_node: str = "") -> None:
    """Index a workflow cache entry for semantic search.

    Document: "{pattern} → {', '.join(intent_names)}"
    Metadata: type="workflow", pattern, intent_count, hit_count, source_node, indexed_at
    """

async def index_qa_report(self, agent_type: str, verdict: str,
                            pass_rate: float,
                            source_node: str = "") -> None:
    """Index a QA report for semantic search.

    Document: "QA for {agent_type}: {verdict} ({pass_rate:.0%} pass rate)"
    Metadata: type="qa_report", agent_type, verdict, pass_rate, source_node, indexed_at
    """

async def index_event(self, category: str, event: str, detail: str,
                       source_node: str = "") -> None:
    """Index a system event for semantic search.

    Document: "[{category}] {event}: {detail}"
    Metadata: type="event", category, event, source_node, indexed_at
    """
```

Each indexing method uses `collection.upsert()` with a deterministic ID (e.g., `f"agent_{agent_type}"` for agents) so re-indexing is idempotent.

**Search method:**

```python
async def search(
    self,
    query: str,
    types: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Semantic search across knowledge types.

    Args:
        query: Natural language search query
        types: Filter to specific types (e.g., ["agents", "skills"]).
               None = search all types including episodes.
        limit: Maximum results to return

    Returns:
        List of result dicts, sorted by relevance:
        [{"type": "agent", "id": ..., "document": ..., "score": ..., "metadata": ...}, ...]
    """
```

Implementation:
1. If `types` is None, search all collections + episodic memory
2. For each collection, call `collection.query(query_texts=[query], n_results=limit)`
3. Convert ChromaDB distance to score: `score = 1.0 - distance`
4. If episodic memory is available and ("episodes" in types or types is None):
   - Call `episodic_memory.recall(query, k=limit)` 
   - Convert episodes to result dicts with `type="episode"`
5. Merge all results, sort by score descending, return top `limit`

**Stats method:**

```python
def stats(self) -> dict:
    """Return per-collection document counts."""
    return {name: col.count() for name, col in self._collections.items()}
```

**Bulk re-index method (for warm boot):**

```python
async def reindex_from_store(self, knowledge_store: Any) -> dict[str, int]:
    """Re-index all knowledge from KnowledgeStore.

    Called during warm boot after KnowledgeStore is loaded.
    Returns {type: count_indexed} for each type.
    """
```

This loads agents/skills/workflows/QA from KnowledgeStore and calls the appropriate `index_*` method for each. Episodes are handled separately by EpisodicMemory's `seed()` — the knowledge layer does NOT re-index episodes.

**Run tests after this step: all 1409 existing tests must still pass (new file, no existing code changes).**

---

### Step 3: Wire into Runtime (AD-243)

**File:** `src/probos/runtime.py`

**AD-243: SemanticKnowledgeLayer runtime integration.** Wire the layer into the runtime lifecycle.

1. **Construction and start:** Create `SemanticKnowledgeLayer` in `start()` after episodic memory is initialized. Pass the same `db_path` parent directory as episodic memory. Pass `episodic_memory` reference.

2. **Auto-indexing hooks:** After each `knowledge_store.store_*()` call in the runtime, add a corresponding `_semantic_layer.index_*()` call:
   - After `store_agent()` → `index_agent()` with record metadata
   - After `store_skill()` → `index_skill()` with intent name and descriptor
   - After `store_qa_report()` → `index_qa_report()` with report data
   - After workflow cache storage in `stop()` → `index_workflow()` for each entry

   **Important:** Wrap each indexing call in try/except — indexing failures must never block or crash the main operation. These are fire-and-forget enrichments.

3. **Warm boot re-indexing:** In `_restore_from_knowledge()`, after all knowledge is loaded, call `_semantic_layer.reindex_from_store(self._knowledge_store)`. This populates the semantic collections from existing artifacts.

4. **Status integration:** Add `"semantic_knowledge"` key to `status()` dict with layer's `stats()` output.

5. **Store reference:** `self._semantic_layer = SemanticKnowledgeLayer(...)` so introspection agent and shell can access it.

6. **Shutdown:** Call `self._semantic_layer.stop()` in `stop()`.

**Conditional creation:** Only create if episodic memory is available (which implies ChromaDB is working). If no episodic memory, `_semantic_layer` stays `None`.

**Run tests after this step: all 1409 must still pass.**

---

### Step 4: Introspection + MockLLMClient (AD-244)

**Files:** `src/probos/agents/introspect.py`, `src/probos/cognitive/llm_client.py`

**AD-244: `search_knowledge` introspection intent.** Add a new intent to `IntrospectionAgent`:

- **Intent descriptor:** `IntentDescriptor(name="search_knowledge", params={"query": "...", "types": "..."}, description="Search across all ProbOS knowledge — episodes, agents, skills, workflows, QA reports, system events. Semantic similarity matching.", requires_reflect=True)`
- **Handler:** `_search_knowledge(rt, params)` 
  - Extracts `query` from params (required)
  - Extracts optional `types` from params (comma-separated string → list, or None for all)
  - Calls `rt._semantic_layer.search(query, types=types, limit=10)`
  - Returns structured results: `{"success": True, "data": {"query": query, "results": results, "count": len(results)}}`
  - If semantic layer not available, return graceful "Semantic knowledge layer not available"

Add to `intent_descriptors`, `_handled_intents`, and `act()` dispatcher.

**MockLLMClient patterns:** Add a pattern for `search_knowledge` that matches queries like "search for", "find in knowledge", "what do you know about". Return a simple DAG routing to the introspect agent with the `search_knowledge` intent.

**Run tests after this step: all 1409 must still pass.**

---

### Step 5: Shell Command + Panel (AD-245)

**Files:** `src/probos/experience/shell.py`, `src/probos/experience/panels.py`

**AD-245: `/search <query>` shell command and `render_search_panel()`.**

**`/search <query>` command** in `shell.py`:
- Requires at least one word of query text
- Calls `await self.runtime._semantic_layer.search(query)` (searches all types)
- Renders results via `render_search_panel()`
- If semantic layer not available, prints "Semantic knowledge layer not available"
- Optional type filter: `/search --type agents <query>` or `/search --type skills,episodes <query>`
- Add to COMMANDS dict and `/help` output

**`render_search_panel(query: str, results: list[dict], stats: dict) -> Panel`** in `panels.py`:
- Title: "Knowledge Search: {query}"
- Top section: per-collection document counts from stats
- Results table: Rich Table with columns: #, Type, Score, Document (truncated to 80 chars)
- Type column color-coded: `agent`=cyan, `skill`=green, `episode`=blue, `workflow`=yellow, `qa_report`=magenta, `event`=dim
- Empty state: "No matching results found"
- Score column: formatted as percentage (e.g., "87%")

**Run tests after this step: all 1409 must still pass.**

---

### Step 6: Tests (AD-246)

**File:** `tests/test_semantic_knowledge.py` (new)

**AD-246: Comprehensive test suite for SemanticKnowledgeLayer.** Target: ~45 tests.

#### Phase 20 cleanup tests (4 tests)
- `parse_agent_id()` returns correct components for simple ID (1 test)
- `parse_agent_id()` returns correct components for compound pool name (1 test)
- `parse_agent_id()` returns None for non-deterministic UUID (1 test)
- `EmergentDetector._all_patterns` capped at 500 (1 test)

#### SemanticKnowledgeLayer lifecycle (3 tests)
- start() creates all collections (1 test)
- stop() cleans up client (1 test)
- stats() returns per-collection counts (1 test)

#### Agent indexing (4 tests)
- index_agent() stores document in collection (1 test)
- index_agent() metadata contains agent_type and intent_name (1 test)
- index_agent() is idempotent (upsert, same ID on re-index) (1 test)
- Multiple agents indexed and searchable (1 test)

#### Skill indexing (3 tests)
- index_skill() stores document (1 test)
- index_skill() metadata contains intent_name and target_agent (1 test)
- Skill searchable by description (1 test)

#### Workflow indexing (3 tests)
- index_workflow() stores document (1 test)
- index_workflow() metadata contains pattern and intent_count (1 test)
- Workflow searchable by pattern text (1 test)

#### QA report indexing (2 tests)
- index_qa_report() stores with verdict metadata (1 test)
- QA report searchable by agent type (1 test)

#### Event indexing (2 tests)
- index_event() stores with category metadata (1 test)
- Event searchable by detail text (1 test)

#### Cross-type search (6 tests)
- search() returns results from multiple types (1 test)
- search() with types filter returns only specified types (1 test)
- search() includes episodes when episodic_memory available (1 test)
- search() results sorted by score descending (1 test)
- search() respects limit parameter (1 test)
- search() with no matches returns empty list (1 test)

#### Bulk re-indexing (3 tests)
- reindex_from_store() indexes all loaded agents (1 test)
- reindex_from_store() indexes all loaded skills (1 test)
- reindex_from_store() returns count dict (1 test)

#### Runtime integration (5 tests)
- Runtime creates semantic layer when episodic memory available (1 test)
- Runtime does NOT create semantic layer without episodic memory (1 test)
- status() includes semantic_knowledge key (1 test)
- Auto-indexing after store_agent (mock knowledge store hook) (1 test)
- Warm boot calls reindex_from_store (1 test)

#### Introspection integration (4 tests)
- search_knowledge intent returns results (1 test)
- search_knowledge with types filter works (1 test)
- search_knowledge without semantic layer returns graceful message (1 test)
- MockLLMClient routes "search for" query to search_knowledge (1 test)

#### Shell and panel (5 tests)
- /search command renders panel (1 test)
- /search without query shows usage (1 test)
- /help includes /search (1 test)
- render_search_panel with results shows table (1 test)
- render_search_panel empty shows "No matching results" (1 test)

**Total: ~44 tests → ~1453 total**

---

## What NOT To Build

- **No knowledge graph** — relational store is a separate roadmap item
- **No provenance system** — derivation chains are a separate roadmap item
- **No confidence decay** — knowledge lifecycle management is a separate roadmap item
- **No federation knowledge sync** — federation scope is separate. **Federation readiness note:** the Semantic Knowledge Layer is designed local-first (single-node), but its architecture is federation-ready. Each indexed artifact can carry `source_node` metadata. When knowledge federation is built (via Git remotes in the Multi-Participant Federation roadmap item), `reindex_from_store()` will naturally index pulled artifacts from peer nodes. The Noöplex emergence thesis (§6) predicts that TC_N becomes most meaningful when multiple meshes contribute knowledge — cross-node semantic search will be the mechanism for detecting whether federated nodes produce integrated understanding that no single node could achieve alone. This is a future phase, not Phase 21 scope.
- **No changes to existing EpisodicMemory** — episodes stay in their own ChromaDB collection. The knowledge layer queries it, doesn't replace it
- **No changes to EmergentDetector behavior** — only the `_extract_pool()` fix and `_all_patterns` cap
- **No duplicate episode indexing** — episodes are already ChromaDB-indexed. The knowledge layer calls `episodic_memory.recall()` for episode results rather than maintaining a second copy
- **No new background loops** — indexing happens synchronously during store operations
- **No LLM dependency** — indexing and search are pure embedding operations, no LLM calls

---

## Implementation Order

1. **Step 1 — Phase 20 cleanup** (identity.py + emergent_detector.py changes) → run tests
2. **Step 2 — SemanticKnowledgeLayer module** (new file, no existing code changes) → run tests
3. **Step 3 — Runtime wiring** (runtime.py changes only) → run tests
4. **Step 4 — Introspection agent + MockLLMClient** (introspect.py + llm_client.py) → run tests
5. **Step 5 — Shell + panels** (shell.py + panels.py) → run tests
6. **Step 6 — Tests** (new test file) → run tests, verify all pass

**After each step, run the full test suite: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`**

If tests fail at any step, fix before proceeding. Do NOT skip failing tests.

---

## PROGRESS.md Update

After all tests pass, update PROGRESS.md:

1. **Line 2** — Update status line: `Phase 21 — Semantic Knowledge Layer (XXXX/XXXX tests + 11 skipped)` with actual test count
2. **What's Been Built section** — Add SemanticKnowledgeLayer under Knowledge Layer table; update EmergentDetector description for the fixes
3. **What's Working section** — Add Phase 21 test summary
4. **Architectural Decisions** — Add entries for AD-241 through AD-246
5. **Checklist** — Mark "Semantic Knowledge Layer" as complete with strikethrough
6. **Test count** — Update the test count in the "What's Working" narrative

**AD numbering reminder: Current highest is AD-240. This phase uses AD-241 through AD-246. Verify before committing.**
