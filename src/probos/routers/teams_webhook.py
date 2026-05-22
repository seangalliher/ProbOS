"""AD-805: Microsoft Teams webhook receiver.

Bot Framework POSTs Activity payloads here. The route resolves the
adapter from ``runtime.teams_adapter`` and dispatches the activity.

v1 substrate trusts the inbound POST (Bot Framework's IP range +
firewall). JWT signature verification is AD-805b — required for any
public-facing deployment.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/channels/teams", tags=["channels"])


@router.post("/webhook")
async def teams_webhook(
    request: Request, runtime: Any = Depends(get_runtime)
) -> dict:
    adapter = getattr(runtime, "teams_adapter", None)
    if adapter is None:
        raise HTTPException(
            status_code=503,
            detail="Teams adapter not configured (AD-805 forward marker)",
        )
    try:
        activity = await request.json()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    if not isinstance(activity, dict):
        raise HTTPException(status_code=400, detail="Activity must be a JSON object")
    try:
        return await adapter.dispatch_activity(activity)
    except Exception as exc:
        # Always 200 to Bot Framework — non-2xx triggers retry storms.
        # Log the failure for diagnosis.
        logger.error("AD-805: dispatch_activity raised: %s", exc, exc_info=True)
        return {"status": "error", "message": str(exc)}
