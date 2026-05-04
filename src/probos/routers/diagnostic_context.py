"""ProbOS API — Diagnostic Context routes (AD-661)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diagnostic-context", tags=["diagnostic-context"])


@router.get("")
async def get_diagnostic_context(
    query: str = "",
    budget: int = 8000,
    agent_id: str | None = None,
    since: float | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-661 v1: Pull-based diagnostic-context bundle.

    Args:
        query: Keyword filter (whitespace-split, lowercased, ≥3 chars retained).
        budget: Token budget (default 8000, hard cap 32000).
        agent_id: Optional chain-trace agent filter.
        since: Optional Unix-timestamp lower bound for chain traces.
    """
    service = getattr(runtime, "diagnostic_context_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="diagnostic_context disabled")

    since_dt = (
        datetime.fromtimestamp(since, tz=timezone.utc) if since is not None else None
    )
    bundle = await service.assemble(
        query=query,
        budget_tokens=min(max(budget, 1), 32000),
        agent_id=agent_id,
        since=since_dt,
    )
    return bundle.to_dict()
