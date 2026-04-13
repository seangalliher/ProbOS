"""AD-616: Ward Room router hot path optimization — targeted lookups, semaphore, coalescing."""

import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from probos.config import WardRoomConfig
from probos.ward_room.service import WardRoomService


# ---------------------------------------------------------------------------
# Change 1: Channel lookup optimization
# ---------------------------------------------------------------------------


class TestChannelLookupOptimization:
    """AD-616 Change 1: list_channels() replaced with targeted lookups."""

    def test_route_event_uses_get_channel_not_list(self):
        """route_event() must not call list_channels()."""
        from probos.ward_room_router import WardRoomRouter
        src = inspect.getsource(WardRoomRouter.route_event)
        assert "list_channels" not in src

    def test_get_channel_by_department_exists(self):
        """get_channel_by_department() exists on both ChannelManager and WardRoomService."""
        from probos.ward_room.channels import ChannelManager
        assert hasattr(ChannelManager, "get_channel_by_department")
        assert hasattr(WardRoomService, "get_channel_by_department")

    def test_get_channel_by_type_exists(self):
        """get_channel_by_type() exists on both ChannelManager and WardRoomService."""
        from probos.ward_room.channels import ChannelManager
        assert hasattr(ChannelManager, "get_channel_by_type")
        assert hasattr(WardRoomService, "get_channel_by_type")


# ---------------------------------------------------------------------------
# Change 2: Event dispatch semaphore
# ---------------------------------------------------------------------------


class TestEventDispatchSemaphore:
    """AD-616 Change 2: Semaphore in communication.py."""

    def test_semaphore_in_ward_room_emit(self):
        """Semaphore and _bounded_route pattern exist in communication.py."""
        src = open("src/probos/startup/communication.py", encoding="utf-8").read()
        assert "Semaphore" in src
        assert "_bounded_route" in src

    def test_router_concurrency_limit_config(self):
        """router_concurrency_limit field exists on WardRoomConfig with default 10."""
        config = WardRoomConfig()
        assert config.router_concurrency_limit == 10


# ---------------------------------------------------------------------------
# Change 3: Event coalescing
# ---------------------------------------------------------------------------


class TestEventCoalescing:
    """AD-616 Change 3: Backend event coalescing."""

    def test_route_event_coalesced_exists(self):
        """route_event_coalesced() method exists on WardRoomRouter."""
        from probos.ward_room_router import WardRoomRouter
        assert hasattr(WardRoomRouter, "route_event_coalesced")
        assert asyncio.iscoroutinefunction(WardRoomRouter.route_event_coalesced)

    def test_coalesce_ms_config(self):
        """event_coalesce_ms field exists on WardRoomConfig with default 200."""
        config = WardRoomConfig()
        assert config.event_coalesce_ms == 200

    @pytest.mark.asyncio
    async def test_thread_created_not_coalesced(self):
        """ward_room_thread_created events should route immediately, not coalesce."""
        from probos.ward_room_router import WardRoomRouter

        router = WardRoomRouter.__new__(WardRoomRouter)
        router._coalesce_timers = {}
        router._coalesce_ms = 200

        router.route_event = AsyncMock()

        await router.route_event_coalesced(
            "ward_room_thread_created",
            {"thread_id": "t1", "channel_id": "c1"},
        )
        router.route_event.assert_called_once_with(
            "ward_room_thread_created",
            {"thread_id": "t1", "channel_id": "c1"},
        )


# ---------------------------------------------------------------------------
# Change 1 (behavioral): New channel query methods with real DB
# ---------------------------------------------------------------------------


class TestNewChannelQueries:
    """AD-616: get_channel_by_department / get_channel_by_type with real DB."""

    @pytest_asyncio.fixture
    async def ward_room(self, tmp_path):
        """Create a WardRoomService with temp SQLite DB."""
        events = []
        def capture_event(event_type, data):
            events.append({"type": event_type, "data": data})

        svc = WardRoomService(
            db_path=str(tmp_path / "ward_room.db"),
            emit_event=capture_event,
        )
        await svc.start()
        yield svc
        await svc.stop()

    @pytest.mark.asyncio
    async def test_get_channel_by_department_returns_match(self, ward_room):
        """get_channel_by_department returns a channel for a known department."""
        # Default channels include department channels — find one
        channels = await ward_room.list_channels()
        dept_channel = next((c for c in channels if c.department), None)
        if dept_channel:
            result = await ward_room.get_channel_by_department(dept_channel.department)
            assert result is not None
            assert result.department == dept_channel.department

    @pytest.mark.asyncio
    async def test_get_channel_by_type_returns_match(self, ward_room):
        """get_channel_by_type returns a channel for 'ship' type."""
        result = await ward_room.get_channel_by_type("ship")
        # Default channels include a ship-wide channel
        assert result is not None
        assert result.channel_type == "ship"
