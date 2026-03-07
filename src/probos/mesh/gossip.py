"""Gossip protocol — SWIM-style state dissemination."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any

from probos.types import AgentID, AgentState, GossipEntry

logger = logging.getLogger(__name__)


class GossipProtocol:
    """SWIM-style gossip protocol for state dissemination.

    Each agent's state is represented as a GossipEntry. The protocol
    periodically selects random peers and exchanges state, merging
    by recency. No agent knows everything — each has a partial view.

    Heartbeat agents act as gossip carriers: on each pulse they
    inject their own entry and forward entries they've heard.
    """

    def __init__(
        self,
        interval_seconds: float = 1.0,
        fanout: int = 2,
    ) -> None:
        self.interval = interval_seconds
        self.fanout = fanout  # Number of peers to gossip with per round
        self._view: dict[AgentID, GossipEntry] = {}
        self._sequence: int = 0
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._listeners: list[Any] = []

    def add_listener(self, callback: Any) -> None:
        """Register a callback invoked when the gossip view changes."""
        self._listeners.append(callback)

    # ------------------------------------------------------------------
    # State injection and merge
    # ------------------------------------------------------------------

    def update_local(
        self,
        agent_id: AgentID,
        agent_type: str,
        state: AgentState,
        pool: str = "",
        capabilities: list[str] | None = None,
        confidence: float = 0.0,
    ) -> GossipEntry:
        """Inject or update a local agent's entry into the gossip view."""
        self._sequence += 1
        entry = GossipEntry(
            agent_id=agent_id,
            agent_type=agent_type,
            state=state,
            pool=pool,
            capabilities=capabilities or [],
            confidence=confidence,
            timestamp=datetime.now(timezone.utc),
            sequence=self._sequence,
        )
        self._view[agent_id] = entry
        return entry

    def receive(self, entry: GossipEntry) -> bool:
        """Merge a received gossip entry. Returns True if view was updated."""
        existing = self._view.get(entry.agent_id)
        if existing is None or entry.timestamp > existing.timestamp:
            self._view[entry.agent_id] = entry
            return True
        return False

    def receive_batch(self, entries: list[GossipEntry]) -> int:
        """Merge multiple entries. Returns count of updates."""
        updated = 0
        for entry in entries:
            if self.receive(entry):
                updated += 1
        return updated

    def remove(self, agent_id: AgentID) -> None:
        """Remove an agent from the gossip view (agent recycled)."""
        self._view.pop(agent_id, None)

    # ------------------------------------------------------------------
    # Querying the view
    # ------------------------------------------------------------------

    def get_entry(self, agent_id: AgentID) -> GossipEntry | None:
        return self._view.get(agent_id)

    def get_view(self) -> dict[AgentID, GossipEntry]:
        return dict(self._view)

    def get_active_agents(self) -> list[GossipEntry]:
        """Return entries for agents believed to be active."""
        return [
            e for e in self._view.values()
            if e.state in (AgentState.ACTIVE, AgentState.DEGRADED)
        ]

    def random_sample(self, count: int, exclude: AgentID | None = None) -> list[GossipEntry]:
        """Pick random entries from the view (for gossip exchange)."""
        candidates = [
            e for e in self._view.values()
            if e.agent_id != exclude
        ]
        k = min(count, len(candidates))
        return random.sample(candidates, k) if k > 0 else []

    @property
    def view_size(self) -> int:
        return len(self._view)

    # ------------------------------------------------------------------
    # Background gossip loop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._gossip_loop(), name="gossip-protocol"
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _gossip_loop(self) -> None:
        """Periodic gossip — notify listeners each round for exchange."""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.interval
                )
                break
            except asyncio.TimeoutError:
                pass

            # Notify listeners (runtime wires this to trigger peer exchange)
            for listener in self._listeners:
                try:
                    if asyncio.iscoroutinefunction(listener):
                        await listener(self._view)
                    else:
                        listener(self._view)
                except Exception:
                    logger.exception("Gossip listener error")
