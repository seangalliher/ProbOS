# AD-382: ServiceProfile — Learned External Service Modeling

## Goal

Replace the hardcoded `_KNOWN_RATE_LIMITS` dict in `HttpFetchAgent` with a persistent, learning-based `ServiceProfile` system. Today, rate limits are hardcoded for 6 domains and default to 2.0s for everything else. The adaptive 429-backoff learning is ephemeral — lost on restart. This AD makes external service knowledge persistent and data-driven.

## Architecture

**Pattern:** Follow the `CrewProfile` pattern (AD-376) — SQLite-backed store with dataclass models.

## Reference Files (read these first)

- `src/probos/agents/http_fetch.py` — `HttpFetchAgent` with `_KNOWN_RATE_LIMITS`, `DomainRateState`, `_update_rate_state()`
- `src/probos/crew_profile.py` — `ProfileStore` pattern (SQLite-backed, `get_or_create()`)
- `tests/test_http_fetch.py` — existing tests

## Files to Create

### `src/probos/service_profile.py` (~180 lines)

```python
"""AD-382: External service behavioral profiles — learned from experience."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LatencyStats:
    """Rolling latency percentiles from recent requests."""
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    sample_count: int = 0

    def record(self, latency_ms: float) -> None:
        """Record a new latency observation.

        Uses exponential moving average for memory-efficient percentile approximation.
        - p50: EMA with alpha=0.1
        - p95: EMA with alpha=0.05, only updates when value > current p95
        - p99: EMA with alpha=0.02, only updates when value > current p99
        """
        ...

    def to_dict(self) -> dict: ...

    @classmethod
    def from_dict(cls, d: dict) -> LatencyStats: ...


@dataclass
class ServiceProfile:
    """Behavioral profile of an external service domain."""
    domain: str
    learned_min_interval: float = 2.0  # seconds between requests
    latency: LatencyStats = field(default_factory=LatencyStats)
    total_requests: int = 0
    total_errors: int = 0  # non-429 errors (5xx, timeouts, connection errors)
    total_rate_limits: int = 0  # 429 responses
    last_request_at: float = 0.0
    last_rate_limit_at: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def error_rate(self) -> float:
        """Fraction of requests that resulted in errors (0.0-1.0)."""
        if self.total_requests == 0:
            return 0.0
        return (self.total_errors + self.total_rate_limits) / self.total_requests

    @property
    def reliability(self) -> float:
        """1.0 - error_rate. Higher is better."""
        return 1.0 - self.error_rate

    def record_request(self, latency_ms: float, status_code: int) -> None:
        """Record a completed request.

        Updates latency stats, request count, error/rate-limit counters.
        On 429: increment total_rate_limits, increase learned_min_interval by 50%
            (capped at 60.0s), set last_rate_limit_at.
        On 5xx: increment total_errors.
        On 2xx after previous 429s: decay learned_min_interval toward seed value
            (multiply by 0.9, floor at seed interval from _SEED_INTERVALS).
        """
        ...

    def to_dict(self) -> dict: ...

    @classmethod
    def from_dict(cls, d: dict) -> ServiceProfile: ...


# Seed intervals — the initial defaults, replacing _KNOWN_RATE_LIMITS
_SEED_INTERVALS: dict[str, float] = {
    "api.coingecko.com": 3.0,
    "wttr.in": 2.0,
    "feeds.reuters.com": 1.0,
    "feeds.bbci.co.uk": 1.0,
    "feeds.npr.org": 1.0,
    "html.duckduckgo.com": 2.0,
}
DEFAULT_INTERVAL = 2.0


class ServiceProfileStore:
    """SQLite-backed persistent store for service profiles."""

    def __init__(self, db_path: Path | str = "data/service_profiles.db") -> None:
        ...  # Create table: domain TEXT PRIMARY KEY, data TEXT, updated_at REAL

    def get_or_create(self, domain: str) -> ServiceProfile:
        """Get existing profile or create from seed intervals."""
        ...

    def save(self, profile: ServiceProfile) -> None:
        """Persist profile to SQLite."""
        ...

    def all_profiles(self) -> list[ServiceProfile]:
        """Return all stored profiles, ordered by total_requests desc."""
        ...

    def get_interval(self, domain: str) -> float:
        """Quick lookup: return learned_min_interval for a domain.

        Returns seed interval if no profile exists (does not create one).
        """
        ...
```

## Files to Modify

### `src/probos/agents/http_fetch.py`

1. Remove `_KNOWN_RATE_LIMITS` class variable
2. Add `_profile_store: ServiceProfileStore | None` class variable (default `None`)
3. Add `@classmethod set_profile_store(cls, store: ServiceProfileStore)` method
4. In `_get_or_create_rate_state()` (or equivalent): instead of `_KNOWN_RATE_LIMITS.get(domain, 2.0)`, call `cls._profile_store.get_interval(domain)` if store is available, else fall back to `DEFAULT_INTERVAL`
5. After each request completes (in `_update_rate_state()`): if `_profile_store` is available, call `profile.record_request(latency_ms, status_code)` and `_profile_store.save(profile)`
6. Keep all existing ephemeral `DomainRateState` logic — the profile is the long-term memory, the rate state is the short-term reflex

### `src/probos/runtime.py`

1. Import `ServiceProfileStore`
2. Add `self.service_profiles: ServiceProfileStore | None = None` in `__init__()`
3. In `start()`: `self.service_profiles = ServiceProfileStore()` and `HttpFetchAgent.set_profile_store(self.service_profiles)`
4. In `stop()`: `HttpFetchAgent.set_profile_store(None)` — clean disconnection

## Tests

### Create `tests/test_service_profile.py` (~150 lines)

1. **`test_latency_stats_record`** — Record 10 latencies, verify p50/p95/p99 are reasonable
2. **`test_latency_stats_roundtrip`** — `to_dict()` → `from_dict()` preserves all fields
3. **`test_service_profile_defaults`** — New profile has error_rate=0.0, reliability=1.0
4. **`test_record_request_success`** — Record 2xx, verify total_requests incremented, no error
5. **`test_record_request_429`** — Record 429, verify total_rate_limits incremented, learned_min_interval increased by 50%
6. **`test_record_request_429_cap`** — Multiple 429s, cap at 60.0s
7. **`test_record_request_recovery`** — 429 then 2xx, verify interval decays toward seed
8. **`test_record_request_5xx`** — Record 500, verify total_errors incremented
9. **`test_error_rate_calculation`** — 8 success + 2 errors = 0.2 error_rate, 0.8 reliability
10. **`test_store_get_or_create_seed`** — Unknown domain → profile with DEFAULT_INTERVAL
11. **`test_store_get_or_create_known`** — Known domain (e.g., "api.coingecko.com") → seed interval 3.0
12. **`test_store_save_and_reload`** — Save profile, create new store from same db, verify data persists
13. **`test_store_all_profiles`** — Create 3 profiles with different request counts, verify ordered by total_requests desc
14. **`test_get_interval_no_profile`** — `get_interval()` returns seed or default without creating a profile

## Constraints

- No new dependencies — SQLite is stdlib
- `ServiceProfileStore` uses `:memory:` SQLite in tests (pass `db_path=":memory:"`)
- Backward compatible — if `_profile_store` is None, behavior is identical to current hardcoded defaults
- Do not change HttpFetchAgent's public API or intent descriptors
