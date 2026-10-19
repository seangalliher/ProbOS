"""ProbOS API — Agent Capital Management routes (AD-427)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.api_models import AgentLifecycleRequest
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/acm", tags=["acm"])

# BF-906: suspend and reinstate record an HR status (AD-427). They do not stop,
# pause or resume the agent's work; the operational stop is AD-1343 (#1595).
HR_STATUS_NOTE = (
    "Records an HR status only. It does not stop or resume the agent's work "
    "(the operational stop is AD-1343)."
)


def _hr_transition_body(status: str, t: Any) -> dict[str, Any]:
    return {
        "status": status,
        "hr_status_only": True,
        "note": HR_STATUS_NOTE,
        "transition": {
            "from_state": t.from_state, "to_state": t.to_state,
            "reason": t.reason, "timestamp": t.timestamp,
        },
    }


@router.get("/agents/{agent_id}/profile")
async def get_acm_profile(agent_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-427: Consolidated agent profile from ACM."""
    if not runtime.acm:
        return {"error": "ACM not available"}
    return await runtime.acm.get_consolidated_profile(agent_id, runtime)


@router.get("/agents/{agent_id}/lifecycle")
async def get_acm_lifecycle(agent_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-427: Agent lifecycle state and transition history."""
    if not runtime.acm:
        return {"error": "ACM not available"}
    state = await runtime.acm.get_lifecycle_state(agent_id)
    history = await runtime.acm.get_transition_history(agent_id)
    return {
        "agent_id": agent_id,
        "current_state": state.value,
        "transitions": [
            {
                "from_state": t.from_state,
                "to_state": t.to_state,
                "reason": t.reason,
                "initiated_by": t.initiated_by,
                "timestamp": t.timestamp,
            }
            for t in history
        ],
    }


@router.post("/agents/{agent_id}/decommission")
async def decommission_agent(agent_id: str, req: AgentLifecycleRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-427: Decommission an agent."""
    if not runtime.acm:
        raise HTTPException(status_code=503, detail="ACM not available")
    reason = req.reason or "Decommissioned by Captain"
    try:
        t = await runtime.acm.decommission(agent_id, reason=reason, initiated_by="captain")
        return {"status": "decommissioned", "transition": {
            "from_state": t.from_state, "to_state": t.to_state,
            "reason": t.reason, "timestamp": t.timestamp,
        }}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/agents/{agent_id}/suspend")
async def suspend_agent(agent_id: str, req: AgentLifecycleRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-427: Record an HR suspension for an agent (Captain order).

    Changes the agent's ACM lifecycle status (an HR record) and nothing else: it
    does not stop, pause or refuse the agent's work (AD-1343). Only an ``active``
    agent can be suspended; any other state answers 409.
    """
    if not runtime.acm:
        raise HTTPException(status_code=503, detail="ACM not available")
    from probos.acm import LifecycleState
    reason = req.reason or "Suspended by Captain"
    try:
        t = await runtime.acm.transition(
            agent_id, LifecycleState.SUSPENDED,
            reason=reason, initiated_by="captain",
        )
        return _hr_transition_body("suspended", t)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/agents/{agent_id}/reinstate")
async def reinstate_agent(agent_id: str, req: AgentLifecycleRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-427: Reinstate a suspended agent's HR status to active.

    An HR record only: a suspension never stopped the agent's work, so reinstating
    resumes nothing (AD-1343).
    """
    if not runtime.acm:
        raise HTTPException(status_code=503, detail="ACM not available")
    from probos.acm import LifecycleState
    reason = req.reason or "Reinstated by Captain"
    try:
        t = await runtime.acm.transition(
            agent_id, LifecycleState.ACTIVE,
            reason=reason, initiated_by="captain",
        )
        return _hr_transition_body("active", t)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
