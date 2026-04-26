"""Tests for BF-232: recreate_stream deletes stale streams before creating."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.mesh.nats_bus import NATSBus


@pytest.fixture
def bus():
    """NATSBus with mocked NATS connection."""
    b = NATSBus(url="nats://localhost:4222")
    b._connected = True
    b._nc = MagicMock()
    b._nc.is_connected = True
    b._js = AsyncMock()
    b._subject_prefix = "probos.local"
    return b


class TestBF232RecreateStream:

    @pytest.mark.asyncio
    async def test_recreate_stream_deletes_before_create(self, bus):
        """BF-232: recreate_stream deletes existing stream before creating."""
        bus._js.delete_stream = AsyncMock()
        bus._js.add_stream = AsyncMock()

        await bus.recreate_stream(
            "SYSTEM_EVENTS", ["system.events.>"],
            max_msgs=50000, max_age=3600,
        )

        bus._js.delete_stream.assert_called_once_with("SYSTEM_EVENTS")
        bus._js.add_stream.assert_called_once()
        config = bus._js.add_stream.call_args[0][0]
        assert "probos.local.system.events.>" in config.subjects

    @pytest.mark.asyncio
    async def test_recreate_stream_delete_failure_nonfatal(self, bus):
        """BF-232: Stream delete failure (not found) doesn't prevent create."""
        bus._js.delete_stream = AsyncMock(side_effect=Exception("stream not found"))
        bus._js.add_stream = AsyncMock()

        await bus.recreate_stream(
            "SYSTEM_EVENTS", ["system.events.>"],
            max_msgs=50000, max_age=3600,
        )

        # Delete failed (benign), but create still attempted
        bus._js.add_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_stale_stream_from_previous_boot_replaced(self, bus):
        """BF-232: Boot finds stale stream, replaces it cleanly."""
        bus._js.delete_stream = AsyncMock()  # Succeeds (stream exists from prev boot)
        bus._js.add_stream = AsyncMock()  # Succeeds (clean creation)

        # Simulate: Phase 2 recreate_stream call after previous boot left stale state
        await bus.recreate_stream(
            "SYSTEM_EVENTS", ["system.events.>"],
            max_msgs=50000, max_age=3600,
        )

        # Old stream deleted, new stream created
        bus._js.delete_stream.assert_called_once_with("SYSTEM_EVENTS")
        bus._js.add_stream.assert_called_once()
        # Critically: update_stream should NEVER be called — the broken code path is gone
        bus._js.update_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_prefix_change_uses_recreate(self, bus):
        """BF-232: set_subject_prefix uses recreate_stream (single delete, no double)."""
        bus._js.delete_stream = AsyncMock()
        bus._js.add_stream = AsyncMock()
        bus._active_subs = []

        # Seed stream configs as Phase 2 would
        bus._stream_configs = [
            {"name": "SYSTEM_EVENTS", "subjects": ["system.events.>"], "max_msgs": 50000, "max_age": 3600},
            {"name": "WARDROOM", "subjects": ["wardroom.events.>"], "max_msgs": 10000, "max_age": 3600},
        ]

        await bus.set_subject_prefix("probos.did_probos_abc123")

        # Each stream deleted exactly once (by recreate_stream, no double-delete)
        deleted_names = [call.args[0] for call in bus._js.delete_stream.call_args_list]
        assert deleted_names.count("SYSTEM_EVENTS") == 1
        assert deleted_names.count("WARDROOM") == 1

        # Recreated with new prefix
        last_configs = [call.args[0] for call in bus._js.add_stream.call_args_list]
        all_subjects = []
        for cfg in last_configs:
            all_subjects.extend(cfg.subjects)
        assert any("probos.did_probos_abc123.system.events.>" in s for s in all_subjects)
        assert any("probos.did_probos_abc123.wardroom.events.>" in s for s in all_subjects)

    @pytest.mark.asyncio
    async def test_recreate_stream_tracks_config(self, bus):
        """BF-232: Stream configs tracked for set_subject_prefix re-creation."""
        bus._js.delete_stream = AsyncMock()
        bus._js.add_stream = AsyncMock()

        await bus.recreate_stream(
            "SYSTEM_EVENTS", ["system.events.>"],
            max_msgs=50000, max_age=3600,
        )

        assert len(bus._stream_configs) == 1
        assert bus._stream_configs[0]["name"] == "SYSTEM_EVENTS"
        assert bus._stream_configs[0]["subjects"] == ["system.events.>"]

    @pytest.mark.asyncio
    async def test_recreate_stream_create_failure_raises(self, bus):
        """BF-232: If create fails after delete, error propagates."""
        bus._js.delete_stream = AsyncMock()
        bus._js.add_stream = AsyncMock(side_effect=Exception("server error"))

        with pytest.raises(Exception, match="server error"):
            await bus.recreate_stream("SYSTEM_EVENTS", ["system.events.>"])

    @pytest.mark.asyncio
    async def test_no_js_skips_everything(self, bus):
        """recreate_stream is no-op without JetStream."""
        bus._js = None
        # Should not raise
        await bus.recreate_stream("SYSTEM_EVENTS", ["system.events.>"])

    @pytest.mark.asyncio
    async def test_ensure_stream_unchanged(self, bus):
        """BF-232: ensure_stream still uses add-or-update (non-destructive)."""
        bus._js.add_stream = AsyncMock()
        bus._js.delete_stream = AsyncMock()

        await bus.ensure_stream(
            "SYSTEM_EVENTS", ["system.events.>"],
            max_msgs=50000, max_age=3600,
        )

        # ensure_stream does NOT call delete_stream
        bus._js.delete_stream.assert_not_called()
        bus._js.add_stream.assert_called_once()
