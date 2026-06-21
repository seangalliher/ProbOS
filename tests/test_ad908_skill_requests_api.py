"""AD-908: tests for the skill-request decision API surface.

asyncio_mode="auto": plain ``async def``. Real ``SkillRequestStore`` behind a
``_FakeRuntime`` (BF-287). Default-OFF parity is exercised by pointing the
runtime's ``skill_request_store`` at None — the mutating endpoints must 503.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.routers.deps import get_runtime
from probos.routers.skill_requests import router
from probos.skill_request import SkillRequestStore


class _FakeRuntime:
    def __init__(self, store: SkillRequestStore | None) -> None:
        self.skill_request_store = store


def _client_for(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


@pytest.fixture
async def store(tmp_path: Any) -> SkillRequestStore:
    s = SkillRequestStore(db_path=str(tmp_path / "skill_requests.db"))
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


async def test_file_skill_request_creates_requested(store: SkillRequestStore) -> None:
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        "/api/skill-requests",
        json={
            "agent_id": "agent-1",
            "skill_id": "summarization",
            "skill_label": "Summarization",
            "source": "self",
            "justification": "condense reports",
        },
    )

    assert resp.status_code == 200
    req = resp.json()["request"]
    assert req["agent_id"] == "agent-1"
    assert req["skill_id"] == "summarization"
    assert req["status"] == "requested"
    assert req["source"] == "self"


async def test_list_pending_returns_filed_requests(store: SkillRequestStore) -> None:
    await store.file_request("agent-1", "negotiation", skill_label="Negotiation")
    client = _client_for(_FakeRuntime(store))

    resp = client.get("/api/skill-requests?status=pending")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert len(body["requests"]) == 1
    assert body["requests"][0]["skill_id"] == "negotiation"


async def test_list_non_pending_status_returns_empty(store: SkillRequestStore) -> None:
    await store.file_request("agent-1", "forecasting")
    client = _client_for(_FakeRuntime(store))

    resp = client.get("/api/skill-requests?status=approved")

    assert resp.status_code == 200
    assert resp.json() == {"requests": [], "status": "approved"}


async def test_decide_approve_updates_status(store: SkillRequestStore) -> None:
    req = await store.file_request("agent-1", "synthesis")
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        f"/api/skill-requests/{req.id}/decide", json={"approve": True}
    )

    assert resp.status_code == 200
    decided = resp.json()["request"]
    assert decided["status"] == "approved"
    assert decided["decided_by"] == "captain"


async def test_decide_deny_without_reason_is_422(store: SkillRequestStore) -> None:
    req = await store.file_request("agent-1", "translation")
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        f"/api/skill-requests/{req.id}/decide",
        json={"approve": False, "reason": "   "},
    )

    assert resp.status_code == 422


async def test_decide_unknown_id_is_404(store: SkillRequestStore) -> None:
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        "/api/skill-requests/does-not-exist/decide", json={"approve": True}
    )

    assert resp.status_code == 404


async def test_decide_already_decided_is_400(store: SkillRequestStore) -> None:
    req = await store.file_request("agent-1", "planning")
    await store.decide(req.id, True)
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        f"/api/skill-requests/{req.id}/decide", json={"approve": True}
    )

    assert resp.status_code == 400


def test_decide_without_store_returns_503() -> None:
    # Default-OFF: no store -> 503 (byte-identical disabled behavior).
    client = _client_for(_FakeRuntime(None))

    resp = client.post("/api/skill-requests/x/decide", json={"approve": True})

    assert resp.status_code == 503


def test_file_without_store_returns_503() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.post(
        "/api/skill-requests",
        json={"agent_id": "a", "skill_id": "s"},
    )

    assert resp.status_code == 503


def test_list_without_store_returns_503() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.get("/api/skill-requests?status=pending")

    assert resp.status_code == 503


async def test_begin_training_not_approved_is_400(store: SkillRequestStore) -> None:
    req = await store.file_request("agent-1", "summarization")  # status=requested
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        f"/api/skill-requests/{req.id}/begin-training",
        json={"simulation_id": "sim-1"},
    )

    assert resp.status_code == 400


async def test_begin_training_approved_links_simulation(store: SkillRequestStore) -> None:
    req = await store.file_request("agent-1", "synthesis")
    await store.decide(req.id, approve=True)
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        f"/api/skill-requests/{req.id}/begin-training",
        json={"simulation_id": "sim-9"},
    )

    assert resp.status_code == 200
    updated = resp.json()["request"]
    assert updated["status"] == "in_training"
    assert updated["linked_simulation_id"] == "sim-9"


async def test_begin_training_unknown_id_is_404(store: SkillRequestStore) -> None:
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        "/api/skill-requests/nope/begin-training",
        json={"simulation_id": "sim-1"},
    )

    assert resp.status_code == 404


def test_list_for_agent_honest_degrade_when_store_absent() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.get("/api/skill-requests/agent/agent-1")

    assert resp.status_code == 200
    assert resp.json() == {"requests": []}
