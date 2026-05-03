"""Combo C AD-572c: Ward Room activity summary in Captain DM context."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from probos.cognitive.captain_engagement import CaptainEngagementProvider


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_wardroom_activity_summary_empty_when_ward_room_missing():
    rt = SimpleNamespace(ward_room=None)
    provider = CaptainEngagementProvider(runtime=rt)

    result = asyncio.run(provider.wardroom_activity_summary())
    assert result == {}


def test_wardroom_activity_summary_aggregates_per_channel_counts():
    ch_a = SimpleNamespace(id="ch-a")
    ch_b = SimpleNamespace(id="ch-b")
    ward_room = SimpleNamespace()
    ward_room.list_channels = AsyncMock(return_value=[ch_a, ch_b])

    async def _list_threads(channel_id, limit=10):
        return {"ch-a": [1, 2, 3], "ch-b": [1, 2]}[channel_id]

    ward_room.list_threads = _list_threads
    rt = SimpleNamespace(ward_room=ward_room)
    provider = CaptainEngagementProvider(runtime=rt)

    result = asyncio.run(provider.wardroom_activity_summary())
    assert result == {
        "channels": {"ch-a": 3, "ch-b": 2},
        "total_threads": 5,
    }


def test_wardroom_activity_summary_degrades_on_per_channel_failure():
    """If list_threads raises for one channel, others still aggregate."""
    ch_a = SimpleNamespace(id="ch-a")
    ch_b = SimpleNamespace(id="ch-b")
    ward_room = SimpleNamespace()
    ward_room.list_channels = AsyncMock(return_value=[ch_a, ch_b])

    async def _list_threads(channel_id, limit=10):
        if channel_id == "ch-a":
            raise RuntimeError("boom")
        return [object(), object()]

    ward_room.list_threads = _list_threads
    rt = SimpleNamespace(ward_room=ward_room)
    provider = CaptainEngagementProvider(runtime=rt)

    result = asyncio.run(provider.wardroom_activity_summary())
    assert result == {"channels": {"ch-b": 2}, "total_threads": 2}
