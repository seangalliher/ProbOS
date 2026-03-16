"""Tests for channel adapter base classes and response formatter."""

import asyncio
from typing import Any
from dataclasses import dataclass

import pytest

from probos.channels.base import ChannelAdapter, ChannelConfig, ChannelMessage
from probos.channels.response_formatter import extract_response_text
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
