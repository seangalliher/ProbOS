"""BF-612: empty-content 200 → recycle the connection pool and retry once.

A degraded keep-alive socket to the Copilot proxy returns HTTP 200 with empty
content (no transport error). Under continuous load the socket never idles past
the keep-alive expiry, so it is reused indefinitely and every call returns
empty — the failure a proxy restart "fixes" by force-closing all sockets.
``call()`` now detects an empty-content reply and retries once on a fresh
socket via ``_refresh_client``, reproducing the proxy-restart fix in-process.

These tests use a real ``OpenAICompatibleClient`` (BF-287: real fixtures at the
substrate boundary) and patch only ``_call_api`` / ``_build_client`` so the
retry-and-recycle control flow is exercised without a live endpoint.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import CognitiveConfig
from probos.types import LLMRequest, LLMResponse


def _make_config(**overrides) -> CognitiveConfig:
    defaults = {
        "llm_base_url": "http://127.0.0.1:8080/v1",
        "llm_api_key": "test-key",
        "llm_model_fast": "claude-sonnet-4.6",
        "llm_model_standard": "claude-sonnet-4.6",
        "llm_model_deep": "claude-opus-4.6",
    }
    defaults.update(overrides)
    return CognitiveConfig(**defaults)


class TestBuildClient:
    """_build_client is the single source of truth for client construction."""

    @pytest.mark.asyncio
    async def test_build_client_normalizes_base_url_trailing_slash(self):
        client = OpenAICompatibleClient(config=_make_config())
        try:
            built = client._build_client("standard")
            try:
                assert str(built.base_url).endswith("/")
            finally:
                await built.aclose()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_build_client_sets_authorization_header(self):
        client = OpenAICompatibleClient(config=_make_config(llm_api_key="abc123"))
        try:
            built = client._build_client("standard")
            try:
                assert built.headers.get("Authorization") == "Bearer abc123"
            finally:
                await built.aclose()
        finally:
            await client.close()


class TestRefreshClient:
    """_refresh_client closes the stale pool and installs a fresh one."""

    @pytest.mark.asyncio
    async def test_refresh_installs_new_client_same_key(self):
        client = OpenAICompatibleClient(config=_make_config())
        try:
            key = client._client_key("standard")
            old = client._clients[key]
            await client._refresh_client("standard")
            new = client._clients[key]
            assert new is not old
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_refresh_closes_old_client(self):
        client = OpenAICompatibleClient(config=_make_config())
        try:
            old = client._clients[client._client_key("standard")]
            await client._refresh_client("standard")
            assert old.is_closed
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_refresh_survives_close_failure(self):
        """A close error is logged-and-degraded; a fresh client still lands."""
        client = OpenAICompatibleClient(config=_make_config())
        try:
            key = client._client_key("standard")
            old = client._clients[key]
            with patch.object(
                old, "aclose", new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ):
                await client._refresh_client("standard")
            assert client._clients[key] is not old
        finally:
            await client.close()


class TestEmptyContentRetry:
    """The call() loop recycles the socket once on an empty-content 200."""

    @pytest.mark.asyncio
    async def test_empty_then_content_recovers(self):
        """Empty first reply → refresh + retry → second reply has content."""
        client = OpenAICompatibleClient(config=_make_config())
        try:
            empty = LLMResponse(content="", model="claude-sonnet-4.6", tier="standard")
            full = LLMResponse(content="hello", model="claude-sonnet-4.6", tier="standard")
            with patch.object(
                client, "_call_api", new_callable=AsyncMock,
                side_effect=[empty, full],
            ) as mock_call, patch.object(
                client, "_refresh_client", new_callable=AsyncMock,
            ) as mock_refresh:
                result = await client.complete(
                    LLMRequest(prompt="hi", tier="standard")
                )
                assert result.content == "hello"
                assert mock_call.await_count == 2
                mock_refresh.assert_awaited_once_with("standard")
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_refresh_at_most_once_per_tier(self):
        """Two empty replies → exactly one refresh, empty surfaces (no spin)."""
        client = OpenAICompatibleClient(config=_make_config())
        try:
            empty = LLMResponse(content="", model="claude-sonnet-4.6", tier="standard")
            with patch.object(
                client, "_call_api", new_callable=AsyncMock,
                return_value=empty,
            ) as mock_call, patch.object(
                client, "_refresh_client", new_callable=AsyncMock,
            ) as mock_refresh:
                result = await client.complete(
                    LLMRequest(prompt="hi", tier="standard")
                )
                # standard tier: 1 initial + 1 retry, then it is in the
                # refreshed set so the fallback tiers each get their own single
                # refresh — assert standard was refreshed exactly once.
                refreshed_standard = [
                    c for c in mock_refresh.await_args_list
                    if c.args == ("standard",)
                ]
                assert len(refreshed_standard) == 1
                assert result.content == ""
                assert mock_call.await_count >= 2
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_non_empty_first_reply_no_refresh(self):
        """A normal reply never triggers a connection recycle."""
        client = OpenAICompatibleClient(config=_make_config())
        try:
            full = LLMResponse(content="world", model="claude-sonnet-4.6", tier="standard")
            with patch.object(
                client, "_call_api", new_callable=AsyncMock,
                return_value=full,
            ) as mock_call, patch.object(
                client, "_refresh_client", new_callable=AsyncMock,
            ) as mock_refresh:
                result = await client.complete(
                    LLMRequest(prompt="hi", tier="standard")
                )
                assert result.content == "world"
                assert mock_call.await_count == 1
                mock_refresh.assert_not_awaited()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_tool_call_reply_not_treated_as_empty(self):
        """An empty-text reply that carries content_blocks (tool call) is a
        legitimate response and must NOT trigger a recycle."""
        client = OpenAICompatibleClient(config=_make_config())
        try:
            tool_reply = LLMResponse(
                content="",
                model="claude-sonnet-4.6",
                tier="standard",
                content_blocks=[{"type": "tool_use"}],
            )
            with patch.object(
                client, "_call_api", new_callable=AsyncMock,
                return_value=tool_reply,
            ) as mock_call, patch.object(
                client, "_refresh_client", new_callable=AsyncMock,
            ) as mock_refresh:
                result = await client.complete(
                    LLMRequest(prompt="use a tool", tier="standard")
                )
                assert result.content_blocks
                assert mock_call.await_count == 1
                mock_refresh.assert_not_awaited()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ollama_empty_reply_no_refresh(self):
        """The recycle is OpenAI/proxy-only; the Ollama-native path is out of
        scope (local server, no upstream-session rotation)."""
        cfg = _make_config(
            llm_base_url_standard="http://localhost:11434",
            llm_api_format_standard="ollama",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            empty = LLMResponse(content="", model="qwen3:8b", tier="standard")
            with patch.object(
                client, "_call_api", new_callable=AsyncMock,
                return_value=empty,
            ), patch.object(
                client, "_refresh_client", new_callable=AsyncMock,
            ) as mock_refresh:
                await client.complete(LLMRequest(prompt="hi", tier="standard"))
                # standard is ollama → never refreshed. (Fallback tiers may be
                # openai, but they have their own clients; assert standard tier
                # specifically was not recycled.)
                refreshed_standard = [
                    c for c in mock_refresh.await_args_list
                    if c.args == ("standard",)
                ]
                assert refreshed_standard == []
        finally:
            await client.close()
