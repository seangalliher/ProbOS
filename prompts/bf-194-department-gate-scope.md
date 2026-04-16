# BF-194: Department Gate Applies to Non-Department Channels

## Overview

Captain all-hands messages only reach ~6 of 14 crew. Root cause: AD-629's per-department "first responder wins" gate in `check_and_increment_reply_cap()` fires on **all** channels, not just department channels. On ship-wide channels (All Hands, Recreation), once one Science agent responds, all other Science agents are blocked. With 5 departments covering 14 agents, the maximum is ~6 responses (one per department + bridge).

## Root Cause

`check_and_increment_reply_cap(thread_id, agent_id)` has no channel context. The department gate (lines 137-150) fires unconditionally:

```python
# --- Per-department gate (first responder wins) ---
dept_id = None
if self._ontology:
    agent_obj = self._registry.get(agent_id)
    if agent_obj:
        dept_id = self._ontology.get_agent_department(agent_obj.agent_type)
if dept_id:
    dept_set = self._dept_thread_responses.get(thread_id, set())
    if dept_id in dept_set:
        return False  # Blocked — department already responded
    self._dept_thread_responses.setdefault(thread_id, set()).add(dept_id)
```

This is correct for department channels (prevents pile-on from the home department). It is **wrong** for ship-wide channels where the Captain expects all crew to respond.

Department distribution:
- Science: 5 agents (architect, scout, data_analyst, systems_analyst, research_specialist) → only 1 responds
- Medical: 4 agents (diagnostician, surgeon, pharmacist, pathologist) → only 1 responds
- Engineering: 2 agents (engineering_officer, builder) → only 1 responds
- Security: 1 agent (security_officer) → responds
- Operations: 1 agent (operations_officer) → responds
- Bridge: 1 agent (counselor) → responds

Maximum: 6 responses. Observed: 5-6 (exact number depends on race conditions in parallel dispatch).

## Fix

### Part 1: Add `is_department_channel` parameter

Add an `is_department_channel: bool = False` parameter to `check_and_increment_reply_cap()`. Wrap the department gate with `if is_department_channel:`.

```python
def check_and_increment_reply_cap(
    self, thread_id: str, agent_id: str,
    *, is_department_channel: bool = False,
) -> bool:
```

The department gate block (lines 137-152) becomes:

```python
# --- Per-department gate (first responder wins) ---
# BF-194: Only apply on department channels — ship-wide channels
# (All Hands, Recreation) allow multiple agents per department.
if is_department_channel:
    dept_id = None
    if self._ontology:
        agent_obj = self._registry.get(agent_id)
        if agent_obj:
            dept_id = self._ontology.get_agent_department(agent_obj.agent_type)
    if dept_id:
        dept_set = self._dept_thread_responses.get(thread_id, set())
        if dept_id in dept_set:
            logger.debug(
                "AD-629: Dept %s already replied in thread %s, blocking %s",
                dept_id, thread_id[:8], agent_id[:12],
            )
            return False
        self._dept_thread_responses.setdefault(thread_id, set()).add(dept_id)
```

Default `False` is safe — existing callers that don't pass the flag will **not** apply the department gate (correct for the common case: ship-wide channels).

### Part 2: Update call site in `_route_to_agents()` (ward_room_router.py)

Line 474 already has `channel` in scope. Pass the flag:

```python
# BF-016b: Per-thread agent response cap
# AD-629: Unified reply cap
if not self.check_and_increment_reply_cap(
    thread_id, agent_id,
    is_department_channel=(
        channel is not None
        and getattr(channel, 'channel_type', '') == "department"
    ),
):
    continue
```

### Part 3: Update call site in `proactive.py`

Line 2673 in `_extract_and_execute_replies()`. The `channel_id` is available at line 2655. Look up the channel to determine type:

```python
# AD-629: Per-thread reply cap — unified enforcement
wr_router = getattr(rt, 'ward_room_router', None)
if wr_router:
    # BF-194: Determine channel type for department gate scoping
    _is_dept_ch = False
    if channel_id:
        try:
            _ch = await rt.ward_room.get_channel(channel_id)
            _is_dept_ch = _ch is not None and getattr(_ch, 'channel_type', '') == "department"
        except Exception:
            pass  # Default False — safe (no department gate)
    if not wr_router.check_and_increment_reply_cap(
        thread_id, agent.id,
        is_department_channel=_is_dept_ch,
    ):
        logger.debug(
            "AD-629: Reply cap hit for %s in thread %s",
            agent.agent_type, thread_id[:8],
        )
        continue
```

**Note:** `get_channel()` is async. This is in an async context (`_extract_and_execute_replies` is `async def`), so this is fine. The result may be cached by Ward Room — check if `get_channel()` uses a cache. If not, this adds one DB lookup per reply extraction. Acceptable cost given it prevents the bug.

### Part 4: Tests

**File:** `tests/test_bf194_department_gate_scope.py`

1. `test_department_gate_blocks_on_department_channel` — Two agents from same department, `is_department_channel=True`. First passes, second blocked. Verify existing behavior preserved.

2. `test_department_gate_allows_on_ship_channel` — Two agents from same department, `is_department_channel=False`. Both pass. This is the bug fix.

3. `test_department_gate_default_false` — Call without `is_department_channel` kwarg. Two same-department agents both pass. Verifies safe default.

4. `test_per_agent_cap_still_enforced_on_ship_channel` — Same agent hits per-agent cap (default 3) on ship channel. Verify per-agent cap is independent of channel type.

5. `test_all_14_crew_eligible_ship_channel` — 14 mock crew agents across 6 departments. Ship channel. All 14 pass `check_and_increment_reply_cap()`.

6. `test_department_gate_mixed_channels` — Agent responds in department channel (department gate recorded), then replies in ship channel for same thread (department gate does NOT apply). Verify ship channel reply succeeds.

7. `test_proactive_reply_passes_channel_type` — Mock proactive reply path with ship-wide channel. Verify `check_and_increment_reply_cap` called with `is_department_channel=False`.

## Files

- **Modify:** `src/probos/ward_room_router.py`
  - `check_and_increment_reply_cap()`: Add `is_department_channel` parameter, wrap department gate
  - `_route_to_agents()` line 474: Pass `is_department_channel` flag
- **Modify:** `src/probos/proactive.py`
  - `_extract_and_execute_replies()` line 2673: Look up channel type, pass flag
- **New:** `tests/test_bf194_department_gate_scope.py`

## Engineering Principles

- **Single Responsibility:** `check_and_increment_reply_cap()` enforces reply caps. The caller determines channel context — cap logic doesn't reach into Ward Room for channel data.
- **Open/Closed:** Existing per-agent cap logic untouched. Department gate wrapped with a condition. No rewrite.
- **Defense in Depth:** Per-agent cap (universal) + per-department gate (department channels only). Two independent layers, each correctly scoped.
- **Fail Fast:** Default `is_department_channel=False` is the safe default — if channel lookup fails, department gate is skipped (over-permits rather than under-permits). For Captain all-hands, over-permitting is correct.
- **DRY:** Channel type check logic is inline at each call site (2 sites). Same pattern but different context (one has `channel` object, other has `channel_id` requiring lookup). Not worth extracting — 2 call sites.
- **Interface Segregation:** Added keyword-only parameter with safe default. Existing callers don't break.

## Scope Boundary

This BF does NOT:
- Change per-agent reply cap behavior — that stays universal
- Change department gate logic — only its activation scope
- Add new config — `is_department_channel` is derived from existing channel metadata
- Affect DM channels — DMs already bypass via `is_direct_target` in `_route_to_agents()`

## Prior Art

- **AD-629:** Introduced unified reply cap with per-department gate. This BF corrects the gate's scope.
- **BF-016b:** Original per-thread cap. Per-agent portion unchanged.
- **AD-625:** Proficiency-modulated overrides. Applied to per-agent cap, not department gate. Unchanged.
- **BF-193:** Parallel Captain dispatch. Works correctly — problem was upstream (this BF).
- **AD-424:** Thread modes (discuss/inform). `thread_max_responders` only applies to discuss mode. Not affected.

## Verification

```bash
python -m pytest tests/test_bf194_department_gate_scope.py -v
```

Then restart ProbOS and test:
```
Captain> Hello Crew, testing our communications. Everyone please acknowledge.
```

Expected: all 14 crew respond (not 5-6).
