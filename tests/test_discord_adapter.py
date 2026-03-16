"""Tests for the Discord adapter — chunking, config, and construction.

Does NOT import discord.py or test actual connectivity.
"""

import pytest

from probos.channels.discord_adapter import _chunk_message, DiscordAdapter
from probos.cognitive.llm_client import MockLLMClient
from probos.config import DiscordConfig, SystemConfig
from probos.runtime import ProbOSRuntime


# ---------------------------------------------------------------------------
# TestChunkMessage
# ---------------------------------------------------------------------------

class TestChunkMessage:
    def test_short_message(self):
        assert _chunk_message("hello") == ["hello"]

    def test_exact_limit(self):
        msg = "A" * 2000
        chunks = _chunk_message(msg)
        assert len(chunks) == 1
        assert chunks[0] == msg

    def test_long_message_splits_on_newline(self):
        # Build a message with a newline near the middle
        part1 = "A" * 1500
        part2 = "B" * 1000
        msg = part1 + "\n" + part2
        chunks = _chunk_message(msg)
        assert len(chunks) == 2
        assert chunks[0] == part1
        assert chunks[1] == part2

    def test_very_long_hard_splits(self):
        msg = "X" * 5000  # No spaces or newlines
        chunks = _chunk_message(msg)
        assert all(len(c) <= 2000 for c in chunks)
        assert "".join(chunks) == msg


# ---------------------------------------------------------------------------
# TestDiscordAdapterInit
# ---------------------------------------------------------------------------

class TestDiscordAdapterInit:
    @pytest.mark.asyncio
    async def test_creates_with_config(self, tmp_path):
        config = SystemConfig()
        llm = MockLLMClient()
        rt = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=llm)
        await rt.start()
        try:
            dc = DiscordConfig(enabled=True, token="fake-token")
            adapter = DiscordAdapter(rt, dc)
            assert adapter.discord_config.token == "fake-token"
            assert adapter._started is False
        finally:
            await rt.stop()

    def test_config_defaults(self):
        dc = DiscordConfig()
        assert dc.enabled is False
        assert dc.token == ""
        assert dc.command_prefix == "!"
        assert dc.mention_required is False
        assert dc.allowed_channel_ids == []


# ---------------------------------------------------------------------------
# TestDiscordConfig
# ---------------------------------------------------------------------------

class TestDiscordConfig:
    def test_config_in_system_config(self):
        """SystemConfig with channels.discord section parses correctly."""
        sc = SystemConfig.model_validate({
            "channels": {
                "discord": {
                    "enabled": True,
                    "token": "test-token",
                    "command_prefix": "?",
                    "mention_required": True,
                    "allowed_channel_ids": [123, 456],
                }
            }
        })
        assert sc.channels.discord.enabled is True
        assert sc.channels.discord.token == "test-token"
        assert sc.channels.discord.command_prefix == "?"
        assert sc.channels.discord.mention_required is True
        assert sc.channels.discord.allowed_channel_ids == [123, 456]

    def test_config_defaults(self):
        sc = SystemConfig()
        assert sc.channels.discord.enabled is False
        assert sc.channels.discord.token == ""
