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


# --- Cognitive Skill Catalog (AD-596a) ---


@router.get("/catalog")
async def catalog_list(
    department: str | None = None,
    rank: str | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """List all cognitive skills (name + description + metadata)."""
    if not runtime.cognitive_skill_catalog:
        return {"skills": []}
    from probos.cognitive.skill_catalog import CognitiveSkillEntry

    entries: list[CognitiveSkillEntry] = runtime.cognitive_skill_catalog.list_entries(
        department=department, min_rank=rank,
    )
    return {
        "skills": [
            {
                "name": e.name,
                "description": e.description,
                "department": e.department,
                "skill_id": e.skill_id,
                "min_proficiency": e.min_proficiency,
                "min_rank": e.min_rank,
                "intents": e.intents,
                "origin": e.origin,
                "license": e.license,
                "compatibility": e.compatibility,
            }
            for e in entries
        ]
    }


@router.get("/catalog/{name}")
async def catalog_get(name: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Get full skill entry including instructions content."""
    if not runtime.cognitive_skill_catalog:
        raise HTTPException(503, "Cognitive skill catalog not available")
    entry = runtime.cognitive_skill_catalog.get_entry(name)
    if not entry:
        raise HTTPException(404, f"Skill not found: {name}")
    instructions = runtime.cognitive_skill_catalog.get_instructions(name)
    return {
        "name": entry.name,
        "description": entry.description,
        "department": entry.department,
        "skill_id": entry.skill_id,
        "min_proficiency": entry.min_proficiency,
        "min_rank": entry.min_rank,
        "intents": entry.intents,
        "origin": entry.origin,
        "license": entry.license,
        "compatibility": entry.compatibility,
        "instructions": instructions,
    }


@router.post("/catalog/rescan")
async def catalog_rescan(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Trigger scan_and_register() to pick up new/changed skill files."""
    if not runtime.cognitive_skill_catalog:
        raise HTTPException(503, "Cognitive skill catalog not available")
    count = await runtime.cognitive_skill_catalog.scan_and_register()
    return {"rescanned": True, "count": count}


# --- AD-596d: External Skill Import endpoints ---


@router.post("/catalog/import")
async def catalog_import(body: dict[str, Any], runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Import a cognitive skill from a filesystem path."""
    if not runtime.cognitive_skill_catalog:
        raise HTTPException(503, "Cognitive skill catalog not available")
    source_path = body.get("source_path")
    if not source_path:
        raise HTTPException(400, "Missing 'source_path' in request body")

    from pathlib import Path
    try:
        entry = await runtime.cognitive_skill_catalog.import_skill(Path(source_path))
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "imported": True,
        "name": entry.name,
        "origin": entry.origin,
        "description": entry.description,
    }


@router.get("/catalog/discover")
async def catalog_discover(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Discover pip-installed skills available for import."""
    if not runtime.cognitive_skill_catalog:
        raise HTTPException(503, "Cognitive skill catalog not available")
    results = runtime.cognitive_skill_catalog.discover_package_skills()
    return {"skills": results}


@router.put("/catalog/{name}/enrich")
async def catalog_enrich(
    name: str,
    body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Add or update ProbOS metadata on a cognitive skill."""
    if not runtime.cognitive_skill_catalog:
        raise HTTPException(503, "Cognitive skill catalog not available")
    try:
        entry = await runtime.cognitive_skill_catalog.enrich_skill(name, body)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "enriched": True,
        "name": entry.name,
        "department": entry.department,
        "skill_id": entry.skill_id,
        "min_proficiency": entry.min_proficiency,
        "min_rank": entry.min_rank,
        "intents": entry.intents,
    }


# --- AD-596e: Skill Validation endpoints ---


def _build_validation_context(runtime: Any) -> dict:
    """Build validation cross-reference context from runtime."""
    ctx: dict = {}

    # Valid departments from standing_orders
    from probos.cognitive.standing_orders import _AGENT_DEPARTMENTS

    ctx["valid_departments"] = set(_AGENT_DEPARTMENTS.values()) | {"*"}

    # Valid ranks from skill_catalog
    from probos.cognitive.skill_catalog import _RANK_ORDER

    ctx["valid_ranks"] = set(_RANK_ORDER.keys())

    # Valid skill_ids from registry
    if runtime.skill_registry:
        ctx["valid_skill_ids"] = {s.skill_id for s in runtime.skill_registry.list_skills()}

    # Known callsigns
    if runtime.callsign_registry:
        ctx["known_callsigns"] = set(runtime.callsign_registry.all_callsigns().values())

    return ctx


@router.get("/catalog/{name}/validate")
async def catalog_validate_single(
    name: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Validate a single cognitive skill."""
    if not runtime.cognitive_skill_catalog:
        raise HTTPException(503, "Cognitive skill catalog not available")

    ctx = _build_validation_context(runtime)
    result = await runtime.cognitive_skill_catalog.validate_skill(name, ctx)
    return {
        "results": [result.to_dict()],
        "summary": {
            "total": 1,
            "valid": 1 if result.valid else 0,
            "invalid": 0 if result.valid else 1,
        },
    }


@router.get("/catalog/validate")
async def catalog_validate_all(
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Validate all cognitive skills."""
    if not runtime.cognitive_skill_catalog:
        raise HTTPException(503, "Cognitive skill catalog not available")

    ctx = _build_validation_context(runtime)
    results = await runtime.cognitive_skill_catalog.validate_all(ctx)
    valid_count = sum(1 for r in results if r.valid)
    return {
        "results": [r.to_dict() for r in results],
        "summary": {
            "total": len(results),
            "valid": valid_count,
            "invalid": len(results) - valid_count,
        },
    }
