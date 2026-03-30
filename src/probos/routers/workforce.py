"""ProbOS API — Workforce Scheduling Engine routes (AD-496, AD-498)."""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request

from probos.routers.deps import get_runtime, get_ws_broadcast

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["workforce"])


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
    broadcast: Callable = Depends(get_ws_broadcast),
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
        raise HTTPException(404, str(e))
    broadcast({"type": "work_item_created", "data": {"work_item": item.to_dict()}})
    return {"work_item": item.to_dict()}


# -- Work Items (AD-496) --


@router.post("/work-items")
async def create_work_item(
    request: Request,
    runtime: Any = Depends(get_runtime),
    broadcast: Callable = Depends(get_ws_broadcast),
) -> dict[str, Any]:
    """Create a new work item."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    item = await runtime.work_item_store.create_work_item(**body)
    broadcast({"type": "work_item_created", "data": {"work_item": item.to_dict()}})
    return {"work_item": item.to_dict()}


@router.get("/work-items")
async def list_work_items(
    status: str | None = None,
    assigned_to: str | None = None,
    work_type: str | None = None,
    parent_id: str | None = None,
    priority: int | None = None,
    limit: int = 50,
    offset: int = 0,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """List work items with filters."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    items = await runtime.work_item_store.list_work_items(
        status=status, assigned_to=assigned_to, work_type=work_type,
        parent_id=parent_id, priority=priority, limit=limit, offset=offset,
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
    broadcast: Callable = Depends(get_ws_broadcast),
) -> dict[str, Any]:
    """Update work item fields."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    item = await runtime.work_item_store.update_work_item(work_item_id, **body)
    if not item:
        raise HTTPException(404, "Work item not found")
    broadcast({"type": "work_item_updated", "data": {"work_item": item.to_dict()}})
    return {"work_item": item.to_dict()}


@router.post("/work-items/{work_item_id}/transition")
async def transition_work_item(
    work_item_id: str,
    request: Request,
    runtime: Any = Depends(get_runtime),
    broadcast: Callable = Depends(get_ws_broadcast),
) -> dict[str, Any]:
    """Transition work item status."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    item = await runtime.work_item_store.transition_work_item(
        work_item_id, body["status"], source=body.get("source", "captain"),
    )
    if not item:
        raise HTTPException(404, "Work item not found or invalid transition")
    broadcast({"type": "work_item_updated", "data": {"work_item": item.to_dict()}})
    return {"work_item": item.to_dict()}


@router.post("/work-items/{work_item_id}/assign")
async def assign_work_item(
    work_item_id: str,
    request: Request,
    runtime: Any = Depends(get_runtime),
    broadcast: Callable = Depends(get_ws_broadcast),
) -> dict[str, Any]:
    """Push assignment: assign work to a specific agent."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    booking = await runtime.work_item_store.assign_work_item(
        work_item_id, body["resource_id"], source=body.get("source", "captain"),
    )
    if not booking:
        raise HTTPException(400, "Assignment failed (ineligible or no capacity)")
    # Re-fetch work item to get updated assigned_to
    wi = await runtime.work_item_store.get_work_item(work_item_id)
    broadcast({"type": "work_item_assigned", "data": {"work_item": wi.to_dict() if wi else {}, "booking": booking.to_dict()}})
    return {"booking": booking.to_dict()}


@router.post("/work-items/claim")
async def claim_work_item(
    request: Request,
    runtime: Any = Depends(get_runtime),
    broadcast: Callable = Depends(get_ws_broadcast),
) -> dict[str, Any]:
    """Pull assignment: agent claims highest-priority eligible work."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    result = await runtime.work_item_store.claim_work_item(
        body["resource_id"],
        work_type=body.get("work_type"),
        department=body.get("department"),
    )
    if not result:
        raise HTTPException(404, "No eligible work items")
    work_item, booking = result
    broadcast({"type": "work_item_assigned", "data": {"work_item": work_item.to_dict(), "booking": booking.to_dict()}})
    return {"work_item": work_item.to_dict(), "booking": booking.to_dict()}


@router.delete("/work-items/{work_item_id}")
async def delete_work_item(
    work_item_id: str,
    runtime: Any = Depends(get_runtime),
    broadcast: Callable = Depends(get_ws_broadcast),
) -> dict[str, Any]:
    """Delete a work item."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    deleted = await runtime.work_item_store.delete_work_item(work_item_id)
    if not deleted:
        raise HTTPException(404, "Work item not found")
    broadcast({"type": "work_item_deleted", "data": {"work_item_id": work_item_id}})
    return {"deleted": True}


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
