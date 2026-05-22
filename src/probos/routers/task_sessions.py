"""AD-815a: REST routes for TaskSession substrate."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from probos.routers.deps import get_runtime

router = APIRouter(prefix="/api/task-sessions", tags=["task-sessions"])


def _get_store(runtime: Any):
    store = getattr(runtime, "task_session_store", None)
    if store is None:
        raise HTTPException(
            status_code=503, detail="TaskSessionStore not available"
        )
    return store


class CreateSessionRequest(BaseModel):
    thread_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=200)
    work_item_id: str | None = None
    schedule_kind: str = Field(default="one_shot", pattern="^(one_shot|recurring)$")
    schedule_cron: str | None = None
    schedule_timezone: str | None = None
    recurrence_policy: str = Field(
        default="reuse", pattern="^(reuse|new_session_each_run)$"
    )
    recurrence_max_runs: int | None = None
    container_image: str | None = None
    egress_policy: str = Field(default="bridge", pattern="^(none|bridge|allowlist)$")


class FinishRunRequest(BaseModel):
    exit_code: int
    container_image_used: str | None = None
    pip_installed_extras: list[str] | None = None
    error: str | None = None


@router.post("")
async def create_session(
    body: CreateSessionRequest, runtime: Any = Depends(get_runtime)
) -> dict:
    store = _get_store(runtime)
    session = store.create_session(
        thread_id=body.thread_id,
        title=body.title,
        work_item_id=body.work_item_id,
        schedule_kind=body.schedule_kind,
        schedule_cron=body.schedule_cron,
        schedule_timezone=body.schedule_timezone,
        recurrence_policy=body.recurrence_policy,
        recurrence_max_runs=body.recurrence_max_runs,
        container_image=body.container_image,
        egress_policy=body.egress_policy,
    )
    return session.to_dict()


@router.get("")
async def list_sessions(
    thread_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    items = store.list_sessions(thread_id=thread_id, status=status, limit=limit)
    return {"sessions": [s.to_dict() for s in items]}


@router.get("/{session_id}")
async def get_session(session_id: str, runtime: Any = Depends(get_runtime)) -> dict:
    store = _get_store(runtime)
    s = store.get_session(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return s.to_dict()


@router.get("/{session_id}/runs")
async def list_runs(session_id: str, runtime: Any = Depends(get_runtime)) -> dict:
    store = _get_store(runtime)
    if store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    runs = store.list_runs(session_id)
    return {"session_id": session_id, "runs": [r.to_dict() for r in runs]}


@router.post("/{session_id}/run")
async def start_run(session_id: str, runtime: Any = Depends(get_runtime)) -> dict:
    from probos.task_sessions import InvalidStatusTransition

    store = _get_store(runtime)
    try:
        run = store.start_run(session_id)
    except InvalidStatusTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return run.to_dict()


@router.post("/{session_id}/cancel")
async def cancel_session(
    session_id: str, runtime: Any = Depends(get_runtime)
) -> dict:
    store = _get_store(runtime)
    s = store.cancel(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return s.to_dict()


@router.post("/runs/{run_id}/finish")
async def finish_run(
    run_id: str, body: FinishRunRequest, runtime: Any = Depends(get_runtime)
) -> dict:
    store = _get_store(runtime)
    run = store.finish_run(
        run_id,
        exit_code=body.exit_code,
        container_image_used=body.container_image_used,
        pip_installed_extras=body.pip_installed_extras,
        error=body.error,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.to_dict()
