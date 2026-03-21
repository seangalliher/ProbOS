"""AD-382: External service behavioral profiles — learned from experience."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LatencyStats:
    """Rolling latency percentiles from recent requests."""
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    sample_count: int = 0

    def record(self, latency_ms: float) -> None:
        """Record a new latency observation.

        Uses asymmetric EMA for memory-efficient percentile approximation.
        Higher percentiles use larger up-alpha to rise faster on spikes,
        and smaller down-alpha to hold those high values longer.
        """
        self.sample_count += 1
        if self.sample_count == 1:
            self.p50_ms = latency_ms
            self.p95_ms = latency_ms
            self.p99_ms = latency_ms
            return
        # p50: symmetric EMA → converges to median
        step = 0.1
        if latency_ms > self.p50_ms:
            self.p50_ms += step * (latency_ms - self.p50_ms)
        else:
            self.p50_ms += step * (latency_ms - self.p50_ms)
        # p95: rise much faster, fall very slow → sits at high tail
        if latency_ms > self.p95_ms:
            self.p95_ms += 0.4 * (latency_ms - self.p95_ms)
        else:
            self.p95_ms += 0.005 * (latency_ms - self.p95_ms)
        # p99: rise even faster, fall even slower → sits near max
        if latency_ms > self.p99_ms:
            self.p99_ms += 0.6 * (latency_ms - self.p99_ms)
        else:
            self.p99_ms += 0.001 * (latency_ms - self.p99_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "sample_count": self.sample_count,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LatencyStats:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ServiceProfile:
    """Behavioral profile of an external service domain."""
    domain: str = ""
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
        self.total_requests += 1
        self.last_request_at = time.time()
        self.updated_at = self.last_request_at
        self.latency.record(latency_ms)

        if status_code == 429:
            self.total_rate_limits += 1
            self.last_rate_limit_at = self.last_request_at
            self.learned_min_interval = min(self.learned_min_interval * 1.5, 60.0)
        elif status_code >= 500:
            self.total_errors += 1
        elif 200 <= status_code < 300 and self.total_rate_limits > 0:
            # Successful after previous 429s — decay toward seed
            seed = _SEED_INTERVALS.get(self.domain, DEFAULT_INTERVAL)
            self.learned_min_interval = max(
                self.learned_min_interval * 0.9, seed
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "learned_min_interval": self.learned_min_interval,
            "latency": self.latency.to_dict(),
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "total_rate_limits": self.total_rate_limits,
            "last_request_at": self.last_request_at,
            "last_rate_limit_at": self.last_rate_limit_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ServiceProfile:
        latency = LatencyStats.from_dict(d["latency"]) if "latency" in d else LatencyStats()
        return cls(
            domain=d.get("domain", ""),
            learned_min_interval=d.get("learned_min_interval", 2.0),
            latency=latency,
            total_requests=d.get("total_requests", 0),
            total_errors=d.get("total_errors", 0),
            total_rate_limits=d.get("total_rate_limits", 0),
            last_request_at=d.get("last_request_at", 0.0),
            last_rate_limit_at=d.get("last_rate_limit_at", 0.0),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
        )


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
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS service_profiles ("
            "  domain TEXT PRIMARY KEY,"
            "  data TEXT NOT NULL,"
            "  updated_at REAL"
            ")"
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the SQLite connection."""
        self._conn.close()

    def get_or_create(self, domain: str) -> ServiceProfile:
        """Get existing profile or create from seed intervals."""
        row = self._conn.execute(
            "SELECT data FROM service_profiles WHERE domain = ?", (domain,)
        ).fetchone()
        if row:
            return ServiceProfile.from_dict(json.loads(row[0]))
        seed = _SEED_INTERVALS.get(domain, DEFAULT_INTERVAL)
        profile = ServiceProfile(
            domain=domain,
            learned_min_interval=seed,
        )
        self.save(profile)
        return profile

    def save(self, profile: ServiceProfile) -> None:
        """Persist profile to SQLite."""
        profile.updated_at = time.time()
        self._conn.execute(
            "INSERT OR REPLACE INTO service_profiles (domain, data, updated_at) VALUES (?, ?, ?)",
            (profile.domain, json.dumps(profile.to_dict()), profile.updated_at),
        )
        self._conn.commit()

    def all_profiles(self) -> list[ServiceProfile]:
        """Return all stored profiles, ordered by total_requests desc."""
        rows = self._conn.execute(
            "SELECT data FROM service_profiles ORDER BY updated_at DESC"
        ).fetchall()
        profiles = []
        for (data_json,) in rows:
            profiles.append(ServiceProfile.from_dict(json.loads(data_json)))
        profiles.sort(key=lambda p: p.total_requests, reverse=True)
        return profiles

    def get_interval(self, domain: str) -> float:
        """Quick lookup: return learned_min_interval for a domain.

        Returns seed interval if no profile exists (does not create one).
        """
        row = self._conn.execute(
            "SELECT data FROM service_profiles WHERE domain = ?", (domain,)
        ).fetchone()
        if row:
            data = json.loads(row[0])
            return data.get("learned_min_interval", DEFAULT_INTERVAL)
        return _SEED_INTERVALS.get(domain, DEFAULT_INTERVAL)
