"""ProbOS API — Workforce Scheduling Engine routes (AD-496, AD-498)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import TypeAdapter, ValidationError

from probos import work_item_steps as owned_steps
from probos.routers.auth import require_crew_scope
from probos.routers.deps import (
    WebSocketBroadcast,
    broadcast_ws_event,
    get_runtime,
    get_ws_broadcast,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["workforce"])


def _raise_if_crew_session_write_reserved(exc: ValueError) -> None:
    if str(exc) == "crew_session_write_reserved":
        raise HTTPException(409, "crew_session_write_reserved") from exc


def _owned_steps_http_error(exc: owned_steps.OwnedStepsError) -> HTTPException:
    if exc.code in {
        "owned_steps_parent_missing",
        "owned_steps_row_missing",
        "owned_steps_not_managed",
    }:
        status_code = 404
    elif exc.code in {
        "owned_steps_authority_denied",
        "owned_steps_actual_context_invalid",
        "owned_steps_scope_conflict",
        "owned_steps_view_scope_conflict",
    }:
        status_code = 403
    elif exc.code in {
        "owned_steps_unavailable",
        "owned_steps_view_unavailable",
        "owned_steps_finalization_unavailable",
    }:
        status_code = 503
    else:
        status_code = 409
    return HTTPException(
        status_code,
        {
            "code": exc.code,
            "message": exc.message,
            "parent_id": exc.parent_id,
            "view_id": exc.view_id,
            "actions": list(exc.actions),
            "feedback": owned_steps.render_owned_steps_feedback(exc),
        },
    )


def _owned_steps_owner(runtime: Any) -> tuple[Any, Any]:
    owner = getattr(runtime, "crew_orchestrator", None)
    service = getattr(runtime, "crew_session_service", None)
    if owner is None or service is None:
        raise HTTPException(503, "owned_steps_owner_unavailable")
    return owner, service


async def _owned_steps_request_json(
    request: Request,
    model: type[Any],
) -> Any:
    try:
        body = await request.body()
        if len(body) > owned_steps.MAX_OWNED_PUBLIC_RESPONSE_BYTES:
            raise ValueError("owned_steps_request_too_large")
        return TypeAdapter(model).validate_json(body)
    except (ValidationError, ValueError, TypeError) as exc:
        raise HTTPException(
            422,
            {
                "code": "owned_steps_request_invalid",
                "message": "Owned steps request is invalid.",
            },
        ) from exc


async def build_ws_workforce_snapshot(
    runtime: Any,
    *,
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    """Build a bounded WebSocket workforce view without CrewSession rows."""
    store = getattr(runtime, "work_item_store", None)
    if store is None:
        return {"work_items": [], "bookings": [], "resources": []}
    visible_items = await store.list_ws_visible_work_items(limit=limit)
    if len(visible_items) > limit:
        raise ValueError("ws_workforce_source_overflow")
    return {
        "work_items": [item.to_dict() for item in visible_items],
        "bookings": [],
        "resources": [],
    }


# -- Work Type Registry & Templates (AD-498) --


@router.get("/work-types")
async def list_work_types(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """List registered work types."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    types = runtime.work_item_store.work_type_registry.list_types()
    return {"work_types": [wt.to_dict() for wt in types]}


@router.get("/work-types/{type_id}")
async def get_work_type(type_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Get work type definition."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    wt = runtime.work_item_store.work_type_registry.get(type_id)
    if not wt:
        raise HTTPException(404, f"Work type '{type_id}' not found")
    return {"work_type": wt.to_dict()}


@router.get("/work-types/{type_id}/transitions")
async def get_work_type_transitions(
    type_id: str, from_status: str = "open", runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Get valid transitions for a work type from a given status."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    wt = runtime.work_item_store.work_type_registry.get(type_id)
    if not wt:
        raise HTTPException(404, f"Work type '{type_id}' not found")
    targets = runtime.work_item_store.work_type_registry.get_valid_targets(type_id, from_status)
    return {"type_id": type_id, "from_status": from_status, "valid_targets": targets}


@router.get("/templates")
async def list_templates(
    category: str | None = None, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """List work item templates."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    templates = runtime.work_item_store.template_store.list_templates(category)
    return {"templates": [t.to_dict() for t in templates]}


@router.get("/templates/{template_id}")
async def get_template(template_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Get template details."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    t = runtime.work_item_store.template_store.get(template_id)
    if not t:
        raise HTTPException(404, f"Template '{template_id}' not found")
    return {"template": t.to_dict()}


@router.post("/work-items/from-template/{template_id}")
async def create_from_template(
    template_id: str,
    request: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Create work item from template."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    try:
        item = await runtime.work_item_store.create_from_template(
            template_id,
            variables=body.get("variables"),
            overrides=body.get("overrides"),
            created_by=body.get("created_by", "captain"),
        )
    except ValueError as e:
        _raise_if_crew_session_write_reserved(e)
        raise HTTPException(404, str(e))
    return {"work_item": item.to_dict()}


# -- Work Items (AD-496) --


@router.post("/work-items")
async def create_work_item(
    request: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Create a new work item."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    try:
        item = await runtime.work_item_store.create_work_item(**body)
    except ValueError as exc:
        _raise_if_crew_session_write_reserved(exc)
        raise
    return {"work_item": item.to_dict()}


@router.get("/work-items")
async def list_work_items(
    status: str | None = None,
    assigned_to: str | None = None,
    work_type: str | None = None,
    parent_id: str | None = None,
    priority: int | None = None,
    project_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """List work items with filters."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    items = await runtime.work_item_store.list_work_items(
        status=status, assigned_to=assigned_to, work_type=work_type,
        parent_id=parent_id, priority=priority, project_id=project_id,
        limit=limit, offset=offset,
    )
    return {"work_items": [i.to_dict() for i in items], "count": len(items)}


@router.get("/work-items/{work_item_id}")
async def get_work_item(work_item_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Get a work item by ID."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    item = await runtime.work_item_store.get_work_item(work_item_id)
    if not item:
        raise HTTPException(404, "Work item not found")
    return {"work_item": item.to_dict()}


@router.patch("/work-items/{work_item_id}")
async def update_work_item(
    work_item_id: str,
    request: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Update work item fields."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    try:
        item = await runtime.work_item_store.update_work_item(work_item_id, **body)
    except ValueError as exc:
        _raise_if_crew_session_write_reserved(exc)
        raise
    if not item:
        raise HTTPException(404, "Work item not found")
    return {"work_item": item.to_dict()}


@router.post("/work-items/{work_item_id}/transition")
async def transition_work_item(
    work_item_id: str,
    request: Request,
    runtime: Any = Depends(get_runtime),
    broadcast: WebSocketBroadcast | None = Depends(get_ws_broadcast),
) -> dict[str, Any]:
    """Transition work item status."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    try:
        item = await runtime.work_item_store.transition_work_item(
            work_item_id, body["status"], source=body.get("source", "captain"),
        )
    except ValueError as exc:
        _raise_if_crew_session_write_reserved(exc)
        raise
    if not item:
        raise HTTPException(404, "Work item not found or invalid transition")
    broadcast_ws_event(
        broadcast,
        {"type": "work_item_updated", "data": {"work_item": item.to_dict()}},
    )
    return {"work_item": item.to_dict()}


@router.post("/work-items/{work_item_id}/assign")
async def assign_work_item(
    work_item_id: str,
    request: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Push assignment: assign work to a specific agent."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    try:
        booking = await runtime.work_item_store.assign_work_item(
            work_item_id,
            body["resource_id"],
            source=body.get("source", "captain"),
        )
    except ValueError as exc:
        _raise_if_crew_session_write_reserved(exc)
        raise
    if not booking:
        raise HTTPException(400, "Assignment failed (ineligible or no capacity)")
    return {"booking": booking.to_dict()}


@router.post("/work-items/claim")
async def claim_work_item(
    request: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Pull assignment: agent claims highest-priority eligible work."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    try:
        result = await runtime.work_item_store.claim_work_item(
            body["resource_id"],
            work_type=body.get("work_type"),
            department=body.get("department"),
        )
    except ValueError as exc:
        _raise_if_crew_session_write_reserved(exc)
        raise
    if not result:
        raise HTTPException(404, "No eligible work items")
    work_item, booking = result
    return {"work_item": work_item.to_dict(), "booking": booking.to_dict()}


# -- Todo checklist steps (AD-1080) --


@router.get("/work-items/{work_item_id}/steps")
async def get_work_item_steps(
    work_item_id: str,
    limit: int | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-1080: the work item's Todo checklist (the room plan + validation state)."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    item = await runtime.work_item_store.get_work_item(work_item_id)
    if not item:
        raise HTTPException(404, "Work item not found")
    steps = item.steps
    if limit is not None:
        steps = steps[:max(1, min(limit, 1001))]
    return {
        "steps": steps,
        "gate_completion": bool((item.metadata or {}).get("steps_gate_completion")),
    }


@router.get(
    "/work-items/{work_item_id}/owned-steps",
    dependencies=[Depends(require_crew_scope)],
)
async def get_owned_work_item_steps(
    work_item_id: str,
    cursor: str | None = None,
    detail: str | None = None,
    presentation_budget: int = owned_steps.MAX_OWNED_VIEW_BYTES,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Return one authenticated managed page or a known-unmanaged projection."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    try:
        parent_id = await runtime.work_item_store.resolve_owned_steps_parent_id(
            work_item_id
        )
        if parent_id is None:
            identity = (
                await runtime.work_item_store.read_owned_steps_raw_identity(
                    work_item_id
                )
            )
            if identity is None:
                raise HTTPException(404, "Work item not found")
            try:
                raw_steps = identity.raw_steps
                if raw_steps is None:
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_rows_invalid"
                    )
                spans = owned_steps.owned_row_spans(raw_steps)
                decoded = owned_steps.owned_json_loads(raw_steps)
            except owned_steps.OwnedStepsError as exc:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_repair_required",
                    parent_id=identity.parent_id,
                    actions=("inspect_source", "replace_manual_prefix"),
                ) from exc
            start = 0
            if cursor is not None:
                try:
                    start = int(cursor)
                except ValueError as exc:
                    raise HTTPException(422, "owned_steps_cursor_invalid") from exc
            if start < 0 or detail is not None:
                raise HTTPException(422, "owned_steps_cursor_invalid")
            rows = decoded[start:start + owned_steps.MAX_OWNED_VIEW_ROWS]
            response = {
                "version": 1,
                "mode": "unmanaged",
                "parent_id": identity.parent_id,
                "requested_item_id": work_item_id,
                "reference": None,
                "rows": [
                    {"ordinal": start + index + 1, "todo": row}
                    for index, row in enumerate(rows)
                ],
                "previous_cursor": (
                    str(max(0, start - owned_steps.MAX_OWNED_VIEW_ROWS))
                    if start
                    else None
                ),
                "next_cursor": (
                    str(start + len(rows))
                    if start + len(rows) < len(spans)
                    else None
                ),
                "recovery": [],
                "finalization": "none",
            }
            if (
                len(owned_steps.owned_json_bytes(response))
                > owned_steps.MAX_OWNED_PUBLIC_RESPONSE_BYTES
            ):
                raise HTTPException(413, "owned_steps_public_response_too_large")
            return response
        owner, service = _owned_steps_owner(runtime)
        turn_id = "http-owner"
        actual_context = await owner.owned_steps_actual_context(
            service.captain_principal(),
            work_item_id=work_item_id,
            turn_id=turn_id,
        )
        if detail is not None:
            return await owner.read_owned_steps_detail(
                actual_context,
                step_id=detail,
            )
        reference = await owner.capture_owned_steps_view(
            actual_context,
            requested_item_id=work_item_id,
            cursor=cursor,
            presentation_budget=presentation_budget,
        )
        view = await owner.admit_owned_steps_presentation(
            reference,
            actual_context,
        )
        response = view.model_dump(mode="json")
        response["reference"] = reference.model_dump(mode="json")
        if (
            len(owned_steps.owned_json_bytes(response))
            > owned_steps.MAX_OWNED_PUBLIC_RESPONSE_BYTES
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_public_response_too_large",
                parent_id=parent_id,
                view_id=reference.view_id,
            )
        return response
    except owned_steps.OwnedStepsError as exc:
        raise _owned_steps_http_error(exc) from exc


@router.post(
    "/work-items/{work_item_id}/owned-steps/preview",
    dependencies=[Depends(require_crew_scope)],
)
async def preview_owned_work_item_steps(
    work_item_id: str,
    request: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    owner, service = _owned_steps_owner(runtime)
    body = await _owned_steps_request_json(
        request,
        owned_steps.OwnedStepsProposalRequest,
    )
    try:
        if isinstance(body, owned_steps.InspectProposalRequest):
            turn_id = "http-owner"
            actual_context = await owner.owned_steps_repair_context(
                service.captain_principal(),
                work_item_id=work_item_id,
                turn_id=turn_id,
            )
        else:
            turn_id = body.reference.turn_id
            context_factory = (
                owner.owned_steps_repair_context
                if isinstance(body.reference, owned_steps.RepairReference)
                else owner.owned_steps_actual_context
            )
            actual_context = await context_factory(
                service.captain_principal(),
                work_item_id=work_item_id,
                turn_id=turn_id,
            )
        preview = await owner.prepare_owned_steps_proposal(
            body,
            actual_context,
        )
        return {"proposal": preview.model_dump(mode="json")}
    except owned_steps.OwnedStepsError as exc:
        raise _owned_steps_http_error(exc) from exc


@router.post(
    "/work-items/{work_item_id}/owned-steps/adopt",
    dependencies=[Depends(require_crew_scope)],
)
async def adopt_owned_work_item_steps(
    work_item_id: str,
    request: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    owner, service = _owned_steps_owner(runtime)
    body = await _owned_steps_request_json(
        request,
        owned_steps.OwnedStepsProposalApplyRequest,
    )
    try:
        actual_context = await owner.owned_steps_repair_context(
            service.captain_principal(),
            work_item_id=work_item_id,
            turn_id=body.reference.turn_id,
        )
        result = await owner.apply_owned_steps_proposal(
            body, actual_context, allowed_kinds=frozenset({"adopt_existing"}),
        )
        return {"disposition": result.disposition}
    except owned_steps.OwnedStepsError as exc:
        raise _owned_steps_http_error(exc) from exc


@router.get(
    "/work-items/{work_item_id}/owned-steps/repair",
    dependencies=[Depends(require_crew_scope)],
)
async def repair_owned_work_item_steps(
    work_item_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Capture raw projection/control evidence without parsing either value."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    owner, service = _owned_steps_owner(runtime)
    try:
        actual_context = await owner.owned_steps_repair_context(
            service.captain_principal(),
            work_item_id=work_item_id,
            turn_id="http-owner",
        )
        observation, reference = (
            await owner.capture_owned_steps_repair_observation(actual_context)
        )
        raw_steps = observation.raw_steps
        raw_control = observation.raw_control
        omissions: list[str] = []
        if (
            raw_steps is not None
            and len(raw_steps.encode("utf-8"))
            > owned_steps.MAX_OWNED_VIEW_BYTES
        ):
            raw_steps = None
            omissions.append("raw_steps")
        if (
            raw_control is not None
            and len(raw_control.encode("utf-8"))
            > owned_steps.MAX_OWNED_VIEW_BYTES
        ):
            raw_control = None
            omissions.append("raw_control")
        response = {
            "version": 1,
            "parent_id": observation.parent_id,
            "reference": reference.model_dump(mode="json"),
            "steps_digest": observation.steps_digest,
            "control_digest": observation.control_digest,
            "raw_steps": raw_steps,
            "raw_control": raw_control,
            "omissions": omissions,
            "actions": [
                "replace_manual_prefix",
                "replan_unstarted",
                "inspect_source",
            ],
        }
        if (
            len(owned_steps.owned_json_bytes(response))
            > owned_steps.MAX_OWNED_PUBLIC_RESPONSE_BYTES
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_public_response_too_large",
                parent_id=work_item_id,
            )
        return response
    except owned_steps.OwnedStepsError as exc:
        raise _owned_steps_http_error(exc) from exc


@router.post(
    "/work-items/{work_item_id}/owned-steps/commands",
    dependencies=[Depends(require_crew_scope)],
)
async def command_owned_work_item_steps(
    work_item_id: str,
    request: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    owner, service = _owned_steps_owner(runtime)
    body = await _owned_steps_request_json(
        request,
        owned_steps.OwnedStepsCommandsRequest,
    )
    body = body.root
    try:
        if isinstance(body, owned_steps.OwnedStepsProposalApplyRequest):
            actual_context = await owner.owned_steps_repair_context(
                service.captain_principal(), work_item_id=work_item_id,
                turn_id=body.reference.turn_id,
            )
            result = await owner.apply_owned_steps_proposal(
                body, actual_context,
                allowed_kinds=frozenset({"replace_manual_prefix", "replan_unstarted"}),
            )
            return {"disposition": result.disposition}
        actual_context = await owner.owned_steps_actual_context(
            service.captain_principal(),
            work_item_id=work_item_id,
            turn_id=body.reference.turn_id,
        )
        results = await owner.apply_owned_steps_commands(
            body,
            actual_context,
        )
        return {
            "results": [
                {
                    "operation_id": command.operation_id,
                    "disposition": result.disposition,
                }
                for command, result in zip(body.commands, results, strict=True)
            ]
        }
    except owned_steps.OwnedStepsError as exc:
        raise _owned_steps_http_error(exc) from exc


@router.post(
    "/work-items/{work_item_id}/owned-steps/finalize",
    dependencies=[Depends(require_crew_scope)],
)
async def finalize_owned_work_item_steps(
    work_item_id: str,
    request: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    owner, service = _owned_steps_owner(runtime)
    body = await _owned_steps_request_json(
        request,
        owned_steps.OwnedStepsFinalizeRequest,
    )
    try:
        actual_context = await owner.owned_steps_actual_context(
            service.captain_principal(),
            work_item_id=work_item_id,
            turn_id=body.reference.turn_id,
        )
        result = await owner.finalize_owned_steps(
            body.reference,
            actual_context,
        )
        return {
            "disposition": getattr(
                result,
                "disposition",
                "completed" if bool(getattr(result, "completed", False)) else "pending",
            )
        }
    except owned_steps.OwnedStepsError as exc:
        raise _owned_steps_http_error(exc) from exc


@router.put("/work-items/{work_item_id}/steps")
async def set_work_item_steps(
    work_item_id: str, request: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-1080: seed/replace the Todo checklist (the room plan)."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    item = await runtime.work_item_store.set_steps(
        work_item_id, body.get("steps", []),
        gate_completion=bool(body.get("gate_completion", False)),
    )
    if not item:
        raise HTTPException(404, "Work item not found")
    return {"work_item": item.to_dict()}


@router.patch("/work-items/{work_item_id}/steps/{index}")
async def update_work_item_step(
    work_item_id: str, index: int, request: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-1080: transition one Todo step (submit / confirm / reject — the
    senior-validation loop)."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    item = await runtime.work_item_store.update_step(
        work_item_id, index,
        status=body.get("status"), actor=body.get("actor"), note=body.get("note"),
    )
    if not item:
        raise HTTPException(400, "Work item not found, bad index, or invalid step transition")
    return {"work_item": item.to_dict()}


@router.delete("/work-items/{work_item_id}")
async def delete_work_item(
    work_item_id: str,
    runtime: Any = Depends(get_runtime),
    broadcast: WebSocketBroadcast | None = Depends(get_ws_broadcast),
) -> dict[str, Any]:
    """Delete a work item."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    deleted = await runtime.work_item_store.delete_work_item(work_item_id)
    if not deleted:
        raise HTTPException(404, "Work item not found")
    broadcast_ws_event(
        broadcast,
        {"type": "work_item_deleted", "data": {"work_item_id": work_item_id}},
    )
    return {"deleted": True}


@router.post("/work-items/{work_item_id}/inputs")
async def attach_work_item_inputs(
    work_item_id: str,
    files: list[UploadFile] = File(...),
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-926a: attach one or more context-input files to a work item (task).

    The WRITE/population path for the AD-926 ``input_attachments`` convention.
    Each file is validated + stored once in the content-addressable
    ``AttachmentStore`` (sha256) via the SHARED chat uploader
    (``_validate_and_store_attachment`` — same defense-in-depth gate, default
    ``origin="chat_attachment"`` = operator intent, never age-reaped), then a
    ref ``{content_hash, mime, filename}`` is appended to the parent
    ``WorkItem.metadata["input_attachments"]``. The files then surface as the
    task room's Inputs via the existing ``GET /api/threads/{id}/inputs``.

    Operator/Captain action: reversible, additive, low-risk — no consensus
    gate (Safety Budget axiom), mirroring the other work-item mutation routes
    (PATCH / transition / assign / delete have no per-caller authority check).

    Honest-degrade per file: a rejected file (oversize / mime mismatch /
    disallowed) is collected into ``skipped`` rather than failing the request.
    A single owned-key merge per request (all files stored first, then one
    store-owned metadata merge) preserves every other ``metadata`` key plus any existing
    inputs and dedupes by ``content_hash``.
    """
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    wi = await runtime.work_item_store.get_work_item(work_item_id)
    if not wi:
        raise HTTPException(404, "Work item not found")

    from probos.routers.chat import _validate_and_store_attachment

    new_refs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for f in files:
        blob = await f.read()
        ok, result = await _validate_and_store_attachment(
            runtime,
            blob,
            f.content_type or "application/octet-stream",
            declared_filename=f.filename,
            declared_hash_or_None=None,
        )
        if not ok:
            skipped.append({
                "filename": f.filename,
                "error": (result.get("body") or {}).get("error", "rejected"),
            })
            continue
        new_refs.append({
            "content_hash": result["sha256"],
            "mime": result["mime"],
            "filename": f.filename,
        })

    # Single owned-key merge: preserve every unrelated top-level metadata key
    # while appending inputs and deduping by content_hash.
    if new_refs:
        existing = list(
            (getattr(wi, "metadata", {}) or {}).get("input_attachments", []) or []
        )
        seen = {
            r.get("content_hash")
            for r in existing
            if isinstance(r, dict)
        }
        for ref in new_refs:
            if ref["content_hash"] not in seen:
                existing.append(ref)
                seen.add(ref["content_hash"])
        updated = await runtime.work_item_store.merge_work_item_metadata(
            work_item_id, {"input_attachments": existing},
        )
        wi = updated or wi

    # Return the task-level input list (mirrors the AD-926 read shape,
    # source="task"). size is best-effort from the content-addressable store.
    attachment_store = getattr(runtime, "attachment_store", None)
    inputs: list[dict[str, Any]] = []
    for ref in (getattr(wi, "metadata", {}) or {}).get("input_attachments", []) or []:
        if not isinstance(ref, dict):
            continue
        ch = ref.get("content_hash")
        size: int | None = None
        if attachment_store is not None and ch:
            try:
                size = await attachment_store.size(ch)
            except Exception:  # pragma: no cover - defensive, Tier-2
                size = None
        inputs.append({
            "content_hash": ch,
            "mime": ref.get("mime") or "application/octet-stream",
            "filename": ref.get("filename"),
            "size": size,
            "source": "task",
        })

    return {"work_item_id": work_item_id, "inputs": inputs, "skipped": skipped}


# -- Bookings --


@router.get("/bookings")
async def list_bookings(
    resource_id: str | None = None,
    work_item_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """List bookings with filters."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    bookings = await runtime.work_item_store.list_bookings(
        resource_id=resource_id, work_item_id=work_item_id, status=status, limit=limit,
    )
    return {"bookings": [b.to_dict() for b in bookings], "count": len(bookings)}


@router.get("/bookings/{booking_id}/journal")
async def get_booking_journal(booking_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Get time/token segments for a booking."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    entries = await runtime.work_item_store.get_booking_journal(booking_id)
    return {"journal": [e.to_dict() for e in entries]}


# -- Resources --


@router.get("/resources")
async def list_resources(
    department: str | None = None,
    resource_type: str | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """List bookable resources."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    resources = runtime.work_item_store.list_resources(
        department=department, resource_type=resource_type,
    )
    return {"resources": [r.to_dict() for r in resources], "count": len(resources)}


@router.get("/resources/{resource_id}/availability")
async def get_resource_availability(
    resource_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Get resource availability (capacity minus active bookings)."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    availability = runtime.work_item_store.get_resource_availability(resource_id)
    if not availability:
        raise HTTPException(404, "Resource not found")
    return availability
