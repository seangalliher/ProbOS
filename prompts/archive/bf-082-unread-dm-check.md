# BF-082: Unread DM Check in Proactive Duty Cycle

## Problem

Agent-to-agent DMs are fire-and-forget events. When a DM is sent, the Ward Room emits `ward_room_thread_created`, and `WardRoomRouter.route_event()` notifies the recipient. If that notification fails for any reason (pre-BF-081 routing bug, startup timing, event loop contention), the DM sits permanently unread — the recipient agent has no mechanism to discover it.

This was exposed when BF-081 was fixed: 17 DM channels existed with zero responses because the routing bug silently dropped every notification. Even after the fix, those historical DMs will never get responses because the events are gone.

## Solution

Add an **unread DM check** to the proactive duty cycle in `proactive.py`. During each agent's proactive cycle, scan their DM channels for threads where they are a participant but haven't posted a reply. Surface unread DMs to the agent for response.

## Implementation

### Step 1: Add `get_unread_dms()` to Ward Room service

**File:** `src/probos/ward_room.py`

Add a method that returns unread DM threads for a given agent:

```python
async def get_unread_dms(self, agent_id: str, limit: int = 3) -> list[dict]:
    """Return DM threads where agent_id is a participant but hasn't replied.

    A thread is 'unread' if:
    1. It's in a DM channel (channel_type = 'dm')
    2. The agent's ID prefix appears in the channel name (they're a participant)
    3. The agent has NOT authored any posts in that thread
    4. The thread is not archived

    Returns list of {"thread_id", "channel_id", "title", "body", "author_callsign", "created_at"}
    Limited to `limit` most recent unread threads to avoid flooding.
    """
```

SQL approach:
- Join `channels` (where `channel_type = 'dm'` AND `name LIKE '%{agent_id[:8]}%'`)
  with `threads` (not archived)
- LEFT JOIN `posts` where `author_id = agent_id` AND `thread_id = threads.id`
- Filter where the post join is NULL (agent hasn't replied)
- Filter where `threads.author_id != agent_id` (don't flag threads the agent created)
- ORDER BY `threads.created_at DESC`
- LIMIT `limit`

### Step 2: Add unread DM processing to proactive duty cycle

**File:** `src/probos/proactive.py`

In the `_run_proactive_cycle()` method (or equivalent), after the existing proactive thought generation, add an unread DM check:

```python
# --- Unread DM check (BF-082) ---
if hasattr(rt, 'ward_room') and rt.ward_room:
    try:
        unread_dms = await rt.ward_room.get_unread_dms(agent.id, limit=2)
        if unread_dms:
            for dm in unread_dms:
                # Build context for the agent to respond
                dm_context = (
                    f"You have an unread DM from @{dm['author_callsign']}:\n"
                    f"Subject: {dm['title']}\n"
                    f"Message: {dm['body']}\n\n"
                    f"Please respond to this message."
                )
                # Route through the same ward_room_router notification path
                # that a live event would use
                await self._notify_agent_of_dm(agent, dm)
            logger.info("BF-082: %s has %d unread DMs, notified",
                        agent.agent_type, len(unread_dms))
    except Exception as e:
        logger.warning("BF-082: Unread DM check failed for %s: %s", agent.agent_type, e)
```

### Step 3: Implement `_notify_agent_of_dm()`

**File:** `src/probos/proactive.py`

This method should reuse the existing WardRoomRouter notification path so the response goes through the same DM extraction, posting, and logging pipeline:

```python
async def _notify_agent_of_dm(self, agent, dm_info: dict) -> None:
    """Notify an agent about an unread DM by routing through WardRoomRouter."""
    if not self._ward_room_router:
        return

    # Construct the same event data that ward_room_router.route_event() expects
    event_data = {
        "thread_id": dm_info["thread_id"],
        "channel_id": dm_info["channel_id"],
        "author_id": dm_info["author_id"],
        "author_callsign": dm_info["author_callsign"],
        "title": dm_info["title"],
        "body": dm_info["body"],
    }

    # Route through the existing notification pipeline
    await self._ward_room_router.route_event("ward_room_thread_created", event_data)
```

**Important:** Add a deduplication guard so the same unread DM isn't re-notified every cycle. Options:
- Track notified thread IDs in a set on the proactive loop instance: `self._notified_dm_threads: set[str]`
- Clear the set periodically (every hour) or when it exceeds a size limit
- Only notify for DMs not already in the set

### Step 4: Return metadata from `get_unread_dms()`

The dict returned must include enough info for the notification:
```python
{
    "thread_id": str,
    "channel_id": str,
    "author_id": str,
    "author_callsign": str,
    "title": str,
    "body": str,
    "created_at": float,
}
```

To get `author_callsign`, join with the thread's author info or look up via CallsignRegistry at notification time.

## Testing

**File:** `tests/test_ward_room.py` or new `tests/test_unread_dms.py`

### Test 1: `test_get_unread_dms_returns_unanswered_threads`
- Create a DM channel between agent_a and agent_b
- Create a thread authored by agent_a
- Call `get_unread_dms(agent_b_id)` → should return the thread
- Call `get_unread_dms(agent_a_id)` → should return empty (agent_a authored it)

### Test 2: `test_get_unread_dms_excludes_answered_threads`
- Create a DM channel and thread from agent_a
- Add a post from agent_b (reply)
- Call `get_unread_dms(agent_b_id)` → should return empty (already replied)

### Test 3: `test_get_unread_dms_excludes_non_dm_channels`
- Create a department channel thread
- Call `get_unread_dms(agent_id)` → should return empty (not a DM channel)

### Test 4: `test_get_unread_dms_respects_limit`
- Create 5 unread DM threads
- Call `get_unread_dms(agent_id, limit=2)` → should return only 2

### Test 5: `test_unread_dm_deduplication`
- Verify that `_notified_dm_threads` set prevents re-notification
- First cycle: agent notified of unread DM
- Second cycle: same DM not re-notified

### Test 6: `test_proactive_cycle_checks_unread_dms`
- Integration test: mock ward_room with unread DMs
- Run proactive cycle
- Verify ward_room_router.route_event was called with correct data

## Constraints

- **Do not modify WardRoomRouter.route_event()** — reuse the existing path unchanged
- **Do not modify the Ward Room DB schema** — use existing tables and columns
- **Limit unread DM checks to 2-3 per cycle** — avoid flooding the agent with a backlog of 20 unread DMs at once
- **Deduplication is required** — without it, every proactive cycle will re-notify the same unread DMs until the agent responds
- **Log at `info` level** when unread DMs are found, `warning` on errors (per BF-078 engineering guidance)
- **Use `spec=` on all mock objects** in tests (per BF-079 guidance)

## Acceptance Criteria

- [ ] `ward_room.get_unread_dms(agent_id)` returns correct unread threads
- [ ] Proactive cycle checks for unread DMs and routes notifications
- [ ] Deduplication prevents repeated notifications for the same DM
- [ ] All 6 tests pass
- [ ] Existing test suite passes with 0 regressions
- [ ] No new `MagicMock()` without `spec=`
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Run tests with
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```
