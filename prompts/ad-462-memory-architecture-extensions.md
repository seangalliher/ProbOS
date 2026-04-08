# AD-462c/d/e: Memory Architecture Extensions — Build Prompt

**AD:** 462c (Variable Recall Tiers), 462d (Social Memory), 462e (Oracle Service)
**Status:** In Progress
**Scope:** Multi-phased — 3 phases, 1 new file, 5 modified files, 1 new test file
**GitHub Issue:** #25

## Context

ProbOS has a mature episodic memory pipeline: `recall_weighted()` (AD-567b) provides salience-scored recall, `recall_by_anchor()` (AD-570) provides structured queries, and the `ParticipantIndex` (AD-570b) provides participant lookups. But all agents get the same recall capability regardless of rank. Agents cannot ask each other for help remembering. And there's no unified way to search across all three knowledge tiers (Episodes, Ship's Records, KnowledgeStore).

AD-462a (salience-weighted recall) was absorbed by AD-567b. AD-462b (active forgetting) was absorbed by AD-567d. AD-462f (concept graphs) is deferred. This build delivers the remaining three sub-ADs.

## Builder Instructions

```
Read and execute this build prompt: d:\ProbOS\prompts\ad-462-memory-architecture-extensions.md
```

Execute phases 1→2→3 sequentially. Run tests after each phase. Do NOT proceed to the next phase if tests fail.

---

## Phase 1: AD-462c — Variable Recall Tiers (Trust-Gated Recall Depth)

**Principle:** Memory capability scales with earned trust. Junior agents get basic recall; experienced officers get the full pipeline. This maps to the biological memory staging model — not every organism gets the same memory capacity.

### 1a. New recall tier model in `src/probos/cognitive/earned_agency.py`

Add a `RecallTier` enum and a mapping function after the existing `AgencyLevel` enum:

```python
class RecallTier(str, Enum):
    """Memory recall capability tier — mapped from Earned Agency rank."""
    BASIC = "basic"            # Vector similarity only, small budget
    ENHANCED = "enhanced"      # Vector + keyword + salience weights, standard budget
    FULL = "full"              # Full recall_weighted + recall_by_anchor, large budget
    ORACLE = "oracle"          # All recall paths + Oracle Service (AD-462e)


def recall_tier_from_rank(rank: Rank) -> RecallTier:
    """Map rank to recall capability tier."""
    return {
        Rank.ENSIGN: RecallTier.BASIC,
        Rank.LIEUTENANT: RecallTier.ENHANCED,
        Rank.COMMANDER: RecallTier.FULL,
        Rank.SENIOR: RecallTier.ORACLE,
    }[rank]
```

### 1b. Recall tier parameters in `src/probos/config.py`

Add `RecallTierConfig` as a nested model inside `MemoryConfig`. Place it AFTER line 278 (`anchor_confidence_gate`):

```python
    # AD-462c: Variable Recall Tiers
    recall_tiers: dict[str, dict[str, Any]] = {
        "basic": {
            "k": 3,
            "context_budget": 1500,
            "anchor_confidence_gate": 0.0,
            "use_salience_weights": False,
            "cross_department_anchors": False,
        },
        "enhanced": {
            "k": 5,
            "context_budget": 4000,
            "anchor_confidence_gate": 0.3,
            "use_salience_weights": True,
            "cross_department_anchors": False,
        },
        "full": {
            "k": 8,
            "context_budget": 6000,
            "anchor_confidence_gate": 0.3,
            "use_salience_weights": True,
            "cross_department_anchors": True,
        },
        "oracle": {
            "k": 10,
            "context_budget": 8000,
            "anchor_confidence_gate": 0.2,
            "use_salience_weights": True,
            "cross_department_anchors": True,
        },
    }
```

The `Any` import should already exist in config.py. If not, add it.

### 1c. Helper to resolve tier parameters in `src/probos/cognitive/episodic.py`

Add a module-level helper function BEFORE the `EpisodicMemory` class:

```python
def resolve_recall_tier_params(
    tier: str,
    tier_config: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve recall parameters for a given tier (AD-462c).

    Returns dict with keys: k, context_budget, anchor_confidence_gate,
    use_salience_weights, cross_department_anchors.
    Falls back to 'enhanced' tier defaults if tier not found.
    """
    defaults = {
        "basic": {"k": 3, "context_budget": 1500, "anchor_confidence_gate": 0.0, "use_salience_weights": False, "cross_department_anchors": False},
        "enhanced": {"k": 5, "context_budget": 4000, "anchor_confidence_gate": 0.3, "use_salience_weights": True, "cross_department_anchors": False},
        "full": {"k": 8, "context_budget": 6000, "anchor_confidence_gate": 0.3, "use_salience_weights": True, "cross_department_anchors": True},
        "oracle": {"k": 10, "context_budget": 8000, "anchor_confidence_gate": 0.2, "use_salience_weights": True, "cross_department_anchors": True},
    }
    source = tier_config if tier_config else defaults
    return source.get(tier, source.get("enhanced", defaults["enhanced"]))
```

### 1d. Wire tier-gated recall into `src/probos/cognitive/cognitive_agent.py`

Modify `_recall_relevant_memories()` (starts at line 2319).

**AFTER** line 2360 (`_mem_id = getattr(self, 'sovereign_id', None) or self.id`), add tier resolution:

```python
            # AD-462c: Resolve recall tier from agent rank
            from probos.earned_agency import recall_tier_from_rank, RecallTier
            from probos.cognitive.episodic import resolve_recall_tier_params
            _rank = getattr(self, 'rank', None)
            _recall_tier = recall_tier_from_rank(_rank) if _rank else RecallTier.ENHANCED
            _tier_cfg = getattr(mem_cfg, 'recall_tiers', None) if mem_cfg else None
            _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)
```

Then modify the `recall_weighted` call block (lines 2371-2381). Replace the hardcoded parameters:

**Replace** lines 2371-2381 with:

```python
            scored_results = []
            if hasattr(em, 'recall_weighted') and _tier_params.get("use_salience_weights", True):
                scored_results = await em.recall_weighted(
                    _mem_id, query,
                    trust_network=trust_net,
                    hebbian_router=heb_router,
                    intent_type=intent.intent,
                    k=_tier_params.get("k", 5),
                    context_budget=_tier_params.get("context_budget", 4000),
                    weights=getattr(mem_cfg, 'recall_weights', None) if mem_cfg else None,
                    anchor_confidence_gate=_tier_params.get("anchor_confidence_gate", 0.3),
                )
            elif hasattr(em, 'recall_for_agent'):
                # BASIC tier: vector similarity only, no salience weighting
                episodes_raw = await em.recall_for_agent(
                    _mem_id, query, k=_tier_params.get("k", 3)
                )
                # Wrap in pseudo-scored-results for uniform downstream handling
                scored_results = []  # episodes handled by fallback path below
                if episodes_raw:
                    observation["_basic_recall_episodes"] = episodes_raw
```

Then modify the fallback path (lines 2383-2388). Replace with:

```python
            # Fallback to old recall path if recall_weighted unavailable or returned nothing
            episodes = [rs.episode for rs in scored_results] if scored_results else []
            if not episodes:
                episodes = observation.pop("_basic_recall_episodes", [])
            if not episodes:
                episodes = await em.recall_for_agent(_mem_id, query, k=_tier_params.get("k", 3))
            if not episodes and hasattr(em, 'recent_for_agent'):
                episodes = await em.recent_for_agent(_mem_id, k=_tier_params.get("k", 3))
```

### 1e. Wire tier-gated recall into `src/probos/proactive.py`

Same pattern in `_gather_context()`. AFTER line 802 (`_agent_mem_id = ...`), add:

```python
                # AD-462c: Resolve recall tier from agent rank
                from probos.earned_agency import recall_tier_from_rank, RecallTier
                from probos.cognitive.episodic import resolve_recall_tier_params
                _rank = getattr(agent, 'rank', None)
                _recall_tier = recall_tier_from_rank(_rank) if _rank else RecallTier.ENHANCED
                _tier_cfg = getattr(mem_cfg, 'recall_tiers', None) if mem_cfg else None
                _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)
```

Then replace the `recall_weighted` call (lines 818-826) with:

```python
                    if _tier_params.get("use_salience_weights", True):
                        scored_results = await em.recall_weighted(
                            _agent_mem_id, query,
                            trust_network=trust_net,
                            hebbian_router=heb_router,
                            k=_tier_params.get("k", 5),
                            context_budget=_tier_params.get("context_budget", 4000),
                            weights=getattr(mem_cfg, 'recall_weights', None) if mem_cfg else None,
                            anchor_confidence_gate=_tier_params.get("anchor_confidence_gate", 0.3),
                        )
                        episodes = [rs.episode for rs in scored_results]
                    else:
                        # BASIC tier: vector similarity only
                        episodes = await em.recall_for_agent(
                            _agent_mem_id, query, k=_tier_params.get("k", 3)
                        )
```

And update the fallback calls (lines 830-835) to use `_tier_params.get("k", 5)` instead of hardcoded `5`.

### Phase 1 Tests

Add the following tests to `tests/test_memory_architecture.py` (NEW file):

**TestRecallTiers** (8 tests):
1. `test_recall_tier_from_rank_ensign` — Ensign → BASIC
2. `test_recall_tier_from_rank_lieutenant` — Lieutenant → ENHANCED
3. `test_recall_tier_from_rank_commander` — Commander → FULL
4. `test_recall_tier_from_rank_senior` — Senior → ORACLE
5. `test_resolve_recall_tier_params_basic` — basic tier returns small k, small budget, no salience
6. `test_resolve_recall_tier_params_oracle` — oracle tier returns large k, large budget, salience + cross-dept
7. `test_resolve_recall_tier_params_unknown_falls_back` — unknown tier name → enhanced defaults
8. `test_resolve_recall_tier_params_custom_config` — custom tier_config dict overrides defaults

---

## Phase 2: AD-462e — Oracle Service (Cross-Tier Unified Query)

**Principle:** A Ship's Computer service that searches across all three knowledge tiers (Tier 1: EpisodicMemory, Tier 2: Ship's Records, Tier 3: KnowledgeStore) and returns merged, provenance-tagged results. Dependency-injected, no direct imports of concrete stores.

### 2a. New file: `src/probos/cognitive/oracle_service.py`

```python
"""Oracle Service — Cross-Tier Unified Memory Query (AD-462e).

Searches across all three knowledge tiers:
  - Tier 1 (Episodic): ChromaDB vector + salience-weighted recall
  - Tier 2 (Records): Ship's Records keyword search
  - Tier 3 (Operational): KnowledgeStore file-based lookup

Results are merged, scored, and provenance-tagged so the consumer
knows which knowledge tier each result came from.
"""
```

**Class: `OracleService`**

Constructor (all dependency-injected, all optional):
```python
class OracleService:
    def __init__(
        self,
        *,
        episodic_memory: Any = None,
        records_store: Any = None,
        knowledge_store: Any = None,
        trust_network: Any = None,
        hebbian_router: Any = None,
    ):
```

Store all as private fields. No startup/shutdown needed — this is a stateless query aggregator.

**Dataclass: `OracleResult`** (frozen):
```python
@dataclass(frozen=True)
class OracleResult:
    """A single result from the Oracle Service."""
    source_tier: str         # "episodic" | "records" | "operational"
    content: str             # The text content
    score: float             # Normalized relevance score (0.0–1.0)
    metadata: dict[str, Any] # Tier-specific metadata
    provenance: str          # Human-readable provenance tag
```

**Method: `async query()`**:
```python
    async def query(
        self,
        query_text: str,
        *,
        agent_id: str = "",
        intent_type: str = "",
        k_per_tier: int = 5,
        tiers: list[str] | None = None,  # None = all tiers
    ) -> list[OracleResult]:
```

Implementation:
1. **Tier 1 (Episodic):** If `episodic_memory` is set and `"episodic"` in tiers:
   - Try `recall_weighted()` if agent_id provided (with trust_network, hebbian_router, intent_type). Use k=k_per_tier, context_budget=999999 (no budget enforcement at Oracle level — leave that to the caller).
   - Fallback to `recall()` (non-agent-scoped) if no agent_id.
   - Convert each result to `OracleResult(source_tier="episodic", content=episode.user_input, score=recall_score.composite_score, metadata={"episode_id": ep.id, "timestamp": ep.timestamp, "agent_ids": ep.agent_ids, "source": ep.source}, provenance="[episodic memory]")`
   - Score normalization: composite_score is already 0–1.

2. **Tier 2 (Records):** If `records_store` is set and `"records"` in tiers:
   - Call `records_store.search(query_text, scope="ship")`.
   - Convert each result to `OracleResult(source_tier="records", content=result.get("snippet", ""), score=min(result.get("score", 0) / 10.0, 1.0), metadata={"path": result.get("path", ""), "frontmatter": result.get("frontmatter", {})}, provenance="[ship's records]")`
   - Score normalization: RecordsStore returns raw keyword match count. Normalize: `min(matches / 10.0, 1.0)`.

3. **Tier 3 (Operational/KnowledgeStore):** If `knowledge_store` is set and `"operational"` in tiers:
   - Call `knowledge_store.load_episodes(limit=k_per_tier)`.
   - Simple keyword matching against `episode.user_input` and `episode.reflection`: count query words present.
   - Convert to `OracleResult(source_tier="operational", content=ep.user_input, score=min(keyword_matches / 5.0, 1.0), metadata={"timestamp": ep.timestamp}, provenance="[operational state]")`
   - **Note:** KnowledgeStore is not a primary query target — it's operational state. This tier is included for completeness but will typically score low.

4. **Merge & sort**: Combine all results, sort by `score` descending, return top `k_per_tier * len(active_tiers)` results.

**Error handling:** Each tier is independently try/excepted. If one tier fails, the others still return results. Log failures at debug level.

**Method: `async query_formatted()`** — convenience method that returns a formatted string:
```python
    async def query_formatted(
        self,
        query_text: str,
        *,
        agent_id: str = "",
        intent_type: str = "",
        k_per_tier: int = 3,
        tiers: list[str] | None = None,
        max_chars: int = 4000,
    ) -> str:
```

Returns a string like:
```
=== ORACLE QUERY RESULTS ===
[episodic memory] (score: 0.82, 2h ago) Observed LaForge debugging routing issue...
[ship's records] (score: 0.71, notebooks/Lynx/systems-analysis.md) Stasis recovery creates temporal desync...
[episodic memory] (score: 0.65, 1d ago) Participated in trust calibration discussion...
=== END ORACLE RESULTS ===
```

Budget enforcement: accumulate content lengths, stop at `max_chars`.

### 2b. Startup wiring in `src/probos/startup/dreaming.py`

This is the wrong place — Oracle Service is not a dreaming subsystem. Instead, wire it in `src/probos/startup/cognitive_services.py`.

Find the end of the cognitive services init function (after the AD-570b participant index block). Add:

```python
    # AD-462e: Oracle Service — cross-tier unified memory query
    from probos.cognitive.oracle_service import OracleService
    oracle_service = OracleService(
        episodic_memory=episodic_memory,
        records_store=records_store,
        knowledge_store=knowledge_store,
        trust_network=trust_network,
        hebbian_router=hebbian_router,
    )
```

Check what parameters `init_cognitive_services()` already receives. It should have `episodic_memory`, `trust_network`, `hebbian_router`. If `records_store` and `knowledge_store` are not passed, add them as parameters with default `None`. Store on the result object.

**IMPORTANT:** Verify the actual function signature of `init_cognitive_services()` before modifying. Read the file. The parameters `records_store` and `knowledge_store` may need to be threaded from `src/probos/startup/finalize.py` or wherever the cognitive services startup is called.

Store the oracle_service on the result object so runtime can access it as `runtime._oracle_service`.

### 2c. API route in `src/probos/routers/system.py`

Add after the `/behavioral-metrics/history` route:

```python
@router.get("/oracle")
async def oracle_query(
    q: str,
    agent_id: str = "",
    k: int = 3,
    tiers: str = "",
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-462e: Cross-tier unified memory query."""
    oracle = getattr(runtime, "_oracle_service", None)
    if not oracle:
        return {"status": "not_available", "message": "Oracle service not wired"}
    tier_list = [t.strip() for t in tiers.split(",") if t.strip()] or None
    results = await oracle.query(q, agent_id=agent_id, k_per_tier=k, tiers=tier_list)
    return {
        "status": "ok",
        "count": len(results),
        "results": [
            {"source_tier": r.source_tier, "content": r.content[:500], "score": r.score,
             "provenance": r.provenance, "metadata": r.metadata}
            for r in results
        ],
    }
```

### Phase 2 Tests

Add to `tests/test_memory_architecture.py`:

**TestOracleService** (10 tests):
1. `test_oracle_query_episodic_only` — only episodic_memory injected, returns episodic results
2. `test_oracle_query_records_only` — only records_store injected, returns records results
3. `test_oracle_query_all_tiers` — all three stores injected, returns merged sorted results
4. `test_oracle_query_tier_filter` — `tiers=["records"]` only queries records tier
5. `test_oracle_query_empty_query` — empty query returns empty results
6. `test_oracle_query_tier_failure_graceful` — one tier raises, others still return
7. `test_oracle_result_provenance_tags` — results have correct provenance strings
8. `test_oracle_query_formatted_budget` — formatted output respects max_chars budget
9. `test_oracle_query_formatted_content` — formatted output contains `=== ORACLE QUERY RESULTS ===` header
10. `test_oracle_no_stores` — no stores injected, returns empty results gracefully

Use mock stores with `AsyncMock` for all tier dependencies. Pattern:
```python
@pytest.fixture
def mock_episodic():
    em = AsyncMock()
    em.recall_weighted = AsyncMock(return_value=[
        MagicMock(episode=MagicMock(id="ep1", user_input="test memory", timestamp=time.time(),
                                     agent_ids=["agent-001"], source="direct"),
                  composite_score=0.85),
    ])
    return em
```

---

## Phase 3: AD-462d — Social Memory ("Does anyone remember?")

**Principle:** When an agent can't recall something, it can ask other crew members through the Ward Room. This is protocol, not infrastructure — uses existing Ward Room + recall pipeline with a new thread_mode.

### 3a. Add `memory_query` thread mode support

In `src/probos/ward_room/models.py`, the `thread_mode` column already accepts any string value (no CHECK constraint in the schema). No schema change needed. The `browse_threads()` method already filters on `thread_mode` as a parameter.

### 3b. New file: `src/probos/cognitive/social_memory.py`

```python
"""Social Memory — Cross-Agent Memory Query Protocol (AD-462d).

"Does anyone remember?" — When an agent can't recall something from
their own sovereign memory shard, they can post a memory query to
the Ward Room. Other agents detect the query during their proactive
cycle and respond from their episodic memory if they have relevant
matches.

This is PROTOCOL, not infrastructure. It uses existing Ward Room
threads + episodic recall. The SocialMemoryService coordinates
the query/response lifecycle.
"""
```

**Class: `SocialMemoryService`**

Constructor:
```python
class SocialMemoryService:
    def __init__(
        self,
        *,
        ward_room: Any = None,
        episodic_memory: Any = None,
    ):
        self._ward_room = ward_room
        self._episodic_memory = episodic_memory
```

**Method: `async post_memory_query()`** — an agent posts a memory query:
```python
    async def post_memory_query(
        self,
        requesting_agent_id: str,
        requesting_callsign: str,
        query: str,
        *,
        department_channel_id: str = "",
        k: int = 3,
    ) -> str | None:
        """Post a memory query to the Ward Room.

        Creates a thread with thread_mode='memory_query' in the agent's
        department channel (or a general channel). Returns the thread_id
        if created, None if ward_room unavailable.
        """
```

Implementation:
1. Guard: if `self._ward_room` is None, return None.
2. Create a thread via `self._ward_room.create_thread()`:
   - `channel_id=department_channel_id` (caller provides their department channel)
   - `author_id=requesting_agent_id`
   - `title=f"[Memory Query] {query[:80]}"`
   - `body=f"Does anyone remember: {query}"`
   - `thread_mode="memory_query"`
   - `max_responders=k` (limit responses)
3. Return the thread ID.

**Method: `async check_and_respond_to_queries()`** — called during proactive cycle:
```python
    async def check_and_respond_to_queries(
        self,
        agent_id: str,
        agent_callsign: str,
        *,
        since: float = 0.0,
        max_queries: int = 3,
    ) -> list[dict[str, Any]]:
        """Check for open memory queries and respond if agent has relevant memories.

        Returns list of dicts: [{"thread_id": ..., "query": ..., "responded": bool}]
        """
```

Implementation:
1. Browse threads with `thread_mode="memory_query"`, since=since, limit=max_queries.
2. For each query thread:
   a. Skip if the requesting author is this agent (don't answer your own query).
   b. Get the thread to check if this agent already responded (check posts for author_id match).
   c. Extract the query text from the thread title (strip `[Memory Query]` prefix).
   d. Try `self._episodic_memory.recall_for_agent(agent_id, query_text, k=2)`.
   e. If results found with meaningful content (user_input length > 20):
      - Post a reply via `self._ward_room.create_post()`:
        - `thread_id=thread.id`
        - `author_id=agent_id`
        - `body=f"I recall: {episode.user_input[:300]}. Source: {episode.source}, {format_duration(time.time() - episode.timestamp)} ago."`
      - Mark as responded.
   f. If no results, skip (don't post "I don't remember" noise).
3. Return the response summary list.

**Method: `async get_query_responses()`** — requesting agent checks responses:
```python
    async def get_query_responses(
        self,
        thread_id: str,
    ) -> list[dict[str, str]]:
        """Get responses to a memory query thread.

        Returns list of dicts: [{"responder_id": ..., "content": ..., "timestamp": ...}]
        """
```

Implementation: Call `self._ward_room.get_thread(thread_id)`, extract posts (skip the original post by author match), return structured response dicts.

### 3c. Integration in proactive cycle — `src/probos/proactive.py`

In `_gather_context()`, AFTER the episodic memory section (after line 864), add a social memory section:

```python
        # AD-462d: Social Memory — check for open memory queries to respond to
        if hasattr(rt, '_social_memory_service') and rt._social_memory_service:
            try:
                since = time.time() - 3600  # Last hour
                responses = await rt._social_memory_service.check_and_respond_to_queries(
                    agent_id=getattr(agent, 'sovereign_id', None) or agent.id,
                    agent_callsign=getattr(agent, 'callsign', '') or '',
                    since=since,
                    max_queries=2,
                )
                if responses:
                    context["memory_query_responses"] = responses
            except Exception:
                logger.debug("AD-462d: Social memory check failed", exc_info=True)
```

### 3d. Startup wiring in `src/probos/startup/cognitive_services.py`

After the Oracle Service wiring (from Phase 2), add:

```python
    # AD-462d: Social Memory Service
    from probos.cognitive.social_memory import SocialMemoryService
    social_memory_service = SocialMemoryService(
        ward_room=ward_room,
        episodic_memory=episodic_memory,
    )
```

Store on the result object. Verify `ward_room` is available as a parameter to `init_cognitive_services()` — if not, thread it through.

### Phase 3 Tests

Add to `tests/test_memory_architecture.py`:

**TestSocialMemory** (10 tests):
1. `test_post_memory_query_creates_thread` — creates thread with thread_mode="memory_query"
2. `test_post_memory_query_no_ward_room` — returns None when ward_room is None
3. `test_check_queries_finds_open_query` — finds and responds to an open memory_query thread
4. `test_check_queries_skips_own_query` — doesn't respond to own query
5. `test_check_queries_skips_already_responded` — doesn't double-respond
6. `test_check_queries_skips_no_relevant_memory` — no recall results → no response posted
7. `test_check_queries_responds_with_memory_content` — response includes episode user_input
8. `test_get_query_responses_returns_replies` — fetches replies from a memory query thread
9. `test_get_query_responses_excludes_original_post` — original query post excluded from responses
10. `test_social_memory_no_episodic_memory` — gracefully handles missing episodic_memory

Use `AsyncMock` ward_room and episodic_memory. Pattern for ward_room mock:
```python
@pytest.fixture
def mock_ward_room():
    wr = AsyncMock()
    wr.create_thread = AsyncMock(return_value=MagicMock(id="thread-001"))
    wr.browse_threads = AsyncMock(return_value=[
        MagicMock(id="thread-001", author_id="agent-requester", title="[Memory Query] trust thresholds",
                  body="Does anyone remember: trust thresholds", thread_mode="memory_query"),
    ])
    wr.get_thread = AsyncMock(return_value={"thread": {...}, "posts": [...]})
    wr.create_post = AsyncMock(return_value=MagicMock(id="post-001"))
    return wr
```

---

## Files Summary

| File | Action | Phase |
|------|--------|-------|
| `src/probos/cognitive/earned_agency.py` | Modified — RecallTier enum + recall_tier_from_rank() | 1 |
| `src/probos/config.py` | Modified — recall_tiers in MemoryConfig | 1 |
| `src/probos/cognitive/episodic.py` | Modified — resolve_recall_tier_params() helper | 1 |
| `src/probos/cognitive/cognitive_agent.py` | Modified — tier-gated recall in _recall_relevant_memories() | 1 |
| `src/probos/proactive.py` | Modified — tier-gated recall in _gather_context() + social memory check | 1, 3 |
| `src/probos/cognitive/oracle_service.py` | **Created** — OracleService + OracleResult | 2 |
| `src/probos/startup/cognitive_services.py` | Modified — Oracle + SocialMemory wiring | 2, 3 |
| `src/probos/routers/system.py` | Modified — /oracle API route | 2 |
| `src/probos/cognitive/social_memory.py` | **Created** — SocialMemoryService | 3 |
| `tests/test_memory_architecture.py` | **Created** — 28 tests across 3 test classes | 1, 2, 3 |

## Engineering Principles Compliance

| Principle | How Enforced |
|-----------|-------------|
| **SOLID/S** | OracleService = query aggregation only. SocialMemoryService = query/response lifecycle only. RecallTier = tier mapping only. Each has one reason to change. |
| **SOLID/D** | OracleService receives all stores via constructor injection (episodic_memory, records_store, knowledge_store). SocialMemoryService receives ward_room + episodic_memory. No concrete imports. |
| **SOLID/O** | Existing recall_weighted()/recall_for_agent() unchanged. Tier gating adds a parameter resolution layer on top. |
| **Law of Demeter** | No reaching through objects. OracleService calls public methods on injected dependencies. |
| **Cloud-Ready Storage** | OracleService is backend-agnostic — receives abstract interfaces. SocialMemoryService uses existing Ward Room service interface. |
| **Fail Fast** | Each Oracle tier is independently try/excepted (log-and-degrade). Social memory check failures don't block proactive cycle. |
| **Defense in Depth** | Tier parameters validated with fallback to enhanced defaults. Missing stores → empty results, not crashes. |
| **DRY** | `resolve_recall_tier_params()` is a single function used by both cognitive_agent.py and proactive.py. |

## Scope Boundary

**In scope:**
- RecallTier enum and rank→tier mapping
- Tier-parameterized recall in both cognitive_agent.py and proactive.py
- OracleService cross-tier query aggregator
- SocialMemoryService Ward Room memory query protocol
- API route for Oracle
- 28 tests

**Out of scope:**
- AD-462f (concept graphs, optimized representation) — deferred
- LLM-augmented query translation (the "MemoryProcessor" from the roadmap) — future, token-expensive
- Oracle access from agents during act() — Oracle is query-time only, not prompt injection
- Social memory query initiation from agents (agents don't yet decide "I can't remember, let me ask") — requires cognitive self-awareness of recall failure, future AD
- HXI Oracle panel — future AD
