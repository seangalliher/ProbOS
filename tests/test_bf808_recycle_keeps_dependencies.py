"""BF-808 (#1272): a recycled agent comes back able to do its job.

Health-driven recycling respawned with `agent_id` alone, so the replacement had
`_runtime = None` and no `llm_client`. Measured on a real `PageReaderAgent`
before the fix:

    RECYCLED same id          : True
    RECYCLED _runtime is None : True
    RECYCLED llm_client set   : False
    RECYCLED is_alive         : True
    RECYCLED state            : AgentState.ACTIVE
    RECYCLED fetched_content  : False
    RECYCLED fetch_failed     : None

The last two lines are the point. It did not fetch, and it did not report a
failure either -- `perceive` short-circuits on `self._runtime` before it can
honestly degrade. The agent reported healthy and was permanently dataless, and
nothing anywhere said so.

`ResourcePool` already held the dependencies its members were built with. It now
hands them back on recycle, and a replacement that still comes back short raises
rather than being registered: a pool one member down is a state the system can
act on, an inert member that reports healthy is not.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.agents.utility.web_agents import PageReaderAgent
from probos.config import PoolConfig
from probos.substrate.agent import BaseAgent
from probos.substrate.pool import ResourcePool
from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.types import IntentMessage


class _PlainAgent(BaseAgent):
    """An agent with no runtime and no llm_client, legitimately."""

    agent_type = "plain"

    async def perceive(self, intent):
        return {}

    async def decide(self, observation):
        return {}

    async def act(self, decision):
        return {"success": True}

    async def report(self, result):
        return result


def _spawner(registry: AgentRegistry) -> AgentSpawner:
    spawner = AgentSpawner(registry)
    spawner.register_template("page_reader", PageReaderAgent)
    spawner.register_template("plain", _PlainAgent)
    return spawner


# ── the seam: the spawner ────────────────────────────────────────


class TestRecycleCarriesTheDependenciesForward:
    async def test_a_replacement_keeps_runtime_and_llm_client(self):
        registry = AgentRegistry()
        spawner = _spawner(registry)
        runtime, llm = MagicMock(), MagicMock()

        await spawner.spawn(
            "page_reader", "readers", agent_id="r1",
            runtime=runtime, llm_client=llm,
        )
        replacement = await spawner.recycle(
            "r1", respawn=True, runtime=runtime, llm_client=llm
        )

        assert replacement is not None
        assert replacement._runtime is runtime
        assert replacement._llm_client is llm
        await replacement.stop()

    async def test_the_identity_still_survives_a_recycle(self):
        """AD-179: the individual persists through recycling -- same id, same
        trust, same routing. That must not be a casualty of this fix."""
        registry = AgentRegistry()
        spawner = _spawner(registry)
        runtime = MagicMock()

        original = await spawner.spawn(
            "page_reader", "readers", agent_id="r2", runtime=runtime
        )
        replacement = await spawner.recycle("r2", respawn=True, runtime=runtime)

        assert replacement.id == original.id == "r2"
        assert replacement is not original
        assert replacement.pool == original.pool
        await replacement.stop()

    async def test_an_agent_that_never_had_an_llm_is_not_required_to_grow_one(self):
        """The snapshot is taken from the PREDECESSOR, not from a fixed list,
        so a dependency-free agent recycles normally."""
        registry = AgentRegistry()
        spawner = _spawner(registry)

        await spawner.spawn("plain", "plains", agent_id="p1")
        replacement = await spawner.recycle("p1", respawn=True)

        assert replacement is not None
        assert replacement.id == "p1"
        await replacement.stop()

    async def test_a_dependency_free_agent_is_not_falsely_reported(self, caplog):
        """A fixed list would report every plain agent as having lost both
        dependencies. A warning that fires on healthy recycles is noise, and
        noise is what teaches people to ignore the real one."""
        import logging

        registry = AgentRegistry()
        spawner = _spawner(registry)
        await spawner.spawn("plain", "plains", agent_id="p3")

        with caplog.at_level(logging.ERROR):
            replacement = await spawner.recycle("p3", respawn=True)

        assert not any("BF-808" in r.getMessage() for r in caplog.records), (
            "a dependency-free agent was reported as having lost dependencies"
        )
        await replacement.stop()

    async def test_losing_a_dependency_raises_rather_than_registering_it(self):
        """REPLACED by `test_a_lost_dependency_is_reported`. Kept inverted rather
        than deleted so the reasoning stays visible: refusing the replacement
        killed the pool's health task, because the raise escaped `check_health`
        before its refill loop and nothing restarts it."""
        registry = AgentRegistry()
        spawner = _spawner(registry)
        runtime = MagicMock()

        await spawner.spawn(
            "page_reader", "readers", agent_id="r3", runtime=runtime
        )

        replacement = await spawner.recycle("r3", respawn=True)

        assert replacement is not None, "recycle must not raise here"
        await replacement.stop()

    async def test_a_lost_dependency_is_reported(self, caplog):
        """Reported, not refused. Refusing was the first draft and was worse in
        two measured ways -- see `TestRefusingWouldHaveBeenWorse`."""
        import logging

        registry = AgentRegistry()
        spawner = _spawner(registry)

        await spawner.spawn(
            "page_reader", "readers", agent_id="r4",
            runtime=MagicMock(), llm_client=MagicMock(),
        )

        with caplog.at_level(logging.ERROR):
            replacement = await spawner.recycle("r4", respawn=True)

        assert replacement is not None
        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "_runtime" in messages
        assert "_llm_client" in messages
        await replacement.stop()

    async def test_nothing_is_reported_when_the_dependencies_survive(self, caplog):
        import logging

        registry = AgentRegistry()
        spawner = _spawner(registry)
        runtime, llm = MagicMock(), MagicMock()

        await spawner.spawn(
            "page_reader", "readers", agent_id="r6",
            runtime=runtime, llm_client=llm,
        )

        with caplog.at_level(logging.ERROR):
            replacement = await spawner.recycle(
                "r6", respawn=True, runtime=runtime, llm_client=llm
            )

        assert not any("BF-808" in r.getMessage() for r in caplog.records)
        await replacement.stop()

    async def test_recycling_an_unknown_agent_is_still_a_no_op(self):
        registry = AgentRegistry()
        spawner = _spawner(registry)

        assert await spawner.recycle("nobody", respawn=True) is None

    async def test_respawn_false_still_returns_none(self):
        registry = AgentRegistry()
        spawner = _spawner(registry)
        await spawner.spawn("plain", "plains", agent_id="p2")

        assert await spawner.recycle("p2", respawn=False) is None
        assert registry.get("p2") is None


# ── the path that actually recycles in production ────────────────


class TestRecycleThroughThePool:
    """The issue's acceptance criterion: recycle a real agent through the pool
    and then exercise a capability that requires `runtime`."""

    @staticmethod
    async def _pool(registry, spawner, **kwargs) -> ResourcePool:
        pool = ResourcePool(
            name="readers",
            agent_type="page_reader",
            spawner=spawner,
            registry=registry,
            config=PoolConfig(default_pool_size=1, min_pool_size=1, max_pool_size=2),
            target_size=1,
            **kwargs,
        )
        await pool.start()
        return pool

    async def test_a_pool_recycled_agent_can_still_reach_the_mesh(self):
        registry = AgentRegistry()
        spawner = _spawner(registry)
        runtime, llm = MagicMock(), MagicMock()
        pool = await self._pool(registry, spawner, runtime=runtime, llm_client=llm)
        try:
            aid = pool._agent_ids[0]

            await pool._recycle_registered_agent_inner(aid)

            recycled = registry.get(aid)
            assert recycled is not None
            assert recycled._runtime is runtime, (
                "the pool holds the dependencies and did not hand them back"
            )
            assert recycled._llm_client is llm
        finally:
            await pool.stop()

    async def test_the_recycled_agent_actually_fetches(self, monkeypatch):
        """Not "has an attribute" -- does the work. A recycled reader used to
        return an observation with neither content nor a failure."""
        from probos.agents.utility import web_agents

        registry = AgentRegistry()
        spawner = _spawner(registry)
        runtime, llm = MagicMock(), MagicMock()
        pool = await self._pool(registry, spawner, runtime=runtime, llm_client=llm)
        try:
            aid = pool._agent_ids[0]
            await pool._recycle_registered_agent_inner(aid)
            recycled = registry.get(aid)

            async def _fetch(_runtime, _url):
                return web_agents.FetchOutcome(
                    body="<html><body>hello</body></html>",
                    status_code=200,
                    final_url="https://e.co/x",
                )

            monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", _fetch)

            obs = await recycled.perceive(
                IntentMessage(intent="read_page", params={"url": "https://e.co/x"})
            )

            assert "hello" in obs.get("fetched_content", ""), (
                "the recycled agent produced no content and no failure -- the "
                "silently-inert state BF-808 describes"
            )
            assert not obs.get("fetch_failed")
        finally:
            await pool.stop()

    async def test_the_pool_keeps_tracking_the_recycled_member(self):
        registry = AgentRegistry()
        spawner = _spawner(registry)
        pool = await self._pool(registry, spawner, runtime=MagicMock())
        try:
            aid = pool._agent_ids[0]
            await pool._recycle_registered_agent_inner(aid)

            assert pool._agent_ids == [aid]
            assert pool.current_size == 1
        finally:
            await pool.stop()

    async def test_a_pool_with_no_dependencies_recycles_unchanged(self):
        """A pool whose members take no runtime must be byte-identical in
        behaviour -- the fix must not require dependencies that never existed."""
        registry = AgentRegistry()
        spawner = _spawner(registry)
        pool = ResourcePool(
            name="plains",
            agent_type="plain",
            spawner=spawner,
            registry=registry,
            config=PoolConfig(default_pool_size=1, min_pool_size=1, max_pool_size=2),
            target_size=1,
        )
        await pool.start()
        try:
            aid = pool._agent_ids[0]
            await pool._recycle_registered_agent_inner(aid)

            assert registry.get(aid) is not None
        finally:
            await pool.stop()


class TestRefusingWouldHaveBeenWorse:
    """The first draft REFUSED a replacement that lost a dependency. Review
    measured two ways that was worse than the defect, both pinned here."""

    async def test_a_recycle_leaves_the_pools_health_task_alive(self):
        """The raise escaped `check_health` before its refill loop, and nothing
        in `src/` restarts a pool health task. One bad member would have
        disabled monitoring for that pool permanently."""
        registry = AgentRegistry()
        spawner = _spawner(registry)
        pool = ResourcePool(
            name="readers",
            agent_type="page_reader",
            spawner=spawner,
            registry=registry,
            config=PoolConfig(default_pool_size=1, min_pool_size=1, max_pool_size=2),
            target_size=1,
            runtime=MagicMock(),
        )
        await pool.start()
        try:
            aid = pool._agent_ids[0]
            await pool._recycle_registered_agent_inner(aid)

            assert pool._health_task is not None
            assert not pool._health_task.done(), (
                "the pool's health task died on a recycle; nothing restarts it"
            )
            assert pool.current_size == 1
        finally:
            await pool.stop()

    async def test_the_replacement_is_kept_rather_than_orphaned(self):
        """Removing a refused replacement meant stopping then unregistering it.
        When `stop()` failed, the unregister still ran and left an ACTIVE agent
        with a live task outside registry, pool and shutdown ownership."""
        registry = AgentRegistry()
        spawner = _spawner(registry)

        await spawner.spawn(
            "page_reader", "readers", agent_id="r7", runtime=MagicMock()
        )
        replacement = await spawner.recycle("r7", respawn=True)

        assert replacement is not None
        assert registry.get("r7") is replacement, (
            "the replacement must stay owned by the registry"
        )
        await replacement.stop()


class TestTheDependencySetIsADecision:
    def test_each_named_dependency_is_one_an_agent_really_has(self):
        """Not a restatement of the constant -- each name is checked against a
        real constructed agent, so a rename in `BaseAgent` makes the guard
        silently stop firing and this fails instead."""
        agent = PageReaderAgent(
            agent_id="probe", pool="readers",
            runtime=MagicMock(), llm_client=MagicMock(),
        )
        for name in AgentSpawner._RECYCLE_CRITICAL_DEPS:
            assert getattr(agent, name, None) is not None, (
                f"{name!r} is not an attribute a wired agent actually carries, "
                f"so the recycle guard can never fire for it"
            )

    def test_a_renamed_dependency_would_be_caught(self):
        """The guard reads attributes by name. If nothing ties those names to
        the real class, a rename leaves a guard that always passes."""
        agent = PageReaderAgent(agent_id="probe2", pool="readers")
        for name in AgentSpawner._RECYCLE_CRITICAL_DEPS:
            assert hasattr(agent, name), (
                f"{name!r} does not exist on the agent at all"
            )
