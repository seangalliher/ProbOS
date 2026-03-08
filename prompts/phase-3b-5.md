# Phase 3b-5: Habit Formation — Pre-Warm Integration & Workflow Caching

**Goal:** Wire the dreaming engine's pre-warm intents into the decomposer so frequently-used workflows resolve faster, and add a workflow cache that stores and replays successful multi-step DAGs without re-querying the LLM.

---

## Context

Phase 3b-4 built the dreaming engine. It replays episodes, strengthens/weakens Hebbian weights, and computes `pre_warm_intents` via temporal bigram analysis. But those pre-warm intents are stored on `DreamingEngine.pre_warm_intents` and **never consumed**. The decomposer doesn't know about them.

The original vision says: *"Frequently-used workflows get pre-composed, pre-warmed, ready to fire. Novel requests take longer. Familiar ones feel instant."*

This phase delivers that promise by:
1. Feeding pre-warm intents to the decomposer as hints
2. Building a workflow cache that stores successful DAG patterns and replays them without an LLM call

---

## Deliverables

### 1. Add `WorkflowCacheEntry` type — `src/probos/types.py`

```python
@dataclass
class WorkflowCacheEntry:
    pattern: str           # normalized user input (lowercase, stripped)
    dag_json: str          # serialized TaskDAG JSON
    hit_count: int = 0
    last_hit: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

### 2. Create `src/probos/cognitive/workflow_cache.py`

**`WorkflowCache`** — in-memory LRU cache of successful DAG patterns.

Public API:

| Method | Signature | Description |
|---|---|---|
| `__init__` | `(max_size: int = 100)` | Bounded cache |
| `store` | `(user_input: str, dag: TaskDAG) -> None` | Store a successful DAG pattern. Only stores DAGs with ≥1 node where all nodes completed successfully. Normalizes input (lowercase, strip). |
| `lookup` | `(user_input: str) -> TaskDAG \| None` | Return a cached DAG (deep copy with fresh node IDs and reset statuses) if the normalized input matches. Increments `hit_count`. Returns `None` on miss. |
| `lookup_fuzzy` | `(user_input: str, pre_warm_intents: list[str]) -> TaskDAG \| None` | If exact match fails, try fuzzy: find cached entries whose intents are a subset of `pre_warm_intents` AND whose normalized pattern shares ≥50% keyword overlap with the input. Returns the highest `hit_count` match, or `None`. |
| `size` | `@property -> int` | Number of cached entries |
| `entries` | `@property -> list[WorkflowCacheEntry]` | All entries sorted by hit_count descending |
| `clear` | `() -> None` | Empty the cache |

Internals:
- `_cache: dict[str, WorkflowCacheEntry]` keyed by normalized input
- `_normalize(text: str) -> str` — lowercase, strip, collapse whitespace
- When `max_size` exceeded, evict the entry with the lowest `hit_count` (LRU-by-popularity)
- `lookup` returns a **deep copy** of the stored DAG with all node statuses reset to `"pending"` and fresh UUIDs for node IDs (to avoid ID collisions across requests)

### 3. Modify `src/probos/cognitive/decomposer.py`

Add workflow cache integration to `IntentDecomposer`:

**a) Constructor** — accept optional `workflow_cache: WorkflowCache | None = None` and `pre_warm_intents: list[str] | None = None`.

**b) `decompose()` method** — before calling the LLM, check the workflow cache:

```python
# Try workflow cache first (exact match)
if self.workflow_cache:
    cached = self.workflow_cache.lookup(text)
    if cached:
        logger.info("Workflow cache HIT (exact): %s", text[:50])
        return cached

# Try fuzzy match with pre-warm intents
if self.workflow_cache and self.pre_warm_intents:
    cached = self.workflow_cache.lookup_fuzzy(text, self.pre_warm_intents)
    if cached:
        logger.info("Workflow cache HIT (fuzzy): %s", text[:50])
        return cached
```

If cache misses, proceed with LLM decomposition as today.

**c) Add `pre_warm_intents` property** — getter/setter so runtime can update from dreaming engine.

**d) Add pre-warm hints to the LLM prompt** — when `pre_warm_intents` is non-empty, append a section:

```
## PRE-WARM HINTS
Recent usage patterns suggest these intents are likely: read_file, list_directory
Consider using these intents if they match the user's request.
```

This goes after PAST EXPERIENCE and before `User request:`.

### 4. Modify `src/probos/runtime.py`

**a)** Create a `WorkflowCache` in `__init__` and pass it to the decomposer.

**b)** After successful DAG execution in `process_natural_language()`, store the result in the workflow cache:

```python
# Store successful workflows in cache
if self.workflow_cache and dag.nodes:
    all_success = all(n.status == "completed" for n in dag.nodes)
    if all_success:
        self.workflow_cache.store(text, dag)
```

**c)** After each dream cycle completes (in the scheduler callback or at activity time), sync pre-warm intents to the decomposer:

```python
if self.dream_scheduler and self.dream_scheduler.last_dream_report:
    engine = self.dream_scheduler.engine
    self.decomposer.pre_warm_intents = engine.pre_warm_intents
```

Add this sync in `process_natural_language()` before decomposition (cheap — just a list assignment).

**d)** Expose workflow cache stats in `status()`:

```python
result["workflow_cache"] = {
    "size": self.workflow_cache.size,
    "entries": len(self.workflow_cache.entries),
}
```

### 5. Modify `src/probos/experience/renderer.py`

In `process_with_feedback()`, after successful execution, store in workflow cache (mirroring runtime — same AD-34 pattern):

```python
if self.runtime.workflow_cache and dag.nodes:
    all_success = all(n.status == "completed" for n in dag.nodes)
    if all_success:
        self.runtime.workflow_cache.store(text, dag)
```

Also sync pre-warm intents before decomposition (same as runtime).

### 6. Modify `src/probos/experience/panels.py`

Add `render_workflow_cache_panel(entries: list, size: int) -> Panel` that shows cached workflow patterns with hit counts. Keep it simple — a table with columns: Pattern (truncated to 40 chars), Intents, Hits, Last Hit.

### 7. Modify `src/probos/experience/shell.py`

Add `/cache` command that renders the workflow cache panel.

### 8. Create `tests/test_workflow_cache.py`

---

## Build Order

1. **Types** (`types.py`) — add `WorkflowCacheEntry`
2. **Workflow cache** (`workflow_cache.py`) — core cache logic
3. **Tests** (`test_workflow_cache.py`) — unit tests for cache
4. **Decomposer** (`decomposer.py`) — cache lookup before LLM, pre-warm hints
5. **Runtime** (`runtime.py`) — create cache, store after success, sync pre-warm
6. **Renderer** (`renderer.py`) — store after success, sync pre-warm
7. **Panels** (`panels.py`) — `render_workflow_cache_panel`
8. **Shell** (`shell.py`) — `/cache` command
9. **Integration tests** — add to `test_workflow_cache.py`
10. **Run full suite** — `uv run pytest tests/ -v` — all 415 existing + new tests must pass.

---

## Test Specification — `tests/test_workflow_cache.py`

### WorkflowCache unit tests

1. **`test_store_and_exact_lookup`** — Store a DAG for "read the file", lookup same string. Assert DAG returned with correct intents.
2. **`test_lookup_miss_returns_none`** — Lookup uncached input. Assert `None`.
3. **`test_lookup_returns_deep_copy`** — Store a DAG, lookup twice. Assert returned DAGs have different node IDs and both have status `"pending"`.
4. **`test_normalize_case_insensitive`** — Store "Read The FILE", lookup "read the file". Assert hit.
5. **`test_normalize_strips_whitespace`** — Store "  read file  ", lookup "read file". Assert hit.
6. **`test_hit_count_increments`** — Store, lookup 3 times. Assert `hit_count == 3`.
7. **`test_max_size_evicts_lowest_hits`** — Create cache with `max_size=2`. Store 3 entries. Assert size == 2 and the entry with lowest hit_count was evicted.
8. **`test_only_stores_successful_dags`** — Create a DAG where one node has `status="failed"`. Call `store()`. Assert `size == 0`.
9. **`test_fuzzy_lookup_with_prewarm`** — Store a DAG with `read_file` intent for "read pyproject.toml". Fuzzy lookup "read the config file" with `pre_warm_intents=["read_file"]`. Assert hit (keyword overlap ≥ 50% on "read"+"file").
10. **`test_fuzzy_lookup_no_overlap_returns_none`** — Store a "read file" DAG. Fuzzy lookup "fetch website data" with `pre_warm_intents=["http_fetch"]`. Assert `None`.
11. **`test_clear_empties_cache`** — Store entries, call `clear()`. Assert `size == 0`.
12. **`test_entries_sorted_by_hits`** — Store 3 entries, lookup them different numbers of times. Assert `entries` returns highest hit_count first.

### Decomposer integration tests

13. **`test_decomposer_cache_hit_skips_llm`** — Create decomposer with a WorkflowCache pre-loaded with a DAG. Call `decompose()` with matching input. Assert returned DAG matches cached pattern. Assert LLM `call_count == 0`.
14. **`test_decomposer_cache_miss_calls_llm`** — Create decomposer with empty WorkflowCache. Call `decompose()`. Assert LLM `call_count == 1`.
15. **`test_decomposer_prewarm_in_prompt`** — Set `decomposer.pre_warm_intents = ["read_file", "list_directory"]`. Call `decompose()` with a cache miss. Assert "PRE-WARM HINTS" appears in the LLM request prompt.

### Runtime integration tests

16. **`test_runtime_stores_successful_dag_in_cache`** — Process NL, assert `workflow_cache.size == 1` after successful execution.
17. **`test_runtime_skips_failed_dag_in_cache`** — Process NL that produces a failed node. Assert `workflow_cache.size == 0`.
18. **`test_status_includes_workflow_cache`** — Assert `"workflow_cache"` key in status dict.

### Shell/panel tests

19. **`test_cache_command_renders_panel`** — Execute `/cache` command. Assert output contains "Workflow Cache".
20. **`test_render_workflow_cache_panel_with_entries`** — Render panel with mock entries, assert hit count displayed.
21. **`test_render_workflow_cache_panel_empty`** — Render panel with empty list, assert "empty" message.

**Total: 21 new tests. Target: 436/436 (415 existing + 21 new).**

---

## Milestone Test

**End-to-end scenario:** Process "read the file at /tmp/test.txt" twice via `process_natural_language()`. The first call hits the LLM (`call_count == 1`). The second call hits the workflow cache (`call_count` still `== 1`). Both return valid `TaskDAG` objects with `read_file` intent. The cached DAG has fresh node IDs (different from the first). This proves the full loop: LLM decompose → execute → cache store → cache hit → skip LLM.

This is test #13 or a standalone integration test.

---

## Rules

1. Do NOT modify the `DreamingEngine` or `DreamScheduler`. Pre-warm intents are already computed — this phase only consumes them.
2. Do NOT add persistence (SQLite) to the workflow cache. It's in-memory and resets on restart. Persistence is a future concern.
3. The workflow cache is strictly an optimization — if removed, everything works exactly as before (just slower on repeated requests).
4. `lookup()` must return a **deep copy** with reset statuses. Never return a reference to the cached DAG.
5. Fuzzy matching must require pre-warm intent overlap AND keyword overlap. Neither alone is sufficient.
6. All existing 415 tests must continue to pass unchanged.
7. Import `WorkflowCache` from `probos.cognitive.workflow_cache`.
8. The `/cache` command does not take arguments.
9. Run `uv run pytest tests/ -v` after every file change to catch regressions early.
10. Update `PROGRESS.md` when done: add Phase 3b-5 section, new AD entries, update test counts, mark Phase 3b-5 complete in "What's Next".
