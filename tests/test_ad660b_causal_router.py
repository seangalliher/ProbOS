"""AD-660b: tests for /api/causal-templates router."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from probos.routers.system import router


def _make_app(runtime: Any) -> FastAPI:  # type: ignore[name-defined]
    from probos.routers.deps import get_runtime, get_task_tracker
    app = FastAPI()
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_task_tracker] = lambda: SimpleNamespace()
    app.include_router(router)
    return app


from typing import Any  # placed after to avoid forward ref shadow


class _StubJournal:
    def __init__(self, rows):
        self._rows = rows
        self.calls: list[dict] = []

    async def get_recent_causal_templates(self, *, limit, agent_id=None, since=None):
        self.calls.append({"limit": limit, "agent_id": agent_id, "since": since})
        if agent_id:
            return [r for r in self._rows if r.get("agent_id") == agent_id][:limit]
        return self._rows[:limit]


def test_causal_templates_returns_templates() -> None:
    rows = [
        {"template_id": "t1", "agent_id": "alpha", "confidence": 0.8},
        {"template_id": "t2", "agent_id": "beta", "confidence": 0.6},
    ]
    runtime = SimpleNamespace(
        cognitive_journal=_StubJournal(rows),
        emergence_metrics_engine=None,
        commercial_overlay_loaded=False,
        loaded_extension_providers=(),
    )
    app = _make_app(runtime)
    client = TestClient(app)
    r = client.get("/api/causal-templates")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert {t["template_id"] for t in data["templates"]} == {"t1", "t2"}


def test_causal_templates_agent_id_filter() -> None:
    rows = [
        {"template_id": "t1", "agent_id": "alpha"},
        {"template_id": "t2", "agent_id": "beta"},
    ]
    runtime = SimpleNamespace(
        cognitive_journal=_StubJournal(rows),
        emergence_metrics_engine=None,
        commercial_overlay_loaded=False,
        loaded_extension_providers=(),
    )
    app = _make_app(runtime)
    client = TestClient(app)
    r = client.get("/api/causal-templates?agent_id=alpha")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["templates"][0]["template_id"] == "t1"


def test_causal_templates_no_journal_returns_empty() -> None:
    runtime = SimpleNamespace(
        cognitive_journal=None,
        emergence_metrics_engine=None,
        commercial_overlay_loaded=False,
        loaded_extension_providers=(),
    )
    app = _make_app(runtime)
    client = TestClient(app)
    r = client.get("/api/causal-templates")
    assert r.status_code == 200
    assert r.json() == {"templates": [], "count": 0}


def test_causal_templates_journal_failure_log_and_degrade() -> None:
    class _Boom:
        async def get_recent_causal_templates(self, **kw):
            raise RuntimeError("db down")
    runtime = SimpleNamespace(
        cognitive_journal=_Boom(),
        emergence_metrics_engine=None,
        commercial_overlay_loaded=False,
        loaded_extension_providers=(),
    )
    app = _make_app(runtime)
    client = TestClient(app)
    r = client.get("/api/causal-templates")
    assert r.status_code == 200
    assert r.json() == {"templates": [], "count": 0}


def test_causal_templates_limit_clamped() -> None:
    rows = [{"template_id": f"t{i}", "agent_id": "alpha"} for i in range(50)]
    journal = _StubJournal(rows)
    runtime = SimpleNamespace(
        cognitive_journal=journal,
        emergence_metrics_engine=None,
        commercial_overlay_loaded=False,
        loaded_extension_providers=(),
    )
    app = _make_app(runtime)
    client = TestClient(app)
    # Limit 1000 should be clamped to 200
    client.get("/api/causal-templates?limit=1000")
    assert journal.calls[-1]["limit"] == 200
    # Limit 0 should be clamped to 1
    client.get("/api/causal-templates?limit=0")
    assert journal.calls[-1]["limit"] == 1
