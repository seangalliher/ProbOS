"""AD-1024: MCP-app gallery API + the ``mcp-app`` workstation-type registration.

Real objects throughout (BF-287): a real ``MCPAppRegistry`` (AD-597), a real
``SystemConfig``, and a ``SimpleNamespace`` runtime — NO MagicMock at the
registry boundary. Covers the read-only ``GET /api/mcp-apps`` handler
(``list_mcp_apps``): the 404 feature-disabled gate, the 200 projection of an
internal AND an external app (with the empty-``resourceUri`` filter), and the 503
honest-degrade when the registry is absent; plus the ``_wire_workstation_types``
finalize step registering the native ``mcp-app`` type only when the MCP App Host
is enabled (mirrors the AD-1022 real-config fixture).
"""

from __future__ import annotations

import types

import pytest
from fastapi import HTTPException

from probos.config import MCPAppHostConfig, SystemConfig, WorkstationsConfig
from probos.mcp_apps.registry import MCPAppRegistry
from probos.routers.mcp_apps import McpAppsResponse, list_mcp_apps
from probos.startup.finalize import _wire_workstation_types

_VALID_CSP = "default-src 'self'"


async def _ok_handler(args):
    return {"isError": False, "content": [{"type": "text", "text": "ok"}]}


def _make_registry() -> MCPAppRegistry:
    return MCPAppRegistry(
        internal_default_csp=_VALID_CSP,
        external_default_csp=_VALID_CSP,
    )


def _registry_with_apps() -> MCPAppRegistry:
    """A real registry: one internal app, one external app, one UI-less tool."""
    reg = _make_registry()
    # Internal app — has a launchable ui:// resource (external=False, server_id="").
    reg.register_app_tool(
        name="chess",
        description="Play chess",
        input_schema={"type": "object"},
        ui_resource_uri="ui://probos/games/chess/index.html",
        handler=_ok_handler,
    )
    # External app — discovered from an external server (external=True, server_id set).
    reg.register_external_app(
        server_id="srv-weather",
        tool_dict={
            "name": "weather",
            "description": "Show weather",
            "inputSchema": {"type": "object"},
            "_meta": {"ui": {"resourceUri": "ui://external/srv-weather/index.html"}},
        },
        csp=_VALID_CSP,
        mcp_client=types.SimpleNamespace(),
    )
    # UI-less tool — no resourceUri; must be FILTERED out of the gallery.
    reg.register_app_tool(
        name="headless",
        description="No UI",
        input_schema={},
        ui_resource_uri="",
        handler=_ok_handler,
    )
    return reg


def _runtime(*, enabled: bool, registry: object | None) -> object:
    """Real-attribute fake runtime (config is a real SystemConfig, not a mock)."""
    config = SystemConfig()
    config.mcp_app_host = MCPAppHostConfig(enabled=enabled)
    ns = types.SimpleNamespace(config=config)
    if registry is not None:
        ns.mcp_app_registry = registry
    return ns


# ---------------------------------------------------------------------------
# GET /api/mcp-apps handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_mcp_apps_404_when_disabled():
    # Disabled (default) -> feature_disabled 404, even with a registry present.
    runtime = _runtime(enabled=False, registry=_registry_with_apps())
    with pytest.raises(HTTPException) as exc:
        await list_mcp_apps(runtime=runtime)
    assert exc.value.status_code == 404
    assert exc.value.detail == "feature_disabled"


@pytest.mark.asyncio
async def test_list_mcp_apps_lists_internal_and_external_and_filters_uiless():
    runtime = _runtime(enabled=True, registry=_registry_with_apps())
    resp = await list_mcp_apps(runtime=runtime)
    assert isinstance(resp, McpAppsResponse)
    by_name = {a.name: a for a in resp.apps}
    # The UI-less tool is filtered out; only the two launchable apps remain.
    assert set(by_name) == {"chess", "weather"}
    # Internal app projection.
    chess = by_name["chess"]
    assert chess.resource_uri == "ui://probos/games/chess/index.html"
    assert chess.external is False
    assert chess.server_id == ""
    # External app projection.
    weather = by_name["weather"]
    assert weather.resource_uri == "ui://external/srv-weather/index.html"
    assert weather.external is True
    assert weather.server_id == "srv-weather"


@pytest.mark.asyncio
async def test_list_mcp_apps_503_when_registry_absent():
    # Enabled but the registry was never wired (e.g. mid-startup) -> 503.
    runtime = _runtime(enabled=True, registry=None)
    with pytest.raises(HTTPException) as exc:
        await list_mcp_apps(runtime=runtime)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_list_mcp_apps_empty_registry_returns_empty_list():
    runtime = _runtime(enabled=True, registry=_make_registry())
    resp = await list_mcp_apps(runtime=runtime)
    assert resp.apps == []


# ---------------------------------------------------------------------------
# _wire_workstation_types: mcp-app registration (gated on mcp_app_host.enabled)
# ---------------------------------------------------------------------------


def test_wire_registers_mcp_app_when_host_enabled():
    runtime = types.SimpleNamespace()
    config = SystemConfig()
    config.mcp_app_host = MCPAppHostConfig(enabled=True)
    # workstations stays disabled (default) — mcp-app registers anyway (before the
    # early-return); the function still returns False (no OSS baselines).
    result = _wire_workstation_types(runtime=runtime, config=config)
    assert result is False
    reg = runtime.workstation_type_registry
    mcp_app = reg.resolve("mcp-app", commercial_loaded=False)
    assert mcp_app is not None
    assert mcp_app.tier == "oss"
    assert mcp_app.render.kind == "native"
    assert mcp_app.render.component_key == "mcp-app"


def test_wire_does_not_register_mcp_app_when_host_disabled():
    runtime = types.SimpleNamespace()
    config = SystemConfig()
    config.mcp_app_host = MCPAppHostConfig(enabled=False)
    _wire_workstation_types(runtime=runtime, config=config)
    reg = runtime.workstation_type_registry
    assert reg.resolve("mcp-app", commercial_loaded=False) is None


def test_wire_registers_mcp_app_alongside_oss_baselines_when_both_enabled():
    runtime = types.SimpleNamespace()
    config = SystemConfig()
    config.mcp_app_host = MCPAppHostConfig(enabled=True)
    config.workstations = WorkstationsConfig(enabled=True)
    result = _wire_workstation_types(runtime=runtime, config=config)
    assert result is True
    reg = runtime.workstation_type_registry
    # mcp-app + the three OSS baselines, all present.
    assert reg.all_type_ids() == ("browser", "chat", "mcp-app", "monaco")
