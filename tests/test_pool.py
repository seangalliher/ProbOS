"""Tests for ResourcePool."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.substrate.agent import BaseAgent
from probos.substrate.pool import ResourcePool
from probos.types import AgentState, CapabilityDescriptor


class PoolAgent(BaseAgent):
    agent_type = "pool_test"
    default_capabilities = [CapabilityDescriptor(can="pool_test")]

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return None

    async def decide(self, observation: Any) -> Any:
        return None

    async def act(self, plan: Any) -> Any:
        return None

    async def report(self, result: Any) -> dict[str, Any]:
        return {}


class FailingStartPoolAgent(PoolAgent):
    agent_type = "failing_pool_test"

    async def start(self) -> None:
        raise RuntimeError("agent start failed")


class FailingStartAndStopPoolAgent(FailingStartPoolAgent):
    agent_type = "failing_start_stop_pool_test"

    async def stop(self) -> None:
        raise RuntimeError("agent stop failed")


class TestResourcePool:
    @pytest.mark.asyncio
    async def test_pool_starts_at_target_size(self, spawner, registry, pool_config):
        spawner.register_template("pool_test", PoolAgent)
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=3,
        )
        await pool.start()
        assert pool.current_size == 3
        assert registry.count == 3
        assert len(pool.healthy_agents) == 3
        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_stop_cleans_up(self, spawner, registry, pool_config):
        spawner.register_template("pool_test", PoolAgent)
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=2,
        )
        await pool.start()
        assert registry.count == 2
        await pool.stop()
        assert pool.current_size == 0
        assert registry.count == 0

    @pytest.mark.asyncio
    async def test_pool_recovers_degraded_agents(self, spawner, registry, pool_config):
        spawner.register_template("pool_test", PoolAgent)
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=3,
        )
        await pool.start()

        # Degrade one agent
        agents = registry.get_by_pool("test_pool")
        victim = agents[0]
        for _ in range(30):
            victim.update_confidence(False)
        assert victim.state == AgentState.DEGRADED

        # Health check should recycle and respawn
        health = await pool.check_health()
        assert health["degraded"] >= 1
        assert pool.current_size == 3  # Back to target
        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_info(self, spawner, registry, pool_config):
        spawner.register_template("pool_test", PoolAgent)
        pool = ResourcePool(
            name="info_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=2,
        )
        await pool.start()

        info = pool.info()
        assert info["name"] == "info_pool"
        assert info["target_size"] == 2
        assert info["current_size"] == 2
        assert len(info["agents"]) == 2
        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_remove_unwires_before_registry_removal(
        self,
        spawner,
        registry,
        pool_config,
    ):
        spawner.register_template("pool_test", PoolAgent)
        removing = AsyncMock()
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=3,
            on_agent_removing=removing,
        )
        await pool.start()

        removed_id = await pool.remove_agent()

        assert removed_id is not None
        removing.assert_awaited_once_with(removed_id)
        assert registry.get(removed_id) is None
        await pool.stop()

    @pytest.mark.asyncio
    async def test_dynamic_spawn_wires_once_and_stop_unwires_all(
        self,
        spawner,
        registry,
        pool_config,
    ):
        spawner.register_template("pool_test", PoolAgent)
        spawned = AsyncMock()
        removing = AsyncMock()
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=2,
            on_agent_spawned=spawned,
            on_agent_removing=removing,
        )
        await pool.start()
        initial_ids = set(pool.get_agent_ids())

        # runtime.create_pool wires initial members after start(); the callback
        # is for later dynamic births and must not double-wire the initial set.
        spawned.assert_not_awaited()
        new_id = await pool.add_agent()
        assert new_id is not None
        spawned.assert_awaited_once()
        assert spawned.await_args.args[0].id == new_id

        await pool.stop()

        removed_ids = {call.args[0] for call in removing.await_args_list}
        assert removed_ids == initial_ids | {new_id}

    @pytest.mark.asyncio
    async def test_check_health_recycling_unwires_and_unregisters_before_respawn(
        self,
        spawner,
        registry,
        pool_config,
    ):
        spawner.register_template("pool_test", PoolAgent)
        spawned = AsyncMock()
        removing = AsyncMock()
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=2,
            on_agent_spawned=spawned,
            on_agent_removing=removing,
        )
        await pool.start()
        old_id = pool.get_agent_ids()[0]
        old_agent = registry.get(old_id)
        assert old_agent is not None
        await old_agent.stop()

        health = await pool.check_health()

        assert health["dead"] == 1
        removing.assert_any_await(old_id)
        assert registry.get(old_id) is None
        assert old_id not in pool.get_agent_ids()
        assert pool.current_size == 2
        spawned.assert_awaited_once()
        await pool.stop()

    @pytest.mark.asyncio
    async def test_removal_callback_failure_preserves_pool_registry_invariants(
        self,
        spawner,
        registry,
        pool_config,
    ):
        spawner.register_template("pool_test", PoolAgent)
        removing = AsyncMock(side_effect=RuntimeError("unwire failed"))
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=3,
            on_agent_removing=removing,
        )
        await pool.start()
        before = pool.get_agent_ids()

        with pytest.raises(RuntimeError, match="unwire failed"):
            await pool.remove_agent()

        assert pool.get_agent_ids() == before
        assert all(registry.get(agent_id) is not None for agent_id in before)
        pool._on_agent_removing = None
        await pool.stop()

    @pytest.mark.asyncio
    async def test_dynamic_wiring_failure_rolls_back_registry_and_pool(
        self,
        spawner,
        registry,
        pool_config,
    ):
        spawner.register_template("pool_test", PoolAgent)
        spawned = AsyncMock(side_effect=RuntimeError("wire failed"))
        removing = AsyncMock()
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=2,
            on_agent_spawned=spawned,
            on_agent_removing=removing,
        )
        await pool.start()
        before_ids = pool.get_agent_ids()
        before_registry_count = registry.count

        with pytest.raises(RuntimeError, match="wire failed"):
            await pool.add_agent()

        assert pool.get_agent_ids() == before_ids
        assert registry.count == before_registry_count
        removing.assert_awaited_once()
        pool._on_agent_spawned = None
        await pool.stop()

    @pytest.mark.asyncio
    async def test_removal_cancellation_completes_before_propagating(
        self,
        spawner,
        registry,
        pool_config,
    ):
        spawner.register_template("pool_test", PoolAgent)
        removal_started = asyncio.Event()
        removal_release = asyncio.Event()

        async def removing(_agent_id: str) -> None:
            removal_started.set()
            await removal_release.wait()

        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=3,
            on_agent_removing=removing,
        )
        await pool.start()
        removed_id = pool.get_agent_ids()[-1]

        removal = asyncio.create_task(pool.remove_agent())
        await removal_started.wait()
        removal.cancel()
        removal_release.set()

        with pytest.raises(asyncio.CancelledError):
            await removal

        assert removed_id not in pool.get_agent_ids()
        assert registry.get(removed_id) is None
        pool._on_agent_removing = None
        await pool.stop()

    @pytest.mark.asyncio
    async def test_spawner_start_failure_unregisters_partial_agent(
        self,
        spawner,
        registry,
    ):
        spawner.register_template("failing_pool_test", FailingStartPoolAgent)

        with pytest.raises(RuntimeError, match="agent start failed"):
            await spawner.spawn("failing_pool_test", "failed_pool")

        assert registry.get_by_pool("failed_pool") == []

    @pytest.mark.asyncio
    async def test_spawner_failed_start_and_stop_retains_registry_owner(
        self,
        spawner,
        registry,
    ):
        spawner.register_template(
            "failing_start_stop_pool_test",
            FailingStartAndStopPoolAgent,
        )

        with pytest.raises(RuntimeError, match="agent start failed"):
            await spawner.spawn(
                "failing_start_stop_pool_test",
                "failed_pool",
            )

        retained = registry.get_by_pool("failed_pool")
        assert len(retained) == 1
        assert retained[0].agent_type == "failing_start_stop_pool_test"
        await registry.unregister(retained[0].id)

    @pytest.mark.asyncio
    async def test_stop_does_not_deadlock_with_queued_health_transition(
        self,
        spawner,
        registry,
        pool_config,
    ):
        spawner.register_template("pool_test", PoolAgent)
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=2,
        )
        await pool.start()
        original_health_task = pool._health_task
        assert original_health_task is not None
        original_health_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await original_health_task

        await pool._lifecycle_lock.acquire()
        queued_health = asyncio.create_task(pool.check_health())
        pool._health_task = queued_health
        await asyncio.sleep(0)
        stop_task = asyncio.create_task(pool.stop())
        await asyncio.sleep(0)

        assert stop_task.done() is False
        pool._lifecycle_lock.release()
        await asyncio.wait_for(stop_task, timeout=2.0)

        assert queued_health.done()
        assert pool.current_size == 0
        assert registry.count == 0

    @pytest.mark.asyncio
    async def test_concurrent_health_checks_recycle_degraded_agent_once(
        self,
        spawner,
        registry,
        pool_config,
    ):
        spawner.register_template("pool_test", PoolAgent)
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=2,
        )
        await pool.start()
        victim_id = pool.get_agent_ids()[0]
        victim = registry.get(victim_id)
        assert victim is not None
        victim.state = AgentState.DEGRADED
        recycle_started = asyncio.Event()
        recycle_release = asyncio.Event()
        original_recycle = spawner.recycle
        recycle_count = 0

        async def delayed_recycle(*args: Any, **kwargs: Any):
            nonlocal recycle_count
            recycle_count += 1
            recycle_started.set()
            await recycle_release.wait()
            return await original_recycle(*args, **kwargs)

        spawner.recycle = delayed_recycle  # type: ignore[method-assign]
        first = asyncio.create_task(pool.check_health())
        await recycle_started.wait()
        second = asyncio.create_task(pool.check_health())
        await asyncio.sleep(0)
        recycle_release.set()
        await asyncio.gather(first, second)

        assert recycle_count == 1
        assert registry.get(victim_id) is not None
        assert pool.get_agent_ids().count(victim_id) == 1
        await pool.stop()

    @pytest.mark.asyncio
    async def test_dynamic_wire_and_unwire_failure_retains_owner(
        self,
        spawner,
        registry,
        pool_config,
    ):
        spawner.register_template("pool_test", PoolAgent)
        spawned = AsyncMock(side_effect=RuntimeError("wire failed"))
        removing = AsyncMock(side_effect=TimeoutError("unwire failed"))
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=2,
            on_agent_spawned=spawned,
            on_agent_removing=removing,
        )
        await pool.start()
        before = set(pool.get_agent_ids())

        with pytest.raises(RuntimeError, match="wire failed"):
            await pool.add_agent()

        retained = set(pool.get_agent_ids()) - before
        assert len(retained) == 1
        assert registry.get(next(iter(retained))) is not None
        pool._on_agent_spawned = None
        pool._on_agent_removing = None
        await pool.stop()

    @pytest.mark.asyncio
    async def test_agent_stop_failure_restores_wiring_and_retains_owner(
        self,
        spawner,
        registry,
        pool_config,
    ):
        spawner.register_template("pool_test", PoolAgent)
        spawned = AsyncMock()
        removing = AsyncMock()
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=3,
            on_agent_spawned=spawned,
            on_agent_removing=removing,
        )
        await pool.start()
        victim_id = pool.get_agent_ids()[-1]
        victim = registry.get(victim_id)
        assert victim is not None
        original_stop = victim.stop
        victim.stop = AsyncMock(side_effect=RuntimeError("stop failed"))

        with pytest.raises(RuntimeError, match="stop failed"):
            await pool.remove_agent()

        assert victim_id in pool.get_agent_ids()
        assert registry.get(victim_id) is victim
        removing.assert_awaited_once_with(victim_id)
        spawned.assert_awaited_once_with(victim)
        victim.stop = original_stop
        pool._on_agent_spawned = None
        pool._on_agent_removing = None
        await pool.stop()

    @pytest.mark.asyncio
    async def test_recycled_wire_and_unwire_failure_retains_replacement_owner(
        self,
        spawner,
        registry,
        pool_config,
    ):
        spawner.register_template("pool_test", PoolAgent)
        spawned = AsyncMock(side_effect=RuntimeError("replacement wire failed"))
        removing = AsyncMock(
            side_effect=[None, TimeoutError("replacement unwire failed")]
        )
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=2,
            on_agent_spawned=spawned,
            on_agent_removing=removing,
        )
        await pool.start()
        victim_id = pool.get_agent_ids()[0]
        old_agent = registry.get(victim_id)
        assert old_agent is not None
        old_agent.state = AgentState.DEGRADED

        # BF-846: this asserted the wire failure PROPAGATED out of
        # `check_health`. That contract is gone -- it is what stopped a failing
        # pass reaching its own refill step. The invariants this test exists to
        # protect (the replacement is retained and owned, the rollback ran) are
        # unchanged; only the way the failure is reported has moved, from a
        # raise to `status["recycle_failures"]`.
        status = await pool.check_health()
        assert status["recycle_failures"] == 1, status

        replacement = registry.get(victim_id)
        assert replacement is not None
        assert replacement is not old_agent
        assert victim_id in pool.get_agent_ids()
        assert removing.await_count == 2
        pool._on_agent_spawned = None
        pool._on_agent_removing = None
        await pool.stop()
