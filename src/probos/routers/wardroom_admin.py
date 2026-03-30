"""ProbOS API — Ward Room admin routes (AD-416)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ward-room", tags=["wardroom-admin"])


@router.get("/stats")
async def ward_room_stats(runtime: Any = Depends(get_runtime)):
    if not runtime.ward_room:
        return JSONResponse({"error": "Ward Room not enabled"}, status_code=503)
    stats = await runtime.ward_room.get_stats()
    config = runtime.config.ward_room
    pruneable = await runtime.ward_room.count_pruneable(
        config.retention_days, config.retention_days_endorsed, config.retention_days_captain,
    )
    stats["pruneable_threads"] = pruneable
    stats["retention_days"] = config.retention_days
    stats["retention_days_endorsed"] = config.retention_days_endorsed
    return stats


@router.post("/prune")
async def ward_room_prune(runtime: Any = Depends(get_runtime)):
    if not runtime.ward_room:
        return JSONResponse({"error": "Ward Room not enabled"}, status_code=503)
    config = runtime.config.ward_room
    archive_path = None
    if config.archive_enabled:
        archive_dir = runtime._data_dir / "ward_room_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        month = datetime.now().strftime("%Y-%m")
        archive_path = str(archive_dir / f"ward_room_archive_{month}.jsonl")
    result = await runtime.ward_room.prune_old_threads(
        retention_days=config.retention_days,
        retention_days_endorsed=config.retention_days_endorsed,
        retention_days_captain=config.retention_days_captain,
        archive_path=archive_path,
    )
    result.pop("pruned_thread_ids", None)
    return result
