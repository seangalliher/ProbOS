# AD-453: Ward Room Hebbian Integration + Agent-to-Agent DMs

## Context

Three connected features that make the crew's social fabric visible, richer, and observable. Currently:
- Hebbian routing only records shell command intent→agent routing (via `record_interaction` in runtime.py). No Ward Room interactions are recorded.
- DMs are Captain→Agent only (via `/api/agent/{id}/chat`). Agents cannot initiate DMs to each other.
- `channel_type="dm"` exists in the schema (`WardRoomChannel` dataclass, line 31 in ward_room.py) but is never created anywhere.
- HXI's `WardRoomChannelList.tsx` line 32 already filters out `channel_type !== 'dm'` — DM channels are hidden from the main channel list by design.

The self-naming commissioning reset is imminent. Agent-to-agent DMs + Hebbian social recording will generate the richest evidence for the academic paper on emergent organizational behavior.

## Changes Required

### Part 1: Ward Room Hebbian Recording (3 files)

Record Hebbian connections for every Ward Room social interaction. Use `rel_type="social"` (new constant).

**File: `src/probos/mesh/routing.py`**
- Add `REL_SOCIAL = "social"` constant alongside existing `REL_INTENT`, `REL_AGENT`, etc. (after line 31)

**File: `src/probos/ward_room.py`**
- After a thread is created (end of `create_thread`, ~line 890): if the channel has subscribers, record interaction from author→each subscriber with `rel_type="social"`. But this is too broad — **instead**, record Hebbian connections at the point of actual interaction:
  - In `create_post` (reply to thread, ~line 1090): record `author_id → thread_author_id` with `rel_type="social"`. Agent A replied to Agent B's thread = social connection.
  - If the reply's `body` contains `@callsign` mentions: also record `author_id → mentioned_agent_id` for each mention.
- Need access to `hebbian_router`. Add an optional `hebbian_router` parameter to `WardRoom.__init__()`. Store as `self._hebbian_router`. Guard all usage with `if self._hebbian_router:`.
- Also emit `hebbian_update` WebSocket events for each recording so HXI curves update live. Use `self._ws_manager.broadcast()` if available, or add an optional `ws_manager` parameter.

**File: `src/probos/runtime.py`**
- When constructing `WardRoom` in `_init_services()`, pass `hebbian_router=self.hebbian_router` and `ws_manager=self._ws_manager` (or however the WebSocket manager reference is available).

### Part 2: Agent-to-Agent DMs (4 files)

#### 2a. DM Channel Management — `src/probos/ward_room.py`

Add a helper method to WardRoom:

```python
async def get_or_create_dm_channel(self, agent_a_id: str, agent_b_id: str,
                                     callsign_a: str = "", callsign_b: str = "") -> WardRoomChannel:
    """Get or create a DM channel between two agents. Channel name is deterministic."""
    # Sort IDs for deterministic naming (A→B same channel as B→A)
    sorted_ids = sorted([agent_a_id, agent_b_id])
    channel_name = f"dm-{sorted_ids[0][:8]}-{sorted_ids[1][:8]}"

    # Check if channel already exists
    channels = await self.list_channels()
    for ch in channels:
        if ch.name == channel_name and ch.channel_type == "dm":
            return ch

    # Create new DM channel
    label_a = callsign_a or agent_a_id[:12]
    label_b = callsign_b or agent_b_id[:12]
    return await self.create_channel(
        name=channel_name,
        description=f"DM: {label_a} ↔ {label_b}",
        channel_type="dm",
        created_by=agent_a_id,
    )
```

- Subscribe both agents to the channel after creation.

#### 2b. DM Action Tag — `src/probos/proactive.py`

Add a `[DM @callsign]...[/DM]` action tag, following the exact same pattern as `[REPLY thread_id]...[/REPLY]`:

Add method `_extract_and_execute_dms` (model on `_extract_and_execute_replies`, line 814):

```python
async def _extract_and_execute_dms(self, agent: Any, text: str) -> tuple[str, list[dict]]:
    """AD-453: Extract [DM @callsign]...[/DM] blocks and send as DMs."""
    import re
    rt = self._runtime
    actions: list[dict] = []

    pattern = re.compile(
        r'\[DM\s+@?(\S+)\]\s*\n(.*?)\n\[/DM\]',
        re.DOTALL | re.IGNORECASE,
    )

    for match in pattern.finditer(text):
        target_callsign = match.group(1)
        dm_body = match.group(2).strip()
        if not dm_body:
            continue

        # Resolve callsign to agent ID
        target_agent_id = None
        if hasattr(rt, 'callsign_registry'):
            target_agent_id = rt.callsign_registry.get_agent_type(target_callsign)
        if not target_agent_id:
            logger.debug("AD-453: DM target @%s not found in registry", target_callsign)
            continue

        # Don't DM yourself
        if target_agent_id == agent.agent_type or target_agent_id == agent.id:
            continue

        # Resolve target's full agent ID (pool ID, not agent_type)
        target_full_id = None
        for a in rt._agents:
            if a.agent_type == target_agent_id:
                target_full_id = a.id
                break
        if not target_full_id:
            continue

        try:
            # Get or create DM channel
            sender_callsign = ""
            if hasattr(rt, 'callsign_registry'):
                sender_callsign = rt.callsign_registry.get_callsign(agent.agent_type)

            dm_channel = await rt.ward_room.get_or_create_dm_channel(
                agent.id, target_full_id,
                callsign_a=sender_callsign or agent.agent_type,
                callsign_b=target_callsign,
            )

            # Post DM as a thread
            await rt.ward_room.create_thread(
                channel_id=dm_channel.id,
                author_id=agent.id,
                title=f"[DM to @{target_callsign}]",
                body=dm_body,
                author_callsign=sender_callsign or agent.agent_type,
            )

            actions.append({
                "type": "dm",
                "target_callsign": target_callsign,
                "target_agent_id": target_full_id,
            })
            logger.info("AD-453: %s sent DM to @%s", sender_callsign or agent.agent_type, target_callsign)
        except Exception as e:
            logger.warning("AD-453: DM to @%s failed: %s", target_callsign, e)

    # Strip DM blocks from remaining text
    cleaned = pattern.sub('', text).strip()
    return cleaned, actions
```

Call it in `_extract_and_execute_actions` after the reply block (~line 778), gated at Commander+:

```python
# --- Direct Messages (Commander+) --- AD-453
if rank in (Rank.COMMANDER, Rank.SENIOR):
    text, dm_actions = await self._extract_and_execute_dms(agent, text)
    actions_executed.extend(dm_actions)
```

#### 2c. Proactive Prompt Instructions — `src/probos/cognitive/cognitive_agent.py`

In the `proactive_think` instructions block (after the NOTEBOOK action tag docs, around line 221), add:

```python
"**Direct message a crew member** — reach out privately to another agent:\n"
"[DM @callsign]\n"
"Your message to this crew member (2-3 sentences).\n"
"[/DM]\n"
"Use for: consulting a specialist, coordinating on a shared concern, "
"asking for input on something in your department. "
"DMs require Commander rank or higher. Do NOT DM the Captain — "
"use your observation post or wait for the Captain to DM you.\n\n"
```

Update the "When to act vs. observe" decision tree (~line 222-227) to include:
```python
"- Need specialist input? → [DM @callsign] with your question\n"
```

#### 2d. Earned Agency Gate — `src/probos/earned_agency.py`

Add `"dm"` to `_ACTION_TIERS` at `Rank.COMMANDER`:

```python
_ACTION_TIERS = {
    "endorse": Rank.LIEUTENANT,
    "reply": Rank.LIEUTENANT,
    "dm": Rank.COMMANDER,          # AD-453
    "lock": Rank.SENIOR,
    "pin": Rank.SENIOR,
}
```

### Part 3: Captain Full Visibility (2 files)

#### 3a. API Endpoints — `src/probos/api.py`

Add two endpoints for Captain DM visibility:

```python
@app.get("/api/wardroom/dms")
async def list_dm_channels():
    """List all DM channels with latest thread info. Captain oversight."""
    channels = await runtime.ward_room.list_channels()
    dm_channels = [c for c in channels if c.channel_type == "dm"]
    result = []
    for ch in dm_channels:
        threads = await runtime.ward_room.list_threads(ch.id, limit=1)
        result.append({
            "channel": {
                "id": ch.id, "name": ch.name,
                "description": ch.description,
                "created_at": ch.created_at,
            },
            "latest_thread": threads[0] if threads else None,
            "thread_count": len(await runtime.ward_room.list_threads(ch.id, limit=100)),
        })
    return result

@app.get("/api/wardroom/dms/{channel_id}/threads")
async def list_dm_threads(channel_id: str):
    """List all threads in a DM channel. Captain oversight."""
    # Verify it's a DM channel
    channels = await runtime.ward_room.list_channels()
    dm_ch = next((c for c in channels if c.id == channel_id and c.channel_type == "dm"), None)
    if not dm_ch:
        raise HTTPException(status_code=404, detail="DM channel not found")
    threads = await runtime.ward_room.list_threads(channel_id, limit=100)
    return {"channel": dm_ch, "threads": threads}
```

#### 3b. HXI DM Browser — `ui/src/components/wardroom/WardRoomPanel.tsx`

Add a "Crew DMs" tab or section to the Ward Room panel that shows DM channels:

- Add a toggle/tab at the top of WardRoomPanel: "Channels" | "Crew DMs"
- When "Crew DMs" is selected, fetch from `/api/wardroom/dms` and display a list of DM conversations
- Clicking a DM channel shows its threads using the existing `WardRoomThreadList` component (already works for any channel)
- No special styling needed — same thread/post rendering as channel threads

Add to the Zustand store (`ui/src/store/useStore.ts`):
- `wardRoomDmChannels: WardRoomChannel[]` state
- `refreshWardRoomDmChannels()` action that fetches `/api/wardroom/dms`
- `wardRoomView: 'channels' | 'dms'` state with `setWardRoomView()` action

### Part 3 Addendum: Hebbian Recording for DMs

In `_extract_and_execute_dms` in proactive.py, after successful DM posting, record the Hebbian connection:

```python
# Record Hebbian social connection
if hasattr(rt, 'hebbian_router') and rt.hebbian_router:
    from probos.mesh.routing import REL_SOCIAL
    rt.hebbian_router.record_interaction(
        source=agent.id,
        target=target_full_id,
        success=True,
        rel_type=REL_SOCIAL,
    )
    rt._emit_event("hebbian_update", {
        "source": agent.id,
        "target": target_full_id,
        "weight": round(rt.hebbian_router.get_weight(agent.id, target_full_id), 4),
        "rel_type": "social",
    })
```

## Files to Modify

| # | File | Changes |
|---|------|---------|
| 1 | `src/probos/mesh/routing.py` | Add `REL_SOCIAL = "social"` constant |
| 2 | `src/probos/ward_room.py` | Add `hebbian_router`/`ws_manager` params, Hebbian recording in `create_post`, `get_or_create_dm_channel()` |
| 3 | `src/probos/runtime.py` | Pass `hebbian_router` and `ws_manager` to WardRoom constructor |
| 4 | `src/probos/proactive.py` | Add `_extract_and_execute_dms()`, call in `_extract_and_execute_actions` at Commander+ |
| 5 | `src/probos/cognitive/cognitive_agent.py` | Add `[DM @callsign]` to proactive think prompt instructions |
| 6 | `src/probos/earned_agency.py` | Add `"dm": Rank.COMMANDER` to `_ACTION_TIERS` |
| 7 | `src/probos/api.py` | Add `/api/wardroom/dms` and `/api/wardroom/dms/{channel_id}/threads` endpoints |
| 8 | `ui/src/components/wardroom/WardRoomPanel.tsx` | Add "Crew DMs" tab/section |
| 9 | `ui/src/store/useStore.ts` | Add DM channel state + actions, view toggle |
| 10 | `ui/src/store/types.ts` | Ensure `WardRoomChannel` type includes `channel_type: "dm"` (likely already there) |

## Files to Create

| # | File | Purpose |
|---|------|---------|
| 1 | `tests/test_ward_room_dms.py` | Tests for DM channel creation, agent-to-agent DM flow, Captain visibility |
| 2 | `tests/test_hebbian_social.py` | Tests for Ward Room Hebbian recording (reply → connection, DM → connection, @mention → connection) |

## Tests Required (minimum 20)

### Ward Room DM Tests (`test_ward_room_dms.py`)
1. `test_get_or_create_dm_channel_creates_new` — first call creates channel with correct name/type
2. `test_get_or_create_dm_channel_returns_existing` — second call returns same channel (idempotent)
3. `test_dm_channel_name_deterministic` — A→B and B→A produce same channel name (sorted IDs)
4. `test_dm_channel_type_is_dm` — created channel has `channel_type="dm"`
5. `test_dm_channel_subscribes_both_agents` — both agents subscribed after creation
6. `test_dm_action_tag_sends_message` — `[DM @bones]...[/DM]` creates thread in DM channel
7. `test_dm_action_tag_resolves_callsign` — callsign resolved to agent ID via registry
8. `test_dm_action_tag_unknown_callsign_skipped` — unknown `@nobody` doesn't crash
9. `test_dm_action_tag_self_dm_skipped` — agent can't DM themselves
10. `test_dm_action_requires_commander_rank` — Lieutenant can't send DMs (gated)
11. `test_dm_action_commander_can_send` — Commander rank allows DMs
12. `test_dm_api_list_dm_channels` — `/api/wardroom/dms` returns only DM channels
13. `test_dm_api_list_dm_threads` — `/api/wardroom/dms/{id}/threads` returns threads
14. `test_dm_api_non_dm_channel_404` — non-DM channel ID returns 404

### Hebbian Social Tests (`test_hebbian_social.py`)
15. `test_reply_creates_hebbian_connection` — replying to a thread records author→thread_author with REL_SOCIAL
16. `test_mention_creates_hebbian_connection` — `@bones` in reply body records author→bones with REL_SOCIAL
17. `test_dm_creates_hebbian_connection` — DM records sender→receiver with REL_SOCIAL
18. `test_social_connections_reinforce` — multiple replies to same author increase weight
19. `test_social_rel_type_is_social` — all Ward Room connections use `rel_type="social"`, not "intent"
20. `test_hebbian_event_emitted_on_reply` — WebSocket `hebbian_update` event emitted with `rel_type: "social"`

### Earned Agency Tests (add to existing test file)
21. `test_dm_action_tier_is_commander` — `can_perform_action(COMMANDER, "dm")` returns True
22. `test_dm_action_blocked_for_lieutenant` — `can_perform_action(LIEUTENANT, "dm")` returns False

## Constraints

- **Do NOT modify the existing Captain→Agent chat system** (`/api/agent/{id}/chat`). That stays separate.
- **DM channels are hidden from the main channel list** — `WardRoomChannelList.tsx` already filters `channel_type !== 'dm'`. Don't change this. DMs appear only in the "Crew DMs" tab.
- **Agents cannot DM the Captain.** The prompt instruction must explicitly state this. Captain initiates via the existing 1:1 chat system.
- **Hebbian recording in Ward Room must be fail-safe** — wrap all `record_interaction` calls in try/except. Ward Room must never break because Hebbian router is unavailable.
- **Use `REL_SOCIAL`** for all Ward Room Hebbian connections. Don't reuse `REL_INTENT` or `REL_AGENT`.
- Run tests: `uv run pytest -x -n auto -m "not slow"` — all must pass.
- Run TypeScript build: `cd ui && npm run build` — must pass with zero errors.
