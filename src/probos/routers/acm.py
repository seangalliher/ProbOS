"""ProbOS API — Agent Capital Management routes (AD-427)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.api_models import AgentLifecycleRequest
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/acm", tags=["acm"])


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
    """AD-427: Suspend an agent (Captain order)."""
    if not runtime.acm:
        raise HTTPException(status_code=503, detail="ACM not available")
    from probos.acm import LifecycleState
    reason = req.reason or "Suspended by Captain"
    try:
        t = await runtime.acm.transition(
            agent_id, LifecycleState.SUSPENDED,
            reason=reason, initiated_by="captain",
        )
        return {"status": "suspended", "transition": {
            "from_state": t.from_state, "to_state": t.to_state,
            "reason": t.reason, "timestamp": t.timestamp,
        }}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/agents/{agent_id}/reinstate")
async def reinstate_agent(agent_id: str, req: AgentLifecycleRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-427: Reinstate a suspended agent."""
    if not runtime.acm:
        raise HTTPException(status_code=503, detail="ACM not available")
    from probos.acm import LifecycleState
    reason = req.reason or "Reinstated by Captain"
    try:
        t = await runtime.acm.transition(
            agent_id, LifecycleState.ACTIVE,
            reason=reason, initiated_by="captain",
        )
        return {"status": "active", "transition": {
            "from_state": t.from_state, "to_state": t.to_state,
            "reason": t.reason, "timestamp": t.timestamp,
        }}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
