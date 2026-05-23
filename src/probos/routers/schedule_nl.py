"""AD-812: POST /api/schedule/nl — natural-language scheduling endpoint."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from probos.cognitive.schedule_parser import parse_nl_schedule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class NLScheduleRequest(BaseModel):
    text: str


@router.post("/nl")
async def schedule_from_nl(req: NLScheduleRequest, request: Request) -> dict[str, Any]:
    runtime = request.app.state.runtime
    store = getattr(runtime, "persistent_task_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Persistent task store not available")
    spec = await parse_nl_schedule(
        req.text, llm_client=getattr(runtime, "llm_client", None)
    )
    if spec.kind == "error":
        raise HTTPException(status_code=400, detail=spec.reason)
    task = await store.create_task(
        intent_text=spec.intent_text,
        schedule_type=spec.kind,
        execute_at=spec.execute_at,
        interval_seconds=spec.interval_seconds,
        cron_expr=spec.cron_expr,
        channel_id=spec.channel_id,
        max_runs=spec.max_runs,
    )
    return store._task_to_dict(task)
