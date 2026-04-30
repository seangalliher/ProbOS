from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.mesh.intent import IntentBus, IntentMetrics
from probos.mesh.signal import SignalManager
from probos.routers.deps import get_runtime
from probos.routers.system import router
from probos.types import IntentMessage, IntentResult


class _FakeRuntime:
    def __init__(self, intent_bus: IntentBus | None = None) -> None:
        if intent_bus is not None:
            self.intent_bus = intent_bus


def _client_for(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


async def _handler(intent: IntentMessage) -> IntentResult:
    return IntentResult(
        intent_id=intent.id,
        agent_id="agent-1",
        success=True,
        confidence=0.9,
    )


def test_intent_metrics_creation() -> None:
    metrics = IntentMetrics()

    assert metrics.broadcast_count == 0
    assert metrics.send_count == 0
    assert metrics.total_results == 0
    assert metrics.get_summary()["types"] == {}


def test_record_broadcast() -> None:
    metrics = IntentMetrics()

    metrics.record_broadcast("read_file", 1, 10.0)
    metrics.record_broadcast("read_file", 2, 20.0)
    metrics.record_broadcast("write_file", 1, 30.0)

    assert metrics.broadcast_count == 3
    assert metrics.total_results == 4


def test_record_send() -> None:
    metrics = IntentMetrics()

    metrics.record_send("read_file", 10.0)
    metrics.record_send("read_file", 20.0)

    assert metrics.send_count == 2


def test_type_counts() -> None:
    metrics = IntentMetrics()

    metrics.record_broadcast("read_file", 1, 10.0)
    metrics.record_broadcast("write_file", 1, 20.0)
    metrics.record_send("read_file", 30.0)

    assert metrics.type_counts["read_file"] == 2
    assert metrics.type_counts["write_file"] == 1


def test_type_durations_capped() -> None:
    metrics = IntentMetrics()

    for index in range(250):
        metrics.record_broadcast("read_file", 1, float(index))

    assert len(metrics.type_durations_ms["read_file"]) == 200
    assert metrics.type_durations_ms["read_file"][0] == 50.0


def test_metrics_summary() -> None:
    metrics = IntentMetrics()

    metrics.record_broadcast("read_file", 2, 10.0)
    metrics.record_send("read_file", 30.0)

    summary = metrics.get_summary()

    assert summary["broadcast_count"] == 1
    assert summary["send_count"] == 1
    assert summary["total_results"] == 2
    assert summary["types"]["read_file"]["count"] == 2
    assert summary["types"]["read_file"]["mean_ms"] == 20.0
    assert summary["types"]["read_file"]["max_ms"] == 30.0


def test_subscriber_map() -> None:
    bus = IntentBus(SignalManager())

    bus.subscribe("agent-1", _handler, intent_names=["read_file", "stat_file"])
    bus.subscribe("agent-2", _handler, intent_names=["read_file"])

    subscriber_map = bus.get_subscriber_map()

    assert subscriber_map["read_file"] == ["agent-1", "agent-2"]
    assert subscriber_map["stat_file"] == ["agent-1"]
    assert "__fallback__" not in subscriber_map


def test_subscriber_map_fallback() -> None:
    bus = IntentBus(SignalManager())

    bus.subscribe("agent-1", _handler, intent_names=["read_file"])
    bus.subscribe("agent-2", _handler)

    assert bus.get_subscriber_map()["__fallback__"] == ["agent-2"]


def test_get_metrics_on_bus() -> None:
    bus = IntentBus(SignalManager())

    metrics = bus.get_metrics()

    assert metrics["broadcast_count"] == 0
    assert metrics["send_count"] == 0
    assert metrics["total_results"] == 0
    assert metrics["types"] == {}


@pytest.mark.asyncio
async def test_broadcast_records_metrics() -> None:
    bus = IntentBus(SignalManager())
    bus.subscribe("agent-1", _handler, intent_names=["read_file"])
    intent = IntentMessage(intent="read_file")

    results = await bus.broadcast(intent, federated=False)
    metrics = bus.get_metrics()

    assert len(results) == 1
    assert metrics["broadcast_count"] == 1
    assert metrics["total_results"] == 1
    assert metrics["types"]["read_file"]["count"] == 1


@pytest.mark.asyncio
async def test_send_records_metrics() -> None:
    bus = IntentBus(SignalManager())
    bus.subscribe("agent-1", _handler, intent_names=["read_file"])
    intent = IntentMessage(intent="read_file", target_agent_id="agent-1")

    result = await bus.send(intent)
    metrics = bus.get_metrics()

    assert result is not None
    assert metrics["send_count"] == 1
    assert metrics["types"]["read_file"]["count"] == 1


def test_get_intent_metrics_endpoint_enabled_returns_metrics() -> None:
    bus = IntentBus(SignalManager())
    bus.subscribe("agent-1", _handler, intent_names=["read_file"])
    client = _client_for(_FakeRuntime(bus))

    response = client.get("/api/intent-metrics")
    payload: dict[str, Any] = response.json()

    assert response.status_code == 200
    assert payload["subscriber_count"] == 1
    assert payload["subscribers"]["read_file"] == ["agent-1"]
    assert payload["metrics"]["broadcast_count"] == 0


def test_get_intent_metrics_endpoint_disabled_returns_status() -> None:
    client = _client_for(_FakeRuntime())

    response = client.get("/api/intent-metrics")

    assert response.status_code == 200
    assert response.json() == {"status": "disabled"}
