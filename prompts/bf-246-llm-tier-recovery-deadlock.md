# BF-246: LLM Tier Recovery Deadlock — Unreachable Tiers Cannot Self-Recover

## Problem

When the LLM proxy goes down for an extended period (hours), `OpenAICompatibleClient` accumulates thousands of consecutive failures on each tier. When the proxy comes back up, the tiers remain permanently stuck as "unreachable" because:

1. **No periodic health check exists.** `check_connectivity()` is only called at startup (`__main__.py:189`) and reactively when chat produces empty responses (`routers/chat.py:218`). There is no background loop.

2. **Fallback tiers are skipped when unreachable.** Line 379 of `llm_client.py`:
   ```python
   if self._tier_status.get(attempt_tier) is False and attempt_tier != tier:
       continue
   ```
   The primary requested tier is exempt (it still attempts), but fallback tiers are permanently skipped once `_tier_status` marks them `False`.

3. **Recovery requires 3 consecutive successes (BF-240 dwell-time).** Even if the primary tier gets a successful call, `_consecutive_failures` only resets after `_min_consecutive_healthy` (default 3) consecutive successes. But the proactive loop — the main source of LLM calls — records failures at the `ProactiveCognitiveLoop` level (line 702: `_update_llm_status(failure=True)`) which increments `_llm_failure_count` independently. When that counter hits thresholds, it emits `LLM_HEALTH_CHANGED` with status "degraded"/"offline", but there's no symmetric probing path to bring it back.

**Net effect:** After extended downtime, ProbOS requires a full restart to recover LLM connectivity. The health status logs show the counters frozen:
```
LLM tier fast unreachable: 5824 consecutive failures (threshold=3), last_success=43374.0s ago
LLM tier deep unreachable: 2313 consecutive failures (threshold=3), last_success=38810.9s ago
```

## Prior Art

- **BF-069** (Closed): Added per-tier health tracking, 3-failure unreachable threshold, status transitions, bridge alerts. Did NOT add periodic connectivity checks.
- **BF-240** (Closed): Added dwell-time recovery (3 consecutive successes required to clear failure counter). Correct for preventing flap, but assumes calls still flow. No call flow = no recovery.
- **BF-108** (Closed): MockLLMClient returns "mock" status. Not related to real connectivity recovery.

## Root Cause

There is no periodic task that calls `check_connectivity()`. The system relies entirely on organic request flow to detect recovery, but organic requests are suppressed/skipped when tiers are marked unreachable, creating a deadlock.

## Fix

Add a periodic connectivity probe task that runs independently of request flow.

### Section 1: Add `_start_health_loop` to `OpenAICompatibleClient`

**File:** `src/probos/cognitive/llm_client.py`

Add a method to start a background health probe loop. The loop should:
- Run every `health_probe_interval_seconds` (configurable, default 30 seconds)
- Call `check_connectivity()` (which already handles dwell-time recovery via BF-240)
- Only probe tiers that are currently degraded or unreachable (don't waste calls on healthy tiers)
- Log recovery transitions at INFO level
- Emit `LLM_HEALTH_CHANGED` event when overall status transitions (requires an emit callback)

```python
async def start_health_probe(
    self,
    interval_seconds: float = 30.0,
    emit_fn: Callable[[str, dict], None] | None = None,
) -> None:
    """BF-246: Periodic connectivity probe for recovery from extended outages.
    
    Runs check_connectivity() on a timer. Only probes tiers that are
    degraded/unreachable — healthy tiers are not re-checked.
    """
    self._health_probe_task: asyncio.Task | None = None
    self._health_probe_emit = emit_fn
    self._health_probe_task = asyncio.create_task(
        self._health_probe_loop(interval_seconds),
        name="llm-health-probe",
    )
```

```python
async def _health_probe_loop(self, interval: float) -> None:
    """Background loop: probe unreachable/degraded tiers."""
    while True:
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return
        
        # Only probe if at least one tier is not operational
        health = self.get_health_status()
        unhealthy_tiers = [
            tier for tier, info in health["tiers"].items()
            if info["status"] not in ("operational",)
        ]
        if not unhealthy_tiers:
            continue
        
        old_overall = health["overall"]
        results = await self.check_connectivity()
        new_health = self.get_health_status()
        new_overall = new_health["overall"]
        
        if old_overall != new_overall:
            logger.info(
                "BF-246: LLM health probe detected transition: %s -> %s (probed tiers: %s)",
                old_overall, new_overall, unhealthy_tiers,
            )
```

Add a `stop_health_probe` method:
```python
async def stop_health_probe(self) -> None:
    """BF-246: Cancel the background health probe."""
    task = getattr(self, "_health_probe_task", None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
```

Update `close()` to cancel the probe:
```python
async def close(self) -> None:
    await self.stop_health_probe()
    for client in self._clients.values():
        await client.aclose()
```

### Section 2: Add `health_probe_interval_seconds` to config

**File:** `src/probos/config.py`

Add to the LLM-related config section (find where `llm_health_min_consecutive_healthy` is configured — it's on `SystemConfig` as a top-level field accessed via `getattr`):

```python
health_probe_interval_seconds: float = 30.0  # BF-246: Periodic LLM connectivity probe
```

### Section 3: Wire the health probe at startup

**File:** `src/probos/startup/finalize.py`

In `finalize_startup()`, after the LLM client is available, start the health probe:

```python
# BF-246: Start periodic LLM health probe for recovery from extended outages
llm_client = getattr(runtime, "llm_client", None)
if llm_client and hasattr(llm_client, "start_health_probe"):
    probe_interval = getattr(config, "health_probe_interval_seconds", 30.0)
    emit_fn = getattr(runtime, "_emit_event", None)
    await llm_client.start_health_probe(
        interval_seconds=probe_interval,
        emit_fn=emit_fn,
    )
    logger.info("BF-246: LLM health probe started (interval=%.0fs)", probe_interval)
```

### Section 4: Cancel probe on shutdown

**File:** `src/probos/startup/finalize.py` (or wherever shutdown cleanup runs — check `shutdown_runtime` or equivalent)

Search for the shutdown function that calls `llm_client.close()` and ensure `stop_health_probe()` is called. If `close()` already calls it (per Section 1), this is handled automatically. Verify.

## Tests

**File:** `tests/test_bf246_llm_health_probe.py`

8 tests:

1. `test_health_probe_starts` — start probe, verify task is created and running
2. `test_health_probe_stops` — start then stop, verify task is cancelled
3. `test_health_probe_calls_connectivity` — mock `check_connectivity`, start probe with short interval, verify it gets called
4. `test_health_probe_skips_when_healthy` — set all tiers operational, verify `check_connectivity` is NOT called (no unnecessary probing)
5. `test_health_probe_probes_when_unhealthy` — set one tier unreachable, verify `check_connectivity` IS called
6. `test_health_probe_logs_transition` — mock a transition from unreachable to operational, verify INFO log
7. `test_close_cancels_probe` — call `close()`, verify probe task is cancelled
8. `test_config_interval` — verify `health_probe_interval_seconds` is read from config

Use `_FakeEndpoint` / `MockLLMClient` patterns consistent with existing LLM client tests. Use `asyncio.sleep(0.05)` for timing-sensitive tests, not wall-clock waits.

## What This Does NOT Change

- No changes to the dwell-time recovery logic (BF-240) — that's correct, this just ensures calls flow to trigger it
- No changes to the fallback skip logic (line 379) — the primary tier exemption is correct for request latency
- No changes to `ProactiveCognitiveLoop._update_llm_status()` — the probe is at the LLM client level, not the proactive loop level
- No changes to `LlmHealthChangedEvent` structure

## Tracking

- `PROGRESS.md`: Add BF-246 as CLOSED
- `DECISIONS.md`: No entry needed (bug fix, not architectural decision)
- `docs/development/roadmap.md`: Add BF-246 to Bug Tracker table

## Acceptance Criteria

- After extended proxy downtime, ProbOS automatically detects proxy recovery within `health_probe_interval_seconds` without requiring restart
- Healthy tiers are not probed (no unnecessary LLM calls)
- Probe is cleanly cancelled on shutdown
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`
