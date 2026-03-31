"""ProbOS API — Design routes (AD-308)."""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, Depends

from probos.api_models import BuildRequest, DesignApproveRequest, DesignRequest
from probos.events import EventType
from probos.routers.deps import get_pending_designs, get_runtime, get_task_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/design", tags=["design"])


@router.post("/submit")
async def submit_design(
    req: DesignRequest,
    runtime: Any = Depends(get_runtime),
    track_task: Callable = Depends(get_task_tracker),
    pending_designs: dict = Depends(get_pending_designs),
) -> dict[str, Any]:
    """Start async architectural design. Progress via WebSocket events."""
    import uuid
    design_id = uuid.uuid4().hex[:12]
    track_task(
        _run_design(req, design_id, runtime, pending_designs),
        name=f"design-{design_id}",
    )
    return {
        "status": "started",
        "design_id": design_id,
        "message": f"Design request for '{req.feature}' started...",
    }


@router.post("/approve")
async def approve_design(
    req: DesignApproveRequest,
    runtime: Any = Depends(get_runtime),
    track_task: Callable = Depends(get_task_tracker),
    pending_designs: dict = Depends(get_pending_designs),
) -> dict[str, Any]:
    """Approve architect proposal — forwards embedded BuildSpec to builder."""
    if req.design_id not in pending_designs:
        return {"status": "error", "message": f"Design {req.design_id} not found or already processed"}

    proposal_data = pending_designs.pop(req.design_id)
    build_spec = proposal_data["build_spec"]

    import uuid
    from probos.routers.build import _run_build
    build_id = uuid.uuid4().hex[:12]
    build_req = BuildRequest(
        title=build_spec.get("title", ""),
        description=build_spec.get("description", ""),
        target_files=build_spec.get("target_files", []),
        reference_files=build_spec.get("reference_files", []),
        test_files=build_spec.get("test_files", []),
        ad_number=build_spec.get("ad_number", 0),
        constraints=build_spec.get("constraints", []),
    )
    track_task(_run_build(build_req, build_id, runtime), name=f"build-{build_id}")

    return {
        "status": "forwarded",
        "design_id": req.design_id,
        "build_id": build_id,
        "message": f"Proposal approved — forwarded to Builder (build_id: {build_id})",
    }


async def _run_design(
    req: DesignRequest,
    design_id: str,
    rt: Any,
    pending_designs: dict,
) -> None:
    """Background design pipeline with WebSocket progress events."""
    try:
        rt._emit_event(EventType.DESIGN_STARTED, {
            "design_id": design_id,
            "feature": req.feature,
            "message": f"Architect analyzing: {req.feature}...",
        })

        rt._emit_event(EventType.DESIGN_PROGRESS, {
            "design_id": design_id,
            "step": "surveying",
            "step_label": "\u2609 Surveying codebase...",
            "current": 1,
            "total": 3,
            "message": "\u2609 Surveying codebase and roadmap...",
        })

        rt._emit_event(EventType.DESIGN_PROGRESS, {
            "design_id": design_id,
            "step": "designing",
            "step_label": "\u2b21 Designing specification...",
            "current": 2,
            "total": 3,
            "message": "\u2b21 Generating architectural proposal via deep LLM...",
        })

        from probos.types import IntentMessage
        intent = IntentMessage(
            intent="design_feature",
            params={
                "feature": req.feature,
                "phase": req.phase,
            },
            ttl_seconds=600.0,
        )

        results = await rt.intent_bus.broadcast(intent)

        design_result = None
        for r in results:
            if r and r.success and r.result:
                design_result = r
                break

        if not design_result or not design_result.result:
            error_msg = "ArchitectAgent returned no results"
            if results:
                errors = [r.error for r in results if r and r.error]
                if errors:
                    error_msg = "; ".join(errors)
            rt._emit_event(EventType.DESIGN_FAILURE, {
                "design_id": design_id,
                "message": f"Design failed: {error_msg}",
                "error": error_msg,
            })
            return

        rt._emit_event(EventType.DESIGN_PROGRESS, {
            "design_id": design_id,
            "step": "review",
            "step_label": "\u25ce Ready for review",
            "current": 3,
            "total": 3,
            "message": "\u25ce Proposal ready — awaiting Captain review",
        })

        result_data = design_result.result
        if isinstance(result_data, str):
            import json as _json
            try:
                result_data = _json.loads(result_data)
            except Exception:
                logger.debug("Design context failed", exc_info=True)
                result_data = {"proposal": {}, "llm_output": result_data}

        proposal = result_data.get("proposal", {})
        llm_output = result_data.get("llm_output", "")

        # Store proposal for later approval
        pending_designs[design_id] = {
            "proposal": proposal,
            "build_spec": proposal.get("build_spec", {}),
        }

        rt._emit_event(EventType.DESIGN_GENERATED, {
            "design_id": design_id,
            "title": proposal.get("title", req.feature),
            "summary": proposal.get("summary", ""),
            "rationale": proposal.get("rationale", ""),
            "roadmap_ref": proposal.get("roadmap_ref", ""),
            "priority": proposal.get("priority", "medium"),
            "dependencies": proposal.get("dependencies", []),
            "risks": proposal.get("risks", []),
            "build_spec": proposal.get("build_spec", {}),
            "llm_output": llm_output,
            "message": f"Architect proposes: {proposal.get('title', req.feature)} — review and approve to forward to Builder.",
        })

    except Exception as e:
        logger.warning("Design pipeline failed: %s", e, exc_info=True)
        rt._emit_event(EventType.DESIGN_FAILURE, {
            "design_id": design_id,
            "message": f"Design failed: {e}",
            "error": str(e),
        })
