"""AD-908: tests for the skill-request decision API surface.

asyncio_mode="auto": plain ``async def``. Real ``SkillRequestStore`` behind a
``_FakeRuntime`` (BF-287). Default-OFF parity is exercised by pointing the
runtime's ``skill_request_store`` at None — the mutating endpoints must 503.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from probos.config import SystemConfig
from probos.routers.deps import get_runtime
from probos.routers.readiness import unavailable_dependency
from probos.routers.skill_requests import router
from probos.skill_request import SkillRequest, SkillRequestStore


class _FakeRuntime:
    def __init__(self, store: SkillRequestStore | _FakeReadStore | None, config: object | None = None) -> None:
        self.skill_request_store = store
        self.config = config


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


def test_list_for_agent_absent_store_is_unavailable_not_empty() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.get("/api/skill-requests/agent/agent-1")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "skill request store not available"
    assert resp.json()["availability"]["state"] == "unavailable"


class _FakeReadStore:
    def __init__(self, result: Any, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def _read(self, key: str) -> Any:
        self.calls.append(key)
        if self.error is not None:
            raise self.error
        return self.result

    async def list_pending(self) -> Any:
        return self._read("pending")

    async def list_by_agent(self, agent_id: str) -> Any:
        return self._read(agent_id)


@pytest.mark.parametrize("route", ["?status=pending", "/agent/agent-1"])
@pytest.mark.parametrize("enabled", [False, True, None])
def test_skill_get_missing_store_typed_availability(route: str, enabled: bool | None) -> None:
    config = None if enabled is None else SystemConfig.model_validate({"skill_requests": {"enabled": enabled}})
    with _client_for(_FakeRuntime(None, config)) as client:
        response = client.get(f"/api/skill-requests{route}")
    assert response.status_code == 503
    assert response.json() == {
        "detail": "skill request store not available",
        "availability": unavailable_dependency(config, "skill_requests"),
    }


@pytest.mark.parametrize("route,key", [("?status=pending", "pending"), ("/agent/agent-1", "agent-1")])
@pytest.mark.parametrize("populated", [False, True])
def test_skill_get_success_http_body_unchanged(route: str, key: str, populated: bool) -> None:
    requests = [SkillRequest(id="request-1", agent_id="agent-1", skill_id="summary")] if populated else []
    read_store = _FakeReadStore(requests)
    with _client_for(_FakeRuntime(read_store, SystemConfig())) as client:
        response = client.get(f"/api/skill-requests{route}")
    assert read_store.calls == [key]
    expected: dict[str, Any] = {"requests": [asdict(request) for request in requests]}
    if key == "pending":
        expected["status"] = "pending"
    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.parametrize("route", ["?status=pending", "/agent/agent-1"])
@pytest.mark.parametrize("raises", [False, True])
def test_skill_get_read_failure_not_empty_or_leaked(
    route: str, raises: bool, caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "token=private C:/private/skills.db"
    read_store = _FakeReadStore(None, OSError(secret) if raises else None)
    with _client_for(_FakeRuntime(read_store, SystemConfig())) as client:
        response = client.get(f"/api/skill-requests{route}")
    assert len(read_store.calls) == 1
    assert response.status_code == 500
    message = "skill requests unavailable" if route.startswith("?") else "skill request history unavailable"
    assert response.json() == {
        "detail": message,
        "availability": {
            "state": "failed", "code": "skill_requests.read_failed",
            "message": message, "retryable": True,
        },
    }
    assert "returning HTTP 500" in caplog.text
    assert secret not in response.text + caplog.text


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("route", ["?status=pending", "/agent/agent-1"])
def test_skill_get_authorization_preserved(route: str, status: int) -> None:
    read_store = _FakeReadStore(None, HTTPException(status_code=status, detail="Access denied"))
    with _client_for(_FakeRuntime(read_store, SystemConfig())) as client:
        response = client.get(f"/api/skill-requests{route}")
    assert len(read_store.calls) == 1
    assert response.status_code == status
    assert response.json() == {"detail": "Access denied"}


def test_skill_get_non_pending_compatibility_does_not_read() -> None:
    read_store = _FakeReadStore(None, RuntimeError("must not read"))
    with _client_for(_FakeRuntime(read_store, SystemConfig())) as client:
        response = client.get("/api/skill-requests?status=approved")
    assert response.status_code == 200
    assert response.json() == {"requests": [], "status": "approved"}
    assert read_store.calls == []


@pytest.mark.parametrize("enabled", [False, True])
def test_skill_decision_missing_store_legacy_response_unchanged(enabled: bool) -> None:
    config = SystemConfig.model_validate({"skill_requests": {"enabled": enabled}})
    with _client_for(_FakeRuntime(None, config)) as client:
        response = client.post("/api/skill-requests/x/decide", json={"approve": True})
    assert response.status_code == 503
    assert response.json() == {"detail": "skill request store not available"}
