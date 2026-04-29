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

## Why This Works

BF-246 doesn't need to change the fallback skip logic (line 379). Once the health probe flips `_tier_status[fallback_tier]` back to `True` via `check_connectivity()`, line 379's `is False` check stops triggering and fallbacks resume automatically. The probe just ensures `check_connectivity()` gets called periodically — all existing recovery machinery (BF-240 dwell-time, BF-069 status transitions) handles the rest.

The first probe is deliberately delayed — `_health_probe_loop` calls `asyncio.sleep(interval)` before the first check. This avoids double-probing at startup, where `__main__.py:189` already runs an initial `check_connectivity()`.

## Fix

Add a periodic connectivity probe task that runs independently of request flow.

### Section 1: Add health probe to `OpenAICompatibleClient.__init__` and methods

**File:** `src/probos/cognitive/llm_client.py`

**Step 1a:** Add instance attributes in `__init__` (after BF-240 tracking block, around line 138):

```python
        # BF-246: Periodic health probe for recovery from extended outages
        self._health_probe_task: asyncio.Task | None = None
        self._health_probe_emit: Callable[[str, dict], None] | None = None
```

Add `Callable` to the typing imports at the top of the file if not already present:
```python
from collections.abc import Callable
```

**Step 1b:** Add `start_health_probe` method:

```python
    async def start_health_probe(
        self,
        interval_seconds: float = 30.0,
        emit_fn: Callable[[str, dict], None] | None = None,
    ) -> None:
        """BF-246: Periodic connectivity probe for recovery from extended outages.

        Runs check_connectivity() on a timer. Only probes tiers that are
        degraded/unreachable — healthy tiers are not re-checked. The first
        probe is delayed by interval_seconds to avoid double-probing at
        startup (where __main__.py already runs check_connectivity).
        """
        self._health_probe_emit = emit_fn
        self._health_probe_task = asyncio.create_task(
            self._health_probe_loop(interval_seconds),
            name="llm-health-probe",
        )
```

**Step 1c:** Add `_health_probe_loop` method:

```python
    async def _health_probe_loop(self, interval: float) -> None:
        """Background loop: probe unreachable/degraded tiers."""
        while True:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return

            # Only probe if at least one tier is not operational.
            # "recovering" tiers are also probed — they need continued
            # check_connectivity calls to complete the dwell-time sequence.
            health = self.get_health_status()
            unhealthy_tiers = [
                tier for tier, info in health["tiers"].items()
                if info["status"] != "operational"
            ]
            if not unhealthy_tiers:
                continue

            old_overall = health["overall"]
            await self.check_connectivity()
            new_health = self.get_health_status()
            new_overall = new_health["overall"]

            if old_overall != new_overall:
                logger.info(
                    "BF-246: LLM health probe detected transition: %s -> %s (probed tiers: %s)",
                    old_overall, new_overall, unhealthy_tiers,
                )
                if self._health_probe_emit is not None:
                    try:
                        self._health_probe_emit(
                            "llm_health_changed",
                            {
                                "old_status": old_overall,
                                "new_status": new_overall,
                                "source": "bf246_probe",
                            },
                        )
                    except Exception as exc:
                        logger.warning("BF-246: emit_fn raised: %s", exc)
```

Note on double-emit safety: The existing `LlmHealthChangedEvent` listeners in `_wire_anomaly_window` (finalize.py) are idempotent on status transitions — opening an already-open window returns the same ID, and closing an inactive window is a no-op. So probe-triggered emissions are safe alongside organic emissions.

**Step 1d:** Add `stop_health_probe` method:

```python
    async def stop_health_probe(self) -> None:
        """BF-246: Cancel the background health probe."""
        if self._health_probe_task and not self._health_probe_task.done():
            self._health_probe_task.cancel()
            try:
                await self._health_probe_task
            except asyncio.CancelledError:
                pass
```

**Step 1e:** Update `close()` (line 745) to cancel the probe before closing clients:

SEARCH:
```python
    async def close(self) -> None:
        """Close all httpx clients."""
        for client in self._clients.values():
            await client.aclose()
```

REPLACE:
```python
    async def close(self) -> None:
        """Close all httpx clients and cancel background tasks."""
        await self.stop_health_probe()
        for client in self._clients.values():
            await client.aclose()
```

### Section 2: Add `health_probe_interval_seconds` to config

**File:** `src/probos/config.py`
**Class:** `SystemConfig` (around line 163, next to `llm_health_min_consecutive_healthy`)

Add the field:

```python
    health_probe_interval_seconds: float = 30.0  # BF-246: Periodic LLM connectivity probe
```

Add a field_validator to reject non-positive values (prevents CPU-pinning if set to 0):

```python
    @field_validator("health_probe_interval_seconds")
    @classmethod
    def _validate_probe_interval(cls, v: float) -> float:
        if v < 5.0:
            raise ValueError("health_probe_interval_seconds must be >= 5.0 to avoid hammering a recovering proxy")
        return v
```

### Section 3: Wire the health probe at startup

**File:** `src/probos/startup/finalize.py`

In `finalize_startup()`, after the LLM client is available, start the health probe.
Use the **public** `runtime.emit_event` method (defined in `protocols.py:105`, implemented in `runtime.py:771`) — not the private `_emit_event`:

```python
    # BF-246: Start periodic LLM health probe for recovery from extended outages
    llm_client = getattr(runtime, "llm_client", None)
    if llm_client and hasattr(llm_client, "start_health_probe"):
        probe_interval = getattr(config, "health_probe_interval_seconds", 30.0)
        emit_fn = getattr(runtime, "emit_event", None)
        await llm_client.start_health_probe(
            interval_seconds=probe_interval,
            emit_fn=emit_fn,
        )
        logger.info("BF-246: LLM health probe started (interval=%.0fs)", probe_interval)
```

### Section 4: Verify shutdown cancellation

The `close()` method (updated in Section 1e) now calls `stop_health_probe()` before closing httpx clients. Verify this is sufficient by searching for all shutdown paths:

1. Search for `await llm_client.close()` in the codebase — confirm it is called during shutdown.
2. Search for `shutdown_runtime` or equivalent shutdown function — confirm the LLM client close is in the path.
3. If `close()` is not called during shutdown, add an explicit `await llm_client.stop_health_probe()` call in the shutdown function.

The test `test_close_cancels_probe` (Test 7) exercises the `close() → stop_health_probe()` path.

## Tests

**File:** `tests/test_bf246_llm_health_probe.py`

Use `pytest.mark.asyncio`. Do NOT use `freezegun` — the loop uses `asyncio.sleep`, not `time.sleep`. Use `asyncio.sleep(0.05)` for timing-sensitive tests.

Use `_FakeEndpoint` / `MockLLMClient` patterns consistent with existing LLM client tests in the test suite. Mock `check_connectivity` where needed.

9 tests:

1. `test_health_probe_starts` — start probe, verify `_health_probe_task` is created and not done
2. `test_health_probe_stops` — start then stop, verify task is cancelled/done
3. `test_health_probe_calls_connectivity` — mock `check_connectivity`, start probe with short interval (0.05s), verify it gets called within 0.15s
4. `test_health_probe_skips_when_healthy` — set all tiers operational via `_tier_status`, verify `check_connectivity` is NOT called after one interval
5. `test_health_probe_probes_when_unhealthy` — set one tier unreachable (`_tier_status["fast"] = False`), verify `check_connectivity` IS called
6. `test_health_probe_logs_transition` — mock `get_health_status` to return different overall status before/after `check_connectivity`, verify INFO log message contains "BF-246"
7. `test_close_cancels_probe` — start probe, call `close()`, verify `_health_probe_task.done()` is True
8. `test_first_probe_is_delayed` — start probe with 0.1s interval, sleep 0.05s, verify `check_connectivity` has NOT been called yet (first probe waits for full interval)
9. `test_config_validator_rejects_low_interval` — verify `SystemConfig(health_probe_interval_seconds=0)` raises `ValidationError`, and `SystemConfig(health_probe_interval_seconds=5.0)` succeeds

## What This Does NOT Change

- No changes to the dwell-time recovery logic (BF-240) — that's correct, this just ensures calls flow to trigger it
- No changes to the fallback skip logic (line 379) — the primary tier exemption is correct for request latency. Once the probe flips `_tier_status` back to `True`, fallbacks resume automatically.
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
- First probe is delayed (no double-probe at startup)
- `health_probe_interval_seconds` rejects values < 5.0
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
grep -n "async def check_connectivity" src/probos/cognitive/llm_client.py
  240:    async def check_connectivity(self) -> dict[str, bool]:

grep -n "_tier_status" src/probos/cognitive/llm_client.py
  99:        self._tier_status: dict[str, bool] = {}

grep -n "async def close" src/probos/cognitive/llm_client.py
  745:    async def close(self) -> None:

grep -n "_consecutive_successes" src/probos/cognitive/llm_client.py
  135:        self._consecutive_successes: dict[str, int] = ...

grep -n "llm_health_min_consecutive_healthy" src/probos/config.py
  163:    llm_health_min_consecutive_healthy: int = 3

grep -n "def emit_event" src/probos/runtime.py
  771:    def emit_event(self, event: BaseEvent | str, ...) -> None:

grep -n "def emit_event" src/probos/protocols.py
  105:    def emit_event(self, event: BaseEvent | str, ...) -> None: ...
```
