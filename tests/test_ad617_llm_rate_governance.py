"""AD-617: LLM Rate Governance tests.

Tests for token bucket rate limiting, HTTP 429 backoff,
LRU cache eviction, and LLMRateConfig.
"""

import asyncio
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import CognitiveConfig, LLMRateConfig, SystemConfig
from probos.types import LLMRequest, LLMResponse


def _make_client(**kwargs) -> OpenAICompatibleClient:
    """Create a client with rate config for testing."""
    rate_config = LLMRateConfig(**kwargs)
    return OpenAICompatibleClient(config=CognitiveConfig(), rate_config=rate_config)


def _make_response(content: str = "ok", tier: str = "fast") -> LLMResponse:
    """Create a simple LLMResponse for mocking."""
    return LLMResponse(content=content, model="test-model", tier=tier, tokens_used=10)


# ---------------------------------------------------------------------------
# Class 1: Token Bucket Rate Limiter
# ---------------------------------------------------------------------------

class TestTokenBucketRateLimiter:
    """Tests for _wait_for_rate_limit sliding window."""

    @pytest.mark.asyncio
    async def test_allows_requests_under_limit(self):
        """Send 5 requests with rpm=10. All should succeed."""
        client = _make_client(rpm_fast=10)
        rpm_limits = {"fast": 10, "standard": 30, "deep": 15}

        for _ in range(5):
            result = await client._wait_for_rate_limit("fast", rpm_limits)
            assert result is True

        assert len(client._request_timestamps["fast"]) == 5

    @pytest.mark.asyncio
    async def test_blocks_when_over_limit(self):
        """Set rpm_fast=2, max_wait_seconds=0.1. Third request should fail."""
        client = _make_client(rpm_fast=2, max_wait_seconds=0.1)

        # Mock _call_api to return a response
        client._call_api = AsyncMock(return_value=_make_response())

        req1 = LLMRequest(prompt="test1", tier="fast")
        req2 = LLMRequest(prompt="test2", tier="fast")
        req3 = LLMRequest(prompt="test3", tier="fast")

        resp1 = await client.complete(req1)
        resp2 = await client.complete(req2)
        # Third should hit rate limit
        resp3 = await client.complete(req3)
        assert resp3.error is not None
        assert "rate limit exceeded" in resp3.error

    @pytest.mark.asyncio
    async def test_waits_when_at_capacity(self):
        """Set rpm_fast=2. Fill 2 slots, age timestamps, 3rd succeeds after wait."""
        client = _make_client(rpm_fast=2, max_wait_seconds=5.0)
        rpm_limits = {"fast": 2, "standard": 30, "deep": 15}

        # Fill two slots
        await client._wait_for_rate_limit("fast", rpm_limits)
        await client._wait_for_rate_limit("fast", rpm_limits)

        # Age the oldest timestamp so it expires within max_wait
        oldest = client._request_timestamps["fast"][0]
        client._request_timestamps["fast"][0] = time.monotonic() - 59.5

        # Third should succeed after brief wait
        result = await client._wait_for_rate_limit("fast", rpm_limits, max_wait=5.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_rate_limit_disabled_when_zero(self):
        """rpm_fast=0 should allow unlimited requests."""
        client = _make_client(rpm_fast=0)
        rpm_limits = {"fast": 0, "standard": 30, "deep": 15}

        for _ in range(100):
            result = await client._wait_for_rate_limit("fast", rpm_limits)
            assert result is True


# ---------------------------------------------------------------------------
# Class 2: HTTP 429 Backoff
# ---------------------------------------------------------------------------

class TestHTTP429Backoff:
    """Tests for 429-specific handling in complete()."""

    def _mock_429_response(self, headers: dict | None = None):
        """Create a mock httpx.Response with 429 status."""
        response = MagicMock()
        response.status_code = 429
        response.headers = headers or {}
        response.text = "Rate limited"
        mock_request = MagicMock()
        return httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=mock_request,
            response=response,
        )

    @pytest.mark.asyncio
    async def test_429_retries_same_tier(self):
        """Mock first call to return 429, second to succeed. Verify retry on same tier."""
        client = _make_client()
        success_response = _make_response("success", tier="fast")

        call_count = 0
        async def mock_call_api(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise self._mock_429_response()
            return success_response

        client._call_api = mock_call_api

        with patch("asyncio.sleep", new_callable=AsyncMock):
            req = LLMRequest(prompt="test", tier="fast")
            resp = await client.complete(req)

        assert resp.content == "success"
        assert resp.error is None

    @pytest.mark.asyncio
    async def test_429_respects_retry_after_header(self):
        """Mock 429 with Retry-After: 1 header. Verify sleep called with ~1.0s."""
        client = _make_client()
        success_response = _make_response("ok")

        call_count = 0
        async def mock_call_api(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise self._mock_429_response(headers={"Retry-After": "1"})
            return success_response

        client._call_api = mock_call_api

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            req = LLMRequest(prompt="test", tier="fast")
            await client.complete(req)

        mock_sleep.assert_called_once_with(1.0)

    @pytest.mark.asyncio
    async def test_429_exponential_backoff_without_header(self):
        """Mock multiple 429s without Retry-After. Verify backoff grows."""
        client = _make_client()
        success_response = _make_response("ok")

        call_count = 0
        async def mock_call_api(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise self._mock_429_response()
            return success_response

        client._call_api = mock_call_api

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            req = LLMRequest(prompt="test", tier="fast")
            await client.complete(req)

        # Should have been called 3 times with increasing waits: 2, 4, 8
        assert mock_sleep.call_count == 3
        waits = [call.args[0] for call in mock_sleep.call_args_list]
        assert waits == [2.0, 4.0, 8.0]

    @pytest.mark.asyncio
    async def test_429_counter_resets_on_success(self):
        """Trigger 429s, then succeed. Verify _consecutive_429s resets to 0."""
        client = _make_client()
        success_response = _make_response("ok")

        call_count = 0
        async def mock_call_api(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise self._mock_429_response()
            return success_response

        client._call_api = mock_call_api

        with patch("asyncio.sleep", new_callable=AsyncMock):
            req = LLMRequest(prompt="test", tier="fast")
            await client.complete(req)

        assert client._consecutive_429s["fast"] == 0


# ---------------------------------------------------------------------------
# Class 3: LRU Cache Eviction
# ---------------------------------------------------------------------------

class TestLRUCacheEviction:
    """Tests for OrderedDict LRU cache with max entries."""

    @pytest.mark.asyncio
    async def test_cache_evicts_oldest(self):
        """Set cache_max_entries=3. Add 4 cached responses. Oldest evicted."""
        client = _make_client(cache_max_entries=3)

        responses = [
            _make_response(f"resp{i}", tier="fast")
            for i in range(4)
        ]

        call_idx = 0
        async def mock_call_api(*args, **kwargs):
            nonlocal call_idx
            resp = responses[call_idx]
            call_idx += 1
            return resp

        client._call_api = mock_call_api

        for i in range(4):
            req = LLMRequest(prompt=f"prompt{i}", tier="fast")
            await client.complete(req)

        # Cache should have 3 entries (evicted the oldest)
        assert len(client._cache) == 3
        # First key should be gone
        first_key = client._cache_key("fast", "prompt0")
        assert first_key not in client._cache
        # Last 3 should remain
        for i in range(1, 4):
            key = client._cache_key("fast", f"prompt{i}")
            assert key in client._cache

    @pytest.mark.asyncio
    async def test_cache_lru_reorder(self):
        """Access an existing cache entry. Verify it survives eviction."""
        client = _make_client(cache_max_entries=3)

        call_idx = 0
        responses = [_make_response(f"resp{i}") for i in range(4)]

        async def mock_call_api(*args, **kwargs):
            nonlocal call_idx
            resp = responses[min(call_idx, len(responses) - 1)]
            call_idx += 1
            return resp

        client._call_api = mock_call_api

        # Fill cache with 3 entries
        for i in range(3):
            req = LLMRequest(prompt=f"prompt{i}", tier="fast")
            await client.complete(req)

        # Re-request prompt0 (should hit cache and move to end)
        # But we need to trigger move_to_end — re-requesting with same prompt
        # will get cache hit in fallback path. Let's query again:
        req_replay = LLMRequest(prompt="prompt0", tier="fast")
        await client.complete(req_replay)  # cache miss in rate-limit path; cache hit won't occur there
        # prompt0's key got re-written (not just read), moving to end

        # Now add a new entry to trigger eviction
        req_new = LLMRequest(prompt="prompt_new", tier="fast")
        await client.complete(req_new)

        # prompt0 should still be in cache (it was moved to end)
        key0 = client._cache_key("fast", "prompt0")
        assert key0 in client._cache
        assert len(client._cache) == 3

    def test_default_cache_max(self):
        """Default config has cache_max_entries=500."""
        config = LLMRateConfig()
        assert config.cache_max_entries == 500

        client = _make_client()
        assert client._cache_max_entries == 500


# ---------------------------------------------------------------------------
# Class 4: LLMRateConfig
# ---------------------------------------------------------------------------

class TestLLMRateConfig:
    """Tests for the LLMRateConfig Pydantic model."""

    def test_default_values(self):
        """Verify LLMRateConfig defaults."""
        config = LLMRateConfig()
        assert config.rpm_fast == 120
        assert config.rpm_standard == 120
        assert config.rpm_deep == 30
        assert config.max_wait_seconds == 30.0
        assert config.cache_max_entries == 500

    def test_config_in_system_config(self):
        """Verify SystemConfig().llm_rate returns an LLMRateConfig instance."""
        sys_config = SystemConfig()
        assert isinstance(sys_config.llm_rate, LLMRateConfig)
        assert sys_config.llm_rate.rpm_fast == 120
