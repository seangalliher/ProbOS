"""BF-674: bound shared-endpoint retries during empty-response outages."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import CognitiveConfig, LLMRateConfig
from probos.types import LLMRequest, LLMResponse, Priority


@dataclass
class _RateConfig:
    rpm_fast: int = 100_000
    rpm_standard: int = 100_000
    rpm_deep: int = 100_000
    max_wait_seconds: float = 30.0
    cache_max_entries: int = 10
    per_agent_hourly_token_cap: int = 0
    max_concurrent_calls: int = 6
    interactive_reserved_slots: int = 2
    max_inflight_per_endpoint: int = 8
    endpoint_failure_cooldown_seconds: float = 30.0


def _make_client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        config=CognitiveConfig(
            llm_base_url="http://127.0.0.1:8080/v1",
            llm_api_key="test-key",
            llm_model_fast="fast-model",
            llm_model_standard="standard-model",
            llm_model_deep="deep-model",
        ),
        rate_config=_RateConfig(),
    )


def _http_error(status_code: int, *, retry_after: str | None = None) -> Exception:
    request = httpx.Request("POST", "http://proxy.invalid/v1/chat/completions")
    headers = {"Retry-After": retry_after} if retry_after is not None else None
    response = httpx.Response(
        status_code,
        headers=headers,
        request=request,
        text="probe failure",
    )
    return httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=request,
        response=response,
    )


async def _open_breaker(client: OpenAICompatibleClient) -> tuple[int, float]:
    admission = await client._claim_endpoint_admission("standard")
    for attempt in range(3):
        opened = await client._record_endpoint_failure(
            "standard",
            admission,
            count_when_closed=True,
        )
        assert opened is (attempt == 2)
    state = client._endpoint_failure_states[client._client_key("standard")]
    return state.epoch, state.cooldown_until


@pytest.mark.asyncio
async def test_background_empty_outage_opens_shared_endpoint_cooldown() -> None:
    client = _make_client()
    empty = LLMResponse(content="", model="empty", tier="standard")

    try:
        with patch.object(
            client,
            "_call_api",
            new_callable=AsyncMock,
            return_value=empty,
        ) as call_api, patch(
            "probos.cognitive.llm_client.random.uniform",
            return_value=0.0,
        ):
            first = await client.complete(
                LLMRequest(prompt="first", tier="standard"),
                priority=Priority.NORMAL,
            )
            attempts_after_first = call_api.await_count
            second = await client.complete(
                LLMRequest(prompt="second", tier="standard"),
                priority=Priority.NORMAL,
            )

        assert first.error is not None
        assert attempts_after_first == 6
        assert call_api.await_count == attempts_after_first
        assert second.error is not None
        assert "cooldown" in second.error.lower()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_critical_call_bypasses_cooldown_and_recovers_endpoint() -> None:
    client = _make_client()
    empty = LLMResponse(content="", model="empty", tier="standard")
    full = LLMResponse(content="recovered", model="standard-model", tier="standard")

    try:
        with patch.object(
            client,
            "_call_api",
            new_callable=AsyncMock,
            return_value=empty,
        ), patch(
            "probos.cognitive.llm_client.random.uniform",
            return_value=0.0,
        ):
            failed = await client.complete(
                LLMRequest(prompt="open", tier="standard"),
                priority=Priority.NORMAL,
            )
        assert failed.error is not None
        assert client._endpoint_cooldown_remaining("standard") > 0.0

        with patch.object(
            client,
            "_call_api",
            new_callable=AsyncMock,
            return_value=full,
        ) as call_api:
            critical = await client.complete(
                LLMRequest(prompt="captain", tier="standard"),
                priority=Priority.CRITICAL,
            )
            background = await client.complete(
                LLMRequest(prompt="resumed", tier="standard"),
                priority=Priority.NORMAL,
            )

        assert critical.content == "recovered"
        assert background.content == "recovered"
        assert call_api.await_count == 2
        assert client._endpoint_cooldown_remaining("standard") == 0.0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_expired_cooldown_allows_only_one_half_open_probe() -> None:
    client = _make_client()
    key = client._client_key("standard")
    state = client._endpoint_failure_states[key]
    state.failures = 3
    state.cooldown_until = time.monotonic() - 1.0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_success(*_args, **_kwargs) -> LLMResponse:
        entered.set()
        await release.wait()
        return LLMResponse(
            content="probe-ok",
            model="standard-model",
            tier="standard",
        )

    first: asyncio.Task[LLMResponse] | None = None
    second: asyncio.Task[LLMResponse] | None = None
    try:
        with patch.object(
            client,
            "_call_api",
            new_callable=AsyncMock,
            side_effect=blocked_success,
        ) as call_api:
            first = asyncio.create_task(
                client.complete(
                    LLMRequest(prompt="probe", tier="standard"),
                    priority=Priority.NORMAL,
                )
            )
            await asyncio.wait_for(entered.wait(), timeout=2.0)
            second = asyncio.create_task(
                client.complete(
                    LLMRequest(prompt="queued", tier="standard"),
                    priority=Priority.NORMAL,
                )
            )
            queued = await asyncio.wait_for(second, timeout=2.0)
            release.set()
            recovered = await asyncio.wait_for(first, timeout=2.0)

        assert queued.error is not None
        assert "cooldown" in queued.error.lower()
        assert recovered.content == "probe-ok"
        assert call_api.await_count == 1
        assert state.recovery_probe_inflight is False
        assert state.cooldown_until == 0.0
    finally:
        release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await client.close()


@pytest.mark.asyncio
async def test_cancel_while_half_open_waits_for_capacity_releases_claim() -> None:
    client = _make_client()
    key = client._client_key("standard")
    state = client._endpoint_failure_states[key]
    endpoint = client._endpoint_semaphores[key]
    state.failures = 3
    state.cooldown_until = time.monotonic() - 1.0
    for _ in range(8):
        await endpoint.acquire()

    task: asyncio.Task[LLMResponse] | None = None
    try:
        task = asyncio.create_task(
            client.complete(
                LLMRequest(prompt="cancel", tier="standard"),
                priority=Priority.NORMAL,
            )
        )
        for _ in range(100):
            if state.recovery_probe_inflight:
                break
            await asyncio.sleep(0)
        assert state.recovery_probe_inflight is True
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert state.recovery_probe_inflight is False
    finally:
        while endpoint._value < 8:
            endpoint.release()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await client.close()


@pytest.mark.asyncio
async def test_zero_cooldown_preserves_repeated_attempts() -> None:
    rate = _RateConfig(endpoint_failure_cooldown_seconds=0.0)
    client = OpenAICompatibleClient(
        config=CognitiveConfig(
            llm_base_url="http://127.0.0.1:8080/v1",
            llm_api_key="test-key",
            llm_model_fast="fast-model",
            llm_model_standard="standard-model",
            llm_model_deep="deep-model",
        ),
        rate_config=rate,
    )
    empty = LLMResponse(content="", model="empty", tier="standard")

    try:
        with patch.object(
            client,
            "_call_api",
            new_callable=AsyncMock,
            return_value=empty,
        ) as call_api, patch(
            "probos.cognitive.llm_client.random.uniform",
            return_value=0.0,
        ):
            await client.complete(LLMRequest(prompt="one", tier="standard"))
            await client.complete(LLMRequest(prompt="two", tier="standard"))

        assert call_api.await_count == 12
        assert client._endpoint_cooldown_remaining("standard") == 0.0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_health_reports_shared_endpoint_cooldown() -> None:
    client = _make_client()
    key = client._client_key("standard")
    client._endpoint_failure_states[key].cooldown_until = 100.0

    try:
        with patch(
            "probos.cognitive.llm_client.time.monotonic",
            return_value=90.0,
        ):
            status = client.get_health_status()

        for tier in ("standard", "fast", "deep"):
            assert (
                status["tiers"][tier]["endpoint_cooldown_remaining_seconds"]
                == 10.0
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_stale_normal_success_does_not_close_newer_outage() -> None:
    client = _make_client()
    admission = await client._claim_endpoint_admission("standard")

    try:
        epoch, deadline = await _open_breaker(client)
        await client._record_endpoint_success("standard", admission)
        state = client._endpoint_failure_states[client._client_key("standard")]

        assert state.epoch == epoch
        assert state.cooldown_until == deadline
        assert state.failures == 3
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_stale_half_open_success_does_not_close_reopened_outage() -> None:
    client = _make_client()
    state = client._endpoint_failure_states[client._client_key("standard")]
    state.failures = 3
    state.cooldown_until = time.monotonic() - 1.0

    try:
        admission = await client._claim_endpoint_admission("standard")
        assert admission.recovery_probe is True
        assert await client._record_endpoint_failure(
            "standard",
            admission,
            count_when_closed=False,
        ) is True
        reopened_epoch = state.epoch
        reopened_deadline = state.cooldown_until

        await client._record_endpoint_success("standard", admission)

        assert state.epoch == reopened_epoch
        assert state.cooldown_until == reopened_deadline
        assert state.failures == 3
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_post_trip_inflight_failure_does_not_extend_outage_epoch() -> None:
    client = _make_client()
    admission = await client._claim_endpoint_admission("standard")

    try:
        epoch, deadline = await _open_breaker(client)
        assert await client._record_endpoint_failure(
            "standard",
            admission,
            count_when_closed=True,
        ) is False
        state = client._endpoint_failure_states[client._client_key("standard")]

        assert state.epoch == epoch
        assert state.cooldown_until == deadline
        assert state.failures == 3
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("failure", "expected_attempts"),
    [
        (httpx.ConnectError("down"), 1),
        (httpx.TimeoutException("slow"), 1),
        (_http_error(503), 1),
        (RuntimeError("unexpected"), 1),
        (_http_error(429, retry_after="0"), 5),
    ],
    ids=["connect", "timeout", "http", "generic", "rate-limit"],
)
@pytest.mark.asyncio
async def test_failed_half_open_probe_reopens_without_alias_fallback(
    failure: Exception,
    expected_attempts: int,
) -> None:
    client = _make_client()
    state = client._endpoint_failure_states[client._client_key("standard")]
    state.failures = 3
    state.cooldown_until = time.monotonic() - 1.0

    try:
        with patch.object(
            client,
            "_call_api",
            new_callable=AsyncMock,
            side_effect=failure,
        ) as call_api:
            result = await client.complete(
                LLMRequest(prompt="half-open-failure", tier="standard"),
                priority=Priority.NORMAL,
            )

        assert result.error is not None
        assert call_api.await_count == expected_attempts
        assert state.epoch == 1
        assert state.cooldown_until > time.monotonic()
        assert state.recovery_probe_inflight is False
    finally:
        await client.close()


@pytest.mark.parametrize("phase", ["initial", "retry"])
@pytest.mark.asyncio
async def test_cancel_half_open_during_transport_releases_claim(phase: str) -> None:
    client = _make_client()
    state = client._endpoint_failure_states[client._client_key("standard")]
    state.failures = 3
    state.cooldown_until = time.monotonic() - 1.0
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def transport(*_args, **_kwargs) -> LLMResponse:
        nonlocal calls
        calls += 1
        if phase == "retry" and calls == 1:
            return LLMResponse(content="", model="empty", tier="standard")
        entered.set()
        await release.wait()
        return LLMResponse(content="late", model="standard-model", tier="standard")

    task: asyncio.Task[LLMResponse] | None = None
    try:
        with patch.object(client, "_call_api", side_effect=transport), patch(
            "probos.cognitive.llm_client.random.uniform",
            return_value=0.0,
        ):
            task = asyncio.create_task(
                client.complete(
                    LLMRequest(prompt=f"cancel-{phase}", tier="standard"),
                    priority=Priority.NORMAL,
                )
            )
            await asyncio.wait_for(entered.wait(), timeout=2.0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert state.recovery_probe_inflight is False
        assert client._background_semaphore._value == 4
        assert client._endpoint_semaphores[client._client_key("standard")]._value == 8
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await client.close()


@pytest.mark.asyncio
async def test_active_cooldown_returns_original_tier_cache_without_transport() -> None:
    client = _make_client()
    prompt = "cached-during-cooldown"
    cached = LLMResponse(
        content="cached answer",
        model="cached-model",
        tier="standard",
    )
    client._cache[client._cache_key("standard", prompt)] = cached
    state = client._endpoint_failure_states[client._client_key("standard")]
    state.failures = 3
    state.cooldown_until = time.monotonic() + 30.0

    try:
        with patch.object(
            client,
            "_call_api",
            new_callable=AsyncMock,
        ) as call_api:
            result = await client.complete(
                LLMRequest(prompt=prompt, tier="standard"),
                priority=Priority.NORMAL,
            )

        assert result.content == "cached answer"
        assert result.cached is True
        call_api.assert_not_awaited()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_distinct_endpoints_have_independent_cooldown_state() -> None:
    client = OpenAICompatibleClient(
        config=CognitiveConfig(
            llm_base_url="http://127.0.0.1:8080/v1",
            llm_api_key="test-key",
            llm_model_fast="fast-model",
            llm_model_standard="standard-model",
            llm_model_deep="deep-model",
            llm_base_url_vision="http://127.0.0.1:11434/v1",
            llm_model_vision="vision-model",
            llm_api_format_vision="openai",
        ),
        rate_config=_RateConfig(),
    )
    text_state = client._endpoint_failure_states[client._client_key("standard")]
    text_state.failures = 3
    text_state.cooldown_until = time.monotonic() + 30.0

    try:
        with patch.object(
            client,
            "_call_api",
            new_callable=AsyncMock,
            return_value=LLMResponse(
                content="vision-ok",
                model="vision-model",
                tier="vision",
            ),
        ) as call_api:
            result = await client.complete(
                LLMRequest(prompt="describe", tier="vision"),
                priority=Priority.NORMAL,
            )

        assert result.content == "vision-ok"
        call_api.assert_awaited_once()
        assert text_state.cooldown_until > time.monotonic()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_periodic_probe_participates_in_half_open_recovery() -> None:
    client = _make_client()
    key = client._client_key("standard")
    state = client._endpoint_failure_states[key]
    state.failures = 3
    state.cooldown_until = time.monotonic() - 1.0
    pooled = client._clients[key]
    response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "pong"}}]},
        request=httpx.Request("POST", "http://proxy.invalid/v1/chat/completions"),
    )

    try:
        with patch.object(
            pooled,
            "post",
            new_callable=AsyncMock,
            return_value=response,
        ):
            assert await client._check_endpoint(
                "standard",
                respect_cooldown=True,
            ) is True

        assert state.cooldown_until == 0.0
        assert state.recovery_probe_inflight is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_periodic_probe_failure_reopens_half_open_cooldown() -> None:
    client = _make_client()
    key = client._client_key("standard")
    state = client._endpoint_failure_states[key]
    state.failures = 3
    state.cooldown_until = time.monotonic() - 1.0
    pooled = client._clients[key]
    response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": ""}}]},
        request=httpx.Request("POST", "http://proxy.invalid/v1/chat/completions"),
    )

    try:
        with patch.object(
            pooled,
            "post",
            new_callable=AsyncMock,
            return_value=response,
        ):
            assert await client._check_endpoint(
                "standard",
                respect_cooldown=True,
            ) is False

        assert state.epoch == 1
        assert state.cooldown_until > time.monotonic()
        assert state.recovery_probe_inflight is False
    finally:
        await client.close()


def test_rate_config_cooldown_defaults_and_bounds() -> None:
    assert LLMRateConfig().endpoint_failure_cooldown_seconds == 15.0
    assert (
        LLMRateConfig(
            endpoint_failure_cooldown_seconds=0.0
        ).endpoint_failure_cooldown_seconds
        == 0.0
    )
    with pytest.raises(ValidationError):
        LLMRateConfig(endpoint_failure_cooldown_seconds=-0.1)
    with pytest.raises(ValidationError):
        LLMRateConfig(endpoint_failure_cooldown_seconds=300.1)

@pytest.mark.asyncio
async def test_half_open_error_envelope_reopens_without_alias_fallback() -> None:
    client = _make_client()
    state = client._endpoint_failure_states[client._client_key("standard")]
    state.failures = 3
    state.cooldown_until = time.monotonic() - 1.0
    error_response = LLMResponse(
        content="",
        model="standard-model",
        tier="standard",
        error="proxy returned no completion",
    )

    try:
        with patch.object(
            client,
            "_call_api",
            new_callable=AsyncMock,
            return_value=error_response,
        ) as call_api:
            result = await client.complete(
                LLMRequest(prompt="error-envelope", tier="standard"),
                priority=Priority.NORMAL,
            )

        assert result.error is not None
        assert "proxy returned no completion" in result.error
        call_api.assert_awaited_once()
        assert state.epoch == 1
        assert state.cooldown_until > time.monotonic()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_critical_error_envelope_does_not_close_active_outage() -> None:
    client = _make_client()
    state = client._endpoint_failure_states[client._client_key("standard")]
    state.epoch = 4
    state.failures = 3
    state.cooldown_until = time.monotonic() + 30.0
    deadline = state.cooldown_until
    error_response = LLMResponse(
        content="",
        model="standard-model",
        tier="standard",
        error="critical proxy error",
    )

    try:
        with patch.object(
            client,
            "_call_api",
            new_callable=AsyncMock,
            return_value=error_response,
        ) as call_api:
            result = await client.complete(
                LLMRequest(prompt="captain-error", tier="standard"),
                priority=Priority.CRITICAL,
            )

        assert result.error is not None
        assert call_api.await_count == 3
        assert state.epoch == 4
        assert state.failures == 3
        assert state.cooldown_until == deadline
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_half_open_persistent_empty_reopens_without_alias_fallback() -> None:
    client = _make_client()
    state = client._endpoint_failure_states[client._client_key("standard")]
    state.failures = 3
    state.cooldown_until = time.monotonic() - 1.0
    empty = LLMResponse(content="", model="standard-model", tier="standard")

    try:
        with patch.object(
            client,
            "_call_api",
            new_callable=AsyncMock,
            return_value=empty,
        ) as call_api, patch(
            "probos.cognitive.llm_client.random.uniform",
            return_value=0.0,
        ):
            result = await client.complete(
                LLMRequest(prompt="empty-half-open", tier="standard"),
                priority=Priority.NORMAL,
            )

        assert result.error is not None
        assert call_api.await_count == 2
        assert state.epoch == 1
        assert state.cooldown_until > time.monotonic()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_failed_endpoint_still_falls_back_to_independent_text_endpoint() -> None:
    client = OpenAICompatibleClient(
        config=CognitiveConfig(
            llm_base_url="http://primary.invalid/v1",
            llm_api_key="test-key",
            llm_model_fast="fast-model",
            llm_model_standard="standard-model",
            llm_model_deep="deep-model",
            llm_base_url_deep="http://independent.invalid/v1",
        ),
        rate_config=_RateConfig(),
    )
    primary_state = client._endpoint_failure_states[
        client._client_key("standard")
    ]
    primary_state.failures = 3
    primary_state.cooldown_until = time.monotonic() - 1.0
    attempted_models: list[str] = []

    async def fail_primary_then_succeed_deep(
        _request,
        model: str,
        _http_client,
        **_kwargs,
    ) -> LLMResponse:
        attempted_models.append(model)
        if model == "standard-model":
            raise httpx.ConnectError("primary unavailable")
        return LLMResponse(content="deep-ok", model=model, tier="deep")

    try:
        with patch.object(
            client,
            "_call_api",
            side_effect=fail_primary_then_succeed_deep,
        ):
            result = await client.complete(
                LLMRequest(prompt="independent-fallback", tier="standard"),
                priority=Priority.NORMAL,
            )

        assert result.content == "deep-ok"
        assert attempted_models == ["standard-model", "deep-model"]
        assert primary_state.cooldown_until > time.monotonic()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_same_url_different_format_health_probes_are_independent() -> None:
    client = OpenAICompatibleClient(
        config=CognitiveConfig(
            llm_base_url="http://same.invalid/v1",
            llm_api_key="test-key",
            llm_model_fast="fast-model",
            llm_model_standard="standard-model",
            llm_model_deep="deep-model",
            llm_api_format_standard="ollama",
        ),
        rate_config=_RateConfig(),
    )
    openai_client = client._clients[client._client_key("fast")]
    ollama_client = client._clients[client._client_key("standard")]
    openai_response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "pong"}}]},
        request=httpx.Request("POST", "http://same.invalid/v1/chat/completions"),
    )
    ollama_response = httpx.Response(
        200,
        json={"message": {"content": "pong"}},
        request=httpx.Request("POST", "http://same.invalid/v1/api/chat"),
    )

    try:
        with patch.object(
            openai_client,
            "post",
            new_callable=AsyncMock,
            return_value=openai_response,
        ) as openai_post, patch.object(
            ollama_client,
            "post",
            new_callable=AsyncMock,
            return_value=ollama_response,
        ) as ollama_post:
            results = await client.check_connectivity()

        assert results["fast"] is True
        assert results["standard"] is True
        openai_post.assert_awaited_once()
        ollama_post.assert_awaited_once()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_repeated_cancel_during_blocked_release_drains_claim() -> None:
    client = _make_client()
    state = client._endpoint_failure_states[client._client_key("standard")]
    state.failures = 3
    state.cooldown_until = time.monotonic() - 1.0
    transport_entered = asyncio.Event()
    release_entered = asyncio.Event()
    release_cleanup = asyncio.Event()
    original_release = client._release_endpoint_admission

    async def blocked_transport(*_args, **_kwargs) -> LLMResponse:
        transport_entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def blocked_release(tier, admission):  # noqa: ANN001
        release_entered.set()
        await release_cleanup.wait()
        await original_release(tier, admission)

    task: asyncio.Task[LLMResponse] | None = None
    try:
        with patch.object(client, "_call_api", side_effect=blocked_transport), patch.object(
            client,
            "_release_endpoint_admission",
            side_effect=blocked_release,
        ):
            task = asyncio.create_task(
                client.complete(
                    LLMRequest(prompt="repeat-cancel", tier="standard"),
                    priority=Priority.NORMAL,
                )
            )
            await asyncio.wait_for(transport_entered.wait(), timeout=2.0)
            task.cancel()
            await asyncio.wait_for(release_entered.wait(), timeout=2.0)
            task.cancel()
            await asyncio.sleep(0)
            release_cleanup.set()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert state.recovery_probe_inflight is False
    finally:
        release_cleanup.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await client.close()


@pytest.mark.asyncio
async def test_production_health_loop_does_not_steal_completion_probe() -> None:
    client = _make_client()
    key = client._client_key("standard")
    state = client._endpoint_failure_states[key]
    state.failures = 3
    state.cooldown_until = time.monotonic() - 1.0
    client._consecutive_failures["standard"] = 3
    completion_entered = asyncio.Event()
    completion_release = asyncio.Event()
    shared_post = AsyncMock()
    client._clients[key].post = shared_post
    original_check = client.check_connectivity
    client.check_connectivity = AsyncMock(wraps=original_check)

    async def blocked_completion(*_args, **_kwargs) -> LLMResponse:
        completion_entered.set()
        await completion_release.wait()
        return LLMResponse(
            content="completion-ok",
            model="standard-model",
            tier="standard",
        )

    completion: asyncio.Task[LLMResponse] | None = None
    try:
        with patch.object(client, "_call_api", side_effect=blocked_completion):
            completion = asyncio.create_task(
                client.complete(
                    LLMRequest(prompt="completion-probe", tier="standard"),
                    priority=Priority.NORMAL,
                )
            )
            await asyncio.wait_for(completion_entered.wait(), timeout=2.0)
            await client.start_health_probe(interval_seconds=0.01)
            for _ in range(100):
                if client.check_connectivity.await_count:
                    break
                await asyncio.sleep(0.005)
            assert client.check_connectivity.await_count >= 1
            shared_post.assert_not_awaited()
            assert state.recovery_probe_inflight is True

            await client.stop_health_probe()
            completion_release.set()
            result = await asyncio.wait_for(completion, timeout=2.0)

        assert result.content == "completion-ok"
        assert state.cooldown_until == 0.0
        assert state.recovery_probe_inflight is False
    finally:
        completion_release.set()
        await client.stop_health_probe()
        if completion is not None and not completion.done():
            completion.cancel()
            await asyncio.gather(completion, return_exceptions=True)
        await client.close()


@pytest.mark.asyncio
async def test_closed_success_advances_epoch_and_invalidates_older_admission() -> None:
    client = _make_client()
    state = client._endpoint_failure_states[client._client_key("standard")]
    stale = await client._claim_endpoint_admission("standard")
    current = await client._claim_endpoint_admission("standard")
    state.failures = 2

    try:
        await client._record_endpoint_success("standard", current)
        assert state.epoch == 1
        assert state.failures == 0

        assert await client._record_endpoint_failure(
            "standard",
            stale,
            count_when_closed=True,
        ) is False
        assert state.epoch == 1
        assert state.failures == 0
    finally:
        await client.close()
