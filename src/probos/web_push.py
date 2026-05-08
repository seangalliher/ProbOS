"""AD-473d: Web Push subscription registry.

Lightweight in-memory store for client push subscriptions. Real Web Push
delivery (signed VAPID + httpx POST to endpoint) is the forcing function
for AD-473d-1; v1 just records subscriptions so the registry shape is
stable when delivery lands.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PushSubscription:
    """W3C PushSubscription serialization."""
    endpoint: str
    keys: dict[str, str]  # {"p256dh": ..., "auth": ...}
    subscriber_id: str = ""  # caller-supplied stable id (Captain DID, agent_id, etc.)
    created_at: float = 0.0


class PushSubscriptionRegistry:
    """In-memory registry keyed by endpoint."""

    def __init__(self) -> None:
        self._subs: dict[str, PushSubscription] = {}

    def register(self, *, endpoint: str, keys: dict[str, str], subscriber_id: str = "") -> PushSubscription:
        if not endpoint:
            raise ValueError("AD-473d: endpoint must be non-empty")
        sub = PushSubscription(
            endpoint=endpoint,
            keys=dict(keys or {}),
            subscriber_id=subscriber_id,
            created_at=time.time(),
        )
        self._subs[endpoint] = sub
        return sub

    def unregister(self, endpoint: str) -> bool:
        return self._subs.pop(endpoint, None) is not None

    def all_subscriptions(self) -> tuple[PushSubscription, ...]:
        return tuple(self._subs.values())

    def for_subscriber(self, subscriber_id: str) -> tuple[PushSubscription, ...]:
        return tuple(s for s in self._subs.values() if s.subscriber_id == subscriber_id)

    def count(self) -> int:
        return len(self._subs)
