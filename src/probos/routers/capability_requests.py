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
        # AD-1154: the action shape for kind="action"; None for every other
        # kind. Without it the Captain sees a bare ``target`` and nothing else.
        "payload": req.payload,
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
    standing = await _maybe_issue_standing_rule(runtime, decided, req)
    return {"request": _serialize(decided), "standing_rule": standing}


async def _maybe_issue_standing_rule(
    runtime: Any,
    decided: CapabilityRequest,
    req: CapabilityRequestDecideRequest,
) -> dict[str, Any] | None:
    """AD-1154: convert an approval into a scoped, expiring standing rule.

    Returns the issued rule, or ``None`` when one was not issued for any reason.
    Honest-degrade throughout — a missing store, a disabled flag or a failed
    write yields ``None`` with HTTP 200, never a 500. The decision itself is
    already durably recorded by ``decide()``; failing the whole request because
    an *optional* convenience could not be granted would discard it.

    Deliberately narrow, in four ways:

    * Only ``kind == "action"`` — ``grant`` / ``install`` / ``build`` have no
      action shape to scope a rule to, so ``grant_standing`` is logged and
      ignored rather than rejected.
    * Only on ``approve=True``. A denial issues nothing even when
      ``grant_standing`` is set.
    * Only when ``approval_inbox.standing_rules_enabled`` is on.
    * TTL clamped to ``standing_rule_max_ttl_hours``; omitted TTL falls back to
      ``standing_rule_default_ttl_hours``, itself clamped, so an operator whose
      default exceeds their max still gets the max rather than a 422.

    It does NOT re-execute the parked action and does NOT re-dispatch the
    originating work item: the recorded browser session is almost certainly
    reaped (session TTL 1800s vs human latency), and re-running the agentic loop
    from a REST handler would put an unbudgeted LLM run behind a button.
    """
    if not req.grant_standing:
        return None
    if decided.kind != "action":
        logger.info(
            "AD-1154: grant_standing ignored for capability request %s — kind "
            "'%s' has no action shape to scope a standing rule to; the "
            "decision itself was recorded normally",
            decided.id[:12],
            decided.kind,
        )
        return None
    if not req.approve:
        logger.info(
            "AD-1154: grant_standing ignored for denied request %s — a denial "
            "never issues a standing rule",
            decided.id[:12],
        )
        return None

    config = getattr(getattr(runtime, "config", None), "approval_inbox", None)
    if not getattr(config, "standing_rules_enabled", False):
        logger.info(
            "AD-1154: grant_standing requested for %s but "
            "approval_inbox.standing_rules_enabled is off; the approval stands "
            "and no durable privilege was granted",
            decided.id[:12],
        )
        return None

    store = getattr(runtime, "action_approval_store", None)
    payload = decided.payload
    if store is None or type(payload) is not dict:
        logger.warning(
            "AD-1154: cannot issue a standing rule for %s — %s. The approval "
            "itself is recorded; the Captain will be asked again next run",
            decided.id[:12],
            "no action-approval store is wired" if store is None
            else "the request carries no decoded action payload",
        )
        return None

    max_hours = int(getattr(config, "standing_rule_max_ttl_hours", 168))
    default_hours = int(getattr(config, "standing_rule_default_ttl_hours", 24))
    requested = req.standing_ttl_hours
    hours = default_hours if requested is None else int(requested)
    hours = max(1, min(hours, max_hours))

    try:
        approval = await store.issue_approval(
            decided.agent_id,
            str(payload.get("tool_id", "")),
            str(payload.get("action", "")),
            scope_key=str(payload.get("scope_key", "")),
            ttl_seconds=hours * 3600.0,
            reason=req.reason,
            issued_by="captain",
        )
    except Exception:
        logger.warning(
            "AD-1154: issuing a standing rule for %s failed; the approval "
            "itself is recorded and the Captain will be asked again next run",
            decided.id[:12],
            exc_info=True,
        )
        return None
    return {
        "id": approval.id,
        "agent_id": approval.agent_id,
        "tool_id": approval.tool_id,
        "action": approval.action,
        "scope_key": approval.scope_key,
        "issued_at": approval.issued_at,
        "expires_at": approval.expires_at,
    }
