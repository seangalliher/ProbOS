"""Resource pool — maintains N redundant agents of the same type."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

from probos.config import PoolConfig
from probos.substrate.identity import generate_agent_id
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
        agent_ids: list[str] | None = None,
        **spawn_kwargs: Any,
    ) -> None:
        self.name = name
        self.agent_type = agent_type
        self.spawner = spawner
        self.registry = registry
        self.config = config
        self.target_size = target_size or config.default_pool_size
        self.min_size = config.min_pool_size
        self.max_size = config.max_pool_size
        self._agent_ids: list[AgentID] = []
        self._predetermined_ids: list[str] | None = agent_ids
        self._next_instance_index: int = len(agent_ids) if agent_ids else 0
        self._health_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._spawn_kwargs = spawn_kwargs

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

        # Spawn to target, using predetermined IDs if provided
        idx = 0
        while len(self._agent_ids) < self.target_size:
            kwargs = dict(self._spawn_kwargs)
            if self._predetermined_ids and idx < len(self._predetermined_ids):
                kwargs["agent_id"] = self._predetermined_ids[idx]
            idx += 1
            agent = await self.spawner.spawn(self.agent_type, self.name, **kwargs)
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
            new_id = generate_agent_id(
                self.agent_type, self.name, self._next_instance_index,
            )
            self._next_instance_index += 1
            agent = await self.spawner.spawn(
                self.agent_type, self.name, agent_id=new_id, **self._spawn_kwargs,
            )
            self._agent_ids.append(agent.id)

        # Cap at max_pool_size (safety check)
        while len(self._agent_ids) > self.max_size:
            excess_id = self._agent_ids.pop()
            agent = self.registry.get(excess_id)
            if agent:
                await agent.stop()
                await self.registry.unregister(excess_id)

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

    async def add_agent(self, **kwargs: Any) -> str | None:
        """Spawn one additional agent. Returns new agent ID, or None if at max.

        Does NOT modify target_size — the scaler owns target_size adjustments.
        Generates a deterministic ID using the next available instance_index.
        """
        if self.current_size >= self.max_size:
            return None
        new_id = generate_agent_id(
            self.agent_type, self.name, self._next_instance_index,
        )
        self._next_instance_index += 1
        agent = await self.spawner.spawn(
            self.agent_type, self.name,
            agent_id=new_id, **self._spawn_kwargs, **kwargs,
        )
        self._agent_ids.append(agent.id)
        return agent.id

    async def remove_agent(self, trust_network: Any = None) -> str | None:
        """Stop and remove one agent. Returns removed ID, or None if at min.

        If trust_network is provided, removes the agent with the lowest trust score.
        If trust_network is None or all agents have equal trust, removes newest (last in list).
        Does NOT modify target_size — the scaler owns target_size adjustments.
        """
        if self.current_size <= self.min_size:
            return None

        if trust_network:
            worst_id = None
            worst_trust = float('inf')
            for aid in self._agent_ids:
                score = trust_network.get_score(aid)
                if score < worst_trust:
                    worst_trust = score
                    worst_id = aid
            if worst_id:
                self._agent_ids.remove(worst_id)
                agent = self.registry.get(worst_id)
                if agent:
                    await agent.stop()
                    await self.registry.unregister(worst_id)
                return worst_id

        # Fallback: remove newest
        aid = self._agent_ids.pop()
        agent = self.registry.get(aid)
        if agent:
            await agent.stop()
            await self.registry.unregister(aid)
        return aid

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
