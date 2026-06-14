"""Tool asset catalog HTTP surface (AD-894).

The global tool registry is an asset catalog scoped to the *ship*, not to any
single crew agent, so it lives under its own ``/api/tools`` prefix rather than
under ``/api/crew``. The per-agent **certification** endpoints (grant / revoke,
``GET/POST/DELETE /api/crew/{agent_id}/tools``) are personnel-record facets and
live in ``routers/crew.py`` — they read/mutate the ``ToolPermissionStore``, the
audited grant trail. This split keeps the catalog query separate from the
governed privilege-edit surface.

Read-only catalog. No mutation here.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def list_tool_catalog(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Return the ship-wide tool asset catalog (AD-894).

    Honest-degrades to an empty catalog when the tool registry is unavailable
    rather than raising — the personnel console treats the catalog as an
    enrichment surface, not a hard dependency.
    """
    registry = getattr(runtime, "tool_registry", None)
    if registry is None:
        return {"tools": [], "count": 0}
    tools = [reg.to_dict() for reg in registry.list_tools()]
    return {"tools": tools, "count": len(tools)}


@router.get("/catalog")
async def list_capability_catalog(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-1001: the "Ship's Locker" — the global capabilities catalog.

    A ship-wide read-only view of every capability available across all four
    axes — **tools** (ToolRegistry), **skills** (CognitiveSkillCatalog), **mesh
    intents** (live IntentDescriptors), and **MCP servers** (config) — plus
    ``held_by`` for the per-agent axes (tools + skills): which crew hold each
    capability by explicit Captain grant. This is the global counterpart to the
    per-agent Service Configuration hub (AD-1000): "what can the ship do, and
    who holds what."

    ``held_by`` reflects **explicit grants only** (the audited, Captain-issued
    grants in ToolPermissionStore / SkillGrantStore) — role/department defaults
    are not enumerated here (they're derived per agent and would make this a
    heavy scan); the per-agent hub shows an agent's full effective set. Mesh
    intents are ship-served (reachable by all crew), so they carry no per-agent
    ``held_by``. Honest-degrades each axis to empty independently; never raises.
    """
    from probos.routers.agents import _mesh_intents, _tool_origin

    # --- held_by reverse maps (explicit grants only) -------------------------
    tool_held: dict[str, list[str]] = {}
    skill_held: dict[str, list[str]] = {}
    registry = getattr(runtime, "registry", None)
    perms = getattr(runtime, "tool_permission_store", None)
    grants = getattr(runtime, "skill_grant_store", None)
    if registry is not None:
        try:
            for agent in registry.all():
                aid = getattr(agent, "id", "")
                if not aid:
                    continue
                if perms is not None:
                    try:
                        for g in perms.get_active_grants_sync(aid):
                            if not getattr(g, "is_restriction", False):
                                tool_held.setdefault(g.tool_id, []).append(aid)
                    except Exception:
                        logger.debug("AD-1001: tool grants read failed for %s", aid, exc_info=True)
                if grants is not None:
                    try:
                        for g in grants.get_active_grants_sync(aid):
                            if not getattr(g, "is_restriction", False):
                                skill_held.setdefault(g.skill_name, []).append(aid)
                    except Exception:
                        logger.debug("AD-1001: skill grants read failed for %s", aid, exc_info=True)
        except Exception:
            logger.debug("AD-1001: registry walk failed", exc_info=True)

    # --- tools ---------------------------------------------------------------
    tools: list[dict[str, Any]] = []
    tool_registry = getattr(runtime, "tool_registry", None)
    if tool_registry is not None:
        try:
            for reg in tool_registry.list_tools():
                d = reg.to_dict()
                tools.append({
                    "id": d.get("tool_id", ""),
                    "name": d.get("name", d.get("tool_id", "")),
                    "description": d.get("description", ""),
                    "origin": _tool_origin(d.get("tool_type", ""), d.get("provider", "")),
                    "tool_type": d.get("tool_type", ""),
                    "domain": d.get("domain", "*"),
                    "department": d.get("department"),
                    "held_by": sorted(tool_held.get(d.get("tool_id", ""), [])),
                })
        except Exception:
            logger.debug("AD-1001: tool catalog failed", exc_info=True)

    # --- skills --------------------------------------------------------------
    skills: list[dict[str, Any]] = []
    catalog = getattr(runtime, "cognitive_skill_catalog", None)
    if catalog is not None:
        try:
            for e in catalog.list_entries():
                skills.append({
                    "id": e.name,
                    "name": e.name,
                    "description": e.description,
                    "department": e.department,
                    "min_rank": e.min_rank,
                    "intents": list(e.intents),
                    "held_by": sorted(skill_held.get(e.name, [])),
                })
        except Exception:
            logger.debug("AD-1001: skill catalog failed", exc_info=True)
    skills.sort(key=lambda s: s["id"])

    # --- mesh intents (ship-served) ------------------------------------------
    mesh_intents = _mesh_intents(runtime)

    # --- MCP servers ---------------------------------------------------------
    mcp_servers: list[dict[str, Any]] = []
    cfg = getattr(runtime, "config", None)
    mcp_cfg = getattr(cfg, "mcp", None) if cfg is not None else None
    if mcp_cfg is not None and getattr(mcp_cfg, "enabled", False):
        try:
            for srv in getattr(mcp_cfg, "servers", []) or []:
                mcp_servers.append({"url": getattr(srv, "url", ""), "origin": "mcp"})
        except Exception:
            logger.debug("AD-1001: mcp catalog failed", exc_info=True)

    return {
        "tools": tools,
        "skills": skills,
        "mesh_intents": mesh_intents,
        "mcp_servers": mcp_servers,
        "counts": {
            "tools": len(tools),
            "skills": len(skills),
            "mesh_intents": len(mesh_intents),
            "mcp_servers": len(mcp_servers),
        },
    }

