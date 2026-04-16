# BF-193: Parallel Captain Message Dispatch

## Overview

Captain all-hands messages only reach 6/14 crew. Root cause: `_route_to_agents()` dispatches intents **sequentially** — each `await self._intent_bus.send(intent)` blocks until the full chain pipeline (QUERY → ANALYZE → COMPOSE → EVALUATE → REFLECT) completes (~10-15s per agent). With 14 agents and 30s TTL timeout, agents 7-14 compete with reply-triggered chains from agents 1-6, causing LLM scheduler saturation and timeouts.

## Root Cause

```python
# Current: sequential — agent 2 waits for agent 1's full chain to finish
for agent_id in target_agent_ids:
    ...
    result = await self._intent_bus.send(intent)  # 10-15s per agent
    ... process result ...
```

14 agents × 10s average = 140s sequential. LLM scheduler (AD-636) saturates after 6 concurrent chains, deprioritizing the remaining 8.

## Fix

Split `_route_to_agents()` into three phases:

### Phase 1: Pre-filter eligible agents and build intents

Move the cooldown/cap/DM-limit checks into a pre-filter loop that builds a list of `(agent_id, intent)` tuples. No behavioral change — same guards, same order of evaluation.

### Phase 2: Concurrent dispatch

For **Captain messages only** (`is_captain=True`), dispatch all intents concurrently:

```python
if is_captain:
    # BF-193: Parallel dispatch — all crew hear Captain simultaneously
    async def _dispatch_one(agent_id, intent):
        try:
            return agent_id, await self._intent_bus.send(intent)
        except Exception as e:
            logger.warning("Ward Room agent notification failed for %s: %s", agent_id, e)
            return agent_id, None

    dispatch_results = await asyncio.gather(
        *[_dispatch_one(aid, intent) for aid, intent in eligible],
        return_exceptions=False,  # exceptions caught inside _dispatch_one
    )
else:
    # Non-Captain: sequential (existing behavior, prevents thread explosion)
    dispatch_results = []
    for agent_id, intent in eligible:
        try:
            result = await self._intent_bus.send(intent)
            dispatch_results.append((agent_id, result))
        except Exception as e:
            logger.warning("Ward Room agent notification failed for %s: %s", agent_id, e)
            dispatch_results.append((agent_id, None))
```

**Why only Captain?** Agent-triggered responses use sequential dispatch deliberately — it prevents thread explosion where 14 agents simultaneously respond to each other's posts, creating O(N²) cascading chains. Captain messages have social obligation bypass, so the quality gates don't suppress — every agent WILL respond, and that's the desired behavior.

### Phase 3: Sequential result processing

Process results in order — endorsements, DM extraction, recreation commands, posting, cooldown updates. This must be sequential because `create_post` ordering matters (posts appear in order).

```python
for agent_id, result in dispatch_results:
    if not result or not result.result:
        continue
    response_text = str(result.result).strip()
    # ... existing processing (endorsements, DMs, bracket stripping, posting) ...
```

### Part 4: Pass `is_captain` to `_route_to_agents()`

Add `is_captain` parameter to `_route_to_agents()` signature (it's already passed to the call site at line 406-411, just needs to be received).

## Files

**Modify:** `src/probos/ward_room_router.py`
- `_route_to_agents()`: Refactor into 3-phase structure
- Add `is_captain` parameter

**No other files changed.** This is contained to one method.

## Tests

**File:** `tests/test_bf193_parallel_captain_dispatch.py`

1. `test_captain_dispatch_is_parallel` — Mock `intent_bus.send()` with 100ms delay per call. 14 agents. Captain message. Verify total time < 2s (parallel), not 14 × 100ms sequential.

2. `test_captain_dispatch_all_agents_receive` — 14 mock agents, Captain message. Verify all 14 receive intents and all 14 responses are posted.

3. `test_agent_dispatch_stays_sequential` — Non-Captain message (`is_captain=False`). Verify agents are dispatched sequentially (each starts after prior finishes).

4. `test_captain_dispatch_handles_individual_failure` — 1 of 14 agents raises exception during `send()`. Verify other 13 still respond and post.

5. `test_captain_dispatch_respects_reply_cap` — Verify pre-filter still applies reply cap before dispatch. Agent at cap limit is excluded from dispatch batch.

6. `test_captain_dispatch_post_ordering` — Verify responses are posted in a consistent order (by position in `target_agent_ids`, not by completion time).

7. `test_captain_dispatch_cooldown_updated` — After parallel dispatch, verify all responding agents have updated cooldown timestamps.

## Engineering Principles

- **Single Responsibility:** Pre-filter, dispatch, and result processing are three distinct phases with clear boundaries.
- **Open/Closed:** Agent-triggered path unchanged. Captain path extended with parallel dispatch.
- **Defense in Depth:** Pre-filter still applies all existing guards (cooldown, reply cap, DM limit). Parallel dispatch doesn't bypass safety layers.
- **Fail Fast:** Individual agent failures in `_dispatch_one()` are caught and logged. Other agents continue. No cascade.
- **DRY:** Result processing is shared between Captain and non-Captain paths — same code processes `dispatch_results` regardless of how they were collected.

## Scope Boundary

This BF does NOT:
- Change the LLM scheduler (AD-636) — that's a separate concern
- Add NATS (AD-637) — this is a bridge fix
- Change non-Captain dispatch — sequential is correct for agent-triggered responses
- Add configurable concurrency limits — the natural limit is `Semaphore(10)` in `communication.py` + AD-636 scheduler

## Verification

```bash
python -m pytest tests/test_bf193_parallel_captain_dispatch.py -v
```

Then restart ProbOS and test:
```
Captain> Hello Crew, testing our communications. Everyone please acknowledge.
```

Expected: all 14 crew respond within ~30s (one chain timeout window), not 6/14.
