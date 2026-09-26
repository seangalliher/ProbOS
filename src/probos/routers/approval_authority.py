"""AD-1213 (#1170): the Captain's approval-authority controls.

The Captain's two expiring records, which widen who may decide a capability or
skill request:

* ``PUT`` / ``DELETE /delegation`` -- the First Officer delegation. With no
  live delegation the First Officer decides nothing.
* ``PUT`` / ``DELETE /availability`` -- the Captain-unavailable mark, which
  zeroes the grace period while it lasts.

``GET /state`` shows both, and the grace period. Each record needs a duration
in hours, clamped to its configured ceiling, so neither can outlive it (open
question 2). Every route is operator-scoped (``require_crew_scope``) and answers
503 while the store is absent (the feature is off) or does not answer. Every
change is audited as ``approval_authority``; the audit is log-and-degrade, so
the Captain's own act is never refused for want of an audit log.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from probos.approval_authority import (
    CAPTAIN_UNAVAILABLE,
    FIRST_OFFICER_DELEGATION,
    ApprovalAuthorityUnavailable,
)
from probos.delegated_approvals import AUTHORITY_AUDIT_CATEGORY
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approval-authority", tags=["approval-authority"])

_CAPTAIN = "captain"
_NOT_ENABLED = "approval authority is not enabled"
_UNREADABLE = "approval authority could not be read"
_REFUSED = "approval authority record refused: invalid duration, issuer or reason"


class AuthorityGrantBody(BaseModel):
    """How long a delegation or an unavailability mark lasts, and why."""

    model_config = ConfigDict(extra="forbid")

    hours: int = Field(ge=1, le=8760)
    reason: str = Field(default="", max_length=500)


def _store(runtime: Any) -> Any:
    store = getattr(runtime, "approval_authority_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail=_NOT_ENABLED)
    return store


def _record(record: Any) -> dict[str, Any] | None:
    return dataclasses.asdict(record) if record is not None else None


def _unreadable(action: str) -> HTTPException:
    logger.warning(
        "AD-1213: the approval-authority store could not answer the Captain's %s; nothing "
        "changed and the route answers 503",
        action,
    )
    return HTTPException(status_code=503, detail=_UNREADABLE)


def _audit(
    runtime: Any, action: str, *, record_id: str | None, expires_at: float | None,
    revoked: int | None, reason: str,
) -> None:
    """Append the Captain's change to the audit log; log-and-degrade, never refuse."""
    audit_log = getattr(runtime, "audit_log", None)
    if audit_log is None:
        logger.warning(
            "AD-1213: the Captain's %s is in effect but not audited: no audit log is wired",
            action,
        )
        return
    detail = {
        "v": 1,
        "action": action,
        "record_id": record_id,
        "expires_at": expires_at,
        "revoked": revoked,
        "reason": reason,
    }
    try:
        audit_log.append(
            category=AUTHORITY_AUDIT_CATEGORY,
            detail=json.dumps(detail, sort_keys=True, separators=(",", ":")),
        )
    except Exception:
        logger.warning(
            "AD-1213: auditing the Captain's %s failed; the change itself stands",
            action, exc_info=True,
        )


async def _issue(
    runtime: Any, kind: str, body: AuthorityGrantBody, ceiling_field: str, action: str,
) -> dict[str, Any]:
    store = _store(runtime)
    granted = min(body.hours, getattr(runtime.config.approval_inbox, ceiling_field))
    try:
        record = await store.issue(
            kind, ttl_seconds=granted * 3600, issued_by=_CAPTAIN, reason=body.reason,
        )
    except ApprovalAuthorityUnavailable:
        raise _unreadable(action) from None
    except ValueError:
        raise HTTPException(status_code=422, detail=_REFUSED) from None
    _audit(
        runtime, action, record_id=record.id, expires_at=record.expires_at,
        revoked=None, reason=body.reason,
    )
    return {
        "record": _record(record),
        "requested_hours": body.hours,
        "granted_hours": granted,
        "clamped": granted < body.hours,
    }


async def _revoke(runtime: Any, kind: str, action: str) -> dict[str, int]:
    store = _store(runtime)
    try:
        count = await store.revoke(kind, revoked_by=_CAPTAIN)
    except ApprovalAuthorityUnavailable:
        raise _unreadable(action) from None
    _audit(runtime, action, record_id=None, expires_at=None, revoked=count, reason="")
    return {"revoked": count}


@router.get("/state", dependencies=[Depends(require_crew_scope)])
async def get_approval_authority_state(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """The live First Officer delegation, the Captain-unavailable mark and the grace period."""
    store = _store(runtime)
    inbox = runtime.config.approval_inbox
    try:
        delegation = store.live(FIRST_OFFICER_DELEGATION)
        unavailable = store.live(CAPTAIN_UNAVAILABLE)
    except ApprovalAuthorityUnavailable:
        raise _unreadable("state read") from None
    return {
        "enabled": inbox.delegated_approvals_enabled is True,
        "approval_grace_seconds": inbox.approval_grace_seconds,
        "first_officer_delegation": _record(delegation),
        "captain_unavailable": _record(unavailable),
        "now": time.time(),
    }


@router.put("/delegation", dependencies=[Depends(require_crew_scope)])
async def delegate_to_first_officer(
    body: AuthorityGrantBody, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Delegate approvals to the First Officer for ``hours``, clamped to the configured ceiling."""
    return await _issue(
        runtime, FIRST_OFFICER_DELEGATION, body, "first_officer_delegation_max_ttl_hours",
        "delegate",
    )


@router.delete("/delegation", dependencies=[Depends(require_crew_scope)])
async def revoke_first_officer_delegation(runtime: Any = Depends(get_runtime)) -> dict[str, int]:
    """Revoke any live First Officer delegation; the First Officer decides nothing from now on."""
    return await _revoke(runtime, FIRST_OFFICER_DELEGATION, "revoke_delegation")


@router.put("/availability", dependencies=[Depends(require_crew_scope)])
async def mark_captain_unavailable(
    body: AuthorityGrantBody, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Mark the Captain unavailable for ``hours`` (clamped): the grace period is zero until it lapses."""
    return await _issue(
        runtime, CAPTAIN_UNAVAILABLE, body, "captain_unavailable_max_ttl_hours",
        "mark_unavailable",
    )


@router.delete("/availability", dependencies=[Depends(require_crew_scope)])
async def mark_captain_available(runtime: Any = Depends(get_runtime)) -> dict[str, int]:
    """Clear the Captain-unavailable mark: the configured grace period applies again."""
    return await _revoke(runtime, CAPTAIN_UNAVAILABLE, "mark_available")
