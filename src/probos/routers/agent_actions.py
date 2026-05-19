"""AD-745: Captain-facing endpoints for the agent-action dispatcher.

Three endpoints:

* ``POST /api/browser/actions/{action_id}/ack``   — tier-2 in-thread ACK.
* ``POST /api/browser/actions/{action_id}/abort`` — Captain abort.
* ``GET  /api/browser/actions/{thread_id}``       — list pending + recent
  actions for a DM thread.

All require ``crew`` scope. AD-722c-3 forward marker AD-745-7 covers
SQLite persistence across restart; v1 is process-lifetime in-memory.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from probos.cognitive.dm.action_dispatcher import ActionStatus
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/browser", tags=["browser-actions"])


def _dispatcher(runtime: Any):
    return getattr(runtime, "action_dispatcher", None)


@router.post(
    "/actions/{action_id}/ack",
    dependencies=[Depends(require_crew_scope)],
)
async def ack_action(
    action_id: str,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """Captain-issued ACK for a pending tier-2 (or tier-3 confirm) action.

    Tier-2 honest-degrade: unknown action_id returns 404 without raising;
    already-executed actions return 409 (conflict) to surface the
    duplicate to the operator.
    """
    disp = _dispatcher(runtime)
    if disp is None:
        return JSONResponse(status_code=503, content={"error": "dispatcher_unavailable"})
    action = disp.get(action_id)
    if action is None:
        return JSONResponse(status_code=404, content={"error": "action_not_found"})
    if action.status in (
        ActionStatus.EXECUTED, ActionStatus.ABORTED,
        ActionStatus.TIMED_OUT, ActionStatus.FAILED,
    ):
        return JSONResponse(status_code=409, content={
            "error": "action_already_decided",
            "status": action.status.value,
        })

    browser_tool = getattr(runtime, "browser_tool", None)
    result: Any = None
    error: str | None = None
    if browser_tool is not None:
        try:
            params = {"action": action.verb, **action.args}
            tool_result = await browser_tool.invoke(
                params, context={"agent_id": action.agent_id},
            )
            result = getattr(tool_result, "output", None)
            error = getattr(tool_result, "error", None)
        except Exception as ex:
            error = str(ex)
            logger.warning(
                "AD-745: BrowserTool.invoke raised on ack action_id=%s: %s",
                action_id, ex, exc_info=True,
            )

    if error:
        disp.mark_failed(action_id, error=error)
    else:
        disp.mark_executed(action_id, result=result)

    updated = disp.get(action_id)
    return {"ok": error is None, "action": updated.to_public_dict() if updated else None}


@router.post(
    "/actions/{action_id}/abort",
    dependencies=[Depends(require_crew_scope)],
)
async def abort_action(
    action_id: str,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """Captain-issued abort. Also sets the BrowserSession ``aborted`` flag
    so any in-flight Playwright operation surfaces the abort signal.
    """
    disp = _dispatcher(runtime)
    if disp is None:
        return JSONResponse(status_code=503, content={"error": "dispatcher_unavailable"})
    action = disp.get(action_id)
    if action is None:
        return JSONResponse(status_code=404, content={"error": "action_not_found"})

    browser_tool = getattr(runtime, "browser_tool", None)
    if browser_tool is not None:
        try:
            session = browser_tool.get_session(action.agent_id)
            if session is not None:
                setattr(session, "aborted", True)
        except Exception:
            logger.warning(
                "AD-745: BrowserTool.get_session raised on abort action_id=%s",
                action_id, exc_info=True,
            )

    disp.mark_aborted(action_id, error="aborted_by_captain")
    updated = disp.get(action_id)
    return {"ok": True, "action": updated.to_public_dict() if updated else None}


@router.get(
    "/actions/by-thread/{thread_id}",
    dependencies=[Depends(require_crew_scope)],
)
async def list_thread_actions(
    thread_id: str,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """Return all dispatched actions for a DM thread, newest first."""
    disp = _dispatcher(runtime)
    if disp is None:
        return {"actions": []}
    actions = disp.list_for_thread(thread_id)
    actions.sort(key=lambda a: a.proposed_at, reverse=True)
    return {"actions": [a.to_public_dict() for a in actions]}
