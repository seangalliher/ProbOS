"""Tests for LLM client abstraction — MockLLMClient and fallback behavior."""

import json

import pytest

from probos.cognitive.llm_client import MockLLMClient, OpenAICompatibleClient
from probos.types import LLMRequest, LLMResponse


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
