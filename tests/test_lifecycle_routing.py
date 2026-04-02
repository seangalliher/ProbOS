"""AD-538: Tests for lifecycle API endpoints."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.routers.procedures import router


def _make_app(store=None):
    """Create a FastAPI app with the procedures router and a mock runtime."""
    app = FastAPI()
    app.include_router(router)

    runtime = MagicMock()
    if store is None:
        store = AsyncMock()
        store.get_stale_procedures = AsyncMock(return_value=[])
        store.get_archived_procedures = AsyncMock(return_value=[])
        store.restore_procedure = AsyncMock(return_value=True)
        store.find_duplicate_candidates = AsyncMock(return_value=[])
        store.merge_procedures = AsyncMock(return_value=True)
        store.get = AsyncMock(return_value=None)
        store.get_quality_metrics = AsyncMock(return_value={"total_completions": 0})
        store.get_pending_promotions = AsyncMock(return_value=[])
        store.get_promoted_procedures = AsyncMock(return_value=[])
        store.get_observed_procedures = AsyncMock(return_value=[])
    runtime.procedure_store = store

    from probos.routers.deps import get_runtime
    app.dependency_overrides[get_runtime] = lambda: runtime

    return app, runtime, store


def test_api_stale_endpoint():
    """GET /procedures/stale returns stale procedures."""
    app, runtime, store = _make_app()
    store.get_stale_procedures.return_value = [
        {"id": "s1", "name": "Stale", "compilation_level": 3,
         "last_used_at": time.time() - 86400 * 40, "days_unused": 40,
         "total_completions": 5, "total_selections": 8},
    ]
    client = TestClient(app)
    resp = client.get("/api/procedures/stale")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["stale"][0]["id"] == "s1"


def test_api_stale_custom_days():
    """?days=60 query param works."""
    app, runtime, store = _make_app()
    client = TestClient(app)
    resp = client.get("/api/procedures/stale?days=60")
    assert resp.status_code == 200
    store.get_stale_procedures.assert_called_once_with(days=60)


def test_api_archived_endpoint():
    """GET /procedures/archived returns archived procedures."""
    app, runtime, store = _make_app()
    store.get_archived_procedures.return_value = [
        {"id": "a1", "name": "Archived", "compilation_level": 1,
         "last_used_at": 0, "total_completions": 3, "archived_at": time.time()},
    ]
    client = TestClient(app)
    resp = client.get("/api/procedures/archived")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1


def test_api_restore_endpoint():
    """POST /procedures/restore restores procedure."""
    app, runtime, store = _make_app()
    from probos.cognitive.procedures import Procedure, ProcedureStep
    store.get.return_value = Procedure(
        id="r1", name="Restored", steps=[ProcedureStep(step_number=1, action="test")]
    )
    client = TestClient(app)
    resp = client.post("/api/procedures/restore", json={"procedure_id": "r1"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


def test_api_duplicates_endpoint():
    """GET /procedures/duplicates returns candidates."""
    app, runtime, store = _make_app()
    store.find_duplicate_candidates.return_value = [
        {"primary_id": "p1", "primary_name": "A", "duplicate_id": "d1",
         "duplicate_name": "B", "similarity": 0.92},
    ]
    client = TestClient(app)
    resp = client.get("/api/procedures/duplicates")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1


def test_api_merge_endpoint():
    """POST /procedures/merge merges procedures."""
    app, runtime, store = _make_app()
    from probos.cognitive.procedures import Procedure, ProcedureStep
    p = Procedure(id="p1", name="Primary", steps=[ProcedureStep(step_number=1, action="test")])
    d = Procedure(id="d1", name="Dup", steps=[ProcedureStep(step_number=1, action="test")])
    store.get = AsyncMock(side_effect=lambda pid: p if pid == "p1" else d)
    store.get_quality_metrics.return_value = {"total_completions": 15}

    client = TestClient(app)
    resp = client.post("/api/procedures/merge", json={"primary_id": "p1", "duplicate_id": "d1"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["combined_completions"] == 15


def test_api_merge_invalid():
    """Bad IDs → error."""
    app, runtime, store = _make_app()
    store.get.return_value = None
    client = TestClient(app)
    resp = client.post("/api/procedures/merge", json={"primary_id": "bad1", "duplicate_id": "bad2"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "not found" in data["error"]
