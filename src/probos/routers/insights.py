"""AD-810: GET /api/insights operator-facing recent-activity summary."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["insights"])


@router.get("/insights")
async def get_insights(
    request: Request, days: int = Query(default=7, ge=1, le=90)
) -> dict[str, Any]:
    """Return aggregated recent-activity insights as JSON."""
    runtime = request.app.state.runtime
    service = getattr(runtime, "insight_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Insights service not available")
    report = await service.build_report(days=days)
    return report.to_json()
