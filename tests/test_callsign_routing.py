"""Tests for BF-009: @callsign routing in HXI and embedded mentions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.channels.base import ChannelAdapter, ChannelConfig, ChannelMessage
from probos.crew_profile import extract_callsign_mention


# ---------------------------------------------------------------------------
# 1. extract_callsign_mention utility
# ---------------------------------------------------------------------------

class TestExtractCallsignMention:
    """BF-009: Shared utility for @callsign extraction."""

    def test_at_start(self):
        result = extract_callsign_mention("@wesley hello")
        assert result == ("wesley", "hello")

    def test_embedded(self):
        result = extract_callsign_mention("Hello @wesley")
        assert result == ("wesley", "Hello")

    def test_embedded_middle(self):
        result = extract_callsign_mention("Hello @wesley how are you?")
        assert result == ("wesley", "Hello how are you?")

    def test_at_only(self):
        result = extract_callsign_mention("@wesley")
        assert result == ("wesley", "")

    def test_no_mention(self):
        assert extract_callsign_mention("no mention") is None

    def test_multiple_mentions_takes_first(self):
        result = extract_callsign_mention("@wesley ask @bones about it")
        assert result is not None
        assert result[0] == "wesley"

    def test_empty_string(self):
        assert extract_callsign_mention("") is None

    def test_bare_at_sign(self):
        # @ followed by space — \w+ won't match
        assert extract_callsign_mention("@ hello") is None


# ---------------------------------------------------------------------------
# 2. API endpoint @callsign routing
# ---------------------------------------------------------------------------

class TestAPIChatCallsignRouting:
    """BF-009: /api/chat handles @callsign messages."""

    @pytest.fixture
    def mock_runtime(self):
        rt = MagicMock()
        rt.callsign_registry = MagicMock()
        rt.intent_bus = MagicMock()
        return rt

    @pytest.mark.asyncio
    async def test_api_callsign_at_start(self, mock_runtime):
        """@wesley hello → routes to direct_message intent."""
        mock_runtime.callsign_registry.resolve.return_value = {
            "agent_type": "scout",
            "callsign": "Wesley",
            "agent_id": "scout-0",
            "department": "science",
        }
        mock_result = MagicMock()
        mock_result.result = "Aye, sir!"
        mock_runtime.intent_bus.send = AsyncMock(return_value=mock_result)

        from probos.api import create_app
        app = create_app(mock_runtime)

        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/api/chat", json={"message": "@wesley hello"})
        assert r.status_code == 200
        data = r.json()
        assert "Wesley" in data["response"]
        assert "Aye, sir!" in data["response"]
        mock_runtime.intent_bus.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_api_callsign_embedded(self, mock_runtime):
        """Hello @wesley → routes to direct_message intent."""
        mock_runtime.callsign_registry.resolve.return_value = {
            "agent_type": "scout",
            "callsign": "Wesley",
            "agent_id": "scout-0",
            "department": "science",
        }
        mock_result = MagicMock()
        mock_result.result = "Here, sir."
        mock_runtime.intent_bus.send = AsyncMock(return_value=mock_result)

        from probos.api import create_app
        app = create_app(mock_runtime)

        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/api/chat", json={"message": "Hello @wesley"})
        assert r.status_code == 200
        data = r.json()
        assert "Wesley" in data["response"]

    @pytest.mark.asyncio
    async def test_api_unknown_callsign_falls_through(self, mock_runtime):
        """@picard hello → unresolved, falls through to NL processing."""
        mock_runtime.callsign_registry.resolve.return_value = None
        mock_runtime.process_natural_language = AsyncMock(return_value={
            "final_response": "I don't know a picard.",
        })

        from probos.api import create_app
        app = create_app(mock_runtime)

        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/api/chat", json={"message": "@picard hello"})
        assert r.status_code == 200
        # Should have fallen through to NL processing
        mock_runtime.process_natural_language.assert_called_once()

    @pytest.mark.asyncio
    async def test_api_callsign_not_on_duty(self, mock_runtime):
        """@wesley hello but agent not spawned → 'not on duty' message."""
        mock_runtime.callsign_registry.resolve.return_value = {
            "agent_type": "scout",
            "callsign": "Wesley",
            "agent_id": None,
            "department": "science",
        }

        from probos.api import create_app
        app = create_app(mock_runtime)

        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/api/chat", json={"message": "@wesley hello"})
        assert r.status_code == 200
        assert "not currently on duty" in r.json()["response"]


# ---------------------------------------------------------------------------
# 3. Channel adapter @callsign routing
# ---------------------------------------------------------------------------

class TestChannelCallsignRouting:
    """BF-009: Channel adapter handles embedded @callsign."""

    @pytest.mark.asyncio
    async def test_channel_embedded_callsign(self):
        """Hello @wesley → routes via _handle_callsign_resolved."""
        from probos.channels.base import ChannelAdapter, ChannelMessage
        class FakeAdapter(ChannelAdapter):
            async def start(self): pass
            async def stop(self): pass
            async def send_response(self, channel_id, text): pass

        rt = MagicMock()
        rt.callsign_registry.resolve.return_value = {
            "agent_type": "scout",
            "callsign": "Wesley",
            "agent_id": "scout-0",
            "department": "science",
        }
        mock_result = MagicMock()
        mock_result.result = "Reporting."
        rt.intent_bus.send = AsyncMock(return_value=mock_result)

        adapter = FakeAdapter(rt, ChannelConfig())
        msg = ChannelMessage(text="Hello @wesley", channel_id="ch1", user_id="u1")
        result = await adapter.handle_message(msg)
        assert "Wesley" in result
        assert "Reporting" in result

    @pytest.mark.asyncio
    async def test_channel_unknown_callsign_falls_through(self):
        """@picard hello → unresolved, falls through to NL processing."""
        from probos.channels.base import ChannelAdapter, ChannelMessage
        class FakeAdapter(ChannelAdapter):
            async def start(self): pass
            async def stop(self): pass
            async def send_response(self, channel_id, text): pass

        rt = MagicMock()
        rt.callsign_registry.resolve.return_value = None
        rt.process_natural_language = AsyncMock(return_value={
            "final_response": "NL response",
        })

        adapter = FakeAdapter(rt, ChannelConfig())
        msg = ChannelMessage(text="@picard hello", channel_id="ch1", user_id="u1")
        result = await adapter.handle_message(msg)
        # Should have fallen through to NL processing
        rt.process_natural_language.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Slash commands still work (regression)
# ---------------------------------------------------------------------------

class TestSlashCommandRegression:
    """BF-009: Verify slash commands are not broken by @callsign changes."""

    @pytest.mark.asyncio
    async def test_slash_takes_priority_over_callsign(self):
        """A /command should never be intercepted by @callsign logic."""
        from probos.channels.base import ChannelAdapter, ChannelMessage
        class FakeAdapter(ChannelAdapter):
            async def start(self): pass
            async def stop(self): pass
            async def send_response(self, channel_id, text): pass

        rt = MagicMock()
        # If callsign routing fired, resolve would be called
        rt.callsign_registry.resolve.return_value = None

        adapter = FakeAdapter(rt, ChannelConfig())
        msg = ChannelMessage(text="/status", channel_id="ch1", user_id="u1")
        # /status should route to _handle_slash_command — not trigger @ detection
        with patch("probos.api._handle_slash_command", new_callable=AsyncMock) as mock_slash:
            mock_slash.return_value = {"response": "All systems nominal."}
            result = await adapter.handle_message(msg)
        assert "All systems nominal" in result
        rt.callsign_registry.resolve.assert_not_called()


# ---------------------------------------------------------------------------
# 5. No @mention falls through to NL (regression)
# ---------------------------------------------------------------------------

class TestNoMentionRegression:
    """BF-009: Messages without @ go through NL processing."""

    @pytest.mark.asyncio
    async def test_plain_text_goes_to_nl(self):
        from probos.channels.base import ChannelAdapter, ChannelMessage
        class FakeAdapter(ChannelAdapter):
            async def start(self): pass
            async def stop(self): pass
            async def send_response(self, channel_id, text): pass

        rt = MagicMock()
        rt.process_natural_language = AsyncMock(return_value={
            "final_response": "NL response",
        })

        adapter = FakeAdapter(rt, ChannelConfig())
        msg = ChannelMessage(text="How is the ship?", channel_id="ch1", user_id="u1")
        result = await adapter.handle_message(msg)
        rt.process_natural_language.assert_called_once()
        rt.callsign_registry.resolve.assert_not_called()
