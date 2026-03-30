"""ProbOS API — Scheduled Task routes (Phase 25a, AD-418)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from probos.api_models import ScheduledTaskRequest, UpdateAgentHintRequest
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scheduled-tasks", tags=["scheduled-tasks"])


@router.get("")
async def list_scheduled_tasks(status: str | None = None, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """List persistent scheduled tasks."""
    if not runtime.persistent_task_store:
        return {"tasks": [], "error": "Persistent task store not enabled"}
    tasks = await runtime.persistent_task_store.list_tasks(status=status)
    return {"tasks": [runtime.persistent_task_store._task_to_dict(t) for t in tasks]}


@router.post("")
async def create_scheduled_task(req: ScheduledTaskRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Create a new persistent scheduled task."""
    if not runtime.persistent_task_store:
        return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
    try:
        task = await runtime.persistent_task_store.create_task(
            intent_text=req.intent_text,
            schedule_type=req.schedule_type,
            name=req.name,
            execute_at=req.execute_at,
            interval_seconds=req.interval_seconds,
            cron_expr=req.cron_expr,
            channel_id=req.channel_id,
            max_runs=req.max_runs,
            created_by=req.created_by,
            webhook_name=req.webhook_name,
            agent_hint=req.agent_hint,
        )
        return runtime.persistent_task_store._task_to_dict(task)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.get("/{task_id}")
async def get_scheduled_task(task_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Get a single scheduled task by ID."""
    if not runtime.persistent_task_store:
        return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
    task = await runtime.persistent_task_store.get_task(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})
    return runtime.persistent_task_store._task_to_dict(task)


@router.delete("/{task_id}")
async def cancel_scheduled_task(task_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Cancel a scheduled task."""
    if not runtime.persistent_task_store:
        return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
    cancelled = await runtime.persistent_task_store.cancel_task(task_id)
    if not cancelled:
        return JSONResponse(status_code=404, content={"error": "Task not found or already cancelled"})
    return {"cancelled": True, "task_id": task_id}


@router.patch("/{task_id}/hint")
async def update_task_agent_hint(
    task_id: str, req: UpdateAgentHintRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-418: Update a scheduled task's agent_hint for routing bias."""
    if not runtime.persistent_task_store:
        return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
    task = await runtime.persistent_task_store.get_task(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})
    # Direct DB update
    async with runtime.persistent_task_store._db.execute(
        "UPDATE scheduled_tasks SET agent_hint = ? WHERE id = ?",
        (req.agent_hint, task_id),
    ) as _:
        pass
    await runtime.persistent_task_store._db.commit()
    updated = await runtime.persistent_task_store.get_task(task_id)
    return runtime.persistent_task_store._task_to_dict(updated)


@router.post("/webhook/{webhook_name}")
async def trigger_webhook(webhook_name: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Trigger a named webhook task."""
    if not runtime.persistent_task_store:
        return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
    task = await runtime.persistent_task_store.trigger_webhook(webhook_name)
    if not task:
        return JSONResponse(status_code=404, content={"error": f"Webhook '{webhook_name}' not found"})
    return {"triggered": True, "task_id": task.id, "webhook_name": webhook_name}


@router.post("/dag/{dag_id}/resume")
async def resume_dag_checkpoint(dag_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Resume a stale DAG checkpoint (Captain-approved)."""
    if not runtime.persistent_task_store:
        return JSONResponse(status_code=503, content={"error": "Persistent task store not enabled"})
    result = await runtime.persistent_task_store.resume_dag(dag_id)
    if "error" in result:
        return JSONResponse(status_code=400, content=result)
    return result
