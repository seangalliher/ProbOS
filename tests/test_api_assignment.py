"""Tests for Assignment API endpoints (AD-408a)."""

import pytest
import pytest_asyncio

from probos.assignment import AssignmentService
from probos.runtime import ProbOSRuntime


@pytest_asyncio.fixture
async def assignment_svc(tmp_path):
    """Create an AssignmentService with temp SQLite DB."""
    svc = AssignmentService(db_path=str(tmp_path / "assignments.db"))
    await svc.start()
    yield svc
    await svc.stop()


@pytest.fixture
def mock_runtime(assignment_svc):
    """Create a mock runtime with assignment_service."""
    from unittest.mock import MagicMock
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.assignment_service = assignment_svc
    runtime.ward_room = None
    runtime.add_event_listener = MagicMock()
    return runtime


@pytest.fixture
def client(mock_runtime):
    """Create a test client for the API."""
    from probos.api import create_app
    from fastapi.testclient import TestClient
    app = create_app(mock_runtime)
    return TestClient(app)


def test_list_assignments_empty(client):
    """GET returns empty list when none exist."""
    resp = client.get("/api/assignments")
    assert resp.status_code == 200
    data = resp.json()
    assert data["assignments"] == []


def test_create_assignment(client):
    """POST creates assignment, GET retrieves it."""
    resp = client.post("/api/assignments", json={
        "name": "Alpha Team",
        "assignment_type": "away_team",
        "members": ["a1", "a2"],
        "created_by": "captain",
        "mission": "Investigate signal",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Alpha Team"
    assert data["assignment_type"] == "away_team"
    assert data["status"] == "active"
    aid = data["id"]

    # GET by ID
    resp2 = client.get(f"/api/assignments/{aid}")
    assert resp2.status_code == 200
    assert resp2.json()["name"] == "Alpha Team"


def test_add_remove_member(client):
    """POST members endpoint works for add and remove."""
    a = client.post("/api/assignments", json={
        "name": "Team", "assignment_type": "away_team",
        "members": ["a1"], "created_by": "captain",
    }).json()
    aid = a["id"]

    # Add member
    resp = client.post(f"/api/assignments/{aid}/members", json={
        "agent_id": "a2", "action": "add",
    })
    assert resp.status_code == 200
    assert "a2" in resp.json()["members"]

    # Remove member
    resp2 = client.post(f"/api/assignments/{aid}/members", json={
        "agent_id": "a2", "action": "remove",
    })
    assert resp2.status_code == 200
    assert "a2" not in resp2.json()["members"]


def test_complete_assignment(client):
    """POST complete endpoint works."""
    a = client.post("/api/assignments", json={
        "name": "Mission", "assignment_type": "away_team",
        "members": ["a1"], "created_by": "captain",
    }).json()
    aid = a["id"]

    resp = client.post(f"/api/assignments/{aid}/complete")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_dissolve_assignment(client):
    """DELETE dissolves assignment."""
    a = client.post("/api/assignments", json={
        "name": "Temp", "assignment_type": "working_group",
        "members": ["a1"], "created_by": "captain",
    }).json()
    aid = a["id"]

    resp = client.delete(f"/api/assignments/{aid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "dissolved"


def test_agent_assignments(client):
    """GET agent assignments returns correct list."""
    client.post("/api/assignments", json={
        "name": "Team1", "assignment_type": "away_team",
        "members": ["a1", "a2"], "created_by": "captain",
    })
    client.post("/api/assignments", json={
        "name": "Team2", "assignment_type": "bridge",
        "members": ["a1"], "created_by": "captain",
    })

    resp = client.get("/api/assignments/agent/a1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["assignments"]) == 2


def test_assignment_not_found(client):
    """GET nonexistent returns 404."""
    resp = client.get("/api/assignments/nonexistent-id")
    assert resp.status_code == 404
