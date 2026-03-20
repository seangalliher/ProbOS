"""Tests for per-tier LLM endpoints — Phase 12."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from probos.config import CognitiveConfig
from probos.cognitive.llm_client import OpenAICompatibleClient, MockLLMClient
from probos.types import LLMRequest


# ---------------------------------------------------------------------------
# TestCognitiveConfigTiers (tests 1-5)
# ---------------------------------------------------------------------------


class TestCognitiveConfigTiers:
    """Tests for CognitiveConfig per-tier endpoint configuration."""

    def test_default_config_falls_back_to_shared(self):
        """Default config: all per-tier URLs are None, fall back to shared."""
        config = CognitiveConfig()
        for tier in ("fast", "standard", "deep"):
            tc = config.tier_config(tier)
            assert tc["base_url"] == config.llm_base_url
            assert tc["api_key"] == config.llm_api_key
            assert tc["timeout"] == config.llm_timeout_seconds

    def test_per_tier_url_overrides_shared(self):
        """Per-tier URL set: tier_config returns the override, not shared."""
        config = CognitiveConfig(
            llm_base_url="http://shared:8080/v1",
            llm_base_url_fast="http://ollama:11434/v1",
        )
        tc = config.tier_config("fast")
        assert tc["base_url"] == "http://ollama:11434/v1"
        # Standard should still use shared
        tc_std = config.tier_config("standard")
        assert tc_std["base_url"] == "http://shared:8080/v1"

    def test_per_tier_api_key_overrides_shared(self):
        """Per-tier API key set: tier_config returns the override."""
        config = CognitiveConfig(
            llm_api_key="shared-key",
            llm_api_key_fast="",  # Empty = no auth for Ollama
        )
        tc = config.tier_config("fast")
        assert tc["api_key"] == ""
        # Standard should still use shared key
        tc_std = config.tier_config("standard")
        assert tc_std["api_key"] == "shared-key"

    def test_mixed_overrides(self):
        """Mixed: fast has override, standard/deep fall back to shared."""
        config = CognitiveConfig(
            llm_base_url="http://proxy:8080/v1",
            llm_api_key="proxy-key",
            llm_base_url_fast="http://ollama:11434/v1",
            llm_api_key_fast="",
            llm_timeout_fast=15.0,
        )
        # Fast tier uses overrides
        tc_fast = config.tier_config("fast")
        assert tc_fast["base_url"] == "http://ollama:11434/v1"
        assert tc_fast["api_key"] == ""
        assert tc_fast["timeout"] == 15.0

        # Standard tier falls back to shared
        tc_std = config.tier_config("standard")
        assert tc_std["base_url"] == "http://proxy:8080/v1"
        assert tc_std["api_key"] == "proxy-key"
        assert tc_std["timeout"] == config.llm_timeout_seconds

        # Deep tier falls back to shared
        tc_deep = config.tier_config("deep")
        assert tc_deep["base_url"] == "http://proxy:8080/v1"
        assert tc_deep["api_key"] == "proxy-key"

    def test_tier_config_returns_correct_model(self):
        """tier_config() returns correct model name per tier."""
        config = CognitiveConfig(
            llm_model_fast="qwen3.5:35b",
            llm_model_standard="claude-sonnet-4.6",
            llm_model_deep="claude-opus-4.6",
        )
        assert config.tier_config("fast")["model"] == "qwen3.5:35b"
        assert config.tier_config("standard")["model"] == "claude-sonnet-4.6"
        assert config.tier_config("deep")["model"] == "claude-opus-4.6"


# ---------------------------------------------------------------------------
# TestCognitiveConfigSampling (AD-358: per-tier temperature & top_p)
# ---------------------------------------------------------------------------


class TestCognitiveConfigSampling:
    """Tests for per-tier temperature and top_p in CognitiveConfig."""

    def test_tier_config_returns_temperature_when_set(self):
        """Set llm_temperature_deep=0.7, verify deep returns 0.7, fast returns None."""
        config = CognitiveConfig(llm_temperature_deep=0.7)
        assert config.tier_config("deep")["temperature"] == 0.7
        assert config.tier_config("fast")["temperature"] is None

    def test_tier_config_returns_top_p_when_set(self):
        """Set llm_top_p_deep=0.95, verify deep returns 0.95, fast returns None."""
        config = CognitiveConfig(llm_top_p_deep=0.95)
        assert config.tier_config("deep")["top_p"] == 0.95
        assert config.tier_config("fast")["top_p"] is None

    def test_tier_defaults_not_set_returns_none(self):
        """Default CognitiveConfig() returns None for temperature and top_p in all tiers."""
        config = CognitiveConfig()
        for tier in ("fast", "standard", "deep"):
            tc = config.tier_config(tier)
            assert tc["temperature"] is None
            assert tc["top_p"] is None

    def test_tier_info_includes_sampling_params(self):
        """OpenAICompatibleClient with llm_temperature_fast=0.1 shows it in tier_info()."""
        config = CognitiveConfig(llm_temperature_fast=0.1)
        client = OpenAICompatibleClient(config=config)
        info = client.tier_info()
        assert info["fast"]["temperature"] == 0.1
        assert info["fast"]["top_p"] is None
        assert info["standard"]["temperature"] is None

    def test_llm_request_top_p_field(self):
        """LLMRequest accepts top_p parameter and defaults to None."""
        req_default = LLMRequest(prompt="test")
        assert req_default.top_p is None

        req_set = LLMRequest(prompt="test", top_p=0.9)
        assert req_set.top_p == 0.9


# ---------------------------------------------------------------------------
# TestOpenAICompatibleClientMultiEndpoint (tests 6-10)
# ---------------------------------------------------------------------------


class TestOpenAICompatibleClientMultiEndpoint:
    """Tests for OpenAICompatibleClient per-tier endpoint routing."""

    def test_separate_clients_for_different_base_urls(self):
        """Client creates separate httpx clients for different base_urls."""
        config = CognitiveConfig(
            llm_base_url="http://proxy:8080/v1",
            llm_base_url_fast="http://ollama:11434/v1",
        )
        client = OpenAICompatibleClient(config=config)
        # Fast tier has a different URL, so there should be 2 httpx clients
        assert len(client._clients) == 2
        assert "http://proxy:8080/v1|openai" in client._clients
        assert "http://ollama:11434/v1|openai" in client._clients

    def test_deduplicates_clients_for_shared_base_urls(self):
        """Client deduplicates httpx clients for shared base_urls."""
        config = CognitiveConfig(
            llm_base_url="http://proxy:8080/v1",
            # No per-tier URL overrides — all use shared
        )
        client = OpenAICompatibleClient(config=config)
        # All tiers share the same URL, so only 1 httpx client
        assert len(client._clients) == 1

    @pytest.mark.asyncio
    async def test_complete_routes_fast_to_fast_endpoint(self):
        """complete() tries fast tier first, then falls back through other tiers."""
        config = CognitiveConfig(
            llm_base_url="http://proxy:8080/v1",
            llm_base_url_fast="http://ollama:11434/v1",
            llm_model_fast="qwen3.5:35b",
        )
        client = OpenAICompatibleClient(config=config)
        # The request will fail (no server), falling back through all tiers
        request = LLMRequest(prompt="test", tier="fast")
        response = await client.complete(request)
        assert response.error is not None
        assert "All LLM tiers unavailable" in response.error

    @pytest.mark.asyncio
    async def test_complete_routes_standard_to_standard_endpoint(self):
        """complete() tries standard tier first, then falls back through other tiers."""
        config = CognitiveConfig(
            llm_base_url="http://proxy:8080/v1",
            llm_base_url_fast="http://ollama:11434/v1",
            llm_model_standard="claude-sonnet-4.6",
        )
        client = OpenAICompatibleClient(config=config)
        request = LLMRequest(prompt="test", tier="standard")
        response = await client.complete(request)
        assert response.error is not None
        assert "All LLM tiers unavailable" in response.error

    def test_tier_info_returns_per_tier_config(self):
        """tier_info() returns per-tier config with base_url and model."""
        config = CognitiveConfig(
            llm_base_url="http://proxy:8080/v1",
            llm_base_url_fast="http://ollama:11434/v1",
            llm_model_fast="qwen3.5:35b",
            llm_model_standard="claude-sonnet-4.6",
            llm_model_deep="claude-opus-4.6",
        )
        client = OpenAICompatibleClient(config=config)
        info = client.tier_info()
        assert info["fast"]["base_url"] == "http://ollama:11434/v1"
        assert info["fast"]["model"] == "qwen3.5:35b"
        assert info["standard"]["base_url"] == "http://proxy:8080/v1"
        assert info["standard"]["model"] == "claude-sonnet-4.6"
        assert info["deep"]["base_url"] == "http://proxy:8080/v1"
        assert info["deep"]["model"] == "claude-opus-4.6"

    def test_backward_compat_legacy_kwargs(self):
        """Legacy keyword args still work (backward compatibility)."""
        client = OpenAICompatibleClient(
            base_url="http://legacy:8080/v1",
            api_key="legacy-key",
            models={"fast": "gpt-4o-mini", "standard": "claude-sonnet-4-6", "deep": "claude-opus-4-0"},
            timeout=60.0,
        )
        assert client.base_url == "http://legacy:8080/v1"
        assert client.api_key == "legacy-key"
        assert client.timeout == 60.0
        assert client.models["fast"] == "gpt-4o-mini"
        assert client.models["standard"] == "claude-sonnet-4-6"
        # All tiers share same endpoint
        assert len(client._clients) == 1

    def test_models_property_reflects_tier_configs(self):
        """models property returns per-tier model names from tier_configs."""
        config = CognitiveConfig(
            llm_model_fast="local-model",
            llm_model_standard="cloud-model-a",
            llm_model_deep="cloud-model-b",
        )
        client = OpenAICompatibleClient(config=config)
        assert client.models == {
            "fast": "local-model",
            "standard": "cloud-model-a",
            "deep": "cloud-model-b",
        }


# ---------------------------------------------------------------------------
# TestConnectivityCheck (tests 11-13)
# ---------------------------------------------------------------------------


class TestConnectivityCheck:
    """Tests for per-tier connectivity checks."""

    @pytest.mark.asyncio
    async def test_check_connectivity_returns_per_tier_dict(self):
        """check_connectivity() returns per-tier status dict."""
        client = OpenAICompatibleClient(
            base_url="http://localhost:1",  # Nothing listening
            timeout=1.0,
        )
        try:
            result = await client.check_connectivity()
            assert isinstance(result, dict)
            assert set(result.keys()) == {"fast", "standard", "deep"}
            for tier, reachable in result.items():
                assert isinstance(reachable, bool)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_shared_endpoint_checked_once(self):
        """Shared endpoint is checked once, result reused for all sharing tiers."""
        config = CognitiveConfig(
            llm_base_url="http://localhost:1",
        )
        client = OpenAICompatibleClient(config=config)

        check_count = 0
        original_check = client._check_endpoint

        async def counting_check(tier: str) -> bool:
            nonlocal check_count
            check_count += 1
            return await original_check(tier)

        client._check_endpoint = counting_check

        try:
            result = await client.check_connectivity()
            # All tiers share the same URL, so _check_endpoint should be called once
            assert check_count == 1
            # All tiers should have the same result
            assert result["fast"] == result["standard"] == result["deep"]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_individual_tier_failure_doesnt_block_others(self):
        """Individual tier failure doesn't block other tiers."""
        config = CognitiveConfig(
            llm_base_url="http://localhost:1",  # unreachable for standard/deep
            llm_base_url_fast="http://localhost:2",  # also unreachable, but independent
        )
        client = OpenAICompatibleClient(config=config)

        try:
            result = await client.check_connectivity()
            # Both fail (nothing listening), but they're checked independently
            assert isinstance(result["fast"], bool)
            assert isinstance(result["standard"], bool)
            assert isinstance(result["deep"], bool)
            # Standard and deep share endpoint, should have same result
            assert result["standard"] == result["deep"]
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# TestBootSequence (tests 14-15)
# ---------------------------------------------------------------------------


class TestBootSequence:
    """Tests for boot sequence with per-tier connectivity."""

    @pytest.mark.asyncio
    async def test_all_tiers_unreachable_falls_back_to_mock(self):
        """All tiers unreachable -> _create_llm_client returns MockLLMClient."""
        from io import StringIO
        from rich.console import Console
        from probos.config import SystemConfig
        from probos.__main__ import _create_llm_client

        config = SystemConfig(
            cognitive=CognitiveConfig(
                llm_base_url="http://localhost:1",
            )
        )
        console = Console(file=StringIO())

        with patch(
            "probos.__main__.OpenAICompatibleClient"
        ) as MockClientClass:
            mock_instance = AsyncMock()
            mock_instance.check_connectivity = AsyncMock(
                return_value={"standard": False, "fast": False, "deep": False}
            )
            mock_instance.close = AsyncMock()
            MockClientClass.return_value = mock_instance

            client = await _create_llm_client(config, console)
            assert isinstance(client, MockLLMClient)

    @pytest.mark.asyncio
    async def test_partial_connectivity_returns_tier_status(self):
        """Partial connectivity is tracked in tier_status."""
        config = CognitiveConfig(
            llm_base_url="http://localhost:1",
            llm_base_url_fast="http://localhost:2",
        )
        # Construct a client and simulate partial connectivity
        client = OpenAICompatibleClient(config=config)
        client._tier_status = {"fast": True, "standard": False, "deep": False}
        info = client.tier_info()
        assert info["fast"]["reachable"] is True
        assert info["standard"]["reachable"] is False
        assert info["deep"]["reachable"] is False
        await client.close()
