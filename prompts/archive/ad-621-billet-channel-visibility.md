# AD-621: Billet-Driven Channel Visibility — Subscription-Based Routing

## Context

AD-620 (complete) established the clearance model: billet clearance on `Post`, `effective_recall_tier()`, and FULL+ clearance agents auto-subscribed to all department channels at startup. The Counselor, First Officer, and department chiefs are now correctly subscribed.

**The problem:** Subscription alone doesn't grant visibility. The WardRoomRouter's `find_targets()` routes department channel events by checking `get_department(agent.agent_type) == channel.department` — it only notifies agents whose **home department** matches the channel. A Bridge officer subscribed to the Engineering channel via AD-620 **never receives notifications** from that channel because her home department is Bridge, not Engineering.

This means AD-620's cross-department subscriptions are write-only — agents can browse threads (the read path uses memberships), but they don't get real-time notifications.

**Design reference:** `docs/research/clearance-system-design.md` (AD-621 section, lines 217-234)

## Scope

AD-621 makes the WardRoomRouter honor memberships for notification routing, so cross-department subscribers actually receive department channel events.

**In scope:**
1. WardRoomRouter `find_targets()` — check memberships instead of (or in addition to) home department
2. WardRoomRouter `find_targets_for_agent()` — same fix for agent-authored posts
3. Refine `startup/communication.py` subscription logic — switch from clearance-based (`FULL+`) to ontology-driven (`reports_to: captain`) per design doc
4. `list_channels(agent_id)` — actually filter by membership when agent_id is provided

**Out of scope:**
- Message-level classification (e.g., CLASSIFIED threads within a channel)
- DM clearance gating (who can DM whom)
- AD-622: Dynamic ClearanceGrant model

## Engineering Principles Compliance

- **SOLID/S**: WardRoomRouter's concern is routing, not clearance resolution. It checks memberships (its own domain), not billet clearance.
- **SOLID/O**: Extending `find_targets()` logic without changing its signature or callers.
- **DRY**: Both `find_targets()` and `find_targets_for_agent()` share the same department routing pattern. Factor the membership check once if practical.
- **Law of Demeter**: Router queries the Ward Room's own memberships table — doesn't reach into ontology for clearance.
- **Defense in Depth**: Subscription is the gate. If an agent is subscribed to a channel, they belong there. If not, they don't see it. The subscription logic (startup/communication.py) is where clearance/ontology policy is enforced.

## Changes

### 1. `src/probos/ward_room_router.py` — `find_targets()` (lines 554-573)

**Current department channel routing (lines 555-573):**
```python
        elif channel.channel_type == "department" and channel.department:
            # Department channel: notify agents in that department
            from probos.cognitive.standing_orders import get_department
            for agent in self._registry.all():
                if (agent.is_alive
                        and agent.id != author_id
                        and agent.id not in target_ids
                        and hasattr(agent, 'handle_intent')
                        and is_crew_agent(agent, self._ontology)
                        and ((self._ontology.get_agent_department(agent.agent_type) if self._ontology else None) or get_department(agent.agent_type)) == channel.department):
                    # AD-357: Earned Agency trust-tier gating
                    if self._config.earned_agency.enabled:
                        from probos.earned_agency import can_respond_ambient
                        from probos.crew_profile import Rank
                        _agent_rank = Rank.from_trust(self._trust_network.get_score(agent.id))
                        if not can_respond_ambient(_agent_rank, is_captain_post=True,
                                                   same_department=True):
                            continue
                    target_ids.append(agent.id)
```

**Replace with membership-based routing:**
```python
        elif channel.channel_type == "department" and channel.department:
            # AD-621: Department channel — notify all subscribed agents
            # Subscription is the gate (set at startup by communication.py).
            # Home-department agents AND cross-department subscribers both receive.
            from probos.cognitive.standing_orders import get_department
            _subscribed_ids = self._get_channel_subscribers(channel.id)
            for agent in self._registry.all():
                if (agent.is_alive
                        and agent.id != author_id
                        and agent.id not in target_ids
                        and hasattr(agent, 'handle_intent')
                        and is_crew_agent(agent, self._ontology)
                        and agent.id in _subscribed_ids):
                    # AD-357: Earned Agency trust-tier gating
                    # Cross-department subscribers (via billet): same_department=True
                    # because they have explicit channel access.
                    _home_dept = ((self._ontology.get_agent_department(agent.agent_type) if self._ontology else None)
                                  or get_department(agent.agent_type))
                    _same_dept = (_home_dept == channel.department)
                    if self._config.earned_agency.enabled:
                        from probos.earned_agency import can_respond_ambient
                        from probos.crew_profile import Rank
                        _agent_rank = Rank.from_trust(self._trust_network.get_score(agent.id))
                        if not can_respond_ambient(_agent_rank, is_captain_post=True,
                                                   same_department=_same_dept):
                            continue
                    target_ids.append(agent.id)
```

**Key design decisions:**
- **Subscription is the gate, not department membership.** This is the clean separation: `communication.py` decides WHO gets subscribed (policy), the router decides WHO gets notified (membership lookup).
- **Earned Agency `same_department` flag** is set correctly: home-department agents get `same_department=True` (lower response threshold), cross-department subscribers get `same_department=False` (higher threshold — they observe more, respond only when their expertise applies). This prevents Bridge officers from responding to every Engineering post.
- **Fallback if memberships unavailable**: If `_get_channel_subscribers()` returns empty (DB issue), fall back to the old department-matching logic to avoid silent notification failure.

### 2. `src/probos/ward_room_router.py` — `_get_channel_subscribers()` (NEW method)

Add a helper method to the WardRoomRouter class that reads the memberships table:

```python
    def _get_channel_subscribers(self, channel_id: str) -> set[str]:
        """AD-621: Get agent IDs subscribed to a channel.

        Returns a set for O(1) lookup in find_targets(). Reads from the
        Ward Room's memberships table via the service facade.
        """
        try:
            ward_room = getattr(self, '_ward_room', None)
            if not ward_room:
                return set()
            # Ward Room service exposes get_channel_members or similar
            members = ward_room.get_channel_members_sync(channel_id)
            return {m.agent_id for m in members}
        except Exception:
            return set()
```

**IMPORTANT:** The WardRoomRouter currently has no reference to the WardRoomService. Check how the router accesses the Ward Room:
- The router is wired in `startup/finalize.py` — look at what references it receives at construction or post-init.
- If the router doesn't have a WardRoomService reference, pass it during wiring. Alternative: query the memberships DB directly (the WardRoomService and router share the same SQLite DB path via config).

**Approach options (choose the cleanest):**

**(A) Async membership query via WardRoomService:**
The router's `find_targets()` is synchronous. If the Ward Room exposes only async methods, this won't work directly. Check whether `find_targets()` can be made async or if a sync cache is needed.

**(B) Membership cache (preferred):**
Build a `_channel_members: dict[str, set[str]]` cache at startup (after subscriptions are set). Refresh on `subscribe()`/`unsubscribe()` calls. This avoids async-in-sync issues and gives O(1) lookup.

The cache should be populated once after `communication.py` finishes the subscription loop. The WardRoomRouter already has a `setup()` or post-init phase in `startup/finalize.py` — add cache population there.

Cache invalidation: `subscribe()` and `unsubscribe()` in `ward_room/messages.py` should emit an event or call a callback to update the cache. Or, simpler: rebuild the cache once at startup and accept that runtime subscription changes (rare) aren't reflected until restart. Document this as acceptable for AD-621 scope.

**(C) Direct SQL query (simplest, synchronous):**
If the router has access to the DB path, open a sync connection and query directly:
```python
import sqlite3
def _get_channel_subscribers(self, channel_id: str) -> set[str]:
    try:
        conn = sqlite3.connect(self._db_path)
        cursor = conn.execute(
            "SELECT agent_id FROM memberships WHERE channel_id = ?",
            (channel_id,),
        )
        result = {row[0] for row in cursor}
        conn.close()
        return result
    except Exception:
        return set()
```
Check if the router has access to the DB path. The WardRoomService stores its DB at `{data_dir}/ward_room.db`. The router receives `config` — check if `data_dir` is accessible.

**Builder: evaluate approaches A/B/C and implement whichever is cleanest given the router's existing architecture. If `find_targets()` callers are all async, prefer making it async (Approach A). If callers are sync, use B or C. Document the choice.**

### 3. `src/probos/ward_room_router.py` — `find_targets_for_agent()` (lines 626-644)

Apply the same membership-based routing fix to the agent-authored post path:

**Current code (lines 627-644):**
```python
        if channel.channel_type == "department" and channel.department:
            from probos.cognitive.standing_orders import get_department
            for agent in self._registry.all():
                if (agent.is_alive
                        and agent.id != author_id
                        and agent.id not in target_ids
                        and hasattr(agent, 'handle_intent')
                        and is_crew_agent(agent, self._ontology)
                        and ((self._ontology.get_agent_department(agent.agent_type) if self._ontology else None) or get_department(agent.agent_type)) == channel.department):
                    # AD-357: Earned Agency trust-tier gating
                    ...
                    target_ids.append(agent.id)
```

**Replace with membership-based routing (same pattern as `find_targets()` above).**

For agent-authored posts, cross-department subscribers SHOULD be notified (they subscribed for a reason), but Earned Agency gating should use `same_department=False` for cross-department subscribers — they observe but only respond when their role applies. This naturally throttles cross-talk.

### 4. `src/probos/startup/communication.py` — Refine subscription logic (lines 164-173)

**Current AD-620 code (clearance-based):**
```python
            # AD-620: Agents with FULL+ billet clearance get all department channels
            _billet_cl = resolve_billet_clearance(agent.agent_type, getattr(runtime, 'ontology', None))
            if _billet_cl:
                try:
                    _cl_tier = RecallTier(_billet_cl.lower())
                    if _TIER_ORDER.get(_cl_tier, 0) >= _TIER_ORDER.get(RecallTier.FULL, 0):
                        for dept_ch_id in dept_channel_map.values():
                            await ward_room.subscribe(agent.id, dept_ch_id)
                except ValueError:
                    pass  # Invalid clearance string — skip
```

**Replace with ontology-driven subscription:**
```python
            # AD-621: Ontology-driven channel visibility
            # Bridge officers (reports_to: captain) get all department channels.
            # Channel visibility is about observation (being in the room),
            # not capability access — separate concern from clearance.
            _ontology = getattr(runtime, 'ontology', None)
            if _ontology:
                _post = _ontology.get_post_for_agent(agent.agent_type)
                if _post and _post.reports_to == "captain":
                    for dept_ch_id in dept_channel_map.values():
                        await ward_room.subscribe(agent.id, dept_ch_id)
```

**Rationale for the switch:**
- Design doc: "Channel visibility is ontology-driven, not clearance-driven."
- `reports_to: captain` (First Officer, Counselor) captures exactly the agents with ship-wide observation needs.
- Department chiefs (`reports_to: first_officer`) do NOT get all-department channels — they see their own department + ship-wide channels. This is correct: the Chief Engineer doesn't need to observe Medical discussions. If a chief needs cross-department visibility for a specific case, that's AD-622 (ClearanceGrant).
- This is a **scope reduction** from AD-620's `FULL+` approach. Previously all 8 chiefs + Bridge got all channels. Now only the 2 Bridge officers (First Officer, Counselor) do. Captain is `tier: external` and not in the agent registry, so the captain check is effectively First Officer + Counselor.
- **IMPORTANT:** Verify this is the intended behavior. The user may want chiefs to retain all-department visibility. If so, use `_post.reports_to in ("captain", "first_officer")` instead.

**Also remove the now-unused imports from line 138:**
```python
# Before:
from probos.earned_agency import resolve_billet_clearance, RecallTier, _TIER_ORDER
# After: (remove this line entirely — no longer needed in this file)
```

### 5. `src/probos/ward_room/channels.py` — `list_channels(agent_id)` (lines 100-115)

The method accepts `agent_id` but ignores it — returns all channels. Fix to filter by membership when `agent_id` is provided:

**Current code:**
```python
    async def list_channels(self, agent_id: str | None = None) -> list[WardRoomChannel]:
        """All channels."""
        if not self._db:
            return []
        channels: list[WardRoomChannel] = []
        async with self._db.execute(
            "SELECT id, name, channel_type, department, created_by, created_at, archived, description "
            "FROM channels ORDER BY created_at"
        ) as cursor:
            ...
```

**Replace with membership-aware query:**
```python
    async def list_channels(self, agent_id: str | None = None) -> list[WardRoomChannel]:
        """List channels, optionally filtered by agent membership.

        AD-621: When agent_id is provided, return only channels the agent
        is subscribed to. When None, return all channels (admin view).
        """
        if not self._db:
            return []
        channels: list[WardRoomChannel] = []

        if agent_id:
            sql = (
                "SELECT c.id, c.name, c.channel_type, c.department, c.created_by, "
                "c.created_at, c.archived, c.description "
                "FROM channels c "
                "INNER JOIN memberships m ON m.channel_id = c.id "
                "WHERE m.agent_id = ? "
                "ORDER BY c.created_at"
            )
            params: tuple = (agent_id,)
        else:
            sql = (
                "SELECT id, name, channel_type, department, created_by, created_at, "
                "archived, description FROM channels ORDER BY created_at"
            )
            params = ()

        async with self._db.execute(sql, params) as cursor:
            async for row in cursor:
                channels.append(WardRoomChannel(
                    id=row[0], name=row[1], channel_type=row[2],
                    department=row[3], created_by=row[4], created_at=row[5],
                    archived=bool(row[6]), description=row[7],
                ))
        return channels
```

**Check all callers of `list_channels()`** to verify they pass `agent_id=None` when they need the full list (e.g., `communication.py` subscription loop at line 139 needs all channels to build `dept_channel_map`).

## Tests

### File: `tests/test_ad621_channel_visibility.py` (NEW)

1. **Router: home-department agent notified** — Agent in Engineering subscribed to Engineering channel → receives Engineering channel events.
2. **Router: cross-department subscriber notified** — First Officer (Bridge) subscribed to Engineering channel → receives Engineering channel events.
3. **Router: non-subscriber NOT notified** — Scout (Science) NOT subscribed to Engineering → does NOT receive Engineering events.
4. **Router: @mention overrides subscription** — Agent NOT subscribed to channel but @mentioned → receives event.
5. **Router: agent-authored cross-dept notification** — LaForge posts in Engineering → First Officer (subscribed) receives notification.
6. **Router: Earned Agency same_department flag** — Cross-department subscriber gets `same_department=False` for EA gating; home-department agent gets `same_department=True`.
7. **Subscription: reports_to captain gets all channels** — First Officer and Counselor subscribed to all department channels at startup.
8. **Subscription: department chiefs get own channel only** — Chief Engineer subscribed to Engineering only, NOT Medical or Science.
9. **Subscription: regular officers get own channel only** — Scout subscribed to Science only.
10. **list_channels(agent_id) filtering** — Agent subscribed to 3 channels → `list_channels(agent_id)` returns exactly 3.
11. **list_channels(None) returns all** — No agent_id → returns all channels.
12. **Router fallback: empty memberships** — If `_get_channel_subscribers()` returns empty set, verify graceful degradation (no crash, agents simply not notified).
13. **Ship channel routing unchanged** — Ship-wide channel events still route to all crew (no change from current behavior).
14. **DM routing unchanged** — DM events still route to the other participant (no change).

## Verification

```bash
# AD-621 tests
uv run python -m pytest tests/test_ad621_channel_visibility.py -v

# Verify no remaining department-matching routing in router
# (should be replaced by membership checks)
grep -n "get_department.*== channel.department" src/probos/ward_room_router.py

# Verify startup subscriptions work
uv run python -m pytest tests/ -k "communication" -v

# Full test suite
uv run python -m pytest tests/ -x -q
```

## Tracking Updates

- PROGRESS.md: AD-621 → IN PROGRESS
- DECISIONS.md: Add AD-621 entry after build
- roadmap.md: Update status
- GitHub Project: Issue #207 → In Progress
