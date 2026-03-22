# BF-008: Dream Cycle Double-Replay After Dolphin Dreaming

## Problem

The micro-dream (Tier 1, "dolphin sleep") and full dream (Tier 2) both replay
episodes, causing double-strengthening of Hebbian weights.

**Micro-dream** runs every 10 seconds and incrementally replays new episodes as
they arrive (up to 10 per cycle), advancing `_last_consolidated_count`. By the
time the full dream runs (every 10 minutes when idle), micro-dream has already
replayed every episode. The full dream's Step 1 (`_replay_episodes` on the 50
most recent) then re-strengthens pathways that are already consolidated.

Observable in logs as static `replayed=50 strengthened=80` every 10 minutes,
even though no new episodes arrived — the same 50 episodes are re-replayed
every cycle.

## Root Cause

`dream_cycle()` always runs `_replay_episodes()` on the `replay_episode_count`
most recent episodes (line 93-99 in `dreaming.py`), regardless of whether
micro-dream already consolidated them. There is no coordination between the
two tiers.

## Fix: Composable Dream Cycle

Make `dream_cycle()` self-contained by having it **start with a micro-dream
flush**, then do maintenance-only operations. This way `dream_cycle()` is
always correct regardless of who calls it — the scheduler loop, shutdown,
Surgeon force_dream, or any future caller.

The biological metaphor holds: full dream = flush any remaining real-time
consolidation (micro-dream) + deep maintenance (pruning, trust, strategy).

### Changes to `dream_cycle()` in `src/probos/cognitive/dreaming.py`:

1. **Add `micro_dream()` call as Step 0** at the top of `dream_cycle()`. This
   flushes any episodes that arrived since the last micro-dream tick (up to 10s
   gap). The micro-dream cursor advances, so no episode is double-replayed.

   ```python
   async def dream_cycle(self) -> DreamReport:
       t_start = time.monotonic()

       # Step 0: Flush any un-consolidated episodes (compose with micro-dream)
       micro_report = await self.micro_dream()

       # Step 1 (replay) removed — micro_dream owns incremental consolidation

       episodes = await self.episodic_memory.recent(k=self.config.replay_episode_count)
       # ... rest of steps use episodes for trust/pre-warm/strategy/gaps
   ```

2. **Remove the old Step 1** (`_replay_episodes()` call on the fetched
   episodes). The micro-dream flush in Step 0 handles any remaining replay.

3. **Keep episodes fetch for maintenance steps** — Steps 3 (trust
   consolidation), 4 (pre-warm), 6 (strategy extraction), and 7 (gap
   prediction) all need the recent episodes list as input. Fetch episodes for
   these consumers but do NOT pass them through `_replay_episodes()`.

4. **Update `DreamReport`** — set `weights_strengthened` to the value returned
   by the micro-dream flush (from `micro_report["weights_strengthened"]`). This
   captures any last-moment consolidation that happened. If micro-dream found
   nothing new, this will be 0.

5. **Update `episodes_replayed`** in the report — set to
   `micro_report["episodes_replayed"]` to reflect only the genuinely new
   episodes that were replayed (not the full 50 re-replay).

6. **Remove the micro-dream cursor reset** at line 157-159
   (`self._last_consolidated_count = stats.get("total", 0)`). The micro-dream
   flush in Step 0 already advanced the cursor. No need for the full dream to
   interfere.

### No changes needed to callers:

Since `dream_cycle()` now starts with a micro-dream flush internally, **no
caller changes are required**:

- **Shutdown consolidation** (`src/probos/runtime.py`, line ~1131) — calls
  `dream_cycle()`, which now self-flushes. No change.
- **Surgeon force_dream** (`src/probos/agents/medical/surgeon.py`, line ~79) —
  calls `dream_cycle()`, which now self-flushes. No change.
- **DreamScheduler._do_dream()** (`src/probos/cognitive/dreaming.py`,
  line ~424) — calls `dream_cycle()`, which now self-flushes. No change.

This is the composability advantage: `dream_cycle()` is a complete,
self-contained operation.

### Update log message:

The `dream_cycle()` log line (line 149-154) should reflect the composed nature:
```python
logger.info(
    "dream-cycle: flushed=%d strengthened=%d pruned=%d trust_adjusted=%d "
    "strategies=%d gaps=%d",
    report.episodes_replayed,
    report.weights_strengthened,
    report.weights_pruned,
    report.trust_adjustments,
    report.strategies_extracted,
    report.gaps_predicted,
)
```

The key change: `flushed` (new micro-dream episodes only) replaces the old
`replayed` (redundant batch of 50). When idle with no new activity, this will
correctly show `flushed=0 strengthened=0` instead of the misleading
`replayed=50 strengthened=80`.

## Files to modify

- `src/probos/cognitive/dreaming.py` — `dream_cycle()` method, log message

## Files to read first

- `src/probos/cognitive/dreaming.py` — full file, understand both tiers
- `src/probos/runtime.py` — shutdown path (~line 1127-1139), confirm no change needed
- `src/probos/agents/medical/surgeon.py` — force_dream (~line 74-82), confirm no change needed
- `src/probos/config.py` — `DreamingConfig` (~line 161)
- `src/probos/types.py` — `DreamReport` dataclass

## Tests

Update tests in `tests/test_dreaming.py`:

1. **Verify `dream_cycle` calls `micro_dream` first** — mock `micro_dream`
   and confirm it is called once at the start of `dream_cycle()`.

2. **Verify `dream_cycle` does NOT call `_replay_episodes` directly** — mock
   `_replay_episodes` and confirm it is only called via the `micro_dream()`
   path, not separately by dream_cycle.

3. **Verify `dream_cycle` still runs maintenance** — confirm pruning, trust
   consolidation, pre-warming, strategy extraction, and gap prediction all
   still execute.

4. **Verify `DreamReport` reflects micro-dream flush** — after
   `dream_cycle()`, `episodes_replayed` should equal the micro-dream's count
   (not the full `replay_episode_count`). When no new episodes exist,
   `episodes_replayed` and `weights_strengthened` should be 0.

5. **Verify micro-dream cursor is not reset by full dream** — run micro-dream,
   then dream_cycle, then check `_last_consolidated_count` was not changed by
   dream_cycle (only by the embedded micro_dream call).

6. **Preserve existing tests** — all current dreaming tests must continue
   to pass.

## Acceptance criteria

- `dream_cycle()` starts with a `micro_dream()` flush — fully composable
- No caller changes needed (shutdown, Surgeon, scheduler all just call
  `dream_cycle()`)
- Full dream cycle no longer separately replays episodes
- Pruning, trust consolidation, pre-warming, strategy extraction, gap
  prediction all still work
- `DreamReport` accurately reflects new-only replay counts (not redundant 50)
- Log output shows `flushed=0 strengthened=0` when idle (not `replayed=50`)
- All existing tests pass
- New tests verify the composed behavior
