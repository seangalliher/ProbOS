"""AD-633b: Speculation Cache — TTL+FIFO bounded cache for pre-computed analysis."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CacheEntry:
    signature: str
    agent_id: str
    intent_type: str
    payload: dict[str, Any]
    stored_at: float
    ttl_seconds: float

    def is_expired(self, now: float) -> bool:
        return (now - self.stored_at) >= self.ttl_seconds


class SpeculationCache:
    """AD-633b: TTL+FIFO bounded cache for speculative analysis results.

    Key: `(agent_id, intent_type, signature)` collapsed into a single string
    via the signature (which already incorporates agent_id + intent_type).
    Eviction order: TTL first, then FIFO when capacity is exceeded.
    Emits PREDICTION_HIT on lookup-hit and PREDICTION_FLUSHED on eviction.
    """

    def __init__(
        self,
        *,
        max_entries: int,
        ttl_seconds: float,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        if ttl_seconds < 1.0:
            raise ValueError("ttl_seconds must be >= 1.0")
        self._max_entries = int(max_entries)
        self._ttl = float(ttl_seconds)
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._emit = emit_event
        # Counters for AD-633e accuracy tracking introspection
        self._hits = 0
        self._misses = 0
        self._flushes = 0

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def hit_count(self) -> int:
        return self._hits

    @property
    def miss_count(self) -> int:
        return self._misses

    @property
    def flush_count(self) -> int:
        return self._flushes

    def store(
        self,
        *,
        signature: str,
        agent_id: str,
        intent_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Store a speculative result. Evicts oldest FIFO entry if at capacity."""
        now = time.time()
        # Drop expired entries opportunistically (cheap; bounded by max_entries)
        self.flush_expired()
        # FIFO eviction if still over capacity
        while len(self._entries) >= self._max_entries:
            evicted_sig, evicted = self._entries.popitem(last=False)
            self._flushes += 1
            self._emit_safe(
                "prediction_flushed",
                {
                    "signature": evicted_sig,
                    "agent_id": evicted.agent_id,
                    "intent_type": evicted.intent_type,
                    "reason": "capacity",
                },
            )
        self._entries[signature] = _CacheEntry(
            signature=signature,
            agent_id=agent_id,
            intent_type=intent_type,
            payload=payload,
            stored_at=now,
            ttl_seconds=self._ttl,
        )
        self._entries.move_to_end(signature, last=True)

    def lookup(self, signature: str) -> dict[str, Any] | None:
        """Return the cached payload or None. Hit emits PREDICTION_HIT."""
        entry = self._entries.get(signature)
        if entry is None:
            self._misses += 1
            return None
        if entry.is_expired(time.time()):
            del self._entries[signature]
            self._flushes += 1
            self._misses += 1
            self._emit_safe(
                "prediction_flushed",
                {
                    "signature": signature,
                    "agent_id": entry.agent_id,
                    "intent_type": entry.intent_type,
                    "reason": "ttl",
                },
            )
            return None
        self._hits += 1
        self._emit_safe(
            "prediction_hit",
            {
                "signature": signature,
                "agent_id": entry.agent_id,
                "intent_type": entry.intent_type,
            },
        )
        return entry.payload

    def evict(self, signature: str) -> bool:
        """Manually evict. Returns True if removed."""
        entry = self._entries.pop(signature, None)
        if entry is None:
            return False
        self._flushes += 1
        self._emit_safe(
            "prediction_flushed",
            {
                "signature": signature,
                "agent_id": entry.agent_id,
                "intent_type": entry.intent_type,
                "reason": "manual",
            },
        )
        return True

    def flush_expired(self) -> int:
        """Drop all expired entries. Returns count flushed."""
        now = time.time()
        expired = [sig for sig, e in self._entries.items() if e.is_expired(now)]
        for sig in expired:
            entry = self._entries.pop(sig)
            self._flushes += 1
            self._emit_safe(
                "prediction_flushed",
                {
                    "signature": sig,
                    "agent_id": entry.agent_id,
                    "intent_type": entry.intent_type,
                    "reason": "ttl",
                },
            )
        return len(expired)

    def _emit_safe(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._emit is None:
            return
        try:
            self._emit(event_type, payload)
        except Exception:
            logger.warning(
                "AD-633b: emit_event failed for %s; cache continues", event_type, exc_info=True
            )
