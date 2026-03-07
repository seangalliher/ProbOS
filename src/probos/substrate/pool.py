"""Resource pool — maintains N redundant agents of the same type."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from probos.config import PoolConfig
from probos.types import AgentID, AgentState

if TYPE_CHECKING:
    from probos.substrate.registry import AgentRegistry
    from probos.substrate.spawner import AgentSpawner

logger = logging.getLogger(__name__)


class ResourcePool:
    """Manages a named pool of N redundant agents.

    Maintains pool at target size by respawning failed/degraded agents.
    """

    def __init__(
        self,
        name: str,
        agent_type: str,
        spawner: AgentSpawner,
        registry: AgentRegistry,
        config: PoolConfig,
        target_size: int | None = None,
    ) -> None:
        self.name = name
        self.agent_type = agent_type
        self.spawner = spawner
        self.registry = registry
        self.config = config
        self.target_size = target_size or config.default_pool_size
        self._agent_ids: list[AgentID] = []
        self._health_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def current_size(self) -> int:
        return len(self._agent_ids)

    @property
    def healthy_agents(self) -> list[AgentID]:
        """Return IDs of agents that are alive and not degraded."""
        result = []
        for aid in self._agent_ids:
            agent = self.registry.get(aid)
            if agent and agent.is_alive:
                result.append(aid)
        return result

    async def start(self) -> None:
        """Spawn agents to reach target size and start health monitoring."""
        logger.info(
            "Starting pool %r: type=%s target=%d",
            self.name,
            self.agent_type,
            self.target_size,
        )
        self._stop_event.clear()

        # Spawn to target
        while len(self._agent_ids) < self.target_size:
            agent = await self.spawner.spawn(self.agent_type, self.name)
            self._agent_ids.append(agent.id)

        # Start health monitoring loop
        self._health_task = asyncio.create_task(
            self._health_loop(), name=f"pool-health-{self.name}"
        )
        logger.info(
            "Pool %r started: %d agents active", self.name, len(self._agent_ids)
        )

    async def stop(self) -> None:
        """Gracefully shut down all pool members."""
        logger.info("Stopping pool %r...", self.name)
        self._stop_event.set()

        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        # Stop all agents
        for aid in list(self._agent_ids):
            agent = self.registry.get(aid)
            if agent:
                await agent.stop()
                await self.registry.unregister(aid)
        self._agent_ids.clear()
        logger.info("Pool %r stopped.", self.name)

    async def check_health(self) -> dict[str, int]:
        """Check agent health, recycle degraded agents, respawn to maintain size."""
        healthy = 0
        degraded = 0
        dead = 0
        to_recycle: list[AgentID] = []

        for aid in list(self._agent_ids):
            agent = self.registry.get(aid)
            if agent is None:
                # Agent disappeared from registry
                dead += 1
                self._agent_ids.remove(aid)
            elif agent.state == AgentState.DEGRADED:
                degraded += 1
                to_recycle.append(aid)
            elif agent.state == AgentState.RECYCLING:
                dead += 1
                self._agent_ids.remove(aid)
            else:
                healthy += 1

        # Recycle degraded agents
        for aid in to_recycle:
            self._agent_ids.remove(aid)
            new_agent = await self.spawner.recycle(aid, respawn=True)
            if new_agent:
                self._agent_ids.append(new_agent.id)

        # Respawn to maintain target size
        while len(self._agent_ids) < self.target_size:
            agent = await self.spawner.spawn(self.agent_type, self.name)
            self._agent_ids.append(agent.id)

        status = {"healthy": healthy, "degraded": degraded, "dead": dead}
        if degraded or dead:
            logger.info("Pool %r health check: %s", self.name, status)
        return status

    async def _health_loop(self) -> None:
        """Periodic health check loop."""
        interval = self.config.health_check_interval_seconds
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=interval
                )
                break  # Stop event was set
            except asyncio.TimeoutError:
                pass  # Timeout means it's time for a health check
            await self.check_health()

    def info(self) -> dict:
        """Pool status snapshot."""
        agents = []
        for aid in self._agent_ids:
            agent = self.registry.get(aid)
            if agent:
                agents.append(agent.info())
        return {
            "name": self.name,
            "agent_type": self.agent_type,
            "target_size": self.target_size,
            "current_size": len(self._agent_ids),
            "agents": agents,
        }
