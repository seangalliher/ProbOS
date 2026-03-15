# AD-270: Per-Domain Rate Limiter in HttpFetchAgent

## Problem

Free-tier APIs (CoinGecko, wttr.in, RSS feeds) throttle when ProbOS makes multiple requests to the same domain in quick succession. The self-mod pipeline (sandbox → deploy → auto-retry) and normal usage both route through `HttpFetchAgent` — but there's no rate awareness. Repeated 429 errors degrade the user experience.

## Design

Add a **per-domain rate limiter** to `HttpFetchAgent`. Before each HTTP request, check if the domain was recently called. If too soon, wait before retrying. Track rate limit signals from HTTP response headers (`Retry-After`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`). Display a user-visible message when waiting.

### Architecture

The rate limiter lives in `HttpFetchAgent` — the single gateway for all mesh HTTP. This means ALL agents (bundled and designed) automatically get rate limiting without any changes to their code.

### Rate limit tracking

Store per-domain state as a class-level (shared across all HttpFetchAgent instances) dict:

```python
# Class-level shared state — all pool members share rate limit knowledge
_domain_state: ClassVar[dict[str, DomainRateState]] = {}
```

Where `DomainRateState` is a simple dataclass:

```python
@dataclass
class DomainRateState:
    last_request_time: float = 0.0       # monotonic time of last request
    min_interval_seconds: float = 2.0    # minimum gap between requests (default 2s)
    retry_after: float | None = None     # from Retry-After header
    remaining: int | None = None         # from X-RateLimit-Remaining
    reset_time: float | None = None      # from X-RateLimit-Reset (monotonic)
    consecutive_429s: int = 0             # escalating backoff counter
```

### Default interval

The default `min_interval_seconds = 2.0` is a conservative baseline for free-tier APIs. Most free APIs allow 10-30 requests/minute. 2 seconds between requests = 30/minute, which fits under almost every free tier.

### Known domain overrides

Hardcode known rate limits for common free APIs that ProbOS agents use:

```python
_KNOWN_RATE_LIMITS: ClassVar[dict[str, float]] = {
    "api.coingecko.com": 3.0,      # ~10-30/min free tier, be conservative
    "wttr.in": 2.0,                # weather API
    "feeds.reuters.com": 1.0,      # RSS - generous
    "feeds.bbci.co.uk": 1.0,       # RSS - generous
    "feeds.npr.org": 1.0,          # RSS - generous
    "html.duckduckgo.com": 2.0,    # search
}
```

### Adaptive behavior from response headers

After each response, update the domain state:

1. **429 response:** Increment `consecutive_429s`. If `Retry-After` header present, use it. Otherwise, exponential backoff: `min_interval = min(2 ** consecutive_429s, 60)` seconds.
2. **`X-RateLimit-Remaining` header:** If remaining is low (≤ 2), double the interval temporarily.
3. **`X-RateLimit-Reset` header:** Parse as Unix timestamp, compute wait until reset.
4. **200 response:** Reset `consecutive_429s` to 0.

### Wait behavior

In `_fetch_url()`, before making the request:

1. Extract domain from URL via `urllib.parse.urlparse(url).netloc`
2. Look up or create `DomainRateState` for the domain
3. Compute `time_since_last = time.monotonic() - state.last_request_time`
4. If `time_since_last < state.min_interval_seconds`, sleep for the difference
5. If sleeping, log at DEBUG level: `"Rate limit courtesy delay: %.1fs for %s", delay, domain`
6. Update `state.last_request_time = time.monotonic()`

### User visibility

When the agent waits, include a note in the result. Add a `rate_limited` field to the result dict:

```python
result["data"]["rate_limit_delay"] = delay_seconds  # how long we waited (0 if no wait)
```

The auto-retry progress event in `api.py` already shows a message — no additional UI changes needed. The delay is transparent: the request just takes a bit longer, and the progress stepper shows "Executing your request..." during the wait.

## Implementation

### File: `src/probos/agents/http_fetch.py`

1. Add imports: `import time`, `import urllib.parse`, `from dataclasses import dataclass`, `from typing import ClassVar`

2. Add `DomainRateState` dataclass before the class

3. Add class-level attributes to `HttpFetchAgent`:
   - `_domain_state: ClassVar[dict[str, DomainRateState]] = {}`
   - `_KNOWN_RATE_LIMITS: ClassVar[dict[str, float]] = { ... }`

4. Add method `_get_domain_state(self, url: str) -> tuple[str, DomainRateState]`:
   - Parses domain from URL
   - Returns existing state or creates new with known rate limit override

5. Add method `async def _wait_for_rate_limit(self, domain: str, state: DomainRateState) -> float`:
   - Computes required delay
   - Sleeps if needed
   - Returns actual delay in seconds

6. Add method `_update_rate_state(self, state: DomainRateState, response: httpx.Response) -> None`:
   - Reads `Retry-After`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers
   - Updates state based on status code and headers
   - Resets `consecutive_429s` on success

7. Modify `_fetch_url()`:
   - Before the request: call `_get_domain_state()` then `_wait_for_rate_limit()`
   - After the response: call `_update_rate_state()`
   - Add `rate_limit_delay` to the result data dict
   - On 429 response: update state, then **retry once** after the computed delay

8. Add `_SAFE_HEADERS` entries for rate limit headers:
   - Add `"retry-after"`, `"x-ratelimit-remaining"`, `"x-ratelimit-reset"`, `"x-ratelimit-limit"` to the frozenset

## Tests

### File: `tests/test_expansion_agents.py` (or `tests/test_rate_limiter.py`)

Add tests to the `TestHttpFetchAgent` class (or a new class):

1. `test_domain_state_created` — fetch a URL, verify domain state exists with `last_request_time > 0`
2. `test_known_domain_interval` — verify `api.coingecko.com` gets 3.0s interval
3. `test_unknown_domain_default_interval` — verify unknown domain gets 2.0s default
4. `test_consecutive_429_backoff` — simulate two 429s, verify interval escalates
5. `test_success_resets_429_counter` — simulate 429 then 200, verify counter resets
6. `test_retry_after_header_respected` — mock response with `Retry-After: 5`, verify state updated
7. `test_rate_limit_delay_in_result` — verify `rate_limit_delay` field in successful result

Use `unittest.mock.patch` on `httpx.AsyncClient` for HTTP mocking, and `unittest.mock.patch('time.monotonic')` or `asyncio.sleep` patching for timing tests.

## PROGRESS.md

Update:
- Status line (line 3) test count
- Add AD-270 section before `## Active Roadmap`:

```
### AD-270: Per-Domain Rate Limiter in HttpFetchAgent

**Problem:** Free-tier APIs (CoinGecko, wttr.in) throttle when ProbOS makes multiple requests to the same domain in quick succession. No rate awareness in the HTTP layer caused repeated 429 errors.

| AD | Decision |
|----|----------|
| AD-270 | Per-domain rate limiter in `HttpFetchAgent` — the single gateway for all mesh HTTP. Tracks per-domain state (last request time, min interval, consecutive 429 count). Known domain overrides for common free APIs (CoinGecko: 3s, wttr.in: 2s, DuckDuckGo: 2s). Adaptive: reads `Retry-After` and `X-RateLimit-*` response headers. Exponential backoff on consecutive 429s. Default 2s interval for unknown domains. Auto-retries once on 429 after computed delay. Class-level shared state across all pool members |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/agents/http_fetch.py` | Added `DomainRateState` dataclass, `_domain_state` class-level dict, `_KNOWN_RATE_LIMITS`, `_get_domain_state()`, `_wait_for_rate_limit()`, `_update_rate_state()`. Modified `_fetch_url()` with pre-request delay + post-response state update + 429 retry. Added rate limit headers to `_SAFE_HEADERS` |

NNNN/NNNN tests passing (+ 11 skipped). N new tests.
```

## Constraints

- Only touch `src/probos/agents/http_fetch.py`, test files, and `PROGRESS.md`
- Do NOT modify `api.py`, `runtime.py`, or any UI files
- Do NOT modify bundled agents or the agent designer
- Do NOT add new config fields — the rate limiter is self-contained in HttpFetchAgent
- The `_domain_state` dict MUST be class-level (ClassVar), shared across all instances
- The default interval MUST be 2.0 seconds — conservative enough for any free API
- The 429 retry MUST be limited to ONE retry — no infinite retry loops
- Run tests after each edit: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- Report the final test count
