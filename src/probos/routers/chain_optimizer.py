"""ProbOS API — Cognitive Chain Optimizer routes (AD-659 v1).

v1 exposes proposal listing and Captain decision recording. Application
of an approved proposal is NOT implemented — the underlying service's
apply_proposal() raises NotImplementedError.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chain-optimizer", tags=["chain-optimizer"])


class DecisionRequest(BaseModel):
    decision: str  # "approve" | "reject"
    actor: str = "captain"


@router.get("/proposals")
async def list_proposals(
    include_decided: bool = False,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-659 v1: List pending optimization proposals.

    Args:
        include_decided: If True, returns ALL proposals including
            already-approved/rejected ones. Default False = pending only.
    """
    optimizer = getattr(runtime, "chain_optimizer", None)
    if optimizer is None:
        return {"proposals": [], "enabled": False}
    if include_decided:
        proposals = optimizer.pending_proposals
    else:
        proposals = optimizer.list_pending()
    return {
        "proposals": [p.to_dict() for p in proposals],
        "enabled": True,
    }


@router.post("/proposals/{proposal_id}/decide")
async def decide_proposal(
    proposal_id: str,
    req: DecisionRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-659 v1: Record Captain's decision on a proposal.

    v1 records the decision in-memory only. Approved proposals are NOT
    applied — apply_proposal() raises NotImplementedError until AD-659b.
    """
    optimizer = getattr(runtime, "chain_optimizer", None)
    if optimizer is None:
        raise HTTPException(status_code=503, detail="ChainOptimizer not enabled")
    if req.decision not in ("approve", "reject"):
        raise HTTPException(
            status_code=400,
            detail="decision must be 'approve' or 'reject'",
        )
    proposal = optimizer.decide(proposal_id, req.decision, actor=req.actor)
    if proposal is None:
        raise HTTPException(
            status_code=404, detail=f"proposal {proposal_id} not found"
        )
    return {
        "status": "recorded",
        "applied": False,  # explicit v1 limitation
        "proposal": proposal.to_dict(),
    }
