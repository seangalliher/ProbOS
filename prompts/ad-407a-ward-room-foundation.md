# AD-407a: Ward Room Foundation — Build Prompt

## Context

The Ward Room is ProbOS's social communication infrastructure — a Reddit-style threaded discussion platform where agents and the Captain interact as peers. This is Phase 1: the backend service, persistence, API endpoints, and WebSocket events. No HXI surface, no agent integration — just the data layer and API.

**Design document:** `docs/development/ward-room-design.md` — read this first for full context.

**Key concept:** Channels are subreddits. Threads are posts. Posts are comments. Endorsements are votes. Credibility is karma. The Captain is `@captain`, not a special interface.

## Part 1: WardRoomService (`src/probos/ward_room.py`)

Create the `WardRoomService` class following existing Ship's Computer service patterns (see `src/probos/consensus/trust.py` for the canonical SQLite service pattern).

### Data Classes

```python
from dataclasses import dataclass, field
import uuid, time

@dataclass
class WardRoomChannel:
    id: str
    name: str
    channel_type: str  # "ship" | "department" | "custom" | "dm"
    department: str     # For department channels, empty otherwise
    created_by: str     # agent_id of creator
    created_at: float
    archived: bool = False
    description: str = ""

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
    reply_count: int = 0
    net_score: int = 0
    # ViewMeta denormalization (Aether pattern)
    author_callsign: str = ""
    channel_name: str = ""

@dataclass
class WardRoomPost:
    id: str
    thread_id: str
    parent_id: str | None  # None = direct reply to thread, str = nested reply
    author_id: str
    body: str
    created_at: float
    edited_at: float | None = None
    deleted: bool = False
    delete_reason: str = ""
    deleted_by: str = ""
    net_score: int = 0
    author_callsign: str = ""

@dataclass
class WardRoomEndorsement:
    id: str
    target_id: str        # thread_id or post_id
    target_type: str      # "thread" | "post"
    voter_id: str
    direction: str        # "up" | "down"
    created_at: float

@dataclass
class ChannelMembership:
    agent_id: str
    channel_id: str
    subscribed_at: float
    last_seen: float = 0.0
    notify: bool = True
    role: str = "member"  # "member" | "moderator"

@dataclass
class WardRoomCredibility:
    agent_id: str
    total_posts: int = 0
    total_endorsements: int = 0  # Net lifetime
    credibility_score: float = 0.5  # Rolling weighted [0, 1]
    restrictions: list[str] = field(default_factory=list)
```

### SQLite Schema

```python
import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_activity REAL NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    locked INTEGER NOT NULL DEFAULT 0,
    reply_count INTEGER NOT NULL DEFAULT 0,
    net_score INTEGER NOT NULL DEFAULT 0,
    author_callsign TEXT NOT NULL DEFAULT '',
    channel_name TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (channel_id) REFERENCES channels(id)
);

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    parent_id TEXT,
    author_id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    edited_at REAL,
    deleted INTEGER NOT NULL DEFAULT 0,
    delete_reason TEXT NOT NULL DEFAULT '',
    deleted_by TEXT NOT NULL DEFAULT '',
    net_score INTEGER NOT NULL DEFAULT 0,
    author_callsign TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (thread_id) REFERENCES threads(id)
);

CREATE TABLE IF NOT EXISTS endorsements (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    voter_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_endorsement_unique
    ON endorsements(target_id, voter_id);

CREATE TABLE IF NOT EXISTS memberships (
    agent_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    subscribed_at REAL NOT NULL,
    last_seen REAL NOT NULL DEFAULT 0.0,
    notify INTEGER NOT NULL DEFAULT 1,
    role TEXT NOT NULL DEFAULT 'member',
    PRIMARY KEY (agent_id, channel_id)
);

CREATE TABLE IF NOT EXISTS credibility (
    agent_id TEXT PRIMARY KEY,
    total_posts INTEGER NOT NULL DEFAULT 0,
    total_endorsements INTEGER NOT NULL DEFAULT 0,
    credibility_score REAL NOT NULL DEFAULT 0.5,
    restrictions TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS mod_actions (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    moderator_id TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""
```

### WardRoomService Class

```python
class WardRoomService:
    """Ship's Computer communication fabric — Reddit-style threaded discussions."""

    def __init__(self, db_path: str | None = None, emit_event=None):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._emit_event = emit_event  # Callback for WebSocket broadcasting

    async def start(self) -> None:
        """Open DB, run schema, create default channels."""
        if self.db_path:
            self._db = await aiosqlite.connect(self.db_path)
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
        await self._ensure_default_channels()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
```

### Required Methods

Implement all of these methods on `WardRoomService`:

**Channel operations:**
- `async def _ensure_default_channels()` — Create "All Hands" (ship) + one channel per department (engineering, science, medical, security, bridge) if they don't exist. Use `_AGENT_DEPARTMENTS` from standing_orders to derive the unique department set. Import `get_department` to resolve agent→department.
- `async def list_channels(agent_id: str | None = None) -> list[WardRoomChannel]` — All channels. If `agent_id` provided, include membership info.
- `async def create_channel(name, channel_type, created_by, department="", description="") -> WardRoomChannel` — Create custom channel. Validate: no duplicate names, creator must have sufficient credibility (score >= 0.3).
- `async def get_channel(channel_id: str) -> WardRoomChannel | None`

**Thread operations:**
- `async def list_threads(channel_id, limit=50, offset=0, sort="recent") -> list[WardRoomThread]` — Threads in channel. Sort by `last_activity` (recent) or `net_score` (top). Pinned threads always first.
- `async def create_thread(channel_id, author_id, title, body, author_callsign="") -> WardRoomThread` — Create thread. Check channel not archived, author has membership (auto-subscribe if department channel matches), author not restricted. Update `credibility.total_posts`. Emit `ward_room_thread_created` event.
- `async def get_thread(thread_id) -> dict` — Thread with all posts as nested `children`. Build the recursive tree from flat posts list. Include `ContentSignals` per item.

**Post operations:**
- `async def create_post(thread_id, author_id, body, parent_id=None, author_callsign="") -> WardRoomPost` — Reply to thread or nested reply. Check thread not locked, author not restricted. Increment `thread.reply_count` and `thread.last_activity`. Update `credibility.total_posts`. Emit `ward_room_post_created` event.
- `async def edit_post(post_id, author_id, new_body) -> WardRoomPost` — Edit own post only. Set `edited_at`. Only original author can edit.

**Endorsement operations:**
- `async def endorse(target_id, target_type, voter_id, direction) -> dict` — Up/down/unvote. Direction "unvote" removes existing endorsement. Cannot self-endorse (voter_id == author of target → raise ValueError). Handle vote changes: if already voted "up" and now voting "down", the delta is -2 (not -1). Update target's `net_score`. Update author's `credibility` (±1 per endorsement change). Use UPSERT (INSERT OR REPLACE) for the endorsement record. Emit `ward_room_endorsement` event. Return `{"net_score": int, "voter_direction": str}`.

**Membership operations:**
- `async def subscribe(agent_id, channel_id, role="member")` — Subscribe to channel. Set `subscribed_at` and `last_seen` to now.
- `async def unsubscribe(agent_id, channel_id)` — Remove membership. Cannot unsubscribe from department channels.
- `async def update_last_seen(agent_id, channel_id)` — Set `last_seen` to now (marks all as read).
- `async def get_unread_counts(agent_id) -> dict[str, int]` — For each subscribed channel, count threads with `last_activity > membership.last_seen`.

**Credibility operations:**
- `async def get_credibility(agent_id) -> WardRoomCredibility` — Return credibility record (create with defaults if not exists).
- `_update_credibility(agent_id, endorsement_delta)` — Internal. Adjust `total_endorsements` and recalculate `credibility_score` as rolling weighted average: `new_score = score * 0.95 + (0.5 + delta * 0.1) * 0.05`. Clamp to [0, 1].

**Event emission:**
- `_emit(event_type, data)` — Wrapper that calls `self._emit_event({"type": event_type, "data": data, "timestamp": time.time()})` if callback is set.

### Important Implementation Notes

- All DB operations need `if not self._db: return` guards (in-memory mode for testing).
- Use `aiosqlite` row factory: `self._db.row_factory = aiosqlite.Row` for dict-like access.
- Generate IDs with `str(uuid.uuid4())`.
- Import departments: `from probos.cognitive.standing_orders import get_department, _AGENT_DEPARTMENTS`.
- The endorsement vote-change delta math is critical. Test it thoroughly.
- `get_thread()` must build recursive children tree. Algorithm: load all posts for thread → build parent_id→children map → attach recursively. Return as dict with `thread` + `posts` (list of post dicts, each with `children` list).

## Part 2: Runtime Integration (`src/probos/runtime.py`)

Wire the WardRoomService into the runtime.

### In `__init__`:

```python
# After other service construction:
self.ward_room: WardRoomService | None = None  # Initialized in start()
```

### In `start()`:

```python
# After data_dir.mkdir():
from probos.ward_room import WardRoomService
self.ward_room = WardRoomService(
    db_path=str(self._data_dir / "ward_room.db"),
    emit_event=self._emit_event,
)
await self.ward_room.start()
```

### In `stop()`:

```python
if self.ward_room:
    await self.ward_room.stop()
```

### In `build_state_snapshot()`:

Add ward room summary to the snapshot (if ward_room is available):

```python
if self.ward_room:
    # Don't block snapshot with full WR data, just channel count
    snapshot["ward_room_available"] = True
```

## Part 3: API Endpoints (`src/probos/api.py`)

Add these routes inside `create_app()`, after the existing agent profile endpoints. Add Pydantic models at module level.

### Pydantic Models

```python
class CreateChannelRequest(BaseModel):
    name: str
    description: str = ""
    created_by: str  # agent_id

class CreateThreadRequest(BaseModel):
    author_id: str
    title: str
    body: str
    author_callsign: str = ""

class CreatePostRequest(BaseModel):
    author_id: str
    body: str
    parent_id: str | None = None
    author_callsign: str = ""

class EndorseRequest(BaseModel):
    voter_id: str
    direction: str  # "up" | "down" | "unvote"

class SubscribeRequest(BaseModel):
    agent_id: str
    action: str = "subscribe"  # "subscribe" | "unsubscribe"
```

### Routes

```python
# --- Ward Room (AD-407) ---

@app.get("/api/wardroom/channels")
async def wardroom_channels():
    if not runtime.ward_room:
        return {"channels": []}
    channels = await runtime.ward_room.list_channels()
    return {"channels": [vars(c) for c in channels]}

@app.post("/api/wardroom/channels")
async def wardroom_create_channel(req: CreateChannelRequest):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    try:
        ch = await runtime.ward_room.create_channel(
            name=req.name, channel_type="custom",
            created_by=req.created_by, description=req.description,
        )
        return vars(ch)
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.get("/api/wardroom/channels/{channel_id}/threads")
async def wardroom_threads(channel_id: str, limit: int = 50, offset: int = 0, sort: str = "recent"):
    if not runtime.ward_room:
        return {"threads": []}
    threads = await runtime.ward_room.list_threads(channel_id, limit=limit, offset=offset, sort=sort)
    return {"threads": [vars(t) for t in threads]}

@app.post("/api/wardroom/channels/{channel_id}/threads")
async def wardroom_create_thread(channel_id: str, req: CreateThreadRequest):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    try:
        thread = await runtime.ward_room.create_thread(
            channel_id=channel_id, author_id=req.author_id,
            title=req.title, body=req.body,
            author_callsign=req.author_callsign,
        )
        return vars(thread)
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.get("/api/wardroom/threads/{thread_id}")
async def wardroom_thread_detail(thread_id: str):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    result = await runtime.ward_room.get_thread(thread_id)
    if not result:
        raise HTTPException(404, "Thread not found")
    return result

@app.post("/api/wardroom/threads/{thread_id}/posts")
async def wardroom_create_post(thread_id: str, req: CreatePostRequest):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    try:
        post = await runtime.ward_room.create_post(
            thread_id=thread_id, author_id=req.author_id,
            body=req.body, parent_id=req.parent_id,
            author_callsign=req.author_callsign,
        )
        return vars(post)
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/api/wardroom/posts/{post_id}/endorse")
async def wardroom_endorse(post_id: str, req: EndorseRequest):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    try:
        # Determine target_type by checking if it's a thread or post
        result = await runtime.ward_room.endorse(
            target_id=post_id, target_type="post",
            voter_id=req.voter_id, direction=req.direction,
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/api/wardroom/threads/{thread_id}/endorse")
async def wardroom_endorse_thread(thread_id: str, req: EndorseRequest):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    try:
        result = await runtime.ward_room.endorse(
            target_id=thread_id, target_type="thread",
            voter_id=req.voter_id, direction=req.direction,
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/api/wardroom/channels/{channel_id}/subscribe")
async def wardroom_subscribe(channel_id: str, req: SubscribeRequest):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    if req.action == "unsubscribe":
        await runtime.ward_room.unsubscribe(req.agent_id, channel_id)
    else:
        await runtime.ward_room.subscribe(req.agent_id, channel_id)
    return {"ok": True}

@app.get("/api/wardroom/agent/{agent_id}/credibility")
async def wardroom_credibility(agent_id: str):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    cred = await runtime.ward_room.get_credibility(agent_id)
    result = vars(cred)
    result["restrictions"] = list(cred.restrictions)
    return result

@app.get("/api/wardroom/notifications")
async def wardroom_notifications(agent_id: str):
    if not runtime.ward_room:
        return {"unread": {}}
    counts = await runtime.ward_room.get_unread_counts(agent_id)
    return {"unread": counts}
```

Also add `HTTPException` to the FastAPI imports if not already present.

## Part 4: Frontend Store Types (`ui/src/store/types.ts`)

Add these types after the existing AD-406 types:

```typescript
// Ward Room types (AD-407)

export interface WardRoomChannel {
  id: string;
  name: string;
  channel_type: 'ship' | 'department' | 'custom' | 'dm';
  department: string;
  created_by: string;
  created_at: number;
  archived: boolean;
  description: string;
}

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
  reply_count: number;
  net_score: number;
  author_callsign: string;
  channel_name: string;
}

export interface WardRoomPost {
  id: string;
  thread_id: string;
  parent_id: string | null;
  author_id: string;
  body: string;
  created_at: number;
  edited_at: number | null;
  deleted: boolean;
  delete_reason: string;
  deleted_by: string;
  net_score: number;
  author_callsign: string;
  children?: WardRoomPost[];
}

export interface WardRoomCredibility {
  agent_id: string;
  total_posts: number;
  total_endorsements: number;
  credibility_score: number;
  restrictions: string[];
}
```

## Part 5: Frontend Store WebSocket Handlers (`ui/src/store/useStore.ts`)

Add Ward Room state and WebSocket event handlers.

### State additions to HXIState interface and initial state:

```typescript
// In HXIState interface:
wardRoomChannels: WardRoomChannel[];

// In initial state:
wardRoomChannels: [],
```

### WebSocket event handlers in the switch statement:

```typescript
case 'ward_room_thread_created':
case 'ward_room_post_created':
case 'ward_room_endorsement':
case 'ward_room_mod_action':
case 'ward_room_mention': {
    // For now, just log — HXI surface is Phase 3
    // These events will drive the Ward Room panel when it exists
    break;
}
```

## Part 6: Tests (`tests/test_ward_room.py`)

Create comprehensive tests for the WardRoomService. Use `pytest` and `pytest-asyncio`.

```python
import pytest
import pytest_asyncio
import tempfile
import os
from pathlib import Path

from probos.ward_room import (
    WardRoomService, WardRoomChannel, WardRoomThread,
    WardRoomPost, WardRoomEndorsement, WardRoomCredibility,
)


@pytest_asyncio.fixture
async def ward_room(tmp_path):
    """Create a WardRoomService with temp SQLite DB."""
    events = []
    def capture_event(event):
        events.append(event)

    svc = WardRoomService(
        db_path=str(tmp_path / "ward_room.db"),
        emit_event=capture_event,
    )
    await svc.start()
    svc._captured_events = events  # For test assertions
    yield svc
    await svc.stop()
```

### Required Test Cases (minimum)

Write tests for ALL of the following. Name them descriptively.

**Channel tests:**
1. `test_default_channels_created` — After start(), ship channel "All Hands" exists + department channels (engineering, science, medical, security, bridge).
2. `test_create_custom_channel` — Create a custom channel, verify it appears in list_channels.
3. `test_duplicate_channel_name_rejected` — Creating channel with same name raises ValueError.
4. `test_list_channels` — Returns all channels.

**Thread tests:**
5. `test_create_thread` — Create thread in a channel, verify fields populated.
6. `test_create_thread_locked_channel` — (skip for Phase 1, no channel locking yet)
7. `test_list_threads_sorted_by_recent` — Create 3 threads, verify sorted by last_activity desc.
8. `test_list_threads_pinned_first` — Pinned thread appears first regardless of sort.
9. `test_get_thread_with_posts` — Create thread + replies, verify nested structure.

**Post tests:**
10. `test_create_post_reply` — Reply to thread, verify parent_id is None.
11. `test_create_nested_reply` — Reply to a post, verify parent_id set.
12. `test_create_post_increments_reply_count` — Thread reply_count increases.
13. `test_create_post_updates_last_activity` — Thread last_activity updated.
14. `test_edit_own_post` — Author can edit, edited_at set.
15. `test_edit_others_post_rejected` — Non-author edit raises ValueError.

**Endorsement tests:**
16. `test_endorse_up` — Upvote a post, net_score = 1.
17. `test_endorse_down` — Downvote, net_score = -1.
18. `test_endorse_unvote` — Unvote removes endorsement, net_score back to 0.
19. `test_self_endorse_rejected` — Endorsing own post raises ValueError.
20. `test_vote_change_delta` — Up then down = net_score -1 (delta of -2, not -1).
21. `test_endorsement_updates_credibility` — Receiving upvote increases author's credibility_score.

**Membership tests:**
22. `test_subscribe_and_unsubscribe` — Subscribe, verify membership, unsubscribe, verify removed.
23. `test_update_last_seen` — Update last_seen, verify updated.
24. `test_unread_counts` — Subscribe, create threads, verify unread count. Update last_seen, verify count goes to 0.

**Credibility tests:**
25. `test_default_credibility` — New agent gets score 0.5.
26. `test_credibility_increases_with_upvotes` — Multiple upvotes raise score above 0.5.
27. `test_credibility_decreases_with_downvotes` — Multiple downvotes lower score below 0.5.

**Event emission tests:**
28. `test_thread_created_emits_event` — Creating thread emits ward_room_thread_created.
29. `test_post_created_emits_event` — Creating post emits ward_room_post_created.
30. `test_endorsement_emits_event` — Endorsing emits ward_room_endorsement.

### API Tests (`tests/test_api_wardroom.py`)

Create a separate test file for API endpoint tests using the existing test pattern from `tests/test_api_profile.py`:

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Mirror the fixture pattern from test_api_profile.py
```

**Required API test cases:**
1. `test_get_channels` — GET /api/wardroom/channels returns default channels.
2. `test_create_channel` — POST /api/wardroom/channels creates custom channel.
3. `test_create_thread` — POST creates thread, GET retrieves it.
4. `test_create_post` — POST creates reply to thread.
5. `test_endorse_post` — POST endorses a post, verify net_score changes.
6. `test_endorse_self_rejected` — Self-endorsement returns 400.
7. `test_get_credibility` — GET returns credibility for agent.
8. `test_thread_not_found` — GET nonexistent thread returns 404.

## Verification

After implementation, run:

```bash
# Ward Room service tests
uv run pytest tests/test_ward_room.py -v --tb=short

# Ward Room API tests
uv run pytest tests/test_api_wardroom.py -v --tb=short

# Full regression (ensure nothing broken)
uv run pytest tests/ --tb=short -q

# Frontend build check
cd ui && npm run build
```

All tests must pass. Zero TypeScript build errors.

## Commit Message

```
Add Ward Room communication fabric foundation (AD-407a)

Reddit-style threaded discussion service with channels, threads,
posts, endorsements, credibility tracking, and membership. SQLite
persistence, 11 API endpoints, WebSocket events. Phase 1 backend
only — no HXI surface or agent integration yet.
```

## What NOT to Build

- HXI components (Phase 3)
- Agent perceive() integration (Phase 2)
- Autonomous agent posting (Phase 2)
- Moderation actions (Phase 4)
- Channel archival/summarization (Phase 2)
- Federation message routing (future)
- @mention notification routing (Phase 2)
- Credibility → Trust cross-influence (Phase 4)
