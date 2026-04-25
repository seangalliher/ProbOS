# BF-027: Agent Memory Recall Ineffective — Threshold + Missing Fallback + Mock Gap

## Symptom

Agents cannot recall their own Ward Room postings or past 1:1 conversations with the Captain, even though episodes are being stored correctly. The Counselor was asked "Can you recall posting anything in the Ward Room?" and answered "I don't have any record of posting in the Ward Room" — despite having multiple Ward Room posts in its episodic memory.

## Root Cause (Three Issues)

### Issue A: Relevance threshold too strict for conversational queries

`recall_for_agent()` (episodic.py line 208) applies the **0.7 cosine similarity threshold**. The Captain's conversational query "Can you recall posting anything in the Ward Room?" is embedded and compared against stored episode text like `[Proactive thought] Counselor: I've noticed increased trust variance across departments...`. The semantic distance between a meta-question about memory and the actual content of a past thought is large — the cosine similarity likely falls below 0.7, so the episode is filtered out. The threshold works for system queries (proactive loop asking `"recent activity"`) but fails for natural conversational queries from the Captain.

### Issue B: No fallback when semantic recall returns empty

When `recall_for_agent()` returns `[]` (either no episodes at all or none clearing the threshold), `_recall_relevant_memories()` simply returns the observation unchanged. The agent gets zero memory context. There should be a fallback: if semantic recall returns nothing, retrieve the agent's N most recent episodes by timestamp — give the agent *something* to work with.

The infrastructure for this exists: `EpisodicMemory.recent()` returns episodes sorted by timestamp. But there's no `recent_for_agent()` that filters by agent_id. And `_recall_relevant_memories()` doesn't attempt any fallback.

### Issue C: MockEpisodicMemory missing `recall_for_agent()`

`MockEpisodicMemory` (episodic_mock.py) has `recall()`, `recall_by_intent()`, `recent()`, `store()`, `seed()`, `start()`, `stop()`, `get_stats()` — but **no `recall_for_agent()`**. Any test code path that reaches `self._runtime.episodic_memory.recall_for_agent(...)` with a MockEpisodicMemory will raise `AttributeError`. The `except Exception: pass` in `_recall_relevant_memories()` silently swallows it, so the agent proceeds without memory — masking the bug in tests.

## Fix

### Fix A: Lower threshold for conversational recall (episodic.py)

**File:** `src/probos/cognitive/episodic.py`

In `recall_for_agent()` (line 187), use a **separate, lower threshold** for agent-scoped recall. The sovereign shard filter already limits results to the correct agent — we can afford a wider semantic net.

Change line 208 from:
```python
if similarity < self.relevance_threshold:
```
To:
```python
# BF-027: Use a relaxed threshold for agent-scoped recall.
# The sovereign shard filter (agent_ids) already constrains results.
# Conversational queries from the Captain ("what did you post?") are
# semantically distant from stored episode text — 0.7 filters too aggressively.
agent_recall_threshold = min(self.relevance_threshold, 0.3)
if similarity < agent_recall_threshold:
```

**Rationale:** 0.3 is permissive but not zero. The sovereign shard filter prevents cross-agent leakage. We retrieve `k * 5` candidates and take the top `k` by ChromaDB's ranked ordering — the most relevant episodes still come first.

### Fix B: Add `recent_for_agent()` to EpisodicMemory and MockEpisodicMemory

**File:** `src/probos/cognitive/episodic.py`

Add after `recall_for_agent()` (after line 227):

```python
async def recent_for_agent(self, agent_id: str, k: int = 5) -> list[Episode]:
    """BF-027: Return the k most recent episodes for a specific agent.

    Timestamp-based fallback when semantic recall returns nothing.
    No relevance threshold — just the most recent experiences.
    """
    if not self._collection:
        return []
    count = self._collection.count()
    if count == 0:
        return []

    result = self._collection.get(
        include=["metadatas", "documents"],
    )
    if not result or not result["ids"]:
        return []

    # Filter to this agent's sovereign shard, sort by timestamp
    agent_episodes: list[tuple[str, dict, str]] = []
    for i, doc_id in enumerate(result["ids"]):
        metadata = result["metadatas"][i] if result["metadatas"] else {}
        agent_ids_json = metadata.get("agent_ids_json", "[]")
        try:
            agent_ids = json.loads(agent_ids_json)
        except (json.JSONDecodeError, TypeError):
            agent_ids = []
        if agent_id in agent_ids:
            document = result["documents"][i] if result["documents"] else ""
            agent_episodes.append((doc_id, metadata, document))

    # Sort by timestamp descending (most recent first)
    agent_episodes.sort(key=lambda x: x[1].get("timestamp", 0), reverse=True)

    return [
        self._metadata_to_episode(doc_id, metadata, document)
        for doc_id, metadata, document in agent_episodes[:k]
    ]
```

**File:** `src/probos/cognitive/episodic_mock.py`

Add after `recall()` (after line 86):

```python
async def recall_for_agent(self, agent_id: str, query: str, k: int = 5) -> list[Episode]:
    """BF-027: Agent-scoped recall with keyword matching."""
    query_tokens = _tokenize(query)
    scored: list[tuple[float, Episode]] = []
    for ep in self._episodes:
        if agent_id not in ep.agent_ids:
            continue
        if not query_tokens:
            scored.append((0.0, ep))
            continue
        ep_tokens = _tokenize(ep.user_input)
        if not ep_tokens:
            continue
        overlap = len(query_tokens & ep_tokens)
        score = overlap / max(len(query_tokens), len(ep_tokens))
        scored.append((score, ep))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [ep for _, ep in scored[:k]]

async def recent_for_agent(self, agent_id: str, k: int = 5) -> list[Episode]:
    """BF-027: Most recent episodes for a specific agent."""
    agent_eps = [ep for ep in self._episodes if agent_id in ep.agent_ids]
    return list(reversed(agent_eps[-k:]))
```

### Fix C: Fallback in `_recall_relevant_memories()` (cognitive_agent.py)

**File:** `src/probos/cognitive/cognitive_agent.py`

In `_recall_relevant_memories()`, after the semantic recall call, add a fallback to `recent_for_agent()` when semantic recall returns empty:

Find the block that calls `recall_for_agent` and builds `recent_memories`. Replace:

```python
        episodes = await self._runtime.episodic_memory.recall_for_agent(
            self.id, query, k=3
        )
        if episodes:
            observation["recent_memories"] = [
                {
                    "input": ep.user_input[:200] if ep.user_input else "",
                    "reflection": ep.reflection[:200] if ep.reflection else "",
                }
                for ep in episodes
            ]
```

With:

```python
        episodes = await self._runtime.episodic_memory.recall_for_agent(
            self.id, query, k=3
        )

        # BF-027: Fallback to recent episodes when semantic recall returns nothing
        if not episodes and hasattr(self._runtime.episodic_memory, 'recent_for_agent'):
            episodes = await self._runtime.episodic_memory.recent_for_agent(
                self.id, k=3
            )

        if episodes:
            observation["recent_memories"] = [
                {
                    "input": ep.user_input[:200] if ep.user_input else "",
                    "reflection": ep.reflection[:200] if ep.reflection else "",
                }
                for ep in episodes
            ]
```

## Tests

**File:** `tests/test_cognitive_agent.py` — Add to existing test classes.

### Test 1: MockEpisodicMemory.recall_for_agent filters by agent_id
```
Store 3 episodes — 2 for agent-A, 1 for agent-B.
Call recall_for_agent("agent-A", "test query").
Assert only agent-A's episodes are returned.
```

### Test 2: MockEpisodicMemory.recent_for_agent returns most recent by agent
```
Store 5 episodes for agent-A with incrementing timestamps.
Call recent_for_agent("agent-A", k=2).
Assert returns 2 most recent episodes (by insertion order).
```

### Test 3: EpisodicMemory.recent_for_agent filters by agent sovereign shard
```
If ChromaDB tests are feasible (check existing patterns), test real EpisodicMemory.
Otherwise, test via MockEpisodicMemory: store episodes for 2 agents, call recent_for_agent for one, assert only that agent's episodes returned.
```

### Test 4: Recall fallback fires when semantic recall returns empty
```
Create a CognitiveAgent with mock runtime. Mock recall_for_agent() to return [].
Mock recent_for_agent() to return 2 episodes.
Send a direct_message intent.
Assert recent_for_agent() was called (fallback fired).
Assert observation contains "recent_memories" with 2 entries.
```

### Test 5: Recall fallback does NOT fire when semantic recall returns results
```
Create a CognitiveAgent with mock runtime. Mock recall_for_agent() to return 2 episodes.
Send a direct_message intent.
Assert recent_for_agent() was NOT called (no fallback needed).
```

### Test 6: Lower threshold returns results that 0.7 would filter
```
This test validates the threshold fix. If testing with real ChromaDB:
Store an episode with user_input "[Proactive thought] Bones: observed increased pool churn".
Call recall_for_agent with query "What have you been thinking about?".
Assert the episode IS returned (would have been filtered at 0.7).
If ChromaDB tests aren't feasible, skip — the threshold change is a config-level fix.
```

## Constraints

- All fallback/recall operations are still wrapped in try/except — non-critical, never blocks the cognitive lifecycle.
- The `recent_for_agent()` fallback uses `hasattr` guard so it's backward-compatible with older EpisodicMemory instances.
- `recall_for_agent()` threshold is lowered at the method level (not globally) — `recall()` still uses the original 0.7 threshold for system queries.
- MockEpisodicMemory `recall_for_agent()` does NOT apply a threshold — it returns all matching episodes ranked by keyword overlap. This matches the mock's existing design (simple, deterministic, no false negatives in tests).
- Episode ordering in `recent_for_agent()` is by timestamp descending (most recent first), consistent with `recent()`.

## Run

```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_cognitive_agent.py -x -v 2>&1 | tail -40
```

Broader validation (ensure no regressions in episodic memory):
```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/ -x -v -k "episodic or cognitive_agent or memory" 2>&1 | tail -40
```
