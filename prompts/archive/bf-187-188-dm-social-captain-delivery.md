# BF-187/BF-188: DM Social Obligation + Captain Delivery Guarantee

## Problem

Two bugs prevent crew from replying to DMs and cause partial Captain delivery:

### BF-187: DM Social Obligation Missing
When a crew member sends a DM to another crew member, the DM arrives as a `ward_room_notification` intent and goes through the sub-task chain (AD-632). The chain's Analyze step can return `SILENT`, causing Compose to short-circuit to `[NO_RESPONSE]`. The Evaluate step can return `suppress`. None of the existing social obligation bypasses catch this because:
- `_from_captain` is False (it's crew-to-crew)
- `_was_mentioned` is False (DMs don't use @mentions)
- No `_is_dm` flag exists

**Result:** Agents never reply to DMs from other crew. In the old single-shot pipeline, DMs always got responses because there were no quality gates. The chain pipeline introduced three suppression points (Compose SILENT, Evaluate suppress, Reflect suppress) without recognizing DMs as social obligations.

### BF-188: Captain Delivery Race Condition
When the Captain posts to the ship channel, `_ward_room_emit()` in `startup/communication.py` fires `asyncio.create_task(_bounded_route())` — fire-and-forget. The `route_event()` in `ward_room_router.py` processes target agents **sequentially** via `await self._intent_bus.send(intent)`. While agents 1-6 are being processed (each waits for full cognitive chain completion), the agents that have already responded create new ward room posts, which trigger additional `_ward_room_emit()` calls, spawning **concurrent** routing tasks.

These concurrent tasks compete for LLM capacity with the Captain's still-in-progress delivery loop. Result: some agents may timeout or get starved — the Captain's delivery to agents 7-14 competes with agent-reply notifications for agents 1-6.

**Result:** Only 6/14 crew responded to the Captain's all-hands post (2026-04-16). The routing was sequential-by-design but concurrent-in-practice due to fire-and-forget task spawning.

## Root Cause

1. **BF-187:** The social obligation bypass pattern (BF-184/185/186) only recognizes two flags (`_from_captain`, `_was_mentioned`). DM receipt is a social obligation that was never encoded. The intent params at `ward_room_router.py` line 437-449 don't include `channel_type`, so the chain context has no way to detect DM channels.

2. **BF-188:** No coordination between Captain delivery and agent-reply routing. Both use the same `_ward_room_emit()` → `create_task()` → `_bounded_route()` → `route_event()` pipeline with only a `Semaphore(10)` for backpressure (AD-616). This is a stopgap until AD-637 (NATS event bus) provides proper priority and delivery guarantees.

## Fix

### Part 1: Add `is_dm_channel` to intent params (`ward_room_router.py`)

At line 437, the intent is constructed with params. Add `is_dm_channel` from the `channel` object already available in scope (line 272):

```python
intent = IntentMessage(
    intent="ward_room_notification",
    params={
        "event_type": event_type,
        "thread_id": thread_id,
        "channel_id": channel_id,
        "channel_name": channel.name,
        "title": title,
        "author_id": author_id,
        "author_callsign": data.get("author_callsign", ""),
        "was_mentioned": agent_id in mentioned_agent_ids,
        # BF-187: DM channel flag for social obligation bypass in chain
        "is_dm_channel": getattr(channel, 'channel_type', '') == "dm",
    },
    context=thread_context,
    target_agent_id=agent_id,
)
```

The `channel` variable is already resolved at line 272 (`channel = await self._ward_room.get_channel(channel_id)`) and is in scope at line 437. `channel_type` is a field on the ward room channel object — verify with: `grep -n "channel_type" src/probos/ward_room.py`.

### Part 2: Extract `_is_dm` into chain context (`cognitive_agent.py`)

In `_execute_sub_task_chain()`, after the existing social obligation flags (line 1593), add:

```python
# BF-187: DM social obligation — DM recipients must always respond
observation["_is_dm"] = _params.get("is_dm_channel", False)
```

This follows the exact same pattern as `_from_captain` (line 1592) and `_was_mentioned` (line 1593).

### Part 3: Add `_is_dm` to Compose SILENT bypass (`compose.py`)

In `_should_short_circuit()` (line 32-44), add `_is_dm` to the existing social obligation check:

**Current** (line 35):
```python
if context and (context.get("_from_captain") or context.get("_was_mentioned")):
    return False
```

**New:**
```python
# BF-186 + BF-187: Social obligation overrides SILENT
if context and (context.get("_from_captain") or context.get("_was_mentioned") or context.get("_is_dm")):
    return False
```

### Part 4: Add `_is_dm` to Evaluate bypass (`evaluate.py`)

In `EvaluateHandler.__call__()` (line 244), add `_is_dm` to the existing bypass:

**Current:**
```python
if context.get("_from_captain") or context.get("_was_mentioned"):
```

**New:**
```python
# BF-184 + BF-187: Captain, @mention, and DM bypass quality gate
if context.get("_from_captain") or context.get("_was_mentioned") or context.get("_is_dm"):
```

Update the `reason` assignment to include the DM case:
```python
if context.get("_from_captain"):
    reason = "captain_message"
elif context.get("_was_mentioned"):
    reason = "mentioned"
else:
    reason = "dm_recipient"
```

Update the log message prefix from "BF-184" to "BF-184/187".

### Part 5: Add `_is_dm` to Reflect bypass AND fix suppress ordering (`reflect.py`)

Two changes in `ReflectHandler.__call__()`:

**Change 1 — Fix suppress/social-obligation ordering (line 262-302):**

Currently, the suppress short-circuit (line 263) runs BEFORE the social obligation bypass (line 279). This means if Evaluate returns `"suppress"` for a DM (which it currently can, since there's no DM bypass in evaluate yet), Reflect will honor the suppress and return `[NO_RESPONSE]` without ever checking social obligation.

Move the social obligation check ABOVE the suppress check. The logic should be:

```python
# 1. Social obligation bypass (BF-185 + BF-187) — FIRST
if context.get("_from_captain") or context.get("_was_mentioned") or context.get("_is_dm"):
    compose_output = _get_compose_output(prior_results)
    if context.get("_from_captain"):
        reason = "captain_message"
    elif context.get("_was_mentioned"):
        reason = "mentioned"
    else:
        reason = "dm_recipient"
    logger.info(
        "BF-185/187: Reflect auto-approved for %s (social obligation: %s)",
        context.get("_agent_type", "unknown"),
        reason,
    )
    return SubTaskResult(
        sub_task_type=SubTaskType.REFLECT,
        name=spec.name,
        result={
            "output": compose_output,
            "revised": False,
            "suppressed": False,
            "bypass_reason": reason,
        },
        tokens_used=0,
        duration_ms=int((time.monotonic() - start) * 1000),
        success=True,
        tier_used="",
    )

# 2. Suppress short-circuit (Evaluate recommended suppress) — AFTER social obligation
if _should_suppress(prior_results):
    ...
```

**Why the reorder:** Defense in depth. Even if a bug causes Evaluate to return "suppress" for a socially obligated message (Captain, @mention, DM), Reflect won't suppress it. Social obligation outranks quality assessment at every gate.

Note: For `_from_captain` and `_was_mentioned` this reorder is currently a no-op (Evaluate already auto-approves so it would never recommend suppress). But for `_is_dm`, this is critical — until Part 4 is implemented and tested, the ordering fix provides a safety net.

### Part 6: Captain delivery coordination (`ward_room_router.py`)

Add an `asyncio.Event` to coordinate Captain delivery:

**In `__init__`:**
```python
# BF-188: Captain delivery coordination — agent-reply routing waits
# until Captain's routing to all targets completes
self._captain_delivery_done: asyncio.Event = asyncio.Event()
self._captain_delivery_done.set()  # Initially done (no Captain routing in progress)
```

**In `route_event()`, after the `is_captain` / `is_agent_post` determination (line 236):**

```python
# BF-188: Agent-reply routing waits for Captain delivery to complete
if is_agent_post:
    try:
        await asyncio.wait_for(self._captain_delivery_done.wait(), timeout=120.0)
    except asyncio.TimeoutError:
        logger.warning("BF-188: Timed out waiting for Captain delivery, proceeding")
```

**Wrap the target routing loop** (the `for agent_id in targets:` loop that starts around line 395):

```python
if is_captain:
    self._captain_delivery_done.clear()

try:
    for agent_id in targets:
        ...  # existing routing logic
finally:
    if is_captain:
        self._captain_delivery_done.set()
```

This ensures all 14 agents receive the Captain's message before any agent-reply routing begins. The `asyncio.Event` blocks agent-reply routing only while Captain delivery is in progress. 120s timeout prevents deadlock if Captain routing hangs.

**Add `import asyncio`** to `ward_room_router.py` if not already imported.

## Files to Modify

1. **`src/probos/ward_room_router.py`** — Add `is_dm_channel` to intent params (Part 1) + Captain delivery coordination (Part 6)
2. **`src/probos/cognitive/cognitive_agent.py`** — Extract `_is_dm` into chain context (Part 2), 1 line
3. **`src/probos/cognitive/sub_tasks/compose.py`** — Add `_is_dm` to `_should_short_circuit()` bypass (Part 3)
4. **`src/probos/cognitive/sub_tasks/evaluate.py`** — Add `_is_dm` to quality gate bypass (Part 4)
5. **`src/probos/cognitive/sub_tasks/reflect.py`** — Add `_is_dm` to bypass + reorder suppress/social-obligation (Part 5)

## Tests

Write tests in `tests/test_bf187_bf188_dm_captain_delivery.py`. Minimum 18 tests:

### BF-187: DM Social Obligation (12 tests)

**Intent params (2 tests):**
1. `test_intent_params_include_is_dm_channel_true` — When routing a DM channel post, verify `is_dm_channel` is True in the IntentMessage params. Mock ward_room.get_channel to return a channel with `channel_type="dm"`.
2. `test_intent_params_include_is_dm_channel_false` — When routing a ship channel post, verify `is_dm_channel` is False.

**Chain context injection (2 tests):**
3. `test_chain_context_includes_is_dm` — Verify `observation["_is_dm"]` is True when params contain `is_dm_channel=True`.
4. `test_chain_context_is_dm_false_by_default` — Verify `observation["_is_dm"]` is False when params don't contain `is_dm_channel`.

**Compose bypass (2 tests):**
5. `test_compose_short_circuit_bypassed_for_dm` — When analyze returns SILENT but `_is_dm` is True, `_should_short_circuit()` returns False.
6. `test_compose_short_circuit_normal_for_non_dm` — When analyze returns SILENT and `_is_dm` is False (and no other social obligation), `_should_short_circuit()` returns True.

**Evaluate bypass (2 tests):**
7. `test_evaluate_bypassed_for_dm` — When `_is_dm` is True, EvaluateHandler returns auto-approved result with `bypass_reason="dm_recipient"`.
8. `test_evaluate_not_bypassed_without_dm` — When `_is_dm` is False (and no other social obligation), EvaluateHandler proceeds to LLM call.

**Reflect bypass (4 tests):**
9. `test_reflect_bypassed_for_dm` — When `_is_dm` is True, ReflectHandler returns compose output unmodified with `bypass_reason="dm_recipient"`.
10. `test_reflect_dm_overrides_suppress` — When `_is_dm` is True AND Evaluate recommended suppress, Reflect still returns compose output (NOT `[NO_RESPONSE]`). **This tests the reorder fix.**
11. `test_reflect_suppress_still_works_without_social` — When `_is_dm` is False (and no other social obligation) and Evaluate recommended suppress, Reflect returns `[NO_RESPONSE]`. Regression test for existing behavior.
12. `test_reflect_captain_overrides_suppress` — When `_from_captain` is True AND Evaluate recommended suppress, Reflect returns compose output. Regression test that the reorder doesn't break existing behavior.

### BF-188: Captain Delivery Coordination (6 tests)

13. `test_captain_delivery_event_cleared_on_start` — When a Captain post enters `route_event()`, `_captain_delivery_done` is cleared before routing begins.
14. `test_captain_delivery_event_set_on_completion` — After Captain routing completes (even with errors), `_captain_delivery_done` is set.
15. `test_agent_routing_waits_for_captain` — When a Captain routing is in progress, agent-triggered `route_event()` waits on the Event before proceeding.
16. `test_agent_routing_proceeds_when_no_captain` — When no Captain routing is in progress, agent-triggered `route_event()` proceeds immediately (Event is already set).
17. `test_captain_delivery_event_set_on_exception` — If Captain routing raises an exception, `_captain_delivery_done` is still set (try/finally). No deadlock.
18. `test_captain_delivery_timeout_proceeds` — If Captain delivery takes >120s, agent routing times out and proceeds with a warning log.

## Prior Work to Preserve

- **BF-051/052:** `_compose_dm_instructions()` — department-grouped crew roster. Already injected in chain context as `_crew_manifest` (BF-186). No changes needed.
- **BF-156:** DM channels bypass thread depth cap in `route_event()`. No conflict — BF-187 operates at chain level, BF-156 at routing level.
- **BF-157:** DM recipients bypass cooldown in routing (`is_direct_target`). Complementary — BF-157 ensures routing delivers to the agent, BF-187 ensures the chain doesn't suppress the response.
- **BF-184/185/186:** Social obligation bypass pattern (`_from_captain`, `_was_mentioned`). BF-187 extends the same pattern with `_is_dm`. Same code locations, same structure.
- **AD-614:** DM exchange limit (6). Routing-level cap — still applies after BF-187. Agents will respond to the first 6 DM exchanges per thread, then stop. BF-187 doesn't override routing-level limits, only chain-level quality gates.
- **AD-616:** Semaphore(10) in `_ward_room_emit()`. BF-188 adds coordination above the semaphore, not replacing it.
- **AD-623:** DM convergence gate. Routing-level — applies before the intent is sent to the agent. BF-187 doesn't conflict.
- **AD-629:** Unified reply cap. Still applies — BF-187 doesn't bypass the per-thread per-agent cap (3 responses per thread).
- **AD-632d SRP:** Compose produces text only; action tag parsing happens downstream in `act()`. Preserved.

## Engineering Principles

- **DRY:** Social obligation check at each gate follows identical pattern (`context.get("_from_captain") or context.get("_was_mentioned") or context.get("_is_dm")`). Three flags, one boolean expression, four check sites.
- **Single Responsibility:** `ward_room_router.py` adds one field to intent params (transport responsibility). `cognitive_agent.py` extracts one flag (context responsibility). Sub-task handlers check one composite condition (gate responsibility). Each change is one line or one conditional.
- **Open/Closed:** New social obligation flags can be added to the same pattern without modifying the bypass logic structure. Just add another `or context.get("_is_X")`.
- **Defense in Depth:** Social obligation is checked at ALL four chain gates (Compose, Evaluate, Reflect, and now the suppress ordering fix). If one gate has a bug, the others catch it.
- **Fail Fast:** Captain delivery Event has a 120s timeout — agent routing proceeds with a warning rather than deadlocking.
- **Law of Demeter:** `is_dm_channel` is derived from `channel.channel_type` in the router, then passed as a flat boolean through intent params. Chain handlers don't reach into ward room objects — they read a flat flag from their context dict.

## Verification

1. `pytest tests/test_bf187_bf188_dm_captain_delivery.py -x -q`
2. `pytest tests/test_bf184_evaluate_social_bypass.py tests/test_bf185_reflect_social_bypass.py tests/test_bf186_compose_standing_orders.py -x -q` (regression — existing social bypass still works)
3. `pytest tests/ -x -q -o "addopts="` (full suite, override xdist)
4. Grep verify: `grep -rn "_is_dm" src/probos/` should show exactly 5 files (ward_room_router.py, cognitive_agent.py, compose.py, evaluate.py, reflect.py)
