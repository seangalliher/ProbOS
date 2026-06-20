"""AD-1019e: department-locker authoring API for MCP tools.

Prefix ``/api/mcp/departments``. The HTTP authoring surface over the AD-1019b
:class:`~probos.integrations.mcp_bridge.department_grants.DepartmentToolGrantStore`
— stock / unstock a tool into a department's locker and list the active
department grants. Gated on ``config.mcp.management_enabled`` (404
``feature_disabled`` when off, matching api.py's flat unconditional include loop)
and honest-degrades to 503 when a store is absent.

A department grant uses the same composite ``ToolPermissionStore`` tool-id
convention as the per-agent grants (``mcp:{server_name}`` /
``mcp:{server_name}:{tool}``), so the AD-1019b three-source resolver folds it for
every agent in that department: an agent in the department resolves
``source="department"`` for the stocked tool (the loop that closes #964).

Boundary: this router only reads ``mcp_server_store`` (to resolve the server
``name`` for the composite tool-id) and wraps the existing async mutators on the
pre-existing ``department_tool_grant_store``. No store/schema/migration change.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from probos.integrations.mcp_bridge.access import (
    mcp_server_tool_id,
    mcp_tool_tool_id,
)
from probos.routers.deps import get_runtime
from probos.tools.protocol import ToolPermission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp/departments", tags=["mcp-departments"])


class DepartmentToolBody(BaseModel):
    """Body for ``POST /api/mcp/departments/{department}/tools`` (AD-1019e).

    ``server_id`` is the MCP server record id; ``tool`` (when present) scopes the
    locker entry to a single tool, else it stocks the whole server (all tools).
    ``enabled`` flips between a grant (``True``) and a restriction (``False``).
    """

    server_id: str
    tool: str | None = None
    enabled: bool


def _require_enabled(runtime: Any) -> None:
    """404 ``feature_disabled`` unless ``config.mcp.management_enabled`` is True.

    Replicated from :mod:`probos.routers.mcp_servers` so this router is
    self-contained (it does not import a private helper from a sibling router).
    """
    cfg = getattr(getattr(runtime, "config", None), "mcp", None)
    if cfg is None or not getattr(cfg, "management_enabled", False):
        raise HTTPException(status_code=404, detail="feature_disabled")


def _dept_store_or_503(runtime: Any) -> Any:
    """Honest-degrade 503 when the DepartmentToolGrantStore was not constructed."""
    store = getattr(runtime, "department_tool_grant_store", None)
    if store is None:
        raise HTTPException(
            status_code=503, detail="department_tool_grant_store_unavailable"
        )
    return store


def _server_store_or_503(runtime: Any) -> Any:
    """Honest-degrade 503 when the McpServerStore was not constructed."""
    store = getattr(runtime, "mcp_server_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="mcp_server_store_unavailable")
    return store


def _grant_public(grant: Any) -> dict[str, Any]:
    """Serialize a department ``ToolAccessGrant`` (``agent_id`` carries the dept)."""
    return {
        "grant_id": grant.id,
        "department": grant.agent_id,  # AD-1019b convention: agent_id == department
        "tool_id": grant.tool_id,
        "is_restriction": grant.is_restriction,
        "enabled": not grant.is_restriction,
    }


@router.get("/grants")
async def list_department_grants(
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """List the active department-locker grants (AD-1019e)."""
    _require_enabled(runtime)
    dept_store = _dept_store_or_503(runtime)
    grants = await dept_store.list_grants()
    return {"grants": [_grant_public(g) for g in grants]}


@router.post("/{department}/tools")
async def stock_department_tool(
    department: str,
    body: DepartmentToolBody,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Stock (or restrict) an MCP tool/server in a department's locker (AD-1019e)."""
    _require_enabled(runtime)
    server_store = _server_store_or_503(runtime)
    record = await server_store.get(body.server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    dept_store = _dept_store_or_503(runtime)
    tool_id = (
        mcp_tool_tool_id(record.name, body.tool)
        if body.tool
        else mcp_server_tool_id(record.name)
    )
    grant = await dept_store.issue_grant(
        department,
        tool_id,
        ToolPermission.WRITE if body.enabled else ToolPermission.NONE,
        is_restriction=not body.enabled,
        reason="department locker",
    )
    return _grant_public(grant)


@router.delete("/grants/{grant_id}")
async def unstock_department_tool(
    grant_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Revoke a department-locker grant by id (AD-1019e)."""
    _require_enabled(runtime)
    dept_store = _dept_store_or_503(runtime)
    revoked = await dept_store.revoke_grant(grant_id)
    return {"revoked": revoked}
