"""ProbOS API — remote skill/pack marketplace BROWSE (AD-813, read-only).

Fetches an operator-configured registry index so the operator can browse
available packs/skills. **BROWSE ONLY — nothing is downloaded, written, scanned,
loaded, or executed** (install is a later slice, AD-813b, behind the operator
trust gate).

SSRF guard (the #1 invariant): the registry URL comes ONLY from
``config.skills_marketplace.registry_url`` (operator config) — the endpoint
exposes NO ``url`` / ``registry_url`` param. The only request input that reaches
the fetch is ``query`` (a ``?q=`` SEARCH TERM), which never changes the host.
Disabled (``enabled=False`` OR empty ``registry_url``) → inert shape, ZERO HTTP
calls.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from probos.packs.marketplace import fetch_marketplace_index
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills/marketplace", tags=["marketplace"])


@router.get("")
async def browse_marketplace(
    query: str = "",
    page: int = 1,
    page_size: int | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-813: read-only BROWSE of the operator-configured remote registry.

    Disabled (no config / ``enabled=False`` / empty ``registry_url``) → inert
    shape with ZERO HTTP calls. Otherwise fetch the CONFIGURED registry (the host
    NEVER comes from the request — SSRF guard), defensively filter by ``query``,
    cap to ``max_results``, and paginate. Honest-degrade: a fetch failure returns
    200 with an empty result set + a generic ``error`` (never raises).
    """
    cfg = getattr(getattr(runtime, "config", None), "skills_marketplace", None)
    url = (getattr(cfg, "registry_url", "") or "").strip() if cfg else ""
    if cfg is None or not getattr(cfg, "enabled", False) or not url:
        return {"enabled": False, "results": [], "counts": {"total": 0, "returned": 0}}

    result = await fetch_marketplace_index(
        url,
        query=query,
        timeout=cfg.timeout_seconds,
        max_bytes=cfg.max_bytes,
        source=url,
    )

    # Defensive client-side filter (name + description, case-insensitive). The
    # registry MAY have honored ?q=; this guarantees the contract regardless.
    entries = result.entries
    q = query.strip().lower()
    if q:
        entries = [
            e for e in entries if q in e.name.lower() or q in e.description.lower()
        ]

    capped = entries[: cfg.max_results]
    ps = min(page_size or cfg.default_page_size, 100)
    pg = max(page, 1)
    start = (pg - 1) * ps
    page_items = capped[start : start + ps]
    return {
        "enabled": True,
        "results": [e.to_dict() for e in page_items],
        "counts": {"total": len(capped), "returned": len(page_items)},
        "page": pg,
        "page_size": ps,
        "error": result.error or None,
    }
