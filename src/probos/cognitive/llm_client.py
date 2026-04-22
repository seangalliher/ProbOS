"""LLM client abstraction with tiered routing and fallback chain."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from collections import OrderedDict, deque
from typing import Any

import httpx

from probos.types import LLMRequest, LLMResponse, Priority

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """Abstract LLM client interface."""

    @abstractmethod
    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        """Send a completion request and return the response."""

    def get_health_status(self) -> dict[str, Any]:
        """Return per-tier and overall LLM health status.

        Default implementation returns all-operational for subclasses
        that don't track health (e.g., MockLLMClient).
        """
        tiers = {t: {"status": "operational", "consecutive_failures": 0,
                      "last_success": None, "last_failure": None}
                 for t in ("fast", "standard", "deep")}
        return {"tiers": tiers, "overall": "operational"}

    async def close(self) -> None:
        """Clean up resources."""


class OpenAICompatibleClient(BaseLLMClient):
    """Multi-endpoint OpenAI-compatible LLM client with per-tier routing.

    Each tier (fast/standard/deep) can have its own:
    - base_url (different server)
    - api_key (different auth)
    - model (different model name)
    - timeout (different latency budget)
    - httpx.AsyncClient (separate connection pool)

    When per-tier config is not specified, falls back to shared values.
    Tiers sharing the same base_url share the same httpx.AsyncClient
    (no duplicate connection pools for the same server).
    """

    _UNREACHABLE_THRESHOLD = 3  # BF-069: consecutive failures before tier is unreachable

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080/v1",
        api_key: str = "",
        models: dict[str, str] | None = None,
        timeout: float = 30.0,
        default_tier: str = "standard",
        config: Any = None,  # CognitiveConfig — optional, overrides all above
        rate_config: Any = None,  # AD-617: LLMRateConfig — optional
    ) -> None:
        from probos.config import CognitiveConfig

        if config is not None and isinstance(config, CognitiveConfig):
            self._config = config
        else:
            # Build a CognitiveConfig from legacy keyword args
            models = models or {
                "fast": "gpt-4o-mini",
                "standard": "claude-sonnet-4-6",
                "deep": "claude-opus-4-0-20250115",
            }
            self._config = CognitiveConfig(
                llm_base_url=base_url,
                llm_api_key=api_key,
                llm_model_fast=models.get("fast", "gpt-4o-mini"),
                llm_model_standard=models.get("standard", "claude-sonnet-4"),
                llm_model_deep=models.get("deep", "claude-sonnet-4"),
                llm_timeout_seconds=timeout,
            )

        self.default_tier = self._config.default_llm_tier if hasattr(self._config, 'default_llm_tier') else default_tier

        # Resolve per-tier configs
        self._tier_configs: dict[str, dict] = {}
        for tier in ("fast", "standard", "deep"):
            self._tier_configs[tier] = self._config.tier_config(tier)

        # Create httpx clients, deduplicated by (base_url, api_key)
        self._clients: dict[str, httpx.AsyncClient] = {}  # base_url → client
        self._tier_status: dict[str, bool] = {}
        for tier in ("fast", "standard", "deep"):
            tc = self._tier_configs[tier]
            url = tc["base_url"]
            api_format = tc.get("api_format", "openai")

            # For Ollama native format, use the base URL directly (no /v1/ suffix).
            # For OpenAI format, ensure trailing slash so relative paths resolve.
            if api_format == "ollama":
                normalized = url.rstrip("/") + "/"
            else:
                normalized = url.rstrip("/") + "/"

            # Deduplicate clients by (url, format) — same Ollama server could
            # be used for both native and OpenAI endpoints, needing separate clients.
            client_key = f"{url}|{api_format}"
            if client_key not in self._clients:
                headers = {"Content-Type": "application/json"}
                if tc["api_key"]:
                    headers["Authorization"] = f"Bearer {tc['api_key']}"
                self._clients[client_key] = httpx.AsyncClient(
                    base_url=normalized,
                    headers=headers,
                    timeout=tc["timeout"],
                )

        # Simple response cache keyed by (tier, prompt_hash)
        self._cache: OrderedDict[str, LLMResponse] = OrderedDict()  # AD-617: LRU eviction
        self._cache_max_entries: int = 500  # AD-617: default, overridden by rate_config

        # BF-069: Per-tier failure tracking for health monitoring
        self._consecutive_failures: dict[str, int] = {t: 0 for t in ("fast", "standard", "deep")}
        self._last_success: dict[str, float] = {}  # tier -> monotonic timestamp
        self._last_failure: dict[str, float] = {}  # tier -> monotonic timestamp

        # Ollama keep_alive to prevent model unloading during idle periods
        self._ollama_keep_alive: str = getattr(self._config, "ollama_keep_alive", "30m")

        # AD-617: Rate governance config
        self._rate_config = rate_config
        if rate_config and hasattr(rate_config, 'cache_max_entries'):
            self._cache_max_entries = rate_config.cache_max_entries

        # AD-617: Per-tier token bucket rate limiting
        self._request_timestamps: dict[str, deque[float]] = {
            t: deque() for t in ("fast", "standard", "deep")
        }

        # AD-617: Per-tier 429 consecutive counter for exponential backoff
        self._consecutive_429s: dict[str, int] = {t: 0 for t in ("fast", "standard", "deep")}

        # AD-636: Priority-lane concurrency semaphores
        _max_concurrent = 6
        _interactive_reserved = 2
        if rate_config:
            if hasattr(rate_config, 'max_concurrent_calls'):
                _max_concurrent = rate_config.max_concurrent_calls
            if hasattr(rate_config, 'interactive_reserved_slots'):
                _interactive_reserved = rate_config.interactive_reserved_slots
        _background_slots = max(1, _max_concurrent - _interactive_reserved)
        self._interactive_semaphore = asyncio.Semaphore(_interactive_reserved)
        self._background_semaphore = asyncio.Semaphore(_background_slots)

    # Backward-compat properties
    @property
    def base_url(self) -> str:
        return self._config.llm_base_url

    @property
    def api_key(self) -> str:
        return self._config.llm_api_key

    @property
    def timeout(self) -> float:
        return self._config.llm_timeout_seconds

    @property
    def models(self) -> dict[str, str]:
        return {
            tier: self._tier_configs[tier]["model"]
            for tier in ("fast", "standard", "deep")
        }

    def _client_key(self, tier: str) -> str:
        """Return the client lookup key for a tier."""
        tc = self._tier_configs[tier]
        return f"{tc['base_url']}|{tc.get('api_format', 'openai')}"

    def _cache_key(self, tier: str, prompt: str) -> str:
        return f"{tier}:{hash(prompt)}"

    async def _wait_for_rate_limit(self, tier: str, rpm_limits: dict[str, int], max_wait: float = 30.0) -> bool:
        """AD-617: Token bucket rate limiter. Returns True if allowed, False if budget exhausted.

        Sliding window: count requests in the last 60 seconds.
        If at capacity, sleep until a slot opens (up to max_wait seconds).
        """
        limit = rpm_limits.get(tier, 60)
        if limit <= 0:
            return True  # Disabled

        timestamps = self._request_timestamps[tier]
        now = time.monotonic()

        # Evict expired entries (older than 60s)
        while timestamps and now - timestamps[0] > 60.0:
            timestamps.popleft()

        if len(timestamps) < limit:
            timestamps.append(now)
            return True

        # At capacity — compute wait time
        wait_until = timestamps[0] + 60.0
        wait_seconds = wait_until - now

        if wait_seconds > max_wait:
            logger.warning(
                "LLM rate limit exceeded (tier=%s, rpm=%d, wait=%.1fs > max=%.1fs)",
                tier, limit, wait_seconds, max_wait,
            )
            return False

        logger.info(
            "LLM rate limit backpressure: waiting %.1fs (tier=%s, rpm=%d)",
            wait_seconds, tier, limit,
        )
        await asyncio.sleep(wait_seconds)
        # Re-evict and add
        now = time.monotonic()
        while timestamps and now - timestamps[0] > 60.0:
            timestamps.popleft()
        timestamps.append(now)
        return True

    async def check_connectivity(self) -> dict[str, bool]:
        """Check connectivity for each tier independently.

        Returns {"fast": True/False, "standard": True/False, "deep": True/False}.
        Tiers sharing the same endpoint share the result (no duplicate checks).
        """
        results: dict[str, bool] = {}
        checked_urls: dict[str, bool] = {}

        for tier in ("fast", "standard", "deep"):
            tc = self._tier_configs[tier]
            url = tc["base_url"]
            if url in checked_urls:
                results[tier] = checked_urls[url]
            else:
                reachable = await self._check_endpoint(tier)
                checked_urls[url] = reachable
                results[tier] = reachable
            self._tier_status[tier] = results[tier]
            # BF-069: Reset failure counter on successful connectivity check
            if results[tier]:
                self._consecutive_failures[tier] = 0
                self._last_success[tier] = time.monotonic()

        return results

    async def _check_endpoint(self, tier: str) -> bool:
        """Check if a tier's endpoint is reachable.

        Sends a minimal completion request with a short timeout.
        Any response below HTTP 500 means the server is up.
        """
        tc = self._tier_configs[tier]
        client = self._clients[self._client_key(tier)]
        api_format = tc.get("api_format", "openai")
        try:
            if api_format == "ollama":
                resp = await client.post(
                    "api/chat",
                    json={
                        "model": tc["model"],
                        "messages": [{"role": "user", "content": "ping"}],
                        "stream": False,
                        "think": False,
                        "keep_alive": self._ollama_keep_alive,
                    },
                    timeout=5.0,
                )
            else:
                resp = await client.post(
                    "chat/completions",
                    json={
                        "model": tc["model"],
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                    timeout=5.0,
                )
            reachable = resp.status_code < 500
            if not reachable:
                logger.warning(
                    "LLM health check failed: tier=%s, model=%s, status=%d",
                    tier, tc["model"], resp.status_code,
                )
            return reachable
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
            logger.warning(
                "LLM health check failed: tier=%s, model=%s, url=%s, error=%s: %s",
                tier, tc["model"], tc["base_url"], type(e).__name__, e,
            )
            return False

    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        """Send a completion request with fallback chain.

        Routes to the appropriate tier's endpoint and client.
        Fallback order: requested tier → next available tier → cache → error.
        Tier fallback: fast → standard → deep.

        AD-636/637f: Priority.CRITICAL uses reserved interactive slots
        (Captain DMs, @mentions). NORMAL and LOW share background capacity.
        LOW is an observability label — same semaphore as NORMAL.
        """
        # AD-637f: CRITICAL uses reserved interactive slots; NORMAL and LOW share background
        sem = self._interactive_semaphore if priority == Priority.CRITICAL else self._background_semaphore
        try:
            await asyncio.wait_for(sem.acquire(), timeout=30.0)
        except asyncio.TimeoutError:
            # Fail-open: if semaphore times out, proceed without it (degrade, don't block Captain)
            logger.warning("AD-636: %s semaphore acquisition timed out, proceeding without", priority)
            sem = None  # type: ignore[assignment]

        try:
            return await self._complete_inner(request)
        finally:
            if sem is not None:
                sem.release()

    async def _complete_inner(self, request: LLMRequest) -> LLMResponse:
        """Inner completion logic (separated from semaphore for AD-636)."""
        tier = request.tier or self.default_tier

        # AD-617: Rate limit check before dispatch
        if hasattr(self, '_rate_config') and self._rate_config:
            rpm_limits = {
                "fast": self._rate_config.rpm_fast,
                "standard": self._rate_config.rpm_standard,
                "deep": self._rate_config.rpm_deep,
            }
            if not await self._wait_for_rate_limit(tier, rpm_limits, self._rate_config.max_wait_seconds):
                # Budget exhausted — try cache, then return error
                cache_key = self._cache_key(tier, request.prompt)
                if cache_key in self._cache:
                    cached = self._cache[cache_key]
                    return LLMResponse(
                        content=cached.content, model=cached.model, tier=tier,
                        tokens_used=cached.tokens_used, cached=True, request_id=request.id,
                    )
                return LLMResponse(
                    content="", model="", tier=tier,
                    error=f"LLM rate limit exceeded for tier {tier}",
                    request_id=request.id,
                )

        # Build fallback chain: requested tier first, then others in order
        _TIER_ORDER = ["fast", "standard", "deep"]
        fallback_tiers = [tier] + [t for t in _TIER_ORDER if t != tier]

        last_error = ""
        for attempt_tier in fallback_tiers:
            tc = self._tier_configs.get(attempt_tier, self._tier_configs["standard"])
            client = self._clients[self._client_key(attempt_tier)]
            model = tc["model"]
            api_format = tc.get("api_format", "openai")
            tier_timeout = tc["timeout"]

            # Skip tiers known to be unreachable at boot
            if self._tier_status.get(attempt_tier) is False and attempt_tier != tier:
                continue

            # Apply tier-level sampling defaults (caller override wins)
            effective_temp = request.temperature
            if effective_temp == 0.0 and tc.get("temperature") is not None:
                effective_temp = tc["temperature"]

            effective_top_p = request.top_p
            if effective_top_p is None and tc.get("top_p") is not None:
                effective_top_p = tc["top_p"]

            # AD-617: Inner retry loop for 429 backpressure (stays on same tier)
            _max_429_retries = 5
            for _429_attempt in range(_max_429_retries):
                try:
                    response = await self._call_api(
                        request, model, client, api_format=api_format,
                        timeout=tier_timeout,
                        effective_temp=effective_temp,
                        effective_top_p=effective_top_p,
                    )
                    # Cache successful responses (keyed by original tier)
                    cache_key = self._cache_key(tier, request.prompt)
                    self._cache[cache_key] = response
                    self._cache.move_to_end(cache_key)  # AD-617: LRU — most recent to end
                    # AD-617: Evict oldest if over limit
                    if hasattr(self, '_cache_max_entries'):
                        while len(self._cache) > self._cache_max_entries:
                            self._cache.popitem(last=False)
                    # BF-069: Reset failure counter on successful completion
                    prev_failures = self._consecutive_failures[attempt_tier]
                    self._consecutive_failures[attempt_tier] = 0
                    self._consecutive_429s[attempt_tier] = 0  # AD-617: Reset 429 backoff
                    self._last_success[attempt_tier] = time.monotonic()
                    if prev_failures > 0:
                        logger.info(
                            "LLM tier %s recovered after %d consecutive failures (model=%s)",
                            attempt_tier, prev_failures, model,
                        )
                    if attempt_tier != tier:
                        logger.info(
                            "LLM tier fallback: %s → %s (model=%s)",
                            tier, attempt_tier, model,
                        )
                    return response
                except httpx.ConnectError:
                    last_error = f"LLM endpoint unreachable at {tc['base_url']}"
                    self._consecutive_failures[attempt_tier] += 1
                    self._last_failure[attempt_tier] = time.monotonic()
                    logger.warning(
                        "%s (tier=%s, model=%s, consecutive_failures=%d/%d)",
                        last_error, attempt_tier, model,
                        self._consecutive_failures[attempt_tier],
                        self._UNREACHABLE_THRESHOLD,
                    )
                    break  # Move to next tier
                except httpx.TimeoutException:
                    last_error = f"LLM request timed out after {tc['timeout']:.0f}s"
                    self._consecutive_failures[attempt_tier] += 1
                    self._last_failure[attempt_tier] = time.monotonic()
                    logger.warning(
                        "%s (tier=%s, model=%s, consecutive_failures=%d/%d)",
                        last_error, attempt_tier, model,
                        self._consecutive_failures[attempt_tier],
                        self._UNREACHABLE_THRESHOLD,
                    )
                    break  # Move to next tier
                except httpx.HTTPStatusError as e:
                    status_code = e.response.status_code
                    if status_code == 429:
                        # AD-617: Specific 429 handling with exponential backoff
                        retry_after = e.response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                wait = float(retry_after)
                            except ValueError:
                                wait = 2.0
                        else:
                            # Exponential backoff: track consecutive 429s per tier
                            c429 = self._consecutive_429s.get(attempt_tier, 0) + 1
                            self._consecutive_429s[attempt_tier] = c429
                            wait = min(2 ** c429, 8.0)  # 2s, 4s, 8s, cap at 8

                        logger.warning(
                            "LLM endpoint returned 429 (tier=%s, wait=%.1fs, retry_after=%s)",
                            attempt_tier, wait, retry_after,
                        )
                        await asyncio.sleep(wait)
                        # Don't count 429 as a tier failure — retry same tier
                        continue
                    else:
                        last_error = f"LLM endpoint returned HTTP {status_code}"
                        self._consecutive_failures[attempt_tier] += 1
                        self._last_failure[attempt_tier] = time.monotonic()
                        logger.warning(
                            "%s (tier=%s, model=%s, consecutive_failures=%d/%d): %s",
                            last_error, attempt_tier, model,
                            self._consecutive_failures[attempt_tier],
                            self._UNREACHABLE_THRESHOLD,
                            e.response.text[:200],
                        )
                        break  # Move to next tier
                except Exception as e:
                    last_error = f"{type(e).__name__}: {e}"
                    self._consecutive_failures[attempt_tier] += 1
                    self._last_failure[attempt_tier] = time.monotonic()
                    logger.warning(
                        "LLM call failed (tier=%s, model=%s, consecutive_failures=%d/%d): %s",
                        attempt_tier, model,
                        self._consecutive_failures[attempt_tier],
                        self._UNREACHABLE_THRESHOLD,
                        last_error,
                    )
                    break  # Move to next tier

        # Try cache (keyed by original tier)
        cache_key = self._cache_key(tier, request.prompt)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            logger.debug("Using cached LLM response for request %s", request.id[:8])
            return LLMResponse(
                content=cached.content,
                model=cached.model,
                tier=tier,
                tokens_used=cached.tokens_used,
                cached=True,
                request_id=request.id,
            )

        # Final fallback: error response
        logger.error("All LLM tiers unavailable and no cached response for request %s", request.id[:8])
        return LLMResponse(
            content="",
            model="",
            tier=tier,
            error=f"All LLM tiers unavailable ({last_error})",
            request_id=request.id,
        )

    async def _call_api(
        self, request: LLMRequest, model: str, client: httpx.AsyncClient,
        *, api_format: str = "openai", timeout: float = 30.0,
        effective_temp: float | None = None, effective_top_p: float | None = None,
    ) -> LLMResponse:
        """Make the actual API call, routing by api_format."""
        if api_format == "ollama":
            return await self._call_ollama_native(
                request, model, client, timeout=timeout,
                effective_temp=effective_temp, effective_top_p=effective_top_p,
            )
        return await self._call_openai(
            request, model, client, timeout=timeout,
            effective_temp=effective_temp, effective_top_p=effective_top_p,
        )

    async def _call_openai(
        self, request: LLMRequest, model: str, client: httpx.AsyncClient,
        *, timeout: float = 30.0,
        effective_temp: float | None = None, effective_top_p: float | None = None,
    ) -> LLMResponse:
        """OpenAI-compatible chat/completions call."""
        if effective_temp is None:
            effective_temp = request.temperature
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": effective_temp,
            "max_tokens": request.max_tokens,
        }
        if effective_top_p is not None:
            payload["top_p"] = effective_top_p

        logger.debug("LLM request payload (openai): %s", json.dumps(payload, indent=2))

        resp = await client.post("chat/completions", json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        logger.debug("Raw HTTP response body: %s", data)

        message = data["choices"][0]["message"]
        content = message.get("content") or ""

        # Some models (e.g. qwen3 via Ollama's OpenAI compat) put output
        # in a "reasoning" field when content is empty.  Fall back to it
        # so callers still receive usable text.
        if not content and message.get("reasoning"):
            logger.debug("content empty, falling back to reasoning field")
            content = message["reasoning"]

        usage = data.get("usage", {})
        tokens_used = usage.get("total_tokens", 0)
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        return LLMResponse(
            content=content,
            model=model,
            tier=request.tier or self.default_tier,
            tokens_used=tokens_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached=False,
            request_id=request.id,
        )

    async def _call_ollama_native(
        self, request: LLMRequest, model: str, client: httpx.AsyncClient,
        *, timeout: float = 30.0,
        effective_temp: float | None = None, effective_top_p: float | None = None,
    ) -> LLMResponse:
        """Native Ollama /api/chat call with think disabled."""
        if effective_temp is None:
            effective_temp = request.temperature
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": self._ollama_keep_alive,
        }
        if request.max_tokens:
            payload.setdefault("options", {})["num_predict"] = request.max_tokens
        if effective_temp is not None:
            payload.setdefault("options", {})["temperature"] = effective_temp
        if effective_top_p is not None:
            payload.setdefault("options", {})["top_p"] = effective_top_p

        logger.debug("LLM request payload (ollama): %s", json.dumps(payload, indent=2))

        resp = await client.post("api/chat", json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        logger.debug("Raw HTTP response body: %s", data)

        message = data.get("message", {})
        content = message.get("content") or ""

        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        tokens_used = prompt_tokens + completion_tokens

        return LLMResponse(
            content=content,
            model=model,
            tier=request.tier or self.default_tier,
            tokens_used=tokens_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached=False,
            request_id=request.id,
        )

    def tier_info(self) -> dict[str, dict]:
        """Return per-tier config for /model display.

        Returns {"fast": {"base_url": ..., "model": ..., "reachable": ...}, ...}
        """
        info = {}
        for tier in ("fast", "standard", "deep"):
            tc = self._tier_configs[tier]
            info[tier] = {
                "base_url": tc["base_url"],
                "model": tc["model"],
                "timeout": tc["timeout"],
                "api_format": tc.get("api_format", "openai"),
                "reachable": self._tier_status.get(tier),
                "temperature": tc.get("temperature"),
                "top_p": tc.get("top_p"),
            }
        return info

    def get_health_status(self) -> dict[str, Any]:
        """BF-069: Return per-tier and overall LLM health status.

        Per-tier status:
        - "operational": 0 consecutive failures
        - "degraded": 1-2 consecutive failures
        - "unreachable": 3+ consecutive failures

        Overall status:
        - "operational": all tiers operational
        - "degraded": at least one tier operational, at least one not
        - "offline": all tiers unreachable
        """
        tiers: dict[str, dict[str, Any]] = {}
        for tier in ("fast", "standard", "deep"):
            failures = self._consecutive_failures.get(tier, 0)
            if failures == 0:
                status = "operational"
            elif failures < self._UNREACHABLE_THRESHOLD:
                status = "degraded"
                logger.info(
                    "LLM tier %s degraded: %d consecutive failures (threshold=%d)",
                    tier, failures, self._UNREACHABLE_THRESHOLD,
                )
            else:
                status = "unreachable"
                logger.warning(
                    "LLM tier %s unreachable: %d consecutive failures (threshold=%d), "
                    "last_success=%.1fs ago, last_failure=%.1fs ago",
                    tier, failures, self._UNREACHABLE_THRESHOLD,
                    time.monotonic() - self._last_success.get(tier, 0) if self._last_success.get(tier) else -1,
                    time.monotonic() - self._last_failure.get(tier, 0) if self._last_failure.get(tier) else -1,
                )
            tiers[tier] = {
                "status": status,
                "consecutive_failures": failures,
                "last_success": self._last_success.get(tier),
                "last_failure": self._last_failure.get(tier),
            }

        statuses = [t["status"] for t in tiers.values()]
        if all(s == "operational" for s in statuses):
            overall = "operational"
        elif all(s == "unreachable" for s in statuses):
            overall = "offline"
        else:
            overall = "degraded"

        return {"tiers": tiers, "overall": overall}

    async def close(self) -> None:
        """Close all httpx clients."""
        for client in self._clients.values():
            await client.aclose()


class MockLLMClient(BaseLLMClient):
    """Deterministic mock LLM client for testing.

    Returns canned responses based on input pattern matching.
    Patterns are checked in order; first match wins.
    """

    def __init__(self) -> None:
        self._patterns: list[tuple[str, str]] = []
        self._call_log: list[LLMRequest] = []
        self._default_response: str = '{"intents": []}'
        self._register_defaults()

    def get_health_status(self) -> dict[str, Any]:
        """BF-108: Report honestly — MockLLMClient has no real LLM."""
        tiers = {t: {"status": "offline", "consecutive_failures": 0,
                      "last_success": None, "last_failure": None}
                 for t in ("fast", "standard", "deep")}
        return {"tiers": tiers, "overall": "mock"}

    def _register_defaults(self) -> None:
        """Register default pattern → response mappings.

        Order matters — first match wins. New expansion patterns
        are registered before read/write to avoid false matches
        (e.g., "what files are in /tmp" matching read_file).
        """

        # --- Expansion agent patterns (registered first) ---

        # --- Introspection patterns (before expansion to catch NL queries) ---

        # explain_last
        self.add_pattern(
            r"what (?:just )?happened|explain.*(last|previous)|what did you (?:just )?do",
            self._make_explain_last_response,
        )

        # system_health
        self.add_pattern(
            r"how healthy|system (?:health|status)|are you ok",
            self._make_system_health_response,
        )

        # agent_info
        self.add_pattern(
            r"tell me about (.+) agents?|info.*(agent|file_reader|file_writer)",
            self._make_agent_info_response,
        )

        # why
        self.add_pattern(
            r"why did you|why.*(choose|pick|use|select)",
            self._make_why_response,
        )

        # introspect_memory
        self.add_pattern(
            r"do you have memory|memory status|how many.*remember|episodic|introspect.*memory",
            self._make_introspect_memory_response,
        )

        # introspect_system
        self.add_pattern(
            r"introspect.*system|system overview|describe.*system|how is the system",
            self._make_introspect_system_response,
        )

        # system_anomalies
        self.add_pattern(
            r"anomal|system anomal|are there any anomalies|detect.*anomal",
            self._make_system_anomalies_response,
        )

        # emergent_patterns
        self.add_pattern(
            r"emergent|show emergent|emergent pattern|cooperation cluster|tc_n",
            self._make_emergent_patterns_response,
        )

        # search_knowledge
        self.add_pattern(
            r"search (?:for|knowledge|across)|find in knowledge|what do you know about",
            self._make_search_knowledge_response,
        )

        # --- Bundled agent patterns (AD-252, registered last to avoid shadowing) ---

        # web_search
        self.add_pattern(
            r"search (?:the )?web (?:for )?|google|duckduckgo|look up online",
            self._make_web_search_response,
        )

        # read_page
        self.add_pattern(
            r"read (?:this )?(?:web ?)?page|summarize (?:this )?url|open (?:this )?link",
            self._make_read_page_response,
        )

        # get_weather
        self.add_pattern(
            r"weather (?:in|for|at)|what.s the weather|temperature (?:in|at)",
            self._make_get_weather_response,
        )

        # get_news
        self.add_pattern(
            r"news|headlines|current events|what.s happening",
            self._make_get_news_response,
        )

        # translate_text
        self.add_pattern(
            r"translate|translation|in (?:spanish|french|german|chinese|japanese)",
            self._make_translate_response,
        )

        # summarize_text
        self.add_pattern(
            r"summarize|summary|tldr|tl;dr|give me (?:the )?gist",
            self._make_summarize_response,
        )

        # calculate
        self.add_pattern(
            r"calculate|compute|what is \d|how much is|convert \d|math",
            self._make_calculate_response,
        )

        # manage_todo
        self.add_pattern(
            r"todo|to-do|task list|add.* to (?:my )?list",
            self._make_manage_todo_response,
        )

        # manage_notes
        self.add_pattern(
            r"(?:save|take|write|create|find|search) (?:a )?note|my notes",
            self._make_manage_notes_response,
        )

        # manage_schedule
        self.add_pattern(
            r"remind(?:er| me)|(?:set|create) (?:a )?reminder|schedule|(?:my )?calendar|upcoming|what.s (?:coming )?up",
            self._make_manage_schedule_response,
        )

        # HTTP fetch — must be before read_file (both can match URLs)
        self.add_pattern(
            r"fetch\s+(https?://[\w./\-:?&=%]+)",
            self._make_http_fetch_response,
        )

        # Run shell command
        self.add_pattern(
            r"run\s+(?:the\s+)?(?:command|cmd)\s+(.+)",
            self._make_run_command_response,
        )

        # Search files — must be before list_directory (both use paths)
        self.add_pattern(
            r"(?:find|search)\s+.*?files?\s+.*?((?:/|[A-Za-z]:\\)[\w./\\\-]+)",
            self._make_search_files_response,
        )

        # List directory — must be before read_file
        self.add_pattern(
            r"(?:list|what\s+files|files\s+in|what(?:'s|\s+is)\s+in)\s+.*?((?:/|[A-Za-z]:\\)[\w./\\\-]+)",
            self._make_list_directory_response,
        )

        # --- Original patterns ---

        # Single read_file intent
        self.add_pattern(
            r"read.*file.*((?:/|[A-Za-z]:\\)[\w./\\]+)",
            self._make_read_response,
        )

        # Multiple file reads (parallel)
        self.add_pattern(
            r"read.*(?:/|[A-Za-z]:\\)[\w./\\]+.*and.*(?:/|[A-Za-z]:\\)[\w./\\]+",
            self._make_parallel_read_response,
        )

        # Write file intent
        self.add_pattern(
            r"write.*(?:to|into)\s+((?:/|[A-Za-z]:\\)[\w./\\]+)",
            self._make_write_response,
        )

    def add_pattern(self, pattern: str, handler: Any) -> None:
        """Register a regex pattern with a handler (string or callable)."""
        self._patterns.append((pattern, handler))

    def set_default_response(self, response: str) -> None:
        """Set the response for unmatched inputs."""
        self._default_response = response

    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        """Match input against patterns and return canned response."""
        self._call_log.append(request)

        # Detect escalation arbitration requests
        if (
            request.system_prompt
            and "escalation arbiter" in request.system_prompt
        ):
            content = json.dumps({
                "action": "reject",
                "reason": "MockLLMClient cannot arbitrate — escalating to user",
            })
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        # Detect reflection requests (uses REFLECT_PROMPT as system prompt)
        if (
            request.system_prompt
            and "analyzing results returned by ProbOS agents" in request.system_prompt
        ):
            content = self._make_reflect_response(request.prompt)
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        # Detect agent design requests (AGENT_DESIGN_PROMPT signature)
        if "UNHANDLED INTENT:" in request.prompt and "CognitiveAgent" in request.prompt:
            content = self._make_agent_design_response(request.prompt)
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        # Detect skill design requests (SKILL_DESIGN_PROMPT signature)
        if "SKILL TO CREATE:" in request.prompt and "handle_" in request.prompt:
            content = self._make_skill_design_response(request.prompt)
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        # Detect research query generation requests
        if "INTENT TO BUILD:" in request.prompt and "search queries" in request.prompt:
            content = json.dumps(["python library docs", "API reference example"])
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        # Detect research synthesis requests
        if "DOCUMENTATION FETCHED:" in request.prompt and "reference section" in request.prompt:
            content = "Reference: Use the json module for parsing. Example: json.loads(data)."
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        # Detect cognitive agent decide() calls — CognitiveAgent sends
        # instructions as system_prompt and observation as user prompt.
        # Must be after escalation/reflect/design/skill/research detectors.
        if (
            request.system_prompt
            and "Intent:" in request.prompt
            and "UNHANDLED INTENT:" not in request.prompt
        ):
            content = self._make_cognitive_decide_response(request)
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        # Detect intent extraction requests
        if "no existing agent can handle it" in request.prompt and "intent_name_snake_case" in request.prompt:
            content = self._make_intent_extraction_response(request.prompt)
            return LLMResponse(
                content=content,
                model="mock",
                tier=request.tier,
                tokens_used=len(content) // 4,
                cached=False,
                request_id=request.id,
            )

        prompt = request.prompt.lower()

        # When the decomposer wraps the user text in system state context,
        # only pattern-match against the "User request: ..." portion to avoid
        # false positives from pool names and capability listings.
        user_req_marker = "user request: "
        marker_pos = prompt.rfind(user_req_marker)
        match_text = prompt[marker_pos + len(user_req_marker):] if marker_pos >= 0 else prompt

        for pattern, handler in self._patterns:
            match = re.search(pattern, match_text, re.IGNORECASE)
            if match:
                if callable(handler):
                    content = handler(prompt, match)
                else:
                    content = handler
                return LLMResponse(
                    content=content,
                    model="mock",
                    tier=request.tier,
                    tokens_used=len(content) // 4,
                    cached=False,
                    request_id=request.id,
                )

        return LLMResponse(
            content=self._default_response,
            model="mock",
            tier=request.tier,
            tokens_used=len(self._default_response) // 4,
            cached=False,
            request_id=request.id,
        )

    @property
    def call_count(self) -> int:
        return len(self._call_log)

    @property
    def last_request(self) -> LLMRequest | None:
        return self._call_log[-1] if self._call_log else None

    # Regex for extracting file paths (Unix and Windows)
    _PATH_WITH_EXT = re.compile(r'((?:/|[A-Za-z]:\\)[\w./\\\-]+\.[\w]+)')
    _PATH_ANY = re.compile(r'((?:/|[A-Za-z]:\\)[\w./\\\-]+)')

    def _extract_paths(self, text: str) -> list[str]:
        """Extract file paths from text, supporting both Unix and Windows."""
        paths = self._PATH_WITH_EXT.findall(text)
        if not paths:
            paths = self._PATH_ANY.findall(text)
        return paths

    def _make_read_response(self, prompt: str, match: re.Match) -> str:
        """Generate a read_file intent response."""
        paths = self._extract_paths(prompt)

        if len(paths) == 1:
            return json.dumps({
                "intents": [
                    {
                        "id": "t1",
                        "intent": "read_file",
                        "params": {"path": paths[0]},
                        "depends_on": [],
                        "use_consensus": False,
                    }
                ]
            })

        # Multiple paths — parallel reads
        intents = []
        for i, path in enumerate(paths):
            intents.append({
                "id": f"t{i + 1}",
                "intent": "read_file",
                "params": {"path": path},
                "depends_on": [],
                "use_consensus": False,
            })
        return json.dumps({"intents": intents})

    def _make_parallel_read_response(self, prompt: str, match: re.Match) -> str:
        """Generate parallel read_file intents."""
        paths = self._extract_paths(prompt)

        intents = []
        for i, path in enumerate(paths):
            intents.append({
                "id": f"t{i + 1}",
                "intent": "read_file",
                "params": {"path": path},
                "depends_on": [],
                "use_consensus": False,
            })
        return json.dumps({"intents": intents})

    def _make_write_response(self, prompt: str, match: re.Match) -> str:
        """Generate a write_file intent response."""
        paths = self._extract_paths(prompt)
        path = paths[0] if paths else "/tmp/output.txt"

        # Try to extract content — look for quoted strings or "write X to"
        content_match = re.search(
            r'write\s+["\']?(.+?)["\']?\s+(?:to|into)\s+(?:/|[A-Za-z]:\\)',
            prompt,
            re.IGNORECASE,
        )
        content = content_match.group(1).strip().strip("'\"") if content_match else "content"

        return json.dumps({
            "intents": [
                {
                    "id": "t1",
                    "intent": "write_file",
                    "params": {"path": path, "content": content},
                    "depends_on": [],
                    "use_consensus": True,
                }
            ]
        })

    def _make_list_directory_response(self, prompt: str, match: re.Match) -> str:
        """Generate a list_directory intent response."""
        paths = self._extract_paths(prompt)
        path = paths[0] if paths else match.group(1)
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "list_directory",
                "params": {"path": path},
                "depends_on": [],
                "use_consensus": False,
            }]
        })

    def _make_search_files_response(self, prompt: str, match: re.Match) -> str:
        """Generate a search_files intent response."""
        # Extract glob pattern from the prompt
        pattern_match = re.search(r'(?:named|matching|called)\s+(\S+)', prompt, re.IGNORECASE)
        if pattern_match:
            pattern = pattern_match.group(1)
        else:
            # Fallback: look for *.ext patterns
            glob_match = re.search(r'(\*[\w.*]+)', prompt)
            pattern = glob_match.group(1) if glob_match else "*"

        paths = self._extract_paths(prompt)
        path = paths[-1] if paths else match.group(1)

        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "search_files",
                "params": {"path": path, "pattern": pattern},
                "depends_on": [],
                "use_consensus": False,
            }]
        })

    def _make_run_command_response(self, prompt: str, match: re.Match) -> str:
        """Generate a run_command intent response."""
        command = match.group(1).strip().strip("'\"")
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "run_command",
                "params": {"command": command},
                "depends_on": [],
                "use_consensus": True,
            }]
        })

    def _make_http_fetch_response(self, prompt: str, match: re.Match) -> str:
        """Generate an http_fetch intent response."""
        url = match.group(1)
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "http_fetch",
                "params": {"url": url, "method": "GET"},
                "depends_on": [],
                "use_consensus": True,
            }]
        })

    def _make_reflect_response(self, prompt: str) -> str:
        """Generate a canned reflection synthesis from agent results."""
        return "Based on the agent results: The operation completed successfully."

    def _make_explain_last_response(self, prompt: str, match: re.Match) -> str:
        """Generate an explain_last intent response."""
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "explain_last",
                "params": {},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        })

    def _make_system_health_response(self, prompt: str, match: re.Match) -> str:
        """Generate a system_health intent response."""
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "system_health",
                "params": {},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        })

    def _make_agent_info_response(self, prompt: str, match: re.Match) -> str:
        """Generate an agent_info intent response."""
        # Try to extract agent type from the prompt
        type_match = re.search(r"about\s+(\w+)\s+agents?", prompt, re.IGNORECASE)
        agent_type = type_match.group(1) if type_match else "file_reader"
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "agent_info",
                "params": {"agent_type": agent_type},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        })

    def _make_why_response(self, prompt: str, match: re.Match) -> str:
        """Generate a why intent response."""
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "why",
                "params": {"question": prompt},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        })

    def _make_introspect_memory_response(self, prompt: str, match: re.Match) -> str:
        """Generate an introspect_memory intent response."""
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "introspect_memory",
                "params": {},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        })

    def _make_introspect_system_response(self, prompt: str, match: re.Match) -> str:
        """Generate an introspect_system intent response."""
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "introspect_system",
                "params": {},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        })

    def _make_system_anomalies_response(self, prompt: str, match: re.Match) -> str:
        """Generate a system_anomalies intent response."""
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "system_anomalies",
                "params": {},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        })

    def _make_emergent_patterns_response(self, prompt: str, match: re.Match) -> str:
        """Generate an emergent_patterns intent response."""
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "emergent_patterns",
                "params": {},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        })

    def _make_search_knowledge_response(self, prompt: str, match: re.Match) -> str:
        """Generate a search_knowledge intent response."""
        # Extract search query from the prompt
        query = prompt.strip()
        return json.dumps({
            "intents": [{
                "id": "t1",
                "intent": "search_knowledge",
                "params": {"query": query},
                "depends_on": [],
                "use_consensus": False,
            }],
            "reflect": True,
        })

    # --- Bundled agent response handlers (AD-252) ---

    def _make_web_search_response(self, prompt: str, match: re.Match) -> str:
        query = prompt.strip()
        return json.dumps({
            "intents": [{"id": "t1", "intent": "web_search", "params": {"query": query}, "depends_on": [], "use_consensus": False}],
            "reflect": True,
        })

    def _make_read_page_response(self, prompt: str, match: re.Match) -> str:
        url_match = re.search(r'(https?://\S+)', prompt)
        url = url_match.group(1) if url_match else "https://example.com"
        return json.dumps({
            "intents": [{"id": "t1", "intent": "read_page", "params": {"url": url}, "depends_on": [], "use_consensus": False}],
            "reflect": True,
        })

    def _make_get_weather_response(self, prompt: str, match: re.Match) -> str:
        location = prompt.strip().split()[-1] if prompt.strip() else "London"
        return json.dumps({
            "intents": [{"id": "t1", "intent": "get_weather", "params": {"location": location}, "depends_on": [], "use_consensus": False}],
            "reflect": True,
        })

    def _make_get_news_response(self, prompt: str, match: re.Match) -> str:
        return json.dumps({
            "intents": [{"id": "t1", "intent": "get_news", "params": {"source": "reuters"}, "depends_on": [], "use_consensus": False}],
            "reflect": True,
        })

    def _make_translate_response(self, prompt: str, match: re.Match) -> str:
        return json.dumps({
            "intents": [{"id": "t1", "intent": "translate_text", "params": {"text": prompt.strip(), "target_language": "Spanish"}, "depends_on": [], "use_consensus": False}],
            "reflect": True,
        })

    def _make_summarize_response(self, prompt: str, match: re.Match) -> str:
        return json.dumps({
            "intents": [{"id": "t1", "intent": "summarize_text", "params": {"text": prompt.strip()}, "depends_on": [], "use_consensus": False}],
            "reflect": True,
        })

    def _make_calculate_response(self, prompt: str, match: re.Match) -> str:
        expr_match = re.search(r'[\d+\-*/().]+', prompt)
        expr = expr_match.group(0) if expr_match else "2+2"
        return json.dumps({
            "intents": [{"id": "t1", "intent": "calculate", "params": {"expression": expr}, "depends_on": [], "use_consensus": False}],
        })

    def _make_manage_todo_response(self, prompt: str, match: re.Match) -> str:
        return json.dumps({
            "intents": [{"id": "t1", "intent": "manage_todo", "params": {"action": "list"}, "depends_on": [], "use_consensus": False}],
        })

    def _make_manage_notes_response(self, prompt: str, match: re.Match) -> str:
        return json.dumps({
            "intents": [{"id": "t1", "intent": "manage_notes", "params": {"action": "list"}, "depends_on": [], "use_consensus": False}],
        })

    def _make_manage_schedule_response(self, prompt: str, match: re.Match) -> str:
        return json.dumps({
            "intents": [{"id": "t1", "intent": "manage_schedule", "params": {"action": "list"}, "depends_on": [], "use_consensus": False}],
            "reflect": True,
        })

    def _make_agent_design_response(self, prompt: str) -> str:
        """Generate a valid CognitiveAgent subclass for an agent design request.

        Parses the intent name from the prompt and returns minimal valid
        CognitiveAgent subclass Python source code.
        """
        # Extract intent name from the prompt
        name_match = re.search(r'Name:\s*(\w+)', prompt)
        intent_name = name_match.group(1) if name_match else "count_words"

        # Build class name
        parts = intent_name.split("_")
        class_name = "".join(p.capitalize() for p in parts) + "Agent"

        return (
            'from probos.cognitive.cognitive_agent import CognitiveAgent\n'
            'from probos.types import IntentDescriptor\n'
            '\n'
            f'class {class_name}(CognitiveAgent):\n'
            f'    """Cognitive agent for {intent_name}."""\n'
            '\n'
            f'    agent_type = "{intent_name}"\n'
            f'    _handled_intents = {{"{intent_name}"}}\n'
            '    instructions = (\n'
            f'        "You are a specialist for {intent_name} tasks. "\n'
            '        "Given the input parameters, produce a clear, structured response. "\n'
            '        "Be concise and accurate."\n'
            '    )\n'
            '    intent_descriptors = [\n'
            '        IntentDescriptor(\n'
            f'            name="{intent_name}",\n'
            '            params={"text": "input text"},\n'
            f'            description="Handle {intent_name} intent",\n'
            '            requires_consensus=False,\n'
            '            requires_reflect=True,\n'
            '            tier="domain",\n'
            '        )\n'
            '    ]\n'
            '\n'
            '    async def act(self, decision: dict) -> dict:\n'
            '        if decision.get("action") == "error":\n'
            '            return {"success": False, "error": decision.get("reason")}\n'
            '        llm_output = decision.get("llm_output", "")\n'
            '        return {"success": True, "result": llm_output}\n'
        )

    def _make_skill_design_response(self, prompt: str) -> str:
        """Generate a valid skill handler function for a skill design request.

        Parses the intent name from the prompt and returns minimal valid
        skill handler Python source code.
        """
        # Extract intent name from the prompt
        name_match = re.search(r'Name:\s*(\w+)', prompt)
        intent_name = name_match.group(1) if name_match else "custom_task"

        return (
            'from probos.types import IntentMessage, IntentResult, LLMRequest\n'
            '\n'
            f'async def handle_{intent_name}(intent: IntentMessage, llm_client=None) -> IntentResult:\n'
            f'    """Handle {intent_name} intent."""\n'
            '    params = intent.params\n'
            '    text = params.get("text", "")\n'
            '    result_data = {"result": f"Processed: {text}"}\n'
            '    if llm_client:\n'
            '        request = LLMRequest(prompt=f"Process: {text}", tier="fast")\n'
            '        response = await llm_client.complete(request)\n'
            '        result_data = {"result": response.content}\n'
            '    return IntentResult(\n'
            '        intent_id=intent.id,\n'
            '        agent_id="skill",\n'
            '        success=True,\n'
            '        result=result_data,\n'
            '    )\n'
        )

    def _make_intent_extraction_response(self, prompt: str) -> str:
        """Generate a valid JSON intent extraction response.

        Parses the user request text from the prompt and returns
        a synthetic intent name.
        """
        # Extract user request text
        req_match = re.search(r'User request:\s*"(.+?)"', prompt)
        user_text = req_match.group(1) if req_match else "count words"

        # Derive a simple intent name from the user text
        words = re.findall(r'[a-z]+', user_text.lower())
        intent_name = "_".join(words[:3]) if words else "custom_task"

        return json.dumps({
            "name": intent_name,
            "description": f"Handle the request: {user_text}",
            "parameters": {"text": "input text"},
            "actual_values": {"text": user_text},
            "requires_consensus": False,
        })

    def _make_cognitive_decide_response(self, request: LLMRequest) -> str:
        """Generate a mock response for CognitiveAgent.decide() calls.

        The request has instructions as system_prompt and an observation
        as user prompt.  Returns a reasonable mock output that the
        agent's act() can parse.
        """
        # Extract the intent name from the user prompt
        intent_match = re.search(r'Intent:\s*(\w+)', request.prompt)
        intent_name = intent_match.group(1) if intent_match else "unknown"
        return f"Mock cognitive response for {intent_name}: processed successfully."
