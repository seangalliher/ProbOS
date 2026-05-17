"""AD-720c: CSRF state-store unit tests.

* TTL expiry — expired entries cannot be consumed.
* Single-consume — second consume returns False (replay protection).
"""
from __future__ import annotations

import time

from probos.cloud_pickers.tokens import CsrfStateStore


def test_state_store_single_consume_replay_protection() -> None:
    s = CsrfStateStore(ttl_seconds=60)
    state = s.mint("google_drive")
    assert s.consume(state, "google_drive") is True
    # Replay: second consume returns False.
    assert s.consume(state, "google_drive") is False


def test_state_store_provider_mismatch_rejected() -> None:
    s = CsrfStateStore(ttl_seconds=60)
    state = s.mint("google_drive")
    # Wrong provider → False AND entry consumed (prevent fishing).
    assert s.consume(state, "onedrive") is False
    assert s.consume(state, "google_drive") is False


def test_state_store_ttl_expiry() -> None:
    s = CsrfStateStore(ttl_seconds=1)
    state = s.mint("google_drive")
    # Force the entry to be expired by rewriting it with a past timestamp.
    with s._lock:  # noqa: SLF001 — test introspection
        s._entries[state] = ("google_drive", time.time() - 5)
    assert s.consume(state, "google_drive") is False
    assert len(s) == 0  # Consumed even when expired.


def test_state_store_purge_expired_removes_only_stale_entries() -> None:
    s = CsrfStateStore(ttl_seconds=60)
    fresh = s.mint("google_drive")
    stale = s.mint("google_drive")
    with s._lock:  # noqa: SLF001
        s._entries[stale] = ("google_drive", time.time() - 5)
    removed = s.purge_expired()
    assert removed == 1
    assert s.consume(fresh, "google_drive") is True
