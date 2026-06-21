"""ProbOS API — Skill-request decision surface (AD-908).

Thin router exposing the crew skill-acquisition requests filed by (or for)
agents and the Captain's approve/deny decision endpoint, plus the AD-907
``begin-training`` link endpoint and a per-agent history read. Backed by
``runtime.skill_request_store`` (AD-906). The store owns persistence and the
state machine; this router owns the request-state guards and serialization.

Structurally mirrors ``routers/capability_requests.py``. The entire surface is
gated dark: when ``config.skill_requests.enabled`` is False no store is
constructed and the mutating endpoints return 503.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from probos.api_models import SkillRequestDecideRequest, SkillRequestFileRequest
from probos.routers.deps import get_runtime
from probos.skill_request import SkillRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skill-requests", tags=["skill-requests"])


class _BeginTrainingBody(BaseModel):
    """Request body linking an approved skill request to a simulation."""
    simulation_id: str


def _serialize(req: SkillRequest) -> dict[str, Any]:
    """Serialize a SkillRequest dataclass to a JSON-safe dict.

    The dataclass has no ``to_dict()``; the field set is built explicitly so
    the wire shape is stable and the HXI card can read the training-linkage
    fields (``linked_simulation_id`` / ``pre_metric`` / ``post_metric``) that
    the lifecycle events omit.
    """
    return {
        "id": req.id,
        "agent_id": req.agent_id,
        "skill_id": req.skill_id,
        "skill_label": req.skill_label,
        "source": req.source,
        "justification": req.justification,
        "status": req.status,
        "linked_simulation_id": req.linked_simulation_id,
        "created_at": req.created_at,
        "decided_at": req.decided_at,
        "decided_by": req.decided_by,
        "decision_reason": req.decision_reason,
        "pre_metric": req.pre_metric,
        "post_metric": req.post_metric,
    }


@router.post("")
async def file_skill_request(
    req: SkillRequestFileRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-908: File a new skill-acquisition request.

    503 when the skill-request store is unavailable (cluster disabled).
    """
    if not runtime.skill_request_store:
        raise HTTPException(status_code=503, detail="skill request store not available")
    filed = await runtime.skill_request_store.file_request(
        req.agent_id,
        req.skill_id,
        skill_label=req.skill_label,
        source=req.source,
        justification=req.justification,
    )
    return {"request": _serialize(filed)}


@router.get("")
async def list_skill_requests(
    status: str = "pending",
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-908: List skill requests (pending by default).

    Only the pending view is served today; the ``status`` query param is
    accepted for forward-compatibility but anything other than ``pending``
    returns an empty list (no other view is built in this AD).
    """
    if not runtime.skill_request_store:
        raise HTTPException(status_code=503, detail="skill request store not available")
    if status != "pending":
        return {"requests": [], "status": status}
    pending = await runtime.skill_request_store.list_pending()
    return {"requests": [_serialize(r) for r in pending], "status": "pending"}


@router.post("/{request_id}/decide")
async def decide_skill_request(
    request_id: str,
    req: SkillRequestDecideRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-908: Approve or deny a pending skill request.

    Unknown id -> 404. Already-decided (non-requested) -> 400. The store's
    ``decide()`` has no already-decided guard, so the requested-state check is
    owned here (mirrors AD-857).
    """
    if not runtime.skill_request_store:
        raise HTTPException(status_code=503, detail="skill request store not available")
    store = runtime.skill_request_store
    existing = await store.get(request_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="skill request not found")
    if existing.status != "requested":
        raise HTTPException(
            status_code=400,
            detail=f"skill request already decided (status={existing.status})",
        )
    decided = await store.decide(
        request_id, req.approve, reason=req.reason, decided_by="captain"
    )
    if decided is None:  # pragma: no cover - guarded above, defensive only
        raise HTTPException(status_code=404, detail="skill request not found")
    return {"request": _serialize(decided)}


@router.post("/{request_id}/begin-training")
async def begin_skill_request_training(
    request_id: str,
    body: _BeginTrainingBody,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-908: Link an approved skill request to a holodeck simulation.

    Unknown id -> 404. Non-approved -> 400. Advances the request to
    ``in_training`` with ``linked_simulation_id`` set (AD-907 link half).
    """
    if not runtime.skill_request_store:
        raise HTTPException(status_code=503, detail="skill request store not available")
    store = runtime.skill_request_store
    existing = await store.get(request_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="skill request not found")
    if existing.status != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"skill request is not approved (status={existing.status})",
        )
    updated = await store.begin_training(request_id, body.simulation_id)
    if updated is None:  # pragma: no cover - guarded above, defensive only
        raise HTTPException(status_code=404, detail="skill request not found")
    return {"request": _serialize(updated)}


@router.get("/agent/{agent_id}")
async def list_skill_requests_for_agent(
    agent_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-908: List all skill requests filed for a given agent.

    Honest-degrade: when the store is unavailable, returns an empty list
    rather than 503 so a read-only history view never errors.
    """
    if not runtime.skill_request_store:
        return {"requests": []}
    by_agent = await runtime.skill_request_store.list_by_agent(agent_id)
    return {"requests": [_serialize(r) for r in by_agent]}
