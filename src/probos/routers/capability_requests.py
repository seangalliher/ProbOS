"""ProbOS API — Capability-request decision surface (AD-857).

Thin router exposing the pending capability requests filed by agents (the
BLOCKED -> request -> approve/deny loop) and the Captain's decision endpoint.
Backed by ``runtime.capability_request_store`` (AD-853). The store owns
persistence; this router owns the pending-state guard and serialization.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequest
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/capability-requests", tags=["capability-requests"])


def _serialize(req: CapabilityRequest) -> dict[str, Any]:
    """Serialize a CapabilityRequest dataclass to a JSON-safe dict.

    The dataclass has no ``to_dict()``; the field set is built explicitly so
    the wire shape is stable and the HXI card can read ``work_item_id`` (the
    DECIDED event omits it — AD-857 correction #3).
    """
    return {
        "id": req.id,
        "agent_id": req.agent_id,
        "kind": req.kind,
        "target": req.target,
        "rationale": req.rationale,
        "work_item_id": req.work_item_id,
        "status": req.status,
        "created_at": req.created_at,
        "decided_at": req.decided_at,
        "decided_by": req.decided_by,
        "decision_reason": req.decision_reason,
    }


@router.get("")
async def list_capability_requests(
    status: str = "pending",
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-857: List capability requests (pending by default).

    Only the pending view is served today; the ``status`` query param is
    accepted for forward-compatibility but anything other than ``pending``
    returns an empty list (no other view is built in this AD).
    """
    if not runtime.capability_request_store:
        raise HTTPException(status_code=503, detail="capability request store not available")
    if status != "pending":
        return {"requests": [], "status": status}
    pending = await runtime.capability_request_store.list_pending()
    return {"requests": [_serialize(r) for r in pending], "status": "pending"}


@router.post("/{request_id}/decide")
async def decide_capability_request(
    request_id: str,
    req: CapabilityRequestDecideRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-857: Approve or deny a pending capability request.

    Unknown id -> 404. Already-decided (non-pending) -> 400. The store's
    ``decide()`` has no already-decided guard, so the pending check is owned
    here (AD-857 correction #2).
    """
    if not runtime.capability_request_store:
        raise HTTPException(status_code=503, detail="capability request store not available")
    store = runtime.capability_request_store
    existing = await store.get(request_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="capability request not found")
    if existing.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"capability request already decided (status={existing.status})",
        )
    decided = await store.decide(
        request_id, req.approve, reason=req.reason, decided_by="captain"
    )
    if decided is None:  # pragma: no cover - guarded above, defensive only
        raise HTTPException(status_code=404, detail="capability request not found")
    return {"request": _serialize(decided)}
