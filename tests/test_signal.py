"""Tests for SignalManager."""

import asyncio

import pytest

from probos.mesh.signal import SignalManager
from probos.types import IntentMessage


class TestSignalManager:
    @pytest.mark.asyncio
    async def test_track_and_check_alive(self):
        sm = SignalManager()
        intent = IntentMessage(intent="test", ttl_seconds=10.0)
        sm.track(intent)
        assert sm.is_alive(intent.id)
        assert sm.active_count == 1

    @pytest.mark.asyncio
    async def test_untrack(self):
        sm = SignalManager()
        intent = IntentMessage(intent="test", ttl_seconds=10.0)
        sm.track(intent)
        sm.untrack(intent.id)
        assert not sm.is_alive(intent.id)
        assert sm.active_count == 0

    @pytest.mark.asyncio
    async def test_unknown_id_not_alive(self):
        sm = SignalManager()
        assert not sm.is_alive("nonexistent")

    @pytest.mark.asyncio
    async def test_expired_signal_is_not_alive(self):
        sm = SignalManager()
        intent = IntentMessage(intent="test", ttl_seconds=0.1)
        sm.track(intent)
        await asyncio.sleep(0.2)
        assert not sm.is_alive(intent.id)

    @pytest.mark.asyncio
    async def test_reaper_removes_expired(self):
        sm = SignalManager(reap_interval=0.1)
        expired_ids: list[str] = []
        sm.on_expired(lambda id_: expired_ids.append(id_))

        intent = IntentMessage(intent="test", ttl_seconds=0.2)
        sm.track(intent)

        await sm.start()
        await asyncio.sleep(0.5)
        await sm.stop()

        assert intent.id in expired_ids
        assert sm.active_count == 0

    @pytest.mark.asyncio
    async def test_start_stop_idempotent(self):
        sm = SignalManager()
        await sm.start()
        await sm.stop()
        await sm.stop()  # Should not raise
