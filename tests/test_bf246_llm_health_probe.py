"""BF-246: LLM health probe recovery tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import CognitiveConfig, SystemConfig


def _make_client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(config=CognitiveConfig())


def _unhealthy_health(overall: str = "offline") -> dict:
    return {
        "overall": overall,
        "tiers": {
            "fast": {"status": "unreachable"},
            "standard": {"status": "operational"},
            "deep": {"status": "operational"},
        },
    }


def _healthy_health() -> dict:
    return {
        "overall": "operational",
        "tiers": {
            "fast": {"status": "operational"},
            "standard": {"status": "operational"},
            "deep": {"status": "operational"},
        },
    }


def _httpx_response(status_code: int, *, json: dict) -> httpx.Response:
    response = httpx.Response(status_code, json=json)
    response._request = httpx.Request("POST", "http://test")
    return response


@pytest.mark.asyncio
async def test_health_probe_starts() -> None:
    client = _make_client()
    try:
        await client.start_health_probe(interval_seconds=5.0)
        assert client._health_probe_task is not None
        assert client._health_probe_task.done() is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_health_probe_stops() -> None:
    client = _make_client()
    try:
        await client.start_health_probe(interval_seconds=5.0)
        task = client._health_probe_task
        await client.stop_health_probe()
        assert task is not None
        assert task.done() is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_health_probe_calls_connectivity() -> None:
    client = _make_client()
    client._consecutive_failures["fast"] = 3
    client.check_connectivity = AsyncMock()
    try:
        await client.start_health_probe(interval_seconds=0.05)
        await asyncio.sleep(0.15)
        assert client.check_connectivity.await_count >= 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_health_probe_skips_when_healthy() -> None:
    client = _make_client()
    client.check_connectivity = AsyncMock()
    try:
        await client.start_health_probe(interval_seconds=0.05)
        await asyncio.sleep(0.08)
        client.check_connectivity.assert_not_awaited()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_health_probe_probes_when_unhealthy() -> None:
    client = _make_client()
    client._consecutive_failures["fast"] = 3
    client.check_connectivity = AsyncMock()
    try:
        await client.start_health_probe(interval_seconds=0.05)
        await asyncio.sleep(0.08)
        client.check_connectivity.assert_awaited()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_health_probe_logs_transition(caplog: pytest.LogCaptureFixture) -> None:
    client = _make_client()
    emitted: list[tuple[str, dict]] = []
    client.get_health_status = Mock(side_effect=[_unhealthy_health(), _healthy_health()])
    client.check_connectivity = AsyncMock()
    try:
        with caplog.at_level("INFO"):
            await client.start_health_probe(
                interval_seconds=0.05,
                emit_fn=lambda event_type, data: emitted.append((event_type, data)),
            )
            await asyncio.sleep(0.08)
        assert "BF-246: LLM health probe detected transition" in caplog.text
        assert emitted == [
            (
                "llm_health_changed",
                {
                    "old_status": "offline",
                    "new_status": "operational",
                    "source": "bf246_probe",
                },
            )
        ]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_close_cancels_probe() -> None:
    client = _make_client()
    await client.start_health_probe(interval_seconds=5.0)
    task = client._health_probe_task
    await client.close()
    assert task is not None
    assert task.done() is True


@pytest.mark.asyncio
async def test_first_probe_is_delayed() -> None:
    client = _make_client()
    client._consecutive_failures["fast"] = 3
    client.check_connectivity = AsyncMock()
    try:
        await client.start_health_probe(interval_seconds=0.1)
        await asyncio.sleep(0.05)
        client.check_connectivity.assert_not_awaited()
    finally:
        await client.close()


def test_config_validator_rejects_low_interval() -> None:
    with pytest.raises(ValidationError):
        SystemConfig(health_probe_interval_seconds=0)

    config = SystemConfig(health_probe_interval_seconds=5.0)
    assert config.health_probe_interval_seconds == 5.0


@pytest.mark.asyncio
async def test_empty_http_200_probe_does_not_advance_recovery() -> None:
    client = _make_client()
    client._consecutive_failures["fast"] = 3
    client._consecutive_successes["fast"] = 2
    previous_success = 77.0
    client._last_success["fast"] = previous_success
    for tier in ("standard", "deep", "vision", "vision_fast", "compute_use", "image_gen"):
        client._tier_status[tier] = False
    pooled = client._clients[client._client_key("fast")]
    response = _httpx_response(
        200, json={"choices": [{"message": {"content": ""}}]}
    )
    try:
        with patch.object(
            pooled, "post", new_callable=AsyncMock, return_value=response
        ):
            results = await client.check_connectivity()

        assert results["fast"] is False
        assert client._consecutive_failures["fast"] == 3
        assert client._consecutive_successes["fast"] == 0
        assert client._last_success["fast"] == previous_success
        assert client.get_health_status()["tiers"]["fast"]["status"] == "unreachable"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_health_probe_holds_endpoint_permit_and_client_lease() -> None:
    client = _make_client()
    key = client._client_key("fast")
    endpoint = client._endpoint_semaphores[key]
    state = client._client_pool_states[key]
    pooled = client._clients[key]
    observed: list[tuple[int, dict[int, int]]] = []

    async def inspect_post(*args, **kwargs):  # noqa: ANN002, ANN003
        observed.append((endpoint._value, dict(state.borrowers)))
        return _httpx_response(
            200, json={"choices": [{"message": {"content": "pong"}}]}
        )

    try:
        with patch.object(pooled, "post", side_effect=inspect_post):
            assert await client._check_endpoint("fast") is True

        assert observed == [(7, {0: 1})]
        assert endpoint._value == 8
        assert state.borrowers == {}
        assert state.borrowers_zero.is_set()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_health_probe_forces_governance_even_in_inherited_critical_context() -> None:
    client = _make_client()
    key = client._client_key("fast")
    endpoint = client._endpoint_semaphores[key]
    pooled = client._clients[key]
    entered = asyncio.Event()

    async def post(*args, **kwargs):  # noqa: ANN002, ANN003
        entered.set()
        return _httpx_response(
            200, json={"choices": [{"message": {"content": "pong"}}]}
        )

    for _ in range(8):
        await endpoint.acquire()
    task: asyncio.Task[bool] | None = None
    try:
        from probos.cognitive.llm_client import _ENDPOINT_GOVERNED

        token = _ENDPOINT_GOVERNED.set(False)
        try:
            with patch.object(pooled, "post", side_effect=post):
                task = asyncio.create_task(client._check_endpoint("fast"))
                await asyncio.sleep(0)
                assert entered.is_set() is False
                endpoint.release()
                result = await asyncio.wait_for(task, timeout=2.0)
            assert result is True
            assert _ENDPOINT_GOVERNED.get() is False
        finally:
            _ENDPOINT_GOVERNED.reset(token)
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        while endpoint._value < 8:
            endpoint.release()
        await client.close()


@pytest.mark.asyncio
async def test_cancel_health_probe_transport_releases_endpoint_and_lease() -> None:
    client = _make_client()
    key = client._client_key("fast")
    endpoint = client._endpoint_semaphores[key]
    state = client._client_pool_states[key]
    pooled = client._clients[key]
    entered = asyncio.Event()
    release = asyncio.Event()

    async def post(*args, **kwargs):  # noqa: ANN002, ANN003
        entered.set()
        await release.wait()
        return _httpx_response(
            200, json={"choices": [{"message": {"content": "pong"}}]}
        )

    task: asyncio.Task[bool] | None = None
    try:
        with patch.object(pooled, "post", side_effect=post):
            task = asyncio.create_task(client._check_endpoint("fast"))
            await asyncio.wait_for(entered.wait(), timeout=2.0)
            assert endpoint._value == 7
            assert state.borrowers == {0: 1}

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert endpoint._value == 8
        assert state.borrowers == {}
        assert state.retired == {}
        assert state.borrowers_zero.is_set()
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await client.close()
