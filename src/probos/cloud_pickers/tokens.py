"""AD-720c: OAuth token bundle + CSRF state store.

The ``OAuthTokenBundle`` is the canonical wire shape persisted in the
AD-706f credential vault under ``cloud_provider:{provider}:{captain_id}``
(see ``BUILDER`` prompt — drafter flagged the model's home as TBD; this is
its single source of truth).
"""
from __future__ import annotations

import secrets
import threading
import time

from pydantic import BaseModel, Field


class OAuthTokenBundle(BaseModel):
    """AD-720c: OAuth token bundle persisted in the credential vault.

    Stored JSON-serialized via ``model_dump_json()``. ``refresh_token`` may be
    ``None`` for providers that don't issue one (or for the legacy bare-access
    bundles before AD-720c). ``expires_at`` is a Unix timestamp; ``0.0`` means
    "no expiry known — treat access_token as opaque and rely on 401-driven
    refresh".
    """

    access_token: str
    refresh_token: str | None = None
    expires_at: float = Field(
        default=0.0,
        description=(
            "Unix timestamp (seconds). 0.0 = no expiry known; treat "
            "access_token as opaque and refresh reactively on 401."
        ),
    )
    token_type: str = "Bearer"


# ---------------------------------------------------------------------------
# CSRF state store
# ---------------------------------------------------------------------------


class CsrfStateStore:
    """AD-720c: in-memory TTL set for OAuth ``state`` CSRF guard.

    Single-consume — ``consume()`` returns ``True`` exactly once per state
    token and removes it. Expired entries are dropped lazily on read.
    Threadsafe (RLock). Cleared on runtime shutdown.
    """

    def __init__(self, *, ttl_seconds: int = 300) -> None:
        if ttl_seconds <= 0:
            raise ValueError(
                f"AD-720c: ttl_seconds must be positive, got {ttl_seconds}"
            )
        self._ttl = float(ttl_seconds)
        self._lock = threading.RLock()
        # state -> (provider_id, expires_at)
        self._entries: dict[str, tuple[str, float]] = {}

    def add(self, state: str, provider_id: str) -> None:
        """Register a new state token. Caller must use ``mint()`` to generate it."""
        with self._lock:
            self._entries[state] = (provider_id, time.time() + self._ttl)

    def mint(self, provider_id: str) -> str:
        """Generate + register a 32-byte url-safe state token; return it."""
        token = secrets.token_urlsafe(32)
        self.add(token, provider_id)
        return token

    def consume(self, state: str, provider_id: str) -> bool:
        """Single-consume the state token, asserting provider match + freshness.

        Returns ``True`` exactly once if state was minted for ``provider_id``
        and has not expired. Removes the entry in all cases (consumed or
        invalid) to prevent replay.
        """
        with self._lock:
            entry = self._entries.pop(state, None)
            if entry is None:
                return False
            stored_provider, expires_at = entry
            if stored_provider != provider_id:
                return False
            if time.time() >= expires_at:
                return False
            return True

    def purge_expired(self) -> int:
        """Drop expired entries. Returns count removed. Called by tests + reaper."""
        with self._lock:
            now = time.time()
            stale = [k for k, (_, exp) in self._entries.items() if now >= exp]
            for k in stale:
                del self._entries[k]
            return len(stale)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
