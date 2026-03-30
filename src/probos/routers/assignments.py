"""ProbOS API — Assignment routes (AD-408)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.api_models import CreateAssignmentRequest, ModifyMembersRequest
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assignments", tags=["assignments"])


@router.get("")
async def list_assignments(status: str = "active", runtime: Any = Depends(get_runtime)):
    if not runtime.assignment_service:
        return {"assignments": []}
    assignments = await runtime.assignment_service.list_assignments(status=status)
    return {"assignments": [vars(a) for a in assignments]}


@router.post("")
async def create_assignment(req: CreateAssignmentRequest, runtime: Any = Depends(get_runtime)):
    if not runtime.assignment_service:
        raise HTTPException(503, "Assignment service not available")
    try:
        assignment = await runtime.assignment_service.create_assignment(
            name=req.name,
            assignment_type=req.assignment_type,
            created_by=req.created_by,
            members=req.members,
            mission=req.mission,
        )
        return vars(assignment)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{assignment_id}")
async def get_assignment(assignment_id: str, runtime: Any = Depends(get_runtime)):
    if not runtime.assignment_service:
        raise HTTPException(503, "Assignment service not available")
    assignment = await runtime.assignment_service.get_assignment(assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    return vars(assignment)


@router.post("/{assignment_id}/members")
async def modify_assignment_members(assignment_id: str, req: ModifyMembersRequest, runtime: Any = Depends(get_runtime)):
    if not runtime.assignment_service:
        raise HTTPException(503, "Assignment service not available")
    try:
        if req.action == "remove":
            assignment = await runtime.assignment_service.remove_member(assignment_id, req.agent_id)
        else:
            assignment = await runtime.assignment_service.add_member(assignment_id, req.agent_id)
        return vars(assignment)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{assignment_id}/complete")
async def complete_assignment(assignment_id: str, runtime: Any = Depends(get_runtime)):
    if not runtime.assignment_service:
        raise HTTPException(503, "Assignment service not available")
    try:
        assignment = await runtime.assignment_service.complete_assignment(assignment_id)
        return vars(assignment)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{assignment_id}")
async def dissolve_assignment(assignment_id: str, runtime: Any = Depends(get_runtime)):
    if not runtime.assignment_service:
        raise HTTPException(503, "Assignment service not available")
    try:
        assignment = await runtime.assignment_service.dissolve_assignment(assignment_id)
        return vars(assignment)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/agent/{agent_id}")
async def agent_assignments(agent_id: str, runtime: Any = Depends(get_runtime)):
    if not runtime.assignment_service:
        return {"assignments": []}
    assignments = await runtime.assignment_service.get_agent_assignments(agent_id)
    return {"assignments": [vars(a) for a in assignments]}
