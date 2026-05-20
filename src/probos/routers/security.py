"""AD-754 security endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, model_validator

from probos.knowledge.erasure import ErasureManager
from probos.routers.deps import get_runtime
from probos.security.audit_log import AuditLog

router = APIRouter(prefix="/api/security", tags=["security"])


class ForgetRequest(BaseModel):
    episode_id: str | None = None
    resource_path: str | None = None
    agent_id: str | None = None
    reason: str = "user_request"

    @model_validator(mode="after")
    def _validate_target(self) -> "ForgetRequest":
        provided = [
            bool(self.episode_id),
            bool(self.resource_path),
            bool(self.agent_id),
        ]
        if sum(1 for flag in provided if flag) != 1:
            raise ValueError("exactly one of episode_id/resource_path/agent_id is required")
        return self


def _get_audit_log(runtime: Any) -> AuditLog:
    existing = getattr(runtime, "_assistant_audit_log", None)
    if isinstance(existing, AuditLog):
        return existing

    retention = int(getattr(runtime.config.security_infra, "audit_retention_days", 90))
    data_dir = Path(getattr(runtime, "_data_dir", Path("data")))
    log = AuditLog(db_path=str(data_dir / "assistant_audit.db"), retention_days=retention)
    runtime._assistant_audit_log = log
    return log


@router.post("/forget")
async def request_erasure(
    request: ForgetRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """User-directed erasure for episode, resource, or agent memory."""
    manager = ErasureManager(
        episodic_memory=getattr(runtime, "episodic_memory", None),
        attachment_store=getattr(runtime, "attachment_store", None),
        audit_log=_get_audit_log(runtime),
    )

    if request.episode_id:
        result = await manager.forget_episode(request.episode_id, reason=request.reason)
    elif request.resource_path:
        result = await manager.forget_resource(request.resource_path)
    elif request.agent_id:
        result = await manager.forget_agent_memory(request.agent_id)
    else:
        return JSONResponse(
            {"error": "one erasure target is required"},
            status_code=400,
        )

    return {
        "deleted_count": result.count,
        "timestamps": result.timestamps,
        "deleted_episode_ids": result.deleted_episode_ids,
        "deleted_attachment_ids": result.deleted_attachment_ids,
    }
