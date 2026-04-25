# AD-416: Ward Room Archival & Pruning

## Context

The proactive cognitive loop generates Ward Room posts every time a crew agent thinks successfully. With 11 crew agents thinking every ~5 minutes, that's ~130 posts/hour, ~3,100 posts/day. `ward_room.db` grows unbounded — no archival, no pruning, no retention policy. Over weeks of operation this becomes a performance and storage problem, and the proactive context gathering (`get_recent_activity()`) has to scan an ever-growing table.

Additionally, the runtime's in-memory Ward Room tracking dicts (`_ward_room_thread_rounds`, `_ward_room_round_participants`, `_ward_room_agent_thread_responses`) grow without bound since thread IDs are never cleaned up.

## Pre-Build Audit

Read these files before editing:

1. `src/probos/ward_room.py` — Full WardRoomService. Focus on:
   - SQLite schema (lines 108-194): `threads`, `posts`, `endorsements` tables
   - `start()` method (line 213): aiosqlite open + schema migration pattern
   - `stop()` method (line 233)
   - `get_recent_activity()` (line 478): how it filters by timestamp
   - No existing pruning/archival logic exists

2. `src/probos/config.py` — `WardRoomConfig` class (line 270). Current fields are all throttling. New retention fields go here.

3. `src/probos/runtime.py` — Ward Room wiring:
   - Instance vars (lines 210-216): the unbounded tracking dicts
   - Start (line 1211): WardRoomService creation
   - Stop (line 1349): WardRoomService shutdown
   - `_route_ward_room_event()` (~line 2884): uses tracking dicts

4. `src/probos/__main__.py` — `_cmd_reset()` (line 520): existing reset flow archives `ward_room.db` to `data_dir/archives/` before wiping. The archival format here (full DB copy) is the reset pattern; AD-416 is the *operational* pruning pattern (selective row deletion with JSONL archive).

5. `tests/test_ward_room.py` — Existing test patterns for WardRoomService

## What To Build

### Step 1: Config — `src/probos/config.py`

Add retention fields to `WardRoomConfig`:

```python
class WardRoomConfig(BaseModel):
    """Ward Room communication fabric configuration (AD-407)."""
    enabled: bool = False
    max_agent_rounds: int = 3
    agent_cooldown_seconds: float = 45
    max_agent_responses_per_thread: int = 3
    default_discuss_responder_cap: int = 3
    # AD-416: Retention & archival
    retention_days: int = 7                    # Regular posts older than this are pruned
    retention_days_endorsed: int = 30          # Posts with net_score > 0 retained longer
    retention_days_captain: int = 0            # 0 = indefinite retention for Captain posts
    archive_enabled: bool = True               # Write pruned posts to JSONL archive before deletion
    prune_interval_seconds: float = 86400.0    # How often to run pruning (default: daily)
```

### Step 2: Core — Ward Room pruning methods in `src/probos/ward_room.py`

Add three methods to `WardRoomService`:

#### `async def prune_old_threads(self, retention_days, retention_days_endorsed, retention_days_captain, archive_path) -> dict`

This is the main pruning method. Logic:

1. Calculate cutoff timestamps:
   - `regular_cutoff = time.time() - (retention_days * 86400)`
   - `endorsed_cutoff = time.time() - (retention_days_endorsed * 86400)`

2. Find pruneable threads with a single query:
   ```sql
   SELECT id, channel_id, author_id, title, body, created_at, last_activity,
          pinned, locked, thread_mode, reply_count, net_score, author_callsign
   FROM threads
   WHERE pinned = 0
     AND last_activity < ?  -- regular cutoff
   ```
   Then filter in Python:
   - Skip if `net_score > 0` AND `last_activity >= endorsed_cutoff`
   - Skip if `author_id == "captain"` AND `retention_days_captain == 0`

3. For each pruneable thread, collect its posts and endorsements.

4. If `archive_path` is provided, write each thread + its posts to a JSONL file (one JSON object per line = one thread with nested posts). Archive filename: `ward_room_archive_YYYY-MM.jsonl` (monthly rotation). **Append mode** — multiple prune runs in the same month append to the same file.

   Archive record format:
   ```json
   {
     "thread_id": "...",
     "channel_id": "...",
     "author_id": "...",
     "author_callsign": "...",
     "title": "...",
     "body": "...",
     "created_at": 1234567890.0,
     "last_activity": 1234567890.0,
     "thread_mode": "discuss",
     "net_score": 0,
     "reply_count": 3,
     "posts": [
       {"id": "...", "author_id": "...", "author_callsign": "...", "body": "...", "created_at": 1234567890.0, "net_score": 0}
     ],
     "pruned_at": 1234567890.0
   }
   ```

5. Delete in order (respecting implicit FK relationships):
   - `DELETE FROM endorsements WHERE target_id IN (post_ids + thread_ids)`
   - `DELETE FROM posts WHERE thread_id IN (thread_ids)`
   - `DELETE FROM threads WHERE id IN (thread_ids)`

6. Return summary: `{"threads_pruned": N, "posts_pruned": N, "endorsements_pruned": N, "archived_to": "path or None"}`

7. Emit event: `ward_room_pruned` with the summary dict.

#### `async def get_stats(self) -> dict`

Returns basic stats for monitoring:

```python
{
    "total_threads": N,
    "total_posts": N,
    "total_endorsements": N,
    "oldest_thread_at": float_or_None,
    "db_size_bytes": os.path.getsize(self.db_path),
}
```

#### `async def count_pruneable(self, retention_days, retention_days_endorsed, retention_days_captain) -> int`

Dry-run count of how many threads would be pruned. Useful for the API and monitoring without actually deleting.

### Step 3: Prune loop — `src/probos/ward_room.py`

Add a background prune loop to WardRoomService, similar to PersistentTaskStore's `_tick_loop`:

```python
async def start_prune_loop(self, config: "WardRoomConfig", archive_dir: Path) -> None:
    """Start background pruning task."""
    self._prune_config = config
    self._archive_dir = archive_dir
    self._prune_task = asyncio.create_task(self._prune_loop())

async def _prune_loop(self) -> None:
    """Periodic pruning of old threads."""
    while True:
        await asyncio.sleep(self._prune_config.prune_interval_seconds)
        try:
            archive_path = None
            if self._prune_config.archive_enabled:
                self._archive_dir.mkdir(parents=True, exist_ok=True)
                month = datetime.now().strftime("%Y-%m")
                archive_path = str(self._archive_dir / f"ward_room_archive_{month}.jsonl")
            result = await self.prune_old_threads(
                retention_days=self._prune_config.retention_days,
                retention_days_endorsed=self._prune_config.retention_days_endorsed,
                retention_days_captain=self._prune_config.retention_days_captain,
                archive_path=archive_path,
            )
            if result["threads_pruned"] > 0:
                logger.info(
                    "Ward Room pruned: %d threads, %d posts archived to %s",
                    result["threads_pruned"], result["posts_pruned"],
                    result.get("archived_to", "none"),
                )
        except Exception:
            logger.warning("Ward Room prune failed", exc_info=True)

async def stop_prune_loop(self) -> None:
    """Cancel the prune task."""
    if hasattr(self, '_prune_task') and self._prune_task:
        self._prune_task.cancel()
        try:
            await self._prune_task
        except asyncio.CancelledError:
            pass
        self._prune_task = None
```

### Step 4: Runtime wiring — `src/probos/runtime.py`

**Start** (after `await self.ward_room.start()`, ~line 1230):
```python
# AD-416: Start Ward Room pruning loop
archive_dir = self._data_dir / "ward_room_archive"
await self.ward_room.start_prune_loop(self.config.ward_room, archive_dir)
```

**Stop** (before `await self.ward_room.stop()`, ~line 1349):
```python
await self.ward_room.stop_prune_loop()
```

**In-memory dict cleanup** — Add a method to clean up stale entries from the tracking dicts. Call it from `_route_ward_room_event()` or the prune loop:

```python
def _cleanup_ward_room_tracking(self, pruned_thread_ids: set[str]) -> None:
    """Remove tracking entries for pruned threads."""
    for tid in pruned_thread_ids:
        self._ward_room_thread_rounds.pop(tid, None)
        keys_to_remove = [k for k in self._ward_room_round_participants if k.startswith(f"{tid}:")]
        for k in keys_to_remove:
            del self._ward_room_round_participants[k]
        keys_to_remove = [k for k in self._ward_room_agent_thread_responses if k.startswith(f"{tid}:")]
        for k in keys_to_remove:
            del self._ward_room_agent_thread_responses[k]
```

Wire this into the prune event handler or call it directly after pruning.

**State snapshot** — Add ward room stats to `build_state_snapshot()`:
```python
if self.ward_room:
    result["ward_room_available"] = True
    result["ward_room_channels"] = self.ward_room.get_channel_snapshot()
    stats = await self.ward_room.get_stats()
    result["ward_room_stats"] = stats
```

Note: `build_state_snapshot()` is not async currently. If getting stats requires async, either make it a sync query, cache the stats from the last prune run, or skip this for now. Prefer caching: store `_last_stats` on the service and update it after each prune run + on startup.

### Step 5: REST API — `src/probos/api.py`

Add two endpoints:

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/ward-room/stats` | Return `get_stats()` + `count_pruneable()` |
| POST | `/api/ward-room/prune` | Manual prune trigger (Captain override) |

**GET `/api/ward-room/stats`:**
```python
@app.get("/api/ward-room/stats")
async def ward_room_stats():
    if not runtime.ward_room:
        return JSONResponse({"error": "Ward Room not enabled"}, status_code=503)
    stats = await runtime.ward_room.get_stats()
    config = runtime.config.ward_room
    pruneable = await runtime.ward_room.count_pruneable(
        config.retention_days, config.retention_days_endorsed, config.retention_days_captain,
    )
    stats["pruneable_threads"] = pruneable
    stats["retention_days"] = config.retention_days
    stats["retention_days_endorsed"] = config.retention_days_endorsed
    return JSONResponse(stats)
```

**POST `/api/ward-room/prune`:**
```python
@app.post("/api/ward-room/prune")
async def ward_room_prune():
    if not runtime.ward_room:
        return JSONResponse({"error": "Ward Room not enabled"}, status_code=503)
    config = runtime.config.ward_room
    archive_path = None
    if config.archive_enabled:
        archive_dir = runtime._data_dir / "ward_room_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        month = datetime.now().strftime("%Y-%m")
        archive_path = str(archive_dir / f"ward_room_archive_{month}.jsonl")
    result = await runtime.ward_room.prune_old_threads(
        retention_days=config.retention_days,
        retention_days_endorsed=config.retention_days_endorsed,
        retention_days_captain=config.retention_days_captain,
        archive_path=archive_path,
    )
    return JSONResponse(result)
```

### Step 6: Tests — `tests/test_ward_room.py`

Add a new test class `TestWardRoomPruning` with these tests:

| Test | What It Validates |
|------|-------------------|
| `test_prune_old_thread` | Thread older than retention_days is deleted |
| `test_prune_preserves_recent` | Thread within retention_days survives |
| `test_prune_preserves_endorsed` | Thread with net_score > 0 uses endorsed retention window |
| `test_prune_preserves_pinned` | Pinned threads are never pruned |
| `test_prune_preserves_captain` | Captain-authored threads survive with retention_days_captain=0 |
| `test_prune_cascades_posts` | Posts belonging to pruned threads are deleted |
| `test_prune_cascades_endorsements` | Endorsements on pruned threads/posts are deleted |
| `test_prune_archives_to_jsonl` | Pruned threads are written to JSONL file with correct format |
| `test_prune_archive_appends` | Multiple prune runs append to same monthly file |
| `test_prune_no_archive` | When archive_enabled=False, no file is written |
| `test_count_pruneable` | Dry-run count matches actual prune count |
| `test_get_stats` | Returns correct counts and oldest_thread_at |
| `test_prune_returns_summary` | Return dict has correct keys and counts |
| `test_prune_emits_event` | `ward_room_pruned` event emitted with summary |

For time manipulation, set `created_at` and `last_activity` to explicit epoch values in the past rather than using `time.time()`. Example: `time.time() - 8 * 86400` for an 8-day-old thread (past the 7-day default).

## Allowed Files

- `src/probos/config.py` — retention config fields
- `src/probos/ward_room.py` — pruning methods + prune loop
- `src/probos/runtime.py` — wiring prune loop start/stop + tracking dict cleanup
- `src/probos/api.py` — stats and manual prune endpoints
- `tests/test_ward_room.py` — pruning tests

## Do Not Build

- Do not modify the existing `probos reset` flow in `__main__.py` — reset already archives the full DB
- Do not add HXI components (future AD)
- Do not modify the proactive loop or dream scheduler
- Do not change existing Ward Room methods (create_thread, create_post, etc.)
- Do not add cron/scheduling dependencies — the prune loop is a simple `asyncio.sleep` timer

## Test Gates

After implementation:
```bash
uv run pytest tests/test_ward_room.py -x -q --tb=short
```

Full regression:
```bash
uv run pytest tests/ -x -q --tb=short
```

## Acceptance Criteria

1. `WardRoomConfig` has retention and archival fields with sensible defaults
2. `prune_old_threads()` deletes threads + posts + endorsements older than retention window
3. Pinned threads are never pruned; endorsed threads get extended retention; Captain posts get indefinite retention (configurable)
4. Pruned threads archived to monthly JSONL files in `data_dir/ward_room_archive/` (append mode)
5. Background prune loop runs on configurable interval (default: daily)
6. Manual prune trigger via `POST /api/ward-room/prune`
7. `GET /api/ward-room/stats` returns thread/post counts, DB size, pruneable count
8. `ward_room_pruned` event emitted after each prune
9. Runtime tracking dicts cleaned up when threads are pruned
10. 14 new tests pass
11. Full test suite passes
