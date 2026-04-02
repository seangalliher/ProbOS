"""AD-536/537/538: Procedure promotion governance, observational learning, and lifecycle API endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from probos.routers.deps import get_runtime

router = APIRouter(prefix="/api/procedures", tags=["procedures"])
logger = logging.getLogger(__name__)


class RejectRequest(BaseModel):
    reason: str


class ApproveRequest(BaseModel):
    message: str = ""


class TeachRequest(BaseModel):
    procedure_id: str
    target_callsign: str


@router.get("/pending")
async def list_pending(
    department: str | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """List pending promotion requests."""
    store = runtime.procedure_store
    if not store:
        return {"pending": [], "count": 0}
    pending = await store.get_pending_promotions(department=department)
    return {"pending": pending, "count": len(pending)}


@router.post("/{procedure_id}/approve")
async def approve_promotion(
    procedure_id: str,
    body: ApproveRequest | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """Approve a procedure promotion."""
    store = runtime.procedure_store
    if not store:
        return {"success": False, "error": "ProcedureStore not available"}

    status = await store.get_promotion_status(procedure_id)
    if status != "pending":
        return {"success": False, "error": f"Procedure is not pending (status: {status})"}

    procedure = await store.get(procedure_id)
    if not procedure:
        return {"success": False, "error": "Procedure not found"}

    # Create RuntimeDirective
    directive_store = runtime.directive_store
    if not directive_store:
        return {"success": False, "error": "DirectiveStore not available"}

    from probos.crew_profile import Rank
    from probos.directive_store import DirectiveType

    quality = await store.get_quality_metrics(procedure_id)
    effective_rate = quality.get("effective_rate", 0) if quality else 0
    total_comp = quality.get("total_completions", 0) if quality else 0
    steps_text = "\n".join(f"  {s.step_number}. {s.action}" for s in procedure.steps)

    content = (
        f"When handling {', '.join(procedure.intent_types) or 'related tasks'}, "
        f"follow these steps:\n{steps_text}\n"
        f"This procedure was validated through {total_comp} completions "
        f"with {effective_rate:.0%} success rate. "
        f"Origin: {', '.join(procedure.origin_agent_ids) or 'system'}."
    )

    agent_type = procedure.origin_agent_ids[0] if procedure.origin_agent_ids else "*"
    department = None
    if runtime.ontology:
        department = runtime.ontology.get_agent_department(agent_type)

    directive, reason = directive_store.create_directive(
        issuer_type="captain",
        issuer_department=None,
        issuer_rank=Rank.SENIOR,
        target_agent_type=agent_type,
        target_department=department,
        directive_type=DirectiveType.CAPTAIN_ORDER,
        content=content,
        authority=1.0,
        priority=3,
    )

    if not directive:
        return {"success": False, "error": f"Directive creation failed: {reason}"}

    await store.approve_promotion(procedure_id, "captain", directive.id)

    return {
        "success": True,
        "procedure_id": procedure_id,
        "directive_id": directive.id,
        "procedure_name": procedure.name,
    }


@router.post("/{procedure_id}/reject")
async def reject_promotion(
    procedure_id: str,
    body: RejectRequest,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """Reject a procedure promotion with feedback."""
    store = runtime.procedure_store
    if not store:
        return {"success": False, "error": "ProcedureStore not available"}

    status = await store.get_promotion_status(procedure_id)
    if status != "pending":
        return {"success": False, "error": f"Procedure is not pending (status: {status})"}

    await store.reject_promotion(procedure_id, "captain", body.reason)

    return {
        "success": True,
        "procedure_id": procedure_id,
        "reason": body.reason,
    }


@router.get("/promoted")
async def list_promoted(
    runtime: Any = Depends(get_runtime),
) -> dict:
    """List all promoted (approved) procedures."""
    store = runtime.procedure_store
    if not store:
        return {"promoted": [], "count": 0}
    promoted = await store.get_promoted_procedures()
    return {"promoted": promoted, "count": len(promoted)}


@router.post("/teach")
async def teach_procedure(
    body: TeachRequest,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """AD-537: Teach a Level 5 procedure to another agent via Ward Room DM."""
    store = runtime.procedure_store
    if not store:
        return {"success": False, "error": "ProcedureStore not available"}

    from probos.config import TEACHING_MIN_COMPILATION_LEVEL

    # Validate procedure exists
    procedure = await store.get(body.procedure_id)
    if not procedure:
        return {"success": False, "error": "Procedure not found"}

    # Must be Level 5
    if procedure.compilation_level < TEACHING_MIN_COMPILATION_LEVEL:
        return {
            "success": False,
            "error": f"Procedure must be Level {TEACHING_MIN_COMPILATION_LEVEL}+ "
                     f"(current: Level {procedure.compilation_level})",
        }

    # Must be approved
    status = await store.get_promotion_status(body.procedure_id)
    if status != "approved":
        return {"success": False, "error": f"Procedure not approved (status: {status})"}

    # Send teaching DM
    if not hasattr(runtime, "ward_room") or not runtime.ward_room:
        return {"success": False, "error": "Ward Room not available"}

    quality = await store.get_quality_metrics(body.procedure_id)
    total_comp = quality.get("total_completions", 0) if quality else 0
    effective_rate = quality.get("effective_rate", 0) if quality else 0
    steps_text = "\n".join(f"  {s.step_number}. {s.action}" for s in procedure.steps)

    dm_body = (
        f"**[TEACHING] Procedure: {procedure.name}**\n\n"
        f"Validated through {total_comp} executions with {effective_rate:.0%} success rate.\n\n"
        f"**Description:** {procedure.description}\n\n"
        f"**Steps:**\n{steps_text}\n\n"
        f"Institutionally approved and promoted to Expert level."
    )

    try:
        dm_channel = await runtime.ward_room.get_or_create_dm_channel(
            "captain", body.target_callsign,
            callsign_a="captain", callsign_b=body.target_callsign,
        )
        await runtime.ward_room.create_thread(
            channel_id=dm_channel.id,
            author_id="captain",
            title=f"[TEACHING] {procedure.name}",
            body=dm_body,
            author_callsign="captain",
        )
    except Exception as e:
        return {"success": False, "error": f"Teaching DM failed: {e}"}

    return {
        "success": True,
        "procedure_id": body.procedure_id,
        "procedure_name": procedure.name,
        "target": body.target_callsign,
    }


@router.get("/observed")
async def list_observed(
    agent: str | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """AD-537: List observed/taught procedures."""
    store = runtime.procedure_store
    if not store:
        return {"observed": [], "count": 0}
    observed = await store.get_observed_procedures(agent=agent)
    return {"observed": observed, "count": len(observed)}


# ------------------------------------------------------------------
# AD-538: Lifecycle endpoints
# ------------------------------------------------------------------


class RestoreRequest(BaseModel):
    procedure_id: str


class MergeRequest(BaseModel):
    primary_id: str
    duplicate_id: str


@router.get("/stale")
async def list_stale(
    days: int | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """AD-538: List stale procedures that would be decayed."""
    store = runtime.procedure_store
    if not store:
        return {"stale": [], "count": 0}
    stale = await store.get_stale_procedures(days=days)
    return {"stale": stale, "count": len(stale)}


@router.get("/archived")
async def list_archived(
    limit: int = 20,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """AD-538: List archived procedures."""
    store = runtime.procedure_store
    if not store:
        return {"archived": [], "count": 0}
    archived = await store.get_archived_procedures(limit=limit)
    return {"archived": archived, "count": len(archived)}


@router.post("/restore")
async def restore_procedure(
    body: RestoreRequest,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """AD-538: Restore an archived procedure."""
    store = runtime.procedure_store
    if not store:
        return {"success": False, "error": "ProcedureStore not available"}

    success = await store.restore_procedure(body.procedure_id)
    if not success:
        return {"success": False, "error": "Procedure not found or not archived"}

    proc = await store.get(body.procedure_id)
    return {
        "success": True,
        "procedure_id": body.procedure_id,
        "procedure_name": proc.name if proc else "",
    }


@router.get("/duplicates")
async def list_duplicates(
    runtime: Any = Depends(get_runtime),
) -> dict:
    """AD-538: List duplicate procedure candidates."""
    store = runtime.procedure_store
    if not store:
        return {"duplicates": [], "count": 0}
    candidates = await store.find_duplicate_candidates()
    return {"duplicates": candidates, "count": len(candidates)}


@router.post("/merge")
async def merge_procedures(
    body: MergeRequest,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """AD-538: Merge duplicate procedure into primary."""
    store = runtime.procedure_store
    if not store:
        return {"success": False, "error": "ProcedureStore not available"}

    primary = await store.get(body.primary_id)
    if not primary:
        return {"success": False, "error": f"Primary procedure {body.primary_id} not found"}

    duplicate = await store.get(body.duplicate_id)
    if not duplicate:
        return {"success": False, "error": f"Duplicate procedure {body.duplicate_id} not found"}

    success = await store.merge_procedures(body.primary_id, body.duplicate_id)
    if not success:
        return {"success": False, "error": "Merge failed — ensure both procedures are active"}

    metrics = await store.get_quality_metrics(body.primary_id)
    return {
        "success": True,
        "primary_id": body.primary_id,
        "primary_name": primary.name,
        "duplicate_id": body.duplicate_id,
        "duplicate_name": duplicate.name,
        "combined_completions": metrics.get("total_completions", 0) if metrics else 0,
    }
