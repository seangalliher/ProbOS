"""Tests for channel adapter base classes and response formatter."""

import asyncio
from typing import Any
from dataclasses import dataclass

import pytest

from probos.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelMessage,
    PairingNotificationError,
)
from probos.utils.response_formatter import extract_response_text
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime


# ---------------------------------------------------------------------------
# TestExtractResponseText
# ---------------------------------------------------------------------------

class TestExtractResponseText:
    def test_none_result(self):
        assert extract_response_text(None) == "(Processing failed)"

    def test_direct_response(self):
        assert extract_response_text({"response": "Hello"}) == "Hello"

    def test_reflection_fallback(self):
        result = {"response": "", "reflection": "Based on the analysis..."}
        assert extract_response_text(result) == "Based on the analysis..."

    def test_correction_fallback(self):
        result = {"response": "", "correction": {"changes": "Fixed typo"}}
        assert extract_response_text(result) == "Fixed typo"

    def test_results_with_stdout(self):
        @dataclass
        class FakeResult:
            result: Any = None
            error: str | None = None

        result = {
            "response": "",
            "results": {
                "t1": {"results": [FakeResult(result={"stdout": "output text"})]}
            },
        }
        assert "output text" in extract_response_text(result)

    def test_results_with_string(self):
        @dataclass
        class FakeResult:
            result: Any = None
            error: str | None = None

        result = {
            "response": "",
            "results": {
                "t1": {"results": [FakeResult(result="file contents")]}
            },
        }
        assert "file contents" in extract_response_text(result)

    def test_results_with_error(self):
        @dataclass
        class FakeResult:
            result: Any = None
            error: str = "failed"

        result = {
            "response": "",
            "results": {
                "t1": {"results": [FakeResult()]}
            },
        }
        assert "Error: failed" in extract_response_text(result)

    def test_empty_result(self):
        result = {"response": "", "results": {}}
        text = extract_response_text(result)
        assert len(text) > 0  # Should return a fallback message


# ---------------------------------------------------------------------------
# TestChannelMessage
# ---------------------------------------------------------------------------

class TestChannelMessage:
    def test_construction(self):
        msg = ChannelMessage(
            text="hello",
            channel_id="123",
            user_id="456",
            user_display_name="Alice",
            reply_to_message_id="789",
        )
        assert msg.text == "hello"
        assert msg.channel_id == "123"
        assert msg.user_id == "456"
        assert msg.user_display_name == "Alice"
        assert msg.reply_to_message_id == "789"

    def test_defaults(self):
        msg = ChannelMessage(text="hi", channel_id="c1", user_id="u1")
        assert msg.user_display_name == ""
        assert msg.reply_to_message_id is None


# ---------------------------------------------------------------------------
# TestChannelAdapterHandleMessage
# ---------------------------------------------------------------------------

class _FakeAdapter(ChannelAdapter):
    """Minimal concrete adapter for testing the base class handle_message."""

    def __init__(self, runtime: ProbOSRuntime) -> None:
        super().__init__(runtime, ChannelConfig(enabled=True))
        self.sent: list[tuple[str, str]] = []

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def send_response(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        self.sent.append((channel_id, response))


@pytest.fixture
async def runtime(tmp_path):
    config = SystemConfig()
    config.qa.enabled = False
    llm = MockLLMClient()
    rt = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=llm)
    await rt.start()
    yield rt
    await rt.stop()


class TestChannelAdapterHandleMessage:
    @pytest.mark.asyncio
    async def test_slash_command(self, runtime):
        adapter = _FakeAdapter(runtime)
        msg = ChannelMessage(text="/status", channel_id="ch1", user_id="u1")
        result = await adapter.handle_message(msg)
        assert isinstance(result, str)
        assert len(result) > 0  # slash commands return something

    @pytest.mark.asyncio
    async def test_natural_language(self, runtime):
        adapter = _FakeAdapter(runtime)
        msg = ChannelMessage(
            text="read the file at /tmp/test.txt",
            channel_id="ch1",
            user_id="u1",
        )
        result = await adapter.handle_message(msg)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_conversation_history(self, runtime):
        adapter = _FakeAdapter(runtime)
        # Send two messages to the same channel
        msg1 = ChannelMessage(text="hello world", channel_id="ch1", user_id="u1")
        await adapter.handle_message(msg1)
        msg2 = ChannelMessage(text="hello again", channel_id="ch1", user_id="u1")
        await adapter.handle_message(msg2)
        # History should have 4 entries (2 user + 2 assistant)
        history = adapter._conversation_histories.get("ch1", [])
        assert len(history) == 4
        assert history[0][0] == "user"
        assert history[1][0] == "assistant"
        assert history[2][0] == "user"
        assert history[3][0] == "assistant"

    @pytest.mark.asyncio
    async def test_history_trimming(self, runtime):
        adapter = _FakeAdapter(runtime)
        adapter._max_history = 5
        # Send 12 messages → expect trimming to max_history * 2 = 10
        for i in range(12):
            msg = ChannelMessage(
                text=f"message {i}",
                channel_id="ch1",
                user_id="u1",
            )
            await adapter.handle_message(msg)
        history = adapter._conversation_histories.get("ch1", [])
        assert len(history) <= adapter._max_history * 2


# ---------------------------------------------------------------------------
# BF-804: the pairing gate must not swallow a failed notification
# ---------------------------------------------------------------------------


class _PairingRuntime:
    """Only the member `_check_pairing` reads."""

    def __init__(self, pairing_service: Any) -> None:
        self.pairing_service = pairing_service


class _PairingService:
    """`resolve_did` answers None, so every sender takes the notify path."""

    def __init__(self, *, request_error: Exception | None = None) -> None:
        self.request_error = request_error
        self.requested: list[tuple[str, str]] = []

    def resolve_did(self, channel: str, raw_id: str) -> str | None:
        return None

    async def request_pairing(self, *, channel: str, raw_id: str) -> str:
        self.requested.append((channel, raw_id))
        if self.request_error is not None:
            raise self.request_error
        return "ABC123"


class _GatedAdapter(ChannelAdapter):
    """A concrete adapter that sets `channel_name`, so AD-802a really fires."""

    channel_name = "fake"

    def __init__(
        self, runtime: Any, *, send_error: Exception | None = None
    ) -> None:
        super().__init__(runtime, ChannelConfig(enabled=True))
        self.send_error = send_error
        self.sent: list[tuple[str, str]] = []

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def send_response(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append((channel_id, response))


class TestPairingNotificationFailure:
    """BF-804 (#1350): both non-delivery paths propagate instead of returning
    False, because a bool cannot tell the caller "instructions delivered" from
    "instructions lost".

    These pin the RAISE, one test per path. They are supporting evidence only:
    the consequence that actually discriminates -- Gmail declining to
    acknowledge, so the mail is re-fetched -- lives in
    tests/test_bf804_pairing_notification.py.
    """

    @pytest.mark.asyncio
    async def test_request_pairing_failure_raises(self):
        service = _PairingService(request_error=RuntimeError("store is down"))
        adapter = _GatedAdapter(_PairingRuntime(service))
        msg = ChannelMessage(text="hi", channel_id="c1", user_id="u1")

        with pytest.raises(PairingNotificationError) as caught:
            await adapter._check_pairing(msg)

        assert service.requested == [("fake", "u1")], "control: the mint ran"
        assert adapter.sent == [], "no instructions can exist without a code"
        assert isinstance(caught.value.__cause__, RuntimeError)
        assert "u1" not in str(caught.value)

    @pytest.mark.asyncio
    async def test_instruction_send_failure_raises(self):
        service = _PairingService()
        adapter = _GatedAdapter(
            _PairingRuntime(service), send_error=RuntimeError("transport down")
        )
        msg = ChannelMessage(text="hi", channel_id="c1", user_id="u1")

        with pytest.raises(PairingNotificationError) as caught:
            await adapter._check_pairing(msg)

        assert service.requested == [("fake", "u1")], "control: a code was minted"
        assert isinstance(caught.value.__cause__, RuntimeError)
        assert "u1" not in str(caught.value)

    @pytest.mark.asyncio
    async def test_a_delivered_notice_still_returns_false(self):
        """Outcome 2 stays a clean drop -- the fix must not make every
        unpaired message retry forever."""
        service = _PairingService()
        adapter = _GatedAdapter(_PairingRuntime(service))
        msg = ChannelMessage(text="hi", channel_id="c1", user_id="u1")

        assert await adapter._check_pairing(msg) is False
        assert len(adapter.sent) == 1
        assert "probos pairing approve fake ABC123" in adapter.sent[0][1]

    @pytest.mark.asyncio
    async def test_handle_message_propagates_rather_than_returning_empty(self):
        """The seam the Gmail consumer reads: `handle_message` must not map a
        lost notification onto the same "" it returns for a delivered one."""
        service = _PairingService()
        adapter = _GatedAdapter(
            _PairingRuntime(service), send_error=RuntimeError("transport down")
        )
        msg = ChannelMessage(text="hi", channel_id="c1", user_id="u1")

        with pytest.raises(PairingNotificationError):
            await adapter.handle_message(msg)

        delivered = _GatedAdapter(_PairingRuntime(_PairingService()))
        assert await delivered.handle_message(msg) == "", (
            "control: a DELIVERED notice still returns the empty string"
        )
