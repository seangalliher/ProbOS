"""BF-846 (#1316): `check_health` contains a member's failure and still refills.

BF-824 shipped only the loop boundary. The second half -- containing failures
per MEMBER so a failing pass reaches its own refill step -- needed
`check_health`'s public raise-contract migrated, which is what this closes.

Measured against real `ResourcePool` / `AgentSpawner` / `AgentRegistry`, before
and after, each with a control that behaves differently::

    BEFORE  RECYCLE FAILS  raised=RuntimeError  size=1/2  spawns=0
            RECYCLE OK     raised=None          size=2/2  spawns=1
    AFTER   RECYCLE FAILS  raised=None          size=2/2  spawns=1
                           status={'recycle_failures': 1}

One correction to the issue, recorded rather than quietly fixed: it reports the
Surgeon answering ``{'success': True}`` over a still-degraded member under the
CURRENT code. Driving the real `SurgeonAgent.act` shows the opposite -- today
the raise reaches its own ``except Exception`` and it answers
``{'success': False, 'error': 'recycle refused'}``. The false success is what
CONTAINMENT would have introduced, which is exactly why the issue calls the
raise-contract a blocker. The migration therefore has to carry that property
across, and `test_the_surgeon_does_not_report_success_over_an_unremediated_pool`
is what holds it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.agents.medical.surgeon import SurgeonAgent
from probos.config import PoolConfig
from probos.substrate.pool import ResourcePool
from probos.types import AgentState


# ---------------------------------------------------------------------------
# Doubles -- real ResourcePool, minimal collaborators
# ---------------------------------------------------------------------------


class _Agent:
    def __init__(self, aid: str, state: Any = AgentState.ACTIVE) -> None:
        self.id = aid
        self.state = state

    async def stop(self) -> None:
        return None


class _Registry:
    def __init__(self) -> None:
        self.agents: dict[str, _Agent] = {}

    def get(self, aid: str) -> Any:
        return self.agents.get(aid)

    async def unregister(self, aid: str) -> None:
        self.agents.pop(aid, None)


class _Spawner:
    def __init__(self, registry: _Registry, *, recycle_fails: bool = False) -> None:
        self.registry = registry
        self.recycle_fails = recycle_fails
        self.spawns = 0
        self.recycles = 0

    async def spawn(self, agent_type: str, pool: str, agent_id: str = "", **kw: Any) -> Any:
        self.spawns += 1
        agent = _Agent(agent_id or f"auto-{self.spawns}")
        self.registry.agents[agent.id] = agent
        return agent

    async def recycle(self, agent_id: str, respawn: bool = True, **kw: Any) -> Any:
        self.recycles += 1
        if self.recycle_fails:
            raise RuntimeError("recycle refused")
        agent = _Agent(agent_id)
        self.registry.agents[agent_id] = agent
        return agent


def _degraded_pool(
    *, recycle_fails: bool, target: int = 2, **pool_kw: Any
) -> tuple[ResourcePool, _Registry, _Spawner]:
    registry = _Registry()
    spawner = _Spawner(registry, recycle_fails=recycle_fails)
    pool = ResourcePool(
        "p", "worker", spawner, registry, PoolConfig(), target_size=target, **pool_kw,
    )
    registry.agents["a"] = _Agent("a", AgentState.DEGRADED)
    pool._agent_ids = ["a"]
    return pool, registry, spawner


# ---------------------------------------------------------------------------
# 1. A failing pass reaches its refill step
# ---------------------------------------------------------------------------


async def test_a_failing_recycle_no_longer_blocks_the_refill_step() -> None:
    # Arrange: one short, and the survivor cannot be recycled.
    pool, _registry, spawner = _degraded_pool(recycle_fails=True)

    # Act
    status = await pool.check_health()

    # Assert: the pool holds its size WHILE the member keeps failing. Before
    # BF-846 the exception escaped ahead of refill and the pool stayed at 1.
    assert len(pool._agent_ids) == pool.target_size
    assert spawner.spawns == 1
    assert status["recycle_failures"] == 1, status


async def test_a_clean_pass_refills_and_reports_no_failure() -> None:
    """Control. Without it, a pool that never recycled anything would pass."""
    # Arrange
    pool, registry, spawner = _degraded_pool(recycle_fails=False)

    # Act
    status = await pool.check_health()

    # Assert
    assert len(pool._agent_ids) == pool.target_size
    assert status["recycle_failures"] == 0, status
    assert registry.agents["a"].state == AgentState.ACTIVE


async def test_cancellation_still_ends_a_pass() -> None:
    """The containment must not swallow cancellation -- shutdown depends on it."""
    # Arrange
    pool, _registry, spawner = _degraded_pool(recycle_fails=False)

    async def _cancel(*_a: Any, **_k: Any) -> Any:
        raise asyncio.CancelledError()

    spawner.recycle = _cancel  # type: ignore[assignment]

    # Act / Assert
    with pytest.raises(asyncio.CancelledError):
        await pool.check_health()


class _FatalControl(BaseException):
    """Stands in for ``KeyboardInterrupt`` / ``SystemExit`` / ``GeneratorExit``.

    Raising a real ``KeyboardInterrupt`` here aborts the whole pytest session,
    so it cannot be used to test this boundary. What the boundary actually
    keys on is "not an ``Exception``", and this is exactly that.
    """


async def test_a_fatal_control_exception_is_not_contained() -> None:
    """Containment is scoped to ``Exception``.

    A contained failure continues into the refill step, which SPAWNS. Letting
    a shutdown signal through that is the one way "keep going" makes things
    strictly worse. Measured before the repair: a ``BaseException`` and a
    ``BaseExceptionGroup(CancelledError, ...)`` both returned
    ``{'recycle_failures': 1}`` instead of propagating.
    """
    # Arrange
    pool, _registry, spawner = _degraded_pool(recycle_fails=False)

    async def _boom(*_a: Any, **_k: Any) -> Any:
        raise _FatalControl("shutting down")

    spawner.recycle = _boom  # type: ignore[assignment]

    # Act / Assert
    with pytest.raises(_FatalControl):
        await pool.check_health()


async def test_memory_exhaustion_is_not_contained() -> None:
    """``MemoryError`` IS an ``Exception``, so it needs its own re-raise.

    Continuing into refill -- which spawns -- under memory exhaustion is the
    same "keep going makes it worse" case as a shutdown signal.
    """
    # Arrange
    pool, _registry, spawner = _degraded_pool(recycle_fails=False)

    async def _boom(*_a: Any, **_k: Any) -> Any:
        raise MemoryError()

    spawner.recycle = _boom  # type: ignore[assignment]

    # Act / Assert
    with pytest.raises(MemoryError):
        await pool.check_health()


async def test_a_group_carrying_a_cancellation_is_not_contained() -> None:
    """A ``BaseExceptionGroup`` holding a cancellation is not an ``Exception``,
    so it propagates by construction. Pinned, because containing
    ``BaseException`` let exactly this case through into refill."""
    # Arrange
    pool, _registry, spawner = _degraded_pool(recycle_fails=False)

    async def _boom(*_a: Any, **_k: Any) -> Any:
        raise BaseExceptionGroup(
            "shutdown", [asyncio.CancelledError(), RuntimeError("x")],
        )

    spawner.recycle = _boom  # type: ignore[assignment]

    # Act / Assert
    with pytest.raises(BaseExceptionGroup):
        await pool.check_health()


async def test_an_ordinary_exception_group_is_contained() -> None:
    """Control for the test above: a group of ordinary exceptions IS an
    ``Exception`` and must still be contained, or the boundary would be a
    blanket ban on groups rather than on fatal control flow."""
    # Arrange
    pool, _registry, spawner = _degraded_pool(recycle_fails=False)

    async def _boom(*_a: Any, **_k: Any) -> Any:
        raise ExceptionGroup("two problems", [RuntimeError("a"), ValueError("b")])

    spawner.recycle = _boom  # type: ignore[assignment]

    # Act
    status = await pool.check_health()

    # Assert
    assert status["recycle_failures"] == 1, status
    assert len(pool._agent_ids) == pool.target_size


async def test_an_exception_that_cannot_be_rendered_is_still_contained() -> None:
    """``str(exc)`` is arbitrary caller code.

    Rendering it inside the containment let a failing ``__str__`` propagate and
    leave the pool short -- recreating the very defect this issue removes.
    """
    # Arrange
    class _Unprintable(RuntimeError):
        def __str__(self) -> str:
            raise RuntimeError("str exploded")

    pool, _registry, spawner = _degraded_pool(recycle_fails=False)

    async def _boom(*_a: Any, **_k: Any) -> Any:
        raise _Unprintable()

    spawner.recycle = _boom  # type: ignore[assignment]

    # Act
    status = await pool.check_health()

    # Assert
    assert status["recycle_failures"] == 1, status
    assert len(pool._agent_ids) == pool.target_size


async def test_a_failure_of_the_pass_itself_still_propagates() -> None:
    """Only per-MEMBER recycle failures are contained.

    A spawn that fails during refill is a failure of the pass, not of one
    member, and must still reach the caller -- otherwise `check_health` would
    report a pool it never refilled.
    """
    # Arrange
    pool, _registry, spawner = _degraded_pool(recycle_fails=False)

    async def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("spawn refused")

    spawner.spawn = _boom  # type: ignore[assignment]

    # Act / Assert
    with pytest.raises(RuntimeError, match="spawn refused"):
        await pool.check_health()


# ---------------------------------------------------------------------------
# 2. The Surgeon must not report success over a pool it failed to remediate
# ---------------------------------------------------------------------------


async def _surgeon_verdict(pool: ResourcePool) -> dict[str, Any]:
    runtime = MagicMock()
    runtime.pools = {"p": pool}
    surgeon = object.__new__(SurgeonAgent)
    surgeon._runtime = runtime

    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    surgeon._log_remediation = _noop  # type: ignore[assignment]
    return await surgeon.act({
        "action": "execute",
        "llm_output": json.dumps({"action": "recycle_agent", "target": "p"}),
    })


async def test_the_surgeon_does_not_report_success_over_an_unremediated_pool() -> None:
    """The property the migration had to carry across.

    Under the old raise-contract the Surgeon's own ``except Exception`` caught
    the failure and reported it. With the raise gone, "the call returned" is no
    longer evidence of anything, so it has to READ the status -- otherwise the
    ship closes a fault that is still open.
    """
    # Arrange
    pool, registry, _spawner = _degraded_pool(recycle_fails=True, target=1)

    # Act
    verdict = await _surgeon_verdict(pool)

    # Assert
    assert verdict["success"] is False, verdict
    assert "could not be recycled" in verdict["error"]
    assert registry.agents["a"].state == AgentState.DEGRADED


async def test_the_surgeon_still_reports_success_on_a_real_remediation() -> None:
    """Control. A Surgeon that always failed would pass the test above."""
    # Arrange
    pool, registry, _spawner = _degraded_pool(recycle_fails=False, target=1)

    # Act
    verdict = await _surgeon_verdict(pool)

    # Assert
    assert verdict["success"] is True, verdict
    assert registry.agents["a"].state == AgentState.ACTIVE


# ---------------------------------------------------------------------------
# 3. The ACTIVE-replacement path is retried, not dropped
# ---------------------------------------------------------------------------


def _rollback_pool() -> tuple[ResourcePool, _Registry, _Spawner]:
    """Wire fails, and the rollback's unwire fails too.

    That is the one path where the failure does NOT leave the member degraded:
    the replacement is retained and ACTIVE, so an ordinary scan would never
    look at it again and the failure becomes a one-pass signal.
    """
    wires = {"n": 0}

    async def _wire(_agent: Any) -> None:
        wires["n"] += 1
        raise RuntimeError("wire failed")

    async def _unwire(_aid: str) -> None:
        if wires["n"] >= 1:
            raise TimeoutError("unwire failed")

    return _degraded_pool(
        recycle_fails=False, target=1,
        on_agent_spawned=_wire, on_agent_removing=_unwire,
    )


async def test_a_retained_active_replacement_is_retried_on_the_next_pass() -> None:
    # Arrange
    pool, registry, _spawner = _rollback_pool()

    # Act
    first = await pool.check_health()

    # Assert the premise: the member really is left ACTIVE, so nothing about
    # its state would make a scan revisit it.
    assert first["recycle_failures"] == 1, first
    assert registry.agents["a"].state == AgentState.ACTIVE
    assert pool._recycle_retry == {"a"}

    # Act: a second pass, which the scan alone would treat as healthy.
    second = await pool.check_health()

    # Assert: it was retried. `healthy: 1` shows the SCAN did not queue it, so
    # the retry set is the only thing that could have produced the failure.
    assert second["healthy"] == 1, second
    assert second["degraded"] == 0, second
    assert second["recycle_failures"] == 1, second


async def test_a_healthy_member_is_not_retried() -> None:
    """Control for the retry set: it must not re-recycle a working member."""
    # Arrange
    pool, _registry, spawner = _degraded_pool(recycle_fails=False, target=1)
    await pool.check_health()
    recycles_after_first = spawner.recycles

    # Act
    second = await pool.check_health()

    # Assert
    assert second["recycle_failures"] == 0, second
    assert spawner.recycles == recycles_after_first
    assert pool._recycle_retry == set()


# ---------------------------------------------------------------------------
# 4. A repeated failure does not flood the log
# ---------------------------------------------------------------------------


async def test_repeated_identical_failures_emit_one_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Measured before the fix: 1,054 exception records in 50 ms at
    ``health_check_interval_seconds=0.0``, and one traceback every five seconds
    per failing member forever at the default."""
    # Arrange
    pool, _registry, _spawner = _degraded_pool(recycle_fails=True, target=1)

    # Act
    with caplog.at_level(logging.DEBUG, logger="probos.substrate.pool"):
        for _ in range(200):
            await pool.check_health()

    # Assert
    ours = [r for r in caplog.records if r.name == "probos.substrate.pool"]
    tracebacks = [r for r in ours if r.exc_info]
    assert len(tracebacks) == 1, (
        f"expected exactly one traceback for 200 identical failures, got "
        f"{len(tracebacks)}"
    )
    errors = [r for r in ours if r.levelno >= logging.ERROR]
    assert len(errors) == 1, f"expected one ERROR record, got {len(errors)}"
    # Scope, stated rather than implied: the per-pass status INFO is NOT
    # throttled here. It fires once per pass whenever a member is degraded,
    # which predates BF-846 and is the pool's ordinary status cadence.


async def test_a_changed_failure_is_reported_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Control: the throttle keys on the SIGNATURE, so a different failure must
    not be suppressed behind the first one."""
    # Arrange
    pool, _registry, spawner = _degraded_pool(recycle_fails=True, target=1)

    with caplog.at_level(logging.DEBUG, logger="probos.substrate.pool"):
        await pool.check_health()

        async def _other(*_a: Any, **_k: Any) -> Any:
            raise ValueError("a different failure")

        spawner.recycle = _other  # type: ignore[assignment]

        # Act
        await pool.check_health()

    # Assert
    tracebacks = [
        r for r in caplog.records
        if r.name == "probos.substrate.pool" and r.exc_info
    ]
    assert len(tracebacks) == 2, (
        f"a NEW failure signature must carry its own traceback; got "
        f"{len(tracebacks)}"
    )


async def test_the_same_message_from_a_different_stage_is_not_suppressed() -> None:
    """The fingerprint carries the failing frame, not just class and text.

    ``_recycle_registered_agent_inner`` can fail at several stages -- an
    initial unwire, a replacement start, a rollback unwire -- and two of them
    can raise the same class with the same message. Coalescing those hides the
    second, genuinely different, problem.
    """
    # Arrange
    pool, _registry, spawner = _degraded_pool(recycle_fails=False, target=1)

    async def _fail_in_recycle(*_a: Any, **_k: Any) -> Any:
        raise TimeoutError("nats timeout")

    async def _fail_in_unwire(*_a: Any, **_k: Any) -> Any:
        raise TimeoutError("nats timeout")

    spawner.recycle = _fail_in_recycle  # type: ignore[assignment]
    await pool.check_health()

    # Act: same class, same message, different stage.
    spawner.recycle = _degraded_pool(recycle_fails=False)[2].recycle  # a working one
    pool._on_agent_removing = _fail_in_unwire
    await pool.check_health()

    # Assert
    signatures = {sig for _aid, sig in pool._recycle_failure_log}
    assert len(signatures) == 2, (
        f"identical text from two stages collapsed into one signature: {signatures}"
    )


async def test_alternating_failures_are_each_throttled() -> None:
    """The throttle is keyed by ``(member, signature)``.

    Remembering only the LAST signature made two failures that alternate each
    look new every time, so neither was ever throttled -- measured, 6 full
    tracebacks in 6 passes.
    """
    # Arrange
    pool, _registry, spawner = _degraded_pool(recycle_fails=False, target=1)
    flip = {"n": 0}

    async def _alternate(*_a: Any, **_k: Any) -> Any:
        flip["n"] += 1
        raise (RuntimeError("A") if flip["n"] % 2 else ValueError("B"))

    spawner.recycle = _alternate  # type: ignore[assignment]

    # Act
    for _ in range(20):
        await pool.check_health()

    # Assert: two signatures, so exactly two tracebacks -- not twenty.
    assert len(pool._recycle_failure_log) == 2, pool._recycle_failure_log


async def test_throttle_state_does_not_outlive_the_member() -> None:
    """Entries were dropped only on a SUCCESSFUL recycle, so every member that
    failed and then left the pool -- the ordinary outcome when a replacement
    cannot be started -- left one behind forever."""
    # Arrange: recycle removes the member from the pool, then fails.
    pool, registry, spawner = _degraded_pool(recycle_fails=False, target=1)

    async def _drop_then_fail(agent_id: str, **_k: Any) -> Any:
        registry.agents.pop(agent_id, None)
        raise RuntimeError("replacement could not start")

    spawner.recycle = _drop_then_fail  # type: ignore[assignment]

    # Act
    for _ in range(12):
        status = await pool.check_health()
        # Re-degrade whatever the refill produced, so the next pass fails too.
        for aid in pool._agent_ids:
            member = registry.agents.get(aid)
            if member is not None:
                member.state = AgentState.DEGRADED

    # Assert: premise first -- the failures really happened.
    assert status["recycle_failures"] >= 1, status
    stale = [k for k in pool._recycle_failure_log if k[0] not in set(pool._agent_ids)]
    assert stale == [], f"throttle state leaked for departed members: {stale}"


async def test_restarting_a_pool_does_not_inherit_a_previous_run_s_retry() -> None:
    """Transient recovery state belongs to a RUN, not to the object.

    Left over a restart, a retry entry made a fresh member with a reused
    predetermined id get recycled once for a previous run's failure.
    """
    # Arrange
    pool, _registry, _spawner = _rollback_pool()
    await pool.check_health()
    assert pool._recycle_retry, "the premise failed: nothing was queued for retry"

    # Act
    pool._on_agent_spawned = None
    pool._on_agent_removing = None
    await pool.start()

    # Assert
    assert pool._recycle_retry == set()
    assert pool._recycle_failure_log == {}
    await pool.stop()


async def test_a_non_positive_health_interval_is_rejected() -> None:
    """``0.0`` turned the loop into a busy loop; a negative value is an
    immediate ``wait_for`` timeout with the same effect; ``inf`` silently
    disables health checking; a denormal reproduces the busy loop while
    satisfying a bare "greater than zero"."""
    for bad in (0.0, -1.0, 5e-324, float("inf"), float("nan")):
        with pytest.raises(Exception):
            PoolConfig(health_check_interval_seconds=bad)

    # Control: the supported values still validate, including the 0.05 the
    # BF-824 loop tests run at.
    for good in (0.05, 1.0, 5.0):
        assert PoolConfig(health_check_interval_seconds=good).health_check_interval_seconds == good


# ---------------------------------------------------------------------------
# 5. The reserved agent_id kwarg cannot be supplied
# ---------------------------------------------------------------------------


def test_a_reserved_agent_id_kwarg_is_rejected_at_construction() -> None:
    """``runtime.py`` forwards arbitrary ``**spawn_kwargs`` publicly, so this
    is reachable. Left alone it collided with the explicit keyword on the first
    health pass: ``TypeError: recycle() got multiple values for argument
    'agent_id'`` -- far from the mistake that caused it."""
    registry = _Registry()
    with pytest.raises(TypeError, match="agent_ids"):
        ResourcePool(
            "p", "worker", _Spawner(registry), registry, PoolConfig(),
            target_size=1, agent_id="fixed",
        )


def test_the_supported_way_to_pin_identities_still_works() -> None:
    """Control: the rejection must name a real alternative, and it must work."""
    registry = _Registry()
    pool = ResourcePool(
        "p", "worker", _Spawner(registry), registry, PoolConfig(),
        target_size=1, agent_ids=["pinned-0"],
    )
    assert pool._predetermined_ids == ["pinned-0"]


def test_ordinary_spawn_kwargs_are_still_forwarded() -> None:
    """Control: only the reserved key is rejected."""
    registry = _Registry()
    pool = ResourcePool(
        "p", "worker", _Spawner(registry), registry, PoolConfig(),
        target_size=1, runtime="rt", llm_client="llm",
    )
    assert pool._spawn_kwargs == {"runtime": "rt", "llm_client": "llm"}
