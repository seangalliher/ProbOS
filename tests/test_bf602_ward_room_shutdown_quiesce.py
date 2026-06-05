"""BF-602: Ward Room routing must quiesce on shutdown.

Root cause: ``WardRoomRouter.route_event_coalesced`` scheduled ``_fire()`` via
``loop.call_later`` + a bare ``asyncio.create_task`` (fire-and-forget, no
reference held). During shutdown the explicit dream_cycle makes agents post to
the Ward Room; each post schedules a ~200ms coalesce timer. If the ward_room DB
connection is torn down before the timer fires, ``route_event`` crashes inside
aiosqlite with ``ValueError("no active connection")`` as an unretrieved task
exception ("Task exception was never retrieved").

Fix: a ``_stopping`` flag + ``stop()`` that cancels pending coalesce timers and
in-flight ``_fire`` tasks, guards on ``route_event``/``route_event_coalesced``,
and a held task reference with log-and-degrade in ``_fire``.
"""

import asyncio
import inspect

import pytest
from unittest.mock import AsyncMock

from probos.ward_room_router import WardRoomRouter


def _make_router(*, coalesce_ms: int = 200) -> WardRoomRouter:
    """Construct a bare router with only the attributes the routing/shutdown
    paths touch (mirrors the AD-616 coalescing unit tests)."""
    router = WardRoomRouter.__new__(WardRoomRouter)
    router._coalesce_timers = {}
    router._coalesce_ms = coalesce_ms
    router._coalesce_fire_tasks = set()
    router._stopping = False
    router._ward_room = object()  # sentinel — must NOT be touched when stopping
    return router


class TestStopTeardown:
    """BF-602: stop() quiesces routing and cancels pending work."""

    def test_stop_method_exists_and_is_sync(self):
        assert hasattr(WardRoomRouter, "stop")
        assert not asyncio.iscoroutinefunction(WardRoomRouter.stop)

    def test_stop_sets_stopping_flag(self):
        router = _make_router()
        assert router._stopping is False
        router.stop()
        assert router._stopping is True

    def test_stop_is_idempotent(self):
        router = _make_router()
        router.stop()
        router.stop()  # must not raise
        assert router._stopping is True

    @pytest.mark.asyncio
    async def test_stop_cancels_pending_coalesce_timer(self):
        """A scheduled coalesce timer is cancelled and cleared by stop()."""
        router = _make_router(coalesce_ms=10_000)  # long window so it won't fire
        router.route_event = AsyncMock()

        await router.route_event_coalesced(
            "ward_room_post_created", {"thread_id": "t1"}
        )
        assert "t1" in router._coalesce_timers
        handle = router._coalesce_timers["t1"]

        router.stop()

        assert router._coalesce_timers == {}
        assert handle.cancelled() is True
        # Wait past where the timer *would* have fired — it must not route.
        await asyncio.sleep(0.05)
        router.route_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_cancels_inflight_fire_task(self):
        router = _make_router()

        async def _never() -> None:
            await asyncio.sleep(100)

        task = asyncio.create_task(_never())
        router._coalesce_fire_tasks.add(task)

        router.stop()

        assert router._coalesce_fire_tasks == set()
        await asyncio.sleep(0)  # let cancellation propagate
        assert task.cancelled() is True


class TestRoutingSuppressedWhenStopping:
    """BF-602: no routing into a (possibly closed) ward_room DB after stop()."""

    @pytest.mark.asyncio
    async def test_route_event_noop_when_stopping(self):
        router = _make_router()
        router._stopping = True
        # _ward_room is a bare sentinel; if route_event proceeds it would touch
        # eviction helpers / get_channel and blow up. Early-return proves quiesce.
        await router.route_event("ward_room_post_created", {"thread_id": "t1"})

    @pytest.mark.asyncio
    async def test_route_event_coalesced_noop_when_stopping(self):
        router = _make_router()
        router.route_event = AsyncMock()
        router._stopping = True

        await router.route_event_coalesced(
            "ward_room_post_created", {"thread_id": "t1"}
        )

        router.route_event.assert_not_called()
        assert router._coalesce_timers == {}

    @pytest.mark.asyncio
    async def test_coalesced_post_schedules_when_not_stopping(self):
        """Sanity: normal path still schedules a coalesce timer."""
        router = _make_router(coalesce_ms=10_000)
        router.route_event = AsyncMock()
        await router.route_event_coalesced(
            "ward_room_post_created", {"thread_id": "t1"}
        )
        assert "t1" in router._coalesce_timers
        router.stop()  # cleanup


class TestFireExceptionHandled:
    """BF-602: a late _fire() must not become an unretrieved task exception."""

    @pytest.mark.asyncio
    async def test_fire_after_db_close_logs_and_degrades(self, caplog):
        """Simulate the production crash: the timer fires but routing raises
        'no active connection'. The exception must be caught (retrieved), not
        surfaced as 'Task exception was never retrieved'."""
        router = _make_router(coalesce_ms=10)
        router.route_event = AsyncMock(
            side_effect=ValueError("no active connection")
        )

        with caplog.at_level("WARNING"):
            await router.route_event_coalesced(
                "ward_room_post_created", {"thread_id": "t1"}
            )
            # Wait for the coalesce window + the _fire task to run and finish.
            await asyncio.sleep(0.1)

        # route_event was attempted, raised, and the error was degraded.
        router.route_event.assert_awaited_once()
        assert any("BF-602" in r.message for r in caplog.records)
        # The done-callback drained the task reference.
        assert router._coalesce_fire_tasks == set()

    @pytest.mark.asyncio
    async def test_fire_task_reference_held_during_flight(self):
        """The _fire task is tracked (not fire-and-forget) while in flight."""
        router = _make_router(coalesce_ms=10)

        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow(*_a, **_k) -> None:
            started.set()
            await release.wait()

        router.route_event = _slow
        await router.route_event_coalesced(
            "ward_room_post_created", {"thread_id": "t1"}
        )
        await asyncio.wait_for(started.wait(), timeout=1.0)

        # While route_event is awaiting, the task reference is held.
        assert len(router._coalesce_fire_tasks) == 1

        release.set()
        await asyncio.sleep(0.02)
        assert router._coalesce_fire_tasks == set()


class TestShutdownWiring:
    """BF-602: shutdown.py quiesces the router before consolidation."""

    def test_shutdown_calls_ward_room_router_stop(self):
        from probos.startup import shutdown as shutdown_mod

        src = inspect.getsource(shutdown_mod)
        assert "ward_room_router" in src
        assert "BF-602" in src
        assert ".stop()" in src
