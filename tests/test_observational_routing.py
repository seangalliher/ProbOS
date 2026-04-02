"""AD-537: Tests for observational learning API endpoints (teach + observed)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.api import create_app


def _make_procedure(
    proc_id: str = "proc-001",
    name: str = "test-procedure",
    compilation_level: int = 5,
) -> MagicMock:
    """Create a mock procedure with required attributes."""
    proc = MagicMock()
    proc.id = proc_id
    proc.name = name
    proc.description = "A test procedure"
    proc.compilation_level = compilation_level
    proc.origin_agent_ids = ["science_agent"]
    proc.intent_types = ["analysis"]
    proc.preconditions = []
    proc.postconditions = []
    step = MagicMock()
    step.step_number = 1
    step.action = "do the thing"
    proc.steps = [step]
    return proc


@pytest.fixture
def mock_runtime():
    """Minimal mock runtime for procedure endpoints."""
    runtime = MagicMock()
    runtime._started = True
    runtime.procedure_store = MagicMock()
    runtime.ward_room = MagicMock()
    runtime.ontology = MagicMock()
    runtime.registry = MagicMock()
    runtime.registry.count = 0
    runtime.registry.all.return_value = []
    runtime.episodic_memory = None
    runtime.trust_network = None
    runtime._knowledge_store = None
    runtime.cognitive_journal = None
    runtime.codebase_index = None
    runtime.skill_registry = None
    runtime.skill_service = None
    runtime.acm = None
    runtime.hebbian_router = None
    runtime.intent_bus = None
    return runtime


@pytest.fixture
def client(mock_runtime):
    """FastAPI test client wired to mock runtime."""
    app = create_app(mock_runtime)
    return TestClient(app)


class TestTeachEndpoint:
    """POST /api/procedures/teach"""

    def test_api_teach_endpoint(self, client, mock_runtime):
        """POST /procedures/teach with valid Level 5 procedure returns success."""
        proc = _make_procedure(compilation_level=5)
        store = mock_runtime.procedure_store
        store.get = AsyncMock(return_value=proc)
        store.get_promotion_status = AsyncMock(return_value="approved")
        store.get_quality_metrics = AsyncMock(
            return_value={"total_completions": 10, "effective_rate": 0.95}
        )

        dm_channel = MagicMock()
        dm_channel.id = "dm-123"
        mock_runtime.ward_room.get_or_create_dm_channel = AsyncMock(
            return_value=dm_channel
        )
        mock_runtime.ward_room.create_thread = AsyncMock()

        resp = client.post(
            "/api/procedures/teach",
            json={"procedure_id": "proc-001", "target_callsign": "data"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["procedure_id"] == "proc-001"
        assert data["target"] == "data"
        assert data["procedure_name"] == "test-procedure"

    def test_api_teach_precondition_error(self, client, mock_runtime):
        """POST /procedures/teach with sub-Level-5 procedure returns error."""
        proc = _make_procedure(compilation_level=3)
        store = mock_runtime.procedure_store
        store.get = AsyncMock(return_value=proc)

        resp = client.post(
            "/api/procedures/teach",
            json={"procedure_id": "proc-001", "target_callsign": "data"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "Level 5" in data["error"]
        assert "Level 3" in data["error"]


class TestObservedEndpoint:
    """GET /api/procedures/observed"""

    def test_api_observed_endpoint(self, client, mock_runtime):
        """GET /procedures/observed returns observed procedures list."""
        store = mock_runtime.procedure_store
        store.get_observed_procedures = AsyncMock(
            return_value=[
                {"id": "proc-001", "name": "p1"},
                {"id": "proc-002", "name": "p2"},
            ]
        )

        resp = client.get("/api/procedures/observed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["observed"]) == 2
        assert data["observed"][0]["id"] == "proc-001"

    def test_api_observed_filter(self, client, mock_runtime):
        """GET /procedures/observed?agent=xxx passes filter to store."""
        store = mock_runtime.procedure_store
        store.get_observed_procedures = AsyncMock(
            return_value=[{"id": "proc-003", "name": "p3"}]
        )

        resp = client.get("/api/procedures/observed?agent=science_agent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        store.get_observed_procedures.assert_called_once_with(agent="science_agent")

    def test_api_observed_empty(self, client, mock_runtime):
        """GET /procedures/observed returns empty list when none exist."""
        store = mock_runtime.procedure_store
        store.get_observed_procedures = AsyncMock(return_value=[])

        resp = client.get("/api/procedures/observed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["observed"] == []
        assert data["count"] == 0
