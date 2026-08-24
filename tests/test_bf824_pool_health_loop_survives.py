"""BF-824: a pool's health loop must survive a failing health pass.

`ResourcePool._health_loop` called `await self.check_health()` with no
exception boundary, so any exception from a health pass escaped the health
task, which then ended. **Nothing in `src/` restarts a pool health task.**

Measured against the real periodic task before the fix::

    initial size             : 2
    health task done         : True
    health task exception    : RuntimeError: lost dependencies: _runtime
    size after recovery wait : 2
    degraded members left    : 1

The last line is the point. Recycling was made healthy again and the member
stayed degraded forever, because the loop was gone. The pool kept its members,
kept answering, and simply never checked again.

Every test here drives the periodic ``_health_task``. A test that calls
``check_health()`` directly cannot see the loop die, which is why the existing
pool suite never caught this.

**Scope, deliberately narrow, and what it does NOT reach.** The issue also
asked to contain failures per MEMBER inside `check_health`, so a failing pass
still reaches its own refill step. That was implemented, and reverted:
`check_health` is public and callers rely on it RAISING --
`agents/medical/surgeon.py` treats any return as success, and
`test_ad1019c_consensus::test_recycle_delete_failure_does_not_wire_replacement`
asserts the raise. Swallowing per-member is a contract change with its own
consumer migration, filed separately.

So the residual is real and is pinned below: while a member keeps failing to
recycle, the exception still escapes `check_health` before its refill step, and
the pool stays short. What this fix buys is that the LOOP survives, so the pool
recovers by itself the moment the failure clears -- which, before BF-824, it
never could.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from probos.config import PoolConfig
from probos.substrate.agent import BaseAgent
from probos.substrate.pool import ResourcePool
from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.types import AgentState


class _PlainAgent(BaseAgent):
    agent_type = "plain"

    async def perceive(self, intent: Any) -> Any:
        return {}

    async def decide(self, observation: Any) -> Any:
        return {}

    async def act(self, decision: Any) -> Any:
        return {"success": True}

    async def report(self, result: Any) -> Any:
        return result


def _spawner(registry: AgentRegistry) -> AgentSpawner:
    spawner = AgentSpawner(registry)
    spawner.register_template("plain", _PlainAgent)
    return spawner


def _pool(
    registry: AgentRegistry, spawner: AgentSpawner, *, interval: float = 0.05
) -> ResourcePool:
    cfg = PoolConfig(
        default_pool_size=2,
        min_pool_size=1,
        max_pool_size=4,
        health_check_interval_seconds=interval,
    )
    return ResourcePool("p", "plain", spawner, registry, cfg, target_size=2)


def _fail_recycle(spawner: AgentSpawner, flag: dict[str, bool]) -> None:
    """Make `recycle` raise while ``flag['on']``, else delegate to the real one."""
    real = spawner.recycle

    async def flaky(*a: Any, **k: Any) -> Any:
        if flag["on"]:
            raise RuntimeError("lost dependencies: _runtime")
        return await real(*a, **k)

    spawner.recycle = flaky  # type: ignore[assignment]


async def _wait_until(predicate: Any, *, seconds: float = 5.0) -> bool:
    """Poll an observable rather than sleeping a guessed interval.

    A fixed sleep encodes how fast the box is, and the gate runs `-n 16`.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while not predicate():
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.01)
    return True


async def test_the_health_task_survives_a_failing_pass() -> None:
    # Arrange
    registry = AgentRegistry()
    spawner = _spawner(registry)
    _fail_recycle(spawner, {"on": True})
    pool = _pool(registry, spawner)
    await pool.start()
    try:
        assert await _wait_until(lambda: len(pool._agent_ids) == 2)
        registry.get(pool._agent_ids[0]).state = AgentState.DEGRADED

        # Act: let several ticks hit the failing recycle.
        await asyncio.sleep(0.25)

        # Assert
        assert pool._health_task is not None
        assert not pool._health_task.done(), (
            "the health task ended on a failing pass; nothing in src/ restarts "
            "it, so this pool would never check or refill again"
        )
    finally:
        await pool.stop()


async def test_the_pool_recovers_once_the_failure_clears() -> None:
    """The consequence that matters: a dead loop can never recover."""
    # Arrange
    registry = AgentRegistry()
    spawner = _spawner(registry)
    failing = {"on": True}
    _fail_recycle(spawner, failing)
    pool = _pool(registry, spawner)
    await pool.start()
    try:
        assert await _wait_until(lambda: len(pool._agent_ids) == 2)
        registry.get(pool._agent_ids[0]).state = AgentState.DEGRADED
        await asyncio.sleep(0.2)  # fail a few times

        # Act
        failing["on"] = False

        # Assert
        def _no_degraded() -> bool:
            members = [registry.get(i) for i in pool._agent_ids]
            return all(
                m is not None and m.state != AgentState.DEGRADED for m in members
            )

        assert await _wait_until(_no_degraded), (
            "the degraded member was never recycled after recycling recovered"
        )
    finally:
        await pool.stop()


async def test_refill_resumes_once_the_failure_clears() -> None:
    """The honest bound of the narrowed fix.

    The recycle loop runs BEFORE refill, so while a member keeps failing to
    recycle the exception still escapes `check_health` on EVERY pass and refill
    never runs. Measured: a pool held one short with a permanently unrecyclable
    member stayed at 1 rather than refilling to 2.

    What the fix changes is that the LOOP survives, so the moment the failure
    clears the pool recovers by itself. Before BF-824 the health task was gone
    and it never would.

    Containing failures per MEMBER so a failing pass still reaches its own
    refill is the remaining half, and it needs `check_health`'s public
    raise-contract migrated first -- filed separately.
    """
    # Arrange: one short, and the survivor cannot be recycled.
    registry = AgentRegistry()
    spawner = _spawner(registry)
    failing = {"on": True}
    _fail_recycle(spawner, failing)
    pool = _pool(registry, spawner)
    await pool.start()
    try:
        assert await _wait_until(lambda: len(pool._agent_ids) == 2)
        await pool.remove_agent()
        registry.get(pool._agent_ids[0]).state = AgentState.DEGRADED
        assert len(pool._agent_ids) == 1

        # While the failure persists, refill is blocked -- state it rather than
        # imply the fix reaches further than it does.
        await asyncio.sleep(0.25)
        assert len(pool._agent_ids) == 1, (
            "refill unexpectedly ran while the recycle was still failing; the "
            "residual documented here no longer holds and this test should be "
            "rewritten rather than deleted"
        )

        # Act
        failing["on"] = False

        # Assert: the surviving loop recovers the pool without help.
        assert await _wait_until(lambda: len(pool._agent_ids) >= 2), (
            "the pool never refilled after the failure cleared: the health "
            "loop had died"
        )
    finally:
        await pool.stop()


async def test_the_failing_pass_is_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Silence is the property BF-824 exists to remove.

    A loop that survives but says nothing would hide a pool that can never
    recycle -- the same invisibility, one level up.
    """
    # Arrange
    registry = AgentRegistry()
    spawner = _spawner(registry)
    _fail_recycle(spawner, {"on": True})
    pool = _pool(registry, spawner)

    with caplog.at_level(logging.ERROR, logger="probos.substrate.pool"):
        await pool.start()
        try:
            assert await _wait_until(lambda: len(pool._agent_ids) == 2)
            registry.get(pool._agent_ids[0]).state = AgentState.DEGRADED

            # Act
            assert await _wait_until(
                lambda: any(
                    r.name == "probos.substrate.pool" and r.levelno >= logging.ERROR
                    for r in caplog.records
                )
            ), "the failing health pass was never reported"
        finally:
            await pool.stop()

    # Assert
    ours = [
        r for r in caplog.records
        if r.name == "probos.substrate.pool" and r.levelno >= logging.ERROR
    ]
    joined = " ".join(r.getMessage() for r in ours)
    assert "p" in joined, "the log must name the pool"
    assert "survives" in joined, (
        "the log must say the loop continues -- otherwise a reader cannot tell "
        "this from the old permanent death"
    )


async def test_stopping_the_pool_still_ends_the_loop() -> None:
    """`CancelledError` must NOT be swallowed by the new boundary.

    A loop that survives cancellation would hang shutdown -- a worse failure
    than the one being fixed.
    """
    # Arrange
    registry = AgentRegistry()
    spawner = _spawner(registry)
    pool = _pool(registry, spawner)
    await pool.start()
    task = pool._health_task
    assert task is not None

    # Act
    await asyncio.wait_for(pool.stop(), timeout=5.0)

    # Assert
    assert task.done()


async def test_a_healthy_pool_is_untouched() -> None:
    """The counter-case: the boundary must not change the ordinary path."""
    # Arrange
    registry = AgentRegistry()
    spawner = _spawner(registry)
    pool = _pool(registry, spawner)
    await pool.start()
    try:
        assert await _wait_until(lambda: len(pool._agent_ids) == 2)

        # Act
        await asyncio.sleep(0.2)  # several clean ticks

        # Assert
        assert len(pool._agent_ids) == 2
        assert pool._health_task is not None
        assert not pool._health_task.done()
    finally:
        await pool.stop()


async def test_check_health_still_raises_for_direct_callers() -> None:
    """The narrowed scope, pinned.

    `agents/medical/surgeon.py` and `test_ad1019c_consensus` rely on
    `check_health()` propagating. The loop boundary must not have changed that.
    """
    # Arrange
    registry = AgentRegistry()
    spawner = _spawner(registry)
    _fail_recycle(spawner, {"on": True})
    pool = _pool(registry, spawner, interval=60.0)  # no background interference
    await pool.start()
    try:
        registry.get(pool._agent_ids[0]).state = AgentState.DEGRADED

        # Act / Assert
        with pytest.raises(RuntimeError, match="lost dependencies"):
            await pool.check_health()
    finally:
        await pool.stop()
