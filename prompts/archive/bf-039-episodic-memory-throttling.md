# BF-039: Episodic Memory Flooding — Throttling & Deduplication

## Problem

After a reset, agents (especially Medical crew like Bones) accumulate hundreds of episodic memories within hours. Bones hit 730 episodes in under 24 hours. The system has no meaningful guards against episode volume — only a 100,000 cap with oldest-eviction.

## Root Causes

1. **Double episode creation per proactive thought.** When an agent has a proactive thought and posts it to the Ward Room, TWO episodes are created for the same cognitive event:
   - `proactive.py` line ~339 stores an episode via the proactive path
   - `ward_room.py` line ~885 stores another episode when `_post_to_ward_room()` creates the thread
   - Math: every 5 minutes per agent × 2 episodes = 576+ episodes/day minimum

2. **Ward Room bypasses `should_store()`.** `ward_room.py` lines ~885 (thread creation) and ~1082 (reply creation) call `episodic.store()` directly without passing through the `should_store()` selective encoding gate.

3. **No per-agent rate limiter.** There is no check like "this agent already stored N episodes in the last hour."

4. **No content-based deduplication.** Every `Episode` gets a fresh UUID on construction (`types.py`), so `upsert()` never deduplicates. Two episodes with identical text but different UUIDs are both stored.

5. **Duplicate `count_for_agent()` method.** Defined twice in `episodic.py` (lines ~278 and ~401). The second definition shadows the first. Both are O(N) over all episodes in the collection.

6. **No cold-start dampening for episodes.** BF-034 added cold-start suppression for trust anomalies (5-minute window), but no equivalent exists for episode creation rate.

## Fix Specification

### Fix 1: Deduplicate proactive + Ward Room episode path

**File:** `src/probos/proactive.py`

In `_think_for_agent()`, after a successful proactive thought that is posted to the Ward Room via `_post_to_ward_room()`, do NOT also store a separate proactive episode. The Ward Room will store its own episode for the thread creation.

- Find the episode creation at line ~339 (the "successful proactive thought" path)
- Add a guard: if the thought was posted to Ward Room (check the `_post_to_ward_room` return or a flag), skip the proactive episode storage
- The `[Proactive thought -- no response]` path (line ~257) already gets filtered by `should_store()`, so leave it alone

### Fix 2: Route Ward Room episodes through `should_store()`

**File:** `src/probos/ward_room.py`

- At line ~885 (thread creation episode) and line ~1082 (reply creation episode), wrap the `store()` call with a `should_store()` check
- Import or access `should_store()` from episodic memory
- This ensures Ward Room episodes respect the same selective encoding gate as other episode sources

### Fix 3: Per-agent episode rate limiter

**File:** `src/probos/cognitive/episodic.py`

Add a rate limiter to `store()`:

```python
# Configuration
MAX_EPISODES_PER_HOUR = 20  # per agent, configurable

def store(self, episode: Episode) -> None:
    # ... existing should_store check ...

    # Rate limit: max N episodes per agent per rolling hour
    if self._is_rate_limited(episode):
        logger.debug("Episode rate-limited for agent %s", episode.agent_ids)
        return

    # ... existing upsert logic ...

def _is_rate_limited(self, episode: Episode) -> bool:
    """Check if agent has exceeded episode rate limit in the last hour."""
    if not episode.agent_ids:
        return False
    agent_id = episode.agent_ids[0]
    one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    # Query recent episodes for this agent
    recent = self._collection.get(
        where={"timestamp": {"$gte": one_hour_ago}},
    )
    # Count episodes belonging to this agent
    count = 0
    for meta in (recent.get("metadatas") or []):
        aids = meta.get("agent_ids_json", "[]")
        if agent_id in aids:
            count += 1
    return count >= self.MAX_EPISODES_PER_HOUR
```

Make `MAX_EPISODES_PER_HOUR` configurable — add it to `EpisodicMemoryConfig` in `config.py` if one exists, otherwise as a class attribute with a sensible default (20).

### Fix 4: Content similarity gate

**File:** `src/probos/cognitive/episodic.py`

In `store()`, before upserting, check if a very similar episode from the same agent was stored recently:

```python
SIMILARITY_WINDOW_MINUTES = 30
SIMILARITY_THRESHOLD = 0.8  # Jaccard word-level

def _is_duplicate_content(self, episode: Episode) -> bool:
    """Check if a very similar episode was stored recently for same agent."""
    if not episode.agent_ids or not episode.text:
        return False
    agent_id = episode.agent_ids[0]
    window_start = (datetime.now(timezone.utc) - timedelta(minutes=self.SIMILARITY_WINDOW_MINUTES)).isoformat()
    recent = self._collection.get(
        where={"timestamp": {"$gte": window_start}},
    )
    episode_words = set(episode.text.lower().split())
    for i, meta in enumerate(recent.get("metadatas") or []):
        if agent_id not in meta.get("agent_ids_json", "[]"):
            continue
        doc = (recent.get("documents") or [])[i] if recent.get("documents") else ""
        if not doc:
            continue
        existing_words = set(doc.lower().split())
        intersection = episode_words & existing_words
        union = episode_words | existing_words
        if union and len(intersection) / len(union) >= self.SIMILARITY_THRESHOLD:
            return True
    return False
```

Add the `_is_duplicate_content()` check in `store()` after the rate limit check. Log when dedup fires.

### Fix 5: Remove duplicate `count_for_agent()`

**File:** `src/probos/cognitive/episodic.py`

- There are TWO definitions of `count_for_agent()` (around lines ~278 and ~401)
- The second one shadows the first
- Remove the duplicate (keep whichever is more correct/complete)
- Verify nothing depends on the specific line location

### Fix 6: Cold-start episode dampening

**File:** `src/probos/proactive.py`

During the cold-start period (first 10 minutes after reset, detectable via `runtime._cold_start` or by checking if the ship was commissioned recently), apply a 3x multiplier to the per-agent proactive cooldown:

- Normal cooldown: 300s (5 min) → cold-start cooldown: 900s (15 min)
- This is the same pattern as the existing "free-form 3x cooldown" (line ~191) but applied to ALL proactive thinks during cold-start, not just free-form
- The cold-start window should be configurable (default 600 seconds = 10 minutes)
- After the window expires, restore normal cooldown behavior

## Testing

Add tests in the appropriate test files:

### `tests/test_episodic.py` (or wherever episodic tests live)

1. **test_rate_limiter_blocks_excess_episodes** — Store MAX+1 episodes for the same agent within an hour window. Assert the last one is rejected.
2. **test_rate_limiter_allows_different_agents** — Store MAX episodes for agent A, then store one for agent B. Assert agent B's episode is accepted.
3. **test_rate_limiter_allows_after_window** — Store MAX episodes, advance time past the window, store another. Assert accepted.
4. **test_content_similarity_dedup** — Store an episode, then store a near-identical episode (>0.8 Jaccard) for the same agent within the window. Assert rejected.
5. **test_content_similarity_allows_different_content** — Store an episode, then store a substantially different episode. Assert accepted.
6. **test_content_similarity_allows_different_agent** — Store an episode for agent A, then identical text for agent B. Assert accepted (different agents).
7. **test_count_for_agent_single_definition** — Verify `count_for_agent` works correctly (basic correctness after dedup removal).

### `tests/test_proactive.py` (or equivalent)

8. **test_proactive_no_double_episode_on_wr_post** — Mock a proactive think that posts to Ward Room. Assert only ONE episode is created (from WR), not two.
9. **test_cold_start_dampening_extends_cooldown** — During cold-start, verify the cooldown is 3x normal.
10. **test_cold_start_dampening_expires** — After cold-start window, verify normal cooldown resumes.

### `tests/test_ward_room.py` (or equivalent)

11. **test_ward_room_episode_respects_should_store** — Create a Ward Room thread with content that `should_store()` would reject. Assert no episode stored.
12. **test_ward_room_episode_stores_when_should_store_passes** — Create a Ward Room thread with valid content. Assert episode stored normally.

## Files to Modify

| File | Changes |
|------|---------|
| `src/probos/cognitive/episodic.py` | Rate limiter, content similarity gate, remove duplicate `count_for_agent()` |
| `src/probos/proactive.py` | Deduplicate proactive+WR episode path, cold-start dampening |
| `src/probos/ward_room.py` | Route episode storage through `should_store()` |
| `src/probos/config.py` | Add rate limit config if `EpisodicMemoryConfig` exists |

## Acceptance Criteria

- [ ] No double episodes from proactive thought + Ward Room post for the same event
- [ ] Ward Room episodes pass through `should_store()` gate
- [ ] Per-agent rate limiter: max 20 episodes/hour/agent (configurable)
- [ ] Content similarity dedup: >0.8 Jaccard within 30-min window blocked
- [ ] Single `count_for_agent()` definition (no shadowing)
- [ ] Cold-start episode dampening: 3x cooldown for first 10 minutes
- [ ] 12 new tests, all passing
- [ ] Full test suite green (3569+ pytest, 118 vitest)
- [ ] After fix: a fresh reset should produce <50 episodes per agent in the first hour (down from 100+)
