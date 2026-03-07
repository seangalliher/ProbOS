"""Heartbeat agent — fixed-interval health pulses + gossip carrier."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor

if TYPE_CHECKING:
    from probos.mesh.gossip import GossipProtocol

logger = logging.getLogger(__name__)


class HeartbeatAgent(BaseAgent):
    """Base class for agents that emit periodic health pulses.

    Unlike regular agents, heartbeat agents don't respond to intents.
    They run a fixed-interval loop collecting and broadcasting metrics.
    Subclasses implement `collect_metrics()` to define what they report.

    Heartbeat agents also serve as gossip carriers: on each pulse they
    inject their own state into the gossip protocol and carry entries
    from the gossip view, helping state disseminate across the mesh.
    """

    agent_type: str = "heartbeat"
    default_capabilities = [
        CapabilityDescriptor(can="heartbeat", detail="Periodic health pulse"),
    ]
    initial_confidence: float = 0.95  # Simple, reliable agents

    def __init__(self, pool: str = "system", interval: float = 5.0) -> None:
        super().__init__(pool=pool)
        self.interval = interval
        self._pulse_count: int = 0
        self._last_metrics: dict[str, Any] = {}
        self._listeners: list[Any] = []
        self._gossip: GossipProtocol | None = None

    def attach_gossip(self, gossip: GossipProtocol) -> None:
        """Attach a gossip protocol instance for this agent to carry."""
        self._gossip = gossip

    def add_listener(self, callback: Any) -> None:
        """Register a callback invoked on each heartbeat pulse."""
        self._listeners.append(callback)

    async def collect_metrics(self) -> dict[str, Any]:
        """Collect metrics to broadcast. Override in subclasses."""
        return {"pulse": self._pulse_count, "agent_id": self.id}

    async def _run_loop(self) -> None:
        """Fixed-interval pulse loop."""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.interval
                )
                break
            except asyncio.TimeoutError:
                pass

            self._pulse_count += 1
            try:
                metrics = await self.collect_metrics()
                self._last_metrics = metrics
                self.update_confidence(True)

                # Inject own state into gossip
                if self._gossip is not None:
                    self._gossip.update_local(
                        agent_id=self.id,
                        agent_type=self.agent_type,
                        state=self.state,
                        pool=self.pool,
                        capabilities=[c.can for c in self.capabilities],
                        confidence=self.confidence,
                    )

                # Notify listeners
                for listener in self._listeners:
                    try:
                        if asyncio.iscoroutinefunction(listener):
                            await listener(metrics)
                        else:
                            listener(metrics)
                    except Exception:
                        logger.exception("Heartbeat listener error")

                logger.debug(
                    "Heartbeat pulse #%d from %s: %s",
                    self._pulse_count,
                    self.id[:8],
                    metrics,
                )
            except Exception:
                self.update_confidence(False)
                logger.exception("Heartbeat collect_metrics failed for %s", self.id[:8])

    # ------------------------------------------------------------------
    # Lifecycle stubs — heartbeat agents don't process intents
    # ------------------------------------------------------------------

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return None

    async def decide(self, observation: Any) -> Any:
        return None

    async def act(self, plan: Any) -> Any:
        return None

    async def report(self, result: Any) -> dict[str, Any]:
        return self._last_metrics

    def info(self) -> dict[str, Any]:
        base = super().info()
        base["pulse_count"] = self._pulse_count
        base["last_metrics"] = self._last_metrics
        return base
