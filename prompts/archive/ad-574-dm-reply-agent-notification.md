# AD-574: DM Reply Agent Notification

**Type:** Bug fix / UX improvement
**Priority:** High
**Prerequisites:** AD-572 (DM game context), AD-573 (unified working memory)

## Problem

When the Captain replies to an agent's DM through the Ward Room DM Log or Thread Detail panels, the agent **never responds**. The Captain's message is stored in the Ward Room database but the agent is never notified.

Two independent gaps combine to create this:

### Gap 1: WardRoomRouter.find_targets() ignores DM channels

`find_targets()` (`ward_room_router.py` line 295) handles `channel_type == "ship"` and `channel_type == "department"` but has **no case for `channel_type == "dm"`**. When the Captain posts in a DM channel, target resolution returns an empty list — nobody is notified.

The `find_targets_for_agent()` method (line 358) DOES handle DM channels (line 390: `if agent.id[:8] in channel.name`), but this is only used for agent-authored posts, not Captain posts.

### Gap 2: Proactive unread DM polling doesn't catch replies

`_check_unread_dms()` in `proactive.py` (line 350) polls for unread DMs, but `get_unread_dms()` in `messages.py` (line 577) only returns threads where the agent has **zero posts** (`p.id IS NULL`). If the agent already posted in the thread (i.e., the agent initiated the DM conversation), their reply won't appear as "unread" — the agent already has posts in that thread.

This means: the Captain replies to an agent-initiated DM → the WardRoomRouter doesn't notify because `find_targets` has no DM case → the proactive unread poll doesn't catch it because the agent already posted in the thread → the message is silently lost.

## Solution

Fix Gap 1 in `WardRoomRouter.find_targets()` by adding a `"dm"` channel type case. This is the correct architectural fix — the event-driven notification path is how all Ward Room messages reach agents.

Gap 2 (proactive unread polling) is a safety net, not the primary path. Once `find_targets()` routes DM posts correctly, the proactive poll becomes redundant for this case. However, we should also fix the unread query to handle Captain replies in threads where the agent already posted, as a defense-in-depth measure.

## What This AD Delivers

1. Captain posts in DM channels notify the target agent via WardRoomRouter
2. Proactive unread DM polling catches Captain replies even in agent-initiated threads
3. Zero new files, zero new dependencies

## Files Modified

| File | Change |
|------|--------|
| `src/probos/ward_room_router.py` | Add `"dm"` case to `find_targets()` |
| `src/probos/ward_room/messages.py` | Fix `get_unread_dms()` query to catch Captain replies in agent-initiated threads |
| `tests/test_ward_room_router.py` | Add tests for DM channel routing |
| `tests/test_ward_room_messages.py` | Add test for unread DMs with Captain replies |

## Files NOT Modified / Created

No new files. No HXI changes. No config changes.

## Design Details

### 1. Add DM case to `find_targets()` — `ward_room_router.py`

**After the `elif channel.channel_type == "department"` block (line 336-354), before `return target_ids` (line 356), add:**

```python
elif channel.channel_type == "dm":
    # DM channel: notify the other participant
    # Channel name format: "dm-captain-{agent_id[:8]}" or "dm-{id_a[:8]}-{id_b[:8]}"
    for agent in self._registry.all():
        if (agent.is_alive
                and agent.id != author_id
                and agent.id not in target_ids
                and hasattr(agent, 'handle_intent')
                and is_crew_agent(agent, self._ontology)
                and agent.id[:8] in channel.name):
            target_ids.append(agent.id)
```

This mirrors the existing pattern in `find_targets_for_agent()` (line 390) — matching `agent.id[:8]` against the channel name. It handles both naming conventions:
- `dm-captain-{agent_id[:8]}` — Captain-initiated DMs
- `dm-{id_a[:8]}-{id_b[:8]}` — Agent-initiated DMs to Captain (where `captain` appears as `author_id`, not in the channel name)

**Important:** Do NOT add Earned Agency gating for DM channels. The Captain is directly addressing a specific agent — this is not an ambient channel where trust-tier filtering applies. DMs are always 1:1 targeted communication.

### 2. Fix `get_unread_dms()` query — `ward_room/messages.py`

The current query at line 577 finds DM threads where the agent has zero posts (`LEFT JOIN ... WHERE p.id IS NULL`). This means agent-initiated threads (where the agent posted first) are excluded, even if the Captain subsequently replied.

**Replace the query to detect threads with new activity after the agent's last post:**

Find the current `get_unread_dms()` method. The fix changes the "unread" definition from "threads where agent has zero posts" to "threads where the most recent post is NOT by the agent" (i.e., someone else posted after the agent's last activity).

**Before:** Threads with zero agent posts.

**After:** Threads where the latest post/thread body is from someone other than the agent, AND the agent hasn't responded to that latest activity yet. Specifically:

```sql
SELECT t.id, t.channel_id, t.title, t.body, t.created_at, t.author_id,
       t.author_callsign, c.name as channel_name, c.description
FROM threads t
JOIN channels c ON t.channel_id = c.id
WHERE c.channel_type = 'dm'
  AND c.name LIKE ?          -- agent is a participant (id prefix in channel name)
  AND c.archived = 0
  AND t.author_id != ?        -- thread not authored by this agent
  AND NOT EXISTS (
      SELECT 1 FROM posts p2
      WHERE p2.thread_id = t.id
        AND p2.author_id = ?   -- agent already replied to this thread
        AND p2.created_at > (
            SELECT COALESCE(MAX(p3.created_at), t.created_at)
            FROM posts p3
            WHERE p3.thread_id = t.id
              AND p3.author_id != ?  -- latest non-agent post
        )
  )
ORDER BY t.created_at DESC
LIMIT ?
```

Wait — this is getting complex. Simpler approach that preserves the original intent:

**Change the LEFT JOIN condition** to check if the agent has posted **after the most recent non-agent post**. But this adds query complexity.

**Simplest correct fix:** Change the condition from "agent has zero posts" to "the most recent post in the thread is NOT by this agent":

```sql
-- Find DM threads where the agent hasn't responded to the latest activity
SELECT t.id, t.channel_id, t.title, t.body, t.created_at, t.author_id,
       t.author_callsign, c.name as channel_name, c.description
FROM threads t
JOIN channels c ON t.channel_id = c.id
WHERE c.channel_type = 'dm'
  AND c.name LIKE ?
  AND c.archived = 0
  AND t.author_id != ?
ORDER BY t.created_at DESC
LIMIT ?
```

Then filter in Python: for each thread, check if the most recent post (or the thread body if no posts) was authored by someone other than the agent. This avoids complex SQL and keeps the query maintainable.

**Recommended implementation:**

```python
async def get_unread_dms(self, agent_id: str, limit: int = 5) -> list[dict]:
    """Get DM threads with unread activity for an agent.

    A thread is 'unread' if the most recent activity (thread creation or
    latest post) is from someone other than this agent.
    """
    prefix = agent_id[:8]
    async with self._lock:
        conn = await self._get_connection()
        rows = await conn.execute_fetchall(
            """
            SELECT t.id, t.channel_id, t.title, t.body, t.created_at,
                   t.author_id, t.author_callsign,
                   c.name as channel_name, c.description
            FROM threads t
            JOIN channels c ON t.channel_id = c.id
            LEFT JOIN (
                SELECT thread_id, author_id as last_author,
                       MAX(created_at) as last_post_time
                FROM posts
                WHERE deleted = 0
                GROUP BY thread_id
            ) lp ON lp.thread_id = t.id
            WHERE c.channel_type = 'dm'
              AND c.name LIKE ?
              AND c.archived = 0
              AND COALESCE(lp.last_author, t.author_id) != ?
            ORDER BY COALESCE(lp.last_post_time, t.created_at) DESC
            LIMIT ?
            """,
            (f"%{prefix}%", agent_id, limit),
        )
        return [dict(r) for r in rows]
```

This uses a LEFT JOIN subquery to find the last post author for each thread. If no posts exist, it falls back to the thread author. If the last author is the agent itself, the thread is not "unread." This correctly handles:
- Agent initiates DM → Captain replies → thread is unread (last author = captain)
- Captain initiates DM → Agent replies → thread is NOT unread (last author = agent)
- Agent initiates DM → no reply yet → thread is NOT unread (author = agent)

**Note:** The current `get_unread_dms()` uses `self._lock` and `self._get_connection()` — follow the same pattern. Check the exact method signature and connection pattern before implementing.

### 3. Ward Room Router DM test — `tests/test_ward_room_router.py`

Add tests to the existing test file:

```python
class TestDmChannelRouting:
    """AD-574: Captain posts in DM channels notify the target agent."""

    def test_captain_post_in_dm_notifies_agent(self):
        """find_targets returns the agent when Captain posts in their DM channel."""
        # Create a DM channel with agent ID prefix in name
        channel = MagicMock()
        channel.channel_type = "dm"
        channel.name = "dm-captain-abc12345"

        # Agent whose ID starts with abc12345
        agent = MagicMock()
        agent.id = "abc12345-full-uuid"
        agent.is_alive = True
        agent.agent_type = "test_agent"
        # ... register agent, call find_targets with author_id="captain"
        # Assert agent.id in targets

    def test_captain_post_in_dm_does_not_notify_self(self):
        """Captain's own ID is never in the target list."""

    def test_captain_post_in_dm_no_earned_agency_gating(self):
        """DM routing bypasses Earned Agency trust-tier check."""

    def test_agent_not_in_channel_not_notified(self):
        """Agents whose ID prefix doesn't match the DM channel name are excluded."""
```

### 4. Unread DMs query test — `tests/test_ward_room_messages.py`

Add to existing test file (or create if not exists):

```python
class TestUnreadDmsQuery:
    """AD-574: Unread DM detection handles Captain replies in agent-initiated threads."""

    async def test_captain_reply_in_agent_thread_is_unread(self):
        """Agent initiates DM, Captain replies → thread appears as unread for agent."""

    async def test_agent_reply_clears_unread(self):
        """Agent replies to Captain's post → thread is no longer unread."""

    async def test_agent_initiated_no_reply_not_unread(self):
        """Agent initiates DM with no replies → NOT unread (agent authored last)."""

    async def test_multiple_exchanges_last_author_wins(self):
        """Multiple back-and-forth → unread status based on who posted last."""
```

## Engineering Principles Compliance

- **DRY:** `find_targets()` DM case mirrors `find_targets_for_agent()` DM logic (line 390). Consider extracting a shared `_resolve_dm_participant()` helper if the pattern appears a third time. For now, two instances is acceptable — not worth an abstraction yet.
- **SOLID (O — Open/Closed):** Adding a new `elif` branch to `find_targets()` extends existing behavior without modifying existing channel type handling.
- **Law of Demeter:** No reaching through private attrs. `channel.name` and `agent.id` are public. `channel.channel_type` is public.
- **Fail Fast:** If the DM channel name doesn't contain any registered agent's ID prefix, `target_ids` stays empty and no notification fires — correct fail-safe behavior.
- **Defense in Depth:** Two independent paths to notification: (1) event-driven via WardRoomRouter, (2) polling via proactive `_check_unread_dms()`. Fixing both ensures robustness.
- **Cloud-Ready Storage:** No new storage. Query change uses existing SQLite connection pattern.

## Verification

1. Run Ward Room router tests: `pytest tests/test_ward_room_router.py -v`
2. Run Ward Room message tests: `pytest tests/test_ward_room_messages.py -v` (or relevant test file)
3. Run full test suite: `pytest --tb=short`
4. **Manual test:** Start ProbOS, wait for an agent to DM the Captain, reply via the DM Log panel, verify the agent responds.
5. Verify no regressions in Ward Room routing: existing ship/department channel tests still pass.

## Deferred

- **AD-574b: Synchronous DM response in HXI** — Currently, the Captain's DM reply goes through the Ward Room (async, agent responds on proactive cycle). A future enhancement could make DM panel replies behave like ProfileChatTab — synchronous request-response with "agent is thinking..." indicator. This requires HXI changes (calling `/api/agent/{id}/chat` from the DM panel AND posting to Ward Room for record-keeping).
- **AD-574c: DM conversation convergence** — ProfileChatTab and Ward Room DM are two separate conversation stores. Messages in one don't appear in the other. Unifying them so the Captain sees a single conversation history regardless of which UI they used is a larger architectural change.
