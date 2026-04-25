# AD-425: Ward Room Active Browsing — Build Prompt

## Context

Crew agents currently receive Ward Room content through two passive paths only:
1. **Real-time push** — `ward_room_notification` intents when a thread targets them (AD-424 thread modes)
2. **Proactive context injection** — recent department channel activity injected into proactive thinks (AD-413)

Agents **cannot independently browse** the Ward Room. They can't check All Hands, read threads from other departments, or review historical conversations. They only know what's pushed to them.

AD-425 gives agents the ability to actively read the Ward Room — like walking up to the bulletin board instead of waiting for someone to hand you a notice.

## Architecture Decision

**This is NOT a Skill (in the `Skill` dataclass sense).** The `Skill` pattern in ProbOS is for dynamically-designed capabilities created by the self-mod pipeline. Ward Room browsing is a core communication function — it belongs in the proactive loop's context gathering, the Ward Room service itself, and the REST API.

**Three changes:**
1. **WardRoomService gets a new query method** — `browse_threads()` for cross-channel thread discovery
2. **Proactive context expands** — All Hands activity added alongside department channel activity
3. **REST API gets a new endpoint** — activity feed for HXI display
4. **Read receipts wired** — `update_last_seen()` called after proactive context consumption

---

## Part 1: WardRoomService — `browse_threads()` method

**File:** `src/probos/ward_room.py`

Add a new public method `browse_threads()` that supports cross-channel thread discovery with earned-agency-aware scoping.

```python
async def browse_threads(
    self,
    agent_id: str,
    channels: list[str] | None = None,
    thread_mode: str | None = None,
    limit: int = 10,
    since: float = 0.0,
) -> list[WardRoomThread]:
    """Browse threads across one or more channels.

    Args:
        agent_id: The browsing agent (for read receipt tracking).
        channels: Channel IDs to browse. None = all subscribed channels.
        thread_mode: Filter by thread mode ("discuss", "inform", "action"). None = all.
        limit: Max threads to return.
        since: Only threads with last_activity after this epoch timestamp.

    Returns:
        List of WardRoomThread sorted by last_activity descending.
    """
```

**Implementation:**
- If `channels` is None, query the `memberships` table for all channels the agent is subscribed to, collect their IDs
- Query `threads` table with `WHERE channel_id IN (?) AND last_activity > ?`, optionally filtered by `thread_mode`
- Order by `last_activity DESC`, limit
- Hydrate into `WardRoomThread` dataclasses with view-meta (author_callsign, channel_name) — follow the same pattern as `list_threads()`
- Do NOT call `update_last_seen` here — that happens separately (the agent may browse but not "consume")

**Tests (in `tests/test_ward_room.py`):**
Add a new test class `TestBrowseThreads`:

| Test | What it validates |
|------|------------------|
| `test_browse_all_subscribed_channels` | Agent subscribed to 2 channels, browse with `channels=None` returns threads from both |
| `test_browse_specific_channel` | Pass explicit `channels=["ch1"]`, only get threads from ch1 |
| `test_browse_thread_mode_filter` | Create INFORM and DISCUSS threads, filter by `thread_mode="discuss"` returns only DISCUSS |
| `test_browse_since_filter` | Create old and new threads, `since` filters correctly |
| `test_browse_limit` | Create 5 threads, `limit=3` returns 3 most recent |
| `test_browse_empty_result` | No matching threads returns empty list |

---

## Part 2: Proactive Context Expansion — All Hands Activity

**File:** `src/probos/proactive.py`

Currently `_gather_context()` (around lines 306-337) only pulls recent activity from the agent's **department channel**. Expand to also include **All Hands** activity (ship-wide channel).

**Changes to `_gather_context()`:**

After the existing department channel lookup and `get_recent_activity()` call, add a second block:

```python
# AD-425: Also include recent All Hands activity (ship-wide)
all_hands_ch = None
for ch in channels:
    if ch.channel_type == "ship":
        all_hands_ch = ch
        break

if all_hands_ch and all_hands_ch.id != dept_channel_id:
    all_hands_activity = await rt.ward_room.get_recent_activity(
        all_hands_ch.id, since=since, limit=3
    )
    # Filter: only DISCUSS threads (INFORM already consumed, ACTION is targeted)
    all_hands_filtered = [
        a for a in all_hands_activity
        if a.get("thread_mode") != "inform"
    ]
    if all_hands_filtered:
        if "ward_room_activity" not in context:
            context["ward_room_activity"] = []
        context["ward_room_activity"].extend([
            {
                "type": item["type"],
                "author": item.get("author", "unknown"),
                "body": item.get("body", "")[:150],
                "channel": "All Hands",
            }
            for item in all_hands_filtered[:3]
        ])
```

**Important:** `get_recent_activity()` currently returns dicts with keys `{type, author, title, body, created_at}`. Check if it also returns `thread_mode`. If not, the filtering needs adjustment — see Part 2a below.

### Part 2a: Update `get_recent_activity()` to include `thread_mode`

**File:** `src/probos/ward_room.py`

In the `get_recent_activity()` method, the thread query already joins on the threads table. Add `thread_mode` to the returned dict for thread-type entries:

```python
# In the thread query results formatting:
{
    "type": "thread",
    "author": row["author_id"],
    "title": row["title"],
    "body": row["body"],
    "created_at": row["created_at"],
    "thread_mode": row["thread_mode"],  # ADD THIS
}
```

If `get_recent_activity()` also returns post-type entries, those should inherit the parent thread's `thread_mode`. The simplest approach: for post entries, join against threads to get the mode, or omit `thread_mode` (posts in INFORM threads shouldn't exist anyway since INFORM threads don't accept replies).

**Tests (in `tests/test_ward_room.py`):**
Add to `TestWardRoomRecentActivity`:

| Test | What it validates |
|------|------------------|
| `test_recent_activity_includes_thread_mode` | `get_recent_activity()` result dicts include `thread_mode` field |

---

## Part 3: Proactive Read Receipt — Mark Ward Room as Seen

**File:** `src/probos/proactive.py`

After `_gather_context()` successfully retrieves Ward Room activity for an agent, call `update_last_seen()` to mark that channel as read. This prevents the same threads from appearing in context repeatedly.

**Changes to `_gather_context()`:**

After the department channel activity retrieval:
```python
if ward_room_activity:
    # AD-425: Mark channel as seen after consuming activity
    try:
        await rt.ward_room.update_last_seen(agent.id, dept_channel.id)
    except Exception:
        pass  # Non-critical — don't block proactive think
```

After the All Hands activity retrieval (Part 2):
```python
if all_hands_filtered:
    try:
        await rt.ward_room.update_last_seen(agent.id, all_hands_ch.id)
    except Exception:
        pass
```

**Tests (in `tests/test_proactive.py`):**
Add to `TestProactiveWardRoomContext`:

| Test | What it validates |
|------|------------------|
| `test_ward_room_context_marks_seen` | After `_gather_context()`, `ward_room.update_last_seen` was called with the agent's department channel |
| `test_all_hands_context_marks_seen` | After `_gather_context()`, `ward_room.update_last_seen` was called with All Hands channel |

---

## Part 4: REST API — Activity Feed Endpoint

**File:** `src/probos/api.py`

Add a new endpoint for the HXI to display Ward Room activity across channels.

```python
@router.get("/api/wardroom/activity")
async def get_ward_room_activity(
    agent_id: str | None = None,
    channel_id: str | None = None,
    thread_mode: str | None = None,
    limit: int = 20,
    since: float = 0.0,
):
    """Browse Ward Room threads across channels.

    Query params:
        agent_id: Scope to agent's subscribed channels (optional).
        channel_id: Specific channel (optional, overrides agent_id scoping).
        thread_mode: Filter by mode — discuss, inform, action (optional).
        limit: Max threads (default 20).
        since: Epoch timestamp filter (default 0 = all).
    """
```

**Implementation:**
- If `channel_id` is provided, call `ward_room.list_threads(channel_id, limit=limit)` and filter by `thread_mode` / `since` if needed
- If `agent_id` is provided (no `channel_id`), call `ward_room.browse_threads(agent_id, thread_mode=thread_mode, limit=limit, since=since)`
- If neither, call `ward_room.browse_threads("_anonymous", limit=limit, since=since)` — returns threads from all channels (HXI Captain view)
- Return list of thread dicts: `[asdict(t) for t in threads]`
- Guard: `if not runtime.ward_room:` return empty list

**Also add:** A PUT endpoint to mark Ward Room as read:

```python
@router.put("/api/wardroom/channels/{channel_id}/seen")
async def mark_channel_seen(channel_id: str, agent_id: str):
    """Mark all threads in a channel as seen for an agent."""
    await runtime.ward_room.update_last_seen(agent_id, channel_id)
    return {"status": "ok"}
```

**Tests (in `tests/test_api_wardroom.py`):**

| Test | What it validates |
|------|------------------|
| `test_activity_feed_returns_threads` | GET `/api/wardroom/activity` returns threads from multiple channels |
| `test_activity_feed_mode_filter` | `?thread_mode=discuss` filters correctly |
| `test_activity_feed_agent_scoped` | `?agent_id=a1` returns only threads from subscribed channels |
| `test_mark_channel_seen` | PUT `/api/wardroom/channels/{id}/seen?agent_id=a1` returns 200 |

---

## Part 5: HXI Store — TypeScript Types

**File:** `ui/src/store/types.ts`

No new TypeScript types needed beyond what already exists. The `WardRoomThread` type in the HXI store covers the response format. If not already present, ensure the type includes `thread_mode` and `max_responders` fields (AD-424 should have added these).

**File:** `ui/src/store/useStore.ts`

No store changes needed for this AD. The activity feed endpoint is a simple REST query — the HXI can call it directly when the Ward Room panel is open (no WebSocket subscription needed for browsing).

---

## Part 6: Membership Auto-Subscribe on Crew Registration

**File:** `src/probos/runtime.py`

When crew agents are registered with the Ward Room (in the startup sequence where `_WARD_ROOM_CREW` agents are processed), ensure they are **subscribed to their department channel AND All Hands**. This ensures `browse_threads(agent_id, channels=None)` returns results from both.

**Check if this already happens.** Search for `ward_room.subscribe` calls in runtime.py. If crew agents are already subscribed to both channels, skip this part. If they're only subscribed to their department channel, add:

```python
# Auto-subscribe to All Hands (ship-wide)
for ch in channels:
    if ch.channel_type == "ship":
        await self.ward_room.subscribe(agent.id, ch.id)
        break
```

**Tests (in `tests/test_ward_room_agents.py`):**
If subscription wiring is added to runtime, add:

| Test | What it validates |
|------|------------------|
| `test_crew_subscribed_to_all_hands` | After runtime setup, crew agents have memberships in both department and All Hands channels |

---

## Verification

```bash
# Targeted tests
uv run pytest tests/test_ward_room.py -x -v -k "browse"
uv run pytest tests/test_proactive.py -x -v -k "ward_room"
uv run pytest tests/test_api_wardroom.py -x -v -k "activity or seen"

# Regression
uv run pytest tests/test_ward_room.py tests/test_proactive.py tests/test_api_wardroom.py tests/test_ward_room_agents.py -x -v

# Full suite
uv run pytest tests/ --tb=short -q
```

## What This Does NOT Change

- Ward Room thread classification (AD-424 — already complete)
- Ward Room endorsement system (AD-426 — future)
- Agent duty schedules (AD-419 — already complete, "check Ward Room" duty is future)
- Earned agency gates for cross-department browsing (mentioned in roadmap design but deferred — all crew can currently see all channels they're subscribed to, which is sufficient for now)
- Proactive loop think frequency or cooldown logic
- Thread routing (`_route_ward_room_event`) — browsing is read-only, separate from notification routing

## Summary of Changes

| Part | File | Lines | Description |
|------|------|-------|-------------|
| 1 | `src/probos/ward_room.py` | ~40 | `browse_threads()` cross-channel query method |
| 2 | `src/probos/proactive.py` | ~25 | All Hands context in `_gather_context()` |
| 2a | `src/probos/ward_room.py` | ~5 | `thread_mode` in `get_recent_activity()` results |
| 3 | `src/probos/proactive.py` | ~10 | Read receipt after context consumption |
| 4 | `src/probos/api.py` | ~40 | Activity feed + mark-seen endpoints |
| 5 | `ui/src/store/types.ts` | ~0 | Verify existing types sufficient |
| 6 | `src/probos/runtime.py` | ~5 | Auto-subscribe crew to All Hands (if missing) |
| Tests | 4 test files | ~100 | ~12-14 new tests |
