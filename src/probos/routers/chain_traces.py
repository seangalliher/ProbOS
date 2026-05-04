"""ProbOS API — Cognitive Chain Trace routes (AD-658)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chain-traces", tags=["chain-traces"])


@router.get("")
async def list_chain_traces(
    limit: int = 50,
    agent_id: str | None = None,
    since: float | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-658: Recent cognitive-chain step traces, most recent first.

    Args:
        limit: Max rows (default 50, hard-capped at 500).
        agent_id: Optional agent filter.
        since: Optional Unix-timestamp lower bound on started_at.
    """
    if not runtime.cognitive_journal:
        return {"traces": []}
    traces = await runtime.cognitive_journal.get_recent_chain_traces(
        limit=min(max(limit, 1), 500),
        agent_id=agent_id,
        since=since,
    )
    return {"traces": traces}
