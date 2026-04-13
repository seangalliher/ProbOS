# AD-616: Ward Room Router Hot Path Optimization

**Priority:** High
**Issue:** #200
**Depends on:** AD-615 (WAL mode — COMPLETE)
**Connects to:** AD-613 (HXI debouncing — frontend), BF-163 (DM flood), AD-614 (DM exchange limit)

## Motivation

The BF-163 DM flood (8,448 posts in 90 minutes) exposed three backend bottlenecks in `ward_room_router.py`:

1. **Redundant DB queries:** `list_channels()` is called 4 times across different code paths (lines 140, 398, 630, 738). Each call executes a full `SELECT * FROM channels ORDER BY created_at` — when the router only needs a single channel by ID or by name. Under flood, this alone was ~33K redundant DB reads.

2. **Zero event dispatch backpressure:** `asyncio.create_task(router.route_event())` in `communication.py:113` is fire-and-forget. Under flood, thousands of concurrent `route_event()` tasks overwhelm the event loop — each one triggers `get_thread()`, `list_channels()`, `find_targets()`, and potentially LLM calls via the intent bus.

3. **No event coalescing:** AD-613 added 300ms frontend debouncing, but the backend fires a `route_event()` for every single post. Rapid-fire posts to the same thread (e.g., 120/min during the flood) each trigger a full routing decision → LLM call cascade.

## Scope

Three changes to two source files + one new test file. Strictly backend — no frontend or UI changes.

### Change 1: Replace `list_channels()` with targeted lookups in `ward_room_router.py`

The router calls `list_channels()` (full table scan) then does a linear search for one channel. Replace all 4 call sites with targeted lookups using existing `WardRoomService` methods.

**Line 140 (route_event hot path — called on EVERY event):**
```python
# BEFORE:
channels = await self._ward_room.list_channels()
channel = next((c for c in channels if c.id == channel_id), None)

# AFTER:
channel = await self._ward_room.get_channel(channel_id)
```

**Line 398 (_extract_recreation_commands — CHALLENGE tag):**
```python
# BEFORE:
channels = await self._ward_room.list_channels()
rec_ch = next((c for c in channels if c.name == "Recreation"), None)

# AFTER:
rec_ch = await self._ward_room.get_channel_by_name("Recreation")
```

**Line 630 (_handle_self_modification_proposal):**
```python
# BEFORE:
channels = await self._ward_room.list_channels()
proposals_ch = None
for ch in channels:
    if ch.name == "Improvement Proposals":
        proposals_ch = ch
        break

# AFTER:
proposals_ch = await self._ward_room.get_channel_by_name("Improvement Proposals")
```

**Line 738 (deliver_bridge_alert):**
```python
# BEFORE:
channels = await self._ward_room.list_channels()
if alert.severity == AlertSeverity.INFO and alert.department:
    channel = next((c for c in channels if c.department == alert.department), None)
else:
    channel = next((c for c in channels if c.channel_type == "ship"), None)

# AFTER:
if alert.severity == AlertSeverity.INFO and alert.department:
    channel = await self._ward_room.get_channel_by_department(alert.department)
else:
    channel = await self._ward_room.get_channel_by_type("ship")
```

**For the bridge alert path (line 738), two new convenience methods are needed on `ChannelManager` and `WardRoomService`:**

In `src/probos/ward_room/channels.py`, add after the existing `get_channel_by_name()` method:

```python
async def get_channel_by_department(self, department: str) -> WardRoomChannel | None:
    """Get the first channel matching a department."""
    if not self._db:
        return None
    async with self._db.execute(
        "SELECT id, name, channel_type, department, created_by, created_at, archived, description "
        "FROM channels WHERE department = ? AND (archived = 0 OR archived IS NULL) LIMIT 1",
        (department,),
    ) as cursor:
        row = await cursor.fetchone()
        if not row:
            return None
        return WardRoomChannel(
            id=row[0], name=row[1], channel_type=row[2],
            department=row[3], created_by=row[4], created_at=row[5],
            archived=bool(row[6]), description=row[7],
        )

async def get_channel_by_type(self, channel_type: str) -> WardRoomChannel | None:
    """Get the first channel matching a channel type."""
    if not self._db:
        return None
    async with self._db.execute(
        "SELECT id, name, channel_type, department, created_by, created_at, archived, description "
        "FROM channels WHERE channel_type = ? AND (archived = 0 OR archived IS NULL) LIMIT 1",
        (channel_type,),
    ) as cursor:
        row = await cursor.fetchone()
        if not row:
            return None
        return WardRoomChannel(
            id=row[0], name=row[1], channel_type=row[2],
            department=row[3], created_by=row[4], created_at=row[5],
            archived=bool(row[6]), description=row[7],
        )
```

In `src/probos/ward_room/service.py`, add delegation methods in the "Channel delegation" section:

```python
async def get_channel_by_department(self, department: str) -> WardRoomChannel | None:
    """Get channel by department (LoD-safe public API)."""
    if self._channels:
        return await self._channels.get_channel_by_department(department)
    return None

async def get_channel_by_type(self, channel_type: str) -> WardRoomChannel | None:
    """Get channel by type (LoD-safe public API)."""
    if self._channels:
        return await self._channels.get_channel_by_type(channel_type)
    return None
```

### Change 2: Event dispatch semaphore in `communication.py`

Add an `asyncio.Semaphore` to bound concurrent `route_event()` calls. This provides backpressure — excess events queue in the semaphore rather than stampeding the event loop.

In `src/probos/startup/communication.py`, modify the `_ward_room_emit` closure:

```python
# Add semaphore before the closure definition (after line 107)
_ward_room_semaphore = asyncio.Semaphore(
    getattr(config.ward_room, 'router_concurrency_limit', 10)
)

def _ward_room_emit(event_type: str, data: dict) -> None:
    emit_event_fn(event_type, data)
    router = _ward_room_router_ref[0]
    if router:
        async def _bounded_route() -> None:
            async with _ward_room_semaphore:
                await router.route_event(event_type, data)
        asyncio.create_task(_bounded_route())
```

**Important:** The semaphore does NOT block — it's an asyncio semaphore, so excess tasks await their turn cooperatively. The event loop stays responsive.

### Change 3: Backend event coalescing for rapid-fire posts

Add a short coalesce window per thread for `ward_room_post_created` events. When multiple posts arrive for the same thread within the window, only the last event is routed.

In `src/probos/ward_room_router.py`, add coalescing state to `__init__()`:

```python
# Add after existing state dicts (after line 71):
self._coalesce_timers: dict[str, asyncio.TimerHandle] = {}  # thread_id -> pending timer
self._coalesce_ms: int = getattr(config.ward_room, 'event_coalesce_ms', 200)
```

Add a coalescing wrapper method:

```python
async def route_event_coalesced(self, event_type: str, data: dict[str, Any]) -> None:
    """Coalesce rapid-fire post events per thread.

    Thread creation events and non-post events are routed immediately.
    Post events are delayed by coalesce_ms — if another post arrives for the
    same thread within the window, the timer resets and only the latest
    event is routed.
    """
    # Thread creation and non-post events: route immediately
    if event_type != "ward_room_post_created" or self._coalesce_ms <= 0:
        await self.route_event(event_type, data)
        return

    thread_id = data.get("thread_id", "")
    if not thread_id:
        await self.route_event(event_type, data)
        return

    # Cancel any pending timer for this thread
    existing = self._coalesce_timers.pop(thread_id, None)
    if existing:
        existing.cancel()

    # Schedule routing after the coalesce window
    loop = asyncio.get_running_loop()

    async def _fire() -> None:
        self._coalesce_timers.pop(thread_id, None)
        await self.route_event(event_type, data)

    handle = loop.call_later(
        self._coalesce_ms / 1000.0,
        lambda: asyncio.create_task(_fire()),
    )
    self._coalesce_timers[thread_id] = handle
```

**Update the dispatch call site** in `communication.py` to use the coalescing wrapper:

```python
# In _bounded_route():
await router.route_event_coalesced(event_type, data)
```

**Note:** `route_event()` remains the direct entry point (used by proactive loop's `_check_unread_dms()` and tests). `route_event_coalesced()` is only used by the Ward Room emit path where rapid-fire events originate.

### Change 4: Config fields on `WardRoomConfig`

In `src/probos/config.py`, add two fields to `WardRoomConfig` (after `dm_similarity_threshold`):

```python
router_concurrency_limit: int = 10     # AD-616: max concurrent route_event() tasks
event_coalesce_ms: int = 200           # AD-616: coalesce window for rapid-fire post events (0 = disabled)
```

## Deliberate Exclusions

| Excluded | Why |
|----------|-----|
| In-memory channel dict cache on `ChannelManager` | The targeted lookups (`get_channel()`, `get_channel_by_name()`, etc.) already hit the DB with indexed queries — `O(1)` via primary key or name. Adding a memory cache layer adds invalidation complexity for marginal gain. The fix is replacing full-table scan + linear search with indexed single-row queries, not adding another caching layer. |
| Modifying `route_event()` signature or return type | The coalescing wrapper is a separate method. Existing callers (proactive loop, tests) use `route_event()` directly, unaffected. |
| Frontend changes | AD-613 already handles frontend debouncing. This AD is backend-only. |
| LLM rate limiting | Deferred to AD-617, which has its own scope and config surface. |

## Engineering Principles Applied

- **SOLID (S):** Coalescing is a new method, not added to `route_event()`. Single responsibility — `route_event()` handles routing logic, `route_event_coalesced()` handles timing.
- **SOLID (O):** New `get_channel_by_department()`/`get_channel_by_type()` extend the query API without modifying existing methods.
- **SOLID (D):** Router depends on `WardRoomService` public API, not `ChannelManager` internals. No `_channel_cache` access across boundaries.
- **Law of Demeter:** Router calls `self._ward_room.get_channel()`, not `self._ward_room._channels._channel_cache[...]`.
- **Fail Fast:** Semaphore is log-and-degrade — excess events queue, they don't get dropped. Coalescing only defers, never loses events.
- **DRY:** `get_channel_by_department()` and `get_channel_by_type()` follow the exact same pattern as existing `get_channel_by_name()`.

## Test Specification

Create `tests/test_ad616_router_hot_path.py` with the following tests:

### Class: `TestChannelLookupOptimization` (3 tests)

1. **`test_route_event_uses_get_channel_not_list`** — Structural: assert `list_channels` does NOT appear in the `route_event` method source code (inspect.getsource).
2. **`test_get_channel_by_department_exists`** — Verify `get_channel_by_department()` method exists on `ChannelManager` and `WardRoomService`.
3. **`test_get_channel_by_type_exists`** — Verify `get_channel_by_type()` method exists on `ChannelManager` and `WardRoomService`.

### Class: `TestEventDispatchSemaphore` (2 tests)

4. **`test_semaphore_in_ward_room_emit`** — Structural: verify the `_bounded_route` pattern and `Semaphore` appear in `communication.py` source (grep for `Semaphore` and `_bounded_route`).
5. **`test_router_concurrency_limit_config`** — Verify `router_concurrency_limit` field exists on `WardRoomConfig` with default value 10.

### Class: `TestEventCoalescing` (3 tests)

6. **`test_route_event_coalesced_exists`** — Verify `route_event_coalesced()` method exists on `WardRoomRouter`.
7. **`test_coalesce_ms_config`** — Verify `event_coalesce_ms` field exists on `WardRoomConfig` with default value 200.
8. **`test_thread_created_not_coalesced`** — Behavioral: call `route_event_coalesced()` with `ward_room_thread_created` event, verify `route_event()` is called immediately (mock `route_event`, assert called once without delay).

### Class: `TestNewChannelQueries` (2 tests — behavioral, real DB)

9. **`test_get_channel_by_department_returns_match`** — Create a minimal SQLite DB with channels table, insert a department channel, verify `get_channel_by_department()` returns it.
10. **`test_get_channel_by_type_returns_match`** — Same pattern: insert a "ship" type channel, verify `get_channel_by_type("ship")` returns it.

## Files Modified

| File | Change |
|------|--------|
| `src/probos/ward_room/channels.py` | Add `get_channel_by_department()`, `get_channel_by_type()` |
| `src/probos/ward_room/service.py` | Add delegation for `get_channel_by_department()`, `get_channel_by_type()` |
| `src/probos/ward_room_router.py` | Replace 4× `list_channels()` with targeted lookups. Add `route_event_coalesced()` method + `_coalesce_timers`/`_coalesce_ms` state. |
| `src/probos/startup/communication.py` | Add `asyncio.Semaphore`, wrap `route_event` call in `_bounded_route()`, use `route_event_coalesced()`. |
| `src/probos/config.py` | Add `router_concurrency_limit`, `event_coalesce_ms` to `WardRoomConfig`. |
| `tests/test_ad616_router_hot_path.py` | **NEW** — 10 tests across 4 classes. |

## Verification

After building:
1. Run `pytest tests/test_ad616_router_hot_path.py -v` — all 10 must pass.
2. Run `pytest tests/ -x --timeout=60` — full regression, no failures.
3. Grep `ward_room_router.py` for `list_channels` — must return ZERO matches.
