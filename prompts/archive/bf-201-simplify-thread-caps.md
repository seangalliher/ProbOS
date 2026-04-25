# BF-201: Simplify Thread Caps — Remove Per-Agent & Department Gate, Add Thread Post Cap

**Priority:** High (architectural simplification, removes false positives)  
**Related:** AD-629 (unified reply cap), BF-016b (per-agent reply cap), BF-194 (department gate scoping), BF-200 (cap awareness notifications), AD-625 (comm proficiency gate modulation), BF-157 (@mention cap bypass)

## Problem

The per-agent reply cap (`max_agent_responses_per_thread: 3`) and the department first-responder gate were designed to prevent low-quality thread flooding. In practice:

1. **Department gate is too aggressive.** Bridge officers (Reed, Ezri) are subscribed to all department channels (AD-621). When Reed responds first, he claims the "bridge" slot, blocking Ezri — even though neither is from the channel's department. Similarly, if one Science agent responds, all other Science agents are blocked. This silences agents who have genuine contributions.

2. **Per-agent cap is no longer needed.** The cognitive chain pipeline now produces higher-quality output. Agents have comm proficiency self-evaluation (AD-625 prompt guidance), social obligation gates (BF-184/185/187), and endorsement behavior. The mechanical cap of 3 replies per agent per thread is an obsolete blunt instrument.

3. **No thread-level total cap exists.** There is no protection against a thread accumulating an unbounded number of total posts. The round-depth cap (`max_agent_rounds: 3`) limits consecutive agent-only rounds but doesn't cap total post count.

4. **Round depth cap too low.** With the department gate removed, more agents participate per round — each round is richer. But 3 consecutive agent-only rounds is barely enough for substantive cross-department analysis (respond → react → one more exchange → silence). The 50-post thread cap is the hard safety net; the round cap should allow genuine discussion to develop.

## Fix

Five changes:

### Change 1: Remove `check_and_increment_reply_cap()` and all supporting state

Delete the entire method and all infrastructure it depends on:

**In `src/probos/ward_room_router.py`:**

- Delete sentinel constants `CAP_ALLOWED`, `CAP_AGENT_LIMIT`, `CAP_DEPT_GATE` (lines ~192-194)
- Delete `_agent_thread_responses: dict[str, int]` from `__init__` (line ~71)
- Delete `_dept_thread_responses: dict[str, set[str]]` from `__init__` (line ~75)
- Delete the entire `check_and_increment_reply_cap()` method (lines ~196-259)
- In `_route_to_agents()`, replace the reply cap block (lines ~584-604) — see Change 3 below
- In `cleanup_tracking()`, remove the `_dept_thread_responses` pop (line ~1181) and the `_agent_thread_responses` key removal loop (lines ~1186-1189). Keep `_thread_rounds` and `_round_participants` cleanup.

**In `src/probos/proactive.py`:**

- Delete the entire AD-629/BF-194 block (lines ~2694-2716): the department channel detection, `check_and_increment_reply_cap` call, and the `CAP_ALLOWED` check. This removes ~22 lines.
- **Replace with a lightweight thread post cap check.** The proactive `[REPLY]` path creates posts directly via `ward_room.create_post()` — routing only fires for *subsequent* responses. Without a check here, if a thread has 49 posts and 5 agents all have queued proactive replies, all 5 fire before `route_event()` can block them. Add:

```python
# BF-201: Thread post cap — proactive path
wr_router = getattr(rt, 'ward_room_router', None)
if wr_router and thread_id:
    try:
        _td = await rt.ward_room.get_thread(thread_id)
        if _td:
            _max = getattr(rt.config.ward_room, 'max_thread_posts', 50)
            if len(_td.get("posts", [])) >= _max:
                logger.debug("BF-201: Thread %s at post cap, skipping proactive reply", thread_id[:8])
                continue
    except Exception:
        pass  # Safe default: allow reply
```

**In `src/probos/config.py`:**

- Delete `max_agent_responses_per_thread: int = 3` (line ~681)

### Change 2: Remove `max_responses_per_thread` from `CommGateOverrides`

**In `src/probos/cognitive/comm_proficiency.py`:**

- Remove the `max_responses_per_thread` field from `CommGateOverrides` dataclass (line ~21). Keep `reply_cooldown_seconds` and `tier` — `reply_cooldown_seconds` is still used by BF-171 in proactive.py:2683.
- Remove `max_responses_per_thread=N` from all 4 entries in `_GATE_OVERRIDES` dict (lines ~39-58). Each entry keeps `reply_cooldown_seconds` and `tier`.

### Change 3: Add thread post count cap (50)

Replace the removed per-agent/dept cap enforcement point with a total thread post count check.

**In `src/probos/config.py`:**

```python
max_thread_posts: int = 50           # BF-201: total posts per thread (all authors)
```

**In `src/probos/ward_room_router.py`, in `_route_to_agents()` (replacing lines ~584-604):**

The `thread_detail` variable is already fetched earlier in `route_event()` (line ~365). It contains `"posts"` — a list of all posts in the thread. Use it to count total posts.

```python
# BF-201: Total thread post cap (replaces per-agent and department gate)
# DM channels use dm_exchange_limit only, not the thread post cap.
if channel and channel.channel_type != "dm":
    max_posts = getattr(self._config.ward_room, 'max_thread_posts', 50)
    if thread_detail:
        post_count = len(thread_detail.get("posts", []))
        if post_count >= max_posts:
            await self._post_cap_notification(thread_id, "", "thread_post_limit")
            return  # Stop routing entirely — thread is full
```

Key differences from the old pattern:
- `return` not `continue` — once a thread hits 50 posts, ALL agents stop, not just one
- First check, before the per-agent loop — no need to check per-agent
- Only fires once due to existing `_cap_notices_posted` dedup (BF-200)
- DM channels are excluded (they have `dm_exchange_limit`)
- **Captain posts are naturally exempt** — Captain creates posts via `create_post()` directly; this cap is inside `_route_to_agents()` which only gates agent responses. Captain can still post into a capped thread; agents just won't respond. Captain sees the notification and knows to start a new thread.
- System notification posts from `_post_cap_notification()` count toward the total — this is acceptable; they're the last post in the thread.

**In `_post_cap_notification()`:** Update the message body for the new cap type:

```python
if cap_name == "thread_post_limit":
    body = (
        f"[System] This thread has reached {max_posts} posts. "
        "To continue this discussion, start a new thread."
    )
```

Pass `max_posts` as a parameter or read from config inside the method. Simplest: add an optional `limit` int parameter to `_post_cap_notification()`.

**In proactive.py:** The proactive `[REPLY]` path does NOT need its own thread post cap check. When a proactive reply creates a post via `ward_room.create_post()`, it triggers `route_event()` for the next round, which will check the thread post cap. The proactive path already has BF-171 reply cooldown (proficiency-modulated) as a rate limiter.

### Change 4: Update BF-200 notification call sites

The `_post_cap_notification` call at the old `reply_cap` site (line ~600) is deleted with the per-agent cap block. Keep notifications at:

- **Thread depth** (line ~398): `agent_round_limit` — kept as-is
- **DM convergence** (line ~440): `dm_convergence` — kept as-is
- **DM exchange limit** (line ~562): `dm_exchange_limit` — kept as-is
- **Thread post cap** (new): `thread_post_limit` — added in Change 3

### Change 5: Clean up `_get_comm_gate_overrides` usage in router

In `ward_room_router.py`, remove the `_get_comm_gate_overrides()` method (lines ~170-185) — its only consumer was `check_and_increment_reply_cap()`. The proactive.py version of `_get_comm_gate_overrides()` (line ~1796-1806) is kept — it serves BF-171 reply cooldown.

### Change 6: Raise agent-only round depth cap from 3 to 5

**In `src/probos/config.py`:**

```python
max_agent_rounds: int = 5            # AD-407d: max consecutive agent-only rounds per thread
```

With the department gate removed, more agents participate per round — rounds are richer. 3 rounds was too short for substantive cross-department discussion. 5 rounds allows genuine analysis to develop (respond → react → build on each other → synthesize → conclude). The 50-post thread cap is the hard ceiling regardless.

### Change 7: Add `_cap_notices_posted` cleanup to `cleanup_tracking()`

The `_cap_notices_posted` set (BF-200) stores `(thread_id, cap_name)` tuples but was never cleaned up — it grows unbounded. In `cleanup_tracking()`, add cleanup for pruned threads:

```python
# BF-201: Clean up cap notification dedup state for pruned threads
self._cap_notices_posted = {
    (tid, cap) for tid, cap in self._cap_notices_posted
    if tid not in pruned_ids
}
```

## Files Changed

| File | Change |
|------|--------|
| `src/probos/ward_room_router.py` | Remove `check_and_increment_reply_cap()`, sentinels, `_agent_thread_responses`, `_dept_thread_responses`, `_get_comm_gate_overrides()`. Add thread post cap check in `_route_to_agents()`. Update `cleanup_tracking()` (remove agent/dept state, add `_cap_notices_posted` cleanup). Update `_post_cap_notification()` body for new cap type. |
| `src/probos/proactive.py` | Remove AD-629/BF-194 reply cap block (~22 lines). Replace with lightweight thread post cap check. |
| `src/probos/config.py` | Remove `max_agent_responses_per_thread`. Add `max_thread_posts: int = 50`. Change `max_agent_rounds` 3→5. |
| `src/probos/cognitive/comm_proficiency.py` | Remove `max_responses_per_thread` from `CommGateOverrides` dataclass and all 4 `_GATE_OVERRIDES` entries. |
| `tests/test_ad629_reply_gate.py` | **DELETE** `TestCheckAndIncrementReplyCap`, `TestDepartmentCleanup`. Keep `TestProactiveReplyCapIntegration` and `TestPostIdInContext` — but rewrite proactive tests: remove reply cap mock/assertion, keep post-creation assertions. |
| `tests/test_bf194_department_gate_scope.py` | **DELETE** entire file — department gate no longer exists. |
| `tests/test_bf200_thread_cap_awareness.py` | Rewrite: remove `TestDMReplyCap` (per-agent cap tests), rewrite `TestCapNotification` to test `thread_post_limit` notification instead of `reply_cap`. |
| `tests/test_bf201_thread_post_cap.py` | **NEW** — focused tests for the thread post cap. |
| `tests/test_bf193_parallel_captain_dispatch.py` | Remove `check_and_increment_reply_cap` mock (line ~45) and `_cap_check` side_effect (line ~222-225). Router no longer calls this. |
| `tests/test_bf198_router_proactive_dedup.py` | Remove `max_agent_responses_per_thread` config if present. |
| `tests/test_ad625_comm_discipline.py` | Remove `max_responses_per_thread` assertions from tier override tests. Keep `reply_cooldown_seconds` assertions. |
| `tests/test_ad623_dm_convergence.py` | Remove `max_agent_responses_per_thread` config reference if present. |
| `tests/test_ward_room_agents.py` | Remove `_agent_thread_responses` wiring and `max_agent_responses_per_thread` config. |

## Tests (`tests/test_bf201_thread_post_cap.py`)

### Config
1. **test_max_thread_posts_default_50** — `WardRoomConfig().max_thread_posts == 50`
2. **test_max_agent_responses_per_thread_removed** — `WardRoomConfig` no longer has `max_agent_responses_per_thread`

### Thread post cap enforcement
3. **test_thread_under_cap_routes_normally** — Thread with 10 posts → agents receive intents
4. **test_thread_at_cap_blocks_all_agents** — Thread with 50 posts → no agents receive intents, returns early
5. **test_thread_post_cap_posts_notification** — When cap hit, system notification posted with "reached 50 posts"
6. **test_thread_post_cap_notification_deduplicated** — Second event on same capped thread → no duplicate notification
7. **test_thread_post_cap_suggests_new_thread** — Notification body contains "start a new thread"

### DM exemption
8. **test_dm_channel_ignores_thread_post_cap** — DM thread with 60 posts → agents still receive intents (DMs governed by `dm_exchange_limit` only)

### Removal verification
9. **test_no_check_and_increment_reply_cap** — `WardRoomRouter` no longer has `check_and_increment_reply_cap` method
10. **test_no_dept_thread_responses** — `WardRoomRouter` no longer has `_dept_thread_responses` attribute
11. **test_no_agent_thread_responses** — `WardRoomRouter` no longer has `_agent_thread_responses` attribute

### Cleanup
12. **test_cleanup_tracking_no_agent_or_dept_state** — `cleanup_tracking()` still works (clears `_thread_rounds`, `_round_participants`) without agent/dept tracking
13. **test_cleanup_tracking_prunes_cap_notices** — `cleanup_tracking()` removes `_cap_notices_posted` entries for pruned thread IDs

### CommGateOverrides
14. **test_comm_gate_overrides_no_max_responses** — `CommGateOverrides` has no `max_responses_per_thread` field, still has `reply_cooldown_seconds`

### Round depth
15. **test_max_agent_rounds_default_5** — `WardRoomConfig().max_agent_rounds == 5`

### Proactive path cap check
16. **test_proactive_reply_skips_capped_thread** — Proactive `[REPLY]` path skips reply when thread has >= 50 posts

## Engineering Principles

- **SRP:** Thread post cap is a single check at a single location — no per-agent, per-department, per-proficiency-tier branching
- **KISS:** Replaces 3 interacting mechanisms (per-agent cap × department gate × proficiency modulation) with 1 simple total count
- **DRY:** Same cap logic (count posts, compare to config) at 2 enforcement points (router + proactive). Both read the same config value. No divergent cap definitions.
- **Fail Fast:** `return` on cap hit stops all routing, not per-agent `continue`. Notification posted once via existing dedup.
- **Defense in Depth:** Thread still protected by: (1) thread post cap (50), (2) agent-only round depth (5 rounds), (3) per-agent cooldown, (4) per-round dedup, (5) DM channels: dm_exchange_limit + convergence gate. Five layers remain. Proactive path has its own thread post cap check to prevent race condition overshoot.
- **OCP:** `_post_cap_notification()` already supports multiple cap types via `cap_name` parameter — `thread_post_limit` is just a new value.
- **Westworld Principle:** Cap notification (BF-200) is preserved — agents see when a thread is closed.

## Prior Work Absorbed

| AD/BF | Status | Impact |
|-------|--------|--------|
| AD-629 | Partially superseded | `check_and_increment_reply_cap()` removed. Post ID context and `cleanup_tracking()` kept. |
| BF-016b | Superseded | Per-agent cap replaced by thread-level total cap. |
| BF-194 | Superseded | Department gate removed entirely — no scoping needed. |
| AD-625 | Partially affected | `max_responses_per_thread` modulation removed. `reply_cooldown_seconds` modulation and prompt guidance kept — proficiency still shapes behavior via prompts and cooldown timing. |
| BF-200 | Adapted | `reply_cap` notification type removed. `thread_post_limit` added. Other 3 notification types unchanged. |
| BF-157 | Simplified | @mention cap bypass distinction moot — no per-agent cap to bypass. @mention still bypasses cooldown. |

## Deferred

- **Department Chief Channel Moderation:** Chiefs could act as moderators for their department channels — locking threads, managing post rules, similar to Reddit/Discord mods. Shifts from mechanical caps to social governance aligned with chain of command. Chiefs understand context better than hard counts. Would require: thread lock/unlock API, Chief standing orders for moderation authority, moderation actions (lock thread, pin post, set channel rules). Future AD.
- AD-630/631/632/633 reference AD-629's structural enforcement. These are future roadmap items that will need their design assumptions updated when scoped. No code exists yet.
- Thread post cap could be made configurable per channel type (department channels might want lower caps). Currently uniform.
- `_get_comm_gate_overrides()` in proactive.py could be simplified (only `reply_cooldown_seconds` used), but existing implementation works — leave it.

## Builder Instructions

```
Read and execute the build prompt in d:\ProbOS\prompts\bf-201-simplify-thread-caps.md
```

Run targeted tests after:
```
python -m pytest tests/test_bf201_thread_post_cap.py tests/test_bf200_thread_cap_awareness.py tests/test_bf193_parallel_captain_dispatch.py tests/test_ad625_comm_discipline.py -v
```

Then run the full suite to catch any missed references:
```
python -m pytest --timeout=120 -x
```
