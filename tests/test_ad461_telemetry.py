import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from probos.config import TelemetryConfig
from probos.events import EventType
from probos.routers.deps import get_runtime
from probos.substrate.telemetry import TelemetryService


def test_telemetry_record() -> None:
    telemetry = TelemetryService()

    telemetry.record("cognitive_chain", duration_ms=10.0)
    telemetry.record("cognitive_chain", duration_ms=20.0)
    telemetry.record("cognitive_chain", duration_ms=30.0)

    report = telemetry.get_report()
    assert report["operations"]["cognitive_chain"]["count"] == 3


def test_telemetry_bucket_stats() -> None:
    telemetry = TelemetryService()

    for duration in [10.0, 20.0, 30.0]:
        telemetry.record("llm_call", duration_ms=duration)

    stats = telemetry.get_report()["operations"]["llm_call"]
    assert stats["mean_ms"] == 20.0
    assert stats["min_ms"] == 10.0
    assert stats["max_ms"] == 30.0


def test_telemetry_p95() -> None:
    telemetry = TelemetryService()

    for duration in range(1, 101):
        telemetry.record("trust_update", duration_ms=float(duration))

    stats = telemetry.get_report()["operations"]["trust_update"]
    assert stats["p95_ms"] == 96.0


@pytest.mark.asyncio
async def test_telemetry_measure_context_manager() -> None:
    telemetry = TelemetryService()

    async with telemetry.measure("op"):
        await asyncio.sleep(0)

    stats = telemetry.get_report()["operations"]["op"]
    assert stats["count"] == 1
    assert stats["max_ms"] > 0.0


def test_telemetry_flush_clears_buckets() -> None:
    telemetry = TelemetryService()
    telemetry.record("op", duration_ms=5.0)

    report = telemetry.flush()

    assert report["operations"]["op"]["count"] == 1
    assert telemetry.get_report()["operations"] == {}


def test_telemetry_max_samples_eviction() -> None:
    telemetry = TelemetryService(max_samples_per_bucket=5)

    for duration in range(10):
        telemetry.record("op", duration_ms=float(duration))

    stats = telemetry.get_report()["operations"]["op"]
    assert stats["count"] == 5
    assert stats["min_ms"] == 5.0
    assert stats["max_ms"] == 9.0


@pytest.mark.asyncio
async def test_telemetry_maybe_emit_report() -> None:
    emitted: list[tuple[Any, dict[str, Any]]] = []
    telemetry = TelemetryService(
        emit_fn=lambda event_type, report: emitted.append((event_type, report)),
        report_interval_seconds=0,
    )
    telemetry.record("op", duration_ms=5.0)

    await telemetry.maybe_emit_report()

    assert emitted[0][0] == EventType.TELEMETRY_REPORT
    assert emitted[0][1]["operations"]["op"]["count"] == 1


def test_telemetry_event_type_exists() -> None:
    assert EventType.TELEMETRY_REPORT.value == "telemetry_report"


def test_telemetry_config_defaults() -> None:
    config = TelemetryConfig()

    assert config.enabled is True
    assert config.report_interval_seconds == 60.0
    assert config.max_samples_per_bucket == 1000


class _FakeRuntime:
    def __init__(self, telemetry_service: TelemetryService | None = None) -> None:
        if telemetry_service is not None:
            self._telemetry_service = telemetry_service


def _client_for(runtime: _FakeRuntime) -> TestClient:
    from fastapi import FastAPI

    from probos.routers.system import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def test_get_telemetry_enabled_returns_report() -> None:
    telemetry = TelemetryService()
    telemetry.record("op", duration_ms=12.5)
    client = _client_for(_FakeRuntime(telemetry))

    response = client.get("/api/telemetry")

    assert response.status_code == 200
    assert response.json()["operations"]["op"]["count"] == 1


def test_get_telemetry_disabled_returns_empty_operations() -> None:
    client = _client_for(_FakeRuntime())

    response = client.get("/api/telemetry")

    assert response.status_code == 200
    assert response.json() == {"status": "disabled", "operations": {}}


def test_get_telemetry_empty_service_returns_empty_report() -> None:
    client = _client_for(_FakeRuntime(TelemetryService()))

    response = client.get("/api/telemetry")

    assert response.status_code == 200
    assert response.json()["operations"] == {}
