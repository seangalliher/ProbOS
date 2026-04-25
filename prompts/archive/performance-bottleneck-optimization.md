# Performance Bottleneck Analysis & Optimization (AD-289)

> **Context:** ProbOS currently runs 43 agents across 7 pools. As the system scales
> toward 100-1000 agents, several architectural bottlenecks will become critical.
> This prompt addresses the highest-impact optimizations to keep ProbOS efficient.
>
> **This is a research + recommendations prompt.** Do not implement all fixes. Instead,
> investigate each area, confirm the bottleneck exists, assess severity, and implement
> only the P0 fixes marked as "IMPLEMENT NOW". Add the rest to PROGRESS.md as roadmap items.

## Pre-read

Before starting, read these files to understand the current code:
- `src/probos/mesh/intent.py` — `IntentBus.broadcast()` (line ~78-86)
- `src/probos/substrate/registry.py` — `Registry.all()` (line ~61), `get_by_pool()` (line ~51)
- `src/probos/substrate/pool.py` — `healthy_agents` property (line ~57), `check_health()` (line ~115), `_health_loop()` (line ~168)
- `src/probos/consensus/shapley.py` — `shapley_values()` (line ~64-78)
- `src/probos/api.py` — `_safe_serialize()` (line ~565), `_broadcast_event()` (line ~583), `build_state_snapshot()` in runtime
- `src/probos/runtime.py` — `build_state_snapshot()` (line ~272), `submit_intent_with_consensus()` (line ~843)
- `src/probos/cognitive/hebbian.py` — weight storage and lookup
- `src/probos/substrate/event_log.py` — event logging mechanism
- `PROGRESS.md` line 2 — current test count

## P0: IMPLEMENT NOW — Critical at Scale

### Fix 1: Intent Bus Pre-Filtering

**Problem:** `IntentBus.broadcast()` fans out every intent to ALL subscribed agents. Each agent receives every intent and returns `None` to decline. At 1000 agents, this creates 1000 asyncio tasks per user request.

**File:** `src/probos/mesh/intent.py`

**Fix:** Build a reverse index mapping intent names to relevant agent IDs. Only create tasks for agents that can handle the intent.

1. Add `_intent_index: dict[str, set[str]]` to `IntentBus.__init__`
2. When agents subscribe, also register which intents they handle (from their `IntentDescriptor.intents` list)
3. Add `subscribe_for_intents(agent_id, handler, intent_names: list[str])` method
4. In `broadcast()`, look up `self._intent_index.get(intent.name, set())` and only create tasks for matching agents
5. Fall back to full broadcast if no index entry exists (backward compatibility)

**Also update:** `src/probos/runtime.py` — where agents are wired up (line ~2131), pass the agent's intent descriptors to the subscription call.

**Tests:**
1. Verify only matching agents receive a broadcast intent
2. Verify fallback to full broadcast for unknown intents
3. Verify unsubscribe removes agent from intent index

### Fix 2: Shapley Value Factorial Explosion Guard

**Problem:** `shapley_values()` computes over all permutations of a coalition. With `math.factorial(n)` at the core, pool sizes >10 will lock the CPU. At 12 agents: 479 million iterations. At 15: 1.3 trillion.

**File:** `src/probos/consensus/shapley.py`

**Fix:** Add a cap. If the coalition size exceeds a threshold (e.g., 10), switch to Monte Carlo approximation (sample random permutations) instead of exact enumeration.

```python
MAX_EXACT_SHAPLEY = 10

def shapley_values(agents, value_fn):
    if len(agents) > MAX_EXACT_SHAPLEY:
        return _approximate_shapley(agents, value_fn, samples=1000)
    return _exact_shapley(agents, value_fn)
```

**Tests:**
1. Exact Shapley still works for small coalitions (<=10)
2. Approximate Shapley returns reasonable values for larger coalitions
3. Values sum to approximately the grand coalition value (Shapley efficiency axiom)

### Fix 3: Registry.all() Caching

**Problem:** `Registry.all()` creates a new list from `dict.values()` on every call. Called from 11+ locations including the `/api/health` endpoint (polled every few seconds) and the DAG executor (per node execution).

**File:** `src/probos/substrate/registry.py`

**Fix:** Cache the list and invalidate on register/unregister.

```python
def __init__(self):
    self._agents: dict[AgentID, BaseAgent] = {}
    self._all_cache: list[BaseAgent] | None = None

def all(self) -> list[BaseAgent]:
    if self._all_cache is None:
        self._all_cache = list(self._agents.values())
    return self._all_cache

async def register(self, agent):
    # ... existing logic ...
    self._all_cache = None  # invalidate

async def unregister(self, agent_id):
    # ... existing logic ...
    self._all_cache = None  # invalidate
```

**Important:** Return a reference to the cached list. Callers should not mutate it. If any caller currently mutates the returned list, they need to be fixed.

**Tests:**
1. `all()` returns same list object on consecutive calls without registration changes
2. `all()` returns fresh list after register/unregister
3. Returned list reflects current state

## P1: ADD TO ROADMAP — Important but Not Urgent

### Roadmap Item: Pool Health Check Optimization

**Problem:** `healthy_agents` is a computed property that scans all agents in the pool on every access. Called from 15+ locations including the DAG executor (per node execution). Also, `check_health()` uses `list.remove()` inside a loop (O(P^2) worst case).

**Fixes to roadmap:**
- Cache `healthy_agents` list, invalidate on agent state change
- Replace `list.remove()` with batch rebuild in `check_health()`
- Stagger health check intervals across pools with random jitter
- Build `intent_name -> pool -> agent_id` index for DAG executor lookups

### Roadmap Item: WebSocket Delta Updates

**Problem:** `_safe_serialize()` does `json.dumps()` then `json.loads()` on every event (roundtrip serialization). `build_state_snapshot()` calls `all_weights_typed()` three times and `registry.all()` once per WebSocket connect. At 1000 agents, the initial snapshot is huge.

**Fixes to roadmap:**
- Remove the json.dumps/loads roundtrip — serialize once directly
- Cache `all_weights_typed()` result for short TTL within snapshot building
- Send delta updates (only changed agents) instead of full state on events
- Throttle event broadcast rate (batch events within a 100ms window)

### Roadmap Item: Event Log Write Batching

**Problem:** Event log commits to SQLite on every write. During a single intent submission with consensus, 16+ events fire (5 hebbian + 1 consensus + 10 trust updates), each triggering a DB commit.

**Fixes to roadmap:**
- Batch event log writes (flush every 100ms or every 10 events, whichever comes first)
- Use WAL mode for SQLite if not already enabled
- Consider append-only in-memory buffer with periodic flush

### Roadmap Item: Episodic Memory Query Optimization

**Problem:** `recent(k)` fetches from ChromaDB. At scale, full-table scans for "most recent" episodes become slow without proper indexing.

**Fixes to roadmap:**
- Add timestamp index to ChromaDB collection
- Cache recent episodes with TTL for repeated access (dream cycle + introspection)

## Run Tests

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

## Verification

After P0 fixes:
1. Run existing test suite — all tests pass
2. Intent broadcast only fans out to relevant agents (check with logging)
3. Shapley computation completes in <1s even with 20 agents in a coalition
4. `Registry.all()` returns cached list (verify with `id()` comparison)
5. Report final test count

## Update PROGRESS.md

- Update test count on line 2
- Add AD-289 section with P0 fixes implemented
- Add P1 roadmap items under a "Performance Optimization" section
- Note the analysis methodology and scaling targets (100-1000 agents)
