"""ProbOS API — Identity & DID routes (AD-441)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

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
