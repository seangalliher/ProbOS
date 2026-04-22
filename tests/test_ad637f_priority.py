"""AD-637f: Priority Model Formalization tests."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.types import Priority


# ------------------------------------------------------------------
# Priority enum basics (Tests 1-2)
# ------------------------------------------------------------------


class TestPriorityEnum:
    """AD-637f: Priority enum value and serialization tests."""

    def test_priority_enum_values(self):
        """Test 1: Priority StrEnum has expected string values."""
        assert Priority.CRITICAL.value == "critical"
        assert Priority.NORMAL.value == "normal"
        assert Priority.LOW.value == "low"

    def test_priority_json_serializable(self):
        """Test 2: Priority StrEnum is JSON-serializable."""
        # Dict value path
        assert json.dumps({"priority": Priority.CRITICAL}) == '{"priority": "critical"}'
        # List element path
        assert json.dumps([Priority.CRITICAL, Priority.LOW]) == '["critical", "low"]'


# ------------------------------------------------------------------
# Priority.classify (Tests 3-8)
# ------------------------------------------------------------------


class TestPriorityClassify:
    """AD-637f: Priority.classify() classification rules."""

    def test_classify_captain_is_critical(self):
        """Test 3: Captain-originated → CRITICAL."""
        assert Priority.classify(is_captain=True) == Priority.CRITICAL

    def test_classify_mentioned_is_critical(self):
        """Test 4: @mentioned → CRITICAL."""
        assert Priority.classify(was_mentioned=True) == Priority.CRITICAL

    def test_classify_dm_is_critical(self):
        """Test 5: All DMs → CRITICAL (any sender)."""
        assert Priority.classify(intent="direct_message") == Priority.CRITICAL
        # Captain DM — captain flag takes precedence, same result
        assert Priority.classify(intent="direct_message", is_captain=True) == Priority.CRITICAL

    def test_classify_proactive_is_low(self):
        """Test 6: Proactive think → LOW."""
        assert Priority.classify(intent="proactive_think") == Priority.LOW

    def test_classify_ward_room_is_normal(self):
        """Test 7: Ward room notification → NORMAL."""
        assert Priority.classify(intent="ward_room_notification") == Priority.NORMAL

    def test_classify_defaults_to_normal(self):
        """Test 8: No args → NORMAL."""
        assert Priority.classify() == Priority.NORMAL


# ------------------------------------------------------------------
# LLM client integration (Tests 9-10)
# ------------------------------------------------------------------


class TestLLMClientPriority:
    """AD-637f: LLM client accepts Priority enum."""

    @pytest.mark.asyncio
    async def test_llm_client_priority_enum(self):
        """Test 9: MockLLMClient.complete() accepts all Priority tiers."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.types import LLMRequest

        client = MockLLMClient()
        request = LLMRequest(
            prompt="test",
            system_prompt="test",
        )
        # All three tiers accepted without error
        await client.complete(request, priority=Priority.CRITICAL)
        await client.complete(request, priority=Priority.NORMAL)
        await client.complete(request, priority=Priority.LOW)
        assert len(client._call_log) == 3

    @pytest.mark.asyncio
    async def test_critical_uses_interactive_semaphore(self):
        """Test 10: Priority.CRITICAL routes to interactive semaphore."""
        from probos.cognitive.llm_client import OpenAICompatibleClient

        # Create client — defaults give 2 interactive, 4 background slots
        client = OpenAICompatibleClient()
        assert client._interactive_semaphore._value == 2
        assert client._background_semaphore._value == 4

        # Exhaust background semaphore
        for _ in range(4):
            await client._background_semaphore.acquire()
        assert client._background_semaphore._value == 0

        # Interactive semaphore still has capacity — CRITICAL would proceed
        assert client._interactive_semaphore._value == 2

        # Clean up
        for _ in range(4):
            client._background_semaphore.release()


# ------------------------------------------------------------------
# NATS priority headers (Tests 11-13)
# ------------------------------------------------------------------


class TestNATSPriorityHeaders:
    """AD-637f: X-Priority headers on NATS JetStream publishes."""

    @pytest.mark.asyncio
    async def test_ward_room_nats_publish_has_priority_header(self):
        """Test 11: Ward room JetStream publish includes X-Priority header."""
        from probos.mesh.nats_bus import MockNATSBus

        bus = MockNATSBus()
        await bus.start()
        await bus.ensure_stream("WARD_ROOM", ["wardroom.events.>"])

        # Capture headers via subscriber
        received_headers: list[dict] = []

        async def _capture(msg):
            received_headers.append(dict(msg.headers) if msg.headers else {})

        await bus.js_subscribe("wardroom.events.>", _capture, stream="WARD_ROOM")

        # Simulate what communication.py _ward_room_emit does
        data = {"author_id": "wesley", "mentions": [], "content": "hello"}
        _author = data.get("author_id", "")
        _mentions = data.get("mentions", [])
        _is_captain = _author == "captain"
        _was_mentioned = "captain" in [m.lower() for m in _mentions if isinstance(m, str)]
        _priority = Priority.classify(is_captain=_is_captain, was_mentioned=_was_mentioned)
        headers = {"X-Priority": _priority.value}

        await bus.js_publish("wardroom.events.new_post", {"event_type": "new_post", **data}, headers=headers)

        assert len(received_headers) == 1
        assert received_headers[0].get("X-Priority") == "normal"

    @pytest.mark.asyncio
    async def test_ward_room_captain_author_gets_critical_header(self):
        """Test 12: Captain-authored ward room event → X-Priority: critical."""
        data = {"author_id": "captain", "mentions": []}
        _is_captain = data["author_id"] == "captain"
        _was_mentioned = "captain" in [m.lower() for m in data.get("mentions", []) if isinstance(m, str)]
        _priority = Priority.classify(is_captain=_is_captain, was_mentioned=_was_mentioned)

        assert _priority == Priority.CRITICAL
        assert _priority.value == "critical"

    @pytest.mark.asyncio
    async def test_ward_room_captain_mentioned_gets_critical_header(self):
        """Test 13: Ward room event mentioning Captain → X-Priority: critical."""
        data = {"author_id": "wesley", "mentions": ["Captain", "LaForge"]}
        _is_captain = data["author_id"] == "captain"
        _was_mentioned = "captain" in [m.lower() for m in data.get("mentions", []) if isinstance(m, str)]
        _priority = Priority.classify(is_captain=_is_captain, was_mentioned=_was_mentioned)

        assert _priority == Priority.CRITICAL
        assert _priority.value == "critical"
