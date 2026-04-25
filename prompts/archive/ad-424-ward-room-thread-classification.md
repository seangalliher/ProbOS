# AD-424: Ward Room Thread Classification & Lifecycle — Build Prompt

## Context

Bridge alerts post to All Hands as threads authored by "Ship's Computer" (with `author_id="captain"`, so crew routing treats them as Captain posts). But Earned Agency gating blocks all Lieutenants from responding to ship-wide ambient posts:

```python
# earned_agency.py line 40-42
if rank == Rank.LIEUTENANT:
    return is_captain_post and same_department  # True AND False = False for ship-wide
```

In `_find_ward_room_targets()` (runtime.py ~line 3059-3075), ship-wide channels hardcode `same_department=False`. Post-reset, all crew are at trust 0.5 = Lieutenant — **no one can respond to advisories** (BF-022).

Beyond this bug, the Ward Room lacks message classification. Every thread is treated the same — any thread on All Hands tries to notify all crew for a response. This creates two problems: (1) informational broadcasts (system status reports) shouldn't trigger agent LLM calls at all, and (2) discussion threads shouldn't have 7 agents pile in with reply-all.

**Goal:** Add thread classification (INFORM/DISCUSS/ACTION), fix BF-022, add responder controls for DISCUSS threads, and add Captain thread management (lock/reclassify).

## Part 1: Add `thread_mode` to Ward Room data model

**File:** `src/probos/ward_room.py`

### 1a: Update WardRoomThread dataclass

Add `thread_mode` field to `WardRoomThread` (currently at line ~40). Insert after `locked`:

```python
@dataclass
class WardRoomThread:
    id: str
    channel_id: str
    author_id: str
    title: str
    body: str
    created_at: float
    last_activity: float
    pinned: bool = False
    locked: bool = False
    thread_mode: str = "discuss"  # AD-424: "inform" | "discuss" | "action"
    max_responders: int = 0       # AD-424: 0 = unlimited, >0 = cap
    reply_count: int = 0
    net_score: int = 0
    author_callsign: str = ""
    channel_name: str = ""
```

**Note:** `thread_mode` defaults to `"discuss"` for backward compatibility — all existing threads behave as DISCUSS. `max_responders` defaults to 0 (unlimited) for backward compatibility.

### 1b: Update SQLite schema

In the `_init_db()` method (line ~106), update the `threads` table to add the two new columns. Add them after `locked`:

```sql
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES channels(id),
    author_id TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_activity REAL NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    locked INTEGER NOT NULL DEFAULT 0,
    thread_mode TEXT NOT NULL DEFAULT 'discuss',
    max_responders INTEGER NOT NULL DEFAULT 0,
    reply_count INTEGER NOT NULL DEFAULT 0,
    net_score INTEGER NOT NULL DEFAULT 0,
    author_callsign TEXT NOT NULL DEFAULT '',
    channel_name TEXT NOT NULL DEFAULT ''
)
```

**Also add schema migration** for existing databases. In the `start()` method (after `_init_db()`), add ALTER TABLE migration for existing DBs that lack these columns:

```python
# AD-424: Schema migration — add thread_mode and max_responders if missing
try:
    await db.execute("ALTER TABLE threads ADD COLUMN thread_mode TEXT NOT NULL DEFAULT 'discuss'")
except Exception:
    pass  # Column already exists
try:
    await db.execute("ALTER TABLE threads ADD COLUMN max_responders INTEGER NOT NULL DEFAULT 0")
except Exception:
    pass  # Column already exists
await db.commit()
```

### 1c: Update create_thread()

Add `thread_mode` and `max_responders` parameters to `create_thread()` (line ~445):

```python
async def create_thread(
    self, channel_id: str, author_id: str, title: str, body: str,
    author_callsign: str = "",
    thread_mode: str = "discuss",      # AD-424
    max_responders: int = 0,           # AD-424
) -> WardRoomThread:
```

Pass the new fields to the `WardRoomThread` constructor and the INSERT statement. Add `thread_mode` and `max_responders` to the event data in the `ward_room_thread_created` emission.

### 1d: Update thread retrieval

Any method that reads threads from the DB and constructs `WardRoomThread` objects needs to include the new columns. Check `list_threads()`, `get_thread()`, `get_recent_activity()`, and any other query that SELECT from `threads`. The new fields should map from the DB row to the dataclass constructor.

### 1e: Add update_thread() method

Add a new method for Captain thread management (lock, reclassify, adjust responder cap):

```python
async def update_thread(
    self, thread_id: str, **updates: Any,
) -> WardRoomThread | None:
    """Update thread fields (AD-424). Captain-level operation.

    Supported fields: locked, thread_mode, max_responders, pinned.
    """
    if not self._db:
        return None
    allowed = {"locked", "thread_mode", "max_responders", "pinned"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return None

    async with self._db as db:
        sets = ", ".join(f"{k} = ?" for k in filtered)
        vals = list(filtered.values())
        vals.append(thread_id)
        await db.execute(f"UPDATE threads SET {sets} WHERE id = ?", vals)
        await db.commit()

    thread = await self.get_thread(thread_id)
    if thread and self._emit_event:
        event_type = "ward_room_thread_updated"
        self._emit_event(event_type, {
            "thread_id": thread_id,
            "updates": filtered,
        })
    return thread
```

## Part 2: Update Bridge Alert delivery to use INFORM mode

**File:** `src/probos/runtime.py`

In `_deliver_bridge_alert()` (line ~2807), pass `thread_mode="inform"` when creating the Ward Room thread:

```python
thread = await self.ward_room.create_thread(
    channel_id=channel.id,
    author_id="captain",
    author_callsign="Ship's Computer",
    title=f"[{alert.severity.value.upper()}] {alert.title}",
    body=alert.detail,
    thread_mode="inform",   # AD-424: Bridge alerts are informational
)
```

**Effect:** All bridge alert threads are classified as INFORM. The routing logic (Part 3) will skip agent notification for INFORM threads entirely.

## Part 3: Update Ward Room event routing for thread modes

**File:** `src/probos/runtime.py`

### 3a: Thread mode gate in _route_ward_room_event()

In `_route_ward_room_event()` (line ~2860), after retrieving the thread object (needed for thread depth tracking anyway), add a thread mode check **before** the target selection logic:

```python
# AD-424: Thread mode gating
# Retrieve thread to check mode (we need it anyway for depth tracking)
thread_obj = await self.ward_room.get_thread(thread_id)
if not thread_obj:
    return

# INFORM threads: no agent notification at all
if thread_obj.thread_mode == "inform":
    return

# ACTION threads: only @mentioned agents (existing BF-016a behavior)
# DISCUSS threads: responder cap + relaxed earned agency (below)
```

**Important:** The `_route_ward_room_event` already fetches thread data around line 2937-2953 for building context. Move or reuse that thread fetch to happen earlier (before target selection), so the mode check can use it. Don't fetch the thread twice.

### 3b: Responder cap for DISCUSS threads

After `_find_ward_room_targets()` returns the target list, apply the responder cap if the thread has `max_responders > 0`:

```python
# AD-424: Apply responder cap for DISCUSS threads
if thread_obj.thread_mode == "discuss" and thread_obj.max_responders > 0:
    targets = targets[:thread_obj.max_responders]
```

This is a simple truncation — `_find_ward_room_targets()` already returns targets in a deterministic order (@mentions first, then department match, then remaining crew). The cap just limits how many get notified.

### 3c: Relaxed earned agency for DISCUSS threads on ship-wide channels

**File:** `src/probos/runtime.py`

In `_find_ward_room_targets()` (line ~3037), the ship-wide channel block (lines ~3059-3075) currently passes `same_department=False` to `can_respond_ambient()`. For DISCUSS threads, we want `same_department=True` so Lieutenants can respond.

Add a `thread_mode` parameter to `_find_ward_room_targets()`:

```python
def _find_ward_room_targets(
    self,
    channel: Any,
    author_id: str,
    mentions: list[str] | None = None,
    thread_mode: str = "discuss",  # AD-424
) -> list[str]:
```

In the ship-wide channel block, adjust the `same_department` value based on thread mode:

```python
# Ship-wide channel — notify all crew agents
if channel.channel_type == "ship":
    for agent in self.registry.all_agents():
        if not self._is_crew_agent(agent.agent_type):
            continue
        if agent.id == author_id:
            continue
        # AD-424: DISCUSS threads on ship-wide treat as same-department
        # for earned agency purposes. The Captain explicitly opened
        # the thread for discussion — Lieutenants should participate.
        effective_same_dept = (thread_mode == "discuss")
        if self.config.earned_agency.enabled:
            rank = Rank.from_trust(self._get_trust(agent.id))
            if not can_respond_ambient(
                rank,
                is_captain_post=is_captain_post,
                same_department=effective_same_dept,
            ):
                continue
        targets.append(agent.id)
```

**Update the call site** in `_route_ward_room_event()` to pass the thread mode:

```python
targets = self._find_ward_room_targets(
    channel, author_id, mentions,
    thread_mode=thread_obj.thread_mode,
)
```

**Effect on BF-022:** With `thread_mode="discuss"` and `effective_same_dept=True`, `can_respond_ambient(LIEUTENANT, is_captain_post=True, same_department=True)` → `True AND True = True`. Lieutenants can now respond to DISCUSS threads on All Hands. INFORM threads never reach this code (filtered in Part 3a). BF-022 is fixed.

## Part 4: Add PATCH endpoint for thread management

**File:** `src/probos/api.py`

Add a Pydantic request model and a new PATCH endpoint:

```python
class UpdateThreadRequest(BaseModel):
    """AD-424: Captain thread management."""
    locked: bool | None = None
    thread_mode: str | None = None     # "inform" | "discuss" | "action"
    max_responders: int | None = None
    pinned: bool | None = None
```

Add the route (after the existing `wardroom_thread_detail` GET endpoint, around line ~1254):

```python
@app.patch("/api/wardroom/threads/{thread_id}")
async def wardroom_update_thread(thread_id: str, req: UpdateThreadRequest):
    """AD-424: Update thread properties (Captain-level)."""
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No updates provided")
    thread = await runtime.ward_room.update_thread(thread_id, **updates)
    if not thread:
        raise HTTPException(404, "Thread not found")
    return vars(thread)
```

## Part 5: Update TypeScript types

**File:** `ui/src/store/types.ts`

Add the new fields to the `WardRoomThread` interface (line ~341):

```typescript
export interface WardRoomThread {
  id: string;
  channel_id: string;
  author_id: string;
  title: string;
  body: string;
  created_at: number;
  last_activity: number;
  pinned: boolean;
  locked: boolean;
  thread_mode: 'inform' | 'discuss' | 'action';  // AD-424
  max_responders: number;                          // AD-424
  reply_count: number;
  net_score: number;
  author_callsign: string;
  channel_name: string;
}
```

**File:** `ui/src/store/useStore.ts`

In the SSE event handlers, add a handler for `ward_room_thread_updated`:

```typescript
case 'ward_room_thread_updated': {
  // AD-424: Thread was reclassified, locked, or responder cap changed
  const channelId = get().wardRoomChannels.find(c =>
    get().wardRoomThreads[c.id]?.some(t => t.id === data.thread_id)
  )?.id;
  if (channelId) {
    get().refreshWardRoomThreads(channelId);
  }
  break;
}
```

If the SSE handling pattern for ward_room events is different (e.g., using the event's `channel_id` directly), follow the existing pattern instead.

## Part 6: Update WardRoomConfig

**File:** `src/probos/config.py`

Add the default responder cap to WardRoomConfig (line ~270):

```python
class WardRoomConfig(BaseModel):
    """Ward Room communication fabric configuration (AD-407)."""
    enabled: bool = False
    max_agent_rounds: int = 3
    agent_cooldown_seconds: float = 45
    max_agent_responses_per_thread: int = 3
    default_discuss_responder_cap: int = 3  # AD-424: Default max_responders for DISCUSS
```

**File:** `src/probos/runtime.py`

When Captain creates a Ward Room thread via the shell or direct API without specifying `max_responders`, use the config default. This applies to `_deliver_bridge_alert()` (already uses `thread_mode="inform"`, no cap needed for INFORM) and any future Captain Ward Room posting.

No change needed for bridge alerts (INFORM mode doesn't use responder cap). The config default is primarily for programmatic thread creation where a cap is desired but the caller doesn't specify one.

## Part 7: Tests

**File:** `tests/test_ward_room.py` (add to existing file)

Add a new test class `TestThreadClassification` with these tests:

### Test 1: `test_create_thread_default_mode`
- Create a thread without specifying `thread_mode`
- Assert `thread.thread_mode == "discuss"` (backward compat)
- Assert `thread.max_responders == 0` (unlimited)

### Test 2: `test_create_thread_inform_mode`
- Create a thread with `thread_mode="inform"`
- Assert `thread.thread_mode == "inform"`
- Retrieve it with `get_thread()`, assert mode persists

### Test 3: `test_create_thread_action_mode`
- Create a thread with `thread_mode="action"`
- Assert `thread.thread_mode == "action"`

### Test 4: `test_create_thread_with_responder_cap`
- Create a thread with `thread_mode="discuss"`, `max_responders=3`
- Assert `thread.max_responders == 3`

### Test 5: `test_update_thread_lock`
- Create a thread
- Call `update_thread(thread_id, locked=True)`
- Assert returned thread has `locked == True`
- Verify `get_thread()` also shows locked
- Verify creating a post on the locked thread raises (existing behavior)

### Test 6: `test_update_thread_reclassify`
- Create a thread with `thread_mode="inform"`
- Call `update_thread(thread_id, thread_mode="discuss")`
- Assert thread_mode changed to `"discuss"`

### Test 7: `test_update_thread_responder_cap`
- Create a thread
- Call `update_thread(thread_id, max_responders=5)`
- Assert `thread.max_responders == 5`

### Test 8: `test_update_thread_emits_event`
- Create a thread
- Clear captured events
- Call `update_thread(thread_id, locked=True)`
- Assert a `ward_room_thread_updated` event was emitted with `thread_id` and `{"locked": True}` in updates

### Test 9: `test_thread_mode_in_event`
- Create a thread with `thread_mode="inform"`
- Assert the `ward_room_thread_created` event includes `thread_mode: "inform"`

### Test 10: `test_schema_migration`
- Create a WardRoomService with a DB that was created WITHOUT the new columns (simulate by creating the old schema manually, then starting a new service on the same DB)
- Assert the service starts successfully (migration runs)
- Create a thread, assert `thread_mode == "discuss"`

---

**File:** `tests/test_ward_room_agents.py` (add to existing file)

Add a new test class `TestThreadModeRouting` with these tests, using the existing `_make_mock_runtime()` pattern:

### Test 11: `test_inform_thread_no_agent_notification`
- Create a mock runtime with a real WardRoomService
- Create an INFORM thread on the ship channel
- Call `_route_ward_room_event("ward_room_thread_created", {...})`
- Assert `intent_bus.send` was NOT called (no agents notified)

### Test 12: `test_discuss_thread_notifies_agents`
- Create a DISCUSS thread on the ship channel
- Call `_route_ward_room_event("ward_room_thread_created", {...})`
- Assert `intent_bus.send` WAS called (agents notified)

### Test 13: `test_discuss_ship_wide_lieutenant_can_respond`
- Create a mock runtime with earned agency enabled
- Set all agents to trust 0.5 (Lieutenant)
- Create a DISCUSS thread on the ship channel (author_id="captain")
- Call `_find_ward_room_targets()` with `thread_mode="discuss"`
- Assert at least one agent is in the returned targets
- *This directly validates BF-022 is fixed*

### Test 14: `test_inform_not_passed_to_targets`
- Explicitly verify that for INFORM threads, `_find_ward_room_targets()` is never called (routing short-circuits in `_route_ward_room_event`)

### Test 15: `test_discuss_responder_cap_applied`
- Create a mock runtime with 5 crew agents
- Create a DISCUSS thread with `max_responders=2`
- Call `_route_ward_room_event("ward_room_thread_created", {...})`
- Assert `intent_bus.send` was called at most 2 times

### Test 16: `test_action_only_mentions`
- Create an ACTION thread with @mentions for 2 specific agents
- Call `_route_ward_room_event("ward_room_thread_created", {...})`
- Assert only the 2 @mentioned agents were notified (existing BF-016a behavior)

---

**File:** `tests/test_earned_agency.py` (add to existing class or new class)

### Test 17: `test_lieutenant_ship_wide_discuss_can_respond`
- `can_respond_ambient(Rank.LIEUTENANT, is_captain_post=True, same_department=True)` → `True`
- *This test already exists (testing Lieutenant captain+same_dept). Verify it passes — no new test needed if covered.*

---

**File:** `tests/test_api_wardroom.py` (add to existing file)

### Test 18: `test_patch_thread_lock`
- POST to create a thread
- PATCH `/api/wardroom/threads/{id}` with `{"locked": true}`
- Assert 200 response with `locked: true`

### Test 19: `test_patch_thread_reclassify`
- POST to create an INFORM thread (pass `thread_mode` in create request — update `CreateThreadRequest` if needed)
- PATCH to reclassify to DISCUSS
- GET the thread, assert `thread_mode == "discuss"`

### Test 20: `test_patch_thread_not_found`
- PATCH `/api/wardroom/threads/nonexistent` with `{"locked": true}`
- Assert 404

## Part 8: Update CreateThreadRequest for API

**File:** `src/probos/api.py`

Update `CreateThreadRequest` (line ~198) to include the new fields:

```python
class CreateThreadRequest(BaseModel):
    author_id: str
    title: str
    body: str
    author_callsign: str = ""
    thread_mode: str = "discuss"      # AD-424
    max_responders: int = 0           # AD-424
```

Update the `wardroom_create_thread()` handler to pass these through to `ward_room.create_thread()`.

## Verification

After implementation:
1. Run `uv run pytest tests/test_ward_room.py -x -v` — all tests pass (existing + new)
2. Run `uv run pytest tests/test_ward_room_agents.py -x -v` — all tests pass (existing + new)
3. Run `uv run pytest tests/test_earned_agency.py -x -v` — no regressions
4. Run `uv run pytest tests/test_bridge_alerts.py -x -v` — no regressions
5. Run `uv run pytest tests/test_api_wardroom.py -x -v` — all tests pass (existing + new)
6. Run `uv run pytest tests/ -x -q` — full suite clean

## Summary

| Part | File | Change |
|------|------|--------|
| 1 | ward_room.py | `thread_mode` + `max_responders` fields on dataclass, schema, create_thread(), update_thread() |
| 2 | runtime.py | Bridge alerts use `thread_mode="inform"` |
| 3 | runtime.py | INFORM threads skip notification; DISCUSS threads relax earned agency for ship-wide; responder cap |
| 4 | api.py | `PATCH /api/wardroom/threads/{id}` + UpdateThreadRequest |
| 5 | types.ts + useStore.ts | TypeScript types + SSE handler for thread updates |
| 6 | config.py | `default_discuss_responder_cap` in WardRoomConfig |
| 7 | test files | ~20 new tests across 4 test files |
| 8 | api.py | Update CreateThreadRequest with thread_mode + max_responders |

**After this AD:**
- **BF-022 FIXED:** DISCUSS threads on ship-wide channels pass `same_department=True` to earned agency → Lieutenants can respond.
- **Bridge alerts silent:** INFORM threads don't trigger any agent LLM calls — no notification, no response attempts.
- **Reply-all prevention:** DISCUSS threads support `max_responders` cap. Default configurable.
- **Captain control:** PATCH endpoint lets Captain reclassify threads (INFORM → DISCUSS to open discussion), lock/unlock, adjust responder cap at runtime.
- **Backward compatible:** All existing threads default to `thread_mode="discuss"`, `max_responders=0` (unlimited).
