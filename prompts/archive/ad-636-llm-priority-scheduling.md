# AD-636: LLM Priority Scheduling & Load Distribution

## Problem Statement

AD-632 sub-task chains increased LLM call volume 3-5x per agent (QUERY + ANALYZE + COMPOSE + EVALUATE + REFLECT vs single call). With 14 crew agents running proactive cycles every 120s plus ward room notification chains, the LLM proxy saturates. Captain DMs (direct_message intent) queue behind background chains and timeout at the 30s TTL — a chain-of-command violation. The Captain must always get the stick.

## Root Cause Analysis

Three gaps in the current architecture:

1. **No priority differentiation** — `llm_client.py` treats all requests equally. A Captain DM competes with a background proactive think for the same rate limiter slot.
2. **No inter-agent staggering** — `proactive.py:_run_cycle()` iterates all crew agents sequentially with no delay between them. This creates bursty LLM call patterns even though dispatch is sequential, because each agent's chain spawns multiple async LLM calls.
3. **No global concurrency cap** — Nothing limits how many simultaneous LLM calls are in-flight across all subsystems. If 14 agents each run a 5-step chain, that's up to 70 queued LLM calls.

## Design

### Part A: Priority Lanes in LLM Client

Add a `priority` parameter to `LLMClient.complete()`.

Two priority classes:
- **`interactive`** — Captain DMs, direct_message intent, HXI chat, shell commands. Reserved capacity.
- **`background`** — proactive_think, ward_room_notification, dream consolidation, sub-task chains. Yields to interactive.

Implementation:
- Add `asyncio.Semaphore` in `LLMClient.__init__()` for global concurrency cap. Config: `llm.max_concurrent_calls` (default: 6).
- Add a **separate** `asyncio.Semaphore` for interactive requests with reserved slots (default: 2 of the 6). Interactive requests acquire only the interactive semaphore. Background requests acquire the background semaphore (remaining 4 slots).
- When interactive semaphore is available, interactive requests proceed immediately — no RPM rate limit wait.
- Add `priority: str = "background"` parameter to `LLMClient.complete()`. Default is background so all existing callers work unchanged.

Callers that should pass `priority="interactive"`:
- `_decide_via_llm()` when `observation.get("intent") == "direct_message"` — check in `cognitive_agent.py`
- Any caller originating from HXI chat endpoint (`routers/chat.py`)

### Part B: Proactive Loop Staggering

Add inter-agent delay in `proactive.py:_run_cycle()` to distribute LLM load evenly across the cycle interval.

**Slot-based scheduling:**
- After each `_think_for_agent()` call, `await asyncio.sleep(stagger_delay)`.
- `stagger_delay = interval_seconds / eligible_agent_count` (e.g., 120s / 14 = 8.5s).
- If the stagger delay would exceed the remaining cycle time, reduce proportionally.
- Config: `proactive.stagger_enabled` (default: `true`), `proactive.min_stagger_seconds` (default: 5.0).

This converts the current "burst at cycle start" pattern into evenly distributed load.

### Part C: DM TTL Increase

Increase `IntentMessage.ttl_seconds` for direct_message intents to 60s.

- In `routers/agents.py` (HXI DM endpoint): set `IntentMessage(..., ttl_seconds=60.0)`
- In `experience/commands/session.py` (shell /hail): set `IntentMessage(..., ttl_seconds=60.0)`
- Default TTL (30s) unchanged for all other intents.

### Part D: Chain Concurrency Cap

Add a global semaphore to `SubTaskExecutor` limiting concurrent chain executions across all agents.

- Config: `sub_task.max_concurrent_chains` (default: 4).
- `asyncio.Semaphore(max_concurrent_chains)` in `SubTaskExecutor.__init__()`.
- Acquired at `SubTaskExecutor.execute()` entry, released on return.
- Prevents N agents from all running chains simultaneously.
- Interactive intents (direct_message) do NOT use chains, so this doesn't affect DM latency.

## Files to Modify

1. **`src/probos/cognitive/llm_client.py`** — Add priority parameter, global concurrency semaphore, interactive reserved slots
2. **`src/probos/proactive.py`** — Add stagger delay in `_run_cycle()` between agent iterations
3. **`src/probos/cognitive/sub_task.py`** — Add `max_concurrent_chains` semaphore to `SubTaskExecutor`
4. **`src/probos/cognitive/cognitive_agent.py`** — Pass `priority="interactive"` for direct_message intents in `_decide_via_llm()`
5. **`src/probos/routers/agents.py`** — Set `ttl_seconds=60.0` on DM IntentMessage
6. **`src/probos/experience/commands/session.py`** — Set `ttl_seconds=60.0` on shell DM IntentMessage
7. **`src/probos/config.py`** — Add config fields: `llm.max_concurrent_calls`, `proactive.stagger_enabled`, `proactive.min_stagger_seconds`, `sub_task.max_concurrent_chains`
8. **`config/system.yaml`** — Add default values

## Config Additions

```yaml
llm:
  max_concurrent_calls: 6        # global semaphore cap
  interactive_reserved_slots: 2  # reserved for interactive priority

proactive:
  stagger_enabled: true
  min_stagger_seconds: 5.0

sub_task:
  max_concurrent_chains: 4       # cap simultaneous chain executions
```

## Engineering Principles

- **SOLID (O):** Priority parameter extends LLMClient without changing existing callers (default="background").
- **SOLID (D):** Semaphores injected via config, not hardcoded.
- **Fail Fast:** If interactive semaphore unavailable (shouldn't happen with 2 reserved), log warning and proceed without semaphore — degrade, don't block Captain.
- **HXI Cockpit View:** Captain interactions always get priority. "The Captain always needs the stick."
- **Cloud-Ready:** Semaphore counts configurable. Commercial deployments with more LLM capacity increase limits.

## Test Plan

### Part A — Priority Lanes (12-15 tests)
- `test_priority_interactive_bypasses_background_queue` — interactive request proceeds when background semaphore full
- `test_priority_background_respects_concurrency_cap` — background blocks at cap
- `test_priority_default_is_background` — existing callers unchanged
- `test_interactive_reserved_slots` — interactive has dedicated capacity
- `test_concurrent_calls_exceed_cap` — excess calls wait, don't fail
- `test_priority_parameter_propagated` — LLMClient passes priority through

### Part B — Stagger (6-8 tests)
- `test_stagger_delay_calculated_from_interval_and_count` — 120s / 14 = 8.5s
- `test_stagger_adds_delay_between_agents` — verify sleep called between iterations
- `test_stagger_disabled_when_config_false` — no delay when disabled
- `test_stagger_min_seconds_floor` — delay not below min_stagger_seconds
- `test_stagger_handles_single_agent` — no division by zero
- `test_cycle_completes_within_interval` — stagger doesn't extend cycle beyond interval

### Part C — DM TTL (3-4 tests)
- `test_hxi_dm_ttl_60_seconds` — HXI DM endpoint sets 60s TTL
- `test_shell_dm_ttl_60_seconds` — shell /hail sets 60s TTL
- `test_default_ttl_unchanged` — non-DM intents keep 30s

### Part D — Chain Concurrency Cap (5-6 tests)
- `test_chain_semaphore_limits_concurrent_chains` — max 4 concurrent
- `test_chain_semaphore_releases_on_completion` — slot freed after chain
- `test_chain_semaphore_releases_on_failure` — slot freed on exception
- `test_chain_concurrency_config` — semaphore count from config
- `test_chain_semaphore_does_not_block_interactive` — DMs bypass chains entirely

**Total: 26-33 tests**

## Backward Compatibility

- All new parameters have defaults matching current behavior (no semaphore before = effectively infinite, no stagger = 0 delay).
- `priority="background"` default means zero changes for existing callers.
- Config additions are optional — system works without them using defaults.

## Acceptance Criteria

1. Captain DMs respond within 15s even under full proactive cycle load
2. No `Agent did not respond in time` errors for direct_message intents
3. Proactive cycle LLM calls distributed evenly across interval (no burst)
4. Chain execution limited to N concurrent (configurable)
5. All existing tests pass unchanged
6. 26+ new tests covering priority, staggering, TTL, and chain cap
