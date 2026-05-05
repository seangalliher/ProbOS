"""ProbOS API — NL-to-Graph Query routes (AD-691 v1)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nl-graph-query", tags=["nl-graph-query"])


@router.get("")
async def nl_graph_query(
    q: str = "",
    max_hops: int = 2,
    limit: int = 10,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-691 v1: NL-to-graph query.

    Args:
        q: Natural-language query.
        max_hops: Traversal depth (clamped to [1, 3]).
        limit: Max edges returned (clamped to >= 1, hard cap 100).
    """
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="q must be non-empty")
    service = getattr(runtime, "nl_graph_query", None)
    if service is None:
        raise HTTPException(status_code=503, detail="nl_graph_query disabled")
    result = await service.query(
        q,
        max_hops=min(max(max_hops, 1), 3),
        limit=min(max(limit, 1), 100),
    )
    return result.to_dict()
