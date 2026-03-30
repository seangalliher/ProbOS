"""ProbOS API — Skill Framework routes (AD-428)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.api_models import SkillAssessmentRequest, SkillCommissionRequest
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("/registry")
async def skills_registry(
    category: str | None = None, domain: str | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """List all skill definitions in the registry."""
    if not runtime.skill_registry:
        return {"skills": []}
    from probos.skill_framework import SkillCategory
    cat = SkillCategory(category) if category else None
    skills = runtime.skill_registry.list_skills(category=cat, domain=domain)
    return {"skills": [
        {
            "skill_id": s.skill_id,
            "name": s.name,
            "category": s.category.value,
            "description": s.description,
            "domain": s.domain,
            "prerequisites": s.prerequisites,
            "decay_rate_days": s.decay_rate_days,
            "origin": s.origin,
        }
        for s in skills
    ]}


@router.get("/agents/{agent_id}/profile")
async def skill_profile(agent_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Get the full skill profile for an agent."""
    if not runtime.skill_service:
        return {"agent_id": agent_id, "pccs": [], "role_skills": [], "acquired_skills": [], "depth": 0, "breadth": 0}
    profile = await runtime.skill_service.get_profile(agent_id)
    return profile.to_dict()


@router.post("/agents/{agent_id}/commission")
async def skill_commission(agent_id: str, req: SkillCommissionRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Commission an agent with initial PCC + role skills."""
    if not runtime.skill_service:
        raise HTTPException(503, "Skill service not available")
    profile = await runtime.skill_service.commission_agent(agent_id, req.agent_type)
    return profile.to_dict()


@router.post("/agents/{agent_id}/assess")
async def skill_assess(agent_id: str, req: SkillAssessmentRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Record a skill assessment (update proficiency)."""
    if not runtime.skill_service:
        raise HTTPException(503, "Skill service not available")
    from probos.skill_framework import ProficiencyLevel
    try:
        level = ProficiencyLevel(req.new_level)
    except ValueError:
        raise HTTPException(400, f"Invalid proficiency level: {req.new_level}")
    record = await runtime.skill_service.update_proficiency(
        agent_id, req.skill_id, level, source=req.source, notes=req.notes,
    )
    if not record:
        raise HTTPException(404, f"Agent {agent_id} does not have skill {req.skill_id}")
    return record.to_dict()


@router.post("/agents/{agent_id}/exercise")
async def skill_exercise(agent_id: str, skill_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Record that an agent exercised a skill."""
    if not runtime.skill_service:
        raise HTTPException(503, "Skill service not available")
    record = await runtime.skill_service.record_exercise(agent_id, skill_id)
    if not record:
        raise HTTPException(404, f"Agent {agent_id} does not have skill {skill_id}")
    return record.to_dict()


@router.get("/agents/{agent_id}/prerequisites/{skill_id}")
async def skill_prerequisites(agent_id: str, skill_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Check if an agent meets prerequisites for a skill."""
    if not runtime.skill_service:
        return {"met": True, "missing": []}
    return await runtime.skill_service.check_prerequisites(agent_id, skill_id)
