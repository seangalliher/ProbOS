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
    """BF-846: the residual this test used to pin is CLOSED.

    It previously asserted the pool stayed at 1 while a member could not be
    recycled, and told a future reader to rewrite rather than delete it if that
    residual was ever closed. This is that rewrite.

    The recycle loop still runs before refill, but a member's failure is now
    contained, so the same pass reaches its refill step: the pool holds its
    target size THROUGHOUT the failure instead of only recovering after it
    clears. Measured before BF-846: size 1 with ``spawns=0``.
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

        # Act / Assert: refill happens WHILE the recycle keeps failing.
        assert await _wait_until(lambda: len(pool._agent_ids) >= 2), (
            "the pool never refilled while a member was unrecyclable; the "
            "BF-846 containment is not reaching the refill step"
        )

        # And the failure is still visible in the status, not swallowed.
        status = await pool.check_health()
        assert status["recycle_failures"] >= 1, status

        # Act: clear the failure.
        failing["on"] = False

        # Assert: the MEMBER is remediated, not merely the bookkeeping. An
        # empty failure log alone could mean the state was cleared without a
        # successful recycle, so the pool's actual health leads.
        #
        # Both conditions are POLLED together rather than asserted in sequence:
        # the replacement is registered ACTIVE inside
        # `_recycle_registered_agent_inner`, and its caller clears the log
        # afterwards, so there is an await between them where the health
        # condition holds and the log is not yet clean.
        assert await _wait_until(
            lambda: len(pool._agent_ids) >= 2
            and all(
                (member := registry.get(aid)) is not None
                and member.state != AgentState.DEGRADED
                for aid in pool._agent_ids
            )
            and not pool._recycle_failure_log
        ), "the degraded member was never recycled after the failure cleared"
    finally:
        await pool.stop()


async def test_the_failing_pass_is_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Silence is the property BF-824 exists to remove.

    BF-846 moved the report: the loop no longer sees an exception at all,
    because the failure is contained per member inside ``check_health``. So the
    ERROR now comes from the containment site. A pool that quietly failed to
    recycle forever would be the same invisibility, one level down.
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
            ), "the failing recycle was never reported"
        finally:
            await pool.stop()

    # Assert
    ours = [
        r for r in caplog.records
        if r.name == "probos.substrate.pool" and r.levelno >= logging.ERROR
    ]
    joined = " ".join(r.getMessage() for r in ours)
    assert "p" in joined, "the log must name the pool"
    assert "could not recycle" in joined, (
        "the log must say WHICH failure happened -- a bare 'health check "
        "failed' cannot be told from the pass itself dying"
    )
    assert any(r.exc_info for r in ours), (
        "the first occurrence must carry its traceback; without one the "
        "operator cannot see why the recycle failed"
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


async def test_check_health_reports_a_member_failure_in_its_status() -> None:
    """BF-846 migrated this contract; the property it guards is unchanged.

    It used to assert `check_health()` PROPAGATED a member's recycle failure,
    which is what stopped a failing pass reaching its refill step. The failure
    must still be knowable to a direct caller -- ``agents/medical/surgeon.py``
    reports remediation success on the strength of it -- so it now travels in
    the returned status instead.
    """
    # Arrange
    registry = AgentRegistry()
    spawner = _spawner(registry)
    _fail_recycle(spawner, {"on": True})
    pool = _pool(registry, spawner, interval=60.0)  # no background interference
    await pool.start()
    try:
        registry.get(pool._agent_ids[0]).state = AgentState.DEGRADED

        # Act
        status = await pool.check_health()

        # Assert
        assert status["recycle_failures"] == 1, status
        assert len(pool._agent_ids) == 2, "the pass must still hold the pool's size"
    finally:
        await pool.stop()


async def test_a_clean_pass_reports_no_member_failure() -> None:
    """Control. Without it, a status that always reported a failure would pass
    the test above."""
    # Arrange
    registry = AgentRegistry()
    spawner = _spawner(registry)
    pool = _pool(registry, spawner, interval=60.0)
    await pool.start()
    try:
        registry.get(pool._agent_ids[0]).state = AgentState.DEGRADED

        # Act
        status = await pool.check_health()

        # Assert
        assert status["recycle_failures"] == 0, status
    finally:
        await pool.stop()
