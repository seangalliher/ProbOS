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
        try:
            await agent.start()
        except BaseException as start_error:
            try:
                await agent.stop()
            except BaseException:
                logger.warning(
                    "Agent startup rollback could not stop type=%s id=%s; "
                    "retaining registry ownership of the failed instance",
                    type_name,
                    agent.id,
                    exc_info=True,
                )
                raise start_error
            try:
                await self.registry.unregister(agent.id)
            except BaseException:
                logger.exception(
                    "Agent startup rollback could not unregister type=%s id=%s; "
                    "preserving the original startup error",
                    type_name,
                    agent.id,
                )
            raise start_error
        return agent

    #: Dependencies a recycled agent visibly loses when the caller does not pass
    #: them. Reported, NOT enforced -- see the note in :meth:`recycle`.
    _RECYCLE_CRITICAL_DEPS = ("_runtime", "_llm_client")

    async def recycle(
        self, agent_id: str, respawn: bool = True, **spawn_kwargs: Any
    ) -> BaseAgent | None:
        """Stop an agent, unregister it, and optionally spawn a replacement.

        The replacement gets the SAME agent_id — the individual persists
        through recycling (Phase 14c).

        BF-808: ``spawn_kwargs`` carries the dependencies the agent was built
        with. Recycling used to pass only ``agent_id``, so a replacement came
        back with ``_runtime = None`` and no ``llm_client`` -- alive, answering,
        and permanently unable to do its job. The caller owns those kwargs
        (``ResourcePool`` holds them for exactly this reason), so the caller
        supplies them rather than the factory guessing.

        A lost dependency is REPORTED, not refused. Refusing was the first
        draft and was worse in two measured ways: the raise escaped
        ``check_health`` before its refill loop and killed the pool's health
        task outright (there is no supervisor to restart it), and it implied a
        completeness the check does not have -- a recycled Quartermaster keeps
        ``_runtime``, passes this check, and is still degraded because its
        store, router and reconciler are wired after construction in
        ``finalize`` and are not constructor kwargs at all. Making recycle
        whole needs a runtime-owned rehydration hook, tracked separately.
        """
        agent = self.registry.get(agent_id)
        if agent is None:
            logger.warning("Cannot recycle unknown agent: %s", agent_id[:8])
            return None

        agent_type = agent.agent_type
        pool = agent.pool
        # Snapshot from the PREDECESSOR rather than a fixed list, so an agent
        # that legitimately has no llm_client is not reported as losing one.
        had = {
            name
            for name in self._RECYCLE_CRITICAL_DEPS
            if getattr(agent, name, None) is not None
        }

        await agent.stop()
        await self.registry.unregister(agent_id)
        logger.info("Recycled agent: type=%s id=%s", agent_type, agent_id[:8])

        if respawn and agent_type in self._templates:
            replacement = await self.spawn(
                agent_type, pool, agent_id=agent_id, **spawn_kwargs
            )
            lost = sorted(
                name for name in had if getattr(replacement, name, None) is None
            )
            if lost:
                logger.error(
                    "BF-808: recycled agent type=%s id=%s came back without %s. "
                    "It will report healthy and never have data. The caller did "
                    "not pass the dependencies the original was built with.",
                    agent_type, agent_id[:8], ", ".join(lost),
                )
            return replacement
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
