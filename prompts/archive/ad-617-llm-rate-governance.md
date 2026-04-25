# AD-617: LLM Rate Governance

## Context

The BF-163 DM flood incident (8,448 DMs in 90 minutes) exposed that ProbOS has **zero LLM call governance**. Agent-to-agent feedback loops generated up to 101K LLM proxy requests with no backpressure — HTTP 500 errors were literally the only rate limiter.

AD-613/614/615/616 addressed the routing/message/DB layers. AD-617 closes the remaining gap: **the LLM call layer itself.**

Current state of `src/probos/cognitive/llm_client.py` (1,312 lines):
- `BaseLLMClient` (line 19): Abstract base, `async def complete(self, request: LLMRequest) -> LLMResponse`
- `OpenAICompatibleClient` (line 41): Production client with tiered routing (fast/standard/deep), fallback chain, and health tracking (BF-069)
- `MockLLMClient` (line 512): Test mock
- `_cache` (line 123): Unbounded `dict[str, LLMResponse]` — memory leak
- No rate limiting, no 429 backoff, no token budget, no concurrency cap anywhere on the `.complete()` path
- 30+ call sites across the codebase all funnel through `.complete()`

## Dependencies

- **AD-576** (COMPLETE): LLM status state machine (`operational/degraded/offline`) in `proactive.py`. Integration point — NOT to be duplicated.
- **BF-069** (COMPLETE): Per-tier health tracking (`_consecutive_failures`, `_last_success`, `_last_failure`). Must coexist.
- **AD-616** (COMPLETE): Semaphore pattern in `startup/communication.py` — architectural template for concurrency bounding.
- **AD-488** (COMPLETE): Circuit breaker — infrastructure_degraded flag on cognitive events. Rate governance events should use this tag.

## Changes

### Part A — Token Bucket Rate Limiter (`llm_client.py`)

Add per-tier token bucket rate limiting to `OpenAICompatibleClient`.

**What to add in `__init__()` (after line 131):**

```python
# AD-617: Per-tier token bucket rate limiting
from collections import deque
self._request_timestamps: dict[str, deque[float]] = {
    t: deque() for t in ("fast", "standard", "deep")
}
```

**What to add — new method `_wait_for_rate_limit()`:**

```python
async def _wait_for_rate_limit(self, tier: str, rpm_limits: dict[str, int], max_wait: float = 30.0) -> bool:
    """AD-617: Token bucket rate limiter. Returns True if allowed, False if budget exhausted.

    Sliding window: count requests in the last 60 seconds.
    If at capacity, sleep until a slot opens (up to max_wait seconds).
    """
    import asyncio

    limit = rpm_limits.get(tier, 60)
    if limit <= 0:
        return True  # Disabled

    timestamps = self._request_timestamps[tier]
    now = time.monotonic()

    # Evict expired entries (older than 60s)
    while timestamps and now - timestamps[0] > 60.0:
        timestamps.popleft()

    if len(timestamps) < limit:
        timestamps.append(now)
        return True

    # At capacity — compute wait time
    wait_until = timestamps[0] + 60.0
    wait_seconds = wait_until - now

    if wait_seconds > max_wait:
        logger.warning(
            "LLM rate limit exceeded (tier=%s, rpm=%d, wait=%.1fs > max=%.1fs)",
            tier, limit, wait_seconds, max_wait,
        )
        return False

    logger.info(
        "LLM rate limit backpressure: waiting %.1fs (tier=%s, rpm=%d)",
        wait_seconds, tier, limit,
    )
    await asyncio.sleep(wait_seconds)
    # Re-evict and add
    now = time.monotonic()
    while timestamps and now - timestamps[0] > 60.0:
        timestamps.popleft()
    timestamps.append(now)
    return True
```

**What to modify in `complete()` (line 223):**

Add rate limit check as the first operation inside `complete()`, before the fallback tier loop (after line 230, before line 232):

```python
# AD-617: Rate limit check before dispatch
if hasattr(self, '_rate_config') and self._rate_config:
    rpm_limits = {
        "fast": self._rate_config.rpm_fast,
        "standard": self._rate_config.rpm_standard,
        "deep": self._rate_config.rpm_deep,
    }
    if not await self._wait_for_rate_limit(tier, rpm_limits, self._rate_config.max_wait_seconds):
        # Budget exhausted — try cache, then return error
        cache_key = self._cache_key(tier, request.prompt)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            return LLMResponse(
                content=cached.content, model=cached.model, tier=tier,
                tokens_used=cached.tokens_used, cached=True, request_id=request.id,
            )
        return LLMResponse(
            content="", model="", tier=tier,
            error=f"LLM rate limit exceeded for tier {tier}",
            request_id=request.id,
        )
```

### Part B — HTTP 429 Backoff (`llm_client.py`)

Currently, 429 is caught by the generic `httpx.HTTPStatusError` handler (line 285-292). Replace with specific 429 handling.

**What to modify in `complete()` — inside the `try` block, replace the `except httpx.HTTPStatusError` handler (lines 285-292) with:**

```python
except httpx.HTTPStatusError as e:
    status_code = e.response.status_code
    if status_code == 429:
        # AD-617: Specific 429 handling with exponential backoff
        retry_after = e.response.headers.get("Retry-After")
        if retry_after:
            try:
                wait = float(retry_after)
            except ValueError:
                wait = 2.0
        else:
            # Exponential backoff: track consecutive 429s per tier
            c429 = self._consecutive_429s.get(attempt_tier, 0) + 1
            self._consecutive_429s[attempt_tier] = c429
            wait = min(2 ** c429, 8.0)  # 2s, 4s, 8s, cap at 8

        logger.warning(
            "LLM endpoint returned 429 (tier=%s, wait=%.1fs, retry_after=%s)",
            attempt_tier, wait, retry_after,
        )
        await asyncio.sleep(wait)
        # Don't count 429 as a tier failure — it's temporary backpressure
        continue  # Retry same tier
    else:
        last_error = f"LLM endpoint returned HTTP {status_code}"
        logger.warning(
            "LLM endpoint returned HTTP %d (tier=%s): %s",
            status_code, attempt_tier, e.response.text[:200],
        )
        self._consecutive_failures[attempt_tier] += 1
        self._last_failure[attempt_tier] = time.monotonic()
```

**What to add in `__init__()` (after the `_request_timestamps` block from Part A):**

```python
# AD-617: Per-tier 429 consecutive counter for exponential backoff
self._consecutive_429s: dict[str, int] = {t: 0 for t in ("fast", "standard", "deep")}
```

**Reset 429 counter on success** — in the success path of `complete()` (after line 267, where `_consecutive_failures` is reset), add:

```python
self._consecutive_429s[attempt_tier] = 0  # AD-617: Reset 429 backoff
```

**Important:** Add `import asyncio` to the top of the file (after `import time`, line 8).

### Part C — LRU Cache Eviction (`llm_client.py`)

The `_cache` dict (line 123) grows unbounded. Fix: evict oldest entries when exceeding max size.

**What to modify in `__init__()` — replace line 123:**

```python
# Before:
self._cache: dict[str, LLMResponse] = {}

# After:
from collections import OrderedDict
self._cache: OrderedDict[str, LLMResponse] = OrderedDict()  # AD-617: LRU eviction
self._cache_max_entries: int = 500  # AD-617: Configurable via LLMRateConfig
```

**What to modify in `complete()` — where cache is written (around line 264-265):**

```python
# Before:
cache_key = self._cache_key(tier, request.prompt)
self._cache[cache_key] = response

# After:
cache_key = self._cache_key(tier, request.prompt)
self._cache[cache_key] = response
self._cache.move_to_end(cache_key)  # AD-617: LRU — most recent to end
# AD-617: Evict oldest if over limit
if hasattr(self, '_cache_max_entries'):
    while len(self._cache) > self._cache_max_entries:
        self._cache.popitem(last=False)
```

**Note:** The `OrderedDict` import goes at the top with the `deque` import from Part A. Consolidate into: `from collections import deque, OrderedDict`.

### Part D — Config Model (`config.py`)

Add `LLMRateConfig` Pydantic model and wire into `OpenAICompatibleClient`.

**What to add in `config.py` — new model after `CognitiveConfig` class (after line ~240):**

```python
class LLMRateConfig(BaseModel):
    """AD-617: LLM call rate governance configuration."""

    # Per-tier requests per minute (0 = disabled)
    rpm_fast: int = 60
    rpm_standard: int = 30
    rpm_deep: int = 15

    # Max seconds to wait for a rate limit slot before returning error
    max_wait_seconds: float = 30.0

    # Max LLM response cache entries (LRU eviction)
    cache_max_entries: int = 500
```

**What to add in `SystemConfig` — new field (in the `SystemConfig` class, after the existing config sections):**

```python
llm_rate: LLMRateConfig = LLMRateConfig()
```

**What to modify in `OpenAICompatibleClient.__init__()` — accept and store rate config:**

Add a new parameter to `__init__()`:

```python
def __init__(
    self,
    base_url: str = "http://127.0.0.1:8080/v1",
    api_key: str = "",
    models: dict[str, str] | None = None,
    timeout: float = 30.0,
    default_tier: str = "standard",
    config: Any = None,
    rate_config: Any = None,  # AD-617: LLMRateConfig — optional
) -> None:
```

Store it after existing init (after line 131):

```python
# AD-617: Rate governance config
self._rate_config = rate_config
if rate_config and hasattr(rate_config, 'cache_max_entries'):
    self._cache_max_entries = rate_config.cache_max_entries
```

**What to modify in `__main__.py` — wire rate config at construction (line 186):**

```python
# Before:
client = OpenAICompatibleClient(config=cog)

# After:
client = OpenAICompatibleClient(config=cog, rate_config=config.llm_rate)
```

## Deliberate Exclusions

| What | Why |
|------|-----|
| Per-agent hourly token budget | Original scope included this, but enforcement requires intercepting ALL 30+ `.complete()` call sites or adding `agent_id` to `LLMRequest`. Deferred to AD-617b as a follow-on — requires `LLMRequest` schema change + Cognitive Journal completeness work. |
| Counselor integration | Rate limit events could trigger Counselor assessment. Deferred — not required for baseline governance. |
| VitalsMonitor integration | Rate metrics in /vitals. Future work. |
| Alert condition escalation | Sustained rate limiting could raise vessel alert level. Future work. |
| Service profile learning | Adaptive RPM based on observed 429 frequency (like `ServiceProfile` for HTTP). Future optimization. |

## Files Modified

| File | What Changes |
|------|-------------|
| `src/probos/cognitive/llm_client.py` | Token bucket rate limiter, 429 backoff with retry, LRU cache eviction, rate_config parameter |
| `src/probos/config.py` | `LLMRateConfig` model, `SystemConfig.llm_rate` field |
| `src/probos/types.py` | No changes needed |
| `src/probos/__main__.py` | Wire `config.llm_rate` to client constructor (line 186) |

## Files Created

| File | What |
|------|------|
| `tests/test_ad617_llm_rate_governance.py` | New test file |

## Tests

Create `tests/test_ad617_llm_rate_governance.py` with these test classes:

### Class 1: `TestTokenBucketRateLimiter`

```python
import asyncio
import time
from collections import deque
from unittest.mock import AsyncMock, patch

import pytest

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import CognitiveConfig, LLMRateConfig
from probos.types import LLMRequest, LLMResponse


def _make_client(**kwargs) -> OpenAICompatibleClient:
    """Create a client with rate config for testing."""
    rate_config = LLMRateConfig(**kwargs)
    return OpenAICompatibleClient(config=CognitiveConfig(), rate_config=rate_config)
```

Tests:
1. `test_allows_requests_under_limit` — Send 5 requests with rpm=10. All should succeed (no wait). Verify `_request_timestamps` has 5 entries.
2. `test_blocks_when_over_limit` — Set rpm_fast=2, max_wait_seconds=0.1. Send 3 requests. Third should return rate limit error response.
3. `test_waits_when_at_capacity` — Set rpm_fast=2. Send 2 requests, manually age timestamps, send 3rd. Should succeed after brief wait.
4. `test_rate_limit_disabled_when_zero` — Set rpm_fast=0. Should allow unlimited requests.

### Class 2: `TestHTTP429Backoff`

Tests (mock `_call_api` to raise `httpx.HTTPStatusError` with 429 status):
5. `test_429_retries_same_tier` — Mock first call to return 429, second to succeed. Verify response is from the successful retry, not a tier fallback.
6. `test_429_respects_retry_after_header` — Mock 429 with `Retry-After: 1` header. Verify sleep was called with ~1.0s.
7. `test_429_exponential_backoff_without_header` — Mock multiple 429s without Retry-After. Verify `_consecutive_429s` increments and backoff grows.
8. `test_429_counter_resets_on_success` — Trigger 429s, then succeed. Verify `_consecutive_429s` resets to 0.

### Class 3: `TestLRUCacheEviction`

Tests:
9. `test_cache_evicts_oldest` — Set cache_max_entries=3. Add 4 cached responses. Verify oldest is evicted, newest 3 remain.
10. `test_cache_lru_reorder` — Access an existing cache entry. Verify it moves to end and survives eviction.
11. `test_default_cache_max` — Default config has cache_max_entries=500.

### Class 4: `TestLLMRateConfig`

Tests:
12. `test_default_values` — Verify LLMRateConfig defaults: rpm_fast=60, rpm_standard=30, rpm_deep=15, max_wait_seconds=30.0, cache_max_entries=500.
13. `test_config_in_system_config` — Verify `SystemConfig().llm_rate` returns an `LLMRateConfig` instance.

## Engineering Principles Compliance

- **Single Responsibility**: Rate governance is added to the existing `complete()` path as a pre-call gate, not a separate wrapper class. This is correct because all 30+ call sites must be governed, and `.complete()` is the single choke point.
- **Open/Closed**: New `LLMRateConfig` extends config. Existing `CognitiveConfig` fields unchanged.
- **DRY**: 429 backoff pattern follows `http_fetch.py`'s `DomainRateState` exponential backoff model.
- **Fail Fast / Log-and-Degrade**: Rate limit exceeded = log warning + return error response (callers handle gracefully). 429 = log + retry. Cache eviction = silent maintenance.
- **Defense in Depth**: Rate limiting at the LLM client level complements AD-616's event dispatch semaphore and BF-163's DM send cooldown. Three layers of flood defense.
- **Law of Demeter**: Rate config is injected via constructor parameter, not reached through nested objects.
