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

import asyncio
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
    """_refresh_client conditionally swaps one observed generation."""

    @pytest.mark.asyncio
    async def test_refresh_installs_new_generation_same_key(self):
        client = OpenAICompatibleClient(config=_make_config())
        try:
            key = client._client_key("standard")
            state = client._client_pool_states[key]
            old = client._clients[key]
            installed = await client._refresh_client(
                "standard", observed_generation=state.generation
            )
            new = client._clients[key]
            assert installed is True
            assert new is not old
            assert state.generation == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_refresh_closes_unborrowed_old_generation(self):
        client = OpenAICompatibleClient(config=_make_config())
        try:
            key = client._client_key("standard")
            state = client._client_pool_states[key]
            old = client._clients[key]
            await client._refresh_client(
                "standard", observed_generation=state.generation
            )
            assert old.is_closed
            assert state.retired == {}
            assert state.retirement_closes == {}
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_refresh_close_failure_still_keeps_new_generation(self):
        """A close error is logged-and-degraded; a fresh client still lands."""
        client = OpenAICompatibleClient(config=_make_config())
        try:
            key = client._client_key("standard")
            state = client._client_pool_states[key]
            old = client._clients[key]
            with patch.object(
                old, "aclose", new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ):
                installed = await client._refresh_client(
                    "standard", observed_generation=state.generation
                )
            assert installed is True
            assert client._clients[key] is not old
            assert state.generation == 1
            assert state.retired == {}
            assert state.retirement_closes == {}
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_refresh_build_failure_preserves_current_generation(self):
        client = OpenAICompatibleClient(config=_make_config())
        try:
            key = client._client_key("standard")
            state = client._client_pool_states[key]
            old = client._clients[key]

            with patch.object(
                client,
                "_build_client",
                side_effect=RuntimeError("injected build failure"),
            ):
                installed = await client._refresh_client(
                    "standard", observed_generation=state.generation
                )

            assert installed is False
            assert state.generation == 0
            assert client._clients[key] is old
            assert old.is_closed is False
            assert state.borrowers == {}
            assert state.retired == {}
            assert state.retirement_closes == {}
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_refresh_publication_failure_rolls_back_and_closes_unpublished_client_once(self):
        client = OpenAICompatibleClient(config=_make_config())
        replacement = client._build_client("standard")
        replacement_close = replacement.aclose
        replacement_close_calls = 0

        async def counted_replacement_close() -> None:
            nonlocal replacement_close_calls
            replacement_close_calls += 1
            await replacement_close()

        try:
            key = client._client_key("standard")
            state = client._client_pool_states[key]
            old = client._clients[key]
            with patch.object(
                client, "_build_client", return_value=replacement
            ), patch.object(
                client,
                "_claim_retired_locked",
                side_effect=RuntimeError("injected publication failure"),
            ) as claim_retired, patch.object(
                replacement, "aclose", new=counted_replacement_close
            ):
                installed = await client._refresh_client(
                    "standard", observed_generation=state.generation
                )

            assert installed is False
            claim_retired.assert_called_once_with(state)
            assert state.generation == 0
            assert client._clients[key] is old
            assert old.is_closed is False
            assert replacement.is_closed is True
            assert replacement_close_calls == 1
            assert state.borrowers == {}
            assert state.retired == {}
            assert state.retirement_closes == {}
            assert not any(
                task.get_name() == "probos-llm-client-unpublished-close"
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task() and not task.done()
            )
        finally:
            if not replacement.is_closed:
                await replacement.aclose()
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
                client, "_refresh_client", wraps=client._refresh_client,
            ) as mock_refresh:
                result = await client.complete(
                    LLMRequest(prompt="hi", tier="standard")
                )
                assert result.content == "hello"
                assert mock_call.await_count == 2
                mock_refresh.assert_awaited_once_with(
                    "standard", observed_generation=0
                )
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_refresh_at_most_once_per_endpoint_generation(self):
        """Each observed endpoint generation receives one refresh budget."""
        client = OpenAICompatibleClient(config=_make_config())
        try:
            empty = LLMResponse(content="", model="claude-sonnet-4.6", tier="standard")
            with patch.object(
                client, "_call_api", new_callable=AsyncMock,
                return_value=empty,
            ) as mock_call, patch.object(
                client, "_refresh_client", wraps=client._refresh_client,
            ) as mock_refresh:
                result = await client.complete(
                    LLMRequest(prompt="hi", tier="standard")
                )
                # Standard gets one refresh for its observed endpoint
                # generation; fallback tiers may refresh later generations.
                refreshed_standard = [
                    c for c in mock_refresh.await_args_list
                    if c.args == ("standard",)
                ]
                assert len(refreshed_standard) == 1
                assert result.content == ""
                assert result.error is not None
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

    @pytest.mark.asyncio
    async def test_persistent_empty_records_failure_and_falls_back(self):
        client = OpenAICompatibleClient(
            config=_make_config(
                llm_model_fast="fast-model",
                llm_model_standard="standard-model",
                llm_model_deep="deep-model",
            )
        )
        try:
            empty = LLMResponse(
                content="", model="claude-sonnet-4.6", tier="standard"
            )
            fallback = LLMResponse(
                content="fallback", model="claude-sonnet-4.6", tier="fast"
            )
            old_success = 123.0
            prior_429s = 4
            client._consecutive_successes["standard"] = 2
            client._last_success["standard"] = old_success
            client._consecutive_429s["standard"] = prior_429s
            before_failure = client._last_failure.get("standard")

            async def empty_then_fallback(request, model, http_client, **kwargs):  # noqa: ANN001
                if model == "standard-model":
                    return empty
                return fallback

            with patch.object(client, "_call_api", side_effect=empty_then_fallback), patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ):
                result = await client.complete(
                    LLMRequest(prompt="persistent", tier="standard")
                )

            assert result.content == "fallback"
            assert client._consecutive_failures["standard"] == 1
            assert client._consecutive_successes["standard"] == 0
            assert client._last_success["standard"] == old_success
            assert client._last_failure["standard"] != before_failure
            assert client._consecutive_429s["standard"] == prior_429s
            assert client._cache_key("standard", "persistent") in client._cache
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_all_text_tiers_persistent_empty_returns_original_tier_cache_hit(self):
        client = OpenAICompatibleClient(
            config=_make_config(
                llm_model_fast="fast-model",
                llm_model_standard="standard-model",
                llm_model_deep="deep-model",
            )
        )
        prompt = "all-empty-cache-hit"
        cached = LLMResponse(
            content="cached-original-tier",
            model="cached-standard-model",
            tier="standard",
        )
        client._cache[client._cache_key("standard", prompt)] = cached
        attempted_models: list[str] = []

        async def persistent_empty(request, model, http_client, **kwargs):  # noqa: ANN001
            attempted_models.append(model)
            return LLMResponse(content="", model=model, tier=request.tier)

        try:
            with patch.object(
                client, "_call_api", side_effect=persistent_empty
            ), patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ):
                result = await client.complete(
                    LLMRequest(prompt=prompt, tier="standard")
                )

            assert result.content == "cached-original-tier"
            assert result.model == "cached-standard-model"
            assert result.tier == "standard"
            assert result.cached is True
            assert attempted_models.count("standard-model") == 2
            assert attempted_models.count("fast-model") == 2
            assert attempted_models.count("deep-model") == 2
            assert client._cache[client._cache_key("standard", prompt)] is cached
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_all_text_tiers_persistent_empty_returns_existing_error_on_cache_miss(self):
        client = OpenAICompatibleClient(config=_make_config())
        try:
            empty = LLMResponse(content="", model="empty", tier="standard")
            with patch.object(client, "_call_api", return_value=empty), patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ):
                result = await client.complete(
                    LLMRequest(prompt="all-empty-cache-miss", tier="standard")
                )

            assert result.content == ""
            assert result.error is not None
            assert result.error.startswith("All LLM tiers unavailable (")
            assert "Persistent empty LLM response" in result.error
            assert client._cache == {}
            for tier in ("standard", "fast", "deep"):
                assert client._consecutive_failures[tier] == 1
                assert client._consecutive_successes[tier] == 0
                assert tier in client._last_failure
                assert tier not in client._last_success
        finally:
            await client.close()
