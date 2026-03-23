"""Tests for probos.utils.json_extract — shared JSON extraction and retry."""

from __future__ import annotations

import json
import pytest

from probos.utils.json_extract import extract_json, extract_json_list, complete_with_retry
from probos.types import LLMRequest, LLMResponse


# ── extract_json ──────────────────────────────────────────────────────────


class TestExtractJson:
    def test_clean_json(self):
        result = extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_fences(self):
        text = '```json\n{"key": "value"}\n```'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_preamble_text(self):
        text = 'Here is the result: {"key": "value"}'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_think_blocks(self):
        text = '<think>reasoning here</think>{"key": "value"}'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_braces_in_strings(self):
        text = '{"code": "if (x) { y }"}'
        result = extract_json(text)
        assert result == {"code": "if (x) { y }"}

    def test_no_json_raises(self):
        with pytest.raises(ValueError, match="No valid JSON object"):
            extract_json("just plain text with no json")


# ── extract_json_list ─────────────────────────────────────────────────────


class TestExtractJsonList:
    def test_json_array(self):
        result = extract_json_list('["a", "b", "c"]')
        assert result == ["a", "b", "c"]

    def test_markdown_fenced_array(self):
        text = '```json\n["search query 1", "search query 2"]\n```'
        result = extract_json_list(text)
        assert result == ["search query 1", "search query 2"]

    def test_no_array_raises(self):
        with pytest.raises(ValueError, match="No valid JSON array"):
            extract_json_list("just some text")


# ── complete_with_retry ───────────────────────────────────────────────────


class _FakeLLMClient:
    """Minimal fake LLM client for retry tests."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self._call_count = 0
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        resp = self._responses[self._call_count]
        self._call_count += 1
        return resp


class TestCompleteWithRetry:
    @pytest.mark.asyncio
    async def test_success_first_try(self):
        client = _FakeLLMClient([
            LLMResponse(content='{"intents": []}', error=None),
        ])
        request = LLMRequest(prompt="test", temperature=0.0)
        result, response = await complete_with_retry(
            client, request, extract_json, max_retries=1,
        )
        assert result == {"intents": []}
        assert len(client.requests) == 1

    @pytest.mark.asyncio
    async def test_success_on_retry(self):
        client = _FakeLLMClient([
            LLMResponse(content="not json at all", error=None),
            LLMResponse(content='{"intents": []}', error=None),
        ])
        request = LLMRequest(prompt="test", temperature=0.0)
        result, response = await complete_with_retry(
            client, request, extract_json, max_retries=1,
        )
        assert result == {"intents": []}
        assert len(client.requests) == 2

    @pytest.mark.asyncio
    async def test_all_failures_raises(self):
        client = _FakeLLMClient([
            LLMResponse(content="garbage", error=None),
            LLMResponse(content="still garbage", error=None),
        ])
        request = LLMRequest(prompt="test", temperature=0.0)
        with pytest.raises(ValueError):
            await complete_with_retry(
                client, request, extract_json, max_retries=1,
            )
        assert len(client.requests) == 2

    @pytest.mark.asyncio
    async def test_retry_prompt_includes_error(self):
        client = _FakeLLMClient([
            LLMResponse(content="no json here", error=None),
            LLMResponse(content='{"ok": true}', error=None),
        ])
        request = LLMRequest(prompt="original prompt", temperature=0.0)
        await complete_with_retry(
            client, request, extract_json, max_retries=1,
        )
        # The retry request should contain the error feedback
        retry_request = client.requests[1]
        assert "could not be parsed" in retry_request.prompt
        assert "original prompt" in retry_request.prompt
        # Temperature should have bumped
        assert retry_request.temperature == pytest.approx(0.1)
