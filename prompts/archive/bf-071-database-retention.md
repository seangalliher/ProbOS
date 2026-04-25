# BF-071: Database Retention — Event Log & Cognitive Journal

## Problem

Two append-only databases grow without bound:

1. **`events.db`** — Every system event (heartbeat, spawn, intent, lifecycle) is logged with no eviction, rotation, or size cap. Will reach hundreds of MB over weeks.
2. **`cognitive_journal.db`** — Every LLM call trace is logged. Has a `wipe()` method (full DELETE) but no partial/rolling cleanup.

The code review flagged this as **CRITICAL** — it's a ticking time bomb for long-running instances.

## Solution

Add retention configuration and periodic pruning to both stores, following the Ward Room retention pattern (`ward_room.py:252-295`) as the reference implementation.

## Files to Modify

### 1. `src/probos/config.py`

Add retention config fields to the existing config structure. Find where `EventLog` and `CognitiveJournal` are configured and add:

```python
# Add to the appropriate config section (near DreamingConfig around line 161)
class EventLogConfig(BaseModel):
    """Event log retention configuration."""
    retention_days: int = 7          # Delete events older than N days (0 = keep forever)
    max_rows: int = 100_000          # Hard cap on total rows (0 = no cap)
    prune_interval_seconds: float = 3600.0  # Check for pruning every N seconds

class CognitiveJournalConfig(BaseModel):
    """Cognitive journal retention configuration."""
    enabled: bool = True
    retention_days: int = 14         # Keep journal entries for N days (0 = keep forever)
    max_rows: int = 500_000          # Hard cap on total rows (0 = no cap)
    prune_interval_seconds: float = 3600.0
```

Wire these into the main config class at the appropriate location.

### 2. `src/probos/substrate/event_log.py`

Add retention support to `EventLog`:

**a) Add a `prune()` method:**

```python
async def prune(self, retention_days: int = 7, max_rows: int = 100_000) -> int:
    """Delete events older than retention_days and enforce max_rows cap.

    Returns number of rows deleted.
    """
    if not self._db:
        return 0

    deleted = 0

    # Age-based pruning
    if retention_days > 0:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        cursor = await self._db.execute(
            "DELETE FROM events WHERE timestamp < ?", (cutoff,)
        )
        deleted += cursor.rowcount

    # Row-count cap
    if max_rows > 0:
        cursor = await self._db.execute("SELECT COUNT(*) FROM events")
        row = await cursor.fetchone()
        total = row[0] if row else 0
        if total > max_rows:
            excess = total - max_rows
            cursor = await self._db.execute(
                "DELETE FROM events WHERE id IN "
                "(SELECT id FROM events ORDER BY id ASC LIMIT ?)",
                (excess,)
            )
            deleted += cursor.rowcount

    if deleted > 0:
        await self._db.commit()
        logger.info("EventLog pruned: %d events removed", deleted)

    return deleted
```

**b) Add a `wipe()` method** (for reset support — currently missing):

```python
async def wipe(self) -> None:
    """Delete all events. Used by probos reset."""
    if not self._db:
        return
    try:
        await self._db.execute("DELETE FROM events")
        await self._db.commit()
    except Exception:
        logger.debug("EventLog wipe failed", exc_info=True)
```

**c) Add a `count_all()` method** for dry-run display:

```python
async def count_all(self) -> int:
    """Total event count."""
    return await self.count()
```

### 3. `src/probos/cognitive/journal.py`

Add retention support to `CognitiveJournal`:

**a) Add a `prune()` method:**

```python
async def prune(self, retention_days: int = 14, max_rows: int = 500_000) -> int:
    """Delete journal entries older than retention_days and enforce max_rows.

    Returns number of rows deleted.
    """
    if not self._db:
        return 0

    import time as _time
    deleted = 0

    # Age-based pruning (timestamp is Unix epoch float)
    if retention_days > 0:
        cutoff = _time.time() - (retention_days * 86400)
        cursor = await self._db.execute(
            "DELETE FROM journal WHERE timestamp < ?", (cutoff,)
        )
        deleted += cursor.rowcount

    # Row-count cap
    if max_rows > 0:
        cursor = await self._db.execute("SELECT COUNT(*) FROM journal")
        row = await cursor.fetchone()
        total = row[0] if row else 0
        if total > max_rows:
            excess = total - max_rows
            cursor = await self._db.execute(
                "DELETE FROM journal WHERE id IN "
                "(SELECT id FROM journal ORDER BY timestamp ASC LIMIT ?)",
                (excess,)
            )
            deleted += cursor.rowcount

    if deleted > 0:
        await self._db.commit()
        logger.info("CognitiveJournal pruned: %d entries removed", deleted)

    return deleted
```

### 4. `src/probos/runtime.py`

Wire up periodic pruning in the runtime. Find where the Ward Room prune loop is started (search for `_prune_loop` or `prune_interval`) and add similar loops for EventLog and CognitiveJournal:

```python
# In start(), after event_log and cognitive_journal are initialized,
# start prune loops (similar pattern to Ward Room's _run_prune_loop)

async def _event_log_prune_loop(self):
    """Periodic event log retention cleanup."""
    config = self._config.event_log  # or however the config is accessed
    while True:
        await asyncio.sleep(config.prune_interval_seconds)
        try:
            await self.event_log.prune(
                retention_days=config.retention_days,
                max_rows=config.max_rows,
            )
        except Exception:
            logger.debug("Event log prune failed", exc_info=True)

async def _journal_prune_loop(self):
    """Periodic cognitive journal retention cleanup."""
    config = self._config.cognitive_journal  # or however the config is accessed
    while True:
        await asyncio.sleep(config.prune_interval_seconds)
        try:
            await self.cognitive_journal.prune(
                retention_days=config.retention_days,
                max_rows=config.max_rows,
            )
        except Exception:
            logger.debug("Journal prune failed", exc_info=True)
```

Start these loops at the end of `start()`, near where other background tasks are launched:

```python
asyncio.ensure_future(self._event_log_prune_loop())
asyncio.ensure_future(self._journal_prune_loop())
```

**Note:** Yes, `asyncio.ensure_future()` is the existing pattern in the codebase. A separate BF will modernize these to `create_task()`.

### 5. Tests

Add tests in a new file `tests/test_database_retention.py`:

```python
"""Tests for BF-071: Database retention — EventLog and CognitiveJournal pruning."""
```

Test cases:

1. **EventLog.prune() — age-based**: Insert events with old timestamps, call prune, verify old events deleted and recent preserved.
2. **EventLog.prune() — max_rows cap**: Insert more than max_rows, call prune, verify count equals max_rows and oldest removed.
3. **EventLog.prune() — no-op when within limits**: Insert few events within retention, verify prune returns 0.
4. **EventLog.wipe()**: Insert events, wipe, verify empty.
5. **CognitiveJournal.prune() — age-based**: Insert entries with old timestamps, call prune, verify old entries deleted.
6. **CognitiveJournal.prune() — max_rows cap**: Insert more than max_rows, call prune, verify count.
7. **CognitiveJournal.prune() — no-op when within limits**.
8. **Config defaults**: Verify EventLogConfig and CognitiveJournalConfig have sensible defaults.
9. **prune() with retention_days=0 skips age pruning**: Verify events kept regardless of age.
10. **prune() with max_rows=0 skips row cap**: Verify no cap applied.

## Implementation Notes

- **EventLog timestamps are ISO strings** (`datetime.now(timezone.utc).isoformat()`). The prune comparison should use ISO string comparison (lexicographic ordering works for ISO 8601).
- **CognitiveJournal timestamps are Unix epoch floats** (`time.time()`). Use numeric comparison.
- The `prune()` methods should be safe to call when db is None (return 0).
- Follow the same commit-per-write pattern the existing code uses (explicit `await self._db.commit()` after deletions).
- **Do NOT use `asyncio.create_task()`** — use `asyncio.ensure_future()` to match existing codebase patterns. A separate BF will modernize these.

## Acceptance Criteria

- [ ] EventLog has `prune()` and `wipe()` methods
- [ ] CognitiveJournal has `prune()` method (already has `wipe()`)
- [ ] Config has `EventLogConfig` and `CognitiveJournalConfig` with retention defaults
- [ ] Runtime starts prune loops alongside other background tasks
- [ ] All new tests pass
- [ ] Existing tests unaffected
