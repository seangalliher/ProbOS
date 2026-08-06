from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.capability_request import CapabilityRequestStore
from probos.routers.capability_requests import router
from probos.routers.deps import get_runtime


class _FakeRuntime:
    def __init__(self, store: CapabilityRequestStore | None) -> None:
        self.capability_request_store = store


def _client_for(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


@pytest.fixture
async def store(tmp_path: Any) -> CapabilityRequestStore:
    s = CapabilityRequestStore(db_path=str(tmp_path / "caprequests.db"))
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


async def test_list_pending_returns_filed_requests(store: CapabilityRequestStore) -> None:
    await store.file_request(
        agent_id="agent-1", kind="install", target="numpy",
        rationale="need arrays", work_item_id="wi-1",
    )
    client = _client_for(_FakeRuntime(store))

    resp = client.get("/api/capability-requests?status=pending")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert len(body["requests"]) == 1
    req = body["requests"][0]
    assert req["agent_id"] == "agent-1"
    assert req["kind"] == "install"
    assert req["target"] == "numpy"
    assert req["rationale"] == "need arrays"
    assert req["work_item_id"] == "wi-1"


async def test_list_non_pending_status_returns_empty(store: CapabilityRequestStore) -> None:
    await store.file_request(agent_id="agent-1", kind="grant", target="fs.write")
    client = _client_for(_FakeRuntime(store))

    resp = client.get("/api/capability-requests?status=approved")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"requests": [], "status": "approved"}


def test_list_without_store_returns_503() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.get("/api/capability-requests?status=pending")

    assert resp.status_code == 503


async def test_decide_approve_updates_status(store: CapabilityRequestStore) -> None:
    req = await store.file_request(agent_id="agent-1", kind="build", target="ScraperAgent")
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        f"/api/capability-requests/{req.id}/decide",
        json={"approve": True},
    )

    assert resp.status_code == 200
    decided = resp.json()["request"]
    assert decided["status"] == "approved"
    assert decided["decided_by"] == "captain"


async def test_decide_deny_records_reason(store: CapabilityRequestStore) -> None:
    req = await store.file_request(agent_id="agent-1", kind="grant", target="root")
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        f"/api/capability-requests/{req.id}/decide",
        json={"approve": False, "reason": "too broad"},
    )

    assert resp.status_code == 200
    decided = resp.json()["request"]
    assert decided["status"] == "denied"
    assert decided["decision_reason"] == "too broad"


async def test_decide_deny_without_reason_is_422(store: CapabilityRequestStore) -> None:
    req = await store.file_request(agent_id="agent-1", kind="grant", target="root")
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        f"/api/capability-requests/{req.id}/decide",
        json={"approve": False, "reason": "   "},
    )

    assert resp.status_code == 422


async def test_decide_unknown_id_is_404(store: CapabilityRequestStore) -> None:
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        "/api/capability-requests/does-not-exist/decide",
        json={"approve": True},
    )

    assert resp.status_code == 404


async def test_decide_already_decided_is_400(store: CapabilityRequestStore) -> None:
    # BF-722 UPDATED THIS TEST. It used to approve the request and then assert
    # that re-approving it was a 400 — which pinned the defect as the contract.
    # Fulfilment can fail while the approval is durably recorded, and the
    # blanket guard then refused the only retry. Re-approving an ``approved``
    # request is now a retry of the fulfilment (see the test below).
    #
    # The guard still has teeth for every other decided status, so this case
    # moved to ``denied``: re-approving a denial is a reversal, not a retry.
    req = await store.file_request(agent_id="agent-1", kind="install", target="pandas")
    await store.decide(req.id, False, reason="not now")
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        f"/api/capability-requests/{req.id}/decide",
        json={"approve": True},
    )

    assert resp.status_code == 400


async def test_decide_already_approved_retries_fulfilment_with_200(
    store: CapabilityRequestStore,
) -> None:
    """BF-722: an approved request re-approved retries fulfilment, not the decision."""
    req = await store.file_request(agent_id="agent-1", kind="install", target="pandas")
    await store.decide(req.id, True)
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        f"/api/capability-requests/{req.id}/decide",
        json={"approve": True},
    )

    assert resp.status_code == 200
    body = resp.json()
    # ``install`` has no fulfiller, so the honest answer is "not fulfilled".
    assert body["fulfilled"] is False
    assert body["request"]["status"] == "approved"


async def test_decide_already_approved_then_denied_is_400(
    store: CapabilityRequestStore,
) -> None:
    """BF-722: re-DENYING an approved request is a revocation — out of scope."""
    req = await store.file_request(agent_id="agent-1", kind="install", target="pandas")
    await store.decide(req.id, True)
    client = _client_for(_FakeRuntime(store))

    resp = client.post(
        f"/api/capability-requests/{req.id}/decide",
        json={"approve": False, "reason": "changed my mind"},
    )

    assert resp.status_code == 400


def test_decide_without_store_returns_503() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.post(
        "/api/capability-requests/x/decide",
        json={"approve": True},
    )

    assert resp.status_code == 503
