"""Agent registry — in-memory index of all live agents."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from probos.types import AgentID

if TYPE_CHECKING:
    from probos.substrate.agent import BaseAgent

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Thread/task-safe registry of all live agents.

    Provides lookup by ID, pool name, or capability.
    """

    def __init__(self) -> None:
        self._agents: dict[AgentID, BaseAgent] = {}
        self._all_cache: list[BaseAgent] | None = None
        self._lock = asyncio.Lock()

    async def register(self, agent: BaseAgent) -> None:
        async with self._lock:
            self._agents[agent.id] = agent
            self._all_cache = None  # invalidate
            logger.debug(
                "Registered agent: type=%s id=%s pool=%s",
                agent.agent_type,
                agent.id[:8],
                agent.pool,
            )

    async def unregister(self, agent_id: AgentID) -> BaseAgent | None:
        async with self._lock:
            agent = self._agents.pop(agent_id, None)
            if agent:
                self._all_cache = None  # invalidate
                logger.debug(
                    "Unregistered agent: type=%s id=%s",
                    agent.agent_type,
                    agent.id[:8],
                )
            return agent

    def get(self, agent_id: AgentID) -> BaseAgent | None:
        return self._agents.get(agent_id)

    def get_by_pool(self, pool_name: str) -> list[BaseAgent]:
        return [a for a in self._agents.values() if a.pool == pool_name]

    def get_by_capability(self, capability: str) -> list[BaseAgent]:
        return [
            a
            for a in self._agents.values()
            if any(c.can == capability for c in a.capabilities)
        ]

    def all(self) -> list[BaseAgent]:
        if self._all_cache is None:
            self._all_cache = list(self._agents.values())
        return self._all_cache

    @property
    def count(self) -> int:
        return len(self._agents)

    def summary(self) -> dict[str, int]:
        """Count of agents per pool."""
        pools: dict[str, int] = {}
        for agent in self._agents.values():
            pools[agent.pool] = pools.get(agent.pool, 0) + 1
        return pools
