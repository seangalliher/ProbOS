"""ProbOS API — Counselor routes (AD-503)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/counselor", tags=["counselor"])


@router.get("/profiles")
async def list_profiles(runtime: Any = Depends(get_runtime)) -> Any:
    """List all cognitive profiles (summary view)."""
    if not runtime._counselor_profile_store:
        return JSONResponse({"error": "Counselor not available"}, status_code=503)
    summary = await runtime._counselor_profile_store.get_crew_summary()
    return {"profiles": summary}


@router.get("/profile/{agent_id}")
async def get_profile(agent_id: str, runtime: Any = Depends(get_runtime)) -> Any:
    """Get detailed cognitive profile for an agent."""
    if not runtime._counselor_profile_store:
        return JSONResponse({"error": "Counselor not available"}, status_code=503)
    profile = await runtime._counselor_profile_store.load_profile(agent_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile for {agent_id}")
    return profile.to_dict()


@router.get("/assessments/{agent_id}")
async def get_assessments(
    agent_id: str, limit: int = 20, runtime: Any = Depends(get_runtime)
) -> Any:
    """Get assessment history for an agent."""
    if not runtime._counselor_profile_store:
        return JSONResponse({"error": "Counselor not available"}, status_code=503)
    history = await runtime._counselor_profile_store.get_assessment_history(
        agent_id, limit=limit
    )
    return {"agent_id": agent_id, "assessments": [a.to_dict() for a in history]}


@router.get("/summary")
async def crew_summary(runtime: Any = Depends(get_runtime)) -> Any:
    """Get crew-wide wellness summary."""
    counselor = _get_counselor_agent(runtime)
    if not counselor:
        return JSONResponse({"error": "Counselor not available"}, status_code=503)
    profiles = counselor.all_profiles()
    red = sum(1 for p in profiles if p.alert_level == "red")
    yellow = sum(1 for p in profiles if p.alert_level == "yellow")
    green = sum(1 for p in profiles if p.alert_level == "green")
    return {
        "total": len(profiles),
        "red": red,
        "yellow": yellow,
        "green": green,
        "profiles": [
            {
                "agent_id": p.agent_id,
                "alert_level": p.alert_level,
                "last_assessed": p.last_assessed,
            }
            for p in profiles
        ],
    }


@router.post("/assess/{agent_id}")
async def assess_agent(agent_id: str, runtime: Any = Depends(get_runtime)) -> Any:
    """Trigger an on-demand assessment for a specific agent."""
    counselor = _get_counselor_agent(runtime)
    if not counselor:
        return JSONResponse({"error": "Counselor not available"}, status_code=503)
    agent = runtime.registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    metrics = counselor._gather_agent_metrics(agent_id)
    assessment = counselor.assess_agent(
        agent_id,
        current_trust=metrics["trust_score"],
        current_confidence=metrics["confidence"],
        hebbian_avg=metrics["hebbian_avg"],
        success_rate=metrics["success_rate"],
        personality_drift=metrics["personality_drift"],
        trigger="api",
    )
    # Persist
    if runtime._counselor_profile_store:
        profile = counselor.get_profile(agent_id)
        if profile:
            await runtime._counselor_profile_store.save_profile(profile)
        await runtime._counselor_profile_store.save_assessment(assessment)
    return assessment.to_dict()


@router.post("/sweep")
async def run_sweep(runtime: Any = Depends(get_runtime)) -> Any:
    """Trigger a full crew wellness sweep."""
    counselor = _get_counselor_agent(runtime)
    if not counselor:
        return JSONResponse({"error": "Counselor not available"}, status_code=503)
    results = await counselor._run_wellness_sweep()
    return {
        "total_assessed": len(results),
        "assessments": [r.to_dict() for r in results],
    }


def _get_counselor_agent(runtime: Any) -> Any:
    """Get the counselor agent from the pool."""
    if "counselor" not in runtime.pools:
        return None
    agents = runtime.registry.get_by_pool("counselor")
    return agents[0] if agents else None
