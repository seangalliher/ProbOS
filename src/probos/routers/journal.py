"""ProbOS API — Cognitive Journal routes (AD-431, AD-432)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("/stats")
async def journal_stats(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-431: Cognitive Journal statistics."""
    if not runtime.cognitive_journal:
        return {"total_entries": 0}
    return await runtime.cognitive_journal.get_stats()


@router.get("/tokens")
async def journal_token_usage(agent_id: str | None = None, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-431: Token usage summary (ship-wide or per-agent)."""
    if not runtime.cognitive_journal:
        return {"total_tokens": 0, "total_calls": 0}
    return await runtime.cognitive_journal.get_token_usage(agent_id)


@router.get("/tokens/by")
async def journal_token_usage_by(
    group_by: str = "model", agent_id: str | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-432: Token usage grouped by model, tier, agent, or intent."""
    if not runtime.cognitive_journal:
        return {"groups": []}
    groups = await runtime.cognitive_journal.get_token_usage_by(
        group_by=group_by, agent_id=agent_id,
    )
    return {"group_by": group_by, "groups": groups}


@router.get("/decisions")
async def journal_decision_points(
    agent_id: str | None = None,
    min_latency_ms: float | None = None,
    failures_only: bool = False,
    limit: int = 20,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-432: Notable decision points — high-latency or failed LLM calls."""
    if not runtime.cognitive_journal:
        return {"entries": []}
    entries = await runtime.cognitive_journal.get_decision_points(
        agent_id=agent_id,
        min_latency_ms=min_latency_ms,
        failures_only=failures_only,
        limit=min(limit, 100),
    )
    return {"entries": entries}
