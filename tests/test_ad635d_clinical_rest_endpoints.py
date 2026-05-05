"""AD-635d v1: REST endpoints for clinical telemetry."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.routers.clinical import router
from probos.routers.deps import get_runtime


# ---- Test harness (mirrors tests/test_ad561_intervention_classification.py) ----


class _FakeClinicalTelemetryService:
    """In-test stub for ClinicalTelemetryService — only the four surfaces
    the REST router consumes are stubbed out."""

    def __init__(
        self,
        *,
        dreams: list[dict[str, Any]] | None = None,
        traces: list[dict[str, Any]] | None = None,
        transitions: list[dict[str, Any]] | None = None,
        audit: list[dict[str, Any]] | None = None,
    ) -> None:
        self.query_dream_history = AsyncMock(return_value=list(dreams or []))
        self.query_agent_chain_traces = AsyncMock(return_value=list(traces or []))
        self.query_circuit_breaker_history = AsyncMock(
            return_value=list(transitions or [])
        )
        self._audit = list(audit or [])

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        return list(self._audit)


class _FakeRuntime:
    def __init__(self, service: _FakeClinicalTelemetryService | None) -> None:
        self.clinical_telemetry = service


def _client_for(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


# ---- Dreams ----


def test_dreams_happy_path_returns_envelope_with_rows() -> None:
    rows = [{"ts": 1.0, "summary": "dream-a"}]
    service = _FakeClinicalTelemetryService(dreams=rows)
    client = _client_for(_FakeRuntime(service))

    resp = client.get("/api/clinical/dreams", params={"requester_agent_id": "med-1"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload == {"requester_agent_id": "med-1", "dreams": rows}
    service.query_dream_history.assert_awaited_once_with(
        requester_agent_id="med-1", limit=20
    )


def test_dreams_missing_requester_agent_id_returns_422() -> None:
    service = _FakeClinicalTelemetryService(dreams=[])
    client = _client_for(_FakeRuntime(service))

    resp = client.get("/api/clinical/dreams")

    assert resp.status_code == 422
    service.query_dream_history.assert_not_awaited()


def test_dreams_service_unavailable_returns_503() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.get("/api/clinical/dreams", params={"requester_agent_id": "med-1"})

    assert resp.status_code == 503
    assert resp.json() == {"error": "Clinical telemetry not available"}


def test_dreams_clearance_denied_returns_200_with_empty_list() -> None:
    # Service-side denial → query_dream_history returns []. REST passes through.
    service = _FakeClinicalTelemetryService(dreams=[])
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/dreams",
        params={"requester_agent_id": "no-clearance-agent"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "requester_agent_id": "no-clearance-agent",
        "dreams": [],
    }


def test_dreams_limit_query_param_is_clamped_to_cap() -> None:
    service = _FakeClinicalTelemetryService(dreams=[])
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/dreams",
        params={"requester_agent_id": "med-1", "limit": 9999},
    )

    assert resp.status_code == 200
    service.query_dream_history.assert_awaited_once_with(
        requester_agent_id="med-1", limit=100
    )


# ---- Chain traces ----


def test_chain_traces_happy_path_returns_envelope_with_rows() -> None:
    rows = [{"chain_id": "c1", "agent_id": "khan-1"}]
    service = _FakeClinicalTelemetryService(traces=rows)
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/chain-traces/khan-1",
        params={"requester_agent_id": "med-1"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "requester_agent_id": "med-1",
        "target_agent_id": "khan-1",
        "traces": rows,
    }
    service.query_agent_chain_traces.assert_awaited_once_with(
        requester_agent_id="med-1", target_agent_id="khan-1", limit=20
    )


def test_chain_traces_missing_requester_agent_id_returns_422() -> None:
    service = _FakeClinicalTelemetryService()
    client = _client_for(_FakeRuntime(service))

    resp = client.get("/api/clinical/chain-traces/khan-1")

    assert resp.status_code == 422
    service.query_agent_chain_traces.assert_not_awaited()


def test_chain_traces_service_unavailable_returns_503() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.get(
        "/api/clinical/chain-traces/khan-1",
        params={"requester_agent_id": "med-1"},
    )

    assert resp.status_code == 503


def test_chain_traces_clearance_denied_returns_200_with_empty_list() -> None:
    service = _FakeClinicalTelemetryService(traces=[])
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/chain-traces/khan-1",
        params={"requester_agent_id": "no-clearance-agent"},
    )

    assert resp.status_code == 200
    assert resp.json()["traces"] == []


# ---- Circuit-breaker history ----


def test_circuit_breakers_happy_path_returns_envelope_with_transitions() -> None:
    rows = [
        {"ts": 100.0, "agent_id": "khan-1", "transition_kind": "state",
         "old_value": "closed", "new_value": "open", "trip_count": 1},
    ]
    service = _FakeClinicalTelemetryService(transitions=rows)
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/circuit-breakers/khan-1",
        params={"requester_agent_id": "med-1"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "requester_agent_id": "med-1",
        "target_agent_id": "khan-1",
        "transitions": rows,
    }
    service.query_circuit_breaker_history.assert_awaited_once_with(
        requester_agent_id="med-1", target_agent_id="khan-1", limit=50
    )


def test_circuit_breakers_missing_requester_agent_id_returns_422() -> None:
    service = _FakeClinicalTelemetryService()
    client = _client_for(_FakeRuntime(service))

    resp = client.get("/api/clinical/circuit-breakers/khan-1")

    assert resp.status_code == 422


def test_circuit_breakers_service_unavailable_returns_503() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.get(
        "/api/clinical/circuit-breakers/khan-1",
        params={"requester_agent_id": "med-1"},
    )

    assert resp.status_code == 503


def test_circuit_breakers_clearance_denied_returns_200_with_empty_list() -> None:
    service = _FakeClinicalTelemetryService(transitions=[])
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/circuit-breakers/khan-1",
        params={"requester_agent_id": "no-clearance-agent"},
    )

    assert resp.status_code == 200
    assert resp.json()["transitions"] == []


def test_circuit_breakers_limit_query_param_is_clamped_to_cap() -> None:
    service = _FakeClinicalTelemetryService(transitions=[])
    client = _client_for(_FakeRuntime(service))

    resp = client.get(
        "/api/clinical/circuit-breakers/khan-1",
        params={"requester_agent_id": "med-1", "limit": 9999},
    )

    assert resp.status_code == 200
    service.query_circuit_breaker_history.assert_awaited_once_with(
        requester_agent_id="med-1", target_agent_id="khan-1", limit=500
    )


# ---- Audit ----


def test_audit_returns_audit_log_snapshot_envelope() -> None:
    audit = [
        {"ts": 1.0, "requester_agent_id": "a", "query_type": "dream_history",
         "granted": True, "result_count": 0},
        {"ts": 2.0, "requester_agent_id": "b", "query_type": "chain_traces",
         "granted": False, "result_count": 0},
    ]
    service = _FakeClinicalTelemetryService(audit=audit)
    client = _client_for(_FakeRuntime(service))

    resp = client.get("/api/clinical/audit")

    assert resp.status_code == 200
    assert resp.json() == {"audit": audit}


def test_audit_service_unavailable_returns_503() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.get("/api/clinical/audit")

    assert resp.status_code == 503


def test_audit_limit_returns_most_recent_slice() -> None:
    audit = [
        {"ts": float(i), "requester_agent_id": f"a{i}",
         "query_type": "dream_history", "granted": True, "result_count": 0}
        for i in range(10)
    ]
    service = _FakeClinicalTelemetryService(audit=audit)
    client = _client_for(_FakeRuntime(service))

    resp = client.get("/api/clinical/audit", params={"limit": 3})

    assert resp.status_code == 200
    payload = resp.json()
    # Most-recent slice = audit[-3:] — entries ts=7,8,9.
    assert [row["ts"] for row in payload["audit"]] == [7.0, 8.0, 9.0]
