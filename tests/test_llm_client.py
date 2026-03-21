"""Tests for LLM client abstraction — MockLLMClient, fallback, and API format routing."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from probos.cognitive.llm_client import MockLLMClient, OpenAICompatibleClient
from probos.config import CognitiveConfig
from probos.types import LLMRequest, LLMResponse


def _httpx_response(status_code: int, *, json: dict) -> httpx.Response:
    """Build an httpx.Response with a dummy request so raise_for_status() works."""
    resp = httpx.Response(status_code, json=json)
    resp._request = httpx.Request("POST", "http://test")
    return resp


class TestMockLLMClient:
    @pytest.fixture
    def client(self):
        return MockLLMClient()

    @pytest.mark.asyncio
    async def test_single_read_file(self, client):
        request = LLMRequest(prompt="read the file at /tmp/test.txt")
        response = await client.complete(request)

        assert response.model == "mock"
        assert not response.error

        data = json.loads(response.content)
        assert "intents" in data
        assert len(data["intents"]) == 1
        assert data["intents"][0]["intent"] == "read_file"
        assert data["intents"][0]["params"]["path"] == "/tmp/test.txt"
        assert data["intents"][0]["use_consensus"] is False

    @pytest.mark.asyncio
    async def test_parallel_reads(self, client):
        request = LLMRequest(prompt="read /tmp/a.txt and /tmp/b.txt")
        response = await client.complete(request)

        data = json.loads(response.content)
        assert len(data["intents"]) == 2

        paths = {i["params"]["path"] for i in data["intents"]}
        assert "/tmp/a.txt" in paths
        assert "/tmp/b.txt" in paths

        # All should be independent (no depends_on)
        for intent in data["intents"]:
            assert intent["depends_on"] == []

    @pytest.mark.asyncio
    async def test_write_file_with_consensus(self, client):
        request = LLMRequest(prompt="write hello to /tmp/out.txt")
        response = await client.complete(request)

        data = json.loads(response.content)
        assert len(data["intents"]) == 1
        intent = data["intents"][0]
        assert intent["intent"] == "write_file"
        assert intent["params"]["path"] == "/tmp/out.txt"
        assert intent["use_consensus"] is True

    @pytest.mark.asyncio
    async def test_unmatched_returns_default(self, client):
        request = LLMRequest(prompt="what is the meaning of life?")
        response = await client.complete(request)

        data = json.loads(response.content)
        assert data == {"intents": []}

    @pytest.mark.asyncio
    async def test_call_count(self, client):
        assert client.call_count == 0
        await client.complete(LLMRequest(prompt="read /tmp/a.txt"))
        assert client.call_count == 1
        await client.complete(LLMRequest(prompt="read /tmp/b.txt"))
        assert client.call_count == 2

    @pytest.mark.asyncio
    async def test_last_request(self, client):
        assert client.last_request is None
        req = LLMRequest(prompt="read /tmp/a.txt")
        await client.complete(req)
        assert client.last_request is req

    @pytest.mark.asyncio
    async def test_custom_default_response(self, client):
        client.set_default_response('{"intents": [{"id": "t1", "intent": "noop", "params": {}, "depends_on": [], "use_consensus": false}]}')
        request = LLMRequest(prompt="something unmatched")
        response = await client.complete(request)

        data = json.loads(response.content)
        assert len(data["intents"]) == 1
        assert data["intents"][0]["intent"] == "noop"

    @pytest.mark.asyncio
    async def test_response_has_token_estimate(self, client):
        response = await client.complete(LLMRequest(prompt="read /tmp/a.txt"))
        assert response.tokens_used > 0

    @pytest.mark.asyncio
    async def test_tier_passed_through(self, client):
        request = LLMRequest(prompt="read /tmp/a.txt", tier="fast")
        response = await client.complete(request)
        assert response.tier == "fast"

    @pytest.mark.asyncio
    async def test_remind_me_routes_to_scheduler(self, client):
        """'Remind me to...' should route to manage_schedule, not manage_todo."""
        response = await client.complete(LLMRequest(
            prompt="remind me to call the dentist at 3pm",
        ))
        data = json.loads(response.content)
        assert data["intents"][0]["intent"] == "manage_schedule", (
            f"Expected manage_schedule but got {data['intents'][0]['intent']}"
        )


class TestOpenAICompatibleClientFallback:
    @pytest.mark.asyncio
    async def test_fallback_to_error_when_no_server(self):
        """When the LLM endpoint is unreachable and cache is empty, return error."""
        client = OpenAICompatibleClient(
            base_url="http://localhost:1",  # Nothing listening
            timeout=1.0,
        )
        try:
            request = LLMRequest(prompt="test prompt")
            response = await client.complete(request)

            assert response.error is not None
            assert response.content == ""
        finally:
            await client.close()


# ---------------------------------------------------------------------------
#  AD-145: API format routing & native Ollama support
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> CognitiveConfig:
    """Helper: build a CognitiveConfig with sensible test defaults."""
    defaults = {
        "llm_base_url": "http://127.0.0.1:8080/v1",
        "llm_api_key": "test-key",
        "llm_model_fast": "qwen3:8b",
        "llm_model_standard": "claude-sonnet-4",
        "llm_model_deep": "claude-sonnet-4",
    }
    defaults.update(overrides)
    return CognitiveConfig(**defaults)


class TestTierConfigApiFormat:
    """CognitiveConfig.tier_config() should return correct api_format."""

    def test_default_is_openai(self):
        cfg = _make_config()
        assert cfg.tier_config("fast")["api_format"] == "openai"
        assert cfg.tier_config("standard")["api_format"] == "openai"
        assert cfg.tier_config("deep")["api_format"] == "openai"

    def test_per_tier_ollama(self):
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
        )
        assert cfg.tier_config("fast")["api_format"] == "ollama"
        assert cfg.tier_config("standard")["api_format"] == "openai"

    def test_multiple_tiers_different_formats(self):
        cfg = _make_config(
            llm_api_format_fast="ollama",
            llm_api_format_standard="openai",
            llm_api_format_deep="ollama",
        )
        assert cfg.tier_config("fast")["api_format"] == "ollama"
        assert cfg.tier_config("standard")["api_format"] == "openai"
        assert cfg.tier_config("deep")["api_format"] == "ollama"

    def test_none_defaults_to_openai(self):
        """Explicitly setting None should still default to openai."""
        cfg = _make_config(llm_api_format_fast=None)
        assert cfg.tier_config("fast")["api_format"] == "openai"


class TestClientDeduplication:
    """Clients should be deduplicated by (url, api_format)."""

    @pytest.mark.asyncio
    async def test_same_url_same_format_shares_client(self):
        cfg = _make_config(
            llm_base_url_fast="http://localhost:8080/v1",
            llm_base_url_standard="http://localhost:8080/v1",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            key_fast = client._client_key("fast")
            key_std = client._client_key("standard")
            assert key_fast == key_std
            # Both should resolve to the same httpx.AsyncClient
            assert client._clients[key_fast] is client._clients[key_std]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_same_url_different_format_separate_clients(self):
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
            llm_base_url_standard="http://localhost:11434",
            llm_api_format_standard="openai",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            key_fast = client._client_key("fast")
            key_std = client._client_key("standard")
            assert key_fast != key_std
            assert client._clients[key_fast] is not client._clients[key_std]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_different_url_separate_clients(self):
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_base_url_standard="http://localhost:8080/v1",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            key_fast = client._client_key("fast")
            key_std = client._client_key("standard")
            assert key_fast != key_std
        finally:
            await client.close()


class TestApiFormatRouting:
    """_call_api should route to the correct backend method."""

    @pytest.fixture
    def ollama_config(self):
        return _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
        )

    @pytest.fixture
    def openai_config(self):
        return _make_config()

    @pytest.mark.asyncio
    async def test_ollama_format_routes_to_native(self, ollama_config):
        client = OpenAICompatibleClient(config=ollama_config)
        try:
            mock_resp = LLMResponse(content="hello", model="qwen3:8b", tier="fast")
            with patch.object(client, "_call_ollama_native", new_callable=AsyncMock, return_value=mock_resp) as mock_native, \
                 patch.object(client, "_call_openai", new_callable=AsyncMock) as mock_openai:
                result = await client.complete(LLMRequest(prompt="test", tier="fast"))
                mock_native.assert_awaited_once()
                mock_openai.assert_not_awaited()
                assert result.content == "hello"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_openai_format_routes_to_openai(self, openai_config):
        client = OpenAICompatibleClient(config=openai_config)
        try:
            mock_resp = LLMResponse(content="world", model="claude-sonnet-4", tier="standard")
            with patch.object(client, "_call_openai", new_callable=AsyncMock, return_value=mock_resp) as mock_openai, \
                 patch.object(client, "_call_ollama_native", new_callable=AsyncMock) as mock_native:
                result = await client.complete(LLMRequest(prompt="test", tier="standard"))
                mock_openai.assert_awaited_once()
                mock_native.assert_not_awaited()
                assert result.content == "world"
        finally:
            await client.close()


class TestOllamaNativeResponseParsing:
    """_call_ollama_native should correctly parse Ollama API responses."""

    def _mock_ollama_response(self, content: str, prompt_eval_count: int = 10, eval_count: int = 5):
        """Create a mock httpx.Response matching Ollama /api/chat format."""
        body = {
            "model": "qwen3:8b",
            "message": {"role": "assistant", "content": content},
            "prompt_eval_count": prompt_eval_count,
            "eval_count": eval_count,
            "done": True,
        }
        return _httpx_response(200, json=body)

    @pytest.mark.asyncio
    async def test_parses_content(self):
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            mock_client = client._clients[client._client_key("fast")]
            with patch.object(mock_client, "post", new_callable=AsyncMock, return_value=self._mock_ollama_response("こんにちは")) as mock_post:
                result = await client._call_ollama_native(
                    LLMRequest(prompt="translate hello", tier="fast"),
                    "qwen3:8b", mock_client,
                )
                assert result.content == "こんにちは"
                assert result.model == "qwen3:8b"
                assert result.tier == "fast"
                # Verify request payload
                call_args = mock_post.call_args
                payload = call_args.kwargs.get("json") or call_args[1].get("json") or call_args[0][1]
                assert payload["stream"] is False
                assert payload["think"] is False
                assert payload["model"] == "qwen3:8b"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_token_counting(self):
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            mock_client = client._clients[client._client_key("fast")]
            with patch.object(mock_client, "post", new_callable=AsyncMock, return_value=self._mock_ollama_response("ok", 100, 50)):
                result = await client._call_ollama_native(
                    LLMRequest(prompt="test", tier="fast"),
                    "qwen3:8b", mock_client,
                )
                assert result.tokens_used == 150  # prompt_eval_count + eval_count

        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_max_tokens_becomes_num_predict(self):
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            mock_client = client._clients[client._client_key("fast")]
            with patch.object(mock_client, "post", new_callable=AsyncMock, return_value=self._mock_ollama_response("ok")) as mock_post:
                await client._call_ollama_native(
                    LLMRequest(prompt="test", tier="fast", max_tokens=512),
                    "qwen3:8b", mock_client,
                )
                payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
                assert payload["options"]["num_predict"] == 512
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_temperature_in_options(self):
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            mock_client = client._clients[client._client_key("fast")]
            with patch.object(mock_client, "post", new_callable=AsyncMock, return_value=self._mock_ollama_response("ok")) as mock_post:
                await client._call_ollama_native(
                    LLMRequest(prompt="test", tier="fast", temperature=0.7),
                    "qwen3:8b", mock_client,
                )
                payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
                assert payload["options"]["temperature"] == 0.7
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_system_prompt_included(self):
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            mock_client = client._clients[client._client_key("fast")]
            with patch.object(mock_client, "post", new_callable=AsyncMock, return_value=self._mock_ollama_response("ok")) as mock_post:
                await client._call_ollama_native(
                    LLMRequest(prompt="test", tier="fast", system_prompt="Be concise."),
                    "qwen3:8b", mock_client,
                )
                payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
                assert payload["messages"][0] == {"role": "system", "content": "Be concise."}
                assert payload["messages"][1] == {"role": "user", "content": "test"}
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_empty_content_returns_empty_string(self):
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            mock_client = client._clients[client._client_key("fast")]
            # Ollama response with empty content
            body = {"model": "qwen3:8b", "message": {"role": "assistant", "content": ""}, "done": True}
            with patch.object(mock_client, "post", new_callable=AsyncMock, return_value=_httpx_response(200, json=body)):
                result = await client._call_ollama_native(
                    LLMRequest(prompt="test", tier="fast"),
                    "qwen3:8b", mock_client,
                )
                assert result.content == ""
        finally:
            await client.close()


class TestOpenAIResponseParsing:
    """_call_openai should correctly parse OpenAI chat/completions responses."""

    def _mock_openai_response(self, content: str, reasoning: str | None = None, tokens: int = 42):
        msg = {"role": "assistant", "content": content}
        if reasoning is not None:
            msg["reasoning"] = reasoning
        body = {
            "choices": [{"message": msg, "finish_reason": "stop"}],
            "usage": {"total_tokens": tokens},
        }
        return _httpx_response(200, json=body)

    @pytest.mark.asyncio
    async def test_parses_content(self):
        cfg = _make_config()
        client = OpenAICompatibleClient(config=cfg)
        try:
            mock_client = client._clients[client._client_key("standard")]
            with patch.object(mock_client, "post", new_callable=AsyncMock, return_value=self._mock_openai_response("hello world", tokens=50)):
                result = await client._call_openai(
                    LLMRequest(prompt="say hello", tier="standard"),
                    "claude-sonnet-4", mock_client,
                )
                assert result.content == "hello world"
                assert result.tokens_used == 50
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_reasoning_fallback_when_content_empty(self):
        """If content is empty but reasoning is present, use reasoning."""
        cfg = _make_config()
        client = OpenAICompatibleClient(config=cfg)
        try:
            mock_client = client._clients[client._client_key("standard")]
            with patch.object(mock_client, "post", new_callable=AsyncMock,
                              return_value=self._mock_openai_response("", reasoning="I think the answer is 42")):
                result = await client._call_openai(
                    LLMRequest(prompt="test", tier="standard"),
                    "claude-sonnet-4", mock_client,
                )
                assert result.content == "I think the answer is 42"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_content_preferred_over_reasoning(self):
        """When both content and reasoning are present, use content."""
        cfg = _make_config()
        client = OpenAICompatibleClient(config=cfg)
        try:
            mock_client = client._clients[client._client_key("standard")]
            with patch.object(mock_client, "post", new_callable=AsyncMock,
                              return_value=self._mock_openai_response("real answer", reasoning="thinking...")):
                result = await client._call_openai(
                    LLMRequest(prompt="test", tier="standard"),
                    "claude-sonnet-4", mock_client,
                )
                assert result.content == "real answer"
        finally:
            await client.close()


class TestCheckEndpointRouting:
    """_check_endpoint should send the right probe based on api_format."""

    @pytest.mark.asyncio
    async def test_ollama_format_probes_api_chat(self):
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            mock_client = client._clients[client._client_key("fast")]
            probe_resp = _httpx_response(200, json={"message": {"content": "pong"}, "done": True})
            with patch.object(mock_client, "post", new_callable=AsyncMock, return_value=probe_resp) as mock_post:
                result = await client._check_endpoint("fast")
                assert result is True
                call_args = mock_post.call_args
                assert call_args[0][0] == "api/chat"
                payload = call_args.kwargs.get("json") or call_args[1]["json"]
                assert payload["stream"] is False
                assert payload["think"] is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_openai_format_probes_chat_completions(self):
        cfg = _make_config()
        client = OpenAICompatibleClient(config=cfg)
        try:
            mock_client = client._clients[client._client_key("standard")]
            probe_resp = _httpx_response(200, json={"choices": [{"message": {"content": ""}}]})
            with patch.object(mock_client, "post", new_callable=AsyncMock, return_value=probe_resp) as mock_post:
                result = await client._check_endpoint("standard")
                assert result is True
                call_args = mock_post.call_args
                assert call_args[0][0] == "chat/completions"
                payload = call_args.kwargs.get("json") or call_args[1]["json"]
                assert payload["max_tokens"] == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_unreachable_returns_false(self):
        cfg = _make_config(
            llm_base_url_fast="http://localhost:1",
            llm_api_format_fast="ollama",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            mock_client = client._clients[client._client_key("fast")]
            with patch.object(
                mock_client, "post", new_callable=AsyncMock,
                side_effect=httpx.ConnectError("Connection refused"),
            ):
                result = await client._check_endpoint("fast")
                assert result is False
        finally:
            await client.close()


class TestTierInfo:
    """tier_info() should include api_format for each tier."""

    @pytest.mark.asyncio
    async def test_includes_api_format(self):
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            info = client.tier_info()
            assert info["fast"]["api_format"] == "ollama"
            assert info["standard"]["api_format"] == "openai"
            assert info["deep"]["api_format"] == "openai"
        finally:
            await client.close()


class TestEndToEndApiFormatComplete:
    """Integration: complete() should route correctly through the full path."""

    @pytest.mark.asyncio
    async def test_ollama_complete_end_to_end(self):
        """Full path: complete(tier=fast, api_format=ollama) → _call_ollama_native."""
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            ollama_body = {
                "model": "qwen3:8b",
                "message": {"role": "assistant", "content": "translated text"},
                "prompt_eval_count": 20,
                "eval_count": 10,
                "done": True,
            }
            mock_client = client._clients[client._client_key("fast")]
            with patch.object(mock_client, "post", new_callable=AsyncMock, return_value=_httpx_response(200, json=ollama_body)):
                result = await client.complete(LLMRequest(prompt="translate hello", tier="fast"))
                assert result.content == "translated text"
                assert result.tokens_used == 30
                assert result.error is None
                assert result.tier == "fast"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_openai_complete_end_to_end(self):
        """Full path: complete(tier=standard, api_format=openai) → _call_openai."""
        cfg = _make_config()
        client = OpenAICompatibleClient(config=cfg)
        try:
            openai_body = {
                "choices": [{"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 99},
            }
            mock_client = client._clients[client._client_key("standard")]
            with patch.object(mock_client, "post", new_callable=AsyncMock, return_value=_httpx_response(200, json=openai_body)):
                result = await client.complete(LLMRequest(prompt="do something", tier="standard"))
                assert result.content == "done"
                assert result.tokens_used == 99
                assert result.error is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ollama_failure_falls_back_to_cache(self):
        """When all tiers are unreachable and cache has a hit, use cache."""
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            # Seed cache via successful call
            ollama_body = {
                "model": "qwen3:8b",
                "message": {"role": "assistant", "content": "cached answer"},
                "prompt_eval_count": 5, "eval_count": 3, "done": True,
            }
            mock_client = client._clients[client._client_key("fast")]
            with patch.object(mock_client, "post", new_callable=AsyncMock, return_value=_httpx_response(200, json=ollama_body)):
                await client.complete(LLMRequest(prompt="cache me", tier="fast"))

            # Now simulate connection failure on ALL tiers so cache is used
            patchers = []
            for tier_key in set(client._clients.keys()):
                c = client._clients[tier_key]
                patchers.append(patch.object(c, "post", new_callable=AsyncMock, side_effect=httpx.ConnectError("refused")))
            for p in patchers:
                p.start()
            try:
                result = await client.complete(LLMRequest(prompt="cache me", tier="fast"))
                assert result.content == "cached answer"
                assert result.cached is True
            finally:
                for p in patchers:
                    p.stop()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_fast_tier_failure_falls_back_to_standard(self):
        """When fast tier is unreachable, falls back to standard tier."""
        cfg = _make_config(
            llm_base_url_fast="http://localhost:11434",
            llm_api_format_fast="ollama",
            llm_base_url="http://localhost:9999",
        )
        client = OpenAICompatibleClient(config=cfg)
        try:
            fast_client = client._clients[client._client_key("fast")]
            standard_client = client._clients[client._client_key("standard")]
            standard_body = {
                "choices": [{"message": {"content": "standard answer"}}],
                "model": "test-model",
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            }
            with patch.object(fast_client, "post", new_callable=AsyncMock, side_effect=httpx.ConnectError("refused")), \
                 patch.object(standard_client, "post", new_callable=AsyncMock, return_value=_httpx_response(200, json=standard_body)):
                result = await client.complete(LLMRequest(prompt="hello", tier="fast"))
                assert result.content == "standard answer"
                assert result.error is None
        finally:
            await client.close()