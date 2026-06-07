"""AD-900 — Governed directive authoring HTTP surface.

BF-287 discipline: a real ``DirectiveStore`` (tmp-file SQLite) and a real,
hand-written registry stub — no MagicMock at the substrate boundary. The store
is synchronous ``sqlite3`` (``check_same_thread`` default), so the suite drives
the app in-process via ``httpx.ASGITransport``/``AsyncClient``: the store, the
seed helpers, and the endpoints all execute in the test coroutine's single
thread, mirroring how the production runtime creates the store and serves async
endpoints from one event-loop thread.

The composed-instruction invalidation contract (``standing_orders.clear_cache``
must fire on every mutation, exactly as the ``/order`` CLI does) is verified by
monkeypatching the ``clear_cache`` symbol the router actually calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.directive_store import DirectiveStore, DirectiveType, DirectiveStatus
from probos.crew_profile import Rank
from probos.routers import crew as crew_router
from probos.routers.deps import get_runtime


@dataclass
class _FakeAgent:
    id: str
    agent_type: str


@dataclass
class _FakeRegistry:
    agents: dict[str, _FakeAgent] = field(default_factory=dict)

    def get(self, agent_id: str) -> _FakeAgent | None:
        return self.agents.get(agent_id)


@dataclass
class _FakeOntology:
    departments: dict[str, str] = field(default_factory=dict)

    def get_agent_department(self, agent_type: str) -> str | None:
        return self.departments.get(agent_type)


@dataclass
class _Runtime:
    directive_store: DirectiveStore | None = None
    registry: _FakeRegistry | None = None
    ontology: _FakeOntology | None = None


def _make_runtime(tmp_path: Any, *, with_store: bool = True) -> _Runtime:
    registry = _FakeRegistry(agents={"agent-1": _FakeAgent("agent-1", "builder")})
    ontology = _FakeOntology(departments={"builder": "engineering"})
    store = DirectiveStore(db_path=str(tmp_path / "directives.db")) if with_store else None
    return _Runtime(directive_store=store, registry=registry, ontology=ontology)


def _client_for(runtime: _Runtime) -> AsyncClient:
    app = FastAPI()
    app.include_router(crew_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def cache_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count invocations of the ``clear_cache`` the router actually calls."""
    calls: list[int] = []
    monkeypatch.setattr(
        crew_router.standing_orders, "clear_cache", lambda: calls.append(1)
    )
    return calls


def _seed_pending(runtime: _Runtime) -> str:
    """Create a PENDING_APPROVAL peer suggestion and return its id."""
    assert runtime.directive_store is not None
    directive, _reason = runtime.directive_store.create_directive(
        issuer_type="builder",
        issuer_department="engineering",
        issuer_rank=Rank.LIEUTENANT,
        target_agent_type="builder",
        target_department=None,
        directive_type=DirectiveType.PEER_SUGGESTION,
        content="Suggest a retro",
    )
    assert directive is not None
    assert directive.status == DirectiveStatus.PENDING_APPROVAL
    return directive.id


# ----------------------------------------------------------------------
# GET /api/crew/{agent_id}/directives
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_captain_order_appears_active_in_list(tmp_path: Any, cache_calls: list[int]) -> None:
    runtime = _make_runtime(tmp_path)
    async with _client_for(runtime) as client:
        post = await client.post("/api/crew/agent-1/directives", json={"content": "Prioritize tests"})
        assert post.status_code == 200
        listing = await client.get("/api/crew/agent-1/directives")

    assert listing.status_code == 200
    body = listing.json()
    assert body["count"] == 1
    entry = body["directives"][0]
    assert entry["content"] == "Prioritize tests"
    assert entry["status"] == DirectiveStatus.ACTIVE.value
    assert entry["directive_type"] == DirectiveType.CAPTAIN_ORDER.value
    assert entry["target_department"] == "engineering"


@pytest.mark.asyncio
async def test_list_directives_unknown_agent_404(tmp_path: Any) -> None:
    runtime = _make_runtime(tmp_path)
    async with _client_for(runtime) as client:
        resp = await client.get("/api/crew/ghost/directives")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_directives_no_store_honest_degrades(tmp_path: Any) -> None:
    runtime = _make_runtime(tmp_path, with_store=False)
    async with _client_for(runtime) as client:
        resp = await client.get("/api/crew/agent-1/directives")
    assert resp.status_code == 200
    body = resp.json()
    assert body["directives"] == []
    assert body["count"] == 0


@pytest.mark.asyncio
async def test_broadcast_directive_appears_for_agent(tmp_path: Any) -> None:
    runtime = _make_runtime(tmp_path)
    assert runtime.directive_store is not None
    runtime.directive_store.create_directive(
        issuer_type="captain",
        issuer_department=None,
        issuer_rank=Rank.SENIOR,
        target_agent_type="*",
        target_department=None,
        directive_type=DirectiveType.CAPTAIN_ORDER,
        content="All hands: log everything",
    )
    async with _client_for(runtime) as client:
        resp = await client.get("/api/crew/agent-1/directives")
    assert resp.status_code == 200
    contents = [d["content"] for d in resp.json()["directives"]]
    assert "All hands: log everything" in contents


# ----------------------------------------------------------------------
# POST /api/crew/{agent_id}/directives
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_directive_invokes_clear_cache(tmp_path: Any, cache_calls: list[int]) -> None:
    runtime = _make_runtime(tmp_path)
    async with _client_for(runtime) as client:
        resp = await client.post("/api/crew/agent-1/directives", json={"content": "Be careful"})
    assert resp.status_code == 200
    assert len(cache_calls) == 1


@pytest.mark.asyncio
async def test_issue_directive_missing_content_400(tmp_path: Any) -> None:
    runtime = _make_runtime(tmp_path)
    async with _client_for(runtime) as client:
        resp = await client.post("/api/crew/agent-1/directives", json={})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_issue_directive_unknown_agent_404(tmp_path: Any) -> None:
    runtime = _make_runtime(tmp_path)
    async with _client_for(runtime) as client:
        resp = await client.post("/api/crew/ghost/directives", json={"content": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_issue_directive_no_store_503(tmp_path: Any) -> None:
    runtime = _make_runtime(tmp_path, with_store=False)
    async with _client_for(runtime) as client:
        resp = await client.post("/api/crew/agent-1/directives", json={"content": "x"})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_duplicate_issue_returns_authorization_reason(tmp_path: Any, cache_calls: list[int]) -> None:
    runtime = _make_runtime(tmp_path)
    async with _client_for(runtime) as client:
        first = await client.post("/api/crew/agent-1/directives", json={"content": "Same order"})
        assert first.status_code == 200
        dup = await client.post("/api/crew/agent-1/directives", json={"content": "Same order"})
    assert dup.status_code == 400
    assert "Duplicate" in dup.json()["detail"]


# ----------------------------------------------------------------------
# POST /api/crew/directives/{directive_id}/approve
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_pending_directive_becomes_active(tmp_path: Any, cache_calls: list[int]) -> None:
    runtime = _make_runtime(tmp_path)
    directive_id = _seed_pending(runtime)
    async with _client_for(runtime) as client:
        resp = await client.post(f"/api/crew/directives/{directive_id}/approve")
        listing = await client.get("/api/crew/agent-1/directives")
    assert resp.status_code == 200
    assert len(cache_calls) == 1
    statuses = {d["id"]: d["status"] for d in listing.json()["directives"]}
    assert statuses[directive_id] == DirectiveStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_approve_unknown_directive_404(tmp_path: Any) -> None:
    runtime = _make_runtime(tmp_path)
    async with _client_for(runtime) as client:
        resp = await client.post("/api/crew/directives/nope/approve")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_no_store_503(tmp_path: Any) -> None:
    runtime = _make_runtime(tmp_path, with_store=False)
    async with _client_for(runtime) as client:
        resp = await client.post("/api/crew/directives/x/approve")
    assert resp.status_code == 503


# ----------------------------------------------------------------------
# DELETE /api/crew/directives/{directive_id}
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_directive_disappears_from_list(tmp_path: Any, cache_calls: list[int]) -> None:
    runtime = _make_runtime(tmp_path)
    async with _client_for(runtime) as client:
        post = await client.post("/api/crew/agent-1/directives", json={"content": "Temporary"})
        directive_id = post.json()["id"]
        revoke = await client.delete(f"/api/crew/directives/{directive_id}")
        listing = await client.get("/api/crew/agent-1/directives")
    assert revoke.status_code == 200
    assert revoke.json()["revoked"] is True
    ids = [d["id"] for d in listing.json()["directives"]]
    assert directive_id not in ids


@pytest.mark.asyncio
async def test_revoke_unknown_directive_404(tmp_path: Any) -> None:
    runtime = _make_runtime(tmp_path)
    async with _client_for(runtime) as client:
        resp = await client.delete("/api/crew/directives/nope")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_revoke_invokes_clear_cache(tmp_path: Any, cache_calls: list[int]) -> None:
    runtime = _make_runtime(tmp_path)
    async with _client_for(runtime) as client:
        post = await client.post("/api/crew/agent-1/directives", json={"content": "Throwaway"})
        cache_calls.clear()
        await client.delete(f"/api/crew/directives/{post.json()['id']}")
    assert len(cache_calls) == 1


# ----------------------------------------------------------------------
# PATCH /api/crew/directives/{directive_id}
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_amend_directive_updates_content(tmp_path: Any, cache_calls: list[int]) -> None:
    runtime = _make_runtime(tmp_path)
    async with _client_for(runtime) as client:
        post = await client.post("/api/crew/agent-1/directives", json={"content": "Original"})
        directive_id = post.json()["id"]
        cache_calls.clear()
        amend = await client.patch(
            f"/api/crew/directives/{directive_id}", json={"content": "Amended"}
        )
        listing = await client.get("/api/crew/agent-1/directives")
    assert amend.status_code == 200
    assert amend.json()["content"] == "Amended"
    assert len(cache_calls) == 1
    contents = {d["id"]: d["content"] for d in listing.json()["directives"]}
    assert contents[directive_id] == "Amended"


@pytest.mark.asyncio
async def test_amend_missing_content_400(tmp_path: Any) -> None:
    runtime = _make_runtime(tmp_path)
    async with _client_for(runtime) as client:
        post = await client.post("/api/crew/agent-1/directives", json={"content": "Original"})
        resp = await client.patch(f"/api/crew/directives/{post.json()['id']}", json={})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_amend_unknown_directive_404(tmp_path: Any) -> None:
    runtime = _make_runtime(tmp_path)
    async with _client_for(runtime) as client:
        resp = await client.patch("/api/crew/directives/nope", json={"content": "x"})
    assert resp.status_code == 404
