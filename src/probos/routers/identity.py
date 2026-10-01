"""ProbOS API — Identity & DID routes (AD-441), and the ship key's Captain-only controls (AD-1196).

AD-1196 adds four routes under ``/api/identity/keys``. ``GET`` reports the key
binding's status, key history and DID document -- public data only, the same
data ``export_chain`` already serves to peers. ``POST /rotate``,
``POST /recovery`` (prepare without ``authorization``, apply with it) and
``POST /reinception`` change the ship's cryptographic identity. Every key route
is operator-scoped (``require_crew_scope``) and answers 503 while the binding
is not armed. The three mutating routes then answer 403
``identity_keys_require_token`` while no crew-scope token is configured:
``require_crew_scope`` is a pass-through with an empty token and a confirm
literal is not authentication (AD-731a-1's rule). That refusal comes before any
key action and any audit entry. Each action is audited as ``identity_keys``
(log-and-degrade), never with key material.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from probos.identity_keys import (
    IdentityKeyStateError,
    IdentityKeyUnavailable,
    KeyEventInvalid,
    RecoveryAuthorizationInvalid,
)
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/identity", tags=["identity"])


@router.get("/ledger")
async def get_identity_ledger(runtime: Any = Depends(get_runtime)) -> Any:
    """Return the Identity Ledger status and chain verification."""
    if not runtime.identity_registry:
        return JSONResponse({"error": "Identity registry not available"}, status_code=503)

    valid, message = await runtime.identity_registry.verify_chain()
    chain = await runtime.identity_registry.export_chain()

    return {
        "valid": valid,
        "message": message,
        "block_count": len(chain),
        "chain": chain,
    }


@router.get("/certificates")
async def list_birth_certificates(runtime: Any = Depends(get_runtime)) -> Any:
    """Return all birth certificates on this ship."""
    if not runtime.identity_registry:
        return JSONResponse({"error": "Identity registry not available"}, status_code=503)

    certs = runtime.identity_registry.get_all()
    return {
        "count": len(certs),
        "certificates": [c.to_verifiable_credential() for c in certs],
    }


@router.get("/ship")
async def get_ship_identity(runtime: Any = Depends(get_runtime)) -> Any:
    """Return the ship's birth certificate and commissioning data."""
    if not runtime.identity_registry:
        return JSONResponse({"error": "Identity registry not available"}, status_code=503)

    cert = runtime.identity_registry.get_ship_certificate()
    if not cert:
        return JSONResponse({"error": "Ship not commissioned"}, status_code=404)

    return {
        "ship_did": cert.ship_did,
        "instance_id": cert.instance_id,
        "vessel_name": cert.vessel_name,
        "commissioned_at": cert.commissioned_at,
        "birth_certificate": cert.to_verifiable_credential(),
    }


@router.get("/assets")
async def list_asset_tags(runtime: Any = Depends(get_runtime)) -> Any:
    """Return all asset tags for infrastructure and utility agents."""
    if not runtime.identity_registry:
        return JSONResponse({"error": "Identity registry not available"}, status_code=503)

    tags = runtime.identity_registry.get_asset_tags()
    return {
        "count": len(tags),
        "assets": [t.to_dict() for t in tags],
    }


# ── AD-1196: the ship key's Captain-only controls ─────────────────────

_KEYS_AUDIT_CATEGORY = "identity_keys"
_NOT_ENABLED = "identity key binding is not enabled"
_TOKEN_REQUIRED = "identity_keys_require_token"
# What a refused key action maps to; anything else (a database failure) propagates as a 500.
_REFUSALS = (IdentityKeyUnavailable, IdentityKeyStateError, KeyEventInvalid, RecoveryAuthorizationInvalid, ValueError)


class KeyRotateBody(BaseModel):
    """A key rotation; the note is kept in the audit log."""

    model_config = ConfigDict(extra="forbid")

    note: str = Field(default="", max_length=500)


class KeyRecoveryBody(BaseModel):
    """A recovery: prepared without ``authorization``, applied with the Captain's offline signature."""

    model_config = ConfigDict(extra="forbid")

    reason: Literal["lost", "compromised"]
    compromised_after_index: int | None = Field(default=None, ge=0)
    next_recovery_public_key: str = Field(default="", max_length=64)
    authorization: str = Field(default="", max_length=4096)
    note: str = Field(default="", max_length=500)


class KeyReinceptionBody(BaseModel):
    """A re-inception: a new key root, allowed only while no recovery key is committed."""

    model_config = ConfigDict(extra="forbid")

    reason: Literal["lost", "compromised"]
    compromised_after_index: int | None = Field(default=None, ge=0)
    confirm: Literal["abandon-key-continuity"]
    note: str = Field(default="", max_length=500)


def _binding(runtime: Any) -> Any:
    binding = getattr(runtime, "identity_key_binding", None)
    if binding is None:
        raise HTTPException(status_code=503, detail=_NOT_ENABLED)
    return binding


async def _key_action_binding(runtime: Any = Depends(get_runtime)) -> Any:
    """The binding for a mutating key route: 503 while unarmed, then 403 while no token is configured."""
    binding = _binding(runtime)
    if not runtime.config.auth.crew_scope_token:
        raise HTTPException(status_code=403, detail=_TOKEN_REQUIRED)
    return binding


def _refused(action: str, exc: Exception) -> HTTPException:
    """Map a refused key action to its status; the binding's messages carry no key material."""
    if isinstance(exc, IdentityKeyUnavailable):
        status = 503
    elif isinstance(exc, RecoveryAuthorizationInvalid):
        status = 403
    elif isinstance(exc, (IdentityKeyStateError, KeyEventInvalid)):
        status = 409
    else:
        status = 422
    logger.warning(
        "AD-1196: the Captain's identity key %s was refused (%d: %s); no key event was recorded",
        action, status, exc,
    )
    return HTTPException(status_code=status, detail=str(exc))


def _audit(runtime: Any, action: str, *, kid: str, block_index: int | None, reason: str, note: str) -> None:
    """Append the Captain's key action to the audit log; log-and-degrade, never refuse. No key material."""
    audit_log = getattr(runtime, "audit_log", None)
    if audit_log is None:
        logger.warning(
            "AD-1196: the Captain's identity key %s took effect but is not audited: no audit log is wired",
            action,
        )
        return
    detail = {
        "v": 1,
        "action": action,
        "did": kid.partition("#")[0],  # a kid is "<did>#key-<fingerprint>" (identity_keys.key_id)
        "kid": kid,
        "block_index": block_index,
        "reason": reason,
        "note": note,
    }
    try:
        audit_log.append(
            category=_KEYS_AUDIT_CATEGORY, detail=json.dumps(detail, sort_keys=True, separators=(",", ":")),
        )
    except Exception:
        logger.warning(
            "AD-1196: auditing the Captain's identity key %s failed; the action itself stands",
            action, exc_info=True,
        )


@router.get("/keys", dependencies=[Depends(require_crew_scope)])
async def get_identity_keys(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """The ship key binding's status, key history and DID document. Public data only."""
    return await _binding(runtime).status()


@router.post("/keys/rotate", dependencies=[Depends(require_crew_scope)])
async def rotate_identity_key(
    body: KeyRotateBody,
    runtime: Any = Depends(get_runtime),
    binding: Any = Depends(_key_action_binding),
) -> dict[str, Any]:
    """Rotate the ship key: authorised by the outgoing key, possession proven by the incoming one."""
    try:
        result = await binding.rotate()
    except _REFUSALS as exc:
        raise _refused("rotation", exc) from None
    _audit(runtime, "rotate", kid=result["kid"], block_index=result["block_index"], reason="", note=body.note)
    return result


@router.post("/keys/recovery", dependencies=[Depends(require_crew_scope)])
async def recover_identity_key(
    body: KeyRecoveryBody,
    runtime: Any = Depends(get_runtime),
    binding: Any = Depends(_key_action_binding),
) -> dict[str, Any]:
    """Replace a lost or compromised key under the Captain's recovery key.

    Without ``authorization`` it prepares: the replacement key is created and the
    exact payload to sign offline (``sign_recovery_authorization``) is returned.
    With ``authorization`` it verifies that signature and anchors the recovery.
    """
    arguments: dict[str, Any] = {
        "reason": body.reason,
        "compromised_after_index": body.compromised_after_index,
        "next_recovery_public_key": body.next_recovery_public_key,
    }
    action = "recovery_apply" if body.authorization else "recovery_prepare"
    try:
        if body.authorization:
            result = await binding.apply_recovery(authorization=body.authorization, **arguments)
        else:
            result = await binding.prepare_recovery(**arguments)
    except _REFUSALS as exc:
        raise _refused("recovery", exc) from None
    _audit(
        runtime, action, kid=result["kid"], block_index=result.get("block_index"), reason=body.reason,
        note=body.note,
    )
    return result


@router.post("/keys/reinception", dependencies=[Depends(require_crew_scope)])
async def reincept_identity_key(
    body: KeyReinceptionBody,
    runtime: Any = Depends(get_runtime),
    binding: Any = Depends(_key_action_binding),
) -> dict[str, Any]:
    """Start a new key root while no recovery key is committed; key continuity is reported broken there."""
    try:
        result = await binding.reincept(reason=body.reason, compromised_after_index=body.compromised_after_index)
    except _REFUSALS as exc:
        raise _refused("re-inception", exc) from None
    _audit(
        runtime, "reinception", kid=result["kid"], block_index=result["block_index"], reason=body.reason,
        note=body.note,
    )
    return result
