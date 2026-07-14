from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.mesh.intent import (
    IntentBus,
    IntentMetrics,
    _COGNITIVE_HANDLER_LATENCY_MS,
    _DETERMINISTIC_HANDLER_LATENCY_MS,
    _NETWORK_HANDLER_LATENCY_MS,
)
from probos.mesh.signal import SignalManager
from probos.routers.deps import get_runtime
from probos.routers.system import router
from probos.types import HandlerLatencyClass, IntentMessage, IntentResult


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
    assert metrics.get_summary()["handlers"] == []


def test_intent_bus_default_thresholds_match_mesh_config() -> None:
    from probos.config import MeshConfig

    bus = IntentBus(SignalManager())
    config = MeshConfig()

    assert bus._handler_latency_thresholds_ms == {
        HandlerLatencyClass.DETERMINISTIC: _DETERMINISTIC_HANDLER_LATENCY_MS,
        HandlerLatencyClass.NETWORK: _NETWORK_HANDLER_LATENCY_MS,
        HandlerLatencyClass.COGNITIVE: _COGNITIVE_HANDLER_LATENCY_MS,
    }
    assert bus._handler_latency_thresholds_ms == {
        HandlerLatencyClass.DETERMINISTIC: config.handler_latency_deterministic_ms,
        HandlerLatencyClass.NETWORK: config.handler_latency_network_ms,
        HandlerLatencyClass.COGNITIVE: config.handler_latency_cognitive_ms,
    }


@pytest.mark.parametrize(
    "thresholds",
    [
        {
            HandlerLatencyClass.DETERMINISTIC: 100.0,
            HandlerLatencyClass.NETWORK: 10_000.0,
        },
        {
            HandlerLatencyClass.DETERMINISTIC: 0.0,
            HandlerLatencyClass.NETWORK: 10_000.0,
            HandlerLatencyClass.COGNITIVE: 30_000.0,
        },
        {
            HandlerLatencyClass.DETERMINISTIC: 100.0,
            HandlerLatencyClass.NETWORK: float("inf"),
            HandlerLatencyClass.COGNITIVE: 30_000.0,
        },
    ],
)
def test_intent_bus_rejects_invalid_threshold_mapping(thresholds) -> None:
    with pytest.raises(ValueError, match="handler latency threshold"):
        IntentBus(SignalManager(), handler_latency_thresholds_ms=thresholds)


def test_record_handler_creates_outcome_row() -> None:
    metrics = IntentMetrics()

    metrics.record_handler(
        "agent-full-id",
        "reason",
        HandlerLatencyClass.COGNITIVE,
        8000.0,
        "responded",
    )

    assert metrics.get_summary()["handlers"] == [
        {
            "agent_id": "agent-full-id",
            "intent": "reason",
            "latency_class": "cognitive",
            "count": 1,
            "mean_ms": 8000.0,
            "p95_ms": 8000.0,
            "max_ms": 8000.0,
            "responded_count": 1,
            "declined_count": 0,
            "error_count": 0,
        }
    ]


@pytest.mark.parametrize(
    ("samples", "expected_p95"),
    [([1.0], 1.0), ([1.0, 2.0], 2.0), ([float(i) for i in range(1, 21)], 19.0)],
)
def test_record_handler_uses_nearest_rank_p95(
    samples: list[float],
    expected_p95: float,
) -> None:
    metrics = IntentMetrics()

    for sample in samples:
        metrics.record_handler(
            "agent",
            "intent",
            HandlerLatencyClass.DETERMINISTIC,
            sample,
            "responded",
        )

    assert metrics.get_summary()["handlers"][0]["p95_ms"] == expected_p95


def test_record_handler_caps_samples_but_preserves_lifetime_counts() -> None:
    metrics = IntentMetrics()

    for index in range(250):
        outcome = ("responded", "declined", "error")[index % 3]
        metrics.record_handler(
            "agent",
            "intent",
            HandlerLatencyClass.DETERMINISTIC,
            float(index),
            outcome,  # type: ignore[arg-type]
        )

    key = ("agent", "intent", HandlerLatencyClass.DETERMINISTIC)
    assert metrics._handler_stats[key].durations_ms == [float(i) for i in range(50, 250)]
    row = metrics.get_summary()["handlers"][0]
    assert row["count"] == 250
    assert row["responded_count"] == 84
    assert row["declined_count"] == 83
    assert row["error_count"] == 83
    assert row["mean_ms"] == 149.5
    assert row["p95_ms"] == 239.0
    assert row["max_ms"] == 249.0


def test_record_handler_lru_refresh_and_eviction() -> None:
    metrics = IntentMetrics()
    latency_class = HandlerLatencyClass.DETERMINISTIC

    for index in range(1_000):
        metrics.record_handler(
            f"agent-{index:04d}", "intent", latency_class, 1.0, "responded"
        )
    metrics.record_handler("agent-0000", "intent", latency_class, 2.0, "error")
    metrics.record_handler("agent-1000", "intent", latency_class, 3.0, "declined")

    keys = set(metrics._handler_stats)
    assert len(keys) == 1_000
    assert ("agent-0000", "intent", latency_class) in keys
    assert ("agent-0001", "intent", latency_class) not in keys
    assert ("agent-1000", "intent", latency_class) in keys
    refreshed = next(
        row for row in metrics.get_summary()["handlers"]
        if row["agent_id"] == "agent-0000"
    )
    assert refreshed["count"] == 2
    assert refreshed["responded_count"] == 1
    assert refreshed["error_count"] == 1


def test_handler_rows_are_sorted_by_full_typed_key() -> None:
    metrics = IntentMetrics()
    entries = [
        ("z-agent", "b-intent", HandlerLatencyClass.NETWORK),
        ("a-agent", "z-intent", HandlerLatencyClass.COGNITIVE),
        ("a-agent", "a-intent", HandlerLatencyClass.DETERMINISTIC),
    ]

    for agent_id, intent_type, latency_class in entries:
        metrics.record_handler(agent_id, intent_type, latency_class, 1.0, "responded")

    assert [
        (row["agent_id"], row["intent"], row["latency_class"])
        for row in metrics.get_summary()["handlers"]
    ] == [
        ("a-agent", "a-intent", "deterministic"),
        ("a-agent", "z-intent", "cognitive"),
        ("z-agent", "b-intent", "network"),
    ]


@pytest.mark.parametrize(
    ("duration_ms", "outcome", "exception"),
    [
        (-1.0, "responded", ValueError),
        (float("nan"), "responded", ValueError),
        (float("inf"), "responded", ValueError),
        (float("-inf"), "responded", ValueError),
        (1.0, "unknown", ValueError),
    ],
)
def test_record_handler_invalid_input_does_not_mutate(
    duration_ms: float,
    outcome: str,
    exception: type[Exception],
) -> None:
    metrics = IntentMetrics()

    with pytest.raises(exception):
        metrics.record_handler(
            "agent",
            "intent",
            HandlerLatencyClass.DETERMINISTIC,
            duration_ms,
            outcome,  # type: ignore[arg-type]
        )

    assert metrics._handler_stats == {}
    assert metrics.get_summary()["handlers"] == []


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
    assert summary["handlers"] == []


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
    assert metrics["handlers"] == []


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
    assert payload["metrics"]["handlers"] == []


def test_get_intent_metrics_endpoint_disabled_returns_status() -> None:
    client = _client_for(_FakeRuntime())

    response = client.get("/api/intent-metrics")

    assert response.status_code == 200
    assert response.json() == {"status": "disabled"}
