"""Agent spawner — factory for creating agents from registered templates."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from probos.types import AgentState

if TYPE_CHECKING:
    from probos.substrate.agent import BaseAgent
    from probos.substrate.registry import AgentRegistry

logger = logging.getLogger(__name__)


class AgentSpawner:
    """Factory that creates agent instances from registered template classes."""

    def __init__(self, registry: AgentRegistry) -> None:
        self.registry = registry
        self._templates: dict[str, type[BaseAgent]] = {}

    def register_template(self, type_name: str, agent_class: type[BaseAgent]) -> None:
        """Register an agent class as a spawnable template."""
        self._templates[type_name] = agent_class
        logger.info("Registered template: %s -> %s", type_name, agent_class.__name__)

    @property
    def available_templates(self) -> list[str]:
        return list(self._templates.keys())

    async def spawn(self, type_name: str, pool: str = "default", **kwargs: Any) -> BaseAgent:
        """Create, register, and start an agent from a template."""
        if type_name not in self._templates:
            raise ValueError(
                f"Unknown agent template: {type_name!r}. "
                f"Available: {self.available_templates}"
            )

        agent_class = self._templates[type_name]
        agent = agent_class(pool=pool, **kwargs)
        agent.state = AgentState.SPAWNING
        await self.registry.register(agent)
        await agent.start()
        return agent

    async def recycle(self, agent_id: str, respawn: bool = True) -> BaseAgent | None:
        """Stop an agent, unregister it, and optionally spawn a replacement."""
        agent = self.registry.get(agent_id)
        if agent is None:
            logger.warning("Cannot recycle unknown agent: %s", agent_id[:8])
            return None

        agent_type = agent.agent_type
        pool = agent.pool

        await agent.stop()
        await self.registry.unregister(agent_id)
        logger.info("Recycled agent: type=%s id=%s", agent_type, agent_id[:8])

        if respawn and agent_type in self._templates:
            return await self.spawn(agent_type, pool)
        return None
