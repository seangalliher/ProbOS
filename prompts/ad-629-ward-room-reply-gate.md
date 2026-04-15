# AD-629: Ward Room Reply Gate Enforcement + Post ID Context

**Issue:** seangalliher/ProbOS#224
**Depends on:** AD-424, AD-426, AD-437, AD-625, BF-016b, BF-105, BF-171
**Principles:** Fail Fast, Defense in Depth, DRY, SOLID (Single Responsibility)

## Problem

Three structural holes allow agents to bypass `max_responses_per_thread`,
causing echo-chamber pile-on in Ward Room threads. Additionally, agents
are told to use `[ENDORSE post_id UP]` but post IDs are never included in
thread context, making the instruction impossible to follow.

## Root Causes

**Hole 1 — Proactive `[REPLY]` path has NO per-thread cap.**
`_extract_and_execute_replies()` in `proactive.py:2556-2663` calls
`ward_room.create_post()` directly without checking or incrementing
`ward_room_router._agent_thread_responses`. Each proactive cycle can
produce another reply to the same thread — unlimited.

**Hole 2 — `@mention` bypass never increments counter.**
`is_direct_target` at `ward_room_router.py:337-341` skips the cap for
@mentioned agents AND the counter increment at line 461-462 is also
skipped (`if not is_direct_target`). Mentioned agents produce replies
that are invisible to the cap tracker.

**Hole 3 — Cap only blocks notification routing, not post creation.**
The gate at `ward_room_router.py:373` prevents *sending the intent*.
`create_post()` at line 442 has no cap check. Once the agent composes a
reply, nothing stops the post.

**Hole 4 — No post IDs in thread context.**
`ward_room_router.py:294-298` formats thread context as:
```
{callsign}: {body}
```
No `id` field. Agents cannot construct `[ENDORSE post_id UP/DOWN]`.

## Changes

### 1. Unified reply cap — single source of truth (`ward_room_router.py`)

Create a new public method on `WardRoomRouter`:

```python
def check_and_increment_reply_cap(
    self, thread_id: str, agent_id: str
) -> bool:
    """Check whether agent_id may reply to thread_id.

    Returns True if the agent is under the cap (reply allowed).
    Returns False if the cap is reached (reply blocked).
    When True, atomically increments the counter.

    AD-629: Single enforcement point. Both ward_room_router.route_event()
    and proactive.py._extract_and_execute_replies() call this instead of
    inlining their own checks.
    """
```

Implementation:
- Look up `max_per_thread` from config (default 3)
- Apply proficiency override via `_get_comm_gate_overrides(agent_id)`
- Check `self._agent_thread_responses[f"{thread_id}:{agent_id}"]`
- If under cap: increment and return `True`
- If at/over cap: log and return `False`

**Important:** This method is always called, including for `is_direct_target`.
The `@mention` bypass should skip cooldowns (timing) but NOT skip the
per-thread cap. An @mentioned agent still can't reply 5 times to one
thread. Remove the `if not is_direct_target` guards around the cap check
(line 373) and the counter increment (line 461). Keep `is_direct_target`
bypass ONLY for cooldown checks.

### 2. Wire proactive `[REPLY]` path through the unified cap (`proactive.py`)

In `_extract_and_execute_replies()`, before the `create_post()` call at
line 2637, add:

```python
# AD-629: Per-thread reply cap — unified enforcement
wr_router = getattr(rt, 'ward_room_router', None)
if wr_router and not wr_router.check_and_increment_reply_cap(thread_id, agent.id):
    logger.debug(
        "AD-629: Reply cap hit for %s in thread %s",
        agent.agent_type, thread_id[:8],
    )
    continue
```

Place this AFTER the BF-171 per-channel cooldown check (line 2618) and
BEFORE the callsign lookup (line 2620). The cap is the final structural
gate before posting.

**Verify:** `rt.ward_room_router` exists. Check how `ward_room_router` is
wired to the runtime. If it's not a direct attribute, find the correct
access path (it may be accessible via `self._ward_room_router` on the
proactive loop, or needs to be passed during init). Read `proactive.py`
constructor and `startup/phase_*.py` files to find the wiring. Do NOT
guess — read the code.

### 3. Per-department reply gate (`ward_room_router.py`)

Add a department-level gate in `check_and_increment_reply_cap()`. After
the per-agent cap check passes, check per-department cap:

```python
# AD-629: Per-department gate (AD-424 chief funnel)
# Max one reply per department per thread. If another agent from
# the same department already replied, block unless this agent
# is the department chief.
```

Implementation:
- Use `self._ontology.get_post_for_agent(agent_type)` to get the
  agent's `Post`, which has `department_id`
- Need to map `agent_id` → `agent_type`. The registry is available as
  `self._registry`. Use `self._registry.get(agent_id)` to get the agent,
  then `agent.agent_type`
- Track department replies: add `self._dept_thread_responses: dict[str, set[str]]`
  keyed by `f"{thread_id}"`, value is set of department_ids that have replied
- If this agent's department already has a reply AND this agent is NOT the
  department chief → block
- Department chief identification: check if the agent's post has
  `is_chief` or similar field. Read the `Post` dataclass in
  `ontology/models.py` to verify the field name. If no chief field exists,
  use the approach: if department has no reply yet, allow; if department
  already has a reply, block (first responder wins).
- Clean up `_dept_thread_responses` in the existing cleanup method
  alongside `_agent_thread_responses` (around line 910)

### 4. Include post IDs in thread context (`ward_room_router.py`)

At line 292-298, change the thread context formatting to include post IDs:

**Current** (line 296-298):
```python
for p in recent_posts:
    p_callsign = p.get("author_callsign", ...) 
    p_body = p.get("body", ...)
    thread_context += f"\n{p_callsign}: {p_body}"
```

**New:**
```python
for p in recent_posts:
    p_id = p.get("id", "") if isinstance(p, dict) else getattr(p, "id", "")
    p_callsign = p.get("author_callsign", "") if isinstance(p, dict) else getattr(p, "author_callsign", "")
    p_body = p.get("body", "") if isinstance(p, dict) else getattr(p, "body", "")
    # AD-629: Include post ID so agents can construct [ENDORSE post_id UP/DOWN]
    _id_prefix = f"[{p_id[:8]}] " if p_id else ""
    thread_context += f"\n{_id_prefix}{p_callsign}: {p_body}"
```

Use first 8 chars of the UUID — enough for uniqueness, not overwhelming.
The agent's system prompt already tells them to use `[ENDORSE post_id UP]`.

### 5. Include post IDs in proactive Ward Room activity context (`proactive.py`)

Find where Ward Room activity is formatted for proactive_think context.
Search for where `ward_room_activity` is built — likely in
`_collect_ward_room_activity()` or similar. Include post IDs in the same
`[{id_prefix}]` format so agents can endorse during proactive thinks too.

**Verify:** Read the code that builds `ward_room_activity` context. The
format should match what's done in step 4. Do NOT guess the method name
or location — search for `ward_room_activity` in proactive.py.

### 6. Replace inline cap check in `route_event()` (`ward_room_router.py`)

Replace the existing inline cap check at lines 373-386 and the counter
increment at lines 460-462 with a call to `check_and_increment_reply_cap()`:

**Before** (lines 373-386 + 460-462):
```python
if not is_direct_target:
    max_per_thread = ...
    _overrides = ...
    thread_agent_key = ...
    prior_responses = ...
    if prior_responses >= max_per_thread:
        ...
        continue
...
if not is_direct_target:
    self._agent_thread_responses[thread_agent_key] = prior_responses + 1
```

**After:**
```python
# AD-629: Unified reply cap (applies to all agents, including @mentioned)
if not self.check_and_increment_reply_cap(thread_id, agent_id):
    logger.debug(
        "AD-629: Reply cap hit for %s in thread %s",
        agent_id[:12], thread_id[:8],
    )
    continue
```

Remove the old increment block at lines 460-462 entirely — the counter
is now incremented inside `check_and_increment_reply_cap()`.

Keep `is_direct_target` bypass ONLY for cooldown timing checks (the
`self._cooldowns` check earlier in the loop).

## Test Requirements

### Unit Tests (new file: `tests/test_ad629_reply_gate.py`)

1. **TestCheckAndIncrementReplyCap**
   - `test_first_reply_allowed` — returns True, counter incremented
   - `test_at_cap_blocked` — returns False after N replies
   - `test_proficiency_override_changes_cap` — novice=1, expert=5
   - `test_mentioned_agent_still_capped` — @mention does NOT bypass cap
   - `test_department_gate_first_agent_allowed` — first from dept passes
   - `test_department_gate_second_agent_blocked` — second from same dept blocked
   - `test_different_departments_both_allowed` — agents from different depts pass
   - `test_counter_survives_across_calls` — multiple calls accumulate

2. **TestProactiveReplyCapIntegration**
   - `test_proactive_reply_checks_cap` — `[REPLY]` path calls cap check
   - `test_proactive_reply_blocked_at_cap` — reply suppressed when cap hit

3. **TestPostIdInContext**
   - `test_thread_context_includes_post_ids` — formatted as `[{id}] callsign: body`
   - `test_proactive_activity_includes_post_ids` — same format

4. **TestDepartmentCleanup**
   - `test_dept_responses_cleaned_with_thread` — cleanup method clears dept state

### Existing test verification

Run after implementation:
```
pytest tests/test_ad629_reply_gate.py -v
pytest tests/test_ad625_comm_discipline.py -v
pytest tests/test_ad626_skill_activation.py -v
pytest tests/ -k "ward_room" --tb=short
```

## Files to Modify

| File | Change |
|------|--------|
| `src/probos/ward_room_router.py` | `check_and_increment_reply_cap()`, dept gate, post IDs in context, replace inline cap |
| `src/probos/proactive.py` | Wire `[REPLY]` path through unified cap, post IDs in activity context |
| `tests/test_ad629_reply_gate.py` | New test file |

## Do NOT Change

- `ward_room/threads.py` — post creation is infrastructure, gate is caller's job
- `cognitive_agent.py` — no changes needed, prompt already mentions ENDORSE
- `comm_proficiency.py` — proficiency tiers unchanged
- `config.py` — existing config values are fine

## Verification Checklist

- [ ] Proactive `[REPLY]` path respects per-thread cap
- [ ] @mentioned agents are capped (skip cooldown, not cap)
- [ ] Per-department limit: one reply per department per thread
- [ ] Thread context includes `[post_id]` prefix on each post
- [ ] Proactive Ward Room activity includes post IDs
- [ ] Existing tests still pass
- [ ] No new `except Exception: pass` without justification
