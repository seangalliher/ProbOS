"""AD-1041: project the live ProbOS capability surface into an ARD ``AiCatalog``.

Epic #989 Foundation 2/12. This module turns the AD-1001 "Ship's Locker"
assembly (tools / skills / mesh-intents / MCP servers) plus the AD-1003c pack
inventory into the AD-1040 catalog envelope, so a generic ARD client can read
``GET /.well-known/ai-catalog.json`` (AD-1042) and discover what the ship can do.

Layer discipline (AD-1040 purity invariant):
  * the three pure modules — ``catalog`` / ``urn`` / ``media_types`` — stay
    ``probos``-import-free; this projector is allowed to import ``probos`` but
    does so LAZILY (in-function) so importing ``probos.federation.ard`` never
    triggers a router/runtime import at module-load time (no import cycle).

Design contracts reused from AD-1040:
  * DD-1 (value-or-reference): every :class:`CatalogEntry` carries EXACTLY one
    of ``url`` (a reference — used for http-MCP servers that expose a URL) or
    ``data`` (an inline payload — used for the ship-local axes). Enforced by
    ``CatalogEntry.__post_init__``; honest-degrade means a malformed source row
    is SKIPPED (per-entry ``try/except``), never raised.
  * DD-7 (secrets-never-projected): the MCP projection reads ONLY
    ``id`` / ``name`` / ``type`` / ``url`` from each ``McpServerRecord``. It NEVER
    touches ``auth_kind`` / ``credential_ref`` / ``auth_header_name`` /
    ``auth_scheme`` / ``auth_env_var`` / ``oauth_json`` / ``headers`` / ``env`` /
    ``command`` / ``args`` / ``cwd`` — no credential reference or value can reach
    the public catalog.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .catalog import AiCatalog, CatalogEntry, HostInfo
from .media_types import (
    MT_A2A_AGENT,
    MT_AI_CATALOG,
    MT_AI_SKILL,
    MT_MCP_SERVER,
    MT_PROBOS_TOOL,
    PROBOS_AXIS_TO_MEDIA_TYPE,
)
from .urn import build_urn

logger = logging.getLogger(__name__)

# How many representative queries to attach to any one entry (DD-3 bound).
_REPR_CAP = 5


def _sanitize_domain(name: str) -> str:
    """Slugify a free-text vessel name into a URN-safe publisher segment.

    Lowercases, replaces any run of non ``[a-z0-9.-]`` characters with a single
    hyphen, and strips leading/trailing hyphens/dots. Returns ``""`` when nothing
    usable remains (honest-degrade — the caller falls through to the next source).
    """
    return re.sub(r"[^a-z0-9.-]+", "-", (name or "").strip().lower()).strip("-.")


def _publisher_domain(runtime: Any) -> str:
    """Resolve the URN publisher (FQDN-ish) segment.

    Precedence: an explicit ``federation.ard.publisher_namespace_domain`` →
    the ship certificate's ``vessel_name`` (sanitized) → its ``ship_did`` →
    ``"probos.local"``. Every lookup honest-degrades (never raises).
    """
    try:
        cfg = getattr(getattr(getattr(runtime, "config", None), "federation", None), "ard", None)
        configured = (getattr(cfg, "publisher_namespace_domain", "") or "").strip()
        if configured:
            return configured
    except Exception:
        logger.debug("AD-1041: publisher domain config read failed", exc_info=True)
    try:
        registry = getattr(runtime, "identity_registry", None)
        if registry is not None:
            cert = registry.get_ship_certificate()
            if cert is not None:
                slug = _sanitize_domain(getattr(cert, "vessel_name", "") or "")
                if slug:
                    return slug
                did = (getattr(cert, "ship_did", "") or "").strip()
                if did:
                    return did
    except Exception:
        logger.debug("AD-1041: publisher domain cert read failed", exc_info=True)
    return "probos.local"


def _host_info(runtime: Any) -> HostInfo:
    """Build the catalog ``HostInfo`` from the ship certificate (honest-degrade)."""
    vessel_name = "ProbOS"
    ship_did = ""
    try:
        registry = getattr(runtime, "identity_registry", None)
        if registry is not None:
            cert = registry.get_ship_certificate()
            if cert is not None:
                vessel_name = getattr(cert, "vessel_name", "") or "ProbOS"
                ship_did = getattr(cert, "ship_did", "") or ""
    except Exception:
        logger.debug("AD-1041: host info cert read failed", exc_info=True)
    return HostInfo(display_name=vessel_name, identifier=ship_did)


def _repr_for(repr_queries: dict[str, list[str]] | None, keys: list[str]) -> list[str]:
    """Merge representative queries across ``keys`` (deduped, capped at 5).

    The miner (AD-1043) keys its output by intent name, so a mesh-intent matches
    on its own name, a skill matches on any of its intents, and a tool matches on
    its id. A resource with no observed query simply gets an empty list.
    """
    if not repr_queries:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if not key:
            continue
        for query in repr_queries.get(key, []) or []:
            if query in seen:
                continue
            seen.add(query)
            out.append(query)
            if len(out) >= _REPR_CAP:
                return out
    return out


async def project_catalog(
    runtime: Any,
    *,
    repr_queries: dict[str, list[str]] | None = None,
) -> AiCatalog:
    """Project the live ProbOS capability surface into an ARD ``AiCatalog``.

    Reuses the AD-1001 ``list_capability_catalog`` assembly (tools / skills /
    mesh-intents) + the AD-1015 ``mcp_server_store`` + the AD-1003c pack
    inventory. ``repr_queries`` (from AD-1043) is attached per entry. Every
    source axis honest-degrades independently and every entry is built behind a
    per-entry ``try/except`` (a malformed row is skipped, never raised) — so the
    projector always returns a well-formed catalog (host-only in the worst case).
    """
    publisher = _publisher_domain(runtime)
    host = _host_info(runtime)
    entries: list[CatalogEntry] = []

    # --- AD-1001 Ship's Locker assembly (tools / skills / mesh-intents) ------
    try:
        from probos.routers.tools import list_capability_catalog

        locker = await list_capability_catalog(runtime)
    except Exception:
        logger.warning("AD-1041: capability catalog assembly failed; skipping ship axes", exc_info=True)
        locker = {}

    # --- tools ---------------------------------------------------------------
    for tool in locker.get("tools", []) or []:
        try:
            tid = tool.get("id", "") or ""
            origin = tool.get("origin", "built_in") or "built_in"
            domain = tool.get("domain", "") or ""
            department = tool.get("department")
            data: dict[str, Any] = {"axis": "tool", "origin": origin}
            if domain:
                data["domain"] = domain
            if department:
                data["department"] = department
            tags = [t for t in (origin, domain) if t and t != "*"]
            entries.append(CatalogEntry(
                identifier=build_urn(publisher, "tools", tid),
                display_name=tool.get("name", tid) or tid,
                type=PROBOS_AXIS_TO_MEDIA_TYPE.get(origin, MT_PROBOS_TOOL),
                data=data,
                description=tool.get("description", "") or "",
                tags=tags,
                capabilities=[tid] if tid else [],
                representative_queries=_repr_for(repr_queries, [tid]),
            ))
        except Exception:
            logger.debug("AD-1041: tool projection skipped a malformed row", exc_info=True)

    # --- skills --------------------------------------------------------------
    for skill in locker.get("skills", []) or []:
        try:
            sid = skill.get("id", "") or ""
            intents = list(skill.get("intents", []) or [])
            department = skill.get("department")
            min_rank = skill.get("min_rank")
            data = {"axis": "skill"}
            if department:
                data["department"] = department
            if min_rank:
                data["minRank"] = min_rank
            entries.append(CatalogEntry(
                identifier=build_urn(publisher, "skills", sid),
                display_name=skill.get("name", sid) or sid,
                type=MT_AI_SKILL,
                data=data,
                description=skill.get("description", "") or "",
                tags=[department] if department and department != "*" else [],
                capabilities=intents,
                representative_queries=_repr_for(repr_queries, intents or [sid]),
            ))
        except Exception:
            logger.debug("AD-1041: skill projection skipped a malformed row", exc_info=True)

    # --- mesh intents --------------------------------------------------------
    for mesh in locker.get("mesh_intents", []) or []:
        try:
            name = (mesh.get("name", "") or mesh.get("id", "")) or ""
            description = mesh.get("description", "") or ""
            usage_hint = mesh.get("usage_hint", "") or ""
            if usage_hint:
                description = f"{description} {usage_hint}".strip() if description else usage_hint
            tier = mesh.get("tier", "domain") or "domain"
            data = {
                "axis": "mesh_intent",
                "tier": tier,
                "requiresConsensus": bool(mesh.get("requires_consensus", False)),
            }
            entries.append(CatalogEntry(
                identifier=build_urn(publisher, "intents", name),
                display_name=name,
                type=MT_A2A_AGENT,
                data=data,
                description=description,
                tags=[tier],
                capabilities=[name] if name else [],
                representative_queries=_repr_for(repr_queries, [name]),
            ))
        except Exception:
            logger.debug("AD-1041: mesh-intent projection skipped a malformed row", exc_info=True)

    # --- MCP servers (DD-7: ONLY id/name/type/url — never any credential) ----
    store = getattr(runtime, "mcp_server_store", None)
    records: list[Any] = []
    if store is not None:
        try:
            records = store.list_sync()
        except Exception:
            logger.debug("AD-1041: mcp_server_store.list_sync failed", exc_info=True)
            records = []
    for record in records:
        try:
            rid = getattr(record, "id", "") or ""
            rname = getattr(record, "name", "") or ""
            rtype = getattr(record, "type", "") or ""
            rurl = getattr(record, "url", "") or ""
            # URN name segment uses the human handle (consistent with the
            # tool/skill/intent axes); the uuid id is a back-up only.
            identifier = build_urn(publisher, "mcp", rname or rid)
            display_name = rname or rid
            capabilities = [rname] if rname else []
            if rtype == "http" and rurl:
                # DD-1: an http-MCP server with a URL is projected by REFERENCE.
                entries.append(CatalogEntry(
                    identifier=identifier,
                    display_name=display_name,
                    type=MT_MCP_SERVER,
                    url=rurl,
                    capabilities=capabilities,
                ))
            else:
                # DD-1: otherwise project an inline non-secret descriptor.
                entries.append(CatalogEntry(
                    identifier=identifier,
                    display_name=display_name,
                    type=MT_MCP_SERVER,
                    data={"axis": "mcp", "serverType": rtype},
                    capabilities=capabilities,
                ))
        except Exception:
            logger.debug("AD-1041: mcp projection skipped a malformed record", exc_info=True)

    # --- AD-1003c packs ------------------------------------------------------
    try:
        from probos.routers.packs import list_packs

        packs_resp = await list_packs(runtime)
    except Exception:
        logger.debug("AD-1041: pack inventory read failed", exc_info=True)
        packs_resp = {}
    for pack in packs_resp.get("packs", []) or []:
        try:
            if not pack.get("ok", False):
                continue
            pid = pack.get("name", "") or ""
            data = {"axis": "pack"}
            version = pack.get("version", "") or ""
            if version:
                data["version"] = version
            entries.append(CatalogEntry(
                identifier=build_urn(publisher, "packs", pid),
                display_name=pid,
                type=MT_AI_CATALOG,
                data=data,
                description=pack.get("description", "") or "",
                representative_queries=_repr_for(repr_queries, [pid]),
            ))
        except Exception:
            logger.debug("AD-1041: pack projection skipped a malformed row", exc_info=True)

    return AiCatalog(host=host, entries=entries)


__all__ = ["project_catalog"]
