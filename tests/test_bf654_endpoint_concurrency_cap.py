"""BF-654: per-endpoint in-flight concurrency cap for the LLM client.

On ``probos serve`` boot, a burst of ~80 concurrent background LLM calls all
hit the AD-636 lane-acquire timeout together and FAIL OPEN (``sem = None``) at
once, flooding the shared Copilot proxy into an empty-content storm. BF-654
adds a per-endpoint in-flight semaphore (keyed by ``base_url|api_format`` — the
httpx pool key) that bounds TOTAL simultaneous requests to each upstream,
composing with — not replacing — the priority lanes. CRITICAL (interactive)
calls bypass the cap so the Captain is never throttled; distinct endpoints
(the proxy vs. ollama for vision) get independent caps.

These tests use a REAL ``OpenAICompatibleClient`` (BF-287: real fixtures at the
substrate boundary) and patch only the transport (``_call_api`` /
``_complete_inner``) so the concurrency control flow is exercised without a
live endpoint. The lane is made large in the helper so the ENDPOINT cap — not
the lane — is the constraint under test.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import CognitiveConfig
from probos.types import LLMRequest, LLMResponse, Priority


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeRateConfig:
    """Minimal LLMRateConfig stub with the BF-654 field.

    RPM defaults are deliberately huge so the AD-617 per-tier rate limiter
    never throttles — isolating the endpoint in-flight cap as the sole
    concurrency constraint under test.
    """
    rpm_fast: int = 100_000
    rpm_standard: int = 100_000
    rpm_deep: int = 100_000
    max_wait_seconds: float = 30.0
    cache_max_entries: int = 10
    per_agent_hourly_token_cap: int = 0
    max_concurrent_calls: int = 6
    interactive_reserved_slots: int = 2
    max_inflight_per_endpoint: int = 8


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


def _make_client(
    *, max_inflight: int = 8, max_concurrent: int = 100, interactive_reserved: int = 2,
    config: CognitiveConfig | None = None,
) -> OpenAICompatibleClient:
    """Build a real client with a LARGE lane so the ENDPOINT cap binds first."""
    rate = _FakeRateConfig(
        max_concurrent_calls=max_concurrent,
        interactive_reserved_slots=interactive_reserved,
        max_inflight_per_endpoint=max_inflight,
    )
    return OpenAICompatibleClient(config=config, rate_config=rate)


class _ConcurrencyCounter:
    """Counts simultaneous entries into the faked transport, tracking the peak."""

    def __init__(self, dwell: float = 0.02) -> None:
        self.cur = 0
        self.peak = 0
        self.total = 0
        self._dwell = dwell

    async def call(self, request, model, client, **kwargs) -> LLMResponse:  # noqa: ANN001
        self.cur += 1
        self.total += 1
        self.peak = max(self.peak, self.cur)
        try:
            await asyncio.sleep(self._dwell)
            return LLMResponse(content="ok", model=model, tier="standard")
        finally:
            self.cur -= 1


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBF654EndpointConcurrencyCap:
    """BF-654: the per-endpoint in-flight cap and its composition with lanes."""

    @pytest.mark.asyncio
    async def test_endpoint_semaphores_created_by_default(self):
        """Default construction (no rate_config) creates the text endpoint cap at 8."""
        client = OpenAICompatibleClient()
        try:
            text_key = client._client_key("standard")
            assert text_key in client._endpoint_semaphores
            assert client._endpoint_semaphores[text_key]._value == 8
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_disabled_when_zero_no_semaphores(self):
        """max_inflight_per_endpoint <= 0 => no endpoint semaphores (escape hatch)."""
        client = _make_client(max_inflight=0)
        try:
            assert client._endpoint_semaphores == {}
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_at_most_N_concurrent_inflight_to_one_endpoint(self):
        """HEADLINE: at most `cap` requests are ever concurrently in flight to
        one endpoint under a 30-call background burst — and the SAME burst
        floods past 8 when the cap is disabled (proving the cap is load-bearing).
        """
        # WITH the cap (8): peak concurrent in-flight to the one text endpoint <= 8.
        counter = _ConcurrencyCounter()
        client = _make_client(max_inflight=8, max_concurrent=100)
        try:
            client._call_api = counter.call
            reqs = [LLMRequest(prompt=f"r{i}", tier="standard") for i in range(30)]
            results = await asyncio.gather(
                *(client.complete(r, priority=Priority.NORMAL) for r in reqs)
            )
            assert len(results) == 30
            assert all(r.content == "ok" for r in results)
            assert counter.total == 30  # every call really reached the transport
            assert counter.peak <= 8, f"endpoint cap breached: peak={counter.peak}"
            assert counter.peak >= 2  # sanity: calls genuinely overlapped
        finally:
            await client.close()

        # COUNTERFACTUAL: with the cap DISABLED, the identical 30-call burst
        # floods the endpoint (peak >> 8) — the BF-654 bug the cap fixes. If
        # this ever fails, the burst isn't 30-wide and the assertion above is
        # vacuous (i.e. the headline would still pass with the cap deleted).
        counter2 = _ConcurrencyCounter()
        disabled = _make_client(max_inflight=0, max_concurrent=100)
        try:
            disabled._call_api = counter2.call
            reqs2 = [LLMRequest(prompt=f"d{i}", tier="standard") for i in range(30)]
            await asyncio.gather(
                *(disabled.complete(r, priority=Priority.NORMAL) for r in reqs2)
            )
            assert counter2.peak > 8, (
                f"burst not wide enough to prove the cap: peak={counter2.peak}"
            )
        finally:
            await disabled.close()

    @pytest.mark.asyncio
    async def test_ollama_endpoint_independent_of_copilot_cap(self):
        """A distinct vision/ollama endpoint gets its own cap; text saturation
        never throttles it."""
        cfg = _make_config(
            llm_base_url_vision="http://127.0.0.1:11434",
            llm_model_vision="qwen2.5vl:3b",
            llm_api_format_vision="ollama",
        )
        client = _make_client(max_inflight=8, max_concurrent=100, config=cfg)
        try:
            text_key = client._client_key("standard")
            vision_key = client._client_key("vision")
            # Two distinct endpoints => two independent caps.
            assert text_key != vision_key
            assert text_key in client._endpoint_semaphores
            assert vision_key in client._endpoint_semaphores

            # Drain the TEXT endpoint cap to zero.
            text_sem = client._endpoint_semaphores[text_key]
            for _ in range(8):
                await text_sem.acquire()
            assert text_sem._value == 0

            # A vision call still completes promptly — its cap is untouched.
            counter = _ConcurrencyCounter()
            client._call_api = counter.call
            result = await asyncio.wait_for(
                client.complete(
                    LLMRequest(prompt="describe", tier="vision"),
                    priority=Priority.NORMAL,
                ),
                timeout=2.0,
            )
            assert result.content == "ok"
            assert text_sem._value == 0  # the vision call never touched the text cap
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_critical_bypasses_endpoint_cap(self):
        """CRITICAL (Captain) calls never acquire the endpoint cap, even when it
        is fully drained."""
        client = _make_client(max_inflight=8, max_concurrent=100)
        try:
            text_key = client._client_key("standard")
            text_sem = client._endpoint_semaphores[text_key]
            for _ in range(8):
                await text_sem.acquire()  # drain to 0
            assert text_sem._value == 0

            mock_resp = LLMResponse(content="ok", model="t", tier="standard")
            client._complete_inner = AsyncMock(return_value=mock_resp)

            result = await asyncio.wait_for(
                client.complete(
                    LLMRequest(prompt="captain", tier="standard"),
                    priority=Priority.CRITICAL,
                ),
                timeout=2.0,
            )
            assert result.content == "ok"
            # CRITICAL bypassed the cap entirely — the drained sem is untouched.
            assert text_sem._value == 0
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_no_deadlock_mixed_priorities(self):
        """Interactive CRITICAL calls proceed while background calls hold the
        endpoint cap — no cyclic wait, no hang."""
        client = _make_client(max_inflight=4, max_concurrent=6, interactive_reserved=2)

        async def fast_call(request, model, client_, **kwargs):  # noqa: ANN001
            await asyncio.sleep(0.01)
            return LLMResponse(content="ok", model=model, tier="standard")

        try:
            client._call_api = fast_call
            tasks = [
                asyncio.create_task(
                    client.complete(
                        LLMRequest(prompt=f"b{i}", tier="standard"),
                        priority=Priority.NORMAL,
                    )
                )
                for i in range(6)
            ]
            tasks += [
                asyncio.create_task(
                    client.complete(
                        LLMRequest(prompt=f"c{i}", tier="standard"),
                        priority=Priority.CRITICAL,
                    )
                )
                for i in range(3)
            ]
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5.0)
            assert len(results) == 9
            assert all(r.content == "ok" for r in results)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_endpoint_failopen_on_timeout(self, caplog):
        """A background call fails OPEN (does not hang) when the endpoint cap
        acquire times out."""
        client = _make_client(max_inflight=8, max_concurrent=100)
        try:
            client._endpoint_acquire_timeout = 0.05
            text_sem = client._endpoint_semaphores[client._client_key("standard")]
            for _ in range(8):
                await text_sem.acquire()  # drain to 0 => next acquire times out

            async def ok_call(request, model, client_, **kwargs):  # noqa: ANN001
                return LLMResponse(content="ok", model=model, tier="standard")

            client._call_api = ok_call
            with caplog.at_level(logging.WARNING):
                result = await asyncio.wait_for(
                    client.complete(
                        LLMRequest(prompt="x", tier="standard"),
                        priority=Priority.NORMAL,
                    ),
                    timeout=2.0,
                )
            assert result.content == "ok"  # failed open — did not hang
            assert "BF-654" in caplog.text
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_default_safe_byte_identical_path(self):
        """max_inflight_per_endpoint <= 0: no endpoint semaphores and no acquire
        attempt — byte-identical to pre-BF-654."""
        client = _make_client(max_inflight=0, max_concurrent=100)
        try:
            assert client._endpoint_semaphores == {}
            mock_resp = LLMResponse(content="ok", model="t", tier="standard")
            client._complete_inner = AsyncMock(return_value=mock_resp)
            result = await client.complete(
                LLMRequest(prompt="x", tier="standard"), priority=Priority.NORMAL
            )
            assert result.content == "ok"
            assert client._complete_inner.await_count == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_endpoint_semaphores_keyed_per_client_key(self):
        """The endpoint semaphore dict is keyed by _client_key (base_url|format),
        so text tiers collapse to one shared cap and vision keeps its own."""
        cfg = _make_config(
            llm_base_url_vision="http://127.0.0.1:11434",
            llm_model_vision="qwen2.5vl:3b",
            llm_api_format_vision="ollama",
        )
        client = _make_client(max_inflight=8, config=cfg)
        try:
            # fast/standard/deep all resolve to the one Copilot-proxy key.
            assert (
                client._client_key("fast")
                == client._client_key("standard")
                == client._client_key("deep")
            )
            text_sem = client._endpoint_semaphores[client._client_key("standard")]
            assert client._endpoint_semaphores[client._client_key("fast")] is text_sem
            assert client._endpoint_semaphores[client._client_key("deep")] is text_sem
            # vision is a separate key => a separate semaphore object.
            vision_sem = client._endpoint_semaphores[client._client_key("vision")]
            assert vision_sem is not text_sem
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_bf612_jitter_only_when_cap_enabled(self):
        """The BF-612 empty-200 recycle jitter fires only when the endpoint cap
        is enabled; a disabled client's retry path is byte-identical (no jitter).
        """
        empty = LLMResponse(content="", model="claude-sonnet-4.6", tier="standard")
        full = LLMResponse(content="hi", model="claude-sonnet-4.6", tier="standard")

        # ENABLED (default 8, no rate_config): the retry path jitters exactly once.
        enabled = OpenAICompatibleClient(config=_make_config())
        try:
            assert enabled._endpoint_semaphores  # cap enabled
            with patch.object(
                enabled, "_call_api", new_callable=AsyncMock, side_effect=[empty, full]
            ), patch.object(
                enabled, "_refresh_client", new_callable=AsyncMock
            ), patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ) as mock_unif:
                result = await enabled.complete(LLMRequest(prompt="hi", tier="standard"))
                assert result.content == "hi"
                assert mock_unif.call_count == 1  # jitter fired
        finally:
            await enabled.close()

        # DISABLED (0): identical retry path, NO jitter added.
        disabled = OpenAICompatibleClient(
            config=_make_config(),
            rate_config=_FakeRateConfig(max_inflight_per_endpoint=0),
        )
        try:
            assert disabled._endpoint_semaphores == {}  # cap disabled
            with patch.object(
                disabled, "_call_api", new_callable=AsyncMock, side_effect=[empty, full]
            ), patch.object(
                disabled, "_refresh_client", new_callable=AsyncMock
            ), patch(
                "probos.cognitive.llm_client.random.uniform", return_value=0.0
            ) as mock_unif2:
                result2 = await disabled.complete(LLMRequest(prompt="hi", tier="standard"))
                assert result2.content == "hi"
                assert mock_unif2.call_count == 0  # byte-identical: no jitter
        finally:
            await disabled.close()
