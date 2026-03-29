"""Agent spawner — factory for creating agents from registered templates."""

from __future__ import annotations

import logging
from collections.abc import Iterator
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

    def unregister_template(self, type_name: str) -> None:
        """Remove a registered agent template."""
        self._templates.pop(type_name, None)

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
        """Stop an agent, unregister it, and optionally spawn a replacement.

        The replacement gets the SAME agent_id — the individual persists
        through recycling (Phase 14c).
        """
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
            return await self.spawn(agent_type, pool, agent_id=agent_id)
        return None

    # ------------------------------------------------------------------
    # AD-514: Public API for template access
    # ------------------------------------------------------------------

    def get_template(self, agent_type: str) -> type[BaseAgent] | None:
        """Return the registered agent class for the given type, or None."""
        return self._templates.get(agent_type)

    def list_templates(self) -> dict[str, type[BaseAgent]]:
        """Return a copy of all registered templates {type_name: class}."""
        return dict(self._templates)

    def iter_templates(self) -> Iterator[tuple[str, type[BaseAgent]]]:
        """Iterate over (type_name, class) pairs."""
        return iter(self._templates.items())

    def replace_template(self, agent_type: str, cls: type[BaseAgent]) -> None:
        """Replace the class for an existing agent type (self-mod hot-swap)."""
        if agent_type not in self._templates:
            raise KeyError(f"Unknown agent type: {agent_type}")
        self._templates[agent_type] = cls
        logger.info("Template replaced: %s -> %s", agent_type, cls.__name__)
