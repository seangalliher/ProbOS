"""Tests for Bridge System API endpoints (AD-436)."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from unittest.mock import MagicMock

from probos.cognitive.codebase_index import CodebaseIndex
from probos.config import SystemConfig
from probos.routers.system import router
from probos.runtime import ProbOSRuntime


@pytest.fixture
def mock_runtime():
    """Minimal mock runtime for system endpoints."""
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime._started = True
    runtime.registry = MagicMock()
    runtime.registry.count = 0
    runtime.registry.all.return_value = []

    # Services that exist
    runtime.ward_room = MagicMock()
    runtime.episodic_memory = MagicMock()
    runtime.trust_network = MagicMock()
    runtime._knowledge_store = MagicMock()
    runtime.cognitive_journal = MagicMock()
    runtime.codebase_index = MagicMock(spec=CodebaseIndex)
    runtime.skill_registry = MagicMock()
    runtime.skill_service = MagicMock()
    runtime.acm = MagicMock()
    runtime.hebbian_router = MagicMock()
    runtime.intent_bus = MagicMock()

    # BF-069: LLM client with health status
    llm_client = MagicMock()
    llm_client.get_health_status.return_value = {
        "tiers": {"standard": {"status": "operational", "consecutive_failures": 0}},
        "overall": "operational",
    }
    runtime.llm_client = llm_client

    return runtime


@pytest.fixture
def client(mock_runtime):
    """FastAPI test client."""
    from probos.api import create_app
    from fastapi.testclient import TestClient
    app = create_app(mock_runtime)
    return TestClient(app)


class TestSystemServices:
    """GET /api/system/services"""

    def test_returns_all_services(self, client):
        """AD-436: Services endpoint lists all system services."""
        resp = client.get("/api/system/services")
        assert resp.status_code == 200
        data = resp.json()
        assert "services" in data
        names = [s["name"] for s in data["services"]]
        assert "Ward Room" in names
        assert "Episodic Memory" in names
        assert "Trust Network" in names
        assert "ACM" in names

    def test_all_online_when_initialized(self, client):
        """AD-436: All services report online when initialized."""
        resp = client.get("/api/system/services")
        data = resp.json()
        for svc in data["services"]:
            assert svc["status"] == "online", f"{svc['name']} should be online"

    def test_offline_when_none(self, client, mock_runtime):
        """AD-436: Services report offline when set to None."""
        mock_runtime.ward_room = None
        mock_runtime.acm = None
        resp = client.get("/api/system/services")
        data = resp.json()
        statuses = {s["name"]: s["status"] for s in data["services"]}
        assert statuses["Ward Room"] == "offline"
        assert statuses["ACM"] == "offline"
        # Others should still be online
        assert statuses["Trust Network"] == "online"


class TestSystemShutdown:
    """POST /api/system/shutdown"""

    def test_shutdown_returns_status(self, client):
        """AD-436: Shutdown endpoint returns shutting_down status."""
        resp = client.post(
            "/api/system/shutdown",
            json={"reason": "Testing AD-436"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "shutting_down"
        assert data["reason"] == "Testing AD-436"

    def test_shutdown_no_reason(self, client):
        """AD-436: Shutdown works without a reason."""
        resp = client.post("/api/system/shutdown", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "shutting_down"
        assert data["reason"] == ""


class _FakeRegistry:
    def __init__(self, confidences: list[float]) -> None:
        self.agents = [SimpleNamespace(confidence=value) for value in confidences]
        self.count = len(self.agents)

    def all(self) -> list[SimpleNamespace]:
        return list(self.agents)


class _FakeSystemRuntime:
    def __init__(self, config: object | None, confidences: list[float] | None = None) -> None:
        self.config = config
        self.registry = _FakeRegistry(confidences or [])
        self.ward_room = None
        self.episodic_memory = None
        self.trust_network = None
        self.records_store = None
        self.knowledge_browser = None
        self.skill_request_store = None
        self.ontology = None
        self.spatial_layout = None
        self.nats_bus = None
        self.startup_warnings = ["NATS unavailable during startup"]

    def status(self) -> dict[str, int]:
        return {"crew_agents": 2, "total_agents": 7}


class _FakeNatsBus:
    def __init__(self, value: object = True, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.observations = 0

    @property
    def connected(self) -> object:
        self.observations += 1
        if self.error is not None:
            raise self.error
        return self.value


def _system_client(runtime: _FakeSystemRuntime) -> TestClient:
    app = FastAPI()
    app.state.runtime = runtime
    app.include_router(router)
    return TestClient(app)


def _enabled_config(enabled: bool = True) -> SystemConfig:
    with pytest.MonkeyPatch.context() as environment:
        environment.delenv("PROBOS_NATS_ENABLED", raising=False)
        config = SystemConfig.model_validate({
            feature: {"enabled": enabled}
            for feature in ("records", "knowledge_browser", "skill_requests", "spatial_explorer", "nats")
        })
    assert config.nats.enabled is enabled
    return config


@pytest.mark.parametrize("confidences,expected", [([], 0.0), ([0.2, 0.8, 0.9], 0.63)])
def test_health_legacy_values_and_registered_population_scope(
    confidences: list[float], expected: float,
) -> None:
    runtime = _FakeSystemRuntime(_enabled_config(), confidences)
    with _system_client(runtime) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert {key: payload[key] for key in ("status", "agents", "crew_agents", "health")} == {
        "status": "ok", "agents": 7, "crew_agents": 2, "health": expected,
    }
    assert payload["liveness"] is True
    assert payload["liveness_scope"] == "http_handler_response"
    assert payload["health_scope"] == {
        "metric": "mean_confidence", "population": "registered_agents",
        "population_count": len(confidences), "empty_population": not confidences,
        "integrations_assessed": False,
    }


@pytest.mark.parametrize("enabled", [False, True, None])
def test_system_services_finite_missing_integrations_preserve_legacy(enabled: bool | None) -> None:
    runtime = _FakeSystemRuntime(None if enabled is None else _enabled_config(enabled))
    with _system_client(runtime) as client:
        response = client.get("/api/system/services")
    assert response.status_code == 200
    payload = response.json()
    assert payload["services"] == [
        {"name": name, "status": "offline"} for name in (
            "Ward Room", "Episodic Memory", "Trust Network", "Knowledge Store",
            "Cognitive Journal", "Codebase Index", "Skill Framework", "Skill Service",
            "ACM", "Hebbian Router", "Intent Bus", "LLM Proxy",
        )
    ]
    rows = payload["integrations"]
    assert [row["id"] for row in rows] == [
        "records", "knowledge_browser", "skill_requests", "ontology_graph", "spatial_layout", "nats",
    ]
    for row in rows:
        assert set(row) == {"id", "state", "scope", "code", "message", "retryable"}
        assert row["state"] == ("disabled" if enabled is False and row["id"] != "ontology_graph" else "unavailable")
        assert row["scope"] == ("connection" if row["id"] == "nats" else "initialization")


def test_system_services_presence_only_measures_initialization() -> None:
    runtime = _FakeSystemRuntime(_enabled_config())
    for attribute in ("records_store", "knowledge_browser", "skill_request_store", "ontology", "spatial_layout"):
        setattr(runtime, attribute, object())
    with _system_client(runtime) as client:
        response = client.get("/api/system/services")
    assert response.status_code == 200
    for row in response.json()["integrations"][:-1]:
        assert row["state"] == "initialized"
        assert row["scope"] == "initialization"
        assert row["message"] == "Initialized. Read operations have not been checked."


def test_system_nats_current_connection_recovers_despite_same_startup_warnings() -> None:
    runtime = _FakeSystemRuntime(_enabled_config())
    bus = _FakeNatsBus()
    runtime.nats_bus = bus
    warnings = list(runtime.startup_warnings)
    legacy = None
    with _system_client(runtime) as client:
        for connected, state, code in [(True, "ready", "nats.connected"), (False, "unavailable", "nats.disconnected"), (True, "ready", "nats.connected")]:
            bus.value = connected
            response = client.get("/api/system/services")
            assert response.status_code == 200
            payload = response.json()
            row = payload["integrations"][-1]
            assert row["id"] == "nats"
            assert row["state"] == state
            assert row["code"] == code
            assert row["scope"] == "connection"
            assert row["retryable"] is (not connected)
            if connected:
                assert row["message"] == "Connected. JetStream operations have not been checked."
            if legacy is not None:
                assert payload["services"] == legacy
            legacy = payload["services"]
            assert runtime.startup_warnings == warnings
    assert bus.observations == 3


@pytest.mark.parametrize("config", [None, {}, MagicMock(), _enabled_config(False)])
def test_system_nats_unknown_or_disabled_config_never_claims_ready(config: object | None) -> None:
    runtime = _FakeSystemRuntime(config)
    bus = _FakeNatsBus()
    runtime.nats_bus = bus
    with _system_client(runtime) as client:
        response = client.get("/api/system/services")
    assert response.status_code == 200
    assert response.json()["integrations"][-1]["state"] == ("disabled" if isinstance(config, SystemConfig) else "unavailable")
    assert bus.observations == 0


@pytest.mark.parametrize("observation", [None, "true", 1, MagicMock()])
def test_system_nats_non_boolean_connection_is_unknown(observation: object) -> None:
    runtime = _FakeSystemRuntime(_enabled_config())
    runtime.nats_bus = _FakeNatsBus(observation)
    with _system_client(runtime) as client:
        response = client.get("/api/system/services")
    assert response.status_code == 200
    assert response.json()["integrations"][-1]["code"] == "nats.connection_unknown"
    assert response.json()["integrations"][-1]["state"] == "unavailable"
    assert runtime.nats_bus.observations == 1


def test_system_nats_observation_failure_controlled(caplog: pytest.LogCaptureFixture) -> None:
    secret = "token=private nats://private-host"
    runtime = _FakeSystemRuntime(_enabled_config())
    runtime.nats_bus = _FakeNatsBus(error=RuntimeError(secret))
    with _system_client(runtime) as client:
        response = client.get("/api/system/services")
    assert response.status_code == 200
    assert response.json()["integrations"][-1]["state"] == "unavailable"
    assert "reporting unavailable" in caplog.text
    assert secret not in response.text + caplog.text
