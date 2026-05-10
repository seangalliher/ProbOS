"""AD-722b: per-agent WebSocket connection registry for avatar telemetry.

Tracks active subscribers per agent for fan-out and max-connection
enforcement. Single-process; no cross-process sharing. Pairs with
``runtime.avatar_sampling_state`` (popout-tier flip on register/unregister)
and ``runtime.avatar_event_bus`` (subscriber wake on trigger).
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger(__name__)


class MaxConnectionsExceeded(Exception):
    """Raised by ``register`` when the per-agent cap is reached."""


class AvatarTelemetryConnectionManager:
    """Per-agent WebSocket registry. Each connection is given a stable
    UUID; the UUID is the handle the WS handler uses to deregister.

    The manager does NOT broadcast frames itself — each connection's
    publish loop owns its own send. The manager exists for:

      1. Max-connections-per-agent enforcement (config-driven cap).
      2. Test-time introspection (``connections_for(agent_id)``).
      3. Future fan-out helpers (forward marker AD-722b-4 multi-agent).
    """

    def __init__(self, max_per_agent: int) -> None:
        if max_per_agent < 1:
            raise ValueError(
                f"max_per_agent must be >= 1, got {max_per_agent}"
            )
        self._max_per_agent = int(max_per_agent)
        # agent_id -> {connection_id: WebSocket}
        self._connections: dict[str, dict[str, "WebSocket"]] = {}

    def register(self, agent_id: str, websocket: "WebSocket") -> str:
        """Allocate a connection_id and register the WS. Raises
        ``MaxConnectionsExceeded`` if the cap is hit.
        """
        bucket = self._connections.setdefault(agent_id, {})
        if len(bucket) >= self._max_per_agent:
            raise MaxConnectionsExceeded(
                f"agent={agent_id} already has {len(bucket)} connections "
                f"(max={self._max_per_agent})"
            )
        connection_id = str(uuid.uuid4())
        bucket[connection_id] = websocket
        return connection_id

    def deregister(self, agent_id: str, connection_id: str) -> None:
        """Tier-2: silent on missing keys (idempotent close paths)."""
        bucket = self._connections.get(agent_id)
        if bucket is None:
            return
        bucket.pop(connection_id, None)
        if not bucket:
            self._connections.pop(agent_id, None)

    def connections_for(self, agent_id: str) -> int:
        return len(self._connections.get(agent_id, ()))

    @property
    def max_per_agent(self) -> int:
        return self._max_per_agent
