"""AD-479g: FederationClusterMonitor — gossip-driven peer liveness flag.

Polls ``bridge._router._peer_models`` every ``gossip_interval_seconds * 3``
and flips peers to unreachable when ``last_gossip_at`` is older than
``peer_unreachable_seconds``. Auto-recovery is just gossip arriving again.

Process-level auto-restart and graceful handoff are satisfied at the
AD-637e + AD-637c layer (NATS reconnection + JetStream durable consumers
replaying un-ack'd messages on disconnect); v1 does NOT add a process
supervisor — that surface belongs in deployment tooling, not federation
runtime.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class FederationClusterMonitor:
    """Polls peer gossip timestamps and emits unreachable / recovered events."""

    def __init__(
        self,
        *,
        bridge: Any,
        peer_unreachable_seconds: float = 60.0,
        poll_interval_seconds: float | None = None,
        emit_event_fn: Any | None = None,
    ) -> None:
        self._bridge = bridge
        self._peer_unreachable_seconds = peer_unreachable_seconds
        # Default poll cadence: every gossip_interval * 3 (rounded up).
        gossip_interval = 10.0
        config = getattr(bridge, "_config", None)
        if config is not None:
            gossip_interval = float(
                getattr(config, "gossip_interval_seconds", 10.0)
            )
        self._poll_interval = (
            poll_interval_seconds if poll_interval_seconds is not None
            else max(1.0, gossip_interval * 3.0)
        )
        self._emit_event_fn = emit_event_fn
        self._unreachable: dict[str, bool] = {}
        self._task: asyncio.Task[None] | None = None
        self._stopped = False

    async def start(self) -> None:
        """Start the polling task."""
        self._stopped = False
        self._task = asyncio.create_task(
            self._loop(), name="federation-cluster-monitor",
        )

    async def stop(self) -> None:
        """Stop the polling task cleanly."""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def is_unreachable(self, peer_node_id: str) -> bool:
        """Return True if the peer is currently flagged unreachable."""
        return self._unreachable.get(peer_node_id, False)

    def list_unreachable(self) -> list[str]:
        """Return the list of currently-unreachable peer node ids."""
        return [p for p, flag in self._unreachable.items() if flag]

    async def _loop(self) -> None:
        while not self._stopped:
            try:
                await asyncio.sleep(self._poll_interval)
                self._tick(now=time.monotonic())
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Cluster monitor tick error: %s", exc)

    def _tick(self, *, now: float) -> None:
        """Inspect peer gossip timestamps and emit transition events."""
        router = getattr(self._bridge, "_router", None)
        peer_models = getattr(router, "_peer_models", {}) if router is not None else {}
        threshold = self._peer_unreachable_seconds
        for node_id, model in list(peer_models.items()):
            last = float(getattr(model, "timestamp", 0.0))
            if last <= 0.0:
                continue
            previously_unreachable = self._unreachable.get(node_id, False)
            silent_for = now - last
            now_unreachable = silent_for > threshold
            if now_unreachable and not previously_unreachable:
                self._unreachable[node_id] = True
                self._emit("federation_peer_unreachable", node_id, silent_for)
            elif not now_unreachable and previously_unreachable:
                self._unreachable[node_id] = False
                self._emit("federation_peer_recovered", node_id, silent_for)

    def _emit(self, event_name: str, peer_node_id: str, silent_for: float) -> None:
        if self._emit_event_fn is None:
            return
        try:
            from probos.events import EventType
            event_type = EventType(event_name)
            self._emit_event_fn(event_type, {
                "peer_node_id": peer_node_id,
                "silent_for_seconds": silent_for,
            })
        except Exception as exc:
            logger.debug("Cluster monitor emit failed: %s", exc)
