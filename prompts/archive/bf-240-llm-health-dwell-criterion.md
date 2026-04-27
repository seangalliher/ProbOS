# BF-240: LLM Health Dwell-Time Criterion

**Status:** Ready for builder
**Issue:** #344
**Scope:** OSS (`src/probos/cognitive/llm_client.py`, `src/probos/config.py`, `src/probos/events.py`, `src/probos/proactive.py`, `tests/test_bf069_llm_health.py`)

## Context

`OpenAICompatibleClient` (in `src/probos/cognitive/llm_client.py`) resets `_consecutive_failures[tier]` to 0 on the **first** successful response (line 401) or connectivity check (line 253). This triggers immediate recovery — `get_health_status()` reports "operational" after one good response, even if the tier was bouncing between failures. Forge (Engineering) submitted 2 improvement proposals identifying this: a single healthy check amid instability shouldn't release the diagnostic hold.

**Fix:** Track consecutive healthy responses per tier. Only transition from degraded/unreachable to operational after `min_consecutive_healthy` (default 3) successive healthy checks.

## Implementation

### 1. Add config field to `CognitiveConfig` in `src/probos/config.py`

Add to the `CognitiveConfig` class (around line 148), after the existing LLM configuration fields. Add a Pydantic validator to enforce `>= 1`.

First, update the pydantic import (line 9):

```python
SEARCH:
from pydantic import BaseModel

REPLACE:
from pydantic import BaseModel, field_validator
```

Then add the field and validator:

```python
SEARCH:
    llm_model_deep: str = "claude-sonnet-4"

REPLACE:
    llm_model_deep: str = "claude-sonnet-4"

    # BF-240: Dwell-time criterion for LLM health recovery
    llm_health_min_consecutive_healthy: int = 3  # Consecutive successes before tier transitions to operational

    @field_validator("llm_health_min_consecutive_healthy")
    @classmethod
    def _validate_min_consecutive_healthy(cls, v: int) -> int:
        if v < 1:
            raise ValueError("llm_health_min_consecutive_healthy must be >= 1")
        return v
```

### 2. Add recovery tracking state to `OpenAICompatibleClient.__init__()` in `src/probos/cognitive/llm_client.py`

After the existing health tracking fields (lines 129-132):

```python
SEARCH:
        # BF-069: Per-tier failure tracking for health monitoring
        self._consecutive_failures: dict[str, int] = {t: 0 for t in ("fast", "standard", "deep")}
        self._last_success: dict[str, float] = {}  # tier -> monotonic timestamp
        self._last_failure: dict[str, float] = {}  # tier -> monotonic timestamp

        # Ollama keep_alive to prevent model unloading during idle periods

REPLACE:
        # BF-069: Per-tier failure tracking for health monitoring
        self._consecutive_failures: dict[str, int] = {t: 0 for t in ("fast", "standard", "deep")}
        self._last_success: dict[str, float] = {}  # tier -> monotonic timestamp
        self._last_failure: dict[str, float] = {}  # tier -> monotonic timestamp

        # BF-240: Dwell-time recovery tracking
        self._consecutive_successes: dict[str, int] = {t: 0 for t in ("fast", "standard", "deep")}
        self._min_consecutive_healthy: int = getattr(
            self._config, "llm_health_min_consecutive_healthy", 3
        )

        # Ollama keep_alive to prevent model unloading during idle periods
```

**Config flow:** `self._config` is always a `CognitiveConfig` instance — either injected via constructor or built inline in `__init__()` (line 81). No finalize wiring needed. The `getattr` with default handles any legacy configs missing the field.

### 3. Modify success handling — track consecutive successes

**In the completion success path (lines 401-410).** Replace the immediate failure counter reset with dwell-time logic. The `model` variable is in scope (resolved at line 339 in the retry loop).

```python
SEARCH:
                    # BF-069: Reset failure counter on successful completion
                    prev_failures = self._consecutive_failures[attempt_tier]
                    self._consecutive_failures[attempt_tier] = 0
                    self._consecutive_429s[attempt_tier] = 0  # AD-617: Reset 429 backoff
                    self._last_success[attempt_tier] = time.monotonic()
                    if prev_failures > 0:
                        logger.info(
                            "LLM tier %s recovered after %d consecutive failures (model=%s)",
                            attempt_tier, prev_failures, model,
                        )
                    if attempt_tier != tier:

REPLACE:
                    # BF-240: Dwell-time recovery — track consecutive successes
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
                    if attempt_tier != tier:
```

**In the connectivity check success path (lines 253-256):**

```python
SEARCH:
            # BF-069: Reset failure counter on successful connectivity check
            if results[tier]:
                self._consecutive_failures[tier] = 0
                self._last_success[tier] = time.monotonic()

        return results

REPLACE:
            # BF-240: Dwell-time recovery for connectivity checks
            if results[tier]:
                self._consecutive_successes[tier] += 1
                self._last_success[tier] = time.monotonic()
                if self._consecutive_successes[tier] >= self._min_consecutive_healthy:
                    self._consecutive_failures[tier] = 0

        return results
```

### 4. Reset consecutive successes on failure

In **every** failure handler, add `self._consecutive_successes[attempt_tier] = 0` after the existing `self._consecutive_failures[attempt_tier] += 1` line. There are four sites:

**ConnectError handler (line 419):**

```python
SEARCH:
                except httpx.ConnectError:
                    last_error = f"LLM endpoint unreachable at {tc['base_url']}"
                    self._consecutive_failures[attempt_tier] += 1
                    self._last_failure[attempt_tier] = time.monotonic()

REPLACE:
                except httpx.ConnectError:
                    last_error = f"LLM endpoint unreachable at {tc['base_url']}"
                    self._consecutive_failures[attempt_tier] += 1
                    self._consecutive_successes[attempt_tier] = 0  # BF-240: Reset dwell counter
                    self._last_failure[attempt_tier] = time.monotonic()
```

**TimeoutException handler (line 430):**

```python
SEARCH:
                except httpx.TimeoutException:
                    last_error = f"LLM request timed out after {tc['timeout']:.0f}s"
                    self._consecutive_failures[attempt_tier] += 1
                    self._last_failure[attempt_tier] = time.monotonic()

REPLACE:
                except httpx.TimeoutException:
                    last_error = f"LLM request timed out after {tc['timeout']:.0f}s"
                    self._consecutive_failures[attempt_tier] += 1
                    self._consecutive_successes[attempt_tier] = 0  # BF-240: Reset dwell counter
                    self._last_failure[attempt_tier] = time.monotonic()
```

**HTTPStatusError handler (non-429, line 464):**

```python
SEARCH:
                    else:
                        last_error = f"LLM endpoint returned HTTP {status_code}"
                        self._consecutive_failures[attempt_tier] += 1
                        self._last_failure[attempt_tier] = time.monotonic()

REPLACE:
                    else:
                        last_error = f"LLM endpoint returned HTTP {status_code}"
                        self._consecutive_failures[attempt_tier] += 1
                        self._consecutive_successes[attempt_tier] = 0  # BF-240: Reset dwell counter
                        self._last_failure[attempt_tier] = time.monotonic()
```

**Generic Exception handler (line 476):**

```python
SEARCH:
                except Exception as e:
                    last_error = f"{type(e).__name__}: {e}"
                    self._consecutive_failures[attempt_tier] += 1
                    self._last_failure[attempt_tier] = time.monotonic()

REPLACE:
                except Exception as e:
                    last_error = f"{type(e).__name__}: {e}"
                    self._consecutive_failures[attempt_tier] += 1
                    self._consecutive_successes[attempt_tier] = 0  # BF-240: Reset dwell counter
                    self._last_failure[attempt_tier] = time.monotonic()
```

### 5. Add "recovering" status to `get_health_status()`

Replace the per-tier status logic and overall status logic in `get_health_status()` (line 655):

```python
SEARCH:
        tiers: dict[str, dict[str, Any]] = {}
        for tier in ("fast", "standard", "deep"):
            failures = self._consecutive_failures.get(tier, 0)
            if failures == 0:
                status = "operational"
            elif failures < self._UNREACHABLE_THRESHOLD:
                status = "degraded"
                logger.info(
                    "LLM tier %s degraded: %d consecutive failures (threshold=%d)",
                    tier, failures, self._UNREACHABLE_THRESHOLD,
                )
            else:
                status = "unreachable"
                logger.warning(
                    "LLM tier %s unreachable: %d consecutive failures (threshold=%d), "
                    "last_success=%.1fs ago, last_failure=%.1fs ago",
                    tier, failures, self._UNREACHABLE_THRESHOLD,
                    time.monotonic() - self._last_success.get(tier, 0) if self._last_success.get(tier) else -1,
                    time.monotonic() - self._last_failure.get(tier, 0) if self._last_failure.get(tier) else -1,
                )
            tiers[tier] = {
                "status": status,
                "consecutive_failures": failures,
                "last_success": self._last_success.get(tier),
                "last_failure": self._last_failure.get(tier),
            }

        statuses = [t["status"] for t in tiers.values()]
        if all(s == "operational" for s in statuses):
            overall = "operational"
        elif all(s == "unreachable" for s in statuses):
            overall = "offline"
        else:
            overall = "degraded"

REPLACE:
        tiers: dict[str, dict[str, Any]] = {}
        for tier in ("fast", "standard", "deep"):
            failures = self._consecutive_failures.get(tier, 0)
            successes = self._consecutive_successes.get(tier, 0)
            if failures == 0:
                status = "operational"
            elif failures < self._UNREACHABLE_THRESHOLD:
                if successes > 0:
                    status = "recovering"  # BF-240: Has recent successes but hasn't met dwell threshold
                else:
                    status = "degraded"
                    # Note: only log when not recovering — a tier that flips
                    # degraded→recovering→degraded won't re-log. This is intentional:
                    # the recovering→degraded transition means successes reset, so the
                    # original degraded log from when failures first crossed threshold
                    # is still the relevant diagnostic entry.
                    logger.info(
                        "LLM tier %s degraded: %d consecutive failures (threshold=%d)",
                        tier, failures, self._UNREACHABLE_THRESHOLD,
                    )
            else:
                if successes > 0:
                    status = "recovering"  # BF-240: Unreachable but accumulating healthy checks
                else:
                    status = "unreachable"
                    logger.warning(
                        "LLM tier %s unreachable: %d consecutive failures (threshold=%d), "
                        "last_success=%.1fs ago, last_failure=%.1fs ago",
                        tier, failures, self._UNREACHABLE_THRESHOLD,
                        time.monotonic() - self._last_success.get(tier, 0) if self._last_success.get(tier) else -1,
                        time.monotonic() - self._last_failure.get(tier, 0) if self._last_failure.get(tier) else -1,
                    )
            tiers[tier] = {
                "status": status,
                "consecutive_failures": failures,
                "consecutive_successes": successes,  # BF-240
                "last_success": self._last_success.get(tier),
                "last_failure": self._last_failure.get(tier),
            }

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

Add `consecutive_successes` field. Existing subscribers (e.g., `proactive.py:3434`) will see the default `0`, which is safe — no subscriber behavior changes.

```python
SEARCH:
@dataclass
class LlmHealthChangedEvent(BaseEvent):
    """AD-576: Emitted on LLM backend status transitions."""
    event_type: EventType = field(default=EventType.LLM_HEALTH_CHANGED, init=False)
    old_status: str = ""       # "operational", "degraded", "offline"
    new_status: str = ""       # "operational", "degraded", "offline"
    consecutive_failures: int = 0
    downtime_seconds: float = 0.0  # Time since first failure (0 on recovery)

REPLACE:
@dataclass
class LlmHealthChangedEvent(BaseEvent):
    """AD-576: Emitted on LLM backend status transitions."""
    event_type: EventType = field(default=EventType.LLM_HEALTH_CHANGED, init=False)
    old_status: str = ""       # "operational", "degraded", "offline", "recovering"
    new_status: str = ""       # "operational", "degraded", "offline", "recovering"
    consecutive_failures: int = 0
    consecutive_successes: int = 0  # BF-240: Dwell count at transition time
    downtime_seconds: float = 0.0  # Time since first failure (0 on recovery)
```

### 7. Pass `consecutive_successes` at event emission site in `src/probos/proactive.py`

The `LlmHealthChangedEvent` is emitted in `ProactiveAgent._update_llm_status()` around line 3437. The proactive agent maintains its **own** failure tracking (`_llm_failure_count` with BF-228 decay) separate from `llm_client.py`'s `_consecutive_failures`. To populate `consecutive_successes`, query `self._llm_client.get_health_status()` which now includes `consecutive_successes` per tier (from Section 5).

```python
SEARCH:
        # Emit typed event on transition
        if self._on_event:
            from probos.events import LlmHealthChangedEvent
            downtime = (time.monotonic() - self._llm_offline_since) if self._llm_offline_since else 0.0
            try:
                event = LlmHealthChangedEvent(
                    old_status=old_status,
                    new_status=new_status,
                    consecutive_failures=self._llm_failure_count,
                    downtime_seconds=downtime if new_status == "operational" else 0.0,
                )

REPLACE:
        # Emit typed event on transition
        if self._on_event:
            from probos.events import LlmHealthChangedEvent
            downtime = (time.monotonic() - self._llm_offline_since) if self._llm_offline_since else 0.0
            # BF-240: Get max consecutive_successes across tiers from the LLM client
            cs = 0
            if hasattr(self, "_llm_client") and self._llm_client:
                try:
                    health = self._llm_client.get_health_status()
                    cs = max(
                        t.get("consecutive_successes", 0)
                        for t in health.get("tiers", {}).values()
                    ) if health.get("tiers") else 0
                except Exception:
                    pass  # Log-and-degrade: event still emits with cs=0
            try:
                event = LlmHealthChangedEvent(
                    old_status=old_status,
                    new_status=new_status,
                    consecutive_failures=self._llm_failure_count,
                    consecutive_successes=cs,  # BF-240
                    downtime_seconds=downtime if new_status == "operational" else 0.0,
                )
```

### 8. Tests — `tests/test_bf069_llm_health.py`

Add a new test class `TestDwellTimeCriterion` after the existing test classes. Follow the existing `_make_client()` pattern from `TestLLMClientHealthTracking`:

```python
def _make_client(self):
    """Create a minimal OpenAICompatibleClient for testing."""
    from probos.cognitive.llm_client import OpenAICompatibleClient
    client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
    client._consecutive_failures = {t: 0 for t in ("fast", "standard", "deep")}
    client._consecutive_successes = {t: 0 for t in ("fast", "standard", "deep")}  # BF-240
    client._min_consecutive_healthy = 3  # BF-240
    client._last_success = {}
    client._last_failure = {}
    return client
```

**Also update the existing `TestLLMClientHealthTracking._make_client()`** to include the new fields, so existing tests don't break:

```python
    client._consecutive_successes = {t: 0 for t in ("fast", "standard", "deep")}
    client._min_consecutive_healthy = 3
```

Tests (10 total):

1. **`test_single_success_does_not_clear_failures`** — After 3 failures, 1 success → `consecutive_failures` still > 0, status != "operational"
2. **`test_dwell_threshold_clears_failures`** — After 3 failures, 3 consecutive successes → `consecutive_failures` == 0, status == "operational"
3. **`test_failure_resets_success_counter`** — After 3 failures, 2 successes, 1 failure → consecutive_successes reset to 0
4. **`test_recovering_status_exposed`** — After failures, partial successes → per-tier status is "recovering"
5. **`test_connectivity_check_dwell`** — `check_connectivity()` also respects dwell threshold. This test is `async def` with `@pytest.mark.asyncio`. Mock `self._check_endpoint` (returns `True`/`False`) via `AsyncMock` — no real httpx needed. Set up tier configs via `client._tier_configs` with dummy URLs, and `client._tier_status = {}`. Call `await client.check_connectivity()` and verify `_consecutive_successes` increments but `_consecutive_failures` doesn't clear until threshold met
6. **`test_overall_status_recovering`** — One tier recovering → overall "recovering"
7. **`test_config_overrides_default`** — `llm_health_min_consecutive_healthy=5` → requires 5 successes
8. **`test_consecutive_successes_in_health_dict`** — `get_health_status()` includes `consecutive_successes` field
9. **`test_zero_failures_no_dwell_needed`** — Tier with 0 failures → success keeps operational. The dwell logic only gates recovery (prev_failures > 0). When failures == 0, there's nothing to gate — `get_health_status()` returns "operational" based on `failures == 0` check, regardless of consecutive_successes count. No special handling needed in Section 3.
10. **`test_event_includes_dwell_count`** — `LlmHealthChangedEvent` includes `consecutive_successes` at transition time

Use `pytest.mark.asyncio` for any async tests (test 5). Use `unittest.mock.AsyncMock` for httpx client mocking. Follow existing patterns in the file — no new base classes or fixtures needed.

## Files Changed

| File | Change |
|------|--------|
| `src/probos/cognitive/llm_client.py` | `_consecutive_successes` tracking, dwell-gated recovery, "recovering" status |
| `src/probos/config.py` | `llm_health_min_consecutive_healthy` field + validator in `CognitiveConfig` |
| `src/probos/events.py` | `consecutive_successes` field on `LlmHealthChangedEvent` |
| `src/probos/proactive.py` | Pass `consecutive_successes` at event emission site |
| `tests/test_bf069_llm_health.py` | 10 new tests in `TestDwellTimeCriterion`, update existing `_make_client()` |

## Tracker Updates

- `PROGRESS.md` — Update BF-240 from OPEN to CLOSED
- `docs/development/roadmap.md` — Update BF-240 status to Closed
