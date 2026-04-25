# BF-200: Thread Cap Awareness & DM Cap Raise

**Priority:** High (user-visible, affects conversation quality)  
**Related:** BF-016b (per-agent reply cap), AD-614 (DM exchange limit), AD-629 (unified reply cap), AD-625 (comm proficiency gate modulation), AD-623 (DM convergence gate), BF-156 (DM depth bypass), BF-157 (@mention cap bypass)

## Problem

When a thread response cap is reached, the agent is silently suppressed — the message is never dispatched to them. The agent has no idea the Captain (or another agent) continued speaking. From the agent's perspective, the conversation simply stopped. There is no notification, no episodic memory entry, no awareness.

Additionally, DM exchange limits are too low for substantive conversations. The `dm_exchange_limit` config is 5, and the `max_agent_responses_per_thread` default is 3 (proficiency-modulated 1–5). Captain-to-crew 1:1 conversations hit the ceiling before meaningful dialogue develops.

## Cap Inventory (Current State)

All caps that can silence an agent, with current behavior:

| # | Cap | Location | Default | DM? | Silent? |
|---|-----|----------|---------|-----|---------|
| 1 | Thread depth (agent-only rounds) | ward_room_router.py:332-339 | 3 rounds | Bypassed | Yes |
| 2 | DM convergence gate | ward_room_router.py:366-388 | semantic sim | DM only | Emits event, no post |
| 3 | DM exchange limit | ward_room_router.py:492-508 | 5 per agent | DM only | Yes |
| 4 | Per-agent cooldown | ward_room_router.py:510-514 | 30s/tier | Bypassed | Yes |
| 5 | Per-round dedup | ward_room_router.py:517-518 | 1 per round | Bypassed | Yes |
| 6 | Per-thread reply cap | ward_room_router.py:523-530 | 3 (tier: 1-5) | **Hits** | Yes |

**Wesley's case:** Ward Room DM thread → cap #6 hit after 3 replies (NOVICE tier in fresh instance).

## Fix

Two changes:

### Change 1: Raise DM exchange limit to 40

In `src/probos/config.py`, change `dm_exchange_limit` from 5 to 40.

```python
dm_exchange_limit: int = 40          # BF-200: raised from 5 — DMs need room for substantive conversation
```

This is the AD-614 per-agent post count limit for DM channels specifically (ward_room_router.py:493-508). The per-thread reply cap (#6 above) still applies but is lower — for DMs we should also bypass the per-thread reply cap when `is_direct_target` is True (DMs already set this). Add a DM guard before `check_and_increment_reply_cap`:

```python
# BF-200: DM channels use dm_exchange_limit, not the per-thread reply cap
if channel and channel.channel_type == "dm":
    pass  # Already guarded by AD-614 dm_exchange_limit above
elif not self.check_and_increment_reply_cap(
    thread_id, agent_id,
    is_department_channel=(
        channel is not None
        and getattr(channel, 'channel_type', '') == "department"
    ),
):
    continue
```

This means DMs are governed by `dm_exchange_limit=40` only, not double-capped by both AD-614 and BF-016b.

### Change 2: Post a system notification when a cap is hit

When any cap silences an agent on a thread, post a visible system message to the thread so agents (and the Captain) can see the cap was reached.

#### 2a. Add `_post_cap_notification()` method to `WardRoomRouter`

```python
async def _post_cap_notification(
    self, thread_id: str, agent_id: str, cap_name: str,
) -> None:
    """BF-200: Post a system notice when a response cap silences an agent."""
    if not self._ward_room:
        return
    # Deduplicate: only post once per (thread, cap_name)
    cap_key = (thread_id, cap_name)
    if cap_key in self._cap_notices_posted:
        return
    self._cap_notices_posted.add(cap_key)

    callsign = ""
    if hasattr(self, '_proactive_loop') and self._proactive_loop:
        _rt = getattr(self._proactive_loop, '_runtime', None)
        if _rt and hasattr(_rt, 'callsign_registry'):
            callsign = _rt.callsign_registry.get_callsign_by_id(agent_id) or agent_id[:8]
    if not callsign:
        callsign = agent_id[:8]

    body = (
        f"[System] Thread response limit reached for {callsign}. "
        "To continue this discussion, start a new thread or DM."
    )
    try:
        await self._ward_room.create_post(
            thread_id=thread_id,
            author_id="system",
            body=body,
            author_callsign="System",
        )
    except Exception:
        logger.debug("BF-200: Failed to post cap notification", exc_info=True)
```

#### 2b. Add `_cap_notices_posted: set[tuple[str, str]]` to `__init__`

```python
self._cap_notices_posted: set[tuple[str, str]] = set()
```

Add cleanup in the existing periodic cleanup method (same pattern as `_responded_threads` cleanup) — clear entries older than 1 hour or on a size threshold.

#### 2c. Apply at cap #1 — thread depth (line 334-339)

Replace the silent return:

```python
if current_round >= max_rounds:
    logger.debug(
        "Ward Room: thread %s hit agent round limit (%d), silencing",
        thread_id[:8], max_rounds,
    )
    # BF-200: Notify thread that cap was hit
    await self._post_cap_notification(thread_id, "", "agent_round_limit")
    return
```

#### 2d. Apply at cap #3 — DM exchange limit (line 501-506)

Replace the silent continue:

```python
if agent_post_count >= dm_limit:
    logger.debug(
        "AD-614: %s hit DM exchange limit (%d/%d) in thread %s",
        agent_id[:12], agent_post_count, dm_limit, thread_id[:8],
    )
    # BF-200: Notify thread that cap was hit
    await self._post_cap_notification(thread_id, agent_id, "dm_exchange_limit")
    continue
```

#### 2e. Apply at cap #6 — per-thread reply cap (line 523-530)

This only fires for non-DM channels after Change 1. Replace the silent continue:

```python
elif not self.check_and_increment_reply_cap(
    thread_id, agent_id,
    is_department_channel=(
        channel is not None
        and getattr(channel, 'channel_type', '') == "department"
    ),
):
    # BF-200: Notify thread that cap was hit
    await self._post_cap_notification(thread_id, agent_id, "reply_cap")
    continue
```

#### 2f. Apply at DM convergence gate (line 370-386)

This one already emits an event. Add a post too:

```python
if convergence and convergence.get("converged"):
    logger.info(...)
    self._event_emitter(...)
    # BF-200: Notify DM thread that convergence ended it
    await self._post_cap_notification(thread_id, "", "dm_convergence")
    return
```

## Files Changed

| File | Change |
|------|--------|
| `src/probos/config.py` | `dm_exchange_limit` 5 → 40 |
| `src/probos/ward_room_router.py` | Add `_post_cap_notification()`, `_cap_notices_posted` set, DM bypass of reply cap, cap notifications at 4 cap sites |
| `tests/test_bf200_thread_cap_awareness.py` | **NEW** — tests |

## Tests (`tests/test_bf200_thread_cap_awareness.py`)

### Config
1. **test_dm_exchange_limit_default_40** — `WardRoomConfig().dm_exchange_limit == 40`

### DM reply cap bypass
2. **test_dm_bypasses_reply_cap** — DM channel agent not blocked by `check_and_increment_reply_cap`
3. **test_non_dm_still_uses_reply_cap** — Department/ship channel still subject to reply cap

### Cap notification posting
4. **test_cap_notification_posted_on_reply_cap** — When reply cap hit, system post created in thread
5. **test_cap_notification_posted_on_dm_exchange_limit** — Same for DM exchange limit
6. **test_cap_notification_posted_on_thread_depth** — Same for agent round limit
7. **test_cap_notification_posted_on_dm_convergence** — Same for DM convergence gate
8. **test_cap_notification_deduplicated** — Second cap hit on same thread+cap_name → no duplicate post
9. **test_cap_notification_contains_callsign** — Notification body includes agent callsign, not raw ID
10. **test_cap_notification_suggests_new_thread** — Body contains "start a new thread"

### Integration
11. **test_dm_conversation_allows_40_exchanges** — Agent can reply up to 40 times in DM thread
12. **test_ward_room_thread_cap_then_notification** — Full flow: 3 replies → cap → system post visible

## Engineering Principles

- **SRP:** `_post_cap_notification()` — cap notification is a single responsibility, not duplicated at each site
- **DRY:** Shared method used at all 4 cap enforcement points
- **Defense in Depth:** DMs still have a cap (40), not unlimited. Convergence gate provides semantic-level protection.
- **Fail Fast:** Notification post failure is logged, never propagates — cap enforcement continues regardless
- **Westworld Principle:** Agents should know their constraints. A silent cap violates authentic AI identity — the agent should know the system limited it, not experience an inexplicable silence.
- **OCP:** `_cap_notices_posted` dedup set extensible for future cap types

## Deferred

- Agent-side awareness (episodic memory entry recording "I was capped") — could complement the thread notification but adds complexity. The posted system message achieves awareness for all thread participants.
- Comm proficiency tier adjustment for DMs — currently DMs bypass the reply cap entirely. Could add DM-specific tier scaling later.
- `_cap_notices_posted` cleanup could be integrated into the existing `_cleanup_stale_data()` method if one exists, or a simple size-based eviction.

## Builder Instructions

```
Read and execute the build prompt in d:\ProbOS\prompts\bf-200-thread-cap-awareness.md
```

Run targeted tests after:
```
python -m pytest tests/test_bf200_thread_cap_awareness.py -v
```
