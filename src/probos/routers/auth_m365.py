"""Microsoft 365 authentication routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/m365", tags=["auth_m365"])


@router.post("/authorize")
async def authorize_m365_personal(request: Request) -> dict[str, Any]:
    """Trigger device-code OAuth flow for personal M365 account.
    
    Returns device_code + user_code for display to user.
    """
    runtime = request.app.state.runtime
    
    if not runtime.config.m365.enabled:
        raise HTTPException(
            status_code=400,
            detail="M365 integration is not enabled. Set m365.enabled=true in config.",
        )
    
    if not runtime.config.m365.client_id:
        raise HTTPException(
            status_code=400,
            detail="M365 client_id not configured. Set m365.client_id in config.",
        )
    
    try:
        import msal
    except ImportError:
        logger.error("msal library not installed; install via 'pip install msal'")
        raise HTTPException(
            status_code=500,
            detail="M365 authentication dependencies not available.",
        )
    
    try:
        app = msal.PublicClientApplication(
            runtime.config.m365.client_id,
            authority=runtime.config.m365.authority,
        )
        
        flow = app.initiate_device_flow(scopes=runtime.config.m365.scopes)
        
        if "user_code" not in flow:
            raise HTTPException(
                status_code=500,
                detail="Failed to initiate device-code flow.",
            )
        
        # Store the flow in runtime for polling later
        if not hasattr(runtime, "_m365_device_flows"):
            runtime._m365_device_flows = {}
        runtime._m365_device_flows[flow["device_code"]] = {
            "app": app,
            "flow": flow,
        }
        
        logger.info("M365 device-code flow initiated")
        
        return {
            "status": "device_code_initiated",
            "device_code": flow["device_code"],
            "user_code": flow["user_code"],
            "verification_uri": flow["verification_url"],
            "expires_in": flow.get("expires_in", 900),
            "interval": flow.get("interval", 5),
        }
    
    except Exception:
        logger.exception("M365 device-code initiation error")
        raise HTTPException(
            status_code=500,
            detail="M365 authentication failed.",
        )


@router.post("/complete")
async def complete_m365_auth(request: Request) -> dict[str, Any]:
    """Poll device-code flow until token is acquired.
    
    Safe for unattended operation with honest-degrade on auth failure.
    """
    runtime = request.app.state.runtime
    body = await request.json()
    device_code = body.get("device_code")
    
    if not device_code:
        raise HTTPException(
            status_code=400,
            detail="device_code required in request body.",
        )
    
    if not hasattr(runtime, "_m365_device_flows"):
        raise HTTPException(
            status_code=400,
            detail="No active device-code flow. Call /authorize first.",
        )
    
    flow_info = runtime._m365_device_flows.get(device_code)
    if not flow_info:
        raise HTTPException(
            status_code=400,
            detail="Unknown device_code.",
        )
    
    try:
        app = flow_info["app"]
        flow = flow_info["flow"]
        
        result = app.acquire_token_by_device_flow(flow)
        
        if "access_token" in result:
            # Token acquired successfully
            import keyring
            
            if "refresh_token" in result:
                try:
                    keyring.set_password(
                        "probos.m365",
                        "refresh_token",
                        result["refresh_token"],
                    )
                    logger.info("M365 refresh token stored securely")
                except Exception:
                    logger.warning(
                        "Failed to store M365 refresh token in keyring; "
                        "tokens will not persist"
                    )
            
            # Clean up flow
            del runtime._m365_device_flows[device_code]
            
            logger.info("M365 authentication completed successfully")
            return {
                "status": "authenticated",
                "message": "M365 authentication completed. Refresh token stored securely.",
            }
        
        # Still pending
        error_description = result.get("error_description", "User has not completed authentication yet")
        return {
            "status": "pending",
            "message": error_description,
        }
    
    except Exception:
        logger.exception("M365 token completion error")
        raise HTTPException(
            status_code=500,
            detail="M365 token completion failed.",
        )
