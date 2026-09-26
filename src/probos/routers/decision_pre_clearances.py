"""AD-1214 (#1171): the Captain's decision pre-clearances.

A pre-clearance stops the Captain's notification for one exact class of
delegated decision (``probos.decision_pre_clearance``); it confers no authority.

* ``GET`` -- the live pre-clearances, each with its exact scope and expiry.
* ``POST`` -- accept a notification's pre-clear offer. The body carries only
  the opaque offer id; the server resolves it to the exact class it froze when
  it wrote the notification, so a client can neither author nor widen a scope.
  The duration defaults to the offer's hours and is clamped to
  ``decision_pre_clearance_max_ttl_hours``.
* ``DELETE /{record_id}`` -- revoke one, and that class notifies again.
  Revoking only narrows, so it is allowed even while the feature is switched
  off.

Every route is operator-scoped (``require_crew_scope``) and answers 503 while
the store is absent (the feature is off) or does not answer. Every change is
audited as ``decision_pre_clearance``; the audit is log-and-degrade, so the
Captain's own act is never refused for want of an audit log.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from probos.decision_pre_clearance import (
    PRE_CLEARANCE_AUDIT_CATEGORY,
    PreClearanceUnavailable,
    describe_scope,
)
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/decision-pre-clearances", tags=["decision-pre-clearances"])

_CAPTAIN = "captain"
_OFF = "decision pre-clearance is switched off"
_SWITCHED_OFF = "decision pre-clearance is switched off on this vessel"
_UNREADABLE = "decision pre-clearances could not be read"
_NO_OFFER = "no pre-clear offer has that id; the next decision of that class offers it again"
_NO_RECORD = "no live pre-clearance has that id"
_REFUSED = "pre-clearance refused: invalid duration or reason"
_BAD_ID = "a pre-clearance id is a lowercase uuid4"
_UUID4_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


class PreClearBody(BaseModel):
    """Accept one pre-clear offer: its opaque id, an optional duration, and why."""

    model_config = ConfigDict(extra="forbid")

    offer_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    hours: int | None = Field(default=None, ge=1, le=8760)
    reason: str = Field(default="", max_length=500)


def _store(runtime: Any) -> Any:
    store = getattr(runtime, "decision_pre_clearance_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail=_OFF)
    return store


def _switched_off(runtime: Any) -> bool:
    """Both flags, re-read live: with either off, no new pre-clearance is created."""
    inbox = runtime.config.approval_inbox
    return not (
        inbox.delegated_approvals_enabled is True and inbox.decision_pre_clearance_enabled is True
    )


def _record(record: Any) -> dict[str, Any]:
    return {**dataclasses.asdict(record), "scope": describe_scope(record.key)}


def _unreadable(action: str) -> HTTPException:
    logger.warning(
        "AD-1214: the decision pre-clearance store could not answer the Captain's %s; nothing "
        "changed and the route answers 503",
        action,
    )
    return HTTPException(status_code=503, detail=_UNREADABLE)


def _audit(runtime: Any, action: str, **fields: Any) -> None:
    """Append the Captain's change to the audit log; log-and-degrade, never refuse."""
    audit_log = getattr(runtime, "audit_log", None)
    if audit_log is None:
        logger.warning(
            "AD-1214: the Captain's %s is in effect but not audited: no audit log is wired",
            action,
        )
        return
    detail = {"v": 1, "action": action, **fields}
    try:
        audit_log.append(
            category=PRE_CLEARANCE_AUDIT_CATEGORY,
            detail=json.dumps(detail, sort_keys=True, separators=(",", ":")),
        )
    except Exception:
        logger.warning(
            "AD-1214: auditing the Captain's %s failed; the change itself stands",
            action, exc_info=True,
        )


@router.get("", dependencies=[Depends(require_crew_scope)])
async def list_decision_pre_clearances(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """The live pre-clearances, oldest first, each with its exact scope and expiry."""
    store = _store(runtime)
    inbox = runtime.config.approval_inbox
    try:
        live = store.live()
    except PreClearanceUnavailable:
        raise _unreadable("list") from None
    return {
        "enabled": not _switched_off(runtime),
        "default_ttl_hours": inbox.decision_pre_clearance_default_ttl_hours,
        "max_ttl_hours": inbox.decision_pre_clearance_max_ttl_hours,
        "pre_clearances": [_record(record) for record in live],
        "now": time.time(),
    }


@router.post("", status_code=201, dependencies=[Depends(require_crew_scope)])
async def create_decision_pre_clearance(
    body: PreClearBody, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Accept a pre-clear offer: pre-clear exactly its class for the offer's hours, clamped."""
    store = _store(runtime)
    if _switched_off(runtime):
        raise HTTPException(status_code=409, detail=_SWITCHED_OFF)
    try:
        offered = store.offered(body.offer_id)
    except PreClearanceUnavailable:
        raise _unreadable("pre-clear") from None
    if offered is None:
        raise HTTPException(status_code=404, detail=_NO_OFFER)
    key, offer_hours = offered
    requested = body.hours or offer_hours
    granted = min(requested, runtime.config.approval_inbox.decision_pre_clearance_max_ttl_hours)
    try:
        record = await store.issue(
            key, ttl_seconds=granted * 3600, issued_by=_CAPTAIN, reason=body.reason,
        )
    except PreClearanceUnavailable:
        raise _unreadable("pre-clear") from None
    except ValueError:
        raise HTTPException(status_code=422, detail=_REFUSED) from None
    _audit(
        runtime, "pre_clear", record_id=record.id, expires_at=record.expires_at,
        offer_id=body.offer_id, requested_hours=requested, granted_hours=granted,
        key=dataclasses.asdict(key), reason=body.reason,
    )
    return {
        "pre_clearance": _record(record),
        "requested_hours": requested,
        "granted_hours": granted,
        "clamped": granted < requested,
    }


@router.delete("/{record_id}", dependencies=[Depends(require_crew_scope)])
async def revoke_decision_pre_clearance(
    record_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, int]:
    """Revoke one pre-clearance: its class notifies the Captain again. Allowed while switched off."""
    store = _store(runtime)
    if not _UUID4_RE.fullmatch(record_id):
        raise HTTPException(status_code=422, detail=_BAD_ID)
    try:
        count = await store.revoke(record_id, revoked_by=_CAPTAIN)
    except PreClearanceUnavailable:
        raise _unreadable("revoke") from None
    if count == 0:
        raise HTTPException(status_code=404, detail=_NO_RECORD)
    _audit(runtime, "revoke_pre_clearance", record_id=record_id, revoked=count)
    return {"revoked": count}
