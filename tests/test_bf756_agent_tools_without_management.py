"""BF-756: ``agent_tools_enabled`` alone was documented as supported and was inert.

``config.py`` promised the flag was "Independent of management_enabled". It was
not. ``startup/finalize.py`` constructed ``McpServerStore``,
``DepartmentToolGrantStore`` and ``McpToolRiskStore`` only inside
``if config.mcp.management_enabled:`` and set all three to ``None`` in the
``else``. The workbench was then built with ``server_store=None``, and
``MCPWorkbench`` returns ``[]`` on exactly that condition -- so an operator who
set ``agent_tools_enabled`` got a workbench, a registered ``find_mcp_tool``, an
``AD-1019c: MCP workbench wired`` log line, and zero discoverable tools.

The fix widens store construction to either flag. The three stores are the READ
side (the workbench resolves every discovery and authorization decision against
them); the CRUD API is the write side and gates itself. These tests assert the
behaviour an operator and an agent can observe -- what is discoverable, what a
route returns -- not which branch ran.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.config import MCPConfig, MCPServerConfig, SystemConfig
from probos.runtime import ProbOSRuntime

_SERVER_NAME = "weather"
_SERVER_URL = "https://mcp.example.com/mcp"


def _config(*, management: bool, agent_tools: bool) -> SystemConfig:
    """Default SystemConfig + one declared MCP server, so seeding has real work.

    An unseeded store discovers exactly as much as no store, so a config server
    is what makes "the stores exist" and "an agent can find something" different
    assertions.
    """
    return SystemConfig(
        mcp=MCPConfig(
            management_enabled=management,
            agent_tools_enabled=agent_tools,
            servers=[
                MCPServerConfig(type="http", url=_SERVER_URL, name=_SERVER_NAME)
            ],
        )
    )


def _client(runtime: Any) -> TestClient:
    """Both MCP mutation routers mounted over a real, booted runtime."""
    from probos.routers.mcp_departments import router as departments_router
    from probos.routers.mcp_servers import router as servers_router

    app = FastAPI()
    app.include_router(servers_router)
    app.include_router(departments_router)
    app.state.runtime = runtime
    return TestClient(app)


def _mutation_routes(server_id: str) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Every write-side MCP route, with bodies that PASS schema validation.

    Body validation runs before the handler, so an invalid body 422s without
    ever reaching the ``management_enabled`` gate -- a 404-safety test built on
    malformed bodies would prove nothing. ``test_management_alone_is_unchanged``
    replays this same table with the gate open to prove each entry really
    reaches a handler.
    """
    return [
        ("get", "/api/mcp/servers", None),
        (
            "post",
            "/api/mcp/servers",
            {"name": "probe", "type": "http", "url": "https://probe.example.com/mcp"},
        ),
        ("get", f"/api/mcp/servers/{server_id}", None),
        ("put", f"/api/mcp/servers/{server_id}", {"url": "https://probe.example.com/2"}),
        ("post", f"/api/mcp/servers/{server_id}/enable", None),
        ("post", f"/api/mcp/servers/{server_id}/disable", None),
        ("post", f"/api/mcp/servers/{server_id}/agents/agent-1", {"enabled": True}),
        ("delete", f"/api/mcp/servers/{server_id}/agents/agent-1", None),
        ("put", f"/api/mcp/servers/{server_id}/tools/probe/risk", {"risk": "confirm"}),
        ("delete", f"/api/mcp/servers/{server_id}/tools/probe/risk", None),
        ("get", "/api/mcp/departments/grants", None),
        (
            "post",
            "/api/mcp/departments/science/tools",
            {"server_id": server_id, "enabled": True},
        ),
        ("delete", "/api/mcp/departments/grants/grant-1", None),
        # Last: it removes the row the paths above address.
        ("delete", f"/api/mcp/servers/{server_id}", None),
    ]


@pytest.mark.asyncio
async def test_agent_tools_alone_makes_a_config_server_discoverable(tmp_path):
    """The exact combination the issue names: tools on, management off."""
    rt = ProbOSRuntime(
        data_dir=tmp_path / "data",
        config=_config(management=False, agent_tools=True),
    )
    await rt.start()
    try:
        assert rt.config.mcp.management_enabled is False
        assert rt.config.mcp.agent_tools_enabled is True

        # The read-side stores exist.
        assert rt.mcp_server_store is not None
        assert rt.department_tool_grant_store is not None
        assert rt.mcp_tool_risk_store is not None

        # The workbench holds a real store, not None.
        assert rt.mcp_workbench is not None
        assert rt.mcp_workbench.enabled_server_names == [_SERVER_NAME]

        # And the agent-visible surface names it: find_mcp_tool's description is
        # what an agent actually reads when deciding whether MCP is worth a hop.
        assert rt.tool_registry is not None
        find_tool = rt.tool_registry.get_tool("find_mcp_tool")
        assert find_tool is not None
        assert _SERVER_NAME in find_tool.description
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_agent_tools_alone_does_not_open_the_mutation_api(tmp_path):
    """The load-bearing one: constructing the stores must not expose CRUD.

    Widening construction is only safe because every handler in both routers
    gates itself on ``management_enabled`` before it reaches a store. Proven
    here rather than asserted: the stores are present and every mutation route
    still 404s ``feature_disabled``, and the seeded row is untouched afterwards.
    """
    rt = ProbOSRuntime(
        data_dir=tmp_path / "data",
        config=_config(management=False, agent_tools=True),
    )
    await rt.start()
    try:
        assert rt.mcp_server_store is not None  # premise: a store IS reachable
        seeded = rt.mcp_server_store.list_sync()
        assert [r.name for r in seeded] == [_SERVER_NAME]
        server_id = seeded[0].id

        client = _client(rt)
        for method, path, body in _mutation_routes(server_id):
            resp = getattr(client, method)(path, **({"json": body} if body else {}))
            assert resp.status_code == 404, f"{method.upper()} {path} -> {resp.text}"
            assert resp.json()["detail"] == "feature_disabled", f"{method} {path}"

        # Nothing the API could have mutated was mutated.
        after = rt.mcp_server_store.list_sync()
        assert [(r.name, r.url, r.enabled) for r in after] == [
            (_SERVER_NAME, _SERVER_URL, True)
        ]
        assert await rt.department_tool_grant_store.list_grants() == []
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_both_flags_off_constructs_nothing(tmp_path):
    """Default-OFF boot is unchanged: no stores, no workbench, no DB files."""
    data_dir = tmp_path / "data"
    rt = ProbOSRuntime(data_dir=data_dir, config=_config(management=False, agent_tools=False))
    await rt.start()
    try:
        assert rt.mcp_server_store is None
        assert rt.department_tool_grant_store is None
        assert rt.mcp_tool_risk_store is None
        assert rt.mcp_workbench is None
        assert rt.mcp_workbench_reaper is None
        # Constructing a store is what creates its file, so absence is the
        # observable form of "constructed nothing".
        for name in (
            "mcp_servers.db",
            "department_tool_grants.db",
            "mcp_tool_risk.db",
        ):
            assert not (rt.data_dir / name).exists(), name
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_management_alone_is_unchanged(tmp_path):
    """Management on, tools off: stores + CRUD as before, still no workbench."""
    rt = ProbOSRuntime(
        data_dir=tmp_path / "data",
        config=_config(management=True, agent_tools=False),
    )
    await rt.start()
    try:
        assert rt.mcp_server_store is not None
        assert rt.department_tool_grant_store is not None
        assert rt.mcp_tool_risk_store is not None
        # agent_tools_enabled is still its own gate.
        assert rt.mcp_workbench is None
        assert rt.mcp_workbench_reaper is None
        assert rt.tool_registry is not None
        assert rt.tool_registry.get("find_mcp_tool") is None

        # The CRUD API is open, and reads the seeded row.
        client = _client(rt)
        resp = client.get("/api/mcp/servers")
        assert resp.status_code == 200, resp.text
        servers = resp.json()["servers"]
        assert [s["name"] for s in servers] == [_SERVER_NAME]

        # Premise check for the safety test above: with the gate OPEN, not one
        # of those routes answers "feature_disabled". So every 404 it asserts
        # came from the gate, not from a mistyped path or a rejected body.
        for method, path, body in _mutation_routes(servers[0]["id"]):
            probe = getattr(client, method)(path, **({"json": body} if body else {}))
            detail = probe.json().get("detail") if probe.content else None
            assert detail != "feature_disabled", f"{method.upper()} {path}"
            assert probe.status_code != 422, f"{method.upper()} {path} -> {probe.text}"
    finally:
        await rt.stop()
