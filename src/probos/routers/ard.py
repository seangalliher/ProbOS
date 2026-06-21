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
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from probos.federation.ard import (
    MT_A2A_AGENT,
    MT_AI_CATALOG,
    MT_AI_REGISTRY,
    ArdClient,
    CatalogEntry,
    ard_resource_tool_id,
    ard_tool_tool_id,
    connect_candidate,
    discover_federated,
    entry_from_dict,
    facet_entries,
    get_cached_catalog,
    merge_catalog_entries,
    publish_catalog,
    search_entries,
)
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
from probos.tools.protocol import ToolPermission

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


class ArdAccessBody(BaseModel):
    """AD-1048: ``POST /ard/agents/{agent_id}/access`` body (camelCase boundary).

    ``enabled`` toggles opt-in: ``True`` issues a READ grant, ``False`` issues a
    NONE restriction (explicit deny). ``tool`` is optional — omit it to scope the
    grant to the whole resource (all tools).
    """

    model_config = ConfigDict(populate_by_name=True)

    catalog: str
    resource: str
    tool: str | None = None
    enabled: bool = True


class ArdAdoptBody(BaseModel):
    """AD-1049: ``POST /ard/adopt`` body — explicit, gated adopt of one entry.

    Carries the agent context (``agent_id`` + the ``catalog``/``resource`` it is
    being enabled for), the serving ``endpoint_host`` (for the publisher-domain
    trust check), and the discovered ``entry`` as a raw catalog dict (parsed +
    value-or-reference validated server-side via ``entry_from_dict``).
    """

    model_config = ConfigDict(populate_by_name=True)

    agent_id: str
    catalog: str
    resource: str
    endpoint_host: str = Field(default="", alias="endpointHost")
    entry: dict[str, Any] = Field(default_factory=dict)


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


# --------------------------------------------------------------------------- #
# AD-1046/1048 OPERATOR endpoints (crew-scope gated — they trigger outbound
# fetches / mutate grants — unlike the PUBLIC discovery-service queries above)
# --------------------------------------------------------------------------- #


def _ard_discovery_endpoints(runtime: Any) -> list[str]:
    """Read the operator-configured ARD discovery endpoint allowlist (honest-degrade)."""
    cfg = getattr(getattr(getattr(runtime, "config", None), "federation", None), "ard", None)
    endpoints = getattr(cfg, "discovery_endpoints", None)
    return list(endpoints) if isinstance(endpoints, list) else []


def _require_tool_permission_store(runtime: Any) -> Any:
    """Return ``runtime.tool_permission_store`` or raise 503 if unavailable."""
    perms = getattr(runtime, "tool_permission_store", None)
    if perms is None:
        raise HTTPException(status_code=503, detail="tool_permission_store_unavailable")
    return perms


@router.get("/ard/discovered", dependencies=[Depends(require_crew_scope)])
async def ard_discovered(runtime: Any = Depends(get_runtime)) -> JSONResponse:
    """AD-1046: fetch + parse the operator-configured ARD discovery endpoints.

    OPERATOR-facing (``require_crew_scope``) because it triggers OUTBOUND fetches.
    404 ``feature_disabled`` when ARD is off. Fetches ONLY
    ``config.federation.ard.discovery_endpoints`` (the operator allowlist) via the
    DD-1 SSRF-guarded ``ArdClient`` (``follow_redirects=False``, bounded timeout +
    size cap); it never dereferences an entry's ``url``. Honest-degrade: any
    top-level failure returns an empty ``discovered`` list (never a 500);
    per-endpoint failures are isolated into each row's ``error``.
    """
    _require_ard_enabled(runtime)

    try:
        endpoints = _ard_discovery_endpoints(runtime)
        results = await ArdClient().discover(endpoints)
        discovered = [
            {
                "source": d.source_endpoint,
                "error": d.error,
                "catalog": d.catalog.to_dict() if d.catalog else None,
            }
            for d in results
        ]
    except Exception:
        logger.warning("AD-1046: ard discovered failed; serving empty list", exc_info=True)
        discovered = []

    body = {
        "specVersion": "1.0",
        "conformance": "registry",
        "discovered": discovered,
    }
    return JSONResponse(content=body, media_type=MT_AI_REGISTRY)


@router.post("/ard/agents/{agent_id}/access", dependencies=[Depends(require_crew_scope)])
async def ard_set_agent_access(
    agent_id: str,
    body: ArdAccessBody = Body(...),
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-1048: enable/disable an ARD resource (or one tool) for an agent.

    OPERATOR-facing (``require_crew_scope``) — it mutates grants. 404 when ARD is
    off; 503 when the tool-permission store is unavailable. DD-3 opt-in:
    ``enabled`` issues a READ grant; ``enabled=False`` issues a NONE restriction
    (explicit deny). Reuses the audited ``ToolPermissionStore`` with the
    ``ard:{catalog}:{resource}[:{tool}]`` composite id.
    """
    _require_ard_enabled(runtime)
    perms = _require_tool_permission_store(runtime)

    tool_id = (
        ard_tool_tool_id(body.catalog, body.resource, body.tool)
        if body.tool
        else ard_resource_tool_id(body.catalog, body.resource)
    )
    grant = await perms.issue_grant(
        agent_id,
        tool_id,
        ToolPermission.READ if body.enabled else ToolPermission.NONE,
        is_restriction=not body.enabled,
        reason="ard enablement",
    )
    return {
        "grant_id": grant.id,
        "agent_id": agent_id,
        "tool_id": tool_id,
        "enabled": body.enabled,
        "is_restriction": not body.enabled,
    }


@router.get("/ard/agents/{agent_id}/access", dependencies=[Depends(require_crew_scope)])
async def ard_list_agent_access(
    agent_id: str, runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    """AD-1048: list an agent's active ARD grants (``ard:`` composite ids only).

    OPERATOR-facing (``require_crew_scope``). 404 when ARD off; 503 when the store
    is unavailable. Zero-I/O cache read; never lists non-ARD grants.
    """
    _require_ard_enabled(runtime)
    perms = _require_tool_permission_store(runtime)

    grants = [
        {"tool_id": g.tool_id, "is_restriction": g.is_restriction}
        for g in perms.get_active_grants_sync(agent_id)
        if g.tool_id.startswith("ard:")
    ]
    return {"agent_id": agent_id, "grants": grants}


@router.delete("/ard/agents/{agent_id}/access", dependencies=[Depends(require_crew_scope)])
async def ard_clear_agent_access(
    agent_id: str, runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    """AD-1048: revoke ALL active ARD grants for an agent (operator clear).

    OPERATOR-facing (``require_crew_scope``). 404 when ARD off; 503 when the store
    is unavailable. Soft-revokes only ``ard:`` grants; non-ARD grants are
    untouched. Returns the count revoked.
    """
    _require_ard_enabled(runtime)
    perms = _require_tool_permission_store(runtime)

    ard_grants = [
        g
        for g in perms.get_active_grants_sync(agent_id)
        if g.tool_id.startswith("ard:")
    ]
    revoked = 0
    for g in ard_grants:
        if await perms.revoke_grant(g.id):
            revoked += 1
    return {"agent_id": agent_id, "revoked": revoked}


# --------------------------------------------------------------------------- #
# AD-1049/1050/1051 OPERATOR endpoints (crew-scope gated — they trigger outbound
# fetches / POSTs / mutate trust + the MCP bridge).
# --------------------------------------------------------------------------- #


@router.get("/ard/federated", dependencies=[Depends(require_crew_scope)])
async def ard_federated(runtime: Any = Depends(get_runtime)) -> JSONResponse:
    """AD-1050: fan out ARD discovery to federated referral peers (mode-gated).

    OPERATOR-facing (``require_crew_scope``) — it triggers OUTBOUND fetches. 404
    ``feature_disabled`` when ARD is off. ``federation.ard.federation_mode`` gates the
    fan-out: ``none`` → empty (NO peer fetch); ``referrals``/``auto`` → fetch the
    bounded ``a2a.outbound_peers`` via the SSRF-guarded client, then MERGE all peer
    catalogs (dedupe by URN). Honest-degrade: any failure returns empty results.
    """
    _require_ard_enabled(runtime)

    try:
        discovered = await discover_federated(runtime)
        entries = merge_catalog_entries(discovered)
        results = [entry.to_dict() for entry in entries]
    except Exception:
        logger.warning("AD-1050: ard federated failed; serving empty results", exc_info=True)
        results = []

    body = {
        "specVersion": "1.0",
        "conformance": "registry",
        "results": results,
        "total": len(results),
    }
    return JSONResponse(content=body, media_type=MT_AI_REGISTRY)


@router.post("/ard/adopt", dependencies=[Depends(require_crew_scope)])
async def ard_adopt(
    body: ArdAdoptBody = Body(...), runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    """AD-1049: explicit, gated adopt-and-connect of one discovered ARD entry.

    OPERATOR-facing (``require_crew_scope``) — it mutates trust + the MCP bridge. 404
    when ARD is off; 503 when the tool-permission store is unavailable; 422
    ``invalid_entry`` when ``entry`` fails value-or-reference parsing. Delegates the
    strict permission → trust → connect ordering to ``connect_candidate`` and returns
    its ``ConnectResult`` as a dict.
    """
    _require_ard_enabled(runtime)
    _require_tool_permission_store(runtime)

    entry = entry_from_dict(body.entry)
    if entry is None:
        raise HTTPException(status_code=422, detail="invalid_entry")

    result = await connect_candidate(
        runtime,
        agent_id=body.agent_id,
        catalog=body.catalog,
        resource=body.resource,
        entry=entry,
        endpoint_host=body.endpoint_host,
    )
    return asdict(result)


@router.post("/ard/publish", dependencies=[Depends(require_crew_scope)])
async def ard_publish(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-1051: publish the ship's secret-free catalog to the configured registry.

    OPERATOR-facing (``require_crew_scope``) — it triggers an OUTBOUND POST. 404 when
    ARD is off. An empty ``federation.ard.registry_url`` is a no-op (``no_registry_url``)
    with NO HTTP call. Delegates to ``publish_catalog`` (DD-7 secret-free body,
    SSRF-guarded) and returns its ``PublishResult`` as a dict.
    """
    _require_ard_enabled(runtime)
    result = await publish_catalog(runtime)
    return asdict(result)
