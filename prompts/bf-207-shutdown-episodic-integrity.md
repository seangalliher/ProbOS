# BF-207: Shutdown Race Condition Causes Episodic Memory Hash Mismatch

## Overview

Fix a race condition where the 5-second shutdown timeout in `__main__.py:366` expires before `episodic_memory.stop()` runs, leaving ChromaDB improperly closed. On restart, affected episodes have metadata that no longer matches their stored content hash, producing warnings like:

```
Episode 251209b5 hash mismatch (v2): stored=d26c3f50e3a4 recomputed=e6fdef22ef7f
```

This has been observed twice across restarts. Root cause: the shutdown sequence budget is exhausted by earlier operations (1s grace period + up to 5s dream_cycle timeout + ~20 service stop operations), so `episodic_memory.stop()` at `shutdown.py:366` is never reached. `os._exit(0)` kills the process, and ChromaDB's `client.close()` never executes.

## Root Cause Analysis

### The Timing Budget Problem

`__main__.py:366` enforces a hard 5-second timeout on the entire `runtime.stop()` call:
```python
await asyncio.wait_for(runtime.stop(...), timeout=5)
```
On timeout → `os._exit(0)` at line 374 — hard process kill.

Inside `shutdown.py`, the budget is consumed by:
1. **Line 85:** `asyncio.sleep(1)` — 1s grace period
2. **Lines 96–265:** ~20 service stop operations (ACM, SIF, initiative, proactive loop, Ward Room, journals, stores, etc.)
3. **Line 272:** `asyncio.wait_for(dream_cycle(), timeout=5.0)` — up to **5s** dream timeout
4. **Lines 287–345:** Working memory freeze, pools stop, knowledge store flush, mesh stop
5. **Line 366:** `episodic_memory.stop()` ← often NEVER reached

The dream_cycle timeout (5s) alone can consume the entire shutdown budget. After 1s grace + a few service stops + dream_cycle, the 5s global timeout fires.

### Prior Art (same root cause family)

- **BF-135/BF-137/BF-141:** Session record write moved to top of shutdown because `os._exit(0)` was killing the process before it ran. Same race, different victim.
- **BF-065:** Stasis detection broken because shutdown timeout canceled `stop()` before lifecycle persistence.
- **BF-099:** WAL mode + concurrency fixes for trust engine — established the PRAGMA patterns.

All four prior BFs demonstrate that the 5-second shutdown budget is insufficient for the full sequence. BF-207 is the episodic memory instance of this systemic issue.

## Fix (Three Parts)

### Part 1: Move `episodic_memory.stop()` Earlier in Shutdown

**Rationale:** Nothing between pools stop (`shutdown.py:308`) and the current `episodic_memory.stop()` position (`shutdown.py:366`) writes to episodic memory. Knowledge store persistence writes trust/hebbian/manifest/workflows — not episodes. Mesh service stops don't touch episodes. The dream_cycle already ran before pools stop.

Move `episodic_memory.stop()` from its current position (line 366–368) to immediately after pools stop and working memory freeze (after line 308). This ensures ChromaDB is properly closed early in the shutdown sequence, well within the 5s budget.

**In `shutdown.py`, after the pools stop block (line 308: `runtime.pools.clear()`):**

Add:
```python
# BF-207: Close episodic memory (ChromaDB) early — nothing below writes episodes,
# and the 5s __main__.py shutdown timeout often expires before reaching the
# original position (line 366+). Without client.close(), ChromaDB's internal
# state may not finalize, causing hash mismatches on restart.
if runtime.episodic_memory:
    await runtime.episodic_memory.stop()
```

Remove the old block at the current position (around line 366–368):
```python
# Stop episodic memory  ← DELETE
if runtime.episodic_memory:  ← DELETE
    await runtime.episodic_memory.stop()  ← DELETE
```

Also move the eviction audit log stop (`_eviction_audit.stop()`, currently lines 370–374) to right after the new episodic memory stop, since it's a companion service.

### Part 2: Reduce Dream Cycle Shutdown Timeout

**In `shutdown.py`, line 272:**

Change:
```python
timeout=5.0,  # Don't let consolidation block shutdown
```

To:
```python
timeout=2.0,  # BF-207: Reduced from 5s — must leave budget for cleanup within __main__'s 5s limit
```

Update the timeout warning message at line 283:
```python
logger.warning("Shutdown consolidation timed out (2s limit) — partial consolidation completed")
```

**Rationale:** Dream consolidation is best-effort at shutdown. Partial consolidation is fine — episodes are already stored, dream just updates Hebbian/trust weights. The micro_dream in the periodic flush handles incremental consolidation during normal operation. 2s is generous for a single dream pass.

### Part 3: Auto-Heal Current-Version Hash Mismatches

Currently, `_verify_episode_hash()` at `episodic.py:495` only auto-heals episodes with `_hash_v < _HASH_VERSION`. Current-version mismatches just log a WARNING and move on. After this fix, auto-heal should repair current-version mismatches too, since the shutdown race is the known cause.

**In `episodic.py`, function `_verify_episode_hash()` (around line 492):**

Replace the existing mismatch handling block:
```python
    if recomputed != stored_hash:
        # Auto-heal: episodes stored with older normalization have stale hashes.
        stored_v = metadata.get("_hash_v", 0) if metadata else 0
        if stored_v < _HASH_VERSION and collection:
            try:
                updated_meta = dict(metadata)
                updated_meta["content_hash"] = recomputed
                updated_meta["_hash_v"] = _HASH_VERSION
                collection.update(
                    ids=[episode.id],
                    metadatas=[updated_meta],
                )
                logger.info(
                    "AD-541e: Auto-healed hash v%d->v%d for episode %s",
                    stored_v, _HASH_VERSION, episode.id[:8],
                )
                return True
            except Exception:
                logger.debug("Auto-heal failed for %s", episode.id[:8], exc_info=True)
        # Genuine mismatch on a current-version episode — log warning
        logger.warning(
            "Episode %s hash mismatch (v%d): stored=%s recomputed=%s",
            episode.id[:8] if episode.id else "unknown",
            stored_v, stored_hash[:12], recomputed[:12],
        )
        return False
```

With:
```python
    if recomputed != stored_hash:
        stored_v = metadata.get("_hash_v", 0) if metadata else 0
        # Auto-heal: update stale hash from version upgrade OR shutdown race (BF-207).
        # Shutdown can leave ChromaDB in a state where metadata doesn't match
        # the hash computed at store time. The data in ChromaDB is authoritative
        # (it's what will be used), so recompute the hash to match.
        if collection and metadata:
            try:
                updated_meta = dict(metadata)
                updated_meta["content_hash"] = recomputed
                updated_meta["_hash_v"] = _HASH_VERSION
                collection.update(
                    ids=[episode.id],
                    metadatas=[updated_meta],
                )
                if stored_v < _HASH_VERSION:
                    logger.info(
                        "AD-541e: Auto-healed hash v%d->v%d for episode %s",
                        stored_v, _HASH_VERSION, episode.id[:8],
                    )
                else:
                    logger.warning(
                        "BF-207: Repaired hash mismatch for episode %s "
                        "(likely shutdown race — stored=%s recomputed=%s)",
                        episode.id[:8], stored_hash[:12], recomputed[:12],
                    )
                return True
            except Exception:
                logger.debug("Auto-heal failed for %s", episode.id[:8], exc_info=True)
        # No collection available — can't heal, log warning only
        logger.warning(
            "Episode %s hash mismatch (v%d): stored=%s recomputed=%s",
            episode.id[:8] if episode.id else "unknown",
            stored_v, stored_hash[:12], recomputed[:12],
        )
        return False
```

**Key difference:** Auto-heal now runs for ALL hash mismatches when `collection` is available, not just version upgrades. Current-version mismatches log at WARNING level with "BF-207" attribution. The stored data is treated as authoritative — the hash is updated to match the data, not the other way around.

## Files Modified

| File | Change |
|------|--------|
| `src/probos/startup/shutdown.py` | Move `episodic_memory.stop()` + eviction audit stop after pools stop; reduce dream_cycle timeout 5s→2s |
| `src/probos/cognitive/episodic.py` | Extend auto-heal to repair current-version hash mismatches |

## Tests

Add tests in `tests/test_bf207_shutdown_episodic_integrity.py`:

1. **`test_auto_heal_current_version_mismatch`** — Episode with `_hash_v=2` but wrong `content_hash`. Verify `_verify_episode_hash()` auto-heals and updates ChromaDB.
2. **`test_auto_heal_old_version_still_works`** — Episode with `_hash_v=1`. Verify existing auto-heal path unchanged.
3. **`test_auto_heal_no_collection`** — Mismatch with `collection=None`. Verify returns False, logs warning, no crash.
4. **`test_auto_heal_update_failure`** — Mock `collection.update()` to raise. Verify graceful degradation (returns False, logs debug).
5. **`test_shutdown_episodic_stop_before_knowledge_store`** — Mock runtime with episodic_memory. Run `shutdown()`. Verify `episodic_memory.stop()` is called BEFORE `_knowledge_store.flush()`.
6. **`test_shutdown_dream_cycle_timeout_reduced`** — Verify dream_cycle uses 2s timeout (not 5s). Mock dream_cycle to sleep forever, verify TimeoutError within ~2s.
7. **`test_auto_heal_preserves_episode_data`** — After auto-heal, verify episode can be recalled and all fields match original (heal changes only content_hash and _hash_v, not data).
8. **`test_shutdown_eviction_audit_stops_with_episodic`** — Verify eviction audit stop moved alongside episodic memory stop.

## Engineering Principles Compliance

- **Fail Fast:** Auto-heal is log-and-degrade — logs WARNING, heals the data, doesn't crash. No `except Exception: pass`. Each exception handler has a clear action (heal attempt → fallback to warning).
- **Defense in Depth:** Three-layer fix — (1) move stop earlier prevents the race, (2) reduced timeout prevents budget exhaustion, (3) auto-heal catches any remaining cases.
- **Single Responsibility:** No new classes or abstractions. Changes are minimal and scoped to the two affected modules.
- **DRY:** Auto-heal logic refactored to handle both version upgrade and shutdown race in one path, differentiated only by log message.
- **Law of Demeter:** No new private member access. All changes use existing public APIs (`episodic_memory.stop()`, `collection.update()`).

## Absorbs / Relates To

- **AD-541e:** Episode content hashing (the system being protected)
- **BF-135/137/141:** Prior shutdown race fixes (same root cause family — session record)
- **BF-065:** Shutdown timeout causing stale state (same category)
- **BF-099:** WAL/concurrency patterns for trust engine (established precedent)
