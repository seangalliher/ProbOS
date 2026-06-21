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

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from probos.federation.ard import (
    MT_A2A_AGENT,
    MT_AI_CATALOG,
    MT_AI_REGISTRY,
    CatalogEntry,
    facet_entries,
    get_cached_catalog,
    search_entries,
)
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ard"])

# AD-1044 R-3 bound: the query endpoints are PUBLIC (no auth dep, mirrors
# AD-1042 + the A2A card), so a requested page size is HARD-clamped to this cap
# (honest-degrade — a too-large value is clamped, never a 422).
_MAX_PAGE_SIZE = 50


# --------------------------------------------------------------------------- #
# AD-1044 request models (camelCase boundary; populate_by_name so tests + JSON
# clients can use either the snake_case field name or the camelCase alias)
# --------------------------------------------------------------------------- #


class ArdQueryFilter(BaseModel):
    """ARD query filter (spec §7.1): exact media-``type`` + ``tags`` AND-match."""

    model_config = ConfigDict(populate_by_name=True)

    type: str | None = None
    tags: list[str] = Field(default_factory=list)


class ArdQuery(BaseModel):
    """ARD query body: free ``text`` plus an optional ``filter``."""

    model_config = ConfigDict(populate_by_name=True)

    text: str = ""
    filter: ArdQueryFilter | None = None


class ArdSearchRequest(BaseModel):
    """``POST /ard/search`` body: a query plus bounded offset pagination."""

    model_config = ConfigDict(populate_by_name=True)

    query: ArdQuery = Field(default_factory=ArdQuery)
    page_size: int = Field(default=20, alias="pageSize")
    page_token: str = Field(default="", alias="pageToken")


class ArdExploreRequest(BaseModel):
    """``POST /ard/explore`` body: optional query/filter plus bounded pagination."""

    model_config = ConfigDict(populate_by_name=True)

    query: ArdQuery = Field(default_factory=ArdQuery)
    page_size: int = Field(default=20, alias="pageSize")
    page_token: str = Field(default="", alias="pageToken")


# --------------------------------------------------------------------------- #
# Gate + pagination helpers (shared by all four endpoints)
# --------------------------------------------------------------------------- #


def _require_ard_enabled(runtime: Any) -> None:
    """DD-2 gate: raise 404 ``feature_disabled`` unless ``federation.ard.enabled``."""
    cfg = getattr(getattr(getattr(runtime, "config", None), "federation", None), "ard", None)
    if cfg is None or not getattr(cfg, "enabled", False):
        raise HTTPException(status_code=404, detail="feature_disabled")


def _clamp_page_size(page_size: int) -> int:
    """Honest-degrade clamp of a requested page size to ``[1, _MAX_PAGE_SIZE]``."""
    if page_size < 1:
        return 1
    return min(page_size, _MAX_PAGE_SIZE)


def _parse_offset(page_token: str) -> int:
    """Honest-degrade parse of an opaque page token into a non-negative offset."""
    try:
        offset = int(page_token)
    except (TypeError, ValueError):
        return 0
    return offset if offset > 0 else 0


def _paginate(
    entries: list[CatalogEntry], page_size: int, page_token: str
) -> tuple[list[CatalogEntry], str]:
    """Bounded offset pagination → ``(page, nextPageToken)`` (``""`` when exhausted)."""
    size = _clamp_page_size(page_size)
    offset = _parse_offset(page_token)
    page = entries[offset : offset + size]
    next_offset = offset + size
    next_token = str(next_offset) if next_offset < len(entries) else ""
    return page, next_token


@router.get("/.well-known/ai-catalog.json")
async def serve_ai_catalog(runtime: Any = Depends(get_runtime)) -> JSONResponse:
    """Serve the ship's ARD capability catalog (``ai-catalog+json``).

    404 ``feature_disabled`` unless ``config.federation.ard.enabled`` is True.
    Public (no auth) when enabled. Routed through ``get_cached_catalog`` (DD-4
    short-TTL projection cache, ``episodic_k=0`` — behavior-preserving vs. the
    AD-1042 direct projection). Honest-degrade: any projection failure logs and
    returns an empty-but-well-formed envelope rather than a 500.
    """
    _require_ard_enabled(runtime)

    try:
        catalog = await get_cached_catalog(runtime)
        body = catalog.to_dict()
    except Exception:
        logger.warning("AD-1042: catalog projection failed; serving empty envelope", exc_info=True)
        body = {"specVersion": "1.0", "entries": []}

    return JSONResponse(content=body, media_type=MT_AI_CATALOG)


@router.post("/ard/search")
async def ard_search(
    req: ArdSearchRequest, runtime: Any = Depends(get_runtime)
) -> JSONResponse:
    """AD-1044: ARD discovery-service query — keyword-rank the cached projection.

    PUBLIC + BOUNDED (R-3): 404 ``feature_disabled`` when off; otherwise reads
    the short-TTL cached projection (zero-I/O, ``episodic_k=0``) and ranks it
    in-memory with ``search_entries`` (relevance only, never trust). ``pageSize``
    is hard-clamped to ``_MAX_PAGE_SIZE`` (honest-degrade, never 422). ``results``
    are ``CatalogEntry.to_dict()`` (value-or-reference + camelCase preserved).
    Served as ``ai-registry+json`` (registry conformance mode).
    """
    _require_ard_enabled(runtime)

    flt = req.query.filter
    try:
        catalog = await get_cached_catalog(runtime)
        ranked = search_entries(
            catalog.entries,
            req.query.text,
            type=flt.type if flt else None,
            tags=flt.tags if flt else None,
        )
    except Exception:
        logger.warning("AD-1044: ard search failed; serving empty results", exc_info=True)
        ranked = []

    page, next_token = _paginate(ranked, req.page_size, req.page_token)
    body = {
        "specVersion": "1.0",
        "conformance": "registry",
        "results": [entry.to_dict() for entry in page],
        "total": len(ranked),
        "nextPageToken": next_token,
    }
    return JSONResponse(content=body, media_type=MT_AI_REGISTRY)


@router.post("/ard/explore")
async def ard_explore(
    req: ArdExploreRequest, runtime: Any = Depends(get_runtime)
) -> JSONResponse:
    """AD-1045: ARD browse — catalog facet counts plus an optional filtered page.

    Returns ``facets`` (``types``/``tags``/``axes`` counts over the whole catalog)
    so a client can navigate the surface, plus a ``results`` page of the entries
    matching the optional ``query`` (empty text + filter → a filtered browse).
    Same PUBLIC + BOUNDED posture as ``/ard/search``.
    """
    _require_ard_enabled(runtime)

    flt = req.query.filter
    try:
        catalog = await get_cached_catalog(runtime)
        facets = facet_entries(catalog.entries)
        selected = search_entries(
            catalog.entries,
            req.query.text,
            type=flt.type if flt else None,
            tags=flt.tags if flt else None,
        )
    except Exception:
        logger.warning("AD-1045: ard explore failed; serving empty facets", exc_info=True)
        facets = {"types": {}, "tags": {}, "axes": {}}
        selected = []

    page, next_token = _paginate(selected, req.page_size, req.page_token)
    body = {
        "specVersion": "1.0",
        "conformance": "registry",
        "facets": facets,
        "results": [entry.to_dict() for entry in page],
        "total": len(selected),
        "nextPageToken": next_token,
    }
    return JSONResponse(content=body, media_type=MT_AI_REGISTRY)


@router.get("/ard/agents")
async def ard_agents(
    runtime: Any = Depends(get_runtime),
    text: str = Query(default=""),
    page_size: int = Query(default=20, alias="pageSize"),
    page_token: str = Query(default="", alias="pageToken"),
) -> JSONResponse:
    """AD-1045: list the ship's agent-card entries (``MT_A2A_AGENT`` only).

    A convenience view over ``/ard/search`` pinned to the agent media type:
    optional ``text`` ranks within the agent axis. Same PUBLIC + BOUNDED posture.
    """
    _require_ard_enabled(runtime)

    try:
        catalog = await get_cached_catalog(runtime)
        ranked = search_entries(catalog.entries, text, type=MT_A2A_AGENT)
    except Exception:
        logger.warning("AD-1045: ard agents failed; serving empty results", exc_info=True)
        ranked = []

    page, next_token = _paginate(ranked, page_size, page_token)
    body = {
        "specVersion": "1.0",
        "conformance": "registry",
        "results": [entry.to_dict() for entry in page],
        "total": len(ranked),
        "nextPageToken": next_token,
    }
    return JSONResponse(content=body, media_type=MT_AI_REGISTRY)
