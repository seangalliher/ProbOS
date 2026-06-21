"""AD-1042: serve the ARD catalog at ``GET /.well-known/ai-catalog.json``.

Epic #989 Foundation 3/12. This is the PUBLIC discovery endpoint a generic ARD
client fetches to learn what the ship can do. It projects the live capability
surface (AD-1041) — with representative queries (AD-1043) — into the AD-1040
``ai-catalog+json`` envelope.

Security / availability decisions:
  * **DD-2 default-OFF.** Gated on ``config.federation.ard.enabled`` (default
    False) → 404 ``feature_disabled`` when off (mirrors
    ``routers/mcp_servers._require_enabled``), so the router is safe to include
    unconditionally without changing any existing path.
  * **Public when on.** When enabled the endpoint is UNAUTHENTICATED (mirrors
    the A2A ``/.well-known/agent.json`` card) — discovery is meant to be open.
  * **Zero-I/O on the public path.** Because the endpoint is unauthenticated,
    it mines representative queries with ``episodic_k=0`` (workflow-cache only,
    no ChromaDB ``await``) — an unauthenticated-resource-consumption guard. The
    AD-1043 episodic path stays available for future authenticated / cached use.
  * **DD-7 secrets-never-projected.** The projector reads only non-secret fields
    (id/name/type/url for MCP); no credential or value can reach this response.

v1 limitation: the catalog is served at the STANDARD path
``/.well-known/ai-catalog.json`` only. A configurable ``well_known_path`` (the
config field exists) is a later slice — the decorator path is static here.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from probos.federation.ard import MT_AI_CATALOG
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ard"])


@router.get("/.well-known/ai-catalog.json")
async def serve_ai_catalog(runtime: Any = Depends(get_runtime)) -> JSONResponse:
    """Serve the ship's ARD capability catalog (``ai-catalog+json``).

    404 ``feature_disabled`` unless ``config.federation.ard.enabled`` is True.
    Public (no auth) when enabled. Honest-degrade: any projection failure logs
    and returns an empty-but-well-formed envelope rather than a 500.
    """
    cfg = getattr(getattr(getattr(runtime, "config", None), "federation", None), "ard", None)
    if cfg is None or not getattr(cfg, "enabled", False):
        raise HTTPException(status_code=404, detail="feature_disabled")

    from probos.federation.ard import mine_representative_queries, project_catalog

    try:
        # episodic_k=0: workflow-cache-only mining — zero I/O on this public,
        # unauthenticated endpoint (resource-consumption guard).
        repr_queries = await mine_representative_queries(runtime, episodic_k=0)
        catalog = await project_catalog(runtime, repr_queries=repr_queries)
        body = catalog.to_dict()
    except Exception:
        logger.warning("AD-1042: catalog projection failed; serving empty envelope", exc_info=True)
        body = {"specVersion": "1.0", "entries": []}

    return JSONResponse(content=body, media_type=MT_AI_CATALOG)
