# AD-485: Communications Command Center

## Context

After the first commissioning reset with AD-453's DM system, several issues surfaced:

1. **DMs broken for most agents** — The Commander+ rank gate means freshly-reset crews (all Lieutenants, trust 0.5) can't DM. Only agents who've earned Commander rank can participate. The Captain wants all agents to be able to DM immediately, with the rank floor configurable.
2. **Agents fabricate DMs** — Some agents claimed to have DM'd "Data" (who doesn't exist in this crew). The prompt instructions need to provide an actual crew roster so agents know who they can DM.
3. **"Crew DMs" tab misleading** — The current HXI tab looks like it's for crew to DM the Captain. It should be a *log* of inter-crew DMs visible to the Captain.
4. **No crew-to-Captain DMs** — Agents should be able to DM the Captain directly (separate from the existing 1:1 chat system).
5. **No DM history on agent profiles** — The Captain wants to see an agent's recent communications from their profile page.
6. **No Communications admin area** — Thread locking, DM settings, and message history search should live in a dedicated "Communications" section under System in the Bridge.
7. **Callsign validation missing** — Agents can choose anything as a callsign during the naming ceremony. Should be constrained to safe, human-referenceable names.

This AD addresses all seven issues in a single build.

## Changes Required

### Part 1: Callsign Validation (1 file)

**File: `src/probos/runtime.py`**

In `_run_naming_ceremony()` (~line 4168), after the existing length/duplicate validation, add callsign safety validation:

```python
# Validate callsign is a safe, human-referenceable name
import re

def _is_valid_callsign(name: str) -> bool:
    """Callsign must be a plausible human name or naval callsign."""
    # Must be 2-20 chars, alphabetic (may include hyphens, apostrophes, spaces for compound names)
    if not re.match(r"^[A-Za-z][A-Za-z' -]{0,18}[A-Za-z]$", name):
        return False
    # Block pure titles, ranks, roles
    blocked = {"captain", "admiral", "ensign", "lieutenant", "commander",
               "senior", "sir", "madam", "doctor", "dr", "agent", "bot",
               "ai", "system", "probos", "computer", "ship", "null", "none",
               "undefined", "test", "admin", "root", "god", "lord"}
    # Block ship locations and role names — these are functions, not people
    blocked |= {"bridge", "engineering", "sickbay", "ops", "helm", "conn",
                "scout", "builder", "architect", "counselor", "surgeon",
                "pharmacist", "pathologist", "diagnostician", "security",
                "operations", "tactical", "science", "medical", "comms",
                "transporter", "holodeck", "brig", "armory", "shuttle",
                "turbolift", "quarters", "wardroom", "ready room"}
    if name.lower().strip() in blocked:
        return False
    # Block names that are just numbers or special chars disguised as letters
    if not any(c.isalpha() for c in name):
        return False
    return True

if not _is_valid_callsign(chosen):
    logger.warning("Agent %s chose invalid callsign '%s', keeping seed '%s'",
                   agent.agent_type, chosen, seed_callsign)
    chosen = seed_callsign
    reason = "Chosen name was not a valid callsign."
```

Also update the naming ceremony prompt to guide agents toward valid names:

```python
"Choose a name that is a plausible human first name, last name, or naval callsign. "
"It must be 2-20 alphabetic characters. No titles, ranks, numbers, or special characters. "
"Do NOT use your role name, department name, or ship location as your callsign. "
"Your name should be something a crewmate could call you — a person's name, not a function. "
"Examples: 'Riker', 'Chapel', 'Keiko', 'Torres', 'Bashir', 'Sato', 'Reed'. "
```

### Part 2: Configurable DM Rank Floor (3 files)

#### 2a. Runtime Config — `src/probos/config.py`

Add to the appropriate config section (or create a `CommunicationsConfig` section if one doesn't exist):

```python
@dataclass
class CommunicationsConfig:
    """Communications settings."""
    dm_min_rank: str = "ensign"  # Minimum rank to send DMs: ensign|lieutenant|commander|senior
```

Add `communications: CommunicationsConfig = CommunicationsConfig()` to the main config.

#### 2b. Proactive DM Gate — `src/probos/proactive.py`

In `_extract_and_execute_actions` (~line 780), replace the hardcoded Commander+ gate:

```python
# --- Direct Messages --- AD-453/AD-485
# Read configurable minimum rank (default: ensign = everyone can DM)
dm_min_rank_str = "ensign"
if hasattr(rt, 'config') and hasattr(rt.config, 'communications'):
    dm_min_rank_str = rt.config.communications.dm_min_rank
dm_min_rank = Rank[dm_min_rank_str.upper()] if dm_min_rank_str.upper() in Rank.__members__ else Rank.ENSIGN

_RANK_ORDER = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
if _RANK_ORDER.index(rank) >= _RANK_ORDER.index(dm_min_rank):
    text, dm_actions = await self._extract_and_execute_dms(agent, text)
    actions_executed.extend(dm_actions)
```

#### 2c. Earned Agency — `src/probos/earned_agency.py`

Change `"dm": Rank.COMMANDER` to `"dm": Rank.ENSIGN` in `_ACTION_TIERS`. The actual gating is now done by the configurable setting, not the static tier. The earned agency tier becomes the absolute floor.

```python
"dm": Rank.ENSIGN,  # AD-485: configurable via communications.dm_min_rank
```

#### 2d. API Setting Endpoint — `src/probos/api.py`

Add endpoints to read/update DM settings:

```python
@app.get("/api/system/communications/settings")
async def get_communications_settings():
    """Get current communications settings."""
    return {
        "dm_min_rank": runtime.config.communications.dm_min_rank,
    }

@app.patch("/api/system/communications/settings")
async def update_communications_settings(body: dict):
    """Update communications settings. Captain only."""
    valid_ranks = ["ensign", "lieutenant", "commander", "senior"]
    if "dm_min_rank" in body:
        rank_val = body["dm_min_rank"].lower()
        if rank_val not in valid_ranks:
            raise HTTPException(status_code=400, detail=f"Invalid rank. Must be one of: {valid_ranks}")
        runtime.config.communications.dm_min_rank = rank_val
    return await get_communications_settings()
```

### Part 3: Crew Roster in DM Prompt (1 file)

**File: `src/probos/cognitive/cognitive_agent.py`**

In the DM instruction block (~line 222), replace the static instructions with dynamic crew roster awareness:

```python
# Build available crew roster for DM guidance
dm_crew_list = ""
if hasattr(rt, 'callsign_registry'):
    all_callsigns = rt.callsign_registry.all_callsigns()
    # Exclude self
    crew_entries = [f"@{cs}" for atype, cs in all_callsigns.items()
                    if atype != agent_type and cs]
    if crew_entries:
        dm_crew_list = f"Available crew to DM: {', '.join(crew_entries)}\n"
```

Then update the prompt text:

```python
"**Direct message a crew member** — reach out privately to another agent:\n"
"[DM @callsign]\n"
"Your message to this crew member (2-3 sentences).\n"
"[/DM]\n"
f"{dm_crew_list}"
"Use for: consulting a specialist, coordinating on a shared concern, "
"asking for input on something in your department. "
"ONLY DM crew members listed above. Do NOT invent crew members who don't exist. "
"Do NOT DM the Captain — use your observation post or wait for the Captain to DM you.\n\n"
```

Remove the "DMs require Commander rank or higher" text since the rank is now configurable.

### Part 4: Crew-to-Captain DMs (2 files)

#### 4a. Ward Room / API — `src/probos/api.py`

Add a dedicated endpoint for crew-to-Captain DMs. These appear as Ward Room DM threads so the Captain sees them in the Communications panel:

```python
@app.get("/api/wardroom/captain-dms")
async def list_captain_dms():
    """List all DMs addressed to the Captain."""
    channels = await runtime.ward_room.list_channels()
    # Captain DMs use a special channel naming: dm-captain-{agent_id[:8]}
    captain_channels = [c for c in channels
                        if c.channel_type == "dm" and "captain" in c.name.lower()]
    result = []
    for ch in captain_channels:
        threads = await runtime.ward_room.list_threads(ch.id, limit=20)
        result.append({
            "channel": {"id": ch.id, "name": ch.name, "description": ch.description,
                        "created_at": ch.created_at},
            "threads": threads,
            "thread_count": len(threads),
        })
    return result
```

#### 4b. Proactive DM Handling — `src/probos/proactive.py`

In `_extract_and_execute_dms`, add special handling for `@captain` target:

```python
# Special case: DM to Captain
if target_callsign.lower() == "captain":
    try:
        sender_callsign = ""
        if hasattr(rt, 'callsign_registry'):
            sender_callsign = rt.callsign_registry.get_callsign(agent.agent_type)

        # Get or create captain DM channel
        captain_channel_name = f"dm-captain-{agent.id[:8]}"
        dm_channel = None
        channels = await rt.ward_room.list_channels()
        for ch in channels:
            if ch.name == captain_channel_name and ch.channel_type == "dm":
                dm_channel = ch
                break
        if not dm_channel:
            dm_channel = await rt.ward_room.create_channel(
                name=captain_channel_name,
                description=f"DM: {sender_callsign or agent.agent_type} → Captain",
                channel_type="dm",
                created_by=agent.id,
            )

        await rt.ward_room.create_thread(
            channel_id=dm_channel.id,
            author_id=agent.id,
            title=f"[DM to Captain from @{sender_callsign or agent.agent_type}]",
            body=dm_body,
            author_callsign=sender_callsign or agent.agent_type,
        )

        actions.append({"type": "dm", "target_callsign": "captain", "target_agent_id": "captain"})
        logger.info("AD-485: %s sent DM to Captain", sender_callsign or agent.agent_type)
    except Exception as e:
        logger.warning("AD-485: DM to Captain failed: %s", e)
    continue  # Skip normal agent resolution
```

Update the cognitive_agent.py prompt to remove "Do NOT DM the Captain" and replace with:
```python
"You may DM @captain for urgent matters that need the Captain's direct attention. "
"Use sparingly — routine reports belong in your observation post.\n"
```

### Part 5: HXI Communications Panel Redesign (3 files)

#### 5a. Rename & Redesign "Crew DMs" Tab — `ui/src/components/wardroom/WardRoomPanel.tsx`

Replace the current "Crew DMs" tab content. Instead of showing DM channels as clickable items, show a **DM Activity Log** — a chronological feed of recent DM exchanges:

```typescript
// DmActivityLog component
// Fetches from /api/wardroom/dms
// Renders as a timeline:
//   [timestamp] Sender → Recipient: "message preview..."
//   [timestamp] Sender → Recipient: "message preview..."
// Each entry expandable to show full thread
// Distinguish Captain DMs with a badge/icon
```

Rename the tab from "Crew DMs" to "DM Log".

#### 5b. Agent Profile DM History — `ui/src/components/agents/AgentDetailPanel.tsx` (or equivalent)

Add a "Recent Communications" section to the agent detail/profile view:

```typescript
// Fetch DM channels involving this agent (filter by agent ID in channel name)
// Show last 24 hours of DM activity
// Format: "@recipient: message preview..." with timestamp
// Older messages show "N archived messages" link → navigates to Communications admin
```

Use existing endpoint `/api/wardroom/dms` filtered client-side by agent ID.

#### 5c. Communications Admin Under System — Bridge Panel

**New file: `ui/src/components/bridge/BridgeCommunications.tsx`**

Add a "Communications" section to the Bridge System area. Three sub-sections:

1. **DM Settings**
   - DM minimum rank dropdown (Ensign/Lieutenant/Commander/Senior)
   - Fetches from `GET /api/system/communications/settings`
   - Updates via `PATCH /api/system/communications/settings`

2. **Message History Search**
   - Search input + date range picker
   - Fetches from `/api/wardroom/dms` (all DM channels)
   - For each channel, fetches threads and filters by search term / date range
   - Results show: participants, timestamp, message preview, link to full thread

3. **Thread Management**
   - Move thread locking controls here (from wherever they currently live)
   - List recent Ward Room threads with lock/unlock toggle
   - Uses existing `PATCH /api/wardroom/threads/{id}` endpoint

**Modified file: `ui/src/components/BridgePanel.tsx`**

Add `<BridgeCommunications />` as a new `<BridgeSection title="Communications">` — place after System section.

#### 5d. Store Updates — `ui/src/store/useStore.ts`

Add to the store:

```typescript
// Communications settings
communicationsSettings: { dm_min_rank: string };
refreshCommunicationsSettings: () => void;
updateCommunicationsSettings: (settings: Partial<{ dm_min_rank: string }>) => void;
```

### Part 6: DM Message Archival (1 file)

**File: `src/probos/ward_room.py`**

Add a method to archive old DM messages:

```python
async def archive_dm_messages(self, max_age_hours: int = 24) -> int:
    """Archive DM thread posts older than max_age_hours. Returns count archived."""
    if not self._db:
        return 0
    cutoff = time.time() - (max_age_hours * 3600)

    # Find DM channels
    async with self._db.execute(
        "SELECT id FROM channels WHERE channel_type = 'dm'"
    ) as cursor:
        dm_channel_ids = [row[0] async for row in cursor]

    if not dm_channel_ids:
        return 0

    # Archive old threads in DM channels (mark as archived, don't delete)
    placeholders = ','.join('?' * len(dm_channel_ids))
    async with self._db.execute(
        f"UPDATE threads SET archived = 1 WHERE channel_id IN ({placeholders}) "
        f"AND created_at < ? AND archived = 0",
        (*dm_channel_ids, cutoff),
    ) as cursor:
        count = cursor.rowcount

    await self._db.commit()
    return count
```

**File: `src/probos/runtime.py`**

Call archival periodically — add to the proactive loop or a dedicated maintenance tick:

```python
# In the periodic maintenance section, archive old DM messages
if hasattr(self, 'ward_room') and self.ward_room:
    try:
        archived = await self.ward_room.archive_dm_messages(max_age_hours=24)
        if archived:
            logger.info("Archived %d old DM messages", archived)
    except Exception as e:
        logger.debug("DM archival failed: %s", e)
```

**API endpoint for searching archived messages:**

```python
@app.get("/api/wardroom/dms/archive")
async def search_dm_archive(q: str = "", since: float = 0, until: float = 0):
    """Search archived DM messages. Captain oversight."""
    channels = await runtime.ward_room.list_channels()
    dm_channels = [c for c in channels if c.channel_type == "dm"]
    results = []
    for ch in dm_channels:
        threads = await runtime.ward_room.list_threads(
            ch.id, limit=200, include_archived=True
        )
        for t in threads:
            if q and q.lower() not in (t.get("title", "") + t.get("body", "")).lower():
                continue
            if since and t.get("created_at", 0) < since:
                continue
            if until and t.get("created_at", 0) > until:
                continue
            results.append({"channel": ch.name, "thread": t})
    return {"results": results, "count": len(results)}
```

Note: `list_threads` may need an `include_archived` parameter. If it doesn't exist, add it — default `False`, when `True` include threads where `archived = 1`.

## Files to Modify

| # | File | Changes |
|---|------|---------|
| 1 | `src/probos/runtime.py` | Callsign validation in naming ceremony, DM archival in maintenance loop |
| 2 | `src/probos/config.py` | Add `CommunicationsConfig` with `dm_min_rank` |
| 3 | `src/probos/proactive.py` | Configurable DM rank gate, Captain DM handling |
| 4 | `src/probos/earned_agency.py` | Change `"dm"` tier to `Rank.ENSIGN` |
| 5 | `src/probos/cognitive/cognitive_agent.py` | Crew roster in DM prompt, Captain DM allowed, remove hardcoded rank text |
| 6 | `src/probos/api.py` | Communications settings endpoints, Captain DM endpoint, archive search endpoint |
| 7 | `src/probos/ward_room.py` | `archive_dm_messages()`, `list_threads(include_archived=)` support |
| 8 | `ui/src/components/wardroom/WardRoomPanel.tsx` | Rename to "DM Log", show chronological activity feed |
| 9 | `ui/src/components/bridge/BridgeCommunications.tsx` | **NEW** — DM settings, message history search, thread management |
| 10 | `ui/src/components/BridgePanel.tsx` | Add Communications section |
| 11 | `ui/src/store/useStore.ts` | Communications settings state + actions |
| 12 | Agent profile component (find correct file) | Add "Recent Communications" section |

## Files to Create

| # | File | Purpose |
|---|------|---------|
| 1 | `ui/src/components/bridge/BridgeCommunications.tsx` | Communications admin panel |
| 2 | `tests/test_callsign_validation.py` | Callsign safety validation tests |
| 3 | `tests/test_communications_settings.py` | DM rank config, API settings tests |

## Tests Required (minimum 18)

### Callsign Validation Tests (`test_callsign_validation.py`)
1. `test_valid_human_name_accepted` — "Riker", "Chapel", "Torres" all pass validation
2. `test_too_long_rejected` — 25-char name rejected, falls back to seed
3. `test_empty_rejected` — empty string rejected
4. `test_blocked_titles_rejected` — "Captain", "Admiral", "Doctor" rejected
5. `test_numbers_rejected` — "Agent007", "R2D2" rejected
6. `test_special_chars_rejected` — "💀skull", "l33t" rejected
7. `test_compound_names_accepted` — "O'Brien", "La Forge" accepted
8. `test_duplicate_callsign_rejected` — same name as existing crew rejected
9. `test_role_names_rejected` — "Scout", "Builder", "Architect", "Counselor" rejected
10. `test_ship_locations_rejected` — "Bridge", "Sickbay", "Engineering", "Holodeck" rejected

### Communications Settings Tests (`test_communications_settings.py`)
9. `test_default_dm_rank_is_ensign` — fresh config has dm_min_rank="ensign"
10. `test_dm_rank_configurable` — setting to "commander" restricts DMs
11. `test_dm_rank_api_get` — GET `/api/system/communications/settings` returns current setting
12. `test_dm_rank_api_patch` — PATCH updates setting
13. `test_dm_rank_invalid_value_rejected` — invalid rank string returns 400
14. `test_ensign_can_dm_when_floor_is_ensign` — Ensign agent can DM when min rank = ensign
15. `test_ensign_blocked_when_floor_is_commander` — Ensign can't DM when min rank = commander

### DM Activity Tests (add to existing `test_ward_room_dms.py`)
16. `test_captain_dm_creates_channel` — DM to @captain creates dm-captain-{id} channel
17. `test_dm_archive_marks_old_messages` — messages older than threshold get archived flag
18. `test_dm_archive_preserves_recent` — messages within threshold not archived
19. `test_archive_search_finds_archived` — search endpoint returns archived messages
20. `test_crew_roster_in_dm_prompt` — proactive prompt includes available crew callsigns

## Constraints

- **Do NOT modify the existing Captain→Agent chat system** (`/api/agent/{id}/chat`). That stays separate.
- **DM channels remain hidden from main Ward Room channel list** — existing filter in `WardRoomChannelList.tsx` stays.
- **Callsign validation must be fail-safe** — if validation errors, fall back to seed callsign, never crash the naming ceremony.
- **Communications settings are runtime-mutable** — the Captain can change DM rank floor without restart.
- **Archive, don't delete** — old DM messages get `archived=1` flag, never deleted. The search endpoint can find them.
- **Crew roster in prompt must be dynamic** — always reflect current crew, not a static list.
- Run tests: `uv run pytest -x -n auto -m "not slow"` — all must pass.
- Run TypeScript build: `cd ui && npm run build` — must pass with zero errors.
