"""BF-246: LLM health probe recovery tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

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
