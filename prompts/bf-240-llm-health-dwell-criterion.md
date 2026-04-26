# BF-240: LLM Health Dwell-Time Criterion

**Status:** Ready for builder
**Issue:** #344
**Scope:** OSS (`src/probos/cognitive/llm_client.py`, `src/probos/config.py`, `src/probos/events.py`, `tests/test_bf069_llm_health.py`)

## Context

`OpenAICompatibleClient` (in `src/probos/cognitive/llm_client.py`) resets `_consecutive_failures[tier]` to 0 on the **first** successful response (line 401) or connectivity check (line 253). This triggers immediate recovery — `get_health_status()` reports "operational" after one good response, even if the tier was bouncing between failures. Forge (Engineering) submitted 2 improvement proposals identifying this: a single healthy check amid instability shouldn't release the diagnostic hold.

**Fix:** Track consecutive healthy responses per tier. Only transition from degraded/unreachable to operational after `min_consecutive_healthy` (default 3) successive healthy checks.

## Implementation

### 1. Add config field to `CognitiveConfig` in `src/probos/config.py`

Add to the `CognitiveConfig` class (around line 148), in the LLM configuration section:

```python
    # BF-240: Dwell-time criterion for LLM health recovery
    llm_health_min_consecutive_healthy: int = 3  # Consecutive successes before tier transitions to operational
```

### 2. Add recovery tracking state to `OpenAICompatibleClient.__init__()` in `src/probos/cognitive/llm_client.py`

After the existing health tracking fields (lines 129-132), add:

```python
        # BF-240: Dwell-time recovery tracking
        self._consecutive_successes: dict[str, int] = {t: 0 for t in ("fast", "standard", "deep")}
        self._min_consecutive_healthy: int = 3  # default, overridden from config below
```

In the config initialization block (where `self._config` is set, around line 135), read the threshold:

```python
        if self._config and hasattr(self._config, "llm_health_min_consecutive_healthy"):
            self._min_consecutive_healthy = self._config.llm_health_min_consecutive_healthy
```

### 3. Modify success handling — track consecutive successes

**In the completion success path (line 401-410):** Replace the immediate failure counter reset with dwell-time logic:

```python
                prev_failures = self._consecutive_failures[attempt_tier]
                self._consecutive_successes[attempt_tier] += 1
                self._last_success[attempt_tier] = time.monotonic()
                self._consecutive_429s[attempt_tier] = 0  # AD-617: Reset 429 backoff

                if self._consecutive_successes[attempt_tier] >= self._min_consecutive_healthy:
                    self._consecutive_failures[attempt_tier] = 0
                    if prev_failures > 0:
                        logger.info(
                            "LLM tier %s recovered after %d consecutive failures "
                            "(dwell: %d consecutive healthy, threshold: %d, model=%s)",
                            attempt_tier, prev_failures,
                            self._consecutive_successes[attempt_tier],
                            self._min_consecutive_healthy, model,
                        )
                elif prev_failures > 0:
                    logger.debug(
                        "LLM tier %s healthy check %d/%d (model=%s)",
                        attempt_tier,
                        self._consecutive_successes[attempt_tier],
                        self._min_consecutive_healthy, model,
                    )
```

**In the connectivity check success path (line 253-256):** Same pattern:

```python
                if results[tier]:
                    self._consecutive_successes[tier] += 1
                    self._last_success[tier] = time.monotonic()
                    if self._consecutive_successes[tier] >= self._min_consecutive_healthy:
                        self._consecutive_failures[tier] = 0
```

### 4. Reset consecutive successes on failure

In **every** failure handler (ConnectError line 419, TimeoutException line 430, HTTPStatusError line 464, generic Exception line 476), add after the existing `self._consecutive_failures[attempt_tier] += 1` line:

```python
                    self._consecutive_successes[attempt_tier] = 0  # BF-240: Reset dwell counter
```

### 5. Add "recovering" status to `get_health_status()`

In `get_health_status()` (line 655), update the per-tier status logic to include a new state:

```python
            if failures == 0:
                status = "operational"
            elif failures < self._UNREACHABLE_THRESHOLD:
                if self._consecutive_successes[tier] > 0:
                    status = "recovering"  # BF-240: Has recent successes but hasn't met dwell threshold
                else:
                    status = "degraded"
            else:
                if self._consecutive_successes[tier] > 0:
                    status = "recovering"  # BF-240: Unreachable but accumulating healthy checks
                else:
                    status = "unreachable"
```

Add `consecutive_successes` to the per-tier return dict:

```python
            tiers[tier] = {
                "status": status,
                "consecutive_failures": failures,
                "consecutive_successes": self._consecutive_successes[tier],  # BF-240
                "last_success": self._last_success.get(tier),
                "last_failure": self._last_failure.get(tier),
            }
```

Update overall status logic to treat "recovering" as non-operational:

```python
        statuses = [t["status"] for t in tiers.values()]
        if all(s == "operational" for s in statuses):
            overall = "operational"
        elif all(s in ("unreachable", "offline") for s in statuses):
            overall = "offline"
        elif any(s == "recovering" for s in statuses):
            overall = "recovering"  # BF-240
        else:
            overall = "degraded"
```

### 6. Update `LlmHealthChangedEvent` in `src/probos/events.py`

Add `consecutive_successes` field to `LlmHealthChangedEvent` (around line 584):

```python
    consecutive_successes: int = 0  # BF-240: Dwell count at transition time
```

### 7. Tests — `tests/test_bf069_llm_health.py`

Add a new test class `TestDwellTimeCriterion` after the existing test classes. Tests:

1. **`test_single_success_does_not_clear_failures`** — After 3 failures, 1 success → `consecutive_failures` still > 0, status != "operational"
2. **`test_dwell_threshold_clears_failures`** — After 3 failures, 3 consecutive successes → `consecutive_failures` == 0, status == "operational"
3. **`test_failure_resets_success_counter`** — After 3 failures, 2 successes, 1 failure → consecutive_successes reset to 0
4. **`test_recovering_status_exposed`** — After failures, partial successes → per-tier status is "recovering"
5. **`test_connectivity_check_dwell`** — `check_connectivity()` also respects dwell threshold
6. **`test_overall_status_recovering`** — One tier recovering → overall "recovering"
7. **`test_config_overrides_default`** — `llm_health_min_consecutive_healthy=5` → requires 5 successes
8. **`test_consecutive_successes_in_health_dict`** — `get_health_status()` includes `consecutive_successes` field
9. **`test_zero_failures_no_dwell_needed`** — Tier with 0 failures → success immediately keeps it operational (no unnecessary gating)
10. **`test_event_includes_dwell_count`** — `LlmHealthChangedEvent` includes `consecutive_successes` at transition time

Use existing test patterns from the file. Mock `httpx.AsyncClient` for request simulation. Use `pytest.mark.asyncio` for async tests.

## Files Changed

| File | Change |
|------|--------|
| `src/probos/cognitive/llm_client.py` | `_consecutive_successes` tracking, dwell-gated recovery, "recovering" status |
| `src/probos/config.py` | `llm_health_min_consecutive_healthy` field in `CognitiveConfig` |
| `src/probos/events.py` | `consecutive_successes` field on `LlmHealthChangedEvent` |
| `tests/test_bf069_llm_health.py` | 10 new tests in `TestDwellTimeCriterion` |

## Tracker Updates

- `PROGRESS.md` — Update BF-240 from OPEN to CLOSED
- `docs/development/roadmap.md` — Update BF-240 status to Closed
