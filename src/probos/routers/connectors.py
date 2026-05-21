"""AD-763: M365 connector scoping + scan-config endpoints.

Endpoints:
  - GET  /api/connectors/m365/mail-folders  -> Graph /me/mailFolders (list)
  - GET  /api/connectors/m365/calendars     -> Graph /me/calendars (list)
  - GET  /api/connectors/scan-config        -> current ProactiveScanConfig
  - PUT  /api/connectors/scan-config        -> validate + persist new shape

Auth: requires an authenticated M365 OAuth session (token from runtime token
manager). Discovery endpoints return 401 when no token; 502 when Graph is
unreachable. Scan-config endpoints do not require Graph reachability — they
only mutate the in-memory SystemConfig (per-operator persistence comes with
AD-741 follow-ups).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from probos.config import (
    ProactiveScanCalendarConfig,
    ProactiveScanConfig,
    ProactiveScanInboxConfig,
)
from probos.integrations.m365_connector import GRAPH_BASE_URL, _graph_get

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


def _require_runtime(request: Request) -> Any:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="runtime not attached")
    return runtime


async def _require_token(runtime: Any) -> str:
    tm = getattr(runtime, "_m365_token_manager", None)
    if tm is None:
        logger.info("AD-763: M365 token manager not initialized; returning 401")
        raise HTTPException(status_code=401, detail="M365 not authenticated")
    token = await tm.get_token()
    if not token:
        logger.info("AD-763: M365 token unavailable; returning 401")
        raise HTTPException(status_code=401, detail="M365 token unavailable")
    return token


@router.get("/m365/mail-folders")
async def list_mail_folders(request: Request) -> dict[str, Any]:
    """List the operator's Graph mail folders for the Connectors UI multiselect."""
    runtime = _require_runtime(request)
    token = await _require_token(runtime)

    url = (
        f"{GRAPH_BASE_URL}/me/mailFolders"
        "?$top=100&$select=id,displayName,parentFolderId,totalItemCount"
    )
    status, body = await _graph_get(url, token)
    if status == 401:
        raise HTTPException(status_code=401, detail="Graph rejected token")
    if status == 0 or status >= 500:
        logger.warning("AD-763: mail-folders Graph status=%s; returning 502", status)
        raise HTTPException(status_code=502, detail="Microsoft Graph unreachable")
    if status != 200 or body is None:
        raise HTTPException(status_code=502, detail=f"Graph status {status}")

    items = body.get("value", []) if isinstance(body, dict) else []
    folders = [
        {
            "id": it.get("id", ""),
            "displayName": it.get("displayName", ""),
            "parentFolderId": it.get("parentFolderId"),
            "totalItemCount": it.get("totalItemCount", 0),
        }
        for it in items
        if isinstance(it, dict)
    ]
    return {"folders": folders}


@router.get("/m365/calendars")
async def list_calendars(request: Request) -> dict[str, Any]:
    """List the operator's Graph calendars for the Connectors UI multiselect."""
    runtime = _require_runtime(request)
    token = await _require_token(runtime)

    url = (
        f"{GRAPH_BASE_URL}/me/calendars"
        "?$top=100&$select=id,name,owner,canEdit,isDefaultCalendar"
    )
    status, body = await _graph_get(url, token)
    if status == 401:
        raise HTTPException(status_code=401, detail="Graph rejected token")
    if status == 0 or status >= 500:
        logger.warning("AD-763: calendars Graph status=%s; returning 502", status)
        raise HTTPException(status_code=502, detail="Microsoft Graph unreachable")
    if status != 200 or body is None:
        raise HTTPException(status_code=502, detail=f"Graph status {status}")

    items = body.get("value", []) if isinstance(body, dict) else []
    calendars = [
        {
            "id": it.get("id", ""),
            "name": it.get("name", ""),
            "owner": it.get("owner"),
            "canEdit": bool(it.get("canEdit", False)),
            "isDefaultCalendar": bool(it.get("isDefaultCalendar", False)),
        }
        for it in items
        if isinstance(it, dict)
    ]
    return {"calendars": calendars}


@router.get("/scan-config")
async def get_scan_config(request: Request) -> dict[str, Any]:
    """Return the current ProactiveScanConfig as a JSON-safe dict."""
    runtime = _require_runtime(request)
    cfg = getattr(runtime.config, "proactive_scan", None)
    if cfg is None:
        cfg = ProactiveScanConfig()
    return cfg.model_dump()


@router.put("/scan-config")
async def put_scan_config(request: Request) -> dict[str, Any]:
    """Validate and apply a new ProactiveScanConfig.

    Validation is performed via Pydantic; invalid payloads return 422 with the
    Pydantic error list. The runtime config is mutated in place — persistence
    to ``config/system.yaml`` is operator-driven (out of scope for v1).
    """
    runtime = _require_runtime(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")

    # Allow partial payloads: merge against current shape so callers can PUT just
    # ``{"inbox": {...}}`` without losing the calendar block.
    current = getattr(runtime.config, "proactive_scan", None)
    if current is None:
        current = ProactiveScanConfig()
    merged: dict[str, Any] = current.model_dump()
    if "inbox" in payload:
        if not isinstance(payload["inbox"], dict):
            raise HTTPException(status_code=400, detail="inbox must be an object")
        merged["inbox"] = {**merged.get("inbox", {}), **payload["inbox"]}
    if "calendar" in payload:
        if not isinstance(payload["calendar"], dict):
            raise HTTPException(status_code=400, detail="calendar must be an object")
        merged["calendar"] = {**merged.get("calendar", {}), **payload["calendar"]}

    try:
        new_cfg = ProactiveScanConfig(
            inbox=ProactiveScanInboxConfig(**merged["inbox"]),
            calendar=ProactiveScanCalendarConfig(**merged["calendar"]),
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    # Mutate the live SystemConfig instance. The proactive_scan field is a
    # Pydantic submodel; reassigning it keeps validation invariants intact.
    try:
        runtime.config.proactive_scan = new_cfg
    except Exception as exc:
        logger.error("AD-763: failed to persist scan-config update: %s", exc)
        raise HTTPException(status_code=500, detail="failed to apply config")

    logger.info(
        "AD-763: scan-config updated folders=%d calendars=%d allowlist=%d denylist=%d",
        len(new_cfg.inbox.folders),
        len(new_cfg.calendar.calendar_ids),
        len(new_cfg.inbox.sender_allowlist),
        len(new_cfg.inbox.sender_denylist),
    )
    return new_cfg.model_dump()
