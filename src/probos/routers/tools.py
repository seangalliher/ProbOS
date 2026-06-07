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
