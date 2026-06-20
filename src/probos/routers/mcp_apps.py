"""AD-1024: read-only MCP-app gallery API.

Prefix ``/api/mcp-apps``. Gated on ``config.mcp_app_host.enabled`` (AD-597,
default OFF): every request 404s with ``feature_disabled`` when off (mirroring
``routers/mcp_servers._require_enabled``), so the router can be included
unconditionally (matching api.py's flat include loop) without changing any
existing path or behavior — byte-identical when off.

The gallery source is the AD-597 ``runtime.mcp_app_registry`` (``MCPAppRegistry``,
wired by ``_wire_mcp_app_host`` only when the feature is enabled). It surfaces the
boot-discovered internal + external app tools from ``list_tools()``; entries
without a ``ui.resourceUri`` (a tool with no launchable UI) are filtered out so
the gallery only lists apps the HXI can actually open in an ``McpAppFrame``.

Read-only: no app is invoked, registered, or mutated here. Runtime external-app
re-discovery + the AD-1018 connection UX is the deferred AD-1024a slice.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp-apps", tags=["mcp-apps"])


class McpAppView(BaseModel):
    """Public, launchable view of a registered MCP app (gallery row).

    ``resource_uri`` is the ``ui://`` resource the HXI feeds to ``McpAppFrame``
    (served by ``GET /api/mcp/resource?uri=``). ``external`` distinguishes a
    boot-discovered external-server app from an internal one; ``server_id`` is the
    originating external server id ("" for internal apps).
    """

    name: str
    description: str
    resource_uri: str
    external: bool
    server_id: str


class McpAppsResponse(BaseModel):
    """Response envelope for ``GET /api/mcp-apps``."""

    apps: list[McpAppView] = Field(default_factory=list)


def _require_enabled(runtime: Any) -> None:
    """404 ``feature_disabled`` unless ``config.mcp_app_host.enabled`` is True."""
    cfg = getattr(getattr(runtime, "config", None), "mcp_app_host", None)
    if cfg is None or not getattr(cfg, "enabled", False):
        raise HTTPException(status_code=404, detail="feature_disabled")


@router.get("", response_model=McpAppsResponse)
async def list_mcp_apps(
    runtime: Any = Depends(get_runtime),
) -> McpAppsResponse:
    """List registered MCP apps that have a launchable ``ui://`` resource.

    Gated on ``config.mcp_app_host.enabled`` (404 when off). Honest-degrades to a
    503 when the registry is absent (enabled but not yet wired). Entries without a
    ``ui.resourceUri`` are skipped (not launchable in an ``McpAppFrame``).
    """
    _require_enabled(runtime)

    registry = getattr(runtime, "mcp_app_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="mcp_app_registry not available")

    apps: list[McpAppView] = []
    for entry in registry.list_tools():
        meta = entry.get("_meta", {}) or {}
        ui = meta.get("ui", {}) or {}
        resource_uri = ui.get("resourceUri", "") or ""
        if not resource_uri:
            # A tool with no launchable UI — not a gallery app.
            continue
        probos_meta = meta.get("probos", {}) or {}
        apps.append(
            McpAppView(
                name=entry.get("name", "") or "",
                description=entry.get("description", "") or "",
                resource_uri=resource_uri,
                external=bool(probos_meta.get("external", False)),
                server_id=probos_meta.get("server_id", "") or "",
            )
        )
    return McpAppsResponse(apps=apps)
