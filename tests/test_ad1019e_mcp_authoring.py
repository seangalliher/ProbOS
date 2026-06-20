"""AD-1019e: MCP authoring endpoints (risk tiers + department lockers).

The HTTP authoring surface over the **pre-existing** AD-1019b stores — risk
set/clear/read and department-locker stock/unstock/list. Backend-only; the stores
are not modified.

BF-287 (no MagicMock at the substrate boundary): the registry/ontology/agent are
REAL small stub classes (an attribute typo surfaces instead of auto-faking), the
bridge is a tiny ``_Fake*`` whose ``list_tools()`` returns a fixed tool set, and
**every store is a REAL store over a real ``tmp_path`` DB** (NOT ``db_path=""``
cache-only — a real DB exercises ``_row_to_*`` / ``rowcount``). One test reopens
the department DB to prove persistence + ``_row_to_grant`` reload.

DD-1 (load-bearing): the risk store keys on the server RECORD id — the same key
the AD-1019c dispatch reads (``mcp_workbench.py``/``agentic_dispatch.py`` both
read ``get_risk_sync(record.id, tool)``; the adapter is built with
``server_id=record.id``). The PUT/DELETE/GET-read all use the ``{server_id}``
path param, which IS the record id, so an authored override is the one the
dispatch resolves.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1019e_mcp_authoring.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

import sys
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.config import MCPConfig, SystemConfig
from probos.integrations.mcp_bridge.department_grants import DepartmentToolGrantStore
from probos.integrations.mcp_bridge.risk import McpToolRisk, McpToolRiskStore
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore
from probos.routers.mcp_departments import router as mcp_departments_router
from probos.routers.mcp_servers import router as mcp_servers_router
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission

_AGENT = "sci-1"
_AGENT_TYPE = "scientist"
_DEPT = "science"
_DEFAULT_TOOLS = [
    {"name": "reverse", "description": "reverse a string"},
    {"name": "shout", "description": "uppercase a string"},
]


# --------------------------------------------------------------------------- #
# Real (non-Mock) substrate stubs — an attribute typo surfaces, not auto-faked.
# --------------------------------------------------------------------------- #


class _Agent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


class _Registry:
    def __init__(self, agents: dict[str, _Agent]) -> None:
        self._agents = agents

    def get(self, agent_id: str) -> _Agent | None:
        return self._agents.get(agent_id)


class _Ontology:
    def __init__(self, dept_map: dict[str, str]) -> None:
        self._dept_map = dept_map

    def get_agent_department(self, agent_type: str) -> str | None:
        return self._dept_map.get(agent_type)


class _FakeClient:
    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self._tools = tools

    async def list_tools(self) -> list[dict[str, Any]]:
        return self._tools


class _FakeBridge:
    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self._client = _FakeClient(tools)

    def get_client(self, _key: str) -> _FakeClient:
        return self._client


class _Runtime:
    def __init__(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


def _config(*, management_enabled: bool = True) -> SystemConfig:
    return SystemConfig(
        mcp=MCPConfig(
            management_enabled=management_enabled,
            command_allowlist=["python", sys.executable],
            request_timeout_seconds=5.0,
        )
    )


async def _make(
    tmp_path: Any,
    *,
    management_enabled: bool = True,
    tools: list[dict[str, Any]] | None = None,
) -> tuple[TestClient, str, _Runtime]:
    """Build real-DB stores + a fake bridge + real registry/ontology stubs.

    Returns ``(client, server_id, runtime)``. The TestClient mounts BOTH the
    mcp_servers and mcp_departments routers (test 8 spans both surfaces).
    """
    server_store = McpServerStore(db_path=str(tmp_path / "srv.db"))
    await server_store.start()
    record = await server_store.create(
        McpServerRecord(name="echo", type="http", url="https://echo.test/mcp")
    )

    risk_store = McpToolRiskStore(db_path=str(tmp_path / "risk.db"))
    await risk_store.start()

    dept_store = DepartmentToolGrantStore(db_path=str(tmp_path / "dept.db"))
    await dept_store.start()

    perms = ToolPermissionStore(db_path=str(tmp_path / "perm.db"))
    await perms.start()

    runtime = _Runtime(
        config=_config(management_enabled=management_enabled),
        mcp_server_store=server_store,
        mcp_bridge=_FakeBridge(_DEFAULT_TOOLS if tools is None else tools),
        mcp_tool_risk_store=risk_store,
        department_tool_grant_store=dept_store,
        tool_permission_store=perms,
        registry=_Registry({_AGENT: _Agent(_AGENT_TYPE)}),
        ontology=_Ontology({_AGENT_TYPE: _DEPT}),
    )

    app = FastAPI()
    app.include_router(mcp_servers_router)
    app.include_router(mcp_departments_router)
    app.state.runtime = runtime
    return TestClient(app), record.id, runtime


# --------------------------------------------------------------------------- #
# (1)-(3),(5)-(7) — risk authoring + read
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_put_risk_happy_returns_risk(tmp_path: Any) -> None:
    client, sid, _ = await _make(tmp_path)
    resp = client.put(f"/api/mcp/servers/{sid}/tools/reverse/risk", json={"risk": "confirm"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"server_id": sid, "tool": "reverse", "risk": "confirm"}


@pytest.mark.asyncio
async def test_put_risk_invalid_value_400(tmp_path: Any) -> None:
    client, sid, _ = await _make(tmp_path)
    resp = client.put(f"/api/mcp/servers/{sid}/tools/reverse/risk", json={"risk": "nuke"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_risk"


@pytest.mark.asyncio
async def test_put_risk_unknown_server_404(tmp_path: Any) -> None:
    client, _, _ = await _make(tmp_path)
    resp = client.put("/api/mcp/servers/does-not-exist/tools/reverse/risk", json={"risk": "open"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "not_found"


@pytest.mark.asyncio
async def test_delete_risk_cleared_true_then_false(tmp_path: Any) -> None:
    client, sid, _ = await _make(tmp_path)
    put = client.put(f"/api/mcp/servers/{sid}/tools/reverse/risk", json={"risk": "consensus"})
    assert put.status_code == 200, put.text
    first = client.delete(f"/api/mcp/servers/{sid}/tools/reverse/risk")
    assert first.status_code == 200
    assert first.json() == {"cleared": True}
    second = client.delete(f"/api/mcp/servers/{sid}/tools/reverse/risk")
    assert second.status_code == 200
    assert second.json() == {"cleared": False}


@pytest.mark.asyncio
async def test_get_tools_reports_risk_default_then_override(tmp_path: Any) -> None:
    client, sid, _ = await _make(tmp_path)
    # No override → server default ('open') + risk_source 'default'.
    before = client.get(f"/api/mcp/servers/{sid}/tools")
    assert before.status_code == 200, before.text
    by_name = {t["name"]: t for t in before.json()["tools"]}
    assert by_name["reverse"]["risk"] == "open"
    assert by_name["reverse"]["risk_source"] == "default"
    # Set an override → that tool reports the override + 'override'.
    client.put(f"/api/mcp/servers/{sid}/tools/reverse/risk", json={"risk": "confirm"})
    after = client.get(f"/api/mcp/servers/{sid}/tools")
    by_name = {t["name"]: t for t in after.json()["tools"]}
    assert by_name["reverse"]["risk"] == "confirm"
    assert by_name["reverse"]["risk_source"] == "override"
    # A sibling without an override still resolves to the default.
    assert by_name["shout"]["risk"] == "open"
    assert by_name["shout"]["risk_source"] == "default"


@pytest.mark.asyncio
async def test_dd1_authored_override_is_the_key_the_dispatch_reads(tmp_path: Any) -> None:
    """DD-1: the PUT writes ``(server_id=record.id, tool)`` — the exact key both
    the workbench and the agentic dispatch read via ``get_risk_sync(record.id, tool)``.
    """
    client, sid, runtime = await _make(tmp_path)
    resp = client.put(f"/api/mcp/servers/{sid}/tools/reverse/risk", json={"risk": "confirm"})
    assert resp.status_code == 200, resp.text
    # The dispatch reads with the record id (== the path param sid) — parity.
    assert runtime.mcp_tool_risk_store.get_risk_sync(sid, "reverse") == McpToolRisk.CONFIRM
    # A different tool name (same server id) has no override.
    assert runtime.mcp_tool_risk_store.get_risk_sync(sid, "shout") is None


# --------------------------------------------------------------------------- #
# (8)-(10) — department lockers + the #964 integration loop
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dept_stock_lists_and_resolves_department_for_member(tmp_path: Any) -> None:
    """Stock the server into the science locker; an agent in science resolves
    ``source="department"`` for the tool — the loop that closes #964."""
    client, sid, _ = await _make(tmp_path)
    stock = client.post(
        f"/api/mcp/departments/{_DEPT}/tools",
        json={"server_id": sid, "enabled": True},
    )
    assert stock.status_code == 200, stock.text
    grant = stock.json()
    assert grant["department"] == _DEPT
    assert grant["enabled"] is True
    assert grant["is_restriction"] is False

    listed = client.get("/api/mcp/departments/grants")
    assert listed.status_code == 200
    grants = listed.json()["grants"]
    assert any(g["grant_id"] == grant["grant_id"] for g in grants)

    # The integration proof: the agent's per-tool access resolves to department.
    access = client.get(f"/api/mcp/servers/{sid}/agents/{_AGENT}/access")
    assert access.status_code == 200, access.text
    by_name = {t["name"]: t for t in access.json()["tools"]}
    assert by_name["reverse"]["enabled"] is True
    assert by_name["reverse"]["source"] == "department"


@pytest.mark.asyncio
async def test_dept_delete_grant_revoked_true(tmp_path: Any) -> None:
    client, sid, _ = await _make(tmp_path)
    stock = client.post(
        f"/api/mcp/departments/{_DEPT}/tools",
        json={"server_id": sid, "tool": "reverse", "enabled": True},
    )
    grant_id = stock.json()["grant_id"]
    resp = client.delete(f"/api/mcp/departments/grants/{grant_id}")
    assert resp.status_code == 200
    assert resp.json() == {"revoked": True}
    # Revoking an unknown id is a clean False (not 404).
    again = client.delete(f"/api/mcp/departments/grants/{grant_id}")
    assert again.json() == {"revoked": False}


@pytest.mark.asyncio
async def test_dept_stock_unknown_server_404(tmp_path: Any) -> None:
    client, _, _ = await _make(tmp_path)
    resp = client.post(
        f"/api/mcp/departments/{_DEPT}/tools",
        json={"server_id": "nope", "enabled": True},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "not_found"


# --------------------------------------------------------------------------- #
# (4) — gate-off: every new endpoint 404 feature_disabled
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_gate_off_all_new_endpoints_404(tmp_path: Any) -> None:
    client, sid, _ = await _make(tmp_path, management_enabled=False)
    cases = [
        client.put(f"/api/mcp/servers/{sid}/tools/reverse/risk", json={"risk": "open"}),
        client.delete(f"/api/mcp/servers/{sid}/tools/reverse/risk"),
        client.get("/api/mcp/departments/grants"),
        client.post(f"/api/mcp/departments/{_DEPT}/tools", json={"server_id": sid, "enabled": True}),
        client.delete("/api/mcp/departments/grants/any-id"),
    ]
    for resp in cases:
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "feature_disabled"


# --------------------------------------------------------------------------- #
# Real-DB persistence: reopen proves _row_to_grant reload + rowcount semantics.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dept_grant_persists_across_reopen(tmp_path: Any) -> None:
    db = str(tmp_path / "dept_reopen.db")
    store = DepartmentToolGrantStore(db_path=db)
    await store.start()
    grant = await store.issue_grant(
        _DEPT, "mcp:echo", ToolPermission.WRITE, is_restriction=False, reason="locker"
    )
    await store.stop()

    reopened = DepartmentToolGrantStore(db_path=db)
    await reopened.start()
    try:
        active = reopened.get_active_grants_sync(_DEPT)
        assert len(active) == 1
        assert active[0].tool_id == "mcp:echo"
        assert active[0].agent_id == _DEPT  # agent_id carries the department
        assert active[0].permission == ToolPermission.WRITE
        # rowcount semantics on a real DB: True the first time, False the second.
        assert await reopened.revoke_grant(grant.id) is True
        assert await reopened.revoke_grant(grant.id) is False
    finally:
        await reopened.stop()
