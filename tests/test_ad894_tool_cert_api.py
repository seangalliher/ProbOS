"""AD-894 — Tool Registry + certification HTTP surface.

BF-287 discipline: real ``ToolRegistry`` and real ``ToolPermissionStore``
(tmp-file SQLite) — no MagicMock at the substrate boundary. Mutations flow
through the FastAPI ``TestClient`` so every DB op runs in the client's event
loop; ``start()`` only provisions the schema.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.routers import crew as crew_router
from probos.routers import tools as tools_router
from probos.routers.deps import get_runtime
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.permissions import ToolPermissionStore
from probos.tools.registry import ToolRegistry


class _StubTool:
    """Minimal Tool-protocol implementation for registry fixtures."""

    def __init__(
        self,
        tool_id: str,
        *,
        name: str = "Stub",
        tool_type: ToolType = ToolType.INFRA_SERVICE,
        description: str = "stub",
    ) -> None:
        self._tool_id = tool_id
        self._name = name
        self._tool_type = tool_type
        self._description = description

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return self._tool_type

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "string"}

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        return ToolResult(output="ok")


@dataclass
class _Runtime:
    tool_registry: ToolRegistry | None = None
    tool_permission_store: ToolPermissionStore | None = None


def _client_for(runtime: _Runtime) -> TestClient:
    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if runtime.tool_permission_store is not None:
            await runtime.tool_permission_store.start()
        try:
            yield
        finally:
            if runtime.tool_permission_store is not None:
                await runtime.tool_permission_store.stop()

    app = FastAPI(lifespan=_lifespan)
    app.include_router(crew_router.router)
    app.include_router(tools_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def _make_store(tmp_path: Any) -> ToolPermissionStore:
    return ToolPermissionStore(db_path=str(tmp_path / "tool_grants.db"))


def _make_registry(*tool_ids: str) -> ToolRegistry:
    registry = ToolRegistry()
    for tid in tool_ids:
        registry.register(_StubTool(tid, name=tid))
    return registry


# ----------------------------------------------------------------------
# GET /api/tools — catalog
# ----------------------------------------------------------------------


def test_list_tool_catalog_returns_registered_tools(tmp_path: Any) -> None:
    runtime = _Runtime(tool_registry=_make_registry("file_read", "shell"))
    with _client_for(runtime) as client:
        resp = client.get("/api/tools")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    ids = {t["tool_id"] for t in body["tools"]}
    assert ids == {"file_read", "shell"}


def test_list_tool_catalog_empty_when_no_registry() -> None:
    runtime = _Runtime(tool_registry=None)
    with _client_for(runtime) as client:
        resp = client.get("/api/tools")

    assert resp.status_code == 200
    assert resp.json() == {"tools": [], "count": 0}


# ----------------------------------------------------------------------
# GET /api/crew/{agent_id}/tools — certifications
# ----------------------------------------------------------------------


def test_crew_tools_empty_when_no_grants(tmp_path: Any) -> None:
    runtime = _Runtime(
        tool_registry=_make_registry("file_read"),
        tool_permission_store=_make_store(tmp_path),
    )
    with _client_for(runtime) as client:
        resp = client.get("/api/crew/agent-1/tools")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"agent_id": "agent-1", "certifications": [], "count": 0}


def test_crew_tools_empty_when_no_store() -> None:
    runtime = _Runtime(tool_permission_store=None)
    with _client_for(runtime) as client:
        resp = client.get("/api/crew/agent-1/tools")

    assert resp.status_code == 200
    assert resp.json()["certifications"] == []


def test_crew_tools_lists_active_grant_joined_with_metadata(tmp_path: Any) -> None:
    runtime = _Runtime(
        tool_registry=_make_registry("file_read"),
        tool_permission_store=_make_store(tmp_path),
    )
    with _client_for(runtime) as client:
        granted = client.post(
            "/api/crew/agent-1/tools",
            json={"tool_id": "file_read", "permission": "read", "reason": "duty"},
        )
        assert granted.status_code == 200
        resp = client.get("/api/crew/agent-1/tools")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    cert = body["certifications"][0]
    assert cert["tool_id"] == "file_read"
    assert cert["permission"] == "read"
    assert cert["is_restriction"] is False
    assert cert["tool"]["tool_id"] == "file_read"


# ----------------------------------------------------------------------
# POST /api/crew/{agent_id}/tools — grant
# ----------------------------------------------------------------------


def test_grant_tool_happy_path(tmp_path: Any) -> None:
    runtime = _Runtime(
        tool_registry=_make_registry("shell"),
        tool_permission_store=_make_store(tmp_path),
    )
    with _client_for(runtime) as client:
        resp = client.post(
            "/api/crew/agent-1/tools",
            json={"tool_id": "shell", "permission": "write", "reason": "ops"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["tool_id"] == "shell"
    assert body["permission"] == "write"
    assert body["issued_by"] == "captain"
    assert body["grant_id"]


def test_grant_tool_unknown_tool_returns_404(tmp_path: Any) -> None:
    runtime = _Runtime(
        tool_registry=_make_registry("file_read"),
        tool_permission_store=_make_store(tmp_path),
    )
    with _client_for(runtime) as client:
        resp = client.post(
            "/api/crew/agent-1/tools",
            json={"tool_id": "nonexistent", "permission": "read"},
        )

    assert resp.status_code == 404


def test_grant_tool_missing_fields_returns_400(tmp_path: Any) -> None:
    runtime = _Runtime(
        tool_registry=_make_registry("file_read"),
        tool_permission_store=_make_store(tmp_path),
    )
    with _client_for(runtime) as client:
        resp = client.post("/api/crew/agent-1/tools", json={"tool_id": "file_read"})

    assert resp.status_code == 400


def test_grant_tool_invalid_permission_returns_400(tmp_path: Any) -> None:
    runtime = _Runtime(
        tool_registry=_make_registry("file_read"),
        tool_permission_store=_make_store(tmp_path),
    )
    with _client_for(runtime) as client:
        resp = client.post(
            "/api/crew/agent-1/tools",
            json={"tool_id": "file_read", "permission": "superuser"},
        )

    assert resp.status_code == 400


def test_grant_tool_no_store_returns_503() -> None:
    runtime = _Runtime(tool_permission_store=None)
    with _client_for(runtime) as client:
        resp = client.post(
            "/api/crew/agent-1/tools",
            json={"tool_id": "file_read", "permission": "read"},
        )

    assert resp.status_code == 503


# ----------------------------------------------------------------------
# DELETE /api/crew/{agent_id}/tools/{grant_id} — revoke
# ----------------------------------------------------------------------


def test_revoke_tool_happy_path(tmp_path: Any) -> None:
    runtime = _Runtime(
        tool_registry=_make_registry("file_read"),
        tool_permission_store=_make_store(tmp_path),
    )
    with _client_for(runtime) as client:
        grant_id = client.post(
            "/api/crew/agent-1/tools",
            json={"tool_id": "file_read", "permission": "read"},
        ).json()["grant_id"]
        resp = client.delete(f"/api/crew/agent-1/tools/{grant_id}")
        assert resp.status_code == 200
        assert resp.json()["revoked"] is True
        # Grant disappears from the certification list after revoke.
        after = client.get("/api/crew/agent-1/tools").json()
        assert after["count"] == 0


def test_revoke_tool_unknown_returns_404(tmp_path: Any) -> None:
    runtime = _Runtime(
        tool_registry=_make_registry("file_read"),
        tool_permission_store=_make_store(tmp_path),
    )
    with _client_for(runtime) as client:
        resp = client.delete("/api/crew/agent-1/tools/does-not-exist")

    assert resp.status_code == 404
