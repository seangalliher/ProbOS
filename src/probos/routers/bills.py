"""ProbOS API — Bill System routes (AD-618d)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bills", tags=["bills"])


def _get_bill_runtime(runtime: Any) -> Any:
    """Extract BillRuntime, return None if unavailable."""
    return getattr(runtime, "_bill_runtime", None)


# ── Request models ───────────────────────────────────────────────


class ActivateBillRequest(BaseModel):
    """Request body for bill activation."""

    bill_id: str
    context: dict[str, Any] = {}


class CancelBillRequest(BaseModel):
    """Request body for bill cancellation."""

    reason: str = ""


# ── Bill Definitions (catalog) ───────────────────────────────────


@router.get("/definitions")
async def list_bill_definitions(runtime: Any = Depends(get_runtime)) -> Any:
    """List all loaded bill definitions (built-in + custom)."""
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    definitions = br.list_definitions()
    return {
        "definitions": [_serialize_definition(d) for d in definitions],
        "count": len(definitions),
    }


@router.get("/definitions/{bill_id}")
async def get_bill_definition(
    bill_id: str, runtime: Any = Depends(get_runtime),
) -> Any:
    """Get a specific bill definition by slug."""
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    defn = br.get_definition(bill_id)
    if not defn:
        return JSONResponse({"error": f"Bill '{bill_id}' not found"}, status_code=404)
    return _serialize_definition(defn)


# ── Bill Instances (active/completed) ────────────────────────────


@router.get("/instances")
async def list_bill_instances(
    status: str = "",
    bill_id: str = "",
    runtime: Any = Depends(get_runtime),
) -> Any:
    """List bill instances, optionally filtered by status or bill_id."""
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    from probos.sop.instance import InstanceStatus

    _status = None
    if status:
        try:
            _status = InstanceStatus(status)
        except ValueError:
            return JSONResponse(
                {"error": f"Invalid status '{status}'"}, status_code=400,
            )
    instances = br.list_instances(
        status=_status,
        bill_id=bill_id or None,
    )
    return {
        "instances": [i.to_dict() for i in instances],
        "count": len(instances),
    }


@router.get("/instances/{instance_id}")
async def get_bill_instance(
    instance_id: str, runtime: Any = Depends(get_runtime),
) -> Any:
    """Get detailed state of a specific bill instance."""
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    instance = br.get_instance(instance_id)
    if not instance:
        return JSONResponse(
            {"error": f"Instance '{instance_id}' not found"}, status_code=404,
        )
    return instance.to_dict()


@router.get("/instances/{instance_id}/assignments")
async def get_instance_assignments(
    instance_id: str, runtime: Any = Depends(get_runtime),
) -> Any:
    """Get role assignments for a bill instance (WQSB roster).

    Reads instance.role_assignments directly — NOT get_agent_assignments(),
    which takes an agent_id and returns "what bills is this agent in?"
    """
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    instance = br.get_instance(instance_id)
    if not instance:
        return JSONResponse(
            {"error": f"Instance '{instance_id}' not found"}, status_code=404,
        )
    assignments = [
        {
            "role_id": ra.role_id,
            "agent_id": ra.agent_id,
            "agent_type": ra.agent_type,
            "callsign": ra.callsign,
            "department": ra.department,
        }
        for ra in instance.role_assignments.values()
    ]
    return {
        "instance_id": instance_id,
        "assignments": assignments,
        "count": len(assignments),
    }


# ── Bill Actions ─────────────────────────────────────────────────


@router.post("/activate")
async def activate_bill(
    body: ActivateBillRequest, runtime: Any = Depends(get_runtime),
) -> Any:
    """Activate a bill — creates an instance with WQSB role assignments.

    activate() takes a BillDefinition (not a bill_id), so we look up
    the definition first from the registry.
    """
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    defn = br.get_definition(body.bill_id)
    if not defn:
        return JSONResponse(
            {"error": f"Bill '{body.bill_id}' not found"}, status_code=404,
        )
    try:
        from probos.sop.runtime import BillActivationError

        instance = await br.activate(defn, activation_data=body.context)
    except BillActivationError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.error("Bill activation failed: %s", e, exc_info=True)
        return JSONResponse({"error": "Activation failed"}, status_code=500)
    return instance.to_dict()


@router.post("/instances/{instance_id}/cancel")
async def cancel_bill_instance(
    instance_id: str,
    body: CancelBillRequest,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """Cancel an active bill instance.

    cancel() returns bool, not BillInstance. Fetch instance after cancel
    for the response payload.
    """
    br = _get_bill_runtime(runtime)
    if not br:
        return JSONResponse({"error": "Bill System not available"}, status_code=503)
    if not br.cancel(instance_id, reason=body.reason):
        return JSONResponse(
            {"error": "Instance not found or already terminal"}, status_code=404,
        )
    instance = br.get_instance(instance_id)
    if not instance:
        return JSONResponse({"error": "Instance not found"}, status_code=404)
    return instance.to_dict()


# ── Serializers ──────────────────────────────────────────────────


def _serialize_definition(defn: Any) -> dict[str, Any]:
    """Serialize a BillDefinition for the API response.

    Field names match schema.py (AD-618a):
    - BillDefinition: bill, title, description, version, activation
    - BillRole: id, department, count, qualifications
    - BillStep: id, name, role, action, gateway_type, timeout
    """
    return {
        "bill_id": defn.bill,
        "title": defn.title,
        "description": defn.description,
        "version": defn.version,
        "activation": {
            "trigger": defn.activation.trigger,
            "authority": defn.activation.authority,
        }
        if defn.activation
        else None,
        "roles": [
            {
                "role_id": r.id,
                "department": r.department,
                "count": r.count,
                "qualifications": r.qualifications,
            }
            for r in (
                defn.roles.values()
                if isinstance(defn.roles, dict)
                else defn.roles or []
            )
        ],
        "steps": [
            {
                "step_id": s.id,
                "name": s.name,
                "role": s.role,
                "action": s.action,
                "gateway_type": s.gateway_type.value
                if hasattr(s.gateway_type, "value")
                else str(s.gateway_type),
                "timeout": s.timeout,
            }
            for s in (defn.steps or [])
        ],
        "step_count": len(defn.steps or []),
        "role_count": len(defn.roles) if defn.roles else 0,
    }
