"""Resource pool — maintains N redundant agents of the same type."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TYPE_CHECKING, TypeVar

from probos.config import PoolConfig
from probos.substrate.identity import generate_agent_id
from probos.types import AgentID, AgentState

if TYPE_CHECKING:
    from probos.substrate.agent import BaseAgent
    from probos.substrate.registry import AgentRegistry
    from probos.substrate.spawner import AgentSpawner

logger = logging.getLogger(__name__)

_LifecycleResult = TypeVar("_LifecycleResult")


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
        on_agent_spawned: Callable[[BaseAgent], Awaitable[None]] | None = None,
        on_agent_removing: Callable[[AgentID], Awaitable[None]] | None = None,
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
        self._on_agent_spawned = on_agent_spawned
        self._on_agent_removing = on_agent_removing
        self._lifecycle_lock = asyncio.Lock()

    async def _notify_agent_spawned(self, agent: BaseAgent) -> None:
        """Wire one dynamically spawned agent into runtime-owned mesh state."""
        if self._on_agent_spawned is not None:
            await self._on_agent_spawned(agent)

    async def _notify_agent_removing(self, agent_id: AgentID) -> None:
        """Unwire one agent before its registry entry disappears."""
        if self._on_agent_removing is not None:
            await self._on_agent_removing(agent_id)

    async def _run_lifecycle_transition(
        self,
        operation: Callable[[], Awaitable[_LifecycleResult]],
    ) -> _LifecycleResult:
        """Defer caller cancellation until one lifecycle mutation is coherent."""
        async def _owned_transition() -> _LifecycleResult:
            async with self._lifecycle_lock:
                return await operation()

        task = asyncio.create_task(_owned_transition())
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except BaseException:
                logger.exception(
                    "Pool %r lifecycle transition failed while caller "
                    "cancellation was deferred",
                    self.name,
                )
            raise

    async def _adopt_dynamic_agent(self, agent: BaseAgent) -> None:
        """Wire a dynamic birth, rolling back registry state on failure."""
        try:
            await self._notify_agent_spawned(agent)
        except BaseException as wire_error:
            if agent.id not in self._agent_ids:
                self._agent_ids.append(agent.id)
            try:
                await self._notify_agent_removing(agent.id)
            except BaseException:
                logger.exception(
                    "Dynamic agent %s onboarding rollback could not unwind mesh "
                    "state; retaining pool and registry ownership",
                    agent.id,
                )
                raise wire_error
            try:
                await agent.stop()
            except BaseException:
                logger.exception(
                    "Dynamic agent %s onboarding rollback could not stop the "
                    "agent; retaining pool and registry ownership",
                    agent.id,
                )
                raise wire_error
            try:
                await self.registry.unregister(agent.id)
            except BaseException:
                logger.exception(
                    "Dynamic agent %s onboarding rollback could not unregister "
                    "the agent; retaining pool ownership",
                    agent.id,
                )
                raise wire_error
            self._agent_ids.remove(agent.id)
            raise wire_error
        self._agent_ids.append(agent.id)

    async def _remove_registered_agent_inner(self, agent_id: AgentID) -> bool:
        """Unwire, stop, unregister, then remove one tracked pool member."""
        if agent_id not in self._agent_ids:
            return False

        # A callback failure leaves both pool tracking and registry untouched.
        await self._notify_agent_removing(agent_id)
        agent = self.registry.get(agent_id)
        if agent is not None:
            try:
                await agent.stop()
            except BaseException as stop_error:
                try:
                    await self._notify_agent_spawned(agent)
                except BaseException:
                    logger.exception(
                        "Agent %s stop failed and prior mesh wiring could not "
                        "be restored; retaining pool and registry ownership",
                        agent_id,
                    )
                raise stop_error
            try:
                await self.registry.unregister(agent_id)
            except BaseException:
                logger.exception(
                    "Agent %s stopped but registry removal failed; retaining "
                    "pool ownership for retry",
                    agent_id,
                )
                raise
        self._agent_ids.remove(agent_id)
        return True

    async def _remove_registered_agent(self, agent_id: AgentID) -> bool:
        """Complete one removal atomically before propagating cancellation."""
        return await self._run_lifecycle_transition(
            lambda: self._remove_registered_agent_inner(agent_id)
        )

    async def _remove_missing_agent_inner(self, agent_id: AgentID) -> None:
        """Unwire stale mesh state for an agent already absent from registry."""
        await self._notify_agent_removing(agent_id)
        if agent_id in self._agent_ids:
            self._agent_ids.remove(agent_id)

    async def _recycle_registered_agent_inner(self, agent_id: AgentID) -> None:
        """Replace one degraded agent without overlapping transport owners."""
        old_agent = self.registry.get(agent_id)
        await self._notify_agent_removing(agent_id)
        try:
            # BF-808: the pool owns the dependencies its members were built
            # with, so it hands them back on recycle. Without this the
            # replacement returns alive, answering and permanently dataless.
            new_agent = await self.spawner.recycle(
                agent_id, respawn=True, **self._spawn_kwargs
            )
        except BaseException as recycle_error:
            existing = self.registry.get(agent_id)
            if existing is None and agent_id in self._agent_ids:
                self._agent_ids.remove(agent_id)
            elif existing is old_agent and old_agent is not None:
                try:
                    await self._notify_agent_spawned(existing)
                except BaseException:
                    logger.exception(
                        "Agent %s recycle failed and prior mesh wiring could "
                        "not be restored; pool tracking and registry are preserved",
                        agent_id,
                    )
            raise recycle_error

        if new_agent is None:
            if agent_id in self._agent_ids:
                self._agent_ids.remove(agent_id)
            return

        try:
            await self._notify_agent_spawned(new_agent)
        except BaseException as wire_error:
            try:
                await self._notify_agent_removing(new_agent.id)
            except BaseException:
                logger.exception(
                    "Recycled agent %s onboarding rollback could not unwind "
                    "mesh state; retaining replacement ownership",
                    agent_id,
                )
                raise wire_error
            try:
                await new_agent.stop()
            except BaseException:
                logger.exception(
                    "Recycled agent %s onboarding rollback could not stop the "
                    "replacement; retaining pool and registry ownership",
                    agent_id,
                )
                raise wire_error
            try:
                await self.registry.unregister(new_agent.id)
            except BaseException:
                logger.exception(
                    "Recycled agent %s onboarding rollback could not unregister "
                    "the replacement; retaining pool ownership",
                    agent_id,
                )
                raise wire_error
            if agent_id in self._agent_ids:
                self._agent_ids.remove(agent_id)
            raise wire_error

    async def _recycle_registered_agent(self, agent_id: AgentID) -> None:
        """Complete one recycle atomically before propagating cancellation."""
        await self._run_lifecycle_transition(
            lambda: self._recycle_registered_agent_inner(agent_id)
        )

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

    async def _start_inner(self) -> None:
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

    async def start(self) -> None:
        """Start the pool under the lifecycle lock."""
        await self._run_lifecycle_transition(self._start_inner)

    async def _stop_members_inner(self) -> None:
        """Stop all members after the health loop has quiesced."""
        logger.info("Stopping pool %r...", self.name)

        # Stop all agents
        for aid in list(self._agent_ids):
            await self._remove_registered_agent_inner(aid)
        logger.info("Pool %r stopped.", self.name)

    async def stop(self) -> None:
        """Quiesce health, then stop members before propagating cancellation."""
        async def _stop_transition() -> None:
            self._stop_event.set()
            health_task = self._health_task
            if (
                health_task is not None
                and health_task is not asyncio.current_task()
                and not health_task.done()
            ):
                health_task.cancel()
                try:
                    await health_task
                except asyncio.CancelledError:
                    pass
            self._health_task = None
            async with self._lifecycle_lock:
                await self._stop_members_inner()

        task = asyncio.create_task(_stop_transition())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except BaseException:
                logger.exception(
                    "Pool %r stop failed while caller cancellation was deferred",
                    self.name,
                )
            raise

    async def _check_health_inner(self) -> dict[str, int]:
        """Check agent health, recycle degraded agents, respawn to maintain size."""
        healthy = 0
        degraded = 0
        dead = 0
        to_recycle: list[AgentID] = []

        for aid in list(self._agent_ids):
            agent = self.registry.get(aid)
            if agent is None:
                # Agent disappeared from registry
                await self._remove_missing_agent_inner(aid)
                dead += 1
            elif agent.state == AgentState.DEGRADED:
                degraded += 1
                to_recycle.append(aid)
            elif agent.state == AgentState.RECYCLING:
                dead += 1
                await self._remove_registered_agent_inner(aid)
            else:
                healthy += 1

        # Recycle degraded agents
        for aid in to_recycle:
            await self._recycle_registered_agent_inner(aid)

        # Respawn to maintain target size
        while len(self._agent_ids) < self.target_size:
            new_id = generate_agent_id(
                self.agent_type, self.name, self._next_instance_index,
            )
            self._next_instance_index += 1
            agent = await self.spawner.spawn(
                self.agent_type, self.name, agent_id=new_id, **self._spawn_kwargs,
            )
            await self._adopt_dynamic_agent(agent)

        # Cap at max_pool_size (safety check)
        while len(self._agent_ids) > self.max_size:
            await self._remove_registered_agent_inner(self._agent_ids[-1])

        status = {"healthy": healthy, "degraded": degraded, "dead": dead}
        if degraded or dead:
            logger.info("Pool %r health check: %s", self.name, status)
        return status

    async def check_health(self) -> dict[str, int]:
        """Run one serialized pool health and recovery pass."""
        return await self._run_lifecycle_transition(self._check_health_inner)

    async def _health_loop(self) -> None:
        """Periodic health check loop.

        BF-824: the check is wrapped, because `await self.check_health()` used
        to be unguarded -- one exception ended this task, and **nothing in
        `src/` restarts a pool health task**. The failure was invisible: the
        pool kept its members, kept answering, and simply never checked or
        refilled again for the remaining life of the process.

        Scope is deliberately just this boundary. Containing failures per
        MEMBER inside `check_health` would also let a failing pass reach its own
        refill step, but `check_health` is public and callers rely on it
        RAISING (`agents/medical/surgeon.py`, `test_ad1019c_consensus`), so that
        is a contract change with its own consumer migration -- filed
        separately.

        The residual is therefore real: while a member keeps failing to recycle,
        the exception still escapes before refill and the pool stays short. What
        this boundary buys is that the loop SURVIVES, so the pool recovers by
        itself the moment the failure clears.

        `CancelledError` is deliberately NOT caught: shutdown must still be
        able to end this loop.
        """
        interval = self.config.health_check_interval_seconds
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=interval
                )
                break  # Stop event was set
            except asyncio.TimeoutError:
                pass  # Timeout means it's time for a health check
            try:
                await self.check_health()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Pool %r health check failed; the loop survives and will "
                    "try again in %ss.",
                    self.name, interval,
                )

    async def _add_agent_inner(self, **kwargs: Any) -> str | None:
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
        await self._adopt_dynamic_agent(agent)
        return agent.id

    async def add_agent(self, **kwargs: Any) -> str | None:
        """Spawn one additional agent under the lifecycle lock."""
        return await self._run_lifecycle_transition(
            lambda: self._add_agent_inner(**kwargs)
        )

    async def _remove_agent_inner(self, trust_network: Any = None) -> str | None:
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
                await self._remove_registered_agent_inner(worst_id)
                return worst_id

        # Fallback: remove newest
        aid = self._agent_ids[-1]
        await self._remove_registered_agent_inner(aid)
        return aid

    async def remove_agent(self, trust_network: Any = None) -> str | None:
        """Stop and remove one agent under the lifecycle lock."""
        return await self._run_lifecycle_transition(
            lambda: self._remove_agent_inner(trust_network)
        )

    async def remove_specific_agent(self, agent_id: AgentID) -> bool:
        """Stop and remove one exact member through the full lifecycle."""
        return await self._run_lifecycle_transition(
            lambda: self._remove_registered_agent_inner(agent_id)
        )

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

    # ------------------------------------------------------------------
    # AD-514: Public API for agent ID access
    # ------------------------------------------------------------------

    def get_agent_ids(self) -> list[AgentID]:
        """Return a copy of all agent IDs in this pool."""
        return list(self._agent_ids)

    def contains_agent(self, agent_id: AgentID) -> bool:
        """Check if an agent is in this pool."""
        return agent_id in self._agent_ids

    def remove_agent_by_id(self, agent_id: AgentID) -> None:
        """Remove only stale tracking state; never use for live lifecycle removal."""
        if agent_id in self._agent_ids:
            self._agent_ids.remove(agent_id)
            logger.debug("Agent %s removed from pool %s tracking", agent_id, self.name)
        else:
            logger.debug("Agent %s not found in pool %s tracking; no-op", agent_id, self.name)
