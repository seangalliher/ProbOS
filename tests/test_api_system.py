"""Tests for Bridge System API endpoints (AD-436)."""

import pytest
from unittest.mock import MagicMock

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
    runtime.codebase_index = MagicMock()
    runtime.skill_registry = MagicMock()
    runtime.skill_service = MagicMock()
    runtime.acm = MagicMock()
    runtime.hebbian_router = MagicMock()
    runtime.intent_bus = MagicMock()

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
