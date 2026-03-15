# AD-272: Decision Distillation — Deterministic Learning Loop for CognitiveAgents

## Problem

Every CognitiveAgent query makes an LLM call in `decide()`, even for identical repetitive requests. "What's the Bitcoin price?" on Monday = LLM call. Same query Tuesday = same LLM call. 100 identical queries = 100 LLM calls. This wastes latency (2-5s per call), cost (~$0.01-0.05 per call), and doesn't improve with experience.

## Design

Add a **decision cache** inside `CognitiveAgent.decide()` that records LLM reasoning results and replays them for matching future observations. Agents start as reasoning engines and progressively compile themselves into deterministic functions.

### Flow:

```
decide(observation):
  cache_key = semantic_hash(instructions + observation)
  if cache_key in decision_cache:
    return cached_decision                    # <1ms, $0
  llm_result = await self._llm_client.complete(...)  # 2-5s, $0.01+
  decision_cache.store(cache_key, llm_result, ttl)
  return llm_result
```

### Key design decisions:

1. **Cache key**: Hash of `instructions` + serialized observation. Two agents with different instructions but the same observation get different cache entries. Use a deterministic JSON serialization + SHA256 hash, NOT semantic similarity (too expensive to compute on every decide() call).

2. **TTL (time-to-live)**: Per-entry expiration. Default: 300 seconds (5 minutes). This handles time-sensitive data (Bitcoin price changes, weather). The agent's `instructions` can influence TTL — if instructions mention "real-time" or "current" or "live," use a shorter TTL. Static knowledge like translations gets a longer TTL (3600s / 1 hour).

3. **Cache storage**: Simple in-memory dict on the agent class (class-level, shared across pool members — same pattern as HttpFetchAgent._domain_state). Persisted to KnowledgeStore on shutdown, restored on warm boot.

4. **Negative feedback eviction**: When `/feedback bad` is applied, the FeedbackEngine should evict matching cache entries. This prevents repeating bad decisions.

5. **Cache hit trust scoring**: Cache hits still count as successful executions for trust scoring — the agent performed correctly, it just did it faster.

6. **Metrics**: Track cache hits/misses per agent for introspection (`/designed` could show hit rate).

## Implementation

### File: `src/probos/cognitive/cognitive_agent.py`

1. Add imports: `import hashlib`, `import json`, `import time`

2. Add class-level cache dict and TTL config:

```python
class CognitiveAgent(BaseAgent):
    # Decision cache — shared across all instances of the same subclass
    _decision_cache: ClassVar[dict[str, tuple[dict, float, float]]] = {}
    # Cache format: {hash: (decision_dict, created_at_monotonic, ttl_seconds)}
    
    # Default TTL — subclasses or instructions can override
    _cache_ttl_seconds: float = 300.0  # 5 minutes default
    
    # Cache metrics
    _cache_hits: int = 0
    _cache_misses: int = 0
```

**WAIT — ClassVar shared across ALL CognitiveAgent subclasses is wrong.** Each agent TYPE needs its own cache. The Bitcoin agent's cache shouldn't pollute the weather agent's cache.

Better approach: use a module-level dict keyed by `agent_type`:

```python
# Module-level cache: {agent_type: {hash: (decision, created_at, ttl)}}
_DECISION_CACHES: dict[str, dict[str, tuple[dict, float, float]]] = {}
_CACHE_HITS: dict[str, int] = {}
_CACHE_MISSES: dict[str, int] = {}
```

3. Add `_compute_cache_key()` method:

```python
def _compute_cache_key(self, observation: dict) -> str:
    """Compute a deterministic hash from instructions + observation."""
    # Sort dict keys for determinism
    obs_str = json.dumps(observation, sort_keys=True, default=str)
    key_material = f"{self.instructions}|{obs_str}"
    return hashlib.sha256(key_material.encode()).hexdigest()[:16]
```

4. Add `_get_cache_ttl()` method:

```python
def _get_cache_ttl(self) -> float:
    """Determine TTL based on agent instructions.
    
    Real-time/live data agents get short TTL.
    Static knowledge agents get long TTL.
    """
    if not self.instructions:
        return self._cache_ttl_seconds
    lower = self.instructions.lower()
    # Real-time indicators → short TTL
    if any(kw in lower for kw in ("real-time", "current", "live", "latest", "now", "price", "weather", "stock")):
        return 120.0  # 2 minutes
    # Static knowledge → long TTL
    if any(kw in lower for kw in ("translate", "define", "calculate", "convert", "summarize")):
        return 3600.0  # 1 hour
    return self._cache_ttl_seconds  # default 5 min
```

5. Modify `decide()` to check cache before LLM call:

```python
async def decide(self, observation: dict) -> dict:
    """Consult the LLM with instructions + observation.
    
    Decision Distillation (AD-272): checks in-memory cache before
    calling LLM. Cache hits return instantly (<1ms, $0).
    """
    if not self._llm_client:
        return {"action": "error", "reason": "No LLM client available"}

    # --- Decision cache lookup ---
    cache = _DECISION_CACHES.setdefault(self.agent_type, {})
    cache_key = self._compute_cache_key(observation)
    
    if cache_key in cache:
        decision, created_at, ttl = cache[cache_key]
        if time.monotonic() - created_at < ttl:
            # Cache hit — return without LLM call
            _CACHE_HITS[self.agent_type] = _CACHE_HITS.get(self.agent_type, 0) + 1
            logger.debug("Decision cache hit for %s (key=%s)", self.agent_type, cache_key[:8])
            return {**decision, "cached": True}
        else:
            # Expired — remove and proceed to LLM
            del cache[cache_key]

    _CACHE_MISSES[self.agent_type] = _CACHE_MISSES.get(self.agent_type, 0) + 1

    # --- LLM call (cache miss) ---
    user_message = self._build_user_message(observation)
    request = LLMRequest(
        prompt=user_message,
        system_prompt=self.instructions,
        tier=self._resolve_tier(),
    )
    response = await self._llm_client.complete(request)
    
    decision = {
        "action": "execute",
        "llm_output": response.content,
        "tier_used": response.tier,
    }

    # --- Store in cache ---
    ttl = self._get_cache_ttl()
    cache[cache_key] = (decision, time.monotonic(), ttl)
    
    # Evict oldest entries if cache exceeds 1000 per agent type
    if len(cache) > 1000:
        oldest_key = min(cache, key=lambda k: cache[k][1])
        del cache[oldest_key]

    return decision
```

6. Add class method for cache eviction (used by FeedbackEngine):

```python
@classmethod
def evict_cache_for_type(cls, agent_type: str, observation: dict | None = None) -> int:
    """Evict cache entries for an agent type.
    
    If observation provided, evict only the matching entry.
    If None, evict all entries for that agent type.
    Returns count of evicted entries.
    """
    cache = _DECISION_CACHES.get(agent_type, {})
    if not cache:
        return 0
    if observation is None:
        count = len(cache)
        cache.clear()
        return count
    # TODO: compute key and delete specific entry
    return 0
```

7. Add cache stats method (for introspection):

```python
@classmethod
def cache_stats(cls) -> dict[str, dict[str, int]]:
    """Return cache statistics per agent type."""
    stats = {}
    for agent_type, cache in _DECISION_CACHES.items():
        stats[agent_type] = {
            "entries": len(cache),
            "hits": _CACHE_HITS.get(agent_type, 0),
            "misses": _CACHE_MISSES.get(agent_type, 0),
        }
    return stats
```

### File: `src/probos/cognitive/feedback.py`

In `apply_execution_feedback()`, when feedback is negative, evict the decision cache for agents involved:

```python
# After trust/Hebbian updates for negative feedback:
from probos.cognitive.cognitive_agent import CognitiveAgent
for agent_type in agent_types_involved:
    CognitiveAgent.evict_cache_for_type(agent_type)
```

This is optional — do it if easy, skip if the import gets circular.

### NOT doing (keep scope small):

- KnowledgeStore persistence of the cache (future — needs serialization of decision dicts)
- Semantic similarity for cache keys (too expensive per-call — exact hash is good enough since the decomposer normalizes inputs)
- HXI display of cache metrics (future — `/designed` panel could show hit rate)

## Tests

### File: `tests/test_cognitive_agent.py`

Add these tests:

1. `test_decision_cache_hit` — call `decide()` twice with same observation, verify LLM called only once (check `_llm_client.call_count`)
2. `test_decision_cache_miss_different_observation` — call `decide()` with two different observations, verify LLM called twice
3. `test_decision_cache_ttl_expiry` — set short TTL, call `decide()`, wait/mock time past TTL, call again, verify LLM called twice
4. `test_decision_cache_key_includes_instructions` — two agents with different instructions but same observation get different cache entries
5. `test_cache_stats_reports_hits_misses` — verify `cache_stats()` reflects correct counts
6. `test_cache_eviction_on_overflow` — fill cache beyond 1000 entries, verify oldest evicted
7. `test_cached_response_has_cached_flag` — verify cache hits include `"cached": True` in the decision dict

Clear the module-level cache dicts in test setup to prevent cross-test contamination:
```python
@pytest.fixture(autouse=True)
def clear_caches():
    from probos.cognitive.cognitive_agent import _DECISION_CACHES, _CACHE_HITS, _CACHE_MISSES
    _DECISION_CACHES.clear()
    _CACHE_HITS.clear()
    _CACHE_MISSES.clear()
```

## PROGRESS.md

Update:
- Status line (line 3) test count
- Add AD-272 section before `## Active Roadmap`:

```
### AD-272: Decision Distillation — Deterministic Learning Loop

**Problem:** Every CognitiveAgent call made an LLM request even for identical repetitive queries. "Bitcoin price" 100 times = 100 LLM calls (2-5s, ~$1-5 total).

| AD | Decision |
|----|----------|
| AD-272 | In-memory decision cache in `CognitiveAgent.decide()`. Cache key: SHA256 of instructions + observation. Cache hit returns instantly (<1ms, $0) with `"cached": True` flag. TTL per entry — time-sensitive agents (price, weather) get 2min TTL, static knowledge (translate, calculate) gets 1hr. Module-level cache dict keyed by agent_type (each agent type has its own cache). 1000-entry cap per type with LRU eviction. Negative feedback evicts matching cache entries. Cache metrics (hits/misses) exposed via `cache_stats()` |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | Added `_DECISION_CACHES`, `_CACHE_HITS`, `_CACHE_MISSES` module-level dicts. `_compute_cache_key()`, `_get_cache_ttl()` methods. `decide()` checks cache before LLM, stores result after. `evict_cache_for_type()`, `cache_stats()` class methods. 1000-entry cap with oldest eviction |

NNNN/NNNN tests passing (+ 11 skipped). 7 new tests.
```

## Constraints

- Only touch `src/probos/cognitive/cognitive_agent.py`, `tests/test_cognitive_agent.py`, and `PROGRESS.md`
- Do NOT modify `feedback.py` (cache eviction from feedback is future work — avoid circular imports)
- Do NOT add KnowledgeStore persistence (future work)
- Do NOT use semantic similarity for cache keys — deterministic SHA256 hash only
- The `_DECISION_CACHES` dict MUST be module-level (not ClassVar) — each agent type gets its own cache namespace
- Cache hits MUST include `"cached": True` in the returned decision dict so callers can distinguish
- TTL for "real-time" agents MUST be ≤ 2 minutes (stale prices/weather are worse than an LLM call)
- Run tests after each edit: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- Report the final test count
