"""Resource pool — maintains N redundant agents of the same type."""

from __future__ import annotations

import asyncio
import logging
import time
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
        # BF-846: ``agent_id`` is assigned per member by this pool, and it is
        # also forwarded verbatim to ``spawner.spawn``/``recycle`` -- so a
        # caller-supplied one collides with the explicit keyword and raises
        # ``TypeError: got multiple values for argument 'agent_id'`` on the
        # first health pass, long after construction. ``runtime.py`` forwards
        # arbitrary ``**spawn_kwargs`` publicly, so this is reachable. Rejected
        # here, where the mistake is, rather than at the failure.
        if "agent_id" in spawn_kwargs:
            raise TypeError(
                "ResourcePool assigns each member's agent_id, so 'agent_id' "
                "cannot be passed as a spawn kwarg. Use agent_ids=[...] to pin "
                "member identities."
            )
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
        # BF-846: members whose recycle failed WITHOUT leaving them degraded.
        # The ordinary failure leaves the member DEGRADED, so the next scan
        # re-queues it by itself; the wire-fails-then-rollback-unwire-fails
        # path instead retains an ACTIVE replacement, which the scan would
        # never look at again.
        self._recycle_retry: set[AgentID] = set()
        # BF-846: last logged failure per ``(member, signature)``, and when. A
        # permanently unrecyclable member otherwise emits a traceback every
        # interval forever -- measured at 1,054 exception records in 50 ms.
        self._recycle_failure_log: dict[tuple[AgentID, str], tuple[float, int]] = {}

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
        # BF-846: transient recovery state belongs to a RUN, not to the object.
        # Left over a restart, a retry entry made a fresh member with a reused
        # predetermined id get recycled once for a previous run's failure.
        self._recycle_retry.clear()
        self._recycle_failure_log.clear()

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

    _RECYCLE_FAILURE_LOG_COOLDOWN_SECONDS = 60.0
    _RECYCLE_FAILURE_LOG_MAX_ENTRIES = 64

    @staticmethod
    def _failure_signature(exc: BaseException) -> str:
        """A bounded, non-throwing fingerprint for one failure.

        ``str(exc)`` is arbitrary caller code. An exception whose ``__str__``
        raised propagated out of the containment and left the pool short --
        recreating the exact defect BF-846 removes -- so rendering must not be
        able to fail. It is truncated because the value goes into a dict key
        and a dynamic tail would defeat coalescing.

        The last traceback frame is part of the fingerprint: the same class and
        message can arrive from different lifecycle stages (an initial unwire
        and a rollback unwire, say), and treating those as one failure hides
        the second.
        """
        try:
            detail = str(exc)[:200]
        except Exception:  # noqa: BLE001 - a failure here must not mask the failure
            detail = "<unprintable>"
        origin = "?"
        try:
            frame = exc.__traceback__
            while frame is not None and frame.tb_next is not None:
                frame = frame.tb_next
            if frame is not None:
                origin = f"{frame.tb_frame.f_code.co_name}:{frame.tb_lineno}"
        except Exception:  # noqa: BLE001
            origin = "?"
        return f"{type(exc).__name__}@{origin}: {detail}"

    def _prune_recycle_failure_log(self) -> None:
        """Drop throttle state for members the pool no longer owns.

        Entries were only removed on a SUCCESSFUL recycle, so every member that
        failed and then left -- the ordinary outcome when a replacement cannot
        be started -- left one behind forever. Measured: 12 failures, 12 stale
        entries, none of their ids still tracked.
        """
        tracked = set(self._agent_ids)
        for key in [k for k in self._recycle_failure_log if k[0] not in tracked]:
            del self._recycle_failure_log[key]
        # A last-resort bound. Pruning by ownership is the real mechanism; this
        # only stops a pathological churn of signatures growing without limit.
        while len(self._recycle_failure_log) > self._RECYCLE_FAILURE_LOG_MAX_ENTRIES:
            oldest = min(self._recycle_failure_log, key=lambda k: self._recycle_failure_log[k][0])
            del self._recycle_failure_log[oldest]

    def _report_recycle_failure(self, agent_id: AgentID, exc: BaseException) -> None:
        """Report a contained recycle failure without flooding the log.

        BF-846: a permanently unrecyclable member used to emit a full traceback
        on every pass -- measured at 1,054 exception records in 50 ms with the
        interval at 0.0, and a traceback every five seconds forever at the
        default. The first occurrence of a signature carries its traceback; a
        repeat is a single line, at most once per cooldown, carrying how many
        were suppressed. Silence is not an option -- that is the invisibility
        BF-824 exists to remove.

        Keyed by ``(member, signature)``, not by member alone: keeping only the
        LAST signature made two failures that alternate each look new, so
        neither was ever throttled.
        """
        signature = self._failure_signature(exc)
        key = (agent_id, signature)
        now = time.monotonic()
        previous = self._recycle_failure_log.get(key)
        if previous is not None:
            last_logged, suppressed = previous
            if now - last_logged < self._RECYCLE_FAILURE_LOG_COOLDOWN_SECONDS:
                self._recycle_failure_log[key] = (last_logged, suppressed + 1)
                return
            logger.error(
                "Pool %r still cannot recycle member %s (%s); %d further "
                "identical failures were suppressed. The pass continues and "
                "refills, so the pool holds its size, but this member is not "
                "being replaced.",
                self.name, agent_id, signature, suppressed,
            )
            self._recycle_failure_log[key] = (now, 0)
            return
        self._recycle_failure_log[key] = (now, 0)
        logger.exception(
            "Pool %r could not recycle member %s; the pass continues to its "
            "refill step and will retry this member next tick.",
            self.name, agent_id, exc_info=exc,
        )

    async def _check_health_inner(self) -> dict[str, int]:
        """Check agent health, recycle degraded agents, respawn to maintain size.

        BF-846: a member that cannot be recycled no longer aborts the pass.
        The recycle loop runs BEFORE refill, so a single raising member left the
        pool permanently short -- measured, a pool of target 2 held at 1 with
        ``spawns=0`` while the failure persisted. Failures are contained per
        member, counted into the returned status, and retried on the next pass.

        `CancelledError` still propagates: shutdown must be able to end a pass.
        """
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

        # BF-846: members carried over from a failure that did NOT leave them
        # degraded. Without this the ACTIVE replacement retained by the
        # rollback path is a one-pass signal the scan never revisits.
        for aid in sorted(self._recycle_retry):
            if aid in self._agent_ids and aid not in to_recycle:
                to_recycle.append(aid)
        self._recycle_retry.clear()

        # Recycle degraded agents
        recycle_failures = 0
        for aid in to_recycle:
            try:
                await self._recycle_registered_agent_inner(aid)
            except MemoryError:
                # A contained failure continues into the refill step, which
                # SPAWNS. Doing that under memory exhaustion is the one way
                # "keep going" makes things strictly worse.
                raise
            except Exception as exc:
                # Deliberately ``Exception``, not ``BaseException``: everything
                # outside it -- ``CancelledError``, ``SystemExit``,
                # ``KeyboardInterrupt``, ``GeneratorExit``, and a
                # ``BaseExceptionGroup`` carrying any of them -- means STOP,
                # and containing those let a shutdown continue into refill.
                recycle_failures += 1
                self._report_recycle_failure(aid, exc)
                member = self.registry.get(aid)
                if (
                    aid in self._agent_ids
                    and member is not None
                    and member.state != AgentState.DEGRADED
                ):
                    # Nothing about this member's state will make the next scan
                    # look at it again, so remember it explicitly.
                    self._recycle_retry.add(aid)
            else:
                self._recycle_failure_log = {
                    k: v for k, v in self._recycle_failure_log.items() if k[0] != aid
                }

        self._prune_recycle_failure_log()

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

        status = {
            "healthy": healthy,
            "degraded": degraded,
            "dead": dead,
            # BF-846: non-zero means the pool did NOT fully remediate itself.
            # A caller that reports success on the strength of the call
            # returning is reporting something it did not check.
            "recycle_failures": recycle_failures,
        }
        if degraded or dead or recycle_failures:
            logger.info("Pool %r health check: %s", self.name, status)
        return status

    async def check_health(self) -> dict[str, int]:
        """Run one serialized pool health and recovery pass.

        BF-846: this no longer raises when an individual member cannot be
        recycled -- containing that is what lets the same pass reach its refill
        step. The failure is reported in ``status["recycle_failures"]``, so a
        caller that needs to know whether the pool actually remediated itself
        must READ the status rather than treat "it returned" as success.

        It still raises for a failure of the pass itself, such as a spawn that
        fails during refill.
        """
        return await self._run_lifecycle_transition(self._check_health_inner)

    async def _health_loop(self) -> None:
        """Periodic health check loop.

        BF-824: the check is wrapped, because `await self.check_health()` used
        to be unguarded -- one exception ended this task, and **nothing in
        `src/` restarts a pool health task**. The failure was invisible: the
        pool kept its members, kept answering, and simply never checked or
        refilled again for the remaining life of the process.

        BF-846 closed the residual BF-824 left: a member that cannot be
        recycled is now contained inside `check_health`, so the same pass
        reaches its refill step and the pool holds its size while the failure
        persists. This boundary still matters for a failure of the pass ITSELF
        -- a spawn that fails during refill, say -- which is exactly the class
        that would otherwise end the loop.

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
