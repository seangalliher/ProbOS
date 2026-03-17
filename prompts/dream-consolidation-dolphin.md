# Dream Consolidation Improvements — Dolphin Sleep Model (AD-288)

> **Context:** ProbOS reports dream_consolidation_rate of 0.0% because the 5-minute
> idle threshold is never reached during interactive sessions. Dreams never trigger,
> so the system never learns from its own experience during a session.
>
> **Solution:** Adopt a "dolphin sleep" model — continuous micro-consolidation in the
> background, with periodic deep housekeeping during idle periods and a final flush
> at shutdown. Three tiers of dreaming, zero interruption to active conversations.

## Pre-read

Before starting, read these files to understand the current code:
- `src/probos/cognitive/dreaming.py` — `DreamingEngine` class (line ~24), `dream_cycle()` (line ~42), `_replay_episodes()` (line ~102), `_prune_weights()` (line ~140), `_consolidate_trust()` (line ~163), `DreamScheduler` (line ~243), `_monitor_loop()` (line ~317)
- `src/probos/config.py` — `DreamingConfig` defaults (line ~140)
- `src/probos/runtime.py` — dream scheduler wiring in `start()` (line ~637), `record_activity()` (line ~1086), `_on_post_dream()` (line ~1938), `_build_episode()` (line ~1987), `stop()` (line ~700)
- `src/probos/cognitive/emergent_detector.py` — `dream_consolidation_rate` metric (line ~529), `_dream_history` (line ~90)
- `src/probos/cognitive/episodic.py` — `recent()` method (line ~226)
- `PROGRESS.md` line 2 — current test count

## Design: Three-Tier Dreaming

### Tier 1: Micro-Dream (continuous, every 10s)
- Process only new episodes since last micro-dream
- Replay: strengthen/weaken Hebbian weights for those episodes only
- Lightweight: ~5 episodes per tick, O(episodes × outcomes), independent of agent count
- Runs continuously regardless of user activity — safe because it's <0.1ms
- Track a `_last_consolidated_episode_id` or `_consolidated_count` cursor to avoid replaying already-consolidated episodes

### Tier 2: Idle Dream (periodic, after 120s idle)
- Full dream cycle: replay + prune + trust consolidation + pre-warm analysis
- Reduce idle threshold from 300s to 120s in config defaults
- Only runs when the system has been inactive for 120s (existing idle detection)
- Includes housekeeping that doesn't belong in micro-dreams (pruning dead weights, trust batch adjustment)

### Tier 3: Shutdown Flush (on stop)
- Consolidate any remaining episodes since last micro-dream tick
- Log: `"Consolidating session memories..."` before, summary after
- Fast because Tier 1 handles most work continuously

## Step 1: Add Micro-Dream to DreamingEngine

**File:** `src/probos/cognitive/dreaming.py`

Add a new method `micro_dream()` to `DreamingEngine` that only does episode replay (no pruning, no trust consolidation, no pre-warm):

```python
async def micro_dream(self, since_index: int = 0) -> dict[str, Any]:
    """Lightweight consolidation of recent episodes only.

    Unlike dream_cycle(), this only replays new episodes to update
    Hebbian weights. Pruning and trust consolidation happen in the
    full idle dream. Returns a summary dict.
    """
    if not self._episodic_memory:
        return {"episodes_replayed": 0, "weights_strengthened": 0}

    episodes = await self._episodic_memory.recent(k=10)
    # Filter to only episodes we haven't consolidated yet
    new_episodes = [e for i, e in enumerate(episodes) if i >= since_index]

    strengthened, weakened = self._replay_episodes(new_episodes)
    return {
        "episodes_replayed": len(new_episodes),
        "weights_strengthened": strengthened,
        "weights_weakened": weakened,
    }
```

**Note:** The exact filtering mechanism depends on how episodes are indexed. Options:
- Use a monotonic counter from `episodic_memory.get_stats()["total"]`
- Track `self._last_micro_dream_count` and compare to current total
- Use timestamps if episodes have them

Pick whichever approach fits cleanly with the existing `EpisodicMemory` API. The key requirement is: **never replay the same episode twice in micro-dreams**.

## Step 2: Add Micro-Dream Loop to DreamScheduler

**File:** `src/probos/cognitive/dreaming.py`

Modify `DreamScheduler._monitor_loop()` to run micro-dreams every 10 seconds **in addition to** the existing idle-based full dream check:

```python
# New config field
micro_dream_interval_seconds: float = 10.0

# In _monitor_loop:
# Every tick (1s), check two things:
# 1. Has it been 10s since last micro-dream? -> micro_dream()
# 2. Has it been 120s idle + 600s since last full dream? -> dream_cycle()
```

Add a `_last_micro_dream_time` tracker. The micro-dream runs unconditionally (not gated by idle time) because it's < 0.1ms and safe during active use.

The full dream (`dream_cycle()`) keeps its idle gate but with the reduced threshold.

## Step 3: Reduce Idle Threshold

**File:** `src/probos/config.py`

Change the default `idle_threshold_seconds` from 300.0 to 120.0:

```python
idle_threshold_seconds: float = 120.0  # was 300.0
```

## Step 4: Add Shutdown Dream

**File:** `src/probos/runtime.py`

In `stop()`, before episodic memory is shut down, run a final consolidation:

```python
# In stop(), before self.episodic_memory.stop():
if self.dream_scheduler and self.episodic_memory:
    logger.info("Consolidating session memories...")
    try:
        report = await self.dream_scheduler._engine.dream_cycle()
        logger.info(
            "Session consolidation complete: replayed=%d strengthened=%d pruned=%d",
            report.episodes_replayed,
            report.weights_strengthened,
            report.weights_pruned,
        )
    except Exception as e:
        logger.warning("Shutdown consolidation failed: %s", e)
```

Use `dream_cycle()` (not `micro_dream()`) for shutdown — this is the last chance to do pruning and trust consolidation.

## Step 5: Fix Episode agent_ids Population

**File:** `src/probos/runtime.py`

Check `_build_episode()` (line ~1987). The `agent_ids` extraction at lines 2017-2022 depends on execution results carrying `agent_id` attributes. Verify this works:

```python
agent_ids = []
for r in node_result.get("results", []):
    if hasattr(r, "agent_id"):
        agent_ids.append(r.agent_id)
```

If `results` contains dicts (not objects with attributes), fix to:
```python
    aid = r.get("agent_id") if isinstance(r, dict) else getattr(r, "agent_id", None)
    if aid:
        agent_ids.append(aid)
```

This ensures replay has agent_ids to strengthen/weaken. Without this, micro-dreams run but do nothing.

## Step 6: Dream Report Logging

**File:** `src/probos/cognitive/dreaming.py`

Add a one-line log summary after each dream tier:

- Micro-dream: `logger.debug("micro-dream: replayed=%d strengthened=%d", ...)`
- Full dream: `logger.info("dream-cycle: replayed=%d strengthened=%d pruned=%d trust_adjusted=%d", ...)`

Use `debug` for micro-dreams (too frequent for info level) and `info` for full dreams.

## Step 7: EmergentDetector Early-Session Guard

**File:** `src/probos/cognitive/emergent_detector.py`

The cooperation cluster detector flags initial routing patterns as "emergent cooperation" after just 2-3 interactions. Add a minimum episode threshold before cooperation detection fires.

Find the cooperation detection logic and add a guard:

```python
# Don't detect cooperation clusters until we have enough data
if total_episodes < 10:
    return []  # Skip cooperation anomaly detection early in session
```

This prevents the 16 false-positive cooperation anomalies ProbOS reported.

## Step 8: Update EmergentDetector dream_consolidation_rate

**File:** `src/probos/cognitive/emergent_detector.py`

The `get_snapshot()` method only reads from `_dream_history` (populated by full dreams). With Tier 1 micro-dreams running continuously, the metric should also account for micro-dream activity.

Option A: Have the `DreamScheduler` call `emergent_detector.analyze()` after micro-dreams too (with a lightweight report).

Option B: Track a separate micro-dream counter and include it in the snapshot.

Pick whichever is simpler. The goal is that `dream_consolidation_rate > 0` when micro-dreams have been running, even if no full dream has triggered.

## Run Tests

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

## Verification

After all changes:
1. Start ProbOS, send 3-4 requests
2. Check logs for `micro-dream: replayed=...` entries appearing every ~10s
3. Wait 2+ minutes idle — verify a full `dream-cycle:` log entry appears
4. Stop ProbOS — verify `"Consolidating session memories..."` appears at shutdown
5. Run `/introspect emergent` — verify `dream_consolidation_rate > 0`
6. Verify no cooperation anomalies appear before 10 episodes
7. All existing tests pass
8. Report final test count

## Update PROGRESS.md

- Update test count on line 2
- Add AD-288 section noting the dolphin sleep model for continuous consolidation
- Note the three tiers: micro-dream, idle dream, shutdown flush
