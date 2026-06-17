"""AD-1019b: get_agent_access router integration — the 3-source resolver wired
through the real substrate boundary (registry + ontology + both grant stores).

BF-287: the registry/ontology/agent are REAL small stub classes (not MagicMock),
so an attribute typo would surface instead of being auto-faked. The stores are
real (``db_path=""`` cache-only) and the bridge is a tiny fake whose
``list_tools()`` returns a fixed tool set so per-tool ``source`` is assertable.

Covers the ONLY production call site of ``_agent_department`` /
``resolve_mcp_access(department_grants=...)``.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1019b_router_access.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.config import MCPConfig, SystemConfig
from probos.integrations.mcp_bridge.access import mcp_server_tool_id, mcp_tool_tool_id
from probos.integrations.mcp_bridge.department_grants import DepartmentToolGrantStore
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission

_DEFAULT_TOOLS = [
    {"name": "get_forecast", "description": "forecast"},
    {"name": "get_humidity", "description": "humidity"},
]


# --------------------------------------------------------------------------- #
# Real (non-Mock) substrate stubs — attribute typos surface, not auto-faked.
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
    *,
    agent_grants: Sequence[tuple[str, bool]] = (),
    dept_grants: Sequence[tuple[str, bool]] = (),
    agent_type: str = "scientist",
    dept: str = "science",
    registry_has_agent: bool = True,
    with_ontology: bool = True,
    management_enabled: bool = True,
    tools: list[dict[str, Any]] | None = None,
) -> tuple[TestClient, str]:
    store = McpServerStore(db_path="")
    await store.start()
    record = await store.create(
        McpServerRecord(name="weather", type="http", url="https://example.com/mcp")
    )

    perms = ToolPermissionStore(db_path="")
    await perms.start()
    for tool_id, is_restriction in agent_grants:
        await perms.issue_grant(
            "agent-1",
            tool_id,
            ToolPermission.NONE if is_restriction else ToolPermission.READ,
            is_restriction=is_restriction,
        )

    dept_store = DepartmentToolGrantStore(db_path="")
    await dept_store.start()
    for tool_id, is_restriction in dept_grants:
        await dept_store.issue_grant(
            department=dept,
            tool_id=tool_id,
            permission=ToolPermission.NONE if is_restriction else ToolPermission.READ,
            is_restriction=is_restriction,
        )

    registry = _Registry({"agent-1": _Agent(agent_type)} if registry_has_agent else {})
    ontology = _Ontology({agent_type: dept}) if with_ontology else None

    runtime = _Runtime(
        config=_config(management_enabled=management_enabled),
        mcp_server_store=store,
        mcp_bridge=_FakeBridge(_DEFAULT_TOOLS if tools is None else tools),
        tool_permission_store=perms,
        department_tool_grant_store=dept_store,
        registry=registry,
        ontology=ontology,
    )

    from probos.routers.mcp_servers import router

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    return TestClient(app), record.id


def _get_access(client: TestClient, server_id: str) -> dict[str, Any]:
    resp = client.get(f"/api/mcp/servers/{server_id}/agents/agent-1/access")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _tool(body: dict[str, Any], name: str) -> dict[str, Any]:
    return next(t for t in body["tools"] if t["name"] == name)


# --------------------------------------------------------------------------- #
# Department tier folds in through the real registry+ontology resolution.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dept_server_grant_enables_via_resolved_department() -> None:
    """Agent has no grants; its department has a server-grant → enabled,
    source='department'. Proves registry→ontology→dept-store wiring."""
    client, sid = await _make(
        dept_grants=[(mcp_server_tool_id("weather"), False)]
    )
    body = _get_access(client, sid)
    assert body["server_enabled"] is True
    assert _tool(body, "get_forecast")["enabled"] is True
    assert _tool(body, "get_forecast")["source"] == "department"
    assert _tool(body, "get_humidity")["source"] == "department"


@pytest.mark.asyncio
async def test_agent_tool_restriction_overrides_dept_server_grant() -> None:
    """A per-agent tool restriction beats the department's broad server grant,
    but only for that one tool."""
    client, sid = await _make(
        agent_grants=[(mcp_tool_tool_id("weather", "get_forecast"), True)],
        dept_grants=[(mcp_server_tool_id("weather"), False)],
    )
    body = _get_access(client, sid)
    assert _tool(body, "get_forecast")["enabled"] is False
    assert _tool(body, "get_forecast")["source"] == "tool"
    # The other tool still rides the department server-grant.
    assert _tool(body, "get_humidity")["enabled"] is True
    assert _tool(body, "get_humidity")["source"] == "department"


# --------------------------------------------------------------------------- #
# Honest-degrade: when the department can't be resolved, dept grants are ignored
# (byte-identical to the AD-1019a two-source behavior).
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_no_ontology_ignores_department_grants() -> None:
    client, sid = await _make(
        dept_grants=[(mcp_server_tool_id("weather"), False)],
        with_ontology=False,
    )
    body = _get_access(client, sid)
    assert body["server_enabled"] is False
    assert _tool(body, "get_forecast")["source"] == "default"


@pytest.mark.asyncio
async def test_agent_absent_from_registry_ignores_department_grants() -> None:
    client, sid = await _make(
        dept_grants=[(mcp_server_tool_id("weather"), False)],
        registry_has_agent=False,
    )
    body = _get_access(client, sid)
    assert body["server_enabled"] is False
    assert _tool(body, "get_forecast")["source"] == "default"


@pytest.mark.asyncio
async def test_gate_off_returns_404() -> None:
    client, sid = await _make(management_enabled=False)
    resp = client.get(f"/api/mcp/servers/{sid}/agents/agent-1/access")
    assert resp.status_code == 404
