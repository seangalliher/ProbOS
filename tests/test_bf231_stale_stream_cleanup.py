"""Tests for BF-231: JetStream streams deleted and recreated on prefix change."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from probos.mesh.nats_bus import NATSBus


@pytest.fixture
def bus():
    """Create a NATSBus instance with mocked NATS connection."""
    b = NATSBus(url="nats://localhost:4222")
    b._connected = True
    b._nc = MagicMock()
    b._nc.is_connected = True
    b._js = AsyncMock()
    b._subject_prefix = "probos.local"
    # Simulate streams created during Phase 2
    b._stream_configs = [
        {"name": "SYSTEM_EVENTS", "subjects": ["system.events.>"], "max_msgs": 50000, "max_age": 3600},
        {"name": "WARDROOM", "subjects": ["wardroom.events.>"], "max_msgs": 10000, "max_age": 3600},
    ]
    # Prevent subscription re-wiring from interfering
    b._active_subs = []
    return b


class TestBF231StaleStreamCleanup:

    @pytest.mark.asyncio
    async def test_prefix_change_deletes_streams(self, bus):
        """BF-231: set_subject_prefix deletes existing streams before recreating."""
        bus._js.delete_stream = AsyncMock()
        bus._js.add_stream = AsyncMock()

        await bus.set_subject_prefix("probos.did_probos_new123")

        # Both streams should be deleted
        deleted_names = [call.args[0] for call in bus._js.delete_stream.call_args_list]
        assert "SYSTEM_EVENTS" in deleted_names
        assert "WARDROOM" in deleted_names

    @pytest.mark.asyncio
    async def test_prefix_change_recreates_streams_with_new_prefix(self, bus):
        """BF-231: Recreated streams use the new prefix and preserve retention limits."""
        bus._js.delete_stream = AsyncMock()
        bus._js.add_stream = AsyncMock()

        await bus.set_subject_prefix("probos.did_probos_new123")

        # Streams should be recreated with new prefix
        add_calls = bus._js.add_stream.call_args_list
        subjects_created = []
        for call in add_calls:
            config = call.args[0] if call.args else call.kwargs.get("config")
            subjects_created.extend(config.subjects)

        assert any("probos.did_probos_new123.system.events.>" in s for s in subjects_created)
        assert any("probos.did_probos_new123.wardroom.events.>" in s for s in subjects_created)

        # Retention limits must be preserved (not reset to defaults)
        first_config = bus._js.add_stream.call_args_list[0].args[0]
        assert first_config.max_msgs == 50000  # SYSTEM_EVENTS
        assert first_config.max_age == 3600

    @pytest.mark.asyncio
    async def test_delete_failure_does_not_block_recreate(self, bus):
        """BF-231: If delete fails (stream doesn't exist), recreate still attempted."""
        bus._js.delete_stream = AsyncMock(side_effect=Exception("stream not found"))
        bus._js.add_stream = AsyncMock()

        await bus.set_subject_prefix("probos.did_probos_new123")

        # add_stream should still be called despite delete failure
        assert bus._js.add_stream.call_count >= 2

    @pytest.mark.asyncio
    async def test_same_prefix_skips_recreate(self, bus):
        """No-op when prefix hasn't changed."""
        bus._js.delete_stream = AsyncMock()

        await bus.set_subject_prefix("probos.local")

        # Same prefix — should return early, no delete calls
        bus._js.delete_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_streams_no_action(self, bus):
        """BF-231: When no streams tracked, prefix change is subscription-only."""
        bus._stream_configs = []
        bus._js.delete_stream = AsyncMock()

        await bus.set_subject_prefix("probos.did_probos_new123")

        bus._js.delete_stream.assert_not_called()
